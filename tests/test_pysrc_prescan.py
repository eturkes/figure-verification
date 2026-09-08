# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""P1-P13 over `verifier.pysrc.prescan`.

Contract: `.agent/contracts/m13u1.md`.

This is the first surface untrusted model bytes touch, so every refusal path needs its own witness
and the ORDER of the checks is itself a predicate: P1 arms bombs on the two downstream stages,
because an oversized buffer that still gets decoded has already lost the property the byte cap
exists for.

Limits are hand-stated per case rather than read from `DEFAULT_LIMITS`: a test that builds its
expectation from the production constant pins nothing.
"""

from pathlib import Path

import pytest

from verifier.pysrc import prescan as prescan_module
from verifier.pysrc.errors import PysrcCallerError, PysrcRefusalError, RefusalCode
from verifier.pysrc.limits import DEFAULT_LIMITS, PysrcLimits, validate_limits
from verifier.pysrc.prescan import prescan

# Wide enough that only the cap under test can fire.
_ROOMY = PysrcLimits(
    max_source_bytes=100_000,
    max_tokens=10_000,
    max_bracket_depth=64,
    max_indent_depth=16,
    max_line_bytes=10_000,
)


def _refusal_code(source: bytes, limits: PysrcLimits) -> RefusalCode:
    with pytest.raises(PysrcRefusalError) as caught:
        prescan(source, limits)
    return caught.value.code


def test_p1_byte_cap_precedes_decode_and_tokenize(monkeypatch: pytest.MonkeyPatch) -> None:
    """P1: the byte cap is charged first. Acceptance: neither downstream stage runs, proven by
    bombs rather than by the returned code -- the code alone cannot distinguish "refused early"
    from "decoded, tokenized, then refused"."""

    def _decode_bomb(_source: bytes) -> str:
        message = "decode ran despite an oversized buffer"
        raise AssertionError(message)

    def _tokenize_bomb(_text: str) -> list[object]:
        message = "tokenize ran despite an oversized buffer"
        raise AssertionError(message)

    monkeypatch.setattr(prescan_module, "_decode", _decode_bomb)
    monkeypatch.setattr(prescan_module, "_tokenize", _tokenize_bomb)
    assert _refusal_code(b"x" * 11, PysrcLimits(max_source_bytes=10)) == "source_too_large"


def test_p1_boundary_length_is_admitted() -> None:
    """P1: the cap is inclusive. Acceptance: exactly `max_source_bytes` passes."""
    assert prescan(b"x = 1", PysrcLimits(max_source_bytes=5, max_line_bytes=10)) == "x = 1"


def test_p2_non_utf8_refuses() -> None:
    """P2: undecodable bytes get a verdict, not a `UnicodeDecodeError`."""
    assert _refusal_code(b"\xff\xfe = 1", _ROOMY) == "source_not_utf8"


def test_p3_nul_byte_refuses() -> None:
    """P3: a NUL is refused here rather than deeper, keeping the vocabulary total."""
    assert _refusal_code(b"x = 1\x00", _ROOMY) == "source_has_nul"


def test_p4_over_long_line_refuses() -> None:
    """P4: line length is charged per line, measured in UTF-8 bytes."""
    limits = PysrcLimits(max_line_bytes=10)
    assert _refusal_code(b"x = 1\ny = 'aaaaaaaaaaaaaa'\n", limits) == "line_too_long"


def test_p4_boundary_line_is_admitted() -> None:
    """P4: a line of exactly the cap passes; the check is `>` not `>=`."""
    assert prescan(b"x = 123456", PysrcLimits(max_line_bytes=10)) == "x = 123456"


def test_p4_line_length_counts_bytes_not_characters() -> None:
    """P4: a multi-byte character costs its encoded width. Acceptance: 4 astral characters
    exceed a 10-byte cap that 4 ASCII characters would not."""
    assert _refusal_code(
        "# \U0001f600\U0001f600\U0001f600".encode(), PysrcLimits(max_line_bytes=10)
    ) == ("line_too_long")


def test_p5_untokenizable_source_refuses() -> None:
    """P5: an unterminated string is a verdict. Acceptance: `tokenize.TokenError` never escapes --
    it derives straight from `Exception`, so a `ValueError`-only guard would miss it."""
    assert _refusal_code(b"x = 'abc", _ROOMY) == "source_not_tokenizable"


def test_p6_token_count_is_capped() -> None:
    """P6: token count is charged after tokenizing and before any structural walk."""
    assert _refusal_code(b"x = 1\ny = 2\nz = 3\n", PysrcLimits(max_tokens=5)) == "too_many_tokens"


def test_p6_boundary_token_count_is_admitted() -> None:
    """P6: exactly `max_tokens` passes. Acceptance: the count includes NEWLINE and ENDMARKER."""
    source = b"x = 1\n"
    assert prescan(source, PysrcLimits(max_tokens=5)) == "x = 1\n"
    assert _refusal_code(source, PysrcLimits(max_tokens=4)) == "too_many_tokens"


def test_p7_deep_nesting_yields_a_verdict_not_a_recursion_error() -> None:
    """P7: THE predicate this unit exists for. Acceptance: 200 nested parens produce a refusal
    rather than an interpreter-level failure -- `ast.parse` on this input is what the pre-scan
    exists to prevent. The UNBALANCED form is refused one step earlier, by tokenize; both are
    verdicts and neither reaches the parser, which is the property that matters."""
    balanced = b"(" * 200 + b"1" + b")" * 200
    assert _refusal_code(balanced, _ROOMY) == "nesting_too_deep"
    assert _refusal_code(b"(" * 200, _ROOMY) == "source_not_tokenizable"


def test_p7_brackets_inside_a_string_do_not_count() -> None:
    """P7: depth comes from OP tokens only. Acceptance: a title full of parentheses -- ordinary
    matplotlib code -- passes a depth cap a naive character scan would trip."""
    source = b'plt.title("((((((((((((((((((((((((( f(x) = sin(x)")\n'
    assert prescan(source, PysrcLimits(max_bracket_depth=3)) == source.decode()


def test_p7_boundary_depth_is_admitted() -> None:
    """P7: exactly `max_bracket_depth` passes; one deeper refuses."""
    assert prescan(b"x = ((1))", PysrcLimits(max_bracket_depth=2)) == "x = ((1))"
    assert _refusal_code(b"x = ((1))", PysrcLimits(max_bracket_depth=1)) == "nesting_too_deep"


def test_p8_unbalanced_closer_refuses() -> None:
    """P8: a closer with no opener refuses immediately. Acceptance: refusing here keeps the
    counter from going negative, which would mask a genuinely deep region further on."""
    assert _refusal_code(b")\n", _ROOMY) == "unbalanced_brackets"
    assert _refusal_code(b"x = (1))\n", PysrcLimits(max_bracket_depth=2)) == "unbalanced_brackets"


def test_p9_indent_depth_is_capped() -> None:
    """P9: nesting of blocks is bounded independently of bracket depth."""
    source = b"if 1:\n if 1:\n  if 1:\n   x = 1\n"
    assert _refusal_code(source, PysrcLimits(max_indent_depth=2)) == "indent_too_deep"


def test_p9_dedent_restores_budget() -> None:
    """P9: DEDENT decrements. Acceptance: two sibling blocks at the cap pass, proving depth is
    tracked rather than a running count of INDENT tokens."""
    source = b"if 1:\n x = 1\nif 1:\n y = 2\n"
    assert prescan(source, PysrcLimits(max_indent_depth=1)) == source.decode()


def test_p10_refusal_carries_no_source_bytes() -> None:
    """P10: the message IS the code. Acceptance: a distinctive marker in the source appears
    nowhere in the exception, so model-authored text cannot ride a verdict into a log."""
    marker = "S3CR3T_MARKER_TEXT"
    with pytest.raises(PysrcRefusalError) as caught:
        prescan(f"x = '{marker}'\n".encode(), PysrcLimits(max_tokens=1))
    assert caught.value.code == "too_many_tokens"
    assert str(caught.value) == "too_many_tokens"
    assert marker not in str(caught.value)
    assert marker not in repr(caught.value)


def test_p10_every_refusal_code_is_reachable() -> None:
    """P10: the closed vocabulary has no dead member. Acceptance: every literal in `RefusalCode`
    is produced by some input above; an unreachable code is a defect, not spare capacity."""
    observed = {
        _refusal_code(b"x" * 11, PysrcLimits(max_source_bytes=10)),
        _refusal_code(b"\xff", _ROOMY),
        _refusal_code(b"x = 1\x00", _ROOMY),
        _refusal_code(b"y = 'aaaaaaaaaaaaaa'", PysrcLimits(max_line_bytes=10)),
        _refusal_code(b"x = 'abc", _ROOMY),
        _refusal_code(b"x = 1\ny = 2\n", PysrcLimits(max_tokens=3)),
        _refusal_code(b"(" * 200 + b"1" + b")" * 200, _ROOMY),
        _refusal_code(b")", _ROOMY),
        _refusal_code(b"if 1:\n if 1:\n  x = 1\n", PysrcLimits(max_indent_depth=1)),
    }
    assert observed == {
        "source_too_large",
        "source_not_utf8",
        "source_has_nul",
        "line_too_long",
        "source_not_tokenizable",
        "too_many_tokens",
        "nesting_too_deep",
        "unbalanced_brackets",
        "indent_too_deep",
    }


def test_p11_caller_limits_are_threaded_not_defaults() -> None:
    """P11: the passed policy decides. Acceptance: one source, two verdicts, under a policy
    STRICTER than the default -- equal-value arguments would hide a defect that ignores the
    argument and reads `DEFAULT_LIMITS`."""
    source = b"x = ((((1))))"
    assert prescan(source, _ROOMY) == source.decode()
    assert _refusal_code(source, PysrcLimits(max_bracket_depth=2)) == "nesting_too_deep"
    # The default admits it, so a defect substituting DEFAULT_LIMITS would pass the first case.
    assert prescan(source, DEFAULT_LIMITS) == source.decode()


def test_p12_non_positive_limit_is_a_caller_error() -> None:
    """P12: a disabled ceiling is a misconfiguration, not a source verdict. Acceptance: the two
    exception families are unrelated, so a caller error can never be reported as a refusal."""
    for bad in (
        PysrcLimits(max_source_bytes=0),
        PysrcLimits(max_tokens=0),
        PysrcLimits(max_bracket_depth=0),
        PysrcLimits(max_indent_depth=0),
        PysrcLimits(max_line_bytes=-1),
    ):
        with pytest.raises(PysrcCallerError):
            prescan(b"x = 1", bad)
    assert not issubclass(PysrcCallerError, PysrcRefusalError)
    assert not issubclass(PysrcRefusalError, PysrcCallerError)


def test_p12_validate_limits_admits_the_defaults() -> None:
    """P12: the shipped defaults satisfy their own validator."""
    validate_limits(DEFAULT_LIMITS)


def test_p13_prescan_never_reaches_the_parser() -> None:
    """P13: the pre-scan imports no `ast`.

    Acceptance: a committed search over the module source -- the whole point is that nothing here
    can hand bytes to the parser before the caps are charged."""
    source = Path(prescan_module.__file__).read_text(encoding="utf-8")
    code_lines = [
        line
        for line in source.splitlines()
        if line.startswith(("import ", "from ")) and "tokenize" not in line
    ]
    assert not any("ast" in line for line in code_lines), code_lines
