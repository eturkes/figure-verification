# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""One cell as the judge reads it from the user's CSV."""

__all__ = ["CellValue"]

# A text key is a string; every other cell is float64. There is no null and no NaN: the CSV
# profile refuses every NA spelling before a cell reaches here.
type CellValue = float | str
