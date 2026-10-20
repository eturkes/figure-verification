# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The human-facing text law over the check list + status lines (M16 C3, M18 E1, M15 D2, kept by
M19.5, less their word caps; `.claude/rules/human-facing.md`).

English printable ASCII with no character the embed or a same-origin frame would read as markup;
each Japanese title, cover, explanation, status line + UI word named below holds a kana letter
(`CODE` + the mark labels exempt). Length is a review judgment, never a count.
"""

import unicodedata

import pytest

from webui.paste_in import checks
from webui.paste_in.reasons import REASONS

_KANA = ("HIRAGANA LETTER", "KATAKANA LETTER", "HALFWIDTH KATAKANA LETTER")


def _law(text: str, *, japanese: bool, kana: bool = True) -> None:
    assert text
    assert not any(character in text for character in '<>&"\n')
    assert "Chart." not in text
    assert "x-" not in text
    if japanese:
        if kana:
            assert any(unicodedata.name(c, "").startswith(_KANA) for c in text), text
    else:
        assert all(" " <= character <= "~" for character in text), text


def _sentences(text: str) -> list[str]:
    return [part for part in text.removesuffix(".").split(". ") if part]


@pytest.mark.parametrize("check", checks.CHECKS)
def test_titles_and_covers_obey_the_law(check: str) -> None:
    rows = [checks.TEXTS[check]]  # type: ignore[index]
    if check == "columns":
        rows.append(checks.STRICT_COLUMNS)
    for pair in rows:
        for language, (title, covers) in enumerate(pair):
            _law(title, japanese=bool(language))
            _law(covers, japanese=bool(language))


@pytest.mark.parametrize("check", checks.CHECKS)
def test_explanations_obey_the_law(check: str) -> None:
    english, japanese = checks.EXPLAIN[check]  # type: ignore[index]
    _law(english, japanese=False)
    _law(japanese, japanese=True)
    assert all(len(sentence.split()) >= 1 for sentence in _sentences(english)), english


def test_ui_words_obey_the_law() -> None:
    names = ("SHOW", "HIDE", "WHAT", "CODE", "RELATED", "RAN", "NO_LINES", "WHY", "NOT_RUN")
    for name in (*names, "DREW", "GUIDE_LINK", "BEYOND", "ELIDED"):
        for language, text in enumerate(getattr(checks, name)):
            _law(text, japanese=bool(language), kana=name != "CODE")
    for _glyph, labels in checks.MARKS.values():
        for language, text in enumerate(labels):
            _law(text, japanese=bool(language), kana=False)


@pytest.mark.parametrize("reason", sorted(REASONS))
def test_status_lines_are_one_cause_and_at_most_one_fix(reason: str) -> None:
    english, japanese = REASONS[reason]  # type: ignore[index]
    _law(english, japanese=False)
    _law(japanese, japanese=True)
    assert english.endswith(".") and japanese.endswith("。")
    sentences = _sentences(english)
    assert 1 <= len(sentences) <= 2  # a cause, then at most one fix
    assert all(len(sentence.split()) >= 1 for sentence in sentences), english
