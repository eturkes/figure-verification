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

M1.6b adds the vl-convert SVG layer and the totality hardening. _scaled_cell now routes EVERY
(column, cell) pair through canon._cell_token, so the parity tests assert render's inlined token
equals the hash token on every valid pair and raises the SAME type on every canon-rejected pair;
build_vega_lite rejects duplicate column names. render_svg is exercised against the real native
dep: all ten good specs compile (schema validity vl-convert alone can prove), the SVG is self-
contained (no <script>, no http(s) in any href/src/url value) and byte-identical across calls,
text routes through the vendored DejaVu Sans, and an external-data-url spec is hard-blocked. The
compile-confirm inspects the COMPILED Vega: our sort:null/order:null leave no sort key anywhere,
while a naive variant (nulling stripped) reintroduces the line-vertex and legend sorts.
"""

import json
import re
from decimal import Decimal
from pathlib import Path

import msgspec
import pytest
import vl_convert

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
_ALL_GOOD = [p.name for p in sorted(_GOOD.glob("*.json"))]  # the full verified-good corpus

# Self-containment scan targets: the VALUES of fetch-bearing attributes + CSS url(). xmlns
# namespace declarations and escaped data text also contain http(s) but are NOT fetches, so the
# scan reads these values only, never the raw SVG string (memory M1.6 self-containment note).
_HREF_RE = re.compile(r'(?:href|src|xlink:href)\s*=\s*"([^"]*)"')
_URL_RE = re.compile(r"url\(([^)]*)\)")


def _good(name: str) -> tuple[VPlotSpec, ingest.Manifest]:
    spec = decode_spec((_GOOD / name).read_bytes())
    stem = Path(spec.dataset.name).stem
    manifest = ingest.load_manifest((_SCHEMAS / f"{stem}.json").read_bytes())
    return spec, manifest


def _evaluated(name: str) -> tuple[VPlotSpec, ingest.Manifest, canon.Table]:
    spec, manifest = _good(name)
    table = evaluate(spec, manifest, (_DATA / spec.dataset.name).read_bytes())
    return spec, manifest, table


def _built(name: str) -> dict[str, object]:
    spec, manifest, table = _evaluated(name)
    return render.build_vega_lite(spec, table, manifest)


def _svg(name: str) -> str:
    spec, manifest, table = _evaluated(name)
    return render.render_svg(render.vega_lite_json(spec, table, manifest))


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


# --- totality hardening: render's token == canon's hash token, reject-parity on mismatches -----
# A type-mismatched cell (a Decimal in a string column) once slipped through _scaled_cell and was
# serialized as a number where canon._cell_token RAISES (codex-review r2). The builder must be
# total over a canon.Table iff the hash is: same token on every valid pair, same raise on every
# rejected pair.
_VALID_PAIRS: list[tuple[canon.Column, canon.Cell]] = [
    (canon.NumericColumn(name="n", scale=2), Decimal("10.50")),
    (canon.NumericColumn(name="n", scale=0), Decimal(5)),
    (canon.NumericColumn(name="n", scale=2), Decimal(1)),  # re-quantize up to 1.00
    (canon.NumericColumn(name="n", scale=2), Decimal("1.234")),  # re-quantize down to 1.23
    (canon.NumericColumn(name="n", scale=2), Decimal("-0.00")),  # -0 folds to +0
    (canon.NumericColumn(name="n", scale=2), None),
    (canon.StringColumn(name="s"), "hi"),
    (canon.StringColumn(name="s"), None),
    (canon.TemporalColumn(name="t", granularity="date"), "2024-01-01"),
    (canon.TemporalColumn(name="t", granularity="datetime"), None),
]


@pytest.mark.parametrize(("column", "cell"), _VALID_PAIRS)
def test_scaled_cell_token_matches_canon(column: canon.Column, cell: canon.Cell) -> None:
    # The inlined JSON token EQUALS canon's hash token for every valid (column, cell) pair, so the
    # chart number matches the certificate's plotted-table hash by construction.
    rendered = render._cell_to_json(render._scaled_cell(column, cell))
    assert rendered == canon._cell_token(column, cell)


_REJECTED_PAIRS: list[tuple[canon.Column, canon.Cell]] = [
    (canon.NumericColumn(name="n", scale=2), "x"),  # str in a numeric column -> TypeError
    (canon.NumericColumn(name="n", scale=2), Decimal("NaN")),  # non-finite -> ValueError
    (canon.NumericColumn(name="n", scale=2), Decimal("Infinity")),
    (canon.StringColumn(name="s"), Decimal(1)),  # Decimal in a string column -> TypeError
    (canon.TemporalColumn(name="t", granularity="date"), Decimal(1)),  # Decimal in a temporal col
]


@pytest.mark.parametrize(("column", "cell"), _REJECTED_PAIRS)
def test_scaled_cell_rejects_exactly_what_canon_rejects(
    column: canon.Column, cell: canon.Cell
) -> None:
    # reject-parity: _scaled_cell raises the SAME exception type canon._cell_token raises.
    with pytest.raises((TypeError, ValueError)) as canon_exc:
        canon._cell_token(column, cell)
    with pytest.raises(type(canon_exc.value)):
        render._scaled_cell(column, cell)


def test_build_rejects_duplicate_column_names() -> None:
    # Duplicate names collapse in each row dict -> a column's data vanishes silently; reject first.
    spec, manifest = _good(_G01)
    table = canon.Table(
        columns=(canon.NumericColumn(name="x", scale=0), canon.NumericColumn(name="x", scale=0)),
        rows=((Decimal(1), Decimal(2)),),
    )
    with pytest.raises(ValueError, match="duplicate column"):
        render.build_vega_lite(spec, table, manifest)


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


# --- render_svg: the vl-convert native dep (M1.6b) ----------------------------
def test_vl_version_pin_is_available() -> None:
    # The pin is the determinism lever: it must be a version vl-convert can actually select.
    assert render._VL_VERSION in vl_convert.get_vegalite_versions()


@pytest.mark.parametrize("name", _ALL_GOOD)
def test_render_svg_compiles_and_is_self_contained(name: str) -> None:
    # Every good spec must COMPILE (only vl-convert proves v5-schema validity -- the gap that let
    # a line encoding.order:null ship past M1.6a's structural gate) and yield a self-contained SVG.
    svg = _svg(name)
    assert "<script" not in svg.lower()  # no JavaScript sink
    for value in _HREF_RE.findall(svg) + _URL_RE.findall(svg):
        assert "http://" not in value and "https://" not in value  # no external fetch


def test_render_svg_is_byte_deterministic() -> None:
    # Byte-identical across calls within this pinned vl-convert build (same-process/same-build).
    spec, manifest, table = _evaluated(_G07)
    vl_json = render.vega_lite_json(spec, table, manifest)
    assert render.render_svg(vl_json) == render.render_svg(vl_json)


def test_render_svg_routes_text_through_vendored_font() -> None:
    svg = _svg(_G07)  # has axis titles + a legend -> text elements present
    assert f'font-family="{render._FONT_FAMILY}"' in svg  # the vendored DejaVu Sans, not a fallback


def test_render_svg_blocks_external_data_url() -> None:
    # allowed_base_urls=[] hard-blocks any external fetch -- defense-in-depth behind the builder's
    # positive allowlist (which never emits a data.url in the first place).
    external = json.dumps(
        {
            "$schema": render._VEGA_LITE_SCHEMA,
            "data": {"url": "https://example.com/x.csv"},
            "mark": "point",
        }
    )
    with pytest.raises(ValueError, match="External data url not allowed"):
        render.render_svg(external)


# --- compile-confirm: the structural nulling actually defeats Vega's implicit ordering ---------
def _find_sorts(obj: object) -> list[object]:
    """Every value under a key literally named 'sort', anywhere in a compiled-Vega tree."""
    found: list[object] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "sort":
                found.append(value)
            found.extend(_find_sorts(value))
    elif isinstance(obj, list):
        for value in obj:
            found.extend(_find_sorts(value))
    return found


@pytest.mark.parametrize("name", _ALL_GOOD)
def test_compiled_vega_carries_no_implicit_ordering(name: str) -> None:
    # b-side proof of a's sort:null / line order:null: the COMPILED Vega has no sort key anywhere,
    # so no implicit line-vertex sort and no legend-domain sort survive -- the recomputed row order
    # and data-order legend are authoritative.
    spec, manifest, table = _evaluated(name)
    vega = vl_convert.vegalite_to_vega(
        render.vega_lite_json(spec, table, manifest), vl_version=render._VL_VERSION
    )
    assert _find_sorts(vega) == []


def test_naive_spec_reintroduces_implicit_ordering() -> None:
    # The differential proving the assertion above is NOT vacuous: strip our sort:null + line-mark
    # order:null and Vega-Lite's implicit line-vertex sort and legend-domain sort reappear.
    spec, manifest, table = _evaluated(_G07)
    built = render.build_vega_lite(spec, table, manifest)
    built["mark"] = "line"  # drop the mark-level order:null
    for channel in built["encoding"].values():
        channel.pop("sort", None)  # drop every sort:null
    vega = vl_convert.vegalite_to_vega(render._dumps(built), vl_version=render._VL_VERSION)
    assert _find_sorts(vega)  # the implicit sorts are back
