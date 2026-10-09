# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The inlet's prompt templates: the user's task, the attached file, the chart rules (ruling 8).

Model guidance may state every rule the verifier checks; it never moves the boundary, because the
outlet judges the finished figure whatever the model wrote. Nothing from this repository reaches
the production system prompt (user: the deployer cannot change it), so production's templates end
in the `draw_figure` transport paragraph; the demo's end in the bare-source format paragraph its
adapter turns into that call (Q40).
"""

from dataclasses import dataclass
from typing import Final

# The task, then the file the program reads (its sandbox path and header).
_FILE: Final = (
    "{task}\n\nUse the CSV file at /mnt/uploads/{dataset}. Its columns are {columns}.\n"
    "Read the CSV file with pandas. Draw the figure with matplotlib.\n\n"
    "When the task asks for one value per time or category, group by its named field with pandas"
    " and calculate one plotted value per group. For totals, calculate a sum; for averages, a"
    " mean; for highest or lowest values, a maximum or minimum. Draw the grouped values rather"
    " than the original rows.\n\n"
)
_NO_FILE: Final = "{task}\n\nDraw the figure with matplotlib.\n\n"
RULES: Final = (
    "Draw one figure. Plot only values from the CSV file or numbers written in the task, as they"
    " are or as one total, mean, minimum, maximum or row count per group. Keep the chart honest:"
    " bars and filled areas start at zero, axes stay linear and not inverted, every value stays"
    " inside the axis limits, each panel has one set of axes, a legend names every series when"
    " there are two or more, and varying marker sizes or colors have a size legend or a color"
    " bar.\n"
)
TRANSPORT: Final = (
    "\nWrite one complete Python program that draws the chart. Call the draw_figure tool once, with"
    " the whole program as the program argument. Do not put the program in your reply text.\n"
)
FORMAT: Final = "\nReturn one complete Python program as bare source text, no Markdown fences.\n"


@dataclass(frozen=True, slots=True)
class Templates:
    """One artifact's inlet templates: with an attached file, and without one."""

    file: str
    no_file: str


PRODUCTION_TEMPLATES: Final = Templates(_FILE + RULES + TRANSPORT, _NO_FILE + RULES + TRANSPORT)
DEMO_TEMPLATES: Final = Templates(_FILE + RULES + FORMAT, _NO_FILE + RULES + FORMAT)
