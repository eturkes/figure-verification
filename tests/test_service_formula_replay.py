# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Formula replay HTTP mode-classification, retrieval, and schema contract."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, NoReturn, cast

import httpx
import pytest
from litestar import Litestar
from litestar.testing import TestClient

from formula_plot_bundle_helpers import formula_bundle_parts
from verifier import vcert
from verifier.limits import VerificationLimits
from verifier.service import app as service_app
from verifier.service.admission import AdmissionController
from verifier.service.app import create_app
from verifier.service.archive import (
    Archive,
    ArchiveIntegrityError,
    ArchiveReadLimitError,
    BlobKind,
    FormulaPlotBundle,
    PlotRole,
    PlotSourceKind,
)
from verifier.service.identity import SigningIdentity
from verifier.service.settings import Settings

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_DATASET_SPEC = _ROOT / "examples/good_specs/g01_total_revenue_by_month.json"
_FORMULA_SPEC = _ROOT / "examples/formula_good_specs/f02_linear.json"
_JSON = {"content-type": "application/json"}
_DIRECT_TABLE_CAP = 100_003
_DIRECT_SCRIPT_CAP = 997
_UNKNOWN_TABLE_CAP = 731
_UNKNOWN_SCRIPT_CAP = 509
_FORMULA_TABLE_BYTES = 103
_FORMULA_SCRIPT_BYTES = 483
_TABLE_UNDER_CAP = 102
_SCRIPT_UNDER_CAP = 482
_PROBLEM_JSON = "application/problem+json"
_FORMULA_VERDICT_KEYS = {
    "status",
    "integrity_ok",
    "trusted_keyid",
    "failure_stage",
    "diagnostic",
    "artifact_matches",
    "payload_match",
    "version_match",
    "drift",
    "exact",
}
_FORMULA_ARTIFACT_KEYS = {
    "formula",
    "spec",
    "plotted_table",
    "matplotlib_script",
}
_SOURCE_KIND_NEAR_MISSES = (
    "",
    "Formula",
    "formula ",
    "formula-v2",
    "dataset_formula",
    "__formula__",
    "__class__",
)


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _formula_plot(client: TestClient[Litestar]) -> str:
    response = client.post(
        "/verify-formula",
        content=_FORMULA_SPEC.read_bytes(),
        headers=_JSON,
    )
    assert response.status_code == 200
    body = cast("dict[str, Any]", response.json())
    assert body["verified"] is True
    return cast("str", body["plot_id"])


def _dataset_plot(client: TestClient[Litestar]) -> str:
    response = client.post(
        "/verify-and-render",
        content=_DATASET_SPEC.read_bytes(),
        headers=_JSON,
    )
    assert response.status_code == 200
    body = cast("dict[str, Any]", response.json())
    assert body["verified"] is True
    return cast("str", body["plot_id"])


def _publish_formula_plot(app: Litestar) -> FormulaPlotBundle:
    settings = cast("Settings", app.state["settings"])
    identity = cast("SigningIdentity", app.state["identity"])
    archive = cast("Archive", app.state["archive"])
    plot = cast("FormulaPlotBundle", formula_bundle_parts(signing=identity.signer).bundle)
    archive.publish_plot(plot, limits=settings.limits)
    return plot


def _arm_selection_bombs(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, int]:
    calls = {"source": 0, "read": 0}

    def source_bomb(_archive: Archive, _plot_id: str) -> NoReturn:
        calls["source"] += 1
        msg = "attempt selection reached source-mode classification"
        raise AssertionError(msg)

    def read_bomb(
        _archive: Archive,
        _attempt_id: str,
        *,
        max_bytes: int,
        limits: VerificationLimits,
    ) -> NoReturn:
        calls["read"] += 1
        _ = max_bytes, limits
        msg = "attempt selection reached attempt materialization"
        raise AssertionError(msg)

    monkeypatch.setattr(Archive, "plot_source_kind", source_bomb, raising=False)
    monkeypatch.setattr(Archive, "read_attempt", read_bomb)
    return calls


