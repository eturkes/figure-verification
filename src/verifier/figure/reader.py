# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Run a chart program and report what its finished matplotlib figures hold (M19 reader).

Facts only: every decision is the judge's (`.claude/rules/figure.md`). This file runs inside Open
WebUI's Pyodide sandbox, exec'd from base64 by the wrapper (`webui/paste_in/sandbox.py`), and on the
gate host under test. It is the one `verifier` module that imports matplotlib, numpy and pandas;
every import is lazy, so the stdlib judge never loads them.

The program shares this interpreter (ruling 7: non-adversarial). Hooks installed before it runs
record, per artist, the program line that created it (`site`, display only) and the outermost
Axes-module frame (`origin`, family attribution). The judge decides on the final artist properties,
read after the program finished.

One sandbox runtime serves many replies, so the hooks are installed once per interpreter and find
the current run through one holder object stored on `matplotlib.artist`; a holder from another
reader version is unwound before this version installs its own.
"""

import base64
import contextlib
import functools
import importlib
import inspect
import io
import json
import logging
import math
import re
import sys
import warnings
from collections.abc import Callable, Iterable
from types import FrameType, TracebackType
from typing import Any, cast

PROGRAM = "<verified-figure>"
TAG = "FIGURE_VERIFICATION_DESCRIPTION:"
VERSION = "figure-description/1"
PNG_PREFIX = "data:image/png;base64,"
MAX_AXES = 24
MAX_CHILDREN = 2_000
MAX_COORDINATES = 20_000
MAX_TEXT = 1_000
MAX_DESCRIPTION_BYTES = 400_000
MAX_PNG_CHARACTERS = 500_000
_HOLDER = "_figure_verification_hooks"
_AXES_MODULES = frozenset(
    {"matplotlib.axes._axes", "matplotlib.axes._base", "matplotlib.stackplot"}
)
_PYPLOT = "matplotlib.pyplot"
# Methods whose program call line the Show checks listing marks (ruling 13): name -> slot.
_AXES_CALLS = {
    "set_xlim": "xlim",
    "set_ylim": "ylim",
    "set_xbound": "xlim",
    "set_ybound": "ylim",
    "set_xscale": "xscale",
    "set_yscale": "yscale",
    "invert_xaxis": "xinvert",
    "invert_yaxis": "yinvert",
    "set_xticks": "xticks",
    "set_yticks": "yticks",
    "set_xticklabels": "xticks",
    "set_yticklabels": "yticks",
    "twinx": "twin",
    "twiny": "twin",
    "secondary_xaxis": "twin",
    "secondary_yaxis": "twin",
    "inset_axes": "inset",
    "legend": "legend",
}
_AXIS_CALLS = {
    "set_ticks": "ticks",
    "set_ticklabels": "ticks",
    "set_major_formatter": "ticks",
    "set_major_locator": "ticks",
    "set_inverted": "invert",
}
# A missing glyph's warning: "Glyph <n> (<c>) missing from current font." (matplotlib 3.8, the
# sandbox) or "Glyph <n> (<c>) missing from font(s) <names>." (3.9, the gate host).
_GLYPH = re.compile(r"\AGlyph \d+ .* missing from (?:current )?font", re.DOTALL)
# Mathtext reports a glyph its font set lacks through matplotlib's LOGGER, never `warnings`:
# "Font 'default' does not have a glyph for '\u5e74' [U+5e74], substituting with a dummy symbol."
_MATHTEXT_LOG = "matplotlib.mathtext"
_MATHTEXT_GLYPH = re.compile(r"\AFont .* does not have a glyph for ", re.DOTALL)
_DATE_MODULES = ("matplotlib.dates", "pandas.")
_MATRIX = 2  # a facecolor array is rows of RGBA


class _TooLargeError(Exception):
    """A cap was reached; the description becomes the minimal `too_large` record."""


class _Run:
    """One program run: the figures it produced and what their description has cost so far."""

    def __init__(self) -> None:
        self.figures: list[dict[str, Any]] = []
        self.pngs: list[str] = []
        self.glyphs = 0
        self.coordinates = 0
        self.too_large = False
        self.error: dict[str, Any] | None = None

    def spend(self, count: int) -> None:
        self.coordinates += count
        if self.coordinates > MAX_COORDINATES:
            raise _TooLargeError

    def capture(self) -> None:
        """Draw, describe and render every open figure once, then close them all."""
        plt = importlib.import_module(_PYPLOT)
        for number in plt.get_fignums():
            figure = plt.figure(number)
            try:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    png = io.BytesIO()
                    figure.savefig(png, format="png")  # the one draw the description reads
            except Exception:  # a figure the program left undrawable
                self.error = self.error or {"kind": "draw", "name": "draw", "line": None}
                continue
            self.glyphs += sum(_GLYPH.match(str(item.message)) is not None for item in caught)
            if not self.too_large:
                try:
                    self.figures.append(_figure(figure, self))
                except _TooLargeError:
                    self.too_large = True
            self.pngs.append(base64.b64encode(png.getvalue()).decode("ascii"))
        plt.close("all")


class _GlyphLog(logging.Handler):
    """Counts the mathtext missing-glyph records into the active run."""

    def __init__(self, run: _Run) -> None:
        super().__init__(logging.WARNING)
        self.run = run

    def emit(self, record: logging.LogRecord) -> None:
        self.run.glyphs += _MATHTEXT_GLYPH.match(record.getMessage()) is not None


class _Holder:
    """The interpreter-wide hook state: the active run, and every original this version replaced."""

    def __init__(self) -> None:
        self.version = VERSION
        self.run: _Run | None = None
        self.originals: list[tuple[object, str, object]] = []

    def replace(self, owner: object, name: str, make: Callable[[Any], object]) -> None:
        original = getattr(owner, name)
        self.originals.append((owner, name, original))
        setattr(owner, name, make(original))

    def unwind(self) -> None:
        for owner, name, original in reversed(self.originals):
            setattr(owner, name, original)
        self.originals.clear()


def _program_line(frame: FrameType | None) -> int | None:
    while frame is not None:
        if frame.f_code.co_filename == PROGRAM:
            return frame.f_lineno
        frame = frame.f_back
    return None


def _origin(frame: FrameType | None) -> str | None:
    """The outermost Axes-module frame between the caller and the program, or None."""
    origin = None
    while frame is not None and frame.f_code.co_filename != PROGRAM:
        if frame.f_globals.get("__name__") in _AXES_MODULES:
            origin = frame.f_code.co_qualname
        frame = frame.f_back
    return origin if frame is not None else None


def _direct_line(frame: FrameType | None) -> int | None:
    """The program line when the program itself made this call, directly or through pyplot."""
    while frame is not None and frame.f_globals.get("__name__") == _PYPLOT:
        frame = frame.f_back
    if frame is not None and frame.f_code.co_filename == PROGRAM:
        return frame.f_lineno
    return None


def _number(value: float) -> object:
    """A float as JSON: finite values as numbers, the rest as the strings `nan` `inf` `-inf`."""
    value = float(value)
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return value


def _floats(value: object) -> list[object]:
    np = importlib.import_module("numpy")
    return [_number(v) for v in np.asarray(value, dtype=float).ravel().tolist()]


def _bound(
    original: Callable[..., Any], args: tuple[object, ...], kwargs: dict[str, object]
) -> dict[str, Any]:
    """The hooked call's arguments by parameter name, defaults applied."""
    arguments = inspect.signature(original).bind(*args, **kwargs)
    arguments.apply_defaults()
    return dict(arguments.arguments)


