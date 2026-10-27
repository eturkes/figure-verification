# reviewer-3 — Q4 mutation-credit rulings

## Fixed check set + contracts

Target = 1,680 seeded `(mutant,node)` rows, nodes 4 + 5 only. Check = mutation behavior against the owning node's contract; `specified` = detection required, `open` = outside that contract or equivalent for it. Contract sources read before candidate adjudication. Tracked targets read-only; base `66c3fe9e054fb3c3abc5424dc62120efc290bfcf`.

- **Node 4 / R272 / UTC control.** A timezone-aware line whose axis carries UTC keeps each plotted position's calendar date/time, without an offset suffix, and an otherwise honest line over matching `date,value` CSV rows passes. Neither matching tick locations nor a UTC rcParams default is a precondition. This zero-offset member does not specify every other integrity/CSV-profile rule that `judge` reaches. Sources: `tests/test_figure_reader.py:1062-1088` (`_zoned`, parametrization, assertions); `.agent/review.md:173`; `src/verifier/figure/reader.py:806-825`, `837-890`, `893-912`; `.claude/rules/figure.md` Values/date-key clause.
- **Node 5 / R271 / drift guard.** Every declared reader slot decodes in its matching owner: axes = `xlim ylim xscale yscale xinvert yinvert xticks yticks twin inset legend`; axis = `ticks invert style`. Successful decoding means the owner and `(slot,line,clock)` tuple survive, not merely a non-None outer `Description` containing missing owners/fields. Source-line capture and clock ordering at the reader are separate contracts; preserving an already-recorded integer clock is this decoder contract. Unknown-slot refusal belongs to the negative sibling tests. Sources: `tests/test_figure_description.py:253-278`; `.agent/review.md:172`; `src/verifier/figure/description.py:27-33`, `369-380`, `672-691`, `728-746`; reader maps `src/verifier/figure/reader.py:55-85`.

## Verdict table

| node | verdict | rows | specified | open | never-executed class ruling |
|---|---|---:|---:|---:|---|
| 4 | finding — detail ids below | 1296 | 9 | 1287 | open — 4233; see class ruling |
| 5 | finding — detail ids below | 384 | 19 | 365 | open — 1243; see class ruling |

28 specified rows: 27 observed existing-test kills; 1 uncovered among inspected pins. Each is a **minor** mutation-credit detection gap, not a demonstrated bug in the unmutated production implementation.

### Never-executed class rulings

- **Node 4: open, 4,233 = 5,529 − 1,296.** Class = the unexercised alternatives of the 27-file scope: Period/other converter paths, other mark families, invalid input/refusal and additional value vocabularies. The UTC-aware honest-line control does not own their independent contracts. Date code inspection confirms UTC-bearing valid datetime positions use `_date`'s matplotlib arm; its Period/error arms do not supply that reading. Counts = `git show -s --format=fuller 7b61aa2`; off-executed mutants were not individually reproduced or reconstructed, as the brief requests one class ruling.
- **Node 5: open, 1,243 = 1,627 − 384.** Class = unexercised reader branches + alternate geometry/error/negative-shape decoder branches. The declared axes/axis vocabularies and positive `_calls` route are in the executed scope; other families and malformed-input refusals belong to other tests. Counts from the same commit; no individual off-executed mutant replay.

## Checked bulk predicates

All rows retain header/order/key/operator/node/mutated bytes; only `ruling` + `reason` change. No sampling of the 1,680 rows. Bulk routing uses exact `(node,file,line,operator)` predicates, with the candidate exceptions below applied first. AST containing-function names/ranges are included in every open-row reason; location inventory + source module docstrings establish the independent behavior. Date/call reach was checked through the full relevant implementations, not guessed from filenames.

1. **Specified node 4:** `reader.py` lines 820/821 with `FuncCall`; 865 `FuncCall`; 866 `AugAssign` (2); 898 `DictArray`; 899 `Compare`/`String`; 900 `AugAssign`. `_date:806-825` must thread UTC units despite another rc default; `_axis:837-890` + `_positions:893-912` must retain plotted coordinates not coinciding with ticks. Every predicate probed red below.
2. **Specified node 5:** `description.py` lines 304/330 `Return`; 338/380/674/730/756 `Return` + `FuncCall`; all 7 surviving expressions on line 373. `_int`, `_choice`, `_tuple`, `_call`, `_calls`, `_axis`, `_axes`, `_figure` erase/corrupt the admitted call tuple or its owner. Every predicate probed red below.
3. **Equivalent-for-contract:** source statement contains `: TypeAlias =`; a `String` mutant in `cast(...)`'s type argument; `description.py:16` type variable. Read aliases/casts in their containing source statements; these type expressions do not decide either date facts or call admission. This is runtime contract equivalence on the tested CPython 3.14 run, not a type-checker claim.
4. **Dataclass options:** `Keyword` on source `@dataclass(...)`: frozen/slots representation policy is independent of these observed date facts and decoded slot tuples. Not called globally equivalent.
5. **Node 5 remaining reader rows:** `reader.py:37-1157` outside changed declared slot values (none survive this node): capture/hook lifecycle, site/clock production, geometry facts, limits, text and transport. Maps `55-85`, hooks `241-306`, install `487-507`, serialized maps `837-890`/`979-1032` read; slot source values come from the maps/`_STYLE`, while the node injects already-recorded maps to test decoding. Actual hook-recording correctness stays outside this decoder drift guard.
6. **Node 4 remaining reader rows:** exact inclusive range predicates:

