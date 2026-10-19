# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Mutation credit: poodle's default operators over the files ONE test imports or calls.

`CLAUDE.md` `Engineering`: a test pinning behavior that already passes counts once the
stack's mutation tool kills the mutants of its scope (default operators; scope = the files the test
imports or calls). poodle = that tool (research pass, queue row Q53): native AST, module-level
literals mutated, one copied tree per mutant, per-mutant JSON. Unlike `tools/mutate.py`
(hand-written mutants, each naming its red), this grades a test against operators nobody chose.

Steps, every one fail-closed:
1. Stage = a copy of the tracked + untracked-unignored files: the run reads the working tree, never
   `.git`, venvs or model weights.
2. Scope = every file of the repo's packages (`verifier`, `webui`, `model_backend`) holding a line
   the test executes, from one coverage run in the stage; a file measured outside it aborts.
3. poodle mutates the scope inside the stage. Each trial runs the one node from its own copied tree
   behind a canary plugin that exits 3 when a scope module imports from anywhere else: the editable
   `.pth` points at the primary `src`, and a trial over those bytes would credit unmutated code.
4. Verdict per mutant from its JSON record alone. poodle counts every nonzero rc but 1 as found (a
   collection error, a canary exit), so only pytest rc 1 (`Mutant Found`) kills; `Mutant Not Found`
   survives; anything else is ABNORMAL and credits nothing.

