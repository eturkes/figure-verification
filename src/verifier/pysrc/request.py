# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Extract a formula target from the user's request, independently of program bytes.

The expression lexer consumes one maximal run at a time. Each carrier is visited once; the
Japanese interval probe skips starts inside a run it has already scanned. Nothing from a model
program or chat history enters this parser.
"""

import math
import re
import unicodedata
from dataclasses import dataclass
from fractions import Fraction
from typing import cast

from verifier.pysrc.limits import DEFAULT_LIMITS, PysrcLimits
from verifier.pysrc.spec import (
    Bin,
    Const,
    Expr,
    Fn,
    FnName,
    FormulaTarget,
    Grid,
    Interval,
    Neg,
    Num,
    Var,
)

REQUEST_GRAMMAR = "pyexpr-0.1"

_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_FUNCTIONS = frozenset({"sin", "cos", "tan", "exp", "log", "sqrt", "abs"})
_CONSTANTS = frozenset({"pi", "e"})
_OPERATORS = frozenset({"+", "-", "*", "/", "(", ")"})


class _InvalidError(Exception):
    """A carrier cannot supply a target, never a verdict about the submitted program."""


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str
    text: str


def _word(char: str) -> bool:
    return "A" <= char <= "Z" or "a" <= char <= "z" or "0" <= char <= "9" or char == "_"


def _japanese(char: str) -> bool:
    return "　" <= char <= "ヿ" or "一" <= char <= "鿿"


def _start_boundary(text: str, index: int) -> bool:
    if index == 0:
        return True
    preceding = text[index - 1]
    return preceding.isspace() or _japanese(preceding) or preceding in ",;:="


def _prose_boundary(text: str, index: int) -> bool:
    if index == len(text):
        return True
    current = text[index]
    if current in " \t\r\n" or _japanese(current):
        return True
    if current in ",;:.?":
        next_index = index + 1
        return (
            next_index == len(text) or text[next_index] in " \t\r\n" or _japanese(text[next_index])
        )
    return False


def _spaces(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t":
        index += 1
    return index


def _lex(text: str, start: int, *, allow_x: bool) -> tuple[list[_Token], int]:
    """Return the maximal run; `end` excludes trailing blanks before a prose boundary."""
    tokens: list[_Token] = []
    index = start
    end = start
    while index < len(text):
        index = _spaces(text, index)
        if index == len(text):
            break
        char = text[index]
        if "0" <= char <= "9":
            matched = _NUMBER.match(text, index)
            if matched is None:  # pragma: no cover - every ASCII digit starts a number
                raise _InvalidError
            tokens.append(_Token("number", matched.group()))
            end = index = matched.end()
        elif ("A" <= char <= "Z") or ("a" <= char <= "z") or char == "_":
            matched = _IDENTIFIER.match(text, index)
            if matched is None:  # pragma: no cover - every ASCII letter starts an identifier
                raise _InvalidError
            name = matched.group()
            if name not in _FUNCTIONS and name not in _CONSTANTS and not (allow_x and name == "x"):
                break
            tokens.append(_Token("name", name))
            end = index = matched.end()
        elif text.startswith("**", index):
            tokens.append(_Token("operator", "**"))
            end = index = index + 2
        elif char in _OPERATORS:
            tokens.append(_Token("operator", char))
            end = index = index + 1
        else:
            break
    return tokens, end


class _Expression:
    def __init__(self, tokens: list[_Token], limits: PysrcLimits) -> None:
        self.tokens = tokens
        self.index = 0
        self.nodes = 0
        self.limits = limits

    def _node(self, value: Expr) -> Expr:
        self.nodes += 1
        if self.nodes > self.limits.max_expr_nodes:
            raise _InvalidError
        return value

    def _nest(self, depth: int) -> int:
        if depth >= self.limits.max_bracket_depth:
            raise _InvalidError
        return depth + 1

    def _peek(self) -> str | None:
        return self.tokens[self.index].text if self.index < len(self.tokens) else None

    def _take(self, expected: str) -> None:
        if self._peek() != expected:
            raise _InvalidError
        self.index += 1

    def parse(self) -> Expr:
        result = self._sum(0)
        if self.index != len(self.tokens):
            raise _InvalidError
        return result

    def _sum(self, depth: int) -> Expr:
        value = self._product(depth)
        while (operator := self._peek()) in ("+", "-"):
            self.index += 1
            right = self._product(depth)
            value = self._node(Bin("add" if operator == "+" else "sub", value, right))
        return value

    def _product(self, depth: int) -> Expr:
        value = self._unary(depth)
        while (operator := self._peek()) in ("*", "/"):
            self.index += 1
            right = self._unary(depth)
            value = self._node(Bin("mul" if operator == "*" else "div", value, right))
        return value

    def _unary(self, depth: int) -> Expr:
        sign = self._peek()
        if sign in ("+", "-"):
            self.index += 1
            operand = self._unary(self._nest(depth))
            return self._node(Neg(operand)) if sign == "-" else operand
        return self._power(depth)

    def _power(self, depth: int) -> Expr:
        value = self._primary(depth)
        if self._peek() == "**":
            self.index += 1
            sign = self._peek()
            if sign in ("+", "-"):
                self.index += 1
                self._nest(depth)
            if self.index == len(self.tokens):
                raise _InvalidError
            token = self.tokens[self.index]
            if token.kind != "number" or not token.text.isdecimal():
                raise _InvalidError
            self.index += 1
            exponent = self._node(Num(Fraction(int(token.text))))
            if sign == "-":
                exponent = self._node(Neg(exponent))
            value = self._node(Bin("pow", value, exponent))
        return value

    def _primary(self, depth: int) -> Expr:
        if self.index == len(self.tokens):
            raise _InvalidError
        token = self.tokens[self.index]
        self.index += 1
        if token.kind == "number":
            if "." in token.text or "e" in token.text.lower():
                float_value = float(token.text)
                if not math.isfinite(float_value):
                    raise _InvalidError
                return self._node(Num(Fraction(float_value)))
            return self._node(Num(Fraction(int(token.text))))
        if token.text == "x":
            return self._node(Var())
        if token.text in _CONSTANTS:
            return self._node(Const("pi" if token.text == "pi" else "e"))
        if token.text in _FUNCTIONS:
            self._take("(")
            argument = self._sum(self._nest(depth))
            self._take(")")
            # The lexer, not the model, chooses the name from the closed function vocabulary.
            return self._node(Fn(cast("FnName", token.text), argument))
        if token.text == "(":
            value = self._sum(self._nest(depth))
            self._take(")")
            return value
        raise _InvalidError


def _expression(text: str, index: int, limits: PysrcLimits, *, allow_x: bool) -> tuple[Expr, int]:
    tokens, end = _lex(text, index, allow_x=allow_x)
    if not tokens:
        raise _InvalidError
    return _Expression(tokens, limits).parse(), end


def _bracket_interval(text: str, start: int, limits: PysrcLimits) -> tuple[Interval, int]:
    left, index = _expression(text, start, limits, allow_x=False)
    index = _spaces(text, index)
    if index == len(text) or text[index] != ",":
        raise _InvalidError
    right, index = _expression(text, index + 1, limits, allow_x=False)
    index = _spaces(text, index)
    if index == len(text) or text[index] != "]":
        raise _InvalidError
    return Interval(left, right), index + 1


def _formula_start(text: str, index: int) -> int | None:
    if index and _word(text[index - 1]):
        return None
    if text.startswith("f(x)", index):
        end = index + 4
    elif text[index] == "y":
        end = index + 1
    else:
        return None
    end = _spaces(text, end)
    return end + 1 if end < len(text) and text[end] == "=" else None


def _bracket_start(text: str, index: int) -> int | None:
    if text[index] != "x" or (index and _word(text[index - 1])):
        return None
    end = _spaces(text, index + 1)
    if text.startswith("∈", end):
        end += 1
    elif text[end : end + 2].lower() == "in":
        end += 2
    else:
        return None
    end = _spaces(text, end)
    return end + 1 if end < len(text) and text[end] == "[" else None


def _count_start(text: str, index: int) -> int | None:
    if text[index] != "n" or (index and _word(text[index - 1])):
        return None
    end = _spaces(text, index + 1)
    return end + 1 if end < len(text) and text[end] == "=" else None


def _from_interval(text: str, index: int, limits: PysrcLimits) -> tuple[Interval, int] | None:
    if (
        (index and _word(text[index - 1]))
        or text[index : index + 4].lower() != "from"
        or text[index + 4 : index + 5] not in (" ", "\t")
    ):
        return None
    try:
        left, end = _expression(text, index + 4, limits, allow_x=False)
        next_word = _spaces(text, end)
        if (
            next_word == end
            or text[next_word : next_word + 2].lower() != "to"
            or text[next_word + 2 : next_word + 3] not in (" ", "\t")
        ):
            return None
        right, end = _expression(text, next_word + 2, limits, allow_x=False)
        if not _prose_boundary(text, end):
            return None
    except _InvalidError:
        return None
    return Interval(left, right), end


def _japanese_interval(text: str, index: int, limits: PysrcLimits) -> tuple[Interval | None, int]:
    tokens, end = _lex(text, index, allow_x=False)
    separator = _spaces(text, end)
    if not tokens or not text.startswith("から", separator):
        return None, end
    try:
        left = _Expression(tokens, limits).parse()
        right, finish = _expression(text, separator + 2, limits, allow_x=False)
    except _InvalidError:
        return None, end
    finish = _spaces(text, finish)
    if not text.startswith("まで", finish):
        return None, end
    return Interval(left, right), finish + 2


def formula_target(  # noqa: PLR0911, PLR0912 - each carrier fails closed in one linear pass
    text: str, limits: PysrcLimits = DEFAULT_LIMITS
) -> FormulaTarget | None:
    """Extract one user-authored formula and interval; any ambiguity leaves no target."""
    normalized = unicodedata.normalize("NFKC", text)
    try:
        if (
            limits.max_source_bytes < 1
            or limits.max_expr_nodes < 1
            or limits.max_bracket_depth < 1
            or len(normalized.encode("utf-8")) > limits.max_source_bytes
        ):
            return None
        formula: Expr | None = None
        interval: Interval | None = None
        samples: int | None = None
        spans: list[tuple[int, int]] = []
        japanese_scanned = 0
        for index in range(len(normalized)):
            if (start := _formula_start(normalized, index)) is not None:
                if formula is not None:
                    return None
                formula, finish = _expression(normalized, start, limits, allow_x=True)
                if not _prose_boundary(normalized, finish):
                    return None
                spans.append((index, finish))
            if (start := _bracket_start(normalized, index)) is not None:
                if interval is not None:
                    return None
                interval, finish = _bracket_interval(normalized, start, limits)
                spans.append((index, finish))
            if (start := _count_start(normalized, index)) is not None:
                if samples is not None:
                    return None
                finish = _spaces(normalized, start)
                begin = finish
                while finish < len(normalized) and "0" <= normalized[finish] <= "9":
                    finish += 1
                if finish == begin or not _prose_boundary(normalized, finish):
                    return None
                samples = int(normalized[begin:finish])
                spans.append((index, finish))
            if (found := _from_interval(normalized, index, limits)) is not None:
                if interval is not None:
                    return None
                interval, finish = found
                spans.append((index, finish))
            if index >= japanese_scanned and _start_boundary(normalized, index):
                japanese_candidate, japanese_scanned = _japanese_interval(normalized, index, limits)
                if japanese_candidate is not None:
                    if interval is not None:
                        return None
                    interval = japanese_candidate
                    spans.append((index, japanese_scanned))
        if formula is None or interval is None:
            return None
        spans.sort()
        if any(spans[index][1] > spans[index + 1][0] for index in range(len(spans) - 1)):
            return None
        grid: Grid | Interval = (
            Grid(interval.start, interval.stop, samples) if samples is not None else interval
        )
        return FormulaTarget(formula, grid)
    except (_InvalidError, UnicodeError, ValueError, OverflowError, RecursionError):
        return None
