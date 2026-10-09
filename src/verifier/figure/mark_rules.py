# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Mark rules over one judged panel (`.claude/rules/figure.md` § Mark rules).

Order (`.agent/archive/contracts/m19u3.md` U2): `mark_hidden` → `value_not_finite` → bars
(`bar_not_from_zero`, `bars_overlap`) → `x_not_ordered` → `hist_counts` → `pie_not_whole` →
`area_not_from_zero` → scatter encodings. Each block marks the line that drew the offending mark.
"""

import itertools
import math
from typing import Final, cast

from verifier.figure.description import (
    Axes,
    BandGeometry,
    Geometry,
    HistRecord,
    LineGeometry,
    PieRecord,
    PolygonGeometry,
    RectGeometry,
    ScatterGeometry,
    WedgeGeometry,
)
from verifier.figure.parts import Mark, Panel
from verifier.figure.reasons import block
from verifier.figure.shapes import Bar, band_edges, bars, coordinates

_TOLERANCE: Final = 1e-9
# matplotlib computes wedge angles in float32 (`np.asarray(x, np.float32)` in `Axes.pie`).
_PIE_DEGREES: Final = 1e-4


def _site(axes: Axes, mark: Mark) -> int | None:
    return axes.artists[mark.artists[0]].site


def _near(a: float, b: float) -> bool:
    return abs(a - b) <= _TOLERANCE * max(1.0, abs(a), abs(b))


def _record_values(axes: Axes, mark: Mark) -> list[float]:
    """Inputs a mark received besides its geometry: hist inputs + edges, pie values."""
    if mark.container is not None:
        record = axes.containers[mark.container].hist
        return [] if record is None else [*record.values, *record.bins]
    return [] if mark.pie is None else list(axes.pies[mark.pie].values)


_NO_LINE: Final = frozenset({"None", "none", "", " "})


def _clear(rgba: tuple[float, ...] | None) -> bool:
    return rgba is None or rgba[3] == 0.0


def _no_ink(geometry: Geometry) -> bool:
    """The artist's final styling draws nothing: transparent, no line and no marker, zero size."""
    if isinstance(geometry, LineGeometry):
        line = not (
            geometry.linestyle in _NO_LINE or geometry.linewidth == 0.0 or _clear(geometry.color)
        )
        marker = not (
            geometry.marker in _NO_LINE
            or geometry.markersize == 0.0
            or (_clear(geometry.marker_face) and _clear(geometry.marker_edge))
        )
        return not line and not marker
    if isinstance(geometry, ScatterGeometry):
        faces = any(not _clear(face) for face in geometry.colors)
        edges = any(not _clear(edge) for edge in geometry.edges) and any(geometry.linewidths)
        return not any(geometry.sizes) or not (faces or edges)
    patch = cast("RectGeometry | WedgeGeometry | PolygonGeometry | BandGeometry", geometry)
    return _clear(patch.color) and (_clear(patch.edge) or patch.linewidth == 0.0)


def _check_drawn(axes: Axes, panel: Panel) -> None:
    """What a mark receives but does not show: a hidden panel or artist, a non-finite value."""
    if not axes.visible:
        block("mark_hidden", axes.site)
    for mark in panel.marks:
        for index in mark.artists:
            artist = axes.artists[index]
            if not artist.visible or artist.alpha == 0.0 or _no_ink(artist.geometry):
                block("mark_hidden", artist.site)
    for mark in panel.marks:
        values = [value for _, value, _ in coordinates(axes, mark)] + _record_values(axes, mark)
        geometry = axes.artists[mark.artists[0]].geometry
        dropped = (
            isinstance(geometry, BandGeometry)
            and geometry.band is not None
            and geometry.inputs != len(geometry.band.x)
        )
        if dropped or not all(math.isfinite(value) for value in values):
            block("value_not_finite", _site(axes, mark))


def _stacked(bar: Bar, every: list[tuple[bool, Bar]], *, horizontal: bool) -> bool:
    """G1 for a bar off zero: it continues another bar at its position, on the same side of 0."""
    same_side = bar.extent == 0.0 or (bar.extent > 0.0) == (bar.base > 0.0)
    return same_side and any(
        other.index != bar.index
        and other_horizontal == horizontal
        and (other.key, other.thickness) == (bar.key, bar.thickness)
        and other.end == bar.base
        for other_horizontal, other in every
    )


def _check_bars(axes: Axes, panel: Panel) -> None:
    every = [
        (mark.horizontal, bar)
        for mark in panel.marks
        if mark.family in ("bar", "hist")
        for bar in bars(axes, mark)
    ]
    for horizontal, bar in every:
        if bar.base != 0.0 and not _stacked(bar, every, horizontal=horizontal):
            block("bar_not_from_zero", axes.artists[bar.index].site)
    boxes = sorted(
        (*_box(cast("RectGeometry", axes.artists[bar.index].geometry)), bar.index)
        for _, bar in every
    )
    for position, (_x0, x1, y0, y1, index) in enumerate(boxes):
        for other_x0, other_x1, other_y0, other_y1, other in boxes[position + 1 :]:
            if other_x0 >= x1 - _TOLERANCE * max(1.0, abs(x1)):
                break
            width = min(x1, other_x1) - other_x0
            height = min(y1, other_y1) - max(y0, other_y0)
            if width > _TOLERANCE * max(1.0, abs(x1)) and height > _TOLERANCE * max(
                1.0, abs(y1), abs(other_y1)
            ):
                block("bars_overlap", axes.artists[max(index, other)].site)  # the later bar


