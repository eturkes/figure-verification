# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""What each judged mark draws, read off the reader's geometry: coordinates, bars, bands, colour.

Shared by the axes, mark, legend and value stages, so every stage reads one mark the same way.
`Mark.horizontal` = the mark's value lies on x (barh, a horizontal hist, an axvline/axvspan).
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, cast

from verifier.figure.description import (
    Axes,
    BandArrays,
    BandGeometry,
    LineGeometry,
    PolygonGeometry,
    RectGeometry,
    ScatterGeometry,
    WedgeGeometry,
)
from verifier.figure.parts import Mark, Panel

type Coordinate = tuple[int, float, int | None]  # (dimension 0 = x / 1 = y, value, artist line)
type RGB = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class Bar:
    """One bar read by orientation: where it sits on the key axis and how far it reaches."""

    index: int
    key: float  # start on the key axis
    thickness: float
    base: float
    extent: float  # signed length along the value axis

    @property
    def center(self) -> float:
        return self.key + self.thickness / 2

    @property
    def end(self) -> float:
        return self.base + self.extent


def bars(axes: Axes, mark: Mark) -> list[Bar]:
    """The mark's rectangles, by orientation; a bar or hist mark holds rectangles alone."""
    found: list[Bar] = []
    for index in mark.artists:
        rect = cast("RectGeometry", axes.artists[index].geometry)
        if mark.horizontal:
            found.append(Bar(index, rect.y, rect.height, rect.x, rect.width))
        else:
            found.append(Bar(index, rect.x, rect.width, rect.y, rect.height))
    return found


def _reference(axes: Axes, mark: Mark) -> Iterator[Coordinate]:
    """A reference mark's data coordinates, on its data dimension alone."""
    artist = axes.artists[mark.artists[0]]
    dimension = 0 if mark.horizontal else 1
    geometry = artist.geometry
    if isinstance(geometry, LineGeometry):
        values = geometry.x if dimension == 0 else geometry.y
        yield from ((dimension, value, artist.site) for value in values)
    elif isinstance(geometry, RectGeometry):
        start = geometry.x if dimension == 0 else geometry.y
        extent = geometry.width if dimension == 0 else geometry.height
        yield dimension, start, artist.site
        yield dimension, start + extent, artist.site
    else:  # matplotlib 3.8 (the sandbox) draws a span as a Polygon
        polygon = cast("PolygonGeometry", geometry)
        yield from ((dimension, pair[dimension], artist.site) for pair in polygon.xy)


def _line_pairs(geometry: LineGeometry) -> list[tuple[float, float]]:
    return list(zip(geometry.x, geometry.y, strict=True))


def _scatter_pairs(geometry: ScatterGeometry) -> list[tuple[float, float]]:
    return list(geometry.offsets)


def _rect_pairs(geometry: RectGeometry) -> list[tuple[float, float]]:
    return [(geometry.x, geometry.y), (geometry.x + geometry.width, geometry.y + geometry.height)]


def _wedge_pairs(geometry: WedgeGeometry) -> list[tuple[float, float]]:
    radius = geometry.r
    return [
        (geometry.cx - radius, geometry.cy - radius),
        (geometry.cx + radius, geometry.cy + radius),
    ]


def _band_pairs(geometry: BandGeometry) -> list[tuple[float, float]]:
    return [pair for path in geometry.paths for pair in path]


# Judged family -> how its geometry spans the axes (a reference reads its data dimension alone).
_PAIRS: dict[str, Callable[[Any], list[tuple[float, float]]]] = {
    "line": _line_pairs,
    "scatter": _scatter_pairs,
    "bar": _rect_pairs,
    "hist": _rect_pairs,
    "pie": _wedge_pairs,
    "band": _band_pairs,
}


def coordinates(axes: Axes, mark: Mark) -> Iterator[Coordinate]:
    """Every data coordinate the mark draws: what clipping and finiteness read."""
    if mark.family == "reference":
        yield from _reference(axes, mark)
        return
    for index in mark.artists:
        artist = axes.artists[index]
        for x, y in _PAIRS[mark.family](artist.geometry):
            yield 0, x, artist.site
            yield 1, y, artist.site


type Edges = tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]  # x, base, far


def band_edges(axes: Axes, panel: Panel) -> dict[int, Edges]:
    """Each GROUNDED band's (x, base edge, far edge): its base is all zero, or exactly the far
    edge of a grounded band at the same x. Bands that only rest on each other ground nothing."""
    arrays = {
        mark.artists[0]: cast(
            "BandArrays", cast("BandGeometry", axes.artists[mark.artists[0]].geometry).band
        )
        for mark in panel.marks
        if mark.family == "band"
    }
    grounded: dict[int, Edges] = {}
    changed = True
    while changed:
        changed = False
        for index, band in arrays.items():
            if index in grounded:
                continue
            tops = [far for other, (x, _base, far) in grounded.items() if x == band.x]
            for base, far in ((band.y2, band.y1), (band.y1, band.y2)):
                if all(value == 0.0 for value in base) or base in tops:
                    grounded[index] = (band.x, base, far)
                    changed = True
                    break
    return grounded


def color(axes: Axes, mark: Mark) -> RGB | None:
    """A series mark's own colour, as a legend handle shows it (RGB; alpha is presentation)."""
    geometry = axes.artists[mark.artists[0]].geometry
    if isinstance(geometry, ScatterGeometry):
        rgba = geometry.colors[0] if geometry.colors else None
    else:
        rgba = cast("LineGeometry | RectGeometry | BandGeometry", geometry).color
    return None if rgba is None else rgba[:3]


def label(axes: Axes, mark: Mark) -> str:
    """The mark's own label: its container's for bars, else its artist's."""
    if mark.container is not None:
        return axes.containers[mark.container].label
    return axes.artists[mark.artists[0]].label


def series_marks(panel: Panel) -> list[Mark]:
    """The marks a legend may name as series: every family but pies and reference marks."""
    return [mark for mark in panel.marks if mark.family not in ("pie", "reference")]
