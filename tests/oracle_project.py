# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Independent M13.3 AST-to-plot projection oracle.

The oracle classifies the whole module before assembling a value model. Production is expected to
use its own representation and traversal; ``normalize`` is the sole comparison boundary.
"""

import ast
import math
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from fractions import Fraction
from typing import Literal, NoReturn, cast

type OracleRefusalCode = Literal[
    "no_mark",
    "multiple_marks",
    "x_not_a_grid",
    "y_not_over_grid",
    "grid_not_representable",
    "label_not_literal",
    "no_terminal",
    "statement_after_terminal",
    "name_rebound",
    "mark_not_valid_for_arm",
    "statement_not_projected",
]

type Mark = Literal["line", "scatter"]
type Function = Literal["sin", "cos", "tan", "exp", "log", "sqrt", "abs"]
type ConstantName = Literal["pi", "e"]
type BinaryOperator = Literal["add", "sub", "mul", "div", "pow"]

_MIN_GRID_SAMPLES = 2
_MAX_GRID_SAMPLES = 100_000
_EXACT_GRID_INTEGER = 2**52
_GRID_TARGETS = frozenset({"np.linspace", "np.arange"})
_MARK_TARGETS = frozenset({"plt.plot", "plt.scatter", "plt.bar"})
_LABEL_TARGETS = frozenset({"plt.title", "plt.xlabel", "plt.ylabel"})
_DECOR_TARGETS = _LABEL_TARGETS | {"plt.legend", "plt.grid"}
_MATH_FUNCTIONS: dict[str, Function] = {
    "np.sin": "sin",
    "np.cos": "cos",
    "np.tan": "tan",
    "np.exp": "exp",
    "np.log": "log",
    "np.sqrt": "sqrt",
    "np.abs": "abs",
}


class OracleProjectionError(Exception):
    """An independently detected projection refusal."""

    def __init__(self, code: OracleRefusalCode) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class Number:
    value: Fraction


@dataclass(frozen=True, slots=True)
class Constant:
    name: ConstantName


@dataclass(frozen=True, slots=True)
class Variable:
    pass


@dataclass(frozen=True, slots=True)
class Unary:
    operand: "Expression"


@dataclass(frozen=True, slots=True)
class Binary:
    op: BinaryOperator
    left: "Expression"
    right: "Expression"


@dataclass(frozen=True, slots=True)
class Call:
    function: Function
    argument: "Expression"


type Expression = Number | Constant | Variable | Unary | Binary | Call


@dataclass(frozen=True, slots=True)
class Grid:
    start: Expression
    stop: Expression
    count: int


@dataclass(frozen=True, slots=True)
class Labels:
    title: str | None = None
    xlabel: str | None = None
    ylabel: str | None = None
    series: str | None = None
    legend: bool = False
    grid: bool = False


@dataclass(frozen=True, slots=True)
class FormulaPlot:
    grid: Grid
    expression: Expression
    mark: Mark
    labels: Labels


type OraclePlotSpec = FormulaPlot


@dataclass(frozen=True, slots=True)
class _Binding:
    statement_index: int
    value: ast.expr


@dataclass(frozen=True, slots=True)
class _CallStatement:
    statement_index: int
    call: ast.Call
    target: str | None


@dataclass(frozen=True, slots=True)
class _Program:
    bindings: dict[str, _Binding]
    calls: tuple[_CallStatement, ...]
    structural_statements: frozenset[int]


@dataclass(frozen=True, slots=True)
class _ProjectedExpression:
    value: Expression
    over_grid: bool


def _refuse(code: OracleRefusalCode) -> NoReturn:
    raise OracleProjectionError(code)


def _target(call: ast.Call) -> str | None:
    func = call.func
    if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
        return None
    return f"{func.value.id}.{func.attr}"


def _classify(tree: ast.Module) -> _Program:
    """Pass one: record bindings and top-level calls without projecting either."""
    seen: set[str] = set()
    bindings: dict[str, _Binding] = {}
    calls: list[_CallStatement] = []
    structural: set[int] = set()

    for index, statement in enumerate(tree.body):
        if isinstance(statement, ast.Import):
            structural.add(index)
            for alias in statement.names:
                name = alias.asname
                if name is None:
                    _refuse("statement_not_projected")
                if name in seen:
                    _refuse("name_rebound")
                seen.add(name)
            continue
        if isinstance(statement, ast.Assign):
            target = statement.targets[0]
            if not isinstance(target, ast.Name):
                _refuse("statement_not_projected")
            if target.id in seen:
                _refuse("name_rebound")
            seen.add(target.id)
            bindings[target.id] = _Binding(index, statement.value)
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            calls.append(_CallStatement(index, statement.value, _target(statement.value)))
            continue
        _refuse("statement_not_projected")

    return _Program(bindings, tuple(calls), frozenset(structural))


def _effect_calls(tree: ast.Module, targets: frozenset[str]) -> list[ast.Call]:
    return [
        node for node in ast.walk(tree) if isinstance(node, ast.Call) and _target(node) in targets
    ]


def _top_level_call(program: _Program, call: ast.Call) -> _CallStatement | None:
    return next((statement for statement in program.calls if statement.call is call), None)


def _checked_sample_count(count: int) -> int:
    if not _MIN_GRID_SAMPLES <= count <= _MAX_GRID_SAMPLES:
        _refuse("grid_not_representable")
    return count


def _sample_count(node: ast.expr) -> int:
    if not isinstance(node, ast.Constant) or type(node.value) is not int:
        _refuse("grid_not_representable")
    return _checked_sample_count(node.value)


def _binary_operator(node: ast.operator, invalid: OracleRefusalCode) -> BinaryOperator:
    if isinstance(node, ast.Add):
        return "add"
    if isinstance(node, ast.Sub):
        return "sub"
    if isinstance(node, ast.Mult):
        return "mul"
    if isinstance(node, ast.Div):
        return "div"
    if isinstance(node, ast.Pow):
        return "pow"
    _refuse(invalid)


def _grid(
    node: ast.expr,
    program: _Program,
    used: set[int],
    *,
    invalid: OracleRefusalCode,
    active: frozenset[str] = frozenset(),
) -> Grid:
    if isinstance(node, ast.Name):
        binding = program.bindings.get(node.id)
        if binding is None or node.id in active:
            _refuse(invalid)
        used.add(binding.statement_index)
        return _grid(
            binding.value,
            program,
            used,
            invalid=invalid,
            active=active | {node.id},
        )
    if not isinstance(node, ast.Call) or _target(node) not in _GRID_TARGETS:
        _refuse(invalid)
    target = _target(node)
    if target == "np.linspace":
        return _linspace(node, program, used)
    if target == "np.arange":
        return _arange(node, program, used)
    _refuse(invalid)


def _linspace(call: ast.Call, program: _Program, used: set[int]) -> Grid:
    if len(call.args) not in {2, 3} or len(call.keywords) > 1:
        _refuse("grid_not_representable")
    keyword_num = call.keywords[0].value if call.keywords else None
    if len(call.args) == 3 and keyword_num is not None:
        _refuse("grid_not_representable")
    count_node = call.args[2] if len(call.args) == 3 else keyword_num
    count = 50 if count_node is None else _sample_count(count_node)
    return Grid(
        start=_scalar(call.args[0], program, used).value,
        stop=_scalar(call.args[1], program, used).value,
        count=count,
    )


def _rational(node: ast.expr, program: _Program, used: set[int]) -> Fraction:
    projected = _scalar(node, program, used).value
    if isinstance(projected, Number):
        return projected.value
    if isinstance(projected, Unary) and isinstance(projected.operand, Number):
        return -projected.operand.value
    _refuse("grid_not_representable")


def _arange(call: ast.Call, program: _Program, used: set[int]) -> Grid:
    if not 1 <= len(call.args) <= 3 or call.keywords:
        _refuse("grid_not_representable")
    bounds = [_rational(arg, program, used) for arg in call.args]
    start, excluded_stop = (Fraction(0), bounds[0]) if len(bounds) == 1 else (bounds[0], bounds[1])
    step = bounds[2] if len(bounds) == 3 else Fraction(1)
    if any(value.denominator != 1 for value in (start, excluded_stop, step)) or any(
        abs(value.numerator) > _EXACT_GRID_INTEGER for value in (start, excluded_stop, step)
    ):
        _refuse("grid_not_representable")
    if step == 0:
        _refuse("grid_not_representable")
    span = (excluded_stop - start) / step
    if span <= 0:
        _refuse("grid_not_representable")
    count = _checked_sample_count(math.ceil(span))
    return Grid(
        start=Number(start),
        stop=Number(start + (count - 1) * step),
        count=count,
    )


def _matching_grid(
    node: ast.expr, selected: Grid, program: _Program, used: set[int]
) -> bool | None:
    probe_used: set[int] = set()
    try:
        candidate = _grid(node, program, probe_used, invalid="y_not_over_grid")
    except OracleProjectionError:
        return None
    if candidate != selected:
        return False
    used.update(probe_used)
    return True


def _literal(node: ast.Constant, invalid: OracleRefusalCode) -> Number:
    value = node.value
    if type(value) is int:
        return Number(Fraction(value))
    if type(value) is float and math.isfinite(value):
        return Number(Fraction(value))
    _refuse(invalid)


def _expression(  # noqa: PLR0911, PLR0912, PLR0913 — closed AST expression dispatch
    node: ast.expr,
    program: _Program,
    used: set[int],
    *,
    selected: Grid | None,
    invalid: OracleRefusalCode,
    active: frozenset[str] = frozenset(),
) -> _ProjectedExpression:
    if selected is not None:
        match = _matching_grid(node, selected, program, used)
        if match is True:
            return _ProjectedExpression(Variable(), over_grid=True)
        if match is False:
            _refuse(invalid)
    if isinstance(node, ast.Constant):
        return _ProjectedExpression(_literal(node, invalid), over_grid=False)
    if isinstance(node, ast.Name):
        binding = program.bindings.get(node.id)
        if binding is None or node.id in active:
            _refuse(invalid)
        used.add(binding.statement_index)
        return _expression(
            binding.value,
            program,
            used,
            selected=selected,
            invalid=invalid,
            active=active | {node.id},
        )
    if isinstance(node, ast.Attribute):
        if not isinstance(node.value, ast.Name) or node.value.id != "np":
            _refuse(invalid)
        if node.attr == "pi":
            return _ProjectedExpression(Constant("pi"), over_grid=False)
        if node.attr == "e":
            return _ProjectedExpression(Constant("e"), over_grid=False)
        _refuse(invalid)
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ast.USub):
            _refuse(invalid)
        operand = _expression(
            node.operand, program, used, selected=selected, invalid=invalid, active=active
        )
        return _ProjectedExpression(Unary(operand.value), operand.over_grid)
    if isinstance(node, ast.BinOp):
        left = _expression(
            node.left, program, used, selected=selected, invalid=invalid, active=active
        )
        right = _expression(
            node.right, program, used, selected=selected, invalid=invalid, active=active
        )
        return _ProjectedExpression(
            Binary(_binary_operator(node.op, invalid), left.value, right.value),
            left.over_grid or right.over_grid,
        )
    if isinstance(node, ast.Call):
        function = _MATH_FUNCTIONS.get(_target(node) or "")
        if function is None or len(node.args) != 1 or node.keywords:
            _refuse(invalid)
        argument = _expression(
            node.args[0], program, used, selected=selected, invalid=invalid, active=active
        )
        return _ProjectedExpression(Call(function, argument.value), argument.over_grid)
    _refuse(invalid)


def _scalar(node: ast.expr, program: _Program, used: set[int]) -> _ProjectedExpression:
    result = _expression(
        node,
        program,
        used,
        selected=None,
        invalid="grid_not_representable",
    )
    if result.over_grid:
        _refuse("grid_not_representable")
    return result


def _formula_mark(statement: _CallStatement) -> Mark:
    if statement.target == "plt.bar":
        _refuse("mark_not_valid_for_arm")
    if statement.target == "plt.plot":
        return "line"
    if statement.target == "plt.scatter":
        return "scatter"
    _refuse("statement_not_projected")


def _mark(tree: ast.Module, program: _Program) -> tuple[_CallStatement, Mark]:
    marks = _effect_calls(tree, _MARK_TARGETS)
    if not marks:
        _refuse("no_mark")
    statements: list[tuple[_CallStatement, Mark]] = []
    for call in marks:
        statement = _top_level_call(program, call)
        if statement is None:
            _refuse("statement_not_projected")
        statements.append((statement, _formula_mark(statement)))
    if len(statements) != 1:
        _refuse("multiple_marks")
    return statements[0]


def _terminal(tree: ast.Module, program: _Program) -> _CallStatement:
    terminals = _effect_calls(tree, frozenset({"plt.show"}))
    if not terminals:
        _refuse("no_terminal")
    statements = [_top_level_call(program, call) for call in terminals]
    if any(statement is None for statement in statements):
        _refuse("statement_not_projected")
    top_level = cast("list[_CallStatement]", statements)
    if len(top_level) != 1 or top_level[0].statement_index != len(tree.body) - 1:
        _refuse("statement_after_terminal")
    statement = top_level[0]
    if statement.call.args or statement.call.keywords:
        _refuse("statement_not_projected")
    return statement


def _string_literal(node: ast.expr) -> str:
    if not isinstance(node, ast.Constant) or type(node.value) is not str:
        _refuse("label_not_literal")
    return node.value


def _mark_label(call: ast.Call) -> str | None:
    if not call.keywords:
        return None
    keyword = call.keywords[0]
    if keyword.arg != "label":
        _refuse("statement_not_projected")
    return _string_literal(keyword.value)


def _labels(tree: ast.Module, program: _Program, used: set[int], series: str | None) -> Labels:
    values: dict[str, str | bool | None] = {
        "title": None,
        "xlabel": None,
        "ylabel": None,
        "legend": False,
        "grid": False,
    }
    seen: set[str] = set()
    for call in _effect_calls(tree, frozenset(_DECOR_TARGETS)):
        statement = _top_level_call(program, call)
        target = _target(call)
        if statement is None or target is None or target in seen:
            _refuse("statement_not_projected")
        seen.add(target)
        used.add(statement.statement_index)
        if target in _LABEL_TARGETS:
            if len(call.args) != 1 or call.keywords:
                _refuse("label_not_literal")
            values[target.removeprefix("plt.")] = _string_literal(call.args[0])
        elif target == "plt.legend":
            if call.args or call.keywords:
                _refuse("statement_not_projected")
            values["legend"] = True
        elif target == "plt.grid":
            if call.keywords or len(call.args) > 1:
                _refuse("statement_not_projected")
            if not call.args:
                values["grid"] = True
            elif not isinstance(call.args[0], ast.Constant) or type(call.args[0].value) is not bool:
                _refuse("statement_not_projected")
            else:
                values["grid"] = call.args[0].value
        else:
            _refuse("statement_not_projected")
    return Labels(
        title=cast("str | None", values["title"]),
        xlabel=cast("str | None", values["xlabel"]),
        ylabel=cast("str | None", values["ylabel"]),
        series=series,
        legend=cast("bool", values["legend"]),
        grid=cast("bool", values["grid"]),
    )


def _assemble_mark(
    mark_statement: _CallStatement, mark: Mark, program: _Program, used: set[int]
) -> tuple[Grid, Expression, Mark, str | None]:
    call = mark_statement.call
    if len(call.args) != 2 or len(call.keywords) > 1:
        _refuse("statement_not_projected")
    used.add(mark_statement.statement_index)
    grid = _grid(call.args[0], program, used, invalid="x_not_a_grid")
    projected = _expression(
        call.args[1],
        program,
        used,
        selected=grid,
        invalid="y_not_over_grid",
    )
    if not projected.over_grid:
        _refuse("y_not_over_grid")
    return grid, projected.value, mark, _mark_label(call)


def project(tree: ast.Module) -> OraclePlotSpec:
    """Project one admitted formula program without evaluating or retaining AST nodes."""
    program = _classify(tree)
    mark_statement, mark = _mark(tree, program)
    terminal_statement = _terminal(tree, program)
    used = set(program.structural_statements)
    used.add(terminal_statement.statement_index)
    grid, expression, mark, series = _assemble_mark(mark_statement, mark, program, used)
    labels = _labels(tree, program, used, series)
    if used != set(range(len(tree.body))):
        _refuse("statement_not_projected")
    return FormulaPlot(grid=grid, expression=expression, mark=mark, labels=labels)


_CANONICAL_NODE_NAMES = {
    "Number": "Num",
    "Num": "Num",
    "Variable": "Var",
    "Var": "Var",
    "Constant": "Const",
    "Const": "Const",
    "Unary": "Neg",
    "Neg": "Neg",
    "Call": "Fn",
    "Fn": "Fn",
    "Binary": "Bin",
    "Bin": "Bin",
    "Grid": "Grid",
    "Labels": "Labels",
    "FormulaPlot": "FormulaPlot",
}
_CANONICAL_FIELD_NAMES = {
    "Number": {"value": "value"},
    "Num": {"value": "value"},
    "Variable": {},
    "Var": {},
    "Constant": {"name": "name"},
    "Const": {"name": "name"},
    "Unary": {"operand": "operand"},
    "Neg": {"operand": "operand"},
    "Call": {"function": "name", "argument": "arg"},
    "Fn": {"name": "name", "arg": "arg"},
    "Binary": {"op": "op", "left": "left", "right": "right"},
    "Bin": {"op": "op", "left": "left", "right": "right"},
    "Grid": {"start": "start", "stop": "stop", "count": "samples", "samples": "samples"},
    "Labels": {
        "title": "title",
        "xlabel": "xlabel",
        "ylabel": "ylabel",
        "series": "series",
        "legend": "legend",
        "grid": "grid",
    },
    "FormulaPlot": {
        "mark": "mark",
        "grid": "grid",
        "expression": "y",
        "y": "y",
        "labels": "labels",
    },
}
_CANONICAL_FIELD_ORDER = {
    "Num": ("value",),
    "Var": (),
    "Const": ("name",),
    "Neg": ("operand",),
    "Fn": ("name", "arg"),
    "Bin": ("op", "left", "right"),
    "Grid": ("start", "stop", "samples"),
    "Labels": ("title", "xlabel", "ylabel", "series", "legend", "grid"),
    "FormulaPlot": ("mark", "grid", "y", "labels"),
}


def normalize(value: object) -> object:
    """Translate both independent representations to one closed canonical tuple."""
    if is_dataclass(value) and not isinstance(value, type):
        source_name = type(value).__name__
        try:
            canonical_name = _CANONICAL_NODE_NAMES[source_name]
            field_names = _CANONICAL_FIELD_NAMES[source_name]
        except KeyError as error:
            message = f"unmapped projection node: {source_name}"
            raise TypeError(message) from error
        source_fields = fields(value)
        unknown = {field.name for field in source_fields} - field_names.keys()
        if unknown:
            message = f"unmapped {source_name} fields: {sorted(unknown)!r}"
            raise TypeError(message)
        translated = {
            field_names[field.name]: normalize(getattr(value, field.name))
            for field in source_fields
        }
        order = _CANONICAL_FIELD_ORDER[canonical_name]
        if len(translated) != len(source_fields) or set(translated) != set(order):
            message = f"incomplete {source_name} translation: {sorted(translated)!r}"
            raise TypeError(message)
        return canonical_name, tuple((name, translated[name]) for name in order)
    if isinstance(value, Enum):
        return normalize(value.value)
    if isinstance(value, tuple):
        return tuple(normalize(item) for item in value)
    if isinstance(value, list):
        return tuple(normalize(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((str(key), normalize(item)) for key, item in value.items()))
    return value
