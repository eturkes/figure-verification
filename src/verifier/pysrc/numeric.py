# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Binary64 evaluation of a projected expression, and materialization of a projected grid.

Written for this job rather than ported from `verifier.expr`. `expr.py` is exact over `Fraction`
and rounds once at the end; the executed program is numpy float64 and rounds at EVERY operator, so
an exact engine computes a number the program never computes. The more precise engine is the less
faithful one, and faithfulness is the whole claim.

Every node rounds to binary64 before its parent reads it. No exact intermediate exists, and a
`Fraction` literal converts through `float()` so a source `0.1` becomes the float64 `0.1` the
program passes to numpy -- not a rounded `1/10`.

Domain and overflow faults are never raised out of here. They reproduce numpy's IEEE values, so
`x/0` is `+-inf` and `log(0)` is `-inf`, and a single downstream refusal rejects any non-finite
that reaches the table. `pow` is the one operator where reproducing numpy takes real logic; see
`_pow`.
"""

import math
from fractions import Fraction
from typing import Literal, assert_never, cast

from verifier.pysrc.budget import WorkBudget
from verifier.pysrc.spec import Bin, BinOp, Const, ConstName, Expr, Fn, FnName, Grid, Neg, Num, Var

__all__ = ["NUMERIC_PROFILE", "OPERATOR_CLASSES", "evaluate_expr", "materialize_grid"]

# Published in every certificate. The name is load-bearing: the LEGACY JSON formula mode runs
# `rational-half-even-v1` and is exact, and `examples/index.json` ships a sentence about that
# exactness. A reader must never carry one mode's guarantee onto the other, so the profiles are
# separately named and the certificate prints this one verbatim.
NUMERIC_PROFILE = "binary64-libm-v1"
OPERATOR_CLASSES: dict[str, frozenset[str]] = {
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

_NEGATIVE_NAN = -math.nan


def _fraction_float(value: Fraction) -> float:
    try:
        return float(value)
    except OverflowError:
        return -math.inf if value.numerator < 0 else math.inf


def _divide(left: float, right: float) -> float:
    try:
        return left / right
    except ZeroDivisionError:
        if math.isnan(left):
            return left
        if left == 0.0:
            return _NEGATIVE_NAN
        sign = math.copysign(1.0, left) * math.copysign(1.0, right)
        return math.copysign(math.inf, sign)


def _odd_integer(value: float) -> bool:
    return math.isfinite(value) and value.is_integer() and math.fmod(abs(value), 2.0) == 1.0


def _pow(base: float, exponent: float) -> float:
    """`math.pow` with its exceptions mapped to C99 / numpy values.

    `ValueError` is ambiguous: it covers zero-base poles and negative-base domains, which numpy
    maps to infinities and NaNs respectively. The operands, including negative zero's sign bit,
    decide which result the executed program receives.
    """
    try:
        return math.pow(base, exponent)
    except OverflowError:
        negative = base < 0.0 and _odd_integer(exponent)
        return -math.inf if negative else math.inf
    except ValueError:
        if base == 0.0:
            negative = math.copysign(1.0, base) < 0.0 and _odd_integer(exponent)
            return -math.inf if negative else math.inf
        return math.copysign(math.nan, base)


def _trig(name: Literal["sin", "cos", "tan"], value: float) -> float:
    try:
        if name == "sin":
            return math.sin(value)
        if name == "cos":
            return math.cos(value)
        if name == "tan":
            return math.tan(value)
        raise AssertionError(name)  # pragma: no cover - the literal type is closed
    except ValueError:
        return _NEGATIVE_NAN


def _exp(value: float) -> float:
    try:
        return math.exp(value)
    except OverflowError:
        return math.inf


def _log(value: float) -> float:
    try:
        return math.log(value)
    except ValueError:
        return -math.inf if value == 0.0 else math.nan


def _sqrt(value: float) -> float:
    try:
        return math.sqrt(value)
    except ValueError:
        return math.copysign(math.nan, value)


def _function(name: FnName, value: float) -> float:
    match name:
        case "sin" | "cos" | "tan":
            return _trig(name, value)
        case "abs":
            return abs(value)
        case "exp":
            return _exp(value)
        case "log":
            return _log(value)
        case "sqrt":
            return _sqrt(value)
        case _ as unreachable:  # pragma: no cover - `FnName` is closed
            assert_never(unreachable)


def _binary(operator: BinOp, left: float, right: float) -> float:
    if operator == "add":
        return left + right
    if operator == "sub":
        return left - right
    if operator == "mul":
        return left * right
    if operator == "div":
        return _divide(left, right)
    if operator == "pow":
        return _pow(left, right)
    assert_never(operator)  # pragma: no cover - `BinOp` is closed


type _CompoundExpr = Neg | Fn | Bin


def _constant(name: ConstName) -> float:
    if name == "pi":
        return math.pi
    if name == "e":
        return math.e
    assert_never(name)  # pragma: no cover - `ConstName` is closed


def _start_node(
    node: Expr,
    x: float,
    pending: list[tuple[Expr, bool]],
    values: list[float],
) -> None:
    if isinstance(node, Num):
        values.append(_fraction_float(node.value))
    elif isinstance(node, Var):
        values.append(x)
    elif isinstance(node, Const):
        values.append(_constant(node.name))
    elif isinstance(node, Neg):
        pending.extend(((node, True), (node.operand, False)))
    elif isinstance(node, Fn):
        pending.extend(((node, True), (node.arg, False)))
    elif isinstance(node, Bin):
        pending.extend(((node, True), (node.right, False), (node.left, False)))
    else:  # pragma: no cover - `Expr` is a closed union
        assert_never(node)


def _finish_node(node: _CompoundExpr, values: list[float]) -> None:
    if isinstance(node, Neg):
        values.append(-values.pop())
    elif isinstance(node, Fn):
        values.append(_function(node.name, values.pop()))
    elif isinstance(node, Bin):
        right = values.pop()
        left = values.pop()
        values.append(_binary(node.op, left, right))
    else:  # pragma: no cover - `_CompoundExpr` is a closed union
        assert_never(node)


def _evaluate_expr(
    expr: Expr,
    x: float,
    budget: WorkBudget,
    *,
    charge_nodes: bool,
) -> float:
    pending: list[tuple[Expr, bool]] = [(expr, False)]
    values: list[float] = []
    while pending:
        node, ready = pending.pop()
        if ready:
            _finish_node(cast("_CompoundExpr", node), values)
        else:
            if charge_nodes:
                budget.charge(1)
            _start_node(node, x, pending, values)
    return values[0]


def evaluate_expr(expr: Expr, x: float, budget: WorkBudget) -> float:
    """Evaluate `expr` at `x`, rounding per node and charging each node once."""
    return _evaluate_expr(expr, x, budget, charge_nodes=True)


def materialize_grid(grid: Grid, budget: WorkBudget) -> tuple[float, ...]:
    """Materialize the normalized grid without expression-node charges.

    `Grid.stop` is inclusive for both constructors -- projection already normalized `arange`'s
    excluded bound onto the inclusive triple, and `arange` bounds are integers only (M13.3).
    """
    start = _evaluate_expr(grid.start, 0.0, budget, charge_nodes=False)
    stop = _evaluate_expr(grid.stop, 0.0, budget, charge_nodes=False)
    count = grid.samples
    delta = stop - start
    divisor = count - 1
    step = delta / divisor
    if step == 0.0:
        values = tuple((float(index) / divisor) * delta + start for index in range(count))
    else:
        values = tuple(float(index) * step + start for index in range(count))
    return (*values[:-1], stop)
