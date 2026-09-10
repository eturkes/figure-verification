# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""W5: the measured work rate that sets `max_work`'s default on the host of record.

`max_work` is the binding recomputation ceiling. The other caps multiply out to far more
evaluation than a demo may spend -- `max_expr_nodes` times `max_grid_samples` alone is 100,000,000
work -- so `max_work` is the number that refuses a program which is admissible but not affordable.
Choosing it by feel picks a wall-clock bound by accident. This measures the rate, and the default
follows from a stated time ceiling.

A work unit is only a wall-clock bound if its cost is roughly constant, so this also MEASURES that
premise instead of assuming it. The formula arm charges per expression node and holds: the two
formula workloads share a node count and differ only in operator class, and their rates sit within
about ten percent, because per-node interpreter overhead dominates the libm call. The dataset arm
charged per CELL and did NOT hold -- cell WIDTH is free to a per-cell meter and not to the clock --
so the sweep below reports each width under both the per-cell tariff and the size-aware one that
replaced it (`.agent/archive/contracts/m13u5.md` § The W2 tariff is size-aware). A flat
`work/s` column is the property being demonstrated; the per-cell column is retained because
a tariff regression shows
up as that column fanning out again.

The work each workload consumes is READ BACK from the production meter instead of being recomputed
here: a benchmark that re-modelled the tariff would report a wrong rate exactly when the tariff
changed, which is the moment the number matters.

Run: `uv run --locked python tools/bench_pysrc_work.py`.
"""

import csv
import io
import platform
import statistics
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from verifier.pysrc.admit import parse_admitted
from verifier.pysrc.budget import WorkBudget
from verifier.pysrc.csvread import read_columns
from verifier.pysrc.limits import DEFAULT_LIMITS
from verifier.pysrc.numeric import evaluate_expr, materialize_grid
from verifier.pysrc.prescan import prescan
from verifier.pysrc.project import project
from verifier.pysrc.spec import CorePlotSpec, DatasetPlot, FormulaPlot

_REPEATS = 7
# The verifier runs inline ahead of the sandbox render, so its recomputation must stay small
# against the model's own generation latency. One second on the host of record is the ceiling
# `max_work` is derived from: it bounds what an adversarial-but-admissible program can spend, and
# it is a denial-of-service bound rather than a performance target.
_CEILING_SECONDS = 1.0
# Large enough that each timed region is tens of milliseconds -- far above `perf_counter`
# resolution -- and small enough that the whole run is a few seconds.
_SAMPLES = 20_000

# Bytes of cell text per extra work unit, the size-aware tariff's divisor. Measured, not chosen:
# the host fit is about 1.28 us per cell plus 0.051 us per byte, so a byte costs roughly a
# twenty-fifth of a cell and a divisor of 32 flattens `work/s` across the whole width range.
_BYTES_PER_UNIT = 32

# Categorical x widths, up to `max_csv_cell_bytes`. Below 8 the unique-label prefix does not fit.
# 31 and 63 are the load-bearing entries: a floor-division surcharge is worst just BELOW a
# threshold, where the cell pays full time for zero extra charge, so a sweep of round widths alone
# reports a floor the verifier cannot hold.
_WIDTHS = (8, 16, 31, 32, 63, 64, 128, 256, 512)
# Rows per width, sized to hold each corpus near this many bytes so every timed region is
# comparable, then clamped under `max_csv_rows` and above a floor that keeps the median stable.
_CORPUS_BYTES = 2_000_000
_MAX_ROWS = 20_000
_MIN_ROWS = 2_000

_FORMULA_LIBM = (
    "import numpy as np\n"
    "import matplotlib.pyplot as plt\n"
    f"x = np.linspace(0, 10, {_SAMPLES})\n"
    "y = np.sin(x) * np.exp(x / 100) + np.sqrt(np.abs(x))\n"
    "plt.plot(x, y)\n"
    "plt.show()\n"
)

# Deliberately the same node count as the libm workload, so the pair isolates operator CLASS from
# tree size: the two rates differ by the cost of `sin`/`exp`/`sqrt` and by nothing else.
_FORMULA_EXACT = (
    "import numpy as np\n"
    "import matplotlib.pyplot as plt\n"
    f"x = np.linspace(0, 10, {_SAMPLES})\n"
    "y = ((x * 2 + 3) * (x - 1)) / 4\n"
    "plt.plot(x, y)\n"
    "plt.show()\n"
)

# A categorical x is where cell width is reachable: the numeric profile caps a number near 17
# characters, while a category runs to `max_csv_cell_bytes`.
_DATASET_BAR = (
    "import pandas as pd\n"
    "import matplotlib.pyplot as plt\n"
    'df = pd.read_csv("data.csv")\n'
    'plt.bar(df["x"], df["y"])\n'
    "plt.show()\n"
)


@dataclass(frozen=True, slots=True)
class _Workload:
    """One timed recomputation, with the corpus whose size-aware charge the sweep reports."""

    name: str
    run: Callable[[WorkBudget], None]
    content: bytes | None = None


@dataclass(frozen=True, slots=True)
class _Measured:
    """A workload's median over `_REPEATS` passes, under both tariffs."""

    name: str
    work: int
    sized_work: int
    seconds: float

    @property
    def rate(self) -> float:
        return self.work / self.seconds

    @property
    def sized_rate(self) -> float:
        return self.sized_work / self.seconds


def _projected(source: str) -> CorePlotSpec:
    """Project through the real pipeline, so the timed trees are the ones production evaluates."""
    return project(parse_admitted(prescan(source.encode(), DEFAULT_LIMITS)), DEFAULT_LIMITS)


