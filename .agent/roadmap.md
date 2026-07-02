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
| **M2** | Verifier API service (Litestar) | 1·api,8 | none | **IN-PROGRESS** |
| M3 | Local model proposer + failure eval | 1·model,7,8·propose,12 | Ollama + a local model | UNPLANNED |
| M4 | Open WebUI integration | 1·webui,9,10,11 | Open WebUI running | UNPLANNED |
| M5 | Formal + provenance hardening | 13,14 | none | UNPLANNED |
| M6 | End-to-end demo | 15 | full stack (M3+M4) | UNPLANNED |

Seed step 1 ("create the local stack") is split by gate: scaffold+data → M1, API → M2, model backend → M3, Open WebUI → M4. Plan each milestone only when it becomes active (prior one REVIEWED); M3/M4/M6 are gated — confirm preconditions functionally at their planning turn, deny-listed inputs off-limits.

---

## M2 — Verifier API service   (IN-PROGRESS)

Wrap the M1 library as a local HTTP service (seed 8 + seed 1's API slice): an untrusted caller submits a VPlot spec; the service runs the trusted pipeline and answers a structured verdict, rendering only on pass. Claim boundary UNCHANGED — the service is TRANSPORT around the verifier; POC_SCOPE's modest claim + TCB line hold verbatim; `data_dir` stays trusted operator config (checks.py TOCTOU precondition). Library seam (mapped): no verify-only orchestrator exists — service strings `decode_spec → resolve manifest → load_manifest → checks.verify` for structured detail; `render.render()` returns `None` on fail BY DESIGN (drops detail) → on a passed verdict the service calls `render()`, accepting its internal deterministic re-verify (defense in depth, small CSVs). Core modules stay import-free of the service subpackage (one-way dep).

**Stack (researched; overrides seed's FastAPI like M1 overrode Pydantic/pandas)**: **Litestar** `>=2.24,<3` — msgspec-NATIVE (no Pydantic second validator at the boundary), raw-bytes handlers hand the body verbatim to `decode_spec` (its dup-key pre-scan stays authoritative), msgspec response structs render natively + feed OpenAPI 3.1 with explicit `operation_id`/`summary` (M4 Open WebUI tool-ready), py.typed, bundled httpx test client. + **uvicorn** `>=0.49,<1` single worker on 127.0.0.1. Rejected: FastAPI (Pydantic-coupled dual validation = fail-open risk; bypassing it leaves only its bulk), Starlette+hand-authored openapi.json (runner-up: fewest deps, but hand-sync drift + more glue), Falcon/BlackSheep/Esmerald (weaker msgspec∩OpenAPI). Error split: verification outcomes — incl. spec-DECODE failure, an expected model failure mode M3 meters — answer **200 + verdict envelope**; only TRANSPORT misuse (content-type, oversize, bad path param, server config) answers **RFC 9457 `application/problem+json`** 4xx/5xx.

**Seed-8 divergences (resolved like VPlot_SEMANTICS §11)**: POST body = the raw VPlot spec JSON itself — seed's envelope rejected (`dataset_rows` = model-supplied data, violates the trust spine; `dataset_name` duplicates `spec.dataset.name`; `user_request` → M5 provenance). `plot_id` = content-addressed 64-hex SHA-256 of canonical VCert bytes (seed's timestamp id breaks determinism; re-render = same id, idempotent). `/propose-spec` → M3 (needs the model backend). Artifact store in-memory + bounded (seed-14 disk provenance/replay = M5). Vega-safe-numeric render gate (render.py's "M2+ candidate") → M5 hardening — a verifier-core check, not transport.

| Unit | Deliverable | Status | Ctx |
|------|-------------|--------|-----|
| M2.1 | Service scaffold: deps + settings + app factory + /health + runner | OPEN | |
| M2.2 | Verdict models + pipeline + POST /verify-only (corpus-driven suite) | OPEN | |
| M2.3 | POST /verify-and-render + bounded store + certificate/spec GETs | OPEN | |
| M2.4 | OpenAPI golden + live-socket smoke + POC_SCOPE service section | OPEN | |

### M2.1 — Service scaffold
Smallest unit first = the dep probe (M1 lesson), though litestar/uvicorn are pure-Python → low risk.
- pyproject: `litestar>=2.24,<3` + `uvicorn>=0.49,<1` into `[project].dependencies`; `uv lock`. Both ship py.typed; if mypy still complains, add an override block like jsonschema's.
- `src/verifier/service/` subpackage (coverage `source=["verifier"]` auto-measures it; 100% branch applies):
  - `settings.py` — `Settings` frozen kw-only msgspec Struct (container only, never decoded): `data_dir: Path`, `host: str = "127.0.0.1"`, `port: int = 8000`, `max_body_bytes: int = 65536` (spec schema bounds make real specs ≪64 KiB), `store_cap: int = 256`; `from_env()` classmethod reading `VERIFIER_DATA_DIR` (default `data`), `VERIFIER_HOST/PORT/...` — each parse branch tested.
  - `app.py` — `create_app(settings: Settings) -> Litestar`: registers routes, settings on app state. Every sync handler declares `sync_to_thread` EXPLICITLY (Litestar warns otherwise; CPU-bound handlers `True`, trivial ones `False`).
  - `__main__.py` — `main()`: `Settings.from_env()` → `uvicorn.run(create_app(…), host, port, workers=1)`; `if __name__ == "__main__": main()` (guard line = the one excused branch; `main()` itself covered via monkeypatched `uvicorn.run`). Default host literal 127.0.0.1 (S104 fires only on 0.0.0.0).
  - `GET /health` → `{"status": "ok", "version": __version__}`.
- `tests/test_service.py` — `litestar.testing.create_test_client(create_app(Settings(data_dir=…)))` fixture pattern; health 200+payload; `from_env` branches; `main()` monkeypatch test.
- **Accept**: gate green `--locked` (lockfile updated, mypy strict, 100% branch on the subpackage); test-client health passes.

### M2.2 — Verdict models + pipeline + POST /verify-only
- `service/models.py` — msgspec frozen kw-only structs, `omit_defaults=True` on optionals: `Verdict{verified: bool, layer: Literal["decode","verify"], results: tuple[checks.CheckResult, ...]}` (reuse `CheckResult` verbatim — seed's `{id,message,severity}` shape diverges, ours richer); `Problem{type, title, status, detail}` for RFC 9457 + a Litestar exception handler emitting `application/problem+json`.
- `service/pipeline.py` — pure `verify_only(raw: bytes, settings: Settings) -> Verdict`:
  1. `decode_spec(raw)`; `DecodeError`/`ValidationError` → `Verdict(verified=False, layer="decode", results=(CheckResult(check="spec.decode", status="fail", severity="blocking", message=str(exc)),))` — synthetic check id; reconcile with what `examples/index.json` records for `decodes:false` entries.
  2. Resolve manifest: `data_dir/"schemas"/f"{Path(spec.dataset.name).stem}.json"`, confined via `resolve()` + `is_relative_to(data_dir.resolve())` (reuse checks.py pattern); missing/escaping → verdict fail, synthetic `dataset.manifest_available`.
  3. `load_manifest(bytes)`; a BROKEN trusted manifest = operator config bug → raise → 500 problem+json (tested via a corrupt-manifest fixture dir); same for `checks.verify`'s `ValueError` name-mismatch (corrupt config, not caller race).
  4. `checks.verify(spec, manifest, data_dir=…)` → `Verdict(verified=report.passed, layer="verify", results=report.results)`.
- `POST /verify-only`: raw body bytes → pipeline → 200 Verdict. Preferred handler shape: sync `def` + `data: bytes` + `sync_to_thread=True`; fallback async + `await request.body()` + `anyio.to_thread.run_sync`. Content-Type guard: exactly `application/json` else 415 problem+json. Body-cap = pure-ASGI middleware wrapping `receive` summing `http.request` chunk lengths → 413 BEFORE buffering (uvicorn has no body flag; never a draining BaseHTTPMiddleware); lands here with the first POST, both branches tested (under-cap, over-cap, chunked/no-content-length).
- `tests/test_service_verify.py` — mirror `test_examples.py` corpus iteration: 10 good → `verified:true`, all results pass; 18 bad split on `decodes`: decode-layer → `layer:"decode"` + `spec.decode` fail; semantic → `verified:false` + the index-declared `check` among failed results. Transport: 415 wrong/missing content-type; 413 oversize; 405 wrong method; problem+json content-type asserted. THE fail-closed pin: duplicate-key spec body → decode fail through the raw-bytes path (proves the framework never pre-parsed).
- **Accept**: full corpus verdicts match `index.json` expectations; transport misuse → problem+json; dup-key pin holds; gate green.

### M2.3 — POST /verify-and-render + bounded store + retrieval GETs
- `service/store.py` — `ArtifactStore`: `threading.Lock` + `OrderedDict` LRU capped at `store_cap` (handlers run threadpooled), `move_to_end` on hit, evict oldest on overflow. Keys: `plot_id` = sha256 hexdigest (bare 64-hex) of the canonical VCert bytes (msgspec deterministic encode, same encoder family as canon) → `{cert_bytes, spec_canonical_bytes}`; secondary `spec_hash` bare-hex → spec canonical bytes. Store ONLY verified renders.
- `POST /verify-and-render?include_html=false` (kw bool query param): pipeline verdict; failed → 200 `Verdict` (omit_defaults ⇒ NO svg/html keys); passed → `render.render(spec, manifest_bytes, data_dir=…, include_html=…)`; a `None` return after a passed verdict = invariant break → explicit branch → 500 problem+json (covered via monkeypatched render; cast-not-assert lesson). Store, then 200 `RenderVerdict{…Verdict fields, plot_id, dataset_hash, spec_hash, plotted_table_hash, manifest_hash, svg: str, html: str | None}`.
- `GET /certificate/{plot_id}` + `GET /spec/{spec_hash}`: param must `fullmatch("[0-9a-f]{64}")` else 404 problem+json (no validity leak); hit → stored canonical bytes verbatim as `application/json`; miss → 404 problem+json. Add `X-Content-Type-Options: nosniff` as an app-default response header (asserted app-wide).
- `tests/test_service_render.py` — good corpus: svg byte-equals a direct `render.render()` (determinism THROUGH the service); repeat POST → same `plot_id` (idempotent); cert GET bytes round-trip; spec GET = canonical spec bytes; `include_html=true` attaches html, default omits. ALL 18 bad: raw response bytes contain neither `"svg"` nor `"html"` keys (seed-8 "never a chart when verified=false", pinned at byte level). Store eviction at a small-cap fixture; param regex rejects (upper/short/traversal); render-None → 500.
- **Accept**: never-chart pin at byte level over the full bad corpus; artifacts content-addressed + idempotent; GETs serve stored canonical bytes; store bounded; gate green.

### M2.4 — OpenAPI golden + live smoke + docs close-out
- OpenAPI: `OpenAPIConfig(create_examples=False, …)` (polyfactory examples are nondeterministic), explicit `operation_id` + `summary` on EVERY route (Open WebUI maps operationId → tool name and reads `summary`, not description), title/version/servers `http://127.0.0.1:8000`. POST body schema: inject `schema.json_schema()` (the VPlot golden) if Litestar customization is clean, else typed-object + description pointing at `schema/vplot-0.1.schema.json`. Commit golden `schema/openapi.json` (byte-stable snapshot test; assert `openapi: 3.1.x` + every operation carries operation_id; upgrade drift lands only via `uv.lock` bumps and the golden catches it).
- Live-socket smoke (seed: "API can be tested with curl"): one pytest booting `sys.executable -m verifier.service` (or uvicorn) on a free port (`# noqa: S603` precedent), poll `/health`, then real-TCP httpx: health + verify-only(good spec) → 200s; terminate. Proves out-of-process serving, not just the ASGI test client.
- Docs: POC_SCOPE new top-level `## Service boundary` adjacent to "The line we hold" — service = trusted-output transport OFF the verification claim; verdict-vs-transport error split; in-memory artifacts (provenance/replay = M5); curl examples. VPlot_SEMANTICS untouched (transport ≠ DSL semantics). memory.md M2 lessons + roadmap close-out; milestone → IMPLEMENTED.
- **Accept**: openapi.json golden byte-stable + operation_ids explicit; live-socket health+verify pass over real TCP; POC_SCOPE section lands; gate green.

---

## M1 — Trusted verifier core   (REVIEWED — closed)

Delivered the headless library `verifier`, gate-free, exercised entirely by pytest: schema decode gate (`schema.py` + exported JSON Schema golden) → canonical forms + 4 provenance hashes (`canon.py`) → typed ingest (`ingest.py`/`errors.py`) → Decimal-exact evaluator (`eval.py`) → verification spine + encoding/label checks (`checks.py`) → Vega-Lite positive-allowlist builder + SVG + VCert v0.1 badge + `render()` gate + optional offline HTML (`render.py`). 480 tests / 100% branch, dual-engine DuckDB oracle parity, golden corpus (10 good / 18 bad). Unit trail, per-unit context-usage, and the review pass: `git log --grep "(M1[. ]"`.

**Right-sizing rule (M1 evidence; binds M2+ unit sizing AND planning turns)**: size a unit at ~one module + its tests; an independent oracle or a property/fuzz layer is its OWN unit, never bundled. A unit whose DESIGN alone overflows a 200K window is mis-sized → split it. A unit that overflows in IMPLEMENTATION despite a complete recipe is OVER-deriving, not under-specified → pre-derive a gate-validated transcription recipe (`.agent/*_design.md`), TRANSCRIBE not re-derive, reach the gate early, and salvage-continue (overflow ≠ bad work — a completed-but-overflowed unit's gate-green output stands; recipes deleted once consumed). Isolate native-dep probes to scratch sessions — probing in the implementing window overflowed twice. M1 units landed at 39–88% of 200K under this rule.
