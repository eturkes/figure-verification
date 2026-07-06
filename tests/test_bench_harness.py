# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M3-review feedback loop for bench's pure logic (no servers, no sockets).

bench/ is a coverage-excluded runnable harness, not part of the verifier claim — but its
classifiers decide what the eval REPORTS, and until this module they had no standing tests (the
M3.4a synthetic-payload exercise was a one-off script, never committed). Locked here:

- the verdict buckets (verified / schema=decode-layer / semantic / policy) incl. the
  policy-requires-policy-family rule and the empty-failing-set drift arm;
- the fault split, incl. the pin-mismatch detail string staying byte-equal to app.py's (the
  harness duplicates it by design — an out-of-tree observer imports no verifier internals — so
  THIS test is the drift guard);
- the reply-shape taxonomy + de-fence rule the headline numbers rest on;
- both corpus identity pins re-derived from the live tree (a corpus edit fails this portable
  gate, not just the next hardware-gated live run);
- the exit-code validity matrix (every single violation flips a valid run to exit 1).
"""

from pathlib import Path

import msgspec
import pytest

from bench.__main__ import (
    _EXPECTED_BAD_CORPUS_DIGEST,
    _EXPECTED_BAD_CORPUS_SIZE,
    _EXPECTED_GOOD_CORPUS_DIGEST,
    _EXPECTED_GOOD_CORPUS_SIZE,
    _exit_code,
)
from bench.harness import (
    GuaranteeBlock,
    MetaBlock,
    ObservationsBlock,
    RateBlock,
    ReplyShapeBlock,
    Report,
    _classify,
    _classify_fault,
    _corpus_digest,
    _defenced_json_valid,
    _Index,
    _reply_shape,
    _RespCheck,
    _RespVerdict,
)
from verifier.service.app import _PIN_MISMATCH_DETAIL

_EXAMPLES = Path(__file__).parents[1] / "examples"


def _verdict(*, verified: bool, layer: str, failing: tuple[str, ...] = ()) -> _RespVerdict:
    results = tuple(_RespCheck(check=check, status="fail") for check in failing)
    return _RespVerdict(verified=verified, layer=layer, results=results)


# --- verdict buckets ----------------------------------------------------------
def test_classify_verified() -> None:
    assert _classify(_verdict(verified=True, layer="verify")) == "verified"


def test_classify_decode_layer_is_schema_bucket() -> None:
    # Bucket != check family: the schema BUCKET is the decode LAYER.
    assert _classify(_verdict(verified=False, layer="decode", failing=("spec.decode",))) == "schema"


def test_classify_policy_only_when_all_failing_families_policy() -> None:
    verdict = _verdict(
        verified=False, layer="verify", failing=("label.quantitative_units_present",)
    )
    assert _classify(verdict) == "policy"


def test_classify_mixed_families_is_semantic() -> None:
    # A policy failure alongside a semantic one buckets SEMANTIC (policy must be exclusive).
    verdict = _verdict(
        verified=False,
        layer="verify",
        failing=("label.quantitative_units_present", "encoding.fields_exist_in_plotted_table"),
    )
    assert _classify(verdict) == "semantic"


def test_classify_verify_family_named_schema_is_semantic() -> None:
    # The schema.* check FAMILY is a verify-layer failure -> semantic, never the schema bucket.
    assert (
        _classify(_verdict(verified=False, layer="verify", failing=("schema.fields_exist",)))
        == "semantic"
    )


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


def test_fault_4xx_is_harness_error() -> None:
    assert _classify_fault(400, "malformed propose request body") == "harness_error"
    assert _classify_fault(404, "no such dataset") == "harness_error"


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


# --- corpus identity pins re-derived from the tree -----------------------------
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
    (tmp_path / "a.json").write_bytes(b"{ }")
    assert _corpus_digest(tmp_path, ("a.json", "b.json")) != base  # content-sensitive
    assert _corpus_digest(tmp_path, ("a.json",)) != base  # membership-sensitive


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
        tool_call_rate=0.0,
        json_validity_rate=0.0,
        schema_failure_rate=1.0,
        semantic_failure_rate=0.0,
        policy_failure_rate=0.0,
        verified_render_rate=0.0,
        off_request_count=0,
        upstream_fault_count=0,
        harness_error_count=0,
    )
    shape = ReplyShapeBlock(
        n=100, fenced=97, bare_object=2, empty=0, other=1, defenced_json_valid=24
    )
    return Report(
        meta=MetaBlock(
            served_model="m", prompt_count=100, categories=("normal",), reproducibility="r"
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


def test_exit_code_harness_error_and_void_run_are_invalid() -> None:
    report = _valid_report()
    overall = msgspec.structs.replace(report.observations.overall, harness_error_count=1)
    observations = msgspec.structs.replace(report.observations, overall=overall)
    assert _exit_code(msgspec.structs.replace(report, observations=observations)) == 1
    void = msgspec.structs.replace(report.observations.overall, n=0)
    observations = msgspec.structs.replace(report.observations, overall=void)
    assert _exit_code(msgspec.structs.replace(report, observations=observations)) == 1
