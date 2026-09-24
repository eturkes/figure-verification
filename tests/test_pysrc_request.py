# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.4 request grammar `pyexpr-0.1`.

Contract: `.agent/archive/contracts/m10u4.md` predicate group R. Each test pins one grammar
property against a target independent of model-authored source.
"""

import importlib
import inspect
import re
import time
from collections.abc import Callable
from dataclasses import replace
from fractions import Fraction
from typing import cast, get_type_hints

import pytest
from hypothesis import given
from hypothesis import strategies as st

from verifier.pysrc import spec
from verifier.pysrc.admit import parse_admitted
from verifier.pysrc.limits import DEFAULT_LIMITS, PysrcLimits
from verifier.pysrc.project import project

_PRELUDE = "import numpy as np\nimport matplotlib.pyplot as plt\n"


def _request_target(text: str, limits: PysrcLimits = DEFAULT_LIMITS) -> spec.FormulaTarget | None:
    module = importlib.import_module("verifier.pysrc.request")
    parser = cast(Callable[..., spec.FormulaTarget | None], module.formula_target)
    return parser(text, limits=limits)


def _bound(text: str, limits: PysrcLimits = DEFAULT_LIMITS) -> spec.FormulaTarget:
    target = _request_target(text, limits)
    assert isinstance(target, spec.FormulaTarget)
    return target


def _num(value: int | float) -> spec.Num:
    return spec.Num(Fraction(value))


def test_r1_version_and_public_signature() -> None:
    """R1: the version and public signature state the target's authority and limits."""
    module = importlib.import_module("verifier.pysrc.request")
    assert module.REQUEST_GRAMMAR == "pyexpr-0.1"
    parser = module.formula_target
    signature = inspect.signature(parser)
    assert tuple(signature.parameters) == ("text", "limits")
    assert signature.parameters["limits"].default is DEFAULT_LIMITS
    assert get_type_hints(parser) == {
        "text": str,
        "limits": PysrcLimits,
        "return": spec.FormulaTarget | None,
    }
    assert _bound("y = x, x in [0, 1]").y == spec.Var()


@given(st.text())
def test_r1_total_for_any_text(text: str) -> None:
    """R1: every Unicode string returns a target or None without raising."""
    assert isinstance(_request_target(text), (spec.FormulaTarget, type(None)))
    assert _bound("y = x, x in [0, 1]").y == spec.Var()


@pytest.mark.parametrize(
    "text",
    [
        "\ud800",
        "\x00y = x, x in [0, 1]",
        "y = x, x in [1e400, 2]",
        "y = (((x))), x in [0, 1]",
        "x in [0, 1] y = x n = 3 n = 4",
        "y = x, x in [0, 1] " + ("x" * 20_001),
    ],
    ids=["surrogate", "nul", "non-finite", "nested", "two-counts", "oversize"],
)
def test_r1_total_adversarial_bank(text: str) -> None:
    """R1: UTF-8 faults, malformed carriers and the cap return, never escape."""
    assert isinstance(_request_target(text), (spec.FormulaTarget, type(None)))
    assert _bound("y = sin(x), x in [0, 1]").y == spec.Fn("sin", spec.Var())


def test_r2_nfkc_is_applied_before_carrier_and_expression_rules() -> None:
    """R2: every ASCII graphic in a full-width twin folds before parsing."""
    text = "y=sin(x), x in [0, 1]"
    full_width = "".join(
        chr(ord(char) + 0xFEE0) if "!" <= char <= "~" else chr(0x3000) for char in text
    )
    assert full_width != text
    assert ord(full_width[0]) == 0xFF59
    assert chr(0x3000) in full_width
    assert (
        _bound(full_width)
        == _bound(text)
        == spec.FormulaTarget(spec.Fn("sin", spec.Var()), spec.Interval(_num(0), _num(1)))
    )
    unspaced = "y=sin(x),x in [0,1]"
    unspaced_full_width = "".join(
        chr(ord(char) + 0xFEE0) if "!" <= char <= "~" else chr(0x3000) for char in unspaced
    )
    assert _request_target(unspaced_full_width) is None
    assert _request_target(unspaced) is None


def test_r2_normalized_utf8_byte_cap_is_not_raw_character_count() -> None:
    """R2: the 20,000-byte cap applies to the normalized UTF-8 message."""
    valid = "y = x, x in [0, 1]"
    assert _bound(valid + " " * (20_000 - len(valid))).y == spec.Var()
    assert _request_target(valid + " " * (20_001 - len(valid))) is None
    # Full-width graphics are three bytes before normalization but one afterward.
    full_width = "".join(chr(ord(char) + 0xFEE0) if "!" <= char <= "~" else char for char in valid)
    assert len(full_width.encode("utf-8")) > len(valid)
    assert _bound(full_width + " " * (20_000 - len(valid))) == _bound(valid)
    assert _request_target("\ud800" + valid) is None


