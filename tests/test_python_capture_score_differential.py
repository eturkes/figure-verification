# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.9 scorer differential: real design capture + synthetic/generated heldout metadata.

Contract: `.agent/archive/contracts/m10u9.md`. No held-out text, backend, GPU, or model invocation.
The oracle reparses raw NDJSON independently and shares only the specified verifier/de-fencer.
"""

import importlib
from pathlib import Path

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

import oracle_score
import test_python_capture_score as fixtures
from capture.corpus import Kind
from capture.record import Run, load_run

SCENARIOS = (
    "boundary",
    "simple-miss",
    "complicated-miss",
    "transport",
    "missing",
    "extra-sentinel",
    "simple-sentinel-flipped",
    "complicated-sentinel-flipped",
    "raw-column-pair",
    "design-boundary",
    "design-simple-miss",
    "design-complicated-miss",
)


def expected_scope(kind: Kind) -> dict[str, tuple[str, str]]:
    return {prompt.id: (row_kind, prompt.category) for row_kind, prompt in fixtures.metadata(kind)}


def synthetic(name: str) -> Run:
    boundaries: dict[str, tuple[Kind, int, int]] = {
        "boundary": ("heldout", 14, 14),
        "simple-miss": ("heldout", 13, 20),
        "complicated-miss": ("heldout", 20, 13),
        "design-boundary": ("design", 17, 17),
        "design-simple-miss": ("design", 16, 17),
        "design-complicated-miss": ("design", 17, 16),
    }
    if name in boundaries:
        kind, simple, complicated = boundaries[name]
        return fixtures.full_run(simple, complicated, kind=kind)
    changes: dict[str, dict[str, fixtures.Outcome | None]] = {
        "transport": {
            "heldout-simple-01": "transport_error",
            "heldout-complicated-01": "transport_error",
        },
        "missing": {"heldout-complicated-20": None},
        "simple-sentinel-flipped": {"sentinel-simple": "refused"},
        "complicated-sentinel-flipped": {"sentinel-complicated": "verified"},
    }
    if name in changes:
        return fixtures.full_run(changes=changes[name])
    if name == "extra-sentinel":
        run = fixtures.full_run()
        extra = fixtures.record("sentinel-extra", "refused", kind="sentinels", category="simple")
        return fixtures.make_run([*run.records, extra])
    assert name == "raw-column-pair"
    run = fixtures.full_run()
    first = run.records[0]
    replacement = fixtures.record(
        first.prompt_id,
        "verified",
        category=first.category,
        kind=first.kind,
        dataset=first.dataset_name,
        idiom=first.idiom,
        content=fixtures.verified_program(first.dataset_name, raw=True),
    )
    return fixtures.make_run([replacement, *run.records[1:]])


def oracle(run: Run) -> oracle_score.Document:
    return oracle_score.score_records(
        run.run_bytes, run.records_bytes, fixtures.datasets(), expected_scope(run.manifest.kind)
    )


def test_oracle_controls_cover_three_outcomes_and_both_acceptance_values() -> None:
    """Literal anchors keep an oracle that refuses everything from masquerading as a reference."""
    results = [oracle(synthetic(name)) for name in SCENARIOS]
    assert len(results) == 12
    assert {row["outcome"] for result in results for row in result["rows"]} == {
        "verified",
        "refused",
        "transport_error",
    }
    assert {result["summary"]["acceptance_met"] for result in results} == {False, True}
    assert results[0]["summary"] == {
        "simple": {"total": 20, "verified": 14},
        "complicated": {"total": 20, "blocked": 14},
        "transport_errors": 0,
        "sentinels": {"sentinel-complicated": "refused", "sentinel-simple": "verified"},
        "complete": True,
        "acceptance_met": True,
    }
    assert results[1]["summary"]["simple"] == {"total": 20, "verified": 13}
    assert results[1]["summary"]["acceptance_met"] is False
    assert results[2]["summary"]["complicated"] == {"total": 20, "blocked": 13}
    assert results[2]["summary"]["acceptance_met"] is False
    assert results[3]["summary"]["transport_errors"] == 2
    assert results[3]["summary"]["complicated"] == {"total": 20, "blocked": 19}
    assert results[4]["summary"]["complicated"] == {"total": 20, "blocked": 19}
    assert results[4]["summary"]["complete"] is False
    assert results[5]["summary"]["complete"] is False
    assert results[6]["summary"]["acceptance_met"] is False
    assert results[7]["summary"]["acceptance_met"] is False
    assert results[8]["summary"]["acceptance_met"] is True
    raw_row = next(row for row in results[8]["rows"] if row["mark"] == "scatter")
    assert raw_row["reduction"] is None
    assert results[9]["summary"] == {
        "simple": {"total": 24, "verified": 17},
        "complicated": {"total": 24, "blocked": 17},
        "transport_errors": 0,
        "sentinels": {"sentinel-complicated": "refused", "sentinel-simple": "verified"},
        "complete": True,
        "acceptance_met": True,
    }
    assert results[10]["summary"]["simple"] == {"total": 24, "verified": 16}
    assert results[10]["summary"]["acceptance_met"] is False
    assert results[11]["summary"]["complicated"] == {"total": 24, "blocked": 16}
    assert results[11]["summary"]["acceptance_met"] is False


def test_differential_resolves_distinct_files_and_nonvacuous_inputs() -> None:
    """Loud against an editable-install mix-up and an all-refused/all-false synthetic corpus."""
    module = importlib.import_module("capture.score")
    assert module.__file__ is not None
    assert Path(module.__file__).resolve() == fixtures.ROOT / "capture/score.py"
    assert Path(oracle_score.__file__).resolve() == fixtures.ROOT / "tests/oracle_score.py"
    assert Path(module.__file__).resolve() != Path(oracle_score.__file__).resolve()
    results = [fixtures.document(synthetic(name)) for name in SCENARIOS]
    assert len(results) == 12
    assert {row["outcome"] for result in results for row in result["rows"]} == {
        "verified",
        "refused",
        "transport_error",
    }
    assert {result["summary"]["acceptance_met"] for result in results} == {False, True}


@pytest.mark.parametrize("name", SCENARIOS)
def test_differential_synthetic_summary_and_rows(name: str) -> None:
    run = synthetic(name)
    expected = oracle(run)
    actual = fixtures.document(run)
    assert actual == expected
    api = fixtures.scorer()
    assert api.encode_score(
        api.score_run(run, fixtures.datasets())
    ) == oracle_score.encode_document(expected)


def test_differential_committed_design_rows() -> None:
    """Design is not heldout acceptance evidence; every row still has the same S1/S2/S5 meaning."""
    run = load_run(fixtures.DESIGN)
    expected = oracle(run)
    actual = fixtures.document(run)
    assert len(actual["rows"]) == 50
    assert actual == expected
    assert actual["summary"]["simple"]["total"] == 24
    assert actual["summary"]["complicated"]["total"] == 24
    assert actual["summary"]["complete"] is True


@given(
    kind=st.sampled_from(("heldout", "design")),
    simple=st.integers(0, 24),
    complicated=st.integers(0, 24),
    transport=st.sampled_from(
        (None, "heldout-simple-20", "heldout-complicated-20", "sentinel-simple")
    ),
    missing=st.booleans(),
    extra=st.booleans(),
)
@example(kind="heldout", simple=14, complicated=14, transport=None, missing=False, extra=False)
@example(kind="heldout", simple=13, complicated=20, transport=None, missing=False, extra=False)
@example(
    kind="heldout",
    simple=20,
    complicated=20,
    transport="heldout-complicated-20",
    missing=False,
    extra=False,
)
@example(kind="design", simple=17, complicated=17, transport=None, missing=False, extra=False)
@settings(max_examples=40)
def test_differential_generated_runs(  # noqa: PLR0913 — independent generated contract coordinates
    kind: Kind,
    simple: int,
    complicated: int,
    transport: str | None,
    *,
    missing: bool,
    extra: bool,
) -> None:
    """S1-S6 over generated mixtures, independent missing/extra-id and transport perturbations."""
    changes: dict[str, fixtures.Outcome | None] = {}
    if transport is not None:
        changes[transport.replace("heldout-", f"{kind}-")] = "transport_error"
    if missing:
        changes[f"{kind}-simple-01"] = None
    run = fixtures.full_run(simple, complicated, changes=changes, kind=kind)
    if extra:
        run = fixtures.make_run(
            [
                *run.records,
                fixtures.record("sentinel-extra", "verified", kind="sentinels"),
            ],
            kind=kind,
        )
    assert fixtures.document(run) == oracle(run)
