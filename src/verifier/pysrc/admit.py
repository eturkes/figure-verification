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
from typing import NoReturn, cast

from verifier.pysrc.errors import PysrcRefusalError, RefusalCode

# Module -> required alias. The alias is fixed, not merely required: admitting an arbitrary alias
# would make every downstream target string depend on model-chosen text.
ADMITTED_IMPORTS: dict[str, str] = {"matplotlib.pyplot": "plt", "numpy": "np", "pandas": "pd"}

# Closed call-target set, spelled `<alias>.<attr>`, grouped by the idiom class each serves.
_GRID_TARGETS = frozenset({"np.linspace", "np.arange"})
_MATH_TARGETS = frozenset({"np.sin", "np.cos", "np.tan", "np.exp", "np.log", "np.sqrt", "np.abs"})
_MARK_TARGETS = frozenset({"plt.plot", "plt.scatter", "plt.bar", "plt.barh"})
_DECOR_TARGETS = frozenset({"plt.title", "plt.xlabel", "plt.ylabel", "plt.legend", "plt.grid"})
# Presentation calls, admitted because the measured proposer writes them in 16 of 25 simple prompts
# and none of them can change a plotted value. `plt.figure` is the exception that proves the class:
# a SECOND one starts a new figure and would orphan whatever was already drawn, so projection binds
# it to a position (`figure_orphans_mark`) rather than treating it as free.
_PRESENTATION_TARGETS = frozenset({"plt.figure", "plt.tight_layout", "plt.xticks"})
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
    | _PRESENTATION_TARGETS
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
    # Style keywords are closed PER TARGET to match matplotlib's own signature: `plot` takes a
    # linestyle, `bar` does not, and admitting one set for every mark would admit calls that would
    # raise when executed. Each carries a string literal and therefore no data. `c=` and `cmap=`
    # stay out: they are the colour-by-category channel, which encodes a column the projection
    # does not state. `s=` stays out: it is G6's area-encoding channel. `alpha=` and
    # `edgecolors=` stay out because nothing measured asks for them.
    "plt.plot": frozenset({"label", "color", "marker", "linestyle"}),
    "plt.scatter": frozenset({"label", "color", "marker"}),
    "plt.bar": frozenset({"label", "color"}),
    "plt.barh": frozenset({"label", "color"}),
    "plt.figure": frozenset({"figsize"}),
    "plt.tight_layout": frozenset(),
    "plt.xticks": frozenset({"rotation"}),
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
# `<bound name>.index` and `<bound name>.values` -- ONE idiom class, because admission has no types
# and cannot tell an aggregate from a frame. PROJECTION decides: an aggregate's index is its group
# key, while `df.values` is the whole frame as an array and refuses `column_not_from_source` there.
ADMITTED_VALUE_ATTRS = frozenset({"index", "values"})

# `(target, keyword) -> element count`. A tuple display is refused everywhere else by the expression
# tail, so this is the ONLY door a tuple enters the language by, and it is keyed per keyword rather
# than opened globally: `figsize` is the one admitted tuple.
ADMITTED_TUPLE_KEYWORDS: dict[tuple[str, str], int] = {("plt.figure", "figsize"): 2}
# Targets admitting NO positional argument. `plt.figure(1)` selects a figure by number, which is a
# figure-lifecycle effect the spec does not represent, so it refuses rather than being ignored.
_NO_POSITIONAL_TARGETS = frozenset({"plt.figure"})

# The `groupby` idiom, admitted as ONE atomic shape rather than link by link. `_dotted` bounds an
# attribute chain to depth 1 against an `ast.Name`, so the outer `.sum` of a chain -- whose receiver
# is a `Subscript` -- would refuse before the shape could be read at all.
_GROUPBY = "groupby"
_REDUCTIONS = frozenset({"sum", "mean", "min", "max"})

# The pandas plotting ACCESSOR, `<data>.plot(kind="bar"|"line")`, written by 4 of the 25 simple
# `m13-design` captures (bar) and 5 of the 24 simple `m10-design` captures (line). It is its own
# route rather than a dotted target: its receiver is a name the MODEL bound,
# so admitting it through `ADMITTED_CALL_TARGETS` -- which is keyed by a FIXED import alias -- would
# open every `<name>.plot` at once.
_ACCESSOR_ATTR = "plot"
# `kind` is TARGET IDENTITY, not a style keyword: each value names the mark the accessor draws, and
# it maps onto that mark's own target string here so projection never defaults an unlisted spelling
# onto a line the program does not draw.
ADMITTED_ACCESSOR_KINDS: dict[str, str] = {"bar": "plt.bar", "barh": "plt.barh", "line": "plt.plot"}
# Closed exactly as `ADMITTED_KEYWORDS` is per target. `x=`/`y=` stay out: they select columns, and
# the accessor's projection reads its channels from the receiver instead.
ADMITTED_ACCESSOR_KEYWORDS = frozenset({"kind", "color"})
# Trailing calls projection UNWRAPS off an admitted chain, BY NAME. `_admit_aggregation` admits ONE
# trailing no-argument call, so `.sort_values()` arrives ALREADY ADMITTED and is refused only at
# projection; an unwrap taking whatever trailing call it finds would admit a REORDERING with nothing
# red, and both G8's row coverage and G9's ordering read off group-key order.
ADMITTED_UNWRAPPED_ATTRS = frozenset({"reset_index"})
# A fixed import alias is never an accessor receiver: `plt.plot` is a mark target and `pd.plot` /
# `np.plot` are no target at all, so all three keep resolving through `ADMITTED_CALL_TARGETS`.
_IMPORT_ALIASES = frozenset(ADMITTED_IMPORTS.values())

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
    if node.attr not in ADMITTED_VALUE_ATTRS and dotted not in ADMITTED_CONSTANT_ATTRS:
        _refuse("attribute_not_admitted")
    if alias not in scope.bound:
        _refuse("name_not_bound")


