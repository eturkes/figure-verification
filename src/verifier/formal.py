# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Finite SMT checks over one concrete plotted table + builder artifact.

This module is the sole production boundary around z3-solver's dynamic Python API. Callers provide
only immutable typed facts and receive public ``CheckResult`` values plus bounded ``FormalTrace``
metadata; no Z3 context, AST, solver, model, or model text crosses the boundary.

The obligations are deliberately finite and quantifier-free. ``sort.canonical_order`` rejects the
first adjacent row inversion under the declared keys + canonical tail. ``scale.bar_zero`` requires
each quantitative positional channel on a bar to carry an explicit true zero baseline.
``encoding.legend_domain_exact`` requires set equality between plotted discrete categories and the
explicit color scale domain. Each solver searches for the negation (a counterexample): UNSAT passes,
SAT fails with the unique lowest witness, and UNKNOWN/timeout/exception fails closed.

Every call owns one explicit Z3 Context and creates one solver per applicable obligation. Solver
timeout + single-thread settings are local; this module never mutates Z3 global parameters. Term
counts conservatively cover every AST constructor used below and are summed before the Context or
any AST exists, so ``resource.smt_terms`` rejects an over-limit call without partial solver work.
"""

from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from functools import partial
from itertools import pairwise
from typing import Any, Literal, cast

import z3

from verifier.checks import CheckResult, make_result
from verifier.errors import VerificationError
from verifier.limits import DEFAULT_LIMITS, VerificationLimits

__all__ = [
    "BarZeroFacts",
    "FormalFacts",
    "FormalRun",
    "FormalTrace",
    "LegendCategory",
    "LegendDomainFacts",
    "RankedCell",
    "RowOrderFacts",
    "solver_version",
    "verify_formal",
]

type Rank = int | Fraction
type SortDirection = Literal["ascending", "descending"]
type FormalObligation = Literal[
    "sort.canonical_order",
    "scale.bar_zero",
    "encoding.legend_domain_exact",
]
type ResultClass = Literal["unsat", "sat", "unknown", "exception"]
type _SolverResultClass = Literal["unsat", "sat", "unknown"]

_SOLVER_COMPLETED = "formal.solver_completed"


@dataclass(frozen=True, slots=True)
class RankedCell:
    """One sortable value: null flag + exact numeric or precomputed category rank.

    Null ranks are ignored. Non-null numeric ranks may be exact ``Fraction`` values; temporal and
    string facts use monotone integer category ranks chosen by the later artifact fact builder.
    """

    is_null: bool
    rank: Rank


@dataclass(frozen=True, slots=True)
class RowOrderFacts:
    """Rows projected onto the active declared keys + ascending canonical tail."""

    rows: tuple[tuple[RankedCell, ...], ...]
    directions: tuple[SortDirection, ...]

    def __post_init__(self) -> None:
        width = len(self.directions)
        if any(len(row) != width for row in self.rows):
            msg = f"row-order fact width must equal {width} directions"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class BarZeroFacts:
    """Exact mark/channel/scale facts read from the built Vega-Lite object."""

    is_bar: bool
    x_quantitative: bool
    x_zero: bool
    y_quantitative: bool
    y_zero: bool


@dataclass(frozen=True, slots=True)
class LegendCategory:
    """One plotted/domain category's shared integer rank + readable canonical label."""

    rank: int
    label: str


@dataclass(frozen=True, slots=True)
class LegendDomainFacts:
    """Discrete plotted color occurrences and explicit scale-domain entries."""

    plotted: tuple[LegendCategory, ...]
    domain: tuple[LegendCategory, ...]

    def __post_init__(self) -> None:
        labels: dict[int, str] = {}
        for category in self.plotted + self.domain:
            prior = labels.setdefault(category.rank, category.label)
            if prior != category.label:
                msg = (
                    f"category rank {category.rank} has conflicting labels "
                    f"{prior!r} and {category.label!r}"
                )
                raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class FormalFacts:
    """One formal invocation; optional facts mean the conditional check is inapplicable."""

    row_order: RowOrderFacts
    bar_zero: BarZeroFacts | None = None
    legend_domain: LegendDomainFacts | None = None


