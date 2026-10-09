# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M19.2 reader: hooks, capture, errors, facts and caps (`.agent/archive/contracts/m19u2.md` P1-P5).

Every program runs through `reader.run` on the host's matplotlib 3.9.4 and is read back through
`parse_description`; expected values are hand-stated from matplotlib's documented geometry.
"""

import contextlib
import io
from pathlib import Path
from typing import cast

import pytest

from verifier.figure import reader
from verifier.figure.description import (
    BandGeometry,
    Description,
    LineGeometry,
    ProgramError,
    RectGeometry,
    ScatterGeometry,
    Text,
    TextGeometry,
    WedgeGeometry,
    parse_description,
)

_DATA = Path(__file__).resolve().parents[1] / "data"
_PLT = "import matplotlib.pyplot as plt\n"
_PD = "import pandas as pd\nimport matplotlib.pyplot as plt\n"


def _describe(source: str) -> Description:
    described = parse_description(reader.run(source))
    assert described is not None
    return described


def _origins(source: str) -> list[list[tuple[str, str | None, int | None]]]:
    return [
        [(artist.cls, artist.origin, artist.site) for artist in axes.artists]
        for figure in _describe(source).figures
        for axes in figure.axes
    ]


# --- P1 hooks --------------------------------------------------------------------------------


def test_p1_bar_spellings_share_one_origin() -> None:
    """`plt.bar`, `ax.bar` and the pandas accessor all reach `Axes.bar`; site = the program line."""
    pyplot = _origins(_PLT + "plt.bar(['a', 'b'], [1, 2])\n")
    method = _origins(_PLT + "fig, ax = plt.subplots()\nax.bar(['a', 'b'], [1, 2])\n")
    pandas = _origins(_PD + "pd.Series([1, 2], index=['a', 'b']).plot(kind='bar')\n")
    assert pyplot == [[("Rectangle", "Axes.bar", 2), ("Rectangle", "Axes.bar", 2)]]
    assert method == [[("Rectangle", "Axes.bar", 3), ("Rectangle", "Axes.bar", 3)]]
    assert pandas == [[("Rectangle", "Axes.bar", 3), ("Rectangle", "Axes.bar", 3)]]


def test_p1_the_outermost_axes_method_names_the_family() -> None:
    """`hist` builds its bars through `bar`; `stackplot` through `fill_between`."""
    hist = _origins(_PLT + "plt.hist([1, 2, 2], bins=2)\n")
    stack = _origins(_PLT + "plt.stackplot([1, 2], [1, 2], [3, 4])\n")
    assert hist == [[("Rectangle", "Axes.hist", 2), ("Rectangle", "Axes.hist", 2)]]
    assert stack == [[("PolyCollection", "stackplot", 2), ("PolyCollection", "stackplot", 2)]]


def test_p1_an_artist_the_program_builds_itself_has_no_origin() -> None:
    source = (
        _PLT
        + "import matplotlib.patches as patches\n"
        + "import matplotlib.lines as lines\n"
        + "ax = plt.gca()\n"
        + "ax.add_patch(patches.Circle((0.5, 0.5), 0.2))\n"
        + "ax.add_line(lines.Line2D([0, 1], [0, 1]))\n"
    )
    assert _origins(source) == [[("Circle", None, 5), ("Line2D", None, 6)]]


def test_p1_site_is_the_innermost_program_line() -> None:
    """A program function's body line, not the line that called the function."""
    source = (
        _PLT
        + "def draw(ax):\n"
        + "    ax.plot([1, 2], [3, 4])\n"
        + "fig, ax = plt.subplots()\n"
        + "draw(ax)\n"
    )
    assert _origins(source) == [[("Line2D", "Axes.plot", 3)]]


def test_p1_calls_record_the_program_line_alone() -> None:
    """A call the program makes, directly or through pyplot, records its line; pandas' own
    limit and tick calls inside `.plot` record nothing."""
    source = (
        _PD
        + "pd.Series([1, 2], index=['a', 'b']).plot(kind='bar')\n"
        + "plt.ylim(0, 5)\n"
        + "plt.gca().invert_xaxis()\n"
        + "plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: str(v)))\n"
    )
    axes = _describe(source).figures[0].axes[0]
    assert dict(axes.calls) == {"xinvert": 5, "ylim": 4}
    assert dict(axes.y.calls) == {"ticks": 6}
    assert dict(axes.x.calls) == {}


# --- P2 capture ------------------------------------------------------------------------------


