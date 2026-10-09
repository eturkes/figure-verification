# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Axes rules over one judged panel (`.claude/rules/figure.md` § Axes rules).

Order (`.agent/archive/contracts/m19u3.md` U2): `mark_not_in_data` → `scale_not_linear` →
`axis_inverted` → `zero_not_in_limits` → `tick_label_mismatch` → `point_clipped`. A truncated bar
axis reports the zero rule, not the clip it implies. Each block marks the program call that set the
offending property when the reader recorded one, else the line that drew the offending mark.
"""

import math
import re
import unicodedata
from typing import Final

from verifier.figure.description import Axes, Axis, Text
from verifier.figure.parts import Mark, Panel
from verifier.figure.reasons import block
from verifier.figure.shapes import coordinates
from verifier.figure.ticks import labelled, mismatched_tick

_LOG_WORDS: Final = re.compile(r"(?<![a-z])log(?:arithmic)?(?![a-z])")
_LOG_JA: Final = "対数"
_MAGNITUDE: Final = frozenset({"bar", "hist", "band"})
# The data dimension a reference family draws in its blended transform.
_REFERENCE_TRANSFORMS: Final = {
    "Axes.axhline": "yaxis",
    "Axes.axhspan": "yaxis",
    "Axes.axvline": "xaxis",
    "Axes.axvspan": "xaxis",
}


def call(axes: Axes, axis: Axis, *slots: str) -> int | None:
    """The program line of the LATEST call among `slots` (axes calls + `axis-` axis calls): each
    slot keeps its last call and the reader's clock orders them (display only, ruling 13)."""
    calls = [(clock, line) for slot, line, clock in axes.calls if slot in slots]
    calls += [(clock, line) for slot, line, clock in axis.calls if f"axis-{slot}" in slots]
    return max(calls)[1] if calls else None


def view(axis: Axis) -> tuple[float, float]:
    low, high = axis.view
    return min(low, high), max(low, high)


def value_on_x(mark: Mark) -> bool:
    """Whether the mark's values lie on x: horizontal bars, hists and vertical references."""
    return mark.horizontal and mark.family in ("bar", "hist", "reference")


def _check_transforms(axes: Axes, panel: Panel) -> None:
    for mark in panel.marks:
        for index in mark.artists:
            artist = axes.artists[index]
            expected = (
                _REFERENCE_TRANSFORMS.get(artist.origin or "", "")
                if mark.family == "reference"
                else "data"
            )
            if artist.transform != expected:
                block("mark_not_in_data", artist.site)


def _names_log(texts: list[Text | None]) -> bool:
    """R3: the axis label or the panel title names the logarithmic scale."""
    for text in texts:
        if text is not None:
            folded = unicodedata.normalize("NFKC", text.text).casefold()
            if _LOG_WORDS.search(folded) or _LOG_JA in folded:
                return True
    return False


def _check_scales(axes: Axes) -> None:
    for name, axis in (("x", axes.x), ("y", axes.y)):
        stated = axis.scale == "log" and _names_log([axis.label, *axes.titles])
        if axis.scale != "linear" and not stated:
            block("scale_not_linear", call(axes, axis, f"{name}scale"))
    for name, axis in (("x", axes.x), ("y", axes.y)):
        if axis.inverted:
            block("axis_inverted", call(axes, axis, f"{name}invert", "axis-invert", f"{name}lim"))


def _check_zero(axes: Axes, panel: Panel) -> None:
    """R1: a magnitude mark's value axis shows zero."""
    for mark in panel.marks:
        if mark.family in _MAGNITUDE:
            name, axis = ("x", axes.x) if value_on_x(mark) else ("y", axes.y)
            low, high = view(axis)
            if not low <= 0.0 <= high:
                site = axes.artists[mark.artists[0]].site
                block("zero_not_in_limits", call(axes, axis, f"{name}lim") or site)


def key_axes(panel: Panel) -> tuple[bool, bool]:
    """(x, y): whether that axis carries keys alone, never a value any mark is read from."""
    x_value = y_value = x_key = y_key = False
    for mark in panel.marks:
        if mark.family == "pie":
            continue
        if mark.family == "hist":  # the bins axis carries the measured values, the other counts
            x_value = y_value = True
        elif mark.family == "reference":
            x_value, y_value = x_value or mark.horizontal, y_value or not mark.horizontal
        elif value_on_x(mark):
            x_value, y_key = True, True
        else:
            x_key, y_value = True, True
    return x_key and not x_value, y_key and not y_value


def _check_ticks(axes: Axes, panel: Panel) -> None:
    x_keys, y_keys = key_axes(panel)
    for name, axis, keys in (("x", axes.x, x_keys), ("y", axes.y, y_keys)):
        if mismatched_tick(axis, key_labels=keys and labelled(axis)) is not None:
            block("tick_label_mismatch", call(axes, axis, f"{name}ticks", "axis-ticks"))


def _check_clipping(axes: Axes, panel: Panel) -> None:
    views = (view(axes.x), view(axes.y))
    for mark in panel.marks:
        if mark.family == "pie":  # matplotlib draws wedges unclipped: no limit hides a share
            continue
        for dimension, value, site in coordinates(axes, mark):
            low, high = views[dimension]
            if math.isfinite(value) and not low <= value <= high:
                name, axis = ("x", axes.x) if dimension == 0 else ("y", axes.y)
                block("point_clipped", call(axes, axis, f"{name}lim") or site)


def check_axes(panel: Panel) -> None:
    axes = panel.axes
    _check_transforms(axes, panel)
    _check_scales(axes)
    _check_zero(axes, panel)
    _check_ticks(axes, panel)
    _check_clipping(axes, panel)
