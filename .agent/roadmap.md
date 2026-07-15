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

Seed step 1 ("create the local stack") is split by gate: scaffold+data → M1, API → M2, model backend → M3, Open WebUI → M4. Plan each milestone only when it becomes active (prior one REVIEWED); M3/M4/M6 are gated — confirm preconditions functionally at their planning turn; bring generated/heavy inputs into scope only when the gate needs them.

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
  deployment assumption, POC_SCOPE will record it). Model context (source-SETTLED, middleware.py:917-931):
  the Location variant REPLACES tool_result with a generic ui_component message UNLESS the body is a
  2-list `[_, context]`, `str()`-ified to the model → DECIDED (memory "## M4" Location-variant embed):
  verified-success body = `[ProposeResult, summary_str]` — the model reads the lean summary string,
  direct/bench clients read `body[0]`, goldens/bench follow. Beats srcdoc-inline (our offline HTML inlines
  the whole Vega bundle — MBs per message); the HTML rides the Location URL GET /chart serves, never the
  body. Live confirmation of the embed rides M4.5's E2E.
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
- **M4.1a — offline-page height self-reporter** (DONE, 59% 200K): `render.py` `_HEIGHT_REPORTER`
  trusted-template JS (`postMessage {type:"iframe:height",…}` on load + ResizeObserver) appended as
  `render_html`'s LAST `<script>`, off the cert hash chain; presence + self-containment pinned in
  `tests/test_render.py`. Recipe consumed → git (`git log --grep "(M4.1a"`).
- **M4.1b — chart store + operator bound** (DONE, 54% 200K): `Settings.html_cap` (`VERIFIER_HTML_CAP`,
  default 16, fail-closed `>= 1` guard mirroring store_cap, both construction paths) + `ArtifactStore` second
  LRU — `put_chart`/`chart` over a `_charts` OrderedDict capped at html_cap, evicting INDEPENDENTLY of the
  render/cert LRU (BOTH mixed states pinned by direct tests: chart-gone-cert-lives AND cert-gone-chart-lives,
  the latter added beyond the recipe to back the "both mixed states" docstring claim; + re-put recency cycle).
  `create_app` threads `html_cap=`; pipeline UNTOUCHED (chart producer + GET route = M4.1c). Recipe consumed →
  git (`git log --grep "(M4.1b"`).
- **M4.1c — chart capture + HTTP surface** (DONE, 70% 200K): `render_outcome` builds the offline page on
  EVERY verified render (`render(include_html=True)` + `store.put_chart`), `include_html` now gating ONLY the
  JSON-body copy; `_fetch_artifact` parameterized (`media_type` + `headers`) as the one seam serving the JSON
  artifacts AND the `GET /chart/{plot_id}` text/html page under `_CHART_HEADERS` (CSP `sandbox allow-scripts`;
  a 404 carries neither CSP nor html — app-default nosniff rides it); openapi.py `_html_response` + `/chart`
  path + golden regen. The chart is stored on every verified render regardless of entry route
  (verify-and-render OR propose — the shared seam), served until chart-LRU eviction. Recipe
  consumed → git (`git log --grep "(M4.1c"`).
