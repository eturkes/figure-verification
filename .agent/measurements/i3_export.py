# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""I3 host leg: the reader's description of every I1 census program, plus each program's wrapper.

`uv run --locked python .agent/measurements/i3_export.py` writes `i3-host.json` (host descriptions,
matplotlib 3.9.4) and `i3-wrappers.json` (the production `wrapper_code` per program, its CSV paths
under `/mnt/uploads`), which `node i3_pyodide.mjs owui i3-0283.json` runs in the installed bundle.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
sys.path[:0] = [str(PROJECT / "src"), str(PROJECT), str(ROOT)]

from i1_census import programs  # noqa: E402 - the census owns the program list

from verifier.figure import reader  # noqa: E402
from webui.paste_in.sandbox import wrapper_code  # noqa: E402


def main():
    host = {
        name: reader.run(source).splitlines()[0]
        for name, source in programs(str(PROJECT / "data")).items()
    }
    wrappers = {name: wrapper_code(source) for name, source in programs("/mnt/uploads").items()}
    (ROOT / "i3-host.json").write_text(json.dumps(host, indent=1, sort_keys=True) + "\n")
    (ROOT / "i3-wrappers.json").write_text(json.dumps(wrappers, sort_keys=True) + "\n")
    print(json.dumps({"programs": len(host)}))


if __name__ == "__main__":
    main()
