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

_SOURCES["webui.paste_in.verdicts"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The one string the tool returns to the model.

The tool decides nothing: the outlet filter runs the recorded program in the user's browser and
judges the finished figure, so no verdict exists when the tool returns. The string is MODEL-facing;
the strings a USER reads are the filter's (`Intent`), and no surface may depend on the model
narrating a verdict (`.claude/rules/owui.md`).
"""

from typing import Final

CHART_SENT: Final = "The chart program was sent. The reply shows the chart if it passes the checks."
'''

_SOURCES["webui.paste_in.aliases"] = r'''
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

_SOURCES["webui.paste_in.tool"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The one model-visible operation: a program in, a fixed string out.

Transport, never authority. The method records the model's exact program bytes, the chat's
attachment ids (the outlet re-resolves each against the requesting user), the request text and the
admin's aliases in backend request state, and returns one fixed string. It runs nothing and decides
nothing: the outlet filter runs the recorded program in the user's browser and judges the finished
figure, and only that outlet may publish (tool-call-only PASS transport).

`Tools` is Open WebUI's fixed entry name; it instantiates the class once and exposes every public
method to the model (`utils/plugin.py`, `utils/tools.py`), so a helper here must stay private or it
becomes a second operation. The reserved `__…__` parameters are injected by Open WebUI and are
absent from the model-facing schema: pydantic's `create_model` drops a leading-underscore field
name, and `get_tools()` strips the same names again before the spec reaches the model.

`Valves` = the admin's settings (Q43: column aliases). Open WebUI builds it on every save
(`Valves(**form)`, a failed validation refuses the save) and on every load, and sets it on the
instance only when the instance already holds `valves`; the model never supplies it. The tool
records the parsed aliases in its receipt, so the outlet's verdict reads the same aliases.
`pydantic` is part of the Open WebUI image, as `open_webui` is.
"""

from pydantic import BaseModel, Field, field_validator

from webui.paste_in.aliases import parse_aliases
from webui.paste_in.owui_files import attachment_ids
from webui.paste_in.receipt import Receipt, write_receipt
from webui.paste_in.verdicts import CHART_SENT


def _request_text(metadata: dict[str, object] | None) -> str | None:
    user_message = (metadata or {}).get("user_message")
    if not isinstance(user_message, dict):
        return None
    content = user_message.get("content")
    return content if isinstance(content, str) else None


class Tools:
    """The pasted tool. One public method, so the model sees one operation."""

    class Valves(BaseModel):
        """The admin's settings for this tool."""

        column_aliases: str = Field(
            default="",
            description=(
                "Other names for CSV columns, one line per column: column = alias, alias."
                " A request or chart label that writes an alias names its column."
            ),
        )

        @field_validator("column_aliases")
        @classmethod
        def check_column_aliases(cls, value: str) -> str:
            """Refuse the save of text that `parse_aliases` cannot read."""
            parse_aliases(value)
            return value

    def __init__(self) -> None:
        self.valves = self.Valves()

    async def draw_figure(
        self,
        program: str,
        __metadata__: dict[str, object] | None = None,
        __request__: object | None = None,
    ) -> str:
        """Draw one chart with matplotlib from a complete Python program.

        Plot only values from the attached CSV file or numbers written in the request, as they
        are or as one total, mean, minimum, maximum or row count per group. Keep the chart honest:
        bars and filled areas start at zero, axes stay linear and not inverted, every value stays
        inside the axis limits, each panel has one set of axes, a legend names every series when
        there are two or more, and varying marker sizes or colors have a size legend or a color
        bar. The reply shows the chart only when it follows these rules.

        :param program: The complete Python program that draws the chart.
        """
        if __request__ is not None:
            write_receipt(
                __request__,
                Receipt(
                    program,
                    tuple(attachment_ids(__metadata__)),
                    _request_text(__metadata__),
                    parse_aliases(self.valves.column_aliases),
                ),
            )
        return CHART_SENT
'''

_SOURCES["webui.paste_in.demo_tool"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The demo's tool: the production tool, generated into the demo's own pair (Q37).

The tool decides nothing, so the demo and production tools are the same code; the demo's filter
carries the demo's anchoring rule and inlet templates.
"""

from webui.paste_in.tool import Tools as ProductionTools


class Tools(ProductionTools):
    """The demo's pasted tool; `draw_figure` is inherited unchanged."""
'''

_ROOT = "webui.paste_in.demo_tool"


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


Tools = _load().Tools
