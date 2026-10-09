# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Every judged mark as the values it shows: keyed points, a value multiset, or reference values.

A series = one line · scatter collection · bar container · pie · area band · histogram's inputs ·
reference mark, plus each scatter channel a colorbar or legend key shows (colour values, sizes:
R8), each channel point carrying its scatter point's key and value. A keyed point pairs the key its
key axis shows with its value. A bar's value is
its height, stacked or not (matplotlib stores the height it was given); an area band point
carries its base edge, since its value = the far edge the stack computed as base + value.
"""

from dataclasses import dataclass
from typing import Literal, cast

from verifier.figure.axes_rules import value_on_x
from verifier.figure.description import (
    Axes,
    LineGeometry,
    PolygonGeometry,
    RectGeometry,
    ScatterGeometry,
    TextGeometry,
)
from verifier.figure.keys import Key, KeyReader
from verifier.figure.legends import Names
from verifier.figure.parts import Mark, Panel
from verifier.figure.shapes import band_edges, bars

type Shape = Literal["keyed", "values", "reference"]
type Channel = Literal["value", "colors", "sizes"]


@dataclass(frozen=True, slots=True)
class Point:
    key: Key
    value: float
    base: float | None = None  # a stacked point: drawn value = far end, base = what it sits on
    partner: float | None = None  # a channel point: its scatter point's value (same row)


@dataclass(frozen=True, slots=True)
class Series:
    panel: int
    mark: Mark
    shape: Shape
    name: str | None
    points: tuple[Point, ...]
    site: int | None
    channel: Channel = "value"


_NO_KEY = Key()


def _name(mark: Mark, position: int, names: Names) -> str | None:
    """The series' displayed name = its legend entry; a label no legend shows names nothing.

    A pie's wedge labels are its keys and a reference mark names no rows: neither is a series.
    """
    if mark.family in ("pie", "reference"):
        return None
    return names.get((position, mark.artists[0]))


def _keyed_points(axes: Axes, panel: Panel, mark: Mark) -> tuple[Point, ...]:
    keys = KeyReader(axes.y if value_on_x(mark) else axes.x)
    artist = axes.artists[mark.artists[0]]
    geometry = artist.geometry
    if mark.family in ("bar", "hist"):
        return tuple(Point(keys.key(bar.center), bar.extent, None) for bar in bars(axes, mark))
    if mark.family == "line":
        line = cast("LineGeometry", geometry)
        return tuple(Point(keys.key(x), y) for x, y in zip(line.x, line.y, strict=True))
    if mark.family == "scatter":
        offsets = cast("ScatterGeometry", geometry).offsets
        return tuple(Point(keys.key(x), y) for x, y in offsets)
    x, base, far = band_edges(axes, panel)[mark.artists[0]]
    return tuple(
        Point(keys.key(at), top, bottom) for at, bottom, top in zip(x, base, far, strict=True)
    )


def _drawn_label(axes: Axes, text: int | None) -> str | None:
    """A wedge label as drawn: its Text's final text, unless removed, hidden or blank."""
    if text is None:
        return None
    artist = axes.artists[text]
    shown = cast("TextGeometry", artist.geometry).text
    return shown if artist.visible and shown.strip() else None


def _pie(axes: Axes, mark: Mark, position: int, names: Names) -> tuple[Shape, tuple[Point, ...]]:
    """A pie's values keyed by each wedge's drawn label, else by the legend entry naming it."""
    record = axes.pies[cast("int", mark.pie)]
    texts = record.texts if len(record.texts) == len(mark.artists) else (None,) * len(mark.artists)
    labels = [
        _drawn_label(axes, text) or names.get((position, wedge))
        for wedge, text in zip(mark.artists, texts, strict=True)
    ]
    if not any(labels):
        return "values", tuple(Point(_NO_KEY, value) for value in record.values)
    return "keyed", tuple(
        Point(_NO_KEY if text is None else Key(text=text), value)
        for text, value in zip(labels, record.values, strict=True)
    )


def _reference(axes: Axes, mark: Mark) -> tuple[Point, ...]:
    """A reference line's value, or a span's two edges, on its data dimension."""
    geometry = axes.artists[mark.artists[0]].geometry
    dimension = 0 if mark.horizontal else 1
    if isinstance(geometry, LineGeometry):
        values: tuple[float, ...] = tuple(sorted(set(geometry.x if dimension == 0 else geometry.y)))
    elif isinstance(geometry, RectGeometry):
        start = geometry.x if dimension == 0 else geometry.y
        extent = geometry.width if dimension == 0 else geometry.height
        values = (start, start + extent)
    else:
        xy = cast("PolygonGeometry", geometry).xy
        values = (min(p[dimension] for p in xy), max(p[dimension] for p in xy))
    return tuple(Point(_NO_KEY, value) for value in values)


def _channels(
    axes: Axes, panel: Panel, mark: Mark, shown: frozenset[tuple[int, int, str]]
) -> list[tuple[Channel, tuple[Point, ...]]]:
    """A scatter's colour values and sizes, each keyed like its points, where a colorbar or a
    legend key shows them (matplotlib cycles a shorter array over the points)."""
    geometry = cast("ScatterGeometry", axes.artists[mark.artists[0]].geometry)
    marks = _keyed_points(axes, panel, mark)
    found: list[tuple[Channel, tuple[Point, ...]]] = []
    for channel, values in (("colors", geometry.array), ("sizes", geometry.sizes)):
        if values and (panel.index, mark.artists[0], channel) in shown:
            points = tuple(
                Point(point.key, values[i % len(values)], partner=point.value)
                for i, point in enumerate(marks)
            )
            found.append((cast("Channel", channel), points))
    return found


def series(
    panels: tuple[Panel, ...], names: Names, shown: frozenset[tuple[int, int, str]]
) -> tuple[Series, ...]:
    """Every judged mark's series; `shown` = (axes, artist, channel) a colorbar (`colors`) or a
    legend key displays."""
    found: list[Series] = []
    for position, panel in enumerate(panels):
        axes = panel.axes
        for mark in panel.marks:
            site = axes.artists[mark.artists[0]].site
            name = _name(mark, position, names)
            if mark.family == "reference":
                shape: Shape = "reference"
                points = _reference(axes, mark)
            elif mark.family == "pie":
                shape, points = _pie(axes, mark, position, names)
            elif mark.family == "hist":
                record = axes.containers[cast("int", mark.container)].hist
                values = record.values if record is not None else ()
                shape, points = "values", tuple(Point(_NO_KEY, v) for v in values)
            else:
                shape = "keyed"
                points = _keyed_points(axes, panel, mark)
            found.append(Series(position, mark, shape, name, points, site))
            if mark.family == "scatter":
                found += (
                    Series(position, mark, "keyed", name, encoded, site, channel)
                    for channel, encoded in _channels(axes, panel, mark, shown)
                )
    return tuple(found)
