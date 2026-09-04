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
| M14 | Portable OWUI artifact — embedded paste-in, air-gap-safe (ruling 7) | — (user request) | M10 DONE (demo established) | UNPLANNED |

Plan each milestone only when it becomes active (prior one REVIEWED). M3/M4/M6/M7/M10/M14 are gated — confirm preconditions functionally at the planning turn, and bring generated/heavy inputs into scope only when the gate needs them. A gate unmet there ⇒ set the milestone PARKED with its named precondition verbatim, clearing the marker only when a functional recheck meets it; M11 is ungated + sequence-adjustable, so M10's live-OWUI gate parks rather than stalls the roadmap.

**Host change — model tier only.** The proposer's live stack was built on the ORIGIN host (Intel NPU + OpenVINO); CURRENT has no NPU, so the NPU-era config cannot load here and no REAL-MODEL arm of the M3/M4/M6/M7/M8 live-stack gates or M9.12's live formula smoke can be REPRODUCED on CURRENT — the ORIGIN tuple no longer exists on this machine, and M12's replacement stack is a different `(device, config)` whose numbers do not substitute for theirs. Those REVIEWED verdicts STAND — their evidence was validly taken on ORIGIN. The trusted core is host-free (verifier + bench + tests + demo gate fully on CURRENT) ⇒ M9 is unaffected and stays active, while **M10 carries a SECOND precondition beyond browser-live OWUI: a working local proposer on the host of record**. **M10 precondition 1 = MET on CURRENT**: `webui/launch.sh --stub` stands all three services up and a verified chart renders inline in the browser. **Precondition 2 is PART-MET as of M12.2**: the backend itself now serves real dGPU completions on CURRENT (`tok_s=10.291`, MX150 cc 6.1 fp16), but `webui/launch.sh` still carries only the OpenVINO arm, so the full stack does not stand up until M12.4 — that close owns the flip to MET. M10's live-proposer arms stay parked until then; its sandbox-execution arms are probeable today. A runtime port is its own UNPLANNED milestone, never an M9 unit. Host inventory, the measured runtime verdict, the two byte-exact backend contracts any replacement engine must reproduce, the evidence a swap does and does not invalidate + the weak-proposer calibration constraint → `.agent/reference.md`.

**Demo acceptance (user-stated; binds the runtime-port milestone + M10).** The demo must show, with a REAL model on CURRENT, `Plot a scatter chart of revenue versus orders.` VERIFYING and the 2×2 dashboard prompt FAILING — probabilistically, as a general tendency. This SUPERSEDES the hold-model/quant-class-fixed reading of the weak-proposer rule: the stated gradient IS the acceptance criterion, so the port tunes toward it and measures PER CATEGORY. Three obstacles, only the third ever measured: the demo prompt OMITS `dataset_name`, which `ProposeRequest` requires (`service/models.py:190`) and bench supplies out-of-band as a separate corpus field; OWUI tool selection was 5/10 UNGUIDED pre-M8 and is unmeasured under guidance; end-to-end `verified_render` was **26/100 GUIDED vs 0/100 RAW**, dominated by `spec.decode`(51) + `encoding.fields_exist_in_plotted_table`(22). The harness computes `by_category` (a `Report` field, so `report.json` archives it) but `bench/reports/` is gitignored + ORIGIN-only ⇒ committed evidence needs a tracked path. **Numeric target, user-stated and now CLOSED: ≥ 70% of SIMPLE prompts verify AND ≥ 70% of COMPLICATED prompts fail, measured PER CATEGORY over the 20+20 held-out corpus on the host of record; the demo pair (exact scatter prompt + exact 2×2 dashboard prompt) = PUBLIC SENTINELS outside both corpora and both denominators, their outcomes required SEPARATELY at M10** — each sentinel must pass outright while it could contribute only 1/20 to a category rate, so it is scored on its own. The FAIL arm's structural reading is SUPERSEDED by the pivot below: under model-authored Python the fail arm is probabilistic, because the model may write anything and the allowlist is what refuses it.

