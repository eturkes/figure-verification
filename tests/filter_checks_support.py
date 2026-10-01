# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M16.1 semantic embed oracle; states come from literals, production supplies text alone."""

from __future__ import annotations

import importlib
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import cast

CHECK_IDS = (
    "program",
    "data",
    "readable",
    "accepted",
    "chart",
    "binding",
    "recompute",
    "integrity",
    "render",
    "match",
    "attach",
)
_REASON_GROUPS = {
    "program": ("no_tool_call",),
    "data": ("no_user", "no_target"),
    "readable": (
        "source_too_large",
        "source_not_utf8",
        "source_has_nul",
        "line_too_long",
        "source_not_tokenizable",
        "too_many_tokens",
        "nesting_too_deep",
        "unbalanced_brackets",
        "indent_too_deep",
        "source_not_parsable",
    ),
    "accepted": (
        "statement_not_admitted",
        "expression_not_admitted",
        "import_not_admitted",
        "assign_target_not_admitted",
        "call_target_not_admitted",
        "keyword_not_admitted",
        "attribute_not_admitted",
        "operator_not_admitted",
        "literal_not_admitted",
        "name_not_bound",
        "column_not_literal",
    ),
    "chart": (
        "no_mark",
        "multiple_marks",
        "mark_arity_not_projected",
        "mark_not_valid_for_arm",
        "x_not_a_grid",
        "y_not_over_grid",
        "grid_not_representable",
        "expression_not_projected",
        "label_not_literal",
        "name_rebound",
        "no_terminal",
        "statement_after_terminal",
        "statement_not_projected",
        "arm_ambiguous",
        "no_source",
        "multiple_sources",
        "source_not_literal",
        "column_not_from_source",
        "aggregation_not_projected",
        "figure_orphans_mark",
    ),
    "binding": ("source_not_supplied", "target_mismatch"),
    "recompute": (
        "csv_too_large",
        "csv_not_parsable",
        "column_not_present",
        "column_not_numeric",
        "value_not_in_profile",
        "value_not_finite",
        "work_budget_exceeded",
    ),
    "integrity": ("category_not_unique", "x_not_ordered"),
    "render": (
        "no_browser",
        "browser_timeout",
        "browser_error",
        "browser_no_answer",
        "reply_malformed",
        "sandbox_unavailable",
        "sandbox_error",
        "no_image",
    ),
    "match": ("no_observation", "observation_mismatch"),
    "attach": ("publish_failed",),
}
REASON_CHECK = {reason: check for check, reasons in _REASON_GROUPS.items() for reason in reasons}
_MARKS = {
    "pass": ("✓", ("passed", "合格")),
    "fail": ("✗", ("failed", "不合格")),
    "skip": ("\u2013", ("not checked", "未実施")),
}


@dataclass(frozen=True)
class CheckRow:
    state: str
    glyph: str
    label: str
    title: str
    covers: str
    unrun: str | None = None
    cause: str | None = None


@dataclass(frozen=True)
class ChecksDocument:
    language: str
    show: str
    hide: str
    rows: tuple[CheckRow, ...]


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    children: list[_Node | str] = field(default_factory=list)

    def descendants(self) -> list[_Node]:
        return [
            node
            for child in self.children
            if isinstance(child, _Node)
            for node in (child, *child.descendants())
        ]

    def text(self, *, omit: str = "") -> str:
        return "".join(
            child if isinstance(child, str) else child.text(omit=omit)
            for child in self.children
            if isinstance(child, str) or omit not in (child.attrs.get("class") or "").split()
        )


class _DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, dict(attrs))
        assert len(node.attrs) == len(attrs), "duplicate HTML attribute"
        self.stack[-1].children.append(node)
        if tag not in {"meta", "br", "hr", "input", "img", "link", "wbr"}:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        assert len(self.stack) > 1 and self.stack[-1].tag == tag, "unbalanced document"
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def _one(nodes: list[_Node], *, tag: str = "", cls: str = "") -> _Node:
    selected = [
        node
        for node in nodes
        if (not tag or node.tag == tag)
        and (not cls or cls in (node.attrs.get("class") or "").split())
    ]
    assert len(selected) == 1, f"expected one {tag or cls}, got {len(selected)}"
    return selected[0]


