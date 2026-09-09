# figure-verification spec

## Intent

A local Open WebUI instance where a weak local model writes the Python that draws a chart and a separate trusted verifier decides whether that chart may appear. The model proposes only code — never plotted values. The verifier admits the code against a closed allowlist, recomputes every plotted number from the source CSV, blocks whatever it cannot verify, and releases only verified figures with provenance. Demo: on the host of record, simple CSV charts (bar/line/scatter over columns) verify and render inline through Open WebUI's native Pyodide sandbox; complex requests (dashboards, multi-panel, styling beyond the subset) fail, output is blocked, and the user reads `Figure verification failed, no image produced`. Acceptance: ≥70% of simple prompts verify AND ≥70% of complicated prompts fail, per category on the committed held-out corpus; both public sentinel prompts pass outright. The model attempts arbitrary Python; the verifier alone decides — no grammar, prompt or hard-coded branch may move the pass/fail boundary out of it. Production artifact: Python code + prompts an admin pastes into an existing Open WebUI instance's tools/skills — one file, verifier embedded, zero network calls, no dependency beyond stdlib + what the Open WebUI image and its Pyodide bundle already carry (matplotlib, pandas, numpy); the target instance is a network-less Docker image, so nothing may require a rebuild. The repo's own stack (verifier service, model backend, launcher) is the demo harness, not the deliverable. Demo-grade: correctness testing yes; crypto sealing, escrow, tamper-evidence ceremonies no. The claim stays modest: verified = code, recomputed table, emitted artifact and certificate mutually consistent with every check passed; renderer, browser, Pyodide sandbox and pixels are trusted, not verified.

## Artifacts

Env + gate = `.claude/rules/ops.md`; commands run as `uv run --locked python -m …`. Shipped = JSON-spec dataset + headless formula modes; python mode = the spine.
- Gate — `bash tools/gate.sh` (ONE command, 8 stages: format · lint · types · tests · audit · secrets · workflows · shell); positive controls = `bash tools/gate-probe.sh`. CI = `.github/workflows/gate.yml` runs the same script; updates = `.github/dependabot.yml`.
- Mutation credit — `uv run --locked python tools/mutate.py tools/mutants/project.toml` (committed driver + per-module catalogue; baseline must be green, each mutant names the ONE test that must go red).
- Demo instance — `webui/launch.sh` (real dGPU model) | `--stub` (hardware-free) → `http://127.0.0.1:8080`; sentinel prompts pinned there.
- Verifier service — `-m verifier.service` (:8000; `audit <attempt_id>`); routes = `POC_SCOPE.md`.
- Demos — `-m demo` · `-m demo.formula_walkthrough` · `-m demo.e2e`. Bench — `-m bench` (JSON-spec proposer eval; live :8000 + :8001).
- Corpus + capture — `-m capture.corpus` · `-m capture stats corpus/python/captures/m12-design` · `-m capture run --run <name>`.
- Model backend — `.venv-model/bin/python -m model_backend` (:8001); `-m model_backend.guidance_oracle` on the host.

## Decisions

