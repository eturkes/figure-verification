# figure-verification — roadmap

Local "verified-plot" PoC. A weak local LLM only PROPOSES a restricted JSON chart spec (VPlot); a separate trusted verifier deterministically recomputes the plotted data from the source CSV, runs structured checks, blocks charts whose spec, encoding, policy, or dataset binding fail those checks, and renders only verified charts with a provenance certificate (dataset hash, spec hash, plotted-table hash, passed checks).

- **Scope-seed**: `.agent/outline.md` — the original outline as 16 verbatim seed steps "Milestone 0..15" (commit `9d09ecb`). The ledger below maps each routine-milestone `M<m>` to those steps; read the relevant seed step on demand when planning a milestone.
- **Stack**: `.agent/memory.md` (Stack + M1 lessons) — researched SOTA, deliberately overriding the outline's human-popular defaults. Determinism/trust invariants live in `VPlot_SEMANTICS.md` + `POC_SCOPE.md` + module docstrings, locked by the suites.
- **Data-flow (trust spine)**: the untrusted model proposes ONLY a VPlot spec (transforms + encoding + declared `dataset.hash`) — never plotted values. The verifier recomputes ALL plotted data; the renderer inlines only that. So lies needing model-supplied data (the seed's "plots a value ≠ recomputation") are impossible by construction, not checks; checks target spec/encoding/policy/dataset-binding consistency. (The seed's `aggregates_match_recomputation` example carries a model-supplied value — a seed inconsistency, resolved here.)
- **Modest claim** (hold the line): verified = {validated spec, the independently recomputed plotted table, the emitted Vega-Lite inlining only that table, the provenance badge} are mutually consistent and the checks passed. Trusted, NOT verified (TCB): `vl-convert`/Vega, SVG rasterization, browser, pixels — trusted to render verified data faithfully, not proven to.
- **Quality gate** (M1.1 wires it; every WORK-UNIT VERIFY runs it, all green, touched scripts exit clean): `ruff format --check .` · `ruff check .` · `mypy` · `pytest` — all via `uv run --locked` (the lockfile, not a newer floor-satisfying release, pins the gate).

## Milestone ledger

| M | Title | Seed steps | Gate | Status |
|---|-------|-----------|------|--------|
| M1 | Trusted verifier core (headless) | 0,1·scaffold,2,3,4,5,6 | none — toolchain confirmed | REVIEWED |
| M2 | Verifier API service (Litestar) | 1·api,8 | none | REVIEWED |
| M3 | Local model proposer + failure eval | 1·model,7,8·propose,12 | local OpenAI-compat backend — OpenVINO (confirmed M3.1a; was "Ollama") | REVIEWED |
| **M4** | Open WebUI integration | 1·webui,9,10,11 | Open WebUI running | **UNPLANNED** |
| M5 | Formal + provenance hardening | 13,14 | none | UNPLANNED |
| M6 | End-to-end demo | 15 | full stack (M3+M4) | UNPLANNED |

Seed step 1 ("create the local stack") is split by gate: scaffold+data → M1, API → M2, model backend → M3, Open WebUI → M4. Plan each milestone only when it becomes active (prior one REVIEWED); M3/M4/M6 are gated — confirm preconditions functionally at their planning turn, deny-listed inputs off-limits.

---

## M3 — Local model proposer + failure eval   (REVIEWED — closed)

