# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M14: the administrator guide ships in English AND Japanese, and the two say the same thing.

Prose equivalence is a judgment; what a tool CAN decide is pinned here: both guides name the same
identifiers (files, item ids, settings, commands), keep the same section/step/table shape, carry the
two verdict strings byte for byte, and cite only files that exist. The system prompts are
MODEL-facing, so ruling 6 binds them instead: task + format + the `draw_figure` transport, no
admission vocabulary in either language.
"""

import re
from pathlib import Path

import pytest

from capture.corpus import banned_terms
from webui.paste_in.filter import FAIL_TEXT, FILTER_ID, PASS_TEXT
from webui.settings import Settings

_ROOT = Path(__file__).resolve().parents[1]
_ADMIN = _ROOT / "docs" / "admin"
_GUIDES = ("README.md", "README.ja.md")
_PROMPTS = ("system_prompt.en.txt", "system_prompt.ja.txt")
_SPAN = re.compile(r"`([^`\n]+)`")
_IDENTIFIER = re.compile(r"[A-Za-z0-9_./-]+")
# Every identifier an administrator must type or find, hand-stated: a guide that drops one fails.
_REQUIRED = frozenset(
    {
        "paste-in/figure_verification_tool.py",
        "paste-in/figure_verification_filter.py",
        "figure_verification",
        "figure_verification_filter",
        "system_prompt.en.txt",
        "system_prompt.ja.txt",
        "ENABLE_CODE_EXECUTION",
        "ENABLE_CODE_INTERPRETER",
        "ENABLE_API_OUTLET_FILTERS",
        "BYPASS_EMBEDDING_AND_RETRIEVAL",
        "data/sales.csv",
    }
)
# Japanese renderings of the admission vocabulary ruling 6 bans (capture.corpus._BANNED_STEMS):
# verification, permit/allow, forbid, refuse/reject, restrict, sandbox, support, block, policy.
_BANNED_JA = (
    "検証",
    "許可",
    "禁止",
    "拒否",
    "拒絶",
    "制限",
    "サンドボックス",
    "サポート",
    "ブロック",
    "ポリシー",
)


def _text(name: str) -> str:
    return (_ADMIN / name).read_text(encoding="utf-8")


def _identifiers(name: str) -> set[str]:
    return {span for span in _SPAN.findall(_text(name)) if _IDENTIFIER.fullmatch(span)}


def test_both_guides_name_the_same_identifiers() -> None:
    english, japanese = (_identifiers(name) for name in _GUIDES)
    assert english == japanese
    assert english >= _REQUIRED


def test_both_guides_keep_the_same_shape() -> None:
    def shape(name: str) -> tuple[int, int, int]:
        text = _text(name)
        return (
            len(re.findall(r"^## ", text, re.MULTILINE)),
            len(re.findall(r"^\d+\. ", text, re.MULTILINE)),
            len(re.findall(r"^\|", text, re.MULTILINE)),
        )

    assert shape(_GUIDES[0]) == shape(_GUIDES[1])


@pytest.mark.parametrize("name", _GUIDES)
def test_each_guide_carries_both_verdicts_and_the_provisioned_ids(name: str) -> None:
    text = _text(name)
    assert f"`{PASS_TEXT}`" in text
    assert f"`{FAIL_TEXT}`" in text
    assert f"`{FILTER_ID}`" in text
    assert f"`{Settings.from_env().tool_id}`" in text


@pytest.mark.parametrize("name", _GUIDES)
def test_each_cited_repository_file_exists(name: str) -> None:
    cited = {span for span in _identifiers(name) if "/" in span or span.endswith((".txt", ".md"))}
    missing = sorted(
        span for span in cited if not ((_ROOT / span).exists() or (_ADMIN / span).is_file())
    )
    assert not missing, missing


@pytest.mark.parametrize("name", _PROMPTS)
def test_each_system_prompt_names_the_transport_and_no_admission_vocabulary(name: str) -> None:
    text = _text(name)
    for needle in ("draw_figure", "program", "/mnt/uploads/", "plt.show()"):
        assert needle in text, needle
    assert banned_terms(text) == []
    assert [term for term in _BANNED_JA if term in text] == []
