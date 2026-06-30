# M1.6a render builder — transcription recipe

TRANSCRIBE, do NOT re-derive. The prior session overflowed a 200K window in DESIGN alone (no
code written) by re-confirming the at-scale invariant, re-resolving the serializer
architecture, and re-analyzing coverage. Everything it derived is below, symbol-checked vs
`canon.py`/`checks.py`/`ingest.py`/`schema.py`/`eval.py`/`pyproject.toml` + the corpus this
session. Write the three artifacts verbatim, run the gate, fix only real gate failures. This recipe was
gate-VALIDATED end-to-end (ruff format+check, mypy --strict, pytest 400 passed @ 100% branch
incl. render.py 58stmt/26br) then the implementation reverted — so expect a CLEAN pass; the
lint/type fixes that surfaced are already folded in (FBT003 noqa on the two bool asserts;
`Decimal(5)` for FURB157; `# type: ignore[index]` — not `[operator]` — on the asserts that
index a `dict[str, object]` value, since indexing `object` errors first and yields `Any`). The
frozenset/signature line reflows are pure `ruff format` output (the format step normalizes them).
Reach the gate early to confirm. Delete this doc at M1 review.

Read NOTHING else except the two rename targets (`checks.py`, `tests/test_checks.py`); all
external signatures are inlined here. The roadmap M1.6 SHARED + M1.6a bullets carry the
trust-model rationale (already read at session start).

## Verified external signatures (do not re-open these files)
- `canon._format_decimal(value: Decimal, scale: int) -> str` — fixed-point token, exactly
  `scale` places, ROUND_HALF_EVEN, folds -0→+0, no sci-notation. Reuse via the MODULE
  (`canon._format_decimal(...)`) — ruff PLC2701 flags `from canon import _x`, not attr access
  (same pattern as eval→`ingest._decimal_at_scale`).
- `canon.Cell = Decimal | str | None`; `canon.Table{columns: tuple[Column,...], rows:
  tuple[tuple[Cell,...],...]}`; `Column` union members each have `.name` (+ `.kind` ClassVar).
- `checks.unit_source(name: str, aggregates: tuple[Aggregate,...]) -> str | None` (AFTER the
  rename below) — reverse lineage: count-derived→None, else the manifest column name. Works
  for any channel kind (x/y/color), not just numeric.
- `ingest.Manifest{dataset: str, columns: tuple[ManifestColumn,...]}`;
  `ingest.NumericColumnSpec{name, scale, unit: str|None=None, label: str|None=None}`;
  `ingest.TemporalColumnSpec{name, granularity, label: str|None=None}`;
  `ingest.StringColumnSpec{name, label: str|None=None}`;
  `ingest.ManifestColumn = NumericColumnSpec | TemporalColumnSpec | StringColumnSpec`;
  `ingest.load_manifest(bytes) -> Manifest`. Structs are directly constructible (kw_only); Meta
  constraints enforce at DECODE only, so direct construction skips them — fine for tests.
- `schema.VPlotSpec{version, dataset{name,hash}, transform: tuple[Transform,...], mark,
  encoding}`; `Encoding{x: Channel, y: Channel, color: Channel|None=None}`; `Channel{field:
  str, kind: ChannelType}` (kind = JSON key `type`); `Mark = Literal["bar","line","scatter"]`;
  `ChannelType = Literal["quantitative","temporal","ordinal","nominal"]`; `Aggregate{measures:
  tuple[Measure,...]}`; `Measure{field, fn, output}` (output = JSON key `as`).
- `eval.evaluate(spec: VPlotSpec, manifest: ingest.Manifest, csv_bytes: bytes) -> canon.Table`.
- Config: ruff line-length 100, full select incl. FBT/EM/TRY/RET/PL/S/TID; mypy --strict;
  coverage branch=true source=["verifier"] fail_under=100. Gate = `uv run --locked` (below).

## Key decisions (already resolved — do not re-litigate)
- The serializer keys Decimal scale off the cell's OWN exponent (`-value.as_tuple().exponent`),
  NOT the column scale: every canon.Table numeric cell has exponent == -column.scale (ingest
  re-quantize + eval `_scaled_int_to_decimal`), so this equals column-scale formatting AND the
  generic `_dumps` walk needs no per-cell column context. Reusing `_format_decimal` (vs
  `format(v,'f')`) is load-bearing: it folds -0, matching canon's NDJSON byte-for-byte.
