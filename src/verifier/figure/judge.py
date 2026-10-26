# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The judge: one described figure in, one verdict out (M19; law `.claude/rules/figure.md`).

Stages, each blocking before the next runs: figure (the run and its one figure) → parts (the
closed artist set) → axes → marks → values → columns. The judge is pure and stdlib: it reads
the reader's description, the user's CSV bytes and the request text, and nothing else.

Values + columns run twice at most (Q45 D1): today's vocabulary first; a figure that pass blocks on
a value or a column runs them again with the admitted computations competing, and keeps the first
pass's verdict unless the second passes or explains every value and blocks on a column.
"""

from dataclasses import dataclass

from verifier.figure.anchoring import Aliases, Anchoring
from verifier.figure.axes_rules import check_axes
from verifier.figure.columns import check_anchoring, check_labels, drawn
from verifier.figure.description import Description, Figure
from verifier.figure.explain import Choice, Context, Unexplained, duplicate_key, explain
from verifier.figure.interpret import interpretation
from verifier.figure.legends import Legends, read_legends
from verifier.figure.mark_rules import check_marks
from verifier.figure.parts import Panel, panels
from verifier.figure.reasons import Blocked, BlockedError, block
from verifier.figure.request import read_request
from verifier.figure.series import series
from verifier.figure.sources import Table, Unreadable, read_table

_MISSING_MODULES = frozenset({"ModuleNotFoundError", "ImportError"})


@dataclass(frozen=True, slots=True)
class Judged:
    """A figure every integrity rule passed: its panels and each series' displayed name."""

    figure: Figure
    panels: tuple[Panel, ...]
    legends: Legends


def check_figure(description: Description) -> None:
    """The run produced exactly one drawable figure, every glyph present."""
    error = description.error
    if error is not None:
        if error.kind == "syntax":
            block("program_syntax_error", error.line)
        if error.name in _MISSING_MODULES:
            block("module_not_available", error.line)
        block("program_error", error.line)
    if description.too_large:
        block("figure_too_large")
    if not description.figures:
        block("no_figure")
    if len(description.figures) > 1:
        block("multiple_figures", description.figures[1].site)
    if description.glyphs:
        block("glyph_missing")


def integrity(description: Description) -> Judged | Blocked:
    """Every stage up to and including the mark rules; values + columns follow (M19.4)."""
    try:
        check_figure(description)
        figure, judged = panels(description)
        for panel in judged:
            check_axes(panel)
        colorbars = {axes.colorbar_shown for axes in figure.axes if axes.colorbar_shown}
        legends = read_legends(judged, figure.legends)
        for panel in judged:
            check_marks(panel, colorbars, legends.encodings)
    except BlockedError as error:
        return error.blocked
    return Judged(figure, judged, legends)


@dataclass(frozen=True, slots=True)
class Passed:
    """A figure every rule passed: what each series was explained by, in plain words."""

    judged: Judged
    choices: tuple[Choice, ...]
    integrity_only: bool
    interpretation: str
    interpretation_ja: str


@dataclass(frozen=True, slots=True)
class Sources:
    """What the user supplied: attached files (name, bytes), the request, and the admin's words."""

    files: tuple[tuple[str, bytes], ...] = ()
    request: str | None = None
    anchoring: Anchoring = "strict"
    aliases: Aliases = ()


def _texts(judged: Judged, *, integrity_only: bool) -> tuple[str, ...]:
    """On-chart text no check judged; a pie's drawn labels are keys once values are compared."""
    listed = [text for panel in judged.panels for text in panel.texts]
    if integrity_only:
        listed += [text for panel in judged.panels for text in panel.pie_labels]
    listed += [text.text for text in judged.figure.texts if text.text.strip()]
    return tuple(listed)


# A second pass can change these verdicts; every other block stands. When the first pass found no
# source for a value and the second explains every value but blocks on its columns, the second
# pass's reason is the one that tells the user what to fix.
_VALUE_REASONS = frozenset({"value_not_found", "label_not_in_request"})
_COLUMN_REASONS = frozenset({"column_not_requested", "column_not_named", "label_not_consistent"})


def judge(description: Description, sources: Sources) -> Passed | Blocked:
    """Every stage: integrity, then the drawn values, then the columns they name; values +
    columns once more with the admitted computations when the first pass blocks on them."""
    judged = integrity(description)
    if isinstance(judged, Blocked):
        return judged
    # Both passes read the same sources: each file and the request are parsed once (a 99,000-row
    # file takes 0.45 s, a MB of typed numbers 1.4 s, M22.1 F3).
    read = [read_table(name, content) for name, content in sources.files]
    tables = tuple(table for table in read if isinstance(table, Table))
    unreadable = tuple(table for table in read if isinstance(table, Unreadable))
    context = Context(
        tables,
        read_request(sources.request),
        sources.request,
        sources.aliases,
        sources.anchoring == "strict",
    )
    first, _explained = _values(judged, sources, context, unreadable, admitted=False)
    if isinstance(first, Blocked) and first.reason in _VALUE_REASONS | _COLUMN_REASONS:
        second, explained = _values(judged, sources, context, unreadable, admitted=True)
        if isinstance(second, Passed) or (explained and first.reason in _VALUE_REASONS):
            return second
    return first


def _values(
    judged: Judged,
    sources: Sources,
    context: Context,
    unreadable: tuple[Unreadable, ...],
    *,
    admitted: bool,
) -> tuple[Passed | Blocked, bool]:
    """The values + columns stages, and whether every series was explained before any block
    (so a block after it is a column's)."""
    integrity_only = not sources.files and not context.request.numbers
    colorbars = {
        (*axes.colorbar_shown, "colors") for axes in judged.figure.axes if axes.colorbar_shown
    }
    every = series(
        judged.panels, judged.legends.names, judged.legends.encodings | frozenset(colorbars)
    )
    choices: tuple[Choice, ...] = ()
    explained = False
    try:
        for each in every:
            if duplicate_key(each):
                block("category_not_unique", each.site)
        if not integrity_only:
            outcome = explain(every, context, unreadable, admitted=admitted)
            if isinstance(outcome, Unexplained):
                block(outcome.reason, outcome.series.site)
            choices = outcome
        explained = True
        columns = drawn(choices)
        check_anchoring(context, columns)
        check_labels(judged.figure, judged.panels, choices, context, columns)
    except BlockedError as error:
        return error.blocked, explained
    texts = _texts(judged, integrity_only=integrity_only)
    passed = Passed(
        judged,
        choices,
        integrity_only,
        interpretation(choices, texts, integrity_only=integrity_only, japanese=False),
        interpretation(choices, texts, integrity_only=integrity_only, japanese=True),
    )
    return passed, True
