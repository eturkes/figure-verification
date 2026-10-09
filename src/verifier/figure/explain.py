# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Explaining the drawn values (ruling 4; R2, R4, R6, R7; `.claude/rules/figure.md` § Values).

The vocabulary is closed: per attached CSV, `raw(K, V)` · `index(V)` (row position) ·
`group(K, V, r)` for r in sum mean min max · `count(K)`; a series whose name is a cell value of a
column C reads the rows holding that value alone (R6). A series takes ONE explanation; a point it
leaves unexplained must be a request number with a key the request typed (per value EITHER).
Matching is injective (a row backs one point) and exact in binary64; a strict subset passes and is
published as N of M (R2). Two explanations over different columns that both explain a series tie;
the request breaks the tie when it names the columns of exactly one (R7), else
`column_not_requested`.
"""

import math
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, cast

from verifier.figure.anchoring import Aliases, AmbiguousTermError, anchors
from verifier.figure.keys import Key
from verifier.figure.reasons import FigureReason
from verifier.figure.request import Request
from verifier.figure.series import Point, Series
from verifier.figure.sources import Column, Table, Unreadable
from verifier.pysrc.aggregate import Reduction, aggregate_series
from verifier.pysrc.budget import WorkBudget, WorkBudgetExceededError
from verifier.pysrc.errors import PysrcRefusalError
from verifier.pysrc.table import CellValue

type Family = Literal["raw", "index", "sum", "mean", "min", "max", "count"]
type Canon = tuple[str, object]

_PREFERENCE: Final[tuple[Family, ...]] = ("raw", "index", "sum", "mean", "min", "max", "count")
_REDUCTIONS: Final[tuple[Reduction, ...]] = ("sum", "mean", "min", "max")
_ISO: Final = re.compile(
    r"([0-9]{4})-([0-9]{2})(?:-([0-9]{2})(?:[T ]([0-9]{2}):([0-9]{2})(?::([0-9]{2}))?)?)?"
)
MAX_WORK: Final = 5_000_000
MAX_GROUPS: Final = 1_000


@dataclass(frozen=True, slots=True)
class Explanation:
    """One closed explanation over one CSV: its pairs in pandas' order, and group counts."""

    table: str
    family: Family
    key: str | None
    value: str | None
    where: tuple[str, str] | None
    pairs: tuple[tuple[CellValue | int, float], ...]
    counts: tuple[int, ...] | None
    # A channel explanation (R8): per pair, the main series' value of the same row or group, so a
    # colour or size binds to its own point, never to another point with the same key.
    partners: tuple[float, ...] | None = None

    @property
    def columns(self) -> frozenset[str]:
        return frozenset(name for name in (self.key, self.value) if name is not None)


@dataclass(frozen=True, slots=True)
class Choice:
    """How one series is explained: its explanation (None = request numbers alone), the points it
    backs (N of its M pairs: R2), and the points the request typed instead."""

    series: Series
    explanation: Explanation | None
    matched: int
    from_request: int
    # A reference mark's (file, column) per distinct column that alone holds one of its values,
    # and how many of its values several columns hold (those draw no column).
    reference: tuple[tuple[str, str], ...] = ()
    shared: int = 0

    @property
    def columns(self) -> tuple[tuple[str, frozenset[str]], ...]:
        """(file, the columns its drawn values come from) per file; empty for request numbers."""
        if self.explanation is not None:
            return ((self.explanation.table, self.explanation.columns),)
        files = sorted({file for file, _column in self.reference})
        return tuple(
            (file, frozenset(column for owner, column in self.reference if owner == file))
            for file in files
        )


@dataclass(frozen=True, slots=True)
class Unexplained:
    series: Series
    reason: FigureReason


def _date(text: str) -> str | None:
    match = _ISO.fullmatch(text.strip())
    if match is None:
        return None
    year, month, day, hour, minute, second = (
        int(part or default)
        for part, default in zip(match.groups(), ("0", "0", "1", "0", "0", "0"), strict=True)
    )
    try:
        # Calendar text, not an instant: no time zone applies.
        return datetime(year, month, day, hour, minute, second).isoformat()  # noqa: DTZ001
    except ValueError:
        return None


