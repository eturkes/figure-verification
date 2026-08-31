# audit-m9 — claim replayer: every recorded M9 number re-derived

STATUS: DONE
FLUSHED: 6/6

## Unit verdicts

Fill one row per batch. verdict = CLEAN | FINDINGS. findings = comma-separated F-ids or `none`.

| unit | verdict | findings |
|---|---|---|
| GATE | FINDINGS | F1 |
| COUNTS | FINDINGS | F2,F3,F4 |
| HASHES | FINDINGS | F5,F6 |
| SIZES | FINDINGS | F7,F8 |
| GAUGES | FINDINGS | F9,F10,F11,F12,F13 |
| BRANCHES | FINDINGS | F14 |

## Findings

One block per finding. Header: `### F<n> | sev=HIGH|MED|LOW | <unit> | <file>:<line>`.
Required bullets: `divergence:` `impact:` `acceptance-check:` `red-test:`.
Zero findings overall ⇒ write the literal token NO-FINDINGS on its own line here.

### F1 | sev=LOW | GATE | .agent/roadmap.md:144

- divergence: RECORDED M9.12c gate = bare mypy 129 files + pytest 2882 passed + 100% branch; CURRENT edit-free HEAD `c8f308c` gate = bare mypy 131 files + pytest 2900 passed + 100.00% branch (6801 statements, 1406 branches, 0 missed).
- impact: the gate remains green, but the roadmap's retained historical cardinalities are not the current HEAD cardinalities; the review brief's asserted current 129-file baseline is also false.
- acceptance-check: retain the M9.12c numbers as explicitly historical and record the milestone-close HEAD numbers as 131 mypy files, 2900 tests, and 100.00% branch coverage.
- red-test: `/home/eturkes/Projects/figure-verification/.scratch/worktrees/audit-m9/audit_m9/rederive_gate.sh`.

### F2 | sev=LOW | COUNTS | .agent/roadmap.md:151

- divergence: RECORDED M9.13c = `+103 statements` (`demo/e2e.py +94`, `tests/test_demo_e2e.py +9`); CURRENT pinned `coverage.parser.PythonParser` comparison at `e9e3471^..e9e3471` = net `+100` (`demo/e2e.py +91`, tests `+9`). Gross changed-statement additions are `103` with `3` removed statements.
- impact: `103` is reproducible only as the gross addition count, not as the net statement delta used for M9.9; the sizing ledger mixes two measurement definitions.
- acceptance-check: label M9.13c as `103 gross statement additions / 3 removals / +100 net`, or use the net `+100` consistently with the M9.9 datum.
- red-test: `/home/eturkes/Projects/figure-verification/.scratch/worktrees/audit-m9/audit_m9/rederive_counts.py`.

### F3 | sev=MED | COUNTS | .agent/roadmap.md:152

- divergence: RECORDED M9.13d review harvest = `21 of 25` findings applied; CURRENT retained review report `.scratch/agents/rev-m9u13d-2.md` has `26` finding rows, and V-26's unqualified “SOLE strictly-increasing authority” remains in `VPlot_SEMANTICS.md:492-495`. The archived classification still totals 25 = 21 applied + 1 partial + 3 declined.
- impact: the live milestone ledger omits one retained MED finding, so the review disposition is incomplete against its own current evidence artifact.
- acceptance-check: rule V-26 and update the applied/partial/declined denominator to 26, or restore a source-state-bound 25-row review artifact that proves V-26 arrived outside the reviewed close.
- red-test: `/home/eturkes/Projects/figure-verification/.scratch/worktrees/audit-m9/audit_m9/rederive_counts.py`.

### F4 | sev=MED | COUNTS | .agent/roadmap.md:74

- divergence: RECORDED M9.3 = `64,480` oracle points, `11,513` expected production-only work refusals, and zero unexpected divergences; CURRENT re-derived value = UNREPRODUCIBLE because only `.agent/roadmap.md` and `.agent/archive/m9.md` retain the number, while no committed or retained executable records the Cartesian axes or regeneration command.
- impact: the headline oracle cardinality and outcome partition cannot rerun from committed state; current oracle tests establish behavior but cannot reconstruct that historical campaign.
- acceptance-check: commit a bounded runner that states every axis, derives exactly 64,480 cases, classifies exactly 11,513 work-only refusals, and reports zero unexpected divergences on HEAD.
- red-test: judgment-only.

