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
from dataclasses import dataclass, field
from typing import NoReturn, assert_never

from verifier.figure.anchoring import AmbiguousTermError as _AmbiguousTermError
from verifier.figure.anchoring import anchors as _anchors
from verifier.figure.anchoring import nameable as _nameable
from verifier.figure.anchoring import named_columns as _named_columns
from verifier.figure.anchoring import summaries as _summaries
from verifier.pysrc.admit import parse_admitted
from verifier.pysrc.budget import WorkBudget, WorkBudgetExceededError
from verifier.pysrc.certificate import CoreCertificate, certify
from verifier.pysrc.csvread import header_names, read_columns
from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.limits import DEFAULT_LIMITS, PysrcLimits, validate_limits
from verifier.pysrc.numeric import evaluate_expr, materialize_grid
from verifier.pysrc.position import Role, SourceMap, Span, Trace
from verifier.pysrc.prescan import prescan
from verifier.pysrc.project import project, same_bound, statement_trace
from verifier.pysrc.spec import (
    Aliases,
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
    """Carries the projection, the recomputation and the certificate, plus where each statement
    sits.

    Deliberately holds no raw source text, no AST node and no unprojected identifier: the spec
    carries only what the figure states (its literal labels included) and the certificate the
    source's digest. The one place this project must never let the model write is the operator
    surface, and a verdict is on that surface. `trace` is integers and a closed role per statement
    -- what a reader needs to find the code in the program they already hold -- and is a
    diagnostic outside the verdict's identity.
    """

    spec: CorePlotSpec
    table: PlottedTable
    certificate: CoreCertificate
    trace: Trace = field(default=(), compare=False)


@dataclass(frozen=True, slots=True)
class Refused:
    """The closed code IS the whole verdict. There is no free text and no echoed input.

    `at` = where in the program the refusal points (`()` = no single place: a whole-program fault,
    or one in the file, the data or the request); `trace` = the statement roles once projection
    succeeded. Both are diagnostics outside the verdict's identity.
    """

    code: RefusalCode
    at: tuple[Span, ...] = field(default=(), compare=False)
    trace: Trace = field(default=(), compare=False)


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


def _refuse(
    code: RefusalCode,
    cause: BaseException | None = None,
    *,
    at: tuple[Span, ...] = (),
    role: Role | None = None,
) -> NoReturn:
    raise PysrcRefusalError(code, at=at, role=role) from cause


def _check_anchoring(
    spec: DatasetPlot, target: DatasetTarget, request: str, limits: PysrcLimits
) -> None:
    """Q8: refuse a substitution -- the program drops a column the request names AND plots one it
    never names (`revenue by region`, drawn over `month`).

    Either half alone is no substitution: a request naming only the measure (`chart revenue`)
    leaves the x column to the program, and a request naming three columns lets a two-column chart
    pick two of them. Strict anchoring (Q37, production) refuses the second half alone too: once a
    request names or negates a column, it must name every drawn column a request can name.

    Anchoring is a refinement: an unreadable header, a plotted column absent from it (recompute's
    own refusals) or a request naming no column leaves the verdict to the checks that follow.
    """
    header = header_names(target.content, limits)
    plotted = {spec.x.name, spec.y.name}
    if header is None or not plotted <= set(header):
        return
    try:
        named, negated = _anchors(
            request, header, target.aliases, short_names=target.anchoring == "strict"
        )
    except _AmbiguousTermError as exc:
        _refuse("column_not_requested", exc)
    if named - plotted and plotted - named:
        _refuse("column_not_requested")
    match target.anchoring:
        case "strict":
            if (named or negated) and any(_nameable(c, target.aliases) for c in plotted - named):
                _refuse("column_not_named")
        case "substitution":
            pass
        case _ as unreachable:  # pragma: no cover - the anchoring union is closed
            assert_never(unreachable)


def _check_labels(spec: DatasetPlot, header: tuple[str, ...], aliases: Aliases = ()) -> None:
    drawn = {spec.x.name, spec.y.name}
    labels = spec.labels
    # Each label with the statement that wrote it: the series text is the mark's `label=`.
    texts: tuple[tuple[Role, str | None], ...] = (
        ("title", labels.title),
        ("xlabel", labels.xlabel),
        ("ylabel", labels.ylabel),
        ("mark", labels.series),
    )
    for role, text in texts:
        if text is None:
            continue
        if _named_columns(text, header, aliases, ignore_ties=True) - drawn:
            _refuse("label_not_consistent", role=role)
        if spec.group is not None and _summaries(text, header, aliases) - {spec.group}:
            _refuse("label_not_consistent", role=role)


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
            _refuse("source_not_supplied", role="source")
        if spec.source.path != target.path:
            _refuse("target_mismatch", role="source")
        if target.request is not None:
            _check_anchoring(spec, target, target.request, limits)
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


def _dataset_integrity(
    spec: DatasetPlot, table: PlottedTable, header: tuple[str, ...], aliases: Aliases = ()
) -> None:
    match spec.mark:
        case "bar" | "barh":
            categories = tuple(value for value in table.x if isinstance(value, str))
            if len(categories) == len(table.x) and len(set(categories)) != len(categories):
                _refuse("category_not_unique")
        case "line":
            _check_line_order(table.x)
        case "scatter":
            pass
        case _ as unreachable:  # pragma: no cover - the mark union is closed
            assert_never(unreachable)
    _check_labels(spec, header, aliases)


def check_integrity(
    spec: CorePlotSpec, table: PlottedTable, header: tuple[str, ...] = (), aliases: Aliases = ()
) -> None:
    """The G-rules that become decidable only once the table exists. Raises, or returns.

    `header` = the dataset's column names, which G10 matches labels against; empty for a formula.
    """
    if isinstance(spec, FormulaPlot):
        _formula_integrity(spec, table)
    elif isinstance(spec, DatasetPlot):
        _dataset_integrity(spec, table, header, aliases)
    else:  # pragma: no cover - `CorePlotSpec` is closed
        assert_never(spec)


def _header(target: DeclaredTarget | None, limits: PysrcLimits) -> tuple[str, ...]:
    # Recomputation already read this header, so `None` (unreadable) cannot reach here; `()`
    # would name nothing.
    if isinstance(target, DatasetTarget):
        return header_names(target.content, limits) or ()
    return ()


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
    trace: Trace = ()
    try:
        try:
            source_bytes = source.encode("utf-8")
        except UnicodeEncodeError as exc:
            _refuse("source_not_utf8", exc, at=(SourceMap(source).char(exc.start),))
        text = prescan(source_bytes, limits)
        tree = parse_admitted(text)
        spec = project(tree, limits)
        trace = statement_trace(tree)
        bound_target = bind_target(spec, declared_target, limits)
        recomputation = recompute(spec, bound_target, limits)
        table = recomputation.table
        aliases = bound_target.aliases if isinstance(bound_target, DatasetTarget) else ()
        check_integrity(spec, table, _header(bound_target, limits), aliases)
        certificate = certify(spec, table, source_bytes, bound_target, recomputation.group_counts)
        return Verified(spec=spec, table=table, certificate=certificate, trace=trace)
    except PysrcRefusalError as exc:
        # A stage that sees the spec, not the tree, names the ROLE of the statement to point at.
        at = exc.at or tuple(step.span for step in trace if step.role == exc.role)
        return Refused(code=exc.code, at=at, trace=trace)
