# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Independent exact oracle for formula sampling.

Shared production contract surface = expression AST/parser, canonical table types,
``FormulaPlotSpec``, ``VerificationLimits``, and ``DEFAULT_LIMITS``. Production evaluator,
work-meter, and quantization helpers remain unreachable. This oracle intentionally ignores
``max_formula_work_units`` and never yields or compares ``work_units``; production remains the
sole work-tariff accounting authority.

Evaluation uses an iterative postorder machine rather than recursive dispatch, and quantization
derives ties-to-even directly from integer quotient/remainder parity rather than Decimal context
or a production helper.
"""

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from itertools import pairwise
from typing import NoReturn

from verifier import canon
from verifier.expr import Abs, Binary, Expr, Neg, Number, Pow, Variable, parse_expr
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.schema import FormulaPlotSpec


class FormulaOracleError(Exception):
    """An independently detected semantic or resource rejection."""

    def __init__(self, message: str, *, check: str) -> None:
        super().__init__(message)
        self.check = check


@dataclass(frozen=True, slots=True)
class _RoundedInteger:
    """Nearest scaled integer plus the exact input sign, including rounded negative zero."""

    negative: bool
    magnitude: int


def _reject(check: str, message: str) -> NoReturn:
    raise FormulaOracleError(message, check=check)


def _round_half_even(value: Fraction, scale: int) -> _RoundedInteger:
    """Round ``value * 10**scale`` by exact quotient/remainder parity."""
    scaled_numerator = value.numerator * 10**scale
    negative = scaled_numerator < 0
    quotient, remainder = divmod(abs(scaled_numerator), value.denominator)
    doubled = remainder * 2
    if doubled > value.denominator or (doubled == value.denominator and quotient % 2 == 1):
        quotient += 1
    return _RoundedInteger(negative=negative, magnitude=quotient)


def _rounded_fraction(value: _RoundedInteger, scale: int) -> Fraction:
    signed = -value.magnitude if value.negative else value.magnitude
    return Fraction(signed, 10**scale)


def _rounded_decimal(value: _RoundedInteger, scale: int) -> Decimal:
    # The sign predicate is the explicit negative-zero canonicalization step. Keeping the
    # pre-round sign when magnitude == 0 would construct Decimal("-0..."), which is forbidden.
    sign = int(value.negative and value.magnitude != 0)
    digits = tuple(int(digit) for digit in str(value.magnitude))
    return Decimal((sign, digits, -scale))


def _checked(value: Fraction, limits: VerificationLimits) -> Fraction:
    bits = max(abs(value.numerator).bit_length(), value.denominator.bit_length())
    if bits > limits.max_formula_intermediate_bits:
        message = (
            f"exact intermediate needs {bits} bits; limit is {limits.max_formula_intermediate_bits}"
        )
        _reject("resource.formula_intermediate_bits", message)
    return value


def _bounded_power(base: Fraction, exponent: int, limits: VerificationLimits) -> Fraction:
    if exponent < 0:
        if base == 0:
            _reject("formula.values_defined", "zero cannot be raised to a negative exponent")
        base = _checked(Fraction(base.denominator, base.numerator), limits)
        exponent = -exponent

    result = Fraction(1)
    factor = base
    while exponent:
        if exponent & 1:
            result = _checked(result * factor, limits)
        exponent //= 2
        if exponent:
            factor = _checked(factor * factor, limits)
    return _checked(result, limits)


def _atom_value(
    node: Expr,
    x_value: Fraction,
    limits: VerificationLimits,
) -> Fraction | None:
    if isinstance(node, Number):
        return _checked(node.value, limits)
    if isinstance(node, Variable):
        return _checked(x_value, limits)
    return None


def _push_children(frames: list[tuple[Expr, bool]], node: Expr) -> None:
    frames.append((node, True))
    if isinstance(node, Binary):
        frames.append((node.right, False))
        frames.append((node.left, False))
    elif isinstance(node, (Neg, Abs)):
        frames.append((node.operand, False))
    elif isinstance(node, Pow):
        frames.append((node.base, False))
    else:
        msg = "an atom reached the oracle composite-node scheduler"
        raise TypeError(msg)


def _binary_result(node: Binary, left: Fraction, right: Fraction) -> Fraction:
    if node.op == "add":
        return left + right
    if node.op == "sub":
        return left - right
    if node.op == "mul":
        return left * right
    if right == 0:
        _reject("formula.values_defined", "formula division by zero")
    return left / right


def _finish_node(node: Expr, values: list[Fraction], limits: VerificationLimits) -> None:
    if isinstance(node, Neg):
        values.append(_checked(-values.pop(), limits))
        return
    if isinstance(node, Abs):
        values.append(_checked(abs(values.pop()), limits))
        return
    if isinstance(node, Pow):
        values.append(_bounded_power(values.pop(), node.exponent, limits))
        return
    if not isinstance(node, Binary):
        msg = "an atom reached the oracle composite-node reducer"
        raise TypeError(msg)
    right = values.pop()
    left = values.pop()
    values.append(_checked(_binary_result(node, left, right), limits))


def _eval_ast(root: Expr, x_value: Fraction, limits: VerificationLimits) -> Fraction:
    """Interpret one AST via an explicit postorder stack, never production evaluator code."""
    frames: list[tuple[Expr, bool]] = [(root, False)]
    values: list[Fraction] = []

    while frames:
        node, ready = frames.pop()
        if ready:
            _finish_node(node, values, limits)
            continue
        atom = _atom_value(node, x_value, limits)
        if atom is not None:
            values.append(atom)
        else:
            _push_children(frames, node)

    if len(values) != 1:
        msg = "oracle postorder machine ended with an invalid value-stack shape"
        raise AssertionError(msg)
    return values[0]


def evaluate_formula_oracle(
    spec: FormulaPlotSpec,
    *,
    parsed_ast: Expr | None = None,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> canon.Table:
    """Construct the exact canonical x/y table required by ``spec``.

    Sampling positions are exact Fractions. Each x is rounded independently to its declared
    scale, endpoint reproduction and strict increase are checked on those canonical values,
    and the expression is evaluated at that canonical x. Each exact y is rounded once.
    ``parsed_ast`` lets an agreement caller bind the exact AST also observed from production;
    omission keeps parser rejection and precedence self-validation available.
    """
    domain = spec.domain
    start = Fraction(domain.start)
    stop = Fraction(domain.stop)
    if start >= stop:
        _reject("formula.domain_ordered", "formula domain start must be less than stop")
    if domain.samples > limits.max_formula_samples:
        _reject(
            "resource.formula_samples",
            f"formula samples {domain.samples} exceed limit {limits.max_formula_samples}",
        )
    _checked(start, limits)
    _checked(stop, limits)
    if parsed_ast is None:
        parsed_ast = parse_expr(spec.formula, allowed_vars=frozenset({"x"}), limits=limits).ast

    denominator = domain.samples - 1
    span = _checked(stop - start, limits)
    rounded_x: list[_RoundedInteger] = []
    exact_x: list[Fraction] = []
    for index in range(domain.samples):
        ratio = _checked(Fraction(index, denominator), limits)
        offset = _checked(ratio * span, limits)
        position = _checked(start + offset, limits)
        rounded = _round_half_even(position, domain.x_scale)
        canonical = _checked(_rounded_fraction(rounded, domain.x_scale), limits)
        rounded_x.append(rounded)
        exact_x.append(canonical)

    if exact_x[0] != start or exact_x[-1] != stop:
        _reject(
            "formula.domain_bounded",
            "declared domain endpoints are not exactly representable at x_scale",
        )
    if any(left >= right for left, right in pairwise(exact_x)):
        _reject(
            "formula.sample_points_strictly_increasing",
            "canonical sample x values are not strictly increasing",
        )

    rows = []
    for x_fraction, x_rounded in zip(exact_x, rounded_x, strict=True):
        exact_y = _eval_ast(parsed_ast, x_fraction, limits)
        y_rounded = _round_half_even(exact_y, domain.y_scale)
        _checked(_rounded_fraction(y_rounded, domain.y_scale), limits)
        rows.append(
            (
                _rounded_decimal(x_rounded, domain.x_scale),
                _rounded_decimal(y_rounded, domain.y_scale),
            )
        )

    return canon.Table(
        columns=(
            canon.NumericColumn(name="x", scale=domain.x_scale),
            canon.NumericColumn(name="y", scale=domain.y_scale),
        ),
        rows=tuple(rows),
    )
