# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Branch-edge witnesses for the request grammar beyond the contract-level suite."""

from dataclasses import replace
from fractions import Fraction

import pytest

from verifier.pysrc.limits import DEFAULT_LIMITS
from verifier.pysrc.request import REQUEST_GRAMMAR, formula_target
from verifier.pysrc.spec import Bin, Const, Expr, Fn, FormulaTarget, Grid, Interval, Neg, Num, Var

_ZERO = Num(Fraction(0))
_ONE = Num(Fraction(1))
_DOMAIN = Interval(_ZERO, _ONE)


@pytest.mark.parametrize(
    ("text", "expression"),
    [
        ("0", _ZERO),
        ("0.1", Num(Fraction(0.1))),
        ("1e-3", Num(Fraction(0.001))),
        ("pi", Const("pi")),
        ("e", Const("e")),
        ("x", Var()),
        ("+x", Var()),
        ("-x", Neg(Var())),
        ("x + 1", Bin("add", Var(), _ONE)),
        ("x - 1", Bin("sub", Var(), _ONE)),
        ("x * 1", Bin("mul", Var(), _ONE)),
        ("x / 1", Bin("div", Var(), _ONE)),
        ("2*x*x", Bin("mul", Bin("mul", Num(Fraction(2)), Var()), Var())),
        ("-x**2", Neg(Bin("pow", Var(), Num(Fraction(2))))),
        ("x**-2", Bin("pow", Var(), Neg(Num(Fraction(2))))),
        ("x**+2", Bin("pow", Var(), Num(Fraction(2)))),
        ("(x)", Var()),
        ("sin(x)", Fn("sin", Var())),
        ("cos(x)", Fn("cos", Var())),
        ("tan(x)", Fn("tan", Var())),
        ("exp(x)", Fn("exp", Var())),
        ("log(x)", Fn("log", Var())),
        ("sqrt(x)", Fn("sqrt", Var())),
        ("abs(x)", Fn("abs", Var())),
    ],
)
def test_internal_expression_nodes(text: str, expression: Expr) -> None:
    """R3's distinct node and operator arms project hand-stated trees."""
    assert REQUEST_GRAMMAR == "pyexpr-0.1"
    assert formula_target(f"y = {text}, x in [0, 1]") == FormulaTarget(expression, _DOMAIN)


@pytest.mark.parametrize(
    ("text", "grid"),
    [
        ("y = x, x ∈ [0, 1]", _DOMAIN),
        ("f(x) = x, x IN [0, 1]", _DOMAIN),
        ("y = x from 0 to 1", _DOMAIN),
        ("y = x FROM 0 TO 1", _DOMAIN),
        ("y = xを0から1まで描いて", _DOMAIN),
        ("y = xを0 から1まで描いて", _DOMAIN),
        ("y = xを0から1 まで描いて", _DOMAIN),
        ("y = x, x in [0, 1], n = 3", Grid(_ZERO, _ONE, 3)),
        ("y = x, x in [0, 1], n\t=\t10", Grid(_ZERO, _ONE, 10)),
        (
            "y = x, x in [-5, 2*pi]",
            Interval(Neg(Num(Fraction(5))), Bin("mul", Num(Fraction(2)), Const("pi"))),
        ),
        ("ｙ＝ｘ，　ｘ　ｉｎ　［０，　１］", _DOMAIN),  # noqa: RUF001 - NFKC input vector
        ("y=x; x in [0,1]", _DOMAIN),
        ("y=x。x in [0,1]", _DOMAIN),
    ],
)
def test_internal_carrier_forms(text: str, grid: Grid | Interval) -> None:
    """R5-R7 carrier spelling, normalization, Japanese boundaries and count attachment."""
    assert formula_target(text) == FormulaTarget(Var(), grid)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "y = x",
        "y = x ",
        "y = )x, x in [0,1]",
        "x in [0,1]",
        "y = x,x in [0,1]",
        "y = x*2,5; x in [0,1]",
        "ｙ＝ｓｉｎ（ｘ），ｘ ｉｎ ［０，１］",  # noqa: RUF001 - NFKC near miss
        "y = x^2, x in [0,1]",
        "y = x+, x in [0,1]",
        "y = x!, x in [0,1]",
        "y = 2pi, x in [0,1]",
        "y = sin x, x in [0,1]",
        "y = x**x, x in [0,1]",
        "y = x**2**2, x in [0,1]",
        "y = x**, x in [0,1]",
        "y = x**-e, x in [0,1]",
        "y = 1e400, x in [0,1]",
        "y = 1e, x in [0,1]",
        "y = .5, x in [0,1]",
        "y = x, x in [0, 1], n = nope",
        "y = x, x in [0, 1], n = -1",
        "y = x, x in [0, 1], n = 3x",
        "y = x, x in [0, 1], n = 3, n = 4",
        "y = x, y = x, x in [0,1]",
        "y = x, x in [0,1], x in [0,1]",
        "y = x from 0 to 1, x in [0,1]",
        "y = x from 0 to 1 from 1 to 2",
        "y = 0から1まで",
        "y = x, 0から1だけ",
        "y = x, 0から1まで 1から2まで",
        "y = x, 2^3から4まで",
        "y = x, x in [0]",
        "y = x, x in [0,1",
        "y = x, x in [x,1]",
        "y = x, x in [0,x]",
        "y = x, x in [0,,1]",
        "y = x, x in [0,1e400]",
        "y = x, from 0 to",
        "y = x, from x to 1",
        "y = x, from 0 to x",
        "y = x, from 0 to 1!",
        "y = x, 0からxまで",
        "y = x, 0から1e400まで",
        "y = x, ファイルから",
        "my = x, x in [0,1]",
        "_y = x, x in [0,1]",
        "Y = x, x in [0,1]",
        "y = x, data from the file",
        "y = x, datax in [0,1]",
        "y = x, n = 3",
        "y = x, x in [0,1]\ud800",
    ],
)
def test_internal_malformed_carriers_fail_closed(text: str) -> None:
    """Near misses leave no target even if another carrier might parse."""
    assert formula_target(text) is None


@pytest.mark.parametrize(
    ("text", "field", "value"),
    [
        ("y=x, x in [0,1]", "max_source_bytes", 1),
        ("y=x, x in [0,1]", "max_source_bytes", 0),
        ("y=x, x in [0,1]", "max_expr_nodes", 0),
        ("y=x, x in [0,1]", "max_bracket_depth", 0),
        ("y=x+x, x in [0,1]", "max_expr_nodes", 2),
        ("y=(x), x in [0,1]", "max_bracket_depth", 0),
        ("y=--x, x in [0,1]", "max_bracket_depth", 1),
        ("y=sin(sin(x)), x in [0,1]", "max_bracket_depth", 1),
        ("y=sin(x**-2), x in [0,1]", "max_bracket_depth", 1),
    ],
)
def test_internal_policy_limits(text: str, field: str, value: int) -> None:
    """R2/R8 caller limits each fail before constructing an oversized target."""
    limits = replace(DEFAULT_LIMITS, **{field: value})
    assert formula_target(text, limits) is None


def test_internal_huge_literal_never_raises() -> None:
    """The parser is total even where Python's integer conversion rejects long literals."""
    assert formula_target(f"y = {'1' * 5000}, x in [0,1]") is None


def test_internal_nonascii_literal_never_coerces() -> None:
    """NFKC folds full-width digits, but never accepts unrelated Unicode digit classes."""
    assert formula_target("y = ٠, x in [0,1]") is None  # noqa: RUF001 - non-ASCII digit
