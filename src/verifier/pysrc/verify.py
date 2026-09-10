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
from dataclasses import dataclass
from typing import NoReturn, assert_never

from verifier.pysrc.admit import parse_admitted
from verifier.pysrc.budget import WorkBudget, WorkBudgetExceededError
from verifier.pysrc.certificate import CoreCertificate, certify
from verifier.pysrc.csvread import read_columns
from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.limits import DEFAULT_LIMITS, PysrcLimits, validate_limits
from verifier.pysrc.numeric import evaluate_expr, materialize_grid
from verifier.pysrc.prescan import prescan
from verifier.pysrc.project import project
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


type Verdict = Verified | Refused


def _refuse(code: RefusalCode, cause: BaseException | None = None) -> NoReturn:
    raise PysrcRefusalError(code) from cause


def bind_target(spec: CorePlotSpec, target: DeclaredTarget | None) -> DeclaredTarget | None:
    """Check the submitted program against the artifact the USER supplied.

    One refusal code covers both arms: the fault shape is "this program is not about your
    artifact", and which artifact is evident from the program. The dataset arm's path comparison is
    byte-for-byte -- no normalization, no `Path` resolution, no case folding -- because normalizing
    would let two different files answer to one name.
    """
    if isinstance(spec, DatasetPlot):
        if not isinstance(target, DatasetTarget):
            _refuse("source_not_supplied")
        if spec.source.path != target.path:
            _refuse("target_mismatch")
        return target
    if isinstance(spec, FormulaPlot):
        if isinstance(target, FormulaTarget):
            if spec.y != target.y or (target.grid is not None and spec.grid != target.grid):
                _refuse("target_mismatch")
            return target
        if target is None:
            return None
        if isinstance(target, DatasetTarget):
            return target
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
) -> PlottedTable:
    if not isinstance(target, DatasetTarget):  # pragma: no cover - binding closes it
        _refuse("source_not_supplied")
    x, y = read_columns(target.content, spec, limits, budget)
    return _finish_table(x, y, budget)


def recompute(
    spec: CorePlotSpec,
    target: DeclaredTarget | None,
    limits: PysrcLimits,
) -> PlottedTable:
    """Every plotted number, derived from the source rather than read from the program."""
    validate_limits(limits)
    budget = WorkBudget(limits.max_work)
    try:
        if isinstance(spec, FormulaPlot):
            return _formula_table(spec, limits, budget)
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
        case "bar":
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
        bound_target = bind_target(spec, declared_target)
        table = recompute(spec, bound_target, limits)
        check_integrity(spec, table)
        certificate = certify(spec, table, source_bytes, bound_target)
        return Verified(spec=spec, table=table, certificate=certificate)
    except PysrcRefusalError as exc:
        return Refused(code=exc.code)