| source range | outside-node behavior |
|---|---|
| `reader.py:1-99` | reader metadata/caps/other family constants |
| `reader.py:100-179` | capture lifecycle/caps/glyph accounting and hook-holder state |
| `reader.py:180-208` | program-site/origin frame tracing |
| `reader.py:209-218` | non-finite-number transport |
| `reader.py:235-507` | call-site clocks/recording and other artist input hooks |
| `reader.py:510-533` | hook version/reuse lifecycle |
| `reader.py:541-557` | text limits/visibility |
| `reader.py:560-604` | artist transform/line budget facts |
| `reader.py:742-789` | artist geometry dispatch/visibility/clipping |
| `reader.py:792-803` | other/missing converter recognition (valid matplotlib date converter unchanged) |
| `reader.py:806-825` | Period or non-timezone-unit path (outside this UTC-aware node) |
| `reader.py:828-890` | tick/formatter/category/offset facts (plotted date-position path unchanged) |
| `reader.py:893-912` | other geometry position extraction |
| `reader.py:979-1075` | containers/pies/colorbars/figure child census |
| `reader.py:1088-1137` | renderer lifecycle/environment/output/glyph accounting |
| `reader.py:1140-1157` | PNG/JSON transport and resource bounds |

7. **Remaining decoder rows:** node 4 = other fields/word sets/negative-shape checks; its valid date-map/ISO decoding path is unchanged. Node 5 = non-call geometry/fields or malformed-input checks; e.g. `_choice:327-330` OR→AND widens admission, but valid slots still decode, so the negative R271 tests own it. The 19 call-preservation exceptions prevent accepting erased tuple/owner mutants as merely irrelevant.
8. **Node 4 other modules:** complete per-module routing below; each row records its actual containing function/range. `rg` across `src/verifier` for `tzinfo|num2date|_date\(|\.dates|key\.date|_DATE_MODULES` identifies the UTC path in reader + date consumers in keys/explain/ticks/description; those functions read in full. The surviving key/explain date guards change missing/invalid-key paths, not valid UTC dates; numeric/category/tick-label contracts are separate.

| module | outside-node behavior |
|---|---|
| `src/verifier/__init__.py` (1) | package version metadata |
| `src/verifier/figure/anchoring.py` (82) | lexical column naming/negation/aliases, not UTC calendar conversion |
| `src/verifier/figure/axes_rules.py` (48) | integrity rules and display-site selection, not UTC calendar conversion |
| `src/verifier/figure/columns.py` (27) | request/label column anchoring, not UTC calendar conversion |
| `src/verifier/figure/computed.py` (11) | admitted arithmetic vocabulary, not raw date-key conversion |
| `src/verifier/figure/explain.py` (139) | value explanations, pairing/reduction/selection, not reader UTC conversion |
| `src/verifier/figure/inert.py` (47) | publication text escaping, not date facts |
| `src/verifier/figure/interpret.py` (60) | publication prose, not date facts or the pass verdict |
| `src/verifier/figure/judge.py` (45) | other integrity/refusal dispatch and publication metadata, not UTC conversion |
| `src/verifier/figure/keys.py` (18) | numeric/category keys and missing-date fallback, not a valid UTC date reading |
| `src/verifier/figure/legends.py` (9) | legend naming/encoding, not date positions |
| `src/verifier/figure/mark_rules.py` (53) | mark integrity, not UTC calendar facts |
| `src/verifier/figure/parts.py` (77) | artist-family admission, not UTC calendar facts |
| `src/verifier/figure/reasons.py` (5) | reason taxonomy/error representation, not UTC calendar facts |
| `src/verifier/figure/request.py` (11) | typed request parsing, not CSV date-key conversion |
| `src/verifier/figure/series.py` (35) | series family/name/channel dispatch, not UTC calendar conversion |
| `src/verifier/figure/shapes.py` (23) | other mark geometry/colour/label facts, not UTC calendar conversion |
| `src/verifier/figure/sources.py` (14) | CSV profile classification/row metadata, not the axis timezone |
| `src/verifier/figure/ticks.py` (68) | tick-label integrity/formatting, not plotted date-key conversion |
| `src/verifier/pysrc/aggregate.py` (61) | group reduction/dtype rules, not raw UTC date conversion |
| `src/verifier/pysrc/budget.py` (17) | work admission, not date facts |
| `src/verifier/pysrc/csvread.py` (94) | CSV lexical/profile/bounds rules, not UTC date conversion |
| `src/verifier/pysrc/errors.py` (1) | CSV refusal exception vocabulary, not date conversion |
| `src/verifier/pysrc/limits.py` (17) | CSV work/size limits, not date facts |
| `src/verifier/pysrc/table.py` (1) | cell typing, not date conversion |

