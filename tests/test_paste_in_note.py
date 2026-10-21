# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q78 (`.agent/archive/contracts/q78.md`): the model's note — a request that the chart rules
override is stated in the reply, shown inert under the verdict, and never moves a verdict."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Coroutine, Iterator
from pathlib import Path
from typing import Any, cast

import pytest

from outlet_support import FAIL, PASS, SESSION, SIMPLE, TRUNCATED, USER, Browser, load, verdict
from paste_in_support import fake_open_webui, filter_body, filter_request, owui_driver_output
from verifier.figure.inert import prose
from verifier.figure.judge import Passed, Sources

_NOTE = "The request asked for plt.ylim(30000, 45000). The chart starts the y axis at 0 instead."
_HOSTILE = (
    "![x](http://example.invalid/?q=data) <img src=x onerror=alert(1)> \\(x\\) $x$ ``` "
    "[link](javascript:alert(1)) **bold** \u202eevil\nsecond line\r\n# heading"
)
# "in the language of the request" made gpt-6-luna write English notes in Spanish or French (6 of
# 6 live + bridge runs); naming the language by the kana rule fixed it (3 of 3 each).
_REQUEST_ON = (
    "\nIf the request, taken as written, asks for anything that the chart rules above do not"
    " allow, follow the rules. Then use the note argument of draw_figure to say what the request"
    " asked for and what the chart shows instead. Write the note in {language}. When the chart"
    " follows the request, leave the note empty.\n"
)
_PARAM = (
    "Empty unless the request, taken as written, asks for something these rules do not allow:"
    " then what the request asked for and what the chart shows instead."
)


@pytest.fixture(autouse=True)
def _empty_store(tmp_path: Path) -> Iterator[None]:
    with fake_open_webui((), tmp_path):
        yield


def _filter(module: str = "filter", *, valve: bool | None = None) -> Any:
    api = load(module)
    instance = api.Filter()
    if valve is not None:
        instance.valves = api.Filter.Valves(model_note=valve)
    return instance


def _outlet(  # noqa: PLR0913 - the receipt's note plus the outlet's reserved arguments
    program: str,
    note: str,
    *,
    valve: bool | None = None,
    request_text: str | None = None,
    receipt: bool = True,
    metadata: dict[str, object] | None = None,
) -> tuple[dict[str, object], Browser]:
    browser = Browser(program)
    request = filter_request()
    if receipt:
        module = load("receipt")
        module.write_receipt(request, module.Receipt(program, (), request_text, (), note))
    result = asyncio.run(
        cast(
            Coroutine[Any, Any, dict[str, object]],
            _filter(valve=valve).outlet(
                filter_body("MODEL_PROSE"),
                __user__=USER,
                __request__=request,
                __event_call__=browser.call,
                __event_emitter__=browser.emit,
                __metadata__=metadata
                or {"session_id": SESSION, "user_message": {"content": request_text}},
            ),
        )
    )
    return result, browser


def _unidentified(calls: list[dict[str, object]]) -> list[dict[str, object]]:
    """The RPC payloads with each call's fresh uuid4 id masked."""
    return [
        {**call, "data": {**cast(dict[str, object], call["data"]), "id": None}} for call in calls
    ]


def _reply(body: dict[str, object]) -> str:
    message = cast(list[dict[str, object]], body["messages"])[-1]
    content = cast(str, message["content"])
    item = cast(list[dict[str, object]], message["output"])
    assert item == [
        {
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": content}],
        }
    ]
    return content


def test_q78_n1_the_tool_records_the_note_beside_the_program() -> None:
    tool = load("tool").Tools()
    for note, recorded in ((_NOTE, _NOTE), ("", ""), (None, ""), (3, ""), (["x"], "")):
        request = filter_request()
        asyncio.run(
            cast(
                Coroutine[Any, Any, object],
                tool.draw_figure(SIMPLE, note, __request__=request),
            )
        )
        receipt = load("receipt").read_receipt(request)
        assert receipt is not None and receipt.program == SIMPLE and receipt.note == recorded
    request = filter_request()
    asyncio.run(cast(Coroutine[Any, Any, object], tool.draw_figure(SIMPLE, __request__=request)))
    assert load("receipt").read_receipt(request).note == ""


