# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Refusal and caller-error types for the portable core.

Two families, deliberately unrelated: `PysrcRefusalError` is a verdict about UNTRUSTED input and is
always convertible into a check result, while `PysrcCallerError` means the operator configured the
verifier wrongly and no verdict about the source exists. Collapsing them would let a
misconfiguration read as a refused program.

A refusal carries a closed `code` and never any bytes from the source. Echoing input back into a
message would smuggle model-authored text into logs, verdicts and, through those, into the operator
surface -- the one place this project must never let the model write.
"""

from typing import Literal

# Closed set. A new member needs a distinct fault shape, not a new phrasing of an existing one.
# Grouped by the stage that can raise it; a stage never raises another stage's code.
RefusalCode = Literal[
    # prescan
    "source_too_large",
    "source_not_utf8",
    "source_has_nul",
    "line_too_long",
    "source_not_tokenizable",
    "too_many_tokens",
    "nesting_too_deep",
    "unbalanced_brackets",
    "indent_too_deep",
    # admit
    "source_not_parsable",
    "statement_not_admitted",
    "expression_not_admitted",
    "import_not_admitted",
    "assign_target_not_admitted",
    "call_target_not_admitted",
    "keyword_not_admitted",
    "attribute_not_admitted",
    "operator_not_admitted",
    "literal_not_admitted",
    "name_not_bound",
    # project -- what an ADMITTED program fails to say about the figure it draws. Distinct from
    # admission: these bytes may run, and the refusal is that the verifier cannot state what they
    # would draw. A construct admitted without a projection rule lands on one of these, never on
    # silence.
    "no_mark",
    "multiple_marks",
    "mark_arity_not_projected",
    "mark_not_valid_for_arm",
    "x_not_a_grid",
    "y_not_over_grid",
    "grid_not_representable",
    "expression_not_projected",
    "label_not_literal",
    "name_rebound",
    "no_terminal",
    "statement_after_terminal",
    "statement_not_projected",
    # project, dataset arm -- each names a fault shape the formula arm cannot produce.
    "arm_ambiguous",
    "no_source",
    "multiple_sources",
    "source_not_literal",
    "column_not_literal",
    "column_not_from_source",
]


class PysrcRefusalError(Exception):
    """The submitted source is refused. `code` is the whole verdict; there is no free text."""

    def __init__(self, code: RefusalCode) -> None:
        super().__init__(code)
        self.code: RefusalCode = code


class PysrcCallerError(Exception):
    """The verifier was configured with limits it cannot honour. Never a verdict about source."""
