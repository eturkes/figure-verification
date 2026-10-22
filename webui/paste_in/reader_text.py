# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The figure reader's exact text, which every target ships into its sandbox unchanged."""

from pathlib import Path

from verifier.figure import reader


def reader_source() -> str:
    """The reader's exact text: the paste-in keeps each embedded module's text, a checkout reads
    the tracked file."""
    embedded = getattr(reader, "__paste_in_source__", None)
    if isinstance(embedded, str):
        return embedded
    return Path(reader.__file__).read_text(encoding="utf-8")