### F5 | sev=LOW | HASHES | .agent/archive/m9.md:71

- divergence: RECORDED M9.6a = the whole v0.2 certificate subsystem was relocated into `vcert.py` “byte-unchanged”; CURRENT mechanical source comparison = exact bytes for `Tcb`, `DisclosedFilter`, `DisclosedSort`, `CertifiedCheck`, and `VCert`, but changed bytes for `vcert_bytes`, `hash_vega_lite`, and `disclosed_transforms`. CURRENT wire output remains byte-identical to `b6c8161^`: payload `1675 B`, `sha256:4bc125e35261d501104aebd4ccb489e7f0d6dca805942eb495478b6ac3a89bc4`; fixed-key envelope `2514 B`, `sha256:b01f2c3c1a85ec5e465e55b5ae149dd1f16dea83bbba56e3049a1ff7ed8c53d3`.
- impact: the compatibility guarantee holds, but the archived wording conflates source-text identity with emitted-byte identity.
- acceptance-check: state that v0.2 wire output stayed byte-identical and name the exact source nodes that moved unchanged; do not claim whole-subsystem source identity.
- red-test: `/home/eturkes/Projects/figure-verification/.scratch/worktrees/audit-m9/audit_m9/rederive_hashes.py`.

### F6 | sev=HIGH | HASHES | .agent/reference.md:88

- divergence: RECORDED second-interpreter gate = CPython 3.13.5 green with 2530 passed and 100.00% coverage; CURRENT exact recipe = rc=1, `2898 passed / 2 failed`, coverage `99.98%` with `pipeline.py:641-642` missed. Both failures expect `max_attestation_bytes=1801` to refuse, but on 3.13.5 the live formula certificate fits and returns a verified success. The injected-TCB vector suite itself remains REPRODUCED: `tests/test_vcert.py` = 49 passed on 3.13.5.
- impact: canonical vector patch portability still holds, but the current full acceptance gate is no longer CPython-patch-portable across the claimed pair.
- acceptance-check: make the two attestation-ceiling tests derive a patch-neutral boundary or inject the fixed TCB, then require the exact reference recipe to pass all 2900 tests at 100.00% on both 3.13.5 and 3.13.14.
- red-test: `/home/eturkes/Projects/figure-verification/.scratch/worktrees/audit-m9/audit_m9/rederive_py3135.sh`.

### F7 | sev=LOW | SIZES | .agent/roadmap.md:144

- divergence: RECORDED promotion-time attached `.agent/` = `287,738 B`; CURRENT re-derived historical value = UNREPRODUCIBLE from committed state. The adjacent committed attached trios are `287,482 B` at `3e21462` and `288,405 B` at promotion commit `dbebdc7`; neither equals the recorded figure.
- impact: this one sizing datum depends on an uncommitted intermediate tree and cannot serve as a rerunnable committed-state measurement.
- acceptance-check: bind the 287,738-byte snapshot to a retained tree/object, or replace it with the exact adjacent committed measurement and name the included file set.
- red-test: `/home/eturkes/Projects/figure-verification/.scratch/worktrees/audit-m9/audit_m9/rederive_sizes.py`.

### F8 | sev=MED | SIZES | .agent/roadmap.md:144

- divergence: RECORDED post-M9.12c sizes = roadmap `30,870 B`, memory `29,125 B`, combined `59,995 B`, reference `23,951 B`, archive M9 `243,475 B`; CURRENT = roadmap `38,901 B`, memory `30,472 B`, combined `69,373 B`, reference `32,581 B`, archive M9 `268,782 B`. Current attached trio including polish is `109,308 B`; all `.agent/**/*.md` total `461,821 B`.
- impact: the live roadmap sentence retains snapshot numbers without a snapshot qualifier; current sizing decisions can underprice attached state by using 59,995 B as a present value.
- acceptance-check: label all five figures as commit-`9a1fb39` snapshots and add one mechanically generated current attached-state total, or remove the stale present-tense sizes from the live roadmap.
- red-test: `/home/eturkes/Projects/figure-verification/.scratch/worktrees/audit-m9/audit_m9/rederive_sizes.py`.

### F9 | sev=MED | GAUGES | .agent/roadmap.md:68

