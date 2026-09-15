# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M13.6 aggregation: admission, projection, the reduction engine, `barh`, and the certificate.

Contract: `.agent/contracts/m13u6.md` predicate groups A, R, B, plus G11/G9r and K1-K3. Each
docstring carries its predicate's acceptance check; the check is the test's specification and the
contract's wording wins wherever a body would assert more.

The reduction engine reproduces what the EXECUTED program plots, not what is arithmetically
nicest. pandas reduces a float64 group with ordered binary64 Kahan compensation in file-row order,
measured: naive left-to-right differs on 2,761/4,000 admitted-profile CSV groups (worst 8,192 ulp),
`math.fsum` on 1,483 (worst 5,252 ulp), Kahan on 0/16,062. A more precise engine is a less faithful
one, exactly as in M13.5's `expr.py` ruling.

Skeleton: each body is `pytest.skip` until M13.6 lands. Both the skips and this line clear at that
unit's close.
"""

import pytest

# --- A: `groupby` admission and projection -----------------------------------


def test_a1_reduction_vocabulary_and_group_field_are_closed() -> None:
    """A1: `get_args(Reduction.__value__)` equals the hand-stated literal tuple
    `("sum", "mean", "min", "max")`, and `DatasetPlot.__dataclass_fields__` is pinned as an exact
    set including `group: Reduction | None = None`. Hand-stated, never read from production."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_a2_admitted_chain_shape_projects() -> None:
    """A2: `<frame>.groupby('<key>')['<col>'].<reduction>()` bound by assignment projects, with the
    group key as x and the reduced column as y."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_a2_chain_deviations_each_refuse() -> None:
    """A2: one refusal witness per deviation — non-literal key, non-literal column, tuple column
    selection `['revenue', 'orders']` (the design set writes it once), unknown reduction
    `.median()`, a reduction carrying an argument, a chain on an unbound name."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_a3_reset_index_refuses_aggregation_not_projected() -> None:
    """A3: `df.groupby('r')['o'].max().reset_index()` refuses `aggregation_not_projected`. It is a
    different projection, not a decoration: it changes the channel spelling to a column
    subscript."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_a4_aggregate_channels_project() -> None:
    """A4: `plt.bar(g.index, g.values)` and `plt.bar(g.index, g)` both project."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_a4_mixing_aggregate_and_raw_channels_refuses() -> None:
    """A4: `plt.bar(df['region'], g.values)` and `plt.bar(g.index, df['revenue'])` each refuse
    `column_not_from_source` — one mark reads one projection."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_a5_frame_values_admits_then_refuses_at_projection() -> None:
    """A5: `df.values` is ADMITTED (admission has no types) and refused `column_not_from_source` at
    projection. Pinned at BOTH stages separately — one end-to-end assertion cannot say which caught
    it. `g.shape` and `df.loc` refuse `attribute_not_admitted` at admission."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_a6_unplotted_aggregation_refuses() -> None:
    """A6: a bound aggregation no mark references refuses `statement_not_projected`, exactly as an
    unused grid does. The design set writes a bare `data.groupby('city')` once."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_a7_local_fault_precedes_global_count() -> None:
    """A7: a program with a faulty aggregation AND two marks refuses the aggregation fault. Per
    `pysrc.md` the witness must be a SECOND faulty statement in a program admission ADMITS —
    at a first faulty statement the two orders are equivalent."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_a8_atomic_chain_admission_keeps_the_depth_bound() -> None:
    """A8: `np.random.rand(3)` still refuses `attribute_not_admitted` — the atomic aggregation rule
    did not relax `_dotted`'s depth-1 bound. A mutant widening `_admit_aggregation` to accept any
    trailing attribute goes red on `df.groupby('r')['c'].cumsum()`."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


# --- R: the reduction engine, measured against pandas ------------------------


def test_r1_float_sum_is_kahan_not_naive_or_fsum() -> None:
    """R1: differential against pandas over the committed reduction corpus, bit patterns, zero
    disagreements. The naive-sum mutant and the `fsum` mutant must BOTH go red; they are what price
    this predicate."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_r2_float_mean_is_kahan_sum_over_count() -> None:
    """R2: bit-pattern differential, plus a witness where sum-then-divide and a running mean differ
    in the last bit."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_r3_int_mean_casts_before_summing() -> None:
    """R3: MEASURED witness `[2**53, 1, 0]` — pandas `mean` is `0x1.5555555555555p+51`, exact-then-
    divide is `0x1.5555555555556p+51`. Both pinned as hex-float literals; the implementation returns
    pandas'. A mutant computing the exact integer mean goes red here alone. Int64 `sum` stays int64
    and exact."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_r4_extrema_keep_the_first_tied_value_bits() -> None:
    """R4: `[-0.0, +0.0]` gives `-0.0` for both `min` and `max`; reversed gives `+0.0`. Compared as
    bit patterns, since `-0.0 == +0.0`. Unreachable under C10 today and pinned anyway, because the
    profile is what makes it unreachable and the profile is what a later unit widens."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_r5_int_sum_overflow_is_unreachable_under_the_profile() -> None:
    """R5: computes the worst-case magnitude from C10's range and `max_table_rows` and asserts it
    below 2**63. A mutant raising `max_table_rows` past that point makes this go red. pandas WRAPS
    on overflow (`[2**63-1, 1]` -> `-2**63`); the implementation asserts the bound instead."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_r6_nan_never_reaches_a_reduction() -> None:
    """R6: every NA spelling refuses `value_not_in_profile` ahead of the reduction, with a
    call-counting bomb on the reduction proving it never runs. So pandas' NaN-skipping arm and its
    compensation reset are both unreachable and neither is implemented — an unreachable branch would
    fail the 100% branch gate. A profile widening that admits NaN must add both arms."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_r7_group_keys_sort_by_code_point() -> None:
    """R7: sorted-order differential against pandas over a key corpus separating the candidates —
    mixed case, digits vs letters, embedded spaces, non-ASCII, strings differing only past a common
    prefix. A locale-collator mutant and a file-order mutant each go red. MEASURED identical under
    C, C.utf8 and en_US.utf8, with an en_US collation control ordering differently."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_r8_key_dtype_decides_before_key_order() -> None:
    """R8: witness pair — a key column of numeric-looking strings orders differently from one whose
    cells are all numeric. `['2', 'a', '10', '2']` groups to `['10', '2', 'a']`."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_r9_rows_keep_file_order_inside_a_group() -> None:
    """R9: a CSV whose rows for one key are not in value order sums in file order; a mutant sorting
    within the group goes red. This is what makes R1's ordered Kahan well defined."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_r10_group_count_is_bounded_and_charged() -> None:
    """R10: boundary witnesses at `max_groups` and `max_groups + 1`, the second refusing
    `work_budget_exceeded`; a budget bomb asserts the per-row and per-group charge happens."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


# --- B: `barh` and the aggregate profile bound -------------------------------


def test_b1_barh_joins_the_mark_vocabulary_with_bar_argument_order() -> None:
    """B1: `get_args(DatasetMark.__value__)` pinned as the exact literal tuple
    `("line", "scatter", "bar", "barh")`; `plt.barh(g.index, g.values)` puts the key in x and the
    reduced column in y, the same as `bar`."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_b2_barh_carries_bar_integrity_rules() -> None:
    """B2: a duplicate-category `barh` refuses `category_not_unique`. The `match` in
    `_dataset_integrity` is closed over the widened vocabulary, so a missing arm fails
    `mypy --strict` rather than passing silently."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_b3_integer_aggregate_is_bounded_after_aggregation() -> None:
    """B3: two cells at `2147483647` summing to `4294967294` refuse `value_not_in_profile` under
    `bar` and under `barh`; the identical sum under `scatter` or `line` verifies; the negative bound
    carries its own witness at `-4294967296`. A mutant bounding only cells goes red on the first.
    MEASURED: both Pyodide builds raise `OverflowError: Python int too large to convert to C long`
    for bar and barh, while in-int32 controls render."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_b4_reductions_retain_dtype() -> None:
    """B4: witness matrix over (int, float) x (sum, mean, min, max) asserting which combinations B3
    binds. The int-`mean` cell distinguishes dtype retention from a blanket bound — it is float64 by
    R3 and never reaches the renderer's integer branch, so a mutant bounding every aggregate goes
    red there."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


# --- G + K: integrity and the published sentence -----------------------------


def test_g11_per_group_counts_are_published() -> None:
    """G11: certificate byte-pin for one aggregate of each reduction, carrying the group count and
    each group's member count. A mutant dropping the counts goes red."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_g78r_group_counts_sum_to_the_data_row_count() -> None:
    """G78r: for every aggregate, the summed per-group counts equal the CSV's data-row count. A
    `groupby` drops no row — every row joins exactly one group — which is what keeps G7 and G8
    unconditional while aggregation is admitted."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_g9r_line_over_a_group_key_verifies_in_sorted_order() -> None:
    """G9r: a line over a group key verifies, and its table rows are in sorted key order. A
    column-pair line still plots in FILE order — the pin that stops the restatement leaking into the
    non-aggregate path."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_k1_aggregate_interpretation_is_byte_pinned() -> None:
    """K1: `sum of revenue grouped by region - 2 groups - 6 rows`, byte-pinned per reduction and
    hand-stated in the test."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_k2_column_pair_interpretation_is_unchanged() -> None:
    """K2: sha256 pin on the M13.4 column-pair certificate text. `assurance.md` requires
    byte-pinning the unchanged mode whenever a shared message splits by mode."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_k3_cosmetic_fields_stay_out_of_the_sentence() -> None:
    """K3: two programs differing only in `figsize` have byte-identical interpretations and UNEQUAL
    specs. A figure size is not something the figure says about its data."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")