def _called(slot: str) -> Callable[[Any], object]:
    def make(original: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(original)
        def hooked(self: Any, *args: object, **kwargs: object) -> object:
            line = _direct_line(sys._getframe(1))
            if line is not None:
                # The last call decides the property, so the listing marks the last one.
                self.__dict__.setdefault("_fv_calls", {})[slot] = line
            return original(self, *args, **kwargs)

        return hooked

    return make


def _artist_init(original: Callable[..., None]) -> Callable[..., None]:
    @functools.wraps(original)
    def hooked(self: Any, *args: object, **kwargs: object) -> None:
        original(self, *args, **kwargs)
        frame = sys._getframe(1)
        self._fv_site = _program_line(frame)
        self._fv_origin = _origin(frame)

    return hooked


def _set_text(original: Callable[..., None]) -> Callable[..., None]:
    """A text's site = the program line that last set it (`plt.title` sets an existing artist)."""

    @functools.wraps(original)
    def hooked(self: Any, *args: object, **kwargs: object) -> None:
        original(self, *args, **kwargs)
        line = _program_line(sys._getframe(1))
        if line is not None:
            self._fv_site = line

    return hooked


def _legend_init(original: Callable[..., None]) -> Callable[..., None]:
    @functools.wraps(original)
    def hooked(
        self: Any,
        parent: object,
        handles: Iterable[object],
        labels: Iterable[str],
        *args: object,
        **kwargs: object,
    ) -> None:
        handles, labels = list(handles), list(labels)
        self._fv_entries = (handles, labels)
        self._fv_site = _program_line(sys._getframe(1))
        original(self, parent, handles, labels, *args, **kwargs)

    return hooked


def _argument(call: dict[str, Any], name: str) -> Any:
    """A hooked call's argument, resolved through `data=` the way matplotlib resolves it."""
    value = call[name]
    data = call.get("data")
    return data[value] if isinstance(value, str) and data is not None else value


def _recording(record: Callable[[], None]) -> None:
    """Record a construction fact, never at the program's cost: a failure records nothing, and
    the judge then finds no record and refuses the mark."""
    with contextlib.suppress(Exception):
        record()


def _hist(original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def hooked(*args: object, **kwargs: object) -> Any:
        result = original(*args, **kwargs)

        def record() -> None:
            call = _bound(original, args, kwargs)
            cbook = importlib.import_module("matplotlib.cbook")
            datasets = cbook._reshape_2D(_argument(call, "x"), "x")
            facts = {
                "values": [value for data in datasets for value in _floats(data)],
                "bins": _floats(result[1]),
                "density": bool(call["density"]),
                "weighted": call["weights"] is not None,
                "cumulative": bool(call["cumulative"]),
                "histtype": str(call["histtype"]),
                "datasets": len(datasets),
            }
            for container in result[2] if isinstance(result[2], list) else [result[2]]:
                with contextlib.suppress(AttributeError):  # a step outline is a bare Polygon list
                    container._fv_hist = facts

        _recording(record)
        return result

    return hooked


def _pie(original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def hooked(*args: object, **kwargs: object) -> Any:
        result = original(*args, **kwargs)

        def record() -> None:
            call = _bound(original, args, kwargs)
            facts = {
                "values": _floats(_argument(call, "x")),
                "normalize": bool(call["normalize"]),
                "wedges": list(result[0]),
                "texts": list(result[1]),
            }
            call["self"].__dict__.setdefault("_fv_pies", []).append(facts)

        _recording(record)
        return result

    return hooked


def _fill_between(original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def hooked(*args: object, **kwargs: object) -> Any:
        result = original(*args, **kwargs)

        def record() -> None:
            call = _bound(original, args, kwargs)
            result._fv_plain = call["where"] is None and call["step"] is None
            # How many points the call received: a non-finite one leaves the polygon unseen.
            result._fv_inputs = len(_argument(call, "x"))

        _recording(record)
        return result

    return hooked


def _legend_elements(original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def hooked(self: object, *args: object, **kwargs: object) -> Any:
        handles, labels = original(self, *args, **kwargs)
        prop = _bound(original, (self, *args), kwargs)["prop"]
        for handle in handles:
            handle._fv_elements = (self, str(prop))
        return handles, labels

    return hooked


def _show(holder: _Holder) -> Callable[[Any], object]:
    def make(original: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(original)
        def hooked(*args: object, **kwargs: object) -> Any:
            if holder.run is None:
                return original(*args, **kwargs)
            holder.run.capture()
            return None

        return hooked

    return make


def _install(holder: _Holder) -> None:
    def module(name: str) -> Any:
        return importlib.import_module(f"matplotlib.{name}")

    holder.replace(module("artist").Artist, "__init__", _artist_init)
    for name, slot in _AXES_CALLS.items():
        holder.replace(module("axes").Axes, name, _called(slot))
    for name, slot in _AXIS_CALLS.items():
        holder.replace(module("axis").Axis, name, _called(slot))
    holder.replace(module("text").Text, "set_text", _set_text)
    holder.replace(module("legend").Legend, "__init__", _legend_init)
    holder.replace(module("axes").Axes, "hist", _hist)
    holder.replace(module("axes").Axes, "pie", _pie)
    holder.replace(module("axes").Axes, "fill_between", _fill_between)
    holder.replace(module("collections").PathCollection, "legend_elements", _legend_elements)
    holder.replace(module("pyplot"), "show", _show(holder))


def _holder() -> _Holder:
    martist = importlib.import_module("matplotlib.artist")
    found = getattr(martist, _HOLDER, None)
    if getattr(found, "version", None) == VERSION:
        # The same reader exec'd again in this runtime: its hooks call back through this holder.
        return cast("_Holder", found)
    if found is not None:
        found.unwind()
    holder = _Holder()
    _install(holder)
    setattr(martist, _HOLDER, holder)
    return holder


def _rgba(color: object) -> list[float]:
    mcolors = importlib.import_module("matplotlib.colors")
    return [float(c) for c in mcolors.to_rgba(color)]


def _cut(text: str) -> str:
    """Text within the cap; longer text makes the whole description the `too_large` record."""
    if len(text) > MAX_TEXT:
        raise _TooLargeError
    return text


def _text(artist: Any) -> dict[str, Any] | None:
    if artist is None or not artist.get_visible() or artist.get_text() == "":
        return None
    return {"text": _cut(artist.get_text()), "site": getattr(artist, "_fv_site", None)}


def _transform(artist: Any, axes: Any) -> str:
    """Which coordinate system carries the artist's data: the transform its data passes through."""
    kind = type(artist).__name__
    if kind == "PathCollection":
        transform = artist.get_offset_transform()
    elif hasattr(artist, "get_data_transform") and hasattr(artist, "get_path"):
        transform = artist.get_data_transform()
    else:
        transform = artist.get_transform()
    for name, reference in (
        ("data", axes.transData),
        ("axes", axes.transAxes),
        ("xaxis", axes.get_xaxis_transform()),
        ("yaxis", axes.get_yaxis_transform()),
        ("figure", axes.figure.transFigure),
    ):
        if transform == reference:
            return name
    return "other"


def _line(artist: Any, run: _Run) -> dict[str, Any]:
    xy = artist.get_xydata()
    run.spend(len(xy))
    return {
        "kind": "line",
        "x": [_number(x) for x, _ in xy],
        "y": [_number(y) for _, y in xy],
        "color": _rgba(artist.get_color()),
        "marker": str(artist.get_marker()),
        "linestyle": str(artist.get_linestyle()),
        "drawstyle": str(artist.get_drawstyle()),
        "linewidth": _number(artist.get_linewidth()),
        "markersize": _number(artist.get_markersize()),
        "marker_face": _rgba(artist.get_markerfacecolor()),
        "marker_edge": _rgba(artist.get_markeredgecolor()),
    }


def _ink(patch: Any) -> dict[str, Any]:
    """A patch's face and edge: what decides whether it shows any ink."""
    return {
        "color": _rgba(patch.get_facecolor()),
        "edge": _rgba(patch.get_edgecolor()),
        "linewidth": _number(patch.get_linewidth()),
    }


def _rect(artist: Any, run: _Run) -> dict[str, Any]:
    run.spend(1)
    return {
        "kind": "rect",
        "x": _number(artist.get_x()),
        "y": _number(artist.get_y()),
        "width": _number(artist.get_width()),
        "height": _number(artist.get_height()),
        "angle": _number(artist.get_angle()),
        **_ink(artist),
    }


def _wedge(artist: Any, run: _Run) -> dict[str, Any]:
    run.spend(1)
    return {
        "kind": "wedge",
        "cx": _number(artist.center[0]),
        "cy": _number(artist.center[1]),
        "r": _number(artist.r),
        "width": None if artist.width is None else _number(artist.width),
        "theta1": _number(artist.theta1),
        "theta2": _number(artist.theta2),
        **_ink(artist),
    }


def _polygon(artist: Any, run: _Run) -> dict[str, Any]:
    xy = artist.get_xy()
    run.spend(len(xy))
    return {
        "kind": "polygon",
        "xy": [[_number(x), _number(y)] for x, y in xy],
        **_ink(artist),
    }


def _scatter(artist: Any, run: _Run) -> dict[str, Any]:
    offsets = artist.get_offsets()
    run.spend(len(offsets))
    array = artist.get_array()
    return {
        "kind": "scatter",
        "offsets": [[_number(x), _number(y)] for x, y in offsets],
        "sizes": [_number(s) for s in artist.get_sizes()],
        "colors": [_rgba(c) for c in artist.get_facecolors()],
        "edges": [_rgba(c) for c in artist.get_edgecolors()],
        "linewidths": [_number(w) for w in artist.get_linewidths()],
        "array": None if array is None else _floats(array),
        "colorbar": getattr(artist, "colorbar", None) is not None,
    }


def _band_arrays(path: list[list[float]]) -> dict[str, Any] | None:
    """`fill_between`'s polygon read back into its arrays, or None for any other shape.

    One plain call draws (x0, y2_0), every (x_i, y1_i), (x_n, y2_n), every (x_i, y2_i) backwards,
    then (x0, y2_0) again: the vertices hold the arrays exactly, units already converted.
    """
    count = (len(path) - 3) // 2
    if count < 1 or len(path) != 2 * count + 3:
        return None
    forward = path[1 : count + 1]
    backward = path[count + 2 : 2 * count + 2][::-1]
    if (
        path[0] != path[-1]
        or path[0] != backward[0]
        or path[count + 1] != backward[-1]
        or [x for x, _ in forward] != [x for x, _ in backward]
    ):
        return None
    return {
        "x": [_number(x) for x, _ in forward],
        "y1": [_number(y) for _, y in forward],
        "y2": [_number(y) for _, y in backward],
    }


def _band(artist: Any, run: _Run) -> dict[str, Any]:
    paths = [path.vertices.tolist() for path in artist.get_paths()]
    plain = getattr(artist, "_fv_plain", False) is True and len(paths) == 1
    band = _band_arrays(paths[0]) if plain else None
    run.spend(sum(len(path) for path in paths) + (0 if band is None else 3 * len(band["x"])))
    faces, edges, widths = (
        artist.get_facecolors(),
        artist.get_edgecolors(),
        artist.get_linewidths(),
    )
    inputs = getattr(artist, "_fv_inputs", None)
    return {
        "kind": "band",
        "paths": [[[_number(x), _number(y)] for x, y in path] for path in paths],
        "color": _rgba(faces[0]) if len(faces) else None,
        "edge": _rgba(edges[0]) if len(edges) else None,
        "linewidth": _number(widths[0]) if len(widths) else 0.0,
        "band": band,
        "inputs": inputs if isinstance(inputs, int) else None,
    }


def _text_geometry(artist: Any, _run: _Run) -> dict[str, Any]:
    return {"kind": "text", "text": _cut(artist.get_text())}


# Exact class name -> what the reader measures; every other class is described by class alone.
_GEOMETRY: dict[str, Callable[[Any, _Run], dict[str, Any]]] = {
    "Line2D": _line,
    "Rectangle": _rect,
    "Wedge": _wedge,
    "Polygon": _polygon,
    "PathCollection": _scatter,
    "PolyCollection": _band,
    "Text": _text_geometry,
    "Annotation": _text_geometry,
}


def _geometry(artist: Any, run: _Run) -> dict[str, Any]:
    measure = _GEOMETRY.get(type(artist).__name__)
    return {"kind": "none"} if measure is None else measure(artist, run)


def _structural(axes: Any) -> set[int]:
    slots = [axes.patch, axes.xaxis, axes.yaxis, axes.title, axes._left_title, axes._right_title]
    slots += list(axes.spines.values())
    if axes.legend_ is not None:
        slots.append(axes.legend_)
    return {id(slot) for slot in slots}


def _children(axes: Any) -> list[Any]:
    structural = _structural(axes)
    return [child for child in axes.get_children() if id(child) not in structural]


def _artist(artist: Any, axes: Any, run: _Run) -> dict[str, Any]:
    alpha = artist.get_alpha()
    return {
        "cls": type(artist).__name__,
        "origin": getattr(artist, "_fv_origin", None),
        "site": getattr(artist, "_fv_site", None),
        "visible": bool(artist.get_visible()),
        "alpha": None if alpha is None else _number(alpha),
        "label": _cut(str(artist.get_label())),
        "transform": _transform(artist, axes),
        "geometry": _geometry(artist, run),
    }


def _axis_kind(axis: Any) -> str:
    converter = getattr(axis, "converter", None)
    if converter is None:
        return "numeric"
    name = type(converter).__name__
    if name == "StrCategoryConverter":
        return "category"
    if type(converter).__module__.startswith(_DATE_MODULES) and (
        "Date" in name or "Period" in name
    ):
        return "date"
    return "unknown"


def _date(axes: Any, axis: Any, position: float) -> str | None:
    """The calendar reading of one position on a date axis, by the converter that drew it.

    `position` is finite: `_positions` passes floats alone, and non-finite values travel as text.
    """
    if type(axis.converter).__name__ == "PeriodConverter":
        freq = getattr(axes, "freq", None)
        if freq is None or not position.is_integer():
            return None
        pandas = importlib.import_module("pandas")
        return str(pandas.Period(ordinal=int(position), freq=freq).start_time.isoformat())
    mdates = importlib.import_module("matplotlib.dates")
    try:
        return str(mdates.num2date(position).replace(tzinfo=None).isoformat())
    except (ValueError, OverflowError):
        return None


def _formatter(axis: Any) -> tuple[str, str]:
    """The tick formatter's class, and the module whose code writes the label text."""
    formatter = axis.get_major_formatter()
    function = getattr(formatter, "func", None)
    while isinstance(function, functools.partial):
        function = function.func
    owner = type(formatter) if function is None else function
    return type(formatter).__name__, str(owner.__module__)


def _axis(axes: Any, axis: Any, positions: Iterable[object]) -> dict[str, Any]:
    low, high = (float(value) for value in axis.get_view_interval())
    lo, hi = min(low, high), max(low, high)
    formatter = axis.get_major_formatter()
    name, module = _formatter(axis)
    kind = _axis_kind(axis)
    ticks: list[list[object]] = []
    if axes.axison and axis.get_visible():
        for tick in axis.get_major_ticks():
            position = float(tick.get_loc())
            shown = [label for label in (tick.label1, tick.label2) if label.get_visible()]
            if lo <= position <= hi and shown:
                ticks.append([_number(position), _cut(shown[0].get_text())])
    mapping = axis.units._mapping if kind == "category" else None
    dates: list[list[object]] = []
    if kind == "date":
        wanted = {p for p in positions if isinstance(p, float)}
        wanted |= {t[0] for t in ticks if isinstance(t[0], float)}
        dates = [[p, _date(axes, axis, p)] for p in sorted(wanted)]
    scalar = name == "ScalarFormatter"
    return {
        "label": _text(axis.label),
        "scale": str(axis.get_scale()),
        "view": [_number(low), _number(high)],
        "inverted": bool(axis.get_inverted()),
        "kind": kind,
        "categories": None
        if mapping is None
        else [[_cut(str(key)), _number(value)] for key, value in mapping.items()],
        "formatter": name,
        "formatter_module": module,
        "offset": _number(formatter.offset if scalar else 0.0),
        "order": int(formatter.orderOfMagnitude if scalar else 0),
        "percent_xmax": _number(formatter.xmax) if name == "PercentFormatter" else None,
        "ticks": ticks,
        "dates": dates,
        "calls": dict(sorted(getattr(axis, "_fv_calls", {}).items())),
    }


def _positions(artists: list[dict[str, Any]], dimension: int) -> list[object]:
    """Every data coordinate an axis carries: what a date axis must translate."""
    found: list[object] = []
    for artist in artists:
        geometry = artist["geometry"]
        kind = geometry["kind"]
        if kind == "line":
            found += geometry["xy"[dimension]]
        elif kind == "scatter":
            found += [pair[dimension] for pair in geometry["offsets"]]
        elif kind == "rect":
            start = geometry["xy"[dimension]]
            extent = geometry[("width", "height")[dimension]]
            if isinstance(start, float) and isinstance(extent, float):
                found += [start, start + extent / 2, start + extent]
        elif kind == "polygon":
            found += [pair[dimension] for pair in geometry["xy"]]
        elif kind == "band":
            found += [pair[dimension] for path in geometry["paths"] for pair in path]
    return found


def _handle_color(handle: Any) -> list[float] | None:
    """A legend handle's colour, read the way its family draws: patches, lines, collections."""
    if hasattr(handle, "patches"):  # a container handed to the legend whole
        handle = handle.patches[0] if handle.patches else None
    if handle is None:
        return None
    if hasattr(handle, "get_facecolor"):
        value = handle.get_facecolor()
        if getattr(value, "ndim", 1) == _MATRIX:
            return _rgba(value[0]) if len(value) else None
        return _rgba(value)
    return _rgba(handle.get_color()) if hasattr(handle, "get_color") else None


def _find(figure: Any, handle: object) -> tuple[int, int | None, int | None] | None:
    """(axes, artist, container) of the drawn object `handle` is, anywhere in the figure."""
    for number, axes in enumerate(figure.axes):
        artist = next((i for i, child in enumerate(_children(axes)) if child is handle), None)
        container = next((i for i, c in enumerate(axes.containers) if c is handle), None)
        if artist is not None or container is not None:
            return number, artist, container
    return None


def _legend(legend: Any, figure: Any) -> dict[str, Any]:
    """Each entry: its displayed text, and the drawn artist or container it names (anywhere in
    the figure), else its own colour; a `legend_elements` key names its collection."""
    handles, _labels = getattr(legend, "_fv_entries", ([], []))
    shown = iter(legend.texts)  # one text per handle the legend could draw, as finally displayed
    entries = []
    for handle, drawn in zip(handles, legend.legend_handles, strict=False):
        if drawn is None:
            continue
        label = next(shown).get_text()
        found = _find(figure, handle)
        elements = getattr(handle, "_fv_elements", None)
        keyed = None if elements is None else _find(figure, elements[0])
        axes = found[0] if found is not None else (keyed[0] if keyed is not None else None)
        entries.append(
            {
                "text": _cut(str(label)),
                "axes": axes,
                "target": None if found is None else found[1],
                "container": None if found is None else found[2],
                "proxy_color": _handle_color(handle) if found is None else None,
                "elements_of": None
                if elements is None
                else [None if keyed is None else keyed[1], elements[1]],
            }
        )
    return {"site": getattr(legend, "_fv_site", None), "entries": entries}


def _member_indices(members: Iterable[object], children: list[Any]) -> list[int]:
    return [index for member in members for index, child in enumerate(children) if child is member]


def _axes(axes: Any, figure: Any, run: _Run) -> dict[str, Any]:
    children = _children(axes)
    artists = [_artist(child, axes, run) for child in children]
    containers = list(axes.containers)
    described = []
    for container in containers:
        hist = getattr(container, "_fv_hist", None)
        if hist is not None:
            run.spend(len(hist["values"]) + len(hist["bins"]))
        described.append(
            {
                "cls": type(container).__name__,
                "orientation": getattr(container, "orientation", None),
                "label": _cut(str(container.get_label())),
                "members": _member_indices(getattr(container, "patches", ()), children),
                "hist": hist,
            }
        )
    pies = []
    for record in getattr(axes, "_fv_pies", ()):
        run.spend(len(record["values"]))
        pies.append(
            {
                **record,
                "wedges": _member_indices(record["wedges"], children),
                # A label Text the program removed reads as None: that wedge shows no label.
                "texts": [
                    next((index for index, child in enumerate(children) if child is text), None)
                    for text in record["texts"]
                ],
            }
        )
    colorbar = getattr(axes, "_colorbar", None)
    position = axes.get_position()
    siblings = figure.axes
    return {
        "cls": type(axes).__name__,
        "site": getattr(axes, "_fv_site", None),
        "visible": bool(axes.get_visible()),
        "position": [_number(v) for v in (position.x0, position.y0, position.x1, position.y1)],
        "colorbar_of": None if colorbar is None else _locate(siblings, colorbar.mappable),
        "shared_x": _shared(siblings, axes, axes.get_shared_x_axes()),
        "shared_y": _shared(siblings, axes, axes.get_shared_y_axes()),
        "titles": [_text(t) for t in (axes._left_title, axes.title, axes._right_title)],
        "x": _axis(axes, axes.xaxis, _positions(artists, 0)),
        "y": _axis(axes, axes.yaxis, _positions(artists, 1)),
        "calls": dict(sorted(getattr(axes, "_fv_calls", {}).items())),
        "artists": artists,
        "containers": described,
        "pies": pies,
        "legend": None if axes.legend_ is None else _legend(axes.legend_, figure),
    }


def _locate(siblings: list[Any], target: object) -> list[int] | None:
    for index, axes in enumerate(siblings):
        for position, child in enumerate(_children(axes)):
            if child is target:
                return [index, position]
    return None


def _shared(siblings: list[Any], axes: Any, grouper: Any) -> list[int]:
    return [
        i for i, other in enumerate(siblings) if other is not axes and grouper.joined(axes, other)
    ]


def _figure(figure: Any, run: _Run) -> dict[str, Any]:
    if len(figure.axes) > MAX_AXES or sum(len(_children(ax)) for ax in figure.axes) > MAX_CHILDREN:
        raise _TooLargeError
    axes = [_axes(ax, figure, run) for ax in figure.axes]
    supers = [figure._suptitle, figure._supxlabel, figure._supylabel]
    known = {id(figure.patch), *(id(a) for a in figure.axes), *(id(s) for s in supers)}
    known |= {id(legend) for legend in figure.legends} | {id(text) for text in figure.texts}
    return {
        "site": getattr(figure, "_fv_site", None),
        "titles": [_text(s) for s in supers],
        "texts": [
            t
            for t in (_text(text) for text in figure.texts if all(text is not s for s in supers))
            if t is not None
        ],
        "legends": [_legend(legend, figure) for legend in figure.legends],
        "others": [
            {
                "cls": type(child).__name__,
                "origin": getattr(child, "_fv_origin", None),
                "site": getattr(child, "_fv_site", None),
            }
            for child in figure.get_children()
            if id(child) not in known
        ],
        "axes": axes,
    }


def _error(exc: BaseException, kind: str) -> dict[str, Any]:
    line = getattr(exc, "lineno", None) if kind == "syntax" else None
    trace: TracebackType | None = exc.__traceback__
    while trace is not None:
        if trace.tb_frame.f_code.co_filename == PROGRAM:
            line = trace.tb_lineno
        trace = trace.tb_next
    return {"kind": kind, "name": type(exc).__name__, "line": line}


def _prepare(font: str | None) -> None:
    """Start from matplotlib's defaults: one runtime serves many replies."""
    mpl = importlib.import_module("matplotlib")
    mpl.rcdefaults()
    mpl.use("Agg")
    plt = importlib.import_module(_PYPLOT)
    plt.close("all")
    if font is not None:
        fonts = importlib.import_module("matplotlib.font_manager")
        fonts.fontManager.addfont(font)
        plt.rcParams["font.family"] = ["DejaVu Sans", fonts.FontProperties(fname=font).get_name()]


def run(source: str, font: str | None = None) -> str:
    """Run `source` as the chart program; return the description line, then one PNG line."""
    _prepare(font)
    holder = _holder()
    current = _Run()
    holder.run = current
    sink = io.StringIO()
    glyph_log = _GlyphLog(current)
    logging.getLogger(_MATHTEXT_LOG).addHandler(glyph_log)
    try:
        with (
            warnings.catch_warnings(record=True) as caught,
            contextlib.redirect_stdout(sink),
            contextlib.redirect_stderr(sink),
        ):
            warnings.simplefilter("always")
            try:
                code = compile(source, PROGRAM, "exec")
            except (SyntaxError, ValueError) as exc:  # ValueError: text UTF-8 cannot encode
                current.error = _error(exc, "syntax")
            else:
                try:
                    # Running the program IS the job (ruling 7: a non-adversarial program).
                    exec(code, {"__name__": "__main__"})  # noqa: S102
                except BaseException as exc:  # every outcome of the program is a fact to report
                    current.error = _error(exc, "exception")
            current.capture()
            current.glyphs += sum(_GLYPH.match(str(item.message)) is not None for item in caught)
    finally:
        holder.run = None
        logging.getLogger(_MATHTEXT_LOG).removeHandler(glyph_log)
    return _render(current)


def _render(current: _Run) -> str:
    description = {
        "version": VERSION,
        "error": current.error,
        "too_large": current.too_large,
        "glyphs": current.glyphs,
        "figures": [] if current.too_large else current.figures,
    }
    text = json.dumps(description, separators=(",", ":"), allow_nan=False)
    png = None if current.too_large or len(current.pngs) != 1 else current.pngs[0]
    if len(text.encode("utf-8")) > MAX_DESCRIPTION_BYTES or (
        png is not None and len(PNG_PREFIX) + len(png) > MAX_PNG_CHARACTERS
    ):
        description["too_large"] = True
        description["figures"] = []
        text = json.dumps(description, separators=(",", ":"))
        png = None
    return f"{TAG}{text}\n" + ("" if png is None else f"{PNG_PREFIX}{png}\n")
