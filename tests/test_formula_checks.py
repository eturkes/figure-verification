# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Formula core verification: concrete lifecycle, corpus, gates, and evidence bindings."""

import json
from dataclasses import FrozenInstanceError, fields, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, NoReturn

import msgspec
import pytest

from verifier import canon, checks, formula_prepare
from verifier.eval import EvaluationError, FormulaEvaluationRun, evaluate_formula_run
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.schema import FormulaPlotSpec, decode_formula_spec

_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLES = _ROOT / "examples"
_GOOD_DIR = _EXAMPLES / "formula_good_specs"
_BAD_DIR = _EXAMPLES / "formula_bad_specs"
_INDEX: dict[str, Any] = json.loads((_EXAMPLES / "index.json").read_text(encoding="utf-8"))
_GOOD: list[dict[str, Any]] = _INDEX["formula_good_specs"]
_BAD_LATER: list[dict[str, Any]] = [
    entry for entry in _INDEX["formula_bad_specs"] if entry["decodes"]
]


def _ids(entries: list[dict[str, Any]]) -> list[str]:
    return [Path(entry["file"]).stem for entry in entries]


def _spec(filename: str = "f02_linear.json") -> FormulaPlotSpec:
    return decode_formula_spec((_GOOD_DIR / filename).read_bytes())


def _two_point_spec() -> FormulaPlotSpec:
    spec = _spec()
    domain = msgspec.structs.replace(spec.domain, stop="1", samples=2)
    return msgspec.structs.replace(spec, formula="x", domain=domain)


def test_formula_run_types_are_concrete_frozen_slotted_and_lifecycle_checked() -> None:
    assert tuple(item.name for item in fields(checks.FormulaVerificationTrace)) == (
        "formula_work_units",
    )
    assert tuple(item.name for item in fields(checks.FormulaVerificationRun)) == (
        "report",
        "trace",
        "evidence",
    )

    successful = checks.verify_formula_run(_two_point_spec())
    evidence = successful.require_evidence()
    assert successful.evidence is evidence
    assert not hasattr(successful, "__dict__")
    frozen_field = "formula_work_units"
    with pytest.raises(FrozenInstanceError):
        setattr(successful.trace, frozen_field, 0)

    failed_formula = checks.verify_formula_run(
        decode_formula_spec((_BAD_DIR / "fb17_reversed_domain.json").read_bytes())
    )
    with pytest.raises(ValueError, match="formula verification run has no evidence"):
        failed_formula.require_evidence()

    failed_dataset = checks.VerificationRun(
        report=checks.VerificationReport(results=()),
        trace=checks.VerificationTrace(manifest_bytes=None, source_bytes=None),
        evidence=None,
    )
    with pytest.raises(ValueError, match="dataset verification run has no evidence"):
        failed_dataset.require_evidence()


@pytest.mark.parametrize("entry", _BAD_LATER, ids=_ids(_BAD_LATER))
def test_formula_bad_corpus_fails_at_indexed_first_check_without_artifact(
    entry: dict[str, Any],
) -> None:
    spec = decode_formula_spec((_BAD_DIR / entry["file"]).read_bytes())
    run = checks.verify_formula_run(spec)
    failures = [result.check for result in run.report.results if result.status == "fail"]
    assert failures == [entry["check"]]
    assert not run.report.passed
    evidence = run.evidence
    preparation = formula_prepare.prepare_formula(spec, evidence) if evidence is not None else None
    assert evidence is None
    assert preparation is None


@pytest.mark.parametrize(
    "filename",
    ("fb15_disallowed_function.json", "fb17_reversed_domain.json"),
    ids=("parser-rejection", "pre-parser-domain-rejection"),
)
def test_formula_security_affirmation_describes_the_only_execution_path(
    filename: str,
) -> None:
    spec = decode_formula_spec((_BAD_DIR / filename).read_bytes())
    run = checks.verify_formula_run(spec)
    assert run.report.results[0] == checks.make_result(
        "security.no_arbitrary_code",
        status="pass",
        message=(
            "formula text can reach evaluation only through the closed verifier-owned AST "
            "interpreter; this path never executes it as Python"
        ),
    )


