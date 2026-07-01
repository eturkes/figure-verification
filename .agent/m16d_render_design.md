# M1.6d recipe — `render.py` OPTIONAL offline interactive HTML (OFF the cert hash chain)

GATE-VALIDATED: this EXACT code was transcribed onto M1.6c's `render.py` + `test_render.py` and ran
the full gate GREEN (`ruff format --check .` · `ruff check .` · `mypy` · `pytest` → 479 passed /
100% branch; `render.py` 154 stmt · 36 br fully covered), then REVERTED. So TRANSCRIBE faithfully,
run one no-op autofix (`ruff format .`), then the gate — expect a clean pass; salvage-continue on any
drift. Delete this doc at M1 review.

Read ONLY: this doc + `src/verifier/render.py` (append the block after `render_svg`; edit
`RenderResult` + `render`) + `tests/test_render.py` (append). The lever is CONFIRMED — do NOT
re-probe vl-convert (inline probing is what overflowed the prior window).

## Confirmed lever (de-risked across isolated probes — trust, do not re-derive)
- `vl_convert.javascript_bundle(snippet, vl_version="5.21")` bundles vega + vega-lite + vega-embed +
  deps into ONE self-contained `<script>` (no external fetch; only inert namespace URLs inside),
  byte-deterministic within the lockfile-pinned `vl-convert-python` build (fixed `vl_version`),
  ~0.9MB. The snippet references the INJECTED library globals (`vegaEmbed` / `vegaLite` / `vega` /
  `lodashDebounce`) WITHOUT any `import`; `"window.vegaEmbed = vegaEmbed;"` re-exposes `vegaEmbed`
  as a window global. (An `import … from "vega-embed"` FAILS to resolve in the bundler; `""`
  tree-shakes to an EMPTY bundle — hence the non-empty, global-referencing snippet.)
- vl-convert's own `vegalite_to_html` is REJECTED: it re-serializes the spec (undoing any pre-escape
  → a `</script>` in a string cell survives) AND always ships the actions/editor menu with no
  disable lever (1.9.0.post1). So we OWN the template.
- Breakout-safety: embed the built JSON as inert `<script type="application/json">` DATA
  (`JSON.parse`'d at runtime, never executed) with `</` → `<\/` rewritten. Because WE own the
  template (the spec is NOT routed through vl-convert's serializer) the escape survives; `\/` is a
  valid JSON escape → `JSON.parse` recovers `/` losslessly; the HTML parser sees `<\/script` so the
  data block never closes early. Scope: neutralizes the primary `</script>` breakout — defense in
  depth, since in the pipeline every spec byte is manifest-/trusted-source-derived (untrusted-input
  hardening is M2+). `vegaEmbed` runs `{actions: false, renderer: "svg"}` → menu-free, mirroring
  `render_svg`.

## `render.py` additions

1) Add `import functools` to the stdlib import block (alphabetical — immediately before
   `import hashlib`).

2) Insert AFTER `render_svg`'s `return`, BEFORE the `# --- provenance certificate (M1.6c …)` comment:

