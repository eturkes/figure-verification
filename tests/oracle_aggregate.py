# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Independent M13.6 aggregation oracle: dtype, group order, and the reduction engine.

Written from `.agent/contracts/m13u6.md` section R alone, never from `verifier.pysrc.aggregate`.
A differential between two implementations of one contract compares MEANING, so this module keeps
its own vocabulary and `tests/test_pysrc_aggregate_differential.py` owns the single translation.

pandas is absent from the gate venv, so the pandas-facing half of R1/R2/R7 is frozen measurement
under `.agent/measurements/`. Every predicate here is graded against the contract's hand-stated
MEASURED witnesses: R1's four cells separating Kahan from naive from `fsum`, R3's `[2**53, 1, 0]`
1-ulp split, R4's signed-zero bits, R7's code-point key order.

Skeleton: every unit raises `NotImplementedError` until M13.6 lands. This line clears at that close.
"""

from dataclasses import dataclass
from typing import Literal

type OracleReduction = Literal["sum", "mean", "min", "max"]
type OracleDtype = Literal["int64", "float64", "string"]


@dataclass(frozen=True, slots=True)
class OracleGroup:
    """One group: its key text and its member row indices in FILE order (R9)."""

    key: str
    rows: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class OracleAggregate:
    """A reduced series in plotted x-order, with the per-group counts G11 publishes."""

    reduction: OracleReduction
    keys: tuple[str, ...]
    reduced: tuple[float | int, ...]
    counts: tuple[int, ...]


def column_dtype(cells: tuple[str, ...]) -> OracleDtype:
    """R8: the dtype decision `pd.read_csv` makes, BEFORE any ordering decision.

    A column types as STRING whenever any cell is non-numeric, which is what makes
    `['2', 'a', '10', '2']` group in code-point order rather than numerically. An all-integer
    column is `int64`; any numeric column carrying a fractional part is `float64`.
    """
    raise NotImplementedError


def order_keys(keys: tuple[str, ...], dtype: OracleDtype) -> tuple[str, ...]:
    """R7 + R8: distinct keys in pandas' `sort=True` order — the plotted x-order.

    Ascending, by Unicode CODE POINT for a string key and numerically for a numeric one.
    MEASURED locale-independent across `C`, `C.utf8` and `en_US.utf8`; an `en_US` collation
    control orders differently, which is what proves the choice discriminates.
    """
    raise NotImplementedError


def group_rows(key_cells: tuple[str, ...], dtype: OracleDtype) -> tuple[OracleGroup, ...]:
    """R9 + R7: groups in plotted key order, each holding its member rows in FILE order.

    File order inside the group is what makes the ordered Kahan summation of R1 well defined.
    """
    raise NotImplementedError


def reduce_float64(values: tuple[float, ...], reduction: OracleReduction) -> float:
    """R1, R2, R4: the float64 reduction, in the file order its caller supplies.

    `sum` is ordered binary64 Kahan compensation, NOT naive left-to-right, NOT `math.fsum`, NOT
    Neumaier — the three separate on the contract's four-cell witness. `mean` is that Kahan sum
    divided by the count, in that order. `min`/`max` update on STRICT `<`/`>`, so a tie keeps the
    FIRST value's bits (`[-0.0, +0.0]` reduces to `-0.0` both ways).
    """
    raise NotImplementedError


def reduce_int64(values: tuple[int, ...], reduction: OracleReduction) -> float | int:
    """R3, R4, R5: the int64 reduction, retaining dtype except for `mean`.

    `sum`/`min`/`max` stay int64 and exact. `mean` is NOT the exact integer mean: pandas casts each
    value to float64 first, then Kahan-sums, then divides, which splits from exact-then-divide by
    1 ulp on `[2**53, 1, 0]`. Overflow wrapping is UNREACHABLE under the C10 profile and is
    asserted rather than emulated.
    """
    raise NotImplementedError


def aggregate(
    key_cells: tuple[str, ...],
    value_cells: tuple[str, ...],
    reduction: OracleReduction,
) -> OracleAggregate:
    """The whole engine over one already-read column pair: dtype, order, group, reduce, count.

    `key_cells` and `value_cells` are the raw CSV cell texts in file order, of equal length. The
    returned `counts` sum to `len(key_cells)` for every input — G78r's totality, and the reason a
    `groupby` leaves G7 and G8 unconditional.
    """
    raise NotImplementedError
