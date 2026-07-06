# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Eval driver, classification, and report encoding for the failure eval (M3.4a).

An out-of-tree observer: a synchronous httpx client (deterministic) driving ONLY the verifier's
public HTTP surface -- /propose-spec for the model path and /verify-only for the corpus
guarantee. It never imports verifier internals, so it adds no trust; it measures the existing
service. Two measurements, never conflated:

  GUARANTEE (deterministic, the only bounds) -- the trusted verifier blocks all 18 M1 bad
  goldens (bad_corpus_false_accept_count MUST be 0) AND accepts all 10 good ones
  (good_corpus_false_reject_count MUST be 0). Either non-zero is a real verifier regression;
  without the good leg, a verifier that rejected EVERYTHING would satisfy the bad-corpus
  bound vacuously and the run would still exit 0 (M3-review finding).

  OBSERVATIONS (statistical, characterize the weak proposer) -- tool-call / json-validity /
  schema|semantic|policy failure / verified-render rates plus the top failing checks. NOT a
  bound: a weak model failing most prompts is the expected outcome. There is no automatic model
  false-accept number -- a chart verified for an unfair-but-real request sits outside the
  verifier claim and needs manual labels (out of scope, POC_SCOPE).

Response bodies decode into LOOSE local structs, never the service models: RenderVerdict.verified
is Literal[True], which msgspec rejects at decode, so decoding a real 200 into the service model
would raise. These structs read only the fields the report needs and ignore the rest (msgspec
ignores unknown keys by default).
"""

import hashlib
import logging
import re
from collections import Counter
from pathlib import Path

import httpx
import msgspec

from bench.prompts import CATEGORIES, Prompt

_LOGGER = logging.getLogger(__name__)

# HTTP status the verifier answers verification outcomes with (a Verdict rides a 200).
_HTTP_OK = 200
# The pin-refusal status: the model proposed a spec for a different dataset than requested.
_HTTP_PIN_MISMATCH = 502
# Any status at or above this is a server/upstream fault (502/503 backend, or a verifier 500).
_HTTP_SERVER_ERR = 500
# app.py's exact pin-mismatch detail string; the only 502 that is a model off-request behavior.
_PIN_MISMATCH_DETAIL = "the model proposed a specification for a different dataset than requested"

_NDIGITS = 4  # rate rounding
_TOP_MODES = 5  # how many top failing checks the report keeps
# Config-scoped only: the harness observes neither the backend device nor its sampling mode
# (greedy temperature 0 is the verifier client's fixed request), so the note asserts no
# device fact -- runs are byte-reproducible per backend (device, config).
_REPRODUCIBILITY = "fixed ordered prompts, greedy client; per backend (device, config)"

# Verdict buckets for a 200 response.
_BUCKET_VERIFIED = "verified"
_BUCKET_SCHEMA = "schema"
_BUCKET_SEMANTIC = "semantic"
_BUCKET_POLICY = "policy"
# Fault buckets for a non-200 response.
_BUCKET_OFF_REQUEST = "off_request"
_BUCKET_UPSTREAM_FAULT = "upstream_fault"
_BUCKET_HARNESS_ERROR = "harness_error"

# Policy check families: units, arbitrary-code, and bar-baseline concerns. Every other verify
# check family is semantic. Today only label.quantitative_units_present can FAIL among these
# (security.no_arbitrary_code is a pass-only affirmation; scale.* is a certificate string), but
# keeping all three is correct by construction -- a future failing policy check buckets right.
_POLICY_FAMILIES = frozenset({"label", "security", "scale"})

# Reply-shape taxonomy over a 200 model reply -- WHY the strict decode gate fails (codex-review
# M3.4b F2). Reproducible per (device, config) from the persisted replies; de-fence rule below.
_SHAPE_FENCED = "fenced"  # the reply carries a ``` fence (a markdown code block)
_SHAPE_BARE_OBJECT = "bare_object"  # no fence; the stripped reply opens with {
_SHAPE_EMPTY = "empty"  # the stripped reply is ""
_SHAPE_OTHER = "other"  # none of the above (prose, a list, a truncated fragment, ...)
# Pulls the first ```-fenced block's body so a fence-wrapped spec can be re-parsed.
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


# --- loose decode structs (subset of each service payload; unknown keys ignored) ------------
class _RespCheck(msgspec.Struct):
    check: str
    status: str


class _RespVerdict(msgspec.Struct):
    verified: bool
    layer: str
    results: tuple[_RespCheck, ...]


class _RespProposeResult(msgspec.Struct):
    model_reply: str
    verdict: _RespVerdict


class _RespProblem(msgspec.Struct):
    detail: str


class _SpecEntry(msgspec.Struct):
    file: str


class _Index(msgspec.Struct):
    bad_specs: tuple[_SpecEntry, ...]
    good_specs: tuple[_SpecEntry, ...]


class _Models(msgspec.Struct):
    id: str


class _ModelList(msgspec.Struct):
    data: tuple[_Models, ...]


# --- report structs (encoded to report.json; all frozen + kw_only) --------------------------
class MetaBlock(msgspec.Struct, frozen=True, kw_only=True):
    """Provenance for the run: the served model, prompt count, categories, reproducibility note."""

    served_model: str | None
    prompt_count: int
    categories: tuple[str, ...]
    reproducibility: str


class GuaranteeBlock(msgspec.Struct, frozen=True, kw_only=True):
    """The deterministic bounds: all 18 bad goldens blocked (false_accept == 0) AND all 10 good
    goldens accepted (false_reject == 0) -- the good leg keeps a reject-everything verifier from
    satisfying the bad bound vacuously (M3-review).

    Each corpus digest pins its IDENTITY (SHA-256 over the sorted filename + content-hash pairs),
    so __main__ rejects a run whose --examples-dir is not the real M1 goldens even when it
    happens to hold same-sized sets of other specs (codex-review M3.4b F1).
    """

    bad_corpus_size: int
    bad_corpus_digest: str
    bad_corpus_false_accept_count: int
    bad_corpus_transport_errors: int
    good_corpus_size: int
    good_corpus_digest: str
    good_corpus_false_reject_count: int
    good_corpus_transport_errors: int


class RateBlock(msgspec.Struct, frozen=True, kw_only=True):
    """Observational rates over the n 200-responses, plus the three non-200 fault counts.

    n = number of 200 responses in this scope; every rate is a count / n. The fault counts are
    non-200 outcomes NOT in n: off_request (a model naming a different dataset -- a model failure
    mode), upstream_fault (backend/verifier infra), harness_error (the harness sent a bad request,
    expected to be 0). n + the three fault counts = the scope's prompt count.
    """

    n: int
    tool_call_rate: float
    json_validity_rate: float
    schema_failure_rate: float
    semantic_failure_rate: float
    policy_failure_rate: float
    verified_render_rate: float
    off_request_count: int
    upstream_fault_count: int
    harness_error_count: int


class FailureMode(msgspec.Struct, frozen=True, kw_only=True):
    """One failing check name and how many 200-verdicts it appeared in."""

    check: str
    count: int


class ReplyShapeBlock(msgspec.Struct, frozen=True, kw_only=True):
    """Reply-shape taxonomy over the n 200-responses -- why the strict decode gate fails.

    Partitions each 200 reply by surface form (fenced / bare_object / empty / other) and counts
    defenced_json_valid: replies that parse as JSON AFTER the first ```-fence is stripped. It
    isolates fence-wrapping (syntactic) from deeper malformation. Reproducible per (device, config)
    from the replies in details.jsonl via the de-fence rule in bench/README.md.
    """

    n: int
    fenced: int
    bare_object: int
    empty: int
    other: int
    defenced_json_valid: int


class ObservationsBlock(msgspec.Struct, frozen=True, kw_only=True):
    """The statistical picture: overall + per-category rates, top failing checks, reply shape."""

    overall: RateBlock
    by_category: dict[str, RateBlock]
    top_failure_modes: tuple[FailureMode, ...]
    reply_shape: ReplyShapeBlock


class Report(msgspec.Struct, frozen=True, kw_only=True):
    """The full eval report: provenance, the guarantee bound, and the observations."""

    meta: MetaBlock
    guarantee: GuaranteeBlock
    observations: ObservationsBlock


class PromptRecord(msgspec.Struct, frozen=True, kw_only=True):
    """One JSONL detail row: the prompt, the HTTP status, its bucket, and the model reply.

    For a 200 response model_reply is the model's verbatim content; for a non-200 fault it is the
    problem detail (best-effort, "" if it did not decode).
    """

    category: str
    dataset_name: str
    user_request: str
    http_status: int
    bucket: str
    model_reply: str


class _Tally(msgspec.Struct):
    """Mutable per-scope counters, finalized into a RateBlock by _rate_block."""

    n: int = 0
    verified: int = 0
    schema: int = 0
    semantic: int = 0
    policy: int = 0
    tool_call: int = 0
    json_valid: int = 0
    off_request: int = 0
    upstream_fault: int = 0
    harness_error: int = 0
    fenced: int = 0
    bare_object: int = 0
    empty: int = 0
    other: int = 0
    defenced_json_valid: int = 0


# --- classification -------------------------------------------------------------------------
def _classify(verdict: _RespVerdict) -> str:
    """Bucket a 200-response verdict: verified, schema (decode-layer), semantic, or policy.

    NAMING TRAP: the schema bucket is a decode-LAYER failure. The schema.* check FAMILY is a
    verify-layer check, so it buckets as semantic. Bucket is not family.
    """
    if verdict.verified:
        return _BUCKET_VERIFIED
    if verdict.layer == "decode":
        return _BUCKET_SCHEMA
    failing = tuple(r.check for r in verdict.results if r.status == "fail")
    # Policy only when >=1 check failed and all failing families are policy; otherwise semantic.
    # An empty failing set (verified False yet nothing failed) is a drift the service precludes.
    only_policy = bool(failing) and all(
        check.split(".", 1)[0] in _POLICY_FAMILIES for check in failing
    )
    return _BUCKET_POLICY if only_policy else _BUCKET_SEMANTIC


def _classify_fault(status: int, detail: str) -> str:
    """Bucket a non-200 fault: off_request (model), upstream_fault (infra), or harness_error.

    A 502 with the pin-mismatch detail is a model off-request behavior (a successful dataset
    redirect), NOT infra -- it stays out of upstream_fault. Every other 5xx is infra; a 4xx means
    the harness sent a bad request (expected to be 0).
    """
    if status == _HTTP_PIN_MISMATCH and detail == _PIN_MISMATCH_DETAIL:
        return _BUCKET_OFF_REQUEST
    if status >= _HTTP_SERVER_ERR:
        return _BUCKET_UPSTREAM_FAULT
    return _BUCKET_HARNESS_ERROR


def _json_shape(reply: str) -> tuple[bool, bool]:
    """(valid_json, is_object) for a model reply. is_object implies valid_json."""
    try:
        parsed = msgspec.json.decode(reply.encode("utf-8"))
    except (msgspec.DecodeError, ValueError):
        return (False, False)
    return (True, isinstance(parsed, dict))


def _reply_shape(reply: str) -> str:
    """Classify a model reply's surface form (see ReplyShapeBlock)."""
    stripped = reply.strip()
    if not stripped:
        return _SHAPE_EMPTY
    if "```" in reply:
        return _SHAPE_FENCED
    if stripped.startswith("{"):
        return _SHAPE_BARE_OBJECT
    return _SHAPE_OTHER


