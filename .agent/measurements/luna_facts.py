# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Figure facts of one chart program, read with plain matplotlib, NOT the verifier's reader.

    python -I luna_facts.py <program.py>     (cwd = a dir holding the program's CSV files)

The independent half of luna_classify.py: whether a misleading run's figure carries the distortion
it asked for is decided from these facts, so a verifier defect cannot hide its own miss. Prints one
JSON line: per axes its position, limits, scales, inversion, labels, bars, scatters, wedges, lines.
"""

import argparse
import json
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PathCollection, PolyCollection
from matplotlib.container import BarContainer
from matplotlib.patches import Wedge


def _no_show(*_args: object, **_kwargs: object) -> None:
    """The program's `show` draws nothing here: the facts read the open figures."""


plt.show = _no_show
parser = argparse.ArgumentParser(
    description="Print the figure facts of one chart program, read with plain matplotlib."
)
parser.add_argument("program", type=Path, help="the chart program file")
source = parser.parse_args().program.read_text(encoding="utf-8")
error = None
try:
    # Running the recorded program IS the measurement (a non-adversarial program, ruling 7).
    code = compile(source.replace("/mnt/uploads/", ""), "program", "exec")
    exec(code, {"__name__": "__main__"})  # noqa: S102
except BaseException as exc:
    error = f"{type(exc).__name__}: {exc}"[:300]


def axes_facts(ax):
    bars = []
    for container in ax.containers:
        if isinstance(container, BarContainer):
            vertical = getattr(container, "orientation", "vertical") == "vertical"
            for patch in container.patches:
                x, y, w, h = patch.get_x(), patch.get_y(), patch.get_width(), patch.get_height()
                base, top = (y, y + h) if vertical else (x, x + w)
                start, end = (x, x + w) if vertical else (y, y + h)
                bars.append(
                    {
                        "vertical": vertical,
                        "base": float(base),
                        "top": float(top),
                        "start": float(start),
                        "end": float(end),
                    }
                )
    scatters = [
        {"sizes": [float(s) for s in c.get_sizes()], "n": len(c.get_offsets())}
        for c in ax.collections
        if isinstance(c, PathCollection)
    ]
    areas = [
        [float(v) for v in c.get_paths()[0].vertices[:, 1]] if c.get_paths() else []
        for c in ax.collections
        if isinstance(c, PolyCollection)
    ]
    wedges = [
        float((p.theta2 - p.theta1) % 360 or 360.0) for p in ax.patches if isinstance(p, Wedge)
    ]
    lines = [
        {
            "label": str(line.get_label()),
            "n": len(line.get_xdata()),
            "y": [str(v) for v in line.get_ydata()],
        }
        for line in ax.get_lines()
    ]
    return {
        "position": [round(v, 4) for v in ax.get_position().bounds],
        "xlim": [float(v) for v in ax.get_xlim()],
        "ylim": [float(v) for v in ax.get_ylim()],
        "xscale": ax.get_xscale(),
        "yscale": ax.get_yscale(),
        "x_inverted": bool(ax.xaxis_inverted()),
        "y_inverted": bool(ax.yaxis_inverted()),
        "xlabel": ax.get_xlabel(),
        "ylabel": ax.get_ylabel(),
        "title": ax.get_title(),
        "legend": ax.get_legend() is not None,
        "xticklabels": [t.get_text() for t in ax.get_xticklabels()],
        "yticklabels": [t.get_text() for t in ax.get_yticklabels()],
        "texts": [t.get_text() for t in ax.texts],
        "bars": bars,
        "scatters": scatters,
        "areas": areas,
        "wedges": wedges,
        "lines": lines,
    }


figures = [plt.figure(n) for n in plt.get_fignums()]
for figure in figures:
    figure.canvas.draw()  # tick label texts exist only after a draw
print(
    json.dumps(
        {
            "error": error,
            "figures": [
                {"axes": [axes_facts(ax) for ax in fig.axes], "legends": len(fig.legends)}
                for fig in figures
            ],
        }
    )
)
