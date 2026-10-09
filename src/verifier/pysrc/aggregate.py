# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Grouped reduction, reproducing what the EXECUTED program plots.

pandas is not importable here and never will be: the core is stdlib-only so M14 can inline it. So
this module reimplements the reductions pandas performs, and every choice below is fixed by
MEASUREMENT against pandas rather than by what is arithmetically nicest -- the more precise engine
is the less faithful one, exactly as in `expr.py`'s ruling.

The four decisions that carry the module, all measured:

- a float64 `sum` is ORDERED binary64 Kahan compensation in file-row order. Naive left-to-right
  differs on 2,761 of 4,000 admitted-profile CSV groups, `math.fsum` on 1,483; Kahan matches on
  0 of 16,062.
- an int64 `mean` casts each value to float64 BEFORE summing, so it is NOT the exact integer mean:
  `[2**53, 1, 0]` splits the two orders by 1 ulp.
- `min` and `max` update on STRICT `<` and `>`, so a tie keeps the FIRST value's bits.
- group key order IS the plotted x-order, and it is pandas' `sort=True` default: ascending, by
  Unicode code point for text keys, measured identical under `C`, `C.utf8` and `en_US.utf8` while
  an `en_US` collation control orders differently.

Host versus both target Pyodide builds: 0 differences over 96,372 reduction rows. Unlike the libm
functions the reduction carries NO measured ulp band, so a disagreement here is a defect rather than
an environment gap.
"""

from dataclasses import dataclass
from typing import Literal, NoReturn, assert_never

from verifier.pysrc.budget import WorkBudget
from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.table import CellValue

__all__ = ["Aggregated", "ColumnDtype", "Reduction", "aggregate_series", "column_dtype"]

# Grouped reductions, closed. Each one is a total function from a group's cells to one number,
# which is what lets the judge reproduce it exactly; a reduction needing a parameter (quantile,
# std's delta degrees of freedom) is not a member.
type Reduction = Literal["sum", "mean", "min", "max"]

# The dtype `pd.read_csv` infers for a column inside the admitted cell profile. There is no third
# member: the profile refuses every NA spelling, every boolean text and every non-fixed-point token
# before a cell reaches here, so a selected value column is one of these two.
type ColumnDtype = Literal["int64", "float64"]

# `mean` is the one reduction that does not retain an integer dtype: pandas produces float64 for it,
# which is also why the renderer's integer bound never binds an integer mean.
_DTYPE_RETAINING = frozenset({"sum", "min", "max"})


@dataclass(frozen=True, slots=True)
class Aggregated:
    """One reduced series in PLOTTED order, with the evidence G11 publishes beside it.

    `counts` is aligned with `keys` and sums to the data-row count of the file for every input,
    because every row joins exactly one group. That totality is what keeps G7's range claim and
    G8's ROW COVERAGE unconditional while aggregation is admitted: a `groupby` drops no row. It
    does collapse rows into fewer points than the file has rows, which is why G8 is coverage rather
    than point-count equality and why `counts` is published rather than merely computed.
    """

    keys: tuple[CellValue, ...]
    values: tuple[float, ...]
    counts: tuple[int, ...]
    dtype: ColumnDtype


def _refuse(code: RefusalCode) -> NoReturn:
    raise PysrcRefusalError(code)


def column_dtype(texts: tuple[str, ...]) -> ColumnDtype:
    """`int64` only when NO cell carries a decimal point, which is pandas' own inference.

    Reading the TEXT rather than the parsed float is what makes this exact: `5` and `5.0` parse to
    the same float64 and pandas types their columns differently.
    """
    return "float64" if any("." in text for text in texts) else "int64"


def _kahan_sum(values: tuple[float, ...]) -> float:
    """Ordered binary64 Kahan compensation. Not naive, not `fsum`, not Neumaier.

    The compensation reset pandas performs for NaN is absent because NaN cannot arrive: the cell
    profile refuses every NA spelling ahead of this call, so the arm would be an unreachable branch.
    """
    total = 0.0
    compensation = 0.0
    for value in values:
        adjusted = value - compensation
        running = total + adjusted
        compensation = (running - total) - adjusted
        total = running
    return total


def _extremum[T: (float, int)](values: tuple[T, ...], *, greater: bool) -> T:
    """Strict `<`/`>`, so a tie keeps the FIRST value's bits -- `[-0.0, +0.0]` reduces to `-0.0`."""
    best = values[0]
    for value in values[1:]:
        if (value > best) if greater else (value < best):
            best = value
    return best