def test_p2_each_show_captures_the_figures_open_at_that_moment() -> None:
    source = _PLT + "plt.plot([1, 2])\nplt.show()\nplt.bar(['a'], [1])\nplt.show()\n"
    described = _describe(source)
    assert [[a.cls for a in f.axes[0].artists] for f in described.figures] == [
        ["Line2D"],
        ["Rectangle"],
    ]


def test_p2_open_figures_are_captured_at_the_end() -> None:
    described = _describe(_PLT + "plt.plot([1, 2])\n")
    assert len(described.figures) == 1
    assert described.error is None


def test_p2_a_closed_figure_is_no_figure() -> None:
    assert _describe(_PLT + "plt.plot([1, 2])\nplt.close('all')\n").figures == ()


def test_p2_program_output_never_reaches_the_reply() -> None:
    """The sandbox reply is the whole stdout + stderr, so the program writes to a sink."""
    printed, errors = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(errors):
        text = reader.run(
            _PLT + "import sys\nprint('hello')\nsys.stderr.write('oops')\nplt.plot([1])\n"
        )
    assert (printed.getvalue(), errors.getvalue()) == ("", "")
    lines = text.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith(reader.TAG)
    assert lines[1].startswith(reader.PNG_PREFIX)


def test_p2_two_figures_carry_no_png_line() -> None:
    text = reader.run(_PLT + "plt.figure()\nplt.plot([1])\nplt.figure()\nplt.plot([2])\n")
    assert [line[:5] for line in text.splitlines()] == [reader.TAG[:5]]


def test_p2_a_failure_after_show_keeps_the_shown_figure() -> None:
    described = _describe(_PLT + "plt.plot([1, 2])\nplt.show()\n1 / 0\n")
    assert described.error == ProgramError("exception", "ZeroDivisionError", 4)
    assert len(described.figures) == 1


# --- P3 errors -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("x = (1,\n", ProgramError("syntax", "SyntaxError", 1)),
        ("x = 1\nprint(undefined)\n", ProgramError("exception", "NameError", 2)),
        ("import seaborn\n", ProgramError("exception", "ModuleNotFoundError", 1)),
        (
            _PLT + "plt.plot([1, 2], [1, 2, 3])\n",
            ProgramError("exception", "ValueError", 2),
        ),
        ("import sys\nsys.exit(3)\n", ProgramError("exception", "SystemExit", 2)),
        ("def f():\n    return 1 / 0\nf()\n", ProgramError("exception", "ZeroDivisionError", 2)),
    ],
    ids=["syntax", "name", "module", "inside-matplotlib", "exit", "innermost"],
)
def test_p3_errors(source: str, expected: ProgramError) -> None:
    assert _describe(source).error == expected


def test_p3_a_draw_failure_is_its_own_kind() -> None:
    """A figure the program leaves undrawable fails at the reader's own draw."""
    source = _PLT + "plt.plot([1, 2])\nplt.title('$\\\\frac{$')\n"
    described = _describe(source)
    assert described.error == ProgramError("draw", "draw", None)
    assert described.figures == ()


# --- P4 facts --------------------------------------------------------------------------------


def test_p4_category_bars() -> None:
    axes = _describe(_PLT + "plt.bar(['b', 'a'], [1.5, 2])\nplt.title('T')\n").figures[0].axes[0]
    assert axes.x.kind == "category"
    assert axes.x.categories == (("b", 0.0), ("a", 1.0))
    assert axes.x.ticks == ((0.0, "b"), (1.0, "a"))
    assert axes.titles == (None, Text("T", 3), None)
    blue = (0.12156862745098039, 0.4666666666666667, 0.7058823529411765, 1.0)
    rects = [artist.geometry for artist in axes.artists]
    assert [
        (r.x, r.y, r.width, r.height, r.angle, r.color)
        for r in rects
        if isinstance(r, RectGeometry)
    ] == [(-0.4, 0.0, 0.8, 1.5, 0.0, blue), (0.6, 0.0, 0.8, 2.0, 0.0, blue)]
    assert [(c.cls, c.orientation, c.members) for c in axes.containers] == [
        ("BarContainer", "vertical", (0, 1))
    ]
    assert all(artist.transform == "data" for artist in axes.artists)


def test_p4_pandas_bar_sets_labels_on_a_numeric_axis() -> None:
    axes = (
        _describe(_PD + "pd.Series([3, 4], index=['x', 'y']).plot(kind='bar')\n").figures[0].axes[0]
    )
    assert (axes.x.kind, axes.x.formatter, axes.x.formatter_module) == (
        "numeric",
        "FuncFormatter",
        "matplotlib.axis",
    )
    assert axes.x.ticks == ((0.0, "x"), (1.0, "y"))


