# figure-verification — roadmap

Local "verified-plot" PoC. A weak local LLM only PROPOSES a restricted JSON chart spec (VPlot); a separate trusted verifier deterministically recomputes the plotted data from the source CSV, runs structured checks, blocks charts whose spec, encoding, policy, or dataset binding fail those checks, and renders only verified charts with a provenance certificate (dataset hash, spec hash, plotted-table hash, passed checks).

- **Scope-seed**: 16 verbatim steps "Milestone 0..15" at `git show 9d09ecb:.agent/outline.md`, consumed by M1–M6 (step 1 split by gate: scaffold+data → M1, API → M2, model backend → M3, OWUI → M4). The Seed-steps column maps them; read one only when a later milestone reopens its ground.
- **Stack**: `.agent/memory.md` + `.agent/reference.md` — researched SOTA over the outline's human-popular defaults. Determinism/trust invariants → `VPlot_SEMANTICS.md` + `POC_SCOPE.md` + module docstrings, locked by the suites.
- **Data-flow (trust spine)**: the untrusted model proposes ONLY a VPlot spec (transforms + encoding + declared `dataset.hash`) — never plotted values. The verifier recomputes ALL plotted data; the renderer inlines only that. So lies needing model-supplied data (the seed's "plots a value ≠ recomputation") are impossible by construction, not checks; checks target spec/encoding/policy/dataset-binding consistency.
- **Modest claim** (hold the line): verified = {validated spec, the independently recomputed plotted table, the emitted Vega-Lite inlining only that table, the provenance badge} are mutually consistent and the checks passed. Trusted, NOT verified (TCB): `vl-convert`/Vega, SVG rasterization, browser, pixels — trusted to render verified data faithfully, not proven to.
- **Quality gate** (M1.1 wires it; every WORK-UNIT runs it — teammate worktrees concurrently off the shared venv, MAIN's rerun on the primary tree decides — all green, touched scripts exit clean): `ruff format --check .` · `ruff check .` · `mypy` · `pytest` — all via `uv run --locked` (the lockfile, not a newer floor-satisfying release, pins the gate).

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
| M9 | Verified formula-plot mode (headless) | — (user request) | none (headless verifier core) | REVIEWED — M9R1/M9R2/M9R3 open |
| M10 | Model-authored Python in the OWUI sandbox + calibrated demo | — (user request) | M12 + M13 DONE; browser-live OWUI `execute:python`; local proposer on the host of record | UNPLANNED |
| M11 | Derived/computed columns (dataset mode) | — (user request) | none (headless; reuses M9 expr engine) | UNPLANNED — DEPRIORITIZED behind M12/M13/M10 |
| M12 | dGPU proposer runtime port + model-authored-Python corpus | — (user request) | torch CUDA build reaches MX150 — MET at plan | IN-PROGRESS |
| M13 | Python-source verification mode (headless) | — (user request) | none (headless verifier core); consumes M12's captured corpus | UNPLANNED |

Plan each milestone only when it becomes active (prior one REVIEWED). M3/M4/M6/M7/M10 are gated — confirm preconditions functionally at the planning turn, and bring generated/heavy inputs into scope only when the gate needs them. A gate unmet there ⇒ set the milestone PARKED with its named precondition verbatim, clearing the marker only when a functional recheck meets it; M11 is ungated + sequence-adjustable, so M10's live-OWUI gate parks rather than stalls the roadmap.

**Host change — model tier only.** The proposer's live stack was built on the ORIGIN host (Intel NPU + OpenVINO); CURRENT has no NPU ⇒ `MODEL_BACKEND_DEVICE=NPU` cannot load and every REAL-MODEL arm of the M3/M4/M6/M7/M8 live-stack gates + M9.12's live formula smoke is UNMET here. Those REVIEWED verdicts STAND — their evidence was validly taken on ORIGIN. The trusted core is host-free (verifier + bench + tests + demo gate fully on CURRENT) ⇒ M9 is unaffected and stays active, while **M10 carries a SECOND precondition beyond browser-live OWUI: a working local proposer on the host of record**. **M10 precondition 1 = MET on CURRENT**: `webui/launch.sh --stub` stands all three services up and a verified chart renders inline in the browser; precondition 2 stays UNMET, so M10's live-proposer arms park while its sandbox-execution arms are probeable today. A runtime port is its own UNPLANNED milestone, never an M9 unit. Host inventory, the measured runtime verdict, the two byte-exact backend contracts any replacement engine must reproduce, the evidence a swap does and does not invalidate + the weak-proposer calibration constraint → `.agent/reference.md`.

**Demo acceptance (user-stated; binds the runtime-port milestone + M10).** The demo must show, with a REAL model on CURRENT, `Plot a scatter chart of revenue versus orders.` VERIFYING and the 2×2 dashboard prompt FAILING — probabilistically, as a general tendency. This SUPERSEDES the hold-model/quant-class-fixed reading of the weak-proposer rule: the stated gradient IS the acceptance criterion, so the port tunes toward it and measures PER CATEGORY. Three obstacles, only the third ever measured: the demo prompt OMITS `dataset_name`, which `ProposeRequest` requires (`service/models.py:190`) and bench supplies out-of-band as a separate corpus field; OWUI tool selection was 5/10 UNGUIDED pre-M8 and is unmeasured under guidance; end-to-end `verified_render` was **26/100 GUIDED vs 0/100 RAW**, dominated by `spec.decode`(51) + `encoding.fields_exist_in_plotted_table`(22). The harness computes `by_category` (a `Report` field, so `report.json` archives it) but `bench/reports/` is gitignored + ORIGIN-only ⇒ committed evidence needs a tracked path. **Numeric target, user-stated and now CLOSED: ≥ 70% of SIMPLE prompts verify AND ≥ 70% of COMPLICATED prompts fail, measured PER CATEGORY over the SEALED 20+20 held-out corpus on the host of record; the demo pair (exact scatter prompt + exact 2×2 dashboard prompt) = PUBLIC SENTINELS outside both corpora and both denominators, their outcomes required SEPARATELY at M10** — a sentinel inside the sealed sample would block pre-demo qualification while contributing only 1/20, and revealing it after a failure would invalidate the seal. The FAIL arm's structural reading is SUPERSEDED by the pivot below: under model-authored Python the fail arm is probabilistic, because the model may write anything and the allowlist is what refuses it.

**Closed-milestone records** — M1–M8 ranges · shipped surfaces · gauge bands → `.agent/archive/closed-milestones.md`; per-milestone detail → `.agent/archive/m<m>.md`. Status → the ledger above.

---

## Unit sizing rule (M1 evidence; binds every unit + every planning turn)

Size a unit at ~one module + its tests. An oracle or property/fuzz layer MAIN must author is its OWN unit, never bundled; a teammate-borne one (`orc`, `gate`) rides the unit it instruments and costs MAIN nothing. A DESIGN projecting well past the ~200K aim is mis-sized → split it. An IMPLEMENTATION running past the aim despite a complete recipe is OVER-deriving, not under-specified → pre-derive a gate-validated transcription recipe (`.agent/*_design.md`), TRANSCRIBE, reach the gate early, salvage-continue; an overshoot ≠ bad work and a completed unit's gate-green output stands (recipes deleted once consumed). Isolate native-dep probes to scratch sessions — probing inside the implementing window overflowed twice.

Basis: sizing reads MAIN's own implementing window — `main=` for MAIN-implemented units, `impl=` alone across M1–M9.6a whose `main=` metered COORDINATION only. **MAIN-implements re-baseline (binds every unit from M9.6b): one MAIN window now carries implementation AND coordination, which the delegated era spent as SEPARATE windows at `impl=` 53–100% + `main=` 44–98% ⇒ M9-era unit sizes do NOT fit and must be split smaller, coordination compressed into the model's own levers (teammate digests over bulk payloads, batch-ruled decision points, `triage` on failure logs).** `mate=` = teammate high-water; a unit chained into the previous unit's MAIN window records a cumulative `main=` + the tag `chained`. `impl=` through M9.1 = each teammate's FINAL-turn reading, which under-reads anyone reset by compaction or a stripped trail (M9.2 noted its 239K peak by hand); M9.3+ reads the HIGH-WATER turn via `context-gauge <name>` ⇒ compare basis-aware. M1 units landed at 39–88% of 200K.

Four cost drivers the statement-count estimate does NOT see; price each one explicitly at planning (M9 evidence, nine consecutive kernel-tier units):
- **A multi-teammate PREP WAVE is its own window.** Contract authoring + fan-out + finding rulings consumed a full MAIN window with ZERO production lines nine times running. Budget it separately, bank the certified contract + evidence on disk, and let implementation start fresh against it; a `STATE-<unit>.md` naming mode, accepted-but-unimplemented rulings and the next actions in order is what makes that boundary free. The wave also holds effective SIZING authority — it re-prices, deletes and adds scope, so re-split at WORK-UNIT entry on its evidence rather than defending the planned boundary.
- **ATTACHED STATE is a first-class window cost.** `.agent/` rides every session before the first tool call and re-attaches the project `CLAUDE.md` on every teammate dispatch and external-change echo; at 288 KB it alone bound a window in which one of five planned steps landed. Measure it at every planning turn; keep closed-unit detail in `.agent/archive/` and subsystem-conditional mechanics in `.agent/reference.md`.
- **A DUPLICATED-TWIN unit prices the TWIN, not the delta.** M9.9 predicted ~103 new production statements and shipped +236, because its own duplicate-don't-parameterize ruling made every formula guard a hand-written twin of a dataset guard — so the count scales with the EXISTING engine, not with the new decisions. Where a ruling mandates duplication, estimate from the surface being twinned.
- **A compaction boundary destroys the datum.** A unit that crossed one records the SUCCESSOR window's occupancy, not its cost ⇒ record it as ">1 window" and never cite the raw number as a fit. Over-window units, re-derived from every closed body at the M9 review: **M9.6b · M9.11 · M9.12a · M9.12b · M9.12c · M9.13b · M9.13d · M9.13e**. M9.11 belongs there and its `main=95%` must NOT be reused as a fit analog — the reading is a successor window that also spent ~20% on teardown, and M9.12's sizing rationale cited it as one. M9.13d (~1.6 windows) and M9.13e (~1.5) are chained, so their closing 52%/53% are likewise not fits.

Opposite sizing verdicts from two independent owners ⇒ arbitrate on measurement BASIS and record the loser's seam as a declared FALLBACK split point with a NUMERIC trigger rather than discarding it; a dissent priced in statements is reusable the moment the implementation window misbehaves (M9.12's A→B trigger fired at 94% and split the unit as declared).

---

## Active track — model-authored Python (M12 → M13 → M10)

User pivot (re-affirmed with the OWUI message contract verbatim). It SUPERSEDES the formula-mode demo plan and binds M10, M12 and M13. Six rulings:

1. **The model authors the EXECUTED Python.** The model writes real matplotlib code from a
   free-form prompt; the verifier statically checks it; on pass, THE MODEL'S OWN BYTES run in
   OWUI's Pyodide sandbox. Rejected, do not re-litigate: verifier-authored script (the M9/M10
   status quo) and verifier-RE-authored script after parsing the model's.