- divergence: RECORDED = one `## M9.<u>` archive heading per closed unit, each body carrying its gauges, with M9.6b/M9.12a/M9.12b/M9.12c read as `>1 window`; CURRENT archive = M9.6b and M9.12b explicitly own that marking, M9.12a is a nested bullet that reports raw `94% 226K/240K` and is reclassified only backward from M9.12b, and M9.12c has no archive heading or body at all (its roadmap-only record is raw `main=100% 239K/240K`, `mate=89% 214K/240K`).
- impact: the promised archive is not a self-contained unit/gauge index; a heading-bounded consumer cannot confirm M9.12a or find M9.12c from the primary claim source.
- acceptance-check: give every delivered unit its own archive heading; put explicit `>1 window` markings in the M9.12a and M9.12c bodies; keep split-only umbrella headings separately classified as non-units.
- red-test: judgment-only.

### F10 | sev=MED | GAUGES | .agent/archive/m9.md:223

- divergence: RECORDED rule = any unit crossing a compaction boundary reads `>1 window`, and its raw successor/high-water number is never cited as a fit; CURRENT M9.11 record says one boundary crossed at close and about 20% of the successor window was spent on teardown/gate/ledger, yet records `main=95% 229K/240K`, and M9.12's sizing rationale cites M9.11 as an analog that “fit at 95%”.
- impact: the fit set contains a unit that the governing rule classifies as over-window, biasing later split decisions toward larger units.
- acceptance-check: classify M9.11 as `>1 window`; remove its raw 95% from fit analogs; re-state any sizing ruling that depended on that analog.
- red-test: judgment-only.

### F11 | sev=MED | GAUGES | .agent/roadmap.md:68

- divergence: RECORDED live over-window index names M9.6b, M9.12a, M9.12b, and M9.12c; CURRENT later archive bodies add M9.13b (`>1 window`), M9.13d (closing `52% 125K/240K`, true cost ≈1.6 windows), and M9.13e (closing `53% 126K/240K`, true cost ≈1.5 windows). With F10 applied, M9.11 is an eighth over-window unit.
- impact: PLANNING's attached index omits three explicit post-index overflows and one internally inconsistent earlier overflow, so it can select invalid raw percentages without reading every archived body.
- acceptance-check: derive the over-window index from every closed-unit body and list at least M9.6b, M9.11, M9.12a, M9.12b, M9.12c, M9.13b, M9.13d, and M9.13e; never expose their raw closing/successor readings as fit values.
- red-test: judgment-only.

### F12 | sev=LOW | GAUGES | .agent/archive/m9.md:206

- divergence: RECORDED M9.10 prep record contains the literal but valueless ``main=`` followed by “this window”, while recording `mate=87% 208K/240K` (`map-m9u10=84% 203K/240K`); CURRENT exact prep MAIN occupancy is UNREPRODUCIBLE from the archive. The implementation record separately carries `main=95% 229K/240K` and `mate=99% 237K/240K`.
- impact: one of the nine claimed full-window prep waves has no numeric MAIN datum, so the archived gauge table cannot reproduce every prep-wave reading.
- acceptance-check: recover and source-bind the M9.10 prep MAIN high-water, or replace the empty field with the literal `not recorded` and exclude it from numerical ranges.
- red-test: judgment-only.

### F13 | sev=MED | GAUGES | .agent/archive/m9.md:9

- divergence: RECORDED = the table below's historical `main=`/`mate=`/`impl=` percentages and K/240K readings; CURRENT independent measurement = UNREPRODUCIBLE because past windows have ended and the archive binds no reading to a retained transcript ID, exact `context-gauge -p` output, or source hash. Only exact textual extraction and cross-record consistency can be reproduced now.
- impact: the sizing datums are durable assertions but not replayable evidence; a local transcript cleanup or prefix collision can make the underlying measurement permanently undecidable.
- acceptance-check: retain one source-bound gauge artifact per unit with exact transcript IDs, high-water extraction output, and the command/version that produced it; make the archived body point to that artifact.
- red-test: judgment-only.

### F14 | sev=LOW | BRANCHES | .agent/polish.md:25

