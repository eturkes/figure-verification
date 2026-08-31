# rev-m9-2 — evidence + checks + script emission + certificate

STATUS: DONE
FLUSHED: 5/5

## Unit verdicts

Fill one row per batch. verdict = CLEAN | FINDINGS. findings = comma-separated F-ids or `none`.

| unit | verdict | findings |
|---|---|---|
| M9.4a | CLEAN | none |
| M9.4b | FINDINGS | F1 |
| M9.5 | CLEAN | none |
| M9.6a | FINDINGS | F2 |
| M9.6b | CLEAN | none |

## Findings

One block per finding. Header: `### F<n> | sev=HIGH|MED|LOW | <unit> | <file>:<line>`.
Required bullets: `divergence:` `impact:` `acceptance-check:` `red-test:`.
Zero findings overall ⇒ write the literal token NO-FINDINGS on its own line here.

### F1 | sev=MED | M9.4b | src/verifier/formula_prepare.py:98
- divergence: `prepare_formula` correctly forwards the caller policy, but no shipped test pins `smt_timeout_ms` at this public seam. Replacing the caller policy with `DEFAULT_LIMITS` whenever its timeout differs left all 2900 shipped tests green.
- impact: a regression can silently relax the operator's solver deadline and extend worker occupancy while every existing row-limit, SMT-term, and direct-`formal.verify_formal` test still passes.
- acceptance-check: call `prepare_formula` with `smt_timeout_ms=17`, spy `formal.verify_formal`, assert the exact caller object and timeout arrive, then reapply the default-substitution mutant and require RED.
- red-test: tests/test_review_m9_4b_policy_threading.py

### F2 | sev=LOW | M9.6a | src/verifier/vcert.py:473
- divergence: the v0.2 relocation preserved wire behavior but dropped the old `vcert_bytes` and builder rationale: exact served/content-addressed bytes, passing-result order, every filter versus only the active sort, and later HTML escaping are no longer stated at their owning seams.
- impact: future agents must infer these constraints from distant tests and call sites; a v0.2 extension can treat ordering, disclosure, or served-byte identity as incidental because the owning code no longer explains why they bind.
- acceptance-check: restore concise owner-local rationale for canonical served bytes and dataset-builder ordering/disclosure rules, then mechanically diff the removed `render.py` rationale against its `vcert.py` replacement and leave no unmatched proposition.
- red-test: judgment-only

## Notes

- M9.4a CLEAN: commit-diff AST probe found exactly 18 registry additions, every ID already literal-emitted by parent `expr.py`/`eval.py`, zero removals; pre/post evidence field lists matched exactly. Closed-registry/evidence/dataset-report subset: 13 passed.
- M9.4b FINDINGS: formula/check/formal subset 55 passed; explicit per-call Z3 contexts + concurrent distinct-context pin present; exact Decimal `0.2` rank and nondecreasing-vs-strict split pinned. Timeout-drop mutant applied and proved, shipped suite 2900 passed, review pin failed 1/1, source SHA restored.
- M9.5 CLEAN: emitter/registry subset 86 passed. Fixed AST allowlist covers 41 script/data mutants; line/scatter lookup is exact + immutable + near-miss pinned. The 483-byte script passes at 483 and is built before the 482-byte refusal; hash/success work is bombed downstream. Float fidelity uses exact `Fraction.from_float`, declared scales, strict projected x, and endpoint equality. Fresh-import test excludes matplotlib, `vl_convert`, and `render`.
- M9.6a FINDINGS: VCert/live-TCB subset 50 passed. Mixed pass/fail witness killed `any→all` before hashing; source SHA restored. Parent-versus-relocated real dataset payloads compared byte-identical: 1719 B, SHA-256 `4d9fab9954f05f35fb3e9313b67952fecf10857c33345f243544422656befb31`. Fixed/live TCB form-vs-wiring split, nine-field exact set, four rehash guards, full 2-valid/6-invalid family matrix, leaf import boundary, and replay live-TCB no-kwargs pin are present. A stale service TCB mutant was killed by shipped archive/replay checks.
- M9.6b CLEAN: DSSE/v0.3 wrapper suites 104 passed. All four sign/verify operations spy their own fixed MIME despite equal 51-byte lengths; ceilings equal 1,399,079 at the default. Signature + type precede application decode, and the decoder receives the same verified payload object. Stricter caller limits, canonical-envelope policy, keyid relation, tamper families, correctly re-signed changed claims, exact two-wrapper export closure, and v0.2 payload/envelope bytes are pinned.
- Exact worktree gate: ruff format PASS; ruff check PASS; mypy PASS; pytest 2901 passed with 100.00% branch coverage. Eight pre-existing `ResourceWarning` instances reported unclosed SQLite connections.
