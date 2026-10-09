# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Write the M16 harness input: every "Show checks" text plus the stub's expected PASS reply.

The PASS text is derived the way the outlet derives it, from the committed sentinel-simple program
the stub sends, verified over `data/sales.csv` at the path the sandbox uses.
"""

import json
import sys
from pathlib import Path

from model_backend.adapter import defence
from verifier.pysrc import DatasetTarget, Verified, verify_python_source
from webui.paste_in import checks
from webui.paste_in.filter import PASS_TEXT
from webui.paste_in.reasons import REASONS

root = Path(__file__).resolve().parents[2]
records = root / "corpus/python/captures/m10-design/records.ndjson"
sentinel = next(
    json.loads(line)["content"]
    for line in records.read_text().splitlines()
    if json.loads(line)["prompt_id"] == "sentinel-simple"
)
fenced, program = defence(sentinel)
if not fenced or not program:
    msg = "sentinel-simple capture has no Python program"
    raise ValueError(msg)
target = DatasetTarget("/mnt/uploads/sales.csv", (root / "data/sales.csv").read_bytes())
verdict = verify_python_source(program, declared_target=target)
if not isinstance(verdict, Verified):
    msg = f"sentinel-simple does not verify over data/sales.csv: {verdict}"
    raise TypeError(msg)
table = {
    "checks": checks.CHECKS,
    "texts": checks.TEXTS,
    "show": checks.SHOW,
    "hide": checks.HIDE,
    "unrun": checks.UNRUN,
    "marks": checks.MARKS,
    "reasons": REASONS,
    "pass_text": f"{PASS_TEXT}\n\n{verdict.certificate.interpretation}",
}
Path(sys.argv[1]).write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
