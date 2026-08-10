# polish register — deferred perfection (off-spine)

Producers = every session, writing the row at deferral time while the evidence is fresh. Consumer = `/session-polish` alone; selection, staleness + close rules live there. Empty register = nothing deferred.

Row (one line each, hottest `pri` first):

`- [<id>] pri=<1-3> size=<S|M|L> scope=<commit-scope> | <what> | why: <evidence — file:line | SHA | run output> | acc: <runnable check that decides done> | <open | stale(<why>) | spine? <finding>>`

`id` = `p<n>`, monotonic, never reused · `pri` 1 = correctness-adjacent, 2 = clarity/perf/ergonomics, 3 = cosmetic · `size` S ≤15% window, M ≤35%, L = session · `scope` = the scope its commit lands under (`<scope> (polish): …`).

## Items

- [p1] pri=3 size=S scope=roadmap | M5 close text states the archive commits at `synchronous=FULL`; code forces + reads back `EXTRA` (`archive.py:1564`, `_EXTRA_SYNCHRONOUS = 3`) and `tests/test_service_archive.py:130` pins `3` | why: `.agent/roadmap.md` M5 section "journal_mode=DELETE + synchronous=FULL" vs `archive.py:1569`; drift found while mapping M9.7 | acc: `command grep -n 'synchronous' .agent/roadmap.md` names EXTRA, and no roadmap line claims FULL | open