## Evidence protocol

- Import canary printed `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/verifier/__init__.py`.
- Mutation target = copied source only. Driver `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-mutation-probes.py`: prove changed bytes + parse, run each probe in a fresh `python -B`, restore in `finally`, byte-compare restored copy to source. Both mutated files restored; final equality check `True` for reader + description.
- Baseline `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-probes.py`: `3 passed`, rc 0. Initial harness collection attempt imported `Passed` from the wrong module, rc 2; corrected to `verifier.figure.judge`, then baseline green. That failed setup is not a mutation kill.
- Existing baseline: R272[0], R272[9], date edge-position test, P1 call-recording test, R271 drift guard = `5 passed`, rc 0.
- Per mutant command prefix (cwd = repo root): `PYTHONPATH=.scratch/agents/q4/reviewer-3-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy PYTHONDONTWRITEBYTECODE=1 uv run --no-sync --locked python -B -m pytest -q --no-cov -p no:cacheprovider -x`. Each detail names the test suffix + rc + failing output. Run inventory `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-probe-results.json`; full logs `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-<row>-{probe,existing}.log`.
- Evidence archived from `/tmp/reviewer-3-*` to `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/`; original test command suffixes below preserve the executed `/tmp` paths. For rerun, use the archived test path; its fixture path alone was relocated. `/tmp` task files removed.
- Probe inputs: UTC tests = dates `2026-01-01T01:23`, `2026-01-02T02:34` (second line `03:45`/`04:56`) and matching CSV; zone test sets `plt.rcParams["timezone"]="Asia/Tokyo"` while axis data carry UTC. Slot test = pristine reader description with each axes slot `[2,1]` and each x/y axis slot `[4,3]`; assert exact owner tuples. Source `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-probes.py`; raw fixture `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-raw.json` generated by the unmutated copied reader.

## Specified row details

### src/verifier/figure/description.py:304:4 node 5 — row 322, Return

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone — valid call tuples must survive decoding in their owner.

- Mutated text: `return None`.
- Contract + kill sketch: A valid recorded slot must reach its decoded owner unchanged; mutation erases the owner/tuple or changes a tuple field. Outer non-None alone does not show successful slot decoding.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_slots_reach_their_decoded_owner`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-322-probe.log`.
```text
E       AssertionError: (('xlim', None, None), ('ylim', None, None), ('xscale', None, None), ('yscale', None, None), ('xinvert', None, None), ('yinvert', None, None), ...)
E       assert (('xlim', Non...e, None), ...) == (('xlim', 2, ...', 2, 1), ...)
```
- Existing kill: `tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-322-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       AssertionError: assert {'xinvert': N... 'ylim': None} == {'xinvert': 5, 'ylim': 4}
E         
```

### src/verifier/figure/description.py:330:4 node 5 — row 330, Return

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone — valid call tuples must survive decoding in their owner.

- Mutated text: `return None`.
- Contract + kill sketch: A valid recorded slot must reach its decoded owner unchanged; mutation erases the owner/tuple or changes a tuple field. Outer non-None alone does not show successful slot decoding.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_slots_reach_their_decoded_owner`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-330-probe.log`.
```text
E       AssertionError: ((None, 2, 1), (None, 2, 1), (None, 2, 1), (None, 2, 1), (None, 2, 1), (None, 2, 1), ...)
E       assert ((None, 2, 1)...e, 2, 1), ...) == (('xlim', 2, ...', 2, 1), ...)
```
- Existing kill: `tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-330-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       AssertionError: assert {None: 4} == {'xinvert': 5, 'ylim': 4}
E         
```

