# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""A2 -- label consistency (G10, Q16): false refusals and caught plants per language.

Corpus = the 24 design-simple tasks of `design_intent.json`, each drawn as its intent program and
labelled from `a2_labels.json` (concept names + summary words per language) in three forms: `en`
and `ja` name concepts in their language, `ja` over a copy of the dataset whose header is the
Japanese concept names (`a1_ja.json` headers), and `ja_mixed` names the English header columns
inside Japanese labels. Plus the `m10-design` captures (EN labels the proposer wrote). Held-out
prompts stay unread.

Legs:
- intent: a title, an x label and a y label per task; a task needing a per-city series is counted
  apart. Every refusal of the others is FALSE.
- plant: the intent labels with the x label swapped for another header column's name, and over a
  reduction the summary word swapped for each other reduction's; a plant G10 refuses is CAUGHT.
- capture: each `m10-design` row whose verdict G10 changes (baseline = the same verifier with
  `_check_labels` neutralised), with W1's FAITHFUL reading.

    uv run --locked python .agent/measurements/a2_labels.py   # writes a2-result.json
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from capture.harness import defence  # noqa: E402 -- the repo root must be on the path first
from verifier.pysrc import verify  # noqa: E402
from verifier.pysrc.spec import DatasetTarget  # noqa: E402

HERE = Path(__file__).parent
CALLS = {"line": "plot", "scatter": "scatter", "bar": "bar", "barh": "barh"}
FORMS = ("en", "ja", "ja_mixed")

design = json.loads((REPO_ROOT / "corpus/python/design/manifest.json").read_text())
intent = json.loads((HERE / "design_intent.json").read_text())
words = json.loads((HERE / "a2_labels.json").read_text())
headers_ja = json.loads((HERE / "a1_ja.json").read_text())["headers"]
dataset_of = {row["id"]: row["dataset_name"] for row in design["prompts"]}
data = {name: (REPO_ROOT / "data" / name).read_bytes() for name in headers_ja}


def translated(name):
    mapping = headers_ja[name]
    head, _, rest = data[name].partition(b"\n")
    assert head.decode().split(",") == list(mapping)
    return ",".join(mapping.values()).encode() + b"\n" + rest


def outcome(source, content):
    verdict = verify.verify_python_source(
        source, declared_target=DatasetTarget(path="/mnt/uploads/data.csv", content=content)
    )
    return "VERIFIED" if isinstance(verdict, verify.Verified) else verdict.code


def labels(form, name, x, y, reduction):
    """(title, xlabel, ylabel) for one task in one form."""
    language = "en" if form == "en" else "ja"
    concept = (lambda c: c) if form == "ja_mixed" else words["concepts"][language].get
    summary = words["summaries"][language].get(reduction) if reduction else None
    if language == "en":
        ylabel = f"{summary} {concept(y)}" if summary else concept(y)
        title = f"{ylabel} by {concept(x)}"
    else:
        ylabel = f"{concept(y)}の{summary}" if summary else concept(y)
        title = f"{concept(x)}ごとの{ylabel}"
    assert name in headers_ja
    return title, concept(x), ylabel


def program(content_columns, task, title, xlabel, ylabel):
    x, y = content_columns[task["x"]], content_columns[task["y"]]
    lines = ["import pandas as pd", "import matplotlib.pyplot as plt"]
    lines.append('df = pd.read_csv("/mnt/uploads/data.csv")')
    call = CALLS[task["mark"]]
    if task["reduction"]:
        lines += [
            f'g = df.groupby("{x}")["{y}"].{task["reduction"]}()',
            f"plt.{call}(g.index, g.values)",
        ]
    else:
        lines.append(f'plt.{call}(df["{x}"], df["{y}"])')
    lines += [f'plt.title("{title}")', f'plt.xlabel("{xlabel}")', f'plt.ylabel("{ylabel}")']
    return "\n".join([*lines, "plt.show()", ""])


