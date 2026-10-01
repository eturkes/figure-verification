# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M9 review reds for the expression AST's runtime closure."""

from dataclasses import dataclass
from fractions import Fraction
from typing import Any, cast

import pytest

from verifier.expr import Abs, Binary, Expr, Neg, Number, Pow, Variable, print_expr


@dataclass(frozen=True, slots=True)
class _BinaryNearMiss:
    op: str
    left: Expr
    right: Expr


def _near_subclass(node_type: type[Any], **kwargs: object) -> Expr:
    subclass = type(f"_Near{node_type.__name__}", (node_type,), {})
    return cast("Expr", subclass(**kwargs))


_ONE = Number(value=Fraction(1))
_X = Variable(name="x")
_SUBCLASS_NEAR_MISSES = (
    _near_subclass(Number, value=Fraction(1)),
    _near_subclass(Variable, name="x"),
    _near_subclass(Neg, operand=_X),
    _near_subclass(Abs, operand=_X),
    _near_subclass(Pow, base=_X, exponent=2),
    _near_subclass(Binary, op="add", left=_ONE, right=_ONE),
)


def test_number_refuses_direct_negative_literal() -> None:
    with pytest.raises(ValueError):
        Number(value=Fraction(-1))


def test_binary_refuses_dunder_shaped_operator_on_direct_construction() -> None:
    one = Number(value=Fraction(1))
    with pytest.raises(ValueError):
        Binary(op=cast("Any", "__div__"), left=one, right=one)


def test_printer_refuses_structural_near_miss_instead_of_aliasing_binary() -> None:
    left = Variable(name="x")
    right = Number(value=Fraction(1))
    near_miss = _BinaryNearMiss(op="add", left=left, right=right)
    with pytest.raises(TypeError):
        print_expr(cast("Any", near_miss))


@pytest.mark.parametrize(
    "near_miss",
    _SUBCLASS_NEAR_MISSES,
    ids=lambda node: type(node).__name__,
)
def test_printer_refuses_undeclared_node_subclass(near_miss: Expr) -> None:
    with pytest.raises(TypeError):
        print_expr(near_miss)
