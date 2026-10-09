# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M19.5 O1-O5: RPC-first publication path, real-reader witnesses, bounded diagnostics."""

from __future__ import annotations

import asyncio
import copy
import importlib
import logging
import sys
import time
from collections.abc import Awaitable, Callable, Coroutine, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from outlet_support import (
    FAIL,
    LOGGER,
    PASS,
    SALES,
    SALES_BYTES,
    SESSION,
    SIMPLE,
    TRUNCATED,
    USER,
    Bomb,
    Browser,
    Document,
    EventCall,
    assert_failure,
    assert_log,
    assert_rewrite,
    assert_states,
    embed,
    listing,
    load,
    output,
    patched_filter,
    rows,
    verdict,
)
from paste_in_support import (
    StoredFile,
    fake_open_webui,
    filter_body,
    invoke_filter,
    recorded_request,
)
from verifier.figure.judge import Passed, Sources, judge
from verifier.figure.reasons import Blocked


@pytest.fixture(autouse=True)
def _empty_store(tmp_path: Path) -> Iterator[None]:
    with fake_open_webui((), tmp_path):
        yield


def _async_outlet(
    browser: Browser,
    emitter: EventCall,
    *,
    receipt: bool = True,
    module: ModuleType | None = None,
) -> Coroutine[Any, Any, dict[str, object]]:
    api = module or load("filter")
    return cast(
        Coroutine[Any, Any, dict[str, object]],
        api.Filter().outlet(
            filter_body("MODEL_PROSE"),
            __user__=USER,
            __request__=recorded_request(browser.program) if receipt else None,
            __event_call__=browser.call,
            __event_emitter__=emitter,
            __metadata__={"session_id": SESSION},
        ),
    )


class _UnreadUser(dict[str, object]):
    calls = 0

    def get(self, key: str, default: object = None) -> object:
        del key, default
        self.calls += 1
        message = "user lookup preceded receipt validation"
        raise AssertionError(message)


def test_o1_receipt_precedes_user_files_font_and_rpc(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _UnreadUser(id="owner")
    downstream = Bomb()
    browser = Browser()
    with patched_filter(
        monkeypatch, (("webui.paste_in.owui_files", "cjk_font", downstream),)
    ) as api:
        result = invoke_filter(
            api,
            filter_body("```python\n" + SIMPLE + "```"),
            user=user,
            request=None,
            metadata={"session_id": SESSION},
            event_call=cast(EventCall, downstream),
            event_emitter=browser.emit,
        )
    assert user.calls == downstream.calls == 0
    assert_failure(result, browser.events, "no_tool_call")


@pytest.mark.parametrize("user", [None, {}, {"id": ""}, {"id": 7}])
def test_o1_no_user_precedes_owned_files_font_and_rpc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, user: dict[str, object] | None
) -> None:
    downstream = Bomb()
    browser = Browser()
    with (
        fake_open_webui((), tmp_path) as lookups,
        patched_filter(
            monkeypatch, (("webui.paste_in.owui_files", "cjk_font", downstream),)
        ) as api,
    ):
        files = importlib.import_module("open_webui.models.files").Files
        monkeypatch.setattr(files, "get_file_by_id_and_user_id", downstream)
        result = invoke_filter(
            api,
            filter_body("MODEL_PROSE"),
            user=user,
            request=recorded_request(SIMPLE, ("missing",)),
            metadata={"session_id": SESSION},
            event_call=cast(EventCall, downstream),
            event_emitter=browser.emit,
        )
    assert lookups == [] and downstream.calls == 0
    assert_failure(result, browser.events, "no_user")


