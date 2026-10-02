# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The safe CSV profile: what the verifier parses with stdlib `csv` + `float`, and what it refuses.

The verifier may not depend on pandas, but the SANDBOX calls plain `pd.read_csv`, whose default
float parser is not correctly rounded. Measured against stdlib `float` over 1,000,000 adversarial
cells, 326,834 disagree, 12,053 of them by 2 to 7,262 ulp, and no significant-digit cap repairs it.
So the profile RESTRICTS rather than reimplementing `xstrtod`: it admits only a region measured at
0 bit mismatches out of 4,000,000 against the target sandbox, and refuses the exact complement.

Two admitted-region clauses are about the RENDERER, not the parser: Pyodide's `plt.bar` keeps
integer heights as `int32` and RAISES outside signed 32 bits, and matplotlib bar erases the sign of
`-0.0`. Both are excluded here so the drawn figure cannot differ from the recomputed table.

Full six-clause profile + its evidence = `.agent/archive/contracts/m13u5.md`.
"""

import csv
import io
import math
import re
from dataclasses import dataclass
from typing import Literal, NoReturn, assert_never

from verifier.pysrc.aggregate import Aggregated, aggregate_series, column_dtype
from verifier.pysrc.budget import WorkBudget
from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.limits import PysrcLimits
from verifier.pysrc.spec import DatasetMark, DatasetPlot
from verifier.pysrc.table import CellValue

__all__ = ["NA_SPELLINGS", "DatasetSeries", "read_columns"]

# Every default NA spelling pandas recognises, measured on the target build. A cell matching one of
# these -- quoted or plain -- refuses rather than becoming a null: the verifier has no null, and
# that absence is what makes G8's row coverage true by construction. Coverage, not point-count
# equality: an aggregate collapses its rows into one point per group and G11 publishes the counts.
NA_SPELLINGS: frozenset[str] = frozenset(
    {
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
    }
)

_UTF8_BOM = b"\xef\xbb\xbf"
_CR = ord("\r")
_LF = ord("\n")
_INT32_MIN = -(2**31)
_INT32_MAX = 2**31 - 1
# Float64 heights `plt.bar` draws bit-exactly, measured on both pinned Pyodide builds and the
# installed bundle (Q12: 0/2,364 changed). A float64 CELL never reaches it -- the 15-digit cap keeps
# every cell below 10**15 -- so it binds a float64 REDUCTION alone.
_FLOAT_HEIGHT_MAX = 2**53
# The marks whose magnitude is drawn as a LENGTH, which is the Pyodide integer path C10 bounds.
_INT_HEIGHT_MARKS = frozenset({"bar", "barh"})
_MAX_SIGNIFICANT_DIGITS = 15
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?")
_BOOLEAN_TEXT = frozenset({"true", "false"})
type _ColumnClass = Literal["numeric", "categorical", "mixed"]
type _RawTable = tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]


def _refuse(code: RefusalCode, cause: BaseException | None = None) -> NoReturn:
    raise PysrcRefusalError(code) from cause


def _check_record_endings(content: bytes) -> None:
    for index, byte in enumerate(content):
        if byte == _CR and (index + 1 == len(content) or content[index + 1] != _LF):
            _refuse("csv_not_parsable")


def _check_cell_sizes(row: list[str], limit: int) -> None:
    if any(len(cell.encode("utf-8")) > limit for cell in row):
        _refuse("csv_too_large")


def _read_csv(content: bytes, limits: PysrcLimits, budget: WorkBudget) -> _RawTable:
    if len(content) > limits.max_csv_bytes:
        _refuse("csv_too_large")
    if content.startswith(_UTF8_BOM) or b"\x00" in content:
        _refuse("csv_not_parsable")
    _check_record_endings(content)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        _refuse("csv_not_parsable", exc)

    reader = csv.reader(
        io.StringIO(text, newline=""),
        delimiter=",",
        quotechar='"',
        doublequote=True,
        escapechar=None,
        skipinitialspace=False,
        strict=True,
    )
    try:
        header_row = next(reader)
        budget.charge(sum(1 + len(cell) // 32 for cell in header_row))
        _check_cell_sizes(header_row, limits.max_csv_cell_bytes)
        if len(header_row) > limits.max_csv_columns:
            _refuse("csv_too_large")
        if (
            not header_row
            or any(not cell for cell in header_row)
            or len(set(header_row)) != len(header_row)
        ):
            _refuse("csv_not_parsable")

        rows: list[tuple[str, ...]] = []
        for row_number, row in enumerate(reader, start=1):
            if row_number > limits.max_csv_rows:
                _refuse("csv_too_large")
            if row_number > limits.max_table_rows:
                _refuse("work_budget_exceeded")
            _check_cell_sizes(row, limits.max_csv_cell_bytes)
            if len(row) != len(header_row):
                _refuse("csv_not_parsable")
            budget.charge(sum(1 + len(cell) // 32 for cell in row))
            rows.append(tuple(row))
    except StopIteration:
        _refuse("csv_not_parsable")
    except csv.Error as exc:
        _refuse("csv_not_parsable", exc)

    if not rows:
        _refuse("csv_not_parsable")
    return tuple(header_row), tuple(rows)


def _column_indices(header: tuple[str, ...], plot: DatasetPlot) -> tuple[int, int]:
    try:
        return header.index(plot.x.name), header.index(plot.y.name)
    except ValueError as exc:
        _refuse("column_not_present", exc)


def _significant_digits(text: str) -> int:
    digits = text.lstrip("-").replace(".", "").lstrip("0")
    return len(digits) if digits else 1


def _profile_float(text: str, value: float, *, integer_column: bool) -> float:
    if (
        _NUMBER.fullmatch(text) is None
        or _significant_digits(text) > _MAX_SIGNIFICANT_DIGITS
        or not math.isfinite(value)
        or (integer_column and not _INT32_MIN <= value <= _INT32_MAX)
        or (value == 0.0 and math.copysign(1.0, value) < 0.0)
    ):
        _refuse("value_not_in_profile")
    # The range and signed-zero clauses bind the renderer, not parsing. Pyodide's integer bar
    # raises outside int32 -- an INTEGER column alone reaches that path; a column pandas infers
    # float64 (any token with a decimal point) draws through the float path, measured bit-exact to
    # 2**53 (Q12) -- while matplotlib bar turns -0.0 into +0.0; either would make the emitted mark
    # differ from this recomputation even though pandas parsed the token correctly.
    return value


def _check_selected_text(text: str) -> None:
    if text in NA_SPELLINGS or text.casefold() in _BOOLEAN_TEXT:
        # pandas infers bool and matplotlib renders it as 1/0; the verifier has no bool cell type.
        _refuse("value_not_in_profile")


def _classify_column(texts: tuple[str, ...]) -> _ColumnClass:
    parsed = 0
    for text in texts:
        try:
            float(text)
        except ValueError:
            continue
        parsed += 1
    if parsed == len(texts):
        return "numeric"
    if parsed == 0:
        return "categorical"
    return "mixed"


def _numeric_value(text: str, integer_column: bool) -> float:  # noqa: FBT001 - the one seam
    try:
        value = float(text)
    except ValueError as exc:
        _refuse("value_not_in_profile", exc)
    return _profile_float(text, value, integer_column=integer_column)


def _numeric_values(texts: tuple[str, ...]) -> tuple[float, ...]:
    """A numeric column's cells; its inferred dtype picks the range clause (user ruling Q12)."""
    integer_column = column_dtype(texts) == "int64"
    return tuple(_numeric_value(text, integer_column) for text in texts)