**Closed-milestone records** — M1–M8 ranges · shipped surfaces · gauge bands → `.agent/archive/closed-milestones.md`; per-milestone detail → `.agent/archive/m<m>.md`. Status → the ledger above.

---

## Unit sizing rule (M1 evidence; binds every unit + every planning turn)

Size a unit at ~one module + its tests. An oracle or property/fuzz layer MAIN must author is its OWN unit, never bundled; a teammate-borne one (`orc`, `gate`) rides the unit it instruments and costs MAIN nothing. A DESIGN projecting well past the ~200K aim is mis-sized → split it. An IMPLEMENTATION running past the aim despite a complete recipe is OVER-deriving, not under-specified → pre-derive a gate-validated transcription recipe (`.agent/*_design.md`), TRANSCRIBE, reach the gate early, salvage-continue; an overshoot ≠ bad work and a completed unit's gate-green output stands (recipes deleted once consumed). Isolate native-dep probes to scratch sessions — probing inside the implementing window overflowed twice.

Basis: sizing reads MAIN's own implementing window — `main=` for MAIN-implemented units, `impl=` alone across M1–M9.6a whose `main=` metered COORDINATION only. **MAIN-implements re-baseline (binds every unit from M9.6b): one MAIN window now carries implementation AND coordination, which the delegated era spent as SEPARATE windows at `impl=` 53–100% + `main=` 44–98% ⇒ M9-era unit sizes do NOT fit and must be split smaller, coordination compressed into the model's own levers (teammate digests over bulk payloads, batch-ruled decision points, `triage` on failure logs).** `mate=` = teammate high-water; `harvest=` (MAIN's gauge as implementation starts) joins the close from M12.4 and meters the prep+harvest term the four drivers below price qualitatively. CHAINING IS RETIRED — one WORK-UNIT session ships one unit — so the cumulative `main=` + `chained` tag read as historical (M9.13d/e) and no future unit records them. `impl=` through M9.1 = each teammate's FINAL-turn reading, which under-reads anyone reset by compaction or a stripped trail (M9.2 noted its 239K peak by hand); M9.3+ reads the HIGH-WATER turn via `context-gauge <name>` ⇒ compare basis-aware. M1 units landed at 39–88% of 200K.

**Calibration — corrections live in the multiplier, never in the bottom-up figure.** Size against the nearest analog, then multiply by the measured `main=`/`est` ratio and record both as `est <raw>K → <cal>K`. **No such pair exists yet**: M1–M12.3b were sized qualitatively, so every recorded `main=` is an actual with NO estimate beside it and the multiplier is UNCOMPUTABLE — not 1.0, and not substitutable by the over-window list below. **M12.4 is the calibration probe** — record `est` at unit entry, `main=` at close, re-size M12.5–M12.9 from that ratio, and keep a tier with no analog explicitly uncalibrated. The one existing actual/estimate datum is STATEMENT-scoped, not gauge-scoped, and covers duplicated-twin scope alone: M9.9's ~103 → +236 = 2.29× (driver below).

Four cost drivers the statement-count estimate does NOT see; price each one explicitly at planning (M9 evidence, nine consecutive kernel-tier units):
- **A multi-teammate PREP WAVE is its own window.** Contract authoring + fan-out + finding rulings consumed a full MAIN window with ZERO production lines nine times running. Budget it separately, bank the certified contract + evidence on disk, and let implementation start fresh against it; a `STATE-<unit>.md` naming mode, accepted-but-unimplemented rulings and the next actions in order is what makes that boundary free. The wave also holds effective SIZING authority — it re-prices, deletes and adds scope, so re-split at WORK-UNIT entry on its evidence rather than defending the planned boundary.
- **ATTACHED STATE is a first-class window cost.** `roadmap.md` + `memory.md` + `polish.md` ride every session before the first tool call, and the project `CLAUDE.md` re-attaches on every teammate dispatch and external-change echo; the M9-era snapshot measured 288 KB and alone bound a window in which one of five planned steps landed (135,606 B across the three at this commit). Measure it at every planning turn; keep closed-unit detail in `.agent/archive/`, subsystem-conditional mechanics in `.agent/reference.md`, and dispatch inputs in `.agent/contracts/`.
- **A DUPLICATED-TWIN unit prices the TWIN, not the delta.** M9.9 predicted ~103 new production statements and shipped +236, because its own duplicate-don't-parameterize ruling made every formula guard a hand-written twin of a dataset guard — so the count scales with the EXISTING engine, not with the new decisions. Where a ruling mandates duplication, estimate from the surface being twinned.
- **A compaction boundary destroys the datum.** A unit that crossed one records the SUCCESSOR window's occupancy, not its cost ⇒ record it as ">1 window" and never cite the raw number as a fit. Over-window units, re-derived from every closed body at the M9 review, plus M12.2: **M9.6b · M9.11 · M9.12a · M9.12b · M9.12c · M9.13b · M9.13d · M9.13e · M12.2** (M12.2 spent prep, implementation and close/verify in three separate windows — its 64% close reading is a CLOSE cost, not a unit fit). M9.11 belongs there and its `main=95%` must NOT be reused as a fit analog — the reading is a successor window that also spent ~20% on teardown, and M9.12's sizing rationale cited it as one. M9.13d (~1.6 windows) and M9.13e (~1.5) are chained, so their closing 52%/53% are likewise not fits.

Opposite sizing verdicts from two independent owners ⇒ arbitrate on measurement BASIS and record the loser's seam as a declared FALLBACK split point with a NUMERIC trigger rather than discarding it; a dissent priced in statements is reusable the moment the implementation window misbehaves (M9.12's A→B trigger fired at 94% and split the unit as declared).

