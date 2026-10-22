# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q82.1 T12 + T14 (`.agent/contracts/q82.md`): the nucllei reasons and the markdown check list."""

from __future__ import annotations

import re
from typing import get_args

import pytest

from nucllei_skill.checks import CHECK_OF, EXPLAIN, TEXTS, checklist
from nucllei_skill.reasons import REASONS, ToolCause
from outlet_support import ORDER, REASON_GROUPS
from test_paste_in_texts import _law
from verifier.figure.reasons import FigureReason
from webui.paste_in.checks import Evidence

CAUSES = {
    "no_user": "program",
    "delegated_session": "program",
    "sandbox_unreachable": "run",
    "sandbox_timeout": "run",
    "sandbox_error": "run",
    "reply_malformed": "run",
    "no_description": "run",
    "verifier_error": "figure",
    "no_image": "attach",
    "publish_failed": "attach",
}
_MARKDOWN = re.compile(r"[*`\[\]<>\\|#]")
_ROW = re.compile(r"^- (\S) \*\*(.+?)\*\*", re.MULTILINE)


def test_q82_t14_the_reason_set_is_closed() -> None:
    assert set(get_args(ToolCause)) == set(CAUSES)
    assert set(REASONS) == set(CAUSES) | set(get_args(FigureReason))


def test_q82_t14_each_reason_maps_to_its_stage() -> None:
    figure = {
        reason: check
        for check, reasons in REASON_GROUPS.items()
        for reason in reasons
        if reason in get_args(FigureReason)
    }
    assert {**figure, **CAUSES} == CHECK_OF


@pytest.mark.parametrize("reason", sorted(set(CAUSES) | {"module_not_available"}))
def test_q82_t14_each_own_text_obeys_the_law_and_names_no_browser(reason: str) -> None:
    english, japanese = REASONS[reason]  # type: ignore[index]
    _law(english, japanese=False)
    _law(japanese, japanese=True)
    assert "browser" not in english.lower()
    assert "Open WebUI" not in english
    assert "ブラウザ" not in japanese


@pytest.mark.parametrize("check", ORDER)
def test_q82_t12_row_texts_obey_the_law_and_carry_no_markdown(check: str) -> None:
    for language in (0, 1):
        texts = (*TEXTS[check][language], EXPLAIN[check][language])  # type: ignore[index]
        for text in texts:
            _law(text, japanese=bool(language), kana=check != "attach" or language == 0)
            assert _MARKDOWN.search(text) is None, text
    assert "browser" not in " ".join(TEXTS[check][0]).lower()  # type: ignore[index]


def test_q82_t12_rows_after_the_failing_check_are_unrun() -> None:
    listed = checklist("axis_inverted", japanese=False, evidence=Evidence())
    rows = _ROW.findall(listed)
    passed, failed, unrun = "\N{CHECK MARK}", "\N{BALLOT X}", "\N{EN DASH}"
    assert [mark for mark, _ in rows] == [passed] * 4 + [failed] + [unrun] * 4
    assert listed.count("(not checked)") == 4
    assert listed.count("This check did not run, because an earlier check failed.") == 4
    assert "Why it failed: An axis is inverted. (axis_inverted)" in listed
    assert listed.count("/ext/public/figure-verification/checks.html#check-") == 9


def test_q82_t12_a_pass_lists_every_check_passed_in_japanese() -> None:
    listed = checklist(None, japanese=True, evidence=Evidence())
    assert [mark for mark, _ in _ROW.findall(listed)] == ["\N{CHECK MARK}"] * 9
    assert listed.startswith("**チェック項目**\n")
    assert listed.count("/ext/public/figure-verification/checks.ja.html#check-") == 9
    assert "プログラムはエラーなく最後まで実行されました。" in listed


def test_q82_t12_program_text_cannot_close_its_fence() -> None:
    program = "a = 1\nb = '```'\nc = '````'\nplot()\n"
    listed = checklist(
        "axis_inverted",
        japanese=False,
        evidence=Evidence(program, 4, (("axes", frozenset({2, 3, 4})),)),
    )
    fence = "`````"
    assert f"  {fence}\n" in listed
    assert "  ▶ 4 | plot()" in listed
    assert "▶ The marked line drew the part, or made the call, that failed this check." in listed


def test_q82_t12_the_program_row_points_at_the_call_and_never_lists_it() -> None:
    listed = checklist(None, japanese=False, evidence=Evidence("x = 1\nshow()\n", None))
    program_row = listed.split("- ✓ **Program run in the code sandbox**")[0]
    assert "x = 1" not in program_row
    assert "which the tool block shows above" in program_row


def test_q82_t12_a_failing_row_without_related_lines_lists_the_program() -> None:
    listed = checklist("program_error", japanese=False, evidence=Evidence("x = 1\nboom()\n", 2))
    assert "Program:" in listed
    assert "  ▶ 2 | boom()" in listed
