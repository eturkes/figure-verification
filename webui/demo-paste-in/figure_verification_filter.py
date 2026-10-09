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
    dates: tuple[tuple[float, str | None], ...]
    calls: tuple[tuple[str, int], ...]


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
    calls: tuple[tuple[str, int], ...]
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


def _calls(value: object) -> tuple[tuple[str, int], ...]:
    if type(value) is not dict:
        raise _InvalidError
    return tuple((_str(key), _int(line)) for key, line in value.items())


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
import json
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
                self.__dict__.setdefault("_fv_calls", {})[slot] = line
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


def _formatter(axis: Any) -> tuple[str, str]:
    """The tick formatter's class, and the module whose code writes the label text."""
    formatter = axis.get_major_formatter()
    function = getattr(formatter, "func", None)
    while isinstance(function, functools.partial):
        function = function.func
    owner = type(formatter) if function is None else function
    return type(formatter).__name__, str(owner.__module__)


def _axis(axes: Any, axis: Any, positions: Iterable[object]) -> dict[str, Any]:
    low, high = (float(value) for value in axis.get_view_interval())
    lo, hi = min(low, high), max(low, high)
    formatter = axis.get_major_formatter()
    name, module = _formatter(axis)
    kind = _axis_kind(axis)
    ticks: list[list[object]] = []
    if axes.axison and axis.get_visible():
        for tick in axis.get_major_ticks():
            position = float(tick.get_loc())
            shown = [label for label in (tick.label1, tick.label2) if label.get_visible()]
            if lo <= position <= hi and shown:
                ticks.append([_number(position), _cut(shown[0].get_text())])
    mapping = axis.units._mapping if kind == "category" else None
    dates: list[list[object]] = []
    if kind == "date":
        wanted = {p for p in positions if isinstance(p, float)}
        wanted |= {t[0] for t in ticks if isinstance(t[0], float)}
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

_SOURCES["verifier.pysrc.position"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Where in the submitted program a verdict points: integer spans and statement roles, no bytes.

A position is diagnostic and never part of a verdict's identity. The wrapper that shows a user the
refused code quotes the program it already holds; the core only says where to look, so no model
byte enters a verdict through this module.

`Span` follows `ast`: lines count from 1 at `\\r\\n`, `\\r` or `\\n` (never `str.splitlines`'s wider
set), columns are UTF-8 byte offsets within the line, and the end is exclusive. A span whose end
equals its start is a POINT: a place with no character, such as the end of a line.
"""

import re
from dataclasses import dataclass
from typing import Literal, Protocol, cast

Role = Literal[
    "import", "source", "data", "mark", "title", "xlabel", "ylabel", "decoration", "layout", "show"
]

_NEWLINE = re.compile(r"\r\n|\r|\n")


@dataclass(frozen=True, slots=True)
class Span:
    line: int
    column: int
    end_line: int
    end_column: int


@dataclass(frozen=True, slots=True)
class Step:
    """One top-level statement and the part it plays in the chart."""

    role: Role
    span: Span


type Trace = tuple[Step, ...]


class _Located(Protocol):
    """An `ast` statement or expression, typed structurally: the pre-scan imports this module and
    must not import `ast`."""

    lineno: int
    col_offset: int
    end_lineno: int | None
    end_col_offset: int | None


def node_span(node: _Located) -> Span:
    # Every node `ast.parse` returns carries its end; only hand-built nodes lack one.
    return Span(
        node.lineno, node.col_offset, cast("int", node.end_lineno), cast("int", node.end_col_offset)
    )


def _utf8_length(text: str) -> int:
    # `surrogatepass`: a lone surrogate reaches here only as the character a refusal points at.
    return len(text.encode("utf-8", "surrogatepass"))


class SourceMap:
    """Character offsets in one text -> spans. Every offset is clamped into the text, so a locator
    fed a position past the end still returns a valid span rather than raising."""

    def __init__(self, text: str) -> None:
        self._text = text
        breaks = list(_NEWLINE.finditer(text))
        self._starts = [0, *(match.end() for match in breaks)]
        self._ends = [*(match.start() for match in breaks), len(text)]
        # `tokenize` reads through `readline`, which splits at `\n` alone.
        self._token_starts = [0, *(match.end() for match in re.finditer("\n", text))]

    def _locate(self, offset: int) -> tuple[int, int]:
        """`(line index, offset)`, the offset clamped into the text and off any line break: a
        break belongs to the end of the line it closes."""
        offset = max(0, min(offset, len(self._text)))
        # Linear: a locator runs once or twice per refusal, over a program the byte cap bounds.
        index = sum(1 for start in self._starts if start <= offset) - 1
        return index, min(offset, self._ends[index])

    def _position(self, offset: int) -> tuple[int, int]:
        index, offset = self._locate(offset)
        return index + 1, _utf8_length(self._text[self._starts[index] : offset])

    def span(self, start: int, end: int) -> Span:
        line, column = self._position(start)
        end_line, end_column = self._position(max(start, end))
        return Span(line, column, end_line, end_column)

    def char(self, offset: int) -> Span:
        """The one character at `offset`, or a point where there is none (a line break, the end)."""
        index, start = self._locate(offset)
        return self.span(start, start + 1 if start < self._ends[index] else start)

    def offset(self, line: int, column: int) -> int:
        """`line` in the `Span` convention, `column` in characters."""
        index = max(0, min(line - 1, len(self._starts) - 1))
        start = self._starts[index]
        return start + max(0, min(column, self._ends[index] - start))

    def token_offset(self, row: int, column: int) -> int:
        """`tokenize`'s `(row, column)`: rows split at `\\n` alone, columns in characters, clamped
        into the row -- its `unexpected EOF` error counts the row's BYTES instead (measured on
        3.13), and the clamp keeps that past-the-end column on its own row."""
        index = max(0, min(row - 1, len(self._token_starts) - 1))
        start = self._token_starts[index]
        end = self._token_starts[index + 1] - 1 if index + 1 < len(self._token_starts) else None
        return min(start + max(0, column), len(self._text) if end is None else end)

    def syntax_error(self, error: SyntaxError) -> tuple[Span, ...]:
        """Where `ast.parse` stopped: `lineno` + 1-based CHARACTER `offset`, the end used only
        when it lies after the start (CPython reports 0 or -1 for an unknown end)."""
        if error.lineno is None:
            return ()
        start = self.offset(error.lineno, (error.offset or 1) - 1)
        end = start
        if error.end_lineno is not None and error.end_offset is not None:
            end = self.offset(error.end_lineno, error.end_offset - 1)
        return (self.span(start, end) if end > start else self.char(start),)

    def token_error(self, position: object) -> tuple[Span, ...]:
        """Where `tokenize` stopped: `(row, 1-based column)` in its own `\\n`-only rows."""
        match position:
            case (int() as row, int() as column):
                return (self.char(self.token_offset(row, column - 1)),)
            case _:
                return ()
'''

_SOURCES["verifier.pysrc.spec"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Core plot spec — what the verifier claims an admitted program draws.

Stdlib-only frozen dataclasses, deliberately not the `msgspec` structs of `verifier.schema`: M14
inlines this package into one pasted file, so a dependency here becomes a dependency there.

The spec holds NO `ast` node, line number or raw source text; only what the figure states survives,
its literal labels and source path included. Two consequences that are the point: a projection is
comparable by value, and no unprojected program byte can ride a verdict into a log.

Numbers are exact `Fraction`. A source `0.1` is projected as `Fraction(0.1)` -- the exact float64
the executed program actually passes to numpy -- and NOT as `Fraction(1, 10)`, which is the decimal
a reader means but not the value that runs. Projection is faithful to execution; the gap between
the two spellings belongs to the comparison layer, which has to state which one it is checking.
"""

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

# Closed vocabularies. Each mirrors an `admit.py` allowlist entry, stripped of its `np.` alias:
# admission decides which SOURCE spellings exist, projection names the MEANINGS they map onto.
type FnName = Literal["sin", "cos", "tan", "exp", "log", "sqrt", "abs"]
type ConstName = Literal["pi", "e"]
type BinOp = Literal["add", "sub", "mul", "div", "pow"]
# Sampled functions are line or scatter, never bar: a bar's length encodes a categorical magnitude
# from a zero baseline, which a continuous sample has no claim to. Mirrors `schema.FormulaMark`.
type FormulaMark = Literal["line", "scatter"]
# The dataset arm adds bar: a CSV column carries the categorical magnitude a bar's length claims.
# `barh` is the same claim rotated -- the length still encodes magnitude from a zero baseline, so it
# carries bar's integrity rules unchanged and differs only in the axis the renderer draws it on.
type DatasetMark = Literal["line", "scatter", "bar", "barh"]
# Grouped reductions, closed. Each one is a total function from a group's cells to one number, which
# is what lets recomputation reproduce it exactly; a reduction needing a parameter (quantile, std's
# delta degrees of freedom) would need that parameter projected and is therefore not a member.
type Reduction = Literal["sum", "mean", "min", "max"]

# Request anchoring (Q37): `strict` = production, `substitution` = the demo's shipped Q8 rule.
type Anchoring = Literal["strict", "substitution"]
# Admin-declared column aliases (Q43): (column, alias) pairs, each alias another name of the column
# wherever a request or label names a header column. Admin configuration, never model-supplied.
type Aliases = tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class Num:
    """One exact literal."""

    value: Fraction


@dataclass(frozen=True, slots=True)
class Var:
    """The grid variable -- the sample point. Nameless on purpose.

    A projected expression has exactly one free variable, so carrying the model's chosen spelling
    would make two programs that compute the same thing project to unequal specs. It also lets the
    bound form (`x = np.linspace(...)`) and the inline form (`plt.plot(np.linspace(...), ...)`)
    compare equal, which is what makes the two spellings one projection.
    """


@dataclass(frozen=True, slots=True)
class Const:
    """`np.pi` or `np.e`, held symbolically -- neither has an exact `Fraction`."""

    name: ConstName


@dataclass(frozen=True, slots=True)
class Neg:
    operand: "Expr"


@dataclass(frozen=True, slots=True)
class Fn:
    name: FnName
    arg: "Expr"


@dataclass(frozen=True, slots=True)
class Bin:
    op: BinOp
    left: "Expr"
    right: "Expr"


type Expr = Num | Var | Const | Neg | Fn | Bin

# The deepest expression tree the core walks recursively (Q34). Projection refuses a deeper program
# expression, the request grammar names no target for a deeper request expression, and
# `project.same_bound` never folds a deeper declared bound. Every level costs a few Python frames,
# so this sits far below the interpreter's recursion limit while far above any chart program.
MAX_EXPR_DEPTH = 100


def expr_height(expr: Expr) -> int:
    """Levels in `expr`, counted without recursion: a flat 10,000-term sum is 10,000 levels."""
    deepest = 0
    stack: list[tuple[Expr, int]] = [(expr, 1)]
    while stack:
        node, level = stack.pop()
        deepest = max(deepest, level)
        if isinstance(node, Bin):
            stack += ((node.left, level + 1), (node.right, level + 1))
        elif isinstance(node, Neg):
            stack.append((node.operand, level + 1))
        elif isinstance(node, Fn):
            stack.append((node.arg, level + 1))
    return deepest


@dataclass(frozen=True, slots=True)
class Grid:
    """The sample points, as one shape for every admitted grid call.

    `stop` is INCLUSIVE -- it is the last sample, not `np.arange`'s excluded bound. Normalizing
    `arange` onto this triple is what lets a projection compare two source spellings of one grid
    by value, and it is why `arange` needs rational bounds while `linspace` does not.
    """

    start: Expr
    stop: Expr
    samples: int


@dataclass(frozen=True, slots=True)
class Interval:
    """The user-stated x interval, with an inclusive stop and no promised sample count."""

    start: Expr
    stop: Expr


@dataclass(frozen=True, slots=True)
class Labels:
    """Everything the figure says about itself, for tier-3 publication.

    Carried through the projection rather than discarded because the certificate publishes what
    was verified in plain words, and a label that disagrees with the computation is a finding.
    """

    title: str | None = None
    xlabel: str | None = None
    ylabel: str | None = None
    series: str | None = None
    legend: bool = False
    grid: bool = False
    # Presentation, and DATA-EFFECT-FREE by construction: none of the three can change a value in
    # the plotted table. They are carried rather than discarded because admission admits nothing it
    # cannot represent -- a projection that dropped them would be silently ignoring a statement.
    # `figsize` is exact `Fraction` for the same reason every other projected number is: the figure
    # size the program passes is the size it passes, and a float would round it.
    figsize: tuple[Fraction, Fraction] | None = None
    tick_rotation: Fraction | None = None
    tight_layout: bool = False


@dataclass(frozen=True, slots=True)
class FormulaPlot:
    """A function sampled over a grid: the arm where the request sentence is the specification."""

    mark: FormulaMark
    grid: Grid
    y: Expr
    labels: Labels


@dataclass(frozen=True, slots=True)
class DatasetRef:
    """The user's file, as the program names it.

    `path` is the EXACT string literal passed to `read_csv`, never a resolved or normalized path:
    binding it to the bytes the user actually uploaded is a CHECK the comparison layer performs
    against a caller-supplied target, not a fact the projection may invent. Keeping it verbatim is
    what lets that check compare the program's own claim against the user's own artifact.
    """

    path: str


@dataclass(frozen=True, slots=True)
class Column:
    """One column of the bound frame, named by the string literal that selected it."""

    name: str


@dataclass(frozen=True, slots=True)
class DatasetPlot:
    """Two columns of the user's file: the clinical spine, and the demo's acceptance surface.

    Bar is admitted here and refused in the formula arm. That asymmetry is G5, not an oversight: a
    bar's length encodes a categorical magnitude from a zero baseline, which a CSV column supports
    and a continuous sample has no claim to.
    """

    mark: DatasetMark
    source: DatasetRef
    x: Column
    y: Column
    labels: Labels
    # `None` is the column pair M13.4 admitted: x and y are read row for row. A reduction means
    # `x.groupby(<x>)[<y>].<group>()`, so the group KEY is the x channel and the REDUCED column is
    # the y channel, and one row of the plotted table is one group rather than one file row. No new
    # union member and no new total map: a reduction changes how the two named columns combine, not
    # what the spec is.
    group: Reduction | None = None


# The union M13.4 widened. Every total map over it needs its own exact-set pin: this repo has
# shipped a defect where a union grew and a total map over it stayed green.
type CorePlotSpec = FormulaPlot | DatasetPlot


@dataclass(frozen=True, slots=True)
class DatasetTarget:
    """The user's uploaded file, as BYTES -- never as a path the core would open.

    Carrying the content is what makes dataset recomputation possible at all: the core is pure and
    has no filesystem, so a bare path would name an artifact it could never read. `path` is
    compared byte-for-byte against the string literal the program passed to `read_csv`; the caller
    derives both fields from ONE authenticated upload, so the comparison is name-binding and the
    content is byte-binding, and neither substitutes for the other.
    """

    path: str
    content: bytes
    # The user's request text, when the caller has it: lexical anchoring (Q8) checks the program's
    # columns against the header names it states. `None` anchors nothing.
    request: str | None = None
    # The anchoring rule (Q37). Production = strict: a request naming or negating a column must
    # name every drawn column it can name. The demo keeps Q8's substitution rule.
    anchoring: Anchoring = "strict"
    # The admin's column aliases (Q43); `()` = header names alone.
    aliases: Aliases = ()


@dataclass(frozen=True, slots=True)
class FormulaTarget:
    """An expression the USER stated, already parsed into the core's own tree.

    The core's request grammar builds this tree from the user's request sentence, independently of
    the model-authored program. `Interval` binds only the stated bounds; `Grid` also binds a stated
    sample count. A headless caller may omit the target, but that verdict claims only internal
    consistency and publishes the gap.
    """

    y: Expr
    grid: Grid | Interval | None = None


type DeclaredTarget = DatasetTarget | FormulaTarget
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


def _numeric_ok(position: float, text: str, axis: Axis) -> bool:
    readings = _reading(_plain(text))
    if readings is None:
        return False
    scale = 10.0**axis.order
    for value, half in readings:
        shown = value * scale + axis.offset
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
    return None
'''

_SOURCES["verifier.pysrc.errors"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Refusal and caller-error types for the portable core.

Two families, deliberately unrelated: `PysrcRefusalError` is a verdict about UNTRUSTED input and is
always convertible into a check result, while `PysrcCallerError` means the operator configured the
verifier wrongly and no verdict about the source exists. Collapsing them would let a
misconfiguration read as a refused program.

A refusal carries a closed `code` and never any bytes from the source. Echoing input back into a
message would smuggle model-authored text into logs, verdicts and, through those, into the operator
surface -- the one place this project must never let the model write.
"""

from typing import Literal

from verifier.pysrc.position import Role, Span

# Closed set. A new member needs a distinct fault shape, not a new phrasing of an existing one.
# Grouped by the stage that can raise it; a stage never raises another stage's code.
RefusalCode = Literal[
    # prescan
    "source_too_large",
    "source_not_utf8",
    "source_has_nul",
    "line_too_long",
    "source_not_tokenizable",
    "too_many_tokens",
    "nesting_too_deep",
    "unbalanced_brackets",
    "indent_too_deep",
    # admit
    "source_not_parsable",
    "statement_not_admitted",
    "expression_not_admitted",
    "import_not_admitted",
    "assign_target_not_admitted",
    "call_target_not_admitted",
    "keyword_not_admitted",
    "attribute_not_admitted",
    "operator_not_admitted",
    "literal_not_admitted",
    "name_not_bound",
    # project -- what an ADMITTED program fails to say about the figure it draws. Distinct from
    # admission: these bytes may run, and the refusal is that the verifier cannot state what they
    # would draw. A construct admitted without a projection rule lands on one of these, never on
    # silence.
    "no_mark",
    "multiple_marks",
    "mark_arity_not_projected",
    "mark_not_valid_for_arm",
    "x_not_a_grid",
    "y_not_over_grid",
    "grid_not_representable",
    "expression_not_projected",
    "label_not_literal",
    "name_rebound",
    "no_terminal",
    "statement_after_terminal",
    "statement_not_projected",
    # project, dataset arm -- each names a fault shape the formula arm cannot produce.
    "arm_ambiguous",
    "no_source",
    "multiple_sources",
    "source_not_literal",
    "column_not_literal",
    "column_not_from_source",
    # An admitted `groupby` chain whose MEANING the projection cannot state. Distinct from
    # `statement_not_projected`: the statement is a projectable kind, and distinct from
    # `column_not_from_source`: the columns may be perfectly valid. What is missing is a rule for
    # the shape -- `.reset_index()` re-spells the channels, a bare column selection reduces nothing.
    "aggregation_not_projected",
    # `plt.figure` after anything already drawn. The new figure would not contain it, so the
    # emitted artifact and the spec would disagree about what the chart holds. Distinct from
    # `statement_not_projected`: the call IS projectable, just not in that position.
    "figure_orphans_mark",
    # bind -- the submitted program versus the artifact the USER supplied. One code covers both
    # arms: the fault shape is "this program is not about your artifact", and which artifact is
    # evident from the program itself.
    "source_not_supplied",
    "target_mismatch",
    # A substitution (Q8): the program drops a CSV column the request names and plots one the
    # request never names. A request naming no column anchors nothing and never reaches this code.
    "column_not_requested",
    # Strict anchoring (Q37, production): the request names or negates a column, and the program
    # draws a nameable column the request never names.
    "column_not_named",
    # recompute -- reading the user's bytes, then evaluating. `value_not_finite` is the SOLE
    # domain refusal: the evaluator reproduces numpy's IEEE results instead of raising, so every
    # domain and overflow fault arrives as a non-finite value and needs no classification.
    "csv_too_large",
    "csv_not_parsable",
    "column_not_present",
    "column_not_numeric",
    "value_not_in_profile",
    "value_not_finite",
    "work_budget_exceeded",
    # integrity -- what an otherwise-recomputable figure would misrepresent.
    "category_not_unique",
    "x_not_ordered",
    # G10 (Q16): a title, axis label or legend label names a CSV column the chart does not draw,
    # or -- over a reduction -- the summary word of another reduction.
    "label_not_consistent",
]


class PysrcRefusalError(Exception):
    """The submitted source is refused. `code` is the whole verdict; there is no free text.

    `at` = where in the program the refusal points, `()` for a whole-program fault; `role` = the
    kind of statement to point at instead, for a stage that sees the spec rather than the tree.
    Both are diagnostics: integers and a closed role, never source bytes.
    """

    def __init__(
        self, code: RefusalCode, *, at: tuple[Span, ...] = (), role: Role | None = None
    ) -> None:
        super().__init__(code)
        self.code: RefusalCode = code
        self.at = at
        self.role = role


class PysrcCallerError(Exception):
    """The verifier was called wrongly -- a limit it cannot honour, or arguments that disagree with
    each other. Never a verdict about source, and never reachable from submitted bytes."""
'''

