# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Write the M16 harness input: every "Show checks" text plus the stub's expected PASS reply.

The PASS text is derived the way the outlet derives it: the banner's `simple` program (the one the
stub sends) runs through the reader beside `data/sales.csv`, and the judge decides it with that file
and the arm's request under the demo's substitution anchoring.
"""

import contextlib
import json
import sys
import tempfile
from pathlib import Path

from verifier.figure import reader
from verifier.figure.description import parse_description
from verifier.figure.judge import Passed, Sources, judge
from webui.banner import load
from webui.paste_in import checks
from webui.paste_in.filter import PASS_TEXT
from webui.paste_in.reasons import REASONS

root = Path(__file__).resolve().parents[2]
arm = next(arm for arm in load().arms if arm.id == "simple")
content = (root / "data" / arm.dataset).read_bytes()
with tempfile.TemporaryDirectory() as scratch, contextlib.chdir(scratch):
    Path("uploads").mkdir()
    (Path("uploads") / arm.dataset).write_bytes(content)
    described = parse_description(reader.run(arm.program.replace("/mnt/uploads/", "uploads/")))
if described is None:
    msg = "the banner simple program yields no description"
    raise ValueError(msg)
verdict = judge(described, Sources(((arm.dataset, content),), arm.prompt, "substitution"))
if not isinstance(verdict, Passed):
    msg = f"the banner simple program does not pass over data/sales.csv: {verdict}"
    raise TypeError(msg)
table = {
    "checks": checks.CHECKS,
    "texts": checks.TEXTS,
    "show": checks.SHOW,
    "hide": checks.HIDE,
    "unrun": checks.UNRUN,
    "marks": checks.MARKS,
    "reasons": REASONS,
    "pass_text": f"{PASS_TEXT}\n\n{verdict.interpretation}",
}
Path(sys.argv[1]).write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