result = {}
for form in FORMS:
    leg = {
        "faithful": 0,
        "false_refusals": [],
        "series": 0,
        "series_refused": [],
        "baseline_refused": [],
        "column_plants": 0,
        "column_caught": 0,
        "column_missed": [],
        "summary_plants": 0,
        "summary_caught": 0,
    }
    for prompt_id, task in sorted(intent.items()):
        name = dataset_of[prompt_id]
        columns = headers_ja[name] if form == "ja" else {c: c for c in headers_ja[name]}
        content = translated(name) if form == "ja" else data[name]
        title, xlabel, ylabel = labels(form, name, task["x"], task["y"], task["reduction"])
        verdict = outcome(program(columns, task, title, xlabel, ylabel), content)
        if verdict not in {"VERIFIED", "label_not_consistent"}:
            leg["baseline_refused"].append(f"{prompt_id}:{verdict}")
            continue
        if "series_by" in task:
            leg["series"] += 1
            if verdict != "VERIFIED":
                leg["series_refused"].append(prompt_id)
            continue
        leg["faithful"] += 1
        if verdict != "VERIFIED":
            leg["false_refusals"].append(prompt_id)
            continue
        for other in headers_ja[name]:
            if other in (task["x"], task["y"]):
                continue
            planted = labels(form, name, other, task["y"], task["reduction"])[1]
            leg["column_plants"] += 1
            if outcome(program(columns, task, title, planted, ylabel), content) != "VERIFIED":
                leg["column_caught"] += 1
            else:
                leg["column_missed"].append(f"{prompt_id}:{other}")
        for wrong in ("sum", "mean", "min", "max"):
            if task["reduction"] is None or wrong == task["reduction"]:
                continue
            planted_title = labels(form, name, task["x"], task["y"], wrong)[0]
            leg["summary_plants"] += 1
            refused = outcome(program(columns, task, planted_title, xlabel, ylabel), content)
            leg["summary_caught"] += refused == "label_not_consistent"
    result[form] = leg

records = [
    json.loads(line)
    for line in (REPO_ROOT / "corpus/python/captures/m10-design/records.ndjson")
    .read_text()
    .splitlines()
    if line
]
checked = verify._check_labels
changed, faithful_refused = [], []
for record in records:
    if record["kind"] != "design":
        continue
    prompt_id, name = record["prompt_id"], record["dataset_name"]
    _, source = defence(record["content"] or "")
    target = DatasetTarget(path=f"/mnt/uploads/{name}", content=data[name])
    verify._check_labels = lambda _spec, _header: None
    try:
        base = verify.verify_python_source(source, declared_target=target)
    finally:
        verify._check_labels = checked
    labelled = verify.verify_python_source(source, declared_target=target)
    before = "VERIFIED" if isinstance(base, verify.Verified) else base.code
    after = "VERIFIED" if isinstance(labelled, verify.Verified) else labelled.code
    if before == after:
        continue
    changed.append(f"{prompt_id}:{before}->{after}")
    task = intent.get(prompt_id)
    if (
        isinstance(base, verify.Verified)
        and task is not None
        and "series_by" not in task
        and (base.spec.mark, base.spec.x.name, base.spec.y.name, base.spec.group)
        == (task["mark"], task["x"], task["y"], task["reduction"])
    ):
        faithful_refused.append(prompt_id)
result["capture"] = {"changed": changed, "faithful_refused": faithful_refused}

for form in FORMS:
    leg = result[form]
    print(
        f"{form}: false refusals {len(leg['false_refusals'])}/{leg['faithful']};"
        f" series refused {len(leg['series_refused'])}/{leg['series']};"
        f" column plants caught {leg['column_caught']}/{leg['column_plants']};"
        f" summary plants caught {leg['summary_caught']}/{leg['summary_plants']}"
    )
    print(f"  false: {leg['false_refusals']}  baseline refused: {leg['baseline_refused']}")
    print(f"  missed column plants: {leg['column_missed']}")
print(f"capture: FAITHFUL refused {faithful_refused}; changed by G10: {changed}")
(HERE / "a2-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