def test_q78_n1_open_webui_offers_the_note_as_an_optional_argument(tmp_path: Path) -> None:
    """Open WebUI's own spec builder over the committed production artifact."""
    (tmp_path / "owui").mkdir()
    payload = owui_driver_output(
        """
        import asyncio
        import json
        import pathlib

        from open_webui.utils.plugin import load_tool_module_by_id
        from open_webui.utils.tools import get_tool_specs

        async def main():
            artifact = pathlib.Path(__file__).with_name("figure_verification_tool.py")
            tool, _frontmatter, _module = await load_tool_module_by_id(
                "q78_note_test", content=artifact.read_text(encoding="utf-8")
            )
            print("Q78_SPECS=" + json.dumps([spec["parameters"] for spec in get_tool_specs(tool)]))

        asyncio.run(main())
        """,
        tmp_path / "owui",
        "Q78_SPECS",
    )
    (parameters,) = json.loads(payload)
    assert parameters["required"] == ["program"]
    assert set(parameters["properties"]) == {"program", "note"}
    assert " ".join(parameters["properties"]["note"]["description"].split()) == _PARAM


@pytest.mark.parametrize(
    ("task", "language"),
    [("Chart a 1, b 2", "English"), ("a 1、b 2 をグラフに", "Japanese"), ("漢字 1", "English")],
)
def test_q78_n3_the_inlet_asks_for_the_note_only_while_the_valve_is_on(
    task: str, language: str
) -> None:
    body: dict[str, object] = {"messages": [{"role": "user", "content": task}]}
    rendered = {}
    for module, valve in (("filter", None), ("filter", False), ("demo_filter", None)):
        result = asyncio.run(
            cast(
                Coroutine[Any, Any, dict[str, object]],
                _filter(module, valve=valve).inlet(body, __user__=USER, __metadata__={}),
            )
        )
        rendered[module, valve] = cast(list[dict[str, str]], result["messages"])[0]["content"]
    templates = load("templates")
    production = templates.PRODUCTION_TEMPLATES.no_file.format(task=task)
    assert rendered["filter", None] == production + _REQUEST_ON.format(language=language)
    assert rendered["filter", False] == production
    assert rendered["demo_filter", None] == templates.DEMO_TEMPLATES.no_file.format(task=task)
    assert templates.NOTE_REQUEST == _REQUEST_ON


def test_q78_n8_the_valve_is_on_in_production_and_off_in_the_demo() -> None:
    assert load("filter").Filter.Valves().model_note is True
    assert load("demo_filter").Filter.Valves().model_note is False
    assert load("demo_filter").Filter.Valves(model_note=True).model_note is True


@pytest.mark.parametrize(
    ("request_text", "label"),
    [("Chart it", "**Model note:**"), ("グラフにして", "**モデルの注記:**")],
)
def test_q78_n4_a_pass_shows_the_note_under_the_interpretation(
    request_text: str, label: str
) -> None:
    result, _browser = _outlet(SIMPLE, f"  {_NOTE}\n", request_text=request_text)
    expected = verdict(SIMPLE, Sources(request=request_text))
    assert isinstance(expected, Passed)
    japanese = label != "**Model note:**"
    interpretation = expected.interpretation_ja if japanese else expected.interpretation
    assert _reply(result) == f"{PASS}\n\n{interpretation}\n\n{label} {prose(_NOTE)}"


def test_q78_n4_a_failure_shows_the_note_under_the_verdict() -> None:
    result, browser = _outlet(TRUNCATED, _NOTE)
    assert _reply(result) == f"{FAIL}\n\n**Model note:** {prose(_NOTE)}"
    assert [event["type"] for event in browser.events] == ["status", "embeds"]


def test_q78_n4_a_failure_before_the_browser_shows_the_note_too() -> None:
    result, browser = _outlet(SIMPLE, _NOTE, metadata={"user_message": {"content": "x"}})
    assert _reply(result) == f"{FAIL}\n\n**Model note:** {prose(_NOTE)}"
    assert browser.calls == []


