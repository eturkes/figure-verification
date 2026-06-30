# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M1.5c verifier tests: structured report + binding + eval-surface + encoding/label stage.

verify() recomputes the plotted data and emits a VerificationReport; M1.6 renders only
when report.passed. This suite drives it from the M1.3 corpus (examples/index.json):
decode-layer specs never reach verify; pre-table bad specs (binding + eval-surfaced) each
fail with exactly their indexed check and carry no plotted_table; the encoding/label bad
specs (b11 axis-type, b12 field-absent, b13 missing-unit) fail post-eval, so plotted_table
stays populated; good specs pass and inline the recomputation. A direct matrix test pins
every VPlot_SEMANTICS.md section 7 channel-type ↔ column-kind pair behaviorally (branch
coverage cannot reach individual map entries); direct unit_source tests pin every arm of
the count-exempt position-aware unit lineage (terminating + sound on reused output names). A
Hypothesis property pins the spine invariant: verify inlines exactly what eval recomputes.
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
from verifier.schema import Aggregate, Measure, VPlotSpec, decode_spec

_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLES = _ROOT / "examples"
_GOOD_DIR = _EXAMPLES / "good_specs"
_BAD_DIR = _EXAMPLES / "bad_specs"
_DATA = _ROOT / "data"
_SCHEMAS = _DATA / "schemas"

_INDEX: dict[str, Any] = json.loads((_EXAMPLES / "index.json").read_text(encoding="utf-8"))
_GOOD: list[dict[str, Any]] = _INDEX["good_specs"]
_BAD: list[dict[str, Any]] = _INDEX["bad_specs"]

# Encoding/label checks the M1.5c stage catches (b11 axis-type, b12 field-absent, b13 unit).
_ENCODING_CHECKS = frozenset(
    {
        "encoding.fields_exist_in_plotted_table",
        "encoding.axis_types_match_fields",
        "label.quantitative_units_present",
    }
)
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
_PRE_TABLE_BAD = [b for b in _BAD if b["decodes"] and b["check"] not in _ENCODING_CHECKS]
# Encoding/label: blocked AFTER eval succeeds (b11/b12/b13) -> plotted_table populated.
_ENCODING_BAD = [b for b in _BAD if b["check"] in _ENCODING_CHECKS]


def _ids(entries: list[dict[str, Any]]) -> list[str]:
    return [Path(e["file"]).stem for e in entries]


def _manifest_for(name: str) -> ingest.Manifest:
    return ingest.load_manifest((_SCHEMAS / f"{Path(name).stem}.json").read_bytes())


# --- corpus split guards (no silent vacuous parametrization) ------------------
def test_corpus_split_covers_each_layer() -> None:
    pre_table_checks = {b["check"] for b in _PRE_TABLE_BAD}
    assert "dataset.hash_matches_source" in pre_table_checks  # binding gate
    assert len(_PRE_TABLE_BAD) >= 7  # b08 binding + b07/b09/b10/b14/b15/b16 eval-surfaced
    # All three narrowing arms must have a failing fixture (not duplicates), one each.
    assert {b["check"] for b in _ENCODING_BAD} == _ENCODING_CHECKS
    assert len(_ENCODING_BAD) == len(_ENCODING_CHECKS)  # b11 axis-type + b12 absent + b13 unit
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
    # b11/b12/b13 fail in the encoding/label stage, which runs AFTER eval succeeds, so the
    # recomputed plotted_table is populated even though report.passed is False (M1.6 reads it
    # only when passed). The narrowing chain makes each fail exactly its own check: b12's
    # absent field is excluded from the axis-type and unit checks, and b11's type-mismatched
    # (non-numeric) field is excluded from the unit check, so each fails only its own check.
    spec = decode_spec((_BAD_DIR / entry["file"]).read_bytes())
    manifest = _manifest_for(spec.dataset.name)
    report = verify(spec, manifest, data_dir=_DATA)
    failing = {r.check for r in report.results if r.status == "fail"}
    assert failing == {entry["check"]}
    assert not report.passed
    assert report.plotted_table is not None  # eval succeeded -> table reflects the recompute


