# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Deterministic, resource, and adversarial tests for the closed expression engine."""

import ast
import inspect
import os
import subprocess
import sys
from decimal import Decimal
from fractions import Fraction
from typing import Any, NoReturn, cast

import pytest

import verifier.expr as expr_module
from verifier.errors import VerificationError
from verifier.expr import (
    FUNCTION_NAMES,
    GRAMMAR_VERSION,
    Abs,
    Binary,
    Expr,
    ExpressionEvaluationError,
    Neg,
    Number,
    ParsedExpr,
    Pow,
    Variable,
    eval_expr,
    parse_expr,
    print_expr,
)
from verifier.limits import VerificationLimits
from verifier.work import WorkBudget, WorkBudgetExceededError

_ALLOWED = frozenset({"x", "x_1"})
_CANONICAL_CASES = [
    ("x**2", "(pow x 2)"),
    ("2*x + 1", "(add (mul 2 x) 1)"),
    ("x*(x - 1)*(x + 1)", "(mul (mul x (sub x 1)) (add x 1))"),
    ("1/(1 + x*x)", "(div 1 (add 1 (mul x x)))"),
    ("abs(x)", "(abs x)"),
    ("-x**2 + 3*x - 2", "(sub (add (neg (pow x 2)) (mul 3 x)) 2)"),
    ("-x**2", "(neg (pow x 2))"),
    ("1-2-3", "(sub (sub 1 2) 3)"),
    ("8/4/2", "(div (div 8 4) 2)"),
    ("2*3+4", "(add (mul 2 3) 4)"),
    ("2+3*4", "(add 2 (mul 3 4))"),
    ("abs(-x)*2", "(mul (abs (neg x)) 2)"),
    ("x**-3", "(pow x -3)"),
    ("x**+3", "(pow x 3)"),
    ("+x", "x"),
    ("++++x", "x"),
    ("007.500", "15/2"),
    ("7.5", "15/2"),
    ("(((x)))", "x"),
    ("2*x", "(mul 2 x)"),
    ("2 * x", "(mul 2 x)"),
    ("  2   *   x  ", "(mul 2 x)"),
    ("(-x)**2", "(pow (neg x) 2)"),
    ("--x", "(neg (neg x))"),
    ("x_1", "x_1"),
]


def _parse(
    source: str,
    *,
    allowed_vars: frozenset[str] = _ALLOWED,
    limits: VerificationLimits | None = None,
) -> ParsedExpr:
    active_limits = VerificationLimits() if limits is None else limits
    return parse_expr(source, allowed_vars=allowed_vars, limits=active_limits)


def _ast_metrics(node: Expr) -> tuple[int, int]:
    if isinstance(node, (Number, Variable)):
        return 1, 1
    if isinstance(node, (Neg, Abs)):
        child_nodes, child_depth = _ast_metrics(node.operand)
        return child_nodes + 1, child_depth + 1
    if isinstance(node, Pow):
        child_nodes, child_depth = _ast_metrics(node.base)
        return child_nodes + 1, child_depth + 1
    left_nodes, left_depth = _ast_metrics(node.left)
    right_nodes, right_depth = _ast_metrics(node.right)
    return left_nodes + right_nodes + 1, max(left_depth, right_depth) + 1


@pytest.mark.parametrize(("source", "expected"), _CANONICAL_CASES)
def test_parser_accepts_closed_grammar_with_pinned_canonical_ast(
    source: str, expected: str
) -> None:
    parsed = _parse(source)
    assert print_expr(parsed.ast) == expected
    assert "\n" not in expected


def test_subtraction_and_division_chains_are_left_associative() -> None:
    assert print_expr(_parse("1-2-3").ast) == "(sub (sub 1 2) 3)"
    assert print_expr(_parse("8/4/2").ast) == "(div (div 8 4) 2)"


def test_power_binds_tighter_than_unary_minus() -> None:
    parsed = _parse("-x**2")
    assert parsed.ast == Neg(operand=Pow(base=Variable(name="x"), exponent=2))
    assert print_expr(parsed.ast) == "(neg (pow x 2))"


def test_variable_identifier_invariant_closes_atom_composite_printer_collision() -> None:
    composite = Binary(
        op="add",
        left=Variable(name="x"),
        right=Number(value=Fraction(1)),
    )
    assert print_expr(composite) == "(add x 1)"
    with pytest.raises(ValueError, match="ASCII identifier"):
        Variable(name="(add x 1)")


def test_direct_numeric_nodes_obey_the_fixed_digit_magnitude_ceiling() -> None:
    magnitude_limit = 10**512
    assert magnitude_limit == expr_module._INTEGER_MAGNITUDE_LIMIT
    largest = magnitude_limit - 1
    enormous = 10**5000

    assert Number(value=Fraction(largest)).value == Fraction(largest)
    assert Number(value=Fraction(1, largest)).value == Fraction(1, largest)
    for value in (Fraction(magnitude_limit), Fraction(enormous)):
        with pytest.raises(ValueError, match="numerator"):
            Number(value=value)
    for value in (Fraction(1, magnitude_limit), Fraction(1, enormous)):
        with pytest.raises(ValueError, match="denominator"):
            Number(value=value)

    base = Variable(name="x")
    for exponent in (largest, -largest):
        assert Pow(base=base, exponent=exponent).exponent == exponent
    for exponent in (magnitude_limit, -magnitude_limit, enormous, -enormous):
        with pytest.raises(ValueError, match="exponent"):
            Pow(base=base, exponent=exponent)