- divergence: RECORDED p8 command = `git diff --stat main..wt/test-m9u7b2` yields `11 files, +565/−318`; CURRENT exact command = `88 files, +2283/−16609` because `main` advanced. The historical value reproduces only at `35397e0^..54fe1d4`; the current branch-only merge-base comparison is `5 files, +1611/−22`.
- impact: the retained test remainder still exists, but the unpinned two-tip command no longer inventories it and now mixes years of mainline drift into the branch justification.
- acceptance-check: bind the 11/+565/−318 snapshot to `35397e0^`, and use an explicit merge-base or path manifest for the current unique remainder.
- red-test: judgment-only.

## Notes

### GATE

- HEAD = `c8f308c95a9c74f6ee95d33c671b7b05878a7110`; worktree was clean before the run. `git diff --exit-code -- src tests pyproject.toml` after the run returned rc=0. The cited coverage run was not edited through.
- Exact environment: `cd /home/eturkes/Projects/figure-verification/.scratch/worktrees/audit-m9 && export UV_PROJECT_ENVIRONMENT=/home/eturkes/Projects/figure-verification/.venv UV_LINK_MODE=copy PYTHONPATH=/home/eturkes/Projects/figure-verification/.scratch/worktrees/audit-m9/src COVERAGE_FILE=/home/eturkes/Projects/figure-verification/.scratch/worktrees/audit-m9/.coverage`.
- `uv run --no-sync --locked ruff format --check .` → rc=0; output tail empty.
- `uv run --no-sync --locked ruff check .` → rc=0; output tail empty.
- `uv run --no-sync --locked mypy` → rc=0; tail `Success: no issues found in 131 source files`.
- `uv run --no-sync --locked pytest -p no:cacheprovider` → rc=0; tail `2900 passed, 8 warnings in 171.23s`; coverage `6801` statements, `1406` branches, `0` missed, `100.00%`.
- With the worktree venv first on `PATH` and worktree `src` on `PYTHONPATH`, `python -m demo` → rc=0, `13/13 scenarios PASS`; `python -m demo.e2e` → rc=0, `4/4 cases PASS`; `python -m demo.formula_walkthrough` → rc=0, `5/5 scenarios PASS`.

### COUNTS

- REPRODUCED — formula policy has 12 M9 limits: 11 `max_formula_*` fields plus `max_matplotlib_script_bytes`.
- REPRODUCED — `_CHECK_METHODS` commit deltas are 18 at `8fcaef5`, 4 at `f4af5a0`, and 6 at `d8ca58d`; all exact added-ID sets were AST-derived.
- REPRODUCED — real f02 chain emits 13 certified checks over exactly `{construction, deterministic_recompute, z3_smt}`.
- REPRODUCED — corpus = f01–f06 (`6`) and fb01–fb20 (`20`).
- REPRODUCED — `BlobKind` widened `17→19` by `FORMULA_SOURCE` + `MATPLOTLIB_SCRIPT`; `PlotRole` widened `9→11`; `_SCHEMA_VERSION=4`; archive DDL has six `REFERENCES blobs(digest, kind)` tables.
- REPRODUCED — current route inventory has nine surfaces. M9.8a commit `ffd9624` owns four policy maps (`3` archive + old `_ROUTE_ATTACHES_PLOT`). Current descendants are five after the attach-map split; the literal current route-keyed dict count is six when the pre-existing replay `_EXPECTED_MODEL_ROLES` mirror is included.
- REPRODUCED — five `_PLOT_ROLE_FIELDS_BY_SOURCE[...]` totality sites; ratified M9.9 contract has 14 layer-matrix rows.
- REPRODUCED — dataset `_SCENARIOS=13`; formula `_FORMULA_SCENARIOS=5`; formula registry commit delta `3→5`; aggregator calls three archive-integrity guards; four dedicated hardening tests cover audit CLI + each guard.
- REPRODUCED — `VPlot_SEMANTICS.md` has 21 `###` sections: 12 dataset (`§1`–`§11` + `Settled decisions`) and 9 formula (`§F1`–`§F9`).
- REPRODUCED — M9.9 static statement delta `391→627 = +236`; M9.12b OpenAPI `+157/−0` lines. DRIFTED — M9.13c is `+100` net statements, while `+103` is its gross-addition count; see F2.
- UNREPRODUCIBLE — M9.3's 64,480/11,513 oracle campaign lacks a retained executable axis inventory; see F4.
- REPRODUCED — the 23-row M9.13e source table classifies `NO-EDIT 11 · REPAIR 7 · PLACE 5`.
- REPRODUCED at archived close — five numbered false-claim corrections and the 25-row disposition `21 applied + 1 partial + 3 declined`. DRIFTED against the current retained report — 26 rows; see F3.
- REPRODUCED — parser hard ceilings `64/64/512`; default AST depth `32`; a 32-term flat sum admits at depth 32 with 63 tokens, while term 33 spends 65 tokens and raises `resource.formula_ast_depth` at position 64.
- REPRODUCED — joint parser profiler reports 267 active calls at `(32,32)` and 523 at `(64,64)`.
- REPRODUCED — work tariff is `5 + AST tariff` per admitted sample; every node costs 1 and `Pow` adds `abs(exponent)`. Direct 11-sample calls return `x=66` and `x+x=88`.
- Replayer: `/home/eturkes/Projects/figure-verification/.scratch/worktrees/audit-m9/audit_m9/rederive_counts.py`.

