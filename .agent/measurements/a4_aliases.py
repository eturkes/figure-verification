# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""A4 -- admin-declared column aliases (Q43): A1, A3 and H1 re-run with one committed alias file.

Aliases = `a4_aliases.txt`, the tool Valve's own text format, parsed by the paste-in's parser and
authored from column MEANINGS (EN + JA, the A1 headers, their translations and the A3 clinical
header) before any A4 run. Each leg mirrors its source script with `DatasetTarget.aliases` set:
- A1 (`a1_anchor.py`): per language, the 18 faithful intent programs (false refusals under both
  rules), the series tasks, every baseline-VERIFIED x/y swap (caught under both rules), the stop +
  negation plants, and the `m10-design` capture rows whose verdict strict anchoring changes.
- A3 (`a3_short_names.py`): the names the strict short-word tier adds, every leg, FALSE marked as
  there; the clinical charts verified under both rules.
- H1 (`h1_heldout_anchoring.py`): the held-out capture re-graded under both rules. Reported, never
  targeted: the alias file predates this run, and MAIN read 7 held-out prompts before the contract.

    uv run --locked python .agent/measurements/a4_aliases.py   # writes a4-result.json
"""

import json
import sys
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from capture import score  # noqa: E402 -- the repo root must be on the path first
from capture.corpus import load_corpus  # noqa: E402
from capture.harness import defence  # noqa: E402
from capture.record import load_run  # noqa: E402
from verifier.pysrc import verify  # noqa: E402
from verifier.pysrc.spec import DatasetPlot, DatasetTarget  # noqa: E402
from webui.paste_in.aliases import parse_aliases  # noqa: E402

HERE = Path(__file__).parent
CALLS = {"line": "plot", "scatter": "scatter", "bar": "bar", "barh": "barh"}
ALIASES = parse_aliases((HERE / "a4_aliases.txt").read_text())

design = json.loads((REPO_ROOT / "corpus/python/design/manifest.json").read_text())
simple = {row["id"]: row for row in design["prompts"] if row["category"] == "simple"}
intent = json.loads((HERE / "design_intent.json").read_text())
ja = json.loads((HERE / "a1_ja.json").read_text())
clinical = json.loads((HERE / "a3_clinical.json").read_text())
data = {name: (REPO_ROOT / "data" / name).read_bytes() for name in ja["headers"]}
headers = {name: tuple(mapping.values()) for name, mapping in ja["headers"].items()}
CLINICAL = tuple(clinical["header"])
CLINICAL_CONTENT = "\n".join(",".join(r) for r in [clinical["header"], *clinical["rows"]]).encode()


def translated(name):
    mapping = ja["headers"][name]
    head, _, rest = data[name].partition(b"\n")
    assert head.decode().split(",") == list(mapping)
    return ",".join(mapping.values()).encode() + b"\n" + rest


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


def outcome(source, path, content, request, anchoring):
    target = DatasetTarget(path, content, request, anchoring, ALIASES)
    verdict = verify.verify_python_source(source, declared_target=target)
    return "VERIFIED" if isinstance(verdict, verify.Verified) else verdict.code


def case(language, prompt_id):
    name = simple[prompt_id]["dataset_name"]
    path = f"/mnt/uploads/{name}"
    identity = {c: c for c in ja["headers"][name]}
    if language == "en":
        return simple[prompt_id]["prompt"], path, data[name], identity
    if language == "ja":
        return ja["prompts"][prompt_id]["ja"], path, translated(name), ja["headers"][name]
    return ja["prompts"][prompt_id]["ja_mixed"], path, data[name], identity


result = {}
for language in ("en", "ja", "ja_mixed"):
    leg = {"faithful": 0, "series": 0, "swaps_verified": 0, "baseline_refused": []}
    for rule in ("substitution", "strict"):
        leg[rule] = {
            "false_refusals": [],
            "series_refused": [],
            "swaps_caught": 0,
            "stop_false_refusals": [],
            "negation_false_refusals": [],
        }
    for prompt_id, task in sorted(intent.items()):
        request, path, content, columns = case(language, prompt_id)
        x, y = columns[task["x"]], columns[task["y"]]
        source = program(path, task["mark"], x, y, task["reduction"])
        if (base := outcome(source, path, content, None, "strict")) != "VERIFIED":
            leg["baseline_refused"].append(f"{prompt_id}:{base}")
            continue
        series = "series_by" in task
        leg["series" if series else "faithful"] += 1
        other = next(column for column in columns.values() if column not in (x, y))
        plants = {
            "stop": f"{request.rstrip('.')} in chronological order."
            if language == "en"
            else f"{request}(chronological order)",
            "negation": f"{request.rstrip('.')}, not {other}."
            if language == "en"
            else f"{other}ではなく、{request}",
        }
        swaps = []
        for slot in ("x", "y"):
            for column in columns.values():
                if column in (x, y):
                    continue
                pair = (column, y) if slot == "x" else (x, column)
                swap = program(path, task["mark"], *pair, task["reduction"])
                if outcome(swap, path, content, None, "strict") == "VERIFIED":
                    swaps.append(swap)
        if not series:
            leg["swaps_verified"] += len(swaps)
        for rule in ("substitution", "strict"):
            ruled = leg[rule]
            verdict = outcome(source, path, content, request, rule)
            if series:
                if verdict != "VERIFIED":
                    ruled["series_refused"].append(f"{prompt_id}:{verdict}")
                continue
            if verdict != "VERIFIED":
                ruled["false_refusals"].append(f"{prompt_id}:{verdict}")
            for plant, planted in plants.items():
                if (verdict := outcome(source, path, content, planted, rule)) != "VERIFIED":
                    ruled[f"{plant}_false_refusals"].append(f"{prompt_id}:{verdict}")
            ruled["swaps_caught"] += sum(
                outcome(swap, path, content, request, rule) != "VERIFIED" for swap in swaps
            )
    result[language] = leg

prompts = {row["id"]: row["prompt"] for row in design["prompts"]}
capture = {"strict_changed": [], "strict_faithful_refused": []}
for line in (
    (REPO_ROOT / "corpus/python/captures/m10-design/records.ndjson").read_text().splitlines()
):
    record = json.loads(line) if line else None
    if record is None or record["kind"] != "design":
        continue
    prompt_id, name = record["prompt_id"], record["dataset_name"]
    _, source = defence(record["content"] or "")
    path = f"/mnt/uploads/{name}"
    verdict = verify.verify_python_source(source, declared_target=DatasetTarget(path, data[name]))
    base = "VERIFIED" if isinstance(verdict, verify.Verified) else verdict.code
    strict = outcome(source, path, data[name], prompts[prompt_id], "strict")
    task = intent.get(prompt_id)
    faithful = (
        isinstance(verdict, verify.Verified)
        and task is not None
        and "series_by" not in task
        and (verdict.spec.mark, verdict.spec.x.name, verdict.spec.y.name, verdict.spec.group)
        == (task["mark"], task["x"], task["y"], task["reduction"])
    )
    if strict != base:
        capture["strict_changed"].append(f"{prompt_id}:{base}->{strict}")
        if faithful:
            capture["strict_faithful_refused"].append(prompt_id)
result["capture"] = capture


def added(request, header):
    """The names A3's strict short-word tier adds over the shared matcher, aliases included."""
    try:
        shared = verify._anchors(request, header, ALIASES)[0]
        strict = verify._anchors(request, header, ALIASES, short_names=True)[0]
    except verify._AmbiguousTermError:
        return {"TIE"}
    return set(strict - shared)


