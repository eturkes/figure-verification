# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M18.1: `SourceMap`'s locators degrade to no place, never to an exception or a wrong line.

The suite's witnesses reach these through real CPython errors; the shapes below are the ones no
3.13 error produces today (no line, no end, a position that is not a pair), so they are planted.
"""

from verifier.pysrc.position import SourceMap, Span
from verifier.pysrc.verify import Refused, verify_python_source


def test_a_syntax_error_without_a_line_points_nowhere() -> None:
    assert SourceMap("x = (\n").syntax_error(SyntaxError("planted")) == ()


def test_a_syntax_error_without_an_end_marks_its_start_character() -> None:
    error = SyntaxError("planted", ("<x>", 1, 5, "年 = )\n"))
    assert (error.end_lineno, error.end_offset) == (None, None)
    assert SourceMap("年 = )\n").syntax_error(error) == (Span(1, 6, 1, 7),)


def test_a_token_error_position_that_is_not_a_pair_points_nowhere() -> None:
    source = SourceMap("x = 'abc\n")
    for position in (None, "message", (1,), (1, 2, 3), ("1", 2)):
        assert source.token_error(position) == ()
    assert source.token_error((1, 5)) == (Span(1, 4, 1, 5),)


def test_a_token_row_past_the_text_clamps_to_the_last_row() -> None:
    assert SourceMap("a\nb").token_error((9, 1)) == (Span(2, 0, 2, 1),)


def test_a_token_row_after_a_bare_cr_maps_to_its_span_line() -> None:
    """Tokenizer row 2 starts after the `\\n`, but a bare `\\r` already began Span line 2."""
    refused = verify_python_source("x = 1\ry = 2\nz = 'a")
    assert isinstance(refused, Refused)
    assert refused.code == "source_not_tokenizable"
    assert refused.at == (Span(3, 4, 3, 5),)


def test_a_crlf_break_belongs_to_the_line_it_closes() -> None:
    """An offset on the `\\n` of `\\r\\n` is the end of line 1, never past its `\\r`."""
    assert SourceMap("ab\r\ncd").char(3) == Span(1, 2, 1, 2)
    refused = verify_python_source("x = 1 \\\r\n")
    assert isinstance(refused, Refused)
    assert refused.at == (Span(1, 7, 1, 7),)