_SOURCES["verifier.pysrc.numeric"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Binary64 evaluation of a projected expression, and materialization of a projected grid.

Written for this job rather than ported from `verifier.expr`. `expr.py` is exact over `Fraction`
and rounds once at the end; the executed program is numpy float64 and rounds at EVERY operator, so
an exact engine computes a number the program never computes. The more precise engine is the less
faithful one, and faithfulness is the whole claim.

Every node rounds to binary64 before its parent reads it. No exact intermediate exists, and a
`Fraction` literal converts through `float()` so a source `0.1` becomes the float64 `0.1` the
program passes to numpy -- not a rounded `1/10`.

Domain and overflow faults are never raised out of here. They reproduce numpy's IEEE values, so
`x/0` is `+-inf` and `log(0)` is `-inf`, and a single downstream refusal rejects any non-finite
that reaches the table. `pow` is the one operator where reproducing numpy takes real logic; see
`_pow`.
"""

import math
from fractions import Fraction
from typing import Literal, assert_never, cast

from verifier.pysrc.budget import WorkBudget
from verifier.pysrc.spec import Bin, BinOp, Const, ConstName, Expr, Fn, FnName, Grid, Neg, Num, Var

__all__ = ["NUMERIC_PROFILE", "OPERATOR_CLASSES", "evaluate_expr", "materialize_grid"]

# Published in every certificate. The name is load-bearing: the LEGACY JSON formula mode runs
# `rational-half-even-v1` and is exact, and `examples/index.json` ships a sentence about that
# exactness. A reader must never carry one mode's guarantee onto the other, so the profiles are
# separately named and the certificate prints this one verbatim.
NUMERIC_PROFILE = "binary64-libm-v1"
OPERATOR_CLASSES: dict[str, frozenset[str]] = {
    "standard-exact": frozenset(
        {
            "add",
            "sub",
            "mul",
            "div",
            "neg",
            "abs",
            "sqrt",
            "literal",
            "pi",
            "e",
            "linspace",
            "arange",
        }
    ),
    "libm-dependent": frozenset({"sin", "cos", "tan", "exp", "log", "pow"}),
}

_NEGATIVE_NAN = -math.nan


def _fraction_float(value: Fraction) -> float:
    try:
        return float(value)
    except OverflowError:
        return -math.inf if value.numerator < 0 else math.inf


def _divide(left: float, right: float) -> float:
    try:
        return left / right
    except ZeroDivisionError:
        if math.isnan(left):
            return left
        if left == 0.0:
            return _NEGATIVE_NAN
        sign = math.copysign(1.0, left) * math.copysign(1.0, right)
        return math.copysign(math.inf, sign)


def _odd_integer(value: float) -> bool:
    return math.isfinite(value) and value.is_integer() and math.fmod(abs(value), 2.0) == 1.0


def _pow(base: float, exponent: float) -> float:
    """`math.pow` with its exceptions mapped to C99 / numpy values.

    `ValueError` is ambiguous: it covers zero-base poles and negative-base domains, which numpy
    maps to infinities and NaNs respectively. The operands, including negative zero's sign bit,
    decide which result the executed program receives.
    """
    try:
        return math.pow(base, exponent)
    except OverflowError:
        negative = base < 0.0 and _odd_integer(exponent)
        return -math.inf if negative else math.inf
    except ValueError:
        if base == 0.0:
            negative = math.copysign(1.0, base) < 0.0 and _odd_integer(exponent)
            return -math.inf if negative else math.inf
        return math.copysign(math.nan, base)


def _trig(name: Literal["sin", "cos", "tan"], value: float) -> float:
    try:
        if name == "sin":
            return math.sin(value)
        if name == "cos":
            return math.cos(value)
        if name == "tan":
            return math.tan(value)
        raise AssertionError(name)  # pragma: no cover - the literal type is closed
    except ValueError:
        return _NEGATIVE_NAN


def _exp(value: float) -> float:
    try:
        return math.exp(value)
    except OverflowError:
        return math.inf


def _log(value: float) -> float:
    try:
        return math.log(value)
    except ValueError:
        return -math.inf if value == 0.0 else math.nan


def _sqrt(value: float) -> float:
    try:
        return math.sqrt(value)
    except ValueError:
        return math.copysign(math.nan, value)


def _function(name: FnName, value: float) -> float:
    match name:
        case "sin" | "cos" | "tan":
            return _trig(name, value)
        case "abs":
            return abs(value)
        case "exp":
            return _exp(value)
        case "log":
            return _log(value)
        case "sqrt":
            return _sqrt(value)
        case _ as unreachable:  # pragma: no cover - `FnName` is closed
            assert_never(unreachable)


def _binary(operator: BinOp, left: float, right: float) -> float:
    if operator == "add":
        return left + right
    if operator == "sub":
        return left - right
    if operator == "mul":
        return left * right
    if operator == "div":
        return _divide(left, right)
    if operator == "pow":
        return _pow(left, right)
    assert_never(operator)  # pragma: no cover - `BinOp` is closed


type _CompoundExpr = Neg | Fn | Bin


def _constant(name: ConstName) -> float:
    if name == "pi":
        return math.pi
    if name == "e":
        return math.e
    assert_never(name)  # pragma: no cover - `ConstName` is closed


def _start_node(
    node: Expr,
    x: float,
    pending: list[tuple[Expr, bool]],
    values: list[float],
) -> None:
    if isinstance(node, Num):
        values.append(_fraction_float(node.value))
    elif isinstance(node, Var):
        values.append(x)
    elif isinstance(node, Const):
        values.append(_constant(node.name))
    elif isinstance(node, Neg):
        pending.extend(((node, True), (node.operand, False)))
    elif isinstance(node, Fn):
        pending.extend(((node, True), (node.arg, False)))
    elif isinstance(node, Bin):
        pending.extend(((node, True), (node.right, False), (node.left, False)))
    else:  # pragma: no cover - `Expr` is a closed union
        assert_never(node)


def _finish_node(node: _CompoundExpr, values: list[float]) -> None:
    if isinstance(node, Neg):
        values.append(-values.pop())
    elif isinstance(node, Fn):
        values.append(_function(node.name, values.pop()))
    elif isinstance(node, Bin):
        right = values.pop()
        left = values.pop()
        values.append(_binary(node.op, left, right))
    else:  # pragma: no cover - `_CompoundExpr` is a closed union
        assert_never(node)


def _evaluate_expr(
    expr: Expr,
    x: float,
    budget: WorkBudget,
    *,
    charge_nodes: bool,
) -> float:
    pending: list[tuple[Expr, bool]] = [(expr, False)]
    values: list[float] = []
    while pending:
        node, ready = pending.pop()
        if ready:
            _finish_node(cast("_CompoundExpr", node), values)
        else:
            if charge_nodes:
                budget.charge(1)
            _start_node(node, x, pending, values)
    return values[0]


def evaluate_expr(expr: Expr, x: float, budget: WorkBudget) -> float:
    """Evaluate `expr` at `x`, rounding per node and charging each node once."""
    return _evaluate_expr(expr, x, budget, charge_nodes=True)


def materialize_grid(grid: Grid, budget: WorkBudget) -> tuple[float, ...]:
    """Materialize the normalized grid without expression-node charges.

    `Grid.stop` is inclusive for both constructors -- projection already normalized `arange`'s
    excluded bound onto the inclusive triple, and `arange` bounds are integers only (M13.3).
    """
    start = _evaluate_expr(grid.start, 0.0, budget, charge_nodes=False)
    stop = _evaluate_expr(grid.stop, 0.0, budget, charge_nodes=False)
    count = grid.samples
    delta = stop - start
    divisor = count - 1
    step = delta / divisor
    if step == 0.0:
        values = tuple((float(index) / divisor) * delta + start for index in range(count))
    else:
        values = tuple(float(index) * step + start for index in range(count))
    return (*values[:-1], stop)
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
            block("tick_label_mismatch", dict(axes.calls).get(f"{name}ticks", axes.site))


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
                block("axes_twin", dict(a.calls).get("twin", b.site))
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

_SOURCES["verifier.pysrc.admit"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Positive AST allowlist for `pysrc-0.1`. This IS the pass/fail boundary.

Admission is a closed allowlist over idiom CLASSES, never a denylist of bad constructs: a node type,
call target, attribute chain, keyword or literal kind that is not named here is refused, so a
construct nobody anticipated fails closed. Dispatch is exhaustive by node type with refusal as the
tail -- a `.get(kind, default_admit)` over a variant space is this repo's most-repeated defect
class, and here it would silently widen the boundary.

`plt.subplots` and every multi-panel form are absent BY CONSTRUCTION rather than by a named ban: the
projection targets exactly one chart, so a program producing more than one Axes has nothing to
project onto, and `call_target_not_admitted` is the honest reason.

Two deliberate non-admissions worth naming, because both are calibration levers rather than safety
properties, and M13.6 measurement is what should move them:

- a module docstring (a bare `str` expression statement) refuses, since it plots nothing;
- an empty program admits, since admission answers "may these bytes run", not "do they draw" --
  projection is what demands a chart.

This module parses; it never evaluates. No `eval`, `exec`, `compile` or `getattr` appears, and a
committed search test pins that.
"""

import ast
from dataclasses import dataclass, field
from typing import NoReturn, cast

from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.position import SourceMap, Span, node_span

# Module -> required alias. The alias is fixed, not merely required: admitting an arbitrary alias
# would make every downstream target string depend on model-chosen text.
ADMITTED_IMPORTS: dict[str, str] = {"matplotlib.pyplot": "plt", "numpy": "np", "pandas": "pd"}

# Closed call-target set, spelled `<alias>.<attr>`, grouped by the idiom class each serves.
_GRID_TARGETS = frozenset({"np.linspace", "np.arange"})
_MATH_TARGETS = frozenset({"np.sin", "np.cos", "np.tan", "np.exp", "np.log", "np.sqrt", "np.abs"})
_MARK_TARGETS = frozenset({"plt.plot", "plt.scatter", "plt.bar", "plt.barh"})
_DECOR_TARGETS = frozenset({"plt.title", "plt.xlabel", "plt.ylabel", "plt.legend", "plt.grid"})
# Presentation calls, admitted because the measured proposer writes them in 16 of 25 simple prompts
# and none of them can change a plotted value. `plt.figure` is the exception that proves the class:
# a SECOND one starts a new figure and would orphan whatever was already drawn, so projection binds
# it to a position (`figure_orphans_mark`) rather than treating it as free.
_PRESENTATION_TARGETS = frozenset({"plt.figure", "plt.tight_layout", "plt.xticks"})
_TERMINAL_TARGETS = frozenset({"plt.show"})
# Exactly one reader. `read_table`, `read_excel` and friends stay out: each would need its own
# projection rule for separators, sheets and header handling before the verifier could state what
# the program reads.
_SOURCE_TARGETS = frozenset({"pd.read_csv"})
ADMITTED_CALL_TARGETS = (
    _GRID_TARGETS
    | _MATH_TARGETS
    | _MARK_TARGETS
    | _DECOR_TARGETS
    | _PRESENTATION_TARGETS
    | _TERMINAL_TARGETS
    | _SOURCE_TARGETS
)

# Keywords are closed PER TARGET: a keyword admitted on one call is not thereby admitted on
# another, because each one has to be projectable where it appears.
ADMITTED_KEYWORDS: dict[str, frozenset[str]] = {
    "np.linspace": frozenset({"num"}),
    "np.arange": frozenset(),
    "np.sin": frozenset(),
    "np.cos": frozenset(),
    "np.tan": frozenset(),
    "np.exp": frozenset(),
    "np.log": frozenset(),
    "np.sqrt": frozenset(),
    "np.abs": frozenset(),
    # Style keywords are closed PER TARGET to match matplotlib's own signature: `plot` takes a
    # linestyle, `bar` does not, and admitting one set for every mark would admit calls that would
    # raise when executed. Each carries a string literal and therefore no data. `c=` and `cmap=`
    # stay out: they are the colour-by-category channel, which encodes a column the projection
    # does not state. `s=` stays out: it is G6's area-encoding channel. `alpha=` and
    # `edgecolors=` stay out because nothing measured asks for them.
    "plt.plot": frozenset({"label", "color", "marker", "linestyle"}),
    "plt.scatter": frozenset({"label", "color", "marker"}),
    "plt.bar": frozenset({"label", "color"}),
    "plt.barh": frozenset({"label", "color"}),
    "plt.figure": frozenset({"figsize"}),
    "plt.tight_layout": frozenset(),
    "plt.xticks": frozenset({"rotation"}),
    "plt.title": frozenset(),
    "plt.xlabel": frozenset(),
    "plt.ylabel": frozenset(),
    "plt.legend": frozenset(),
    "plt.grid": frozenset(),
    "plt.show": frozenset(),
    # No `sep`, `header`, `usecols`, `dtype`: each changes what the file MEANS, so admitting one
    # without a projection rule would let the program restate the user's artifact unchecked.
    "pd.read_csv": frozenset(),
}

# Attribute reads that are values rather than call targets.
ADMITTED_CONSTANT_ATTRS = frozenset({"np.pi", "np.e"})
# `<bound name>.index` and `<bound name>.values` -- ONE idiom class, because admission has no types
# and cannot tell an aggregate from a frame. PROJECTION decides: an aggregate's index is its group
# key, while `df.values` is the whole frame as an array and refuses `column_not_from_source` there.
ADMITTED_VALUE_ATTRS = frozenset({"index", "values"})

# `(target, keyword) -> element count`. A tuple display is refused everywhere else by the expression
# tail, so this is the ONLY door a tuple enters the language by, and it is keyed per keyword rather
# than opened globally: `figsize` is the one admitted tuple.
ADMITTED_TUPLE_KEYWORDS: dict[tuple[str, str], int] = {("plt.figure", "figsize"): 2}
# Targets admitting NO positional argument, all refused here with ONE code (user ruling Q26).
# `plt.figure(1)` selects a figure by number, a figure-lifecycle effect the spec does not
# represent; `plt.xticks(ticks)` sets tick locations or labels, restating what the x axis says
# about the data; `plt.tight_layout` takes no argument the spec carries.
_NO_POSITIONAL_TARGETS = frozenset({"plt.figure", "plt.tight_layout", "plt.xticks"})

# The `groupby` idiom, admitted as ONE atomic shape rather than link by link. `_dotted` bounds an
# attribute chain to depth 1 against an `ast.Name`, so the outer `.sum` of a chain -- whose receiver
# is a `Subscript` -- would refuse before the shape could be read at all.
_GROUPBY = "groupby"
_REDUCTIONS = frozenset({"sum", "mean", "min", "max"})

# The pandas plotting ACCESSOR, `<data>.plot(kind="bar"|"line")`, written by 4 of the 25 simple
# `m13-design` captures (bar) and 5 of the 24 simple `m10-design` captures (line). It is its own
# route rather than a dotted target: its receiver is a name the MODEL bound,
# so admitting it through `ADMITTED_CALL_TARGETS` -- which is keyed by a FIXED import alias -- would
# open every `<name>.plot` at once.
_ACCESSOR_ATTR = "plot"
# `kind` is TARGET IDENTITY, not a style keyword: each value names the mark the accessor draws, and
# it maps onto that mark's own target string here so projection never defaults an unlisted spelling
# onto a line the program does not draw.
ADMITTED_ACCESSOR_KINDS: dict[str, str] = {"bar": "plt.bar", "barh": "plt.barh", "line": "plt.plot"}
# Closed exactly as `ADMITTED_KEYWORDS` is per target. `x=`/`y=` stay out: they select columns, and
# the accessor's projection reads its channels from the receiver instead.
ADMITTED_ACCESSOR_KEYWORDS = frozenset({"kind", "color"})
# Trailing calls projection UNWRAPS off an admitted chain, BY NAME. `_admit_aggregation` admits ONE
# trailing no-argument call, so `.sort_values()` arrives ALREADY ADMITTED and is refused only at
# projection; an unwrap taking whatever trailing call it finds would admit a REORDERING with nothing
# red, and both G8's row coverage and G9's ordering read off group-key order.
ADMITTED_UNWRAPPED_ATTRS = frozenset({"reset_index"})
# A fixed import alias is never an accessor receiver: `plt.plot` is a mark target and `pd.plot` /
# `np.plot` are no target at all, so all three keep resolving through `ADMITTED_CALL_TARGETS`.
_IMPORT_ALIASES = frozenset(ADMITTED_IMPORTS.values())

_ADMITTED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
_ADMITTED_UNARYOPS = (ast.USub,)

# `bool` is admitted because `plt.grid(True)` is an ordinary matplotlib idiom; which argument slots
# accept which literal kind is projection's question, not admission's.
#
# The membership test is EXACT type, not `isinstance`, so that this tuple is the whole boundary
# rather than a subclass-closed one: `bool` subclasses `int`, so under `isinstance` removing `bool`
# here would not actually refuse `True`. The two spellings agree on every input today and diverge
# the moment the set is narrowed, which is exactly when the difference has to hold.
_ADMITTED_LITERAL_TYPES = (int, float, str, bool)


@dataclass(slots=True)
class _Scope:
    """Names bound so far. Order matters: a name is admitted only after its binding statement."""

    bound: set[str] = field(default_factory=set)


def _refuse(
    code: RefusalCode, cause: BaseException | None = None, at: tuple[Span, ...] = ()
) -> NoReturn:
    raise PysrcRefusalError(code, at=at) from cause


def _dotted(node: ast.Attribute) -> tuple[str, str]:
    """Return `(alias, "alias.attr")` for a depth-1 chain, refusing anything deeper.

    Depth is bounded here rather than at the leaf: `np.random.rand` must refuse because its chain is
    two deep, not because `rand` happens to be unlisted -- otherwise adding one name to the
    allowlist could accidentally admit a whole submodule.
    """
    value = node.value
    if not isinstance(value, ast.Name):
        _refuse("attribute_not_admitted")
    if node.attr.startswith("_"):
        _refuse("attribute_not_admitted")
    return value.id, f"{value.id}.{node.attr}"


def _admit_constant_attr(node: ast.Attribute, scope: _Scope) -> None:
    """Admit a bare attribute READ, as opposed to a call target."""
    alias, dotted = _dotted(node)
    if node.attr not in ADMITTED_VALUE_ATTRS and dotted not in ADMITTED_CONSTANT_ATTRS:
        _refuse("attribute_not_admitted")
    if alias not in scope.bound:
        _refuse("name_not_bound")


def _groupby_root(node: ast.expr) -> tuple[ast.Call, ast.Name] | None:
    """The innermost `<name>.groupby(...)` call an expression is rooted in, with that name.

    Recognizing the aggregation family by its ROOT is what makes the chain admissible atomically.
    A chain rooted in anything else -- `np.random.rand`, whose spine ends at an alias attribute --
    returns `None` and keeps the depth-1 bound that refuses it.
    """
    current = node
    while True:
        if isinstance(current, ast.Call):
            func = current.func
            if not isinstance(func, ast.Attribute):
                return None
            if func.attr == _GROUPBY and isinstance(func.value, ast.Name):
                return current, func.value
            current = func.value
        elif isinstance(current, (ast.Attribute, ast.Subscript)):
            current = current.value
        else:
            return None


@dataclass(frozen=True, slots=True)
class AggregationChain:
    """The canonical `<frame>.groupby("<key>")["<column>"].<reduction>()`, read structurally."""

    frame: str
    key: str
    column: str
    reduction: str


def aggregation_chain(node: ast.expr) -> AggregationChain | None:
    """Read the canonical chain, or `None` for every other shape.

    The spine is written down ONCE, here beside the admission that closes it, and projection reads
    it back instead of restating it: two matchers over one shape drift apart silently, and only one
    of them would be the boundary.
    """
    match node:
        case ast.Call(
            func=ast.Attribute(
                value=ast.Subscript(
                    value=ast.Call(
                        func=ast.Attribute(value=ast.Name(id=frame), attr=str() as grouper),
                        args=[ast.Constant(value=str() as key)],
                        keywords=[],
                    ),
                    slice=ast.Constant(value=str() as column),
                ),
                attr=str() as reduction,
            ),
            args=[],
            keywords=[],
        ) if grouper == _GROUPBY and reduction in _REDUCTIONS:
            return AggregationChain(frame=frame, key=key, column=column, reduction=reduction)
        case _:
            return None


def accessor_receiver(node: ast.Call) -> ast.Name | None:
    """The bound NAME an accessor call draws from, or `None` for every other call shape.

    The shape is written down ONCE, here beside the admission that closes it, and projection reads
    it back instead of restating it: two matchers over one shape drift apart silently, and only one
    of them would be the boundary.

    Shape alone, refusing nothing. `<name>.plot(...)` and `<name>["<col>"].plot(...)` both return
    the ROOT name, because both are receivers the checks below have to price; deciding `kind` or
    the keywords here would land `call_target_not_admitted` on a program whose fault is positional.
    """
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != _ACCESSOR_ATTR:
        return None
    root = func.value
    if isinstance(root, ast.Subscript):
        root = root.value
    if not isinstance(root, ast.Name) or root.id in _IMPORT_ALIASES:
        return None
    return root


def accessor_is_subscripted(node: ast.Call) -> bool:
    """Whether an accessor call's receiver carries a column subscript.

    Split from `accessor_receiver` rather than folded into its return, because the two stages price
    different things about one subscript: admission prices its SLICE, projection prices its EFFECT,
    and the ROOT name is what both have to reach first. Callable only where `accessor_receiver`
    returned a name, which is what makes the cast a postcondition rather than a hope.
    """
    func = cast("ast.Attribute", node.func)
    return isinstance(func.value, ast.Subscript)


def accessor_kind(node: ast.Call) -> str | None:
    """The accessor's `kind=` string literal, or `None` when it is absent or not a string."""
    for keyword in node.keywords:
        if keyword.arg == "kind":
            value = keyword.value
            if isinstance(value, ast.Constant) and type(value.value) is str:
                return value.value
            return None
    return None


def _admit_accessor(node: ast.Call, receiver: ast.Name, scope: _Scope) -> None:
    """`<data>.plot(kind="<mark>")`, closed on its own shape.

    Refusal order is the contract's: the keyword allowlist prices the call's SHAPE, `kind` then
    prices its TARGET, and the receiver's binding is checked last -- the same target-before-bound
    order `_admit_call` keeps, so the two routes tell an author the same thing about one program.
    """
    if node.args:
        # The accessor's positional slot is `x`, which selects a column the projection reads from
        # the receiver instead. Two channel sources for one mark is not a shape it can state.
        _refuse("keyword_not_admitted")
    for keyword in node.keywords:
        # `arg is None` is `**kwargs`, whose keyword set is not statically known at all.
        if keyword.arg is None or keyword.arg not in ADMITTED_ACCESSOR_KEYWORDS:
            _refuse("keyword_not_admitted")
    if accessor_kind(node) not in ADMITTED_ACCESSOR_KINDS:
        # Unlisted, non-literal and ABSENT all land here: `kind` is the target, so a call whose
        # target cannot be read names no admitted target at all. Absent defaults to a line in
        # pandas, and defaulting is what a closed map exists to refuse.
        _refuse("call_target_not_admitted")
    if receiver.id not in scope.bound:
        _refuse("name_not_bound")
    # `accessor_receiver` reached `receiver` by walking `node.func`, so an `ast.Attribute` here is
    # its postcondition rather than a hope.
    func = cast("ast.Attribute", node.func)
    if isinstance(func.value, ast.Subscript):
        _admit_string_index(func.value.slice)
    for keyword in node.keywords:
        _admit_expr(keyword.value, scope)


def _admit_string_index(node: ast.expr) -> None:
    """A string-literal column name. A tuple selection (`[["a", "b"]]`) lands here and refuses."""
    if not isinstance(node, ast.Constant) or type(node.value) is not str:
        _refuse("column_not_literal")


def _admit_reduction_chain(node: ast.Call, root: ast.Call) -> None:
    """The two links above the root: `["<col>"]`, then `.<reduction>()` with no argument."""
    if node.args or node.keywords:
        # A reduction carrying `axis=` or a positional computes something else entirely.
        _refuse("keyword_not_admitted")
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in _REDUCTIONS:
        _refuse("attribute_not_admitted")
    selection = func.value
    if not isinstance(selection, ast.Subscript) or selection.value is not root:
        _refuse("attribute_not_admitted")
    _admit_string_index(selection.slice)


def _admit_aggregation(node: ast.Call, root: ast.Call, frame: ast.Name, scope: _Scope) -> None:
    """Admit the `groupby` idiom as one closed shape. Three spellings pass.

    The bare `<frame>.groupby("<key>")`, the canonical
    `<frame>.groupby("<key>")["<col>"].<reduction>()`, and that chain carrying ONE trailing no-
    argument call. The trailing call is admitted as a CLASS and unwrapped by name: projection reads
    `ADMITTED_UNWRAPPED_ATTRS` and refuses every other spelling, `.sort_values()` included, so
    `aggregation_not_projected` names an unstatable meaning where `attribute_not_admitted` would
    blame the attribute. The bare `groupby` admits for the same reason and reduces nothing.
    """
    if frame.id not in scope.bound:
        _refuse("name_not_bound")
    if len(root.args) != 1 or root.keywords:
        _refuse("column_not_literal")
    _admit_string_index(root.args[0])
    if node is root:
        return
    # `_groupby_root` reached `root` by walking `node.func`, so an `ast.Attribute` here is its
    # postcondition rather than a hope. Casting instead of re-testing keeps the branch out of the
    # module: an arm no input can take is one the coverage gate cannot price.
    func = cast("ast.Attribute", node.func)
    reduction = node
    receiver = func.value
    if isinstance(receiver, ast.Call) and receiver is not root:
        if func.attr.startswith("_") or node.args or node.keywords:
            _refuse("attribute_not_admitted")
        reduction = receiver
    _admit_reduction_chain(reduction, root)


def _admit_call_or_aggregation(node: ast.Call, scope: _Scope) -> None:
    """Route one call: two idioms close on their own shape, everything else by target."""
    receiver = accessor_receiver(node)
    if receiver is not None:
        _admit_accessor(node, receiver, scope)
        return
    rooted = _groupby_root(node)
    if rooted is None:
        _admit_call(node, scope)
        return
    root, frame = rooted
    _admit_aggregation(node, root, frame, scope)


def _admit_number_tuple(node: ast.expr, arity: int) -> None:
    """A fixed-arity tuple of NUMERIC literals, admitted in one keyword slot and nowhere else."""
    if not isinstance(node, ast.Tuple) or len(node.elts) != arity:
        _refuse("literal_not_admitted")
    for element in node.elts:
        # Exact type: `bool` subclasses `int`, and `figsize=(True, 6)` is not a figure size.
        if not isinstance(element, ast.Constant) or type(element.value) not in (int, float):
            _refuse("literal_not_admitted")


def _admit_call(node: ast.Call, scope: _Scope) -> None:
    func = node.func
    if not isinstance(func, ast.Attribute):
        _refuse("call_target_not_admitted")
    alias, target = _dotted(func)
    if target not in ADMITTED_CALL_TARGETS:
        _refuse("call_target_not_admitted")
    if alias not in scope.bound:
        _refuse("name_not_bound")
    admitted = ADMITTED_KEYWORDS[target]
    for keyword in node.keywords:
        # `arg is None` is `**kwargs`, whose keyword set is not statically known at all.
        if keyword.arg is None or keyword.arg not in admitted:
            _refuse("keyword_not_admitted")
        arity = ADMITTED_TUPLE_KEYWORDS.get((target, keyword.arg))
        if arity is None:
            _admit_expr(keyword.value, scope)
        else:
            _admit_number_tuple(keyword.value, arity)
    if node.args and target in _NO_POSITIONAL_TARGETS:
        _refuse("keyword_not_admitted")
    for arg in node.args:
        # `*args` arrives as `ast.Starred`, which the expression tail refuses.
        _admit_expr(arg, scope)


def _admit_expr(node: ast.expr, scope: _Scope) -> None:  # noqa: PLR0912 - one closed dispatch
    """Admit one expression; a refusal points at the innermost expression that raised it.

    The location is attached HERE, in the recursing frame itself: a wrapper function would double
    the Python frames per nesting level and halve the depth a program can reach before the
    interpreter's recursion limit.
    """
    try:
        if isinstance(node, ast.Constant):
            if type(node.value) not in _ADMITTED_LITERAL_TYPES:
                _refuse("literal_not_admitted")
        elif isinstance(node, ast.Name):
            if node.id not in scope.bound:
                _refuse("name_not_bound")
        elif isinstance(node, ast.Attribute):
            _admit_constant_attr(node, scope)
        elif isinstance(node, ast.Call):
            _admit_call_or_aggregation(node, scope)
        elif isinstance(node, ast.BinOp):
            if not isinstance(node.op, _ADMITTED_BINOPS):
                _refuse("operator_not_admitted")
            _admit_expr(node.left, scope)
            _admit_expr(node.right, scope)
        elif isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, _ADMITTED_UNARYOPS):
                _refuse("operator_not_admitted")
            _admit_expr(node.operand, scope)
        elif isinstance(node, ast.Subscript):
            _admit_column(node, scope)
        else:
            # The closed tail: comprehensions, lambdas, f-strings, list/dict/set/tuple displays,
            # starred args, walrus, comparisons, boolean and conditional expressions.
            _refuse("expression_not_admitted")
    except PysrcRefusalError as exc:
        exc.at = exc.at or (node_span(node),)
        raise


