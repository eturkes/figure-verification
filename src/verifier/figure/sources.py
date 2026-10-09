# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The user's data, read once: each attached CSV under the pandas-equal profile (ruling 4).

`verifier.pysrc.csvread` owns the profile: a cell pandas would parse differently from stdlib
`float` makes its column unusable as numbers here, so no explanation reads it as a value (its text
can still be a key). A file the profile refuses whole carries its refusal code instead of a table.
"""

from dataclasses import dataclass
from typing import cast

from verifier.figure.reasons import FigureReason
from verifier.pysrc.budget import WorkBudget, WorkBudgetExceededError
from verifier.pysrc.csvread import (
    _check_selected_text,
    _classify_column,
    _numeric_values,
    _read_csv,
    _x_values,
)
from verifier.pysrc.errors import PysrcRefusalError
from verifier.pysrc.limits import DEFAULT_LIMITS
from verifier.pysrc.table import CellValue


@dataclass(frozen=True, slots=True)
class Column:
    """One CSV column: its cells as text, as group keys, and as numbers when the profile allows."""

    name: str
    texts: tuple[str, ...]
    keys: tuple[CellValue, ...]
    numbers: tuple[float, ...] | None
    integer: bool


@dataclass(frozen=True, slots=True)
class Table:
    """One attached CSV, as the program reads it with plain `pd.read_csv`."""

    name: str
    header: tuple[str, ...]
    columns: tuple[Column, ...]
    content: bytes

    @property
    def rows(self) -> int:
        return len(self.columns[0].texts)


@dataclass(frozen=True, slots=True)
class Unreadable:
    """An attached file the profile refuses whole; its code explains an unexplained value."""

    name: str
    code: FigureReason  # csv_too_large | csv_not_parsable | work_budget_exceeded


def _column(name: str, texts: tuple[str, ...]) -> Column:
    try:
        for text in texts:
            _check_selected_text(text)
        numbers = _numeric_values(texts) if _classify_column(texts) == "numeric" else None
    except PysrcRefusalError:
        numbers = None
    try:
        keys = _x_values(texts, "bar", grouped=True)
    except PysrcRefusalError:
        keys = texts
    integer = numbers is not None and not any("." in text for text in texts)
    return Column(name, texts, keys, numbers, integer)


def read_table(name: str, content: bytes) -> Table | Unreadable:
    """Read one attachment; a whole-file refusal becomes `Unreadable` with its code."""
    try:
        header, rows = _read_csv(content, DEFAULT_LIMITS, WorkBudget(DEFAULT_LIMITS.max_work))
    except PysrcRefusalError as refusal:
        return Unreadable(name, cast("FigureReason", refusal.code))
    except WorkBudgetExceededError:
        return Unreadable(name, "work_budget_exceeded")
    columns = tuple(
        _column(column, tuple(row[index] for row in rows)) for index, column in enumerate(header)
    )
    return Table(name, header, columns, content)
