# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Resource ceilings for the portable core.

Every value is a policy bound on UNTRUSTED input, so each is validated fail-closed before use: a
caller that passes a non-positive cap gets `PysrcCallerError`, never a silently disabled check.
"""

from dataclasses import dataclass, fields

from verifier.pysrc.errors import PysrcCallerError


@dataclass(frozen=True, kw_only=True, slots=True)
class PysrcLimits:
    """Ceilings applied before `ast.parse` sees the source.

    Defaults are sized against observed model-authored plotting programs (completion lengths of
    148-470 tokens, `archive/contracts/m12u7.md`), with headroom, not against what the parser can
    survive -- an admitted program is a short chart script or it is not admitted.
    """

    max_source_bytes: int = 20_000
    max_tokens: int = 4_000
    # A title string full of parentheses does not reach this: depth is counted from OP tokens only.
    max_bracket_depth: int = 16
    max_indent_depth: int = 4
    max_line_bytes: int = 400


DEFAULT_LIMITS = PysrcLimits()


def validate_limits(limits: PysrcLimits) -> None:
    """Refuse a configuration that would disable a ceiling. Raises `PysrcCallerError`."""
    for spec in fields(limits):
        value: int = getattr(limits, spec.name)
        if value < 1:
            message = f"limit {spec.name} must be >= 1"
            raise PysrcCallerError(message)
