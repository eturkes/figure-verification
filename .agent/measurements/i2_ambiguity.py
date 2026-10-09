# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""I2: keyed value-explanation ambiguity + chance matches over data/*.csv (M19 readings).

Explanations (closed, `.claude/rules/figure.md`): raw(K,V), index(V), group(K,V,r) r in sum mean
min max, count(K). A point = (key, value). Measures, per CSV: (a) full-series ties between
explanations with different column sets; (b) keyed points shared by explanations with different
column sets; (c) k-point subsets (k = 1..3) of one explanation also explained, injectively, by an
explanation with other columns; (d) chance: made-up series over a real key column's keys with
values uniform in [0, 2 * column max], k = 1..5 points, 10,000 trials each, explained by any
explanation. Host only: `uv run --locked python .agent/measurements/i2_ambiguity.py`.
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


def explanations(header, rows):
    numeric = [c for c in header if rows and all(number(r[c]) is not None for r in rows)]
    found = {}
    for v in numeric:
        found[("index", (v,))] = Counter((float(i), number(r[v])) for i, r in enumerate(rows))
        for k in header:
            if k == v:
                continue
            found[("raw", (k, v))] = Counter((r[k], number(r[v])) for r in rows)
            groups = {}
            for r in rows:
                groups.setdefault(r[k], []).append(number(r[v]))
            for how in REDUCTIONS:
                found[(how, (k, v))] = Counter((key, reduce(vs, how)) for key, vs in groups.items())
    for k in header:
        found[("count", (k,))] = Counter(Counter(r[k] for r in rows).items())
    return found


def explains(explanation, points):
    return not (Counter(points) - explanation)


def measure(path, rng):
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header, rows = list(reader.fieldnames or ()), list(reader)
    numeric = [c for c in header if rows and all(number(r[c]) is not None for r in rows)]
    if not numeric:  # e.g. deliberately_dirty.csv: every column holds an empty or NA cell
        return {"rows": len(rows), "numeric_columns": 0}
    found = explanations(header, rows)
    names = sorted(found)
    full_ties = sorted(
        f"{a[0]}{list(a[1])}={b[0]}{list(b[1])}"
        for a, b in itertools.combinations(names, 2)
        if a[1] != b[1] and found[a] == found[b]
    )
    owners = {}
    for name in names:
        for point in found[name]:
            owners.setdefault(point, set()).add(name[1])
    shared = sum(1 for cols in owners.values() if len(cols) > 1)
    subsets = {}
    for size in (1, 2, 3):
        total = tied = 0
        for name in names:
            points = list(found[name].elements())
            for combo in itertools.combinations(points, size):
                total += 1
                tied += any(
                    other[1] != name[1] and explains(found[other], combo) for other in names
                )
        subsets[str(size)] = {"subsets": total, "tied": tied}
    keys = [c for c in header if c not in numeric] or header
    top = max(abs(number(r[c])) for r in rows for c in numeric)
    chance = {}
    for size in range(1, 6):
        hits = 0
        for _ in range(TRIALS):
            column = rng.choice(keys)
            pool = sorted({r[column] for r in rows})
            picked = rng.sample(pool, min(size, len(pool)))
            series = [(key, float(rng.randint(0, int(2 * top)))) for key in picked]
            hits += any(explains(found[name], series) for name in names)
        chance[str(size)] = hits
    return {
        "rows": len(rows),
        "numeric_columns": len(numeric),
        "explanations": len(found),
        "full_ties": full_ties,
        "points": len(owners),
        "shared_points": shared,
        "subsets": subsets,
        "chance_hits": chance,
        "trials": TRIALS,
    }


if __name__ == "__main__":
    rng = random.Random(19)  # noqa: S311 - a seeded sample, not a secret
    data = ROOT.parents[1] / "data"
    result = {path.name: measure(path, rng) for path in sorted(data.glob("*.csv"))}
    (ROOT / "i2-result.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(json.dumps(result, ensure_ascii=False))
