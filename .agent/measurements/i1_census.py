# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""I1: matplotlib artist census over the M19 chart scope, keyed (class, origin, transform).

Run on the host (`uv run --locked python .agent/measurements/i1_census.py`) and inside the
installed Open WebUI Pyodide bundle (`node i1_pyodide.mjs owui i1-0283.json`); the I1 projection
compares the two. Origin = qualname of the OUTERMOST frame in the matplotlib Axes modules between
the artist's constructor and the program (`.claude/rules/figure.md`).
"""

import json
import sys
from pathlib import Path

PROGRAM = "<program>"
AXES_MODULES = ("matplotlib.axes._axes", "matplotlib.axes._base", "matplotlib.stackplot")


def programs(data):
    sales, weather = f"{data}/sales.csv", f"{data}/weather.csv"
    pd = "import pandas as pd\nimport matplotlib.pyplot as plt\n"
    mp = "import matplotlib.pyplot as plt\n"
    np_ = "import numpy as np\nimport matplotlib.pyplot as plt\n"
    pivot = (
        f"df=pd.read_csv('{sales}')\np=df.pivot(index='month',columns='region',values='revenue')\n"
    )
    return {
        "bar": pd + f"df=pd.read_csv('{sales}')\ng=df.groupby('region')['revenue'].sum()\n"
        "plt.bar(g.index,g.values)\nplt.title('t')\nplt.xlabel('x')\nplt.ylabel('y')",
        "barh": pd + f"df=pd.read_csv('{sales}')\ng=df.groupby('region')['revenue'].sum()\n"
        "plt.barh(g.index,g.values)",
        "bar_numeric": mp + "plt.bar([1,2,3],[4,5,6])",
        "line": pd + f"df=pd.read_csv('{sales}')\ng=df.groupby('month')['revenue'].sum()\n"
        "plt.plot(g.index,g.values,marker='o',label='r')\nplt.legend()\nplt.grid(True)",
        "step": mp + "plt.step([1,2,3],[1,3,2])",
        "scatter": pd + f"df=pd.read_csv('{sales}')\nplt.scatter(df['orders'],df['revenue'])",
        "scatter_colorbar": pd + f"df=pd.read_csv('{sales}')\n"
        "s=plt.scatter(df['orders'],df['revenue'],c=df['orders'],s=df['orders'])\nplt.colorbar(s)",
        "hist": mp + "plt.hist([1,2,2,3,3,3,4],bins=3)",
        "hist_step": mp + "plt.hist([1,2,2,3],bins=2,histtype='step')",
        "stacked_bar": mp + "plt.bar(['a','b'],[1,2],label='x')\n"
        "plt.bar(['a','b'],[3,4],bottom=[1,2],label='y')\nplt.legend()",
        "grouped_bar": np_ + "x=np.arange(2)\nplt.bar(x-0.2,[1,2],0.4,label='x')\n"
        "plt.bar(x+0.2,[3,4],0.4,label='y')\nplt.xticks(x,['a','b'])\nplt.legend()",
        "pie": mp + "plt.pie([1,2,3],labels=['a','b','c'],autopct='%1.1f%%')",
        "fill_between": mp + "plt.fill_between([1,2,3],[1,4,2])",
        "stackplot": mp + "plt.stackplot([1,2,3],[1,2,3],[2,2,2],labels=['a','b'])\nplt.legend()",
        "subplots": mp + "fig,axs=plt.subplots(1,2)\naxs[0].bar(['a','b'],[1,2])\n"
        "axs[1].plot([1,2],[3,4])\nfig.suptitle('s')\nplt.tight_layout()",
        "twinx": mp + "fig,ax=plt.subplots()\nax.plot([1,2],[3,4])\nax.twinx().plot([1,2],[30,40])",
        "pd_bar": pd
        + f"df=pd.read_csv('{sales}')\ndf.groupby('region')['revenue'].sum().plot(kind='bar')",
        "pd_barh": pd
        + f"df=pd.read_csv('{sales}')\ndf.groupby('region')['revenue'].sum().plot.barh()",
        "pd_line": pd
        + f"df=pd.read_csv('{sales}')\ndf.groupby('month')['revenue'].sum().plot(kind='line')",
        "pd_area": pd + pivot + "p.plot.area()",
        "pd_pie": pd + f"df=pd.read_csv('{sales}')\n"
        "df.groupby('region')['revenue'].sum().plot.pie(autopct='%1.0f%%')",
        "pd_hist": pd + f"df=pd.read_csv('{sales}')\ndf['revenue'].plot.hist(bins=3)",
        "pd_scatter": pd + f"df=pd.read_csv('{sales}')\ndf.plot.scatter(x='orders',y='revenue')",
        "pd_stacked": pd + pivot + "p.plot(kind='bar',stacked=True)",
        "pd_grouped": pd + pivot + "p.plot(kind='bar')",
        "pd_lines": pd + pivot + "p.plot()",
        "pd_dates": pd + f"df=pd.read_csv('{weather}',parse_dates=['date'])\n"
        "df.groupby('date')['temp_c'].mean().plot()",
        "text": mp + "b=plt.bar(['a','b'],[1,2])\nplt.bar_label(b)\nplt.text(0,1,'hi')\n"
        "plt.annotate('x',xy=(1,2),xytext=(0.5,1.5),arrowprops=dict(arrowstyle='->'))\n"
        "plt.figtext(0.1,0.1,'f')",
        "reference": mp + "plt.plot([1,2],[3,4])\nplt.axhline(3.5)\nplt.axvline(1.5)\n"
        "plt.axhspan(3,3.2)\nplt.axvspan(1.1,1.2)",
        "imshow": mp + "plt.imshow([[1,2],[3,4]])",
        "pcolormesh": mp + "plt.pcolormesh([[1,2],[3,4]])",
        "contour": np_ + "x=np.arange(3.0)\nplt.contour(x,x,np.outer(x,x))",
        "errorbar": mp + "plt.errorbar([1,2],[3,4],yerr=[0.1,0.2])",
        "boxplot": mp + "plt.boxplot([[1,2,3],[2,3,4]])",
        "violin": mp + "plt.violinplot([[1,2,3],[2,3,4]])",
        "stem": mp + "plt.stem([1,2,3],[1,3,2])",
        "hexbin": mp + "plt.hexbin([1,2,3],[1,3,2],gridsize=3)",
        "fill": mp + "plt.fill([0,1,1],[0,0,1])",
        "fill_betweenx": mp + "plt.fill_betweenx([1,2,3],[1,4,2])",
        "polar": mp + "ax=plt.subplot(projection='polar')\nax.plot([0,1],[1,2])",
        "inset": mp + "fig,ax=plt.subplots()\nax.plot([1,2],[3,4])\n"
        "ax.inset_axes([0.5,0.5,0.4,0.4]).plot([1,2],[1,2])",
        "secondary": mp + "fig,ax=plt.subplots()\nax.plot([1,2],[3,4])\n"
        "ax.secondary_yaxis('right',functions=(lambda v:v*2,lambda v:v/2))",
        "table": mp + "plt.table(cellText=[['1','2']],loc='bottom')\nplt.plot([1,2],[1,2])",
        "broken_barh": mp + "plt.broken_barh([(1,2),(4,1)],(0,1))",
        "eventplot": mp + "plt.eventplot([1,2,3])",
        "quiver": mp + "plt.quiver([0,1],[0,1],[1,1],[1,0])",
        "patch": mp
        + "import matplotlib.patches as mp\nplt.gca().add_patch(mp.Circle((0.5,0.5),0.2))",
        "add_line": mp
        + "import matplotlib.lines as ml\nplt.gca().add_line(ml.Line2D([0,1],[0,1]))",
        "figimage": mp + "plt.figure().figimage([[1,2],[3,4]])",
        "empty": mp + "plt.figure()",
        "nothing": "x=1",
        "two_figs": mp + "plt.figure()\nplt.plot([1,2])\nplt.figure()\nplt.bar(['a'],[1])",
    }


def transform_kind(artist, ax):
    if hasattr(artist, "get_offset_transform") and type(artist).__name__ == "PathCollection":
        transform = artist.get_offset_transform()
    elif hasattr(artist, "get_data_transform") and hasattr(artist, "get_path"):
        transform = artist.get_data_transform()
    else:
        transform = artist.get_transform()
    for name, reference in (
        ("data", ax.transData),
        ("axes", ax.transAxes),
        ("xaxis", ax.get_xaxis_transform()),
        ("yaxis", ax.get_yaxis_transform()),
    ):
        if transform == reference:
            return name
    return "other"


def measure(data):
    # Imported here, after the caller set the backend: the Pyodide leg runs this file by path.
    import matplotlib as mpl  # noqa: PLC0415

    mpl.use("Agg")
    import matplotlib.artist as martist  # noqa: PLC0415
    import matplotlib.pyplot as plt  # noqa: PLC0415

    init = martist.Artist.__init__

    def artist_init(self, *args, **kwargs):
        init(self, *args, **kwargs)
        frame, origin = sys._getframe(1), None
        while frame is not None and frame.f_code.co_filename != PROGRAM:
            if frame.f_globals.get("__name__") in AXES_MODULES:
                origin = frame.f_code.co_qualname
            frame = frame.f_back
        self._i1_origin = origin if frame is not None else None

    martist.Artist.__init__ = artist_init
    cases = {}
    for name, source in programs(data).items():
        plt.close("all")
        error = None
        try:
            exec(compile(source, PROGRAM, "exec"), {"__name__": "__main__"})  # noqa: S102
        except Exception as exc:
            error = type(exc).__name__
        figures = []
        for number in plt.get_fignums():
            figure = plt.figure(number)
            figure.canvas.draw()
            axes = []
            for ax in figure.axes:
                skip = {id(ax.patch), id(ax.xaxis), id(ax.yaxis), id(ax.title), id(ax.legend_)}
                skip |= {id(ax._left_title), id(ax._right_title)}
                skip |= {id(spine) for spine in ax.spines.values()}
                children = [
                    [type(c).__name__, getattr(c, "_i1_origin", None), transform_kind(c, ax)]
                    for c in ax.get_children()
                    if id(c) not in skip
                ]
                axes.append({"class": type(ax).__name__, "children": children})
            others = [
                type(c).__name__
                for c in figure.get_children()
                if c is not figure.patch and c not in figure.axes
            ]
            figures.append({"axes": axes, "others": others})
        cases[name] = {"error": error, "figures": figures}
    plt.close("all")
    return {
        "versions": {"matplotlib": mpl.__version__, "python": sys.version.split()[0]},
        "cases": cases,
    }


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    result = measure(str(root.parents[1] / "data"))
    (root / "i1-host.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(json.dumps(result["versions"]))
