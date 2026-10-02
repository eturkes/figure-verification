# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q18 I1-I9: hand-derived intervals; the observation implementation stays unread."""

from __future__ import annotations

import math
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from verifier.pysrc import spec
from webui.paste_in import observe

type Range = tuple[float, float]


def _num(value: float) -> spec.Num:
    return spec.Num(Fraction(value))


def _outward(lower: float, upper: float) -> Range:
    return (math.nextafter(lower, -math.inf), math.nextafter(upper, math.inf))


def _band(point: float) -> tuple[spec.Expr, Range]:
    # A point power's one-ulp enclosure supplies a non-point argument without a mock.
    return spec.Bin("pow", _num(point), _num(1.0)), _outward(point, point)


def _wide(scale: float = 1e16, center: float = 0.0) -> tuple[spec.Expr, Range]:
    argument, (lower, upper) = _band(scale)
    expression: spec.Expr = spec.Bin("sub", argument, _num(scale))
    lower, upper = _outward(lower - scale, upper - scale)
    if center != 0.0:
        expression = spec.Bin("add", expression, _num(center))
        lower, upper = _outward(lower + center, upper + center)
    return expression, (lower, upper)


def _actual(expression: spec.Expr, x: float = 0.0) -> Range | None:
    assert Path(observe.__file__).resolve() == (
        Path(__file__).resolve().parents[1] / "webui/paste_in/observe.py"
    )
    return observe._interval(expression, x)


@pytest.mark.parametrize("point", (-745.0, -4.0, 0.3, 709.0, 710.0))
def test_i1_exp_interval_endpoints_and_nonfinite_refusal(point: float) -> None:
    """I1: exp is monotone, widens both endpoints, and refuses overflow."""
    expression, (lower, upper) = _band(point)
    expected = None if point == 710.0 else _outward(math.exp(lower), math.exp(upper))
    assert _actual(spec.Fn("exp", expression)) == expected


@pytest.mark.parametrize("point", (-1.0, 0.0, 0.2, 1.0))
def test_i2_log_positive_domain_and_zero_boundary(point: float) -> None:
    """I2: a lower endpoint equal to zero is outside log's domain."""
    expression, (lower, upper) = _band(point)
    if point == 0.0:
        expression = spec.Fn("abs", expression)
        lower = 0.0
    expected = None if lower <= 0.0 else _outward(math.log(lower), math.log(upper))
    assert _actual(spec.Fn("log", expression)) == expected


@pytest.mark.parametrize("case", ("positive", "zero-lower", "negative-lower", "negative"))
def test_i3_sqrt_correct_rounding_and_domain_unchanged(case: str) -> None:
    """I3: sqrt does not widen; lo = 0 releases, lo < 0 withholds."""
    expression, (lower, upper) = _band(
        4.0 if case == "positive" else -1.0 if case == "negative" else 0.0
    )
    if case == "zero-lower":
        expression = spec.Fn("abs", expression)
        lower = 0.0
    expected = None if lower < 0.0 else (math.sqrt(lower), math.sqrt(upper))
    assert _actual(spec.Fn("sqrt", expression)) == expected


@pytest.mark.parametrize("case", ("endpoint", "maximum", "minimum", "both", "full-period"))
def test_i4_sin_interval_extrema_and_full_period(case: str) -> None:
    """I4: interior extrema bind even when neither endpoint attains them."""
    if case == "endpoint":
        expression, (lower, upper) = _band(0.3)
        expected = _outward(math.sin(lower), math.sin(upper))
    else:
        expression, (lower, upper) = _wide(
            2e16 if case == "full-period" else 1e16,
            math.pi / 2 if case == "maximum" else -math.pi / 2 if case == "minimum" else 0.0,
        )
        endpoints = (math.sin(lower), math.sin(upper))
        expected = _outward(
            -1.0 if case in {"minimum", "both", "full-period"} else min(endpoints),
            1.0 if case in {"maximum", "both", "full-period"} else max(endpoints),
        )
    assert _actual(spec.Fn("sin", expression)) == expected


@pytest.mark.parametrize("case", ("endpoint", "maximum", "minimum", "both", "full-period"))
def test_i5_cos_interval_extrema_and_full_period(case: str) -> None:
    """I5: +1 at 0 and -1 at pi are independent extrema, not endpoint samples."""
    if case == "endpoint":
        expression, (lower, upper) = _band(0.3)
        expected = _outward(math.cos(upper), math.cos(lower))
    else:
        expression, (lower, upper) = _wide(
            2e16 if case == "full-period" else 1e16,
            math.pi if case == "minimum" else math.pi / 2 if case == "both" else 0.0,
        )
        endpoints = (math.cos(lower), math.cos(upper))
        expected = _outward(
            -1.0 if case in {"minimum", "both", "full-period"} else min(endpoints),
            1.0 if case in {"maximum", "both", "full-period"} else max(endpoints),
        )
    assert _actual(spec.Fn("cos", expression)) == expected