# --- count-derived channel: dimensionless -> unit-exempt (end-to-end) ---------
def test_count_derived_channel_is_unit_exempt() -> None:
    # A count-derived quantitative channel is dimensionless, so the unit check exempts it even
    # though its count source (region, a string) carries no unit. Run end-to-end over the real
    # sales.csv so binding + recompute + the unit check's source-None arm all fire on a PASS.
    csv_bytes = (_DATA / "sales.csv").read_bytes()
    spec = decode_spec(
        msgspec.json.encode(
            {
                "version": "vplot-0.1",
                "dataset": {"name": "sales.csv", "hash": canon.hash_dataset(csv_bytes)},
                "transform": [
                    {"op": "group_by", "keys": ["month"]},
                    {
                        "op": "aggregate",
                        "measures": [{"field": "region", "fn": "count", "as": "region_count"}],
                    },
                ],
                "mark": "bar",
                "encoding": {
                    "x": {"field": "month", "type": "nominal"},
                    "y": {"field": "region_count", "type": "quantitative"},
                },
            }
        )
    )
    manifest = _manifest_for("sales.csv")
    report = verify(spec, manifest, data_dir=_DATA)
    assert report.passed  # count exemption -> the unit check passes despite a unitless source
    unit = next(r for r in report.results if r.check == "label.quantitative_units_present")
    assert unit.status == "pass"


def test_count_sum_chain_channel_is_unit_exempt() -> None:
    # A count->sum chain stays dimensionless: count(region) as c, then sum(c) as cc. The unit
    # check must trace cc back THROUGH the sum to the count (not stop at c) and exempt it. Run
    # end-to-end so the multi-aggregate backward walk fires inside verify, not only unit_source.
    csv_bytes = (_DATA / "sales.csv").read_bytes()
    spec = decode_spec(
        msgspec.json.encode(
            {
                "version": "vplot-0.1",
                "dataset": {"name": "sales.csv", "hash": canon.hash_dataset(csv_bytes)},
                "transform": [
                    {"op": "group_by", "keys": ["month"]},
                    {
                        "op": "aggregate",
                        "measures": [{"field": "region", "fn": "count", "as": "c"}],
                    },
                    {"op": "group_by", "keys": ["month"]},
                    {
                        "op": "aggregate",
                        "measures": [{"field": "c", "fn": "sum", "as": "cc"}],
                    },
                ],
                "mark": "bar",
                "encoding": {
                    "x": {"field": "month", "type": "nominal"},
                    "y": {"field": "cc", "type": "quantitative"},
                },
            }
        )
    )
    manifest = _manifest_for("sales.csv")
    report = verify(spec, manifest, data_dir=_DATA)
    assert report.passed  # cc -> sum(c) -> count(region) -> None: exempt through the chain
    unit = next(r for r in report.results if r.check == "label.quantitative_units_present")
    assert unit.status == "pass"


def test_no_false_accepts_over_full_bad_suite() -> None:
    # Every decodes=true bad spec (binding + eval-surface + encoding/label, b13 now included)
    # is blocked: not one reports passed.
    accepted = 0
    for entry in _PRE_TABLE_BAD + _ENCODING_BAD:
        spec = decode_spec((_BAD_DIR / entry["file"]).read_bytes())
        manifest = _manifest_for(spec.dataset.name)
        if verify(spec, manifest, data_dir=_DATA).passed:
            accepted += 1
    assert accepted == 0


