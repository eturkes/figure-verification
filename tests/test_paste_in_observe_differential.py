# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Independent observation decision versus the paste-in reader over real core verdicts."""

from __future__ import annotations

import importlib
import json
import math
from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass, replace
from fractions import Fraction
from pathlib import Path
from types import ModuleType
from typing import NoReturn, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.strategies import DrawFn

from oracle_observe import oracle_interval, oracle_matches, oracle_parse
from verifier.pysrc import spec
from verifier.pysrc.table import PlottedTable
from verifier.pysrc.verify import Verified, verify_python_source

_ROOT = Path(__file__).resolve().parents[1]
_TAG = "FIGURE_VERIFICATION_OBSERVATION:"
_SALES = "/mnt/uploads/sales.csv"
_DATA = f"import pandas as pd\nimport matplotlib.pyplot as plt\nframe = pd.read_csv('{_SALES}')\n"
_FORMULA = "import numpy as np\nimport matplotlib.pyplot as plt\n"


@dataclass(frozen=True, slots=True)
class Case:
    name: str
    source: str
    dataset: str | None
    mode: str


def _dataset_case(mark: str, mode: str) -> Case:
    if mark == "line":
        body = 'reduced = frame.groupby("region")["revenue"].sum()\n'
        plot = "plt.plot(reduced.index, reduced.values)\n"
        mode = "categorical"
    elif mark == "scatter":
        body = ""
        plot = 'plt.scatter(frame["orders"], frame["revenue"])\n'
        mode = "numeric"
    else:
        key = "region" if mode == "categorical" else "orders"
        body = f'reduced = frame.groupby("{key}")["revenue"].sum()\n'
        plot = (
            f"reduced.plot(kind='{mark}')\n"
            if mode == "accessor"
            else f"plt.{mark}(reduced.index, reduced.values)\n"
        )
    return Case(f"{mark}-{mode}", _DATA + body + plot + "plt.show()\n", _SALES, mode)


def _formula_case(expression: str, *, mark: str = "line") -> Case:
    source = (
        _FORMULA
        + "x = np.linspace(0.1, 1.1, num=6)\n"
        + f"plt.{'plot' if mark == 'line' else 'scatter'}(x, {expression})\n"
        + "plt.show()\n"
    )
    return Case(f"formula-{mark}-{expression}", source, None, "formula")


_CASES = {
    case.name: case
    for case in (
        *(
            _dataset_case(mark, mode)
            for mark in ("bar", "barh")
            for mode in ("categorical", "numeric", "accessor")
        ),
        _dataset_case("line", "categorical"),
        _dataset_case("scatter", "numeric"),
        _formula_case("np.sin(x)"),
        _formula_case("np.sin(2*x)"),
        _formula_case("np.sin(x) - np.cos(x)"),
        _formula_case("np.exp(-x**2)"),
        _formula_case("x ** 1.3", mark="scatter"),
    )
}
_RELEASING = (
    "bar-categorical",
    "bar-numeric",
    "bar-accessor",
    "barh-categorical",
    "barh-numeric",
    "barh-accessor",
    "formula-line-np.sin(2*x)",
    "formula-line-np.sin(x) - np.cos(x)",
)
_PERTURBATIONS = (
    "none",
    "count",
    "order",
    "x",
    "y",
    "edge",
    "extent",
    "base",
    "key",
    "tick",
    "line-extra",
    "collection-extra",
    "container-extra",
    "artist-missing",
    "axes-two",
    "formula-outside",
    "formula-inside",
    "bad-shape",
    "double-tag",
    "wrong-hex",
)


def _verified(case: Case) -> Verified:
    target = None
    if case.dataset is not None:
        target = spec.DatasetTarget(case.dataset, (_ROOT / "data/sales.csv").read_bytes())
    result = verify_python_source(case.source, declared_target=target)
    assert isinstance(result, Verified), (case.name, result)
    return result


def _hex(value: float) -> str:
    return float(value).hex()


def _axis() -> dict[str, object]:
    return {"units": None, "ticks": []}


