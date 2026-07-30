# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Closed, bounded expression grammar shared by formula and future derive modes.

The grammar is ``sum -> product -> unary -> power -> primary`` with only decimal
literals, caller-allowlisted variables, ``abs``, ``+ - * /``, and one signed-integer
``**`` exponent. Formula text is parsed into verifier-owned nodes and later interpreted
directly; no ``eval``, ``exec``, ``compile``, ``__import__``, Python ``ast``, or sympy
API exists anywhere on that path.

``print_expr`` is the canonical AST form used by formula provenance. It normalizes exactly
source whitespace, redundant source grouping, decimal-literal spelling to a lowest-terms
``Fraction``, unary plus (the exact rational identity), and integer-exponent sign/leading-zero
spelling. It performs no constant folding or other algebraic rewrite. Parse cost is bounded
by admitted source bytes and tokens/nodes plus the fixed literal-digit ceiling; trusted
allowlist validation additionally depends on allowlist cardinality. No separate parse work
meter is needed, so ``max_formula_work_units`` remains M9.3's cumulative exact-evaluator
budget rather than a parser bound. The structured check names raised here
become registered check IDs when M9.4 wires the engine into the verification spine; until
then this leaf is called only by its tests. The variable allowlist is a caller parameter so
M11 can reuse the same engine with dataset column names bound instead of formula mode's ``x``.
"""

from fractions import Fraction
from typing import Literal, NoReturn, cast

import msgspec

from verifier.errors import VerificationError
from verifier.limits import VerificationLimits

__all__ = [
    "FUNCTION_NAMES",
    "GRAMMAR_VERSION",
    "Abs",
    "Binary",
    "Expr",
    "Neg",
    "Number",
    "ParsedExpr",
    "Pow",
    "Variable",
    "parse_expr",
    "print_expr",
]

GRAMMAR_VERSION = "expr-0.1"
FUNCTION_NAMES: frozenset[str] = frozenset({"abs"})


type Expr = Number | Variable | Neg | Abs | Pow | Binary
type BinaryOp = Literal["add", "sub", "mul", "div"]


class Number(msgspec.Struct, frozen=True, kw_only=True):
    """One exact non-negative decimal literal."""

    value: Fraction

    def __post_init__(self) -> None:
        if abs(self.value.numerator) >= _INTEGER_MAGNITUDE_LIMIT:
            msg = "number numerator exceeds the 512-digit AST magnitude ceiling"
            raise ValueError(msg)
        if self.value.denominator >= _INTEGER_MAGNITUDE_LIMIT:
            msg = "number denominator exceeds the 512-digit AST magnitude ceiling"
            raise ValueError(msg)


class Variable(msgspec.Struct, frozen=True, kw_only=True):
    """One ASCII identifier, making atom/composite printer forms disjoint."""

    name: str

    def __post_init__(self) -> None:
        if not _is_identifier(self.name):
            msg = f"variable name is not an ASCII identifier: {self.name[:16]!r}"
            raise ValueError(msg)


class Neg(msgspec.Struct, frozen=True, kw_only=True):
    operand: Expr


class Abs(msgspec.Struct, frozen=True, kw_only=True):
    operand: Expr


class Pow(msgspec.Struct, frozen=True, kw_only=True):
    base: Expr
    exponent: int

    def __post_init__(self) -> None:
        if abs(self.exponent) >= _INTEGER_MAGNITUDE_LIMIT:
            msg = "power exponent exceeds the 512-digit AST magnitude ceiling"
            raise ValueError(msg)


class Binary(msgspec.Struct, frozen=True, kw_only=True):
    op: BinaryOp
    left: Expr
    right: Expr


class ParsedExpr(msgspec.Struct, frozen=True, kw_only=True):
    """A parsed AST plus the exact resources consumed by its source.

    ``tokens`` excludes spaces and has no EOF sentinel. ``nodes`` counts every AST node;
    a ``Pow`` exponent is an integer field, not a node. ``depth`` is maximum AST depth with
    an atom at depth one. ``paren_depth`` is maximum source-parenthesis nesting, counting
    both grouping and ``abs(``; text with no parentheses has depth zero.
    """

    ast: Expr
    tokens: int
    nodes: int
    depth: int
    paren_depth: int


type _TokenKind = Literal["number", "ident", "+", "-", "*", "/", "**", "(", ")"]
type _Built = tuple[Expr, int]


class _Token(msgspec.Struct, frozen=True, kw_only=True):
    kind: _TokenKind
    text: str
    position: int


_DIGITS = "0123456789"
_LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_IDENT_FIRST = _LETTERS + "_"
_IDENT_REST = _IDENT_FIRST + _DIGITS

# Joint source shapes at the default (32, 32) and ceiling (64, 64) require at most 267
# and 523 active Python calls; printing a ceiling-depth AST requires 65. This basis assumes
# CPython's default recursion limit of 1000; lowering it below roughly 527 invalidates it.
_MAX_FORMULA_AST_DEPTH = 64
_MAX_FORMULA_PAREN_DEPTH = 64
# 512 stays below CPython's minimum permitted sys.int_info.str_digits_check_threshold
# value of 640, so every legal interpreter configuration converts admitted literals.
_MAX_FORMULA_DIGITS = 512
_INTEGER_MAGNITUDE_LIMIT = 10**_MAX_FORMULA_DIGITS
# Bytes, tokens, nodes, and exponent magnitude do not drive parser recursion or integer-string
# conversion; they deliberately have no parser-owned absolute ceiling.


def _resource_error(check: str, label: str, limit: int, position: int) -> NoReturn:
    msg = f"formula {label} limit {limit} exceeded at position {position}"
    raise VerificationError(msg, check=check)


def _grammar_error(position: int, detail: str) -> NoReturn:
    msg = f"formula grammar is not allowed at position {position}: {detail}"
    raise VerificationError(msg, check="formula.grammar_allowed")


def _semantic_error(check: str, position: int, detail: str) -> NoReturn:
    msg = f"formula token at position {position} is not allowed: {detail}"
    raise VerificationError(msg, check=check)


def _is_identifier(name: str) -> bool:
    if not name or name[0] not in _IDENT_FIRST:
        return False
    return all(char in _IDENT_REST for char in name[1:])


def _caller_error(message: str) -> NoReturn:
    """Keep every trusted allowlist-contract breach a native ``ValueError``."""
    raise ValueError(message)


def _validate_limit(field: str, value: int, ceiling: int) -> None:
    if value > ceiling:
        msg = f"{field} must not exceed parser structural ceiling {ceiling}, got {value}"
        _caller_error(msg)


def _validate_limits(limits: VerificationLimits) -> None:
    """Reject trusted policy that would invalidate parser totality or stack safety."""
    _validate_limit(
        "max_formula_ast_depth",
        limits.max_formula_ast_depth,
        _MAX_FORMULA_AST_DEPTH,
    )
    _validate_limit(
        "max_formula_paren_depth",
        limits.max_formula_paren_depth,
        _MAX_FORMULA_PAREN_DEPTH,
    )
    _validate_limit(
        "max_formula_digits",
        limits.max_formula_digits,
        _MAX_FORMULA_DIGITS,
    )


def _validate_allowed_vars(allowed_vars: frozenset[str], limits: VerificationLimits) -> None:
    if type(allowed_vars) is not frozenset:
        msg = "allowed_vars must be a frozenset"
        _caller_error(msg)
    if not allowed_vars:
        msg = "allowed_vars must not be empty"
        _caller_error(msg)
    for value in cast("frozenset[object]", allowed_vars):
        if not isinstance(value, str):
            msg = "allowed_vars entries must be strings"
            _caller_error(msg)
        if not _is_identifier(value):
            msg = f"allowed variable is not an ASCII identifier: {value[:16]!r}"
            _caller_error(msg)
        if len(value) > limits.max_formula_identifier_bytes:
            msg = (
                "allowed variable exceeds max_formula_identifier_bytes "
                f"{limits.max_formula_identifier_bytes}: {value[:16]!r}"
            )
            _caller_error(msg)
        if value in FUNCTION_NAMES:
            msg = f"allowed variable is reserved as a function: {value!r}"
            _caller_error(msg)


def _validate_text_bytes(text: str, limits: VerificationLimits) -> None:
    limit = limits.max_formula_bytes
    if len(text) > limit:
        _resource_error("resource.formula_bytes", "byte", limit, limit + 1)
    try:
        payload = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        _grammar_error(exc.start + 1, "text is not UTF-8 encodable")
    if len(payload) > limit:
        _resource_error("resource.formula_bytes", "byte", limit, max(1, len(text)))


def _emit_token(
    tokens: list[_Token],
    kind: _TokenKind,
    text: str,
    position: int,
    limits: VerificationLimits,
) -> None:
    if len(tokens) >= limits.max_formula_tokens:
        _resource_error(
            "resource.formula_tokens",
            "token",
            limits.max_formula_tokens,
            position + 1,
        )
    tokens.append(_Token(kind=kind, text=text, position=position))


def _scan_number(
    text: str,
    start: int,
    tokens: list[_Token],
    limits: VerificationLimits,
) -> int:
    index = start
    digits = 0
    while index < len(text) and text[index] in _DIGITS:
        digits += 1
        if digits > limits.max_formula_digits:
            _resource_error(
                "resource.formula_digits",
                "numeric-literal digit",
                limits.max_formula_digits,
                index + 1,
            )
        index += 1
    if index < len(text) and text[index] == ".":
        point = index
        index += 1
        if index >= len(text) or text[index] not in _DIGITS:
            _grammar_error(point + 1, "a decimal point needs digits on both sides")
        while index < len(text) and text[index] in _DIGITS:
            digits += 1
            if digits > limits.max_formula_digits:
                _resource_error(
                    "resource.formula_digits",
                    "numeric-literal digit",
                    limits.max_formula_digits,
                    index + 1,
                )
            index += 1
    _emit_token(tokens, "number", text[start:index], start, limits)
    return index


def _scan_identifier(
    text: str,
    start: int,
    tokens: list[_Token],
    limits: VerificationLimits,
) -> int:
    index = start
    while index < len(text) and text[index] in _IDENT_REST:
        if index - start + 1 > limits.max_formula_identifier_bytes:
            _resource_error(
                "resource.formula_identifier_bytes",
                "identifier byte",
                limits.max_formula_identifier_bytes,
                index + 1,
            )
        index += 1
    _emit_token(tokens, "ident", text[start:index], start, limits)
    return index


def _scan_symbol(
    text: str,
    index: int,
    tokens: list[_Token],
    limits: VerificationLimits,
) -> int:
    char = text[index]
    if char == "*":
        if index + 1 < len(text) and text[index + 1] == "*":
            _emit_token(tokens, "**", "**", index, limits)
            return index + 2
        _emit_token(tokens, "*", "*", index, limits)
        return index + 1
    if char in "/+-()":
        kind = cast("_TokenKind", char)
        _emit_token(tokens, kind, char, index, limits)
        return index + 1
    if char == ".":
        _grammar_error(index + 1, "a decimal point needs digits on both sides")
    _grammar_error(index + 1, f"unexpected character {char!r}")


def _lex(text: str, limits: VerificationLimits) -> tuple[_Token, ...]:
    tokens: list[_Token] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == " ":
            index += 1
        elif char in _DIGITS:
            index = _scan_number(text, index, tokens, limits)
        elif char in _IDENT_FIRST:
            index = _scan_identifier(text, index, tokens, limits)
        else:
            index = _scan_symbol(text, index, tokens, limits)
    return tuple(tokens)


class _Parser:
    _tokens: tuple[_Token, ...]
    _allowed_vars: frozenset[str]
    _limits: VerificationLimits
    _text_length: int
    _index: int
    _nodes: int
    _paren_depth: int
    _max_paren_depth: int

    def __init__(
        self,
        tokens: tuple[_Token, ...],
        allowed_vars: frozenset[str],
        limits: VerificationLimits,
        text_length: int,
    ) -> None:
        self._tokens = tokens
        self._allowed_vars = allowed_vars
        self._limits = limits
        self._text_length = text_length
        self._index = 0
        self._nodes = 0
        self._paren_depth = 0
        self._max_paren_depth = 0

    def parse(self) -> ParsedExpr:
        self._ensure_ast_depth(1, self._position())
        node, depth = self._parse_expr(1)
        trailing = self._peek()
        if trailing is not None:
            _grammar_error(
                trailing.position + 1,
                f"unexpected trailing token {trailing.text[:16]!r}",
            )
        return ParsedExpr(
            ast=node,
            tokens=len(self._tokens),
            nodes=self._nodes,
            depth=depth,
            paren_depth=self._max_paren_depth,
        )

    def _peek(self) -> _Token | None:
        if self._index == len(self._tokens):
            return None
        return self._tokens[self._index]

    def _advance(self) -> _Token:
        token = self._tokens[self._index]
        self._index += 1
        return token

    def _position(self) -> int:
        token = self._peek()
        if token is None:
            return self._text_length + 1
        return token.position + 1

    def _ensure_ast_depth(self, depth: int, position: int) -> None:
        if depth > self._limits.max_formula_ast_depth:
            _resource_error(
                "resource.formula_ast_depth",
                "AST depth",
                self._limits.max_formula_ast_depth,
                position,
            )

    def _admit_node(self, depth: int, position: int) -> None:
        self._ensure_ast_depth(depth, position)
        if self._nodes >= self._limits.max_formula_ast_nodes:
            _resource_error(
                "resource.formula_ast_nodes",
                "AST node",
                self._limits.max_formula_ast_nodes,
                position,
            )
        self._nodes += 1

    def _enter_paren(self, token: _Token) -> None:
        depth = self._paren_depth + 1
        if depth > self._limits.max_formula_paren_depth:
            _resource_error(
                "resource.formula_paren_depth",
                "parenthesis depth",
                self._limits.max_formula_paren_depth,
                token.position + 1,
            )
        self._paren_depth = depth
        self._max_paren_depth = max(self._max_paren_depth, depth)

    def _leave_paren(self) -> None:
        self._paren_depth -= 1

    def _parse_expr(self, level: int) -> _Built:
        return self._parse_sum(level)

    def _parse_sum(self, level: int) -> _Built:
        left = self._parse_product(level)
        while True:
            token = self._peek()
            if token is None or token.kind not in ("+", "-"):
                return left
            self._advance()
            self._ensure_ast_depth(level + 1, token.position + 1)
            right = self._parse_product(level + 1)
            op: BinaryOp = "add" if token.kind == "+" else "sub"
            left = self._make_binary(op, left, right, token.position + 1)

    def _parse_product(self, level: int) -> _Built:
        left = self._parse_unary(level)
        while True:
            token = self._peek()
            if token is None or token.kind not in ("*", "/"):
                return left
            self._advance()
            self._ensure_ast_depth(level + 1, token.position + 1)
            right = self._parse_unary(level + 1)
            op: BinaryOp = "mul" if token.kind == "*" else "div"
            left = self._make_binary(op, left, right, token.position + 1)

    def _parse_unary(self, level: int) -> _Built:
        token = self._peek()
        while token is not None and token.kind == "+":
            self._advance()
            token = self._peek()
        if token is not None and token.kind == "-":
            self._advance()
            self._ensure_ast_depth(level + 1, token.position + 1)
            operand = self._parse_unary(level + 1)
            return self._make_neg(operand, token.position + 1)
        return self._parse_power(level)

    def _parse_power(self, level: int) -> _Built:
        base = self._parse_primary(level)
        token = self._peek()
        if token is None or token.kind != "**":
            return base
        self._advance()
        self._ensure_ast_depth(level + 1, token.position + 1)
        exponent = self._parse_exponent(token)
        return self._make_pow(base, exponent, token.position + 1)

    def _parse_exponent(self, power: _Token) -> int:
        sign = 1
        token = self._peek()
        if token is not None and token.kind in ("+", "-"):
            sign = -1 if token.kind == "-" else 1
            self._advance()
            token = self._peek()
        if token is None:
            _grammar_error(self._text_length + 1, "expected a signed integer exponent")
        if token.kind != "number" or "." in token.text:
            _grammar_error(token.position + 1, "expected a signed integer exponent literal")
        self._advance()
        exponent = sign * int(token.text)
        if abs(exponent) > self._limits.max_formula_exponent:
            msg = (
                f"exponent magnitude limit {self._limits.max_formula_exponent} exceeded "
                f"after ** at position {power.position + 1}"
            )
            raise VerificationError(msg, check="formula.exponents_bounded")
        return exponent

    def _parse_primary(self, level: int) -> _Built:
        token = self._peek()
        if token is None:
            _grammar_error(self._text_length + 1, "expected a number, variable, abs, or '('")
        if token.kind == "number":
            self._advance()
            self._admit_node(1, token.position + 1)
            return Number(value=Fraction(token.text)), 1
        if token.kind == "ident":
            return self._parse_identifier(level)
        if token.kind == "(":
            return self._parse_group(level)
        _grammar_error(
            token.position + 1,
            f"expected an expression, found {token.text[:16]!r}",
        )

    def _parse_identifier(self, level: int) -> _Built:
        token = self._advance()
        following = self._peek()
        if following is not None and following.kind == "(":
            if token.text not in FUNCTION_NAMES:
                _semantic_error(
                    "formula.functions_allowed",
                    token.position + 1,
                    f"function {token.text[:16]!r}",
                )
            self._advance()
            return self._parse_abs(token, following, level)
        if token.text in FUNCTION_NAMES:
            _grammar_error(token.position + 1, "reserved function 'abs' requires '(...)'")
        if token.text not in self._allowed_vars:
            _semantic_error(
                "formula.names_allowed",
                token.position + 1,
                f"name {token.text[:16]!r}",
            )
        self._admit_node(1, token.position + 1)
        return Variable(name=token.text), 1

    def _parse_abs(self, function: _Token, left_paren: _Token, level: int) -> _Built:
        self._enter_paren(left_paren)
        self._ensure_ast_depth(level + 1, left_paren.position + 1)
        operand = self._parse_expr(level + 1)
        self._expect_right_paren()
        self._leave_paren()
        depth = operand[1] + 1
        self._admit_node(depth, function.position + 1)
        return Abs(operand=operand[0]), depth

    def _parse_group(self, level: int) -> _Built:
        left_paren = self._advance()
        self._enter_paren(left_paren)
        self._ensure_ast_depth(level, left_paren.position + 1)
        inner = self._parse_expr(level)
        self._expect_right_paren()
        self._leave_paren()
        return inner

    def _expect_right_paren(self) -> None:
        token = self._peek()
        if token is None:
            _grammar_error(self._text_length + 1, "expected ')' before end of formula")
        if token.kind != ")":
            _grammar_error(
                token.position + 1,
                f"expected ')', found {token.text[:16]!r}",
            )
        self._advance()

    def _make_neg(self, operand: _Built, position: int) -> _Built:
        depth = operand[1] + 1
        self._admit_node(depth, position)
        return Neg(operand=operand[0]), depth

    def _make_pow(self, base: _Built, exponent: int, position: int) -> _Built:
        depth = base[1] + 1
        self._admit_node(depth, position)
        return Pow(base=base[0], exponent=exponent), depth

    def _make_binary(
        self,
        op: BinaryOp,
        left: _Built,
        right: _Built,
        position: int,
    ) -> _Built:
        depth = max(left[1], right[1]) + 1
        self._admit_node(depth, position)
        return Binary(op=op, left=left[0], right=right[0]), depth


def parse_expr(
    text: str,
    *,
    allowed_vars: frozenset[str],
    limits: VerificationLimits,
) -> ParsedExpr:
    """Parse one bounded formula into the closed immutable AST, or block it.

    Caller misuse in ``allowed_vars`` or parser-unsafe policy raises ``ValueError``. Every
    rejection of untrusted formula text is a ``VerificationError`` with one stable
    parser/resource check name.
    """
    _validate_limits(limits)
    _validate_allowed_vars(allowed_vars, limits)
    _validate_text_bytes(text, limits)
    tokens = _lex(text, limits)
    return _Parser(tokens, allowed_vars, limits, len(text)).parse()


def print_expr(node: Expr) -> str:
    """Return the injective, single-line canonical prefix form of one AST.

    ASTs produced by ``parse_expr`` under validated policy are bounded by
    ``_MAX_FORMULA_AST_DEPTH`` and safe for this recursive printer. A deeper hand-built
    tree is trusted-caller misuse; this function deliberately performs no validating walk.
    """
    if isinstance(node, Number):
        return str(node.value)
    if isinstance(node, Variable):
        return node.name
    if isinstance(node, Neg):
        return f"(neg {print_expr(node.operand)})"
    if isinstance(node, Abs):
        return f"(abs {print_expr(node.operand)})"
    if isinstance(node, Pow):
        return f"(pow {print_expr(node.base)} {node.exponent})"
    return f"({node.op} {print_expr(node.left)} {print_expr(node.right)})"
