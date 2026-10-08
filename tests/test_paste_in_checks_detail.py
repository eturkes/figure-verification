# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M18.2 E1-E5/E9b: contract-derived row disclosures and bounded source listings.

Contract: `.agent/archive/contracts/m18u2.md`; implementation unread.
"""

from __future__ import annotations

import re
import time
from dataclasses import FrozenInstanceError, fields, is_dataclass
from html import unescape
from typing import cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from test_paste_in_checks import (
    _ALL_REASONS,
    _ANCHORINGS,
    _HEIGHT_REPORTER,
    _assert_rows,
    _assert_text,
    _Document,
    _Node,
    _one,
)
from test_paste_in_checks_detail_support import (
    EXPLAIN,
    ORDER,
    PASS_LINES,
    PROGRAM,
    ROLES,
    TRACE,
    TRIGGERS,
    UI,
    URLS,
    EvidenceView,
    api,
    direct,
    evidence,
    listing,
    numbers,
    rows,
)
from verifier.pysrc.spec import Anchoring
from webui.paste_in.reasons import REASONS, Reason


def test_e1_new_texts_obey_the_text_law_and_anchors_are_byte_exact() -> None:
    """E1: every new UI word + explanation pinned, not only its vocabulary."""
    module = api()
    assert module.EXPLAIN == EXPLAIN
    assert set(module.EXPLAIN) == set(ORDER)
    assert module.CODE_ROLES == ROLES
    assert {name: getattr(module, name) for name in UI} == UI
    assert module.SPECIFICATION == URLS
    for pair in (*module.EXPLAIN.values(), *(getattr(module, name) for name in UI)):
        assert isinstance(pair, tuple) and len(pair) == 2
        for language, text in enumerate(pair):
            _assert_text(text, japanese=bool(language))
            if language == 0:
                assert all(len(sentence.split()) <= 25 for sentence in text[:-1].split(". "))


def test_e1_evidence_is_frozen_slots_with_the_declared_defaults() -> None:
    raw: object = api().Evidence()
    assert is_dataclass(raw)
    assert tuple(field.name for field in fields(raw)) == ("program", "at", "trace")
    value = cast(EvidenceView, raw)
    assert (value.program, value.at, value.trace) == (None, (), ())
    assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        value.program = "changed"


def _sections(row: _Node) -> list[_Node]:
    disclosure = _one(row.nodes(tag="details"))
    assert disclosure.attrs == {"class": "row"}
    summary, more = direct(disclosure)
    assert summary.tag == "summary"
    assert more.tag == "div" and more.attrs == {"class": "more"}
    assert direct(row) == [disclosure]
    mark, body = direct(summary)
    assert mark.tag == "span" and mark.attrs.get("class") == "mark"
    assert body.tag == "div"
    return direct(more)


@pytest.mark.parametrize("with_evidence", [False, True], ids=["empty", "full"])
@pytest.mark.parametrize("anchoring", _ANCHORINGS)
@pytest.mark.parametrize("reason", _ALL_REASONS)
@pytest.mark.parametrize("japanese", [False, True], ids=["en", "ja"])
def test_e2_every_row_is_its_own_collapsed_disclosure(  # noqa: PLR0915 - document conjuncts
    reason: Reason | None,
    anchoring: Anchoring,
    *,
    japanese: bool,
    with_evidence: bool,
) -> None:
    """E2: all 560 documents; sections, state, slots and localization in order."""
    item = evidence(PROGRAM, ((5, 0, 5, 6),), TRACE) if with_evidence else api().Evidence()
    source = api().breakdown_html(reason, japanese=japanese, anchoring=anchoring, evidence=item)
    root = _Document(source).root
    _assert_rows(root, reason, japanese=japanese, anchoring=anchoring)
    assert len(root.nodes(tag="details")) == 12
    language = int(japanese)
    for check, row in rows(source).items():
        state = row.attrs["class"]
        selected = with_evidence and state != "skip" and ROLES[check] is not None
        sections = _sections(row)
        expected = ["what"]
        if state == "skip":
            expected.append("unrun-note")
        if selected:
            expected.append("code")
        if state == "fail":
            expected.append("why")
        expected.append("link")
        assert [section.attrs.get("class") for section in sections] == expected
        for section in sections:
            cls = section.attrs["class"]
            if cls in {"what", "code", "why"}:
                label = direct(section)[0]
                assert label.tag == "span" and label.attrs == {"class": "label"}
                assert label.text() == UI[cls.upper()][language]
        what = _one(row.nodes(cls="what"))
        assert [(node.tag, node.attrs) for node in direct(what)] == [
            ("span", {"class": "label"}),
            ("p", {}),
        ]
        assert _one(what.nodes(tag="p")).text() == EXPLAIN[check][language]
        if state == "skip":
            note = _one(row.nodes(cls="unrun-note"))
            assert [(node.tag, node.attrs) for node in direct(note)] == [("p", {})]
            assert note.text() == UI["NOT_RUN"][language]
        if selected:
            code = _one(row.nodes(cls="code"))
            assert [(node.tag, node.attrs) for node in direct(code)] == [
                ("span", {"class": "label"}),
                ("pre", {"class": "listing"}),
            ]
        if state == "fail":
            assert reason is not None
            why = _one(row.nodes(cls="why"))
            paragraphs = why.nodes(tag="p")
            assert len(paragraphs) == 1 + int(selected)
            assert paragraphs[0].text() == REASONS[reason][language] + f" ({reason})"
            stopped = row.nodes(cls="stopped")
            assert bool(stopped) is selected
            if stopped:
                assert _one(stopped).text() == UI["STOPPED"][language]
        else:
            assert not row.nodes(tag="mark")
            assert all(not item[1] for item in listing(row))
        link = _one(row.nodes(cls="link"))
        assert link.tag == "p" and len(direct(link)) == 1
        anchor = direct(link)[0]
        assert anchor.tag == "a"
        assert anchor.attrs == {
            "class": "spec",
            "href": URLS[language] + "#check-" + check,
            "target": "_blank",
            "rel": "noopener noreferrer",
        }
        assert anchor.text() == UI["SPEC"][language]


def test_e2_outer_toggle_css_cannot_select_row_summaries() -> None:
    source = api().breakdown_html(None, japanese=False, anchoring="strict")
    root = _Document(source).root
    css = _one(root.nodes(tag="style")).text()
    rules = re.findall(r"([^{}]+)\{([^{}]+)\}", css)
    toggle_selectors = [
        re.sub(r"\s+", "", selector)
        for selectors, _body in rules
        for selector in selectors.split(",")
        if ".show" in selector or ".hide" in selector
    ]
    assert toggle_selectors
    assert all(
        re.match(r"#r>details(?:\[open\]|:not\(\[open\]\))?>summary", selector)
        for selector in toggle_selectors
    )
    assert re.search(r"overflow-wrap\s*:\s*(?:anywhere|break-word)", css)
    assert re.search(r"white-space\s*:\s*pre-wrap", css)
    for cls in ("line", "gap"):
        assert any(
            f".{cls}" in selectors and re.search(r"display\s*:\s*block", body)
            for selectors, body in rules
        )


@pytest.mark.parametrize("japanese", [False, True], ids=["en", "ja"])
def test_e3_pass_aggregate_selects_the_hand_stated_lines_per_row(*, japanese: bool) -> None:
    source = api().breakdown_html(
        None,
        japanese=japanese,
        anchoring="strict",
        evidence=evidence(PROGRAM, ((5, 0, 5, 6),), TRACE),
    )
    for check, row in rows(source).items():
        assert numbers(row) == PASS_LINES[check]
        assert all(not at and marks == () for _number, at, _text, marks in listing(row))


@pytest.mark.parametrize("japanese", [False, True], ids=["en", "ja"])
def test_e4_each_row_links_its_reference_section(*, japanese: bool) -> None:
    source = api().breakdown_html(None, japanese=japanese, anchoring="strict")
    assert len(_Document(source).root.nodes(tag="a")) == 11
    for check, row in rows(source).items():
        link = _one(row.nodes(tag="a"))
        assert link.attrs == {
            "class": "spec",
            "href": URLS[int(japanese)] + "#check-" + check,
            "target": "_blank",
            "rel": "noopener noreferrer",
        }
        assert link.text() == UI["SPEC"][int(japanese)]


@pytest.mark.parametrize("japanese", [False, True], ids=["en", "ja"])
def test_e4_url_round_trips_escaped_and_trigger_free(
    monkeypatch: pytest.MonkeyPatch,
    *,
    japanese: bool,
) -> None:
    planted = 'https://example.invalid/x-data/Chart."<&(sentinel)?x=@value'
    monkeypatch.setattr(api(), "SPECIFICATION", (planted, planted))
    source = api().breakdown_html(None, japanese=japanese, anchoring="strict")
    for check, row in rows(source).items():
        assert _one(row.nodes(tag="a")).attrs["href"] == planted + "#check-" + check
    assert planted not in source
    assert not any(trigger in source for trigger in TRIGGERS)
    assert all(
        reference in source for reference in ("&#45;", "&#46;", "&#40;", "&#58;", "&#61;", "&#64;")
    )
    assert "&quot;" in source and "&lt;" in source and "&amp;" in source


def _inert(source: str) -> None:
    root = _Document(source).root
    assert len(source.encode("utf-8")) <= 262144
    assert _one(root.nodes(tag="script")).text() == _HEIGHT_REPORTER
    assert not re.search(r"\bsrc\s*=|url\s*\(|@import|https?:", source, re.IGNORECASE)
    assert not any(trigger in source for trigger in TRIGGERS)
    for node in root.nodes():
        if "href" in node.attrs:
            assert node.tag == "a" and node.attrs["class"] == "spec"


@pytest.mark.parametrize("anchoring", _ANCHORINGS)
@pytest.mark.parametrize("reason", _ALL_REASONS)
@pytest.mark.parametrize("japanese", [False, True], ids=["en", "ja"])
def test_e5_documents_stay_self_contained_and_trigger_free(
    reason: Reason | None,
    anchoring: Anchoring,
    *,
    japanese: bool,
) -> None:
    for program in (None, PROGRAM, " ".join(TRIGGERS)):
        item = evidence(program, ((1, 0, 1, 1),), TRACE)
        _inert(api().breakdown_html(reason, japanese=japanese, anchoring=anchoring, evidence=item))


@pytest.mark.parametrize(
    "program",
    ['"' * 65537, "." * 65537, ("q" * 401 + "\n") * 200],
    ids=["quotes", "dots", "long-lines"],
)
@pytest.mark.parametrize("reason", _ALL_REASONS)
@pytest.mark.parametrize("japanese", [False, True], ids=["en", "ja"])
def test_e5_worst_case_document_size(
    reason: Reason | None, program: str, *, japanese: bool
) -> None:
    trace = tuple(
        (role, (1, 0, 200, 0))
        for role in (
            "import",
            "source",
            "data",
            "mark",
            "title",
            "xlabel",
            "ylabel",
            "decoration",
            "layout",
            "show",
        )
    )
    _inert(
        api().breakdown_html(
            reason,
            japanese=japanese,
            anchoring="strict",
            evidence=evidence(program, ((1, 0, 1, 1),), trace),
        )
    )


@given(
    st.lists(
        st.tuples(st.sampled_from(_ALL_REASONS), st.booleans(), st.text(max_size=100)),
        min_size=1,
        max_size=8,
    )
)
@settings(deadline=None)
def test_e5_evidence_renderer_is_pure(inputs: list[tuple[Reason | None, bool, str]]) -> None:
    module = api()
    before = (module.EXPLAIN.copy(), module.CODE_ROLES.copy(), module.SPECIFICATION)
    items = [(reason, ja, evidence(program)) for reason, ja, program in inputs]
    outputs = [
        module.breakdown_html(reason, japanese=ja, anchoring="strict", evidence=item)
        for reason, ja, item in items
    ]
    for (reason, ja, item), expected in reversed(list(zip(items, outputs, strict=True))):
        assert (
            module.breakdown_html(reason, japanese=ja, anchoring="strict", evidence=item)
            == expected
        )
    assert before == (module.EXPLAIN, module.CODE_ROLES, module.SPECIFICATION)


@pytest.mark.parametrize(
    "program", ["z" * 5_000_000, ("z" * 24 + "\n") * 200_000], ids=["one-line", "200000-lines"]
)
@pytest.mark.parametrize("japanese", [False, True], ids=["en", "ja"])
def test_e9b_rendering_work_is_bounded(program: str, *, japanese: bool) -> None:
    trace = (("mark", (1, 0, 200000, 0)),)
    item = evidence(program, ((1, 0, 1, 1),), trace)
    started = time.perf_counter()
    source = api().breakdown_html(
        "observation_mismatch", japanese=japanese, anchoring="strict", evidence=item
    )
    elapsed = time.perf_counter() - started
    assert elapsed < 0.5, elapsed
    _inert(source)
    cut = api().breakdown_html(
        "observation_mismatch",
        japanese=japanese,
        anchoring="strict",
        evidence=evidence(program[:65536], ((1, 0, 1, 1),), trace),
    )
    note = '<p class="beyond">' + UI["BEYOND"][int(japanese)] + "</p>"
    assert note in source
    assert note not in cut
    assert source.replace(note, "") == cut


@pytest.mark.parametrize("length,beyond", [(65535, False), (65536, False), (65537, True)])
def test_e9b_scan_boundary_is_exact(length: int, *, beyond: bool) -> None:
    source = api().breakdown_html(
        None, japanese=False, anchoring="strict", evidence=evidence("z" * length)
    )
    for check, row in rows(source).items():
        assert bool(row.nodes(cls="beyond")) is (beyond and ROLES[check] == "all")
        assert all(len(text) == 401 for _n, _at, text, _marks in listing(row))
    assert unescape(source).count(UI["BEYOND"][0]) == (5 if beyond else 0)


def test_e5_program_url_and_src_assignment_obey_the_global_source_bans() -> None:
    """E3/E5 ruling: colon/equal/at-sign escaping keeps program URLs and assignments inert."""
    program = 'url = "https://example.test"\nsrc = 1\n# @import url(http://example.test)'
    source = api().breakdown_html(
        "literal_not_admitted", japanese=False, anchoring="strict", evidence=evidence(program)
    )
    _inert(source)
    assert listing(rows(source)["accepted"])[0][2] == 'url = "https://example.test"'
    assert listing(rows(source)["accepted"])[1][2] == "src = 1"
    assert listing(rows(source)["accepted"])[2][2] == "# @import url(http://example.test)"
