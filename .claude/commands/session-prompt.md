Continue project. First load `.agent/roadmap.md` + `.agent/memory.md`; either missing ⇒ create a minimal stub (roadmap: goal + first UNPLANNED milestone from available context; memory: empty) before proceeding. Task present ⇒ execute exactly it; update other files as needed for consistency. Task empty ⇒ run MODE for the active milestone (first awaiting DONE/REVIEWED).

MODE ← active-milestone status (state-changing closes use a scoped commit; an unchanged BLOCKED recheck closes read-only; convention below):
- UNPLANNED (incl. a still-unsplit future milestone) → PLANNING
- IN-PROGRESS (has an OPEN unit) → WORK-UNIT (lowest OPEN unit)
- IN-PROGRESS (OPEN=0; BLOCKED>0) → WORK-UNIT (lowest BLOCKED, gate recheck)
- IMPLEMENTED (all units DONE; review pending) → MILESTONE-REVIEW

Execution map:
- Every MODE fans work out to named teammates (this command = standing opt-in), each spawned with a role name `<role>-m<m>[u<u>][-<k>]`, task + constraints, a unique completion marker ending its final message (fresh `-<k>` suffix per iteration), and a report destination — findings/evidence → `.scratch/agents/<name>.md`, code → working tree. Batch independent spawns in one block so they run in parallel. A supplied task uses the same fan-out when MAIN judges it beneficial or the user requests it.
- MAIN owns the one-line scope + acceptance restatement, precondition confirmation, per-teammate task definitions, and close; MAIN alone creates repository commits. MAIN verifies independently: inspects every returned diff, reruns the decisive gates, and accepts evidence that traces permitted real inputs.
- Implementation teammates land the accepted scope as working-tree changes: reuse project modules/style, run the required lint/format/type-check/tests, confirm touched scripts exit cleanly, route durable guidance, and report diff + evidence. Parallel implementation teammates only on disjoint file sets.
- Review + research teammates stay analysis-only; findings land in their report files.
- Teammate hygiene: scope each to finish inside ~200K; research teammates get a bounded question set + an explicit WebSearch allowance (session budget = 200, shared) + BrowserOS MCP for authenticated/paywalled sources. Completion/death = pull-only ⇒ poll each transcript for its marker (anchored `rg '"text":"<MARKER>'`); stalled/markerless ⇒ read the transcript tail, revive via `SendMessage`. Harvest every report + `TaskStop` every teammate before close.
- Context: PLANNING + MILESTONE-REVIEW run past auto-compaction — MAIN checkpoints coherently before each and continues after. Every other run completes within one window, and WORK-UNIT records its usage at close.

PLANNING — split scope into milestones as needed; plan the next milestone.
- Read the prior milestone's commit range and recorded `impl=` context; for the first planned milestone, read the scope-seed commit(s) named by the roadmap. Size future units from implementation usage; treat `main=` as coordination overhead.
- MAIN confirms each milestone precondition through project pipeline/tooling. Met ⇒ clear stale standing block + continue. Unmet ⇒ record standing block + evidence; changed record ⇒ commit `roadmap (M<m> block): …`; unchanged record ⇒ read-only close.
- Fan out parallel research teammates over the open questions, one bounded question set each; MAIN discovers code via Serena (`get_symbols_overview` → `find_symbol` → `find_referencing_symbols`), then reconciles `git status`.
- Break the milestone into units that each project to fit one implementing teammate inside the one-window aim; planning holds sole sizing authority, so every unit ships as scoped. Sequence gate-independent prep first; mark a gated unit BLOCKED until its precondition is met.
- Close: set the milestone IN-PROGRESS (units enumerated), commit `roadmap (M<m> plan): …`.

WORK-UNIT.
- Read the last completed unit's commit(s), or the planning commit(s) for the milestone's first unit.
- Precondition transition: recheck BLOCKED first. Met ⇒ clear block, set OPEN, continue. Unmet ⇒ retain BLOCKED; materially changed evidence ⇒ update + commit `roadmap (M<m>.<u> block): …`; stable evidence ⇒ read-only close. OPEN + unmet ⇒ set BLOCKED, record condition/evidence, make block commit, close.
- Implement: teammate `impl-m<m>u<u>` carries the accepted scope, locations, constraints, quality gates + acceptance checks; marker `UNIT-DONE`.
- Review: fresh teammate `rev-m<m>u<u>` (impl context withheld for independence) scrutinizes the diff adversarially (correctness/spec, claim soundness, guarantee-vs-claim gaps) against scope + acceptance + project conventions; marker `REV-DONE-<k>`. MAIN validates findings, `SendMessage`s accepted fixes to `impl-m<m>u<u>` (retained unit context; fix passes end `FIXES-DONE-<k>`) and material changes back to `rev-m<m>u<u>` for re-review; MAIN reruns the decisive gates and `TaskStop`s both before close.
- Close: record `main=<.agent/context.sh full pct used/240K>` + `impl=<peak implementing teammate's transcript final pct used/240K>` in the roadmap. Set the unit DONE and, once all units are DONE, the milestone IMPLEMENTED; commit `<scope> (M<m>.<u>): …`.

MILESTONE-REVIEW.
- Read every commit within the milestone.
- Fan out parallel review teammates: one per unit (that unit's commits + touched surfaces; correctness/spec) + one cross-cutting (cross-unit integration; instruction/memory conformance; token-efficiency/obsolescence). Each finding supplies severity + `file:line` + divergence + impact + acceptance check.
- MAIN validates + deduplicates findings; accepted implementation findings become one fix teammate per cohesive batch, carrying locations + acceptance checks.
- A requirement-changing design reaches the user before any scope-source edit.
- Close: set the milestone REVIEWED, commit `<scope> (M<m> review): …`. The next session plans the next milestone.

Commit convention — scoped (`<scope>: …`), trace key in parens: unit `(M<m>.<u>)`, block `(M<m> block)` / `(M<m>.<u> block)`, plan `(M<m> plan)`, review `(M<m> review)`. Grep a milestone's history: `git log --grep "(M<m>[. ]"`.

Task: $ARGUMENTS