### src/verifier/figure/description.py:338:4 node 5 — row 334, Return

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone — valid call tuples must survive decoding in their owner.

- Mutated text: `return None`.
- Contract + kill sketch: A valid recorded slot must reach its decoded owner unchanged; mutation erases the owner/tuple or changes a tuple field. Outer non-None alone does not show successful slot decoding.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_slots_reach_their_decoded_owner`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-334-probe.log`.
```text
E       AssertionError: assert None is not None
E        +  where None = Description(version='figure-description/2', error=None, too_large=False, glyphs=0, figures=None).figures
```
- Existing kill: `tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-334-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       TypeError: 'NoneType' object is not subscriptable
```

### src/verifier/figure/description.py:338:11 node 5 — row 335, FuncCall

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone — valid call tuples must survive decoding in their owner.

- Mutated text: `return None`.
- Contract + kill sketch: A valid recorded slot must reach its decoded owner unchanged; mutation erases the owner/tuple or changes a tuple field. Outer non-None alone does not show successful slot decoding.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_slots_reach_their_decoded_owner`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-335-probe.log`.
```text
E       AssertionError: assert None is not None
E        +  where None = Description(version='figure-description/2', error=None, too_large=False, glyphs=0, figures=None).figures
```
- Existing kill: `tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-335-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       TypeError: 'NoneType' object is not subscriptable
```

### src/verifier/figure/description.py:373:4 node 5 — row 349, Return

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone — valid call tuples must survive decoding in their owner.

- Mutated text: `return None`.
- Contract + kill sketch: A valid recorded slot must reach its decoded owner unchanged; mutation erases the owner/tuple or changes a tuple field. Outer non-None alone does not show successful slot decoding.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_slots_reach_their_decoded_owner`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-349-probe.log`.
```text
E       AssertionError: (None, None, None, None, None, None, ...)
E       assert (None, None, ...ne, None, ...) == (('xlim', 2, ...', 2, 1), ...)
```
- Existing kill: `tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-349-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       TypeError: cannot unpack non-iterable NoneType object
```

### src/verifier/figure/description.py:373:11 node 5 — row 351, FuncCall

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone — valid call tuples must survive decoding in their owner.

- Mutated text: `return None, _int(items[0]), _int(items[1])`.
- Contract + kill sketch: A valid recorded slot must reach its decoded owner unchanged; mutation erases the owner/tuple or changes a tuple field. Outer non-None alone does not show successful slot decoding.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_slots_reach_their_decoded_owner`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-351-probe.log`.
```text
E       AssertionError: ((None, 2, 1), (None, 2, 1), (None, 2, 1), (None, 2, 1), (None, 2, 1), (None, 2, 1), ...)
E       assert ((None, 2, 1)...e, 2, 1), ...) == (('xlim', 2, ...', 2, 1), ...)
```
- Existing kill: `tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-351-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       AssertionError: assert {None: 4} == {'xinvert': 5, 'ylim': 4}
E         
```

### src/verifier/figure/description.py:373:32 node 5 — row 353, FuncCall

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone — valid call tuples must survive decoding in their owner.

- Mutated text: `return _choice(key, slots), None, _int(items[1])`.
- Contract + kill sketch: A valid recorded slot must reach its decoded owner unchanged; mutation erases the owner/tuple or changes a tuple field. Outer non-None alone does not show successful slot decoding.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_slots_reach_their_decoded_owner`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-353-probe.log`.
```text
E       AssertionError: (('xlim', None, 1), ('ylim', None, 1), ('xscale', None, 1), ('yscale', None, 1), ('xinvert', None, 1), ('yinvert', None, 1), ...)
E       assert (('xlim', Non...None, 1), ...) == (('xlim', 2, ...', 2, 1), ...)
```
- Existing kill: `tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-353-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       AssertionError: assert {'xinvert': N... 'ylim': None} == {'xinvert': 5, 'ylim': 4}
E         
```

### src/verifier/figure/description.py:373:43 node 5 — row 355, Number

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone — valid call tuples must survive decoding in their owner.

- Mutated text: `return _choice(key, slots), _int(items[-1]), _int(items[1])`.
- Contract + kill sketch: A valid recorded slot must reach its decoded owner unchanged; mutation erases the owner/tuple or changes a tuple field. Outer non-None alone does not show successful slot decoding.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_slots_reach_their_decoded_owner`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-355-probe.log`.
```text
E       AssertionError: (('xlim', 1, 1), ('ylim', 1, 1), ('xscale', 1, 1), ('yscale', 1, 1), ('xinvert', 1, 1), ('yinvert', 1, 1), ...)
E       assert (('xlim', 1, ...', 1, 1), ...) == (('xlim', 2, ...', 2, 1), ...)
```
- Existing kill: `tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-355-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       AssertionError: assert {'xinvert': 1, 'ylim': 0} == {'xinvert': 5, 'ylim': 4}
E         
```

