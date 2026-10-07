# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M16.1 C6-C9: fixed outlet verdicts plus a bounded, independently graded check embed.

Contract: `.agent/archive/contracts/m16u1.md`; literal reason→check map = filter_checks_support.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import ModuleType
from typing import cast, get_args

import pytest

from filter_checks_support import embed_event, normalized_events, parse_document
from observe_support import stdout_for_verified
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
from test_paste_in_filter_reasons import (
    _BY_NAME,
    _CASES,
    _FAIL,
    _LOGGER,
    _assert_log,
    _Case,
    _exercise,
    _expected_pass,
    _files,
    _records,
    _reply,
    _status,
)
from verifier.pysrc import DatasetTarget, Refused, Verified, verify_python_source
from verifier.pysrc.errors import RefusalCode

_EXCEPTION_CASES = ("01-no-receipt", "04-call-refusal", "11-sandbox", "15-publish-error", "pass")


def _case(name: str) -> _Case:
    return _Case("pass", "", 1) if name == "pass" else _BY_NAME[name]


def _verdict(case: _Case) -> str:
    return _expected_pass() if case.name == "pass" else _FAIL


def _events(case: _Case, *, embed: bool = True) -> list[dict[str, object]]:
    events = [_files()] if case.publish_fails or case.name == "pass" else []
    if case.name != "pass":
        events.append(_status(case.reason))
    if embed:
        events.append(embed_event(None if case.name == "pass" else case.reason))
    return events


def _assert_events(case: _Case, events: list[dict[str, object]], *, embed: bool = True) -> None:
    kinds = ["files"] if case.publish_fails or case.name == "pass" else []
    if case.name != "pass":
        kinds.append("status")
    if embed:
        kinds.append("embeds")
    assert [event["type"] for event in events] == kinds
    assert normalized_events(events) == _events(case, embed=embed)


def _assert_result(
    case: _Case, result: dict[str, object], caplog: pytest.LogCaptureFixture
) -> None:
    assert_filter_text(result, _verdict(case))
    if case.name == "pass":
        assert _records(caplog) == []
    else:
        _assert_log(caplog, case.reason)


