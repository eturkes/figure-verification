Continue this project in a fresh Codex session. A non-empty task below is the sole task; edit
`.agent/roadmap.md` only when the task or roadmap requires it. With an empty task, run the MODE for
the roadmap's first active milestone yet to reach DONE/REVIEWED.

Load `.agent/roadmap.md` (ledger + active-milestone detail), then the implicated parts of
`.agent/memory.md` (lessons + decisions). `AGENTS.md` is already in force. Start from tracked
source/config/docs + `git status`; expand the read set only as the task requires.

MODE ← active-milestone status; each mode advances it and closes with one scoped commit:
- UNPLANNED, including an unsplit future milestone → PLANNING
- IN-PROGRESS with an OPEN unit → WORK-UNIT (lowest OPEN unit)
- IMPLEMENTED with all units DONE → MILESTONE-REVIEW

PLANNING — split the scope if needed, then plan only the next milestone.
- Read the prior milestone's commit range, especially recorded unit sizes; for the first milestone,
  use the roadmap-named scope-seed commits.
- Resolve gates functionally through project tooling. An unmet gate → record the standing block and
  stop. Bring generated/heavy inputs into scope only when the gate needs them.
- Use a dynamic plan + web research. Reconcile findings against `git status`. Target self-contained
  ~200K-token units per the roadmap's sizing evidence; sequence gate-free preparation first; mark
  still-gated units BLOCKED.
- Close: set the milestone IN-PROGRESS with enumerated units; commit
  `roadmap (M<m> plan): …`.

WORK-UNIT.
- Read the last completed unit's commits, or the planning commits for the first unit.
- Restate the unit + acceptance in one line. Before edits, size it against memory's rules and the
  read-cost of exact-shape gates. A projection well beyond the ~200K aim → split at a confirmed seam
  into fresh self-contained units; retain decisions, confirmed facts, and precise reading pointers;
  remove session-only WIP; commit `roadmap (M<m>.<u> respec): …`. Continue into the first replacement
  only when it can close cleanly in the current session.
- Implement by reusing project modules and matching local style. Resolve unit gates functionally so
  each result traces to real inputs. Run the roadmap-defined quality gate; touched scripts must exit
  cleanly. Record only durable lessons/decisions in `.agent/memory.md`.
- Close: set the unit DONE and, when every unit is DONE, the milestone IMPLEMENTED. Record context
  usage only when Codex exposes an exact value; omit estimates. Commit `<scope> (M<m>.<u>): …`.
  A respec-only session closes at its respec commit with replacement units OPEN.

MILESTONE-REVIEW.
- Read every milestone commit, including planning commits. Adversarially review the whole body for
  correctness, logic, claim strength, cross-unit consistency, scope/AGENTS/memory conformance,
  token-efficiency, and obsolescence; fix every accepted finding. Ask before changing requirements.
- Close: set the milestone REVIEWED; commit `<scope> (M<m> review): …`. The next session plans the
  next milestone.

Commit convention: scoped `<scope>: …`; trace key `(M<m>.<u>)`, `(M<m> plan)`, or
`(M<m> review)`. A separately requested Codex review follow-up keeps the key and adds
`Codex-Review: <accepted findings>`. History query: `git log --grep "(M<m>[. ]"`.

Task (may be empty): $ARGUMENTS
