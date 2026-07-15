# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Independent exhaustive/property differential for the finite SMT obligations (M5.2c)."""

import ast
import inspect
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from fractions import Fraction
from itertools import product
from typing import Any, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.strategies import DrawFn, SearchStrategy

import formal_oracle as direct_oracle
from formal_oracle import (
    BarOutcome,
    LegendOutcome,
    NullableRawValue,
    OracleRun,
    OrderOutcome,
    RawBarCase,
    RawFormalCase,
    RawLegendCase,
    RawOrderCase,
    RawSortKey,
    RawValue,
    SortDirection,
    ValueKind,
    check_bar,
    check_case,
    check_legend,
    check_order,
)
from verifier import formal
from verifier.checks import CheckResult
from verifier.formal import (
    BarZeroFacts,
    FormalFacts,
    FormalTrace,
    LegendCategory,
    LegendDomainFacts,
    RankedCell,
    RowOrderFacts,
)

_DIRECTIONS: tuple[SortDirection, ...] = ("ascending", "descending")
_KINDS: tuple[ValueKind, ...] = ("decimal", "temporal", "string")


def test_direct_oracle_imports_no_solver_or_production_module() -> None:
    tree = ast.parse(inspect.getsource(direct_oracle))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    )
    assert not {
        module for module in imported if module.split(".", maxsplit=1)[0] in {"z3", "verifier"}
    }


def _adapter_ordered_values(values: set[RawValue], kind: ValueKind) -> list[RawValue]:
    """Test fact-builder ordering, intentionally separate from formal_oracle's direct path."""
    if kind == "decimal":
        decimals = [value for value in values if isinstance(value, Decimal)]
        if len(decimals) != len(values):
            message = "decimal fact adapter received text"
            raise TypeError(message)
        return sorted(decimals)
    strings = [value for value in values if isinstance(value, str)]
    if len(strings) != len(values):
        message = f"{kind} fact adapter received a Decimal"
        raise TypeError(message)
    return sorted(strings)


def _adapter_label(value: RawValue) -> str:
    return format(value, "f") if isinstance(value, Decimal) else value


def _order_facts(case: RawOrderCase) -> RowOrderFacts:
    text_ranks: list[dict[str, int]] = []
    for index, key in enumerate(case.keys):
        if key.kind == "decimal":
            text_ranks.append({})
            continue
        values = sorted({value for row in case.rows if isinstance((value := row[index]), str)})
        text_ranks.append({value: rank for rank, value in enumerate(values)})

    ranked_rows: list[tuple[RankedCell, ...]] = []
    for row in case.rows:
        ranked_row: list[RankedCell] = []
        for index, (value, key) in enumerate(zip(row, case.keys, strict=True)):
            if value is None:
                ranked_row.append(RankedCell(is_null=True, rank=0))
            elif key.kind == "decimal":
                if not isinstance(value, Decimal):
                    message = "decimal fact adapter received text"
                    raise TypeError(message)
                ranked_row.append(RankedCell(is_null=False, rank=Fraction(value)))
            else:
                if not isinstance(value, str):
                    message = f"{key.kind} fact adapter received a Decimal"
                    raise TypeError(message)
                ranked_row.append(RankedCell(is_null=False, rank=text_ranks[index][value]))
        ranked_rows.append(tuple(ranked_row))
    return RowOrderFacts(
        rows=tuple(ranked_rows),
        directions=tuple(key.direction for key in case.keys),
    )


def _bar_facts(case: RawBarCase) -> BarZeroFacts:
    return BarZeroFacts(
        is_bar=case.is_bar,
        x_quantitative=case.x_quantitative,
        x_zero=case.x_zero,
        y_quantitative=case.y_quantitative,
        y_zero=case.y_zero,
    )


def _legend_facts(case: RawLegendCase) -> LegendDomainFacts:
    values = {value for value in case.plotted if value is not None} | set(case.domain)
    ordered = _adapter_ordered_values(values, case.kind)
    ranks = {value: rank for rank, value in enumerate(ordered)}

    def category(value: RawValue) -> LegendCategory:
        return LegendCategory(rank=ranks[value], label=_adapter_label(value))

    return LegendDomainFacts(
        plotted=tuple(category(value) for value in case.plotted if value is not None),
        domain=tuple(category(value) for value in case.domain),
    )


