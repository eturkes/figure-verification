# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The closed reasons a figure is blocked for, and the one way a stage blocks (M19).

`.claude/rules/figure.md` § Checks maps each reason to its Show checks row. A stage blocks by
raising `Blocked`, carrying the program line the row listing marks; the judge returns it.
"""

from dataclasses import dataclass
from typing import Literal, NoReturn

FigureReason = Literal[
    # run: the program and the sandbox reply
    "program_syntax_error",
    "program_error",
    "module_not_available",
    "figure_too_large",
    # figure
    "no_figure",
    "multiple_figures",
    "glyph_missing",
    # parts: the closed artist set
    "raster_image",
    "axes_not_judged",
    "axes_twin",
    "axes_overlap",
    "artist_not_judged",
    "no_data",
    # axes
    "mark_not_in_data",
    "scale_not_linear",
    "axis_inverted",
    "zero_not_in_limits",
    "tick_label_mismatch",
    "point_clipped",
    # marks
    "mark_hidden",
    "value_not_finite",
    "bar_not_from_zero",
    "bars_overlap",
    "category_not_unique",
    "x_not_ordered",
    "hist_counts",
    "pie_not_whole",
    "area_not_from_zero",
    "marker_size_varies",
    "marker_color_varies",
    "legend_mismatch",
    # values
    "csv_too_large",
    "csv_not_parsable",
    "work_budget_exceeded",
    "value_not_found",
    "label_not_in_request",
    # columns
    "column_not_requested",
    "column_not_named",
    "label_not_consistent",
]


@dataclass(frozen=True, slots=True)
class Blocked:
    """The figure is blocked for `reason`; `site` = the program line that drew or caused it."""

    reason: FigureReason
    site: int | None = None


class BlockedError(Exception):
    """Carries a `Blocked` verdict out of the stage that decided it."""

    def __init__(self, blocked: Blocked) -> None:
        super().__init__(blocked.reason)
        self.blocked = blocked


def block(reason: FigureReason, site: int | None = None) -> NoReturn:
    raise BlockedError(Blocked(reason, site))
