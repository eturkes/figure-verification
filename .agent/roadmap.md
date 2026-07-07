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
| **M4** | Open WebUI integration | 1·webui,9,10,11 | Open WebUI running — CONFIRMED at plan | **IN-PROGRESS** |
| M5 | Formal + provenance hardening | 13,14 | none | UNPLANNED |
| M6 | End-to-end demo | 15 | full stack (M3+M4) | UNPLANNED |

Seed step 1 ("create the local stack") is split by gate: scaffold+data → M1, API → M2, model backend → M3, Open WebUI → M4. Plan each milestone only when it becomes active (prior one REVIEWED); M3/M4/M6 are gated — confirm preconditions functionally at their planning turn, deny-listed inputs off-limits.

---

## M4 — Open WebUI integration   (IN-PROGRESS)

**Gate CONFIRMED at planning (functional)**: open-webui 0.10.2 installed project-local (`.venv-webui`,
py3.12 — 3.13 refused upstream) + served on 127.0.0.1:8080 → `/health` `{"status":true}`, first-signup
→ admin JWT, authed `GET /api/v1/configs/tool_servers` round-trip. Current `.webui-data/` = throwaway
gate-confirmation state; M4.3 wipes + re-provisions under the canonical env. All integration mechanics
re-verified against v0.10.2 SOURCE at planning (5-agent workflow + web) → facts/recipes = memory "## M4"
(several M2-era notes were stale: native FC now default, description-over-summary, ENABLE_API_KEYS rename,
persistent-config env trap). Plan-time probes stayed off the model backend (still down; M4.5 gates on it).

