# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Export the banner's simple program, three plotting programs and the Japanese legs (M17.1, Q44).

The Japanese legs carry the installed Open WebUI's own font, read from the path given as argv[1],
cut as the filter cuts it: `fonts.cut` runs in that install's interpreter, so its fontTools does.
"""

import json
import subprocess
import sys
from pathlib import Path

from webui.banner import load
from webui.paste_in.fonts import characters
from webui.paste_in.sandbox import wrapper_code

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
font_path = Path(sys.argv[1]).resolve()
font = font_path.read_bytes()
clinic = (root / "data/clinic_ja.csv").read_bytes()
# <venv>/lib/python3.11/site-packages/open_webui/static/fonts/<font>
owui_python = font_path.parents[6] / "bin" / "python"
_CUT = (
    "import json, sys\n"
    "import fontTools\n"
    "from webui.paste_in.fonts import cut\n"
    "job = json.load(sys.stdin)\n"
    "font = open(job['font'], 'rb').read()\n"
    "cuts = [cut(font, frozenset(keep)).hex() for keep in job['keeps']]\n"
    "print(json.dumps({'fonttools': fontTools.version, 'cuts': cuts}))\n"
)
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
keeps = {name: sorted(characters(source, [clinic])) for name, source in legs.items()}
done = json.loads(
    subprocess.run(  # noqa: S603 - fixed argv: the install's own interpreter
        [
            str(owui_python),
            "-I",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); " + _CUT,
            str(root),
        ],
        input=json.dumps({"font": str(font_path), "keeps": list(keeps.values())}),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
)
cuts = dict(zip(keeps, (bytes.fromhex(cut) for cut in done["cuts"]), strict=True))
print(
    json.dumps(
        {
            "dataset": (root / "data/sales.csv").read_bytes().hex(),
            "clinic": clinic.hex(),
            "fonttools": done["fonttools"],
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
