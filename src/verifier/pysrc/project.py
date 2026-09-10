# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Admitted AST -> core plot spec. This is where the projection gap is closed.

Admission answers "may these bytes run". Projection answers "what do they draw", and the verifier
stakes every downstream claim on that answer, so the gap -- *what the projection says the script
plots* vs *what the script plots when executed* -- is closed BY CONSTRUCTION here rather than
declared trusted: every admitted statement must contribute to the returned spec, and a statement
whose effect the spec cannot represent is refused. Nothing is silently ignored. A construct added
to `admit.py` without a projection rule therefore fails closed instead of vanishing from the claim.

Bound names are SUBSTITUTED away, so the spec depends on what the program computes and not on what
the model chose to call it. Two programs differing only in variable names project to equal specs.

Scope is the formula arm. `plt.bar` is refused here rather than in `admit.py` because it is
admissible in the dataset arm: what refuses it is the arm, not the call.
"""

import ast
import math
from fractions import Fraction
from typing import NoReturn

from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.limits import DEFAULT_LIMITS, PysrcLimits, validate_limits
from verifier.pysrc.spec import (
    Bin,
    BinOp,
    Column,
    Const,
    ConstName,
    CorePlotSpec,
    DatasetMark,
    DatasetPlot,
    DatasetRef,
    Expr,
    Fn,
    FnName,
    FormulaMark,
    FormulaPlot,
    Grid,
    Labels,
    Neg,
    Num,
    Var,
)

_GRID_CALLS = frozenset({"np.linspace", "np.arange"})
# Source spelling -> projected meaning. Exhaustive over `admit.ADMITTED_CALL_TARGETS`' math group;
# a target admitted but missing here reaches the closed tail and refuses.
_FUNCTIONS: dict[str, FnName] = {
    "np.sin": "sin",
    "np.cos": "cos",
    "np.tan": "tan",
    "np.exp": "exp",
    "np.log": "log",
    "np.sqrt": "sqrt",
    "np.abs": "abs",
}
_CONSTANTS: dict[str, ConstName] = {"np.pi": "pi", "np.e": "e"}
_MARKS: dict[str, FormulaMark] = {"plt.plot": "line", "plt.scatter": "scatter"}
# The same three targets, read under the other arm. Bar appears here and not above: G5 bans bar for
# SAMPLED FUNCTIONS, not for CSV columns.
_DATASET_MARKS: dict[str, DatasetMark] = {
    "plt.plot": "line",
    "plt.scatter": "scatter",
    "plt.bar": "bar",
}
_SOURCE_CALL = "pd.read_csv"


def _uses_grid(tree: ast.Module) -> bool:
    """Whether a grid call appears anywhere -- the formula arm's structural selector."""
    return any(
        isinstance(node, ast.Call) and _call_target(node) in _GRID_CALLS for node in ast.walk(tree)
    )


# Admissible source, inadmissible for THIS arm: a sampled function has no categorical magnitude to
# encode as a length from a zero baseline (G5).
_WRONG_ARM_MARKS = frozenset({"plt.bar"})
_TERMINAL = "plt.show"
_TEXT_LABELS = frozenset({"plt.title", "plt.xlabel", "plt.ylabel"})
_FLAG_LABELS = frozenset({"plt.legend", "plt.grid"})

# A mark draws one series: x and y, never an implicit x and never a third positional.
_MARK_ARITY = 2
_LINSPACE_BOUNDS_ARITY = 2
_LINSPACE_FULL_ARITY = 3
_ARANGE_MAX_ARITY = 3
# Every integer up to 2**53 is exactly representable in float64; 2**52 leaves the difference of
# two bounds inside that range, which is what makes `arange`'s float64 sizing provably exact.
_EXACT_INT = 2**52

_BINOPS: dict[type[ast.operator], BinOp] = {
    ast.Add: "add",
    ast.Sub: "sub",
    ast.Mult: "mul",
    ast.Div: "div",
    ast.Pow: "pow",
}


def _refuse(code: RefusalCode) -> NoReturn:
    raise PysrcRefusalError(code)


def _dotted(node: ast.Attribute) -> str:
    """`alias.attr` for a chain admission has already bounded to depth 1."""
    value = node.value
    if not isinstance(value, ast.Name):  # pragma: no cover - admission refuses deeper chains
        _refuse("expression_not_projected")
    return f"{value.id}.{node.attr}"