@pytest.mark.parametrize("name", ["x", "x_1", "Revenue9"])
def test_parser_produced_variables_satisfy_public_identifier_invariant(name: str) -> None:
    parsed = _parse(name, allowed_vars=frozenset({name}))
    assert parsed.ast == Variable(name=name)


def test_ast_types_are_frozen_keyword_only_hashable_and_structurally_equal() -> None:
    one = Number(value=Fraction(1))
    x = Variable(name="x")
    left = Binary(op="add", left=x, right=one)
    same = Binary(op="add", left=Variable(name="x"), right=Number(value=Fraction(1)))
    different = Binary(op="add", left=one, right=x)
    assert left == same
    assert hash(left) == hash(same)
    assert left != different
    assert len({left, same, different}) == 2
    name = "name"  # dynamic name bypasses mypy's frozen-field check
    with pytest.raises(AttributeError):
        setattr(x, name, "y")
    with pytest.raises(TypeError):
        cast("Any", Variable)("x")


def test_ast_shapes_and_printer_cover_every_public_node_kind_without_folding() -> None:
    one = Number(value=Fraction(1))
    x = Variable(name="x")
    nodes: list[tuple[Expr, str]] = [
        (one, "1"),
        (x, "x"),
        (Neg(operand=x), "(neg x)"),
        (Abs(operand=x), "(abs x)"),
        (Pow(base=x, exponent=-2), "(pow x -2)"),
        (Binary(op="add", left=one, right=one), "(add 1 1)"),
        (Binary(op="sub", left=one, right=one), "(sub 1 1)"),
        (Binary(op="mul", left=one, right=one), "(mul 1 1)"),
        (Binary(op="div", left=one, right=one), "(div 1 1)"),
    ]
    assert [print_expr(node) for node, _ in nodes] == [expected for _, expected in nodes]


@pytest.mark.parametrize(
    ("source", "tokens", "nodes", "depth", "paren_depth"),
    [
        ("x", 1, 1, 1, 0),
        ("-x**2", 4, 3, 3, 0),
        ("abs(-x)*2", 7, 5, 4, 1),
        ("(((x)))", 7, 1, 1, 3),
        ("1-2-3", 5, 5, 3, 0),
        ("x**-3", 4, 2, 2, 0),
    ],
)
def test_parser_metrics_have_pinned_source_and_ast_semantics(
    source: str,
    tokens: int,
    nodes: int,
    depth: int,
    paren_depth: int,
) -> None:
    parsed = _parse(source)
    assert (parsed.tokens, parsed.nodes, parsed.depth, parsed.paren_depth) == (
        tokens,
        nodes,
        depth,
        paren_depth,
    )
    assert _ast_metrics(parsed.ast) == (nodes, depth)


_REJECT_CASES = [
    ("", "formula.grammar_allowed"),
    ("   ", "formula.grammar_allowed"),
    ("\t", "formula.grammar_allowed"),
    ("x\n", "formula.grammar_allowed"),
    ("x^2", "formula.grammar_allowed"),
    ("1.", "formula.grammar_allowed"),
    (".5", "formula.grammar_allowed"),
    ("1.a", "formula.grammar_allowed"),
    ("1..2", "formula.grammar_allowed"),
    ("+", "formula.grammar_allowed"),
    ("*x", "formula.grammar_allowed"),
    ("()", "formula.grammar_allowed"),
    ("(x", "formula.grammar_allowed"),
    ("(x y)", "formula.grammar_allowed"),
    ("x)", "formula.grammar_allowed"),
    ("2x", "formula.grammar_allowed"),
    ("2(x+1)", "formula.grammar_allowed"),
    ("x y", "formula.grammar_allowed"),
    ("x**2.5", "formula.grammar_allowed"),
    ("x**2.0", "formula.grammar_allowed"),
    ("x**y", "formula.grammar_allowed"),
    ("x**(2)", "formula.grammar_allowed"),
    ("x**", "formula.grammar_allowed"),
    ("x***2", "formula.grammar_allowed"),
    ("abs", "formula.grammar_allowed"),
    ("2**3**2", "formula.grammar_allowed"),
    ("x ** 2 ** 3", "formula.grammar_allowed"),
    ("sin(x)", "formula.functions_allowed"),
    ("y + 1", "formula.names_allowed"),
    ("__import__('os')", "formula.grammar_allowed"),
    ("x; import os", "formula.grammar_allowed"),
    ("eval(x)", "formula.functions_allowed"),
    ("x.__class__", "formula.grammar_allowed"),
    ("abs(x)(1)", "formula.grammar_allowed"),
    ("lambda x: x", "formula.grammar_allowed"),
    ("sympify(x)", "formula.functions_allowed"),
    ("x if x else 1", "formula.grammar_allowed"),
    ("0x10", "formula.grammar_allowed"),
    ("1e3", "formula.grammar_allowed"),
    ("\ud800", "formula.grammar_allowed"),
]


