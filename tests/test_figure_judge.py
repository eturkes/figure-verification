# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M19.3 judge: stage order, sites and the branch witnesses the corpus does not reach.

Programs run through the real reader. Where a fact only the sandbox's matplotlib 3.8 writes is
needed (a span drawn as a Polygon) or a shape no program reaches, one field of a real description
is edited, since the judge reads descriptions alone.
"""

import json
from collections.abc import Callable
from typing import Any

import pytest

from verifier.figure import reader
from verifier.figure.description import TAG, parse_description
from verifier.figure.judge import Judged, check_figure, integrity
from verifier.figure.reasons import Blocked, BlockedError

_PLT = "import matplotlib.pyplot as plt\n"


def _judge(source: str) -> Judged | Blocked:
    described = parse_description(reader.run(source))
    assert described is not None
    return integrity(described)


def _edited(source: str, change: Callable[[dict[str, Any]], None]) -> Judged | Blocked:
    raw = json.loads(reader.run(source).splitlines()[0][len(TAG) :])
    change(raw)
    described = parse_description(TAG + json.dumps(raw))
    assert described is not None
    return integrity(described)


def _axes(raw: dict[str, Any], index: int = 0) -> dict[str, Any]:
    axes: dict[str, Any] = raw["figures"][0]["axes"][index]
    return axes


# --- J1 figure stage -----------------------------------------------------------------------------


def test_j1_a_program_error_outranks_a_second_figure() -> None:
    source = _PLT + "plt.figure()\nplt.plot([1])\nplt.figure()\nplt.plot([2])\n1 / 0\n"
    assert _judge(source) == Blocked("program_error", 6)


def test_j1_a_draw_failure_is_a_program_error_without_a_line() -> None:
    assert _judge(_PLT + "plt.plot([1])\nplt.title('$\\\\frac{$')\n") == Blocked("program_error")


def test_j1_an_import_error_is_a_missing_module() -> None:
    assert _judge("from math import nothing\n") == Blocked("module_not_available", 1)


def test_j1_too_large_reads_no_figure_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """A too_large record carries no figures; the judge must not report `no_figure` for it."""
    with monkeypatch.context() as patch:
        patch.setattr(reader, "MAX_COORDINATES", 1)
        text = reader.run(_PLT + "plt.plot([1, 2])\n")
    described = parse_description(text)
    assert described is not None
    with pytest.raises(BlockedError) as raised:
        check_figure(described)
    assert raised.value.blocked == Blocked("figure_too_large")


def test_j1_a_figure_without_axes_has_no_data() -> None:
    assert _judge(_PLT + "plt.figure()\n") == Blocked("no_data", 2)


# --- J2 parts ------------------------------------------------------------------------------------


def test_j2_a_colorbar_of_an_image_is_no_judged_axes() -> None:
    source = _PLT + "image = plt.imshow([[1, 2]])\nplt.colorbar(image)\n"
    assert _judge(source) == Blocked("axes_not_judged", 3)


def test_j2_an_empty_bar_container_adds_no_mark() -> None:
    verdict = _judge(_PLT + "plt.bar([], [])\nplt.plot([1, 2])\n")
    assert isinstance(verdict, Judged)
    assert [mark.family for mark in verdict.panels[0].marks] == ["line"]


def test_j2_a_bar_outside_any_container_is_unjudged() -> None:
    def detach(raw: dict[str, Any]) -> None:
        _axes(raw)["containers"] = []

    assert _edited(_PLT + "plt.bar(['a'], [1])\n", detach) == Blocked("artist_not_judged", 2)


def test_j2_a_pie_record_without_wedges_adds_no_mark() -> None:
    def empty_pie(raw: dict[str, Any]) -> None:
        _axes(raw)["pies"].append({"values": [], "normalize": True, "wedges": [], "texts": []})

    verdict = _edited(_PLT + "plt.plot([1, 2])\n", empty_pie)
    assert isinstance(verdict, Judged)
    assert [mark.family for mark in verdict.panels[0].marks] == ["line"]


# --- J3 axes -------------------------------------------------------------------------------------


def test_j3_a_log_title_states_the_scale_after_a_plain_label() -> None:
    source = _PLT + "plt.plot([1, 10, 100])\nplt.yscale('log')\nplt.ylabel('Value')\n"
    assert _judge(source) == Blocked("scale_not_linear", 3)
    assert isinstance(_judge(source + "plt.title('log scale')\n"), Judged)


def test_j3_japanese_names_the_log_scale() -> None:
    def japanese(raw: dict[str, Any]) -> None:
        _axes(raw)["y"]["label"] = {"text": "値 対数", "site": 3}

    source = _PLT + "plt.plot([1, 10, 100])\nplt.yscale('log')\nplt.ylabel('Value')\n"
    assert isinstance(_edited(source, japanese), Judged)


def test_j3_horizontal_bars_read_their_value_on_x() -> None:
    source = _PLT + "plt.barh(['a', 'b'], [1, 2])\n"
    assert isinstance(_judge(source), Judged)
    assert _judge(source + "plt.xlim(0.5, 3)\n") == Blocked("zero_not_in_limits", 3)


def test_j3_reference_spans_in_either_shape() -> None:
    """3.9 draws `axhspan` as a Rectangle (host), 3.8 as a Polygon (sandbox): both judged."""
    source = _PLT + "plt.plot([1, 2], [1, 4])\nplt.axhspan(2, 3)\n"
    assert isinstance(_judge(source), Judged)

    def polygon(raw: dict[str, Any]) -> None:
        span = _axes(raw)["artists"][1]
        span["cls"] = "Polygon"
        span["geometry"] = {
            "kind": "polygon",
            "xy": [[0.0, 2.0], [0.0, 3.0], [1.0, 3.0], [1.0, 2.0], [0.0, 2.0]],
            "color": span["geometry"]["color"],
            "edge": span["geometry"]["edge"],
            "linewidth": span["geometry"]["linewidth"],
        }

    assert isinstance(_edited(source, polygon), Judged)
    assert _judge(source + "plt.ylim(0, 2.5)\n") == Blocked("point_clipped", 4)


@pytest.mark.parametrize(
    ("formatter", "values", "expected"),
    [
        ("ticker.EngFormatter()", "[1000, 2000, 3000]", "pass"),
        ("ticker.FuncFormatter(lambda v, _: f'{v:.0f}k')", "[1, 2, 3]", "tick_label_mismatch"),
        ("ticker.FuncFormatter(lambda v, _: f'{v / 1000:.0f}k')", "[1000, 2000]", "pass"),
        ("ticker.FuncFormatter(lambda v, _: f'-${-v:,.0f}')", "[-3000, -2000, -1000]", "pass"),
        ("ticker.FuncFormatter(lambda v, _: f'${v:,.2f}')", "[1000, 2000, 3000]", "pass"),
        (
            "ticker.FuncFormatter(lambda v, _: f'${v / 2:,.2f}')",
            "[1000, 2000]",
            "tick_label_mismatch",
        ),
        ("ticker.FuncFormatter(lambda v, _: f'${v:.0f}$')", "[1, 2, 3]", "pass"),
        ("ticker.FuncFormatter(lambda v, _: 'many')", "[1, 2, 3]", "tick_label_mismatch"),
        ("ticker.FuncFormatter(lambda v, _: '$10^{999}$')", "[1, 2, 3]", "tick_label_mismatch"),
        ("ticker.FuncFormatter(lambda v, _: '$0^{2}$')", "[1, 2, 3]", "tick_label_mismatch"),
    ],
    ids=[
        "engineering",
        "prefix-scales",
        "thousands",
        "negative-money",
        "money",
        "halved",
        "mathtext",
        "words",
        "huge-power",
        "zero-base",
    ],
)
def test_j3_numeric_label_forms(formatter: str, values: str, expected: str) -> None:
    source = (
        _PLT
        + "import matplotlib.ticker as ticker\n"
        + f"plt.plot({values})\n"
        + f"plt.gca().yaxis.set_major_formatter({formatter})\n"
    )
    verdict = _judge(source)
    if expected == "pass":
        assert isinstance(verdict, Judged), verdict
    else:
        assert verdict == Blocked("tick_label_mismatch", 4)


def test_j3_a_date_label_needs_a_known_position() -> None:
    def unknown_position(raw: dict[str, Any]) -> None:
        _axes(raw)["x"]["dates"] = []

    source = (
        _PLT
        + "import datetime as dt\n"
        + "d = [dt.datetime(2026, 1, 1), dt.datetime(2026, 1, 2)]\n"
        + "plt.plot(d, [1, 2])\n"
        + "plt.xticks(d, ['2026-01-01', '2026-01-02'])\n"
    )
    assert isinstance(_judge(source), Judged)
    assert _edited(source, unknown_position) == Blocked("tick_label_mismatch", 5)


def test_j3_an_unknown_converter_axis_cannot_carry_labels() -> None:
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
    )
    assert _judge(source) == Blocked("tick_label_mismatch")


# --- J4 marks ------------------------------------------------------------------------------------


def _hist(change: Callable[[dict[str, Any]], None]) -> Judged | Blocked:
    return _edited(_PLT + "plt.hist([1, 2, 2, 3], bins=3)\n", change)


def test_j4_hist_edges_must_increase() -> None:
    def flat(raw: dict[str, Any]) -> None:
        bins = _axes(raw)["containers"][0]["hist"]["bins"]
        bins[1] = bins[0]

    assert _hist(flat) == Blocked("hist_counts", 2)


def test_j4_hist_bars_must_hold_the_counts() -> None:
    def taller(raw: dict[str, Any]) -> None:
        _axes(raw)["artists"][0]["geometry"]["height"] = 2.0

    assert _hist(taller) == Blocked("hist_counts", 2)


def _pie(change: Callable[[dict[str, Any]], None]) -> Judged | Blocked:
    return _edited(_PLT + "plt.pie([1, 2, 3])\n", change)


def _pie_values(values: list[float]) -> Callable[[dict[str, Any]], None]:
    def change(raw: dict[str, Any]) -> None:
        _axes(raw)["pies"][0]["values"] = values

    return change


def _wedge(index: int, field: str, value: float) -> Callable[[dict[str, Any]], None]:
    def change(raw: dict[str, Any]) -> None:
        wedges = [a for a in _axes(raw)["artists"] if a["cls"] == "Wedge"]
        wedges[index]["geometry"][field] = value

    return change


def _boundary(angle: float) -> Callable[[dict[str, Any]], None]:
    """Move the edge between the first two wedges: spans change, contiguity + total hold."""

    def change(raw: dict[str, Any]) -> None:
        wedges = [a for a in _axes(raw)["artists"] if a["cls"] == "Wedge"]
        wedges[0]["geometry"]["theta2"] = angle
        wedges[1]["geometry"]["theta1"] = angle

    return change


@pytest.mark.parametrize(
    "change",
    [
        _pie_values([1.0, 2.0]),
        _pie_values([0.0, 0.0, 0.0]),
        _pie_values([1.0, 1.0, 3.0]),
        _wedge(1, "theta1", 61.0),
        _wedge(2, "theta2", 359.0),
        _boundary(61.0),
    ],
    ids=["count", "zero-total", "share", "gap", "short", "boundary-moved"],
)
def test_j4_pie_rules(change: Callable[[dict[str, Any]], None]) -> None:
    assert _pie(change) == Blocked("pie_not_whole", 2)


def test_j4_a_normalised_partial_pie_is_whole_when_its_shares_sum_to_one() -> None:
    assert isinstance(_judge(_PLT + "plt.pie([0.5, 0.5], normalize=False)\n"), Judged)


# --- legends -------------------------------------------------------------------------------------


def test_legend_a_proxy_without_colour_names_nothing() -> None:
    def colourless(raw: dict[str, Any]) -> None:
        entry = _axes(raw)["legend"]["entries"][0]
        entry.update(target=None, container=None, proxy_color=None)

    source = _PLT + "plt.plot([1, 2], label='a')\nplt.legend()\n"
    assert isinstance(_judge(source), Judged)
    assert _edited(source, colourless) == Blocked("legend_mismatch", 3)


def test_legend_an_encoding_key_must_belong_to_a_scatter() -> None:
    def elsewhere(raw: dict[str, Any]) -> None:
        _axes(raw)["legend"]["entries"][0]["elements_of"] = [0, "sizes"]

    source = _PLT + "plt.plot([1, 2], label='a')\nplt.legend()\n"
    assert _edited(source, elsewhere) == Blocked("legend_mismatch", 3)


def test_figure_legends_name_one_series_anywhere() -> None:
    source = (
        _PLT
        + "fig, (a, b) = plt.subplots(1, 2)\n"
        + "a.plot([1, 2], label='first')\n"
        + "b.plot([2, 1], label='second', color='red')\n"
        + "fig.legend()\n"
    )
    verdict = _judge(source)
    assert isinstance(verdict, Judged)
    assert sorted(verdict.legends.names.values()) == ["first", "second"]
    proxy = source.replace(
        "fig.legend()\n",
        "import matplotlib.patches as patches\n"
        "fig.legend(handles=[patches.Patch(color='C0', label='first')])\n",
    ).replace("label='second', color='red'", "label='first'")
    assert _judge(proxy) == Blocked("legend_mismatch", 6)


def test_j3_log_must_be_its_own_word() -> None:
    source = _PLT + "plt.plot([1, 10, 100])\nplt.yscale('log')\nplt.ylabel('Catalogue size')\n"
    assert _judge(source) == Blocked("scale_not_linear", 3)


def test_j3_a_number_label_must_show_its_position_to_its_last_digit() -> None:
    source = _PLT + "plt.plot([5, 6, 7])\nplt.yticks([5, 6, 7], ['5.1', '6.0', '7.0'])\n"
    assert _judge(source) == Blocked("tick_label_mismatch", 3)
    assert isinstance(_judge(source.replace("'5.1'", "'5.0'")), Judged)


def test_j4_a_bar_continuing_another_runs_the_same_way() -> None:
    source = _PLT + "plt.bar(['a'], [1])\nplt.bar(['a'], [-0.5], bottom=[1])\n"
    assert _judge(source) == Blocked("bar_not_from_zero", 3)
    stacked = _PLT + "plt.bar(['a'], [1])\nplt.bar(['a'], [0.5], bottom=[1])\n"
    assert isinstance(_judge(stacked), Judged)


def test_j4_a_colorbar_explains_its_own_collection_alone() -> None:
    source = (
        _PLT
        + "first = plt.scatter([1, 2], [1, 2], c=[1, 2])\n"
        + "plt.scatter([1, 2], [3, 4], c=[3, 4])\n"
        + "plt.colorbar(first)\n"
    )
    assert _judge(source) == Blocked("marker_color_varies", 3)


def test_legend_a_proxy_in_a_series_colour_must_carry_its_label() -> None:
    source = (
        _PLT
        + "import matplotlib.patches as patches\n"
        + "line, = plt.plot([1, 4, 9], label='values')\n"
        + "plt.legend(handles=[patches.Patch(color=line.get_color(), label='forecast')])\n"
    )
    assert _judge(source) == Blocked("legend_mismatch", 4)
    honest = source.replace("label='forecast'", "label='values'")
    assert isinstance(_judge(honest), Judged)


def test_legend_entries_must_name_judged_marks() -> None:
    """A handle drawn in an unjudged axes, a drawn artist outside any mark, an encoding key of a
    non-scatter or of nothing found: each names nothing judged."""

    def unjudged_axes(raw: dict[str, Any]) -> None:
        _axes(raw)["legend"]["entries"][0]["axes"] = 5

    def no_mark(raw: dict[str, Any]) -> None:
        _axes(raw)["legend"]["entries"][0]["target"] = 7

    def keyed_line(raw: dict[str, Any]) -> None:
        entry = _axes(raw)["legend"]["entries"][0]
        entry["elements_of"] = [0, "sizes"]
        entry["axes"] = 0

    def keyed_nothing(raw: dict[str, Any]) -> None:
        _axes(raw)["legend"]["entries"][0]["elements_of"] = [None, "sizes"]

    source = _PLT + "plt.plot([1, 2], label='a')\nplt.legend()\n"
    assert _edited(source, unjudged_axes) == Blocked("legend_mismatch", 3)
    assert _edited(source, no_mark) == Blocked("legend_mismatch", 3)
    assert _edited(source, keyed_line) == Blocked("legend_mismatch", 3)
    assert _edited(source, keyed_nothing) == Blocked("legend_mismatch", 3)
