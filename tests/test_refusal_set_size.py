# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The closed refusal set's SIZE has one owner: `typing.get_args(RefusalCode)`.

A size stated in prose reads like a live invariant while nothing checks it, and one stale count
survived a whole unit with every suite green. This decides every LIVE statement of the size in a
tracked file against the enumeration. As-of records are history, not law: `.agent/archive/**` and
the review ledger, which quotes stale counts in order to report them, stay out.
"""

import re
import subprocess
import typing
from pathlib import Path

from verifier.pysrc.errors import RefusalCode

_ROOT = Path(__file__).resolve().parents[1]
_AS_OF = (".agent/archive/", ".agent/review.md")
# The shapes a size statement takes in this repo: "the <n>-member refusal set", "all <n> refusal
# codes", "the closed refusal set is <n> members", "the unit's <n>-member invariant surface" --
# each read across a line wrap, since prose wraps wherever the column runs out.
_SIZE = re.compile(
    r"\b(\d+)-member\b[^.]{0,40}?(?:refusal|invariant\s+surface)"
    r"|\b(\d+)\s+refusal\s+codes\b"
    r"|\brefusal\s+set\s+is\s+(\d+)\b",
)


def _statements(text: str) -> list[tuple[int, int]]:
    """`(line, stated size)` for each size statement in `text`."""
    return [
        (text.count("\n", 0, match.start()) + 1, int(next(g for g in match.groups() if g)))
        for match in _SIZE.finditer(text)
    ]


def _text(path: Path) -> str:
    """Every tracked file is read: an undecodable byte turns into U+FFFD, never a skipped file."""
    return path.read_bytes().decode("utf-8", errors="replace")


def _live_files() -> list[str]:
    tracked = subprocess.run(
        ["git", "ls-files"],  # noqa: S607 - fixed literal argv
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return [name for name in tracked if not name.startswith(_AS_OF)]


def test_every_live_size_statement_equals_the_enumerated_refusal_set() -> None:
    size = len(set(typing.get_args(RefusalCode)))
    stale: list[str] = []
    for name in _live_files():
        stale += [
            f"{name}:{line}: {stated}"
            for line, stated in _statements(_text(_ROOT / name))
            if stated != size
        ]
    assert not stale, f"refusal-set size is {size}; stale statements: {stale}"


def test_the_check_reads_each_statement_shape_and_skips_as_of_records(tmp_path: Path) -> None:
    """Positive control: a planted `51-member` statement is found with its line; every shape the
    repo uses is read; the as-of records stay out of the sweep."""
    # Sizes ride f-string fields: as literals, this tracked file's own sweep would read the plants.
    planted = (
        f"intro\nthe {51}-member refusal set\nall {9} refusal codes; the refusal set is {7} members"
    )
    assert _statements(planted) == [(2, 51), (3, 9), (3, 7)]
    assert _statements(f"the unit's {52}-member invariant surface") == [(1, 52)]
    assert _statements(f"x\nall {8}\nrefusal codes; the {6}-member\n  refusal set") == [
        (2, 8),
        (3, 6),
    ]
    latin1 = tmp_path / "legacy.txt"
    latin1.write_bytes(b"caf\xe9\nthe " + str(51).encode() + b"-member refusal set\n")
    assert _statements(_text(latin1)) == [(2, 51)]
    live = _live_files()
    assert ".agent/review.md" not in live
    assert not any(name.startswith(".agent/archive/") for name in live)
    assert "tests/test_pysrc_accessor.py" in live
