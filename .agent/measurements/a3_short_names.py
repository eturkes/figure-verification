# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""A3 -- Japanese short-word naming (Q41 + Q42 suffixes): every name the strict-only tier adds.

Corpus = `a3_clinical.json` (an authored clinical header, 3 rows, 20 Japanese requests, each with
the chart it asks for) + A1's Japanese renderings (`a1_ja.json`). Held-out prompts stay unread.

Legs:
- clinical: each request over the clinical header. `added` = the names strict anchoring's
  short-word tier adds to the shared matcher's names; a name outside the request's own chart is
  FALSE. The request's own chart is verified under each rule; every refusal is FALSE.
- own: each A1 `ja` rendering over its own translated header; a name outside the intent's x/y is
  FALSE (`design_intent.json`; a per-city series task also names `都市`).
- noise: each A1 `ja` rendering over the OTHER dataset's translated header and over the clinical
  header, and each clinical request over both translated headers. An added name is FALSE unless it
  spells a column the request asks for in its own dataset (`年月` is the month column in both).
- suffix (Q42): each clinical request rewritten with each grouping suffix (`別` `毎` `次`
  `単位`): its grouping word (`ごと`, or the one suffix it already holds) replaced, or, in a scatter
  request with no grouping word, the suffix glued to its x-axis word; over the clinical header and
  both translated headers; FALSE as in the noise leg.

    uv run --locked python .agent/measurements/a3_short_names.py   # writes a3-result.json
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from verifier.pysrc import verify  # noqa: E402 -- the repo root must be on the path first
from verifier.pysrc.spec import DatasetTarget  # noqa: E402

HERE = Path(__file__).parent
CALLS = {"line": "plot", "scatter": "scatter", "bar": "bar", "barh": "barh"}

clinical = json.loads((HERE / "a3_clinical.json").read_text())
ja = json.loads((HERE / "a1_ja.json").read_text())
intent = json.loads((HERE / "design_intent.json").read_text())
design = json.loads((REPO_ROOT / "corpus/python/design/manifest.json").read_text())
dataset = {row["id"]: row["dataset_name"] for row in design["prompts"]}
headers = {name: tuple(mapping.values()) for name, mapping in ja["headers"].items()}
CLINICAL = tuple(clinical["header"])
CONTENT = "\n".join(",".join(row) for row in [clinical["header"], *clinical["rows"]]).encode()


def added(request, header):
    """The names the short-word tier adds; a tie under either reading = `TIE`."""
    try:
        shared = verify._anchors(request, header)[0]
        strict = verify._anchors(request, header, short_names=True)[0]
    except verify._AmbiguousTermError:
        return {"TIE"}
    return set(strict - shared)


def program(task):
    lines = ["import pandas as pd", "import matplotlib.pyplot as plt", 'df = pd.read_csv("c.csv")']
    call, x, y = CALLS[task["mark"]], task["x"], task["y"]
    if task["reduction"]:
        lines += [
            f'g = df.groupby("{x}")["{y}"].{task["reduction"]}()',
            f"plt.{call}(g.index, g.values)",
        ]
    else:
        lines.append(f'plt.{call}(df["{x}"], df["{y}"])')
    return "\n".join([*lines, "plt.show()", ""])


def outcome(source, request, anchoring):
    target = DatasetTarget(path="c.csv", content=CONTENT, request=request, anchoring=anchoring)
    verdict = verify.verify_python_source(source, declared_target=target)
    return "VERIFIED" if isinstance(verdict, verify.Verified) else verdict.code


def marked(label, names, wanted):
    return [f"{label}:{name}" + ("" if name in wanted else ":FALSE") for name in sorted(names)]


result = {"clinical": {"requests": 0, "added": [], "baseline_refused": [], "false_refusals": {}}}
leg = result["clinical"]
leg["false_refusals"] = {"strict": [], "substitution": []}
for number, task in enumerate(clinical["requests"], 1):
    leg["requests"] += 1
    leg["added"] += marked(
        f"c{number:02}", added(task["request"], CLINICAL), {task["x"], task["y"]}
    )
    source = program(task)
    if (base := outcome(source, None, "strict")) != "VERIFIED":
        leg["baseline_refused"].append(f"c{number:02}:{base}")
        continue
    for anchoring in ("strict", "substitution"):
        if (verdict := outcome(source, task["request"], anchoring)) != "VERIFIED":
            leg["false_refusals"][anchoring].append(f"c{number:02}:{verdict}")

own = []
wants = {}
for prompt_id, task in sorted(intent.items()):
    mapping = ja["headers"][dataset[prompt_id]]
    wants[prompt_id] = {mapping[task["x"]], mapping[task["y"]]} | (
        {mapping[task["series_by"]]} if "series_by" in task else set()
    )
    request = ja["prompts"][prompt_id]["ja"]
    own += marked(prompt_id, added(request, headers[dataset[prompt_id]]), wants[prompt_id])
result["own"] = {"prompts": len(intent), "added": own}

noise = []
pairs = 0
other = {"sales.csv": "weather.csv", "weather.csv": "sales.csv"}
for prompt_id in sorted(intent):
    for label, header in (("other", headers[other[dataset[prompt_id]]]), ("clinical", CLINICAL)):
        pairs += 1
        request = ja["prompts"][prompt_id]["ja"]
        noise += marked(f"{prompt_id}/{label}", added(request, header), wants[prompt_id])
for number, task in enumerate(clinical["requests"], 1):
    for name, header in sorted(headers.items()):
        pairs += 1
        noise += marked(
            f"c{number:02}/{name}", added(task["request"], header), {task["x"], task["y"]}
        )
result["noise"] = {"pairs": pairs, "added": noise}

suffixed = []
suffix_pairs = 0
SUFFIXES = ("別", "毎", "次", "単位")
for number, task in enumerate(clinical["requests"], 1):
    text = task["request"]
    if not task["reduction"]:
        word, glue = task["x"], task["x"]
    else:
        word, glue = "ごと" if "ごと" in text else next(w for w in SUFFIXES if w in text), ""
    assert text.count(word) == 1, text
    for suffix in SUFFIXES:
        request = text.replace(word, glue + suffix)
        for name, header in [("clinical", CLINICAL), *sorted(headers.items())]:
            suffix_pairs += 1
            label = f"c{number:02}{suffix}/{name}"
            suffixed += marked(label, added(request, header), {task["x"], task["y"]})
result["suffix"] = {"pairs": suffix_pairs, "added": suffixed}

print(f"clinical: {leg['requests']} requests; added {leg['added']}")
print(f"  baseline refused {leg['baseline_refused']}; false refusals {leg['false_refusals']}")
print(f"own: added {own}")
print(f"noise: {pairs} pairs; added {noise}")
print(f"suffix: {suffix_pairs} pairs; added {suffixed}")
(HERE / "a3-result.json").write_text(
    json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
)
