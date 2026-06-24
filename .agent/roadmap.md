# figure-verification — roadmap

Local "verified-plot" PoC. A weak local LLM only PROPOSES a restricted JSON chart spec (VPlot); a separate trusted verifier deterministically recomputes the plotted data from the source CSV, runs structured checks, blocks invalid/misleading charts, and renders only verified charts with a provenance certificate (dataset hash, spec hash, plotted-table hash, passed checks).

- **Scope-seed**: `.agent/outline.md` — the original outline as 16 verbatim seed steps "Milestone 0..15" (commit `9d09ecb`). The ledger below maps each routine-milestone `M<m>` to those steps; read the relevant seed step on demand when planning a milestone.
- **Stack + determinism invariants**: `.agent/memory.md` (Stack / Determinism sections) — researched SOTA, deliberately overriding the outline's human-popular defaults.
- **Modest claim** (hold the line on this): a rendered chart's plotted data, encodings, filters, and labels match a restricted formal VPlot spec over a concrete dataset. NOT claimed: the browser renderer, Vega runtime, or pixels are formally verified.
- **Quality gate** (M1.1 wires it; every WORK-UNIT VERIFY runs it, all green, touched scripts exit clean): `ruff format --check .` · `ruff check .` · `mypy` · `pytest` — all via `uv run`.

## Milestone ledger

| M | Title | Seed steps | Gate | Status |
|---|-------|-----------|------|--------|
| **M1** | Trusted verifier core (headless) | 0,1·scaffold,2,3,4,5,6 | none — toolchain confirmed | **IN-PROGRESS** |
| M2 | Verifier API service (FastAPI) | 1·api,8 | none | UNPLANNED |
| M3 | Local model proposer + failure eval | 1·model,7,12 | Ollama + a local model | UNPLANNED |
| M4 | Open WebUI integration | 1·webui,9,10,11 | Open WebUI running | UNPLANNED |
| M5 | Formal + provenance hardening | 13,14 | none | UNPLANNED |
| M6 | End-to-end demo | 15 | full stack (M3+M4) | UNPLANNED |

Seed step 1 ("create the local stack") is split by gate: scaffold+data → M1, API → M2, model backend → M3, Open WebUI → M4. Plan each milestone only when it becomes active (prior one REVIEWED); M3/M4/M6 are gated — confirm preconditions functionally at their planning turn, deny-listed inputs off-limits.

---

## M1 — Trusted verifier core   (IN-PROGRESS)

Headless, fully gate-free: pure local Python over synthetic CSVs, exercised entirely by pytest. No Open WebUI / Ollama / Docker / runtime network. Delivers the trusted recompute → check → render → certificate pipeline as the library `verifier`. Units run in dependency order (all gate-independent). Record each unit's context-usage (`.agent/context.sh`, full `pct used/window`) at its close.

| Unit | Deliverable | Status | Ctx |
|------|-------------|--------|-----|
| M1.1 | Scaffold + tooling + scope doc | OPEN | — |
| M1.2 | VPlot v0.1 schema (msgspec) | OPEN | — |
| M1.3 | Synthetic datasets + golden good/bad specs | OPEN | — |
| M1.4 | Deterministic evaluator + canonical hashing | OPEN | — |
| M1.5 | Verification checks v0 | OPEN | — |
| M1.6 | VPlot → Vega-Lite → SVG/HTML compiler + badge | OPEN | — |

### M1.1 — Scaffold + tooling + scope doc
- `uv` src-layout package `verifier/` (+ `py.typed`, `uv_build` backend), `requires-python = ">=3.13"`, committed `uv.lock`. Dev group: ruff, mypy, pytest, pytest-cov, hypothesis, syrupy, duckdb.
- `pyproject.toml` configured per memory Stack (ruff select incl. S/T20/DTZ; `mypy --strict`; pytest `--strict-markers --strict-config`; branch coverage; Hypothesis CI/dev profiles).
- `POC_SCOPE.md` (one page): allowed charts (bar/line/scatter), allowed transforms (select/filter/group_by/aggregate{sum,mean,count,min,max}/sort), what verification means here, what is intentionally unsupported (arbitrary Python/SQL/JS, free-form Vega expr, maps, faceting, interaction, dashboards, joins), and the modest claim above.
- **Accept**: quality gate green on the skeleton; scope doc answers all four questions.

