# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Evidence-bound VPlot -> Vega-Lite preparation, rendering, and certification.

Turns an untrusted VPlotSpec plus the verifier's recomputed plotted table into a Vega-Lite
v5 spec dict that inlines ONLY that table. Two trust mechanisms, kept distinct: (1) the
builder copies NO model-supplied Vega-Lite key, so no dangerous data/JS/URL sink can appear
(positive allowlist by construction); (2) it EMITS its own narrow fixed safe set to pin
determinism -- every channel sort:null, quantitative stack:null, line-mark order:null, bar
scale.zero, and an explicit discrete-color domain from recomputed non-null values -- defeating
Vega-Lite's implicit field-sort / line-vertex-sort / legend-domain sort / stacking so the
displayed marks are intended to match the recomputed row order (M1.6b compile-confirms the effect).

Axis titles are manifest-sourced via checks.unit_source lineage (count-derived -> the fixed
"count", as a count is dimensionless and its output name is model-proposed). _dumps is the
SOLE serializer: a Decimal cell becomes a RAW fixed-point JSON number token at its COLUMN
scale (build re-quantizes each data cell via _scaled_cell, so the inlined number equals the
hashed table's token), -0 folded, so the same table yields byte-identical JSON; a Python float
is rejected at the boundary. The string _dumps returns is the authoritative artifact M1.6b/c
consume -- stdlib json.dumps is never applied to builder output (it cannot serialize the
Decimals build_vega_lite keeps in data.values).

The orchestration boundary is deliberately two-stage. ``prepare_render`` consumes a decoded
spec plus core-check-passed ``RecomputedEvidence`` (never a live data directory), binds the pair,
builds/serializes once, derives formal facts from that exact builder object, and runs the bounded
SMT gate. Only a complete passing report carries ``PreparedArtifact`` forward. ``render_prepared``
mints and byte-admits the VCert before native work, renders that exact artifact, and admits the
SVG/optional HTML before returning either. The ``render`` convenience entry is their single-read
verify -> prepare/formal-check -> render composition.
"""

import functools
import hashlib
import html
import importlib.metadata
import importlib.resources
import json
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal, cast

import msgspec
import vl_convert

from verifier import __version__, canon, checks, formal, ingest
from verifier.errors import VerificationError
from verifier.eval import active_sort
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.schema import Aggregate, Channel, Filter, SortOrder, VPlotSpec

# $schema is the Vega-Lite v5 MAJOR-version URI constant -- a fixed string, DECOUPLED from the
# exact bundled minor (vl_version is M1.6b's determinism lever), so this half needs no dep.
_VEGA_LITE_SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"
# The family name of the vendored font (the file + register_font_directory are below). Naming it
# in every spec's config REQUESTS this family for all text; the registered vendored file guarantees
# it RESOLVES (availability), and on a host without a same-named system font these exact bytes are
# laid out -- byte SELECTION over an existing system DejaVu is not proven (see render_svg).
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
    cell validation MATCHES hash_table's (no silent mis-serialization). build_vega_lite is then
    STRICTER -- it also rejects duplicate column names hash_table tolerates, so the builder accepts
    hash_table's inputs MINUS dup-name tables, never a superset. A
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


def _discrete_domain(values: list[dict[str, canon.Cell]], field: str) -> list[canon.Cell]:
    """Distinct non-null values in first plotted occurrence order.

    The evaluator's canonical total order makes first occurrence deterministic. Cells are
    immutable/hashable, so one set gives linear deduplication without reordering the legend.
    """
    seen: set[Decimal | str] = set()
    domain: list[canon.Cell] = []
    for row in values:
        value = row[field]
        if value is not None and value not in seen:
            seen.add(value)
            domain.append(value)
    return domain


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
        color = _channel(spec.encoding.color, aggregates, manifest)
        if spec.encoding.color.kind in ("nominal", "ordinal"):
            # An explicit builder-owned domain closes the exact legend artifact that the formal
            # gate checks. Empty/all-null domains intentionally emit [] (valid Vega-Lite v5).
            color["scale"] = {
                "domain": _discrete_domain(values, spec.encoding.color.field),
            }
        encoding["color"] = color
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


@dataclass(frozen=True, slots=True)
class PreparedArtifact:
    """Internal formal-passed build carrying exact Vega-Lite bytes into native rendering."""

    spec: VPlotSpec = field(repr=False)
    evidence: checks.RecomputedEvidence = field(repr=False)
    results: tuple[checks.CheckResult, ...] = field(repr=False)
    vega_lite: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class PreparationRun:
    """Final report + bounded solver trace + artifact only when every result passed."""

    report: checks.VerificationReport
    formal_trace: tuple[formal.FormalTrace, ...]
    prepared: PreparedArtifact | None = field(repr=False)


def _row_order_facts(
    spec: VPlotSpec,
    table: canon.Table,
    built: dict[str, Any],
) -> formal.RowOrderFacts:
    """Rank the exact built rows under the declared active sort + canonical tail."""
    active = active_sort(spec.transform)
    keys: list[tuple[str, SortOrder]] = (
        [(key.field, key.order) for key in active.by] if active is not None else []
    )
    used = {field for field, _direction in keys}
    keys.extend((column.name, "ascending") for column in table.columns if column.name not in used)

    columns = {column.name: column for column in table.columns}
    data = cast("dict[str, Any]", built["data"])
    rows = cast("list[dict[str, canon.Cell]]", data["values"])
    text_ranks: dict[str, dict[str, int]] = {}
    for field_name, _direction in keys:
        if not isinstance(columns[field_name], canon.NumericColumn):
            values = sorted(
                {cast("str", row[field_name]) for row in rows if row[field_name] is not None}
            )
            text_ranks[field_name] = {value: rank for rank, value in enumerate(values)}

    ranked_rows: list[tuple[formal.RankedCell, ...]] = []
    for row in rows:
        ranked_row: list[formal.RankedCell] = []
        for field_name, _direction in keys:
            value = row[field_name]
            if value is None:
                ranked_row.append(formal.RankedCell(is_null=True, rank=0))
            elif isinstance(columns[field_name], canon.NumericColumn):
                ranked_row.append(
                    formal.RankedCell(is_null=False, rank=Fraction(cast("Decimal", value)))
                )
            else:
                ranked_row.append(
                    formal.RankedCell(
                        is_null=False, rank=text_ranks[field_name][cast("str", value)]
                    )
                )
        ranked_rows.append(tuple(ranked_row))
    return formal.RowOrderFacts(
        rows=tuple(ranked_rows),
        directions=tuple(direction for _field, direction in keys),
    )


def _zero_enabled(channel: dict[str, Any]) -> bool:
    scale = cast("dict[str, Any]", channel.get("scale", {}))
    return scale.get("zero") is True


def _bar_zero_facts(built: dict[str, Any]) -> formal.BarZeroFacts | None:
    """Read applicable mark/channel/zero facts from the exact built object."""
    encoding = cast("dict[str, Any]", built["encoding"])
    x = cast("dict[str, Any]", encoding["x"])
    y = cast("dict[str, Any]", encoding["y"])
    x_quantitative = x["type"] == "quantitative"
    y_quantitative = y["type"] == "quantitative"
    if built["mark"] != "bar" or not (x_quantitative or y_quantitative):
        return None
    return formal.BarZeroFacts(
        is_bar=True,
        x_quantitative=x_quantitative,
        x_zero=_zero_enabled(x),
        y_quantitative=y_quantitative,
        y_zero=_zero_enabled(y),
    )


def _category_label(value: Decimal | str) -> str:
    return format(value, "f") if isinstance(value, Decimal) else value


def _legend_domain_facts(
    table: canon.Table,
    built: dict[str, Any],
) -> formal.LegendDomainFacts | None:
    """Read discrete color occurrences + explicit domain from the exact built object."""
    encoding = cast("dict[str, Any]", built["encoding"])
    color_value = encoding.get("color")
    if color_value is None:
        return None
    color = cast("dict[str, Any]", color_value)
    if color["type"] not in ("nominal", "ordinal"):
        return None

    field_name = cast("str", color["field"])
    data = cast("dict[str, Any]", built["data"])
    rows = cast("list[dict[str, canon.Cell]]", data["values"])
    plotted = [row[field_name] for row in rows if row[field_name] is not None]
    scale = cast("dict[str, Any]", color["scale"])
    domain = cast("list[Decimal | str]", scale["domain"])
    column = {item.name: item for item in table.columns}[field_name]
    if isinstance(column, canon.NumericColumn):
        ordered: list[Decimal | str] = sorted(
            set(cast("list[Decimal]", plotted)) | set(cast("list[Decimal]", domain))
        )
    else:
        ordered = sorted(set(cast("list[str]", plotted)) | set(cast("list[str]", domain)))
    ranks = {value: rank for rank, value in enumerate(ordered)}

    def category(value: Decimal | str) -> formal.LegendCategory:
        return formal.LegendCategory(rank=ranks[value], label=_category_label(value))

    return formal.LegendDomainFacts(
        plotted=tuple(category(cast("Decimal | str", value)) for value in plotted),
        domain=tuple(category(value) for value in domain),
    )


def _formal_facts(
    spec: VPlotSpec,
    table: canon.Table,
    built: dict[str, Any],
) -> formal.FormalFacts:
    """Typed facts projected from the exact builder object later handed to ``_dumps``."""
    return formal.FormalFacts(
        row_order=_row_order_facts(spec, table, built),
        bar_zero=_bar_zero_facts(built),
        legend_domain=_legend_domain_facts(table, built),
    )


def _enforce_byte_limit(payload: bytes, limit: int, *, artifact: str, check: str) -> None:
    """Admit an exact byte artifact at an inclusive ceiling or fail under ``check``."""
    size = len(payload)
    if size > limit:
        message = f"{artifact} has {size} bytes; limit is {limit}"
        raise VerificationError(message, check=check)


def prepare_render(
    spec: VPlotSpec,
    evidence: checks.RecomputedEvidence,
    *,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> PreparationRun:
    """Build and formally check one authoritative artifact from recomputation evidence.

    ``spec`` is paired to the evidence by its canonical hash before either the row gate or
    builder runs; a mismatch is a caller invariant violation, not a model-driven verification
    outcome. The row ceiling runs before materializing builder rows. Serialization then happens
    exactly once from the same dict used to derive formal facts. UTF-8 bytes are admitted before
    solver work. A failed/uncertain formal result returns no ``PreparedArtifact``, making the
    native-render handoff represent only a complete passing report.
    """
    spec_hash = canon.hash_spec(spec)
    if spec_hash != evidence.spec_hash:
        message = f"spec hash {spec_hash} does not match evidence {evidence.spec_hash}"
        raise ValueError(message)

    row_count = len(evidence.plotted_table.rows)
    if row_count > limits.max_render_rows:
        message = f"plotted table has {row_count} render rows; limit is {limits.max_render_rows}"
        raise VerificationError(message, check="resource.render_rows")

    built = build_vega_lite(spec, evidence.plotted_table, evidence.manifest)
    vega_lite = _dumps(built).encode("utf-8")
    _enforce_byte_limit(
        vega_lite,
        limits.max_vega_bytes,
        artifact="Vega-Lite JSON",
        check="resource.vega_bytes",
    )
    formal_run = formal.verify_formal(
        _formal_facts(spec, evidence.plotted_table, built),
        limits=limits,
    )
    report = checks.VerificationReport(results=(*evidence.results, *formal_run.results))
    prepared = (
        PreparedArtifact(
            spec=spec,
            evidence=evidence,
            results=report.results,
            vega_lite=vega_lite,
        )
        if report.passed
        else None
    )
    return PreparationRun(
        report=report,
        formal_trace=formal_run.trace,
        prepared=prepared,
    )


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
    identity is not claimed). SVG bytes are reproducible across calls within this pinned build.

    KNOWN TCB quantization (not merely unproven fidelity): the embedded JS runtime parses the
    inlined JSON numbers as IEEE-754 doubles, so a value beyond exact-double range (integer part
    past 2**53, or more than ~16 significant digits -- DECIMAL(38) admits both) can DISPLAY
    rounded; the emitted Vega-Lite JSON and the certified plotted-table hash carry it exactly
    (POC_SCOPE TCB line; a Vega-safe-numeric render gate is a candidate M2+ hardening)."""
    return vl_convert.vegalite_to_svg(vega_lite_json, vl_version=_VL_VERSION, allowed_base_urls=[])


# --- offline HTML view (M1.6d: OPTIONAL self-contained view, OFF the cert hash chain) ---------
# A second, non-canonical rendering of the SAME builder JSON the SVG and cert consume: a fully
# self-contained page a browser renders CLIENT-SIDE from the inlined vega runtime. The emitted
# builder specs carry no params / selection / tooltip, so it is the SAME chart as the SVG drawn by
# JS rather than pre-rasterized -- not a richer pan/zoom/hover view. It is NEVER hashed into the
# VCert -- the plotted-table hash stays the one canonical artifact, and this HTML is trusted output
# like the SVG. Two levers keep it self-contained and menu-free:
#   * javascript_bundle inlines vega + vega-lite + vega-embed (and their deps) into ONE <script>
#     with no <script src> / CDN reference. The vega runtime still carries dormant data/image URL
#     code paths, but the builder allowlist emits no external data URL (compile-time
#     allowed_base_urls=[]) and no image mark, so a builder-produced page triggers no fetch; the
#     tests are a static regression guard over the pinned bundle (no raw </script> breaking its own
#     wrapper, no quoted absolute http(s) src/href), not a runtime/browser proof.
#   * the built spec is embedded as inert <script type="application/json"> DATA -- JSON.parse'd at
#     runtime, never executed -- with EVERY "<" rewritten to its JSON unicode escape (U+003C), so
#     no data byte can open script-data markup (</script>, <!--, <script>) that would corrupt the
#     page; the escape is lossless through JSON.parse. vegaEmbed runs with actions:false, so NO
#     editor/actions menu (hence no "open in Vega editor" external link) is shown. renderer:"svg"
#     mirrors render_svg.
# vl-convert's own vegalite_to_html is deliberately NOT used: it re-serializes the spec (which
# undoes any pre-escape) and always ships the actions menu with no lever to disable it.
_EMBED_SNIPPET = "window.vegaEmbed = vegaEmbed;"

# A trusted-template height self-reporter appended as the page's LAST <script> (render_html). Open
# WebUI embeds this page (M4) in a sandboxed iframe (allow-scripts, no allow-same-origin) with no
# intrinsic height -- absent a self-report the frame collapses and the chart renders tiny (Open
# WebUI's same-origin auto-measure throws on a no-same-origin child -> self-report is mandatory). So
# the page posts its rendered CONTENT height; Open WebUI sizes the frame on the
# {type:"iframe:height",height} message (its listener source-matches the frame + applies height
# VERBATIM -> the value must be right; memory "## M4" pins the verified contract). Height =
# ceil(documentElement.getBoundingClientRect().height) = the viewport-INDEPENDENT content box;
# scrollHeight is WRONG (floors at the frame's viewport -> a chart shorter than its frame reports
# inflated + can never shrink; verified headless). Fires on load AND every ResizeObserver tick (the
# async vega render grows the DOM only after load). Fixed self-contained JS reading only its OWN
# document: no external ref, no model byte -- off the cert hash chain like the rest of this view.
_HEIGHT_REPORTER = (
    "function vplotReportHeight(){parent.postMessage("
    '{type:"iframe:height",'
    "height:Math.ceil(document.documentElement.getBoundingClientRect().height)},"
    '"*");}'
    'window.addEventListener("load",vplotReportHeight);'
    "new ResizeObserver(vplotReportHeight).observe(document.documentElement);"
)


@functools.cache
def _embed_bundle() -> str:
    """The offline vega / vega-lite / vega-embed JavaScript bundle exposing vegaEmbed as a window
    global. javascript_bundle injects the library names into the snippet's scope; the snippet
    references vegaEmbed, so it (and its deps) are bundled with no <script src> / CDN reference.
    Byte-identical across in-process rebuilds for the lockfile-pinned vl-convert build (fixed
    vl_version). The vega runtime carries dormant data/image URL code paths, but a builder-produced
    spec (no external data URL, no image mark) triggers no fetch. Cached: it is identical for every
    chart and costs ~0.7s / ~0.9MB to build, so it is built at most once per process."""
    return vl_convert.javascript_bundle(_EMBED_SNIPPET, vl_version=_VL_VERSION)


def render_html(vega_lite_json: str) -> str:
    """A self-contained, fully offline HTML view of a BUILDER-PRODUCED Vega-Lite JSON string -- the
    same string render_svg consumes, drawn CLIENT-SIDE by the inlined vega runtime (the same chart
    as the SVG, not a richer interactive view: the builder emits no params / selection / tooltip).
    No <script src> / CDN reference and no editor/actions menu (actions:false). A trailing
    trusted-template <script> (_HEIGHT_REPORTER) self-reports its content height to a parent
    frame (postMessage on load + ResizeObserver), so an M4 sandboxed-iframe embed sizes to content
    instead of rendering tiny -- fixed self-contained JS adding no external ref. OFF the cert hash
    chain: a convenience view, never hashed into the VCert. Self-containment also rests on embedding
    the spec as inert application/json DATA (JSON.parse'd, never executed) with EVERY "<" rewritten
    to its JSON unicode escape (U+003C), so no data byte can open script-data markup (</script>,
    <!--, <script>) and corrupt the page; the escape is lossless through JSON.parse. Like
    render_svg it trusts its builder input rather than sanitizing an arbitrary hand-rolled
    spec; in the pipeline every string byte is either a trusted-source/manifest value or a
    schema-constrained field identifier (model-selected field + aggregate-output names, bound by
    the FieldName regex to [A-Za-z_][A-Za-z0-9_]* — no markup bytes), and the "<"-escape above
    holds regardless of provenance (untrusted-input hardening is M2+)."""
    safe_spec = vega_lite_json.replace("<", "\\u003c")
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<title>Verified Plot</title>\n"
        "</head>\n"
        "<body>\n"
        '<div id="vplot-chart"></div>\n'
        f'<script type="application/json" id="vplot-spec">{safe_spec}</script>\n'
        f"<script>{_embed_bundle()}</script>\n"
        '<script>vegaEmbed("#vplot-chart", '
        'JSON.parse(document.getElementById("vplot-spec").textContent), '
        '{actions: false, renderer: "svg"}).catch(console.error);</script>\n'
        f"<script>{_HEIGHT_REPORTER}</script>\n"
        "</body>\n"
        "</html>\n"
    )