@pytest.mark.parametrize(
    "missing", ["call", "emitter", "metadata", "session", "empty", "wrong-type"]
)
def test_o1_no_browser_precedes_file_fetch_and_font(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    missing: str,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    downstream = Bomb()
    browser = Browser()
    metadata: object = {"session_id": SESSION}
    if missing == "metadata":
        metadata = []
    elif missing == "session":
        metadata = {}
    elif missing == "empty":
        metadata = {"session_id": ""}
    elif missing == "wrong-type":
        metadata = {"session_id": 7}
    with (
        fake_open_webui((), tmp_path),
        patched_filter(
            monkeypatch, (("webui.paste_in.owui_files", "cjk_font", downstream),)
        ) as api,
    ):
        files = importlib.import_module("open_webui.models.files").Files
        monkeypatch.setattr(files, "get_file_by_id_and_user_id", downstream)
        result = invoke_filter(
            api,
            filter_body("MODEL_PROSE"),
            user=USER,
            request=recorded_request(SIMPLE + "# 年", ("missing",)),
            metadata=cast(dict[str, object], metadata),
            event_call=None if missing == "call" else cast(EventCall, downstream),
            event_emitter=None if missing == "emitter" else browser.emit,
        )
    assert downstream.calls == 0
    assert_log(caplog, "no_browser")
    if missing == "emitter":
        assert_rewrite(result, FAIL)
        assert browser.events == []
    else:
        assert_failure(result, browser.events, "no_browser")


_FAULTS: tuple[tuple[str, object, str], ...] = (
    ("timeout", None, "browser_timeout"),
    ("raise", None, "browser_error"),
    ("non-dict", [], "reply_malformed"),
    ("none", None, "reply_malformed"),
    ("error", {"error": "PRIVATE_ERROR"}, "browser_no_answer"),
    ("loader", {"stderr": "loadPyodide is not defined PRIVATE_STDERR"}, "sandbox_unavailable"),
    ("webkit", {"stderr": "Can't find variable: loadPyodide"}, "sandbox_unavailable"),
    (
        "traceback",
        {"stderr": "Traceback (most recent call last):\nNameError: loadPyodide"},
        "sandbox_error",
    ),
    ("stderr", {"stderr": "PRIVATE_STDERR"}, "sandbox_error"),
    ("missing-stderr", {"stdout": "anything"}, "reply_malformed"),
    ("bad-stderr", {"stderr": []}, "reply_malformed"),
)


@pytest.mark.parametrize("case,reply,reason", _FAULTS, ids=[case[0] for case in _FAULTS])
def test_o1_reply_faults_precede_description_and_judge(
    monkeypatch: pytest.MonkeyPatch, case: str, reply: object, reason: str
) -> None:
    parse_bomb, judge_bomb = Bomb(), Bomb()
    browser = Browser()
    calls = 0

    async def rpc(_payload: dict[str, object]) -> object:
        nonlocal calls
        calls += 1
        if case == "timeout":
            await asyncio.Event().wait()
        if case == "raise":
            message = "PRIVATE_RPC_EXCEPTION"
            raise RuntimeError(message)
        return reply

    with patched_filter(
        monkeypatch,
        (
            ("verifier.figure.description", "parse_description", parse_bomb),
            ("verifier.figure.judge", "judge", judge_bomb),
        ),
    ) as api:
        assert api.RPC_TIMEOUT_SECONDS == 60
        monkeypatch.setattr(api, "RPC_TIMEOUT_SECONDS", 0.01)
        result = invoke_filter(
            api,
            filter_body("MODEL_PROSE"),
            request=recorded_request(SIMPLE),
            user=USER,
            metadata={"session_id": SESSION},
            event_call=rpc,
            event_emitter=browser.emit,
        )
    assert calls == 1 and parse_bomb.calls == judge_bomb.calls == 0
    assert_failure(result, browser.events, reason)


@pytest.mark.parametrize("stdout", [None, "", "garbled", 123, [], "data:image/png;base64,AAAA"])
def test_o1_no_description_never_judges_or_publishes(
    monkeypatch: pytest.MonkeyPatch, stdout: object
) -> None:
    judge_bomb = Bomb()
    browser = Browser()
    calls = 0

    async def rpc(_payload: dict[str, object]) -> object:
        nonlocal calls
        calls += 1
        return {"stdout": stdout, "stderr": None}

    with patched_filter(monkeypatch, (("verifier.figure.judge", "judge", judge_bomb),)) as api:
        result = invoke_filter(
            api,
            filter_body("MODEL_PROSE"),
            request=recorded_request(SIMPLE),
            user=USER,
            metadata={"session_id": SESSION},
            event_call=rpc,
            event_emitter=browser.emit,
        )
    assert calls == 1 and judge_bomb.calls == 0
    assert_failure(result, browser.events, "no_description")


@pytest.mark.parametrize("stderr", [None, ""])
def test_o1_clean_browser_reply_runs_real_judge_before_publication(stderr: str | None) -> None:
    browser = Browser()

    async def rpc(payload: dict[str, object]) -> object:
        clean = cast(dict[str, object], await browser.call(payload))
        return {**clean, "stderr": stderr}

    result = invoke_filter(
        load("filter"),
        filter_body("MODEL_PROSE"),
        request=recorded_request(SIMPLE),
        user=USER,
        metadata={"session_id": SESSION},
        event_call=rpc,
        event_emitter=browser.emit,
    )
    expected = verdict(SIMPLE)
    assert isinstance(expected, Passed)
    assert_rewrite(result, PASS + "\n\n" + expected.interpretation)
    assert len(browser.calls) == 1
    assert [event["type"] for event in browser.events] == ["files", "embeds"]
    assert_states(embed(browser.events), None)


@pytest.mark.parametrize("mode", ["absent", "duplicate", "inline", "jpeg"])
def test_o1_pass_without_exactly_one_standalone_png_line_blocks(mode: str) -> None:
    browser = Browser()
    raw = output(SIMPLE)
    description, png = raw.splitlines()
    replacement = {
        "absent": description,
        "duplicate": description + "\n" + png + "\n" + png,
        "inline": description + "\nimage = " + png,
        "jpeg": description + "\n" + png.replace("image/png", "image/jpeg"),
    }[mode]

    async def rpc(payload: dict[str, object]) -> object:
        await browser.call(payload)
        return {"stdout": replacement, "stderr": None}

    result = invoke_filter(
        load("filter"),
        filter_body("MODEL_PROSE"),
        request=recorded_request(SIMPLE),
        user=USER,
        metadata={"session_id": SESSION},
        event_call=rpc,
        event_emitter=browser.emit,
    )
    assert len(browser.calls) == 1
    assert_failure(result, browser.events, "no_image")


def test_o1_an_indented_png_line_still_counts() -> None:
    """MAIN ruling C1 (inherited from the M10 outlet): the PNG line is read stripped."""
    browser = Browser()
    description, png = output(SIMPLE).splitlines()

    async def rpc(payload: dict[str, object]) -> object:
        await browser.call(payload)
        return {"stdout": description + "\n  " + png + "  \n", "stderr": None}

    result = invoke_filter(
        load("filter"),
        filter_body("MODEL_PROSE"),
        request=recorded_request(SIMPLE),
        user=USER,
        metadata={"session_id": SESSION},
        event_call=rpc,
        event_emitter=browser.emit,
    )
    messages = cast(list[dict[str, object]], result["messages"])
    assert str(messages[-1]["content"]).startswith("Figure verification passed")


def test_o1_blocked_judge_precedes_missing_png_and_threads_site() -> None:
    browser = Browser(TRUNCATED)
    assert verdict(TRUNCATED) == Blocked("zero_not_in_limits", 3)

    async def rpc(payload: dict[str, object]) -> object:
        await browser.call(payload)
        return {"stdout": output(TRUNCATED).splitlines()[0], "stderr": None}

    result = invoke_filter(
        load("filter"),
        filter_body("MODEL_PROSE"),
        request=recorded_request(TRUNCATED),
        user=USER,
        metadata={"session_id": SESSION},
        event_call=rpc,
        event_emitter=browser.emit,
    )
    assert_failure(result, browser.events, "zero_not_in_limits")
    assert tuple(item for item in listing(rows(embed(browser.events))["axes"]) if item[1]) == (
        (3, True, "plt.ylim(30000, 45000)", ("plt.ylim(30000, 45000)",)),
    )


@pytest.mark.parametrize("when", ["call", "await"])
def test_o1_files_emit_failure_blocks_instead_of_publishing_pass(when: str) -> None:
    browser = Browser()

    async def finish(event: dict[str, object]) -> None:
        if event["type"] == "files" and when == "await":
            message = "FILE_EMIT_ERROR"
            raise RuntimeError(message)

    def emit_event(event: dict[str, object]) -> Awaitable[object]:
        browser.events.append(event)
        if event["type"] == "files" and when == "call":
            message = "FILE_EMIT_ERROR"
            raise ValueError(message)
        return finish(event)

    result = asyncio.run(_async_outlet(browser, emit_event))
    assert [event["type"] for event in browser.events] == ["files", "status", "embeds"]
    assert_failure(result, browser.events[1:], "publish_failed")


def test_o2_every_owned_file_reaches_rpc_in_receipt_order(tmp_path: Path) -> None:
    browser = Browser(
        SALES,
        files=[
            {"id": "weather", "filename": "weather.csv"},
            {"id": "sales", "filename": "uploaded-sales.csv"},
        ],
    )
    stored = (
        StoredFile("weather", "outlet-owner", "weather.csv", b"x,z\n1,200\n"),
        StoredFile("sales", "outlet-owner", "uploaded-sales.csv", SALES_BYTES),
        StoredFile("foreign", "other", "private.csv", SALES_BYTES),
    )
    with fake_open_webui(stored, tmp_path) as lookups:
        result = browser.exercise(
            file_ids=("weather", "foreign", "missing", "sales"), request_text="revenue by region"
        )
    expected = verdict(
        SALES,
        Sources(
            (("weather.csv", b"x,z\n1,200\n"), ("uploaded-sales.csv", SALES_BYTES)),
            "revenue by region",
        ),
    )
    assert isinstance(expected, Passed)
    assert_rewrite(result, PASS + "\n\n" + expected.interpretation)
    assert "uploaded-sales.csv" in expected.interpretation
    assert lookups == [
        (name, "outlet-owner") for name in ("weather", "foreign", "missing", "sales")
    ]
    assert len(browser.calls) == 1
    assert_states(embed(browser.events), None)


@pytest.mark.parametrize("trigger", ["none", "request-only", "filename-only", "program", "file"])
def test_o2_font_trigger_reads_program_and_all_owned_bytes_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, trigger: str
) -> None:
    program = SIMPLE + ("# 年\n" if trigger == "program" else "")
    content = b"name,value\na,100\n" + ("年,200\n".encode() if trigger == "file" else b"")
    name = "表.csv" if trigger == "filename-only" else "extra.csv"
    needed = trigger in {"program", "file"}
    font = b"exact OWUI font payload"
    calls = 0

    async def read_font() -> bytes:
        nonlocal calls
        calls += 1
        return font

    browser = Browser(
        program, files=[{"id": "owned", "filename": name}], font=font if needed else None
    )
    request = "グラフ 3 5 9" if trigger == "request-only" else "3 5 9"
    with (
        fake_open_webui((StoredFile("owned", "outlet-owner", name, content),), tmp_path),
        patched_filter(monkeypatch, (("webui.paste_in.owui_files", "cjk_font", read_font),)),
    ):
        result = browser.exercise(file_ids=("owned",), request_text=request)
    assert calls == int(needed)
    assert len(browser.calls) == 1
    assert cast(list[dict[str, object]], result["messages"])[-1]["content"] != FAIL
    assert_states(embed(browser.events), None)