def _groupby_root(node: ast.expr) -> tuple[ast.Call, ast.Name] | None:
    """The innermost `<name>.groupby(...)` call an expression is rooted in, with that name.

    Recognizing the aggregation family by its ROOT is what makes the chain admissible atomically.
    A chain rooted in anything else -- `np.random.rand`, whose spine ends at an alias attribute --
    returns `None` and keeps the depth-1 bound that refuses it.
    """
    current = node
    while True:
        if isinstance(current, ast.Call):
            func = current.func
            if not isinstance(func, ast.Attribute):
                return None
            if func.attr == _GROUPBY and isinstance(func.value, ast.Name):
                return current, func.value
            current = func.value
        elif isinstance(current, (ast.Attribute, ast.Subscript)):
            current = current.value
        else:
            return None


@dataclass(frozen=True, slots=True)
class AggregationChain:
    """The canonical `<frame>.groupby("<key>")["<column>"].<reduction>()`, read structurally."""

    frame: str
    key: str
    column: str
    reduction: str


def aggregation_chain(node: ast.expr) -> AggregationChain | None:
    """Read the canonical chain, or `None` for every other shape.

    The spine is written down ONCE, here beside the admission that closes it, and projection reads
    it back instead of restating it: two matchers over one shape drift apart silently, and only one
    of them would be the boundary.
    """
    match node:
        case ast.Call(
            func=ast.Attribute(
                value=ast.Subscript(
                    value=ast.Call(
                        func=ast.Attribute(value=ast.Name(id=frame), attr=str() as grouper),
                        args=[ast.Constant(value=str() as key)],
                        keywords=[],
                    ),
                    slice=ast.Constant(value=str() as column),
                ),
                attr=str() as reduction,
            ),
            args=[],
            keywords=[],
        ) if grouper == _GROUPBY and reduction in _REDUCTIONS:
            return AggregationChain(frame=frame, key=key, column=column, reduction=reduction)
        case _:
            return None


def accessor_receiver(node: ast.Call) -> ast.Name | None:
    """The bound NAME an accessor call draws from, or `None` for every other call shape.

    The shape is written down ONCE, here beside the admission that closes it, and projection reads
    it back instead of restating it: two matchers over one shape drift apart silently, and only one
    of them would be the boundary.

    Shape alone, refusing nothing. `<name>.plot(...)` and `<name>["<col>"].plot(...)` both return
    the ROOT name, because both are receivers the checks below have to price; deciding `kind` or
    the keywords here would land `call_target_not_admitted` on a program whose fault is positional.
    """
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != _ACCESSOR_ATTR:
        return None
    root = func.value
    if isinstance(root, ast.Subscript):
        root = root.value
    if not isinstance(root, ast.Name) or root.id in _IMPORT_ALIASES:
        return None
    return root


def accessor_is_subscripted(node: ast.Call) -> bool:
    """Whether an accessor call's receiver carries a column subscript.

    Split from `accessor_receiver` rather than folded into its return, because the two stages price
    different things about one subscript: admission prices its SLICE, projection prices its EFFECT,
    and the ROOT name is what both have to reach first. Callable only where `accessor_receiver`
    returned a name, which is what makes the cast a postcondition rather than a hope.
    """
    func = cast("ast.Attribute", node.func)
    return isinstance(func.value, ast.Subscript)


def accessor_kind(node: ast.Call) -> str | None:
    """The accessor's `kind=` string literal, or `None` when it is absent or not a string."""
    for keyword in node.keywords:
        if keyword.arg == "kind":
            value = keyword.value
            if isinstance(value, ast.Constant) and type(value.value) is str:
                return value.value
            return None
    return None


