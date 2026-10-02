# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""An independent request grammar judges each parsed target, not just refusals."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, fields, is_dataclass
from fractions import Fraction
from pathlib import Path
from time import perf_counter
from types import ModuleType

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.strategies import DrawFn, SearchStrategy

from oracle_request import Neutral, oracle_formula_target
from verifier.pysrc import spec
from verifier.pysrc.limits import DEFAULT_LIMITS, PysrcLimits

_ROOT = Path(__file__).resolve().parent.parent
_NUM_0: Neutral = ("num", Fraction(0))
_NUM_1: Neutral = ("num", Fraction(1))
_NUM_2: Neutral = ("num", Fraction(2))
_VAR: Neutral = ("var",)
_PI: Neutral = ("const", "pi")


def _target(
    y: Neutral, start: Neutral = _NUM_0, stop: Neutral = _NUM_1, n: int | None = None
) -> Neutral:
    grid = ("interval", start, stop) if n is None else ("grid", start, stop, n)
    return ("target", y, grid)


@dataclass(frozen=True, slots=True)
class _HandCase:
    id: str
    text: str
    expected: Neutral | None
    limits: PysrcLimits = DEFAULT_LIMITS


_HAND = (
    # R1: any string, even with surrogate code points, must return rather than raise.
    _HandCase("R1-plain", "chart these observations", None),
    _HandCase("R1-surrogate", "y = x, x in [0, 1]\ud800", None),
    # R2 + A2: both directions of NFKC, folding before boundary and byte checks.
    _HandCase(
        "R2-width",
        "ｙ＝ｓｉｎ（ｘ），　ｘ　ｉｎ　［０，　１］",  # noqa: RUF001
        _target(("fn", "sin", _VAR)),
    ),
    _HandCase("R2-ascii", "y=sin(x), x in [0, 1]", _target(("fn", "sin", _VAR))),
    _HandCase("R2-unspaced", "ｙ＝ｓｉｎ（ｘ），ｘ ｉｎ ［０，１］", None),  # noqa: RUF001
    _HandCase("R2-oversize", "a" * 20_001, None),
    # R3: precedence, associativity, signed integer power, binary64 literals, near misses.
    _HandCase(
        "R3-neg-power", "y = -x**2, x in [0, 1]", _target(("neg", ("bin", "pow", _VAR, _NUM_2)))
    ),
    _HandCase(
        "R3-negative-exponent",
        "y = x**-2, x in [0, 1]",
        _target(("bin", "pow", _VAR, ("neg", _NUM_2))),
    ),
    _HandCase(
        "R3-positive-exponent", "y = x**+2, x in [0, 1]", _target(("bin", "pow", _VAR, _NUM_2))
    ),
    _HandCase(
        "R3-left-assoc",
        "y = 2*x*x, x in [0, 1]",
        _target(("bin", "mul", ("bin", "mul", _NUM_2, _VAR), _VAR)),
    ),
    _HandCase("R3-float", "y = 0.1, x in [0, 1]", _target(("num", Fraction(0.1)))),
    _HandCase("R3-exponent-literal", "y = 1e-3, x in [0, 1]", _target(("num", Fraction(0.001)))),
    _HandCase("R3-leading-zeros", "y = 0002, x in [0, 1]", _target(_NUM_2)),
    _HandCase(
        "R3-const",
        "y = x*pi+e, x in [0, 1]",
        _target(("bin", "add", ("bin", "mul", _VAR, _PI), ("const", "e"))),
    ),
    *(
        _HandCase(f"R3-fn-{name}", f"y = {name}(x), x in [0, 1]", _target(("fn", name, _VAR)))
        for name in ("sin", "cos", "tan", "exp", "log", "sqrt", "abs")
    ),
    *(
        _HandCase(f"R3-invalid-{index}", f"y = {expression}, x in [0, 1]", None)
        for index, expression in enumerate(("2pi", "x^2", "2**x", "x**2**2", "sin x", "1e400"))
    ),
    # R5: every interval spelling and both formula spellings; incomplete prose is not a carrier.
    _HandCase("R5-membership", "f(x) = sin(x), x ∈ [0, 1]", _target(("fn", "sin", _VAR))),
    _HandCase("R5-case", "y = x, x IN [0, 1]", _target(_VAR)),
    _HandCase("R5-from", "y = x, FROM 0 TO 1", _target(_VAR)),
    _HandCase("R5-japanese", "y = xを0から1まで描いて", _target(_VAR)),
    _HandCase("R5-ja-spaced", "y = xを0 から 1 まで描いて", _target(_VAR)),
    _HandCase("R5-not-from", "y = x, data from the file", None),
    _HandCase("R5-not-ja", "y = x, ファイルから", None),
    _HandCase("R5-japanese-prefix", "y = x。零から一まで", None),
    # R6 + A1: a punctuated end needs a prose boundary; parentheses are ordinary expressions.
    _HandCase("R6-caret", "y = x^2, x in [0, 1]", None),
    _HandCase("R6-bang", "y = x!, x in [0, 1]", None),
    _HandCase("R6-parens", "y = (x), x in [0, 1]", _target(_VAR)),
    _HandCase("R6-no-interval", "y = (x)", None),
    _HandCase("R6-comma", "y = x,x in [0,1]", None),
    _HandCase("R6-bounds-caret", "y = xを2^3から4まで", None),
    _HandCase(
        "R6-japanese",
        "y = sin(x)を0から2*piまで描いて",
        _target(("fn", "sin", _VAR), stop=("bin", "mul", _NUM_2, _PI)),
    ),
    # R7: cardinality, malformed matches and pairwise disjoint spans.
    _HandCase("R7-double-formula", "y = x; y = x, x in [0, 1]", None),
    _HandCase("R7-no-interval", "y = x", None),
    _HandCase("R7-double-interval", "y = x, from 0 to 1, x in [0, 1]", None),
    _HandCase("R7-overlap", "y = 0から1まで", None),
    _HandCase("R7-count", "y = x, x in [0, 1], n = 20", _target(_VAR, n=20)),
    _HandCase("R7-double-count", "y = x, x in [0, 1], n = 2, n = 3", None),
    _HandCase("R7-malformed-count", "y = x, x in [0, 1], n = -2", None),
    _HandCase("R7-malformed-bracket", "y = x, x in [0, 1", None),
    _HandCase("R7-bad-bound", "y = x, x in [x, 1]", None),
    # R8: node/depth/byte limits are independent.
    _HandCase(
        "R8-depth", "y = sin(sin(sin(x))), x in [0, 1]", None, PysrcLimits(max_bracket_depth=2)
    ),
    _HandCase("R8-nodes", "y = x+x+x, x in [0, 1]", None, PysrcLimits(max_expr_nodes=4)),
    _HandCase("R8-plus-node", "y = +x, x in [0, 1]", _target(_VAR), PysrcLimits(max_expr_nodes=1)),
    _HandCase("R8-minus-node", "y = -x, x in [0, 1]", None, PysrcLimits(max_expr_nodes=1)),
    _HandCase("R8-bytes", "y = x, x in [0, 1]", None, PysrcLimits(max_source_bytes=17)),
)


