# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The reader's figure description, decoded strictly into closed types (stdlib; M19).

The description is the judge's only view of the figure, so this decoder admits exactly the shape
`reader.py` writes: one tagged line, a closed key set at every level, every value exactly typed
(a JSON `true` is no integer, `1` is no float), non-finite numbers only as the strings `nan`
`inf` `-inf`. Anything else decodes to `None`, which the outlet reports as `no_description`.
"""

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

TAG: Final = "FIGURE_VERIFICATION_DESCRIPTION:"
VERSION: Final = "figure-description/1"
MAX_BYTES: Final = 400_000
_NON_FINITE: Final = {"nan": math.nan, "inf": math.inf, "-inf": -math.inf}
_ERROR_KINDS: Final = frozenset({"syntax", "exception", "draw"})
_AXIS_KINDS: Final = frozenset({"numeric", "category", "date", "unknown"})
_TRANSFORMS: Final = frozenset({"data", "axes", "xaxis", "yaxis", "figure", "other"})
_ORIENTATIONS: Final = frozenset({"vertical", "horizontal"})
_ELEMENT_PROPS: Final = frozenset({"sizes", "colors"})

type Color = tuple[float, float, float, float]
type Pair = tuple[float, float]


@dataclass(frozen=True, slots=True)
class ProgramError:
    kind: str  # syntax | exception | draw
    name: str
    line: int | None


@dataclass(frozen=True, slots=True)
class Text:
    text: str
    site: int | None


@dataclass(frozen=True, slots=True)
class LineGeometry:
    x: tuple[float, ...]
    y: tuple[float, ...]
    color: Color
    marker: str
    linestyle: str
    drawstyle: str
    linewidth: float
    markersize: float
    marker_face: Color
    marker_edge: Color


@dataclass(frozen=True, slots=True)
class RectGeometry:
    x: float
    y: float
    width: float
    height: float
    angle: float
    color: Color
    edge: Color
    linewidth: float


@dataclass(frozen=True, slots=True)
class WedgeGeometry:
    cx: float
    cy: float
    r: float
    width: float | None
    theta1: float
    theta2: float
    color: Color
    edge: Color
    linewidth: float


@dataclass(frozen=True, slots=True)
class PolygonGeometry:
    xy: tuple[Pair, ...]
    color: Color
    edge: Color
    linewidth: float


@dataclass(frozen=True, slots=True)
class ScatterGeometry:
    offsets: tuple[Pair, ...]
    sizes: tuple[float, ...]
    colors: tuple[Color, ...]
    edges: tuple[Color, ...]
    linewidths: tuple[float, ...]
    array: tuple[float, ...] | None
    colorbar: bool


@dataclass(frozen=True, slots=True)
class BandArrays:
    """A plain `fill_between` call's arrays, read back from its one polygon (no `where`/`step`)."""

    x: tuple[float, ...]
    y1: tuple[float, ...]
    y2: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class BandGeometry:
    paths: tuple[tuple[Pair, ...], ...]
    color: Color | None
    edge: Color | None
    linewidth: float
    band: BandArrays | None
    inputs: int | None  # how many points the `fill_between` call received


@dataclass(frozen=True, slots=True)
class TextGeometry:
    text: str


@dataclass(frozen=True, slots=True)
class NoGeometry:
    """An artist class the reader does not measure; the judge refuses it by class."""


type Geometry = (
    LineGeometry
    | RectGeometry
    | WedgeGeometry
    | PolygonGeometry
    | ScatterGeometry
    | BandGeometry
    | TextGeometry
    | NoGeometry
)


@dataclass(frozen=True, slots=True)
class Artist:
    cls: str
    origin: str | None
    site: int | None
    visible: bool
    alpha: float | None
    label: str
    transform: str
    geometry: Geometry


@dataclass(frozen=True, slots=True)
class HistRecord:
    values: tuple[float, ...]
    bins: tuple[float, ...]
    density: bool
    weighted: bool
    cumulative: bool
    histtype: str
    datasets: int