def test_p4_scalar_formatter_offset_and_order() -> None:
    axes = _describe(_PLT + "plt.plot([1, 2], [100001, 100002])\n").figures[0].axes[0]
    assert (axes.y.formatter, axes.y.offset, axes.y.order) == ("ScalarFormatter", 100000.0, 0)
    big = _describe(_PLT + "plt.plot([1, 2], [1e7, 3e7])\n").figures[0].axes[0]
    assert (big.y.offset, big.y.order) == (0.0, 7)


def test_p4_percent_and_log_axes() -> None:
    source = (
        _PLT
        + "import matplotlib.ticker as ticker\n"
        + "plt.plot([1, 10], [0.1, 0.5])\n"
        + "plt.gca().yaxis.set_major_formatter(ticker.PercentFormatter(1.0))\n"
        + "plt.xscale('log')\n"
    )
    axes = _describe(source).figures[0].axes[0]
    assert (axes.y.formatter, axes.y.percent_xmax) == ("PercentFormatter", 1.0)
    assert (axes.x.scale, axes.x.formatter) == ("log", "LogFormatterSciNotation")


def test_p4_date_axes_read_calendar_positions() -> None:
    weather = _DATA / "weather.csv"
    matplotlib_dates = (
        _describe(
            _PD
            + f"df = pd.read_csv({str(weather)!r}, parse_dates=['date'])\n"
            + "plt.plot(df['date'][::2], df['temp_c'][::2])\n"
        )
        .figures[0]
        .axes[0]
    )
    pandas_periods = (
        _describe(
            _PD
            + f"df = pd.read_csv({str(weather)!r}, parse_dates=['date'])\n"
            + "df.groupby('date')['temp_c'].mean().plot()\n"
        )
        .figures[0]
        .axes[0]
    )
    assert matplotlib_dates.x.kind == pandas_periods.x.kind == "date"
    assert (20454.0, "2026-01-01T00:00:00") in matplotlib_dates.x.dates
    assert (20457.0, "2026-01-04T00:00:00") in pandas_periods.x.dates


def test_p4_legends_name_artists_containers_and_proxies() -> None:
    source = (
        _PD
        + "fig, (a, b) = plt.subplots(1, 2)\n"
        + "a.plot([1, 2], label='line')\n"
        + "a.bar([1, 2], [3, 4], label='bars')\n"
        + "a.legend()\n"
        + "pd.DataFrame({'p': [1, 2], 'q': [3, 4]}).plot(kind='bar', ax=b)\n"
        + "import matplotlib.patches as patches\n"
        + "fig.legend(handles=[patches.Patch(color='red', label='r')])\n"
    )
    figure = _describe(source).figures[0]
    first, second = figure.axes
    assert first.legend is not None and second.legend is not None
    entries = [(e.text, e.target, e.container, e.proxy_color) for e in first.legend.entries]
    assert entries == [("line", 0, None, None), ("bars", None, 0, None)]
    pandas = [(e.text, e.target, e.container, e.proxy_color) for e in second.legend.entries]
    assert pandas == [("p", None, 0, None), ("q", None, 1, None)]
    proxy = [(e.text, e.target, e.container, e.proxy_color) for e in figure.legends[0].entries]
    assert proxy == [("r", None, None, (1.0, 0.0, 0.0, 1.0))]


def test_p4_scatter_colorbar_and_size_legend() -> None:
    source = (
        _PLT
        + "s = plt.scatter([1, 2], [3, 4], c=[5, 6], s=[10, 40])\n"
        + "plt.colorbar(s)\n"
        + "plt.legend(*s.legend_elements('sizes'))\n"
    )
    scatter_axes, bar_axes = _describe(source).figures[0].axes
    assert scatter_axes.artists[0].transform == "data"
    geometry = scatter_axes.artists[0].geometry
    assert isinstance(geometry, ScatterGeometry)
    assert (geometry.offsets, geometry.sizes, geometry.array, geometry.colorbar) == (
        ((1.0, 3.0), (2.0, 4.0)),
        (10.0, 40.0),
        (5.0, 6.0),
        True,
    )
    assert bar_axes.colorbar_of == (0, 0)
    assert scatter_axes.legend is not None
    assert {e.elements_of for e in scatter_axes.legend.entries} == {(0, "sizes")}


