# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M19.6 acceptance pins over the rule corpus (`.agent/deferred.md` row "Integrity redesign").

The corpus harness (`tests/test_figure_corpus.py`) runs each case; these pins decide that the
corpus covers what the acceptance clause names: every chart kind both ways, one witness per I1
census type outside the judged set, and the named source cases.
"""

import json
import tomllib
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from verifier.figure import reader
from verifier.figure.description import TAG

_CORPUS = Path(__file__).parent / "figure_corpus"
_DATA = Path(__file__).resolve().parents[1] / "data"
_OUTSIDE = frozenset({"artist_not_judged", "raster_image", "axes_not_judged"})
# The integrity rules a misleading program may break (the run + figure faults excluded).
_RULE_REASONS = frozenset(
    {
        "raster_image",
        "axes_not_judged",
        "axes_twin",
        "axes_overlap",
        "artist_not_judged",
        "no_data",
        "mark_not_in_data",
        "scale_not_linear",
        "axis_inverted",
        "zero_not_in_limits",
        "tick_label_mismatch",
        "point_clipped",
        "mark_hidden",
        "value_not_finite",
        "bar_not_from_zero",
        "bars_overlap",
        "x_not_ordered",
        "hist_counts",
        "pie_not_whole",
        "area_not_from_zero",
        "marker_size_varies",
        "marker_color_varies",
        "legend_mismatch",
        "category_not_unique",
        "value_not_found",
        "label_not_in_request",
        "column_not_requested",
        "column_not_named",
        "label_not_consistent",
    }
)


def _cases() -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for path in sorted(_CORPUS.glob("*.toml")):
        for case in tomllib.loads(path.read_text(encoding="utf-8"))["case"]:
            found[case["id"]] = case
    return found


_ALL = _cases()


@cache
def _description(case_id: str) -> dict[str, Any]:
    program = _ALL[case_id]["program"]
    program = program.replace("{data}", str(_DATA)).replace("{corpus}", str(_CORPUS))
    line = reader.run(program).splitlines()[0]
    described: dict[str, Any] = json.loads(line[len(TAG) :])
    return described


def _types(case_id: str) -> set[str]:
    """Every (class, origin) the figure holds, as `class|origin`."""
    found: set[str] = set()
    for figure in _description(case_id)["figures"]:
        for axes in figure["axes"]:
            found |= {f"{artist['cls']}|{artist['origin']}" for artist in axes["artists"]}
        found |= {f"{part['cls']}|{part['origin']}" for part in figure["others"]}
    return found


# Hand-stated: every I1 census type outside the judged set -> its witness case (the census list =
# `.agent/measurements/expected/I1.json` `sandbox_families`).
_CENSUS_WITNESSES = {
    "AxesImage|Axes.imshow": "imshow",
    "Axes|Axes.inset_axes": "inset-axes",
    "Circle|None": "colorbar-user-patch",
    "EventCollection|Axes.eventplot": "eventplot",
    "Line2D|Axes.boxplot": "boxplot",
    "Line2D|Axes.errorbar": "errorbar",
    "Line2D|Axes.stem": "stem",
    "Line2D|None": "user-line",
    "LineCollection|Axes.errorbar": "errorbar",
    "LineCollection|Axes.stem": "stem",
    "LineCollection|Axes.violinplot": "violin",
    "LineCollection|None": "user-line-collection",
    "PolyCollection|Axes.broken_barh": "broken-barh",
    "PolyCollection|Axes.fill_betweenx": "fill-betweenx",
    "PolyCollection|Axes.hexbin": "hexbin",
    "PolyCollection|Axes.violinplot": "violin",
    "Polygon|Axes.fill": "fill-polygon",
    "Polygon|Axes.hist": "step-histogram",
    "QuadContourSet|Axes.contour": "contour",
    "QuadMesh|Axes.pcolormesh": "pcolormesh",
    "Quiver|Axes.quiver": "quiver",
    "SecondaryAxis|Axes.secondary_yaxis": "secondary-axis",
    "Table|None": "table",
}


@pytest.mark.parametrize(("census_type", "case_id"), sorted(_CENSUS_WITNESSES.items()))
def test_every_census_type_outside_the_set_has_a_blocking_witness(
    census_type: str, case_id: str
) -> None:
    assert _ALL[case_id]["expect"] in _OUTSIDE
    assert census_type in _types(case_id)


def _kinds(case_id: str) -> set[str]:
    """The chart kinds a case draws, read off the reader's description alone."""
    kinds: set[str] = set()
    figures = _description(case_id)["figures"]
    panels = [axes for figure in figures for axes in figure["axes"] if axes["colorbar_of"] is None]
    if len(panels) > 1:
        kinds.add("multi-panel")
    for axes in panels:
        origins = [artist["origin"] for artist in axes["artists"]]
        bar_containers = [c for c in axes["containers"] if c["hist"] is None]
        kinds |= {
            kind
            for origin, kind in (
                ("Axes.plot", "line"),
                ("Axes.scatter", "scatter"),
                ("Axes.hist", "histogram"),
                ("Axes.pie", "pie"),
                ("Axes.fill_between", "area"),
                ("stackplot", "area"),
            )
            if origin in origins
        }
        if bar_containers:
            kinds.add("bar")
        kinds |= _bar_layouts(axes, bar_containers)
    return kinds


