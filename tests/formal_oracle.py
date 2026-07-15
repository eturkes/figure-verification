# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Direct raw-value oracle for the finite SMT obligations (M5.2c).

This test-only module imports neither Z3 nor ``verifier.formal``. Generated cases stay at the
pre-fact boundary: exact Decimals/text/nulls, declared sort metadata, raw mark/channel flags, and
raw legend occurrences/domain entries. The oracle compares those values directly. A separate
adapter in ``test_formal_differential`` constructs production facts, so no rank builder, Z3
expression, witness helper, or obligation implementation is shared across the differential.
"""

from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise
from typing import Literal

type ValueKind = Literal["decimal", "temporal", "string"]
type SortDirection = Literal["ascending", "descending"]
type RawValue = Decimal | str
type NullableRawValue = RawValue | None
type ResultClass = Literal["unsat", "sat"]
type BarWitness = Literal["x", "y"]
type LegendSide = Literal["missing", "extra"]


@dataclass(frozen=True, slots=True)
class RawSortKey:
    kind: ValueKind
    direction: SortDirection


@dataclass(frozen=True, slots=True)
class RawOrderCase:
    keys: tuple[RawSortKey, ...]
    rows: tuple[tuple[NullableRawValue, ...], ...]

    def __post_init__(self) -> None:
        width = len(self.keys)
        if any(len(row) != width for row in self.rows):
            message = f"raw row width must equal {width} keys"
            raise ValueError(message)
        for row in self.rows:
            for value, key in zip(row, self.keys, strict=True):
                _validate_value(value, key.kind, nullable=True)


@dataclass(frozen=True, slots=True)
class RawBarCase:
    is_bar: bool
    x_quantitative: bool
    x_zero: bool
    y_quantitative: bool
    y_zero: bool


@dataclass(frozen=True, slots=True)
class RawLegendCase:
    kind: ValueKind
    plotted: tuple[NullableRawValue, ...]
    domain: tuple[RawValue, ...]

    def __post_init__(self) -> None:
        for value in self.plotted:
            _validate_value(value, self.kind, nullable=True)
        for value in self.domain:
            _validate_value(value, self.kind, nullable=False)


@dataclass(frozen=True, slots=True)
class RawFormalCase:
    order: RawOrderCase
    bar: RawBarCase
    legend: RawLegendCase


@dataclass(frozen=True, slots=True)
class OrderOutcome:
    result_class: ResultClass
    witness: int | None


@dataclass(frozen=True, slots=True)
class BarOutcome:
    result_class: ResultClass
    witness: BarWitness | None


@dataclass(frozen=True, slots=True)
class LegendOutcome:
    result_class: ResultClass
    witness_rank: int | None
    witness_label: str | None
    side: LegendSide | None


@dataclass(frozen=True, slots=True)
class OracleRun:
    order: OrderOutcome
    bar: BarOutcome
    legend: LegendOutcome


def _validate_value(value: NullableRawValue, kind: ValueKind, *, nullable: bool) -> None:
    if value is None:
        if nullable:
            return
        message = "raw domain values cannot be null"
        raise TypeError(message)
    valid = isinstance(value, Decimal) if kind == "decimal" else isinstance(value, str)
    if not valid:
        message = f"raw {kind} value has incompatible type {type(value).__name__}"
        raise TypeError(message)


def _nonnull_compare(left: RawValue, right: RawValue, kind: ValueKind) -> int:
    if kind == "decimal":
        if not isinstance(left, Decimal) or not isinstance(right, Decimal):
            message = "raw decimal comparison received text"
            raise TypeError(message)
        if left < right:
            return -1
        if left > right:
            return 1
        return 0
    if not isinstance(left, str) or not isinstance(right, str):
        message = f"raw {kind} comparison received a Decimal"
        raise TypeError(message)
    if left < right:
        return -1
    if left > right:
        return 1
    return 0


def _cell_compare(left: NullableRawValue, right: NullableRawValue, key: RawSortKey) -> int:
    """Return negative/equal/positive when left belongs before/equal/after right."""
    if left is None:
        if right is None:
            return 0
        return 1 if key.direction == "ascending" else -1
    if right is None:
        return -1 if key.direction == "ascending" else 1
    comparison = _nonnull_compare(left, right, key.kind)
    return comparison if key.direction == "ascending" else -comparison


def _row_is_after(
    left: tuple[NullableRawValue, ...],
    right: tuple[NullableRawValue, ...],
    keys: tuple[RawSortKey, ...],
) -> bool:
    for left_value, right_value, key in zip(left, right, keys, strict=True):
        comparison = _cell_compare(left_value, right_value, key)
        if comparison != 0:
            return comparison > 0
    return False


def check_order(case: RawOrderCase) -> OrderOutcome:
    for index, (left, right) in enumerate(pairwise(case.rows)):
        if _row_is_after(left, right, case.keys):
            return OrderOutcome(result_class="sat", witness=index)
    return OrderOutcome(result_class="unsat", witness=None)


def check_bar(case: RawBarCase) -> BarOutcome:
    if case.is_bar and case.x_quantitative and not case.x_zero:
        return BarOutcome(result_class="sat", witness="x")
    if case.is_bar and case.y_quantitative and not case.y_zero:
        return BarOutcome(result_class="sat", witness="y")
    return BarOutcome(result_class="unsat", witness=None)


def _ordered_values(values: set[RawValue], kind: ValueKind) -> list[RawValue]:
    if kind == "decimal":
        decimals = [value for value in values if isinstance(value, Decimal)]
        if len(decimals) != len(values):
            message = "raw decimal legend contains text"
            raise TypeError(message)
        return sorted(decimals)
    strings = [value for value in values if isinstance(value, str)]
    if len(strings) != len(values):
        message = f"raw {kind} legend contains a Decimal"
        raise TypeError(message)
    return sorted(strings)


def _label(value: RawValue) -> str:
    return format(value, "f") if isinstance(value, Decimal) else value


def check_legend(case: RawLegendCase) -> LegendOutcome:
    plotted = {value for value in case.plotted if value is not None}
    domain = set(case.domain)
    ordered = _ordered_values(plotted | domain, case.kind)
    mismatch = plotted ^ domain
    for rank, value in enumerate(ordered):
        if value in mismatch:
            side: LegendSide = "missing" if value in plotted else "extra"
            return LegendOutcome(
                result_class="sat",
                witness_rank=rank,
                witness_label=_label(value),
                side=side,
            )
    return LegendOutcome(
        result_class="unsat",
        witness_rank=None,
        witness_label=None,
        side=None,
    )


def check_case(case: RawFormalCase) -> OracleRun:
    return OracleRun(
        order=check_order(case.order),
        bar=check_bar(case.bar),
        legend=check_legend(case.legend),
    )