def _call_target(node: ast.Call) -> str:
    func = node.func
    if not isinstance(func, ast.Attribute):  # pragma: no cover - admission refuses bare calls
        _refuse("expression_not_projected")
    return _dotted(func)


class _Projector:
    """One projection. Mutable only for the duration of a single `project` call."""

    def __init__(self, limits: PysrcLimits) -> None:
        self._limits = limits
        self._aliases: set[str] = set()
        self._grids: dict[str, Grid] = {}
        self._exprs: dict[str, ast.expr] = {}
        self._used: set[str] = set()
        # The mark is held by TARGET, not by projected mark: which meaning `plt.bar` carries depends
        # on the arm, and the arm is settled before any statement runs.
        self._mark: tuple[str, ast.Call] | None = None
        self._frames: dict[str, DatasetRef] = {}
        self._cols: dict[str, tuple[str, Column]] = {}
        self._pandas = False
        # Decorations are collected keyed by their source target and assembled into `Labels` once,
        # so every field has exactly one origin and no branch has to guess which field it is.
        self._decorated: set[str] = set()
        self._text: dict[str, str] = {}
        self._flags: dict[str, bool] = {}
        self._series: str | None = None
        self._grid_in_scope: Grid | None = None
        self._terminal = False

    # --- expressions ---------------------------------------------------------

    def _literal(self, node: ast.Constant) -> Expr:
        value = node.value
        # Exact type, never `isinstance`: `bool` subclasses `int`, and `True` is a flag for
        # `plt.grid`, never a number to plot.
        if type(value) is int:
            return Num(Fraction(value))
        if type(value) is float:
            # The executed program hands numpy the float64, so the projection carries the float64.
            if not math.isfinite(value):
                _refuse("expression_not_projected")
            return Num(Fraction(value))
        _refuse("expression_not_projected")

    def _expr(self, node: ast.expr, grid_name: str | None) -> Expr:
        """Project one admitted expression, substituting bound names away.

        `grid_name` is the only free name the result may carry; `None` means none may.
        """
        if isinstance(node, ast.Constant):
            return self._literal(node)
        if isinstance(node, ast.Name):
            return self._name(node.id, grid_name)
        if isinstance(node, ast.Attribute):
            constant = _CONSTANTS.get(_dotted(node))
            if constant is None:  # pragma: no cover - `ADMITTED_CONSTANT_ATTRS` == `_CONSTANTS`
                _refuse("expression_not_projected")
            return Const(constant)
        if isinstance(node, ast.Call):
            return self._call_expr(node, grid_name)
        if isinstance(node, ast.BinOp):
            operator = _BINOPS.get(type(node.op))
            if operator is None:  # pragma: no cover - admission closes the operator set
                _refuse("expression_not_projected")
            left = self._expr(node.left, grid_name)
            return Bin(operator, left, self._expr(node.right, grid_name))
        if isinstance(node, ast.UnaryOp):
            return Neg(self._expr(node.operand, grid_name))
        _refuse("expression_not_projected")  # pragma: no cover - admission closes the tail

    def _call_expr(self, node: ast.Call, grid_name: str | None) -> Expr:
        target = _call_target(node)
        if target in _GRID_CALLS:
            # The grid call written twice -- once as x, once inside y -- names the same sample
            # points, so it projects to the grid variable exactly when the two grids are equal.
            if self._grid(node) != self._grid_in_scope:
                _refuse("y_not_over_grid")
            return Var()
        function = _FUNCTIONS.get(target)
        if function is None or len(node.args) != 1 or node.keywords:
            _refuse("expression_not_projected")
        return Fn(function, self._expr(node.args[0], grid_name))

    def _name(self, name: str, grid_name: str | None) -> Expr:
        if name == grid_name:
            return Var()
        bound_grid = self._grids.get(name)
        if bound_grid is not None:
            # A grid reached by a route other than the mark's x argument. Structural equality
            # decides it: the same sample points ARE the grid variable, however the model spelled
            # them, and different points mean y is not a function of THE grid.
            if bound_grid != self._grid_in_scope:
                _refuse("y_not_over_grid")
            self._used.add(name)
            return Var()
        bound = self._exprs.get(name)
        if bound is None:
            # An alias (`np`, `plt`) in value position, or a name admission bound but projection
            # never saw -- neither denotes a number.
            _refuse("expression_not_projected")
        self._used.add(name)
        return self._expr(bound, grid_name)

    def _rational(self, node: ast.expr) -> Fraction:
        """A grid bound that arithmetic must reach: symbolic constants have no exact value."""
        projected = self._expr(node, None)
        # A source `-1` is `UnaryOp(USub, 1)`, so a descending `np.arange(5, 0, -1)` reaches here
        # as `Neg(Num)`. Folding it is exact; anything wider (`2 + 3`, `np.pi`) stays refused,
        # since a general folder needs its own ruling on division by zero and on `pow`.
        if isinstance(projected, Neg) and isinstance(projected.operand, Num):
            return -projected.operand.value
        if not isinstance(projected, Num):
            _refuse("grid_not_representable")
        return projected.value

    # --- grids ---------------------------------------------------------------

    def _samples(self, count: int) -> int:
        if not (self._limits.min_grid_samples <= count <= self._limits.max_grid_samples):
            _refuse("grid_not_representable")
        return count

    def _linspace(self, node: ast.Call) -> Grid:
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        num_node = keywords.get("num")
        if len(node.args) == _LINSPACE_FULL_ARITY:
            if num_node is not None:
                _refuse("grid_not_representable")
            num_node = node.args[2]
        elif len(node.args) != _LINSPACE_BOUNDS_ARITY:
            _refuse("grid_not_representable")
        if num_node is None:
            count = 50  # numpy's own default; a program omitting `num` still draws 50 points.
        elif isinstance(num_node, ast.Constant) and type(num_node.value) is int:
            count = num_node.value
        else:
            # A bound name resolving to 10 is still not a literal: the count has to be readable
            # from the source, or the grid's size depends on evaluation.
            _refuse("grid_not_representable")
        return Grid(
            start=self._expr(node.args[0], None),
            stop=self._expr(node.args[1], None),
            samples=self._samples(count),
        )

    def _arange(self, node: ast.Call) -> Grid:
        if node.keywords or not 1 <= len(node.args) <= _ARANGE_MAX_ARITY:
            _refuse("grid_not_representable")
        bounds = [self._rational(arg) for arg in node.args]
        start, stop = (Fraction(0), bounds[0]) if len(bounds) == 1 else (bounds[0], bounds[1])
        step = bounds[2] if len(bounds) == _ARANGE_MAX_ARITY else Fraction(1)
        # INTEGERS ONLY, and it is a faithfulness bound rather than a taste. numpy sizes `arange`
        # as ceil((stop - start) / step) in float64 and accumulates its samples in float64, so a
        # non-integer step makes the EXECUTED array disagree with the exact-rational grid by a
        # whole step: measured, `arange(0, 3, 0.3)` draws 10 points ending at 2.6999999999999997
        # where the exact grid says 11 ending at 3, and `arange(1, 2, 0.1)` ends at
        # 1.9000000000000008, not 1.9. numpy's own reference calls non-integer steps inconsistent
        # and points at `linspace`, which is the admitted tool for real-valued sampling and whose
        # residual is a per-sample rounding rather than a different number of samples. Under
        # `_EXACT_INT` every operation above is exact in float64, so the projection stays faithful
        # BY CONSTRUCTION; over it, `ceil` could misround.
        if any(value.denominator != 1 for value in (start, stop, step)) or any(
            abs(value.numerator) > _EXACT_INT for value in (start, stop, step)
        ):
            _refuse("grid_not_representable")
        if step == 0:
            _refuse("grid_not_representable")
        span = (stop - start) / step
        if span <= 0:
            _refuse("grid_not_representable")
        # Half-open: `arange(0, 10)` is 0..9. Normalizing onto an inclusive stop is what makes one
        # `Grid` shape serve both call forms, and it is why this form needs exact arithmetic.
        count = self._samples(math.ceil(span))
        return Grid(start=Num(start), stop=Num(start + (count - 1) * step), samples=count)

    def _grid(self, node: ast.Call) -> Grid:
        return self._linspace(node) if _call_target(node) == "np.linspace" else self._arange(node)

    # --- dataset arm ---------------------------------------------------------

    def _source(self, node: ast.Call) -> DatasetRef:
        if len(node.args) != 1 or node.keywords:
            _refuse("source_not_literal")
        arg = node.args[0]
        if not isinstance(arg, ast.Constant) or type(arg.value) is not str:
            _refuse("source_not_literal")
        return DatasetRef(path=arg.value)

    def _column_parts(self, node: ast.Subscript) -> tuple[str, Column]:
        """`<frame>["<literal>"]` split into the frame it reads and the column it names."""
        value = node.value
        if not isinstance(value, ast.Name):  # pragma: no cover - admission refuses other bases
            _refuse("column_not_from_source")
        index = node.slice
        if not isinstance(index, ast.Constant) or type(index.value) is not str:
            _refuse("column_not_literal")  # pragma: no cover - admission refuses non-literal keys
        return value.id, Column(name=index.value)

    def _channel(self, node: ast.expr) -> tuple[str, Column]:
        """One mark channel, from the inline subscript or the name a subscript was bound to."""
        if isinstance(node, ast.Subscript):
            frame, column = self._column_parts(node)
        elif isinstance(node, ast.Name) and node.id in self._cols:
            frame, column = self._cols[node.id]
            self._used.add(node.id)
        else:
            _refuse("column_not_from_source")
        if frame not in self._frames:
            _refuse("column_not_from_source")
        self._used.add(frame)
        return frame, column

    # --- statements ----------------------------------------------------------

    def _assign(self, node: ast.Assign) -> None:
        target = node.targets[0]
        if not isinstance(target, ast.Name):  # pragma: no cover - admission refuses other targets
            _refuse("statement_not_projected")
        name = target.id
        if (
            name in self._aliases
            or name in self._grids
            or name in self._exprs
            or name in self._frames
            or name in self._cols
        ):
            _refuse("name_rebound")
        value = node.value
        if isinstance(value, ast.Call) and _call_target(value) in _GRID_CALLS:
            self._grids[name] = self._grid(value)
        elif isinstance(value, ast.Call) and _call_target(value) == _SOURCE_CALL:
            if self._frames:
                _refuse("multiple_sources")
            self._frames[name] = self._source(value)
        elif isinstance(value, ast.Subscript):
            self._cols[name] = self._column_parts(value)
        else:
            # Held unprojected: a bound expression is only meaningful once the grid it reads is
            # known, and that is decided at the mark.
            self._exprs[name] = value

    def _label_call(self, target: str, node: ast.Call) -> None:
        if target in self._decorated:
            # The earlier call ran, and its text would vanish from the spec.
            _refuse("statement_not_projected")
        self._decorated.add(target)
        if target in _TEXT_LABELS:
            if len(node.args) != 1 or node.keywords:
                _refuse("label_not_literal")
            text = node.args[0]
            if not isinstance(text, ast.Constant) or type(text.value) is not str:
                _refuse("label_not_literal")
            self._text[target] = text.value
            return
        if node.keywords or len(node.args) > 1:
            _refuse("label_not_literal")
        flag = True
        if node.args:
            arg = node.args[0]
            if not isinstance(arg, ast.Constant) or type(arg.value) is not bool:
                _refuse("label_not_literal")
            flag = arg.value
        self._flags[target] = flag

    def _labels(self) -> Labels:
        return Labels(
            title=self._text.get("plt.title"),
            xlabel=self._text.get("plt.xlabel"),
            ylabel=self._text.get("plt.ylabel"),
            series=self._series,
            legend=self._flags.get("plt.legend", False),
            grid=self._flags.get("plt.grid", False),
        )

    def _call_statement(self, node: ast.Call) -> None:
        target = _call_target(node)
        if target == _TERMINAL:
            if node.args or node.keywords:
                _refuse("statement_not_projected")
            self._terminal = True
            return
        if target in _DATASET_MARKS:
            # Arm validity is LOCAL to this statement and is therefore decided before the
            # program-wide mark count: `plt.bar` after a `plt.plot` refuses `mark_not_valid_for_arm`
            # in the formula arm, not `multiple_marks`.
            if not self._pandas and target in _WRONG_ARM_MARKS:
                _refuse("mark_not_valid_for_arm")
            if self._mark is not None:
                _refuse("multiple_marks")
            self._mark = (target, node)
            return
        if target in _TEXT_LABELS or target in _FLAG_LABELS:
            self._label_call(target, node)
            return
        # An admitted call with no drawing effect -- `np.sin(x)` as a statement computes and
        # discards. Representing it is impossible; ignoring it would widen the gap.
        _refuse("statement_not_projected")

    def _statement(self, node: ast.stmt) -> None:
        if self._terminal:
            _refuse("statement_after_terminal")
        if isinstance(node, ast.Import):
            for alias in node.names:
                self._aliases.add(alias.asname or alias.name)
            return
        if isinstance(node, ast.Assign):
            self._assign(node)
            return
        if isinstance(node, ast.Expr):
            value = node.value
            if not isinstance(value, ast.Call):  # pragma: no cover - admission refuses non-calls
                _refuse("statement_not_projected")
            self._call_statement(value)
            return
        _refuse("statement_not_projected")  # pragma: no cover - admission closes the tail

    # --- assembly ------------------------------------------------------------

    def _mark_shape(self, node: ast.Call) -> None:
        """Arity and the one admitted keyword -- identical under both arms, so stated once."""
        if len(node.args) != _MARK_ARITY:
            _refuse("mark_arity_not_projected")
        for keyword in node.keywords:
            if keyword.arg != "label":  # pragma: no cover - admission closes the keyword set
                _refuse("label_not_literal")
            text = keyword.value
            if not isinstance(text, ast.Constant) or type(text.value) is not str:
                _refuse("label_not_literal")
            self._series = text.value

    def _resolve_dataset_mark(self, target: str, node: ast.Call) -> DatasetPlot:
        self._mark_shape(node)
        x_frame, x = self._channel(node.args[0])
        y_frame, y = self._channel(node.args[1])
        if x_frame != y_frame:  # pragma: no cover - `multiple_sources` keeps `_frames` a singleton
            # Dead while exactly one source binds, and kept anyway: the day a second source is
            # admitted, this is the line that stops the figure being a join no projection states.
            _refuse("column_not_from_source")
        return DatasetPlot(
            mark=_DATASET_MARKS[target],
            source=self._frames[x_frame],
            x=x,
            y=y,
            labels=self._labels(),
        )

    def _resolve_mark(self, mark: FormulaMark, node: ast.Call) -> FormulaPlot:
        self._mark_shape(node)
        x_node = node.args[0]
        grid_name: str | None = None
        if isinstance(x_node, ast.Name) and x_node.id in self._grids:
            grid_name = x_node.id
            grid = self._grids[grid_name]
            self._used.add(grid_name)
        elif isinstance(x_node, ast.Call) and _call_target(x_node) in _GRID_CALLS:
            grid = self._grid(x_node)
        else:
            _refuse("x_not_a_grid")
        self._grid_in_scope = grid
        return FormulaPlot(
            mark=mark, grid=grid, y=self._expr(node.args[1], grid_name), labels=self._labels()
        )

    def run(self, tree: ast.Module) -> CorePlotSpec:
        # The arm is settled from the tree BEFORE any statement runs, because a mark statement's own
        # validity depends on it. Both selectors present is a refusal, never a precedence.
        self._pandas = any(
            isinstance(node, ast.Import) and any(alias.name == "pandas" for alias in node.names)
            for node in tree.body
        )
        if self._pandas and _uses_grid(tree):
            _refuse("arm_ambiguous")
        for statement in tree.body:
            self._statement(statement)
        if self._mark is None:
            _refuse("no_mark")
        if not self._terminal:
            _refuse("no_terminal")
        target, node = self._mark
        if self._pandas:
            if not self._frames:
                _refuse("no_source")
            plot: CorePlotSpec = self._resolve_dataset_mark(target, node)
        else:
            plot = self._resolve_mark(_MARKS[target], node)
        unused = (
            self._grids.keys() | self._exprs.keys() | self._frames.keys() | self._cols.keys()
        ) - self._used
        if unused:
            # Bound, admitted, executed, and absent from the spec: exactly the gap this module
            # exists to close.
            _refuse("statement_not_projected")
        return plot


def project(tree: ast.Module, limits: PysrcLimits = DEFAULT_LIMITS) -> CorePlotSpec:
    """Project an ADMITTED tree onto the core plot spec, or raise `PysrcRefusalError`.

    `tree` must be what `parse_admitted` returned: every guarantee here rests on the allowlist
    having run first, and the closed tails below are unreachable only under that precondition.
    """
    validate_limits(limits)
    return _Projector(limits).run(tree)
