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
from typing import Literal, NoReturn, assert_never

from verifier.pysrc.budget import WorkBudget
from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.limits import PysrcLimits
from verifier.pysrc.spec import DatasetMark, DatasetPlot
from verifier.pysrc.table import CellValue

__all__ = ["NA_SPELLINGS", "read_columns"]

# Every default NA spelling pandas recognises, measured on the target build. A cell matching one of
# these -- quoted or plain -- refuses rather than becoming a null: the verifier has no null, and
# that absence is what makes "plotted point count = non-null row count" true by construction.
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


def _profile_float(text: str, value: float) -> float:
    if (
        _NUMBER.fullmatch(text) is None
        or _significant_digits(text) > _MAX_SIGNIFICANT_DIGITS
        or not math.isfinite(value)
        or not _INT32_MIN <= value <= _INT32_MAX
        or (value == 0.0 and math.copysign(1.0, value) < 0.0)
    ):
        _refuse("value_not_in_profile")
    # The range and signed-zero clauses bind the renderer, not parsing. Pyodide's integer bar
    # raises outside int32, while matplotlib bar turns -0.0 into +0.0; either would make the
    # emitted mark differ from this recomputation even though pandas parsed the token correctly.
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


def _numeric_value(text: str) -> float:
    try:
        value = float(text)
    except ValueError as exc:
        _refuse("value_not_in_profile", exc)
    return _profile_float(text, value)


def _x_values(texts: tuple[str, ...], mark: DatasetMark) -> tuple[CellValue, ...]:
    column_class = _classify_column(texts)
    match mark:
        case "scatter":
            if column_class == "categorical":
                _refuse("column_not_numeric")
            return tuple(_numeric_value(text) for text in texts)
        case "line" | "bar":
            if column_class == "mixed":
                _refuse("column_not_numeric")
            if column_class == "numeric":
                return tuple(_numeric_value(text) for text in texts)
            return texts
        case _ as unreachable:  # pragma: no cover - `DatasetMark` is closed
            assert_never(unreachable)


def _y_values(texts: tuple[str, ...]) -> tuple[float, ...]:
    if _classify_column(texts) == "categorical":
        _refuse("column_not_numeric")
    return tuple(_numeric_value(text) for text in texts)


def read_columns(
    content: bytes,
    plot: DatasetPlot,
    limits: PysrcLimits,
    budget: WorkBudget,
) -> tuple[tuple[CellValue, ...], tuple[float, ...]]:
    """The two selected columns of the user's CSV, in file order, or a refusal.

    Takes the whole projected `DatasetPlot` rather than loose names: the column names and the mark
    all come from one projection, and splitting them into separate arguments invites a caller to
    pair a column with the wrong mark.

    Every ceiling is checked BEFORE the work it bounds: a row cap read after materializing the rows
    buys nothing. Each read cell costs `1 + len(cell_text) // 32`; emitted cells stay flat.

    Both selected columns are swept for inadmissible text before classification. stdlib `float`
    success decides numeric, categorical or mixed. The mark decides which class its role admits.
    """
    header, rows = _read_csv(content, limits, budget)
    x_index, y_index = _column_indices(header, plot)
    selected = tuple((row[x_index], row[y_index]) for row in rows)
    for x_text, y_text in selected:
        _check_selected_text(x_text)
        _check_selected_text(y_text)
    x_texts = tuple(x_text for x_text, _ in selected)
    y_texts = tuple(y_text for _, y_text in selected)
    return _x_values(x_texts, plot.mark), _y_values(y_texts)