def _size_surcharge(content: bytes) -> int:
    """The size-aware tariff's extra charge over the whole file, one unit per `_BYTES_PER_UNIT`
    bytes of each cell's text. Walks every cell because the reader charges for every cell read."""
    reader = csv.reader(io.StringIO(content.decode()), strict=True)
    return sum(len(cell) // _BYTES_PER_UNIT for row in reader for cell in row)


def _rows_for(width: int) -> int:
    return min(_MAX_ROWS, max(_MIN_ROWS, _CORPUS_BYTES // (width + 10)))


def _categorical_csv(width: int, rows: int) -> bytes:
    """A categorical x at exactly `width` bytes, unique per row so G8 admits it."""
    body = "".join(f"c{index:05d}".ljust(width, "x") + f",{index}.5\n" for index in range(rows))
    return f"x,y\n{body}".encode()


def _formula_workload(name: str, source: str) -> _Workload:
    spec = _projected(source)
    if not isinstance(spec, FormulaPlot):
        message = f"{name}: expected the formula arm, projected {type(spec).__name__}"
        raise TypeError(message)

    def run(budget: WorkBudget) -> None:
        for x in materialize_grid(spec.grid, budget):
            evaluate_expr(spec.y, x, budget)

    return _Workload(name=name, run=run)


def _dataset_workload(name: str, source: str, content: bytes) -> _Workload:
    spec = _projected(source)
    if not isinstance(spec, DatasetPlot):
        message = f"{name}: expected the dataset arm, projected {type(spec).__name__}"
        raise TypeError(message)

    def run(budget: WorkBudget) -> None:
        read_columns(content, spec, DEFAULT_LIMITS, budget)

    return _Workload(name=name, run=run, content=content)


def _measure(workload: _Workload) -> _Measured:
    """One warm pass, then `_REPEATS` timed ones; the median resists a scheduler hiccup.

    The meter runs unbounded: this run measures the rate, and a refusal mid-workload would time a
    partial pass. The production caps are what `max_work` then bounds.
    """
    warm = WorkBudget(limit=1 << 40)
    workload.run(warm)

    seconds: list[float] = []
    for _ in range(_REPEATS):
        budget = WorkBudget(limit=1 << 40)
        start = time.perf_counter()
        workload.run(budget)
        seconds.append(time.perf_counter() - start)

    surcharge = 0 if workload.content is None else _size_surcharge(workload.content)
    return _Measured(
        name=workload.name,
        work=warm.consumed,
        sized_work=warm.consumed + surcharge,
        seconds=statistics.median(seconds),
    )


def _round_down(value: int) -> int:
    """Two significant figures, rounded DOWN: a policy constant reads as a decision, and rounding
    down keeps the derived bound on the conservative side of the measurement."""
    minimum = 100
    if value < minimum:
        return value
    # `int ** int` widens to Any because a negative exponent yields a float; the early return
    # above makes the exponent at least 1, so the annotation is a narrowing, not an assertion.
    scale: int = 10 ** (len(str(value)) - 2)
    return value // scale * scale


def _report(
    formula: list[_Measured], sweep: list[_Measured], widths: tuple[int, ...]
) -> Iterator[str]:
    yield f"host      {platform.machine()} · CPython {platform.python_version()}\n"
    yield f"repeats   {_REPEATS} timed passes per workload, median reported\n"
    yield f"tariff    size-aware surcharge = 1 per {_BYTES_PER_UNIT} bytes of cell text\n\n"

    yield f"{'formula arm':<18}{'work':>12}{'median s':>12}{'work/s':>14}\n"
    for entry in formula:
        yield f"{entry.name:<18}{entry.work:>12,}{entry.seconds:>12.4f}{entry.rate:>14,.0f}\n"

    yield f"\n{'dataset sweep':<18}{'work':>12}{'median s':>12}{'per-cell/s':>14}{'sized/s':>14}\n"
    for width, entry in zip(widths, sweep, strict=True):
        yield (
            f"width {width:<12}{entry.work:>12,}{entry.seconds:>12.4f}"
            f"{entry.rate:>14,.0f}{entry.sized_rate:>14,.0f}\n"
        )

    per_cell = [entry.rate for entry in sweep]
    sized = [entry.sized_rate for entry in sweep]
    yield (
        f"\nspread    per-cell {max(per_cell) / min(per_cell):.1f}x"
        f" · size-aware {max(sized) / min(sized):.1f}x\n"
    )

    binding = min([*(entry.sized_rate for entry in formula), *sized])
    recommended = _round_down(int(binding * _CEILING_SECONDS))
    current = DEFAULT_LIMITS.max_work
    yield f"binding   {binding:,.0f} work/s over both arms\n"
    yield f"ceiling   {_CEILING_SECONDS} s of recomputation\n"
    yield f"max_work  {recommended:,} recommended · {current:,} currently shipped\n"

    # What the recommendation admits, which is the number showing the default is a denial-of-service
    # bound rather than an accidental restriction on real charts.
    nodes = formula[0].work // _SAMPLES
    yield (
        f"\nat {recommended:,}: the measured {nodes}-node expression admits "
        f"{recommended // nodes:,} samples against a {DEFAULT_LIMITS.max_grid_samples:,} cap; "
        f"a two-column numeric CSV admits {recommended // 4:,} rows against a "
        f"{DEFAULT_LIMITS.max_csv_rows:,} cap.\n"
    )


def main() -> int:
    formula = [
        _measure(_formula_workload("formula-libm", _FORMULA_LIBM)),
        _measure(_formula_workload("formula-exact", _FORMULA_EXACT)),
    ]
    sweep = [
        _measure(
            _dataset_workload(
                f"width-{width}", _DATASET_BAR, _categorical_csv(width, _rows_for(width))
            )
        )
        for width in _WIDTHS
    ]
    sys.stdout.writelines(_report(formula, sweep, _WIDTHS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
