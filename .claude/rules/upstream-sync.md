---
paths:
  - "CLAUDE.md"
---

# Upstream sync — `CLAUDE.md` template refresh

`CLAUDE.md` = a verbatim copy of `~/Projects/agents/claude/CLAUDE.project.md`; a refresh overwrites it whole, so project law never lives there. Invariants a refresh must keep, else restore:
- Line 1 = `@.agent/spec.md` import (silent when missing — `claude -p` answering a spec-only question with zero tools = the check).
- `Session flow` names `.agent/spec.md` (five sections, liveness rule, NO size budget) + `.agent/review.md`; `Engineering` routes deferrals to `.agent/deferred.md` rows. `tests/test_spec.py` S1-S5 enforces the structure a refresh must leave intact.
- The `.claude/rules/` two-tier bullet (bare | `paths:`) present — the sole carrier of project law + teammate inheritance.
- No `## Claude Code` section; no retired-flow references (session commands, attached roadmap/polish/memory ledgers, Serena, `read-guard`).
Post-refresh: `git diff HEAD -- CLAUDE.md` → any repo-measured law in the removed lines folds into the owning `.claude/rules/` file; a refresh that RETIRES a mechanism sweeps every repo reference in the same commit.