def test_formula_success_results_methods_messages_and_evidence_bind_one_run() -> None:
    spec = _spec("f04_rational.json")
    evaluated = evaluate_formula_run(spec)
    run = checks.verify_formula_run(spec)
    evidence = run.require_evidence()

    assert [(result.check, result.method, result.status) for result in run.report.results] == [
        ("security.no_arbitrary_code", "construction", "pass"),
        ("formula.values_bounded", "deterministic_recompute", "pass"),
        ("formula.hash_matches_source", "deterministic_recompute", "pass"),
        ("formula.points_from_recomputation", "construction", "pass"),
        ("formula.rounding_unambiguous", "construction", "pass"),
        ("encoding.fields_exist_in_plotted_table", "deterministic_recompute", "pass"),
        ("encoding.axis_types_match_fields", "deterministic_recompute", "pass"),
    ]
    messages = {result.check: result.message for result in run.report.results}
    assert messages["security.no_arbitrary_code"] == (
        "formula text can reach evaluation only through the closed verifier-owned AST "
        "interpreter; this path never executes it as Python"
    )
    assert messages["formula.values_bounded"] == (
        "successful evaluator completion disclosed that all admitted sampled and intermediate "
        "values passed its configured bounds"
    )
    assert messages["formula.hash_matches_source"] == (
        "the verifier computed the formula hash from this run's exact canonical resolved-source "
        "bytes"
    )
    assert messages["formula.points_from_recomputation"] == (
        "the sampled table contains evaluator-produced points; the spec supplies no candidate "
        "point values"
    )
    assert messages["formula.rounding_unambiguous"] == (
        "the numeric profile fixes one rounding rule that the verifier applies deterministically "
        "to x and y quantization"
    )
    assert not {
        "label.quantitative_units_present",
        "transform.ops_allowed",
        "transform.filters_declared",
        "transform.aggregates_match_recomputation",
        "render.float64_fidelity",
        "resource.matplotlib_script_bytes",
        "resource.attestation_bytes",
    } & {result.check for result in run.report.results}

    assert run.trace.formula_work_units == evaluated.work_units
    assert evidence.formula_source == evaluated.formula_source
    assert evidence.formula_source_bytes == canon.formula_source_bytes(evaluated.formula_source)
    assert evidence.formula_hash == canon.hash_formula_source(evidence.formula_source_bytes)
    assert evidence.spec_hash == canon.hash_spec(spec)
    assert evidence.plotted_table == evaluated.table
    assert evidence.plotted_table_hash == canon.hash_table(evaluated.table)
    assert evidence.results == run.report.results