- **M4.2 — proposeSpec tool-facing response + surface tuning** is SPLIT a→b→c: its single-unit form
  (settings knob + app wrapper + propose/bench test ripples + OpenAPI + golden, atop an OWUI source recon)
  overflowed one 200K window — the one-module right-sizing rule again, the recon compounding it. The
  Location-variant is SETTLED from source (memory "## M4" Location-variant embed bullet = verdict + wrapper
  decision) → NO re-probe; TRANSCRIBE the recipes below, read only the named files + the cited memory
  notes. Land a→b→c in order (b's Location header needs a's `public_base_url`; c documents b's body shape);
  each leaves the gate green. Live confirmation of the embed rides M4.5's E2E, not here.
- **M4.2a — `Settings.public_base_url` operator knob** (DONE, 57% 200K): `public_base_url: str | None`
  (env `VERIFIER_PUBLIC_BASE_URL`) = the absolute browser-facing chart-Location origin (M4.2b), separate
  from `host` the bind address; unset → derive `f"http://127.0.0.1:{port}"` via `object.__setattr__`
  (frozen-struct init derivation — VERIFIED in a msgspec `__post_init__`: sets the slot, `hash()` +
  frozen-ness intact). `__post_init__` (first guard) requires a CLEAN origin `scheme://host[:port]` on
  both construction paths — http(s) scheme, present host, ASCII authority allowlist, exact-origin
  roundtrip, parseable port — all inside one `try/except` wrapping `urlparse` for a uniform fail-closed
  `public_base_url` message. Codex-review HARDENED the initial roundtrip-only validator (added the
  allowlist + `parsed.hostname` + the urlparse-wrap, dropped the redundant `isspace` scan) to close the
  urlparse-vs-WHATWG-browser gaps — `\` path-injection, userinfo host-confusion, empty-host, control/
  percent/unicode authority bytes; the reusable lesson + kept-benign cases live in `.agent/memory.md`.
  Recipe + hardening consumed → git (`git log --grep "(M4.2a"`).
- **M4.2b — proposeSpec verified-success embed wrapper** (DONE, 61% 200K): `propose_spec_route` →
  `ProposeResult | Response[bytes]`; a verified render answers the OWUI Location-variant embed —
  `msgspec.json.encode([ProposeResult, summary])` under `content-disposition: inline` +
  `location: {public_base_url}/chart/{plot_id}` (app-default nosniff rides the Response, not re-added);
  `summary = f"Verified chart for {dataset}: all {N} checks passed."` (clean STRING = the model's
  context). Non-verified/4xx/5xx bodies byte-identical (`return result` unchanged, existing suites prove
  it). `bench/harness.py` `_decode_propose_result` discriminates the embed among 200s by the `location`
  header → `tuple[_RespProposeResult, str][0]`, else the bare object (downstream tally unchanged). Test
  proves the `public_base_url` knob drives the Location via a custom-base scoped client. `openapi.py`
  untouched — the doc regen for the new 200 shape is M4.2c. Recipe consumed → git (`git log --grep "(M4.2b"`).
- **M4.2c — OpenAPI tuning + golden regen** (DONE, 48% 200K): `openapi.py` — proposeSpec gained a
  model-facing `description` (0.10.x description-over-summary; names `user_request`/`dataset_name`, with
  concrete sales.csv/weather.csv examples), and its verified-success 200 widened to
  `anyOf[ProposeResult object, bounded [ProposeResult, string] 2-tuple (prefixItems + min/maxItems 2)]`
  (anyOf-not-oneOf house style; the array arm = the M4.2b `[result, summary]` embed body). Golden
  `schema/openapi.json` regenerated (byte-match test green). External-contract test extended: the real
  `[ProposeResult, summary]` array validates against the 200 anyOf, plus two mutation-verified non-vacuity
  negatives (a 3rd element trips maxItems, a non-string element1 trips prefixItems[1]) pinning the tuple
  bounds. Description scoped to `openapi.py` only — the app.py route-level summary is an inert mirror under
  `openapi_config=None`. Recipe consumed → git (`git log --grep "(M4.2c"`).
- **M4.3 — webui/ provisioning package** is SPLIT a→b→c→d→e: its single-unit form (6 modules — settings +
  client + bootstrap + model_stub + __main__ + __init__ — plus tests + README + a live 3-service smoke,
  atop a live OWUI-behavior probe) overflowed one 200K window — the cross-LAYER one-module rule again, the
  probe compounding it. The probe is now SETTLED LIVE (memory "## M4" Provisioning-SETTLED-LIVE bullet =
  the 0.10.2 verdict: `Config.get` env-over-DB, TOOL_SERVER_CONNECTIONS registration, signup-or-signin
  idempotency, `/ready` + `/api/models` + `/api/v1/tools/` readback) → NO re-probe; TRANSCRIBE the recipes
  below, read only the named files + the cited memory notes (M4 "Launch env" + "Provisioning-SETTLED-LIVE"
  carry every env var, the connection-JSON shape, and each endpoint). webui/ = repo-root out-of-tree pkg
  (mypy `files` + isort first-party = a's one-line pyproject wiring; coverage-excluded, so its tests are a
  bench-style feedback loop NOT a 100% gate; unshipped); provisioner knobs = `WEBUI_PROVISION_*` env,
  distinct from the OWUI env it EMITS. All code imports only gate-venv deps (msgspec/httpx/litestar/uvicorn)
  → the pkg gate-checks hardware-free; the `.venv-webui` open-webui binary is EXEC'd, never imported. Land
  a→b→c→d→e in order (b imports a's Settings; c = the hardware-free stub; d's CLI wires a+b+c; e
  live-smokes a+b+c+d); a–d each leave the gate green, e adds the live evidence. Live embed/E2E stays M4.5.
  c was RE-SPLIT from a former single c (stub + __main__ CLI + README, 2 modules): it went green but
  overflowed at CLOSE — webui units run context-HOT (a/b each ONE module landed 75-77%; the dense
  OWUI-behavior memory notes + dep-file reads inflate them), so a webui unit = STRICTLY one module + its tests.
  d then overflowed too (reads to 56% — its recipe named ~10 source files — then writing 3 deliverables +
  gate iterations tipped the window) → d's recipe is now SELF-CONTAINED (a consumed-surface card inline, opens
  NO webui source) and its README moved to e (authored against the verified live launch). The lesson binds
  every remaining webui unit: bake the consumed surface INTO the recipe so the unit opens no source.
- **M4.3a — `webui/settings.py` canonical-env container + wiring** (DONE, 75% 200K): frozen `Settings`
  (WEBUI_PROVISION_* `from_env`, `__post_init__` bounds port 1..65535 / non-empty secret+email+pw /
  finite-positive timeouts — two loops, distinct `text`/`seconds` names per the mypy landmine) emitting the
  hermetic OWUI `launch_env()` (`_FIXED_ENV` static toggles + 5 derived keys) + `tool_server_connections()`;
  pyproject wired (`webui` → isort known-first-party + mypy files); `tests/test_webui_settings.py` (20 tests,
  coverage-excluded bench-style loop). Deliberate refinements vs recipe (both verified at open-webui 0.10.2
  source, not a behavior re-probe): all 5 generation toggles default-True → pinned off incl.
  `SEARCH_QUERY_GENERATION` (memory listed 4); `DATA_DIR` emitted ABSOLUTE (`str(data_dir.resolve())` — OWUI
  `env.py:216` resolves a relative one vs ITS own cwd, so absolute keeps state in `.webui-data` regardless of
  exec cwd; `.resolve()` reads cwd not os.environ, so launch_env stays assertable via a recomputed resolve);
  minimal `webui/__init__.py` package marker landed HERE (regular pkg like model_backend/bench, needed for
  mypy+import gate-green) → stays as-is (d's __main__ is the entry point; no CLI exports needed). Codex-review (xhigh) HARDENED (all verified at
  0.10.2 source): pinned the auth/bootstrap surface in `_FIXED_ENV` (`WEBUI_AUTH`/`ENABLE_LOGIN_FORM`/
  `ENABLE_PASSWORD_AUTH` on, `ENABLE_SIGNUP` off, `WEBUI_ADMIN_EMAIL`+`WEBUI_AUTH_TRUSTED_EMAIL_HEADER` empty
  — else ambient seizes the boot admin (main.py:326) or disables auth); validated emitted URLs http(s)+host
  (empty `model_backend_url` ⇒ api.openai.com fallback config.py:335, empty `verifier_url` ⇒ dropped tool
  server — both fail OPEN); added `child_env()` = curated base-env passthrough + `launch_env()` = the real
  hermetic boundary (a bare `{**os.environ,**launch_env()}` leaks `HTTP_PROXY` via aiohttp trust_env + any
  unpinned axis), corrected the launch_env purity + hermetic docstrings; closed runtime type-strictness by documenting
  `from_env` as the coercion boundary in the Settings docstring (rejected the add-type-guards option —
  msgspec skips runtime type checks, sibling model_backend convention). Recipe + review consumed → git (`git log --grep "(M4.3a"`).
- **M4.3b — `webui/client.py` REST client + `webui/bootstrap.py` smoke** (DONE, 77% 200K):
  `WebUIProvisionError(RuntimeError)` + `WebUIClient(http: httpx.Client, settings)` over the
  Provisioning-SETTLED-LIVE surface — `wait_ready` (poll `/ready` to `httpx.codes.OK` or the
  `ready_timeout` `time.monotonic` deadline, `httpx.HTTPError` = still-booting, raise on timeout),
  `authenticate` (signup→signin fallback on ANY non-200, both-non-200 / empty-token fail-closed,
  stores + returns the JWT), `model_ids` (`{data:[…]}` envelope), `tool_server_ids` (BARE
  `list[ToolUserResponse]`, `server:`-filtered); readbacks decode LOUD via loose msgspec structs (no
  swallow, so a live shape drift surfaces). bootstrap.py: `SmokeResult` (frozen/kw_only, `ok` =
  model_enumerated ∧ tool_registered), `smoke`/`run_bootstrap` over a structural `_Provisioner`
  Protocol. `tests/test_webui_client.py` (20 tests, coverage-excluded): `httpx.MockTransport` pins
  the wire shapes (signup-200/signin-fallback/both-fail/empty-token, wait_ready 200/retry/timeout,
  the `data[]` vs BARE-array parse + `server:` filter, bearer wiring) + a pure `_Provisioner` fake
  pins the wait→auth→smoke order, ok truth table, and idempotency. Deliberate vs recipe: `_auth_headers`
  guards authed calls (raise before authenticate); the `_Provisioner` Protocol types the recipe's
  "fake client" under mypy --strict; `wait_ready` timeout test monkeypatches the shared `time` module
  for a real-time-free deterministic timeout; `_TOOL_SERVER_ID_PREFIX="server:"` single-sourced in
  client.py (bootstrap imports it). Recipe consumed → git (`git log --grep "(M4.3b"`).
- **M4.3c — `webui/model_stub.py` hardware-free OpenAI /v1 stub** (DONE, 62% 200K): the M4.3e-smoke
  stand-in with NO NPU. `create_app(model_id)`/`list_models`/`chat_completions` REUSE
  `model_backend.models` (msgspec only, no openvino — imports resolve repo-root; gate ran it hardware-free)
  ⇒ OWUI sees the SAME /v1 wire SHAPE as the live backend (routes, status, object literals, msgspec
  field order); chat builds the same response STRUCT with synthetic VALUES (fixed `_STUB_REPLY` INERT
  until M4.5, word-count usage, always finish `stop`). `serve(settings)` = urlparse `model_backend_url`,
  fail loud unless it is `http://<host>:<port>/v1` the stub can bind+serve (rejects non-http, non-`/v1`
  path, missing/non-numeric port — Settings only checks scheme+host), else `uvicorn.run(…, workers=1)`.
  NO own `main()` (d's __main__ dispatches). Tests (`tests/test_webui_model_stub.py`, coverage-excluded,
  Litestar `TestClient`, no socket) pin the full /v1 key-sets + OWUI extra-field tolerance + serve
  default-bind + unservable-URL rejects (monkeypatch the SHARED `uvicorn`). Recipe consumed → git
  (`git log --grep "(M4.3c"`).
