# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Contract-derived observation reader and comparator, independent of the outlet filter."""

from __future__ import annotations

import json
import math
from fractions import Fraction
from typing import cast

from verifier.pysrc import spec
from verifier.pysrc.verify import Verified

_TAG = "FIGURE_VERIFICATION_OBSERVATION:"
_MAX_BYTES = 16_777_216
_FIELDS = frozenset(
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
)
_AXIS_FIELDS = frozenset({"units", "ticks"})
_ARTISTS = {"line": "lines", "scatter": "collections", "bar": "containers", "barh": "containers"}

type Pair = tuple[float, float]
type Box = tuple[float, float, float, float]
type Axis = dict[str, object]
type Observation = dict[str, object]
type Range = tuple[float, float]


def _invalid() -> ValueError:
    return ValueError("observation does not have the contract's wire shape")


def _number(value: object) -> float:
    if type(value) is not str:
        raise _invalid()
    result = float.fromhex(value)
    if not math.isfinite(result):
        raise _invalid()
    return result


def _rows(raw: object, width: int) -> tuple[tuple[float, ...], ...]:
    if not isinstance(raw, list):
        raise _invalid()
    rows: list[tuple[float, ...]] = []
    for row in raw:
        if not isinstance(row, list) or len(row) != width:
            raise _invalid()
        rows.append(tuple(_number(value) for value in row))
    return tuple(rows)


def _artists(raw: object, width: int) -> tuple[tuple[tuple[float, ...], ...], ...]:
    if not isinstance(raw, list):
        raise _invalid()
    return tuple(_rows(artist, width) for artist in raw)


def _axis(raw: object) -> Axis:
    if not isinstance(raw, dict) or raw.keys() != _AXIS_FIELDS:
        raise _invalid()
    units_raw = raw["units"]
    units: tuple[tuple[str, float], ...] | None = None
    if units_raw is not None:
        if not isinstance(units_raw, list):
            raise _invalid()
        mappings: list[tuple[str, float]] = []
        for item in units_raw:
            if not isinstance(item, list) or len(item) != 2 or type(item[0]) is not str:
                raise _invalid()
            mappings.append((item[0], _number(item[1])))
        units = tuple(mappings)
    ticks_raw = raw["ticks"]
    if not isinstance(ticks_raw, list):
        raise _invalid()
    ticks: list[tuple[float, str]] = []
    for item in ticks_raw:
        if not isinstance(item, list) or len(item) != 2 or type(item[1]) is not str:
            raise _invalid()
        ticks.append((_number(item[0]), item[1]))
    return {"units": units, "ticks": tuple(ticks)}


def _reject_constant(_value: str) -> None:
    raise _invalid()


def oracle_parse(stdout: str) -> Observation | None:
    """Read exactly one bounded tagged JSON line into a canonical value-only representation."""
    try:
        tagged = [line for line in stdout.splitlines() if line.startswith(_TAG)]
        if len(tagged) != 1 or len(tagged[0].encode("utf-8")) > _MAX_BYTES:
            return None
        value: object = json.loads(tagged[0][len(_TAG) :], parse_constant=_reject_constant)
        if not isinstance(value, dict) or value.keys() != _FIELDS:
            return None
        counts = (value["axes"], value["patches"], value["images"], value["texts"])
        if any(type(count) is not int for count in counts):
            return None
        return {
            "axes": value["axes"],
            "lines": _artists(value["lines"], 2),
            "collections": _artists(value["collections"], 2),
            "containers": _artists(value["containers"], 4),
            "patches": value["patches"],
            "images": value["images"],
            "texts": value["texts"],
            "xaxis": _axis(value["xaxis"]),
            "yaxis": _axis(value["yaxis"]),
        }
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError):
        return None


def _steps(value: float) -> Range | None:
    if not math.isfinite(value):
        return None
    lower, upper = math.nextafter(value, -math.inf), math.nextafter(value, math.inf)
    if not (math.isfinite(lower) and math.isfinite(upper)):
        return None
    return (lower, upper)


def _finite_range(lower: float, upper: float) -> Range | None:
    if not (math.isfinite(lower) and math.isfinite(upper)):
        return None
    return (lower, upper)


def _fraction(value: Fraction) -> Range | None:
    try:
        number = float(value)
    except OverflowError:
        return None
    return _finite_range(number, number)


def _binary(op: str, left: float, right: float) -> float:
    if op == "add":
        return left + right
    if op == "sub":
        return left - right
    if op == "mul":
        return left * right
    if op == "div":
        return left / right
    if op == "pow":
        return math.pow(left, right)
    raise ValueError(op)


def _arithmetic(op: str, left: Range, right: Range) -> Range | None:
    if op == "div" and right[0] <= 0.0 <= right[1]:
        return None
    if op == "pow":
        if left[0] != left[1] or right[0] != right[1]:
            return None
        return _steps(_binary(op, left[0], right[0]))
    if left[0] == left[1] and right[0] == right[1]:
        point = _binary(op, left[0], right[0])
        return _finite_range(point, point)
    results = [_binary(op, a, b) for a in left for b in right]
    return _finite_range(
        math.nextafter(min(results), -math.inf), math.nextafter(max(results), math.inf)
    )