def _corrupt_blob(archive: Archive, kind: BlobKind) -> None:
    connection = sqlite3.connect(archive.database_path)
    try:
        trigger_row = connection.execute(
            "SELECT sql FROM sqlite_schema WHERE type = 'trigger' AND name = ?",
            ("blobs_reject_update",),
        ).fetchone()
        blob_row = connection.execute(
            "SELECT rowid, content FROM blobs WHERE kind = ? ORDER BY rowid LIMIT 1",
            (kind.value,),
        ).fetchone()
        assert trigger_row is not None
        assert blob_row is not None
        rowid, payload = cast("tuple[int, bytes]", blob_row)
        assert payload
        changed = bytes([payload[0] ^ 1]) + payload[1:]
        connection.execute("DROP TRIGGER blobs_reject_update")
        connection.execute(
            "UPDATE blobs SET content = ? WHERE rowid = ?",
            (changed, rowid),
        )
        connection.execute(cast("str", trigger_row[0]))
        connection.commit()
    finally:
        connection.close()


def _corrupt_source_kind(archive: Archive, plot_id: str, value: str) -> None:
    connection = sqlite3.connect(archive.database_path)
    try:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        cursor = connection.execute(
            "UPDATE plots SET source_kind = ? WHERE plot_id = ?",
            (value, plot_id),
        )
        assert cursor.rowcount == 1
        connection.commit()
    finally:
        connection.close()


def _assert_formula_integrity_failure(response: httpx.Response) -> None:
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["x-content-type-options"] == "nosniff"
    body = cast("dict[str, Any]", response.json())
    assert set(body) == _FORMULA_VERDICT_KEYS
    assert body["status"] == "integrity_failed"
    assert body["integrity_ok"] is False
    assert body["trusted_keyid"] is None
    assert body["failure_stage"] == "attempt_artifacts"
    artifact_matches = cast("dict[str, Any]", body["artifact_matches"])
    assert set(artifact_matches) == _FORMULA_ARTIFACT_KEYS
    assert set(artifact_matches.values()) == {None}
    assert body["payload_match"] is None
    assert body["version_match"] is None
    assert body["drift"] == []
    assert body["exact"] is False
    assert "svg_match" not in body


def _assert_problem(response: httpx.Response, status: int, detail: str) -> None:
    assert response.status_code == status
    assert response.headers["content-type"] == _PROBLEM_JSON
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.json() == {
        "title": httpx.codes.get_reason_phrase(status),
        "status": status,
        "detail": detail,
    }


@pytest.mark.parametrize(
    "kind",
    (
        BlobKind.PLOTTED_TABLE,
        BlobKind.MATPLOTLIB_SCRIPT,
        BlobKind.FORMULA_SOURCE,
        BlobKind.VCERT_PAYLOAD,
    ),
)
def test_classifiable_formula_blob_corruption_keeps_formula_verdict_shape(
    tmp_path: Path,
    kind: BlobKind,
) -> None:
    app = create_app(Settings(data_dir=_DATA, state_dir=tmp_path / "state"))
    archive = cast("Archive", app.state["archive"])
    with TestClient(app=app) as client:
        plot_id = _formula_plot(client)
        _corrupt_blob(archive, kind)
        response = client.get(f"/replay/{plot_id}")

    _assert_formula_integrity_failure(response)


def test_formula_archive_fault_classifies_mode_before_shaping_any_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(Settings(data_dir=_DATA, state_dir=tmp_path / "state"))
    order: list[str] = []
    observed: dict[str, object] = {}

    with TestClient(app=app) as client:
        plot_id = _formula_plot(client)

        def source_kind_spy(_archive: Archive, candidate: str) -> PlotSourceKind:
            order.append("source")
            assert candidate == plot_id
            return PlotSourceKind.FORMULA

        def read_fault(
            _archive: Archive,
            attempt_id: str,
            *,
            max_bytes: int,
            limits: VerificationLimits,
        ) -> NoReturn:
            order.append("read")
            observed.update(
                attempt_id=attempt_id,
                max_bytes=max_bytes,
                limits=limits,
            )
            msg = "forced classifiable formula archive fault"
            raise ArchiveIntegrityError(msg)

        monkeypatch.setattr(Archive, "plot_source_kind", source_kind_spy)
        monkeypatch.setattr(Archive, "read_attempt", read_fault)
        response = client.get(f"/replay/{plot_id}")

    _assert_formula_integrity_failure(response)
    # The fault carries no bundle, so stored provenance is consulted once the read has failed and
    # always before the verdict is shaped. The fault itself never selects the shape.
    assert order == ["read", "source"]
    assert observed["max_bytes"] == cast("Settings", app.state["settings"]).max_archive_bytes
    assert observed["limits"] is cast("Settings", app.state["settings"]).limits


