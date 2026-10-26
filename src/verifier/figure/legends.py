# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Legend ↔ artists (`legend_mismatch`), each series' displayed name, and each encoding key.

An entry names a judged mark by handle (the artist or container itself, in any axes of the
figure), or as a proxy by a mark's own label + colour (an axes legend: in its axes; a figure
legend: anywhere), or through an ink-free proxy its axes holds (seaborn's `hue` keys) by colour
alone, naming the one unlabelled series mark of that colour. A `legend_elements` key names no
series: it explains its collection's sizes or colours. With ≥ 2 series (lines, points, bars,
areas) in a legended axes, every one is named; pies and reference marks may stay unnamed.
"""

from dataclasses import dataclass, field
from typing import TypeAlias, cast

from verifier.figure.description import (
    Legend,
    LegendEntry,
    LineGeometry,
    RectGeometry,
    ScatterGeometry,
)
from verifier.figure.parts import Mark, Panel
from verifier.figure.reasons import block
from verifier.figure.request import read_request
from verifier.figure.shapes import RGB, color, label, series_marks

Names: TypeAlias = dict[tuple[int, int], str]  # (panel position, the named artist) -> its name


@dataclass(frozen=True, slots=True)
class Legends:
    """What the figure's legends say: the names of drawn marks, and the encodings they explain."""

    names: Names = field(default_factory=dict)
    # (figure axes index, scatter artist, "sizes" | "colors")
    encodings: frozenset[tuple[int, int, str]] = frozenset()


_Candidate: TypeAlias = tuple[
    int, Mark, str, RGB | None
]  # (panel position, mark, own label, colour)


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
    panel = panels[position]
    for mark in panel.marks:
        if entry.target is not None and entry.target in mark.artists:
            # A series is named once, by its first artist: two bars of one container are one
            # name (reviewer-2 F3). A pie names each wedge.
            return position, entry.target if mark.family == "pie" else mark.artists[0]
        if entry.container is not None and mark.container == entry.container:
            return position, mark.artists[0]
    if entry.target is not None and entry.target in panel.proxies:
        return _proxied(position, panel, entry.target)
    bands = [band for line, band in panel.outlines if line == entry.target]
    return (position, bands[0]) if bands else None


def _hidden(text: str) -> bool:
    """matplotlib shows no legend entry for an empty label or one opening with `_`."""
    return not text or text.startswith("_")


def _proxied(position: int, panel: Panel, proxy: int) -> tuple[int, int] | None:
    """The one series mark of the panel with no shown label of its own and the proxy's colour."""
    rgb = cast("LineGeometry | RectGeometry", panel.axes.artists[proxy].geometry).color[:3]
    matches = [
        mark.artists[0]
        for mark in series_marks(panel)
        if color(panel.axes, mark) == rgb and _hidden(label(panel.axes, mark))
    ]
    return (position, matches[0]) if len(matches) == 1 else None


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


def _size_key_panel(
    entry: LegendEntry, panels: tuple[Panel, ...], by_axes: dict[int, int]
) -> Panel | None:
    """The panel whose hand-built size key is this entry's handle, if it is one."""
    position = by_axes.get(entry.axes) if entry.axes is not None else None
    if position is None or entry.target not in panels[position].size_keys:
        return None
    return panels[position]


def _sized(entry: LegendEntry, panel: Panel) -> tuple[int, int, str] | None:
    """A hand-built size key explains the sizes of the one scatter of its panel that draws its
    size, when its label types one number, that size (sizes are drawn values, R8)."""
    artists = panel.axes.artists
    size = cast("ScatterGeometry", artists[cast("int", entry.target)].geometry).sizes[0]
    drawing = [
        mark.artists[0]
        for mark in panel.marks
        if mark.family == "scatter"
        and size in cast("ScatterGeometry", artists[mark.artists[0]].geometry).sizes
    ]
    if len(drawing) != 1 or read_request(entry.text).sequence != (size,):
        return None
    return panel.index, drawing[0], "sizes"


def _read(
    legend: Legend,
    panels: tuple[Panel, ...],
    by_axes: dict[int, int],
    candidates: list[_Candidate],
) -> tuple[Names, set[tuple[int, int, str]]]:
    names: Names = {}
    encodings: set[tuple[int, int, str]] = set()
    for entry in legend.entries:
        keyed = _size_key_panel(entry, panels, by_axes)
        if entry.elements_of is not None or keyed is not None:
            encoding = _encoding(entry, panels, by_axes) if keyed is None else _sized(entry, keyed)
            # A legend draws each key marker at its `markerscale`: a size key at another scale
            # shows a size its points do not draw.
            if encoding is None or (encoding[2] == "sizes" and legend.markerscale != 1):
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


def _merge(names: Names, found: Names, legend: Legend) -> None:
    """A series takes ONE name: another legend naming it otherwise is a mismatch (reviewer-2 F2:
    an axes legend + a figure legend, or two figure legends, merged with the last name winning)."""
    for mark, text in found.items():
        if names.get(mark, text) != text:
            block("legend_mismatch", legend.site)
    names |= found


def read_legends(panels: tuple[Panel, ...], figure_legends: tuple[Legend, ...]) -> Legends:
    by_axes = {panel.index: position for position, panel in enumerate(panels)}
    names: Names = {}
    encodings: set[tuple[int, int, str]] = set()
    for position, panel in enumerate(panels):
        legend = panel.axes.legend
        if legend is None:
            continue
        found, keys = _read(legend, panels, by_axes, _candidates(panels, [position]))
        _merge(names, found, legend)
        encodings |= keys
        series = series_marks(panel)
        named = [mark for mark in series if (position, mark.artists[0]) in found]
        if named and len(series) >= 2 and len(named) != len(series):  # noqa: PLR2004
            block("legend_mismatch", legend.site)
    everywhere = _candidates(panels, list(range(len(panels))))
    for legend in figure_legends:
        found, keys = _read(legend, panels, by_axes, everywhere)
        _merge(names, found, legend)
        encodings |= keys
    return Legends(names, frozenset(encodings))