def _observed(verified: Verified, mode: str) -> dict[str, object]:
    table, mark = verified.table, verified.spec.mark
    result: dict[str, object] = {
        "axes": 1,
        "lines": [],
        "collections": [],
        "containers": [],
        "patches": 0,
        "images": 0,
        "texts": 0,
        "xaxis": _axis(),
        "yaxis": _axis(),
    }
    position_axis = cast("dict[str, object]", result["yaxis" if mark == "barh" else "xaxis"])
    units: list[list[str]] | None = None
    if mode == "categorical":
        units = [[cast(str, key), _hex(float(i))] for i, key in enumerate(table.x)]
        position_axis["units"] = units
    if mode == "accessor":
        position_axis["ticks"] = [[_hex(float(i)), str(key)] for i, key in enumerate(table.x)]
    positions = [
        float(index)
        if mode == "accessor"
        else float(index)
        if units is not None
        else cast(float, key)
        for index, key in enumerate(table.x)
    ]
    if mark in {"line", "scatter"}:
        points = [[_hex(x), _hex(y)] for x, y in zip(positions, table.y, strict=True)]
        cast("list[object]", result["lines" if mark == "line" else "collections"]).append(points)
    else:
        span = (
            0.5
            if mode == "accessor"
            else 0.8
            if mode == "categorical"
            else (positions[0] + 0.8) - positions[0]
        )
        boxes = [
            [_hex(position - span / 2), _hex(0.0), _hex(span), _hex(y)]
            if mark == "bar"
            else [_hex(0.0), _hex(position - span / 2), _hex(y), _hex(span)]
            for position, y in zip(positions, table.y, strict=True)
        ]
        cast("list[object]", result["containers"]).append(boxes)
    return result


