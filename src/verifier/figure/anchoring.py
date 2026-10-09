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
type Reduction = Literal["sum", "mean", "min", "max"]

__all__ = [
    "SUMMARY_WORDS",
    "AmbiguousTermError",
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