def _x_values(
    texts: tuple[str, ...], mark: DatasetMark, *, grouped: bool = False
) -> tuple[CellValue, ...]:
    """The x column as cells. `grouped` reads it as a GROUP KEY rather than as an axis.

    That is the whole difference, and it is one clause: a raw x column refuses `mixed` because half
    a numeric axis cannot be drawn, while a key column has no axis until it is reduced and pandas
    groups `['2', 'a', '10', '2']` perfectly well -- measured, as the text keys `['10', '2', 'a']`.
    `scatter` is unmoved either way, since its x IS a coordinate however it was produced.
    """
    column_class = _classify_column(texts)
    match mark:
        case "scatter":
            if column_class == "categorical":
                _refuse("column_not_numeric")
            return _numeric_values(texts)
        case "line" | "bar" | "barh":
            if column_class == "mixed" and not grouped:
                _refuse("column_not_numeric")
            if column_class == "numeric":
                return _numeric_values(texts)
            return texts
        case _ as unreachable:  # pragma: no cover - `DatasetMark` is closed
            assert_never(unreachable)


def _y_values(texts: tuple[str, ...]) -> tuple[float, ...]:
    if _classify_column(texts) == "categorical":
        _refuse("column_not_numeric")
    return _numeric_values(texts)


@dataclass(frozen=True, kw_only=True, slots=True)
class DatasetSeries:
    """The plotted columns, plus the per-group evidence G11 publishes when there is any.

    `group_counts` is `None` for an ungrouped plot and never an empty tuple: "this figure draws no
    groups" and "this figure draws zero groups" are different statements, and the certificate says
    only the first one.
    """

    x: tuple[CellValue, ...]
    y: tuple[float, ...]
    group_counts: tuple[int, ...] | None


