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
| M4 | Open WebUI integration | 1·webui,9,10,11 | Open WebUI running — CONFIRMED at plan | REVIEWED |
| M5 | Formal + provenance hardening | 13,14 | none — toolchain probe confirmed | REVIEWED |
| M6 | End-to-end demo | 15 | full stack (M3+M4) — CONFIRMED live at plan | REVIEWED |
| M7 | Interactive local-model browser instance | — (user request) | live stack (verifier+model+OWUI) — CONFIRMED at plan | REVIEWED |
| M8 | Reliable real-model figures (schema-guided decoding) | — (user request) | live NPU stack + OV structured output — CONFIRMED at plan | REVIEWED |

Seed step 1 ("create the local stack") is split by gate: scaffold+data → M1, API → M2, model backend → M3, Open WebUI → M4. Plan each milestone only when it becomes active (prior one REVIEWED); M3/M4/M6/M7 are gated — confirm preconditions functionally at their planning turn; bring generated/heavy inputs into scope only when the gate needs them.

---

## M8 — Reliable real-model figures (schema-guided decoding)   (REVIEWED)

### Review ledger: M8 REVIEWED — all dispositions closed

Four analysis lenses (correctness/spec, cross-unit integration, instruction/memory conformance,
token-efficiency/obsolescence) over every M8 commit (`git log --grep "(M8[. ]"` — plan + M8.1 + M8.2a
+ M8.2b + M8.3 ×2), cross-checked by independent peer audits + three targeted probes (artifact/SPDX,
bench-provenance, OWUI-traffic). No trust-boundary or logic defect surfaced: every mechanic —
per-request `guided_json` scoping, the xgrammar `pattern`/`format` strip, strict-decode authority,
Decimal recompute, SHA-256 re-bind — is correct, and guidance is structure-only (SPDX "fails closed",
bench-provenance "clean trust seam", OWUI-trace "guidance adds no trust"; the deterministic bound
18/18 bad blocked + 10/10 good accepted + 0 faults held). Cross-unit integration confirmed the four
units compose at their seams (M8.1 mechanism → M8.2a per-request scoping → M8.2b OWUI two-call flow →
M8.3 measure) with the TCB unmoved end-to-end. Every accepted finding was CLAIM-DISCIPLINE, folded
into this review commit (comment/docstring + doc/roadmap/memory only, no logic change → no separate
Agent batch):

