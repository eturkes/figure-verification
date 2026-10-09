# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The judge: one described figure in, one verdict out (M19; law `.claude/rules/figure.md`).

Stages, each blocking before the next runs: figure (the run and its one figure) → parts (the
closed artist set) → axes → marks → values → columns. The judge is pure and stdlib: it reads
the reader's description, the user's CSV bytes and the request text, and nothing else.
"""

from dataclasses import dataclass

from verifier.figure.anchoring import Aliases, Anchoring
from verifier.figure.axes_rules import check_axes
from verifier.figure.columns import check_anchoring, check_labels, drawn
from verifier.figure.description import Description, Figure
from verifier.figure.explain import Choice, Context, Unexplained, explain
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
        colorbars = {axes.colorbar_of for axes in figure.axes if axes.colorbar_of is not None}
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


def judge(description: Description, sources: Sources) -> Passed | Blocked:
    """Every stage: integrity, then the drawn values, then the columns they name."""
    judged = integrity(description)
    if isinstance(judged, Blocked):
        return judged
    read = [read_table(name, content) for name, content in sources.files]
    tables = tuple(table for table in read if isinstance(table, Table))
    unreadable = tuple(table for table in read if isinstance(table, Unreadable))
    request = read_request(sources.request)
    integrity_only = not sources.files and not request.numbers
    context = Context(
        tables, request, sources.request, sources.aliases, sources.anchoring == "strict"
    )
    colorbars = {
        (*axes.colorbar_of, "colors") for axes in judged.figure.axes if axes.colorbar_of is not None
    }
    every = series(
        judged.panels, judged.legends.names, judged.legends.encodings | frozenset(colorbars)
    )
    choices: tuple[Choice, ...] = ()
    try:
        if not integrity_only:
            outcome = explain(every, context, unreadable)
            if isinstance(outcome, Unexplained):
                block(outcome.reason, outcome.series.site)
            choices = outcome
        columns = drawn(choices)
        check_anchoring(context, columns)
        check_labels(judged.figure, judged.panels, choices, context, columns)
    except BlockedError as error:
        return error.blocked
    texts = _texts(judged, integrity_only=integrity_only)
    return Passed(
        judged,
        choices,
        integrity_only,
        interpretation(choices, texts, integrity_only=integrity_only, japanese=False),
        interpretation(choices, texts, integrity_only=integrity_only, japanese=True),
    )
