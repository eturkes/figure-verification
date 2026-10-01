# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M9 review reds for evaluator refusal precedence and dispatch closure."""

from fractions import Fraction
from typing import Any, cast

import msgspec
import pytest

import formula_oracle as oracle_module
from formula_oracle import FormulaOracleError, evaluate_formula_oracle
from verifier import expr as expr_module
from verifier.eval import EvaluationError, evaluate_formula_run
from verifier.expr import Abs, Binary, Expr, Neg, Number, Pow, Variable, eval_expr
from verifier.limits import VerificationLimits
from verifier.pysrc.budget import WorkBudget
from verifier.schema import FormulaPlotSpec, decode_formula_spec


def _spec(*, stop: str = "0.04", samples: int = 5) -> FormulaPlotSpec:
    return decode_formula_spec(
        msgspec.json.encode(
            {
                "version": "vplot-formula-0.1",
                "formula": "x",
                "domain": {
                    "start": "0",
                    "stop": stop,
                    "samples": samples,
                    "x_scale": 0,
                    "y_scale": 0,
                },
                "numeric_profile": "rational-half-even-v1",
                "mark": "line",
                "encoding": {
                    "x": {"field": "x", "type": "quantitative"},
                    "y": {"field": "y", "type": "quantitative"},
                },
            }
        )
    )


def test_endpoint_boundedness_precedes_an_earlier_interior_collision() -> None:
    spec = _spec()
    with pytest.raises(FormulaOracleError) as oracle_exc:
        evaluate_formula_oracle(spec)
    assert oracle_exc.value.check == "formula.domain_bounded"

    with pytest.raises(EvaluationError) as production_exc:
        evaluate_formula_run(spec)
    assert production_exc.value.check == "formula.domain_bounded"


class _BinaryNearMiss:
    def __init__(self, *, op: str, left: Expr, right: Expr) -> None:
        self.op = op
        self.left = left
        self.right = right


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


def test_evaluator_refuses_structural_binary_near_miss() -> None:
    near_miss = _BinaryNearMiss(
        op="add",
        left=Variable(name="x"),
        right=Number(value=Fraction(1)),
    )
    with pytest.raises(TypeError):
        eval_expr(
            cast("Any", near_miss),
            {"x": Fraction(2)},
            VerificationLimits(),
        )


@pytest.mark.parametrize(
    "near_miss",
    _SUBCLASS_NEAR_MISSES,
    ids=lambda node: type(node).__name__,
)
def test_evaluator_refuses_undeclared_node_subclass(near_miss: Expr) -> None:
    with pytest.raises(TypeError):
        eval_expr(near_miss, {"x": Fraction(2)}, VerificationLimits())


def test_binary_operator_dispatch_refuses_dunder_near_miss() -> None:
    with pytest.raises(ValueError):
        expr_module._apply_binary(
            cast("Any", "__div__"),
            Fraction(1),
            Fraction(2),
            WorkBudget(limit=1),
        )


@pytest.mark.parametrize(
    "near_miss",
    _SUBCLASS_NEAR_MISSES,
    ids=lambda node: type(node).__name__,
)
def test_formula_oracle_refuses_undeclared_node_subclass(near_miss: Expr) -> None:
    with pytest.raises(TypeError):
        evaluate_formula_oracle(_spec(stop="1", samples=2), parsed_ast=near_miss)


def test_formula_oracle_binary_dispatch_refuses_dunder_near_miss() -> None:
    near_miss = _BinaryNearMiss(
        op="__div__",
        left=Number(value=Fraction(1)),
        right=Number(value=Fraction(2)),
    )
    with pytest.raises(ValueError):
        oracle_module._binary_result(cast("Any", near_miss), Fraction(1), Fraction(2))


def test_formula_oracle_refuses_a_binary_subclass_before_its_children_run() -> None:
    near_miss = _near_subclass(
        Binary,
        op="add",
        left=Binary(op="div", left=_ONE, right=Number(value=Fraction(0))),
        right=_ONE,
    )
    with pytest.raises(TypeError):
        evaluate_formula_oracle(_spec(stop="1", samples=2), parsed_ast=near_miss)
