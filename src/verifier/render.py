# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Evidence-bound VPlot -> Vega-Lite preparation, rendering, and certification.

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

The orchestration boundary is deliberately two-stage. ``prepare_render`` consumes a decoded
spec plus check-passed ``RecomputedEvidence`` (never a live data directory), binds the pair,
enforces the render-row ceiling, and carries the one authoritative serialized Vega-Lite byte
string forward. ``render_prepared`` mints and byte-admits the VCert before native work, renders
that exact prepared artifact, and admits the SVG/optional HTML before returning either. The
``render`` convenience entry is their single-read verify -> prepare -> render composition.
"""

import functools
import hashlib
import html
import importlib.metadata
import importlib.resources
import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import msgspec
import vl_convert

from verifier import canon, checks, ingest
from verifier.errors import VerificationError
from verifier.eval import active_sort
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.schema import Aggregate, Channel, Filter, VPlotSpec

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


@dataclass(frozen=True, slots=True)
class PreparedArtifact:
    """Internal check-passed build carrying the exact Vega-Lite bytes into native rendering."""

    spec: VPlotSpec = field(repr=False)
    evidence: checks.RecomputedEvidence = field(repr=False)
    vega_lite: bytes = field(repr=False)


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
) -> PreparedArtifact:
    """Build one authoritative Vega-Lite artifact from captured verification evidence.

    ``spec`` is paired to the evidence by its canonical hash before either the row gate or
    builder runs; a mismatch is a caller invariant violation, not a model-driven verification
    outcome. The row ceiling runs before materializing builder rows. Serialization then happens
    exactly once, and the UTF-8 bytes are admitted before any native renderer can receive them.
    """
    spec_hash = canon.hash_spec(spec)
    if spec_hash != evidence.spec_hash:
        message = f"spec hash {spec_hash} does not match evidence {evidence.spec_hash}"
        raise ValueError(message)

    row_count = len(evidence.plotted_table.rows)
    if row_count > limits.max_render_rows:
        message = f"plotted table has {row_count} render rows; limit is {limits.max_render_rows}"
        raise VerificationError(message, check="resource.render_rows")

    vega_lite = vega_lite_json(spec, evidence.plotted_table, evidence.manifest).encode("utf-8")
    _enforce_byte_limit(
        vega_lite,
        limits.max_vega_bytes,
        artifact="Vega-Lite JSON",
        check="resource.vega_bytes",
    )
    return PreparedArtifact(spec=spec, evidence=evidence, vega_lite=vega_lite)


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


# --- provenance certificate (M1.6c: VCert v0.1 badge + render() gate) --------
# VCert v0.1 is NON-REPLAYABLE (no nonce/signature; replay + signing are M5). It stamps the
# four canonical hashes (dataset/spec/plotted-table/manifest), the passed-check names INCLUDING
# the two the renderer enforces by construction, the disclosed applied filter/sort literals
# (model-controlled -> badge_html escapes them), and the TCB it TRUSTS to render the verified
# data faithfully (canon + interpreter versions, the vl-convert build, the pinned vl_version,
# the vendored font family + sha256). The SVG bytes are never hashed into the cert; the TCB
# DISCLOSES the toolchain for provenance, it does not prove byte-identity (the build + vendored
# font narrow the toolchain beyond vl_version alone, cross-machine SVG identity is unclaimed).
_VCERT_VERSION = "vcert-0.1"

# The two checks the RENDERER enforces by construction (examples/index.json marks them
# enforced_by_construction, NOT computed in checks.py): the builder sets a bar's quantitative-
# axis scale.zero, and derives the color legend domain from the recomputed data (channel
# sort:null). Disclosed in the cert only when the spec's mark/encoding makes them applicable,
# so the cert records the full verified surface without claiming an inapplicable guarantee.
_RENDERER_BAR_ZERO = "scale.bar_quantitative_axis_zero"
_RENDERER_LEGEND_DOMAIN = "encoding.legend_domain_matches_data"

# The vendored font ASSET's content hash, computed once from the bytes we ship + register (ties
# the cert's font provenance to the real asset, not a hardcoded constant). It identifies the
# REQUESTED/available typeface; vl-convert is not proven to lay out with THIS copy over a
# same-named system font (render_svg documents the same scope) -- hence vendored_font_sha256.
_FONT_SHA256 = "sha256:" + hashlib.sha256((_FONT_DIR / "DejaVuSans.ttf").read_bytes()).hexdigest()


class Tcb(msgspec.Struct, frozen=True, kw_only=True):
    """The trusted computing base disclosed for the rendered SVG's provenance, stamped into the
    VCert. Trusted to render the verified data faithfully, NOT proven to (the SVG is never hashed
    into the cert, and cross-machine byte-identity is unclaimed). vl_convert_python is the
    installed distribution version; vl_version the pinned Vega-Lite; font_family +
    vendored_font_sha256 identify the vendored typeface ASSET we register (vl-convert is not
    proven to select it over a same-named system font -- render_svg documents the same scope)."""

    canon_version: str
    python: str
    msgspec: str
    unidata: str
    vl_convert_python: str
    vl_version: str
    font_family: str
    vendored_font_sha256: str


class DisclosedFilter(msgspec.Struct, frozen=True, kw_only=True):
    """One applied filter op, disclosed in the cert. `value` is model-controlled (arbitrary
    text within FilterValue bounds) -> badge_html HTML-escapes it."""

    field: str
    cmp: str
    value: int | str


class DisclosedSort(msgspec.Struct, frozen=True, kw_only=True):
    """One applied sort key, disclosed in the cert (flattened across all sort ops in order)."""

    field: str
    order: str


class VCert(msgspec.Struct, frozen=True, kw_only=True):
    """A VPlot v0.1 provenance certificate: the four canonical hashes, the passed checks, the
    disclosed applied filters/sorts, and the disclosed render TCB. Non-replayable (M5 adds
    signing/replay). Output record, never decoded from untrusted input."""

    version: str
    dataset_hash: str
    spec_hash: str
    plotted_table_hash: str
    manifest_hash: str
    checks_passed: tuple[str, ...]
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
    """The render TCB disclosed for the SVG's provenance (canon.runtime_versions + the vl-convert
    build + vendored font); trusted to render faithfully, not proven to (see Tcb)."""
    versions = canon.runtime_versions()
    return Tcb(
        canon_version=versions.canon_version,
        python=versions.python,
        msgspec=versions.msgspec,
        unidata=versions.unidata,
        vl_convert_python=importlib.metadata.version("vl-convert-python"),
        vl_version=_VL_VERSION,
        font_family=_FONT_FAMILY,
        vendored_font_sha256=_FONT_SHA256,
    )


def _build_certificate(
    spec: VPlotSpec,
    evidence: checks.RecomputedEvidence,
) -> VCert:
    """Mint a certificate directly from the same evidence used to build the prepared artifact.

    No source, manifest, table, or hash is re-read/re-derived here. ``checks_passed`` is the
    evidence's passing names plus the renderer-enforced checks applicable to ``spec``: bar-zero
    only for a bar with a quantitative positional axis, and legend-domain when color is present.
    Filters disclose every filter; sorts disclose only the active sort. Model-controlled values
    are escaped later by ``badge_html``.
    """
    checks_passed = [r.check for r in evidence.results if r.status == "pass"]
    if spec.mark == "bar" and (
        spec.encoding.x.kind == "quantitative" or spec.encoding.y.kind == "quantitative"
    ):
        checks_passed.append(_RENDERER_BAR_ZERO)
    if spec.encoding.color is not None:
        checks_passed.append(_RENDERER_LEGEND_DOMAIN)
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
        checks_passed=tuple(checks_passed),
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
    certificate = _build_certificate(prepared.spec, prepared.evidence)
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
    deterministic. Non-replayable (signing is M5)."""

    def esc(value: object) -> str:
        return html.escape(str(value), quote=True)

    checks_items = "".join(f"<li>{esc(name)}</li>" for name in cert.checks_passed)
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
        "</dl>"
        f"<h3>Checks passed</h3><ul>{checks_items}</ul>"
        f"<h3>Applied filters</h3><ul>{filter_items}</ul>"
        f"<h3>Applied sorts</h3><ul>{sort_items}</ul>"
        '<dl class="vcert-tcb">'
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

    A failed verification returns ``None`` and performs no preparation/native work. Render policy
    failures raise a tagged ``VerificationError`` for orchestration layers to surface as structured
    outcomes. The source is read only by ``verify_run``; every later stage consumes its immutable
    evidence, so mutation/deletion of the live CSV cannot rebind an admitted render. Optional HTML
    remains off the cert hash chain and cannot change the SVG, VCert, or Vega-Lite bytes.
    """
    run = checks.verify_run(spec, manifest_bytes, data_dir=data_dir, limits=limits)
    if not run.report.passed:
        return None
    # A passing report implies every checks gate passed, so evidence is populated; cast is the
    # coverage-clean narrowing (an assert's never-taken branch fails the 100% gate).
    evidence = cast("checks.RecomputedEvidence", run.evidence)
    prepared = prepare_render(spec, evidence, limits=limits)
    return render_prepared(prepared, include_html=include_html, limits=limits)