rc 0 = every mutant killed · 1 = complete, survivors listed · 2 = abnormal trials or no run.
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_PACKAGES = ("verifier", "webui", "model_backend")
_ROOTS = ("src/verifier/", "webui/", "model_backend/")
_CANARY = "_mutation_canary"
_CANARY_SOURCE = '''"""Exit 3 when a scope module imports from outside this trial's copied tree."""

import importlib.util
import os
from pathlib import Path

import pytest


def pytest_sessionstart(session: pytest.Session) -> None:
    # `find_spec` resolves without executing the module: `model_backend.engine` imports
    # `transformers`, which exists only as the fake its tests install at collection.
    here = Path.cwd().resolve()
    for name in os.environ["MUTATION_SCOPE_MODULES"].split():
        spec = importlib.util.find_spec(name)
        origin = Path((spec and spec.origin) or "").resolve()
        if not origin.is_relative_to(here):
            pytest.exit(f"mutation canary: {name} from {origin}, outside {here}", returncode=3)
'''
# `src` first: pytest inserts its `pythonpath` ahead of PYTHONPATH and the editable `.pth`.
_PYTEST = ("-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "pythonpath=src tests .")
_KILLED = "Mutant Found"
_SURVIVED = "Mutant Not Found"


class AbortError(Exception):
    """A run that can grade nothing: the message says why."""


def module_name(path: str) -> str:
    """`src/verifier/figure/inert.py` → `verifier.figure.inert`; `<pkg>/__init__.py` → `<pkg>`."""
    parts = list(Path(path).with_suffix("").parts)
    if parts[0] == "src":
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def classify(trials: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Each trial into `killed` | `survived` | `abnormal` by its own reason code."""
    verdicts: dict[str, list[dict[str, Any]]] = {"killed": [], "survived": [], "abnormal": []}
    for trial in trials:
        code = trial["result"]["reason_code"]
        verdict = "killed" if code == _KILLED else "survived" if code == _SURVIVED else "abnormal"
        verdicts[verdict].append(trial)
    return verdicts


def _stage(target: Path) -> None:
    listed = subprocess.run(
        ["/usr/bin/git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=_ROOT,
        capture_output=True,
        check=True,
    )
    for name in filter(None, listed.stdout.decode("utf-8").split("\0")):
        source = _ROOT / name
        if source.is_file():  # a deleted-but-tracked path lists too
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target / name)


def _scope(stage: Path, node: str) -> list[str]:
    report = stage / ".scope.json"
    # An empty config: the project's `[tool.coverage.report] include` keeps `verifier` alone.
    blank = stage / ".scope.coveragerc"
    blank.write_text("", "utf-8")
    covered = [f"--cov={package}" for package in _PACKAGES]
    command = [sys.executable, *_PYTEST, *covered, f"--cov-config={blank}"]
    command.append(f"--cov-report=json:{report}")
    run = subprocess.run(  # noqa: S603 - argv built from constants + the caller's node
        [*command, "--cov-fail-under=0", node], cwd=stage, capture_output=True, check=False
    )
    if run.returncode != 0:
        sys.stdout.write(run.stdout.decode("utf-8", "replace")[-2000:])
        message = f"scope run rc {run.returncode}: the test must pass unmutated"
        raise AbortError(message)
    files: dict[str, Any] = json.loads(report.read_text("utf-8"))["files"]
    scope = []
    for name, data in files.items():
        path = (stage / name).resolve()
        if not path.is_relative_to(stage.resolve()):
            message = f"scope run measured {path}, outside the stage"
            raise AbortError(message)
        relative = path.relative_to(stage.resolve()).as_posix()
        # Coverage measures the test modules beside the packages; the scope is the code under test.
        if data["executed_lines"] and relative.startswith(_ROOTS):
            scope.append(relative)
    if not scope:
        message = "scope run measured no package file"
        raise AbortError(message)
    return sorted(scope)


def _config(stage: Path, node: str, scope: list[str]) -> Path:
    """poodle reads TOML alone; a JSON string is a TOML basic string."""
    command = shlex.join([sys.executable, *_PYTEST, "-p", _CANARY, "--no-cov", node])
    modules = " ".join(map(module_name, scope))
    path = stage / "poodle.toml"
    path.write_text(
        "[poodle]\n"
        'source_folders = ["."]\n'
        f"only_files = {json.dumps(scope)}\n"
        "[poodle.runner_opts]\n"
        f"command_line = {json.dumps(command)}\n"
        "[poodle.runner_opts.command_line_env]\n"
        f"MUTATION_SCOPE_MODULES = {json.dumps(modules)}\n"
        "[poodle.reporter_opts]\n"
        "json_report_found = true\n",
        "utf-8",
    )
    return path


def _report(verdicts: dict[str, list[dict[str, Any]]]) -> list[str]:
    lines = [f"{name} {len(trials)}\n" for name, trials in verdicts.items()]
    for name in ("survived", "abnormal"):
        for trial in verdicts[name]:
            mutant, result = trial["mutant"], trial["result"]
            where = f"{mutant['source_file']}:{mutant['lineno']}:{mutant['col_offset']}"
            lines.append(f"\n{name.upper()} {where} {mutant['mutator_name']}\n")
            lines.append(mutant.get("unified_diff") or f"{mutant['text']}\n")
            if name == "abnormal":
                lines.append(f"{result['reason_code']}: {str(result['reason_desc'])[-600:]}\n")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mutate every file one test imports or calls, and list each surviving mutant."
    )
    parser.add_argument("node", help="one pytest node, e.g. tests/test_x.py::test_y")
    parser.add_argument("--workers", type=int, default=4, help="parallel trials (default 4)")
    parser.add_argument("--json", type=Path, help="also write poodle's full report here")
    args = parser.parse_args(argv)

    stage = Path(tempfile.mkdtemp(prefix="mutation-credit-"))
    try:
        _stage(stage)
        (stage / f"{_CANARY}.py").write_text(_CANARY_SOURCE, "utf-8")
        try:
            scope = _scope(stage, args.node)
        except AbortError as error:
            sys.stdout.write(f"ABORT: {error}\n")
            return 2
        sys.stdout.write(f"node {args.node}\nscope {len(scope)} files\n")
        sys.stdout.writelines(f"  {path}\n" for path in scope)
        report = stage / "poodle-report.json"
        config = _config(stage, args.node, scope)
        # poodle ships no `__main__`: its console script sits beside this interpreter.
        poodle = [str(Path(sys.executable).parent / "poodle"), "-c", str(config)]
        run = subprocess.run(  # noqa: S603 - argv built from constants + paths made here
            [*poodle, "-w", str(args.workers), "--json", str(report)],
            cwd=stage,
            env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
            capture_output=True,
            check=False,
        )
        if not report.is_file():
            sys.stdout.write(run.stdout.decode("utf-8", "replace")[-4000:])
            sys.stdout.write(run.stderr.decode("utf-8", "replace")[-4000:])
            sys.stdout.write(f"NO REPORT: poodle rc {run.returncode}\n")
            return 2
        results = json.loads(report.read_text("utf-8"))
        if args.json:
            shutil.copyfile(report, args.json)
        trials = results["mutant_trials"]
        verdicts = classify(trials)
        sys.stdout.writelines(_report(verdicts))
        if not trials or len(trials) != results["summary"]["trials"]:
            sys.stdout.write("INCOMPLETE: the report lists fewer trials than poodle ran\n")
            return 2
        if verdicts["abnormal"]:
            return 2
        return 1 if verdicts["survived"] else 0
    finally:
        shutil.rmtree(stage, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
