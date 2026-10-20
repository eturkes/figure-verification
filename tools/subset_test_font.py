# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Write the test font: Noto Sans JP cut to the characters the tracked tests and data draw.

The sandbox draws Japanese text with the font the filter finds on the Open WebUI server
(`webui/paste_in/owui_files.py::cjk_font`); the gate host has no Japanese font, so a figure test
with Japanese text needs one. The full Noto Sans JP is 5.7 MB; this subset keeps ASCII, the kana
blocks and every other character in the tracked test inputs. Run with `NotoSansJP-Regular.ttf`
(Noto Sans JP 2.004, OFL; Google Fonts) after test text gains a character (a test then reports
`glyph_missing`):

    uv run --locked python tools/subset_test_font.py <path to NotoSansJP-Regular.ttf>

`--cff` writes the CFF test font instead (Q74): Noto Sans CJK JP (face 0 of
`NotoSansCJK-Regular.ttc`, OFL, Adobe) cut to `CFF_TEXT` with its subroutines + hints kept, so the
stdlib cut's CID-keyed path (global + local subroutines, hint masks, several Font DICTs) has a
real witness in the gate:

    uv run --locked python tools/subset_test_font.py --cff <path to NotoSansCJK-Regular.ttc>

Deterministic: the same font, fontTools release and tracked text write the same bytes.
"""

import subprocess
import sys
from pathlib import Path

from fontTools import subset  # type: ignore[import-untyped]
from fontTools.ttLib import TTFont  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests" / "fonts" / "NotoSansJP-subset.ttf"
CFF_OUTPUT = ROOT / "tests" / "fonts" / "NotoSansCJKjp-subset.otf"
# Latin, kana + kanji glyphs sit in different Font DICTs of Noto Sans CJK JP.
CFF_TEXT = (
    "".join(map(chr, range(0x20, 0x7F)))
    + "\u2212あいうえおかがきぎくぐアイウエオカガキギ、。「」\uff08\uff09\uff05\uff1a"
    + "患者数診療科ごとの平均待ち時間分週年月日売上地域内外小児整形"
)
_SCANNED = ("data", "tests", "webui/banner.json")
_KANA = (*range(0x3000, 0x3100), *range(0xFF00, 0xFFF0))  # CJK punctuation, kana, full width


def _characters() -> set[int]:
    listed = subprocess.run(  # noqa: S603 - fixed argv
        ["git", "ls-files", "-z", *_SCANNED],  # noqa: S607 - git from PATH
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    # U+2212 = the minus matplotlib's tick formatters write; the filter's cut keeps it (Q44).
    found = set(range(0x20, 0x7F)) | set(_KANA) | {0x2212}
    for name in filter(None, listed):
        if name.endswith(b".ttf"):
            continue
        try:
            text = (ROOT / name.decode()).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        found |= {ord(character) for character in text if ord(character) > 0x7F}  # noqa: PLR2004
    return found


def main(argv: list[str]) -> int:
    cff = argv[:1] == ["--cff"]
    if len(argv) != 1 + cff:
        sys.stderr.write(
            "usage: subset_test_font.py <NotoSansJP-Regular.ttf>\n"
            "       subset_test_font.py --cff <NotoSansCJK-Regular.ttc>\n"
        )
        return 2
    options = subset.Options()
    options.recalc_timestamp = False
    options.name_IDs = ["*"]
    options.name_legacy = True
    options.notdef_outline = True
    font = TTFont(argv[-1], fontNumber=0, recalcTimestamp=False)
    subsetter = subset.Subsetter(options)
    if cff:
        subsetter.populate(text=CFF_TEXT)
    else:
        subsetter.populate(unicodes=sorted(_characters()))
    subsetter.subset(font)
    output = CFF_OUTPUT if cff else OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    font.save(output)
    sys.stdout.write(f"wrote {output.relative_to(ROOT)} ({output.stat().st_size} bytes)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