2. **Simple arm = CSV charts.** Bar/line/scatter over columns of a source CSV. NOT closed-form
   curves — formula mode stays shipped and unbroken but does not answer demo prompts.
3. **Acceptance = ≥70% / ≥70%, measured** per category over ~20 committed prompts each, on the host
   of record.
4. **OWUI operator surface.** Pass ⇒ inline PNG + the message `Figure verification passed`, the
   message NOT rendered into the image. Fail ⇒ output blocked + `Figure verification failed, no
   image produced`.
5. **The grammar may constrain FORMAT; it may never constrain ADMISSION.** The user's words bind
   here: *the model should attempt to write arbitrary Python that will then go through verification
   check*, and *these outcomes should not be hardcoded*. A grammar whose language IS the allowlisted
   subset moves the pass/fail boundary out of the verifier and into the decoder, so nothing can fail
   for a substantive reason. `res-port` measured all three arms on the port stack (`n=5`/category,
   greedy, toy AST subset — NOT the required ~20/category end-to-end run):
   - **Subset-only CFG** → simple 5/5 verify, complicated **0/5** fail. The dashboard prompt became
     an ordinary line plot. The gradient collapses exactly as predicted.
   - **Two-branch CFG** (`program | "# unsupported\\n"`) + 3 positive + 5 boundary-negative
     few-shots → simple 5/5 AND complicated 5/5 fail. It hits the numbers, but the MODEL decides the
     outcome by picking a branch and the verifier only rejects a sentinel comment. It also cannot
     emit arbitrary Python. **REJECTED against ruling 1 and the user's "not hardcoded" requirement**
     — recorded here with its measurement so it is not re-proposed as a win.
   - **Unconstrained** → 0/3 replies `ast.parse`-able. The cause is FORMAT, not capability: Markdown
     fences plus 256-token truncation. Neither was mitigated in the probe.

   Ruling: the primary arm constrains format only — de-fence the reply before `ast.parse` (bench
   already owns this rule as `_defenced_json_valid`) and raise `max_new_tokens` past truncation;
   optionally enforce "bare Python, no fence" with a grammar over PYTHON SYNTAX, never over the
   admitted subset. The verifier's allowlist stays the sole admission authority, so a complicated
   prompt fails because the program overreaches, not because the model declared defeat. M12
   measures this arm; the two-branch number stands only as the recorded upper bound of a rejected
   design. Guided decoding stays available for the JSON-spec modes, whose grammar is a TRANSPORT
   schema and never the safety boundary.