@pytest.mark.parametrize("source_kind", _SOURCE_KIND_NEAR_MISSES)
def test_unclassifiable_source_mode_emits_no_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_kind: str,
) -> None:
    # A record whose own mode cannot be named supports no concrete verdict arm, so the fault
    # escapes unshaped to the logged generic 500 rather than a confidently mislabelled 200.
    app = create_app(Settings(data_dir=_DATA, state_dir=tmp_path / "state"))
    archive = cast("Archive", app.state["archive"])
    handler = _ListHandler()
    logger = logging.getLogger("verifier.service.app")

    with TestClient(app=app) as client:
        plot_id = _formula_plot(client)
        _corrupt_source_kind(archive, plot_id, source_kind)

        def read_fault(
            _archive: Archive,
            _attempt_id: str,
            *,
            max_bytes: int,
            limits: VerificationLimits,
        ) -> NoReturn:
            _ = max_bytes, limits
            msg = "forced archive fault over an unclassifiable occurrence"
            raise ArchiveIntegrityError(msg)

        monkeypatch.setattr(Archive, "read_attempt", read_fault)
        logger.addHandler(handler)
        try:
            response = client.get(f"/replay/{plot_id}")
        finally:
            logger.removeHandler(handler)

    _assert_problem(response, 500, "the verifier encountered an internal error")
    assert handler.records
    record = handler.records[-1]
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
    cause = record.exc_info[1]
    assert isinstance(cause, ArchiveIntegrityError)
    assert "source kind" in str(cause)


@pytest.mark.parametrize("mode", ("dataset", "formula"))
def test_table_route_returns_exact_archived_bytes_for_both_modes(
    tmp_path: Path,
    mode: str,
) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    app = create_app(settings)
    archive = cast("Archive", app.state["archive"])

    with TestClient(app=app) as client:
        plot_id = _dataset_plot(client) if mode == "dataset" else _formula_plot(client)
        expected = archive.read_plot(
            plot_id,
            max_bytes=settings.max_archive_bytes,
            limits=settings.limits,
        ).plotted_table
        response = client.get(f"/table/{plot_id}")

    assert response.status_code == 200
    assert response.content == expected
    assert response.headers["content-type"] == "application/x-ndjson"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_script_route_returns_exact_archived_formula_script(tmp_path: Path) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    app = create_app(settings)
    archive = cast("Archive", app.state["archive"])

    with TestClient(app=app) as client:
        plot_id = _formula_plot(client)
        plot = cast(
            "FormulaPlotBundle",
            archive.read_plot(
                plot_id,
                max_bytes=settings.max_archive_bytes,
                limits=settings.limits,
            ),
        )
        response = client.get(f"/script/{plot_id}")

    assert response.status_code == 200
    assert response.content == plot.matplotlib_script
    assert response.headers["content-type"].split(";", maxsplit=1)[0] == "text/x-python"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_table_and_script_delegate_roles_without_source_mode_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "state"
    seed_settings = Settings(data_dir=_DATA, state_dir=state_dir)
    with TestClient(app=create_app(seed_settings)) as client:
        plot_id = _dataset_plot(client)

    settings = Settings(
        data_dir=_DATA,
        state_dir=state_dir,
        max_archive_bytes=_DIRECT_TABLE_CAP,
        max_matplotlib_script_bytes=_DIRECT_SCRIPT_CAP,
    )
    app = create_app(settings)
    read_calls: list[tuple[str, PlotRole, int]] = []
    source_calls = 0
    original_read = Archive.read_plot_blob

    def source_bomb(_archive: Archive, _plot_id: str) -> NoReturn:
        nonlocal source_calls
        source_calls += 1
        msg = "artifact route inspected plot source mode"
        raise AssertionError(msg)

    def read_spy(
        archive: Archive,
        candidate: str,
        role: PlotRole,
        *,
        max_bytes: int,
    ) -> bytes:
        read_calls.append((candidate, role, max_bytes))
        return original_read(archive, candidate, role, max_bytes=max_bytes)

    monkeypatch.setattr(Archive, "plot_source_kind", source_bomb, raising=False)
    monkeypatch.setattr(Archive, "read_plot_blob", read_spy)
    with TestClient(app=app) as client:
        table = client.get(f"/table/{plot_id}")
        script = client.get(f"/script/{plot_id}")

    assert table.status_code == 200
    _assert_problem(script, 404, "no such artifact")
    assert source_calls == 0
    assert read_calls == [
        (plot_id, PlotRole.PLOTTED_TABLE, _DIRECT_TABLE_CAP),
        (plot_id, PlotRole.MATPLOTLIB_SCRIPT, _DIRECT_SCRIPT_CAP),
    ]


