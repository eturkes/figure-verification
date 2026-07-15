---
name: session-prompt
description: Continue figure-verification in a fresh Codex session through its roadmap-driven planning, work-unit, or milestone-review workflow. Trigger on explicit $session-prompt invocation; accompanying text is the task override.
---

# Session prompt

1. Read the repo-root `.codex/prompts/session.md` completely.
2. Replace `$ARGUMENTS` with the text accompanying the explicit `$session-prompt` invocation,
   excluding the skill mention itself; use an empty value when no text accompanies it.
3. Follow the expanded prompt under the active `AGENTS.md` instructions.
4. Treat this skill + `.codex/prompts/session.md` as one interface; update both together whenever
   their contract changes.
