# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.2 O3/O4: dataset values bind to forward artist geometry, categories, and ticks.

Contract: `.agent/archive/contracts/m10u2.md` § A1 R1-R3. The rows come from real core verdicts,
including the committed CSV; artist records are constructed separately from the wire contract.
"""

import copy
import importlib
import math
from typing import Any, cast

import pytest

from observe_support import (
    Binding,
    committed_sales_verdict,
    dataset_verdict,
    observation_for,
    stdout_for,
)
from verifier.pysrc import Verified, verify_python_source
from verifier.pysrc.spec import DatasetTarget


def _matches(verdict: Verified, observed: dict[str, Any]) -> bool:
    module = importlib.import_module("webui.paste_in.observe")
    parsed = module.parse_observation(stdout_for(observed))
    assert parsed is not None
    return bool(module.observation_matches(verdict, parsed))


def _artist(verdict: Verified, observed: dict[str, Any]) -> list[list[str]]:
    return cast(
        list[list[str]],
        observed[
            {"line": "lines", "scatter": "collections", "bar": "containers", "barh": "containers"}[
                verdict.spec.mark
            ]
        ][0],
    )


def _position_axis(verdict: Verified, observed: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], observed["yaxis" if verdict.spec.mark == "barh" else "xaxis"])


_CASES = [
    pytest.param("line", "categorical", False, False, id="line-category"),
    pytest.param("line", "numeric", False, False, id="line-number"),
    pytest.param("scatter", "numeric", False, False, id="scatter-number"),
    pytest.param("bar", "categorical", False, False, id="bar-category"),
    pytest.param("bar", "numeric", False, False, id="bar-number"),
    pytest.param("bar", "accessor", False, False, id="bar-accessor-category"),
    pytest.param("bar", "accessor", True, False, id="bar-accessor-number"),
    pytest.param("barh", "categorical", False, False, id="barh-category"),
    pytest.param("barh", "numeric", False, False, id="barh-number"),
    pytest.param("barh", "accessor", False, False, id="barh-accessor-category"),
    pytest.param("barh", "accessor", True, False, id="barh-accessor-number"),
    pytest.param("bar", "categorical", False, True, id="bar-grouped-category"),
    pytest.param("barh", "numeric", False, True, id="barh-grouped-number"),
]


@pytest.mark.parametrize("mark,binding,numeric_keys,grouped", _CASES)
def test_o3_values_release_for_every_admitted_artist_binding(
    mark: str, binding: Binding, *, numeric_keys: bool, grouped: bool
) -> None:
    """O3: every mark and each direct/accessor bar binding releases its recomputed values."""
    verdict = dataset_verdict(cast(Any, mark), binding, numeric_keys=numeric_keys, grouped=grouped)
    assert _matches(verdict, observation_for(verdict, binding))


@pytest.mark.parametrize(
    "mark,binding",
    [
        ("line", "categorical"),
        ("scatter", "numeric"),
        ("bar", "categorical"),
        ("barh", "categorical"),
        ("bar", "accessor"),
        ("barh", "accessor"),
    ],
)
def test_o3_committed_csv_values_release_for_each_mark_and_accessor(
    mark: str, binding: Binding
) -> None:
    """O3: `data/sales.csv` bytes feed the verifier, not a table copied into the test."""
    verdict = committed_sales_verdict(cast(Any, mark), accessor=binding == "accessor")
    assert _matches(verdict, observation_for(verdict, binding))


@pytest.mark.parametrize("mark", ["line", "scatter", "bar", "barh"])
def test_o3_dropped_point_withholds(mark: str) -> None:
    """O3: dropping one point violates exact series length."""
    verdict = dataset_verdict(cast(Any, mark), "numeric")
    observed = observation_for(verdict)
    _artist(verdict, observed).pop()
    assert not _matches(verdict, observed)


@pytest.mark.parametrize("mark", ["line", "scatter", "bar", "barh"])
def test_o3_swapped_point_order_withholds(mark: str) -> None:
    """O3: the same points permuted are not the submitted order."""
    verdict = dataset_verdict(cast(Any, mark), "numeric")
    observed = observation_for(verdict)
    points = _artist(verdict, observed)
    points[0], points[1] = points[1], points[0]
    assert not _matches(verdict, observed)


@pytest.mark.parametrize(
    "mark,binding",
    [
        ("line", "numeric"),
        ("line", "categorical"),
        ("scatter", "numeric"),
        ("bar", "numeric"),
        ("bar", "categorical"),
        ("barh", "numeric"),
        ("barh", "categorical"),
    ],
)
def test_o3_one_changed_magnitude_withholds(mark: str, binding: Binding) -> None:
    """O3: one finite 1-ulp y error blocks line, scatter, vertical and horizontal bars."""
    verdict = dataset_verdict(cast(Any, mark), binding)
    observed = observation_for(verdict, binding)
    point = _artist(verdict, observed)[0]
    magnitude = 2 if mark == "barh" else 3 if mark == "bar" else 1
    point[magnitude] = math.nextafter(float.fromhex(point[magnitude]), math.inf).hex()
    assert not _matches(verdict, observed)


@pytest.mark.parametrize("mark", ["line", "scatter", "bar", "barh"])
def test_o3_numeric_positions_must_equal_the_verifier_table(mark: str) -> None:
    """O3: one numeric x rounded by one ulp no longer binds the original table."""
    verdict = dataset_verdict(cast(Any, mark), "numeric")
    observed = observation_for(verdict)
    point = _artist(verdict, observed)[0]
    edge_or_x = 1 if mark == "barh" else 0
    point[edge_or_x] = math.nextafter(float.fromhex(point[edge_or_x]), math.inf).hex()
    assert not _matches(verdict, observed)


@pytest.mark.parametrize("mark", ["line", "bar", "barh"])
@pytest.mark.parametrize("field", ["key", "position"])
def test_o3_categorical_direct_artist_binds_through_units(mark: str, field: str) -> None:
    """O3: the observed x/y axis's category→position mapping names the table key."""
    verdict = dataset_verdict(cast(Any, mark), "categorical")
    observed = observation_for(verdict, "categorical")
    units = _position_axis(verdict, observed)["units"]
    # ulp(0.4) = the smallest position shift the forward bar edge `p - 0.8 / 2` resolves (R3);
    # a subnormal shift draws the identical edge.
    units[0][0 if field == "key" else 1] = "unrelated" if field == "key" else math.ulp(0.4).hex()
    assert not _matches(verdict, observed)


