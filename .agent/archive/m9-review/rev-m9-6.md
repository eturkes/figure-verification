# rev-m9-6 — attached-state split + formula capstone demo + doc sweep

STATUS: DONE
FLUSHED: 6/6

## Unit verdicts

Fill one row per batch. verdict = CLEAN | FINDINGS. findings = comma-separated F-ids or `none`.

| unit | verdict | findings |
|---|---|---|
| M9.12c | FINDINGS | F1,F2,F3 |
| M9.13a | FINDINGS | F4,F5 |
| M9.13b | CLEAN | none |
| M9.13c | FINDINGS | F6 |
| M9.13d | CLEAN | none |
| M9.13e | FINDINGS | F7,F8,F9 |

## Findings

### F1 | sev=LOW | M9.12c | .agent/roadmap.md:111
- divergence: M9.11 R3/F09 says `p27` owns the `/table` + `/script` certificate-graph-authentication residual; the archived ruling names `p2`, while `p27` concerns the certificate-route envelope MIME.
- impact: A future repair follows an unrelated polish item and leaves the stated artifact-authentication residual unowned.
- acceptance-check: Change the residual pointer to `p2`; verify the archived M9.11 R3/F09 and live roadmap name the same item, while R9 alone points to `p27`.
- red-test: review_checks/check_m9_12c_residual_pointer.py

### F2 | sev=LOW | M9.12c | .agent/roadmap.md:144
- divergence: The roadmap cites `.scratch/archive_m9.py` as the archive byte-exactness credential, but the gitignored instrument cannot check the current committed archive: `dbebdc7 --check` validates its generated slice, then reports `on-disk archive matches source slice: False` and exits 1. `HEAD --check` cannot find the pre-prune start marker. Open polish `p35` already records the same reproducibility gap.
- impact: The durable verbatim-copy claim does not rerun from committed state; later hand-appended and unit-close sections sit outside the cited generator.
- acceptance-check: Port an idempotent generator/checker into tracked state; regenerate the complete current archive byte-identically, including Plan, pre-prune Memory, and later unit sections; run its check from a clean committed tree with rc=0.
- red-test: review_checks/check_m9_12c_archive_replay.py

### F3 | sev=LOW | M9.12c | .agent/roadmap.md:116
- divergence: Two rulings are restated across attached registers instead of having one authority plus pointers: the unmeasured formula-gradient premise appears in roadmap line 116 and polish `p32`; the INSERT-only archive-containment premise appears in roadmap line 132 and polish `p2`.
- impact: The attached set pays duplicate context cost and admits independent drift between the binding claim and its deferred repair.
- acceptance-check: Keep each premise in one attached register; replace the other copy with a terse pointer while preserving each polish acceptance check. A search over roadmap, memory, and polish must find one substantive statement per ruling.
- red-test: judgment-only

### F4 | sev=HIGH | M9.13a | demo/walkthrough.py:948
- divergence: The 13-scenario dataset registry has no committed exact-name or literal-cardinality pin. Replacing `_SCENARIOS` with `()` leaves `run_walkthrough()` reporting PASS over 0/0, and the complete current suite still reports 2900 passed.
- impact: `python -m demo` can silently lose every dataset capstone scenario while the project gate remains green and the aggregate claims success.
- acceptance-check: Hand-state the exact 13 dataset scenario names and the literal count 13 in a committed test; assert the in-process and subprocess reports are `(13, 13, 0)` and match that set; rerun empty-registry and rename mutants and require nonzero pytest rc.
- red-test: review_checks/check_m9_13a_mutants.py

### F5 | sev=MED | M9.13a | demo/formula_walkthrough.py:285
- divergence: The certificate-shape scenario pins non-empty IDs, all-pass status, and the three method labels, but never the hand-stated 13-check cardinality. Returning the authenticated certificate with one construction check removed preserves all three methods and leaves all 2900 tests green.
- impact: The capstone can under-report completed certified checks while still claiming the measured three-method formula shape.
- acceptance-check: Hand-state 13 beside the method literal; assert `len(certificate.checks) == 13` in the scenario and its dedicated test; rerun the drop-one-check mutant and require nonzero pytest rc.
- red-test: review_checks/check_m9_13a_mutants.py

