# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Exact formula sampling, HALF_EVEN quantization, table, and work matrices."""

import os
import subprocess
import sys
from decimal import Decimal, Inexact, Rounded, localcontext
from fractions import Fraction
from typing import Any, NoReturn, cast

import msgspec
import pytest

from verifier import canon
from verifier import eval as eval_module
from verifier.eval import EvaluationError, FormulaEvaluationRun, evaluate_formula_run
from verifier.limits import VerificationLimits
from verifier.schema import FormulaPlotSpec, decode_formula_spec


def _spec(
    formula: str,
    *,
    bounds: tuple[str, str] = ("0", "1"),
    samples: int = 2,
    x_scale: int = 0,
    y_scale: int = 0,
) -> FormulaPlotSpec:
    start, stop = bounds
    raw: dict[str, Any] = {
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
        "mark": "line",
        "encoding": {
            "x": {"field": "x", "type": "quantitative"},
            "y": {"field": "y", "type": "quantitative"},
        },
    }
    return decode_formula_spec(msgspec.json.encode(raw))


def _numeric_rows(run: FormulaEvaluationRun) -> tuple[tuple[Decimal, Decimal], ...]:
    rows: list[tuple[Decimal, Decimal]] = []
    for x_value, y_value in run.table.rows:
        assert isinstance(x_value, Decimal)
        assert isinstance(y_value, Decimal)
        rows.append((x_value, y_value))
    return tuple(rows)


def _assert_raw(value: Decimal, expected: str) -> None:
    target = Decimal(expected)
    assert value.as_tuple() == target.as_tuple()
    assert value.is_signed() is target.is_signed()


@pytest.mark.parametrize(
    ("start", "stop", "expected_midpoint"),
    [("0", "5", "2"), ("0", "7", "4"), ("-5", "0", "-2"), ("-7", "0", "-4")],
)
def test_x_half_even_ties_are_exact_and_preserve_raw_scale(
    start: str, stop: str, expected_midpoint: str
) -> None:
    rows = _numeric_rows(
        evaluate_formula_run(_spec("x", bounds=(start, stop), samples=3, x_scale=0, y_scale=0))
    )
    _assert_raw(rows[1][0], expected_midpoint)
    _assert_raw(rows[1][1], expected_midpoint)


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("1/4", "0"),
        ("3/4", "1"),
        ("1/2", "0"),
        ("3/2", "2"),
        ("-1/2", "0"),
        ("-3/2", "-2"),
    ],
)
def test_y_half_even_matrix_and_negative_zero_canonicalization(formula: str, expected: str) -> None:
    rows = _numeric_rows(evaluate_formula_run(_spec(formula)))
    for _x_value, y_value in rows:
        _assert_raw(y_value, expected)
        if expected == "0":
            assert y_value.is_signed() is False


def test_simultaneous_x_and_y_ties_evaluate_at_canonical_x() -> None:
    # Raw midpoint x=2.5 ties down to canonical x=2; y=x/4 then ties 0.5 down to even 0.
    # Evaluating at hidden x=2.5 would instead quantize y=0.625 up to 1.
    rows = _numeric_rows(evaluate_formula_run(_spec("x/4", bounds=("0", "5"), samples=3)))
    _assert_raw(rows[1][0], "2")
    _assert_raw(rows[1][1], "0")
    assert rows[1][0].is_signed() is False
    assert rows[1][1].is_signed() is False


def test_negative_x_tie_canonicalizes_zero_before_evaluation() -> None:
    rows = _numeric_rows(evaluate_formula_run(_spec("x", bounds=("-2", "1"), samples=3)))
    assert tuple(row[0] for row in rows) == (Decimal(-2), Decimal(0), Decimal(1))
    _assert_raw(rows[1][0], "0")
    _assert_raw(rows[1][1], "0")
    assert rows[1][0].is_signed() is False
    assert rows[1][1].is_signed() is False


@pytest.mark.parametrize(
    ("formula", "expected"),
    [("1/2000000000000", "0.000000000000"), ("3/2000000000000", "0.000000000002")],
)
def test_max_scale_half_even_ties_are_exact(formula: str, expected: str) -> None:
    rows = _numeric_rows(evaluate_formula_run(_spec(formula, y_scale=12)))
    for _x_value, y_value in rows:
        _assert_raw(y_value, expected)
        if expected == "0.000000000000":
            assert y_value.is_signed() is False


