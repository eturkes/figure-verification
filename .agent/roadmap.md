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
| **M3** | Local model proposer + failure eval | 1·model,7,8·propose,12 | local OpenAI-compat backend — default OpenVINO, PROVISIONAL (was "Ollama") | **IN-PROGRESS** |
| M4 | Open WebUI integration | 1·webui,9,10,11 | Open WebUI running | UNPLANNED |
| M5 | Formal + provenance hardening | 13,14 | none | UNPLANNED |
| M6 | End-to-end demo | 15 | full stack (M3+M4) | UNPLANNED |

Seed step 1 ("create the local stack") is split by gate: scaffold+data → M1, API → M2, model backend → M3, Open WebUI → M4. Plan each milestone only when it becomes active (prior one REVIEWED); M3/M4/M6 are gated — confirm preconditions functionally at their planning turn, deny-listed inputs off-limits.

---

## M3 — Local model proposer + failure eval   (IN-PROGRESS — 4 units enumerated)

Adds the UNTRUSTED weak model that ONLY proposes VPlot specs; the M1/M2 verifier recomputes + blocks as before. The model EXERCISES the existing claim, never weakens it — claim boundary UNCHANGED (POC_SCOPE modest claim + TCB line hold; VPlot_SEMANTICS untouched, no DSL change). Seed steps 1·model,7,8·propose,12.

**Backend — PROVISIONAL (OpenVINO), pending user confirm; reversible (rescopes only M3.1).** Gate wording revised "Ollama"→"local OpenAI-compatible backend". Picked over Ollama because this Lunar Lake container is provisioned+verified for OpenVINO GPU+NPU while Ollama's Intel-GPU support is experimental/CPU-only here (AGENTS.md SOTA-fit; CLAUDE.local.md). Switch to Ollama later = point M3.2-4's `VERIFIER_MODEL_BASE_URL` at Ollama's `/v1` (M3.2-4 are backend-agnostic OpenAI-compatible; only M3.1 changes).
- Serve = **DIY tiny Litestar+uvicorn wrapper** around the INSTALLED `openvino_genai.LLMPipeline`, OpenAI-compatible `POST /v1/chat/completions` + `GET /v1/models`. The ONLY path reusing the verified 2026.2 GenAI + pinned-IGC accel farm — OVMS / vLLM-openvino / community wrappers / ANY pip `openvino*` wheel bundle a 2nd OV stack that SHADOWS the PYTHONPATH accel build + bypasses the IGC farm → GPU breaks (LANDMINE: keep strictly to the installed genai; `openvino_genai` stays PYTHONPATH-provided, accel env sourced, NOT a pyproject dep). Wrapper lives OUTSIDE `src/verifier/` (untrusted backend ≠ verifier; e.g. `model_backend/`) → outside the 100%-branch coverage source (like tests/oracle.py). Device default `AUTO:GPU,CPU` (sub-1s TTFT, no static-shape/precision landmines); NPU = perf/W opt-in later (int8-ov CRASHES on NPU, group-wise vs channel-wise int4, ~90s cold compile, greedy/multinomial only). Blocking/stateful `generate()` → `asyncio.to_thread` + one lock (single in-flight).
- Model = `OpenVINO/Qwen2-0.5B-Instruct-int4-ov` (primary weak proposer; ready -ov, Apache-2.0, ungated; genuinely unreliable at strict JSON = strong failure signal). Diversity alts: Qwen2.5-Coder-0.5B-int4-ov (almost-valid JSON), Qwen2.5-1.5B-int4-ov (less-unreliable tier — calibrates ACCEPT of real-but-imperfect), SmolLM2-360M (optimum-cli convert; non-Qwen modes).
- Client = **httpx** (add to `[project].dependencies`; today only transitive via TestClient). Verifier parses the reply ITSELF (`choices[0].message.content` → raw bytes → `decode_spec`), NOT the openai client (its pydantic coercion HIDES the malformed payload that IS the signal). Route = `httpx.AsyncClient` (async); harness = sync httpx (deterministic).

**Error split (new — POC_SCOPE service boundary):** model-backend unreachable/timeout = operator/infra UPSTREAM fault → 502/503 `application/problem+json` (cause logged+withheld, reuse the M2 Exception-handler + nosniff chokepoint); a model that RESPONDS, even with garbage → its bytes → `decode_spec` → 200 Verdict (metered model-failure mode).