def test_p4_hist_pie_and_band_records() -> None:
    hist = _describe(_PLT + "plt.hist([1, 2, 2, 4], bins=3, density=True)\n").figures[0].axes[0]
    record = hist.containers[0].hist
    assert record is not None
    assert (record.values, record.bins, record.density, record.datasets) == (
        (1.0, 2.0, 2.0, 4.0),
        (1.0, 2.0, 3.0, 4.0),
        True,
        1,
    )
    pie = _describe(_PLT + "plt.pie([1, 3], labels=['a', 'b'])\n").figures[0].axes[0]
    assert [(p.values, p.normalize, p.wedges, p.texts) for p in pie.pies] == [
        ((1.0, 3.0), True, (0, 2), (1, 3))
    ]
    assert [pie.artists[i].geometry for i in (1, 3)] == [TextGeometry("a"), TextGeometry("b")]
    wedge = pie.artists[0].geometry
    assert isinstance(wedge, WedgeGeometry)
    assert (wedge.theta1, wedge.theta2, wedge.r) == (0.0, 90.0, 1.0)
    band = _describe(_PLT + "plt.fill_between([1, 2], [3, 4])\n").figures[0].axes[0]
    geometry = band.artists[0].geometry
    assert isinstance(geometry, BandGeometry) and geometry.band is not None
    assert (geometry.band.x, geometry.band.y1, geometry.band.y2) == (
        (1.0, 2.0),
        (3.0, 4.0),
        (0.0, 0.0),
    )


def test_p4_twin_axes_share_x() -> None:
    source = _PLT + "fig, ax = plt.subplots()\nax.plot([1, 2])\nax.twinx().plot([3, 4])\n"
    first, second = _describe(source).figures[0].axes
    assert (first.shared_x, second.shared_x, first.position == second.position) == (
        (1,),
        (0,),
        True,
    )
    assert dict(first.calls) == {"twin": 4}


def test_p4_inset_and_figure_parts() -> None:
    source = (
        _PLT
        + "fig, ax = plt.subplots()\n"
        + "ax.plot([1, 2])\n"
        + "ax.inset_axes([0.5, 0.5, 0.3, 0.3])\n"
        + "fig.suptitle('S')\n"
        + "fig.text(0.1, 0.1, 'note')\n"
        + "fig.figimage([[1, 2], [3, 4]])\n"
    )
    figure = _describe(source).figures[0]
    assert [(a.cls, a.origin) for a in figure.axes[0].artists] == [
        ("Line2D", "Axes.plot"),
        ("Axes", "Axes.inset_axes"),
    ]
    assert figure.titles == (Text("S", 5), None, None)
    assert figure.texts == (Text("note", 6),)
    assert [(p.cls, p.site) for p in figure.others] == [("FigureImage", 7)]


def test_p4_reference_marks_use_blended_transforms() -> None:
    source = _PLT + "plt.plot([1, 2], [3, 4])\nplt.axhline(3.5)\nplt.axvline(1.5)\n"
    artists = _describe(source).figures[0].axes[0].artists
    assert [(a.origin, a.transform) for a in artists] == [
        ("Axes.plot", "data"),
        ("Axes.axhline", "yaxis"),
        ("Axes.axvline", "xaxis"),
    ]
    line = artists[1].geometry
    assert isinstance(line, LineGeometry)
    assert (line.x, line.y) == ((0.0, 1.0), (3.5, 3.5))


def test_p4_glyphs_count_missing_characters() -> None:
    assert _describe(_PLT + "plt.plot([1])\nplt.title('年')\n").glyphs > 0
    assert _describe(_PLT + "plt.plot([1])\nplt.title('ok')\n").glyphs == 0


def test_p4_each_run_starts_from_matplotlib_defaults() -> None:
    reader.run(_PLT + "plt.rcParams['lines.linewidth'] = 9\nplt.plot([1])\n")
    import matplotlib as mpl  # noqa: PLC0415 - the reader imports it lazily too

    assert mpl.rcParams["lines.linewidth"] == 9
    reader.run(_PLT + "plt.plot([1])\n")
    assert mpl.rcParams["lines.linewidth"] == 1.5


# --- P5 caps ---------------------------------------------------------------------------------


def _capped(monkeypatch: pytest.MonkeyPatch, name: str, value: int, source: str) -> str:
    with monkeypatch.context() as patch:
        patch.setattr(reader, name, value)
        return reader.run(source)


@pytest.mark.parametrize(
    ("name", "at_cap", "over_cap", "source"),
    [
        ("MAX_COORDINATES", 3, 2, _PLT + "plt.plot([1, 2, 3])\n"),
        ("MAX_CHILDREN", 2, 1, _PLT + "plt.bar(['a', 'b'], [1, 2])\n"),
        (
            "MAX_AXES",
            2,
            1,
            _PLT + "fig, ax = plt.subplots(1, 2)\nax[0].plot([1])\nax[1].plot([2])\n",
        ),
    ],
    ids=["coordinates", "children", "axes"],
)
def test_p5_caps(
    monkeypatch: pytest.MonkeyPatch, name: str, at_cap: int, over_cap: int, source: str
) -> None:
    within = parse_description(_capped(monkeypatch, name, at_cap, source))
    over_text = _capped(monkeypatch, name, over_cap, source)
    over = parse_description(over_text)
    assert within is not None and not within.too_large and len(within.figures) == 1
    assert over is not None and over.too_large and over.figures == ()
    assert len(over_text.splitlines()) == 1


