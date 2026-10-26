# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""`tools/mutation_credit.py` end to end over a one-module project: each mutant lands on its node.

`ast` positions are UTF-8 byte offsets; poodle 1.3.4 splices its mutant text into the `str` line at
them, so on a line holding a non-ASCII character before the node the mutant lands elsewhere (a
SyntaxError trial, or another mutant than the one listed). This repository's sources hold Japanese
text, so the credit tool runs poodle with a byte-offset splice.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_TOOL = Path(__file__).resolve().parents[1] / "tools" / "mutation_credit.py"
_MODULE = (
    'WORDS = ("ではなく", "じゃなく")\n\n\n'
    "def negated(text: str) -> bool:\n"
    "    return text.endswith(WORDS)\n"
)
_TEST = (
    "from verifier.words import negated\n\n\n"
    "def test_negated() -> None:\n"
    '    assert negated("赤ではなく")\n'
    '    assert negated("青じゃなく")\n'
    '    assert not negated("緑")\n'
)


def _project(root: Path) -> None:
    for name, text in {
        "src/verifier/__init__.py": "",
        "src/verifier/words.py": _MODULE,
        "tests/test_words.py": _TEST,
    }.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, "utf-8")
    (root / "tools").mkdir()
    shutil.copy2(_TOOL, root / "tools" / _TOOL.name)
    subprocess.run(["/usr/bin/git", "init", "-q"], cwd=root, check=True)


def test_cr_r345_a_mutant_past_non_ascii_text_lands_on_its_own_node(tmp_path: Path) -> None:
    _project(tmp_path)
    report = tmp_path / "report.json"
    node = "tests/test_words.py::test_negated"
    tool = str(tmp_path / "tools" / _TOOL.name)
    run = subprocess.run(  # noqa: S603 - argv built from constants + paths made here
        [sys.executable, tool, node, "--workers", "2", "--json", str(report)],
        cwd=tmp_path,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert run.returncode in (0, 1), run.stdout[-3000:]
    trials = json.loads(report.read_text("utf-8"))["mutant_trials"]
    codes = {trial["result"]["reason_code"] for trial in trials}
    assert codes <= {"Mutant Found", "Mutant Not Found"}, run.stdout[-3000:]
    # The diff comes from poodle's parent process, the verdict from the trial a worker spliced: a
    # misplaced second mutant appends a no-op `'XXじゃなくXX'` line, which survives.
    strings = {
        line[1:]: trial["result"]["reason_code"]
        for trial in trials
        if trial["mutant"]["mutator_name"] == "String"
        for line in trial["mutant"]["unified_diff"].splitlines()
        if line.startswith("+") and not line.startswith("+++")
    }
    assert strings == {
        "WORDS = ('XXではなくXX', \"じゃなく\")": "Mutant Found",
        "WORDS = (\"ではなく\", 'XXじゃなくXX')": "Mutant Found",
    }
