# rev-m9-4 — attempt-route totality + pure formula replay

STATUS: DONE
FLUSHED: 3/3

## Unit verdicts

| unit | verdict | findings |
|---|---|---|
| M9.8a | CLEAN | none |
| M9.8b | FINDINGS | F1 |
| M9.9 | FINDINGS | F2,F3,F4,F5 |

## Findings

### F1 | sev=MED | M9.8b | .agent/reference.md:60

- divergence: The forward-binding reference says `_validate_attempt_outcome` enforces plot present ⇔ `VERIFIED`. Live code intentionally makes `_validate_manifest_plot_presence`, called once from pre-sign `_validate_manifest_route_relations`, the sole owner; `_validate_attempt_outcome` explicitly omits the unreachable duplicate.
- impact: A future archive change following the reference can re-add the deleted bundle-layer predicate, target ordering probes after signing, or misread the actual single-owner guarantee.
- acceptance-check: Rewrite the sentence to name `_validate_manifest_plot_presence` inside the pre-sign route-relations owner. Search live guidance for `_validate_attempt_outcome` and retain only its reply-identity/artifact-verdict responsibilities.
- red-test: judgment-only

### F2 | sev=MED | M9.9 | src/verifier/replay.py:1602

- divergence: Formula replay authenticates digest-bound plotted-table bytes without first proving the canonical typed-NDJSON representation. A malformed table, rebound into the certificate and re-signed through the attempt, returns `recomputation_failed` with `integrity_ok=True` instead of `integrity_failed` at `plot_contents`.
- impact: Replay labels a cryptographically authentic but structurally invalid archive carrier as a recomputation disagreement. Consumers cannot use the integrity verdict or failure stage to distinguish malformed archived evidence from a valid recomputation mismatch.
- acceptance-check: Centralize canonical plotted-table decoding in `canon`; require it before semantic recomputation in archive publication and both replay engines. Pin formula, dataset, and publication rejection. Require `integrity_failed`, `failure_stage == "plot_contents"`, and `integrity_ok is False` for digest-authentic malformed bytes.
- red-test: `tests/test_rev_m9_4.py::test_formula_replay_rejects_digest_authentic_noncanonical_table`

### F3 | sev=MED | M9.9 | src/verifier/replay.py:946

- divergence: Formula replay authenticates an attempt DSSE envelope without requiring its canonical byte representation. Appending one ASCII space, recomputing `attempt_id`, and retaining the signed payload and occurrence returns `exact`.
- impact: Multiple envelope byte encodings can identify the same signed attempt semantics. Replay accepts an attempt representation that archive publication is intended to reject, weakening canonical identity and cross-surface integrity consistency.
- acceptance-check: Pass `require_canonical_envelope=True` at both attempt-authentication sites. Pin formula replay, dataset replay, and archive publication refusal for a whitespace-padded attempt envelope; formula replay must return `integrity_failed` at `attempt_signature` with `integrity_ok is False`.
- red-test: `tests/test_rev_m9_4.py::test_formula_replay_rejects_noncanonical_attempt_envelope`

### F4 | sev=LOW | M9.9 | src/verifier/replay.py:1256

- divergence: Two local comments overstate the purity/import boundary. The dataset-import comment says only that path pays for both `vl_convert` and Z3, although formula replay loads Z3 through `formula_prepare`. `_recompute_formula_certificate` says it rebuilds from the spec “and nothing else”, although caller limits, live verifier code, and fresh TCB collection also influence the result.
- impact: Maintainers can infer a false dependency boundary or a stronger replay-purity guarantee than the implementation provides. The module-level docstring already states the narrower, correct archived-input claim.
- acceptance-check: Align both local comments with the module-level wording: the canonical formula spec is the sole archived semantic input; formula replay still loads Z3; live limits, implementation, and TCB remain recomputation inputs.
- red-test: judgment-only

### F5 | sev=LOW | M9.9 | .scratch/mutate_m9u9.py:32

- divergence: The retained M9.9 mutation regeneration path is stale on the current tree. It reports 39 killed, zero survivors, and two malformed anchors (`route-formula-false`, `graph-model-roles`) instead of executing all 41 configured mutations. Both predicates kill focused tests after manual re-anchoring to the current four-route and reply-identity shapes.
- impact: The one-command review gate exits nonzero and cannot regenerate its full claim from committed state. A result summarized only by survivor count can also hide two unexecuted predicates.
- acceptance-check: Update the retained driver for the current nodes or port it into the committed gate. From committed state, require 41 killed, zero survivors, zero malformed, and byte-identical source restoration. Existing polish item `p4` owns the broader committed-gate port.
- red-test: judgment-only

## Evidence

- M9.8a: 9/9 isolated route-surface mutants killed by dedicated single-node tests; every mutation applied, every source SHA-256 restored, and `src/**/__pycache__` cleared per cycle. Route/proposer subset: 103 passed, rc=0. Live-tree `_ROUTE_ATTACHES_PLOT` search: rc=1/0 lines; `_ROUTE_ATTACHES_DATASET_PLOT` positive control: rc=0/4 lines.
- M9.8b: 17/17 isolated presence/topology/binding/source/role/TCB/certificate/reader/audit/replay-dispatch mutants killed by existing focused tests; every source SHA-256 restored and bytecode caches cleared per cycle. One initial reader-selector candidate exercised standalone reads rather than attempt reconstruction; the existing formula-attempt round-trip killed the applied mutant. Plot-union subset: 110 passed, rc=0. Production single-owner/source-neutral design clean; F1 is a false forward-binding ownership claim.
- M9.9 replay boundary: formula replay decodes the archived canonical spec, reparses and recomputes through `checks.verify_formula_run`, rebuilds evidence/script through `prepare_formula` and `emit_matplotlib_script`, and collects a fresh live TCB. Archived AST, point table, script, verdict, certificate, and TCB do not steer recomputation. Formula replay imports neither `verifier.render` nor `vl_convert`; dataset replay owns its function-local `render` import. No `verifier.service` module enters the pure replay import graph. Formula verdicts expose no artifact or signature bytes.
- M9.9 exactness: `exact` compares four hashes, the canonical VCert payload, and live TCB. Rewriting only a check message retained `status=exact`, `exact=True`, and `payload_match=True`. Equivalent formula spelling retained formula/table/script hashes but changed spec hash, VCert payload, and plot identity. Dataset-preservation differential: rc=0. Formula replay subset: 75 passed, rc=0.
- M9.9 mutations: retained driver configured 41, killed 39, survived 0, malformed 2; source SHA-256 restored. Manual current-node runs killed both malformed predicates. All 41 intended predicates were therefore exercised, but the retained one-command path remains nonzero and stale per F5.
- Reviewer red witnesses: `tests/test_rev_m9_4.py` committed as `e18bcfb` (`tests (review): replay gaps latent → pin red witnesses`). Ruff format/check and file-scoped mypy passed. Exact full pytest gate: 2900 passed, 2 failed, 8 warnings, 100.00% coverage, rc=1; failures were exactly F2 and F3 witnesses. Shipped suite with the reviewer file ignored: 2900 passed, 8 warnings, 100.00% coverage, rc=0.
- Full static gates: `ruff format --check .` passed; `ruff check .` passed; `mypy` passed across 132 source files.
