# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M19.2 decoder: the description admits exactly the reader's shape (`m19u2.md` P6).

Round trips run the real reader; refusals mutate one field of a real description at each nesting
level, so every closed key set and exact type check is reached through `parse_description`.
"""

import json
from collections.abc import Callable
from typing import Any, cast

import pytest

from verifier.figure import reader
from verifier.figure.description import (
    MAX_BYTES,
    TAG,
    Description,
    NoGeometry,
    TextGeometry,
    parse_description,
)

_PLT = "import matplotlib.pyplot as plt\n"
# One program whose description holds every geometry kind, legend, container, pie and hist record.
_EVERYTHING = (
    _PLT
    + "fig, (a, b, c) = plt.subplots(1, 3)\n"
    + "a.plot([1, 2], [3, 4], label='l')\n"
    + "a.bar([1, 2], [3, 4], label='b')\n"
    + "a.scatter([1], [2], c=[3])\n"
    + "a.fill_between([1, 2], [1, 2])\n"
    + "a.fill([1, 2, 2], [1, 1, 2])\n"
    + "a.text(1, 1, 't')\n"
    + "a.legend()\n"
    + "b.pie([1, 2], labels=['x', 'y'])\n"
    + "c.hist([1, 2, 2], bins=2)\n"
    + "c.add_artist(plt.Circle((0, 0), 1))\n"
)


def _raw(source: str = _EVERYTHING) -> dict[str, Any]:
    line = reader.run(source).splitlines()[0]
    value: dict[str, Any] = json.loads(line[len(TAG) :])
    return value


def _parse(value: object) -> Description | None:
    return parse_description(TAG + json.dumps(value, ensure_ascii=False) + "\n")


def test_p6_round_trip_reaches_every_geometry() -> None:
    described = _parse(_raw())
    assert described is not None
    kinds = {
        type(artist.geometry).__name__
        for figure in described.figures
        for axes in figure.axes
        for artist in axes.artists
    }
    assert kinds == {
        "LineGeometry",
        "RectGeometry",
        "ScatterGeometry",
        "BandGeometry",
        "PolygonGeometry",
        "TextGeometry",
        "WedgeGeometry",
        "NoGeometry",
    }
    first, second, third = described.figures[0].axes
    assert first.legend is not None and len(first.legend.entries) == 2
    assert [second.artists[cast("int", i)].geometry for i in second.pies[0].texts] == [
        TextGeometry("x"),
        TextGeometry("y"),
    ]
    assert third.containers[0].hist is not None
    assert isinstance(third.artists[-1].geometry, NoGeometry)


def test_p6_errors_and_non_finite_strings_decode() -> None:
    described = _parse(_raw(_PLT + "plt.plot([1, float('nan')])\nplt.show()\n1 / 0\n"))
    assert described is not None and described.error is not None
    assert described.error.line == 4


@pytest.mark.parametrize(
    "text",
    [
        "",
        "no tag here\n",
        f"{TAG}{{}}\n",
        f"{TAG}not json\n",
        f"{TAG}[]\n",
    ],
    ids=["empty", "untagged", "empty-object", "not-json", "not-object"],
)
def test_p6_line_shape_refusals(text: str) -> None:
    assert parse_description(text) is None


def test_p6_two_valid_lines_refuse() -> None:
    line = reader.run(_PLT + "plt.plot([1])\n").splitlines()[0]
    assert parse_description(line + "\n") is not None
    assert parse_description(f"{line}\n{line}\n") is None


def test_p6_oversize_refuses() -> None:
    raw = _raw(_PLT + "plt.plot([1])\n")
    raw["figures"][0]["texts"] = [{"text": "x" * MAX_BYTES, "site": None}]
    assert _parse(raw) is None


def test_p6_constant_and_duplicate_tokens_refuse() -> None:
    good = json.dumps(_raw(_PLT + "plt.plot([1])\n"))
    assert parse_description(TAG + good) is not None
    assert parse_description(TAG + good.replace('"offset": 0.0', '"offset": NaN', 1)) is None
    assert parse_description(TAG + good.replace('"offset": 0.0', '"offset": "nan"', 1)) is not None
    assert parse_description(TAG + good.replace('"glyphs": 0', '"glyphs": 0, "glyphs": 0')) is None


def test_p6_version_must_match() -> None:
    raw = _raw(_PLT + "plt.plot([1])\n")
    raw["version"] = "figure-description/0"
    assert _parse(raw) is None


type _Path = tuple[str | int, ...]


def _at(value: Any, path: _Path) -> Any:
    for step in path:
        value = value[step]
    return value


def _edit(path: _Path, change: Callable[[Any], Any]) -> dict[str, Any]:
    raw = _raw()
    parent = _at(raw, path[:-1])
    parent[path[-1]] = change(parent[path[-1]])
    return raw


_AXES: _Path = ("figures", 0, "axes", 0)
_ARTIST = (*_AXES, "artists", 0)
_GEOMETRY = (*_ARTIST, "geometry")


def _extra(value: Any) -> Any:
    return {**value, "extra": 1}


def _drop_first(value: Any) -> Any:
    return dict(list(value.items())[1:])


@pytest.mark.parametrize(
    ("path", "change"),
    [
        pytest.param(("error",), lambda _: {"kind": "x", "name": "y"}, id="error-keys"),
        pytest.param(("too_large",), lambda _: 0, id="too-large-int"),
        pytest.param(("glyphs",), lambda _: True, id="glyphs-bool"),
        pytest.param(("figures",), lambda _: {}, id="figures-object"),
        pytest.param(("figures", 0), _extra, id="figure-extra"),
        pytest.param(("figures", 0, "titles"), lambda _: [None, None], id="titles-two"),
        pytest.param(("figures", 0, "texts"), lambda _: [{"text": 1, "site": None}], id="text-int"),
        pytest.param(
            ("figures", 0, "others"),
            lambda _: [{"cls": "X", "origin": None, "site": "1"}],
            id="part-site-text",
        ),
        pytest.param(_AXES, _drop_first, id="axes-missing-key"),
        pytest.param((*_AXES, "position"), lambda _: [0.0, 0.0, 1.0], id="position-three"),
        pytest.param((*_AXES, "colorbar_of"), lambda _: [0], id="colorbar-one"),
        pytest.param((*_AXES, "shared_x"), lambda _: [0.0], id="shared-float"),
        pytest.param((*_AXES, "calls"), lambda _: [["xlim", 1]], id="calls-list"),
        pytest.param((*_AXES, "calls"), lambda _: {"xlim": "1"}, id="calls-text"),
        pytest.param((*_AXES, "x"), _extra, id="axis-extra"),
        pytest.param((*_AXES, "x", "view"), lambda _: [0, 1], id="view-int"),
        pytest.param((*_AXES, "x", "categories"), lambda _: [["a"]], id="category-one"),
        pytest.param((*_AXES, "x", "ticks"), lambda _: [[0.0]], id="tick-one"),
        pytest.param((*_AXES, "x", "dates"), lambda _: [[0.0]], id="date-one"),
        pytest.param((*_AXES, "x", "order"), lambda _: 0.0, id="order-float"),
        pytest.param(_ARTIST, _extra, id="artist-extra"),
        pytest.param((*_ARTIST, "visible"), lambda _: 1, id="visible-int"),
        pytest.param((*_ARTIST, "alpha"), lambda _: 1, id="alpha-int"),
        pytest.param(_GEOMETRY, lambda _: {"kind": "circle"}, id="geometry-unknown"),
        pytest.param(_GEOMETRY, lambda _: {"x": []}, id="geometry-no-kind"),
        pytest.param(_GEOMETRY, lambda value: {**value, "y": value["y"][:1]}, id="line-y-short"),
        pytest.param((*_GEOMETRY, "color"), lambda _: [0.0, 0.0, 0.0], id="color-three"),
        pytest.param((*_AXES, "artists", 1, "geometry"), _extra, id="rect-extra"),
        pytest.param(
            (*_AXES, "artists", 3, "geometry", "offsets"),
            lambda _: [[1.0]],
            id="scatter-offset-one",
        ),
        pytest.param((*_AXES, "artists", 3, "geometry"), _extra, id="scatter-extra"),
        pytest.param(
            (*_AXES, "artists", 4, "geometry", "band", "y1"), lambda _: [], id="band-y1-short"
        ),
        pytest.param((*_AXES, "artists", 4, "geometry"), _extra, id="band-extra"),
        pytest.param((*_AXES, "artists", 5, "geometry"), _extra, id="polygon-extra"),
        pytest.param((*_AXES, "artists", 6, "geometry"), _extra, id="text-extra"),
        pytest.param((*_AXES, "containers", 0), _extra, id="container-extra"),
        pytest.param((*_AXES, "legend", "entries", 0), _extra, id="entry-extra"),
        pytest.param(
            (*_AXES, "legend", "entries", 0, "elements_of"), lambda _: [0], id="elements-one"
        ),
        pytest.param(("figures", 0, "axes", 1, "pies", 0), _extra, id="pie-extra"),
        pytest.param(("figures", 0, "axes", 1, "artists", 0, "geometry"), _extra, id="wedge-extra"),
        pytest.param(("figures", 0, "axes", 2, "containers", 0, "hist"), _extra, id="hist-extra"),
        pytest.param(("figures", 0, "axes", 2, "artists", 2, "geometry"), _extra, id="none-extra"),
    ],
)
def test_p6_every_level_refuses_a_wrong_shape(path: _Path, change: Callable[[Any], Any]) -> None:
    assert _parse(_raw()) is not None
    assert _parse(_edit(path, change)) is None


def test_p6_deep_nesting_refuses() -> None:
    nested: str = "[" * 100_000 + "]" * 100_000
    assert parse_description(f"{TAG}{nested}\n") is None


def test_f9_numeric_overflow_is_no_number() -> None:
    line = reader.run(_PLT + "plt.plot([1])\n").splitlines()[0]
    assert '"offset":0.0' in line
    assert parse_description(line.replace('"offset":0.0', '"offset":1e999', 1)) is None


@pytest.mark.parametrize("field", ["error.kind", "axis.kind", "artist.transform", "orientation"])
def test_f10_closed_word_fields_refuse_other_words(field: str) -> None:
    raw = _raw()
    if field == "error.kind":
        raw["error"] = {"kind": "not-declared", "name": "X", "line": 1}
    elif field == "axis.kind":
        raw["figures"][0]["axes"][0]["x"]["kind"] = "not-declared"
    elif field == "artist.transform":
        raw["figures"][0]["axes"][0]["artists"][0]["transform"] = "not-declared"
    else:
        raw["figures"][0]["axes"][0]["containers"][0]["orientation"] = "diagonal"
    assert _parse(raw) is None