@pytest.mark.parametrize(("source", "check"), _REJECT_CASES)
def test_parser_rejects_every_other_grammar_and_injection_shape(source: str, check: str) -> None:
    with pytest.raises(VerificationError) as exc_info:
        _parse(source)
    assert exc_info.value.check == check
    assert "position" in str(exc_info.value)


@pytest.mark.parametrize("source", ["x**65", "x**-65"])
def test_exponent_magnitude_boundary_plus_one_is_structured(source: str) -> None:
    assert print_expr(_parse("x**64").ast) == "(pow x 64)"
    assert print_expr(_parse("x**-64").ast) == "(pow x -64)"
    with pytest.raises(VerificationError) as exc_info:
        _parse(source)
    assert exc_info.value.check == "formula.exponents_bounded"
    assert "limit 64" in str(exc_info.value)
    assert "position" in str(exc_info.value)


_RESOURCE_CASES = [
    (
        "x ",
        "x  ",
        frozenset({"x"}),
        VerificationLimits(max_formula_bytes=2),
        ("resource.formula_bytes", 2),
    ),
    (
        "x**-2",
        "-x**-2",
        frozenset({"x"}),
        VerificationLimits(max_formula_tokens=4),
        ("resource.formula_tokens", 4),
    ),
    (
        "99",
        "999",
        frozenset({"x"}),
        VerificationLimits(max_formula_digits=2),
        ("resource.formula_digits", 2),
    ),
    (
        "yy",
        "yyy",
        frozenset({"yy"}),
        VerificationLimits(max_formula_identifier_bytes=2),
        ("resource.formula_identifier_bytes", 2),
    ),
    (
        "--x",
        "---x",
        frozenset({"x"}),
        VerificationLimits(max_formula_ast_nodes=3),
        ("resource.formula_ast_nodes", 3),
    ),
    (
        "--x",
        "---x",
        frozenset({"x"}),
        VerificationLimits(max_formula_ast_depth=3),
        ("resource.formula_ast_depth", 3),
    ),
    (
        "((x))",
        "(((x)))",
        frozenset({"x"}),
        VerificationLimits(max_formula_paren_depth=2),
        ("resource.formula_paren_depth", 2),
    ),
]


@pytest.mark.parametrize(
    ("boundary_source", "over_source", "allowed_vars", "limits", "expected"),
    _RESOURCE_CASES,
)
def test_each_parser_resource_bound_admits_boundary_and_blocks_boundary_plus_one(
    boundary_source: str,
    over_source: str,
    allowed_vars: frozenset[str],
    limits: VerificationLimits,
    expected: tuple[str, int],
) -> None:
    check, bound = expected
    assert isinstance(_parse(boundary_source, allowed_vars=allowed_vars, limits=limits), ParsedExpr)
    with pytest.raises(VerificationError) as exc_info:
        _parse(over_source, allowed_vars=allowed_vars, limits=limits)
    assert exc_info.value.check == check
    message = str(exc_info.value)
    assert "position" in message
    assert "limit" in message
    assert str(bound) in message


def test_token_limit_blocks_before_boundary_plus_one_is_appended() -> None:
    limits = VerificationLimits(max_formula_tokens=4)
    assert _parse("x**-2", limits=limits).tokens == 4
    with pytest.raises(VerificationError) as exc_info:
        _parse("-x**-2", limits=limits)
    assert exc_info.value.check == "resource.formula_tokens"


def test_ast_depth_policy_has_an_absolute_structural_ceiling() -> None:
    ceiling = 64
    assert ceiling == expr_module._MAX_FORMULA_AST_DEPTH
    assert _parse("x", limits=VerificationLimits(max_formula_ast_depth=ceiling)).depth == 1
    with pytest.raises(ValueError, match="max_formula_ast_depth"):
        _parse("x", limits=VerificationLimits(max_formula_ast_depth=ceiling + 1))


def test_parenthesis_depth_policy_has_an_absolute_structural_ceiling() -> None:
    ceiling = 64
    assert ceiling == expr_module._MAX_FORMULA_PAREN_DEPTH
    assert _parse("x", limits=VerificationLimits(max_formula_paren_depth=ceiling)).depth == 1
    with pytest.raises(ValueError, match="max_formula_paren_depth"):
        _parse("x", limits=VerificationLimits(max_formula_paren_depth=ceiling + 1))


def test_literal_digit_policy_has_an_absolute_conversion_ceiling() -> None:
    ceiling = 512
    assert ceiling == expr_module._MAX_FORMULA_DIGITS
    assert _parse("1", limits=VerificationLimits(max_formula_digits=ceiling)).depth == 1
    with pytest.raises(ValueError, match="max_formula_digits"):
        _parse("1", limits=VerificationLimits(max_formula_digits=ceiling + 1))


def test_parser_unsafe_policy_is_rejected_before_the_lexer_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(expr_module, "_lex", cast("Any", pytest.fail))
    cases = (
        (
            "max_formula_ast_depth",
            VerificationLimits(max_formula_ast_depth=65),
        ),
        (
            "max_formula_paren_depth",
            VerificationLimits(max_formula_paren_depth=65),
        ),
        ("max_formula_digits", VerificationLimits(max_formula_digits=513)),
    )
    for field, limits in cases:
        with pytest.raises(ValueError, match=field):
            _parse("x", limits=limits)