@pytest.mark.parametrize(
    "route_case",
    (
        ("table", PlotRole.PLOTTED_TABLE, _UNKNOWN_TABLE_CAP),
        ("script", PlotRole.MATPLOTLIB_SCRIPT, _UNKNOWN_SCRIPT_CAP),
    ),
)
@pytest.mark.parametrize(
    "address_case",
    (("0" * 64, 1), ("not-a-plot-id", 0)),
)
def test_artifact_routes_share_not_found_shape_and_validate_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route_case: tuple[str, PlotRole, int],
    address_case: tuple[str, int],
) -> None:
    route, role, limit = route_case
    artifact_id, reader_calls = address_case
    settings = Settings(
        data_dir=_DATA,
        state_dir=tmp_path / "state",
        max_archive_bytes=_UNKNOWN_TABLE_CAP,
        max_matplotlib_script_bytes=_UNKNOWN_SCRIPT_CAP,
    )
    app = create_app(settings)
    observed: list[tuple[str, PlotRole, int]] = []
    source_calls = 0
    original_read = Archive.read_plot_blob

    def source_bomb(_archive: Archive, _plot_id: str) -> NoReturn:
        nonlocal source_calls
        source_calls += 1
        msg = "artifact not-found path inspected plot source mode"
        raise AssertionError(msg)

    def read_spy(
        archive: Archive,
        candidate: str,
        selected_role: PlotRole,
        *,
        max_bytes: int,
    ) -> bytes:
        observed.append((candidate, selected_role, max_bytes))
        return original_read(archive, candidate, selected_role, max_bytes=max_bytes)

    monkeypatch.setattr(Archive, "plot_source_kind", source_bomb, raising=False)
    monkeypatch.setattr(Archive, "read_plot_blob", read_spy)
    with TestClient(app=app) as client:
        response = client.get(f"/{route}/{artifact_id}")

    _assert_problem(response, 404, "no such artifact")
    assert source_calls == 0
    expected = [] if reader_calls == 0 else [(artifact_id, role, limit)]
    assert observed == expected


