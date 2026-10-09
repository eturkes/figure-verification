# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""What key a drawn point belongs to, read off its key axis (`.claude/rules/figure.md` § Values).

A category axis names the category drawn there; a date axis, the reader's calendar reading; a plain
numeric axis, the number itself; a numeric axis whose labels the program or pandas set, the label
of the tick whose band holds the point — or, at an integral position no label reaches, the
position alone (`slot`), which binds to an explanation's key order.
"""

import itertools
from dataclasses import dataclass
from typing import Final

from verifier.figure.description import Axis
from verifier.figure.ticks import labelled

_BAND: Final = 0.5


@dataclass(frozen=True, slots=True)
class Key:
    """Exactly one field is set; all `None` = the point carries no key the chart shows."""

    text: str | None = None
    number: float | None = None
    date: str | None = None
    slot: int | None = None


_NONE: Final = Key()


def _nearest(position: float, ticks: list[tuple[float, str]], half: float) -> str | None:
    """The label of the one tick within `half` of `position` (strictly), else None."""
    near = [text for tick, text in ticks if abs(tick - position) < half]
    return near[0] if len(near) == 1 else None


class KeyReader:
    """Reads keys off one axis; built once per axis, asked once per point."""

    def __init__(self, axis: Axis) -> None:
        self._axis = axis
        self._dates = dict(axis.dates)
        self._labelled = axis.kind == "numeric" and labelled(axis)
        self._categories = sorted((position, name) for name, position in axis.categories or ())
        ticks = sorted((position, text) for position, text in axis.ticks if text.strip())
        self._ticks = ticks
        gaps = [b[0] - a[0] for a, b in itertools.pairwise(ticks)]
        self._half = min(gaps) / 2 if gaps else _BAND

    def key(self, position: float) -> Key:
        """`position` is finite: the mark stage blocked every non-finite coordinate first."""
        kind = self._axis.kind
        if kind == "category":
            name = _nearest(position, self._categories, _BAND)
            return _NONE if name is None else Key(text=name)
        if kind == "date":
            date = self._dates.get(position)
            return _NONE if date is None else Key(date=date)
        return self._numeric(position) if kind == "numeric" else _NONE

    def _numeric(self, position: float) -> Key:
        if not self._labelled:
            return Key(number=position)
        label = _nearest(position, self._ticks, self._half)
        if label is not None:
            return Key(text=label)
        return Key(slot=int(position)) if position.is_integer() and position >= 0 else _NONE