- A Decimal cannot live in a plain dict as a JSON NUMBER (stdlib `json` raises on Decimal;
  `default=str` would stringify; a float is lossy). So `_dumps` is the SOLE serializer and its
  STRING is the authoritative artifact M1.6b/c consume; `build_vega_lite` returns Decimals in
  `data.values` for structural/allowlist assertions only (deliberately not stdlib-serializable).
- Float at the JSON boundary is FORBIDDEN (determinism guard) → `_cell_to_json` raises
  TypeError on float (and on int/anything non-{None,bool,str,Decimal} — none of which the
  builder emits; the raise is defensive, covered once by a float test).
- M1.6a escaping = JSON-string escaping via `msgspec.json.encode` (in `_cell_to_json` str
  arm). XML/HTML escaping of SVG/badge text is M1.6b (vl-convert) / M1.6c (badge_html).
- NO `position: bool` param anywhere (FBT). Stack/scale logic lives in a `build_vega_lite` loop
  over (x,y); `_channel` is position-agnostic.
- Count-axis title is the FIXED constant `"count"`, never the model's aggregate-output name
  (titles stay manifest-sourced, never spec-proposed).

## Artifact 1 — `src/verifier/render.py` (write verbatim; `ruff format` after)
```python
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""VPlot -> Vega-Lite builder (M1.6a, the pure no-native-dep half).

Turns an untrusted VPlotSpec plus the verifier's recomputed plotted table into a Vega-Lite
v5 spec dict that inlines ONLY that table. Two trust mechanisms, kept distinct: (1) the
builder copies NO model-supplied Vega-Lite key, so no dangerous data/JS/URL sink can appear
(positive allowlist by construction); (2) it EMITS its own narrow fixed safe set to pin
determinism -- every channel sort:null, quantitative stack:null, line order:null, bar
scale.zero -- defeating Vega-Lite's implicit field-sort / line-vertex-sort / legend-domain
sort / stacking so the displayed marks match the recomputed row order.

Axis titles are manifest-sourced via checks.unit_source lineage (count-derived -> the fixed
"count", as a count is dimensionless and its output name is model-proposed). _dumps is the
SOLE serializer: a Decimal cell becomes a RAW fixed-point JSON number token (canon's
fixed-point form, -0 folded), so the same table yields byte-identical JSON; a Python float
is rejected at the boundary. The string _dumps returns is the authoritative artifact M1.6b/c
consume -- stdlib json.dumps is never applied to builder output (it cannot serialize the
Decimals build_vega_lite keeps in data.values).
"""

from decimal import Decimal
from typing import Any, cast

import msgspec

from verifier import canon, checks, ingest
from verifier.schema import Aggregate, Channel, VPlotSpec

# $schema is the Vega-Lite v5 MAJOR-version URI constant -- a fixed string, DECOUPLED from the
# exact bundled minor (vl_version is M1.6b's determinism lever), so this half needs no dep.
_VEGA_LITE_SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"
# The font family name only; the font FILE + register_font_directory land at M1.6b.
_FONT_FAMILY = "Inter"
_COUNT_AXIS_TITLE = "count"
# Vega-Lite has no scatter mark; scatter -> point.
_MARK_MAP: dict[str, str] = {"bar": "bar", "line": "line", "scatter": "point"}


def _cell_to_json(value: object) -> str:
    """One scalar as its JSON token. Decimal -> raw fixed-point number at the cell's own scale
    (== column scale by the at-scale invariant), -0 folded via canon._format_decimal; str ->
    msgspec JSON string (escaping); None -> null; bool -> true/false. A float (or any other
    type) is forbidden at the JSON boundary -- the determinism guard keeping lossy floats out."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return msgspec.json.encode(value).decode("utf-8")
    if isinstance(value, Decimal):
        scale = -cast(int, value.as_tuple().exponent)
        return canon._format_decimal(value, scale)
    msg = f"value is not JSON-serializable in a verified chart: {value!r}"
    raise TypeError(msg)


def _dumps(obj: object) -> str:
    """The sole, authoritative serializer: a deterministic compact JSON string with Decimals as
    RAW number tokens (stdlib json cannot emit a Decimal as a number). Walks dicts/lists; every
    leaf goes through _cell_to_json (so a stray float raises)."""
    if isinstance(obj, dict):
        return "{" + ",".join(f"{_cell_to_json(k)}:{_dumps(v)}" for k, v in obj.items()) + "}"
    if isinstance(obj, list):
        return "[" + ",".join(_dumps(item) for item in obj) + "]"
    return _cell_to_json(obj)


def _manifest_column(manifest: ingest.Manifest, name: str) -> ingest.ManifestColumn:
    return {column.name: column for column in manifest.columns}[name]


def _axis_title(field: str, aggregates: tuple[Aggregate, ...], manifest: ingest.Manifest) -> str:
    """A channel's axis title from the manifest (never the spec): the lineage source's label
    (or its name when unlabelled), plus a unit suffix for a numeric source that declares one. A
    count-derived channel has no source -> the fixed dimensionless title."""
    source = checks.unit_source(field, aggregates)
    if source is None:
        return _COUNT_AXIS_TITLE
    column = _manifest_column(manifest, source)
    base = column.label if column.label is not None else column.name
    if isinstance(column, ingest.NumericColumnSpec) and column.unit is not None:
        return f"{base} ({column.unit})"
    return base


def _channel(
    channel: Channel, aggregates: tuple[Aggregate, ...], manifest: ingest.Manifest
) -> dict[str, Any]:
    """A channel definition with the always-emitted safe keys: field + type + sort:null (defeats
    the implicit field sort, and a nominal color's legend-domain sort) + a manifest-sourced
    title. stack/scale are added per-channel by build_vega_lite."""
    return {
        "field": channel.field,
        "type": channel.kind,
        "sort": None,
        "title": _axis_title(channel.field, aggregates, manifest),
    }


def build_vega_lite(
    spec: VPlotSpec, table: canon.Table, manifest: ingest.Manifest
) -> dict[str, Any]:
    """The Vega-Lite v5 spec dict inlining only the recomputed table. Carries Decimal cells in
    data.values (for structural/allowlist assertions; NOT stdlib-serializable) -- vega_lite_json
    is the serializable handoff. Emits only allowlisted keys (copies no model Vega key)."""
    aggregates = tuple(t for t in spec.transform if isinstance(t, Aggregate))
    values = [
        {column.name: cell for column, cell in zip(table.columns, row, strict=True)}
        for row in table.rows
    ]
    x = _channel(spec.encoding.x, aggregates, manifest)
    y = _channel(spec.encoding.y, aggregates, manifest)
    for encoded, channel in ((x, spec.encoding.x), (y, spec.encoding.y)):
        if channel.kind == "quantitative":
            encoded["stack"] = None  # defeat implicit stacking
            if spec.mark == "bar":
                encoded["scale"] = {"zero": True}  # bar baseline-0 obligation (section 7)
    encoding: dict[str, Any] = {"x": x, "y": y}
    if spec.encoding.color is not None:
        encoding["color"] = _channel(spec.encoding.color, aggregates, manifest)
    if spec.mark == "line":
        encoding["order"] = None  # data-order vertex connection (else Vega sorts by x)
    return {
        "$schema": _VEGA_LITE_SCHEMA,
        "data": {"values": values},
        "mark": _MARK_MAP[spec.mark],
        "encoding": encoding,
        "config": {"font": _FONT_FAMILY},
    }


def vega_lite_json(spec: VPlotSpec, table: canon.Table, manifest: ingest.Manifest) -> str:
    """The authoritative Vega-Lite JSON string (raw Decimal tokens, floats rejected) -- the form
    M1.6b's render_svg consumes."""
    return _dumps(build_vega_lite(spec, table, manifest))
```

