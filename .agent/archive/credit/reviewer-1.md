# reviewer-1 — R294 survivor rulings

## Contract fixed before adjudication

Target = node 0, `tests/test_figure_values.py::test_cr_r294_a_reference_reads_pandas_own_whole_column_reduction[group-sum]`; 1,179 seeded executed-line survivor rows. Read revision = `66c3fe9e054fb3c3abc5424dc62120efc290bfcf`; mutation record = `7b61aa2`, source `a0b1861`. Reviewed source + node have no intervening diff.

C0: an admitted numeric column's whole-column pandas `groupby(...).sum()` (Kahan) remains a valid reference value; exact membership rejects a drawn scalar absent from the cells and admitted whole-column reductions, with the reference's source site. The test's one-ULP perturbation pins that exactness, not a tolerance band. Sibling `sum` / `mean` parameters own their positive pairwise-sum/mean acceptance paths; an erroneous extra candidate can still break this control's negative clause. Domain = admitted numeric data, not the fixture's eight constants; numeric values include integer and singleton columns, with unrelated text columns ignored.

Sources: `tests/test_figure_values.py:708-730` (parametrization, docstring, assertions); `.agent/review.md:195` (R294 acceptance/fix/control); `src/verifier/figure/explain.py:182-206,982-1024` (`_group`, `_column_values`, `_explain_reference`); `.claude/rules/figure.md` reference-value / exact-binary64 rules. C0 × every seeded row = fixed check set. Other figure integrity, CSV-profile, anchoring, and presentation contracts stay outside C0; their incidental execution does not widen this check set.

## Verdict table

| node | rows | specified | open | never-executed class ruling |
|---|---:|---:|---:|---|
| 0 | 1,179 | 31 (all killed by existing tests) | 1,148 | **mixed; blanket `open` rejected** — 4,511 counted survivors; confirmed C0-bearing member N0 below. Full membership unavailable, so no all-member assurance. |

All 31 `specified` rows = gaps in this individual node, **not uncovered suite behavior**: seven existing tests kill all 31 on actual mutated copies. No new test is requested for these rows. TSV preserves the full seeded row multiset, including same-location/operator alternatives.

### Existing killer summary

| mutants | existing test |
|---:|---|
| 17 | `tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum` |
| 2 | `tests/test_figure_values.py::test_v6_reference_values_from_a_column` |
| 2 | `tests/test_figure_values.py::test_cr_r294_a_reference_reads_pandas_own_whole_column_reduction[mean]` |
| 1 | `tests/test_figure_values.py::test_sources_profile_faults_leave_columns_as_text` |
| 4 | `tests/test_pysrc_aggregate.py::test_b4_reductions_retain_dtype` |
| 3 | `tests/test_pysrc_aggregate.py::test_r1_float_sum_is_kahan_not_naive_or_fsum` |
| 2 | `tests/test_pysrc_aggregate.py::test_r2_float_mean_is_kahan_sum_over_count` |

## Evidence + replay

Owned copy = `.scratch/agents/q4/reviewer-1-src/`; every mutant trial writes that copy only, restores source bytes in `finally`, removes its copied bytecode caches, and prints the import canary. Every pytest child overrides `pythonpath` to the owned copy; no editable-install resync. Canary = `/home/eturkes/Projects/figure-verification/.scratch/agents/q4/reviewer-1-src/verifier/__init__.py`.

Commands (run from repository root; `export UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy`):

- Baseline candidate killers: `uv run --no-sync --locked python /tmp/reviewer-1-existing.py baseline` → rc 0, **7 passed**.
- Specified rows: `heavy .venv/bin/python /tmp/reviewer-1-existing.py mutants` → driver rc 0; **31/31 child runs rc 1**, each canary true; **54.29 s**. Per-row source splice uses poodle's default operator, exact location + mutated-line matching, and UTF-8 byte offsets; `/tmp/reviewer-1-existing-results.json` + `/tmp/reviewer-1-existing-<row>.log`.
- Independent end-to-end kill sketches: `PYTHONPATH=.scratch/agents/q4/reviewer-1-src uv run --no-sync --locked python /tmp/reviewer-1-witness.py check all` → rc 0, **31 checks / 0 failures**; `uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant <row>` → rc 1 on each corresponding copied mutant. Every sketch runs the real reader + judge; `/tmp/reviewer-1-red-<row>.log`.
- Numeric search helper `/tmp/reviewer-1-probe.py` = bounded witness discovery, **not** an all-input proof or mutation-credit run. Concrete witnesses + exact trial outputs decide the findings below. Long random witnesses replaced by simpler repeated-value controls in `/tmp/reviewer-1-witnesses.json`.

Common sketch program: imports pandas + pyplot; reads `amount` CSV (plus `label` where stated); makes non-identity numeric axes on source line 5; draws `plt.axhline(value)` on line 6. A positive witness computes `df.groupby(lambda _: 0)['amount'].sum().iloc[0]`; a negative draws the stated literal. Sources = that CSV + request `total amount`. Baseline positive ⇒ `Passed`; negative ⇒ `Blocked('value_not_found', 6)`. Non-identity limits isolate arithmetic from register R1 below.

## Specified rows
### F01 — `src/verifier/figure/computed.py:43:17 node 0` (Number; row 197)

Severity = minor (individual-node coverage; existing kill confirmed). C0: pairwise candidates preserve the exact allowed reduction bits instead of admitting another scalar.

