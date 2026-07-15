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
| M5 | Formal + provenance hardening | 13,14 | none — toolchain probe confirmed | IN-PROGRESS |
| M6 | End-to-end demo | 15 | full stack (M3+M4) | UNPLANNED |

Seed step 1 ("create the local stack") is split by gate: scaffold+data → M1, API → M2, model backend → M3, Open WebUI → M4. Plan each milestone only when it becomes active (prior one REVIEWED); M3/M4/M6 are gated — confirm preconditions functionally at their planning turn; bring generated/heavy inputs into scope only when the gate needs them.

---

## M5 — Formal + provenance hardening   (IN-PROGRESS)

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
  "holder of this independently pinned public key signed these bytes" - no operator identity, PKI,
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
  an oversized success/error envelope is a typed 502 and never enters trace/archive. Preserve raw
  model failure metering below the bound. Acceptance: spy backend sees zero calls on every prompt
  policy breach; exact-limit request still takes the old path; chunked oversized response proves
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
- **M5.2d — pre-render formal gate** (OPEN): builder emits an explicit deterministic scale domain
  for nominal/ordinal color from recomputed non-null values; build typed formal facts from the
  exact dict handed to `_dumps`. Split preparation from native rendering at the orchestration seam:
  every public verify path (including `/verify-only`) prepares once, runs SMT, merges its results,
  and carries an internal formal-passed build with authoritative Vega bytes to `render_outcome`.
  Thus public `verified=true` always includes SMT; render paths never rebuild or re-solve, and a
  formal failure returns the ordinary 200 Verdict, never `None`->500. Passing formal IDs enter the
  current VCert's name-only list while carrying `z3_smt` in the report; replace the old
  construction-only bar/legend claims everywhere. Planning probe already compile-confirmed
  empty/all-null nominal domain `[]` and numeric ordinal domain under pinned Vega-Lite.
  Acceptance: `/verify-only`, direct render, and
  proposer mutation seams block row/domain/zero corruption; spies prove one build + solver pass and
  zero native render for verify-only/failure; all good corpus renders, all bad corpus blocks,
  emitted Vega compiles; gate green.
- **M5.2e — VCert v0.2 method provenance** (OPEN): replace `checks_passed` with
  `checks: tuple[CertifiedCheck(id, method, status="pass")]`; stamp verifier package + Z3 versions
  in TCB and add `vega_lite_hash` over the exact serialized builder output. Update certificate
  canonical bytes, plot IDs, badge, service models, hand OpenAPI, goldens, and claim docs.
  Acceptance: certificate checks exactly equal the passing final report's IDs/methods; changing one
  Vega byte or verifier version changes payload/plot identity and is visible; no check-name-only
  compatibility shim; gate green.

- **M5.3a — DSSE + Ed25519 primitives** (OPEN): add current `cryptography>=49,<50` + lock; implement
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
  and unknown envelope fields tolerated per DSSE; gate green.
- **M5.3b — persistent signing identity** (OPEN): add a state-dir + key-file setting, eagerly
  absolutized without following the final component (default launch-root `.verifier-state`).
  Create the directory mode 0700 and one raw Ed25519 private key atomically/no-follow with mode
  0600 + file/directory fsync when absent; reject final-component symlink/non-directory,
  wrong-size, wrong-owner, or group/world-accessible state/key paths. Expose a typed signer +
  `keyid=sha256(raw public key)`. Preserve raw public keys by keyid for verification; keep state out
  of git. Trusted-key policy defaults to the current signer and accepts at most 32 deduplicated,
  shape-validated historical keyid pins from operator config; an archived/public endpoint key is
  NEVER trusted merely because it is present. Acceptance: create/reopen/concurrent-first-start,
  permissions, symlink/truncation, explicit rotation, and unpinned-historical-key tests; restart
  returns the same signer/keyid; gate green.
- **M5.3c — signed service certificate + plot IDs** (OPEN): after core render, the service signs
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
  docs state the out-of-band pin/identity limit; gate green.

- **M5.4a — transactional provenance archive** (OPEN): add `service/archive.py`, stdlib SQLite
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
  quota, unknown schema, and reopen tests; gate green.
- **M5.4b — content-addressed plot bundles** (OPEN): add typed `PlotBundle` materialization from
  one `RecomputedEvidence` + formal-passed render artifact and a direct archive write/read API.
  Store raw CSV, raw manifest, canonical spec, canonical plotted-table bytes, full method-aware
  verdict, emitted Vega-Lite, SVG, VCert payload, DSSE envelope, verifier/runtime versions, and
  signing public key. Occurrence time/route stay out of this content-deduplicated plot. Acceptance:
  every certificate hash/address resolves to exact role-typed bytes; shared blobs deduplicate;
  round-trip/reopen is lossless; injected commit fault leaves zero partial rows/blobs; gate green.