def test_p5_text_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Text over the cap is never cut: the whole description becomes the `too_large` record."""
    source = _PLT + "plt.plot([1])\nplt.title('abcdefghij')\n"
    within = parse_description(_capped(monkeypatch, "MAX_TEXT", 10, source))
    over_text = _capped(monkeypatch, "MAX_TEXT", 9, source)
    over = parse_description(over_text)
    assert within is not None and within.figures[0].axes[0].titles[1] == Text("abcdefghij", 3)
    assert over is not None and over.too_large and over.figures == ()
    assert len(over_text.splitlines()) == 1


@pytest.mark.parametrize(
    ("name", "limit"),
    [("MAX_DESCRIPTION_BYTES", 200), ("MAX_PNG_CHARACTERS", 100)],
)
def test_p5_reply_sizes(monkeypatch: pytest.MonkeyPatch, name: str, limit: int) -> None:
    text = _capped(monkeypatch, name, limit, _PLT + "plt.plot([1, 2])\n")
    described = parse_description(text)
    assert described is not None and described.too_large
    assert len(text.splitlines()) == 1


# --- branch witnesses ------------------------------------------------------------------------


def test_a_figure_after_a_capped_one_stays_undescribed(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _PLT + "plt.plot([1, 2, 3])\nplt.show()\nplt.plot([1])\nplt.show()\n"
    text = _capped(monkeypatch, "MAX_COORDINATES", 2, source)
    described = parse_description(text)
    assert described is not None and described.too_large and described.figures == ()


def test_non_finite_coordinates_travel_as_strings() -> None:
    line = _describe(_PLT + "plt.plot([1, 2, 3], [1, float('nan'), float('inf')])\n")
    geometry = line.figures[0].axes[0].artists[0].geometry
    assert isinstance(geometry, LineGeometry)
    assert repr(geometry.y) == "(1.0, nan, inf)"
    negative = _describe(_PLT + "plt.plot([1, 2], [1, float('-inf')])\n")
    geometry = negative.figures[0].axes[0].artists[0].geometry
    assert isinstance(geometry, LineGeometry)
    assert geometry.y == (1.0, float("-inf"))


def test_a_holder_from_another_reader_is_unwound() -> None:
    """A runtime that ran an older reader: its hooks come off before this version's go on."""
    import matplotlib.artist as martist  # noqa: PLC0415 - imported where the reader imports it

    reader.run(_PLT + "plt.plot([1])\n")
    old = getattr(martist, "_figure_verification_hooks")  # noqa: B009 - the stored holder
    hooked_init = martist.Artist.__init__
    old.version = "figure-description/0"
    reader.run(_PLT + "plt.plot([1])\n")
    new = getattr(martist, "_figure_verification_hooks")  # noqa: B009
    assert new is not old and old.originals == []
    assert martist.Artist.__init__ is not hooked_init
    assert new.originals[0][2] is not hooked_init


def test_show_outside_a_run_is_matplotlib_s_own() -> None:
    reader.run(_PLT + "plt.plot([1])\n")
    import matplotlib.pyplot as plt  # noqa: PLC0415

    plt.plot([1])
    plt.show()  # Agg's own show: nothing captured, no run active
    assert plt.get_fignums() == [1]
    plt.close("all")


def test_polygons_and_unknown_converters() -> None:
    source = (
        _PLT
        + "import matplotlib.units as units\n"
        + "class Box:\n"
        + "    def __init__(self, v):\n"
        + "        self.v = v\n"
        + "class Convert(units.ConversionInterface):\n"
        + "    @staticmethod\n"
        + "    def convert(value, unit, axis):\n"
        + "        return [b.v for b in value] if hasattr(value, '__iter__') else value.v\n"
        + "units.registry[Box] = Convert()\n"
        + "plt.plot([Box(1), Box(2)], [3, 4])\n"
        + "plt.fill([1, 2, 2], [3, 3, 4])\n"
    )
    axes = _describe(source).figures[0].axes[0]
    assert axes.x.kind == "unknown"
    assert [(a.cls, a.origin) for a in axes.artists] == [
        ("Line2D", "Axes.plot"),
        ("Polygon", "Axes.fill"),
    ]


