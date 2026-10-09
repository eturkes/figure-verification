# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The reduction engine the judge explains grouped values with (`verifier.pysrc.aggregate`).

Contract: `.agent/archive/contracts/m13u6.md` predicates R1-R10, B4, G11 + G78r + G9r, re-rooted
from the retired static path onto `aggregate_series` itself (M19.7b). Each docstring carries its
predicate's acceptance check.

The engine reproduces what the EXECUTED program plots, not what is arithmetically nicest. pandas
reduces a float64 group with ordered binary64 Kahan compensation in file-row order, measured: naive
left-to-right differs on 2,761/4,000 admitted-profile CSV groups (worst 8,192 ulp), `math.fsum` on
1,483 (worst 5,252 ulp), Kahan on 0/16,062.
"""

import math
import struct

import pytest

from verifier.figure.sources import Table, read_table
from verifier.pysrc import csvread as csvread_module
from verifier.pysrc.aggregate import Aggregated, Reduction, aggregate_series
from verifier.pysrc.budget import WorkBudget, WorkBudgetExceededError
from verifier.pysrc.csvread import key_values
from verifier.pysrc.errors import PysrcRefusalError
from verifier.pysrc.limits import DEFAULT_LIMITS


def _aggregate(
    rows: tuple[tuple[str, str], ...],
    reduction: Reduction,
    *,
    budget: WorkBudget | None = None,
    max_groups: int = DEFAULT_LIMITS.max_groups,
) -> Aggregated:
    """`(key text, value text)` rows in file order, reduced as the judge reduces a key + value."""
    keys = key_values(tuple(key for key, _ in rows))
    texts = tuple(value for _, value in rows)
    return aggregate_series(
        keys,
        texts,
        tuple(float(text) for text in texts),
        reduction,
        budget=budget or WorkBudget(DEFAULT_LIMITS.max_work),
        max_groups=max_groups,
    )


def _one(*values: str) -> tuple[tuple[str, str], ...]:
    return tuple(("one", value) for value in values)


def test_a1_the_reduction_vocabulary_is_closed() -> None:
    """A1: `get_args(Reduction.__value__)` = the hand-stated `("sum", "mean", "min", "max")`."""
    from typing import get_args  # noqa: PLC0415

    assert get_args(Reduction.__value__) == ("sum", "mean", "min", "max")


def test_r1_float_sum_is_kahan_not_naive_or_fsum() -> None:
    """R1: the witness separating ordered Kahan from naive left-to-right and from `math.fsum`;
    the naive-sum mutant and the `fsum` mutant must BOTH go red."""
    values = (1_000_000_000.0, 0.000001, 0.000001, -1_000_000_000.0)
    observed = _aggregate(_one("1000000000.0", "0.000001", "0.000001", "-1000000000.0"), "sum")
    naive = 0.0
    for value in values:
        naive += value
    assert observed.values[0].hex() == "0x1.1000000000000p-19"
    assert naive.hex() == "0x1.0000000000000p-19"
    assert math.fsum(values).hex() == "0x1.0c6f7a0b5ed8dp-19"


def test_r2_float_mean_is_kahan_sum_over_count() -> None:
    """R2: sum-then-divide, where a running mean differs in the last bit."""
    mean = _aggregate(_one("1000000000.0", "0.000001", "0.000001", "-1000000000.0"), "mean")
    assert mean.values[0].hex() == "0x1.1000000000000p-21"
    running = 0.0
    for count, value in enumerate((1_000_000_000.0, 0.000001, 0.000001, -1_000_000_000.0), 1):
        running += (value - running) / count
    assert running.hex() == "0x1.0000000000000p-21"


def test_r3_int_mean_casts_before_summing() -> None:
    """R3: MEASURED witness `[2**53, 1, 0]` -- pandas `mean` is `0x1.5555555555555p+51`, exact-then-
    divide is `0x1.5555555555556p+51`; an int64 `sum` stays exact."""
    mean = _aggregate(_one("9007199254740992", "1", "0"), "mean")
    assert mean.values[0].hex() == "0x1.5555555555555p+51"
    assert float((2**53 + 1) / 3).hex() == "0x1.5555555555556p+51"
    total = _aggregate(_one("2147483647", "1"), "sum")
    assert total.values[0].hex() == "0x1.0000000000000p+31"


def test_r4_extrema_keep_the_first_tied_value_bits() -> None:
    """R4: `[-0.0, +0.0]` gives `-0.0` for both `min` and `max`; reversed gives `+0.0`, compared as
    bit patterns since `-0.0 == +0.0`. The profile keeps `-0.0` out of a column; pinned anyway."""
    for values, bits in (
        (("-0.0", "0.0"), b"\x80" + bytes(7)),
        (("0.0", "-0.0"), bytes(8)),
    ):
        for reduction in ("min", "max"):
            result = _aggregate(_one(*values), reduction)
            assert struct.pack(">d", result.values[0]) == bits, (values, reduction)


def test_r5_int_sum_overflow_is_unreachable_under_the_profile() -> None:
    """R5: the worst-case magnitude from the int32 cell bound and `max_table_rows` stays below 2**63
    (pandas WRAPS on overflow: `[2**63-1, 1]` -> `-2**63`). Raising `max_table_rows` past it
    reddens."""
    largest_positive_sum = (2**31 - 1) * DEFAULT_LIMITS.max_table_rows
    largest_negative_magnitude = 2**31 * DEFAULT_LIMITS.max_table_rows
    assert max(largest_positive_sum, largest_negative_magnitude) < 2**63


# Hand-stated, never read from `csvread.NA_SPELLINGS`: the equality assertion below is what makes a
# deletion and an addition both go red.
_NA_SPELLINGS = (
    "",
    "#N/A",
    "#N/A N/A",
    "#NA",
    "-1.#IND",
    "-1.#QNAN",
    "-NaN",
    "-nan",
    "1.#IND",
    "1.#QNAN",
    "<NA>",
    "N/A",
    "NA",
    "NULL",
    "NaN",
    "None",
    "n/a",
    "nan",
    "null",
)


def test_r6_nan_never_reaches_a_reduction() -> None:
    """R6: every NA spelling, plain and quoted, leaves its column with no numbers, so the judge has
    no NaN to reduce -- pandas' NaN-skipping arm is unreachable and unimplemented."""
    assert frozenset(_NA_SPELLINGS) == csvread_module.NA_SPELLINGS
    for spelling in _NA_SPELLINGS:
        for cell in (spelling, f'"{spelling}"'):
            table = read_table("sales.csv", f"region,revenue\none,{cell}\n".encode())
            assert isinstance(table, Table), cell
            assert table.columns[1].numbers is None, cell