@pytest.mark.parametrize(
    "point",
    (
        -0.3,
        0.3,
        math.pi / 2 - 1e-10,
        math.pi / 2 + 1e-10,
        math.nextafter(math.pi / 2, -math.inf),
        math.pi / 2,
        math.nextafter(math.pi / 2, math.inf),
        -math.pi / 2,
    ),
)
def test_i6_tan_safe_branch_and_possible_pole(point: float) -> None:
    """I6: endpoint poles and one-ulp uncertainty withhold; separated branches release."""
    expression, (lower, upper) = _band(point)
    possible_pole = point in {
        math.nextafter(math.pi / 2, -math.inf),
        math.pi / 2,
        math.nextafter(math.pi / 2, math.inf),
        -math.pi / 2,
    }
    expected = None if possible_pole else _outward(math.tan(lower), math.tan(upper))
    assert _actual(spec.Fn("tan", expression)) == expected


def test_i6_tan_interval_spanning_poles_withholds() -> None:
    expression, (lower, upper) = _wide()
    assert lower < -math.pi / 2 < math.pi / 2 < upper
    assert _actual(spec.Fn("tan", expression)) is None


@pytest.mark.parametrize(
    ("base", "exponent"),
    (
        (2.0, 0.0),
        (2.0, 1.0),
        (2.0, 3.0),
        (-2.0, 3.0),
        (2.0, 2.0),
        (-2.0, 2.0),
        (0.0, 2.0),
        (2.0, -2.0),
        (-2.0, -3.0),
        (0.0, -2.0),
        (2.0, 1.5),
    ),
)
def test_i7_interval_base_point_integer_exponent(base: float, exponent: float) -> None:
    """I7: integer signs/parity determine the enclosure; non-integers withhold."""
    expression, (lower, upper) = _wide() if base == 0.0 else _band(base)
    expected: Range | None
    if not exponent.is_integer() or (exponent < 0.0 and lower <= 0.0 <= upper):
        expected = None
    elif exponent == 0.0:
        expected = (1.0, 1.0)
    else:
        endpoints = (math.pow(lower, exponent), math.pow(upper, exponent))
        expected = (
            (0.0, math.nextafter(max(endpoints), math.inf))
            if exponent > 0.0 and int(exponent) % 2 == 0 and lower <= 0.0 <= upper
            else _outward(min(endpoints), max(endpoints))
        )
    assert _actual(spec.Bin("pow", expression, _num(exponent))) == expected


@pytest.mark.parametrize("sign", (-1, 1))
@pytest.mark.parametrize("exponent", (0.0, 2.0, 4.0, -2.0, -3.0))
def test_i7_zero_touch_even_power_and_negative_power(sign: int, exponent: float) -> None:
    """I7: zero at either endpoint has the same exact-zero/refusal rule as a crossing."""
    expression, (lower, upper) = _wide()
    expression = spec.Fn("abs", expression)
    edge = max(-lower, upper)
    if sign < 0:
        expression = spec.Neg(expression)
    expected: Range | None
    if exponent < 0.0:
        expected = None
    elif exponent == 0.0:
        expected = (1.0, 1.0)
    else:
        expected = (0.0, math.nextafter(math.pow(edge, exponent), math.inf))
    assert _actual(spec.Bin("pow", expression, _num(exponent))) == expected


@pytest.mark.parametrize(("base", "exponent"), ((1e200, 2.0), (-1e200, 3.0), (1e-200, -2.0)))
def test_i7_nonfinite_endpoint_withholds(base: float, exponent: float) -> None:
    expression, _ = _band(base)
    assert _actual(spec.Bin("pow", expression, _num(exponent))) is None


@pytest.mark.parametrize("base", (2.0, 0.0))
def test_i7_nonpoint_exponent_withholds(base: float) -> None:
    expression, _ = _band(base)
    exponent, _ = _band(2.0)
    assert _actual(spec.Bin("pow", expression, exponent)) is None


@pytest.mark.parametrize(("base", "exponent"), ((2.0, 1.3), (-2.0, 3.0), (0.0, 0.0)))
def test_i7_point_power_no_regression(base: float, exponent: float) -> None:
    result = math.pow(base, exponent)
    assert _actual(spec.Bin("pow", _num(base), _num(exponent))) == _outward(result, result)


def test_i8_arithmetic_abs_neg_and_atomic_no_regression() -> None:
    """I8: ordinary point arithmetic stays exact; interval arithmetic widens once."""
    expression, (lower, upper) = _wide()
    assert _actual(spec.Var(), -0.0) == (-0.0, -0.0)
    assert _actual(_num(0.2)) == (0.2, 0.2)
    assert _actual(spec.Const("pi")) == (math.pi, math.pi)
    assert _actual(spec.Const("e")) == (math.e, math.e)
    assert _actual(spec.Neg(expression)) == (-upper, -lower)
    assert _actual(spec.Fn("abs", expression)) == (0.0, max(-lower, upper))
    assert _actual(spec.Bin("add", expression, _num(3.0))) == _outward(lower + 3.0, upper + 3.0)
    assert _actual(spec.Bin("sub", expression, _num(3.0))) == _outward(lower - 3.0, upper - 3.0)
    assert _actual(spec.Bin("mul", expression, _num(-2.0))) == _outward(-2.0 * upper, -2.0 * lower)
    assert _actual(spec.Bin("div", expression, _num(2.0))) == _outward(lower / 2.0, upper / 2.0)
    assert _actual(spec.Bin("div", _num(1.0), expression)) is None
    operations: tuple[tuple[spec.BinOp, float], ...] = (
        ("add", 5.0),
        ("sub", -1.0),
        ("mul", 6.0),
        ("div", 2.0 / 3.0),
    )
    for op, expected in operations:
        assert _actual(spec.Bin(op, _num(2.0), _num(3.0))) == (expected, expected)


