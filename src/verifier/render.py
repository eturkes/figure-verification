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
