# figure-verification — roadmap

Local "verified-plot" PoC. A weak local LLM only PROPOSES a restricted JSON chart spec (VPlot); a separate trusted verifier deterministically recomputes the plotted data from the source CSV, runs structured checks, blocks invalid/misleading charts, and renders only verified charts with a provenance certificate (dataset hash, spec hash, plotted-table hash, passed checks).

- **Scope-seed**: `.agent/outline.md` — the original outline as 16 verbatim seed steps "Milestone 0..15" (commit `9d09ecb`). The ledger below maps each routine-milestone `M<m>` to those steps; read the relevant seed step on demand when planning a milestone.
- **Stack + determinism invariants**: `.agent/memory.md` (Stack / Determinism sections) — researched SOTA, deliberately overriding the outline's human-popular defaults.
- **Data-flow (trust spine)**: the untrusted model proposes ONLY a VPlot spec (transforms + encoding + declared `dataset.hash`) — never plotted values. The verifier recomputes ALL plotted data; the renderer inlines only that. So lies needing model-supplied data (the seed's "plots a value ≠ recomputation") are impossible by construction, not checks; checks target spec/encoding/policy/dataset-binding consistency. (The seed's `aggregates_match_recomputation` example carries a model-supplied value — a seed inconsistency, resolved here.)
- **Modest claim** (hold the line): verified = {validated spec, the independently recomputed plotted table, the emitted Vega-Lite inlining only that table, the provenance badge} are mutually consistent and the checks passed. Trusted, NOT verified (TCB): `vl-convert`/Vega, SVG rasterization, browser, pixels — trusted to render verified data faithfully, not proven to.
- **Quality gate** (M1.1 wires it; every WORK-UNIT VERIFY runs it, all green, touched scripts exit clean): `ruff format --check .` · `ruff check .` · `mypy` · `pytest` — all via `uv run --locked` (the lockfile, not a newer floor-satisfying release, pins the gate).

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

Headless, fully gate-free: pure local Python over synthetic CSVs, exercised entirely by pytest. No Open WebUI / Ollama / Docker / runtime network. Delivers the trusted recompute → check → render → provenance-badge (VCert v0.1, non-replayable) pipeline as the library `verifier`. Units run in dependency order (all gate-independent). Record each unit's context-usage (`.agent/context.sh`, full `pct used/window`) at its close.

| Unit | Deliverable | Status | Ctx |
|------|-------------|--------|-----|
| M1.1 | Scaffold + tooling + scope doc | DONE | 44% 87K/200K |
| M1.2 | VPlot v0.1 schema (msgspec) | OPEN | — |
| M1.3 | Synthetic datasets + golden good/bad specs | OPEN | — |
| M1.4 | Deterministic evaluator + canonical hashing | OPEN | — |
| M1.5 | Verification checks v0 | OPEN | — |
| M1.6 | VPlot → Vega-Lite → SVG/HTML compiler + badge | OPEN | — |

### M1.1 — Scaffold + tooling + scope doc
- `uv` src-layout package `verifier/` (+ `py.typed`, `uv_build` backend), `requires-python = ">=3.13,<3.14"` (capped + `.python-version` pinned to the 3.13.x line for hash determinism — NFC/UCD version changes at 3.14), committed `uv.lock`. Dev group: ruff, mypy, pytest, pytest-cov, hypothesis, syrupy, duckdb.
- `pyproject.toml` configured per memory Stack (ruff select incl. S/T20/DTZ; `mypy --strict`; pytest `--strict-markers --strict-config`; branch coverage; Hypothesis CI/dev profiles).
- `POC_SCOPE.md` (one page): allowed charts (bar/line/scatter), allowed transforms (select/filter/group_by/aggregate{sum,mean,count,min,max}/sort), what verification means here, what is intentionally unsupported (arbitrary Python/SQL/JS, free-form Vega expr, maps, faceting, interaction, dashboards, joins), and the modest claim above.
- **Accept**: quality gate green on the skeleton; scope doc answers all four questions.

### M1.2 — VPlot v0.1 schema (msgspec)
- `verifier/schema.py`: frozen `msgspec.Struct` models (`VPlotSpec`, encoding channels, `Transform` tagged union Select/Filter/GroupBy/Aggregate/Sort with `tag_field="op"`), `mark` = `Literal["bar","line","scatter"]`, aggregate fn `Literal` over the five fns, `forbid_unknown_fields=True` on every struct, bounds via `Meta`; spec numerics are int or decimal-string (floats forbidden, so the re-encode hash is exact); one module-level `Decoder`; emit `msgspec.json.schema(VPlotSpec)` as a golden-snapshotted artifact.
- `VPlot_SEMANTICS.md`: the formal companion that makes "formal VPlot" honest — data model, one null token, total-order rule, numeric/rounding semantics per op, transform semantics, label/unit policy, error conditions. (Schema is syntax; this is meaning.)
- **Accept**: valid specs decode to typed objects; unknown field/mark/transform/agg-fn rejected at decode; no coercion (string-for-number, bool-for-int rejected); fuzz/property test → decode yields a valid typed object or `ValidationError`, never partial/coerced; emitted JSON Schema is draft-2020-12 valid and snapshot-stable; semantics doc covers every op.