# --- §7 compatibility matrix: pin every channel-type x column-kind pair --------
# _CHANNEL_COLUMN_COMPAT is a data table, and 100% BRANCH coverage cannot reach its entries
# (a single `not in` branch covers the whole map), so one wrong entry — a verification bypass
# or a false reject — would slip past the corpus tests, which sample only a few pairs and
# never a FAILING color. Drive _encoding_checks directly over a synthetic one-column-per-kind
# table, asserting the axis-type verdict for all twelve pairs against section 7 restated
# independently here (not imported from checks, so the test is an external oracle).
_COLUMN_OF_KIND: dict[str, canon.Column] = {
    "numeric": canon.NumericColumn(name="n", scale=0),
    "temporal": canon.TemporalColumn(name="t", granularity="date"),
    "string": canon.StringColumn(name="s"),
}
_MATRIX_TABLE = canon.Table(columns=tuple(_COLUMN_OF_KIND.values()), rows=())
# A manifest matching the matrix table so _encoding_checks' unit check can resolve the numeric
# column; n carries a unit so that check never interferes with the axis-type assertions.
_MATRIX_MANIFEST = ingest.load_manifest(
    msgspec.json.encode(
        {
            "dataset": "t.csv",
            "columns": [
                {"type": "numeric", "name": "n", "scale": 0, "unit": "u"},
                {"type": "temporal", "name": "t", "granularity": "date"},
                {"type": "string", "name": "s"},
            ],
        }
    )
)
# VPlot_SEMANTICS.md section 7, transcribed straight from the spec table.
_SECTION7_ADMISSIBLE: dict[str, frozenset[str]] = {
    "quantitative": frozenset({"numeric"}),
    "temporal": frozenset({"temporal"}),
    "ordinal": frozenset({"numeric", "string"}),
    "nominal": frozenset({"string", "numeric"}),
}


def _spec_with_encoding(
    x: tuple[str, str], y: tuple[str, str], color: tuple[str, str] | None = None
) -> VPlotSpec:
    # A minimally-decoding spec (empty transform; _encoding_checks never evaluates) whose
    # encoding carries the channels under test, each given as (field, type).
    enc: dict[str, Any] = {"x": {"field": x[0], "type": x[1]}, "y": {"field": y[0], "type": y[1]}}
    if color is not None:
        enc["color"] = {"field": color[0], "type": color[1]}
    return decode_spec(
        msgspec.json.encode(
            {
                "version": "vplot-0.1",
                "dataset": {"name": "t.csv", "hash": "sha256:" + "0" * 64},
                "transform": [],
                "mark": "bar",
                "encoding": enc,
            }
        )
    )


@pytest.mark.parametrize("ch_type", sorted(_SECTION7_ADMISSIBLE))
@pytest.mark.parametrize("col_kind", sorted(_COLUMN_OF_KIND))
def test_axis_type_matrix_pins_every_section7_pair(ch_type: str, col_kind: str) -> None:
    # y carries the pair under test; x is held at an always-admissible pairing (nominal over
    # the string column) so the axis-type verdict reflects y alone, and both fields exist so
    # fields_exist passes and never masks the result.
    col = _COLUMN_OF_KIND[col_kind]
    spec = _spec_with_encoding(x=("s", "nominal"), y=(col.name, ch_type))
    results = {r.check: r for r in checks._encoding_checks(spec, _MATRIX_TABLE, _MATRIX_MANIFEST)}
    assert results["encoding.fields_exist_in_plotted_table"].status == "pass"
    expected = "pass" if col_kind in _SECTION7_ADMISSIBLE[ch_type] else "fail"
    assert results["encoding.axis_types_match_fields"].status == expected


def test_color_channel_is_type_checked_not_merely_counted() -> None:
    # color present and MISMATCHED (quantitative over the string column) must FAIL the
    # axis-type check with the color field named, proving color is type-checked, not merely
    # admitted by the `color is not None` branch. x/y are held valid.
    spec = _spec_with_encoding(
        x=("s", "nominal"), y=("n", "quantitative"), color=("s", "quantitative")
    )
    results = {r.check: r for r in checks._encoding_checks(spec, _MATRIX_TABLE, _MATRIX_MANIFEST)}
    assert results["encoding.fields_exist_in_plotted_table"].status == "pass"
    axis = results["encoding.axis_types_match_fields"]
    assert axis.status == "fail"
    assert "s" in axis.message  # the color field surfaces in the mismatch list


def test_color_channel_absent_field_is_narrowed_out() -> None:
    # color referencing a non-existent column folds into the fields-exist failure and is
    # excluded from the axis-type check (the narrowing chain), so axis-type still passes on the
    # valid x/y — the narrowing the corpus exercises for x/y, now pinned for color.
    spec = _spec_with_encoding(
        x=("s", "nominal"), y=("n", "quantitative"), color=("ghost", "nominal")
    )
    results = {r.check: r for r in checks._encoding_checks(spec, _MATRIX_TABLE, _MATRIX_MANIFEST)}
    fields = results["encoding.fields_exist_in_plotted_table"]
    assert fields.status == "fail"
    assert "ghost" in fields.message
    assert results["encoding.axis_types_match_fields"].status == "pass"


