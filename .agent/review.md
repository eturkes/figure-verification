# Review ledger — IMPLEMENT close

Adversarial pass over the phase diff. Rows are adjudicated against a check set fixed BEFORE the
diff is read; an accepted ruling holds until new evidence reverses it, and a fix earns one
re-review round against its acceptance check alone. Findings outside an artifact's acceptance
contract report as register entries, never as blockers.

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
| R3 | M13.0 | L-GAP | The slim baseline drops `is_secret`, so the committed artifact no longer carries the human ruling that the 106 findings are benign. | closed | The audit and its evidence live in `.agent/contracts/m13u0.md` § Probe seed and in `ops.md`, which are the surfaces a session actually reads. |
| R4 | M13.0 | L-CORR | CI has never executed: the workflow is verified locally (zizmor, actionlint-equivalent pins, YAML-parsed predicates) but no run has proven the gate green on `ubuntu-latest`. | open | First push produces a green `gate` run, or the divergence is fixed and recorded here. |
