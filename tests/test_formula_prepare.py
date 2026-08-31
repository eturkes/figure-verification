# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Formula preparation: evidence rebinding, resource gates, and nondecreasing-x SMT facts."""

import json
from dataclasses import FrozenInstanceError, fields, replace
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, NoReturn, cast

import msgspec
import pytest

from verifier import canon, checks, formal, formula_prepare
from verifier.errors import VerificationError
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.schema import FormulaPlotSpec, decode_formula_spec

_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLES = _ROOT / "examples"
_GOOD_DIR = _EXAMPLES / "formula_good_specs"
_INDEX: dict[str, Any] = json.loads((_EXAMPLES / "index.json").read_text(encoding="utf-8"))
_GOOD: list[dict[str, Any]] = _INDEX["formula_good_specs"]


def _ids(entries: list[dict[str, Any]]) -> list[str]:
    return [Path(entry["file"]).stem for entry in entries]


def _spec(filename: str = "f02_linear.json") -> FormulaPlotSpec:
    return decode_formula_spec((_GOOD_DIR / filename).read_bytes())


def _two_point_spec() -> FormulaPlotSpec:
    spec = _spec()
    domain = msgspec.structs.replace(spec.domain, stop="1", samples=2)
    return msgspec.structs.replace(spec, formula="x", domain=domain)


def _three_point_spec() -> FormulaPlotSpec:
    spec = _spec()
    domain = msgspec.structs.replace(spec.domain, stop="2", samples=3)
    return msgspec.structs.replace(spec, formula="x", domain=domain)


def _evidence(spec: FormulaPlotSpec) -> checks.FormulaEvidence:
    return checks.verify_formula_run(spec).require_evidence()


@pytest.mark.parametrize("entry", _GOOD, ids=_ids(_GOOD))
def test_formula_good_corpus_core_and_formal_prepare_all_pass(
    entry: dict[str, Any],
) -> None:
    spec = decode_formula_spec((_GOOD_DIR / entry["file"]).read_bytes())
    core = checks.verify_formula_run(spec)
    evidence = core.require_evidence()
    preparation = formula_prepare.prepare_formula(spec, evidence)
    prepared = preparation.prepared

    assert core.report.passed
    assert preparation.report.passed
    assert prepared is not None
    assert preparation.report.results[:-1] == evidence.results
    assert preparation.report.results[-1] == checks.make_result(
        "sort.canonical_order",
        status="pass",
        message="sampled x values are nondecreasing in ascending order",
    )
    assert preparation.formal_trace == (
        formal.FormalTrace(
            obligation="sort.canonical_order",
            term_count=24 * len(evidence.plotted_table.rows) - 17,
            result_class="unsat",
        ),
    )
    assert prepared.spec is spec
    assert prepared.evidence is evidence
    assert prepared.results == preparation.report.results


def test_preparation_types_are_frozen_slotted_and_closed() -> None:
    spec = _two_point_spec()
    preparation = formula_prepare.prepare_formula(spec, _evidence(spec))
    prepared = preparation.prepared
    assert prepared is not None

    assert tuple(item.name for item in fields(formula_prepare.PreparedFormula)) == (
        "spec",
        "evidence",
        "results",
    )
    assert tuple(item.name for item in fields(formula_prepare.FormulaPreparationRun)) == (
        "report",
        "formal_trace",
        "prepared",
    )
    assert not hasattr(prepared, "__dict__")
    frozen_field = "results"
    with pytest.raises(FrozenInstanceError):
        setattr(prepared, frozen_field, ())


def test_formula_row_order_facts_project_one_exact_ascending_x_rank() -> None:
    spec = _spec("f06_quadratic.json")
    facts = formula_prepare.formula_row_order_facts(_evidence(spec))
    assert facts.directions == ("ascending",)
    assert tuple(row[0].rank for row in facts.rows) == (
        Fraction(0),
        Fraction(1, 2),
        Fraction(1),
        Fraction(3, 2),
        Fraction(2),
        Fraction(5, 2),
        Fraction(3),
    )
    assert all(len(row) == 1 and not row[0].is_null for row in facts.rows)


