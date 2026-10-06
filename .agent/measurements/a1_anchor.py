# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""A1 -- request anchoring (Q8): false refusals and caught substitutions per language.

Corpus = the 24 design-simple prompts (EN, `corpus/python/design/manifest.json`) + two authored
Japanese renderings each (`a1_ja.json`): `ja` names the columns in Japanese over a copy of the
dataset whose header is translated, `ja_mixed` names the English header columns inside Japanese
sentences. Held-out prompts stay unread.

Legs, each verified with `request=None` (baseline) and with the prompt as the request:
- intent: the program `design_intent.json` describes. A task needing a per-city series is not
  faithful to its program and is counted apart; every other refusal by anchoring is FALSE.
- substitution: the intent program with x or y swapped for another header column; a baseline
  VERIFIED swap that anchoring refuses is CAUGHT.
- capture: the committed `m10-design` proposer captures (EN), every row whose verdict anchoring
  changes, with W1's FAITHFUL reading.

    uv run --locked python .agent/measurements/a1_anchor.py   # writes a1-result.json
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from capture.harness import defence  # noqa: E402 -- the repo root must be on the path first
from verifier.pysrc.spec import DatasetTarget  # noqa: E402
from verifier.pysrc.verify import Verified, verify_python_source  # noqa: E402

HERE = Path(__file__).parent
CALLS = {"line": "plot", "scatter": "scatter", "bar": "bar", "barh": "barh"}
LANGUAGES = ("en", "ja", "ja_mixed")

design = json.loads((REPO_ROOT / "corpus/python/design/manifest.json").read_text())
simple = {row["id"]: row for row in design["prompts"] if row["category"] == "simple"}
intent = json.loads((HERE / "design_intent.json").read_text())
ja = json.loads((HERE / "a1_ja.json").read_text())
assert set(intent) == set(simple) == set(ja["prompts"])
data = {name: (REPO_ROOT / "data" / name).read_bytes() for name in ja["headers"]}


def translated(name):
    """The dataset with its header line alone translated; every data byte stays."""
    mapping = ja["headers"][name]
    head, _, rest = data[name].partition(b"\n")
    columns = head.decode().split(",")
    assert columns == list(mapping)
    return ",".join(mapping[c] for c in columns).encode() + b"\n" + rest


def program(path, mark, x, y, reduction):
    lines = [
        "import pandas as pd",
        "import matplotlib.pyplot as plt",
        f'df = pd.read_csv("{path}")',
    ]
    call = CALLS[mark]
    if reduction:
        lines += [f'g = df.groupby("{x}")["{y}"].{reduction}()', f"plt.{call}(g.index, g.values)"]
    else:
        lines.append(f'plt.{call}(df["{x}"], df["{y}"])')
    return "\n".join([*lines, "plt.show()", ""])


def outcome(source, path, content, request):
    verdict = verify_python_source(
        source, declared_target=DatasetTarget(path=path, content=content, request=request)
    )
    return "VERIFIED" if isinstance(verdict, Verified) else verdict.code


def case(language, prompt_id):
    """(request, path, content, column map) for one prompt in one language."""
    name = simple[prompt_id]["dataset_name"]
    path = f"/mnt/uploads/{name}"
    if language == "en":
        identity = {c: c for c in ja["headers"][name]}
        return simple[prompt_id]["prompt"], path, data[name], identity
    if language == "ja":
        return ja["prompts"][prompt_id]["ja"], path, translated(name), ja["headers"][name]
    identity = {c: c for c in ja["headers"][name]}
    return ja["prompts"][prompt_id]["ja_mixed"], path, data[name], identity


result = {}
for language in LANGUAGES:
    leg = {
        "faithful": 0,
        "baseline_refused": [],
        "false_refusals": [],
        "series_refused": [],
        "series": 0,
        "swaps_verified": 0,
        "swaps_caught": 0,
        "swaps_missed": [],
    }
    for prompt_id, task in sorted(intent.items()):
        request, path, content, columns = case(language, prompt_id)
        x, y = columns[task["x"]], columns[task["y"]]
        source = program(path, task["mark"], x, y, task["reduction"])
        base = outcome(source, path, content, None)
        if base != "VERIFIED":
            leg["baseline_refused"].append(f"{prompt_id}:{base}")
            continue
        anchored = outcome(source, path, content, request)
        if "series_by" in task:
            leg["series"] += 1
            if anchored != "VERIFIED":
                leg["series_refused"].append(f"{prompt_id}:{anchored}")
            continue
        leg["faithful"] += 1
        if anchored != "VERIFIED":
            leg["false_refusals"].append(f"{prompt_id}:{anchored}")
        for slot in ("x", "y"):
            for other in columns.values():
                if other in (x, y):
                    continue
                swapped = (other, y) if slot == "x" else (x, other)
                swap = program(path, task["mark"], *swapped, task["reduction"])
                if outcome(swap, path, content, None) != "VERIFIED":
                    continue
                leg["swaps_verified"] += 1
                if outcome(swap, path, content, request) == "column_not_requested":
                    leg["swaps_caught"] += 1
                else:
                    leg["swaps_missed"].append(f"{prompt_id}:{slot}={other}")
    result[language] = leg

records = [
    json.loads(line)
    for line in (REPO_ROOT / "corpus/python/captures/m10-design/records.ndjson")
    .read_text()
    .splitlines()
    if line
]
prompts = {row["id"]: row["prompt"] for row in design["prompts"]}
changed = []
faithful_refused = []
verified = 0
for record in records:
    if record["kind"] != "design":
        continue
    prompt_id, name = record["prompt_id"], record["dataset_name"]
    _, source = defence(record["content"] or "")
    path = f"/mnt/uploads/{name}"
    target = DatasetTarget(path=path, content=data[name])
    verdict = verify_python_source(source, declared_target=target)
    base = "VERIFIED" if isinstance(verdict, Verified) else verdict.code
    verified += base == "VERIFIED"
    anchored = outcome(source, path, data[name], prompts[prompt_id])
    if anchored == base:
        continue
    changed.append(f"{prompt_id}:{base}->{anchored}")
    # W1's FAITHFUL reading: the verified spec equals the task intent, which needs no series.
    task = intent.get(prompt_id)
    if (
        isinstance(verdict, Verified)
        and task is not None
        and "series_by" not in task
        and (verdict.spec.mark, verdict.spec.x.name, verdict.spec.y.name, verdict.spec.group)
        == (task["mark"], task["x"], task["y"], task["reduction"])
    ):
        faithful_refused.append(prompt_id)
result["capture"] = {
    "design_rows": len([r for r in records if r["kind"] == "design"]),
    "baseline_verified": verified,
    "changed": changed,
    "faithful_refused": faithful_refused,
}

for language in LANGUAGES:
    leg = result[language]
    print(
        f"{language}: false refusals {len(leg['false_refusals'])}/{leg['faithful']} faithful;"
        f" series tasks refused {len(leg['series_refused'])}/{leg['series']};"
        f" swaps caught {leg['swaps_caught']}/{leg['swaps_verified']};"
        f" baseline refused {leg['baseline_refused']}"
    )
    print(f"  false: {leg['false_refusals']}  series: {leg['series_refused']}")
    print(f"  missed swaps: {leg['swaps_missed']}")
print(
    f"capture: {verified}/{result['capture']['design_rows']} design rows VERIFIED;"
    f" FAITHFUL refused {faithful_refused}; changed by anchoring: {changed}"
)
(HERE / "a1-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
