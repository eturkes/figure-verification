# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Export the banner's simple program, three plotting programs + the Japanese legs (M17.1, Q44, U2,
Q74).

The Japanese legs carry the font the filter reads on this host (`owui_files.find_cjk_font`;
`FV_CJK_FONT` stands in for the admin's Valve path; a collection draws face 0). The cut legs cut it
with the filter's own stdlib cut (`fonts.cut`, Q74) while every fontTools import is blocked, as on
Open WebUI 0.12.3's image; `ja-whole` sends it whole, the path a refused cut takes. `identity`
compares, in the bundle's own FreeType, every character the `ja-font` cut keeps with the whole font.
"""

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

# Open WebUI 0.12.3's image holds no fontTools: blocked, so the cut measured is the shipped one.
sys.modules["fontTools"] = None  # type: ignore[assignment]

from webui.banner import load  # noqa: E402
from webui.paste_in.fonts import characters, cut  # noqa: E402
from webui.paste_in.owui_files import find_cjk_font  # noqa: E402
from webui.paste_in.sandbox import wrapper_code  # noqa: E402

argparse.ArgumentParser(
    description="Print the F7 wrapper programs and the Japanese font legs as JSON."
).parse_args()
root = Path(__file__).resolve().parents[2]
program = next(arm.program for arm in load().arms if arm.id == "simple")

programs = {
    "banner-simple": program,
    "line": (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        "df = pd.read_csv('/mnt/uploads/sales.csv')\n"
        "plt.plot(df['orders'], df['revenue'])\n"
        "plt.show()\n"
    ),
    "scatter": (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        "df = pd.read_csv('/mnt/uploads/sales.csv')\n"
        "plt.scatter(df['orders'], df['revenue'])\n"
        "plt.show()\n"
    ),
    "no-show": (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        "df = pd.read_csv('/mnt/uploads/sales.csv')\n"
        "plt.plot(df['orders'], df['revenue'])\n"
    ),
}
# A verified bar over Japanese categories with a Japanese title + y label: ticks AND labels.
japanese = (
    "import pandas as pd\n"
    "import matplotlib.pyplot as plt\n"
    "df = pd.read_csv('/mnt/uploads/clinic_ja.csv')\n"
    "totals = df.groupby('診療科')['患者数'].sum()\n"
    "totals.plot(kind='bar')\n"
    "plt.title('診療科ごとの患者数')\n"
    "plt.ylabel('患者数')\n"
    "plt.show()\n"
)
mathtext = japanese.replace("plt.title('診療科ごとの患者数')", "plt.title('$年$')")
# Q44 F3: `週` (U+9031) is in neither the program text nor the CSV, so the cut lacks it.
miss = japanese.replace("plt.ylabel('患者数')", "plt.ylabel(chr(0x9031))")
# Q44 F4: a second reply in the same runtime whose cut holds glyphs the first lacks (別 分).
second = (
    "import pandas as pd\n"
    "import matplotlib.pyplot as plt\n"
    "df = pd.read_csv('/mnt/uploads/clinic_ja.csv')\n"
    "waits = df.groupby('診療科')['平均待ち時間'].mean()\n"
    "waits.plot(kind='bar')\n"
    "plt.title('診療科別の平均待ち時間 (分)')\n"
    "plt.show()\n"
)
font = find_cjk_font(os.environ.get("FV_CJK_FONT", ""))
if font is None:
    sys.exit("f7_export: no Japanese font on this host; set FV_CJK_FONT to a font file")
clinic = (root / "data/clinic_ja.csv").read_bytes()
marker = japanese.replace("plt.show()", "plt.plot([0, 1], [100, 200], marker='$週$')\nplt.show()")
# Closing review G1: a TextPath marker lays its glyphs out without a warning; the reader counts each
# `.notdef` it lays out.
textpath = japanese.replace(
    "plt.show()",
    "from matplotlib.textpath import TextPath\n"
    "plt.plot([0, 1], [100, 200], marker=TextPath((0, 0), chr(0x9031)))\nplt.show()",
)
legs = {
    "ja-textpath": textpath,
    "ja-font": japanese,
    "ja-mathtext": mathtext,
    "ja-miss": miss,
    "ja-second": second,
    "ja-marker": marker,
}
started = time.perf_counter()
cuts = {"ja-font": cut(font, characters(japanese, [clinic]))}
cut_ms = round(1000 * (time.perf_counter() - started))
cuts |= {name: cut(font, characters(source, [clinic])) for name, source in legs.items()}
if any(len(piece) >= len(font) for piece in cuts.values()):
    sys.exit("f7_export: the cut refused this font; set FV_CJK_FONT to another Japanese font")
# Q74: the bundle's FreeType draws each kept character of the cut as it draws the whole font --
# unhinted, natively hinted at two sizes; autohinted outlines follow the glyph repertoire (Q44).
identity = f"""
import base64, json
import matplotlib.ft2font as ft
whole, part = "/tmp/fv-identity-whole", "/tmp/fv-identity-part"
for path, data in ((whole, {base64.b64encode(font).decode()!r}),
                   (part, {base64.b64encode(cuts["ja-font"]).decode()!r})):
    with open(path, "wb") as handle:
        handle.write(base64.b64decode(data))
def drawn(path, code, flags, size, factor):
    face = ft.FT2Font(path, hinting_factor=factor)
    face.set_size(size, 72)
    glyph = face.load_char(code, flags=flags)
    vertices, kinds = face.get_path()
    return glyph.horiAdvance, glyph.linearHoriAdvance, vertices.tobytes(), kinds.tobytes()
codes = [code for code in {sorted(map(ord, characters(japanese, [clinic])))!r}
         if ft.FT2Font(whole).get_char_index(code)]
modes = {{
    "unhinted": (ft.LoadFlags.NO_HINTING, 12, 8),
    "native-12": (ft.LoadFlags.DEFAULT, 12, 1),
    "native-100": (ft.LoadFlags.DEFAULT, 100, 1),
    "autohint": (ft.LoadFlags.FORCE_AUTOHINT, 12, 8),
}}
differ = {{name: sum(drawn(whole, c, *mode) != drawn(part, c, *mode) for c in codes)
          for name, mode in modes.items()}}
print(json.dumps({{"freetype": ft.__freetype_version__, "kept": len(codes), "differ": differ}}))
"""
print(
    json.dumps(
        {
            "dataset": (root / "data/sales.csv").read_bytes().hex(),
            "clinic": clinic.hex(),
            "cut": {"ms": cut_ms, "font_bytes": len(font), "cut_bytes": len(cuts["ja-font"])},
            "identity": identity,
            "wrappers": {name: wrapper_code(source) for name, source in programs.items()},
            # Each runs in its own fresh runtime: a font or a warning cache must not leak across.
            "japanese": {
                "ja-font": wrapper_code(japanese, cuts["ja-font"]),
                "ja-whole": wrapper_code(japanese, font),
                "ja-no-font": wrapper_code(japanese),
                "ja-mathtext": wrapper_code(mathtext, cuts["ja-mathtext"]),
                "ja-miss": wrapper_code(miss, cuts["ja-miss"]),
                "ja-textpath": wrapper_code(textpath, cuts["ja-textpath"]),
            },
            # Each sequence shares one fresh runtime, as Open WebUI's one worker per tab does.
            "sequences": {
                # Q44 review: a text marker's mathtext miss counts on every reply, not the first.
                "ja-marker-repeat": [wrapper_code(marker, cuts["ja-marker"])] * 2,
                "ja-second": [
                    wrapper_code(japanese, cuts["ja-font"]),
                    wrapper_code(second, cuts["ja-second"]),
                ],
            },
        }
    )
)
