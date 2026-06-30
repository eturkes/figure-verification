# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""VPlot -> Vega-Lite builder (M1.6a, the pure no-native-dep half).

Turns an untrusted VPlotSpec plus the verifier's recomputed plotted table into a Vega-Lite
v5 spec dict that inlines ONLY that table. Two trust mechanisms, kept distinct: (1) the
builder copies NO model-supplied Vega-Lite key, so no dangerous data/JS/URL sink can appear
(positive allowlist by construction); (2) it EMITS its own narrow fixed safe set to pin
determinism -- every channel sort:null, quantitative stack:null, line-mark order:null, bar
scale.zero -- defeating Vega-Lite's implicit field-sort / line-vertex-sort / legend-domain
sort / stacking so the displayed marks are intended to match the recomputed row order (M1.6b
compile-confirms the effect).

Axis titles are manifest-sourced via checks.unit_source lineage (count-derived -> the fixed
"count", as a count is dimensionless and its output name is model-proposed). _dumps is the
SOLE serializer: a Decimal cell becomes a RAW fixed-point JSON number token at its COLUMN
scale (build re-quantizes each data cell via _scaled_cell, so the inlined number equals the
hashed table's token), -0 folded, so the same table yields byte-identical JSON; a Python float
is rejected at the boundary. The string _dumps returns is the authoritative artifact M1.6b/c
consume -- stdlib json.dumps is never applied to builder output (it cannot serialize the
Decimals build_vega_lite keeps in data.values).
"""

import importlib.resources
from decimal import Decimal
from typing import Any, cast

import msgspec
import vl_convert

from verifier import canon, checks, ingest
from verifier.schema import Aggregate, Channel, VPlotSpec

# $schema is the Vega-Lite v5 MAJOR-version URI constant -- a fixed string, DECOUPLED from the
# exact bundled minor (vl_version is M1.6b's determinism lever), so this half needs no dep.
_VEGA_LITE_SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"
# The family name of the vendored font (the file + register_font_directory are below). Naming
# it in every spec's config routes all text through these exact bytes for stable metrics.
_FONT_FAMILY = "DejaVu Sans"
_COUNT_AXIS_TITLE = "count"
# Vega-Lite has no scatter mark; scatter -> point.
_MARK_MAP: dict[str, str] = {"bar": "bar", "line": "line", "scatter": "point"}


def _cell_to_json(value: object) -> str:
    """One scalar as its JSON token. Decimal -> raw fixed-point number at the cell's own scale
    (builder data cells pre-quantized to scale >= 0 via _scaled_cell; a raw positive-exponent
    Decimal is out of contract, it raises here), -0 folded via
    canon._format_decimal; str -> msgspec JSON string (escaping); None -> null; bool ->
    true/false. A float (or any other type) is forbidden at the JSON boundary -- the determinism
    guard keeping lossy floats out."""
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


def _scaled_cell(column: canon.Column, cell: canon.Cell) -> canon.Cell:
    """A data cell validated and re-quantized to its column's canonical scale. canon._cell_token
    is the authority: it raises on any (column, cell) type mismatch -- a Decimal in a string
    column, a str in a numeric column, a non-finite numeric -- EXACTLY as the table hash does, so
    the builder is total over a canon.Table iff hash_table is (no silent mis-serialization). A
    numeric cell returns the Decimal of that token, whose JSON form EQUALS the hashed token BY
    CONSTRUCTION (not merely by the evaluate/ingest at-scale invariant); str/None pass through
    verbatim (their token re-derives identically in _cell_to_json)."""
    token = canon._cell_token(column, cell)  # validates the pairing; raises on a type mismatch
    if isinstance(column, canon.NumericColumn) and cell is not None:
        return Decimal(token)  # re-quantized to the column scale -> token == the hash token
    return cell


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
    data.values (each re-quantized to its column scale via _scaled_cell, for structural/allowlist
    assertions; NOT stdlib-serializable) -- vega_lite_json is the serializable handoff. Emits only
    allowlisted keys (copies no model Vega key). Accepts every (cell, row-width) hash_table accepts
    -- each (column, cell) routed through canon._cell_token via _scaled_cell, the zip(strict=True)
    row-width check -- so it never silently mis-serializes a cell the hash would reject; it adds ONE
    render-specific rejection hash_table lacks: duplicate column names (they collapse in each row
    dict, silently dropping a column, where canon's positional NDJSON tolerates them). So the
    builder's domain is hash_table's minus duplicate-name tables, never a superset."""
    names = [column.name for column in table.columns]
    if len(set(names)) != len(names):
        msg = f"duplicate column names in the plotted table: {names!r}"
        raise ValueError(msg)
    aggregates = tuple(t for t in spec.transform if isinstance(t, Aggregate))
    values = [
        {col.name: _scaled_cell(col, cell) for col, cell in zip(table.columns, row, strict=True)}
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
    mark: dict[str, Any] | str = _MARK_MAP[spec.mark]
    if spec.mark == "line":
        # order:null is a MARK property -- the v5 `encoding.order` channel admits no null. Connect
        # vertices in the recomputed row order (else Vega sorts line points by the x field).
        mark = {"type": _MARK_MAP[spec.mark], "order": None}
    return {
        "$schema": _VEGA_LITE_SCHEMA,
        "data": {"values": values},
        "mark": mark,
        "encoding": encoding,
        "config": {"font": _FONT_FAMILY},
    }


def vega_lite_json(spec: VPlotSpec, table: canon.Table, manifest: ingest.Manifest) -> str:
    """The authoritative Vega-Lite JSON string (raw Decimal tokens, floats rejected) -- the form
    render_svg consumes."""
    return _dumps(build_vega_lite(spec, table, manifest))


# --- SVG rendering (M1.6b: the vl-convert native dep) ------------------------
# Two determinism levers: a pinned Vega-Lite version (one of get_vegalite_versions()) and the
# vendored DejaVu Sans, registered below and named by _FONT_FAMILY in every spec's config. Within
# one pinned vl-convert-python build the SVG bytes are reproducible across calls (same-process /
# same-build; NOT a cross-machine guarantee -- the SVG is trusted TCB output, never hashed into
# the cert). DejaVu Sans is the matplotlib-proven deterministic default and covers the corpus
# glyphs (Latin plus the degree sign in "°C"). Vendoring + registration guarantee the family
# RESOLVES regardless of the host's system fonts; on a host already carrying DejaVu Sans the
# rendered metrics are identical either way (cross-machine identity is not claimed). v5.21 matches
# the v5 $schema constant above.
_VL_VERSION = "5.21"
_FONT_DIR = importlib.resources.files("verifier") / "assets" / "fonts"

# Register the vendored font directory ONCE at import: register_font_directory mutates vl-convert's
# process-global font database, so this single call serves every later render_svg. It no-ops
# silently on a missing dir, so the asset's presence + sha256 are pinned by a test rather than a
# hard import-time raise (whose never-missing branch would be uncoverable under the 100% gate).
vl_convert.register_font_directory(str(_FONT_DIR))


def render_svg(vega_lite_json: str) -> str:
    """A static SVG from a BUILDER-PRODUCED Vega-Lite JSON string (vega_lite_json's output, never a
    stdlib-serialized dict). Self-containment rests on that input precondition -- the positive
    allowlist emits no image/href/url/datasets sink -- PLUS allowed_base_urls=[], which hard-blocks
    every external DATA url at COMPILE time (defense-in-depth). It does NOT sanitize arbitrary
    input: a hand-rolled non-builder spec with an image mark keeps its external href in the output
    (a general post-render output audit is the M1.6c render() gate's job); here the caller is always
    the builder. Text is laid out as DejaVu Sans -- the vendored family named in the spec config,
    its directory registered at import so the family RESOLVES regardless of the host's system fonts
    (vendoring guarantees availability; it does not prove vl-convert chose our copy over a
    same-named system font -- same-machine metrics are identical either way, and cross-machine SVG
    identity is not claimed). SVG bytes are reproducible across calls within this pinned build."""
    return vl_convert.vegalite_to_svg(vega_lite_json, vl_version=_VL_VERSION, allowed_base_urls=[])