def test_formula_row_order_rank_keeps_exact_decimal() -> None:
    evidence = _evidence(_spec("f03_cubic.json"))
    facts = formula_prepare.formula_row_order_facts(evidence)
    x_values = tuple(cast(Decimal, row[0]) for row in evidence.plotted_table.rows)
    expected = tuple(Fraction(x) for x in x_values)

    assert Fraction(1, 5) in expected
    assert tuple(row[0].rank for row in facts.rows) == expected


def test_formula_preparation_bridge_rejects_descending_evidence() -> None:
    spec = _three_point_spec()
    evidence = _evidence(spec)
    rows = evidence.plotted_table.rows
    descending_table = canon.Table(
        columns=evidence.plotted_table.columns,
        rows=(rows[0], rows[2], rows[1]),
    )
    descending = replace(
        evidence,
        plotted_table=descending_table,
        plotted_table_hash=canon.hash_table(descending_table),
    )

    preparation = formula_prepare.prepare_formula(spec, descending)
    assert preparation.report.results[-1] == checks.make_result(
        "sort.canonical_order",
        status="fail",
        message="sampled x values descend between rows 1 and 2",
    )
    assert not preparation.report.passed
    assert preparation.prepared is None


def test_formula_preparation_rejects_spec_rebind_before_fact_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec()
    evidence = _evidence(spec)
    different = msgspec.structs.replace(spec, mark="scatter")
    facts_called = False

    def forbidden_facts(_evidence_value: checks.FormulaEvidence) -> NoReturn:
        nonlocal facts_called
        facts_called = True
        raise AssertionError

    monkeypatch.setattr(formula_prepare, "formula_row_order_facts", forbidden_facts)
    with pytest.raises(ValueError, match="does not match evidence"):
        formula_prepare.prepare_formula(different, evidence)
    assert not facts_called