@pytest.mark.parametrize("mark", ["bar", "barh"])
@pytest.mark.parametrize("fault", ["label", "position", "missing"])
def test_o3_accessor_category_requires_tick_identity(mark: str, fault: str) -> None:
    """O3: a category label binds at the patch's FORWARD position, not at a guessed ordinal."""
    verdict = dataset_verdict(cast(Any, mark), "accessor")
    observed = observation_for(verdict, "accessor")
    ticks = _position_axis(verdict, observed)["ticks"]
    if fault == "label":
        ticks[0][1] = "unrelated"
    elif fault == "position":
        ticks[0][0] = math.nextafter(0.0, math.inf).hex()
    else:
        ticks.pop(0)
    assert not _matches(verdict, observed)


@pytest.mark.parametrize("mark", ["bar", "barh"])
def test_o3_accessor_numeric_key_parses_tick_text_instead_of_matching_ordinal(mark: str) -> None:
    """O3: numeric accessor keys 10/20 release at patch positions 0/1 with numeric tick text."""
    verdict = dataset_verdict(cast(Any, mark), "accessor", numeric_keys=True)
    observed = observation_for(verdict, "accessor")
    ticks = _position_axis(verdict, observed)["ticks"]
    assert ticks[0][0] == (0.0).hex()
    assert verdict.table.x[0] == 10.0
    ticks[0][1] = "1e1"
    assert _matches(verdict, observed)
    for wrong in ("11", "inf", "unrelated"):
        altered = copy.deepcopy(observed)
        _position_axis(verdict, altered)["ticks"][0][1] = wrong
        assert not _matches(verdict, altered), wrong


@pytest.mark.parametrize("mark", ["bar", "barh"])
def test_o4_decimal_forward_edge_releases_when_inverse_center_disagrees(mark: str) -> None:
    """O4: `0.000001 - span/2` is faithful although `edge + span/2 != 0.000001`."""
    verdict = dataset_verdict(cast(Any, mark), "numeric")
    observed = observation_for(verdict)
    x = cast(float, verdict.table.x[0])
    assert x == 0.000001
    patch = _artist(verdict, observed)[0]
    edge_index, span_index = (1, 3) if mark == "barh" else (0, 2)
    edge, span = float.fromhex(patch[edge_index]), float.fromhex(patch[span_index])
    assert edge == x - span / 2
    assert edge + span / 2 != x  # The inverse-center test would block a correct plot.
    assert _matches(verdict, observed)


@pytest.mark.parametrize("mark", ["bar", "barh"])
@pytest.mark.parametrize("binding", ["categorical", "numeric", "accessor"])
@pytest.mark.parametrize("fault", ["base", "extent", "edge"])
def test_o4_forward_geometry_checks_baseline_extent_and_edge(
    mark: str, binding: Binding, fault: str
) -> None:
    """O4: perturb one geometric conjunct with the magnitudes and labels unchanged."""
    verdict = dataset_verdict(cast(Any, mark), binding)
    observed = observation_for(verdict, binding)
    patch = _artist(verdict, observed)[0]
    index = (
        (1 if mark == "bar" else 0)
        if fault == "base"
        else (2 if mark == "bar" else 3)
        if fault == "extent"
        else (0 if mark == "bar" else 1)
    )
    original = float.fromhex(patch[index])
    patch[index] = math.nextafter(original, math.inf).hex()
    assert not _matches(verdict, observed)


@pytest.mark.parametrize("mark", ["bar", "barh"])
def test_o4_direct_numeric_span_is_converted_at_first_key(mark: str) -> None:
    """O4: 0.4's converted span is one ulp above literal 0.8; nominal span must withhold."""
    path = "/mnt/uploads/decimal.csv"
    source = (
        "import pandas as pd\nimport matplotlib.pyplot as plt\n"
        f'df = pd.read_csv("{path}")\n'
        f'plt.{mark}(df["key"], df["value"])\nplt.show()\n'
    )
    verdict = verify_python_source(
        source,
        declared_target=DatasetTarget(path, b"key,value\n0.4,1.25\n0.6,2.5\n"),
    )
    assert isinstance(verdict, Verified)
    observed = observation_for(verdict)
    assert _matches(verdict, observed)
    patch = _artist(verdict, observed)[0]
    span_index = 3 if mark == "barh" else 2
    assert float.fromhex(patch[span_index]) != 0.8
    patch[span_index] = (0.8).hex()
    assert not _matches(verdict, observed)