### M1.2 — VPlot v0.1 schema (msgspec)
- `verifier/schema.py`: frozen `msgspec.Struct` models (`VPlotSpec`, encoding channels, `Transform` tagged union Select/Filter/GroupBy/Aggregate/Sort with `tag_field="op"`), `mark` = `Literal["bar","line","scatter"]`, aggregate fn `Literal` over the five fns, `forbid_unknown_fields=True` on every struct, bounds via `Meta`; one module-level `Decoder`; emit `msgspec.json.schema(VPlotSpec)` as a golden-snapshotted artifact.
- **Accept**: valid specs decode to typed objects; unknown field/mark/transform/agg-fn rejected at decode; no coercion (string-for-number, bool-for-int rejected); fuzz/property test → decode yields a valid typed object or `ValidationError`, never partial/coerced; emitted JSON Schema is draft-2020-12 valid and snapshot-stable.

### M1.3 — Synthetic datasets + golden good/bad specs
- `data/`: synthetic CSVs (`sales.csv` per seed step 2, plus ≥1 more and a `deliberately_dirty.csv`).
- `examples/good_specs/` (≥5) and `examples/bad_specs/` (≥10), each bad spec covering a distinct failure (nonexistent field, wrong aggregation, undeclared filter, y-claims-revenue-plots-orders, missing y-unit, non-zero bar baseline, mis-declared sort, derived-value mismatch, unknown mark/transform, coercion attempt) and annotated with its expected failing check.
- 10 natural-language chart intents mapped to good specs.
- **Accept**: all good specs decode (schema-valid); schema-invalid bad specs reject at decode, the rest staged for semantic rejection in M1.5; every bad spec has a documented expected reason.

### M1.4 — Deterministic evaluator + canonical hashing
- `verifier/eval.py` (hand-rolled): typed CSV load (text → declared-schema coercion; decimals → `Decimal`/scaled-int, never float at ingest) → allowlisted transforms with compensated summation and an explicit TOTAL-sort closure → canonical plotted table.
- `verifier/canon.py`: typed-NDJSON table serializer + msgspec-re-encode spec hash + raw-CSV dataset hash (all SHA-256, text canonical forms, never Parquet/Arrow bytes).
- DuckDB oracle (dev/test): `threads=1` reproduces byte-identical canonical tables on every golden good case.
- **Accept**: good specs → exactly reproducible plotted tables (row-for-row golden); dataset hash changes on source change, plotted-table hash changes on transform change; property tests prove all three hashes permutation-invariant and stable across runs/process restarts; dual-engine (hand-roll vs DuckDB) hash agreement green; no plain float `sum`, no binary-serialization hashing.

### M1.5 — Verification checks v0
- `verifier/checks.py`: all deterministic checks (`schema.fields_exist`, `schema.field_types_match`, `transform.ops_allowed`, `transform.aggregates_match_recomputation`, `transform.filters_declared`, `encoding.fields_exist_in_plotted_table`, `encoding.axis_types_match_fields`, `encoding.legend_domain_matches_data`, `scale.bar_y_zero`, `label.quantitative_units_present`, `security.no_arbitrary_code`) → structured results `{check, status, message, severity}`; renderer NOT called if any blocking check fails.
- `aggregates_match_recomputation` is value/hash equality against the M1.4 recompute.
- **Accept**: structured pass/fail with user-readable reasons; every bad-spec category from M1.3 fails with its specific expected check; `false_accept_count = 0` on the bad-spec suite; property test for aggregate-vs-recompute; tests cover every failure category.

### M1.6 — VPlot → Vega-Lite → SVG/HTML compiler + badge
- `verifier/render.py`: pure VPlot→Vega-Lite spec builder (whitelist fields; inline ONLY the evaluator's canonical plotted table as `data.values`; reject `data.url`/`datasets`/`transform`/`params`/`expr`) → vl-convert static **SVG** (pinned `vl_version` + vendored/registered font) → provenance badge composed in trusted Python (dataset/spec/plotted-table hashes, checks passed, `vl_version`). Optional non-canonical interactive HTML (`bundle=True`, `actions=False`, offline), excluded from the hash chain.
- **Accept**: passing spec → inline chart embedding verifier-computed data + visible provenance/verification status; failing spec → no chart; injection test (bad specs with url/transform/expr refused, never rendered); self-containment test (zero http(s) fetches, `$schema` stripped/pinned, no external editor link); provenance test (badge hashes equal verifier-computed hashes; editing any input flips the relevant hash); determinism goal (same good spec → byte-identical SVG twice / after clean reinstall).

### M1 close (when M1.1–M1.6 all DONE)
Set M1 IMPLEMENTED; the next session runs MILESTONE-REVIEW (1M context), then planning of M2.
