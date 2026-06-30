# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M1.6a render-builder tests: the canonical JSON serializer + the positive-allowlist Vega-Lite
builder, fully unit-testable (no native dep).

The serializer pins each cell kind to its token (Decimal -> raw fixed-point number, -0 folded;
float rejected) and the raw-token/round-trip property; _scaled_cell re-quantizes a data cell to
its column scale (so the inlined number equals canon's hash token). The builder is driven from
good corpus specs (g01 bar/no-color over sales, g07 line+color over weather, g10 scatter over
weather) so every branch fires: mark map (behaviorally -- a lookup table is invisible to branch
coverage), every-channel sort:null, color present/absent, line-mark order:null vs a bare mark
string,
quantitative stack:null vs omitted, bar scale.zero vs omitted, the $schema/font constants, and
manifest-sourced+escaped axis titles. A direct _axis_title matrix over a synthetic manifest
pins every title branch (count-exempt, label present/absent, numeric+unit / numeric-no-unit /
non-numeric). An allowlist scan over all three specs proves only the generated safe key set is
emitted and no dangerous data/JS/URL key appears.
"""

import json
from decimal import Decimal
from pathlib import Path

import msgspec
import pytest

from verifier import canon, ingest, render
from verifier.eval import evaluate
from verifier.schema import Aggregate, Measure, VPlotSpec, decode_spec

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_GOOD = _ROOT / "examples" / "good_specs"
_SCHEMAS = _DATA / "schemas"

_G01 = "g01_total_revenue_by_month.json"  # bar, no color, ordinal x + quantitative y, sales
_G07 = "g07_temp_over_time_by_city.json"  # line + nominal color, temporal x, weather
_G10 = "g10_temp_vs_precip.json"  # scatter, two quantitative channels, weather


def _good(name: str) -> tuple[VPlotSpec, ingest.Manifest]:
    spec = decode_spec((_GOOD / name).read_bytes())
    stem = Path(spec.dataset.name).stem
    manifest = ingest.load_manifest((_SCHEMAS / f"{stem}.json").read_bytes())
    return spec, manifest


def _built(name: str) -> dict[str, object]:
    spec, manifest = _good(name)
    table = evaluate(spec, manifest, (_DATA / spec.dataset.name).read_bytes())
    return render.build_vega_lite(spec, table, manifest)


# --- serializer: each cell kind -> its token ---------------------------------
def test_cell_to_json_none() -> None:
    assert render._cell_to_json(None) == "null"


def test_cell_to_json_bool_true() -> None:
    assert render._cell_to_json(True) == "true"  # noqa: FBT003 -- bool is the value under test


def test_cell_to_json_bool_false() -> None:
    # The False arc of the bool ternary -- scale.zero is always True, so this needs a direct hit.
    assert render._cell_to_json(False) == "false"  # noqa: FBT003 -- bool is the value under test


def test_cell_to_json_str() -> None:
    assert render._cell_to_json("hi") == '"hi"'


@pytest.mark.parametrize(
    ("value", "token"),
    [
        (Decimal("10.50"), "10.50"),
        (Decimal(5), "5"),
        (Decimal("0.00"), "0.00"),
        (Decimal("-3.14"), "-3.14"),
        (Decimal("-0.00"), "0.00"),  # -0 folds to +0 (canon._format_decimal)
    ],
)
def test_cell_to_json_decimal_raw_fixed_point(value: Decimal, token: str) -> None:
    assert render._cell_to_json(value) == token


def test_cell_to_json_str_escapes_like_msgspec() -> None:
    s = 'a"b\\c\n\t'
    assert render._cell_to_json(s) == msgspec.json.encode(s).decode("utf-8")


def test_cell_to_json_rejects_float() -> None:
    with pytest.raises(TypeError):
        render._cell_to_json(1.5)


# --- _dumps: compact JSON, raw Decimal tokens, float rejected ----------------
def test_dumps_rejects_nested_float() -> None:
    with pytest.raises(TypeError):
        render._dumps({"a": [1.5]})


def test_dumps_nested_round_trip() -> None:
    obj = {"k": "v", "n": Decimal("1.50"), "z": None, "xs": ["a", Decimal("2.00")]}
    out = render._dumps(obj)
    assert out == '{"k":"v","n":1.50,"z":null,"xs":["a",2.00]}'
    # numbers are RAW tokens (re-parsing floats as Decimal recovers exact scale, not "1.50").
    assert json.loads(out, parse_float=Decimal) == obj


# --- _scaled_cell: data cells re-quantized to the column scale (matching canon's hash token) --
def test_scaled_cell_normalizes_to_column_scale() -> None:
    col2 = canon.NumericColumn(name="x", scale=2)
    # off-scale cells render at the COLUMN scale (== canon's hash token), not the cell's own.
    assert render._cell_to_json(render._scaled_cell(col2, Decimal(1))) == "1.00"
    assert render._cell_to_json(render._scaled_cell(col2, Decimal("1.234"))) == "1.23"
    assert render._scaled_cell(col2, None) is None  # numeric null passes through
    assert render._scaled_cell(canon.StringColumn(name="s"), "hi") == "hi"  # non-numeric verbatim


def test_scaled_cell_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        render._scaled_cell(canon.NumericColumn(name="x", scale=2), Decimal("NaN"))


# --- the authoritative string + build/stdlib boundary ------------------------
def test_vega_lite_json_inlines_decimal_as_raw_token() -> None:
    spec, manifest = _good(_G10)  # temp_c/precip_mm scale 1 -> tokens carry a decimal point
    table = evaluate(spec, manifest, (_DATA / spec.dataset.name).read_bytes())
    out = render.vega_lite_json(spec, table, manifest)
    temps = [r["temp_c"] for r in json.loads(out, parse_float=Decimal)["data"]["values"]]
    temps = [t for t in temps if t is not None]
    assert temps
    assert all(isinstance(t, Decimal) for t in temps)  # raw number, never a "23.5" string


def test_build_keeps_raw_decimals_unserializable_by_stdlib() -> None:
    built = _built(_G10)
    values = built["data"]["values"]  # type: ignore[index]
    assert any(isinstance(c, Decimal) for row in values for c in row.values())
    with pytest.raises(TypeError):
        json.dumps(built)  # the Decimals make stdlib json refuse -> _dumps is the sole serializer


# --- mark map (behavioral: a lookup table is invisible to branch coverage) ----
@pytest.mark.parametrize(("name", "mark"), [(_G01, "bar"), (_G10, "point")])
def test_mark_map(name: str, mark: str) -> None:
    # bar/scatter emit a bare mark string; line emits a mark OBJECT (test_line_mark_order_null).
    assert _built(name)["mark"] == mark


# --- the emitted safe keys ----------------------------------------------------
def test_every_channel_sorts_null() -> None:
    enc = _built(_G07)["encoding"]
    assert enc["x"]["sort"] is None  # type: ignore[index]
    assert enc["y"]["sort"] is None  # type: ignore[index]
    assert enc["color"]["sort"] is None  # type: ignore[index]


def test_color_present() -> None:
    enc = _built(_G07)["encoding"]
    assert enc["color"]["field"] == "city"  # type: ignore[index]


def test_color_absent() -> None:
    assert "color" not in _built(_G01)["encoding"]  # type: ignore[operator]


def test_line_mark_order_null() -> None:
    # order:null is a MARK property -- a line spec with encoding.order:null FAILS the real v5
    # schema (the order channel admits no null). Full schema validity is M1.6b's vl-convert compile.
    built = _built(_G07)
    assert built["mark"] == {"type": "line", "order": None}
    assert "order" not in built["encoding"]  # type: ignore[operator]  # moved to the mark


def test_non_line_omits_order() -> None:
    for name in (_G01, _G10):
        built = _built(name)
        assert isinstance(built["mark"], str)  # non-line: a bare mark string, no order anywhere
        assert "order" not in built["encoding"]  # type: ignore[operator]


def test_quantitative_channel_stack_null() -> None:
    assert _built(_G01)["encoding"]["y"]["stack"] is None  # type: ignore[index]


def test_non_quantitative_channel_omits_stack() -> None:
    assert "stack" not in _built(_G01)["encoding"]["x"]  # type: ignore[index]


def test_bar_quantitative_axis_scale_zero() -> None:
    assert _built(_G01)["encoding"]["y"]["scale"] == {"zero": True}  # type: ignore[index]


def test_non_bar_omits_scale() -> None:
    enc = _built(_G10)["encoding"]  # scatter, quantitative x/y -> stack:null but no scale.zero
    assert "scale" not in enc["x"]  # type: ignore[index]
    assert "scale" not in enc["y"]  # type: ignore[index]
    assert enc["x"]["stack"] is None  # type: ignore[index]


def test_schema_and_font_constants() -> None:
    built = _built(_G01)
    assert built["$schema"] == "https://vega.github.io/schema/vega-lite/v5.json"
    assert built["$schema"] == render._VEGA_LITE_SCHEMA
    assert built["config"]["font"] == render._FONT_FAMILY  # type: ignore[index]


# --- axis titles: manifest-sourced -------------------------------------------
def test_axis_titles_g01() -> None:
    enc = _built(_G01)["encoding"]
    assert enc["x"]["title"] == "Month"  # type: ignore[index]
    assert enc["y"]["title"] == "Revenue (USD)"  # type: ignore[index]  # sum(revenue)->revenue


def test_axis_titles_g07() -> None:
    enc = _built(_G07)["encoding"]
    assert enc["x"]["title"] == "Date"  # type: ignore[index]
    assert enc["y"]["title"] == "Temperature (°C)"  # type: ignore[index]
    assert enc["color"]["title"] == "City"  # type: ignore[index]


_TITLE_MANIFEST = ingest.Manifest(
    dataset="t.csv",
    columns=(
        ingest.NumericColumnSpec(name="rev", scale=2, unit="USD", label="Revenue"),
        ingest.NumericColumnSpec(name="aqi", scale=0, label="Air quality"),  # label, no unit
        ingest.NumericColumnSpec(name="bare", scale=0, unit="x"),  # unit, NO label -> name base
        ingest.StringColumnSpec(name="city", label="City"),  # non-numeric -> no unit suffix
    ),
)
_COUNT_AGG = (Aggregate(measures=(Measure(field="city", fn="count", output="c"),)),)


@pytest.mark.parametrize(
    ("field", "aggregates", "title"),
    [
        ("rev", (), "Revenue (USD)"),  # numeric + label + unit
        ("aqi", (), "Air quality"),  # numeric + label, unit None -> no suffix
        ("bare", (), "bare (x)"),  # label None -> name fallback; numeric + unit
        ("city", (), "City"),  # non-numeric -> isinstance False -> no suffix
        ("c", _COUNT_AGG, "count"),  # count-derived -> source None -> the fixed title
    ],
)
def test_axis_title_branches(field: str, aggregates: tuple[Aggregate, ...], title: str) -> None:
    assert render._axis_title(field, aggregates, _TITLE_MANIFEST) == title


def test_special_char_label_escaped_end_to_end() -> None:
    # A manifest label with a quote is JSON-escaped in the authoritative string, so no raw quote
    # breaks the JSON (M1.6a's escaping boundary; XML/HTML escaping for SVG is M1.6b/c).
    spec, _ = _good(_G01)
    manifest = ingest.Manifest(
        dataset="sales.csv",
        columns=(
            ingest.StringColumnSpec(name="month", label='M"x'),
            ingest.StringColumnSpec(name="region", label="Region"),
            ingest.NumericColumnSpec(name="revenue", scale=0, unit="USD", label="Revenue"),
            ingest.NumericColumnSpec(name="orders", scale=0, unit="orders", label="Orders"),
        ),
    )
    table = evaluate(spec, manifest, (_DATA / "sales.csv").read_bytes())
    out = render.vega_lite_json(spec, table, manifest)
    assert r"M\"x" in out  # the quote is backslash-escaped
    assert json.loads(out, parse_float=Decimal)  # the whole string is still valid JSON


# --- positive allowlist: only the generated safe key set is emitted -----------
_ALLOWED_KEYS = frozenset(
    {
        "$schema",
        "data",
        "values",
        "mark",
        "encoding",
        "config",
        "font",
        "x",
        "y",
        "color",
        "order",
        "field",
        "type",
        "sort",
        "title",
        "stack",
        "scale",
        "zero",
    }
)
# Keys that would re-open a data/JS/URL sink if the builder ever copied a model-supplied one.
_DANGEROUS_KEYS = frozenset(
    {
        "url",
        "datasets",
        "transform",
        "params",
        "expr",
        "href",
        "tooltip",
        "loader",
        "signals",
        "aggregate",
        "bin",
        "impute",
        "domain",
    }
)


def _structural_keys(obj: object) -> set[str]:
    # Recurse structural dicts only; data.values rows (a list) are opaque DATA whose keys are
    # arbitrary column names, not Vega structure -> not recursed (a list returns the empty set).
    keys: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            keys.add(key)
            keys |= _structural_keys(value)
    return keys


@pytest.mark.parametrize("name", [_G01, _G07, _G10])
def test_allowlist_keys_only(name: str) -> None:
    keys = _structural_keys(_built(name))
    assert keys <= _ALLOWED_KEYS  # no key outside the generated safe set
    assert keys.isdisjoint(_DANGEROUS_KEYS)  # no data/JS/URL sink
