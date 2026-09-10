# Review ledger — IMPLEMENT close

Adversarial pass over the phase diff, run under `CLAUDE.md` `Engineering` review law: the check
set is fixed BEFORE the diff is read, every row is adjudicated, and the table is the deliverable.
Bindings this ledger adds: a `finding` cell recorded from here on carries its evidence at the
global `Subagents` bar -- a red test for behavior, or the disputed bytes as a greppable anchor
plus `file:line` for an artifact's text; an absence claim carries its command, rc and positive
control.

Status vocabulary: `open` · `accepted` (fix required, named) · `rejected` (with reason) ·
`register` (outside contract, recorded not fixed) · `closed` (fix landed + re-reviewed).

## Lenses

| id | lens | what it asks |
|---|---|---|
| L-CORR | correctness / spec | does the code do what its contract's predicates say, on the inputs the contract admits? |
| L-CLAIM | claim soundness | is every sentence the project ships true at the strength it is stated? |
| L-GAP | guarantee vs. claim | does a shipped guarantee outrun the mechanism that backs it? |
| L-LAW | `CLAUDE.md` conformance | tiers, contracts, gate identity, claim discipline, authoring register |

## Rows

| id | unit | lens | finding | status | acceptance check |
|---|---|---|---|---|---|
| R1 | M13.0 | L-GAP | `uv audit` reads only the committed lock, so a clean `audit` stage says nothing about `.venv-model` (the py3.12 CUDA runtime with its own lock, never resolved by the gate venv). | closed | Dependabot covers `/model_backend/runtime` (`tests/test_gate.py::test_g7_...`); the gate's own scope limit is stated in `.claude/rules/ops.md`. |
| R2 | M13.0 | L-CLAIM | The `secrets` stage proves "no NEW secret material in tracked files", not "no secrets". `.verifier-state/signing.key` is real and deliberately unscanned because it is gitignored. | closed | `ops.md` states the tracked-files scope; `tools/gate.sh` comments the exclusion reason at the call site. |
| R3 | M13.0 | L-GAP | The slim baseline drops `is_secret`, so the committed artifact no longer carries the human ruling that the 106 findings are benign. | closed | The audit and its evidence live in `.agent/archive/contracts/m13u0.md` § Probe seed and in `ops.md`, which are the surfaces a session actually reads. |
| R5 | phase | L-CLAIM | The two human-facing scope documents state the project as JSON-spec-only with a VERIFIER-authored script, which python mode's ruling 1 reverses. `README.md:5` `A caller submits a restricted JSON plot specification.` and `README.md:12` `The verifier writes that script and never runs it.`; `POC_SCOPE.md:278` `# (the verifier authors that script and never runs it)`, `POC_SCOPE.md:324` `verifier authors the certified matplotlib script and never executes it`. Under `pysrc-0.1` the MODEL authors the EXECUTED bytes and Pyodide runs them. Both files are correct for the shipped JSON modes and wrong as a statement of what the project now is. | open | Rewrite at phase close, once M13.5/M10/M14 have fixed what python mode actually claims — rewriting now would rewrite twice. Accept: `README.md` in human-facing ASD-STE100 register covering install/run/configure, no sentence contradicting `.claude/rules/pysrc.md`, and `POC_SCOPE.md`'s two script-authorship sentences scoped explicitly to the JSON modes. |
| R4 | M13.0 | L-CORR | CI has never executed: the workflow is verified locally (zizmor, actionlint-equivalent pins, YAML-parsed predicates) but no run has proven the gate green on `ubuntu-latest`. | open | CONFIRMED, and the row paid for itself. Hosted run 13 on `c0940c3` FAILED where the same commit gates green locally and in a clean clone: `tests rc=1`, 4 failures, other 7 stages rc=0. TWO `ubuntu-latest` divergences, both real defects, both fixed here. (1) `actions/checkout` defaults to depth 1, so `git show e432bd9:…` and `git worktree add --detach … e432bd9` exit 128 and 3 baseline tests die — fixed by `fetch-depth: 0`, pinned by `test_g6_checkout_fetches_full_history` + probe `g6-fetch-depth`, because the tempting repair is to skip those tests where the object is absent and that is a silent green. (2) `capture/record.py` resolved `nvidia-smi`/`git` with `shutil.which` BEFORE consulting the injected runner, so `collect_host_provenance(runner=valid)` returned `None` on a GPU-less runner — the injected seam was not authoritative and `test_i7_subprocess_seam` passed here only because this host owns an MX150. Fixed by `_tool_path`, which consults the host only when no runner is injected; `_git_facts` carried the identical latent defect and moved in the same commit. Closes on the next hosted `gate` run reading green. |