@dataclass(frozen=True, slots=True)
class Container:
    cls: str
    orientation: str | None
    label: str
    members: tuple[int, ...]
    hist: HistRecord | None


@dataclass(frozen=True, slots=True)
class PieRecord:
    values: tuple[float, ...]
    normalize: bool
    wedges: tuple[int, ...]
    labels: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class LegendEntry:
    text: str
    axes: int | None  # the axes holding the named artist/container/collection
    target: int | None
    container: int | None
    proxy_color: Color | None
    elements_of: tuple[int | None, str] | None


@dataclass(frozen=True, slots=True)
class Legend:
    site: int | None
    entries: tuple[LegendEntry, ...]


@dataclass(frozen=True, slots=True)
class Axis:
    label: Text | None
    scale: str
    view: Pair
    inverted: bool
    kind: str  # numeric | category | date | unknown
    categories: tuple[tuple[str, float], ...] | None
    formatter: str
    formatter_module: str
    offset: float
    order: int
    percent_xmax: float | None
    ticks: tuple[tuple[float, str], ...]
    dates: tuple[tuple[float, str | None], ...]
    calls: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class Axes:
    cls: str
    site: int | None
    visible: bool
    position: tuple[float, float, float, float]
    colorbar_of: tuple[int, int] | None
    shared_x: tuple[int, ...]
    shared_y: tuple[int, ...]
    titles: tuple[Text | None, Text | None, Text | None]
    x: Axis
    y: Axis
    calls: tuple[tuple[str, int], ...]
    artists: tuple[Artist, ...]
    containers: tuple[Container, ...]
    pies: tuple[PieRecord, ...]
    legend: Legend | None


@dataclass(frozen=True, slots=True)
class Part:
    cls: str
    origin: str | None
    site: int | None


@dataclass(frozen=True, slots=True)
class Figure:
    site: int | None
    titles: tuple[Text | None, Text | None, Text | None]  # suptitle, supxlabel, supylabel
    texts: tuple[Text, ...]
    legends: tuple[Legend, ...]
    others: tuple[Part, ...]
    axes: tuple[Axes, ...]


@dataclass(frozen=True, slots=True)
class Description:
    version: str
    error: ProgramError | None
    too_large: bool
    glyphs: int
    figures: tuple[Figure, ...]


class _InvalidError(ValueError):
    """The value is not the shape the reader writes."""


def _object(value: object, keys: tuple[str, ...]) -> dict[str, object]:
    if type(value) is not dict or set(value) != set(keys):
        raise _InvalidError
    return value


def _list(value: object) -> list[object]:
    if type(value) is not list:
        raise _InvalidError
    return value


def _int(value: object) -> int:
    if type(value) is not int:
        raise _InvalidError
    return value


def _bool(value: object) -> bool:
    if type(value) is not bool:
        raise _InvalidError
    return value


def _str(value: object) -> str:
    if type(value) is not str:
        raise _InvalidError
    return value


def _float(value: object) -> float:
    if type(value) is float and math.isfinite(value):  # `1e999` parses to inf: never a number
        return value
    if type(value) is str and value in _NON_FINITE:
        return _NON_FINITE[value]
    raise _InvalidError


def _choice(value: object, allowed: frozenset[str]) -> str:
    if type(value) is not str or value not in allowed:
        raise _InvalidError
    return value


def _optional[T](value: object, read: Callable[[object], T]) -> T | None:
    return None if value is None else read(value)


def _tuple[T](value: object, read: Callable[[object], T]) -> tuple[T, ...]:
    return tuple(read(item) for item in _list(value))


def _pair(value: object) -> Pair:
    items = _list(value)
    if len(items) != 2:  # noqa: PLR2004 - a coordinate pair
        raise _InvalidError
    return _float(items[0]), _float(items[1])


def _color(value: object) -> Color:
    items = _list(value)
    if len(items) != 4:  # noqa: PLR2004 - RGBA
        raise _InvalidError
    red, green, blue, alpha = (_float(item) for item in items)
    return red, green, blue, alpha


