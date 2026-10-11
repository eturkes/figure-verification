# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The admitted computations of the user's data (Q45, `.agent/archive/contracts/q45.md`; stdlib).

Closed list: of one series — `square`, `cumsum`, `diff`, `share`, `percent`; of two numeric
columns — `ratio`, `difference`, `product`, `total`. Each is evaluated the ways an honest program
evaluates it, one whole-series VARIANT at a time, and matched exactly like every other
explanation: the judge cannot run the sandbox's numpy, so it reproduces the bits of the spellings
it admits. A total is numpy's pairwise sum (`Series.sum`, `np.sum`), a sequential sum (`sum` over
numpy scalars, a loop), CPython's Neumaier `sum` over floats, pandas' Kahan group sum, or
`math.fsum`; a percent is `(100*v)/t`, `(v/t)*100` or `v*(100/t)`. A value that is not finite, or
the share of a zero total, is no candidate (None).
"""

import itertools
import math
from collections.abc import Callable, Iterator, Sequence
from typing import Final, Literal

from verifier.pysrc.aggregate import kahan_sum

type Transform = Literal[
    "square", "cumsum", "diff", "share", "percent", "ratio", "difference", "product", "total"
]
type Values = tuple[float | None, ...]

# Canonical order: the published reading when several computations explain the same columns.
ORDER: Final[tuple[Transform, ...]] = (
    "square",
    "cumsum",
    "diff",
    "share",
    "percent",
    "ratio",
    "difference",
    "product",
    "total",
)
UNARY: Final[tuple[Transform, ...]] = ORDER[:5]
BINARY: Final[tuple[Transform, ...]] = ORDER[5:]
# numpy's pairwise summation: blocks below 8 sum left to right, up to 128 through 8 accumulators;
# a reduction reaches it one 8192-value buffer at a time, the buffers summed left to right.
_UNROLL: Final = 8
_BLOCK: Final = 128
_BUFFER: Final = 8192


def pairwise_sum(values: Sequence[float]) -> float:
    """`np.add.reduce` over float64 (`Series.sum`, `np.sum`), bit for bit."""
    total = 0.0
    for start in range(0, len(values), _BUFFER):
        total += _pairwise(values[start : start + _BUFFER])
    return total


def _pairwise(values: Sequence[float]) -> float:
    """numpy's `pairwise_sum` over one buffer."""
    count = len(values)
    if count < _UNROLL:
        total = 0.0
        for value in values:
            total += value
        return total
    if count <= _BLOCK:
        lanes = list(values[:_UNROLL])
        end = count - count % _UNROLL
        for start in range(_UNROLL, end, _UNROLL):
            for lane in range(_UNROLL):
                lanes[lane] += values[start + lane]
        total = ((lanes[0] + lanes[1]) + (lanes[2] + lanes[3])) + (
            (lanes[4] + lanes[5]) + (lanes[6] + lanes[7])
        )
        for value in values[end:]:
            total += value
        return total
    half = count // 2
    half -= half % _UNROLL
    return _pairwise(values[:half]) + _pairwise(values[half:])


def sequential_sum(values: Sequence[float]) -> float:
    total = 0.0
    for value in values:
        total += value
    return total


def neumaier_sum(values: Sequence[float]) -> float:
    """CPython's `sum` over floats (3.12 onward): Neumaier compensation, added at the end."""
    total = compensation = 0.0
    for value in values:
        running = total + value
        if abs(total) >= abs(value):
            compensation += (total - running) + value
        else:
            compensation += (value - running) + total
        total = running
    if compensation and math.isfinite(compensation):
        total += compensation
    return total


def exact_sum(values: Sequence[float]) -> float:
    """`math.fsum`; its overflow or an infinite input (a typed `1e999`) is no total."""
    try:
        return math.fsum(values)
    except (OverflowError, ValueError):
        return math.inf


_TOTALS: Final[tuple[Callable[[Sequence[float]], float], ...]] = (
    pairwise_sum,
    sequential_sum,
    neumaier_sum,
    kahan_sum,
    exact_sum,
)
_PERCENTS: Final[tuple[Callable[[float, float], float], ...]] = (
    lambda value, total: (100.0 * value) / total,
    lambda value, total: (value / total) * 100.0,
    lambda value, total: value * (100.0 / total),
)


def _finite(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _distinct(found: Iterator[tuple[Transform, Values]]) -> Iterator[tuple[Transform, Values]]:
    """Each transform's variants once: an integer series' totals all agree."""
    seen: set[tuple[Transform, Values]] = set()
    for each in found:
        if each not in seen:
            seen.add(each)
            yield each


def _unary(values: Sequence[float]) -> Iterator[tuple[Transform, Values]]:
    yield "square", tuple(_finite(value * value) for value in values)
    yield "cumsum", tuple(_finite(total) for total in itertools.accumulate(values))
    yield "diff", (None, *(_finite(right - left) for left, right in itertools.pairwise(values)))
    # Equal totals give equal shares: an integer series' five totals are one.
    totals = list(dict.fromkeys(total(values) for total in _TOTALS))
    for total in totals:
        if total and math.isfinite(total):
            yield "share", tuple(_finite(value / total) for value in values)
    for percent in _PERCENTS:
        for total in totals:
            if total and math.isfinite(total):
                yield "percent", tuple(_finite(percent(value, total)) for value in values)


def unary(values: Sequence[float]) -> Iterator[tuple[Transform, Values]]:
    """Every one-series computation of `values` (in their drawn order), one variant per yield; a
    pair with no defined value is None (`diff`'s first, a non-finite result)."""
    return _distinct(_unary(values))


def _apply(op: Transform, left: float, right: float) -> float | None:
    if op == "ratio":
        return _finite(left / right) if right else None
    if op == "difference":
        return _finite(left - right)
    if op == "product":
        return _finite(left * right)
    return _finite(left + right)


def binary(op: Transform, left: Sequence[float], right: Sequence[float]) -> Values:
    """One two-column computation, element by element."""
    return tuple(_apply(op, a, b) for a, b in zip(left, right, strict=True))


def typed(sequence: Sequence[float]) -> Iterator[tuple[Transform, frozenset[float]]]:
    """Each computation of the request's numbers, as the set of values it yields (R4 membership)."""
    for transform, values in unary(sequence):
        yield transform, frozenset(value for value in values if value is not None)
