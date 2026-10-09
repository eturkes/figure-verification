# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The closed artist set: every part of the figure is a judged family, listed text, or a block.

Law = `.claude/rules/figure.md` § Closed artist set. A family is decided by (class, origin) and the
records the reader attached (bar container, hist record, pie record, band arrays); a part the table
does not name blocks, marking the line that created it. Each judged axes becomes a `Panel`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal, cast

from verifier.figure.description import (
    Artist,
    Axes,
    BandArrays,
    BandGeometry,
    Description,
    Figure,
    LineGeometry,
    RectGeometry,
    TextGeometry,
)
from verifier.figure.reasons import block
from verifier.figure.ticks import mismatched_tick

type Family = Literal["line", "scatter", "bar", "hist", "pie", "band", "reference"]
type _Kind = Family | Literal["text"] | None

_RASTER: Final = frozenset({"AxesImage", "QuadMesh", "FigureImage", "PcolorImage"})
_LINES: Final = frozenset({"Axes.plot", "Axes.step"})
# Reference origin -> horizontal (its value lies on x).
_REFERENCES: Final = {
    "Axes.axhline": False,
    "Axes.axhspan": False,
    "Axes.axvline": True,
    "Axes.axvspan": True,
}
_REFERENCE_LINES: Final = frozenset({"Axes.axhline", "Axes.axvline"})
_REFERENCE_SPANS: Final = frozenset({"Axes.axhspan", "Axes.axvspan"})
_LISTED: Final = frozenset({"Axes.text", "Axes.annotate", "Axes.bar_label", "Axes.pie"})
_BANDS: Final = frozenset({"Axes.fill_between", "stackplot"})
_BARS: Final = frozenset({"Axes.bar", "Axes.barh"})
_TOLERANCE: Final = 1e-9


@dataclass(frozen=True, slots=True)
class Mark:
    """One judged mark: its family, the axes artists that draw it, and the record grouping them.

    `horizontal` = the mark's value lies on x (barh, a horizontal hist, an axvline/axvspan).
    """

    family: Family
    artists: tuple[int, ...]
    container: int | None = None
    pie: int | None = None
    horizontal: bool = False


@dataclass(frozen=True, slots=True)
class Panel:
    """One judged axes: its index in the figure, its marks, and the text it only lists."""

    index: int
    axes: Axes
    marks: tuple[Mark, ...]
    texts: tuple[str, ...]
    pie_labels: tuple[str, ...] = ()  # drawn wedge labels: keys the values stage judges


def _line(artist: Artist, _axes: Axes, _index: int) -> _Kind:
    origin = artist.origin or ""
    if origin in _LINES:
        return "line"
    return "reference" if origin in _REFERENCE_LINES else None


def _scatter(artist: Artist, _axes: Axes, _index: int) -> _Kind:
    return "scatter" if artist.origin == "Axes.scatter" else None


def _rectangle(artist: Artist, axes: Axes, index: int) -> _Kind:
    origin = artist.origin or ""
    if origin in _REFERENCE_SPANS:  # matplotlib 3.9 draws a span as a Rectangle
        return "reference"
    owner = next((c for c in axes.containers if index in c.members), None)
    upright = cast("RectGeometry", artist.geometry).angle == 0.0
    if owner is None or owner.cls != "BarContainer" or not upright:  # a rotated bar is no bar
        return None
    if origin in _BARS and owner.hist is None:
        return "bar"
    return "hist" if origin == "Axes.hist" and owner.hist is not None else None


def _polygon(artist: Artist, _axes: Axes, _index: int) -> _Kind:
    # matplotlib 3.8 (the sandbox) draws a span as a Polygon; any other Polygon is unjudged.
    return "reference" if (artist.origin or "") in _REFERENCE_SPANS else None


def _wedge(artist: Artist, axes: Axes, index: int) -> _Kind:
    recorded = any(index in pie.wedges for pie in axes.pies)
    return "pie" if artist.origin == "Axes.pie" and recorded else None


def _band(artist: Artist, _axes: Axes, _index: int) -> _Kind:
    geometry = cast("BandGeometry", artist.geometry)
    # The arrays are read back from the final polygon, and the input count shows what it dropped.
    read_back = geometry.band is not None and geometry.inputs is not None
    return "band" if artist.origin in _BANDS and read_back else None


def _text(artist: Artist, _axes: Axes, _index: int) -> _Kind:
    return "text" if artist.origin in _LISTED else None


_FAMILIES: Final[dict[str, Callable[[Artist, Axes, int], _Kind]]] = {
    "Line2D": _line,
    "PathCollection": _scatter,
    "Rectangle": _rectangle,
    "Polygon": _polygon,
    "Wedge": _wedge,
    "PolyCollection": _band,
    "Text": _text,
    "Annotation": _text,
}


