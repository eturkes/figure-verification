# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Tick labels must denote their positions (ruling 3: each tick label = the value at its position).

Stdlib, deterministic. A numeric label is read the ways matplotlib's formatters write numbers:
NFKC, the minus sign U+2212, mathtext (`$\\mathdefault{10^{2}}$`, `2\\times10^{3}`), `,`
thousands, one leading currency sign, a trailing `%`, one SI prefix (`k`, `M`, …). Its
value must lie within half a unit of its last shown digit of the tick position (times the
ScalarFormatter order, plus its offset). A date label must read as the ISO date at its position.
A category label must be the category drawn there.
"""

import math
import re
import unicodedata
from typing import Final

from verifier.figure.description import Axis

_DATE_FORMATTERS: Final = ("matplotlib.dates", "pandas.")
_SET_LABELS: Final = frozenset({"matplotlib.axis"})
_NUMBER: Final = re.compile(
    r"(?P<sign>[-+]?)[$¥€£]?(?P<after>[-+]?)"
    r"(?P<whole>[0-9]{1,3}(?:,[0-9]{3})+|[0-9]*)(?:\.(?P<fraction>[0-9]+))?"
    r"(?:[eE](?P<exponent>[-+]?[0-9]+))?(?P<prefix>[kMGTmµμunp]?)(?P<percent>\\?%?)"
)
# A power as matplotlib's log formatters write it: `10^{2}`, `2^{3}`, `e^{1}`, `5\times10^{3}`.
_POWER: Final = re.compile(
    r"(?:(?P<mantissa>[-+]?[0-9]+(?:\.[0-9]+)?)\\times ?)?"
    r"(?P<base>[0-9]+(?:\.[0-9]+)?|e)\^\{?(?P<exponent>[-+]?[0-9]+)\}?"
)
_LARGEST: Final = 300  # a decimal exponent past binary64's range names no position
# SI prefixes (`EngFormatter`'s, and the `10k` a program's own formatter writes).
_SI: Final = {
    "k": 3,
    "M": 6,
    "G": 9,
    "T": 12,
    "m": -3,
    "µ": -6,
    "μ": -6,
    "u": -6,
    "n": -9,
    "p": -12,
}
_ISO: Final = re.compile(
    r"[0-9]{4}(?:-[0-9]{2}(?:-[0-9]{2}(?:[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2})?)?)?)?"
)
_ABSOLUTE: Final = 1e-12


def labelled(axis: Axis) -> bool:
    """Labels the program or pandas SET on a numeric axis: they name keys, never numbers."""
    return axis.formatter == "FixedFormatter" or (
        axis.formatter == "FuncFormatter"
        and (axis.formatter_module in _SET_LABELS or axis.formatter_module.startswith("pandas."))
    )


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).strip().replace("\N{MINUS SIGN}", "-")
    if len(text) > 1 and text.startswith("$") and text.endswith("$"):
        text = text[1:-1].replace("\\mathdefault", "").strip()
        if text.startswith("{") and text.endswith("}"):
            text = text[1:-1]
    return text.replace(" ", "")


def _power(power: re.Match[str]) -> list[tuple[float, float]] | None:
    exponent = int(power["exponent"])
    mantissa = power["mantissa"] or "1"
    base = math.e if power["base"] == "e" else float(power["base"])
    if abs(exponent) > _LARGEST or base <= 0.0:
        return None
    value = float(mantissa) * base**exponent
    # A log formatter writes the exact power its tick sits at: the position must be that value.
    return [(value, 0.0)]


def _reading(text: str) -> list[tuple[float, float]] | None:
    """(value, half unit of its last digit) per way the label can be read; None = not a number."""
    power = _POWER.fullmatch(text)
    if power is not None:
        return _power(power)
    match = _NUMBER.fullmatch(text)
    if (
        match is None
        or (match["sign"] and match["after"])
        or not (match["whole"] or match["fraction"])
    ):
        return None
    sign = match["sign"] or match["after"]
    fraction, exponent = match["fraction"] or "", int(match["exponent"] or 0)
    shift = _SI[match["prefix"]] if match["prefix"] else 0
    if abs(exponent + shift - len(fraction)) > _LARGEST or abs(exponent) > _LARGEST:
        return None
    whole = match["whole"].replace(",", "") or "0"
    value = float(f"{sign}{whole}.{fraction or '0'}e{exponent}") * 10.0**shift
    half = 0.5 * 10.0 ** (exponent + shift - len(fraction))
    if not match["percent"]:
        return [(value, half)]
    # `v%` is the value v/100, or v itself when the data are already percentages; a formatter's
    # `xmax` restating 100% as another value would rescale the data, so it earns no reading.
    return [(value / 100.0, half / 100.0), (value, half)]


def _numeric_ok(position: float, text: str, axis: Axis | None) -> bool:
    """`axis` = the major formatter's offset + order; None = a label under no formatter's trust."""
    readings = _reading(_plain(text))
    if readings is None:
        return False
    scale = 10.0 ** (axis.order if axis is not None else 0)
    for value, half in readings:
        shown = value * scale + (axis.offset if axis is not None else 0.0)
        tolerance = half * scale + _ABSOLUTE * max(1.0, abs(position))
        if math.isfinite(shown) and abs(shown - position) <= tolerance:
            return True
    return False


def _date_ok(position: float, text: str, axis: Axis) -> bool:
    dates = dict(axis.dates)
    iso = dates.get(position)
    label = unicodedata.normalize("NFKC", text).strip()
    if iso is None or _ISO.fullmatch(label) is None:
        return False
    return iso.startswith(label.replace(" ", "T"))


def mismatched_tick(axis: Axis, *, key_labels: bool) -> float | None:
    """The first tick position whose label does not denote it, or None.

    `key_labels` = this axis carries set labels that name keys (a numeric key axis): the values
    stage reads them as keys, so they are no numbers here.
    """
    categories = {position: key for key, position in axis.categories or ()}
    for position, text in axis.ticks:
        if not text.strip():
            continue
        if axis.kind == "category":
            ok = categories.get(position) == text
        elif axis.kind == "date":
            ok = axis.formatter_module.startswith(_DATE_FORMATTERS) or _date_ok(
                position, text, axis
            )
        elif axis.kind == "numeric":
            ok = key_labels or _numeric_ok(position, text, axis)
        else:
            ok = False
        if not ok:
            return position
    # Minor labels: a trusted date formatter of their OWN (pandas' month names) is trusted; any
    # other label must denote its position under no formatter's offset or order.
    for position, text in axis.minor:
        if axis.kind == "category":
            ok = categories.get(position) == text
        elif axis.kind == "date":
            ok = axis.minor_formatter_module.startswith(_DATE_FORMATTERS) or _date_ok(
                position, text, axis
            )
        else:
            ok = axis.kind == "numeric" and _numeric_ok(position, text, None)
        if not ok:
            return position
    return None