**Units** (each ~one module+tests, M2's 46-87%/200K band; M3.1 native-dep → scratch-probe→recipe→transcribe per the right-sizing rule):
- **M3.1 — backend standup (GATE-resolution).** DIY wrapper serving the weak model on GPU over `/v1/chat/completions`+`/v1/models`; scratch-probe `openvino_genai` device + model-pull FIRST (isolated session), bake a gate-validated `.agent/m3_1_design.md` recipe, transcribe; handle the untyped native import under mypy. Acceptance: a smoke test confirms the verifier's httpx client gets a chat completion (a candidate, possibly-malformed VPlot JSON) from the served weak model — the functional gate. Deny-listed inputs off-limits.
- **M3.2 — `model_client.py` + prompt + Settings.** `propose_spec(request,settings)->bytes`: seed-7 prompt (system JSON-only + allowed marks/transforms + explicit-filters/units rules; user_request; dataset schema summary from the TRUSTED manifest; first-N sample rows from the TRUSTED CSV under `settings.data_dir`) → POST `{base_url}/chat/completions` `{model,messages,temperature:0}` → strict-decode reply (internal `_ChatResponse/_Choice/_Message`) → content → raw UTF-8 bytes (mirrors the pipeline's `raw: bytes`). New `VERIFIER_MODEL_{BASE_URL,NAME,TIMEOUT,SAMPLE_ROWS}` validated in `Settings.__post_init__` (field defaults share from_env consts). Mock-tested (patch the shared httpx module object). Gate-INDEPENDENT code.
- **M3.3 — `/propose-spec` endpoint.** `ProposeRequest`(user_request,dataset_name; frozen/kw_only/forbid_unknown_fields — dataset_name selects the trusted manifest/CSV, sample rows derived server-side NOT caller-trusted), `ProposeResult`(raw model text + reused Verdict|RenderVerdict). `propose_spec_route` (`@post('/propose-spec',operation_id='proposeSpec',status_code=200)`, `_require_json` 415, async model call, `sync_to_thread` verify/render, upstream-fault→502/503) registered in `route_handlers`; feeds raw bytes to EXISTING `verify_and_render`/`verify_only` (ZERO pipeline change — decode_spec stays authoritative). Add `proposeSpec` to `openapi.py` (op+summary mirrored on the decorator; hand-derive if it returns the `Literal[True]`-bearing union) → regen `schema/openapi.json` golden + external-contract test. POC_SCOPE "## Model proposer" error-split note. Mock-tested (patch model_client). Gate-independent code.
- **M3.4 — failure-oriented eval harness (seed 12).** `bench` module OUTSIDE `src/` (dodges the `verifier.eval` name collision + the 100%-branch gate, like tests/oracle.py). ≥100 prompts (5×20: normal/ambiguous/adversarial/bad-aggregation/hidden-filter) → propose→verify(+render) → JSON report {tool_call_rate, model_json_validity_rate, schema/semantic/policy_failure_rate, verified_render_rate, false_accept_rate} + ranked top-5 model failure modes. Reproducible: greedy/temp=0 + fixed seed. The false_accept=0 GUARANTEE = the deterministic verifier on the 18-bad corpus (already locked by M1 checks + M2 service-verify) — model-driven rates are OBSERVATIONAL statistics, not guarantees (POC_SCOPE note). Gated on M3.1 (live model).

**Sequencing:** M3.1→M3.2→M3.3→M3.4. M3.1 first resolves the gate + de-risks the native dep (its feasibility gates the milestone; the eval is impossible without it). M3.2/M3.3 are mock-testable (gate-independent) → reorder before M3.1 only if the gate stalls. M3.4 hard-gated on M3.1. Seams (finder-confirmed vs live tree): `app.py` `route_handlers` list + `_require_json` + `state['settings'|'store']`; `models.py` struct patterns; `pipeline.py` `verify_only`/`verify_and_render(raw,...)`; `openapi.py` component assembly + golden. Conventions binding every unit: SPDX header, frozen+kw_only (+forbid_unknown_fields for ProposeRequest), raw-body discipline, error-split, nosniff, `uv run --locked` gate (ruff · ruff format · mypy --strict · pytest · 100% branch).

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