@dataclass(frozen=True, slots=True)
class FormalTrace:
    """Bounded internal solver metadata; never includes a model, reason string, or AST."""

    obligation: FormalObligation
    term_count: int
    result_class: ResultClass


@dataclass(frozen=True, slots=True)
class FormalRun:
    """Structured formal results plus one internal trace entry per applicable obligation."""

    results: tuple[CheckResult, ...]
    trace: tuple[FormalTrace, ...]


@dataclass(frozen=True, slots=True)
class _SolverOutcome:
    result_class: _SolverResultClass
    witness: int = 0


@dataclass(frozen=True, slots=True)
class _Plan:
    obligation: FormalObligation
    term_count: int
    solve: Callable[[Any, int], _SolverOutcome]
    success_message: str
    counterexample_message: Callable[[int], str]


@dataclass(frozen=True, slots=True)
class _Z3Cell:
    is_null: Any
    rank: Any


def solver_version() -> str:
    """The native Z3 semantic version through the typed boundary (for later TCB stamping)."""
    return cast(str, z3.get_version_string())


def _new_context() -> Any:
    """Create the one explicit context wholly owned by a ``verify_formal`` call."""
    return z3.Context()


def _configure_solver(solver: Any, timeout_ms: int) -> None:
    """Apply solver-local resource/determinism settings; never touch global Z3 parameters."""
    solver.set(timeout=timeout_ms, threads=1)


def _new_solver(context: Any, timeout_ms: int) -> Any:
    solver = z3.Solver(ctx=context)
    _configure_solver(solver, timeout_ms)
    return solver


def _check_solver(solver: Any) -> _SolverResultClass:
    result = solver.check()
    if result == z3.unsat:
        return "unsat"
    if result == z3.sat:
        return "sat"
    return "unknown"


def _model_int(solver: Any, expression: Any) -> int:
    value = solver.model().eval(expression, model_completion=True)
    return cast(int, value.as_long())


def _or(expressions: list[Any], context: Any) -> Any:
    return z3.Or(*expressions) if expressions else z3.BoolVal(val=False, ctx=context)


def _rank_expression(rank: Rank, context: Any) -> Any:
    if isinstance(rank, int):
        return z3.RealVal(rank, ctx=context)
    numerator = z3.RealVal(rank.numerator, ctx=context)
    if rank.denominator == 1:
        return numerator
    denominator = z3.RealVal(rank.denominator, ctx=context)
    return numerator / denominator


def _z3_cell(cell: RankedCell, context: Any) -> _Z3Cell:
    return _Z3Cell(
        is_null=z3.BoolVal(cell.is_null, ctx=context),
        rank=_rank_expression(cell.rank, context),
    )


def _cell_equal(left: _Z3Cell, right: _Z3Cell) -> Any:
    return z3.And(
        left.is_null == right.is_null,
        z3.Or(left.is_null, left.rank == right.rank),
    )


def _cell_after(left: _Z3Cell, right: _Z3Cell, direction: SortDirection) -> Any:
    """Whether ``left`` belongs after ``right`` under one key (an adjacent inversion)."""
    left_present = z3.Not(left.is_null)
    right_present = z3.Not(right.is_null)
    both_present = z3.And(left_present, right_present)
    if direction == "ascending":
        null_inversion = z3.And(left.is_null, right_present)
        rank_inversion = left.rank > right.rank
    else:
        null_inversion = z3.And(right.is_null, left_present)
        rank_inversion = left.rank < right.rank
    return z3.Or(null_inversion, z3.And(both_present, rank_inversion))


def _row_inversion(
    left: tuple[_Z3Cell, ...],
    right: tuple[_Z3Cell, ...],
    directions: tuple[SortDirection, ...],
    context: Any,
) -> Any:
    prefix_equal = z3.BoolVal(val=True, ctx=context)
    inversions: list[Any] = []
    for left_cell, right_cell, direction in zip(left, right, directions, strict=True):
        inversions.append(z3.And(prefix_equal, _cell_after(left_cell, right_cell, direction)))
        prefix_equal = z3.And(prefix_equal, _cell_equal(left_cell, right_cell))
    return _or(inversions, context)


