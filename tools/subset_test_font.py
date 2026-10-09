# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Write the test font: Noto Sans JP cut to the characters the tracked tests and data draw.

The sandbox draws Japanese text with Open WebUI's bundled `NotoSansJP-Regular.ttf`; the gate host
has no Japanese font, so a figure test with Japanese text needs one. The full font is 5.7 MB; this
subset keeps ASCII, the kana blocks and every other character in the tracked test inputs.
Run with Open WebUI's font after test text gains a character (a test then reports
`glyph_missing`):

    uv run --locked python tools/subset_test_font.py <path to NotoSansJP-Regular.ttf>

Deterministic: the same font and the same tracked text write the same bytes.
"""

import subprocess
import sys
from pathlib import Path

from fontTools import subset  # type: ignore[import-untyped]
from fontTools.ttLib import TTFont  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tests" / "fonts" / "NotoSansJP-subset.ttf"
_SCANNED = ("data", "tests", "webui/banner.json")
_KANA = (*range(0x3000, 0x3100), *range(0xFF00, 0xFFF0))  # CJK punctuation, kana, full width


def _characters() -> set[int]:
    listed = subprocess.run(  # noqa: S603 - fixed argv
        ["git", "ls-files", "-z", *_SCANNED],  # noqa: S607 - git from PATH
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    found = set(range(0x20, 0x7F)) | set(_KANA)
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
    if len(argv) != 1:
        sys.stderr.write("usage: subset_test_font.py <NotoSansJP-Regular.ttf>\n")
        return 2
    options = subset.Options()
    options.recalc_timestamp = False
    options.name_IDs = ["*"]
    options.name_legacy = True
    options.notdef_outline = True
    font = TTFont(argv[0], recalcTimestamp=False)
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=sorted(_characters()))
    subsetter.subset(font)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    font.save(OUTPUT)
    sys.stdout.write(f"wrote {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size} bytes)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