def _admit_column(node: ast.Subscript, scope: _Scope) -> None:
    """`<bound name>["<literal>"]` and nothing else.

    Narrower than it looks by accident: a slice, a tuple index, `df[cols]` and `df.loc[...]` all
    land on a refusal, because each selects something the projection has no rule for. `.loc`/`.iloc`
    additionally fail at the attribute check, which is the near-miss this shape has to survive.
    """
    if not isinstance(node.value, ast.Name):
        _refuse("expression_not_admitted")
    if node.value.id not in scope.bound:
        _refuse("name_not_bound")
    index = node.slice
    if not isinstance(index, ast.Constant) or type(index.value) is not str:
        _refuse("column_not_literal")


def _admit_import(node: ast.Import, scope: _Scope) -> None:
    for alias in node.names:
        required = ADMITTED_IMPORTS.get(alias.name)
        if required is None or alias.asname != required:
            _refuse("import_not_admitted")
        scope.bound.add(required)


def _admit_assign(node: ast.Assign, scope: _Scope) -> None:
    if len(node.targets) != 1:
        _refuse("assign_target_not_admitted")
    target = node.targets[0]
    if not isinstance(target, ast.Name):
        _refuse("assign_target_not_admitted")
    if target.id.startswith("_"):
        _refuse("assign_target_not_admitted")
    # Right-hand side first, then bind: `x = x + 1` must refuse while `x` is still unbound.
    _admit_expr(node.value, scope)
    scope.bound.add(target.id)


def _admit_stmt(node: ast.stmt, scope: _Scope) -> None:
    if isinstance(node, ast.Import):
        _admit_import(node, scope)
    elif isinstance(node, ast.Assign):
        _admit_assign(node, scope)
    elif isinstance(node, ast.Expr):
        # A bare expression statement is admitted only as a call: a lone name, literal or docstring
        # has no plotting effect, and admitting one would carry statements the projection ignores.
        value = node.value
        if not isinstance(value, ast.Call):
            _refuse("statement_not_admitted")
        _admit_call_or_aggregation(value, scope)
    else:
        # The closed tail: loops, `def`, `class`, `try`, `with`, `del`, `global`, `nonlocal`,
        # `raise`, `assert`, `async`, `from x import y`, annotated and augmented assignment.
        _refuse("statement_not_admitted")


def parse_admitted(text: str) -> ast.Module:
    """Parse and admit `text`, returning the tree. Raises `PysrcRefusalError` on refusal.

    `text` must be what `prescan` returned: the caps it charges are what bound this parse.
    """
    try:
        tree = ast.parse(text)
    # The pre-scan tokenizes but does not parse, so a tokenizable-yet-unparsable program reaches
    # here and must become a verdict rather than a traceback.
    except SyntaxError as exc:
        _refuse("source_not_parsable", exc, SourceMap(text).syntax_error(exc))

    scope = _Scope()
    for statement in tree.body:
        try:
            _admit_stmt(statement, scope)
        except PysrcRefusalError as exc:
            # A fault no expression owns -- an import, an assignment target -- is its statement's.
            exc.at = exc.at or (node_span(statement),)
            raise
    return tree
'''

_SOURCES["verifier.pysrc.limits"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Resource ceilings for the portable core.

Every value is a policy bound on UNTRUSTED input, so each is validated fail-closed before use: a
caller that passes a non-positive cap gets `PysrcCallerError`, never a silently disabled check.
"""

from dataclasses import dataclass, fields

from verifier.pysrc.errors import PysrcCallerError


@dataclass(frozen=True, kw_only=True, slots=True)
class PysrcLimits:
    """Ceilings applied before `ast.parse` sees the source.

    Defaults are sized against observed model-authored plotting programs (completion lengths of
    148-470 tokens, `archive/contracts/m12u7.md`), with headroom, not against what the parser can
    survive -- an admitted program is a short chart script or it is not admitted.
    """

    max_source_bytes: int = 20_000
    max_tokens: int = 4_000
    # A title string full of parentheses does not reach this: depth is counted from OP tokens only.
    max_bracket_depth: int = 16
    max_indent_depth: int = 4
    max_line_bytes: int = 400
    # Projection-stage ceiling, not a parse ceiling: a grid is what recomputation must evaluate
    # point by point, so the bound matches the shipped `FormulaDomain.samples` cap rather than
    # anything the parser cares about. Two points is the floor -- one point is not a curve.
    min_grid_samples: int = 2
    max_grid_samples: int = 100_000
    # Recomputation ceilings. Every one bounds work the verifier does on UNTRUSTED bytes, and each
    # is checked BEFORE the work it bounds -- a row cap read after materializing the rows buys
    # nothing. Sized for a chat attachment, not for a data warehouse.
    max_csv_bytes: int = 8_000_000
    max_csv_rows: int = 100_000
    max_csv_columns: int = 128
    max_csv_cell_bytes: int = 512
    max_table_rows: int = 100_000
    max_expr_nodes: int = 1_000
    # Groups are PLOTTED MARKS, so this is a legibility ceiling before it is a cost one: a chart
    # with a thousand bars is already unreadable, and the reduction charges work per group anyway.
    # It binds ahead of the reduction rather than after, so a high-cardinality key column refuses
    # before its groups are materialized.
    max_groups: int = 1_000
    # The binding ceiling in practice: the other caps multiply out to far more evaluation than a
    # demo may spend, so this is what refuses a program that is admissible but not affordable.
    # Measured, not guessed: `tools/bench_pysrc_work.py` on a quiet host of record put the binding
    # rate at 398,458 work/s -- the slowest of both arms, at cell width 31, where `len // 32`
    # surcharges nothing yet the bytes are still read. One second of recomputation, two significant
    # figures. Work binds before `max_table_rows` on purpose: it is size-aware and the row cap is
    # not, so a wide-celled file must refuse on what it actually costs.
    max_work: int = 390_000


DEFAULT_LIMITS = PysrcLimits()


def validate_limits(limits: PysrcLimits) -> None:
    """Refuse a configuration that would disable a ceiling. Raises `PysrcCallerError`."""
    for spec in fields(limits):
        value: int = getattr(limits, spec.name)
        if value < 1:
            message = f"limit {spec.name} must be >= 1"
            raise PysrcCallerError(message)
'''

