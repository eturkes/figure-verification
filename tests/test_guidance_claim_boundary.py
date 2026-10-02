# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The guidance claim boundary, decided over every tracked live file.

"The grammar enforces the guidance schema" is FALSE on every surface (`.claude/rules/claims.md`):
the grammar constrains generation TOWARD the schema, and strict re-decode is the sole admission
authority. The forbidden family is a phrase, so a tool decides it. The one admitted spelling is
the law's own negation: the phrase in quotes followed by `is FALSE`, or `never "..."`. Every
tracked file is read (an undecodable byte becomes U+FFFD) except two: archived records are history,
and this module plants the phrase in its own positive control.
"""

import re
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SELF = "tests/test_guidance_claim_boundary.py"
# Words part on any whitespace run: a Markdown line wrap must not hide the phrase.
_PHRASE = r"enforc\w*\s+the\s+guidance\s+schema|subset\s+xgrammar\s+supports"
_FAMILY = re.compile(_PHRASE, re.IGNORECASE)
# A match inside a quotation the law immediately negates: `"... phrase" is FALSE` or
# `never "... phrase"`.
_NEGATED = re.compile(
    rf"\"[^\"]{{0,200}}(?:{_PHRASE})\"\s+is\s+FALSE|never\s+\"[^\"]{{0,200}}(?:{_PHRASE})\"",
    re.IGNORECASE,
)


def _affirmations(text: str) -> list[int]:
    """Offsets of family matches that no admitted negation spans."""
    negated = [match.span() for match in _NEGATED.finditer(text)]
    return [
        match.start()
        for match in _FAMILY.finditer(text)
        if not any(start <= match.start() < end for start, end in negated)
    ]


def _live_files() -> list[str]:
    tracked = subprocess.run(
        ["git", "ls-files"],  # noqa: S607 - fixed literal argv
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return [name for name in tracked if not name.startswith(".agent/archive/") and name != _SELF]


def test_no_live_file_affirms_the_forbidden_guidance_claim() -> None:
    found: list[str] = []
    for name in _live_files():
        text = (_ROOT / name).read_bytes().decode("utf-8", errors="replace")
        found += [f"{name}:{text.count(chr(10), 0, at) + 1}" for at in _affirmations(text)]
    assert not found, found


def test_the_check_fires_on_an_affirmation_and_spares_the_negations() -> None:
    """Positive control, both ways: each planted affirmation is found, the law's forms are not."""
    assert len(_affirmations("The matcher enforces the guidance schema.")) == 1
    assert len(_affirmations("We ship the subset xgrammar supports.")) == 1
    assert _affirmations('"The grammar enforces the guidance schema" is FALSE.') == []
    assert _affirmations('Say never "the subset xgrammar supports".') == []
    assert len(_affirmations('"The grammar enforces the guidance schema" is true.')) == 1
    assert len(_affirmations("The grammar enforces the guidance\n  schema.")) == 1
    assert _affirmations('"The grammar enforces the\nguidance schema" is\nFALSE.') == []
