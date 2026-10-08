# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""X6 (M17.3): the Japanese demo set, its CSV, the stub's replayed replies and the banner.

Contract: `.agent/archive/contracts/m17u3.md`.
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
import unicodedata

import pytest

from capture.corpus import CAPTURE_PROMPT_SHA256, banned_terms
from capture.harness import defence
from model_backend.models import ChatMessage
from paste_in_support import REPO_ROOT
from test_admin_docs import _BANNED_JA
from verifier.pysrc import Refused, Verified
from verifier.pysrc.budget import WorkBudget
from verifier.pysrc.csvread import NA_SPELLINGS, _read_csv
from verifier.pysrc.limits import DEFAULT_LIMITS
from webui import demo_ja, model_stub
from webui.paste_in import filter as filter_module
from webui.paste_in.demo_filter import Filter as DemoFilter
from webui.paste_in.filter import _needs_font
from webui.paste_in.owui_files import UploadedFile
from webui.paste_in.selection import first_verdict

_IDS = ("ja-sales-simple", "ja-sales-elaborate", "ja-clinic-simple", "ja-clinic-elaborate")
_SHELL = {
    "ja_simple_prompt": "ja-sales-simple",
    "ja_elaborate_prompt": "ja-sales-elaborate",
    "ja_clinic_simple_prompt": "ja-clinic-simple",
    "ja_clinic_elaborate_prompt": "ja-clinic-elaborate",
}
# The M15 harness's Japanese case: a kana request sent with no attachment, so no inlet rendering.
_M15_KANA = "地域ごとの売上を棒グラフにしてください。"


def _prompts() -> dict[str, demo_ja.DemoPrompt]:
    return {prompt.id: prompt for prompt in demo_ja.load().prompts}


def _upload(prompt: demo_ja.DemoPrompt) -> UploadedFile:
    content = (REPO_ROOT / "data" / prompt.dataset).read_bytes()
    return UploadedFile(file_id="f1", path=f"/mnt/uploads/{prompt.dataset}", content=content)


def _reply(user: str, *, selector: bool = True) -> str:
    system = "Available Tools: draw_figure" if selector else "Ordinary discussion."
    return model_stub._scripted_reply(
        (ChatMessage(role="system", content=system), ChatMessage(role="user", content=user))
    )


def _kana(text: str) -> bool:
    letters = ("HIRAGANA LETTER", "KATAKANA LETTER", "HALFWIDTH KATAKANA LETTER")
    return any(unicodedata.name(character, "").startswith(letters) for character in text)


def test_x6a_clinic_csv_reads_under_the_core_profile() -> None:
    """X6a: Japanese header, 9 rows, no pandas NA spelling, UTF-8 without BOM, LF-terminated."""
    raw = (REPO_ROOT / "data" / "clinic_ja.csv").read_bytes()
    header, rows = _read_csv(raw, DEFAULT_LIMITS, WorkBudget(DEFAULT_LIMITS.max_work))
    assert header == ("年月", "診療科", "患者数", "平均待ち時間")
    assert len(rows) == 9
    assert not any(cell in NA_SPELLINGS for row in rows for cell in row)
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.endswith(b"\n")
    assert b"\r" not in raw


def test_x6b_prompt_file_holds_four_captured_japanese_requests() -> None:
    """X6b: ids, datasets, capture provenance, kana, no banned term, a parseable program each."""
    demo = demo_ja.load()
    assert tuple(prompt.id for prompt in demo.prompts) == _IDS
    assert demo.capture is not None
    assert demo.capture.repo.capture_prompt_sha256 == CAPTURE_PROMPT_SHA256
    assert demo.capture.service.model_name == "Qwen2.5-Coder-0.5B-Instruct"
    assert demo.capture.temperature == 0.0
    assert demo.capture.max_tokens == 512
    assert demo_ja.encode(demo) == demo_ja.DEMO_JA.read_bytes()
    for prompt in demo.prompts:
        assert (REPO_ROOT / "data" / prompt.dataset).is_file()
        assert _kana(prompt.prompt), prompt.id
        assert banned_terms(prompt.prompt) == [], prompt.id
        assert [term for term in _BANNED_JA if term in prompt.prompt] == [], prompt.id
        assert prompt.content, prompt.id
        if prompt.expect == "pass":
            # A fail fixture may be unparseable: a tokenizer refusal is a valid block (X6e).
            _, program = defence(prompt.content)
            assert ast.parse(program).body, prompt.id
    assert {prompt.expect for prompt in demo.prompts} == {"pass", "fail"}


