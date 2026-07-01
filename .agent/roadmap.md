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
| **M1** | Trusted verifier core (headless) | 0,1·scaffold,2,3,4,5,6 | none — toolchain confirmed | **IMPLEMENTED** |
| M2 | Verifier API service (FastAPI) | 1·api,8 | none | UNPLANNED |
| M3 | Local model proposer + failure eval | 1·model,7,12 | Ollama + a local model | UNPLANNED |
| M4 | Open WebUI integration | 1·webui,9,10,11 | Open WebUI running | UNPLANNED |
| M5 | Formal + provenance hardening | 13,14 | none | UNPLANNED |
| M6 | End-to-end demo | 15 | full stack (M3+M4) | UNPLANNED |

Seed step 1 ("create the local stack") is split by gate: scaffold+data → M1, API → M2, model backend → M3, Open WebUI → M4. Plan each milestone only when it becomes active (prior one REVIEWED); M3/M4/M6 are gated — confirm preconditions functionally at their planning turn, deny-listed inputs off-limits.

---

## M1 — Trusted verifier core   (IMPLEMENTED)

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
| M1.6c | `render.py` provenance: VCert v0.1 badge + render() gate (recipe `.agent/m16c_render_design.md`) | DONE | 42% 83K/200K |
| M1.6d | `render.py` OPTIONAL offline interactive HTML view off the cert hash chain (`render_html` + `include_html`; recipe `.agent/m16d_render_design.md`) | DONE | 53% 106K/200K |

DONE-unit detail (M1.1–M1.6d: per-unit design + accept criteria) is realized in code + tests + `.agent/memory.md` lessons + git; recover the pre-implementation prose via `git log --grep "(M1[. ]"` / `git show <planning-commit>`. Every unit is DONE → M1 IMPLEMENTED; the git-held detail is fully available to the M1-review session (1M context), which reads every commit.

### M1 close
M1 is IMPLEMENTED — every unit DONE (M1.6d landed the OPTIONAL offline-HTML view off the cert hash chain). Next session runs MILESTONE-REVIEW (1M context): read every commit of the milestone, adversarially review the whole body (AGENTS.md criteria + cross-unit consistency), fix findings, delete the consumed `.agent/m16*_render_design.md` recipes, set M1 REVIEWED. Then PLANNING of M2.