def test_o2_font_fault_falls_back_to_no_font(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = 0
    environment = ModuleType("open_webui.env")
    environment.__dict__["FONTS_DIR"] = tmp_path
    monkeypatch.setitem(sys.modules, "open_webui.env", environment)
    original = cast(Callable[[], Awaitable[bytes | None]], load("owui_files").cjk_font)

    async def missing_font() -> bytes | None:
        nonlocal calls
        calls += 1
        font = await original()
        assert font is None
        return font

    browser = Browser(SIMPLE + "# 年\n")
    with patched_filter(monkeypatch, (("webui.paste_in.owui_files", "cjk_font", missing_font),)):
        result = browser.exercise()
    assert calls == 1 and len(browser.calls) == 1
    expected = verdict(browser.program)
    assert isinstance(expected, Passed)
    assert_rewrite(result, PASS + "\n\n" + expected.interpretation)


@pytest.mark.parametrize("changed", [False, True], ids=["exact-bytes", "changed-owned-data"])
def test_o3_owned_csv_bytes_decide_values(tmp_path: Path, *, changed: bool) -> None:
    content = SALES_BYTES.replace(b"12000", b"12001") if changed else SALES_BYTES
    browser = Browser(SALES, files=[{"id": "owned", "filename": "source.csv"}])
    sources = Sources((("source.csv", content),), "revenue by region")
    expected = verdict(SALES, sources)
    with fake_open_webui((StoredFile("owned", "outlet-owner", "source.csv", content),), tmp_path):
        result = browser.exercise(file_ids=("owned",), request_text="revenue by region")
    if changed:
        assert expected == Blocked("value_not_found", 2)
        assert_failure(result, browser.events, "value_not_found")
    else:
        assert isinstance(expected, Passed)
        assert_rewrite(result, PASS + "\n\n" + expected.interpretation)
        assert "source.csv" in expected.interpretation
        assert_states(embed(browser.events), None)


@pytest.mark.parametrize("request_text", ["3 5 9", "3 5 8"])
def test_o3_receipt_request_not_mutated_metadata_decides_values(request_text: str) -> None:
    browser = Browser()
    result = invoke_filter(
        load("filter"),
        filter_body("MODEL_PROSE"),
        request=recorded_request(SIMPLE, request_text=request_text),
        user=USER,
        metadata={
            "session_id": SESSION,
            "user_message": {"content": "3 5 8" if request_text == "3 5 9" else "3 5 9"},
        },
        event_call=browser.call,
        event_emitter=browser.emit,
    )
    expected = verdict(SIMPLE, Sources(request=request_text))
    if request_text == "3 5 8":
        assert expected == Blocked("value_not_found", 2)
        assert_failure(result, browser.events, "value_not_found")
    else:
        assert isinstance(expected, Passed)
        assert_rewrite(result, PASS + "\n\n" + expected.interpretation)
        assert_states(embed(browser.events), None)


@pytest.mark.parametrize("demo", [False, True], ids=["strict", "substitution"])
def test_o3_artifact_anchoring_changes_the_real_judge_verdict(
    tmp_path: Path, *, demo: bool
) -> None:
    browser = Browser(SALES, files=[{"id": "sales", "filename": "sales.csv"}])
    with fake_open_webui(
        (StoredFile("sales", "outlet-owner", "sales.csv", SALES_BYTES),), tmp_path
    ):
        result = browser.exercise(file_ids=("sales",), request_text="Chart by region", demo=demo)
    expected = verdict(
        SALES,
        Sources(
            (("sales.csv", SALES_BYTES),), "Chart by region", "substitution" if demo else "strict"
        ),
    )
    if demo:
        assert isinstance(expected, Passed)
        assert_rewrite(result, PASS + "\n\n" + expected.interpretation)
        assert_states(embed(browser.events), None)
    else:
        assert expected == Blocked("column_not_named")
        assert_failure(result, browser.events, "column_not_named")


@pytest.mark.parametrize("aliased", [False, True])
def test_o3_receipt_aliases_change_the_real_judge_verdict(tmp_path: Path, *, aliased: bool) -> None:
    aliases = (("revenue", "sales"),) if aliased else ()
    browser = Browser(SALES, files=[{"id": "sales", "filename": "sales.csv"}])
    with fake_open_webui(
        (StoredFile("sales", "outlet-owner", "sales.csv", SALES_BYTES),), tmp_path
    ):
        result = browser.exercise(
            file_ids=("sales",), request_text="sales by region", aliases=aliases
        )
    expected = verdict(
        SALES, Sources((("sales.csv", SALES_BYTES),), "sales by region", "strict", aliases)
    )
    if aliased:
        assert isinstance(expected, Passed)
        assert_rewrite(result, PASS + "\n\n" + expected.interpretation)
        assert_states(embed(browser.events), None)
    else:
        assert expected == Blocked("column_not_named")
        assert_failure(result, browser.events, "column_not_named")


def test_o3_sources_field_values_reach_public_judge_seam(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[Sources] = []
    expected = Sources(
        (("receipt-name.csv", SALES_BYTES),), "sales by region", "strict", (("revenue", "sales"),)
    )
    real_judge = cast(Callable[[object, Sources], object], judge)

    def spy(description: object, sources: Sources) -> object:
        seen.append(sources)
        return real_judge(description, sources)

    browser = Browser(SALES, files=[{"id": "sales", "filename": "receipt-name.csv"}])
    with (
        fake_open_webui(
            (StoredFile("sales", "outlet-owner", "receipt-name.csv", SALES_BYTES),), tmp_path
        ),
        patched_filter(monkeypatch, (("verifier.figure.judge", "judge", spy),)),
    ):
        result = browser.exercise(
            file_ids=("sales",), request_text="sales by region", aliases=(("revenue", "sales"),)
        )
    assert seen == [expected]
    outcome = verdict(SALES, expected)
    assert isinstance(outcome, Passed)
    assert_rewrite(result, PASS + "\n\n" + outcome.interpretation)


@pytest.mark.parametrize("program,reason", [(SIMPLE, None), (TRUNCATED, "zero_not_in_limits")])
@pytest.mark.parametrize(
    "request_text,japanese", [("Chart", False), ("漢字", False), ("グラフ", True), ("ｸﾞﾗﾌ", True)]
)
def test_o4_multiturn_rewrites_only_last_assistant_with_localized_interpretation(
    program: str, reason: str | None, request_text: str, *, japanese: bool
) -> None:
    browser = Browser(program)
    messages: list[dict[str, object]] = [
        {"role": "user", "content": "old request_text"},
        {"role": "assistant", "content": "old response", "output": ["old output"]},
        {"role": "user", "content": request_text},
        {"role": "assistant", "content": "MODEL_PROSE", "output": [{"type": "reasoning"}]},
        {"role": "tool", "content": "trailing item"},
    ]
    before = copy.deepcopy(messages)
    result = invoke_filter(
        load("filter"),
        {"messages": messages},
        request=recorded_request(program, request_text=request_text),
        user=USER,
        metadata={"session_id": SESSION, "user_message": {"content": request_text}},
        event_call=browser.call,
        event_emitter=browser.emit,
    )
    observed = cast(list[dict[str, object]], result["messages"])
    assert observed[:3] == before[:3] and observed[4] == before[4]
    if reason:
        assert_failure(result, browser.events, reason, japanese=japanese)
    else:
        expected = verdict(program, Sources(request=request_text))
        assert isinstance(expected, Passed)
        interpretation = expected.interpretation_ja if japanese else expected.interpretation
        assert_rewrite(result, PASS + "\n\n" + interpretation)
        assert_states(embed(browser.events), None)


@pytest.mark.parametrize("program,reason", [(SIMPLE, None), (TRUNCATED, "zero_not_in_limits")])
def test_o5_exact_events_and_one_code_only_log(
    caplog: pytest.LogCaptureFixture, program: str, reason: str | None
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    browser = Browser(program)
    result = browser.exercise()
    assert_log(caplog, reason)
    if reason:
        assert_failure(result, browser.events, reason)
    else:
        expected = verdict(program)
        assert isinstance(expected, Passed)
        assert_rewrite(result, PASS + "\n\n" + expected.interpretation)
        png = output(program).splitlines()[1]
        assert browser.events[0] == {
            "type": "files",
            "data": {"files": [{"type": "image", "url": png}]},
        }
        assert [event["type"] for event in browser.events] == ["files", "embeds"]
        assert_states(embed(browser.events), None)


def test_o5_status_and_log_never_include_source_or_sandbox_bytes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    program = SIMPLE + "# PRIVATE_PROGRAM\n"
    browser = Browser(program)

    async def rpc(payload: dict[str, object]) -> object:
        await browser.call(payload)
        return {"stdout": "PRIVATE_STDOUT", "stderr": "PRIVATE_STDERR"}

    result = invoke_filter(
        load("filter"),
        filter_body("PRIVATE_MODEL"),
        request=recorded_request(program, request_text="PRIVATE_REQUEST"),
        user=USER,
        metadata={"session_id": SESSION, "user_message": {"content": "PRIVATE_REQUEST"}},
        event_call=rpc,
        event_emitter=browser.emit,
    )
    assert_log(caplog, "sandbox_error")
    assert_failure(result, browser.events, "sandbox_error")
    diagnostic = repr(browser.events[0]) + repr(
        [(r.levelno, r.getMessage()) for r in caplog.records]
    )
    assert "PRIVATE_" not in diagnostic
    html = embed(browser.events)
    document = Document(html).root
    assert "PRIVATE_PROGRAM" in "".join(source.text() for source in document.nodes(cls="src"))
    assert "PRIVATE_" not in document.text(excluding="code")
    for sentinel in ("PRIVATE_STDOUT", "PRIVATE_STDERR", "PRIVATE_REQUEST", "PRIVATE_MODEL"):
        assert sentinel not in html


@given(
    plain=st.text(alphabet="abc0123漢字ー。!", max_size=30),
    kana=st.sampled_from(("", "あ", "カ", "ｶ")),
)
@settings(max_examples=35, deadline=None)
def test_o5_language_property_is_kana_letter_not_other_japanese_text(plain: str, kana: str) -> None:
    browser = Browser()
    request = plain + kana
    result = invoke_filter(
        load("filter"),
        filter_body("MODEL_PROSE"),
        metadata={"user_message": {"content": request}},
        event_emitter=browser.emit,
    )
    assert_failure(result, browser.events, "no_tool_call", japanese=bool(kana))
    assert one_language(embed(browser.events)) == ("ja" if kana else "en")


def one_language(html: str) -> str | None:
    return Document(html).root.nodes(tag="html")[0].attrs.get("lang")


@pytest.mark.parametrize("channel", ["status", "embeds"])
@pytest.mark.parametrize("when", ["call", "await"])
def test_o5_diagnostic_exceptions_leave_verdict_and_other_diagnostic(
    caplog: pytest.LogCaptureFixture, channel: str, when: str
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    browser = Browser()

    async def finish(event: dict[str, object]) -> None:
        if event["type"] == channel and when == "await":
            message = "DIAGNOSTIC_AWAIT"
            raise RuntimeError(message)

    def emit_event(event: dict[str, object]) -> Awaitable[object]:
        browser.events.append(event)
        if event["type"] == channel and when == "call":
            message = "DIAGNOSTIC_CALL"
            raise RuntimeError(message)
        return finish(event)

    result = asyncio.run(_async_outlet(browser, emit_event, receipt=False))
    assert_failure(result, browser.events, "no_tool_call")
    assert_log(caplog, "no_tool_call")


@pytest.mark.parametrize("passed", [False, True])
def test_o5_embed_renderer_fault_cannot_change_verdict(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, *, passed: bool
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER)
    bomb = Bomb()
    browser = Browser()
    with patched_filter(monkeypatch, (("webui.paste_in.checks", "breakdown_html", bomb),)) as api:
        result = asyncio.run(_async_outlet(browser, browser.emit, receipt=passed, module=api))
    assert bomb.calls == 1
    assert [event["type"] for event in browser.events] == (["files"] if passed else ["status"])
    expected = verdict(SIMPLE)
    assert isinstance(expected, Passed)
    assert_rewrite(result, PASS + "\n\n" + expected.interpretation if passed else FAIL)
    assert_log(caplog, None if passed else "no_tool_call")


def test_o5_raising_log_handler_cannot_change_failed_reply() -> None:
    class RaisingHandler(logging.Handler):
        calls = 0

        def emit(self, _record: logging.LogRecord) -> None:
            self.calls += 1
            message = "LOG_HANDLER_ERROR"
            raise OSError(message)

    logger = logging.getLogger(LOGGER)
    handler = RaisingHandler()
    before = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    browser = Browser()
    try:
        result = asyncio.run(_async_outlet(browser, browser.emit, receipt=False))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(before)
    assert handler.calls == 1
    assert_failure(result, browser.events, "no_tool_call")


def test_o5_pending_status_consumes_one_deadline_and_skips_embed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = load("filter")
    assert api.STATUS_TIMEOUT_SECONDS == 5
    monkeypatch.setattr(api, "STATUS_TIMEOUT_SECONDS", 0.03)
    browser = Browser()
    cancelled = []

    async def scenario() -> dict[str, object]:
        async def emit_event(event: dict[str, object]) -> None:
            browser.events.append(event)
            if event["type"] == "status":
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.append(True)

        task = asyncio.create_task(_async_outlet(browser, emit_event, receipt=False, module=api))
        done, _pending = await asyncio.wait({task}, timeout=0.1)
        try:
            assert done, "pending status delayed the verdict"
            result = await task
            await asyncio.sleep(0)
            return result
        finally:
            if not done:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    result = asyncio.run(scenario())
    assert_rewrite(result, FAIL)
    assert cancelled == [True]
    assert [event["type"] for event in browser.events] == ["status"]


def test_o5_status_spends_the_embed_budget_too(monkeypatch: pytest.MonkeyPatch) -> None:
    api = load("filter")
    monkeypatch.setattr(api, "STATUS_TIMEOUT_SECONDS", 0.1)
    browser = Browser()
    cancelled = []

    async def scenario() -> dict[str, object]:
        async def emit_event(event: dict[str, object]) -> None:
            browser.events.append(event)
            if event["type"] == "status":
                await asyncio.sleep(0.07)
            if event["type"] == "embeds":
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.append(True)

        task = asyncio.create_task(_async_outlet(browser, emit_event, receipt=False, module=api))
        done, _pending = await asyncio.wait({task}, timeout=0.145)
        try:
            assert done, "status and embed received separate deadlines"
            return await task
        finally:
            if not done:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    result = asyncio.run(scenario())
    assert_rewrite(result, FAIL)
    assert cancelled == [True]
    assert_failure(result, browser.events, "no_tool_call")


def test_o5_blocking_emitter_call_spends_the_shared_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = load("filter")
    monkeypatch.setattr(api, "STATUS_TIMEOUT_SECONDS", 0.2)
    browser = Browser()

    async def complete() -> None:
        return None

    def emit_event(event: dict[str, object]) -> Awaitable[object]:
        browser.events.append(event)
        if event["type"] == "status":
            time.sleep(0.15)
            return asyncio.Event().wait()
        return complete()

    start = time.monotonic()
    result = asyncio.run(_async_outlet(browser, emit_event, receipt=False, module=api))
    elapsed = time.monotonic() - start
    assert elapsed < 0.3, "emitter invocation time received a second budget"
    assert_rewrite(result, FAIL)
    assert [event["type"] for event in browser.events] == ["status"]


class _JumpLoop(asyncio.SelectorEventLoop):
    jump = 0.0

    def time(self) -> float:
        return super().time() + self.jump


@pytest.mark.parametrize("passed", [False, True])
def test_o5_slow_emit_cancellation_cleanup_does_not_delay_verdict(
    monkeypatch: pytest.MonkeyPatch, *, passed: bool
) -> None:
    api = load("filter")
    monkeypatch.setattr(api, "STATUS_TIMEOUT_SECONDS", 3600)
    browser = Browser()
    output(SIMPLE)
    cleanup = []

    async def scenario() -> dict[str, object]:
        release = asyncio.Event()

        async def emit_event(event: dict[str, object]) -> None:
            browser.events.append(event)
            if event["type"] == "embeds":
                cast(_JumpLoop, asyncio.get_running_loop()).jump = 7200
                try:
                    await asyncio.Event().wait()
                finally:
                    cleanup.append(True)
                    await release.wait()

        task = asyncio.create_task(_async_outlet(browser, emit_event, receipt=passed, module=api))
        limit = time.monotonic() + 2
        while not cleanup and not task.done() and time.monotonic() < limit:
            await asyncio.sleep(0.001)
        for _ in range(1000):
            if task.done():
                break
            await asyncio.sleep(0)
        done = task.done()
        release.set()
        try:
            assert done, "outlet awaited cancelled emitter cleanup"
            return await task
        finally:
            if not done:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    result = asyncio.run(scenario(), loop_factory=_JumpLoop)
    assert cleanup == [True]
    if passed:
        expected = verdict(SIMPLE)
        assert isinstance(expected, Passed)
        assert_rewrite(result, PASS + "\n\n" + expected.interpretation)
        assert_states(embed(browser.events), None)
    else:
        assert_failure(result, browser.events, "no_tool_call")


@pytest.mark.parametrize("channel", ["rpc", "files", "status", "embeds"])
@pytest.mark.parametrize("external", [False, True], ids=["self", "external"])
def test_o5_cancellation_propagates_at_every_async_boundary(
    channel: str, *, external: bool
) -> None:
    browser = Browser()
    output(SIMPLE)

    async def scenario() -> None:
        started = asyncio.Event()

        async def cancel() -> None:
            started.set()
            if not external:
                raise asyncio.CancelledError
            await asyncio.Event().wait()

        async def rpc(payload: dict[str, object]) -> object:
            if channel == "rpc":
                await cancel()
            return await browser.call(payload)

        async def emit_event(event: dict[str, object]) -> None:
            browser.events.append(event)
            if event["type"] == channel:
                await cancel()

        api = load("filter")
        operation = api.Filter().outlet(
            filter_body("MODEL_PROSE"),
            __user__=USER,
            __request__=None if channel == "status" else recorded_request(SIMPLE),
            __metadata__={"session_id": SESSION},
            __event_call__=rpc,
            __event_emitter__=emit_event,
        )
        task = asyncio.create_task(cast(Coroutine[Any, Any, object], operation))
        try:
            if external:
                await asyncio.wait_for(started.wait(), timeout=0.5)
                task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        assert started.is_set()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "program,reason",
    [
        ("not Python :\n", "program_syntax_error"),
        ("raise ValueError('PRIVATE_EXCEPTION')\n", "program_error"),
        ("import absent_m19_test_package\n", "module_not_available"),
        ("print('PRIVATE_PRINT')\n", "no_figure"),
        ("import matplotlib.pyplot as plt\nplt.figure()\nplt.figure()\n", "multiple_figures"),
    ],
    ids=["syntax", "runtime", "module", "no-figure", "multiple"],
)
def test_o1_python_and_figure_faults_are_decided_after_unchanged_rpc(
    program: str, reason: str
) -> None:
    browser = Browser(program)
    expected = verdict(program)
    assert isinstance(expected, Blocked) and expected.reason == reason
    result = browser.exercise()
    assert len(browser.calls) == 1
    assert_failure(result, browser.events, reason)


def test_o2_repeated_completions_get_fresh_uuid4_rpc_ids() -> None:
    browsers = [Browser(), Browser()]
    for browser in browsers:
        result = browser.exercise()
        expected = verdict(SIMPLE)
        assert isinstance(expected, Passed)
        assert_rewrite(result, PASS + "\n\n" + expected.interpretation)
        assert_states(embed(browser.events), None)
    identifiers = [cast(dict[str, object], browser.calls[0]["data"])["id"] for browser in browsers]
    assert identifiers[0] != identifiers[1]


def test_o1_a_description_naming_data_keeps_its_png() -> None:
    """A chart text holding `data:` sits inside the description line, never a second PNG line."""
    program = "import matplotlib.pyplot as plt\nplt.bar(['a'], [1])\nplt.title('data:x')\n"
    browser = Browser(program=program)

    async def rpc(payload: dict[str, object]) -> object:
        await browser.call(payload)
        return {"stdout": output(program), "stderr": None}

    result = invoke_filter(
        load("filter"),
        filter_body("MODEL_PROSE"),
        request=recorded_request(program),
        user=USER,
        metadata={"session_id": SESSION},
        event_call=rpc,
        event_emitter=browser.emit,
    )
    messages = cast(list[dict[str, object]], result["messages"])
    assert str(messages[-1]["content"]).startswith("Figure verification passed")
