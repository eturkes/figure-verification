Continue project. First load `.agent/roadmap.md` + `.agent/memory.md`; either missing ⇒ create a minimal stub (roadmap: goal + first UNPLANNED milestone from available context; memory: empty) before proceeding. Task present ⇒ execute exactly it; update other files as needed for consistency. Task empty ⇒ run MODE for the active milestone (first awaiting DONE/REVIEWED).

MODE ← active-milestone status (state-changing closes use a scoped commit; an unchanged BLOCKED recheck closes read-only; convention below):
- UNPLANNED (incl. a still-unsplit future milestone) → PLANNING
- IN-PROGRESS (has an OPEN unit) → WORK-UNIT (lowest OPEN unit)
- IN-PROGRESS (OPEN=0; BLOCKED>0) → WORK-UNIT (lowest BLOCKED, gate recheck)
- IMPLEMENTED (all units DONE; review pending) → MILESTONE-REVIEW

Isolation — one `git worktree` per teammate; MAIN alone writes the primary tree.
- Per spawn: `git worktree add -b wt/<name> .scratch/worktrees/<name>` = 3.7 MB, ~20 ms. The brief carries that path as the teammate's whole world.
- Gate inside a worktree: `UV_PROJECT_ENVIRONMENT=<primary>/.venv` + `uv run --no-sync --locked …`, `COVERAGE_FILE=<wt>/.coverage`, `pytest -p no:cacheprovider` → every worktree runs the full gate concurrently off the shared venv.
- Teammates commit inside their own worktree before each mutation cycle: `git checkout` then restores the baseline, new files included.
- MAIN reads a teammate's work as `git diff --stat main..wt/<name>` then targeted files, selects, and `git merge --squash wt/<name>` → one scoped commit.
- Live-stack binders (ports 8000/8001/8080, NPU, `.verifier-state/`, `.webui-data/`) = one holder per wave, named in that brief; every other teammate uses a private state dir.

