# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Finite-SMT obligation engine: exact witnesses, bounds, and context isolation (M5.2b)."""

import importlib.metadata
import inspect
import threading
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from typing import Any

import pytest

from verifier import checks, formal
from verifier.errors import VerificationError
from verifier.formal import (
    BarZeroFacts,
    FormalFacts,
    LegendCategory,
    LegendDomainFacts,
    RankedCell,
    RowOrderFacts,
)
from verifier.limits import VerificationLimits


def _rank(value: int | Fraction, *, null: bool = False) -> RankedCell:
    return RankedCell(is_null=null, rank=value)


def _order_pass() -> RowOrderFacts:
    # Ascending primary key (null last), descending tie-breaker (null first). Fractions exercise
    # exact non-integral + denominator-one construction; integers exercise category ranks.
    return RowOrderFacts(
        directions=("ascending", "descending"),
        rows=(
            (_rank(Fraction(1, 2)), _rank(0, null=True)),
            (_rank(Fraction(1, 2)), _rank(3)),
            (_rank(Fraction(1, 2)), _rank(2)),
            (_rank(Fraction(2, 1)), _rank(1)),
            (_rank(0, null=True), _rank(0)),
        ),
    )


def _legend_pass() -> LegendDomainFacts:
    return LegendDomainFacts(
        plotted=(
            LegendCategory(rank=0, label="EU"),
            LegendCategory(rank=1, label="NA"),
            LegendCategory(rank=0, label="EU"),
        ),
        domain=(LegendCategory(rank=1, label="NA"), LegendCategory(rank=0, label="EU")),
    )


def _all_pass() -> FormalFacts:
    return FormalFacts(
        row_order=_order_pass(),
        bar_zero=BarZeroFacts(
            is_bar=True,
            x_quantitative=True,
            x_zero=True,
            y_quantitative=True,
            y_zero=True,
        ),
        legend_domain=_legend_pass(),
    )


def test_official_z3_runtime_version_matches_locked_distribution() -> None:
    assert importlib.metadata.version("z3-solver") == "4.16.0.0"
    assert formal.solver_version() == "4.16.0"


def test_all_three_obligations_pass_with_bounded_public_free_trace() -> None:
    run = formal.verify_formal(_all_pass())
    assert [(result.check, result.method, result.status) for result in run.results] == [
        ("sort.canonical_order", "z3_smt", "pass"),
        ("scale.bar_zero", "z3_smt", "pass"),
        ("encoding.legend_domain_exact", "z3_smt", "pass"),
    ]
    assert [trace.result_class for trace in run.trace] == ["unsat", "unsat", "unsat"]
    assert all(trace.term_count > 0 for trace in run.trace)
    assert all(
        not hasattr(trace, name) for trace in run.trace for name in ("model", "ast", "context")
    )


def test_row_order_counterexample_uses_lowest_adjacent_row() -> None:
    facts = FormalFacts(
        row_order=RowOrderFacts(
            directions=("ascending",),
            rows=((_rank(2),), (_rank(1),), (_rank(0),)),
        )
    )
    run = formal.verify_formal(facts)
    assert len(run.results) == 1
    result = run.results[0]
    assert (result.check, result.method, result.status, result.message) == (
        "sort.canonical_order",
        "z3_smt",
        "fail",
        "canonical row order is violated between rows 0 and 1",
    )
    assert run.trace[0].result_class == "sat"


def test_bar_counterexample_uses_x_before_y() -> None:
    facts = FormalFacts(
        row_order=RowOrderFacts(rows=(), directions=()),
        bar_zero=BarZeroFacts(
            is_bar=True,
            x_quantitative=True,
            x_zero=False,
            y_quantitative=True,
            y_zero=False,
        ),
    )
    run = formal.verify_formal(facts)
    result = run.results[1]
    assert (result.check, result.status, result.message) == (
        "scale.bar_zero",
        "fail",
        "quantitative bar channel 'x' requires scale.zero=true",
    )
    assert run.trace[1].result_class == "sat"


def test_legend_counterexample_uses_lowest_missing_rank() -> None:
    facts = FormalFacts(
        row_order=RowOrderFacts(rows=(), directions=()),
        legend_domain=LegendDomainFacts(
            plotted=(
                LegendCategory(rank=0, label="EU"),
                LegendCategory(rank=1, label="NA"),
            ),
            domain=(
                LegendCategory(rank=0, label="EU"),
                LegendCategory(rank=2, label="APAC"),
            ),
        ),
    )
    run = formal.verify_formal(facts)
    result = run.results[1]
    assert (result.check, result.status, result.message) == (
        "encoding.legend_domain_exact",
        "fail",
        "legend domain is missing plotted category 'NA' (rank 1)",
    )
    assert run.trace[1].result_class == "sat"


def test_legend_counterexample_reports_extra_domain_category() -> None:
    facts = FormalFacts(
        row_order=RowOrderFacts(rows=(), directions=()),
        legend_domain=LegendDomainFacts(
            plotted=(LegendCategory(rank=0, label="EU"),),
            domain=(
                LegendCategory(rank=0, label="EU"),
                LegendCategory(rank=1, label="NA"),
            ),
        ),
    )
    assert formal.verify_formal(facts).results[1].message == (
        "legend domain has extra category 'NA' (rank 1)"
    )


def test_empty_and_inapplicable_obligations_are_vacuously_unsat() -> None:
    facts = FormalFacts(
        row_order=RowOrderFacts(rows=(), directions=()),
        bar_zero=BarZeroFacts(
            is_bar=False,
            x_quantitative=True,
            x_zero=False,
            y_quantitative=True,
            y_zero=False,
        ),
        legend_domain=LegendDomainFacts(plotted=(), domain=()),
    )
    run = formal.verify_formal(facts)
    assert [result.status for result in run.results] == ["pass", "pass", "pass"]
    assert [trace.result_class for trace in run.trace] == ["unsat", "unsat", "unsat"]


