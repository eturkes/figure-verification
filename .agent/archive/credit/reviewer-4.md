# reviewer-4 — credit survivors, nodes 6–9

## Fixed check set + contract readings

Check = each `(mutant,node)` survivor against that node's acceptance-side contract; `specified` = an observable violation inside it, `open` = another contract or an equivalent mutation. Target = committed survivor inventory `.agent/credit/cr-twins-survivors.tsv`; target code read-only. No verdict for the whole verifier is implied.

- **6 / R274 — `cr-adjacent-bars-one-ulp-apart`:** adjacent bars whose apparent overlap is only floating-point error must pass. The overlap slack allows the larger of 64 ulps at the coordinates' magnitude and `1e-9 × own size`; geometry still distinguishes actual positive-area overlap. Sources: `tests/figure_corpus/code_review.toml:359–366`, `tests/test_figure_corpus.py:34–48`, `.agent/review.md:175`, `src/verifier/figure/mark_rules.py::_slack`, `_check_bars` and `_box`. This twin pins the honest/roundoff side, not every independent mark refusal.
- **7 / R274 — `cr-translated-bars-apart`:** bars separated in key space must stay accepted after translating their key coordinates to `1e12`; the corrected overlap slack must not create a false overlap. Sources: `tests/figure_corpus/code_review.toml:312–318`, `tests/test_figure_corpus.py:34–48`, `.agent/review.md:175`, `src/verifier/figure/mark_rules.py::_slack`, `_check_bars` and `_box`. The distortion side has separate blocking corpus cases.
- **8 / R274 — `cr-translated-hist`:** an unmodified histogram with genuine counts and recorded bin centers at large translated coordinates must pass; the same size/ulp slack governs its center comparison. Sources: `tests/figure_corpus/code_review.toml:350–356`, `tests/test_figure_corpus.py:34–48`, `.agent/review.md:175`, `src/verifier/figure/mark_rules.py::_slack`, `_hist_ok`, `_counts`, `_check_hist` and `_check_bars`. Altered histogram geometry/counts belong to separate refusal cases.
- **9 / R310 — `cr-tiny-ticks-labelled-true`:** true small-magnitude numeric tick labels must pass; the numeric comparison uses half the last displayed digit plus `1e-12 × max(abs(position),abs(shown))`, with formatter scale/offset. Sources: `tests/figure_corpus/code_review.toml:330–337`, `tests/test_figure_corpus.py:34–48`, `.agent/review.md:211`, `src/verifier/figure/ticks.py::_numeric_ok`, `_reading` and `mismatched_tick`. False labels at tiny positions belong to the blocking twin.

These readings were fixed before opening the seeded survivor rows. Shared input decoding, other artist families, source matching, columns, unrelated axes/mark rules, publication text and display-only sites are outside these narrow twin contracts.


## Verdict table

3,958 executed-line `(mutant,node)` pairs adjudicated, no unknowns: **31 specified / 3,927 open**. Specified = **21 pairs killed by an existing named test; 10 pairs lack a demonstrated existing kill**. The 31 pairs represent 22 distinct mutants. All specified pairs have a baseline-green/copied-mutant-red observable witness. `uncovered` means no kill in the targeted controls listed below, not an exhaustive proof that the full suite has none.

| node | rows | specified | open | verdict | never-executed class ruling |
|---|---:|---:|---:|---|---|
| 6 | 993 | 5 | 988 | finding: F1368, F1400, F1542, F1546, F1571 | open: 4,970; N6 below |
| 7 | 992 | 2 | 990 | finding: F1369, F1401 | open: 4,969; N7 below |
| 8 | 995 | 7 | 988 | finding: F1370, F1402, F1544, F1548, F1573, F1745, F1752 | open: 4,850; N8 below |
| 9 | 978 | 17 | 961 | finding: F1371, F1403, F3442, F3575, F3583, F3599, F3603, F3607, F3611, F3615, F3619, F3624, F3625, F3629, F3633, F3637, F3639 | open: 4,969; N9 below |

### Never-executed classes

Counts = `git show 7b61aa25118fbf5353d14402d1861a01a4e3fa2a`: total survivors minus executed-line survivors. Class ruling requested by the brief; individual members were not enumerated or rerun. This is a scope ruling for the named twin, not a claim that these mutants are equivalent across the product.

- **N6 / 4,970 → open:** alternate artist/data-source/error branches and refusal paths absent from the source-free adjacent-bar acceptance path; their behavior belongs to other corpus/contracts.
- **N7 / 4,969 → open:** alternate families/sources/errors and refusal paths absent from the translated-separated-bar acceptance path.
- **N8 / 4,850 → open:** alternate families/sources/errors and histogram variants outside this plain count/center-acceptance path.
- **N9 / 4,969 → open:** alternate families/sources/errors and date/category/malformed-label paths outside tiny numeric-label acceptance.

## Bulk predicates (checked before scripting)

Every row was retained in its original order, including distinct mutations sharing the same key/node. The script classifies by exact module, AST enclosing function/range and mutation text; candidate exceptions are exact line/text/node predicates. Inspection: 1,133 distinct executed-line mutations expanded to all 3,958 node pairs, no row sampling.

