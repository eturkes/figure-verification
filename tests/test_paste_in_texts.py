# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The human-facing text law over the check list + status lines (M16 C3, M18 E1, M15 D2, kept by
M19.5; `.claude/rules/human-facing.md`).

Titles ≤ 10 words, covers ≤ 25, every English sentence ≤ 25 words; English printable ASCII with no
character the embed or a same-origin frame would read as markup; Japanese holds a kana letter.
"""

import unicodedata

import pytest

from webui.paste_in import checks
from webui.paste_in.reasons import REASONS

_KANA = ("HIRAGANA LETTER", "KATAKANA LETTER", "HALFWIDTH KATAKANA LETTER")


def _law(text: str, *, japanese: bool, words: int | None = None, kana: bool = True) -> None:
    assert text
    assert not any(character in text for character in '<>&"\n')
    assert "Chart." not in text
    assert "x-" not in text
    if japanese:
        if kana:
            assert any(unicodedata.name(c, "").startswith(_KANA) for c in text), text
    else:
        assert all(" " <= character <= "~" for character in text), text
        if words is not None:
            assert len(text.split()) <= words, text


def _sentences(text: str) -> list[str]:
    return [part for part in text.removesuffix(".").split(". ") if part]


@pytest.mark.parametrize("check", checks.CHECKS)
def test_titles_and_covers_obey_the_budget(check: str) -> None:
    rows = [checks.TEXTS[check]]  # type: ignore[index]
    if check == "columns":
        rows.append(checks.STRICT_COLUMNS)
    for pair in rows:
        for language, (title, covers) in enumerate(pair):
            _law(title, japanese=bool(language), words=10)
            _law(covers, japanese=bool(language), words=25)


@pytest.mark.parametrize("check", checks.CHECKS)
def test_explanations_obey_the_sentence_budget(check: str) -> None:
    english, japanese = checks.EXPLAIN[check]  # type: ignore[index]
    _law(english, japanese=False)
    _law(japanese, japanese=True)
    assert all(1 <= len(sentence.split()) <= 25 for sentence in _sentences(english)), english


def test_ui_words_obey_the_law() -> None:
    for name in ("SHOW", "HIDE", "WHAT", "CODE", "WHY", "NOT_RUN", "DREW", "SPEC", "BEYOND"):
        for language, text in enumerate(getattr(checks, name)):
            _law(text, japanese=bool(language), kana=name != "CODE")
            if not language:
                assert all(len(sentence.split()) <= 25 for sentence in _sentences(text))
    for _glyph, labels in checks.MARKS.values():
        for language, text in enumerate(labels):
            _law(text, japanese=bool(language), kana=False)


@pytest.mark.parametrize("reason", sorted(REASONS))
def test_status_lines_are_one_cause_and_at_most_one_fix(reason: str) -> None:
    english, japanese = REASONS[reason]  # type: ignore[index]
    _law(english, japanese=False)
    assert english.endswith(".") and japanese.endswith("。")
    sentences = _sentences(english)
    assert 1 <= len(sentences) <= 2  # a cause, then at most one fix
    assert all(1 <= len(sentence.split()) <= 25 for sentence in sentences), english