def _wire(payload: dict[str, object]) -> str:
    return (
        _TAG + json.dumps(payload, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n"
    )


def _artist(payload: dict[str, object], mark: str) -> list[list[str]]:
    field = "lines" if mark == "line" else "collections" if mark == "scatter" else "containers"
    entries = cast("list[list[list[str]]]", payload[field])
    return entries[0]


def _shift(text: str, direction: int, steps: int) -> str:
    value = float.fromhex(text)
    for _ in range(steps):
        value = math.nextafter(value, math.copysign(math.inf, direction))
    return _hex(value)


def _perturb(  # noqa: PLR0912, PLR0915
    verified: Verified, base: dict[str, object], kind: str, *, direction: int = 1, steps: int = 4
) -> str:
    raw = deepcopy(base)
    mark = verified.spec.mark
    position_axis = cast("dict[str, object]", raw["yaxis" if mark == "barh" else "xaxis"])
    if kind == "none":
        return _wire(raw)
    if kind == "double-tag":
        return _wire(raw) + _wire(raw)
    if kind == "bad-shape":
        raw["axes"] = True
        return _wire(raw)
    if kind == "wrong-hex":
        _artist(raw, mark)[0][0] = "NaN"
        return _wire(raw)
    if kind == "axes-two":
        raw["axes"] = 2
    elif kind in {"line-extra", "collection-extra", "container-extra"}:
        field = {
            "line-extra": "lines",
            "collection-extra": "collections",
            "container-extra": "containers",
        }[kind]
        cast("list[object]", raw[field]).append([])
    elif kind == "artist-missing":
        field = "lines" if mark == "line" else "collections" if mark == "scatter" else "containers"
        cast("list[object]", raw[field]).clear()
    elif kind == "count":
        _artist(raw, mark).pop()
    elif kind == "order":
        _artist(raw, mark).reverse()
    elif kind in {"x", "y", "edge", "extent", "base"}:
        point = _artist(raw, mark)[0]
        offset = (
            {"x": 0, "y": 1}.get(kind)
            if mark in {"line", "scatter"}
            else {
                "x": 0 if mark == "bar" else 1,
                "y": 3 if mark == "bar" else 2,
                "edge": 0 if mark == "bar" else 1,
                "extent": 2 if mark == "bar" else 3,
                "base": 1 if mark == "bar" else 0,
            }.get(kind)
        )
        if offset is None:
            raw["axes"] = 2
        else:
            point[offset] = _shift(point[offset], direction, steps)
    elif kind == "key":
        units = position_axis["units"]
        if units is None:
            raw["axes"] = 2
        else:
            cast("list[list[str]]", units)[0][0] += "-changed"
    elif kind == "tick":
        ticks = cast("list[list[str]]", position_axis["ticks"])
        if not ticks:
            raw["axes"] = 2
        else:
            ticks[0][1] += "-changed"
    elif kind in {"formula-outside", "formula-inside"}:
        if not isinstance(verified.spec, spec.FormulaPlot):
            raw["axes"] = 2
        else:
            interval = oracle_interval(verified.spec.y, cast(float, verified.table.x[0]))
            if interval is None:
                raw["axes"] = 2
            else:
                new_y = (
                    math.nextafter(interval[1], math.inf)
                    if kind == "formula-outside"
                    else interval[1]
                )
                _artist(raw, mark)[0][1] = _hex(new_y)
    else:
        raise ValueError(kind)
    return _wire(raw)


def _production() -> ModuleType:
    module = importlib.import_module("webui.paste_in.observe")
    source = getattr(module, "__file__", None)
    assert source is not None and Path(source).resolve() == _ROOT / "webui/paste_in/observe.py"
    assert Path(verify_python_source.__code__.co_filename).resolve() == (
        _ROOT / "src/verifier/pysrc/verify.py"
    )
    return module


def _unmapped(label: str, value: object) -> NoReturn:
    message = f"unmapped observation {label}: {value!r}"
    raise TypeError(message)


def _record(value: object, keys: frozenset[str]) -> dict[str, object]:
    if isinstance(value, dict):
        if value.keys() != keys:
            _unmapped("fields", (set(value), keys))
        return cast("dict[str, object]", value)
    if not is_dataclass(value):
        _unmapped("type", type(value).__name__)
    names = frozenset(field.name for field in fields(value))
    if names != keys:
        _unmapped("fields", (names, keys))
    return {name: getattr(value, name) for name in keys}


def _canonical_artists(value: object, width: int) -> tuple[tuple[tuple[float, ...], ...], ...]:
    if not isinstance(value, (list, tuple)):
        _unmapped("artist list", value)
    decoded: list[tuple[tuple[float, ...], ...]] = []
    for artist in value:
        if not isinstance(artist, (list, tuple)):
            _unmapped("artist", artist)
        points: list[tuple[float, ...]] = []
        for point in artist:
            if not isinstance(point, (list, tuple)) or len(point) != width:
                _unmapped("point", point)
            if any(type(number) is not float for number in point):
                _unmapped("coordinates", point)
            points.append(tuple(point))
        decoded.append(tuple(points))
    return tuple(decoded)


def _canonical_axis(value: object) -> dict[str, object]:
    axis = _record(value, frozenset({"units", "ticks"}))
    units = axis["units"]
    if units is not None:
        if not isinstance(units, (list, tuple)):
            _unmapped("units", units)
        unit_pairs: list[tuple[str, float]] = []
        for item in units:
            if (
                not isinstance(item, (list, tuple))
                or len(item) != 2
                or type(item[0]) is not str
                or type(item[1]) is not float
            ):
                _unmapped("unit item", item)
            unit_pairs.append((item[0], item[1]))
        units = tuple(unit_pairs)
    ticks = axis["ticks"]
    if not isinstance(ticks, (list, tuple)):
        _unmapped("ticks", ticks)
    tick_pairs: list[tuple[float, str]] = []
    for item in ticks:
        if (
            not isinstance(item, (list, tuple))
            or len(item) != 2
            or type(item[0]) is not float
            or type(item[1]) is not str
        ):
            _unmapped("tick item", item)
        tick_pairs.append((item[0], item[1]))
    return {"units": units, "ticks": tuple(tick_pairs)}


def _canonical(value: object) -> dict[str, object]:
    """Translate only the contract's nine fields; an unknown production shape raises."""
    names = frozenset(
        {
            "axes",
            "lines",
            "collections",
            "containers",
            "patches",
            "images",
            "texts",
            "xaxis",
            "yaxis",
        }
    )
    record = _record(value, names)
    result: dict[str, object] = {}
    for name in ("axes", "patches", "images", "texts"):
        count = record[name]
        if type(count) is not int:
            _unmapped(name, count)
        result[name] = count
    for name, width in (("lines", 2), ("collections", 2), ("containers", 4)):
        result[name] = _canonical_artists(record[name], width)
    for name in ("xaxis", "yaxis"):
        result[name] = _canonical_axis(record[name])
    return result


def _agree(verified: Verified, stdout: str) -> bool:
    expected = oracle_parse(stdout)
    module = _production()
    parsed = module.parse_observation(stdout)
    if parsed is None:
        assert expected is None, f"parser rejected a valid observation: {stdout[:200]!r}"
        return False
    assert expected is not None, f"parser admitted a malformed observation: {stdout[:200]!r}"
    actual = _canonical(parsed)
    assert actual == expected, f"production={actual!r}; oracle={expected!r}"
    oracle = oracle_matches(verified, expected)
    production = module.observation_matches(verified, parsed)
    assert type(production) is bool
    assert production == oracle, (
        f"case={verified.spec.mark}, source={stdout[:240]!r}; "
        f"production={production!r}, oracle={oracle!r}"
    )
    return oracle


def _case_agrees(case: Case, kind: str, *, direction: int = 1, steps: int = 4) -> bool:
    verdict = _verified(case)
    return _agree(
        verdict,
        _perturb(verdict, _observed(verdict, case.mode), kind, direction=direction, steps=steps),
    )


@pytest.mark.parametrize("name", tuple(_CASES))
def test_oracle_real_verified_artists(name: str) -> None:
    """Every mark + three modes per bar: core verdict first, then independent geometry."""
    case = _CASES[name]
    verdict = _verified(case)
    parsed = oracle_parse(_wire(_observed(verdict, case.mode)))
    assert parsed is not None
    expect = "np.exp(-x**2)" not in name
    assert oracle_matches(verdict, parsed) is expect, name


@pytest.mark.parametrize("reason", ("bool-count", "extra-key", "wrong-hex", "non-finite"))
def test_oracle_hand_stated_wire_rejections(reason: str) -> None:
    case = _CASES["formula-line-np.sin(x)"]
    raw = _observed(_verified(case), case.mode)
    if reason == "bool-count":
        raw["axes"] = True
    elif reason == "extra-key":
        raw["extra"] = 1
    elif reason == "wrong-hex":
        _artist(raw, "line")[0][0] = "not-hex"
    else:
        _artist(raw, "line")[0][0] = "NaN"
    assert oracle_parse(_wire(raw)) is None, reason


def test_oracle_tag_cardinality_and_byte_limit() -> None:
    case = _CASES["bar-categorical"]
    line = _wire(_observed(_verified(case), case.mode))
    assert oracle_parse("prompt output\n" + line) is not None
    assert oracle_parse(line + line) is None
    assert oracle_parse(_TAG + "{" + " " * 16_777_216 + "}") is None


def test_oracle_interval_hand_stated_cases() -> None:
    """R4 keeps point arithmetic point, including sin(2*x), and fails closed on nested libm."""
    x = math.pi / 4
    variable = spec.Var()
    two = spec.Num(Fraction(2))
    sin_two = spec.Fn("sin", spec.Bin("mul", two, variable))
    sin = spec.Fn("sin", variable)
    cos = spec.Fn("cos", variable)
    cancel = spec.Bin("sub", sin, cos)
    pow_x = spec.Bin("pow", variable, spec.Num(Fraction(1.3)))
    exp_pow = spec.Fn("exp", spec.Neg(spec.Bin("pow", variable, two)))
    point = oracle_interval(spec.Bin("mul", two, variable), x)
    assert point == (2 * x, 2 * x)
    sin_band = oracle_interval(sin_two, x)
    assert sin_band is not None and sin_band[0] <= math.sin(2 * x) <= sin_band[1]
    assert oracle_interval(spec.Fn("sin", sin), x) is None
    width = oracle_interval(cancel, x)
    assert width is not None and width[0] < 0 < width[1]
    assert width[0] <= math.sin(x) - math.cos(x) <= width[1]
    assert math.nextafter(width[1], math.inf) > width[1]
    assert oracle_interval(pow_x, 0.5) is not None
    assert oracle_interval(exp_pow, 0.5) is None
    assert oracle_interval(spec.Bin("div", variable, spec.Num(Fraction(0))), x) is None


def test_oracle_signed_zero_equals_zero_but_neighbor_does_not() -> None:
    """R1 normalises signed zero only; one positive ulp remains distinguishable."""
    case = _CASES["line-categorical"]
    verdict = _verified(case)
    zero = replace(verdict, table=PlottedTable(verdict.table.x, (0.0, verdict.table.y[1])))
    raw = _observed(zero, case.mode)
    _artist(raw, "line")[0][1] = _hex(-0.0)
    parsed = oracle_parse(_wire(raw))
    assert parsed is not None and oracle_matches(zero, parsed)
    _artist(raw, "line")[0][1] = _hex(math.nextafter(0.0, math.inf))
    neighbor = oracle_parse(_wire(raw))
    assert neighbor is not None and not oracle_matches(zero, neighbor)


def test_oracle_forward_edge_decimal_and_accessor_key() -> None:
    case = _CASES["bar-numeric"]
    verdict = _verified(case)
    tiny = replace(verdict, table=PlottedTable((0.000001, 0.000002), (3.0, 4.0)))
    raw = _observed(tiny, "numeric")
    parsed = oracle_parse(_wire(raw))
    assert parsed is not None and oracle_matches(tiny, parsed)
    extent = (0.000001 + 0.8) - 0.000001
    first = _artist(raw, "bar")[0]
    assert float.fromhex(first[0]) + extent / 2 != 0.000001
    wrong = deepcopy(raw)
    _artist(wrong, "bar")[0][0] = _shift(first[0], 1, 1)
    changed = oracle_parse(_wire(wrong))
    assert changed is not None and not oracle_matches(tiny, changed)


@st.composite
def _drawn(draw: DrawFn) -> tuple[Case, str, int, int]:
    return (
        _CASES[draw(st.sampled_from(tuple(_CASES)))],
        draw(st.sampled_from(_PERTURBATIONS)),
        draw(st.sampled_from((-1, 1))),
        draw(st.sampled_from((1, 2, 4, 8))),
    )


@given(drawn=st.lists(_drawn(), min_size=12, max_size=12))
@settings(max_examples=64, deadline=None)
def test_differential_drawn_pairs(drawn: list[tuple[Case, str, int, int]]) -> None:
    """20 pairs per draw; eight independently releasing basis cases bind ≥25% of decisions."""
    results = [_case_agrees(_CASES[name], "none") for name in _RELEASING]
    results.extend(
        _case_agrees(case, kind, direction=direction, steps=steps)
        for case, kind, direction, steps in drawn
    )
    assert sum(results) >= 5, f"vacuous differential: {sum(results)}/20 released"


@pytest.mark.parametrize(
    ("name", "kind"),
    (
        ("bar-categorical", "key"),
        ("bar-numeric", "edge"),
        ("bar-accessor", "tick"),
        ("barh-categorical", "base"),
        ("barh-numeric", "extent"),
        ("barh-accessor", "tick"),
        ("line-categorical", "order"),
        ("scatter-numeric", "y"),
        ("formula-line-np.sin(x) - np.cos(x)", "formula-inside"),
        ("formula-line-np.exp(-x**2)", "none"),
        ("formula-scatter-x ** 1.3", "formula-outside"),
    ),
)
def test_differential_boundaries(name: str, kind: str) -> None:
    _case_agrees(_CASES[name], kind)


@pytest.mark.parametrize("kind", _PERTURBATIONS)
def test_differential_perturbation_inventory(kind: str) -> None:
    """Each generated fault class is guaranteed to reach the differential at least once."""
    name = (
        "bar-accessor"
        if kind == "tick"
        else "formula-line-np.sin(2*x)"
        if kind.startswith("formula-")
        else "bar-categorical"
    )
    _case_agrees(_CASES[name], kind)


def test_differential_closed_unmapped_mark() -> None:
    case = _CASES["bar-categorical"]
    verdict = _verified(case)
    assert isinstance(verdict.spec, spec.DatasetPlot)
    unknown = replace(verdict, spec=replace(verdict.spec, mark=cast("spec.DatasetMark", "unknown")))
    _agree(unknown, _wire(_observed(verdict, case.mode)))


@pytest.mark.parametrize("neighbor", (False, True))
def test_differential_signed_zero(*, neighbor: bool) -> None:
    case = _CASES["line-categorical"]
    verdict = _verified(case)
    zero = replace(verdict, table=PlottedTable(verdict.table.x, (0.0, verdict.table.y[1])))
    raw = _observed(zero, case.mode)
    _artist(raw, "line")[0][1] = _hex(math.nextafter(0.0, math.inf) if neighbor else -0.0)
    assert _agree(zero, _wire(raw)) is (not neighbor)


def test_differential_decimal_edge() -> None:
    case = _CASES["bar-numeric"]
    verdict = _verified(case)
    tiny = replace(verdict, table=PlottedTable((0.000001, 0.000002), (3.0, 4.0)))
    assert _agree(tiny, _wire(_observed(tiny, "numeric")))


def test_differential_fixture_replay() -> None:
    """All 52 self-contained committed observations, plus one perturbation per file."""
    paths = sorted((_ROOT / "tests/fixtures/observe").glob("*.json"))
    assert len(paths) == 52, f"fixture inventory drift: {len(paths)}/52"
    for index, path in enumerate(paths):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        assert set(fixture) == {"id", "arm", "mark", "source", "dataset", "observation"}
        dataset = fixture["dataset"]
        target = None
        if dataset is not None:
            assert set(dataset) == {"path", "content"}
            target = spec.DatasetTarget(dataset["path"], dataset["content"].encode("utf-8"))
        verdict = verify_python_source(fixture["source"], declared_target=target)
        assert isinstance(verdict, Verified), (path.name, verdict)
        assert verdict.spec.mark == fixture["mark"]
        observed = _TAG + fixture["observation"] + "\n"
        _agree(verdict, observed)
        payload = json.loads(fixture["observation"])
        assert set(payload) == {
            "axes",
            "lines",
            "collections",
            "containers",
            "patches",
            "images",
            "texts",
            "xaxis",
            "yaxis",
        }
        _agree(
            verdict,
            _perturb(verdict, payload, _PERTURBATIONS[index % (len(_PERTURBATIONS) - 1) + 1]),
        )