def test_date_axis_edge_positions() -> None:
    """Non-finite and out-of-calendar positions read as no date; polygons and bars contribute."""
    source = (
        _PD
        + "import datetime\n"
        + "d = [datetime.datetime(2026, 1, 1), datetime.datetime(2026, 1, 2)]\n"
        + "plt.plot(d, [1, 2])\n"
        + "plt.bar(d, [1, float('nan')], width=0.5)\n"
        + "plt.fill(d + [d[0]], [0, 1, 1])\n"
        + "plt.axvline(1e12)\n"
        + "plt.xlim(d[0], d[1])\n"
    )
    axes = _describe(source).figures[0].axes[0]
    dates = dict(axes.x.dates)
    assert axes.x.kind == "date"
    assert dates[20454.0] == "2026-01-01T00:00:00"
    assert dates[1e12] is None


def test_period_positions_off_the_ordinal_grid() -> None:
    weather = _DATA / "weather.csv"
    source = (
        _PD
        + f"df = pd.read_csv({str(weather)!r}, parse_dates=['date'])\n"
        + "df.groupby('date')['temp_c'].mean().plot()\n"
        + "plt.axvline(20454.5)\n"
        + "plt.axvline(float('nan'))\n"
    )
    dates = dict(_describe(source).figures[0].axes[0].x.dates)
    assert dates[20454.5] is None
    assert dates[20454.0] == "2026-01-01T00:00:00"


def test_legend_handle_colours_by_family() -> None:
    source = (
        _PLT
        + "fig, ax = plt.subplots()\n"
        + "bars = ax.bar(['a'], [1], color='red', label='b')\n"
        + "empty = ax.bar([], [], label='e')\n"
        + "dots = ax.scatter([1], [1], facecolors='none', edgecolors='k', label='s')\n"
        + "image = ax.imshow([[1]])\n"
        + "line, = ax.plot([1], color='blue', label='l')\n"
        + "fig.legend([bars, empty, dots, image, line], ['b', 'e', 's', 'i', 'l'])\n"
    )
    entries = _describe(source).figures[0].legends[0].entries
    assert [(e.text, e.axes, e.target, e.container, e.proxy_color) for e in entries] == [
        ("b", 0, None, 0, None),
        ("e", 0, None, 1, None),
        ("s", 0, 1, None, None),
        ("l", 0, 3, None, None),
    ]


def test_a_colorbar_of_an_undrawn_mappable_locates_nothing() -> None:
    source = (
        _PLT
        + "import matplotlib.cm as cm\n"
        + "fig, ax = plt.subplots()\n"
        + "ax.plot([1, 2])\n"
        + "fig.colorbar(cm.ScalarMappable(), ax=ax)\n"
    )
    plot_axes, colorbar_axes = _describe(source).figures[0].axes
    assert (plot_axes.colorbar_of, colorbar_axes.colorbar_of) == (None, None)


def test_a_font_becomes_the_fallback_family() -> None:
    import matplotlib as mpl  # noqa: PLC0415

    font = Path(mpl.get_data_path()) / "fonts" / "ttf" / "DejaVuSerif.ttf"
    reader.run(_PLT + "plt.plot([1])\n", font=str(font))
    assert mpl.rcParams["font.family"] == ["DejaVu Sans", "DejaVu Serif"]


# --- review witnesses (reviewer-1, M19.2) --------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        "plt.hist('v', data={'v': [1, 2, 2]}, bins=[1, 2, 3])\n",
        "plt.pie('v', labels='k', data={'v': [1, 3], 'k': ['a', 'b']})\n",
        "plt.fill_between('x', 'y', data={'x': [1, 2], 'y': [3, 4]})\n",
        "import datetime as dt\n"
        "plt.fill_between([dt.date(2026, 1, 1), dt.date(2026, 1, 2)], [3, 4])\n",
    ],
    ids=["hist-data", "pie-data", "area-data", "area-date"],
)
def test_f3_recorders_keep_valid_calls_valid(body: str) -> None:
    """F3: a call matplotlib draws stays a success, and its construction facts are kept."""
    described = _describe(_PLT + body)
    assert described.error is None
    axes = described.figures[0].axes[0]
    records = [c.hist for c in axes.containers if c.hist is not None]
    bands = [a.geometry.band for a in axes.artists if isinstance(a.geometry, BandGeometry)]
    assert records or axes.pies or any(band is not None for band in bands)
    if records:
        assert records[0].values == (1.0, 2.0, 2.0)
    if axes.pies:
        texts = [axes.artists[cast("int", i)].geometry for i in axes.pies[0].texts]
        assert (axes.pies[0].values, texts) == ((1.0, 3.0), [TextGeometry("a"), TextGeometry("b")])


