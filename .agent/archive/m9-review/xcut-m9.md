# xcut-m9 — cross-unit integration + project-CLAUDE.md conformance

STATUS: IN-PROGRESS
FLUSHED: 4/5

## Unit verdicts

Fill one row per batch. verdict = CLEAN | FINDINGS. findings = comma-separated F-ids or `none`.

| unit | verdict | findings |
|---|---|---|
| INTEGRATION | CLEAN | none |
| AUTHORING | FINDINGS | F1,F2 |
| ENGINEERING | FINDINGS | F3,F4,F5,F6,F7 |
| REGISTERS | FINDINGS | F8,F9,F10 |
| OBSOLESCENCE | unknown | unknown |

## Findings

One block per finding. Header: `### F<n> | sev=HIGH|MED|LOW | <unit> | <file>:<line>`.
Required bullets: `divergence:` `impact:` `acceptance-check:` `red-test:`.
Zero findings overall ⇒ write the literal token NO-FINDINGS on its own line here.

### F1 | sev=LOW | AUTHORING | README.md:237

- divergence: M9-touched human-facing prose retains confirmed passive constructions: “Known-bad specs are blocked,” “Unverified chart-like output is blocked,” benchmark corpora “are pinned,” demo cases “are blocked,” and optional legs “are disabled.” Project Authoring requires active voice. Sentence-length, filler, summaries, CLI help, filter copy, chart copy, and launcher copy otherwise conform in the audited surface.
- impact: Product claims hide the verifier/operator as the actor and miss the project’s fixed active-voice register.
- acceptance-check: Rewrite the confirmed passive sentences with explicit actors while preserving claims, values, code spans, links, and quoted internal text; run `review_m9_ste.py` and manually rule stative “remain/stay trusted” hits rather than rewriting them as false actions.
- red-test: review_m9_ste.py

### F2 | sev=MED | AUTHORING | .agent/archive/m9.md:93

- divergence: Durable M9 prose preserves extensive origin stories and verification chronology (“six contract defects found,” prep/review waves, agent harvest/death narratives, discovery order, repeated gate events); durable source/tests also retain unit provenance such as `vcert.py:5` “this unit” and `tests/test_m9u10_contract_reachability.py:2` “PREP-certified contract got wrong.” Project Authoring requires current facts/rules and prunes provenance, dates, verification/discovery events, and origin stories.
- impact: The 268,782-byte archive and milestone-labelled code prose make current invariants harder to retrieve, keep dead process detail durable, and couple behavioral tests to implementation chronology.
- acceptance-check: Reduce each archived unit to shipped surface, binding rulings, measurements that still constrain decisions, gate result, and evidence pointers; remove process chronology. Rename/reword milestone-labelled test and source prose by behavior while preserving regression coverage and archive pointers.
- red-test: judgment-only

### F3 | sev=MED | ENGINEERING | .agent/polish.md:21

- divergence: The durable M9.7a v3→v4 migration-equivalence claim rests on a scratch driver plus the lost local-only `wt/orc-m9u7a` rebuild oracle. No committed command can reconstruct the seven-archive corpus and compare logical sections; the source material is gone.
- impact: The judgment-bearing migration mechanism’s strongest independent equivalence evidence cannot rerun from committed state, so future SQLite changes cannot distinguish regression from a historical claim.
- acceptance-check: Rebuild and commit the independent corpus/oracle/differential; rerun it from a clean checkout; require equality for every logical section and declare `page_count`/`file_size` as expected mechanism differences.
- red-test: judgment-only

### F4 | sev=MED | ENGINEERING | .agent/polish.md:22