def _defenced_json_valid(reply: str) -> bool:
    """True if the reply parses as JSON after its first ```-fence (if any) is stripped."""
    match = _FENCE_RE.search(reply)
    inner = (match.group(1) if match else reply).strip()
    try:
        msgspec.json.decode(inner.encode("utf-8"))
    except (msgspec.DecodeError, ValueError):
        return False
    return True


# --- tallying + rates -----------------------------------------------------------------------
class _Sample(msgspec.Struct, frozen=True):
    """One 200 response's derived classification, tallied into both the overall and cat scopes."""

    bucket: str
    valid_json: bool
    is_object: bool
    shape: str
    defenced_valid: bool


def _tally_200(tally: _Tally, sample: _Sample) -> None:
    """Record one 200 response into a scope's counters."""
    tally.n += 1
    if sample.valid_json:
        tally.json_valid += 1
    if sample.is_object:
        tally.tool_call += 1
    if sample.bucket == _BUCKET_VERIFIED:
        tally.verified += 1
    elif sample.bucket == _BUCKET_SCHEMA:
        tally.schema += 1
    elif sample.bucket == _BUCKET_SEMANTIC:
        tally.semantic += 1
    elif sample.bucket == _BUCKET_POLICY:
        tally.policy += 1
    if sample.shape == _SHAPE_FENCED:
        tally.fenced += 1
    elif sample.shape == _SHAPE_BARE_OBJECT:
        tally.bare_object += 1
    elif sample.shape == _SHAPE_EMPTY:
        tally.empty += 1
    else:
        tally.other += 1
    if sample.defenced_valid:
        tally.defenced_json_valid += 1


