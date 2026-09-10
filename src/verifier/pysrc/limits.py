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
    # Projection-stage ceiling, not a parse ceiling: a grid is what recomputation must evaluate
    # point by point, so the bound matches the shipped `FormulaDomain.samples` cap rather than
    # anything the parser cares about. Two points is the floor -- one point is not a curve.
    min_grid_samples: int = 2
    max_grid_samples: int = 100_000
    # Recomputation ceilings. Every one bounds work the verifier does on UNTRUSTED bytes, and each
    # is checked BEFORE the work it bounds -- a row cap read after materializing the rows buys
    # nothing. Sized for a chat attachment, not for a data warehouse.
    max_csv_bytes: int = 8_000_000
    max_csv_rows: int = 100_000
    max_csv_columns: int = 128
    max_csv_cell_bytes: int = 512
    max_table_rows: int = 100_000
    max_expr_nodes: int = 1_000
    # The binding ceiling in practice: the other caps multiply out to far more evaluation than a
    # demo may spend, so this is what refuses a program that is admissible but not affordable.
    # Measured, not guessed: `tools/bench_pysrc_work.py` on a quiet host of record put the binding
    # rate at 398,458 work/s -- the slowest of both arms, at cell width 31, where `len // 32`
    # surcharges nothing yet the bytes are still read. One second of recomputation, two significant
    # figures. Work binds before `max_table_rows` on purpose: it is size-aware and the row cap is
    # not, so a wide-celled file must refuse on what it actually costs.
    max_work: int = 390_000


DEFAULT_LIMITS = PysrcLimits()


def validate_limits(limits: PysrcLimits) -> None:
    """Refuse a configuration that would disable a ceiling. Raises `PysrcCallerError`."""
    for spec in fields(limits):
        value: int = getattr(limits, spec.name)
        if value < 1:
            message = f"limit {spec.name} must be >= 1"
            raise PysrcCallerError(message)
