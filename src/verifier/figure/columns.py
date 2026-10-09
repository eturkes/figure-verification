# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The request names the drawn columns; no label names a column the chart does not draw.

Drawn columns = per attached file, the columns that explain the drawn values (`raw`/`group` K and
V, `index` V, `count` K, a reference mark's one column); a label column R6 filters by draws
nothing. Anchoring = the shipped matcher (`anchoring.py`): the demo's substitution rule, or
production's strict rule. G10: a title, axis label, suptitle or legend entry naming a header
column the chart does not draw blocks; over reductions, so does another reduction's summary word.
"""

from dataclasses import dataclass

from verifier.figure.anchoring import (
    AmbiguousTermError,
    anchors,
    nameable,
    named_columns,
    summaries,
)
from verifier.figure.description import Figure, Legend, Text
from verifier.figure.explain import Choice, Context
from verifier.figure.parts import Panel
from verifier.figure.reasons import block
from verifier.figure.sources import Table

_REDUCTIONS: frozenset[str] = frozenset({"sum", "mean", "min", "max"})


@dataclass(frozen=True, slots=True)
class Drawn:
    """Per file name, the columns its values were drawn from."""

    columns: dict[str, frozenset[str]]

    def of(self, table: Table) -> frozenset[str]:
        return self.columns.get(table.name, frozenset())


def drawn(choices: tuple[Choice, ...]) -> Drawn:
    found: dict[str, frozenset[str]] = {}
    for choice in choices:
        for file, columns in choice.columns:
            found[file] = found.get(file, frozenset()) | columns
    return Drawn(found)


def check_anchoring(context: Context, columns: Drawn) -> None:
    """Q8 substitution (demo) / Q37 strict (production) over each file's drawn columns."""
    request = context.request_text
    if request is None:
        return
    for table in context.tables:
        plotted = columns.of(table)
        if not plotted:
            continue
        try:
            named, negated = anchors(
                request, table.header, context.aliases, short_names=context.strict
            )
        except AmbiguousTermError:
            block("column_not_requested")
        if named - plotted and plotted - named:
            block("column_not_requested")
        unnamed = plotted - named
        if (
            context.strict
            and (named or negated)
            and any(nameable(column, context.aliases) for column in unnamed)
        ):
            block("column_not_named")


def _entries(legend: Legend | None) -> list[Text]:
    return [] if legend is None else [Text(entry.text, legend.site) for entry in legend.entries]


def _panel_labels(figure: Figure, panel: Panel) -> list[Text | None]:
    """A panel's judged labels: axis labels, titles, its legend and its colorbars' labels."""
    axes = panel.axes
    texts = [axes.x.label, axes.y.label, *axes.titles, *_entries(axes.legend)]
    for other in figure.axes:
        if other.colorbar_of is not None and other.colorbar_of[0] == panel.index:
            texts += [other.x.label, other.y.label]
    return texts


def _check(
    texts: list[Text | None], reductions: set[str], context: Context, columns: Drawn
) -> None:
    for text in texts:
        if text is None:
            continue
        for table in context.tables:
            header, aliases = table.header, context.aliases
            if named_columns(text.text, header, aliases, ignore_ties=True) - columns.of(table):
                block("label_not_consistent", text.site)
            if reductions and summaries(text.text, header, aliases) - reductions:
                block("label_not_consistent", text.site)


def check_labels(
    figure: Figure,
    panels: tuple[Panel, ...],
    choices: tuple[Choice, ...],
    context: Context,
    columns: Drawn,
) -> None:
    """G10 over every judged label, against every attached file's header: a panel's labels
    against that panel's reductions, the figure's own (suptitle, supxlabel, supylabel, figure
    legends) against every panel's."""
    every: set[str] = set()
    for position, panel in enumerate(panels):
        reductions: set[str] = {
            choice.explanation.family
            for choice in choices
            if choice.series.panel == position
            and choice.explanation is not None
            and choice.explanation.family in _REDUCTIONS
        }
        every |= reductions
        _check(_panel_labels(figure, panel), reductions, context, columns)
    figure_texts = [*figure.titles, *(e for legend in figure.legends for e in _entries(legend))]
    _check(figure_texts, every, context, columns)
