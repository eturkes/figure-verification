# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M19.5 O8/O9: literal stage map + independent listing oracle, implementation unread."""

from __future__ import annotations

import re
import unicodedata
from typing import cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from outlet_support import (
    ORDER,
    REASON_CHECK,
    SPECIFICATION,
    Document,
    Node,
    assert_states,
    listing,
    load,
    one,
    rows,
    texts,
)

# Older detail helpers import these parser names; their old check ids remain their own fixture.
_Document = Document
_Node = Node
_one = one


def _render(
    reason: str | None = None,
    *,
    program: str | None = None,
    site: int | None = None,
    japanese: bool = False,
    anchoring: str = "strict",
) -> str:
    api = load("checks")
    return cast(
        str,
        api.breakdown_html(
            reason,
            japanese=japanese,
            anchoring=anchoring,
            evidence=api.Evidence(program=program, site=site),
        ),
    )


def test_o8_check_order_reason_map_and_text_tables_are_total() -> None:
    api = load("checks")
    assert tuple(api.CHECKS) == ORDER
    assert api.CHECK_OF == REASON_CHECK
    assert set(api.TEXTS) == set(ORDER)
    assert set(api.EXPLAIN) == set(ORDER)
    for check in ORDER:
        assert len(api.TEXTS[check]) == 2
        assert all(len(pair) == 2 and all(pair) for pair in api.TEXTS[check])
        assert len(api.EXPLAIN[check]) == 2 and all(api.EXPLAIN[check])
    assert api.TEXTS["columns"] != api.STRICT_COLUMNS


@pytest.mark.parametrize("reason", [None, *REASON_CHECK])
@pytest.mark.parametrize("japanese", [False, True], ids=["en", "ja"])
def test_o9_all_reasons_have_exact_completed_prefix_and_one_cause(
    reason: str | None, *, japanese: bool
) -> None:
    html = _render(reason, japanese=japanese)
    root = Document(html).root
    assert one(root.nodes(tag="html")).attrs["lang"] == ("ja" if japanese else "en")
    assert len(root.nodes(tag="details")) == 10
    outer = [d for d in root.nodes(tag="details") if d.attrs.get("class") != "row"]
    assert "open" not in one(outer).attrs
    assert one(root.nodes(cls="show")).text() == (
        "チェック項目を表示" if japanese else "Show checks"
    )
    assert_states(html, reason)
    for check, row in rows(html).items():
        disclosure = one(row.nodes(tag="details"))
        assert disclosure.attrs == {"class": "row"}
        assert len(disclosure.nodes(tag="summary")) == 1
        assert one(row.nodes(cls="title")).text().strip()
        assert one(row.nodes(cls="covers")).text().strip()
        links = row.nodes(tag="a")
        assert len(links) == 1
        assert links[0].attrs["href"] == SPECIFICATION[int(japanese)] + "#check-" + check
        assert links[0].attrs["target"] == "_blank"
        assert links[0].text().strip()
        causes = row.nodes(cls="cause")
        if reason is not None and check == REASON_CHECK[reason]:
            assert one(causes).text() == texts()[reason][int(japanese)]
        else:
            assert not causes
        if row.attrs["class"] == "skip":
            assert one(row.nodes(cls="unrun")).text() == ("未実施" if japanese else "not checked")
        else:
            assert not row.nodes(cls="unrun")
    assert not root.nodes(cls="code")


@pytest.mark.parametrize("japanese", [False, True])
def test_o9_columns_cover_the_actual_artifact_policy(*, japanese: bool) -> None:
    strict = rows(_render(japanese=japanese, anchoring="strict"))
    demo = rows(_render(japanese=japanese, anchoring="substitution"))
    for check in ORDER:
        a = one(strict[check].nodes(cls="covers")).text()
        b = one(demo[check].nodes(cls="covers")).text()
        assert (a != b) == (check == "columns")


@pytest.mark.parametrize("reason", [None, *REASON_CHECK])
def test_o9_only_passed_program_and_failing_row_list_source(reason: str | None) -> None:
    program = "first = 1\nsecond = 2\nthird = 3"
    observed = rows(_render(reason, program=program, site=2))
    failed = None if reason is None else REASON_CHECK[reason]
    for check, row in observed.items():
        shown = listing(row)
        if check in ("program", failed):
            assert tuple((line, text) for line, _at, text, _marks in shown) == (
                (1, "first = 1"),
                (2, "second = 2"),
                (3, "third = 3"),
            )
            assert tuple(line for line, at, _text, _marks in shown if at) == (
                (2,) if check == failed else ()
            )
            assert tuple(mark for _line, _at, _text, marks in shown for mark in marks) == (
                ("second = 2",) if check == failed else ()
            )
        else:
            assert shown == ()