def _number(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _canon_text(text: str) -> set[Canon]:
    forms: set[Canon] = {("t", text)}
    number = _number(text)
    if number is not None:
        forms.add(("n", number))
    date = _date(text)
    if date is not None:
        forms.add(("d", date))
    return forms


def _canon_cell(value: CellValue | int) -> set[Canon]:
    if isinstance(value, str):
        return _canon_text(value)
    return {("n", float(value))}


def _canon_key(key: Key) -> set[Canon]:
    if key.text is not None:
        return _canon_text(key.text)
    if key.number is not None:
        return {("n", key.number)}
    if key.date is not None:
        date = _date(key.date)
        return set() if date is None else {("d", date)}
    return set()


def _value_ok(point: Point, candidate: float) -> bool:
    if point.base is None:
        return candidate == point.value
    return point.base + candidate == point.value


# --- the closed vocabulary -----------------------------------------------------------------------


def _rows(table: Table, where: tuple[str, str] | None) -> list[int]:
    if where is None:
        return list(range(table.rows))
    column = table.columns[table.header.index(where[0])]
    return [row for row, text in enumerate(column.texts) if text == where[1]]


def _group(
    table: Table, key: Column, value: Column, rows: list[int], budget: WorkBudget
) -> Iterator[Explanation]:
    numbers = cast("tuple[float, ...]", value.numbers)  # callers pass numeric columns alone
    for reduction in _REDUCTIONS:
        try:
            reduced = aggregate_series(
                tuple(key.keys[row] for row in rows),
                tuple(value.texts[row] for row in rows),
                tuple(numbers[row] for row in rows),
                reduction,
                budget=budget,
                max_groups=MAX_GROUPS,
            )
        except PysrcRefusalError:
            return
        yield Explanation(
            table.name,
            reduction,
            key.name,
            value.name,
            None,
            tuple(zip(reduced.keys, reduced.values, strict=True)),
            reduced.counts,
        )


def _count(table: Table, key: Column, rows: list[int]) -> Explanation:
    groups = Counter(key.keys[row] for row in rows)
    ordered = sorted(groups, key=lambda value: (isinstance(value, str), value))
    return Explanation(
        table.name,
        "count",
        key.name,
        None,
        None,
        tuple((group, float(groups[group])) for group in ordered),
        tuple(groups[group] for group in ordered),
    )


def explanations(
    table: Table, where: tuple[str, str] | None, budget: WorkBudget
) -> Iterator[Explanation]:
    """Every closed explanation over `table`, filtered to `where`'s rows (R6), in a fixed order."""
    rows = _rows(table, where)  # never empty: a `where` comes from a cell the column holds
    budget.charge(len(table.columns) * len(rows))
    usable = table.columns  # a filter column may be the key: the series shows its own label
    for value in usable:
        if value.numbers is None:
            continue
        numbers = value.numbers
        yield Explanation(
            table.name,
            "index",
            None,
            value.name,
            where,
            tuple((row, numbers[row]) for row in rows),
            None,
        )
        for key in usable:
            budget.charge(len(rows))
            yield Explanation(
                table.name,
                "raw",
                key.name,
                value.name,
                where,
                tuple((key.keys[row], numbers[row]) for row in rows),
                None,
            )
            if key is value:  # raw(K, K): a colour or size encoding its own point's key
                continue
            for grouped in _group(table, key, value, rows, budget):
                yield Explanation(
                    grouped.table,
                    grouped.family,
                    grouped.key,
                    grouped.value,
                    where,
                    grouped.pairs,
                    grouped.counts,
                )
    for key in usable:
        counted = _count(table, key, rows)
        yield Explanation(
            counted.table, "count", counted.key, None, where, counted.pairs, counted.counts
        )


# --- matching ------------------------------------------------------------------------------------


def _keys_free(series: Series) -> bool:
    """No source must supply the keys: a keyless series (hist inputs, an unnamed pie) or the
    default positions 0..n-1 (`plt.plot(values)`)."""
    points = series.points
    return series.shape == "values" or [point.key.number for point in points] == [
        float(i) for i in range(len(points))
    ]


def _request_key(key: Key, request: Request, *, positional: bool) -> bool:
    if key.text is not None:
        return request.names(key.text)  # R4
    if key.number is not None:
        return positional or key.number in request.numbers
    if key.date is not None:
        return request.names(key.date[:10]) or request.names(key.date[:7])
    return positional or key.slot is not None


def _request_value(point: Point, request: Request) -> bool:
    if point.base is None:
        return point.value in request.numbers
    return any(point.base + number == point.value for number in request.numbers)


def _orders(explanation: Explanation) -> list[list[int]]:
    """The pair orders a positional key may bind to: pandas' own, and a raw table re-sorted by key
    (a pivot sorts its index)."""
    pairs = explanation.pairs
    if explanation.family != "raw":
        return [list(range(len(pairs)))]
    resorted = sorted(range(len(pairs)), key=lambda at: _sort_value(pairs[at][0]))
    return [list(range(len(pairs))), resorted]


def _sort_value(value: CellValue | int) -> tuple[int, float, str]:
    if isinstance(value, str):
        return (1, 0.0, value)
    return (0, float(value), "")


def _fits(point: Point, explanation: Explanation, position: int) -> bool:
    partners = explanation.partners
    return _value_ok(point, explanation.pairs[position][1]) and (
        partners is None or partners[position] == point.partner
    )


def _matched_keyed(
    points: tuple[Point, ...], explanation: Explanation, order: list[int]
) -> list[bool]:
    """Injective: each pair (row or group) backs one point; `order` = the pairs a slot counts."""
    pairs = explanation.pairs
    index: dict[Canon, list[int]] = {}
    for position, (key, _value) in enumerate(pairs):
        for form in _canon_cell(key):
            index.setdefault(form, []).append(position)
    used: set[int] = set()
    matched = [False] * len(points)
    # A slot binds one row; a keyed point any row of its key class (rows sharing key + value are
    # interchangeable), so binding the slots first keeps the greedy assignment maximal.
    slots_first = sorted(range(len(points)), key=lambda i: points[i].key.slot is None)
    for at in slots_first:
        point = points[at]
        found = None
        if point.key.slot is not None:
            slot = point.key.slot
            if (
                slot < len(order)
                and order[slot] not in used
                and _fits(point, explanation, order[slot])
            ):
                found = order[slot]
        else:
            found = next(
                (
                    position
                    for form in sorted(_canon_key(point.key), key=repr)
                    for position in index.get(form, ())
                    if position not in used and _fits(point, explanation, position)
                ),
                None,
            )
        if found is not None:
            used.add(found)
            matched[at] = True
    return matched


def _matched_values(points: tuple[Point, ...], explanation: Explanation) -> list[bool]:
    pool = Counter(value for _key, value in explanation.pairs)
    matched: list[bool] = []
    for point in points:
        ok = pool[point.value] > 0
        if ok:
            pool[point.value] -= 1
        matched.append(ok)
    return matched


def _coverage(series: Series, explanation: Explanation) -> list[bool]:
    """Per point, whether `explanation` backs it; the best of its pair orders."""
    if series.shape == "values":
        return _matched_values(series.points, explanation)
    best: list[bool] = []
    for order in _orders(explanation):
        matched = _matched_keyed(series.points, explanation, order)
        if sum(matched) > sum(best):
            best = matched
    return best or [False] * len(series.points)


@dataclass(frozen=True, slots=True)
class Context:
    """The judge's data: attached tables, the request, and the anchoring words it needs."""

    tables: tuple[Table, ...]
    request: Request
    request_text: str | None
    aliases: Aliases
    strict: bool


def _where(series: Series, table: Table) -> list[tuple[str, str] | None]:
    """R6: a series named by a cell value of column C reads the rows holding it, never all rows."""
    if series.name is None:
        return [None]
    columns = [c.name for c in table.columns if series.name in c.texts]
    return [(column, series.name) for column in columns] or [None]


def _named(context: Context, table: Table) -> frozenset[str]:
    if context.request_text is None:
        return frozenset()
    try:
        named, _negated = anchors(
            context.request_text,
            table.header,
            context.aliases,
            ignore_ties=True,
            short_names=context.strict,
        )
    except AmbiguousTermError:  # pragma: no cover - ignore_ties never raises
        return frozenset()
    return named


def _pick(
    candidates: list[Explanation], context: Context, series: Series
) -> Explanation | Unexplained:
    """One explanation per column set; R7 breaks a tie between column sets by request naming."""
    # The filter column draws nothing (R6): two filters over the same drawn columns are one
    # reading, published by the first filter column in header order.
    groups: dict[tuple[str, frozenset[str]], list[Explanation]] = {}
    for explanation in candidates:
        groups.setdefault((explanation.table, explanation.columns), []).append(explanation)
    if len(groups) > 1:
        tables = {table.name: table for table in context.tables}
        named = [group for group in groups if group[1] <= _named(context, tables[group[0]])]
        if len(named) != 1:
            return Unexplained(series, "column_not_requested")
        groups = {named[0]: groups[named[0]]}
    (members,) = groups.values()
    return min(members, key=lambda e: _PREFERENCE.index(e.family))  # stable: first filter wins


def _candidates(series: Series, context: Context, budget: WorkBudget) -> Iterator[Explanation]:
    for table in context.tables:
        for where in _where(series, table):
            yield from explanations(table, where, budget)


def _explain_series(
    series: Series, candidates: Iterator[Explanation], context: Context
) -> Choice | Unexplained:
    request = context.request
    positional = _keys_free(series)
    by_request = [
        _request_value(point, request) and _request_key(point.key, request, positional=positional)
        for point in series.points
    ]
    full: list[Explanation] = []
    partial: list[tuple[int, Explanation]] = []
    backed = [False] * len(series.points)  # the most points any one explanation backs
    for explanation in candidates:
        matched = _coverage(series, explanation)
        if sum(matched) > sum(backed):
            backed = matched
        if all(matched):
            full.append(explanation)
        elif any(matched) and all(m or r for m, r in zip(matched, by_request, strict=True)):
            partial.append((sum(matched), explanation))
    if full:
        picked = _pick(full, context, series)
    elif partial:
        best = max(count for count, _ in partial)
        picked = _pick([e for count, e in partial if count == best], context, series)
    elif all(by_request):
        return Choice(series, None, 0, len(series.points))
    else:
        reason = _unexplained_reason(series, request, backed, positional=positional)
        return Unexplained(series, reason)
    if isinstance(picked, Unexplained):
        return picked
    matched = _coverage(series, picked)
    return Choice(series, picked, sum(matched), len(matched) - sum(matched))


def _unexplained_reason(
    series: Series, request: Request, backed: list[bool], *, positional: bool
) -> FigureReason:
    """A typed value whose key the request lacks, among points no file explanation backs."""
    for point, done in zip(series.points, backed, strict=True):
        if (
            not done
            and _request_value(point, request)
            and not _request_key(point.key, request, positional=positional)
        ):
            return "label_not_in_request"
    return "value_not_found"


# --- encoded channels (R8) -----------------------------------------------------------------------


def _channel_explanations(
    table: Table, main: Explanation, budget: WorkBudget
) -> Iterator[Explanation]:
    """A channel's candidates: the main explanation's rows or groups, another numeric column's
    cells (or one reduction of it per group), each pair carrying the main value it sits beside."""
    rows = _rows(table, main.where)
    key = None if main.key is None else table.columns[table.header.index(main.key)]
    for column in table.columns:
        numbers = column.numbers
        if numbers is None:
            continue
        budget.charge(len(rows))
        if main.family in ("raw", "index"):
            keys = list(rows) if key is None else [key.keys[row] for row in rows]
            yield Explanation(
                table.name,
                main.family,
                main.key,
                column.name,
                main.where,
                tuple(zip(keys, (numbers[row] for row in rows), strict=True)),
                None,
                tuple(value for _key, value in main.pairs),
            )
            continue
        partner = dict(main.pairs)
        for grouped in _group(table, cast("Column", key), column, rows, budget):
            yield Explanation(
                table.name,
                grouped.family,
                main.key,
                column.name,
                main.where,
                grouped.pairs,
                grouped.counts,
                tuple(partner[group] for group, _value in grouped.pairs),
            )


def _explain_channel(
    series: Series, main: Choice, context: Context, budget: WorkBudget
) -> Choice | Unexplained:
    """A colour or size channel: from the rows or groups of its scatter's own explanation, else
    request numbers alone (a scatter typed in the request types its channels too)."""
    explanation = main.explanation
    if explanation is None:
        return _explain_series(series, iter(()), context)
    table = next(table for table in context.tables if table.name == explanation.table)
    return _explain_series(series, _channel_explanations(table, explanation, budget), context)


# --- reference marks -----------------------------------------------------------------------------


def _column_values(table: Table, column: Column, budget: WorkBudget) -> set[float]:
    """A numeric column's cells and its whole-column reductions: what a reference line may be."""
    numbers = column.numbers
    if numbers is None:
        return set()
    found = set(numbers)
    rows = list(range(table.rows))
    whole = Column("", ("",) * table.rows, ("",) * table.rows, None, integer=False)
    for explanation in _group(table, whole, column, rows, budget):
        found.update(value for _key, value in explanation.pairs)
    return found


def _explain_reference(
    series: Series, context: Context, budget: WorkBudget
) -> Choice | Unexplained:
    """A reference value = zero, a request number, a cell, or one whole-column reduction; a value
    exactly one column holds draws that column, one several columns hold draws none."""
    holders: set[tuple[str, str]] = set()
    typed = shared = 0
    for point in series.points:
        if point.value == 0.0 or point.value in context.request.numbers:
            typed += 1
            continue
        found = {
            (table.name, column.name)
            for table in context.tables
            for column in table.columns
            if point.value in _column_values(table, column, budget)
        }
        if not found:
            return Unexplained(series, "value_not_found")
        if len(found) == 1:
            holders |= found
        else:
            shared += 1
    return Choice(series, None, 0, typed, tuple(sorted(holders)), shared)


# --- every series ------------------------------------------------------------------------------


def duplicate_key(series: Series) -> bool:
    """G8: two points of one keyed series show the same category (they overplot). An integrity
    rule: it binds every figure, a figure with no data source included."""
    if series.shape != "keyed" or series.mark.family == "scatter":
        return False
    texts = [point.key.text for point in series.points if point.key.text is not None]
    return len(texts) != len(set(texts))


def explain(
    every: tuple[Series, ...], context: Context, unreadable: tuple[Unreadable, ...]
) -> tuple[Choice, ...] | Unexplained:
    """One choice per series, or the first series no source explains (with its reason)."""
    budget = WorkBudget(MAX_WORK)
    choices: list[Choice] = []
    try:
        for series in every:
            if series.shape == "reference":
                outcome = _explain_reference(series, context, budget)
            elif series.channel != "value":
                main = next(c for c in reversed(choices) if c.series.mark is series.mark)
                outcome = _explain_channel(series, main, context, budget)
            else:
                outcome = _explain_series(series, _candidates(series, context, budget), context)
            if isinstance(outcome, Unexplained):
                if outcome.reason == "value_not_found" and unreadable:
                    return Unexplained(series, unreadable[0].code)
                return outcome
            choices.append(outcome)
    except WorkBudgetExceededError:
        return Unexplained(every[0], "work_budget_exceeded")
    return tuple(choices)
