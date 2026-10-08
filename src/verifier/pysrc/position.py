# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Where in the submitted program a verdict points: integer spans and statement roles, no bytes.

A position is diagnostic and never part of a verdict's identity. The wrapper that shows a user the
refused code quotes the program it already holds; the core only says where to look, so no model
byte enters a verdict through this module.

`Span` follows `ast`: lines count from 1 at `\\r\\n`, `\\r` or `\\n` (never `str.splitlines`'s wider
set), columns are UTF-8 byte offsets within the line, and the end is exclusive. A span whose end
equals its start is a POINT: a place with no character, such as the end of a line.
"""

import re
from dataclasses import dataclass
from typing import Literal, Protocol, cast

Role = Literal[
    "import", "source", "data", "mark", "title", "xlabel", "ylabel", "decoration", "layout", "show"
]

_NEWLINE = re.compile(r"\r\n|\r|\n")


@dataclass(frozen=True, slots=True)
class Span:
    line: int
    column: int
    end_line: int
    end_column: int


@dataclass(frozen=True, slots=True)
class Step:
    """One top-level statement and the part it plays in the chart."""

    role: Role
    span: Span


type Trace = tuple[Step, ...]


class _Located(Protocol):
    """An `ast` statement or expression, typed structurally: the pre-scan imports this module and
    must not import `ast`."""

    lineno: int
    col_offset: int
    end_lineno: int | None
    end_col_offset: int | None


def node_span(node: _Located) -> Span:
    # Every node `ast.parse` returns carries its end; only hand-built nodes lack one.
    return Span(
        node.lineno, node.col_offset, cast("int", node.end_lineno), cast("int", node.end_col_offset)
    )


def _utf8_length(text: str) -> int:
    # `surrogatepass`: a lone surrogate reaches here only as the character a refusal points at.
    return len(text.encode("utf-8", "surrogatepass"))


class SourceMap:
    """Character offsets in one text -> spans. Every offset is clamped into the text, so a locator
    fed a position past the end still returns a valid span rather than raising."""

    def __init__(self, text: str) -> None:
        self._text = text
        breaks = list(_NEWLINE.finditer(text))
        self._starts = [0, *(match.end() for match in breaks)]
        self._ends = [*(match.start() for match in breaks), len(text)]
        # `tokenize` reads through `readline`, which splits at `\n` alone.
        self._token_starts = [0, *(match.end() for match in re.finditer("\n", text))]

    def _locate(self, offset: int) -> tuple[int, int]:
        """`(line index, offset)`, the offset clamped into the text and off any line break: a
        break belongs to the end of the line it closes."""
        offset = max(0, min(offset, len(self._text)))
        # Linear: a locator runs once or twice per refusal, over a program the byte cap bounds.
        index = sum(1 for start in self._starts if start <= offset) - 1
        return index, min(offset, self._ends[index])

    def _position(self, offset: int) -> tuple[int, int]:
        index, offset = self._locate(offset)
        return index + 1, _utf8_length(self._text[self._starts[index] : offset])

    def span(self, start: int, end: int) -> Span:
        line, column = self._position(start)
        end_line, end_column = self._position(max(start, end))
        return Span(line, column, end_line, end_column)

    def char(self, offset: int) -> Span:
        """The one character at `offset`, or a point where there is none (a line break, the end)."""
        index, start = self._locate(offset)
        return self.span(start, start + 1 if start < self._ends[index] else start)

    def offset(self, line: int, column: int) -> int:
        """`line` in the `Span` convention, `column` in characters."""
        index = max(0, min(line - 1, len(self._starts) - 1))
        start = self._starts[index]
        return start + max(0, min(column, self._ends[index] - start))

    def token_offset(self, row: int, column: int) -> int:
        """`tokenize`'s `(row, column)`: rows split at `\\n` alone, columns in characters, clamped
        into the row -- its `unexpected EOF` error counts the row's BYTES instead (measured on
        3.13), and the clamp keeps that past-the-end column on its own row."""
        index = max(0, min(row - 1, len(self._token_starts) - 1))
        start = self._token_starts[index]
        end = self._token_starts[index + 1] - 1 if index + 1 < len(self._token_starts) else None
        return min(start + max(0, column), len(self._text) if end is None else end)

    def syntax_error(self, error: SyntaxError) -> tuple[Span, ...]:
        """Where `ast.parse` stopped: `lineno` + 1-based CHARACTER `offset`, the end used only
        when it lies after the start (CPython reports 0 or -1 for an unknown end)."""
        if error.lineno is None:
            return ()
        start = self.offset(error.lineno, (error.offset or 1) - 1)
        end = start
        if error.end_lineno is not None and error.end_offset is not None:
            end = self.offset(error.end_lineno, error.end_offset - 1)
        return (self.span(start, end) if end > start else self.char(start),)

    def token_error(self, position: object) -> tuple[Span, ...]:
        """Where `tokenize` stopped: `(row, 1-based column)` in its own `\\n`-only rows."""
        match position:
            case (int() as row, int() as column):
                return (self.char(self.token_offset(row, column - 1)),)
            case _:
                return ()