- Trust spine, every mode: the model supplies a program or spec, never data; the verifier recomputes all plotted values from the source CSV; renderer, Vega, Pyodide, browser + pixels = trusted, never verified. Boundary = `POC_SCOPE.md`; meaning = `VPlot_SEMANTICS.md`; claim-scope law = `.claude/rules/claims.md`.
- Python mode (`pysrc-0.1`), seven rulings: (1) the model authors the EXECUTED bytes — verifier-(re)authored scripts REJECTED; (2) BOTH arms ship — dataset arm (`read_csv` over the user's uploaded file) = the clinical spine, formula arm (`f(x)` over a stated interval) = the high-resolution case where the request sentence IS the specification; (3) acceptance = ≥70%/≥70% per category over `corpus/python/heldout/`, sentinels scored alone; (4) pass ⇒ inline PNG + `Figure verification passed`; fail ⇒ blocked + `Figure verification failed, no image produced`; (5) a grammar may constrain FORMAT, never ADMISSION — de-fence + raise `max_tokens`; two-branch + subset-only CFGs REJECTED (measured; archived roadmap § Active track); (6) prompts carry task + format + dataset binding only, admission vocabulary banned everywhere (C6 enforces); levers = model, `max_tokens`, temperature, task phrasing, positive style examples; (7) demo-grade — sealing/escrow/tamper ceremonies REJECTED.
- Demo shape: the launcher's OWUI runs the production paste-in itself, python mode the only exposed tool; dataset JSON + formula modes stay headless service features. Single-source: the verification core is written once, stdlib-only; the paste-in inlines it by generation (hand fork banned); the :8000 service wraps the same core. No OWUI `requirements:`.
- **Verification model (user; supersedes the math-function-only re-scope, which superseded ruling 2's CSV reading — archived contracts on either reading are historical).** Three tiers: **provenance** (every plotted number recomputed from the user's artifact, no intent needed) · **integrity** (closed per-mark G-rule set — truncated baselines, dual axes, silent row drops; no intent needed) · **interpretation** (the certificate publishes what was verified in plain words). Fidelity to INTENT is never claimed; tier 3 publishes that gap. Coverage grows one mark at a time at NO new trust. Truth source = the user's own artifact, resolving fork (a). Deployment = Japan/clinical, production proposer Kimi, demo proposer unchanged ⇒ the design may not depend on proposer strength. Full law incl. the G-rules, the four comparison surfaces, the still-OPEN fork (b) and the core/wrapper layering = `.claude/rules/pysrc.md`.
- M10 mechanism: trusted outlet filter → authentic verifier result → direct `execute:python` RPC → Pyodide → inline PNG; else block (`.claude/rules/owui.md`). JSON mode sat at 0/3 on the simple sentinel ⇒ the PASS arm is the calibration risk.
- Proposer: fp16 `Qwen2.5-Coder-0.5B-Instruct` on the MX150 = the sole GO; every proposer number = one `(device, config)` observation (`.claude/rules/host-runtime.md`). "The grammar enforces the guidance schema" is FALSE on every surface; strict re-decode = the sole admission authority.
- Stack: `uv` + py 3.13 cap · msgspec · Decimal-exact evaluator · DuckDB dev oracle · Litestar · ruff + `mypy --strict` + pytest + Hypothesis · torch/transformers/xgrammar. Per unit: tier + contract before code (`.agent/contracts/<unit>.md`, archived at close); ledger `.agent/review.md`.

## Deferred

Queue = `.agent/deferred.md`, 12 rows, one line + acceptance check each; nothing there blocks the units below.

Spine = the unfinished units, in order: M13.3 close → M13.4 → M10 → M14.

**M13.3** — python-source projection + integrity. OPEN, gate-green, one merge short of close; contract + verdicts = `.agent/contracts/m13u3.md`.

- SHIPPED. `spec.py` + `project.py` = the formula-arm projection, 13 refusal codes, structural grid identity, integer-only `arange`. `tests/test_pysrc_project.py` (P1-P12 + P13 reachability) + `tests/test_pysrc_integrity.py` (G1/G2/G3/G6) merged from `wt/m13u3-test` with three MAIN rulings applied. Gate rc=0 on all 8 stages, `verifier` at 100% branch, probes 21/21, `tools/mutants/project.toml` at 23/23 killed.
- RESUME. One harvest remains: `wt/m13u3-orc` @ `edaa682` — an independent oracle + Hypothesis differential (`tests/oracle_project.py`, `tests/test_pysrc_project_differential.py`, 1244 lines), UNMERGED. Run from the PRIMARY tree, since its vacuity guard resolves both sides against the tree the files sit in. Last measured there: 25 failed / 77 passed, of which exactly ONE is a semantic disagreement (the oracle's `cap=10_000` against `max_grid_samples` = 100_000) and 24 are form noise in its `normalize` — node-class names, field names, field order, and the `kind`/`step` fields the Grid ruling removes. The fix (one explicit translation map onto a canonical tuple) was messaged but not applied before the teammate stopped, so a resumed session either applies it directly or re-dispatches an `orc` successor from that branch. Its corpora predate the integer-only `arange` ruling and the structural grid-identity ruling. Both worktrees are clean and still checked out under `.scratch/worktrees/`.
- CLOSE. Verdict table into the contract, archive it under `.agent/archive/contracts/`, then record the close in `Phase` and drop this unit from the spine.

**M13.4** — dataset arm: `read_csv` idioms → `DatasetPlot` → the `CorePlotSpec` union widens, breaking the one-member alias pin on purpose.

**M10** — OWUI integration + calibrated demo; mechanism + calibration risk = `.claude/rules/owui.md`.

**M14** — paste-in artifact; shape = `Intent` + the single-source ruling in `Decisions` (inlined by generation, hand fork banned).

## Phase

IMPLEMENT, milestone M13 — python-source verification (projection → integrity → verdict). M13.0 CLOSED (one gate command + supply-chain scanning + CI). M13.1 CLOSED (`verifier.pysrc` pre-scan: byte cap + nesting pre-scan ahead of `ast.parse`, stdlib-only, 9 closed refusal codes). M13.2 CLOSED (`admit.py` positive AST allowlist, 11 more refusal codes, 13/13 mutants killed).