1. `TypeAlias`, `TypeVar` or `cast`-type-string mutations → open for these contracts: annotations/type reflection do not enter the numerical decisions. Checked declarations and casts in `description.py:16–36,148–153`, `parts.py:28–29`, `shapes.py:24–27,126`, `series.py:29–30`, and the source-side modules. Dataclass `frozen`/`slots`/`kw_only` flips → open: object mutation, layout and constructor surface are not a geometry/tick acceptance predicate. A version-string mutation is metadata, not a chart fact. No claim about whole-package type-reflection behavior.
2. Entire source-data modules (`anchoring`, `columns`, `computed`, `explain`, `keys`, `request`, `series`, `sources`, `pysrc/{aggregate,budget,csvread,errors,limits,table}`) → open outside contract: all four corpus entries supply neither CSV nor request. Read their module responsibility declarations, survivor-containing definitions and the controlling branch `judge.py:152–173` (`integrity_only` bypasses explanations). `explain.py:1030–1036` is the separate duplicate-category-key rule; these are numeric axes.
3. `inert.py:1–67`, `interpret.py:1–226`, `judge.py::_texts`, diagnostics/reason sites → open: publication/description wording and display-only sites, not the twins' numeric verdict. `legends.py` survivors → open: no legend or encoding key in these cases. `description.py` representation/schema/slot-survivor groups → open: the decoder has its own contract; these twins do not grade schema closure, metadata or instance layout.
4. `reader.py` survivors grouped by function: call/site hooks (`181–361`, `487–533`), renderer/resources (`100–178`, `1088–1157`), independent artist facts (`364–453`, `541–912`, `975–1075`) → open under the fixed contract boundary. Numeric comparison is the subject, not acquisition/schema/visibility/return-value contracts of every upstream reader API. Read the whole reader and every distinct survivor in these ranges. Likewise `parts.py:28–311`, `axes_rules.py:23–176`, `shapes.py:24–174` survivors → open for independent admission, transform, clipping, ink, source-key and display properties. The quantitative overlap/center/tick comparisons are retained below as explicit exceptions in their deciding modules.
5. `mark_rules.py` for node 9 and `ticks.py` for nodes 6–8 → open: orthogonal checks. `mark_rules.py` other-family/ink/order/zero/width/density branches → open. `_check_bars:166–175` surviving mutations either skip potential refusals or alter early termination while the later positive-area/slack test remains: none adds a refusal for already-separated bars. Bigger slack (`32–46`) changes the refusal side; the blocking twins own it. **Exceptions:** decreased own-size/ulp slack for nodes 6 and 8; `_counts:224` and negative-translated width at `_hist_ok:242` for node 8.
6. `ticks.py` parser forms, dates/categories, blank labels, broader allowances and disabled checks → open outside this acceptance-side contract. **Exceptions for node 9:** reduced `1e-12` allowance; reduced half-last-digit allowance; `_numeric_ok:110,116` decimal scale/offset and its explicit `axis=None` minor-label convention; additive tolerance at `119`. Reading/parsing exotic numeric spellings has its own preexisting form tests; this review does not expand R310 into every spelling.
7. `judge.py:139` (`return None`) and `177–183` (`passed = None`) → specified for all nodes: a passing chart needs a `Passed` verdict, not merely a non-`Blocked` object. Other judge survivors change refusal/source/display behavior outside these honest numeric cases. The corpus assertion at `tests/test_figure_corpus.py:47` admits `None`; the existing `test_v6_integrity_alone_is_disclosed` kills both mutations.

Exact classifier + preserved per-row reasons: `/tmp/reviewer-4-adjudicate.py` → this TSV; D1 evidence update: `/tmp/reviewer-4-finish.py`.

## Witness catalogue

All direct witnesses use real `RectGeometry`, `HistRecord`, `Mark` or `Axis` objects; lightweight axes/panel wrappers supply only the fields the called function reads. A synthetic description can sit exactly on a documented tolerance boundary, including a tiny apparent overlap/center displacement: acceptance follows the measured coordinates and allowance, never an inferred cause of the roundoff.

| probe | input + contract observable |
|---|---|
| `verdict` | Run the four original corpus programs unchanged through `reader.run → parse_description → judge(Sources())`; every result must be `Passed`. |
| `bars-size` | Two width-2, height-1, zero-based rects at x=0 and x=`2−1.5e-9`; permitted overlap `< 1e-9×2`; `_check_bars` must not block. |
| `bars-ulp` | Two width-1, height-1, zero-based rects at x=`1e12` and `1e12+1−64*ulp(1e12)`; boundary overlap is allowed; `_check_bars` must not block. |
| `hist-size` | Bins `(0,2)`, value `.5`, genuine count 1; width-2 bar center shifted `1.5e-9`, within the own-size allowance; `_hist_ok` must return True. |
| `hist-ulp` | Bins `(1e12,1e12+2)`, value `1e12+.5`, count 1; bar center shifted `64*ulp(1e12)`; `_hist_ok` must return True. |
| `hist-counts` | Values `(1e12,1e12+2,1e12+3)`, bins `(1e12,1e12+1.5,1e12+3)`; `_counts` must return `[1,2]`. |
| `hist-negative` | Bins `(-1e12,-1e12+2)`, value `-1e12+.5`, width-2 bar at first edge, height 1; `_hist_ok` must return True. |
| `tick-relative` | `_numeric_ok(1.00000000000075e-13, "0.000000000000100000000000000000", axis(order=0,offset=0))` must return True: difference fits `1e-12×magnitude`. |
| `tick-half` | `_numeric_ok(1.004e-13, "0.000000000000100", axis(order=0,offset=0))` must return True: difference fits half the last decimal digit. |
| `tick-exact` | `_numeric_ok(1e-13, "0.000000000000100000000000000000", axis(order=0,offset=0))` must return True: an exact label never fails because tolerance became negative. |
| `tick-scale` | `_numeric_ok(1e-13, "1.000", axis(order=-13,offset=0))` must return True. |
| `tick-offset` | `_numeric_ok(1.01e-13, "0.000000000000001", axis(order=0,offset=1e-13))` must return True. |
| `tick-minor` | `_numeric_ok(1e-13, "0.000000000000100000", None)` must return True (unit scale + zero offset). |

