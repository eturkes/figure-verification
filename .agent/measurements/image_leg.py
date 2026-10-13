# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Runs INSIDE the Open WebUI image: import each generated file, construct it, judge each arm."""

import importlib.util
import json
import platform
import sys
from pathlib import Path

work = Path(sys.argv[1])
arms = json.loads((work / "arms.json").read_text())
result = {"python": platform.python_version(), "imports": {}, "verdicts": {}}
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
print(json.dumps(result, sort_keys=True))
