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
equals the hash token on every valid pair, raises the SAME type on every canon-rejected pair, and
rejects a width-mismatched row exactly as the hash does; build_vega_lite additionally rejects
duplicate column names (a render-specific hazard hash_table tolerates). render_svg is exercised
against the real native dep: all ten good specs compile (schema validity vl-convert alone can
prove) and are self-contained -- no <script>, and _external_refs flags no external/relative
href/src/CSS-url reference (proven non-vacuous against a known leak) -- and byte-identical across
calls; render_svg NAMES the vendored DejaVu Sans family, whose exact bytes are pinned by sha256;
an external-data-url spec is hard-blocked. The compile-confirm inspects the COMPILED Vega: our
sort:null/order:null leave no sort key anywhere, while a naive variant (nulling stripped)
reintroduces the line-vertex sort; removing the explicit discrete domain too reintroduces the
legend-domain sort.

M5.1c makes orchestration evidence-driven: preparation binds spec/evidence, gates render rows,
and serializes one authoritative Vega artifact; prepared rendering gates VCert/SVG/HTML UTF-8
bytes. Mutation/deletion, single-read/single-serialization, exact-boundary, and native-tripwire
witnesses pin each expensive seam while the ordinary artifact bytes remain unchanged.

M5.2d makes preparation final-verification work: one exact builder object supplies serialized Vega
bytes + typed SMT facts, and only a passing merged report yields a native-renderable artifact.
Direct/service/proposer mutation witnesses corrupt row order/domain/zero and prove fail-closed
blocking before native Vega.