def _lowest_index_witness(solver: Any, violations: list[Any], context: Any) -> Any:
    """Assert a violation and force its model witness to the lowest violating list index."""
    witness = z3.Int("witness", ctx=context)
    prefix_holds = z3.BoolVal(val=True, ctx=context)
    cases: list[Any] = []
    for index, violation in enumerate(violations):
        index_expression = z3.IntVal(index, ctx=context)
        cases.append(z3.And(witness == index_expression, prefix_holds, violation))
        prefix_holds = z3.And(prefix_holds, z3.Not(violation))
    solver.add(_or(cases, context))
    return witness


def _order_term_count(facts: RowOrderFacts) -> int:
    """Conservative constructor count: ranked cells + comparisons + lowest-row witness."""
    row_count = len(facts.rows)
    key_count = len(facts.directions)
    pair_count = max(row_count - 1, 0)
    return 4 * row_count * key_count + pair_count * (13 * key_count + 6) + 3


def _solve_order(facts: RowOrderFacts, context: Any, timeout_ms: int) -> _SolverOutcome:
    solver = _new_solver(context, timeout_ms)
    rows = tuple(tuple(_z3_cell(cell, context) for cell in row) for row in facts.rows)
    violations = [
        _row_inversion(left, right, facts.directions, context) for left, right in pairwise(rows)
    ]
    witness = _lowest_index_witness(solver, violations, context)
    result_class = _check_solver(solver)
    if result_class == "sat":
        return _SolverOutcome(result_class="sat", witness=_model_int(solver, witness))
    return _SolverOutcome(result_class=result_class)


def _order_message(witness: int) -> str:
    return f"canonical row order is violated between rows {witness} and {witness + 1}"


def _bar_channels(facts: BarZeroFacts) -> list[tuple[str, bool]]:
    channels: list[tuple[str, bool]] = []
    if facts.is_bar and facts.x_quantitative:
        channels.append(("x", facts.x_zero))
    if facts.is_bar and facts.y_quantitative:
        channels.append(("y", facts.y_zero))
    return channels


def _bar_term_count(facts: BarZeroFacts) -> int:
    # Bool + negation per applicable channel; five nodes per lowest-index witness candidate.
    return 7 * len(_bar_channels(facts)) + 3


def _solve_bar(facts: BarZeroFacts, context: Any, timeout_ms: int) -> _SolverOutcome:
    solver = _new_solver(context, timeout_ms)
    violations = [z3.Not(z3.BoolVal(zero, ctx=context)) for _channel, zero in _bar_channels(facts)]
    witness = _lowest_index_witness(solver, violations, context)
    result_class = _check_solver(solver)
    if result_class == "sat":
        return _SolverOutcome(result_class="sat", witness=_model_int(solver, witness))
    return _SolverOutcome(result_class=result_class)


def _bar_message(facts: BarZeroFacts, witness: int) -> str:
    channel = _bar_channels(facts)[witness][0]
    return f"quantitative bar channel {channel!r} requires scale.zero=true"


def _legend_labels(facts: LegendDomainFacts) -> dict[int, str]:
    return {category.rank: category.label for category in facts.plotted + facts.domain}


def _legend_ranks(facts: LegendDomainFacts) -> list[int]:
    return sorted(_legend_labels(facts))


def _legend_term_count(facts: LegendDomainFacts) -> int:
    candidates = len(_legend_ranks(facts))
    occurrences = len(facts.plotted) + len(facts.domain)
    # Shared rank constants + per-candidate membership/XOR + lowest-rank witness constraints.
    return 3 + candidates * (occurrences + 8)


def _member(
    candidate: Any,
    categories: tuple[LegendCategory, ...],
    ranks: dict[int, Any],
    context: Any,
) -> Any:
    return _or([candidate == ranks[category.rank] for category in categories], context)


