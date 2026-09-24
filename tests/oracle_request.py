# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Independent pyexpr-0.1 request oracle; outputs tuples, not verifier spec objects."""

from __future__ import annotations

import ast
import math
import re
import unicodedata
from dataclasses import dataclass
from fractions import Fraction
from typing import cast

from verifier.pysrc.limits import DEFAULT_LIMITS, PysrcLimits

type Neutral = tuple[object, ...]
_FN = frozenset({"sin", "cos", "tan", "exp", "log", "sqrt", "abs"})
_CONST = frozenset({"pi", "e"})
_OPERATORS = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.Div: "div"}
_FORMULA = re.compile(r"(?<![A-Za-z0-9_])(?:y|f\(x\))[ \t]*=")
_BRACKET = re.compile(r"(?<![A-Za-z0-9_])x[ \t]*(?:∈|(?i:in))[ \t]*\[")
_FROM = re.compile(r"(?<![A-Za-z0-9_])(?i:from)[ \t]+")
_COUNT = re.compile(r"(?<![A-Za-z0-9_])n[ \t]*=")
_JA = re.compile("から")
_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
_TO = re.compile(r"[ \t]+(?i:to)[ \t]+")
_INT = re.compile(r"[0-9]+")


@dataclass(frozen=True, slots=True)
class _Span:
    start: int
    stop: int
    tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Carrier:
    start: int
    stop: int
    value: Neutral | int | None


def _japanese(ch: str) -> bool:
    return "　" <= ch <= "ヿ" or "一" <= ch <= "鿿"


def _end_boundary(text: str, pos: int) -> bool:
    if pos == len(text):
        return True
    ch = text[pos]
    return (
        ch in " \t\r\n"
        or _japanese(ch)
        or (
            ch in ",;:.?"
            and (pos + 1 == len(text) or text[pos + 1].isspace() or _japanese(text[pos + 1]))
        )
    )


def _start_boundary(text: str, pos: int) -> bool:
    if pos == 0:
        return True
    ch = text[pos - 1]
    return ch.isspace() or _japanese(ch) or ch in ",;:="


def _span(text: str, start: int, *, with_x: bool) -> _Span:
    """Take the maximal context-specific grammar-token run; prose is not a token."""
    pos = start
    words = _FN | _CONST | ({"x"} if with_x else set())
    pieces: list[str] = []
    last = start
    while pos < len(text):
        if text[pos] in " \t":
            pos += 1
            continue
        number = _NUMBER.match(text, pos)
        if number is not None:
            pieces.append(number.group())
            pos = last = number.end()
            continue
        name = _NAME.match(text, pos)
        if name is not None:
            if name.group() not in words:
                break
            pieces.append(name.group())
            pos = last = name.end()
            continue
        if text.startswith("**", pos):
            pieces.append("**")
            pos = last = pos + 2
            continue
        if text[pos] not in "+-*/()":
            break
        pieces.append(text[pos])
        pos = last = pos + 1
    return _Span(start, last, tuple(pieces))


def _depth(tokens: tuple[str, ...]) -> int:
    brackets: list[int] = []
    unary = 0
    peak = 0
    expects_operand = True
    for index, piece in enumerate(tokens):
        if piece in {"+", "-"} and expects_operand:
            unary += 1
            peak = max(peak, len(brackets) + unary)
            continue
        if piece == "(":
            brackets.append(unary)
            peak = max(peak, len(brackets) + unary)
            expects_operand = True
            continue
        if piece == ")":
            unary = brackets.pop() if brackets else 0
            expects_operand = False
            continue
        if piece in {"+", "-", "*", "/", "**"}:
            unary = brackets[-1] if brackets else 0
            expects_operand = True
            continue
        if index + 1 == len(tokens) or tokens[index + 1] != "(":
            unary = brackets[-1] if brackets else 0
        expects_operand = False
    return peak


def _binary(node: ast.BinOp) -> Neutral:
    if isinstance(node.op, ast.Pow):
        exponent = node.right
        if isinstance(exponent, ast.UnaryOp) and isinstance(exponent.op, (ast.UAdd, ast.USub)):
            exponent = exponent.operand
        if not isinstance(exponent, ast.Constant) or type(exponent.value) is not int:
            raise ValueError
        return ("bin", "pow", _tree(node.left), _tree(node.right))
    operation = _OPERATORS.get(type(node.op))
    if operation is None:
        raise ValueError
    return ("bin", operation, _tree(node.left), _tree(node.right))


def _literal(node: ast.Constant) -> Neutral:
    if type(node.value) is int or (type(node.value) is float and math.isfinite(node.value)):
        return ("num", Fraction(node.value))
    raise ValueError


def _name(node: ast.Name) -> Neutral:
    if node.id == "x":
        return ("var",)
    if node.id in _CONST:
        return ("const", node.id)
    raise ValueError


def _tree(node: ast.AST) -> Neutral:
    if isinstance(node, ast.Constant):
        return _literal(node)
    if isinstance(node, ast.Name):
        return _name(node)
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.UAdd):
            return _tree(node.operand)
        if isinstance(node.op, ast.USub):
            return ("neg", _tree(node.operand))
    if isinstance(node, ast.BinOp):
        return _binary(node)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FN
        and len(node.args) == 1
        and not node.keywords
    ):
        return ("fn", node.func.id, _tree(node.args[0]))
    raise ValueError


def _fits_nodes(root: Neutral, cap: int) -> bool:
    pending = [root]
    count = 0
    while pending:
        node = pending.pop()
        count += 1
        if count > cap:
            return False
        if node[0] == "neg":
            pending.append(cast(Neutral, node[1]))
        elif node[0] == "fn":
            pending.append(cast(Neutral, node[2]))
        elif node[0] == "bin":
            pending.extend((cast(Neutral, node[2]), cast(Neutral, node[3])))
    return True


