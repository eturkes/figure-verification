# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The numbers a request types, ranges expanded (ruling 4; stdlib, deterministic).

Read after NFKC. A number = optional sign, digits with optional `,` thousands groups, optional
decimals and exponent; a letter or digit right before it, or a digit right after it, makes it part
of a word (`Q1`, `x2`). `1,200` reads both ways (1200, and 1 and 200), since a list and a thousands
group look alike. An integer range expands to every integer between its ends: `a through b`,
`a to b`, `a thru b`, a U+2013/U+2014 dash, `a~b`, `a〜b`, `aからbまで`; an ASCII hyphen is
never a range,
because dates and negative numbers use it. A range longer than `MAX_RANGE` terms adds its ends
alone.
"""

import itertools
import re
import unicodedata
from dataclasses import dataclass
from typing import Final

MAX_RANGE: Final = 10_000
_NUMBER: Final = re.compile(
    r"(?<![0-9A-Za-z_.])(?<![0-9]-)(?P<sign>[-+])?(?P<body>[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)"
    r"(?P<fraction>\.[0-9]+)?(?P<exponent>[eE][-+]?[0-9]+)?(?![0-9])"
)
_RANGE: Final = re.compile(
    "^\\s*(?:through|thru|to)\\s*$|^\\s*[\N{EN DASH}\N{EM DASH}~〜]\\s*$|^\\s*から\\s*$"
)
_UNTIL: Final = "まで"


@dataclass(frozen=True, slots=True)
class Request:
    """What the request supplies as data: its numbers and its folded text (R4 label search)."""

    numbers: frozenset[float]
    text: str

    def names(self, label: str) -> bool:
        """R4: a category label the request typed, after NFKC + casefold on both sides."""
        folded = fold(label)
        return bool(folded) and folded in self.text


def fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).replace("\N{MINUS SIGN}", "-").casefold()


def _readings(match: re.Match[str]) -> tuple[float, ...]:
    sign = "-" if match["sign"] == "-" else ""
    body = match["body"]
    tail = (match["fraction"] or "") + (match["exponent"] or "")
    whole = float(sign + body.replace(",", "") + tail)
    if "," not in body:
        return (whole,)
    parts = body.split(",")
    listed = [float(sign + parts[0])] + [float(part) for part in parts[1:-1]]
    listed.append(float(parts[-1] + tail))
    return (whole, *listed)


def _integer(match: re.Match[str]) -> int | None:
    if match["fraction"] or match["exponent"] or "," in match["body"]:
        return None
    return int(("-" if match["sign"] == "-" else "") + match["body"])


def read_request(text: str | None) -> Request:
    """The request's numbers + folded text; `None` (no request) supplies nothing."""
    if text is None:
        return Request(frozenset(), "")
    folded = fold(text)
    matches = list(_NUMBER.finditer(folded))
    numbers: set[float] = set()
    for match in matches:
        numbers.update(_readings(match))
    for left, right in itertools.pairwise(matches):
        start, end = _integer(left), _integer(right)
        between = folded[left.end() : right.start()]
        ranged = _RANGE.match(between) is not None
        if ranged and between.strip() == "から":
            ranged = folded.startswith(_UNTIL, right.end())
        if not ranged or start is None or end is None:
            continue
        low, high = min(start, end), max(start, end)
        if high - low < MAX_RANGE:
            numbers.update(float(value) for value in range(low, high + 1))
    return Request(frozenset(numbers), folded)
