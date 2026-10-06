# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M15.1 D1-D8: contract-derived outlet causes, fixed verdicts and bounded diagnostics.

Contract: `.agent/archive/contracts/m15u1.md`. Reason codes, language and event shapes are
independent; REASONS supplies sentence bytes only, with four separately pinned bilingual anchors.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import unicodedata
from collections.abc import Awaitable
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import ModuleType
from typing import Literal, cast, get_args

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from filter_checks_support import embed_event, normalized_events
from observe_support import formula_verdict, observation_for, stdout_for, stdout_for_verified
from paste_in_support import (
    StoredFile,
    assert_filter_text,
    fake_open_webui,
    filter_body,
    invoke_filter,
    load_filter_module,
    recorded_request,
    valid_png_uri,
)
from verifier.pysrc import DatasetTarget, Refused, Verified, verify_python_source
from verifier.pysrc.errors import RefusalCode
from verifier.pysrc.request import formula_target

_FAIL = "Figure verification failed, no image produced"
_LOGGER = "webui.paste_in.filter"
_REQUEST = "y = sin(x), x in [0, 1], n = 3"
_PROGRAM = (
    "import numpy as np\n"
    "import matplotlib.pyplot as plt\n"
    "x = np.linspace(0, 1, num=3)\n"
    "y = np.sin(x)\n"
    "plt.plot(x, y)\n"
    "plt.show()\n"
)
_CAUSES = {
    "no_tool_call",
    "no_user",
    "no_target",
    "no_browser",
    "browser_timeout",
    "browser_error",
    "browser_no_answer",
    "reply_malformed",
    "sandbox_unavailable",
    "sandbox_error",
    "no_image",
    "no_observation",
    "observation_mismatch",
    "publish_failed",
}
_KANA_PREFIXES = ("HIRAGANA LETTER", "KATAKANA LETTER", "HALFWIDTH KATAKANA LETTER")


def _texts() -> dict[str, tuple[str, str]]:
    module = importlib.import_module("webui.paste_in.reasons")
    assert isinstance(module.REASONS, dict)
    return cast(dict[str, tuple[str, str]], module.REASONS)


def _status(reason: str, language: Literal[0, 1] = 0) -> dict[str, object]:
    return {
        "type": "status",
        "data": {"description": f"{_texts()[reason][language]} ({reason})", "done": True},
    }


def _files() -> dict[str, object]:
    return {"type": "files", "data": {"files": [{"type": "image", "url": valid_png_uri()}]}}


def _expected_pass() -> str:
    target = formula_target(_REQUEST)
    assert target is not None
    verdict = verify_python_source(_PROGRAM, declared_target=target)
    assert isinstance(verdict, Verified)
    return "Figure verification passed\n\n" + verdict.certificate.interpretation


def _records(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str]]:
    return [
        (record.levelno, record.getMessage())
        for record in caplog.records
        if record.name == _LOGGER and record.levelno >= logging.INFO
    ]


def _assert_log(caplog: pytest.LogCaptureFixture, reason: str) -> None:
    assert _records(caplog) == [(logging.INFO, f"figure verification failed reason={reason}")]


@dataclass(frozen=True)
class _Case:
    name: str
    reason: str
    rpc_count: int = 0
    receipt: bool = True
    program: str = _PROGRAM
    request_text: str | None = _REQUEST
    user: dict[str, object] | None = field(default_factory=lambda: dict[str, object](id="owner"))
    metadata: dict[str, object] | None = field(
        default_factory=lambda: dict[str, object](session_id="session")
    )
    rpc: Literal["returns", "raises", "timeout", "absent"] = "returns"
    reply: str = "good"
    emitter: bool = True
    publish_fails: bool = False


