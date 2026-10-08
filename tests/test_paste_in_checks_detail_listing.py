# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M18.2 E3: independent line/mark/cap witnesses + generated listing differential."""

from __future__ import annotations

import re
import unicodedata

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from test_paste_in_checks import _Document, _one
from test_paste_in_checks_detail_support import (
    PROGRAM,
    TRACE,
    SpanTuple,
    TraceTuple,
    api,
    evidence,
    listing,
    numbers,
    rows,
)
from webui.paste_in.reasons import Reason


@pytest.mark.parametrize(
    "reason,program,at,trace,check,expected",
    [
        (
            "source_has_nul",
            "年é\x00z\nnext",
            ((1, 5, 1, 6),),
            (),
            "readable",
            ((1, True, "年é␀z", ("␀",)), (2, False, "next", ())),
        ),
        (
            "name_not_bound",
            "one\ntwo\nthree\nfour\ncall(年bad)\nsix\nseven\neight",
            ((5, 5, 5, 11),),
            (),
            "accepted",
            (
                (1, False, "one", ()),
                (2, False, "two", ()),
                (3, False, "three", ()),
                (4, False, "four", ()),
                (5, True, "call(年bad)", ("年bad",)),
                (6, False, "six", ()),
                (7, False, "seven", ()),
                (8, False, "eight", ()),
            ),
        ),
        (
            "y_not_over_grid",
            "x = 0\ny = other\nplt.plot(x, y)\nplt.show()",
            ((2, 4, 2, 9), (3, 0, 3, 14)),
            (),
            "chart",
            (
                (1, False, "x = 0", ()),
                (2, True, "y = other", ("other",)),
                (3, True, "plt.plot(x, y)", ("plt.plot(x, y)",)),
                (4, False, "plt.show()", ()),
            ),
        ),
        (
            "source_not_supplied",
            PROGRAM,
            ((3, 0, 3, 42),),
            TRACE,
            "binding",
            (
                (
                    3,
                    True,
                    "df = pd.read_csv('/mnt/uploads/chart.csv')",
                    ("df = pd.read_csv('/mnt/uploads/chart.csv')",),
                ),
                (4, False, "totals = df.groupby('region')['revenue'].sum()", ()),
                (5, False, "totals.plot(kind='bar')", ()),
            ),
        ),
        (
            "column_not_numeric",
            PROGRAM,
            (),
            TRACE,
            "recompute",
            (
                (3, False, "df = pd.read_csv('/mnt/uploads/chart.csv')", ()),
                (4, False, "totals = df.groupby('region')['revenue'].sum()", ()),
                (5, False, "totals.plot(kind='bar')", ()),
            ),
        ),
        (
            "column_not_named",
            PROGRAM,
            (),
            TRACE,
            "binding",
            (
                (3, False, "df = pd.read_csv('/mnt/uploads/chart.csv')", ()),
                (4, False, "totals = df.groupby('region')['revenue'].sum()", ()),
                (5, False, "totals.plot(kind='bar')", ()),
            ),
        ),
        (
            "label_not_consistent",
            PROGRAM,
            ((6, 0, 6, 19),),
            TRACE,
            "integrity",
            (
                (4, False, "totals = df.groupby('region')['revenue'].sum()", ()),
                (5, False, "totals.plot(kind='bar')", ()),
                (6, True, "plt.title('Totals')", ("plt.title('Totals')",)),
                (7, False, "plt.xlabel('Region')", ()),
                (8, False, "plt.ylabel('Revenue')", ()),
            ),
        ),
        (
            "source_not_parsable",
            "年éa\r\nsecond\rthird\nfourth",
            ((1, 3, 1, 5),),
            (),
            "readable",
            (
                (1, True, "年éa", ("é",)),
                (2, False, "second", ()),
                (3, False, "third", ()),
                (4, False, "fourth", ()),
            ),
        ),
        (
            "source_not_utf8",
            "\x00\x1f\x7f\x85\u202e\u2028\u2029\ud800\ue000\u0378\tZ",
            ((1, 14, 1, 17),),
            (),
            "readable",
            ((1, True, "␀␟␡�������\tZ", ("�",)),),
        ),
        (
            "source_not_parsable",
            "abc\nDEF\nghi",
            ((1, 1, 3, 2),),
            (),
            "readable",
            ((1, True, "abc", ("bc",)), (2, True, "DEF", ("DEF",)), (3, True, "ghi", ("gh",))),
        ),
        ("source_not_parsable", "abc", ((1, 3, 1, 3),), (), "readable", ((1, True, "abc", ()),)),
        (
            "source_not_parsable",
            "abcdef",
            ((1, 0, 1, 2), (1, 1, 1, 4), (1, 4, 1, 5)),
            (),
            "readable",
            ((1, True, "abcdef", ("abcde",)),),
        ),
    ],
    ids=[
        "nul-byte-column",
        "inner-line5",
        "substituted-binding",
        "bound-source",
        "data-fault-unmarked",
        "request-fault-unmarked",
        "title-role",
        "newline-kinds",
        "invisible-categories",
        "multiline-mark",
        "point",
        "merged-mark-runs",
    ],
)
def test_e3_listings_are_the_hand_stated_lines_and_marks(  # noqa: PLR0913, PLR0917 - witness columns
    reason: Reason,
    program: str,
    at: tuple[SpanTuple, ...],
    trace: TraceTuple,
    check: str,
    expected: tuple[tuple[int, bool, str, tuple[str, ...]], ...],
) -> None:
    wanted = {item[0] for item in expected}
    assert tuple(item for item in _reference(program, at) if item[0] in wanted) == expected
    source = api().breakdown_html(
        reason, japanese=False, anchoring="strict", evidence=evidence(program, at, trace)
    )
    by_check = rows(source)
    row = by_check[check]
    assert listing(row) == expected
    stopped = row.nodes(cls="stopped")
    assert bool(stopped) is any(item[1] for item in expected)
    if stopped:
        assert _one(stopped).text() == "The check stopped at the marked code."
    for other in by_check.values():
        if other.attrs["class"] != "fail":
            assert not other.nodes(tag="mark")
            assert not any(item[1] for item in listing(other))