@pytest.mark.parametrize(
    ("name", "point"),
    (
        ("sin", 0.0),
        ("sin", math.pi / 2),
        ("cos", 0.0),
        ("cos", math.pi),
        ("tan", 0.0),
        ("tan", math.pi / 2),
        ("exp", 0.0),
        ("exp", -745.0),
        ("log", 1.0),
        ("log", math.nextafter(0.0, math.inf)),
        ("sqrt", 0.0),
        ("sqrt", 4.0),
        ("abs", -3.0),
    ),
)
def test_i9_point_function_arguments_no_regression(name: spec.FnName, point: float) -> None:
    """I9: a point libm call keeps its old one-ulp band, including point tan(pi/2)."""
    functions: dict[spec.FnName, Callable[[float], float]] = {
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "exp": math.exp,
        "log": math.log,
        "sqrt": math.sqrt,
        "abs": abs,
    }
    result = functions[name](point)
    expected = (result, result) if name in {"sqrt", "abs"} else _outward(result, result)
    assert _actual(spec.Fn(name, spec.Var()), point) == expected


@pytest.mark.parametrize(("name", "point"), (("log", 0.0), ("sqrt", -1.0), ("exp", 710.0)))
def test_i9_point_function_error_paths_no_regression(name: spec.FnName, point: float) -> None:
    assert _actual(spec.Fn(name, spec.Var()), point) is None


def test_i8_nonfinite_variable_and_point_power_domain_withhold() -> None:
    for value in (math.inf, -math.inf, math.nan):
        assert _actual(spec.Var(), value) is None
    assert _actual(spec.Bin("pow", _num(-2.0), _num(0.5))) is None


@given(point=st.floats(min_value=1e-100, max_value=100.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=64, deadline=None)
def test_i1_i2_i3_monotone_enclosure_property(point: float) -> None:
    """Positive interval endpoints determine exp/log/sqrt over the generated domain."""
    expression, (lower, upper) = _band(point)
    functions: tuple[tuple[spec.FnName, Callable[[float], float]], ...] = (
        ("exp", math.exp),
        ("log", math.log),
        ("sqrt", math.sqrt),
    )
    for name, function in functions:
        expected = (function(lower), function(upper))
        if name != "sqrt":
            expected = _outward(*expected)
        assert _actual(spec.Fn(name, expression)) == expected


@given(
    base=st.floats(min_value=-20.0, max_value=20.0, allow_nan=False, allow_infinity=False),
    exponent=st.integers(min_value=-5, max_value=5),
)
@settings(max_examples=96, deadline=None)
def test_i7_integer_power_enclosure_property(base: float, exponent: int) -> None:
    """I7 parity/sign rule holds beyond the hand-chosen basis values."""
    expression, (lower, upper) = _band(base)
    expected: Range | None
    if exponent < 0 and lower <= 0.0 <= upper:
        expected = None
    elif exponent == 0:
        expected = (1.0, 1.0)
    else:
        try:
            endpoints = (math.pow(lower, exponent), math.pow(upper, exponent))
            expected = (
                (0.0, math.nextafter(max(endpoints), math.inf))
                if exponent > 0 and exponent % 2 == 0 and lower <= 0.0 <= upper
                else _outward(min(endpoints), max(endpoints))
            )
            if not all(math.isfinite(value) for value in expected):
                expected = None
        except OverflowError:
            expected = None
    assert _actual(spec.Bin("pow", expression, _num(float(exponent)))) == expected


def test_i7_negative_power_over_a_base_straddling_zero_withholds() -> None:
    """I7 (MAIN, from the mutation run): a base interval holding zero STRICTLY inside -- here
    `sin(x) - sin(x)`, about +-2 ulp of zero -- under a negative integer exponent withholds; the
    endpoint powers alone are finite and would hide the pole between them."""
    sine = spec.Fn("sin", spec.Var())
    straddling = spec.Bin("sub", sine, sine)
    base = _actual(straddling, 1.0)
    assert base is not None
    assert base[0] < 0.0 < base[1]
    assert _actual(spec.Bin("pow", straddling, _num(-2.0)), 1.0) is None


def test_i7_a_point_base_with_an_interval_exponent_withholds() -> None:
    """I7 (MAIN, from the mutation run): `2 ** sin(x)` has a POINT base and an interval exponent;
    only a point exponent is admitted, so it withholds rather than evaluating one endpoint."""
    exponent = spec.Fn("sin", spec.Var())
    assert _actual(spec.Bin("pow", _num(2.0), exponent), 1.0) is None
