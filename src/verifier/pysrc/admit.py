# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Positive AST allowlist for `pysrc-0.1`. This IS the pass/fail boundary.

Admission is a closed allowlist over idiom CLASSES, never a denylist of bad constructs: a node type,
call target, attribute chain, keyword or literal kind that is not named here is refused, so a
construct nobody anticipated fails closed. Dispatch is exhaustive by node type with refusal as the
tail -- a `.get(kind, default_admit)` over a variant space is this repo's most-repeated defect
class, and here it would silently widen the boundary.

`plt.subplots` and every multi-panel form are absent BY CONSTRUCTION rather than by a named ban: the
projection targets exactly one chart, so a program producing more than one Axes has nothing to
project onto, and `call_target_not_admitted` is the honest reason.

Two deliberate non-admissions worth naming, because both are calibration levers rather than safety
properties, and M13.6 measurement is what should move them:

- a module docstring (a bare `str` expression statement) refuses, since it plots nothing;
- an empty program admits, since admission answers "may these bytes run", not "do they draw" --
  projection is what demands a chart.

This module parses; it never evaluates. No `eval`, `exec`, `compile` or `getattr` appears, and a
committed search test pins that.
"""

import ast
from dataclasses import dataclass, field
from typing import NoReturn

from verifier.pysrc.errors import PysrcRefusalError, RefusalCode

# Module -> required alias. The alias is fixed, not merely required: admitting an arbitrary alias
# would make every downstream target string depend on model-chosen text.
ADMITTED_IMPORTS: dict[str, str] = {"matplotlib.pyplot": "plt", "numpy": "np", "pandas": "pd"}

# Closed call-target set, spelled `<alias>.<attr>`, grouped by the idiom class each serves.
_GRID_TARGETS = frozenset({"np.linspace", "np.arange"})
_MATH_TARGETS = frozenset({"np.sin", "np.cos", "np.tan", "np.exp", "np.log", "np.sqrt", "np.abs"})
_MARK_TARGETS = frozenset({"plt.plot", "plt.scatter", "plt.bar"})
_DECOR_TARGETS = frozenset({"plt.title", "plt.xlabel", "plt.ylabel", "plt.legend", "plt.grid"})
_TERMINAL_TARGETS = frozenset({"plt.show"})
# Exactly one reader. `read_table`, `read_excel` and friends stay out: each would need its own
# projection rule for separators, sheets and header handling before the verifier could state what
# the program reads.
_SOURCE_TARGETS = frozenset({"pd.read_csv"})
ADMITTED_CALL_TARGETS = (
    _GRID_TARGETS
    | _MATH_TARGETS
    | _MARK_TARGETS
    | _DECOR_TARGETS
    | _TERMINAL_TARGETS
    | _SOURCE_TARGETS
)

# Keywords are closed PER TARGET: a keyword admitted on one call is not thereby admitted on
# another, because each one has to be projectable where it appears.
ADMITTED_KEYWORDS: dict[str, frozenset[str]] = {
    "np.linspace": frozenset({"num"}),
    "np.arange": frozenset(),
    "np.sin": frozenset(),
    "np.cos": frozenset(),
    "np.tan": frozenset(),
    "np.exp": frozenset(),
    "np.log": frozenset(),
    "np.sqrt": frozenset(),
    "np.abs": frozenset(),
    "plt.plot": frozenset({"label"}),
    "plt.scatter": frozenset({"label"}),
    "plt.bar": frozenset({"label"}),
    "plt.title": frozenset(),
    "plt.xlabel": frozenset(),
    "plt.ylabel": frozenset(),
    "plt.legend": frozenset(),
    "plt.grid": frozenset(),
    "plt.show": frozenset(),
    # No `sep`, `header`, `usecols`, `dtype`: each changes what the file MEANS, so admitting one
    # without a projection rule would let the program restate the user's artifact unchecked.
    "pd.read_csv": frozenset(),
}

# Attribute reads that are values rather than call targets.
ADMITTED_CONSTANT_ATTRS = frozenset({"np.pi", "np.e"})

_ADMITTED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
_ADMITTED_UNARYOPS = (ast.USub,)

# `bool` is admitted because `plt.grid(True)` is an ordinary matplotlib idiom; which argument slots
# accept which literal kind is projection's question, not admission's.
#
# The membership test is EXACT type, not `isinstance`, so that this tuple is the whole boundary
# rather than a subclass-closed one: `bool` subclasses `int`, so under `isinstance` removing `bool`
# here would not actually refuse `True`. The two spellings agree on every input today and diverge
# the moment the set is narrowed, which is exactly when the difference has to hold.
_ADMITTED_LITERAL_TYPES = (int, float, str, bool)


@dataclass(slots=True)
class _Scope:
    """Names bound so far. Order matters: a name is admitted only after its binding statement."""

    bound: set[str] = field(default_factory=set)


def _refuse(code: RefusalCode, cause: BaseException | None = None) -> NoReturn:
    raise PysrcRefusalError(code) from cause


def _dotted(node: ast.Attribute) -> tuple[str, str]:
    """Return `(alias, "alias.attr")` for a depth-1 chain, refusing anything deeper.

    Depth is bounded here rather than at the leaf: `np.random.rand` must refuse because its chain is
    two deep, not because `rand` happens to be unlisted -- otherwise adding one name to the
    allowlist could accidentally admit a whole submodule.
    """
    value = node.value
    if not isinstance(value, ast.Name):
        _refuse("attribute_not_admitted")
    if node.attr.startswith("_"):
        _refuse("attribute_not_admitted")
    return value.id, f"{value.id}.{node.attr}"


def _admit_constant_attr(node: ast.Attribute, scope: _Scope) -> None:
    """Admit a bare attribute READ, as opposed to a call target."""
    alias, dotted = _dotted(node)
    if dotted not in ADMITTED_CONSTANT_ATTRS:
        _refuse("attribute_not_admitted")
    if alias not in scope.bound:
        _refuse("name_not_bound")


def _admit_call(node: ast.Call, scope: _Scope) -> None:
    func = node.func
    if not isinstance(func, ast.Attribute):
        _refuse("call_target_not_admitted")
    alias, target = _dotted(func)
    if target not in ADMITTED_CALL_TARGETS:
        _refuse("call_target_not_admitted")
    if alias not in scope.bound:
        _refuse("name_not_bound")
    admitted = ADMITTED_KEYWORDS[target]
    for keyword in node.keywords:
        # `arg is None` is `**kwargs`, whose keyword set is not statically known at all.
        if keyword.arg is None or keyword.arg not in admitted:
            _refuse("keyword_not_admitted")
        _admit_expr(keyword.value, scope)
    for arg in node.args:
        # `*args` arrives as `ast.Starred`, which the expression tail refuses.
        _admit_expr(arg, scope)


def _admit_expr(node: ast.expr, scope: _Scope) -> None:
    if isinstance(node, ast.Constant):
        if type(node.value) not in _ADMITTED_LITERAL_TYPES:
            _refuse("literal_not_admitted")
    elif isinstance(node, ast.Name):
        if node.id not in scope.bound:
            _refuse("name_not_bound")
    elif isinstance(node, ast.Attribute):
        _admit_constant_attr(node, scope)
    elif isinstance(node, ast.Call):
        _admit_call(node, scope)
    elif isinstance(node, ast.BinOp):
        if not isinstance(node.op, _ADMITTED_BINOPS):
            _refuse("operator_not_admitted")
        _admit_expr(node.left, scope)
        _admit_expr(node.right, scope)
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ADMITTED_UNARYOPS):
            _refuse("operator_not_admitted")
        _admit_expr(node.operand, scope)
    elif isinstance(node, ast.Subscript):
        _admit_column(node, scope)
    else:
        # The closed tail: comprehensions, lambdas, f-strings, list/dict/set/tuple displays,
        # starred args, walrus, comparisons, boolean and conditional expressions.
        _refuse("expression_not_admitted")


def _admit_column(node: ast.Subscript, scope: _Scope) -> None:
    """`<bound name>["<literal>"]` and nothing else.

    Narrower than it looks by accident: a slice, a tuple index, `df[cols]` and `df.loc[...]` all
    land on a refusal, because each selects something the projection has no rule for. `.loc`/`.iloc`
    additionally fail at the attribute check, which is the near-miss this shape has to survive.
    """
    if not isinstance(node.value, ast.Name):
        _refuse("expression_not_admitted")
    if node.value.id not in scope.bound:
        _refuse("name_not_bound")
    index = node.slice
    if not isinstance(index, ast.Constant) or type(index.value) is not str:
        _refuse("column_not_literal")


def _admit_import(node: ast.Import, scope: _Scope) -> None:
    for alias in node.names:
        required = ADMITTED_IMPORTS.get(alias.name)
        if required is None or alias.asname != required:
            _refuse("import_not_admitted")
        scope.bound.add(required)


def _admit_assign(node: ast.Assign, scope: _Scope) -> None:
    if len(node.targets) != 1:
        _refuse("assign_target_not_admitted")
    target = node.targets[0]
    if not isinstance(target, ast.Name):
        _refuse("assign_target_not_admitted")
    if target.id.startswith("_"):
        _refuse("assign_target_not_admitted")
    # Right-hand side first, then bind: `x = x + 1` must refuse while `x` is still unbound.
    _admit_expr(node.value, scope)
    scope.bound.add(target.id)


def _admit_stmt(node: ast.stmt, scope: _Scope) -> None:
    if isinstance(node, ast.Import):
        _admit_import(node, scope)
    elif isinstance(node, ast.Assign):
        _admit_assign(node, scope)
    elif isinstance(node, ast.Expr):
        # A bare expression statement is admitted only as a call: a lone name, literal or docstring
        # has no plotting effect, and admitting one would carry statements the projection ignores.
        value = node.value
        if not isinstance(value, ast.Call):
            _refuse("statement_not_admitted")
        _admit_call(value, scope)
    else:
        # The closed tail: loops, `def`, `class`, `try`, `with`, `del`, `global`, `nonlocal`,
        # `raise`, `assert`, `async`, `from x import y`, annotated and augmented assignment.
        _refuse("statement_not_admitted")


def parse_admitted(text: str) -> ast.Module:
    """Parse and admit `text`, returning the tree. Raises `PysrcRefusalError` on refusal.

    `text` must be what `prescan` returned: the caps it charges are what bound this parse.
    """
    try:
        tree = ast.parse(text)
    # The pre-scan tokenizes but does not parse, so a tokenizable-yet-unparsable program reaches
    # here and must become a verdict rather than a traceback.
    except SyntaxError as exc:
        _refuse("source_not_parsable", exc)

    scope = _Scope()
    for statement in tree.body:
        _admit_stmt(statement, scope)
    return tree
