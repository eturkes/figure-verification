# Deferral queue

One entry + acceptance check each. The spine — the unfinished units, and any blocker inside one — lives in `.agent/spec.md` `Tasks`, whose last line points here; a row here is off-spine until a unit adopts it.

- Q63 Bare-tier records (template refresh; `CLAUDE.md` `Engineering` firing records + `Session flow` rules upkeep): `.claude/rules/ops.md` (every context's bare tier) still carries run results + per-check firing records, e.g. the gate-probe result `52/52 FIRED, rc=0, ~55 s`, the `spec`-stage firing, the R1 positive-control recipe + per-probe detail; firing records belong in a `paths:` rule on the check's files, results in commit bodies. Accept: ops.md keeps gate invocations + law alone; the firing records sit in a `paths:` rule keyed on `tools/gate-probe.sh`, `tests/test_gate.py`, `tests/test_spec.py`, `.agent/spec-lint` + `.agent/measurements/**`; full gate green, S4 + symbol citations included.

- Q64 Ledger header repeats itself: `.agent/review.md` states the FULL-verdict-table sentence twice (top paragraph + the M13.6 paragraph). Accept: `/usr/bin/rg -c 'FULL verdict table lands with its archived' .agent/review.md` = 1, the M13.6 pointer kept.