---

## Active track — model-authored Python (M12 → M13 → M10)

User pivot (re-affirmed with the OWUI message contract verbatim). It SUPERSEDES the formula-mode demo plan and binds M10, M12 and M13. Seven rulings:

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
7. **Demo-grade project + paste-in production artifact.** The OWUI goal is a DEMO; nothing here
   demands security or rigorous-integrity machinery — crypto sealing, key escrow, tamper-evidence
   ceremonies = REJECTED over-engineering (the seal proposal drew this ruling; do not re-propose
   the class). Correctness testing is unaffected; anti-overfit stays instruction-level (ruling
   below). Production artifact AFTER the demo: something an ADMIN places into an EXISTING OWUI
   instance through the web interface, installed manually by the user — that instance has Pyodide
   available and accepts added skills + tools. The repo's own stack (launcher, local model,
   verifier service) = demo harness, not the deliverable shape. Packaging DECIDED (user): the
   verifier is EMBEDDED in the pasted file — ONE artifact that works on instances with NO outside
   network access; a separately-maintained networked variant is REJECTED. Consequences: the
   artifact makes zero outbound calls and needs zero install-time fetches (OWUI frontmatter
   `requirements:` pip-installs ⇒ banned; imports = stdlib + packages the OWUI backend already
   bundles); single-source rule — the pysrc verification core is written ONCE and M14 inlines it
   (generated bundle OK, hand-maintained fork banned), the repo service wrapping the same core for
   the demo. Binds M13 layering (see sketch) + seeds M14.

**Why the port precedes the new mode, despite M13 being hardware-free.** M13's allowlisted subset
IS the pass/fail boundary, and the ≥70% simple arm holds only if the subset covers the idioms a real
model actually writes. Designing it before observing real generations is designing blind. So M12
ships a SECOND deliverable beside the engine: a captured corpus of RAW model-authored Python across
both prompt categories.