### F6 | sev=MED | M9.13c | demo/e2e.py:265
- divergence: The real-socket report claims restart durability, but no observation pins that `_VerifierService.restart()` replaced the child. Replacing the method with a no-op leaves the complete current suite at 2900 passed, including the 4/4 subprocess demo test. Open polish `p40` records the same gap.
- impact: A restart regression can reuse the live process, in-memory chart cache, and already-open service while the capstone still reports exact post-restart replay.
- acceptance-check: Expose and assert a process-independent replacement witness, such as `_launches` advancing across each restart-taking case, or install a call-counting bomb that proves `restart()` executes stop then start. Rerun the no-op mutant and require nonzero pytest rc.
- red-test: review_checks/check_m9_13c_restart_mutant.py

### F7 | sev=MED | M9.13e | POC_SCOPE.md:326
- divergence: The exact carrier is a six-field `FormulaPlotSpec` `{version, formula, domain, numeric_profile, mark, encoding}`, but four live claim surfaces narrow what the model supplies: POC_SCOPE and `app.py` say only expression + domain; the root diagram omits version, numeric profile, and mark; the roadmap says only `{formula, domain, encoding}`. The model controls `mark` (`line|scatter`) and submits the fixed-profile/version/encoding fields too.
- impact: The trust boundary understates model-controlled input and lets future claim edits reason from an incomplete formula carrier.
- acceptance-check: Make `VPlot_SEMANTICS.md` F1 the exact inventory authority; sweep `.agent/roadmap.md`, `POC_SCOPE.md`, `README.md`, and `src/verifier/service/app.py` to say the model supplies a complete restricted `FormulaPlotSpec` but no points or Python, or enumerate all six fields once and use pointers elsewhere. Re-run the named search and require zero narrowed copies with a positive control on F1.
- red-test: review_checks/check_m9_13e_formula_claims.py

### F8 | sev=MED | M9.13e | README.md:198
- divergence: The M9.13e acceptance paragraph says `POST /verify-formula` and `POST /propose-formula` “verify, certify, archive, and replay canonical matplotlib scripts.” Neither POST route replays; `GET /replay/{plot_id}` is the separate replay surface, recomputes from archived canonical spec, and reproduces no artifact bytes or signature.
- impact: The reader-facing acceptance record overstates both POST contracts and obscures the load-bearing separation between publication and replay.
- acceptance-check: Attribute verify/certify/archive to the POST flow conditionally on a verified result; attribute recomputation/reporting to `GET /replay/{plot_id}` and state that script bytes remain independently retrievable. Search for any POST→replay restatement and require zero matches.
- red-test: review_checks/check_m9_13e_formula_claims.py

### F9 | sev=LOW | M9.13e | README.md:237
- divergence: The four human-facing READMEs still contain 14 ASD-STE100 violations: README 9, bench README 1, demo README 4. All 14 current anchors independently re-resolved; open polish `p41` records their active-voice rewrites and notes that `webui/README.md` still needs the same hand review.
- impact: Shipped operator prose remains outside the required register, and passive constructions obscure the acting component in verification and replay claims.
- acceptance-check: Apply the 14 p41 rewrites, hand-review `webui/README.md`, preserve every POC_SCOPE quotation byte-for-byte, and avoid upgrading conditional real-model claims. Run the committed README checker specified by `p11` once it lands.
- red-test: judgment-only

## Notes

