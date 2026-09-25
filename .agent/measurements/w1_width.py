# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""W1 -- grade one design capture against the shipped verifier and the task intent table.

Design rows alone form the 24-row category denominators. Sentinels print separately;
these design-set rates are tuning evidence, never held-out acceptance evidence.

    uv run --locked python .agent/measurements/w1_width.py [<run-dir>]
"""

import collections
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from capture.harness import defence  # noqa: E402 -- the repo root must be on the path first
from verifier.pysrc.spec import DatasetPlot, DatasetTarget  # noqa: E402
from verifier.pysrc.verify import Verified, verify_python_source  # noqa: E402

DEFAULT_RUN = REPO_ROOT / "corpus" / "python" / "captures" / "m10-design"
DATASETS = ("sales.csv", "weather.csv")

run_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_RUN
data = {name: (REPO_ROOT / "data" / name).read_bytes() for name in DATASETS}
design = json.loads((REPO_ROOT / "corpus/python/design/manifest.json").read_text())
idiom_of = {prompt["id"]: prompt["idiom"] for prompt in design["prompts"]}
intent = json.loads((Path(__file__).parent / "design_intent.json").read_text())
simple_ids = {row["id"] for row in design["prompts"] if row["category"] == "simple"}
assert set(intent) == simple_ids
assert all(
    set(item) in ({"mark", "x", "y", "reduction"}, {"mark", "x", "y", "reduction", "series_by"})
    for item in intent.values()
)
records = [
    json.loads(line) for line in (run_dir / "records.ndjson").read_text().splitlines() if line
]

by_category: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
by_idiom: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
faithful_ids: list[str] = []
unfaithful: dict[str, tuple[dict[str, object], dict[str, object]]] = {}
sentinels: dict[str, str] = {}
sentinel_counts: collections.Counter[str] = collections.Counter()
outcome_of: dict[str, str] = {}

for record in records:
    prompt_id = record["prompt_id"]
    name = record["dataset_name"]
    _, source = defence(record["content"] or "")
    verdict = verify_python_source(
        source, declared_target=DatasetTarget(path=f"/mnt/uploads/{name}", content=data[name])
    )
    outcome = "VERIFIED" if isinstance(verdict, Verified) else verdict.code
    if record["kind"] == "sentinels":
        sentinels[prompt_id] = outcome
        sentinel_counts[prompt_id] += 1
        continue
    assert record["kind"] == "design" and prompt_id in idiom_of
    category = record["category"]
    by_category[category][outcome] += 1
    by_idiom[idiom_of[prompt_id]][outcome] += 1
    outcome_of[prompt_id] = outcome
    if category == "simple" and isinstance(verdict, Verified):
        assert isinstance(verdict.spec, DatasetPlot)
        projected = {
            "mark": verdict.spec.mark,
            "x": verdict.spec.x.name,
            "y": verdict.spec.y.name,
            "reduction": verdict.spec.group,
        }
        expected = intent[prompt_id]
        if "series_by" not in expected and projected == expected:
            faithful_ids.append(prompt_id)
        else:
            unfaithful[prompt_id] = (expected, projected)

assert set(outcome_of) == set(idiom_of)
assert sum(by_category["simple"].values()) == sum(by_category["complicated"].values()) == 24
print(f"run: {run_dir.name}   records: {len(records)}")
for category in ("simple", "complicated"):
    codes = by_category[category]
    total = sum(codes.values())
    verified = codes["VERIFIED"]
    print(f"\n=== design {category}: {verified}/{total} VERIFIED")
    if category == "simple":
        print(f"=== design simple: {len(faithful_ids)}/{total} FAITHFUL")
        print("faithful ids:", ", ".join(sorted(faithful_ids)))
        print("verified but unfaithful:")
        for prompt_id, (expected, projected) in sorted(unfaithful.items()):
            print(f"  {prompt_id} expected={expected} projected={projected}")
    else:
        print(f"=== design complicated: {total - verified}/{total} BLOCKED")
    for code, count in codes.most_common():
        print(f"  {count:3d}  {code}")

print(f"\nname_not_bound, design simple: {by_category['simple']['name_not_bound']}/24")
print("\n=== simple idioms")
for key in sorted({idiom_of[p] for p in simple_ids}):
    print(f"  {key:26} {dict(by_idiom[key])}")

print("\n=== sentinels (outside category denominators)")
for prompt_id, outcome in sorted(sentinels.items()):
    print(f"  {prompt_id}: {outcome} (records: {sentinel_counts[prompt_id]})")

print("\n=== per design row")
for prompt_id, outcome in sorted(outcome_of.items()):
    status = "F" if prompt_id in faithful_ids else "U" if prompt_id in unfaithful else "R"
    print(f"  {prompt_id:22} {idiom_of[prompt_id]:26} {status} {outcome}")
