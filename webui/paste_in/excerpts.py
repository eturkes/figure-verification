# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The program lines each "Show checks" row lists: display only, never a verdict input (M20).

The reader records the program line that created each part of the figure, or made each call that
set an axis (ruling 13). A row lists the lines of the parts its check reads, each widened to its
whole statement and the headers of the blocks around it. The values and columns rows add the
statements that prepare the drawn data: a static trace back from each drawing statement through
the statements that bind or change the names it reads. The trace reads the program text with
`ast`, so it can miss a line (a function's caller, a value a call changes) and decides nothing.
"""

import ast
from dataclasses import dataclass
from typing import Final

from verifier.figure.description import Axes, Description, Text, TextGeometry
from webui.paste_in.checks import Check

type Lines = tuple[tuple[Check, frozenset[int]], ...]

# The listing's own scan bound: a longer program keeps its recorded lines as they are.
_PARSE = 65_536
# Calls that change their receiver in place; with `inplace=True`, any call does.
_CHANGERS: Final = frozenset(
    {
        "add",
        "append",
        "clear",
        "discard",
        "extend",
        "insert",
        "pop",
        "remove",
        "reverse",
        "setdefault",
        "sort",
        "update",
    }
)
# Recorded call slots (`reader.py` `_AXES_CALLS` + `_AXIS_CALLS`): what sets an axis or its ticks.
_TICK_SLOTS: Final = frozenset({"xticks", "yticks", "ticks"})
_AXIS_SLOTS: Final = _TICK_SLOTS | {
    "xlim",
    "ylim",
    "xscale",
    "yscale",
    "xinvert",
    "yinvert",
    "invert",
}
_SCOPES: Final = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_ROWS: Final[tuple[Check, ...]] = ("figure", "parts", "axes", "marks", "values", "columns")


def _sites(*sites: int | None) -> set[int]:
    return {site for site in sites if site is not None}


def _texts(*texts: Text | None) -> set[int]:
    return _sites(*(text.site for text in texts if text is not None))


def _calls(axes: Axes, slots: frozenset[str]) -> set[int]:
    every = (*axes.calls, *axes.x.calls, *axes.y.calls)
    return {line for slot, line, _ in every if slot in slots}


@dataclass(frozen=True, slots=True)
class _Recorded:
    rows: dict[Check, set[int]]
    marks: set[int]  # lines that drew a mark: the trace's seeds
    made: set[int]  # lines that made a figure or an axes: chart, never data


def _recorded(description: Description) -> _Recorded:
    """Each row's recorded lines (contract E1)."""
    rows: dict[Check, set[int]] = {check: set() for check in _ROWS}
    marks: set[int] = set()
    made: set[int] = set()
    for figure in description.figures:
        titles = _texts(*figure.titles)
        texts = _texts(*figure.texts)
        legends = _sites(*(legend.site for legend in figure.legends))
        made |= _sites(figure.site)
        rows["figure"] |= _sites(figure.site) | titles | texts | legends
        rows["parts"] |= titles | texts | legends | _sites(*(part.site for part in figure.others))
        rows["marks"] |= legends
        rows["columns"] |= titles | legends
        for axes in figure.axes:
            words = _sites(*(a.site for a in axes.artists if isinstance(a.geometry, TextGeometry)))
            drawn = _sites(
                *(a.site for a in axes.artists if not isinstance(a.geometry, TextGeometry))
            )
            labels = _texts(*axes.titles, axes.x.label, axes.y.label)
            legend = _sites(axes.legend.site if axes.legend is not None else None)
            axes_site = _sites(axes.site)
            marks |= drawn
            made |= axes_site
            rows["figure"] |= labels | words | legend | _calls(axes, _TICK_SLOTS)
            rows["parts"] |= axes_site | drawn | words | labels | legend
            rows["axes"] |= axes_site | labels | _calls(axes, _AXIS_SLOTS)
            rows["marks"] |= drawn | legend
            rows["values"] |= drawn
            rows["columns"] |= drawn | labels | legend
    return _Recorded(rows, marks, made)


def _names(target: ast.AST) -> set[str]:
    """The names a binding target binds whole; a subscript or attribute target binds none."""
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, ast.Starred):
        return _names(target.value)
    if isinstance(target, ast.Tuple | ast.List):
        return {name for item in target.elts for name in _names(item)}
    return set()


def _root(node: ast.AST) -> set[str]:
    """The name an attribute or subscript chain starts from (`df` in `df.loc['a']`)."""
    while isinstance(node, ast.Attribute | ast.Subscript):
        node = node.value
    return {node.id} if isinstance(node, ast.Name) else set()


