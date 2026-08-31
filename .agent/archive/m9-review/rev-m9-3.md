# rev-m9-3 — archive schema v4 + plot bundles + interpreter portability

STATUS: DONE
FLUSHED: 4/4

## Unit verdicts

Fill one row per batch. verdict = CLEAN | FINDINGS. findings = comma-separated F-ids or `none`.

| unit | verdict | findings |
|---|---|---|
| M9.7a | FINDINGS | F3 |
| M9.7b-1 | FINDINGS | F1 |
| M9.7p | FINDINGS | F2 |
| M9.7b-2 | FINDINGS | F4 |

## Findings

### F1 | sev=LOW | M9.7b-1 | .agent/archive/m9.md:109

- divergence: The M9.7b-1 record assigns per-mode `_PLOT_BINDING_FIELDS` plus `_plot_bindings` dispatch to `4e9c7b8` and calls `_decode_canonical_spec` per-mode. That commit contains one dataset `_PLOT_BINDING_FIELDS`, a dataset-only `_plot_bindings`, the unchanged dataset decoder, and a separate new `_decode_canonical_formula_spec`. Per-mode binding maps first land in `005c714` (M9.8b). `.agent/roadmap.md:83` repeats the wrong unit ownership.
- impact: The unit ledger and archived boundary are historically false, so a later audit can attribute an M9.8b formula-attempt obligation to M9.7b-1 and trust dispatch that did not exist at that boundary. Current runtime behavior is correct because `005c714` later adds the maps.
- acceptance-check: Rewrite the M9.7b-1 ledger/body to name the dataset-only binding state and separate formula decoder; assign per-mode binding maps and `_plot_bindings` dispatch only to M9.8b. Confirm `git show 4e9c7b8:src/verifier/service/archive.py` has only `_PLOT_BINDING_FIELDS`, while `git show 005c714:src/verifier/service/archive.py` has `_FORMULA_PLOT_BINDING_FIELDS` and `_PLOT_BINDING_FIELDS_BY_SOURCE`.
- red-test: judgment-only

### F2 | sev=MED | M9.7p | .agent/archive/m9.md:129

- divergence: The FORM-vs-WIRING record says fixed-TCB canonical form is "portable across every admitted patch", and `src/verifier/vcert.py:484` says it stays byte-stable across every patch admitted by `>=3.13,<3.14`. The binding ruling and the same unit's later acceptance text limit evidence to CPython 3.13.5 and 3.13.14 only. Injection removes live TCB bytes; it does not prove that every unmeasured interpreter patch preserves producer semantics and serialized bytes.
- impact: The durable archive and builder API documentation overstate the portability guarantee, inviting callers and future audits to treat unmeasured CPython patches as certified. The executable vectors remain correct on the measured pair.
- acceptance-check: Replace both general statements with the exact measured pair and retain the no-host/no-platform boundary. A repository search for `every admitted patch` and `patch releases that a` must return no portability claims; 3.13.5 and 3.13.14 vector suites must still pass byte-exactly.
- red-test: judgment-only

### F3 | sev=MED | M9.7a | src/verifier/service/archive.py:2166

- divergence: Schema v4 reopening compares live `sqlite_schema` text to the current `_SCHEMA_OBJECTS`, but no committed oracle pins that tuple to the v4 bytes shipped in `bcecfd1`; `tests/test_service_archive.py:1115` pins only derived v3 text. A whitespace-only change to `_CREATE_PLOT_SOURCE_GUARD` applied cleanly and all 2900 tests passed in an isolated worktree-linked environment. Reopening the mutant archive with the unmodified v4 code failed exact-schema validation, which is the real backward-compatibility outcome.
- impact: An incidental DDL formatting or wording edit can keep `_SCHEMA_VERSION == 4`, pass the complete primary-style suite, and make every previously created v4 archive refuse to open. The data remains present, but the durable archive becomes unavailable until code or schema migration is repaired.
- acceptance-check: Add a same-tree test that extracts the 13 shipped v4 schema-object rows from `bcecfd1:src/verifier/service/archive.py` and compares them byte-for-byte with `_SCHEMA_OBJECTS` while the version remains 4. The whitespace-only trigger mutant must fail that test; an intentional DDL change must instead bump the schema and ship a migration.
- red-test: judgment-only

### F4 | sev=MED | M9.7b-2 | src/verifier/service/archive.py:1021

- divergence: `_CANONICAL_SPEC_DECODERS` and `_ARCHIVE_CERTIFICATE_AUTHENTICATORS` are documented as total over `PlotSourceKind`, but neither has its own hand-stated exact-key-set pin or isolated enum-widening mutant. Adding `PlotSourceKind.SYNTHETIC` and only the role-map entry needed to satisfy the existing `set(_PLOT_ROLE_FIELDS_BY_SOURCE) == set(PlotSourceKind)` assertion left both dispatch maps partial; `mypy` returned 0 and all 2900 tests passed.
- impact: A future source-mode declaration can ship while projection, public-certificate authentication, the SQL source domain, and trigger policy remain incomplete. The first new-mode use then fails through a leaked `KeyError` or a storage refusal instead of the suite identifying each missing consumer at the enum change.
- acceptance-check: Hand-state the exact `PlotSourceKind` values and exact keys for each source-total map, including `_CANONICAL_SPEC_DECODERS` and `_ARCHIVE_CERTIFICATE_AUTHENTICATORS`. Add one isolated widening mutant per map and one SQL-domain/trigger mutant; each test must fail at its own consumer after sibling maps are made complete.
- red-test: judgment-only

## Notes

- M9.7a: FINDINGS F3. Historic v3 DDL independently extracted from `b7f594e:src/verifier/service/archive.py`: all 3 derived table definitions byte-equal; full 12-object `_SCHEMA_OBJECTS_V3` equal. Focused migration/profile/trigger/replay suite: 14 passed, 67 deselected. Rootpage identity, forced migration order, success/failure guard restoration, profile readback, FK-safe insert order, isolated role CHECK, exact v4→v3 fixture, and INSERT-only containment wording are correct. The missing shipped-v4 byte oracle remains the compatibility gap.
- M9.7b-1: FINDINGS F1. Full formula-bundle suite: 51 passed. Dataset validator remains byte-identical to `e432bd9`; current closed dispatch, v0.3 wrapper arguments/family narrowing, four digest bindings, TCB/verdict checks, exact-type guards, and historical `NotImplementedError` choke are pinned. Commit-object inventory disproves the archived binding-map ownership claim.
- M9.7p: FINDINGS F2. `tests/test_vcert.py` + `tests/test_attestation_v03.py`: 109 passed on CPython 3.13.14 and the same 109 passed on 3.13.5. Regeneration rc=0 and byte-idempotent (`c69de260…` before/after); outputs remain 1847/1847/1746 B at the archived digests. Builder signatures retain keyword-only `tcb=` and no legacy `verifier_version=`. Synthetic hand-authored vectors, live-source wiring, disagreement/identity threading, and production call-site live collection are pinned; only the written portability scope overclaims.
- M9.7b-2: FINDINGS F4. Landed storage + five localized totality-mutant suites: 42 passed. Eighteen still-relevant tests from retained `670e1b7` also passed after the documented decoder-spy seam adaptation; its two no-producer/deferred-surface tests were excluded because M9.8+ intentionally superseded them. Projection/read/reopen, 7-role graph, replay mirror, trigger/CHECK sets, certificate/spec closed dispatch, identical typed absence, typed dedup/quota, rollback, insert order, and v3→v4 dataset compatibility are correct. The source-mode widening mutant remained fully green: `mypy` rc=0 + 2900 passed.
