# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The four register-bound operator READMEs stay inside the ASD-STE100 sentence budget.

`.claude/rules/human-facing.md` binds the shipped READMEs to ASD-STE100: at most 25 words per
descriptive sentence. Register is a judgment, but length is countable, so this check decides it:
every sentence outside fenced code, indented code, block quotations, tables and headings carries at
most 25 words, and each offender is named by `file:line`. Voice is a judgment no count decides;
the passive-pattern half reports the auxiliary + participle shapes the hand review rewrote, so a
new one fails here and is either rewritten or ruled active.
"""

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_READMES = ("README.md", "webui/README.md", "bench/README.md", "demo/README.md")
_MAX_WORDS = 25
_FENCE = re.compile(r"^\s*```")
# A fence closes only on a bare backtick run: ```"""` inside a fenced heredoc is content.
_FENCE_CLOSE = re.compile(r"^\s*```+\s*$")
_BULLET = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")
_CODE = re.compile(r"`[^`]*`")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# A sentence ends at a full stop, question or exclamation mark followed by space and a capital,
# digit or code span; a colon or semicolon continues the sentence, so it cannot split one in two.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`*\"(])")
_WORD = re.compile(r"[A-Za-z0-9][\w'\u2019./-]*")
_PASSIVE = re.compile(
    r"\b(?:is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?(\w+(?:ed|en|wn|lt|ut|un|ld))\b",
    re.IGNORECASE,
)
# Adjectives and nouns the participle shape over-reads; each is a predicate here, not a passive.
_NOT_PARTICIPLES = frozenset(
    {"open", "often", "then", "even", "seven", "between", "token", "hidden", "given", "unknown"}
)


def _units(text: str) -> list[tuple[int, str]]:
    """Prose units as `(first line, text)`: a paragraph, or one list item, with code stripped."""
    units: list[tuple[int, str]] = []
    fence = False
    start = 0
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            units.append((start, " ".join(buffer)))
            buffer.clear()

    for number, line in enumerate(text.splitlines(), 1):
        if (_FENCE_CLOSE if fence else _FENCE).match(line):
            flush()
            fence = not fence
            continue
        skipped = (
            fence
            or line.startswith(("    ", ">", "#", "|"))
            or line.count("|") >= 2  # a table row carries a cell delimiter pair
        )
        if skipped or not line.strip():
            flush()
            continue
        if _BULLET.match(line):
            flush()
        if not buffer:
            start = number
        buffer.append(_BULLET.sub("", line).strip())
    flush()
    return units


def _sentences(path: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for line, unit in _units((_ROOT / path).read_text(encoding="utf-8")):
        prose = _LINK.sub(r"\1", _CODE.sub("CODE", unit))
        found += [(f"{path}:{line}", sentence) for sentence in _SENTENCE_END.split(prose)]
    return found


def _passives(sentence: str) -> list[str]:
    return [
        match.group(0)
        for match in _PASSIVE.finditer(sentence)
        if match.group(1).lower() not in _NOT_PARTICIPLES
    ]


@pytest.mark.parametrize("path", _READMES)
def test_every_readme_sentence_is_at_most_25_words(path: str) -> None:
    long = [
        f"{where}: {len(_WORD.findall(sentence))} words: {sentence[:80]}"
        for where, sentence in _sentences(path)
        if len(_WORD.findall(sentence)) > _MAX_WORDS
    ]
    assert not long, long


@pytest.mark.parametrize("path", _READMES)
def test_no_readme_sentence_carries_a_passive_auxiliary_shape(path: str) -> None:
    passive = [
        f"{where}: {_passives(sentence)}: {sentence[:80]}"
        for where, sentence in _sentences(path)
        if _passives(sentence)
    ]
    assert not passive, passive


def test_the_checks_fire_on_a_long_and_a_passive_sentence(tmp_path: Path) -> None:
    """Positive control: a planted 26-word sentence and a planted passive each fail, by line."""
    planted = tmp_path / "README.md"
    planted.write_text(
        "# Title\n\n"
        + " ".join(["word"] * 26)
        + ".\n\n- The chart is drawn by the browser.\n\n"
        + " ".join(["word"] * 13)
        + ": "
        + " ".join(["Word"] * 13)
        + '.\n\n```sh\ncat <<EOF\n```"""\nEOF\n```\n\nAfter the fence.\n',
        encoding="utf-8",
    )
    units = _units(planted.read_text(encoding="utf-8"))
    assert [line for line, _ in units] == [3, 5, 7, 15]
    lengths = [len(_WORD.findall(text)) for _, text in units]
    assert lengths[0] > _MAX_WORDS
    assert _passives(units[1][1]) == ["is drawn"]
    assert [len(_WORD.findall(s)) for s in _SENTENCE_END.split(units[2][1])] == [26]