def test_f3_a_record_matplotlib_cannot_express_as_numbers_is_skipped() -> None:
    """A date histogram draws; its inputs are no floats, so no record is kept (judge refuses)."""
    source = _PLT + "import datetime as dt\n"
    source += "plt.hist([dt.datetime(2026, 1, 1), dt.datetime(2026, 1, 2)], bins=2)\n"
    described = _describe(source)
    assert described.error is None
    assert [c.hist for c in described.figures[0].axes[0].containers] == [None]


def test_f3_band_arrays_read_back_converted_dates() -> None:
    source = _PLT + "import datetime as dt\n"
    source += "plt.fill_between([dt.date(2026, 1, 1), dt.date(2026, 1, 2)], [3, 4])\n"
    geometry = _describe(source).figures[0].axes[0].artists[0].geometry
    assert isinstance(geometry, BandGeometry) and geometry.band is not None
    assert (geometry.band.x, geometry.band.y1, geometry.band.y2) == (
        (20454.0, 20455.0),
        (3.0, 4.0),
        (0.0, 0.0),
    )


def test_f3_a_band_drawn_with_where_carries_no_arrays() -> None:
    source = _PLT + "plt.fill_between([1, 2, 3], [1, 2, 1], where=[True, False, True])\n"
    for artist in _describe(source).figures[0].axes[0].artists:
        assert isinstance(artist.geometry, BandGeometry) and artist.geometry.band is None


def test_f4_right_hand_tick_labels_are_reported() -> None:
    source = (
        _PLT
        + "fig, ax = plt.subplots()\n"
        + "ax.plot([1, 2], [1, 2])\n"
        + "ax.set_yticks([1, 2], ['100', '200'])\n"
        + "ax.tick_params(axis='y', labelleft=False, labelright=True)\n"
    )
    assert _describe(source).figures[0].axes[0].y.ticks == ((1.0, "100"), (2.0, "200"))


def test_f5_legend_entries_read_their_displayed_text() -> None:
    source = (
        _PLT
        + "fig, ax = plt.subplots()\n"
        + "ax.plot([1, 2], [1, 2], label='revenue')\n"
        + "legend = ax.legend()\n"
        + "legend.get_texts()[0].set_text('orders')\n"
    )
    legend = _describe(source).figures[0].axes[0].legend
    assert legend is not None
    assert [(e.text, e.target) for e in legend.entries] == [("orders", 0)]