@pytest.mark.parametrize("site", [None, -1, 0, 4, 100000])
def test_o9_absent_or_out_of_program_site_keeps_listing_unmarked(site: int | None) -> None:
    document = rows(_render("axis_inverted", program="one\ntwo\nthree", site=site))
    assert listing(document["axes"]) == (
        (1, False, "one", ()),
        (2, False, "two", ()),
        (3, False, "three", ()),
    )
    assert not document["program"].nodes(tag="mark")


def _visible(char: str) -> str:
    if char != "\t" and unicodedata.category(char) in {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}:
        return chr(0x2400 + ord(char)) if ord(char) < 32 else "␡" if ord(char) == 127 else "�"
    return char


def _reference(
    program: str, site: int | None
) -> tuple[tuple[int, bool, str, tuple[str, ...]], ...]:
    lines = re.split(r"\r\n|\r|\n", program[:65536])
    point = site if site is not None and 1 <= site <= len(lines) else None
    near = set() if point is None else set(range(point - 2, point + 3))
    priority = sorted(
        range(1, len(lines) + 1),
        key=lambda n: (0 if n == point else 1 if n in near else 2, n),
    )
    kept: list[int] = []
    cost = 0
    for number in priority:
        extra = min(len(lines[number - 1]), 400)
        if len(kept) < 60 and cost + extra <= 3000:
            kept.append(number)
            cost += extra
    result = []
    for number in sorted(kept):
        raw = lines[number - 1]
        text = "".join(_visible(char) for char in raw[:400])
        marks = (text,) if number == point and text else ()
        result.append((number, number == point, text + ("…" if len(raw) > 400 else ""), marks))
    return tuple(result)


@given(
    lines=st.lists(
        st.text(alphabet="ab年é<>\"'&.-(:=@\t\x00\u202e\u2028", min_size=1, max_size=450),
        min_size=1,
        max_size=85,
    ),
    point=st.integers(min_value=-3, max_value=95),
    newline=st.sampled_from(("\n", "\r", "\r\n")),
)
@settings(max_examples=64, deadline=None)
def test_o9_generated_listings_match_independent_budget_and_site_oracle(
    lines: list[str], point: int, newline: str
) -> None:
    program = newline.join(lines)
    document = rows(_render("value_not_found", program=program, site=point))
    assert listing(document["values"]) == _reference(program, point)
    assert listing(document["program"]) == _reference(program, None)


@pytest.mark.parametrize("length", [399, 400, 401, 3000, 65535, 65536, 65537])
def test_o9_scan_and_per_line_boundaries(length: int) -> None:
    program = "z" * length + "\nBEYOND_SCAN"
    result = rows(_render("program_error", program=program, site=2))
    assert listing(result["run"]) == _reference(program, 2)
    assert all("BEYOND_SCAN" not in item[2] for item in listing(result["run"])) == (length >= 65535)


def test_o9_site_and_neighbors_take_priority_inside_caps() -> None:
    program = "\n".join(f"row{n:03d}" for n in range(1, 201))
    actual = listing(rows(_render("axis_inverted", program=program, site=198))["axes"])
    assert tuple(item[0] for item in actual) == (*range(1, 56), 196, 197, 198, 199, 200)
    assert tuple(item for item in actual if item[1]) == ((198, True, "row198", ("row198",)),)
    assert actual == _reference(program, 198)


def test_o9_source_escaping_is_exact_and_confined_to_listing() -> None:
    program = "-.(:=@<>&\"'\t\x00\u202e\x7f"
    document = Document(_render("bar_not_from_zero", program=program, site=1)).root
    expected = "&#45;&#46;&#40;&#58;&#61;&#64;&lt;&gt;&amp;&quot;&#x27;\t␀�␡"
    sources = document.nodes(cls="src")
    assert len(sources) == 2
    assert all(source.text(raw=True) == expected for source in sources)
    assert all(source.text() == "-.(:=@<>&\"'\t␀�␡" for source in sources)
    assert program not in document.text(excluding="code")
    assert not document.nodes(tag="img")


@pytest.mark.parametrize(
    ("program", "site"),
    [
        ("\n".join("x" * 1 for _ in range(61)), 1),  # 61 one-character lines: the line cap binds
        ("\n".join(["y" * 375] * 8 + ["z"]), 1),  # 3,000 characters exactly, then one more
        ("\n".join("w" for _ in range(100)), 101),  # a site past the program keeps number order
        ("\n".join("v" for _ in range(100)), -1),
    ],
    ids=["line-cap", "character-cap", "site-past-end", "site-before-start"],
)
def test_o9_caps_bind_at_their_exact_boundaries(program: str, site: int) -> None:
    """MAIN's boundary witnesses beside the generated oracle: each cap and an out-of-program site
    at the point where one more line or character would change the listing."""
    document = rows(_render("axis_inverted", program=program, site=site))
    assert listing(document["axes"]) == _reference(program, site)