_SOURCES["verifier.pysrc.table"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The plotted table -- recomputation's static product, and the thing the certificate binds.

The model supplies a program, never values, so no CLAIMED number exists to contradict statically.
What recomputation produces instead is this table: the x and y the verifier says the figure shows.
Whether the EMITTED artifact really shows them is not settled here and is not implied; the
certificate declares that gap open, and M10's observation is what closes it.
"""

from dataclasses import dataclass

from verifier.pysrc.errors import PysrcCallerError

__all__ = ["CellValue", "PlottedTable"]

# A categorical x is a string; every other cell is float64. There is no null and no NaN: the CSV
# profile refuses every NA spelling before a cell reaches here, which is what makes G8 hold.
type CellValue = float | str

_DOMAIN = b"pysrc-table-0.1\n"
_LENGTH_BYTES = 8


def _payload(value: CellValue) -> tuple[bytes, bytes]:
    if isinstance(value, str):
        return b"s", value.encode("utf-8")
    return b"f", value.hex().encode("ascii")


def _field(value: CellValue) -> bytes:
    kind, payload = _payload(value)
    return kind + len(payload).to_bytes(_LENGTH_BYTES, "big") + payload


@dataclass(frozen=True, slots=True)
class PlottedTable:
    """One series: x against y, in the order the figure draws them.

    Row order is the order the SOURCE itself defines: file order for a column pair, grid order in
    the formula arm, sorted key order for an aggregate -- pandas' `sort=True` default, which the
    executed program would draw. The legacy JSON mode's total sort is deliberately not reused over
    a column pair: sorting there would silently redraw a figure whose point order is part of what
    the user submitted.
    """

    x: tuple[CellValue, ...]
    y: tuple[float, ...]

    def __post_init__(self) -> None:
        """Unequal lengths are a CALLER fault, not a verdict about the source."""
        if len(self.x) != len(self.y):
            message = (
                f"plotted table length mismatch: {len(self.x)} x values, {len(self.y)} y values"
            )
            raise PysrcCallerError(message)

    def canonical_bytes(self) -> bytes:
        """One byte encoding per table value, locale-free and `repr`-free.

        Floats as `%a` hex, so a 1-ulp difference in any cell changes the bytes; string cells as
        UTF-8 behind a length prefix, so no cell's text can imitate a delimiter. Two structurally
        equal tables built by different code paths must produce identical bytes.
        """
        encoded = bytearray(_DOMAIN)
        encoded.extend(len(self.x).to_bytes(_LENGTH_BYTES, "big"))
        for x, y in zip(self.x, self.y, strict=True):
            encoded.extend(_field(x))
            encoded.extend(_field(y))
        return bytes(encoded)
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
from verifier.pysrc.spec import Reduction
from verifier.pysrc.table import CellValue

__all__ = ["Aggregated", "ColumnDtype", "aggregate_series", "column_dtype"]

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

_SOURCES["verifier.pysrc.prescan"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Bound untrusted bytes BEFORE the CPython parser sees them.

`ast.parse` executes nothing, but it recurses: deeply nested source is answered by a C-stack
failure rather than by an exception a verdict can be built from. A post-parse depth check is
therefore too late, and this module is what runs first. It imports no `ast` at all -- a committed
search test pins that -- so no path here can reach the parser early.

`tokenize` is a TCB addition for this package alone. It is chosen over a hand-rolled character scan
because it understands Python string literals: a naive scan counting `(` would refuse
`plt.title("f(x) = sin(x)")`, which is ordinary matplotlib code. It recurses nowhere, and the byte
cap is charged before it runs, so its worst case is bounded by that cap.

Order is load-bearing and cheapest-first: every step assumes its predecessors held.
"""

import io
import re
import tokenize
from tokenize import TokenInfo
from typing import NoReturn

from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.limits import PysrcLimits, validate_limits
from verifier.pysrc.position import SourceMap, Span

_OPENERS = frozenset("([{")
_CLOSERS = frozenset(")]}")


def _refuse(
    code: RefusalCode, cause: BaseException | None = None, at: tuple[Span, ...] = ()
) -> NoReturn:
    raise PysrcRefusalError(code, at=at) from cause


_BYTE_BREAK = re.compile(rb"\r\n|\r|\n")


def _decode(source: bytes) -> str:
    try:
        return source.decode("utf-8")
    except UnicodeDecodeError as exc:
        # No text exists to map, so the undecodable byte is located over the bytes themselves.
        breaks = list(_BYTE_BREAK.finditer(source, 0, exc.start))
        line = len(breaks) + 1
        column = exc.start - (breaks[-1].end() if breaks else 0)
        _refuse("source_not_utf8", exc, (Span(line, column, line, column + 1),))


def _tokenize(text: str, source: SourceMap) -> list[TokenInfo]:
    try:
        return list(tokenize.generate_tokens(io.StringIO(text).readline))
    # A malformed program must produce a verdict, never a tokenizer traceback. `TokenError` is the
    # actual shape on 3.13 (measured: unterminated string, unterminated triple-quote, trailing
    # backslash) and derives straight from `Exception`, so catching `ValueError` alone would have
    # caught nothing; `SyntaxError` is what the 3.12+ f-string tokenizer raises instead.
    except tokenize.TokenError as exc:
        # `TokenError(message, (row, column))`, the column 1-based (measured on 3.13).
        position = exc.args[1] if len(exc.args) > 1 else None
        _refuse("source_not_tokenizable", exc, source.token_error(position))
    except SyntaxError as exc:
        _refuse("source_not_tokenizable", exc, source.token_error((exc.lineno, exc.offset)))
    # CPython 3.13's tokenizer raises this while building its OWN error message for some texts
    # mixing a bare `\r` with non-ASCII (measured: 6,755 of 200,000 random fragments), so the
    # position it was reporting is lost too.
    except UnicodeDecodeError as exc:
        _refuse("source_not_tokenizable", exc)


def _token_span(token: TokenInfo, source: SourceMap) -> tuple[Span, ...]:
    start = source.token_offset(*token.start)
    return (source.span(start, source.token_offset(*token.end)),)


def _check_bracket_depth(tokens: list[TokenInfo], limit: int, source: SourceMap) -> None:
    depth = 0
    for token in tokens:
        if token.type != tokenize.OP:
            continue
        if token.string in _OPENERS:
            depth += 1
            if depth > limit:
                _refuse("nesting_too_deep", at=_token_span(token, source))
        elif token.string in _CLOSERS:
            depth -= 1
            # A closer with no opener never balances later; refusing here keeps the counter from
            # going negative and masking a genuinely deep region further on.
            if depth < 0:
                _refuse("unbalanced_brackets", at=_token_span(token, source))


def _check_indent_depth(tokens: list[TokenInfo], limit: int, source: SourceMap) -> None:
    depth = 0
    for token in tokens:
        if token.type == tokenize.INDENT:
            depth += 1
            if depth > limit:
                _refuse("indent_too_deep", at=_token_span(token, source))
        elif token.type == tokenize.DEDENT:
            depth -= 1


def prescan(source: bytes, limits: PysrcLimits) -> str:
    """Return the decoded source, or raise `PysrcRefusalError`.

    The returned text is what the caller may hand to `ast.parse`; nothing else in this package
    should parse bytes that did not come back from here.
    """
    validate_limits(limits)

    # First and unconditional: everything below is bounded by this cap, so it may not be skipped
    # or reordered. Charging it against the raw bytes also keeps a decode bomb out of memory.
    if len(source) > limits.max_source_bytes:
        _refuse("source_too_large")

    text = _decode(source)

    # The parser rejects NUL too, but only after accepting the buffer; refusing here keeps the
    # closed refusal vocabulary total over inputs the parser would answer with its own error.
    located = SourceMap(text)
    if "\x00" in text:
        _refuse("source_has_nul", at=(located.char(text.index("\x00")),))

    start = 0
    for line, ended in zip(text.splitlines(), text.splitlines(keepends=True), strict=True):
        if len(line.encode("utf-8")) > limits.max_line_bytes:
            _refuse("line_too_long", at=(located.span(start, start + len(line)),))
        start += len(ended)

    tokens = _tokenize(text, located)
    if len(tokens) > limits.max_tokens:
        _refuse("too_many_tokens")

    _check_bracket_depth(tokens, limits.max_bracket_depth, located)
    _check_indent_depth(tokens, limits.max_indent_depth, located)
    return text
'''

_SOURCES["verifier.pysrc.project"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Admitted AST -> core plot spec. This is where the projection gap is closed.

Admission answers "may these bytes run". Projection answers "what do they draw", and the verifier
stakes every downstream claim on that answer, so the gap -- *what the projection says the script
plots* vs *what the script plots when executed* -- is closed BY CONSTRUCTION here rather than
declared trusted: every admitted statement must contribute to the returned spec, and a statement
whose effect the spec cannot represent is refused. Nothing is silently ignored. A construct added
to `admit.py` without a projection rule therefore fails closed instead of vanishing from the claim.

Bound names are SUBSTITUTED away, so the spec depends on what the program computes and not on what
the model chose to call it. Two programs differing only in variable names project to equal specs.

Scope is the formula arm. `plt.bar` is refused here rather than in `admit.py` because it is
admissible in the dataset arm: what refuses it is the arm, not the call.
"""

import ast
import math
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from typing import NoReturn, assert_never, cast

from verifier.pysrc.admit import (
    ADMITTED_ACCESSOR_KINDS,
    ADMITTED_UNWRAPPED_ATTRS,
    accessor_is_subscripted,
    accessor_kind,
    accessor_receiver,
    aggregation_chain,
)
from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.limits import DEFAULT_LIMITS, PysrcLimits, validate_limits
from verifier.pysrc.position import Role, Span, Step, Trace, node_span
from verifier.pysrc.spec import (
    MAX_EXPR_DEPTH,
    Bin,
    BinOp,
    Column,
    Const,
    ConstName,
    CorePlotSpec,
    DatasetMark,
    DatasetPlot,
    DatasetRef,
    Expr,
    Fn,
    FnName,
    FormulaMark,
    FormulaPlot,
    Grid,
    Labels,
    Neg,
    Num,
    Reduction,
    Var,
    expr_height,
)

_GRID_CALLS = frozenset({"np.linspace", "np.arange"})
# Source spelling -> projected meaning. Exhaustive over `admit.ADMITTED_CALL_TARGETS`' math group;
# a target admitted but missing here reaches the closed tail and refuses.
_FUNCTIONS: dict[str, FnName] = {
    "np.sin": "sin",
    "np.cos": "cos",
    "np.tan": "tan",
    "np.exp": "exp",
    "np.log": "log",
    "np.sqrt": "sqrt",
    "np.abs": "abs",
}
_CONSTANTS: dict[str, ConstName] = {"np.pi": "pi", "np.e": "e"}
_MARKS: dict[str, FormulaMark] = {"plt.plot": "line", "plt.scatter": "scatter"}
# The same three targets, read under the other arm. Bar appears here and not above: G5 bans bar for
# SAMPLED FUNCTIONS, not for CSV columns.
_DATASET_MARKS: dict[str, DatasetMark] = {
    "plt.plot": "line",
    "plt.scatter": "scatter",
    "plt.bar": "bar",
    "plt.barh": "barh",
}
# Source spelling -> reduced meaning, mirroring `admit._REDUCTIONS`: admission decides which chains
# exist, projection names what each one computes.
_REDUCTIONS: dict[str, Reduction] = {"sum": "sum", "mean": "mean", "min": "min", "max": "max"}
_SOURCE_CALL = "pd.read_csv"
# A mark resolved at its own statement, still owing the decorations that may follow it. Holding the
# builder rather than the node is what keeps LOCAL-before-GLOBAL true for channels and arity.
type _MarkBuilder = Callable[[Labels], CorePlotSpec]


@dataclass(frozen=True, slots=True)
class _Aggregate:
    """A projected `groupby` chain: the frame it reads, its two columns, and the reduction."""

    frame: str
    key: Column
    column: Column
    reduction: Reduction


def _reset_index_inner(node: ast.Call) -> ast.Call | None:
    """The aggregation call under a trailing `.reset_index()`, or `None` for every other shape.

    The unwrap is BY NAME against `admit.ADMITTED_UNWRAPPED_ATTRS`. Admission closes the trailing
    link as a CLASS -- one no-argument, non-underscore call -- so `.sort_values()` arrives here
    already admitted; unwrapping whatever it finds would read a REORDERED series as the chain
    beneath it, and both G8's row coverage and G9's ordering are read off group-key order.
    """
    func = node.func
    if (
        not isinstance(func, ast.Attribute)
        or func.attr not in ADMITTED_UNWRAPPED_ATTRS
        or not isinstance(func.value, ast.Call)
    ):
        return None
    return func.value


def _uses_grid(tree: ast.Module) -> bool:
    """Whether a grid call appears anywhere -- the formula arm's structural selector.

    Reads the spelling INLINE and refuses nothing. This runs before any statement does, so a
    refusal here would decide the ARM for every program merely holding a call whose receiver is not
    a bare name -- and an aggregation chain is exactly that call.
    """
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and f"{node.func.value.id}.{node.func.attr}" in _GRID_CALLS
        for node in ast.walk(tree)
    )


# Admissible source, inadmissible for THIS arm: a sampled function has no categorical magnitude to
# encode as a length from a zero baseline (G5). Both bar spellings live here and in NEITHER
# `_MARKS`, so the wrong arm can never index a formula mark that does not exist.
_WRONG_ARM_MARKS = frozenset({"plt.bar", "plt.barh"})
_TERMINAL = "plt.show"
_TEXT_LABELS = frozenset({"plt.title", "plt.xlabel", "plt.ylabel"})
_FLAG_LABELS = frozenset({"plt.legend", "plt.grid"})
_FIGURE = "plt.figure"
_TIGHT_LAYOUT = "plt.tight_layout"
_XTICKS = "plt.xticks"
# Cosmetic calls: none can move a plotted number, so each projects onto a `Labels` field and the
# figure it describes is the same figure. Carrying them is what keeps "nothing is silently ignored"
# true once they are admitted.
_PRESENTATION = frozenset({_FIGURE, _TIGHT_LAYOUT, _XTICKS})

# A mark draws one series: x and y, never an implicit x and never a third positional.
_MARK_ARITY = 2
# Width and height, the only tuple the language admits at all.
_FIGSIZE_ARITY = 2
_LINSPACE_BOUNDS_ARITY = 2
_LINSPACE_FULL_ARITY = 3
_ARANGE_MAX_ARITY = 3
# Every integer up to 2**53 is exactly representable in float64; 2**52 leaves the difference of
# two bounds inside that range, which is what makes `arange`'s float64 sizing provably exact.
_EXACT_INT = 2**52

# The exact folder a grid bound and a declared target bound share (user rulings Q9 + Q17): `+ - * /`
# over literals and negations, `**` only with an integer-literal exponent of magnitude at most
# `_POW_EXPONENT_MAX`. EVERY node must also be exact in binary64 and at most `_FOLD_MAX` in
# magnitude: there Python's exact ints, numpy's float64 and IEEE's correctly rounded `+ - * /` all
# agree with the exact value, so the fold is what the executed program computes. `1/49*49` (exact
# 1, binary64 0.9999999999999999) would otherwise shift an `arange` start and change its sample
# count. A zero divisor, a wider power or an inexact node folds to None.
_POW_EXPONENT_MAX = 64
_FOLD_MAX = 2**53


def _exact_node(value: Fraction) -> Fraction | None:
    if abs(value) > _FOLD_MAX or Fraction(float(value)) != value:
        return None
    return value


def _computed(value: Fraction | None) -> Fraction | None:
    """A COMPUTED zero has a sign `Fraction` cannot carry: `0 / -1` and `-0.0` execute as -0.0,
    a different number downstream (`-1 / x` is +inf there, -inf at +0.0). Only a literal zero
    folds."""
    return None if value == 0 else value


def _fold_pow(base: Fraction, exponent_node: Expr, exponent: Fraction) -> Fraction | None:
    literal = isinstance(exponent_node, Num) or (
        isinstance(exponent_node, Neg) and isinstance(exponent_node.operand, Num)
    )
    if not literal or exponent.denominator != 1 or abs(exponent) > _POW_EXPONENT_MAX:
        return None
    if base == 0 and exponent < 0:
        return None
    return _exact_node(base ** int(exponent))


def same_bound(program: Expr, declared: Expr) -> bool:
    """Two grid bounds agree by EXACT value when both fold (user ruling Q17), else by tree.

    Shared by target binding (`verify.bind_target`) and the certificate's provenance
    (`certificate._target_consumed`), so the two can never disagree on whether a target bound.

    `np.arange(-5, 6)` projects its start to `Num(-5)` while the request keeps `-5` as `Neg(Num)`;
    both fold to -5. `fold_exact` folds only a tree binary64 computes exactly, so a bound the
    program rounds (`1/49*49`) still compares by tree and refuses.
    """
    if expr_height(declared) > MAX_EXPR_DEPTH:
        return False  # deeper than any tree projection admits: no program bound equals it
    left, right = fold_exact(program), fold_exact(declared)
    if left is not None and right is not None:
        return left == right
    return program == declared


def _fold_bin(op: BinOp, left: Fraction, right: Fraction, right_node: Expr) -> Fraction | None:
    match op:
        case "add":
            return _computed(_exact_node(left + right))
        case "sub":
            return _computed(_exact_node(left - right))
        case "mul":
            return _computed(_exact_node(left * right))
        case "div":
            return None if right == 0 else _computed(_exact_node(left / right))
        case "pow":
            return _computed(_fold_pow(left, right_node, right))
        case _:  # pragma: no cover - `BinOp` is closed
            assert_never(op)


def fold_exact(expr: Expr) -> Fraction | None:
    """The exact value of a closed arithmetic tree every node of which binary64 computes exactly."""
    if isinstance(expr, Num):
        return _exact_node(expr.value)
    if isinstance(expr, Neg):
        operand = _computed(fold_exact(expr.operand))
        return None if operand is None else -operand
    if not isinstance(expr, Bin):
        return None  # `Var`, `Const`, `Fn`: no exact rational
    left, right = fold_exact(expr.left), fold_exact(expr.right)
    if left is None or right is None:
        return None
    return _fold_bin(expr.op, left, right, expr.right)


_BINOPS: dict[type[ast.operator], BinOp] = {
    ast.Add: "add",
    ast.Sub: "sub",
    ast.Mult: "mul",
    ast.Div: "div",
    ast.Pow: "pow",
}


def _refuse(code: RefusalCode, at: tuple[Span, ...] = ()) -> NoReturn:
    raise PysrcRefusalError(code, at=at)


def _within(inner: Span, outer: Span) -> bool:
    return (outer.line, outer.column) <= (inner.line, inner.column) and (
        inner.end_line,
        inner.end_column,
    ) <= (outer.end_line, outer.end_column)


def _dotted(node: ast.Attribute) -> str:
    """`alias.attr` for a chain admission has already bounded to depth 1."""
    value = node.value
    if not isinstance(value, ast.Name):  # pragma: no cover - admission refuses deeper chains
        _refuse("expression_not_projected")
    return f"{value.id}.{node.attr}"


def _target(node: ast.Call) -> str | None:
    """`alias.attr` for a call on a bare name, `None` for every other receiver.

    Non-refusing on purpose. An aggregation chain calls its reduction on a SUBSCRIPT, so every
    caller here has to be able to recognize that shape and refuse it with its own stage's code --
    a refusal inside this function would land the wrong one, or land it too early.
    """
    func = node.func
    if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
        return None
    return f"{func.value.id}.{func.attr}"


def _exact(node: ast.expr) -> Fraction:
    """A numeric literal's exact value. Non-finite refuses rather than raising inside `Fraction`.

    Exact type, never `isinstance`: `bool` subclasses `int`, and `figsize=(True, 6)` is not a size.
    """
    if not isinstance(node, ast.Constant):  # pragma: no cover - admission requires the literal
        _refuse("label_not_literal")
    value = node.value
    if type(value) is int:
        return Fraction(value)
    if type(value) is not float or not math.isfinite(value):
        _refuse("label_not_literal")
    return Fraction(value)


def _figsize(node: ast.Call) -> tuple[Fraction, Fraction] | None:
    """`figsize=(w, h)` exactly, or `None` for the bare call that opens a default-sized figure."""
    if not node.keywords:
        return None
    size = node.keywords[0].value
    if (
        not isinstance(size, ast.Tuple) or len(size.elts) != _FIGSIZE_ARITY
    ):  # pragma: no cover - admission requires the 2-tuple
        _refuse("label_not_literal")
    return _exact(size.elts[0]), _exact(size.elts[1])


class _Projector:
    """One projection. Mutable only for the duration of a single `project` call."""

    def __init__(self, limits: PysrcLimits) -> None:
        self._limits = limits
        self._aliases: set[str] = set()
        self._grids: dict[str, Grid] = {}
        self._exprs: dict[str, ast.expr] = {}
        self._depth = 0
        self._used: set[str] = set()
        self._mark: _MarkBuilder | None = None
        self._frames: dict[str, DatasetRef] = {}
        self._cols: dict[str, tuple[str, Column]] = {}
        self._aggs: dict[str, _Aggregate] = {}
        # A chain re-spelled by `.reset_index()`, kept in its OWN table rather than flagged inside
        # `_aggs`: the reset frame's `.index` is a fresh RangeIndex and not the group key, so the
        # two spellings must not cross, and separate tables make that structural instead of a
        # conjunct every later reader has to remember.
        self._resets: dict[str, _Aggregate] = {}
        self._pandas = False
        # Decorations are collected keyed by their source target and assembled into `Labels` once,
        # so every field has exactly one origin and no branch has to guess which field it is.
        self._decorated: set[str] = set()
        self._text: dict[str, str] = {}
        self._flags: dict[str, bool] = {}
        self._series: str | None = None
        self._figsize: tuple[Fraction, Fraction] | None = None
        self._tick_rotation: Fraction | None = None
        self._tight_layout = False
        # Anything already ON the figure -- a mark, a decoration, a layout call. `plt.figure` is
        # the only call that reads it, and it is what makes that call positional rather than free.
        self._drawn = False
        self._grid_in_scope: Grid | None = None
        self._terminal = False

    # --- expressions ---------------------------------------------------------

    def _literal(self, node: ast.Constant) -> Expr:
        value = node.value
        # Exact type, never `isinstance`: `bool` subclasses `int`, and `True` is a flag for
        # `plt.grid`, never a number to plot.
        if type(value) is int:
            return Num(Fraction(value))
        if type(value) is float:
            # The executed program hands numpy the float64, so the projection carries the float64.
            if not math.isfinite(value):
                _refuse("expression_not_projected")
            return Num(Fraction(value))
        _refuse("expression_not_projected")

    def _expr(self, node: ast.expr, grid_name: str | None) -> Expr:
        """Project one admitted expression, substituting bound names away.

        `grid_name` is the only free name the result may carry; `None` means none may. Nesting --
        operators and the alias chains substitution follows -- is bounded at `MAX_EXPR_DEPTH`
        (Q34): an unbounded chain (`a1 = a0`, `a2 = a1`, ...) recursed until Python raised.
        """
        self._depth += 1
        try:
            if self._depth > MAX_EXPR_DEPTH:
                _refuse("expression_not_projected")
            return self._expr_node(node, grid_name)
        except PysrcRefusalError as exc:
            exc.at = exc.at or (node_span(node),)
            raise
        finally:
            self._depth -= 1

    def _expr_node(self, node: ast.expr, grid_name: str | None) -> Expr:
        if isinstance(node, ast.Constant):
            return self._literal(node)
        if isinstance(node, ast.Name):
            return self._name(node.id, grid_name)
        if isinstance(node, ast.Attribute):
            constant = _CONSTANTS.get(_dotted(node))
            if constant is None:  # pragma: no cover - `ADMITTED_CONSTANT_ATTRS` == `_CONSTANTS`
                _refuse("expression_not_projected")
            return Const(constant)
        if isinstance(node, ast.Call):
            return self._call_expr(node, grid_name)
        if isinstance(node, ast.BinOp):
            operator = _BINOPS.get(type(node.op))
            if operator is None:  # pragma: no cover - admission closes the operator set
                _refuse("expression_not_projected")
            left = self._expr(node.left, grid_name)
            return Bin(operator, left, self._expr(node.right, grid_name))
        if isinstance(node, ast.UnaryOp):
            return Neg(self._expr(node.operand, grid_name))
        _refuse("expression_not_projected")  # pragma: no cover - admission closes the tail

    def _call_expr(self, node: ast.Call, grid_name: str | None) -> Expr:
        target = _target(node)
        if target in _GRID_CALLS:
            # The grid call written twice -- once as x, once inside y -- names the same sample
            # points, so it projects to the grid variable exactly when the two grids are equal.
            if self._grid(node) != self._grid_in_scope:
                _refuse("y_not_over_grid")
            return Var()
        if target is None:
            # An aggregation chain in value position. It reduces a column rather than naming a
            # number, and no formula-arm expression can hold one.
            _refuse("expression_not_projected")
        function = _FUNCTIONS.get(target)
        if function is None or len(node.args) != 1 or node.keywords:
            _refuse("expression_not_projected")
        return Fn(function, self._expr(node.args[0], grid_name))

    def _name(self, name: str, grid_name: str | None) -> Expr:
        if name == grid_name:
            return Var()
        bound_grid = self._grids.get(name)
        if bound_grid is not None:
            # A grid reached by a route other than the mark's x argument. Structural equality
            # decides it: the same sample points ARE the grid variable, however the model spelled
            # them, and different points mean y is not a function of THE grid.
            if bound_grid != self._grid_in_scope:
                _refuse("y_not_over_grid")
            self._used.add(name)
            return Var()
        bound = self._exprs.get(name)
        if bound is None:
            # An alias (`np`, `plt`) in value position, or a name admission bound but projection
            # never saw -- neither denotes a number.
            _refuse("expression_not_projected")
        self._used.add(name)
        return self._expr(bound, grid_name)

    def _rational(self, node: ast.expr) -> Fraction:
        """A grid bound that arithmetic must reach: `fold_exact` or `grid_not_representable`."""
        value = fold_exact(self._expr(node, None))
        if value is None:
            _refuse("grid_not_representable")
        return value

    # --- grids ---------------------------------------------------------------

    def _samples(self, count: int) -> int:
        if not (self._limits.min_grid_samples <= count <= self._limits.max_grid_samples):
            _refuse("grid_not_representable")
        return count

    def _linspace(self, node: ast.Call) -> Grid:
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        num_node = keywords.get("num")
        if len(node.args) == _LINSPACE_FULL_ARITY:
            if num_node is not None:
                _refuse("grid_not_representable")
            num_node = node.args[2]
        elif len(node.args) != _LINSPACE_BOUNDS_ARITY:
            _refuse("grid_not_representable")
        if num_node is None:
            count = 50  # numpy's own default; a program omitting `num` still draws 50 points.
        elif isinstance(num_node, ast.Constant) and type(num_node.value) is int:
            count = num_node.value
        else:
            # A bound name resolving to 10 is still not a literal: the count has to be readable
            # from the source, or the grid's size depends on evaluation.
            _refuse("grid_not_representable")
        return Grid(
            start=self._expr(node.args[0], None),
            stop=self._expr(node.args[1], None),
            samples=self._samples(count),
        )

    def _arange(self, node: ast.Call) -> Grid:
        if node.keywords or not 1 <= len(node.args) <= _ARANGE_MAX_ARITY:
            _refuse("grid_not_representable")
        bounds = [self._rational(arg) for arg in node.args]
        start, stop = (Fraction(0), bounds[0]) if len(bounds) == 1 else (bounds[0], bounds[1])
        step = bounds[2] if len(bounds) == _ARANGE_MAX_ARITY else Fraction(1)
        # INTEGERS ONLY, and it is a faithfulness bound rather than a taste. numpy sizes `arange`
        # as ceil((stop - start) / step) in float64 and accumulates its samples in float64, so a
        # non-integer step makes the EXECUTED array disagree with the exact-rational grid by a
        # whole step: measured, `arange(0, 3, 0.3)` draws 10 points ending at 2.6999999999999997
        # where the exact grid says 11 ending at 3, and `arange(1, 2, 0.1)` ends at
        # 1.9000000000000008, not 1.9. numpy's own reference calls non-integer steps inconsistent
        # and points at `linspace`, which is the admitted tool for real-valued sampling and whose
        # residual is a per-sample rounding rather than a different number of samples. Under
        # `_EXACT_INT` every operation above is exact in float64, so the projection stays faithful
        # BY CONSTRUCTION; over it, `ceil` could misround.
        if any(value.denominator != 1 for value in (start, stop, step)) or any(
            abs(value.numerator) > _EXACT_INT for value in (start, stop, step)
        ):
            _refuse("grid_not_representable")
        if step == 0:
            _refuse("grid_not_representable")
        span = (stop - start) / step
        if span <= 0:
            _refuse("grid_not_representable")
        # Half-open: `arange(0, 10)` is 0..9. Normalizing onto an inclusive stop is what makes one
        # `Grid` shape serve both call forms, and it is why this form needs exact arithmetic.
        count = self._samples(math.ceil(span))
        return Grid(start=Num(start), stop=Num(start + (count - 1) * step), samples=count)

    def _grid(self, node: ast.Call) -> Grid:
        return self._linspace(node) if _target(node) == "np.linspace" else self._arange(node)

    # --- dataset arm ---------------------------------------------------------

    def _source(self, node: ast.Call) -> DatasetRef:
        if len(node.args) != 1 or node.keywords:
            _refuse("source_not_literal")
        arg = node.args[0]
        if not isinstance(arg, ast.Constant) or type(arg.value) is not str:
            _refuse("source_not_literal")
        return DatasetRef(path=arg.value)

    def _column_parts(self, node: ast.Subscript) -> tuple[str, Column]:
        """`<frame>["<literal>"]` split into the frame it reads and the column it names."""
        value = node.value
        if not isinstance(value, ast.Name):  # pragma: no cover - admission refuses other bases
            _refuse("column_not_from_source")
        index = node.slice
        if not isinstance(index, ast.Constant) or type(index.value) is not str:
            _refuse("column_not_literal")  # pragma: no cover - admission refuses non-literal keys
        return value.id, Column(name=index.value)

    def _channel(self, node: ast.expr) -> tuple[str, Column]:
        """One mark channel, from the inline subscript or the name a subscript was bound to."""
        if isinstance(node, ast.Subscript):
            frame, column = self._column_parts(node)
        elif isinstance(node, ast.Name) and node.id in self._cols:
            frame, column = self._cols[node.id]
            self._used.add(node.id)
        else:
            _refuse("column_not_from_source")
        if frame not in self._frames:
            _refuse("column_not_from_source")
        self._used.add(frame)
        return frame, column

    # --- statements ----------------------------------------------------------

    def _assign(self, node: ast.Assign) -> None:
        target = node.targets[0]
        if not isinstance(target, ast.Name):  # pragma: no cover - admission refuses other targets
            _refuse("statement_not_projected")
        name = target.id
        if (
            name in self._aliases
            or name in self._grids
            or name in self._exprs
            or name in self._frames
            or name in self._cols
            or name in self._aggs
            or name in self._resets
        ):
            _refuse("name_rebound")
        value = node.value
        if isinstance(value, ast.Call):
            self._assign_call(name, value)
            return
        if isinstance(value, ast.Subscript):
            self._cols[name] = self._column_parts(value)
            return
        # Held unprojected: a bound expression is only meaningful once the grid it reads is known,
        # and that is decided at the mark.
        self._exprs[name] = value

    def _assign_call(self, name: str, node: ast.Call) -> None:
        target = _target(node)
        if target in _GRID_CALLS:
            self._grids[name] = self._grid(node)
            return
        if target == _SOURCE_CALL:
            if self._frames:
                _refuse("multiple_sources")
            self._frames[name] = self._source(node)
            return
        if target is None:
            # `None` is exactly the LINKED aggregation shapes: a reduction called on a subscript,
            # or a trailing call on a reduction. A bare `<frame>.groupby("<key>")` keeps its target
            # and falls through to `_exprs`, where it reduces nothing and is never used.
            inner = _reset_index_inner(node)
            if inner is None:
                self._aggs[name] = self._aggregate(node)
            else:
                # Same reduction, DIFFERENT spelling of its channels: the reset re-publishes the
                # series as a two-column frame, so it binds a reset name rather than an aggregate.
                self._resets[name] = self._aggregate(inner)
            return
        self._exprs[name] = node

    def _aggregate(self, node: ast.Call) -> _Aggregate:
        """Decompose the one chain shape that HAS a projection."""
        chain = aggregation_chain(node)
        if chain is None:
            _refuse("aggregation_not_projected")
        if chain.frame not in self._frames:
            _refuse("column_not_from_source")
        return _Aggregate(
            frame=chain.frame,
            key=Column(name=chain.key),
            column=Column(name=chain.column),
            reduction=_REDUCTIONS[chain.reduction],
        )

    def _label_call(self, target: str, node: ast.Call) -> None:
        if target in self._decorated:
            # The earlier call ran, and its text would vanish from the spec.
            _refuse("statement_not_projected")
        self._decorated.add(target)
        if target in _TEXT_LABELS:
            if len(node.args) != 1 or node.keywords:
                _refuse("label_not_literal")
            text = node.args[0]
            if not isinstance(text, ast.Constant) or type(text.value) is not str:
                _refuse("label_not_literal")
            self._text[target] = text.value
            return
        if node.keywords or len(node.args) > 1:
            _refuse("label_not_literal")
        flag = True
        if node.args:
            arg = node.args[0]
            if not isinstance(arg, ast.Constant) or type(arg.value) is not bool:
                _refuse("label_not_literal")
            flag = arg.value
        self._flags[target] = flag

    def _presentation_call(self, target: str, node: ast.Call) -> None:
        """The three cosmetic calls. Each fills a `Labels` field and none moves a number."""
        if target == _FIGURE:
            # The one cosmetic call bound to a POSITION: a new figure is a new canvas, so whatever
            # was already drawn -- a mark, a title, a layout call -- is not in the artifact this
            # program emits, and the spec would describe a chart the PNG does not contain. A second
            # `plt.figure` orphans the first for the same reason.
            if self._drawn:
                _refuse("figure_orphans_mark")
            self._drawn = True
            self._figsize = _figsize(node)
            return
        if target in self._decorated:
            # The earlier call ran, and its effect would vanish from the spec.
            _refuse("statement_not_projected")
        self._decorated.add(target)
        self._drawn = True
        if target == _TIGHT_LAYOUT:
            # Admission refuses every argument here: a positional (`_NO_POSITIONAL_TARGETS`) and
            # every keyword (an empty allowlist), so the call is bare.
            self._tight_layout = True
            return
        if target == _XTICKS:
            # A bare `plt.xticks()` READS the current ticks and changes nothing, so there is
            # nothing to represent. A positional, which SETS ticks, never gets here: admission
            # refuses it (`_NO_POSITIONAL_TARGETS`).
            if not node.keywords:
                _refuse("statement_not_projected")
            self._tick_rotation = _exact(node.keywords[0].value)
            return
        _refuse("statement_not_projected")  # pragma: no cover - `_PRESENTATION` is closed

    def _labels(self) -> Labels:
        return Labels(
            title=self._text.get("plt.title"),
            xlabel=self._text.get("plt.xlabel"),
            ylabel=self._text.get("plt.ylabel"),
            series=self._series,
            legend=self._flags.get("plt.legend", False),
            grid=self._flags.get("plt.grid", False),
            figsize=self._figsize,
            tick_rotation=self._tick_rotation,
            tight_layout=self._tight_layout,
        )

    def _call_statement(self, node: ast.Call) -> None:
        receiver = accessor_receiver(node)
        if receiver is not None:
            # The accessor enters the SAME seam `plt.bar` enters, count included. A parallel route
            # would leave `multiple_marks` unfired, so an accessor beside a `plt.bar` would publish
            # one of two figures with no refusal -- and the spec cannot say which one the PNG holds.
            build = self._accessor_mark(receiver, node)
            if self._mark is not None:
                _refuse("multiple_marks")
            self._mark = build
            self._drawn = True
            return
        target = _target(node)
        if target is None:
            # An aggregation chain as a bare statement: admitted, computed, and discarded without
            # drawing anything. Representing it is impossible; ignoring it would widen the gap.
            _refuse("statement_not_projected")
        if target == _TERMINAL:
            if node.args or node.keywords:
                _refuse("statement_not_projected")
            self._terminal = True
            return
        if target in _DATASET_MARKS:
            # EVERYTHING local to this statement -- arm, arity, keywords, channels -- decides before
            # the program-wide mark count, because that is what LOCAL before GLOBAL means. Deferring
            # channel resolution to assembly made a first mark naming a bad column refuse on the
            # SECOND mark's existence instead. Only labels wait, since decorations may follow.
            if not self._pandas and target in _WRONG_ARM_MARKS:
                _refuse("mark_not_valid_for_arm")
            build = (
                self._resolve_dataset_mark(target, node)
                if self._pandas
                else self._resolve_mark(_MARKS[target], node)
            )
            if self._mark is not None:
                _refuse("multiple_marks")
            self._mark = build
            self._drawn = True
            return
        if target in _TEXT_LABELS or target in _FLAG_LABELS:
            self._label_call(target, node)
            self._drawn = True
            return
        if target in _PRESENTATION:
            self._presentation_call(target, node)
            return
        # An admitted call with no drawing effect -- `np.sin(x)` as a statement computes and
        # discards. Representing it is impossible; ignoring it would widen the gap.
        _refuse("statement_not_projected")

    def _statement(self, node: ast.stmt) -> None:
        """Project one statement; a refusal points at the innermost expression that raised it,
        plus this statement when that expression was substituted in from an earlier binding."""
        try:
            self._project_statement(node)
        except PysrcRefusalError as exc:
            statement = node_span(node)
            if not exc.at:
                exc.at = (statement,)
            elif not _within(exc.at[0], statement):
                exc.at = (*exc.at, statement)
            raise

    def _project_statement(self, node: ast.stmt) -> None:
        if self._terminal:
            _refuse("statement_after_terminal")
        if isinstance(node, ast.Import):
            for alias in node.names:
                self._aliases.add(alias.asname or alias.name)
            return
        if isinstance(node, ast.Assign):
            self._assign(node)
            return
        if isinstance(node, ast.Expr):
            value = node.value
            if not isinstance(value, ast.Call):  # pragma: no cover - admission refuses non-calls
                _refuse("statement_not_projected")
            self._call_statement(value)
            return
        _refuse("statement_not_projected")  # pragma: no cover - admission closes the tail

    # --- assembly ------------------------------------------------------------

    def _mark_shape(self, node: ast.Call) -> None:
        """Arity plus the keywords -- identical under both arms, so stated once."""
        if len(node.args) != _MARK_ARITY:
            _refuse("mark_arity_not_projected")
        self._style_keywords(node)

    def _style_keywords(self, node: ast.Call) -> None:
        """Every mark keyword routed BY NAME; only `label` names the series.

        Style keywords are validated as text and then discarded: they carry no data, so the figure
        they describe is the same figure. Routing every keyword into the series is what would
        publish `steelblue` as the legend text of a chart whose legend says something else entirely.
        The accessor reaches this WITHOUT an arity check -- it takes no positional argument at all
        -- and its `kind` passes through as the literal it is, having already named the mark.
        """
        for keyword in node.keywords:
            text = keyword.value
            if not isinstance(text, ast.Constant) or type(text.value) is not str:
                # `color=df["city"]` is the colour-by-category channel in disguise: a data effect
                # wearing a cosmetic keyword's name.
                _refuse("label_not_literal")
            if keyword.arg == "label":
                self._series = text.value

    def _aggregate_bound(self, node: ast.expr, attribute: str) -> str | None:
        """The bound name behind `<name>.<attribute>`, when it names a projected aggregate."""
        if not isinstance(node, ast.Attribute) or node.attr != attribute:
            return None
        base = node.value
        if not isinstance(base, ast.Name) or base.id not in self._aggs:
            return None
        return base.id

    def _aggregate_channels(self, node: ast.Call) -> _Aggregate | None:
        """One mark reads ONE reduction: an `.index` x demands the SAME name's values as y.

        Mixing a reduced channel with a raw column, or reading `.values` as x, would draw a figure
        whose two axes come from different tables -- and their lengths would agree often enough for
        it to look right.
        """
        name = self._aggregate_bound(node.args[0], "index")
        if name is None:
            return None
        y = node.args[1]
        if self._aggregate_bound(y, "values") != name and not (
            isinstance(y, ast.Name) and y.id == name
        ):
            _refuse("column_not_from_source")
        self._used.add(name)
        return self._aggs[name]

    def _reset_subscript(self, node: ast.expr) -> tuple[str, Column] | None:
        """`<name>["<column>"]` over a RESET frame, split into that name and the column."""
        if not isinstance(node, ast.Subscript):
            return None
        name, column = self._column_parts(node)
        if name not in self._resets:
            return None
        return name, column

    def _reset_channels(self, node: ast.Call) -> _Aggregate | None:
        """A reset frame's two channels: x is the chain KEY, y is the chain's reduced COLUMN.

        The reset publishes one reduced series as a two-column frame, so the pair of channels is
        FULLY determined: `(<name>["<key>"], <name>["<column>"])` and nothing else. Swapping them
        draws the key as a magnitude, the key on both axes draws a chart of its own labels, and a
        third column names one the reset frame does not carry. One predicate over the whole pair,
        because every way of missing it is the same fault -- a channel the chain did not compute.
        """
        x = self._reset_subscript(node.args[0])
        if x is None:
            return None
        name = x[0]
        aggregate = self._resets[name]
        if (x, self._reset_subscript(node.args[1])) != (
            (name, aggregate.key),
            (name, aggregate.column),
        ):
            _refuse("column_not_from_source")
        self._used.add(name)
        return aggregate

    def _resolve_dataset_mark(self, target: str, node: ast.Call) -> _MarkBuilder:
        # The arm's precondition reads first: with no source bound, no channel can name a column,
        # so `column_not_from_source` would report a symptom where `no_source` names the cause.
        if not self._frames:
            _refuse("no_source")
        self._mark_shape(node)
        mark = _DATASET_MARKS[target]
        aggregate = self._aggregate_channels(node)
        if aggregate is None:
            aggregate = self._reset_channels(node)
        if aggregate is not None:
            return self._aggregate_mark(mark, aggregate)
        x_frame, x = self._channel(node.args[0])
        y_frame, y = self._channel(node.args[1])
        if x_frame != y_frame:  # pragma: no cover - `multiple_sources` keeps `_frames` a singleton
            # Dead while exactly one source binds, and kept anyway: the day a second source is
            # admitted, this is the line that stops the figure being a join no projection states.
            _refuse("column_not_from_source")
        source = self._frames[x_frame]
        return lambda labels: DatasetPlot(mark=mark, source=source, x=x, y=y, labels=labels)

    def _aggregate_mark(self, mark: DatasetMark, aggregate: _Aggregate) -> _MarkBuilder:
        """The ONE builder every aggregate spelling ends at.

        `plt.bar(g.index, g.values)`, the `.reset_index()` re-spelling and the accessor all reach
        it, which is what makes the three project EQUAL rather than merely alike: the spelling is
        decided in the resolution above and appears nowhere on the spec below.
        """
        self._used.add(aggregate.frame)
        grouped = self._frames[aggregate.frame]
        return lambda labels: DatasetPlot(
            mark=mark,
            source=grouped,
            x=aggregate.key,
            y=aggregate.column,
            labels=labels,
            group=aggregate.reduction,
        )

    def _accessor_mark(self, receiver: ast.Name, node: ast.Call) -> _MarkBuilder:
        """`<reduced series>.plot(kind="<mark>")`, resolved at its own statement.

        `kind` named the mark at ADMISSION, against a closed map onto `plt.bar`/`plt.barh`/
        `plt.plot`, so the two lookups below are total rather than defaulted. The receiver carries
        the channels, and only a reduced series states both of them: a frame, a raw column, a reset
        frame and a SELECTED ELEMENT of a reduced series each name a table whose x and y the
        projection would have to guess, so each refuses on the channel it cannot read.
        """
        # The arm's precondition reads first, exactly as `_resolve_dataset_mark` reads it: with no
        # source bound, `column_not_from_source` would report a symptom where `no_source` names
        # the cause. It carries the ARM too, and needs no `_pandas` test of its own: only
        # `pd.read_csv` binds a frame, so the formula arm reaches this with `_frames` empty and an
        # arm check would be a branch no program can take.
        if not self._frames:
            _refuse("no_source")
        self._style_keywords(node)
        # A receiver subscript is admitted as SHAPE and priced HERE: `g["revenue"]` selects one
        # element of the reduced series BY GROUP KEY, never a column, so the executed receiver is a
        # scalar and the spec this would state describes a figure the program never draws. Reading
        # the root alone verifies `g` for a program that plots something else.
        if accessor_is_subscripted(node) or receiver.id not in self._aggs:
            _refuse("column_not_from_source")
        self._used.add(receiver.id)
        # Admission refused every unreadable `kind`, so casting rather than re-testing keeps the
        # branch out of the module: an arm no input can take is one the coverage gate cannot price.
        kind = cast("str", accessor_kind(node))
        mark = _DATASET_MARKS[ADMITTED_ACCESSOR_KINDS[kind]]
        return self._aggregate_mark(mark, self._aggs[receiver.id])

    def _resolve_mark(self, mark: FormulaMark, node: ast.Call) -> _MarkBuilder:
        self._mark_shape(node)
        x_node = node.args[0]
        grid_name: str | None = None
        if isinstance(x_node, ast.Name) and x_node.id in self._grids:
            grid_name = x_node.id
            grid = self._grids[grid_name]
            self._used.add(grid_name)
        elif isinstance(x_node, ast.Call) and _target(x_node) in _GRID_CALLS:
            grid = self._grid(x_node)
        else:
            _refuse("x_not_a_grid")
        self._grid_in_scope = grid
        y = self._expr(node.args[1], grid_name)
        return lambda labels: FormulaPlot(mark=mark, grid=grid, y=y, labels=labels)

    def run(self, tree: ast.Module) -> CorePlotSpec:
        # The arm is settled from the tree BEFORE any statement runs, because a mark statement's own
        # validity depends on it. Both selectors present is a refusal, never a precedence.
        self._pandas = any(
            isinstance(node, ast.Import) and any(alias.name == "pandas" for alias in node.names)
            for node in tree.body
        )
        if self._pandas and _uses_grid(tree):
            _refuse("arm_ambiguous", _arm_selectors(tree))
        for statement in tree.body:
            self._statement(statement)
        if self._mark is None:
            _refuse("no_mark")
        if not self._terminal:
            _refuse("no_terminal")
        # The mark resolved at its own statement; only the decorations, which may follow it, wait.
        plot = self._mark(self._labels())
        unused = (
            self._grids.keys()
            | self._exprs.keys()
            | self._frames.keys()
            | self._cols.keys()
            | self._aggs.keys()
            | self._resets.keys()
        ) - self._used
        if unused:
            # Bound, admitted, executed, and absent from the spec: exactly the gap this module
            # exists to close.
            _refuse("statement_not_projected", _first_binding(tree, unused))
        return plot


def _arm_selectors(tree: ast.Module) -> tuple[Span, ...]:
    """Both arm selectors: every `import pandas`, then every statement holding a grid call."""
    imports = [
        node_span(node)
        for node in tree.body
        if isinstance(node, ast.Import) and any(alias.name == "pandas" for alias in node.names)
    ]
    grids = [node_span(node) for node in tree.body if _uses_grid(ast.Module([node], []))]
    return (*imports, *grids)


def _first_binding(tree: ast.Module, names: set[str]) -> tuple[Span, ...]:
    """The first statement in source order binding one of `names`."""
    for node in tree.body:
        target = node.targets[0] if isinstance(node, ast.Assign) else None
        if isinstance(target, ast.Name) and target.id in names:
            return (node_span(node),)
    return ()  # pragma: no cover - every unused name was bound by an assignment


# Call statement target -> its role in the chart. Closed over what projection lets through.
_CALL_ROLES: dict[str, Role] = {
    "plt.plot": "mark",
    "plt.scatter": "mark",
    "plt.bar": "mark",
    "plt.barh": "mark",
    "plt.title": "title",
    "plt.xlabel": "xlabel",
    "plt.ylabel": "ylabel",
    "plt.legend": "decoration",
    "plt.grid": "decoration",
    "plt.figure": "layout",
    "plt.tight_layout": "layout",
    "plt.xticks": "layout",
    "plt.show": "show",
}


def _role(node: ast.stmt) -> Role:
    if isinstance(node, ast.Import):
        return "import"
    if isinstance(node, ast.Assign):
        value = node.value
        source = isinstance(value, ast.Call) and _target(value) == _SOURCE_CALL
        return "source" if source else "data"
    # Projection lets through imports, assignments and call statements alone.
    call = cast("ast.Call", cast("ast.Expr", node).value)
    if accessor_receiver(call) is not None:
        return "mark"
    return _CALL_ROLES[cast("str", _target(call))]


def statement_trace(tree: ast.Module) -> Trace:
    """Each top-level statement's span and role, in source order. Positions alone: no name, no
    text. Precondition: `project(tree)` returned, so every statement has a role."""
    return tuple(Step(_role(node), node_span(node)) for node in tree.body)


def project(tree: ast.Module, limits: PysrcLimits = DEFAULT_LIMITS) -> CorePlotSpec:
    """Project an ADMITTED tree onto the core plot spec, or raise `PysrcRefusalError`.

    `tree` must be what `parse_admitted` returned: every guarantee here rests on the allowlist
    having run first, and the closed tails below are unreachable only under that precondition.
    """
    validate_limits(limits)
    return _Projector(limits).run(tree)
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
    """The first recorded program line among `slots` (axes calls, then `axis-` axis calls)."""
    calls = dict(axes.calls) | {f"axis-{name}": line for name, line in axis.calls}
    return next((calls[slot] for slot in slots if slot in calls), None)


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
        faces = any(not _clear(face) for face in geometry.colors)
        edges = any(not _clear(edge) for edge in geometry.edges) and any(geometry.linewidths)
        return not any(geometry.sizes) or not (faces or edges)
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

_SOURCES["verifier.pysrc.certificate"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The core certificate: what was verified, in hashes and in plain words.

Stdlib-only, so this is NOT `verifier.vcert` -- that one is msgspec and belongs to the shipped
service. Where reuse conflicts with the paste-in's isolation, isolation wins.

Two disciplines the shape enforces. `checks` is all-pass BY CONSTRUCTION, mirroring v0.3's
`Literal["pass"]`: anything the verifier did not establish goes in `declared_open` and never into
`checks` as a failure. `interpretation` publishes the tier-3 gap in plain words; fidelity to what
the user meant is never claimed.
"""

import hashlib
import json
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal, assert_never, cast

from verifier.pysrc.errors import PysrcCallerError
from verifier.pysrc.numeric import NUMERIC_PROFILE
from verifier.pysrc.project import same_bound
from verifier.pysrc.spec import (
    Bin,
    Const,
    CorePlotSpec,
    DatasetMark,
    DatasetPlot,
    DatasetTarget,
    DeclaredTarget,
    Expr,
    Fn,
    FormulaPlot,
    FormulaTarget,
    Grid,
    Interval,
    Labels,
    Neg,
    Num,
    Reduction,
    Var,
)
from verifier.pysrc.table import PlottedTable

__all__ = ["CERTIFICATE_VERSION", "CertifiedCheck", "CoreCertificate", "certify"]

CERTIFICATE_VERSION = "pysrc-cert-0.1"

type Provenance = Literal["artifact", "internal"]


@dataclass(frozen=True, slots=True)
class CertifiedCheck:
    """One established property. `status` has one admitted value on purpose."""

    id: str
    status: Literal["pass"]


@dataclass(frozen=True, slots=True)
class CoreCertificate:
    """Field set is exact and pinned. A new field is a claim, so it moves the pin deliberately."""

    version: str
    source_sha256: str
    spec_sha256: str
    table_sha256: str
    # G11: one member count per plotted group, aligned with the table's x, and `None` when the plot
    # is not an aggregate. The interpretation sentence carries the two TOTALS a human reads at a
    # glance; the per-group detail lives here, where a machine consumer can check it row by row.
    group_counts: tuple[int, ...] | None
    provenance: Provenance
    artifact_sha256: str | None
    numeric_profile: str
    checks: tuple[CertifiedCheck, ...]
    declared_open: tuple[str, ...]
    interpretation: str
    # The same statement in Japanese, for a reader whose request was Japanese; the caller picks.
    interpretation_ja: str


_CHECKS = tuple(
    CertifiedCheck(check, "pass")
    for check in (
        "prescan",
        "admission",
        "projection",
        "target_binding",
        "recomputation",
        "integrity",
    )
)
_ARTIFACT_GAP = "The emitted image is not compared against this table."
_INTENT_GAP = (
    "The plotted values are the submitted program's own expression, not a target the user stated."
)
_NO_ARTIFACT = (
    "No user artifact was consumed. The plotted values come from the submitted program alone."
)
_SAMPLES_GAP = "The request states no sample count. The submitted program sets it."
_INTERVAL_GAP = (
    "The request states no x interval. "
    "The submitted program sets the interval and the sample count."
)
_SPEC_DOMAIN = b"pysrc-spec-0.1\n"
# Reduction -> the word a person reads. `min`/`max` are abbreviations a reader has to expand;
# `sum` and `mean` are already the English words for what they do.
_REDUCTION_WORDS: dict[Reduction, str] = {
    "sum": "sum",
    "mean": "mean",
    "min": "minimum",
    "max": "maximum",
}

_JA_REDUCTION_WORDS: dict[Reduction, str] = {
    "sum": "合計",
    "mean": "平均",
    "min": "最小値",
    "max": "最大値",
}
_JA_MARK_WORDS: dict[DatasetMark, str] = {
    "bar": "棒グラフ",
    "barh": "横棒グラフ",
    "line": "折れ線グラフ",
    "scatter": "散布図",
}

# (first channel's axis, second channel's axis) as RENDERED, per mark.
_AXIS_LETTERS: dict[DatasetMark, tuple[str, str]] = {
    "line": ("X", "Y"),
    "scatter": ("X", "Y"),
    "bar": ("X", "Y"),
    "barh": ("Y", "X"),
}


def _expr_value(expr: Expr) -> list[object]:
    if isinstance(expr, Num):
        return ["num", expr.value.numerator, expr.value.denominator]
    if isinstance(expr, Var):
        return ["var"]
    if isinstance(expr, Const):
        return ["const", expr.name]
    if isinstance(expr, Neg):
        return ["neg", _expr_value(expr.operand)]
    if isinstance(expr, Fn):
        return ["fn", expr.name, _expr_value(expr.arg)]
    if isinstance(expr, Bin):
        return ["bin", expr.op, _expr_value(expr.left), _expr_value(expr.right)]
    assert_never(expr)  # pragma: no cover - `Expr` is a closed union


def _grid_value(grid: Grid) -> dict[str, object]:
    return {
        "samples": grid.samples,
        "start": _expr_value(grid.start),
        "stop": _expr_value(grid.stop),
    }


def _fraction_value(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def _labels_value(labels: Labels) -> dict[str, object]:
    # The cosmetic fields are hashed like every other one. A figure size changes no plotted number,
    # but a spec digest that ignores a projected field is not a binding on that field, and the one
    # thing this digest exists to say is "the spec you read is the spec that was verified".
    figsize = labels.figsize
    return {
        "figsize": None if figsize is None else [_fraction_value(part) for part in figsize],
        "grid": labels.grid,
        "legend": labels.legend,
        "series": labels.series,
        "tick_rotation": (
            None if labels.tick_rotation is None else _fraction_value(labels.tick_rotation)
        ),
        "tight_layout": labels.tight_layout,
        "title": labels.title,
        "xlabel": labels.xlabel,
        "ylabel": labels.ylabel,
    }


def _spec_value(spec: CorePlotSpec) -> dict[str, object]:
    if isinstance(spec, FormulaPlot):
        return {
            "grid": _grid_value(spec.grid),
            "labels": _labels_value(spec.labels),
            "mark": spec.mark,
            "y": _expr_value(spec.y),
        }
    if isinstance(spec, DatasetPlot):
        return {
            "group": spec.group,
            "labels": _labels_value(spec.labels),
            "mark": spec.mark,
            "path": spec.source.path,
            "x": spec.x.name,
            "y": spec.y.name,
        }
    assert_never(spec)  # pragma: no cover - `CorePlotSpec` is a closed union


def _json_bytes(value: object) -> bytes:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return encoded.encode("utf-8") + b"\n"


def canonical_spec_bytes(spec: CorePlotSpec) -> bytes:
    """One byte encoding per projected spec, domain- and arm-tagged, stdlib-only."""
    if isinstance(spec, FormulaPlot):
        arm = b"formula\n"
    elif isinstance(spec, DatasetPlot):
        arm = b"dataset\n"
    else:
        assert_never(spec)  # pragma: no cover - `CorePlotSpec` is a closed union
    return _SPEC_DOMAIN + arm + _json_bytes(_spec_value(spec))


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _target_consumed(spec: CorePlotSpec, target: DeclaredTarget | None) -> bool:
    if isinstance(spec, DatasetPlot):
        return isinstance(target, DatasetTarget) and target.path == spec.source.path
    if isinstance(spec, FormulaPlot):
        if not isinstance(target, FormulaTarget) or target.y != spec.y:
            return False
        if target.grid is None:
            return True
        if isinstance(target.grid, Grid) and target.grid.samples != spec.grid.samples:
            return False
        return same_bound(spec.grid.start, target.grid.start) and same_bound(
            spec.grid.stop, target.grid.stop
        )
    assert_never(spec)  # pragma: no cover - `CorePlotSpec` is a closed union


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _number_text(number: Num) -> str:
    if number.value.denominator == 1:
        return str(number.value.numerator)
    # Projection creates non-integral fractions only from finite source float64 values.
    return repr(float(number.value))


def _expr_text(expr: Expr) -> str:
    if isinstance(expr, Num):
        return _number_text(expr)
    if isinstance(expr, Var):
        return "x"
    if isinstance(expr, Const):
        return expr.name
    if isinstance(expr, Neg):
        return f"-({_expr_text(expr.operand)})"
    if isinstance(expr, Fn):
        return f"{expr.name}({_expr_text(expr.arg)})"
    if isinstance(expr, Bin):
        operators = {"add": "+", "sub": "-", "mul": "*", "div": "/", "pow": "**"}
        return f"({_expr_text(expr.left)} {operators[expr.op]} {_expr_text(expr.right)})"
    assert_never(expr)  # pragma: no cover - `Expr` is a closed union


def _append_labels(text: str, labels: Labels) -> str:
    sentences: list[str] = []
    if labels.xlabel is not None:
        sentences.append(f"X label: {_quote(labels.xlabel)}.")
    if labels.ylabel is not None:
        sentences.append(f"Y label: {_quote(labels.ylabel)}.")
    if labels.title is not None:
        sentences.append(f"Title: {_quote(labels.title)}.")
    return " ".join((text, *sentences))


def _dataset_text(
    spec: DatasetPlot, table: PlottedTable, group_counts: tuple[int, ...] | None
) -> str:
    # `plt.barh` draws its first positional on the VERTICAL axis and its second on the horizontal
    # one, so the axis letters swap with the mark. The sentence is a tier-3 claim about the figure
    # a person is looking at, and naming the wrong axis misdescribes exactly the mark this width
    # added. Closed on `DatasetMark`, never a default, so a fifth mark fails at the lookup.
    first, second = _AXIS_LETTERS[spec.mark]
    source = f"Chart type: {spec.mark}. The data comes from the file {_quote(spec.source.path)}."
    if spec.group is None:
        return (
            f"{source} {first} shows the column {_quote(spec.x.name)}. "
            f"{second} shows the column {_quote(spec.y.name)}. "
            f"The chart draws {len(table.x)} rows. Numbers follow the profile {NUMERIC_PROFILE}."
        )
    # G11's human half: the group count and the row count behind it, in the sentence a person
    # actually reads. Two numbers that disagree are what tells a reader rows went missing.
    # `certify` has already refused a grouped spec whose counts are absent, so the cast is that
    # guard's postcondition rather than a hope.
    counts = cast("tuple[int, ...]", group_counts)
    return (
        f"{source} {first} shows the groups of the column {_quote(spec.x.name)}. "
        f"{second} shows the {_REDUCTION_WORDS[spec.group]} of the column "
        f"{_quote(spec.y.name)} in each group. "
        f"The chart draws {len(table.x)} groups from {sum(counts)} rows. "
        f"Numbers follow the profile {NUMERIC_PROFILE}."
    )


def _append_labels_ja(text: str, labels: Labels) -> str:
    sentences: list[str] = []
    if labels.xlabel is not None:
        sentences.append(f"X 軸ラベル: {_quote(labels.xlabel)}。")
    if labels.ylabel is not None:
        sentences.append(f"Y 軸ラベル: {_quote(labels.ylabel)}。")
    if labels.title is not None:
        sentences.append(f"タイトル: {_quote(labels.title)}。")
    return "".join((text, *sentences))


def _dataset_text_ja(
    spec: DatasetPlot, table: PlottedTable, group_counts: tuple[int, ...] | None
) -> str:
    first, second = _AXIS_LETTERS[spec.mark]
    source = (
        f"グラフの種類: {_JA_MARK_WORDS[spec.mark]}。"
        f"データはファイル {_quote(spec.source.path)} から読み込みます。"
    )
    if spec.group is None:
        return (
            f"{source}{first} 軸は列 {_quote(spec.x.name)} を表します。"
            f"{second} 軸は列 {_quote(spec.y.name)} を表します。"
            f"描画する行は {len(table.x)} 行です。数値はプロファイル {NUMERIC_PROFILE} に従います。"
        )
    counts = cast("tuple[int, ...]", group_counts)
    return (
        f"{source}{first} 軸は列 {_quote(spec.x.name)} のグループを表します。"
        f"{second} 軸は各グループの列 {_quote(spec.y.name)} の"
        f"{_JA_REDUCTION_WORDS[spec.group]}を表します。"
        f"{sum(counts)} 行から {len(table.x)} 個のグループを描画します。"
        f"数値はプロファイル {NUMERIC_PROFILE} に従います。"
    )


def _interpretation_ja(
    spec: CorePlotSpec,
    table: PlottedTable,
    group_counts: tuple[int, ...] | None,
    target: DeclaredTarget | None,
) -> str:
    if isinstance(spec, FormulaPlot):
        bound = ""
        if isinstance(target, FormulaTarget):
            if isinstance(target.grid, Grid):
                bound = "数式、x の区間、サンプル数は依頼と一致します。"
            elif isinstance(target.grid, Interval):
                bound = "数式と x の区間は依頼と一致します。"
            else:
                bound = "数式は依頼と一致します。"
        text = (
            f"グラフの種類: {_JA_MARK_WORDS[spec.mark]}。"
            f"データは送信されたプログラムから計算します。{bound}"
            f"Y は {_expr_text(spec.y)} を計算します。"
            f"X は {_expr_text(spec.grid.start)} から {_expr_text(spec.grid.stop)} までの "
            f"{spec.grid.samples} 点です。"
            f"数値はプロファイル {NUMERIC_PROFILE} に従います。"
        )
        return _append_labels_ja(text, spec.labels)
    if isinstance(spec, DatasetPlot):
        return _append_labels_ja(_dataset_text_ja(spec, table, group_counts), spec.labels)
    assert_never(spec)  # pragma: no cover - `CorePlotSpec` is a closed union


def _interpretation(
    spec: CorePlotSpec,
    table: PlottedTable,
    group_counts: tuple[int, ...] | None,
    target: DeclaredTarget | None,
) -> str:
    if isinstance(spec, FormulaPlot):
        bound = ""
        if isinstance(target, FormulaTarget):
            if isinstance(target.grid, Grid):
                bound = "The formula, the x interval and the sample count match the request. "
            elif isinstance(target.grid, Interval):
                bound = "The formula and the x interval match the request. "
            else:
                bound = "The formula matches the request. "
        text = (
            f"Chart type: {spec.mark}. The data comes from the submitted program. "
            f"{bound}Y computes {_expr_text(spec.y)}. X runs from {_expr_text(spec.grid.start)} to "
            f"{_expr_text(spec.grid.stop)} in {spec.grid.samples} samples. Numbers follow the "
            f"profile {NUMERIC_PROFILE}."
        )
        return _append_labels(text, spec.labels)
    if isinstance(spec, DatasetPlot):
        return _append_labels(_dataset_text(spec, table, group_counts), spec.labels)
    assert_never(spec)  # pragma: no cover - `CorePlotSpec` is a closed union


def certify(
    spec: CorePlotSpec,
    table: PlottedTable,
    source: bytes,
    target: DeclaredTarget | None,
    group_counts: tuple[int, ...] | None,
) -> CoreCertificate:
    """Bind the submitted bytes, projected spec and recomputed table into one statement.

    `group_counts` is REQUIRED to agree with the spec: G11 publishes per-group counts beside every
    aggregate, and a branch that reads a grouped spec with absent counts as ungrouped would ship a
    G11-less certificate for an aggregate figure instead of failing. That is a caller defect, not
    an input fault, so it raises rather than refusing.
    """
    grouped = isinstance(spec, DatasetPlot) and spec.group is not None
    if grouped is not (group_counts is not None):
        message = (
            f"group counts disagree with the spec: grouped={grouped}, "
            f"counts={'absent' if group_counts is None else 'present'}"
        )
        raise PysrcCallerError(message)
    consumed = _target_consumed(spec, target)
    provenance: Provenance = "artifact" if consumed else "internal"
    declared_open = [_ARTIFACT_GAP]
    if isinstance(spec, FormulaPlot):
        if not isinstance(target, FormulaTarget):
            declared_open.extend((_INTENT_GAP, _NO_ARTIFACT))
        elif isinstance(target.grid, Interval):
            declared_open.append(_SAMPLES_GAP)
        elif target.grid is None:
            declared_open.append(_INTERVAL_GAP)
    return CoreCertificate(
        version=CERTIFICATE_VERSION,
        source_sha256=_digest(source),
        spec_sha256=_digest(canonical_spec_bytes(spec)),
        table_sha256=_digest(table.canonical_bytes()),
        group_counts=group_counts,
        provenance=provenance,
        artifact_sha256=None,
        numeric_profile=NUMERIC_PROFILE,
        checks=_CHECKS,
        declared_open=tuple(declared_open),
        interpretation=_interpretation(spec, table, group_counts, target),
        interpretation_ja=_interpretation_ja(spec, table, group_counts, target),
    )
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
`-0.0`. Both are excluded here so the drawn figure cannot differ from the recomputed table.

Full six-clause profile + its evidence = `.agent/archive/contracts/m13u5.md`.
"""

import csv
import io
import math
import re
from dataclasses import dataclass
from typing import Literal, NoReturn, assert_never

from verifier.pysrc.aggregate import Aggregated, aggregate_series, column_dtype
from verifier.pysrc.budget import WorkBudget, WorkBudgetExceededError
from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.limits import PysrcLimits
from verifier.pysrc.spec import DatasetMark, DatasetPlot
from verifier.pysrc.table import CellValue

__all__ = ["NA_SPELLINGS", "DatasetSeries", "read_columns"]

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
# Float64 heights `plt.bar` draws bit-exactly, measured on both pinned Pyodide builds and the
# installed bundle (Q12: 0/2,364 changed). A float64 CELL never reaches it -- the 15-digit cap keeps
# every cell below 10**15 -- so it binds a float64 REDUCTION alone.
_FLOAT_HEIGHT_MAX = 2**53
# The marks whose magnitude is drawn as a LENGTH, which is the Pyodide integer path C10 bounds.
_INT_HEIGHT_MARKS = frozenset({"bar", "barh"})
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


def header_names(content: bytes, limits: PysrcLimits) -> tuple[str, ...] | None:
    """The first record as column names; None wherever `read_columns` refuses by the header.

    That is every whole-file gate (size, BOM, NUL, record endings, UTF-8) and every header-record
    check (`_check_header`, and its work charge against a fresh meter -- the header is the first
    charge `read_columns` makes). Request anchoring (Q8) reads the header ahead of recomputation,
    so a file it cannot read anchors nothing and recomputation's own refusal still names the fault;
    a malformed LATER row is recomputation's to refuse, after binding.
    """
    try:
        if (
            len(content) > limits.max_csv_bytes
            or content.startswith(_UTF8_BOM)
            or b"\x00" in content
        ):
            return None
        _check_record_endings(content)
        text = content.decode("utf-8")
        header = next(csv.reader(io.StringIO(text, newline=""), strict=True))
        WorkBudget(limits.max_work).charge(_record_work(header))
        _check_header(header, limits)
    except (
        PysrcRefusalError,
        WorkBudgetExceededError,
        UnicodeDecodeError,
        StopIteration,
        csv.Error,
    ):
        return None
    return tuple(header)


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


def _column_indices(header: tuple[str, ...], plot: DatasetPlot) -> tuple[int, int]:
    try:
        return header.index(plot.x.name), header.index(plot.y.name)
    except ValueError as exc:
        _refuse("column_not_present", exc)


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
    try:
        value = float(text)
    except ValueError as exc:
        _refuse("value_not_in_profile", exc)
    return _profile_float(text, value, integer_column=integer_column)


def _numeric_values(texts: tuple[str, ...]) -> tuple[float, ...]:
    """A numeric column's cells; its inferred dtype picks the range clause (user ruling Q12)."""
    integer_column = column_dtype(texts) == "int64"
    return tuple(_numeric_value(text, integer_column) for text in texts)


def _x_values(
    texts: tuple[str, ...], mark: DatasetMark, *, grouped: bool = False
) -> tuple[CellValue, ...]:
    """The x column as cells. `grouped` reads it as a GROUP KEY rather than as an axis.

    That is the whole difference, and it is one clause: a raw x column refuses `mixed` because half
    a numeric axis cannot be drawn, while a key column has no axis until it is reduced and pandas
    groups `['2', 'a', '10', '2']` perfectly well -- measured, as the text keys `['10', '2', 'a']`.
    `scatter` is unmoved either way, since its x IS a coordinate however it was produced.
    """
    column_class = _classify_column(texts)
    match mark:
        case "scatter":
            if column_class == "categorical":
                _refuse("column_not_numeric")
            return _numeric_values(texts)
        case "line" | "bar" | "barh":
            if column_class == "mixed" and not grouped:
                _refuse("column_not_numeric")
            if column_class == "numeric":
                return _numeric_values(texts)
            return texts
        case _ as unreachable:  # pragma: no cover - `DatasetMark` is closed
            assert_never(unreachable)


def _y_values(texts: tuple[str, ...]) -> tuple[float, ...]:
    if _classify_column(texts) == "categorical":
        _refuse("column_not_numeric")
    return _numeric_values(texts)


@dataclass(frozen=True, kw_only=True, slots=True)
class DatasetSeries:
    """The plotted columns, plus the per-group evidence G11 publishes when there is any.

    `group_counts` is `None` for an ungrouped plot and never an empty tuple: "this figure draws no
    groups" and "this figure draws zero groups" are different statements, and the certificate says
    only the first one.
    """

    x: tuple[CellValue, ...]
    y: tuple[float, ...]
    group_counts: tuple[int, ...] | None


def _check_renderer_bound(reduced: Aggregated, mark: DatasetMark) -> None:
    """C10's int32 clause, re-asserted on the REDUCTION rather than on the cells it came from.

    A sum of in-profile cells leaves the range easily. Measured on both target Pyodide builds:
    `bar` and `barh` raise `OverflowError: Python int too large to convert to C long` on the int64
    heights `[4294967294, -4294967296]`, while in-range controls render. Dtype retention is what
    keeps this narrow -- an integer `mean` is float64 and never reaches the renderer's integer
    branch, and `plot`/`scatter` preserve their float64 bits either way. A float64 reduction under
    `bar`/`barh` stays within 2**53, the span measured bit-exact through the float path (Q12):
    float64 cells sum past it, and nothing was measured beyond.
    """
    if mark not in _INT_HEIGHT_MARKS:
        return
    low, high = (
        (_INT32_MIN, _INT32_MAX)
        if reduced.dtype == "int64"
        else (-_FLOAT_HEIGHT_MAX, _FLOAT_HEIGHT_MAX)
    )
    if any(not low <= value <= high for value in reduced.values):
        _refuse("value_not_in_profile")


def read_columns(
    content: bytes,
    plot: DatasetPlot,
    limits: PysrcLimits,
    budget: WorkBudget,
) -> DatasetSeries:
    """The two selected columns of the user's CSV, in file order, or a refusal.

    Takes the whole projected `DatasetPlot` rather than loose names: the column names and the mark
    all come from one projection, and splitting them into separate arguments invites a caller to
    pair a column with the wrong mark.

    Every ceiling is checked BEFORE the work it bounds: a row cap read after materializing the rows
    buys nothing. Each read cell costs `1 + len(cell_text) // 32`; emitted cells stay flat.

    Both selected columns are swept for inadmissible text before classification. stdlib `float`
    success decides numeric, categorical or mixed. The mark decides which class its role admits.

    A projected `group` reduces the pair instead of plotting it: x becomes the sorted group keys
    and y their reduced values. Every cell still passes the profile FIRST, so aggregation reduces
    admitted numbers only.
    """
    header, rows = _read_csv(content, limits, budget)
    x_index, y_index = _column_indices(header, plot)
    selected = tuple((row[x_index], row[y_index]) for row in rows)
    for x_text, y_text in selected:
        _check_selected_text(x_text)
        _check_selected_text(y_text)
    x_texts = tuple(x_text for x_text, _ in selected)
    y_texts = tuple(y_text for _, y_text in selected)
    if plot.group is not None:
        reduced = aggregate_series(
            _x_values(x_texts, plot.mark, grouped=True),
            y_texts,
            _y_values(y_texts),
            plot.group,
            budget=budget,
            max_groups=limits.max_groups,
        )
        _check_renderer_bound(reduced, plot.mark)
        return DatasetSeries(x=reduced.keys, y=reduced.values, group_counts=reduced.counts)
    return DatasetSeries(x=_x_values(x_texts, plot.mark), y=_y_values(y_texts), group_counts=None)
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
    _x_values,
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
        keys = _x_values(texts, "bar", grouped=True)
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

_SOURCES["verifier.pysrc.verify"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The public entry: submitted source in, verdict out.

Seven stages, in order, each refusing before the next runs: prescan -> admit -> project -> bind
target -> recompute -> integrity -> certify. Ordering is a claim, not an implementation detail -- a
later stage that runs after an earlier refusal would be doing work on bytes already rejected, and
a stage's refusal code would stop identifying which check caught what.

A refusal is RETURNED, never raised. A `PysrcCallerError` still propagates: an operator who
configured the verifier wrongly has no verdict about the source, and collapsing the two would let
a misconfiguration read as a refused program.

The entry is PURE. No filesystem, no network, no clock, no RNG, no environment. The user's CSV
arrives as bytes inside `declared_target`, so the core never opens a path -- which is also what
lets M14 inline this package into a sandbox that has neither.
"""

import math
from dataclasses import dataclass, field
from typing import NoReturn, assert_never

from verifier.figure.anchoring import AmbiguousTermError as _AmbiguousTermError
from verifier.figure.anchoring import anchors as _anchors
from verifier.figure.anchoring import nameable as _nameable
from verifier.figure.anchoring import named_columns as _named_columns
from verifier.figure.anchoring import summaries as _summaries
from verifier.pysrc.admit import parse_admitted
from verifier.pysrc.budget import WorkBudget, WorkBudgetExceededError
from verifier.pysrc.certificate import CoreCertificate, certify
from verifier.pysrc.csvread import header_names, read_columns
from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.limits import DEFAULT_LIMITS, PysrcLimits, validate_limits
from verifier.pysrc.numeric import evaluate_expr, materialize_grid
from verifier.pysrc.position import Role, SourceMap, Span, Trace
from verifier.pysrc.prescan import prescan
from verifier.pysrc.project import project, same_bound, statement_trace
from verifier.pysrc.spec import (
    Aliases,
    Bin,
    Const,
    CorePlotSpec,
    DatasetPlot,
    DatasetTarget,
    DeclaredTarget,
    Expr,
    Fn,
    FormulaPlot,
    FormulaTarget,
    Grid,
    Interval,
    Neg,
    Num,
    Var,
)
from verifier.pysrc.table import CellValue, PlottedTable

__all__ = ["Refused", "Verdict", "Verified", "verify_python_source"]


@dataclass(frozen=True, slots=True)
class Verified:
    """Carries the projection, the recomputation and the certificate, plus where each statement
    sits.

    Deliberately holds no raw source text, no AST node and no unprojected identifier: the spec
    carries only what the figure states (its literal labels included) and the certificate the
    source's digest. The one place this project must never let the model write is the operator
    surface, and a verdict is on that surface. `trace` is integers and a closed role per statement
    -- what a reader needs to find the code in the program they already hold -- and is a
    diagnostic outside the verdict's identity.
    """

    spec: CorePlotSpec
    table: PlottedTable
    certificate: CoreCertificate
    trace: Trace = field(default=(), compare=False)


@dataclass(frozen=True, slots=True)
class Refused:
    """The closed code IS the whole verdict. There is no free text and no echoed input.

    `at` = where in the program the refusal points (`()` = no single place: a whole-program fault,
    or one in the file, the data or the request); `trace` = the statement roles once projection
    succeeded. Both are diagnostics outside the verdict's identity.
    """

    code: RefusalCode
    at: tuple[Span, ...] = field(default=(), compare=False)
    trace: Trace = field(default=(), compare=False)


@dataclass(frozen=True, slots=True)
class Recomputation:
    """The plotted table, plus the per-group counts G11 publishes when the plot is an aggregate.

    Kept OUT of `PlottedTable` deliberately: the table is what the figure draws and what every
    comparison surface compares against, while the counts are evidence about how those rows were
    produced. A field on the comparison surface that no comparison reads is how a claim rots.
    """

    table: PlottedTable
    group_counts: tuple[int, ...] | None


type Verdict = Verified | Refused


def _refuse(
    code: RefusalCode,
    cause: BaseException | None = None,
    *,
    at: tuple[Span, ...] = (),
    role: Role | None = None,
) -> NoReturn:
    raise PysrcRefusalError(code, at=at, role=role) from cause


def _check_anchoring(
    spec: DatasetPlot, target: DatasetTarget, request: str, limits: PysrcLimits
) -> None:
    """Q8: refuse a substitution -- the program drops a column the request names AND plots one it
    never names (`revenue by region`, drawn over `month`).

    Either half alone is no substitution: a request naming only the measure (`chart revenue`)
    leaves the x column to the program, and a request naming three columns lets a two-column chart
    pick two of them. Strict anchoring (Q37, production) refuses the second half alone too: once a
    request names or negates a column, it must name every drawn column a request can name.

    Anchoring is a refinement: an unreadable header, a plotted column absent from it (recompute's
    own refusals) or a request naming no column leaves the verdict to the checks that follow.
    """
    header = header_names(target.content, limits)
    plotted = {spec.x.name, spec.y.name}
    if header is None or not plotted <= set(header):
        return
    try:
        named, negated = _anchors(
            request, header, target.aliases, short_names=target.anchoring == "strict"
        )
    except _AmbiguousTermError as exc:
        _refuse("column_not_requested", exc)
    if named - plotted and plotted - named:
        _refuse("column_not_requested")
    match target.anchoring:
        case "strict":
            if (named or negated) and any(_nameable(c, target.aliases) for c in plotted - named):
                _refuse("column_not_named")
        case "substitution":
            pass
        case _ as unreachable:  # pragma: no cover - the anchoring union is closed
            assert_never(unreachable)


def _check_labels(spec: DatasetPlot, header: tuple[str, ...], aliases: Aliases = ()) -> None:
    drawn = {spec.x.name, spec.y.name}
    labels = spec.labels
    # Each label with the statement that wrote it: the series text is the mark's `label=`.
    texts: tuple[tuple[Role, str | None], ...] = (
        ("title", labels.title),
        ("xlabel", labels.xlabel),
        ("ylabel", labels.ylabel),
        ("mark", labels.series),
    )
    for role, text in texts:
        if text is None:
            continue
        if _named_columns(text, header, aliases, ignore_ties=True) - drawn:
            _refuse("label_not_consistent", role=role)
        if spec.group is not None and _summaries(text, header, aliases) - {spec.group}:
            _refuse("label_not_consistent", role=role)


def bind_target(
    spec: CorePlotSpec, target: DeclaredTarget | None, limits: PysrcLimits = DEFAULT_LIMITS
) -> DeclaredTarget | None:
    """Check the submitted program against the artifact the USER supplied.

    One refusal code, `target_mismatch`, covers both arms' artifact comparison: the fault shape is
    "this program is not about your artifact", and which artifact is evident from the program.
    The dataset arm's path comparison is
    byte-for-byte -- no normalization, no `Path` resolution, no case folding -- because normalizing
    would let two different files answer to one name.
    """
    if isinstance(spec, DatasetPlot):
        if not isinstance(target, DatasetTarget):
            _refuse("source_not_supplied", role="source")
        if spec.source.path != target.path:
            _refuse("target_mismatch", role="source")
        if target.request is not None:
            _check_anchoring(spec, target, target.request, limits)
        return target
    if isinstance(spec, FormulaPlot):
        if isinstance(target, FormulaTarget):
            if spec.y != target.y:
                _refuse("target_mismatch")
            grid = target.grid
            if isinstance(grid, Grid) and spec.grid.samples != grid.samples:
                _refuse("target_mismatch")
            if isinstance(grid, Grid | Interval) and not (
                same_bound(spec.grid.start, grid.start) and same_bound(spec.grid.stop, grid.stop)
            ):
                _refuse("target_mismatch")
            return target
        if target is None:
            return None
        if isinstance(target, DatasetTarget):
            _refuse("target_mismatch")
        assert_never(target)  # pragma: no cover - `DeclaredTarget` is closed
    assert_never(spec)  # pragma: no cover - `CorePlotSpec` is closed


def _check_expr_size(expr: Expr, limit: int) -> None:
    pending = [expr]
    count = 0
    while pending:
        node = pending.pop()
        count += 1
        if count > limit:
            _refuse("work_budget_exceeded")
        if isinstance(node, Bin):
            pending.extend((node.right, node.left))
        elif isinstance(node, Neg):
            pending.append(node.operand)
        elif isinstance(node, Fn):
            pending.append(node.arg)
        elif isinstance(node, (Num, Var, Const)):
            continue
        else:  # pragma: no cover - `Expr` is closed
            assert_never(node)


def _finish_table(
    x: tuple[CellValue, ...],
    y: tuple[float, ...],
    budget: WorkBudget,
) -> PlottedTable:
    if any(not math.isfinite(value) for value in x if isinstance(value, float)) or any(
        not math.isfinite(value) for value in y
    ):
        _refuse("value_not_finite")
    budget.charge(len(x) + len(y))
    return PlottedTable(x=x, y=y)


def _formula_table(spec: FormulaPlot, limits: PysrcLimits, budget: WorkBudget) -> PlottedTable:
    if spec.grid.samples > limits.max_table_rows:
        _refuse("work_budget_exceeded")
    for expr in (spec.grid.start, spec.grid.stop, spec.y):
        _check_expr_size(expr, limits.max_expr_nodes)
    x = materialize_grid(spec.grid, budget)
    y = tuple(evaluate_expr(spec.y, sample, budget) for sample in x)
    return _finish_table(x, y, budget)


def _dataset_table(
    spec: DatasetPlot,
    target: DeclaredTarget | None,
    limits: PysrcLimits,
    budget: WorkBudget,
) -> Recomputation:
    if not isinstance(target, DatasetTarget):  # pragma: no cover - binding closes it
        _refuse("source_not_supplied")
    series = read_columns(target.content, spec, limits, budget)
    return Recomputation(
        table=_finish_table(series.x, series.y, budget),
        group_counts=series.group_counts,
    )


def recompute(
    spec: CorePlotSpec,
    target: DeclaredTarget | None,
    limits: PysrcLimits,
) -> Recomputation:
    """Every plotted number, derived from the source rather than read from the program."""
    validate_limits(limits)
    budget = WorkBudget(limits.max_work)
    try:
        if isinstance(spec, FormulaPlot):
            return Recomputation(table=_formula_table(spec, limits, budget), group_counts=None)
        if isinstance(spec, DatasetPlot):
            return _dataset_table(spec, target, limits, budget)
        assert_never(spec)  # pragma: no cover - `CorePlotSpec` is closed
    except WorkBudgetExceededError as exc:
        _refuse("work_budget_exceeded", exc)


def _check_line_order(x: tuple[CellValue, ...]) -> None:
    text = tuple(value for value in x if isinstance(value, str))
    if text:
        if len(text) != len(x):  # pragma: no cover - recomputation emits one cell class
            _refuse("x_not_ordered")
        if len(set(text)) != len(text):
            _refuse("category_not_unique")
        return
    numeric = tuple(value for value in x if isinstance(value, float))
    if len(numeric) != len(x) or any(
        numeric[index] > numeric[index + 1] for index in range(len(numeric) - 1)
    ):
        _refuse("x_not_ordered")


def _formula_integrity(spec: FormulaPlot, table: PlottedTable) -> None:
    match spec.mark:
        case "line":
            _check_line_order(table.x)
        case "scatter":
            return
        case _ as unreachable:  # pragma: no cover - the mark union is closed
            assert_never(unreachable)


def _dataset_integrity(
    spec: DatasetPlot, table: PlottedTable, header: tuple[str, ...], aliases: Aliases = ()
) -> None:
    match spec.mark:
        case "bar" | "barh":
            categories = tuple(value for value in table.x if isinstance(value, str))
            if len(categories) == len(table.x) and len(set(categories)) != len(categories):
                _refuse("category_not_unique")
        case "line":
            _check_line_order(table.x)
        case "scatter":
            pass
        case _ as unreachable:  # pragma: no cover - the mark union is closed
            assert_never(unreachable)
    _check_labels(spec, header, aliases)


def check_integrity(
    spec: CorePlotSpec, table: PlottedTable, header: tuple[str, ...] = (), aliases: Aliases = ()
) -> None:
    """The G-rules that become decidable only once the table exists. Raises, or returns.

    `header` = the dataset's column names, which G10 matches labels against; empty for a formula.
    """
    if isinstance(spec, FormulaPlot):
        _formula_integrity(spec, table)
    elif isinstance(spec, DatasetPlot):
        _dataset_integrity(spec, table, header, aliases)
    else:  # pragma: no cover - `CorePlotSpec` is closed
        assert_never(spec)


def _header(target: DeclaredTarget | None, limits: PysrcLimits) -> tuple[str, ...]:
    # Recomputation already read this header, so `None` (unreadable) cannot reach here; `()`
    # would name nothing.
    if isinstance(target, DatasetTarget):
        return header_names(target.content, limits) or ()
    return ()


def verify_python_source(
    source: str,
    *,
    declared_target: DeclaredTarget | None = None,
    limits: PysrcLimits = DEFAULT_LIMITS,
) -> Verdict:
    """Verify model-authored Python that draws one chart.

    Total over the admitted subset: every admitted program either verifies or refuses with a closed
    code. `source` is `str` because that is what an LLM completion is; it is encoded once here, and
    a lone surrogate -- which no UTF-8 encoder accepts -- refuses like any other non-UTF-8 input
    rather than escaping as a `UnicodeEncodeError`.
    """
    trace: Trace = ()
    try:
        try:
            source_bytes = source.encode("utf-8")
        except UnicodeEncodeError as exc:
            _refuse("source_not_utf8", exc, at=(SourceMap(source).char(exc.start),))
        text = prescan(source_bytes, limits)
        tree = parse_admitted(text)
        spec = project(tree, limits)
        trace = statement_trace(tree)
        bound_target = bind_target(spec, declared_target, limits)
        recomputation = recompute(spec, bound_target, limits)
        table = recomputation.table
        aliases = bound_target.aliases if isinstance(bound_target, DatasetTarget) else ()
        check_integrity(spec, table, _header(bound_target, limits), aliases)
        certificate = certify(spec, table, source_bytes, bound_target, recomputation.group_counts)
        return Verified(spec=spec, table=table, certificate=certificate, trace=trace)
    except PysrcRefusalError as exc:
        # A stage that sees the spec, not the tree, names the ROLE of the statement to point at.
        at = exc.at or tuple(step.span for step in trace if step.role == exc.role)
        return Refused(code=exc.code, at=at, trace=trace)
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

from verifier.figure.anchoring import AmbiguousTermError, anchors
from verifier.figure.keys import Key
from verifier.figure.reasons import FigureReason
from verifier.figure.request import Request
from verifier.figure.series import Point, Series
from verifier.figure.sources import Column, Table, Unreadable
from verifier.pysrc.aggregate import aggregate_series
from verifier.pysrc.budget import WorkBudget, WorkBudgetExceededError
from verifier.pysrc.errors import PysrcRefusalError
from verifier.pysrc.spec import Aliases, Reduction
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


def _duplicate_key(series: Series) -> bool:
    """G8: two points of one keyed series show the same category (they overplot)."""
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
    for series in every:
        if _duplicate_key(series):
            return Unexplained(series, "category_not_unique")
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

_SOURCES["verifier.pysrc"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Portable verification core for `pysrc-0.1` (model-authored Python).

Stdlib-only and importing no `verifier` sibling on purpose: M14 inlines this package into a
single file an admin pastes into an Open WebUI instance that has no outside network access, so a
dependency here becomes a dependency there. Where reuse of the shipped service code conflicts with
that isolation, isolation wins (`.claude/rules/pysrc.md`).

`verify_python_source` is the ONLY entry a consumer calls; everything else exported here is a
value it returns or a policy it accepts. The stage functions stay reachable by module path for
ordering tests, but they are not part of this surface.
"""

from verifier.pysrc.certificate import (
    CertifiedCheck as CertifiedCheck,
)
from verifier.pysrc.certificate import (
    CoreCertificate as CoreCertificate,
)
from verifier.pysrc.errors import (
    PysrcCallerError as PysrcCallerError,
)
from verifier.pysrc.errors import (
    PysrcRefusalError as PysrcRefusalError,
)
from verifier.pysrc.errors import (
    RefusalCode as RefusalCode,
)
from verifier.pysrc.limits import DEFAULT_LIMITS as DEFAULT_LIMITS
from verifier.pysrc.limits import PysrcLimits as PysrcLimits
from verifier.pysrc.spec import DatasetTarget as DatasetTarget
from verifier.pysrc.spec import DeclaredTarget as DeclaredTarget
from verifier.pysrc.spec import FormulaTarget as FormulaTarget
from verifier.pysrc.table import CellValue as CellValue
from verifier.pysrc.table import PlottedTable as PlottedTable
from verifier.pysrc.verify import Refused, Verdict, Verified, verify_python_source

__all__ = ["Refused", "Verdict", "Verified", "verify_python_source"]
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
from verifier.figure.explain import Choice, Context, Unexplained, explain
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