@pytest.mark.parametrize(
    ("expression", "tree"),
    [
        ("-x**2", spec.Neg(spec.Bin("pow", spec.Var(), _num(2)))),
        ("x**-2", spec.Bin("pow", spec.Var(), spec.Neg(_num(2)))),
        ("2*x*x", spec.Bin("mul", spec.Bin("mul", _num(2), spec.Var()), spec.Var())),
        ("9-3-1", spec.Bin("sub", spec.Bin("sub", _num(9), _num(3)), _num(1))),
        ("8/2/2", spec.Bin("div", spec.Bin("div", _num(8), _num(2)), _num(2))),
        ("1+2*3", spec.Bin("add", _num(1), spec.Bin("mul", _num(2), _num(3)))),
        ("0.1", _num(0.1)),
        ("1e-1", _num(0.1)),
        (
            "sin(x)+cos(x)+tan(x)",
            spec.Bin(
                "add",
                spec.Bin("add", spec.Fn("sin", spec.Var()), spec.Fn("cos", spec.Var())),
                spec.Fn("tan", spec.Var()),
            ),
        ),
        (
            "exp(log(sqrt(abs(-x))))",
            spec.Fn("exp", spec.Fn("log", spec.Fn("sqrt", spec.Fn("abs", spec.Neg(spec.Var()))))),
        ),
        ("pi+e", spec.Bin("add", spec.Const("pi"), spec.Const("e"))),
        ("+x", spec.Var()),
        ("(x)", spec.Var()),
        ("x\t+\t1", spec.Bin("add", spec.Var(), _num(1))),
    ],
)
def test_r3_expression_trees_are_structural(expression: str, tree: spec.Expr) -> None:
    """R3: precedence, associativity, constants, functions and binary64 literals."""
    assert _bound(f"y = {expression}, x in [0, 1]").y == tree


@pytest.mark.parametrize(
    "expression",
    ["2pi", "x^2", "2**x", "x**2**2", "sin x", "1e400", ".5", "π"],
)
def test_r3_invalid_expressions_cannot_bind(expression: str) -> None:
    """R3: near-miss spellings and non-finite literals do not bind."""
    assert _request_target(f"y = {expression}, x in [0, 1]") is None


def test_r3_bounds_have_the_same_tree_shape_as_y() -> None:
    """R3: expression grammar also builds symbolic, negative and float64 bound trees."""
    target = _bound("y = x, x in [-0.1, 2*pi], n = 7")
    assert target == spec.FormulaTarget(
        spec.Var(),
        spec.Grid(spec.Neg(_num(0.1)), spec.Bin("mul", _num(2), spec.Const("pi")), 7),
    )
    assert _num(0.1).value != Fraction(1, 10)


def _python_expr(expression: str) -> str:
    for function in ("sin", "cos", "tan", "exp", "log", "sqrt", "abs"):
        expression = expression.replace(f"{function}(", f"np.{function}(")
    return re.sub(r"\b(?:pi|e)\b", lambda found: f"np.{found.group()}", expression)


_ATOMS = st.sampled_from(["x", "0", "1", "3", "0.1", "1e-1", "pi", "e"])
_EXPRESSIONS = st.recursive(
    _ATOMS,
    lambda inner: st.one_of(
        st.builds(lambda expr: f"-({expr})", inner),
        st.builds(
            lambda fn, expr: f"{fn}({expr})",
            st.sampled_from(["sin", "cos", "tan", "exp", "log", "sqrt", "abs"]),
            inner,
        ),
        st.builds(
            lambda left, op, right: f"({left}{op}{right})",
            inner,
            st.sampled_from(["+", "-", "*", "/"]),
            inner,
        ),
        st.builds(lambda expr, exp: f"({expr})**{exp}", inner, st.sampled_from(["2", "-2"])),
    ),
    max_leaves=5,
)
_BOUNDS = st.sampled_from(["0", "1", "2", "-1", "0.1", "pi", "e", "2*pi", "sqrt(4)"])


@given(_EXPRESSIONS, _BOUNDS, _BOUNDS)
def test_r4_request_and_projected_program_trees_agree(
    expression: str, start: str, stop: str
) -> None:
    """R4: every drawn expression/bound matches the independent AST projection."""
    requested = _bound(f"y = {expression}, x in [{start}, {stop}], n = 3")
    source = (
        _PRELUDE
        + f"x = np.linspace({_python_expr(start)}, {_python_expr(stop)}, num=3)\n"
        + f"y = {_python_expr(expression)}\nplt.plot(x, y)\nplt.show()\n"
    )
    projected = project(parse_admitted(source))
    assert isinstance(projected, spec.FormulaPlot)
    assert requested.y == projected.y
    assert requested.grid == projected.grid