def test_formula_render_row_boundary_and_ceiling_plus_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _two_point_spec()
    evidence = _evidence(spec)
    boundary = msgspec.structs.replace(DEFAULT_LIMITS, max_render_rows=2)
    assert formula_prepare.prepare_formula(spec, evidence, limits=boundary).report.passed

    fact_calls = 0
    formal_calls = 0

    def forbidden_facts(_evidence_value: checks.FormulaEvidence) -> NoReturn:
        nonlocal fact_calls
        fact_calls += 1
        raise AssertionError

    def forbidden_formal(
        _facts: formal.FormalFacts,
        *,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> NoReturn:
        nonlocal formal_calls
        del limits
        formal_calls += 1
        raise AssertionError

    monkeypatch.setattr(formula_prepare, "formula_row_order_facts", forbidden_facts)
    monkeypatch.setattr(formal, "verify_formal", forbidden_formal)
    over = msgspec.structs.replace(DEFAULT_LIMITS, max_render_rows=1)
    with pytest.raises(VerificationError) as caught:
        formula_prepare.prepare_formula(spec, evidence, limits=over)
    assert caught.value.check == "resource.render_rows"
    assert str(caught.value) == "plotted table has 2 render rows; limit is 1"
    assert fact_calls == 0
    assert formal_calls == 0


def test_formula_preparation_forwards_the_caller_limits_object_to_the_formal_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`smt_timeout_ms` reaches Z3 only here: pin the caller's own object, not an equal default."""
    spec = _two_point_spec()
    evidence = _evidence(spec)
    caller_limits = msgspec.structs.replace(DEFAULT_LIMITS, smt_timeout_ms=17)
    assert caller_limits.smt_timeout_ms != DEFAULT_LIMITS.smt_timeout_ms
    observed: list[VerificationLimits] = []
    verify_formal = formal.verify_formal

    def spy(
        facts: formal.FormalFacts,
        *,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> formal.FormalRun:
        observed.append(limits)
        return verify_formal(facts, limits=limits)

    monkeypatch.setattr(formal, "verify_formal", spy)
    preparation = formula_prepare.prepare_formula(spec, evidence, limits=caller_limits)

    assert preparation.report.passed
    assert len(observed) == 1
    assert observed[0] is caller_limits
    assert observed[0].smt_timeout_ms == 17


def test_formula_smt_term_boundary_and_ceiling_plus_one_precede_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _two_point_spec()
    evidence = _evidence(spec)
    boundary = msgspec.structs.replace(DEFAULT_LIMITS, max_smt_terms=31)
    preparation = formula_prepare.prepare_formula(spec, evidence, limits=boundary)
    assert preparation.report.passed
    assert preparation.formal_trace[0].term_count == 31

    context_calls = 0

    def forbidden_context() -> NoReturn:
        nonlocal context_calls
        context_calls += 1
        raise AssertionError

    monkeypatch.setattr(formal, "_new_context", forbidden_context)
    over = msgspec.structs.replace(DEFAULT_LIMITS, max_smt_terms=30)
    with pytest.raises(VerificationError) as caught:
        formula_prepare.prepare_formula(spec, evidence, limits=over)
    assert caught.value.check == "resource.smt_terms"
    assert str(caught.value) == "formal check requires 31 SMT terms; limit is 30"
    assert context_calls == 0


def test_joint_formula_rows_cross_smt_term_limit_without_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = tuple(
        (formal.RankedCell(is_null=False, rank=Fraction(index)),) for index in range(4_168)
    )
    limits = msgspec.structs.replace(DEFAULT_LIMITS, max_smt_terms=100_000)
    context_calls = 0

    def forbidden_context() -> NoReturn:
        nonlocal context_calls
        context_calls += 1
        raise AssertionError

    monkeypatch.setattr(formal, "_new_context", forbidden_context)
    admitted = formal.verify_formal(
        formal.FormalFacts(
            row_order=formal.RowOrderFacts(rows=rows[:-1], directions=("ascending",)),
            bar_zero=None,
            legend_domain=None,
        ),
        limits=limits,
    )
    assert admitted.trace == (
        formal.FormalTrace(
            obligation="sort.canonical_order",
            term_count=99_991,
            result_class="exception",
        ),
    )
    assert context_calls == 1

    with pytest.raises(VerificationError) as caught:
        formal.verify_formal(
            formal.FormalFacts(
                row_order=formal.RowOrderFacts(rows=rows, directions=("ascending",)),
                bar_zero=None,
                legend_domain=None,
            ),
            limits=limits,
        )
    assert caught.value.check == "resource.smt_terms"
    assert str(caught.value) == "formal check requires 100015 SMT terms; limit is 100000"
    assert context_calls == 1


@pytest.mark.parametrize(
    ("failure_mode", "result_class"),
    [("unknown", "unknown"), ("exception", "exception")],
)
def test_formula_solver_uncertainty_fails_closed_without_prepared_artifact(
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
    result_class: str,
) -> None:
    spec = _two_point_spec()
    evidence = _evidence(spec)
    if failure_mode == "unknown":

        def unknown(_solver: object) -> str:
            return "unknown"

        monkeypatch.setattr(formal, "_check_solver", unknown)
    else:

        def fail_solver(_context: object, _timeout_ms: int) -> NoReturn:
            raise RuntimeError

        monkeypatch.setattr(formal, "_new_solver", fail_solver)

    preparation = formula_prepare.prepare_formula(spec, evidence)
    result = preparation.report.results[-1]
    assert preparation.report.results[:-1] == evidence.results
    assert (result.check, result.method, result.status) == (
        "formal.solver_completed",
        "z3_smt",
        "fail",
    )
    assert preparation.formal_trace[0].result_class == result_class
    assert not preparation.report.passed
    assert preparation.prepared is None


def test_formula_order_formal_layer_accepts_equality_and_rejects_descending() -> None:
    def facts(values: tuple[int, ...]) -> formal.FormalFacts:
        return formal.FormalFacts(
            row_order=formal.RowOrderFacts(
                rows=tuple((formal.RankedCell(is_null=False, rank=value),) for value in values),
                directions=("ascending",),
            ),
            bar_zero=None,
            legend_domain=None,
        )

    equal = formal.verify_formal(facts((1, 1)))
    descending = formal.verify_formal(facts((2, 1)))
    assert (equal.results[0].check, equal.results[0].status) == (
        "sort.canonical_order",
        "pass",
    )
    assert equal.trace[0].result_class == "unsat"
    assert (descending.results[0].check, descending.results[0].status) == (
        "sort.canonical_order",
        "fail",
    )
    assert descending.trace[0].result_class == "sat"
