# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M1.5b verifier tests: structured report + binding + eval-surface + structural encoding.

verify() recomputes the plotted data and emits a VerificationReport; M1.6 renders only
when report.passed. This suite drives it from the M1.3 corpus (examples/index.json):
decode-layer specs never reach verify; pre-table bad specs (binding + eval-surfaced) each
fail with exactly their indexed check and carry no plotted_table; the structural-encoding
bad specs (b11/b12) fail post-eval, so plotted_table stays populated; good specs pass and
inline the recomputation. The quantitative-unit spec (b13) is M1.5c territory, excluded
here. A Hypothesis property pins the spine invariant: verify inlines exactly what eval
recomputes.
"""

import csv
import io
import json
import tempfile
from pathlib import Path
from typing import Any, NoReturn

import msgspec
import pytest
from hypothesis import given
from hypothesis import strategies as st
from msgspec import DecodeError, ValidationError

from verifier import canon, checks, ingest
from verifier.checks import verify
from verifier.eval import evaluate
from verifier.schema import decode_spec

_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLES = _ROOT / "examples"
_GOOD_DIR = _EXAMPLES / "good_specs"
_BAD_DIR = _EXAMPLES / "bad_specs"
_DATA = _ROOT / "data"
_SCHEMAS = _DATA / "schemas"

_INDEX: dict[str, Any] = json.loads((_EXAMPLES / "index.json").read_text(encoding="utf-8"))
_GOOD: list[dict[str, Any]] = _INDEX["good_specs"]
_BAD: list[dict[str, Any]] = _INDEX["bad_specs"]

# Structural encoding checks the M1.5b stage now catches (b11 axis-type, b12 field-absent).
_STRUCTURAL_ENCODING_CHECKS = frozenset(
    {
        "encoding.fields_exist_in_plotted_table",
        "encoding.axis_types_match_fields",
    }
)
# Still deferred to M1.5c: the quantitative-unit check (b13 only).
_DEFERRED_CHECKS = frozenset({"label.quantitative_units_present"})
# The four AFFIRMED passes (true by construction) the spine records as the trust argument.
_AFFIRMATIONS = frozenset(
    {
        "security.no_arbitrary_code",
        "transform.ops_allowed",
        "transform.filters_declared",
        "transform.aggregates_match_recomputation",
    }
)
# decodes=false -> rejected at decode_spec; verify is never reached.
_BAD_DECODE = [b for b in _BAD if not b["decodes"]]
# Pre-table: decodes=true bad specs blocked before the recompute (binding + eval-surface) ->
# plotted_table is None.
_PRE_TABLE_BAD = [
    b
    for b in _BAD
    if b["decodes"] and b["check"] not in _STRUCTURAL_ENCODING_CHECKS | _DEFERRED_CHECKS
]
# Structural-encoding: blocked AFTER eval succeeds (b11/b12) -> plotted_table populated.
_ENCODING_BAD = [b for b in _BAD if b["check"] in _STRUCTURAL_ENCODING_CHECKS]


def _ids(entries: list[dict[str, Any]]) -> list[str]:
    return [Path(e["file"]).stem for e in entries]


def _manifest_for(name: str) -> ingest.Manifest:
    return ingest.load_manifest((_SCHEMAS / f"{Path(name).stem}.json").read_bytes())


# --- corpus split guards (no silent vacuous parametrization) ------------------
def test_corpus_split_covers_each_layer() -> None:
    pre_table_checks = {b["check"] for b in _PRE_TABLE_BAD}
    assert "dataset.hash_matches_source" in pre_table_checks  # binding gate
    assert len(_PRE_TABLE_BAD) >= 7  # b08 binding + b07/b09/b10/b14/b15/b16 eval-surfaced
    assert len(_ENCODING_BAD) == 2  # b11 axis-type + b12 field-absent
    assert _BAD_DECODE  # decode-layer specs exist to assert verify is unreached


# --- decode layer: verify is never reached -----------------------------------
@pytest.mark.parametrize("entry", _BAD_DECODE, ids=_ids(_BAD_DECODE))
def test_decode_layer_specs_never_reach_verify(entry: dict[str, Any]) -> None:
    # decode_spec is the sole accepted untrusted-input path: a decode-layer rejection means
    # no model-proposed VPlotSpec reaches verify() — the trust gate's first line is the
    # decoder. (Structs stay directly constructible; binding-gate path confinement holds
    # regardless — see test_binding_rejects_absolute_name_even_when_target_readable.)
    raw = (_BAD_DIR / entry["file"]).read_bytes()
    with pytest.raises((ValidationError, DecodeError)):
        decode_spec(raw)


# --- pre-table bad specs: each fails its indexed check, no plotted table -------
@pytest.mark.parametrize("entry", _PRE_TABLE_BAD, ids=_ids(_PRE_TABLE_BAD))
def test_pre_table_bad_spec_fails_its_check(entry: dict[str, Any]) -> None:
    spec = decode_spec((_BAD_DIR / entry["file"]).read_bytes())
    manifest = _manifest_for(spec.dataset.name)
    report = verify(spec, manifest, data_dir=_DATA)
    failing = {r.check for r in report.results if r.status == "fail"}
    assert failing == {entry["check"]}  # a non-empty fail set also means not passed
    assert report.plotted_table is None  # binding/eval block short-circuits -> no table
    passing = {r.check for r in report.results if r.status == "pass"}
    assert passing >= _AFFIRMATIONS  # affirmations are retained even on a failing report


# --- structural-encoding bad specs: fail post-eval, plotted table populated ----
@pytest.mark.parametrize("entry", _ENCODING_BAD, ids=_ids(_ENCODING_BAD))
def test_encoding_bad_spec_fails_its_check(entry: dict[str, Any]) -> None:
    # b11/b12 fail in the structural encoding stage, which runs AFTER eval succeeds, so the
    # recomputed plotted_table is populated even though report.passed is False (M1.6 reads it
    # only when passed). The narrowing chain makes each fail exactly its own check: b12's
    # absent field is excluded from the axis-type check, so only fields_exist fails.
    spec = decode_spec((_BAD_DIR / entry["file"]).read_bytes())
    manifest = _manifest_for(spec.dataset.name)
    report = verify(spec, manifest, data_dir=_DATA)
    failing = {r.check for r in report.results if r.status == "fail"}
    assert failing == {entry["check"]}
    assert not report.passed
    assert report.plotted_table is not None  # eval succeeded -> table reflects the recompute


def test_no_false_accepts_excluding_units() -> None:
    # Every bad spec the M1.5b stage can catch (binding + eval-surface + structural encoding)
    # is blocked; b13 is excluded -> its only defect is a missing unit, checked in M1.5c.
    accepted = 0
    for entry in _PRE_TABLE_BAD + _ENCODING_BAD:
        spec = decode_spec((_BAD_DIR / entry["file"]).read_bytes())
        manifest = _manifest_for(spec.dataset.name)
        if verify(spec, manifest, data_dir=_DATA).passed:
            accepted += 1
    assert accepted == 0


# --- good specs: pass and inline the recomputation ---------------------------
@pytest.mark.parametrize("entry", _GOOD, ids=_ids(_GOOD))
def test_good_spec_passes_and_inlines_recomputation(entry: dict[str, Any]) -> None:
    spec = decode_spec((_GOOD_DIR / entry["file"]).read_bytes())
    manifest = _manifest_for(spec.dataset.name)
    report = verify(spec, manifest, data_dir=_DATA)
    assert report.passed
    assert report.plotted_table is not None  # narrow Table | None for the hash compare
    csv_bytes = (_DATA / spec.dataset.name).read_bytes()
    expected = evaluate(spec, manifest, csv_bytes)
    assert canon.hash_table(report.plotted_table) == canon.hash_table(expected)


# --- report structure: the affirmations are recorded, not implicit ------------
def test_report_records_all_affirmations_on_pass() -> None:
    # The four AFFIRMED passes are part of the recorded trust argument; pin that a good
    # spec's passing checks are exactly the affirmations plus the active binding gate and the
    # two structural encoding checks, so dropping _affirmations() is caught (the
    # pass/fail-name tests alone would not notice).
    spec = decode_spec((_GOOD_DIR / "g01_total_revenue_by_month.json").read_bytes())
    manifest = _manifest_for(spec.dataset.name)
    report = verify(spec, manifest, data_dir=_DATA)
    passing = {r.check for r in report.results if r.status == "pass"}
    assert passing == _AFFIRMATIONS | {
        "dataset.hash_matches_source",
        "encoding.fields_exist_in_plotted_table",
        "encoding.axis_types_match_fields",
    }
    assert all(r.severity == "blocking" for r in report.results)


# --- dataset-binding gate: escape + missing (mismatch is covered by b08) ------
def test_binding_rejects_symlink_escape(tmp_path: Path) -> None:
    # A decoded DatasetName forbids '/', so the only path escape is a symlink inside
    # data_dir pointing out; resolve() exposes the target as a non-relative path.
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.csv").write_bytes(b"month,revenue\n2024-01,1.00\n")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "sales.csv").symlink_to(outside / "secret.csv")
    spec = decode_spec((_GOOD_DIR / "g01_total_revenue_by_month.json").read_bytes())
    manifest = _manifest_for(spec.dataset.name)  # both bind sales.csv -> pairing OK
    report = verify(spec, manifest, data_dir=data_dir)
    assert not report.passed
    assert report.plotted_table is None
    failing = {r.check for r in report.results if r.status == "fail"}
    assert failing == {"dataset.hash_matches_source"}


def test_binding_rejects_missing_source(tmp_path: Path) -> None:
    # An empty data_dir: the bound name resolves inside it (no escape) but cannot be read.
    spec = decode_spec((_GOOD_DIR / "g01_total_revenue_by_month.json").read_bytes())
    manifest = _manifest_for(spec.dataset.name)
    report = verify(spec, manifest, data_dir=tmp_path)
    assert not report.passed
    assert report.plotted_table is None
    failing = {r.check for r in report.results if r.status == "fail"}
    assert failing == {"dataset.hash_matches_source"}


def test_binding_failure_short_circuits_eval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The trust spine must never compute on unauthenticated bytes: a binding failure must
    # return before evaluate() is reached. Patch evaluate to a tripwire and prove it stays
    # unreached when the bound source is missing.
    def _no_eval(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "evaluate ran after a binding failure short-circuit"
        raise AssertionError(msg)

    monkeypatch.setattr(checks, "evaluate", _no_eval)
    spec = decode_spec((_GOOD_DIR / "g01_total_revenue_by_month.json").read_bytes())
    manifest = _manifest_for(spec.dataset.name)
    report = verify(spec, manifest, data_dir=tmp_path)  # empty dir -> source missing
    assert not report.passed
    assert report.plotted_table is None
    failing = {r.check for r in report.results if r.status == "fail"}
    assert failing == {"dataset.hash_matches_source"}


def test_binding_rejects_absolute_name_even_when_target_readable(tmp_path: Path) -> None:
    # Defense in depth: confinement does not rely on the DatasetName pattern. A spec built
    # OUTSIDE decode_spec (msgspec structs are directly constructible) with an absolute name
    # to a real, hash-MATCHING file outside data_dir is still blocked — resolve() +
    # is_relative_to rejects before the read, so a correct declared hash cannot smuggle
    # outside bytes past the gate.
    outside = tmp_path / "outside"
    outside.mkdir()
    payload = b"month,revenue\n2024-01,1.00\n"
    secret = outside / "secret.csv"
    secret.write_bytes(payload)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    base = decode_spec((_GOOD_DIR / "g01_total_revenue_by_month.json").read_bytes())
    evil = msgspec.structs.replace(
        base,
        dataset=msgspec.structs.replace(
            base.dataset, name=str(secret), hash=canon.hash_dataset(payload)
        ),
    )
    manifest = msgspec.structs.replace(_manifest_for(base.dataset.name), dataset=str(secret))
    report = verify(evil, manifest, data_dir=data_dir)
    assert not report.passed  # declared hash matches the outside file, yet confinement blocks
    assert report.plotted_table is None
    failing = {r.check for r in report.results if r.status == "fail"}
    assert failing == {"dataset.hash_matches_source"}


# --- pairing precondition: a caller bug, not a verification outcome -----------
def test_pairing_mismatch_raises_value_error() -> None:
    spec = decode_spec((_GOOD_DIR / "g01_total_revenue_by_month.json").read_bytes())
    paired = _manifest_for(spec.dataset.name)
    mispaired = msgspec.structs.replace(paired, dataset="other.csv")
    with pytest.raises(ValueError):
        verify(spec, mispaired, data_dir=_DATA)


# --- spine property: verify inlines exactly what eval recomputes --------------
# A fixed string-key + scale-2-numeric manifest with a group_by/sum/sort pipeline;
# Hypothesis varies only the rows (so no valid-spec generation is needed).
_PROP_HEADER = ["k", "v"]
_PROP_MANIFEST = ingest.load_manifest(
    msgspec.json.encode(
        {
            "dataset": "t.csv",
            "columns": [
                {"type": "string", "name": "k"},
                {"type": "numeric", "name": "v", "scale": 2},
            ],
        }
    )
)
_PROP_SPEC = decode_spec(
    msgspec.json.encode(
        {
            "version": "vplot-0.1",
            "dataset": {"name": "t.csv", "hash": "sha256:" + "0" * 64},
            "transform": [
                {"op": "group_by", "keys": ["k"]},
                {"op": "aggregate", "measures": [{"field": "v", "fn": "sum", "as": "total"}]},
                {"op": "sort", "by": [{"field": "total", "order": "descending"}]},
            ],
            "mark": "bar",
            "encoding": {
                "x": {"field": "k", "type": "nominal"},
                "y": {"field": "total", "type": "quantitative"},
            },
        }
    )
)


def _scale2(units: int) -> str:
    # Exact scale-2 decimal text via integer arithmetic (no float); ingest coerces cleanly.
    sign = "-" if units < 0 else ""
    mag = abs(units)
    return f"{sign}{mag // 100}.{mag % 100:02d}"


_NUMERIC_OR_NULL = st.integers(min_value=-(10**10), max_value=10**10).map(_scale2) | st.just("")
_PROP_ROWS = st.lists(
    st.tuples(st.text(st.characters(codec="utf-8"), max_size=4), _NUMERIC_OR_NULL),
    max_size=6,
)


def _prop_csv(rows: list[tuple[str, str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_PROP_HEADER)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


@given(rows=_PROP_ROWS)
def test_verify_inlines_exactly_the_recomputation(rows: list[tuple[str, str]]) -> None:
    csv_bytes = _prop_csv(rows)
    live_hash = canon.hash_dataset(csv_bytes)
    spec = msgspec.structs.replace(
        _PROP_SPEC, dataset=msgspec.structs.replace(_PROP_SPEC.dataset, hash=live_hash)
    )
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        (data_dir / "t.csv").write_bytes(csv_bytes)
        report = verify(spec, _PROP_MANIFEST, data_dir=data_dir)
    assert report.passed
    assert report.plotted_table is not None
    expected = evaluate(spec, _PROP_MANIFEST, csv_bytes)
    assert canon.hash_table(report.plotted_table) == canon.hash_table(expected)