```python
# --- interactive HTML (M1.6d: OPTIONAL offline self-contained view, OFF the cert hash chain) -
# A second, non-canonical rendering of the SAME builder JSON the SVG and cert consume: a fully
# offline, self-contained interactive page (pan / zoom / hover). It is NEVER hashed into the VCert
# -- the plotted-table hash stays the one canonical artifact, and this HTML is trusted output like
# the SVG. Two levers keep it self-contained and menu-free:
#   * javascript_bundle inlines vega + vega-lite + vega-embed (and their deps) into ONE <script>
#     with no external fetch (only inert namespace URLs appear inside it), byte-deterministic for
#     the lockfile-pinned vl-convert build + vl_version, and (asserted by a test) no raw </script>
#     that would break its own wrapper. The snippet references the injected vegaEmbed window global.
#   * the built spec is embedded as inert <script type="application/json"> DATA -- JSON.parse'd at
#     runtime, never executed -- with the </script close sequence rewritten so a string cell that
#     holds a literal </script> cannot terminate the data block early; vegaEmbed runs with
#     actions:false, so NO editor/actions menu (hence no "open in Vega editor" external link) is
#     shown. renderer:"svg" mirrors render_svg.
# vl-convert's own vegalite_to_html is deliberately NOT used: it re-serializes the spec (which
# undoes any pre-escape) and always ships the actions menu with no lever to disable it.
_EMBED_SNIPPET = "window.vegaEmbed = vegaEmbed;"


@functools.cache
def _embed_bundle() -> str:
    """The offline vega / vega-lite / vega-embed JavaScript bundle exposing vegaEmbed as a window
    global. javascript_bundle injects the library names into the snippet's scope; the snippet
    references vegaEmbed, so it (and its deps) are bundled. Byte-deterministic within the
    lockfile-pinned vl-convert build (fixed vl_version) and self-contained (no external fetch;
    only inert namespace URLs appear inside it). Cached: it is identical for every chart and
    costs ~0.7s / ~0.9MB to build, so it is built at most once per process."""
    return vl_convert.javascript_bundle(_EMBED_SNIPPET, vl_version=_VL_VERSION)


def render_html(vega_lite_json: str) -> str:
    """A self-contained, fully offline interactive HTML page (pan / zoom / hover) for a
    BUILDER-PRODUCED Vega-Lite JSON string -- the same string render_svg consumes. No external
    fetch (the vega bundle is inlined) and no editor/actions menu (actions:false). OFF the cert
    hash chain: a convenience view, never hashed into the VCert. Self-containment also rests on
    embedding the spec as inert application/json DATA (JSON.parse'd, never executed) with the
    </script close sequence neutralized, so a string cell holding a literal </script> cannot break
    out of the data block. Like render_svg it trusts its builder input rather than sanitizing an
    arbitrary hand-rolled spec; in the pipeline every string byte is manifest- or
    trusted-source-derived (untrusted-input hardening is M2+)."""
    safe_spec = vega_lite_json.replace("</", r"<\/")
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
        "</body>\n"
        "</html>\n"
    )
```

3) On the `RenderResult` struct — replace its docstring and add the `html` field:

```python
    """A verified render: the self-contained SVG plus its provenance certificate, and -- only when
    render(include_html=True) requests it -- an optional fully offline interactive HTML view (OFF
    the cert hash chain; None otherwise)."""

    svg: str
    certificate: VCert
    html: str | None = None
```

4) On `render(…)` — add the keyword-only param `    include_html: bool = False,` (after `data_dir`,
   before the closing `)`); extend the docstring's final sentence (before the closing `"""`) with:

```
 With include_html=True the
    result also carries a self-contained offline interactive HTML view of the same built spec
    (render_html) -- OFF the cert hash chain: the SVG bytes and the certificate are byte-identical
    whether or not it is requested.
```

   and refactor the function tail (compute `built_json` once) from:

```python
    svg = render_svg(vega_lite_json(spec, table, manifest))
    certificate = _build_certificate(spec, manifest_bytes, table, report)
    return RenderResult(svg=svg, certificate=certificate)
```

   to:

```python
    built_json = vega_lite_json(spec, table, manifest)
    svg = render_svg(built_json)
    certificate = _build_certificate(spec, manifest_bytes, table, report)
    interactive_html = render_html(built_json) if include_html else None
    return RenderResult(svg=svg, certificate=certificate, html=interactive_html)
```

## `test_render.py` additions

Append (reuses existing helpers `_evaluated` / `_external_refs` / `_good` / `_manifest_bytes` /
`_render` and constants `_DATA` / `_G01` / `_G07` / `_G10`; `json` + `re` are already imported):