Design (seed steps 9/10/11 adapted to 0.10.2 reality; claim boundary UNCHANGED — Open WebUI + browser
join the trusted DISPLAY layer, the verifier stays sole authority; filter = heuristic guardrail, NOT a bound):
- GLOBAL (admin-registered, backend-called) tool server: headless-scriptable (`tool_ids:["server:<id>"]`),
  zero CORS (verifier stays CORS-free; browser-called user-level path REJECTED — never works headless,
  needs CORS + expose-headers + ~1MB socket cap). Tool surface allowlisted to proposeSpec via
  `function_name_filter_list`. (Overrides seed-9's user-level "Settings → Tools" suggestion.)
- Chart-in-chat = URL-embed (seed 10's HTMLResponse pattern, current form): verified chart HTML stored
  per plot_id, served by new `GET /chart/{plot_id}` (text/html + nosniff + `Content-Security-Policy:
  sandbox allow-scripts` — bare `sandbox` blocks the page's own Vega/height JS; the embedding iframe adds
  its own attr sandbox, no allow-same-origin), tool response adds `Content-Disposition: inline` + absolute
  `Location` on verified success → sandboxed iframe loads straight from the verifier (bare-metal loopback
  deployment assumption, POC_SCOPE will record it). Model context (source-settled, middleware.py:917):
  the Location variant REPLACES tool_result with a generic ui_component message UNLESS the body is a
  2-list `[_, context]` → M4.2 decides: wrapper `[null, verdict]` on verified success (model keeps the
  verdict; body shape changes, goldens/bench follow) vs plain body + generic context. Beats srcdoc-inline
  (our offline HTML inlines the whole Vega bundle — MBs per message). Fallback if the live probe sours on
  embeds: dedicated HTML-success/JSON-failure op.
- Weak-model tool calling = LEGACY FC (`DEFAULT_MODEL_PARAMS='{"function_calling":"legacy"}'`; native =
  the 0.10 default but needs backend `tools` support and never executes headless; task model = the same
  weak model). The 0.5B's tool-selection reliability = an OBSERVATION, claim discipline applies.
- Enforcement filter (seed 11) = repo-authored pure classifier + Filter outlet, REST-installed; outlet
  cannot rewrite API HTTP responses → enforcement asserted via `/api/chat/completed` + persisted-chat flow.

Units (M3 landed 45–81% of 200K). **M4.1 (chart surface) is SPLIT a→b→c**: its single-unit form (6 src
modules + 6 test files, design derived from scratch) overflowed one 200K window mid-tests — the one-module
right-sizing rule binds cross-LAYER too. Each sub-unit's recipe below is pre-derived from that overflow →
TRANSCRIBE it (exact signatures/constants given), don't re-derive; read only the named files + memory's
cited notes. Land a→b→c in order (b's store + c's route/capture depend leftward); each leaves the gate green.
- **M4.1a — offline-page height self-reporter** (OPEN; `render.py` + `tests/test_render.py`; leaf, isolated):
  add a module const `_HEIGHT_REPORTER` by `_EMBED_SNIPPET` (~render.py:245) = memory "## M4" embed rule as a
  fn, JS verbatim — `function vplotReportHeight(){parent.postMessage({type:"iframe:height",height:document.documentElement.scrollHeight},"*");}window.addEventListener("load",vplotReportHeight);new ResizeObserver(vplotReportHeight).observe(document.documentElement);`
  (Python str, assembled per ruff ≤100-col wrap); inject `f"<script>{_HEIGHT_REPORTER}</script>\n"` in
  `render_html` AFTER the `vegaEmbed(...)` script line, BEFORE `"</body>\n"`; docstring notes the self-report
  (trusted-template JS, off the cert hash chain, page stays self-contained). test_render.py: extend the HTML
  output-scan — reporter present (`iframe:height` + `ResizeObserver`) AND still self-contained (no
  `<script src` / external fetchable ref). Acceptance: gate green; offline HTML embeds the load +
  ResizeObserver height reporter posting `{type:"iframe:height",…}` and stays fully self-contained.
- **M4.1b — chart store + operator bound** (OPEN; `settings.py` + `store.py` + `app.py`[1 line] +
  `tests/test_service.py` + `tests/test_store.py`; the subtle LRU, isolated in its own window; pipeline
  UNTOUCHED). settings.py: add `_DEFAULT_HTML_CAP = 16` (chart pages ~MB; the 256 store_cap would balloon →
  own small bound), field `html_cap: int = _DEFAULT_HTML_CAP`, a `__post_init__` guard `html_cap < 1` →
  `"html_cap must be >= 1, got …"` (mirror store_cap), from_env
  `html_cap=int(env.get("VERIFIER_HTML_CAP", str(_DEFAULT_HTML_CAP)))`, extend the fail-closed-caps docstring.
  store.py: `__init__(self, cap, *, html_cap)` + html_cap guard + `self._html_cap` +
  `self._charts: OrderedDict[str, bytes]`; ADD (additive — leave put/certificate/spec + the refcount intact,
  NO _put_render refactor) `put_chart(plot_id, chart_html: bytes)` (lock: set, move_to_end, evict oldest while
  `len(_charts) > _html_cap`) + `chart(plot_id) -> bytes | None` (lock: get + move_to_end on hit); rewrite the
  docstring for THREE blobs (cert, spec, chart) + the SEPARATE chart LRU evicting independently (a chart MAY
  404 while its cert lives — cert authoritative, the accepted mixed state). app.py: `create_app` →
  `ArtifactStore(settings.store_cap, html_cap=settings.html_cap)` (only that line). test_service.py: add
  `VERIFIER_HTML_CAP` to `_VERIFIER_ENV`, `html_cap == 16` default, direct + from_env non-positive-html_cap
  rejects (match `"html_cap"`), html_cap in the from_env override. test_store.py: thread `html_cap=` through
  every `ArtifactStore(...)`; `test_rejects_nonpositive_html_cap` (`ArtifactStore(1, html_cap=bad)`, match
  `"html_cap must"`; disambiguate the existing cap test to match `"cap must"`); independent-eviction test
  (cap 8, html_cap 1: put A then B → `chart(A) is None` while `certificate(A)` lives, B present); re-put-A test
  (chart(A) restored, chart(B) now the evicted one). put_chart/chart are covered directly here (no
  route/producer yet — wired in M4.1c). Acceptance: gate green; store holds/serves chart bytes under html_cap,
  evicting independently of the cert LRU (mixed state + re-put pinned); non-positive html_cap rejected at
  store, Settings, and from_env.
- **M4.1c — chart capture + HTTP surface** (OPEN; `pipeline.py` + `app.py` + `openapi.py` +
  `schema/openapi.json` + `tests/test_service_render.py` + `tests/test_service_openapi.py` + optional
  `tests/test_service_propose.py`; mechanical wiring over a/b — all primitives exist). pipeline.py
  `render_outcome`: build HTML ALWAYS (`render.render(…, include_html=True)`), `chart_html = cast("str",
  result.html)`, after the existing `store.put(...)` add `store.put_chart(plot_id, chart_html.encode("utf-8"))`,
  return `html=chart_html if include_html else None`; docstring — HTML built+stored on EVERY verified render so
  GET /chart works from any path (propose incl.), `include_html` now governs ONLY the JSON-body copy
  (render.render(include_html=False) stays covered by test_render.py — verify). app.py: parameterize
  `_fetch_artifact(artifact_id, fetch, *, media_type="application/json", headers=None)` →
  `Response(payload, media_type=media_type, status_code=HTTP_200_OK, headers=headers)` (404 path unchanged →
  malformed/miss both stay uniform problem+json, NO CSP/html on 404); add
  `_CHART_HEADERS = {"content-security-policy": "sandbox allow-scripts"}` (bare `sandbox` blocks the page's own
  Vega + height JS; allow-scripts re-enables them; never allow-same-origin — memory "## M4"); add `chart_route`
  `@get("/chart/{plot_id:str}", operation_id="getChart", summary=…, sync_to_thread=False)` →
  `_fetch_artifact(plot_id, store.chart, media_type="text/html", headers=_CHART_HEADERS)`; register after
  `spec_route`; update the routes docstring + the `response_headers` comment (nosniff still rides the app
  default → the 200 carries text/html + nosniff + CSP = the three headers). openapi.py: add
  `_html_response(description)` (`content:{"text/html":{"schema":{"type":"string"}}}`), a `/chart/{plot_id}`
  path (getChart, `_id_parameter("plot_id")`, `{"200": _html_response(…), **not_found}`), fix the stale
  `_paths()` docstring ("The five documented operations" → "The documented operations"; already 6 pre-/chart);
  regen the golden (`openapi_document_text()` → `schema/openapi.json`). test_service_render.py: (1) round-trip
  — POST a good spec to `/verify-and-render?include_html=false`, `GET /chart/{plot_id}` → 200, body == the
  direct-render page (include_html=True) verbatim + the three headers (include_html=false PROVES the
  decoupling); (2) mixed state (`store_cap=2, html_cap=1`, two distinct renders): first plot's `GET /chart` 404
  while `GET /certificate` 200; (3) 404 uniformity — malformed + unknown-64-hex plot_id → 404 problem+json with
  NO content-security-policy header. test_service_openapi.py: the drift test auto-covers /chart parity; add a
  shape assert (200 text/html string; 404 → Problem). Optional test_service_propose.py: one assert — a
  successful propose's plot_id serves at `GET /chart` (the literal propose→chart acceptance; the
  verify-and-render round-trip already proves the mechanism). Acceptance: gate green; an include_html=false
  render still serves its page verbatim at `GET /chart/{plot_id}` with the three success headers; evicted
  (cert-alive mixed state) / unknown / malformed plot_id → uniform 404 problem+json without them; the OpenAPI
  doc + golden document `/chart` and the route-drift test passes.
- **M4.2 — tool-facing response headers + surface tuning** (OPEN): scratch fake-tool-server probe against
  the live Open WebUI → settle the Location-variant (model context + embed persistence; fallback decision
  lands here); `Settings.public_base_url` (`VERIFIER_PUBLIC_BASE_URL`, default derived `http://127.0.0.1:
  {port}`, validated in `__post_init__`); proposeSpec verified-success responses gain `Content-Disposition:
  inline` + absolute `Location`; wrapper decision EXECUTED (2-list `[null, verdict]` on verified success —
  or plain body if the probe favors generic context); op summary/description tuned for the model
  (description wins; concrete dataset examples); OpenAPI golden regen. Acceptance: gate green; probe
  verdict session-logged + header wiring pinned by tests; body shape change (if any) confined to
  verified-success responses — all other bodies byte-unchanged (existing suites prove it).
- **M4.3 — webui/ provisioning package** (OPEN): repo-root out-of-tree pkg wired like bench/model_backend
  (mypy files + isort first-party, coverage-excluded, unshipped); canonical env set + launcher + IDEMPOTENT
  bootstrap script (signup→JWT; tool-server registration — TOOL_SERVER_CONNECTIONS env probe first; REST
  fallback = re-POST each boot OR persistent-config ON, since config REST writes don't survive restart
  under persistent-config-off; legacy-FC default + task model; `function_name_filter_list=["proposeSpec"]`); smoke = `/ready`
  + model enumerated from model_backend stub-or-live + tool ops fetched into the registry; README (three-
  service run recipe, bench/README pattern); `.webui-data` wiped + re-provisioned under the canonical env.
  Acceptance: gate green; bootstrap re-runnable (second run = no-op) from a clean `.webui-data`; smoke passes.
- **M4.4 — enforcement filter** (OPEN): `webui/` filter module — pure chart-like classifier (matplotlib/
  plotly/altair/seaborn fences, `<svg`, vega-lite JSON, mermaid, data-URI images ↔ prose + verified-embed
  negatives) + Filter class (outlet rewrites unverified chart-like assistant output, logs what it blocked);
  bootstrap installs+activates globally; `tests/test_webui_*.py` on the bench-harness pattern (pure logic,
  REST-shape pins); headless outlet assertion via `/api/chat/completed`; POC_SCOPE gains the Open WebUI
  section (trusted display, heuristic filter, global-server no-CORS posture, loopback deployment).
  Acceptance: gate green; classifier corpus fully pinned; one live `/api/chat/completed` round-trip blocks
  a chart-like reply and passes a prose reply.
- **M4.5 — live E2E + evidence** (OPEN; GATED: NPU model_backend live — M3 recipe, confirm functionally):
  full three-service stack; headless legacy-FC chat with `tool_ids` → tool executed (verifier artifacts
  exist + verdict context in the reply); persisted-chat flow → embed recorded; chromiumfish capture of the
  chat showing the sandboxed verified chart; filter on/off differential on a direct-chart prompt; record
  observations (task-model tool-selection rate, embed behavior) with claim discipline; close M4 →
  IMPLEMENTED. Acceptance: every seed-9/10/11 exit criterion demonstrated or its miss recorded honestly.

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