**Anti-overfit ruling (protects the user's "not hardcoded" requirement).** The subset is designed by
IDIOM CLASS, never against memorized sample outputs. M12 reserves a HELD-OUT prompt set the subset
design never reads, and acceptance is measured there. A ≥70% figure taken on the design set alone is
not evidence and may not be recorded as the acceptance number. Discipline is INSTRUCTION-LEVEL per
ruling 7: held-out prompts live as committed plaintext in `corpus/python/heldout/`; subset design +
tuning read the design set + its captures only; NO generation runs against held-out prompts until
the M13 config is frozen for the acceptance read. Corpus mechanics → `.agent/reference.md` "Python
corpus".

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
SEARCH-DERIVED manifest (~24 active files; `models.py` `owned_by` already landed at M12.2, leaving
`webui/model_stub.py`, `bench/__init__.py`, `demo/e2e.py`, `.gitignore`), never a fixed list;
`POC_SCOPE.md` = proven NO-edit for M12 (zero identity matches; its claim lines 83/117/278/324 are
M13's). Evidence paths must be TRACKED (`bench/reports/` + `models/` are gitignored). Fresh numbers
are NOT ORIGIN-comparable (model family changed); frame every run as a new `(device, config)`
baseline. Mode isolation: NO python `GuidanceSchemaId` member in M12; capture artifacts labeled
`python_raw_unconstrained` vs `vplot_json_guided`; validators refuse cross-mode aggregation.

| unit | tier | status | scope | DONE gate |
|---|---|---|---|---|
| M12.1 | kernel | **DONE** | Runtime lock + settings port. Shipped `model_backend/runtime/{pyproject.toml,uv.lock,snapshot.json,README.md}` · `model_backend/snapshot.py` (4-class verifier, `--verify`/`--write`) · settings defaults → `cuda` + `models/Qwen2.5-Coder-0.5B-Instruct` · root mypy overrides · `tests/test_model_backend_runtime.py` (23 predicates). Record → `.agent/archive/m12.md` | met |
| M12.2 | kernel | **DONE** | Engine core port, UNGUIDED. Shipped `model_backend/engine.py` (torch/transformers, no torch import) · `model_backend/smoke.py` (live probe) · `owned_by` → `local` · docstrings de-OpenVINO'd · `tests/test_model_backend.py` 92 tests. First live dGPU completion: `tok_s=10.291` on MX150 cc 6.1 fp16. Record → `.agent/archive/m12.md` | met |
| M12.3a | kernel | **DONE** | xgrammar guidance restored in `engine.py` (`_compile_guidance` + per-call processor + load-time `guidance_unusable`); `tests/test_m12u3_guidance.py` 20 predicates `G1`–`G18`+`G2b`+`G6b`; `tests/test_rev_m12u3_contract.py` 3 subprocess checks; seam grew the xgrammar fake, P13 deleted. Gate rc 0 ×4, 3013 passed, 100% cov. Record → `.agent/archive/m12.md` | full gate |
| M12.3b | kernel | **DONE** | `model_backend/guidance_oracle.py` — live both-ways oracle, `O1`–`O8` rc 0 on the host of record. It FOUND a non-terminating grammar config M12.3a had shipped: `engine.py` now pins `any_order=False` + `max_whitespace_cnt=_MAX_GUIDANCE_WHITESPACE` (=8, measured), `G4` re-pinned to that exact-dict literal, `O2b` re-based onto the `pattern`/`format`-stripping witness. Runtime dev group + P15b + P31. Gate rc 0 ×4, 3015 passed, 100% cov. Record → `.agent/archive/m12.md` | oracle rc 0 on the host of record |
| M12.4 | kernel | OPEN | Launcher CUDA arm + code identity + live OWUI loop: `launch.sh` default arm (CUDA preflights — `.venv-model` python + torch-cuda probe; drop `INTEL_ACCEL_ENV`/`OPENVINO_GENAI_PYTHON`; `--stub` intact); code-identity manifest subset (`src/verifier/service/settings.py`, `webui/settings.py`, `webui/model_stub.py`, `verified_chart.py`, `bench/__init__.py`, `demo/e2e.py`) + byte-pin test updates — `models.py` `owned_by` already landed at M12.2; hardware-free launcher tests (default=cuda, refusal-before-traps, `--stub` bypass, teardown, foreign-port non-adoption); LIVE: identity asserts (backend `/v1/models` + verifier health + schema digests) BEFORE browser dataset round-trip; 3 ports closed after | full gate + live round-trip; roadmap flips M10 precondition 2 → MET |
| M12.5 | data | OPEN | Corpus authoring: `corpus/python/` — design manifest+prompts (24 simple + 24 complicated; ids, category+idiom labels, dataset binding); held-out 20+20 PLAINTEXT under `heldout/` (ruling-7 discipline: read only at the frozen-config acceptance run); `sentinels.json` (the 2 public demo prompts, outside both sets); ONE structural validator (counts, unique ids, category balance, design↔held-out prompt disjointness, zero admission vocabulary in any prompt per ruling 6); capture prompt v1 byte-pinned per ruling 6 (task line + dataset path/columns + `Return one complete Python program as bare source text, no Markdown fences.`, ZERO few-shots) + sha256 recorded in every capture row | full gate + validator green pre-generation |
| M12.6 | kernel | OPEN | Capture harness: HTTP-only, `/v1/chat/completions` direct; outbound body pinned WITHOUT `guided_schema` key (backend `structured_output=true` stays on; M12.3's `None`⇒0-processors pin proves omission suffices); versioned record schema + golden — exact model-content UTF-8 bytes, status/finish/usage, prompt sha, provenance tuple (model rev, device, cc, dtype, driver, lock digest, caps, commit+dirty); de-fence = DERIVED stat only, raw bytes canonical; hardware-free tests | full gate + golden |
| M12.7 | data | OPEN | Design capture run: greedy over design 48 + the 2 sentinels (labeled, OUTSIDE category stats) → committed `corpus/python/captures/m12-design/` records + per-category stats (fence rate, `ast.parse`-after-defence rate, truncation rate); offline replay reproduces stats byte-identically; held-out NOT generated (ruling-7 discipline) | replay reproduces committed stats |
| M12.8 | data | OPEN | GUIDED JSON bench re-baseline: writer pre-ruled UNCHANGED (`by_category` = `Report` field, `harness.py:239`); add category-key-set+nonzero pin to `test_bench_harness`; ONE GUIDED dataset-corpus run → tracked `bench/baselines/m12-cuda/` (report + details + provenance sidecar) + `git check-ignore` negative test. RAW arm dropped (off-spine; the python arm owns the unconstrained observation). **Expect the M12-CUDA rate to MOVE and do not treat ORIGIN's `26/100` as the comparand**: M12.3b measured that xgrammar's library-default whitespace policy lets a greedy model pad a finished document to the token cap, and ORIGIN's guided arm ran OpenVINO GenAI's `StructuredOutputConfig` over xgrammar with unknown, plausibly-default bounds — a HYPOTHESIS (never measured on ORIGIN, unmeasurable now) that its `spec.decode`(51) residual was partly cap-truncation rather than model error. Report the new number standalone; any ORIGIN delta needs the two-host + two-stack caveat | full gate + committed baseline replayable |
| M12.9 | docs | OPEN | Prose sweep + register audit: search-manifest remainder (root/`webui`/`bench`/`demo` READMEs — ORIGIN OpenVINO recipes labeled historical, byte-preserved; STE register on the four READMEs + launcher `usage()`/banner; REAL-model outcomes stay conditional); zero-unruled-match final search with per-line historical allowlist; README↔`POC_SCOPE.md` block quotes re-diffed | consistency pass + final search clean |

Order = 12.1→12.9 serial (MAIN implements). Edges: 12.2←12.1 · 12.3←12.2 · 12.4←12.3 ·
12.6←12.5+12.2 · 12.7←12.6 · 12.8←12.3+12.4 · 12.9 last · **M13 planning ← 12.7 committed** ·
capture ← backend only (never OWUI). ASAP landmarks: first live dGPU completion = **LANDED at the
12.2 close**; interactive real-model OWUI = 12.4 close; M13 unblocked = 12.7 close.

**Unit status.** M12.1 + M12.2 + M12.3a + M12.3b DONE (records → `.agent/archive/m12.md`);
M12.4 is next, M12.4–M12.9 untouched. The repo LAUNCHES again — M12.2 closed the non-launchable
window with the project's first live dGPU completion, M12.3a restored schema guidance on top of it,
and M12.3b proved LIVE that guided generation terminates and yields parseable, guidance-valid
documents on both schema ids under both task and adversarial prompts.

**Guidance claim boundary — binds every surface, forever, not just guidance code.** *"The grammar
enforces the guidance schema"* is FALSE and may not be shipped in any docstring, README line,
health-surface description, commit body or report. xgrammar silently ignores JSON-Schema keywords
it does not support, and the guidance schemas additionally STRIP `pattern`/`format` before
compilation. The shippable claim is: *the grammar constrains generation TOWARD the
guidance schema; what it actually enforces is evidenced by the named live-oracle witnesses, and
strict verifier re-decode remains the sole authority on admission.* Never credit "the subset
xgrammar supports" either — that reads as exhaustive coverage of a delimited keyword set, while the
evidence is a handful of named witnesses. This is attached rather than filed under the guidance
trigger because a session writing a README or a health surface does not know it is touching
guidance. Mechanics → `.agent/reference.md` "xgrammar 0.2.3 pinned behaviours".

**Engine rulings still binding after M12.2.**
1. **`engine.py` writes NO `import torch` — and that is now the WHOLE of the rule.** `dtype=`
   accepts the string `"float16"`, `generate` is already `@torch.no_grad()`, and `from_pretrained`
   already returns an eval-mode module, so tensors stay opaque. **M12.3 REVERSES the rest of this
   ruling as originally written**, on measurement: `engine.py` also imports `xgrammar`, so the test
   seam installs TWO fakes rather than one, and `import xgrammar` ALONE pulls `torch` AND
   `transformers` into `sys.modules` — so torch no longer enters `model_backend/` through
   `smoke.py` alone. The surviving obligation is narrow and literal: no torch import statement in
   `engine.py`, tensors handled only through `.shape`, slicing and `int()`. Do not restate the
   retired "sole native import" or "one fake, not two" wording.
2. **EOS/PAD authority is `model.generation_config`, never the tokenizer, and no `eos_token_id`
   reaches `generate`** (§8 R01). The classification set and the stopping set are one value. EOS
   refuses at load (`generation_config_unusable`, 500); PAD degrades to `min(eos_ids)` — EOS drives
   classification AND stopping, PAD only fills positions a single unpadded sequence never reaches.
3. **ADMISSION PRECEDES GUIDANCE, at the same site the M12.2 build refused from.** An over-cap
   prompt naming a schema answers 400 `prompt_too_long` with zero processor constructions and zero
   `generate` calls — never a guidance fault. Measured live at the M12.2 close and pinned by G14.
   Guiding first would silently reclassify that request from a 422 policy refusal to a 502.
4. **D6's KNOWN-BROKEN window is CLOSED (M12.3a).** A named `guided_schema` now attaches that id's
   compiled grammar; naming one while `structured_output` is disabled generates UNGUIDED and does
   NOT raise, which is the shipped best-effort wire contract (`models.py:59`). `guidance_unavailable`
   no longer exists anywhere in the tree. Guidance faults refuse LOUDLY at LOAD instead — one
   surface, 500 `guidance_unusable`, with zero device transfers — because a silent unguided degrade
   is the fail-open class the reference register warns about.

**Prep-wave budgeting (M12.1 + M12.2 measurements; binds every remaining unit).** A prep wave is its
OWN window — twelve consecutive units have split that way, MAIN spending a full window on contract
authoring, fan-out and finding rulings with ZERO production lines. Budget the two separately. Two
sizing rules fall out:
- **Size against the CLOSE reading, never the gate-green one.** M12.1 reached the gate at ~82% and
  closed at **94%**: archive authoring, roadmap surgery, register fixes and worktree teardown are
  ~12% of a window by themselves.
- **Cap a prep wave at THREE teammates, or plan the fourth's harvest into a SECOND prep window from
  the start.** M12.1's three (`map`+`test`+`rev`) harvested inside one window at ~76%; M12.2's four
  did not — MAIN reached ~70% after harvesting `map`+`res` alone. A `res` role earns its slot only
  where the unit turns on external-API facts the repo does not already record.

A prep wave still holds sizing authority — re-split at WORK-UNIT entry on its evidence, not on the
planned boundary.

### M13 scope sketch (unit split decided at M13 PLANNING)

New mode `pysrc-0.1` beside `vplot-0.1` and `vplot-formula-0.1`: bytes admission + nesting pre-scan ·
AST allowlist + refusal corpus · idiom projection to a dataset-mode plot spec · recomputation reusing
the shipped dataset evaluator and checks · certificate (`python-source` source kind, `python-script`
artifact kind under the VCert tagged algebra) · archive (`PlotSourceKind` + `PlotRole` widening, 5
totality sites) · `AttemptRoute.VERIFY_PYTHON` + `PROPOSE_PYTHON` at all NINE route surfaces ·
replay · `POST /verify-python` + `POST /propose-python` · corpus. The archived AND executed artifact
is the EXACT submitted bytes, hashed under a new domain tag. No canonical re-emission —
canonicalizing would make the executed bytes no longer the model's, contradicting ruling 1.

**Embeddability (ruling 7) = M13 DESIGN INPUT, not an M14 retrofit.** Layer the mode so {bytes
admission + pre-scan · AST allowlist · projection · recomputation consistency} form a PORTABLE CORE
— dependency-light (target stdlib-only; no msgspec/litestar/archive imports), inlinable into one
pasted file — with {certificate · archive · replay · routes} as demo-side wrappers. Where "reuse
the shipped dataset evaluator" conflicts with core isolation, embeddability WINS (user word):
extract/adapt into the core rather than import the service stack.

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
Under the review-termination rule it is M9's ONE unadjudicated row — the verdict STANDS (accepted
rulings hold until new evidence reverses them, and the rule binds forward), and any M9 re-entry
seeds `.agent/review-m9.md` with that row alone rather than re-reviewing the milestone.

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
Two prep branches were CONSUMED at their unit's close, suites shipped in `main`, worktree + branch
removed: `wt/test-m12u1` (M12.1 → `tests/test_model_backend_runtime.py`) and `wt/test-m12u2`
(M12.2 → `tests/test_model_backend.py`). M12.2 ADDS one: `wt/rev-m12u2` `e224bfc`
(`tests/test_rev_m12u2_contract.py`, 15 checks — MAIN advanced the tip past `da7e47a` to bank four
checks the teammate's own commit never executed). **Trap: 10 of its 15 checks encode readings §8
OVERRIDES — `eos_token_id` forwarded to `generate`, the `tokenizer_unusable` label, a bad-PAD
refusal. Never credit or implement against them.** The 5 that pass are corroboration and were the
source of two shipped pins. M12.3a CONSUMED its two prep branches — `wt/test-m12u3` (red-suite seed
`827784a` → `tests/test_m12u3_guidance.py`) and `wt/rev-m12u3` (→
`tests/test_rev_m12u3_contract.py`) — suites shipped in `main`, worktree + branch removed:
**17 branches, 0 worktrees live.**
`wt/orc-m9u7a` is GONE from every reachable ref (`p3` must rebuild, not recover). Cite a branch TIP,
never a pre-amend SHA: the review close found `70af87f` cited for M9R1 while the live tip `db833f3`
carried 24 further lines in `test_review_m9_eval_contract.py`. Audit this list at every milestone
close — it drifted by two entries before M9.13b.
**M10 + M11 design seeds** — the source-confirmed OWUI sandbox mechanism (trusted outlet filter → signature check → direct `execute:python` RPC → Pyodide → inline PNG), its settings/gating constraints, the `enforcement_filter.py` rework, the 3-unit split, and M11's `Derive` transform design + its open questions → `.agent/reference.md` "Future-milestone design seeds". Read it at that milestone's PLANNING turn.
