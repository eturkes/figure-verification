# polish register — deferred perfection (off-spine)

Producers = every session, writing the row at deferral time while the evidence is fresh. Consumer = `/session-polish` alone; selection, staleness + close rules live there. Empty register = nothing deferred.

Row (one line each, hottest `pri` first):

`- [<id>] pri=<1-3> size=<S|M|L> scope=<commit-scope> | <what> | why: <evidence — file:line | SHA | run output> | acc: <runnable check that decides done> | <open | stale(<why>) | spine? <finding>>`

`id` = `p<n>`, monotonic, never reused · `pri` 1 = correctness-adjacent, 2 = clarity/perf/ergonomics, 3 = cosmetic · `size` S ≤15% window, M ≤35%, L = session · `scope` = the scope its commit lands under (`<scope> (polish): …`).

## Items

(none)
