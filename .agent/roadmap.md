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
- **M4.3d — `webui/__main__.py` CLI dispatch** (OPEN): wires a+b+c into runnable services (live
  confirmation + README = M4.3e). SELF-CONTAINED — transcribe the CONSUMED SURFACE + helpers below,
  the test landmines are inline; open NO webui source. File = SPDX header
  (`# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception`) + module docstring (the harness entry
  point: `serve` execs OWUI hermetically, `bootstrap` provisions it, `stub` serves the hardware-free
  backend) + `_LOGGER = logging.getLogger(__name__)` + the helpers + module tail
  `if __name__ == "__main__":` / `raise SystemExit(main())`. The GUARD is REQUIRED — an unconditional
  tail runs main() on `import webui.__main__`, which the tests do; mirrors model_backend/__main__.py,
  returning int for the exit code. No `from __future__` (py3.13 PEP-604; siblings omit it). Log paths
  + status, never secrets. __init__.py UNTOUCHED (landed M4.3a).

  CONSUMED SURFACE (source-VERIFIED, drift-check DISCHARGED — these 4 modules are UNCHANGED since
  M4.3a/b/c; confirm with one `git log --oneline -1 -- webui/settings.py webui/client.py
  webui/bootstrap.py webui/model_stub.py` (newest touch = the M4.3c commit; anything newer = drift →
  re-verify that module) instead of re-opening them):
  · `from webui.settings import Settings` — frozen msgspec Struct, EVERY field defaulted ⇒ `Settings()`
    bare-constructs (post_init passes on defaults). Reads `.webui_bin: Path`, `.host: str`, `.port:
    int`, `.base_url: str` (property), `.request_timeout: float`, `.child_env() -> dict[str,str]`
    (hermetic exec env = an 8-key PATH/HOME/locale passthrough from os.environ overlaid with
    launch_env ⇒ ALWAYS carries `OFFLINE_MODE="true"`, carries `PATH` iff in os.environ, DROPS every
    os.environ key outside the allowlist). `Settings.from_env() -> Settings` (@classmethod, annotated
    `-> Self`, no args — the caller receives a `Settings`).
  · `from webui.client import WebUIClient, WebUIProvisionError` — `WebUIClient(http: httpx.Client,
    settings: Settings)`; `WebUIProvisionError(RuntimeError)`.
  · `from webui.bootstrap import run_bootstrap, SmokeResult` — `run_bootstrap(client, settings) ->
    SmokeResult`; `SmokeResult` (frozen kw_only) fields `model_ids: tuple[str,...]`,
    `tool_server_ids: tuple[str,...]`, `model_enumerated: bool`, `tool_registered: bool`; `.ok =
    model_enumerated and tool_registered`.
  · `from webui.model_stub import serve as serve_stub` — `serve_stub(settings) -> None`.
  · stdlib/deps: `argparse`, `logging`, `os`, `httpx`, `collections.abc.Sequence`, `typing.NoReturn`,
    `typing.cast`.

  Helpers:
  · `_serve(settings) -> NoReturn`: `binary = settings.webui_bin`; not `binary.is_file()` ⇒
    `_LOGGER.error` + `raise SystemExit(1)` (loud, vs a raw execve FileNotFoundError); else `argv =
    [str(binary), "serve", "--host", settings.host, "--port", str(settings.port)]`;
    `os.execve(str(binary), argv, settings.child_env())  # noqa: S606` (shell-free; child_env = the
    M4.3a hermetic boundary; execve is typed NoReturn in typeshed ⇒ `-> NoReturn` type-checks).
  · `_bootstrap(settings) -> int`: `try:` `with httpx.Client(base_url=settings.base_url,
    timeout=settings.request_timeout) as http:` `result = run_bootstrap(WebUIClient(http, settings),
    settings)` / `except WebUIProvisionError:` `_LOGGER.exception` (TRY400 — `.exception`, NOT `.error`,
    inside an except arm) + `return 1`; then `if not result.ok:`
    `_LOGGER.error` + `return 1`; else `_LOGGER.info` + `return 0`. (mypy: `result` is bound past the
    except because that arm returns.)
  · `_parse_args(argv: Sequence[str] | None) -> str`: `argparse.ArgumentParser`, one positional
    `command` `choices=("serve","bootstrap","stub")`; `return cast("str",
    parser.parse_args(argv).command)` (Namespace attrs are Any → cast dodges no-any-return).
  · `main(argv: Sequence[str] | None = None) -> int`: `logging.basicConfig(level=logging.INFO)`;
    `command = _parse_args(argv)`; `settings = Settings.from_env()`; then if/elif/ELSE (else keeps
    mypy return-exhaustive; RET503 does NOT fire — the NoReturn `_serve` branch satisfies ruff's
    implicit-return check, no trailing `return` needed): `if command == "serve": _serve(settings)`
    (NoReturn) `elif command ==
    "stub": serve_stub(settings); return 0` `else: return _bootstrap(settings)`.

  Tests `tests/test_webui_cli.py` (SPDX + docstring; webui is coverage-excluded ⇒ a bench-style loop,
  NOT a branch gate; execve/uvicorn monkeypatched so nothing runs). Imports: `import webui.__main__
  as cli`, `from webui.settings import Settings`, `from webui.bootstrap import SmokeResult`, `from
  webui.client import WebUIProvisionError`, `import os`, `import pytest`. Custom test exceptions take
  the N818 `Error` suffix (`tests/**` ignores S101/PLR2004/TID251, NOT N818). Type every fake (mypy
  --strict spans tests): execve fake `(_path: str, argv: list[str], env: dict[str, str]) -> NoReturn`
  (leading `_` on the unused `path` dodges ARG001 — `tests/**` does NOT ignore ARG);
  dispatch stubs `(settings: Settings) -> …` (the `_serve` stub `-> NoReturn`, it records then raises;
  `serve_stub` `-> None`; `_bootstrap` `-> int`); run_bootstrap fake `(client: object, settings:
  Settings) -> SmokeResult`.
  · `_parse_args`: each of the 3 commands returns its string; unknown ⇒ `pytest.raises(SystemExit)`.
  · dispatch threads ONE Settings: `_SENTINEL = Settings()`; LANDMINE (no_implicit_reexport) — patch
    the imported CLASS `monkeypatch.setattr(Settings, "from_env", staticmethod(lambda: _SENTINEL))`,
    NOT `cli.Settings` (⇒ attr-defined); a string `setattr(cli, "_serve"|"serve_stub"|"_bootstrap"|
    "run_bootstrap", …)` is unaffected. serve: stub `cli._serve` to record its arg then raise
    `_ServeCalledError`; `pytest.raises(_ServeCalledError, cli.main, ["serve"])`; recorded arg is
    _SENTINEL. stub: stub `cli.serve_stub` to record + return None; `cli.main(["stub"]) == 0`;
    recorded is _SENTINEL. bootstrap: stub `cli._bootstrap` to record + return 0; `cli.main(
    ["bootstrap"]) == 0`; recorded is _SENTINEL.
  · `_serve` hermetic exec: `binary = tmp_path/"open-webui"; binary.touch()`; `settings =
    Settings(webui_bin=binary)`; `monkeypatch.setenv("PATH", "/usr/bin")`;
    `monkeypatch.setenv("WEBUI_PROVISION_LEAK", "x")`; `fake_execve(_path, argv, env)` captures env
    then raises `_ExecedError`; `monkeypatch.setattr(os, "execve", fake_execve)` (shared os
    singleton); `pytest.raises(_ExecedError, cli._serve, settings)`; assert `env["OFFLINE_MODE"] ==
    "true"`, `env["PATH"] == "/usr/bin"`, `"WEBUI_PROVISION_LEAK" not in env`. Missing binary:
    `Settings(webui_bin=tmp_path/"absent")` ⇒ raises `SystemExit` with `.code == 1`.
  · `_bootstrap` return codes: `setattr(cli, "run_bootstrap", fake)`, fake returns
    `SmokeResult(model_ids=(), tool_server_ids=(), model_enumerated=b, tool_registered=b)` — b True⇒0,
    b False⇒1 — or raises `WebUIProvisionError`⇒1. (httpx.Client + WebUIClient construct without I/O;
    only run_bootstrap is faked.)

  Acceptance: gate green (`uv run --locked` ruff format --check . · ruff check . · mypy · pytest);
  arg-parse / dispatch / hermetic-exec / return-code shapes pinned.