### src/verifier/figure/description.py:373:43 node 5 — row 357, Number

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone — valid call tuples must survive decoding in their owner.

- Mutated text: `return _choice(key, slots), _int(items[1]), _int(items[1])`.
- Contract + kill sketch: A valid recorded slot must reach its decoded owner unchanged; mutation erases the owner/tuple or changes a tuple field. Outer non-None alone does not show successful slot decoding.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_slots_reach_their_decoded_owner`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-357-probe.log`.
```text
E       AssertionError: (('xlim', 1, 1), ('ylim', 1, 1), ('xscale', 1, 1), ('yscale', 1, 1), ('xinvert', 1, 1), ('yinvert', 1, 1), ...)
E       assert (('xlim', 1, ...', 1, 1), ...) == (('xlim', 2, ...', 2, 1), ...)
```
- Existing kill: `tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-357-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       AssertionError: assert {'xinvert': 1, 'ylim': 0} == {'xinvert': 5, 'ylim': 4}
E         
```

### src/verifier/figure/description.py:373:48 node 5 — row 359, FuncCall

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone — valid call tuples must survive decoding in their owner.

- Mutated text: `return _choice(key, slots), _int(items[0]), None`.
- Contract + kill sketch: A valid recorded slot must reach its decoded owner unchanged; mutation erases the owner/tuple or changes a tuple field. Outer non-None alone does not show successful slot decoding.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_slots_reach_their_decoded_owner`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-359-probe.log`.
```text
E       AssertionError: (('xlim', 2, None), ('ylim', 2, None), ('xscale', 2, None), ('yscale', 2, None), ('xinvert', 2, None), ('yinvert', 2, None), ...)
E       assert (('xlim', 2, ...2, None), ...) == (('xlim', 2, ...', 2, 1), ...)
```
- Existing kill: `tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-359-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       TypeError: '<' not supported between instances of 'NoneType' and 'NoneType'
```

### src/verifier/figure/description.py:373:59 node 5 — row 361, Number

**Severity:** minor. specified: uncovered — decoded call clock becomes source line; same outer Description still passes — valid call tuples must survive decoding in their owner.

- Mutated text: `return _choice(key, slots), _int(items[0]), _int(items[0])`.
- Contract + kill sketch: A valid recorded slot must reach its decoded owner unchanged; mutation erases the owner/tuple or changes a tuple field. Outer non-None alone does not show successful slot decoding.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_slots_reach_their_decoded_owner`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-361-probe.log`.
```text
E       AssertionError: (('xlim', 2, 2), ('ylim', 2, 2), ('xscale', 2, 2), ('yscale', 2, 2), ('xinvert', 2, 2), ('yinvert', 2, 2), ...)
E       assert (('xlim', 2, ...', 2, 2), ...) == (('xlim', 2, ...', 2, 1), ...)
```
- Existing P1 candidate passed (rc 0): its source lines increase with call order, masking line-as-clock. No full-suite mutant run performed; another existing kill remains unconfirmed. Add exact decoded tuple equality to the R271 drift guard to detect this directly.

### src/verifier/figure/description.py:380:4 node 5 — row 363, Return

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone — valid call tuples must survive decoding in their owner.

- Mutated text: `return None`.
- Contract + kill sketch: A valid recorded slot must reach its decoded owner unchanged; mutation erases the owner/tuple or changes a tuple field. Outer non-None alone does not show successful slot decoding.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_slots_reach_their_decoded_owner`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-363-probe.log`.
```text
E       AssertionError: None
E       assert None == (('xlim', 2, 1), ('ylim', 2, 1), ('xscale', 2, 1), ('yscale', 2, 1), ('xinvert', 2, 1), ('yinvert', 2, 1), ...)
```
- Existing kill: `tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-363-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       TypeError: 'NoneType' object is not iterable
```

### src/verifier/figure/description.py:380:11 node 5 — row 365, FuncCall

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone — valid call tuples must survive decoding in their owner.

- Mutated text: `return None`.
- Contract + kill sketch: A valid recorded slot must reach its decoded owner unchanged; mutation erases the owner/tuple or changes a tuple field. Outer non-None alone does not show successful slot decoding.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_slots_reach_their_decoded_owner`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-365-probe.log`.
```text
E       AssertionError: None
E       assert None == (('xlim', 2, 1), ('ylim', 2, 1), ('xscale', 2, 1), ('yscale', 2, 1), ('xinvert', 2, 1), ('yinvert', 2, 1), ...)
```
- Existing kill: `tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-365-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       TypeError: 'NoneType' object is not iterable
```

