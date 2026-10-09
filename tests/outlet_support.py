# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M19.5 contract oracle: literal stages, strict RPC, real-reader fixtures, parsed HTML."""

from __future__ import annotations

import importlib
import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from types import ModuleType
from typing import Never, cast
from uuid import UUID

import pytest

from paste_in_support import REPO_ROOT, filter_body, invoke_filter, recorded_request
from verifier.figure.description import parse_description
from verifier.figure.judge import Passed, Sources, judge
from verifier.figure.reader import run
from verifier.figure.reasons import Blocked
from webui.paste_in.sandbox import wrapper_code

PASS = "Figure verification passed"  # noqa: S105 - public verdict, not a credential
FAIL = "Figure verification failed, no image produced"
USER: dict[str, object] = {"id": "outlet-owner"}
SESSION = "browser-session"
LOGGER = "webui.paste_in.filter"
ORDER = ("program", "run", "figure", "parts", "axes", "marks", "values", "columns", "attach")
REASON_GROUPS = {
    "program": ("no_tool_call", "no_user"),
    "run": (
        "no_browser",
        "browser_timeout",
        "browser_error",
        "browser_no_answer",
        "reply_malformed",
        "sandbox_unavailable",
        "sandbox_error",
        "no_description",
        "program_syntax_error",
        "program_error",
        "module_not_available",
        "figure_too_large",
    ),
    "figure": ("no_figure", "multiple_figures", "glyph_missing"),
    "parts": (
        "raster_image",
        "axes_not_judged",
        "axes_twin",
        "axes_overlap",
        "artist_not_judged",
        "no_data",
    ),
    "axes": (
        "mark_not_in_data",
        "scale_not_linear",
        "axis_inverted",
        "tick_label_mismatch",
        "point_clipped",
        "zero_not_in_limits",
    ),
    "marks": (
        "mark_hidden",
        "value_not_finite",
        "bar_not_from_zero",
        "bars_overlap",
        "x_not_ordered",
        "hist_counts",
        "pie_not_whole",
        "area_not_from_zero",
        "marker_size_varies",
        "marker_color_varies",
        "legend_mismatch",
    ),
    "values": (
        "csv_too_large",
        "csv_not_parsable",
        "work_budget_exceeded",
        "category_not_unique",
        "value_not_found",
        "label_not_in_request",
    ),
    "columns": ("column_not_requested", "column_not_named", "label_not_consistent"),
    "attach": ("no_image", "publish_failed"),
}
REASON_CHECK = {reason: check for check, reasons in REASON_GROUPS.items() for reason in reasons}
CAUSES = {
    "no_tool_call",
    "no_user",
    "no_browser",
    "browser_timeout",
    "browser_error",
    "browser_no_answer",
    "reply_malformed",
    "sandbox_unavailable",
    "sandbox_error",
    "no_description",
    "no_image",
    "publish_failed",
}
FIGURE_REASONS = set(REASON_CHECK) - CAUSES
ANCHORS = {
    "value_not_found": (
        "A drawn value is not in your data. Attach a CSV file or write the values in your request.",
        "描画した値がデータにありません。CSV ファイルを添付するか、依頼文に値を書いてください。",
    ),
    "bar_not_from_zero": (
        "A bar does not start at zero.",
        "ゼロから始まっていない棒があります。",
    ),
    "no_description": (
        "The browser run did not report the drawn figure.",
        "ブラウザが描画した図を報告しませんでした。",
    ),
    "sandbox_unavailable": (
        "The browser could not load Pyodide. Turn off the ad blocker for this site.",
        "Pyodide を読み込めません。このサイトの広告ブロッカーをオフにしてください。",
    ),
}
SPECIFICATION = (
    "https://github.com/eturkes/figure-verification/blob/main/docs/verification.md",
    "https://github.com/eturkes/figure-verification/blob/main/docs/verification.ja.md",
)
SIMPLE = "import matplotlib.pyplot as plt\nplt.bar([0, 1, 2], [3, 5, 9])\nplt.show()\n"
SALES = "import matplotlib.pyplot as plt\nplt.bar(['EU', 'US'], [34000, 40000])\nplt.show()\n"
TRUNCATED = SALES.replace("plt.show()", "plt.ylim(30000, 45000)\nplt.show()")
SALES_BYTES = (REPO_ROOT / "data/sales.csv").read_bytes()


