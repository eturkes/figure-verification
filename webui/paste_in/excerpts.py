# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The program lines each "Show checks" row lists: display only, never a verdict input (M20).

The reader records the program line that created each part of the figure, or made each call that
set an axis (ruling 13). A row lists the lines of the parts its check reads, each widened to its
whole statement and the headers of the blocks around it. The values and columns rows add the
statements that prepare the drawn data: a static trace back from each drawing statement through
the statements that may bind or change the names it reads, on any path. The trace reads the program
text with `ast`, so it can list a statement that did not run (an `except` fallback), miss one (an
argument's caller, a value a call changes) or stop at its work budget, and decides nothing.
"""

import ast
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, TypeAlias

from verifier.figure.description import Axes, Description, Text, TextGeometry
from webui.paste_in.checks import Check

Lines: TypeAlias = tuple[tuple[Check, frozenset[int]], ...]

# The listing's own scan bound: a longer program keeps its recorded lines as they are.
_PARSE = 65_536
# Statements the preparation trace may visit per program: the outlet runs it on Open WebUI's event
# loop, and one walk per drawing statement over 13,000 statements took 72 s (reviewer-3, M20.3).
_WORK = 100_000
# Calls that change their receiver in place; with `inplace=True`, any call does. `add` stays out:
# pandas' `add` returns a copy.
_CHANGERS: Final = frozenset(
    {
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
# A tick style can change the tick font, and with it the glyphs the figure check counts.
_TICK_SLOTS: Final = frozenset({"xticks", "yticks", "ticks", "style"})
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
_COMPREHENSIONS: Final = (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)
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
            rows["marks"] |= drawn | legend | (axes_site if axes.colorbar_of is not None else set())
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


def _locals(body: list[ast.stmt]) -> set[str]:
    """The names a def or class body binds in its own scope (nested scopes excluded)."""
    found: set[str] = set()
    declared: set[str] = set()
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Global | ast.Nonlocal):
            declared.update(node.names)
        elif isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            found.add(node.id)
        elif isinstance(node, _SCOPES):
            found.add(node.name)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            found |= {(alias.asname or alias.name).partition(".")[0] for alias in node.names}
        elif isinstance(node, ast.ExceptHandler) and node.name:
            found.add(node.name)
        if not isinstance(node, (*_SCOPES, ast.Lambda, *_COMPREHENSIONS)):
            stack.extend(ast.iter_child_nodes(node))
    return found - declared


def _free(node: ast.AST) -> set[str]:
    """The names an expression or statement reads from its enclosing scope: a lambda's
    parameters, a comprehension's targets and a def's own locals are its own."""
    if isinstance(node, ast.Name):
        return {node.id} if isinstance(node.ctx, ast.Load) else set()
    if isinstance(node, ast.Lambda):
        defaults = [*node.args.defaults, *(d for d in node.args.kw_defaults if d is not None)]
        return _reads(defaults) | (_free(node.body) - _parameters(node))
    if isinstance(node, _COMPREHENSIONS):
        first, *rest = node.generators
        parts: list[ast.AST] = [first.target, *first.ifs]
        for generator in rest:
            parts += [generator.target, generator.iter, *generator.ifs]
        parts += [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
        bound = {name for generator in node.generators for name in _names(generator.target)}
        return _free(first.iter) | (_reads(parts) - bound)
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        arguments = node.args
        defaults = [*arguments.defaults, *(d for d in arguments.kw_defaults if d is not None)]
        own = _parameters(node) | _locals(node.body)
        return _reads([*node.decorator_list, *defaults]) | (_reads(node.body) - own)
    if isinstance(node, ast.ClassDef):
        outer = [*node.decorator_list, *node.bases, *node.keywords]
        return _reads(outer) | (_reads(node.body) - _locals(node.body))
    return _reads(list(ast.iter_child_nodes(node)))


def _reads(nodes: Sequence[ast.AST]) -> set[str]:
    return set().union(*(_free(node) for node in nodes))


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
    """Each block a statement holds, with the header of the `except` or `case` that opens it."""
    blocks: list[tuple[range | None, list[ast.stmt]]] = [
        (None, getattr(node, name, [])) for name in ("body", "orelse", "finalbody")
    ]
    blocks += [(_span(h.lineno, h.body), h.body) for h in getattr(node, "handlers", ())]
    if isinstance(node, ast.Match):
        # A `case` carries no line of its own: its header runs from the line after the subject
        # or the previous case's body.
        end = node.subject.end_lineno or node.lineno
        for case in node.cases:
            blocks.append((_span(end + 1, case.body), case.body))
            end = case.body[-1].end_lineno or end
    return [(header, body) for header, body in blocks if body]


def _statements(tree: ast.Module) -> tuple[list[_Statement], dict[int, set[int]]]:
    """Every statement in source order, nested blocks included; and each line of an `except` or
    `case` header with the lines it shows (a failure can point into one)."""
    found: list[_Statement] = []
    headers: dict[int, set[int]] = {}

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
            # A block statement's own lines end before its first block, or before the `case`
            # header that opens it.
            first = blocks[0][0].start if blocks and blocks[0][0] else None
            own = (
                (range(start, first) if first else _span(start, blocks[0][1])) if blocks else whole
            )
            found.append(_Statement(node, own, whole, outer, ancestors, scopes))
            inner = scopes | {id(node)} if isinstance(node, _SCOPES) else scopes
            for header, block in blocks:
                around = (*outer, own) if header is None else (*outer, own, header)
                if header is not None:
                    headers.update(dict.fromkeys(header, set().union(*around)))
                visit(block, around, ancestors | {id(node)}, inner)

    visit(tree.body, (), frozenset(), frozenset())
    return found, headers


def _shown(statement: _Statement, *, whole: bool = False) -> set[int]:
    return set(statement.whole if whole else statement.own).union(*statement.outer)


@dataclass(frozen=True, slots=True)
class _Facts:
    binds: set[str]
    changes: set[str]
    reads: set[str]


class _Program:
    """The parsed program: the statements each line belongs to, and the preparation trace."""

    def __init__(self, tree: ast.Module) -> None:
        self.statements, self.headers = _statements(tree)
        self.at: dict[int, list[int]] = {}
        for index, statement in enumerate(self.statements):
            for line in statement.own:
                self.at.setdefault(line, []).append(index)
        self.facts: dict[int, _Facts] = {}
        self.callers: dict[int, int] = {}
        self.work = _WORK

    def widen(self, lines: set[int]) -> set[int]:
        """Each line as its statements + the headers around them (E2); a line no statement or
        header holds stays as it is."""
        shown: set[int] = set()
        for line in lines:
            held = self.at.get(line, [])
            if held:
                shown |= set().union(*(_shown(self.statements[i]) for i in held))
            else:
                shown |= self.headers.get(line, {line})
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

    def _fact(self, index: int) -> _Facts:
        if index not in self.facts:
            node = self.statements[index].node
            self.facts[index] = _Facts(_binds(node), _changes(node), _reads(_header(node)))
        return self.facts[index]

    def _caller(self, index: int, node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
        """Where the trace resumes past the def at `index`: just before the last statement of
        its own body that calls it, else at that body's last statement."""
        if index not in self.callers:
            scopes = self.statements[index].scopes
            body = [
                later
                for later in range(index + 1, len(self.statements))
                if self.statements[later].scopes == scopes
            ]
            self.work -= len(body)
            calls = [later for later in body if node.name in self._fact(later).reads]
            self.callers[index] = calls[-1] - 1 if calls else (body[-1] if body else index - 1)
        return self.callers[index]

    def _trace(self, index: int, builders: set[int]) -> set[int]:
        seed = self.statements[index]
        needed = set(self._fact(index).reads)
        scopes = seed.scopes
        left: set[int] = set()
        taken: set[int] = set()
        position = index - 1
        while position >= 0 and needed and self.work > 0:
            self.work -= 1
            earlier, position = position, position - 1
            statement = self.statements[earlier]
            node = statement.node
            if not statement.scopes <= scopes:
                continue  # a def that does not enclose the seed binds its own names
            if id(node) in seed.ancestors and isinstance(node, _SCOPES):
                if earlier not in left and not isinstance(node, ast.ClassDef):
                    # Past an enclosing def, its free names resolve where it is called.
                    left.add(earlier)
                    needed -= _parameters(node)
                    scopes = statement.scopes
                    position = self._caller(earlier, node)
                continue
            facts = self._fact(earlier)
            if not (facts.binds | facts.changes) & needed:
                continue
            # A binding the seed's path may skip (a branch, a loop body, a loop that runs zero
            # times) keeps the name needed: an earlier binding can still reach the seed.
            if statement.ancestors <= seed.ancestors and not (
                isinstance(node, ast.For | ast.AsyncFor) and id(node) not in seed.ancestors
            ):
                needed -= facts.binds
            # A statement that made the figure or an axes builds the chart, never its data.
            if earlier in builders or isinstance(node, ast.Import | ast.ImportFrom):
                continue
            needed |= facts.reads
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
