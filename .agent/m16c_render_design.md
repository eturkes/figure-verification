# M1.6c transcription recipe — VCert v0.1 badge + `render()` gate

TRANSCRIBE, do NOT re-derive. This recipe is gate-validated (transcribe → full gate green → reverted,
same as the M1.6a recipe). Read ONLY this doc + `src/verifier/render.py` (to append after `render_svg`) +
`tests/test_render.py` (to append). All external signatures are inlined + symbol-checked below. Reach the
gate early, salvage-continue. Delete this doc at M1 review.

SCOPE = the REQUIRED M1.6c core only: provenance structs + `build_certificate` + `badge_html` + the public
`render()` gate, all appended to the existing `render.py` (M1.6a builder + M1.6b `render_svg` already present).
The optional offline interactive HTML is M1.6d (a separate session with an ISOLATED vl-convert probe) — emit
NO HTML here. `render()` returns `RenderResult(svg, certificate)`; no `html` field.

WHY this is low-overflow: every M1.6c-core surface is pure Python over signatures already in the tree — NO
native-dep probe, and NO external-schema gap like M1.6a's `order:null` (badge HTML is human-display, validated
by no external consumer; `html.escape` is stdlib). So the internal gate (lint/type/100%-branch + the assertions
below) fully proves correctness. Expect a CLEAN pass.

---
## Inlined signatures (already in the tree — do NOT re-read to confirm)

`canon.py`:
- `Versions(canon_version:str, python:str, msgspec:str, unidata:str)` — frozen struct.
- `runtime_versions() -> Versions`.
- `hash_dataset(csv_bytes:bytes)->str` · `hash_table(table:Table)->str` · `hash_spec(spec:VPlotSpec)->str` ·
  `hash_manifest(manifest_bytes:bytes)->str` (all return `"sha256:"+hex`).

`checks.py`:
- `CheckResult(_Base, frozen, kw_only)`: `check:str`, `status:Literal["pass","fail"]`,
  `severity:Literal["blocking"]`, `message:str`.
- `VerificationReport(_Base, frozen, kw_only)`: `results:tuple[CheckResult,...]`,
  `plotted_table:canon.Table|None`; `@property passed -> bool` (`all(r.status=="pass" for r in results)`).
- `verify(spec:VPlotSpec, manifest:ingest.Manifest, *, data_dir:Path) -> VerificationReport`.

`schema.py`: `Filter(field:FieldName, cmp:CmpOp, value:FilterValue)` (`FilterValue = int | str`),
`Sort(by:tuple[SortKey,...])`, `SortKey(field:FieldName, order:SortOrder)`, `VPlotSpec(version, dataset, transform, mark, encoding)`, `Dataset(name, hash)`, `Encoding(x, y, color:Channel|None)`.

`render.py` (existing constants to reuse): `_VL_VERSION="5.21"`, `_FONT_FAMILY="DejaVu Sans"`,
`_FONT_DIR = importlib.resources.files("verifier")/"assets"/"fonts"` (font file `DejaVuSans.ttf`),
`vega_lite_json(spec, table, manifest)->str`, `render_svg(vega_lite_json:str)->str`.

`tests/test_render.py` helpers (reuse): `_good(name)->(spec,manifest)`, `_evaluated(name)->(spec,manifest,table)`,
constants `_DATA`, `_GOOD`, `_SCHEMAS`, `_G01`="g01…json" (bar, no color, sales), `_G07`="g07…json" (line + nominal
color, weather), `_G10`="g10…json" (scatter, no color, weather), `_ALL_GOOD`, `_FONT_SHA256` (= the pinned
`57f73e11f51999432bf7ab22ce55b6f945d5eca1bf824404cfa9ec2e3718c84e`, NO `sha256:` prefix in the test constant).

---
## `render.py` — imports to ADD (let `ruff format`/`ruff check` reorder; expected)

