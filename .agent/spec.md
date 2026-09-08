# figure-verification spec

## Intent

A local Open WebUI instance where a weak local model writes the Python that draws a chart and a separate trusted verifier decides whether that chart may appear. The model proposes only code — never plotted values. The verifier admits the code against a closed allowlist, recomputes every plotted number from the source CSV, blocks whatever it cannot verify, and releases only verified figures with provenance. Demo: on the host of record, simple CSV charts (bar/line/scatter over columns) verify and render inline through Open WebUI's native Pyodide sandbox; complex requests (dashboards, multi-panel, styling beyond the subset) fail, output is blocked, and the user reads `Figure verification failed, no image produced`. Acceptance: ≥70% of simple prompts verify AND ≥70% of complicated prompts fail, per category on the committed held-out corpus; both public sentinel prompts pass outright. The model attempts arbitrary Python; the verifier alone decides — no grammar, prompt or hard-coded branch may move the pass/fail boundary out of it. Production artifact: Python code + prompts an admin pastes into an existing Open WebUI instance's tools/skills — one file, verifier embedded, zero network calls, no dependency beyond stdlib + what the Open WebUI image and its Pyodide bundle already carry (matplotlib, pandas, numpy); the target instance is a network-less Docker image, so nothing may require a rebuild. The repo's own stack (verifier service, model backend, launcher) is the demo harness, not the deliverable. Demo-grade: correctness testing yes; crypto sealing, escrow, tamper-evidence ceremonies no. The claim stays modest: verified = code, recomputed table, emitted artifact and certificate mutually consistent with every check passed; renderer, browser, Pyodide sandbox and pixels are trusted, not verified.

## Artifacts

Env + gate = `.claude/rules/ops.md`; commands run as `uv run --locked python -m …`. Shipped = JSON-spec dataset + headless formula modes; python mode = the spine.
- Gate — `bash tools/gate.sh` (ONE command, 8 stages: format · lint · types · tests · audit · secrets · workflows · shell). CI = `.github/workflows/gate.yml` runs the same script; updates = `.github/dependabot.yml`.
- Demo instance — `webui/launch.sh` (real dGPU model) | `--stub` (hardware-free) → `http://127.0.0.1:8080`; sentinel prompts pinned there.
- Verifier service — `-m verifier.service` (:8000; `audit <attempt_id>`); routes = `POC_SCOPE.md`.
- Demos — `-m demo` · `-m demo.formula_walkthrough` · `-m demo.e2e`. Bench — `-m bench` (JSON-spec proposer eval; live :8000 + :8001).
- Corpus + capture — `-m capture.corpus` · `-m capture stats corpus/python/captures/m12-design` · `-m capture run --run <name>`.
- Model backend — `.venv-model/bin/python -m model_backend` (:8001); `-m model_backend.guidance_oracle` on the host.

## Decisions

