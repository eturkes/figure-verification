# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.10 positional accessor-line reading; `.agent/archive/contracts/m10u10.md` predicates B1-B6.

Recorded fixtures exercise installed Pyodide output. Independent wire records isolate positional
binding from admission and vary sparse ticks, wrapped negative labels and binary64 neighbors.
"""

import json
import math
from copy import deepcopy
from dataclasses import replace
from typing import Any, cast

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from observe_support import ROOT, dataset_verdict, observation_for, stdout_for
from verifier.pysrc import Verified, verify_python_source
from verifier.pysrc.spec import DatasetPlot, DatasetTarget
from webui.paste_in import observe

_FIXTURES = ROOT / "tests/fixtures/observe"
_LINE_IDS = (
    "synthetic-accessor-line-str",
    "synthetic-accessor-line-num",
    "synthetic-accessor-line-dec",
    "synthetic-accessor-line-wide",
    "design-simple-05",
    "design-simple-06",
)


def _fixture(case_id: str) -> tuple[Verified, dict[str, Any]]:
    data = json.loads((_FIXTURES / f"{case_id}.json").read_text(encoding="utf-8"))
    assert set(data) == {"id", "arm", "mark", "source", "dataset", "observation"}
    assert (data["id"], data["arm"], data["mark"]) == (case_id, "dataset", "line")
    attached = data["dataset"]
    target = DatasetTarget(attached["path"], attached["content"].encode("utf-8"))
    verified = verify_python_source(data["source"], declared_target=target)
    assert isinstance(verified, Verified), (case_id, verified)
    payload: dict[str, Any] = json.loads(data["observation"])
    return verified, payload


def _matches(verified: Verified, payload: dict[str, Any]) -> bool:
    parsed = observe.parse_observation(stdout_for(payload))
    assert parsed is not None
    return observe.observation_matches(verified, parsed)


def _positional(key_count: int) -> tuple[Verified, dict[str, Any]]:
    """The direct spelling supplies the same spec without depending on accessor admission."""
    content = "key,value\n" + "".join(f"k{index:03},{index}\n" for index in range(key_count))
    source = (
        'import pandas as pd\nimport matplotlib.pyplot as plt\ndf = pd.read_csv("keys.csv")\n'
        'g = df.groupby("key")["value"].sum()\n'
        "plt.plot(g.index, g.values)\nplt.show()\n"
    )
    verified = verify_python_source(
        source, declared_target=DatasetTarget("keys.csv", content.encode("utf-8"))
    )
    assert isinstance(verified, Verified), verified
    payload = observation_for(verified, "categorical")
    payload["xaxis"]["units"] = None
    return verified, payload


@pytest.mark.parametrize("case_id", _LINE_IDS)
def test_b1_committed_accessor_line_fixtures_release(case_id: str) -> None:
    """B1: four synthetic and two captured programs release their own recorded observations."""
    verified, payload = _fixture(case_id)
    assert _matches(verified, payload)


@given(
    key_count=st.integers(min_value=1, max_value=60),
    stride=st.integers(min_value=1, max_value=60),
    offset=st.integers(min_value=0, max_value=59),
    ignored=st.text(alphabet=st.characters(codec="utf-8"), max_size=20),
)
@example(key_count=1, stride=1, offset=0, ignored="wrapped")
@example(key_count=2, stride=2, offset=0, ignored="")
@example(key_count=12, stride=2, offset=0, ignored="k010")
@settings(max_examples=80, deadline=None)
def test_b2_positional_reading_ignores_out_of_range_and_fractional_ticks(
    key_count: int, stride: int, offset: int, ignored: str
) -> None:
    """B2: every nonempty valid sparse tick subset releases; ignored labels impose no condition.

    Singleton, one-label two-key and sparse twelve-key anchors supplement generated tick subsets.
    A1: signed zero compares equal; binary64 neighbors and a container still withhold.
    """
    verified, payload = _positional(key_count)
    keys = verified.table.x
    ticks = [
        [float(index).hex(), keys[index]] for index in range(offset % key_count, key_count, stride)
    ]
    ticks.extend(
        [position.hex(), text]
        for position, text in (
            (-1.0, keys[-1]),
            (-float(key_count), ignored),
            (float(key_count), ignored),
            (0.5, ignored),
            (math.nextafter(1.0, math.inf), ignored),
        )
    )
    payload["xaxis"]["ticks"] = ticks
    assert _matches(verified, payload)
    for coordinate in (0, 1):
        changed = deepcopy(payload)
        changed["lines"][0][0][coordinate] = (-0.0).hex()
        assert _matches(verified, changed)
        changed["lines"][0][0][coordinate] = math.nextafter(0.0, math.inf).hex()
        assert not _matches(verified, changed)
    changed = deepcopy(payload)
    changed["containers"] = [[[(0.0).hex(), (0.0).hex(), (0.8).hex(), (1.0).hex()]]]
    assert not _matches(verified, changed)


@pytest.mark.parametrize(
    "perturbation",
    (
        "labels-swapped",
        "label-altered",
        "x-shifted",
        "x-half-step",
        "y-one-ulp",
        "point-appended",
        "point-dropped",
        "units-present",
        "in-range-ticks-removed",
        "second-line",
        "collection-added",
    ),
)
def test_b3_one_perturbation_withholds(perturbation: str) -> None:  # noqa: PLR0912 — B3 cases
    """B3: mutate exactly one property of a released string-key fixture; then withhold."""
    verified, baseline = _fixture("synthetic-accessor-line-str")
    assert _matches(verified, baseline)
    changed = deepcopy(baseline)
    line = changed["lines"][0]
    ticks = changed["xaxis"]["ticks"]
    integral_ticks = [
        tick
        for tick in ticks
        if float.fromhex(tick[0]).is_integer()
        and 0 <= float.fromhex(tick[0]) < len(verified.table.x)
    ]
    if perturbation == "labels-swapped":
        assert len(integral_ticks) >= 2
        integral_ticks[0][1], integral_ticks[1][1] = integral_ticks[1][1], integral_ticks[0][1]
    elif perturbation == "label-altered":
        integral_ticks[0][1] += "-changed"
    elif perturbation == "x-shifted":
        for point in line:
            point[0] = (float.fromhex(point[0]) + 1.0).hex()
    elif perturbation == "x-half-step":
        line[0][0] = (float.fromhex(line[0][0]) + 0.5).hex()
    elif perturbation == "y-one-ulp":
        line[0][1] = math.nextafter(float.fromhex(line[0][1]), math.inf).hex()
    elif perturbation == "point-appended":
        line.append(deepcopy(line[-1]))
    elif perturbation == "point-dropped":
        line.pop()
    elif perturbation == "units-present":
        changed["xaxis"]["units"] = []
    elif perturbation == "in-range-ticks-removed":
        changed["xaxis"]["ticks"] = [tick for tick in ticks if tick not in integral_ticks]
    elif perturbation == "second-line":
        changed["lines"].append(deepcopy(line))
    elif perturbation == "collection-added":
        changed["collections"] = [deepcopy(line)]
    else:
        raise AssertionError(perturbation)
    assert changed != baseline
    assert not _matches(verified, changed)


@pytest.mark.parametrize("case_id", ("synthetic-accessor-line-num", "synthetic-accessor-line-dec"))
def test_b4_numeric_keys_never_read_positionally(case_id: str) -> None:
    """B4: numeric records release at key values, never at positions justified by key labels."""
    verified, baseline = _fixture(case_id)
    assert _matches(verified, baseline)
    changed = deepcopy(baseline)
    changed["xaxis"]["ticks"] = [
        [float(index).hex(), str(key)] for index, key in enumerate(verified.table.x)
    ]
    for index, point in enumerate(changed["lines"][0]):
        point[0] = float(index).hex()
    assert changed["lines"] != baseline["lines"]
    assert not _matches(verified, changed)


def test_b5_reader_keys_stay_closed_without_a_fallback() -> None:
    """B5: the same four readers release a numeric line, while an unmapped mark withholds."""
    assert set(observe.READERS) == {"line", "scatter", "bar", "barh"}
    verified = dataset_verdict("line", "numeric")
    payload = observation_for(verified)
    assert _matches(verified, payload)
    assert isinstance(verified.spec, DatasetPlot)
    unmapped = replace(verified, spec=replace(verified.spec, mark=cast(Any, "area")))
    assert not _matches(unmapped, payload)


def test_b6_fixture_set_is_38_dataset_and_20_formula() -> None:
    """B6: exact dataset/formula counts; fixture regeneration remains a separate lead-run check."""
    paths = tuple(_FIXTURES.glob("*.json"))
    arms = [json.loads(path.read_text(encoding="utf-8"))["arm"] for path in paths]
    assert len(paths) == 58
    assert arms.count("dataset") == 38
    assert arms.count("formula") == 20
    assert {path.stem for path in paths} >= set(_LINE_IDS)