def test_every_recursive_path_is_total_at_the_absolute_structural_ceilings() -> None:
    limits = VerificationLimits(max_formula_ast_depth=64, max_formula_paren_depth=64)

    unary = _parse("-" * 63 + "x", limits=limits)
    assert (unary.depth, unary.paren_depth) == (64, 0)

    grouped = _parse("(" * 64 + "x" + ")" * 64, limits=limits)
    assert (grouped.depth, grouped.paren_depth) == (1, 64)

    combined = _parse("-(" * 63 + "x" + ")" * 63, limits=limits)
    assert (combined.depth, combined.paren_depth) == (64, 63)

    absolute = _parse("abs(" * 63 + "x" + ")" * 63, limits=limits)
    assert (absolute.depth, absolute.paren_depth) == (64, 63)

    joint_abs_group = _parse("abs(" * 63 + "(x)" + ")" * 63, limits=limits)
    assert (joint_abs_group.depth, joint_abs_group.paren_depth) == (64, 64)

    joint_neg_group = _parse("-(" * 63 + "(x)" + ")" * 63, limits=limits)
    assert (joint_neg_group.depth, joint_neg_group.paren_depth) == (64, 64)

    joint_group_power = _parse("abs(" * 62 + "((x**1))" + ")" * 62, limits=limits)
    assert (joint_group_power.depth, joint_group_power.paren_depth) == (64, 64)


def test_printer_handles_maximally_admitted_left_and_right_skew() -> None:
    limits = VerificationLimits(max_formula_ast_depth=64, max_formula_paren_depth=64)

    left = _parse("+".join(["x"] * 64), limits=limits)
    assert left.depth == 64
    assert print_expr(left.ast).count("(add ") == 63

    right = _parse("abs(" * 63 + "x" + ")" * 63, limits=limits)
    assert right.depth == 64
    assert print_expr(right.ast).count("(abs ") == 63


def test_literal_and_exponent_conversion_are_total_at_the_digit_ceiling() -> None:
    digits = "9" * 512
    fractional_digits = "9" * 511
    max_exponent = 10**512 - 1
    limits = VerificationLimits(
        max_formula_bytes=1024,
        max_formula_digits=512,
        max_formula_exponent=max_exponent,
    )

    literal = _parse(digits, limits=limits)
    assert isinstance(literal.ast, Number)
    assert literal.ast.value == Fraction(max_exponent)

    fractional = _parse("0." + fractional_digits, limits=limits)
    assert fractional.ast == Number(value=Fraction(10**511 - 1, 10**511))

    power = _parse("x**" + digits, limits=limits)
    assert power.ast == Pow(base=Variable(name="x"), exponent=max_exponent)


def test_exact_utf8_byte_count_is_checked_after_the_character_upper_bound() -> None:
    limits = VerificationLimits(max_formula_bytes=1)
    with pytest.raises(VerificationError) as char_exc:
        _parse("xx", limits=limits)
    with pytest.raises(VerificationError) as byte_exc:
        _parse("é", limits=limits)
    assert char_exc.value.check == "resource.formula_bytes"
    assert byte_exc.value.check == "resource.formula_bytes"
    assert "position 2" in str(char_exc.value)
    assert "position 1" in str(byte_exc.value)


def test_digit_bound_also_applies_to_integer_exponent_literals() -> None:
    limits = VerificationLimits(max_formula_digits=2)
    assert print_expr(_parse("x**64", limits=limits).ast) == "(pow x 64)"
    with pytest.raises(VerificationError) as exc_info:
        _parse("x**100", limits=limits)
    assert exc_info.value.check == "resource.formula_digits"


def test_digit_bound_counts_fractional_digits_but_not_the_decimal_point() -> None:
    limits = VerificationLimits(max_formula_digits=2)
    assert print_expr(_parse("1.2", limits=limits).ast) == "6/5"
    with pytest.raises(VerificationError) as exc_info:
        _parse("1.23", limits=limits)
    assert exc_info.value.check == "resource.formula_digits"


def test_stack_guards_fire_before_host_recursion_can_be_exhausted() -> None:
    parens = "(" * 200 + "x" + ")" * 200
    with pytest.raises(VerificationError) as paren_exc:
        _parse(parens, limits=VerificationLimits(max_formula_tokens=500))
    assert paren_exc.value.check == "resource.formula_paren_depth"

    unary = "-" * 2_000 + "x"
    shallow = VerificationLimits(
        max_formula_bytes=3_000,
        max_formula_tokens=3_000,
        max_formula_ast_depth=1,
    )
    assert _parse("x", limits=shallow).depth == 1
    with pytest.raises(VerificationError) as depth_exc:
        _parse(unary, limits=shallow)
    assert depth_exc.value.check == "resource.formula_ast_depth"