@pytest.mark.parametrize(
    "case",
    (
        ("table", PlotRole.PLOTTED_TABLE, _FORMULA_TABLE_BYTES, _TABLE_UNDER_CAP),
        (
            "script",
            PlotRole.MATPLOTLIB_SCRIPT,
            _FORMULA_SCRIPT_BYTES,
            _SCRIPT_UNDER_CAP,
        ),
    ),
)
def test_artifact_routes_apply_their_own_inclusive_read_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: tuple[str, PlotRole, int, int],
) -> None:
    route, role, payload_bytes, under_cap = case
    state_dir = tmp_path / "state"
    seed_settings = Settings(data_dir=_DATA, state_dir=state_dir)
    seed_app = create_app(seed_settings)
    seed_archive = cast("Archive", seed_app.state["archive"])
    with TestClient(app=seed_app) as client:
        plot_id = _formula_plot(client)
    payload = seed_archive.read_plot_blob(
        plot_id,
        role,
        max_bytes=seed_settings.max_archive_bytes,
    )
    assert len(payload) == payload_bytes
    assert payload_bytes == under_cap + 1

    if route == "table":
        settings = Settings(
            data_dir=_DATA,
            state_dir=state_dir,
            max_archive_bytes=_TABLE_UNDER_CAP,
        )
        assert settings.limits.max_matplotlib_script_bytes != under_cap
    else:
        settings = Settings(
            data_dir=_DATA,
            state_dir=state_dir,
            max_matplotlib_script_bytes=_SCRIPT_UNDER_CAP,
        )
        assert settings.max_archive_bytes != under_cap
    app = create_app(settings)
    calls: list[tuple[str, PlotRole, int]] = []
    original_read = Archive.read_plot_blob
    handler = _ListHandler()
    logger = logging.getLogger("verifier.service.app")

    def read_spy(
        archive: Archive,
        candidate: str,
        selected_role: PlotRole,
        *,
        max_bytes: int,
    ) -> bytes:
        calls.append((candidate, selected_role, max_bytes))
        return original_read(archive, candidate, selected_role, max_bytes=max_bytes)

    monkeypatch.setattr(Archive, "read_plot_blob", read_spy)
    with TestClient(app=app) as client:
        logger.addHandler(handler)
        try:
            response = client.get(f"/{route}/{plot_id}")
        finally:
            logger.removeHandler(handler)

    _assert_problem(response, 500, "the verifier encountered an internal error")
    assert calls == [(plot_id, role, under_cap)]
    assert handler.records
    record = handler.records[-1]
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
    cause = record.exc_info[1]
    assert isinstance(cause, ArchiveReadLimitError)
    assert f"read limit is {under_cap}" in str(cause)


@pytest.mark.parametrize(
    "case",
    (
        ("table", "application/x-ndjson"),
        ("script", "text/x-python"),
        ("certificate", "application/json"),
    ),
)
def test_artifact_gets_take_no_work_admission_permit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: tuple[str, str],
) -> None:
    route, media_type = case
    app = create_app(
        Settings(
            data_dir=_DATA,
            state_dir=tmp_path / "state",
            max_active_jobs=1,
            work_rate_per_minute=10,
            work_burst=10,
        )
    )
    admission = cast("AdmissionController", app.state["admission"])
    with TestClient(app=app) as seed_client:
        plot_id = _formula_plot(seed_client)
    held = admission.try_acquire()
    assert held is not None
    admit_calls = 0
    controller_calls = 0

    def admit_bomb(_state: object) -> NoReturn:
        nonlocal admit_calls
        admit_calls += 1
        msg = "artifact GET reached shared work admission"
        raise AssertionError(msg)

    def controller_bomb(_controller: AdmissionController) -> NoReturn:
        nonlocal controller_calls
        controller_calls += 1
        msg = "artifact GET reached admission controller"
        raise AssertionError(msg)

    monkeypatch.setattr(service_app, "_admit_work", admit_bomb)
    monkeypatch.setattr(AdmissionController, "try_acquire", controller_bomb)
    with held, TestClient(app=app) as client:
        response = client.get(f"/{route}/{plot_id}")

    assert response.status_code == 200
    assert response.headers["content-type"].split(";", maxsplit=1)[0] == media_type
    assert response.headers["x-content-type-options"] == "nosniff"
    assert admit_calls == 0
    assert controller_calls == 0


def test_formula_plot_with_zero_attempts_404s_before_mode_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(Settings(data_dir=_DATA, state_dir=tmp_path / "state"))
    archive = cast("Archive", app.state["archive"])
    plot = _publish_formula_plot(app)
    assert archive.stats().attempts == 0
    calls = _arm_selection_bombs(monkeypatch)

    with TestClient(app=app) as client:
        response = client.get(f"/replay/{plot.plot_id}")

    _assert_problem(response, 404, "no such plot")
    assert calls == {"source": 0, "read": 0}