def parse_document(html: str) -> ChecksDocument:
    """Reject C4 shape drift before normalizing whitespace-independent presentation."""
    parser = _DocumentParser()
    parser.feed(html)
    parser.close()
    assert len(parser.stack) == 1, "unclosed HTML element"
    nodes = parser.root.descendants()
    language = _one(nodes, tag="html").attrs.get("lang")
    assert language in {"en", "ja"}
    details = _one(nodes, tag="details")
    assert "open" not in details.attrs, "disclosure starts expanded"
    summary = _one(details.descendants(), tag="summary")
    show = _one(summary.descendants(), tag="span", cls="show")
    hide = _one(summary.descendants(), tag="span", cls="hide")
    assert summary.descendants().index(show) < summary.descendants().index(hide)
    listing = _one(nodes, tag="ol")
    assert listing in details.descendants()
    items = [node for node in listing.children if isinstance(node, _Node)]
    assert len(items) == len(CHECK_IDS) and all(node.tag == "li" for node in items)
    assert len([node for node in nodes if node.tag == "li"]) == len(CHECK_IDS)
    rows = []
    for item in items:
        state = item.attrs.get("class")
        assert state in _MARKS, "row must have exactly one state class"
        children = item.descendants()
        mark = _one(children, tag="span", cls="mark")
        title = _one(children, cls="title")
        covers = _one(children, cls="covers")
        assert mark.attrs.get("role") == "img"
        label = mark.attrs.get("aria-label")
        assert isinstance(label, str)
        causes = [node for node in children if "cause" in (node.attrs.get("class") or "").split()]
        unruns = [node for node in children if "unrun" in (node.attrs.get("class") or "").split()]
        assert len(causes) == (1 if state == "fail" else 0)
        assert len(unruns) == (1 if state == "skip" else 0)
        if unruns:
            assert unruns[0].tag == "span" and unruns[0] in title.descendants()
        ordered = [mark, title, covers, *causes]
        assert [children.index(node) for node in ordered] == sorted(
            children.index(node) for node in ordered
        )
        rows.append(
            CheckRow(
                state,
                mark.text().strip(),
                label,
                title.text(omit="unrun").strip(),
                covers.text().strip(),
                unruns[0].text().strip() if unruns else None,
                causes[0].text().strip() if causes else None,
            )
        )
    return ChecksDocument(language, show.text().strip(), hide.text().strip(), tuple(rows))


def japanese(metadata: object) -> bool:
    """D5/C8: carrier reads are total; kana LETTER alone selects Japanese."""
    message = metadata.get("user_message") if isinstance(metadata, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    prefixes = ("HIRAGANA LETTER", "KATAKANA LETTER", "HALFWIDTH KATAKANA LETTER")
    return isinstance(content, str) and any(
        unicodedata.name(c, "").startswith(prefixes) for c in content
    )


def expected_document(reason: str | None, *, is_japanese: bool) -> ChecksDocument:
    module = importlib.import_module("webui.paste_in.checks")
    texts = cast(dict[str, tuple[tuple[str, str], tuple[str, str]]], module.TEXTS)
    reasons = cast(
        dict[str, tuple[str, str]], importlib.import_module("webui.paste_in.reasons").REASONS
    )
    index = 1 if is_japanese else 0
    stop = len(CHECK_IDS) if reason is None else CHECK_IDS.index(REASON_CHECK[reason])
    rows = []
    for position, check in enumerate(CHECK_IDS):
        state = "pass" if position < stop else "fail" if position == stop else "skip"
        glyph, labels = _MARKS[state]
        title, covers = texts[check][index]
        rows.append(
            CheckRow(
                state,
                glyph,
                labels[index],
                title,
                covers,
                ("not checked", "未実施")[index] if state == "skip" else None,
                reasons[cast(str, reason)][index] if state == "fail" else None,
            )
        )
    return ChecksDocument(
        "ja" if is_japanese else "en",
        ("Show checks", "チェック項目を表示")[index],
        ("Hide checks", "チェック項目を隠す")[index],
        tuple(rows),
    )


def embed_event(reason: str | None, metadata: object = None) -> dict[str, object]:
    """Expected event: exact transport keys, semantically parsed document, independent states."""
    return {
        "type": "embeds",
        "data": {
            "embeds": [expected_document(reason, is_japanese=japanese(metadata))],
            "replace": True,
        },
    }


def normalize_event(event: dict[str, object]) -> dict[str, object]:
    if event.get("type") != "embeds":
        return event
    assert set(event) == {"type", "data"}
    data = event["data"]
    assert isinstance(data, dict) and set(data) == {"embeds", "replace"}
    assert data["replace"] is True
    embeds = data["embeds"]
    assert isinstance(embeds, list) and len(embeds) == 1 and isinstance(embeds[0], str)
    return {"type": "embeds", "data": {"embeds": [parse_document(embeds[0])], "replace": True}}


def normalized_events(events: list[dict[str, object]]) -> list[dict[str, object]]:
    return [normalize_event(event) for event in events]