- Trust spine, every mode: the model supplies a program or spec, never data; the verifier recomputes all plotted values from the source CSV; renderer, Vega, Pyodide, browser + pixels = trusted, never verified. Boundary = `POC_SCOPE.md`; meaning = `VPlot_SEMANTICS.md`; claim-scope law = `.claude/rules/claims.md`.
- Python mode (`pysrc-0.1`), seven rulings: (1) the model authors the EXECUTED bytes — verifier-(re)authored scripts REJECTED; (2) simple arm = CSV bar/line/scatter; formula mode stays shipped, off the demo; (3) acceptance = ≥70%/≥70% per category over `corpus/python/heldout/`, sentinels scored alone; (4) pass ⇒ inline PNG + `Figure verification passed`; fail ⇒ blocked + `Figure verification failed, no image produced`; (5) a grammar may constrain FORMAT, never ADMISSION — de-fence + raise `max_tokens`; two-branch + subset-only CFGs REJECTED (measured; archived roadmap § Active track); (6) prompts carry task + format + dataset binding only, admission vocabulary banned everywhere (C6 enforces); levers = model, `max_tokens`, temperature, task phrasing, positive style examples; (7) demo-grade — sealing/escrow/tamper ceremonies REJECTED.
- Demo shape: the launcher's OWUI runs the production paste-in itself, python mode the only exposed tool; dataset JSON + formula modes stay headless service features. Single-source: the verification core is written once, stdlib-only; the paste-in inlines it by generation (hand fork banned); the :8000 service wraps the same core. No OWUI `requirements:`.
- **Demo re-scope (user; SUPERSEDES ruling 2).** Demo prompts plot MATH FUNCTIONS and import no data; the complicated arm asks for math the verifier can catch being WRONG. Retires the unbound-`pd` calibration problem, invalidates `corpus/python/` + the `m12-design` capture, retargets the projection at the FORMULA plot spec. `Intent` still describes the CSV demo and needs the user's own edit. Full law incl. the four comparison surfaces, the two OPEN forks (declared target · observed-execution confirmation) and the core/wrapper layering = `.claude/rules/pysrc.md`.
- M10 mechanism: trusted outlet filter → authentic verifier result → direct `execute:python` RPC → Pyodide → inline PNG; else block (`.claude/rules/owui.md`). JSON mode sat at 0/3 on the simple sentinel ⇒ the PASS arm is the calibration risk.
- Proposer: fp16 `Qwen2.5-Coder-0.5B-Instruct` on the MX150 = the sole GO; every proposer number = one `(device, config)` observation (`.claude/rules/host-runtime.md`). "The grammar enforces the guidance schema" is FALSE on every surface; strict re-decode = the sole admission authority.
- Stack: `uv` + py 3.13 cap · msgspec · Decimal-exact evaluator · DuckDB dev oracle · Litestar · ruff + `mypy --strict` + pytest + Hypothesis · torch/transformers/xgrammar. Per unit: tier + contract before code (`.agent/contracts/<unit>.md`, archived at close); ledger `.agent/review.md`.

## Deferred

`p<n>` rows = the archived polish register under `.agent/archive/` (full text + evidence).
- M12.8 guided-JSON bench re-baseline. Accept: tracked `bench/baselines/m12-cuda/` + `by_category` pin + ignore test.
- M12.9 prose sweep. Accept: ORIGIN recipes labeled historical; STE on the READMEs; identity search clean.
- M11 `derive` transform (computed columns via the shared expr engine; seed `archive/reference.md`). Accept: `Derive` in the Transform union; replay reparses.
- M9R1 formula typed-API closure. Accept: `archive/m9-rev-1` `db833f3` 39 reds green.
- M9R2 replay canonical-table proof (p18). Accept: one public `canon` table deserializer, used by archive + both replay engines.
- M9R3 + the unmeasured M9 obsolescence lens. Accept: `.agent/review.md` rows adjudicated.
- Polish register p3–p47, eight themes, per-row text + evidence + acceptance in `archive/polish.md`: attestation/replay hardening · mutation + differential gates from committed state · retained suites + reviews merged (tags deleted at close) · routes/OpenAPI (`additionalProperties:false` + `oneOf`) · test depth (p46 = committed grep over the forbidden guidance claim) · docs register (committed STE check) · bench + prompts (per-category run on the CUDA tuple) · tooling + webui. Accept: per row.
- pysrc CSV arm: `read_csv` projection to the dataset spec (cut by the demo re-scope; the JSON dataset mode still ships). Accept: a simple-CSV category ≥70% on a fresh held-out run.
- CodeQL in CI (repo visibility unknown; free only when public). Accept: `.github/workflows/codeql.yml` green, or a recorded ruling that GHAS is unavailable.

## Phase

IMPLEMENT. Spine: M13 python-source verification (math-function arm) → M10 OWUI integration + calibrated demo → M14 paste-in artifact. M13.0 CLOSED (one gate command + supply-chain scanning + CI). Next = M13.1: the stdlib-only `verifier.pysrc` core — byte cap + nesting pre-scan ahead of `ast.parse`, AST allowlist by idiom class.
