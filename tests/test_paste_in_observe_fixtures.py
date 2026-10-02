# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.2 O3/O5/O7: committed Pyodide observations bind the independently recomputed table.

Contract: `.agent/archive/contracts/m10u2.md` § A1. Fixtures are self-contained rendered artist
observations, not expected verdicts. The host projector is deliberately changed only in O7.
"""

import ast
import hashlib
import importlib
import json
from dataclasses import replace
from fractions import Fraction
from typing import Any
from unittest.mock import patch

import pytest

from observe_support import OBS_TAG, ROOT
from verifier.pysrc import Verified, verify_python_source
from verifier.pysrc.limits import PysrcLimits
from verifier.pysrc.spec import (
    Bin,
    Column,
    CorePlotSpec,
    DatasetPlot,
    DatasetTarget,
    FormulaPlot,
    Num,
)

_FIXTURES = ROOT / "tests" / "fixtures" / "observe"
_DATASET_IDS = (
    "design-simple-01",
    "design-simple-02",
    "design-simple-03",
    "design-simple-05",
    "design-simple-06",
    "design-simple-09",
    "design-simple-11",
    "design-simple-17",
    "design-simple-18",
    "design-simple-19",
    "sentinel-simple",
    "synthetic-bar-str",
    "synthetic-bar-num",
    "synthetic-bar-dec",
    "synthetic-barh-str",
    "synthetic-barh-num",
    "synthetic-barh-dec",
    "synthetic-plot-str",
    "synthetic-plot-num",
    "synthetic-plot-dec",
    "synthetic-scatter-num",
    "synthetic-scatter-dec",
    "synthetic-accessor-bar-str",
    "synthetic-accessor-bar-num",
    "synthetic-accessor-bar-dec",
    "synthetic-accessor-barh-str",
    "synthetic-accessor-barh-num",
    "synthetic-accessor-barh-dec",
    "synthetic-accessor-line-str",
    "synthetic-accessor-line-num",
    "synthetic-accessor-line-dec",
    "synthetic-accessor-line-wide",
    "synthetic-direct-group-bar-str",
    "synthetic-direct-group-bar-num",
    "synthetic-direct-group-bar-dec",
    "synthetic-direct-group-barh-str",
    "synthetic-direct-group-barh-num",
    "synthetic-direct-group-barh-dec",
)
_FORMULA_IDS = tuple(
    f"formula-{function}-{mark}"
    for function in (
        "sin",
        "cos",
        "tan",
        "exp",
        "log",
        "sqrt",
        "abs",
        "pow",
        "exact",
        "cancellation",
        "gauss",
        "sin-square",
    )
    for mark in ("plot", "scatter")
)
_EXPECTED = frozenset((*_DATASET_IDS, *_FORMULA_IDS))


def _case(case_id: str) -> tuple[dict[str, Any], Verified, object]:
    raw = (_FIXTURES / f"{case_id}.json").read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(raw)
    assert set(data) == {"id", "arm", "mark", "source", "dataset", "observation"}
    assert data["id"] == case_id
    assert isinstance(data["source"], str)
    assert isinstance(data["observation"], str)
    declared: DatasetTarget | None = None
    if data["arm"] == "dataset":
        attached = data["dataset"]
        assert isinstance(attached, dict)
        assert set(attached) == {"path", "content"}
        assert isinstance(attached["path"], str)
        assert isinstance(attached["content"], str)
        declared = DatasetTarget(attached["path"], attached["content"].encode("utf-8"))
    else:
        assert data["arm"] == "formula"
        assert data["dataset"] is None
    verdict = verify_python_source(data["source"], declared_target=declared)
    assert isinstance(verdict, Verified), (case_id, verdict)
    assert verdict.spec.mark == data["mark"]
    parsed = importlib.import_module("webui.paste_in.observe").parse_observation(
        OBS_TAG + data["observation"] + "\n"
    )
    assert parsed is not None
    return data, verdict, parsed


def _matches(verdict: Verified, observed: object) -> bool:
    return bool(
        importlib.import_module("webui.paste_in.observe").observation_matches(verdict, observed)
    )


def test_o3_o5_observation_fixture_set_is_exactly_38_dataset_and_24_formula() -> None:
    """O3/O5, widened by M10.10 B6 and by Q18 (the `np.exp(-x**2)` + `np.sin(x)**2` nested-libm
    pairs): exactly 62 IDs, never a silent fixture loss."""
    assert len(_DATASET_IDS) == 38
    assert len(_FORMULA_IDS) == 24
    assert len(_EXPECTED) == 62
    actual = {path.stem for path in _FIXTURES.glob("*.json")}
    assert actual == _EXPECTED, (
        f"missing={sorted(_EXPECTED - actual)}; extra={sorted(actual - _EXPECTED)}"
    )


@pytest.mark.parametrize("case_id", _DATASET_IDS)
def test_o3_committed_dataset_artist_fixture_releases(case_id: str) -> None:
    """O3/B1: 38 recorded dataset artists match recomputation over their own CSV."""
    data, verdict, observed = _case(case_id)
    assert data["arm"] == "dataset"
    assert isinstance(verdict.spec, DatasetPlot)
    assert _matches(verdict, observed)


@pytest.mark.parametrize("case_id", _FORMULA_IDS)
def test_o5_committed_formula_artist_fixture_releases(case_id: str) -> None:
    """O5: 20 recorded formula artists bind all observed samples inside the host interval."""
    data, verdict, observed = _case(case_id)
    assert data["arm"] == "formula"
    assert isinstance(verdict.spec, FormulaPlot)
    assert _matches(verdict, observed)


@pytest.mark.parametrize("case_id", ["synthetic-bar-str", "synthetic-barh-str", "formula-sin-plot"])
def test_o7_host_projection_defect_only_observation_catches(case_id: str) -> None:
    """O7: altered projection still certifies, but original sandbox artist cannot be released."""
    data, original, observed = _case(case_id)
    assert _matches(original, observed)
    verify_module = importlib.import_module("verifier.pysrc.verify")
    original_project = verify_module.project

    def mutated_project(tree: ast.Module, limits: PysrcLimits) -> CorePlotSpec:
        projected: CorePlotSpec = original_project(tree, limits)
        if case_id == "formula-sin-plot":
            assert isinstance(projected, FormulaPlot)
            factor = Num(Fraction(1 + 2**-40))
            return replace(projected, y=Bin("mul", projected.y, factor))
        assert isinstance(projected, DatasetPlot)
        return replace(projected, x=Column("value"))

    attached = data["dataset"]
    declared = (
        None
        if attached is None
        else DatasetTarget(path=attached["path"], content=attached["content"].encode("utf-8"))
    )
    with patch.object(verify_module, "project", side_effect=mutated_project):
        mutated = verify_python_source(data["source"], declared_target=declared)
    assert isinstance(mutated, Verified)
    assert mutated.spec != original.spec
    assert mutated.table != original.table
    assert mutated.certificate.spec_sha256 != original.certificate.spec_sha256
    assert mutated.certificate.table_sha256 == (
        "sha256:" + hashlib.sha256(mutated.table.canonical_bytes()).hexdigest()
    )
    assert not _matches(mutated, observed)