def _tally_fault(tally: _Tally, bucket: str) -> None:
    """Record one non-200 fault into a scope's counters."""
    if bucket == _BUCKET_OFF_REQUEST:
        tally.off_request += 1
    elif bucket == _BUCKET_UPSTREAM_FAULT:
        tally.upstream_fault += 1
    elif bucket == _BUCKET_HARNESS_ERROR:
        tally.harness_error += 1


def _rate(count: int, n: int) -> float:
    """count / n rounded to _NDIGITS, or 0.0 when the scope collected no 200 responses."""
    return round(count / n, _NDIGITS) if n else 0.0


def _rate_block(tally: _Tally) -> RateBlock:
    """Finalize a scope's counters into an immutable RateBlock."""
    return RateBlock(
        n=tally.n,
        tool_call_rate=_rate(tally.tool_call, tally.n),
        json_validity_rate=_rate(tally.json_valid, tally.n),
        schema_failure_rate=_rate(tally.schema, tally.n),
        semantic_failure_rate=_rate(tally.semantic, tally.n),
        policy_failure_rate=_rate(tally.policy, tally.n),
        verified_render_rate=_rate(tally.verified, tally.n),
        off_request_count=tally.off_request,
        upstream_fault_count=tally.upstream_fault,
        harness_error_count=tally.harness_error,
    )


