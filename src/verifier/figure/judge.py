# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The judge: one described figure in, one verdict out (M19; law `.claude/rules/figure.md`).

Stages, each blocking before the next runs: figure (the run and its one figure) → parts (the
closed artist set) → axes → marks → values → columns. The judge is pure and stdlib: it reads
the reader's description, the user's CSV bytes and the request text, and nothing else.
"""

from dataclasses import dataclass

from verifier.figure.axes_rules import check_axes
from verifier.figure.description import Description, Figure
from verifier.figure.legends import Legends, read_legends
from verifier.figure.mark_rules import check_marks
from verifier.figure.parts import Panel, panels
from verifier.figure.reasons import Blocked, BlockedError, block

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