M5.2e upgrades VCert to method-bearing v0.2, binds the exact Vega bytes + verifier/Z3 versions,
and propagates the fifth hash through badge/service/OpenAPI surfaces.
"""

import hashlib
import importlib.metadata
import json
import re
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import msgspec
import pytest
import vl_convert

from verifier import canon, checks, formal, ingest, render
from verifier.errors import VerificationError
from verifier.eval import evaluate
from verifier.limits import DEFAULT_LIMITS, VerificationLimits, read_bounded
from verifier.schema import (
    Aggregate,
    Channel,
    Dataset,
    Encoding,
    Filter,
    Measure,
    Select,
    Sort,
    SortKey,
    Transform,
    VPlotSpec,
    decode_spec,
)

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_GOOD = _ROOT / "examples" / "good_specs"
_SCHEMAS = _DATA / "schemas"

_G01 = "g01_total_revenue_by_month.json"  # bar, no color, ordinal x + quantitative y, sales
_G07 = "g07_temp_over_time_by_city.json"  # line + nominal color, temporal x, weather
_G10 = "g10_temp_vs_precip.json"  # scatter, two quantitative channels, weather
_ALL_GOOD = [p.name for p in sorted(_GOOD.glob("*.json"))]  # the full verified-good corpus

# Self-containment audit: collect every fetchable reference -- href/src attribute VALUES (any
# namespace prefix, single- OR double-quoted, case-insensitive), CSS url(...) targets, @import
# targets -- and keep those that are neither a same-document #fragment nor an inline data: URI.
# xmlns declarations and escaped data text are NOT references (value-scoped, never the raw SVG
# string), so a URL-valued label cell does not false-positive. Builder output carries none of these
# -> the audit is the regression guard, proven non-vacuous (uppercase scheme / protocol-relative /
# single-quoted attr / CSS url) by test_external_ref_audit_flags_a_leak.
_REF_ATTR_RE = re.compile(r"""(?i)\b(?:xlink:href|href|src)\s*=\s*(["'])(.*?)\1""")
_CSS_URL_RE = re.compile(r"(?i)\burl\(\s*['\"]?([^'\")]*)")
_CSS_IMPORT_RE = re.compile(r"(?i)@import\s+(?:url\(\s*)?['\"]([^'\"]*)")


def _external_refs(svg: str) -> list[str]:
    attr_values = [value for _quote, value in _REF_ATTR_RE.findall(svg)]
    refs = attr_values + _CSS_URL_RE.findall(svg) + _CSS_IMPORT_RE.findall(svg)
    external: list[str] = []
    for ref in refs:
        value = ref.strip()
        if value and not value.startswith("#") and not value.lower().startswith("data:"):
            external.append(value)
    return external


def _good(name: str) -> tuple[VPlotSpec, ingest.Manifest]:
    spec = decode_spec((_GOOD / name).read_bytes())
    stem = Path(spec.dataset.name).stem
    manifest = ingest.load_manifest((_SCHEMAS / f"{stem}.json").read_bytes())
    return spec, manifest


def _manifest_bytes(name: str) -> bytes:
    """The raw manifest bytes for a good spec's dataset (for the manifest hash)."""
    spec = decode_spec((_GOOD / name).read_bytes())
    stem = Path(spec.dataset.name).stem
    return (_SCHEMAS / f"{stem}.json").read_bytes()


def _evaluated(name: str) -> tuple[VPlotSpec, ingest.Manifest, canon.Table]:
    spec, manifest = _good(name)
    table = evaluate(spec, manifest, (_DATA / spec.dataset.name).read_bytes())
    return spec, manifest, table


def _evidence(name: str, *, data_dir: Path = _DATA) -> tuple[VPlotSpec, checks.RecomputedEvidence]:
    """One good spec plus the check-passed evidence captured from ``data_dir``."""
    spec, _ = _good(name)
    run = checks.verify_run(spec, _manifest_bytes(name), data_dir=data_dir)
    assert run.evidence is not None
    return spec, run.evidence


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
# serialized as a number where canon._cell_token RAISES (codex-review r2). The builder must match
# the hash CELL-FOR-CELL: same token on every valid pair, same raise on every rejected pair. It is
# additionally STRICTER -- it also rejects duplicate column names (tested below).
_VALID_PAIRS: list[tuple[canon.Column, canon.Cell]] = [
    (canon.NumericColumn(name="n", scale=2), Decimal("10.50")),
    (canon.NumericColumn(name="n", scale=0), Decimal(5)),
    # Past f64-exact range (2**53 + 1): the inlined JSON token stays EXACT (= the hash token);
    # only the TCB's JS-double parse may display it rounded (disclosed -- POC_SCOPE TCB line).
    (canon.NumericColumn(name="n", scale=0), Decimal(2**53 + 1)),
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


@pytest.mark.parametrize(
    "rows",
    [
        pytest.param(((Decimal(1),),), id="short-row"),
        pytest.param(((Decimal(1), Decimal(2), Decimal(3)),), id="long-row"),
    ],
)
def test_build_rejects_row_width_mismatch_like_canon(
    rows: tuple[tuple[canon.Cell, ...], ...],
) -> None:
    # Table-level reject-parity (the cell-level pairs are above): a width-mismatched row raises the
    # SAME ValueError in build_vega_lite (its zip(strict=True)) and canon.hash_table (serialize).
    spec, manifest = _good(_G01)
    table = canon.Table(
        columns=(canon.NumericColumn(name="a", scale=0), canon.NumericColumn(name="b", scale=0)),
        rows=rows,
    )
    with pytest.raises(ValueError) as canon_exc:
        canon.hash_table(table)
    with pytest.raises(type(canon_exc.value)):
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
    assert enc["color"]["scale"]["domain"] == ["Cairo", "London"]  # type: ignore[index]


def test_color_absent() -> None:
    assert "color" not in _built(_G01)["encoding"]  # type: ignore[operator]


@pytest.mark.parametrize(
    ("rows", "domain"),
    [
        ((), []),
        (((None,), (None,)), []),
        (
            ((Decimal("1.0"),), (Decimal("2.0"),), (Decimal("2.0"),)),
            [Decimal("1.0"), Decimal("2.0")],
        ),
    ],
    ids=["empty", "all-null", "numeric-ordinal"],
)
def test_explicit_discrete_domain_edge_cases_compile(
    rows: tuple[tuple[canon.Cell, ...], ...], domain: list[canon.Cell]
) -> None:
    spec = VPlotSpec(
        version="vplot-0.1",
        dataset=Dataset(name="t.csv", hash="sha256:" + "0" * 64),
        transform=(),
        mark="scatter",
        encoding=Encoding(
            x=Channel(field="n", kind="quantitative"),
            y=Channel(field="n", kind="quantitative"),
            color=Channel(field="n", kind="ordinal"),
        ),
    )
    manifest = ingest.Manifest(
        dataset="t.csv",
        columns=(ingest.NumericColumnSpec(name="n", scale=1, unit="u"),),
    )
    table = canon.Table(columns=(canon.NumericColumn(name="n", scale=1),), rows=rows)
    built = render.build_vega_lite(spec, table, manifest)
    assert built["encoding"]["color"]["scale"]["domain"] == domain
    facts = render._formal_facts(spec, table, built)
    assert facts.legend_domain is not None
    assert all(result.status == "pass" for result in formal.verify_formal(facts).results)
    compiled = vl_convert.vegalite_to_vega(render._dumps(built), vl_version=render._VL_VERSION)
    assert isinstance(compiled, dict)


def test_non_discrete_color_has_no_domain_obligation() -> None:
    spec = VPlotSpec(
        version="vplot-0.1",
        dataset=Dataset(name="t.csv", hash="sha256:" + "0" * 64),
        transform=(),
        mark="scatter",
        encoding=Encoding(
            x=Channel(field="n", kind="quantitative"),
            y=Channel(field="n", kind="quantitative"),
            color=Channel(field="n", kind="quantitative"),
        ),
    )
    manifest = ingest.Manifest(
        dataset="t.csv",
        columns=(ingest.NumericColumnSpec(name="n", scale=1, unit="u"),),
    )
    table = canon.Table(
        columns=(canon.NumericColumn(name="n", scale=1),),
        rows=((Decimal("1.0"),),),
    )
    built = render.build_vega_lite(spec, table, manifest)
    assert "scale" not in built["encoding"]["color"]
    assert render._formal_facts(spec, table, built).legend_domain is None


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
        "domain",
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
    assert _external_refs(svg) == []  # no external/relative fetch -- only xmlns + inline content


def test_external_ref_audit_flags_a_leak() -> None:
    # The audit is non-vacuous: an external reference IS flagged, across the cases a raw http(s)
    # substring scan missed -- an uppercase scheme, a protocol-relative //host, a single-quoted
    # attribute, a CSS url(), and a CSS @import. render_svg's allowed_base_urls=[] blocks a
    # compile-time DATA fetch but does NOT strip an image mark's href, so this proves the AUDIT
    # detects a leak; self-containment rests on the builder precondition, never on render_svg
    # sanitizing arbitrary input (M1.6c gate's job).
    leak = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<image xlink:href="HTTPS://example.com/a.png"/>'
        "<use href='https://single.example/q.png'/>"  # single-quoted attr value
        '<rect style="fill:URL(//cdn.example/x.png)"/>'
        "<style>@import 'http://evil.example/s.css';</style></svg>"
    )
    assert sorted(_external_refs(leak)) == [
        "//cdn.example/x.png",
        "HTTPS://example.com/a.png",
        "http://evil.example/s.css",
        "https://single.example/q.png",
    ]
    selfcontained = "<use xlink:href='#clip0'/><image href=\"data:image/png;base64,AAAA\"/>"
    assert _external_refs(selfcontained) == []  # #fragment + inline data: (either quote style)


def test_render_svg_is_byte_deterministic() -> None:
    # Byte-identical across calls within this pinned vl-convert build (same-process/same-build).
    spec, manifest, table = _evaluated(_G07)
    vl_json = render.vega_lite_json(spec, table, manifest)
    assert render.render_svg(vl_json) == render.render_svg(vl_json)


def test_render_svg_names_vendored_font_family() -> None:
    svg = _svg(_G07)  # axis titles + a legend -> text elements present
    # render_svg lays text out as the vendored family NAME; this pins the name in the output. The
    # vendored file's exact bytes are pinned separately (the asset-sha256 test) -- the family-name
    # assertion alone can be met by a same-named system DejaVu Sans.
    assert f'font-family="{render._FONT_FAMILY}"' in svg


_FONT_SHA256 = "57f73e11f51999432bf7ab22ce55b6f945d5eca1bf824404cfa9ec2e3718c84e"


def test_vendored_font_asset_present_and_pinned() -> None:
    # The bytes render._FONT_DIR registers are present + uncorrupted in the package: a packaging /
    # font-swap guard. Vendoring makes OUR DejaVu 2.37 bytes AVAILABLE so the named family resolves
    # to them absent a same-named system font; byte SELECTION over such a font stays unproven (see
    # the family-name test). Read at runtime via importlib.resources -- the same path render.py
    # loads -- so this covers the packaged bytes rather than a source-tree-only path.
    ttf = render._FONT_DIR / "DejaVuSans.ttf"
    assert ttf.is_file()
    assert hashlib.sha256(ttf.read_bytes()).hexdigest() == _FONT_SHA256


def test_render_svg_blocks_external_data_url() -> None:
    # allowed_base_urls=[] hard-blocks an external DATA url at compile time -- defense-in-depth
    # behind the builder's positive allowlist (which never emits a data.url in the first place). It
    # does NOT strip an image-mark href -- output-reference auditing rests on the builder
    # precondition + the M1.6c gate (the leak test exercises an unstripped href).
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
def _find_sorts(obj: object, path: str = "$") -> list[str]:
    """The PATH to every key literally named 'sort' anywhere in a compiled-Vega tree (a path, not
    the value, so the no-ordering assertion names WHERE a stray sort survived and the naive
    differential can pin the line-vertex and legend-domain halves independently)."""
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "sort":
                found.append(f"{path}.sort")
            found.extend(_find_sorts(value, f"{path}.{key}"))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            found.extend(_find_sorts(value, f"{path}[{index}]"))
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
    assert isinstance(vega, dict)  # a non-dict compile result would make _find_sorts vacuously []
    assert _find_sorts(vega) == []


def test_naive_spec_reintroduces_implicit_ordering() -> None:
    # The differential proving the assertion above is NOT vacuous: strip our explicit discrete
    # domain, sort:null, and line-mark order:null; Vega-Lite's implicit legend/vertex sorts return.
    spec, manifest, table = _evaluated(_G07)
    built = render.build_vega_lite(spec, table, manifest)
    built["mark"] = "line"  # drop the mark-level order:null
    for channel in built["encoding"].values():
        channel.pop("sort", None)  # drop every sort:null
    built["encoding"]["color"].pop("scale")
    vega = vl_convert.vegalite_to_vega(render._dumps(built), vl_version=render._VL_VERSION)
    paths = _find_sorts(vega)
    assert any(re.search(r"\.marks\b", p) for p in paths), paths  # line-vertex sort
    assert any(p.endswith(".domain.sort") for p in paths), paths  # legend-domain sort


# --- M1.6c: provenance certificate + render() gate ---------------------------
def _certificate_evidence(
    spec: VPlotSpec,
    table: canon.Table,
    results: tuple[checks.CheckResult, ...] = (),
) -> checks.RecomputedEvidence:
    """Coherent synthetic evidence for certificate-only predicate/disclosure tests."""
    manifest_bytes = b"{}"
    return checks.RecomputedEvidence(
        manifest=ingest.Manifest(dataset=spec.dataset.name, columns=()),
        manifest_bytes=manifest_bytes,
        source_bytes=b"",
        dataset_hash=spec.dataset.hash,
        manifest_hash=canon.hash_manifest(manifest_bytes),
        spec_hash=canon.hash_spec(spec),
        plotted_table=table,
        plotted_table_hash=canon.hash_table(table),
        results=results,
    )


def _render(name: str) -> render.RenderResult:
    """render() on a good spec, asserted non-None (mypy narrowing + gate)."""
    spec, _ = _good(name)
    result = render.render(spec, _manifest_bytes(name), data_dir=_DATA)
    assert result is not None
    return result


def _prepare(
    spec: VPlotSpec,
    evidence: checks.RecomputedEvidence,
    *,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> render.PreparedArtifact:
    """Formally passing preparation, narrowed to its native-renderable artifact."""
    preparation = render.prepare_render(spec, evidence, limits=limits)
    assert preparation.report.passed
    assert preparation.prepared is not None
    return preparation.prepared


def _certificate(
    spec: VPlotSpec,
    evidence: checks.RecomputedEvidence,
    *,
    vega_lite: bytes = b"{}",
) -> render.VCert:
    """Certificate-only helper over an explicit synthetic prepared artifact."""
    return render._build_certificate(
        render.PreparedArtifact(
            spec=spec,
            evidence=evidence,
            results=evidence.results,
            vega_lite=vega_lite,
        )
    )


def test_render_good_spec_returns_svg_and_cert() -> None:
    result = _render(_G01)
    assert "<svg" in result.svg
    assert isinstance(result.certificate, render.VCert)


def test_render_failing_spec_returns_none() -> None:
    # A hash-mismatch makes the binding gate fail -> verify not passed -> no chart.
    spec, _ = _good(_G01)
    broken = msgspec.structs.replace(
        spec, dataset=msgspec.structs.replace(spec.dataset, hash="sha256:" + "0" * 64)
    )
    assert render.render(broken, _manifest_bytes(_G01), data_dir=_DATA) is None


def test_render_gate_skips_svg_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    # Tripwire: render_svg must NOT run for a failing spec (the gate short-circuits before it).
    def _boom(_: str) -> str:
        msg = "render_svg reached for a failing spec"
        raise AssertionError(msg)

    monkeypatch.setattr(render, "render_svg", _boom)
    spec, _ = _good(_G01)
    broken = msgspec.structs.replace(
        spec, dataset=msgspec.structs.replace(spec.dataset, hash="sha256:" + "0" * 64)
    )
    assert render.render(broken, _manifest_bytes(_G01), data_dir=_DATA) is None


def test_direct_render_formal_gate_blocks_built_row_corruption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The solver reads the exact built rows; an inversion never reaches native Vega."""
    original_build = render.build_vega_lite
    original_formal = formal.verify_formal
    build_count = 0
    formal_runs: list[formal.FormalRun] = []

    def corrupt_rows(
        spec: VPlotSpec, table: canon.Table, manifest: ingest.Manifest
    ) -> dict[str, Any]:
        nonlocal build_count
        build_count += 1
        built = original_build(spec, table, manifest)
        values = built["data"]["values"]
        values[0], values[1] = values[1], values[0]
        return built

    def record_formal(
        facts: formal.FormalFacts,
        *,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> formal.FormalRun:
        run = original_formal(facts, limits=limits)
        formal_runs.append(run)
        return run

    def forbidden_native(_: str) -> str:
        msg = "native render reached after a formal row-order failure"
        raise AssertionError(msg)

    monkeypatch.setattr(render, "build_vega_lite", corrupt_rows)
    monkeypatch.setattr(formal, "verify_formal", record_formal)
    monkeypatch.setattr(render, "render_svg", forbidden_native)
    spec, _manifest = _good(_G01)
    result = render.render(spec, _manifest_bytes(_G01), data_dir=_DATA)
    assert result is None
    assert build_count == len(formal_runs) == 1
    failed = [item.check for item in formal_runs[0].results if item.status == "fail"]
    assert failed == ["sort.canonical_order"]


# --- M5.1c: evidence-driven preparation + artifact byte ceilings ------------
def test_render_reads_source_and_builds_vega_once(monkeypatch: pytest.MonkeyPatch) -> None:
    read_paths: list[Path] = []

    def _read_spy(path: Path, max_bytes: int) -> bytes:
        read_paths.append(path)
        return read_bounded(path, max_bytes)

    original_build = render.build_vega_lite
    built: list[dict[str, object]] = []

    def _build_spy(
        spec: VPlotSpec, table: canon.Table, manifest: ingest.Manifest
    ) -> dict[str, object]:
        value = original_build(spec, table, manifest)
        built.append(value)
        return value

    monkeypatch.setattr("verifier.checks.read_bounded", _read_spy)
    monkeypatch.setattr(render, "build_vega_lite", _build_spy)
    spec, _ = _good(_G01)
    result = render.render(spec, _manifest_bytes(_G01), data_dir=_DATA)
    assert result is not None
    assert read_paths == [(_DATA / spec.dataset.name).resolve()]
    assert len(built) == 1
    assert result.vega_lite == render._dumps(built[0]).encode("utf-8")


@pytest.mark.parametrize("action", ["mutate", "delete"])
def test_render_from_evidence_ignores_later_live_source_change(tmp_path: Path, action: str) -> None:
    source = tmp_path / "sales.csv"
    source.write_bytes((_DATA / "sales.csv").read_bytes())
    spec, evidence = _evidence(_G01, data_dir=tmp_path)
    expected = render.render_prepared(_prepare(spec, evidence))

    if action == "mutate":
        source.write_bytes(b"month,region,revenue,orders\n2099-01,NA,1,1\n")
    else:
        source.unlink()

    actual = render.render_prepared(_prepare(spec, evidence))
    assert actual == expected
    assert actual.certificate.dataset_hash == evidence.dataset_hash
    assert actual.certificate.plotted_table_hash == evidence.plotted_table_hash


def test_prepare_rejects_spec_not_bound_to_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    _, evidence = _evidence(_G01)
    different_spec, _ = _good("g02_revenue_by_region.json")

    def _boom(*_args: object, **_kwargs: object) -> str:
        msg = "builder reached for mismatched evidence"
        raise AssertionError(msg)

    monkeypatch.setattr(render, "build_vega_lite", _boom)
    with pytest.raises(ValueError, match="does not match evidence"):
        render.prepare_render(different_spec, evidence)


def test_render_row_limit_is_inclusive_and_precedes_native(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec, evidence = _evidence(_G01)
    row_count = len(evidence.plotted_table.rows)
    prepared = _prepare(spec, evidence, limits=VerificationLimits(max_render_rows=row_count))
    assert prepared.evidence is evidence

    def _boom(_: str) -> str:
        msg = "native render reached after render-row refusal"
        raise AssertionError(msg)

    monkeypatch.setattr(render, "render_svg", _boom)
    with pytest.raises(VerificationError) as caught:
        render.render(
            spec,
            _manifest_bytes(_G01),
            data_dir=_DATA,
            limits=VerificationLimits(max_render_rows=row_count - 1),
        )
    assert caught.value.check == "resource.render_rows"
    assert str(caught.value) == (
        f"plotted table has {row_count} render rows; limit is {row_count - 1}"
    )


def test_vega_byte_limit_is_inclusive_and_precedes_native(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec, evidence = _evidence(_G01)
    expected = _prepare(spec, evidence).vega_lite
    exact = _prepare(spec, evidence, limits=VerificationLimits(max_vega_bytes=len(expected)))
    assert exact.vega_lite == expected

    def _boom(_: str) -> str:
        msg = "native render reached after Vega refusal"
        raise AssertionError(msg)

    monkeypatch.setattr(render, "render_svg", _boom)
    with pytest.raises(VerificationError) as caught:
        render.render(
            spec,
            _manifest_bytes(_G01),
            data_dir=_DATA,
            limits=VerificationLimits(max_vega_bytes=len(expected) - 1),
        )
    assert caught.value.check == "resource.vega_bytes"
    assert str(caught.value) == (
        f"Vega-Lite JSON has {len(expected)} bytes; limit is {len(expected) - 1}"
    )


def test_vcert_byte_limit_is_inclusive_and_precedes_native(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec, evidence = _evidence(_G01)
    prepared = _prepare(spec, evidence)
    payload_size = len(render.vcert_bytes(render._build_certificate(prepared)))
    native_inputs: list[str] = []

    def _svg_stub(vega_lite: str) -> str:
        native_inputs.append(vega_lite)
        return "<svg/>"

    monkeypatch.setattr(render, "render_svg", _svg_stub)
    admitted = render.render_prepared(
        prepared, limits=VerificationLimits(max_attestation_bytes=payload_size)
    )
    assert admitted.svg == "<svg/>"
    assert len(native_inputs) == 1

    with pytest.raises(VerificationError) as caught:
        render.render_prepared(
            prepared, limits=VerificationLimits(max_attestation_bytes=payload_size - 1)
        )
    assert len(native_inputs) == 1
    assert caught.value.check == "resource.attestation_bytes"
    assert str(caught.value) == (
        f"VCert payload has {payload_size} bytes; limit is {payload_size - 1}"
    )


def test_svg_byte_limit_counts_utf8_and_blocks_later_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec, evidence = _evidence(_G01)
    prepared = _prepare(spec, evidence)
    monkeypatch.setattr(render, "render_svg", lambda _vega: "éx")
    exact = render.render_prepared(prepared, limits=VerificationLimits(max_svg_bytes=3))
    assert exact.svg == "éx"

    monkeypatch.setattr(render, "render_svg", lambda _vega: "éxx")

    def _boom(_: str) -> str:
        msg = "HTML built after oversized SVG"
        raise AssertionError(msg)

    monkeypatch.setattr(render, "render_html", _boom)
    with pytest.raises(VerificationError) as caught:
        render.render_prepared(
            prepared, include_html=True, limits=VerificationLimits(max_svg_bytes=3)
        )
    assert caught.value.check == "resource.svg_bytes"
    assert str(caught.value) == "SVG has 4 bytes; limit is 3"


def test_html_byte_limit_counts_utf8_and_is_inclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    spec, evidence = _evidence(_G01)
    prepared = _prepare(spec, evidence)
    monkeypatch.setattr(render, "render_svg", lambda _vega: "<svg/>")
    monkeypatch.setattr(render, "render_html", lambda _vega: "éx")
    exact = render.render_prepared(
        prepared, include_html=True, limits=VerificationLimits(max_html_bytes=3)
    )
    assert exact.html == "éx"

    monkeypatch.setattr(render, "render_html", lambda _vega: "éxx")
    with pytest.raises(VerificationError) as caught:
        render.render_prepared(
            prepared, include_html=True, limits=VerificationLimits(max_html_bytes=3)
        )
    assert caught.value.check == "resource.html_bytes"
    assert str(caught.value) == "HTML has 4 bytes; limit is 3"


def test_certificate_hashes_equal_canonical() -> None:
    spec, _, table = _evaluated(_G01)
    result = _render(_G01)
    cert = result.certificate
    assert cert.version == "vcert-0.2"
    assert cert.dataset_hash == spec.dataset.hash
    assert cert.spec_hash == canon.hash_spec(spec)
    assert cert.plotted_table_hash == canon.hash_table(table)
    assert cert.manifest_hash == canon.hash_manifest(_manifest_bytes(_G01))
    assert cert.vega_lite_hash == "sha256:" + hashlib.sha256(result.vega_lite).hexdigest()


def test_vcert_bytes_is_deterministic_and_round_trips() -> None:
    """vcert_bytes is the public seam the service content-addresses (plot_id) and serves: the
    same VCert encodes byte-identically and the bytes decode back to an equal certificate."""
    cert = _render(_G01).certificate
    encoded = render.vcert_bytes(cert)
    assert render.vcert_bytes(cert) == encoded  # byte-stable
    assert msgspec.json.decode(encoded, type=render.VCert) == cert
    wire: dict[str, Any] = msgspec.json.decode(encoded)
    assert "checks" in wire
    assert "checks_passed" not in wire


def test_certificate_identity_binds_exact_vega_bytes() -> None:
    spec, evidence = _evidence(_G01)
    prepared = _prepare(spec, evidence)
    original = render._build_certificate(prepared)
    changed = render._build_certificate(replace(prepared, vega_lite=prepared.vega_lite + b" "))

    assert original.vega_lite_hash == render.hash_vega_lite(prepared.vega_lite)
    assert changed.vega_lite_hash == render.hash_vega_lite(prepared.vega_lite + b" ")
    assert original.vega_lite_hash != changed.vega_lite_hash
    assert render.vcert_bytes(original) != render.vcert_bytes(changed)
    assert (
        hashlib.sha256(render.vcert_bytes(original)).hexdigest()
        != hashlib.sha256(render.vcert_bytes(changed)).hexdigest()
    )


def test_certificate_identity_binds_visible_verifier_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec, evidence = _evidence(_G01)
    prepared = _prepare(spec, evidence)
    original = render._build_certificate(prepared)
    monkeypatch.setattr(render, "__version__", "0.2.0-test")
    changed = render._build_certificate(prepared)

    assert original.tcb.verifier_version == importlib.metadata.version("verifier")
    assert changed.tcb.verifier_version == "0.2.0-test"
    assert render.vcert_bytes(original) != render.vcert_bytes(changed)
    assert (
        hashlib.sha256(render.vcert_bytes(original)).hexdigest()
        != hashlib.sha256(render.vcert_bytes(changed)).hexdigest()
    )


def test_certificate_manifest_hash_flips_on_edit() -> None:
    # A different manifest byte-string yields a different manifest hash in the cert.
    cert = _render(_G01).certificate
    assert cert.manifest_hash != canon.hash_manifest(_manifest_bytes(_G01) + b" ")


def test_certificate_plotted_hash_flips_on_table_edit() -> None:
    _, _, table = _evaluated(_G01)
    edited = canon.Table(columns=table.columns, rows=table.rows[1:])
    cert = _render(_G01).certificate
    assert cert.plotted_table_hash != canon.hash_table(edited)


def test_certificate_bar_zero_check_present_for_bar_absent_otherwise() -> None:
    # g01 is a bar with no color; g07 is a line with color; g10 is a scatter with no color.
    assert "scale.bar_zero" in {item.id for item in _render(_G01).certificate.checks}
    assert "scale.bar_zero" not in {item.id for item in _render(_G07).certificate.checks}
    assert "scale.bar_zero" not in {item.id for item in _render(_G10).certificate.checks}


def test_certificate_bar_zero_absent_for_bar_without_quantitative_axis() -> None:
    # A bar whose positional channels are both non-quantitative gets NO scale.zero from the
    # builder, so the cert must not claim the bar-zero guarantee (that would be a false cert).
    spec = VPlotSpec(
        version="vplot-0.1",
        dataset=Dataset(name="t.csv", hash="sha256:" + "0" * 64),
        transform=(Select(fields=("a", "b")),),
        mark="bar",
        encoding=Encoding(
            x=Channel(field="a", kind="nominal"),  # kind= (Python attr); JSON key is "type"
            y=Channel(field="b", kind="ordinal"),
        ),
    )
    table = canon.Table(columns=(), rows=())
    evidence = _certificate_evidence(spec, table)
    cert = _certificate(spec, evidence)
    assert "scale.bar_zero" not in {item.id for item in cert.checks}


def test_certificate_legend_domain_check_present_only_with_color() -> None:
    assert "encoding.legend_domain_exact" in {item.id for item in _render(_G07).certificate.checks}
    assert "encoding.legend_domain_exact" not in {
        item.id for item in _render(_G01).certificate.checks
    }
    assert "encoding.legend_domain_exact" not in {
        item.id for item in _render(_G10).certificate.checks
    }


def test_certificate_includes_verifier_passes() -> None:
    passed = {item.id for item in _render(_G01).certificate.checks}
    assert "dataset.hash_matches_source" in passed
    assert "security.no_arbitrary_code" in passed


@pytest.mark.parametrize("name", [_G01, _G07, _G10])
def test_certificate_checks_equal_final_passing_report(name: str) -> None:
    spec, evidence = _evidence(name)
    preparation = render.prepare_render(spec, evidence)
    assert preparation.prepared is not None
    result = render.render_prepared(preparation.prepared)
    expected = tuple(
        render.CertifiedCheck(id=item.check, method=item.method, status="pass")
        for item in preparation.report.results
        if item.status == "pass"
    )
    assert result.certificate.checks == expected


def test_certificate_tcb_stamps_build() -> None:
    tcb = _render(_G01).certificate.tcb
    assert tcb.verifier_version == importlib.metadata.version("verifier")
    assert tcb.z3_version == formal.solver_version()
    assert tcb.canon_version == "canon-0.1"
    assert tcb.vl_version == "5.21"
    assert tcb.font_family == "DejaVu Sans"
    assert tcb.vendored_font_sha256 == "sha256:" + _FONT_SHA256
    assert tcb.vl_convert_python  # non-empty installed version string


def test_build_certificate_discloses_filters_and_sorts() -> None:
    # Direct _build_certificate over a spec mixing Filter/Sort/Select: the Filter arm fires and the
    # active sort's multi-key loop runs (supersession/discard is covered separately below).
    spec = VPlotSpec(
        version="vplot-0.1",
        dataset=Dataset(name="t.csv", hash="sha256:" + "0" * 64),
        transform=(
            Filter(field="a", cmp="gt", value="1"),
            Sort(
                by=(SortKey(field="a", order="ascending"), SortKey(field="b", order="descending"))
            ),
            Select(fields=("a", "b")),
        ),
        mark="line",
        encoding=Encoding(
            x=Channel(field="a", kind="quantitative"),  # kind= (Python attr); JSON key is "type"
            y=Channel(field="b", kind="quantitative"),
        ),
    )
    table = canon.Table(columns=(), rows=())
    evidence = _certificate_evidence(spec, table)
    cert = _certificate(spec, evidence)
    assert cert.filters == (render.DisclosedFilter(field="a", cmp="gt", value="1"),)
    assert cert.sorts == (
        render.DisclosedSort(field="a", order="ascending"),
        render.DisclosedSort(field="b", order="descending"),
    )


def test_build_certificate_empty_filters_and_sorts() -> None:
    # A spec with no Filter/Sort op -> empty disclosure tuples (the empty-comprehension arm).
    spec = VPlotSpec(
        version="vplot-0.1",
        dataset=Dataset(name="t.csv", hash="sha256:" + "0" * 64),
        transform=(Select(fields=("a",)),),
        mark="line",
        encoding=Encoding(
            x=Channel(field="a", kind="quantitative"),  # kind= (Python attr); JSON key is "type"
            y=Channel(field="a", kind="quantitative"),
        ),
    )
    table = canon.Table(columns=(), rows=())
    evidence = _certificate_evidence(spec, table)
    cert = _certificate(spec, evidence)
    assert cert.filters == ()
    assert cert.sorts == ()


def test_build_certificate_discloses_only_the_active_sort() -> None:
    # VPlot section 6: only the last sort with no later aggregate applies. The badge heads sorts
    # "Applied", so the cert must disclose that ACTIVE sort alone -- never a superseded or discarded
    # one, which would be a false "applied" claim.
    table = canon.Table(columns=(), rows=())

    def _sorts(transform: tuple[Transform, ...]) -> tuple[render.DisclosedSort, ...]:
        spec = VPlotSpec(
            version="vplot-0.1",
            dataset=Dataset(name="t.csv", hash="sha256:" + "0" * 64),
            transform=transform,
            mark="bar",
            encoding=Encoding(
                x=Channel(field="a", kind="nominal"),
                y=Channel(field="b", kind="ordinal"),
            ),
        )
        evidence = _certificate_evidence(spec, table)
        return _certificate(spec, evidence).sorts

    asc_a = Sort(by=(SortKey(field="a", order="ascending"),))
    desc_b = Sort(by=(SortKey(field="b", order="descending"),))
    count = Aggregate(measures=(Measure(field="a", fn="count", output="c"),))
    disc_b = (render.DisclosedSort(field="b", order="descending"),)
    assert _sorts((asc_a, desc_b)) == disc_b  # a later sort supersedes an earlier one
    assert _sorts((asc_a, count)) == ()  # an aggregate discards the earlier sort
    assert _sorts((asc_a, count, desc_b)) == disc_b  # a sort after the aggregate survives


@pytest.mark.parametrize("name", [_G01, _G07, _G10])
def test_certificate_bar_zero_disclosure_matches_builder(name: str) -> None:
    # CERT-HONESTY binding: bar-zero is disclosed EXACTLY when the builder emits `scale.zero` on a
    # positional channel -- tie the cert predicate to emitted Vega-Lite, catching any future drift.
    enc = _built(name)["encoding"]
    emits_zero = {"zero": True} in (
        enc["x"].get("scale"),  # type: ignore[index]
        enc["y"].get("scale"),  # type: ignore[index]
    )
    discloses = "scale.bar_zero" in {item.id for item in _render(name).certificate.checks}
    assert discloses == emits_zero


@pytest.mark.parametrize("name", [_G01, _G07, _G10])
def test_certificate_legend_domain_disclosure_matches_builder(name: str) -> None:
    # CERT-HONESTY binding: the formal result is disclosed exactly when the builder emits an
    # explicit discrete color domain over its inlined verified data.
    encoding = _built(name)["encoding"]
    has_domain = "color" in encoding and "scale" in encoding["color"]  # type: ignore[operator,index]
    discloses = "encoding.legend_domain_exact" in {
        item.id for item in _render(name).certificate.checks
    }
    assert discloses == has_domain


def test_badge_html_renders_cert_fields() -> None:
    cert = _render(_G01).certificate
    badge = render.badge_html(cert)
    assert "<script" not in badge
    assert cert.spec_hash in badge
    assert cert.vega_lite_hash in badge
    assert "dataset.hash_matches_source" in badge
    assert "deterministic_recompute" in badge
    assert cert.tcb.verifier_version in badge
    assert cert.tcb.z3_version in badge
    assert render._FONT_FAMILY in badge


def test_badge_html_with_filters_and_sorts() -> None:
    # Non-empty filters + sorts -> the disclosure loops fire (covers the join comprehensions).
    cert = render.VCert(
        version="vcert-0.2",
        dataset_hash="sha256:" + "0" * 64,
        spec_hash="sha256:" + "1" * 64,
        plotted_table_hash="sha256:" + "2" * 64,
        manifest_hash="sha256:" + "3" * 64,
        vega_lite_hash="sha256:" + "4" * 64,
        checks=(
            render.CertifiedCheck(
                id="security.no_arbitrary_code", method="construction", status="pass"
            ),
        ),
        filters=(render.DisclosedFilter(field="region", cmp="eq", value="EU"),),
        sorts=(render.DisclosedSort(field="month", order="ascending"),),
        tcb=render._tcb(),
    )
    badge = render.badge_html(cert)
    assert "region" in badge
    assert "month" in badge
    assert "<script" not in badge


def _filter_cert(value: int | str) -> render.VCert:
    """A minimal cert whose single disclosed filter carries `value` (the badge display tests)."""
    return render.VCert(
        version="vcert-0.2",
        dataset_hash="sha256:" + "0" * 64,
        spec_hash="sha256:" + "1" * 64,
        plotted_table_hash="sha256:" + "2" * 64,
        manifest_hash="sha256:" + "3" * 64,
        vega_lite_hash="sha256:" + "4" * 64,
        checks=(),
        filters=(render.DisclosedFilter(field="x", cmp="eq", value=value),),
        sorts=(),
        tcb=render._tcb(),
    )


def test_badge_html_escapes_adversarial_filter_value() -> None:
    # A model-controlled filter value carrying markup + control chars is escaped to inert text.
    # chr(0x2028) = U+2028 LINE SEPARATOR: inert in HTML text. Built via chr() rather than a
    # unicode-escape literal so the source stays pure ASCII -> ruff RUF001 stays silent, and no
    # Write/Edit JSON transport can decode an escape back into the raw char (which re-triggers it).
    hostile = "</script><script>alert(1)</script><>&\"'\n" + chr(0x2028)
    badge = render.badge_html(_filter_cert(hostile))
    assert "<script>" not in badge
    assert "</script>" not in badge
    assert "&lt;script&gt;" in badge
    assert "&amp;" in badge and "&quot;" in badge and "&#x27;" in badge


def test_badge_html_filter_literal_control_chars_visible() -> None:
    # Disclosure must be AUDITABLE, not merely inert: control / format / bidi code points in a
    # model-controlled literal (NUL, newline, tab, U+2028, U+202E RIGHT-TO-LEFT OVERRIDE -- which
    # would visually reorder the badge text) render as visible \uXXXX / \n escapes inside a
    # JSON-quoted literal, so two distinct literals can never display identically. The raw
    # chars themselves never reach the HTML.
    hostile = "a\x00b\nc\td" + chr(0x2028) + "e" + chr(0x202E) + "f"
    badge = render.badge_html(_filter_cert(hostile))
    for raw in ("\x00", "\n", "\t", chr(0x2028), chr(0x202E)):
        assert raw not in badge  # the raw control/format char never reaches the HTML
    backslash = chr(0x5C)  # built via chr() so this source line stays pure ASCII
    for code in ("u0000", "n", "t", "u2028", "u202e"):
        assert backslash + code in badge  # ...its visible backslash-escape does
    assert "&quot;a" in badge  # JSON-quoted: the literal's bounds are explicit


def test_badge_html_int_and_string_literals_display_distinctly() -> None:
    # int 5 and string "5" are DIFFERENT filter literals (b10's defect class); the badge must
    # display them distinctly: bare 5 vs JSON-quoted &quot;5&quot;.
    assert "<li>x eq 5</li>" in render.badge_html(_filter_cert(5))
    assert "<li>x eq &quot;5&quot;</li>" in render.badge_html(_filter_cert("5"))


# --- M1.6d: OPTIONAL offline HTML view (off the cert hash chain) --------------
# External-fetch audit for the HTML page: a src/href attribute valued as an absolute http(s) URL
# (a network load on page open). The inlined bundle carries none (regression-guarded below) and the
# template adds none; scoped to http(s):// so an inert data string never false-positives, and to a
# QUOTED attribute so a minified-JS fragment (an unquoted `.src=`) does not.
_HTML_FETCH_RE = re.compile(r"""(?i)\b(?:src|href)\s*=\s*(["'])https?://""")


def _json_data_block(html_doc: str) -> str:
    """The inert application/json spec payload from a render_html page, up to the first real
    </script> (the payload's own "<" bytes are all escaped, so no </script> appears inside it)."""
    match = re.search(r'<script type="application/json"[^>]*>(.*?)</script>', html_doc, re.DOTALL)
    assert match is not None
    return match.group(1)


def _html(name: str) -> str:
    spec, manifest, table = _evaluated(name)
    return render.render_html(render.vega_lite_json(spec, table, manifest))


def test_embed_bundle_is_offline_and_deterministic() -> None:
    # Static regression guard over the pinned bundle (not a runtime proof): no quoted absolute
    # http(s) src/href, no raw </script> that would break its inlining <script> wrapper, byte-stable
    # across in-process rebuilds. The vega runtime's dormant URL code paths (an unquoted `.src=`,
    # `new URL(...)`) stay inert -- render_svg's allowlist + allowed_base_urls=[] is the enforced
    # offline boundary -- so the broad _external_refs audit is not run here (it false-positives on
    # minified JS).
    render._embed_bundle.cache_clear()
    bundle = render._embed_bundle()
    assert len(bundle) > 100_000  # vega + vega-lite + vega-embed inlined, not a stub
    assert _HTML_FETCH_RE.search(bundle) is None  # no quoted absolute http(s) src/href
    assert "</script" not in bundle.lower()  # a raw close would terminate the wrapper <script>
    render._embed_bundle.cache_clear()  # drop the cache so the compare is a genuine rebuild
    assert bundle == render._embed_bundle()


def test_render_html_scaffold_is_self_contained() -> None:
    # Strip the (separately audited) bundle; the surrounding template + inlined spec data reference
    # nothing fetchable -- reuse the SVG suite's audit (proven non-vacuous by the leak test).
    html_doc = _html(_G07)
    scaffold = html_doc.replace(render._embed_bundle(), "[BUNDLE]")
    assert _external_refs(scaffold) == []
    assert _HTML_FETCH_RE.search(html_doc) is None  # static scan: no absolute http(s) src/href


def test_render_html_self_reports_height_for_iframe_embed() -> None:
    # An M4 sandboxed-iframe embed has no intrinsic height -> the page must self-report or render
    # tiny. The trusted-template reporter posts {type:"iframe:height",height} to the parent on load
    # AND on every ResizeObserver tick (async vega render grows the DOM after load). Open WebUI's
    # listener applies our height VERBATIM (memory "## M4"), so it must be the viewport-INDEPENDENT
    # content box (getBoundingClientRect), never the frame-viewport-floored scrollHeight -- else a
    # chart shorter than its frame reports inflated and can never shrink. Fixed self-contained JS,
    # off the cert hash chain -- it adds no fetchable ref (scaffold audit clean).
    html_doc = _html(_G01)
    assert render._HEIGHT_REPORTER in html_doc  # the exact trusted-template reporter is embedded
    assert 'type:"iframe:height"' in html_doc  # Open WebUI's own message key (keep verbatim)
    assert "ResizeObserver" in html_doc  # re-posts on content resize, not only the initial load
    assert "getBoundingClientRect" in render._HEIGHT_REPORTER  # viewport-independent content box
    assert "scrollHeight" not in render._HEIGHT_REPORTER  # not the viewport-floored measure
    # the reporter is the page's LAST <script> (fires after the vega-embed script it follows)
    assert html_doc.endswith(f"<script>{render._HEIGHT_REPORTER}</script>\n</body>\n</html>\n")
    scaffold = html_doc.replace(render._embed_bundle(), "[BUNDLE]")
    assert _external_refs(scaffold) == []  # the reporter introduces no external/fetchable ref


def test_render_html_is_menu_free_and_client_rendered() -> None:
    html_doc = _html(_G01)
    assert "vegaEmbed(" in html_doc  # a client-rendered vega-embed, not a pre-rasterized image
    assert '{actions: false, renderer: "svg"}' in html_doc  # no editor/actions menu


def test_render_html_embeds_the_built_spec() -> None:
    # The page shows the SAME recomputed data the SVG/cert are built from: the inert data block
    # parses back to the builder JSON (lossless through the every-"<"-to-U+003C escape).
    spec, manifest, table = _evaluated(_G01)
    built_json = render.vega_lite_json(spec, table, manifest)
    assert json.loads(_json_data_block(render.render_html(built_json))) == json.loads(built_json)


@pytest.mark.parametrize(
    "payload",
    [
        '{"data":{"values":[{"a":"</script><svg onload=alert(1)>","b":1}]}}',  # direct </script>
        '{"data":{"values":[{"a":"<!--<script>alert(1)</script>-->","b":1}]}}',  # double-escape
    ],
)
def test_render_html_neutralizes_script_breakout(payload: str) -> None:
    # A data cell holding raw script-data markup -- a literal </script>, OR a <!--<script> pair that
    # would drive the HTML5 tokenizer into its script-data-double-escaped state (where the block's
    # own </script> no longer closes it) -- must not corrupt the page. Escaping EVERY "<" leaves no
    # raw "<" in the data block, so no such markup can open; JSON.parse still recovers the value.
    block = _json_data_block(render.render_html(payload))
    assert "<" not in block  # no raw "<" -> no script-data markup can open (breakout-proof)
    assert json.loads(block) == json.loads(payload)


def test_render_html_is_deterministic() -> None:
    render._embed_bundle.cache_clear()
    first = _html(_G10)
    render._embed_bundle.cache_clear()  # rebuild the bundle too, not just reuse the cached object
    assert first == _html(_G10)


def test_render_include_html_attaches_offline_view() -> None:
    spec, manifest, table = _evaluated(_G01)
    result = render.render(spec, _manifest_bytes(_G01), data_dir=_DATA, include_html=True)
    assert result is not None
    assert result.html is not None
    assert result.html == render.render_html(render.vega_lite_json(spec, table, manifest))
    assert result.html.startswith("<!doctype html>")


def test_render_default_omits_html() -> None:
    assert _render(_G01).html is None  # off by default -> no bundling cost unless requested


def test_render_html_is_off_the_cert_hash_chain() -> None:
    # Requesting the HTML view changes neither Vega/SVG bytes nor the certificate.
    spec, _ = _good(_G01)
    mb = _manifest_bytes(_G01)
    plain = render.render(spec, mb, data_dir=_DATA)
    withhtml = render.render(spec, mb, data_dir=_DATA, include_html=True)
    assert plain is not None and withhtml is not None
    assert plain.vega_lite == withhtml.vega_lite
    assert plain.svg == withhtml.svg
    assert plain.certificate == withhtml.certificate
    assert plain.html is None and withhtml.html is not None