_CASES = (
    _Case("01-no-receipt", "no_tool_call", receipt=False),
    _Case("02-no-user", "no_user", user=None),
    _Case("02-missing-user-id", "no_user", user={}),
    _Case("02-non-string-user-id", "no_user", user={"id": 7}),
    _Case("03-no-target", "no_target", request_text=None),
    _Case("04-import-refusal", "import_not_admitted", program="import os\n"),
    _Case("04-call-refusal", "call_target_not_admitted", program="print('not a chart')\n"),
    _Case("05-no-rpc", "no_browser", rpc="absent"),
    _Case("05-no-emitter", "no_browser", emitter=False),
    _Case("05-no-metadata", "no_browser", metadata=None),
    _Case("05-no-session", "no_browser", metadata={}),
    _Case("06-timeout", "browser_timeout", 1, rpc="timeout"),
    _Case("07-rpc-error", "browser_error", 1, rpc="raises"),
    _Case("08-caller-error", "browser_no_answer", 1, reply="caller-error"),
    _Case("08-caller-null-error", "browser_no_answer", 1, reply="caller-null-error"),
    _Case("09-non-dict", "reply_malformed", 1, reply="non-dict"),
    _Case("09-no-keys", "reply_malformed", 1, reply="no-keys"),
    _Case("09-no-stderr", "reply_malformed", 1, reply="no-stderr"),
    _Case("09-false-stderr", "reply_malformed", 1, reply="false-stderr"),
    _Case("09-zero-stderr", "reply_malformed", 1, reply="zero-stderr"),
    _Case("09-list-stderr", "reply_malformed", 1, reply="list-stderr"),
    _Case("09-dict-stderr", "reply_malformed", 1, reply="dict-stderr"),
    _Case("10-chromium-loader", "sandbox_unavailable", 1, reply="chromium-loader"),
    _Case("10-webkit-loader", "sandbox_unavailable", 1, reply="webkit-loader"),
    _Case("11-sandbox", "sandbox_error", 1, reply="sandbox"),
    _Case("11-traceback-loader", "sandbox_error", 1, reply="traceback-loader"),
    _Case("11-whitespace-stderr", "sandbox_error", 1, reply="whitespace-stderr"),
    _Case("11-error-and-stderr", "sandbox_error", 1, reply="error-and-stderr"),
    _Case("12-no-image", "no_image", 1, reply="no-image"),
    _Case("12-non-string-stdout", "no_image", 1, reply="non-string-stdout"),
    _Case("12-two-images", "no_image", 1, reply="two-images"),
    _Case("12-invalid-png", "no_image", 1, reply="invalid-png"),
    _Case("13-no-observation", "no_observation", 1, reply="no-observation"),
    _Case("13-bad-observation", "no_observation", 1, reply="bad-observation"),
    _Case("14-mismatching-observation", "observation_mismatch", 1, reply="mismatch"),
    _Case("15-publish-error", "publish_failed", 1, publish_fails=True),
)
_BY_NAME = {case.name: case for case in _CASES}


def _reply(kind: str) -> object:
    uri = valid_png_uri()
    verified = formula_verdict()
    good = stdout_for_verified(verified, uri)
    observation = observation_for(verified)
    observation["lines"][0][0][1] = (99.0).hex()
    replies: dict[str, object] = {
        "good": {"stdout": good, "stderr": ""},
        "null-stderr": {"stdout": good, "stderr": None},
        "error-clean-stderr": {"error": "ignored", "stdout": good, "stderr": ""},
        "caller-error": {"error": "session gone", "stdout": good},
        "caller-null-error": {"error": None},
        "non-dict": [uri],
        "no-keys": {},
        "no-stderr": {"stdout": good},
        "false-stderr": {"stdout": good, "stderr": False},
        "zero-stderr": {"stdout": good, "stderr": 0},
        "list-stderr": {"stdout": good, "stderr": []},
        "dict-stderr": {"stdout": good, "stderr": {}},
        "chromium-loader": {"stderr": "loadPyodide is not defined", "stdout": good},
        "webkit-loader": {"stderr": "Can't find variable: loadPyodide", "stdout": good},
        "sandbox": {"stderr": "an upload failed", "stdout": good},
        "traceback-loader": {
            "stderr": "Traceback (most recent call last):\nNameError: loadPyodide\n",
            "stdout": good,
        },
        "whitespace-stderr": {"stderr": " ", "stdout": good},
        "error-and-stderr": {"error": "caller", "stderr": "sandbox", "stdout": good},
        "no-image": {"stdout": stdout_for_verified(verified, ""), "stderr": ""},
        "non-string-stdout": {"stdout": None, "stderr": ""},
        "two-images": {"stdout": f"{good}\n{uri}", "stderr": ""},
        "invalid-png": {"stdout": "data:image/png;base64,!!!!", "stderr": ""},
        "no-observation": {"stdout": uri, "stderr": ""},
        "bad-observation": {
            "stdout": "FIGURE_VERIFICATION_OBSERVATION:{invalid-json\n" + uri,
            "stderr": "",
        },
        "mismatch": {"stdout": stdout_for(observation) + uri, "stderr": ""},
    }
    return replies[kind]