def _shape_block(tally: _Tally) -> ReplyShapeBlock:
    """Finalize a scope's reply-shape counters into an immutable ReplyShapeBlock."""
    return ReplyShapeBlock(
        n=tally.n,
        fenced=tally.fenced,
        bare_object=tally.bare_object,
        empty=tally.empty,
        other=tally.other,
        defenced_json_valid=tally.defenced_json_valid,
    )


# --- the guarantee: re-judge both golden corpora through /verify-only -----------------------
def _corpus_digest(spec_dir: Path, files: tuple[str, ...]) -> str:
    """SHA-256 over the sorted (filename, content-hash) pairs of one golden corpus.

    Pins the corpus IDENTITY, not just its size, so a wrong --examples-dir holding a same-sized
    set of other specs yields a different digest -- the guarantee cannot pass vacuously against a
    corpus that is not the real M1 goldens (codex-review M3.4b F1).
    """
    digest = hashlib.sha256()
    for name in sorted(files):
        content = (spec_dir / name).read_bytes()
        digest.update(name.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(hashlib.sha256(content).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _verify_only_verdict(client: httpx.Client, verifier_base_url: str, spec: bytes) -> bool | None:
    """POST one golden to /verify-only: its verified bool, or None on a transport fault/non-200
    (a golden can never be transport misuse, so a non-200 is infra, not a verdict)."""
    try:
        response = client.post(
            f"{verifier_base_url}/verify-only",
            content=spec,
            headers={"content-type": "application/json"},
        )
    except httpx.HTTPError:
        return None
    if response.status_code != _HTTP_OK:
        _LOGGER.warning("corpus verify-only answered non-200 (%d)", response.status_code)
        return None
    return msgspec.json.decode(response.content, type=_RespVerdict).verified


def _run_guarantee(
    client: httpx.Client, verifier_base_url: str, examples_dir: Path
) -> GuaranteeBlock:
    """Re-judge both golden corpora through /verify-only: count bad goldens that falsely verify
    and good goldens that falsely fail (see GuaranteeBlock -- the good leg needs the verifier's
    data_dir provisioned with the corpus datasets, which the goldens' baked hashes bind to).

    A transport error or non-200 is logged and counted per corpus as a transport error, never
    as a false accept/reject. Both false counts MUST be 0; either non-zero is a real regression.
    """
    index = msgspec.json.decode((examples_dir / "index.json").read_bytes(), type=_Index)
    counts = {"bad_specs": 0, "good_specs": 0}
    transport = {"bad_specs": 0, "good_specs": 0}
    # regression_verdict = the verdict that counts AGAINST the bound: a bad golden verifying
    # (false accept) or a good golden failing (false reject).
    for subdir, entries, regression_verdict in (
        ("bad_specs", index.bad_specs, True),
        ("good_specs", index.good_specs, False),
    ):
        for entry in entries:
            spec_bytes = (examples_dir / subdir / entry.file).read_bytes()
            verified = _verify_only_verdict(client, verifier_base_url, spec_bytes)
            if verified is None:
                _LOGGER.warning("%s transport error for %s", subdir, entry.file)
                transport[subdir] += 1
            elif verified is regression_verdict:
                counts[subdir] += 1
    return GuaranteeBlock(
        bad_corpus_size=len(index.bad_specs),
        bad_corpus_digest=_corpus_digest(
            examples_dir / "bad_specs", tuple(e.file for e in index.bad_specs)
        ),
        bad_corpus_false_accept_count=counts["bad_specs"],
        bad_corpus_transport_errors=transport["bad_specs"],
        good_corpus_size=len(index.good_specs),
        good_corpus_digest=_corpus_digest(
            examples_dir / "good_specs", tuple(e.file for e in index.good_specs)
        ),
        good_corpus_false_reject_count=counts["good_specs"],
        good_corpus_transport_errors=transport["good_specs"],
    )


# --- encode + provenance --------------------------------------------------------------------
def encode_report(report: Report) -> bytes:
    """Pretty-print the report as indented JSON with a trailing newline."""
    return msgspec.json.format(msgspec.json.encode(report), indent=2) + b"\n"


def encode_details(records: tuple[PromptRecord, ...]) -> bytes:
    """Encode the prompt records as JSONL (one compact object per line, trailing newline each)."""
    return b"".join(msgspec.json.encode(record) + b"\n" for record in records)


def fetch_model_name(client: httpx.Client, model_base_url: str) -> str | None:
    """GET {model_base_url}/models and return the first served model id, or None on any failure."""
    try:
        response = client.get(f"{model_base_url}/models")
        models = msgspec.json.decode(response.content, type=_ModelList)
    except (httpx.HTTPError, msgspec.DecodeError, ValueError):
        return None
    if not models.data:
        return None
    return models.data[0].id


# --- the driver -----------------------------------------------------------------------------
def run_eval(
    client: httpx.Client,
    verifier_base_url: str,
    examples_dir: Path,
    served_model: str | None,
    prompts: tuple[Prompt, ...],
) -> tuple[Report, tuple[PromptRecord, ...]]:
    """Run the guarantee (both corpora) then every prompt through /propose-spec; return the
    report + JSONL rows.

    Each prompt is POSTed to /propose-spec. A 200 decodes to a loose ProposeResult and buckets by
    verdict; a non-200 decodes the problem detail (best-effort) and buckets as a fault. Rates are
    over the 200-response count per scope; the top failing checks span all 200 verdicts.
    """
    guarantee = _run_guarantee(client, verifier_base_url, examples_dir)
    overall = _Tally()
    cat_tallies: dict[str, _Tally] = {category: _Tally() for category in CATEGORIES}
    failing_checks: Counter[str] = Counter()
    records: list[PromptRecord] = []
    for prompt in prompts:
        cat = cat_tallies[prompt.category]
        response = client.post(
            f"{verifier_base_url}/propose-spec",
            json={"dataset_name": prompt.dataset_name, "user_request": prompt.user_request},
        )
        status = response.status_code
        if status == _HTTP_OK:
            result = msgspec.json.decode(response.content, type=_RespProposeResult)
            bucket = _classify(result.verdict)
            valid_json, is_object = _json_shape(result.model_reply)
            sample = _Sample(
                bucket=bucket,
                valid_json=valid_json,
                is_object=is_object,
                shape=_reply_shape(result.model_reply),
                defenced_valid=_defenced_json_valid(result.model_reply),
            )
            _tally_200(overall, sample)
            _tally_200(cat, sample)
            failing_checks.update(r.check for r in result.verdict.results if r.status == "fail")
            reply = result.model_reply
        else:
            reply = _fault_detail(response)
            bucket = _classify_fault(status, reply)
            _tally_fault(overall, bucket)
            _tally_fault(cat, bucket)
        records.append(
            PromptRecord(
                category=prompt.category,
                dataset_name=prompt.dataset_name,
                user_request=prompt.user_request,
                http_status=status,
                bucket=bucket,
                model_reply=reply,
            )
        )
    top = tuple(
        FailureMode(check=check, count=count)
        for check, count in failing_checks.most_common(_TOP_MODES)
    )
    observations = ObservationsBlock(
        overall=_rate_block(overall),
        by_category={category: _rate_block(cat_tallies[category]) for category in CATEGORIES},
        top_failure_modes=top,
        reply_shape=_shape_block(overall),
    )
    meta = MetaBlock(
        served_model=served_model,
        prompt_count=len(prompts),
        categories=CATEGORIES,
        reproducibility=_REPRODUCIBILITY,
    )
    return Report(meta=meta, guarantee=guarantee, observations=observations), tuple(records)


def _fault_detail(response: httpx.Response) -> str:
    """The problem detail of a non-200 response, best-effort ("" if the body did not decode)."""
    try:
        problem = msgspec.json.decode(response.content, type=_RespProblem)
    except (msgspec.DecodeError, ValueError):
        return ""
    return problem.detail