def _text(value: object) -> Text:
    item = _object(value, ("text", "site"))
    return Text(_str(item["text"]), _optional(item["site"], _int))


def _titles(value: object) -> tuple[Text | None, Text | None, Text | None]:
    items = _list(value)
    if len(items) != 3:  # noqa: PLR2004 - three title slots
        raise _InvalidError
    first, second, third = (_optional(item, _text) for item in items)
    return first, second, third


def _calls(value: object) -> tuple[tuple[str, int], ...]:
    if type(value) is not dict:
        raise _InvalidError
    return tuple((_str(key), _int(line)) for key, line in value.items())


def _line(item: dict[str, object]) -> LineGeometry:
    item = _object(
        item,
        (
            "kind",
            "x",
            "y",
            "color",
            "marker",
            "linestyle",
            "drawstyle",
            "linewidth",
            "markersize",
            "marker_face",
            "marker_edge",
        ),
    )
    x, y = _tuple(item["x"], _float), _tuple(item["y"], _float)
    if len(x) != len(y):
        raise _InvalidError
    return LineGeometry(
        x,
        y,
        _color(item["color"]),
        _str(item["marker"]),
        _str(item["linestyle"]),
        _str(item["drawstyle"]),
        _float(item["linewidth"]),
        _float(item["markersize"]),
        _color(item["marker_face"]),
        _color(item["marker_edge"]),
    )


def _rect(item: dict[str, object]) -> RectGeometry:
    item = _object(
        item, ("kind", "x", "y", "width", "height", "angle", "color", "edge", "linewidth")
    )
    return RectGeometry(
        _float(item["x"]),
        _float(item["y"]),
        _float(item["width"]),
        _float(item["height"]),
        _float(item["angle"]),
        _color(item["color"]),
        _color(item["edge"]),
        _float(item["linewidth"]),
    )


def _wedge(item: dict[str, object]) -> WedgeGeometry:
    item = _object(
        item,
        ("kind", "cx", "cy", "r", "width", "theta1", "theta2", "color", "edge", "linewidth"),
    )
    return WedgeGeometry(
        _float(item["cx"]),
        _float(item["cy"]),
        _float(item["r"]),
        _optional(item["width"], _float),
        _float(item["theta1"]),
        _float(item["theta2"]),
        _color(item["color"]),
        _color(item["edge"]),
        _float(item["linewidth"]),
    )


def _polygon(item: dict[str, object]) -> PolygonGeometry:
    item = _object(item, ("kind", "xy", "color", "edge", "linewidth"))
    return PolygonGeometry(
        _tuple(item["xy"], _pair),
        _color(item["color"]),
        _color(item["edge"]),
        _float(item["linewidth"]),
    )


def _scatter(item: dict[str, object]) -> ScatterGeometry:
    item = _object(
        item,
        ("kind", "offsets", "sizes", "colors", "edges", "linewidths", "array", "colorbar"),
    )
    return ScatterGeometry(
        _tuple(item["offsets"], _pair),
        _tuple(item["sizes"], _float),
        _tuple(item["colors"], _color),
        _tuple(item["edges"], _color),
        _tuple(item["linewidths"], _float),
        _optional(item["array"], lambda value: _tuple(value, _float)),
        _bool(item["colorbar"]),
    )


def _band_arrays(value: object) -> BandArrays:
    item = _object(value, ("x", "y1", "y2"))
    x, y1, y2 = (_tuple(item[name], _float) for name in ("x", "y1", "y2"))
    if not len(x) == len(y1) == len(y2):
        raise _InvalidError
    return BandArrays(x, y1, y2)


def _band(item: dict[str, object]) -> BandGeometry:
    item = _object(item, ("kind", "paths", "color", "edge", "linewidth", "band", "inputs"))
    return BandGeometry(
        _tuple(item["paths"], lambda value: _tuple(value, _pair)),
        _optional(item["color"], _color),
        _optional(item["edge"], _color),
        _float(item["linewidth"]),
        _optional(item["band"], _band_arrays),
        _optional(item["inputs"], _int),
    )