def _exercise(
    case: _Case,
    module: ModuleType,
    *,
    status_mode: Literal["normal", "raises", "pending", "cancelled"] = "normal",
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]], list[bool]]:
    calls: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    completed: list[bool] = []

    async def rpc(payload: dict[str, object]) -> object:
        calls.append(payload)
        if case.rpc == "raises":
            error = "RPC_EXCEPTION_SENTINEL"
            raise ValueError(error)
        if case.rpc == "timeout":
            await asyncio.sleep(0.04)
        return _reply(case.reply)

    async def emit(event: dict[str, object]) -> None:
        events.append(event)
        if event["type"] == "files" and case.publish_fails:
            error = "FILES_EXCEPTION_SENTINEL"
            raise OSError(error)
        if event["type"] == "status":
            if status_mode == "raises":
                error = "STATUS_EXCEPTION_SENTINEL"
                raise RuntimeError(error)
            if status_mode == "cancelled":
                raise asyncio.CancelledError
            if status_mode == "pending":
                await asyncio.sleep(0.04)
                completed.append(True)

    body = filter_body("MODEL_REPLY_SENTINEL")
    with fake_open_webui([], Path(__file__).parent):
        result = invoke_filter(
            module,
            body,
            request=(
                recorded_request(case.program, request_text=case.request_text)
                if case.receipt
                else None
            ),
            user=case.user,
            metadata=case.metadata,
            event_call=None if case.rpc == "absent" else rpc,
            event_emitter=emit if case.emitter else None,
        )
    assert result is body
    return result, calls, events, completed


def test_d1_reason_key_set_is_every_refusal_code_plus_the_fourteen_outlet_causes() -> None:
    """D1: exact 54 + 14 key union and disjoint OutletCause alias, not a production-derived list."""
    texts = _texts()
    alias = importlib.import_module("webui.paste_in.reasons").OutletCause
    causes = set(get_args(getattr(alias, "__value__", alias)))
    refusals = set(get_args(RefusalCode))
    assert causes == _CAUSES
    assert len(causes) == 14
    assert len(refusals) == 54
    assert causes.isdisjoint(refusals)
    assert set(texts) == refusals | _CAUSES


@pytest.mark.parametrize("reason", sorted(_CAUSES | set(get_args(RefusalCode))))
def test_d2_every_reason_text_obeys_the_text_law(reason: str) -> None:
    """D2: exhaust the finite dictionary domain, including language-specific line widths."""
    value: object = _texts()[reason]
    assert isinstance(value, tuple) and len(value) == 2
    pair = cast(tuple[str, str], value)
    english, japanese = pair
    assert english.isascii() and english.isprintable() and english.endswith(".")
    # A sentence ends at `. `; the dot inside a code name such as `plt.show()` ends nothing.
    sentences = english[:-1].split(". ")
    assert (
        1 <= len(sentences) <= (2 if reason in {"sandbox_unavailable", "browser_no_answer"} else 1)
    )
    assert all(1 <= len(sentence.split()) <= 25 for sentence in sentences)
    assert japanese.endswith("。")
    assert any(unicodedata.name(char, "").startswith(_KANA_PREFIXES) for char in japanese)
    for sentence in pair:
        assert not any(char in sentence for char in "\n{}")
        text = f"{sentence} ({reason})"
        assert (
            sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in text)
            <= 100
        )


@pytest.mark.parametrize(
    ("reason", "english", "japanese"),
    [
        (
            "no_tool_call",
            "The model did not send a chart program.",
            "モデルからグラフのプログラムが届きませんでした。",
        ),
        (
            "sandbox_unavailable",
            "The browser could not load Pyodide. Turn off the ad blocker for this site.",
            "Pyodide を読み込めません。このサイトの広告ブロッカーをオフにしてください。",
        ),
        (
            "call_target_not_admitted",
            "The program calls a function that the verifier does not accept.",
            "検証器が受け入れない関数が呼び出されています。",
        ),
        (
            "observation_mismatch",
            "The drawn values differ from the recomputed values.",
            "描画された値が再計算した値と一致しません。",
        ),
    ],
)
def test_d2_anchor_texts_are_byte_exact(reason: str, english: str, japanese: str) -> None:
    assert _texts()[reason] == (english, japanese)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case.name)