def _parse(span: _Span, limits: PysrcLimits) -> Neutral | None:
    if not span.tokens or _depth(span.tokens) > limits.max_bracket_depth:
        return None
    try:
        # Canonicalize integer spelling before Python parses it: pyexpr permits leading zeroes.
        tokens = (
            str(int(token)) if token.isascii() and token.isdecimal() else token
            for token in span.tokens
        )
        source = " ".join(tokens)
        tree = ast.parse(source, mode="eval").body
        result = _tree(tree)
    except (SyntaxError, ValueError, OverflowError, RecursionError):
        return None
    return result if _fits_nodes(result, limits.max_expr_nodes) else None


def _formula_carriers(text: str, limits: PysrcLimits) -> list[_Carrier]:
    result: list[_Carrier] = []
    for match in _FORMULA.finditer(text):
        span = _span(text, match.end(), with_x=True)
        valid = _end_boundary(text, span.stop)
        result.append(_Carrier(match.start(), span.stop, _parse(span, limits) if valid else None))
    return result


def _bracket_carriers(text: str, limits: PysrcLimits) -> list[_Carrier]:
    result: list[_Carrier] = []
    for match in _BRACKET.finditer(text):
        start = _span(text, match.end(), with_x=False)
        comma = re.match(r"[ \t]*,[ \t]*", text[start.stop :])
        if comma is None:
            result.append(_Carrier(match.start(), start.stop, None))
            continue
        stop = _span(text, start.stop + comma.end(), with_x=False)
        end = re.match(r"[ \t]*\]", text[stop.stop :])
        left, right = _parse(start, limits), _parse(stop, limits)
        result.append(
            _Carrier(
                match.start(),
                stop.stop + end.end() if end else stop.stop,
                ("interval", left, right)
                if end and left is not None and right is not None
                else None,
            )
        )
    return result


def _from_carriers(text: str, limits: PysrcLimits) -> list[_Carrier]:
    result: list[_Carrier] = []
    for match in _FROM.finditer(text):
        start = _span(text, match.end(), with_x=False)
        to = _TO.match(text, start.stop)
        if to is None:
            continue  # Only a complete from/to form counts as a carrier.
        stop = _span(text, to.end(), with_x=False)
        if not _end_boundary(text, stop.stop):
            continue
        left, right = _parse(start, limits), _parse(stop, limits)
        if left is not None and right is not None:
            result.append(_Carrier(match.start(), stop.stop, ("interval", left, right)))
    return result


def _ja_carriers(text: str, limits: PysrcLimits) -> list[_Carrier]:
    result: list[_Carrier] = []
    for pivot in _JA.finditer(text):
        stop = _span(text, pivot.end(), with_x=False)
        ending = re.match(r"[ \t]*まで", text[stop.stop :])
        if ending is None:
            continue
        # Token runs never cross a non-ASCII grammar char. Find the run's beginning once,
        # then consume each candidate at most once; scanning every possible suffix is quadratic.
        begin = pivot.start() - 1
        while begin >= 0 and text[begin] in (
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_()+-*/. \t"
        ):
            begin -= 1
        cursor = begin + 1
        left: _Span | None = None
        while cursor < pivot.start():
            if not _start_boundary(text, cursor):
                cursor += 1
                continue
            candidate = _span(text, cursor, with_x=False)
            between = text[candidate.stop : pivot.start()]
            if candidate.stop > cursor and not between.strip(" \t"):
                if _parse(candidate, limits) is not None:
                    left = candidate
                break
            cursor = max(cursor + 1, candidate.stop + 1)
        if left is None:
            continue
        first, second = _parse(left, limits), _parse(stop, limits)
        if first is not None and second is not None:
            result.append(
                _Carrier(left.start, stop.stop + ending.end(), ("interval", first, second))
            )
    return result


def _count_carriers(text: str) -> list[_Carrier]:
    result: list[_Carrier] = []
    for match in _COUNT.finditer(text):
        pos = match.end()
        while pos < len(text) and text[pos] in " \t":
            pos += 1
        digits = _INT.match(text, pos)
        end = digits.end() if digits else pos
        try:
            count = int(digits.group()) if digits and _end_boundary(text, end) else None
        except ValueError:
            count = None
        result.append(_Carrier(match.start(), end, count))
    return result


def oracle_formula_target(text: str, limits: PysrcLimits = DEFAULT_LIMITS) -> Neutral | None:
    """Return ('target', y, ('interval', start, stop) | ('grid', start, stop, n))."""
    text = unicodedata.normalize("NFKC", text)
    try:
        if len(text.encode("utf-8")) > limits.max_source_bytes:
            return None
    except UnicodeEncodeError:
        return None
    formulas = _formula_carriers(text, limits)
    intervals = [
        *_bracket_carriers(text, limits),
        *_from_carriers(text, limits),
        *_ja_carriers(text, limits),
    ]
    counts = _count_carriers(text)
    carriers = [*formulas, *intervals, *counts]
    if (
        len(formulas) != 1
        or len(intervals) != 1
        or len(counts) > 1
        or any(item.value is None for item in carriers)
    ):
        return None
    if any(
        a.start < b.stop and b.start < a.stop
        for index, a in enumerate(carriers)
        for b in carriers[index + 1 :]
    ):
        return None
    formula, interval = formulas[0].value, intervals[0].value
    if not isinstance(formula, tuple) or not isinstance(interval, tuple):
        return None
    if counts:
        interval = ("grid", interval[1], interval[2], counts[0].value)
    return ("target", formula, interval)