### src/verifier/figure/description.py:674:4 node 5 — row 379, Return

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone — valid call tuples must survive decoding in their owner.

- Mutated text: `return None`.
- Contract + kill sketch: A valid recorded slot must reach its decoded owner unchanged; mutation erases the owner/tuple or changes a tuple field. Outer non-None alone does not show successful slot decoding.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_slots_reach_their_decoded_owner`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-379-probe.log`.
```text
E       AssertionError: assert (None is not None)
E        +  where None = Axes(cls='Axes', site=2, visible=True, position=(0.125, 0.10999999999999999, 0.9, 0.88), colorbar_of=None, shared_x=()...0), marker_edge_width=1.0, marker_filled=False, markevery=False, dash_on=None)),), containers=(), pies=(), legend=None).x
```
- Existing kill: `tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-379-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       AttributeError: 'NoneType' object has no attribute 'calls'
```

### src/verifier/figure/description.py:674:11 node 5 — row 380, FuncCall

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone — valid call tuples must survive decoding in their owner.

- Mutated text: `return None`.
- Contract + kill sketch: A valid recorded slot must reach its decoded owner unchanged; mutation erases the owner/tuple or changes a tuple field. Outer non-None alone does not show successful slot decoding.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_slots_reach_their_decoded_owner`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-380-probe.log`.
```text
E       AssertionError: assert (None is not None)
E        +  where None = Axes(cls='Axes', site=2, visible=True, position=(0.125, 0.10999999999999999, 0.9, 0.88), colorbar_of=None, shared_x=()...0), marker_edge_width=1.0, marker_filled=False, markevery=False, dash_on=None)),), containers=(), pies=(), legend=None).x
```
- Existing kill: `tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-380-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       AttributeError: 'NoneType' object has no attribute 'calls'
```

### src/verifier/figure/description.py:730:4 node 5 — row 385, Return

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone — valid call tuples must survive decoding in their owner.

- Mutated text: `return None`.
- Contract + kill sketch: A valid recorded slot must reach its decoded owner unchanged; mutation erases the owner/tuple or changes a tuple field. Outer non-None alone does not show successful slot decoding.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_slots_reach_their_decoded_owner`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-385-probe.log`.
```text
E       assert None is not None
```
- Existing kill: `tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-385-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       AttributeError: 'NoneType' object has no attribute 'calls'
```

### src/verifier/figure/description.py:730:11 node 5 — row 386, FuncCall

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone — valid call tuples must survive decoding in their owner.

- Mutated text: `return None`.
- Contract + kill sketch: A valid recorded slot must reach its decoded owner unchanged; mutation erases the owner/tuple or changes a tuple field. Outer non-None alone does not show successful slot decoding.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_slots_reach_their_decoded_owner`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-386-probe.log`.
```text
E       assert None is not None
```
- Existing kill: `tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-386-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       AttributeError: 'NoneType' object has no attribute 'calls'
```

### src/verifier/figure/description.py:756:4 node 5 — row 387, Return

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone — valid call tuples must survive decoding in their owner.

- Mutated text: `return None`.
- Contract + kill sketch: A valid recorded slot must reach its decoded owner unchanged; mutation erases the owner/tuple or changes a tuple field. Outer non-None alone does not show successful slot decoding.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_slots_reach_their_decoded_owner`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-387-probe.log`.
```text
E       assert None is not None
```
- Existing kill: `tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-387-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       AttributeError: 'NoneType' object has no attribute 'axes'
```

### src/verifier/figure/description.py:756:11 node 5 — row 388, FuncCall

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone — valid call tuples must survive decoding in their owner.

- Mutated text: `return None`.
- Contract + kill sketch: A valid recorded slot must reach its decoded owner unchanged; mutation erases the owner/tuple or changes a tuple field. Outer non-None alone does not show successful slot decoding.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_slots_reach_their_decoded_owner`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-388-probe.log`.
```text
E       assert None is not None
```
- Existing kill: `tests/test_figure_reader.py::test_p1_calls_record_the_program_line_alone`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-388-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       AttributeError: 'NoneType' object has no attribute 'axes'
```

### src/verifier/figure/reader.py:820:12 node 4 — row 1210, FuncCall

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_cr_r272_a_date_reads_in_the_zone_its_data_carry[9] — UTC zone must win over rc default.

- Mutated text: `units = None`.
- Contract + kill sketch: UTC-bearing axis units outrank the rc timezone; mutated lookup/guard falls back to Asia/Tokyo and changes the reported calendar text.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_utc_keeps_axis_zone_with_another_rc_default`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-1210-probe.log`.
```text
E       AssertionError: ['2026-01-01T10:23:00', '2026-01-02T11:34:00']
E       assert ['2026-01-01T...-02T11:34:00'] == ['2026-01-01T...-02T02:34:00']
```
- Existing kill: `tests/test_figure_reader.py::test_cr_r272_a_date_reads_in_the_zone_its_data_carry[9]`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-1210-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       AssertionError: assert ['2025-12-31T...-01T15:00:00'] == ['2026-01-01T...-02T00:00:00']
E         
```

