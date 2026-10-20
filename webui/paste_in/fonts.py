# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The server's Japanese font, cut to the characters one figure can draw (Q44).

A whole font is several MB and rides inside the RPC. The cut keeps printable ASCII and the minus
sign that matplotlib's tick formatters write, so a program that names the font family alone still
draws numbers, plus every character of the program text and of each attached file. A character in
neither (one the program builds with `chr`) is outside the cut: drawn with no other font holding
it, the reader counts its missing glyph (matplotlib's warning, mathtext's log record, or a
`.notdef` glyph path text lays out) and the figure fails, so a miss can only block.

The cut is the standard library's (`sfnt.py`, Q74): Open WebUI 0.12.3's image holds no fontTools, so
every server cuts the same way. A font the cut refuses, or any fault while cutting, sends the whole
font.
"""

import hashlib
from collections.abc import Iterable

from webui.paste_in import sfnt

# U+2212 = the minus sign in matplotlib's tick labels.
_ALWAYS = frozenset(chr(code) for code in range(0x20, 0x7F)) | {"\u2212"}


def characters(program: str, contents: Iterable[bytes]) -> frozenset[str]:
    """Every character the figure can draw without building it: the program's, each file's as
    UTF-8 (undecodable bytes dropped), ASCII and the minus sign."""
    found = set(_ALWAYS)
    found.update(program)
    for content in contents:
        found.update(content.decode("utf-8", "ignore"))
    return frozenset(found)


def cut(font: bytes, keep: frozenset[str]) -> bytes:
    """`font` holding the glyphs of `keep` alone, else the whole `font`."""
    try:
        return sfnt.cut(font, keep)
    except Exception:
        return font


def cut_for(font: bytes, program: str, contents: Iterable[bytes]) -> bytes:
    """`font` cut to what this figure can draw, else the whole `font`: collecting the characters
    is part of the cut, so its faults degrade the same way."""
    try:
        keep = characters(program, contents)
    except Exception:
        return font
    return cut(font, keep)


def path(font: bytes) -> str:
    """Where the sandbox writes `font`: one file per distinct font. Open WebUI keeps one Pyodide
    runtime per tab, and matplotlib keeps each font file it opened, keyed by its path."""
    return f"/tmp/figure-verification-cjk-{hashlib.sha256(font).hexdigest()[:16]}.ttf"  # noqa: S108