Mutated text:
```text
_UNROLL: Final = 9
```

Kill sketch: `amount = [0.1] * 8`; draw `0.7999999999999999`.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 197` → rc 1:
```text
row=197 expected=Blocked actual=Passed FAIL
```

Existing killer = `tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E           assert 1159006.5103939997 == 1159006.510394
E            +  where 1159006.5103939997 = <function pairwise_sum at 0x7fe272609010>([504441.92, 739405.71, 554883.0, -25687.154932, 406741.79, -546272.45, ...])
E            +    where <function pairwise_sum at 0x7fe272609010> = computed.pairwise_sum
```

### F02 — `src/verifier/figure/computed.py:44:16 node 0` (Number; row 198)

Severity = minor (individual-node coverage; existing kill confirmed). C0: pairwise candidates preserve the exact allowed reduction bits instead of admitting another scalar.

Mutated text:
```text
_BLOCK: Final = 127
```

Kill sketch: `amount = [0.1] * 128`; draw `12.799999999999999`.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 198` → rc 1:
```text
row=198 expected=Blocked actual=Passed FAIL
```

Existing killer = `tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E           assert 5715611.907784998 == 5715611.907785
E            +  where 5715611.907784998 = <function pairwise_sum at 0x7f20a0281010>([946742.76, 394101.651395, 743392.0, -299323.745828, -871001.534023, -829145.0, ...])
E            +    where <function pairwise_sum at 0x7f20a0281010> = computed.pairwise_sum
```

### F03 — `src/verifier/figure/computed.py:44:16 node 0` (Number; row 199)

Severity = minor (individual-node coverage; existing kill confirmed). C0: pairwise candidates preserve the exact allowed reduction bits instead of admitting another scalar.

Mutated text:
```text
_BLOCK: Final = 129
```

Kill sketch: `amount = [0.1] * 129`; draw `12.900000000000002`.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 199` → rc 1:
```text
row=199 expected=Blocked actual=Passed FAIL
```

Existing killer = `tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E           assert 9073504.890222998 == 9073504.890223
E            +  where 9073504.890222998 = <function pairwise_sum at 0x7f343bdb5010>([-167556.55, -477063.886918, -564508.154169, -873294.0, -678104.34, 295621.0, ...])
E            +    where <function pairwise_sum at 0x7f343bdb5010> = computed.pairwise_sum
```

### F04 — `src/verifier/figure/computed.py:50:7 node 0` (Compare; row 200)

Severity = minor (individual-node coverage; existing kill confirmed). C0: pairwise candidates preserve the exact allowed reduction bits instead of admitting another scalar.

Mutated text:
```text
if count <= _UNROLL:
```

Kill sketch: `amount = [0.1] * 8`; draw `0.7999999999999999`.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 200` → rc 1:
```text
row=200 expected=Blocked actual=Passed FAIL
```

Existing killer = `tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E           assert 1159006.5103939997 == 1159006.510394
E            +  where 1159006.5103939997 = <function pairwise_sum at 0x7f29ded71010>([504441.92, 739405.71, 554883.0, -25687.154932, 406741.79, -546272.45, ...])
E            +    where <function pairwise_sum at 0x7f29ded71010> = computed.pairwise_sum
```

### F05 — `src/verifier/figure/computed.py:50:7 node 0` (Compare; row 201)

Severity = minor (individual-node coverage; existing kill confirmed). C0: a column shorter than the unroll width still has a defined whole-column sum.

Mutated text:
```text
if count >= _UNROLL:
```

Kill sketch: `amount = [0.1, 0.2, 0.3]`; draw the whole-column Kahan group sum.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 201` → rc 1:
```text
row=201 expected=Passed actual=IndexError: list index out of range FAIL
```

Existing killer = `tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E           IndexError: list index out of range
FAILED tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum
```

### F06 — `src/verifier/figure/computed.py:55:7 node 0` (Compare; row 202)

Severity = minor (individual-node coverage; existing kill confirmed). C0: pairwise candidates preserve the exact allowed reduction bits instead of admitting another scalar.

Mutated text:
```text
if count < _BLOCK:
```

Kill sketch: `amount = [0.1] * 128`; draw `12.799999999999999`.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 202` → rc 1:
```text
row=202 expected=Blocked actual=Passed FAIL
```

Existing killer = `tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E           assert 5715611.907784998 == 5715611.907785
E            +  where 5715611.907784998 = <function pairwise_sum at 0x7f1bc5481010>([946742.76, 394101.651395, 743392.0, -299323.745828, -871001.534023, -829145.0, ...])
E            +    where <function pairwise_sum at 0x7f1bc5481010> = computed.pairwise_sum
```

### F07 — `src/verifier/figure/computed.py:57:14 node 0` (BinOp; row 203)

Severity = minor (individual-node coverage; existing kill confirmed). C0: a non-multiple-of-eight column never reads a lane past its final cell.

Mutated text:
```text
end = count + count % _UNROLL
```

