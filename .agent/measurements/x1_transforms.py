# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""X1: chance matches of the admitted computations (Q45, `.agent/archive/contracts/q45.md` C5).

Measures the SHIPPED candidates + matcher (`verifier.figure.explain`, `verifier.figure.computed`):
a made-up series counts as ADDED for a computation when one of that computation's candidates
explains every point while no vocabulary candidate does (the judge's first pass); each computation
on its own value scale, so the sum over computations bounds their union. Per `data/*.csv` with
numeric columns: keyed bar series of n distinct keys from one non-numeric column holding at least
n keys (`null` where none does: these CSVs hold 2-4), values on a grid, matched by `_coverage`
(exact, injective). Request leg: values alone keyed by
position (`plt.plot(values)`), over `1 to m` (m = 3, 5, 10) and m random integers in [1, 100]; a
typed computation explains a series when every value is in its set (membership, as `_typed`
matches) while the typed numbers themselves do not. Grids: `int` = integers in [0, 2M], `dec2` =
two-decimal numbers in [0, 2M], M = the largest |value| the computation yields there. TRIALS per
size per grid. Host only: `uv run --locked python .agent/measurements/x1_transforms.py`.
"""

import json
import random
from collections import defaultdict
from pathlib import Path

from verifier.figure import computed, explain
from verifier.figure.keys import Key
from verifier.figure.parts import Mark
from verifier.figure.request import read_request
from verifier.figure.series import Point, Series
from verifier.figure.sources import Table, read_table
from verifier.pysrc.budget import WorkBudget

ROOT = Path(__file__).resolve().parent
TRIALS = 10_000
SIZES = range(1, 11)
GRIDS = ("int", "dec2")
_MARK = Mark("bar", (0,))


def made_up(rng, grid, top, size):
    if grid == "int":
        return [float(rng.randint(0, int(2 * top))) for _ in range(size)]
    return [round(rng.uniform(0, 2 * top), 2) for _ in range(size)]


def covers(series, explanation, values):
    if any(point.value not in values for point in series.points):
        return False  # a necessary condition `_coverage` would also fail
    return all(explain._coverage(series, explanation))


def measure(table, rng):
    budget = WorkBudget(10**12)
    vocabulary = [(e, {v for _k, v in e.pairs}) for e in explain.explanations(table, None, budget)]
    found = [(e, {v for _k, v in e.pairs}) for e in explain.computations(table, None, budget)]
    numeric = {column.name for column in table.columns if column.numbers is not None}
    keys = [column for column in table.columns if column.name not in numeric]
    pools = {column.name: sorted(set(column.texts)) for column in keys}
    by_transform = defaultdict(list)
    for each in found:
        by_transform[each[0].transform].append(each)
    added = {}
    for name in computed.ORDER:
        cands = by_transform[name]
        top = max((abs(v) for _e, values in cands for v in values), default=0.0) or 1.0
        added[name] = {}
        for grid in GRIDS:
            added[name][grid] = {}
            for size in SIZES:
                eligible = [column for column in keys if len(pools[column.name]) >= size]
                if not eligible:
                    added[name][grid][str(size)] = None
                    continue
                hits = 0
                for _ in range(TRIALS):
                    column = rng.choice(eligible)
                    picked = rng.sample(pools[column.name], size)
                    drawn = made_up(rng, grid, top, size)
                    points = tuple(
                        Point(Key(text=k), v) for k, v in zip(picked, drawn, strict=True)
                    )
                    series = Series(0, _MARK, "keyed", None, points, None)
                    hits += any(covers(series, e, values) for e, values in cands) and not any(
                        covers(series, e, values) for e, values in vocabulary
                    )
                added[name][grid][str(size)] = hits
    return {
        "rows": table.rows,
        "numeric_columns": len(numeric),
        "candidates": len(found),
        "added": added,
    }


def request_leg(rng):
    lists = {f"1 to {m}": f"1 to {m}" for m in (3, 5, 10)}
    for m in (3, 5, 10):
        lists[f"{m} random"] = ", ".join(str(x) for x in rng.sample(range(1, 101), m))
    result = {}
    for label, text in lists.items():
        request = read_request(text)
        sets = defaultdict(frozenset)  # every variant of a computation, as `_typed` tries them all
        for transform, values in computed.typed(request.sequence):
            sets[transform] |= values
        result[label] = {}
        for name in computed.UNARY:
            members = sets.get(name, frozenset())
            top = max((abs(v) for v in members), default=0.0) or 1.0
            result[label][name] = {}
            for grid in GRIDS:
                result[label][name][grid] = {}
                for size in SIZES:
                    hits = 0
                    for _ in range(TRIALS):
                        drawn = made_up(rng, grid, top, size)
                        typed = all(v in request.numbers for v in drawn)
                        hits += not typed and all(v in members for v in drawn)
                    result[label][name][grid][str(size)] = hits
    return result


if __name__ == "__main__":
    rng = random.Random(45)  # noqa: S311 - a seeded sample, not a secret
    data = ROOT.parents[1] / "data"
    tables = {}
    for path in sorted(data.glob("*.csv")):
        table = read_table(path.name, path.read_bytes())
        if isinstance(table, Table) and any(c.numbers is not None for c in table.columns):
            tables[path.name] = measure(table, rng)
        else:
            tables[path.name] = {"numeric_columns": 0}
    result = {"trials": TRIALS, "csv": tables, "request": request_leg(rng)}
    (ROOT / "x1-result.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(json.dumps(result, ensure_ascii=False))