@pytest.mark.parametrize("note", ["", " ", "\n\t \u3000"])
def test_q78_n4_a_blank_note_adds_nothing(note: str) -> None:
    for program in (SIMPLE, TRUNCATED):
        with_note, _ = _outlet(program, note)
        without, _ = _outlet(program, "")
        assert _reply(with_note) == _reply(without)
        assert "Model note" not in _reply(with_note)


def test_q78_n4_no_receipt_means_no_note() -> None:
    result, _browser = _outlet(SIMPLE, _NOTE, receipt=False)
    assert _reply(result) == FAIL


@pytest.mark.parametrize("program", [SIMPLE, TRUNCATED])
@pytest.mark.parametrize("note", [_NOTE, _HOSTILE, "x" * 20_000])
def test_q78_n5_the_note_never_moves_the_verdict_or_the_diagnostics(
    program: str, note: str
) -> None:
    """Differential: the same receipt with and without a note sends the same RPC, emits the same
    files, status and check-list events, and replies the same text up to the note line."""
    base, base_browser = _outlet(program, "")
    noted, noted_browser = _outlet(program, note)
    assert _unidentified(noted_browser.calls) == _unidentified(base_browser.calls)
    assert noted_browser.events == base_browser.events
    assert _reply(noted) == f"{_reply(base)}\n\n**Model note:** {prose(note.strip())}"


@pytest.mark.parametrize("program", [SIMPLE, TRUNCATED])
def test_q78_n6_the_valve_off_shows_today_s_reply(program: str) -> None:
    off, _ = _outlet(program, _NOTE, valve=False)
    base, _ = _outlet(program, "", valve=False)
    assert (
        _reply(off)
        == _reply(base)
        == (
            FAIL
            if program == TRUNCATED
            else f"{PASS}\n\n{cast(Passed, verdict(program)).interpretation}"
        )
    )


def test_q79_a_hostile_note_stays_escaped_text_on_one_line() -> None:
    """Q79 (`.agent/archive/contracts/q79.md`): the note shows as plain text after the bold label,
    every markup character escaped (`inert.prose`), on the label's line."""
    result, _browser = _outlet(SIMPLE, _HOSTILE)
    line = _reply(result).rsplit("\n\n", 1)[1]
    assert line == f"**Model note:** {prose(_HOSTILE.strip())}"
    assert "\n" not in line and "\r" not in line
    assert "<" not in line.replace("\\<", "") and "](" not in line.replace("\\](", "")


@pytest.mark.parametrize("program", [SIMPLE, TRUNCATED])
def test_q78_n4_the_note_renders_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch, program: str
) -> None:
    """The note has no length limit (user): an 8 MB note took 2.7 s to render (CPython 3.14), so
    like every input-sized step since M22.1 it runs off Open WebUI's event loop."""
    loop = threading.get_ident()
    api = load("filter")
    original = api._note_line
    threads: list[int] = []

    def recorded(note: str, metadata: object) -> str:
        threads.append(threading.get_ident())
        return cast(str, original(note, metadata))

    monkeypatch.setattr(api, "_note_line", recorded)
    result, _browser = _outlet(program, _NOTE)
    assert _reply(result).endswith(f"\n\n**Model note:** {prose(_NOTE)}")
    assert threads and loop not in threads


def test_q78_n4_a_fault_rendering_the_note_never_fails_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed reply renders the note on its way out; a fault there must still block."""
    api = load("filter")

    async def broken(*_args: object, **_kwargs: object) -> str:
        message = "PRIVATE_FAULT"
        raise RuntimeError(message)

    monkeypatch.setattr(api.asyncio, "to_thread", _only_note(api.asyncio.to_thread, broken))
    result, _browser = _outlet(TRUNCATED, _NOTE)
    assert _reply(result) == FAIL


def _only_note(original: Any, broken: Any) -> Any:
    async def to_thread(function: Any, /, *args: Any, **kwargs: Any) -> Any:
        if getattr(function, "__name__", "") == "_note_line":
            return await broken()
        return await original(function, *args, **kwargs)

    return to_thread