@dataclass
class _Harness:
    case: _Case
    module: ModuleType
    calls: list[dict[str, object]] = field(default_factory=list)
    events: list[dict[str, object]] = field(default_factory=list)

    async def run(
        self,
        emitter: Callable[[dict[str, object]], Awaitable[object]] | None,
        *,
        metadata: object = None,
    ) -> dict[str, object]:
        async def rpc(payload: dict[str, object]) -> object:
            self.calls.append(payload)
            return _reply(self.case.reply)

        def emit(event: dict[str, object]) -> Awaitable[object]:
            self.events.append(event)
            if event["type"] == "files" and self.case.publish_fails:
                failure = "FILES_EXCEPTION_SENTINEL"
                raise OSError(failure)
            assert emitter is not None
            return emitter(event)

        body = filter_body("MODEL_REPLY_SENTINEL")
        with fake_open_webui([], Path(__file__).parent):
            result = await cast(
                Awaitable[dict[str, object]],
                self.module.Filter().outlet(
                    body,
                    __request__=(
                        recorded_request(self.case.program, request_text=self.case.request_text)
                        if self.case.receipt
                        else None
                    ),
                    __user__=self.case.user,
                    __metadata__={"session_id": "session"} if metadata is None else metadata,
                    __event_call__=rpc,
                    __event_emitter__=emit if emitter is not None else None,
                ),
            )
        assert result is body
        return result


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case.name)
@pytest.mark.parametrize("japanese", [False, True], ids=["en", "ja"])
def test_c6_every_fail_arm_emits_status_then_one_embed(
    case: _Case,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    *,
    japanese: bool,
) -> None:
    """C6: every M15 arm, unchanged RPC count/log/verdict; files→status→replace embed."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    metadata = {
        **(case.metadata or {}),
        "user_message": {"content": "あ" if japanese else "English"},
    }
    case = replace(case, metadata=metadata)
    module = load_filter_module()
    if case.rpc == "timeout":
        monkeypatch.setattr(module, "RPC_TIMEOUT_SECONDS", 0.001)
    result, calls, events, _completed = _exercise(case, module)
    assert_filter_text(result, _FAIL)
    assert len(calls) == case.rpc_count
    _assert_log(caplog, case.reason)
    expected = [_files()] if case.publish_fails else []
    if case.emitter:
        assert [event["type"] for event in events] == (["files"] if case.publish_fails else []) + [
            "status",
            "embeds",
        ]
        expected.extend(
            [_status(case.reason, 1 if japanese else 0), embed_event(case.reason, metadata)]
        )
    assert normalized_events(events) == expected


@pytest.mark.parametrize("reason", sorted(get_args(RefusalCode)))
@pytest.mark.parametrize("japanese", [False, True], ids=["en", "ja"])
def test_c6_each_core_reason_earns_only_its_completed_prefix(
    reason: RefusalCode,
    monkeypatch: pytest.MonkeyPatch,
    *,
    japanese: bool,
) -> None:
    """C6: every core refusal carries its own cause, never an all-pass or later-stage document."""
    module = load_filter_module()
    monkeypatch.setattr(module, "first_verdict", lambda *_args: (Refused(reason), None))
    metadata: dict[str, object] = {"user_message": {"content": "ｶ" if japanese else "English"}}
    case = replace(_BY_NAME["04-call-refusal"], reason=reason, metadata=metadata)
    result, calls, events, _completed = _exercise(case, module)
    assert_filter_text(result, _FAIL)
    assert calls == []
    assert [event["type"] for event in events] == ["status", "embeds"]
    assert normalized_events(events) == [
        _status(reason, 1 if japanese else 0),
        embed_event(reason, metadata),
    ]


@pytest.mark.parametrize("arm", ["dataset", "formula"])
@pytest.mark.parametrize("japanese", [False, True], ids=["en", "ja"])
def test_c7_pass_emits_files_then_one_all_pass_embed(
    arm: str,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    *,
    japanese: bool,
) -> None:
    """C7: both production arms, both languages, exact PASS rewrite and no INFO+ or status."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    metadata: dict[str, object] = {
        "session_id": "session",
        "user_message": {"content": "カ" if japanese else "English"},
    }
    if arm == "formula":
        case = replace(_case("pass"), metadata=metadata)
        result, calls, events, _completed = _exercise(case, load_filter_module())
        text = _expected_pass()
    else:
        content = b"key,value\nwest,1.25\neast,2.5\n"
        source = (
            "import pandas as pd\nimport matplotlib.pyplot as plt\n"
            'df = pd.read_csv("/mnt/uploads/chart.csv")\n'
            'plt.bar(df["key"], df["value"])\nplt.show()\n'
        )
        verified = verify_python_source(
            source, declared_target=DatasetTarget("/mnt/uploads/chart.csv", content)
        )
        assert isinstance(verified, Verified)
        calls = []
        events = []

        async def rpc(payload: dict[str, object]) -> object:
            calls.append(payload)
            return {"stdout": stdout_for_verified(verified, valid_png_uri()), "stderr": None}

        async def emit(event: dict[str, object]) -> None:
            events.append(event)

        with fake_open_webui([StoredFile("upload", "owner", "chart.csv", content)], tmp_path):
            result = invoke_filter(
                load_filter_module(),
                filter_body("MODEL_REPLY_SENTINEL"),
                request=recorded_request(source, ("upload",)),
                user={"id": "owner"},
                metadata=metadata,
                event_call=rpc,
                event_emitter=emit,
            )
        text = "Figure verification passed\n\n" + verified.certificate.interpretation
    assert_filter_text(result, text)
    assert len(calls) == 1
    assert [event["type"] for event in events] == ["files", "embeds"]
    assert normalized_events(events) == [_files(), embed_event(None, metadata)]
    assert _records(caplog) == []


