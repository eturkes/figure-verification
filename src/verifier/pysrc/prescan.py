# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Bound untrusted bytes BEFORE the CPython parser sees them.

`ast.parse` executes nothing, but it recurses: deeply nested source is answered by a C-stack
failure rather than by an exception a verdict can be built from. A post-parse depth check is
therefore too late, and this module is what runs first. It imports no `ast` at all -- a committed
search test pins that -- so no path here can reach the parser early.

`tokenize` is a TCB addition for this package alone. It is chosen over a hand-rolled character scan
because it understands Python string literals: a naive scan counting `(` would refuse
`plt.title("f(x) = sin(x)")`, which is ordinary matplotlib code. It recurses nowhere, and the byte
cap is charged before it runs, so its worst case is bounded by that cap.

Order is load-bearing and cheapest-first: every step assumes its predecessors held.
"""

import io
import tokenize
from tokenize import TokenInfo
from typing import NoReturn

from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.limits import PysrcLimits, validate_limits

_OPENERS = frozenset("([{")
_CLOSERS = frozenset(")]}")


def _refuse(code: RefusalCode, cause: BaseException | None = None) -> NoReturn:
    raise PysrcRefusalError(code) from cause


def _decode(source: bytes) -> str:
    try:
        return source.decode("utf-8")
    except UnicodeDecodeError as exc:
        _refuse("source_not_utf8", exc)


def _tokenize(text: str) -> list[TokenInfo]:
    try:
        return list(tokenize.generate_tokens(io.StringIO(text).readline))
    # A malformed program must produce a verdict, never a tokenizer traceback. `TokenError` is the
    # actual shape on 3.13 (measured: unterminated string, unterminated triple-quote, trailing
    # backslash) and derives straight from `Exception`, so catching `ValueError` alone would have
    # caught nothing; `SyntaxError` is what the 3.12+ f-string tokenizer raises instead.
    except (tokenize.TokenError, SyntaxError) as exc:
        _refuse("source_not_tokenizable", exc)


def _check_bracket_depth(tokens: list[TokenInfo], limit: int) -> None:
    depth = 0
    for token in tokens:
        if token.type != tokenize.OP:
            continue
        if token.string in _OPENERS:
            depth += 1
            if depth > limit:
                _refuse("nesting_too_deep")
        elif token.string in _CLOSERS:
            depth -= 1
            # A closer with no opener never balances later; refusing here keeps the counter from
            # going negative and masking a genuinely deep region further on.
            if depth < 0:
                _refuse("unbalanced_brackets")


def _check_indent_depth(tokens: list[TokenInfo], limit: int) -> None:
    depth = 0
    for token in tokens:
        if token.type == tokenize.INDENT:
            depth += 1
            if depth > limit:
                _refuse("indent_too_deep")
        elif token.type == tokenize.DEDENT:
            depth -= 1


def prescan(source: bytes, limits: PysrcLimits) -> str:
    """Return the decoded source, or raise `PysrcRefusalError`.

    The returned text is what the caller may hand to `ast.parse`; nothing else in this package
    should parse bytes that did not come back from here.
    """
    validate_limits(limits)

    # First and unconditional: everything below is bounded by this cap, so it may not be skipped
    # or reordered. Charging it against the raw bytes also keeps a decode bomb out of memory.
    if len(source) > limits.max_source_bytes:
        _refuse("source_too_large")

    text = _decode(source)

    # The parser rejects NUL too, but only after accepting the buffer; refusing here keeps the
    # closed refusal vocabulary total over inputs the parser would answer with its own error.
    if "\x00" in text:
        _refuse("source_has_nul")

    for line in text.splitlines():
        if len(line.encode("utf-8")) > limits.max_line_bytes:
            _refuse("line_too_long")

    tokens = _tokenize(text)
    if len(tokens) > limits.max_tokens:
        _refuse("too_many_tokens")

    _check_bracket_depth(tokens, limits.max_bracket_depth)
    _check_indent_depth(tokens, limits.max_indent_depth)
    return text
