# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Export the committed sentinel and three plotting programs through the shipped wrapper."""

import json
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
print(
    json.dumps(
        {
            "dataset": (root / "data/sales.csv").read_bytes().hex(),
            "wrappers": {name: wrapper_code(source) for name, source in programs.items()},
        }
    )
)
