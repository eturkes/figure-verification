# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Capture instrument: the live driver over the backend's chat route, and the offline statistics.

Two halves, one seam. The DRIVER talks to POST /v1/chat/completions and emits records; the STATS
are a pure function of a committed run directory, so every number here re-derives from committed
bytes with no backend, no accelerator and no network.

    python -m capture run --run m12-design      drive a corpus set, flushing after every row
    python -m capture stats [<run-dir>...]      grade R1-R11 AND S1-S4, or rewrite stats.json

capture.record owns the record format and never imports this module. Nothing here spells an
outbound body: build_request_body is the sole speller and build_record the sole emitter, which is
what makes R2 and R11 grade the wire rather than a restatement of it.

A record's http_status is 200 ONLY for a complete decoded reply. A transport error, a body that
does not decode, an envelope with no usable choice and a finish_reason outside FINISH_REASONS all
record NO_STATUS with the observed status named in the error text. R6 forces the split, and it is
what keeps a run gradeable after an hour of dGPU time instead of unrecoverable.

De-fencing has ONE authority: `fenced` MEANS the de-fencer extracted an inner block, so the fence
rate and the parse rate cannot disagree about what a fence is. It handles an UNTERMINATED fence
because truncation is one of the three statistics and the two interact -- a reply cut at the token
cap has an opening fence and no closing one.

`parsed` requires at least one statement: ast.parse("") succeeds on an empty module and would
otherwise inflate the headline number. The statistic is total over adversarial bytes -- a byte cap
precedes the parse and four exception families score not-parsed instead of propagating. This is a
TCB addition for capture/ alone; src/verifier/expr.py keeps its no-ast property.

Rates count REPLIES, never records: a transport fault is not a model behaviour. An undefined rate
is None, never 0.0. Sentinels are reported as per-row facts outside every category denominator --
there is one per category, and a rate over n=1 is a category error.

Predicates S1-S4 of .agent/contracts/m12u6b.md are implemented HERE and nowhere else;
tests/test_python_capture_harness.py calls them and restates none of them.
"""

import argparse
import ast
import math
import re
import sys
from collections.abc import Callable, Collection, Sequence
from pathlib import Path
from typing import Final, Literal

import httpx
import msgspec

from capture.corpus import (
    CATEGORIES,
    Category,
    Corpus,
    Kind,
    Prompt,
    load_corpus,
    render_capture_prompt,
)
from capture.record import (
    CAPTURE_MODE,
    CAPTURES_ROOT,
    FINISH_REASONS,
    CaptureFormatError,
    CaptureRecord,
    Provenance,
    Run,
    RunManifest,
    ServiceProvenance,
    Usage,
    build_record,
    build_request_body,
    collect_host_provenance,
    collect_repo_provenance,
    load_run,
    write_run,
)
from capture.record import validate as validate_records

STATS_VERSION: Final = "python-capture-stats-1"
STATS_NAME: Final = "stats.json"
# R-status: the outcome had no usable HTTP result. Distinct from every real status, so R6's 200
# arm stays reserved for a complete decoded reply.
NO_STATUS: Final = 0

CHAT_PATH: Final = "/v1/chat/completions"
HEALTH_PATH: Final = "/health"
DEFAULT_BASE_URL: Final = "http://127.0.0.1:8001"
# The backend's own ceiling (model_backend.settings._DEFAULT_MAX_TOKENS). A larger request is
# CLAMPED silently, so raising the truncation lever is a server-side MODEL_BACKEND_MAX_TOKENS
# change; the manifest records what was sent and usage reports what the backend did with it.
DEFAULT_MAX_TOKENS: Final = 512
# Greedy: the engine passes do_sample=False and pins num_beams at temperature 0.
DEFAULT_TEMPERATURE: Final = 0.0
DEFAULT_TIMEOUT: Final = 300.0
# A cap ahead of ast.parse keeps the statistic total over model bytes. Three orders above any
# reply the token cap admits, so it never fires on a real capture.
MAX_PARSE_BYTES: Final = 1 << 20

_TRUNCATED: Final = "length"
_SENTINELS: Final[Kind] = "sentinels"
_HTTP_OK: Final = 200
_JSON_INDENT: Final = 2
_NDIGITS: Final = 4
_MAX_ERROR_CHARS: Final = 512
_USAGE_OK: Final = 0
_USAGE_FAIL: Final = 1
_USAGE_ARGS: Final = 2

# A fence opener is ``` at the start of a line, through the end of that line. End-of-string
# terminates it too: a reply truncated inside the opener IS fenced, and its inner block is empty.
_FENCE_OPEN_RE: Final = re.compile(r"^[ \t]*```[^\n]*(?:\n|\Z)", re.MULTILINE)
_FENCE_CLOSE_RE: Final = re.compile(r"^[ \t]*```[ \t]*$", re.MULTILINE)


class StatBlock(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Three rates over one scope, with the counts they came from.

    replies is the denominator: a fault carries no model behaviour to measure. Each rate is None
    when replies is 0 -- a zero-sample scope has no rate, and 0.0 would read as a measured zero.
    """

    records: int
    replies: int
    fenced: int
    parsed: int
    truncated: int
    fence_rate: float | None
    parse_rate: float | None
    truncation_rate: float | None


