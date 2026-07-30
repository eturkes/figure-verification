# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Independent parser-oracle and totality properties for the closed expression engine."""

from fractions import Fraction

from hypothesis import assume, example, given
from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from verifier.errors import VerificationError
from verifier.expr import (
    Abs,
    Binary,
    Expr,
    Neg,
    Number,
    ParsedExpr,
    Pow,
    Variable,
    parse_expr,
    print_expr,
)
from verifier.limits import VerificationLimits

_ALLOWED_VARS = frozenset({"x", "y"})
_LIMITS = VerificationLimits()
_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_ ().*/+-"
_EXPECTED_CHECKS = frozenset(
    {
        "formula.grammar_allowed",
        "formula.functions_allowed",
        "formula.names_allowed",
        "formula.exponents_bounded",
        "resource.formula_bytes",
        "resource.formula_tokens",
        "resource.formula_digits",
        "resource.formula_identifier_bytes",
        "resource.formula_ast_nodes",
        "resource.formula_ast_depth",
        "resource.formula_paren_depth",
    }
)
_SYMBOLS = {"add": "+", "sub": "-", "mul": "*", "div": "/"}


def _number(value: int) -> Number:
    return Number(value=Fraction(value))


def _variable(name: str) -> Variable:
    return Variable(name=name)


def _neg(operand: Expr) -> Neg:
    return Neg(operand=operand)


def _absolute(operand: Expr) -> Abs:
    return Abs(operand=operand)


def _power(base: Expr, exponent: int) -> Pow:
    return Pow(base=base, exponent=exponent)


def _binary(op: str, left: Expr, right: Expr) -> Binary:
    if op == "add":
        return Binary(op="add", left=left, right=right)
    if op == "sub":
        return Binary(op="sub", left=left, right=right)
    if op == "mul":
        return Binary(op="mul", left=left, right=right)
    return Binary(op="div", left=left, right=right)


_ATOMS: SearchStrategy[Expr] = st.one_of(
    st.integers(min_value=0, max_value=20).map(_number),
    st.sampled_from(("x", "y")).map(_variable),
)


def _extend_exprs(children: SearchStrategy[Expr]) -> SearchStrategy[Expr]:
    return st.one_of(
        children.map(_neg),
        children.map(_absolute),
        st.builds(_power, children, st.integers(min_value=-4, max_value=4)),
        st.builds(
            _binary,
            st.sampled_from(("add", "sub", "mul", "div")),
            children,
            children,
        ),
    )


_EXPRS: SearchStrategy[Expr] = st.recursive(_ATOMS, _extend_exprs, max_leaves=8)


def _source(node: Expr) -> str:
    """Independent fully-parenthesized infix source, sharing no production printer code."""
    if isinstance(node, Number):
        return str(node.value.numerator)
    if isinstance(node, Variable):
        return node.name
    if isinstance(node, Neg):
        return f"(-({_source(node.operand)}))"
    if isinstance(node, Abs):
        return f"abs({_source(node.operand)})"
    if isinstance(node, Pow):
        return f"(({_source(node.base)})**{node.exponent})"
    return f"({_source(node.left)} {_SYMBOLS[node.op]} {_source(node.right)})"


def _check_totality(text: str) -> None:
    try:
        parsed = parse_expr(text, allowed_vars=_ALLOWED_VARS, limits=_LIMITS)
    except VerificationError as exc:
        assert exc.check in _EXPECTED_CHECKS
        return
    except Exception as exc:
        msg = f"unexpected parser exception {type(exc).__name__}"
        raise AssertionError(msg) from exc
    assert isinstance(parsed, ParsedExpr)


@given(text=st.text(alphabet=_ALPHABET, max_size=600))
@example(text="x")
@example(text=")")
def test_alphabet_restricted_text_is_total(text: str) -> None:
    _check_totality(text)


@given(text=st.text(max_size=600))
@example(text="x")
@example(text="\ud800")
def test_arbitrary_text_is_total(text: str) -> None:
    _check_totality(text)


@given(node=_EXPRS)
def test_independent_fully_parenthesized_source_round_trips_exact_ast(node: Expr) -> None:
    parsed = parse_expr(_source(node), allowed_vars=_ALLOWED_VARS, limits=_LIMITS)
    assert parsed.ast == node


def test_round_trip_oracle_has_a_nonvacuous_shape_anchor() -> None:
    node = Binary(
        op="sub",
        left=Pow(base=Neg(operand=Variable(name="x")), exponent=2),
        right=Abs(operand=Variable(name="y")),
    )
    source = "((((-(x)))**2) - abs(y))"
    assert _source(node) == source
    assert parse_expr(source, allowed_vars=_ALLOWED_VARS, limits=_LIMITS).ast == node


@given(node=_EXPRS)
def test_canonical_printer_is_deterministic(node: Expr) -> None:
    first = print_expr(node)
    assert print_expr(node) == first


@given(left=_EXPRS, right=_EXPRS)
def test_canonical_printer_is_injective_over_distinct_asts(left: Expr, right: Expr) -> None:
    assume(left != right)
    assert print_expr(left) != print_expr(right)


def test_printer_properties_have_a_nonvacuous_close_pair_anchor() -> None:
    x = Variable(name="x")
    one = Number(value=Fraction(1))
    left = Binary(op="add", left=x, right=one)
    right = Binary(op="add", left=one, right=x)
    assert left != right
    assert print_expr(left) == "(add x 1)"
    assert print_expr(right) == "(add 1 x)"
    assert print_expr(left) != print_expr(right)
