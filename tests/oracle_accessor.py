# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Independent M13.8 oracle for aggregate accessor and reset-frame spellings.

The oracle parses source directly into its own small value model. Production admission and
projection remain outside this module; the differential owns the only comparison between them.
"""

import ast
from dataclasses import dataclass
from typing import Final, Literal, NoReturn, cast

type OracleRefusalCode = Literal[
    "no_mark",
    "multiple_marks",
    "mark_arity_not_projected",
    "call_target_not_admitted",
    "keyword_not_admitted",
    "label_not_literal",
    "name_not_bound",
    "name_rebound",
    "column_not_from_source",
    "aggregation_not_projected",
]
type OracleMark = Literal["bar", "barh"]
type OracleReduction = Literal["sum", "mean", "min", "max"]

ACCESSOR_KIND_MAP: Final[dict[str, OracleMark]] = {"bar": "bar", "barh": "barh"}
ACCESSOR_KEYWORDS: Final[frozenset[str]] = frozenset({"kind", "color"})
RESET_UNWRAPS: Final[frozenset[str]] = frozenset({"reset_index"})
_REDUCTIONS: Final[frozenset[str]] = frozenset({"sum", "mean", "min", "max"})


@dataclass(frozen=True, slots=True)
class OracleProjection:
    """The meaning shared by both source spellings in this unit."""

    mark: OracleMark
    path: str
    key: str
    value: str
    reduction: OracleReduction


@dataclass(frozen=True, slots=True)
class OracleRefusal:
    """One contract-owned refusal, with no submitted text retained."""

    code: OracleRefusalCode


type OracleDecision = OracleProjection | OracleRefusal


@dataclass(frozen=True, slots=True)
class _Source:
    frame: str
    path: str


@dataclass(frozen=True, slots=True)
class _Aggregate:
    binding: str
    frame: str
    key: str
    value: str
    reduction: OracleReduction
    reset_frame: bool


class _OracleRefusalError(Exception):
    def __init__(self, code: OracleRefusalCode) -> None:
        super().__init__(code)
        self.code = code


def _refuse(code: OracleRefusalCode) -> NoReturn:
    raise _OracleRefusalError(code)


def _target(call: ast.Call) -> str | None:
    function = call.func
    if not isinstance(function, ast.Attribute) or not isinstance(function.value, ast.Name):
        return None
    return f"{function.value.id}.{function.attr}"


def _bindings(tree: ast.Module) -> dict[str, ast.expr]:
    bindings: dict[str, ast.expr] = {}
    seen: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                if alias.asname is not None:
                    if alias.asname in seen:
                        _refuse("name_rebound")
                    seen.add(alias.asname)
            continue
        if not isinstance(statement, ast.Assign):
            continue
        if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
            continue
        name = statement.targets[0].id
        if name in seen:
            _refuse("name_rebound")
        seen.add(name)
        bindings[name] = statement.value
    return bindings


def _string(node: ast.expr, code: OracleRefusalCode) -> str:
    if not isinstance(node, ast.Constant) or type(node.value) is not str:
        _refuse(code)
    return node.value


def _source(bindings: dict[str, ast.expr]) -> _Source:
    candidates: list[_Source] = []
    for frame, node in bindings.items():
        if not isinstance(node, ast.Call) or _target(node) != "pd.read_csv":
            continue
        if len(node.args) != 1 or node.keywords:
            _refuse("column_not_from_source")
        candidates.append(_Source(frame, _string(node.args[0], "column_not_from_source")))
    if len(candidates) != 1:
        _refuse("column_not_from_source")
    return candidates[0]


def _direct_aggregate(binding: str, node: ast.expr, source: _Source) -> _Aggregate | None:
    if (
        not isinstance(node, ast.Call)
        or node.args
        or node.keywords
        or not isinstance(node.func, ast.Attribute)
        or node.func.attr not in _REDUCTIONS
        or not isinstance(node.func.value, ast.Subscript)
    ):
        return None
    selection = node.func.value
    group_call = selection.value
    if (
        not isinstance(group_call, ast.Call)
        or len(group_call.args) != 1
        or group_call.keywords
        or not isinstance(group_call.func, ast.Attribute)
        or group_call.func.attr != "groupby"
        or not isinstance(group_call.func.value, ast.Name)
        or group_call.func.value.id != source.frame
    ):
        return None
    key = _string(group_call.args[0], "aggregation_not_projected")
    value = _string(selection.slice, "aggregation_not_projected")
    return _Aggregate(
        binding=binding,
        frame=source.frame,
        key=key,
        value=value,
        reduction=cast("OracleReduction", node.func.attr),
        reset_frame=False,
    )


def _bound_aggregate(
    name: str, bindings: dict[str, ast.expr], source: _Source
) -> _Aggregate | None:
    node = bindings.get(name)
    if node is None:
        return None
    direct = _direct_aggregate(name, node, source)
    if direct is not None:
        return direct
    if (
        not isinstance(node, ast.Call)
        or node.args
        or node.keywords
        or not isinstance(node.func, ast.Attribute)
    ):
        return None
    inner = _direct_aggregate(name, node.func.value, source)
    if inner is None:
        return None
    if node.func.attr not in RESET_UNWRAPS:
        _refuse("aggregation_not_projected")
    return _Aggregate(
        binding=inner.binding,
        frame=inner.frame,
        key=inner.key,
        value=inner.value,
        reduction=inner.reduction,
        reset_frame=True,
    )


def _accessor_projection(
    call: ast.Call, bindings: dict[str, ast.expr], source: _Source
) -> OracleProjection:
    function = call.func
    if not isinstance(function, ast.Attribute):
        _refuse("call_target_not_admitted")
    receiver: str | None = None
    if isinstance(function.value, ast.Name):
        receiver = function.value.id
        if receiver in {"plt", "np", "pd"}:
            _refuse("call_target_not_admitted")
        if receiver not in bindings:
            _refuse("name_not_bound")
    elif not isinstance(function.value, ast.Subscript):
        _refuse("call_target_not_admitted")
    if call.args or any(keyword.arg not in ACCESSOR_KEYWORDS for keyword in call.keywords):
        _refuse("keyword_not_admitted")
    keywords = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg is not None}
    kind_node = keywords.get("kind")
    if (
        kind_node is None
        or not isinstance(kind_node, ast.Constant)
        or type(kind_node.value) is not str
    ):
        _refuse("call_target_not_admitted")
    mark = ACCESSOR_KIND_MAP.get(kind_node.value)
    if mark is None:
        _refuse("call_target_not_admitted")
    color = keywords.get("color")
    if color is not None:
        _string(color, "label_not_literal")
    aggregate = None if receiver is None else _bound_aggregate(receiver, bindings, source)
    if aggregate is None or aggregate.reset_frame:
        _refuse("column_not_from_source")
    return OracleProjection(
        mark=mark,
        path=source.path,
        key=aggregate.key,
        value=aggregate.value,
        reduction=aggregate.reduction,
    )


def _aggregate_name(node: ast.expr, *, role: Literal["x", "y"]) -> str | None:
    if role == "x" and isinstance(node, ast.Attribute) and node.attr == "index":
        return node.value.id if isinstance(node.value, ast.Name) else None
    if role == "y" and isinstance(node, ast.Name):
        return node.id
    if (
        role == "y"
        and isinstance(node, ast.Attribute)
        and node.attr == "values"
        and isinstance(node.value, ast.Name)
    ):
        return node.value.id
    return None


def _subscript_channel(node: ast.expr) -> tuple[str, str] | None:
    if (
        not isinstance(node, ast.Subscript)
        or not isinstance(node.value, ast.Name)
        or not isinstance(node.slice, ast.Constant)
        or type(node.slice.value) is not str
    ):
        return None
    return node.value.id, node.slice.value


def _standard_projection(
    call: ast.Call, bindings: dict[str, ast.expr], source: _Source, mark: OracleMark
) -> OracleProjection:
    if len(call.args) != 2:
        _refuse("mark_arity_not_projected")
    x_name = _aggregate_name(call.args[0], role="x")
    y_name = _aggregate_name(call.args[1], role="y")
    aggregate: _Aggregate | None = None
    if x_name is not None and x_name == y_name:
        candidate = _bound_aggregate(x_name, bindings, source)
        if candidate is not None and not candidate.reset_frame:
            aggregate = candidate
    else:
        x_channel = _subscript_channel(call.args[0])
        y_channel = _subscript_channel(call.args[1])
        if x_channel is not None and y_channel is not None and x_channel[0] == y_channel[0]:
            candidate = _bound_aggregate(x_channel[0], bindings, source)
            if (
                candidate is not None
                and candidate.reset_frame
                and x_channel[1] == candidate.key
                and y_channel[1] == candidate.value
            ):
                aggregate = candidate
    if aggregate is None:
        _refuse("column_not_from_source")
    return OracleProjection(
        mark=mark,
        path=source.path,
        key=aggregate.key,
        value=aggregate.value,
        reduction=aggregate.reduction,
    )


def _decide(source_text: str) -> OracleProjection:
    tree = ast.parse(source_text)
    bindings = _bindings(tree)
    dataset = _source(bindings)
    marks: list[OracleProjection] = []
    for statement in tree.body:
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            continue
        call = statement.value
        target = _target(call)
        if target in {"plt.bar", "plt.barh"}:
            marks.append(
                _standard_projection(
                    call,
                    bindings,
                    dataset,
                    cast("OracleMark", target.removeprefix("plt.")),
                )
            )
            continue
        if isinstance(call.func, ast.Attribute) and call.func.attr == "plot":
            marks.append(_accessor_projection(call, bindings, dataset))
            continue
        if (
            target is not None
            and target != "plt.show"
            and target.split(".", maxsplit=1)[0] in {"plt", "np", "pd"}
        ):
            _refuse("call_target_not_admitted")
    if not marks:
        _refuse("no_mark")
    if len(marks) != 1:
        _refuse("multiple_marks")
    return marks[0]


def decide(source_text: str) -> OracleDecision:
    """Decide one source without invoking production admission or projection."""
    try:
        return _decide(source_text)
    except _OracleRefusalError as error:
        return OracleRefusal(error.code)
