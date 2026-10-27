# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Runs INSIDE the Open WebUI image: import each generated file, construct it, judge each arm, and
cut each test font with the filter's own stdlib cut (Q74), which needs no fontTools."""

import argparse
import hashlib
import importlib.util
import json
import platform
from pathlib import Path

parser = argparse.ArgumentParser(
    description="Import, construct and judge the generated files inside the Open WebUI image."
)
parser.add_argument("work", type=Path, help="the directory that holds the files and the arms")
work = parser.parse_args().work
arms = json.loads((work / "arms.json").read_text())
result = {
    "python": platform.python_version(),
    "fonttools": importlib.util.find_spec("fontTools") is not None,
    "imports": {},
    "verdicts": {},
    "cuts": {},
}
for pair in ("production", "demo"):
    filters = None
    for kind, cls in (("tool", "Tools"), ("filter", "Filter")):
        path = work / pair / f"figure_verification_{kind}.py"
        spec = importlib.util.spec_from_file_location(f"pasted_{pair}_{kind}", path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            instance = getattr(module, cls)()
            result["imports"][f"{pair}/{kind}"] = "ok"
        except Exception as exc:  # the failure IS the measurement
            result["imports"][f"{pair}/{kind}"] = f"{type(exc).__name__}: {exc}"
            continue
        if kind == "filter":
            filters = instance
    if filters is None:
        continue
    names = type(filters).outlet.__globals__
    verdicts = {}
    for arm in arms:
        content = (work / arm["dataset"]).read_bytes()
        sources = names["Sources"](
            ((arm["dataset"], content),), arm["prompt"], type(filters)._ANCHORING
        )
        verdict = names["judge"](names["parse_description"](arm["description"]), sources)
        verdicts[arm["id"]] = "pass" if isinstance(verdict, names["Passed"]) else verdict.reason
    result["verdicts"][pair] = verdicts
    cut_input = json.loads((work / "cut.json").read_text())
    contents = [(work / name).read_bytes() for name in cut_input["files"]]
    for font in cut_input["fonts"]:
        whole = (work / font).read_bytes()
        cut = names["cut_for"](whole, cut_input["program"], contents)
        result["cuts"].setdefault(font, {})[pair] = [hashlib.sha256(cut).hexdigest(), len(cut)]
print(json.dumps(result, sort_keys=True))