### HASHES

- REPRODUCED — `schema/vplot-formula-0.1.schema.json` = `3024 B`, full `sha256:62d0a6b804c3fbddeec5918adcbdbc8eaa3be8d79d4adfc546636111a8eace55`.
- REPRODUCED — `GRAMMAR_VERSION="expr-0.1"`; `SCRIPT_TEMPLATE_VERSION="matplotlib-script-0.1"`; `VCERT_V03_PAYLOAD_TYPE="application/vnd.figure-verification.vcert.v0.3+json"`.
- REPRODUCED — v0.2 compatibility against `b6c8161^`: independently rendered current/parent payloads and fixed-key envelopes each compare equal (`cmp` rc=0). DRIFTED wording — only five core source nodes moved byte-exact; see F5.
- REPRODUCED — the R8 sentence is 93 bytes after syntax framing is removed; extracted code/`POC_SCOPE.md`/`README.md` copies compare equal (`cmp` rc=0 twice), with exactly three tracked occurrences.
- REPRODUCED — injected-TCB vectors run on CPython 3.13.5 (`49 passed`). DRIFTED — the exact full second-interpreter recipe fails two later live-TCB ceiling tests; see F6.
- REPRODUCED — `PYTHONPATH=$PWD/tests uv run --locked python tests/regenerate_vcert_vectors.py` ran twice. Each run returned rc=0 and left `tests/vcert_v03_vectors.json` diff-clean. Both emitted f02/f06 `1847 B` digests `8ebacb571133365af951ddc435f0d80765ce560235ba7a8253ea5121c28e5905` / `b53126d857b573e7e25d8e0e588da58945848f77dfd61c0bcb0ec66ac59c81a6`; the `synthetic_*` projection hash stayed `31b5b3fcc6a50d5232d4213364133ff5bcbc81d17b0814f610864782939dade5` before, between, and after runs.
- Replayers: `/home/eturkes/Projects/figure-verification/.scratch/worktrees/audit-m9/audit_m9/rederive_hashes.py`; `/home/eturkes/Projects/figure-verification/.scratch/worktrees/audit-m9/audit_m9/rederive_py3135.sh`.

### SIZES

- REPRODUCED from commit `9a1fb39` — roadmap `170,444→30,870 B`; memory `84,033→29,125 B`; combined `59,995 B`; reference `23,951 B`; archive M9 `243,475 B`. UNREPRODUCIBLE — transient promotion total `287,738 B`; see F7.
- CURRENT `wc -c` equivalent:

| file | bytes |
|---|---:|
| `.agent/roadmap.md` | 38,901 |
| `.agent/memory.md` | 30,472 |
| `.agent/polish.md` | 39,935 |
| `.agent/reference.md` | 32,581 |
| `.agent/archive/closed-milestones.md` | 2,041 |
| `.agent/archive/m1.md` | 703 |
| `.agent/archive/m2.md` | 1,557 |
| `.agent/archive/m3.md` | 11,770 |
| `.agent/archive/m4.md` | 16,306 |
| `.agent/archive/m5.md` | 3,554 |
| `.agent/archive/m6.md` | 2,286 |
| `.agent/archive/m7.md` | 2,661 |
| `.agent/archive/m8.md` | 10,272 |
| `.agent/archive/m9.md` | 268,782 |
| **all `.agent/**/*.md`** | **461,821** |