@pytest.mark.parametrize("japanese", [False, True], ids=["en", "ja"])
def test_e3_at_lines_and_their_neighbors_win_the_sixty_line_cap(*, japanese: bool) -> None:
    program = "\n".join(f"row{n:03d}" for n in range(1, 201))
    source = api().breakdown_html(
        "source_not_parsable",
        japanese=japanese,
        anchoring="strict",
        evidence=evidence(program, ((198, 0, 198, 6),)),
    )
    row = rows(source)["readable"]
    assert numbers(row) == (*range(1, 56), 196, 197, 198, 199, 200)
    assert tuple(item for item in listing(row) if item[1]) == ((198, True, "row198", ("row198",)),)
    assert [gap.text() for gap in row.nodes(cls="gap")] == ["⋮"]
    assert (
        _one(row.nodes(cls="elided")).text()
        == (
            "Lines not shown: 140.",
            "表示していない行: 140 行。",
        )[int(japanese)]
    )
    pre = _one(row.nodes(tag="pre"))
    assert all(not isinstance(child, str) for child in pre.children)
    assert "\n" not in pre.text()


@pytest.mark.parametrize("width", [400, 1000])
def test_e3_character_budget_skips_an_unfitting_line_then_takes_a_later_short_one(
    width: int,
) -> None:
    program = "\n".join(["a" * width] * 8 + ["b" * 200, "c"])
    source = api().breakdown_html(
        "source_not_parsable", japanese=False, anchoring="strict", evidence=evidence(program)
    )
    row = rows(source)["readable"]
    assert numbers(row) == (1, 2, 3, 4, 5, 6, 7, 9)
    assert [gap.text() for gap in row.nodes(cls="gap")] == ["⋮"]
    assert _one(row.nodes(cls="elided")).text() == "Lines not shown: 2."
    assert sum(len(item[2]) for item in listing(row)) == 3000 + (7 if width > 400 else 0)


@pytest.mark.parametrize("length", [399, 400, 401, 1000])
def test_e3_long_line_marks_clip_before_the_ellipsis(length: int) -> None:
    source = api().breakdown_html(
        "source_not_parsable",
        japanese=False,
        anchoring="strict",
        evidence=evidence("a" * length, ((1, 398, 1, length),)),
    )
    expected_mark = "a" * (min(length, 400) - 398)
    expected_text = "a" * min(length, 400) + ("…" if length > 400 else "")
    row = rows(source)["readable"]
    assert listing(row) == ((1, True, expected_text, (expected_mark,)),)
    assert not row.nodes(cls="elided")


def test_e3_at_adds_lines_outside_roles_and_drops_positions_beyond_the_scan() -> None:
    source = api().breakdown_html(
        "source_not_supplied",
        japanese=False,
        anchoring="strict",
        evidence=evidence(
            "a\nb\nc\nd\ne",
            ((2, 0, 2, 1), (99, 0, 99, 1)),
            (("mark", (4, 0, 5, 1)), ("title", (3, 0, 3, 1))),
        ),
    )
    row = rows(source)["binding"]
    assert listing(row) == ((2, True, "b", ("b",)), (4, False, "d", ()), (5, False, "e", ()))
    assert [gap.text() for gap in row.nodes(cls="gap")] == ["⋮"]
    assert not row.nodes(cls="elided")


@pytest.mark.parametrize("program", [None, "", "\n", "\r", "\r\n"])
def test_e3_empty_and_trailing_lines_are_real_scanned_lines(program: str | None) -> None:
    source = api().breakdown_html(
        None, japanese=False, anchoring="strict", evidence=evidence(program)
    )
    expected: tuple[tuple[int, bool, str, tuple[str, ...]], ...] = (
        () if program is None else ((1, False, "", ()),)
    )
    if program:
        expected += ((2, False, "", ()),)
    assert listing(rows(source)["program"]) == expected
    assert listing(rows(source)["binding"]) == ()