def test_canonical_table_shape_bytes_and_formula_source_are_resolved_once() -> None:
    run = evaluate_formula_run(_spec("x/2", bounds=("-1", "1"), samples=3, x_scale=1, y_scale=2))
    assert run.table.columns == (
        canon.NumericColumn(name="x", scale=1),
        canon.NumericColumn(name="y", scale=2),
    )
    rows = _numeric_rows(run)
    for value, expected in zip(
        (rows[0][0], rows[0][1], rows[1][0], rows[1][1], rows[2][0], rows[2][1]),
        ("-1.0", "-0.50", "0.0", "0.00", "1.0", "0.50"),
        strict=True,
    ):
        _assert_raw(value, expected)
    assert canon.serialize_table(run.table) == (
        '["x:numeric:1","y:numeric:2"]\n[-1.0,-0.50]\n[0.0,0.00]\n[1.0,0.50]\n'
    )
    assert run.parsed.nodes == 3
    assert run.formula_source == canon.FormulaSource(
        grammar_version="expr-0.1",
        numeric_profile="rational-half-even-v1",
        rounding="ROUND_HALF_EVEN",
        ast="(div x 2)",
        start=Decimal("-1.0"),
        stop=Decimal("1.0"),
        samples=3,
        x_scale=1,
        y_scale=2,
    )
    name = "work_units"  # dynamic name bypasses mypy's frozen-field check
    with pytest.raises(AttributeError):
        setattr(run, name, 0)


def test_tie_heavy_quantization_ignores_hostile_ambient_decimal_context() -> None:
    cases = (
        (_spec("3/2", bounds=("0", "5"), samples=3), ("0", "2", "5"), "2", 24),
        (_spec("-3/2", bounds=("-5", "0"), samples=3), ("-5", "-2", "0"), "-2", 27),
        (_spec("-1/2", bounds=("-2", "1"), samples=3), ("-2", "0", "1"), "0", 27),
    )
    reference = tuple(evaluate_formula_run(spec) for spec, *_expected in cases)
    with localcontext() as context:
        context.prec = 1
        context.rounding = "ROUND_UP"
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        before = context.copy()
        hostile = tuple(evaluate_formula_run(spec) for spec, *_expected in cases)
        assert context.prec == before.prec
        assert context.rounding == before.rounding
        assert context.traps == before.traps
        assert context.flags == before.flags

    for run, reference_run, (_specification, expected_x, expected_y, expected_work) in zip(
        hostile, reference, cases, strict=True
    ):
        assert run.table == reference_run.table
        assert run.work_units == reference_run.work_units == expected_work
        for (x_value, y_value), expected_x_value in zip(
            _numeric_rows(run), expected_x, strict=True
        ):
            _assert_raw(x_value, expected_x_value)
            _assert_raw(y_value, expected_y)
            if expected_x_value == "0":
                assert x_value.is_signed() is False
            if expected_y == "0":
                assert y_value.is_signed() is False


def test_large_endpoint_schedule_reproduces_both_endpoints_exactly() -> None:
    endpoint = "999999999999999999.999999999"
    run = evaluate_formula_run(
        _spec(
            "x",
            bounds=("-" + endpoint, endpoint),
            samples=3,
            x_scale=9,
            y_scale=9,
        )
    )
    rows = _numeric_rows(run)
    _assert_raw(rows[0][0], "-" + endpoint)
    _assert_raw(rows[1][0], "0.000000000")
    _assert_raw(rows[2][0], endpoint)
    for x_value, y_value in rows:
        assert x_value.as_tuple() == y_value.as_tuple()
        assert x_value.is_signed() is y_value.is_signed()


