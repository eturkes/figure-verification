# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Open WebUI's Japanese font, cut to the characters one figure can draw (Q44).

The whole font is 5.7 MB and rides inside the RPC. The cut keeps printable ASCII and the minus sign
that matplotlib's tick formatters write, so a program that names the font family alone still draws
numbers, plus every character of the program text and of each attached file. A character in
neither (one the program builds with `chr`) is outside the cut: drawn with no other font holding
it, the reader counts its missing glyph (matplotlib's warning, mathtext's log record, or a
`.notdef` glyph path text lays out) and the figure fails, so a miss can only block.

fontTools ships in the Open WebUI image (`fpdf2`). Its import is function-local: without it, or on
any fault while cutting, the whole font goes, as before.
"""

import hashlib
import io
from collections.abc import Iterable

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
        from fontTools import subset  # type: ignore[import-untyped]  # noqa: PLC0415
        from fontTools.ttLib import TTFont  # type: ignore[import-untyped]  # noqa: PLC0415

        options = subset.Options()
        # matplotlib applies no OpenType layout, so its tables would only add bytes.
        options.layout_features = []
        options.recalc_timestamp = False
        loaded = TTFont(io.BytesIO(font), recalcTimestamp=False)
        subsetter = subset.Subsetter(options)
        subsetter.populate(unicodes=sorted(map(ord, keep)))
        subsetter.subset(loaded)
        out = io.BytesIO()
        loaded.save(out)
        return out.getvalue()
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