def test_d3_each_arm_yields_its_reason_and_the_fixed_fail_verdict(
    case: _Case, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """D3/D4/D6: every arm pins both verdict surfaces, RPC count, complete events and log list."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    module = load_filter_module()
    if case.rpc == "timeout":
        monkeypatch.setattr(module, "RPC_TIMEOUT_SECONDS", 0.001)
    result, calls, events, _completed = _exercise(case, module)
    assert_filter_text(result, _FAIL)
    assert len(calls) == case.rpc_count
    _assert_log(caplog, case.reason)
    expected = [_files()] if case.publish_fails else []
    if case.emitter:
        expected.extend([_status(case.reason), embed_event(case.reason, case.metadata)])
    assert normalized_events(events) == expected


@pytest.mark.parametrize("reply", ["good", "null-stderr", "error-clean-stderr"])
def test_d4_one_status_event_per_fail_and_none_on_pass(
    reply: str, caplog: pytest.LogCaptureFixture
) -> None:
    """D4/D6: PASS remains one image, exact interpretation and no status or INFO+ record."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    result, calls, events, _completed = _exercise(
        _Case("pass", "", 1, reply=reply), load_filter_module()
    )
    assert_filter_text(result, _expected_pass())
    assert len(calls) == 1
    assert normalized_events(events) == [_files(), embed_event(None)]
    assert _records(caplog) == []


_LANGUAGE_CASES: tuple[tuple[dict[str, object] | None, Literal[0, 1]], ...] = (
    (None, 0),
    ({}, 0),
    ({"user_message": {}}, 0),
    ({"user_message": {"content": None}}, 0),
    ({"user_message": {"content": ["かな"]}}, 0),
    ({"user_message": {"content": 1}}, 0),
    ({"user_message": {"content": ""}}, 0),
    ({"user_message": {"content": "English request"}}, 0),
    ({"user_message": {"content": "漢字"}}, 0),
    ({"user_message": {"content": "漢字・漢字ー"}}, 0),
    ({"user_message": {"content": "゙゚゛゜ゝゞ・ー･ｰﾞﾟ"}}, 0),
    ({"user_message": {"content": "あ"}}, 1),
    ({"user_message": {"content": "カ"}}, 1),
    ({"user_message": {"content": "ｶ"}}, 1),
    ({"user_message": {"content": "\U0001b001"}}, 1),
)


@pytest.mark.parametrize("metadata,language", _LANGUAGE_CASES)
@pytest.mark.parametrize("receipt", [False, True])
def test_d5_language_follows_kana_in_the_metadata_request_text(
    metadata: dict[str, object] | None, language: Literal[0, 1], *, receipt: bool
) -> None:
    """D5: kana only; malformed/absent carriers default EN, including the no-receipt arm."""
    case = _Case(
        "language",
        "import_not_admitted" if receipt else "no_tool_call",
        receipt=receipt,
        program="import os\n",
        metadata=metadata,
        request_text=_REQUEST + " あ" if language == 0 else _REQUEST,
    )
    result, _calls, events, _completed = _exercise(case, load_filter_module())
    assert_filter_text(result, _FAIL)
    assert normalized_events(events) == [
        _status(case.reason, language),
        embed_event(case.reason, metadata),
    ]


@given(text=st.text(max_size=80), kana=st.sampled_from(("", "あ", "カ", "ｶ", "\U0001b001")))
@settings(max_examples=80, deadline=None)
def test_d5_unicode_language_property(text: str, kana: str) -> None:
    """D5: inserting arbitrary non-kana cannot change the exact Unicode-name predicate."""
    content = text + kana
    language: Literal[0, 1] = (
        1 if any(unicodedata.name(char, "").startswith(_KANA_PREFIXES) for char in content) else 0
    )
    case = replace(_BY_NAME["01-no-receipt"], metadata={"user_message": {"content": content}})
    result, _calls, events, _completed = _exercise(case, load_filter_module())
    assert_filter_text(result, _FAIL)
    assert normalized_events(events) == [
        _status("no_tool_call", language),
        embed_event("no_tool_call", case.metadata),
    ]