### M1.3 — Synthetic datasets + golden good/bad specs
- `data/`: synthetic CSVs (`sales.csv` per seed step 2, plus ≥1 more and a `deliberately_dirty.csv`).
- `data/schemas/<name>.json`: trusted per-column manifest (type, optional unit + display label) — the source-of-truth the evaluator coerces to and the `field_types_match`/unit/label checks read from (a CSV alone has no types/units); hashed into provenance.
- `examples/good_specs/` (≥5) and `examples/bad_specs/` (≥10), each bad spec annotated with the LAYER that must catch it: decode (unknown mark/transform/agg-fn, coercion attempt), dataset-binding (nonexistent field, wrong type, `dataset.hash` mismatch), encoding/label (y-titled-revenue-plots-orders), policy (undeclared filter, non-zero bar baseline, mis-declared sort, missing y-unit). Drop "derived-value mismatch" — impossible by construction (model supplies no values).
- 10 natural-language chart intents mapped to good specs.
- **Accept**: all good specs decode (schema-valid); every bad spec rejected at its annotated layer (decode now, the rest in M1.5), none accepted; manifests hash-stable; every bad spec documents its expected reason.

### M1.4 — Deterministic evaluator + canonical hashing
- `verifier/eval.py` (hand-rolled): typed CSV load against the M1.3 manifest (text → declared type; all numerics → `Decimal`/scaled-int with a declared per-measure scale + `ROUND_HALF_EVEN`, never float — so sums/means are exact-then-quantize and need no Kahan) → allowlisted transforms → explicit TOTAL-sort closure → canonical plotted table.
- `verifier/canon.py`: typed-NDJSON table serializer + spec hash (msgspec re-encode of the validated struct: definition-order fields, pinned msgspec, NFC strings, no floats, `canon_version` tag) + dataset hash (raw CSV bytes — byte-exact SOURCE identity, sensitive to row-order/CRLF/BOM by design) + manifest hash; all SHA-256 over text canonical forms, never Parquet/Arrow bytes.
- DuckDB oracle (dev/test): `threads=1`, columns loaded as matching `DECIMAL`, reproduces byte-identical canonical tables on goldens; any op it cannot match bit-for-bit falls back to a logged tolerance cross-check.
- **Accept**: good specs → exactly reproducible plotted tables (row-for-row golden); dataset hash changes on source byte change; plotted-table hash changes iff the canonical table changes (semantically no-op transforms don't — use the spec hash for spec edits); property tests search for counterexamples to plotted-table-hash invariance under input-row permutation and to run/restart stability of all hashes (dataset hash is intentionally NOT permutation-invariant); spec hashes computed under an asserted `unicodedata.unidata_version` (recorded with full Python/msgspec/`canon_version`) so a Unicode-data change cannot silently shift them; dual-engine agreement green; no float aggregation, no binary-serialization hashing.

### M1.5 — Verification checks v0
- `verifier/checks.py`: all deterministic checks (`dataset.hash_matches_source` (+ source path confined to `data/`), `schema.fields_exist`, `schema.field_types_match`, `transform.ops_allowed`, `transform.aggregates_match_recomputation`, `transform.filters_declared`, `encoding.fields_exist_in_plotted_table`, `encoding.axis_types_match_fields`, `encoding.legend_domain_matches_data`, `scale.bar_y_zero`, `label.quantitative_units_present` (axis unit/label sourced from the trusted manifest, not the spec — present and correct by construction), `security.no_arbitrary_code`) → structured results `{check, status, message, severity}`; renderer NOT called if any blocking check fails.
- `aggregates_match_recomputation` asserts the rendered/inlined `data.values` are byte-identical to the M1.4 recomputation (the renderer cannot inject or alter values), backed by the dual-engine oracle — NOT a compare against any model-supplied value (there is none).
- **Accept**: structured pass/fail with user-readable reasons; every bad-spec category from M1.3 fails with its specific expected check; `false_accept_count = 0` on the curated bad-spec suite (a suite property, not a general soundness proof); property test for the inlined-data-equals-recompute invariant; tests cover every failure category.

### M1.6 — VPlot → Vega-Lite → SVG/HTML compiler + badge
- `verifier/render.py`: pure VPlot→Vega-Lite builder emitting via a POSITIVE allowlist — a recursive schema of the exact subset we generate; every key outside it is dropped, so top-level `url`/`datasets`/`transform`/`params`/`expr`/`href`/`tooltip`/image-`url`/`loader`/`signals` AND encoding-level `aggregate`/`bin`/`stack`/`impute`/`sort`/`scale.domain`/`scale.type` are excluded by construction, not enumeration (and Vega-Lite's IMPLICIT stacking/sorting nulled: explicit `stack:null` + a `sort` matching the recomputed row order) — so the marks display exactly the inlined rows, nothing re-derived; inline ONLY the evaluator's canonical plotted table as `data.values` → vl-convert static **SVG** (pinned `vl_version` + vendored/registered font) → VCert v0.1 badge in trusted Python (dataset/spec/plotted-table/manifest hashes, checks passed, applied filters/sorts disclosed so a reader sees the selected subset, TCB versions `vl_version`/msgspec/`canon_version`/`unidata_version`/Python; non-replayable — replay/signing → M5). Optional non-canonical interactive HTML (`bundle=True`, `actions=False`, offline), off the hash chain.
- **Accept**: passing spec → inline chart embedding verifier-computed data + visible provenance/verification status; failing spec → no chart; injection test (bad specs with url/transform/expr, or encoding-level aggregate/bin/stack/impute/scale-domain, refused or stripped, never rendered; implicit stack/sort proven off — displayed values equal the inlined recomputed table); self-containment + output-scan (emitted SVG/HTML has no `<script>`, no external `href`/`src`/`url`, zero http(s) fetches, `$schema` stripped/pinned, no editor link); provenance test (badge hashes equal verifier-computed hashes; editing any input flips the relevant hash); determinism goal (same good spec → byte-identical SVG twice / after clean reinstall).

### M1 close (when M1.1–M1.6 all DONE)
Set M1 IMPLEMENTED; the next session runs MILESTONE-REVIEW (1M context), then planning of M2.