@pytest.mark.parametrize("case", _HAND, ids=lambda case: case.id)
def test_oracle_hand_stated_r_acceptance(case: _HandCase) -> None:
    """R1-R3, R5-R8: all explicit acceptance witnesses read solely against the contract."""
    assert oracle_formula_target(case.text, case.limits) == case.expected


def _fields(node: object, expected: tuple[str, ...]) -> None:
    if not is_dataclass(node):
        raise TypeError
    actual = tuple(field.name for field in fields(node))
    assert actual == expected, f"unmapped fields: {type(node).__name__}: {actual!r} != {expected!r}"


def _field(node: object, name: str) -> object:
    return getattr(node, name)


def _expression(node: object) -> Neutral:
    if type(node) is spec.Num:
        _fields(node, ("value",))
        value = _field(node, "value")
        assert type(value) is Fraction
        return ("num", value)
    if type(node) is spec.Var:
        _fields(node, ())
        return ("var",)
    if type(node) is spec.Const:
        _fields(node, ("name",))
        return ("const", _field(node, "name"))
    if type(node) is spec.Neg:
        _fields(node, ("operand",))
        return ("neg", _expression(_field(node, "operand")))
    if type(node) is spec.Fn:
        _fields(node, ("name", "arg"))
        return ("fn", _field(node, "name"), _expression(_field(node, "arg")))
    if type(node) is spec.Bin:
        _fields(node, ("op", "left", "right"))
        return (
            "bin",
            _field(node, "op"),
            _expression(_field(node, "left")),
            _expression(_field(node, "right")),
        )
    message = f"unmapped expression node: {type(node).__name__}"
    raise TypeError(message)