def marked(label, names, wanted):
    return [f"{label}:{name}" + ("" if name in wanted else ":FALSE") for name in sorted(names)]


short = {"clinical": [], "clinical_false_refusals": [], "own": [], "noise": [], "suffix": []}
for number, task in enumerate(clinical["requests"], 1):
    wanted = {task["x"], task["y"]}
    short["clinical"] += marked(f"c{number:02}", added(task["request"], CLINICAL), wanted)
    source = program("c.csv", task["mark"], task["x"], task["y"], task["reduction"])
    for rule in ("strict", "substitution"):
        if (verdict := outcome(source, "c.csv", CLINICAL_CONTENT, task["request"], rule)) != (
            "VERIFIED"
        ):
            short["clinical_false_refusals"].append(f"c{number:02}:{rule}:{verdict}")
    for name, header in sorted(headers.items()):
        short["noise"] += marked(f"c{number:02}/{name}", added(task["request"], header), wanted)
    text = task["request"]
    if task["reduction"]:
        word, glue = (
            "ごと" if "ごと" in text else next(s for s in verify._SUFFIXES if s in text),
            "",
        )
    else:
        word, glue = task["x"], task["x"]
    for suffix in ("別", "毎", "次", "単位"):
        request = text.replace(word, glue + suffix)
        for name, header in [("clinical", CLINICAL), *sorted(headers.items())]:
            label = f"c{number:02}{suffix}/{name}"
            short["suffix"] += marked(label, added(request, header), wanted)