def _parts(target: ast.AST) -> set[str]:
    """The names a target changes in place: the root of each subscript or attribute target."""
    if isinstance(target, ast.Attribute | ast.Subscript):
        return _root(target)
    if isinstance(target, ast.Starred):
        return _parts(target.value)
    if isinstance(target, ast.Tuple | ast.List):
        return {name for item in target.elts for name in _parts(item)}
    return set()


def _parameters(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> set[str]:
    arguments = node.args
    every = (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
    rest = (arguments.vararg, arguments.kwarg)
    return {arg.arg for arg in every} | {arg.arg for arg in rest if arg is not None}


def _reads(nodes: list[ast.AST]) -> set[str]:
    """The names the nodes read, less those an inner scope binds (lambda, comprehension, and a
    def or class read whole)."""
    loads: set[str] = set()
    inner: set[str] = set()
    for node in nodes:
        whole = isinstance(node, _SCOPES)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name):
                if isinstance(sub.ctx, ast.Load):
                    loads.add(sub.id)
                elif whole:
                    inner.add(sub.id)
            elif isinstance(sub, ast.Lambda | ast.FunctionDef | ast.AsyncFunctionDef):
                inner |= _parameters(sub)
            elif isinstance(sub, ast.comprehension):
                inner |= _names(sub.target)
    return loads - inner


def _header(node: ast.stmt) -> list[ast.AST]:
    """What a statement evaluates itself: a block statement's header, any other statement whole."""
    if isinstance(node, ast.For | ast.AsyncFor):
        return [node.target, node.iter]
    if isinstance(node, ast.While | ast.If):
        return [node.test]
    if isinstance(node, ast.With | ast.AsyncWith):
        return list(node.items)
    if isinstance(node, ast.Match):
        return [node.subject]
    if isinstance(node, ast.Try | ast.TryStar):
        return []
    return [node]


def _binds(node: ast.stmt) -> set[str]:
    """The names a statement binds whole, so an earlier binding of one no longer reaches a read."""
    found: set[str] = set()
    if isinstance(node, ast.Assign):
        found = {name for target in node.targets for name in _names(target)}
    elif (isinstance(node, ast.AnnAssign) and node.value is not None) or isinstance(
        node, ast.For | ast.AsyncFor
    ):
        found = _names(node.target)
    elif isinstance(node, ast.With | ast.AsyncWith):
        found = {
            name
            for item in node.items
            if item.optional_vars is not None
            for name in _names(item.optional_vars)
        }
    elif isinstance(node, ast.Import | ast.ImportFrom):
        found = {(alias.asname or alias.name).partition(".")[0] for alias in node.names}
    elif isinstance(node, _SCOPES):
        return {node.name}
    for part in _header(node):
        found |= {sub.target.id for sub in ast.walk(part) if isinstance(sub, ast.NamedExpr)}
    return found


def _changes(node: ast.stmt) -> set[str]:
    """The names a statement changes in place: `df['x'] = …`, `n += 1`, `xs.append(…)`."""
    if isinstance(node, ast.Assign | ast.Delete):
        return {name for target in node.targets for name in _parts(target)}
    if isinstance(node, ast.AnnAssign):
        return _parts(node.target)
    if isinstance(node, ast.AugAssign):
        return _names(node.target) | _parts(node.target)
    call = node.value if isinstance(node, ast.Expr) else None
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
        return set()
    method = call.func
    inplace = any(
        keyword.arg == "inplace"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for keyword in call.keywords
    )
    return _root(method.value) if method.attr in _CHANGERS or inplace else set()


@dataclass(frozen=True, slots=True)
class _Statement:
    node: ast.stmt
    own: range  # the lines this statement alone holds: a block statement's header
    whole: range
    outer: tuple[range, ...]  # the headers of the blocks around it
    ancestors: frozenset[int]  # ids of the block statements around it
    scopes: frozenset[int]  # ids of the defs + classes around it


def _span(first: int, body: list[ast.stmt]) -> range:
    return range(first, max(first, body[0].lineno - 1) + 1)


def _blocks(node: ast.stmt) -> list[tuple[range | None, list[ast.stmt]]]:
    """Each block a statement holds, with the header of the `except` handler that opens it."""
    blocks: list[tuple[range | None, list[ast.stmt]]] = [
        (None, getattr(node, name, [])) for name in ("body", "orelse", "finalbody")
    ]
    blocks += [(_span(h.lineno, h.body), h.body) for h in getattr(node, "handlers", ())]
    blocks += [(None, case.body) for case in getattr(node, "cases", ())]
    return [(header, body) for header, body in blocks if body]


def _statements(tree: ast.Module) -> list[_Statement]:
    """Every statement in source order, nested blocks included."""
    found: list[_Statement] = []

    def visit(
        body: list[ast.stmt],
        outer: tuple[range, ...],
        ancestors: frozenset[int],
        scopes: frozenset[int],
    ) -> None:
        for node in body:
            decorators = getattr(node, "decorator_list", [])
            start = min([node.lineno, *(decorator.lineno for decorator in decorators)])
            whole = range(start, (node.end_lineno or node.lineno) + 1)
            blocks = _blocks(node)
            own = _span(start, blocks[0][1]) if blocks else whole
            found.append(_Statement(node, own, whole, outer, ancestors, scopes))
            inner = scopes | {id(node)} if isinstance(node, _SCOPES) else scopes
            for header, block in blocks:
                around = (*outer, own) if header is None else (*outer, own, header)
                visit(block, around, ancestors | {id(node)}, inner)

    visit(tree.body, (), frozenset(), frozenset())
    return found


def _shown(statement: _Statement, *, whole: bool = False) -> set[int]:
    return set(statement.whole if whole else statement.own).union(*statement.outer)


class _Program:
    """The parsed program: the statements each line belongs to, and the preparation trace."""

    def __init__(self, tree: ast.Module) -> None:
        self.statements = _statements(tree)
        self.at: dict[int, list[int]] = {}
        for index, statement in enumerate(self.statements):
            for line in statement.own:
                self.at.setdefault(line, []).append(index)

    def widen(self, lines: set[int]) -> set[int]:
        """Each line as its statements + the headers around them (E2); a line no statement holds
        stays as it is."""
        shown: set[int] = set()
        for line in lines:
            held = self.at.get(line, [])
            shown |= set().union(*(_shown(self.statements[i]) for i in held)) if held else {line}
        return shown

    def prepared(self, marks: set[int], made: set[int]) -> set[int]:
        """The lines of the statements that bind or change what a drawing statement reads (E3)."""
        builders = {index for line in made for index in self.at.get(line, [])}
        taken: set[int] = set()
        for index in sorted({index for line in marks for index in self.at.get(line, [])}):
            taken |= self._trace(index, builders)
        shown: set[int] = set()
        for index in taken:
            statement = self.statements[index]
            shown |= _shown(statement, whole=isinstance(statement.node, _SCOPES))
        return shown

    def _trace(self, index: int, builders: set[int]) -> set[int]:
        seed = self.statements[index]
        needed = _reads(_header(seed.node))
        taken: set[int] = set()
        for earlier in range(index - 1, -1, -1):
            if not needed:
                break
            statement = self.statements[earlier]
            if not statement.scopes <= seed.scopes:
                continue  # a def that does not enclose the seed binds its own names
            node = statement.node
            around = id(node) in seed.ancestors
            if around and isinstance(node, _SCOPES):
                # An enclosing def binds its parameters; its caller is not followed.
                needed -= _parameters(node) if not isinstance(node, ast.ClassDef) else set()
                continue
            bound = _binds(node)
            if not (bound | _changes(node)) & needed:
                continue
            needed -= bound
            # A statement that made the figure or an axes builds the chart, never its data.
            if earlier in builders or isinstance(node, ast.Import | ast.ImportFrom):
                continue
            needed |= _reads(_header(node))
            taken.add(earlier)  # an enclosing block shows as a header already
        return taken


def _parse(program: str) -> _Program | None:
    if len(program) > _PARSE:
        return None
    try:
        return _Program(ast.parse(program))
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None


def excerpts(
    program: str, description: Description | None, failing: Check | None, site: int | None
) -> Lines:
    """Each row's program lines: the recorded ones widened to statements, the values + columns
    rows with the data preparation, the failing row with the line its failure points at."""
    recorded = _recorded(description) if description is not None else _Recorded({}, set(), set())
    rows = recorded.rows
    if failing is not None and site is not None:
        rows[failing] = rows.get(failing, set()) | {site}
    parsed = _parse(program)
    if parsed is not None:
        rows = {check: parsed.widen(lines) for check, lines in rows.items()}
        prepared = parsed.prepared(recorded.marks, recorded.made)
        for check in ("values", "columns"):
            if check in rows:
                rows[check] |= prepared
    return tuple((check, frozenset(lines)) for check, lines in rows.items() if lines)