# --- provenance certificate (M5.2e: VCert v0.2 method + artifact binding) ----
# Core render still returns a NON-REPLAYABLE unsigned VCert (service signing + replay follow in
# M5.3c-M5.5; M5.3a supplies only the isolated attestation primitives). It
# stamps five hashes: dataset/spec/plotted-table/manifest plus the exact formal-passed Vega-Lite
# bytes. Every passing result carries its verification method. The TCB identifies this verifier,
# Z3, canon/interpreter dependencies, and the native display stack. SVG bytes remain outside the
# certificate: the TCB disclosure narrows provenance but proves neither SVG byte identity nor
# pixels (cross-machine SVG identity remains unclaimed).
_VCERT_VERSION: Literal["vcert-0.2"] = "vcert-0.2"

# The vendored font ASSET's content hash, computed once from the bytes we ship + register (ties
# the cert's font provenance to the real asset, not a hardcoded constant). It identifies the
# REQUESTED/available typeface; vl-convert is not proven to lay out with THIS copy over a
# same-named system font (render_svg documents the same scope) -- hence vendored_font_sha256.
_FONT_SHA256 = "sha256:" + hashlib.sha256((_FONT_DIR / "DejaVuSans.ttf").read_bytes()).hexdigest()


class Tcb(msgspec.Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    """The verifier/formal/display TCB stamped into VCert.

    ``verifier_version`` identifies the package implementing the checks; ``z3_version`` the
    solver behind ``z3_smt`` results. The remaining fields identify canonicalization and the
    native display stack trusted to render verified data faithfully, NOT proven to do so. SVG is
    not hashed and cross-machine byte identity is unclaimed. ``vendored_font_sha256`` identifies
    the registered font asset, not proof that vl-convert selected it over a same-named system
    font (``render_svg`` documents the same scope).
    """

    verifier_version: str
    z3_version: str
    canon_version: str
    python: str
    msgspec: str
    unidata: str
    vl_convert_python: str
    vl_version: str
    font_family: str
    vendored_font_sha256: str


class DisclosedFilter(msgspec.Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    """One applied filter op, disclosed in the cert. `value` is model-controlled (arbitrary
    text within FilterValue bounds) -> badge_html HTML-escapes it."""

    field: str
    cmp: str
    value: int | str


class DisclosedSort(msgspec.Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    """One applied sort key, disclosed in the cert (flattened across all sort ops in order)."""

    field: str
    order: str


class CertifiedCheck(msgspec.Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    """One passing final result recorded with the method that established it."""

    id: str
    method: checks.CheckMethod
    status: Literal["pass"]


class VCert(msgspec.Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    """A VPlot v0.1 provenance certificate: five bound artifact hashes, method-bearing passing
    checks, disclosed applied filters/sorts, and the verifier/formal/display TCB. Unsigned and
    non-replayable until later M5 units. Produced by render; attestation verification decodes an
    external copy only after its exact bytes + application type authenticate under a trusted key."""

    version: Literal["vcert-0.2"]
    dataset_hash: str
    spec_hash: str
    plotted_table_hash: str
    manifest_hash: str
    vega_lite_hash: str
    checks: tuple[CertifiedCheck, ...]
    filters: tuple[DisclosedFilter, ...]
    sorts: tuple[DisclosedSort, ...]
    tcb: Tcb


# canon's determinism family (order="deterministic"): definition-order struct fields, sorted
# dict/set keys (the cert has neither), no Unicode normalization. The VCert holds only str /
# tuple / nested-struct fields (filter values are int | str, never float), so the encode is
# total and deterministic in-process for the pinned build.
_CERT_ENCODER = msgspec.json.Encoder(order="deterministic")


def vcert_bytes(cert: VCert) -> bytes:
    """The VCert's deterministic canonical bytes (_CERT_ENCODER, canon's family). The public
    seam the service content-addresses: it hashes these bytes to the plot_id and serves them
    verbatim as the certificate artifact. The same VCert yields byte-identical output."""
    return _CERT_ENCODER.encode(cert)


def hash_vega_lite(vega_lite: bytes) -> str:
    """SHA-256 over the exact serialized Vega-Lite artifact, with the standard digest prefix."""
    return "sha256:" + hashlib.sha256(vega_lite).hexdigest()


class RenderResult(msgspec.Struct, frozen=True, kw_only=True):
    """A verified render carrying the authoritative Vega-Lite bytes, SVG, and VCert.

    ``html`` is the optional fully offline view requested by ``render(include_html=True)``;
    it remains off the certificate hash chain.
    """

    vega_lite: bytes
    svg: str
    certificate: VCert
    html: str | None = None


def _tcb() -> Tcb:
    """The verifier/formal/render TCB disclosed for one certificate (see ``Tcb``)."""
    versions = canon.runtime_versions()
    return Tcb(
        verifier_version=__version__,
        z3_version=formal.solver_version(),
        canon_version=versions.canon_version,
        python=versions.python,
        msgspec=versions.msgspec,
        unidata=versions.unidata,
        vl_convert_python=importlib.metadata.version("vl-convert-python"),
        vl_version=_VL_VERSION,
        font_family=_FONT_FAMILY,
        vendored_font_sha256=_FONT_SHA256,
    )


def _build_certificate(prepared: PreparedArtifact) -> VCert:
    """Mint VCert from one immutable formal-passed artifact, without rebuilding any input.

    Its exact Vega bytes are hashed directly; passing IDs/methods preserve final-report order.
    Filters disclose every filter and sorts only the active sort. Model-controlled filter values
    are escaped later by ``badge_html``.
    """
    spec = prepared.spec
    evidence = prepared.evidence
    certified_checks = tuple(
        CertifiedCheck(id=result.check, method=result.method, status="pass")
        for result in prepared.results
        if result.status == "pass"
    )
    filters = tuple(
        DisclosedFilter(field=t.field, cmp=t.cmp, value=t.value)
        for t in spec.transform
        if isinstance(t, Filter)
    )
    active = active_sort(spec.transform)
    sorts = (
        tuple(DisclosedSort(field=key.field, order=key.order) for key in active.by)
        if active is not None
        else ()
    )
    return VCert(
        version=_VCERT_VERSION,
        dataset_hash=evidence.dataset_hash,
        spec_hash=evidence.spec_hash,
        plotted_table_hash=evidence.plotted_table_hash,
        manifest_hash=evidence.manifest_hash,
        vega_lite_hash=hash_vega_lite(prepared.vega_lite),
        checks=certified_checks,
        filters=filters,
        sorts=sorts,
        tcb=_tcb(),
    )


def render_prepared(
    prepared: PreparedArtifact,
    *,
    include_html: bool = False,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> RenderResult:
    """Render one prepared artifact and return only byte-admitted outputs.

    The VCert is minted from ``prepared.evidence`` and admitted before the first native call.
    SVG and optional HTML are measured as UTF-8 immediately after construction; an oversized
    artifact raises its stable ``resource.*`` failure and is never returned. Native Vega/Vega-Lite
    and browser pixels remain trusted display components, not verified proof targets.
    """
    certificate = _build_certificate(prepared)
    _enforce_byte_limit(
        vcert_bytes(certificate),
        limits.max_attestation_bytes,
        artifact="VCert payload",
        check="resource.attestation_bytes",
    )

    vega_lite_json_text = prepared.vega_lite.decode("utf-8")
    svg = render_svg(vega_lite_json_text)
    _enforce_byte_limit(
        svg.encode("utf-8"),
        limits.max_svg_bytes,
        artifact="SVG",
        check="resource.svg_bytes",
    )

    offline_html = render_html(vega_lite_json_text) if include_html else None
    if offline_html is not None:
        _enforce_byte_limit(
            offline_html.encode("utf-8"),
            limits.max_html_bytes,
            artifact="HTML",
            check="resource.html_bytes",
        )
    return RenderResult(
        vega_lite=prepared.vega_lite,
        svg=svg,
        certificate=certificate,
        html=offline_html,
    )


def _literal(value: int | str) -> str:
    """A disclosed filter literal in its unambiguous DISPLAY form: an int bare, a string
    JSON-quoted with ASCII-only escaping (json.dumps default). Quoting exposes leading/trailing
    whitespace and keeps int 5 distinct from string "5"; every control / format / bidi /
    invisible code point (NUL, newline, TAB, U+2028, a U+202E direction override that would
    visually reorder the badge, ...) renders as its visible \\uXXXX / \\n escape -- so two
    distinct literals can never display identically and the disclosure stays AUDITABLE, not
    merely inert. Display only: the VCert struct carries the raw value."""
    if isinstance(value, int):
        return str(value)
    return json.dumps(value)


def badge_html(cert: VCert) -> str:
    """Render a VCert as a static, self-contained HTML fragment for human display. Every
    model-controlled string (the disclosed filter values -- arbitrary text) is rendered via
    _literal (a visible, injective ASCII form -- control/format/bidi chars appear as \\uXXXX
    escapes, so the disclosure is auditable) and then, like every other field, HTML-escaped via
    html.escape(quote=True); the fragment has NO <script>, foreignObject, or other raw-HTML/JS
    sink, so no filter-value byte is ever live markup. All other fields (constrained field
    names, enum cmp/order, sha256 hashes, versions) are escaped uniformly. Pure +
    deterministic. Non-replayable; service signing follows in M5.3c."""

    def esc(value: object) -> str:
        return html.escape(str(value), quote=True)

    checks_items = "".join(
        f"<li>{esc(item.id)} - {esc(item.method)} - {esc(item.status)}</li>" for item in cert.checks
    )
    filter_items = "".join(
        f"<li>{esc(f.field)} {esc(f.cmp)} {esc(_literal(f.value))}</li>" for f in cert.filters
    )
    sort_items = "".join(f"<li>{esc(s.field)} {esc(s.order)}</li>" for s in cert.sorts)
    tcb = cert.tcb
    return (
        '<div class="vcert">'
        f"<h2>Verified Plot Certificate ({esc(cert.version)})</h2>"
        '<dl class="vcert-hashes">'
        f"<dt>dataset</dt><dd>{esc(cert.dataset_hash)}</dd>"
        f"<dt>spec</dt><dd>{esc(cert.spec_hash)}</dd>"
        f"<dt>plotted table</dt><dd>{esc(cert.plotted_table_hash)}</dd>"
        f"<dt>manifest</dt><dd>{esc(cert.manifest_hash)}</dd>"
        f"<dt>Vega-Lite</dt><dd>{esc(cert.vega_lite_hash)}</dd>"
        "</dl>"
        f"<h3>Checks passed</h3><ul>{checks_items}</ul>"
        f"<h3>Applied filters</h3><ul>{filter_items}</ul>"
        f"<h3>Applied sorts</h3><ul>{sort_items}</ul>"
        '<dl class="vcert-tcb">'
        f"<dt>verifier</dt><dd>{esc(tcb.verifier_version)}</dd>"
        f"<dt>Z3</dt><dd>{esc(tcb.z3_version)}</dd>"
        f"<dt>canon</dt><dd>{esc(tcb.canon_version)}</dd>"
        f"<dt>python</dt><dd>{esc(tcb.python)}</dd>"
        f"<dt>msgspec</dt><dd>{esc(tcb.msgspec)}</dd>"
        f"<dt>unidata</dt><dd>{esc(tcb.unidata)}</dd>"
        f"<dt>vl-convert-python</dt><dd>{esc(tcb.vl_convert_python)}</dd>"
        f"<dt>vega-lite</dt><dd>{esc(tcb.vl_version)}</dd>"
        f"<dt>font</dt><dd>{esc(tcb.font_family)} ({esc(tcb.vendored_font_sha256)})</dd>"
        "</dl>"
        "</div>"
    )


def render(
    spec: VPlotSpec,
    manifest_bytes: bytes,
    *,
    data_dir: Path,
    include_html: bool = False,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> RenderResult | None:
    """Convenience composition: verify once -> prepare captured evidence -> render prepared.

    A failed core verification returns ``None`` before preparation; a failed/uncertain formal
    check returns ``None`` before native work. Resource-policy failures raise a tagged
    ``VerificationError`` for orchestration layers to surface as structured outcomes. The source
    is read only by ``verify_run``; every later stage consumes its immutable evidence, so
    mutation/deletion of the live CSV cannot rebind an admitted render. Optional HTML remains off
    the cert hash chain and cannot change the SVG, VCert, or Vega-Lite bytes.
    """
    verification = checks.verify_run(spec, manifest_bytes, data_dir=data_dir, limits=limits)
    if not verification.report.passed:
        return None
    # A passing report implies every checks gate passed, so evidence is populated; cast is the
    # coverage-clean narrowing (an assert's never-taken branch fails the 100% gate).
    evidence = cast("checks.RecomputedEvidence", verification.evidence)
    preparation = prepare_render(spec, evidence, limits=limits)
    if not preparation.report.passed:
        return None
    prepared = cast("PreparedArtifact", preparation.prepared)
    return render_prepared(prepared, include_html=include_html, limits=limits)