def _formal_facts(case: RawFormalCase) -> FormalFacts:
    return FormalFacts(
        row_order=_order_facts(case.order),
        bar_zero=_bar_facts(case.bar),
        legend_domain=_legend_facts(case.legend),
    )


def _assert_common(
    result: CheckResult,
    trace: FormalTrace,
    *,
    obligation: str,
    result_class: str,
) -> None:
    assert (result.check, result.method, trace.obligation, trace.result_class) == (
        obligation,
        "z3_smt",
        obligation,
        result_class,
    )


def _assert_order_outcome(result: CheckResult, trace: FormalTrace, expected: OrderOutcome) -> None:
    _assert_common(
        result,
        trace,
        obligation="sort.canonical_order",
        result_class=expected.result_class,
    )
    if expected.witness is None:
        assert (result.status, result.message) == (
            "pass",
            "canonical row order matches the active sort and canonical tail",
        )
    else:
        assert (result.status, result.message) == (
            "fail",
            f"canonical row order is violated between rows {expected.witness} "
            f"and {expected.witness + 1}",
        )


def _assert_bar_outcome(result: CheckResult, trace: FormalTrace, expected: BarOutcome) -> None:
    _assert_common(
        result,
        trace,
        obligation="scale.bar_zero",
        result_class=expected.result_class,
    )
    if expected.witness is None:
        assert (result.status, result.message) == (
            "pass",
            "every quantitative bar channel has scale.zero=true",
        )
    else:
        assert (result.status, result.message) == (
            "fail",
            f"quantitative bar channel {expected.witness!r} requires scale.zero=true",
        )


def _assert_legend_outcome(
    result: CheckResult, trace: FormalTrace, expected: LegendOutcome
) -> None:
    _assert_common(
        result,
        trace,
        obligation="encoding.legend_domain_exact",
        result_class=expected.result_class,
    )
    if expected.witness_rank is None:
        assert expected.witness_label is None
        assert expected.side is None
        assert (result.status, result.message) == (
            "pass",
            "discrete legend domain exactly matches plotted categories",
        )
        return
    assert expected.witness_label is not None
    if expected.side == "missing":
        message = (
            f"legend domain is missing plotted category {expected.witness_label!r} "
            f"(rank {expected.witness_rank})"
        )
    else:
        assert expected.side == "extra"
        message = (
            f"legend domain has extra category {expected.witness_label!r} "
            f"(rank {expected.witness_rank})"
        )
    assert (result.status, result.message) == ("fail", message)


def _assert_order_matches(case: RawOrderCase) -> None:
    run = formal.verify_formal(FormalFacts(row_order=_order_facts(case)))
    assert len(run.results) == len(run.trace) == 1
    _assert_order_outcome(run.results[0], run.trace[0], check_order(case))


def _assert_bar_matches(case: RawBarCase) -> None:
    run = formal.verify_formal(
        FormalFacts(row_order=RowOrderFacts(rows=(), directions=()), bar_zero=_bar_facts(case))
    )
    assert len(run.results) == len(run.trace) == 2
    _assert_bar_outcome(run.results[1], run.trace[1], check_bar(case))


def _assert_legend_matches(case: RawLegendCase) -> None:
    run = formal.verify_formal(
        FormalFacts(
            row_order=RowOrderFacts(rows=(), directions=()),
            legend_domain=_legend_facts(case),
        )
    )
    assert len(run.results) == len(run.trace) == 2
    _assert_legend_outcome(run.results[1], run.trace[1], check_legend(case))


def _assert_case_matches(case: RawFormalCase) -> None:
    expected: OracleRun = check_case(case)
    run = formal.verify_formal(_formal_facts(case))
    assert len(run.results) == len(run.trace) == 3
    _assert_order_outcome(run.results[0], run.trace[0], expected.order)
    _assert_bar_outcome(run.results[1], run.trace[1], expected.bar)
    _assert_legend_outcome(run.results[2], run.trace[2], expected.legend)


def _sequences[T](values: tuple[T, ...], max_length: int) -> Iterator[tuple[T, ...]]:
    for length in range(max_length + 1):
        yield from product(values, repeat=length)