Execution map — GPT teammates produce; MAIN decides on small artifacts.
- MAIN spends its window on: the acceptance contract, divergence rulings, findings no check decides, decisive-gate reruns, commits, MAIN-retained files. Its reading stays targeted — agreement matrices, gate output, flagged surfaces, red tests.
- MAIN-retained files = `.agent/roadmap.md`, `.agent/memory.md`, `CLAUDE.md`, command/skill files. A teammate may draft a delta into `.scratch/agents/<name>.md`; MAIN reviews it and applies the durable edit.
- Acceptance contract (MAIN, before fan-out): testable predicates + invariant surfaces + gate identity + probe corpus. Every downstream artifact decides against it.
- Brief = role + scope + contract + worktree path + marker `<NAME>-DONE-<i>` + report destination (`.scratch/agents/<name>.md`) + `read-and-conform-to` set: gates (`pyproject.toml` ruff/mypy/pytest, the roadmap's `uv run --locked` quality gate), oracles (`tests/` + corpus, `bench`/`demo` entry points), scope sources (roadmap, memory, `POC_SCOPE.md`, `VPlot_SEMANTICS.md`) ⇒ a teammate judging one of these wrong reports it and MAIN rules. Batch independent spawns in one block; dependent spawns form waves. A supplied task runs MAIN-direct; teammates fan out on the user's request.
- Differential selection: N implementers (N=3 for kernel/certificate/spec-critical units, else N=2), identical brief, isolated, mutually independent. `diff-m<m>u<u>` then computes the agreement artifact — cross-suite N×N (each impl's tests against every impl's source), canonical-payload SHA-256 equality over the probe corpus, cross-mutation kill matrix, statement/branch/module counts. MAIN reads matrix + divergence list, rules each divergence, selects. Agreement targets review effort; the gate decides acceptance. Correlated divergence indicts the contract or the normative doc ⇒ MAIN's highest-value finding.
- Red-test review: a claimed defect ships as a failing test in the reviewer's worktree, red pre-fix and green post-fix ⇒ MAIN runs it and rules on evidence. Findings a test leaves unexpressed (design, claim soundness, guarantee-vs-claim gaps, CLAUDE.md conformance) ⇒ council rule: ≥2 independent declared lenses confirm ⇒ accept; a unique finding ⇒ MAIN validates by probe before dispatching a fix.
- Fixpoint: implementers + reviewers iterate ≤2 rounds inside their worktrees, gate green each round; the converged tree + any unresolved items reach MAIN.
- Speculation is cheap under abundant teammate capacity — fund it: the next unit's probe/corpus surface, extra spike alternatives, post-acceptance fuzz/property campaigns that escalate on a find, and a standing gate-strength track (property tests, differential oracles, mutation automation) whose every increment moves one MAIN judgment into the gate.
- CLAUDE.md conformance: each mode assigns one reviewer the project-CLAUDE.md lens — Authoring rules on every artifact the mode produced (durable files, briefs, `SendMessage`s, reports, roster, scratch notes, filenames) + Engineering practices on code.
- Roster at `.scratch/agents/roster.md` from first spawn (append via `tee -a … <<'EOF'`), one row per INSTANCE — name | worktree | transcript (`.agent/context-gauge.sh -p <name>`) | marker | watcher bg-task id | last gauge | status | report. Poll every teammate in one loop from it; retire a row's watcher in the same call that stops or supersedes its teammate.
- Hygiene follows the global `CLAUDE.md` `Subagents` protocol (scoping, marker polling, revive/death cadence, report-file confirmation, `TaskStop` at harvest). Project deltas: gauge = `.agent/context-gauge.sh <name>`; successor = `<role>-m<m>u<u>-<k+1>` carrying report + accepted findings; research teammates get a bounded question set, an explicit WebSearch allowance, and the `Authenticated web` route for authenticated sources. Worktree isolation confines the global contention rules to the primary tree, which MAIN alone writes.
- Verification: MAIN reruns the decisive gates on the merged primary tree and credits evidence tracing permitted real inputs. Re-derive a teammate artifact before crediting it — a `.scratch/agents/` PASS from a pre-repair copy certifies the OLD state. A checkpoint claim inherited across a compaction boundary counts as unvalidated ⇒ re-derive from source before acting on it.
- Context: per the project `CLAUDE.md` policy MAIN checkpoints (roster + state) before each compaction boundary and continues. WORK-UNIT closes each unit inside one window and records usage at close; after a full close it chains to the next OPEN unit while used + projected MAIN cost stay under the one-window aim.

PLANNING — split scope into milestones as needed; plan the next milestone.
- Read the prior milestone's commit range + recorded `impl=`; for the first planned milestone read the scope-seed commit(s) the roadmap names. Size future units from implementation usage; treat `main=` as coordination overhead.
- MAIN confirms each milestone precondition through project pipeline/tooling. Met ⇒ clear stale standing block + continue. Unmet ⇒ record standing block + evidence; changed record ⇒ commit `roadmap (M<m> block): …`; unchanged record ⇒ read-only close.
- Wave 1 (one block): `map-m<m>` = Serena/code surface map of the systems in scope; parallel `res-m<m>-<i>` research teammates, one bounded question set each. Wave 2: `plan-m<m>` drafts the unit split from map + research — each unit sized against the nearest completed analog's recorded `impl=` to fit one implementer inside the one-window aim, tagging kernel/certificate/spec-critical units `N=3`. Wave 3: `planrev-m<m>` attacks the draft (sizing realism vs recorded actuals, dependency order, gate coverage, missed scope, parallelizability, CLAUDE.md conformance). MAIN arbitrates + writes the roadmap; planning holds sole sizing authority, so every unit ships as scoped.
- Sequence gate-independent prep first; mark a gated unit BLOCKED until its precondition is met.
- Close: set the milestone IN-PROGRESS (units enumerated), commit `roadmap (M<m> plan): …`.

WORK-UNIT.
- Read the last completed unit's commit(s), or the planning commit(s) for the milestone's first unit.
- Precondition transition: recheck BLOCKED first. Met ⇒ clear block, set OPEN, continue. Unmet ⇒ retain BLOCKED; materially changed evidence ⇒ update + commit `roadmap (M<m>.<u> block): …`; stable evidence ⇒ read-only close. OPEN + unmet ⇒ set BLOCKED, record condition/evidence, make the block commit, close.
- Material design fork (constructor/naming/spec surface) ⇒ `spike-m<m>u<u>-<alt>` per alternative, each validated on real pipeline probes in its own worktree; MAIN picks; the decision record enters the contract.
- MAIN writes the acceptance contract, then spawns in one block: N × `impl-m<m>u<u>-<alt>`; diff-blind `rev-m<m>u<u>` (contract + normative docs alone → adversarial probe matrix + acceptance checklist, marker `<NAME>-PREP-<i>`; once impls land MAIN sends the design record ⇒ red-test review, marker `<NAME>-DONE-<i>`); `rev2-m<m>u<u>` on a complementary lens (conformance + claim audit | determinism + probing | mutation: mutate touched predicates, expect a committed red per mutant).
- `diff-m<m>u<u>` computes the agreement artifact once the impls converge. MAIN rules divergences, selects the winner, squash-merges it, reruns the decisive gates, and closes each accepted finding on its own acceptance check.
- Close: record `main=` (`.agent/context-gauge.sh`) + `impl=` (`.agent/context-gauge.sh <name>`, high-water, peak across implementers), both `N% NK/240K`, in the roadmap. `TaskStop` all, remove every worktree + `wt/` branch, set the unit DONE and — once all units are DONE — the milestone IMPLEMENTED; commit `<scope> (M<m>.<u>): …`; then apply the chain rule.

MILESTONE-REVIEW.
- Read every commit within the milestone.
- One block: per-unit reviewers (that unit's commits + touched surfaces; correctness/spec), one cross-cutting reviewer (cross-unit integration; project-CLAUDE.md conformance incl. instruction/memory token-efficiency + obsolescence), one `audit-m<m>` claim replayer (re-derives every roadmap/docs claim for the milestone: full gate suite, recorded numbers reproduced, unreproducible claims flagged). Each finding supplies severity + `file:line` + divergence + impact + acceptance check, shipping a red test wherever one expresses it.
- MAIN validates + dedupes (council rule); accepted findings become one fix teammate per cohesive batch (locations + acceptance checks) ⇒ MAIN's decisive-gate + acceptance-check rerun closes the batch; originating-reviewer re-review stays for a fix no check decides.
- A requirement-changing design reaches the user before any scope-source edit.
- Close: set the milestone REVIEWED, commit `<scope> (M<m> review): …`. The next session plans the next milestone.

Commit convention — scoped (`<scope>: …`), trace key in parens: unit `(M<m>.<u>)`, block `(M<m> block)` / `(M<m>.<u> block)`, plan `(M<m> plan)`, review `(M<m> review)`. Grep a milestone's history: `git log --grep "(M<m>[. ]"`.

Task: $ARGUMENTS
