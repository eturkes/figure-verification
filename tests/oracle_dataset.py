# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Independent M13.4 dataset-arm AST projection oracle.

The oracle first classifies the arm and whole module, then projects a dataset chart through its own
value model. ``normalize`` is the sole representation translation boundary.
"""

import ast
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import Literal, NoReturn, cast

from oracle_project import FormulaPlot
from oracle_project import OracleProjectionError as FormulaOracleProjectionError
from oracle_project import normalize as normalize_formula
from oracle_project import project as project_formula

type OracleRefusalCode = Literal[
    "arm_ambiguous",
    "no_source",
    "multiple_sources",
    "source_not_literal",
    "column_not_literal",
    "column_not_from_source",
    "no_mark",
    "multiple_marks",
    "mark_arity_not_projected",
    "mark_not_valid_for_arm",
    "x_not_a_grid",
    "y_not_over_grid",
    "grid_not_representable",
    "expression_not_projected",
    "label_not_literal",
    "name_rebound",
    "no_terminal",
    "statement_after_terminal",
    "statement_not_projected",
]
type DatasetMark = Literal["line", "scatter", "bar"]
type _Arm = Literal["formula", "dataset"]

_GRID_TARGETS = frozenset({"np.linspace", "np.arange"})
_SOURCE_TARGET = "pd.read_csv"
_MARK_TARGETS = frozenset({"plt.plot", "plt.scatter", "plt.bar"})
_LABEL_TARGETS = frozenset({"plt.title", "plt.xlabel", "plt.ylabel"})
_DECOR_TARGETS = _LABEL_TARGETS | {"plt.legend", "plt.grid"}


class OracleDatasetProjectionError(Exception):
    """An independently detected dataset or arm-selection refusal."""

    def __init__(self, code: OracleRefusalCode) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CsvFile:
    location: str


@dataclass(frozen=True, slots=True)
class Field:
    column: str


@dataclass(frozen=True, slots=True)
class ChartLabels:
    heading: str | None = None
    horizontal: str | None = None
    vertical: str | None = None
    series_name: str | None = None
    has_legend: bool = False
    has_grid: bool = False


@dataclass(frozen=True, slots=True)
class DatasetChart:
    kind: DatasetMark
    csv: CsvFile
    horizontal: Field
    vertical: Field
    annotations: ChartLabels


type OraclePlotSpec = FormulaPlot | DatasetChart


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
class _Source:
    frame: str
    value: CsvFile


@dataclass(frozen=True, slots=True)
class _ProjectedMark:
    statement: _CallStatement
    kind: DatasetMark
    horizontal: Field
    vertical: Field
    series_name: str | None


def _refuse(code: OracleRefusalCode) -> NoReturn:
    raise OracleDatasetProjectionError(code)


def _target(call: ast.Call) -> str | None:
    func = call.func
    if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
        return None
    return f"{func.value.id}.{func.attr}"


def _effect_calls(tree: ast.Module, targets: frozenset[str]) -> list[ast.Call]:
    return [
        node for node in ast.walk(tree) if isinstance(node, ast.Call) and _target(node) in targets
    ]


def _select_arm(tree: ast.Module) -> _Arm:
    has_dataset = any(
        isinstance(statement, ast.Import)
        and any(alias.name == "pandas" for alias in statement.names)
        for statement in tree.body
    )
    has_formula = bool(_effect_calls(tree, _GRID_TARGETS))
    if has_dataset and has_formula:
        _refuse("arm_ambiguous")
    if has_dataset and not has_formula:
        return "dataset"
    if has_formula and not has_dataset:
        return "formula"
    if not has_dataset and not has_formula:
        return "formula"
    _refuse("arm_ambiguous")


def _classify(tree: ast.Module) -> _Program:
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
            if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                _refuse("statement_not_projected")
            target = statement.targets[0].id
            if target in seen:
                _refuse("name_rebound")
            seen.add(target)
            bindings[target] = _Binding(index, statement.value)
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            calls.append(_CallStatement(index, statement.value, _target(statement.value)))
            continue
        _refuse("statement_not_projected")

    return _Program(bindings, tuple(calls), frozenset(structural))


def _top_level_call(program: _Program, call: ast.Call) -> _CallStatement | None:
    return next((statement for statement in program.calls if statement.call is call), None)


def _source_path(call: ast.Call) -> str:
    if len(call.args) != 1 or call.keywords:
        _refuse("source_not_literal")
    candidate = call.args[0]
    if not isinstance(candidate, ast.Constant) or type(candidate.value) is not str:
        _refuse("source_not_literal")
    return candidate.value


def _source_binding(program: _Program, call: ast.Call) -> tuple[str, _Binding]:
    matches = [
        (name, binding) for name, binding in program.bindings.items() if binding.value is call
    ]
    if len(matches) != 1:
        _refuse("statement_not_projected")
    return matches[0]


def _dataset_source(tree: ast.Module, program: _Program, used: set[int]) -> _Source:
    calls = _effect_calls(tree, frozenset({_SOURCE_TARGET}))
    if not calls:
        _refuse("no_source")
    candidates = [(_source_path(call), _source_binding(program, call)) for call in calls]
    if len(candidates) != 1:
        _refuse("multiple_sources")
    path, (frame, binding) = candidates[0]
    used.add(binding.statement_index)
    return _Source(frame, CsvFile(path))


def _column(
    node: ast.expr,
    source: _Source,
    program: _Program,
    used: set[int],
    *,
    active: frozenset[str] = frozenset(),
) -> Field:
    if isinstance(node, ast.Name):
        binding = program.bindings.get(node.id)
        if binding is None or node.id in active:
            _refuse("column_not_from_source")
        used.add(binding.statement_index)
        return _column(
            binding.value,
            source,
            program,
            used,
            active=active | {node.id},
        )
    if not isinstance(node, ast.Subscript):
        _refuse("column_not_from_source")
    if not isinstance(node.slice, ast.Constant) or type(node.slice.value) is not str:
        _refuse("column_not_literal")
    if not isinstance(node.value, ast.Name) or node.value.id != source.frame:
        _refuse("column_not_from_source")
    return Field(node.slice.value)


def _string_literal(node: ast.expr) -> str:
    if not isinstance(node, ast.Constant) or type(node.value) is not str:
        _refuse("label_not_literal")
    return node.value


def _mark_label(call: ast.Call) -> str | None:
    if not call.keywords:
        return None
    if len(call.keywords) != 1 or call.keywords[0].arg != "label":
        _refuse("statement_not_projected")
    return _string_literal(call.keywords[0].value)


def _dataset_mark(target: str | None) -> DatasetMark:
    if target == "plt.plot":
        return "line"
    if target == "plt.scatter":
        return "scatter"
    if target == "plt.bar":
        return "bar"
    _refuse("statement_not_projected")


def _project_mark(
    call: ast.Call,
    source: _Source,
    program: _Program,
    used: set[int],
) -> _ProjectedMark:
    statement = _top_level_call(program, call)
    if statement is None:
        _refuse("statement_not_projected")
    kind = _dataset_mark(statement.target)
    if len(call.args) != 2:
        _refuse("mark_arity_not_projected")
    local_used: set[int] = {statement.statement_index}
    horizontal = _column(call.args[0], source, program, local_used)
    vertical = _column(call.args[1], source, program, local_used)
    series_name = _mark_label(call)
    used.update(local_used)
    return _ProjectedMark(statement, kind, horizontal, vertical, series_name)


def _mark(
    tree: ast.Module,
    source: _Source,
    program: _Program,
    used: set[int],
) -> _ProjectedMark:
    calls = _effect_calls(tree, _MARK_TARGETS)
    if not calls:
        _refuse("no_mark")
    projected = [_project_mark(call, source, program, used) for call in calls]
    if len(projected) != 1:
        _refuse("multiple_marks")
    return projected[0]


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


def _labels(
    tree: ast.Module,
    program: _Program,
    used: set[int],
    series_name: str | None,
) -> ChartLabels:
    values: dict[str, str | bool | None] = {
        "heading": None,
        "horizontal": None,
        "vertical": None,
        "has_legend": False,
        "has_grid": False,
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
            key = {
                "plt.title": "heading",
                "plt.xlabel": "horizontal",
                "plt.ylabel": "vertical",
            }[target]
            values[key] = _string_literal(call.args[0])
        elif target == "plt.legend":
            if call.args or call.keywords:
                _refuse("statement_not_projected")
            values["has_legend"] = True
        elif target == "plt.grid":
            if call.keywords or len(call.args) > 1:
                _refuse("statement_not_projected")
            if not call.args:
                values["has_grid"] = True
            elif not isinstance(call.args[0], ast.Constant) or type(call.args[0].value) is not bool:
                _refuse("statement_not_projected")
            else:
                values["has_grid"] = call.args[0].value
        else:
            _refuse("statement_not_projected")
    return ChartLabels(
        heading=cast("str | None", values["heading"]),
        horizontal=cast("str | None", values["horizontal"]),
        vertical=cast("str | None", values["vertical"]),
        series_name=series_name,
        has_legend=cast("bool", values["has_legend"]),
        has_grid=cast("bool", values["has_grid"]),
    )


def _project_dataset(tree: ast.Module) -> DatasetChart:
    program = _classify(tree)
    if not _effect_calls(tree, _MARK_TARGETS):
        _refuse("no_mark")
    used = set(program.structural_statements)
    source = _dataset_source(tree, program, used)
    mark = _mark(tree, source, program, used)
    terminal = _terminal(tree, program)
    used.add(terminal.statement_index)
    labels = _labels(tree, program, used, mark.series_name)
    if used != set(range(len(tree.body))):
        _refuse("statement_not_projected")
    return DatasetChart(
        kind=mark.kind,
        csv=source.value,
        horizontal=mark.horizontal,
        vertical=mark.vertical,
        annotations=labels,
    )


def project(tree: ast.Module) -> OraclePlotSpec:
    """Project one admitted two-arm program without evaluation or retained AST nodes."""
    arm = _select_arm(tree)
    if arm == "dataset":
        return _project_dataset(tree)
    if arm == "formula":
        try:
            return project_formula(tree)
        except FormulaOracleProjectionError as error:
            _refuse(cast("OracleRefusalCode", str(error.code)))
    _refuse("arm_ambiguous")


_DATASET_NODE_NAMES = {
    "CsvFile": "DatasetRef",
    "DatasetRef": "DatasetRef",
    "Field": "Column",
    "Column": "Column",
    "ChartLabels": "Labels",
    "DatasetChart": "DatasetPlot",
    "DatasetPlot": "DatasetPlot",
}
_DATASET_FIELD_NAMES = {
    "CsvFile": {"location": "path"},
    "DatasetRef": {"path": "path"},
    "Field": {"column": "name"},
    "Column": {"name": "name"},
    "ChartLabels": {
        "heading": "title",
        "horizontal": "xlabel",
        "vertical": "ylabel",
        "series_name": "series",
        "has_legend": "legend",
        "has_grid": "grid",
    },
    "DatasetChart": {
        "kind": "mark",
        "csv": "source",
        "horizontal": "x",
        "vertical": "y",
        "annotations": "labels",
    },
    "DatasetPlot": {
        "mark": "mark",
        "source": "source",
        "x": "x",
        "y": "y",
        "labels": "labels",
    },
}
_DATASET_FIELD_ORDER = {
    "DatasetRef": ("path",),
    "Column": ("name",),
    "Labels": ("title", "xlabel", "ylabel", "series", "legend", "grid"),
    "DatasetPlot": ("mark", "source", "x", "y", "labels"),
}


def normalize(value: object) -> object:
    """Translate both dataset representations through one closed, explicit map."""
    if is_dataclass(value) and not isinstance(value, type):
        source_name = type(value).__name__
        if source_name not in _DATASET_NODE_NAMES:
            return normalize_formula(value)
        canonical_name = _DATASET_NODE_NAMES[source_name]
        field_names = _DATASET_FIELD_NAMES[source_name]
        source_fields = fields(value)
        unknown = {field.name for field in source_fields} - field_names.keys()
        if unknown:
            message = f"unmapped {source_name} fields: {sorted(unknown)!r}"
            raise TypeError(message)
        translated = {
            field_names[field.name]: normalize(getattr(value, field.name))
            for field in source_fields
        }
        order = _DATASET_FIELD_ORDER[canonical_name]
        if len(translated) != len(source_fields) or set(translated) != set(order):
            message = f"incomplete {source_name} translation: {sorted(translated)!r}"
            raise TypeError(message)
        return canonical_name, tuple((name, translated[name]) for name in order)
    if isinstance(value, Enum):
        return normalize(value.value)
    if isinstance(value, (tuple, list)):
        return tuple(normalize(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((str(key), normalize(item)) for key, item in value.items()))
    return value
