# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""W1 -- what the shipped admitted subset does to a committed capture run.

Reads the raw model replies of ONE run, de-fences each through the capture harness' sole
authority, verifies it with the shipped `verify_python_source` against the dataset the prompt was
bound to, and ranks the outcome per category and per idiom. This is the number a width unit is
aimed by and the number a proposer-lever unit is graded on.

    uv run --locked python .agent/measurements/w1_width.py [<run-dir>]

Design set only, by ruling: the held-out manifest stays ungenerated until the M13 config is frozen,
so a rate taken here is TUNING evidence, never acceptance evidence. Sentinel rows sit outside both
category denominators and are reported on their own.
"""

import collections
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from capture.harness import defence  # noqa: E402 -- the repo root must be on the path first
from verifier.pysrc.spec import DatasetTarget  # noqa: E402
from verifier.pysrc.verify import Verified, verify_python_source  # noqa: E402

DEFAULT_RUN = REPO_ROOT / "corpus" / "python" / "captures" / "m13-design"
DATASETS = ("sales.csv", "weather.csv")

run_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_RUN
data = {name: (REPO_ROOT / "data" / name).read_bytes() for name in DATASETS}
design = json.loads((REPO_ROOT / "corpus/python/design/manifest.json").read_text())
idiom_of = {prompt["id"]: prompt["idiom"] for prompt in design["prompts"]}
records = [
    json.loads(line) for line in (run_dir / "records.ndjson").read_text().splitlines() if line
]

by_category: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
by_idiom: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
verified: collections.Counter[str] = collections.Counter()
totals: collections.Counter[str] = collections.Counter()
outcome_of: dict[str, str] = {}

for record in records:
    name = record["dataset_name"]
    _, source = defence(record["content"] or "")
    verdict = verify_python_source(
        source, declared_target=DatasetTarget(path=f"/mnt/uploads/{name}", content=data[name])
    )
    outcome = "VERIFIED" if isinstance(verdict, Verified) else verdict.code
    category = record["category"]
    totals[category] += 1
    verified[category] += outcome == "VERIFIED"
    by_category[category][outcome] += 1
    by_idiom[idiom_of.get(record["prompt_id"], "sentinel")][outcome] += 1
    outcome_of[record["prompt_id"]] = outcome

print(f"run: {run_dir.name}   records: {len(records)}")
for category in sorted(by_category):
    print(f"\n=== {category}: {verified[category]}/{totals[category]} verified")
    for code, count in by_category[category].most_common():
        print(f"  {count:3d}  {code}")

simple_codes = by_category["simple"]
print(f"\nname_not_bound, simple: {simple_codes['name_not_bound']}/{totals['simple']}")

print("\n=== simple idioms")
for key in sorted({idiom_of[p] for p in idiom_of if p.startswith("design-simple")}):
    print(f"  {key:26} {dict(by_idiom[key])}")

print("\n=== per row")
for prompt_id in sorted(outcome_of):
    print(f"  {prompt_id:22} {idiom_of.get(prompt_id, 'sentinel'):26} {outcome_of[prompt_id]}")