```python
# --- M1.6d: OPTIONAL offline interactive HTML (off the cert hash chain) -------
# External-fetch audit for the HTML page: a src/href attribute valued as an absolute http(s) URL
# (a network load on page open). The inlined bundle carries none (proven below) and my template
# adds none; scoped to http(s):// so an inert data string never false-positives.
_HTML_FETCH_RE = re.compile(r"""(?i)\b(?:src|href)\s*=\s*(["'])https?://""")


def _json_data_block(html_doc: str) -> str:
    """The inert application/json spec payload from a render_html page, up to the first real
    </script> (a neutralized close sequence in a breakout cell does not match, so it is skipped)."""
    match = re.search(r'<script type="application/json"[^>]*>(.*?)</script>', html_doc, re.DOTALL)
    assert match is not None
    return match.group(1)


def _html(name: str) -> str:
    spec, manifest, table = _evaluated(name)
    return render.render_html(render.vega_lite_json(spec, table, manifest))


def test_embed_bundle_is_offline_and_deterministic() -> None:
    # The inlined JS bundle adds no external fetch, carries no raw </script> that would break its
    # inlining <script> wrapper, and is byte-stable across rebuilds for the pinned vl-convert build.
    render._embed_bundle.cache_clear()
    bundle = render._embed_bundle()
    assert len(bundle) > 100_000  # vega + vega-lite + vega-embed inlined, not a stub
    assert _HTML_FETCH_RE.search(bundle) is None  # no external src/href fetch
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


def test_render_html_is_menu_free_and_interactive() -> None:
    html_doc = _html(_G01)
    assert "vegaEmbed(" in html_doc  # an interactive embed, not a static image
    assert '{actions: false, renderer: "svg"}' in html_doc  # no editor/actions menu


def test_render_html_embeds_the_built_spec() -> None:
    # The page shows the SAME recomputed data the SVG/cert are built from: the inert data block
    # parses back to the builder JSON (lossless through the </script neutralization).
    spec, manifest, table = _evaluated(_G01)
    built_json = render.vega_lite_json(spec, table, manifest)
    assert json.loads(_json_data_block(render.render_html(built_json))) == json.loads(built_json)


def test_render_html_neutralizes_script_breakout() -> None:
    # A string cell holding </script> + live markup cannot close the data block early; JSON.parse
    # still recovers the exact value (the escape is lossless).
    payload = '{"data":{"values":[{"a":"</script><svg onload=alert(1)>","b":1}]}}'
    block = _json_data_block(render.render_html(payload))
    assert "</script" not in block  # the breakout close sequence is neutralized in the data block
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
    # Requesting the HTML view changes neither the SVG bytes nor the certificate.
    spec, _ = _good(_G01)
    mb = _manifest_bytes(_G01)
    plain = render.render(spec, mb, data_dir=_DATA)
    withhtml = render.render(spec, mb, data_dir=_DATA, include_html=True)
    assert plain is not None and withhtml is not None
    assert plain.svg == withhtml.svg
    assert plain.certificate == withhtml.certificate
    assert plain.html is None and withhtml.html is not None
```

Coverage note (mypy trap already fixed above): keep `test_render_include_html_attaches_offline_view`
as THREE asserts — `result.html is not None` FIRST (narrows `str | None` → `str`), then the `==`,
then `.startswith`. Folding `is not None` into the same `and` as the `==` line trips mypy
`redundant-expr` ("left operand always true"), because the `== <str>` assert already narrows away
`None`.

## Coverage (100% branch holds)
- `_embed_bundle` (@functools.cache) + `render_html` have NO branches — exercised by the
  bundle / scaffold / menu-free / embed / breakout / determinism tests.
- render()'s only NEW branch is `render_html(built_json) if include_html else None`:
  TRUE arm ← `test_render_include_html_attaches_offline_view` +
  `test_render_html_is_off_the_cert_hash_chain`; FALSE arm ← `test_render_default_omits_html` + every
  pre-existing render() test.

## Close
Set M1.6d → DONE and M1 → IMPLEMENTED (all units DONE) in the roadmap ledger + record M1.6d's
context-usage (`.agent/context.sh`, full `pct used/window`); trim the M1.6d pointer in
`.agent/memory.md` to "render.py fully COMPLETE"; commit
`render (M1.6d): offline interactive HTML view off the cert hash chain`. Next session =
MILESTONE-REVIEW (1M context).