def _bar_layouts(axes: dict[str, Any], containers: list[dict[str, Any]]) -> set[str]:
    """`stacked`: a bar resting where another container's bar ends; `grouped`: bars of two
    containers side by side within one category slot."""
    rects = [
        (index, axes["artists"][member]["geometry"])
        for index, container in enumerate(containers)
        for member in container["members"]
    ]
    found: set[str] = set()
    for first, a in rects:
        for second, b in rects:
            if first == second:
                continue
            same_slot = a["x"] == b["x"] and a["width"] == b["width"]
            if same_slot and a["y"] != 0 and a["y"] == b["y"] + b["height"]:
                found.add("stacked-bar")
            if not same_slot and abs(a["x"] - b["x"]) < 1 and a["y"] == b["y"] == 0:
                found.add("grouped-bar")
    return found


_KINDS = (
    "bar",
    "line",
    "scatter",
    "histogram",
    "stacked-bar",
    "grouped-bar",
    "pie",
    "area",
    "multi-panel",
)


# Parts-stage reasons stop a figure before any panel's rules run, so a case blocked there exercises
# no rule of the kinds it draws (reviewer-5: a judge skipping every panel after the first passed
# the corpus while the only multi-panel misleading cases were twin and overlapping axes).
_PARTS = frozenset(
    {"raster_image", "axes_not_judged", "axes_twin", "axes_overlap", "artist_not_judged", "no_data"}
)


@pytest.mark.parametrize("kind", _KINDS)
def test_every_chart_kind_passes_honest_and_blocks_misleading(kind: str) -> None:
    honest = [case_id for case_id, case in _ALL.items() if case["expect"] == "pass"]
    misleading = [
        case_id
        for case_id, case in _ALL.items()
        if case["expect"] in _RULE_REASONS and case["expect"] not in _PARTS
    ]
    assert any(kind in _kinds(case_id) for case_id in honest), kind
    assert any(kind in _kinds(case_id) for case_id in misleading), kind


@pytest.mark.parametrize(
    ("case_id", "expect"),
    [
        ("other-plotting-library", "module_not_available"),  # a figure no matplotlib drew
        ("image-not-figure", "no_figure"),
        ("made-up-values", "value_not_found"),  # in neither the CSV nor the request
        ("computed-curve", "value_not_found"),
        ("typed-range", "pass"),
        ("typed-range-ja", "pass"),
    ],
)
def test_the_named_acceptance_cases_exist(case_id: str, expect: str) -> None:
    assert _ALL[case_id]["expect"] == expect
