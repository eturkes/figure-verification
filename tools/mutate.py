# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Mutation driver: proof that a suite's reds EXIST, not merely that its lines ran.

100% branch coverage answers "did this line execute", never "does a red exist for it". Every
kernel-tier predicate therefore earns a mutant that neuters its CONDITION -- never its message --
and the credit is a NAMED test reaching a different verdict under that mutant.

Committed rather than scratch-local because a claim backed by a validator that no longer exists is
not rerunnable: this driver is the whole difference between "13/13 killed" and folklore.

Attribution is by construction: a mutant declares the ONE test that must go red, and only that
test runs under it. A whole-suite run with `-x` would report whichever red came first, which is
how a mutant comes to be credited to a test that never covered it.

ANCHOR-MISS is reported apart from SURVIVED because from a distance both look like a kill's
absence for the same reason. It means the anchor was missing or not unique, so NOTHING was
mutated -- a refactor that moves a line lands here instead of silently passing. SURVIVED means the
neutered predicate changed behaviour and the named test did not notice: the finding.

The baseline runs first and must be green: a kill against an already-red suite proves nothing.

CPython invalidates cached bytecode on (mtime, size), so a SAME-SIZE restore silently reuses the
mutant code object -- every write here clears `__pycache__` under the source root.
"""

import argparse
import hashlib
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

_PYTEST = ("uv", "run", "--locked", "pytest", "-q", "--no-cov", "-p", "no:cacheprovider")


@dataclass(frozen=True, slots=True)
class Mutant:
    id: str
    predicate: str
    anchor: str
    mutant: str
    kills: str


@dataclass(frozen=True, slots=True)
class Catalogue:
    module: Path
    tests: tuple[str, ...]
    mutants: tuple[Mutant, ...]


class CatalogueError(Exception):
    """The catalogue is malformed. Never a verdict about the module under test."""


def _text(table: dict[str, object], key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        message = f"{where}: `{key}` must be a non-empty string"
        raise CatalogueError(message)
    return value


def load_catalogue(path: Path) -> Catalogue:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    tests = raw.get("tests")
    if not isinstance(tests, list) or not all(isinstance(item, str) for item in tests):
        message = f"{path}: `tests` must be a list of strings"
        raise CatalogueError(message)
    entries = raw.get("mutant")
    if not isinstance(entries, list) or not entries:
        message = f"{path}: at least one `[[mutant]]` is required"
        raise CatalogueError(message)
    mutants: list[Mutant] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            message = f"{path}: `mutant[{index}]` must be a table"
            raise CatalogueError(message)
        where = f"{path}: mutant[{index}]"
        mutants.append(
            Mutant(
                id=_text(entry, "id", where),
                predicate=_text(entry, "predicate", where),
                anchor=_text(entry, "anchor", where),
                mutant=_text(entry, "mutant", where),
                kills=_text(entry, "kills", where),
            )
        )
    ids = [item.id for item in mutants]
    if len(set(ids)) != len(ids):
        message = f"{path}: mutant ids must be unique"
        raise CatalogueError(message)
    return Catalogue(
        module=Path(_text(raw, "module", str(path))),
        tests=tuple(str(item) for item in tests),
        mutants=tuple(mutants),
    )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clear_caches(root: Path) -> None:
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def _run(selectors: tuple[str, ...]) -> int:
    return subprocess.run([*_PYTEST, *selectors], check=False).returncode  # noqa: S603


@dataclass(frozen=True, slots=True)
class Result:
    mutant: Mutant
    verdict: str


def _apply(module: Path, original: str, item: Mutant) -> str | None:
    """Write the mutated source, or return the reason nothing was written."""
    occurrences = original.count(item.anchor)
    if occurrences != 1:
        return f"anchor occurs {occurrences}x"
    mutated = original.replace(item.anchor, item.mutant)
    if mutated == original:
        return "mutant text equals anchor text"
    module.write_text(mutated, encoding="utf-8")
    return None


def _evaluate(catalogue: Catalogue, item: Mutant) -> Result:
    module = catalogue.module
    original = module.read_text(encoding="utf-8")
    before = _digest(module)
    try:
        reason = _apply(module, original, item)
        if reason is not None:
            return Result(item, f"ANCHOR-MISS ({reason})")
        _clear_caches(module.parent)
        verdict = "KILLED" if _run((item.kills,)) != 0 else "SURVIVED"
    finally:
        module.write_text(original, encoding="utf-8")
        _clear_caches(module.parent)
        after = _digest(module)
        if after != before:
            message = f"restore of {module} failed: {before} -> {after}"
            raise CatalogueError(message)
    return Result(item, verdict)


def _report(results: list[Result]) -> Iterator[str]:
    width = max(len(result.mutant.id) for result in results)
    for result in results:
        yield f"{result.mutant.id.ljust(width)}  {result.verdict}  {result.mutant.predicate}\n"
    killed = sum(result.verdict == "KILLED" for result in results)
    yield f"\n{killed}/{len(results)} killed\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a mutation catalogue against its suite.")
    parser.add_argument("catalogue", type=Path)
    parser.add_argument("--only", action="append", default=[], help="mutant id; repeatable")
    args = parser.parse_args(argv)

    catalogue = load_catalogue(args.catalogue)
    selected = [item for item in catalogue.mutants if not args.only or item.id in set(args.only)]
    if not selected:
        sys.stdout.write("no mutant matched --only\n")
        return 2

    # Vacuity guard: a kill against an already-red suite proves nothing at all.
    sys.stdout.write(f"baseline {' '.join(catalogue.tests)}\n")
    if _run(catalogue.tests) != 0:
        sys.stdout.write("VACUOUS: the suite is red before any mutation\n")
        return 2

    results = [_evaluate(catalogue, item) for item in selected]
    sys.stdout.writelines(_report(results))
    return 0 if all(result.verdict == "KILLED" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