def test_r7_group_keys_sort_by_code_point() -> None:
    """R7: key order = pandas' `sort=True` by code point -- mixed case, digits vs letters, spaces,
    non-ASCII, a shared prefix. MEASURED identical under C, C.utf8 and en_US.utf8."""
    keys = ("é", "a b", "2", "prefixい", "A", "ä", "a  a", "10", "z", "prefixあ", "a")
    result = _aggregate(tuple((key, "1") for key in keys), "sum")
    assert result.keys == (
        "10",
        "2",
        "A",
        "a",
        "a  a",
        "a b",
        "prefixあ",
        "prefixい",
        "z",
        "ä",
        "é",
    )


def test_r8_key_dtype_decides_before_key_order() -> None:
    """R8: an all-numeric key column orders numerically; one text cell turns every key to text:
    `['2', 'a', '10', '2']` groups to `['10', '2', 'a']`."""
    assert _aggregate((("2", "1"), ("10", "1"), ("2", "1")), "sum").keys == (2.0, 10.0)
    textual = _aggregate((("2", "1"), ("a", "1"), ("10", "1"), ("2", "1")), "sum")
    assert textual.keys == ("10", "2", "a")


def test_r9_rows_keep_file_order_inside_a_group() -> None:
    """R9: a group's rows sum in file order (sorting within the group goes red), which is what
    makes R1's ordered Kahan well defined."""
    result = _aggregate(_one("1000000000.0", "-1000000000.0", "0.000001", "0.000002"), "sum")
    assert result.values[0].hex() == "0x1.92a737110e454p-19"
    total = compensation = 0.0
    for value in (-1_000_000_000.0, 0.000001, 0.000002, 1_000_000_000.0):
        corrected = value - compensation
        next_total = total + corrected
        compensation = (next_total - total) - corrected
        total = next_total
    assert total.hex() == "0x1.9000000000000p-19"


def test_r10_group_count_is_bounded_and_charged() -> None:
    """R10: one charge per row + one per group, exact at the boundary; more groups than
    `max_groups` refuse `work_budget_exceeded` before reducing."""
    rows = (("a", "1"), ("b", "2"), ("a", "3"))
    assert _aggregate(rows, "sum", budget=WorkBudget(5), max_groups=2).keys == ("a", "b")
    with pytest.raises(WorkBudgetExceededError):
        _aggregate(rows, "sum", budget=WorkBudget(4), max_groups=2)
    with pytest.raises(PysrcRefusalError) as refused:
        _aggregate((("a", "1"), ("b", "2"), ("c", "3")), "sum", max_groups=2)
    assert refused.value.code == "work_budget_exceeded"


def test_b4_reductions_retain_dtype() -> None:
    """B4: an int64 column keeps int64 under sum, min + max; `mean` is float64 (R3); a float64
    column stays float64 under every reduction."""
    for value, reductions in (
        ("2147483648", {"sum": "int64", "mean": "float64", "min": "int64", "max": "int64"}),
        ("2147483648.0", dict.fromkeys(("sum", "mean", "min", "max"), "float64")),
    ):
        for reduction, dtype in reductions.items():
            result = _aggregate((("1", value),), reduction)  # type: ignore[arg-type]
            assert result.dtype == dtype, (value, reduction)


def test_g11_per_group_counts_align_with_the_keys() -> None:
    """G11 + G78r: member counts align with the sorted keys and sum to the data-row count for every
    reduction -- a `groupby` drops no row (6 rows draw 3 points)."""
    rows = (("a", "1"), ("c", "2"), ("a", "3"), ("b", "4"), ("c", "5"), ("c", "6"))
    for reduction in ("sum", "mean", "min", "max"):
        result = _aggregate(rows, reduction)
        assert result.keys == ("a", "b", "c"), reduction
        assert result.counts == (2, 1, 3), reduction
        assert sum(result.counts) == len(rows), reduction