- **M4.3d — `webui/__main__.py` CLI dispatch** (DONE): commands
  `python -m webui {serve,bootstrap,stub}` wire M4.3a–c without importing Open WebUI: `serve`
  validates the binary
  then shell-free `execve`s it with `Settings.child_env()`; `bootstrap` uses the bounded HTTP client
  and exits 0 only for a complete smoke result (provision errors + partial results → 1); `stub`
  delegates to the hardware-free backend. Tests pin all parser/dispatch branches, one shared Settings
  instance, exact exec path/vector/hermetic env, missing-binary failure, and bootstrap codes; module
  import + `python -m webui --help` exit cleanly. Live confirmation + README remain M4.3e. Recipe
  consumed → git (`git log --grep "(M4.3d"`).
- **M4.3e — live 3-service provisioning smoke + evidence** (DONE): from a wiped `.webui-data`,
  verifier :8000 + hardware-free OpenAI stub :8001 answered before the hermetic launcher started Open
  WebUI :8080. Open WebUI initialized one tool server; startup + both `/api/v1/tools/` readbacks fetched
  `/schema/openapi.json`, and both `/api/models` readbacks fetched `/v1/models`. Bootstrap 1 passed with
  signup 200; bootstrap 2 passed idempotently through signup 403 → signin 200; each found the configured
  model + `server:verifier` and exited 0. This proves provisioning, NOT chat/tool execution (M4.5).
  Boot logs exposed a real config gap: the 23-byte dev JWT secret tripped PyJWT's HS256 minimum warning →
  `Settings` now enforces ≥32 UTF-8 bytes for defaults + overrides, its regression net pins the bound, and
  the final clean rerun was warning-free on that axis. `webui/README.md` records the exact setup, topology,
  readiness order, stub/NPU alternatives, bootstrap semantics, limits, and every `WEBUI_PROVISION_*` knob.
  All services stopped + scratch wiped; gate green (769 tests, 100% verifier branch coverage).
