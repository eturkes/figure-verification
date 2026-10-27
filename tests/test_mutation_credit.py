# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""`tools/mutation_credit.py` end to end over a one-module project: each mutant lands on its node.

`ast` positions are UTF-8 byte offsets; poodle 1.3.4 splices its mutant text into the `str` line at
them, so on a line holding a non-ASCII character before the node the mutant lands elsewhere (a
SyntaxError trial, or another mutant than the one listed). This repository's sources hold Japanese
text, so the credit tool runs poodle with a byte-offset splice.

Grading = the mutation-testing-elements states (user ruling, code-review close): a timeout is
killed; a collection error whose traceback names the mutated file is INVALID (listed, outside the
credit); every other error stays ABNORMAL, rc 2.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_TOOL = Path(__file__).resolve().parents[1] / "tools" / "mutation_credit.py"
_GIT = shutil.which("git")
_MODULE = (
    'WORDS = ("ではなく", "じゃなく")\n\n\n'
    "def negated(text: str) -> bool:\n"
    "    return text.endswith(WORDS)\n"
)
_TEST = (
    "from verifier.words import negated\n\n\n"
    "def test_negated() -> None:\n"
    '    assert negated("月ではなく")\n'
    '    assert negated("日じゃなく")\n'
    '    assert not negated("年")\n'
)


def _project(root: Path, files: dict[str, str]) -> None:
    for name, text in {"src/verifier/__init__.py": "", **files}.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, "utf-8")
    (root / "tools").mkdir()
    shutil.copy2(_TOOL, root / "tools" / _TOOL.name)
    assert _GIT is not None, "git is absent from PATH"
    subprocess.run([_GIT, "init", "-q"], cwd=root, check=True)  # noqa: S603


def _credit(root: Path, node: str, report: Path) -> subprocess.CompletedProcess[str]:
    tool = str(root / "tools" / _TOOL.name)
    return subprocess.run(  # noqa: S603 - argv built from constants + paths made here
        [sys.executable, tool, node, "--workers", "2", "--json", str(report)],
        cwd=root,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def test_cr_r345_a_mutant_past_non_ascii_text_lands_on_its_own_node(tmp_path: Path) -> None:
    _project(tmp_path, {"src/verifier/words.py": _MODULE, "tests/test_words.py": _TEST})
    report = tmp_path / "report.json"
    run = _credit(tmp_path, "tests/test_words.py::test_negated", report)
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


def _trial(code: str, desc: str | None, source: str = "src/verifier/x.py") -> dict[str, Any]:
    return {"mutant": {"source_file": source}, "result": {"reason_code": code, "reason_desc": desc}}


_OTHER = "Other, See Description"
_FRAME = "_ ERROR collecting tests/test_x.py _\nsrc/verifier/x.py:3: in <module>\nE   TypeError: …"
_PARSE = (
    "_ ERROR collecting tests/test_x.py _\n"
    'E     File "/tmp/mutation-credit-a/.poodle-temp/run-7/src/verifier/x.py", line 3\n'
    "E   SyntaxError: invalid syntax"
)
_ELSEWHERE = (
    "_ ERROR collecting tests/test_x.py _\nsrc/verifier/y.py:9: in <module>\nE   TypeError: …"
)
_GRADES = (
    (_trial("Mutant Found", None), "killed"),
    (_trial("Trial Exceeded Timeout", "TimeoutExpired …"), "timeout"),
    (_trial("Mutant Not Found", None), "survived"),
    (_trial(_OTHER, _FRAME), "invalid"),
    (_trial(_OTHER, _PARSE), "invalid"),
    (_trial(_OTHER, _ELSEWHERE), "abnormal"),
    (_trial(_OTHER, _FRAME, source="src/verifier/w.py"), "abnormal"),
    (
        _trial(_OTHER, _FRAME + "\nExit: mutation canary: verifier.x from /usr, outside /tmp"),
        "abnormal",
    ),
    (_trial(_OTHER, "src/verifier/x.py:3: in run\nE   ValueError: …"), "abnormal"),
    (_trial(_OTHER, None), "abnormal"),
    (_trial("Mutant Error", _FRAME), "abnormal"),
)


def test_cr_r346_trials_grade_by_the_mutation_testing_elements_states() -> None:
    spec = importlib.util.spec_from_file_location("mutation_credit_r346", _TOOL)
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    graded = tool.classify([trial for trial, _ in _GRADES])
    assert {name: len(trials) for name, trials in graded.items()} == {
        "killed": 1,
        "timeout": 1,
        "survived": 1,
        "invalid": 2,
        "abnormal": 6,
    }
    for trial, grade in _GRADES:
        assert any(trial is graded_trial for graded_trial in graded[grade]), (trial, grade)


_TWICE = (
    "import functools\n\n\n"
    "@functools.lru_cache(maxsize=None)\n"
    "def twice(x: int) -> int:\n"
    "    return x * 2\n"
)


def test_cr_r346_a_mutant_that_breaks_the_import_is_invalid_not_abnormal(tmp_path: Path) -> None:
    test = (
        "from verifier.twice import twice\n\n\n"
        "def test_twice() -> None:\n"
        "    assert twice(3) == 6\n"
    )
    _project(tmp_path, {"src/verifier/twice.py": _TWICE, "tests/test_twice.py": test})
    run = _credit(tmp_path, "tests/test_twice.py::test_twice", tmp_path / "report.json")
    assert run.returncode in (0, 1), run.stdout[-3000:]
    lines = run.stdout.splitlines()
    assert "abnormal 0" in lines, run.stdout[-3000:]
    assert any(line.startswith("INVALID src/verifier/twice.py:4:") for line in lines), run.stdout


def test_git_absent_from_path_aborts_naming_it(tmp_path: Path) -> None:
    """git resolves through `PATH`, never a fixed location (user ruling, template refresh): with
    none there the tool stages nothing and aborts naming the cause, rc 2."""
    _project(tmp_path, {})
    run = subprocess.run(  # noqa: S603 - argv built from constants + paths made here
        [sys.executable, str(tmp_path / "tools" / _TOOL.name), "tests/test_none.py::test_none"],
        cwd=tmp_path,
        env={"PATH": str(tmp_path / "no-bin")},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert run.returncode == 2, run.stdout + run.stderr
    assert "ABORT: git is absent from PATH" in run.stdout.splitlines(), run.stdout