## Artifact 2 — rename `checks._unit_source` -> `checks.unit_source`
Render imports it for titles (verify->render is natural layering). Keep the body + docstring;
rename only the symbol. Three TARGETED edits in `src/verifier/checks.py` (no docstring mentions
it; replace_all is safe here but use the exact strings):
- `def _unit_source(name: str` -> `def unit_source(name: str`
- `return _unit_source(measure.field, aggregates[:i])` -> `return unit_source(measure.field, aggregates[:i])`
- `source = _unit_source(ch.field, aggregates)` -> `source = unit_source(ch.field, aggregates)`

Four TARGETED edits in `tests/test_checks.py`. WARNING: `test_unit_source_lineage_arm`
CONTAINS the substring `_unit_source` -> a blind replace_all corrupts the function name. Edit
ONLY these exact strings:
- `direct _unit_source tests pin` -> `direct unit_source tests pin` (module docstring)
- `not only _unit_source.` -> `not only unit_source.` (comment)
- `# --- _unit_source:` -> `# --- unit_source:` (section comment)
- `checks._unit_source(name, aggregates)` -> `checks.unit_source(name, aggregates)` (the assert)

## Artifact 3 — `tests/test_render.py` (write verbatim; `ruff format` after)
```python
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M1.6a render-builder tests: the canonical JSON serializer + the positive-allowlist Vega-Lite
builder, fully unit-testable (no native dep).

The serializer pins each cell kind to its token (Decimal -> raw fixed-point number, -0 folded;
float rejected) and the raw-token/round-trip property. The builder is driven from good corpus
specs (g01 bar/no-color over sales, g07 line+color over weather, g10 scatter over weather) so
every branch fires: mark map (all 3, behaviorally -- a lookup table is invisible to branch
coverage), every-channel sort:null, color present/absent, line order:null vs omitted,
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

from verifier import ingest, render
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
@pytest.mark.parametrize(("name", "mark"), [(_G01, "bar"), (_G07, "line"), (_G10, "point")])
def test_mark_map(name: str, mark: str) -> None:
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


def test_line_order_null() -> None:
    assert _built(_G07)["encoding"]["order"] is None  # type: ignore[index]


def test_non_line_omits_order() -> None:
    for name in (_G01, _G10):
        assert "order" not in _built(name)["encoding"]  # type: ignore[operator]


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
def test_axis_title_branches(
    field: str, aggregates: tuple[Aggregate, ...], title: str
) -> None:
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
        "$schema", "data", "values", "mark", "encoding", "config", "font",
        "x", "y", "color", "order", "field", "type", "sort", "title", "stack", "scale", "zero",
    }
)
# Keys that would re-open a data/JS/URL sink if the builder ever copied a model-supplied one.
_DANGEROUS_KEYS = frozenset(
    {
        "url", "datasets", "transform", "params", "expr", "href", "tooltip",
        "loader", "signals", "aggregate", "bin", "impute", "domain",
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
```

