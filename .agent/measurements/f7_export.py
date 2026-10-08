# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Export the committed sentinel, three plotting programs and the Japanese legs (M17.1).

The Japanese legs carry the installed Open WebUI's own font, read from the path given as argv[1].
"""

import json
import sys
from pathlib import Path

from capture.harness import defence
from webui.paste_in.filter import wrapper_code

root = Path(__file__).resolve().parents[2]
records = root / "corpus/python/captures/m10-design/records.ndjson"
sentinel = next(
    json.loads(line)["content"]
    for line in records.read_text().splitlines()
    if json.loads(line)["prompt_id"] == "sentinel-simple"
)
fenced, program = defence(sentinel)
if not fenced or not program:
    msg = "sentinel-simple capture has no Python program"
    raise ValueError(msg)

programs = {
    "sentinel-simple": program,
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
font = Path(sys.argv[1]).read_bytes()
print(
    json.dumps(
        {
            "dataset": (root / "data/sales.csv").read_bytes().hex(),
            "clinic": (root / "data/clinic_ja.csv").read_bytes().hex(),
            "wrappers": {name: wrapper_code(source) for name, source in programs.items()},
            # Each runs in its own fresh runtime: a font or a warning cache must not leak across.
            "japanese": {
                "ja-font": wrapper_code(japanese, font),
                "ja-no-font": wrapper_code(japanese),
                "ja-mathtext": wrapper_code(mathtext, font),
            },
        }
    )
)
