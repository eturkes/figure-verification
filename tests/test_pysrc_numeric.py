# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Numeric profile `binary64-libm-v1` — N1-N8 of `.agent/archive/contracts/m13u5.md`.

The executed program is numpy float64 and rounds at EVERY operator, so the verifier evaluates the
projected tree operator by operator in binary64. An exact-rational engine rounding once at the end
would compute a number the program never computes; the more precise engine is the less faithful
one. Every comparison here is on BIT PATTERNS, never with a tolerance.

Skeleton: each body is `pytest.skip` and its docstring carries the predicate's acceptance check.
"""

import math
import struct
from fractions import Fraction

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from verifier.pysrc import spec
from verifier.pysrc.budget import WorkBudget


def _bits(value: float) -> bytes:
    return struct.pack("<d", value)


def _bit_sequence(values: tuple[float, ...]) -> tuple[bytes, ...]:
    return tuple(_bits(value) for value in values)


def _formula_source(expression: str, *, start: str = "0", stop: str = "1") -> str:
    return (
        "import numpy as np\n"
        "import matplotlib.pyplot as plt\n"
        f"x = np.linspace({start}, {stop}, num=2)\n"
        f"y = {expression}\n"
        "plt.plot(x, y)\n"
        "plt.show()\n"
    )


def test_n1_rounds_at_every_node() -> None:
    """Round-at-each-node, not exact-then-round.

    Accept: a witness expression where exact-rational-then-round and round-at-each-node differ;
    the evaluator must produce the round-at-each-node value AND it must equal numpy's on the same
    expression, compared as bit patterns.
    """
    from verifier.pysrc.numeric import evaluate_expr  # noqa: PLC0415

    expression = spec.Bin(
        "sub",
        spec.Bin(
            "add",
            spec.Num(Fraction(10**16)),
            spec.Num(Fraction(1)),
        ),
        spec.Num(Fraction(10**16)),
    )
    with np.errstate(all="ignore"):
        oracle = np.subtract(
            np.add(np.float64(10**16), np.float64(1)),
            np.float64(10**16),
        )
    evaluated = evaluate_expr(expression, x=0.0, budget=WorkBudget(limit=10))

    assert _bits(evaluated) == _bits(float(oracle)) == _bits(0.0)
    assert _bits(evaluated) != _bits(float(Fraction(10**16) + 1 - Fraction(10**16)))


def test_n2_literal_conversion_is_the_executed_float() -> None:
    """`Num(Fraction(0.1))` evaluates to the float64 `0.1`, never to a rounded `1/10`.

    Accept: hex-float literal comparison for `0.1` and for the non-binary decimal `0.2`
    (`assurance.md` exactness-witness law).
    """
    from verifier.pysrc.numeric import evaluate_expr  # noqa: PLC0415

    witnesses = (
        (0.1, "0x1.999999999999ap-4", Fraction(1, 10)),
        (0.2, "0x1.999999999999ap-3", Fraction(1, 5)),
    )
    for source_float, expected_hex, decimal_fraction in witnesses:
        projected = Fraction(source_float)
        assert projected != decimal_fraction
        evaluated = evaluate_expr(
            spec.Num(projected),
            x=0.0,
            budget=WorkBudget(limit=1),
        )
        assert evaluated.hex() == expected_hex
        assert _bits(evaluated) == _bits(float.fromhex(expected_hex))


def test_n3_ieee_domain_results_instead_of_exceptions() -> None:
    """Domain and overflow faults reproduce numpy's IEEE values rather than raising.

    Accept: table-driven differential against numpy, compared on bit patterns, for `x/0` -> +-inf,
    `0/0` -> nan, `log(0)` -> -inf, `log(x<0)` -> nan, `sqrt(x<0)` -> nan, negative base with
    non-integral exponent -> nan, `exp` overflow -> inf. No `ValueError`, `ZeroDivisionError` or
    `OverflowError` escapes the evaluator.
    """
    from verifier.pysrc.numeric import evaluate_expr  # noqa: PLC0415

    zero = spec.Num(Fraction(0))
    one = spec.Num(Fraction(1))
    negative_one = spec.Num(Fraction(-1))
    half = spec.Num(Fraction(1, 2))
    thousand = spec.Num(Fraction(1000))
    # numpy intentionally warns while returning its IEEE value on these inputs.
    with np.errstate(all="ignore"):
        cases = (
            (spec.Bin("div", one, zero), np.divide(np.float64(1), np.float64(0))),
            (spec.Bin("div", negative_one, zero), np.divide(np.float64(-1), np.float64(0))),
            (spec.Bin("div", zero, zero), np.divide(np.float64(0), np.float64(0))),
            (spec.Fn("log", zero), np.log(np.float64(0))),
            (spec.Fn("log", negative_one), np.log(np.float64(-1))),
            (spec.Fn("sqrt", negative_one), np.sqrt(np.float64(-1))),
            (spec.Bin("pow", negative_one, half), np.power(np.float64(-1), np.float64(0.5))),
            (spec.Fn("exp", thousand), np.exp(np.float64(1000))),
        )

    for expression, oracle in cases:
        evaluated = evaluate_expr(expression, x=0.0, budget=WorkBudget(limit=10))
        assert _bits(evaluated) == _bits(float(oracle))


def test_n4_non_finite_is_the_sole_domain_refusal() -> None:
    """Any non-finite reaching the table refuses `value_not_finite`, and nothing else does.

    Accept: one witness per N3 row reaches `value_not_finite`; a mutant that gives any single
    domain fault its own code kills no test that this one does not already kill.
    """
    from verifier.pysrc import Refused, Verified, verify_python_source  # noqa: PLC0415

    witnesses = (
        _formula_source("1 / x"),
        _formula_source("-1 / x"),
        _formula_source("0 / x"),
        _formula_source("np.log(x)"),
        _formula_source("np.log(-x)", start="1", stop="2"),
        _formula_source("np.sqrt(-x)", start="1", stop="2"),
        _formula_source("(-np.abs(x)) ** 0.5", start="1", stop="2"),
        _formula_source("np.exp(x)", start="1000", stop="1001"),
    )
    for source in witnesses:
        result = verify_python_source(source)
        assert isinstance(result, Refused)
        assert result.code == "value_not_finite"

    finite = verify_python_source(_formula_source("np.sqrt(x)"))
    assert isinstance(finite, Verified)


def test_n5_constants_match_numpy() -> None:
    """`Const("pi")` and `Const("e")` are `math.pi` / `math.e` and bit-equal numpy's.

    Accept: hex-float literals asserted in both directions.
    """
    from verifier.pysrc.numeric import evaluate_expr  # noqa: PLC0415

    witnesses = (
        (spec.Const("pi"), "0x1.921fb54442d18p+1", math.pi, float(np.pi)),
        (spec.Const("e"), "0x1.5bf0a8b145769p+1", math.e, float(np.e)),
    )
    for constant, expected_hex, stdlib_value, numpy_value in witnesses:
        evaluated = evaluate_expr(constant, x=0.0, budget=WorkBudget(limit=1))
        assert evaluated.hex() == expected_hex
        assert _bits(evaluated) == _bits(stdlib_value) == _bits(numpy_value)


@given(
    start=st.integers(min_value=-100, max_value=100),
    step=st.sampled_from((-5, -2, -1, 1, 2, 5)),
    samples=st.integers(min_value=2, max_value=20),
)
def test_n6_grid_matches_numpy_bit_for_bit(start: int, step: int, samples: int) -> None:
    """Grid materialization reproduces `np.linspace` and `np.arange` exactly.

    Accept: differential against numpy over the M13.3 grid corpus, bit patterns, zero
    disagreements. `Grid.stop` is inclusive; `arange` bounds are integers only.
    """
    from verifier.pysrc.numeric import materialize_grid  # noqa: PLC0415

    inclusive_stop = start + (samples - 1) * step
    arange_grid = spec.Grid(
        start=spec.Num(Fraction(start)),
        stop=spec.Num(Fraction(inclusive_stop)),
        samples=samples,
    )
    arange_actual = materialize_grid(arange_grid, budget=WorkBudget(limit=100))
    arange_oracle = tuple(
        float(value) for value in np.arange(start, start + samples * step, step, dtype=np.float64)
    )
    assert _bit_sequence(arange_actual) == _bit_sequence(arange_oracle)

    linspace_cases = (
        (
            spec.Grid(spec.Num(Fraction(0)), spec.Num(Fraction(1)), 7),
            tuple(float(value) for value in np.linspace(0.0, 1.0, num=7)),
        ),
        (
            spec.Grid(spec.Num(Fraction(0.1)), spec.Num(Fraction(0.2)), 11),
            tuple(float(value) for value in np.linspace(0.1, 0.2, num=11)),
        ),
        (
            spec.Grid(spec.Neg(spec.Const("pi")), spec.Const("e"), 13),
            tuple(float(value) for value in np.linspace(-np.pi, np.e, num=13)),
        ),
    )
    for grid, oracle in linspace_cases:
        actual = materialize_grid(grid, budget=WorkBudget(limit=100))
        assert _bit_sequence(actual) == _bit_sequence(oracle)


def test_n7_profile_splits_operators_into_two_classes() -> None:
    """`binary64-libm-v1` names a standard-exact class and a libm-dependent class.

    Accept: the class table is a hand-stated LITERAL in the test, never read from production
    (`assurance.md`: a test reading a production constant pins nothing). Standard-exact =
    `add sub mul div`, unary minus, `abs`, `sqrt`, literal conversion, `pi`, `e`, both grid
    constructors. libm-dependent = `sin cos tan exp log`, `pow`. The certificate's profile string
    is byte-pinned.
    """
    from verifier.pysrc import Verified, verify_python_source  # noqa: PLC0415
    from verifier.pysrc.numeric import (  # noqa: PLC0415
        NUMERIC_PROFILE,
        OPERATOR_CLASSES,
    )

    expected_classes = {
        "standard-exact": frozenset(
            {
                "add",
                "sub",
                "mul",
                "div",
                "neg",
                "abs",
                "sqrt",
                "literal",
                "pi",
                "e",
                "linspace",
                "arange",
            }
        ),
        "libm-dependent": frozenset({"sin", "cos", "tan", "exp", "log", "pow"}),
    }
    assert NUMERIC_PROFILE == "binary64-libm-v1"
    assert expected_classes == OPERATOR_CLASSES
    assert set(OPERATOR_CLASSES) == set(expected_classes)

    result = verify_python_source(_formula_source("np.sin(x)"))
    assert isinstance(result, Verified)
    assert result.certificate.numeric_profile == "binary64-libm-v1"


def test_n8_published_band_is_measured_including_pow() -> None:
    """The 1-ulp band is a measurement on a named environment pair, not a proof.

    Accept: the shipped profile and both operator classes are hand-stated literals; `pow` is in
    the libm-dependent class on its own recorded measurement, never inherited by omission.
    """
    from verifier.pysrc.numeric import (  # noqa: PLC0415
        NUMERIC_PROFILE,
        OPERATOR_CLASSES,
    )

    standard_exact = frozenset(
        {
            "add",
            "sub",
            "mul",
            "div",
            "neg",
            "abs",
            "sqrt",
            "literal",
            "pi",
            "e",
            "linspace",
            "arange",
        }
    )
    libm_dependent = frozenset({"sin", "cos", "tan", "exp", "log", "pow"})

    assert NUMERIC_PROFILE == "binary64-libm-v1"
    assert {
        "standard-exact": standard_exact,
        "libm-dependent": libm_dependent,
    } == OPERATOR_CLASSES
    assert "pow" in libm_dependent
    assert "pow" not in standard_exact


# --- M13.5 edge witnesses: the numeric paths a normal formula never reaches ---------------------
# `_pow`, `_fraction_float`, `_trig` and `_divide` map their exceptions onto C99 / numpy VALUES.
# The public entry cannot observe the SIGN of a non-finite result -- every one of them refuses
# `value_not_finite` -- so a sign predicate is pinned directly on the private function and the
# public refusal is pinned beside it. Confirmed reachable, inputs recorded per docstring.


def test_n2_literal_beyond_float_range_is_not_finite() -> None:
    """A decimal literal too large for binary64 converts to a signed infinity, never an exception.

    Accept: `_fraction_float(Fraction(10**400))` is `+inf` and `Fraction(-10**400)` is `-inf` --
    the sign comes from the NUMERATOR, so a mutant reconverting the huge integer through `float`
    goes red rather than raising. Publicly, a 320-digit literal on one line (`max_line_bytes` is
    400, so 320 digits fit and 400 do not) refuses `value_not_finite`.
    """
    from verifier.pysrc import Refused, verify_python_source  # noqa: PLC0415
    from verifier.pysrc.numeric import _fraction_float  # noqa: PLC0415

    magnitude = Fraction(10**400)
    assert _fraction_float(magnitude) == math.inf
    assert _fraction_float(-magnitude) == -math.inf

    result = verify_python_source(_formula_source(f"x + {'1' * 320}"))
    assert isinstance(result, Refused)
    assert result.code == "value_not_finite"


def test_n3_nan_numerator_over_zero_stays_nan() -> None:
    """numpy propagates a NaN numerator through division by zero; it does not make an infinity.

    Accept: `_divide(math.nan, 0.0)` is NaN, distinguishing it from `_divide(1.0, 0.0)` (`+inf`),
    `_divide(-1.0, 0.0)` (`-inf`) and `_divide(0.0, 0.0)` (NaN) -- all four in one table, since
    the NaN arm is the one an ordinary formula never reaches. Publicly, `np.sqrt(0 - 1) / (x - x)`
    refuses `value_not_finite`.
    """
    from verifier.pysrc import Refused, verify_python_source  # noqa: PLC0415
    from verifier.pysrc.numeric import _divide  # noqa: PLC0415

    assert math.isnan(_divide(math.nan, 0.0))
    assert _divide(1.0, 0.0) == math.inf
    assert _divide(-1.0, 0.0) == -math.inf
    assert math.isnan(_divide(0.0, 0.0))

    result = verify_python_source(_formula_source("np.sqrt(0 - 1) / (x - x)"))
    assert isinstance(result, Refused)
    assert result.code == "value_not_finite"


def test_n3_pow_overflow_follows_c99_signs() -> None:
    """`math.pow`'s `OverflowError` carries no sign; C99 takes it from the operands.

    Accept: `_pow(10.0, 400.0)` is `+inf` and `_pow(-10.0, 401.0)` is `-inf`, while
    `_pow(-10.0, 400.0)` is `+inf` -- so the witness set pins BOTH conjuncts of `base < 0.0 and
    _odd_integer(exponent)`, and `_odd_integer` is exercised by that pair rather than alone.
    Publicly, `(x - x + 10) ** 400` refuses `value_not_finite`.
    """
    from verifier.pysrc import Refused, verify_python_source  # noqa: PLC0415
    from verifier.pysrc.numeric import _pow  # noqa: PLC0415

    assert _pow(10.0, 400.0) == math.inf
    assert _pow(-10.0, 401.0) == -math.inf
    assert _pow(-10.0, 400.0) == math.inf

    result = verify_python_source(_formula_source("(x - x + 10) ** 400"))
    assert isinstance(result, Refused)
    assert result.code == "value_not_finite"


def test_n3_trigonometric_domain_error_returns_nan() -> None:
    """`math.sin/cos/tan` raise on an infinite argument where numpy returns NaN.

    Accept: `_trig("sin", math.inf)` is NaN, and likewise for `cos` and `tan`, so all three
    dispatch arms reach the shared handler. Publicly, `np.sin(1 / x)` over a grid containing 0
    refuses `value_not_finite` -- the infinity arrives from the DIVISION, which is the only way an
    admitted program can hand a non-finite argument to a trigonometric call.
    """
    from verifier.pysrc import Refused, verify_python_source  # noqa: PLC0415
    from verifier.pysrc.numeric import _trig  # noqa: PLC0415

    assert math.isnan(_trig("sin", math.inf))
    assert math.isnan(_trig("cos", math.inf))
    assert math.isnan(_trig("tan", math.inf))

    result = verify_python_source(_formula_source("np.sin(1 / x)"))
    assert isinstance(result, Refused)
    assert result.code == "value_not_finite"


def test_n6_grid_with_underflowed_step_keeps_sample_positions() -> None:
    """When `delta / divisor` underflows to zero, per-index scaling still separates the samples.

    Accept: `Grid(0, 5e-324, samples=11)` materializes
    `(0.0,)*6 + (5e-324,)*5`, NOT the all-zero-but-last tuple the multiply-by-step form produces.
    Assert the WHOLE tuple: both forms yield the same two distinct values and the same length, so
    a distinct-count or endpoint assertion passes under either and pins nothing.
    """
    from verifier.pysrc.numeric import materialize_grid  # noqa: PLC0415

    grid = spec.Grid(spec.Num(Fraction(0)), spec.Num(Fraction(5e-324)), samples=11)
    actual = materialize_grid(grid, budget=WorkBudget(limit=1))

    assert actual == (0.0,) * 6 + (5e-324,) * 5