## Specified-row details

`minor` = assurance defect in this twin's coverage/credit, not a demonstrated defect in the unmutated implementation. Each section below is one seeded TSV row. Duplicate key/node headings carry the physical TSV row for disambiguation.

Common red command, after the named mutation is applied to the copy: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python /tmp/reviewer-4-probe.py <probe>`. Automatic apply/run/restore: `python3 /tmp/reviewer-4-run-probes.py <key>` (all variants of that key). The driver reads the original TSV candidates, replaces the enclosing statement's full span, checks changed bytes and compile validity, clears only the copy's bytecode, and restores identical bytes in `finally`.

### F1368 — `src/verifier/figure/judge.py:139:4 node 6` (TSV row 1368)

- Severity: **minor**. Contract: a pass must be a Passed result, not None.
- Original anchor: `return first`.
- Mutated text (Return): `return None`.
- Kill sketch: **`verdict`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py verdict` rc 1.
- Failing output: `AssertionError: verdict: expected Passed, got [('cr-translated-bars-apart', 'NoneType'), ('cr-tiny-ticks-labelled-true', 'NoneType'), ('cr-translated-hist', 'NoneType'), ('cr-adjacent-bars-one-ulp-apart', 'NoneType')]`.
- **Existing kill:** `tests/test_figure_values.py::test_v6_integrity_alone_is_disclosed`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_values.py::test_v6_integrity_alone_is_disclosed` → rc 1.
- Existing-test red: `E       assert (False)`.

### F1369 — `src/verifier/figure/judge.py:139:4 node 7` (TSV row 1369)

- Severity: **minor**. Contract: a pass must be a Passed result, not None.
- Original anchor: `return first`.
- Mutated text (Return): `return None`.
- Kill sketch: **`verdict`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py verdict` rc 1.
- Failing output: `AssertionError: verdict: expected Passed, got [('cr-translated-bars-apart', 'NoneType'), ('cr-tiny-ticks-labelled-true', 'NoneType'), ('cr-translated-hist', 'NoneType'), ('cr-adjacent-bars-one-ulp-apart', 'NoneType')]`.
- **Existing kill:** `tests/test_figure_values.py::test_v6_integrity_alone_is_disclosed`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_values.py::test_v6_integrity_alone_is_disclosed` → rc 1.
- Existing-test red: `E       assert (False)`.

### F1370 — `src/verifier/figure/judge.py:139:4 node 8` (TSV row 1370)

- Severity: **minor**. Contract: a pass must be a Passed result, not None.
- Original anchor: `return first`.
- Mutated text (Return): `return None`.
- Kill sketch: **`verdict`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py verdict` rc 1.
- Failing output: `AssertionError: verdict: expected Passed, got [('cr-translated-bars-apart', 'NoneType'), ('cr-tiny-ticks-labelled-true', 'NoneType'), ('cr-translated-hist', 'NoneType'), ('cr-adjacent-bars-one-ulp-apart', 'NoneType')]`.
- **Existing kill:** `tests/test_figure_values.py::test_v6_integrity_alone_is_disclosed`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_values.py::test_v6_integrity_alone_is_disclosed` → rc 1.
- Existing-test red: `E       assert (False)`.

### F1371 — `src/verifier/figure/judge.py:139:4 node 9` (TSV row 1371)

- Severity: **minor**. Contract: a pass must be a Passed result, not None.
- Original anchor: `return first`.
- Mutated text (Return): `return None`.
- Kill sketch: **`verdict`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py verdict` rc 1.
- Failing output: `AssertionError: verdict: expected Passed, got [('cr-translated-bars-apart', 'NoneType'), ('cr-tiny-ticks-labelled-true', 'NoneType'), ('cr-translated-hist', 'NoneType'), ('cr-adjacent-bars-one-ulp-apart', 'NoneType')]`.
- **Existing kill:** `tests/test_figure_values.py::test_v6_integrity_alone_is_disclosed`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_values.py::test_v6_integrity_alone_is_disclosed` → rc 1.
- Existing-test red: `E       assert (False)`.

### F1400 — `src/verifier/figure/judge.py:177:13 node 6` (TSV row 1400)

- Severity: **minor**. Contract: a pass must be a Passed result, not None.
- Original anchor: `passed = Passed(`.
- Mutated text (FuncCall): `passed = None`.
- Kill sketch: **`verdict`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py verdict` rc 1.
- Failing output: `AssertionError: verdict: expected Passed, got [('cr-translated-bars-apart', 'NoneType'), ('cr-tiny-ticks-labelled-true', 'NoneType'), ('cr-translated-hist', 'NoneType'), ('cr-adjacent-bars-one-ulp-apart', 'NoneType')]`.
- **Existing kill:** `tests/test_figure_values.py::test_v6_integrity_alone_is_disclosed`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_values.py::test_v6_integrity_alone_is_disclosed` → rc 1.
- Existing-test red: `E       assert (False)`.

### F1401 — `src/verifier/figure/judge.py:177:13 node 7` (TSV row 1401)

- Severity: **minor**. Contract: a pass must be a Passed result, not None.
- Original anchor: `passed = Passed(`.
- Mutated text (FuncCall): `passed = None`.
- Kill sketch: **`verdict`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py verdict` rc 1.
- Failing output: `AssertionError: verdict: expected Passed, got [('cr-translated-bars-apart', 'NoneType'), ('cr-tiny-ticks-labelled-true', 'NoneType'), ('cr-translated-hist', 'NoneType'), ('cr-adjacent-bars-one-ulp-apart', 'NoneType')]`.
- **Existing kill:** `tests/test_figure_values.py::test_v6_integrity_alone_is_disclosed`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_values.py::test_v6_integrity_alone_is_disclosed` → rc 1.
- Existing-test red: `E       assert (False)`.

### F1402 — `src/verifier/figure/judge.py:177:13 node 8` (TSV row 1402)

- Severity: **minor**. Contract: a pass must be a Passed result, not None.
- Original anchor: `passed = Passed(`.
- Mutated text (FuncCall): `passed = None`.
- Kill sketch: **`verdict`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py verdict` rc 1.
- Failing output: `AssertionError: verdict: expected Passed, got [('cr-translated-bars-apart', 'NoneType'), ('cr-tiny-ticks-labelled-true', 'NoneType'), ('cr-translated-hist', 'NoneType'), ('cr-adjacent-bars-one-ulp-apart', 'NoneType')]`.
- **Existing kill:** `tests/test_figure_values.py::test_v6_integrity_alone_is_disclosed`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_values.py::test_v6_integrity_alone_is_disclosed` → rc 1.
- Existing-test red: `E       assert (False)`.

### F1403 — `src/verifier/figure/judge.py:177:13 node 9` (TSV row 1403)

- Severity: **minor**. Contract: a pass must be a Passed result, not None.
- Original anchor: `passed = Passed(`.
- Mutated text (FuncCall): `passed = None`.
- Kill sketch: **`verdict`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py verdict` rc 1.
- Failing output: `AssertionError: verdict: expected Passed, got [('cr-translated-bars-apart', 'NoneType'), ('cr-tiny-ticks-labelled-true', 'NoneType'), ('cr-translated-hist', 'NoneType'), ('cr-adjacent-bars-one-ulp-apart', 'NoneType')]`.
- **Existing kill:** `tests/test_figure_values.py::test_v6_integrity_alone_is_disclosed`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_values.py::test_v6_integrity_alone_is_disclosed` → rc 1.
- Existing-test red: `E       assert (False)`.

### F1542 — `src/verifier/figure/mark_rules.py:32:20 node 6` (TSV row 1542)

- Severity: **minor**. Contract: shrinks the specified own-size allowance and falsely refuses accepted geometry.
- Original anchor: `_TOLERANCE: Final = 1e-9`.
- Mutated text (Number): `_TOLERANCE: Final = 5e-10`.
- Kill sketch: **`bars-size`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py bars-size` rc 1.
- Failing output: `AssertionError: bars-size: expected pass, got bars_overlap`.
- **Uncovered in targeted controls:** no existing kill demonstrated; MAIN must add/locate a boundary test before closing this credit row.
- Existing controls run, all survived: `tests/test_figure_corpus.py::test_corpus_case[cr-adjacent-bars-one-ulp-apart]`, `tests/test_figure_corpus.py::test_corpus_case[cr-translated-bars-apart]`, `tests/test_figure_corpus.py::test_corpus_case[cr-translated-hist]`, `tests/test_figure_corpus.py::test_corpus_case[hist-density]` (rc 0).

### F1544 — `src/verifier/figure/mark_rules.py:32:20 node 8` (TSV row 1544)

- Severity: **minor**. Contract: shrinks the specified own-size allowance and falsely refuses accepted geometry.
- Original anchor: `_TOLERANCE: Final = 1e-9`.
- Mutated text (Number): `_TOLERANCE: Final = 5e-10`.
- Kill sketch: **`hist-size`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py hist-size` rc 1.
- Failing output: `AssertionError: hist-size: expected True, got False`.
- **Uncovered in targeted controls:** no existing kill demonstrated; MAIN must add/locate a boundary test before closing this credit row.
- Existing controls run, all survived: `tests/test_figure_corpus.py::test_corpus_case[cr-adjacent-bars-one-ulp-apart]`, `tests/test_figure_corpus.py::test_corpus_case[cr-translated-bars-apart]`, `tests/test_figure_corpus.py::test_corpus_case[cr-translated-hist]`, `tests/test_figure_corpus.py::test_corpus_case[hist-density]` (rc 0).

### F1546 — `src/verifier/figure/mark_rules.py:33:15 node 6` (TSV row 1546)

- Severity: **minor**. Contract: shrinks the 64-ulp allowance and falsely refuses its accepted boundary.
- Original anchor: `_ULPS: Final = 64`.
- Mutated text (Number): `_ULPS: Final = 63`.
- Kill sketch: **`bars-ulp`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py bars-ulp` rc 1.
- Failing output: `AssertionError: bars-ulp: expected pass, got bars_overlap`.
- **Uncovered in targeted controls:** no existing kill demonstrated; MAIN must add/locate a boundary test before closing this credit row.
- Existing controls run, all survived: `tests/test_figure_corpus.py::test_corpus_case[cr-adjacent-bars-one-ulp-apart]`, `tests/test_figure_corpus.py::test_corpus_case[cr-translated-bars-apart]`, `tests/test_figure_corpus.py::test_corpus_case[cr-translated-hist]`, `tests/test_figure_corpus.py::test_corpus_case[hist-density]` (rc 0).

### F1548 — `src/verifier/figure/mark_rules.py:33:15 node 8` (TSV row 1548)

- Severity: **minor**. Contract: shrinks the 64-ulp allowance and falsely refuses its accepted boundary.
- Original anchor: `_ULPS: Final = 64`.
- Mutated text (Number): `_ULPS: Final = 63`.
- Kill sketch: **`hist-ulp`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py hist-ulp` rc 1.
- Failing output: `AssertionError: hist-ulp: expected True, got False`.
- **Uncovered in targeted controls:** no existing kill demonstrated; MAIN must add/locate a boundary test before closing this credit row.
- Existing controls run, all survived: `tests/test_figure_corpus.py::test_corpus_case[cr-adjacent-bars-one-ulp-apart]`, `tests/test_figure_corpus.py::test_corpus_case[cr-translated-bars-apart]`, `tests/test_figure_corpus.py::test_corpus_case[cr-translated-hist]`, `tests/test_figure_corpus.py::test_corpus_case[hist-density]` (rc 0).

### F1571 — `src/verifier/figure/mark_rules.py:46:75 node 6` (TSV row 1571)

- Severity: **minor**. Contract: dividing by own size shrinks the allowance for wide bars/bins.
- Original anchor: `return max(_ULPS * math.ulp(max(abs(value) for value in coordinates)), _TOLERANCE * size)`.
- Mutated text (BinOp): `return max(_ULPS * math.ulp(max(abs(value) for value in coordinates)), _TOLERANCE / size)`.
- Kill sketch: **`bars-size`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py bars-size` rc 1.
- Failing output: `AssertionError: bars-size: expected pass, got bars_overlap`.
- **Uncovered in targeted controls:** no existing kill demonstrated; MAIN must add/locate a boundary test before closing this credit row.
- Existing controls run, all survived: `tests/test_figure_corpus.py::test_corpus_case[cr-adjacent-bars-one-ulp-apart]`, `tests/test_figure_corpus.py::test_corpus_case[cr-translated-bars-apart]`, `tests/test_figure_corpus.py::test_corpus_case[cr-translated-hist]`, `tests/test_figure_corpus.py::test_corpus_case[hist-density]` (rc 0).

### F1573 — `src/verifier/figure/mark_rules.py:46:75 node 8` (TSV row 1573)

- Severity: **minor**. Contract: dividing by own size shrinks the allowance for wide bars/bins.
- Original anchor: `return max(_ULPS * math.ulp(max(abs(value) for value in coordinates)), _TOLERANCE * size)`.
- Mutated text (BinOp): `return max(_ULPS * math.ulp(max(abs(value) for value in coordinates)), _TOLERANCE / size)`.
- Kill sketch: **`hist-size`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py hist-size` rc 1.
- Failing output: `AssertionError: hist-size: expected True, got False`.
- **Uncovered in targeted controls:** no existing kill demonstrated; MAIN must add/locate a boundary test before closing this credit row.
- Existing controls run, all survived: `tests/test_figure_corpus.py::test_corpus_case[cr-adjacent-bars-one-ulp-apart]`, `tests/test_figure_corpus.py::test_corpus_case[cr-translated-bars-apart]`, `tests/test_figure_corpus.py::test_corpus_case[cr-translated-hist]`, `tests/test_figure_corpus.py::test_corpus_case[hist-density]` (rc 0).

### F1745 — `src/verifier/figure/mark_rules.py:224:67 node 8` (TSV row 1745)

- Severity: **minor**. Contract: miscounts a genuine translated histogram with an interior last-bin value.
- Original anchor: `index = next(i for i in range(len(counts)) if value < bins[i + 1] or i == len(counts) - 1)`.
- Mutated text (BinOp): `index = next(i for i in range(len(counts)) if value < bins[i - 1] or i == len(counts) - 1)`.
- Kill sketch: **`hist-counts`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py hist-counts` rc 1.
- Failing output: `AssertionError: hist-counts: expected [1, 2], got [2, 1]`.
- **Existing kill:** `tests/test_figure_corpus.py::test_corpus_case[hist-honest]`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_corpus.py::test_corpus_case[hist-honest] tests/test_figure_corpus.py::test_corpus_case[hist-unequal-bins]` → rc 1.
- Existing-test red: `E           AssertionError: Blocked(reason='hist_counts', site=3)`.

### F1752 — `src/verifier/figure/mark_rules.py:242:16 node 8` (TSV row 1752)

- Severity: **minor**. Contract: negative translation makes the purported width negative and falsely refuses a genuine histogram.
- Original anchor: `width = high - low`.
- Mutated text (BinOp): `width = high + low`.
- Kill sketch: **`hist-negative`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py hist-negative` rc 1.
- Failing output: `AssertionError: hist-negative: expected True, got False`.
- **Existing kill:** `tests/test_figure_corpus.py::test_corpus_case[hist-density]`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_corpus.py::test_corpus_case[hist-density]` → rc 1.
- Existing-test red: `E           AssertionError: Blocked(reason='hist_counts', site=3)`.

### F3442 — `src/verifier/figure/ticks.py:48:19 node 9` (TSV row 3442)

- Severity: **minor**. Contract: shrinks the magnitude-relative allowance for a true tiny decimal label.
- Original anchor: `_ABSOLUTE: Final = 1e-12`.
- Mutated text (Number): `_ABSOLUTE: Final = 5e-13`.
- Kill sketch: **`tick-relative`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py tick-relative` rc 1.
- Failing output: `AssertionError: tick-relative: expected True, got False`.
- **Uncovered in targeted controls:** no existing kill demonstrated; MAIN must add/locate a boundary test before closing this credit row.
- Existing controls run, all survived: `tests/test_figure_corpus.py::test_corpus_case[honest-small-sci]`, `tests/test_figure_corpus.py::test_corpus_case[minor-tick-honest]`, `tests/test_figure_corpus.py::test_corpus_case[cr-shown-offset-text]`, `tests/test_figure_judge.py::test_j3_numeric_label_forms[money]`, `tests/test_figure_judge.py::test_j3_numeric_label_forms[engineering]` (rc 0).

### F3575 — `src/verifier/figure/ticks.py:98:11 node 9` (TSV row 3575)

- Severity: **minor**. Contract: shrinks the half-last-digit allowance for a true rounded tiny label.
- Original anchor: `half = 0.5 * 10.0 ** (exponent + shift - len(fraction))`.
- Mutated text (Number): `half = 0.25 * 10.0 ** (exponent + shift - len(fraction))`.
- Kill sketch: **`tick-half`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py tick-half` rc 1.
- Failing output: `AssertionError: tick-half: expected True, got False`.
- **Uncovered in targeted controls:** no existing kill demonstrated; MAIN must add/locate a boundary test before closing this credit row.
- Existing controls run, all survived: `tests/test_figure_corpus.py::test_corpus_case[honest-small-sci]`, `tests/test_figure_corpus.py::test_corpus_case[minor-tick-honest]`, `tests/test_figure_corpus.py::test_corpus_case[cr-shown-offset-text]`, `tests/test_figure_judge.py::test_j3_numeric_label_forms[money]`, `tests/test_figure_judge.py::test_j3_numeric_label_forms[engineering]` (rc 0).

### F3583 — `src/verifier/figure/ticks.py:98:17 node 9` (TSV row 3583)

- Severity: **minor**. Contract: shrinks the half-last-digit allowance for a true rounded tiny label.
- Original anchor: `half = 0.5 * 10.0 ** (exponent + shift - len(fraction))`.
- Mutated text (Number): `half = 0.5 * 20.0 ** (exponent + shift - len(fraction))`.
- Kill sketch: **`tick-half`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py tick-half` rc 1.
- Failing output: `AssertionError: tick-half: expected True, got False`.
- **Uncovered in targeted controls:** no existing kill demonstrated; MAIN must add/locate a boundary test before closing this credit row.
- Existing controls run, all survived: `tests/test_figure_corpus.py::test_corpus_case[honest-small-sci]`, `tests/test_figure_corpus.py::test_corpus_case[minor-tick-honest]`, `tests/test_figure_corpus.py::test_corpus_case[cr-shown-offset-text]`, `tests/test_figure_judge.py::test_j3_numeric_label_forms[money]`, `tests/test_figure_judge.py::test_j3_numeric_label_forms[engineering]` (rc 0).

### F3599 — `src/verifier/figure/ticks.py:110:16 node 9` (TSV row 3599)

- Severity: **minor**. Contract: a true tiny major label must use its decimal formatter scale.
- Original anchor: `scale = 10.0 ** (axis.order if axis is not None else 0)`.
- Mutated text (Number): `scale = 20.0 ** (axis.order if axis is not None else 0)`.
- Kill sketch: **`tick-scale`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py tick-scale` rc 1.
- Failing output: `AssertionError: tick-scale: expected True, got False`.
- **Existing kill:** `tests/test_figure_corpus.py::test_corpus_case[honest-small-sci]`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_corpus.py::test_corpus_case[honest-small-sci]` → rc 1.
- Existing-test red: `E           AssertionError: Blocked(reason='tick_label_mismatch', site=None)`.

### F3603 — `src/verifier/figure/ticks.py:110:16 node 9` (TSV row 3603)

- Severity: **minor**. Contract: a true tiny major label must use its decimal formatter scale.
- Original anchor: `scale = 10.0 ** (axis.order if axis is not None else 0)`.
- Mutated text (Number): `scale = 5.0 ** (axis.order if axis is not None else 0)`.
- Kill sketch: **`tick-scale`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py tick-scale` rc 1.
- Failing output: `AssertionError: tick-scale: expected True, got False`.
- **Existing kill:** `tests/test_figure_corpus.py::test_corpus_case[honest-small-sci]`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_corpus.py::test_corpus_case[honest-small-sci]` → rc 1.
- Existing-test red: `E           AssertionError: Blocked(reason='tick_label_mismatch', site=None)`.

### F3607 — `src/verifier/figure/ticks.py:110:39 node 9` (TSV row 3607)

- Severity: **minor**. Contract: a true tiny major label must use its decimal formatter scale.
- Original anchor: `scale = 10.0 ** (axis.order if axis is not None else 0)`.
- Mutated text (Compare): `scale = 10.0 ** (axis.order if axis is None else 0)`.
- Kill sketch: **`tick-scale`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py tick-scale` rc 1.
- Failing output: `AssertionError: tick-scale: expected True, got False`.
- **Existing kill:** `tests/test_figure_corpus.py::test_corpus_case[honest-small-sci]`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_corpus.py::test_corpus_case[honest-small-sci]` → rc 1.
- Existing-test red: `E           AssertionError: Blocked(reason='tick_label_mismatch', site=None)`.

### F3611 — `src/verifier/figure/ticks.py:110:51 node 9` (TSV row 3611)

- Severity: **minor**. Contract: a true tiny minor label must use unit scale when axis is None.
- Original anchor: `scale = 10.0 ** (axis.order if axis is not None else 0)`.
- Mutated text (Keyword): `scale = 10.0 ** (axis.order if axis is not ' ' else 0)`.
- Kill sketch: **`tick-minor`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py tick-minor` rc 1.
- Failing output: `AssertionError: tick-minor: expected True, got AttributeError: 'NoneType' object has no attribute 'order'`.
- **Existing kill:** `tests/test_figure_corpus.py::test_corpus_case[minor-tick-honest]`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_corpus.py::test_corpus_case[minor-tick-honest]` → rc 1.
- Existing-test red: `E           AttributeError: 'NoneType' object has no attribute 'order'`.

### F3615 — `src/verifier/figure/ticks.py:110:61 node 9` (TSV row 3615)

- Severity: **minor**. Contract: a true tiny minor label must use unit scale when axis is None.
- Original anchor: `scale = 10.0 ** (axis.order if axis is not None else 0)`.
- Mutated text (Number): `scale = 10.0 ** (axis.order if axis is not None else -1)`.
- Kill sketch: **`tick-minor`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py tick-minor` rc 1.
- Failing output: `AssertionError: tick-minor: expected True, got False`.
- **Existing kill:** `tests/test_figure_corpus.py::test_corpus_case[minor-tick-honest]`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_corpus.py::test_corpus_case[minor-tick-honest]` → rc 1.
- Existing-test red: `E           AssertionError: Blocked(reason='tick_label_mismatch', site=5)`.

### F3619 — `src/verifier/figure/ticks.py:110:61 node 9` (TSV row 3619)

- Severity: **minor**. Contract: a true tiny minor label must use unit scale when axis is None.
- Original anchor: `scale = 10.0 ** (axis.order if axis is not None else 0)`.
- Mutated text (Number): `scale = 10.0 ** (axis.order if axis is not None else 1)`.
- Kill sketch: **`tick-minor`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py tick-minor` rc 1.
- Failing output: `AssertionError: tick-minor: expected True, got False`.
- **Existing kill:** `tests/test_figure_corpus.py::test_corpus_case[minor-tick-honest]`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_corpus.py::test_corpus_case[minor-tick-honest]` → rc 1.
- Existing-test red: `E           AssertionError: Blocked(reason='tick_label_mismatch', site=5)`.

### F3624 — `src/verifier/figure/ticks.py:116:16 node 9` (TSV row 3624)

- Severity: **minor**. Contract: a true tiny label must add its formatter offset.
- Original anchor: `shown = value * scale + (axis.offset if axis is not None else 0.0)`.
- Mutated text (BinOp): `shown = value * scale - (axis.offset if axis is not None else 0.0)`.
- Kill sketch: **`tick-offset`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py tick-offset` rc 1.
- Failing output: `AssertionError: tick-offset: expected True, got False`.
- **Existing kill:** `tests/test_figure_corpus.py::test_corpus_case[cr-shown-offset-text]`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_corpus.py::test_corpus_case[cr-shown-offset-text]` → rc 1.
- Existing-test red: `E           AssertionError: Blocked(reason='tick_label_mismatch', site=None)`.

### F3625 — `src/verifier/figure/ticks.py:116:48 node 9` (TSV row 3625)

- Severity: **minor**. Contract: a true tiny label must add its formatter offset.
- Original anchor: `shown = value * scale + (axis.offset if axis is not None else 0.0)`.
- Mutated text (Compare): `shown = value * scale + (axis.offset if axis is None else 0.0)`.
- Kill sketch: **`tick-offset`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py tick-offset` rc 1.
- Failing output: `AssertionError: tick-offset: expected True, got False`.
- **Existing kill:** `tests/test_figure_corpus.py::test_corpus_case[cr-shown-offset-text]`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_corpus.py::test_corpus_case[cr-shown-offset-text]` → rc 1.
- Existing-test red: `E           AssertionError: Blocked(reason='tick_label_mismatch', site=None)`.

### F3629 — `src/verifier/figure/ticks.py:116:60 node 9` (TSV row 3629)

- Severity: **minor**. Contract: a true tiny minor label must use zero offset when axis is None.
- Original anchor: `shown = value * scale + (axis.offset if axis is not None else 0.0)`.
- Mutated text (Keyword): `shown = value * scale + (axis.offset if axis is not ' ' else 0.0)`.
- Kill sketch: **`tick-minor`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py tick-minor` rc 1.
- Failing output: `AssertionError: tick-minor: expected True, got AttributeError: 'NoneType' object has no attribute 'offset'`.
- **Existing kill:** `tests/test_figure_corpus.py::test_corpus_case[minor-tick-honest]`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_corpus.py::test_corpus_case[minor-tick-honest]` → rc 1.
- Existing-test red: `E           AttributeError: 'NoneType' object has no attribute 'offset'`.

### F3633 — `src/verifier/figure/ticks.py:116:70 node 9` (TSV row 3633)

- Severity: **minor**. Contract: a true tiny minor label must use zero offset when axis is None.
- Original anchor: `shown = value * scale + (axis.offset if axis is not None else 0.0)`.
- Mutated text (Number): `shown = value * scale + (axis.offset if axis is not None else 1.0)`.
- Kill sketch: **`tick-minor`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py tick-minor` rc 1.
- Failing output: `AssertionError: tick-minor: expected True, got False`.
- **Existing kill:** `tests/test_figure_corpus.py::test_corpus_case[minor-tick-honest]`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_corpus.py::test_corpus_case[minor-tick-honest]` → rc 1.
- Existing-test red: `E           AssertionError: Blocked(reason='tick_label_mismatch', site=5)`.

### F3637 — `src/verifier/figure/ticks.py:119:20 node 9` (TSV row 3637)

- Severity: **minor**. Contract: half-digit and relative allowances add; multiplying/subtracting falsely refuses a true tiny label.
- Original anchor: `tolerance = half * scale + _ABSOLUTE * max(abs(position), abs(shown))`.
- Mutated text (BinOp): `tolerance = half * scale * (_ABSOLUTE * max(abs(position), abs(shown)))`.
- Kill sketch: **`tick-half`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py tick-half` rc 1.
- Failing output: `AssertionError: tick-half: expected True, got False`.
- **Existing kill:** `tests/test_figure_corpus.py::test_corpus_case[honest-small-sci]`.
- Command: `cd /home/eturkes/Projects/figure-verification && PYTHONPATH=.scratch/agents/q4/reviewer-4-src UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy uv run --no-sync --locked python -m pytest --no-cov -p no:cacheprovider -q -x tests/test_figure_corpus.py::test_corpus_case[honest-small-sci] tests/test_figure_corpus.py::test_corpus_case[minor-tick-honest] tests/test_figure_corpus.py::test_corpus_case[cr-shown-offset-text] tests/test_figure_judge.py::test_j3_numeric_label_forms[money] tests/test_figure_judge.py::test_j3_numeric_label_forms[engineering]` → rc 1.
- Existing-test red: `E           AssertionError: Blocked(reason='tick_label_mismatch', site=None)`.

### F3639 — `src/verifier/figure/ticks.py:119:20 node 9` (TSV row 3639)

- Severity: **minor**. Contract: half-digit and relative allowances add; multiplying/subtracting falsely refuses a true tiny label.
- Original anchor: `tolerance = half * scale + _ABSOLUTE * max(abs(position), abs(shown))`.
- Mutated text (BinOp): `tolerance = half * scale - _ABSOLUTE * max(abs(position), abs(shown))`.
- Kill sketch: **`tick-exact`** above. Baseline rc 0; mutated command `… python /tmp/reviewer-4-probe.py tick-exact` rc 1.
- Failing output: `AssertionError: tick-exact: expected True, got False`.
- **Uncovered in targeted controls:** no existing kill demonstrated; MAIN must add/locate a boundary test before closing this credit row.
- Existing controls run, all survived: `tests/test_figure_corpus.py::test_corpus_case[honest-small-sci]`, `tests/test_figure_corpus.py::test_corpus_case[minor-tick-honest]`, `tests/test_figure_corpus.py::test_corpus_case[cr-shown-offset-text]`, `tests/test_figure_judge.py::test_j3_numeric_label_forms[money]`, `tests/test_figure_judge.py::test_j3_numeric_label_forms[engineering]` (rc 0).

## Verification + limits

- This reviewer changed no tracked file; no git writes; no shared environment resync. Isolated source import canary printed `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-4-src/verifier/__init__.py` on every probe. The numerical/judge source files matched `a0b1861` (the mutation-credit target) at review time.
- Baselines: all 13 witness kinds rc 0; 12 unique existing controls passed. Mutants: 22 distinct variants; 31 row witnesses red by observable return/verdict/refusal (not source inspection). Existing controls: 15 distinct variants killed; 7 variants survived the bounded control selection. Pair counts: 21 existing-killed / 10 uncovered.
- An initial replacement of `passed = Passed(...)` replaced only the first line and produced SyntaxError/pytest rc 4. That attempt is discarded. The corrected full-statement mutation produces `None`, the four original cases return `NoneType`, and the existing positive-result test fails its `isinstance(None, Passed)` assertion with rc 1. Every reported result uses the corrected evidence.
- Existing-test search was targeted: `tests/test_figure_values.py`, `tests/test_figure_judge.py`, tick/hist corpus entries and `tools/mutants/{ticks,mark_rules}.toml`. No full suite, poodle rerun, gate, Pyodide leg, or test of every open mutant was run. The absence of a kill outside the selected controls remains **unconfirmed**. This report adjudicates survivors; it does not itself confer mutation-tool credit.
- Evidence retained as validator/harvest inputs: `/tmp/reviewer-4-results.json`, `/tmp/reviewer-4-candidates.json`, `/tmp/reviewer-4-probe.py`, `/tmp/reviewer-4-run-probes.py`; the source copy is restored, not left mutated.

## Register

- Positive corpus grading admits any non-`Blocked` return, including `None` (`tests/test_figure_corpus.py:47`, exact bytes `assert not isinstance(verdict, Blocked), verdict`). This is already represented by the eight specified judge rows, not a second finding or permission to change the gate.
- No unrelated product defect confirmed.

## Validator

- `python3 /home/eturkes/Projects/figure-verification/.scratch/agents/q4/seed.py check reviewer-4 6,7,8,9` → **rc 0**, `reviewer-4: 3958 rows, 0 problems`.
- Positive control: temporarily set the first ruling to `unknown` → **rc 1**, `line 2: ruling 'unknown'`; restored exact original TSV bytes (sha256 equality), reran → **rc 0**.
- Immutable columns + row order compared to the seed source → all 3,958 rows equal, duplicates preserved. The three mutated source files restored byte-identical to primary; shared `verifier.pth` still names the primary `src`.
- All checks required by this brief are complete. Full gate/mutation-credit tool/bundle tests not run, as scoped above.

reviewer-4-DONE-1