def target_to_neutral(target: object) -> Neutral:
    """Map exact production node classes and field sets; every extension fails loudly."""
    if type(target) is not spec.FormulaTarget:
        message = f"unmapped target: {type(target).__name__}"
        raise TypeError(message)
    _fields(target, ("y", "grid"))
    grid = _field(target, "grid")
    if type(grid) is spec.Grid:
        _fields(grid, ("start", "stop", "samples"))
        neutral_grid: Neutral = (
            "grid",
            _expression(_field(grid, "start")),
            _expression(_field(grid, "stop")),
            _field(grid, "samples"),
        )
    elif type(grid) is vars(spec).get("Interval"):
        _fields(grid, ("start", "stop"))
        neutral_grid = (
            "interval",
            _expression(_field(grid, "start")),
            _expression(_field(grid, "stop")),
        )
    else:
        message = f"unmapped grid node: {type(grid).__name__}"
        raise TypeError(message)
    return ("target", _expression(_field(target, "y")), neutral_grid)


def _request_module() -> ModuleType:
    imported = importlib.import_module("verifier.pysrc.request")
    assert imported.__file__ is not None
    assert Path(imported.__file__).resolve() == _ROOT / "src/verifier/pysrc/request.py", (
        f"editable install points at a different checkout: {imported.__file__}"
    )
    return imported


def _assert_same(text: str, limits: PysrcLimits = DEFAULT_LIMITS) -> bool:
    expected = oracle_formula_target(text, limits)
    module = _request_module()
    assert vars(module)["REQUEST_GRAMMAR"] == "pyexpr-0.1"
    observed = vars(module)["formula_target"](text, limits)
    actual = target_to_neutral(observed) if observed is not None else None
    assert actual == expected, f"text={text!r}; production={actual!r}; oracle={expected!r}"
    return expected is not None


@dataclass(frozen=True, slots=True)
class _Expression:
    text: str
    tree: Neutral


@st.composite
def _expressions(draw: DrawFn, *, with_x: bool = True) -> _Expression:
    numbers = (
        ("0", Fraction(0)),
        ("01", Fraction(1)),
        ("2", Fraction(2)),
        ("0.1", Fraction(0.1)),
        ("1e-3", Fraction(0.001)),
        ("2E+2", Fraction(200.0)),
    )
    leaves = st.one_of(
        st.sampled_from([_Expression(text, ("num", number)) for text, number in numbers]),
        st.sampled_from([_Expression(name, ("const", name)) for name in ("pi", "e")]),
        st.just(_Expression("x", _VAR)) if with_x else st.just(_Expression("0", _NUM_0)),
    )

    def extend(inner: SearchStrategy[_Expression]) -> SearchStrategy[_Expression]:
        @st.composite
        def build(nested: DrawFn) -> _Expression:
            operator = nested(st.sampled_from(("fn", "neg", "pos", "bin", "pow")))
            term = nested(inner)
            if operator == "fn":
                name = nested(st.sampled_from(("sin", "cos", "tan", "exp", "log", "sqrt", "abs")))
                return _Expression(f"{name}({term.text})", ("fn", name, term.tree))
            if operator == "neg":
                return _Expression(f"-({term.text})", ("neg", term.tree))
            if operator == "pos":
                return _Expression(f"+({term.text})", term.tree)
            if operator == "pow":
                exponent = nested(st.sampled_from(("+2", "-3", "0")))
                magnitude = Fraction(int(exponent))
                power: Neutral = (
                    ("num", magnitude) if magnitude >= 0 else ("neg", ("num", -magnitude))
                )
                return _Expression(f"({term.text})**{exponent}", ("bin", "pow", term.tree, power))
            second = nested(inner)
            symbol, name = nested(
                st.sampled_from((("+", "add"), ("-", "sub"), ("*", "mul"), ("/", "div")))
            )
            return _Expression(
                f"({term.text}){symbol}({second.text})", ("bin", name, term.tree, second.tree)
            )

        return build()

    return draw(st.recursive(leaves, extend, max_leaves=6))


def _full_width(text: str) -> str:
    return "".join(
        "　" if ch == " " else chr(ord(ch) + 0xFEE0) if "!" <= ch <= "~" else ch for ch in text
    )


@st.composite
def _valid_cases(draw: DrawFn) -> str:
    expression = draw(_expressions())
    a, b = draw(_expressions(with_x=False)), draw(_expressions(with_x=False))
    form = draw(st.sampled_from(("membership", "in", "from", "ja")))
    lhs = draw(st.sampled_from(("y", "f(x)")))
    if form == "ja":
        a_space, b_space, end_space = (draw(st.sampled_from(("", " ", "\t"))) for _ in range(3))
        text = (
            f"{lhs} = {expression.text}を{a.text}{a_space}から"
            f"{b_space}{b.text}{end_space}まで描いて"
        )
    elif form == "from":
        keyword = draw(st.sampled_from(("from", "FROM", "FrOm")))
        text = f"{lhs} = {expression.text}, {keyword} {a.text} to {b.text}"
    else:
        symbol = "∈" if form == "membership" else draw(st.sampled_from(("in", "IN")))
        text = f"{lhs} = {expression.text}, x {symbol} [{a.text}, {b.text}]"
    if draw(st.booleans()):
        text += f" n = {draw(st.integers(min_value=0, max_value=100_000))}"
    text = draw(st.sampled_from(("", "Plot: ", "描いて ", "data from the file. "))) + text
    if draw(st.booleans()):
        text = _full_width(text)
    return text