6. **Prompt surfaces carry TASK + FORMAT + dataset binding only — admission vocabulary is banned
   everywhere** (system prompts + few-shots, python mode, capture AND M10 calibration). Banned:
   allowlist terms, supported/unsupported framing, refusal/sentinel branches, negative examples
   that classify requests. A boundary-teaching prompt relocates the decision out of the verifier
   (soft form of the rejected two-branch CFG) AND collapses the fail arm the same way the
   subset-CFG did — the model answers a dashboard prompt with an admissible line plot, which then
   VERIFIES (`res-port` F6 measured exactly this). Calibration levers that remain: model choice,
   `max_new_tokens`, temperature, task phrasing, positive style examples registered as measured
   levers with a per-category re-read.

**Why the port precedes the new mode, despite M13 being hardware-free.** M13's allowlisted subset
IS the pass/fail boundary, and the ≥70% simple arm holds only if the subset covers the idioms a real
model actually writes. Designing it before observing real generations is designing blind. So M12
ships a SECOND deliverable beside the engine: a captured corpus of RAW model-authored Python across
both prompt categories.

**Anti-overfit ruling (protects the user's "not hardcoded" requirement).** The subset is designed by
IDIOM CLASS, never against memorized sample outputs. M12 reserves a HELD-OUT prompt set the subset
design never sees, and acceptance is measured there. A ≥70% figure taken on the design set alone is
not evidence and may not be recorded as the acceptance number. The seal is ENFORCED, not
instruction-only: the held-out corpus is committed as authenticated CIPHERTEXT with the private key
escrowed OFF-SESSION (user-held; plaintext + local key deleted after sealing), a committed manifest
{per-prompt id, category, sha256(normalized text)} + validator prove counts/disjointness WITHOUT
decryption, and reveal happens once against a frozen M13 config — any post-reveal tuning
invalidates the set and demands a freshly sealed one. NO generation is run against held-out prompts
before that reveal. Protocol mechanics → `.agent/reference.md` "Python corpus + held-out seal".

### Claim change — lands in `POC_SCOPE.md` at M13; stated here so no session ships the old wording

**RETIRED:** *"model smuggles code" is impossible by construction.* True only while the verifier
authored the executed bytes. Under ruling 1 it no longer does.

**REPLACEMENT — three claims at three different strengths:**
- **Recomputation (unchanged, strong).** The verifier independently recomputes every plotted number
  from the source CSV. Model-supplied plotted values stay impossible: the model supplies a program,
  never data.
- **Code admission (new, positive allowlist).** The submitted source parses to an AST whose every
  node, call target, attribute chain and literal kind is on a closed allowlist. Refusal is BY
  ALLOWLIST, not by construction.
- **Containment (new, TRUSTED not proven).** The Pyodide sandbox iframe (`allow-scripts`, no
  `allow-same-origin`) is trusted to contain the admitted script. It joins vl-convert/Vega,
  rasterization, browser and pixels in the TCB.

**THE PROJECTION GAP — M13's central design obligation.** The verifier proves properties of the AST
it PROJECTED; the sandbox executes the same bytes. *What the projection says the script plots* ≡
*what the script plots when executed* is an EQUIVALENCE that must either be closed by construction
(a subset narrow enough that projection is total and injective, with the subset's runtime semantics
pinned) or declared TRUSTED. It may not be left unstated. M13 planning rules which, per construct,
and the shipped claim must match the ruling.

**TCB additions M13 must declare.** `ast.parse` over untrusted bytes — it executes nothing but runs
the CPython parser on adversarial input, so deep nesting is a resource risk needing a byte cap AND a
nesting pre-scan AHEAD of `ast.parse`, not only a post-parse depth check. This reverses M9.2's "no
`eval`/`exec`/`compile`/`ast` reachable" property for the NEW module only; `expr.py` keeps it. Also
Pyodide's own `matplotlib`/`numpy`/`pandas` builds, whose versions the verifier does not control.

### M12 plan (gate MET at plan: env rebuilt from pins → `cuda_available True`, MX150 cc(6,1), fp16 matmul OK, driver 580.178.04 — probe logs recorded 580.173.02, userspace stack unaffected; `.venv-model` pre-staged with the exact stack, py3.12)

Seam + touch set + stack → "Measured port facts" above. All units MAIN-implemented; dGPU + ports
8000/8001/8080 + `.venv-model` + `.venv-webui` + `.webui-data` = MAIN-held every wave. Identity is a
SEARCH-DERIVED manifest (~24 active files incl. `models.py:119` `owned_by="openvino"`,
`webui/model_stub.py`, `bench/__init__.py`, `demo/e2e.py`, `.gitignore`), never a fixed list;
`POC_SCOPE.md` = proven NO-edit for M12 (zero identity matches; its claim lines 83/117/278/324 are
M13's). Evidence paths must be TRACKED (`bench/reports/` + `models/` are gitignored). Fresh numbers
are NOT ORIGIN-comparable (model family changed); frame every run as a new `(device, config)`
baseline. Mode isolation: NO python `GuidanceSchemaId` member in M12; capture artifacts labeled
`python_raw_unconstrained` vs `vplot_json_guided`; validators refuse cross-mode aggregation.

| unit | tier | scope | DONE gate |
|---|---|---|---|
| M12.1 | kernel | Runtime lock + settings port: `model_backend/runtime/{pyproject.toml,uv.lock,README.md}` — py3.12, `torch==2.7.1+cu126` via `[[tool.uv.index]]`+`tool.uv.sources`, transformers 5.16.1 · accelerate 1.14.0 · tokenizers 0.23.1 · xgrammar 0.2.3, FULL transitive lock → gitignored `.venv-model`; model snapshot → gitignored `models/Qwen2.5-Coder-0.5B-Instruct/` + committed HF revision SHA + per-file sha256 manifest; `model_backend/settings.py` defaults (device `cuda`, new model dir/name, env var NAMES unchanged, bounds 1536/512/65536 kept); pyproject mypy overrides `torch.*`/`transformers.*`/`xgrammar.*` (+`accelerate`/`tokenizers` iff imported); adapted settings pins | full gate green + `uv sync --locked` rebuild + `uv pip check` + snapshot hash verify |
| M12.2 | kernel | Engine core port, UNGUIDED: `engine.py` → torch/transformers (F5 recipe; suffix-slice decode, EOS-at-cap→`stop`/cap-no-EOS→`length`, scalar/list eos+pad ids, usage from generated suffix as literals, response ceiling after generation, lock serialization, identity-preserving `.to("cuda")` + same-object `generate` handoff); `guided_schema` naming → LOUD temporary `BackendError` (pinned, replaced in M12.3); `tests/test_model_backend.py` fake torch/transformers seams + canonical refusal bytes; committed smoke probe (from `7c9e408:probes/probe_stack.py`): live `:8001` serve → `/v1/models` + one completion + live over-cap refusal byte-compare, records device/cc/dtype/model/tok-s. FALLBACK at 45% before test rework: close on engine+adapted fakes green, contract battery → successor | full gate + smoke probe rc 0 with recorded tuple |
| M12.3 | kernel | xgrammar guidance + both-ways oracle: `schema_guidance.py` compile-at-load — `TokenizerInfo.from_huggingface` → `GrammarCompiler(...).compile_json_schema(schema, strict_mode=True, any_order=True)` (v0.2.3 API) → fresh `xgrammar.contrib.hf.LogitsProcessor` per generate; engine application block replaces the M12.2 refusal; hardware-free threading pins (per-id selection by identity, `None` ⇒ ZERO processor constructions, fresh processor across 2 calls); live oracle per schema: (a) guided generation strict-validates, (b) schema-specific negative that generic JSON accepts is refused, (c) other mode's strict-valid object refused (selector identity), (d) adversarial generation stays in-schema; + 3/3 greedy determinism + JOINT-corner probe (1536 prompt + 512 new; else lower a bound + record the tuple) | full gate + oracle rc 0 |
| M12.4 | kernel | Launcher CUDA arm + code identity + live OWUI loop: `launch.sh` default arm (CUDA preflights — `.venv-model` python + torch-cuda probe; drop `INTEL_ACCEL_ENV`/`OPENVINO_GENAI_PYTHON`; `--stub` intact); code-identity manifest subset (`src/verifier/service/settings.py`, `webui/settings.py`, `model_stub`+`models.py` `owned_by` → backend-neutral literal, `verified_chart.py`, `bench/__init__.py`, `demo/e2e.py`) + byte-pin test updates; hardware-free launcher tests (default=cuda, refusal-before-traps, `--stub` bypass, teardown, foreign-port non-adoption); LIVE: identity asserts (backend `/v1/models` + verifier health + schema digests) BEFORE browser dataset round-trip; 3 ports closed after | full gate + live round-trip; roadmap flips M10 precondition 2 → MET |
| M12.5 | kernel | Corpus spec + SEAL: `corpus/python/` — design manifest+prompts (24 simple + 24 complicated; ids, frozen category+idiom labels, dataset binding, sha256); held-out 20+20 as authenticated ciphertext + manifest + no-decrypt validator; `sentinels.json` (the 2 public demo prompts, outside both sets); contamination validators (exact counts, byte+normalized disjointness, bounded template similarity, zero prompt-surface overlap, family balance, label freeze); capture prompt v1 byte-pinned per ruling 6 (task line + dataset path/columns + `Return one complete Python program as bare source text, no Markdown fences.`, ZERO few-shots) + sha256 recorded in every capture row. Seal keys: user-escrowed (fallback = plaintext + seal labeled UNENFORCEABLE — user picks at handoff). FALLBACK at 45%: spec+seal close first, validators → successor | full gate + validators green pre-generation |
| M12.6 | kernel | Capture harness: HTTP-only, `/v1/chat/completions` direct; outbound body pinned WITHOUT `guided_schema` key (backend `structured_output=true` stays on; M12.3's `None`⇒0-processors pin proves omission suffices); versioned record schema + golden — exact model-content UTF-8 bytes, status/finish/usage, prompt sha, provenance tuple (model rev, device, cc, dtype, driver, lock digest, caps, commit+dirty); de-fence = DERIVED stat only, raw bytes canonical; hardware-free tests | full gate + golden |
| M12.7 | data | Design capture run: greedy over design 48 + the 2 sentinels (labeled, OUTSIDE category stats) → committed `corpus/python/captures/m12-design/` records + per-category stats (fence rate, `ast.parse`-after-defence rate, truncation rate); offline replay reproduces stats byte-identically; held-out NOT generated (seal) | replay reproduces committed stats |
| M12.8 | data | GUIDED JSON bench re-baseline: writer pre-ruled UNCHANGED (`by_category` = `Report` field, `harness.py:239`); add category-key-set+nonzero pin to `test_bench_harness`; ONE GUIDED dataset-corpus run → tracked `bench/baselines/m12-cuda/` (report + details + provenance sidecar) + `git check-ignore` negative test. RAW arm dropped (off-spine; the python arm owns the unconstrained observation) | full gate + committed baseline replayable |
| M12.9 | docs | Prose sweep + register audit: search-manifest remainder (root/`webui`/`bench`/`demo` READMEs — ORIGIN OpenVINO recipes labeled historical, byte-preserved; STE register on the four READMEs + launcher `usage()`/banner; REAL-model outcomes stay conditional); zero-unruled-match final search with per-line historical allowlist; README↔`POC_SCOPE.md` block quotes re-diffed | consistency pass + final search clean |

Order = 12.1→12.9 serial (MAIN implements). Edges: 12.2←12.1 · 12.3←12.2 · 12.4←12.3 ·
12.6←12.5+12.2 · 12.7←12.6 · 12.8←12.3+12.4 · 12.9 last · **M13 planning ← 12.7 committed** ·
capture ← backend only (never OWUI). ASAP landmarks: first live dGPU completion = 12.2 close;
interactive real-model OWUI = 12.4 close; M13 unblocked = 12.7 close.

### M13 scope sketch (unit split decided at M13 PLANNING)

New mode `pysrc-0.1` beside `vplot-0.1` and `vplot-formula-0.1`: bytes admission + nesting pre-scan ·
AST allowlist + refusal corpus · idiom projection to a dataset-mode plot spec · recomputation reusing
the shipped dataset evaluator and checks · certificate (`python-source` source kind, `python-script`
artifact kind under the VCert tagged algebra) · archive (`PlotSourceKind` + `PlotRole` widening, 5
totality sites) · `AttemptRoute.VERIFY_PYTHON` + `PROPOSE_PYTHON` at all NINE route surfaces ·
replay · `POST /verify-python` + `POST /propose-python` · corpus. The archived AND executed artifact
is the EXACT submitted bytes, hashed under a new domain tag. No canonical re-emission —
canonicalizing would make the executed bytes no longer the model's, contradicting ruling 1.

### M10 re-scope

`enforcement_filter.py` currently treats matplotlib as an UNVERIFIED signal and blocks it — the
user-reported bug, and now doubly wrong since matplotlib is what the demo must publish. Rework to:
verify an authentic verifier result → `execute:python` the ADMITTED script → publish inline PNG +
`Figure verification passed` → else block + `Figure verification failed, no image produced`.
`webui/settings.py` `function_name_filter_list` allowlists `proposeSpec` alone ⇒ OWUI must
additionally see the new python-mode operation. `webui/model_stub.py` classifies only the dataset
system prompt ⇒ it needs a python-mode arm or the stub tier cannot exercise the new path.

### Measured port facts (`res-port`; report tracked at `.agent/archive/m9-review/res-port.md`, probe sources at `7c9e408:probes/*` on `wt/res-port`)

Six probes on the host of record. The probe environment was deleted after verification and rebuilds
from `7c9e408:probes/runtime-pins.txt` + F5's CUDA-index command.

- **Stack.** `torch==2.7.1+cu126` (cu126 index) · `transformers==5.16.1` · `accelerate==1.14.0` ·
  `tokenizers==0.23.1` · `xgrammar==0.2.3`, on Python 3.12. Both byte-exact backend contracts
  survive in-process: the SAME `BatchEncoding` is length-checked then handed to `model.generate`
  (sha256 unchanged across the call), and an over-ceiling buffer refuses with spy call count 0 and
  the canonical `prompt_too_long` envelope. **The seam is spelled `engine.generate(...,
  guided_schema=...)`, not `guided`** — an earlier sketch had it wrong.
- **Quantization — corrects the "Pascal cannot do sub-fp16" premise.** NF4 loads and generates
  (520.8 MiB, 0.589 tok/s) and LLM.int8 does too (718.8 MiB, 3.340 tok/s, 21,504 fallback-cast
  warnings, and OUTSIDE its documented cc 7.5+ support). Both are slower than fp16 (1038.8 MiB,
  5.967 tok/s). GPTQModel, AutoAWQ and torchao all FAIL this stack by actual import or precondition.
  **fp16 is the supported primary path and the ~0.9B ceiling stands**; INT8/~1B is an explicit
  experimental fallback, never the reproducible stack.
- **Model.** `Qwen/Qwen2.5-Coder-0.5B-Instruct` fp16 (494M params, 942.3 MiB weights, Apache-2.0,
  5.52–5.71 tok/s, ~572.8 MiB free at a real 1536-total-token generation). Qwen3-0.6B is second but
  leaves 14.8 MiB of margin — operationally unsafe. LFM2-700M OOMs; Llama-3.2-1B and SmolLM2-1.7B
  exceed VRAM in weights alone.
- **Pyodide — CSV need NOT be inlined, and `pandas` IS present.** OWUI 0.10.2 bundles Pyodide
  `0.28.0.dev0` (CPython 3.13.2, wasm32) with `matplotlib 3.8.4`, `pandas 2.3.1`, `numpy 2.2.5`.
  Chat file metadata is forwarded, the browser fetches each file by id, and the sandbox writes the
  exact bytes to `/mnt/uploads/<filename>` ⇒ the admitted subset MAY use
  `pd.read_csv('/mnt/uploads/<verified-name>.csv')` and model-authored numbers never enter the
  executed bytes, which keeps the recomputation claim intact. The custom `execute:python` RPC must
  carry the `files` payload; a code-only RPC has no CSV despite the package being present. The
  worker sets `MPLBACKEND=AGG`, rewrites `plt.show()` to a `savefig(BytesIO, format="png")` and
  prints a base64 PNG data URI.
- **Grammar.** XGrammar 0.2.3 compiles a full EBNF CFG via `Grammar.from_ebnf(...)` →
  `TokenizerInfo.from_huggingface(...)` → `GrammarCompiler(...).compile_grammar(...)` → a fresh
  `xgrammar.contrib.hf.LogitsProcessor` per `generate`. Enforcement proved BOTH ways: a matcher fed
  `import os` returned `False`, and an adversarial prompt demanding `import os` still emitted only
  the admitted language. Cost is 2.8% per token (guided/free 0.972). Outlines 1.3.3 + llguidance
  1.8.0 are viable alternatives; `guidance` 0.3.1 conflicts with transformers 5.x.

---

## M9 — Verified formula-plot mode (headless)   (REVIEWED)

Shipped: 25 units over `2aa1ce5`..`4357c55`. The milestone record — pivot, thesis, gate, key
decisions, per-unit shipped surfaces, the M9.13 split ruling, the retained-branch inventory, and the
9-lens review wave with its full finding disposition — is at `.agent/archive/m9.md`
(`## M9 — milestone record`, `## M9.12c`, `## M9.13`, `## M9 review`). Read it on demand for
evidence; every ruling a later session must obey unprompted is promoted below.

**Review verdict.** 54 findings across 9 lenses. 13 applied in the close (2 HIGH · 8 MED · 3 LOW),
each credited by MAIN's own mutation rerun with sources restored and sha256-verified. The two HIGH
fixes: both demo scenario registries could be emptied while `run_walkthrough()` reported PASS over
0/0 with the whole suite green, and the recorded CPython 3.13.5 portability gate was RED because a
literal `1801`-byte attestation ceiling is patch-bound (the TCB embeds the interpreter version, so
the live payload is 1802 B on 3.13.14 and 1801 B on 3.13.5). Everything else is a named remediation
unit below or a `.agent/polish.md` entry.

**Coverage limit, declared.** `xcut-m9` saturated at 99% context after 4 of its 5 lenses ⇒ the
OBSOLESCENCE lens (stale-fact sweep across the repo) was NEVER MEASURED. It is unrun, not clean.

### M9 remediation — three named units, ordered BEHIND the active track

Kept out of the active track deliberately: none of them blocks M12 or M13, and the user's stated
priority is a real-model demo. They are units, not polish, because each one falsifies a claim the
project currently makes.

| unit | tier | scope | executable spec |
|---|---|---|---|
| M9R1 | kernel | Runtime closure of the formula typed API. Direct construction and `msgspec.structs.replace` admit near-miss literals/enums on `FormulaPlotSpec`/`FormulaXChannel`/`FormulaYChannel`/`FormulaDomain`, all five concrete formula structs admit undeclared SUBCLASSES (whose extra fields the deterministic encoder serializes and the strict decoder then refuses — a self-inconsistent archive/replay state), `Binary.op` is unguarded with a Binary-shaped catch-all in `print_expr`, `_interpret_expr` sends every unrecognised node to `_interpret_binary` and `_apply_binary` treats every non-add/sub/mul operator as division, and `_admit_formula_sample_points` orders endpoint-boundedness after strictness so production and the oracle disagree on a valid joint-failure input. Decode is unaffected; the falsified claims are "closed interpreter" and "direct-construction guards admit exactly parser-admitted nodes". | `wt/rev-m9-1` `db833f3` — 39 red tests over three files |
| M9R2 | kernel | Formula replay binds the plotted table by DIGEST alone and never proves canonical typed NDJSON, so a re-signed malformed table returns `recomputation_failed` with `integrity_ok=True` instead of `integrity_failed` at `plot_contents`. Reachable only by a trusted-key holder. `canon` has `serialize_table` and NO inverse ⇒ the fix needs a canonical-table parser, which is new kernel surface and a new TCB entry, not a review-close edit. | `wt/rev-m9-4` `e18bcfb` |
| M9R3 | docs | Claim + register hygiene, 20 findings (audited disposition of all 54 → `.agent/archive/m9.md`; per-finding text → `.agent/archive/m9-review/<lens>.md`). Archive prose conflates source-text identity with emitted-byte identity (M9.6a) and keeps process chronology the authoring rules prune; `.agent/roadmap.md` retains snapshot sizes and gate cardinalities without a snapshot qualifier; the trigger split is false in both directions (roadmap and memory still carry named-subsystem mechanics that belong behind `reference.md`, at 109,308 B attached across the three registers); two archived rulings are stranded with no live home (M9.1's no-`max_length` `DecimalText` reason, M9.4b's rejection of a widened generic `VerificationRun`); M9.12a has no direct archive heading; and 13 recorded gate/count/size/gauge values disagree with re-derivation from committed state or are unreproducible without a stated qualifier. The formula-carrier narrowing and the README POST-replay overclaim were FIXED at the close. | — |

### Forward-binding rulings promoted from the closed bodies

A session acting without the archive would get these wrong. Everything else about a closed unit lives at its `## M9.<u>` heading in `.agent/archive/m9.md`.

**Claim scope — what the project may and may not say.** A doc sweep that restates any of these loosely is a regression.

- **Script-artifact negative claim (M9.10 R8) — byte-identical in `emit_formula_outcome`, `POC_SCOPE.md`, `README.md`; never reword one copy alone.** *Only a verified 200 returns or archives a script artifact; every failed verdict does neither.* Stated over VERDICTS, never over non-2xx responses: emission + certification + signing necessarily precede the archive's transactional commit, so a capacity 507 or archive 500 can land AFTER a script was built and signed in memory. Those answer a Problem, never a verdict, and the atomic commit is what keeps the bytes from becoming durable or observable. The planned "never a script on failure" wording is FALSE — the script-size ceiling measures the EXACT emitted length, so a 483-byte script IS built before `resource.matplotlib_script_bytes` refuses at 482.
- **Replay reproduces no artifact bytes and no signature (M9.11 R2).** `exact` = the four certified hashes re-derive equal + the VCert v0.3 PAYLOAD re-encodes byte-identical + TCB matches with `drift=()`. The DSSE ENVELOPE is never reproduced and the response body carries no artifact bytes. Ratified wording: *verify → restart → replay recomputes the occurrence from the archived canonical spec alone and reports `exact`, while the certified table, script, spec and certificate stay independently retrievable.*
- **A certificate binds each check's `{id, method, status}` and nothing else (M9.9 F11).** Recomputation never re-derives an archived verdict's `message` bytes; those are signer-committed through the attempt manifest + plot bindings, so a message rewritten before signing replays `exact`.
- **Attestation proves canonical strict payload + exact bytes/MIME + trusted-key signature — nothing more (M9.6b).** A trusted key holder can re-sign a DIFFERENT authentic claim; artifact coherence and semantic truth belong to archive/replay. Shared implementation across two call sites does not prove the callers cannot drift.
- **Formula check claims map exactly (M9.4b):** values bounded = `deterministic_recompute`; rounding + points-from-recomputation = `construction`. There is NO candidate-point match claim. The solver proves nondecreasing x; sample strictness is the SOLE strictly-increasing authority.
- **Formula input is executable expression DATA (M9.4b)** ⇒ dataset mode's "pure data, no executable path" affirmation NEVER transfers to formula mode. The two modes need separately worded safety claims.
- **Float64 fidelity = round-tripping each projected point at its declared decimal scale + strictly increasing projected x (M9.5).** NOT binary64 identity, NOT pixels, NOT execution. The verifier imports no matplotlib and executes no script; M10's sandbox may execute ONLY the verifier-authored canonical `matplotlib-script-0.1` carrier.
- **An equivalent respelling does NOT certify identically (M9.10 F28).** `2*x + 1` and `2 * x+1` share THREE of the four certified digests — `formula_hash`, `plotted_table_hash` and `matplotlib_script_hash`, whose inputs are the canonical AST and the recomputed points, the emitted script embedding no submitted text — but differ in `spec_hash`, VCert payload and every derived id, because the canonical spec preserves the submitted text. `spec_hash` is the SOLE spelling-sensitive certified digest; wording that makes `formula_hash` the only respelling-invariant one is false.
- **`/table` + `/script` serve typed-relation, digest-addressed bytes and are NOT certificate-graph authenticated (M9.11 R3/F09).** Say exactly that; `p2` owns the residual (`p27` is the certificate-route MIME item).
- **Certified digests are DOMAIN-TAGGED, never a raw SHA-256 of the body (M9.13a).** Compare archived artifact bytes with `canon.hash_table_bytes` / `canon.hash_matplotlib_script` against the AUTHENTICATED VCert v0.3 bindings — never `hashlib.sha256(body)`, which fails on correct bytes, and never the POST verdict's unauthenticated fields. Any doc or test restating this as "SHA-256 of the returned bytes" is wrong.
- **A verified certificate is all-pass by construction (M9.13a).** `CertifiedCheck.status` is `Literal["pass"]` and the builder refuses every non-passing formula artifact, so a mixed-STATUS witness is unreachable through any supported flow and reaching it needs forgery. Mix by METHOD instead: the measured formula set is `{construction, deterministic_recompute, z3_smt}` over 13 checks, hand-stated as a literal.
- **Interpreter portability is measured, not general (M9.7p).** Canonical vectors are patch-portable through INJECTED exact TCBs across CPython 3.13.5↔3.13.14 ONLY — never claim all patches, hosts or platforms. Vector regeneration stays idempotent and preserves hand-authored vectors.
- **The proposer is transport + signed route only (M9.12).** Exact model reply bytes flow unchanged into the existing formula verifier; it adds no verification stage, schema or artifact role. Guidance is a closed operator-pinned selector (dataset schema | formula schema | unguided) whose recursive `pattern`/`format` stripping weakens structure only and grants NO semantic trust; explicit null = omission = unguided; prompting never guarantees compliance.
- **M9.12 makes NO measured formula error-gradient claim.** Its acceptance matrix is hardware-free + mock-driven; the one live smoke on the pinned `(device=NPU, model, quantization, guidance strength, max_tokens)` tuple stays **PARKED UNMET** (CURRENT has no NPU) and no device/model substitution may stand in for it, because the whole tuple is what holds the weak-calibration intent. A formula category benchmark is polish (`p32`), not M9 scope.

**Structure + order — how the shipped code must stay shaped.**

- **VCert v0.3 is a closed exact-family correlation (M9.6a/M9.6b/M9.7b-1).** Dataset = source + Vega + `DatasetTcb`; formula = `FormulaSource` + `matplotlib-script` + `FormulaTcb`, recursively containing exactly FOUR hashes. `FormulaTcb` carries nine formula/runtime fields and EXCLUDES Vega/font/matplotlib/browser/pixels. Dataset v0.3 stays representable but UN-emitted — dataset production remains v0.2. The formula builder RE-HASHES all four supplied carriers with the domain-tagged functions and REFUSES on mismatch (`vcert.py:531-562`) — reading it as "rebinds without recompute" is wrong. What it never does is SEMANTIC: no reparse, re-evaluate, re-sample, re-emit, re-solve or execute, so semantic coherence is upstream's while digest coherence is the builder's own. `vcert.py` is the neutral provenance leaf: renderers depend on it, never conversely. Certificate routing is a closed set of exported fixed-MIME wrappers, NOT a registry; selection is explicit RUNTIME policy pinned to trusted source metadata, never a static or type-level guarantee.
- **A fresh certificate stamps the LIVE TCB and never one sourced from the archive (M9.9).** Archived TCB values are comparison evidence only; injecting one erases both TCB and payload disagreement, so replay drift becomes undetectable by construction. The builder's `tcb=` seam is trusted-caller injection for vectors + tests (M9.7p) ⇒ live stamping is a property of the production call sites, not one the builder enforces on its caller.
- **Source kind derives from signed binding-role TOPOLOGY, never a new manifest field (M9.8b).** Route↔source and `plot_id ≡ plot_artifacts ≡ VERIFIED` settle ONCE pre-sign in `_validate_manifest_route_relations`; the bundle-layer duplicates were unreachable and stay DELETED — do not re-add them.
- **A rejected formula verdict OMITS the plot keys, never nulls them (M9.13b).** Its exact key set is `{attempt_id, layer, results, verified}`; `plot_id` is absent, and the audit's top-level `plot` is `null`. Assert the exact key SET — a `body["plot_id"] is None` test passes vacuously on a present-and-null key and raises `KeyError` on the real shape. Audit carriers are named in `role` VALUES, so no slot could hold a dataset carrier as null either: a rejected formula occurrence discloses exactly `("raw_spec", "verdict")` in BOTH audit arms.
- **A `/chart` 404 proves nothing alone (M9.13c R3; binds M10).** The route reads an ephemeral LRU and `_fetch_artifact` answers the same `404 "no such artifact"` for a malformed id, an unknown id and an evicted chart. Discriminate twice: co-located 200s on `/certificate` + `/table` + `/script` establish the plot EXISTS, and checking `/chart` both BEFORE and AFTER the post-restart replay separates "formula mode builds no chart" from "the chart was evicted" — the dataset case's replay repopulates its chart there.
- **A plot with no signed verified attempt answers 404 in BOTH modes (M9.8b F05).** `_replay_lowest` requires `lowest_verified_attempt_id` BEFORE any mode test, so no mode-specific replay outcome may be attached to such a plot; 501 was never universal and is now deleted.
- **Formula-mode replay classifies the occurrence's source mode BEFORE any verdict is constructed — and NOT before the attempt read (M9.11 R5).** Hoisting the lookup ahead of `read_attempt` flips a dangling attempt from a bounded 200 to 404 and charges every replay a second connect + schema validation. Two independent roles demanded the stronger order; the ratified predicate won and the suites were corrected.
- **One cumulative `WorkBudget` spans the run (M9.3; M11 inherits).** Tariff: admitted sample = `5 + AST tariff` where EVERY node costs 1 and `Pow` costs `1 + abs(exponent)`; the one-node `x` therefore costs `6 × samples`, three-node `x+x` costs `8 × samples` (measured 66/88 over 11 samples). Reading `6` as per-variable-occurrence overstates every multi-node formula. Every charge precedes its guarded operation and a refused charge consumes zero. Check order = domain-order → sample cap → endpoint bits → parse → schedule/bounds/strictness → row eval → y quantize → row admit. Quantization is exact-integer HALF_EVEN, independent of ambient Decimal context, float and string conversion.
- **Parser ABSOLUTE ceilings are trusted-caller policy bounds, not clamps** (`_MAX_FORMULA_AST_DEPTH=64`, `_MAX_FORMULA_PAREN_DEPTH=64`, `_MAX_FORMULA_DIGITS=512`): `_validate_limits` is the FIRST statement of `parse_expr`, ahead of allowlist/bytes/lexing, and over-ceiling policy raises a native `ValueError` naming the field. 512 digits stays under CPython's MINIMUM legal `str_digits_check_threshold` (640) ⇒ conversion-safe at every legal interpreter setting. Stack headroom (267 active calls at the 32/32 defaults, 523 at the 64/64 ceilings) ASSUMES the default 1000-frame limit — a process lowering it below ~527 invalidates the basis. Direct AST construction of integers/variables enforces the parser invariants; a hand-built over-depth AST is trusted misuse, not a supported input.
- **Effective expression envelope (binds M11 `derive` corpus authoring + sizing):** `max_formula_ast_depth=32` binds long flat sums FIRST — a left-associative chain's AST height equals its term count, so the default caps a flat sum at exactly 32 terms; term 33 raises `resource.formula_ast_depth` ("formula AST depth limit 32 exceeded at position 64"). Tokens are NOT the binding ceiling — 33 terms spend 65 of the 256 admitted tokens. Operator-tunable up to the absolute ceiling 64.
- **Canonical normalization is exactly** whitespace, redundant grouping, decimal-literal spelling (lowest-terms `Fraction`), unary plus, and integer-exponent sign/leading-zero spelling — no constant folding, no algebraic rewrite. That list is a PROVENANCE claim: `canon.FormulaSource.ast` hashes this text, so printer injectivity + determinism are provenance-critical.
- **Check ORDER is a corpus obligation:** `formula.domain_ordered` MUST be evaluated before `formula.sample_points_strictly_increasing` — a reversed domain always also yields a descending schedule, so no fixture can isolate them (fb17 + `examples/README.md` record it).
- **Archive containment is insert-time admission only.** `plot_references_match_source` is `BEFORE INSERT`; it admits no cross-mode reference through INSERT and does NOT defend a direct UPDATE (`p2`). Never restate it as "unrepresentable".
- **`formula_source` has no canonical decoder (M9.7b-2).** The archive binds its exact bytes by digest alone and upstream owns cross-carrier coherence; generic blob reads deliberately report identical storage-absence for a cross-mode reference and for a missing same-mode one.
- **Registry inventory rule:** register only check IDs whose emitter already exists — registering an ID commits the project to emitting it. A planned-but-unemitted ID stays unregistered and refusal-pinned. Assign methods by MECHANISM, never by ID prefix.

**REJECTED — do not re-litigate.**

- **A parser work meter on `max_formula_work_units` (M9.2).** Parse cost is bounded structurally by admitted bytes/tokens/nodes/depth/paren/digits + the fixed 512-digit ceiling; a second accounting authority adds no guarantee and collides with the evaluator's cumulative budget, which is the EVALUATOR's alone.
- **Self-scan of the emitted script (M9.5)** — it duplicates authority without adding independent assurance.
- **A third verdict shape (M9.11).** Formula faults stay formula-shaped; an unclassifiable occurrence mode becomes a logged generic 500.

**Retained `wt/` branches** — the only tracked copy of their artifacts; full inventory with
per-branch evidence → `.agent/archive/m9.md`. Live tips, audited against `git branch --list 'wt/*'`
at the M9 review close — 16 branches, no worktree checked out for any of them:
`wt/scout-m9u11` `c0022de` · `wt/map-m9u12` `f851789` · `wt/scout-m9u12` `1635d3c` ·
`wt/rev-m9u12` `53b898b` (`p33`) · `wt/test-m9u7b2` `54fe1d4` (`p8`) ·
`wt/test-m9u10` `845d49f` (`p25`) · `wt/rev-m9u10` `a1171dc` · `wt/test-m9u13a` `6c1bd49` ·
`wt/rev-m9-1` `db833f3` (M9R1) · `wt/rev-m9-4` `e18bcfb` (M9R2) ·
`wt/rev-m9-2` `8093b0a` · `wt/rev-m9-5` `6dac756` · `wt/rev-m9-6` `814e513` ·
`wt/xcut-m9` `a2abd82` · `wt/audit-m9` `d2592e3` · `wt/res-port` `7c9e408` (M12 seed).
`wt/orc-m9u7a` is GONE from every reachable ref (`p3` must rebuild, not recover). Cite a branch TIP,
never a pre-amend SHA: the review close found `70af87f` cited for M9R1 while the live tip `db833f3`
carried 24 further lines in `test_review_m9_eval_contract.py`. Audit this list at every milestone
close — it drifted by two entries before M9.13b.
**M10 + M11 design seeds** — the source-confirmed OWUI sandbox mechanism (trusted outlet filter → signature check → direct `execute:python` RPC → Pyodide → inline PNG), its settings/gating constraints, the `enforcement_filter.py` rework, the 3-unit split, and M11's `Derive` transform design + its open questions → `.agent/reference.md` "Future-milestone design seeds". Read it at that milestone's PLANNING turn.
