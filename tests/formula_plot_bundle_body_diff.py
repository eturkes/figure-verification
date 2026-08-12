# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""T39: compare the dataset validator body against baseline e432bd9."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SYMBOL = "_validate_bundle_contents"


def _source_segment(source: str) -> str:
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == _SYMBOL
    )
    return ast.get_source_segment(source, function) or ""


def _body(segment: str) -> str:
    lines = segment.splitlines(keepends=True)
    return "".join(lines[1:])


def main() -> None:
    candidate_source = (_ROOT / "src/verifier/service/archive.py").read_text()
    baseline_source = subprocess.run(
        ["git", "show", "e432bd9:src/verifier/service/archive.py"],  # noqa: S607 — fixed literal argv
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    baseline = _body(_source_segment(baseline_source))
    candidate = _body(_source_segment(candidate_source))
    if baseline != candidate:
        msg = "T39 dataset validator body differs from e432bd9"
        raise SystemExit(msg)
    positive_control = candidate.replace("Check canonical content", "Mutated canonical content", 1)
    if positive_control == baseline:
        msg = "T39 mutation positive control did not differ"
        raise SystemExit(msg)


if __name__ == "__main__":
    main()