- **Overclaim cluster** ("forces / reliably emit / valid structure" → "steers toward a
  schema-representable structure") — the bulk landed in M8.3's `7aacd83`; review tightened the last
  residual "valid VPlot structure" → "schema-representable" in `model_backend/models.py` +
  `src/verifier/service/model_client.py`.
- **0→26 confound** (git-validated): the raw `0/100` baseline predates BOTH the M5.1h gen-path fix
  (`548809e`) AND the verifier's M5-M7 evolution → the delta reflects all three, not guidance alone;
  only fenced→0 is by-construction guidance-attributable (caveat a). `verified_render` counts VERIFIER
  passes, not natural-language prompt-intent (caveat b).
- **Two distinct blocked paths** (not to be conflated): the banner's reliably-BLOCKED prompt hits the
  `Verified Plot Guard` (model bypass → raw matplotlib → `BLOCKED_NOTICE`, a bypassable guardrail),
  NOT the verifier; the schema-valid-but-semantically-wrong verifier rejection is the backend-direct
  `/propose-spec` probe (`encoding.fields_exist_in_plotted_table`). Documented in the thesis +
  M8.3-close.
- **won't-compile doc-narrow**: `Engine.load` fails closed only on a missing / unreadable / non-object
  schema; the xgrammar grammar builds lazily at first guided generate (an uncompilable override
  surfaces there as an upstream fault — the verifier still accepts no spec).

Deferred (recorded, not fixed — outside M8 claim-discipline): OWUI output-item-type robustness (inert
under the shipped Qwen2-0.5B backend — see Deferred above); operator-schema hardening (load-time
meta-validation + `json.loads` non-finite/duplicate-key strictness — safety-independent, the strict
verifier still prevents false verification); pre-M8 hygiene (`.agent/context.sh` SPDX header; Read-deny
gaps for `.verifier-state/**` [Ed25519 signing.key + archive DB], `.serena/cache/**`,
`bench/reports/details.jsonl`, `.launch-logs/**`); the bench-provenance overhaul + a paired
current-commit raw-vs-guided A/B + the `tool_call_rate` rename — all surfaced to the user
(permission / `CLAUDE.md` edits are the user's call, not peer-grantable).

CLOSED: M8 REVIEWED — MAIN independently reran the full gate green (ruff format 94 / ruff check / mypy
94 / pytest 1605 @ 100% branch) after folding the four claim-discipline edits (comment/docstring + doc
only; no coverage-source logic changed, test count unchanged at 1605).

**User task** (`/session-prompt`): the launched OWUI PoC's "Try typing" banner should offer TWO
real examples — one that reliably gets BLOCKED (with a clear "blocked" message) and one that reliably
SUCCEEDS (renders a real verified figure) — with the REAL weak model, not `--stub`. That requires the
real model to reliably emit a verifiable VPlot for a chosen prompt; M7's banner shows only ONE
mode-gated outcome precisely because the raw model can't (M3: 0/100). Root cause + fix VALIDATED on
the live NPU stack before planning.

**Why M7's one-example banner can't just be doubled.** `webui/launch.sh:250` states the M7 truth:
the verify-vs-block outcome is driven by MODEL TIER (real=blocked, `--stub`=verifies), not prompt
text, so one tier honestly shows one outcome. M8 makes the real model reliably verify a well-formed
request → outcome becomes PROMPT-driven within the single real tier → the banner can honestly show a
blocked-prompt + a succeeds-prompt together. `webui/bootstrap.py` provisions no OWUI-native
suggestion chips; the "Try typing" the user sees IS the launcher banner (bash, outside the
ruff/mypy/pytest gate).

**Thesis preserved / sharpened.** Claim boundary UNCHANGED: the model supplies NO data values; verify
recomputes the whole plotted table (Decimal-exact) + re-binds the CSV by SHA-256. Constrained decoding
steers output toward a relaxed, schema-representable STRUCTURE (value constraints stripped, so strict
decode stays the authority), never SEMANTICS or data → the verifier's demonstrated value shifts from
"catches syntactic garbage" to "catches the semantic errors a schema can't" (wrong column/unit/type);
provenance/hash/recompute/SMT rejection stays a by-construction guarantee, not exercised by this corpus
(faults 0). M3's raw proposer 0/100 stays the honest baseline (unconstrained); M8 ships constrained as
the default and re-measures. Two DISTINCT blocked paths, not to be conflated: (1) the banner's
reliably-BLOCKED prompt is caught by the `Verified Plot Guard` (the model bypasses proposeSpec → raw
matplotlib → `BLOCKED_NOTICE` — a bypassable guardrail, NOT the verifier); (2) the
schema-valid-but-semantically-wrong verifier rejection is demonstrated by the backend-direct
`/propose-spec` probe (`bar chart of total revenue by month` → fails
`encoding.fields_exist_in_plotted_table`).

**Precondition CONFIRMED (live NPU, this session).** OV GenAI 2026.2.1
`StructuredOutputConfig(json_schema=)` works on the NPU (demo default; pipeline loads ~7s,
greedy-deterministic, byte-identical to CPU) AND CPU. Real Qwen2-0.5B → verifier `/verify-only`: raw
0/100 (M3) is a Vega-Lite prior (mark-as-object, ~97% markdown-fenced) + a reliable trailing junk key
(`select` / `color`) after an otherwise-perfect 5-key spec that strict decode rejects — unfixable by
prompting (~30 variants, 0 clean). Schema-guidance forbids the trailing key
(`additionalProperties:false`) → base-prompt+schema 2/3 simple prompts verify; +1-shot empty-transform
example → `scatter of temp_c vs precip_mm from weather.csv` verifies deterministically. Tooling choice
empirically validated (supersedes web docs).

**Recipe (CONSUMED — mechanism shipped in M8.1).** The xgrammar strip (OV's backend rejects the VPlot
schema's negative-lookahead `pattern`s; `pattern` + `format` recursively stripped from
`schema/vplot-0.1.schema.json`, structure — `required` / `additionalProperties:false` / `enum` /
`anyOf`+discriminator — preserved) shipped in `model_backend/schema_guidance.py`, derived at runtime
from the authoritative file so it cannot drift; the strict schema stays the SOLE verifier authority
(guidance only relaxes value patterns). No few-shot exemplar (M8.2a dropped it: base+schema suffices).
Live-NPU probe facts + the final pinned prompts live in `.agent/memory.md` (M8) and the DONE-records
below; the superseded 1-shot/candidate-prompt planning detail + `/tmp` probe scripts are in git.

### Units (IMPLEMENTED)
- **M8.1 (DONE) — backend structured-output mechanism.** New pure `model_backend/schema_guidance.py`
  (NO `openvino_genai` import → portably importable/testable even though model_backend is
  coverage-excluded) deriving the pattern/format-stripped guidance schema from
  `schema/vplot-0.1.schema.json`; `model_backend/settings.py` gains `structured_output: bool = True` +
  `vplot_schema_path`; `model_backend/engine.py` applies `StructuredOutputConfig` in `generate` when
  enabled (`Engine.load` fails closed on a missing, unreadable, or non-JSON-object schema; the
  xgrammar grammar itself builds lazily at first guided generate, so a valid-JSON-but-uncompilable
  override surfaces there as an upstream fault — the verifier still accepts no spec). Portable tests (run in the `.venv` suite, import
  only the no-openvino modules): derivation strips exactly `pattern` / `format`, preserves structure,
  all 10 good goldens validate against the derived schema (drift guard), plus the settings flags.
  Acceptance: ruff/mypy/pytest green (model_backend type-checked, coverage-excluded); MAIN NPU-validates
  constrained generate → structurally-valid VPlot + a simple prompt verifies. No operator-doc change (internal `.agent/` bookkeeping only).
  Done: gates green (ruff format/check, mypy 94 files, pytest 1596 @ 100% verifier cov); MAIN NPU-validated
  the real Engine (structured_output on; 3511-byte guidance, no `pattern`/`format`) → structurally-valid VPlot,
  `decode_spec` ACCEPTED (`weather.csv` scatter). A `sales` (no-`.csv`) run was structure-valid but
  verifier-REJECTED on the dataset-name rule — live-proof of the structure-vs-semantics split (schema forces
  structure; the verifier owns semantics). Context: `main=38% 105K/272K`; `impl=47% 128K/272K` (implementing Agent).
- **M8.2 respec → M8.2a + M8.2b (live-NPU findings).** Confirmed seam: request-scoping is a
  newly-required mechanism (global structured output breaks OWUI chat), and the banner +
  blocked-message decisions need live OWUI validation that only exists once request-scoping lands.
  Phase-A live-NPU findings (CONSUMED — shipped + recorded in `.agent/memory.md` M8 + the DONE-records
  below): global structured output breaks OWUI chat (`capital of France?` emits VPlot JSON) → guidance
  must be REQUEST-SCOPED (M8.2a), superseding M8.2's original direct-`/propose-spec` assumption; OWUI
  cannot relay a summary-only (`process_tool_result` embeds only on `Content-Disposition: inline` +
  `text/html`/`Location`), so the clear blocked message comes from `enforcement_filter.py`'s outlet
  (`BLOCKED_NOTICE`), NOT a verifier response-shape change. Pinned succeeds/blocked prompts + the
  direct-probe semantic-fail (`fields_exist_in_plotted_table`) are in memory M8; full probe detail in git.
- **M8.2a (DONE) — request-scoped structured output.** Make M8.1 guidance opt-in per
  request so OWUI chat/tool-selection stays unconstrained while the verifier's proposeSpec is
  VPlot-constrained. model_backend: `ChatCompletionRequest` gains `guided_json: bool = False`
  (`model_backend/models.py`); `chat_completions` threads `guided=data.guided_json`
  (`model_backend/app.py`); `Engine.generate(…, guided: bool)` applies `StructuredOutputConfig` only
  when `guided and self._guidance_schema is not None` (`model_backend/engine.py`) — load-time
  derivation unchanged, still fail-closed. verifier: `propose_spec` adds `"guided_json": true` to the
  `payload` dict (`src/verifier/service/model_client.py:493`). Tests: model_backend apply/omit becomes
  per-request (coverage-excluded); the model_client request-body byte-equality tests absorb the new
  field. Acceptance: portable gate green (ruff/mypy/pytest, 100% verifier cov); MAIN NPU-check → a
  `guided_json:true` request is VPlot-constrained (proposeSpec still verifies) while a plain
  `/v1/chat/completions` request is unconstrained (`capital of France?` answers in prose). No
  operator-doc change (internal `.agent/` bookkeeping only).
  Done: portable gate independently re-green (ruff format 94 / ruff check / mypy 94 / pytest 1598 @
  100% verifier branch cov). Edits exactly as specced — `ChatCompletionRequest.guided_json: bool =
  False` (models.py), `chat_completions` threads `guided=data.guided_json` (app.py),
  `Engine.generate(…, *, guided: bool)` applies `StructuredOutputConfig` only when `guided and
  self._guidance_schema is not None` (engine.py; load-time derivation unchanged, still fail-closed),
  `propose_spec` payload gains a trailing `"guided_json": True` (model_client.py). Tests recast to
  per-request apply/omit (3 cases: guided+available→applied, not-guided+available→omitted,
  guided+disabled-at-load→omitted) + an app-level `guided_json` true/default-false threading test +
  the `old_wire_body` byte-equality absorbing the field; attempt-capture tests self-adjust (they
  compare against the live `trace.request_body`). MAIN NPU-check (real backend on NPU + verifier,
  fresh tmp state): plain `/v1/chat/completions` `capital of France?` → `"The capital of France is
  Paris."` unconstrained prose (`decode_spec` DecodeError); backend-direct `guided_json:true` →
  structurally-valid VPlot JSON; verifier `/propose-spec` `sales.csv` `Scatter plot of revenue
  versus orders.` → 200 `Content-Disposition: inline` + `Location …/chart/6cb6ab12…` + summary
  `all 9 checks passed` + chart served 200 CSP `sandbox allow-scripts` (the M4 verified-success
  signature — a failure returns a bare object with no Location; reproduces the Phase-A 9/9 result
  under request-scoping). No operator-doc change (internal `.agent/` bookkeeping only). Context: `main=70% 189K/272K`; `impl=48%
  130K/272K` (implementing Agent).
- **M8.2b (DONE) — two-example banner + clear blocked message.** MAIN re-standups the
  real NPU stack with request-scoping and validates the live OWUI flow: plain chat unconstrained; a
  succeeds-prompt (start from `Scatter plot of revenue versus orders.`) that deterministically drives
  proposeSpec → a verified inline chart embed; a blocked-prompt (`Create a bar chart of total revenue
  by month.`) whose OWUI outcome deterministically surfaces a clear blocked message. Tool-selection is
  per-fixed-prompt greedy-deterministic (a prompt always- or never-calls the tool) → pin prompts that
  behave; if the blocked reply is not chart-looking (outlet silent), add a minimal
  `enforcement_filter.py` enhancement (standalone, non-gated) — do NOT relay a verifier summary-only
  (banked OWUI fact). AGENT transcribes: rewrite `webui/launch.sh` "Try typing" banner (and drop its
  `:250` tier-split comment) to show BOTH pinned prompts with their prompt-driven outcomes; any outlet
  enhancement. Acceptance: portable gate green; MAIN real-model standup → succeeds-prompt renders a
  real inline figure end-to-end (textual proof: `/propose-spec` `Location` + served chart HTML +
  certificate; OWUI `run_persisted_chat` embed per M7.2 precedent) AND blocked-prompt shows a clear
  "blocked" message, both deterministic.
  DONE (real NPU, greedy-deterministic; the live pins differ from the plan's starting phrasings):
  succeeds-prompt `Plot a scatter chart of revenue versus orders. dataset_name: sales.csv` — the
  explicit `dataset_name:` cue is required, since a loose `from/using sales.csv` drops the arg
  (`/propose-spec` 400 → raw matplotlib) — drives proposeSpec → a verified inline embed
  `/chart/519a22ee…` (200, `text/html`, 900110 B, live `<svg>`+Vega); blocked-prompt `Using sales.csv,
  plot a chart of revenue versus orders.` → the model emits raw matplotlib → the outlet guard
  (`signals=matplotlib chars=1062`) → `BLOCKED_NOTICE` (147 B); control `What is the capital of
  France?` → `The capital of France is Paris.`. As the plan anticipated, the outlet was silent on
  OWUI's background/persisted path (legacy `content` empty; the reply lives in
  `output[].content[].text`), so the standalone non-gated `enforcement_filter.py` enhancement was
  required: classify over `content`+`output`, then rewrite the persisted `output` via a NEW deep copy
  (OWUI `outlet_filter_handler` persists only on `message["output"] != original` object-inequality —
  `middleware.py` ~L3336/L3396). `webui/launch.sh` banner now shows BOTH pinned prompts with their
  prompt-driven outcomes (real: 1 verifies / 2 blocks; `--stub` verifies any request so both render,
  and points to the real model for the block), and the `:250` tier-split comment is dropped. Portable
  gate green (ruff format/check, mypy 94, pytest 1605, verifier cov 100%); `shellcheck` + `bash -n`
  clean. Context: `main=44% 121K/272K`; `impl=39% 106K/272K` (implementing Agent).
- **M8.3 (DONE) — honest re-measure + finding/doc updates.** MAIN re-runs `bench`
  (constrained default) → new observations. AGENT updates the honest record: this M8 section's numbers,
  an M3 note that 0/100 is the RAW baseline superseded by the constrained default, `.agent/memory.md`,
  `POC_SCOPE.md` (proposer section), root + `webui` READMEs. Acceptance: portable gate green; `bench`
  exits 0; docs state raw-vs-constrained numbers faithfully.
  DONE (MAIN-executed live NPU bench, `python -m bench` exit 0; served `Qwen2-0.5B-Instruct-int4-sym-ov`,
  greedy temp=0, n=100 HTTP-200 `/propose-spec` verdicts; reproducible per (device,config); gitignored
  reports/ → these numbers are the durable record). CONSTRAINED default vs the RAW M3 baseline:
  `verified_render` **0/100 → 26/100**; reply shape **fenced 97→0, bare_object 2→100**,
  defenced/JSON-valid **24→83**; buckets `schema=0.51 / semantic=0.23 / policy=0.00`; top checks
  `spec.decode`(51) + `encoding.fields_exist_in_plotted_table`(22) + `schema.field_types_match`(1);
  faults all 0; per-category verified_render normal 0.15 / ambiguous 0.45 / adversarial 0.45 /
  bad_aggregation 0.00 / hidden_filter 0.25. The GUARANTEE held UNCHANGED — bad 18/18 (`false_accept=0`),
  good 10/10 (`false_reject=0`), 0 transport, corpus digests unchanged — so the deterministic verifier
  bound is untouched. This LIVE-CONFIRMS the M8 sharper-cut thesis: schema guidance STEERS structure —
  it mechanically eliminates the markdown-fence failure mode (the grammar forbids the fence: fenced
  97→0, de-fenced/JSON-valid 24→83) — while residual failures split between token-cap/value-level
  strict-decode misses (51) and SEMANTIC blocks a schema cannot enforce
  (`encoding.fields_exist_in_plotted_table`, 22) — the verifier's demonstrated value shifts from
  catching syntactic garbage to catching the SEMANTIC errors a schema can't; provenance/hash/recompute
  rejection stays a by-construction guarantee, NOT exercised by this corpus (faults 0). TWO CAVEATS on
  the 0→26 delta: (a) it is NOT an isolated guidance A/B — the raw `0/100` baseline (54e5757/944e3a9,
  Jul 6-7) predates BOTH the M5.1h generation-path fix (548809e, string-gen → exact `TokenizedInputs`)
  AND the verifier's M5-M7 evolution (formal/SMT/archive machinery), so the delta reflects all three
  changes, not guidance alone; only fenced→0 is by-construction guidance-attributable (the grammar
  forbids the fence, independent of gen-path or verifier version).
  (b) `verified_render` counts VERIFIER passes (schema + Decimal-exact recompute + provenance), NOT
  natural-language prompt-intent satisfaction — a spec can verify while not answering the request;
  intent alignment is outside the verifier (`bench/README.md`). Claim boundary UNMOVED (model supplies
  no data values; verifier recomputes the whole plotted table + re-binds the CSV by SHA-256; guidance =
  structure-only, no trust). M8.3 shipped in TWO commits. (1) `801ee63` — constrained re-measure + doc updates: `.agent/memory.md`
  (M8 constrained-result bullet + M3 raw-baseline annotation), `.agent/roadmap.md`, `POC_SCOPE.md`
  proposer section, root `README.md` (two-example outcome + 26/100 observation), `webui/README.md`
  (M4.5 raw record annotated + constrained note); MAIN added the M3-section supersession note above.
  Context: `main=73% 199K/272K`; `impl=62% 168K/272K` (doc-update Agent) — this FIRST pass only. (2)
  `7aacd83` — honesty follow-up (faithful raw-vs-constrained numbers + trust boundary):
  `.agent/memory.md`, `POC_SCOPE.md`, `README.md`, `bench/README.md`, `bench/harness.py`,
  `tests/test_bench_harness.py`, `webui/README.md`, and the `webui/launch.sh` banner trust-wording fix
  ("verifier drafts the spec" → "model proposes, verifier recomputes"). Portable gate independently
  re-green at each (ruff format 94 / ruff check / mypy 94 / pytest 1605 @ 100% branch — docs +
  coverage-excluded bench harness/test docstrings; no coverage-source Python changed). M8 IMPLEMENTED
  (M8.1 + M8.2a + M8.2b + M8.3 all DONE).

**Deferred (not M8):** the M7-review launcher crash-detection follow-up (parked in the M7 section)
stays separate — unrelated to proposer reliability.

**Deferred (M8-review):** OWUI output-item-type robustness — the persisted-chat reader
(`webui/client.py:433-443`, positional `output[0].content[0]`) and `enforcement_filter.py:136-158`
(concatenates `output[].content[].text`) both assume a single `type="message"` item. Correct for the
shipped single-`content`-item `model_backend` reply (Qwen2-0.5B, no reasoning item), fragile against
a reasoning-capable backend that prepends a `type="reasoning"` item — MEDIUM: reader returns the
reasoning text or rejects the chart chat as no-final-text (dropping the M8.2b blocked notice); LOW:
filter reasoning-item false-positive. INERT under the shipped backend (M8.2b live path sound, verified
in review); fix when a reasoning backend is introduced by selecting the `type="message"` /
`type="output_text"` item by type, not position (M8 review).

---

## M7 — Interactive local-model browser instance   (REVIEWED)

### Review ledger: M7 REVIEWED — all dispositions closed

Four analysis lenses (correctness/spec, cross-unit integration, instruction/memory conformance,
token-efficiency/obsolescence) over every M7 commit (`git log --grep "(M7[. ]"` — plan + M7.1 +
M7.2). Every accepted finding landed in the launcher `webui/launch.sh` (bash, outside the
ruff/mypy/pytest gate — no coverage-source Python changed), folded into this review commit, no
separate batches. Operator docs (root `README.md` "Try it in your browser", `webui/README.md`
"One-command interactive instance") audited clean — the launcher fix keeps their one-command claim
honest; no doc edit needed.
- FIXED (override-fidelity / port-coupling — the load-bearing finding): the launcher hardcoded its
  child endpoints, so a `VERIFIER_PORT` / `MODEL_BACKEND_PORT` override did NOT wire through — OWUI
  provisioning, the verifier's chart `Location`, AND the verifier's OWN model client (`/propose-spec`
  → the backend, via `VERIFIER_MODEL_BASE_URL`) all stayed pinned to the default ports, so a remapped
  launch served certificate links on the wrong port and the verifier answered 503 against the moved
  backend. Now derives + exports `WEBUI_PROVISION_VERIFIER_URL`, `WEBUI_PROVISION_MODEL_BACKEND_URL`,
  `VERIFIER_MODEL_BASE_URL` (and surfaces `WEBUI_PROVISION_WEBUI_BIN`) from `HEALTH_HOST` + the port
  vars, and also exports `VERIFIER_PORT` — byte-identical to the prior child settings defaults at the
  default ports (an explicit URL override still wins).
- FIXED (start-time safety): a `port_in_use()` `/dev/tcp` preflight refuses to start when any target
  port is already bound, placed BEFORE `trap cleanup` installs so a refusal never `fuser -k`s a
  pre-existing foreign listener (closes the readiness-poll-adopts-a-stranger + teardown-kills-an-
  innocent hazard); the readiness `curl` gained `--connect-timeout 2 --max-time 5` so an
  accepting-but-silent socket can't hang the poll; and the preconditions now check
  `$UV_PROJECT_ENVIRONMENT` / `$WEBUI_PROVISION_WEBUI_BIN` (not hardcoded `.venv` /
  `.venv-webui/bin/open-webui`) so an override governs its own guard.
- ACCEPT-RECORD (no change): M7 moves no verifier trust or claim boundary anywhere (orchestration +
  docs only; POC_SCOPE TCB intact, as the plan asserts); the `--stub`-XOR-real one-port model tier,
  the setsid-group teardown, and the backgrounded-SIGINT no-op are all correct as landed (memory
  M7.1/M7.2).
CLOSED: M7 REVIEWED — MAIN independently reran `shellcheck` rc=0 + `bash -n` rc=0, re-parsed the
verifier `VERIFIER_MODEL_BASE_URL` knob (→ `http://127.0.0.1:8011/v1`), and inspected the full
uncommitted diff; the fix Agent's remapped-port (8010/8011/8090) `--stub` standup returned the
`http://127.0.0.1:8010/chart/<hex>` URL + certificate HTTP 200 (verifier-logged `propose-spec 200`
+ `cert 200`), teardown freed all three ports, tree clean. No coverage-source Python changed → the
ruff/mypy/pytest gate is unaffected (last green at M7.2: 1564 @ 100% branch).

### Post-close challenger findings (independent adversarial re-audit) — dispositioned

An independent read-only challenger re-audited the launcher after the close above; MAIN validated
each item against the committed tree and the follow-up worktree.
- ALREADY CLOSED by the fixes folded above (its static pass read a pre-fix snapshot): the port/URL
  topology (all child endpoints derived + exported, incl. `VERIFIER_MODEL_BASE_URL`), the unbounded
  readiness `curl` (`--connect-timeout` / `--max-time`), the two hardcoded-venv preconditions (now
  `$UV_PROJECT_ENVIRONMENT` / `$WEBUI_PROVISION_WEBUI_BIN`), and the HIGH "a second launcher adopts
  then destroys a running stack" scenario (the start-time `port_in_use` preflight refuses BEFORE
  `trap cleanup` and the pidfile, so a collision never `fuser -k`s or overwrites the pre-existing
  stack).
- FIXED here (genuinely open after that close, one cohesive batch): (finding-4) `wait -n 2>/dev/null
  || true` masked a post-READY required-service crash as exit 0 while `SERVICE_NAMES` sat unused →
  now captures the status, names the dead child via `SERVICE_NAMES`, and exits non-zero through a
  subshell `(exit …)` so a bare top-level `exit` never trips ShellCheck SC2317 on the EXIT-trap-only
  helpers (`set -e` propagates the status; the EXIT trap still tears down). (finding-5)
  `.venv-model/bin/python` was hardcoded with no override, falsifying "every default overridable" →
  added `MODEL_BACKEND_PYTHON` (used by the precondition and the accel `exec`). Plus: the `fuser`
  backstop now fires only on a port STILL bound after the precise group kills (with a log line), and
  `wait_http` checks the child PID before trusting a `curl` 2xx.
- SEPARATE FOLLOW-UP (pre-wait / final-wait crash-detection robustness — root mechanism UNPROVEN):
  the observed trigger was a verifier killed at its bootstrap line (`models=1 tool_servers=1`), BEFORE
  READY, that left the launcher blocked with ports still up until a manual TERM (clean rc143). PROVEN:
  killing a TRACKED service leader post-READY makes the final `wait -n` return and the F-block name it
  (finding-4 rc137); a death during a service's OWN readiness gate is caught within ~1s by that gate's
  `kill -0`; and each `wait_http` is a wall-clock `while (( waited < timeout ))` loop, so a block
  DURING readiness is bounded by that service's `*_READY_S` (default 180s) regardless of PID tracking
  → `die`. NOT proven (the actual gap the challenger named): whether a REAL inner-service crash always
  propagates to the tracked `setsid` leader that `wait -n` / `kill -0` observe — the launcher relies on
  `exec` (accel model) and `uv run` exit-forwarding (verifier / webui) for that, untested; if a leader
  could outlive a crashed descendant, the post-READY final `wait -n` (no wall-clock timeout, unlike
  readiness) could block indefinitely. That worst case is a HANG (a stuck stack surfaced as no-exit / a
  dead endpoint, or rc130/143 on Ctrl-C/TERM), NOT the finding-4 exit-0 false-clean — so the finding-4
  hazard stays closed. Both the challenger and the fix Agent concur on deferring; the artifact ships
  crash-faithful for the proven paths. Follow-up for M8: (1) confirm the killed/crashed PID is the
  tracked setsid leader and dead afterward; (2) validate all tracked PIDs immediately before the READY
  banner / final wait; (3) switch the final wait to explicit tracked-leader operands via
  `wait -n -p VAR pid…` so it monitors the leaders, not any job. No launcher change in this review.
CLOSED (follow-up): MAIN independently reran `shellcheck` rc=0 + `bash -n` rc=0 on the final tree,
confirmed no new `# shellcheck disable` (only the pre-existing SC2016) and the exact six-edit diff,
and reproduced the mechanism (killing a READY verifier → launcher rc 137 naming `service verifier
exited (status 137)`, ports freed; `MODEL_BACKEND_PYTHON=/nonexistent…` → die rc 1, no
`.launch-logs`). Committed in the follow-up `webui (M7 review): …`. M7 stays REVIEWED.

### Post-review follow-up: browser default-tool auto-attach (user-reported) — CLOSED

User hit the real-OWUI browser instance — a chart prompt called the model, which returned a code
snippet: no plot, no verifier call. Root cause (OWUI 0.10.2 source; `.agent/memory.md` holds the
full mechanism): M7 registered `server:verifier` as a GLOBAL tool server (OWUI lists it *available*)
but never attached it to the model, and OWUI auto-attaches a global server to NO chat — the browser
frontend pre-selects a model's `meta.toolIds`, the chat backend resolves only request `tool_ids`,
neither adopts a merely-available global server. So a browser chat was never offered the verifier
absent a manual toggle — exactly the M7.2 walkthrough observation ("a persisted chat IGNORED the
tool → raw matplotlib, no verified chart"), and the undocumented step behind the root-README "Try it
in your browser" verified-path claim.
- FIXED: `bootstrap.run_bootstrap` converges the workspace model's `meta.toolIds` → `server:verifier`
  via new `WebUIClient.ensure_model_tool` (create-or-merge: 404→create, else a non-destructive update
  preserving `params`/other `meta`, idempotent no-write when already attached, fail-closed final-GET
  readback) + `WebUIClient.model_tool_ids` readback; `SmokeResult` gains
  `model_tool_ids`/`model_tool_attached` and `ok` now also requires model-tool-attached (clean banner
  `models=1 tool_servers=1 model_tools=1`). Root `README.md` + `webui/README.md` state the auto-offer;
  `.agent/memory.md` holds the durable mechanism. Headless `run_persisted_chat` is unchanged (it
  already sends `tool_ids` explicitly); `access_grants` omitted (moot on this single-admin instance).
- EVIDENCE (MAIN, live real OWUI 0.10.2, `--stub` standup): `model_tool_ids(model_id)` =
  `['server:verifier']` (browser auto-attach proven), the model still enumerated (omitting
  `access_grants` hid nothing), and a persisted chat returned the verified chart + DSSE-certificate
  URL (the completion path is intact under create-or-merge). Gate independently re-green: ruff format
  / ruff check / mypy 93 files / pytest 1590 @ 100% branch (`webui/` stays coverage-excluded → its
  new `+619/-131` tests don't gate coverage). Stack torn down (SIGTERM pidfile), :8000/:8001/:8080
  freed.
CLOSED: committed `webui: … (M7 followup)`. M7 stays REVIEWED — provisioning + docs only; no verifier
trust or claim boundary moved (browser/pixels stay TCB; the guard stays a bypassable guardrail).

A minimal, human-facing standup: one launcher brings up the existing verifier + `model_backend`
(the REAL local OpenVINO model, per `CLAUDE.local.md`) + Open WebUI, provisioned, so the operator
opens `http://127.0.0.1:8080` in a browser and interactively exercises the verified-plot pipeline.
Adds NO verifier trust and moves NO claim boundary — Open WebUI, its function runner, the
iframe/browser, and pixels stay trusted display/orchestration (POC_SCOPE TCB), exactly as M4
established. New surface = orchestration + operator docs only; every service, provisioning step,
and the chart/embed contract already exist (M3 `model_backend`, M4 `webui/`, M5 verifier, M6
persisted-chat + demo). Not in the outline (seed 0–15 consumed by M1–M6) — a user request layered
on the finished PoC. No new deps; no web research (all-local, already probed — `CLAUDE.local.md` +
`bench/README.md` "OpenVINO wiring" + memory Stack cover OpenVINO).

**Gate: live stack (verifier + OpenVINO `model_backend` + Open WebUI) — CONFIRMED at this planning
turn.** Artifact probes this session: `models/Qwen2-0.5B-Instruct-int4-sym-ov/`, `.venv-model/`
(openvino imports only after the accel env is sourced — expected), and `.venv-webui/bin/open-webui`
all present; the host accel farm is intact (`/var/home/eturkes/.local/app/intel-accel/env.sh`,
`.../openvino_genai/python/`, `.../intel-accel/selftest.py`). The M6 gate probe (same container,
this session-lineage) already live-confirmed the full stack (intel-accel selftest CPU/GPU/NPU
`correct=True`; NPU backend `/v1/models`; `webui serve`→`/ready`; `bootstrap` exit 0). M7.2's live
standup re-confirms at run.

Scope reconciliation + banked decisions (recon this session — read, don't re-derive):
- **"Local model" = the existing `model_backend` on OpenVINO** (`CLAUDE.local.md`: prefer OpenVINO,
  device preference NPU>GPU>CPU). NO `model_backend` code change: `Engine.load` gates the NPU
  static-shape property by substring — `if "NPU" in settings.device` (`model_backend/engine.py:82`)
  — so any NPU-bearing device string already carries `MAX_PROMPT_LEN`. Launcher DEFAULT
  `MODEL_BACKEND_DEVICE=NPU` (top preference; M3/M6 live-confirmed, byte-deterministic greedy
  ~68 tok/s). `AUTO:GPU,CPU` is the documented dynamic-shape fallback knob; `AUTO:NPU,GPU,CPU` /
  `HETERO:...` stay probed experiments, not the default (bench/README: AUTO may transiently run on
  CPU while compiling, and static-shape `MAX_PROMPT_LEN` + AUTO fallback is fragile).
- **Accel-env recipe is load-bearing** (bench/README "OpenVINO wiring", authoritative,
  host-coupled): before `model_backend` the launcher must `source
  /var/home/eturkes/.local/app/intel-accel/env.sh` and prepend
  `/var/home/eturkes/.local/app/openvino_genai/python` to `PYTHONPATH`, then run
  `.venv-model/bin/python -m model_backend` DIRECTLY (loader paths are consumed at exec;
  `uv run`/`-E`/`-I` strip `PYTHONPATH`). Both host paths become launcher env overrides defaulting
  to these values. Wait for `/health`=200 (~7 s cold compile). The verifier imports no OpenVINO →
  it launches via `uv run --locked python -m verifier.service` (no accel/`PYTHONPATH` needs).
- **Orchestration order is load-bearing** (webui/README): verifier `/health` → backend
  `/v1/models` → OWUI `/ready` → `webui bootstrap` (OWUI re-fetches each tool-server's OpenAPI and
  drops an unreachable one, so the verifier must be up first). `webui serve` `os.execve`s (the
  harness `_serve`) → the launcher backgrounds it as a child; a SIGINT/EXIT trap tears every child
  down and frees :8000/:8001/:8080. `:8001` serves stub XOR backend (one port).
- **Honest weak-model framing** (M3: the real NPU verifies 0/100 — 97/100 markdown-fenced, decode
  refused; → M8.3's schema-guided default now verifies 26/100, still a minority — see M8): with the REAL local model the browser honestly shows blocked verdicts + the
  `Verified Plot Guard` outlet notice — that IS the PoC (a trusted verifier holding against a
  fully-failing untrusted proposer). A `--stub` flag swaps `model_backend`→`webui stub` (the
  deterministic known-good `sales.csv` spec) for the verified-chart happy path, hardware-free. Docs
  must set this expectation so a curious operator doesn't read "blocked" as "broken".
- **Browser render is the operator's step, and the TCB boundary.** chromiumfish is BLOCKED in the
  agent execution container (SwANGLE/Vulkan EGL init fails — memory M6.3; the M6-plan probe ran on
  the host). The agent verifies up to the browser boundary (served chart HTML + CSP `sandbox
  allow-scripts` + `embeds[0]` URL + fetched certificate + textual persisted-chat DOM); the
  operator crosses it, which is also POC_SCOPE's trusted-display line. So "open it in my browser"
  is genuinely the human's action; the milestone delivers + verifies the browser-ready instance.
- **Personal-instance state**: bootstrap is idempotent and the admin user + owned function persist
  in `.webui-data/` → the launcher KEEPS `.webui-data` across runs (fast re-launch); `--fresh`
  wipes it. Default admin `operator@localhost` / `loopback-dev-password` (loopback dev defaults,
  overridable via `WEBUI_PROVISION_*`). The launcher raises the verifier work-rate
  (`VERIFIER_WORK_RATE_PER_MINUTE`/`_BURST`, per the webui/README smoke) so interactive clicking
  isn't 429-throttled.
- **Placement**: launcher = committed `webui/launch.sh` (co-located with the harness it invokes;
  root README + webui/README point to it), bash — outside the ruff/mypy/pytest gate, like the rest
  of `webui/`. M7 changes no `verifier` coverage-source Python, so the existing gate (ruff/mypy/
  pytest 1563 @ 100% branch) stays green unchanged; acceptance is a live standup recorded as
  evidence, per M4/M6 precedent.

Sizing: one bash orchestrator + operator docs over already-built services — small. Two units
isolate the hardware gate (mirroring M6's deterministic-then-live shape); both fit well under the
~200K aim.

- **M7.1 — one-command launcher + hardware-free (`--stub`) standup** (DONE): author
  `webui/launch.sh`, a repo-root bash orchestrator that (1) optionally `--fresh`-wipes
  `.webui-data`; (2) starts the verifier (`uv run --locked python -m verifier.service`, raised
  work-rate) and waits `/health`; (3) starts the model tier — default REAL `model_backend` (source
  accel env + OpenVINO `PYTHONPATH`, `.venv-model/bin/python -m model_backend`, device default
  `NPU`) XOR `--stub` (`webui stub`, hardware-free) — and waits `/v1/models`; (4) starts
  `webui serve` (backgrounded child) and waits `/ready`; (5) runs `webui bootstrap`; (6) prints the
  browser URL + admin creds + a one-line "what to try"; (7) traps SIGINT/EXIT to tear all children
  down and free the three ports. Host accel paths, device, creds, and ports are env overrides with
  the confirmed defaults. Acceptance (HARDWARE-FREE, MAIN-executed in the agent container):
  `webui/launch.sh --stub` brings the stack up, all three health endpoints answer,
  `python -m webui chat --prompt "…total revenue by month from sales.csv."` returns the stub
  summary + a `/chart/{plot_id}` URL whose fetched certificate verifies, and the trap tears
  everything down with :8000/:8001/:8080 freed; evidence recorded. Existing Python gate reruns
  green (unchanged — no coverage-source edit).
  Landed executable `webui/launch.sh` (repo-root bash orchestrator, SPDX header) + `.gitignore`
  entry for `.launch-logs/` (per-service `*.log` + `launch.pid`, regenerable). It is bash, outside
  the ruff/mypy/pytest gate, so shellcheck is its quality gate (clean; one justified
  `# shellcheck disable=SC2016` on the single-quoted `bash -c` accel child) and `bash -n` parses.
  Design: each service starts under its own `setsid` session/process-group, so `cleanup`
  group-kills (`kill -- -pgid`, 10s grace, then `SIGKILL`) with a `fuser -k` port backstop that
  frees every straggler; `trap cleanup EXIT` + `trap 'exit 130' INT` + `trap 'exit 143' TERM`; the
  launcher blocks on `wait -n`. Standup order is verifier `/health` → model `/v1/models` →
  Open WebUI `/ready` → `webui bootstrap` → banner (browser URL + admin creds + a what-to-try
  line). Every host path/device/cred/port/timeout is an env override with the confirmed default
  (ports 8000/8001/8080, `MODEL_BACKEND_DEVICE=NPU`, accel `INTEL_ACCEL_ENV` /
  `OPENVINO_GENAI_PYTHON`, `operator@localhost` / `loopback-dev-password`, work-rate 10000). Real
  model tier = accel env sourced + OpenVINO `PYTHONPATH` prepended in a subshell then
  `.venv-model/bin/python -m model_backend` DIRECTLY (uv run/`-E`/`-I` strip PYTHONPATH); the
  `--stub` tier = `uv run --locked python -m webui stub`; `--fresh` wipes `.webui-data`. Live
  hardware-free acceptance (MAIN, agent container): `webui/launch.sh --stub --fresh` reached READY;
  all three health endpoints answered; `python -m webui chat` returned "Figure Verifier confirmed
  the chart; all checks passed." + `http://127.0.0.1:8000/chart/<64-hex>`; the fetched
  `/certificate/{plot_id}` verified under the advertised `/key/{keyid}` Ed25519 key via
  `attestation.verify_vcert` (vcert-0.2, 10 checks, keyid `sha256:88ca1e07…`). Teardown proven
  twice: programmatic SIGTERM → cleanup → :8000/:8001/:8080 freed (0 listeners), AND an operator
  Ctrl-C under a real controlling PTY → INT trap → `exit 130` → cleanup → ports freed. Teardown
  gotcha (durable; → memory at M7.2): a `&`-backgrounded launcher inherits SIGINT=`SIG_IGN` (bash
  cannot trap a signal ignored on entry to a non-interactive shell), so the INT trap is a silent
  no-op ONLY when backgrounded — SIGTERM/EXIT still tear down and interactive Ctrl-C works
  (PTY-proven); programmatic teardown uses SIGTERM or the `.launch-logs/launch.pid` pidfile. Gate
  re-green unchanged: ruff format 93 / ruff check / mypy 93 / pytest 1564 @ 100% branch.
  Context: `main=85% 230K/272K`; `impl=36% 98K/272K` (implementing Agent).
- **M7.2 — real local-model browser walkthrough + operator docs + M7 close** (DONE): run
  `webui/launch.sh` with the REAL local model (`MODEL_BACKEND_DEVICE=NPU`, per `CLAUDE.local.md`);
  confirm the live standup (accel selftest / backend `/v1/models` / OWUI `/ready` / bootstrap
  `models=1 tool_servers=1`); drive one persisted chat through the real model and record the honest
  outcome (blocked verdict + `attempt_id`, plus the guard block/pass outlet differential —
  observations, never bounds); prove the browser-ready surface textually for a `--stub` verified
  case (served chart HTML/CSP + `embeds[0]` + certificate), since the real model produces no chart.
  Author the human-facing docs — a root-README "Try it in your browser" section (one command → open
  `http://127.0.0.1:8080` → log in → what to type → what to expect with the real weak model vs
  `--stub`) + a `webui/README.md` "interactive instance" pointer at `launch.sh`, reconciled with
  the existing multi-terminal recipe; `.agent/memory.md` gains only durable M7 facts. MAIN closes
  M7 (set M7.1+M7.2 DONE, M7 IMPLEMENTED, record main=/impl=, commit). Acceptance: the launcher
  stands the real-model instance up browser-ready; docs match the launcher and set the honest
  weak-model expectation with the `--stub` happy-path pointer; no overclaim (pixels/browser stay
  TCB; the guard stays a bypassable guardrail); existing gate green; M7 IMPLEMENTED.
  Done (MAIN-executed live evidence run + docs — the launcher landed in M7.1, so M7.2 adds only the
  walkthrough + operator docs, no implementing Agent). Precondition reconfirmed this session:
  OpenVINO 2026.2.1 + `openvino_genai` import in `.venv-model` with the accel env sourced, NPU
  enumerated (`['CPU','GPU','NPU']`) — the exact environment the real `model_backend` child runs in
  (so the accel farm/NPU DO work in this container; only chromiumfish/GL is blocked, per M6.3 → the
  browser render stays the operator's step). REAL-NPU standup: `webui/launch.sh --fresh` reached
  READY — verifier `/health`, backend `/v1/models` (serving `Qwen2-0.5B-Instruct-int4-sym-ov`,
  `owned_by=openvino`), OWUI `/ready` all 200; idempotent `bootstrap` → `models=1 tool_servers=1`
  (signup 403 → signin 200, admin persists); launcher alive on the `.launch-logs/launch.pid`
  pidfile. REAL-MODEL walkthrough (observations, never bounds): three live `/propose-spec` →
  `verified=False`, `layer=decode`, `spec.decode`/`schema_validation`/`fail`, three distinct
  `attempt_id`s (`e9582b62…`/`25da6705…`/`6c94ad52…`; the CSPRNG nonce distinguishes even the
  repeated sales.csv prompt), replies fenced-then-rambling (runaway digit string) XOR `bare_object`,
  messages `JSON malformed: invalid character (byte 0)` / `Input data was truncated`; `python -m
  verifier.service audit e9582b62…` → `attempt-audit-0.1`, DSSE `valid` under
  `current-or-explicitly-pinned`, outcome `rejected`, `plot_id: null`, keyid `sha256:88ca1e07…`,
  all five blobs (raw_spec/verdict/model_request/model_response/model_reply) as redacted
  metadata+digests only. Guard differential via `/api/chat/completed` — chart-looking →
  `BLOCKED_NOTICE`, prose unchanged; a persisted chat through the real model IGNORED the tool and
  returned raw matplotlib code (no tool call, `embeds[0]` empty → no verified chart) — exactly the
  chart-looking reply the browser's outlet blocks. `--stub` BROWSER-READY surface (the real model
  produces no chart): `webui/launch.sh --stub` → persisted chat returned `Figure Verifier confirmed
  the chart; all checks passed.` + `embeds[0]` = `…:8000/chart/0415e6a1…`; the served page is HTTP
  200 `text/html` under CSP `sandbox allow-scripts` (no `allow-same-origin`) with server-rendered
  `Verified`/`Checks passed` + `vcert`/`vplot-signature` markup + the plot_id; the fetched
  `/certificate/{plot_id}` DSSE-verified via `attestation.verify_vcert` under the advertised
  `/key/{keyid}` Ed25519 key — `vcert-0.2`, all five bound hashes
  (dataset/spec/plotted_table/manifest/vega_lite), 10 passing checks (4 `construction` + 4
  `deterministic_recompute` + 2 `z3_smt`: `sort.canonical_order`, `scale.bar_zero`), keyid
  `sha256:88ca1e07…` (same signing identity across both passes, from the reused `.verifier-state`).
  Teardown proven both passes: SIGTERM to the pidfile → launcher exited in ~3 s → `cleanup` freed
  :8000/:8001/:8080 and removed the pidfile (the backgrounded INT-trap no-op held; the SIGTERM path
  was exercised, per the M7.1 gotcha now banked in memory). State torn down —
  `.launch-logs`/`.webui-data`/`.verifier-state` removed, tree clean, ports free. DOCS: root
  `README.md` gained a `## Try it in your browser` section (one command → open
  `http://127.0.0.1:8080` → log in → what to type → the honest real-weak-model expectation vs the
  `--stub` verified happy path, with the browser/pixels-TCB + bypassable-guard boundary);
  `webui/README.md` gained a `## One-command interactive instance` section pointing at `launch.sh`,
  reconciled with the per-terminal recipe it automates; `.agent/memory.md` gained two durable M7
  bullets (launcher contract + teardown gotcha; the honest walkthrough + the accel/NPU-works-here /
  only-GL-blocked clarification). No overclaim: pixels/browser stay TCB, the guard stays a bypassable
  guardrail, every model observation is framed as an observation not a bound. Docs-only (coverage
  source stays `verifier`): gate INDEPENDENTLY re-green — ruff format 93 / ruff check / mypy 93 /
  pytest 1564 @ 100% branch (unchanged from M7.1). M7 IMPLEMENTED (M7.1 + M7.2 both DONE).
  Context: `main=76% 207K/272K`; `impl=(none — MAIN-executed live evidence run + docs; the launcher
  itself landed in M7.1)`.

---

## M6 — End-to-end demo   (REVIEWED)

### Review ledger: M6 REVIEWED — all dispositions closed

Lenses (correctness/integration/conformance/efficiency) + a README-evidence audit over M6.1–M6.4
(`git log --grep "(M6[. ]"`); every accepted fix folded into this review commit, no separate batches:
- FIXED code: W2 `_run_webui_leg` → fail-closed when the persisted chat yields no chart (was a
  false PASS); `test_main_with_webui_fails_when_chat_produces_no_chart` locks it. W1
  `--with-webui`/`--with-model` → mutually-exclusive argparse group (enforces the :8001
  stub-XOR-NPU constraint the CLI never checked) + a both-flags rejection test.
- FIXED docs: roadmap M6.2 dropped an impossible "100 new tests" count; roadmap M6.3 replaced the
  invalid combined `--with-webui --with-model` command (now argparse-rejected) with the two separate
  passes; README repo-layout tree gained the omitted `tests/`.
- ADJUDICATED honestly-bounded, no change (README PoC criteria): item 8 inline-chart (global claim
  excludes "what reaches the screen"), item 9 guard (boundary = heuristic/bypassable/usability-only,
  never verification — matches POC_SCOPE), item 10 replay/cert (POC_SCOPE:40-44: keyid =
  unauthenticated hint, no PKI). A README-link "blank-line split" flag was a lossy-read artifact, not
  real. Modest-claim + TCB verbatim from POC_SCOPE; cert-auth soundness + reason-string exactness
  confirmed, empirically corroborated by the green `python -m demo.e2e` (reasons, both z3_smt checks,
  "no external PKI claim").

CLOSED: M6 REVIEWED — gate independently reran green (ruff/mypy clean, 1,564 passed @ 100% branch,
demo 3/3, exit 0).

**Gate: full stack (M3+M4) — CONFIRMED live at this planning turn.** Fresh probes this session:
intel-accel selftest enumerated CPU/GPU/NPU all `correct=True`; the NPU `model_backend` served
`/v1/models` and a live `/propose-spec` returned a 200 verdict in ~12 s with a real fenced NPU
reply (the first call during cold NPU compile returned the typed 503 upstream path WITH a
committed `attempt_id` — M5 capture working live); `python -m webui serve` on the existing
`.venv-webui` answered `/ready` and `python -m webui bootstrap` exited 0 (`models=1
tool_servers=1`); `chromiumfish` present on host (`--headless=new --no-sandbox --disable-gpu`,
optional `--print-to-pdf --no-pdf-header-footer` + `pdftoppm`; avoid the virtual-time/compositor
flags — they can hang). Services stopped after probing; `.webui-data/` + `.verifier-state/` are
operator/disposable state, never test sinks (demo runs use tmp state dirs).

Scope reconciliation (seed 15 + "Suggested PoC acceptance criteria"): the live NPU model verifies
0/100 (M3 eval; pre-M8 unconstrained — M8.3's guided default reaches 26/100, a minority, still not
reliable), so seed case 1 "model proposes → chart renders" is NOT reliably reachable
model-first. The demo therefore layers honestly, mirroring M4.5: a DETERMINISTIC layer proves the
three cases + the full integration chain from a clean checkout (direct API cases; scripted-stub
Open WebUI chain), and a LIVE-NPU observation layer meters the real weak model on the same
prompts (expected: blocked, specific reasons, audit-diagnosable — which IS the PoC story; claim
discipline: observations, never bounds). Case mapping — case 1 = g01 verified chart +
certificate + replay; case 2 = b07 (`schema.fields_exist`: "filter field 'profit' is absent from
sales.csv", the seed's exact scenario); case 3 = policy pair: b13
(`label.quantitative_units_present`, POLICY family) as the 200 policy verdict AND a crafted
g01+`"scale":{"zero":false}` variant proving the misleading-baseline vector is UNREPRESENTABLE
(decode-refused unknown field; `scale.bar_zero` instead rides every verified certificate as a
`z3_smt` pass). Acceptance-criteria sweep (all 10) closes the milestone. No new deps; no web
research needed (all-local stack, already probed).

- **M6.1 — deterministic three-case demo driver** (DONE): add `demo/e2e.py` + `python -m demo.e2e`
  driving a REAL-socket verifier it spawns itself (subprocess `python -m verifier.service`, tmp
  `VERIFIER_STATE_DIR`, free port — reuse the `tests/test_service_live.py` spawn/poll pattern;
  hardware-free, no model backend: direct `/verify-and-render` + `/verify-only`). Cases: (1) g01 →
  verified chart, print all five certificate hashes + check id/method lines, fetch
  `/certificate/{plot_id}` + `/chart/{plot_id}`, restart the subprocess, `/replay/{plot_id}` exact
  → chart repopulated; (2) b07 → blocked, print the specific `schema.fields_exist` message; (3)
  b13 → blocked policy verdict + crafted scale-zero spec → decode-refused (unrepresentable), print
  both reasons + note the certificate's `scale.bar_zero`/`z3_smt` line from case 1. Human-readable
  PASS/FAIL narrative on stdout (logging like `demo/__main__.py`), JSON report to gitignored
  `demo/reports/e2e_report.json` (reuse `walkthrough` report/encode helpers where they fit), exit
  0 only when all cases match expectation. Tests: in-gate pytest spawning the driver end-to-end
  (subprocess, `--no-cov` semantics same as live test — demo stays outside coverage source),
  asserting report shape + case outcomes + specific-reason strings. Recon fast-path (Explore,
  this planning session): reuse walkthrough's transport-neutral helpers `_require`/`_object`/
  `_object_list`/`_response_object`/`_expect_status`/`_expect_problem`/`_attempt_id`
  (demo/walkthrough.py:120-171) + `ScenarioResult`/`WalkthroughReport`/`run_walkthrough`-style
  registry/`encode_report`; do NOT reuse `_certificate`/`_render_*`/`_propose` — TestClient-bound
  (`_certificate` reads `app.state["identity"]`). b13 = weather.csv line y=aqi (manifest has no
  unit); b07 = sales.csv scatter filter field `profit`. Acceptance: `python -m
  demo.e2e` runs clean from a fresh checkout with only `uv sync --locked` (no NPU/webui), report
  shows 1 pass + 2 blocked with the exact reasons, replay-after-restart exact; gate green.
  Landed `demo/e2e.py` (`_VerifierService` owns spawn/restart against one tmp state dir; DSSE cert
  verified under the fetched `/key/{keyid}` Ed25519 key via `attestation.verify_vcert`) +
  `tests/test_demo_e2e.py`. b07 reason = `field 'profit' does not exist in the table` (the plan's
  "absent from sales.csv" was a paraphrase); crafted scale-zero refused as
  ``spec.decode: Object contains unknown field `scale` - at `$.encoding.y```. Determinism boundary:
  spec_id + 5 artifact hashes byte-stable across runs, plot_id + keyid vary per fresh identity.
  Gate green (ruff/mypy/pytest 1532 @ 100% branch + `python -m demo.e2e` exit 0).
  Context: `main=53% 144K/272K`; `impl=49% 132K/272K`.
- **M6.2 — Open WebUI persisted-chat driver** (DONE): extend `webui/` with the persisted-chat
  helper the README leaves as prose: signin → create chat → `POST /api/chat/completions` with
  `session_id`/`chat_id`, assistant `id`, complete `user_message` (id/role/content/timestamp/
  `parentId: null`/`childrenIds:[assistant-id]`) → poll `GET /api/v1/chats/{chat_id}` until the
  assistant message is `done: true` → return final text (`output[0].content[0].text`) + chart URL
  (`embeds[0]`) — reconcile the exact wire shape against the M4.5 evidence commit
  (`git log --grep "(M4.5"`; memory says create-chat-first, README shows the completion fields).
  Expose `python -m webui chat --prompt …` printing text + chart URL; keep `client.py` style
  (`WebUIProvisionError` normalization, no raw-content logging). Recon fast-path (Explore, this
  planning session): `WebUIClient` today = `wait_ready`/`authenticate` (signup→signin fallback;
  no public signin)/`model_ids`/`tool_server_ids`/`ensure_global_filter` — chat/persisted-chat
  helpers do NOT exist anywhere (README:101-145 inline httpx + prose only); CLI subcommands =
  `serve`/`bootstrap`/`stub` (webui/__main__.py:64-80). Tests: `httpx.MockTransport`
  matrix like `tests/test_webui_client.py` (injected-transport `_webui_client` pattern at :58-63)
  (success, poll-pending→done, missing embed, transport/status/JSON faults). Acceptance: against the live hardware-free stack (stub + bootstrap) the
  command returns the stub's final summary + a `/chart/` URL; mock matrix green; gate green.
  Landed `WebUIClient.run_persisted_chat(prompt) -> PersistedChatResult(final_text, chart_url|None)`
  (post-`authenticate()`, reused by M6.3's `--with-webui`) + `python -m webui chat --prompt …`
  (webui/client.py, __main__.py) + MockTransport matrix (test_webui_client.py, test_webui_cli.py).
  Wire shape MAIN-live-PROBED (not guessed) then transcribed: create `POST /api/v1/chats/new`
  `{chat:{models,messages:[],history:{messages:{},currentId:null}}}` → top-level `id`; completion
  `POST /api/chat/completions` (tool_ids from `settings.tool_server_id`) → background
  `{status:true,task_ids,chat_id}`; poll `GET /api/v1/chats/{chat_id}` →
  `chat.history.messages[<assistant_id>].done`, text `output[0].content[0].text`, url `embeds[0]`.
  Poll bounded by `ready_timeout` monotonic deadline (mirrors `wait_ready`); fail-closed on
  missing/empty final text; empty embeds → `None`; loose msgspec wire structs; every fault →
  `WebUIProvisionError`; no raw-content logging. Argparse → `Namespace` (`--prompt` non-empty
  validator, chat-only-required); result → stdout, progress → logger. Live hardware-free acceptance
  (MAIN, real OWUI 0.10.2): stub+bootstrap → `python -m webui chat` returned the stub summary +
  `http://127.0.0.1:8000/chart/<64-hex>`, exit 0 (cold-boot ~110s here). `webui/` coverage-excluded,
  so its new tests don't gate the 100%-branch coverage. Gate green (ruff/mypy + pytest 1556 @
  100% branch). Services/state torn down, ports freed, `.webui-data`/tmp state removed.
  Context: `main=79% 214K/272K`; `impl=59% 161K/272K`.
- **M6.3 — live-stack orchestration + demo evidence run** (DONE): add
  `--with-webui` (drive the M6.2 chat leg against the provisioned stack, record final text +
  chart URL + certificate fetch in the report) and `--with-model` (the three seed-15 prompts
  through live `/propose-spec`; record verdict/failure classes + `attempt_id`s, then shell out to
  `python -m verifier.service audit <id>` for one failure to show post-hoc diagnosability;
  observations, never bounds) flags to `demo/e2e.py`; both default OFF so M6.1's hardware-free
  contract holds; tests stub the legs (no live deps in gate). MAIN then executes the full live
  evidence run: three terminals recipe (NPU backend, verifier, webui serve + bootstrap), `python -m demo.e2e --with-webui` /
  `--with-model` (separate passes), the README outlet block/pass differential, and a
  chromiumfish `/c/{chat_id}` capture proving the embedded verified chart + badge (browser
  evidence stays textual in this roadmap per M4.5/M5.3c precedent — no literal M4.5 command
  survives, only the flag skeleton above; binary resolves via `command -v chromiumfish`; captures
  deleted after inspection). Acceptance: flags off = byte-identical M6.1 behavior; live run records chart
  embedded in Open WebUI, model-leg verdicts + one audited attempt, outlet differential; evidence
  paragraph lands here at close; gate green.
  Landed `demo/e2e.py` `--with-webui`/`--with-model` (both default OFF; flags-on wraps the M6.1
  `WalkthroughReport` in an `E2EReport` adding `webui`/`model` blocks) + hardware-free
  `tests/test_demo_e2e_legs.py` (stubbed legs: byte-identity flags-off, chart-cert webui leg,
  `_propose_once` MockTransport matrix, `--with-model` audit). Live evidence run (MAIN, real OWUI
  0.10.2 stack) is TWO passes because the model backend — stub XOR NPU — shares :8001 (`--with-webui`
  needs the stub for a valid spec→chart; `--with-model` needs the NPU for realistic blocked
  verdicts): (A) STUB pass — bootstrap `models=1 tool_servers=1`; `--with-webui` → 3/3 cases PASS +
  webui leg PASS: persisted chat "Show total revenue by month." → "Figure Verifier confirmed the
  chart; all checks passed.", chart `…:8000/chart/ea130823…`, certificate verified under keyid
  `sha256:bdc125e4…` (5 artifact hashes); persisted-chat DOM (chat `30b5b298…`) assistant
  `done=true`, legacy `content=""`, `embeds[0]`=that chart URL; chart served under CSP
  `sandbox allow-scripts` with server-rendered "Verified"/"Checks passed" + `vcert`/`vplot-signature`
  markup. README Live-outlet differential: chart-looking content → `BLOCKED_NOTICE`, prose unchanged.
  (B) NPU pass — `--with-model` → model leg PASS: all 3 seed prompts http 200 `verified=False`
  `spec.decode` "JSON is malformed: invalid character (byte 0)", distinct `attempt_id`s
  (`921b13e9…`/`18cdabb6…`/`b0a1dcaa…`); `921b13e9…` audited via `python -m verifier.service audit`
  → `audit_ok=True`. Live NPU greedy decode overran the 20s hardware-free hang-guard on a
  token-emitting prompt → dedicated `_MODEL_REQUEST_TIMEOUT_S=180` (model leg only; deterministic
  cases keep 20s). Flags off: `python -m demo.e2e` writes the bare 6-field `WalkthroughReport` (no
  webui/model) — byte-identical M6.1 behavior (in-gate test locks it). chromiumfish capture
  attempted with BOTH a virtual-time DOM dump and the banked `--headless=new --print-to-pdf`
  recipe — both rc=124 hangs: this execution container's software-GL (SwANGLE/Vulkan EGL) fails to
  initialize (GPU process exits, no frame renders) compounded by GCM background-network retries
  (the M6-planning probe ran on the host, not here). Browser render therefore rests on M4.5's
  reviewed Chromium precedent + the textual DOM/CSP proof above (roadmap keeps browser evidence
  textual per M4.5/M5.3c). Gate green (ruff/mypy 93 files + pytest 1563 @ 100% branch, demo.e2e flags-off
  exit 0). Services/state/captures torn down, ports 8000/8001/8080 freed,
  `.webui-data`/`.verifier-state`/tmp removed.
  Context: `main=48% 131K/272K`; `impl=(flags+tests landed prior session; pct not recovered
  post-compaction — MAIN ran the live evidence run + timeout fix this session)`.
- **M6.4 — root README + PoC acceptance sweep + M6 close** (DONE): author the repo's missing
  root `README.md` — what the PoC is, the modest claim (verbatim boundary from POC_SCOPE), trust
  spine diagram, repo layout, quickstart (`uv sync --locked` → gate → `python -m demo` →
  `python -m demo.e2e`), live-stack recipe pointers (bench/webui READMEs), license note. Sweep
  the seed's 10 PoC acceptance criteria into a short "PoC acceptance" record (criterion →
  where proven: filter differential, propose-only construction, recompute-by-construction,
  bench 18/18+10/10, demo cases, chat embed, replay/certificate) — POC_SCOPE or README, one
  place, no overclaim (bypassable filter stays a guardrail, pixels stay TCB). Reconcile
  demo/webui READMEs with the new commands; `.agent/memory.md` gains only durable M6 facts.
  Acceptance: every criterion maps to landed evidence or an explicit modest-claim boundary; docs
  agree with commands; gate green; M6 IMPLEMENTED.
  Landed root `README.md` as the SINGLE PoC-acceptance sweep (POC_SCOPE left as the stable
  claim-boundary reference, not duplicated): what-it-is + the modest claim quoted VERBATIM from
  POC_SCOPE (the four-artifacts "Verified means …" definition + the "line we hold" TCB paragraph,
  both byte-exact — MAIN-verified against POC_SCOPE:22-33/78-82; the two `grep -F` "misses" were
  newline-wrap false negatives) + an ASCII trust-spine (model proposes ONLY a spec → verifier
  recomputes ALL plotted data + re-binds dataset by hash → allowlist builder inlines only that →
  renderer + DSSE VCert v0.2 5 hashes; pixels/`vl-convert`/SVG-raster/browser stay TCB) + repo
  layout + hardware-free quickstart (`uv sync --locked` → gate → `python -m demo` →
  `python -m demo.e2e`) + live-stack pointers (bench/webui READMEs; `--with-webui`/`--with-model`
  off-by-default, :8001 stub-XOR-NPU) + `Apache-2.0 WITH LLVM-exception`. All 10 seed criteria map
  to landed evidence + an explicit modest boundary (guard bypassable #1/#9, corpus-bound not
  universal #5/#6, browser-textual/pixels-TCB #8, replay-not-model/drift→diagnostic #10). Code
  anchors MAIN-checked to resolve (`checks.verify_run`/`eval.evaluate_run`/`render.prepare_render`/
  `render.build_vega_lite`/`ProposeRequest`/`WebUIClient.run_persisted_chat`/`BLOCKED_NOTICE`).
  `demo/README.md` gains a `python -m demo.e2e` three-case section; `webui/README.md` gains the
  `python -m webui chat --prompt …` pointer; `.agent/memory.md` gains one durable line. Docs-only
  (coverage source stays `verifier`): gate INDEPENDENTLY re-green — ruff format 93 / ruff check /
  mypy 93 / pytest 1563 @ 100% branch (all unchanged) + `python -m demo` 13/13 + `python -m demo.e2e`
  3/3, exit 0. M6 IMPLEMENTED (M6.1–M6.4 all DONE).
  Context: `main=56% 153K/272K`; `impl=69% 189K/272K`.

---

## M5 — Formal + provenance hardening   (REVIEWED)

### Review ledger: M5 REVIEWED — all dispositions closed
Lens findings dispositioned. Fixed→commit (`git log --grep "(M5 review"`):
- FIXED: BA-1/BND-2/BA-5/SA-1/SA-4/D2 → 78360e8; FA1/FR1/FR2/L1.4/L1.3 → 6079a24; D5 (dead cert/spec render-LRU + settings drop) → 08a2666; crosscheck#1/#2 → e5925a8; model#1/#2 (propose-spec `from None` exc-sever + suppress-guarded aclose) → 65d6a52. crosscheck#3=BA-5, crosscheck#4=BND-2.
- WITHDRAWN: L1.6 — proposed recomputation-mismatch arm was a semantic regression (payload_match embeds TCB verifier-version → benign drift misreported); exact→drift→else path retained, tests reverted.
- D1–D7 (user-approved "all rec"): D1 archive-integrity TIGHTEN (=BA-1/BND-2/BA-5/SA-1/SA-4) + NARROW only BND-1 (SVG/verdict-severity bound solely via signed AttemptBundle); D2 synchronous durability = EXTRA (done); D3 hard-link DB reject st_nlink>1 (=SA-4, archive DB, done 78360e8); D4 descriptor→connect TOCTOU (archive.py 2611-2616) = document boundary; D5 remove dead LRU (done); D6 /propose-spec dual-snapshot TOCTOU = document boundary; D7 accept re-run-killed lens coverage.
- crypto#1 (Batch G) FIXED → 1661d7e: identity.py:50 `_READ_FLAGS` += `os.O_NONBLOCK` (writerless-FIFO `os.open` no-hang; reject deferred to validate_state_metadata S_ISREG) + deterministic FIFO-reject regression (thread + bounded join, fails-not-hangs). Files: src/verifier/service/identity.py + tests/test_service_identity.py.
- Batch D (docs conformance) FIXED → ee8695e: BND-1 narrow plot_id claim + memory.md:21; crypto#4 identity public-key "signs"/"complete-graph" wording; crosscheck#6 read_plot_envelope doc; F1 render docstring; F2 memory schema v2→v3; L2.2 examples check-ids; L2.6/SA-6; SA-3; D4/D6 TOCTOU boundary docs; render future-comments. LRU-removal stale refs: memory.md 14(refcount)/74/80(either→chart)/75(render-LRU→no process cache + schema v3)/87(put() ref); roadmap.md 737 module-map (KEEP historical unit-lines); POC_SCOPE.md 133(certs/specs archive-durable, not in-mem render-LRU)/147(either→chart). Record L1.6/model#3/formal#2 dispositions where docs cite them.
- ACCEPT-RECORD (verified at close, no change): crypto#2 (create-if-absent key semantics; within modest rotation/state-loss claims; no claim conflict; not surfaced); crypto#3 (owner st_uid==geteuid + no group/world already enforced → nlink accept); model#3 (stdlib exc_info emits no frame-locals; app.py handlers = trusted faults, kept); model#4 (same-object test); formal#2 (AST-purity hardening); crosscheck#5 (migration streaming → accept-document); D7 (coverage).
CLOSED: M5 REVIEWED — crypto#1 1661d7e + Batch D ee8695e atop the earlier fix commits; full gate independently reran green (1531 passed @ 100% branch, demo 13/13) at each batch.

**Gate: none; toolchain CONFIRMED at planning.** A clean project-local Python-3.13 scratch run
installed the current `z3-solver` + `cryptography` releases, proved an UNSAT integer formula, and
round-tripped an Ed25519 signature; scratch removed, tree stayed clean. The stdlib runtime exposes
SQLite 3.46.1 + defensive connection controls. M5 deliberately uses rollback-journal `DELETE`,
not WAL: SQLite documents atomic rollback-journal commits, while the 2026 WAL-reset bug affects
multi-connection WAL through SQLite 3.51.2. No hardware/service gate.

Scope reconciliation (seed 13/14 + deferred hardening; claim boundary stays modest):

- SMT = a second, bounded checker over the concrete recomputed table + exact builder artifact,
  not a universal proof of evaluator/renderer correctness. Z3 joins the trusted verifier TCB;
  `sat` gives a readable counterexample, `unknown`/timeout/exception fails closed, and no chart
  reaches native Vega rendering. Three obligations are load-bearing: final row order matches the
  active declared sort + canonical tail; every quantitative positional channel on a bar carries
  zero baseline; a discrete color legend's explicit domain equals the plotted categories
  (coverage + no extras).
  Aggregation remains exact deterministic recomputation - encoding it in SMT would add a less
  transparent duplicate implementation, not assurance.
- Resource policy gates each expensive boundary: bounded reads (not `stat`-then-read), CSV
  rows/cells, plotted cells, Vega/model-response/attestation bytes, resident cache payload, solver
  time, concurrent active jobs, and prompt size before the corresponding work; transactional
  logical quota before archive commit. Policy breaches are structured failures; quota never silently
  evicts audit history and does not claim to bound SQLite pages/journals or filesystem overhead.
- VCert becomes a method-bearing signed attestation and adds the exact emitted Vega-Lite hash,
  closing the current four-hash certificate's artifact-binding gap. DSSE authenticates payload
  bytes + their application-specific type; PyCA Ed25519 supplies crypto. Authenticity means
  "the holder of the private key corresponding to this independently pinned public key produced these bytes" - no operator identity, PKI,
  timestamp authority, append-only/completeness, or transparency-log claim. `keyid` is only a
  lookup hint, never a trust decision. A second signed attempt manifest binds occurrence metadata
  + every blob in that occurrence; it prevents undetected modification under a pinned key, not
  record deletion.
- Durable provenance snapshots the exact raw CSV + manifest actually used, canonical spec,
  recomputed table, verdict, emitted Vega-Lite, SVG, certificate payload/envelope, prompt/output
  when a model ran, UTC occurrence time, and tool versions. Live-file references alone are
  rejected: mutation/deletion of `data/` must not break replay. The relational bundle follows
  W3C PROV's entity/activity/derivation shape without adding RDF/PROV dependencies.
- Replay first verifies blob hashes + DSSE against an independently selected trusted key, then
  re-executes from archived bytes through the current verifier. With matching versions/limits and
  successful bounded dependencies, replay requires every certified hash + Vega byte to match;
  resource/solver failure and version/key drift are explicit, never papered over. It does not rerun
  the weak model. Pixels/browser remain trusted display, not replay proof.
- Prompt/sample artifacts can contain sensitive user/data text. Raw audit access stays local to
  the state directory/operator CLI. Unauthenticated HTTP keeps the existing chart/spec surface +
  bounded certificate/key/replay artifacts, never raw source/prompt/model output.

Planning research: official Z3 guidance defines validity as UNSAT of the negated obligation and
documents `sat`/`unsat`/`unknown`; its API also makes contexts thread-confined. OpenVINO exposes
exact prompt tokenization before generation; DSSE v1.0.2 supplies the PAE + JSON-envelope test
vectors and requires the exact verified payload bytes reach the application; PyCA documents
Ed25519 public-key verification; SQLite documents atomic commit + WAL sidecars/reset risk. Current
releases were checked at planning, but `uv.lock` remains the executable version pin once
M5.2b/M5.3a land.

Sizing: M4's one-module units landed at 48-77% of 200K; its cross-layer units repeatedly needed
splits. M5 therefore isolates policy, solver, independent oracle, signing, archive, replay, and
transport. Lowest OPEN unit is next-session work; every unit runs the locked quality gate.

- **M5.1a — core limit vocabulary + bounded ingest** (DONE): add `verifier.limits` with a frozen
  `VerificationLimits` + chunked `read_bounded(path, max_bytes)` that reads at most limit+1 and
  distinguishes genuine absence/operator faults exactly like the existing trusted-file rule.
  Defaults/operator-overridable upper bounds: 8 MiB raw CSV, 256 KiB manifest, 1_000 manifest
  columns, 100_000 source rows, 1_000_000 source cells, 1_000_000 plotted cells, 10_000_000
  evaluator work units, 10_000 render rows, 100_000 SMT terms, 16 MiB Vega JSON, 32 MiB SVG/HTML
  each, 1 MiB attestation payload, 1 s SMT timeout. Thread limits through `ingest.load_table`; cap
  manifest columns and stop the CSV iterator at the first over-limit logical row (quoted newlines
  are one row). Use stable `resource.*` `VerificationError` tags and
  boundary-1/boundary/boundary+1 + hostile quoted-row tests. Acceptance: no over-limit source is
  fully allocated/parsed; corpus unchanged; gate green.
- **M5.1b — bounded verification evidence** (DONE): internal `checks.verify_run` accepts core limits
  and returns public results + `VerificationTrace` (exact bounded source/manifest bytes as each is
  read, including hash/semantic failures) + `RecomputedEvidence` only after every `checks` gate
  (decoded manifest, exact bytes, hashes, and recomputed table included). The type means eligible
  for downstream builder/formal gates, never already certified/rendered; public `verify` remains the
  results-only projection. Add dataset/source/plotted resource checks and surface ingest limit
  exceptions under their own stable tag. Public serialization exposes neither internal object.
  Acceptance: byte/row/source-cell/plotted-cell boundary matrix; failures retain only inputs that
  were actually read, perform no later work, and never carry `RecomputedEvidence`; corpus unchanged;
  gate green.
- **M5.1c — evidence-driven render + Vega budget** (DONE): split core render into a preparation
  entry consuming decoded spec + `RecomputedEvidence` (never `data_dir`) and a prepared-artifact
  renderer. Preparation builds + serializes Vega exactly once, enforces render-row/Vega limits,
  and carries authoritative bytes forward; the renderer mints VCert from the same evidence before
  native work, then enforces VCert-payload/SVG/HTML ceilings. Return authoritative Vega bytes with
  SVG + VCert so downstream archive/signing never rebuilds it. Keep the
  public convenience render as verify -> prepare -> render composition, with one source read.
  Acceptance:
  mutate/delete live CSV after evidence capture and output stays bound to captured bytes; injected
  over-limit row/Vega never calls native render; over-limit native output never stores/returns;
  ordinary bytes stay golden; gate green.
- **M5.1d — service single-pass integration** (DONE): carry trace/evidence in service `Outcome`
  and have `render_outcome` call the core prepare/render entries; preserve decode-time dataset pin +
  every existing direct/propose response shape. Resource breaches are ordinary 200 failed verdicts
  with no store, while broken trusted config remains 500. Acceptance: both render routes read CSV +
  manifest once (spy-pinned), no response exposes evidence, and mutation between stages cannot
  change the artifact; gate green.
- **M5.1e — operator resource settings** (DONE): thread every core/proposer/cache bound through
  frozen service `Settings`; add `VERIFIER_MAX_ACTIVE_JOBS` (default 2), work-rate/burst (120/minute +
  120), and render/chart-cache payload budgets (32 MiB + 128 MiB). Keep field defaults + env
  fallbacks single-sourced; validate finite/positive integers, cross-limit cache compatibility,
  eager `VerificationLimits` construction, and absolute upper arithmetic without allocating.
  Acceptance: exhaustive direct/env/default/invalid/cross-field matrix; every
  core/proposer/cache/admission bound has one typed setting and no ambient read outside `from_env`;
  gate green.
- **M5.1f — process-local service admission** (DONE): implement a lock-safe global token bucket
  with integer monotonic-nanosecond accounting plus a nonblocking active-job capacity gate. Apply
  both before model/worker work on every current POST route and expose the same seam for M5 replay;
  retain the active-job permit through model wait, CPU verification/render, and archive commit so
  it also bounds concurrent CPU workers. Refusal answers RFC-9457 429 before expensive work.
  Keep malformed/oversize request bodies on their existing 4xx path. Test permit release on
  success/exception and cancellation while a native worker continues. Acceptance: one configured
  slot admits one job and deterministically refuses the concurrent second; a cancelled request
  HOLDS its permit until the uncancellable thread actually completes; injected-clock burst/refill
  exactness; bench/live recipes override rate explicitly when needed; no leaked/early-released
  permits; process-local scope + OpenAPI documented; gate green.
- **M5.1g — bounded proposer context** (DONE): reuse bounded CSV/manifest reads in
  `model_client`; bound `ProposeRequest.user_request` by UTF-8 bytes (4 KiB) and the fully assembled
  prompt (32 KiB) DURING assembly before concatenating an over-limit sample - byte/memory bounds,
  not a token-count claim. An operator-provisioned dataset/prompt over policy answers a dedicated
  422 problem+json (no model call, no verification claim), distinct from unknown dataset 404 and
  upstream 502/503. Stream the upstream HTTP response and stop at 128 KiB + 1 byte before JSON decode;
  an oversized success/error envelope is a typed 502; its body bytes never enter trace/archive.
  Preserve raw model failure metering below the bound. Acceptance: spy backend sees zero calls on
  every prompt policy breach; exact-limit request still takes the old path; chunked oversized response proves
  bounded read + no decode; OpenAPI + bench classifiers updated; gate green.
- **M5.1h — exact backend prompt-token admission** (DONE): retain `max_prompt_len` in
  `model_backend.Engine`; add a 128 KiB backend request-body cap; after `apply_chat_template`, call
  the installed tokenizer's `encode` with no duplicate special tokens and
  `max_length=max_prompt_len+1`, then reject an over-limit shape with the exact OpenAI error type
  `prompt_too_long` before `pipe.generate`. Forward the SAME admitted `TokenizedInputs` buffer to
  generation: the installed string overload re-applied the chat template (live 24 admitted → 43
  native tokens), while direct token input held 24 → 24 and preserved decoded output. The verifier
  maps ONLY canonical project-backend status/media/body bytes to its 422 policy problem; every
  other non-2xx stays 502.
  Body-cap + fake-tokenizer/pipe tests pin 413-before-decode, no silently accepted truncation,
  exact token boundary + buffer identity, no native generate, and error-shape spoof resistance.
  The installed CPU + NPU paths live-confirmed exact-bound generation + over-bound preflight; the
  post-fix NPU probe compiled `MAX_PROMPT_LEN=20`, reported 20 native input tokens at that exact
  boundary, then returned `prompt_too_long` for an over-bound request. Acceptance: the formerly
  unexercised NPU static-shape overflow is preflighted and cannot enter generation; gate green.
- **M5.1i — deterministic evaluator work budget** (DONE): `eval.evaluate_run` cumulatively charges
  each transform + closure before entry and returns table + consumed units; the existing
  `evaluate` API remains its table-only projection. Integer formulas: select = fields ×
  (rows+columns), filter = rows+columns, group staging = keys × columns, aggregate =
  (keys+measures) × (rows+columns), sort = rows × ceil(log2(max(rows,2))) × keys, closure = the
  sort formula over every final column. `EvaluationError` preserves the prior check/message while
  carrying admitted units through semantic/resource failures; `VerificationTrace` retains them
  without public serialization. This is logical admission accounting, not a wall-time claim.
  Exact/cumulative/many-sort/group-heavy matrices, all-six-boundary no-start tripwires,
  filter-reduction differential, service trace propagation, and the full corpus pin pass; gate
  green.
- **M5.1j — payload-byte-bounded artifact LRUs** (DONE): `ArtifactStore` enforces independent
  count + exact logical-payload ceilings for render/spec and chart LRUs. Render usage is every
  certificate plus each live shared spec once; chart usage is resident HTML bytes. Replacements
  refresh recency and adjust both accounting directions; oldest entries evict until both
  invariants hold. A standalone render pair/chart over its whole budget rejects before lock/mutation.
  `create_app` threads the already positive/cross-compatible `Settings` budgets, making that branch
  unreachable for policy-conforming outputs. Boundary/shared-spec/replacement/mixed-eviction/
  read-re-put/atomicity matrices pass; removing each certificate/spec/chart add or release update
  fails a focused mutation witness. Exact payload bound only - Python/container overhead remains
  outside the claim; gate green.

- **M5.2a — method-aware result contract** (DONE): `CheckResult` requires one closed method from
  `schema_validation`/`resource_policy`/`deterministic_recompute`/`construction`/`z3_smt`.
  One exact internal check-ID registry derives every core/render/service result method and rejects
  unmapped IDs before serialization; service schema prerequisites, every resource/evaluator
  surface, active deterministic checks, and construction affirmations are classified explicitly.
  The package/service is 0.2.0; OpenAPI requires the five-value enum, and bench independently
  requires the same closed wire vocabulary while recognizing resource-policy verdicts. An
  exhaustive ID/method inventory plus decode/verify/resource/render/OpenAPI/version consumer
  regressions pass; no compatibility field can disagree; gate green.
- **M5.2b — finite SMT obligation engine** (DONE): locked `z3-solver` 4.16 behind the sole,
  lint-enforced production import `verifier.formal`. Immutable ranked-row/bar/legend facts enter;
  structured method-aware results + bounded `(obligation, term_count, result_class)` traces leave;
  Z3 Context/AST/solver/model/text never cross the boundary. Three concrete quantifier-free
  negated obligations cover adjacent lexicographic canonical order (exact rationals + category
  ranks + direction/null policy), quantitative bar zero, and discrete legend set equality.
  One explicit Context belongs to each call; one solver per applicable obligation gets local
  timeout + `threads=1`, with no global parameters or SMT-LIB parser. Constructor-count upper
  bounds are summed before Context/AST creation; excess raises registered `resource.smt_terms`.
  UNSAT passes, SAT reports a model-derived uniquely lowest row/channel/category, and
  UNKNOWN/timeout/native exception returns registered `formal.solver_completed` failure without
  leaking native detail; trusted registry drift stays loud. Official-version, exact-boundary,
  empty/inapplicable, rational/null/direction, forced uncertainty/exception, solver-setting, and
  truly concurrent distinct-context tests pass. Disabling each obligation formula makes its
  focused counterexample regression fail; gate green at 1,237 tests/100% branch coverage.
- **M5.2c — independent SMT differential** (DONE): test-only `formal_oracle` consumes raw
  Decimal/text/null + mark/channel/domain cases and imports neither Z3 nor any production verifier
  module (AST-pinned); a separate adapter alone constructs formal facts, sharing no builder or
  obligation helper. Exhaustive agreement covers 3,364 table/sort cases (0..2 keys, 0..3 rows,
  null/0/1 domain), all 32 bar/channel flag combinations, and 91 duplicate/null legend sequences.
  Deterministic Hypothesis sampled 250 larger cross-product cases through 4 mixed-kind/direction
  keys, 7 rows, and larger legend domains with identical outcomes + stable lowest witnesses.
  Persisted anchors cover beyond-f64 exact Decimals, temporal/string ranks, mixed null directions,
  x-before-y, duplicate/empty/all-null color, and numeric ordinal categories. Removing each
  obligation's constraint producer is detected by a focused non-vacuity mutation; property run
  found no counterexample; gate green at 1,247 tests/100% branch coverage.
- **M5.2d — pre-render formal gate** (DONE): builder emits an explicit deterministic scale domain
  for nominal/ordinal color from recomputed non-null values; build typed formal facts from the
  exact dict handed to `_dumps`. Split preparation from native rendering at the orchestration seam:
  every public verify path (including `/verify-only`) prepares once, runs SMT, merges its results,
  and carries an internal formal-passed build with authoritative Vega bytes to `render_outcome`.
  Thus public `verified=true` always includes SMT; render paths never rebuild or re-solve, and a
  formal failure returns the ordinary 200 Verdict, never `None`->500. Passing formal IDs enter the
  current VCert's name-only list while carrying `z3_smt` in the report; replace the old
  construction-only bar/legend claims everywhere. Planning probe already compile-confirmed
  empty/all-null nominal domain `[]` and numeric ordinal domain under pinned Vega-Lite.
  `/verify-only`, direct render, and proposer mutation seams block domain/row/zero corruption;
  spies pin one build + one solver pass and zero native rendering for verify-only/failure. Empty,
  all-null, and numeric-ordinal explicit domains compile; certificate names equal the final passing
  report; every old construction-only bar/legend claim was replaced. All good corpus renders, all
  bad corpus blocks; gate green at 1,258 tests/100% branch coverage.
- **M5.2e — VCert v0.2 method provenance** (DONE): replace `checks_passed` with
  `checks: tuple[CertifiedCheck(id, method, status="pass")]`; stamp verifier package + Z3 versions
  in TCB and add `vega_lite_hash` over the exact serialized builder output. Update certificate
  canonical bytes, plot IDs, badge, service models, hand OpenAPI, goldens, and claim docs.
  VCert's version is a closed v0.2 wire literal; construction consumes one immutable formal-passed
  artifact and records each passing result's exact ID/method/status in report order. The fifth raw
  SHA-256 binds authoritative Vega bytes; TCB stamps package + native Z3 versions; service verdict,
  badge, generated OpenAPI, golden, scope/semantics/examples, and memory all expose the new contract.
  Acceptance: core + HTTP checks equal their passing final reports; one-byte Vega and verifier-version
  mutations change canonical payload + plot identity and remain visible; name-only wire field absent;
  gate green at 1,262 tests/100% branch coverage.

- **M5.3a — DSSE + Ed25519 primitives** (DONE): add current `cryptography>=49,<50` + lock; implement
  the tiny DSSE v1.0.2 PAE/envelope surface in `verifier.attestation` around exact VCert bytes with
  payload type `application/vnd.figure-verification.vcert.v0.2+json`. The application profile requires
  exactly one Ed25519 signature. Strict duplicate-key/base64/shape decoding; reject
  payload over the configured attestation limit and envelope over its derived base64 ceiling
  before JSON/application parse; accept standard + URL-safe base64 as required. The producer emits
  `keyid`; the verifier treats absent/empty identically and only as a bounded candidate-key hint.
  The producer uses one canonical JSON envelope encoding. Verify signature/type before parsing, and
  parse/return the SAME verified payload byte buffer (no envelope reparse). Ed25519 only; no
  home-grown crypto. Acceptance:
  official PAE/envelope serialization vector, generated-key sign/verify, type/payload/signature
  tamper rejection, wrong-key rejection, keyid-tamper/missing equivalence as unauthenticated hints,
  and unknown envelope fields tolerated per DSSE. Landed as an algorithm-closed PyCA Ed25519
  profile: canonical one-signature producer; strict padded standard/URL-safe base64 + duplicate-key
  and known-shape decode; 128-byte unauthenticated keyid hint with complete trusted-key fallback;
  derived pre-JSON envelope cap + pre-application payload cap; signature/type gates before strict
  VCert parsing, whose parser consumes and returns the identical verified byte object. VCert's
  nested wire structs now reject unknown application fields and OpenAPI advertises that constraint,
  while DSSE envelope extensions remain tolerated within the resource cap. Official v1.0.2 vector,
  canonical/deterministic round-trip, tamper/wrong-key/hint/base64/shape/resource-order/same-object
  tests pass; locked gate green at 1,306 tests/100% branch coverage.
- **M5.3b — persistent signing identity** (DONE): add a state-dir + key-file setting, eagerly
  absolutized without following the final component (default launch-root `.verifier-state`).
  Create the directory mode 0700 and one raw Ed25519 private key atomically/no-follow with mode
  0600 + file/directory fsync when absent; reject final-component symlink/non-directory,
  wrong-size, wrong-owner, or group/world-accessible state/key paths. Expose a typed signer +
  `keyid=sha256(raw public key)`. Preserve raw public keys by keyid for verification; keep state out
  of git. Trusted-key policy defaults to the current signer and accepts at most 32 deduplicated,
  shape-validated historical keyid pins from operator config; an archived/public endpoint key is
  NEVER trusted merely because it is present. Acceptance: create/reopen/concurrent-first-start,
  permissions, symlink/truncation, explicit rotation, and unpinned-historical-key tests; restart
  returns the same signer/keyid; gate green. Landed as `service.identity`: launch-root-relative
  paths retain their final component for descriptor-relative `O_NOFOLLOW`; owned owner-private
  directories/files are mandatory (including an external key parent). Missing state/public-key
  directories are 0700. A missing raw 32-byte private key is written + file-fsynced under a random
  0600 name, hard-linked into place without replacement, then directory-fsynced before + after
  temporary cleanup, so concurrent starters observe one complete winner. Current raw public keys
  persist under their SHA-256 keyid; an immutable verification map includes only the current key +
  at most 32 canonical, order-deduplicated historical pins from operator settings. Rotating via an
  explicit new key file preserves but does not auto-trust the old key. Creation/reopen/concurrency,
  file+directory fsync, external path, state/key/public symlink/type/owner/mode/size, tamper,
  rotation/pin/missing/hash mismatch, bounded settings, partial-write/temp-collision/cleanup, and
  immutable-policy tests pass; `.verifier-state/` is ignored; gate green at 1,339 tests/100% branch
  coverage.
- **M5.3c — signed service certificate + plot IDs** (DONE): after core render, the service signs
  exact VCert payload bytes into deterministic DSSE; `plot_id=sha256(envelope bytes)`; certificate
  GET serves the envelope. Rebuild the off-chain chart page from the returned authoritative Vega
  with the static VCert badge + signer keyid + plot_id/certificate link (today `render_html` omits
  `badge_html`, so this closes a real human-facing provenance gap). Thread signer through
  app/pipeline without global mutable state and reapply the final HTML byte ceiling after badge.
  Acceptance: served/returned HTML visibly carries
  all five artifact hashes, check methods, verifier version, keyid, and exact certificate link;
  restart keeps byte-identical envelope/id; key rotation changes id explicitly; external wrong
  key rejects;
  direct/propose paths share one signing seam; headless Chromium sees the badge/link + chart;
  docs state the out-of-band pin/identity limit; gate green. Landed as the single
  `pipeline.render_outcome` signing boundary: `create_app` eagerly loads one persistent identity
  and passes only its signer into both direct/proposer worker paths; canonical DSSE envelope bytes
  replace the unsigned payload as the stored certificate and `plot_id` preimage. The authenticated
  payload remains byte-identical to core VCert; repeat/restart output is byte-stable, explicit key
  rotation changes envelope/id, and an external wrong key rejects. The service rebuilds the
  off-chain page from the returned authoritative Vega + VCert after signing, displaying all five
  hashes, check methods, verifier version, signer hint, plot ID, and exact absolute certificate
  link; cautious copy requires independent pin verification rather than implying the hint is
  trust. Final signed HTML is UTF-8-admitted before either LRU mutation, and render-cache startup
  compatibility now budgets the derived DSSE-envelope ceiling rather than payload bytes alone.
  The OpenAPI response documents the one-signature DSSE profile; scope/semantics document
  identity/pin limits. Live restart kept the same ID; Chromium rendered the SVG + centered chart,
  badge, and exact link. Gate green at 1,345 tests/100% branch coverage.

- **M5.4a — transactional provenance archive** (DONE): add `service/archive.py`, stdlib SQLite
  STRICT schema (`meta`, immutable `blobs`, `keys`, `plots`, `attempts`, typed references), fresh
  connection per worker operation, parameterized SQL only. Force `journal_mode=DELETE`,
  `synchronous=FULL`, foreign keys, defensive mode, trusted-schema off, busy timeout and verify
  every security/durability readback; schema version mismatch fails startup. DB file mode=0600
  under the 0700 state dir. Blob metadata is role-bounded
  before allocation; reads stream through `sqlite3.Blob` while recomputing digest + kind/size. One
  `BEGIN IMMEDIATE` transaction publishes an entire bundle and checks its tracked
  logical-byte quota without a writer race. Default 1 GiB configurable logical quota: refuse
  before commit, no eviction; document that SQLite pages/rollback journal/filesystem overhead can
  exceed it. Acceptance:
  dedup/ref integrity, concurrent writers, rollback-on-injected-fault, corruption/wrong-kind,
  quota, unknown schema, and reopen tests; gate green. Landed as a startup-initialized append-only
  substrate with an exact-fingerprinted STRICT schema: `meta`, immutable typed blobs, keys, plots,
  attempts, and role-constrained plot/attempt references. Blob identity is `(sha256, kind)`, so
  same-role content deduplicates across bundles while byte-identical model-reply/raw-spec roles
  remain truthfully representable; existing bytes are streamed + byte-compared on dedup. Every
  operation owns a hardened fresh connection; startup rejects version/shape/accounting drift and
  unsafe state/DB objects before serving. `BEGIN IMMEDIATE` serializes the trigger-maintained
  logical quota check + whole batch; quota refuses without eviction, and admission stays O(bundle)
  while startup/operator stats reconcile the counter against all blob metadata. Reads bind role,
  kind, size, and caller ceiling before incremental BLOB allocation, then recompute SHA-256.
  `VERIFIER_MAX_ARCHIVE_BYTES` defaults to 1 GiB logical typed payload only - SQLite pages,
  row/index metadata, journals, and filesystem overhead remain explicitly outside the bound.
  Exact-bound/typed-dedup, 12-successful-writer + quota-race, FK/immutable/ref, injected rollback,
  native corruption/wrong-kind, connection-profile/fault, schema/version/reopen, and filesystem
  matrices pass; locked gate green at 1,377 tests/100% branch coverage.
- **M5.4b — content-addressed plot bundles** (DONE): add typed `PlotBundle` materialization from
  one `RecomputedEvidence` + formal-passed render artifact and a direct archive write/read API.
  Store raw CSV, raw manifest, canonical spec, canonical plotted-table bytes, full method-aware
  verdict, emitted Vega-Lite, SVG, VCert payload, DSSE envelope, verifier/runtime versions, and
  signing public key. Occurrence time/route stay out of this content-deduplicated plot. Acceptance:
  every certificate hash/address resolves to exact role-typed bytes; shared blobs deduplicate;
  round-trip/reopen is lossless; injected commit fault leaves zero partial rows/blobs; gate green.
  Landed as a pure materializer over one `PreparedArtifact` (which retains the exact
  `RecomputedEvidence`), its native `RenderResult`, canonical DSSE envelope, and signer. It derives
  the complete passing method-aware verdict rather than accepting a separately pairable copy;
  canonicalizes spec/table/verdict/TCB bytes; and rejects any signature, plot/key address,
  canonical-form, certificate hash, dataset binding, check-method, or tool-version disagreement.
  `Archive.publish_plot` maps the eleven exact typed payloads to one atomic low-level batch;
  `read_plot` admits their aggregate metadata size before any BLOB opens, streams + digests each,
  reconstructs the bundle, and revalidates the signed graph. Archived-key verification proves
  bundle self-consistency only - it grants no trust. Reopen is byte-lossless; a second signer
  shares all nine role blobs while adding only its key/envelope; an injected final-commit fault
  leaves zero rows/bytes. Locked gate green at 1,387 tests/100% branch coverage.
- **M5.4c — lossless model proposal trace** (DONE): model client returns a typed trace carrying
  exact serialized request/messages + bounded raw HTTP response body + extracted reply bytes when
  available, without changing the bytes sent over HTTP or downstream to spec decode. Pre-response
  exceptions carry the pre-call trace + bounded fault classification; policy-discarded oversized
  bodies carry classification only. No prompt/reply enters `str(exc)` or logs. Acceptance:
  request-body byte equality against the old client, fenced extracted reply + invalid-UTF-8/non-2xx
  raw-response traces, and a mutation test proving the decoder receives traced extracted bytes
  verbatim; gate green.
  Landed as repr-hidden `ProposalTrace` bytes + closed `ProposalFault` on a typed `ModelProposal`.
  The client calls HTTPX `build_request` once, retains `request.content`, and sends that same object;
  production constructs the result and trace from one extracted reply buffer, which the app hands
  directly to `decode_stage`. Fully admitted success/non-2xx/malformed bodies retain exact raw bytes;
  transport/interrupted-read/content-coding failures retain the request only, and the limit+1 path
  discards its prefix. Generic public errors/logs carry no prompt/reply or transport-cause text.
  Old-wire serialization, fenced content/object identity, invalid UTF-8, non-2xx, prompt-token,
  encoding, interrupted transport, exact-limit, log-redaction, and chunk-stop cases pass; locked
  gate green at 1,391 tests/100% branch coverage.
- **M5.4d — signed attempt bundles** (DONE): add canonical `AttemptManifest`/`AttemptBundle` types
  + direct archive API under payload type
  `application/vnd.figure-verification.attempt.v0.1+json`. A CSPRNG 128-bit nonce probabilistically
  distinguishes repeats; archive
  uniqueness + bounded collision retry prevents silent aliasing, then
  `attempt_id=sha256(signed attempt-envelope bytes)` addresses the occurrence. The DSSE payload
  binds UTC time, entry route, intended HTTP status/outcome kind, exact `plot_id` when present,
  typed role/digest of every available request/prompt/reply/verdict/trace/plot blob, and
  key/version identifiers. Closed roles + attestation cap bound construction; unavailable inputs
  remain absent, never invented. The canonical outcome snapshot excludes the derived attempt ID;
  that ID exists only after envelope signing, preventing a self-hash cycle. Publish attempt alone
  or successful plot + attempt in one transaction (a deduplicated plot adds only the attempt).
  Acceptance: direct success/failure
  bundles verify + round-trip; repeats differ; injected nonce collision retries then fails closed;
  tamper/wrong-role/partial-transaction matrices fail at the right layer; gate green.
  Landed as a distinct generic exact-payload DSSE profile plus canonical attempt payload. One
  `AttemptDraft` carries the occurrence facts and only bytes actually observed; its manifest binds
  those closed attempt roles and, on success, all eleven typed `PlotBundle` bytes in a separate
  namespace. The payload omits its own derived ID/envelope to avoid a self-hash cycle; a 128-bit
  CSPRNG nonce makes otherwise identical repeats distinct, while serialized archive-ID admission
  retries three collisions then refuses without aliasing. `publish_attempt` validates the complete
  signed attempt/plot graph and commits both in one transaction; an existing plot deduplicates so a
  repeat adds only its new payload/envelope. Complete reads metadata-admit unique aggregate bytes
  before any BLOB opens, authenticate the exact payload under the archived key as self-consistency
  only, reconstruct optional/plot bytes, and re-hold every role/digest/outcome/key/version edge.
  Direct verified/rejected bundles, all classified proposer faults, repeat/collision exhaustion,
  signature/role/byte/SQL corruption, quota/read bounds, and injected rollback matrices pass;
  locked gate green at 1,416 tests/100% branch coverage.
- **M5.4e — mandatory service attempt capture** (DONE): wire every classified outcome-bearing
  admitted `/propose-spec` and `/verify-and-render` occurrence through the bundle APIs, including model
  upstream, decode, verify, resource, and formal failures (nullable plot). Pre-admission
  body/rate/capacity refusal, client cancellation/disconnect before an outcome, process crash, and
  unclassified operator/implementation faults and archive failures stay explicitly outside the
  non-completeness claim. Commit is a precondition for returning an artifact-producing endpoint
  outcome and precedes LRU insertion; logical-quota
  refusal replaces the outcome with RFC-9457 507, other archive faults with generic 500.
  Successful/failing committed verdicts + problem extensions carry the non-secret attempt ID;
  storage-fault responses carry none. Keep `/verify-only` stateless. Acceptance: success + fenced
  decode + semantic/resource/formal fail + backend fault are diagnosable after restart; each stores
  only bytes actually observed; injected ledger failure replaces the original outcome without
  leaking it; no unauditable verified response/LRU entry; OpenAPI/consumers updated; gate green.
  Landed as an `AttemptWriter` + per-occurrence `RenderContext` spanning the exact route bytes,
  signer, limits, archive, and cache. Direct/proposer verified and rejected paths construct the
  canonical pre-address verdict, materialize the successful plot when present, atomically record
  the signed occurrence, then extend the public verdict with `attempt_id` and only afterward mutate
  either LRU. The proposer route catches every closed dataset/policy/model fault while its admission
  permit is live; the total `ProposalFault` mapping records only its lossless available trace, while
  dataset mismatch commits inside the pinned worker before its fixed Problem returns. Logical quota
  maps to fixed 507; every other archive/collision/integrity fault stays generic 500; neither carries
  an attempt ID, original outcome, or cache entry. `Verdict`/`Problem` expose optional committed
  addresses, `RenderVerdict` requires one, and `/verify-only` plus pre-admission 4xx/429 stay
  address-free. Restart tests authenticate direct/proposer success, decode/semantic/resource/formal
  rejection, mismatch, and backend-fault bundles; fault injection pins archive-before-cache and
  transactional refusal. Artifact-route tests use isolated state directories, never operator state.
  OpenAPI golden + loose bench consumer updated; locked gate green at 1,428 tests/100% branch
  coverage.
- **M5.4f — operator audit CLI** (DONE): add an operator-only command that resolves attempt ID,
  verifies its envelope/blobs, and defaults to hashes/metadata; require an explicit flag to reveal
  prompt/reply/raw-spec content as ASCII JSON-escaped UTF-8 or base64, never raw terminal
  control/bidi bytes.
  No raw-audit HTTP route. Acceptance: all success/failure shapes render stable redacted output;
  corruption/wrong key fails closed; terminal-escape/invalid-UTF-8 fixtures stay inert; sensitive
  bytes stay out of logs and default CLI; gate green.
  Landed as `python -m verifier.service audit ATTEMPT_ID [--reveal-sensitive]`. The command first
  performs the archive's aggregate-bounded complete occurrence read, which authenticates every
  address/typed blob/digest and optional plot graph, then independently requires the occurrence
  signer in the current-or-explicitly-pinned key policy and verifies the attempt + optional VCert
  envelopes under that exact key. Archive key presence alone never grants trust. Deterministic
  ASCII JSON defaults to signed metadata, byte counts, and digests; the explicit flag adds every
  available attempt observation as JSON-escaped UTF-8 or padded base64 while plot blobs remain
  metadata-only. Every closed outcome shape, restart/foreign-cwd dispatch, old-key pinning,
  corruption, ANSI/OSC/bidi controls, invalid UTF-8, redaction, and generic content-free failure
  diagnostics are pinned; no HTTP/OpenAPI surface changed. Locked gate green at 1,433 tests/100%
  branch coverage.
- **M5.4g — durable retrieval across restart** (DONE): certificate/spec GETs consult the archive
  as authority; expose the public signing key by exact keyid under a bounded non-secret endpoint;
  chart liveness remains independent/ephemeral until replay. Before serving, re-hold every address
  equation (`plot_id=envelope hash`, `spec_id=spec hash`, `keyid=public-key hash`) and check
  certificate signature/type against its digest-matching stored public key as internal consistency,
  without treating key presence as trust. Unknown/malformed IDs stay uniform 404 and DB corruption
  becomes logged generic 500, never a forged artifact. Update OpenAPI consumer/golden.
  Landed archive-authoritative `GET /certificate/{plot_id}`, `GET /spec/{spec_id}`, and bounded raw
  `GET /key/{keyid}`. Every request validates the exact versioned SQLite schema, admits relation/blob
  metadata before opening bytes, rechecks its content address/canonical form, and - for certificates
  - authenticates canonical DSSE + exact VCert type under the digest-matching archived key as
  self-consistency only. Schema v2 adds an immutable `spec_id -> canonical_spec` index with atomic,
  bounded v1 migration; render LRUs remain nonauthoritative write-side caches and `/chart` remains
  process-local. Restart, eviction, rotation-without-trust, migration, read-bound, schema drift, and
  relation/blob/hash/signature/type corruption matrices are pinned; OpenAPI golden + scope/docs are
  aligned. Locked gate green at 1,467 tests/100% branch coverage.
  Context: `main=52% 142K/272K`; `impl=46% 126K/272K`.

- **M5.5a — pure snapshot replay engine** (DONE): add `verifier.replay`, importing no service
  module. It accepts an explicit trusted-key set + typed snapshot bytes; verifies attempt ID/DSSE,
  exact `plot_id` binding, every blob digest/role, and VCert DSSE before decoding each payload once.
  Re-run manifest decode/eval/check/build/formal from archived CSV/manifest/spec bytes - never
  `data_dir`, model, or stored plotted values as computation inputs. Compare all five certified
  dataset/manifest/spec/table/Vega hashes + exact VCert payload bytes; report version/key drift
  field-by-field; native SVG comparison remains diagnostic (display TCB). Acceptance: in-memory
  same-version fixture replays exactly; wrong key/blob/role/version/recomputation mutation fails or
  reports drift at the right layer; replacing stored table/Vega cannot steer computation; gate green.
  Landed `verifier.replay.replay_snapshot(snapshot, trusted_keys, *, limits) -> ReplayVerdict`, a
  bounded typed verdict carrying five artifact-hash matches, payload/version match, field-by-field
  TCB drift, and a diagnostic-only SVG flag - never raw or rendered bytes. The module imports only
  core (`attestation`/`canon`/`checks`/`errors`/`render`/`schema`/`limits`) with its own strict
  attempt-manifest/verdict wire structs and role vocabulary; an AST test pins zero `verifier.service`
  import and a vocabulary test pins that role copy against the producer `BlobKind`/`PlotRole`. The
  caller's explicit `Mapping[keyid, Ed25519PublicKey]` is the sole trust anchor: embedded key
  bytes/keyids only prove self-address consistency, and `verify_dsse`/`verify_vcert` run under the
  caller-pinned key, so an unpinned keyid returns `untrusted_key` while a pinned-but-bad signature
  returns `integrity_failed`. Authentication binds attempt/plot ID addresses, every artifact/plot
  digest+role, attempt-plot signer equality, route/outcome, all five certified hashes against
  archived bytes, VCert checks/TCB, and canonical round-trips before any recomputation. Recomputation
  feeds only archived canonical-spec/raw-CSV/raw-manifest through the new filesystem-free
  `checks.verify_snapshot` seam (`verify_run` behavior byte-preserved), re-runs formal + render, and
  compares the fresh certificate: `exact` requires all five artifact hashes + no TCB drift + exact
  VCert payload bytes, version drift alone is `drift`, and native SVG equality is reported but never
  gates `exact`. Exact/wrong-key/mutated-blob/role-swap/version-drift/recomputation-mutation and
  stored-table/Vega/verdict/SVG steering-resistance are pinned. Locked gate green at 1,508 tests/100%
  branch coverage.
  Context: `main=24% 65K/272K`; `impl=80% 218K/272K`.
- **M5.5b — archive replay adapter** (DONE): add thin `service.replay` loading bounded role-typed
  blobs from the archive. For a plot, select via indexed `LIMIT 1` the lexicographically lowest
  committed signed successful attempt associated with it, then require the pure engine to verify
  that signed association. Resolve trust only from current signer + explicit historical keyid pins,
  never archive key presence. Acceptance: exact replay survives live CSV/manifest mutation,
  deletion, LRU eviction, process restart, and foreign cwd; unpinned historical key, missing blob,
  corrupt association, and archive read cap fail closed; no model/data-dir access; gate green.
  Landed `verifier.service.replay.replay_plot(archive, trusted_keys, plot_id, *, max_bytes, limits)
  -> ReplayVerdict` plus a `replay_plot_from_settings` convenience: it resolves the lexicographically
  lowest signed verified attempt via a new schema-v3 partial covering index `attempts_by_plot ON
  attempts(plot_id, attempt_id) WHERE plot_id IS NOT NULL` and SQL-owned
  `Archive.lowest_verified_attempt_id` (indexed `LIMIT 1`), reads that bundle under the aggregate
  byte cap, materializes a pure `ReplaySnapshot` by a 1:1 field copy of the archive
  `AttemptBundle`/`PlotBundle`, and passes `identity.trusted_keys` unchanged to `replay_snapshot`.
  The archived key proves storage self-consistency only; trust stays current signer + explicit
  historical pins. The schema bump chains v1->v2->v3 / v2->v3 (the index is derived, no blob reads);
  `_migrate_v1_to_v2` now advances only to the intermediate `_SCHEMA_VERSION_V2` so the chained path
  stays consistent. Pinned: exact replay survives CSV/manifest mutation+deletion, cache-cold state,
  process restart, and foreign cwd; multi-attempt lowest-selection + unchanged trust-mapping are
  observed through a `replay_snapshot` spy; an unpinned signer returns `untrusted_key`; missing blob,
  corrupt plot association, zero read cap, and unknown plot fail closed; an AST test pins no
  model-client import and no `data_dir` argument. Locked gate green at 1,519 tests/100% branch
  coverage.
  Context: `main=61% 165K/272K`; `impl=68% 185K/272K`.
- **M5.5c — replay HTTP surface + audit docs** (DONE): add `GET /replay/{plot_id}` returning a
  typed ReplayVerdict (integrity, trusted keyid, version match, per-artifact comparisons, no raw
  snapshots/prompt); an exact replay includes regenerated SVG + repopulates the ephemeral chart
  LRU. Unknown plot stays 404 and SQLite/schema/implementation faults stay generic 500; signed
  attestation/blob/key/version/recomputation mismatches return a bounded 200 diagnostic with no
  chart. Keep `GET /certificate/{plot_id}` as durable DSSE bytes, and hand-author OpenAPI
  paths/schemas/media types. Document state/key backup, quota failure, key pinning, replay semantics,
  and operator CLI. Acceptance: render -> restart -> replay -> chart GET works from archived inputs;
  real TCP; OpenAPI golden + jsonschema/consumer tests; replay uses the same rate + active-job
  admission; old Open WebUI `proposeSpec` tool surface unchanged; gate green.
  Landed admitted async `GET /replay/{plot_id}` -> `Response[bytes]` serializing the pure
  `verifier.replay.ReplayVerdict` (no raw/prompt/rendered bytes); a synchronous admitted worker runs
  `service.replay.replay_plot_chart` and, only when `verdict.exact`, rebuilds the signed chart from
  the archived hash-bound Vega + caller-trusted DSSE-authenticated VCert payload (archived
  `snapshot.plot.keyid`, `settings.public_base_url`) and repopulates the ephemeral chart LRU.
  `replay_plot_chart`/`PlotReplay` factor a shared `_replay_lowest`; the M5.5b `replay_plot`
  contract + AST purity hold (adds only `render`/`VCert`/`msgspec`). Malformed id -> 404 before
  admission; `ArchiveNotFoundError` -> 404; other archive/SQLite/schema faults -> logged generic
  500; untrusted/integrity/drift/recomputation mismatches -> bounded 200 diagnostic, no chart.
  OpenAPI adds `replayPlot` + the msgspec-introspected `ReplayVerdict`/`ArtifactHashMatches`/
  `VersionDrift` components (golden strictly additive; `proposeSpec` byte-identical, verified by
  sorted-key hash). POC_SCOPE documents replay semantics/error split, `VERIFIER_STATE_DIR` one-unit
  backup, `VERIFIER_MAX_ARCHIVE_BYTES` 507, `VERIFIER_TRUSTED_KEYIDS` pinning, and the `audit` CLI.
  Tests pin render->restart->replay->chart repopulation, bounded body/no-raw-bytes, malformed-vs-
  unknown 404-before-admission ordering, rotated-signer 200 diagnostic w/o chart, schema-drop logged
  500, shared-admission 429, a real-TCP replay leg, and jsonschema consumer validation. Locked gate
  green at 1,530 tests/100% branch coverage.
  Context: `main=72% 197K/272K`; `impl=65% 176K/272K`.
- **M5.5d — end-to-end hardening capstone (pytest)** (DONE): fixed the invalid-UTF-8 decode-500
  defect + authored `tests/test_e2e_hardening.py`. DEFECT (MAIN-reproduced): invalid-UTF-8 bytes
  inside a JSON string made `schema._DECODER.decode` raise builtin `UnicodeDecodeError` (finding 9),
  escaping `pipeline.decode_stage`'s `except (ValidationError, DecodeError)` -> generic 500 on BOTH
  `/verify-only` + `/verify-and-render`, violating the decode->200-verdict contract. FIX centralized
  in `schema.decode_spec` bytes-path (map `UnicodeDecodeError`->`msgspec.DecodeError`, mirror the
  str-path; docstring corrected; regression in `test_schema.py` covers the new branch); both
  endpoints now return the 200 decode verdict (same arm as malformed JSON). No dead branch:
  `archive`/`replay` `decode_spec` callers use `except (ValueError, RecursionError)` (DecodeError +
  UnicodeDecodeError both subclass ValueError, already caught); `_PROPOSE_DECODER` is a separate
  already-catching decoder; `decode_stage` untouched. Capstone = 14 from-empty-state tests covering
  all 13 hardening scenarios (+ a distinct-datasets companion), each assertion annotated to its
  seed-13/14 exit criterion: 13(a) >=3 z3 obligations in a verified VCert; 13(b) HTTP EXACT
  forced-unknown message (three `formal.solver_completed`/`z3_smt`/`fail` obligations) via the
  `_check_solver` seam; 13(c) fetched-VCert `{id,method,status}` shows `z3_smt` vs
  `deterministic_recompute`; 14(a) replay reproduces from archived bytes across restart + LRU
  eviction + live-CSV mutation/deletion, plus one restart->independently-verify-certificate->replay->
  chart flow; 14(b) two DISTINCT datasets (sales+weather) -> distinct fetched-certificate
  `dataset_hash`; 14(c) verifier-version drift visible in replay `version_match`/`drift` + VCert TCB;
  14(d) real endpoint pass+fail -> restart -> actual audit CLI asserting the human-readable reason;
  `/replay/{id}` + `/certificate/{id}` both exercised. Fail-closed guards: rotated-unpinned signer ->
  `untrusted_key` no chart; DROP-INDEX schema damage -> logged generic 500 no leak; blob-content +
  attempt-signature corruption -> detected before use/mutation; capacity 429 (held permit), quota
  507, injected pre-COMMIT rollback -> `ArchiveStats(0,0,0,0,0)` (zero reachable rows and logical
  payload bytes; not COMMIT-failure, hot-journal, or power-loss coverage).
  All trust/availability claims at
  current strength (archived-key verification = self-consistency only; replay/audit fail-closed; no
  crypto/formal overclaim). MAIN independently reproduced the defect, re-derived the exact fix facts
  + solver message, inspected both diffs, and reran all four gate legs. Locked gate green at 1,545
  tests/100% branch coverage; golden `test_examples` green.
  Context: `main=87% 235K/272K`; `impl=61% 166K/272K` (capstone author; +26% 70K/272K fix batch).
  Post-close hardening (adversarial review): `test_05` now 200-guards every compared cert/spec fetch +
  DSSE-decodes the initial VCert; `test_08` pins `spec.decode`/`schema_validation`/`blocking` on both the
  endpoint + audited verdict — two vacuous-capable seed-14 regression guards (uniform-404 archival
  regression; self-referential audit reason) hardened. Peer reports #1-3 + capstone-map's four = stale
  pre-fix reads already addressed by the fix batch. Gate re-green 1,545/100%; `guard-fix=42% 114K/272K`.
- **M5.5e — demo walkthrough + doc-drift sweep + M5 close** (DONE): (a) runnable
  hardware-free `demo/` walkthrough — spin the service on a tmp `state_dir` from empty and walk the
  M5.5d scenarios, printing PASS/FAIL + a gitignored JSON report, with a short `demo/README.md` run
  recipe; mirror the capstone scenario drivers (may import light helpers from `test_e2e_hardening`
  or duplicate — user accepted minor duplication); clean the stale `demo/__pycache__`. (b) doc-drift
  sweep of POC_SCOPE.md / VPlot_SEMANTICS.md / bench+webui+examples READMEs / `.agent/memory.md` to
  current M5 truth — docs already largely current (VCert v0.2, 5-method vocabulary schema_validation/
  resource_policy/deterministic_recompute/construction/z3_smt, DSSE/keyid trust language, replay+
  audit routes, 429/507/500 all present). Known drift candidate: **POC_SCOPE.md:24 "these four
  artifacts"** vs the FIVE bound hashes (dataset/manifest/spec/plotted_table/vega_lite in replay
  `artifact_matches` + VCert v0.2) — verify against the VCert struct and correct if stale; rescan the
  same token families at anchors examples/README.md:28, VPlot_SEMANTICS.md:37/152/172/188/219-222,
  POC_SCOPE.md:24/31/33/119-175, bench/README.md:33-34. WORKLIST (parallel docs-audit; MAIN
  validates each before editing — docs-audit rated POC five-hashes + method vocabulary + DSSE/keyid
  + quota/replay-error split as CONSISTENT, do not touch): DEFINITE doc fixes — VPlot_SEMANTICS.md:
  31-34 "discloses every applied filter + sort" -> only the ACTIVE sort (`render._build_certificate`
  keeps `active_sort`; POC_SCOPE.md:65 already right); VPlot_SEMANTICS.md:217-225 classifies
  `scale.bar_zero` as M1 SEMANTIC -> it is M5.2 `z3_smt` (same doc correct at 187-189);
  webui/README.md:134 "all 8 checks passed" -> g01 now yields 10 final results;
  examples/README.md:19-22 construction inventory omits `security.no_arbitrary_code` +
  `transform.ops_allowed`; `.agent/memory.md:21` "SVG/pixels unhashed" -> pixels unhashed/display-TCB
  but SVG IS digest-bound in signed attempt provenance (`archive._PLOT_BINDING_FIELDS`), only absent
  from VCert + diagnostic-only for exact replay. REVIEW-ONLY wording: POC_SCOPE.md:31-33/47-49,
  VPlot_SEMANTICS.md:29-30/209-216, examples/README.md:24-28, bench/README.md:87-93 (cumulative
  repeat-run archive reuse), `.agent/memory.md:75` (archive schema is now v3 via `_migrate_v2_to_v3`,
  not v2). Reconcile my earlier POC_SCOPE.md:24 "four artifacts" flag (docs-audit rated POC
  five-hashes consistent — confirm whether :24 is a distinct enumeration or a genuine miss). The
  invalid-UTF-8 decode items (POC_SCOPE.md:102-105, VPlot_SEMANTICS.md:204-208) are NOT doc drift —
  they state the correct contract; the CODE bug is fixed in M5.5d, so leave those docs as-is.
  (c) MAIN closes M5: set M5.5d+M5.5e DONE and
  M5 IMPLEMENTED, record main=/impl=, commit. Scaffold identical to M5.5d. Gate green (`demo/`
  outside `verifier` coverage source, like `bench/`). Acceptance: `demo` runs clean from empty state
  and reports every scenario; no stale claim-method/storage statement and no overclaim survives; gate
  green; M5 IMPLEMENTED.
  Done (MAIN-verified): `demo/` package — `python -m demo` runs a self-contained hardware-free
  `walkthrough.py` (in-process `TestClient` with `unittest.mock`/`httpx.MockTransport` model seams,
  no live service or network) that spins the verifier from an empty tmp `state_dir` through all 13
  M5.5d hardening scenarios, prints per-scenario PASS/FAIL, and writes a gitignored
  `demo/reports/report.json`; short `demo/README.md` recipe; mirrors the capstone drivers; transient
  `demo/__pycache__` gitignored. `pyproject.toml` drops `demo` from the coverage source + adds it to
  ruff `known-first-party`; `.gitignore` ignores `demo/reports/`. Doc-drift sweep — 5 DEFINITE fixes:
  VPlot_SEMANTICS.md "every applied filter + sort" -> active sort only, and `scale.bar_zero`
  reclassified M1-SEMANTIC -> M5.2 `z3_smt`; webui/README.md 8 -> 10 checks; examples/README.md
  construction inventory adds `security.no_arbitrary_code` + `transform.ops_allowed`; `.agent/memory.md`
  SVG "unhashed" -> digest-bound in the signed archive (`_PLOT_BINDING_FIELDS`) but outside VCert.
  POC_SCOPE.md:24 "four artifacts" CONFIRMED accurate (distinct top-level enumeration; VCert artifact
  #4 itemizes its 5 bound hashes) — no edit; REVIEW-ONLY anchors reconciled no-edit. Gates re-green
  independently: ruff format/check 0 (90 files), mypy 0 (90 files incl. `demo`), `python -m demo`
  13/13 PASS, pytest 1,545 passed / 100.00% coverage (1,044 branches, 0 missing). M5 IMPLEMENTED
  (M5.1a-M5.5e all DONE).
  Context: `main=62% 168K/272K` (coordination peak before close-compaction; close tail 20% 55K/272K);
  `impl=45% 122K/272K` (demo author; peak 137K/50%, compaction-free).

---

## M4 — Open WebUI integration   (REVIEWED — closed)

Delivered the Open WebUI 0.10.2 integration without moving the verifier claim boundary: Open
WebUI, its function runner, iframe/browser, Vega runtime, and pixels are trusted display /
orchestration; only the verifier's validated spec, recomputed table, emitted Vega-Lite, and
certificate are mutually checked. Pieces:

- verifier chart surface: every verified render builds an offline page with the Open WebUI
  `iframe:height` reporter; an independent `html_cap` LRU serves it at
  `GET /chart/{plot_id}` under `Content-Security-Policy: sandbox allow-scripts`; a clean
  `public_base_url` drives the absolute chart Location;
- `POST /propose-spec` verified success = Open WebUI's Location-variant
  `[ProposeResult, summary]` JSON body under `Content-Disposition: inline`; failures remain
  bare structured results with no embed; the hand-authored OpenAPI description + response union
  are golden- and consumer-validated;
- repo-root `webui/` harness: separate Python-3.12 Open WebUI executable, hermetic canonical
  child env, global backend-called OpenAPI server exposing only `proposeSpec`, legacy headless
  function calling, signup-or-signin provisioning, exact-source active/global filter convergence,
  deterministic hardware-free model stub, CLI, and operator recipe;
- `Verified Plot Guard`: a stdlib-only heuristic outlet classifier for common direct-chart forms.
  It is explicitly bypassable and false-positive-prone - a usability guardrail, never authority or
  evidence of verification.

Live evidence (durable observations, not reliability bounds): clean provisioning + idempotent
rerun found the model and `server:verifier`; the NPU model selected `proposeSpec` on 5/10 fixed
prompts and verified 0/10 (four fenced undecodable specs, one missing argument). The scripted
non-model fixture then proved the successful selector → tool → verifier → lean-context chain,
persisted chart Location, CSP + height reporter, and Chromium-rendered sandboxed chart (no
`allow-same-origin`). The real NPU reply also proved the filter-on blocked / filter-off
byte-preserved differential. Exact standup = `webui/README.md`; external-contract facts =
memory M4.

Milestone review read all 39 trace-keyed M4 commits + final state and accepted four hardening
findings: canonical URL/host validation now rejects ambiguous/misjoined endpoints; the load-bearing
`ENABLE_API_OUTLET_FILTERS=true` setting is explicit; auth/readback/function transport + malformed
UTF-8 responses stay inside `WebUIProvisionError`; POC_SCOPE now states the independent
certificate/spec and chart LRUs. Post-fix live rerun against installed 0.10.2: clean bootstrap
twice, exact outlet env observed in the child, block/pass differential, successful legacy-FC
tool/verifier chain; services/state cleaned, ports free. Full locked gate: 858 tests, 100% verifier
branch coverage. Unit/planning/review-follow-up trail: `git log --grep "(M4[. ]"`.

---

## M3 — Local model proposer + failure eval   (REVIEWED — closed)

Delivered the UNTRUSTED weak proposer in front of the M1/M2 verifier — claim boundary UNCHANGED
(the model supplies NO data values; verify recomputes the whole plotted table + rebinds the CSV
by hash; POC_SCOPE "## Model proposer" holds the contract). Pieces: `model_backend/` (repo-root
Litestar+uvicorn OpenAI-`/v1` wrapper over the installed `openvino_genai.LLMPipeline`, NPU-served
local INT4_SYM Qwen2-0.5B re-export — the NPU switch landed mid-milestone as a direct task;
hardware-gated, coverage-excluded, unshipped) → `service/model_client.py` (async `propose_spec` →
typed proposal with raw reply bytes, never VPlot-decoded client-side) → `POST /propose-spec`
(typed body → reply → `decode_stage` → dataset-name PIN at decode time → `verify_decoded` → `render_outcome`; the
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
is untouched by a fully-failing proposer. **(M8.3 supersession note):** this raw `0/100` is the
honest UNCONSTRAINED baseline; M8 ships schema-guided decoding as the DEFAULT and re-measured
`verified_render=26/100` on the same live NPU (fence failures `97→0`), with the guarantee unchanged
(18/18 blocked, 10/10 accepted) — see the M8 section for the full raw-vs-constrained record.

---

## M2 — Verifier API service   (REVIEWED — closed)

Delivered `verifier.service` — the M1 library wrapped in a local Litestar + uvicorn HTTP
transport (one worker, 127.0.0.1 by default), adding no verification trust of its own (one-way dep:
the core never imports the service). Pieces: `settings.py` (frozen operator config from
`VERIFIER_*` env, fail-closed bound guards) → `app.py` (factory + 6 routes, raw-body-first
POSTs so `decode_spec` stays authoritative, nosniff app default, two problem+json exception
handlers) → `pipeline.py` (decode → resolve manifest → load → `checks.verify`, reused by
render) → `models.py` (Verdict / RenderVerdict with `verified: Literal[True]` / RFC-9457 Problem)
→ `store.py` (bounded LRU over chart renders) → `openapi.py`
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