def _function(name: str, argument: Range) -> Range | None:
    lower, upper = argument
    if name == "abs":
        return _finite_range(
            0.0 if lower <= 0.0 <= upper else min(abs(lower), abs(upper)),
            max(abs(lower), abs(upper)),
        )
    if name == "sqrt":
        if lower < 0.0:
            return None
        return _finite_range(math.sqrt(lower), math.sqrt(upper))
    if lower != upper:
        return None
    if name == "sin":
        result = math.sin(lower)
    elif name == "cos":
        result = math.cos(lower)
    elif name == "tan":
        result = math.tan(lower)
    elif name == "exp":
        result = math.exp(lower)
    elif name == "log":
        result = math.log(lower)
    else:
        raise ValueError(name)
    return _steps(result)


def oracle_interval(expression: spec.Expr, x: float) -> Range | None:  # noqa: PLR0911
    """Host binary64 interval; point arithmetic stays a point until libm widens it."""
    try:
        if type(expression) is spec.Num:
            return _fraction(expression.value)
        if type(expression) is spec.Var:
            return _finite_range(x, x)
        if type(expression) is spec.Const:
            point = math.pi if expression.name == "pi" else math.e
            if expression.name not in {"pi", "e"}:
                return None
            return (point, point)
        if type(expression) is spec.Neg:
            value = oracle_interval(expression.operand, x)
            return None if value is None else _finite_range(-value[1], -value[0])
        if type(expression) is spec.Fn:
            argument = oracle_interval(expression.arg, x)
            return None if argument is None else _function(expression.name, argument)
        if type(expression) is spec.Bin:
            left = oracle_interval(expression.left, x)
            right = oracle_interval(expression.right, x)
            return (
                None if left is None or right is None else _arithmetic(expression.op, left, right)
            )
    except (ValueError, OverflowError, ZeroDivisionError):
        return None
    return None


def _axis_units(axis: Axis) -> tuple[tuple[str, float], ...] | None:
    return cast("tuple[tuple[str, float], ...] | None", axis["units"])


def _axis_ticks(axis: Axis) -> tuple[tuple[float, str], ...]:
    return cast("tuple[tuple[float, str], ...]", axis["ticks"])


def _direct_x(x: float | str, actual: float, axis: Axis) -> bool:
    if isinstance(x, float):
        return x == actual
    units = _axis_units(axis)
    return units is not None and any(key == x and position == actual for key, position in units)


def _tick_identity(x: float | str, position: float, axis: Axis) -> bool:
    for tick_position, text in _axis_ticks(axis):
        if tick_position != position:
            continue
        if isinstance(x, str) and text == x:
            return True
        if isinstance(x, float):
            try:
                number = float(text)
            except ValueError:
                continue
            if math.isfinite(number) and number == x:
                return True
    return False


def _bound_bar(  # noqa: PLR0911, PLR0912
    mark: str,
    patches: tuple[Box, ...],
    verified: Verified,
    axis: Axis,
    mode: str,
) -> bool:
    x_values, y_values = verified.table.x, verified.table.y
    units = _axis_units(axis)
    if mode == "categorical":
        if units is None or any(not isinstance(key, str) for key in x_values):
            return False
        span = 0.8
    elif mode == "numeric":
        if units is not None or any(not isinstance(key, float) for key in x_values):
            return False
        first = cast(float, x_values[0])
        span = (first + 0.8) - first
    elif mode == "accessor":
        if units is not None:
            return False
        span = 0.5
    else:
        return False

    for index, (patch, key, expected_y) in enumerate(zip(patches, x_values, y_values, strict=True)):
        if mode == "categorical":
            assert units is not None
            choices = [position for name, position in units if name == key]
            if not choices:
                return False
            position = choices[0]
        elif mode == "numeric":
            position = cast(float, key)
        else:
            position = float(index)
            if not _tick_identity(key, position, axis):
                return False
        edge, base, extent, magnitude = (
            (patch[0], patch[1], patch[2], patch[3])
            if mark == "bar"
            else (patch[1], patch[0], patch[3], patch[2])
        )
        if not (
            magnitude == expected_y
            and base == 0.0
            and extent == span
            and edge == position - span / 2
        ):
            return False
    return True


def oracle_matches(verified: Verified, observation: Observation) -> bool:  # noqa: PLR0911
    """One observed artist, then its mark-specific binding to the recomputed table."""
    try:
        mark = verified.spec.mark
        artist_name = _ARTISTS.get(mark)
        if artist_name is None:
            return False
        if not (
            observation["axes"] == 1
            and observation["patches"] == 0
            and observation["images"] == 0
            and observation["texts"] == 0
            and all(
                len(cast("tuple[object, ...]", observation[name]))
                == (1 if name == artist_name else 0)
                for name in ("lines", "collections", "containers")
            )
        ):
            return False
        artists = cast("tuple[tuple[tuple[float, ...], ...], ...]", observation[artist_name])
        points = artists[0]
        table = verified.table
        if len(points) != len(table.y) or not table.y:
            return False
        if mark in {"line", "scatter"}:
            x_axis = cast(Axis, observation["xaxis"])
            for x, y, point in zip(table.x, table.y, points, strict=True):
                actual_x, actual_y = point
                if isinstance(verified.spec, spec.FormulaPlot):
                    interval = oracle_interval(verified.spec.y, cast(float, x))
                    if interval is None or not (
                        x == actual_x and interval[0] <= actual_y <= interval[1]
                    ):
                        return False
                elif not (_direct_x(x, actual_x, x_axis) and y == actual_y):
                    return False
            return True
        if not isinstance(verified.spec, spec.DatasetPlot):
            return False
        position_axis = cast(Axis, observation["xaxis" if mark == "bar" else "yaxis"])
        boxes = cast("tuple[Box, ...]", points)
        return any(
            _bound_bar(mark, boxes, verified, position_axis, mode)
            for mode in ("categorical", "numeric", "accessor")
        )
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return False
