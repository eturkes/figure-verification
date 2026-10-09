# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Live law cites tracked code by `path.py::symbol`, never by `path.py:<line>`.

A line number strands on the first edit above it, and nothing notices: one wave of edits left 16
of a law file's ranges pointing at the wrong code. A symbol citation survives edits and can be
decided, so this resolves each one against the cited file's top-level or class-level
definitions. Scope = `.claude/rules/*.md`. A cited path is tracked when it
equals a tracked `.py` path or is the `/`-suffix of one, and a symbol citation must name exactly
one; the upstream sources the rules quote (Open WebUI, transformers) match no tracked path
and stay line-cited.
"""

import ast
import functools
import re
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_LINE = re.compile(r"(?<![\w./-])([\w./-]+\.py):(\d+)")
# The member chain is captured whole: `Class.member.extra` fails instead of resolving its prefix.
_SYMBOL = re.compile(r"(?<![\w./-])([\w./-]+\.py)::([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)")


@functools.cache
def _tracked() -> tuple[str, ...]:
    return tuple(
        subprocess.run(
            ["git", "ls-files"],  # noqa: S607 - fixed literal argv
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
    )


def _scope() -> list[str]:
    return [
        name for name in _tracked() if name.startswith(".claude/rules/") and name.endswith(".md")
    ]


def _matches(cited: str) -> list[str]:
    """Every tracked `.py` path `cited` may name."""
    return [
        name
        for name in _tracked()
        if name.endswith(".py") and (name == cited or name.endswith(f"/{cited}"))
    ]


def _names(body: list[ast.stmt]) -> set[str]:
    names: set[str] = set()
    for node in body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.TypeAlias):
            names.add(node.name.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


@functools.cache
def _definitions(path: str) -> frozenset[str]:
    """Top-level names + `Class.member` for each class-level name of `path`."""
    tree = ast.parse((_ROOT / path).read_text(encoding="utf-8"))
    names = _names(tree.body)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            names.update(f"{node.name}.{member}" for member in _names(node.body))
    return frozenset(names)


def _findings(text: str) -> list[tuple[int, str]]:
    """`(line, problem)` for each tracked line citation + each unresolvable symbol citation."""
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        found += [
            (number, f"line citation {m.group(0)}")
            for m in _LINE.finditer(line)
            if _matches(m.group(1))
        ]
        for m in _SYMBOL.finditer(line):
            paths = _matches(m.group(1))
            if len(paths) != 1:
                found.append((number, f"{m.group(0)}: no single tracked path"))
            elif m.group(2) not in _definitions(paths[0]):
                found.append((number, f"{m.group(0)}: no such definition in {paths[0]}"))
    return found


def test_every_scoped_code_citation_is_a_resolvable_symbol() -> None:
    bad = [
        f"{name}:{line}: {problem}"
        for name in _scope()
        for line, problem in _findings((_ROOT / name).read_text(encoding="utf-8"))
    ]
    assert not bad, bad


def test_the_check_fires_on_planted_citations_and_passes_resolvable_ones() -> None:
    """Positive control: each planted fault is found on its own line; resolvable forms pass."""
    planted = (
        "intro\n"
        "see `src/verifier/figure/description.py::NoSuchSymbol`\n"
        "see `description.py:12`, `settings.py:5` and `settings.py::Settings`\n"
        "see `src/verifier/figure/description.py::Artist.site` + `description.py::Artist`\n"
        "see `src/verifier/figure/description.py::Artist.site.extra`\n"
        "upstream `utils/middleware.py:1102-1124` stays line-cited"
    )
    assert _findings(planted) == [
        (
            2,
            "src/verifier/figure/description.py::NoSuchSymbol: no such definition in "
            "src/verifier/figure/description.py",
        ),
        (3, "line citation description.py:12"),
        (3, "line citation settings.py:5"),
        (3, "settings.py::Settings: no single tracked path"),
        (
            5,
            "src/verifier/figure/description.py::Artist.site.extra: no such definition in "
            "src/verifier/figure/description.py",
        ),
    ]
    assert ".claude/rules/ops.md" in _scope()