Delivered the UNTRUSTED weak proposer in front of the M1/M2 verifier — claim boundary UNCHANGED
(the model supplies NO data values; verify recomputes the whole plotted table + rebinds the CSV
by hash; POC_SCOPE "## Model proposer" holds the contract). Pieces: `model_backend/` (repo-root
Litestar+uvicorn OpenAI-`/v1` wrapper over the installed `openvino_genai.LLMPipeline`, NPU-served
local INT4_SYM Qwen2-0.5B re-export — the NPU switch landed mid-milestone as a direct task;
hardware-gated, coverage-excluded, unshipped) → `service/model_client.py` (async `propose_spec` →
raw reply bytes, never VPlot-decoded client-side) → `POST /propose-spec` (typed body → reply →
`decode_stage` → dataset-name PIN at decode time → `verify_decoded` → `render_outcome`; the
pipeline split into those reusable seams) → repo-root `bench/` (100-prompt failure eval + the
deterministic two-corpus guarantee; classifiers/digests/exit-code locked by
`tests/test_bench_harness.py`). Error split: every extracted reply rides a 200 verdict (decode
failure = the metered model failure); 404 unknown dataset / 503 unreachable / 502 unusable reply
OR off-request pin / 400/415/405 transport misuse = problem+json; a broken trusted manifest = the
500 the model cannot provoke. Backend pick (OpenVINO over the seed's "Ollama", user-confirmed),
device/model/run facts + rejected-finding rationale: memory M3 + `bench/README.md`.
680 tests / 100% branch. Unit trail + per-unit context-usage + codex-review follow-ups:
`git log --grep "(M3[. ]"` (+ `babe6da`/`f53bd0c`/`5936cad`, the NPU switch). Units landed at
45–81% of 200K.

**Eval evidence (live NPU: the M3.4b run + the M3-review re-run that validated the good-corpus
leg).** Served `Qwen2-0.5B-Instruct-int4-sym-ov` (NPU, greedy temp=0, 100 fixed ordered prompts;
recipe `bench/README.md`; reports/ gitignored — these numbers are the durable record; exit 0
both runs). **GUARANTEE CONFIRMED**: bad corpus 18/18 blocked (`false_accept=0`) AND good corpus
10/10 accepted (`false_reject=0`; leg added at M3 review — without it a reject-everything
verifier would satisfy the bad bound vacuously), 0 transport errors, both corpora
size+identity-digest pinned. **Observations** (n=100 HTTP-200 verdicts; NOT a bound):
`tool_call=0 json_validity=0 verified_render=0`; buckets `schema=1.0 semantic=0 policy=0`;
faults `off_request=0 upstream_fault=0 harness_error=0`; top failing check `spec.decode` (100).
Reply shape isolates WHY: `fenced=97 bare_object=2 other=1 empty=0`, de-fenced only 24/100 parse
as JSON — the weak proposer is 100% unreliable at strict VPlot JSON, the dominant failure
SYNTACTIC (markdown fence). The review re-run's summary reported an exact repeat of every
model-side number (independent server processes, same device+config — consistent with the
per-(device,config) determinism design; session-logged only, like all eval numbers here). So the
untrusted model EXERCISES the pipeline without weakening it — the deterministic verifier bound
is untouched by a fully-failing proposer.

---

## M2 — Verifier API service   (REVIEWED — closed)

Delivered `verifier.service` — the M1 library wrapped in a local Litestar + uvicorn HTTP
transport (one worker, 127.0.0.1 by default), adding no verification trust of its own (one-way dep:
the core never imports the service). Pieces: `settings.py` (frozen operator config from
`VERIFIER_*` env, fail-closed bound guards) → `app.py` (factory + 6 routes, raw-body-first
POSTs so `decode_spec` stays authoritative, nosniff app default, two problem+json exception
handlers) → `pipeline.py` (decode → resolve manifest → load → `checks.verify`, reused by
render) → `models.py` (Verdict / RenderVerdict with `verified: Literal[True]` / RFC-9457 Problem)
→ `store.py` (bounded LRU over renders + refcounted shared-spec map) → `openapi.py`
(hand-authored OpenAPI 3.1 doc, served at `/schema/openapi.json`, golden-pinned). Error split
(POC_SCOPE "## Service boundary"): every verification outcome incl. decode failure = 200
verdict; only transport misuse / operator-config fault = problem+json 4xx/5xx (its cause
logged by the handler, withheld from the caller). Claim boundary UNCHANGED — transport around
the verifier; POC_SCOPE holds the modest claim + TCB line verbatim, VPlot_SEMANTICS untouched.
616 tests / 100% branch, incl. a live-socket smoke over real TCP from a foreign cwd. Reusable
transport recipe (for M4's added endpoints) + probed Litestar facts live in `.agent/memory.md`
Stack; unit trail + per-unit context-usage + the review pass: `git log --grep "(M2[. ]"`.
Units landed at 46–87% of 200K.

---

## M1 — Trusted verifier core   (REVIEWED — closed)

Delivered the headless library `verifier`, gate-free, exercised entirely by pytest: schema decode gate (`schema.py` + exported JSON Schema golden) → canonical forms + 4 provenance hashes (`canon.py`) → typed ingest (`ingest.py`/`errors.py`) → Decimal-exact evaluator (`eval.py`) → verification spine + encoding/label checks (`checks.py`) → Vega-Lite positive-allowlist builder + SVG + VCert v0.1 badge + `render()` gate + optional offline HTML (`render.py`). 480 tests / 100% branch, dual-engine DuckDB oracle parity, golden corpus (10 good / 18 bad). Unit trail, per-unit context-usage, and the review pass: `git log --grep "(M1[. ]"`.

**Right-sizing rule (M1 evidence; binds M2+ unit sizing AND planning turns)**: size a unit at ~one module + its tests; an independent oracle or a property/fuzz layer is its OWN unit, never bundled. A unit whose DESIGN alone overflows a 200K window is mis-sized → split it. A unit that overflows in IMPLEMENTATION despite a complete recipe is OVER-deriving, not under-specified → pre-derive a gate-validated transcription recipe (`.agent/*_design.md`), TRANSCRIBE not re-derive, reach the gate early, and salvage-continue (overflow ≠ bad work — a completed-but-overflowed unit's gate-green output stands; recipes deleted once consumed). Isolate native-dep probes to scratch sessions — probing in the implementing window overflowed twice. M1 units landed at 39–88% of 200K under this rule.