def _text_geometry(item: dict[str, object]) -> TextGeometry:
    return TextGeometry(_str(_object(item, ("kind", "text"))["text"]))


def _no_geometry(item: dict[str, object]) -> NoGeometry:
    _object(item, ("kind",))
    return NoGeometry()


_GEOMETRIES: dict[str, Callable[[dict[str, object]], Geometry]] = {
    "line": _line,
    "rect": _rect,
    "wedge": _wedge,
    "polygon": _polygon,
    "scatter": _scatter,
    "band": _band,
    "text": _text_geometry,
    "none": _no_geometry,
}


def _geometry(value: object) -> Geometry:
    if type(value) is not dict or type(value.get("kind")) is not str:
        raise _InvalidError
    read = _GEOMETRIES.get(value["kind"])
    if read is None:
        raise _InvalidError
    return read(value)


def _artist(value: object) -> Artist:
    item = _object(
        value, ("cls", "origin", "site", "visible", "alpha", "label", "transform", "geometry")
    )
    return Artist(
        _str(item["cls"]),
        _optional(item["origin"], _str),
        _optional(item["site"], _int),
        _bool(item["visible"]),
        _optional(item["alpha"], _float),
        _str(item["label"]),
        _choice(item["transform"], _TRANSFORMS),
        _geometry(item["geometry"]),
    )


def _hist(value: object) -> HistRecord:
    item = _object(
        value, ("values", "bins", "density", "weighted", "cumulative", "histtype", "datasets")
    )
    return HistRecord(
        _tuple(item["values"], _float),
        _tuple(item["bins"], _float),
        _bool(item["density"]),
        _bool(item["weighted"]),
        _bool(item["cumulative"]),
        _str(item["histtype"]),
        _int(item["datasets"]),
    )


def _container(value: object) -> Container:
    item = _object(value, ("cls", "orientation", "label", "members", "hist"))
    return Container(
        _str(item["cls"]),
        _optional(item["orientation"], lambda value: _choice(value, _ORIENTATIONS)),
        _str(item["label"]),
        _tuple(item["members"], _int),
        _optional(item["hist"], _hist),
    )


def _pie(value: object) -> PieRecord:
    item = _object(value, ("values", "normalize", "wedges", "labels"))
    return PieRecord(
        _tuple(item["values"], _float),
        _bool(item["normalize"]),
        _tuple(item["wedges"], _int),
        _optional(item["labels"], lambda labels: _tuple(labels, _str)),
    )


def _elements(value: object) -> tuple[int | None, str]:
    items = _list(value)
    if len(items) != 2:  # noqa: PLR2004 - (collection, prop)
        raise _InvalidError
    return _optional(items[0], _int), _choice(items[1], _ELEMENT_PROPS)


def _entry(value: object) -> LegendEntry:
    item = _object(value, ("text", "axes", "target", "container", "proxy_color", "elements_of"))
    return LegendEntry(
        _str(item["text"]),
        _optional(item["axes"], _int),
        _optional(item["target"], _int),
        _optional(item["container"], _int),
        _optional(item["proxy_color"], _color),
        _optional(item["elements_of"], _elements),
    )


def _legend(value: object) -> Legend:
    item = _object(value, ("site", "entries"))
    return Legend(_optional(item["site"], _int), _tuple(item["entries"], _entry))


def _category(value: object) -> tuple[str, float]:
    items = _list(value)
    if len(items) != 2:  # noqa: PLR2004 - (key, position)
        raise _InvalidError
    return _str(items[0]), _float(items[1])


def _tick(value: object) -> tuple[float, str]:
    items = _list(value)
    if len(items) != 2:  # noqa: PLR2004 - (position, label)
        raise _InvalidError
    return _float(items[0]), _str(items[1])


def _date(value: object) -> tuple[float, str | None]:
    items = _list(value)
    if len(items) != 2:  # noqa: PLR2004 - (position, ISO text)
        raise _InvalidError
    return _float(items[0]), _optional(items[1], _str)


