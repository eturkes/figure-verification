# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M21.1 F1: a name, cell or chart text reaches the reply as one inert markdown code span.

Oracle = markdown-it-py's CommonMark parser with raw HTML on (Open WebUI renders HTML blocks), so
the grade never re-uses this module's own reasoning about fences and pads.
"""

import unicodedata

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from markdown_it import MarkdownIt

from verifier.figure.inert import code, prose, visible

_MARKDOWN = MarkdownIt("commonmark", {"html": True})
# Draws nothing or reorders the text around it: controls, format (bidi) and unassigned characters.
_HIDDEN = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
# Characters that open markdown, HTML or KaTeX syntax, line breaks and invisible characters.
_HOSTILE = st.text(
    alphabet=st.sampled_from(
        "`` \t\n\r*_[]()<>!$\\#&|~:=-\"'a\u0000\u007f\u200b\u202e\u2028\u3000年"
    )
    | st.characters(codec="utf-8"),
    max_size=40,
)


@pytest.mark.parametrize(
    ("text", "span"),
    [
        ("revenue", "`revenue`"),
        ("a`b", "``a`b``"),
        ("a``b`", "``` a``b` ```"),
        ("`x", "`` `x ``"),
        (" a ", "`  a  `"),
        (" a", "` a`"),
        ("   ", "`   `"),
        ("", "` `"),
        ("a\nb", "`a\u240ab`"),
        ("x\r\n<iframe>", "`x\u240d\u240a<iframe>`"),
        ("\u202eevil\u200b", "`\ufffdevil\ufffd`"),
        ("\x7f", "`\u2421`"),
        ("\tq", "`\tq`"),
        ("[a](https://e.example) $x$", "`[a](https://e.example) $x$`"),
    ],
)
def test_code_spans_are_hand_stated(text: str, span: str) -> None:
    assert code(text) == span


@given(text=_HOSTILE)
@settings(max_examples=600, deadline=None)
def test_every_text_parses_as_one_code_span_beside_its_neighbours(text: str) -> None:
    """Two spans in two lines of one paragraph, as the interpretation writes them: each stays one
    code span, and no block, link, image, emphasis or HTML token appears."""
    tokens = _MARKDOWN.parse(f"Line {code(text)}: a.\nText {code(text)}, {code(text)}.")
    assert [token.type for token in tokens] == ["paragraph_open", "inline", "paragraph_close"]
    children = tokens[1].children or []
    spans = [child.content for child in children if child.type == "code_inline"]
    assert len(spans) == 3 and len(set(spans)) == 1
    assert [child.type for child in children] == [
        "text",
        "code_inline",
        "text",
        "softbreak",
        "text",
        "code_inline",
        "text",
        "code_inline",
        "text",
    ]
    assert [child.content for child in children if child.type == "text"] == [
        "Line ",
        ": a.",
        "Text ",
        ", ",
        ".",
    ]


@given(text=_HOSTILE)
@settings(max_examples=300, deadline=None)
def test_the_span_shows_the_text_verbatim_with_hidden_characters_as_symbols(text: str) -> None:
    """One shown character per character: itself, or a visible symbol for a character that draws
    nothing or reorders the text around it (a line break among them)."""
    children = _MARKDOWN.parse(f"x {code(text)} y")[1].children or []
    content = next(child.content for child in children if child.type == "code_inline")
    if not text:
        assert content == " "
        return
    assert len(content) == len(text)
    for shown, original in zip(content, text, strict=True):
        if original == "\t" or unicodedata.category(original) not in _HIDDEN:
            assert shown == original
        else:
            assert shown != original and unicodedata.category(shown) not in _HIDDEN


# Q79 (`.agent/archive/contracts/q79.md`): every ASCII punctuation character marked can escape,
# except the two whose escape opens Open WebUI's KaTeX math (`\(`, `\[`).
_ESCAPED = frozenset("!\"#$%&'*+,-./:;<=>?@\\]^_`{|}~)")


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("plt.ylim(30000, 45000)", "plt\\.ylim(30000\\, 45000\\)"),
        ("[a](https://e.example)", "[a\\](https\\:\\/\\/e\\.example\\)"),
        ("\\(x\\)", "\\\\\u2060(x\\\\\u2060\\)"),
        ("\\[w\\] \\begin", "\\\\\u2060[w\\\\\u2060\\] \\\\\u2060begin"),
        ("$x$ {{user}}", "\\$x\\$ \\{\\{user\\}\\}"),
        ("<img src=x>", "\\<img src\\=x\\>"),
        ("a\nb\u202e", "a\u240ab\ufffd"),
        ("ご指定の y 軸を 0 から", "ご指定の y 軸を 0 から"),
        ("", ""),
    ],
)
def test_q79_prose_is_hand_stated(text: str, shown: str) -> None:
    assert prose(text) == shown


@given(text=_HOSTILE)
@settings(max_examples=600, deadline=None)
def test_q79_every_backslash_opens_an_escape_and_no_math_opener_forms(text: str) -> None:
    """Read back pair by pair: each backslash escapes one escapable character, every escapable
    character is escaped, and the pairs decode to the visible text; so no `(` or `[` follows an
    unpaired backslash, and no `$`, `{`, `<`, `:`, `@` or `.` stays bare."""
    shown = prose(text)
    decoded, index = [], 0
    while index < len(shown):
        if shown[index] == "\\":
            assert shown[index + 1] in _ESCAPED | {"\\"}
            decoded.append(shown[index + 1])
            index += 2
            # Open WebUI's KaTeX start() scans raw source, escape pairs included: an escaped
            # backslash keeps a word joiner after it, so no `\[`, `\(`, `\b`, `\c`, `\p` forms.
            if decoded[-1] == "\\":
                assert shown[index] == "\u2060"
                index += 1
        else:
            assert shown[index] not in _ESCAPED
            decoded.append(shown[index])
            index += 1
    assert "".join(decoded) == "".join(map(visible, text))
    assert "$$" not in shown


@given(text=_HOSTILE)
@settings(max_examples=600, deadline=None)
def test_q79_the_note_parses_as_plain_text_after_the_bold_label(text: str) -> None:
    """CommonMark with raw HTML on: one paragraph, the label the one emphasis, then text alone,
    reading exactly the visible characters of the note, stripped as the filter strips it."""
    text = text.strip()
    if not text:
        return
    tokens = _MARKDOWN.parse(f"**Model note:** {prose(text)}")
    assert [token.type for token in tokens] == ["paragraph_open", "inline", "paragraph_close"]
    # markdown-it opens the inline run with an empty text token before the emphasis.
    children = [c for c in tokens[1].children or [] if c.type != "text" or c.content]
    assert [child.type for child in children[:3]] == ["strong_open", "text", "strong_close"]
    assert children[1].content == "Model note:"
    assert {child.type for child in children[3:]} <= {"text"}
    shown = "".join(child.content for child in children[3:]).replace("\u2060", "")
    assert shown == " " + "".join(map(visible, text))
