# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The refusal the CSV profile raises.

A refusal carries a closed `code` and never any bytes from the file: echoing input back into a
message would carry user bytes into logs and the operator surface.
"""

from typing import Literal

# Closed set: what reading the user's CSV can refuse. A new member needs a distinct fault shape.
RefusalCode = Literal[
    "csv_too_large",
    "csv_not_parsable",
    "value_not_in_profile",
    "work_budget_exceeded",
]


class PysrcRefusalError(Exception):
    """The user's file is refused. `code` is the whole verdict; there is no free text."""

    def __init__(self, code: RefusalCode) -> None:
        super().__init__(code)
        self.code: RefusalCode = code