### src/verifier/figure/reader.py:821:20 node 4 — row 1211, FuncCall

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_cr_r272_a_date_reads_in_the_zone_its_data_carry[9] — UTC zone must win over rc default.

- Mutated text: `zone = units if None else None`.
- Contract + kill sketch: UTC-bearing axis units outrank the rc timezone; mutated lookup/guard falls back to Asia/Tokyo and changes the reported calendar text.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_utc_keeps_axis_zone_with_another_rc_default`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-1211-probe.log`.
```text
E       AssertionError: ['2026-01-01T10:23:00', '2026-01-02T11:34:00']
E       assert ['2026-01-01T...-02T11:34:00'] == ['2026-01-01T...-02T02:34:00']
```
- Existing kill: `tests/test_figure_reader.py::test_cr_r272_a_date_reads_in_the_zone_its_data_carry[9]`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-1211-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       AssertionError: assert ['2025-12-31T...-01T15:00:00'] == ['2026-01-01T...-02T00:00:00']
E         
```

### src/verifier/figure/reader.py:865:42 node 4 — row 1237, FuncCall

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_date_axis_edge_positions — every plotted line position needs its UTC date, including positions off ticks.

- Mutated text: `wanted = {p for p in positions if None}`.
- Contract + kill sketch: Plotted positions must have date-map entries even off ticks and across two lines; mutation deletes/replaces the plotted-position set, leaving missing dates.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_utc_positions_off_ticks_and_across_lines_survive`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-1237-probe.log`.
```text
E       AssertionError: [[None, None], [None, None]]
E       assert [[None, None], [None, None]] == [['2026-01-01...02T04:56:00']]
```
- Existing kill: `tests/test_figure_reader.py::test_date_axis_edge_positions`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-1237-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       KeyError: 1000000000000.0
```

### src/verifier/figure/reader.py:866:8 node 4 — row 1238, AugAssign

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_date_axis_edge_positions — every plotted line position needs its UTC date, including positions off ticks.

- Mutated text: `wanted &= {t[0] for t in (*ticks, *minor) if isinstance(t[0], float)}`.
- Contract + kill sketch: Plotted positions must have date-map entries even off ticks and across two lines; mutation deletes/replaces the plotted-position set, leaving missing dates.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_utc_positions_off_ticks_and_across_lines_survive`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-1238-probe.log`.
```text
E       AssertionError: [[None, None], [None, None]]
E       assert [[None, None], [None, None]] == [['2026-01-01...02T04:56:00']]
```
- Existing kill: `tests/test_figure_reader.py::test_date_axis_edge_positions`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-1238-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       KeyError: 1000000000000.0
```

### src/verifier/figure/reader.py:866:8 node 4 — row 1239, AugAssign

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_date_axis_edge_positions — every plotted line position needs its UTC date, including positions off ticks.

- Mutated text: `wanted = {t[0] for t in (*ticks, *minor) if isinstance(t[0], float)}`.
- Contract + kill sketch: Plotted positions must have date-map entries even off ticks and across two lines; mutation deletes/replaces the plotted-position set, leaving missing dates.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_utc_positions_off_ticks_and_across_lines_survive`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-1239-probe.log`.
```text
E       AssertionError: [[None, None], [None, None]]
E       assert [[None, None], [None, None]] == [['2026-01-01...02T04:56:00']]
```
- Existing kill: `tests/test_figure_reader.py::test_date_axis_edge_positions`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-1239-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       KeyError: 1000000000000.0
```

### src/verifier/figure/reader.py:898:15 node 4 — row 1249, DictArray

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_date_axis_edge_positions — every plotted line position needs its UTC date, including positions off ticks.

