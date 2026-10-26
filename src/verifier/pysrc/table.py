# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""One cell as the judge reads it from the user's CSV."""

from typing import TypeAlias

__all__ = ["CellValue"]

# A text key is a string; every other cell is float64. There is no null and no NaN: an NA spelling
# reaches here as its text, never as a number.
CellValue: TypeAlias = float | str
