---
paths:
  - "src/verifier/render.py"
  - "src/verifier/matplotlib_script.py"
---

# Renderer + Vega-Lite

- **vl-convert-python** (pinned `vl_version` + lockfile build) → static SVG in the display TCB; pixels unhashed/trusted. SVG sits outside the VCert hashes + is diagnostic-only for exact replay, but the signed archive DOES digest-bind it.
- Positive-allowlist Vega builder copies no model key, disables implicit stack/sorts, inlines only recomputation. The badge interpolates one integer (the passing-check count) and no filter value.
- JS parses JSON numerics as f64 ⇒ DISPLAY can round while certified bytes stay exact.
- Offline HTML stays outside the cert, fully bundled with inert JSON + every-`<` escape + `actions:false`; vendored DejaVu guarantees font availability, not byte selection over a same-name system font.
- Pinned Vega-Lite 5.21 compiles an explicit empty nominal color domain (`[]`, all-null data) + numeric ordinal domains — transcribe those forms without re-probing.