def _solve_legend(facts: LegendDomainFacts, context: Any, timeout_ms: int) -> _SolverOutcome:
    solver = _new_solver(context, timeout_ms)
    candidate_ranks = _legend_ranks(facts)
    ranks = {rank: z3.IntVal(rank, ctx=context) for rank in candidate_ranks}
    violations = [
        z3.Xor(
            _member(ranks[rank], facts.plotted, ranks, context),
            _member(ranks[rank], facts.domain, ranks, context),
        )
        for rank in candidate_ranks
    ]

    witness = z3.Int("witness", ctx=context)
    prefix_holds = z3.BoolVal(val=True, ctx=context)
    cases: list[Any] = []
    for rank, violation in zip(candidate_ranks, violations, strict=True):
        cases.append(z3.And(witness == ranks[rank], prefix_holds, violation))
        prefix_holds = z3.And(prefix_holds, z3.Not(violation))
    solver.add(_or(cases, context))

    result_class = _check_solver(solver)
    if result_class == "sat":
        return _SolverOutcome(result_class="sat", witness=_model_int(solver, witness))
    return _SolverOutcome(result_class=result_class)


def _legend_message(facts: LegendDomainFacts, witness: int) -> str:
    label = _legend_labels(facts)[witness]
    plotted_ranks = {category.rank for category in facts.plotted}
    if witness in plotted_ranks:
        return f"legend domain is missing plotted category {label!r} (rank {witness})"
    return f"legend domain has extra category {label!r} (rank {witness})"


def _plans(facts: FormalFacts) -> list[_Plan]:
    plans = [
        _Plan(
            obligation="sort.canonical_order",
            term_count=_order_term_count(facts.row_order),
            solve=partial(_solve_order, facts.row_order),
            success_message="canonical row order matches the active sort and canonical tail",
            counterexample_message=_order_message,
        )
    ]
    if facts.bar_zero is not None:
        plans.append(
            _Plan(
                obligation="scale.bar_zero",
                term_count=_bar_term_count(facts.bar_zero),
                solve=partial(_solve_bar, facts.bar_zero),
                success_message="every quantitative bar channel has scale.zero=true",
                counterexample_message=partial(_bar_message, facts.bar_zero),
            )
        )
    if facts.legend_domain is not None:
        plans.append(
            _Plan(
                obligation="encoding.legend_domain_exact",
                term_count=_legend_term_count(facts.legend_domain),
                solve=partial(_solve_legend, facts.legend_domain),
                success_message="discrete legend domain exactly matches plotted categories",
                counterexample_message=partial(_legend_message, facts.legend_domain),
            )
        )
    return plans


def _solver_failed(plan: _Plan) -> tuple[CheckResult, FormalTrace]:
    message = f"SMT solver invocation failed while checking {plan.obligation!r}"
    return (
        make_result(_SOLVER_COMPLETED, status="fail", message=message),
        FormalTrace(
            obligation=plan.obligation,
            term_count=plan.term_count,
            result_class="exception",
        ),
    )


def verify_formal(
    facts: FormalFacts,
    *,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> FormalRun:
    """Check all applicable obligations under one context and fail every uncertainty closed."""
    plans = _plans(facts)
    term_count = sum(plan.term_count for plan in plans)
    if term_count > limits.max_smt_terms:
        message = f"formal check requires {term_count} SMT terms; limit is {limits.max_smt_terms}"
        raise VerificationError(message, check="resource.smt_terms")

    try:
        context = _new_context()
    except Exception:
        failed = tuple(_solver_failed(plan) for plan in plans)
        return FormalRun(
            results=tuple(result for result, _trace in failed),
            trace=tuple(trace for _result, trace in failed),
        )

    results: list[CheckResult] = []
    traces: list[FormalTrace] = []
    for plan in plans:
        try:
            outcome = plan.solve(context, limits.smt_timeout_ms)
        except Exception:
            result, trace = _solver_failed(plan)
        else:
            if outcome.result_class == "unsat":
                result = make_result(
                    plan.obligation,
                    status="pass",
                    message=plan.success_message,
                )
            elif outcome.result_class == "sat":
                result = make_result(
                    plan.obligation,
                    status="fail",
                    message=plan.counterexample_message(outcome.witness),
                )
            else:
                message = (
                    f"SMT solver returned unknown or timed out while checking {plan.obligation!r}"
                )
                result = make_result(_SOLVER_COMPLETED, status="fail", message=message)
            trace = FormalTrace(
                obligation=plan.obligation,
                term_count=plan.term_count,
                result_class=outcome.result_class,
            )
        results.append(result)
        traces.append(trace)
    return FormalRun(results=tuple(results), trace=tuple(traces))
