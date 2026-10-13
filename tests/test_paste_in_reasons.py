# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M19.5 O8: closed bilingual reason vocabulary; contract `.agent/archive/contracts/m19u5.md`."""

import unicodedata
from typing import get_args

import pytest

from outlet_support import ANCHORS, CAUSES, FIGURE_REASONS, REASON_CHECK, load, texts
from verifier.figure.reasons import FigureReason

_KANA = ("HIRAGANA LETTER", "KATAKANA LETTER", "HALFWIDTH KATAKANA LETTER")


def test_o8_reason_union_is_closed_and_disjoint() -> None:
    causes = set(get_args(load("reasons").OutletCause))
    figures = set(get_args(FigureReason))
    assert causes == CAUSES
    assert figures == FIGURE_REASONS
    assert len(causes) == 14 and len(figures) == 39
    assert causes.isdisjoint(figures)
    assert set(texts()) == set(REASON_CHECK)


@pytest.mark.parametrize("reason", sorted(REASON_CHECK))
def test_o8_every_reason_has_one_cause_and_at_most_one_fix(reason: str) -> None:
    pair = texts()[reason]
    assert len(pair) == 2
    english, japanese = pair
    assert english.isascii() and english.isprintable() and english.endswith(".")
    sentences = english[:-1].split(". ")
    assert 1 <= len(sentences) <= 2
    assert all(len(sentence.split()) >= 1 for sentence in sentences)
    assert japanese and japanese.endswith("。")
    # M15.1 D2: a kana letter, the mark the outlet's own language choice reads.
    assert any(unicodedata.name(char, "").startswith(_KANA) for char in japanese), japanese
    assert all("\n" not in text and "\r" not in text and "{" not in text for text in pair)


@pytest.mark.parametrize("reason", sorted(ANCHORS))
def test_o8_reason_anchors_are_exact(reason: str) -> None:
    assert texts()[reason] == ANCHORS[reason]
