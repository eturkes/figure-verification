# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Observation-internal witnesses beyond the diff-blind contract suite."""

import json
import math
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from verifier.pysrc.spec import DatasetTarget
from verifier.pysrc.verify import Verified, verify_python_source
from webui.paste_in import observe

_FIXTURES = Path(__file__).parent / "fixtures/observe"
_NAMES = sorted(path.name for path in _FIXTURES.glob("*.json"))


def _case(name: str) -> tuple[Verified, observe.Observation, dict[str, object]]:
    data = cast("dict[str, object]", json.loads((_FIXTURES / name).read_text()))
    uploaded = cast("dict[str, str] | None", data["dataset"])
    target = (
        DatasetTarget(path=uploaded["path"], content=uploaded["content"].encode("utf-8"))
        if uploaded is not None
        else None
    )
    verdict = verify_python_source(cast("str", data["source"]), declared_target=target)
    observation = observe.parse_observation(
        observe.OBSERVATION_TAG + cast("str", data["observation"])
    )
    assert isinstance(verdict, Verified)
    assert observation is not None
    return verdict, observation, data


def test_fixture_roster_is_full_and_self_contained() -> None:
    assert len(_NAMES) == 52
    counts = {"dataset": 0, "formula": 0}
    for name in _NAMES:
        case = cast("dict[str, object]", json.loads((_FIXTURES / name).read_text()))
        assert set(case) == {"id", "arm", "mark", "source", "dataset", "observation"}
        assert case["id"] == name.removesuffix(".json")
        arm = cast("str", case["arm"])
        counts[arm] += 1
        assert (case["dataset"] is None) == (arm == "formula")
    assert counts == {"dataset": 32, "formula": 20}


@pytest.mark.parametrize("name", _NAMES)
def test_recorded_artist_arrays_match_live_recomputation(name: str) -> None:
    verdict, observation, _ = _case(name)
    assert observe.observation_matches(verdict, observation)


def test_point_arithmetic_does_not_falsely_block_nested_sine() -> None:
    source = (
        "import numpy as np\nimport matplotlib.pyplot as plt\n"
        "x = np.linspace(0.1, 2.1, num=41)\n"
        "y = np.sin(2*x)\nplt.plot(x, y)\nplt.show()\n"
    )
    verdict = verify_python_source(source)
    assert isinstance(verdict, Verified)
    _, recorded, _ = _case("formula-sin-plot.json")
    assert all(isinstance(x, float) for x in verdict.table.x)
    numeric_x = cast("tuple[float, ...]", verdict.table.x)
    series = tuple(zip(numeric_x, verdict.table.y, strict=True))
    observed = replace(recorded, lines=(series,))
    assert observe.observation_matches(verdict, observed)


def test_libm_result_cannot_feed_power_then_exponential_without_range_proof() -> None:
    source = (
        "import numpy as np\nimport matplotlib.pyplot as plt\n"
        "x = np.linspace(0.1, 2.1, num=41)\n"
        "y = np.exp(-x**2)\nplt.plot(x, y)\nplt.show()\n"
    )
    verdict = verify_python_source(source)
    assert isinstance(verdict, Verified)
    _, recorded, _ = _case("formula-sin-plot.json")
    assert all(isinstance(x, float) for x in verdict.table.x)
    numeric_x = cast("tuple[float, ...]", verdict.table.x)
    observed = replace(recorded, lines=(tuple(zip(numeric_x, verdict.table.y, strict=True)),))
    assert not observe.observation_matches(verdict, observed)


def test_recorded_decimal_bar_uses_forward_edge_not_inverse_center() -> None:
    verdict, observed, _ = _case("synthetic-bar-dec.json")
    patches = observed.containers[0]
    assert any(
        (patch[0] + patch[2] / 2) != key
        for patch, key in zip(patches, verdict.table.x, strict=True)
    )
    assert observe.observation_matches(verdict, observed)


def test_one_dataset_y_bit_mismatch_is_withheld() -> None:
    verdict, observed, _ = _case("synthetic-plot-num.json")
    first = observed.lines[0][0]
    moved = (first[0], math.nextafter(first[1], math.inf))
    changed = replace(observed, lines=((moved, *observed.lines[0][1:]),))
    assert not observe.observation_matches(verdict, changed)


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda value: value.replace('"axes":1', '"axes":true', 1),
        lambda value: value.replace('"axes":1', '"axes":1,"axes":1', 1),
        lambda value: value.replace('"patches":0', '"patches":NaN', 1),
        lambda value: value.replace('"images":0', '"images":-Infinity', 1),
        lambda value: value.replace('"lines":[]', '"lines":{}', 1),
    ],
)
def test_parser_fails_closed_on_wrong_types_and_duplicate_keys(
    corrupt: Callable[[str], str],
) -> None:
    _, _, data = _case("synthetic-bar-num.json")
    payload = cast("str", data["observation"])
    broken = corrupt(payload)
    assert broken != payload
    assert observe.parse_observation(observe.OBSERVATION_TAG + broken) is None


def test_line_size_limit_is_utf8_bytes_not_codepoints(monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, data = _case("synthetic-bar-num.json")
    line = observe.OBSERVATION_TAG + cast("str", data["observation"])
    with monkeypatch.context() as patch:
        patch.setattr(observe, "OBSERVATION_MAX_BYTES", len(line.encode("utf-8")))
        assert observe.parse_observation(line) is not None
        patch.setattr(observe, "OBSERVATION_MAX_BYTES", len(line.encode("utf-8")) - 1)
        assert observe.parse_observation(line) is None


def test_duplicate_tag_never_yields_an_observation() -> None:
    _, _, data = _case("synthetic-bar-num.json")
    line = observe.OBSERVATION_TAG + cast("str", data["observation"])
    assert observe.parse_observation(line + "\n" + line) is None
