# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Regression pins for M9.10 adversarial mutation survivors."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from litestar.testing import TestClient

from verifier.service.app import create_app
from verifier.service.archive import open_archive
from verifier.service.settings import Settings

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_FORMULA = _ROOT / "examples/formula_good_specs/f02_linear.json"
_JSON = {"content-type": "application/json"}

_EXPECTED_RESULTS = (
    ("security.no_arbitrary_code", "construction", "pass"),
    ("formula.values_bounded", "deterministic_recompute", "pass"),
    ("formula.hash_matches_source", "deterministic_recompute", "pass"),
    ("formula.points_from_recomputation", "construction", "pass"),
    ("formula.rounding_unambiguous", "construction", "pass"),
    ("encoding.fields_exist_in_plotted_table", "deterministic_recompute", "pass"),
    ("encoding.axis_types_match_fields", "deterministic_recompute", "pass"),
    ("sort.canonical_order", "z3_smt", "pass"),
    ("render.float64_fidelity", "deterministic_recompute", "pass"),
    ("render.axes_linear", "construction", "pass"),
    ("render.x_domain_exact", "construction", "pass"),
    ("render.points_match_evidence", "construction", "pass"),
    ("render.matplotlib_script_allowlisted", "construction", "pass"),
)


def test_formula_success_returns_the_certified_final_result_sequence(tmp_path: Path) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    with TestClient(app=create_app(settings)) as client:
        response = client.post("/verify-formula", content=_FORMULA.read_bytes(), headers=_JSON)

    assert response.status_code == 200
    payload = cast("dict[str, Any]", response.json())
    results = cast("list[dict[str, str]]", payload["results"])
    assert (
        tuple((result["check"], result["method"], result["status"]) for result in results)
        == _EXPECTED_RESULTS
    )


def test_formula_media_type_refusal_precedes_the_body_cap(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=_DATA,
        state_dir=tmp_path / "state",
        max_body_bytes=8,
    )
    with TestClient(app=create_app(settings)) as client:
        response = client.post(
            "/verify-formula",
            content=b"x" * 9,
            headers={"content-type": "text/plain"},
        )

    assert response.status_code == 415
    assert open_archive(settings).stats().attempts == 0
