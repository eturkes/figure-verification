# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""C1 host leg: every rule-corpus case as the production RPC code, plus its host verdict (M19.6).

`uv run --locked python .agent/measurements/c1_export.py` writes `c1-wrappers.json` (the
production `wrapper_code` per case, CSV paths under `/mnt/uploads`, no font: the corpus harness
runs without one, so `glyph_missing` stays reachable) and `c1-host.json` (each case's Sources + the
host verdict, matplotlib 3.9.4). `node c1_pyodide.mjs owui c1-0283.json` runs the wrappers in the
installed bundle; the C1 projector judges each bundle description with the same Sources.
"""

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
sys.path[:0] = [str(PROJECT / "src"), str(PROJECT)]

from verifier.figure import reader  # noqa: E402
from verifier.figure.description import parse_description  # noqa: E402
from verifier.figure.judge import Passed, Sources, judge  # noqa: E402
from webui.paste_in.sandbox import wrapper_code  # noqa: E402

CORPUS = PROJECT / "tests" / "figure_corpus"
DATA = PROJECT / "data"


def cases():
    for path in sorted(CORPUS.glob("*.toml")):
        yield from tomllib.loads(path.read_text(encoding="utf-8"))["case"]


def csv_bytes(name):
    path = DATA / name
    return (path if path.is_file() else CORPUS / name).read_bytes()


def verdict(described, case):
    files = () if "csv" not in case else ((case["csv"], csv_bytes(case["csv"])),)
    outcome = judge(described, Sources(files, case.get("request"), case.get("anchoring", "strict")))
    return "pass" if isinstance(outcome, Passed) else outcome.reason


def main():
    wrappers, host = {}, {}
    for case in cases():
        program = case["program"]
        sandboxed = program.replace("{data}", "/mnt/uploads").replace("{corpus}", "/mnt/uploads")
        local = program.replace("{data}", str(DATA)).replace("{corpus}", str(CORPUS))
        wrappers[case["id"]] = wrapper_code(sandboxed)
        described = parse_description(reader.run(local))
        host[case["id"]] = {
            "expect": case["expect"],
            "csv": case.get("csv"),
            "request": case.get("request"),
            "anchoring": case.get("anchoring", "strict"),
            "verdict": None if described is None else verdict(described, case),
        }
    (ROOT / "c1-wrappers.json").write_text(json.dumps(wrappers, sort_keys=True) + "\n")
    (ROOT / "c1-host.json").write_text(json.dumps(host, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"cases": len(host)}))


if __name__ == "__main__":
    main()
