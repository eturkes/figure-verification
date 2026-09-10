---
paths:
  - "CLAUDE.md"
---

# Upstream sync — `CLAUDE.md` template refresh

`CLAUDE.md` = a verbatim copy of `~/Projects/agents/claude/CLAUDE.project.md`, as `~/.claude/CLAUDE.md` is of `claude/cachyos/CLAUDE.opus.md` there; a refresh overwrites each whole, so project law never lives in either. Prove the copy with `cmp`, never by reading. Invariants a refresh must keep, else restore:
- Line 1 = `@.agent/spec.md` import (silent when missing — `claude -p` answering a spec-only question with zero tools = the check).
- `Session flow` names `.agent/spec.md` (five sections + the liveness rule) + `.agent/review.md`; `Engineering` routes deferrals to `.agent/deferred.md` rows. `tests/test_spec.py` S1-S8 holds the structure a refresh must leave intact, the `Deferred` = unfinished units / `Phase` = closed record split included — S8 additionally binds `Deferred` as a tracker surface a skip may cite.
- The `.claude/rules/` two-tier bullet (bare | `paths:`) present — the sole carrier of project law + teammate inheritance.
- No `## Claude Code` section; no retired-flow references (session commands, attached roadmap/polish/memory ledgers, Serena, `read-guard`).

Post-refresh sweep, landing in the refresh's own commit: `git diff HEAD -- CLAUDE.md` names the moved project lines, and the global file moves in the same upstream commits ⇒ diff it too (`git -C ~/Projects/agents diff <before> <after> -- claude/cachyos/CLAUDE.opus.md`). Repo-measured law in a removed line folds into the owning `.claude/rules/` file. A refresh that RETIRES or RELOCATES a mechanism sweeps every repo restatement in the same commit — relocation from the project file into global `CLAUDE.md` is the common shape (the dispatch shape→role map went that way), and a restatement left behind drifts against its owner unnoticed, so it becomes a citation. A changed SECTION CONTRACT (what `Deferred` holds) is a content migration inside `.agent/spec.md`, not a heading edit, and the sweep is the moment to give it a check.

Third refresh shape, beside RETIRE and RELOCATE: a REWEIGHT, which only re-reads a mechanism the repo already cites by pointer. It strands nothing by construction, so the sweep's whole job is proving that — one census over the live surface, `--hidden` named (`ops.md`), positive control attached. Report the empty census as the result; do not manufacture an edit to justify the pass. A refresh that strands nothing still earns the sweep, because the census is also the moment repo-side drift unrelated to the refresh surfaces, and that drift IS the commit.

Fourth shape: a TIGHTEN — an invariant the corpus never held, so nothing is stranded and the pointers all still resolve. Its sweep runs the OTHER way: census what the repo ALREADY DOES that the new invariant now judges, since a tighten lands retroactively on shipped work. Three moves, in order: (1) find the existing violations + fix or track them; (2) where the invariant is tool-decidable, give it a check — a prose-only tighten drifts exactly like the law it replaced, and the repo's own `Deterministic checks own every rule a tool can decide` binds here; (3) route the judgment remainder to `.agent/review.md` as a lens, never to an ad-hoc audit. A new gate check is itself a gate change ⇒ ASK before writing it, in the same turn the census lands.