@pytest.mark.parametrize(
    ("text", "y", "start", "stop", "samples"),
    [
        ("y = x, x in [0, 1]", spec.Var(), _num(0), _num(1), None),
        ("f(x) = sin(x), x ∈ [0, 1]", spec.Fn("sin", spec.Var()), _num(0), _num(1), None),
        ("y=x FROM 0 TO 1", spec.Var(), _num(0), _num(1), None),
        ("y=x, x IN [0, 1], n = 9", spec.Var(), _num(0), _num(1), 9),
        (
            "y = sin(x)を0から2*piまで描いて",
            spec.Fn("sin", spec.Var()),
            _num(0),
            spec.Bin("mul", _num(2), spec.Const("pi")),
            None,
        ),
    ],
)
def test_r5_each_carrier_form_english_and_japanese(
    text: str, y: spec.Expr, start: spec.Expr, stop: spec.Expr, samples: int | None
) -> None:
    """R5: each complete formula/interval/count form binds once in English and Japanese."""
    target = _bound(text)
    grid = spec.Interval(start, stop) if samples is None else spec.Grid(start, stop, samples)
    assert target == spec.FormulaTarget(y, grid)


def test_r5_keywords_and_bounds_are_closed_by_context() -> None:
    """R5: identifiers are whole keywords; bounds cannot use the grid variable."""
    assert _bound("data from the file; y=x, x in [0,1]").y == spec.Var()
    assert _bound("ファイルから y=x, x in [0,1]").grid == spec.Interval(_num(0), _num(1))
    for text in (
        "pay=x, x in [0,1]",
        "y=x, x in [x,1]",
        "y=x, x in [0,x]",
        "Y=x, x in [0,1]",
        "y=x, x in [0,1] n=2.5",
        "y=x, x in [0,1] n=2e2",
        "y=x, x in [0,1] prefix_n=3",
    ):
        if text.endswith("prefix_n=3"):
            assert _bound(text).grid == spec.Interval(_num(0), _num(1))
        else:
            assert _request_target(text) is None


def test_r6_maximal_spans_and_prose_boundaries() -> None:
    """R6: punctuation cannot conceal a suffix; legal prose/Japanese delimiters can."""
    for text in (
        "y = x^2, x in [0,1]",
        "y = x!, x in [0,1]",
        "y = x,x in [0,1]",
        "y = x, x in [0,1];n=2!",
        "y = x, x in [0,1] n=2!",
        "y = x, 2^3から4まで",
    ):
        assert _request_target(text) is None, text
    assert _request_target("y = (x)") is None  # No interval; parentheses themselves are valid.
    assert _bound("y = (x), x in [0,1]").y == spec.Var()
    assert _bound("y = sin(x)を0から2*piまで描いて").grid == spec.Interval(
        _num(0), spec.Bin("mul", _num(2), spec.Const("pi"))
    )
    assert _bound("y = x; x in [0, 1]").y == spec.Var()


def test_r7_one_of_each_carrier_and_disjoint_spans() -> None:
    """R7: duplicate, absent, overlapping and malformed carriers fail as a whole."""
    for text in (
        "y=x; y=x; x in [0,1]",
        "y=x",
        "y=x; from 0 to 1; x in [0,1]",
        "y = 0から1まで",
        "y=x, x in [0,1] n=3 n=3",
        "y=x^2, y=x, x in [0,1]",
        "y=x, x in [0,1] n=oops",
        "y=x, x in [0,1] x in [0,2",
        "y=x; f(x)=x; x in [0,1]",
    ):
        assert _request_target(text) is None, text
    assert _bound("y=x, x in [0,1] n=5") == spec.FormulaTarget(
        spec.Var(), spec.Grid(_num(0), _num(1), 5)
    )
    assert _bound("y=x, x in [0,1]") == spec.FormulaTarget(
        spec.Var(), spec.Interval(_num(0), _num(1))
    )


def test_r8_node_and_nesting_limits_bind_each_carrier() -> None:
    """R8: caller-supplied limits reject excess expression nodes and nesting."""
    assert (
        _request_target("y = x + x + x, x in [0,1]", replace(DEFAULT_LIMITS, max_expr_nodes=4))
        is None
    )
    assert (
        _request_target(
            "y = sin(sin(sin(x))), x in [0,1]",
            replace(DEFAULT_LIMITS, max_bracket_depth=2),
        )
        is None
    )
    assert (
        _request_target("y=x, x in [sin(sin(0)),1]", replace(DEFAULT_LIMITS, max_bracket_depth=1))
        is None
    )
    assert _bound("y=x, x in [0,1]", replace(DEFAULT_LIMITS, max_expr_nodes=4)).y == spec.Var()


def test_r8_adversarial_20000_byte_message_completes_under_two_seconds() -> None:
    """R8: one measured worst-length hostile message meets the host's two-second cap."""
    text = ("y = x+ " * 2858)[:20_000]
    assert len(text.encode("utf-8")) == 20_000
    start = time.perf_counter()
    target = _request_target(text)
    elapsed = time.perf_counter() - start
    assert target is None
    assert elapsed < 2.0, f"20,000-byte extraction took {elapsed:.3f}s"
