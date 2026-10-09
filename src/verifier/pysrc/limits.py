# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Ceilings on reading the user's CSV: each bounds work done on UNTRUSTED bytes and is checked
BEFORE the work it bounds -- a row cap read after materializing the rows buys nothing."""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True, slots=True)
class PysrcLimits:
    """Sized for a chat attachment, not for a data warehouse."""

    max_csv_bytes: int = 8_000_000
    max_csv_rows: int = 100_000
    max_csv_columns: int = 128
    max_csv_cell_bytes: int = 512
    max_table_rows: int = 100_000
    # Groups are drawn marks, so this is a legibility ceiling before it is a cost one, and it binds
    # ahead of the reduction, so a high-cardinality key column refuses before its groups exist.
    max_groups: int = 1_000
    # The binding ceiling in practice: about one second of reading on the host of record. Work
    # binds before `max_table_rows` on purpose: it is size-aware and the row cap is not.
    max_work: int = 390_000


DEFAULT_LIMITS = PysrcLimits()
