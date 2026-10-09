# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Admin-declared column aliases (Q43): the tool Valve's text, parsed.

One line per column, `<column> = <alias>, <alias>`; blank lines are ignored. The full-width equals
sign + comma (U+FF1D, U+FF0C) and the ideographic comma `、` separate as their ASCII forms do: a
Japanese admin types them, and read as alias text `、` would join two aliases into one two-word
name. A line the format cannot read fails the parse, so Open WebUI refuses to save it
(`Valves(**form)` runs the validator).
"""

import re

from verifier.figure.anchoring import Aliases

_EQUALS = re.compile("[=\uff1d]")
_COMMA = re.compile("[,\uff0c\u3001]")


def parse_aliases(text: str) -> Aliases:
    """`text` as (column, alias) pairs, in line order; raise `ValueError` naming the bad line."""
    pairs: list[tuple[str, str]] = []
    columns: set[str] = set()
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parts = _EQUALS.split(line, maxsplit=1)
        if len(parts) != 2:  # noqa: PLR2004 - a column and its alias list
            msg = f"column aliases, line {number}: write <column> = <alias>, <alias>"
            raise ValueError(msg)
        column = parts[0].strip()
        aliases = [alias.strip() for alias in _COMMA.split(parts[1])]
        if not column:
            msg = f"column aliases, line {number}: the column name is empty"
            raise ValueError(msg)
        if column in columns:
            msg = f"column aliases, line {number}: {column} already has a line"
            raise ValueError(msg)
        if not all(aliases):
            msg = f"column aliases, line {number}: an alias is empty"
            raise ValueError(msg)
        if len(set(aliases)) != len(aliases):
            msg = f"column aliases, line {number}: an alias repeats"
            raise ValueError(msg)
        columns.add(column)
        pairs += [(column, alias) for alias in aliases]
    return tuple(pairs)