def test_empty_key_rows_have_no_order_counterexample() -> None:
    facts = FormalFacts(row_order=RowOrderFacts(rows=((), ()), directions=()))
    run = formal.verify_formal(facts)
    assert run.results[0].status == "pass"
    assert run.trace[0].result_class == "unsat"


def test_fact_shape_guards_reject_internal_drift() -> None:
    with pytest.raises(ValueError, match="width must equal 1"):
        RowOrderFacts(rows=((_rank(1), _rank(2)),), directions=("ascending",))
    with pytest.raises(ValueError, match="conflicting labels"):
        LegendDomainFacts(
            plotted=(LegendCategory(rank=0, label="EU"),),
            domain=(LegendCategory(rank=0, label="NA"),),
        )


def test_term_budget_accepts_boundary_and_rejects_before_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _all_pass()
    used = sum(trace.term_count for trace in formal.verify_formal(facts).trace)
    exact = formal.verify_formal(facts, limits=VerificationLimits(max_smt_terms=used))
    assert sum(trace.term_count for trace in exact.trace) == used

    def forbidden_context() -> Any:
        message = "over-limit formal input constructed a Z3 context"
        raise AssertionError(message)

    monkeypatch.setattr(formal, "_new_context", forbidden_context)
    with pytest.raises(
        VerificationError, match=rf"requires {used} SMT terms; limit is {used - 1}"
    ) as exc:
        formal.verify_formal(facts, limits=VerificationLimits(max_smt_terms=used - 1))
    assert exc.value.check == "resource.smt_terms"


def test_forced_unknown_or_timeout_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(formal, "_check_solver", lambda _solver: "unknown")
    run = formal.verify_formal(FormalFacts(row_order=_order_pass()))
    result = run.results[0]
    assert (result.check, result.method, result.status) == (
        "formal.solver_completed",
        "z3_smt",
        "fail",
    )
    assert "unknown or timed out" in result.message
    assert run.trace[0].result_class == "unknown"


def test_unrecognized_native_status_maps_to_unknown() -> None:
    class UnknownSolver:
        def check(self) -> object:
            return object()

    assert formal._check_solver(UnknownSolver()) == "unknown"


def test_solver_exception_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_solver(_context: object, _timeout_ms: int) -> Any:
        message = "native detail must not escape"
        raise RuntimeError(message)

    monkeypatch.setattr(formal, "_new_solver", fail_solver)
    run = formal.verify_formal(FormalFacts(row_order=_order_pass()))
    assert run.results[0].check == "formal.solver_completed"
    assert run.results[0].message == (
        "SMT solver invocation failed while checking 'sort.canonical_order'"
    )
    assert "native detail" not in run.results[0].message
    assert run.trace[0].result_class == "exception"


def test_result_registry_drift_remains_a_loud_trusted_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(checks._CHECK_METHODS, "sort.canonical_order")
    with pytest.raises(ValueError, match="no registered verification method"):
        formal.verify_formal(FormalFacts(row_order=RowOrderFacts(rows=(), directions=())))


def test_context_creation_exception_fails_every_obligation_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_context() -> Any:
        message = "context unavailable"
        raise RuntimeError(message)

    monkeypatch.setattr(formal, "_new_context", fail_context)
    run = formal.verify_formal(_all_pass())
    assert [result.check for result in run.results] == ["formal.solver_completed"] * 3
    assert [trace.result_class for trace in run.trace] == ["exception"] * 3


def test_every_obligation_gets_local_timeout_and_distinct_solver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = formal._new_solver
    seen: list[tuple[int, int]] = []

    def recording_solver(context: object, timeout_ms: int) -> Any:
        solver = original(context, timeout_ms)
        seen.append((id(solver), timeout_ms))
        return solver

    monkeypatch.setattr(formal, "_new_solver", recording_solver)
    limits = VerificationLimits(smt_timeout_ms=17)
    assert all(
        result.status == "pass"
        for result in formal.verify_formal(_all_pass(), limits=limits).results
    )
    assert len({solver_id for solver_id, _timeout in seen}) == 3
    assert [timeout for _solver_id, timeout in seen] == [17, 17, 17]


def test_solver_configuration_is_local_single_threaded() -> None:
    class RecordingSolver:
        def __init__(self) -> None:
            self.options: dict[str, int] = {}

        def set(self, **options: int) -> None:
            self.options = options

    solver = RecordingSolver()
    formal._configure_solver(solver, 23)
    assert solver.options == {"timeout": 23, "threads": 1}
    source = inspect.getsource(formal)
    assert "set_param(" not in source
    assert "parse_smt2" not in source
    assert ".from_string(" not in source


def test_concurrent_calls_own_distinct_contexts_and_agree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = formal._new_context
    barrier = threading.Barrier(2)
    contexts: list[object] = []
    lock = threading.Lock()

    def synchronized_context() -> Any:
        context = original()
        with lock:
            contexts.append(context)
        barrier.wait(timeout=10)
        return context

    monkeypatch.setattr(formal, "_new_context", synchronized_context)
    facts = _all_pass()
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(formal.verify_formal, facts)
        second = executor.submit(formal.verify_formal, facts)
        runs = (first.result(timeout=20), second.result(timeout=20))
    assert len(contexts) == 2
    assert contexts[0] is not contexts[1]
    assert runs[0] == runs[1]