- DRIFTED — roadmap's unqualified M9.12c snapshot values are not current; see F8.
- REPRODUCED — `VPlot_SEMANTICS.md` = `18,512→46,749 B`; HEAD remains `46,749 B`.
- REPRODUCED — f02 emits a 483-byte script before a 482-byte ceiling raises `resource.matplotlib_script_bytes`; observer saw exactly one constructed script and the exception message named 483.
- Replayer: `/home/eturkes/Projects/figure-verification/.scratch/worktrees/audit-m9/audit_m9/rederive_sizes.py`.

### GAUGES

- Every numeric cell below is REPRODUCED as an exact extraction of the current archive text. Every historical measurement behind those cells is UNREPRODUCIBLE as an independent past-window reading; see F13.
- `—` means that the archive records no value for that field. Phase-qualified cells preserve separate prep and implementation windows rather than combining them.

| unit | main | mate | impl | notes |
|---|---|---|---|---|
| M9.1 | 55% | — | 77% | delegated-era record; no K readings |
| M9.2 | 44% | — | 100% | implementation crossed the 240K boundary during fix pass 2; recorded peak 239K |
| M9.3 | 100% 241K/240K | — | 53% 128K/240K | four sessions; three died mid-unit; high-water basis |
| M9.4a | 71% 171K/240K | — | 65% 156K/240K | — |
| M9.4b | 45% 109K/240K | — | 94% 226K/240K | — |
| M9.5 | 82% 197K/240K | — | 92% 220K/240K | — |
| M9.6a | 98% 236K/240K | — | 70% 167K/240K | fix ≈75% |
| M9.6b | >1 window; peak 240,410; successor 74% 178K/240K | 90% 215K/240K | — | explicit post-compaction classification |
| M9.7 | — | — | — | split umbrella, not a delivered unit |
| M9.7a | implementation 64% 154K/240K; prep 80% 192K/240K | prep 87% 209K/240K | — | implementation was MAIN-solo |
| M9.7b | — | — | — | split umbrella, not a delivered unit |
| M9.7b-1 | 68% 164K/240K | 42% 101K/240K | — | — |
| M9.7p | 87% 210K/240K | 96% 229K/240K | — | — |
| M9.7b-2 | prep 75% 180K/240K; implementation 93% 223K/240K | prep 53% 127K/240K; implementation 98% 236K/240K | — | — |
| M9.8 | — | — | — | split umbrella, not a delivered unit |
| M9.8a | 94% 226K/240K | 99% 238K/240K | — | — |
| M9.8b | prep-1 85% 204K/240K; prep-2 93% 223K/240K; implementation 90% 215K/240K | prep-1 91% 219K/240K; prep-2 99% 237K/240K; implementation 100% 239K/240K | — | — |
| M9.9 | prep 85% 205K/240K; implementation 87% 208K/240K | prep 96% 230K/240K; implementation 95% 228K/240K | — | secondary peaks: scout prep 92% 222K; test implementation 93% 223K |
| M9.10 | prep MISSING; implementation 95% 229K/240K | prep 87% 208K/240K; implementation 99% 237K/240K | — | prep map secondary 84% 203K; see F12 |
| M9.11 | prep 96% 230K/240K; implementation 95% 229K/240K | prep 99% 238K/240K; implementation 100% 240K/240K | — | implementation crossed one boundary at close; successor spent ≈20%; see F10 |
| M9.12 | prep 83% 198K/240K | prep 96% 230K/240K | — | planning/split umbrella; scout 90%, successor map 63% |
| M9.12a | 94% 226K/240K | 96% 230K/240K | — | nested under M9.12; only M9.12b retrospectively marks it >1 window |
| M9.12b | >1 window; successor 55% 131K/240K; intermediate 92% 222K/240K | 96% 231K/240K | — | explicit post-compaction classification |
| M9.12c | archive MISSING; roadmap-only 100% 239K/240K | archive MISSING; roadmap-only 89% 214K/240K | — | roadmap classifies >1 window; see F9 |
| M9.13a | 97% 234K/240K | 68% 162K/240K | — | — |
| M9.13b | >1 window | 59% 143K/240K | — | explicit compaction boundary |
| M9.13c | 84% 202K/240K | 68% 163K/240K | — | prep ran concurrently with implementation |
| M9.13d | >1 window; closing 52% 125K/240K | 87% 209K/240K | — | chained across one boundary; true MAIN cost ≈1.6 windows |
| M9.13e | >1 window; closing 53% 126K/240K | 82% 196K/240K | — | chained across one boundary; true MAIN cost ≈1.5 windows |

