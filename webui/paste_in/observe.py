# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Read a sandbox figure and compare its artists with the recomputed plotted table.

The sandbox reports data from the artist objects before PNG encoding. Rendering and the sandbox
remain trusted; a missing or uncertain observation withholds publication rather than admitting it.
"""

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import assert_never, cast

from verifier.pysrc.spec import Bin, Const, Expr, Fn, FormulaPlot, Neg, Num, Var
from verifier.pysrc.verify import Verified

OBSERVATION_TAG = "FIGURE_VERIFICATION_OBSERVATION:"
OBSERVATION_MAX_BYTES = 16_777_216
_PAIR_SIZE = 2
_PATCH_SIZE = 4

# The wrapper supplies plt. The literal plotting-package name cannot occur in this source:
# OWUI scans the RPC's whole code string for it and rewrites a match before execution.
OBSERVER_SOURCE = """\
import json as _fv_json


def _fv_hex(value):
    return float(value).hex()


def _fv_points(points):
    return [[_fv_hex(x), _fv_hex(y)] for x, y in points]


def _fv_axis(axis):
    units = axis.units
    mapping = getattr(units, "_mapping", None) if units is not None else None
    return {
        "units": None if mapping is None else [
            [str(key), _fv_hex(position)] for key, position in mapping.items()
        ],
        "ticks": [
            [_fv_hex(position), label.get_text()]
            for position, label in zip(axis.get_ticklocs(), axis.get_ticklabels())
        ],
    }


