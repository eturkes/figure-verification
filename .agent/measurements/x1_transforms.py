# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""X1: chance matches of candidate computed-value transforms (queue row `Computed values`, Q45).

The value vocabulary today (I2's, `.claude/rules/figure.md` § Values): raw(K,V), index(V),
group(K,V,r) r in sum mean min max, count(K), plus the request's numbers. Each candidate transform
widens it. Per transform, over each `data/*.csv` with numeric columns and over made-up requests:
- `outputs`: the transform's series; `ties`: of those, how many equal a vocabulary series over
  other columns (a tie the request must break);
- `added`: made-up keyed series (I2's shape: n distinct keys from one real key column holding at
  least n keys; `null` where no column holds n) of n = 1..10 points, TRIALS each per value grid,
  that the transform explains while the vocabulary does not, both matched injectively. Grids:
  `int` = integers in [0, 2M], `dec2` = two-decimal numbers in [0, 2M], M = the largest |value|
  the transform yields on that CSV (a made-up value in the transform's own range).
Request leg: numbers `1 to m` (m = 3, 5, 10) and m random distinct integers in [1, 100]; series are
values alone (pairing is not inferred, R4); a hit = every value in transform(numbers) and not every
value in the numbers, each by membership as the verifier matches typed numbers. Host only:
`uv run --locked python .agent/measurements/x1_transforms.py`.
"""

import csv
import itertools
import json
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REDUCTIONS = ("sum", "mean", "min", "max")
TRIALS = 10_000
SIZES = range(1, 11)
GRIDS = ("int", "dec2")
SERIES = ("square", "cumsum", "share", "percent", "diff")  # of one vocabulary series
PAIRS = ("ratio", "difference", "product", "total")  # of two numeric columns, per row or group
REQUEST = ("square", "cumsum", "share", "percent", "diff")


def number(text):
    try:
        return float(text)
    except ValueError:
        return None


def reduce(values, how):
    if how == "sum":
        return float(sum(values))
    if how == "mean":
        return float(sum(values)) / len(values)
    return float(min(values) if how == "min" else max(values))


def combine(a, b, how):
    if how == "ratio":
        return a / b if b else None
    if how == "difference":
        return a - b
    return a * b if how == "product" else a + b


def of_series(points, how):
    """`points` in pandas' order; None when the transform is undefined there."""
    values = [value for _key, value in points]
    total = sum(values)
    if how == "square":
        return [(key, value * value) for key, value in points]
    if how == "cumsum":
        return list(zip([key for key, _ in points], itertools.accumulate(values), strict=True))
    if how in ("share", "percent"):
        if not total:
            return None
        scale = 100.0 if how == "percent" else 1.0
        return [(key, scale * value / total) for key, value in points]
    return [(points[i][0], values[i] - values[i - 1]) for i in range(1, len(points))]


def vocabulary(header, rows, numeric):
    """Base explanations: (family, columns) -> points in pandas' order."""
    found = {}
    for v in numeric:
        found[("index", (v,))] = [(float(i), number(r[v])) for i, r in enumerate(rows)]
        for k in header:
            if k == v:
                continue
            found[("raw", (k, v))] = [(r[k], number(r[v])) for r in rows]
            groups = {}
            for r in rows:
                groups.setdefault(r[k], []).append(number(r[v]))
            for how in REDUCTIONS:
                found[(how, (k, v))] = [(key, reduce(groups[key], how)) for key in sorted(groups)]
    for k in header:
        counted = Counter(r[k] for r in rows)
        found[("count", (k,))] = [(key, float(counted[key])) for key in sorted(counted)]
    return found


def transforms(header, rows, numeric, base):
    """Candidate explanations per transform name: (name, columns) -> points."""
    out = {name: {} for name in (*SERIES, *PAIRS)}
    for (family, columns), points in base.items():
        for how in SERIES:
            made = of_series(points, how)
            if made:
                out[how][(f"{how}({family})", columns)] = made
    for a, b in itertools.permutations(numeric, 2):
        for how in PAIRS:
            for k in header:
                if k in (a, b):
                    continue
                row = [(r[k], combine(number(r[a]), number(r[b]), how)) for r in rows]
                if all(value is not None for _key, value in row):
                    out[how][(f"{how}(raw)", (k, a, b))] = row
                groups = {}
                for r in rows:
                    groups.setdefault(r[k], []).append((number(r[a]), number(r[b])))
                grouped = [
                    (key, combine(sum(x for x, _ in pairs), sum(y for _, y in pairs), how))
                    for key, pairs in sorted(groups.items())
                ]
                if all(value is not None for _key, value in grouped):
                    out[how][(f"{how}(sum)", (k, a, b))] = grouped
    return out


class Points:
    """One explanation's points as a multiset, with its value set as a cheap first filter."""

    def __init__(self, points):
        self.counter = Counter(points)
        self.values = {value for _key, value in points}

    def explains(self, drawn, counted):
        return all(value in self.values for _key, value in drawn) and not (counted - self.counter)


def made_up(rng, grid, top, size):
    if grid == "int":
        return [float(rng.randint(0, int(2 * top))) for _ in range(size)]
    return [round(rng.uniform(0, 2 * top), 2) for _ in range(size)]


def measure(path, rng):
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header, rows = list(reader.fieldnames or ()), list(reader)
    numeric = [c for c in header if rows and all(number(r[c]) is not None for r in rows)]
    if not numeric:
        return {"rows": len(rows), "numeric_columns": 0}
    base = vocabulary(header, rows, numeric)
    known = [Points(points) for points in base.values()]
    keys = [c for c in header if c not in numeric] or header
    pools = {c: sorted({r[c] for r in rows}) for c in keys}
    result = {"rows": len(rows), "numeric_columns": len(numeric), "transforms": {}}
    for name, found in transforms(header, rows, numeric, base).items():
        candidates = [Points(points) for points in found.values()]
        ties = sum(
            1
            for (_label, columns), points in found.items()
            if any(
                Counter(points) == Counter(other) and set(cols) != set(columns)
                for (_family, cols), other in base.items()
            )
        )
        top = max((abs(v) for points in found.values() for _k, v in points), default=0.0) or 1.0
        added = {}
        for grid in GRIDS:
            added[grid] = {}
            for size in SIZES:
                eligible = [column for column in keys if len(pools[column]) >= size]
                if not eligible:  # no key column holds `size` distinct keys
                    added[grid][str(size)] = None
                    continue
                hits = 0
                for _ in range(TRIALS):
                    column = rng.choice(eligible)
                    picked = rng.sample(pools[column], size)
                    drawn = list(zip(picked, made_up(rng, grid, top, len(picked)), strict=True))
                    counted = Counter(drawn)
                    hits += any(p.explains(drawn, counted) for p in candidates) and not any(
                        p.explains(drawn, counted) for p in known
                    )
                added[grid][str(size)] = hits
        result["transforms"][name] = {"outputs": len(found), "ties": ties, "added": added}
    return result


def request_leg(rng):
    lists = {f"1 to {m}": [float(i) for i in range(1, m + 1)] for m in (3, 5, 10)}
    for m in (3, 5, 10):
        lists[f"{m} random"] = [float(x) for x in rng.sample(range(1, 101), m)]
    result = {}
    for how in REQUEST:
        result[how] = {}
        for label, numbers in lists.items():
            made = [value for _key, value in of_series(list(enumerate(numbers)), how) or []]
            transformed, typed = set(made), set(numbers)
            top = max((abs(v) for v in made), default=0.0) or 1.0
            added = {}
            for grid in GRIDS:
                added[grid] = {}
                for size in SIZES:
                    hits = 0
                    for _ in range(TRIALS):
                        drawn = made_up(rng, grid, top, size)
                        hits += transformed.issuperset(drawn) and not typed.issuperset(drawn)
                    added[grid][str(size)] = hits
            result[how][label] = added
    return result


if __name__ == "__main__":
    rng = random.Random(45)  # noqa: S311 - a seeded sample, not a secret
    data = ROOT.parents[1] / "data"
    result = {
        "trials": TRIALS,
        "csv": {path.name: measure(path, rng) for path in sorted(data.glob("*.csv"))},
        "request": request_leg(rng),
    }
    (ROOT / "x1-result.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(json.dumps(result, ensure_ascii=False))