def test_exhaustive_small_table_and_sort_microdomain_agrees() -> None:
    values: tuple[NullableRawValue, ...] = (None, Decimal(0), Decimal(1))
    checked = 0
    for width in range(3):
        for directions in product(_DIRECTIONS, repeat=width):
            keys = tuple(RawSortKey(kind="decimal", direction=value) for value in directions)
            for row_count in range(4):
                for flat in product(values, repeat=width * row_count):
                    rows: tuple[tuple[NullableRawValue, ...], ...]
                    if width == 0:
                        rows = tuple(() for _ in range(row_count))
                    else:
                        rows = tuple(
                            tuple(flat[offset : offset + width])
                            for offset in range(0, len(flat), width)
                        )
                    _assert_order_matches(RawOrderCase(keys=keys, rows=rows))
                    checked += 1
    assert checked == 3_364


def test_exhaustive_bar_and_channel_microdomain_agrees() -> None:
    checked = 0
    for flags in product((False, True), repeat=5):
        case = RawBarCase(
            is_bar=flags[0],
            x_quantitative=flags[1],
            x_zero=flags[2],
            y_quantitative=flags[3],
            y_zero=flags[4],
        )
        _assert_bar_matches(case)
        checked += 1
    assert checked == 32


def test_exhaustive_legend_domain_microdomain_agrees() -> None:
    plotted_values: tuple[NullableRawValue, ...] = (None, "a", "b")
    domain_values: tuple[RawValue, ...] = ("a", "b")
    checked = 0
    for plotted in _sequences(plotted_values, 2):
        for domain in _sequences(domain_values, 2):
            _assert_legend_matches(RawLegendCase(kind="string", plotted=plotted, domain=domain))
            checked += 1
    assert checked == 91


def _scaled_decimal(value: int) -> Decimal:
    return Decimal(value).scaleb(-3)


def _nonnull_values(kind: ValueKind) -> SearchStrategy[RawValue]:
    if kind == "decimal":
        return cast(
            SearchStrategy[RawValue],
            st.integers(min_value=-(10**18), max_value=10**18).map(_scaled_decimal),
        )
    if kind == "temporal":
        return cast(
            SearchStrategy[RawValue],
            st.dates(min_value=date(1900, 1, 1), max_value=date(2100, 12, 31)).map(date.isoformat),
        )
    return cast(
        SearchStrategy[RawValue],
        st.text(alphabet=("a", "b", "z", "é", "東"), max_size=4),
    )


def _nullable_values(kind: ValueKind) -> SearchStrategy[NullableRawValue]:
    return cast(
        SearchStrategy[NullableRawValue],
        st.one_of(st.none(), _nonnull_values(kind)),
    )


@st.composite
def _order_cases(draw: DrawFn) -> RawOrderCase:
    width = draw(st.integers(min_value=0, max_value=4))
    kinds = draw(st.lists(st.sampled_from(_KINDS), min_size=width, max_size=width))
    directions = draw(st.lists(st.sampled_from(_DIRECTIONS), min_size=width, max_size=width))
    keys = tuple(
        RawSortKey(kind=kind, direction=direction)
        for kind, direction in zip(kinds, directions, strict=True)
    )
    row_count = draw(st.integers(min_value=0, max_value=7))
    rows = tuple(tuple(draw(_nullable_values(key.kind)) for key in keys) for _ in range(row_count))
    return RawOrderCase(keys=keys, rows=rows)


@st.composite
def _bar_cases(draw: DrawFn) -> RawBarCase:
    return RawBarCase(
        is_bar=draw(st.booleans()),
        x_quantitative=draw(st.booleans()),
        x_zero=draw(st.booleans()),
        y_quantitative=draw(st.booleans()),
        y_zero=draw(st.booleans()),
    )


@st.composite
def _legend_cases(draw: DrawFn) -> RawLegendCase:
    kind = draw(st.sampled_from(_KINDS))
    plotted = tuple(draw(st.lists(_nullable_values(kind), max_size=8)))
    domain = tuple(draw(st.lists(_nonnull_values(kind), max_size=6)))
    return RawLegendCase(kind=kind, plotted=plotted, domain=domain)


@st.composite
def _formal_cases(draw: DrawFn) -> RawFormalCase:
    return RawFormalCase(
        order=draw(_order_cases()),
        bar=draw(_bar_cases()),
        legend=draw(_legend_cases()),
    )


@settings(max_examples=250)
@given(case=_formal_cases())
def test_larger_bounded_cross_product_agrees(case: RawFormalCase) -> None:
    _assert_case_matches(case)