def _check_renderer_bound(reduced: Aggregated, mark: DatasetMark) -> None:
    """C10's int32 clause, re-asserted on the REDUCTION rather than on the cells it came from.

    A sum of in-profile cells leaves the range easily. Measured on both target Pyodide builds:
    `bar` and `barh` raise `OverflowError: Python int too large to convert to C long` on the int64
    heights `[4294967294, -4294967296]`, while in-range controls render. Dtype retention is what
    keeps this narrow -- an integer `mean` is float64 and never reaches the renderer's integer
    branch, and `plot`/`scatter` preserve their float64 bits either way. A float64 reduction under
    `bar`/`barh` stays within 2**53, the span measured bit-exact through the float path (Q12):
    float64 cells sum past it, and nothing was measured beyond.
    """
    if mark not in _INT_HEIGHT_MARKS:
        return
    low, high = (
        (_INT32_MIN, _INT32_MAX)
        if reduced.dtype == "int64"
        else (-_FLOAT_HEIGHT_MAX, _FLOAT_HEIGHT_MAX)
    )
    if any(not low <= value <= high for value in reduced.values):
        _refuse("value_not_in_profile")


def read_columns(
    content: bytes,
    plot: DatasetPlot,
    limits: PysrcLimits,
    budget: WorkBudget,
) -> DatasetSeries:
    """The two selected columns of the user's CSV, in file order, or a refusal.

    Takes the whole projected `DatasetPlot` rather than loose names: the column names and the mark
    all come from one projection, and splitting them into separate arguments invites a caller to
    pair a column with the wrong mark.

    Every ceiling is checked BEFORE the work it bounds: a row cap read after materializing the rows
    buys nothing. Each read cell costs `1 + len(cell_text) // 32`; emitted cells stay flat.

    Both selected columns are swept for inadmissible text before classification. stdlib `float`
    success decides numeric, categorical or mixed. The mark decides which class its role admits.

    A projected `group` reduces the pair instead of plotting it: x becomes the sorted group keys
    and y their reduced values. Every cell still passes the profile FIRST, so aggregation reduces
    admitted numbers only.
    """
    header, rows = _read_csv(content, limits, budget)
    x_index, y_index = _column_indices(header, plot)
    selected = tuple((row[x_index], row[y_index]) for row in rows)
    for x_text, y_text in selected:
        _check_selected_text(x_text)
        _check_selected_text(y_text)
    x_texts = tuple(x_text for x_text, _ in selected)
    y_texts = tuple(y_text for _, y_text in selected)
    if plot.group is not None:
        reduced = aggregate_series(
            _x_values(x_texts, plot.mark, grouped=True),
            y_texts,
            _y_values(y_texts),
            plot.group,
            budget=budget,
            max_groups=limits.max_groups,
        )
        _check_renderer_bound(reduced, plot.mark)
        return DatasetSeries(x=reduced.keys, y=reduced.values, group_counts=reduced.counts)
    return DatasetSeries(x=_x_values(x_texts, plot.mark), y=_y_values(y_texts), group_counts=None)