def test_formula_verification_invokes_evaluator_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def counted(
        spec: FormulaPlotSpec,
        *,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> FormulaEvaluationRun:
        nonlocal calls
        calls += 1
        return evaluate_formula_run(spec, limits=limits)

    monkeypatch.setattr(checks, "evaluate_formula_run", counted)
    run = checks.verify_formula_run(_two_point_spec())
    assert run.report.passed
    assert calls == 1


def test_formula_evaluator_failure_preserves_id_message_method_and_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(
        _specification: FormulaPlotSpec,
        *,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> NoReturn:
        del limits
        message = "sample is undefined"
        raise EvaluationError(
            message,
            check="formula.values_defined",
            work_units=37,
        )

    monkeypatch.setattr(checks, "evaluate_formula_run", fail)
    run = checks.verify_formula_run(_two_point_spec())
    assert [
        (result.check, result.method, result.status, result.message)
        for result in run.report.results
    ] == [
        (
            "security.no_arbitrary_code",
            "construction",
            "pass",
            "formula text can reach evaluation only through the closed verifier-owned AST "
            "interpreter; this path never executes it as Python",
        ),
        (
            "formula.values_defined",
            "deterministic_recompute",
            "fail",
            "sample is undefined",
        ),
    ]
    assert run.trace.formula_work_units == 37
    assert run.evidence is None


def test_formula_plotted_cell_boundary_precedes_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _two_point_spec()
    boundary = msgspec.structs.replace(DEFAULT_LIMITS, max_plotted_cells=4)
    assert checks.verify_formula_run(spec, limits=boundary).report.passed

    encoding_calls = 0

    def forbidden_encoding(
        _specification: FormulaPlotSpec,
        _plotted_table: canon.Table,
    ) -> NoReturn:
        nonlocal encoding_calls
        encoding_calls += 1
        raise AssertionError

    monkeypatch.setattr(checks, "_formula_encoding_checks", forbidden_encoding)
    over = msgspec.structs.replace(DEFAULT_LIMITS, max_plotted_cells=3)
    run = checks.verify_formula_run(spec, limits=over)
    assert run.report.results[-1] == checks.make_result(
        "resource.plotted_cells",
        status="fail",
        message="plotted table has 4 cells; limit is 3",
    )
    assert encoding_calls == 0
    assert run.evidence is None


def test_formula_verify_threads_caller_limits() -> None:
    limits = msgspec.structs.replace(DEFAULT_LIMITS, max_formula_samples=1)
    run = checks.verify_formula_run(_two_point_spec(), limits=limits)

    assert run.report.results[-1] == checks.make_result(
        "resource.formula_samples",
        status="fail",
        message="formula sample limit 1 exceeded: 2 requested",
    )
    assert not run.report.passed
    assert run.trace == checks.FormulaVerificationTrace(formula_work_units=0)
    assert run.evidence is None
    with pytest.raises(ValueError, match="formula verification run has no evidence"):
        run.require_evidence()


def test_plotted_cell_refusal_precedes_evidence_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _two_point_spec()
    hash_calls: list[str] = []

    def forbidden_spec_hash(_value: object) -> NoReturn:
        hash_calls.append("spec")
        raise AssertionError

    def forbidden_table_hash(_value: object) -> NoReturn:
        hash_calls.append("table")
        raise AssertionError

    monkeypatch.setattr(canon, "hash_spec", forbidden_spec_hash)
    monkeypatch.setattr(canon, "hash_table", forbidden_table_hash)
    limits = msgspec.structs.replace(DEFAULT_LIMITS, max_plotted_cells=3)
    run = checks.verify_formula_run(spec, limits=limits)

    assert run.report.results[-1] == checks.make_result(
        "resource.plotted_cells",
        status="fail",
        message="plotted table has 4 cells; limit is 3",
    )
    assert hash_calls == []
    assert run.evidence is None


def test_plotted_cell_refusal_precedes_evidence_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    construction_calls = 0

    def forbidden_evidence(**_kwargs: object) -> NoReturn:
        nonlocal construction_calls
        construction_calls += 1
        raise AssertionError

    monkeypatch.setattr(checks, "FormulaEvidence", forbidden_evidence)
    limits = msgspec.structs.replace(DEFAULT_LIMITS, max_plotted_cells=3)
    run = checks.verify_formula_run(_two_point_spec(), limits=limits)

    assert run.report.results[-1] == checks.make_result(
        "resource.plotted_cells",
        status="fail",
        message="plotted table has 4 cells; limit is 3",
    )
    assert construction_calls == 0
    assert run.evidence is None


def test_joint_formula_samples_times_table_width_is_not_clamped() -> None:
    spec = _two_point_spec()
    domain = msgspec.structs.replace(spec.domain, stop="2", samples=3)
    spec = msgspec.structs.replace(spec, domain=domain)
    limits = msgspec.structs.replace(
        DEFAULT_LIMITS,
        max_formula_samples=3,
        max_plotted_cells=5,
    )
    run = checks.verify_formula_run(spec, limits=limits)

    assert run.report.results[-1] == checks.make_result(
        "resource.plotted_cells",
        status="fail",
        message="plotted table has 6 cells; limit is 5",
    )
    assert run.trace == checks.FormulaVerificationTrace(formula_work_units=18)
    assert run.evidence is None


@pytest.mark.parametrize(
    ("table", "expected"),
    [
        (
            canon.Table(
                columns=(canon.NumericColumn(name="x", scale=0),),
                rows=((Decimal(0),), (Decimal(1),)),
            ),
            {
                "encoding.fields_exist_in_plotted_table": "fail",
                "encoding.axis_types_match_fields": "pass",
            },
        ),
        (
            canon.Table(
                columns=(
                    canon.NumericColumn(name="x", scale=0),
                    canon.StringColumn(name="y"),
                ),
                rows=((Decimal(0), "0"), (Decimal(1), "1")),
            ),
            {
                "encoding.fields_exist_in_plotted_table": "pass",
                "encoding.axis_types_match_fields": "fail",
            },
        ),
    ],
    ids=("missing-field", "wrong-kind"),
)
def test_formula_encoding_checks_reject_malformed_successful_evaluator_table(
    monkeypatch: pytest.MonkeyPatch,
    table: canon.Table,
    expected: dict[str, str],
) -> None:
    spec = _two_point_spec()
    evaluated = evaluate_formula_run(spec)

    def malformed(
        _specification: FormulaPlotSpec,
        *,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> FormulaEvaluationRun:
        del limits
        return replace(evaluated, table=table)

    monkeypatch.setattr(checks, "evaluate_formula_run", malformed)
    run = checks.verify_formula_run(spec)
    statuses = {
        result.check: result.status
        for result in run.report.results
        if result.check.startswith("encoding.")
    }
    assert statuses == expected
    assert run.evidence is None