def test_formula_plot_with_only_rejected_attempt_404s_before_mode_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(Settings(data_dir=_DATA, state_dir=tmp_path / "state"))
    archive = cast("Archive", app.state["archive"])
    plot = _publish_formula_plot(app)
    with TestClient(app=app) as client:
        rejected = client.post(
            "/verify-formula",
            content=b"{",
            headers=_JSON,
        )
    assert rejected.status_code == 200
    assert rejected.json()["verified"] is False
    assert archive.stats().attempts == 1
    assert archive.lowest_verified_attempt_id(plot.plot_id) is None
    calls = _arm_selection_bombs(monkeypatch)

    with TestClient(app=app) as client:
        response = client.get(f"/replay/{plot.plot_id}")

    _assert_problem(response, 404, "no such plot")
    assert calls == {"source": 0, "read": 0}


def test_malformed_replay_id_404s_before_archive_or_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(
        Settings(
            data_dir=_DATA,
            state_dir=tmp_path / "state",
            max_active_jobs=1,
            work_rate_per_minute=10,
            work_burst=10,
        )
    )
    admission = cast("AdmissionController", app.state["admission"])
    held = admission.try_acquire()
    assert held is not None
    selection_calls = 0
    admission_calls = 0
    calls = _arm_selection_bombs(monkeypatch)

    def selection_bomb(_archive: Archive, _plot_id: str) -> NoReturn:
        nonlocal selection_calls
        selection_calls += 1
        msg = "malformed replay id reached archive selection"
        raise AssertionError(msg)

    def admission_bomb(_state: object) -> NoReturn:
        nonlocal admission_calls
        admission_calls += 1
        msg = "malformed replay id reached work admission"
        raise AssertionError(msg)

    monkeypatch.setattr(Archive, "lowest_verified_attempt_id", selection_bomb)
    monkeypatch.setattr(service_app, "_admit_work", admission_bomb)
    with held, TestClient(app=app) as client:
        response = client.get("/replay/not-a-plot-id")

    _assert_problem(response, 404, "no such plot")
    assert selection_calls == 0
    assert admission_calls == 0
    assert calls == {"source": 0, "read": 0}


def test_unknown_replay_id_selects_once_without_mode_or_attempt_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(Settings(data_dir=_DATA, state_dir=tmp_path / "state"))
    with TestClient(app=app) as seed_client:
        known_plot_id = _formula_plot(seed_client)
    unknown_plot_id = "0" * 64
    assert unknown_plot_id != known_plot_id
    selected: list[str] = []
    calls = _arm_selection_bombs(monkeypatch)
    original_select = Archive.lowest_verified_attempt_id

    def selection_spy(archive: Archive, candidate: str) -> str | None:
        selected.append(candidate)
        return original_select(archive, candidate)

    monkeypatch.setattr(Archive, "lowest_verified_attempt_id", selection_spy)
    with TestClient(app=app) as client:
        response = client.get(f"/replay/{unknown_plot_id}")

    _assert_problem(response, 404, "no such plot")
    assert selected == [unknown_plot_id]
    assert calls == {"source": 0, "read": 0}


def test_formula_replay_reports_live_tcb_drift_in_its_own_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(Settings(data_dir=_DATA, state_dir=tmp_path / "state"))
    with TestClient(app=app) as client:
        plot_id = _formula_plot(client)
        monkeypatch.setattr(vcert, "__version__", "test-m9u11-drift")
        response = client.get(f"/replay/{plot_id}")

    assert response.status_code == 200
    body = cast("dict[str, Any]", response.json())
    assert set(body) == _FORMULA_VERDICT_KEYS
    assert body["status"] == "drift"
    assert body["integrity_ok"] is True
    assert cast("str", body["trusted_keyid"]).startswith("sha256:")
    assert body["failure_stage"] is None
    assert body["diagnostic"] == (
        "authenticated artifacts match but the current TCB versions drifted"
    )
    assert body["artifact_matches"] == {
        "formula": True,
        "spec": True,
        "plotted_table": True,
        "matplotlib_script": True,
    }
    assert body["payload_match"] is False
    assert body["version_match"] is False
    drift = cast("list[dict[str, str]]", body["drift"])
    assert len(drift) == 1
    assert drift[0]["field"] == "verifier_version"
    assert drift[0]["archived"] != drift[0]["current"]
    assert drift[0]["current"] == "test-m9u11-drift"
    assert body["exact"] is False
    assert "svg_match" not in body