def test_x6b_japanese_stem_check_fires_on_a_planted_request() -> None:
    """X6b positive control: the Japanese stems catch what the English stems miss."""
    planted = "検証器が許可する棒グラフだけを作ってください。"
    assert banned_terms(planted) == []
    assert [term for term in _BANNED_JA if term in planted] == ["検証", "許可"]


def test_x6c_banner_assignments_equal_the_prompt_file() -> None:
    """X6c: each launcher shell assignment equals its Japanese prompt, byte for byte."""
    launch = (REPO_ROOT / "webui/launch.sh").read_text(encoding="utf-8")
    entries = re.findall(
        r"^(ja_(?:clinic_)?(?:simple|elaborate)_prompt)=\"([^\"\n]*)\"$", launch, re.MULTILINE
    )
    prompts = _prompts()
    assert dict(entries) == {name: prompts[prompt_id].prompt for name, prompt_id in _SHELL.items()}
    assert len(entries) == len(_SHELL)


@pytest.mark.parametrize("prompt_id", _IDS)
def test_x6d_rendering_equals_the_demo_inlet(
    prompt_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """X6d: the stub matches the exact user message the demo filter's inlet builds."""
    prompt = _prompts()[prompt_id]

    async def attached(_metadata: object, _user_id: str) -> tuple[UploadedFile, ...]:
        return (_upload(prompt),)

    monkeypatch.setattr(filter_module, "uploaded_files", attached)
    body: dict[str, object] = {"messages": [{"role": "user", "content": prompt.prompt}]}
    result = asyncio.run(DemoFilter().inlet(body, {"id": "u1"}, {"files": [{"id": "f1"}]}))
    assert result["messages"] == [{"role": "user", "content": demo_ja.rendered(prompt)}]


@pytest.mark.parametrize("prompt_id", _IDS)
@pytest.mark.parametrize(
    "prefix",
    ["Query: ", 'History:\nUSER: """Earlier Query: decoy"""\nASSISTANT: """prior"""\nQuery: '],
    ids=["fresh", "history"],
)
def test_x6d_stub_replays_each_captured_program(prompt_id: str, prefix: str) -> None:
    """X6d: one draw_figure call carrying the capture, de-fenced as the demo adapter does."""
    prompt = _prompts()[prompt_id]
    _, program = defence(prompt.content)
    reply = json.loads(_reply(prefix + demo_ja.rendered(prompt)))
    assert reply == {"tool_calls": [{"name": "draw_figure", "parameters": {"program": program}}]}


@pytest.mark.parametrize("prompt_id", _IDS)
@pytest.mark.parametrize("variation", ["unrendered", "rendered-with-suffix", "no-selector-system"])
def test_x6d_stub_keeps_japanese_near_misses_as_prose(prompt_id: str, variation: str) -> None:
    """X6d: unrendered, suffixed and non-selector turns get no scripted call."""
    prompt = _prompts()[prompt_id]
    if variation == "unrendered":
        reply = _reply("Query: " + prompt.prompt)
    elif variation == "rendered-with-suffix":
        reply = _reply("Query: " + demo_ja.rendered(prompt) + "\nextra")
    else:
        reply = _reply("Query: " + demo_ja.rendered(prompt), selector=False)
    assert "tool_calls" not in reply


def test_x6d_m15_kana_case_stays_prose() -> None:
    """X6d: the M15 harness's attachment-free kana request is never answered with a call."""
    assert "tool_calls" not in _reply("Query: " + _M15_KANA)


@pytest.mark.parametrize("prompt_id", _IDS)
def test_x6e_demo_selection_verdicts(prompt_id: str) -> None:
    """X6e: the demo's substitution selection verifies each pass prompt, refuses each fail one."""
    prompt = _prompts()[prompt_id]
    _, program = defence(prompt.content)
    upload = (_upload(prompt),)
    verdict, consumed = first_verdict(program, upload, prompt.prompt, "substitution", ())
    if prompt.expect == "pass":
        assert isinstance(verdict, Verified), verdict
        assert consumed is not None
        # Only the Japanese-header chart draws Japanese text, so only it carries the M17.1 font.
        assert _needs_font(verdict, consumed) is (prompt.dataset == "clinic_ja.csv")
    else:
        assert isinstance(verdict, Refused), verdict