- **M4.3e — live 3-service provisioning smoke + evidence** (OPEN): the hardware-free live confirmation of
  a+b+c+d (the stub stands in for the NPU; asserts model-enumeration + tool-registration + idempotency, NOT a
  chat round-trip — that is M4.5). Recipe: wipe `.webui-data`; launch verifier :8000 + stub :8001 and WAIT for
  each ready (verifier `/health` or `/schema/openapi.json` 200, stub `/v1/models` 200) BEFORE launching OWUI —
  `/api/v1/tools/` live-re-fetches and DROPS a server whose OpenAPI fetch fails (utils/tools.py), so the
  verifier must answer by the readback; then launch OWUI-via-launcher + `python -m webui bootstrap` → smoke
  passes (model_id enumerated, `server:verifier` registered). Re-run bootstrap against the still-running OWUI
  → idempotent PASS via the signin fallback (signup returns 403 same-process; no new DB/config writes), smoke
  still green. Then author `webui/README.md` from THIS verified launch (dense, bench/README style): the
  three-service topology (verifier :8000 `python -m verifier.service`; OpenAI backend :8001 = the stub
  `python -m webui stub` OR the live NPU model_backend; OWUI :8080 `python -m webui serve` → execs
  `.venv-webui/bin/open-webui` hermetically) → readiness-ordered launch (verifier + backend READY before
  OWUI, else `/api/v1/tools/` drops the verifier) → `python -m webui bootstrap`; the `WEBUI_PROVISION_*`
  knobs; coverage-excluded + unshipped. Record the evidence + fix any surfaced gap; then kill the services +
  wipe scratch. Acceptance: both bootstrap runs green from a clean `.webui-data`; readiness-ordered launch;
  README documents the verified recipe; evidence recorded.
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