other = {"sales.csv": "weather.csv", "weather.csv": "sales.csv"}
for prompt_id, task in sorted(intent.items()):
    name, mapping = (
        simple[prompt_id]["dataset_name"],
        ja["headers"][simple[prompt_id]["dataset_name"]],
    )
    wanted = {mapping[task["x"]], mapping[task["y"]]} | (
        {mapping[task["series_by"]]} if "series_by" in task else set()
    )
    request = ja["prompts"][prompt_id]["ja"]
    short["own"] += marked(prompt_id, added(request, headers[name]), wanted)
    for label, header in (("other", headers[other[name]]), ("clinical", CLINICAL)):
        short["noise"] += marked(f"{prompt_id}/{label}", added(request, header), wanted)
result["a3"] = short

heldout = {prompt.id: prompt.prompt for _, prompt in load_corpus().rows()}
run_dir = REPO_ROOT / "corpus/python/captures" / score.HELDOUT_RUN
run, score_data = load_run(run_dir), score.load_data()


def regraded(anchoring):
    def row(record, data):
        if record.http_status != score._OK or record.content is None:
            return score._scored(record, "transport_error", None, None)
        target = DatasetTarget(
            "/mnt/uploads/" + record.dataset_name,
            data[record.dataset_name],
            heldout[record.prompt_id],
            anchoring,
            ALIASES,
        )
        verdict = verify.verify_python_source(defence(record.content)[1], declared_target=target)
        if not isinstance(verdict, verify.Verified):
            return score._scored(record, "refused", verdict.code, None)
        assert isinstance(verdict.spec, DatasetPlot)
        return score._scored(record, "verified", None, verdict.spec)

    with mock.patch.object(score, "_row", row):
        summary = score.score_run(run, score_data).summary
    return {
        "simple_verified": summary.simple.verified,
        "simple_total": summary.simple.total,
        "complicated_blocked": summary.complicated.blocked,
        "complicated_total": summary.complicated.total,
        "sentinels": summary.sentinels,
    }


result["h1"] = {rule: regraded(rule) for rule in ("substitution", "strict")}

for language in ("en", "ja", "ja_mixed"):
    leg = result[language]
    for rule in ("substitution", "strict"):
        ruled = leg[rule]
        print(
            f"{language} {rule}: false refusals {len(ruled['false_refusals'])}/{leg['faithful']}"
            f" {ruled['false_refusals']}; swaps caught {ruled['swaps_caught']}"
            f"/{leg['swaps_verified']}; plants stop {ruled['stop_false_refusals']}"
            f" negation {ruled['negation_false_refusals']}; series {ruled['series_refused']}"
        )
print(f"capture strict: {capture}")
falses = [name for leg in short.values() for name in leg if name.endswith(":FALSE")]
print(f"a3: false names {falses}; clinical false refusals {short['clinical_false_refusals']}")
print(f"a3: {json.dumps({k: len(v) for k, v in short.items()})}")
print(f"h1: {result['h1']}")
(HERE / "a4-result.json").write_text(
    json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
)