@st.composite
def _domain_cases(draw: DrawFn) -> tuple[str, PysrcLimits]:
    variation = draw(st.integers(min_value=0, max_value=13))
    text, limits = draw(_valid_cases()), DEFAULT_LIMITS
    if variation == 0:
        text = text.replace("y =", "y = x^2 +", 1)
    elif variation == 1:
        text += " y = 1"
    elif variation == 2:
        text += " from 0 to 1"
    elif variation == 3:
        text += " n = -3"
    elif variation == 4:
        text += " y = sin x"
    elif variation == 5:
        text += " x ∈ [0, 1"
    elif variation == 6:
        text += " ignored from the file"
    elif variation == 7:
        text += "!"
    elif variation == 8:
        limits = PysrcLimits(max_expr_nodes=2)
    elif variation == 9:
        limits = PysrcLimits(max_source_bytes=10)
    elif variation >= 10:
        text = (
            "y = " + "(" * 17 + "x" + ")" * 17 + ", x in [0, 1]",
            "y = 0から1まで",
            "prey = x, x in [0, 1]",
            "y = 1e400, x in [0, 1]",
        )[variation - 10]
    return text, limits


@given(expression=_expressions(), start=_expressions(with_x=False), stop=_expressions(with_x=False))
@settings(max_examples=100, deadline=None)
def test_oracle_generated_expression_trees(
    expression: _Expression, start: _Expression, stop: _Expression
) -> None:
    """R4: drawn grammar pieces retain exact trees in both request positions."""
    text = f"y = {expression.text}, x in [{start.text}, {stop.text}]"
    assert oracle_formula_target(text) == _target(expression.tree, start.tree, stop.tree)


@given(text=st.text())
@settings(max_examples=120, deadline=None)
def test_oracle_is_total_for_unicode_text(text: str) -> None:
    assert oracle_formula_target(text) is None or isinstance(oracle_formula_target(text), tuple)


def test_oracle_long_japanese_span_is_bounded() -> None:
    """R8: a 19,222-byte span with thousands of start boundaries must finish <2s."""
    text = "y = xを" + "1 + " * 4800 + "1から2まで"
    start = perf_counter()
    assert oracle_formula_target(text) is None
    assert perf_counter() - start < 2


@given(text=_valid_cases())
@settings(max_examples=120, deadline=None)
def test_oracle_generated_carriers_bind(text: str) -> None:
    assert oracle_formula_target(text) is not None, text


@given(
    valid=st.lists(_valid_cases(), min_size=7, max_size=7),
    varied=st.lists(_domain_cases(), min_size=13, max_size=13),
)
# `too_slow` measures wall time per draw, so a loaded host fails it with no code change; the fixed
# example count is the budget this test owns.
@settings(max_examples=48, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_differential_generated_request_domain(
    valid: list[str], varied: list[tuple[str, PysrcLimits]]
) -> None:
    """Twenty texts per draw, at least 7 independently valid: ≥30% must bind.

    The deliberate 7/20 lower bound makes an always-None parser fail loudly while leaving
    13/20 examples for malformed, overlapping, capped and near-miss requests.
    """
    cases = [(text, DEFAULT_LIMITS) for text in valid] + varied
    binds = [oracle_formula_target(text, limits) is not None for text, limits in cases]
    assert sum(binds) >= 6, f"vacuous generated domain: {sum(binds)}/20 targets bound"
    for text, limits in cases:
        _assert_same(text, limits)


@pytest.mark.parametrize(
    "text",
    (
        "ｙ＝ｓｉｎ（ｘ），　ｘ　ｉｎ　［０，　１］",  # noqa: RUF001
        "y = x; y = x, x in [0, 1]",
        "y = x, FROM 0 TO 1",
        "y = 0から1まで",
        "y = x, x in [0, 1], n = 17",
        "y = sin(x)を0から2*piまで描いて",
        "y = x,x in [0,1]",
    ),
    ids=("nfkc-positive", "two-formulas", "from-case", "overlap", "count", "japanese", "comma"),
)
def test_differential_contract_anchors(text: str) -> None:
    _assert_same(text)