_AXIS_KEYS = (
    "label",
    "scale",
    "view",
    "inverted",
    "kind",
    "categories",
    "formatter",
    "formatter_module",
    "offset",
    "order",
    "percent_xmax",
    "ticks",
    "dates",
    "calls",
)


def _axis(value: object) -> Axis:
    item = _object(value, _AXIS_KEYS)
    return Axis(
        _optional(item["label"], _text),
        _str(item["scale"]),
        _pair(item["view"]),
        _bool(item["inverted"]),
        _choice(item["kind"], _AXIS_KINDS),
        _optional(item["categories"], lambda value: _tuple(value, _category)),
        _str(item["formatter"]),
        _str(item["formatter_module"]),
        _float(item["offset"]),
        _int(item["order"]),
        _optional(item["percent_xmax"], _float),
        _tuple(item["ticks"], _tick),
        _tuple(item["dates"], _date),
        _calls(item["calls"]),
    )


def _index_pair(value: object) -> tuple[int, int]:
    items = _list(value)
    if len(items) != 2:  # noqa: PLR2004 - (axes, artist)
        raise _InvalidError
    return _int(items[0]), _int(items[1])


def _position(value: object) -> tuple[float, float, float, float]:
    items = _list(value)
    if len(items) != 4:  # noqa: PLR2004 - x0 y0 x1 y1
        raise _InvalidError
    x0, y0, x1, y1 = (_float(item) for item in items)
    return x0, y0, x1, y1


_AXES_KEYS = (
    "cls",
    "site",
    "visible",
    "position",
    "colorbar_of",
    "shared_x",
    "shared_y",
    "titles",
    "x",
    "y",
    "calls",
    "artists",
    "containers",
    "pies",
    "legend",
)


def _axes(value: object) -> Axes:
    item = _object(value, _AXES_KEYS)
    return Axes(
        _str(item["cls"]),
        _optional(item["site"], _int),
        _bool(item["visible"]),
        _position(item["position"]),
        _optional(item["colorbar_of"], _index_pair),
        _tuple(item["shared_x"], _int),
        _tuple(item["shared_y"], _int),
        _titles(item["titles"]),
        _axis(item["x"]),
        _axis(item["y"]),
        _calls(item["calls"]),
        _tuple(item["artists"], _artist),
        _tuple(item["containers"], _container),
        _tuple(item["pies"], _pie),
        _optional(item["legend"], _legend),
    )


def _part(value: object) -> Part:
    item = _object(value, ("cls", "origin", "site"))
    return Part(_str(item["cls"]), _optional(item["origin"], _str), _optional(item["site"], _int))


def _figure(value: object) -> Figure:
    item = _object(value, ("site", "titles", "texts", "legends", "others", "axes"))
    return Figure(
        _optional(item["site"], _int),
        _titles(item["titles"]),
        _tuple(item["texts"], _text),
        _tuple(item["legends"], _legend),
        _tuple(item["others"], _part),
        _tuple(item["axes"], _axes),
    )


def _error(value: object) -> ProgramError:
    item = _object(value, ("kind", "name", "line"))
    return ProgramError(
        _choice(item["kind"], _ERROR_KINDS), _str(item["name"]), _optional(item["line"], _int)
    )


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise _InvalidError
    return result


def parse_description(stdout: str) -> Description | None:
    """The one tagged description line of a sandbox reply, decoded; `None` for any other shape."""
    lines = [line for line in stdout.splitlines() if line.startswith(TAG)]
    if len(lines) != 1 or len(lines[0][len(TAG) :].encode("utf-8", "surrogatepass")) > MAX_BYTES:
        return None
    try:
        item = _object(
            # A `NaN`/`Infinity` token parses to a non-finite float, which `_float` refuses.
            json.loads(lines[0][len(TAG) :], object_pairs_hook=_unique),
            ("version", "error", "too_large", "glyphs", "figures"),
        )
        if item["version"] != VERSION:
            return None
        return Description(
            VERSION,
            _optional(item["error"], _error),
            _bool(item["too_large"]),
            _int(item["glyphs"]),
            _tuple(item["figures"], _figure),
        )
    except (ValueError, RecursionError):
        return None
