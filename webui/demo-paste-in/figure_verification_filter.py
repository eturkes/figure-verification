# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Figure verification for Open WebUI. GENERATED FILE -- do not edit.

Paste the whole file into Open WebUI. It imports the standard library and packages the image
already carries -- `open_webui`, and `pydantic` in the tool -- and nothing else. There is no
`requirements:` frontmatter and no network call.

Regenerate with `uv run --locked python tools/generate_paste_in.py`. The same command with
`--check` fails when this file and its sources disagree, so an edit made here is lost at the next
gate run: change `webui/paste_in/` or `src/verifier/` instead.
"""

import sys
import types

_SOURCES: dict[str, str] = {}

_SOURCES["verifier"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""verifier — trusted core of the figure verifier.

The model writes a chart program; `verifier.figure.reader` reports what the finished matplotlib
figure holds, and the stdlib judge (`verifier.figure`) decides whether it may appear.
"""

__version__ = "0.2.0"
'''

_SOURCES["verifier.figure"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Figure integrity (M19): a sandbox reader reports the finished figure, a stdlib judge decides.

Law = `.claude/rules/figure.md`. `reader` is the one module importing matplotlib, numpy and pandas,
lazily; every other module here is stdlib-only, so the paste-in inlines it.
"""
'''

_SOURCES["verifier.figure.anchoring"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Which header columns a request (or a chart label) names: the lexical matcher (Q8, Q37-Q43).

Moved here from `verifier.pysrc.verify` (M19.4): the figure judge anchors the columns that explain
the drawn values, and G10 reads labels, with this one matcher. Stdlib only.
"""

import re
import unicodedata
from typing import Literal

# The same shapes `verifier.pysrc.spec` names; spelled here so this module imports no pysrc code.
type Aliases = tuple[tuple[str, str], ...]
type Anchoring = Literal["strict", "substitution"]  # production | demo (Q37)
type Reduction = Literal["sum", "mean", "min", "max"]

__all__ = [
    "SUMMARY_WORDS",
    "Aliases",
    "AmbiguousTermError",
    "Anchoring",
    "anchors",
    "nameable",
    "named_columns",
    "summaries",
]


# --- request anchoring (Q8) ----------------------------------------------------------------------
# Which CSV columns a user's request names: lexical term anchoring (user ruling Q8).
#
# A refinement over the three verification tiers, never a prerequisite: a request that names no
# column anchors nothing, and the verdict proceeds exactly as before. Matching is lexical only --
# no synonyms, no translation beyond the admin's declared aliases (Q43) -- so a request names a
# column only by spelling its header or an alias; with no alias, `売上` never names `revenue`,
# while a Japanese request that writes `revenue` does.
#
# Both sides fold through NFKC (full-width forms become ASCII) and `casefold`, then split into
# words at every non-word character, `_` included, and wherever ASCII meets another script: so
# `unit_price` reads as `unit price`, and `regionごとのrevenue` names both columns. An ASCII header
# matches a request word sequence exactly; a Japanese one matches inside the request's words, since
# Japanese text carries no spaces between words. Two characters already make a Japanese word
# (`売上`), while an ASCII name needs three (`x`, `id` are ordinary request words). A one-word name
# of at least `_FUZZY_MIN` characters also matches a request span within Levenshtein distance 1: a
# word for ASCII, a stretch of near length for Japanese. A span close to names of TWO columns, or a
# name two headers fold to, is a tie and is refused: the request does not say which column it means.
_FUZZY_MIN = 5
_ASCII_ANCHOR_MIN = 3
_OTHER_ANCHOR_MIN = 2
_WORD = re.compile(r"[a-z0-9]+|[^\Wa-z0-9_]+")
# Q38: words beside a header name that do not ask for it. A stop phrase is one edit from `orders`
# (`chronological order`); a negated name (`revenue, not orders`, `注文数ではなく`) is excluded,
# never requested. Both are consumed before naming, so neither names a header nor joins a tie.
_STOP_PHRASES = (
    "chronological order",
    "alphabetical order",
    "descending order",
    "ascending order",
    "numerical order",
    "reverse order",
    "sorted order",
    "sort order",
    "in order",
)
_NEGATION_BEFORE = re.compile(r" (?:not|no|without|except|excluding|rather than|instead of)(?= )")
_FILLERS = (" the ", " any ")
_NEGATION_AFTER = ("ではなく", "じゃなく", "でなく", "以外", "を除")
# Q41, strict anchoring alone: Japanese writes a shorter word for a short column (`月ごと` for
# `年月`, `日ごと` for `日付`). A whole kanji run equal to a 2-4 character name minus its first or
# last character names it; containment cannot, and the shared matcher keeps it out, because a
# one-kanji word also appears in unrelated words (`別` in `診療科別` fits `性別`).
# Every CJK ideograph block NFKC can leave in place: Ext A, the main block, the compatibility
# block (`﨑` is NFKC-stable), Ext B+ (`𠮷`); a run split at one of them is no whole run.
_KANJI_RUN = re.compile(r"[\u3005\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0003ffff]+")
_SHORT_NAME_MAX = 4
# Q42: grouping suffixes a short word takes (`月別`, `月毎`, `月次`, `月単位`), longest
# first; one is cut from a run's end before Q41 reads it.
_SUFFIXES = ("単位", "別", "毎", "次")


class AmbiguousTermError(ValueError):
    """One request word sits within edit distance 1 of two different headers."""


def _words(text: str) -> str:
    """`text` as its folded words, one space apart."""
    return " ".join(_WORD.findall(unicodedata.normalize("NFKC", text).casefold()))


def _within_one(left: str, right: str) -> bool:
    """Levenshtein distance at most 1, in one pass."""
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) > len(right):
        left, right = right, left
    for index, (a, b) in enumerate(zip(left, right, strict=False)):
        if a != b:
            tail = index + 1 if len(left) == len(right) else index
            return left[tail:] == right[index + 1 :]
    return True


def _near_names(rest: str, keys: list[str]) -> list[set[str]]:
    """The names within one edit of each place in the request, overlapping stretches merged.

    A stretch is a whole word for an ASCII name, and a substring one character shorter, as long or
    longer for a Japanese one. Overlapping stretches are one place in the request, so a place within
    one edit of two names is a tie even where no single stretch fits both (`収張期血圧`).
    """
    runs = [run for run in rest.split() if run != "\0"]
    hits: list[tuple[int, int, int, str]] = []
    for key in keys:
        for index, run in enumerate(runs):
            if run.isascii() != key.isascii():
                continue
            windows = (
                [(0, len(run))]
                if key.isascii()
                else [
                    (start, start + width)
                    for width in (len(key) - 1, len(key), len(key) + 1)
                    for start in range(len(run) - width + 1)
                ]
            )
            hits += [(index, s, e, key) for s, e in windows if _within_one(run[s:e], key)]
    places: list[set[str]] = []
    place_run, place_end = -1, 0
    for index, start, end, key in sorted(hits):
        if index != place_run or start >= place_end:
            places.append(set())
            place_run, place_end = index, end
        places[-1].add(key)
        place_end = max(place_end, end)
    return places


def _floor(key: str) -> int:
    """The shortest header name that anchors: `x`, `id` are ordinary request words."""
    return _ASCII_ANCHOR_MIN if key.isascii() else _OTHER_ANCHOR_MIN


def _negated_end(rest: str, start: int, keys: list[str], fuzzy: list[str]) -> int | None:
    """Where the name opening at `start` (the space before it) ends, or None for a non-name."""
    for key in keys:
        if rest.startswith(f" {key} ", start):
            return start + 1 + len(key)
    end = rest.find(" ", start + 1)
    word = rest[start + 1 : end]
    if word.isascii() and any(_within_one(word, key) for key in fuzzy):
        return end
    return None


def _unnamed_places(rest: str, names: list[str]) -> tuple[str, bool]:
    """`rest` with every stop phrase and every negated name consumed (Q38), and whether a name was
    negated: strict anchoring (Q37) reads an excluded column as the request naming its columns.

    A negated name = the longest anchoring name right after an English cue (or after the cue + one
    `the`/`any`), else one ASCII word within one edit of a one-word name of `_FUZZY_MIN`+
    characters; or a name right before a Japanese cue. A cue before anything else negates nothing
    (`not only revenue`). The English scan reads by position and rebuilds the text once, so its
    work stays linear in the request.
    """
    keys = sorted((key for key in names if len(key) >= _floor(key)), key=len, reverse=True)
    fuzzy = [key for key in keys if " " not in key and len(key) >= _FUZZY_MIN]
    for phrase in _STOP_PHRASES:
        needle = f" {phrase} "
        while phrase not in names and needle in rest:
            rest = rest.replace(needle, " \0 ")
    spans: list[tuple[int, int]] = []
    for cue in _NEGATION_BEFORE.finditer(rest):
        start = cue.end()
        if spans and cue.start() < spans[-1][1]:
            continue
        end = _negated_end(rest, start, keys, fuzzy)
        if end is None and rest.startswith(_FILLERS, start):
            end = _negated_end(rest, start + 4, keys, fuzzy)
            start += 4
        if end is not None:
            spans.append((start, end))
    if spans:
        pieces: list[str] = []
        last = 0
        for start, end in spans:
            pieces += [rest[last : start + 1], "\0"]
            last = end
        rest = "".join([*pieces, rest[last:]])
    negated = bool(spans)
    for key in keys:
        # The same place naming matches: an ASCII name as whole words, any other by containment;
        # `_words` splits an ASCII tail from the Japanese cue after it.
        lead = " " if key.isascii() else ""
        gap = " " if key[-1].isascii() else ""
        for after in _NEGATION_AFTER:
            needle = f"{lead}{key}{gap}{after}"
            while needle in rest:
                negated = True
                rest = rest.replace(needle, f" \0 {after}")
    return rest, negated


def named_columns(
    text: str, header: tuple[str, ...], aliases: Aliases = (), *, ignore_ties: bool = False
) -> frozenset[str]:
    """The header names `text` names; a tie raises `AmbiguousTermError`, or names nothing."""
    return anchors(text, header, aliases, ignore_ties=ignore_ties)[0]


def _keys(header: tuple[str, ...], aliases: Aliases) -> dict[str, list[str]]:
    """Each folded name -> the header columns it names: every column's own name, then each admin
    alias (Q43) of every column whose folded name matches the alias's column. A name two columns
    share is a tie, as a fold twin is; an alias of a column the header lacks names nothing."""
    by_key: dict[str, list[str]] = {}
    for column in header:
        by_key.setdefault(_words(column), []).append(column)
    for target, alias in aliases:
        for column in (column for column in header if _words(column) == _words(target)):
            columns = by_key.setdefault(_words(alias), [])
            if column not in columns:
                columns.append(column)
    return by_key


def _short_names(words: str, by_key: dict[str, list[str]]) -> set[str]:
    """The 2-4 character Japanese names a whole kanji run names by dropping one end (Q41), the
    run read also without one grouping suffix (Q42: `月別` → `年月`).

    `words` = the folded request before any name is consumed, so a run is whole in the
    request itself: `診療科別` stays one run where `診療科` is a header, and its `別` never
    names `性別`. A run a Japanese header name overlaps belongs to that exact name; a run
    fitting names of two columns names neither; a run before a Japanese negation cue names
    nothing (as N3 reads an exact name there). A name two headers fold to never names this way.
    """
    exact = [key for key in by_key if not key.isascii() and len(key) >= _OTHER_ANCHOR_MIN]
    keys = [key for key in exact if len(key) <= _SHORT_NAME_MAX]
    found: set[str] = set()
    for run in _KANJI_RUN.finditer(words):
        start, end = run.span()
        if words.startswith(_NEGATION_AFTER, end) or any(
            key in words[max(0, start - len(key) + 1) : end + len(key) - 1] for key in exact
        ):
            continue
        # Q42: the run read whole, and again with one grouping suffix cut from its end; a run
        # and its stem fitting different names is a tie like any other.
        cut = next((suffix for suffix in _SUFFIXES if run[0].endswith(suffix)), "")
        stem = run[0][: len(run[0]) - len(cut)] if cut else ""
        fits = {key for key in keys if {run[0], stem} & {key[1:], key[:-1]}}
        # Fits naming ONE column (its name and an admin alias, Q43) name it. A fold-twin name joins
        # the count, so it ties a run it fits, yet names nothing itself.
        if len({column for key in fits for column in by_key[key]}) == 1:
            found.add(min(fits))
    return found


def anchors(
    text: str,
    header: tuple[str, ...],
    aliases: Aliases = (),
    *,
    ignore_ties: bool = False,
    short_names: bool = False,
) -> tuple[frozenset[str], bool]:
    """`named_columns`, and whether `text` negates a header name (Q38); `short_names` adds
    strict anchoring's Japanese short-word tier (Q41)."""
    by_key = _keys(header, aliases)
    words = f" {_words(text)} "
    rest, negated = _unnamed_places(words, list(by_key))
    named: set[str] = set()
    # Exact names first, longest first, each consuming its span: `unit price` never also names
    # `price`, and `収縮期血圧値` never also names `収縮期血圧`.
    for key in sorted(by_key, key=len, reverse=True):
        needle = f" {key} " if key.isascii() else key
        if len(key) >= _floor(key) and needle in rest:
            named.add(key)
            while needle in rest:  # adjacent occurrences share a space; one pass skips every second
                rest = rest.replace(needle, " \0 ")
    # Then one edit, over what exact names left, against every one-word name of 5+ characters.
    if short_names:
        named |= _short_names(words, by_key)
    near = _near_names(rest, [key for key in by_key if " " not in key and len(key) >= _FUZZY_MIN])
    # A tie: one place in the request within one edit of names of two columns, or one name two
    # headers fold to. Names of ONE column (its name and an admin alias, Q43) name it.
    tied: list[list[str]] = []
    for keys in near:
        if len(keys) == 1 or len({column for key in keys for column in by_key[key]}) == 1:
            named.add(min(keys))
        else:
            tied.append(sorted(keys))
    tied += [[key] for key in named if len(by_key[key]) > 1]
    if tied and not ignore_ties:
        message = f"request places {sorted(tied)} each fit more than one header"
        raise AmbiguousTermError(message)
    return frozenset(by_key[key][0] for key in named if len(by_key[key]) == 1), negated


def nameable(column: str, aliases: Aliases = ()) -> bool:
    """A request can name `column`: its folded name, or an admin alias of it, reaches the anchor
    minimum."""
    return any(
        column in columns and len(key) >= _floor(key)
        for key, columns in _keys((column,), aliases).items()
    )


# --- label consistency (G10, Q16) ----------------------------------------------------------------
# A label is the figure's own claim about what it shows, and G10 checks that claim against the
# projection with the request-anchoring matcher above. It refuses a POSITIVE mismatch alone: a
# title, axis label or legend label naming a CSV column the chart does not draw, or -- over a
# reduction -- the summary word of a different reduction (`Total` over a mean). A label naming
# nothing checkable passes; a word tied between two headers names nothing. Without a reduction a
# summary word goes unread, since a raw column may itself hold totals or averages; and a summary
# word that is also a word of some header (`total_revenue`) names that column, never a summary.
# ASCII summary words match whole words; Japanese ones match inside the label's words.
SUMMARY_WORDS: dict[str, Reduction | None] = {
    "sum": "sum",
    "sums": "sum",
    "summed": "sum",
    "total": "sum",
    "totals": "sum",
    "mean": "mean",
    "means": "mean",
    "average": "mean",
    "averages": "mean",
    "avg": "mean",
    "min": "min",
    "minimum": "min",
    "max": "max",
    "maximum": "max",
    # A summary no admitted reduction computes: naming it is a mismatch under every reduction.
    "median": None,
    "合計": "sum",
    "総計": "sum",
    "平均": "mean",
    "最小": "min",
    "最大": "max",
    "中央値": None,
}


def summaries(text: str, header: tuple[str, ...], aliases: Aliases = ()) -> set[Reduction | None]:
    """The reductions `text` names by a summary word no header name or alias uses."""
    joined = _words(text)
    words = set(joined.split())
    header_text = " ".join(_keys(header, aliases))
    header_words = set(header_text.split())
    found: set[Reduction | None] = set()
    for word, reduction in SUMMARY_WORDS.items():
        if word.isascii():
            if word in words and word not in header_words:
                found.add(reduction)
        elif word in joined and word not in header_text:
            found.add(reduction)
    return found
'''

_SOURCES["verifier.figure.description"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The reader's figure description, decoded strictly into closed types (stdlib; M19).

The description is the judge's only view of the figure, so this decoder admits exactly the shape
`reader.py` writes: one tagged line, a closed key set at every level, every value exactly typed
(a JSON `true` is no integer, `1` is no float), non-finite numbers only as the strings `nan`
`inf` `-inf`. Anything else decodes to `None`, which the outlet reports as `no_description`.
"""

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

TAG: Final = "FIGURE_VERIFICATION_DESCRIPTION:"
VERSION: Final = "figure-description/1"
MAX_BYTES: Final = 400_000
_NON_FINITE: Final = {"nan": math.nan, "inf": math.inf, "-inf": -math.inf}
_ERROR_KINDS: Final = frozenset({"syntax", "exception", "draw"})
_AXIS_KINDS: Final = frozenset({"numeric", "category", "date", "unknown"})
_TRANSFORMS: Final = frozenset({"data", "axes", "xaxis", "yaxis", "figure", "other"})
_ORIENTATIONS: Final = frozenset({"vertical", "horizontal"})
_ELEMENT_PROPS: Final = frozenset({"sizes", "colors"})

type Color = tuple[float, float, float, float]
type Pair = tuple[float, float]


@dataclass(frozen=True, slots=True)
class ProgramError:
    kind: str  # syntax | exception | draw
    name: str
    line: int | None


@dataclass(frozen=True, slots=True)
class Text:
    text: str
    site: int | None


@dataclass(frozen=True, slots=True)
class LineGeometry:
    x: tuple[float, ...]
    y: tuple[float, ...]
    color: Color
    marker: str
    linestyle: str
    drawstyle: str
    linewidth: float
    markersize: float
    marker_face: Color
    marker_edge: Color


@dataclass(frozen=True, slots=True)
class RectGeometry:
    x: float
    y: float
    width: float
    height: float
    angle: float
    color: Color
    edge: Color
    linewidth: float


@dataclass(frozen=True, slots=True)
class WedgeGeometry:
    cx: float
    cy: float
    r: float
    width: float | None
    theta1: float
    theta2: float
    color: Color
    edge: Color
    linewidth: float


@dataclass(frozen=True, slots=True)
class PolygonGeometry:
    xy: tuple[Pair, ...]
    color: Color
    edge: Color
    linewidth: float


@dataclass(frozen=True, slots=True)
class ScatterGeometry:
    offsets: tuple[Pair, ...]
    sizes: tuple[float, ...]
    colors: tuple[Color, ...]
    edges: tuple[Color, ...]
    linewidths: tuple[float, ...]
    array: tuple[float, ...] | None
    colorbar: bool


@dataclass(frozen=True, slots=True)
class BandArrays:
    """A plain `fill_between` call's arrays, read back from its one polygon (no `where`/`step`)."""

    x: tuple[float, ...]
    y1: tuple[float, ...]
    y2: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class BandGeometry:
    paths: tuple[tuple[Pair, ...], ...]
    color: Color | None
    edge: Color | None
    linewidth: float
    band: BandArrays | None
    inputs: int | None  # how many points the `fill_between` call received


@dataclass(frozen=True, slots=True)
class TextGeometry:
    text: str


@dataclass(frozen=True, slots=True)
class NoGeometry:
    """An artist class the reader does not measure; the judge refuses it by class."""


type Geometry = (
    LineGeometry
    | RectGeometry
    | WedgeGeometry
    | PolygonGeometry
    | ScatterGeometry
    | BandGeometry
    | TextGeometry
    | NoGeometry
)


@dataclass(frozen=True, slots=True)
class Artist:
    cls: str
    origin: str | None
    site: int | None
    visible: bool
    alpha: float | None
    label: str
    transform: str
    geometry: Geometry


@dataclass(frozen=True, slots=True)
class HistRecord:
    values: tuple[float, ...]
    bins: tuple[float, ...]
    density: bool
    weighted: bool
    cumulative: bool
    histtype: str
    datasets: int


@dataclass(frozen=True, slots=True)
class Container:
    cls: str
    orientation: str | None
    label: str
    members: tuple[int, ...]
    hist: HistRecord | None


@dataclass(frozen=True, slots=True)
class PieRecord:
    values: tuple[float, ...]
    normalize: bool
    wedges: tuple[int, ...]
    texts: tuple[int | None, ...]  # each wedge's drawn label Text (artist index), if any


@dataclass(frozen=True, slots=True)
class LegendEntry:
    text: str
    axes: int | None  # the axes holding the named artist/container/collection
    target: int | None
    container: int | None
    proxy_color: Color | None
    elements_of: tuple[int | None, str] | None


@dataclass(frozen=True, slots=True)
class Legend:
    site: int | None
    entries: tuple[LegendEntry, ...]


@dataclass(frozen=True, slots=True)
class Axis:
    label: Text | None
    scale: str
    view: Pair
    inverted: bool
    kind: str  # numeric | category | date | unknown
    categories: tuple[tuple[str, float], ...] | None
    formatter: str
    formatter_module: str
    offset: float
    order: int
    percent_xmax: float | None
    ticks: tuple[tuple[float, str], ...]
    minor: tuple[tuple[float, str], ...]  # visible non-empty minor labels
    minor_formatter_module: str
    dates: tuple[tuple[float, str | None], ...]
    calls: tuple[tuple[str, int, int], ...]  # (slot, program line, call clock)


@dataclass(frozen=True, slots=True)
class Axes:
    cls: str
    site: int | None
    visible: bool
    position: tuple[float, float, float, float]
    colorbar_of: tuple[int, int] | None
    shared_x: tuple[int, ...]
    shared_y: tuple[int, ...]
    titles: tuple[Text | None, Text | None, Text | None]
    x: Axis
    y: Axis
    calls: tuple[tuple[str, int, int], ...]  # (slot, program line, call clock)
    artists: tuple[Artist, ...]
    containers: tuple[Container, ...]
    pies: tuple[PieRecord, ...]
    legend: Legend | None


@dataclass(frozen=True, slots=True)
class Part:
    cls: str
    origin: str | None
    site: int | None


@dataclass(frozen=True, slots=True)
class Figure:
    site: int | None
    titles: tuple[Text | None, Text | None, Text | None]  # suptitle, supxlabel, supylabel
    texts: tuple[Text, ...]
    legends: tuple[Legend, ...]
    others: tuple[Part, ...]
    axes: tuple[Axes, ...]


@dataclass(frozen=True, slots=True)
class Description:
    version: str
    error: ProgramError | None
    too_large: bool
    glyphs: int
    figures: tuple[Figure, ...]


class _InvalidError(ValueError):
    """The value is not the shape the reader writes."""


def _object(value: object, keys: tuple[str, ...]) -> dict[str, object]:
    if type(value) is not dict or set(value) != set(keys):
        raise _InvalidError
    return value


def _list(value: object) -> list[object]:
    if type(value) is not list:
        raise _InvalidError
    return value


def _int(value: object) -> int:
    if type(value) is not int:
        raise _InvalidError
    return value


def _bool(value: object) -> bool:
    if type(value) is not bool:
        raise _InvalidError
    return value


def _str(value: object) -> str:
    if type(value) is not str:
        raise _InvalidError
    return value


def _float(value: object) -> float:
    if type(value) is float and math.isfinite(value):  # `1e999` parses to inf: never a number
        return value
    if type(value) is str and value in _NON_FINITE:
        return _NON_FINITE[value]
    raise _InvalidError


def _choice(value: object, allowed: frozenset[str]) -> str:
    if type(value) is not str or value not in allowed:
        raise _InvalidError
    return value


def _optional[T](value: object, read: Callable[[object], T]) -> T | None:
    return None if value is None else read(value)


def _tuple[T](value: object, read: Callable[[object], T]) -> tuple[T, ...]:
    return tuple(read(item) for item in _list(value))


def _pair(value: object) -> Pair:
    items = _list(value)
    if len(items) != 2:  # noqa: PLR2004 - a coordinate pair
        raise _InvalidError
    return _float(items[0]), _float(items[1])


def _color(value: object) -> Color:
    items = _list(value)
    if len(items) != 4:  # noqa: PLR2004 - RGBA
        raise _InvalidError
    red, green, blue, alpha = (_float(item) for item in items)
    return red, green, blue, alpha


def _text(value: object) -> Text:
    item = _object(value, ("text", "site"))
    return Text(_str(item["text"]), _optional(item["site"], _int))


def _titles(value: object) -> tuple[Text | None, Text | None, Text | None]:
    items = _list(value)
    if len(items) != 3:  # noqa: PLR2004 - three title slots
        raise _InvalidError
    first, second, third = (_optional(item, _text) for item in items)
    return first, second, third


def _call(key: str, value: object) -> tuple[str, int, int]:
    items = _list(value)
    if len(items) != 2:  # noqa: PLR2004 - (line, clock)
        raise _InvalidError
    return _str(key), _int(items[0]), _int(items[1])


def _calls(value: object) -> tuple[tuple[str, int, int], ...]:
    if type(value) is not dict:
        raise _InvalidError
    return tuple(_call(key, call) for key, call in value.items())


def call_line(calls: tuple[tuple[str, int, int], ...], slot: str) -> int | None:
    """The program line of `slot`'s last recorded call, or None."""
    return next((line for name, line, _ in calls if name == slot), None)


def _line(item: dict[str, object]) -> LineGeometry:
    item = _object(
        item,
        (
            "kind",
            "x",
            "y",
            "color",
            "marker",
            "linestyle",
            "drawstyle",
            "linewidth",
            "markersize",
            "marker_face",
            "marker_edge",
        ),
    )
    x, y = _tuple(item["x"], _float), _tuple(item["y"], _float)
    if len(x) != len(y):
        raise _InvalidError
    return LineGeometry(
        x,
        y,
        _color(item["color"]),
        _str(item["marker"]),
        _str(item["linestyle"]),
        _str(item["drawstyle"]),
        _float(item["linewidth"]),
        _float(item["markersize"]),
        _color(item["marker_face"]),
        _color(item["marker_edge"]),
    )


def _rect(item: dict[str, object]) -> RectGeometry:
    item = _object(
        item, ("kind", "x", "y", "width", "height", "angle", "color", "edge", "linewidth")
    )
    return RectGeometry(
        _float(item["x"]),
        _float(item["y"]),
        _float(item["width"]),
        _float(item["height"]),
        _float(item["angle"]),
        _color(item["color"]),
        _color(item["edge"]),
        _float(item["linewidth"]),
    )


def _wedge(item: dict[str, object]) -> WedgeGeometry:
    item = _object(
        item,
        ("kind", "cx", "cy", "r", "width", "theta1", "theta2", "color", "edge", "linewidth"),
    )
    return WedgeGeometry(
        _float(item["cx"]),
        _float(item["cy"]),
        _float(item["r"]),
        _optional(item["width"], _float),
        _float(item["theta1"]),
        _float(item["theta2"]),
        _color(item["color"]),
        _color(item["edge"]),
        _float(item["linewidth"]),
    )


def _polygon(item: dict[str, object]) -> PolygonGeometry:
    item = _object(item, ("kind", "xy", "color", "edge", "linewidth"))
    return PolygonGeometry(
        _tuple(item["xy"], _pair),
        _color(item["color"]),
        _color(item["edge"]),
        _float(item["linewidth"]),
    )


def _scatter(item: dict[str, object]) -> ScatterGeometry:
    item = _object(
        item,
        ("kind", "offsets", "sizes", "colors", "edges", "linewidths", "array", "colorbar"),
    )
    return ScatterGeometry(
        _tuple(item["offsets"], _pair),
        _tuple(item["sizes"], _float),
        _tuple(item["colors"], _color),
        _tuple(item["edges"], _color),
        _tuple(item["linewidths"], _float),
        _optional(item["array"], lambda value: _tuple(value, _float)),
        _bool(item["colorbar"]),
    )


def _band_arrays(value: object) -> BandArrays:
    item = _object(value, ("x", "y1", "y2"))
    x, y1, y2 = (_tuple(item[name], _float) for name in ("x", "y1", "y2"))
    if not len(x) == len(y1) == len(y2):
        raise _InvalidError
    return BandArrays(x, y1, y2)


def _band(item: dict[str, object]) -> BandGeometry:
    item = _object(item, ("kind", "paths", "color", "edge", "linewidth", "band", "inputs"))
    return BandGeometry(
        _tuple(item["paths"], lambda value: _tuple(value, _pair)),
        _optional(item["color"], _color),
        _optional(item["edge"], _color),
        _float(item["linewidth"]),
        _optional(item["band"], _band_arrays),
        _optional(item["inputs"], _int),
    )


def _text_geometry(item: dict[str, object]) -> TextGeometry:
    return TextGeometry(_str(_object(item, ("kind", "text"))["text"]))


def _no_geometry(item: dict[str, object]) -> NoGeometry:
    _object(item, ("kind",))
    return NoGeometry()


_GEOMETRIES: dict[str, Callable[[dict[str, object]], Geometry]] = {
    "line": _line,
    "rect": _rect,
    "wedge": _wedge,
    "polygon": _polygon,
    "scatter": _scatter,
    "band": _band,
    "text": _text_geometry,
    "none": _no_geometry,
}


def _geometry(value: object) -> Geometry:
    if type(value) is not dict or type(value.get("kind")) is not str:
        raise _InvalidError
    read = _GEOMETRIES.get(value["kind"])
    if read is None:
        raise _InvalidError
    return read(value)


def _artist(value: object) -> Artist:
    item = _object(
        value, ("cls", "origin", "site", "visible", "alpha", "label", "transform", "geometry")
    )
    return Artist(
        _str(item["cls"]),
        _optional(item["origin"], _str),
        _optional(item["site"], _int),
        _bool(item["visible"]),
        _optional(item["alpha"], _float),
        _str(item["label"]),
        _choice(item["transform"], _TRANSFORMS),
        _geometry(item["geometry"]),
    )


def _hist(value: object) -> HistRecord:
    item = _object(
        value, ("values", "bins", "density", "weighted", "cumulative", "histtype", "datasets")
    )
    return HistRecord(
        _tuple(item["values"], _float),
        _tuple(item["bins"], _float),
        _bool(item["density"]),
        _bool(item["weighted"]),
        _bool(item["cumulative"]),
        _str(item["histtype"]),
        _int(item["datasets"]),
    )


def _container(value: object) -> Container:
    item = _object(value, ("cls", "orientation", "label", "members", "hist"))
    return Container(
        _str(item["cls"]),
        _optional(item["orientation"], lambda value: _choice(value, _ORIENTATIONS)),
        _str(item["label"]),
        _tuple(item["members"], _int),
        _optional(item["hist"], _hist),
    )


def _pie(value: object) -> PieRecord:
    item = _object(value, ("values", "normalize", "wedges", "texts"))
    return PieRecord(
        _tuple(item["values"], _float),
        _bool(item["normalize"]),
        _tuple(item["wedges"], _int),
        _tuple(item["texts"], lambda index: _optional(index, _int)),
    )


def _elements(value: object) -> tuple[int | None, str]:
    items = _list(value)
    if len(items) != 2:  # noqa: PLR2004 - (collection, prop)
        raise _InvalidError
    return _optional(items[0], _int), _choice(items[1], _ELEMENT_PROPS)


def _entry(value: object) -> LegendEntry:
    item = _object(value, ("text", "axes", "target", "container", "proxy_color", "elements_of"))
    return LegendEntry(
        _str(item["text"]),
        _optional(item["axes"], _int),
        _optional(item["target"], _int),
        _optional(item["container"], _int),
        _optional(item["proxy_color"], _color),
        _optional(item["elements_of"], _elements),
    )


def _legend(value: object) -> Legend:
    item = _object(value, ("site", "entries"))
    return Legend(_optional(item["site"], _int), _tuple(item["entries"], _entry))


def _category(value: object) -> tuple[str, float]:
    items = _list(value)
    if len(items) != 2:  # noqa: PLR2004 - (key, position)
        raise _InvalidError
    return _str(items[0]), _float(items[1])


def _tick(value: object) -> tuple[float, str]:
    items = _list(value)
    if len(items) != 2:  # noqa: PLR2004 - (position, label)
        raise _InvalidError
    return _float(items[0]), _str(items[1])


def _date(value: object) -> tuple[float, str | None]:
    items = _list(value)
    if len(items) != 2:  # noqa: PLR2004 - (position, ISO text)
        raise _InvalidError
    return _float(items[0]), _optional(items[1], _str)


_AXIS_KEYS = (
    "label",
    "scale",
    "view",
    "inverted",
    "kind",
    "categories",
    "formatter",
    "formatter_module",
    "offset",
    "order",
    "percent_xmax",
    "ticks",
    "minor",
    "minor_formatter_module",
    "dates",
    "calls",
)


def _axis(value: object) -> Axis:
    item = _object(value, _AXIS_KEYS)
    return Axis(
        _optional(item["label"], _text),
        _str(item["scale"]),
        _pair(item["view"]),
        _bool(item["inverted"]),
        _choice(item["kind"], _AXIS_KINDS),
        _optional(item["categories"], lambda value: _tuple(value, _category)),
        _str(item["formatter"]),
        _str(item["formatter_module"]),
        _float(item["offset"]),
        _int(item["order"]),
        _optional(item["percent_xmax"], _float),
        _tuple(item["ticks"], _tick),
        _tuple(item["minor"], _tick),
        _str(item["minor_formatter_module"]),
        _tuple(item["dates"], _date),
        _calls(item["calls"]),
    )


def _index_pair(value: object) -> tuple[int, int]:
    items = _list(value)
    if len(items) != 2:  # noqa: PLR2004 - (axes, artist)
        raise _InvalidError
    return _int(items[0]), _int(items[1])


def _position(value: object) -> tuple[float, float, float, float]:
    items = _list(value)
    if len(items) != 4:  # noqa: PLR2004 - x0 y0 x1 y1
        raise _InvalidError
    x0, y0, x1, y1 = (_float(item) for item in items)
    return x0, y0, x1, y1


_AXES_KEYS = (
    "cls",
    "site",
    "visible",
    "position",
    "colorbar_of",
    "shared_x",
    "shared_y",
    "titles",
    "x",
    "y",
    "calls",
    "artists",
    "containers",
    "pies",
    "legend",
)


def _axes(value: object) -> Axes:
    item = _object(value, _AXES_KEYS)
    return Axes(
        _str(item["cls"]),
        _optional(item["site"], _int),
        _bool(item["visible"]),
        _position(item["position"]),
        _optional(item["colorbar_of"], _index_pair),
        _tuple(item["shared_x"], _int),
        _tuple(item["shared_y"], _int),
        _titles(item["titles"]),
        _axis(item["x"]),
        _axis(item["y"]),
        _calls(item["calls"]),
        _tuple(item["artists"], _artist),
        _tuple(item["containers"], _container),
        _tuple(item["pies"], _pie),
        _optional(item["legend"], _legend),
    )


def _part(value: object) -> Part:
    item = _object(value, ("cls", "origin", "site"))
    return Part(_str(item["cls"]), _optional(item["origin"], _str), _optional(item["site"], _int))


def _figure(value: object) -> Figure:
    item = _object(value, ("site", "titles", "texts", "legends", "others", "axes"))
    return Figure(
        _optional(item["site"], _int),
        _titles(item["titles"]),
        _tuple(item["texts"], _text),
        _tuple(item["legends"], _legend),
        _tuple(item["others"], _part),
        _tuple(item["axes"], _axes),
    )


def _error(value: object) -> ProgramError:
    item = _object(value, ("kind", "name", "line"))
    return ProgramError(
        _choice(item["kind"], _ERROR_KINDS), _str(item["name"]), _optional(item["line"], _int)
    )


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise _InvalidError
    return result


def parse_description(stdout: str) -> Description | None:
    """The one tagged description line of a sandbox reply, decoded; `None` for any other shape."""
    lines = [line for line in stdout.splitlines() if line.startswith(TAG)]
    if len(lines) != 1 or len(lines[0][len(TAG) :].encode("utf-8", "surrogatepass")) > MAX_BYTES:
        return None
    try:
        item = _object(
            # A `NaN`/`Infinity` token parses to a non-finite float, which `_float` refuses.
            json.loads(lines[0][len(TAG) :], object_pairs_hook=_unique),
            ("version", "error", "too_large", "glyphs", "figures"),
        )
        if item["version"] != VERSION:
            return None
        return Description(
            VERSION,
            _optional(item["error"], _error),
            _bool(item["too_large"]),
            _int(item["glyphs"]),
            _tuple(item["figures"], _figure),
        )
    except (ValueError, RecursionError):
        return None
'''

_SOURCES["verifier.figure.reader"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Run a chart program and report what its finished matplotlib figures hold (M19 reader).

Facts only: every decision is the judge's (`.claude/rules/figure.md`). This file runs inside Open
WebUI's Pyodide sandbox, exec'd from base64 by the wrapper (`webui/paste_in/sandbox.py`), and on the
gate host under test. It is the one `verifier` module that imports matplotlib, numpy and pandas;
every import is lazy, so the stdlib judge never loads them.

The program shares this interpreter (ruling 7: non-adversarial). Hooks installed before it runs
record, per artist, the program line that created it (`site`, display only) and the outermost
Axes-module frame (`origin`, family attribution). The judge decides on the final artist properties,
read after the program finished.

One sandbox runtime serves many replies, so the hooks are installed once per interpreter and find
the current run through one holder object stored on `matplotlib.artist`; a holder from another
reader version is unwound before this version installs its own.
"""

import base64
import contextlib
import functools
import importlib
import inspect
import io
import itertools
import json
import logging
import math
import re
import sys
import warnings
from collections.abc import Callable, Iterable
from types import FrameType, TracebackType
from typing import Any, cast

PROGRAM = "<verified-figure>"
TAG = "FIGURE_VERIFICATION_DESCRIPTION:"
VERSION = "figure-description/1"
PNG_PREFIX = "data:image/png;base64,"
MAX_AXES = 24
MAX_CHILDREN = 2_000
MAX_COORDINATES = 20_000
MAX_TEXT = 1_000
MAX_DESCRIPTION_BYTES = 400_000
MAX_PNG_CHARACTERS = 500_000
_HOLDER = "_figure_verification_hooks"
_AXES_MODULES = frozenset(
    {"matplotlib.axes._axes", "matplotlib.axes._base", "matplotlib.stackplot"}
)
_PYPLOT = "matplotlib.pyplot"
# Methods whose program call line the Show checks listing marks (ruling 13): name -> slot.
_AXES_CALLS = {
    "set_xlim": "xlim",
    "set_ylim": "ylim",
    "set_xbound": "xlim",
    "set_ybound": "ylim",
    "set_xscale": "xscale",
    "set_yscale": "yscale",
    "invert_xaxis": "xinvert",
    "invert_yaxis": "yinvert",
    "set_xticks": "xticks",
    "set_yticks": "yticks",
    "set_xticklabels": "xticks",
    "set_yticklabels": "yticks",
    "twinx": "twin",
    "twiny": "twin",
    "secondary_xaxis": "twin",
    "secondary_yaxis": "twin",
    "inset_axes": "inset",
    "legend": "legend",
}
_AXIS_CALLS = {
    "set_ticks": "ticks",
    "set_ticklabels": "ticks",
    "set_major_formatter": "ticks",
    "set_major_locator": "ticks",
    "set_inverted": "invert",
}
# A missing glyph's warning: "Glyph <n> (<c>) missing from current font." (matplotlib 3.8, the
# sandbox) or "Glyph <n> (<c>) missing from font(s) <names>." (3.9, the gate host).
_GLYPH = re.compile(r"\AGlyph \d+ .* missing from (?:current )?font", re.DOTALL)
# Mathtext reports a glyph its font set lacks through matplotlib's LOGGER, never `warnings`:
# "Font 'default' does not have a glyph for '\u5e74' [U+5e74], substituting with a dummy symbol."
_MATHTEXT_LOG = "matplotlib.mathtext"
_MATHTEXT_GLYPH = re.compile(r"\AFont .* does not have a glyph for ", re.DOTALL)
_DATE_MODULES = ("matplotlib.dates", "pandas.")
_MATRIX = 2  # a facecolor array is rows of RGBA


class _TooLargeError(Exception):
    """A cap was reached; the description becomes the minimal `too_large` record."""


class _Run:
    """One program run: the figures it produced and what their description has cost so far."""

    def __init__(self) -> None:
        self.figures: list[dict[str, Any]] = []
        self.pngs: list[str] = []
        self.glyphs = 0
        self.coordinates = 0
        self.too_large = False
        self.error: dict[str, Any] | None = None
        # One clock per run for every recorded call: the latest call among a property's setters
        # is the one that set it, whichever axes or axis carried it, wherever its line sits.
        self.clock = itertools.count()

    def spend(self, count: int) -> None:
        self.coordinates += count
        if self.coordinates > MAX_COORDINATES:
            raise _TooLargeError

    def capture(self) -> None:
        """Draw, describe and render every open figure once, then close them all."""
        plt = importlib.import_module(_PYPLOT)
        for number in plt.get_fignums():
            figure = plt.figure(number)
            try:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    png = io.BytesIO()
                    figure.savefig(png, format="png")  # the one draw the description reads
            except Exception:  # a figure the program left undrawable
                self.error = self.error or {"kind": "draw", "name": "draw", "line": None}
                continue
            self.glyphs += sum(_GLYPH.match(str(item.message)) is not None for item in caught)
            if not self.too_large:
                try:
                    self.figures.append(_figure(figure, self))
                except _TooLargeError:
                    self.too_large = True
            self.pngs.append(base64.b64encode(png.getvalue()).decode("ascii"))
        plt.close("all")


class _GlyphLog(logging.Handler):
    """Counts the mathtext missing-glyph records into the active run."""

    def __init__(self, run: _Run) -> None:
        super().__init__(logging.WARNING)
        self.run = run

    def emit(self, record: logging.LogRecord) -> None:
        self.run.glyphs += _MATHTEXT_GLYPH.match(record.getMessage()) is not None


class _Holder:
    """The interpreter-wide hook state: the active run, and every original this version replaced."""

    def __init__(self) -> None:
        self.version = VERSION
        self.run: _Run | None = None
        self.originals: list[tuple[object, str, object]] = []

    def replace(self, owner: object, name: str, make: Callable[[Any], object]) -> None:
        original = getattr(owner, name)
        self.originals.append((owner, name, original))
        setattr(owner, name, make(original))

    def unwind(self) -> None:
        for owner, name, original in reversed(self.originals):
            setattr(owner, name, original)
        self.originals.clear()


def _program_line(frame: FrameType | None) -> int | None:
    while frame is not None:
        if frame.f_code.co_filename == PROGRAM:
            return frame.f_lineno
        frame = frame.f_back
    return None


def _origin(frame: FrameType | None) -> str | None:
    """The outermost Axes-module frame between the caller and the program, or None."""
    origin = None
    while frame is not None and frame.f_code.co_filename != PROGRAM:
        if frame.f_globals.get("__name__") in _AXES_MODULES:
            origin = frame.f_code.co_qualname
        frame = frame.f_back
    return origin if frame is not None else None


def _direct_line(frame: FrameType | None) -> int | None:
    """The program line when the program itself made this call, directly or through pyplot."""
    while frame is not None and frame.f_globals.get("__name__") == _PYPLOT:
        frame = frame.f_back
    if frame is not None and frame.f_code.co_filename == PROGRAM:
        return frame.f_lineno
    return None


def _number(value: float) -> object:
    """A float as JSON: finite values as numbers, the rest as the strings `nan` `inf` `-inf`."""
    value = float(value)
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return value


def _floats(value: object) -> list[object]:
    np = importlib.import_module("numpy")
    return [_number(v) for v in np.asarray(value, dtype=float).ravel().tolist()]


def _bound(
    original: Callable[..., Any], args: tuple[object, ...], kwargs: dict[str, object]
) -> dict[str, Any]:
    """The hooked call's arguments by parameter name, defaults applied."""
    arguments = inspect.signature(original).bind(*args, **kwargs)
    arguments.apply_defaults()
    return dict(arguments.arguments)


def _called(slot: str) -> Callable[[Any], object]:
    def make(original: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(original)
        def hooked(self: Any, *args: object, **kwargs: object) -> object:
            line = _direct_line(sys._getframe(1))
            if line is not None:
                # The last call decides the property, so the listing marks the last one.
                run = _holder().run
                clock = next(run.clock) if run is not None else 0
                self.__dict__.setdefault("_fv_calls", {})[slot] = [line, clock]
            return original(self, *args, **kwargs)

        return hooked

    return make


def _artist_init(original: Callable[..., None]) -> Callable[..., None]:
    @functools.wraps(original)
    def hooked(self: Any, *args: object, **kwargs: object) -> None:
        original(self, *args, **kwargs)
        frame = sys._getframe(1)
        self._fv_site = _program_line(frame)
        self._fv_origin = _origin(frame)

    return hooked


def _set_text(original: Callable[..., None]) -> Callable[..., None]:
    """A text's site = the program line that last set it (`plt.title` sets an existing artist)."""

    @functools.wraps(original)
    def hooked(self: Any, *args: object, **kwargs: object) -> None:
        original(self, *args, **kwargs)
        line = _program_line(sys._getframe(1))
        if line is not None:
            self._fv_site = line

    return hooked


def _legend_init(original: Callable[..., None]) -> Callable[..., None]:
    @functools.wraps(original)
    def hooked(
        self: Any,
        parent: object,
        handles: Iterable[object],
        labels: Iterable[str],
        *args: object,
        **kwargs: object,
    ) -> None:
        handles, labels = list(handles), list(labels)
        self._fv_entries = (handles, labels)
        self._fv_site = _program_line(sys._getframe(1))
        original(self, parent, handles, labels, *args, **kwargs)

    return hooked


def _argument(call: dict[str, Any], name: str) -> Any:
    """A hooked call's argument, resolved through `data=` the way matplotlib resolves it."""
    value = call[name]
    data = call.get("data")
    return data[value] if isinstance(value, str) and data is not None else value


def _recording(record: Callable[[], None]) -> None:
    """Record a construction fact, never at the program's cost: a failure records nothing, and
    the judge then finds no record and refuses the mark."""
    with contextlib.suppress(Exception):
        record()


def _hist(original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def hooked(*args: object, **kwargs: object) -> Any:
        result = original(*args, **kwargs)

        def record() -> None:
            call = _bound(original, args, kwargs)
            cbook = importlib.import_module("matplotlib.cbook")
            datasets = cbook._reshape_2D(_argument(call, "x"), "x")
            facts = {
                "values": [value for data in datasets for value in _floats(data)],
                "bins": _floats(result[1]),
                "density": bool(call["density"]),
                "weighted": call["weights"] is not None,
                "cumulative": bool(call["cumulative"]),
                "histtype": str(call["histtype"]),
                "datasets": len(datasets),
            }
            for container in result[2] if isinstance(result[2], list) else [result[2]]:
                with contextlib.suppress(AttributeError):  # a step outline is a bare Polygon list
                    container._fv_hist = facts

        _recording(record)
        return result

    return hooked


def _pie(original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def hooked(*args: object, **kwargs: object) -> Any:
        result = original(*args, **kwargs)

        def record() -> None:
            call = _bound(original, args, kwargs)
            facts = {
                "values": _floats(_argument(call, "x")),
                "normalize": bool(call["normalize"]),
                "wedges": list(result[0]),
                "texts": list(result[1]),
            }
            call["self"].__dict__.setdefault("_fv_pies", []).append(facts)

        _recording(record)
        return result

    return hooked


def _fill_between(original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def hooked(*args: object, **kwargs: object) -> Any:
        result = original(*args, **kwargs)

        def record() -> None:
            call = _bound(original, args, kwargs)
            result._fv_plain = call["where"] is None and call["step"] is None
            # How many points the call received: a non-finite one leaves the polygon unseen.
            result._fv_inputs = len(_argument(call, "x"))

        _recording(record)
        return result

    return hooked


def _legend_elements(original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def hooked(self: object, *args: object, **kwargs: object) -> Any:
        handles, labels = original(self, *args, **kwargs)
        prop = _bound(original, (self, *args), kwargs)["prop"]
        for handle in handles:
            handle._fv_elements = (self, str(prop))
        return handles, labels

    return hooked


def _show(holder: _Holder) -> Callable[[Any], object]:
    def make(original: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(original)
        def hooked(*args: object, **kwargs: object) -> Any:
            if holder.run is None:
                return original(*args, **kwargs)
            holder.run.capture()
            return None

        return hooked

    return make


def _install(holder: _Holder) -> None:
    def module(name: str) -> Any:
        return importlib.import_module(f"matplotlib.{name}")

    holder.replace(module("artist").Artist, "__init__", _artist_init)
    for name, slot in _AXES_CALLS.items():
        holder.replace(module("axes").Axes, name, _called(slot))
    for name, slot in _AXIS_CALLS.items():
        holder.replace(module("axis").Axis, name, _called(slot))
    holder.replace(module("text").Text, "set_text", _set_text)
    holder.replace(module("legend").Legend, "__init__", _legend_init)
    holder.replace(module("axes").Axes, "hist", _hist)
    holder.replace(module("axes").Axes, "pie", _pie)
    holder.replace(module("axes").Axes, "fill_between", _fill_between)
    holder.replace(module("collections").PathCollection, "legend_elements", _legend_elements)
    holder.replace(module("pyplot"), "show", _show(holder))


def _holder() -> _Holder:
    martist = importlib.import_module("matplotlib.artist")
    found = getattr(martist, _HOLDER, None)
    if getattr(found, "version", None) == VERSION:
        # The same reader exec'd again in this runtime: its hooks call back through this holder.
        return cast("_Holder", found)
    if found is not None:
        found.unwind()
    holder = _Holder()
    _install(holder)
    setattr(martist, _HOLDER, holder)
    return holder


def _rgba(color: object) -> list[float]:
    mcolors = importlib.import_module("matplotlib.colors")
    return [float(c) for c in mcolors.to_rgba(color)]


def _cut(text: str) -> str:
    """Text within the cap; longer text makes the whole description the `too_large` record."""
    if len(text) > MAX_TEXT:
        raise _TooLargeError
    return text


def _text(artist: Any) -> dict[str, Any] | None:
    if artist is None or not artist.get_visible() or artist.get_text() == "":
        return None
    return {"text": _cut(artist.get_text()), "site": getattr(artist, "_fv_site", None)}


def _transform(artist: Any, axes: Any) -> str:
    """Which coordinate system carries the artist's data: the transform its data passes through."""
    kind = type(artist).__name__
    if kind == "PathCollection":
        transform = artist.get_offset_transform()
    elif hasattr(artist, "get_data_transform") and hasattr(artist, "get_path"):
        transform = artist.get_data_transform()
    else:
        transform = artist.get_transform()
    for name, reference in (
        ("data", axes.transData),
        ("axes", axes.transAxes),
        ("xaxis", axes.get_xaxis_transform()),
        ("yaxis", axes.get_yaxis_transform()),
        ("figure", axes.figure.transFigure),
    ):
        if transform == reference:
            return name
    return "other"


def _line(artist: Any, run: _Run) -> dict[str, Any]:
    xy = artist.get_xydata()
    run.spend(len(xy))
    return {
        "kind": "line",
        "x": [_number(x) for x, _ in xy],
        "y": [_number(y) for _, y in xy],
        "color": _rgba(artist.get_color()),
        "marker": str(artist.get_marker()),
        "linestyle": str(artist.get_linestyle()),
        "drawstyle": str(artist.get_drawstyle()),
        "linewidth": _number(artist.get_linewidth()),
        "markersize": _number(artist.get_markersize()),
        "marker_face": _rgba(artist.get_markerfacecolor()),
        "marker_edge": _rgba(artist.get_markeredgecolor()),
    }


def _ink(patch: Any) -> dict[str, Any]:
    """A patch's face and edge: what decides whether it shows any ink."""
    return {
        "color": _rgba(patch.get_facecolor()),
        "edge": _rgba(patch.get_edgecolor()),
        "linewidth": _number(patch.get_linewidth()),
    }


def _rect(artist: Any, run: _Run) -> dict[str, Any]:
    run.spend(1)
    return {
        "kind": "rect",
        "x": _number(artist.get_x()),
        "y": _number(artist.get_y()),
        "width": _number(artist.get_width()),
        "height": _number(artist.get_height()),
        "angle": _number(artist.get_angle()),
        **_ink(artist),
    }


def _wedge(artist: Any, run: _Run) -> dict[str, Any]:
    run.spend(1)
    return {
        "kind": "wedge",
        "cx": _number(artist.center[0]),
        "cy": _number(artist.center[1]),
        "r": _number(artist.r),
        "width": None if artist.width is None else _number(artist.width),
        "theta1": _number(artist.theta1),
        "theta2": _number(artist.theta2),
        **_ink(artist),
    }


def _polygon(artist: Any, run: _Run) -> dict[str, Any]:
    xy = artist.get_xy()
    run.spend(len(xy))
    return {
        "kind": "polygon",
        "xy": [[_number(x), _number(y)] for x, y in xy],
        **_ink(artist),
    }


def _scatter(artist: Any, run: _Run) -> dict[str, Any]:
    offsets = artist.get_offsets()
    run.spend(len(offsets))
    array = artist.get_array()
    return {
        "kind": "scatter",
        "offsets": [[_number(x), _number(y)] for x, y in offsets],
        "sizes": [_number(s) for s in artist.get_sizes()],
        "colors": [_rgba(c) for c in artist.get_facecolors()],
        "edges": [_rgba(c) for c in artist.get_edgecolors()],
        "linewidths": [_number(w) for w in artist.get_linewidths()],
        "array": None if array is None else _floats(array),
        "colorbar": getattr(artist, "colorbar", None) is not None,
    }


def _band_arrays(path: list[list[float]]) -> dict[str, Any] | None:
    """`fill_between`'s polygon read back into its arrays, or None for any other shape.

    One plain call draws (x0, y2_0), every (x_i, y1_i), (x_n, y2_n), every (x_i, y2_i) backwards,
    then (x0, y2_0) again: the vertices hold the arrays exactly, units already converted.
    """
    count = (len(path) - 3) // 2
    if count < 1 or len(path) != 2 * count + 3:
        return None
    forward = path[1 : count + 1]
    backward = path[count + 2 : 2 * count + 2][::-1]
    if (
        path[0] != path[-1]
        or path[0] != backward[0]
        or path[count + 1] != backward[-1]
        or [x for x, _ in forward] != [x for x, _ in backward]
    ):
        return None
    return {
        "x": [_number(x) for x, _ in forward],
        "y1": [_number(y) for _, y in forward],
        "y2": [_number(y) for _, y in backward],
    }


def _band(artist: Any, run: _Run) -> dict[str, Any]:
    paths = [path.vertices.tolist() for path in artist.get_paths()]
    plain = getattr(artist, "_fv_plain", False) is True and len(paths) == 1
    band = _band_arrays(paths[0]) if plain else None
    run.spend(sum(len(path) for path in paths) + (0 if band is None else 3 * len(band["x"])))
    faces, edges, widths = (
        artist.get_facecolors(),
        artist.get_edgecolors(),
        artist.get_linewidths(),
    )
    inputs = getattr(artist, "_fv_inputs", None)
    return {
        "kind": "band",
        "paths": [[[_number(x), _number(y)] for x, y in path] for path in paths],
        "color": _rgba(faces[0]) if len(faces) else None,
        "edge": _rgba(edges[0]) if len(edges) else None,
        "linewidth": _number(widths[0]) if len(widths) else 0.0,
        "band": band,
        "inputs": inputs if isinstance(inputs, int) else None,
    }


def _text_geometry(artist: Any, _run: _Run) -> dict[str, Any]:
    return {"kind": "text", "text": _cut(artist.get_text())}


# Exact class name -> what the reader measures; every other class is described by class alone.
_GEOMETRY: dict[str, Callable[[Any, _Run], dict[str, Any]]] = {
    "Line2D": _line,
    "Rectangle": _rect,
    "Wedge": _wedge,
    "Polygon": _polygon,
    "PathCollection": _scatter,
    "PolyCollection": _band,
    "Text": _text_geometry,
    "Annotation": _text_geometry,
}


def _geometry(artist: Any, run: _Run) -> dict[str, Any]:
    measure = _GEOMETRY.get(type(artist).__name__)
    return {"kind": "none"} if measure is None else measure(artist, run)


def _structural(axes: Any) -> set[int]:
    slots = [axes.patch, axes.xaxis, axes.yaxis, axes.title, axes._left_title, axes._right_title]
    slots += list(axes.spines.values())
    if axes.legend_ is not None:
        slots.append(axes.legend_)
    return {id(slot) for slot in slots}


def _children(axes: Any) -> list[Any]:
    structural = _structural(axes)
    return [child for child in axes.get_children() if id(child) not in structural]


def _artist(artist: Any, axes: Any, run: _Run) -> dict[str, Any]:
    alpha = artist.get_alpha()
    return {
        "cls": type(artist).__name__,
        "origin": getattr(artist, "_fv_origin", None),
        "site": getattr(artist, "_fv_site", None),
        "visible": bool(artist.get_visible()),
        "alpha": None if alpha is None else _number(alpha),
        "label": _cut(str(artist.get_label())),
        "transform": _transform(artist, axes),
        "geometry": _geometry(artist, run),
    }


def _axis_kind(axis: Any) -> str:
    converter = getattr(axis, "converter", None)
    if converter is None:
        return "numeric"
    name = type(converter).__name__
    if name == "StrCategoryConverter":
        return "category"
    if type(converter).__module__.startswith(_DATE_MODULES) and (
        "Date" in name or "Period" in name
    ):
        return "date"
    return "unknown"


def _date(axes: Any, axis: Any, position: float) -> str | None:
    """The calendar reading of one position on a date axis, by the converter that drew it.

    `position` is finite: `_positions` passes floats alone, and non-finite values travel as text.
    """
    if type(axis.converter).__name__ == "PeriodConverter":
        freq = getattr(axes, "freq", None)
        if freq is None or not position.is_integer():
            return None
        pandas = importlib.import_module("pandas")
        return str(pandas.Period(ordinal=int(position), freq=freq).start_time.isoformat())
    mdates = importlib.import_module("matplotlib.dates")
    try:
        return str(mdates.num2date(position).replace(tzinfo=None).isoformat())
    except (ValueError, OverflowError):
        return None


def _formatter(formatter: Any) -> tuple[str, str]:
    """The tick formatter's class, and the module whose code writes the label text."""
    function = getattr(formatter, "func", None)
    while isinstance(function, functools.partial):
        function = function.func
    owner = type(formatter) if function is None else function
    return type(formatter).__name__, str(owner.__module__)


def _axis(axes: Any, axis: Any, positions: Iterable[object]) -> dict[str, Any]:
    low, high = (float(value) for value in axis.get_view_interval())
    lo, hi = min(low, high), max(low, high)
    formatter = axis.get_major_formatter()
    name, module = _formatter(formatter)
    kind = _axis_kind(axis)
    ticks: list[list[object]] = []
    minor: list[list[object]] = []
    if axes.axison and axis.get_visible():
        for tick in axis.get_major_ticks():
            position = float(tick.get_loc())
            shown = [label for label in (tick.label1, tick.label2) if label.get_visible()]
            if lo <= position <= hi and shown:
                ticks.append([_number(position), _cut(shown[0].get_text())])
        # A minor label is a label too; the default minor formatter writes none. Its formatter is
        # not the major one, so the judge reads it under no formatter's trust.
        for tick in axis.get_minor_ticks():
            position = float(tick.get_loc())
            shown = [
                label
                for label in (tick.label1, tick.label2)
                if label.get_visible() and label.get_text()
            ]
            if lo <= position <= hi and shown:
                minor.append([_number(position), _cut(shown[0].get_text())])
    mapping = axis.units._mapping if kind == "category" else None
    dates: list[list[object]] = []
    if kind == "date":
        wanted = {p for p in positions if isinstance(p, float)}
        wanted |= {t[0] for t in (*ticks, *minor) if isinstance(t[0], float)}
        dates = [[p, _date(axes, axis, p)] for p in sorted(wanted)]
    scalar = name == "ScalarFormatter"
    return {
        "label": _text(axis.label),
        "scale": str(axis.get_scale()),
        "view": [_number(low), _number(high)],
        "inverted": bool(axis.get_inverted()),
        "kind": kind,
        "categories": None
        if mapping is None
        else [[_cut(str(key)), _number(value)] for key, value in mapping.items()],
        "formatter": name,
        "formatter_module": module,
        "offset": _number(formatter.offset if scalar else 0.0),
        "order": int(formatter.orderOfMagnitude if scalar else 0),
        "percent_xmax": _number(formatter.xmax) if name == "PercentFormatter" else None,
        "ticks": ticks,
        "minor": minor,
        "minor_formatter_module": _formatter(axis.get_minor_formatter())[1],
        "dates": dates,
        "calls": dict(sorted(getattr(axis, "_fv_calls", {}).items())),
    }


def _positions(artists: list[dict[str, Any]], dimension: int) -> list[object]:
    """Every data coordinate an axis carries: what a date axis must translate."""
    found: list[object] = []
    for artist in artists:
        geometry = artist["geometry"]
        kind = geometry["kind"]
        if kind == "line":
            found += geometry["xy"[dimension]]
        elif kind == "scatter":
            found += [pair[dimension] for pair in geometry["offsets"]]
        elif kind == "rect":
            start = geometry["xy"[dimension]]
            extent = geometry[("width", "height")[dimension]]
            if isinstance(start, float) and isinstance(extent, float):
                found += [start, start + extent / 2, start + extent]
        elif kind == "polygon":
            found += [pair[dimension] for pair in geometry["xy"]]
        elif kind == "band":
            found += [pair[dimension] for path in geometry["paths"] for pair in path]
    return found


def _handle_color(handle: Any) -> list[float] | None:
    """A legend handle's colour, read the way its family draws: patches, lines, collections."""
    if hasattr(handle, "patches"):  # a container handed to the legend whole
        handle = handle.patches[0] if handle.patches else None
    if handle is None:
        return None
    if hasattr(handle, "get_facecolor"):
        value = handle.get_facecolor()
        if getattr(value, "ndim", 1) == _MATRIX:
            return _rgba(value[0]) if len(value) else None
        return _rgba(value)
    return _rgba(handle.get_color()) if hasattr(handle, "get_color") else None


def _find(figure: Any, handle: object) -> tuple[int, int | None, int | None] | None:
    """(axes, artist, container) of the drawn object `handle` is, anywhere in the figure."""
    for number, axes in enumerate(figure.axes):
        artist = next((i for i, child in enumerate(_children(axes)) if child is handle), None)
        container = next((i for i, c in enumerate(axes.containers) if c is handle), None)
        if artist is not None or container is not None:
            return number, artist, container
    return None


def _legend(legend: Any, figure: Any) -> dict[str, Any]:
    """Each entry: its displayed text, and the drawn artist or container it names (anywhere in
    the figure), else its own colour; a `legend_elements` key names its collection."""
    handles, _labels = getattr(legend, "_fv_entries", ([], []))
    shown = iter(legend.texts)  # one text per handle the legend could draw, as finally displayed
    entries = []
    for handle, drawn in zip(handles, legend.legend_handles, strict=False):
        if drawn is None:
            continue
        label = next(shown).get_text()
        found = _find(figure, handle)
        elements = getattr(handle, "_fv_elements", None)
        keyed = None if elements is None else _find(figure, elements[0])
        axes = found[0] if found is not None else (keyed[0] if keyed is not None else None)
        entries.append(
            {
                "text": _cut(str(label)),
                "axes": axes,
                "target": None if found is None else found[1],
                "container": None if found is None else found[2],
                "proxy_color": _handle_color(handle) if found is None else None,
                "elements_of": None
                if elements is None
                else [None if keyed is None else keyed[1], elements[1]],
            }
        )
    return {"site": getattr(legend, "_fv_site", None), "entries": entries}


def _member_indices(members: Iterable[object], children: list[Any]) -> list[int]:
    return [index for member in members for index, child in enumerate(children) if child is member]


def _axes(axes: Any, figure: Any, run: _Run) -> dict[str, Any]:
    children = _children(axes)
    artists = [_artist(child, axes, run) for child in children]
    containers = list(axes.containers)
    described = []
    for container in containers:
        hist = getattr(container, "_fv_hist", None)
        if hist is not None:
            run.spend(len(hist["values"]) + len(hist["bins"]))
        described.append(
            {
                "cls": type(container).__name__,
                "orientation": getattr(container, "orientation", None),
                "label": _cut(str(container.get_label())),
                "members": _member_indices(getattr(container, "patches", ()), children),
                "hist": hist,
            }
        )
    pies = []
    for record in getattr(axes, "_fv_pies", ()):
        run.spend(len(record["values"]))
        pies.append(
            {
                **record,
                "wedges": _member_indices(record["wedges"], children),
                # A label Text the program removed reads as None: that wedge shows no label.
                "texts": [
                    next((index for index, child in enumerate(children) if child is text), None)
                    for text in record["texts"]
                ],
            }
        )
    colorbar = getattr(axes, "_colorbar", None)
    position = axes.get_position()
    siblings = figure.axes
    return {
        "cls": type(axes).__name__,
        "site": getattr(axes, "_fv_site", None),
        "visible": bool(axes.get_visible()),
        "position": [_number(v) for v in (position.x0, position.y0, position.x1, position.y1)],
        "colorbar_of": None if colorbar is None else _locate(siblings, colorbar.mappable),
        "shared_x": _shared(siblings, axes, axes.get_shared_x_axes()),
        "shared_y": _shared(siblings, axes, axes.get_shared_y_axes()),
        "titles": [_text(t) for t in (axes._left_title, axes.title, axes._right_title)],
        "x": _axis(axes, axes.xaxis, _positions(artists, 0)),
        "y": _axis(axes, axes.yaxis, _positions(artists, 1)),
        "calls": dict(sorted(getattr(axes, "_fv_calls", {}).items())),
        "artists": artists,
        "containers": described,
        "pies": pies,
        "legend": None if axes.legend_ is None else _legend(axes.legend_, figure),
    }


def _locate(siblings: list[Any], target: object) -> list[int] | None:
    for index, axes in enumerate(siblings):
        for position, child in enumerate(_children(axes)):
            if child is target:
                return [index, position]
    return None


def _shared(siblings: list[Any], axes: Any, grouper: Any) -> list[int]:
    return [
        i for i, other in enumerate(siblings) if other is not axes and grouper.joined(axes, other)
    ]


def _figure(figure: Any, run: _Run) -> dict[str, Any]:
    if len(figure.axes) > MAX_AXES or sum(len(_children(ax)) for ax in figure.axes) > MAX_CHILDREN:
        raise _TooLargeError
    axes = [_axes(ax, figure, run) for ax in figure.axes]
    supers = [figure._suptitle, figure._supxlabel, figure._supylabel]
    known = {id(figure.patch), *(id(a) for a in figure.axes), *(id(s) for s in supers)}
    known |= {id(legend) for legend in figure.legends} | {id(text) for text in figure.texts}
    return {
        "site": getattr(figure, "_fv_site", None),
        "titles": [_text(s) for s in supers],
        "texts": [
            t
            for t in (_text(text) for text in figure.texts if all(text is not s for s in supers))
            if t is not None
        ],
        "legends": [_legend(legend, figure) for legend in figure.legends],
        "others": [
            {
                "cls": type(child).__name__,
                "origin": getattr(child, "_fv_origin", None),
                "site": getattr(child, "_fv_site", None),
            }
            for child in figure.get_children()
            if id(child) not in known
        ],
        "axes": axes,
    }


def _error(exc: BaseException, kind: str) -> dict[str, Any]:
    line = getattr(exc, "lineno", None) if kind == "syntax" else None
    trace: TracebackType | None = exc.__traceback__
    while trace is not None:
        if trace.tb_frame.f_code.co_filename == PROGRAM:
            line = trace.tb_lineno
        trace = trace.tb_next
    return {"kind": kind, "name": type(exc).__name__, "line": line}


def _prepare(font: str | None) -> None:
    """Start from matplotlib's defaults: one runtime serves many replies."""
    mpl = importlib.import_module("matplotlib")
    mpl.rcdefaults()
    mpl.use("Agg")
    plt = importlib.import_module(_PYPLOT)
    plt.close("all")
    if font is not None:
        fonts = importlib.import_module("matplotlib.font_manager")
        fonts.fontManager.addfont(font)
        plt.rcParams["font.family"] = ["DejaVu Sans", fonts.FontProperties(fname=font).get_name()]


def run(source: str, font: str | None = None) -> str:
    """Run `source` as the chart program; return the description line, then one PNG line."""
    _prepare(font)
    holder = _holder()
    current = _Run()
    holder.run = current
    sink = io.StringIO()
    glyph_log = _GlyphLog(current)
    logging.getLogger(_MATHTEXT_LOG).addHandler(glyph_log)
    try:
        with (
            warnings.catch_warnings(record=True) as caught,
            contextlib.redirect_stdout(sink),
            contextlib.redirect_stderr(sink),
        ):
            warnings.simplefilter("always")
            try:
                code = compile(source, PROGRAM, "exec")
            except (SyntaxError, ValueError) as exc:  # ValueError: text UTF-8 cannot encode
                current.error = _error(exc, "syntax")
            else:
                try:
                    # Running the program IS the job (ruling 7: a non-adversarial program).
                    exec(code, {"__name__": "__main__"})  # noqa: S102
                except BaseException as exc:  # every outcome of the program is a fact to report
                    current.error = _error(exc, "exception")
            current.capture()
            current.glyphs += sum(_GLYPH.match(str(item.message)) is not None for item in caught)
    finally:
        holder.run = None
        logging.getLogger(_MATHTEXT_LOG).removeHandler(glyph_log)
    return _render(current)


def _render(current: _Run) -> str:
    description = {
        "version": VERSION,
        "error": current.error,
        "too_large": current.too_large,
        "glyphs": current.glyphs,
        "figures": [] if current.too_large else current.figures,
    }
    text = json.dumps(description, separators=(",", ":"), allow_nan=False)
    png = None if current.too_large or len(current.pngs) != 1 else current.pngs[0]
    if len(text.encode("utf-8")) > MAX_DESCRIPTION_BYTES or (
        png is not None and len(PNG_PREFIX) + len(png) > MAX_PNG_CHARACTERS
    ):
        description["too_large"] = True
        description["figures"] = []
        text = json.dumps(description, separators=(",", ":"))
        png = None
    return f"{TAG}{text}\n" + ("" if png is None else f"{PNG_PREFIX}{png}\n")
'''

_SOURCES["verifier.figure.reasons"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The closed reasons a figure is blocked for, and the one way a stage blocks (M19).

`.claude/rules/figure.md` § Checks maps each reason to its Show checks row. A stage blocks by
raising `Blocked`, carrying the program line the row listing marks; the judge returns it.
"""

from dataclasses import dataclass
from typing import Literal, NoReturn

FigureReason = Literal[
    # run: the program and the sandbox reply
    "program_syntax_error",
    "program_error",
    "module_not_available",
    "figure_too_large",
    # figure
    "no_figure",
    "multiple_figures",
    "glyph_missing",
    # parts: the closed artist set
    "raster_image",
    "axes_not_judged",
    "axes_twin",
    "axes_overlap",
    "artist_not_judged",
    "no_data",
    # axes
    "mark_not_in_data",
    "scale_not_linear",
    "axis_inverted",
    "zero_not_in_limits",
    "tick_label_mismatch",
    "point_clipped",
    # marks
    "mark_hidden",
    "value_not_finite",
    "bar_not_from_zero",
    "bars_overlap",
    "category_not_unique",
    "x_not_ordered",
    "hist_counts",
    "pie_not_whole",
    "area_not_from_zero",
    "marker_size_varies",
    "marker_color_varies",
    "legend_mismatch",
    # values
    "csv_too_large",
    "csv_not_parsable",
    "work_budget_exceeded",
    "value_not_found",
    "label_not_in_request",
    # columns
    "column_not_requested",
    "column_not_named",
    "label_not_consistent",
]


@dataclass(frozen=True, slots=True)
class Blocked:
    """The figure is blocked for `reason`; `site` = the program line that drew or caused it."""

    reason: FigureReason
    site: int | None = None


class BlockedError(Exception):
    """Carries a `Blocked` verdict out of the stage that decided it."""

    def __init__(self, blocked: Blocked) -> None:
        super().__init__(blocked.reason)
        self.blocked = blocked


def block(reason: FigureReason, site: int | None = None) -> NoReturn:
    raise BlockedError(Blocked(reason, site))
'''

_SOURCES["verifier.figure.request"] = r'''
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
'''

_SOURCES["verifier.pysrc"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The pandas-equal CSV profile + group reductions the figure judge reads the user's data with.

Stdlib-only: the paste-in filter inlines this package, so a dependency here becomes a dependency of
an Open WebUI instance with no outside network access.
"""
'''

_SOURCES["verifier.pysrc.budget"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Consumer-neutral run-local logical-work admission.

A meter admits each consumer-defined non-negative charge atomically before the guarded work;
refusal preserves the prior count and reports the exact limit, consumption, and requested cost.

Lives in the portable core because the paste-in needs a meter: the CSV reader, the aggregate engine
and the figure judge share this one (two hand-maintained meters = the fork the single-source ruling
bans).
"""

from dataclasses import dataclass

__all__ = ["WorkBudget", "WorkBudgetExceededError"]


class WorkBudgetExceededError(Exception):
    """One atomic charge that would cross a cumulative work ceiling."""

    def __init__(self, *, limit: int, consumed: int, required: int) -> None:
        message = f"work limit {limit}: {consumed} consumed + {required} required"
        super().__init__(message)
        self.limit = limit
        self.consumed = consumed
        self.required = required


@dataclass(slots=True)
class WorkBudget:
    """Mutable cumulative meter shared across every operation in one consumer run."""

    limit: int
    consumed: int = 0

    def __post_init__(self) -> None:
        if type(self.limit) is not int or self.limit < 0:
            msg = f"work limit must be a non-negative integer, got {self.limit!r}"
            raise ValueError(msg)
        if type(self.consumed) is not int or not 0 <= self.consumed <= self.limit:
            msg = (
                "work consumption must be an integer between zero and the limit, "
                f"got {self.consumed!r}"
            )
            raise ValueError(msg)

    def charge(self, required: int) -> None:
        """Admit ``required`` atomically, or leave consumption unchanged and refuse."""
        if type(required) is not int or required < 0:
            msg = f"required work must be a non-negative integer, got {required!r}"
            raise ValueError(msg)
        if required > self.limit - self.consumed:
            raise WorkBudgetExceededError(
                limit=self.limit,
                consumed=self.consumed,
                required=required,
            )
        self.consumed += required
'''

_SOURCES["verifier.pysrc.errors"] = r'''
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
'''

_SOURCES["verifier.pysrc.limits"] = r'''
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
'''

_SOURCES["verifier.pysrc.table"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""One cell as the judge reads it from the user's CSV."""

__all__ = ["CellValue"]

# A text key is a string; every other cell is float64. There is no null and no NaN: the CSV
# profile refuses every NA spelling before a cell reaches here.
type CellValue = float | str
'''

_SOURCES["webui"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""webui — the Open WebUI integration harness.

Provisions and drives a headless Open WebUI over its REST API: it registers the verifier as an
OpenAPI tool server, bootstraps an admin, and launches OWUI under a canonical hermetic env so the
weak local model proposes chart specs the verifier certifies before render. NOT part of the
verifier trust claim: an out-of-tree harness like model_backend and bench -- type-checked under
mypy --strict but excluded from coverage and the wheel, importing only gate-venv deps (the
.venv-webui open-webui binary is exec'd, never imported).

settings.py owns the frozen config every other module imports; the REST client, bootstrap, model
stub, and CLI keep their wire/process boundaries separate.
"""
'''

_SOURCES["webui.paste_in"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The production paste-in: the source an admin pastes into an Open WebUI instance.

Every module here is written for TWO environments at once. In this repo it is ordinary first-party
code the gate lints, types and tests; in the target instance it arrives as a generated file per
paste target (`tools/generate_paste_in.py`), with `verifier.pysrc` embedded verbatim by the same
generator. A hand fork of either side is banned (`.agent/spec.md` § Decisions) -- the generator is
the single source, and `--check` is what keeps the committed artifact equal to it.

Dependency envelope: the stdlib, plus `open_webui`, which the image already carries. `bundle.py`'s
import scan decides that over the generated bytes rather than over intent, so a dependency added
here fails generation instead of failing a paste.
"""
'''

_SOURCES["webui.paste_in.owui_files"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The ONLY module that imports `open_webui`: uploaded bytes + the bundled CJK font, in-process.

The truth source for every recomputed number is the user's own upload (`.claude/rules/pysrc.md`,
comparison class II), so the bytes come from Open WebUI's own store and not from the chat metadata,
which is client-supplied end to end -- the item's nested `path` included. Only the top-level `id`
is trusted, and it is re-resolved against the requesting user:
`Files.get_file_by_id_and_user_id` returns `None` for a file that is missing, foreign or
unreadable, so a file the caller does not own is never read and no second path exists that could
read it.

The `open_webui` imports are function-local, and that is load-bearing rather than stylistic: this
module must import in the gate environment, which has no `open_webui` and cannot have one, while
binding the real API inside the image. A test injects fakes into `sys.modules` and drives the same
call chain.
"""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

# Where Open WebUI's Pyodide worker writes each attached file before it runs the program. An
# admitted `read_csv` literal must name exactly this, and the core compares byte-for-byte.
UPLOAD_DIR = "/mnt/uploads/"
# Open WebUI ships this font for its own chat-PDF export; the sandbox's matplotlib has no CJK glyph.
CJK_FONT_NAME = "NotoSansJP-Regular.ttf"


@dataclass(frozen=True, slots=True)
class UploadedFile:
    """One attachment, named as the sandbox will name it, carrying the store's exact bytes."""

    file_id: str
    path: str
    content: bytes


def attachment_ids(metadata: Mapping[str, object] | None) -> list[str]:
    """Top-level ids from `__metadata__["files"]`, in chat order. Every other key is untrusted."""
    if metadata is None:
        return []
    items = metadata.get("files")
    if not isinstance(items, Sequence) or isinstance(items, str | bytes):
        return []
    ids: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        file_id = item.get("id")
        if isinstance(file_id, str) and file_id:
            ids.append(file_id)
    return ids


async def owned_files(file_ids: Sequence[str], user_id: str) -> tuple[UploadedFile, ...]:
    """Fetch only owned, readable ids through Open WebUI's store, preserving chat order."""
    from open_webui.models.files import Files  # noqa: PLC0415 - see the module docstring
    from open_webui.storage.provider import Storage  # noqa: PLC0415 - see the module docstring

    found: list[UploadedFile] = []
    for file_id in file_ids:
        record = await Files.get_file_by_id_and_user_id(file_id, user_id)
        if record is None:
            continue
        try:
            local_path = await asyncio.to_thread(Storage.get_file, record.path)
            content = await asyncio.to_thread(Path(local_path).read_bytes)
        except Exception:
            logging.getLogger(__name__).debug("Unreadable owned file omitted")
            continue
        found.append(
            UploadedFile(file_id=file_id, path=UPLOAD_DIR + record.filename, content=content)
        )
    return tuple(found)


async def uploaded_files(
    metadata: Mapping[str, object] | None,
    user_id: str,
) -> tuple[UploadedFile, ...]:
    """Resolve chat attachment ids through the same ownership path the filter uses."""
    return await owned_files(attachment_ids(metadata), user_id)


async def cjk_font() -> bytes | None:
    """Open WebUI's bundled Japanese font from its configured fonts directory, else `None`.

    A missing font only withholds Japanese text from the figure, which then fails as before, so
    every fault here degrades to `None` instead of costing the verdict.
    """
    try:
        from open_webui.env import FONTS_DIR  # noqa: PLC0415 - see the module docstring

        return await asyncio.to_thread(Path(FONTS_DIR, CJK_FONT_NAME).read_bytes)
    except Exception:
        return None
'''

_SOURCES["webui.paste_in.templates"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The inlet's prompt templates: the user's task, the attached file, the chart rules (ruling 8).

Model guidance may state every rule the verifier checks; it never moves the boundary, because the
outlet judges the finished figure whatever the model wrote. Nothing from this repository reaches
the production system prompt (user: the deployer cannot change it), so production's templates end
in the `draw_figure` transport paragraph; the demo's end in the bare-source format paragraph its
adapter turns into that call (Q40).
"""

from dataclasses import dataclass
from typing import Final

# The task, then the file the program reads (its sandbox path and header).
_FILE: Final = (
    "{task}\n\nUse the CSV file at /mnt/uploads/{dataset}. Its columns are {columns}.\n"
    "Read the CSV file with pandas. Draw the figure with matplotlib.\n\n"
    "When the task asks for one value per time or category, group by its named field with pandas"
    " and calculate one plotted value per group. For totals, calculate a sum; for averages, a"
    " mean; for highest or lowest values, a maximum or minimum. Draw the grouped values rather"
    " than the original rows.\n\n"
)
_NO_FILE: Final = "{task}\n\nDraw the figure with matplotlib.\n\n"
RULES: Final = (
    "Draw one figure. Plot only values from the CSV file or numbers written in the task, as they"
    " are or as one total, mean, minimum, maximum or row count per group. Keep the chart honest:"
    " bars and filled areas start at zero, axes stay linear and not inverted, every value stays"
    " inside the axis limits, each panel has one set of axes, a legend names every series when"
    " there are two or more, and varying marker sizes or colors have a size legend or a color"
    " bar.\n"
)
TRANSPORT: Final = (
    "\nWrite one complete Python program that draws the chart. Call the draw_figure tool once, with"
    " the whole program as the program argument. Do not put the program in your reply text.\n"
)
FORMAT: Final = "\nReturn one complete Python program as bare source text, no Markdown fences.\n"


@dataclass(frozen=True, slots=True)
class Templates:
    """One artifact's inlet templates: with an attached file, and without one."""

    file: str
    no_file: str


PRODUCTION_TEMPLATES: Final = Templates(_FILE + RULES + TRANSPORT, _NO_FILE + RULES + TRANSPORT)
DEMO_TEMPLATES: Final = Templates(_FILE + RULES + FORMAT, _NO_FILE + RULES + FORMAT)
'''

_SOURCES["verifier.figure.ticks"] = r'''
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
'''

_SOURCES["verifier.pysrc.aggregate"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Grouped reduction, reproducing what the EXECUTED program plots.

pandas is not importable here and never will be: the core is stdlib-only so M14 can inline it. So
this module reimplements the reductions pandas performs, and every choice below is fixed by
MEASUREMENT against pandas rather than by what is arithmetically nicest -- the more precise engine
is the less faithful one, exactly as in `expr.py`'s ruling.

The four decisions that carry the module, all measured:

- a float64 `sum` is ORDERED binary64 Kahan compensation in file-row order. Naive left-to-right
  differs on 2,761 of 4,000 admitted-profile CSV groups, `math.fsum` on 1,483; Kahan matches on
  0 of 16,062.
- an int64 `mean` casts each value to float64 BEFORE summing, so it is NOT the exact integer mean:
  `[2**53, 1, 0]` splits the two orders by 1 ulp.
- `min` and `max` update on STRICT `<` and `>`, so a tie keeps the FIRST value's bits.
- group key order IS the plotted x-order, and it is pandas' `sort=True` default: ascending, by
  Unicode code point for text keys, measured identical under `C`, `C.utf8` and `en_US.utf8` while
  an `en_US` collation control orders differently.

Host versus both target Pyodide builds: 0 differences over 96,372 reduction rows. Unlike the libm
functions the reduction carries NO measured ulp band, so a disagreement here is a defect rather than
an environment gap.
"""

from dataclasses import dataclass
from typing import Literal, NoReturn, assert_never

from verifier.pysrc.budget import WorkBudget
from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.table import CellValue

__all__ = ["Aggregated", "ColumnDtype", "Reduction", "aggregate_series", "column_dtype"]

# Grouped reductions, closed. Each one is a total function from a group's cells to one number,
# which is what lets the judge reproduce it exactly; a reduction needing a parameter (quantile,
# std's delta degrees of freedom) is not a member.
type Reduction = Literal["sum", "mean", "min", "max"]

# The dtype `pd.read_csv` infers for a column inside the admitted cell profile. There is no third
# member: the profile refuses every NA spelling, every boolean text and every non-fixed-point token
# before a cell reaches here, so a selected value column is one of these two.
type ColumnDtype = Literal["int64", "float64"]

# `mean` is the one reduction that does not retain an integer dtype: pandas produces float64 for it,
# which is also why the renderer's integer bound never binds an integer mean.
_DTYPE_RETAINING = frozenset({"sum", "min", "max"})


@dataclass(frozen=True, slots=True)
class Aggregated:
    """One reduced series in PLOTTED order, with the evidence G11 publishes beside it.

    `counts` is aligned with `keys` and sums to the data-row count of the file for every input,
    because every row joins exactly one group. That totality is what keeps G7's range claim and
    G8's ROW COVERAGE unconditional while aggregation is admitted: a `groupby` drops no row. It
    does collapse rows into fewer points than the file has rows, which is why G8 is coverage rather
    than point-count equality and why `counts` is published rather than merely computed.
    """

    keys: tuple[CellValue, ...]
    values: tuple[float, ...]
    counts: tuple[int, ...]
    dtype: ColumnDtype


def _refuse(code: RefusalCode) -> NoReturn:
    raise PysrcRefusalError(code)


def column_dtype(texts: tuple[str, ...]) -> ColumnDtype:
    """`int64` only when NO cell carries a decimal point, which is pandas' own inference.

    Reading the TEXT rather than the parsed float is what makes this exact: `5` and `5.0` parse to
    the same float64 and pandas types their columns differently.
    """
    return "float64" if any("." in text for text in texts) else "int64"


def _kahan_sum(values: tuple[float, ...]) -> float:
    """Ordered binary64 Kahan compensation. Not naive, not `fsum`, not Neumaier.

    The compensation reset pandas performs for NaN is absent because NaN cannot arrive: the cell
    profile refuses every NA spelling ahead of this call, so the arm would be an unreachable branch.
    """
    total = 0.0
    compensation = 0.0
    for value in values:
        adjusted = value - compensation
        running = total + adjusted
        compensation = (running - total) - adjusted
        total = running
    return total


def _extremum[T: (float, int)](values: tuple[T, ...], *, greater: bool) -> T:
    """Strict `<`/`>`, so a tie keeps the FIRST value's bits -- `[-0.0, +0.0]` reduces to `-0.0`."""
    best = values[0]
    for value in values[1:]:
        if (value > best) if greater else (value < best):
            best = value
    return best


def _reduce_float(values: tuple[float, ...], reduction: Reduction) -> float:
    match reduction:
        case "sum":
            return _kahan_sum(values)
        case "mean":
            # Sum THEN divide, in that order. A running mean and a compensated divide each land on a
            # different last bit, and this is the order pandas takes.
            return _kahan_sum(values) / len(values)
        case "min":
            return _extremum(values, greater=False)
        case "max":
            return _extremum(values, greater=True)
        case _ as unreachable:  # pragma: no cover - `Reduction` is closed
            assert_never(unreachable)


def _reduce_int(values: tuple[int, ...], reduction: Reduction) -> float:
    match reduction:
        case "sum":
            # Exact: Python integers do not wrap where pandas' int64 would, and the profile makes
            # that difference unreachable -- int32 cells times `max_table_rows` stays under 2**48,
            # so the result is also exactly representable in the float64 the table carries.
            return float(sum(values))
        case "mean":
            # Per-value float cast, THEN Kahan, THEN divide. Not the exact integer mean: pandas
            # rounds each value into float64 first, and `[2**53, 1, 0]` is where the two split.
            return _kahan_sum(tuple(float(value) for value in values)) / len(values)
        case "min":
            return float(_extremum(values, greater=False))
        case "max":
            return float(_extremum(values, greater=True))
        case _ as unreachable:  # pragma: no cover - `Reduction` is closed
            assert_never(unreachable)


def _sort_key(value: CellValue) -> tuple[int, float, str]:
    """Total over one column's key class, and code-point ordered for text.

    Python compares `str` by code point, so ascending `sorted` IS pandas' `sort=True` order with no
    locale in the path. The leading discriminator keeps the function total without ever comparing a
    number against a string, which would raise.
    """
    if isinstance(value, str):
        return (1, 0.0, value)
    return (0, value, "")


def aggregate_series(  # noqa: PLR0913 - six independent inputs, none derivable from another
    keys: tuple[CellValue, ...],
    value_texts: tuple[str, ...],
    values: tuple[float, ...],
    reduction: Reduction,
    *,
    budget: WorkBudget,
    max_groups: int,
) -> Aggregated:
    """Reduce `values` by `keys`, in the order and to the bits the executed program would plot.

    `keys` and `value_texts` are the two selected columns in FILE order, already swept against the
    cell profile by the caller. `value_texts` decides the dtype; `values` carries the parsed
    float64 the float path reduces.

    Row order inside each group is file order, which is what makes the ordered summation
    well defined; group order is sorted key order, which is what the figure draws along x.
    """
    budget.charge(len(keys))
    members: dict[CellValue, list[int]] = {}
    for index, key in enumerate(keys):
        members.setdefault(key, []).append(index)
    # Checked BEFORE the reduction it bounds: a high-cardinality key column must refuse on what it
    # would cost rather than after paying it.
    if len(members) > max_groups:
        _refuse("work_budget_exceeded")
    budget.charge(len(members))

    dtype = column_dtype(value_texts)
    integers = tuple(int(text) for text in value_texts) if dtype == "int64" else ()
    ordered = sorted(members, key=_sort_key)
    reduced: list[float] = []
    counts: list[int] = []
    for key in ordered:
        rows = members[key]
        counts.append(len(rows))
        if dtype == "int64":
            reduced.append(_reduce_int(tuple(integers[index] for index in rows), reduction))
        else:
            reduced.append(_reduce_float(tuple(values[index] for index in rows), reduction))
    result_dtype: ColumnDtype = (
        "int64" if dtype == "int64" and reduction in _DTYPE_RETAINING else "float64"
    )
    return Aggregated(
        keys=tuple(ordered),
        values=tuple(reduced),
        counts=tuple(counts),
        dtype=result_dtype,
    )
'''

_SOURCES["webui.paste_in.reasons"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Why a figure failed, in the words the chat user reads above the fixed failure verdict.

Data only; `filter.py` picks the reason and the language. The outlet shows one of these texts as an
Open WebUI status line, which the chat keeps in `statusHistory` and never sends back to the model.
Each text is a short cause, plus a fix where one is known, because Open WebUI clamps a status line
to one line.
"""

from typing import Final, Literal

from verifier.figure.reasons import FigureReason

# Faults the outlet finds around the judge: the model's call, the browser round trip, the image.
OutletCause = Literal[
    "no_tool_call",
    "no_user",
    "no_browser",
    "browser_timeout",
    "browser_error",
    "browser_no_answer",
    "reply_malformed",
    "sandbox_unavailable",
    "sandbox_error",
    "no_description",
    "no_image",
    "publish_failed",
]

type Reason = FigureReason | OutletCause

# reason -> (English, Japanese).
REASONS: Final[dict[Reason, tuple[str, str]]] = {
    "no_tool_call": (
        "The model did not send a chart program.",
        "モデルからグラフのプログラムが届きませんでした。",
    ),
    "no_user": (
        "The request has no signed-in user.",
        "サインインしているユーザーがいません。",
    ),
    "no_browser": (
        "No browser session is available to draw the chart.",
        "グラフを描くブラウザのセッションがありません。",
    ),
    "browser_timeout": (
        "The browser did not answer within 60 seconds.",
        "ブラウザが 60 秒以内に応答しませんでした。",
    ),
    "browser_error": (
        "The call to the browser failed.",
        "ブラウザの呼び出しに失敗しました。",
    ),
    "browser_no_answer": (
        "The chat tab did not answer. Keep the tab open and try again.",
        "チャットのタブが応答しませんでした。タブを開いたままにしてください。",
    ),
    "reply_malformed": (
        "The browser sent a reply in an unknown format.",
        "ブラウザの応答の形式が不明です。",
    ),
    "sandbox_unavailable": (
        "The browser could not load Pyodide. Turn off the ad blocker for this site.",
        "Pyodide を読み込めません。このサイトの広告ブロッカーをオフにしてください。",
    ),
    "sandbox_error": (
        "The browser runtime reported an error.",
        "ブラウザの実行環境がエラーを報告しました。",
    ),
    "no_description": (
        "The browser run did not report the drawn figure.",
        "ブラウザが描画した図を報告しませんでした。",
    ),
    "program_syntax_error": (
        "The program is not valid Python.",
        "プログラムが正しい Python ではありません。",
    ),
    "program_error": (
        "The program stopped with an error.",
        "プログラムがエラーで停止しました。",
    ),
    "module_not_available": (
        "The program imports a module that the browser sandbox does not have.",
        "プログラムが、ブラウザのサンドボックスにないモジュールを読み込んでいます。",
    ),
    "figure_too_large": (
        "The figure is too large to check.",
        "図が大きすぎるため、チェックできません。",
    ),
    "no_figure": (
        "The program did not draw a matplotlib figure.",
        "プログラムが matplotlib の図を描いていません。",
    ),
    "multiple_figures": (
        "The program drew more than one figure. Put all panels in one figure.",
        "プログラムが複数の図を描きました。すべてのパネルを 1 つの図に入れてください。",
    ),
    "glyph_missing": (
        "The figure has characters that the available fonts cannot draw.",
        "図に、使用できるフォントで描けない文字があります。",
    ),
    "raster_image": (
        "The figure contains an image, which the verifier cannot check.",
        "図に画像が含まれています。検証器は画像をチェックできません。",
    ),
    "axes_not_judged": (
        "The figure uses axes that the verifier cannot check, such as polar, 3D or inset axes.",
        "図に、検証器がチェックできない軸 (極座標、3D、挿入図など) があります。",
    ),
    "axes_twin": (
        "Two axes share one panel, for example a second y axis.",
        "1 つのパネルに 2 つの軸があります (2 つ目の y 軸など)。",
    ),
    "axes_overlap": (
        "Two panels overlap.",
        "2 つのパネルが重なっています。",
    ),
    "artist_not_judged": (
        "The figure contains a chart element that the verifier cannot check.",
        "図に、検証器がチェックできないグラフ要素があります。",
    ),
    "no_data": (
        "A panel shows no data.",
        "データを表示していないパネルがあります。",
    ),
    "mark_not_in_data": (
        "A chart element is not placed by its data values.",
        "データの値で配置されていないグラフ要素があります。",
    ),
    "scale_not_linear": (
        "An axis is not linear. A log axis must name its scale in its label or the panel title.",
        "線形でない軸があります。対数軸の場合は、軸ラベルかパネルのタイトルに対数と書いてください。",
    ),
    "axis_inverted": (
        "An axis is inverted.",
        "反転している軸があります。",
    ),
    "zero_not_in_limits": (
        "The value axis of a bar, histogram or area chart does not include zero.",
        "棒グラフ、ヒストグラム、面グラフの値の軸にゼロが含まれていません。",
    ),
    "tick_label_mismatch": (
        "A tick label does not show the value at its position.",
        "目盛りのラベルが、その位置の値を示していません。",
    ),
    "point_clipped": (
        "A data point is outside the axis limits.",
        "軸の範囲の外にあるデータ点があります。",
    ),
    "mark_hidden": (
        "A chart element or panel is hidden or draws nothing visible.",
        "非表示のグラフ要素やパネル、または何も見えないグラフ要素があります。",
    ),
    "value_not_finite": (
        "A drawn value is missing or not finite, or a point was dropped.",
        "描画する値に欠損値や有限でない値があるか、点が欠落しています。",
    ),
    "bar_not_from_zero": (
        "A bar does not start at zero.",
        "ゼロから始まっていない棒があります。",
    ),
    "bars_overlap": (
        "Two bars overlap.",
        "重なっている棒があります。",
    ),
    "category_not_unique": (
        "A category occurs more than once in one series.",
        "1 つの系列に同じカテゴリが複数あります。",
    ),
    "x_not_ordered": (
        "The x values of a line are not in order.",
        "折れ線の x の値が順序どおりではありません。",
    ),
    "hist_counts": (
        "The histogram bars do not show the counts of its data.",
        "ヒストグラムの棒が、データの度数を示していません。",
    ),
    "pie_not_whole": (
        "The pie slices do not show the shares of its values.",
        "円グラフの扇形が、値の割合を示していません。",
    ),
    "area_not_from_zero": (
        "A filled area does not start at zero or on another area.",
        "ゼロからも他の面からも始まっていない面があります。",
    ),
    "marker_size_varies": (
        "Marker sizes vary, but no size legend explains them.",
        "マーカーの大きさが異なりますが、大きさの凡例がありません。",
    ),
    "marker_color_varies": (
        "Marker colors vary, but no color bar or color legend explains them.",
        "マーカーの色が異なりますが、カラーバーも色の凡例もありません。",
    ),
    "legend_mismatch": (
        "The legend does not name the chart's series correctly.",
        "凡例がグラフの系列を正しく示していません。",
    ),
    "csv_too_large": (
        "The CSV file is too large.",
        "CSV ファイルが大きすぎます。",
    ),
    "csv_not_parsable": (
        "The CSV file cannot be read.",
        "CSV ファイルを読み取れません。",
    ),
    "work_budget_exceeded": (
        "Checking the values needs more computation than the limit allows.",
        "値のチェックに必要な計算量が上限を超えています。",
    ),
    "value_not_found": (
        "A drawn value is not in your data. Attach a CSV file or write the values in your request.",
        "描画した値がデータにありません。CSV ファイルを添付するか、依頼文に値を書いてください。",
    ),
    "label_not_in_request": (
        "A category label is not in your request. Write each label in your request.",
        "カテゴリのラベルが依頼文にありません。依頼文に各ラベルを書いてください。",
    ),
    "column_not_requested": (
        "The chart replaces a requested column, or its values fit two columns. Name the column.",
        "グラフが依頼の列を別の列に置き換えたか、値が 2 つの列に当てはまります。"
        "列名を書いてください。",
    ),
    "column_not_named": (
        "Your request does not name a drawn column. Use the file's column names.",
        "描いた列の名前が依頼にありません。列名はファイルのとおりに書いてください。",
    ),
    "label_not_consistent": (
        "A chart label names a CSV column or a summary that the chart does not show.",
        "グラフのラベルが、グラフにない CSV の列または集計を挙げています。",
    ),
    "no_image": (
        "The browser run did not produce exactly one PNG image.",
        "ブラウザでの実行で PNG 画像が 1 枚だけ作られませんでした。",
    ),
    "publish_failed": (
        "Open WebUI could not attach the image.",
        "Open WebUI が画像を添付できませんでした。",
    ),
}
'''

_SOURCES["webui.paste_in.receipt"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""One backend-owned record of the last model-visible tool call.

The generated paste-ins embed this module in separate namespaces. A tagged built-in tuple crosses
their class-identity boundary; the reader validates its shape and accepts no other state value.
"""

from dataclasses import dataclass
from typing import Final

from verifier.figure.anchoring import Aliases

RECEIPT_ATTR: Final = "figure_verification_receipt"
# `/2` carries the admin's column aliases (Q43); a `/1` value decodes to no receipt.
RECEIPT_TAG: Final = "figure-verification-receipt/2"
_RECEIPT_LENGTH = 5
_PAIR = 2


@dataclass(frozen=True, slots=True)
class Receipt:
    """Program, user-owned candidate ids and admin aliases, never a verdict or uploaded bytes."""

    program: str
    file_ids: tuple[str, ...]
    request_text: str | None
    aliases: Aliases


def write_receipt(request: object, receipt: Receipt) -> None:
    """Replace the prior call with a tagged, class-identity-independent value."""
    state = getattr(request, "state", None)
    if state is None:
        return
    setattr(
        state,
        RECEIPT_ATTR,
        (RECEIPT_TAG, receipt.program, receipt.file_ids, receipt.request_text, receipt.aliases),
    )


def read_receipt(request: object) -> Receipt | None:
    """Decode only the backend state's tagged, exactly typed carrier."""
    state = getattr(request, "state", None)
    value = getattr(state, RECEIPT_ATTR, None)
    if type(value) is not tuple or len(value) != _RECEIPT_LENGTH or value[0] != RECEIPT_TAG:
        return None
    _, program, file_ids, request_text, aliases = value
    if (
        type(program) is not str
        or type(file_ids) is not tuple
        or any(type(file_id) is not str for file_id in file_ids)
        or (request_text is not None and type(request_text) is not str)
        or type(aliases) is not tuple
        or any(
            type(pair) is not tuple or len(pair) != _PAIR or any(type(n) is not str for n in pair)
            for pair in aliases
        )
    ):
        return None
    return Receipt(program, file_ids, request_text, aliases)
'''

_SOURCES["webui.paste_in.sandbox"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The code the outlet sends to the browser: the reader, then the model's program, unchanged.

OWUI picks the sandbox packages from literal imports in the RPC source and patches the plotting
library when the source spells that library's name, which raises before the program runs (A5).
So the plotting name is never literal here: the wrapper loads the three packages itself, quietly,
and carries the reader and the program as base64, split wherever the encoding spells that name.
"""

import base64
from pathlib import Path
from typing import Final

from verifier.figure import reader

FONT_PATH: Final = "/tmp/figure-verification-cjk.ttf"  # noqa: S108 - the sandbox's in-memory FS
_PLOTTING: Final = "mat" + "plotlib"


def reader_source() -> str:
    """The reader's exact text: the paste-in keeps each embedded module's text, a checkout reads
    the tracked file."""
    embedded = getattr(reader, "__paste_in_source__", None)
    if isinstance(embedded, str):
        return embedded
    return Path(reader.__file__).read_text(encoding="utf-8")


def _payload(data: bytes) -> str:
    """Base64 source for `data`, split wherever the encoding spells the plotting name."""
    parts = base64.b64encode(data).decode("ascii").split(_PLOTTING)
    return " + 'mat' + 'plotlib' + ".join(repr(part) for part in parts)


def wrapper_code(program: str, font: bytes | None = None) -> str:
    """The RPC code: load the stack, write the font, run the reader over the exact program bytes.

    A `font` becomes matplotlib's fallback after DejaVu Sans inside the reader's run, so ordinary
    text draws its CJK glyphs; without one the reader runs on matplotlib's defaults. The reply's
    stdout is the reader's alone: the description line, then at most one PNG line.
    """
    font_lines = (
        ("_fv_font = None",)
        if font is None
        else (
            f"_fv_font = {FONT_PATH!r}",
            "with open(_fv_font, 'wb') as _fv_handle:",
            f"    _fv_handle.write(_fv_b64.b64decode({_payload(font)}))",
        )
    )
    source = _payload(reader_source().encode("utf-8"))
    program_bytes = _payload(program.encode("utf-8", "surrogatepass"))
    return (
        "\n".join(
            (
                "import pyodide_js as _fv_pyodide",
                "await _fv_pyodide.loadPackage(['numpy', 'pandas', 'mat' + 'plotlib'],",
                "                              messageCallback=lambda _message: None)",
                "import base64 as _fv_b64",
                "import os as _fv_os",
                "_fv_os.environ['MPLBACKEND'] = 'AGG'",
                *font_lines,
                "_fv_reader = {'__name__': 'figure_verification_reader'}",
                f"_fv_source = _fv_b64.b64decode({source}).decode('utf-8')",
                "exec(compile(_fv_source, '<figure-reader>', 'exec'), _fv_reader)",
                f"_fv_program = _fv_b64.b64decode({program_bytes})",
                "_fv_program = _fv_program.decode('utf-8', 'surrogatepass')",
                "print(_fv_reader['run'](_fv_program, _fv_font), end='')",
            )
        )
        + "\n"
    )
'''

_SOURCES["verifier.figure.keys"] = r'''
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
'''

_SOURCES["verifier.figure.parts"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The closed artist set: every part of the figure is a judged family, listed text, or a block.

Law = `.claude/rules/figure.md` § Closed artist set. A family is decided by (class, origin) and the
records the reader attached (bar container, hist record, pie record, band arrays); a part the table
does not name blocks, marking the line that created it. Each judged axes becomes a `Panel`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal, cast

from verifier.figure.description import (
    Artist,
    Axes,
    BandArrays,
    BandGeometry,
    Description,
    Figure,
    LineGeometry,
    RectGeometry,
    TextGeometry,
    call_line,
)
from verifier.figure.reasons import block
from verifier.figure.ticks import mismatched_tick

type Family = Literal["line", "scatter", "bar", "hist", "pie", "band", "reference"]
type _Kind = Family | Literal["text"] | None

_RASTER: Final = frozenset({"AxesImage", "QuadMesh", "FigureImage", "PcolorImage"})
_LINES: Final = frozenset({"Axes.plot", "Axes.step"})
# Reference origin -> horizontal (its value lies on x).
_REFERENCES: Final = {
    "Axes.axhline": False,
    "Axes.axhspan": False,
    "Axes.axvline": True,
    "Axes.axvspan": True,
}
_REFERENCE_LINES: Final = frozenset({"Axes.axhline", "Axes.axvline"})
_REFERENCE_SPANS: Final = frozenset({"Axes.axhspan", "Axes.axvspan"})
_LISTED: Final = frozenset({"Axes.text", "Axes.annotate", "Axes.bar_label", "Axes.pie"})
_BANDS: Final = frozenset({"Axes.fill_between", "stackplot"})
_BARS: Final = frozenset({"Axes.bar", "Axes.barh"})
_TOLERANCE: Final = 1e-9


@dataclass(frozen=True, slots=True)
class Mark:
    """One judged mark: its family, the axes artists that draw it, and the record grouping them.

    `horizontal` = the mark's value lies on x (barh, a horizontal hist, an axvline/axvspan).
    """

    family: Family
    artists: tuple[int, ...]
    container: int | None = None
    pie: int | None = None
    horizontal: bool = False


@dataclass(frozen=True, slots=True)
class Panel:
    """One judged axes: its index in the figure, its marks, and the text it only lists."""

    index: int
    axes: Axes
    marks: tuple[Mark, ...]
    texts: tuple[str, ...]
    pie_labels: tuple[str, ...] = ()  # drawn wedge labels: keys the values stage judges


def _line(artist: Artist, _axes: Axes, _index: int) -> _Kind:
    origin = artist.origin or ""
    if origin in _LINES:
        return "line"
    return "reference" if origin in _REFERENCE_LINES else None


def _scatter(artist: Artist, _axes: Axes, _index: int) -> _Kind:
    return "scatter" if artist.origin == "Axes.scatter" else None


def _rectangle(artist: Artist, axes: Axes, index: int) -> _Kind:
    origin = artist.origin or ""
    if origin in _REFERENCE_SPANS:  # matplotlib 3.9 draws a span as a Rectangle
        return "reference"
    owner = next((c for c in axes.containers if index in c.members), None)
    upright = cast("RectGeometry", artist.geometry).angle == 0.0
    if owner is None or owner.cls != "BarContainer" or not upright:  # a rotated bar is no bar
        return None
    if origin in _BARS and owner.hist is None:
        return "bar"
    return "hist" if origin == "Axes.hist" and owner.hist is not None else None


def _polygon(artist: Artist, _axes: Axes, _index: int) -> _Kind:
    # matplotlib 3.8 (the sandbox) draws a span as a Polygon; any other Polygon is unjudged.
    return "reference" if (artist.origin or "") in _REFERENCE_SPANS else None


def _wedge(artist: Artist, axes: Axes, index: int) -> _Kind:
    recorded = any(index in pie.wedges for pie in axes.pies)
    return "pie" if artist.origin == "Axes.pie" and recorded else None


def _band(artist: Artist, _axes: Axes, _index: int) -> _Kind:
    geometry = cast("BandGeometry", artist.geometry)
    # The arrays are read back from the final polygon, and the input count shows what it dropped.
    read_back = geometry.band is not None and geometry.inputs is not None
    return "band" if artist.origin in _BANDS and read_back else None


def _text(artist: Artist, _axes: Axes, _index: int) -> _Kind:
    return "text" if artist.origin in _LISTED else None


_FAMILIES: Final[dict[str, Callable[[Artist, Axes, int], _Kind]]] = {
    "Line2D": _line,
    "PathCollection": _scatter,
    "Rectangle": _rectangle,
    "Polygon": _polygon,
    "Wedge": _wedge,
    "PolyCollection": _band,
    "Text": _text,
    "Annotation": _text,
}


def _family(artist: Artist, axes: Axes, index: int) -> _Kind:
    """The family one artist belongs to; `None` = outside the closed set."""
    read = _FAMILIES.get(artist.cls)
    return None if read is None else read(artist, axes, index)


def _outline(artist: Artist, bands: list[Artist]) -> bool:
    """A pandas area outline: a plotted line equal to a band's edge (stack geometry, not data).

    `artist` is a judged line and every `bands` member a judged band, so their geometry is known.
    """
    line = cast("LineGeometry", artist.geometry)
    for band in bands:
        arrays = cast("BandArrays", cast("BandGeometry", band.geometry).band)
        if line.x == arrays.x and line.y in (arrays.y1, arrays.y2):
            return True
    return False


def _marks(axes: Axes, families: dict[int, Family]) -> list[Mark]:
    marks: list[Mark] = []
    for number, container in enumerate(axes.containers):
        members = tuple(i for i in container.members if families.get(i) in ("bar", "hist"))
        if members:
            family: Family = "hist" if container.hist is not None else "bar"
            horizontal = container.orientation == "horizontal"
            marks.append(Mark(family, members, container=number, horizontal=horizontal))
    for number, pie in enumerate(axes.pies):
        if pie.wedges:
            marks.append(Mark("pie", pie.wedges, pie=number))
    for index, family in families.items():
        if family in ("line", "scatter", "band"):
            marks.append(Mark(family, (index,)))
        elif family == "reference":
            marks.append(
                Mark(
                    "reference", (index,), horizontal=_REFERENCES[axes.artists[index].origin or ""]
                )
            )
    return sorted(marks, key=lambda mark: mark.artists[0])


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    return width > _TOLERANCE and height > _TOLERANCE


# What a colorbar draws itself: its colour solids and the dividers between them.
_COLORBAR_PARTS: Final = frozenset({("QuadMesh", "Axes.pcolormesh"), ("LineCollection", None)})


def _check_colorbar(axes: Axes) -> None:
    """A colorbar holds its own parts alone, and its tick labels name the values they mark."""
    for artist in axes.artists:
        if (artist.cls, artist.origin) not in _COLORBAR_PARTS:
            block("artist_not_judged", artist.site)
    for name, axis in (("x", axes.x), ("y", axes.y)):
        if mismatched_tick(axis, key_labels=False) is not None:
            block("tick_label_mismatch", call_line(axes.calls, f"{name}ticks") or axes.site)


def _judged_axes(figure: Figure) -> list[int]:
    """The judged axes; a colorbar axes passes only as the colorbar of a judged scatter."""
    judged: list[int] = []
    for index, axes in enumerate(figure.axes):
        if axes.cls != "Axes":
            block("axes_not_judged", axes.site)
        if axes.colorbar_of is None:
            judged.append(index)
            continue
        owner, artist = axes.colorbar_of
        mappable = figure.axes[owner].artists[artist]
        if (mappable.cls, mappable.origin) != ("PathCollection", "Axes.scatter"):
            block("axes_not_judged", axes.site)
        _check_colorbar(axes)
    for position, first in enumerate(judged):
        for second in judged[position + 1 :]:
            a, b = figure.axes[first], figure.axes[second]
            if (second in a.shared_x or second in a.shared_y) and a.position == b.position:
                block("axes_twin", call_line(a.calls, "twin") or b.site)
            if _overlap(a.position, b.position):
                block("axes_overlap", b.site)
    return judged


def _panel(index: int, axes: Axes) -> Panel:
    families: dict[int, Family] = {}
    texts: list[str] = []
    labels: list[str] = []
    keys = {text for pie in axes.pies for text in pie.texts if text is not None}
    for number, artist in enumerate(axes.artists):
        if artist.cls in _RASTER:
            block("raster_image", artist.site)
        kind = _family(artist, axes, number)
        if kind is None:
            block("artist_not_judged", artist.site)
        if kind == "text":
            text = cast("TextGeometry", artist.geometry).text
            if text.strip():
                (labels if number in keys else texts).append(text)
        else:
            families[number] = kind
    bands = [axes.artists[i] for i, family in families.items() if family == "band"]
    for number in [i for i, family in families.items() if family == "line"]:
        if _outline(axes.artists[number], bands):
            del families[number]
    marks = _marks(axes, families)
    if not marks:
        block("no_data", axes.site)
    return Panel(index, axes, tuple(marks), tuple(texts), tuple(labels))


def panels(description: Description) -> tuple[Figure, tuple[Panel, ...]]:
    """The one figure's judged panels, or a block naming the first part outside the closed set.

    Precondition: the figure stage passed, so exactly one figure is described.
    """
    figure = description.figures[0]
    for part in figure.others:
        block("raster_image" if part.cls in _RASTER else "artist_not_judged", part.site)
    judged = tuple(_panel(index, figure.axes[index]) for index in _judged_axes(figure))
    if not judged:
        block("no_data", figure.site)
    return figure, judged
'''

_SOURCES["verifier.pysrc.csvread"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The safe CSV profile: what the verifier parses with stdlib `csv` + `float`, and what it refuses.

The verifier may not depend on pandas, but the SANDBOX calls plain `pd.read_csv`, whose default
float parser is not correctly rounded. Measured against stdlib `float` over 1,000,000 adversarial
cells, 326,834 disagree, 12,053 of them by 2 to 7,262 ulp, and no significant-digit cap repairs it.
So the profile RESTRICTS rather than reimplementing `xstrtod`: it admits only a region measured at
0 bit mismatches out of 4,000,000 against the target sandbox, and refuses the exact complement.

Two admitted-region clauses are about the RENDERER, not the parser: Pyodide's `plt.bar` keeps
integer heights as `int32` and RAISES outside signed 32 bits, and matplotlib bar erases the sign of
`-0.0`. Both are excluded here so a drawn value cannot differ from the value the judge reads.

Full six-clause profile + its evidence = `.agent/archive/contracts/m13u5.md`.
"""

import csv
import io
import math
import re
from typing import Literal, NoReturn

from verifier.pysrc.aggregate import column_dtype
from verifier.pysrc.budget import WorkBudget
from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.limits import PysrcLimits
from verifier.pysrc.table import CellValue

__all__ = ["NA_SPELLINGS", "key_values"]

# Every default NA spelling pandas recognises, measured on the target build. A cell matching one of
# these -- quoted or plain -- refuses rather than becoming a null: the verifier has no null, and
# that absence is what makes G8's row coverage true by construction. Coverage, not point-count
# equality: an aggregate collapses its rows into one point per group and G11 publishes the counts.
NA_SPELLINGS: frozenset[str] = frozenset(
    {
        "",
        "#N/A",
        "#N/A N/A",
        "#NA",
        "-1.#IND",
        "-1.#QNAN",
        "-NaN",
        "-nan",
        "1.#IND",
        "1.#QNAN",
        "<NA>",
        "N/A",
        "NA",
        "NULL",
        "NaN",
        "None",
        "n/a",
        "nan",
        "null",
    }
)

_UTF8_BOM = b"\xef\xbb\xbf"
_CR = ord("\r")
_LF = ord("\n")
_INT32_MIN = -(2**31)
_INT32_MAX = 2**31 - 1
_MAX_SIGNIFICANT_DIGITS = 15
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?")
_BOOLEAN_TEXT = frozenset({"true", "false"})
type _ColumnClass = Literal["numeric", "categorical", "mixed"]
type _RawTable = tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]


def _refuse(code: RefusalCode, cause: BaseException | None = None) -> NoReturn:
    raise PysrcRefusalError(code) from cause


def _check_record_endings(content: bytes) -> None:
    for index, byte in enumerate(content):
        if byte == _CR and (index + 1 == len(content) or content[index + 1] != _LF):
            _refuse("csv_not_parsable")


def _check_cell_sizes(row: list[str], limit: int) -> None:
    if any(len(cell.encode("utf-8")) > limit for cell in row):
        _refuse("csv_too_large")


def _record_work(row: list[str]) -> int:
    return sum(1 + len(cell) // 32 for cell in row)


def _check_header(header: list[str], limits: PysrcLimits) -> None:
    _check_cell_sizes(header, limits.max_csv_cell_bytes)
    if len(header) > limits.max_csv_columns:
        _refuse("csv_too_large")
    if not header or any(not cell for cell in header) or len(set(header)) != len(header):
        _refuse("csv_not_parsable")


def _read_csv(content: bytes, limits: PysrcLimits, budget: WorkBudget) -> _RawTable:
    if len(content) > limits.max_csv_bytes:
        _refuse("csv_too_large")
    if content.startswith(_UTF8_BOM) or b"\x00" in content:
        _refuse("csv_not_parsable")
    _check_record_endings(content)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        _refuse("csv_not_parsable", exc)

    reader = csv.reader(
        io.StringIO(text, newline=""),
        delimiter=",",
        quotechar='"',
        doublequote=True,
        escapechar=None,
        skipinitialspace=False,
        strict=True,
    )
    try:
        header_row = next(reader)
        budget.charge(_record_work(header_row))
        _check_header(header_row, limits)

        rows: list[tuple[str, ...]] = []
        for row_number, row in enumerate(reader, start=1):
            if row_number > limits.max_csv_rows:
                _refuse("csv_too_large")
            if row_number > limits.max_table_rows:
                _refuse("work_budget_exceeded")
            _check_cell_sizes(row, limits.max_csv_cell_bytes)
            if len(row) != len(header_row):
                _refuse("csv_not_parsable")
            budget.charge(_record_work(row))
            rows.append(tuple(row))
    except StopIteration:
        _refuse("csv_not_parsable")
    except csv.Error as exc:
        _refuse("csv_not_parsable", exc)

    if not rows:
        _refuse("csv_not_parsable")
    return tuple(header_row), tuple(rows)


def _significant_digits(text: str) -> int:
    digits = text.lstrip("-").replace(".", "").lstrip("0")
    return len(digits) if digits else 1


def _profile_float(text: str, value: float, *, integer_column: bool) -> float:
    if (
        _NUMBER.fullmatch(text) is None
        or _significant_digits(text) > _MAX_SIGNIFICANT_DIGITS
        or not math.isfinite(value)
        or (integer_column and not _INT32_MIN <= value <= _INT32_MAX)
        or (value == 0.0 and math.copysign(1.0, value) < 0.0)
    ):
        _refuse("value_not_in_profile")
    # The range and signed-zero clauses bind the renderer, not parsing. Pyodide's integer bar
    # raises outside int32 -- an INTEGER column alone reaches that path; a column pandas infers
    # float64 (any token with a decimal point) draws through the float path, measured bit-exact to
    # 2**53 (Q12) -- while matplotlib bar turns -0.0 into +0.0; either would make the emitted mark
    # differ from this recomputation even though pandas parsed the token correctly.
    return value


def _check_selected_text(text: str) -> None:
    if text in NA_SPELLINGS or text.casefold() in _BOOLEAN_TEXT:
        # pandas infers bool and matplotlib renders it as 1/0; the verifier has no bool cell type.
        _refuse("value_not_in_profile")


def _classify_column(texts: tuple[str, ...]) -> _ColumnClass:
    parsed = 0
    for text in texts:
        try:
            float(text)
        except ValueError:
            continue
        parsed += 1
    if parsed == len(texts):
        return "numeric"
    if parsed == 0:
        return "categorical"
    return "mixed"


def _numeric_value(text: str, integer_column: bool) -> float:  # noqa: FBT001 - the one seam
    # Reached only for a column `_classify_column` read as numeric: every cell parses.
    return _profile_float(text, float(text), integer_column=integer_column)


def _numeric_values(texts: tuple[str, ...]) -> tuple[float, ...]:
    """A numeric column's cells; its inferred dtype picks the range clause (user ruling Q12)."""
    integer_column = column_dtype(texts) == "int64"
    return tuple(_numeric_value(text, integer_column) for text in texts)


def key_values(texts: tuple[str, ...]) -> tuple[CellValue, ...]:
    """A column as group or axis KEYS: numbers when every cell parses, else its text.

    A mixed column stays text: pandas groups `['2', 'a', '10', '2']` perfectly well -- measured, as
    the text keys `['10', '2', 'a']`.
    """
    return _numeric_values(texts) if _classify_column(texts) == "numeric" else texts
'''

_SOURCES["webui.paste_in.checks"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The "Show checks" breakdown: every check a figure faces, as one self-contained HTML document.

Data plus one pure renderer; `filter.py` sends the document as an Open WebUI message embed, which
the chat renders in a sandboxed iframe and never sends to a model. Each row opens to what its check
does, why it failed and a link to its section of the reference; the passed `program` row and the
failing row also quote the program, the failing row marking the line that drew the offending part
or made the offending call (ruling 13: display only, never a verdict input). Every text slot comes
from the tables here or from `REASONS`; the one exception is the program itself, quoted escaped
inside a code listing with whatever it spells. Request text, file contents and sandbox output are
never added from any other source.

A check shows as passed only when it completed, so each reason maps to the check whose stage
raises it, in the judge's stage order (`.claude/rules/figure.md` § Checks).
"""

import html
import re
import unicodedata
from dataclasses import dataclass
from typing import Final, Literal

from verifier.figure.anchoring import Anchoring
from webui.paste_in.reasons import REASONS, Reason

Check = Literal["program", "run", "figure", "parts", "axes", "marks", "values", "columns", "attach"]
type _State = Literal["pass", "fail", "skip"]

CHECKS: Final[tuple[Check, ...]] = (
    "program",
    "run",
    "figure",
    "parts",
    "axes",
    "marks",
    "values",
    "columns",
    "attach",
)

_REASONS_OF: Final[dict[Check, tuple[Reason, ...]]] = {
    "program": ("no_tool_call", "no_user"),
    "run": (
        "no_browser",
        "browser_timeout",
        "browser_error",
        "browser_no_answer",
        "reply_malformed",
        "sandbox_unavailable",
        "sandbox_error",
        "no_description",
        "program_syntax_error",
        "program_error",
        "module_not_available",
        "figure_too_large",
    ),
    "figure": ("no_figure", "multiple_figures", "glyph_missing"),
    "parts": (
        "raster_image",
        "axes_not_judged",
        "axes_twin",
        "axes_overlap",
        "artist_not_judged",
        "no_data",
    ),
    "axes": (
        "mark_not_in_data",
        "scale_not_linear",
        "axis_inverted",
        "zero_not_in_limits",
        "tick_label_mismatch",
        "point_clipped",
    ),
    "marks": (
        "mark_hidden",
        "value_not_finite",
        "bar_not_from_zero",
        "bars_overlap",
        "x_not_ordered",
        "hist_counts",
        "pie_not_whole",
        "area_not_from_zero",
        "marker_size_varies",
        "marker_color_varies",
        "legend_mismatch",
    ),
    "values": (
        "csv_too_large",
        "csv_not_parsable",
        "work_budget_exceeded",
        "category_not_unique",
        "value_not_found",
        "label_not_in_request",
    ),
    "columns": ("column_not_requested", "column_not_named", "label_not_consistent"),
    "attach": ("no_image", "publish_failed"),
}
CHECK_OF: Final[dict[Reason, Check]] = {
    reason: check for check, reasons in _REASONS_OF.items() for reason in reasons
}

# check -> ((EN title, EN covers), (JA title, JA covers)).
TEXTS: Final[dict[Check, tuple[tuple[str, str], tuple[str, str]]]] = {
    "program": (
        ("Chart program received from the model", "one program, sent through the chart tool"),
        ("モデルからグラフのプログラムを受信", "グラフ用のツールで送られた 1 つのプログラム"),
    ),
    "run": (
        (
            "Program run in your browser",
            "the program runs unchanged in the Open WebUI sandbox and finishes without an error",
        ),
        (
            "ブラウザでプログラムを実行",
            "プログラムを変更せずに Open WebUI のサンドボックスで実行し、エラーなく終了",
        ),
    ),
    "figure": (
        ("One figure drawn", "one matplotlib figure, every character drawable"),
        ("図を 1 つ描画", "matplotlib の図が 1 つ、すべての文字を描画可能"),
    ),
    "parts": (
        (
            "Only chart parts the verifier checks",
            "plain axes with bars, lines, points, histograms, pies, areas, reference lines and"
            " text; no images, second axes or overlapping panels",
        ),
        (
            "検証器がチェックできる部品だけを使用",
            "通常の軸と、棒、折れ線、点、ヒストグラム、円、面、基準線、テキスト。"
            "画像、2 つ目の軸、重なるパネルはなし",
        ),
    ),
    "axes": (
        (
            "Honest axes",
            "marks at their values, linear or named log scales, no inverted axis, zero on bar"
            " and area axes, true tick labels, all points inside",
        ),
        (
            "正しい軸",
            "データの値の位置に描画、線形または明記した対数、反転なし、棒と面の軸にゼロ、"
            "正しい目盛りラベル、範囲外の点なし",
        ),
    ),
    "marks": (
        (
            "Honest marks",
            "visible finite values, bars and areas from zero, no overlapping bars, true"
            " histograms and pies, ordered lines, keyed sizes and colors, a true legend",
        ),
        (
            "正しいグラフ要素",
            "見える有限の値、ゼロから始まる棒と面、重ならない棒、正しいヒストグラムと円、"
            "順序どおりの折れ線、凡例のある大きさと色、正しい凡例",
        ),
    ),
    "values": (
        (
            "Drawn values come from your data",
            "each value is in your CSV file, one summary per group of it, or a number in your"
            " request; each category once",
        ),
        (
            "描画した値があなたのデータにある",
            "各値が CSV ファイルの値、そのグループごとの集計、または依頼文の数値。"
            "カテゴリの重複なし",
        ),
    ),
    "columns": (
        (
            "Drawn columns match your request",
            "no drawn column replaces a column your request names; labels name only drawn columns",
        ),
        (
            "描いた列が依頼と一致",
            "依頼にある列を別の列に置き換えない。ラベルは描いた列だけを挙げる",
        ),
    ),
    "attach": (
        ("Image attached to the reply", "one PNG image, stored with this reply"),
        ("返信に画像を添付", "PNG 画像 1 枚をこの返信と一緒に保存"),
    ),
}
# The columns row under production's strict anchoring (Q37); TEXTS holds the demo's rule.
STRICT_COLUMNS: Final[tuple[tuple[str, str], tuple[str, str]]] = (
    (
        "Drawn columns match your request",
        "if your request names a column, it names every drawn column; labels name only drawn"
        " columns",
    ),
    (
        "描いた列が依頼と一致",
        "依頼が列名を含む場合は、描いた列をすべて含む。ラベルは描いた列だけを挙げる",
    ),
)

# (EN, JA) per UI word.
SHOW: Final = ("Show checks", "チェック項目を表示")
HIDE: Final = ("Hide checks", "チェック項目を隠す")
UNRUN: Final = ("not checked", "未実施")
MARKS: Final[dict[_State, tuple[str, tuple[str, str]]]] = {
    "pass": ("\N{CHECK MARK}", ("passed", "合格")),
    "fail": ("\N{BALLOT X}", ("failed", "不合格")),
    "skip": ("\N{EN DASH}", UNRUN),
}

# check -> (EN, JA): what the check does, shown when its row is opened.
EXPLAIN: Final[dict[Check, tuple[str, str]]] = {
    "program": (
        "The model must send its chart program through the chart tool. The verifier checks the"
        " last program sent in this reply.",
        "モデルはグラフのプログラムをグラフ用のツールで送る必要があります。"
        "検証器は、この返信で最後に送られたプログラムをチェックします。",
    ),
    "run": (
        "Your browser runs the model's program, unchanged, in the Open WebUI sandbox. The program"
        " must finish without an error, and the run reports the figure that it drew.",
        "ブラウザは、モデルのプログラムを変更せずに Open WebUI のサンドボックスで実行します。"
        "プログラムはエラーなく終了し、実行結果として描いた図を報告する必要があります。",
    ),
    "figure": (
        "The program must draw exactly one matplotlib figure. Charts from pandas are matplotlib"
        " figures too. The available fonts must draw every character of its text.",
        "プログラムは matplotlib の図をちょうど 1 つ描く必要があります。"
        "pandas のグラフも matplotlib の図です。"
        "使用できるフォントで、図のすべての文字を描ける必要があります。",
    ),
    "parts": (
        "Each part of the figure must be a kind that the verifier checks. These are plain axes,"
        " bars, lines, points, histograms, pies, filled areas, reference lines and text. Images,"
        " polar or 3D axes, a second y axis and overlapping panels stop the figure.",
        "図の各部品は、検証器がチェックできる種類である必要があります。"
        "通常の軸、棒、折れ線、点、ヒストグラム、円、面、基準線、テキストです。"
        "画像、極座標や 3D の軸、2 つ目の y 軸、重なるパネルがあると、図は表示されません。",
    ),
    "axes": (
        "Each axis must show the data honestly. Marks sit at their data values, scales are"
        " linear unless an axis label or title names a log scale, and no axis is inverted. Bar,"
        " histogram and area axes include zero, each tick label shows the value at its position,"
        " and no data point is outside the axis limits.",
        "各軸はデータを正しく示す必要があります。"
        "グラフ要素はデータの値の位置にあり、軸ラベルかタイトルが対数と明記しない限り目盛りは線形で、"
        "反転した軸はありません。"
        "棒グラフ、ヒストグラム、面グラフの軸はゼロを含み、各目盛りのラベルはその位置の値を示し、"
        "軸の範囲の外にデータ点はありません。",
    ),
    "marks": (
        "Each mark must show its values honestly. Bars and filled areas start at zero or on"
        " another bar or area, bars do not overlap, and histograms and pies match their data."
        " Lines run in one direction, varying sizes and colors have a legend or color bar, and"
        " the legend names the series.",
        "各グラフ要素は値を正しく示す必要があります。"
        "棒と面はゼロまたは他の棒や面から始まり、棒は重ならず、ヒストグラムと円はデータと一致します。"
        "折れ線は一方向に進み、異なる大きさや色には凡例かカラーバーがあり、凡例は系列を正しく示します。",
    ),
    "values": (
        "Each drawn value must come from your data. It is a value in your CSV file or a number in"
        " your request. It can also be one total, mean, minimum, maximum or row count per group"
        " of the file. Category labels come from the same rows or from your request.",
        "描画した各値は、あなたのデータにある必要があります。"
        "CSV ファイルの値、そのグループごとの合計、平均、最小値、最大値、行数、"
        "または依頼文の数値です。"
        "カテゴリのラベルは、同じ行または依頼文にある必要があります。",
    ),
    "columns": (
        "When your request names columns, the chart must draw those columns. A title, axis label"
        " or legend must not name a column or summary that the chart does not draw.",
        "依頼文に列名がある場合、グラフはその列を描く必要があります。"
        "タイトル、軸ラベル、凡例は、グラフが描いていない列や集計を挙げてはいけません。",
    ),
    "attach": (
        "The run returns one PNG image, and Open WebUI stores it with this reply. If either"
        " step fails, the verifier shows no image.",
        "実行結果として PNG 画像が 1 枚返り、Open WebUI がそれをこの返信と一緒に保存します。"
        "どちらかに失敗した場合、検証器は画像を表示しません。",
    ),
}
WHAT: Final = ("What this check does", "このチェックの内容")
CODE: Final = ("Program", "プログラム")
WHY: Final = ("Why it failed", "不合格の理由")
NOT_RUN: Final = (
    "This check did not run, because an earlier check failed.",
    "前のチェックが不合格だったため、このチェックは実施していません。",
)
DREW: Final = (
    "The marked line drew the part, or made the call, that failed this check.",
    "印の付いた行が、このチェックで不合格になった部分を描いたか、その呼び出しを行いました。",
)
SPEC: Final = ("Read the full specification of this check", "このチェックの詳しい仕様を読む")
ELIDED: Final = ("Lines not shown: {n}.", "表示していない行: {n} 行。")
BEYOND: Final = (
    "The program is too long to show in full.",
    "プログラムが長すぎるため、すべては表示できません。",
)
# The python-mode reference on GitHub, one section per check (`#check-<id>`). A fixed link: the
# instance may have no network, but the browser a user reads it in does (user ruling, M18).
SPECIFICATION: Final = (
    "https://github.com/eturkes/figure-verification/blob/main/docs/verification.md",
    "https://github.com/eturkes/figure-verification/blob/main/docs/verification.ja.md",
)


@dataclass(frozen=True, slots=True)
class Evidence:
    """The program the outlet ran and the line the judge's failure points at (display only).
    Empty = no program reached the outlet."""

    program: str | None = None
    site: int | None = None


# The frame cannot see Open WebUI's theme class, so every colour is a mid tone that reads on the
# light and the dark theme alike; a `prefers-color-scheme` rule would pick the wrong extreme when
# the theme and the OS disagree.
_STYLE = (
    "body{margin:0;color:#7d7d7d;font:14px/1.45 ui-sans-serif,system-ui,-apple-system,"
    '"Segoe UI",Roboto,"Noto Sans JP","Hiragino Sans",sans-serif}'
    "#r{padding:2px 0}"
    "#r>details>summary{cursor:pointer;width:max-content;user-select:none}"
    "#r>details[open]>summary .show,#r>details:not([open])>summary .hide{display:none}"
    "ol{list-style:none;margin:6px 0 0;padding:0}"
    "li{padding:3px 0}"
    ".row>summary{display:flex;gap:8px;cursor:pointer;list-style:none}"
    ".row>summary::before{content:'\\25B8';flex:none;width:.8em}"
    ".row[open]>summary::before{content:'\\25BE'}"
    ".mark{flex:none;width:1.1em;text-align:center;font-weight:700}"
    ".pass .mark{color:#2a9354}"
    ".fail .mark,.cause{color:#d64541}"
    ".title{font-weight:500}"
    ".covers,.unrun,.more{font-size:12.5px}"
    ".skip{opacity:.7}"
    ".more{margin:2px 0 8px 2.6em}"
    ".more p{margin:2px 0}"
    ".label{display:block;font-weight:600;margin-top:6px}"
    ".listing{margin:4px 0;padding:6px 8px;border-radius:6px;background:rgba(125,125,125,.12);"
    'font:12px/1.5 ui-monospace,Menlo,Consolas,"Noto Sans Mono CJK JP",monospace;'
    "white-space:pre-wrap;overflow-wrap:anywhere}"
    ".line,.gap{display:block}"
    ".ln{display:inline-block;min-width:2.4em;padding-right:8px;text-align:right;opacity:.7;"
    "user-select:none}"
    ".at{background:rgba(214,69,65,.14)}"
    "mark{background:rgba(214,69,65,.38);color:inherit;border-radius:2px}"
    "a.spec{color:#3d8bd9}"
)
# Open WebUI sizes an embed only from the frame's own `iframe:height` message, since the sandbox
# denies it access to the frame's document.
_HEIGHT_SCRIPT = (
    'const r=document.getElementById("r");'
    "new ResizeObserver(()=>parent.postMessage("
    '{type:"iframe:height",height:Math.ceil(r.getBoundingClientRect().height)},"*")'
    ").observe(r);"
)


def _text(value: str) -> str:
    return html.escape(value, quote=True)


# A listing reads at most this much of the program, so a huge receipt costs bounded work; past it,
# the row says the program is not shown in full.
_SCAN = 65_536
_MAX_LINES = 60
_MAX_CHARACTERS = 3_000
_LINE_CHARACTERS = 400
_CONTEXT = 2
_BREAK = re.compile(r"\r\n|\r|\n")
_HIDDEN = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
# Open WebUI injects Alpine.js or Chart.js into an embed whose raw text holds `x-<directive>`,
# `new Chart(` or `Chart.` (same-origin frames). Character references keep the program from
# spelling one, or a resource reference (`src=`, `url(`, `@import`, `https:`) a static check could
# mistake for a load; the browser shows the same characters.
_TRIGGER_SAFE = str.maketrans(
    {"-": "&#45;", ".": "&#46;", "(": "&#40;", ":": "&#58;", "=": "&#61;", "@": "&#64;"}
)


def _visible(character: str) -> str:
    """A character that would draw nothing, or reorder the text around it, as a visible symbol."""
    if character == "\t" or unicodedata.category(character) not in _HIDDEN:
        return character
    code = ord(character)
    if code < 0x20:  # noqa: PLR2004 - the C0 controls map onto U+2400-U+241F
        return chr(0x2400 + code)
    return "\N{SYMBOL FOR DELETE}" if code == 0x7F else "\N{REPLACEMENT CHARACTER}"  # noqa: PLR2004


def _code(value: str) -> str:
    return _text("".join(map(_visible, value))).translate(_TRIGGER_SAFE)


def _line(number: int, line: str, *, marked: bool) -> str:
    shown = _code(line[:_LINE_CHARACTERS])
    if marked and shown:
        shown = f"<mark>{shown}</mark>"
    if len(line) > _LINE_CHARACTERS:
        shown += "\N{HORIZONTAL ELLIPSIS}"
    kind = "line at" if marked else "line"
    return (
        f'<span class="{kind}"><span class="ln">{number}</span><span class="src">{shown}</span>'
        "</span>"
    )


def _listing(program: str, site: int | None, language: int) -> tuple[str, bool]:
    """The program's lines within the caps, the `site` line first and marked with its context;
    and whether a mark is shown."""
    lines = _BREAK.split(program[:_SCAN])
    marked = site if site is not None and 1 <= site <= len(lines) else None
    near = [] if marked is None else [marked + d for d in range(-_CONTEXT, _CONTEXT + 1)]
    taken: set[int] = set()
    cost = 0
    for number in (*near, *range(1, len(lines) + 1)):
        if not 1 <= number <= len(lines) or number in taken:
            continue
        weight = min(len(lines[number - 1]), _LINE_CHARACTERS)
        if len(taken) == _MAX_LINES or cost + weight > _MAX_CHARACTERS:
            continue
        taken.add(number)
        cost += weight
    rows: list[str] = []
    for number in sorted(taken):
        if rows and number - 1 not in taken:
            rows.append('<span class="gap">\N{VERTICAL ELLIPSIS}</span>')
        rows.append(_line(number, lines[number - 1], marked=number == marked))
    listing = f'<pre class="listing">{"".join(rows)}</pre>'
    if len(lines) > len(taken):
        elided = ELIDED[language].format(n=len(lines) - len(taken))
        listing += f'<p class="elided">{_text(elided)}</p>'
    if len(program) > _SCAN:
        listing += f'<p class="beyond">{_text(BEYOND[language])}</p>'
    return listing, marked in taken


def _section(kind: str, label: str, body: str) -> str:
    return f'<div class="{kind}"><span class="label">{_text(label)}</span>{body}</div>'


def _more(
    check: Check, state: _State, reason: Reason | None, language: int, evidence: Evidence
) -> str:
    """The opened row: what the check does, whether it ran, the program, why, the link."""
    sections = [_section("what", WHAT[language], f"<p>{_text(EXPLAIN[check][language])}</p>")]
    if state == "skip":
        sections.append(f'<div class="unrun-note"><p>{_text(NOT_RUN[language])}</p></div>')
    quoted = state == "fail" or (check == "program" and state == "pass")
    drew = False
    if quoted and evidence.program is not None:
        site = evidence.site if state == "fail" else None
        listing, drew = _listing(evidence.program, site, language)
        sections.append(_section("code", CODE[language], listing))
    if reason is not None and state == "fail":
        why = f"<p>{_text(f'{REASONS[reason][language]} ({reason})')}</p>"
        if drew:
            why += f'<p class="drew">{_text(DREW[language])}</p>'
        sections.append(_section("why", WHY[language], why))
    href = _code(f"{SPECIFICATION[language]}#check-{check}")
    sections.append(
        f'<p class="link"><a class="spec" href="{href}" target="_blank"'
        f' rel="noopener noreferrer">{_text(SPEC[language])}</a></p>'
    )
    return f'<div class="more">{"".join(sections)}</div>'


def breakdown_html(
    reason: Reason | None,
    *,
    japanese: bool,
    anchoring: Anchoring,
    evidence: Evidence = Evidence(),  # noqa: B008 - frozen, so one shared default is safe
) -> str:
    """Render every check for one reply: passed, the failing one with its cause, the unrun rest.

    `reason` is the failure reason, or `None` for a published figure, whose checks all passed;
    `anchoring` picks the columns row's text, so each artifact describes the rule it runs;
    `evidence` = the program + the line the failure points at.
    """
    language = 1 if japanese else 0
    failing = len(CHECKS) if reason is None else CHECKS.index(CHECK_OF[reason])
    cause = "" if reason is None else REASONS[reason][language]
    rows: list[str] = []
    for index, check in enumerate(CHECKS):
        state: _State = "pass" if index < failing else "fail" if index == failing else "skip"
        glyph, labels = MARKS[state]
        texts = STRICT_COLUMNS if check == "columns" and anchoring == "strict" else TEXTS[check]
        title, covers = texts[language]
        unrun = f' <span class="unrun">{_text(UNRUN[language])}</span>' if state == "skip" else ""
        detail = f'<div class="covers">{_text(covers)}</div>'
        if state == "fail":
            detail += f'<div class="cause">{_text(cause)}</div>'
        rows.append(
            f'<li class="{state}"><details class="row"><summary><span class="mark" role="img"'
            f' aria-label="{_text(labels[language])}">{glyph}</span>'
            f'<div><div class="title">{_text(title)}{unrun}</div>{detail}</div></summary>'
            f"{_more(check, state, reason, language, evidence)}</details></li>"
        )
    return (
        f'<!DOCTYPE html><html lang="{"ja" if japanese else "en"}"><head><meta charset="utf-8">'
        f'<style>{_STYLE}</style></head><body><div id="r"><details><summary>'
        f'<span class="show">{_text(SHOW[language])}</span>'
        f'<span class="hide">{_text(HIDE[language])}</span></summary>'
        f"<ol>{''.join(rows)}</ol></details></div><script>{_HEIGHT_SCRIPT}</script></body></html>"
    )
'''

_SOURCES["verifier.figure.shapes"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""What each judged mark draws, read off the reader's geometry: coordinates, bars, bands, colour.

Shared by the axes, mark, legend and value stages, so every stage reads one mark the same way.
`Mark.horizontal` = the mark's value lies on x (barh, a horizontal hist, an axvline/axvspan).
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, cast

from verifier.figure.description import (
    Axes,
    BandArrays,
    BandGeometry,
    LineGeometry,
    PolygonGeometry,
    RectGeometry,
    ScatterGeometry,
    WedgeGeometry,
)
from verifier.figure.parts import Mark, Panel

type Coordinate = tuple[int, float, int | None]  # (dimension 0 = x / 1 = y, value, artist line)
type RGB = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class Bar:
    """One bar read by orientation: where it sits on the key axis and how far it reaches."""

    index: int
    key: float  # start on the key axis
    thickness: float
    base: float
    extent: float  # signed length along the value axis

    @property
    def center(self) -> float:
        return self.key + self.thickness / 2

    @property
    def end(self) -> float:
        return self.base + self.extent


def bars(axes: Axes, mark: Mark) -> list[Bar]:
    """The mark's rectangles, by orientation; a bar or hist mark holds rectangles alone."""
    found: list[Bar] = []
    for index in mark.artists:
        rect = cast("RectGeometry", axes.artists[index].geometry)
        if mark.horizontal:
            found.append(Bar(index, rect.y, rect.height, rect.x, rect.width))
        else:
            found.append(Bar(index, rect.x, rect.width, rect.y, rect.height))
    return found


def _reference(axes: Axes, mark: Mark) -> Iterator[Coordinate]:
    """A reference mark's data coordinates, on its data dimension alone."""
    artist = axes.artists[mark.artists[0]]
    dimension = 0 if mark.horizontal else 1
    geometry = artist.geometry
    if isinstance(geometry, LineGeometry):
        values = geometry.x if dimension == 0 else geometry.y
        yield from ((dimension, value, artist.site) for value in values)
    elif isinstance(geometry, RectGeometry):
        start = geometry.x if dimension == 0 else geometry.y
        extent = geometry.width if dimension == 0 else geometry.height
        yield dimension, start, artist.site
        yield dimension, start + extent, artist.site
    else:  # matplotlib 3.8 (the sandbox) draws a span as a Polygon
        polygon = cast("PolygonGeometry", geometry)
        yield from ((dimension, pair[dimension], artist.site) for pair in polygon.xy)


def _line_pairs(geometry: LineGeometry) -> list[tuple[float, float]]:
    return list(zip(geometry.x, geometry.y, strict=True))


def _scatter_pairs(geometry: ScatterGeometry) -> list[tuple[float, float]]:
    return list(geometry.offsets)


def _rect_pairs(geometry: RectGeometry) -> list[tuple[float, float]]:
    return [(geometry.x, geometry.y), (geometry.x + geometry.width, geometry.y + geometry.height)]


def _wedge_pairs(geometry: WedgeGeometry) -> list[tuple[float, float]]:
    radius = geometry.r
    return [
        (geometry.cx - radius, geometry.cy - radius),
        (geometry.cx + radius, geometry.cy + radius),
    ]


def _band_pairs(geometry: BandGeometry) -> list[tuple[float, float]]:
    return [pair for path in geometry.paths for pair in path]


# Judged family -> how its geometry spans the axes (a reference reads its data dimension alone).
_PAIRS: dict[str, Callable[[Any], list[tuple[float, float]]]] = {
    "line": _line_pairs,
    "scatter": _scatter_pairs,
    "bar": _rect_pairs,
    "hist": _rect_pairs,
    "pie": _wedge_pairs,
    "band": _band_pairs,
}


def coordinates(axes: Axes, mark: Mark) -> Iterator[Coordinate]:
    """Every data coordinate the mark draws: what clipping and finiteness read."""
    if mark.family == "reference":
        yield from _reference(axes, mark)
        return
    for index in mark.artists:
        artist = axes.artists[index]
        for x, y in _PAIRS[mark.family](artist.geometry):
            yield 0, x, artist.site
            yield 1, y, artist.site


type Edges = tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]  # x, base, far


def band_edges(axes: Axes, panel: Panel) -> dict[int, Edges]:
    """Each GROUNDED band's (x, base edge, far edge): its base is all zero, or exactly the far
    edge of a grounded band at the same x. Bands that only rest on each other ground nothing."""
    arrays = {
        mark.artists[0]: cast(
            "BandArrays", cast("BandGeometry", axes.artists[mark.artists[0]].geometry).band
        )
        for mark in panel.marks
        if mark.family == "band"
    }
    grounded: dict[int, Edges] = {}
    changed = True
    while changed:
        changed = False
        for index, band in arrays.items():
            if index in grounded:
                continue
            tops = [far for other, (x, _base, far) in grounded.items() if x == band.x]
            for base, far in ((band.y2, band.y1), (band.y1, band.y2)):
                if all(value == 0.0 for value in base) or base in tops:
                    grounded[index] = (band.x, base, far)
                    changed = True
                    break
    return grounded


def color(axes: Axes, mark: Mark) -> RGB | None:
    """A series mark's own colour, as a legend handle shows it (RGB; alpha is presentation)."""
    geometry = axes.artists[mark.artists[0]].geometry
    if isinstance(geometry, ScatterGeometry):
        rgba = geometry.colors[0] if geometry.colors else None
    else:
        rgba = cast("LineGeometry | RectGeometry | BandGeometry", geometry).color
    return None if rgba is None else rgba[:3]


def label(axes: Axes, mark: Mark) -> str:
    """The mark's own label: its container's for bars, else its artist's."""
    if mark.container is not None:
        return axes.containers[mark.container].label
    return axes.artists[mark.artists[0]].label


def series_marks(panel: Panel) -> list[Mark]:
    """The marks a legend may name as series: every family but pies and reference marks."""
    return [mark for mark in panel.marks if mark.family not in ("pie", "reference")]
'''

_SOURCES["verifier.figure.sources"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The user's data, read once: each attached CSV under the pandas-equal profile (ruling 4).

`verifier.pysrc.csvread` owns the profile: a cell pandas would parse differently from stdlib
`float` makes its column unusable as numbers here, so no explanation reads it as a value (its text
can still be a key). A file the profile refuses whole carries its refusal code instead of a table.
"""

from dataclasses import dataclass
from typing import cast

from verifier.figure.reasons import FigureReason
from verifier.pysrc.budget import WorkBudget, WorkBudgetExceededError
from verifier.pysrc.csvread import (
    _check_selected_text,
    _classify_column,
    _numeric_values,
    _read_csv,
    key_values,
)
from verifier.pysrc.errors import PysrcRefusalError
from verifier.pysrc.limits import DEFAULT_LIMITS
from verifier.pysrc.table import CellValue


@dataclass(frozen=True, slots=True)
class Column:
    """One CSV column: its cells as text, as group keys, and as numbers when the profile allows."""

    name: str
    texts: tuple[str, ...]
    keys: tuple[CellValue, ...]
    numbers: tuple[float, ...] | None
    integer: bool


@dataclass(frozen=True, slots=True)
class Table:
    """One attached CSV, as the program reads it with plain `pd.read_csv`."""

    name: str
    header: tuple[str, ...]
    columns: tuple[Column, ...]
    content: bytes

    @property
    def rows(self) -> int:
        return len(self.columns[0].texts)


@dataclass(frozen=True, slots=True)
class Unreadable:
    """An attached file the profile refuses whole; its code explains an unexplained value."""

    name: str
    code: FigureReason  # csv_too_large | csv_not_parsable | work_budget_exceeded


def _column(name: str, texts: tuple[str, ...]) -> Column:
    try:
        for text in texts:
            _check_selected_text(text)
        numbers = _numeric_values(texts) if _classify_column(texts) == "numeric" else None
    except PysrcRefusalError:
        numbers = None
    try:
        keys = key_values(texts)
    except PysrcRefusalError:
        keys = texts
    integer = numbers is not None and not any("." in text for text in texts)
    return Column(name, texts, keys, numbers, integer)


def read_table(name: str, content: bytes) -> Table | Unreadable:
    """Read one attachment; a whole-file refusal becomes `Unreadable` with its code."""
    try:
        header, rows = _read_csv(content, DEFAULT_LIMITS, WorkBudget(DEFAULT_LIMITS.max_work))
    except PysrcRefusalError as refusal:
        return Unreadable(name, cast("FigureReason", refusal.code))
    except WorkBudgetExceededError:
        return Unreadable(name, "work_budget_exceeded")
    columns = tuple(
        _column(column, tuple(row[index] for row in rows)) for index, column in enumerate(header)
    )
    return Table(name, header, columns, content)
'''

_SOURCES["verifier.figure.axes_rules"] = r'''
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
'''

_SOURCES["verifier.figure.legends"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Legend ↔ artists (`legend_mismatch`), each series' displayed name, and each encoding key.

An entry names a judged mark by handle (the artist or container itself, in any axes of the
figure), or as a proxy by a mark's own label + colour (an axes legend: in its axes; a figure
legend: anywhere). A `legend_elements` key names no series: it explains its collection's sizes or
colours. With ≥ 2 series (lines, points, bars, areas) in a legended axes, every one is named;
pies and reference marks may stay unnamed.
"""

from dataclasses import dataclass, field

from verifier.figure.description import Legend, LegendEntry
from verifier.figure.parts import Mark, Panel
from verifier.figure.reasons import block
from verifier.figure.shapes import RGB, color, label, series_marks

type Names = dict[tuple[int, int], str]  # (panel position, the named artist) -> its name


@dataclass(frozen=True, slots=True)
class Legends:
    """What the figure's legends say: the names of drawn marks, and the encodings they explain."""

    names: Names = field(default_factory=dict)
    # (figure axes index, scatter artist, "sizes" | "colors")
    encodings: frozenset[tuple[int, int, str]] = frozenset()


type _Candidate = tuple[int, Mark, str, RGB | None]  # (panel position, mark, own label, colour)


def _candidates(panels: tuple[Panel, ...], positions: list[int]) -> list[_Candidate]:
    return [
        (position, mark, label(panels[position].axes, mark), color(panels[position].axes, mark))
        for position in positions
        for mark in panels[position].marks
        if mark.family != "pie"
    ]


def _handle(
    entry: LegendEntry, panels: tuple[Panel, ...], by_axes: dict[int, int]
) -> tuple[int, int] | None:
    """(panel position, named artist) of a handle the reader found drawn, if it is judged."""
    position = by_axes.get(entry.axes) if entry.axes is not None else None
    if position is None:
        return None
    for mark in panels[position].marks:
        if entry.target is not None and entry.target in mark.artists:
            return position, entry.target
        if entry.container is not None and mark.container == entry.container:
            return position, mark.artists[0]
    return None


def _proxy(entry: LegendEntry, candidates: list[_Candidate]) -> tuple[int, int] | None:
    rgb = None if entry.proxy_color is None else entry.proxy_color[:3]
    matches = [
        (position, mark.artists[0])
        for position, mark, own_label, own in candidates
        if rgb is not None and own_label == entry.text and own == rgb
    ]
    return matches[0] if len(matches) == 1 else None


def _encoding(
    entry: LegendEntry, panels: tuple[Panel, ...], by_axes: dict[int, int]
) -> tuple[int, int, str] | None:
    keyed = entry.elements_of
    if keyed is None or keyed[0] is None or entry.axes is None or entry.axes not in by_axes:
        return None
    panel = panels[by_axes[entry.axes]]
    if not any(m.family == "scatter" and m.artists[0] == keyed[0] for m in panel.marks):
        return None
    return entry.axes, keyed[0], keyed[1]


def _read(
    legend: Legend,
    panels: tuple[Panel, ...],
    by_axes: dict[int, int],
    candidates: list[_Candidate],
) -> tuple[Names, set[tuple[int, int, str]]]:
    names: Names = {}
    encodings: set[tuple[int, int, str]] = set()
    for entry in legend.entries:
        if entry.elements_of is not None:
            encoding = _encoding(entry, panels, by_axes)
            if encoding is None:
                block("legend_mismatch", legend.site)
            encodings.add(encoding)
            continue
        named = (
            _handle(entry, panels, by_axes)
            if entry.target is not None or entry.container is not None
            else _proxy(entry, candidates)
        )
        if named is None or named in names:
            block("legend_mismatch", legend.site)
        names[named] = entry.text
    return names, encodings


def read_legends(panels: tuple[Panel, ...], figure_legends: tuple[Legend, ...]) -> Legends:
    by_axes = {panel.index: position for position, panel in enumerate(panels)}
    names: Names = {}
    encodings: set[tuple[int, int, str]] = set()
    for position, panel in enumerate(panels):
        legend = panel.axes.legend
        if legend is None:
            continue
        found, keys = _read(legend, panels, by_axes, _candidates(panels, [position]))
        names |= found
        encodings |= keys
        series = series_marks(panel)
        named = [mark for mark in series if (position, mark.artists[0]) in found]
        if named and len(series) >= 2 and len(named) != len(series):  # noqa: PLR2004
            block("legend_mismatch", legend.site)
    everywhere = _candidates(panels, list(range(len(panels))))
    for legend in figure_legends:
        found, keys = _read(legend, panels, by_axes, everywhere)
        names |= found
        encodings |= keys
    return Legends(names, frozenset(encodings))
'''

_SOURCES["verifier.figure.mark_rules"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Mark rules over one judged panel (`.claude/rules/figure.md` § Mark rules).

Order (`.agent/archive/contracts/m19u3.md` U2): `mark_hidden` → `value_not_finite` → bars
(`bar_not_from_zero`, `bars_overlap`) → `x_not_ordered` → `hist_counts` → `pie_not_whole` →
`area_not_from_zero` → scatter encodings. Each block marks the line that drew the offending mark.
"""

import itertools
import math
from typing import Final, cast

from verifier.figure.description import (
    Axes,
    BandGeometry,
    Geometry,
    HistRecord,
    LineGeometry,
    PieRecord,
    PolygonGeometry,
    RectGeometry,
    ScatterGeometry,
    WedgeGeometry,
)
from verifier.figure.parts import Mark, Panel
from verifier.figure.reasons import block
from verifier.figure.shapes import Bar, band_edges, bars, coordinates

_TOLERANCE: Final = 1e-9
# matplotlib computes wedge angles in float32 (`np.asarray(x, np.float32)` in `Axes.pie`).
_PIE_DEGREES: Final = 1e-4


def _site(axes: Axes, mark: Mark) -> int | None:
    return axes.artists[mark.artists[0]].site


def _near(a: float, b: float) -> bool:
    return abs(a - b) <= _TOLERANCE * max(1.0, abs(a), abs(b))


def _record_values(axes: Axes, mark: Mark) -> list[float]:
    """Inputs a mark received besides its geometry: hist inputs + edges, pie values."""
    if mark.container is not None:
        record = axes.containers[mark.container].hist
        return [] if record is None else [*record.values, *record.bins]
    return [] if mark.pie is None else list(axes.pies[mark.pie].values)


_NO_LINE: Final = frozenset({"None", "none", "", " "})


def _clear(rgba: tuple[float, ...] | None) -> bool:
    return rgba is None or rgba[3] == 0.0


def _cycled[T](values: tuple[T, ...], index: int) -> T | None:
    """matplotlib cycles a collection's per-point properties over its points."""
    return values[index % len(values)] if values else None


def _point_ink(geometry: ScatterGeometry, index: int) -> bool:
    """Whether scatter point `index` draws any ink: a size above zero, and a visible face or a
    visible edge of nonzero width."""
    face = _cycled(geometry.colors, index)
    edge = _cycled(geometry.edges, index)
    width = _cycled(geometry.linewidths, index)
    return bool(_cycled(geometry.sizes, index)) and (
        (face is not None and not _clear(face))
        or (edge is not None and not _clear(edge) and bool(width))
    )


def _no_ink(geometry: Geometry) -> bool:
    """The artist's final styling draws nothing: transparent, no line and no marker, zero size."""
    if isinstance(geometry, LineGeometry):
        line = not (
            geometry.linestyle in _NO_LINE or geometry.linewidth == 0.0 or _clear(geometry.color)
        )
        marker = not (
            geometry.marker in _NO_LINE
            or geometry.markersize == 0.0
            or (_clear(geometry.marker_face) and _clear(geometry.marker_edge))
        )
        return not line and not marker
    if isinstance(geometry, ScatterGeometry):
        return any(not _point_ink(geometry, index) for index in range(len(geometry.offsets)))
    patch = cast("RectGeometry | WedgeGeometry | PolygonGeometry | BandGeometry", geometry)
    return _clear(patch.color) and (_clear(patch.edge) or patch.linewidth == 0.0)


def _check_drawn(axes: Axes, panel: Panel) -> None:
    """What a mark receives but does not show: a hidden panel or artist, a non-finite value."""
    if not axes.visible:
        block("mark_hidden", axes.site)
    for mark in panel.marks:
        for index in mark.artists:
            artist = axes.artists[index]
            if not artist.visible or artist.alpha == 0.0 or _no_ink(artist.geometry):
                block("mark_hidden", artist.site)
    for mark in panel.marks:
        values = [value for _, value, _ in coordinates(axes, mark)] + _record_values(axes, mark)
        geometry = axes.artists[mark.artists[0]].geometry
        dropped = (
            isinstance(geometry, BandGeometry)
            and geometry.band is not None
            and geometry.inputs != len(geometry.band.x)
        )
        if dropped or not all(math.isfinite(value) for value in values):
            block("value_not_finite", _site(axes, mark))


def _stacked(bar: Bar, every: list[tuple[bool, Bar]], *, horizontal: bool) -> bool:
    """G1 for a bar off zero: it continues another bar at its position, on the same side of 0."""
    same_side = bar.extent == 0.0 or (bar.extent > 0.0) == (bar.base > 0.0)
    return same_side and any(
        other.index != bar.index
        and other_horizontal == horizontal
        and (other.key, other.thickness) == (bar.key, bar.thickness)
        and other.end == bar.base
        for other_horizontal, other in every
    )


def _check_bars(axes: Axes, panel: Panel) -> None:
    every = [
        (mark.horizontal, bar)
        for mark in panel.marks
        if mark.family in ("bar", "hist")
        for bar in bars(axes, mark)
    ]
    for horizontal, bar in every:
        if bar.base != 0.0 and not _stacked(bar, every, horizontal=horizontal):
            block("bar_not_from_zero", axes.artists[bar.index].site)
    boxes = sorted(
        (*_box(cast("RectGeometry", axes.artists[bar.index].geometry)), bar.index)
        for _, bar in every
    )
    for position, (_x0, x1, y0, y1, index) in enumerate(boxes):
        for other_x0, other_x1, other_y0, other_y1, other in boxes[position + 1 :]:
            if other_x0 >= x1 - _TOLERANCE * max(1.0, abs(x1)):
                break
            width = min(x1, other_x1) - other_x0
            height = min(y1, other_y1) - max(y0, other_y0)
            if width > _TOLERANCE * max(1.0, abs(x1)) and height > _TOLERANCE * max(
                1.0, abs(y1), abs(other_y1)
            ):
                block("bars_overlap", axes.artists[max(index, other)].site)  # the later bar


def _box(rect: RectGeometry) -> tuple[float, float, float, float]:
    """A drawn rectangle in data x/y, whatever its orientation."""
    return (
        min(rect.x, rect.x + rect.width),
        max(rect.x, rect.x + rect.width),
        min(rect.y, rect.y + rect.height),
        max(rect.y, rect.y + rect.height),
    )


def _check_order(axes: Axes, panel: Panel) -> None:
    """G9 / ruling 3: a line runs monotone in x, either way."""
    for mark in panel.marks:
        geometry = axes.artists[mark.artists[0]].geometry
        if mark.family == "line" and isinstance(geometry, LineGeometry):
            steps = [b - a for a, b in itertools.pairwise(geometry.x)]
            if any(step < 0 for step in steps) and any(step > 0 for step in steps):
                block("x_not_ordered", _site(axes, mark))


def _counts(record: HistRecord) -> list[int] | None:
    """numpy's histogram over the drawn edges (last bin closed); None when an input falls out."""
    bins = record.bins
    counts = [0] * (len(bins) - 1)
    for value in record.values:
        if not bins[0] <= value <= bins[-1]:
            return None
        index = next(i for i in range(len(counts)) if value < bins[i + 1] or i == len(counts) - 1)
        counts[index] += 1
    return counts


def _hist_ok(axes: Axes, mark: Mark, record: HistRecord) -> bool:
    bins = record.bins
    plain = record.histtype == "bar" and record.datasets == 1
    if not plain or record.weighted or record.cumulative or len(bins) != len(mark.artists) + 1:
        return False
    if any(b <= a for a, b in itertools.pairwise(bins)):
        return False
    counts = _counts(record)
    if counts is None:  # R2: an input the drawn bins leave out
        return False
    total = sum(counts)
    for position, bar in enumerate(bars(axes, mark)):
        low, high = bins[position], bins[position + 1]
        width = high - low
        count = counts[position]
        expected = (count / width) / total if record.density else float(count)
        if not (
            _near(bar.center, (low + high) / 2)
            and bar.thickness <= width * (1 + _TOLERANCE)
            and bar.extent == expected
        ):
            return False
    return True


def _check_hist(axes: Axes, mark: Mark) -> None:
    record = cast("HistRecord", axes.containers[cast("int", mark.container)].hist)
    if not _hist_ok(axes, mark, record):
        block("hist_counts", _site(axes, mark))


def _pie_ok(record: PieRecord, wedges: list[WedgeGeometry]) -> bool:
    total = sum(record.values)
    if len(wedges) != len(record.values) or total <= 0.0:
        return False  # a partial pie (`normalize=False`, total < 1) fails the 360° sum below
    if len({(wedge.r, wedge.width) for wedge in wedges}) != 1:
        return False
    shares = [value / total if record.normalize else value for value in record.values]
    arcs = sorted(
        (wedge.theta1, wedge.theta2, share) for wedge, share in zip(wedges, shares, strict=True)
    )
    for (start, end, share), following in itertools.zip_longest(arcs, arcs[1:]):
        if abs((end - start) - 360.0 * share) > _PIE_DEGREES:
            return False
        if following is not None and abs(following[0] - end) > _PIE_DEGREES:
            return False
    return abs((arcs[-1][1] - arcs[0][0]) - 360.0) <= _PIE_DEGREES


def _check_pie(axes: Axes, mark: Mark) -> None:
    wedges = [cast("WedgeGeometry", axes.artists[i].geometry) for i in mark.artists]
    if not _pie_ok(axes.pies[cast("int", mark.pie)], wedges):
        block("pie_not_whole", _site(axes, mark))


def _check_scatter(
    axes: Axes, mark: Mark, explained: frozenset[tuple[str, ...]], *, colorbar: bool
) -> None:
    """Varying sizes need a size key of this collection; colours, a colorbar or colour key."""
    geometry = cast("ScatterGeometry", axes.artists[mark.artists[0]].geometry)
    if len(set(geometry.sizes)) > 1 and ("sizes",) not in explained:
        block("marker_size_varies", _site(axes, mark))
    if len(set(geometry.colors)) > 1 and ("colors",) not in explained and not colorbar:
        block("marker_color_varies", _site(axes, mark))


def check_marks(
    panel: Panel,
    colorbars: set[tuple[int, int]],
    encodings: frozenset[tuple[int, int, str]],
) -> None:
    """`colorbars` = (axes, artist) pairs a colorbar is linked to; `encodings` = (axes, artist,
    prop) a legend key explains."""
    axes = panel.axes
    grounded = band_edges(axes, panel)
    _check_drawn(axes, panel)
    _check_bars(axes, panel)
    _check_order(axes, panel)
    for mark in panel.marks:
        if mark.family == "hist":
            _check_hist(axes, mark)
        elif mark.family == "pie":
            _check_pie(axes, mark)
        elif mark.family == "band" and mark.artists[0] not in grounded:
            block("area_not_from_zero", _site(axes, mark))
        elif mark.family == "scatter":
            index = mark.artists[0]
            explained = frozenset(
                (prop,)
                for owner, artist, prop in encodings
                if (owner, artist) == (panel.index, index)
            )
            linked = cast("ScatterGeometry", axes.artists[index].geometry).colorbar
            colorbar = linked and (panel.index, index) in colorbars
            _check_scatter(axes, mark, explained, colorbar=colorbar)
'''

_SOURCES["verifier.figure.series"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Every judged mark as the values it shows: keyed points, a value multiset, or reference values.

A series = one line · scatter collection · bar container · pie · area band · histogram's inputs ·
reference mark, plus each scatter channel a colorbar or legend key shows (colour values, sizes:
R8), each channel point carrying its scatter point's key and value. A keyed point pairs the key its
key axis shows with its value. A bar's value is
its height, stacked or not (matplotlib stores the height it was given); an area band point
carries its base edge, since its value = the far edge the stack computed as base + value.
"""

from dataclasses import dataclass
from typing import Literal, cast

from verifier.figure.axes_rules import value_on_x
from verifier.figure.description import (
    Axes,
    LineGeometry,
    PolygonGeometry,
    RectGeometry,
    ScatterGeometry,
    TextGeometry,
)
from verifier.figure.keys import Key, KeyReader
from verifier.figure.legends import Names
from verifier.figure.parts import Mark, Panel
from verifier.figure.shapes import band_edges, bars

type Shape = Literal["keyed", "values", "reference"]
type Channel = Literal["value", "colors", "sizes"]


@dataclass(frozen=True, slots=True)
class Point:
    key: Key
    value: float
    base: float | None = None  # a stacked point: drawn value = far end, base = what it sits on
    partner: float | None = None  # a channel point: its scatter point's value (same row)


@dataclass(frozen=True, slots=True)
class Series:
    panel: int
    mark: Mark
    shape: Shape
    name: str | None
    points: tuple[Point, ...]
    site: int | None
    channel: Channel = "value"


_NO_KEY = Key()


def _name(mark: Mark, position: int, names: Names) -> str | None:
    """The series' displayed name = its legend entry; a label no legend shows names nothing.

    A pie's wedge labels are its keys and a reference mark names no rows: neither is a series.
    """
    if mark.family in ("pie", "reference"):
        return None
    return names.get((position, mark.artists[0]))


def _keyed_points(axes: Axes, panel: Panel, mark: Mark) -> tuple[Point, ...]:
    keys = KeyReader(axes.y if value_on_x(mark) else axes.x)
    artist = axes.artists[mark.artists[0]]
    geometry = artist.geometry
    if mark.family in ("bar", "hist"):
        return tuple(Point(keys.key(bar.center), bar.extent, None) for bar in bars(axes, mark))
    if mark.family == "line":
        line = cast("LineGeometry", geometry)
        return tuple(Point(keys.key(x), y) for x, y in zip(line.x, line.y, strict=True))
    if mark.family == "scatter":
        offsets = cast("ScatterGeometry", geometry).offsets
        return tuple(Point(keys.key(x), y) for x, y in offsets)
    x, base, far = band_edges(axes, panel)[mark.artists[0]]
    return tuple(
        Point(keys.key(at), top, bottom) for at, bottom, top in zip(x, base, far, strict=True)
    )


def _drawn_label(axes: Axes, text: int | None) -> str | None:
    """A wedge label as drawn: its Text's final text, unless removed, hidden or blank."""
    if text is None:
        return None
    artist = axes.artists[text]
    shown = cast("TextGeometry", artist.geometry).text
    return shown if artist.visible and shown.strip() else None


def _pie(axes: Axes, mark: Mark, position: int, names: Names) -> tuple[Shape, tuple[Point, ...]]:
    """A pie's values keyed by each wedge's drawn label, else by the legend entry naming it."""
    record = axes.pies[cast("int", mark.pie)]
    texts = record.texts if len(record.texts) == len(mark.artists) else (None,) * len(mark.artists)
    labels = [
        _drawn_label(axes, text) or names.get((position, wedge))
        for wedge, text in zip(mark.artists, texts, strict=True)
    ]
    if not any(labels):
        return "values", tuple(Point(_NO_KEY, value) for value in record.values)
    return "keyed", tuple(
        Point(_NO_KEY if text is None else Key(text=text), value)
        for text, value in zip(labels, record.values, strict=True)
    )


def _reference(axes: Axes, mark: Mark) -> tuple[Point, ...]:
    """A reference line's value, or a span's two edges, on its data dimension."""
    geometry = axes.artists[mark.artists[0]].geometry
    dimension = 0 if mark.horizontal else 1
    if isinstance(geometry, LineGeometry):
        values: tuple[float, ...] = tuple(sorted(set(geometry.x if dimension == 0 else geometry.y)))
    elif isinstance(geometry, RectGeometry):
        start = geometry.x if dimension == 0 else geometry.y
        extent = geometry.width if dimension == 0 else geometry.height
        values = (start, start + extent)
    else:
        xy = cast("PolygonGeometry", geometry).xy
        values = (min(p[dimension] for p in xy), max(p[dimension] for p in xy))
    return tuple(Point(_NO_KEY, value) for value in values)


def _channels(
    axes: Axes, panel: Panel, mark: Mark, shown: frozenset[tuple[int, int, str]]
) -> list[tuple[Channel, tuple[Point, ...]]]:
    """A scatter's colour values and sizes, each keyed like its points, where a colorbar or a
    legend key shows them (matplotlib cycles a shorter array over the points)."""
    geometry = cast("ScatterGeometry", axes.artists[mark.artists[0]].geometry)
    marks = _keyed_points(axes, panel, mark)
    found: list[tuple[Channel, tuple[Point, ...]]] = []
    for channel, values in (("colors", geometry.array), ("sizes", geometry.sizes)):
        if values and (panel.index, mark.artists[0], channel) in shown:
            points = tuple(
                Point(point.key, values[i % len(values)], partner=point.value)
                for i, point in enumerate(marks)
            )
            found.append((cast("Channel", channel), points))
    return found


def series(
    panels: tuple[Panel, ...], names: Names, shown: frozenset[tuple[int, int, str]]
) -> tuple[Series, ...]:
    """Every judged mark's series; `shown` = (axes, artist, channel) a colorbar (`colors`) or a
    legend key displays."""
    found: list[Series] = []
    for position, panel in enumerate(panels):
        axes = panel.axes
        for mark in panel.marks:
            site = axes.artists[mark.artists[0]].site
            name = _name(mark, position, names)
            if mark.family == "reference":
                shape: Shape = "reference"
                points = _reference(axes, mark)
            elif mark.family == "pie":
                shape, points = _pie(axes, mark, position, names)
            elif mark.family == "hist":
                record = axes.containers[cast("int", mark.container)].hist
                values = record.values if record is not None else ()
                shape, points = "values", tuple(Point(_NO_KEY, v) for v in values)
            else:
                shape = "keyed"
                points = _keyed_points(axes, panel, mark)
            found.append(Series(position, mark, shape, name, points, site))
            if mark.family == "scatter":
                found += (
                    Series(position, mark, "keyed", name, encoded, site, channel)
                    for channel, encoded in _channels(axes, panel, mark, shown)
                )
    return tuple(found)
'''

_SOURCES["verifier.figure.explain"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Explaining the drawn values (ruling 4; R2, R4, R6, R7; `.claude/rules/figure.md` § Values).

The vocabulary is closed: per attached CSV, `raw(K, V)` · `index(V)` (row position) ·
`group(K, V, r)` for r in sum mean min max · `count(K)`; a series whose name is a cell value of a
column C reads the rows holding that value alone (R6). A series takes ONE explanation; a point it
leaves unexplained must be a request number with a key the request typed (per value EITHER).
Matching is injective (a row backs one point) and exact in binary64; a strict subset passes and is
published as N of M (R2). Two explanations over different columns that both explain a series tie;
the request breaks the tie when it names the columns of exactly one (R7), else
`column_not_requested`.
"""

import math
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, cast

from verifier.figure.anchoring import Aliases, AmbiguousTermError, anchors
from verifier.figure.keys import Key
from verifier.figure.reasons import FigureReason
from verifier.figure.request import Request
from verifier.figure.series import Point, Series
from verifier.figure.sources import Column, Table, Unreadable
from verifier.pysrc.aggregate import Reduction, aggregate_series
from verifier.pysrc.budget import WorkBudget, WorkBudgetExceededError
from verifier.pysrc.errors import PysrcRefusalError
from verifier.pysrc.table import CellValue

type Family = Literal["raw", "index", "sum", "mean", "min", "max", "count"]
type Canon = tuple[str, object]

_PREFERENCE: Final[tuple[Family, ...]] = ("raw", "index", "sum", "mean", "min", "max", "count")
_REDUCTIONS: Final[tuple[Reduction, ...]] = ("sum", "mean", "min", "max")
_ISO: Final = re.compile(
    r"([0-9]{4})-([0-9]{2})(?:-([0-9]{2})(?:[T ]([0-9]{2}):([0-9]{2})(?::([0-9]{2}))?)?)?"
)
MAX_WORK: Final = 5_000_000
MAX_GROUPS: Final = 1_000


@dataclass(frozen=True, slots=True)
class Explanation:
    """One closed explanation over one CSV: its pairs in pandas' order, and group counts."""

    table: str
    family: Family
    key: str | None
    value: str | None
    where: tuple[str, str] | None
    pairs: tuple[tuple[CellValue | int, float], ...]
    counts: tuple[int, ...] | None
    # A channel explanation (R8): per pair, the main series' value of the same row or group, so a
    # colour or size binds to its own point, never to another point with the same key.
    partners: tuple[float, ...] | None = None

    @property
    def columns(self) -> frozenset[str]:
        return frozenset(name for name in (self.key, self.value) if name is not None)


@dataclass(frozen=True, slots=True)
class Choice:
    """How one series is explained: its explanation (None = request numbers alone), the points it
    backs (N of its M pairs: R2), and the points the request typed instead."""

    series: Series
    explanation: Explanation | None
    matched: int
    from_request: int
    # A reference mark's (file, column) per distinct column that alone holds one of its values,
    # and how many of its values several columns hold (those draw no column).
    reference: tuple[tuple[str, str], ...] = ()
    shared: int = 0

    @property
    def columns(self) -> tuple[tuple[str, frozenset[str]], ...]:
        """(file, the columns its drawn values come from) per file; empty for request numbers."""
        if self.explanation is not None:
            return ((self.explanation.table, self.explanation.columns),)
        files = sorted({file for file, _column in self.reference})
        return tuple(
            (file, frozenset(column for owner, column in self.reference if owner == file))
            for file in files
        )


@dataclass(frozen=True, slots=True)
class Unexplained:
    series: Series
    reason: FigureReason


def _date(text: str) -> str | None:
    match = _ISO.fullmatch(text.strip())
    if match is None:
        return None
    year, month, day, hour, minute, second = (
        int(part or default)
        for part, default in zip(match.groups(), ("0", "0", "1", "0", "0", "0"), strict=True)
    )
    try:
        # Calendar text, not an instant: no time zone applies.
        return datetime(year, month, day, hour, minute, second).isoformat()  # noqa: DTZ001
    except ValueError:
        return None


def _number(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _canon_text(text: str) -> set[Canon]:
    forms: set[Canon] = {("t", text)}
    number = _number(text)
    if number is not None:
        forms.add(("n", number))
    date = _date(text)
    if date is not None:
        forms.add(("d", date))
    return forms


def _canon_cell(value: CellValue | int) -> set[Canon]:
    if isinstance(value, str):
        return _canon_text(value)
    return {("n", float(value))}


def _canon_key(key: Key) -> set[Canon]:
    if key.text is not None:
        return _canon_text(key.text)
    if key.number is not None:
        return {("n", key.number)}
    if key.date is not None:
        date = _date(key.date)
        return set() if date is None else {("d", date)}
    return set()


def _value_ok(point: Point, candidate: float) -> bool:
    if point.base is None:
        return candidate == point.value
    return point.base + candidate == point.value


# --- the closed vocabulary -----------------------------------------------------------------------


def _rows(table: Table, where: tuple[str, str] | None) -> list[int]:
    if where is None:
        return list(range(table.rows))
    column = table.columns[table.header.index(where[0])]
    return [row for row, text in enumerate(column.texts) if text == where[1]]


def _group(
    table: Table, key: Column, value: Column, rows: list[int], budget: WorkBudget
) -> Iterator[Explanation]:
    numbers = cast("tuple[float, ...]", value.numbers)  # callers pass numeric columns alone
    for reduction in _REDUCTIONS:
        try:
            reduced = aggregate_series(
                tuple(key.keys[row] for row in rows),
                tuple(value.texts[row] for row in rows),
                tuple(numbers[row] for row in rows),
                reduction,
                budget=budget,
                max_groups=MAX_GROUPS,
            )
        except PysrcRefusalError:
            return
        yield Explanation(
            table.name,
            reduction,
            key.name,
            value.name,
            None,
            tuple(zip(reduced.keys, reduced.values, strict=True)),
            reduced.counts,
        )


def _count(table: Table, key: Column, rows: list[int]) -> Explanation:
    groups = Counter(key.keys[row] for row in rows)
    ordered = sorted(groups, key=lambda value: (isinstance(value, str), value))
    return Explanation(
        table.name,
        "count",
        key.name,
        None,
        None,
        tuple((group, float(groups[group])) for group in ordered),
        tuple(groups[group] for group in ordered),
    )


def explanations(
    table: Table, where: tuple[str, str] | None, budget: WorkBudget
) -> Iterator[Explanation]:
    """Every closed explanation over `table`, filtered to `where`'s rows (R6), in a fixed order."""
    rows = _rows(table, where)  # never empty: a `where` comes from a cell the column holds
    budget.charge(len(table.columns) * len(rows))
    usable = table.columns  # a filter column may be the key: the series shows its own label
    for value in usable:
        if value.numbers is None:
            continue
        numbers = value.numbers
        yield Explanation(
            table.name,
            "index",
            None,
            value.name,
            where,
            tuple((row, numbers[row]) for row in rows),
            None,
        )
        for key in usable:
            budget.charge(len(rows))
            yield Explanation(
                table.name,
                "raw",
                key.name,
                value.name,
                where,
                tuple((key.keys[row], numbers[row]) for row in rows),
                None,
            )
            if key is value:  # raw(K, K): a colour or size encoding its own point's key
                continue
            for grouped in _group(table, key, value, rows, budget):
                yield Explanation(
                    grouped.table,
                    grouped.family,
                    grouped.key,
                    grouped.value,
                    where,
                    grouped.pairs,
                    grouped.counts,
                )
    for key in usable:
        counted = _count(table, key, rows)
        yield Explanation(
            counted.table, "count", counted.key, None, where, counted.pairs, counted.counts
        )


# --- matching ------------------------------------------------------------------------------------


def _keys_free(series: Series) -> bool:
    """No source must supply the keys: a keyless series (hist inputs, an unnamed pie) or the
    default positions 0..n-1 (`plt.plot(values)`)."""
    points = series.points
    return series.shape == "values" or [point.key.number for point in points] == [
        float(i) for i in range(len(points))
    ]


def _request_key(key: Key, request: Request, *, positional: bool) -> bool:
    if key.text is not None:
        return request.names(key.text)  # R4
    if key.number is not None:
        return positional or key.number in request.numbers
    if key.date is not None:
        return request.names(key.date[:10]) or request.names(key.date[:7])
    return positional or key.slot is not None


def _request_value(point: Point, request: Request) -> bool:
    if point.base is None:
        return point.value in request.numbers
    return any(point.base + number == point.value for number in request.numbers)


def _orders(explanation: Explanation) -> list[list[int]]:
    """The pair orders a positional key may bind to: pandas' own, and a raw table re-sorted by key
    (a pivot sorts its index)."""
    pairs = explanation.pairs
    if explanation.family != "raw":
        return [list(range(len(pairs)))]
    resorted = sorted(range(len(pairs)), key=lambda at: _sort_value(pairs[at][0]))
    return [list(range(len(pairs))), resorted]


def _sort_value(value: CellValue | int) -> tuple[int, float, str]:
    if isinstance(value, str):
        return (1, 0.0, value)
    return (0, float(value), "")


def _fits(point: Point, explanation: Explanation, position: int) -> bool:
    partners = explanation.partners
    return _value_ok(point, explanation.pairs[position][1]) and (
        partners is None or partners[position] == point.partner
    )


def _matched_keyed(
    points: tuple[Point, ...], explanation: Explanation, order: list[int]
) -> list[bool]:
    """Injective: each pair (row or group) backs one point; `order` = the pairs a slot counts."""
    pairs = explanation.pairs
    index: dict[Canon, list[int]] = {}
    for position, (key, _value) in enumerate(pairs):
        for form in _canon_cell(key):
            index.setdefault(form, []).append(position)
    used: set[int] = set()
    matched = [False] * len(points)
    # A slot binds one row; a keyed point any row of its key class (rows sharing key + value are
    # interchangeable), so binding the slots first keeps the greedy assignment maximal.
    slots_first = sorted(range(len(points)), key=lambda i: points[i].key.slot is None)
    for at in slots_first:
        point = points[at]
        found = None
        if point.key.slot is not None:
            slot = point.key.slot
            if (
                slot < len(order)
                and order[slot] not in used
                and _fits(point, explanation, order[slot])
            ):
                found = order[slot]
        else:
            found = next(
                (
                    position
                    for form in sorted(_canon_key(point.key), key=repr)
                    for position in index.get(form, ())
                    if position not in used and _fits(point, explanation, position)
                ),
                None,
            )
        if found is not None:
            used.add(found)
            matched[at] = True
    return matched


def _matched_values(points: tuple[Point, ...], explanation: Explanation) -> list[bool]:
    pool = Counter(value for _key, value in explanation.pairs)
    matched: list[bool] = []
    for point in points:
        ok = pool[point.value] > 0
        if ok:
            pool[point.value] -= 1
        matched.append(ok)
    return matched


def _coverage(series: Series, explanation: Explanation) -> list[bool]:
    """Per point, whether `explanation` backs it; the best of its pair orders."""
    if series.shape == "values":
        return _matched_values(series.points, explanation)
    best: list[bool] = []
    for order in _orders(explanation):
        matched = _matched_keyed(series.points, explanation, order)
        if sum(matched) > sum(best):
            best = matched
    return best or [False] * len(series.points)


@dataclass(frozen=True, slots=True)
class Context:
    """The judge's data: attached tables, the request, and the anchoring words it needs."""

    tables: tuple[Table, ...]
    request: Request
    request_text: str | None
    aliases: Aliases
    strict: bool


def _where(series: Series, table: Table) -> list[tuple[str, str] | None]:
    """R6: a series named by a cell value of column C reads the rows holding it, never all rows."""
    if series.name is None:
        return [None]
    columns = [c.name for c in table.columns if series.name in c.texts]
    return [(column, series.name) for column in columns] or [None]


def _named(context: Context, table: Table) -> frozenset[str]:
    if context.request_text is None:
        return frozenset()
    try:
        named, _negated = anchors(
            context.request_text,
            table.header,
            context.aliases,
            ignore_ties=True,
            short_names=context.strict,
        )
    except AmbiguousTermError:  # pragma: no cover - ignore_ties never raises
        return frozenset()
    return named


def _pick(
    candidates: list[Explanation], context: Context, series: Series
) -> Explanation | Unexplained:
    """One explanation per column set; R7 breaks a tie between column sets by request naming."""
    # The filter column draws nothing (R6): two filters over the same drawn columns are one
    # reading, published by the first filter column in header order.
    groups: dict[tuple[str, frozenset[str]], list[Explanation]] = {}
    for explanation in candidates:
        groups.setdefault((explanation.table, explanation.columns), []).append(explanation)
    if len(groups) > 1:
        tables = {table.name: table for table in context.tables}
        named = [group for group in groups if group[1] <= _named(context, tables[group[0]])]
        if len(named) != 1:
            return Unexplained(series, "column_not_requested")
        groups = {named[0]: groups[named[0]]}
    (members,) = groups.values()
    return min(members, key=lambda e: _PREFERENCE.index(e.family))  # stable: first filter wins


def _candidates(series: Series, context: Context, budget: WorkBudget) -> Iterator[Explanation]:
    for table in context.tables:
        for where in _where(series, table):
            yield from explanations(table, where, budget)


def _explain_series(
    series: Series, candidates: Iterator[Explanation], context: Context
) -> Choice | Unexplained:
    request = context.request
    positional = _keys_free(series)
    by_request = [
        _request_value(point, request) and _request_key(point.key, request, positional=positional)
        for point in series.points
    ]
    full: list[Explanation] = []
    partial: list[tuple[int, Explanation]] = []
    backed = [False] * len(series.points)  # the most points any one explanation backs
    for explanation in candidates:
        matched = _coverage(series, explanation)
        if sum(matched) > sum(backed):
            backed = matched
        if all(matched):
            full.append(explanation)
        elif any(matched) and all(m or r for m, r in zip(matched, by_request, strict=True)):
            partial.append((sum(matched), explanation))
    if full:
        picked = _pick(full, context, series)
    elif partial:
        best = max(count for count, _ in partial)
        picked = _pick([e for count, e in partial if count == best], context, series)
    elif all(by_request):
        return Choice(series, None, 0, len(series.points))
    else:
        reason = _unexplained_reason(series, request, backed, positional=positional)
        return Unexplained(series, reason)
    if isinstance(picked, Unexplained):
        return picked
    matched = _coverage(series, picked)
    return Choice(series, picked, sum(matched), len(matched) - sum(matched))


def _unexplained_reason(
    series: Series, request: Request, backed: list[bool], *, positional: bool
) -> FigureReason:
    """A typed value whose key the request lacks, among points no file explanation backs."""
    for point, done in zip(series.points, backed, strict=True):
        if (
            not done
            and _request_value(point, request)
            and not _request_key(point.key, request, positional=positional)
        ):
            return "label_not_in_request"
    return "value_not_found"


# --- encoded channels (R8) -----------------------------------------------------------------------


def _channel_explanations(
    table: Table, main: Explanation, budget: WorkBudget
) -> Iterator[Explanation]:
    """A channel's candidates: the main explanation's rows or groups, another numeric column's
    cells (or one reduction of it per group), each pair carrying the main value it sits beside."""
    rows = _rows(table, main.where)
    key = None if main.key is None else table.columns[table.header.index(main.key)]
    for column in table.columns:
        numbers = column.numbers
        if numbers is None:
            continue
        budget.charge(len(rows))
        if main.family in ("raw", "index"):
            keys = list(rows) if key is None else [key.keys[row] for row in rows]
            yield Explanation(
                table.name,
                main.family,
                main.key,
                column.name,
                main.where,
                tuple(zip(keys, (numbers[row] for row in rows), strict=True)),
                None,
                tuple(value for _key, value in main.pairs),
            )
            continue
        partner = dict(main.pairs)
        for grouped in _group(table, cast("Column", key), column, rows, budget):
            yield Explanation(
                table.name,
                grouped.family,
                main.key,
                column.name,
                main.where,
                grouped.pairs,
                grouped.counts,
                tuple(partner[group] for group, _value in grouped.pairs),
            )


def _explain_channel(
    series: Series, main: Choice, context: Context, budget: WorkBudget
) -> Choice | Unexplained:
    """A colour or size channel: from the rows or groups of its scatter's own explanation, else
    request numbers alone (a scatter typed in the request types its channels too)."""
    explanation = main.explanation
    if explanation is None:
        return _explain_series(series, iter(()), context)
    table = next(table for table in context.tables if table.name == explanation.table)
    return _explain_series(series, _channel_explanations(table, explanation, budget), context)


# --- reference marks -----------------------------------------------------------------------------


def _column_values(table: Table, column: Column, budget: WorkBudget) -> set[float]:
    """A numeric column's cells and its whole-column reductions: what a reference line may be."""
    numbers = column.numbers
    if numbers is None:
        return set()
    found = set(numbers)
    rows = list(range(table.rows))
    whole = Column("", ("",) * table.rows, ("",) * table.rows, None, integer=False)
    for explanation in _group(table, whole, column, rows, budget):
        found.update(value for _key, value in explanation.pairs)
    return found


def _explain_reference(
    series: Series, context: Context, budget: WorkBudget
) -> Choice | Unexplained:
    """A reference value = zero, a request number, a cell, or one whole-column reduction; a value
    exactly one column holds draws that column, one several columns hold draws none."""
    holders: set[tuple[str, str]] = set()
    typed = shared = 0
    for point in series.points:
        if point.value == 0.0 or point.value in context.request.numbers:
            typed += 1
            continue
        found = {
            (table.name, column.name)
            for table in context.tables
            for column in table.columns
            if point.value in _column_values(table, column, budget)
        }
        if not found:
            return Unexplained(series, "value_not_found")
        if len(found) == 1:
            holders |= found
        else:
            shared += 1
    return Choice(series, None, 0, typed, tuple(sorted(holders)), shared)


# --- every series ------------------------------------------------------------------------------


def duplicate_key(series: Series) -> bool:
    """G8: two points of one keyed series show the same category (they overplot). An integrity
    rule: it binds every figure, a figure with no data source included."""
    if series.shape != "keyed" or series.mark.family == "scatter":
        return False
    texts = [point.key.text for point in series.points if point.key.text is not None]
    return len(texts) != len(set(texts))


def explain(
    every: tuple[Series, ...], context: Context, unreadable: tuple[Unreadable, ...]
) -> tuple[Choice, ...] | Unexplained:
    """One choice per series, or the first series no source explains (with its reason)."""
    budget = WorkBudget(MAX_WORK)
    choices: list[Choice] = []
    try:
        for series in every:
            if series.shape == "reference":
                outcome = _explain_reference(series, context, budget)
            elif series.channel != "value":
                main = next(c for c in reversed(choices) if c.series.mark is series.mark)
                outcome = _explain_channel(series, main, context, budget)
            else:
                outcome = _explain_series(series, _candidates(series, context, budget), context)
            if isinstance(outcome, Unexplained):
                if outcome.reason == "value_not_found" and unreadable:
                    return Unexplained(series, unreadable[0].code)
                return outcome
            choices.append(outcome)
    except WorkBudgetExceededError:
        return Unexplained(every[0], "work_budget_exceeded")
    return tuple(choices)
'''

_SOURCES["verifier.figure.columns"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The request names the drawn columns; no label names a column the chart does not draw.

Drawn columns = per attached file, the columns that explain the drawn values (`raw`/`group` K and
V, `index` V, `count` K, a reference mark's one column); a label column R6 filters by draws
nothing. Anchoring = the shipped matcher (`anchoring.py`): the demo's substitution rule, or
production's strict rule. G10: a title, axis label, suptitle or legend entry naming a header
column the chart does not draw blocks; over reductions, so does another reduction's summary word.
"""

from dataclasses import dataclass

from verifier.figure.anchoring import (
    AmbiguousTermError,
    anchors,
    nameable,
    named_columns,
    summaries,
)
from verifier.figure.description import Figure, Legend, Text
from verifier.figure.explain import Choice, Context
from verifier.figure.parts import Panel
from verifier.figure.reasons import block
from verifier.figure.sources import Table

_REDUCTIONS: frozenset[str] = frozenset({"sum", "mean", "min", "max"})


@dataclass(frozen=True, slots=True)
class Drawn:
    """Per file name, the columns its values were drawn from."""

    columns: dict[str, frozenset[str]]

    def of(self, table: Table) -> frozenset[str]:
        return self.columns.get(table.name, frozenset())


def drawn(choices: tuple[Choice, ...]) -> Drawn:
    found: dict[str, frozenset[str]] = {}
    for choice in choices:
        for file, columns in choice.columns:
            found[file] = found.get(file, frozenset()) | columns
    return Drawn(found)


def check_anchoring(context: Context, columns: Drawn) -> None:
    """Q8 substitution (demo) / Q37 strict (production) over each file's drawn columns."""
    request = context.request_text
    if request is None:
        return
    for table in context.tables:
        plotted = columns.of(table)
        if not plotted:
            continue
        try:
            named, negated = anchors(
                request, table.header, context.aliases, short_names=context.strict
            )
        except AmbiguousTermError:
            block("column_not_requested")
        if named - plotted and plotted - named:
            block("column_not_requested")
        unnamed = plotted - named
        if (
            context.strict
            and (named or negated)
            and any(nameable(column, context.aliases) for column in unnamed)
        ):
            block("column_not_named")


def _entries(legend: Legend | None) -> list[Text]:
    return [] if legend is None else [Text(entry.text, legend.site) for entry in legend.entries]


def _panel_labels(figure: Figure, panel: Panel) -> list[Text | None]:
    """A panel's judged labels: axis labels, titles, its legend and its colorbars' labels."""
    axes = panel.axes
    texts = [axes.x.label, axes.y.label, *axes.titles, *_entries(axes.legend)]
    for other in figure.axes:
        if other.colorbar_of is not None and other.colorbar_of[0] == panel.index:
            texts += [other.x.label, other.y.label]
    return texts


def _check(
    texts: list[Text | None], reductions: set[str], context: Context, columns: Drawn
) -> None:
    for text in texts:
        if text is None:
            continue
        for table in context.tables:
            header, aliases = table.header, context.aliases
            if named_columns(text.text, header, aliases, ignore_ties=True) - columns.of(table):
                block("label_not_consistent", text.site)
            if reductions and summaries(text.text, header, aliases) - reductions:
                block("label_not_consistent", text.site)


def check_labels(
    figure: Figure,
    panels: tuple[Panel, ...],
    choices: tuple[Choice, ...],
    context: Context,
    columns: Drawn,
) -> None:
    """G10 over every judged label, against every attached file's header: a panel's labels
    against that panel's reductions, the figure's own (suptitle, supxlabel, supylabel, figure
    legends) against every panel's."""
    every: set[str] = set()
    for position, panel in enumerate(panels):
        reductions: set[str] = {
            choice.explanation.family
            for choice in choices
            if choice.series.panel == position
            and choice.explanation is not None
            and choice.explanation.family in _REDUCTIONS
        }
        every |= reductions
        _check(_panel_labels(figure, panel), reductions, context, columns)
    figure_texts = [*figure.titles, *(e for legend in figure.legends for e in _entries(legend))]
    _check(figure_texts, every, context, columns)
'''

_SOURCES["verifier.figure.interpret"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""What was verified, in plain words, English and Japanese (tier 3: publication).

One sentence per drawn series names where its values come from: a CSV column, one reduction per
group with each group's row count (G11), a filter by its legend name (R6), the request's typed
numbers, or none. A drawn subset says N of M (R2). A figure with no data source says it was
checked for integrity alone (ruling 4). Text on the chart is listed, never judged (ruling 6).
"""

from typing import Final

from verifier.figure.explain import Choice, Explanation

_MARKS: Final = {
    "line": ("Line", "折れ線"),
    "scatter": ("Points", "散布点"),
    "bar": ("Bars", "棒"),
    "hist": ("Histogram", "ヒストグラム"),
    "pie": ("Pie", "円グラフ"),
    "band": ("Area", "面"),
    "reference": ("Reference mark", "基準線"),
    "colors": ("Point colours", "点の色"),
    "sizes": ("Point sizes", "点の大きさ"),
}
_REDUCTIONS: Final = {
    "sum": ("sum", "合計"),
    "mean": ("mean", "平均"),
    "min": ("minimum", "最小値"),
    "max": ("maximum", "最大値"),
}
_SOURCES: Final = {
    "self": ("{value} from {file}", "{file} の {value} 列"),
    "raw": ("{value} by {key} from {file}", "{file} の {value} 列 ({key} 列ごと)"),
    "index": ("{value} in row order from {file}", "{file} の {value} 列 (行の順)"),
    "count": ("the number of rows per {key} from {file}", "{file} の {key} 列ごとの行数"),
    "reduced": (
        "the {reduction} of {value} per {key} from {file}",
        "{file} の {key} 列ごとの {value} 列の{reduction}",
    ),
}
_WHERE: Final = (", rows where {column} is {cell}", " ({column} 列が {cell} の行)")
# A reference mark's clauses.
_HELD: Final = ("a value of {columns} from {file}", "{file} の {columns} 列の値")
_AND: Final = (" and ", "、")
_SHARED: Final = ("{n} value(s) held by several columns", "複数の列にある値 {n} 件")
_TYPED: Final = ("zero or a number typed in the request", "ゼロまたは依頼文の数値")
_TYPED_COUNT: Final = ("{n} value(s) zero or typed in the request", "ゼロまたは依頼文の数値 {n} 件")
_JOIN: Final = ("; ", "。")
_STOP: Final = (".", "。")
_GROUPS_SHOWN: Final = 8
_TEXTS_SHOWN: Final = 8
_INTEGRITY_ONLY: Final = (
    "No data was attached or typed in the request, so the values were not compared with data."
    " The chart passed the integrity checks alone.",
    "データが添付されておらず、依頼文にも数値がないため、値はデータと照合していません。"
    "グラフは完全性のチェックだけに合格しました。",
)


def _quote(text: str) -> str:
    return f'"{text}"'


def _groups(explanation: Explanation, *, japanese: bool) -> str:
    counts = explanation.counts or ()
    shown = [
        f"{key} {count}" if not japanese else f"{key} {count} 行"
        for (key, _value), count in zip(explanation.pairs, counts, strict=True)
    ][:_GROUPS_SHOWN]
    more = len(counts) > _GROUPS_SHOWN
    if japanese:
        return "各グループの行数: " + "、".join(shown) + ("、…" if more else "")
    return "rows per group: " + ", ".join(shown) + (", …" if more else "")


def _source(explanation: Explanation, *, japanese: bool) -> str:
    family, language = explanation.family, 1 if japanese else 0
    if family in ("sum", "mean", "min", "max"):
        form = "reduced"
    elif family == "raw" and explanation.key == explanation.value:
        form = "self"
    else:
        form = family
    text = _SOURCES[form][language].format(
        file=explanation.table,
        key=explanation.key,
        value=explanation.value,
        reduction=_REDUCTIONS[family][language] if form == "reduced" else "",
    )
    if explanation.where is not None:
        column, cell = explanation.where
        text += _WHERE[language].format(column=column, cell=cell)
    return text


def _reference(named: str, choice: Choice, *, japanese: bool) -> str:
    """A reference mark: the columns that alone hold its values, values several columns hold,
    and values that are zero or typed in the request."""
    language = 1 if japanese else 0
    parts = [
        _HELD[language].format(columns=_AND[language].join(columns), file=file)
        for file, columns in ((file, sorted(c)) for file, c in choice.columns)
    ]
    if choice.shared:
        parts.append(_SHARED[language].format(n=choice.shared))
    if choice.from_request:
        typed = _TYPED[language]
        parts.append(typed if not parts else _TYPED_COUNT[language].format(n=choice.from_request))
    return f"{named}: " + _JOIN[language].join(parts) + _STOP[language]


def _sentence(choice: Choice, *, japanese: bool) -> str:
    series = choice.series
    mark = _MARKS[series.mark.family if series.channel == "value" else series.channel][
        1 if japanese else 0
    ]
    named = f"{mark} {_quote(series.name)}" if series.name is not None else mark
    explanation = choice.explanation
    if explanation is None:
        if series.shape == "reference":
            return _reference(named, choice, japanese=japanese)
        source = "依頼文に入力された数値" if japanese else "numbers typed in the request"
        return f"{named}: {source}。" if japanese else f"{named}: {source}."
    parts = [_source(explanation, japanese=japanese)]
    total = len(explanation.pairs)
    if choice.matched < total:
        parts.append(
            f"{total} 件中 {choice.matched} 件を描画"
            if japanese
            else f"{choice.matched} of {total} drawn"
        )
    if explanation.counts is not None and explanation.family != "count":
        parts.append(_groups(explanation, japanese=japanese))
    if choice.from_request:
        parts.append(
            f"依頼文の数値 {choice.from_request} 件"
            if japanese
            else f"{choice.from_request} value(s) typed in the request"
        )
    if japanese:
        return f"{named}: " + "。".join(parts) + "。"
    return f"{named}: " + "; ".join(parts) + "."


def interpretation(
    choices: tuple[Choice, ...], texts: tuple[str, ...], *, integrity_only: bool, japanese: bool
) -> str:
    """The plain-words record of what passed, in one language."""
    sentences = [_INTEGRITY_ONLY[1 if japanese else 0]] if integrity_only else []
    sentences += [_sentence(choice, japanese=japanese) for choice in choices]
    if texts:
        shown = ", ".join(_quote(text) for text in texts[:_TEXTS_SHOWN])
        more = len(texts) > _TEXTS_SHOWN
        if japanese:
            sentences.append(f"グラフ上の文字は確認していません: {shown}{'、…' if more else ''}。")
        else:
            sentences.append(f"Text on the chart was not checked: {shown}{', …' if more else ''}.")
    return "\n".join(sentences)
'''

_SOURCES["verifier.figure.judge"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The judge: one described figure in, one verdict out (M19; law `.claude/rules/figure.md`).

Stages, each blocking before the next runs: figure (the run and its one figure) → parts (the
closed artist set) → axes → marks → values → columns. The judge is pure and stdlib: it reads
the reader's description, the user's CSV bytes and the request text, and nothing else.
"""

from dataclasses import dataclass

from verifier.figure.anchoring import Aliases, Anchoring
from verifier.figure.axes_rules import check_axes
from verifier.figure.columns import check_anchoring, check_labels, drawn
from verifier.figure.description import Description, Figure
from verifier.figure.explain import Choice, Context, Unexplained, duplicate_key, explain
from verifier.figure.interpret import interpretation
from verifier.figure.legends import Legends, read_legends
from verifier.figure.mark_rules import check_marks
from verifier.figure.parts import Panel, panels
from verifier.figure.reasons import Blocked, BlockedError, block
from verifier.figure.request import read_request
from verifier.figure.series import series
from verifier.figure.sources import Table, Unreadable, read_table

_MISSING_MODULES = frozenset({"ModuleNotFoundError", "ImportError"})


@dataclass(frozen=True, slots=True)
class Judged:
    """A figure every integrity rule passed: its panels and each series' displayed name."""

    figure: Figure
    panels: tuple[Panel, ...]
    legends: Legends


def check_figure(description: Description) -> None:
    """The run produced exactly one drawable figure, every glyph present."""
    error = description.error
    if error is not None:
        if error.kind == "syntax":
            block("program_syntax_error", error.line)
        if error.name in _MISSING_MODULES:
            block("module_not_available", error.line)
        block("program_error", error.line)
    if description.too_large:
        block("figure_too_large")
    if not description.figures:
        block("no_figure")
    if len(description.figures) > 1:
        block("multiple_figures", description.figures[1].site)
    if description.glyphs:
        block("glyph_missing")


def integrity(description: Description) -> Judged | Blocked:
    """Every stage up to and including the mark rules; values + columns follow (M19.4)."""
    try:
        check_figure(description)
        figure, judged = panels(description)
        for panel in judged:
            check_axes(panel)
        colorbars = {axes.colorbar_of for axes in figure.axes if axes.colorbar_of is not None}
        legends = read_legends(judged, figure.legends)
        for panel in judged:
            check_marks(panel, colorbars, legends.encodings)
    except BlockedError as error:
        return error.blocked
    return Judged(figure, judged, legends)


@dataclass(frozen=True, slots=True)
class Passed:
    """A figure every rule passed: what each series was explained by, in plain words."""

    judged: Judged
    choices: tuple[Choice, ...]
    integrity_only: bool
    interpretation: str
    interpretation_ja: str


@dataclass(frozen=True, slots=True)
class Sources:
    """What the user supplied: attached files (name, bytes), the request, and the admin's words."""

    files: tuple[tuple[str, bytes], ...] = ()
    request: str | None = None
    anchoring: Anchoring = "strict"
    aliases: Aliases = ()


def _texts(judged: Judged, *, integrity_only: bool) -> tuple[str, ...]:
    """On-chart text no check judged; a pie's drawn labels are keys once values are compared."""
    listed = [text for panel in judged.panels for text in panel.texts]
    if integrity_only:
        listed += [text for panel in judged.panels for text in panel.pie_labels]
    listed += [text.text for text in judged.figure.texts if text.text.strip()]
    return tuple(listed)


def judge(description: Description, sources: Sources) -> Passed | Blocked:
    """Every stage: integrity, then the drawn values, then the columns they name."""
    judged = integrity(description)
    if isinstance(judged, Blocked):
        return judged
    read = [read_table(name, content) for name, content in sources.files]
    tables = tuple(table for table in read if isinstance(table, Table))
    unreadable = tuple(table for table in read if isinstance(table, Unreadable))
    request = read_request(sources.request)
    integrity_only = not sources.files and not request.numbers
    context = Context(
        tables, request, sources.request, sources.aliases, sources.anchoring == "strict"
    )
    colorbars = {
        (*axes.colorbar_of, "colors") for axes in judged.figure.axes if axes.colorbar_of is not None
    }
    every = series(
        judged.panels, judged.legends.names, judged.legends.encodings | frozenset(colorbars)
    )
    choices: tuple[Choice, ...] = ()
    try:
        for each in every:
            if duplicate_key(each):
                block("category_not_unique", each.site)
        if not integrity_only:
            outcome = explain(every, context, unreadable)
            if isinstance(outcome, Unexplained):
                block(outcome.reason, outcome.series.site)
            choices = outcome
        columns = drawn(choices)
        check_anchoring(context, columns)
        check_labels(judged.figure, judged.panels, choices, context, columns)
    except BlockedError as error:
        return error.blocked
    texts = _texts(judged, integrity_only=integrity_only)
    return Passed(
        judged,
        choices,
        integrity_only,
        interpretation(choices, texts, integrity_only=integrity_only, japanese=False),
        interpretation(choices, texts, integrity_only=integrity_only, japanese=True),
    )
'''

_SOURCES["webui.paste_in.filter"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The only outlet that can publish a figure in Open WebUI.

The model's reply and tool-result prose never grant permission. A tool call leaves a tagged record
in backend request state; this outlet refetches the user's files, runs the recorded program
unchanged in the user's browser sandbox with the trusted reader around it, and judges the finished
figure the reader describes. The browser, the sandbox and matplotlib are trusted to draw and to
report; every decision is the judge's.
"""

import asyncio
import base64
import binascii
import contextlib
import logging
import re
import unicodedata
import uuid
from collections.abc import Awaitable, Callable
from typing import Final, cast

from verifier.figure.anchoring import Anchoring
from verifier.figure.description import TAG, parse_description
from verifier.figure.judge import Passed, Sources, judge
from verifier.pysrc.budget import WorkBudget, WorkBudgetExceededError
from verifier.pysrc.csvread import _read_csv
from verifier.pysrc.errors import PysrcRefusalError
from verifier.pysrc.limits import DEFAULT_LIMITS
from webui.paste_in.checks import Evidence, breakdown_html
from webui.paste_in.owui_files import (
    UPLOAD_DIR,
    UploadedFile,
    cjk_font,
    owned_files,
    uploaded_files,
)
from webui.paste_in.reasons import REASONS, Reason
from webui.paste_in.receipt import read_receipt
from webui.paste_in.sandbox import wrapper_code
from webui.paste_in.templates import PRODUCTION_TEMPLATES, Templates

type _Emit = Callable[[dict[str, object]], Awaitable[object]]

PASS_TEXT: Final = "Figure verification passed"  # noqa: S105 - a verdict, not a credential
FAIL_TEXT: Final = "Figure verification failed, no image produced"
RPC_TIMEOUT_SECONDS: Final = 60
STATUS_TIMEOUT_SECONDS: Final = 5
_PNG_PREFIX = "data:image/png;base64,"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_URI = re.compile(r"data:image/png;base64,[A-Za-z0-9+/]+={0,2}")
_DATA_PREFIX = re.compile(r"(?<!\w)data:")
_TRACEBACK = "Traceback (most recent call last):"
# A kana LETTER alone marks a Japanese request (user ruling): kanji are shared with Chinese, and
# marks such as `・` or `ー` occur beside kanji alone.
_KANA_LETTERS = ("HIRAGANA LETTER", "KATAKANA LETTER", "HALFWIDTH KATAKANA LETTER")
_LOGGER = logging.getLogger(__name__)

# Admin-facing identity; the function source itself comes from the generated paste-in artifact.
FILTER_ID: Final = "figure_verification_filter"
FILTER_NAME: Final = "Figure Verification Filter"
FILTER_DESCRIPTION: Final = "Shows a chart only after the verifier checks the finished figure."


def _needs_font(program: str, files: tuple[UploadedFile, ...]) -> bool:
    """Whether the figure can draw text outside ASCII, which the sandbox fonts may lack: the
    program or an attached file holds a non-ASCII character (over-inclusion costs bytes alone)."""
    return not program.isascii() or any(not file.content.isascii() for file in files)


def _png_uri(stdout: str) -> str | None:
    """Accept exactly one complete PNG data-URI line, outside the description line, carrying a
    valid base64 PNG signature."""
    lines = [
        line.strip()
        for line in stdout.splitlines()
        if not line.startswith(TAG) and _DATA_PREFIX.search(line)
    ]
    if len(lines) != 1 or _PNG_URI.fullmatch(lines[0]) is None:
        return None
    try:
        image = base64.b64decode(lines[0][len(_PNG_PREFIX) :], validate=True)
    except (binascii.Error, ValueError):
        return None
    return lines[0] if image.startswith(_PNG_SIGNATURE) else None


def _rewrite(body: dict[str, object], text: str) -> dict[str, object]:
    """Replace every user-visible narration of the final assistant message, never earlier ones."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        messages = []
        body["messages"] = messages
    assistant = next(
        (
            message
            for message in reversed(messages)
            if isinstance(message, dict) and message.get("role") == "assistant"
        ),
        None,
    )
    if assistant is None:
        assistant = {"role": "assistant"}
        messages.append(assistant)
    assistant["content"] = text
    # OWUI persists output only when a new value differs from its pre-outlet snapshot.
    assistant["output"] = [
        {
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text}],
        }
    ]
    return body


def _reply_fault(response: dict[object, object]) -> Reason | None:
    """Why a sandbox reply cannot carry a clean run, or `None` when its stderr is empty.

    OWUI's own caller answers `{'error': ...}` for a closed or timed-out tab, and reports a clean
    run with null stderr. A content blocker that stops `pyodide.js` leaves `loadPyodide` unbound,
    and OWUI's sandbox host replies with the engine's ReferenceError, which names it; only that
    measured shape earns the ad-blocker fix. The host reports other faults in the same bare shape
    (an upload throwing outside the program's `try`), so the rest stay generic.
    """
    if "stderr" not in response:
        return "browser_no_answer" if "error" in response else "reply_malformed"
    stderr = response["stderr"]
    if stderr is None or (type(stderr) is str and stderr == ""):
        return None
    if type(stderr) is not str:
        return "reply_malformed"
    if "loadPyodide" in stderr and not stderr.startswith(_TRACEBACK):
        return "sandbox_unavailable"
    return "sandbox_error"


def _japanese(metadata: object) -> bool:
    """The user's own request text decides, on every arm; the receipt exists on only some.

    Total, because it runs on diagnostic paths that must never cost the verdict.
    """
    message = metadata.get("user_message") if isinstance(metadata, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    return isinstance(content, str) and any(
        unicodedata.name(character, "").startswith(_KANA_LETTERS) for character in content
    )


async def _emit_bounded(emit: _Emit, event: dict[str, object], deadline: float) -> None:
    """Deliver one diagnostic event unless `deadline` (event-loop time) passes first.

    The emit runs as its own task and a late one is cancelled but never awaited: `wait_for` would
    wait for the emitter's cancellation cleanup, so a slow cleanup would hold back the verdict. An
    emit not started by the deadline is skipped, and the wait gets only the time left once the
    emitter has returned its awaitable, since that call can itself block. An `Exception` from the
    emitter is dropped; a cancellation propagates.
    """
    loop = asyncio.get_running_loop()
    if loop.time() >= deadline:
        return
    try:
        task = asyncio.ensure_future(emit(event))
    except Exception:  # an emitter that raises before it returns an awaitable
        return
    try:
        done, _pending = await asyncio.wait({task}, timeout=max(0.0, deadline - loop.time()))
    except asyncio.CancelledError:
        task.cancel()
        raise
    if not done:
        task.cancel()
        # Retrieve the eventual outcome, so asyncio never reports it as unhandled.
        task.add_done_callback(lambda late: late.cancelled() or late.exception())
        return
    error = task.exception()  # raises CancelledError when the emitter cancelled itself
    if error is not None and not isinstance(error, Exception):
        raise error


async def _diagnose(
    emit: _Emit | None,
    reason: Reason | None,
    metadata: dict[str, object] | None,
    anchoring: Anchoring,
    evidence: Evidence,
) -> None:
    """Show the user why a figure failed, then every check it faced (`reason` None = published).

    Open WebUI keeps a status line in `statusHistory` and an embed in `embeds`; its chat flows
    send neither to a model, since a rewritten reply always carries `output`, which is what they
    read. So a refusal code reaches the user without entering model context. Both are diagnosis
    only: together they wait at most `STATUS_TIMEOUT_SECONDS`, and no failure of theirs costs the
    verdict.
    """
    if emit is None:
        return
    deadline = asyncio.get_running_loop().time() + STATUS_TIMEOUT_SECONDS
    japanese = _japanese(metadata)
    if reason is not None:
        english, japanese_text = REASONS[reason]
        text = f"{japanese_text if japanese else english} ({reason})"
        status: dict[str, object] = {"type": "status", "data": {"description": text, "done": True}}
        await _emit_bounded(emit, status, deadline)
    try:
        document = breakdown_html(reason, japanese=japanese, anchoring=anchoring, evidence=evidence)
    except Exception:
        return
    # `replace` keeps exactly this document on the message; Open WebUI otherwise appends.
    embed: dict[str, object] = {"type": "embeds", "data": {"embeds": [document], "replace": True}}
    await _emit_bounded(emit, embed, deadline)


async def _fail(  # noqa: PLR0913 - the reply body plus the five diagnostic inputs
    body: dict[str, object],
    reason: Reason,
    metadata: dict[str, object] | None,
    emit: _Emit | None,
    anchoring: Anchoring,
    *,
    evidence: Evidence,
) -> dict[str, object]:
    """Block the figure: one log record for the admin, the diagnostics for the user.

    Neither the log nor the status line carries sandbox output, program bytes or request text,
    because an error message can quote the user's clinical data; the check list quotes the
    program alone, inside the user's own chat.
    """
    with contextlib.suppress(Exception):
        _LOGGER.info("figure verification failed reason=%s", reason)
    await _diagnose(emit, reason, metadata, anchoring, evidence)
    return _rewrite(body, FAIL_TEXT)


class Filter:
    """The global active filter; the inlet carries context, and the outlet authors the verdict."""

    # Production = strict request anchoring; the demo's generated filter overrides it (Q37).
    _ANCHORING: Anchoring = "strict"
    # Production's inlet templates carry no format sentence: Kimi calls `draw_figure` (Q40).
    _TEMPLATES: Templates = PRODUCTION_TEMPLATES

    async def inlet(
        self,
        body: dict[str, object],
        __user__: dict[str, object] | None = None,
        __metadata__: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Render the prompt template around the last user message, with the last owned CSV's
        path and header when one is attached, without changing the user's evidence."""
        user_id = (__user__ or {}).get("id")
        messages = body.get("messages")
        if not isinstance(user_id, str) or not isinstance(messages, list):
            return body
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            task = message.get("content")
            if not isinstance(task, str):
                return body
            rendered = self._render(task, await uploaded_files(__metadata__, user_id))
            updated = list(messages)
            updated[index] = {**message, "content": rendered}
            return {**body, "messages": updated}
        return body

    def _render(self, task: str, attachments: tuple[UploadedFile, ...]) -> str:
        if not attachments:
            return self._TEMPLATES.no_file.format(task=task)
        try:
            header, _rows = _read_csv(
                attachments[-1].content, DEFAULT_LIMITS, WorkBudget(DEFAULT_LIMITS.max_work)
            )
        except (PysrcRefusalError, WorkBudgetExceededError):
            return self._TEMPLATES.no_file.format(task=task)
        return self._TEMPLATES.file.format(
            task=task,
            dataset=attachments[-1].path.removeprefix(UPLOAD_DIR),
            columns=", ".join(header),
        )

    async def outlet(  # noqa: PLR0911, PLR0913, PLR0917 - fixed OWUI hook signature
        self,
        body: dict[str, object],
        __user__: dict[str, object] | None = None,
        __request__: object | None = None,
        __event_call__: _Emit | None = None,
        __event_emitter__: _Emit | None = None,
        __metadata__: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Run the recorded program in the browser, judge the figure, publish only a pass."""
        evidence = Evidence()

        async def fail(reason: Reason, site: int | None = None) -> dict[str, object]:
            return await _fail(
                body,
                reason,
                __metadata__,
                __event_emitter__,
                self._ANCHORING,
                evidence=Evidence(evidence.program, site),
            )

        receipt = read_receipt(__request__)
        if receipt is None:
            return await fail("no_tool_call")
        evidence = Evidence(receipt.program)
        user_id = (__user__ or {}).get("id")
        if not isinstance(user_id, str) or not user_id:
            return await fail("no_user")
        session = __metadata__.get("session_id") if isinstance(__metadata__, dict) else None
        if not isinstance(session, str):
            session = None
        if __event_call__ is None or __event_emitter__ is None or not session:
            return await fail("no_browser")
        files = await owned_files(receipt.file_ids, user_id)
        font = await cjk_font() if _needs_font(receipt.program, files) else None
        payload: dict[str, object] = {
            "type": "execute:python",
            "data": {
                "id": str(uuid.uuid4()),
                "code": wrapper_code(receipt.program, font),
                "session_id": session,
                "files": [
                    {"id": file.file_id, "filename": file.path.removeprefix(UPLOAD_DIR)}
                    for file in files
                ],
            },
        }
        try:
            response = await asyncio.wait_for(__event_call__(payload), timeout=RPC_TIMEOUT_SECONDS)
        except TimeoutError:
            return await fail("browser_timeout")
        except Exception:
            return await fail("browser_error")
        if not isinstance(response, dict):
            return await fail("reply_malformed")
        fault = _reply_fault(response)
        if fault is not None:
            return await fail(fault)
        stdout = response.get("stdout")
        description = parse_description(stdout) if isinstance(stdout, str) else None
        if description is None:
            return await fail("no_description")
        sources = Sources(
            tuple((file.path.removeprefix(UPLOAD_DIR), file.content) for file in files),
            receipt.request_text,
            self._ANCHORING,
            receipt.aliases,
        )
        verdict = judge(description, sources)
        if not isinstance(verdict, Passed):
            return await fail(verdict.reason, verdict.site)
        uri = _png_uri(cast("str", stdout))
        if uri is None:
            return await fail("no_image")
        try:
            await __event_emitter__(
                {"type": "files", "data": {"files": [{"type": "image", "url": uri}]}}
            )
        except Exception:
            return await fail("publish_failed")
        await _diagnose(__event_emitter__, None, __metadata__, self._ANCHORING, evidence)
        japanese = _japanese(__metadata__)
        interpretation = verdict.interpretation_ja if japanese else verdict.interpretation
        return _rewrite(body, f"{PASS_TEXT}\n\n{interpretation}")
'''

_SOURCES["webui.paste_in.demo_filter"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The demo's filter: the production filter under the demo's anchoring + inlet templates.

The demo keeps Q8's substitution rule, the rule its OWUI ran before Q37, while production
(`paste-in/`) runs strict anchoring. Everything else is the production filter, inherited.
"""

from verifier.figure.anchoring import Anchoring
from webui.paste_in.filter import Filter as ProductionFilter
from webui.paste_in.templates import DEMO_TEMPLATES, Templates


class Filter(ProductionFilter):
    """The demo's global filter; the inlet and outlet are inherited unchanged."""

    _ANCHORING: Anchoring = "substitution"
    # The demo adapter wraps a bare-source reply as the tool call, so its templates ask for one.
    _TEMPLATES: Templates = DEMO_TEMPLATES
'''

_ROOT = "webui.paste_in.demo_filter"


def _load() -> types.ModuleType:
    """Execute each embedded module in its own namespace and restore the embedded module slots.

    Registration comes first for every name, which is what lets a submodule import resolve before
    its package `__init__` has run; the blobs then execute in dependency order, so each `from X
    import Y` finds `Y` already bound. Each source is stored with one leading newline, stripped
    here so the executed bytes equal the tracked file's.

    The embedded-name registration is undone in `finally`; newly imported standard-library
    modules remain loaded. This file runs inside Open WebUI's process, so an embedded-name residue
    would shadow, or be shadowed by, whatever else that process imports.
    """
    saved = {name: sys.modules.get(name) for name in _SOURCES}
    modules = {}
    for name in _SOURCES:
        module = types.ModuleType(name)
        module.__path__ = []  # treat every name as a package so submodule lookups resolve
        modules[name] = module
        sys.modules[name] = module
    try:
        for name, source in _SOURCES.items():
            # The figure reader ships its own text to the browser (M19), so each module keeps it.
            modules[name].__dict__["__paste_in_source__"] = source[1:]
            code = compile(source[1:], f"<paste-in:{name}>", "exec")
            exec(code, modules[name].__dict__)  # noqa: S102 - embedding IS this file's job
        return modules[_ROOT]
    finally:
        for name, previous in saved.items():
            if previous is None:
                del sys.modules[name]
            else:
                sys.modules[name] = previous


Filter = _load().Filter