def load(name: str) -> ModuleType:
    module = importlib.import_module("webui.paste_in." + name)
    assert Path(cast(str, module.__file__)).resolve().is_relative_to(REPO_ROOT)
    return module


def texts() -> dict[str, tuple[str, str]]:
    return cast(dict[str, tuple[str, str]], load("reasons").REASONS)


@dataclass
class Text:
    value: str
    source: str


@dataclass
class Node:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    children: list[Node | Text] = field(default_factory=list)

    def nodes(self, *, tag: str | None = None, cls: str | None = None) -> list[Node]:
        found = []
        for child in self.children:
            if isinstance(child, Node):
                if (tag is None or child.tag == tag) and (
                    cls is None or cls in (child.attrs.get("class") or "").split()
                ):
                    found.append(child)
                found.extend(child.nodes(tag=tag, cls=cls))
        return found

    def text(self, *, excluding: str | None = None, raw: bool = False) -> str:
        return "".join(
            (child.source if raw else child.value)
            if isinstance(child, Text)
            else child.text(excluding=excluding, raw=raw)
            for child in self.children
            if isinstance(child, Text) or excluding not in (child.attrs.get("class") or "").split()
        )


class Document(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.root = Node("document")
        self.stack = [self.root]
        self.feed(source)
        self.close()
        assert self.stack == [self.root], "unclosed HTML elements"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        assert len(attrs) == len(dict(attrs))
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in {"meta", "link", "br", "hr", "img", "input", "wbr"}:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        assert len(self.stack) > 1 and self.stack[-1].tag == tag, f"unbalanced HTML: {tag}"
        self.stack.pop()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(Text(data, data))

    def handle_entityref(self, name: str) -> None:
        source = f"&{name};"
        self.stack[-1].children.append(Text(unescape(source), source))

    def handle_charref(self, name: str) -> None:
        source = f"&#{name};"
        self.stack[-1].children.append(Text(unescape(source), source))


def one(nodes: list[Node]) -> Node:
    assert len(nodes) == 1
    return nodes[0]


def rows(html: str) -> dict[str, Node]:
    root = Document(html).root
    items = one(root.nodes(tag="ol")).nodes(tag="li")
    assert len(items) == 9, "M19.5 requires exactly nine check rows"
    return dict(zip(ORDER, items, strict=True))


def listing(row: Node) -> tuple[tuple[int, bool, str, tuple[str, ...]], ...]:
    return tuple(
        (
            int(one(line.nodes(cls="ln")).text()),
            "at" in (line.attrs.get("class") or "").split(),
            one(line.nodes(cls="src")).text(),
            tuple(mark.text() for mark in line.nodes(tag="mark")),
        )
        for line in row.nodes(cls="line")
    )


def embed(events: list[dict[str, object]]) -> str:
    selected = [event for event in events if event.get("type") == "embeds"]
    assert len(selected) == 1
    assert set(selected[0]) == {"type", "data"}
    data = selected[0]["data"]
    assert isinstance(data, dict) and set(data) == {"embeds", "replace"}
    assert data["replace"] is True
    values = data["embeds"]
    assert isinstance(values, list) and len(values) == 1 and isinstance(values[0], str)
    return values[0]


def assert_states(html: str, reason: str | None) -> None:
    stop = len(ORDER) if reason is None else ORDER.index(REASON_CHECK[reason])
    for i, row in enumerate(rows(html).values()):
        expected = "pass" if i < stop else "fail" if i == stop else "skip"
        assert row.attrs.get("class") == expected
        assert (
            one(row.nodes(cls="mark")).text()
            == {"pass": "✓", "fail": "✗", "skip": "\u2013"}[expected]
        )


def assert_rewrite(body: dict[str, object], expected: str) -> None:
    messages = cast(list[dict[str, object]], body["messages"])
    last = next(message for message in reversed(messages) if message["role"] == "assistant")
    assert last["content"] == expected
    assert last["output"] == [
        {
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": expected}],
        }
    ]


def assert_failure(
    body: dict[str, object], events: list[dict[str, object]], reason: str, *, japanese: bool = False
) -> None:
    assert_rewrite(body, FAIL)
    assert events[0] == {
        "type": "status",
        "data": {"description": f"{texts()[reason][int(japanese)]} ({reason})", "done": True},
    }
    assert [event["type"] for event in events] == ["status", "embeds"]
    assert_states(embed(events), reason)


def log_records(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str]]:
    return [(r.levelno, r.getMessage()) for r in caplog.records if r.name == LOGGER]


