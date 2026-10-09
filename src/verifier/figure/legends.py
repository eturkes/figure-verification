# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Legend ↔ artists (`legend_mismatch`), each series' displayed name, and each encoding key.

An entry names a judged mark by handle (the artist or container itself, in any axes of the
figure), or as a proxy by a mark's own label + colour (an axes legend: in its axes; a figure
legend: anywhere). A `legend_elements` key names no series: it explains its collection's sizes or
colours. With ≥ 2 series (lines, points, bars, areas) in a legended axes, every one is named;
pies and reference marks may stay unnamed.
"""

from dataclasses import dataclass, field

from verifier.figure.description import Legend, LegendEntry
from verifier.figure.parts import Mark, Panel
from verifier.figure.reasons import block
from verifier.figure.shapes import RGB, color, label, series_marks

type Names = dict[tuple[int, int], str]  # (panel position, the named artist) -> its name


@dataclass(frozen=True, slots=True)
class Legends:
    """What the figure's legends say: the names of drawn marks, and the encodings they explain."""

    names: Names = field(default_factory=dict)
    # (figure axes index, scatter artist, "sizes" | "colors")
    encodings: frozenset[tuple[int, int, str]] = frozenset()


type _Candidate = tuple[int, Mark, str, RGB | None]  # (panel position, mark, own label, colour)


def _candidates(panels: tuple[Panel, ...], positions: list[int]) -> list[_Candidate]:
    return [
        (position, mark, label(panels[position].axes, mark), color(panels[position].axes, mark))
        for position in positions
        for mark in panels[position].marks
        if mark.family != "pie"
    ]


def _handle(
    entry: LegendEntry, panels: tuple[Panel, ...], by_axes: dict[int, int]
) -> tuple[int, int] | None:
    """(panel position, named artist) of a handle the reader found drawn, if it is judged."""
    position = by_axes.get(entry.axes) if entry.axes is not None else None
    if position is None:
        return None
    for mark in panels[position].marks:
        if entry.target is not None and entry.target in mark.artists:
            return position, entry.target
        if entry.container is not None and mark.container == entry.container:
            return position, mark.artists[0]
    return None


def _proxy(entry: LegendEntry, candidates: list[_Candidate]) -> tuple[int, int] | None:
    rgb = None if entry.proxy_color is None else entry.proxy_color[:3]
    matches = [
        (position, mark.artists[0])
        for position, mark, own_label, own in candidates
        if rgb is not None and own_label == entry.text and own == rgb
    ]
    return matches[0] if len(matches) == 1 else None


def _encoding(
    entry: LegendEntry, panels: tuple[Panel, ...], by_axes: dict[int, int]
) -> tuple[int, int, str] | None:
    keyed = entry.elements_of
    if keyed is None or keyed[0] is None or entry.axes is None or entry.axes not in by_axes:
        return None
    panel = panels[by_axes[entry.axes]]
    if not any(m.family == "scatter" and m.artists[0] == keyed[0] for m in panel.marks):
        return None
    return entry.axes, keyed[0], keyed[1]


def _read(
    legend: Legend,
    panels: tuple[Panel, ...],
    by_axes: dict[int, int],
    candidates: list[_Candidate],
) -> tuple[Names, set[tuple[int, int, str]]]:
    names: Names = {}
    encodings: set[tuple[int, int, str]] = set()
    for entry in legend.entries:
        if entry.elements_of is not None:
            encoding = _encoding(entry, panels, by_axes)
            if encoding is None:
                block("legend_mismatch", legend.site)
            encodings.add(encoding)
            continue
        named = (
            _handle(entry, panels, by_axes)
            if entry.target is not None or entry.container is not None
            else _proxy(entry, candidates)
        )
        if named is None or named in names:
            block("legend_mismatch", legend.site)
        names[named] = entry.text
    return names, encodings


def read_legends(panels: tuple[Panel, ...], figure_legends: tuple[Legend, ...]) -> Legends:
    by_axes = {panel.index: position for position, panel in enumerate(panels)}
    names: Names = {}
    encodings: set[tuple[int, int, str]] = set()
    for position, panel in enumerate(panels):
        legend = panel.axes.legend
        if legend is None:
            continue
        found, keys = _read(legend, panels, by_axes, _candidates(panels, [position]))
        names |= found
        encodings |= keys
        series = series_marks(panel)
        named = [mark for mark in series if (position, mark.artists[0]) in found]
        if named and len(series) >= 2 and len(named) != len(series):  # noqa: PLR2004
            block("legend_mismatch", legend.site)
    everywhere = _candidates(panels, list(range(len(panels))))
    for legend in figure_legends:
        found, keys = _read(legend, panels, by_axes, everywhere)
        names |= found
        encodings |= keys
    return Legends(names, frozenset(encodings))
