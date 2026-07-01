# figure-verification — roadmap

Local "verified-plot" PoC. A weak local LLM only PROPOSES a restricted JSON chart spec (VPlot); a separate trusted verifier deterministically recomputes the plotted data from the source CSV, runs structured checks, blocks charts whose spec, encoding, policy, or dataset binding fail those checks, and renders only verified charts with a provenance certificate (dataset hash, spec hash, plotted-table hash, passed checks).

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

**Right-sizing rule** (hard-won across M1.4/M1.5/M1.6 — the Ctx column below is the evidence; carry it into M2+ unit sizing): size a unit at ~one module + its tests; an independent oracle or a property/fuzz layer is its OWN unit, never bundled. A unit whose DESIGN alone overflows a 200K window is mis-sized → split it. A unit that overflows in IMPLEMENTATION despite a complete recipe is OVER-deriving, not under-specified → pre-derive a gate-validated transcription recipe (`.agent/*_design.md`), TRANSCRIBE not re-derive, reach the gate early, and salvage-continue (overflow ≠ bad work — a completed-but-overflowed unit's gate-green output stands). Delete recipes at M1 review.

| Unit | Deliverable | Status | Ctx |
|------|-------------|--------|-----|
| M1.1 | Scaffold + tooling + scope doc | DONE | 44% 87K/200K |
| M1.2a | VPlot v0.1 schema + fail-closed decoder | DONE | 60% 121K/200K |
| M1.2b | VPlot semantics doc + never-partial fuzz suite | DONE | 63% 126K/200K |
| M1.3 | Synthetic datasets + golden good/bad specs | DONE | 72% 144K/200K |
| M1.4a | Canonical forms + provenance hashing (`canon.py`) | DONE | 71% 141K/200K |
| M1.4b | Typed ingest: manifest + CSV→`Table` (`ingest.py` + `errors.py`) | DONE | 68% 136K/200K |
| M1.4c | Step-0 ingest refactor: shared `_decimal_at_scale` + `check`-param threading (`ingest.py`) | DONE | 61% 122K/200K |
| M1.4d | Deterministic evaluator + index normalize + 100% coverage (`eval.py`) | DONE | overflow→compaction (impl+suite written; gate-finished next session: 44% 88K/200K) |
| M1.4e | Eval golden corpus + determinism anchor (`test_eval.py`) | DONE | 56% 112K/200K |
| M1.4f | Dual-engine DuckDB oracle + parity (`tests/oracle.py`; recipe `.agent/m14f_oracle_design.md`) | DONE | 39% 78K/200K |
| M1.4f-cr | Codex-review follow-up (↓ callout): r1 `git apply …m14f_codex_fixes.patch`; r2 recipe `.agent/m14f_cr2_design.md`; r3 in-session fix | r1 DONE `a6e0fb1` · r2 DONE `0114cd1` · r3 DONE | r1 30% 60K/200K · r2 68% 136K/200K · r3 75% 149K/200K |
| M1.4g | Eval determinism properties (`tests/test_eval_properties.py`) | DONE | 71% 143K/200K |
| M1.5a | Verifier spine: structured report + binding/eval-surface/affirmed checks (`checks.py`) | DONE | 77% 153K/200K |
| M1.5b | Structural encoding checks: fields-exist + axis-types (`checks.py`; recipe `.agent/m15bc_checks_design.md`) | DONE | 60% 121K/200K |
| M1.5c | Label-unit check + count-exempt position-aware lineage + full false-accept (`checks.py`; recipe `.agent/m15bc_checks_design.md`) | DONE | 88% 175K/200K |
| M1.6a | `render.py` builder: canonical JSON + Vega-Lite positive allowlist + lineage rename (recipe `.agent/m16a_render_design.md`) | DONE | 67% 134K/200K |
| M1.6a-cr | Codex-review follow-up (2 rounds): r1 mark-level line `order` (v5-schema blocker) + column-scale `_scaled_cell` + mark-validity regression + `unit_source` rename (`ded3dc6`); r2 claim-honesty — scope "total over canon.Table" + the M1.5 affirmation + the order-EFFECT to what M1.6a proves; builder-totality HARDENING (validate-all-pairs + dup-name guard + property test) deferred to M1.6b | DONE | 87% 173K/200K |
| M1.6b | `render.py` SVG: vl-convert dep + vendored font + determinism/self-containment | DONE | 88% 177K/200K |
| M1.6c | `render.py` provenance: VCert v0.1 badge + render() gate (recipe `.agent/m16c_render_design.md`) | OPEN | — |
| M1.6d | `render.py` OPTIONAL offline interactive HTML (isolated vl-convert probe) | OPTIONAL | — |

DONE-unit detail (M1.1–M1.6b: per-unit design + accept criteria) is realized in code + tests + `.agent/memory.md` lessons + git; recover the pre-implementation prose via `git log --grep "(M1[. ]"` / `git show <planning-commit>`. Below: only the OPEN/OPTIONAL units + M1 close. The M1-review session (1M context) reads every commit, so the git-held detail is fully available there.

#### M1.6c — render.py provenance: VCert v0.1 badge + render() gate
TRANSCRIBE from `.agent/m16c_render_design.md` (COMPLETE render.py additions + tests + coverage map + close steps; gate-validated PRE-corrections, codex-review fixes reasoned-consistent but not re-run → expect a near-clean pass, reach the gate early, salvage-continue; delete the doc at M1 review). Read ONLY that doc + `src/verifier/render.py` (append after `render_svg`) + `tests/test_render.py` (append). Adds the provenance layer + the single public entry over M1.6a/b — NO native-dep probe (offline HTML is M1.6d).
- Surface (recipe carries exact code): structs `Tcb` (the disclosed render TCB: canon/python/msgspec/unidata + `vl-convert-python` version + pinned `vl_version` + vendored font family+sha256 — provenance disclosure of the toolchain, NOT a byte-identity proof; vl-convert may pick a same-named system font, cross-machine SVG identity unclaimed), `DisclosedFilter`/`DisclosedSort`, `VCert` (4 hashes + checks-passed + disclosed filters/sorts + `Tcb`), `RenderResult`(svg, certificate); `build_certificate(spec, manifest_bytes, table, report)` — dataset hash = `spec.dataset.hash` (binding already proved it == source), spec/table/manifest hashes recomputed (manifest over the raw BYTES threaded in), checks-passed = report passes PLUS the renderer-enforced checks that APPLY: bar-zero only for a bar with a quantitative positional axis (the builder's exact `scale.zero` condition), legend-domain when a color channel is present; `badge_html(cert)` (all model-controlled text `html.escape`d, no `<script>`/raw-HTML sink; non-replayable, signing → M5); `render(spec, manifest_bytes, *, data_dir) -> RenderResult | None` (decodes the manifest from those bytes internally so verify/render/hash share one source → verify, if passed `vega_lite_json`→`render_svg`→`build_certificate`, else None). `build_certificate` takes the narrowed `table` (render() `cast`s `report.plotted_table` once — the coverage-clean M1.5a narrowing, no dead assert).
- **Accept**: passing spec → SVG + VCert whose four hashes equal the verifier's (`canon.hash_*`, manifest over raw bytes); a table/manifest edit flips the matching hash; renderer-enforced names present per mark/encoding; failing spec → None (SVG skipped, tripwire-proven); SVG carries no `<script>`/external ref; an adversarial filter literal (`</script><script>`, `<>&"'`, control chars + U+2028) is escaped in the badge, no live markup; gate green at 100% branch coverage.

#### M1.6d — render.py OPTIONAL offline interactive HTML   (OPTIONAL; isolated probe)
OPTIONAL, OFF the hash chain — M1 reaches IMPLEMENTED on M1.6c alone (see M1 close). Do M1.6d only when the window is comfortable, else SKIP it (record the reason) and proceed to review. Its one real risk is a vl-convert API lever that is NOT transcribe-confirmed → resolve it FIRST in an isolated scratch session (throwaway `.venv` script), record the confirmed lever, THEN implement — never probe inline in the implementing window (the M1.6-de-risk-overflow lesson).
- Probe (isolated, before code): pick the offline-embed lever on the pinned vl-convert build — `vegalite_to_html(json, bundle=True)` is offline but ships the editor/actions menu; `javascript_bundle("")` returns an EMPTY bundle (no `vegaEmbed` global, codex-confirmed 1.9.0.post1), so an `actions:false` custom template needs a NON-empty embedding snippet. Confirm one yields self-contained, menu-free (or accepted-menu) HTML with NO external `src`/`href`/CDN.
- Surface: `render_html(vega_lite_json) -> str` (offline HTML from the builder JSON string) + an optional `html` field on `RenderResult` (a coverage-safe bare add over M1.6c's struct, populated when HTML is requested).
- **Accept**: built Vega-Lite JSON → self-contained HTML with inline script ONLY (no external src/href/CDN/editor-or-actions unless explicitly accepted); off the cert hash chain; gate green at 100% branch coverage. OR: explicitly SKIPPED with the reason recorded, M1 proceeds.

### M1 close (when M1.6c DONE; M1.6d is OPTIONAL)
Set M1 IMPLEMENTED once M1.6c is DONE — M1.6d does NOT gate it (if not pursued, mark M1.6d SKIPPED with its reason). The next session runs MILESTONE-REVIEW (1M context), then planning of M2.