def assert_log(caplog: pytest.LogCaptureFixture, reason: str | None) -> None:
    assert log_records(caplog) == (
        [] if reason is None else [(logging.INFO, "figure verification failed reason=" + reason)]
    )


@lru_cache(maxsize=64)
def output(program: str) -> str:
    return run(program)


def verdict(program: str, sources: Sources | None = None) -> Passed | Blocked:
    description = parse_description(output(program))
    assert description is not None
    return judge(description, Sources() if sources is None else sources)


@dataclass
class Browser:
    program: str = SIMPLE
    files: list[dict[str, str]] = field(default_factory=list)
    font: bytes | None = None
    calls: list[dict[str, object]] = field(default_factory=list)
    events: list[dict[str, object]] = field(default_factory=list)
    session: str = SESSION

    async def call(self, payload: dict[str, object]) -> object:
        self.calls.append(payload)
        assert set(payload) == {"type", "data"}
        assert payload["type"] == "execute:python"
        data = payload["data"]
        assert isinstance(data, dict) and set(data) == {"id", "code", "session_id", "files"}
        identifier = data["id"]
        assert isinstance(identifier, str) and str(UUID(identifier)) == identifier
        assert UUID(identifier).version == 4
        assert data["session_id"] == self.session
        assert data["files"] == self.files
        assert data["code"] == wrapper_code(self.program, self.font)
        # Font transport is pinned above; ASCII chart fixtures need no host font registration.
        return {"stdout": output(self.program), "stderr": None}

    async def emit(self, event: dict[str, object]) -> None:
        self.events.append(event)

    def exercise(
        self,
        *,
        request_text: str | None = None,
        file_ids: tuple[str, ...] = (),
        aliases: tuple[tuple[str, str], ...] = (),
        demo: bool = False,
    ) -> dict[str, object]:
        return invoke_filter(
            load("demo_filter" if demo else "filter"),
            filter_body("MODEL_NARRATION"),
            request=recorded_request(self.program, file_ids, request_text, aliases),
            user=USER,
            metadata={"session_id": self.session, "user_message": {"content": request_text}},
            event_call=self.call,
            event_emitter=self.emit,
        )


@dataclass
class Bomb:
    calls: int = 0

    def __call__(self, *_args: object, **_kwargs: object) -> Never:
        self.calls += 1
        message = "downstream operation ran before its guard"
        raise AssertionError(message)


@contextmanager
def patched_filter(
    monkeypatch: pytest.MonkeyPatch, patches: tuple[tuple[str, str, object], ...]
) -> Iterator[ModuleType]:
    """Patch public dependency seams, then bind either import style without source inspection."""
    module = load("filter")
    with monkeypatch.context() as patch:
        for name, attribute, replacement in patches:
            dependency = importlib.import_module(name)
            patch.setattr(dependency, attribute, replacement)
        importlib.reload(module)
        try:
            yield module
        finally:
            patch.undo()
            importlib.reload(module)


type EventCall = Callable[[dict[str, object]], Awaitable[object]]
