# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M16.1 C1-C5: independent tables + parsed disclosure semantics.

Contract: `.agent/archive/contracts/m16u1.md`. The renderer implementation stays unread.
"""

from __future__ import annotations

import ast
import re
import unicodedata
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from importlib import import_module
from pathlib import Path
from typing import Literal, Protocol, cast, get_args

import pytest
from hypothesis import given
from hypothesis import strategies as st

from verifier.pysrc.errors import RefusalCode
from webui.paste_in import reasons
from webui.paste_in.reasons import OutletCause, Reason

_ORDER = (
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
_REASON_CHECK: dict[Reason, str] = {
    "no_tool_call": "program",
    "no_user": "data",
    "no_target": "data",
    "source_too_large": "readable",
    "source_not_utf8": "readable",
    "source_has_nul": "readable",
    "line_too_long": "readable",
    "source_not_tokenizable": "readable",
    "too_many_tokens": "readable",
    "nesting_too_deep": "readable",
    "unbalanced_brackets": "readable",
    "indent_too_deep": "readable",
    "source_not_parsable": "readable",
    "statement_not_admitted": "accepted",
    "expression_not_admitted": "accepted",
    "import_not_admitted": "accepted",
    "assign_target_not_admitted": "accepted",
    "call_target_not_admitted": "accepted",
    "keyword_not_admitted": "accepted",
    "attribute_not_admitted": "accepted",
    "operator_not_admitted": "accepted",
    "literal_not_admitted": "accepted",
    "name_not_bound": "accepted",
    "column_not_literal": "accepted",
    "no_mark": "chart",
    "multiple_marks": "chart",
    "mark_arity_not_projected": "chart",
    "mark_not_valid_for_arm": "chart",
    "x_not_a_grid": "chart",
    "y_not_over_grid": "chart",
    "grid_not_representable": "chart",
    "expression_not_projected": "chart",
    "label_not_literal": "chart",
    "name_rebound": "chart",
    "no_terminal": "chart",
    "statement_after_terminal": "chart",
    "statement_not_projected": "chart",
    "arm_ambiguous": "chart",
    "no_source": "chart",
    "multiple_sources": "chart",
    "source_not_literal": "chart",
    "column_not_from_source": "chart",
    "aggregation_not_projected": "chart",
    "figure_orphans_mark": "chart",
    "source_not_supplied": "binding",
    "target_mismatch": "binding",
    "column_not_requested": "binding",
    "csv_too_large": "recompute",
    "csv_not_parsable": "recompute",
    "column_not_present": "recompute",
    "column_not_numeric": "recompute",
    "value_not_in_profile": "recompute",
    "value_not_finite": "recompute",
    "work_budget_exceeded": "recompute",
    "category_not_unique": "integrity",
    "x_not_ordered": "integrity",
    "label_not_consistent": "integrity",
    "no_browser": "render",
    "browser_timeout": "render",
    "browser_error": "render",
    "browser_no_answer": "render",
    "reply_malformed": "render",
    "sandbox_unavailable": "render",
    "sandbox_error": "render",
    "no_image": "render",
    "no_observation": "match",
    "observation_mismatch": "match",
    "publish_failed": "attach",
}
_UI = {
    "SHOW": ("Show checks", "チェック項目を表示"),
    "HIDE": ("Hide checks", "チェック項目を隠す"),
    "UNRUN": ("not checked", "未実施"),
}
_State = Literal["pass", "fail", "skip"]
_MARKS: dict[_State, tuple[str, tuple[str, str]]] = {
    "pass": ("✓", ("passed", "合格")),
    "fail": ("✗", ("failed", "不合格")),
    "skip": ("–", ("not checked", "未実施")),  # noqa: RUF001 - contract glyph
}
_TextPair = tuple[tuple[str, str], tuple[str, str]]
_ANCHORS: dict[str, _TextPair] = {
    "recompute": (
        (
            "Plotted values recomputed from your data",
            "file readable, columns present, y numeric, x numeric or categories, values in "
            "accepted form and size, results finite, computation within the limit",
        ),
        (
            "描画する値をデータから再計算",
            "ファイルの読み取り、列の有無、y は数値、x は数値またはカテゴリ、値の形式と大きさ、"
            "結果が有限、計算量の上限",
        ),
    ),
    "integrity": (
        (
            "Chart integrity",
            "bars from zero, one set of axes, linear scales, no row dropped, no repeated "
            "category, line x never decreasing or in file order, consistent labels",
        ),
        (
            "グラフの完全性",
            "棒はゼロから、軸は 1 組、線形の目盛り、行の欠落なし、カテゴリの重複なし、"
            "折れ線の x は減少しないかファイルの順序どおり、ラベルは描いた列と集計に一致",
        ),
    ),
    "match": (
        (
            "Drawn values checked against recomputed values",
            "the values the browser reports drawing: file values equal exactly, formula values "
            "stay within the checked numerical bounds",
        ),
        (
            "描画された値を再計算した値と照合",
            "ブラウザが報告した描画値。ファイルの値は完全に一致し、"
            "数式の値は定めた数値誤差の範囲内",
        ),
    ),
}
_ALL_REASONS: tuple[Reason | None, ...] = (*_REASON_CHECK, None)
_ROOT = Path(__file__).resolve().parents[1]


class _Checks(Protocol):
    CHECKS: tuple[str, ...]
    CHECK_OF: dict[Reason, str]
    TEXTS: dict[str, _TextPair]
    SHOW: tuple[str, str]
    HIDE: tuple[str, str]
    UNRUN: tuple[str, str]
    MARKS: dict[_State, tuple[str, tuple[str, str]]]

    def breakdown_html(self, reason: Reason | None, *, japanese: bool) -> str: ...


def _checks() -> _Checks:
    module = import_module("webui.paste_in.checks")
    assert Path(cast(str, module.__file__)).resolve() == _ROOT / "webui/paste_in/checks.py"
    return cast(_Checks, module)


@dataclass
class _Text:
    value: str
    source: str


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    children: list[_Node | _Text] = field(default_factory=list)

    def nodes(self, *, tag: str | None = None, cls: str | None = None) -> list[_Node]:
        result: list[_Node] = []
        for child in self.children:
            if isinstance(child, _Node):
                if (tag is None or child.tag == tag) and (
                    cls is None or cls in (child.attrs.get("class") or "").split()
                ):
                    result.append(child)
                result.extend(child.nodes(tag=tag, cls=cls))
        return result

    def text(self, *, excluding: str | None = None, raw: bool = False) -> str:
        parts: list[str] = []
        for child in self.children:
            if isinstance(child, _Text):
                parts.append(child.source if raw else child.value)
            elif excluding not in (child.attrs.get("class") or "").split():
                parts.append(child.text(excluding=excluding, raw=raw))
        return "".join(parts)


class _Document(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.root = _Node("document")
        self.stack = [self.root]
        self.feed(source)
        self.close()
        assert self.stack == [self.root], "unclosed HTML elements"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        assert len(attrs) == len(dict(attrs)), "duplicate HTML attribute"
        node = _Node(tag, dict(attrs))
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
        self.stack[-1].children.append(_Text(data, data))

    def handle_entityref(self, name: str) -> None:
        source = f"&{name};"
        self.stack[-1].children.append(_Text(unescape(source), source))

    def handle_charref(self, name: str) -> None:
        source = f"&#{name};"
        self.stack[-1].children.append(_Text(unescape(source), source))


def _one(nodes: list[_Node]) -> _Node:
    assert len(nodes) == 1
    return nodes[0]


def _assert_disclosure_style(document: _Node) -> None:
    css = "\n".join(node.text() for node in document.nodes(tag="style"))
    rules = re.findall(r"([^{}]+)\{([^{}]+)\}", css)
    open_show_hidden = False
    closed_hide_hidden = False
    for selectors, declarations in rules:
        if re.search(r"\bdisplay\s*:\s*none\b", declarations):
            for selector in selectors.split(","):
                compact = re.sub(r"\s+", "", selector)
                open_show_hidden |= "details[open]" in compact and ".show" in compact
                closed_hide_hidden |= ".hide" in compact and (
                    "[open]" not in compact or "details:not([open])" in compact
                )
    assert open_show_hidden, "details[open] must hide .show"
    assert closed_hide_hidden, "closed details must hide .hide"


def _assert_rows(document: _Node, reason: Reason | None, *, japanese: bool) -> None:
    module = _checks()
    language = int(japanese)
    html = _one(document.nodes(tag="html"))
    assert html.attrs.get("lang") == ("ja" if japanese else "en")
    details = _one(document.nodes(tag="details"))
    assert "open" not in details.attrs
    summary = _one(details.nodes(tag="summary"))
    summary_nodes = [child for child in summary.children if isinstance(child, _Node)]
    assert [(node.tag, node.attrs.get("class")) for node in summary_nodes] == [
        ("span", "show"),
        ("span", "hide"),
    ]
    assert [node.text() for node in summary_nodes] == [
        _UI["SHOW"][language],
        _UI["HIDE"][language],
    ]
    assert not any(isinstance(child, _Text) and child.value.strip() for child in summary.children)
    _assert_disclosure_style(document)
    ordered = _one(document.nodes(tag="ol"))
    assert _one(details.nodes(tag="ol")) is ordered
    rows = ordered.nodes(tag="li")
    assert len(rows) == 11
    assert len(document.nodes(tag="li")) == 11
    assert all(child.tag == "li" for child in ordered.children if isinstance(child, _Node))
    failure_index = 11 if reason is None else _ORDER.index(_REASON_CHECK[reason])
    for index, (check, row) in enumerate(zip(_ORDER, rows, strict=True)):
        state: _State = (
            "pass" if index < failure_index else "fail" if index == failure_index else "skip"
        )
        assert row.attrs.get("class") == state, (reason, check)
        slots = [
            node.attrs.get("class")
            for node in row.nodes()
            if node.attrs.get("class") in {"mark", "title", "covers", "cause"}
        ]
        assert slots == ["mark", "title", "covers", *(["cause"] if state == "fail" else [])]
        mark = _one(row.nodes(cls="mark"))
        glyph, labels = _MARKS[state]
        assert mark.tag == "span"
        assert mark.attrs.get("role") == "img"
        assert mark.attrs.get("aria-label") == labels[language]
        assert mark.text() == glyph
        title = _one(row.nodes(cls="title"))
        expected_title, expected_covers = module.TEXTS[check][language]
        assert title.text(excluding="unrun").strip() == expected_title
        assert _one(row.nodes(cls="covers")).text() == expected_covers
        unrun = row.nodes(cls="unrun")
        if state == "skip":
            skipped = _one(unrun)
            assert skipped.tag == "span"
            assert _one(title.nodes(cls="unrun")) is skipped
            assert skipped.text() == _UI["UNRUN"][language]
        else:
            assert unrun == []
        causes = row.nodes(cls="cause")
        if state == "fail":
            assert reason is not None
            assert _one(causes).text() == reasons.REASONS[reason][language]
        else:
            assert causes == []
    assert len(document.nodes(cls="cause")) == (0 if reason is None else 1)
    assert len(document.nodes(cls="unrun")) == max(0, 10 - failure_index)


class _Sites(ast.NodeVisitor):
    def __init__(self, codes: set[str]) -> None:
        self.codes = codes
        self.outer: str | None = None
        self.found: list[tuple[str, str | None]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        previous = self.outer
        if previous is None:
            self.outer = node.name
        self.generic_visit(node)
        self.outer = previous

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and node.value in self.codes:
            self.found.append((node.value, self.outer))


def _site_check(module: str, function: str | None) -> str:
    if module == "prescan" or (module, function) in {
        ("verify", "verify_python_source"),
        ("admit", "parse_admitted"),
    }:
        return "readable"
    if module == "admit":
        return "accepted"
    if module == "project":
        return "chart"
    if module == "verify" and function in {"bind_target", "_check_anchoring"}:
        return "binding"
    if module in {"csvread", "aggregate"} or (
        module == "verify"
        and function
        in {"_check_expr_size", "_finish_table", "_formula_table", "_dataset_table", "recompute"}
    ):
        return "recompute"
    assert module == "verify" and function in {
        "_check_line_order",
        "_check_labels",
        "_formula_integrity",
        "_dataset_integrity",
        "check_integrity",
    }, f"unmapped refusal site: {module}.{function}"
    return "integrity"


def test_c1_check_order_and_reason_map_are_the_hand_stated_tables() -> None:
    """C1: the complete map, not a key-set-only expectation."""
    module = _checks()
    refusal_codes = set(get_args(RefusalCode))
    outlet_codes = set(get_args(OutletCause))
    assert len(refusal_codes) == 54
    assert len(outlet_codes) == 14
    assert refusal_codes.isdisjoint(outlet_codes)
    assert module.CHECKS == _ORDER
    assert set(module.CHECK_OF) == refusal_codes | outlet_codes == set(_REASON_CHECK)
    assert set(module.CHECK_OF.values()) <= set(_ORDER)
    assert module.CHECK_OF == _REASON_CHECK


def test_c2_each_refusal_maps_to_its_earliest_raise_site_check() -> None:
    """C2: all AST string sites; class traversal + outermost function attribution."""
    module = _checks()
    codes = set(get_args(RefusalCode))
    sites: dict[str, list[tuple[str, str | None, str]]] = {code: [] for code in codes}
    sources = sorted((_ROOT / "src/verifier/pysrc").glob("*.py"))
    assert len(sources) >= 2
    for source in sources:
        if source.name != "errors.py":
            visitor = _Sites(codes)
            visitor.visit(ast.parse(source.read_text(encoding="utf-8"), filename=str(source)))
            for code, function in visitor.found:
                check = _site_check(source.stem, function)
                sites[code].append((source.stem, function, check))
    for code, locations in sorted(sites.items()):
        assert locations, f"refusal without a site: {code}"
        earliest = min((check for _, _, check in locations), key=_ORDER.index)
        assert module.CHECK_OF[cast(RefusalCode, code)] == earliest, (code, locations)


def _assert_text(
    text: str, *, japanese: bool, word_limit: int | None = None, require_kana: bool = True
) -> None:
    assert text
    assert not any(char in text for char in '<>&"\n')
    assert "Chart." not in text
    assert "x-" not in text
    if japanese and require_kana:
        assert any(
            unicodedata.name(char, "").startswith(
                ("HIRAGANA LETTER", "KATAKANA LETTER", "HALFWIDTH KATAKANA LETTER")
            )
            for char in text
        )
    elif not japanese:
        assert all(" " <= char <= "~" for char in text)
        if word_limit is not None:
            assert len(text.split()) <= word_limit


def test_c3_every_text_obeys_the_text_law_and_anchors_are_byte_exact() -> None:
    """C3: all localized slots; UI/marks + three critical rows anchored independently."""
    module = _checks()
    assert set(module.TEXTS) == set(_ORDER)
    assert {name: getattr(module, name) for name in _UI} == _UI
    assert module.MARKS == _MARKS
    for check, texts in module.TEXTS.items():
        assert isinstance(cast(object, texts), tuple)
        assert len(texts) == 2
        for language, pair in enumerate(texts):
            assert isinstance(cast(object, pair), tuple)
            assert len(pair) == 2
            title, covers = pair
            _assert_text(title, japanese=bool(language), word_limit=10)
            _assert_text(covers, japanese=bool(language), word_limit=25)
        if check in _ANCHORS:
            assert texts == _ANCHORS[check]
    for name, word in (("SHOW", module.SHOW), ("HIDE", module.HIDE), ("UNRUN", module.UNRUN)):
        assert isinstance(cast(object, word), tuple)
        assert len(word) == 2
        for language, text in enumerate(word):
            _assert_text(text, japanese=bool(language), require_kana=name != "UNRUN")
    # Kanji-only status words are exact anchors; kana binds titles/covers and SHOW/HIDE.
    for _, labels in module.MARKS.values():
        for language, label in enumerate(labels):
            _assert_text(label, japanese=bool(language), require_kana=False)


@pytest.mark.parametrize("reason", _ALL_REASONS)
@pytest.mark.parametrize("japanese", [False, True], ids=["en", "ja"])
def test_c4_document_rows_follow_the_failing_check(
    reason: Reason | None, *, japanese: bool
) -> None:
    """C4: the full 67 x 2 domain, including both endpoint failures and PASS."""
    module = _checks()
    source = module.breakdown_html(reason, japanese=japanese)
    assert isinstance(source, str)
    assert source == module.breakdown_html(reason, japanese=japanese)
    _assert_rows(_Document(source).root, reason, japanese=japanese)


@given(st.lists(st.tuples(st.sampled_from(_ALL_REASONS), st.booleans()), min_size=1, max_size=16))
def test_c4_renderer_is_pure_across_interleaved_inputs(
    inputs: list[tuple[Reason | None, bool]],
) -> None:
    """C4 property: interleaved calls preserve outputs and every public text/map table."""
    module = _checks()
    before = (
        module.CHECKS,
        module.CHECK_OF.copy(),
        module.TEXTS.copy(),
        module.SHOW,
        module.HIDE,
        module.UNRUN,
        module.MARKS.copy(),
        reasons.REASONS.copy(),
    )
    outputs = [module.breakdown_html(reason, japanese=japanese) for reason, japanese in inputs]
    for (reason, japanese), expected in reversed(list(zip(inputs, outputs, strict=True))):
        assert module.breakdown_html(reason, japanese=japanese) == expected
    assert before == (
        module.CHECKS,
        module.CHECK_OF,
        module.TEXTS,
        module.SHOW,
        module.HIDE,
        module.UNRUN,
        module.MARKS,
        reasons.REASONS,
    )


@pytest.mark.parametrize("japanese", [False, True], ids=["en", "ja"])
def test_c4_title_covers_and_cause_are_escaped_and_round_trip(
    monkeypatch: pytest.MonkeyPatch, *, japanese: bool
) -> None:
    """C4: independent slot plants include both quotes and all three markup characters."""
    module = _checks()
    title = "title < > & \" ' sentinel"
    covers = "covers < > & \" ' sentinel"
    cause = "cause < > & \" ' sentinel"
    monkeypatch.setitem(module.TEXTS, "readable", ((title, covers), (title, covers)))
    monkeypatch.setitem(reasons.REASONS, "source_too_large", (cause, cause))
    source = module.breakdown_html("source_too_large", japanese=japanese)
    root = _Document(source).root
    _assert_rows(root, "source_too_large", japanese=japanese)
    row = _one([node for node in root.nodes(tag="li") if node.attrs.get("class") == "fail"])
    for cls, expected in (("title", title), ("covers", covers), ("cause", cause)):
        slot = _one(row.nodes(cls=cls))
        assert slot.text() == expected
        raw = slot.text(raw=True)
        assert not any(char in raw for char in "<>\"'")
        assert "&" not in re.sub(r"&(?:[A-Za-z][A-Za-z0-9]*|#\d+|#x[0-9A-Fa-f]+);", "", raw)
        assert unescape(raw) == expected
        assert expected not in source


# Hand-stated (reviewer-2 K7): reading the reporter from another rendered document let an
# appended statement pass in every document at once.
_HEIGHT_REPORTER = (
    'const r=document.getElementById("r");'
    "new ResizeObserver(()=>parent.postMessage("
    '{type:"iframe:height",height:Math.ceil(r.getBoundingClientRect().height)},"*")'
    ").observe(r);"
)


@pytest.mark.parametrize("reason", _ALL_REASONS)
@pytest.mark.parametrize("japanese", [False, True], ids=["en", "ja"])
def test_c5_document_is_self_contained_and_inert(reason: Reason | None, *, japanese: bool) -> None:
    """C5: all 134 documents; the fixed reporter is the only script."""
    module = _checks()
    source = module.breakdown_html(reason, japanese=japanese)
    assert len(source.encode("utf-8")) <= 16384
    assert not re.search(
        r"\b(?:src|href)\s*=|url\s*\(|@import|https?:", source, flags=re.IGNORECASE
    )
    triggers = (
        "x-data",
        "x-init",
        "x-show",
        "x-bind",
        "x-on",
        "x-text",
        "x-html",
        "x-model",
        "x-modelable",
        "x-ref",
        "x-for",
        "x-if",
        "x-effect",
        "x-transition",
        "x-cloak",
        "x-ignore",
        "x-teleport",
        "x-id",
        "new Chart(",
        "Chart.",
    )
    assert not any(trigger in source for trigger in triggers)
    script = _one(_Document(source).root.nodes(tag="script"))
    assert "src" not in script.attrs
    body = script.text()
    assert body == _HEIGHT_REPORTER
    assert re.search(r"new\s+ResizeObserver\s*\(", body)
    assert re.search(r"\.observe\s*\(", body)
    assert re.search(r"parent\.postMessage\s*\(", body)
    assert re.search(r"\btype\s*:\s*[\"']iframe:height[\"']", body)
    assert re.search(r"\bheight\b", body)
    assert re.search(r",\s*[\"']\*[\"']\s*\)", body)