- **M5.4c — lossless model proposal trace** (OPEN): model client returns a typed trace carrying
  exact serialized request/messages + bounded raw HTTP response body + extracted reply bytes when
  available, without changing the bytes sent over HTTP or downstream to spec decode. Pre-response
  exceptions carry the pre-call trace + bounded fault classification; policy-discarded oversized
  bodies carry classification only. No prompt/reply enters `str(exc)` or logs. Acceptance:
  request-body byte equality against the old client, fenced extracted reply + invalid-UTF-8/non-2xx
  raw-response traces, and a mutation test proving the decoder receives traced extracted bytes
  verbatim; gate green.
- **M5.4d — signed attempt bundles** (OPEN): add canonical `AttemptManifest`/`AttemptBundle` types
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
- **M5.4e — mandatory service attempt capture** (OPEN): wire every classified outcome-bearing
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
- **M5.4f — operator audit CLI** (OPEN): add an operator-only command that resolves attempt ID,
  verifies its envelope/blobs, and defaults to hashes/metadata; require an explicit flag to reveal
  prompt/reply/raw-spec content as ASCII JSON-escaped UTF-8 or base64, never raw terminal
  control/bidi bytes.
  No raw-audit HTTP route. Acceptance: all success/failure shapes render stable redacted output;
  corruption/wrong key fails closed; terminal-escape/invalid-UTF-8 fixtures stay inert; sensitive
  bytes stay out of logs and default CLI; gate green.
- **M5.4g — durable retrieval across restart** (OPEN): certificate/spec GETs consult the archive
  as authority (LRUs may remain read-through caches); expose the public signing key by exact keyid
  under a bounded non-secret endpoint; chart liveness remains independent/ephemeral until replay.
  Before serving, re-hold every address equation (`plot_id=envelope hash`, `spec_id=spec hash`,
  `keyid=public-key hash`) and check certificate signature/type against its digest-matching stored
  public key as internal consistency, without treating key presence as trust. Unknown/malformed IDs
  stay uniform 404 and DB corruption becomes logged generic 500, never a forged artifact. Update
  OpenAPI consumer/golden. Acceptance: render -> new app process -> exact certificate/spec/key
  bytes; eviction/restart matrix pinned; gate green.

- **M5.5a — pure snapshot replay engine** (OPEN): add `verifier.replay`, importing no service
  module. It accepts an explicit trusted-key set + typed snapshot bytes; verifies attempt ID/DSSE,
  exact `plot_id` binding, every blob digest/role, and VCert DSSE before decoding each payload once.
  Re-run manifest decode/eval/check/build/formal from archived CSV/manifest/spec bytes - never
  `data_dir`, model, or stored plotted values as computation inputs. Compare all five certified
  dataset/manifest/spec/table/Vega hashes + exact VCert payload bytes; report version/key drift
  field-by-field; native SVG comparison remains diagnostic (display TCB). Acceptance: in-memory
  same-version fixture replays exactly; wrong key/blob/role/version/recomputation mutation fails or
  reports drift at the right layer; replacing stored table/Vega cannot steer computation; gate green.
- **M5.5b — archive replay adapter** (OPEN): add thin `service.replay` loading bounded role-typed
  blobs from the archive. For a plot, select via indexed `LIMIT 1` the lexicographically lowest
  committed signed successful attempt associated with it, then require the pure engine to verify
  that signed association. Resolve trust only from current signer + explicit historical keyid pins,
  never archive key presence. Acceptance: exact replay survives live CSV/manifest mutation,
  deletion, LRU eviction, process restart, and foreign cwd; unpinned historical key, missing blob,
  corrupt association, and archive read cap fail closed; no model/data-dir access; gate green.
- **M5.5c — replay HTTP surface + audit docs** (OPEN): add `GET /replay/{plot_id}` returning a
  typed ReplayVerdict (integrity, trusted keyid, version match, per-artifact comparisons, no raw
  snapshots/prompt); an exact replay includes regenerated SVG + repopulates the ephemeral chart
  LRU. Unknown plot stays 404 and SQLite/schema/implementation faults stay generic 500; signed
  attestation/blob/key/version/recomputation mismatches return a bounded 200 diagnostic with no
  chart. Keep `GET /certificate/{plot_id}` as durable DSSE bytes, and hand-author OpenAPI
  paths/schemas/media types. Document state/key backup, quota failure, key pinning, replay semantics,
  and operator CLI. Acceptance: render -> restart -> replay -> chart GET works from archived inputs;
  real TCP; OpenAPI golden + jsonschema/consumer tests; replay uses the same rate + active-job
  admission; old Open WebUI `proposeSpec` tool surface unchanged; gate green.
- **M5.5d — end-to-end hardening evidence** (OPEN): from empty state, exercise direct render +
  deterministic model-stub success/failure, restart, LRU eviction, live-data mutation, exact
  replay, failed-attempt audit, key mismatch, DB/blob/signature corruption, solver timeout,
  capacity 429, quota refusal, and crash-injected transaction rollback. Run golden corpus + full
  locked gate; sweep POC_SCOPE/VPlot semantics/README/memory for claim-method/storage drift; close
  M5 -> IMPLEMENTED. Acceptance: every seed-13/14 exit criterion demonstrated with retained test
  evidence, every trust/availability limit stated without stronger cryptographic/formal claim,
  and gate green.

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