- divergence: Five durable mutation-strength claims lack a committed gate: M9.7b-1 formula-bundle predicates (27 killed/3 redundant), M9.8a route maps (4/4 killed), M9.9 formula replay (41/41 killed), M9.10 service pipeline/app/OpenAPI (36 killed/1 equivalent, no driver at all), and M9.12b occurrence guards (5/5 killed). Their scripts are gitignored, partly missing, or never existed.
- impact: 100% branch coverage remains rerunnable, but the stronger “predicate pinned” claims do not. Equivalent and surviving mutants cannot be reclassified after later edits.
- acceptance-check: Commit one clean-checkout mutation driver covering all five claim sets, restore bytes on every exit path, name each killer test, encode documented equivalence/reachability rulings, and rerun the complete ledger from committed HEAD.
- red-test: judgment-only

### F5 | sev=LOW | ENGINEERING | .agent/polish.md:27

- divergence: The standing four-README ASD-STE100 length claim is gated only by gitignored `.scratch/ste_audit.py`; no committed test executes it. This review’s independent `review_m9_ste.py` also stays worktree-local and therefore does not repair that durable-gate gap.
- impact: A later README edit can violate the declared register while the committed quality gate stays green.
- acceptance-check: Commit a test that checks exactly the four shipped READMEs, excludes byte-pinned quotations/code, reports file:line, and fails after injecting one >25-word description into each file.
- red-test: review_m9_ste.py

### F6 | sev=MED | ENGINEERING | .agent/roadmap.md:144

- divergence: The roadmap credits `.scratch/archive_m9.py` for a byte-exact M9.12c archive extraction, but the gate is uncommitted and currently exits 1 (`marker ambiguity: starts=[] ends=[143]`). The archive also includes hand-appended Plan/Memory sections outside the extractor’s modeled source.
- impact: The claimed reproducible relocation cannot regenerate the committed archive, so later archive repairs have no idempotent source-to-output path.
- acceptance-check: Commit an extractor that models every archived section, rebuilds `.agent/archive/m9.md` byte-identically from the declared source ref, and exits 0 in `--check` mode from committed state; otherwise remove the byte-exact extraction claim.
- red-test: judgment-only

### F7 | sev=LOW | ENGINEERING | .agent/archive/m9.md:9

- divergence: M9.1–M9.12b archive sections omit the project-required assurance-tier declaration; only M9.13a–e headings declare `tier=kernel|docs`. The earlier units often ran kernel-grade gates, but the tier was never stated per unit.
- impact: Reviewers cannot mechanically verify that each unit’s planned rigor matched where defects receive downstream rechecking; the evidence exists without its governing assurance decision.
- acceptance-check: Declare one tier for every M9 implementation unit and map its acceptance evidence to that tier; retain `kernel` only where the archived adversarial battery satisfies the project definition, and identify any deficit as an open acceptance check.
- red-test: judgment-only

### F8 | sev=MED | REGISTERS | .agent/roadmap.md:118

- divergence: The M9.12c trigger split says `roadmap.md` carries trajectory/unprompted rulings, `memory.md` is subsystem-free, and `reference.md` carries named-subsystem mechanics. The attached roadmap still carries VCert, WorkBudget, parser, canonicalization, archive-containment, and decoder mechanics; attached memory still carries msgspec, hashing, DuckDB, mypy/Hypothesis, monkeypatch, dispatch-map, and mutation mechanics. Each has an unmissable subsystem trigger and belongs behind the reference table.
- impact: The claimed trigger boundary is false and every session pays for conditional mechanics. Current roadmap+memory size is 69,373 B versus the M9.12c <60 KB result; all three attached registers total 109,308 B.
- acceptance-check: Classify every roadmap/memory rule by trigger; move named-subsystem mechanics into existing or new `reference.md` sections; retain only trajectory, claim boundaries, and rulings that must bind before a subsystem is known; validate every trigger target and report the resulting per-register byte sizes.
- red-test: judgment-only

### F9 | sev=LOW | REGISTERS | .agent/roadmap.md:68