def _admit_accessor(node: ast.Call, receiver: ast.Name, scope: _Scope) -> None:
    """`<data>.plot(kind="<mark>")`, closed on its own shape.

    Refusal order is the contract's: the keyword allowlist prices the call's SHAPE, `kind` then
    prices its TARGET, and the receiver's binding is checked last -- the same target-before-bound
    order `_admit_call` keeps, so the two routes tell an author the same thing about one program.
    """
    if node.args:
        # The accessor's positional slot is `x`, which selects a column the projection reads from
        # the receiver instead. Two channel sources for one mark is not a shape it can state.
        _refuse("keyword_not_admitted")
    for keyword in node.keywords:
        # `arg is None` is `**kwargs`, whose keyword set is not statically known at all.
        if keyword.arg is None or keyword.arg not in ADMITTED_ACCESSOR_KEYWORDS:
            _refuse("keyword_not_admitted")
    if accessor_kind(node) not in ADMITTED_ACCESSOR_KINDS:
        # Unlisted, non-literal and ABSENT all land here: `kind` is the target, so a call whose
        # target cannot be read names no admitted target at all. Absent defaults to a line in
        # pandas, and defaulting is what a closed map exists to refuse.
        _refuse("call_target_not_admitted")
    if receiver.id not in scope.bound:
        _refuse("name_not_bound")
    # `accessor_receiver` reached `receiver` by walking `node.func`, so an `ast.Attribute` here is
    # its postcondition rather than a hope.
    func = cast("ast.Attribute", node.func)
    if isinstance(func.value, ast.Subscript):
        _admit_string_index(func.value.slice)
    for keyword in node.keywords:
        _admit_expr(keyword.value, scope)


def _admit_string_index(node: ast.expr) -> None:
    """A string-literal column name. A tuple selection (`[["a", "b"]]`) lands here and refuses."""
    if not isinstance(node, ast.Constant) or type(node.value) is not str:
        _refuse("column_not_literal")


def _admit_reduction_chain(node: ast.Call, root: ast.Call) -> None:
    """The two links above the root: `["<col>"]`, then `.<reduction>()` with no argument."""
    if node.args or node.keywords:
        # A reduction carrying `axis=` or a positional computes something else entirely.
        _refuse("keyword_not_admitted")
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in _REDUCTIONS:
        _refuse("attribute_not_admitted")
    selection = func.value
    if not isinstance(selection, ast.Subscript) or selection.value is not root:
        _refuse("attribute_not_admitted")
    _admit_string_index(selection.slice)


def _admit_aggregation(node: ast.Call, root: ast.Call, frame: ast.Name, scope: _Scope) -> None:
    """Admit the `groupby` idiom as one closed shape. Three spellings pass.

    The bare `<frame>.groupby("<key>")`, the canonical
    `<frame>.groupby("<key>")["<col>"].<reduction>()`, and that chain carrying ONE trailing no-
    argument call. The trailing call is admitted as a CLASS and unwrapped by name: projection reads
    `ADMITTED_UNWRAPPED_ATTRS` and refuses every other spelling, `.sort_values()` included, so
    `aggregation_not_projected` names an unstatable meaning where `attribute_not_admitted` would
    blame the attribute. The bare `groupby` admits for the same reason and reduces nothing.
    """
    if frame.id not in scope.bound:
        _refuse("name_not_bound")
    if len(root.args) != 1 or root.keywords:
        _refuse("column_not_literal")
    _admit_string_index(root.args[0])
    if node is root:
        return
    # `_groupby_root` reached `root` by walking `node.func`, so an `ast.Attribute` here is its
    # postcondition rather than a hope. Casting instead of re-testing keeps the branch out of the
    # module: an arm no input can take is one the coverage gate cannot price.
    func = cast("ast.Attribute", node.func)
    reduction = node
    receiver = func.value
    if isinstance(receiver, ast.Call) and receiver is not root:
        if func.attr.startswith("_") or node.args or node.keywords:
            _refuse("attribute_not_admitted")
        reduction = receiver
    _admit_reduction_chain(reduction, root)


def _admit_call_or_aggregation(node: ast.Call, scope: _Scope) -> None:
    """Route one call: two idioms close on their own shape, everything else by target."""
    receiver = accessor_receiver(node)
    if receiver is not None:
        _admit_accessor(node, receiver, scope)
        return
    rooted = _groupby_root(node)
    if rooted is None:
        _admit_call(node, scope)
        return
    root, frame = rooted
    _admit_aggregation(node, root, frame, scope)


def _admit_number_tuple(node: ast.expr, arity: int) -> None:
    """A fixed-arity tuple of NUMERIC literals, admitted in one keyword slot and nowhere else."""
    if not isinstance(node, ast.Tuple) or len(node.elts) != arity:
        _refuse("literal_not_admitted")
    for element in node.elts:
        # Exact type: `bool` subclasses `int`, and `figsize=(True, 6)` is not a figure size.
        if not isinstance(element, ast.Constant) or type(element.value) not in (int, float):
            _refuse("literal_not_admitted")


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
        arity = ADMITTED_TUPLE_KEYWORDS.get((target, keyword.arg))
        if arity is None:
            _admit_expr(keyword.value, scope)
        else:
            _admit_number_tuple(keyword.value, arity)
    if node.args and target in _NO_POSITIONAL_TARGETS:
        _refuse("keyword_not_admitted")
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
        _admit_call_or_aggregation(node, scope)
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
        _admit_call_or_aggregation(value, scope)
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