@pytest.mark.parametrize("reason", sorted(get_args(RefusalCode)))
def test_d6_one_info_record_per_fail_with_no_ids(
    reason: RefusalCode, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D6: every refusal code uses one reason-only record, never metadata/user IDs."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    module = load_filter_module()
    monkeypatch.setattr(module, "first_verdict", lambda *_args: (Refused(reason), None))
    case = _Case(
        "all-refusals",
        reason,
        user={"id": "USER_ID_SENTINEL\n"},
        metadata={"session_id": "SESSION_ID_SENTINEL", "message_id": "MESSAGE_ID_SENTINEL"},
    )
    result, calls, events, _completed = _exercise(case, module)
    assert_filter_text(result, _FAIL)
    assert calls == []
    _assert_log(caplog, reason)
    assert normalized_events(events) == [_status(reason), embed_event(reason)]


@pytest.mark.parametrize(
    ("arm", "reason"),
    [
        (4, "call_target_not_admitted"),
        (10, "sandbox_unavailable"),
        (11, "sandbox_error"),
        (12, "no_image"),
    ],
)
def test_d7_status_and_log_carry_no_untrusted_bytes(
    arm: int, reason: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """D7: six independently planted sources are absent from both diagnostic channels."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    sentinels = (
        "STDERR_SENTINEL_OMEGA",
        "STDOUT_SENTINEL_SIGMA",
        "PROGRAM_SENTINEL_TAU",
        "REQUEST_SENTINEL_RHO",
        "FILENAME_SENTINEL_PHI",
        "CSV_SENTINEL_PSI",
    )
    err, out, source, request, filename, csv = sentinels
    content = f"key,value\n{csv},1\nother,2\n".encode()
    program = (
        "import pandas as pd\nimport matplotlib.pyplot as plt\n"
        f'df = pd.read_csv("/mnt/uploads/{filename}.csv")\n'
        'plt.bar(df["key"], df["value"])\n'
        f"# {source}\nplt.show()\n"
    )
    target = DatasetTarget(f"/mnt/uploads/{filename}.csv", content)
    verified = verify_python_source(program, declared_target=target)
    assert isinstance(verified, Verified)
    if arm == 4:
        program += f"print('{source}')\n"
    stdout = out if arm == 12 else stdout_for_verified(verified, valid_png_uri(), prefix=out + "\n")
    stderr = ""
    if arm == 10:
        stderr = "loadPyodide is not defined " + err
    elif arm == 11:
        stderr = "Traceback (most recent call last):\nloadPyodide " + err
    calls: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    async def rpc(payload: dict[str, object]) -> object:
        calls.append(payload)
        return {"stdout": stdout, "stderr": stderr}

    async def emit(event: dict[str, object]) -> None:
        events.append(event)

    with fake_open_webui(
        [StoredFile("source-file", "owner", filename + ".csv", content)], tmp_path
    ):
        result = invoke_filter(
            load_filter_module(),
            filter_body(out),
            request=recorded_request(program, ("source-file",), request),
            user={"id": "owner"},
            metadata={"session_id": "session", "user_message": {"content": request}},
            event_call=rpc,
            event_emitter=emit,
        )
    assert_filter_text(result, _FAIL)
    assert len(calls) == (0 if arm == 4 else 1)
    _assert_log(caplog, reason)
    assert normalized_events(events) == [_status(reason), embed_event(reason)]
    surfaced = repr(events) + repr(_records(caplog))
    for sentinel in sentinels:
        assert sentinel not in surfaced


@pytest.mark.parametrize(
    "case_name", ["01-no-receipt", "04-call-refusal", "11-sandbox", "15-publish-error"]
)
@pytest.mark.parametrize("status_mode", ["raises", "pending"])
def test_d8_a_raising_or_pending_emitter_never_costs_the_verdict(
    case_name: str,
    status_mode: Literal["raises", "pending"],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D8: each representative stage retains FAIL and logging after status failure/deadline."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    module = load_filter_module()
    if status_mode == "pending":
        limit = getattr(module, "STATUS_TIMEOUT_SECONDS", None)
        assert isinstance(limit, int | float) and 0 < limit <= 5
        monkeypatch.setattr(module, "STATUS_TIMEOUT_SECONDS", 0.001)
    case = _BY_NAME[case_name]
    result, calls, events, completed = _exercise(case, module, status_mode=status_mode)
    assert_filter_text(result, _FAIL)
    assert len(calls) == case.rpc_count
    assert completed == []
    _assert_log(caplog, case.reason)
    expected = ([_files()] if case.publish_fails else []) + [_status(case.reason)]
    if status_mode == "raises":
        expected.append(embed_event(case.reason))
    assert normalized_events(events) == expected


def test_d8_slow_emitter_cleanup_never_delays_the_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D8 (reviewer-1 F2): an emitter that is slow to cancel cannot hold back the FAIL rewrite."""
    module = load_filter_module()
    monkeypatch.setattr(module, "STATUS_TIMEOUT_SECONDS", 0.001)
    body = filter_body("MODEL_REPLY_SENTINEL")

    async def scenario() -> bool:
        release = asyncio.Event()

        async def emit(_event: dict[str, object]) -> None:
            try:
                await asyncio.Event().wait()
            finally:
                await release.wait()

        outlet = asyncio.ensure_future(module.Filter().outlet(body, __event_emitter__=emit))
        done, _pending = await asyncio.wait({outlet}, timeout=1.0)
        release.set()
        await outlet
        return bool(done)

    assert asyncio.run(scenario())
    assert_filter_text(body, _FAIL)


def test_d8_an_emitter_raising_before_it_returns_an_awaitable_keeps_the_verdict(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D8: an emitter that raises on call, not on await, still leaves FAIL + the record."""
    caplog.set_level(logging.INFO, logger=_LOGGER)

    def emit(_event: dict[str, object]) -> Awaitable[object]:
        error = "EMIT_CALL_SENTINEL"
        raise TypeError(error)

    result = invoke_filter(load_filter_module(), filter_body("x"), event_emitter=emit)
    assert_filter_text(result, _FAIL)
    _assert_log(caplog, "no_tool_call")


@pytest.mark.parametrize("case_name", ["01-no-receipt", "04-call-refusal", "05-no-emitter"])
def test_d8_an_absent_emitter_keeps_the_log_record(
    case_name: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    case = replace(_BY_NAME[case_name], emitter=False)
    result, calls, events, _completed = _exercise(case, load_filter_module())
    assert_filter_text(result, _FAIL)
    assert calls == []
    assert events == []
    _assert_log(caplog, case.reason)


@pytest.mark.parametrize("error", [RuntimeError, ValueError, OSError])
def test_d8_a_raising_log_handler_never_costs_the_verdict_or_status(
    error: type[Exception],
) -> None:
    class RaisingHandler(logging.Handler):
        def emit(self, _record: logging.LogRecord) -> None:
            message = "LOG_HANDLER_SENTINEL"
            raise error(message)

    logger = logging.getLogger(_LOGGER)
    previous = logger.level
    handler = RaisingHandler()
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        result, _calls, events, _completed = _exercise(
            _BY_NAME["01-no-receipt"], load_filter_module()
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
    assert_filter_text(result, _FAIL)
    assert normalized_events(events) == [_status("no_tool_call"), embed_event("no_tool_call")]


@pytest.mark.parametrize(
    "case_name", ["01-no-receipt", "04-call-refusal", "11-sandbox", "15-publish-error"]
)
def test_d8_status_cancellation_is_not_swallowed(case_name: str) -> None:
    with pytest.raises(asyncio.CancelledError):
        _exercise(_BY_NAME[case_name], load_filter_module(), status_mode="cancelled")


def test_d8_log_cancellation_is_not_swallowed() -> None:
    class CancellingHandler(logging.Handler):
        def emit(self, _record: logging.LogRecord) -> None:
            raise asyncio.CancelledError

    logger = logging.getLogger(_LOGGER)
    previous = logger.level
    handler = CancellingHandler()
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        with pytest.raises(asyncio.CancelledError):
            _exercise(_BY_NAME["01-no-receipt"], load_filter_module())
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
