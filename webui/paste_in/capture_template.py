# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Generated from corpus/python/capture_prompt_v1.txt; edit that file instead."""

from typing import Final

# The demo's inlet template: the capture template verbatim.
CAPTURE_TEMPLATE: Final = (
    "{task}\n\nUse the CSV file at /mnt/uploads/{dataset}. Its columns are {columns}.\nRead"
    " the CSV file with pandas. Draw the figure with matplotlib.\n\nWhen the task asks for "
    "one value per time or category, group by its named field with pandas and calculate one"
    " plotted value per group. For totals, calculate a sum; for averages, a mean; for highe"
    "st or lowest values, a maximum or minimum. Draw the grouped values rather than the ori"
    "ginal rows.\n\nReturn one complete Python program as bare source text, no Markdown fen"
    "ces.\n"
)
# Production's inlet template: the capture template without its bare-source paragraph.
PRODUCTION_TEMPLATE: Final = (
    "{task}\n\nUse the CSV file at /mnt/uploads/{dataset}. Its columns are {columns}.\nRead"
    " the CSV file with pandas. Draw the figure with matplotlib.\n\nWhen the task asks for "
    "one value per time or category, group by its named field with pandas and calculate one"
    " plotted value per group. For totals, calculate a sum; for averages, a mean; for highe"
    "st or lowest values, a maximum or minimum. Draw the grouped values rather than the ori"
    "ginal rows.\n"
)
