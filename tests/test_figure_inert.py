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

from verifier.figure.inert import code

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
