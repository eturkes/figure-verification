# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The inlet's prompt templates: the user's task, the attached file or the typed data, the chart
rules (ruling 8).

Model guidance may state every rule the verifier checks; it never moves the boundary, because the
outlet judges the finished figure whatever the model wrote. Nothing from this repository reaches
the production system prompt (user: the deployer cannot change it), so production's templates end
in the `draw_figure` transport paragraph; the demo's end in the bare-source format paragraph its
adapter turns into that call (Q40). The file body and the rules are shared; the no-file body forks.
"""

from dataclasses import dataclass
from typing import Final

# The task, then the file the program reads (its sandbox path and header), then where values come
# from; with `RULES` these are the pre-Q68 bytes (the banner arms + the stub's matches render them).
_FILE: Final = (
    "{task}\n\nUse the CSV file at /mnt/uploads/{dataset}. Its columns are {columns}.\n"
    "Read the CSV file with pandas. Draw the figure with matplotlib.\n\n"
    "When the task asks for one value per time or category, group by its named field with pandas"
    " and calculate one plotted value per group. For totals, calculate a sum; for averages, a"
    " mean; for highest or lowest values, a maximum or minimum. Draw the grouped values rather"
    " than the original rows.\n\n"
    "Draw one figure. Plot only values from the CSV file or numbers written in the task, as they"
    " are or as one total, mean, minimum, maximum or row count per group. "
)
# No file: name none (Q68: a CSV named with none attached made the demo's 0.5B model read one
# that does not exist, 10 of 14 failing typed turns, MX150 greedy). Production adds nothing a
# strong model lacks (user, Q71); the demo's body carries the 0.5B's crutches: lists, one number
# per label, and the task after the guidance, since with the task first a follow-up colour
# (`Make it green.`) was dropped (Q69); the demo's form won grids on the typed prompts.
_NO_FILE: Final = (
    "{task}\n\nNo file is attached. Draw the figure with matplotlib.\n\n"
    "Draw one figure. Plot only numbers written in the task. "
)
_DEMO_NO_FILE: Final = (
    "No file is attached. Write the labels and numbers from the request into Python lists, one"
    " number for each label, in the order given. Draw the figure with matplotlib on one set of"
    " axes, and pass both the labels and the values to the plotting call. Apply every change the"
    " request asks for, such as a color or a title.\n\n"
    "The request: {task}\n\n"
    "Draw one figure. "
)
RULES: Final = (
    "Keep the chart honest: bars and filled areas start at zero, axes stay linear, numeric and"
    " date axes are not inverted, every value stays inside the axis limits, each panel has one set"
    " of axes, a legend names every series when there are two or more, and varying marker sizes or"
    " colors have a size legend or a color bar. With seaborn, pass errorbar=None to bar and line"
    " charts. Draw histograms with plt.hist.\n"
)
TRANSPORT: Final = (
    "\nWrite one complete Python program that draws the chart. Call the draw_figure tool once, with"
    " the whole program as the program argument. Do not put the program in your reply text.\n"
)
FORMAT: Final = "\nReturn one complete Python program as bare source text, no Markdown fences.\n"
# Q78 (user): the rules keep overriding a request that breaks them, and the model says so in the
# `draw_figure` note, which the outlet shows under the verdict. The filter appends it while its
# `model_note` Valve is on, so every template above keeps its measured bytes, and names the
# language by the reply's kana rule: "in the language of the request" made gpt-6-luna write the
# note of an English request in Spanish or French (6 of 6 runs).
NOTE_REQUEST: Final = (
    "\nIf the request, taken as written, asks for anything that the chart rules above do not"
    " allow, follow the rules. Then use the note argument of draw_figure to say what the request"
    " asked for and what the chart shows instead. Write the note in {language}. When the chart"
    " follows the request, leave the note empty.\n"
)
NOTE_LANGUAGES: Final = ("English", "Japanese")


@dataclass(frozen=True, slots=True)
class Templates:
    """One artifact's inlet templates: with an attached file, and without one."""

    file: str
    no_file: str


PRODUCTION_TEMPLATES: Final = Templates(_FILE + RULES + TRANSPORT, _NO_FILE + RULES + TRANSPORT)
DEMO_TEMPLATES: Final = Templates(_FILE + RULES + FORMAT, _DEMO_NO_FILE + RULES + FORMAT)
