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
    # An admitted `groupby` chain whose MEANING the projection cannot state. Distinct from
    # `statement_not_projected`: the statement is a projectable kind, and distinct from
    # `column_not_from_source`: the columns may be perfectly valid. What is missing is a rule for
    # the shape -- `.reset_index()` re-spells the channels, a bare column selection reduces nothing.
    "aggregation_not_projected",
    # `plt.figure` after anything already drawn. The new figure would not contain it, so the
    # emitted artifact and the spec would disagree about what the chart holds. Distinct from
    # `statement_not_projected`: the call IS projectable, just not in that position.
    "figure_orphans_mark",
    # bind -- the submitted program versus the artifact the USER supplied. One code covers both
    # arms: the fault shape is "this program is not about your artifact", and which artifact is
    # evident from the program itself.
    "source_not_supplied",
    "target_mismatch",
    # A substitution (Q8): the program drops a CSV column the request names and plots one the
    # request never names. A request naming no column anchors nothing and never reaches this code.
    "column_not_requested",
    # recompute -- reading the user's bytes, then evaluating. `value_not_finite` is the SOLE
    # domain refusal: the evaluator reproduces numpy's IEEE results instead of raising, so every
    # domain and overflow fault arrives as a non-finite value and needs no classification.
    "csv_too_large",
    "csv_not_parsable",
    "column_not_present",
    "column_not_numeric",
    "value_not_in_profile",
    "value_not_finite",
    "work_budget_exceeded",
    # integrity -- what an otherwise-recomputable figure would misrepresent.
    "category_not_unique",
    "x_not_ordered",
    # G10 (Q16): a title, axis label or legend label names a CSV column the chart does not draw,
    # or -- over a reduction -- the summary word of another reduction.
    "label_not_consistent",
]


class PysrcRefusalError(Exception):
    """The submitted source is refused. `code` is the whole verdict; there is no free text."""

    def __init__(self, code: RefusalCode) -> None:
        super().__init__(code)
        self.code: RefusalCode = code


class PysrcCallerError(Exception):
    """The verifier was called wrongly -- a limit it cannot honour, or arguments that disagree with
    each other. Never a verdict about source, and never reachable from submitted bytes."""
