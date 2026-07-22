# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M3-review feedback loop for bench's pure logic (no servers, no sockets).

bench/ is a coverage-excluded runnable harness, not part of the verifier claim — but its
classifiers decide what the eval REPORTS, and until this module they had no standing tests (the
M3.4a synthetic-payload exercise was a one-off script, never committed). Locked here:

- the verdict buckets (verified / schema=decode-layer / semantic / policy) incl. the
  policy-requires-policy-family rule and the empty-failing-set drift arm;
- the fault split, incl. dedicated prompt-policy 422 and the pin-mismatch detail string staying
  byte-equal to app.py's (the
  harness duplicates it by design — an out-of-tree observer imports no verifier internals — so
  THIS test is the drift guard);
- the reply-shape taxonomy + de-fence rule the headline numbers rest on;
- both corpus identity pins re-derived from the live tree (a corpus edit fails this portable
  gate, not just the next hardware-gated live run);
- the guarantee runner itself over a MockTransport mini-corpus (per-corpus regression counting
  and the transport-fault arms — codex-review: a swapped regression_verdict or broken None
  handling must fail HERE, not only on the next live run);
- the exit-code validity matrix (every single violation flips a valid run to exit 1).
"""

import hashlib
import shutil
import subprocess
from pathlib import Path

import httpx
import msgspec
import pytest

from bench.__main__ import (
    _EXPECTED_BAD_CORPUS_DIGEST,
    _EXPECTED_BAD_CORPUS_SIZE,
    _EXPECTED_GOOD_CORPUS_DIGEST,
    _EXPECTED_GOOD_CORPUS_SIZE,
    _SCHEMA_PATH,
    _exit_code,
    _git_provenance,
    _schema_digest,
)
from bench.harness import (
    BackendProvenance,
    GuaranteeBlock,
    MetaBlock,
    ObservationsBlock,
    RateBlock,
    ReplyShapeBlock,
    Report,
    _classify,
    _classify_fault,
    _corpus_digest,
    _decode_propose_result,
    _defenced_json_valid,
    _Index,
    _rate_block,
    _reply_shape,
    _RespCheck,
    _RespMethod,
    _RespVerdict,
    _run_guarantee,
    _Tally,
    _tally_fault,
    fetch_backend_provenance,
)
from verifier.service.app import _PIN_MISMATCH_DETAIL

_EXAMPLES = Path(__file__).parents[1] / "examples"


def _verdict(
    *, verified: bool, layer: str, failing: tuple[tuple[str, _RespMethod], ...] = ()
) -> _RespVerdict:
    results = tuple(
        _RespCheck(check=check, method=method, status="fail") for check, method in failing
    )
    return _RespVerdict(verified=verified, layer=layer, results=results)


# --- verdict buckets ----------------------------------------------------------
def test_classify_verified() -> None:
    assert _classify(_verdict(verified=True, layer="verify")) == "verified"


def test_classify_decode_layer_is_schema_bucket() -> None:
    # Bucket != check family: the schema BUCKET is the decode LAYER.
    assert (
        _classify(
            _verdict(
                verified=False,
                layer="decode",
                failing=(("spec.decode", "schema_validation"),),
            )
        )
        == "schema"
    )


def test_classify_policy_only_when_all_failing_families_policy() -> None:
    verdict = _verdict(
        verified=False,
        layer="verify",
        failing=(("label.quantitative_units_present", "deterministic_recompute"),),
    )
    assert _classify(verdict) == "policy"


def test_classify_mixed_families_is_semantic() -> None:
    # A policy failure alongside a semantic one buckets SEMANTIC (policy must be exclusive).
    verdict = _verdict(
        verified=False,
        layer="verify",
        failing=(
            ("label.quantitative_units_present", "deterministic_recompute"),
            ("encoding.fields_exist_in_plotted_table", "deterministic_recompute"),
        ),
    )
    assert _classify(verdict) == "semantic"


def test_classify_verify_family_named_schema_is_semantic() -> None:
    # The schema.* check FAMILY is a verify-layer failure -> semantic, never the schema bucket.
    assert (
        _classify(
            _verdict(
                verified=False,
                layer="verify",
                failing=(("schema.fields_exist", "deterministic_recompute"),),
            )
        )
        == "semantic"
    )


def test_classify_resource_method_as_policy() -> None:
    verdict = _verdict(
        verified=False,
        layer="verify",
        failing=(("resource.file_bytes", "resource_policy"),),
    )
    assert _classify(verdict) == "policy"


def test_classify_empty_failing_set_is_semantic() -> None:
    # Contract-precluded drift shape (verified False yet nothing failed): falls to semantic,
    # never a vacuous policy count (codex-review M3.4a F2).
    assert _classify(_verdict(verified=False, layer="verify")) == "semantic"


# --- fault buckets ------------------------------------------------------------
def test_fault_pin_mismatch_is_off_request_and_detail_matches_app() -> None:
    # The harness duplicates app.py's pin detail string by design; this assertion is the drift
    # guard — if app.py rewords the 502 detail, off_request would silently misbucket as
    # upstream_fault on the next live run.
    assert _classify_fault(502, _PIN_MISMATCH_DETAIL) == "off_request"


def test_fault_other_5xx_is_upstream() -> None:
    assert _classify_fault(502, "model backend returned HTTP 500") == "upstream_fault"
    assert _classify_fault(503, "") == "upstream_fault"
    assert _classify_fault(500, "the verifier encountered an internal error") == "upstream_fault"


def test_fault_422_is_prompt_policy_not_harness_error() -> None:
    bucket = _classify_fault(422, "the proposer input exceeds policy")
    assert bucket == "prompt_policy"
    tally = _Tally()
    _tally_fault(tally, bucket)
    rates = _rate_block(tally)
    assert rates.prompt_policy_count == 1
    assert rates.harness_error_count == 0
    assert rates.upstream_fault_count == 0


def test_fault_4xx_is_harness_error() -> None:
    assert _classify_fault(400, "malformed propose request body") == "harness_error"
    assert _classify_fault(404, "no such dataset") == "harness_error"


def test_rate_block_reports_json_object_rate_distinct_from_validity() -> None:
    # Guards the tool_call_rate -> json_object_rate rename: the rate is json_object / n and stays
    # DISTINCT from json_validity_rate (a reply can be valid JSON that is not an object, e.g. a
    # bare string or array), so the two counters must never be conflated.
    tally = _Tally(n=4, json_object=1, json_valid=3)
    rates = _rate_block(tally)
    assert rates.json_object_rate == 0.25
    assert rates.json_validity_rate == 0.75


# --- reply shape + de-fence ---------------------------------------------------
def test_reply_shape_taxonomy() -> None:
    assert _reply_shape("") == "empty"
    assert _reply_shape("  \n ") == "empty"
    assert _reply_shape('{"version": "vplot-0.1"}') == "bare_object"
    assert _reply_shape('```json\n{"a": 1}\n```') == "fenced"
    assert _reply_shape("prose then ```\n{}\n``` after") == "fenced"  # fence anywhere wins
    assert _reply_shape("Here is a chart description.") == "other"


def test_defenced_json_valid() -> None:
    assert _defenced_json_valid('```json\n{"a": 1}\n```') is True
    assert _defenced_json_valid("```json\nnot json\n```") is False
    assert _defenced_json_valid('{"a": 1}') is True
    # An UNCLOSED fence (a cap-truncated reply) never matches the fence regex, so the whole
    # reply — fence markers included — must parse, and it does not.
    assert _defenced_json_valid('```json\n{"a": 1}') is False


# --- the propose-200 decoder: embed vs. bare ----------------------------------
def test_decode_propose_result_reads_embed_and_bare() -> None:
    # A verified-success 200 is the Open WebUI Location-variant embed ([ProposeResult, summary]
    # array marked by a Location header) -> take element0; a non-verified 200 is the bare
    # ProposeResult object. Both yield the structured result the report tallies. A weak model
    # verifies only a minority of prompts live, so both shapes occur; each must decode here.
    verified = {
        "verified": True,
        "layer": "verify",
        "results": [],
        "attempt_id": "a" * 64,
    }
    embed = msgspec.json.encode([{"model_reply": "spec", "verdict": verified}, "chart summary"])
    embedded = httpx.Response(200, content=embed, headers={"location": "http://x/chart/id"})
    from_embed = _decode_propose_result(embedded)
    assert from_embed.model_reply == "spec"
    assert from_embed.verdict.verified is True
    # A bare 200 (no Location header) is the non-verified ProposeResult object, as before.
    failed = {
        "verified": False,
        "layer": "decode",
        "results": [],
        "attempt_id": "b" * 64,
    }
    bare = msgspec.json.encode({"model_reply": "```json\n{}\n```", "verdict": failed})
    from_bare = _decode_propose_result(httpx.Response(200, content=bare))
    assert from_bare.model_reply == "```json\n{}\n```"
    assert from_bare.verdict.verified is False


def test_fetch_backend_provenance_uses_backend_root_health() -> None:
    schema_digest = "sha256:" + "a" * 64

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "model_name": "model-id",
                "device": "NPU",
                "structured_output": True,
                "vplot_schema_sha256": schema_digest,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provenance = fetch_backend_provenance(client, "http://backend.test/v1")
    assert provenance == BackendProvenance(
        model_name="model-id",
        device="NPU",
        structured_output=True,
        vplot_schema_sha256=schema_digest,
    )


def test_fetch_backend_provenance_non_200_is_none() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "unavailable"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert fetch_backend_provenance(client, "http://backend.test/v1") is None


def test_fetch_backend_provenance_old_health_shape_is_none() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert fetch_backend_provenance(client, "http://backend.test/v1") is None


@pytest.mark.parametrize(
    "result",
    [
        {"check": "data.header", "status": "fail"},
        {"check": "data.header", "method": "unknown", "status": "fail"},
    ],
    ids=["missing", "outside-closed-vocabulary"],
)
def test_response_consumer_requires_closed_check_method(result: dict[str, str]) -> None:
    payload = msgspec.json.encode({"verified": False, "layer": "verify", "results": [result]})
    with pytest.raises(msgspec.ValidationError, match="method"):
        msgspec.json.decode(payload, type=_RespVerdict)


# --- corpus identity pins re-derived from the tree -----------------------------
def test_schema_digest_matches_committed_schema_bytes() -> None:
    expected = "sha256:" + hashlib.sha256(_SCHEMA_PATH.read_bytes()).hexdigest()
    assert _schema_digest() == expected


def test_git_provenance_reports_untracked_despite_suppressing_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The explicit --untracked-files=normal must defeat an ambient status.showUntrackedFiles=no:
    # an untracked file still marks the tree dirty, so provenance cannot mislabel it clean (a bare
    # `git status --porcelain` honors the config and would hide it). HEAD is None in a fresh,
    # commit-less repo, exercising the best-effort None branch.
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not available")
    monkeypatch.chdir(tmp_path)
    subprocess.run([git, "init", "-q"], check=True)  # noqa: S603 — which()-resolved git
    subprocess.run(  # noqa: S603 — which()-resolved git
        [git, "config", "status.showUntrackedFiles", "no"], check=True
    )
    (tmp_path / "untracked.txt").write_text("x", encoding="utf-8")
    commit, dirty = _git_provenance()
    assert dirty is True
    assert commit is None


def test_corpus_digest_pins_match_tree() -> None:
    # The __main__ pins must equal a fresh digest of the real M1 goldens: a corpus edit without
    # a conscious re-pin fails HERE (portable gate), not only on the next live run.
    index = msgspec.json.decode((_EXAMPLES / "index.json").read_bytes(), type=_Index)
    bad = tuple(entry.file for entry in index.bad_specs)
    good = tuple(entry.file for entry in index.good_specs)
    assert len(bad) == _EXPECTED_BAD_CORPUS_SIZE
    assert len(good) == _EXPECTED_GOOD_CORPUS_SIZE
    assert _corpus_digest(_EXAMPLES / "bad_specs", bad) == _EXPECTED_BAD_CORPUS_DIGEST
    assert _corpus_digest(_EXAMPLES / "good_specs", good) == _EXPECTED_GOOD_CORPUS_DIGEST


def test_corpus_digest_is_content_and_name_sensitive(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_bytes(b"{}")
    (tmp_path / "b.json").write_bytes(b"{}")
    base = _corpus_digest(tmp_path, ("a.json", "b.json"))
    assert _corpus_digest(tmp_path, ("b.json", "a.json")) == base  # order-insensitive (sorted)
    # Same cardinality, same bytes, one file RENAMED -> different digest (names are hashed).
    (tmp_path / "c.json").write_bytes(b"{}")
    assert _corpus_digest(tmp_path, ("b.json", "c.json")) != base  # name-sensitive
    (tmp_path / "a.json").write_bytes(b"{ }")
    assert _corpus_digest(tmp_path, ("a.json", "b.json")) != base  # content-sensitive
    assert _corpus_digest(tmp_path, ("a.json",)) != base  # membership-sensitive


# --- the guarantee runner over a MockTransport mini-corpus ----------------------
def _mini_corpus(root: Path) -> None:
    """One bad + one good golden with an index shaped like examples/index.json."""
    (root / "bad_specs").mkdir()
    (root / "good_specs").mkdir()
    (root / "bad_specs" / "b1.json").write_bytes(b'{"marker": "bad"}')
    (root / "good_specs" / "g1.json").write_bytes(b'{"marker": "good"}')
    index = {"bad_specs": [{"file": "b1.json"}], "good_specs": [{"file": "g1.json"}]}
    (root / "index.json").write_bytes(msgspec.json.encode(index))


def _verdict_response(*, verified: bool) -> httpx.Response:
    return httpx.Response(200, json={"verified": verified, "layer": "verify", "results": []})


def test_run_guarantee_healthy_verifier_counts_zero(tmp_path: Path) -> None:
    _mini_corpus(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        # A healthy verifier: the bad golden fails, the good golden verifies.
        return _verdict_response(verified=b'"good"' in request.content)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        block = _run_guarantee(client, "http://verifier.test", tmp_path)
    assert block.bad_corpus_false_accept_count == 0
    assert block.good_corpus_false_reject_count == 0
    assert block.bad_corpus_transport_errors == 0
    assert block.good_corpus_transport_errors == 0
    assert block.bad_corpus_size == 1
    assert block.good_corpus_size == 1
    assert block.bad_corpus_digest == _corpus_digest(tmp_path / "bad_specs", ("b1.json",))
    assert block.good_corpus_digest == _corpus_digest(tmp_path / "good_specs", ("g1.json",))


def test_run_guarantee_counts_regressions_per_corpus(tmp_path: Path) -> None:
    # A regression in BOTH directions: the bad golden verifies (false accept) and the good
    # golden fails (false reject) — a swapped regression_verdict mutant fails both asserts.
    _mini_corpus(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return _verdict_response(verified=b'"bad"' in request.content)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        block = _run_guarantee(client, "http://verifier.test", tmp_path)
    assert block.bad_corpus_false_accept_count == 1
    assert block.good_corpus_false_reject_count == 1
    assert block.bad_corpus_transport_errors == 0
    assert block.good_corpus_transport_errors == 0


def test_run_guarantee_transport_faults_never_count_as_verdicts(tmp_path: Path) -> None:
    # A non-200 (bad corpus) and a connect error (good corpus) both land in the per-corpus
    # transport counters — never a false accept/reject; the invalid-run signal is transport>0.
    _mini_corpus(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if b'"bad"' in request.content:
            return httpx.Response(500, json={"detail": "boom"})
        msg = "connection refused"
        raise httpx.ConnectError(msg)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        block = _run_guarantee(client, "http://verifier.test", tmp_path)
    assert block.bad_corpus_transport_errors == 1
    assert block.good_corpus_transport_errors == 1
    assert block.bad_corpus_false_accept_count == 0
    assert block.good_corpus_false_reject_count == 0


# --- exit-code validity matrix --------------------------------------------------
def _valid_report(**guarantee_overrides: int | str) -> Report:
    guarantee = GuaranteeBlock(
        bad_corpus_size=_EXPECTED_BAD_CORPUS_SIZE,
        bad_corpus_digest=_EXPECTED_BAD_CORPUS_DIGEST,
        bad_corpus_false_accept_count=0,
        bad_corpus_transport_errors=0,
        good_corpus_size=_EXPECTED_GOOD_CORPUS_SIZE,
        good_corpus_digest=_EXPECTED_GOOD_CORPUS_DIGEST,
        good_corpus_false_reject_count=0,
        good_corpus_transport_errors=0,
    )
    if guarantee_overrides:
        guarantee = msgspec.structs.replace(guarantee, **guarantee_overrides)
    rates = RateBlock(
        n=100,
        json_object_rate=0.0,
        json_validity_rate=0.0,
        schema_failure_rate=1.0,
        semantic_failure_rate=0.0,
        policy_failure_rate=0.0,
        verified_render_rate=0.0,
        off_request_count=0,
        prompt_policy_count=0,
        upstream_fault_count=0,
        harness_error_count=0,
    )
    shape = ReplyShapeBlock(
        n=100, fenced=97, bare_object=2, empty=0, other=1, defenced_json_valid=24
    )
    return Report(
        meta=MetaBlock(
            served_model="m",
            prompt_count=100,
            categories=("normal",),
            reproducibility="r",
            git_commit="abcdef0",
            git_dirty=False,
            vplot_schema_sha256="sha256:" + "0" * 64,
            model_probe_url="http://127.0.0.1:8001/v1",
            backend=None,
        ),
        guarantee=guarantee,
        observations=ObservationsBlock(
            overall=rates, by_category={}, top_failure_modes=(), reply_shape=shape
        ),
    )


def test_exit_code_valid_run_is_zero() -> None:
    # The recorded M3.4b shape (a fully-failing weak model) is the EXPECTED success.
    assert _exit_code(_valid_report()) == 0


@pytest.mark.parametrize(
    "override",
    [
        {"bad_corpus_false_accept_count": 1},
        {"bad_corpus_transport_errors": 1},
        {"bad_corpus_size": 17},
        {"bad_corpus_digest": "0" * 64},
        {"good_corpus_false_reject_count": 1},
        {"good_corpus_transport_errors": 1},
        {"good_corpus_size": 9},
        {"good_corpus_digest": "0" * 64},
    ],
    ids=[
        "false-accept",
        "bad-transport",
        "bad-size",
        "bad-digest",
        "false-reject",
        "good-transport",
        "good-size",
        "good-digest",
    ],
)
def test_exit_code_guarantee_violations_are_invalid(override: dict[str, int | str]) -> None:
    assert _exit_code(_valid_report(**override)) == 1


def test_exit_code_prompt_policy_harness_error_and_void_run_are_invalid() -> None:
    report = _valid_report()
    prompt_policy = msgspec.structs.replace(report.observations.overall, prompt_policy_count=1)
    observations = msgspec.structs.replace(report.observations, overall=prompt_policy)
    assert _exit_code(msgspec.structs.replace(report, observations=observations)) == 1
    overall = msgspec.structs.replace(report.observations.overall, harness_error_count=1)
    observations = msgspec.structs.replace(report.observations, overall=overall)
    assert _exit_code(msgspec.structs.replace(report, observations=observations)) == 1
    void = msgspec.structs.replace(report.observations.overall, n=0)
    observations = msgspec.structs.replace(report.observations, overall=void)
    assert _exit_code(msgspec.structs.replace(report, observations=observations)) == 1