## Branch-coverage map (every render.py arc has a witness)
- `_cell_to_json`: None (sort:null in any build) · bool True (bar scale.zero) · bool False
  (direct test) · str (titles/mark/fields) · Decimal (table cells) · raise (float test).
- `_dumps`: dict + list + scalar all hit by any full build; float-raise by the nested test.
- `_manifest_column`: every build (no dead arm — dict-lookup KeyError, never an explicit raise).
- `_axis_title`: source None (count arm) · label present + absent · numeric+unit /
  numeric-no-unit / non-numeric — all in `test_axis_title_branches`; g01/g07 add integration.
- `build_vega_lite`: quant True (g01 y / g10 x) + False (g01 x ordinal / g07 x temporal) · bar
  True (g01) + False (g07/g10) · color True (g07) + False (g01) · line True (g07) + False
  (g01/g10). g01+g07 alone cover all four; g10 adds the scatter mark-map entry.
- mark map + allowlist: behavioral (a dict/key-set is invisible to branch coverage) — pinned by
  enumerating g01/g07/g10.

## Gate + close
1. `export UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy` then run, fixing real failures:
   `uv run --locked ruff format . && uv run --locked ruff check . && uv run --locked mypy && uv run --locked pytest`
   (mypy/pytest read pyproject `files`/`addopts`; pytest enforces 100% branch via `--cov`).
   If coverage < 100%, the map above names each arc's witness — find the missing one, do not
   add `# pragma`. If the `# type: ignore[...]` codes on the dict-index lines mismatch your
   mypy, adjust the code in the bracket (the indexing into `dict[str, object]` is the cause).
2. Record durable lessons in `.agent/memory.md` (M1.6a entry: the serializer-keys-off-exponent
   decision; `_dumps`-sole-serializer; the test_checks replace_all hazard; whatever the gate
   surfaced). Prune the M1.6 "TRANSCRIBE not re-explore" Deferred note's now-spent parts.
3. Roadmap: set M1.6a DONE, record `.agent/context.sh` full `pct used/window` in its Ctx cell.
4. Commit `render (M1.6a): canonical JSON serializer + Vega-Lite positive-allowlist builder + unit_source rename`.