def _figure_verification_observe():
    fig = plt.gcf()
    axes = len(fig.axes)
    if axes:
        ax = fig.axes[0]
        lines = [_fv_points(line.get_xydata()) for line in ax.lines]
        collections = [_fv_points(item.get_offsets()) for item in ax.collections]
        containers = [
            [
                [_fv_hex(patch.get_x()), _fv_hex(patch.get_y()),
                 _fv_hex(patch.get_width()), _fv_hex(patch.get_height())]
                for patch in container.patches
            ]
            for container in ax.containers
            if type(container).__name__ == "BarContainer"
        ]
        contained = {id(patch) for container in ax.containers if hasattr(container, "patches")
                     for patch in container.patches}
        patches = sum(id(patch) not in contained for patch in ax.patches)
        images = len(ax.images)
        texts = len(ax.texts)
        xaxis = _fv_axis(ax.xaxis)
        yaxis = _fv_axis(ax.yaxis)
    else:
        lines, collections, containers = [], [], []
        patches = images = texts = 0
        xaxis = yaxis = {"units": None, "ticks": []}
    obj = {
        "axes": axes,
        "lines": lines,
        "collections": collections,
        "containers": containers,
        "patches": patches,
        "images": images,
        "texts": texts,
        "xaxis": xaxis,
        "yaxis": yaxis,
    }
    return _fv_json.dumps(obj, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
"""


type Point = tuple[float, float]
type Series = tuple[Point, ...]
type Patch = tuple[float, float, float, float]
type Interval = tuple[float, float]


@dataclass(frozen=True, slots=True)
class AxisObservation:
    units: tuple[tuple[str, float], ...] | None
    ticks: tuple[tuple[float, str], ...]


@dataclass(frozen=True, slots=True)
class Observation:
    axes: int
    lines: tuple[Series, ...]
    collections: tuple[Series, ...]
    containers: tuple[tuple[Patch, ...], ...]
    patches: int
    images: int
    texts: int
    xaxis: AxisObservation
    yaxis: AxisObservation


def _no_constant(value: str) -> None:
    raise ValueError(value)


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError
    return result


def _object(value: object, keys: frozenset[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise ValueError
    return value


def _array(value: object) -> list[object]:
    if type(value) is not list:
        raise ValueError
    return value


def _count(value: object) -> int:
    if type(value) is not int:
        raise ValueError
    return value


def _hex(value: object) -> float:
    if type(value) is not str:
        raise ValueError
    number = float.fromhex(value)
    if not math.isfinite(number):
        raise ValueError
    return number


def _text(value: object) -> str:
    if type(value) is not str:
        raise ValueError
    return value


def _pair[T, U](
    value: object, first: Callable[[object], T], second: Callable[[object], U]
) -> tuple[T, U]:
    values = _array(value)
    if len(values) != _PAIR_SIZE:
        raise ValueError
    return first(values[0]), second(values[1])


def _point(value: object) -> Point:
    return _pair(value, _hex, _hex)


def _patch(value: object) -> Patch:
    values = _array(value)
    if len(values) != _PATCH_SIZE:
        raise ValueError
    x, y, width, height = map(_hex, values)
    return x, y, width, height


def _axis(value: object) -> AxisObservation:
    axis = _object(value, frozenset({"units", "ticks"}))
    units = axis["units"]
    parsed_units = (
        None
        if units is None
        else tuple(
            (str(key), float(position))
            for key, position in (_pair(pair, _text, _hex) for pair in _array(units))
        )
    )
    ticks = tuple(
        (float(position), str(text))
        for position, text in (_pair(pair, _hex, _text) for pair in _array(axis["ticks"]))
    )
    return AxisObservation(units=parsed_units, ticks=ticks)


def parse_observation(stdout: str) -> Observation | None:
    """Accept exactly one tagged, bounded and fully typed observation from stdout."""
    lines = [line for line in stdout.splitlines() if line.startswith(OBSERVATION_TAG)]
    if len(lines) != 1:
        return None
    line = lines[0]
    try:
        if len(line.encode("utf-8")) > OBSERVATION_MAX_BYTES:
            return None
        obj = _object(
            json.loads(
                line[len(OBSERVATION_TAG) :],
                parse_constant=_no_constant,
                object_pairs_hook=_unique_keys,
            ),
            frozenset(
                {
                    "axes",
                    "lines",
                    "collections",
                    "containers",
                    "patches",
                    "images",
                    "texts",
                    "xaxis",
                    "yaxis",
                }
            ),
        )
        lines_ = tuple(
            tuple(_point(point) for point in _array(series)) for series in _array(obj["lines"])
        )
        collections = tuple(
            tuple(_point(point) for point in _array(series))
            for series in _array(obj["collections"])
        )
        containers = tuple(
            tuple(_patch(patch) for patch in _array(series)) for series in _array(obj["containers"])
        )
        return Observation(
            axes=_count(obj["axes"]),
            lines=lines_,
            collections=collections,
            containers=containers,
            patches=_count(obj["patches"]),
            images=_count(obj["images"]),
            texts=_count(obj["texts"]),
            xaxis=_axis(obj["xaxis"]),
            yaxis=_axis(obj["yaxis"]),
        )
    except (TypeError, ValueError, OverflowError, UnicodeEncodeError, RecursionError):
        return None


def _points_match(verified: Verified, points: Series, positions: tuple[float, ...] | None) -> bool:
    if positions is None or len(points) != len(verified.table.y):
        return False
    return all(
        observed_x == expected_x and observed_y == expected_y
        for (observed_x, observed_y), expected_x, expected_y in zip(
            points, positions, verified.table.y, strict=True
        )
    )


def _direct_points(verified: Verified, axis: AxisObservation, points: Series) -> bool:
    positions = (
        _categorical(axis, verified.table.x)
        if axis.units is not None
        else _numeric(axis, verified.table.x)
    )
    return _points_match(verified, points, positions)


def _line_points(verified: Verified, axis: AxisObservation, points: Series) -> bool:
    # String keys with no category units = pandas' line accessor, which never engages the category
    # converter and draws at 0..n-1 instead (measured on the installed bundle, M10.10).
    keys = verified.table.x
    if axis.units is None and all(isinstance(key, str) for key in keys):
        return _points_match(verified, points, _positional(axis, keys))
    return _direct_points(verified, axis, points)


def _line(verified: Verified, observation: Observation) -> bool:
    if len(observation.lines) != 1 or observation.collections or observation.containers:
        return False
    return (
        _formula(verified, observation)
        if isinstance(verified.spec, FormulaPlot)
        else _line_points(verified, observation.xaxis, observation.lines[0])
    )


def _scatter(verified: Verified, observation: Observation) -> bool:
    if len(observation.collections) != 1 or observation.lines or observation.containers:
        return False
    return (
        _formula(verified, observation)
        if isinstance(verified.spec, FormulaPlot)
        else _direct_points(verified, observation.xaxis, observation.collections[0])
    )


def _categorical(axis: AxisObservation, keys: tuple[float | str, ...]) -> tuple[float, ...] | None:
    if axis.units is None or any(not isinstance(key, str) for key in keys):
        return None
    mapping = dict(axis.units)
    if len(mapping) != len(axis.units):
        return None
    positions: list[float] = []
    for key in keys:
        found = mapping.get(cast("str", key))
        if found is None:
            return None
        positions.append(found)
    return tuple(positions)


def _numeric(axis: AxisObservation, keys: tuple[float | str, ...]) -> tuple[float, ...] | None:
    if axis.units is not None or any(not isinstance(key, float) for key in keys):
        return None
    return cast("tuple[float, ...]", keys)


def _tick_matches(text: str, key: float | str) -> bool:
    if isinstance(key, str):
        return text == key
    try:
        numeric = float(text)
    except ValueError:
        return False
    return math.isfinite(numeric) and numeric == key


def _accessor(axis: AxisObservation, keys: tuple[float | str, ...]) -> tuple[float, ...] | None:
    if axis.units is not None:
        return None
    ticks = dict(axis.ticks)
    if len(ticks) != len(axis.ticks):
        return None
    positions: list[float] = []
    for index, key in enumerate(keys):
        position = float(index)
        text = ticks.get(position)
        if text is None or not _tick_matches(text, key):
            return None
        positions.append(position)
    return tuple(positions)


def _positional(axis: AxisObservation, keys: tuple[float | str, ...]) -> tuple[float, ...] | None:
    """pandas labels each integral tick `index[int(p)]`: a negative one WRAPS to a tail key and an
    in-range position may carry no tick at all (n=2 labels 0 alone), so only the in-range integral
    ticks are read -- and at least one must be, or no label binds a key to a position."""
    labelled = [
        (position, text)
        for position, text in axis.ticks
        if position.is_integer() and 0 <= position < len(keys)
    ]
    if not labelled or any(text != keys[int(position)] for position, text in labelled):
        return None
    return tuple(float(index) for index in range(len(keys)))


type _Position = Callable[[AxisObservation, tuple[float | str, ...]], tuple[float, ...] | None]
type _BarMode = tuple[_Position, float]


def _bar_mode(
    verified: Verified,
    axis: AxisObservation,
    patches: tuple[Patch, ...],
    mode: _BarMode,
    *,
    horizontal: bool,
) -> bool:
    if len(patches) != len(verified.table.y):
        return False
    position, span = mode
    positions = position(axis, verified.table.x)
    if positions is None:
        return False
    for patch, expected_position, magnitude in zip(
        patches, positions, verified.table.y, strict=True
    ):
        x, y, width, height = patch
        observed_edge, base = (y, x) if horizontal else (x, y)
        extent, observed_magnitude = (height, width) if horizontal else (width, height)
        if (
            base != 0.0
            or extent != span
            or observed_edge != expected_position - span / 2
            or observed_magnitude != magnitude
        ):
            return False
    return True


def _bars(verified: Verified, observation: Observation, *, horizontal: bool) -> bool:
    if observation.lines or observation.collections or len(observation.containers) != 1:
        return False
    axis = observation.yaxis if horizontal else observation.xaxis
    patches = observation.containers[0]
    numeric_x = verified.table.x[0] if verified.table.x else None
    numeric_span = (numeric_x + 0.8) - numeric_x if isinstance(numeric_x, float) else 0.8
    modes: tuple[_BarMode, ...] = ((_categorical, 0.8), (_numeric, numeric_span), (_accessor, 0.5))
    return any(_bar_mode(verified, axis, patches, mode, horizontal=horizontal) for mode in modes)


def _bar(verified: Verified, observation: Observation) -> bool:
    return _bars(verified, observation, horizontal=False)


def _barh(verified: Verified, observation: Observation) -> bool:
    return _bars(verified, observation, horizontal=True)


def _finite(bounds: Interval) -> Interval | None:
    return bounds if math.isfinite(bounds[0]) and math.isfinite(bounds[1]) else None


def _outward(low: float, high: float) -> Interval | None:
    return _finite((math.nextafter(low, -math.inf), math.nextafter(high, math.inf)))


def _arithmetic(op: str, left: float, right: float) -> float:
    if op == "add":
        return left + right
    if op == "sub":
        return left - right
    if op == "mul":
        return left * right
    if op == "div":
        return left / right
    raise ValueError


def _may_contain(low: float, high: float, offset: float, period: float) -> list[int]:
    """Every k for which `offset + k * period` MAY lie in [low, high], judged conservatively.

    Callers pass a span below two periods, so the scan stays a handful of candidates.
    """
    first = math.floor((low - offset) / period) - 1
    found = []
    for k in range(first, first + 4 + math.ceil((high - low) / period)):
        point = offset + k * period
        slack = 4.0 * (math.ulp(point) + abs(k) * math.ulp(period))
        if low - slack <= point <= high + slack:
            found.append(k)
    return found


def _extremum_interval(name: str, low: float, high: float) -> Interval | None:
    """sin/cos over [low, high]: the endpoint values plus every extremum the interval may hold."""
    if high - low >= 2.0 * math.pi:
        return _outward(-1.0, 1.0)
    function = math.sin if name == "sin" else math.cos
    values = [function(low), function(high)]
    if low != high:  # a point argument keeps today's interval: the value, 1 ulp outward
        # A maximum (+1) sits at sin's pi/2 + 2k*pi and cos's 2k*pi; a minimum (-1) half a turn on.
        offset = math.pi / 2.0 if name == "sin" else 0.0
        values += [1.0 if k % 2 == 0 else -1.0 for k in _may_contain(low, high, offset, math.pi)]
    return _outward(min(values), max(values))


def _monotone_interval(name: str, low: float, high: float) -> Interval | None:
    """exp, log, tan over [low, high]: each is increasing on the admitted span; `math.log` raises
    at or below zero, which withholds."""
    if (
        name == "tan"
        and low != high
        and (high - low >= math.pi or _may_contain(low, high, math.pi / 2.0, math.pi))
    ):
        return None  # a pole may sit inside: tan is not monotone across it
    function = getattr(math, name)
    try:
        return _outward(function(low), function(high))
    except (OverflowError, ValueError):
        return None


def _function_interval(expr: Fn, argument: Interval) -> Interval | None:
    low, high = argument
    if expr.name == "abs":
        if low <= 0.0 <= high:
            return 0.0, max(-low, high)
        return min(abs(low), abs(high)), max(abs(low), abs(high))
    if expr.name == "sqrt":
        return _finite((math.sqrt(low), math.sqrt(high))) if low >= 0.0 else None
    if expr.name in ("sin", "cos"):
        return _extremum_interval(expr.name, low, high)
    return _monotone_interval(expr.name, low, high)


def _integer_power(base: Interval, exponent: int) -> Interval | None:
    """An interval base to a point integer exponent: monotone on each side of zero."""
    low, high = base
    if exponent == 0:
        return 1.0, 1.0
    if low <= 0.0 <= high and exponent < 0:
        return None  # a pole inside the base
    try:
        ends = (math.pow(low, exponent), math.pow(high, exponent))
    except (OverflowError, ValueError):
        return None
    if exponent % 2 == 0 and low <= 0.0 <= high:
        return _finite((0.0, math.nextafter(max(ends), math.inf)))
    return _outward(min(ends), max(ends))


def _power_interval(left: Interval, right: Interval) -> Interval | None:
    if right[0] != right[1]:
        return None
    if left[0] != left[1]:
        if not right[0].is_integer():
            return None
        return _integer_power(left, int(right[0]))
    try:
        value = math.pow(left[0], right[0])
    except (OverflowError, ValueError):
        return None
    return _outward(value, value) if math.isfinite(value) else None


def _binary_interval(expr: Bin, left: Interval, right: Interval) -> Interval | None:
    if expr.op == "pow":
        return _power_interval(left, right)
    if expr.op == "div" and right[0] <= 0.0 <= right[1]:
        return None
    values = [_arithmetic(expr.op, a, b) for a in left for b in right]
    if not all(math.isfinite(value) for value in values):
        return None
    if left[0] == left[1] and right[0] == right[1]:
        return min(values), max(values)
    return _outward(min(values), max(values))


def _interval(expr: Expr, x: float) -> Interval | None:
    """Conservatively enclose a formula's float64 result at one already verified x."""
    if isinstance(expr, (Num, Var, Const)):
        if isinstance(expr, Num):
            value = float(expr.value)
        elif isinstance(expr, Var):
            value = x
        else:
            value = math.pi if expr.name == "pi" else math.e
        return _finite((value, value))
    if isinstance(expr, Neg):
        argument = _interval(expr.operand, x)
        return (-argument[1], -argument[0]) if argument is not None else None
    if isinstance(expr, Fn):
        argument = _interval(expr.arg, x)
        return _function_interval(expr, argument) if argument is not None else None
    if isinstance(expr, Bin):
        left, right = _interval(expr.left, x), _interval(expr.right, x)
        return (
            _binary_interval(expr, left, right) if left is not None and right is not None else None
        )
    assert_never(expr)  # pragma: no cover - projected Expr is closed


def _formula(verified: Verified, observation: Observation) -> bool:
    if not isinstance(verified.spec, FormulaPlot):
        return False
    points = observation.lines[0] if verified.spec.mark == "line" else observation.collections[0]
    if len(points) != len(verified.table.y):
        return False
    for (x, y), expected_x in zip(points, verified.table.x, strict=True):
        if not isinstance(expected_x, float) or x != expected_x:
            return False
        bounds = _interval(verified.spec.y, expected_x)
        if bounds is None or not bounds[0] <= y <= bounds[1]:
            return False
    return True


READERS: dict[str, Callable[[Verified, Observation], bool]] = {
    "line": _line,
    "scatter": _scatter,
    "bar": _bar,
    "barh": _barh,
}


def observation_matches(verified: Verified, observation: Observation) -> bool:
    """Withhold on unknown marks, artist inventory mismatches or uncertain comparisons."""
    if (
        observation.axes != 1
        or observation.patches != 0
        or observation.images != 0
        or observation.texts != 0
    ):
        return False
    mark = verified.spec.mark
    return mark in READERS and READERS[mark](verified, observation)
