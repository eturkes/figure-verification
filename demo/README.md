# demo — throwaway PoC (branch `poc/bilingual-demo`)

Bilingual (EN+JA) offline gallery over the completed M1 verifier. Full golden corpus:
10 good specs → `render()` SVG + verbatim `badge_html` VCert badge; 18 bad specs →
blocked cards with real `decode_spec` / `checks.verify` output. Zero scripts, zero
external refs; rebuild is byte-deterministic.

- Build: `uv run demo/build_demo.py` → `demo/index.html` (open in any browser)
- UI chrome EN+JA stacked/side-by-side (no language toggle, per design brief); verifier
  output + JSON artifacts stay verbatim EN (data, not chrome)
- Kept ruff-clean via file-level `T201`/`E501` noqa; outside mypy/coverage scope —
  throwaway by intent, delete the branch when done