class SentinelStat(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """One sentinel prompt's per-row facts. Never a rate: n=1 per category."""

    prompt_id: str
    category: Category
    http_status: int
    fenced: bool | None
    parsed: bool | None
    truncated: bool | None


class CaptureStats(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """One run's derived statistics: per category over its own corpus set, per row for sentinels."""

    version: Literal["python-capture-stats-1"]
    mode: Literal["python_raw_unconstrained"]
    run: str
    kind: Kind
    record_count: int
    by_category: dict[str, StatBlock]
    sentinels: tuple[SentinelStat, ...]


class StatsRun(msgspec.Struct, frozen=True, kw_only=True):
    """One loaded run plus its statistics and the exact bytes they were read from."""

    run: Run
    stats: CaptureStats
    stats_bytes: bytes


class CaptureConfig(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """The request parameters one run is taken under; the manifest records all four verbatim.

    Bundled deliberately, unlike build_record's per-fact keywords: these four travel together into
    every body AND into the manifest, and R-resume compares them as one committed group.
    """

    base_url: str
    model: str
    max_tokens: int
    temperature: float


class Outcome(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """One exchange: the bytes that went out, and what came back once mapped by R-status."""

    request_body: bytes
    http_status: int
    content: str | None = None
    finish_reason: str | None = None
    usage: Usage | None = None
    error: str | None = None


class _ReplyFacts(msgspec.Struct, frozen=True, kw_only=True):
    """The three per-reply booleans every rate is a mean of."""

    fenced: bool
    parsed: bool
    truncated: bool


class _RespMessage(msgspec.Struct):
    """The assistant turn of a completion. Required: a message without content is not a reply."""

    content: str


class _RespChoice(msgspec.Struct):
    """One completion choice. Both fields required, so a partial envelope takes the fault arm."""

    message: _RespMessage
    finish_reason: str


class _RespUsage(msgspec.Struct):
    """Token accounting. Required: R8 grades the sum, so an absent block cannot default to zero."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class _RespCompletion(msgspec.Struct):
    """The chat-completion envelope, read loosely on EXTRA keys and strictly on required ones.

    Loose on extra so an added backend field never breaks a capture; strict on required so a
    malformed envelope becomes a named fault instead of silently defaulting to empty.
    """

    choices: tuple[_RespChoice, ...]
    usage: _RespUsage


class _RespErrorDetail(msgspec.Struct):
    """The backend's OpenAI-style error body."""

    message: str
    type: str


class _RespError(msgspec.Struct):
    """The envelope around it."""

    error: _RespErrorDetail


class _RespHealth(msgspec.Struct):
    """GET /health, read into this module's OWN loose struct.

    ServiceProvenance forbids unknown fields on purpose, so /health is decoded here and exactly
    three of its fields are carried across; an added health field can never enter a record
    unreviewed.
    """

    model_name: str
    device: str
    structured_output: bool


_STATS_DECODER: Final = msgspec.json.Decoder(CaptureStats)
_COMPLETION_DECODER: Final = msgspec.json.Decoder(_RespCompletion)
_HEALTH_DECODER: Final = msgspec.json.Decoder(_RespHealth)


# --- derived statistics (pure; no network, no accelerator) -----------------------------------
def defence(content: str) -> tuple[bool, str]:
    """Return (fenced, inner block). The SOLE authority on what a Markdown fence is.

    An opening fence with no closing one yields the remainder: that is the truncation shape, and a
    closing-fence-required pattern would score every truncated fenced reply unparseable.
    """
    opened = _FENCE_OPEN_RE.search(content)
    # The opener must be the FIRST fence marker in the reply. Without this a trailing closer
    # answers the search and opens an empty block, discarding a whole program whose real opener
    # sat mid-line and was correctly refused.
    if opened is None or content.find("```") < opened.start():
        return (False, content)
    rest = content[opened.end() :]
    closed = _FENCE_CLOSE_RE.search(rest)
    return (True, rest if closed is None else rest[: closed.start()])


def parses(content: str) -> bool:
    """True when the text parses to a module carrying at least one statement.

    Total over adversarial bytes: over-cap input, a NUL byte, a syntax error and unbounded nesting
    all answer False rather than raising. Nothing is executed, imported or compiled to code.
    """
    if len(content.encode("utf-8")) > MAX_PARSE_BYTES:
        return False
    try:
        module = ast.parse(content)
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return False
    return bool(module.body)


def _reply_facts(record: CaptureRecord) -> _ReplyFacts | None:
    """The three booleans for a reply; None for anything a rate must not count.

    A 200 record with no content is an R6 violation rather than a reply, so it counts as a fault
    here instead of raising -- grading is R6's job and this module never has to be its second one.
    """
    if record.http_status != _HTTP_OK or record.content is None:
        return None
    fenced, inner = defence(record.content)
    return _ReplyFacts(
        fenced=fenced, parsed=parses(inner), truncated=record.finish_reason == _TRUNCATED
    )


def _rate(count: int, replies: int) -> float | None:
    """A rate over replies, or None when the scope holds none."""
    return None if replies == 0 else round(count / replies, _NDIGITS)


def _block(records: Sequence[CaptureRecord]) -> StatBlock:
    """Tally one scope: counts over every record, rates over its replies alone."""
    facts = [found for found in map(_reply_facts, records) if found is not None]
    fenced = sum(1 for fact in facts if fact.fenced)
    parsed = sum(1 for fact in facts if fact.parsed)
    truncated = sum(1 for fact in facts if fact.truncated)
    return StatBlock(
        records=len(records),
        replies=len(facts),
        fenced=fenced,
        parsed=parsed,
        truncated=truncated,
        fence_rate=_rate(fenced, len(facts)),
        parse_rate=_rate(parsed, len(facts)),
        truncation_rate=_rate(truncated, len(facts)),
    )


def _sentinel_stat(record: CaptureRecord) -> SentinelStat:
    """One sentinel row: its facts, or three Nones when the exchange produced no reply."""
    facts = _reply_facts(record)
    return SentinelStat(
        prompt_id=record.prompt_id,
        category=record.category,
        http_status=record.http_status,
        fenced=None if facts is None else facts.fenced,
        parsed=None if facts is None else facts.parsed,
        truncated=None if facts is None else facts.truncated,
    )


def derive_stats(run: Run) -> CaptureStats:
    """Derive one run's statistics. Pure: the same records always give the same bytes."""
    sentinels = sorted(
        (record for record in run.records if record.kind == _SENTINELS),
        key=lambda record: record.prompt_id,
    )
    rows = [record for record in run.records if record.kind != _SENTINELS]
    return CaptureStats(
        version=STATS_VERSION,
        mode=CAPTURE_MODE,
        run=run.manifest.run,
        kind=run.manifest.kind,
        record_count=len(run.records),
        # CATEGORIES order, so the encoded key order is the corpus's declaration order.
        by_category={
            category: _block([record for record in rows if record.category == category])
            for category in CATEGORIES
        },
        sentinels=tuple(_sentinel_stat(record) for record in sentinels),
    )


def encode_stats(stats: CaptureStats) -> bytes:
    """Serialize statistics to their canonical committed form: indented, one trailing newline."""
    return msgspec.json.format(msgspec.json.encode(stats), indent=_JSON_INDENT) + b"\n"


def decode_stats(raw: bytes) -> CaptureStats:
    """Strictly decode one statistics file; raise on any malformed or unknown field."""
    return _STATS_DECODER.decode(raw)


def write_stats(directory: Path, stats: CaptureStats) -> None:
    """Write one statistics file in canonical form, re-deriving nothing."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / STATS_NAME).write_bytes(encode_stats(stats))


def load_stats_run(directory: Path) -> StatsRun:
    """Load one run and its statistics, keeping the bytes so canonical form stays checkable.

    S3 compares against these bytes, so they are read once and never re-encoded on the way in.
    """
    raw = (directory / STATS_NAME).read_bytes()
    return StatsRun(run=load_run(directory), stats=decode_stats(raw), stats_bytes=raw)


def check_stats_version(loaded: StatsRun) -> list[str]:
    """S1 -- the statistics declare this format version and this capture mode."""
    return [
        f"{STATS_NAME}: {field} is {actual!r}, expected {expected!r}"
        for field, actual, expected in (
            ("version", loaded.stats.version, STATS_VERSION),
            ("mode", loaded.stats.mode, CAPTURE_MODE),
        )
        if actual != expected
    ]


def check_stats_identity(loaded: StatsRun) -> list[str]:
    """S2 -- the statistics name the run they were derived from."""
    manifest = loaded.run.manifest
    return [
        f"{STATS_NAME}: {field} is {actual!r}, manifest says {expected!r}"
        for field, actual, expected in (
            ("run", loaded.stats.run, manifest.run),
            ("kind", loaded.stats.kind, manifest.kind),
            ("record_count", loaded.stats.record_count, len(loaded.run.records)),
        )
        if actual != expected
    ]


def check_stats_reproduce(loaded: StatsRun) -> list[str]:
    """S3 -- the committed statistics ARE the re-derivation from the committed records."""
    if loaded.stats_bytes == encode_stats(derive_stats(loaded.run)):
        return []
    return [f"{STATS_NAME}: bytes are not the derivation of {loaded.run.directory.name}'s records"]


def check_stats_scope(loaded: StatsRun) -> list[str]:
    """S4 -- the reported blocks PARTITION the run: closed category set, the run's own sentinel
    rows, and every record counted exactly once across the two.

    Membership, not key order: order is a canonical-bytes property S3 decides byte-for-byte, and
    duplicating it here left a key swap without a specific diagnosis. The arithmetic is measured
    against the RUN's records rather than the statistics' own ``record_count``, which is S2's
    field alone -- summing against it made S4 a second S2 and a second S3 at once.
    """
    stats = loaded.stats
    failures: list[str] = []
    if set(stats.by_category) != set(CATEGORIES):
        failures.append(f"{STATS_NAME}: categories {tuple(stats.by_category)} != {CATEGORIES}")
    committed = tuple(
        sorted(record.prompt_id for record in loaded.run.records if record.kind == _SENTINELS)
    )
    reported = tuple(row.prompt_id for row in stats.sentinels)
    if reported != committed:
        failures.append(f"{STATS_NAME}: sentinel rows {reported} != run's {committed}")
    counted = sum(block.records for block in stats.by_category.values()) + len(stats.sentinels)
    if counted != len(loaded.run.records):
        failures.append(
            f"{STATS_NAME}: blocks count {counted} of {len(loaded.run.records)} records"
        )
    return failures


STATS_PREDICATES: dict[str, Callable[[StatsRun], list[str]]] = {
    "S1": check_stats_version,
    "S2": check_stats_identity,
    "S3": check_stats_reproduce,
    "S4": check_stats_scope,
}


def validate_stats(directory: Path) -> list[str]:
    """Run S1-S4 over one run's statistics; return id-prefixed failure lines, empty when sound."""
    loaded = load_stats_run(directory)
    return [f"{pid}: {line}" for pid, check in STATS_PREDICATES.items() for line in check(loaded)]


# --- the live driver --------------------------------------------------------------------------
def _fault(body: bytes, reason: str) -> Outcome:
    """R-status: an unusable exchange, with the observed status named inside the reason text."""
    return Outcome(request_body=body, http_status=NO_STATUS, error=reason)


def _fault_detail(response: httpx.Response) -> str:
    """The backend's error text, best-effort; the raw body when it is not the error shape."""
    try:
        decoded = msgspec.json.decode(response.content, type=_RespError)
    except (msgspec.DecodeError, ValueError):
        return response.text[:_MAX_ERROR_CHARS]
    return f"{decoded.error.type}: {decoded.error.message}"


def capture_one(  # noqa: PLR0913 — one keyword per request parameter; a bundle would hide which
    client: httpx.Client,
    *,
    base_url: str,
    prompt: Prompt,
    model: str,
    max_tokens: int,
    temperature: float,
) -> Outcome:
    """Send one prompt and map its exchange. Builds no JSON: build_request_body is the speller."""
    body = build_request_body(
        prompt=render_capture_prompt(prompt),
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    try:
        response = client.post(
            f"{base_url}{CHAT_PATH}", content=body, headers={"content-type": "application/json"}
        )
    except httpx.HTTPError as exc:
        return _fault(body, f"transport error, no status: {type(exc).__name__}: {exc}")
    status = response.status_code
    if status != _HTTP_OK:
        return Outcome(
            request_body=body, http_status=status, error=f"HTTP {status}: {_fault_detail(response)}"
        )
    try:
        envelope = _COMPLETION_DECODER.decode(response.content)
    except (msgspec.DecodeError, ValueError) as exc:
        return _fault(body, f"observed status {status}, body did not decode: {exc}")
    if not envelope.choices:
        return _fault(body, f"observed status {status}, envelope carried no choice")
    choice = envelope.choices[0]
    if choice.finish_reason not in FINISH_REASONS:
        return _fault(
            body,
            f"observed status {status}, finish_reason {choice.finish_reason!r} "
            f"not in {FINISH_REASONS}",
        )
    return Outcome(
        request_body=body,
        http_status=status,
        content=choice.message.content,
        finish_reason=choice.finish_reason,
        usage=Usage(
            prompt_tokens=envelope.usage.prompt_tokens,
            completion_tokens=envelope.usage.completion_tokens,
            total_tokens=envelope.usage.total_tokens,
        ),
    )


def fetch_service_provenance(client: httpx.Client, base_url: str) -> ServiceProvenance | None:
    """Read the three archived /health facts; None whenever the service cannot answer them."""
    try:
        response = client.get(f"{base_url}{HEALTH_PATH}")
    except httpx.HTTPError:
        return None
    if response.status_code != _HTTP_OK:
        return None
    try:
        health = _HEALTH_DECODER.decode(response.content)
    except (msgspec.DecodeError, ValueError):
        return None
    return ServiceProvenance(
        model_name=health.model_name,
        device=health.device,
        structured_output=health.structured_output,
    )


def select_rows(corpus: Corpus, kind: Kind, *, sentinels: bool) -> tuple[tuple[Kind, Prompt], ...]:
    """The rows one run drives: its own corpus set, then the sentinels (R5's admitted scope)."""
    rows = [(row_kind, prompt) for row_kind, prompt in corpus.rows() if row_kind == kind]
    if sentinels and kind != _SENTINELS:
        rows.extend(
            (row_kind, prompt) for row_kind, prompt in corpus.rows() if row_kind == _SENTINELS
        )
    return tuple(rows)


def build_manifest(
    run: str, *, kind: Kind, config: CaptureConfig, provenance: Provenance, record_count: int
) -> RunManifest:
    """Assemble one run manifest from its request parameters and collected provenance."""
    return RunManifest(
        version="python-capture-1",
        mode=CAPTURE_MODE,
        run=run,
        kind=kind,
        model=config.model,
        model_base_url=config.base_url,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        record_count=record_count,
        provenance=provenance,
    )


def manifest_conflict(committed: RunManifest, fresh: RunManifest) -> str | None:
    """R-resume: name the first field on which a resumed run disagrees with its committed one.

    record_count is the one field that legitimately grows. Everything else -- commit, dirty state,
    model, revision, dtype, cap, temperature, observed service and host -- pins the evidence set,
    so a disagreement means two tree states, not one run.
    """
    return next(
        (
            field
            for field in RunManifest.__struct_fields__
            if field != "record_count" and getattr(committed, field) != getattr(fresh, field)
        ),
        None,
    )


def _flush(
    directory: Path,
    *,
    kind: Kind,
    config: CaptureConfig,
    provenance: Provenance,
    records: Sequence[CaptureRecord],
) -> None:
    """R-flush: rewrite all three files, so the directory is a complete run at every instant.

    Statistics are derived from the RELOADED run rather than from the in-memory records, which
    round-trips the canonical bytes on every row and surfaces a write fault immediately.
    """
    manifest = build_manifest(
        directory.name,
        kind=kind,
        config=config,
        provenance=provenance,
        record_count=len(records),
    )
    write_run(directory, manifest, records)
    write_stats(directory, derive_stats(load_run(directory)))


def run_capture(  # noqa: PLR0913 — explicit boundary inputs keep scope and provenance non-defaulted
    client: httpx.Client,
    directory: Path,
    *,
    rows: Sequence[tuple[Kind, Prompt]],
    kind: Kind,
    config: CaptureConfig,
    provenance: Provenance,
    keep: Sequence[CaptureRecord] = (),
    progress: bool = True,
) -> tuple[CaptureRecord, ...]:
    """Drive every row not already captured, flushing the whole directory after each one."""
    records = list(keep)
    done = {record.prompt_id for record in records}
    _flush(directory, kind=kind, config=config, provenance=provenance, records=records)
    todo = [(row_kind, prompt) for row_kind, prompt in rows if prompt.id not in done]
    for index, (row_kind, prompt) in enumerate(todo, start=1):
        outcome = capture_one(
            client,
            base_url=config.base_url,
            prompt=prompt,
            model=config.model,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
        )
        records.append(
            build_record(
                run=directory.name,
                prompt=prompt,
                kind=row_kind,
                request_body=outcome.request_body,
                http_status=outcome.http_status,
                content=outcome.content,
                finish_reason=outcome.finish_reason,
                usage=outcome.usage,
                error=outcome.error,
            )
        )
        _flush(directory, kind=kind, config=config, provenance=provenance, records=records)
        if progress:
            sys.stdout.write(f"{index}/{len(todo)} {prompt.id} {outcome.http_status}\n")
    return tuple(records)


# --- CLI ----------------------------------------------------------------------------------------
def _discover(root: Path) -> list[Path]:
    """List every run directory under one captures root, in name order."""
    return sorted(path for path in root.iterdir() if path.is_dir()) if root.is_dir() else []


def _grade(directory: Path) -> list[str]:
    """Grade one run under BOTH predicate sets, so one command decides a whole directory."""
    return validate_records(directory) + validate_stats(directory)


def _report(directory: Path, failures: Sequence[str]) -> bool:
    """Write one run's verdict; True when it was sound."""
    for line in failures:
        sys.stderr.write(f"{directory}: {line}\n")
    if not failures:
        sys.stdout.write(f"{directory}: sound\n")
    return not failures


def _stats_command(directories: Sequence[Path], *, write: bool) -> int:
    """Grade each run, optionally rewriting its statistics from its committed records first."""
    failed = False
    for directory in directories:
        try:
            if write:
                write_stats(directory, derive_stats(load_run(directory)))
            failures = _grade(directory)
        except (CaptureFormatError, msgspec.DecodeError, OSError) as exc:
            sys.stderr.write(f"{directory}: {exc}\n")
            failed = True
            continue
        failed = not _report(directory, failures) or failed
    return _USAGE_FAIL if failed else _USAGE_OK


def _resolve_existing(
    directory: Path,
    *,
    resume: bool,
    overwrite: bool,
    fresh: RunManifest,
    selected: Collection[str],
) -> tuple[tuple[CaptureRecord, ...], str | None]:
    """R-resume: decide what an already-populated run directory contributes, or refuse it."""
    if not (directory / "run.json").exists():
        return ((), None)
    if overwrite:
        return ((), None)
    if not resume:
        return ((), f"{directory} already holds a run; pass --resume or --overwrite")
    committed = load_run(directory)
    conflict = manifest_conflict(committed.manifest, fresh)
    if conflict is not None:
        return ((), f"{directory} was captured under a different {conflict}; refusing to resume")
    # A committed id outside the freshly selected rows has no sound resolution: keeping it widens
    # the run past its own scope, dropping it breaks resume's byte-preservation promise. Prompt ids
    # are not manifest fields, so the conflict check above cannot see this.
    outside = sorted(
        record.prompt_id for record in committed.records if record.prompt_id not in selected
    )
    if outside:
        joined = ", ".join(outside)
        return ((), f"{directory} holds rows outside the selected scope: {joined}")
    return (committed.records, None)


def _run_command(args: argparse.Namespace) -> int:
    """Stand up one live capture run: collect provenance, drive the rows, grade the result."""
    kind: Kind = args.kind
    if kind == "heldout" and not args.heldout_acknowledged:
        sys.stderr.write(
            "refusing to generate against the held-out set; pass --heldout-acknowledged\n"
        )
        return _USAGE_ARGS
    if not (math.isfinite(args.timeout) and args.timeout > 0):
        sys.stderr.write(f"timeout must be finite and positive, got {args.timeout}\n")
        return _USAGE_ARGS
    directory = Path(args.root) / args.run
    # Refuse a populated directory BEFORE any network call: the default refusal is unconditional,
    # so probing /health first would spend a request on a run that was never going to start.
    if (directory / "run.json").exists() and not (args.resume or args.overwrite):
        sys.stderr.write(f"{directory} already holds a run; pass --resume or --overwrite\n")
        return _USAGE_ARGS
    rows = select_rows(load_corpus(), kind, sentinels=not args.no_sentinels)
    with httpx.Client(timeout=args.timeout) as client:
        service = fetch_service_provenance(client, args.base_url)
        model = args.model or (service.model_name if service is not None else None)
        if model is None:
            sys.stderr.write(f"{args.base_url}{HEALTH_PATH} named no model; pass --model\n")
            return _USAGE_ARGS
        config = CaptureConfig(
            base_url=args.base_url,
            model=model,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
        )
        provenance = Provenance(
            repo=collect_repo_provenance(), service=service, host=collect_host_provenance()
        )
        keep, refusal = _resolve_existing(
            directory,
            resume=args.resume,
            overwrite=args.overwrite,
            fresh=build_manifest(
                args.run, kind=kind, config=config, provenance=provenance, record_count=0
            ),
            selected=frozenset(prompt.id for _, prompt in rows),
        )
        if refusal is not None:
            sys.stderr.write(f"{refusal}\n")
            return _USAGE_ARGS
        run_capture(
            client,
            directory,
            rows=rows,
            kind=kind,
            config=config,
            provenance=provenance,
            keep=keep,
            progress=not args.quiet,
        )
    return _USAGE_FAIL if not _report(directory, _grade(directory)) else _USAGE_OK


def _build_parser() -> argparse.ArgumentParser:
    """Build the two-subcommand parser."""
    parser = argparse.ArgumentParser(
        prog="python -m capture",
        description="Capture python-mode model replies, and grade the committed runs.",
        allow_abbrev=False,
    )
    subs = parser.add_subparsers(dest="command", required=True)

    run = subs.add_parser(
        "run",
        description="Send every corpus prompt to the model backend. Write one run directory.",
        allow_abbrev=False,
    )
    run.add_argument("--run", required=True, metavar="NAME", help="name of the run directory")
    run.add_argument(
        "--kind", default="design", choices=("design", "heldout"), help="corpus set to drive"
    )
    run.add_argument(
        "--root", type=Path, default=CAPTURES_ROOT, metavar="DIR", help="captures root directory"
    )
    run.add_argument(
        "--base-url", default=DEFAULT_BASE_URL, metavar="URL", help="model backend base URL"
    )
    run.add_argument("--model", default=None, metavar="NAME", help="model name to send")
    run.add_argument(
        "--max-tokens", type=int, default=DEFAULT_MAX_TOKENS, metavar="N", help="token limit to ask"
    )
    run.add_argument(
        "--temperature", type=float, default=DEFAULT_TEMPERATURE, metavar="F", help="sampling heat"
    )
    run.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT, metavar="F", help="seconds per request"
    )
    run.add_argument("--no-sentinels", action="store_true", help="drive the corpus set only")
    run.add_argument("--resume", action="store_true", help="keep the rows already captured")
    run.add_argument("--overwrite", action="store_true", help="discard the run and start again")
    run.add_argument(
        "--heldout-acknowledged", action="store_true", help="permit a held-out capture"
    )
    run.add_argument("--quiet", action="store_true", help="do not report each row")

    stats = subs.add_parser(
        "stats",
        description="Grade committed capture runs. Add --write to derive the statistics again.",
        allow_abbrev=False,
    )
    stats.add_argument(
        "run_dir", type=Path, nargs="*", metavar="PATH", help="capture run directories"
    )
    stats.add_argument(
        "--root", type=Path, default=CAPTURES_ROOT, metavar="DIR", help="captures root directory"
    )
    stats.add_argument("--write", action="store_true", help="rewrite each stats file first")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one subcommand: drive a live capture, or grade the committed runs."""
    args = _build_parser().parse_args(argv)
    if args.command == "run":
        return _run_command(args)
    directories: list[Path] = args.run_dir or _discover(args.root)
    if not directories:
        sys.stdout.write(f"no capture runs under {args.root}\n")
        return _USAGE_OK
    return _stats_command(directories, write=args.write)


if __name__ == "__main__":
    raise SystemExit(main())