Kill sketch: `amount = [0.1] * 9`; draw the whole-column Kahan group sum.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 203` → rc 1:
```text
row=203 expected=Passed actual=IndexError: tuple index out of range FAIL
```

Existing killer = `tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E                   IndexError: list index out of range
FAILED tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum
```

### F08 — `src/verifier/figure/computed.py:61:16 node 0` (BinOp; row 204)

Severity = minor (individual-node coverage; existing kill confirmed). C0: pairwise candidates preserve the exact allowed reduction bits instead of admitting another scalar.

Mutated text:
```text
total = (lanes[0] + lanes[1] + (lanes[2] + lanes[3])) * (lanes[4] + lanes[5] + (lanes[6] + lanes[7]))
```

Kill sketch: `amount = [0.1] * 8`; draw `0.16000000000000003`.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 204` → rc 1:
```text
row=204 expected=Blocked actual=Passed FAIL
```

Existing killer = `tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E           assert -1088714233665.7955 == 1159006.510394
E            +  where -1088714233665.7955 = <function pairwise_sum at 0x7f5ca72ed010>([504441.92, 739405.71, 554883.0, -25687.154932, 406741.79, -546272.45, ...])
E            +    where <function pairwise_sum at 0x7f5ca72ed010> = computed.pairwise_sum
```

### F09 — `src/verifier/figure/computed.py:61:16 node 0` (BinOp; row 205)

Severity = minor (individual-node coverage; existing kill confirmed). C0: pairwise candidates preserve the exact allowed reduction bits instead of admitting another scalar.

Mutated text:
```text
total = lanes[0] + lanes[1] + (lanes[2] + lanes[3]) - (lanes[4] + lanes[5] + (lanes[6] + lanes[7]))
```

