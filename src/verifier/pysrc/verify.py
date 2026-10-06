# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The public entry: submitted source in, verdict out.

Seven stages, in order, each refusing before the next runs: prescan -> admit -> project -> bind
target -> recompute -> integrity -> certify. Ordering is a claim, not an implementation detail -- a
later stage that runs after an earlier refusal would be doing work on bytes already rejected, and
a stage's refusal code would stop identifying which check caught what.

A refusal is RETURNED, never raised. A `PysrcCallerError` still propagates: an operator who
configured the verifier wrongly has no verdict about the source, and collapsing the two would let
a misconfiguration read as a refused program.

The entry is PURE. No filesystem, no network, no clock, no RNG, no environment. The user's CSV
arrives as bytes inside `declared_target`, so the core never opens a path -- which is also what
lets M14 inline this package into a sandbox that has neither.
"""

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import NoReturn, assert_never

from verifier.pysrc.admit import parse_admitted
from verifier.pysrc.budget import WorkBudget, WorkBudgetExceededError
from verifier.pysrc.certificate import CoreCertificate, certify
from verifier.pysrc.csvread import header_names, read_columns
from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.limits import DEFAULT_LIMITS, PysrcLimits, validate_limits
from verifier.pysrc.numeric import evaluate_expr, materialize_grid
from verifier.pysrc.prescan import prescan
from verifier.pysrc.project import project, same_bound
from verifier.pysrc.spec import (
    Bin,
    Const,
    CorePlotSpec,
    DatasetPlot,
    DatasetTarget,
    DeclaredTarget,
    Expr,
    Fn,
    FormulaPlot,
    FormulaTarget,
    Grid,
    Interval,
    Neg,
    Num,
    Var,
)
from verifier.pysrc.table import CellValue, PlottedTable

__all__ = ["Refused", "Verdict", "Verified", "verify_python_source"]


@dataclass(frozen=True, slots=True)
class Verified:
    """Carries the projection, the recomputation and the certificate -- and nothing else.

    Deliberately holds NO byte derived from the source beyond the certificate's `source_sha256`:
    no line number, no AST node, no source text. The one place this project must never let the
    model write is the operator surface, and a verdict is on that surface.
    """

    spec: CorePlotSpec
    table: PlottedTable
    certificate: CoreCertificate


@dataclass(frozen=True, slots=True)
class Refused:
    """The closed code IS the whole verdict. There is no free text and no echoed input."""

    code: RefusalCode


@dataclass(frozen=True, slots=True)
class Recomputation:
    """The plotted table, plus the per-group counts G11 publishes when the plot is an aggregate.

    Kept OUT of `PlottedTable` deliberately: the table is what the figure draws and what every
    comparison surface compares against, while the counts are evidence about how those rows were
    produced. A field on the comparison surface that no comparison reads is how a claim rots.
    """

    table: PlottedTable
    group_counts: tuple[int, ...] | None


type Verdict = Verified | Refused


def _refuse(code: RefusalCode, cause: BaseException | None = None) -> NoReturn:
    raise PysrcRefusalError(code) from cause


# --- request anchoring (Q8) ----------------------------------------------------------------------
# Which CSV columns a user's request names: lexical term anchoring (user ruling Q8).
#
# A refinement over the three verification tiers, never a prerequisite: a request that names no
# column anchors nothing, and the verdict proceeds exactly as before. Matching is lexical only --
# no synonyms, no translation -- so a request names a column only by spelling its header; `売上`
# never names `revenue`, while a Japanese request that writes `revenue` does.
#
# Both sides fold through NFKC (full-width forms become ASCII) and `casefold`, then split into
# words at every non-word character, `_` included, and wherever ASCII meets another script: so
# `unit_price` reads as `unit price`, and `regionごとのrevenue` names both columns. An ASCII header
# matches a request word sequence exactly; a Japanese one matches inside the request's words, since
# Japanese text carries no spaces between words. Two characters already make a Japanese word
# (`売上`), while an ASCII name needs three (`x`, `id` are ordinary request words). A one-word name
# of at least `_FUZZY_MIN` characters also matches a request span within Levenshtein distance 1: a
# word for ASCII, a stretch of near length for Japanese. A span close to TWO names, or a name two
# headers fold to, is a tie and is refused: the request does not say which column it means.
_FUZZY_MIN = 5
_ASCII_ANCHOR_MIN = 3
_OTHER_ANCHOR_MIN = 2
_WORD = re.compile(r"[a-z0-9]+|[^\Wa-z0-9_]+")


class _AmbiguousTermError(ValueError):
    """One request word sits within edit distance 1 of two different headers."""


def _words(text: str) -> str:
    """`text` as its folded words, one space apart."""
    return " ".join(_WORD.findall(unicodedata.normalize("NFKC", text).casefold()))


def _within_one(left: str, right: str) -> bool:
    """Levenshtein distance at most 1, in one pass."""
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) > len(right):
        left, right = right, left
    for index, (a, b) in enumerate(zip(left, right, strict=False)):
        if a != b:
            tail = index + 1 if len(left) == len(right) else index
            return left[tail:] == right[index + 1 :]
    return True


def _near_names(rest: str, keys: list[str]) -> list[set[str]]:
    """The names within one edit of each place in the request, overlapping stretches merged.

    A stretch is a whole word for an ASCII name, and a substring one character shorter, as long or
    longer for a Japanese one. Overlapping stretches are one place in the request, so a place within
    one edit of two names is a tie even where no single stretch fits both (`収張期血圧`).
    """
    runs = [run for run in rest.split() if run != "\0"]
    hits: list[tuple[int, int, int, str]] = []
    for key in keys:
        for index, run in enumerate(runs):
            if run.isascii() != key.isascii():
                continue
            windows = (
                [(0, len(run))]
                if key.isascii()
                else [
                    (start, start + width)
                    for width in (len(key) - 1, len(key), len(key) + 1)
                    for start in range(len(run) - width + 1)
                ]
            )
            hits += [(index, s, e, key) for s, e in windows if _within_one(run[s:e], key)]
    places: list[set[str]] = []
    place_run, place_end = -1, 0
    for index, start, end, key in sorted(hits):
        if index != place_run or start >= place_end:
            places.append(set())
            place_run, place_end = index, end
        places[-1].add(key)
        place_end = max(place_end, end)
    return places


def _named_columns(text: str, header: tuple[str, ...]) -> frozenset[str]:
    """The header names `text` names; raises `_AmbiguousTermError` on a tie."""
    by_key: dict[str, list[str]] = {}
    for column in header:
        by_key.setdefault(_words(column), []).append(column)
    rest = f" {_words(text)} "
    named: set[str] = set()
    # Exact names first, longest first, each consuming its span: `unit price` never also names
    # `price`, and `収縮期血圧値` never also names `収縮期血圧`.
    for key in sorted(by_key, key=len, reverse=True):
        needle = f" {key} " if key.isascii() else key
        floor = _ASCII_ANCHOR_MIN if key.isascii() else _OTHER_ANCHOR_MIN
        if len(key) >= floor and needle in rest:
            named.add(key)
            while needle in rest:  # adjacent occurrences share a space; one pass skips every second
                rest = rest.replace(needle, " \0 ")
    # Then one edit, over what exact names left, against every one-word name of 5+ characters.
    near = _near_names(rest, [key for key in by_key if " " not in key and len(key) >= _FUZZY_MIN])
    named |= {key for keys in near if len(keys) == 1 for key in keys}
    # A tie: one place in the request within one edit of two names, or one name two headers fold to.
    tied = [sorted(keys) for keys in near if len(keys) > 1]
    tied += [[key] for key in named if len(by_key[key]) > 1]
    if tied:
        message = f"request places {sorted(tied)} each fit more than one header"
        raise _AmbiguousTermError(message)
    return frozenset(by_key[key][0] for key in named if len(by_key[key]) == 1)


def _check_anchoring(spec: DatasetPlot, request: str, content: bytes, limits: PysrcLimits) -> None:
    """Q8: refuse a substitution -- the program drops a column the request names AND plots one it
    never names (`revenue by region`, drawn over `month`).

    Either half alone is no substitution: a request naming only the measure (`chart revenue`)
    leaves the x column to the program, and a request naming three columns lets a two-column chart
    pick two of them.

    Anchoring is a refinement: an unreadable header, a plotted column absent from it (recompute's
    own refusals) or a request naming no column leaves the verdict to the checks that follow.
    """
    header = header_names(content, limits)
    plotted = {spec.x.name, spec.y.name}
    if header is None or not plotted <= set(header):
        return
    try:
        named = _named_columns(request, header)
    except _AmbiguousTermError as exc:
        _refuse("column_not_requested", exc)
    if named - plotted and plotted - named:
        _refuse("column_not_requested")


def bind_target(
    spec: CorePlotSpec, target: DeclaredTarget | None, limits: PysrcLimits = DEFAULT_LIMITS
) -> DeclaredTarget | None:
    """Check the submitted program against the artifact the USER supplied.

    One refusal code, `target_mismatch`, covers both arms' artifact comparison: the fault shape is
    "this program is not about your artifact", and which artifact is evident from the program.
    The dataset arm's path comparison is
    byte-for-byte -- no normalization, no `Path` resolution, no case folding -- because normalizing
    would let two different files answer to one name.
    """
    if isinstance(spec, DatasetPlot):
        if not isinstance(target, DatasetTarget):
            _refuse("source_not_supplied")
        if spec.source.path != target.path:
            _refuse("target_mismatch")
        if target.request is not None:
            _check_anchoring(spec, target.request, target.content, limits)
        return target
    if isinstance(spec, FormulaPlot):
        if isinstance(target, FormulaTarget):
            if spec.y != target.y:
                _refuse("target_mismatch")
            grid = target.grid
            if isinstance(grid, Grid) and spec.grid.samples != grid.samples:
                _refuse("target_mismatch")
            if isinstance(grid, Grid | Interval) and not (
                same_bound(spec.grid.start, grid.start) and same_bound(spec.grid.stop, grid.stop)
            ):
                _refuse("target_mismatch")
            return target
        if target is None:
            return None
        if isinstance(target, DatasetTarget):
            _refuse("target_mismatch")
        assert_never(target)  # pragma: no cover - `DeclaredTarget` is closed
    assert_never(spec)  # pragma: no cover - `CorePlotSpec` is closed


def _check_expr_size(expr: Expr, limit: int) -> None:
    pending = [expr]
    count = 0
    while pending:
        node = pending.pop()
        count += 1
        if count > limit:
            _refuse("work_budget_exceeded")
        if isinstance(node, Bin):
            pending.extend((node.right, node.left))
        elif isinstance(node, Neg):
            pending.append(node.operand)
        elif isinstance(node, Fn):
            pending.append(node.arg)
        elif isinstance(node, (Num, Var, Const)):
            continue
        else:  # pragma: no cover - `Expr` is closed
            assert_never(node)


def _finish_table(
    x: tuple[CellValue, ...],
    y: tuple[float, ...],
    budget: WorkBudget,
) -> PlottedTable:
    if any(not math.isfinite(value) for value in x if isinstance(value, float)) or any(
        not math.isfinite(value) for value in y
    ):
        _refuse("value_not_finite")
    budget.charge(len(x) + len(y))
    return PlottedTable(x=x, y=y)


def _formula_table(spec: FormulaPlot, limits: PysrcLimits, budget: WorkBudget) -> PlottedTable:
    if spec.grid.samples > limits.max_table_rows:
        _refuse("work_budget_exceeded")
    for expr in (spec.grid.start, spec.grid.stop, spec.y):
        _check_expr_size(expr, limits.max_expr_nodes)
    x = materialize_grid(spec.grid, budget)
    y = tuple(evaluate_expr(spec.y, sample, budget) for sample in x)
    return _finish_table(x, y, budget)


def _dataset_table(
    spec: DatasetPlot,
    target: DeclaredTarget | None,
    limits: PysrcLimits,
    budget: WorkBudget,
) -> Recomputation:
    if not isinstance(target, DatasetTarget):  # pragma: no cover - binding closes it
        _refuse("source_not_supplied")
    series = read_columns(target.content, spec, limits, budget)
    return Recomputation(
        table=_finish_table(series.x, series.y, budget),
        group_counts=series.group_counts,
    )


def recompute(
    spec: CorePlotSpec,
    target: DeclaredTarget | None,
    limits: PysrcLimits,
) -> Recomputation:
    """Every plotted number, derived from the source rather than read from the program."""
    validate_limits(limits)
    budget = WorkBudget(limits.max_work)
    try:
        if isinstance(spec, FormulaPlot):
            return Recomputation(table=_formula_table(spec, limits, budget), group_counts=None)
        if isinstance(spec, DatasetPlot):
            return _dataset_table(spec, target, limits, budget)
        assert_never(spec)  # pragma: no cover - `CorePlotSpec` is closed
    except WorkBudgetExceededError as exc:
        _refuse("work_budget_exceeded", exc)


def _check_line_order(x: tuple[CellValue, ...]) -> None:
    text = tuple(value for value in x if isinstance(value, str))
    if text:
        if len(text) != len(x):  # pragma: no cover - recomputation emits one cell class
            _refuse("x_not_ordered")
        if len(set(text)) != len(text):
            _refuse("category_not_unique")
        return
    numeric = tuple(value for value in x if isinstance(value, float))
    if len(numeric) != len(x) or any(
        numeric[index] > numeric[index + 1] for index in range(len(numeric) - 1)
    ):
        _refuse("x_not_ordered")


def _formula_integrity(spec: FormulaPlot, table: PlottedTable) -> None:
    match spec.mark:
        case "line":
            _check_line_order(table.x)
        case "scatter":
            return
        case _ as unreachable:  # pragma: no cover - the mark union is closed
            assert_never(unreachable)


def _dataset_integrity(spec: DatasetPlot, table: PlottedTable) -> None:
    match spec.mark:
        case "bar" | "barh":
            categories = tuple(value for value in table.x if isinstance(value, str))
            if len(categories) == len(table.x) and len(set(categories)) != len(categories):
                _refuse("category_not_unique")
        case "line":
            _check_line_order(table.x)
        case "scatter":
            return
        case _ as unreachable:  # pragma: no cover - the mark union is closed
            assert_never(unreachable)


def check_integrity(spec: CorePlotSpec, table: PlottedTable) -> None:
    """The G-rules that become decidable only once the table exists. Raises, or returns."""
    if isinstance(spec, FormulaPlot):
        _formula_integrity(spec, table)
    elif isinstance(spec, DatasetPlot):
        _dataset_integrity(spec, table)
    else:  # pragma: no cover - `CorePlotSpec` is closed
        assert_never(spec)


def verify_python_source(
    source: str,
    *,
    declared_target: DeclaredTarget | None = None,
    limits: PysrcLimits = DEFAULT_LIMITS,
) -> Verdict:
    """Verify model-authored Python that draws one chart.

    Total over the admitted subset: every admitted program either verifies or refuses with a closed
    code. `source` is `str` because that is what an LLM completion is; it is encoded once here, and
    a lone surrogate -- which no UTF-8 encoder accepts -- refuses like any other non-UTF-8 input
    rather than escaping as a `UnicodeEncodeError`.
    """
    try:
        try:
            source_bytes = source.encode("utf-8")
        except UnicodeEncodeError as exc:
            _refuse("source_not_utf8", exc)
        text = prescan(source_bytes, limits)
        tree = parse_admitted(text)
        spec = project(tree, limits)
        bound_target = bind_target(spec, declared_target, limits)
        recomputation = recompute(spec, bound_target, limits)
        table = recomputation.table
        check_integrity(spec, table)
        certificate = certify(spec, table, source_bytes, bound_target, recomputation.group_counts)
        return Verified(spec=spec, table=table, certificate=certificate)
    except PysrcRefusalError as exc:
        return Refused(code=exc.code)
