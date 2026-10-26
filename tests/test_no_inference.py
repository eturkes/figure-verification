# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""`Intent`: verification uses no inference -- every decision is a deterministic rule.

Two halves a tool decides. The judging core (`src/verifier` beside the reader, the one fact reporter
that loads matplotlib + pandas inside the sandbox) imports the standard library + `verifier` alone,
never by a dynamic import and never a source of randomness, so a model, a network client or a
sampled decision has no way in. And one description, judged twice in one interpreter and once in
each of two interpreters with different hash seeds, reaches the same verdict, published text
included: set or dict order cannot steer a decision.
"""

import ast
import os
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_CORE = _ROOT / "src" / "verifier"
_READER = _CORE / "figure" / "reader.py"
_CORPUS = _ROOT / "tests" / "figure_corpus"
_UNSEEDED = frozenset({"random", "secrets", "uuid"})


def _foreign_imports(source: str) -> list[str]:
    """Each import in `source` outside the standard library + `verifier`, each dynamic import and
    each source of randomness."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            found.append(node.module or "")
        elif (isinstance(node, ast.Attribute) and node.attr == "import_module") or (
            isinstance(node, ast.Name) and node.id == "__import__"
        ):
            found.append("<dynamic import>")
    allowed = sys.stdlib_module_names - _UNSEEDED | {"verifier", "__future__"}
    return [name for name in found if name.split(".")[0] not in allowed]


def test_the_judging_core_imports_the_standard_library_and_verifier_alone() -> None:
    sources = sorted(path for path in _CORE.rglob("*.py") if path != _READER)
    assert len(sources) > 20, sources
    foreign = {
        path.relative_to(_ROOT).as_posix(): names
        for path in sources
        if (names := _foreign_imports(path.read_text(encoding="utf-8")))
    }
    assert not foreign, f"the judging core reaches outside the standard library: {foreign}"


def test_a_model_library_a_dynamic_import_and_randomness_are_each_refused() -> None:
    """The control: each shape the closure check exists to refuse, refused."""
    for source, name in (
        ("import torch\n", "torch"),
        ("from transformers import pipeline\n", "transformers"),
        ("import importlib\nimportlib.import_module('x')\n", "<dynamic import>"),
        ("__import__('x')\n", "<dynamic import>"),
        ("import random\n", "random"),
        ("from secrets import choice\n", "secrets"),
    ):
        assert name in _foreign_imports(source), source
    assert _foreign_imports("import json\nfrom verifier.figure import judge\n") == []


def _sample() -> list[dict[str, Any]]:
    """Three corpus cases: a CSV pass, a typed-number pass, a block."""
    cases = [
        case
        for path in sorted(_CORPUS.glob("*.toml"))
        for case in tomllib.loads(path.read_text(encoding="utf-8"))["case"]
    ]
    picks: tuple[Callable[[dict[str, Any]], bool], ...] = (
        lambda case: case["expect"] == "pass" and "csv" in case,
        lambda case: case["expect"] == "pass" and "csv" not in case and "request" in case,
        lambda case: case["expect"] != "pass",
    )
    return [next(case for case in cases if pick(case)) for pick in picks]


_JUDGE_TWICE = """
import json, sys
from pathlib import Path
from verifier.figure import reader
from verifier.figure.description import parse_description
from verifier.figure.judge import Sources, judge

data, corpus = Path(sys.argv[1]), Path(sys.argv[2])
for case in json.loads(sys.stdin.read()):
    program = case["program"].replace("{data}", str(data)).replace("{corpus}", str(corpus))
    described = parse_description(reader.run(program))
    files = ()
    if "csv" in case:
        path = data / case["csv"]
        files = ((case["csv"], (path if path.is_file() else corpus / case["csv"]).read_bytes()),)
    sources = Sources(files, case.get("request"), case.get("anchoring", "strict"))
    first, second = judge(described, sources), judge(described, sources)
    assert first == second, (case["id"], first, second)
    print(repr(first))
"""


def test_one_description_reaches_one_verdict_under_any_hash_seed() -> None:
    import json  # noqa: PLC0415 - this test alone serializes the sample

    sample = json.dumps(_sample())
    runs = [
        subprocess.run(  # noqa: S603 - this interpreter on a fixed script
            [sys.executable, "-c", _JUDGE_TWICE, str(_ROOT / "data"), str(_CORPUS)],
            input=sample,
            env=os.environ | {"PYTHONHASHSEED": seed, "PYTHONPATH": str(_CORE.parent)},
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        ).stdout
        for seed in ("0", "1")
    ]
    assert runs[0].count("\n") == 3, runs[0]
    assert runs[0] == runs[1], "a verdict moved with the hash seed"