def test_persisted_exact_decimal_and_ranked_text_order_witnesses() -> None:
    exact_decimal = RawOrderCase(
        keys=(RawSortKey(kind="decimal", direction="ascending"),),
        rows=((Decimal("9007199254740992.1"),), (Decimal("9007199254740992.0"),)),
    )
    temporal_then_string = RawOrderCase(
        keys=(
            RawSortKey(kind="temporal", direction="ascending"),
            RawSortKey(kind="string", direction="descending"),
        ),
        rows=(
            ("2026-01-01", "z"),
            ("2026-01-01", "a"),
            ("2025-12-31", "m"),
        ),
    )
    null_mixed_directions = RawOrderCase(
        keys=(
            RawSortKey(kind="decimal", direction="ascending"),
            RawSortKey(kind="string", direction="descending"),
        ),
        rows=(
            (Decimal(-1), None),
            (Decimal(-1), "z"),
            (Decimal(-1), "a"),
            (None, None),
        ),
    )
    cases = (
        (exact_decimal, OrderOutcome(result_class="sat", witness=0)),
        (temporal_then_string, OrderOutcome(result_class="sat", witness=1)),
        (null_mixed_directions, OrderOutcome(result_class="unsat", witness=None)),
    )
    for case, expected in cases:
        assert check_order(case) == expected
        _assert_order_matches(case)


def test_persisted_bar_and_legend_edge_witnesses() -> None:
    both_bad = RawBarCase(
        is_bar=True,
        x_quantitative=True,
        x_zero=False,
        y_quantitative=True,
        y_zero=False,
    )
    assert check_bar(both_bad) == BarOutcome(result_class="sat", witness="x")
    _assert_bar_matches(both_bad)

    pass_outcome = LegendOutcome(
        result_class="unsat",
        witness_rank=None,
        witness_label=None,
        side=None,
    )
    legend_cases = (
        (
            RawLegendCase(
                kind="string",
                plotted=("EU", "EU", "NA"),
                domain=("NA", "EU", "NA"),
            ),
            pass_outcome,
        ),
        (RawLegendCase(kind="string", plotted=(), domain=()), pass_outcome),
        (RawLegendCase(kind="string", plotted=(None, None), domain=()), pass_outcome),
        (
            RawLegendCase(
                kind="decimal",
                plotted=(Decimal("0.10"), Decimal("2.00"), Decimal("0.10")),
                domain=(Decimal("2.00"), Decimal("0.10")),
            ),
            pass_outcome,
        ),
        (
            RawLegendCase(kind="string", plotted=("b", "b"), domain=("a", "c")),
            LegendOutcome(
                result_class="sat",
                witness_rank=0,
                witness_label="a",
                side="extra",
            ),
        ),
    )
    for case, expected in legend_cases:
        assert check_legend(case) == expected
        _assert_legend_matches(case)


def test_differential_detects_deleted_order_constraint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = RawOrderCase(
        keys=(RawSortKey(kind="decimal", direction="ascending"),),
        rows=((Decimal(1),), (Decimal(0),)),
    )

    def deleted_inversion(
        _left: object,
        _right: object,
        _directions: object,
        context: Any,
    ) -> Any:
        return formal._or([], context)

    monkeypatch.setattr(formal, "_row_inversion", deleted_inversion)
    with pytest.raises(AssertionError):
        _assert_order_matches(case)


def test_differential_detects_deleted_bar_constraint(monkeypatch: pytest.MonkeyPatch) -> None:
    case = RawBarCase(
        is_bar=True,
        x_quantitative=True,
        x_zero=False,
        y_quantitative=False,
        y_zero=True,
    )

    def deleted_channels(_facts: BarZeroFacts) -> list[tuple[str, bool]]:
        return []

    monkeypatch.setattr(formal, "_bar_channels", deleted_channels)
    with pytest.raises(AssertionError):
        _assert_bar_matches(case)


def test_differential_detects_deleted_legend_constraint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = RawLegendCase(kind="string", plotted=("missing",), domain=())

    def deleted_candidates(_facts: LegendDomainFacts) -> list[int]:
        return []

    monkeypatch.setattr(formal, "_legend_ranks", deleted_candidates)
    with pytest.raises(AssertionError):
        _assert_legend_matches(case)