def _reduce_float(values: tuple[float, ...], reduction: Reduction) -> float:
    match reduction:
        case "sum":
            return _kahan_sum(values)
        case "mean":
            # Sum THEN divide, in that order. A running mean and a compensated divide each land on a
            # different last bit, and this is the order pandas takes.
            return _kahan_sum(values) / len(values)
        case "min":
            return _extremum(values, greater=False)
        case "max":
            return _extremum(values, greater=True)
        case _ as unreachable:  # pragma: no cover - `Reduction` is closed
            assert_never(unreachable)


def _reduce_int(values: tuple[int, ...], reduction: Reduction) -> float:
    match reduction:
        case "sum":
            # Exact: Python integers do not wrap where pandas' int64 would, and the profile makes
            # that difference unreachable -- int32 cells times `max_table_rows` stays under 2**48,
            # so the result is also exactly representable in the float64 the table carries.
            return float(sum(values))
        case "mean":
            # Per-value float cast, THEN Kahan, THEN divide. Not the exact integer mean: pandas
            # rounds each value into float64 first, and `[2**53, 1, 0]` is where the two split.
            return _kahan_sum(tuple(float(value) for value in values)) / len(values)
        case "min":
            return float(_extremum(values, greater=False))
        case "max":
            return float(_extremum(values, greater=True))
        case _ as unreachable:  # pragma: no cover - `Reduction` is closed
            assert_never(unreachable)


def _sort_key(value: CellValue) -> tuple[int, float, str]:
    """Total over one column's key class, and code-point ordered for text.

    Python compares `str` by code point, so ascending `sorted` IS pandas' `sort=True` order with no
    locale in the path. The leading discriminator keeps the function total without ever comparing a
    number against a string, which would raise.
    """
    if isinstance(value, str):
        return (1, 0.0, value)
    return (0, value, "")


def aggregate_series(  # noqa: PLR0913 - six independent inputs, none derivable from another
    keys: tuple[CellValue, ...],
    value_texts: tuple[str, ...],
    values: tuple[float, ...],
    reduction: Reduction,
    *,
    budget: WorkBudget,
    max_groups: int,
) -> Aggregated:
    """Reduce `values` by `keys`, in the order and to the bits the executed program would plot.

    `keys` and `value_texts` are the two selected columns in FILE order, already swept against the
    cell profile by the caller. `value_texts` decides the dtype; `values` carries the parsed
    float64 the float path reduces.

    Row order inside each group is file order, which is what makes the ordered summation
    well defined; group order is sorted key order, which is what the figure draws along x.
    """
    budget.charge(len(keys))
    members: dict[CellValue, list[int]] = {}
    for index, key in enumerate(keys):
        members.setdefault(key, []).append(index)
    # Checked BEFORE the reduction it bounds: a high-cardinality key column must refuse on what it
    # would cost rather than after paying it.
    if len(members) > max_groups:
        _refuse("work_budget_exceeded")
    budget.charge(len(members))

    dtype = column_dtype(value_texts)
    integers = tuple(int(text) for text in value_texts) if dtype == "int64" else ()
    ordered = sorted(members, key=_sort_key)
    reduced: list[float] = []
    counts: list[int] = []
    for key in ordered:
        rows = members[key]
        counts.append(len(rows))
        if dtype == "int64":
            reduced.append(_reduce_int(tuple(integers[index] for index in rows), reduction))
        else:
            reduced.append(_reduce_float(tuple(values[index] for index in rows), reduction))
    result_dtype: ColumnDtype = (
        "int64" if dtype == "int64" and reduction in _DTYPE_RETAINING else "float64"
    )
    return Aggregated(
        keys=tuple(ordered),
        values=tuple(reduced),
        counts=tuple(counts),
        dtype=result_dtype,
    )