def test_reversed_domain_is_rejected_before_schedule_or_expression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _bomb(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "schedule started for a reversed domain"
        raise AssertionError(msg)

    monkeypatch.setattr(eval_module, "_formula_sample_positions", _bomb)
    with pytest.raises(EvaluationError) as exc_info:
        evaluate_formula_run(_spec("1/0", bounds=("5", "1")))
    assert exc_info.value.check == "formula.domain_ordered"
    assert exc_info.value.work_units == 0


def test_sample_limit_is_checked_before_parser_or_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _bomb(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "formula parsing started after sample admission failed"
        raise AssertionError(msg)

    monkeypatch.setattr(eval_module, "parse_expr", _bomb)
    with pytest.raises(EvaluationError) as exc_info:
        evaluate_formula_run(
            _spec("1/0", samples=3),
            limits=VerificationLimits(max_formula_samples=2),
        )
    assert exc_info.value.check == "resource.formula_samples"
    assert exc_info.value.work_units == 0


def test_sample_collision_is_rejected_before_any_expression_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _bomb(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "expression evaluation started for a colliding x schedule"
        raise AssertionError(msg)

    monkeypatch.setattr(eval_module, "eval_expr", _bomb)
    with pytest.raises(EvaluationError) as exc_info:
        evaluate_formula_run(_spec("1/0", samples=5))
    assert exc_info.value.check == "formula.sample_points_strictly_increasing"
    assert exc_info.value.work_units == 12


@pytest.mark.parametrize(
    ("start", "stop", "expected_work"),
    [("0.04", "1.0", 5), ("0", "1.04", 6)],
)
def test_domain_endpoints_must_be_exactly_representable_at_x_scale(
    start: str, stop: str, expected_work: int
) -> None:
    with pytest.raises(EvaluationError) as exc_info:
        evaluate_formula_run(_spec("x", bounds=(start, stop), x_scale=1))
    assert exc_info.value.check == "formula.domain_bounded"
    assert exc_info.value.work_units == expected_work


def test_division_by_zero_uses_canonical_not_hidden_sample_position() -> None:
    # Raw midpoint 2.5 is defined, but canonical x=2 makes the denominator exactly zero.
    with pytest.raises(EvaluationError) as exc_info:
        evaluate_formula_run(_spec("1/(x-2)", bounds=("0", "5"), samples=3))
    assert exc_info.value.check == "formula.values_defined"
    assert exc_info.value.work_units == 21


def test_parser_failure_is_mapped_to_formula_evaluation_error_with_zero_work() -> None:
    with pytest.raises(EvaluationError) as exc_info:
        evaluate_formula_run(_spec("sin(x)"))
    assert exc_info.value.check == "formula.functions_allowed"
    assert exc_info.value.work_units == 0


def test_formula_intermediate_limit_covers_domain_and_schedule_rationals() -> None:
    with pytest.raises(EvaluationError) as domain_exc:
        evaluate_formula_run(
            _spec("x", bounds=("0", "8")),
            limits=VerificationLimits(max_formula_intermediate_bits=3),
        )
    assert domain_exc.value.check == "resource.formula_intermediate_bits"
    assert domain_exc.value.work_units == 0

    with pytest.raises(EvaluationError) as schedule_exc:
        evaluate_formula_run(
            _spec("x", samples=4, x_scale=1),
            limits=VerificationLimits(max_formula_intermediate_bits=1),
        )
    assert schedule_exc.value.check == "resource.formula_intermediate_bits"
    assert schedule_exc.value.work_units == 3


def test_formula_stage_work_refusal_precedes_x_quantization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _bomb(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "x quantization started after work refusal"
        raise AssertionError(msg)

    monkeypatch.setattr(eval_module, "_quantize_fraction", _bomb)
    with pytest.raises(EvaluationError) as exc_info:
        evaluate_formula_run(
            _spec("x"),
            limits=VerificationLimits(max_formula_work_units=1),
        )
    assert exc_info.value.check == "resource.formula_work"
    assert exc_info.value.work_units == 1


@pytest.mark.parametrize(("samples", "expected_work"), [(2, 12), (3, 18), (5, 30)])
def test_samples_multiply_literal_wrapper_and_node_work_counts(
    samples: int, expected_work: int
) -> None:
    spec = _spec("x", bounds=("0", str(samples - 1)), samples=samples)
    limits = VerificationLimits(
        max_formula_samples=samples,
        max_formula_work_units=expected_work,
    )
    run = evaluate_formula_run(spec, limits=limits)
    assert run.work_units == expected_work
    with pytest.raises(EvaluationError) as exc_info:
        evaluate_formula_run(
            spec,
            limits=VerificationLimits(
                max_formula_samples=samples,
                max_formula_work_units=expected_work - 1,
            ),
        )
    assert exc_info.value.check == "resource.formula_work"
    assert exc_info.value.work_units == expected_work - 1


def test_quantization_is_total_at_the_admitted_fraction_bit_and_scale_corner() -> None:
    numerator = (1 << 4095) - 1
    denominator = (1 << 4094) + 1
    value = Fraction(numerator, denominator)
    quantized = eval_module._quantize_fraction(value, 12)
    assert quantized.is_finite()
    assert quantized.as_tuple().exponent == -12
    assert quantized.is_signed() is False


def test_formula_result_and_rows_never_expose_fraction_or_float_cells() -> None:
    run = evaluate_formula_run(_spec("(1/3)*3", samples=2, y_scale=2))
    assert isinstance(run, FormulaEvaluationRun)
    assert len(run.table.rows) == 2
    for row in run.table.rows:
        assert len(row) == 2
        assert all(isinstance(cell, Decimal) for cell in row)
        y_value = cast("Decimal", row[1])
        _assert_raw(y_value, "1.00")


def _formula_rows_at_failure(exc: EvaluationError) -> list[tuple[canon.Cell, ...]]:
    traceback = exc.__traceback__
    while traceback is not None:
        if traceback.tb_frame.f_code.co_name == "_evaluate_formula":
            rows = traceback.tb_frame.f_locals["rows"]
            assert isinstance(rows, list)
            return cast("list[tuple[canon.Cell, ...]]", rows)
        traceback = traceback.tb_next
    msg = "formula evaluator frame missing from EvaluationError traceback"
    raise AssertionError(msg)


def _formula_error_record(spec: FormulaPlotSpec) -> tuple[str, bytes, int]:
    with pytest.raises(EvaluationError) as exc_info:
        evaluate_formula_run(spec)
    exc = exc_info.value
    assert type(exc) is EvaluationError
    return (exc.check, str(exc).encode(), exc.work_units)


def test_y_quantization_charge_precedes_the_guarded_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_quantize = eval_module._quantize_fraction
    calls: list[tuple[Fraction, int]] = []

    def _record_quantization(value: Fraction, scale: int) -> Decimal:
        calls.append((value, scale))
        return original_quantize(value, scale)

    monkeypatch.setattr(eval_module, "_quantize_fraction", _record_quantization)
    spec = _spec("0")

    with pytest.raises(EvaluationError) as admitted_exc:
        evaluate_formula_run(
            spec,
            limits=VerificationLimits(max_formula_work_units=8),
        )
    assert admitted_exc.value.check == "resource.formula_work"
    assert str(admitted_exc.value) == (
        "formula work limit 8 would be exceeded before row admission: 8 consumed + 1 required"
    )
    assert admitted_exc.value.work_units == 8
    assert calls == [(Fraction(0), 0), (Fraction(1), 0), (Fraction(0), 0)]

    calls.clear()
    with pytest.raises(EvaluationError) as refused_exc:
        evaluate_formula_run(
            spec,
            limits=VerificationLimits(max_formula_work_units=7),
        )
    assert refused_exc.value.check == "resource.formula_work"
    assert str(refused_exc.value) == (
        "formula work limit 7 would be exceeded before y quantization: 7 consumed + 1 required"
    )
    assert refused_exc.value.work_units == 7
    assert calls == [(Fraction(0), 0), (Fraction(1), 0)]


def test_row_admission_charge_precedes_append_and_refuses_atomically() -> None:
    spec = _spec("0")
    run = evaluate_formula_run(
        spec,
        limits=VerificationLimits(max_formula_work_units=12),
    )
    assert run.work_units == 12
    assert len(run.table.rows) == 2

    with pytest.raises(EvaluationError) as exc_info:
        evaluate_formula_run(
            spec,
            limits=VerificationLimits(max_formula_work_units=11),
        )
    assert exc_info.value.check == "resource.formula_work"
    assert str(exc_info.value) == (
        "formula work limit 11 would be exceeded before row admission: 11 consumed + 1 required"
    )
    assert exc_info.value.work_units == 11
    assert len(_formula_rows_at_failure(exc_info.value)) == 1


def test_equal_domain_fails_before_sample_parser_and_schedule_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _bomb(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "a downstream formula stage ran for an equal domain"
        raise AssertionError(msg)

    monkeypatch.setattr(eval_module, "parse_expr", _bomb)
    monkeypatch.setattr(eval_module, "_formula_sample_positions", _bomb)
    with pytest.raises(EvaluationError) as exc_info:
        evaluate_formula_run(
            _spec("sin(x)", bounds=("2", "2"), samples=3),
            limits=VerificationLimits(max_formula_samples=2),
        )
    assert exc_info.value.check == "formula.domain_ordered"
    assert str(exc_info.value) == "formula domain start '2' must be less than stop '2'"
    assert exc_info.value.work_units == 0


def test_endpoint_representability_precedes_joint_quantization_collision() -> None:
    with pytest.raises(EvaluationError) as exc_info:
        evaluate_formula_run(_spec("x", bounds=("0", "0.04"), samples=2, x_scale=0))
    assert exc_info.value.check == "formula.domain_bounded"
    assert str(exc_info.value) == (
        "formula domain endpoints must be exactly representable at x_scale"
    )
    assert exc_info.value.work_units == 6


@pytest.mark.parametrize(
    "case",
    [
        ("schedule ratio", ("-2", "0"), 5, 1, 2, 3),
        ("schedule offset", ("-1.2", "0.2"), 3, 1, 3, 3),
        ("schedule position", ("-7", "-4"), 3, 0, 3, 3),
        ("canonical x", ("0", "0.25"), 3, 2, 4, 4),
    ],
    ids=("ratio", "offset", "position", "canonical-x"),
)
def test_each_deletion_pass_schedule_intermediate_admission_is_stage_local(
    case: tuple[str, tuple[str, str], int, int, int, int],
) -> None:
    stage, bounds, samples, x_scale, bit_limit, expected_work = case
    spec = _spec("0", bounds=bounds, samples=samples, x_scale=x_scale)
    with pytest.raises(EvaluationError) as exc_info:
        evaluate_formula_run(
            spec,
            limits=VerificationLimits(max_formula_intermediate_bits=bit_limit),
        )
    assert type(exc_info.value) is EvaluationError, stage
    assert exc_info.value.check == "resource.formula_intermediate_bits", stage
    assert str(exc_info.value) == (
        f"formula intermediate needs {bit_limit + 1} bits; limit is {bit_limit}"
    ), stage
    assert exc_info.value.work_units == expected_work, stage

    pass_run = evaluate_formula_run(
        spec,
        limits=VerificationLimits(max_formula_intermediate_bits=bit_limit + 1),
    )
    assert pass_run.work_units == 6 * samples, stage
    assert len(pass_run.table.rows) == samples, stage


def test_schedule_span_admission_precedes_quantization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec("0", bounds=("-8", "8"))

    def _bomb(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "x quantization started before the schedule span was admitted"
        raise AssertionError(msg)

    with monkeypatch.context() as patch:
        patch.setattr(eval_module, "_quantize_fraction", _bomb)
        with pytest.raises(EvaluationError) as exc_info:
            evaluate_formula_run(
                spec,
                limits=VerificationLimits(max_formula_intermediate_bits=4),
            )
    assert type(exc_info.value) is EvaluationError
    assert exc_info.value.check == "resource.formula_intermediate_bits"
    assert str(exc_info.value) == "formula intermediate needs 5 bits; limit is 4"
    assert exc_info.value.work_units == 0

    pass_run = evaluate_formula_run(
        spec,
        limits=VerificationLimits(max_formula_intermediate_bits=5),
    )
    assert pass_run.work_units == 12
    assert len(pass_run.table.rows) == 2


@pytest.mark.parametrize(
    ("stage", "bounds", "control_bounds"),
    [
        ("domain start", ("-16", "0"), ("-15", "0")),
        ("domain stop", ("0", "16"), ("0", "15")),
    ],
    ids=("domain-start", "domain-stop"),
)
def test_domain_endpoint_intermediate_admission_precedes_parser(
    stage: str,
    bounds: tuple[str, str],
    control_bounds: tuple[str, str],
) -> None:
    limits = VerificationLimits(max_formula_intermediate_bits=4)
    with pytest.raises(EvaluationError) as exc_info:
        evaluate_formula_run(_spec("(", bounds=bounds), limits=limits)
    assert type(exc_info.value) is EvaluationError, stage
    assert exc_info.value.check == "resource.formula_intermediate_bits", stage
    assert str(exc_info.value) == "formula intermediate needs 5 bits; limit is 4", stage
    assert exc_info.value.work_units == 0, stage

    with pytest.raises(EvaluationError) as control_exc:
        evaluate_formula_run(_spec("(", bounds=control_bounds), limits=limits)
    assert type(control_exc.value) is EvaluationError, stage
    assert control_exc.value.check == "formula.grammar_allowed", stage
    assert str(control_exc.value) == (
        "formula grammar is not allowed at position 2: expected a number, variable, abs, or '('"
    ), stage
    assert control_exc.value.work_units == 0, stage


def test_formula_error_bytes_repeat_across_interleaved_failures() -> None:
    collision = (
        "formula.sample_points_strictly_increasing",
        b"formula sample points must be strictly increasing after x quantization",
        12,
    )
    undefined = (
        "formula.values_defined",
        b"formula value is undefined: division by zero",
        9,
    )
    records = (
        _formula_error_record(_spec("x", samples=5)),
        _formula_error_record(_spec("1/0")),
        _formula_error_record(_spec("x", samples=5)),
        _formula_error_record(_spec("1/0")),
    )
    assert records == (collision, undefined, collision, undefined)


_ERROR_DETERMINISM_PROGRAM = """
import sys

import msgspec

from verifier.eval import EvaluationError, evaluate_formula_run
from verifier.schema import decode_formula_spec


def spec(formula, *, samples=2):
    return decode_formula_spec(
        msgspec.json.encode(
            {
                "version": "vplot-formula-0.1",
                "formula": formula,
                "domain": {
                    "start": "0",
                    "stop": "1",
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


def record(specification):
    try:
        evaluate_formula_run(specification)
    except EvaluationError as exc:
        assert type(exc) is EvaluationError
        return [
            f"{type(exc).__module__}.{type(exc).__qualname__}",
            exc.check,
            str(exc),
            exc.work_units,
        ]
    raise AssertionError("formula unexpectedly succeeded")


collision = spec("x", samples=5)
undefined = spec("1/0")
sys.stdout.buffer.write(
    msgspec.json.encode(
        [record(collision), record(undefined), record(collision), record(undefined)]
    )
)
"""


def _formula_errors_under_seed(seed: str) -> bytes:
    result = subprocess.run(  # noqa: S603 — fixed interpreter and literal child program
        [sys.executable, "-c", _ERROR_DETERMINISM_PROGRAM],
        capture_output=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": seed},
    )
    assert result.stderr == b""
    return result.stdout


def test_formula_error_bytes_are_stable_across_pythonhashseed() -> None:
    expected = msgspec.json.encode(
        [
            [
                "verifier.eval.EvaluationError",
                "formula.sample_points_strictly_increasing",
                "formula sample points must be strictly increasing after x quantization",
                12,
            ],
            [
                "verifier.eval.EvaluationError",
                "formula.values_defined",
                "formula value is undefined: division by zero",
                9,
            ],
            [
                "verifier.eval.EvaluationError",
                "formula.sample_points_strictly_increasing",
                "formula sample points must be strictly increasing after x quantization",
                12,
            ],
            [
                "verifier.eval.EvaluationError",
                "formula.values_defined",
                "formula value is undefined: division by zero",
                9,
            ],
        ]
    )
    assert _formula_errors_under_seed("0") == expected
    assert _formula_errors_under_seed("1") == expected


def test_sample_cap_max_scales_and_final_row_work_boundary() -> None:
    spec = _spec(
        "x",
        bounds=("0", "0.000009999"),
        samples=10_000,
        x_scale=12,
        y_scale=12,
    )
    run = evaluate_formula_run(
        spec,
        limits=VerificationLimits(
            max_formula_samples=10_000,
            max_formula_work_units=60_000,
        ),
    )
    assert run.work_units == 60_000
    assert len(run.table.rows) == 10_000
    first_x, first_y = run.table.rows[0]
    last_x, last_y = run.table.rows[-1]
    assert isinstance(first_x, Decimal)
    assert isinstance(first_y, Decimal)
    assert isinstance(last_x, Decimal)
    assert isinstance(last_y, Decimal)
    _assert_raw(first_x, "0.000000000000")
    _assert_raw(first_y, "0.000000000000")
    _assert_raw(last_x, "0.000009999000")
    _assert_raw(last_y, "0.000009999000")

    with pytest.raises(EvaluationError) as exc_info:
        evaluate_formula_run(
            spec,
            limits=VerificationLimits(
                max_formula_samples=10_000,
                max_formula_work_units=59_999,
            ),
        )
    assert exc_info.value.check == "resource.formula_work"
    assert str(exc_info.value) == (
        "formula work limit 59999 would be exceeded before row admission: "
        "59999 consumed + 1 required"
    )
    assert exc_info.value.work_units == 59_999
    assert len(_formula_rows_at_failure(exc_info.value)) == 9_999


def test_sample_cap_max_scale_collision_neighbour_has_exact_precedence_and_work() -> None:
    with pytest.raises(EvaluationError) as exc_info:
        evaluate_formula_run(
            _spec(
                "x",
                bounds=("0", "0.000000001"),
                samples=10_000,
                x_scale=12,
                y_scale=12,
            ),
            limits=VerificationLimits(max_formula_samples=10_000),
        )
    assert exc_info.value.check == "formula.sample_points_strictly_increasing"
    assert str(exc_info.value) == (
        "formula sample points must be strictly increasing after x quantization"
    )
    assert exc_info.value.work_units == 20_002
