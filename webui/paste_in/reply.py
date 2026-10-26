# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The reply parts every target shares: the verdicts, the note line, the kana rule, the PNG line.

Data plus pure functions. The Open WebUI outlet (`filter.py`) and the nucllei tool
(`nucllei_skill/tool.py`) both write the fixed verdict of the request's language, the model's note
under it, and publish only the one PNG line the reader writes; the rules here are theirs alike.
"""

import base64
import binascii
import re
import unicodedata
from typing import Final

from verifier.figure.description import MAX_BYTES, TAG
from verifier.figure.inert import prose
from verifier.figure.reader import MAX_PNG_CHARACTERS

# (EN, JA) by the kana rule, like every line of the reply (Q81, user).
PASS_TEXTS: Final = ("Figure verification passed", "図の検証に合格しました。")
FAIL_TEXTS: Final = (
    "Figure verification failed, no image produced",
    "図の検証に合格しませんでした。画像は表示されません。",
)
# Q78 (user): the speaker of the line under the verdict, EN + JA, in bold (Q79); no check reads
# the note. Open WebUI's chat CSS draws `strong` at weight 500, which a Japanese font without a
# medium face (Yu Gothic UI, Meiryo) draws regular, and browsers synthesize bold from 600 alone;
# KaTeX's `\textbf` is 700, at `\footnotesize` = the body size (Q80, measured live).
NOTE_LABELS: Final = ("**Model note:**", "$\\footnotesize\\textbf{モデルの注記:}$")
_PNG_PREFIX = "data:image/png;base64,"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_URI = re.compile(r"data:image/png;base64,[A-Za-z0-9+/]+={0,2}")
_DATA_PREFIX = re.compile(r"(?<!\w)data:")
# The longest stdout the reader writes (`reader.py::run`): the tagged description within the
# decoder's cap, then one PNG line within the reader's, each ending in a line break. Open WebUI
# 0.12.3 takes a 16 MiB browser frame, and 16 MiB of line breaks took 1.5 s to decode (M22.1 F4).
MAX_REPLY: Final = len(TAG) + MAX_BYTES + 1 + MAX_PNG_CHARACTERS + 1
# A kana LETTER alone marks a Japanese request (user ruling): kanji are shared with Chinese, and
# marks such as `・` or `ー` occur beside kanji alone. The letters form one character class, since
# the test runs on the host's event loop over a message of any length, and a name lookup per
# character took 0.17 s per MB (CPython 3.11, M22.1 F1); kana letters lie in these blocks alone.
_KANA_LETTERS = ("HIRAGANA LETTER", "KATAKANA LETTER", "HALFWIDTH KATAKANA LETTER")
_KANA_BLOCKS = ((0x3040, 0x3100), (0x31F0, 0x3200), (0xFF65, 0xFFA0), (0x1AFF0, 0x1B170))
KANA_LETTER: Final = re.compile(
    "["
    + "".join(
        chr(code)
        for start, end in _KANA_BLOCKS
        for code in range(start, end)
        if unicodedata.name(chr(code), "").startswith(_KANA_LETTERS)
    )
    + "]"
)


def is_japanese(text: object) -> bool:
    """Whether a request reads in Japanese: it holds a kana letter. Total: anything but a `str`
    reads as English, since the diagnostic paths that ask must never cost the verdict."""
    return isinstance(text, str) and KANA_LETTER.search(text) is not None


def png_uri(stdout: str) -> str | None:
    """Accept exactly one complete PNG data-URI line, outside the description line, carrying a
    valid base64 PNG signature."""
    lines = [
        line.strip()
        for line in stdout.splitlines()
        if not line.startswith(TAG) and _DATA_PREFIX.search(line)
    ]
    if (
        len(lines) != 1
        or len(lines[0]) > MAX_PNG_CHARACTERS
        or _PNG_URI.fullmatch(lines[0]) is None
    ):
        return None
    try:
        image = base64.b64decode(lines[0][len(_PNG_PREFIX) :], validate=True)
    except (binascii.Error, ValueError):
        return None
    return lines[0] if image.startswith(_PNG_SIGNATURE) else None


def note_line(note: str, *, japanese: bool) -> str:
    """The model's own statement of what the chart rules overrode, after its bold label as escaped
    plain text (Q79: both hosts render the reply as markdown), or nothing for a blank note.

    Display alone: read by no check, and built before the pass is published, so a fault here
    reaches the host's failure path (a pass never shows without the note the model gave).
    """
    shown = note.strip()
    return f"\n\n{NOTE_LABELS[japanese]} {prose(shown)}" if shown else ""