- divergence: The roadmap says closed unit records have one `## M9.<u>` archive heading each, but `.agent/archive/m9.md` has no `## M9.12a` or `## M9.12c`. M9.12a is nested inside `## M9.12`; M9.12c remains only as an attached roadmap record.
- impact: Two ledger units cannot be resolved through the declared archive-pointer grammar, and one closed unit’s detail never leaves attached state.
- acceptance-check: Give M9.12a and M9.12c direct archive headings with their closed records, or narrow the one-heading claim and add an explicit pointer map that resolves every ledger unit unambiguously.
- red-test: judgment-only

### F10 | sev=MED | REGISTERS | .agent/archive/m9.md:13

- divergence: A 12-ruling promotion sample found 10 live homes and two stranded rulings: M9.1’s reason that `DecimalText` must have no `max_length`, and M9.4b’s rejection of a widened/generic `VerificationRun` in favor of mode-specific run/trace types (`.agent/archive/m9.md:53`). Neither appears in roadmap, memory, reference, or polish, despite binding future schema and run-model edits.
- impact: A session follows the trigger table yet misses two settled design constraints, so it can reintroduce a non-binding cap or a rejected type shape without reading closed history.
- acceptance-check: Re-derive both rulings against current code; promote each still-binding rule into a named `reference.md` section and trigger row, or mark it retired with the current replacement authority. Repeat the promotion sample across every archive heading.
- red-test: judgment-only

## Notes

- INTEGRATION: `review_m9_integration.py` rc=0 traced one `f02` occurrence through canonical spec, authenticated VCert v0.3, all four certified hashes, exact replay, and route retrieval. Matrix: dataset `/spec`=200 `/certificate`=200 `/chart`=200 `/table`=200 `/script`=404 `/replay`=200; formula =200/200/404/200/200/200. Dataset `/script` has no typed relation; formula `/chart` has no executed/cached page.
- INTEGRATION preservation: `tests/dataset_http_response_diff.py` rc=0; dataset capstone 13/13 PASS; formula capstone 5/5 PASS; cross-layer subset 140 passed. Protocol mirrors are deliberate and pinned: replay remains service-import-pure while `test_replay_role_vocabulary_matches_archive_producer` equates both role tuples; M9.9's formula replay twin is explicitly ruled duplicate-not-parameterize; check methods rejoin at archive + replay validation.
- AUTHORING: `review_m9_ste.py` audits the four shipped READMEs plus launcher/filter/chart/OpenAPI/CLI product strings. Definite length/filler defects=0 after excluding quoted internal prose + code fences; one 21-word demo description remains within the 25-word description ceiling. Confirmed passive copy forms filed as F1.
- ENGINEERING SPDX: diff `6970b7d..4357c55` adds 37 `.py`/`.sh` source files; 37/37 first lines equal `# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception`.
- ENGINEERING duplication: no unruled behavioral twin found. Replay’s role vocabulary duplicate preserves service-import purity and is exact-tuple pinned; formula replay/authentication twins are explicitly duplicate-not-parameterize because v0.2/v0.3 wrappers/types differ; OpenAPI response twins preserve concrete artifact families; archive/audit maps are hand-stated closed consumer vocabularies with literal pins.
- REGISTERS inventory: the repository has four live `.agent/*.md` registers, not five: roadmap 38,901 B, memory 30,472 B, polish 39,935 B, reference 32,581 B. M9 archive is 268,782 B; all five measured files total 410,671 B. The project policy defines those four live registers, so the count itself is clean.
- REGISTERS reference map: 13 trigger rows resolve to 13 sections; missing targets=0, orphan sections=0. Every trigger is named/unmissable; no inferential trigger found. Exact normalized lines duplicated across attached files=0; manual semantic checks found authority/recipe, class/list, sizing/pointer, and scratch-port/action splits rather than duplicate rules.
- REGISTERS promotion sample: 12 archived rulings sampled across M9.1, M9.2, M9.3, M9.4a, M9.4b, M9.5, M9.6b, M9.7a, M9.9, M9.11, M9.12b, and M9.13d; 10 have live homes and 2 are F10. This is a bounded sample, not an exhaustive archive census.