def _box(rect: RectGeometry) -> tuple[float, float, float, float]:
    """A drawn rectangle in data x/y, whatever its orientation."""
    return (
        min(rect.x, rect.x + rect.width),
        max(rect.x, rect.x + rect.width),
        min(rect.y, rect.y + rect.height),
        max(rect.y, rect.y + rect.height),
    )


def _check_order(axes: Axes, panel: Panel) -> None:
    """G9 / ruling 3: a line runs monotone in x, either way."""
    for mark in panel.marks:
        geometry = axes.artists[mark.artists[0]].geometry
        if mark.family == "line" and isinstance(geometry, LineGeometry):
            steps = [b - a for a, b in itertools.pairwise(geometry.x)]
            if any(step < 0 for step in steps) and any(step > 0 for step in steps):
                block("x_not_ordered", _site(axes, mark))


def _counts(record: HistRecord) -> list[int] | None:
    """numpy's histogram over the drawn edges (last bin closed); None when an input falls out."""
    bins = record.bins
    counts = [0] * (len(bins) - 1)
    for value in record.values:
        if not bins[0] <= value <= bins[-1]:
            return None
        index = next(i for i in range(len(counts)) if value < bins[i + 1] or i == len(counts) - 1)
        counts[index] += 1
    return counts


def _hist_ok(axes: Axes, mark: Mark, record: HistRecord) -> bool:
    bins = record.bins
    plain = record.histtype == "bar" and record.datasets == 1
    if not plain or record.weighted or record.cumulative or len(bins) != len(mark.artists) + 1:
        return False
    if any(b <= a for a, b in itertools.pairwise(bins)):
        return False
    counts = _counts(record)
    if counts is None:  # R2: an input the drawn bins leave out
        return False
    total = sum(counts)
    for position, bar in enumerate(bars(axes, mark)):
        low, high = bins[position], bins[position + 1]
        width = high - low
        count = counts[position]
        expected = (count / width) / total if record.density else float(count)
        if not (
            _near(bar.center, (low + high) / 2)
            and bar.thickness <= width * (1 + _TOLERANCE)
            and bar.extent == expected
        ):
            return False
    return True


def _check_hist(axes: Axes, mark: Mark) -> None:
    record = cast("HistRecord", axes.containers[cast("int", mark.container)].hist)
    if not _hist_ok(axes, mark, record):
        block("hist_counts", _site(axes, mark))


def _pie_ok(record: PieRecord, wedges: list[WedgeGeometry]) -> bool:
    total = sum(record.values)
    if len(wedges) != len(record.values) or total <= 0.0:
        return False  # a partial pie (`normalize=False`, total < 1) fails the 360° sum below
    if len({(wedge.r, wedge.width) for wedge in wedges}) != 1:
        return False
    shares = [value / total if record.normalize else value for value in record.values]
    arcs = sorted(
        (wedge.theta1, wedge.theta2, share) for wedge, share in zip(wedges, shares, strict=True)
    )
    for (start, end, share), following in itertools.zip_longest(arcs, arcs[1:]):
        if abs((end - start) - 360.0 * share) > _PIE_DEGREES:
            return False
        if following is not None and abs(following[0] - end) > _PIE_DEGREES:
            return False
    return abs((arcs[-1][1] - arcs[0][0]) - 360.0) <= _PIE_DEGREES


def _check_pie(axes: Axes, mark: Mark) -> None:
    wedges = [cast("WedgeGeometry", axes.artists[i].geometry) for i in mark.artists]
    if not _pie_ok(axes.pies[cast("int", mark.pie)], wedges):
        block("pie_not_whole", _site(axes, mark))


def _check_scatter(
    axes: Axes, mark: Mark, explained: frozenset[tuple[str, ...]], *, colorbar: bool
) -> None:
    """Varying sizes need a size key of this collection; colours, a colorbar or colour key."""
    geometry = cast("ScatterGeometry", axes.artists[mark.artists[0]].geometry)
    if len(set(geometry.sizes)) > 1 and ("sizes",) not in explained:
        block("marker_size_varies", _site(axes, mark))
    if len(set(geometry.colors)) > 1 and ("colors",) not in explained and not colorbar:
        block("marker_color_varies", _site(axes, mark))


def check_marks(
    panel: Panel,
    colorbars: set[tuple[int, int]],
    encodings: frozenset[tuple[int, int, str]],
) -> None:
    """`colorbars` = (axes, artist) pairs a colorbar is linked to; `encodings` = (axes, artist,
    prop) a legend key explains."""
    axes = panel.axes
    grounded = band_edges(axes, panel)
    _check_drawn(axes, panel)
    _check_bars(axes, panel)
    _check_order(axes, panel)
    for mark in panel.marks:
        if mark.family == "hist":
            _check_hist(axes, mark)
        elif mark.family == "pie":
            _check_pie(axes, mark)
        elif mark.family == "band" and mark.artists[0] not in grounded:
            block("area_not_from_zero", _site(axes, mark))
        elif mark.family == "scatter":
            index = mark.artists[0]
            explained = frozenset(
                (prop,)
                for owner, artist, prop in encodings
                if (owner, artist) == (panel.index, index)
            )
            linked = cast("ScatterGeometry", axes.artists[index].geometry).colorbar
            colorbar = linked and (panel.index, index) in colorbars
            _check_scatter(axes, mark, explained, colorbar=colorbar)