- M9.12c shipped sizes re-derived at `9a1fb39`: roadmap 30,870 B; memory 29,125 B; combined 59,995 B; reference 23,951 B; archive 243,475 B. Current: roadmap 38,901 B; memory 30,472 B; combined 69,373 B; polish 39,935 B; attached-three 109,308 B; reference 32,581 B; archive 268,782 B. The roadmap presents the original numbers as the closed unit's historical measurement, so current growth is not itself a stale-fact finding.
- Reference trigger table: 13 rows map to all 13 `##` subsystem sections; no orphan section found. `_ROUTE_ATTACHES_PLOT` occurs only in non-attached reference text that explicitly marks it retired; no attached-state live use found.
- Archive checks: `python3 .scratch/archive_m9.py HEAD --check` rc=1 (`starts=[]`); `python3 .scratch/archive_m9.py dbebdc7 --check` rc=1 after internal heading-strip validation passes and full on-disk comparison fails.
- M9.13a mutation check: empty dataset registry and drop-one-certified-check each ran against the full current suite with `--no-cov`; both survived at 2900 passed, then restored byte-identically (`walkthrough.py` sha256 `29ef080d…`; `formula_walkthrough.py` `6ab56eb2…`).
- `python -m demo.formula_walkthrough` rc=0; report logged 5/5 PASS. Formula registry exact names + literal cardinality are pinned in both in-process and subprocess tests. Domain-tagged artifact checks use authenticated VCert v0.3 bindings; `/chart` is checked before and after replay with co-located certificate/table/script 200s.
- M9.13b: rejected response key set is exactly `{attempt_id, layer, results, verified}`; audit `plot` is null; default + revealed carrier roles are exactly `("raw_spec", "verdict")`, with dataset-role tokens absent from emitted bytes. Revealed verdict result + message equal the POST rejection. Three guard helpers have dedicated tests; the tampered-signature test bombs `Archive._connect`, proving authentication precedes connection. Both full-suite mutant runs and the live 5-scenario demo exercised these paths without a finding.
- M9.13c: `python -m demo.e2e` rc=0 with 4/4 PASS; importing `demo.e2e` left `demo.formula_walkthrough` absent from `sys.modules`. The socket case authenticates a canonical VCert v0.3 under the wire-advertised key, compares all four bindings, domain-hashes table/script bytes, checks artifact-route 200s, and checks `/chart` before + after replay. The exact four case names and literal count are pinned.
- No-op-restart mutant: full suite rc=0, 2900 passed; source restored byte-identically at sha256 `3be7475c…`.
- M9.13d: `review_checks/check_vplot_semantics_structure.py` rc=0 — one H1, two Part H2s, 21 H3s, 12 dataset + 9 formula labels, exact section sequences, and 23 parsed external numbered citations resolving. All 80 backticked code-line ranges exist; Marksman diagnostics are empty. Runtime re-derivation matches six spec fields, five domain fields, nine `FormulaSource` + nine `FormulaTcb` fields, 12 `formula.*` IDs + 11 formula resources + five render IDs, and the three certified success methods over 13 checks. File remains 46,749 B and byte-unchanged after `d17761b`.
- M9.13e accepted repairs rechecked: R8 sentence byte-exact at exactly three sites; five root-README quotations match POC_SCOPE byte-for-byte; respelling probe yields three invariant certified digests and one spelling-sensitive `spec_hash`; formula WebUI code search rc=1 with `proposeSpec` control rc=0.
- `review_checks/check_markdown_integrity.py` rc=0 over 25 tracked Markdown files and 10 parsed relative links: one non-fenced H1 per file and every target exists. Marksman diagnostics are empty for README, POC_SCOPE, four operator/corpus READMEs, and reference.
- `review_checks/check_m9_13e_formula_claims.py` rc=1 on four narrowed carrier sites plus the POST→replay overclaim. All 14 p41 debt anchors re-resolved independently. Mechanical STE audit: webui 0 length/passive hits; root length hits remain quotation-dominated, while the known hand-reviewed active-voice debt remains.
- Demo oracles all ran from this worktree with load-bearing `PYTHONPATH`: dataset 13/13 PASS, formula 5/5 PASS, real-socket e2e 4/4 PASS.
