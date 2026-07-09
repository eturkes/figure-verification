# demo — throwaway PoC (branch `poc/bilingual-demo`)

Bilingual (EN+JA) offline gallery over the completed M1 verifier. It presents VPlot
as the project-specific JSON-like DSL: a small verifier vocabulary serialized as JSON,
not generic Vega-Lite / arbitrary JSON / code. Full golden corpus: 10 good DSL objects
→ `render()` SVG + verbatim `badge_html` VCert badge; 18 bad DSL objects → blocked
cards with the verifier's failing-check messages. Zero scripts, zero external refs;
rebuild is byte-deterministic in the same locked env.

- Build: `uv run --locked demo/build_demo.py` → `demo/index.html` (open in any browser)
- UI chrome EN+JA stacked/side-by-side (no language toggle, per design brief); verifier
  output + JSON artifacts stay verbatim EN (data, not chrome)
- Kept ruff-clean via file-level `T201`/`E501` noqa; outside mypy/coverage scope —
  throwaway by intent, delete the branch when done