- **M4.4 — enforcement filter** is SPLIT a→b→c→d: the original unit crossed a standalone function
  payload/classifier, provisioning REST state machine, bootstrap orchestration, two operator docs, and a
  live 3-service assertion — incompatible with the strict one-module webui rule established by M4.3.
  Source check against installed Open WebUI 0.10.2 SETTLED the seams: create/update import-EXEC the posted
  source; `GET /api/v1/functions/id/{id}` reads state (missing = 401); create/update take the same
  `{id,name,content,meta:{description}}`; active/global are independent toggle endpoints; global selection
  requires `type=="filter" ∧ is_active ∧ is_global`; `/api/chat/completed` returns the outlet-mutated body.
  a–c each touch one webui module + its bench-style tests and leave the full gate green; d carries docs +
  live evidence. Filter id = `verified_plot_guard`, name = `Verified Plot Guard`; every bootstrap updates
  its source before converging flags, so code upgrades + reruns are idempotent.
- **M4.4a — standalone classifier + Filter payload** (DONE): added stdlib-only
  `webui/enforcement_filter.py`, itself the exact source posted to Open WebUI (`function_source()` reads the
  module bytes; no repo imports/Pydantic/frontmatter requirements). Pure `chart_signals(text) -> tuple[str,
  ...]` detects fenced matplotlib/pyplot/plotly/altair/seaborn code, fenced mermaid, raw `<svg`, parsed
  Vega-Lite-shaped JSON, and `data:image/...` URIs. `Filter.outlet(body)` inspects only the final assistant
  message; a hit replaces its content with one fixed verifier-routing notice and warning-logs signal names
  + character count, never the content. Pin each positive class, combinations/dedup/order, malformed/body
  no-op shapes, ordinary prose/library discussion, verifier summary + Location/embed metadata negatives,
  fixed replacement, metadata preservation, and import-exec of `function_source()` in
  `tests/test_webui_enforcement_filter.py`. Landed as specified: the exact payload import-executes under
  Open WebUI's Python 3.12; 31 focused cases + full gate green (800 tests, 100% verifier branch coverage).