def _family(artist: Artist, axes: Axes, index: int) -> _Kind:
    """The family one artist belongs to; `None` = outside the closed set."""
    read = _FAMILIES.get(artist.cls)
    return None if read is None else read(artist, axes, index)


def _outline(artist: Artist, bands: list[Artist]) -> bool:
    """A pandas area outline: a plotted line equal to a band's edge (stack geometry, not data).

    `artist` is a judged line and every `bands` member a judged band, so their geometry is known.
    """
    line = cast("LineGeometry", artist.geometry)
    for band in bands:
        arrays = cast("BandArrays", cast("BandGeometry", band.geometry).band)
        if line.x == arrays.x and line.y in (arrays.y1, arrays.y2):
            return True
    return False


def _marks(axes: Axes, families: dict[int, Family]) -> list[Mark]:
    marks: list[Mark] = []
    for number, container in enumerate(axes.containers):
        members = tuple(i for i in container.members if families.get(i) in ("bar", "hist"))
        if members:
            family: Family = "hist" if container.hist is not None else "bar"
            horizontal = container.orientation == "horizontal"
            marks.append(Mark(family, members, container=number, horizontal=horizontal))
    for number, pie in enumerate(axes.pies):
        if pie.wedges:
            marks.append(Mark("pie", pie.wedges, pie=number))
    for index, family in families.items():
        if family in ("line", "scatter", "band"):
            marks.append(Mark(family, (index,)))
        elif family == "reference":
            marks.append(
                Mark(
                    "reference", (index,), horizontal=_REFERENCES[axes.artists[index].origin or ""]
                )
            )
    return sorted(marks, key=lambda mark: mark.artists[0])


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    return width > _TOLERANCE and height > _TOLERANCE


# What a colorbar draws itself: its colour solids and the dividers between them.
_COLORBAR_PARTS: Final = frozenset({("QuadMesh", "Axes.pcolormesh"), ("LineCollection", None)})


def _check_colorbar(axes: Axes) -> None:
    """A colorbar holds its own parts alone, and its tick labels name the values they mark."""
    for artist in axes.artists:
        if (artist.cls, artist.origin) not in _COLORBAR_PARTS:
            block("artist_not_judged", artist.site)
    for name, axis in (("x", axes.x), ("y", axes.y)):
        if mismatched_tick(axis, key_labels=False) is not None:
            block("tick_label_mismatch", dict(axes.calls).get(f"{name}ticks", axes.site))


def _judged_axes(figure: Figure) -> list[int]:
    """The judged axes; a colorbar axes passes only as the colorbar of a judged scatter."""
    judged: list[int] = []
    for index, axes in enumerate(figure.axes):
        if axes.cls != "Axes":
            block("axes_not_judged", axes.site)
        if axes.colorbar_of is None:
            judged.append(index)
            continue
        owner, artist = axes.colorbar_of
        mappable = figure.axes[owner].artists[artist]
        if (mappable.cls, mappable.origin) != ("PathCollection", "Axes.scatter"):
            block("axes_not_judged", axes.site)
        _check_colorbar(axes)
    for position, first in enumerate(judged):
        for second in judged[position + 1 :]:
            a, b = figure.axes[first], figure.axes[second]
            if (second in a.shared_x or second in a.shared_y) and a.position == b.position:
                block("axes_twin", dict(a.calls).get("twin", b.site))
            if _overlap(a.position, b.position):
                block("axes_overlap", b.site)
    return judged


def _panel(index: int, axes: Axes) -> Panel:
    families: dict[int, Family] = {}
    texts: list[str] = []
    labels: list[str] = []
    keys = {text for pie in axes.pies for text in pie.texts if text is not None}
    for number, artist in enumerate(axes.artists):
        if artist.cls in _RASTER:
            block("raster_image", artist.site)
        kind = _family(artist, axes, number)
        if kind is None:
            block("artist_not_judged", artist.site)
        if kind == "text":
            text = cast("TextGeometry", artist.geometry).text
            if text.strip():
                (labels if number in keys else texts).append(text)
        else:
            families[number] = kind
    bands = [axes.artists[i] for i, family in families.items() if family == "band"]
    for number in [i for i, family in families.items() if family == "line"]:
        if _outline(axes.artists[number], bands):
            del families[number]
    marks = _marks(axes, families)
    if not marks:
        block("no_data", axes.site)
    return Panel(index, axes, tuple(marks), tuple(texts), tuple(labels))


def panels(description: Description) -> tuple[Figure, tuple[Panel, ...]]:
    """The one figure's judged panels, or a block naming the first part outside the closed set.

    Precondition: the figure stage passed, so exactly one figure is described.
    """
    figure = description.figures[0]
    for part in figure.others:
        block("raster_image" if part.cls in _RASTER else "artist_not_judged", part.site)
    judged = tuple(_panel(index, figure.axes[index]) for index in _judged_axes(figure))
    if not judged:
        block("no_data", figure.site)
    return figure, judged