# --- unit_source: position-aware reverse lineage, every arm ------------------
# The count-exempt unit lineage (VPlot_SEMANTICS.md sections 5 + 7) must be position-aware: a
# reused aggregate output name (legal -- output-uniqueness is per-aggregate) makes a global
# last-wins scan non-terminating or unsound. Each arm constructs the aggregate ops directly
# (the walk reads only .measures/.output/.field/.fn) and pins the resolved source: None =
# count-derived (exempt), a string = the manifest column whose unit is required.
def _agg(*measures: Measure) -> Aggregate:
    return Aggregate(measures=measures)


_LINEAGE_ARMS: list[tuple[str, tuple[Aggregate, ...], str, str | None]] = [
    # no aggregate -> name is a manifest column (select / group_by key / passthrough)
    ("manifest passthrough", (), "aqi", "aqi"),
    # count producer -> dimensionless -> exempt
    (
        "count direct",
        (_agg(Measure(field="region", fn="count", output="region_count")),),
        "region_count",
        None,
    ),
    # non-count terminus -> recurse once, bottom out at a manifest column
    (
        "non-count terminus",
        (_agg(Measure(field="aqi", fn="max", output="max_aqi")),),
        "max_aqi",
        "aqi",
    ),
    # count at depth (count -> sum chain) -> exempt via the backward walk, not one-hop
    (
        "count at depth",
        (
            _agg(Measure(field="date", fn="count", output="c")),
            _agg(Measure(field="c", fn="sum", output="cc")),
        ),
        "cc",
        None,
    ),
    # reused output name FA-guard: w -> v(sum, earlier) -> aqi; a last-wins scan would bind v to
    # the later count(v) and false-accept (exempt). Position-aware resolves v at its producer.
    (
        "surviving producer",
        (
            _agg(Measure(field="aqi", fn="sum", output="v")),
            _agg(
                Measure(field="v", fn="min", output="w"),
                Measure(field="v", fn="count", output="v"),
            ),
        ),
        "w",
        "aqi",
    ),
    # reused output name NT-guard: v -> sum(v) -> count(v) terminates; a last-wins scan cycles v->v
    (
        "loop guard terminates",
        (
            _agg(Measure(field="date", fn="count", output="v")),
            _agg(Measure(field="v", fn="sum", output="v")),
        ),
        "v",
        None,
    ),
    # producer at an EARLIER index: agg0 outputs t; agg1 (count t) produces n, not t, so the
    # latest-first walk finds no t-producer in agg1 and advances to agg0 -> recurse temp_c. The
    # bare tuple is eval-valid: agg1 counts t, which agg0 produced (no destroyed field reference).
    (
        "earlier producer",
        (
            _agg(Measure(field="temp_c", fn="sum", output="t")),
            _agg(Measure(field="t", fn="count", output="n")),
        ),
        "t",
        "temp_c",
    ),
    # match is the 2nd measure of an aggregate -> exercises the inner-loop advance
    (
        "multi-measure inner advance",
        (
            _agg(
                Measure(field="temp_c", fn="sum", output="total_temp"),
                Measure(field="aqi", fn="max", output="max_aqi"),
            ),
        ),
        "max_aqi",
        "aqi",
    ),
]


@pytest.mark.parametrize(
    ("aggregates", "name", "expected"),
    [(a[1], a[2], a[3]) for a in _LINEAGE_ARMS],
    ids=[a[0] for a in _LINEAGE_ARMS],
)
def test_unit_source_lineage_arm(
    aggregates: tuple[Aggregate, ...], name: str, expected: str | None
) -> None:
    assert checks.unit_source(name, aggregates) == expected


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
        "label.quantitative_units_present",
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
                {"type": "numeric", "name": "v", "scale": 2, "unit": "units"},
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