- **M4.4b — idempotent function REST convergence** (DONE): `WebUIClient.ensure_global_filter(...)`
  authenticated-discovers then always create/updates the exact function payload, conditionally toggles active
  + global (both inverse endpoints), and final-GET proves exact id + type `filter` + current source + both
  flags. Every transport/status/decode/state failure normalizes to `WebUIProvisionError`. A targeted pinned-
  0.10.2 source check caught a contract nuance before close: create returns `FunctionResponse` WITHOUT
  `content`, whereas update/toggle/GET return `FunctionModel` WITH it; the loose struct therefore permits
  missing source only for create, checks create's id/type/flags, and relies on the mandatory final GET for
  persisted-source proof. MockTransport pins create/update, exact payload/Bearer/paths, all four flag states,
  no-op toggle rejection, malformed/non-200 failures at every seam, intermediate/final exactness, pre-auth +
  transport failure. Active-predicate mutation made the flag matrix fail (non-vacuous). Focused 51 cases +
  full gate green (828 tests, 100% verifier branch coverage).
- **M4.4c — bootstrap filter install** (OPEN): extend only `webui/bootstrap.py` + its tests. Inline the
  consumed M4.4a/b surface: constants `FILTER_ID`/`FILTER_NAME`/`FILTER_DESCRIPTION`, `function_source()`,
  and `_Provisioner.ensure_global_filter(...)`. `run_bootstrap` order = wait → authenticate → converge the
  global filter → existing model/tool smoke; convergence failure already raises, so `SmokeResult` + CLI
  contract stay unchanged. Fake-client tests pin exact args/order, success/rerun idempotency, and that smoke
  starts only after convergence. Acceptance: targeted suite, `python -m webui --help`, full gate green.
- **M4.4d — trust-boundary docs + live outlet assertion** (OPEN): `POC_SCOPE.md` gains an Open WebUI section
  naming it trusted display (not verifier), the heuristic filter as bypassable/false-positive guardrail,
  global server-side tool execution, CORS-free verifier, sandboxed Location iframe, and bare-metal loopback
  deployment assumption; `webui/README.md` records bootstrap's filter convergence + assertion recipe. From
  wiped `.webui-data`, stand up verifier → hardware-free model stub → hermetic Open WebUI; bootstrap twice;
  authenticated `/api/chat/completed` with required `model,id,chat_id,session_id,messages` must replace a
  chart-like assistant reply, preserve a prose reply byte-for-byte, and emit the content-free block warning.
  Record evidence, clean services/state, run full gate. Acceptance: classifier corpus + REST pins green and
  the live block/pass differential demonstrated honestly.
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

**Right-sizing rule (M1 evidence; binds M2+ unit sizing AND planning turns)**: size a unit at ~one module + its tests; an independent oracle or a property/fuzz layer is its OWN unit, never bundled. A unit whose DESIGN alone projects well past the ~200K aim is mis-sized → split it. A unit that runs well past the aim in IMPLEMENTATION despite a complete recipe is OVER-deriving, not under-specified → pre-derive a gate-validated transcription recipe (`.agent/*_design.md`), TRANSCRIBE not re-derive, reach the gate early, and salvage-continue (an overshoot ≠ bad work — a completed unit's gate-green output stands; recipes deleted once consumed). Isolate native-dep probes to scratch sessions — probing in the implementing window overflowed twice. M1 units landed at 39–88% of 200K under this rule.