Kill sketch: `amount = [0.1, 0.1, 0.1, 0.1, 0.2, 0.2, 0.2, 0.2]`; draw `-0.4`.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 205` → rc 1:
```text
row=205 expected=Blocked actual=Passed FAIL
```

Existing killer = `tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E           assert 2387080.439742 == 1159006.510394
E            +  where 2387080.439742 = <function pairwise_sum at 0x7f99a1bc9010>([504441.92, 739405.71, 554883.0, -25687.154932, 406741.79, -546272.45, ...])
E            +    where <function pairwise_sum at 0x7f99a1bc9010> = computed.pairwise_sum
```

### F10 — `src/verifier/figure/computed.py:61:24 node 0` (Number; row 206)

Severity = minor (individual-node coverage; existing kill confirmed). C0: pairwise candidates preserve the exact allowed reduction bits instead of admitting another scalar.

Mutated text:
```text
total = ((lanes[-1] + lanes[1]) + (lanes[2] + lanes[3])) + (
```

Kill sketch: `amount = [0.0, 1000000000000.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.000122]`; draw `1000000000000.0002`.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 206` → rc 1:
```text
row=206 expected=Blocked actual=Passed FAIL
```

Existing killer = `tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E           assert 100359.28572000004 == 1159006.510394
E            +  where 100359.28572000004 = <function pairwise_sum at 0x7ff848bd5010>([504441.92, 739405.71, 554883.0, -25687.154932, 406741.79, -546272.45, ...])
E            +    where <function pairwise_sum at 0x7ff848bd5010> = computed.pairwise_sum
```

### F11 — `src/verifier/figure/computed.py:61:24 node 0` (Number; row 207)

Severity = minor (individual-node coverage; existing kill confirmed). C0: pairwise candidates preserve the exact allowed reduction bits instead of admitting another scalar.

Mutated text:
```text
total = ((lanes[1] + lanes[1]) + (lanes[2] + lanes[3])) + (
```

Kill sketch: `amount = [0.0, 0.000061, 1000000000000.0, 0.0, 0.0, 0.0, 0.0, 0.0]`; draw `1000000000000.0001`.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 207` → rc 1:
```text
row=207 expected=Blocked actual=Passed FAIL
```

Existing killer = `tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E           assert 1393970.300394 == 1159006.510394
E            +  where 1393970.300394 = <function pairwise_sum at 0x7f05ea6e9010>([504441.92, 739405.71, 554883.0, -25687.154932, 406741.79, -546272.45, ...])
E            +    where <function pairwise_sum at 0x7f05ea6e9010> = computed.pairwise_sum
```

### F12 — `src/verifier/figure/computed.py:61:35 node 0` (Number; row 208)

Severity = minor (individual-node coverage; existing kill confirmed). C0: pairwise candidates preserve the exact allowed reduction bits instead of admitting another scalar.

Mutated text:
```text
total = ((lanes[0] + lanes[0]) + (lanes[2] + lanes[3])) + (
```

Kill sketch: `amount = [0.000061, 0.0, 1000000000000.0, 0.0, 0.0, 0.0, 0.0, 0.0]`; draw `1000000000000.0001`.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 208` → rc 1:
```text
row=208 expected=Blocked actual=Passed FAIL
```

Existing killer = `tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E           assert 924042.7203940002 == 1159006.510394
E            +  where 924042.7203940002 = <function pairwise_sum at 0x7f59358e1010>([504441.92, 739405.71, 554883.0, -25687.154932, 406741.79, -546272.45, ...])
E            +    where <function pairwise_sum at 0x7f59358e1010> = computed.pairwise_sum
```

### F13 — `src/verifier/figure/computed.py:61:35 node 0` (Number; row 209)

Severity = minor (individual-node coverage; existing kill confirmed). C0: pairwise candidates preserve the exact allowed reduction bits instead of admitting another scalar.

Mutated text:
```text
total = ((lanes[0] + lanes[2]) + (lanes[2] + lanes[3])) + (
```

Kill sketch: `amount = [1000000000000.0, 0.0, 0.000122, 0.0, 0.0, 0.0, 0.0, 0.0]`; draw `1000000000000.0002`.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 209` → rc 1:
```text
row=209 expected=Blocked actual=Passed FAIL
```

Existing killer = `tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E           assert 974483.800394 == 1159006.510394
E            +  where 974483.800394 = <function pairwise_sum at 0x7f35fd379010>([504441.92, 739405.71, 554883.0, -25687.154932, 406741.79, -546272.45, ...])
E            +    where <function pairwise_sum at 0x7f35fd379010> = computed.pairwise_sum
```

### F14 — `src/verifier/figure/computed.py:61:48 node 0` (Number; row 210)

Severity = minor (individual-node coverage; existing kill confirmed). C0: pairwise candidates preserve the exact allowed reduction bits instead of admitting another scalar.

Mutated text:
```text
total = ((lanes[0] + lanes[1]) + (lanes[1] + lanes[3])) + (
```

Kill sketch: `amount = [1000000000000.0, 0.000122, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]`; draw `1000000000000.0002`.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 210` → rc 1:
```text
row=210 expected=Blocked actual=Passed FAIL
```

Existing killer = `tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E           assert 1343529.220394 == 1159006.510394
E            +  where 1343529.220394 = <function pairwise_sum at 0x7feee78d5010>([504441.92, 739405.71, 554883.0, -25687.154932, 406741.79, -546272.45, ...])
E            +    where <function pairwise_sum at 0x7feee78d5010> = computed.pairwise_sum
```

### F15 — `src/verifier/figure/computed.py:61:48 node 0` (Number; row 211)

Severity = minor (individual-node coverage; existing kill confirmed). C0: pairwise candidates preserve the exact allowed reduction bits instead of admitting another scalar.

Mutated text:
```text
total = ((lanes[0] + lanes[1]) + (lanes[3] + lanes[3])) + (
```

Kill sketch: `amount = [1000000000000.0, 0.0, 0.0, 0.000061, 0.0, 0.0, 0.0, 0.0]`; draw `1000000000000.0001`.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 211` → rc 1:
```text
row=211 expected=Blocked actual=Passed FAIL
```

Existing killer = `tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E           assert 578436.355462 == 1159006.510394
E            +  where 578436.355462 = <function pairwise_sum at 0x7fab97b9d010>([504441.92, 739405.71, 554883.0, -25687.154932, 406741.79, -546272.45, ...])
E            +    where <function pairwise_sum at 0x7fab97b9d010> = computed.pairwise_sum
```

### F16 — `src/verifier/figure/computed.py:61:59 node 0` (Number; row 212)

Severity = minor (individual-node coverage; existing kill confirmed). C0: pairwise candidates preserve the exact allowed reduction bits instead of admitting another scalar.

Mutated text:
```text
total = ((lanes[0] + lanes[1]) + (lanes[2] + lanes[2])) + (
```

Kill sketch: `amount = [1000000000000.0, 0.0, 0.000061, 0.0, 0.0, 0.0, 0.0, 0.0]`; draw `1000000000000.0001`.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 212` → rc 1:
```text
row=212 expected=Blocked actual=Passed FAIL
```

Existing killer = `tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E           assert 1739576.665326 == 1159006.510394
E            +  where 1739576.665326 = <function pairwise_sum at 0x7f003e275010>([504441.92, 739405.71, 554883.0, -25687.154932, 406741.79, -546272.45, ...])
E            +    where <function pairwise_sum at 0x7f003e275010> = computed.pairwise_sum
```

### F17 — `src/verifier/figure/computed.py:61:59 node 0` (Number; row 213)

Severity = minor (individual-node coverage; existing kill confirmed). C0: pairwise candidates preserve the exact allowed reduction bits instead of admitting another scalar.

Mutated text:
```text
total = ((lanes[0] + lanes[1]) + (lanes[2] + lanes[4])) + (
```

Kill sketch: `amount = [1000000000000.0, 0.0, 0.0, 0.0, 0.000122, 0.0, 0.0, 0.0]`; draw `1000000000000.0002`.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 213` → rc 1:
```text
row=213 expected=Blocked actual=Passed FAIL
```

Existing killer = `tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E           assert 1591435.455326 == 1159006.510394
E            +  where 1591435.455326 = <function pairwise_sum at 0x7fe44c1b1010>([504441.92, 739405.71, 554883.0, -25687.154932, 406741.79, -546272.45, ...])
E            +    where <function pairwise_sum at 0x7fe44c1b1010> = computed.pairwise_sum
```

### F18 — `src/verifier/figure/explain.py:985:18 node 0` (Keyword; row 352)

Severity = minor (individual-node coverage; existing kill confirmed). C0: numeric column stays usable beside a text column; None-valued columns are skipped.

Mutated text:
```text
if numbers is ' ':
```

Kill sketch: `amount = [0.1, 0.2, 0.3]`; text column `label = ['a', 'b', 'c']`; draw the whole-column Kahan group sum.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 352` → rc 1:
```text
row=352 expected=Passed actual=TypeError: 'NoneType' object is not iterable FAIL
```

Existing killer = `tests/test_figure_values.py::test_v6_reference_values_from_a_column`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_values.py::test_v6_reference_values_from_a_column'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E       TypeError: 'NoneType' object is not iterable
FAILED tests/test_figure_values.py::test_v6_reference_values_from_a_column - ...
```

### F19 — `src/verifier/figure/explain.py:997:21 node 0` (BinOp; row 359)

Severity = minor (individual-node coverage; existing kill confirmed). C0: the scalar candidate set contains true reductions, never total times row count.

Mutated text:
```text
found |= {total, total * len(numbers)}
```

Kill sketch: `amount = [0.1, 0.2, 0.3]`; draw `1.8000000000000003`.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 359` → rc 1:
```text
row=359 expected=Blocked actual=Passed FAIL
```

Existing killer = `tests/test_figure_values.py::test_cr_r294_a_reference_reads_pandas_own_whole_column_reduction[mean]`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_values.py::test_cr_r294_a_reference_reads_pandas_own_whole_column_reduction[mean]'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E       assert False
E        +  where False = isinstance(Blocked(reason='value_not_found', site=5), Passed)
E        +    where Blocked(reason='value_not_found', site=5) = _judge(("import pandas as pd\nimport matplotlib.pyplot as plt\nfrom io import StringIO\ndf = pd.read_csv(StringIO('amount\\n731.48\\n-96.335\\n-620.196\\n-48.474\\n586.0\\n-106.8\\n-818.659\\n268.906\\n'))\n" + "plt.axhline(df['amount'].mean())\n"), Sources(files=(('t.csv', b'amount\n731.48\n-96.335\n-620.196\n-48.474\n586.0\n-106.8\n-818.659\n268.906\n'),), request='total amount', anchoring='strict', aliases=()))
```

### F20 — `src/verifier/figure/explain.py:997:21 node 0` (BinOp; row 360)

Severity = minor (individual-node coverage; existing kill confirmed). C0: the scalar candidate set contains true reductions, never total minus row count.

Mutated text:
```text
found |= {total, total - len(numbers)}
```

Kill sketch: `amount = [0.1, 0.2, 0.3]`; draw `-2.4`.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 360` → rc 1:
```text
row=360 expected=Blocked actual=Passed FAIL
```

Existing killer = `tests/test_figure_values.py::test_cr_r294_a_reference_reads_pandas_own_whole_column_reduction[mean]`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_values.py::test_cr_r294_a_reference_reads_pandas_own_whole_column_reduction[mean]'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E       assert False
E        +  where False = isinstance(Blocked(reason='value_not_found', site=5), Passed)
E        +    where Blocked(reason='value_not_found', site=5) = _judge(("import pandas as pd\nimport matplotlib.pyplot as plt\nfrom io import StringIO\ndf = pd.read_csv(StringIO('amount\\n731.48\\n-96.335\\n-620.196\\n-48.474\\n586.0\\n-106.8\\n-818.659\\n268.906\\n'))\n" + "plt.axhline(df['amount'].mean())\n"), Sources(files=(('t.csv', b'amount\n731.48\n-96.335\n-620.196\n-48.474\n586.0\n-106.8\n-818.659\n268.906\n'),), request='total amount', anchoring='strict', aliases=()))
```

### F21 — `src/verifier/figure/explain.py:1009:26 node 0` (Number; row 364)

Severity = minor (individual-node coverage; existing kill confirmed). C0: one is not an unconditional reference value when the source never supplies it.

Mutated text:
```text
if point.value == 1.0 or point.value in context.request.numbers:
```

Kill sketch: `amount = [0.1, 0.2, 0.3]`; draw `1.0`.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 364` → rc 1:
```text
row=364 expected=Blocked actual=Passed FAIL
```

Existing killer = `tests/test_figure_values.py::test_v6_reference_values_from_a_column`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_values.py::test_v6_reference_values_from_a_column'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E       AssertionError: assert False
E        +  where False = isinstance(Blocked(reason='value_not_found', site=4), Passed)
FAILED tests/test_figure_values.py::test_v6_reference_values_from_a_column - ...
```

### F22 — `src/verifier/figure/sources.py:63:86 node 0` (Keyword; row 932)

Severity = minor (individual-node coverage; existing kill confirmed). C0: a text column does not crash the reference search for a numeric column.

Mutated text:
```text
numbers = _numeric_values(texts) if _classify_column(texts) == "numeric" else ' '
```

Kill sketch: `amount = [0.1, 0.2, 0.3]`; text column `label = ['a', 'b', 'c']`; draw the whole-column Kahan group sum.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 932` → rc 1:
```text
row=932 expected=Passed actual=IndexError: string index out of range FAIL
```

Existing killer = `tests/test_figure_values.py::test_sources_profile_faults_leave_columns_as_text`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_figure_values.py::test_sources_profile_faults_leave_columns_as_text'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E       AssertionError: assert [('k', ' '), ..., ('w', None)] == [('k', None),..., ('w', None)]
E         
E         At index 0 diff: ('k', ' ') != ('k', None)
```

### F23 — `src/verifier/pysrc/aggregate.py:58:19 node 0` (FuncCall; row 1005)

Severity = minor (individual-node coverage; existing kill confirmed). C0: an admitted integer-column whole sum returns a usable reduction.

Mutated text:
```text
_DTYPE_RETAINING = None
```

Kill sketch: `amount = [1, 2, 3]`; draw the whole-column Kahan group sum.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 1005` → rc 1:
```text
row=1005 expected=Passed actual=TypeError: argument of type 'NoneType' is not a container or iterable FAIL
```

Existing killer = `tests/test_pysrc_aggregate.py::test_b4_reductions_retain_dtype`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_pysrc_aggregate.py::test_b4_reductions_retain_dtype'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E       TypeError: argument of type 'NoneType' is not a container or iterable
FAILED tests/test_pysrc_aggregate.py::test_b4_reductions_retain_dtype - TypeE...
```

### F24 — `src/verifier/pysrc/aggregate.py:101:19 node 0` (BinOp; row 1015)

Severity = minor (individual-node coverage; existing kill confirmed). C0: Kahan compensation subtracts its error instead of adding it.

Mutated text:
```text
adjusted = value + compensation
```

Kill sketch: `amount = [0.1, 0.2, 0.3]`; draw the whole-column Kahan group sum.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 1015` → rc 1:
```text
row=1015 expected=Passed actual=Blocked(reason='value_not_found', site=6) FAIL
```

Existing killer = `tests/test_pysrc_aggregate.py::test_r1_float_sum_is_kahan_not_naive_or_fsum`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_pysrc_aggregate.py::test_r1_float_sum_is_kahan_not_naive_or_fsum'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E       AssertionError: assert '0x1.0000000000000p-19' == '0x1.1000000000000p-19'
E         
E         - 0x1.1000000000000p-19
```

### F25 — `src/verifier/pysrc/aggregate.py:104:39 node 0` (UnaryOp; row 1018)

Severity = minor (individual-node coverage; existing kill confirmed). C0: finite Kahan compensation survives into the next addition.

Mutated text:
```text
if math.isnan(compensation) or mean or math.isfinite(compensation):
```

Kill sketch: `amount = [0.1, 0.2, 0.3]`; draw the whole-column Kahan group sum.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 1018` → rc 1:
```text
row=1018 expected=Passed actual=Blocked(reason='value_not_found', site=6) FAIL
```

Existing killer = `tests/test_pysrc_aggregate.py::test_r1_float_sum_is_kahan_not_naive_or_fsum`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_pysrc_aggregate.py::test_r1_float_sum_is_kahan_not_naive_or_fsum'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E       AssertionError: assert '0x1.0000000000000p-19' == '0x1.1000000000000p-19'
E         
E         - 0x1.1000000000000p-19
```

### F26 — `src/verifier/pysrc/aggregate.py:104:52 node 0` (FuncCall; row 1019)

Severity = minor (individual-node coverage; existing kill confirmed). C0: finite Kahan compensation survives into the next addition.

Mutated text:
```text
if math.isnan(compensation) or not (mean or None):
```

Kill sketch: `amount = [0.1, 0.2, 0.3]`; draw the whole-column Kahan group sum.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 1019` → rc 1:
```text
row=1019 expected=Passed actual=Blocked(reason='value_not_found', site=6) FAIL
```

Existing killer = `tests/test_pysrc_aggregate.py::test_r1_float_sum_is_kahan_not_naive_or_fsum`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_pysrc_aggregate.py::test_r1_float_sum_is_kahan_not_naive_or_fsum'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E       AssertionError: assert '0x1.0000000000000p-19' == '0x1.1000000000000p-19'
E         
E         - 0x1.1000000000000p-19
```

### F27 — `src/verifier/pysrc/aggregate.py:112:18 node 0` (Number; row 1021)

Severity = minor (individual-node coverage; existing kill confirmed). C0: a one-row numeric column has valid sum/mean/extrema; the extrema scan stays in bounds.

Mutated text:
```text
best = values[1]
```

Kill sketch: `amount = [0.1] * 1`; draw the whole-column Kahan group sum.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 1021` → rc 1:
```text
row=1021 expected=Passed actual=IndexError: tuple index out of range FAIL
```

Existing killer = `tests/test_pysrc_aggregate.py::test_b4_reductions_retain_dtype`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_pysrc_aggregate.py::test_b4_reductions_retain_dtype'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E       IndexError: tuple index out of range
FAILED tests/test_pysrc_aggregate.py::test_b4_reductions_retain_dtype - Index...
```

### F28 — `src/verifier/pysrc/aggregate.py:126:19 node 0` (BinOp; row 1030)

Severity = minor (individual-node coverage; existing kill confirmed). C0: the scalar candidate set contains true reductions, never Kahan total times row count.

Mutated text:
```text
return kahan_sum(values, mean=True) * len(values)
```

Kill sketch: `amount = [0.1, 0.2, 0.3]`; draw `1.7999999999999998`.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 1030` → rc 1:
```text
row=1030 expected=Blocked actual=Passed FAIL
```

Existing killer = `tests/test_pysrc_aggregate.py::test_r2_float_mean_is_kahan_sum_over_count`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_pysrc_aggregate.py::test_r2_float_mean_is_kahan_sum_over_count'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E       AssertionError: assert '0x1.1000000000000p-17' == '0x1.1000000000000p-21'
E         
E         - 0x1.1000000000000p-21
```

### F29 — `src/verifier/pysrc/aggregate.py:126:19 node 0` (BinOp; row 1031)

Severity = minor (individual-node coverage; existing kill confirmed). C0: the scalar candidate set contains true reductions, never Kahan total minus row count.

Mutated text:
```text
return kahan_sum(values, mean=True) - len(values)
```

Kill sketch: `amount = [0.1, 0.2, 0.3]`; draw `-2.4`.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 1031` → rc 1:
```text
row=1031 expected=Blocked actual=Passed FAIL
```

Existing killer = `tests/test_pysrc_aggregate.py::test_r2_float_mean_is_kahan_sum_over_count`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_pysrc_aggregate.py::test_r2_float_mean_is_kahan_sum_over_count'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E       AssertionError: assert '-0x1.ffffef0000000p+1' == '0x1.1000000000000p-21'
E         
E         - 0x1.1000000000000p-21
```

### F30 — `src/verifier/pysrc/aggregate.py:195:15 node 0` (FuncCall; row 1048)

Severity = minor (individual-node coverage; existing kill confirmed). C0: an admitted integer-column sum reads its parsed integer cells.

Mutated text:
```text
integers = None if dtype == "int64" else ()
```

Kill sketch: `amount = [1, 2, 3]`; draw the whole-column Kahan group sum.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 1048` → rc 1:
```text
row=1048 expected=Passed actual=TypeError: 'NoneType' object is not subscriptable FAIL
```

Existing killer = `tests/test_pysrc_aggregate.py::test_b4_reductions_retain_dtype`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_pysrc_aggregate.py::test_b4_reductions_retain_dtype'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E   TypeError: 'NoneType' object is not subscriptable
FAILED tests/test_pysrc_aggregate.py::test_b4_reductions_retain_dtype - TypeE...
```

### F31 — `src/verifier/pysrc/aggregate.py:195:68 node 0` (String; row 1049)

Severity = minor (individual-node coverage; existing kill confirmed). C0: an admitted integer-column sum reads its parsed integer cells.

Mutated text:
```text
integers = tuple(int(text) for text in value_texts) if dtype == 'XXint64XX' else ()
```

Kill sketch: `amount = [1, 2, 3]`; draw the whole-column Kahan group sum.

`uv run --no-sync --locked python /tmp/reviewer-1-witness.py mutant 1049` → rc 1:
```text
row=1049 expected=Passed actual=IndexError: tuple index out of range FAIL
```

Existing killer = `tests/test_pysrc_aggregate.py::test_b4_reductions_retain_dtype`. Exact copied-mutant pytest command = `.venv/bin/python -m pytest -q -x --no-cov -p no:cacheprovider -p reviewer_canary -o 'pythonpath=.scratch/agents/q4/reviewer-1-src tests .' 'tests/test_pysrc_aggregate.py::test_b4_reductions_retain_dtype'` with `PYTHONPATH=.scratch/agents/q4/reviewer-1-src:/tmp/reviewer-1-support`; rc 1, canary true. Failure excerpt:
```text
E   IndexError: tuple index out of range
FAILED tests/test_pysrc_aggregate.py::test_b4_reductions_retain_dtype - Index...
```

## N0 — never-executed survivor class

Class ruling = **mixed / contains specified behavior; blanket `open` is unsound**. Count 4,511 = `7b61aa2` node 0's 5,690 total survivors − 1,179 executed-line rows. No full raw node-0 JSON was available at the brief's former `.scratch/cr/credit/0.json`; a shallow local `.scratch` search found no `credit/0.json`. Individual membership of the remaining 4,510 is **unconfirmed**; the count alone supports no universal contract ruling. The executed TSV is complete independently of this limit.

Counterexample (same poodle default operator; generated and tested): `src/verifier/figure/computed.py:69:11`, `BinOp`:
```text
return pairwise_sum(values[:half]) - pairwise_sum(values[half:])
```
The original `[group-sum]` node has eight cells and never reaches the recursion for `count > 128`; the mutant survives it. Longer admitted columns do reach it, and `_column_values` admits the resulting wrong scalar as a reference candidate. Thus non-execution is not evidence that this contract leaves the behavior open.

`uv run --no-sync --locked python /tmp/reviewer-1-never.py baseline` → rc 0, **2 passed**. `… /tmp/reviewer-1-never.py mutant` → rc 1, **1 failed, 1 passed**: original `[group-sum]` passes; existing `tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum` fails:
```text
E           assert -179779.81919499952 == 9073504.890223
FAILED tests/test_figure_computed.py::test_pairwise_sum_is_numpy_and_pandas_sum
1 failed, 1 passed in 6.69s
```
Logs = `/tmp/reviewer-1-never-baseline.log`, `/tmp/reviewer-1-never-red.log`. This proves at least one member's C0 relevance and existing kill; it does not inventory or rule each remaining member. MAIN must obtain/recreate the full survivor inventory, or scope the credit claim to the ruled set.

## Scripted predicates + checked source scope

Class filling is explicit in `/tmp/reviewer-1-rule.py` + `/tmp/reviewer-1-finish.py`; no sampling of the 1,179 row texts. Every affected module and each row's enclosing function was read. Predicates in order:

1. Original line contains `TypeAlias` / `TypeVar(`, or is `FigureReason` / `RefusalCode` definition ⇒ `open`, annotation-only **for C0** (not global equivalence; separate vocabulary introspection tests may read it).
2. Original line is a `@dataclass` declaration ⇒ `open`, object mutability/layout/constructor form; reference arithmetic never mutates or reflects these records.
3. Original line changes `__all__` ⇒ `open`, explicit imports leave C0 behavior unchanged.
4. Module + enclosing-function range ⇒ ownership class below. Each TSV reason records its file/function/range. This is contract scoping, **not** a claim that the mutant is globally harmless.
5. Numeric/reference exceptions were adjudicated individually: all 31 specified rows have both an independent real-reader/judge witness and an existing pytest kill. Remaining arithmetic cases: whole-column dummy keys always form one group; dummy key name/text/numeric flags are not reduced; extrema can add only a raw cell already in the set (or `None`, not equal to a finite scalar); integral sums remain exact below 2**53 under the admitted int32 × row bounds; non-finite compensation is unreachable under the finite 15-significant-digit profile + row cap; reported dtype is not consumed by `_column_values`; request/shared/matched counters affect reporting, not scalar membership. Mean **removal** is the sibling mean-positive contract; a wrong **added** mean candidate is C0 exactness and specified. Meter changes stay the work-budget contract.

| source (under `src/verifier/`) | checked ownership / predicate | open | specified |
|---|---|---:|---:|
| `__init__.py` | version metadata | 1 | 0 |
| `figure/anchoring.py` | lexical columns / aliases / negation; `_words` through `anchors` (86-294) | 117 | 0 |
| `figure/axes_rules.py` | scale / ticks / clipping / zero / axis-role rules (82-176) | 44 | 0 |
| `figure/columns.py` | drawn-column attribution + anchoring + labels (34-135) | 27 | 0 |
| `figure/computed.py` | type/operation vocabulary (21-39); pairwise numeric exceptions (43-69) | 8 | 17 |
| `figure/description.py` | schema + metadata records / decoder (16-801) | 93 | 0 |
| `figure/explain.py` | types/defaults/canonical metadata; `_group` (182-206), scalar candidates (982-1024), duplicate keys / unreadable causes (1030-1079) | 68 | 4 |
| `figure/inert.py` | text display (14-50), no verdict arithmetic | 46 | 0 |
| `figure/interpret.py` | publication wording/counts (45-226), no verdict arithmetic | 40 | 0 |
| `figure/judge.py` | integrity dispatch (41-76), text listing (100-106), second pass / report routing (112-184); both reference passes use same scalar vocabulary | 42 | 0 |
| `figure/keys.py` | key fields / key-reader defaults (17-30); reference has no data key | 9 | 0 |
| `figure/legends.py` | legend names / keys / candidate metadata (27-196) | 9 | 0 |
| `figure/mark_rules.py` | visibility/finiteness and non-reference mark rules (30-324) | 45 | 0 |
| `figure/parts.py` | family/orientation/axes census (28-311) | 71 | 0 |
| `figure/reader.py` | capture/hooks/caps/style/geometry metadata (37-1157); scalar numeric-reduction logic is outside reader | 213 | 0 |
| `figure/reasons.py` | reason type/default site; C0 passes explicit artist site (11-79) | 6 | 0 |
| `figure/request.py` | typed numbers/ranges (23-91); CSV scalar source has no typed substitution | 11 | 0 |
| `figure/series.py` | keys/names/channels/orientation (29-172); reference defaults do not change the horizontal scalar read | 28 | 0 |
| `figure/shapes.py` | geometry/orientation/colour and non-reference bands (24-169) | 25 | 0 |
| `figure/sources.py` | CSV classification/key/integer metadata (26-71); text-column crash exception row 932 | 14 | 1 |
| `figure/ticks.py` | tick-label parsing and tolerance (19-169), never scalar value matching | 56 | 0 |
| `pysrc/aggregate.py` | types/key ordering/metadata/metering plus individually ruled whole-column numeric paths (35-214) | 48 | 9 |
| `pysrc/budget.py` | meter validation and costs (14-57), not numeric exactness below its bound | 17 | 0 |
| `pysrc/csvread.py` | CSV syntax/profile/row-size ceilings and key classification (29-221), outside numeric reduction contract | 91 | 0 |
| `pysrc/errors.py` | refusal-code annotation (11) | 1 | 0 |
| `pysrc/limits.py` | dataclass representation + configured ceilings (8-22) | 17 | 0 |
| `pysrc/table.py` | export-name metadata (6) | 1 | 0 |

## Register (outside C0)

- R1 — unmutated `reader.run("import matplotlib.pyplot as plt\nplt.axhline(0.6)\n")`, judged with `Sources(request="0.6")`, reports `origin Axes.axhline`, `transform data`, x/y views `(0.0, 1.0)`, and `Blocked(reason='mark_not_in_data', site=2)`. `reader.py::_transform` (560-578) checks `transData` before `yaxis`; equal transforms at identity views explain the misclassification. Explicit non-identity x/y limits isolate the arithmetic witnesses; no target fix made.
- R2 — executed-line-only survivor manifests omit contract-bearing unexecuted branches; N0 disproves a blanket outside-contract class. Complete mutation-credit claim remains blocked on an inventory/ruling, despite the executed table's completion.
- Recorded original tool run rc 2 is not converted into a successful tool run by this review. No full poodle credit rerun, gate, CPython 3.11 test pass, hosted CI, or production smoke was run here.

## Completion checks

- Fixed contract + all 1,179 executed rows adjudicated; 31 specified / 1,148 open; 0 uncovered among specified (31 existing kills verified).
- Original code stayed read-only. Final copy check: 29 Python files byte-equal to primary `src/`, 0 differences. Primary `.venv/lib/python3.14/site-packages/verifier.pth` still names primary `src/`.
- Validator: `python3 /home/eturkes/Projects/figure-verification/.scratch/agents/q4/seed.py check reviewer-1 0` (full row multiset) → rc 0, `reviewer-1: 1179 rows, 0 problems`.

reviewer-1-DONE-1
