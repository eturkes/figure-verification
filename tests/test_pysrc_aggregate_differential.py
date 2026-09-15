# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M13.6 differential: the independent aggregation oracle against production.

Contract: `.agent/contracts/m13u6.md` sections A, R, B, W and G11. `tests/oracle_aggregate.py` and
the widened `tests/oracle_dataset.py` are the independent side; this module owns the single
translation between the two vocabularies and escalates a semantic disagreement to the lead instead
of absorbing it into the map.

Two standing requirements from `.claude/rules/assurance.md`, both load-bearing here:
a differential that sets no `PYTHONPATH` can compare a tree against ITSELF through the editable
`.pth`, so every differential ships a LOUD vacuity guard; and the map raises on a name it does not
cover, because a generic lowercase-or-strip rule would absorb a real future divergence.

pandas is absent from the gate venv. The pandas-facing comparison is therefore frozen measurement
under `.agent/measurements/`, and every R predicate here is graded against the contract's
hand-stated MEASURED witnesses, compared as BIT PATTERNS rather than by `==`.

Skeleton: each body is `pytest.skip` until M13.6 lands. Both the skips and this line clear at that
unit's close.
"""

import pytest

# --- the anchor and the vacuity guard ----------------------------------------


def test_aggregate_differential_is_not_vacuous() -> None:
    """Loud guard: oracle and production must resolve to DIFFERENT `__file__` paths, and
    production must resolve from this tree's `src/`. A differential comparing a tree against
    itself passes unconditionally and pins nothing."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_oracle_first_aggregate_bar_is_complete() -> None:
    """Anchor: the oracle projects `df.groupby('region')['revenue'].sum()` plotted as
    `plt.bar(g.index, g.values)` to a complete aggregate chart, with no field left unset. The
    anchor runs BEFORE any differential, so an oracle that refuses everything cannot read as
    agreement."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


# --- R: the reduction engine -------------------------------------------------


def test_r1_differential_float_sum_agrees_bitwise() -> None:
    """R1: over a generated float64 cohort inside C10's fixed-point profile, oracle and production
    sums agree on every bit pattern. Hypothesis-driven, with the cohort drawn so groups carry
    cancelling magnitudes — the shape that separates compensated from naive summation."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_r1_measured_witness_separates_kahan_from_naive_and_fsum() -> None:
    """R1: the four cells `[1000000000.0, 0.000001, 0.000001, -1000000000.0]` give Kahan
    `0x1.1000000000000p-19`, naive `0x1.0000000000000p-19` and `fsum`/Neumaier
    `0x1.0c6f7a0b5ed8dp-19` — three distinct values, hand-stated as hex-float literals. Both the
    oracle and production must return the Kahan value, and the test computes the other two locally
    so the separation is proven rather than asserted."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_r2_differential_float_mean_agrees_bitwise() -> None:
    """R2: `mean` is the Kahan sum divided by the non-NaN count, in that order. Differential over
    the same cohort, bit patterns, plus a witness where sum-then-divide and a running mean differ
    in the last bit."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_r3_differential_int_mean_casts_before_summing() -> None:
    """R3: `[2**53, 1, 0]` — pandas `mean` is `0x1.5555555555555p+51`, exact-then-divide is
    `0x1.5555555555556p+51`. Hand-stated hex-float pins; both sides must return pandas'. Integer
    `sum`/`min`/`max` stay int and exact on the same input."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_r4_differential_extrema_keep_the_first_tied_bits() -> None:
    """R4: `[-0.0, +0.0]` reduces to `-0.0` for both `min` and `max`, and the reversed input to
    `+0.0`. Compared through `math.copysign`/`struct` bit patterns, since `-0.0 == +0.0` hides the
    whole predicate."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_r7_differential_key_order_is_code_point_ascending() -> None:
    """R7: over a key corpus built to separate the candidates — mixed case, digits versus letters,
    embedded spaces, non-ASCII, and strings differing only past a common prefix — oracle and
    production emit the same key order, and it is code-point ascending rather than a locale
    collation or file order."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_r8_differential_dtype_decides_before_order() -> None:
    """R8: the witness pair — `['2', 'a', '10', '2']` orders `['10', '2', 'a']` as strings, while
    an all-numeric key column orders numerically. Both sides agree on both columns."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_r9_differential_members_keep_file_order() -> None:
    """R9: a CSV whose rows for one key are not in value order reduces in FILE order on both
    sides, which is what makes R1's ordered Kahan well defined."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


# --- A, B, W: the widened projection ----------------------------------------


def test_a2_differential_chain_shape_admits_and_refuses_alike() -> None:
    """A2: over the admitted chain and one witness per structural deviation, the oracle and
    production reach the same verdict and the same refusal code. A disagreement is ESCALATED, never
    absorbed: M13.4's single disagreement resolved in the ORACLE's favour and was a real defect no
    red suite had reached."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_a4_differential_aggregate_channels_project_alike() -> None:
    """A4: `plt.bar(g.index, g.values)`, `plt.bar(g.index, g)`, and the two mixed-channel refusals
    project or refuse identically on both sides."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_b1_differential_barh_shares_bar_argument_order() -> None:
    """B1: `plt.barh(g.index, g.values)` puts the key in x and the reduced column in y on both
    sides, differing from `bar` in the mark alone."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_w1_differential_cosmetic_fields_are_carried_not_discarded() -> None:
    """W1 + W6b: programs differing only in `figsize`, `tick_rotation` or `tight_layout` project to
    UNEQUAL specs on both sides, and `label=` alone sets the series name while `color=` does not.
    Both differential suites normalize `Labels` explicitly, so this widening updates the field maps
    deliberately rather than letting an unmapped name pass."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")


def test_g11_differential_group_counts_agree() -> None:
    """G11 + G78r: the per-group counts agree on both sides, and on both sides they sum to the
    CSV's data-row count for every aggregate — a `groupby` drops no row."""
    pytest.skip("M13.6: needs the aggregation width; red until it lands")
