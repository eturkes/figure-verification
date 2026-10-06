---
paths:
  - "VPlot_SEMANTICS.md"
---

# `VPlot_SEMANTICS.md` structure + citation pins

- **NOT human-facing.** It is an agent-consumed meaning contract that the evaluator, checks, renderer, script emitter and both dev/test oracles conform to ⇒ the `CLAUDE.md` dense/symbol-forward default governs it, NOT ASD-STE100. Do not "fix" its sentence lengths; Part A carries 26 sentences over 25 words by design and has passed two milestone reviews that way. The five shipped READMEs remain human-facing — the split above still binds them.
- **Structure.** One shared H1 + intro (the ONLY mode-neutral text) → `## Part A — dataset mode (vplot-0.1, vplot-0.2)` → `## Part B — formula mode (vplot-formula-0.1)`. 21 `###` sections: 12 dataset (`§1`–`§11` + `Settled decisions`), 9 formula (`§F1`–`§F9`). EVERY `###` heading contains its mode label, `— dataset mode` or `— formula mode`, so the invariant is one script away.
- **Section NUMBERS are load-bearing; heading TEXT is not.** No citation anywhere uses a `#anchor` fragment, so titles are free to reword. Numbers are cited from 5 external files — `examples/index.json`, `examples/README.md`, `tests/test_checks.py`, `tests/test_examples.py`, `tests/test_schema_properties.py` — pointing at Part A sections. Renumbering requires sweeping every `§<n>` in those files (`/usr/bin/rg -n '§[0-9]' <files>` decides the current count).
- **Two consumers cite number + PROSE TITLE** — `src/verifier/errors.py` and `src/verifier/ingest.py` ⇒ a Part A TITLE rename must sweep those two even though anchors are unused.
- **Single-authority rule.** Each ruling is stated exactly once at true scope; a second statement is a defect because the copies drift independently. Current pointers rather than copies: `§F7` → `§F4` for the 13-check success count, `§F9` → `§F4` for the normalization contract, `§F1` → `§F6` for the operational no-execution rule, `§F7` → `POC_SCOPE.md` for verdict/route/storage claims. This file's authority ENDS at script emission.