- Mutated text: `kind = None`.
- Contract + kill sketch: Plotted positions must have date-map entries even off ticks and across two lines; mutation deletes/replaces the plotted-position set, leaving missing dates.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_utc_positions_off_ticks_and_across_lines_survive`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-1249-probe.log`.
```text
E       AssertionError: [[None, None], [None, None]]
E       assert [[None, None], [None, None]] == [['2026-01-01...02T04:56:00']]
```
- Existing kill: `tests/test_figure_reader.py::test_date_axis_edge_positions`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-1249-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       KeyError: 1000000000000.0
```

### src/verifier/figure/reader.py:899:11 node 4 — row 1251, Compare

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_date_axis_edge_positions — every plotted line position needs its UTC date, including positions off ticks.

- Mutated text: `if kind != 'line':`.
- Contract + kill sketch: Plotted positions must have date-map entries even off ticks and across two lines; mutation deletes/replaces the plotted-position set, leaving missing dates.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_utc_positions_off_ticks_and_across_lines_survive`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-1251-probe.log`.
```text
E       AssertionError: [[None, None], [None, None]]
E       assert [[None, None], [None, None]] == [['2026-01-01...02T04:56:00']]
```
- Existing kill: `tests/test_figure_reader.py::test_date_axis_edge_positions`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-1251-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E               TypeError: 'float' object is not iterable
```

### src/verifier/figure/reader.py:899:19 node 4 — row 1253, String

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_date_axis_edge_positions — every plotted line position needs its UTC date, including positions off ticks.

- Mutated text: `if kind == 'XXlineXX':`.
- Contract + kill sketch: Plotted positions must have date-map entries even off ticks and across two lines; mutation deletes/replaces the plotted-position set, leaving missing dates.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_utc_positions_off_ticks_and_across_lines_survive`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-1253-probe.log`.
```text
E       AssertionError: [[None, None], [None, None]]
E       assert [[None, None], [None, None]] == [['2026-01-01...02T04:56:00']]
```
- Existing kill: `tests/test_figure_reader.py::test_date_axis_edge_positions`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-1253-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       KeyError: 1000000000000.0
```

### src/verifier/figure/reader.py:900:12 node 4 — row 1255, AugAssign

**Severity:** minor. specified: killed by tests/test_figure_reader.py::test_date_axis_edge_positions — every plotted line position needs its UTC date, including positions off ticks.

- Mutated text: `found = geometry['xy'[dimension]]`.
- Contract + kill sketch: Plotted positions must have date-map entries even off ticks and across two lines; mutation deletes/replaces the plotted-position set, leaving missing dates.
- Red probe command suffix: `/tmp/reviewer-3-probes.py::test_utc_positions_off_ticks_and_across_lines_survive`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-1255-probe.log`.
```text
E       AssertionError: [[None, None], ['2026-01-01T03:45:00', '2026-01-02T04:56:00']]
E       assert [[None, None]...02T04:56:00']] == [['2026-01-01...02T04:56:00']]
```
- Existing kill: `tests/test_figure_reader.py::test_date_axis_edge_positions`; rc 1; log `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-3-src/proof/reviewer-3-1255-existing.log`. Driver uses `-x`: later selected tests were not run after this failure.
```text
E       assert None is not None
```

## Register + limits

- Historical mutation runs rc 2 remain no-credit runs; this ruling alone does not reclassify abnormal/invalid mutants or establish credit. This task covers survivors only.
- `open` means outside this node's fixed contract, not approved production behavior or absence of another test gap. No unrelated code defect claimed.
- One existing-kill search remains bounded: `description.py:373:59` clock substitution was tried against P1 call recording; searched clock/latest/setter references under `tests/`, inspected the latest-inversion corpus case, but did not run the full suite on that mutant. The new exact-tuple probe decisively kills it.
- Exploratory relative-path searches encountered MAIN's changing cwd / missing guessed files; their empty results were not evidence. The final date-path census uses absolute paths; all mutation driver subprocesses set absolute repo cwd. Tracked source stayed read-only.
- `.scratch/agents/q4/LEAD-DIRECTIVES.txt` read: D1 applied, every specified reason names its observed existing killer or says `uncovered`.
- Not run: full gate, full suite per mutant, mutation-credit tool, browser/sandbox runtime, CPython 3.11. No new production behavior delivered.

## Validation

- `python3 /home/eturkes/Projects/figure-verification/.scratch/agents/q4/seed.py check reviewer-3 4,5` → `reviewer-3: 1680 rows, 0 problems`, rc 0.
- Independent ordered projection against `seed.pairs({'4','5'})` → all 1,680 immutable `(key,operator,node,mutated)` tuples match; unknown ruling cells = 0.
- Copy restoration checks: reader + description byte-equal to tracked source. Tracked files remain read-only from this review.
- Python LSP coverage confirmed: hover on `reader.py:806` resolves `_date(axes: Any, axis: Any, position: float) -> str | None`.

reviewer-3-DONE-1
