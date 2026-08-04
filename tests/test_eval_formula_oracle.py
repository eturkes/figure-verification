# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Independent exact-oracle validation and production agreement for formula eval.

Agreement binds equivalent parser AST values and compares canonical table structure, raw Decimal
state, and rejection check names. This is an end-to-end outcome comparison over the public
evaluator boundary, not evidence for any individual production admission site. It intentionally
excludes work-tariff acceptance and
``work_units``; production remains the sole accounting authority.
"""

import ast
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import msgspec
import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from hypothesis.strategies import DrawFn

from formula_oracle import FormulaOracleError, evaluate_formula_oracle
from verifier import canon
from verifier.errors import VerificationError
from verifier.eval import evaluate_formula_run
from verifier.expr import Abs, Binary, Expr, Neg, Number, Pow, Variable, parse_expr
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.schema import FormulaPlotSpec, decode_formula_spec

_ROOT = Path(__file__).resolve().parent.parent
_FORMULA_GOOD = _ROOT / "examples" / "formula_good_specs"
_FORMULA_BAD = _ROOT / "examples" / "formula_bad_specs"
_CORPUS_FILES = (
    "f01_square.json",
    "f02_linear.json",
    "f03_cubic.json",
    "f04_rational.json",
    "f05_absolute_value.json",
    "f06_quadratic.json",
)
_CORPUS_REJECTIONS = (
    ("fb17_reversed_domain.json", "formula.domain_ordered"),
    ("fb18_division_by_zero.json", "formula.values_defined"),
    ("fb20_sample_collision.json", "formula.sample_points_strictly_increasing"),
)


@dataclass(frozen=True, slots=True)
class _LiteralCase:
    name: str
    formula: str
    start: str
    stop: str
    x_scale: int
    y_scale: int
    expected: tuple[tuple[str, str], ...]


_LITERAL_CASES = (
    _LiteralCase(
        "constant",
        "1",
        "0",
        "2",
        0,
        0,
        (("0", "1"), ("1", "1"), ("2", "1")),
    ),
    _LiteralCase(
        "identity-negative",
        "x",
        "-1",
        "1",
        0,
        0,
        (("-1", "-1"), ("0", "0"), ("1", "1")),
    ),
    _LiteralCase(
        "decimal-addition",
        "x + 0.25",
        "0",
        "1",
        1,
        2,
        (("0.0", "0.25"), ("0.5", "0.75"), ("1.0", "1.25")),
    ),
    _LiteralCase(
        "subtraction",
        "2 - x",
        "0",
        "2",
        0,
        0,
        (("0", "2"), ("1", "1"), ("2", "0")),
    ),
    _LiteralCase(
        "multiplication",
        "3*x",
        "-1",
        "1",
        0,
        0,
        (("-1", "-3"), ("0", "0"), ("1", "3")),
    ),
    _LiteralCase(
        "exact-division",
        "x/2",
        "0",
        "2",
        0,
        1,
        (("0", "0.0"), ("1", "0.5"), ("2", "1.0")),
    ),
    _LiteralCase(
        "absolute-value",
        "abs(x)",
        "-2",
        "2",
        0,
        0,
        (("-2", "2"), ("-1", "1"), ("0", "0"), ("1", "1"), ("2", "2")),
    ),
    _LiteralCase(
        "unary-minus-power",
        "-x**2",
        "-2",
        "2",
        0,
        0,
        (("-2", "-4"), ("-1", "-1"), ("0", "0"), ("1", "-1"), ("2", "-4")),
    ),
    _LiteralCase(
        "cube",
        "x**3",
        "-2",
        "2",
        0,
        0,
        (("-2", "-8"), ("-1", "-1"), ("0", "0"), ("1", "1"), ("2", "8")),
    ),
    _LiteralCase("zero-exponent", "x**0", "1", "2", 0, 0, (("1", "1"), ("2", "1"))),
    _LiteralCase(
        "negative-exponent",
        "x**-1",
        "1",
        "2",
        1,
        2,
        (("1.0", "1.00"), ("1.5", "0.67"), ("2.0", "0.50")),
    ),
    _LiteralCase(
        "rational-even",
        "1/(1 + x*x)",
        "-1",
        "1",
        0,
        2,
        (("-1", "0.50"), ("0", "1.00"), ("1", "0.50")),
    ),
    _LiteralCase(
        "half-even-zero-and-two",
        "x",
        "0.5",
        "1.5",
        1,
        0,
        (("0.5", "0"), ("1.5", "2")),
    ),
    _LiteralCase(
        "half-even-two-and-four",
        "x",
        "2.5",
        "3.5",
        1,
        0,
        (("2.5", "2"), ("3.5", "4")),
    ),
    _LiteralCase(
        "negative-half-even",
        "x",
        "-1.5",
        "-0.5",
        1,
        0,
        (("-1.5", "-2"), ("-0.5", "0")),
    ),
    _LiteralCase(
        "negative-near-zero",
        "x",
        "-0.6",
        "-0.4",
        1,
        0,
        (("-0.6", "-1"), ("-0.5", "0"), ("-0.4", "0")),
    ),
    _LiteralCase(
        "evaluate-at-canonical-positive-x",
        "2*x",
        "0",
        "3",
        0,
        0,
        (("0", "0"), ("2", "4"), ("3", "6")),
    ),
    _LiteralCase(
        "evaluate-at-canonical-negative-x",
        "x + 1",
        "-3",
        "0",
        0,
        0,
        (("-3", "-2"), ("-2", "-1"), ("0", "1")),
    ),
    _LiteralCase(
        "half-even-tie-down-at-hundredths",
        "x/8",
        "1",
        "2",
        0,
        2,
        (("1", "0.12"), ("2", "0.25")),
    ),
    _LiteralCase(
        "half-even-tie-up-at-hundredths",
        "3*x/8",
        "1",
        "2",
        0,
        2,
        (("1", "0.38"), ("2", "0.75")),
    ),
    _LiteralCase(
        "nested-operations",
        "abs(x - 1)*2 + 1",
        "0",
        "2",
        0,
        0,
        (("0", "3"), ("1", "1"), ("2", "3")),
    ),
    _LiteralCase("left-associative-division", "8/4/2", "0", "1", 0, 0, (("0", "1"), ("1", "1"))),
    _LiteralCase(
        "double-negation",
        "-(-x)",
        "-1",
        "1",
        0,
        0,
        (("-1", "-1"), ("0", "0"), ("1", "1")),
    ),
    _LiteralCase(
        "rational-polynomial",
        "(x*x - 1)/(1 + abs(x))",
        "-2",
        "2",
        0,
        0,
        (("-2", "1"), ("-1", "0"), ("0", "-1"), ("1", "0"), ("2", "1")),
    ),
    _LiteralCase(
        "fixed-scale-zero",
        "0",
        "0.00",
        "1.00",
        2,
        3,
        (("0.00", "0.000"), ("0.50", "0.000"), ("1.00", "0.000")),
    ),
    _LiteralCase(
        "decimal-literals-exact", "0.1 + 0.2", "0", "1", 0, 1, (("0", "0.3"), ("1", "0.3"))
    ),
    _LiteralCase(
        "grouped-negative-power-base",
        "(-x)**2",
        "-1",
        "1",
        0,
        0,
        (("-1", "1"), ("0", "0"), ("1", "1")),
    ),
    _LiteralCase("one-sixth", "1/6", "0", "1", 0, 2, (("0", "0.17"), ("1", "0.17"))),
    _LiteralCase("negative-eighth", "-1/8", "0", "1", 0, 2, (("0", "-0.12"), ("1", "-0.12"))),
    _LiteralCase(
        "negative-zero-fold",
        "-1/100",
        "0",
        "1",
        0,
        1,
        (("0", "0.0"), ("1", "0.0")),
    ),
)
_LITERAL_BY_NAME = {case.name: case for case in _LITERAL_CASES}


@dataclass(frozen=True, slots=True)
class _RejectCase:
    name: str
    formula: str
    start: str
    stop: str
    samples: int
    x_scale: int
    y_scale: int
    check: str


_REJECT_CASES = (
    _RejectCase("reversed-domain", "x", "1", "0", 2, 0, 0, "formula.domain_ordered"),
    _RejectCase(
        "unrepresentable-endpoint",
        "x",
        "0.01",
        "1.01",
        2,
        1,
        1,
        "formula.domain_bounded",
    ),
    _RejectCase(
        "sample-collision",
        "x",
        "0",
        "1",
        3,
        0,
        0,
        "formula.sample_points_strictly_increasing",
    ),
    _RejectCase(
        "division-by-zero",
        "1/(x - 1)",
        "0",
        "2",
        3,
        0,
        2,
        "formula.values_defined",
    ),
    _RejectCase(
        "zero-negative-power",
        "x**-1",
        "0",
        "1",
        2,
        0,
        2,
        "formula.values_defined",
    ),
)


type _DomainArgs = tuple[str, str, int, int, int]


def _spec(
    formula: str,
    domain: _DomainArgs,
    *,
    mark: str = "line",
) -> FormulaPlotSpec:
    start, stop, samples, x_scale, y_scale = domain
    raw: dict[str, object] = {
        "version": "vplot-formula-0.1",
        "formula": formula,
        "domain": {
            "start": start,
            "stop": stop,
            "samples": samples,
            "x_scale": x_scale,
            "y_scale": y_scale,
        },
        "numeric_profile": "rational-half-even-v1",
        "mark": mark,
        "encoding": {
            "x": {"field": "x", "type": "quantitative"},
            "y": {"field": "y", "type": "quantitative"},
        },
    }
    return decode_formula_spec(msgspec.json.encode(raw))


def _case_spec(case: _LiteralCase) -> FormulaPlotSpec:
    domain = (case.start, case.stop, len(case.expected), case.x_scale, case.y_scale)
    return _spec(case.formula, domain)


def _expected_table(case: _LiteralCase) -> canon.Table:
    return canon.Table(
        columns=(
            canon.NumericColumn(name="x", scale=case.x_scale),
            canon.NumericColumn(name="y", scale=case.y_scale),
        ),
        rows=tuple((Decimal(x), Decimal(y)) for x, y in case.expected),
    )


def _assert_raw_table_equal(actual: canon.Table, expected: canon.Table) -> None:
    """Compare Decimal representation state, never Decimal value equality or serialization."""
    assert actual.columns == expected.columns
    assert len(actual.rows) == len(expected.rows)
    for actual_row, expected_row in zip(actual.rows, expected.rows, strict=True):
        assert len(actual_row) == len(expected_row)
        for actual_cell, expected_cell in zip(actual_row, expected_row, strict=True):
            assert isinstance(actual_cell, Decimal)
            assert isinstance(expected_cell, Decimal)
            assert actual_cell.as_tuple() == expected_cell.as_tuple()
            assert actual_cell.is_signed() is expected_cell.is_signed()
            if actual_cell.is_zero():
                assert not actual_cell.is_signed()


def _production_table(
    spec: FormulaPlotSpec,
    *,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> canon.Table:
    return evaluate_formula_run(spec, limits=limits).table


def _assert_table_agreement(
    spec: FormulaPlotSpec,
    *,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> canon.Table:
    parsed = parse_expr(spec.formula, allowed_vars=frozenset({"x"}), limits=limits)
    oracle_table = evaluate_formula_oracle(spec, parsed_ast=parsed.ast, limits=limits)
    production = evaluate_formula_run(spec, limits=limits)
    assert production.parsed == parsed
    _assert_raw_table_equal(production.table, oracle_table)
    return oracle_table


def _reject_spec(case: _RejectCase) -> FormulaPlotSpec:
    domain = (case.start, case.stop, case.samples, case.x_scale, case.y_scale)
    return _spec(case.formula, domain)


def _assert_rejection_agreement(
    spec: FormulaPlotSpec,
    check: str,
    *,
    limits: VerificationLimits = DEFAULT_LIMITS,
    bind_ast: bool = True,
) -> None:
    parsed_ast = (
        parse_expr(spec.formula, allowed_vars=frozenset({"x"}), limits=limits).ast
        if bind_ast
        else None
    )
    with pytest.raises((FormulaOracleError, VerificationError)) as oracle_exc:
        evaluate_formula_oracle(spec, parsed_ast=parsed_ast, limits=limits)
    with pytest.raises(VerificationError) as production_exc:
        _production_table(spec, limits=limits)
    oracle_error = oracle_exc.value
    assert isinstance(oracle_error, (FormulaOracleError, VerificationError))
    assert oracle_error.check == check
    assert production_exc.value.check == check


# --- oracle self-validation against literal exact results -------------------
def test_oracle_self_validation_matrix_has_thirty_independent_cases() -> None:
    assert len(_LITERAL_CASES) == 30
    assert len(_LITERAL_BY_NAME) == len(_LITERAL_CASES)


def test_oracle_self_validation_has_no_production_or_rounding_helper_dependency() -> None:
    tree = ast.parse(Path(__file__).with_name("formula_oracle.py").read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    imported_members: set[tuple[str, str]] = set()
    called_names: set[str] = set()
    attributes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imported_modules.add(module)
            imported_members.update((module, alias.name) for alias in node.names)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called_names.add(node.func.id)
        elif isinstance(node, ast.Attribute):
            attributes.add(node.attr)

    verifier_modules = {
        module
        for module in imported_modules
        if module == "verifier" or module.startswith("verifier.")
    }
    verifier_members = {
        item
        for item in imported_members
        if item[0] == "verifier" or item[0].startswith("verifier.")
    }
    assert verifier_modules == {
        "verifier",
        "verifier.expr",
        "verifier.limits",
        "verifier.schema",
    }
    assert verifier_members == {
        ("verifier", "canon"),
        ("verifier.expr", "Abs"),
        ("verifier.expr", "Binary"),
        ("verifier.expr", "Expr"),
        ("verifier.expr", "Neg"),
        ("verifier.expr", "Number"),
        ("verifier.expr", "Pow"),
        ("verifier.expr", "Variable"),
        ("verifier.expr", "parse_expr"),
        ("verifier.limits", "DEFAULT_LIMITS"),
        ("verifier.limits", "VerificationLimits"),
        ("verifier.schema", "FormulaPlotSpec"),
    }
    assert imported_modules.isdisjoint({"verifier.eval", "verifier.work"})
    assert imported_members.isdisjoint({("verifier", "eval"), ("verifier", "work")})
    assert "round" not in called_names
    assert "quantize" not in attributes


@pytest.mark.parametrize("filename", _CORPUS_FILES)
def test_oracle_self_validation_good_corpus(filename: str) -> None:
    spec = decode_formula_spec((_FORMULA_GOOD / filename).read_bytes())
    table = evaluate_formula_oracle(spec)
    assert len(table.rows) == spec.domain.samples
    assert table.columns == (
        canon.NumericColumn(name="x", scale=spec.domain.x_scale),
        canon.NumericColumn(name="y", scale=spec.domain.y_scale),
    )
    for row in table.rows:
        for cell in row:
            assert isinstance(cell, Decimal)
            if cell.is_zero():
                assert not cell.is_signed()


@pytest.mark.parametrize("case", _LITERAL_CASES, ids=[case.name for case in _LITERAL_CASES])
def test_oracle_self_validation_literal_matrix(case: _LiteralCase) -> None:
    _assert_raw_table_equal(evaluate_formula_oracle(_case_spec(case)), _expected_table(case))


@pytest.mark.parametrize("case", _REJECT_CASES, ids=[case.name for case in _REJECT_CASES])
def test_oracle_self_validation_rejections(case: _RejectCase) -> None:
    with pytest.raises(FormulaOracleError) as exc_info:
        evaluate_formula_oracle(_reject_spec(case))
    assert exc_info.value.check == case.check


def test_oracle_self_validation_sample_limit() -> None:
    spec = _spec("x", ("0", "2", 3, 0, 0))
    with pytest.raises(FormulaOracleError) as exc_info:
        evaluate_formula_oracle(spec, limits=VerificationLimits(max_formula_samples=2))
    assert exc_info.value.check == "resource.formula_samples"


def test_oracle_self_validation_intermediate_limit() -> None:
    spec = _spec("16", ("0", "1", 2, 0, 0))
    with pytest.raises(FormulaOracleError) as exc_info:
        evaluate_formula_oracle(spec, limits=VerificationLimits(max_formula_intermediate_bits=4))
    assert exc_info.value.check == "resource.formula_intermediate_bits"


@pytest.mark.parametrize(
    ("formula", "domain"),
    (
        pytest.param("0", ("-2", "2", 2, 0, 0), id="sample-span"),
        pytest.param("0", ("0", "1", 5, 0, 0), id="sample-ratio"),
        pytest.param("0", ("0", "1", 4, 2, 0), id="canonical-x"),
        pytest.param("1/3", ("0", "1", 2, 0, 2), id="canonical-y"),
    ),
)
def test_oracle_self_validation_checks_every_fraction_admission(
    formula: str,
    domain: _DomainArgs,
) -> None:
    spec = _spec(formula, domain)
    limits = VerificationLimits(max_formula_intermediate_bits=2)
    with pytest.raises(FormulaOracleError) as exc_info:
        evaluate_formula_oracle(spec, limits=limits)
    assert exc_info.value.check == "resource.formula_intermediate_bits"


@pytest.mark.parametrize(
    ("domain", "limits", "check"),
    (
        pytest.param(
            ("1", "0", 3, 0, 0),
            VerificationLimits(max_formula_samples=2, max_formula_intermediate_bits=1),
            "formula.domain_ordered",
            id="domain-order-before-sample-limit",
        ),
        pytest.param(
            ("0", "4", 3, 0, 0),
            VerificationLimits(max_formula_samples=2, max_formula_intermediate_bits=2),
            "resource.formula_samples",
            id="sample-limit-before-domain-bits",
        ),
        pytest.param(
            ("4", "5", 2, 0, 0),
            VerificationLimits(max_formula_intermediate_bits=2),
            "resource.formula_intermediate_bits",
            id="domain-bits-before-parse",
        ),
    ),
)
def test_oracle_and_production_match_preparse_rejection_precedence(
    domain: _DomainArgs,
    limits: VerificationLimits,
    check: str,
) -> None:
    _assert_rejection_agreement(
        _spec("(", domain),
        check,
        limits=limits,
        bind_ast=False,
    )


def test_parse_rejection_precedes_schedule_admission_in_both_evaluators() -> None:
    spec = _spec("(", ("-2", "2", 2, 0, 0))
    limits = VerificationLimits(max_formula_intermediate_bits=2)
    with pytest.raises(VerificationError) as oracle_exc:
        evaluate_formula_oracle(spec, limits=limits)
    with pytest.raises(VerificationError) as production_exc:
        _production_table(spec, limits=limits)
    assert oracle_exc.value.check == "formula.grammar_allowed"
    assert production_exc.value.check == "formula.grammar_allowed"


@pytest.mark.parametrize(
    ("formula", "domain", "limits", "check"),
    (
        pytest.param(
            "1/(x - x)",
            ("0", "1", 3, 0, 2),
            DEFAULT_LIMITS,
            "formula.sample_points_strictly_increasing",
            id="schedule-before-evaluation",
        ),
        pytest.param(
            "1/(x - x) + 1/3",
            ("0", "1", 2, 0, 2),
            VerificationLimits(max_formula_intermediate_bits=6),
            "formula.values_defined",
            id="evaluation-before-y-quantization",
        ),
    ),
)
def test_oracle_and_production_match_postparse_rejection_precedence(
    formula: str,
    domain: _DomainArgs,
    limits: VerificationLimits,
    check: str,
) -> None:
    _assert_rejection_agreement(_spec(formula, domain), check, limits=limits)


# --- concrete agreement over literals and the formula corpus ----------------
@pytest.mark.parametrize("case", _LITERAL_CASES, ids=[case.name for case in _LITERAL_CASES])
def test_production_agrees_with_literal_validated_oracle(case: _LiteralCase) -> None:
    oracle_table = _assert_table_agreement(_case_spec(case))
    _assert_raw_table_equal(oracle_table, _expected_table(case))


@pytest.mark.parametrize("filename", _CORPUS_FILES)
def test_good_formula_corpus_agrees_with_oracle(filename: str) -> None:
    spec = decode_formula_spec((_FORMULA_GOOD / filename).read_bytes())
    _assert_table_agreement(spec)


def test_agreement_consumes_one_parser_ast_value(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec(
        "-abs(x - 0.5) + (x * 0.25)/(abs(x) + 1.5) + (x + 1.25)**-2",
        ("1", "3", 5, 12, 6),
    )
    parsed = parse_expr(spec.formula, allowed_vars=frozenset({"x"}), limits=DEFAULT_LIMITS)

    def fail_reparse(*_args: object, **_kwargs: object) -> None:
        pytest.fail("the oracle reparsed instead of consuming the bound AST")

    monkeypatch.setattr("formula_oracle.parse_expr", fail_reparse)
    oracle_table = evaluate_formula_oracle(spec, parsed_ast=parsed.ast)
    production = evaluate_formula_run(spec)
    assert production.parsed == parsed
    _assert_raw_table_equal(production.table, oracle_table)


def test_full_ast_generated_anchors_cover_expression_algebra() -> None:
    formulas = (
        "-abs(x - 0.5) + (x * 0.25)/(abs(x) + 1.5) + (x + 1.25)**-2",
        "-abs(x - 0.5) + (x * 0.25)/(abs(x) + 1.5) + (x + 1.25)**+2",
    )
    kinds: set[type[object]] = set()
    operations: set[str] = set()
    exponents: set[int] = set()
    has_decimal_literal = False
    for formula in formulas:
        parsed = parse_expr(formula, allowed_vars=frozenset({"x"}), limits=DEFAULT_LIMITS)
        pending: list[Expr] = [parsed.ast]
        while pending:
            node = pending.pop()
            kinds.add(type(node))
            if isinstance(node, Binary):
                operations.add(node.op)
                pending.extend((node.left, node.right))
            elif isinstance(node, (Neg, Abs)):
                pending.append(node.operand)
            elif isinstance(node, Pow):
                exponents.add(node.exponent)
                pending.append(node.base)
            elif isinstance(node, Number):
                has_decimal_literal |= node.value.denominator != 1
            else:
                assert isinstance(node, Variable)

    assert kinds == {Number, Variable, Neg, Abs, Pow, Binary}
    assert operations == {"add", "sub", "mul", "div"}
    assert exponents == {-2, 2}
    assert has_decimal_literal


@pytest.mark.parametrize(
    ("filename", "check"),
    _CORPUS_REJECTIONS,
    ids=[filename for filename, _check in _CORPUS_REJECTIONS],
)
def test_bad_formula_corpus_rejection_agrees_with_oracle(filename: str, check: str) -> None:
    spec = decode_formula_spec((_FORMULA_BAD / filename).read_bytes())
    _assert_rejection_agreement(spec, check)


@pytest.mark.parametrize("case", _REJECT_CASES, ids=[case.name for case in _REJECT_CASES])
def test_production_and_oracle_reject_same_concrete_case(case: _RejectCase) -> None:
    _assert_rejection_agreement(_reject_spec(case), case.check)


def test_post_quantized_y_intermediate_limit_agrees_with_production() -> None:
    spec = _spec("1/3", ("0", "1", 2, 0, 2))
    limits = VerificationLimits(max_formula_intermediate_bits=2)
    _assert_rejection_agreement(
        spec,
        "resource.formula_intermediate_bits",
        limits=limits,
    )


@pytest.mark.parametrize(
    ("formula", "bit_limit", "exponent_limit", "check"),
    (
        pytest.param("2**3", 3, 3, "resource.formula_intermediate_bits", id="positive-reject"),
        pytest.param("2**3", 4, 3, None, id="positive-admit"),
        pytest.param("2**-3", 3, 3, "resource.formula_intermediate_bits", id="negative-reject"),
        pytest.param("2**-3", 4, 3, None, id="negative-admit"),
        pytest.param("3**4", 6, 4, "resource.formula_intermediate_bits", id="square-reject"),
        pytest.param("3**4", 7, 4, None, id="square-admit"),
        pytest.param(
            "(3/2)**3",
            4,
            3,
            "resource.formula_intermediate_bits",
            id="rational-reject",
        ),
        pytest.param("(3/2)**3", 5, 3, None, id="rational-admit"),
        pytest.param("2**3", 64, 2, "formula.exponents_bounded", id="exponent-reject"),
        pytest.param("2**3", 64, 3, None, id="exponent-admit"),
    ),
)
def test_power_and_intermediate_bit_boundaries_agree(
    formula: str,
    bit_limit: int,
    exponent_limit: int,
    check: str | None,
) -> None:
    spec = _spec(formula, ("0", "1", 2, 0, 0))
    limits = VerificationLimits(
        max_formula_intermediate_bits=bit_limit,
        max_formula_exponent=exponent_limit,
    )
    if check is None:
        _assert_table_agreement(spec, limits=limits)
    else:
        _assert_rejection_agreement(
            spec,
            check,
            limits=limits,
            bind_ast=check != "formula.exponents_bounded",
        )


def test_work_tariff_is_explicitly_outside_oracle_agreement() -> None:
    spec = _spec("x", ("0", "1", 2, 0, 0))
    limits = VerificationLimits(max_formula_work_units=1)
    oracle_table = evaluate_formula_oracle(spec, limits=limits)
    assert len(oracle_table.rows) == 2
    with pytest.raises(VerificationError) as production_exc:
        evaluate_formula_run(spec, limits=limits)
    assert production_exc.value.check == "resource.formula_work"


def test_half_even_tie_rounding_agrees_with_production() -> None:
    case = _LITERAL_BY_NAME["half-even-zero-and-two"]
    oracle_table = _assert_table_agreement(_case_spec(case))
    _assert_raw_table_equal(oracle_table, _expected_table(case))


def test_negative_zero_canonicalization_agrees_with_production() -> None:
    case = _LITERAL_BY_NAME["negative-zero-fold"]
    oracle_table = _assert_table_agreement(_case_spec(case))
    _assert_raw_table_equal(oracle_table, _expected_table(case))
    assert all(not row[1].is_signed() for row in oracle_table.rows if isinstance(row[1], Decimal))


# --- bounded generated polynomial/rational agreement ------------------------
def _scaled_text(units: int, scale: int) -> str:
    if scale == 0:
        return str(units)
    sign = "-" if units < 0 else ""
    whole, fractional = divmod(abs(units), 10**scale)
    return f"{sign}{whole}.{fractional:0{scale}d}"


def _polynomial_text(coefficients: list[int]) -> str:
    expression = str(coefficients[-1])
    for coefficient in reversed(coefficients[:-1]):
        expression = f"({expression})*x + ({coefficient})"
    return expression


@st.composite
def _valid_formula_specs(draw: DrawFn) -> FormulaPlotSpec:
    coefficients = draw(st.lists(st.integers(-5, 5), min_size=1, max_size=5))
    polynomial = _polynomial_text(coefficients)
    denominator = draw(st.sampled_from((None, "1 + x*x", "1 + abs(x)", "2 + x**2")))
    formula = polynomial if denominator is None else f"({polynomial})/({denominator})"

    samples = draw(st.integers(min_value=2, max_value=9))
    x_scale = draw(st.integers(min_value=0, max_value=3))
    y_scale = draw(st.integers(min_value=0, max_value=4))
    start_units = draw(st.integers(min_value=-24, max_value=12))
    # A gap of at least samples-1 whole x quanta makes rounded samples strictly increasing.
    gap_units = draw(st.integers(min_value=samples - 1, max_value=32))
    stop_units = start_units + gap_units
    domain = (
        _scaled_text(start_units, x_scale),
        _scaled_text(stop_units, x_scale),
        samples,
        x_scale,
        y_scale,
    )
    return _spec(formula, domain, mark=draw(st.sampled_from(("line", "scatter"))))


@settings(max_examples=100)
@given(spec=_valid_formula_specs())
def test_generated_polynomial_and_rational_specs_find_no_oracle_disagreement(
    spec: FormulaPlotSpec,
) -> None:
    _assert_table_agreement(spec)


@st.composite
def _full_ast_formula_specs(draw: DrawFn) -> FormulaPlotSpec:
    offset = draw(st.integers(min_value=1, max_value=9))
    factor = draw(st.integers(min_value=1, max_value=9))
    denominator = draw(st.integers(min_value=1, max_value=9))
    shift = draw(st.integers(min_value=1, max_value=9))
    exponent = draw(st.sampled_from((-3, -2, -1, 0, 1, 2, 3)))
    formula = (
        f"-abs(x - 0.{offset}) + "
        f"(x * 0.{factor})/(abs(x) + 1.{denominator}) + "
        f"(x + 1.{shift})**{exponent:+d}"
    )
    samples = draw(st.sampled_from((2, 3, 9, 31, DEFAULT_LIMITS.max_formula_samples)))
    y_scale = draw(st.integers(min_value=0, max_value=12))
    return _spec(
        formula,
        ("1", "3", samples, 12, y_scale),
        mark=draw(st.sampled_from(("line", "scatter"))),
    )


@settings(max_examples=40)
@example(
    spec=_spec(
        "-abs(x - 0.5) + (x * 0.25)/(abs(x) + 1.5) + (x + 1.25)**-2",
        ("1", "3", DEFAULT_LIMITS.max_formula_samples, 12, 6),
    )
)
@example(
    spec=_spec(
        "-abs(x - 0.5) + (x * 0.25)/(abs(x) + 1.5) + (x + 1.25)**+2",
        ("1", "3", 2, 12, 12),
    )
)
@given(spec=_full_ast_formula_specs())
def test_generated_full_ast_specs_find_no_oracle_disagreement(
    spec: FormulaPlotSpec,
) -> None:
    _assert_table_agreement(spec)


type _RejectedAgreementCase = tuple[FormulaPlotSpec, VerificationLimits, str]


@st.composite
def _rejected_formula_cases(draw: DrawFn) -> _RejectedAgreementCase:
    kind = draw(st.sampled_from(("division", "negative-power", "bit-limit")))
    if kind == "division":
        samples = draw(st.sampled_from((2, 3, 9)))
        return (
            _spec("1/(x - x)", ("1", "3", samples, 12, 2)),
            DEFAULT_LIMITS,
            "formula.values_defined",
        )
    if kind == "negative-power":
        samples = draw(st.sampled_from((2, 3, 9)))
        return (
            _spec("(x - x)**-1", ("1", "3", samples, 12, 2)),
            DEFAULT_LIMITS,
            "formula.values_defined",
        )
    y_scale = draw(st.integers(min_value=2, max_value=12))
    bit_limit = draw(st.integers(min_value=2, max_value=6))
    return (
        _spec("1/3", ("0", "1", 2, 12, y_scale)),
        VerificationLimits(max_formula_intermediate_bits=bit_limit),
        "resource.formula_intermediate_bits",
    )


@settings(max_examples=30)
@example(
    case=(
        _spec("1/(x - x)", ("1", "3", 2, 12, 2)),
        DEFAULT_LIMITS,
        "formula.values_defined",
    )
)
@example(
    case=(
        _spec("(x - x)**-1", ("1", "3", 2, 12, 2)),
        DEFAULT_LIMITS,
        "formula.values_defined",
    )
)
@example(
    case=(
        _spec("1/3", ("0", "1", 2, 12, 2)),
        VerificationLimits(max_formula_intermediate_bits=6),
        "resource.formula_intermediate_bits",
    )
)
@given(case=_rejected_formula_cases())
def test_generated_rejections_find_no_oracle_disagreement(
    case: _RejectedAgreementCase,
) -> None:
    spec, limits, check = case
    _assert_rejection_agreement(spec, check, limits=limits)
