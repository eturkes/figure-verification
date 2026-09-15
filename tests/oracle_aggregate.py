# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Independent M13.6 aggregation oracle: dtype, group order, and the reduction engine.

Written from `.agent/archive/contracts/m13u6.md` section R alone, never from
`verifier.pysrc.aggregate`.
A differential between two implementations of one contract compares MEANING, so this module keeps
its own vocabulary and `tests/test_pysrc_aggregate_differential.py` owns the single translation.

pandas is absent from the gate venv, so the pandas-facing half of R1/R2/R7 is frozen measurement
under `.agent/measurements/`. Every predicate here is graded against the contract's hand-stated
MEASURED witnesses: R1's four cells separating Kahan from naive from `fsum`, R3's `[2**53, 1, 0]`
1-ulp split, R4's signed-zero bits, R7's code-point key order.

"""

from dataclasses import dataclass
from typing import Literal, assert_never

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
    if not cells:
        message = "a column must contain at least one cell"
        raise ValueError(message)
    dtype: OracleDtype = "int64"
    for cell in cells:
        try:
            int(cell)
        except ValueError:
            try:
                float(cell)
            except ValueError:
                return "string"
            dtype = "float64"
    return dtype


def order_keys(keys: tuple[str, ...], dtype: OracleDtype) -> tuple[str, ...]:
    """R7 + R8: distinct keys in pandas' `sort=True` order — the plotted x-order.

    Ascending, by Unicode CODE POINT for a string key and numerically for a numeric one.
    MEASURED locale-independent across `C`, `C.utf8` and `en_US.utf8`; an `en_US` collation
    control orders differently, which is what proves the choice discriminates.
    """
    if dtype == "string":
        return tuple(sorted(set(keys)))
    if dtype == "int64":
        integers: dict[int, str] = {}
        for key in keys:
            integers.setdefault(int(key), key)
        return tuple(integers[value] for value in sorted(integers))
    if dtype == "float64":
        floats: dict[float, str] = {}
        for key in keys:
            floats.setdefault(float(key), key)
        return tuple(floats[value] for value in sorted(floats))
    assert_never(dtype)


def group_rows(key_cells: tuple[str, ...], dtype: OracleDtype) -> tuple[OracleGroup, ...]:
    """R9 + R7: groups in plotted key order, each holding its member rows in FILE order.

    File order inside the group is what makes the ordered Kahan summation of R1 well defined.
    """
    ordered = order_keys(key_cells, dtype)
    if dtype == "string":
        return tuple(
            OracleGroup(key, tuple(index for index, cell in enumerate(key_cells) if cell == key))
            for key in ordered
        )
    if dtype == "int64":
        return tuple(
            OracleGroup(
                key,
                tuple(index for index, cell in enumerate(key_cells) if int(cell) == int(key)),
            )
            for key in ordered
        )
    if dtype == "float64":
        return tuple(
            OracleGroup(
                key,
                tuple(index for index, cell in enumerate(key_cells) if float(cell) == float(key)),
            )
            for key in ordered
        )
    assert_never(dtype)


def _kahan_sum(values: tuple[float, ...]) -> float:
    total = compensation = 0.0
    for value in values:
        corrected = value - compensation
        updated = total + corrected
        compensation = (updated - total) - corrected
        total = updated
    return total


def reduce_float64(values: tuple[float, ...], reduction: OracleReduction) -> float:
    """R1, R2, R4: the float64 reduction, in the file order its caller supplies.

    `sum` is ordered binary64 Kahan compensation, NOT naive left-to-right, NOT `math.fsum`, NOT
    Neumaier — the three separate on the contract's four-cell witness. `mean` is that Kahan sum
    divided by the count, in that order. `min`/`max` update on STRICT `<`/`>`, so a tie keeps the
    FIRST value's bits (`[-0.0, +0.0]` reduces to `-0.0` both ways).
    """
    if not values:
        message = "a reduction must contain at least one value"
        raise ValueError(message)
    if reduction == "sum":
        return _kahan_sum(values)
    if reduction == "mean":
        return _kahan_sum(values) / len(values)
    result = values[0]
    if reduction == "min":
        for value in values[1:]:
            if value < result:  # noqa: PLR1730 — strict update preserves first tied bits
                result = value
        return result
    if reduction == "max":
        for value in values[1:]:
            if value > result:  # noqa: PLR1730 — strict update preserves first tied bits
                result = value
        return result
    assert_never(reduction)


def reduce_int64(values: tuple[int, ...], reduction: OracleReduction) -> float | int:
    """R3, R4, R5: the int64 reduction, retaining dtype except for `mean`.

    `sum`/`min`/`max` stay int64 and exact. `mean` is NOT the exact integer mean: pandas casts each
    value to float64 first, then Kahan-sums, then divides, which splits from exact-then-divide by
    1 ulp on `[2**53, 1, 0]`. Overflow wrapping is UNREACHABLE under the C10 profile and is
    asserted rather than emulated.
    """
    if not values:
        message = "a reduction must contain at least one value"
        raise ValueError(message)
    if reduction == "mean":
        return reduce_float64(tuple(float(value) for value in values), "mean")
    if reduction == "sum":
        result = sum(values)
        assert -(2**63) <= result < 2**63, "int64 sum overflow is unreachable under C10"
        return result
    result = values[0]
    if reduction == "min":
        for value in values[1:]:
            if value < result:  # noqa: PLR1730 — strict update mirrors the float path
                result = value
        return result
    if reduction == "max":
        for value in values[1:]:
            if value > result:  # noqa: PLR1730 — strict update mirrors the float path
                result = value
        return result
    assert_never(reduction)


def aggregate(
    key_cells: tuple[str, ...],
    value_cells: tuple[str, ...],
    reduction: OracleReduction,
) -> OracleAggregate:
    """The whole engine over one already-read column pair: dtype, order, group, reduce, count.

    `key_cells` and `value_cells` are the raw CSV cell texts in file order, of equal length. The
    returned `counts` sum to `len(key_cells)` for every input — G78r's totality, and the reason a
    `groupby` leaves G7's range claim and G8's row COVERAGE unconditional. Coverage, not
    point-count equality: fewer points than rows is the normal aggregate shape.
    """
    if not key_cells or len(key_cells) != len(value_cells):
        message = "aggregate columns must be non-empty and equal length"
        raise ValueError(message)
    key_dtype = column_dtype(key_cells)
    value_dtype = column_dtype(value_cells)
    if value_dtype == "string":
        message = "an aggregate value column must be numeric"
        raise ValueError(message)
    groups = group_rows(key_cells, key_dtype)
    reduced: list[float | int] = []
    for group in groups:
        if value_dtype == "int64":
            values = tuple(int(value_cells[index]) for index in group.rows)
            reduced.append(reduce_int64(values, reduction))
        elif value_dtype == "float64":
            float_values = tuple(float(value_cells[index]) for index in group.rows)
            reduced.append(reduce_float64(float_values, reduction))
        else:
            assert_never(value_dtype)
    return OracleAggregate(
        reduction=reduction,
        keys=tuple(group.key for group in groups),
        reduced=tuple(reduced),
        counts=tuple(len(group.rows) for group in groups),
    )