- REPRODUCED — no raw M9.6b, M9.12a, M9.12b, or M9.12c reading is used as a valid fit after its explicit/retrospective `>1 window` classification. DRIFTED — M9.11 is used as a 95% fit despite the same boundary condition; see F10.
- DRIFTED — the live four-unit over-window index predates M9.13b/M9.13d/M9.13e and conflicts with M9.11; see F11.
- MISSING classifications are limited to delivered records: M9.10's prep MAIN number and M9.12c's whole archive body. Gauge-free M9.7/M9.7b/M9.8 headings are split umbrellas, not delivered units.

### BRANCHES

- REPRODUCED — all eight retained branch tips resolve exactly:

| branch | recorded tip | current tip | retained artifact evidence |
|---|---|---|---|
| `wt/scout-m9u11` | `c0022de` | `c0022de` | 33 branch-only paths; 6 parseable probe scripts (30,670 B) + 9 SQLite probe archives (634,880 B) |
| `wt/map-m9u12` | `f851789` | `f851789` | 24 branch-only paths; `measure_static.py`/JSON + 22 parseable generated Python files |
| `wt/scout-m9u12` | `1635d3c` | `1635d3c` | 9 parseable P01–P09 scripts (54,126 B) + the 3024-byte formula schema |
| `wt/rev-m9u12` | `53b898b` | `53b898b` | 10,677-byte review matrix + parseable 7,117-byte contract-review test; both absent from main |
| `wt/test-m9u7b2` | `54fe1d4` | `54fe1d4` | 5 parseable test files, all byte-different from main; branch-only merge-base diff `+1611/−22` |
| `wt/test-m9u10` | `845d49f` | `845d49f` | retained route suite differs from main, has 40 `test_` definitions, and collects 55 items; current merged suite has 28 definitions |
| `wt/rev-m9u10` | `a1171dc` | `a1171dc` | 4 parseable review tests; F22's `test_m9u10_formula_openapi.py` is absent from main and reachability twin differs |
| `wt/test-m9u13a` | `6c1bd49` | `6c1bd49` | one byte-different test file; exact scratch copy confirmed below |

- REPRODUCED — every retained branch still owns unique tracked content: branch-only absent/different-vs-main path counts are respectively `33/24/10/2/5/1/2/1`; no stated retention justification has become empty.
- REPRODUCED — `.scratch/agents/test-m9u13a-suite.py` exists and is byte-identical to `wt/test-m9u13a:tests/test_formula_e2e_hardening.py`: `13,270 B`, full `sha256:4beb4b7806a96fb2d0695186f95dba2478a88856e57c1f8d14dd3b149c1ef615` on both sides.
- REPRODUCED — `refs/heads/wt/orc-m9u7a` verification returns rc=1 with empty stdout/stderr. `git rev-list --all --objects` has zero reachable paths ending `differential.py`, `oracle_corpus.py`, or `oracle_migrate_v4.py`; positive controls resolve `wt/scout-m9u11` at `c0022de` and find reachable `.probe/p01.py`. The lost commit SHA is not recorded, so the proof covers the branch ref and every named artifact path, not unidentified dangling objects.
- REPRODUCED with a dynamic exclusion — after the eight retained branches and the brief's eight review-wave branches (`wt/audit-m9`, `wt/rev-m9-1`…`-6`, `wt/xcut-m9`), the sole extra `wt/*` ref is active current-wave `wt/res-port`. It has an attached worktree, equals `main` at `c8f308c`, and is zero commits ahead; it is not a retained M9 artifact branch.
- DRIFTED — p8's unpinned `main..wt/test-m9u7b2` stat no longer describes the remainder; see F14. The recorded `11 files, +565/−318` does reproduce at `35397e0^..54fe1d4`.
- Coverage limit: branch verification checked refs, tree uniqueness, sizes, Python syntax, one 55-item collection, and the exact M9.13a copy. It did not execute every historical probe or old branch suite against its original dependency state.