@pytest.mark.parametrize("name", _EXCEPTION_CASES)
@pytest.mark.parametrize("channel", ["status", "embeds"])
@pytest.mark.parametrize("when", ["call", "await"])
def test_c8_emit_exception_keeps_the_other_diagnostic_and_the_verdict(
    name: str,
    channel: str,
    when: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """C8: Exception on either emitter seam cannot remove the other diagnostic or files/log."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    harness = _Harness(_case(name), load_filter_module())

    async def complete(event: dict[str, object]) -> None:
        if event["type"] == channel and when == "await":
            failure = "DIAGNOSTIC_AWAIT_SENTINEL"
            raise RuntimeError(failure)

    def emit(event: dict[str, object]) -> Awaitable[object]:
        if event["type"] == channel and when == "call":
            failure = "DIAGNOSTIC_CALL_SENTINEL"
            raise ValueError(failure)
        return complete(event)

    result = asyncio.run(harness.run(emit))
    _assert_result(harness.case, result, caplog)
    assert len(harness.calls) == harness.case.rpc_count
    _assert_events(harness.case, harness.events)


@pytest.mark.parametrize("name", _EXCEPTION_CASES)
def test_c8_renderer_exception_keeps_status_files_log_and_verdict(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    module = load_filter_module()
    calls: list[tuple[object, bool]] = []

    def broken(reason: object, *, japanese: bool, anchoring: str) -> str:
        assert anchoring == "strict"
        calls.append((reason, japanese))
        failure = "RENDERER_EXCEPTION_SENTINEL"
        raise LookupError(failure)

    renderer = importlib.import_module("webui.paste_in.checks")
    with monkeypatch.context() as patch:
        patch.setattr(renderer, "breakdown_html", broken)
        # Rebind either import style at the API seam, without requiring a filter-local alias.
        importlib.reload(module)
        harness = _Harness(_case(name), module)

        async def emit(_event: dict[str, object]) -> None:
            return None

        try:
            result = asyncio.run(harness.run(emit))
        finally:
            patch.undo()
            importlib.reload(module)
    _assert_result(harness.case, result, caplog)
    assert len(harness.calls) == harness.case.rpc_count
    _assert_events(harness.case, harness.events, embed=False)
    assert calls == [(None if name == "pass" else harness.case.reason, False)]


@pytest.mark.parametrize("name", _EXCEPTION_CASES[:-1])
def test_c8_pending_status_uses_one_deadline_and_skips_embed(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    module = load_filter_module()
    monkeypatch.setattr(module, "STATUS_TIMEOUT_SECONDS", 0.03)
    harness = _Harness(_case(name), module)
    cancelled: list[bool] = []

    async def scenario() -> dict[str, object]:
        async def emit(event: dict[str, object]) -> None:
            if event["type"] == "status":
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.append(True)

        task = asyncio.create_task(harness.run(emit))
        done, _pending = await asyncio.wait({task}, timeout=0.08)
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
    _assert_result(harness.case, result, caplog)
    assert cancelled == [True]
    _assert_events(harness.case, harness.events, embed=False)


@pytest.mark.parametrize("name", _EXCEPTION_CASES[:-1])
def test_c8_status_spends_the_embed_budget_too(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """C8: 70 ms status + pending embed fits ONE 100 ms budget, not two per-emit budgets."""
    caplog.set_level(logging.INFO, logger=_LOGGER)
    module = load_filter_module()
    monkeypatch.setattr(module, "STATUS_TIMEOUT_SECONDS", 0.1)
    harness = _Harness(_case(name), module)
    cancelled: list[bool] = []

    async def scenario() -> dict[str, object]:
        async def emit(event: dict[str, object]) -> None:
            if event["type"] == "status":
                await asyncio.sleep(0.07)
            elif event["type"] == "embeds":
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.append(True)

        task = asyncio.create_task(harness.run(emit))
        done, _pending = await asyncio.wait({task}, timeout=0.14)
        try:
            assert done, "status and embed each received a fresh deadline"
            return await task
        finally:
            if not done:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    result = asyncio.run(scenario())
    _assert_result(harness.case, result, caplog)
    assert cancelled == [True]
    _assert_events(harness.case, harness.events)


def test_c8_an_emit_never_starts_after_the_shared_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C8: a status call that exhausts the budget prevents a late embed call."""
    module = load_filter_module()
    monkeypatch.setattr(module, "STATUS_TIMEOUT_SECONDS", 0.002)
    harness = _Harness(_case("01-no-receipt"), module)

    async def complete() -> None:
        return None

    def emit(event: dict[str, object]) -> Awaitable[object]:
        if event["type"] == "status":
            time.sleep(0.006)
        return complete()

    result = asyncio.run(harness.run(emit))
    assert_filter_text(result, _FAIL)
    _assert_events(harness.case, harness.events, embed=False)


def test_c8_a_blocking_emitter_call_spends_the_shared_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C8 (reviewer-1 K3): the wait after a blocking emitter call gets only the time left.

    The emitter blocks 150 ms inside a 200 ms budget and returns a pending awaitable: the outlet
    returns near 200 ms, where a remainder measured before the call waited the full 200 ms again.
    """
    module = load_filter_module()
    monkeypatch.setattr(module, "STATUS_TIMEOUT_SECONDS", 0.2)
    harness = _Harness(_case("01-no-receipt"), module)

    async def complete() -> None:
        return None

    def emit(event: dict[str, object]) -> Awaitable[object]:
        if event["type"] == "status":
            time.sleep(0.15)
            return asyncio.Event().wait()
        return complete()

    started = time.monotonic()
    result = asyncio.run(harness.run(emit))
    elapsed = time.monotonic() - started
    assert_filter_text(result, _FAIL)
    assert elapsed < 0.3, elapsed
    _assert_events(harness.case, harness.events, embed=False)


class _JumpLoop(asyncio.SelectorEventLoop):
    """Event loop whose clock jumps forward on demand, so a test decides when a deadline passes."""

    jump = 0.0

    def time(self) -> float:
        return super().time() + self.jump


@pytest.mark.parametrize("name", _EXCEPTION_CASES)
def test_c8_slow_embed_cancellation_cleanup_never_delays_the_verdict(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    module = load_filter_module()
    # No stall reaches this deadline: the embed's start jumps the loop clock past it, so the embed
    # always starts and the deadline then cancels it. The order check counts loop turns.
    monkeypatch.setattr(module, "STATUS_TIMEOUT_SECONDS", 3600)
    harness = _Harness(_case(name), module)
    cleanup: list[bool] = []

    async def scenario() -> dict[str, object]:
        release = asyncio.Event()

        async def emit(event: dict[str, object]) -> None:
            if event["type"] == "embeds":
                cast(_JumpLoop, asyncio.get_running_loop()).jump = 7200
                try:
                    await asyncio.Event().wait()
                finally:
                    cleanup.append(True)
                    await release.wait()

        task = asyncio.create_task(harness.run(emit))
        # The 30 s wall bound fires for a defect alone (an outlet that never cancels); a working
        # one cancels within a few loop turns of the jump.
        give_up = time.monotonic() + 30
        while not cleanup and not task.done() and time.monotonic() < give_up:
            await asyncio.sleep(0.001)
        # The cleanup now blocks on `release`; an outlet that does not await it finishes within
        # a few loop turns, one that does never finishes while `release` stays unset.
        for _ in range(1000):
            if task.done():
                break
            await asyncio.sleep(0)
        done = task.done()
        release.set()
        try:
            assert done, "outlet awaited the embed's cancellation cleanup"
            return await task
        finally:
            if not done:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    result = asyncio.run(scenario(), loop_factory=_JumpLoop)
    _assert_result(harness.case, result, caplog)
    assert cleanup == [True]
    _assert_events(harness.case, harness.events)


_CANCEL_CASES = tuple(
    (name, channel) for name in _EXCEPTION_CASES for channel in ("embeds",) if name == "pass"
) + tuple((name, channel) for name in _EXCEPTION_CASES[:-1] for channel in ("status", "embeds"))


@pytest.mark.parametrize("name,channel", _CANCEL_CASES)
@pytest.mark.parametrize("external", [False, True], ids=["self", "external"])
def test_c8_diagnostic_cancellation_propagates(name: str, channel: str, *, external: bool) -> None:
    harness = _Harness(_case(name), load_filter_module())

    async def scenario() -> None:
        started = asyncio.Event()

        async def emit(event: dict[str, object]) -> None:
            if event["type"] == channel:
                started.set()
                if not external:
                    raise asyncio.CancelledError
                await asyncio.Event().wait()

        task = asyncio.create_task(harness.run(emit))
        if external:
            await asyncio.wait_for(started.wait(), timeout=0.5)
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


@pytest.mark.parametrize("name", _EXCEPTION_CASES)
@pytest.mark.parametrize("metadata", [[], ["session_id"], "session_id", 7, object()])
def test_c8_non_dict_metadata_defaults_to_english_without_exception(
    name: str,
    metadata: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    harness = _Harness(_case(name), load_filter_module())

    async def emit(_event: dict[str, object]) -> None:
        return None

    result = asyncio.run(harness.run(emit, metadata=metadata))
    reason = harness.case.reason if name in _EXCEPTION_CASES[:2] else "no_browser"
    assert_filter_text(result, _FAIL)
    assert harness.calls == []
    _assert_log(caplog, reason)
    assert normalized_events(harness.events) == [_status(reason), embed_event(reason)]


@pytest.mark.parametrize("name", _EXCEPTION_CASES)
def test_c8_absent_emitter_has_no_diagnostics(name: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    harness = _Harness(_case(name), load_filter_module())
    result = asyncio.run(harness.run(None))
    reason = harness.case.reason if name in _EXCEPTION_CASES[:2] else "no_browser"
    assert_filter_text(result, _FAIL)
    assert harness.events == []
    assert harness.calls == []
    _assert_log(caplog, reason)


@pytest.mark.parametrize(
    "arm", [4, 10, 11, 12, 0], ids=["refusal", "loader", "sandbox", "image", "pass"]
)
def test_c9_embed_carries_no_untrusted_bytes(
    arm: int,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """C9: six independent taint sources, valid dataset and observation on the PASS control."""
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
        'plt.bar(df["key"], df["value"])\n' + f"# {source}\nplt.show()\n"
    )
    verified = verify_python_source(
        program, declared_target=DatasetTarget(f"/mnt/uploads/{filename}.csv", content)
    )
    assert isinstance(verified, Verified)
    if arm == 4:
        program += f"print('{source}')\n"
    stdout = out if arm == 12 else stdout_for_verified(verified, valid_png_uri(), prefix=out + "\n")
    stderr = (
        "loadPyodide is not defined " + err
        if arm == 10
        else "Traceback (most recent call last):\n" + err
        if arm == 11
        else ""
    )
    events: list[dict[str, object]] = []

    async def rpc(_payload: dict[str, object]) -> object:
        return {"stdout": stdout, "stderr": stderr}

    async def emit(event: dict[str, object]) -> None:
        events.append(event)

    with fake_open_webui([StoredFile("upload", "owner", filename + ".csv", content)], tmp_path):
        result = invoke_filter(
            load_filter_module(),
            filter_body(out),
            request=recorded_request(program, ("upload",), request),
            user={"id": "owner"},
            metadata={"session_id": "session", "user_message": {"content": request}},
            event_call=rpc,
            event_emitter=emit,
        )
    reasons = {
        4: "call_target_not_admitted",
        10: "sandbox_unavailable",
        11: "sandbox_error",
        12: "no_image",
    }
    reason = reasons.get(arm)
    assert_filter_text(
        result,
        "Figure verification passed\n\n" + verified.certificate.interpretation
        if arm == 0
        else _FAIL,
    )
    embeds = [event for event in events if event["type"] == "embeds"]
    assert len(embeds) == 1
    assert normalized_events(embeds) == [embed_event(reason)]
    data = cast(dict[str, object], embeds[0]["data"])
    document = cast(list[str], data["embeds"])[0]
    surfaced = document + repr(parse_document(document))
    for sentinel in sentinels:
        assert sentinel not in surfaced