At the top import block add: `import hashlib` · `import html` · `import importlib.metadata`
(SEPARATE from the present `import importlib.resources` — submodules don't auto-import) · `from pathlib import Path`.
Extend the schema import to: `from verifier.schema import Aggregate, Channel, Filter, Sort, VPlotSpec`.

## `render.py` — APPEND after `render_svg` (verbatim)

```python
# --- provenance certificate (M1.6c: VCert v0.1 badge + render() gate) --------
# VCert v0.1 is NON-REPLAYABLE (no nonce/signature; replay + signing are M5). It stamps the
# four canonical hashes (dataset/spec/plotted-table/manifest), the passed-check names INCLUDING
# the two the renderer enforces by construction, the disclosed applied filter/sort literals
# (model-controlled -> badge_html escapes them), and the TCB that determines the SVG bytes
# (canon + interpreter versions PLUS the vl-convert build, the pinned vl_version, and the
# vendored font family + sha256 -- vl_version alone does not pin the SVG; the build + font do).
_VCERT_VERSION = "vcert-0.1"

# The two checks the RENDERER enforces by construction (examples/index.json marks them
# enforced_by_construction, NOT computed in checks.py): the builder sets a bar's quantitative-
# axis scale.zero, and derives the color legend domain from the recomputed data (channel
# sort:null). Disclosed in the cert only when the spec's mark/encoding makes them applicable,
# so the cert records the full verified surface without claiming an inapplicable guarantee.
_RENDERER_BAR_ZERO = "scale.bar_quantitative_axis_zero"
_RENDERER_LEGEND_DOMAIN = "encoding.legend_domain_matches_data"

# The vendored font's content hash, computed once from the actual bytes the SVG is laid out
# with (ties the cert's font provenance to reality, not a hardcoded constant).
_FONT_SHA256 = "sha256:" + hashlib.sha256((_FONT_DIR / "DejaVuSans.ttf").read_bytes()).hexdigest()


class Tcb(msgspec.Struct, frozen=True, kw_only=True):
    """The trusted computing base that determines the rendered SVG bytes, stamped into the
    VCert for provenance. Trusted to render the verified data faithfully, NOT proven to (the
    SVG is never hashed into the cert). vl_convert_python is the installed distribution
    version; vl_version the pinned Vega-Lite; font_family + font_sha256 the vendored typeface."""

    canon_version: str
    python: str
    msgspec: str
    unidata: str
    vl_convert_python: str
    vl_version: str
    font_family: str
    font_sha256: str


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
    disclosed applied filters/sorts, and the SVG-determining TCB. Non-replayable (M5 adds
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


class RenderResult(msgspec.Struct, frozen=True, kw_only=True):
    """A verified render: the self-contained SVG plus its provenance certificate."""

    svg: str
    certificate: VCert


def _tcb() -> Tcb:
    """The current SVG-determining TCB (canon.runtime_versions + the vl-convert build + font)."""
    versions = canon.runtime_versions()
    return Tcb(
        canon_version=versions.canon_version,
        python=versions.python,
        msgspec=versions.msgspec,
        unidata=versions.unidata,
        vl_convert_python=importlib.metadata.version("vl-convert-python"),
        vl_version=_VL_VERSION,
        font_family=_FONT_FAMILY,
        font_sha256=_FONT_SHA256,
    )


def build_certificate(
    spec: VPlotSpec,
    manifest_bytes: bytes,
    table: canon.Table,
    report: checks.VerificationReport,
) -> VCert:
    """The provenance certificate for a verified render. The dataset hash is spec.dataset.hash
    (render runs only when report.passed, so the binding check already proved it equals the
    source bytes' hash -- no CSV re-read); the other three hashes are recomputed here from the
    validated spec, the recomputed table, and the raw manifest bytes. checks_passed is report's
    passing check names PLUS the renderer-enforced checks that APPLY to this spec (bar-zero for
    a bar mark, legend-domain when a color channel is present). Filters/sorts are disclosed from
    the transform pipeline (model-controlled -> escaped at display). `table` is passed narrowed
    (render() casts report.plotted_table once) so this stays total with no coverage-dead assert."""
    checks_passed = [r.check for r in report.results if r.status == "pass"]
    if spec.mark == "bar":
        checks_passed.append(_RENDERER_BAR_ZERO)
    if spec.encoding.color is not None:
        checks_passed.append(_RENDERER_LEGEND_DOMAIN)
    filters = tuple(
        DisclosedFilter(field=t.field, cmp=t.cmp, value=t.value)
        for t in spec.transform
        if isinstance(t, Filter)
    )
    sorts = tuple(
        DisclosedSort(field=key.field, order=key.order)
        for t in spec.transform
        if isinstance(t, Sort)
        for key in t.by
    )
    return VCert(
        version=_VCERT_VERSION,
        dataset_hash=spec.dataset.hash,
        spec_hash=canon.hash_spec(spec),
        plotted_table_hash=canon.hash_table(table),
        manifest_hash=canon.hash_manifest(manifest_bytes),
        checks_passed=tuple(checks_passed),
        filters=filters,
        sorts=sorts,
        tcb=_tcb(),
    )


def badge_html(cert: VCert) -> str:
    """Render a VCert as a static, self-contained HTML fragment for human display. Every
    model-controlled string (the disclosed filter values -- arbitrary text) is HTML-escaped via
    html.escape(quote=True); the fragment has NO <script>, foreignObject, or other raw-HTML/JS
    sink, so a control char or U+2028 in a filter value is inert text, never live markup. All
    other fields (constrained field names, enum cmp/order, sha256 hashes, versions) are escaped
    uniformly. Pure + deterministic. Non-replayable (signing is M5)."""

    def esc(value: object) -> str:
        return html.escape(str(value), quote=True)

    checks_items = "".join(f"<li>{esc(name)}</li>" for name in cert.checks_passed)
    filter_items = "".join(
        f"<li>{esc(f.field)} {esc(f.cmp)} {esc(f.value)}</li>" for f in cert.filters
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
        f"<dt>font</dt><dd>{esc(tcb.font_family)} ({esc(tcb.font_sha256)})</dd>"
        "</dl>"
        "</div>"
    )


def render(
    spec: VPlotSpec,
    manifest: ingest.Manifest,
    manifest_bytes: bytes,
    *,
    data_dir: Path,
) -> RenderResult | None:
    """The single public entry: verify the untrusted spec, and ONLY if every check passes,
    render the self-contained SVG (inlining ONLY the recomputed plotted table) with its
    provenance certificate. Returns None for any failing or blocked spec (no chart for
    unverified data; eval may have been skipped). manifest_bytes is threaded through for the
    manifest hash (a decoded Manifest cannot reproduce its raw bytes)."""
    report = checks.verify(spec, manifest, data_dir=data_dir)
    if not report.passed:
        return None
    # report.passed implies the binding + eval gates passed, so plotted_table is populated;
    # cast is the coverage-clean narrowing (an `assert ... is not None` would leave a
    # never-taken branch that fails the 100% gate -- the M1.5a lesson).
    table = cast(canon.Table, report.plotted_table)
    svg = render_svg(vega_lite_json(spec, table, manifest))
    certificate = build_certificate(spec, manifest_bytes, table, report)
    return RenderResult(svg=svg, certificate=certificate)
```

---
## `tests/test_render.py` — APPEND (verbatim; reuse existing helpers/constants)

Add near the top helpers a manifest-bytes helper (mirrors `_good`'s schema resolution):

```python
def _manifest_bytes(name: str) -> bytes:
    """The raw manifest bytes for a good spec's dataset (for the manifest hash)."""
    spec = decode_spec((_GOOD / name).read_bytes())
    stem = Path(spec.dataset.name).stem
    return (_SCHEMAS / f"{stem}.json").read_bytes()
```

Then append the M1.6c test block:

```python
# --- M1.6c: provenance certificate + render() gate ---------------------------
def _render(name: str) -> render.RenderResult:
    """render() on a good spec, asserted non-None (mypy narrowing + gate)."""
    spec, manifest = _good(name)
    result = render.render(spec, manifest, _manifest_bytes(name), data_dir=_DATA)
    assert result is not None
    return result


def test_render_good_spec_returns_svg_and_cert() -> None:
    result = _render(_G01)
    assert "<svg" in result.svg
    assert isinstance(result.certificate, render.VCert)


def test_render_failing_spec_returns_none() -> None:
    # A hash-mismatch makes the binding gate fail -> verify not passed -> no chart.
    spec, manifest = _good(_G01)
    broken = msgspec.structs.replace(
        spec, dataset=msgspec.structs.replace(spec.dataset, hash="sha256:" + "0" * 64)
    )
    assert render.render(broken, manifest, _manifest_bytes(_G01), data_dir=_DATA) is None


def test_render_gate_skips_svg_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    # Tripwire: render_svg must NOT run for a failing spec (the gate short-circuits before it).
    def _boom(_: str) -> str:
        msg = "render_svg reached for a failing spec"
        raise AssertionError(msg)

    monkeypatch.setattr(render, "render_svg", _boom)
    spec, manifest = _good(_G01)
    broken = msgspec.structs.replace(
        spec, dataset=msgspec.structs.replace(spec.dataset, hash="sha256:" + "0" * 64)
    )
    assert render.render(broken, manifest, _manifest_bytes(_G01), data_dir=_DATA) is None


def test_certificate_hashes_equal_canonical() -> None:
    spec, _, table = _evaluated(_G01)
    cert = _render(_G01).certificate
    assert cert.version == "vcert-0.1"
    assert cert.dataset_hash == spec.dataset.hash
    assert cert.spec_hash == canon.hash_spec(spec)
    assert cert.plotted_table_hash == canon.hash_table(table)
    assert cert.manifest_hash == canon.hash_manifest(_manifest_bytes(_G01))


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
    assert render._RENDERER_BAR_ZERO in _render(_G01).certificate.checks_passed
    assert render._RENDERER_BAR_ZERO not in _render(_G07).certificate.checks_passed
    assert render._RENDERER_BAR_ZERO not in _render(_G10).certificate.checks_passed


def test_certificate_legend_domain_check_present_only_with_color() -> None:
    assert render._RENDERER_LEGEND_DOMAIN in _render(_G07).certificate.checks_passed
    assert render._RENDERER_LEGEND_DOMAIN not in _render(_G01).certificate.checks_passed
    assert render._RENDERER_LEGEND_DOMAIN not in _render(_G10).certificate.checks_passed


def test_certificate_includes_verifier_passes() -> None:
    passed = _render(_G01).certificate.checks_passed
    assert "dataset.hash_matches_source" in passed
    assert "security.no_arbitrary_code" in passed


def test_certificate_tcb_stamps_build() -> None:
    tcb = _render(_G01).certificate.tcb
    assert tcb.canon_version == "canon-0.1"
    assert tcb.vl_version == "5.21"
    assert tcb.font_family == "DejaVu Sans"
    assert tcb.font_sha256 == "sha256:" + _FONT_SHA256
    assert tcb.vl_convert_python  # non-empty installed version string


def test_build_certificate_discloses_filters_and_sorts() -> None:
    # Direct build_certificate over a constructed spec that mixes Filter/Sort/Select ops, so
    # both isinstance arms of each disclosure comprehension fire and the sort-key loop runs.
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
    report = checks.VerificationReport(results=(), plotted_table=table)
    cert = render.build_certificate(spec, b"{}", table, report)
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
    report = checks.VerificationReport(results=(), plotted_table=table)
    cert = render.build_certificate(spec, b"{}", table, report)
    assert cert.filters == ()
    assert cert.sorts == ()


def test_badge_html_renders_cert_fields() -> None:
    cert = _render(_G01).certificate
    badge = render.badge_html(cert)
    assert "<script" not in badge
    assert cert.spec_hash in badge
    assert "dataset.hash_matches_source" in badge
    assert render._FONT_FAMILY in badge


def test_badge_html_with_filters_and_sorts() -> None:
    # Non-empty filters + sorts -> the disclosure loops fire (covers the join comprehensions).
    cert = render.VCert(
        version="vcert-0.1",
        dataset_hash="sha256:" + "0" * 64,
        spec_hash="sha256:" + "1" * 64,
        plotted_table_hash="sha256:" + "2" * 64,
        manifest_hash="sha256:" + "3" * 64,
        checks_passed=("security.no_arbitrary_code",),
        filters=(render.DisclosedFilter(field="region", cmp="eq", value="EU"),),
        sorts=(render.DisclosedSort(field="month", order="ascending"),),
        tcb=render._tcb(),
    )
    badge = render.badge_html(cert)
    assert "region" in badge
    assert "month" in badge
    assert "<script" not in badge


def test_badge_html_escapes_adversarial_filter_value() -> None:
    # A model-controlled filter value carrying markup + control chars is escaped to inert text.
    # chr(0x2028) = U+2028 LINE SEPARATOR: inert in HTML text. Built via chr() rather than a
    # unicode-escape literal so the source stays pure ASCII -> ruff RUF001 stays silent, and no
    # Write/Edit JSON transport can decode an escape back into the raw char (which re-triggers it).
    hostile = "</script><script>alert(1)</script><>&\"'\n" + chr(0x2028)
    cert = render.VCert(
        version="vcert-0.1",
        dataset_hash="sha256:" + "0" * 64,
        spec_hash="sha256:" + "1" * 64,
        plotted_table_hash="sha256:" + "2" * 64,
        manifest_hash="sha256:" + "3" * 64,
        checks_passed=(),
        filters=(render.DisclosedFilter(field="x", cmp="eq", value=hostile),),
        sorts=(),
        tcb=render._tcb(),
    )
    badge = render.badge_html(cert)
    assert "<script>" not in badge
    assert "</script>" not in badge
    assert "&lt;script&gt;" in badge
    assert "&amp;" in badge and "&quot;" in badge and "&#x27;" in badge
```

Test imports to ADD:
- `from verifier import canon, ingest, render` → add `checks`: `from verifier import canon, checks, ingest, render`
  (`checks.VerificationReport` is constructed in the direct build_certificate tests).
- `from verifier.schema import Aggregate, Measure, VPlotSpec, decode_spec` → add the structs the direct tests
  construct: `Channel, Dataset, Encoding, Filter, Select, Sort, SortKey`. NOTE the aliased `Channel.kind`
  attribute: construct with `kind=` (the Python attr), NOT `type=` (that is only the JSON key) — same as
  `Measure(output=…)` elsewhere in the suite.

---
## Branch-coverage map (render.py new code)

- `build_certificate`: `if spec.mark == "bar"` True (g01) / False (g07, g10); `if color is not None` True (g07) /
  False (g01, g10); filter genexpr isinstance True+False + non-empty (constructed mix test) + empty (empty test);
  sort genexpr isinstance True+False + inner key loop (2 keys) + empty. All covered by the tests above.
- `badge_html`: three join genexprs — a non-empty run covers both the yield + exhaust arcs (checks always ≥1;
  filters/sorts non-empty in `test_badge_html_with_filters_and_sorts`; empty case in the g01/adversarial certs).
- `render`: `if not report.passed` True (broken spec) / False (g01). `cast` has no runtime branch.
- Module-level `_FONT_SHA256` executes at import (no branch).

## Close steps
1. Append the render.py code + fix imports; append the test block + fix test imports.
2. Gate: `UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --locked ruff format --check . && uv run --locked ruff check . && uv run --locked mypy && uv run --locked pytest`
   (code is pre-formatted to ruff style — double-quoted, long `Sort(...)` pre-wrapped, `chr(0x2028)` keeps the U+2028 test source ASCII — so `--check` passes clean as-transcribed; on any stray reflow run `ruff format .` then re-check). Confirm 100% branch, render.py fully covered.
3. Record ctx (`.agent/context.sh`) into the roadmap M1.6c row; set M1.6c DONE. M1 stays IN-PROGRESS (M1.6d OPTIONAL remains).
4. Commit `render (M1.6c): VCert v0.1 badge + render() gate`. Delete this doc at M1 review.