@pytest.mark.parametrize(
    ("allowed_vars", "limits", "message"),
    [
        (cast("frozenset[str]", {"x"}), VerificationLimits(), "frozenset"),
        (frozenset(), VerificationLimits(), "empty"),
        (
            cast("frozenset[str]", frozenset({1})),
            VerificationLimits(),
            "strings",
        ),
        (frozenset({"1x"}), VerificationLimits(), "identifier"),
        (
            frozenset({"long"}),
            VerificationLimits(max_formula_identifier_bytes=3),
            "max_formula_identifier_bytes",
        ),
        (frozenset({"abs"}), VerificationLimits(), "reserved"),
    ],
)
def test_allowed_variable_contract_rejects_every_trusted_caller_misuse(
    allowed_vars: frozenset[str], limits: VerificationLimits, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _parse("x", allowed_vars=allowed_vars, limits=limits)


# --- exact interpreter + shared work meter ----------------------------------
def _evaluate_expression(
    source: str,
    binding: dict[str, Decimal | Fraction] | None = None,
    *,
    limits: VerificationLimits | None = None,
) -> tuple[Fraction, int]:
    active_limits = VerificationLimits() if limits is None else limits
    budget = WorkBudget(limit=active_limits.max_formula_work_units)
    value = eval_expr(
        _parse(source, limits=active_limits).ast, binding or {}, active_limits, budget=budget
    )
    return value, budget.consumed


@pytest.mark.parametrize(
    ("source", "binding", "expected", "expected_work"),
    [
        ("1", {}, Fraction(1), 1),
        ("x", {"x": Decimal("1.25")}, Fraction(5, 4), 1),
        ("-x", {"x": Fraction(5, 4)}, Fraction(-5, 4), 2),
        ("abs(-x)", {"x": Fraction(5, 4)}, Fraction(5, 4), 3),
        ("x+2", {"x": Fraction(3)}, Fraction(5), 3),
        ("x-2", {"x": Fraction(3)}, Fraction(1), 3),
        ("x*2", {"x": Fraction(3)}, Fraction(6), 3),
        ("x/2", {"x": Fraction(3)}, Fraction(3, 2), 3),
        ("2**3", {}, Fraction(8), 5),
        ("2**-3", {}, Fraction(1, 8), 5),
        ("0**0", {}, Fraction(1), 2),
        ("1**64", {}, Fraction(1), 66),
        ("x+x_1", {"x": Fraction(2), "x_1": Fraction(3)}, Fraction(5), 3),
    ],
)
def test_eval_expr_covers_every_node_with_exact_literal_work_counts(
    source: str,
    binding: dict[str, Decimal | Fraction],
    expected: Fraction,
    expected_work: int,
) -> None:
    assert _evaluate_expression(source, binding) == (expected, expected_work)


def test_work_budget_admits_boundary_and_refuses_atomically() -> None:
    budget = WorkBudget(limit=3)
    budget.charge(0)  # shared dataset accounting legitimately has zero-cost empty stages
    budget.charge(3)
    with pytest.raises(WorkBudgetExceededError) as exc_info:
        budget.charge(1)
    assert (exc_info.value.limit, exc_info.value.consumed, exc_info.value.required) == (3, 3, 1)
    assert str(exc_info.value) == "work limit 3: 3 consumed + 1 required"
    assert budget.consumed == 3


def test_work_budget_accepts_neutral_constructor_boundaries() -> None:
    at_limit = WorkBudget(limit=1, consumed=1)
    assert at_limit.consumed == 1

    zero = WorkBudget(limit=0)
    assert zero.consumed == 0
    with pytest.raises(WorkBudgetExceededError) as exc_info:
        zero.charge(1)
    assert (exc_info.value.limit, exc_info.value.consumed, exc_info.value.required) == (0, 0, 1)
    assert zero.consumed == 0


def test_work_budget_rejects_invalid_trusted_state_and_charges() -> None:
    for limit in (-1, cast("int", 1.5), cast("int", bool(1))):
        with pytest.raises(ValueError, match="limit"):
            WorkBudget(limit=limit)
    for consumed in (-1, 2, cast("int", 0.5), cast("int", bool(0))):
        with pytest.raises(ValueError, match="consumption"):
            WorkBudget(limit=1, consumed=consumed)
    budget = WorkBudget(limit=1)
    for required in (-1, cast("int", 0.5), cast("int", bool(1))):
        with pytest.raises(ValueError, match="required"):
            budget.charge(required)
    assert budget.consumed == 0


@pytest.mark.parametrize(
    ("node", "admitted", "refused", "operation"),
    [
        (
            Number(value=Fraction(1)),
            (1, Fraction(1), (Fraction(1),)),
            (1, 1, ()),
            "number",
        ),
        (
            Neg(operand=Number(value=Fraction(1))),
            (2, Fraction(-1), (Fraction(1), Fraction(-1))),
            (1, 0, (Fraction(1),)),
            "negation",
        ),
        (
            Abs(operand=Number(value=Fraction(1))),
            (2, Fraction(1), (Fraction(1), Fraction(1))),
            (1, 0, (Fraction(1),)),
            "absolute value",
        ),
    ],
)
def test_node_charge_precedes_its_intermediate_admission(
    node: Expr,
    admitted: tuple[int, Fraction, tuple[Fraction, ...]],
    refused: tuple[int, int, tuple[Fraction, ...]],
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admitted_limit, expected, admitted_checks = admitted
    refused_limit, refused_consumed, refused_checks = refused
    original_bounded_fraction = expr_module._bounded_fraction
    checked: list[Fraction] = []

    def _observe(
        value: Fraction,
        limits: VerificationLimits,
        budget: WorkBudget,
    ) -> Fraction:
        checked.append(value)
        return original_bounded_fraction(value, limits, budget)

    monkeypatch.setattr(expr_module, "_bounded_fraction", _observe)

    admitted_limits = VerificationLimits(max_formula_work_units=admitted_limit)
    admitted_budget = WorkBudget(limit=admitted_limit)
    assert eval_expr(node, {}, admitted_limits, budget=admitted_budget) == expected
    assert admitted_budget.consumed == admitted_limit
    assert tuple(checked) == admitted_checks

    checked.clear()
    refused_limits = VerificationLimits(max_formula_work_units=refused_limit)
    refused_budget = WorkBudget(limit=refused_limit, consumed=refused_consumed)
    with pytest.raises(ExpressionEvaluationError) as exc_info:
        eval_expr(node, {}, refused_limits, budget=refused_budget)
    assert exc_info.value.check == "resource.formula_work"
    assert str(exc_info.value) == (
        f"formula work limit {refused_limit} would be exceeded before {operation}: "
        f"{refused_limit} consumed + 1 required"
    )
    assert exc_info.value.work_units == refused_limit
    assert refused_budget.consumed == refused_limit
    assert tuple(checked) == refused_checks


def test_expression_work_refusal_precedes_the_guarded_binary_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = False

    def _bomb(*_args: object, **_kwargs: object) -> NoReturn:
        nonlocal started
        started = True
        msg = "binary arithmetic started after work refusal"
        raise AssertionError(msg)

    monkeypatch.setattr(expr_module, "_apply_binary", _bomb)
    limits = VerificationLimits(max_formula_work_units=2)
    budget = WorkBudget(limit=2)
    with pytest.raises(ExpressionEvaluationError) as exc_info:
        eval_expr(_parse("x+1", limits=limits).ast, {"x": Fraction(2)}, limits, budget=budget)
    assert exc_info.value.check == "resource.formula_work"
    assert exc_info.value.work_units == 2
    assert budget.consumed == 2
    assert started is False


@pytest.mark.parametrize(("source", "expected_work"), [("1/0", 3), ("0**-1", 3)])
def test_undefined_operations_retain_their_admitted_work(source: str, expected_work: int) -> None:
    limits = VerificationLimits()
    budget = WorkBudget(limit=limits.max_formula_work_units)
    with pytest.raises(ExpressionEvaluationError) as exc_info:
        eval_expr(_parse(source).ast, {}, limits, budget=budget)
    assert exc_info.value.check == "formula.values_defined"
    assert exc_info.value.work_units == expected_work
    assert budget.consumed == expected_work


def test_eval_expr_rejects_invalid_trusted_binding_and_budget_contracts() -> None:
    node = _parse("x").ast
    limits = VerificationLimits(max_formula_work_units=2)

    missing_budget = WorkBudget(limit=2)
    with pytest.raises(ValueError, match="missing variable"):
        eval_expr(node, {}, limits, budget=missing_budget)
    assert missing_budget.consumed == 1

    for value, error, message in [
        (Decimal("NaN"), ValueError, "finite"),
        (cast("Decimal | Fraction", 1), TypeError, "Decimal or Fraction"),
    ]:
        budget = WorkBudget(limit=2)
        with pytest.raises(error, match=message):
            eval_expr(node, {"x": value}, limits, budget=budget)
        assert budget.consumed == 1

    mismatched = WorkBudget(limit=1)
    with pytest.raises(ValueError, match="does not match"):
        eval_expr(node, {"x": Fraction(1)}, limits, budget=mismatched)
    assert mismatched.consumed == 0


def test_numerator_and_denominator_bit_bounds_hold_at_the_joint_corner() -> None:
    limits = VerificationLimits(max_formula_intermediate_bits=4)
    assert _evaluate_expression("x", {"x": Fraction(15, 8)}, limits=limits) == (
        Fraction(15, 8),
        1,
    )
    for value in (Fraction(17, 8), Fraction(15, 16)):
        budget = WorkBudget(limit=limits.max_formula_work_units)
        with pytest.raises(ExpressionEvaluationError) as exc_info:
            eval_expr(_parse("x", limits=limits).ast, {"x": value}, limits, budget=budget)
        assert exc_info.value.check == "resource.formula_intermediate_bits"
        assert exc_info.value.work_units == 1


def test_each_arithmetic_result_is_checked_at_the_intermediate_boundary() -> None:
    limits = VerificationLimits(max_formula_intermediate_bits=4)
    for source, expected_work in [("15+1", 3), ("(1/8)/2", 5)]:
        budget = WorkBudget(limit=limits.max_formula_work_units)
        with pytest.raises(ExpressionEvaluationError) as exc_info:
            eval_expr(_parse(source, limits=limits).ast, {}, limits, budget=budget)
        assert exc_info.value.check == "resource.formula_intermediate_bits"
        assert exc_info.value.work_units == expected_work


def test_number_intermediate_admission_precedes_cancellation() -> None:
    limits = VerificationLimits(max_formula_intermediate_bits=4)
    admitted = Binary(
        op="sub",
        left=Number(value=Fraction(15)),
        right=Number(value=Fraction(15)),
    )
    admitted_budget = WorkBudget(limit=limits.max_formula_work_units)
    assert eval_expr(admitted, {}, limits, budget=admitted_budget) == 0
    assert admitted_budget.consumed == 3

    rejected = Binary(
        op="sub",
        left=Number(value=Fraction(16)),
        right=Number(value=Fraction(15)),
    )
    rejected_budget = WorkBudget(limit=limits.max_formula_work_units)
    with pytest.raises(ExpressionEvaluationError) as exc_info:
        eval_expr(rejected, {}, limits, budget=rejected_budget)
    assert exc_info.value.check == "resource.formula_intermediate_bits"
    assert str(exc_info.value) == "formula intermediate needs 5 bits; limit is 4"
    assert exc_info.value.work_units == 1
    assert rejected_budget.consumed == 1


def test_transient_intermediate_is_rejected_before_later_cancellation() -> None:
    limits = VerificationLimits(max_formula_intermediate_bits=4)
    assert _evaluate_expression("(14+1)-15", limits=limits) == (Fraction(0), 5)

    budget = WorkBudget(limit=limits.max_formula_work_units)
    with pytest.raises(ExpressionEvaluationError) as exc_info:
        eval_expr(_parse("(15+1)-15", limits=limits).ast, {}, limits, budget=budget)
    assert exc_info.value.check == "resource.formula_intermediate_bits"
    assert str(exc_info.value) == "formula intermediate needs 5 bits; limit is 4"
    assert exc_info.value.work_units == 3
    assert budget.consumed == 3


def test_binary_evaluation_reports_the_left_failure_before_the_right_failure() -> None:
    limits = VerificationLimits(max_formula_intermediate_bits=4)
    right = Pow(base=Number(value=Fraction(0)), exponent=-1)

    right_budget = WorkBudget(limit=limits.max_formula_work_units)
    with pytest.raises(ExpressionEvaluationError) as right_exc:
        eval_expr(right, {}, limits, budget=right_budget)
    assert right_exc.value.check == "formula.values_defined"
    assert str(right_exc.value) == "formula value is undefined: zero to a negative power"
    assert right_exc.value.work_units == 3
    assert right_budget.consumed == 3

    joint = Binary(
        op="add",
        left=Number(value=Fraction(16)),
        right=right,
    )
    joint_budget = WorkBudget(limit=limits.max_formula_work_units)
    with pytest.raises(ExpressionEvaluationError) as joint_exc:
        eval_expr(joint, {}, limits, budget=joint_budget)
    assert joint_exc.value.check == "resource.formula_intermediate_bits"
    assert str(joint_exc.value) == "formula intermediate needs 5 bits; limit is 4"
    assert joint_exc.value.work_units == 1
    assert joint_budget.consumed == 1


@pytest.mark.parametrize(
    ("source", "expected", "expected_work"),
    [("2**3", Fraction(8), 5), ("2**-3", Fraction(1, 8), 5)],
)
def test_power_admits_positive_and_reciprocal_joint_bit_boundaries(
    source: str, expected: Fraction, expected_work: int
) -> None:
    assert _evaluate_expression(
        source,
        limits=VerificationLimits(max_formula_intermediate_bits=4),
    ) == (expected, expected_work)


def test_power_node_has_its_own_intermediate_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_bounded_fraction = expr_module._bounded_fraction
    checked: list[Fraction] = []

    def _observe(
        value: Fraction,
        limits: VerificationLimits,
        budget: WorkBudget,
    ) -> Fraction:
        checked.append(value)
        return original_bounded_fraction(value, limits, budget)

    monkeypatch.setattr(expr_module, "_bounded_fraction", _observe)
    limits = VerificationLimits(
        max_formula_work_units=3,
        max_formula_intermediate_bits=2,
    )
    budget = WorkBudget(limit=3)
    node = Pow(base=Number(value=Fraction(2)), exponent=1)
    assert eval_expr(node, {}, limits, budget=budget) == 2
    assert budget.consumed == 3
    assert checked == [Fraction(2), Fraction(2)]


@pytest.mark.parametrize(
    ("legal", "over", "bits"),
    [
        (("2**1", Fraction(2), 3), ("2**2", 4), 2),
        (("2**-1", Fraction(1, 2), 3), ("2**-2", 4), 2),
        (("11**2", Fraction(121), 4), ("12**2", 4), 7),
        (("11**-2", Fraction(1, 121), 4), ("12**-2", 4), 7),
    ],
)
def test_power_preflight_admits_quotient_equality_and_rejects_its_neighbor(
    legal: tuple[str, Fraction, int],
    over: tuple[str, int],
    bits: int,
) -> None:
    source, expected, expected_work = legal
    over_source, over_work = over
    limits = VerificationLimits(max_formula_intermediate_bits=bits)
    assert _evaluate_expression(source, limits=limits) == (expected, expected_work)

    budget = WorkBudget(limit=limits.max_formula_work_units)
    with pytest.raises(ExpressionEvaluationError) as exc_info:
        eval_expr(_parse(over_source, limits=limits).ast, {}, limits, budget=budget)
    assert exc_info.value.check == "resource.formula_intermediate_bits"
    assert str(exc_info.value) == f"formula power cannot fit intermediate bit limit {bits}"
    assert exc_info.value.work_units == over_work
    assert budget.consumed == over_work


@pytest.mark.parametrize(
    ("source", "expected_work"),
    [("2**4", 6), ("2**-4", 6), ("3**3", 5)],
)
def test_power_growth_is_refused_before_exact_power_allocation(
    source: str,
    expected_work: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _bomb(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "oversized exact power was allocated"
        raise AssertionError(msg)

    monkeypatch.setattr(expr_module, "_pow_exact", _bomb)
    limits = VerificationLimits(max_formula_intermediate_bits=4)
    budget = WorkBudget(limit=limits.max_formula_work_units)
    with pytest.raises(ExpressionEvaluationError) as exc_info:
        eval_expr(_parse(source, limits=limits).ast, {}, limits, budget=budget)
    assert exc_info.value.check == "resource.formula_intermediate_bits"
    assert exc_info.value.work_units == expected_work


def test_power_preflight_has_no_exact_allocation_before_the_single_power_site() -> None:
    tree = ast.parse(inspect.getsource(expr_module))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    power_sites = {
        name: [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow)
        ]
        for name, function in functions.items()
    }
    assert power_sites["_component_power_fits"] == []
    assert {name for name, sites in power_sites.items() if sites} == {"_pow_exact"}
    assert len(power_sites["_pow_exact"]) == 1


_LOW_INT_STRING_LIMIT_PROGRAM = """
from fractions import Fraction

from verifier.expr import eval_expr, parse_expr
from verifier.limits import VerificationLimits
from verifier.work import WorkBudget

limits = VerificationLimits(
    max_formula_exponent=4095,
    max_formula_intermediate_bits=4096,
    max_formula_work_units=4097,
)
budget = WorkBudget(limit=4097)
parsed = parse_expr("2**4095", allowed_vars=frozenset({"x"}), limits=limits)
value = eval_expr(parsed.ast, {}, limits, budget=budget)
assert value == Fraction(1 << 4095)
print(value.numerator.bit_length(), value.denominator, budget.consumed)
"""


def test_fraction_bit_admission_ignores_python_integer_string_limit() -> None:
    result = subprocess.run(  # noqa: S603 — fixed interpreter and literal child program
        [sys.executable, "-c", _LOW_INT_STRING_LIMIT_PROGRAM],
        capture_output=True,
        check=True,
        env={**os.environ, "PYTHONINTMAXSTRDIGITS": "640"},
        text=True,
    )
    assert result.stdout == "4096 1 4097\n"


def test_direct_ast_exponent_policy_fails_before_base_evaluation() -> None:
    limits = VerificationLimits(max_formula_exponent=2, max_formula_intermediate_bits=1)
    node = Pow(base=Number(value=Fraction(2)), exponent=3)
    budget = WorkBudget(limit=limits.max_formula_work_units)
    with pytest.raises(ExpressionEvaluationError) as exc_info:
        eval_expr(node, {}, limits, budget=budget)
    assert exc_info.value.check == "formula.exponents_bounded"
    assert exc_info.value.work_units == 0


def test_interpreter_function_dispatch_matches_the_parser_allowlist_exactly() -> None:
    assert frozenset({"abs"}) == FUNCTION_NAMES
    assert _evaluate_expression("abs(x)", {"x": Fraction(-2)}) == (Fraction(2), 2)
    for name in ("sin", "cos", "tan", "exp", "log", "sqrt"):
        with pytest.raises(VerificationError) as exc_info:
            _parse(f"{name}(x)")
        assert exc_info.value.check == "formula.functions_allowed"


def test_failure_messages_never_echo_an_unbounded_model_token() -> None:
    source = "z" * 100
    with pytest.raises(VerificationError) as exc_info:
        _parse(
            source,
            allowed_vars=frozenset({"x"}),
            limits=VerificationLimits(max_formula_identifier_bytes=16),
        )
    message = str(exc_info.value)
    assert exc_info.value.check == "resource.formula_identifier_bytes"
    assert source not in message
    assert len(message) < 160


def test_module_uses_only_the_closed_engine_dependencies_and_no_execution_surface() -> None:
    tree = ast.parse(inspect.getsource(expr_module))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    )
    assert imported == {
        "collections.abc",
        "decimal",
        "fractions",
        "typing",
        "msgspec",
        "verifier.errors",
        "verifier.limits",
        "verifier.work",
    }

    forbidden = {
        "eval",
        "exec",
        "compile",
        "__import__",
        "getattr",
        "setattr",
        "globals",
        "locals",
        "vars",
        "open",
        "input",
        "subprocess",
        "os",
        "sys",
        "sympy",
        "ast",
    }
    referenced = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    referenced.update(
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
    )
    assert referenced.isdisjoint(forbidden)


def test_public_constants_pin_the_formula_provenance_contract() -> None:
    assert GRAMMAR_VERSION == "expr-0.1"
    assert frozenset({"abs"}) == FUNCTION_NAMES
    with pytest.raises(AttributeError):
        cast("Any", FUNCTION_NAMES).add("sin")