def test_f7_the_children_cap_counts_the_whole_figure(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _PLT + "fig, ax = plt.subplots(1, 2)\nax[0].plot([1])\nax[1].plot([2])\n"
    within = parse_description(_capped(monkeypatch, "MAX_CHILDREN", 2, source))
    over = parse_description(_capped(monkeypatch, "MAX_CHILDREN", 1, source))
    assert within is not None and not within.too_large
    assert over is not None and over.too_large


def test_f8_a_description_at_the_cap_decodes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reader and decoder measure the same bytes: the JSON after the tag."""
    from verifier.figure import description  # noqa: PLC0415 - the module whose cap is moved

    source = _PLT + "plt.plot([1, 2])\n"
    body = reader.run(source).splitlines()[0][len(reader.TAG) :]
    size = len(body.encode("utf-8"))
    monkeypatch.setattr(reader, "MAX_DESCRIPTION_BYTES", size)
    monkeypatch.setattr(description, "MAX_BYTES", size)
    at_cap = parse_description(reader.run(source))
    assert at_cap is not None and not at_cap.too_large
    monkeypatch.setattr(reader, "MAX_DESCRIPTION_BYTES", size - 1)
    over = parse_description(reader.run(source))
    assert over is not None and over.too_large


def test_f11_line_separators_inside_text_survive_the_transport() -> None:
    title = _describe(_PLT + "plt.plot([1])\nplt.title('a\\u2028b\\u0085c')\n")
    assert title.figures[0].axes[0].titles[1] == Text("a\u2028b\u0085c", 3)


def test_f1_the_same_reader_exec_d_again_reuses_its_holder() -> None:
    import matplotlib.artist as martist  # noqa: PLC0415

    source = Path(reader.__file__).read_text(encoding="utf-8")
    holders = []
    for _ in range(2):
        namespace: dict[str, object] = {"__name__": "figure_verification_reader"}
        exec(compile(source, "<figure-reader>", "exec"), namespace)  # noqa: S102 - as the wrapper does
        run = namespace["run"]
        assert callable(run)
        run(_PLT + "plt.plot([1])\n")
        holders.append(getattr(martist, "_figure_verification_hooks"))  # noqa: B009
    assert holders[0] is holders[1]


def test_f2_one_capture_draws_once() -> None:
    source = (
        _PLT
        + "fig, ax = plt.subplots()\n"
        + "ax.plot([1, 2])\n"
        + "events = []\n"
        + "fig.canvas.mpl_connect('draw_event', lambda e: events.append(1))\n"
        + "plt.show()\n"
        + "assert len(events) == 1, len(events)\n"
    )
    assert _describe(source).error is None


@pytest.mark.parametrize(
    ("vertices", "expected"),
    [
        ("[(1, 0), (1, 3), (2, 4), (2, 0), (2, 0)]", None),
        ("[(1, 0), (1, 3), (2, 4), (2, 0), (2, 0), (1, 0)]", ((1.0, 2.0), (3.0, 4.0))),
        ("[(1, 0), (1, 3), (2, 4), (2, 0), (2, 0), (1, 1)]", None),
        ("[(1, 0), (1, 3), (2, 4), (3, 0), (2, 0), (1, 0)]", None),
        ("[(1, 0), (1, 3), (3, 4), (2, 0), (2, 0), (1, 0)]", None),
    ],
    ids=["even-count", "layout", "start-moved", "turn-moved", "x-moved"],
)
def test_a_band_reads_back_only_the_fill_between_layout(
    vertices: str, expected: tuple[tuple[float, ...], tuple[float, ...]] | None
) -> None:
    """Final geometry decides: a plain band whose polygon the program replaced keeps no arrays.

    `set_verts` closes each polygon itself, so each case lists one vertex fewer than it draws.
    """
    source = _PLT + "band = plt.fill_between([1, 2], [3, 4])\n" + f"band.set_verts([{vertices}])\n"
    geometry = _describe(source).figures[0].axes[0].artists[0].geometry
    assert isinstance(geometry, BandGeometry)
    read = None if geometry.band is None else (geometry.band.x, geometry.band.y1)
    assert read == expected


def test_proxy_handles_drawn_elsewhere_carry_their_own_colour() -> None:
    """A handle from a figure the program closed is no drawn artist: its colour is read off it."""
    source = (
        _PLT
        + "other = plt.figure().gca()\n"
        + "dots = other.scatter([1], [1], color='red')\n"
        + "rings = other.scatter([1], [1], facecolors='none', edgecolors='k')\n"
        + "bars = other.bar([1], [1], color='blue')\n"
        + "empty = other.bar([], [])\n"
        + "plt.close(other.figure)\n"
        + "plt.plot([1, 2])\n"
        + "plt.legend([dots, rings, bars, empty], ['d', 'r', 'b', 'e'])\n"
    )
    legend = _describe(source).figures[0].axes[0].legend
    assert legend is not None
    assert [(e.text, e.axes, e.proxy_color) for e in legend.entries] == [
        ("d", None, (1.0, 0.0, 0.0, 1.0)),
        ("r", None, None),
        ("b", None, (0.0, 0.0, 1.0, 1.0)),
        ("e", None, None),
    ]


@pytest.mark.parametrize(
    ("message", "counted"),
    [
        # matplotlib 3.8.4 (the Pyodide sandbox), measured by the C1 bundle leg (M19.6).
        ("Glyph 22770 (\\N{CJK UNIFIED IDEOGRAPH-58F2}) missing from current font.", True),
        # matplotlib 3.9.4 (the gate host).
        ("Glyph 22770 (\\N{CJK UNIFIED IDEOGRAPH-58F2}) missing from font(s) DejaVu Sans.", True),
        ("Glyph missing from current font.", False),
        ("Font family 'x' not found.", False),
    ],
)
def test_m19_6_a_missing_glyph_counts_in_either_matplotlib(message: str, *, counted: bool) -> None:
    """The sandbox's matplotlib words the warning differently from the host's; both count."""
    pattern = vars(reader)["_GLYPH"]
    assert (pattern.match(message) is not None) is counted


@pytest.mark.parametrize(("title", "missing"), [("$年$", True), ("$x^2$", False)])
def test_m19_9_a_mathtext_glyph_the_font_lacks_counts(title: str, *, missing: bool) -> None:
    """Mathtext reports a glyph its font set lacks through matplotlib's LOGGER, not `warnings`
    (`Font 'default' does not have a glyph for …, substituting with a dummy symbol.`), so the
    warnings capture alone drew tofu and passed it (F7's `ja-mathtext` leg, M19.9)."""
    program = f"import matplotlib.pyplot as plt\nplt.plot([1, 2])\nplt.title({title!r})\n"
    described = parse_description(reader.run(program))
    assert described is not None
    assert (described.glyphs > 0) is missing