def _reference(
    program: str, spans: tuple[SpanTuple, ...]
) -> tuple[tuple[int, bool, str, tuple[str, ...]], ...]:
    """Standalone contract oracle: char-wise byte spans, greedy budgets, no production tables."""
    lines = re.split(r"\r\n|\r|\n", program[:65536])
    marked = {n for first, _col, last, _end in spans for n in range(first, last + 1)}
    near = {n for at in marked for n in range(at - 2, at + 3)}
    priority = sorted(
        range(1, len(lines) + 1), key=lambda n: (0 if n in marked else 1 if n in near else 2, n)
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
        line = lines[number - 1]
        pieces: list[tuple[str, bool]] = []
        byte = 0
        for char in line[:400]:
            covered = any(
                first <= number <= last
                and (number != first or byte >= col)
                and (number != last or byte < end)
                for first, col, last, end in spans
            )
            byte += len(char.encode("utf-8", errors="surrogatepass"))
            rendered = char
            if char != "\t" and unicodedata.category(char) in {
                "Cc",
                "Cf",
                "Cs",
                "Co",
                "Cn",
                "Zl",
                "Zp",
            }:
                rendered = (
                    chr(0x2400 + ord(char)) if ord(char) < 32 else "␡" if ord(char) == 127 else "�"
                )
            pieces.append((rendered, covered))
        marks: list[str] = []
        run = ""
        for char, covered in [*pieces, ("", False)]:
            if covered:
                run += char
            elif run:
                marks.append(run)
                run = ""
        text = "".join(char for char, _covered in pieces) + ("…" if len(line) > 400 else "")
        result.append((number, number in marked, text, tuple(marks)))
    return tuple(result)


@given(
    st.lists(
        st.text(alphabet="ab年é<>\"'&.-(\t\x00\u202e\u2028", max_size=450), min_size=1, max_size=80
    ),
    st.integers(min_value=0, max_value=10000),
    st.sampled_from(("\n", "\r", "\r\n")),
)
@settings(max_examples=60, deadline=None)
def test_e3_generated_listings_match_the_independent_reference(
    lines: list[str],
    point: int,
    newline: str,
) -> None:
    number = point % len(lines) + 1
    text = lines[number - 1]
    split = point % (len(text) + 1)
    start = len(text[:split].encode("utf-8"))
    end = len(text.encode("utf-8"))
    spans = ((number, start, number, end),)
    program = newline.join(lines)
    source = api().breakdown_html(
        "source_not_parsable", japanese=False, anchoring="strict", evidence=evidence(program, spans)
    )
    assert listing(rows(source)["readable"]) == _reference(program, spans)
    assert not any(node.tag == "mark" for node in rows(source)["program"].nodes())
    assert len(_Document(source).root.nodes(tag="script")) == 1


@pytest.mark.parametrize("start", [100, 141])
def test_e3_more_than_sixty_at_lines_are_taken_in_source_order(start: int) -> None:
    source = api().breakdown_html(
        "source_not_parsable",
        japanese=False,
        anchoring="strict",
        evidence=evidence("\n".join(["z"] * 200), ((start, 0, 200, 1),)),
    )
    row = rows(source)["readable"]
    assert numbers(row) == tuple(range(start, start + 60))
    assert all(at and marks == ("z",) for _number, at, _text, marks in listing(row))
    assert not row.nodes(cls="gap")
    assert _one(row.nodes(cls="elided")).text() == "Lines not shown: 140."


def test_e3_source_escaping_is_byte_exact() -> None:
    source = api().breakdown_html(
        None, japanese=False, anchoring="strict", evidence=evidence("-.(:=@<>&\"'\t")
    )
    row = rows(source)["program"]
    raw = _one(row.nodes(cls="src")).text(raw=True)
    assert raw == "&#45;&#46;&#40;&#58;&#61;&#64;&lt;&gt;&amp;&quot;&#x27;\t"


def test_e3_a_mark_beyond_the_visible_prefix_does_not_mark_the_ellipsis() -> None:
    source = api().breakdown_html(
        "source_not_parsable",
        japanese=False,
        anchoring="strict",
        evidence=evidence("z" * 1000, ((1, 500, 1, 700),)),
    )
    row = rows(source)["readable"]
    assert listing(row) == ((1, True, "z" * 400 + "…", ()),)
    assert _one(row.nodes(cls="stopped")).text() == "The check stopped at the marked code."


def test_e3_exclusive_end_at_next_line_start_marks_no_character_on_that_line() -> None:
    source = api().breakdown_html(
        "source_not_parsable",
        japanese=False,
        anchoring="strict",
        evidence=evidence("ab\ncd", ((1, 1, 2, 0),)),
    )
    assert listing(rows(source)["readable"]) == (
        (1, True, "ab", ("b",)),
        (2, True, "cd", ()),
    )
