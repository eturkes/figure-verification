# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Replay HTTP transport: bounded verdicts, trust/error split, chart regeneration, admission."""

import logging
import sqlite3
from pathlib import Path
from typing import Any, cast

import httpx
from litestar import Litestar
from litestar.testing import TestClient

from verifier.service.admission import AdmissionController
from verifier.service.app import create_app
from verifier.service.archive import Archive, ArchiveSchemaError, BlobKind
from verifier.service.settings import Settings

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_GOOD_SPEC = _ROOT / "examples" / "good_specs" / "g01_total_revenue_by_month.json"
_JSON = {"content-type": "application/json"}
_PROBLEM_JSON = "application/problem+json"


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _render_plot(client: TestClient[Litestar]) -> str:
    response = client.post(
        "/verify-and-render",
        content=_GOOD_SPEC.read_bytes(),
        headers=_JSON,
    )
    assert response.status_code == 200
    body = cast("dict[str, Any]", response.json())
    assert body["verified"] is True
    return cast("str", body["plot_id"])


def _assert_problem(response: httpx.Response, status: int, detail: str) -> None:
    assert response.status_code == status
    assert response.headers["content-type"] == _PROBLEM_JSON
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.json() == {
        "title": httpx.codes.get_reason_phrase(status),
        "status": status,
        "detail": detail,
    }


def test_render_restart_replay_repopulates_chart_lru(tmp_path: Path) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    with TestClient(app=create_app(settings)) as first_client:
        plot_id = _render_plot(first_client)

    with TestClient(app=create_app(settings)) as restarted_client:
        assert restarted_client.get(f"/chart/{plot_id}").status_code == 404

        replay = restarted_client.get(f"/replay/{plot_id}")
        assert replay.status_code == 200
        assert replay.headers["content-type"] == "application/json"
        body = cast("dict[str, Any]", replay.json())
        assert body["status"] == "exact"
        assert body["exact"] is True
        assert body["integrity_ok"] is True

        chart = restarted_client.get(f"/chart/{plot_id}")
        assert chart.status_code == 200
        assert chart.headers["content-type"].startswith("text/html")
        assert chart.headers["content-security-policy"] == "sandbox allow-scripts"
        assert chart.headers["x-content-type-options"] == "nosniff"
        assert plot_id.encode() in chart.content


def test_exact_replay_response_is_bounded_replay_verdict(tmp_path: Path) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    with TestClient(app=create_app(settings)) as client:
        plot_id = _render_plot(client)
        response = client.get(f"/replay/{plot_id}")

    assert response.status_code == 200
    body = cast("dict[str, Any]", response.json())
    assert set(body) == {
        "status",
        "integrity_ok",
        "trusted_keyid",
        "failure_stage",
        "diagnostic",
        "artifact_matches",
        "payload_match",
        "version_match",
        "drift",
        "svg_match",
        "exact",
    }
    assert body["status"] == "exact"
    assert body["integrity_ok"] is True
    assert cast("str", body["trusted_keyid"]).startswith("sha256:")
    assert body["failure_stage"] is None
    assert body["artifact_matches"] == {
        "dataset": True,
        "manifest": True,
        "spec": True,
        "plotted_table": True,
        "vega_lite": True,
    }
    assert body["payload_match"] is True
    assert body["version_match"] is True
    assert body["drift"] == []
    assert body["svg_match"] is True
    assert body["exact"] is True
    for forbidden_field in (
        b'"raw_csv"',
        b'"raw_manifest"',
        b'"raw_spec"',
        b'"prompt"',
        b'"snapshot"',
        b'"chart_html"',
        b'"svg"',
    ):
        assert forbidden_field not in response.content


def test_malformed_plot_id_404s_before_admission(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            data_dir=_DATA,
            state_dir=tmp_path / "state",
            max_active_jobs=1,
            work_rate_per_minute=1,
            work_burst=1,
        )
    )
    admission = cast("AdmissionController", app.state["admission"])
    held = admission.try_acquire()
    assert held is not None

    with TestClient(app=app) as client, held:
        response = client.get("/replay/not-a-plot-id")

    _assert_problem(response, 404, "no such plot")


def test_unknown_plot_id_404s_from_archive_lookup(tmp_path: Path) -> None:
    with TestClient(
        app=create_app(Settings(data_dir=_DATA, state_dir=tmp_path / "state"))
    ) as client:
        response = client.get(f"/replay/{'0' * 64}")

    _assert_problem(response, 404, "no such plot")


def test_untrusted_archived_signer_returns_diagnostic_without_chart(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    with TestClient(app=create_app(Settings(data_dir=_DATA, state_dir=state_dir))) as first_client:
        plot_id = _render_plot(first_client)

    rotated = Settings(
        data_dir=_DATA,
        state_dir=state_dir,
        signing_key_file=state_dir / "rotated.key",
    )
    with TestClient(app=create_app(rotated)) as client:
        assert client.get(f"/chart/{plot_id}").status_code == 404
        replay = client.get(f"/replay/{plot_id}")
        assert replay.status_code == 200
        body = cast("dict[str, Any]", replay.json())
        assert body["status"] == "untrusted_key"
        assert body["integrity_ok"] is False
        assert body["exact"] is False
        assert client.get(f"/chart/{plot_id}").status_code == 404


def test_archive_artifact_integrity_fault_returns_bounded_200(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=_DATA, state_dir=tmp_path / "state"))
    archive = cast("Archive", app.state["archive"])

    with TestClient(app=app) as client:
        plot_id = _render_plot(client)
        connection = sqlite3.connect(archive.database_path)
        try:
            row = connection.execute(
                "SELECT content FROM blobs WHERE kind = ?",
                (BlobKind.RAW_CSV.value,),
            ).fetchone()
            assert row is not None
            payload = cast("bytes", row[0])
            trigger_row = connection.execute(
                "SELECT sql FROM sqlite_schema WHERE type = 'trigger' AND name = ?",
                ("blobs_reject_update",),
            ).fetchone()
            assert trigger_row is not None
            trigger_sql = cast("str", trigger_row[0])
            connection.execute("DROP TRIGGER blobs_reject_update")
            connection.execute(
                "UPDATE blobs SET content = ? WHERE kind = ?",
                (b"x" * len(payload), BlobKind.RAW_CSV.value),
            )
            connection.execute(trigger_sql)
            connection.commit()
        finally:
            connection.close()

        response = client.get(f"/replay/{plot_id}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "status": "integrity_failed",
        "integrity_ok": False,
        "trusted_keyid": None,
        "failure_stage": "attempt_artifacts",
        "diagnostic": "archived replay artifacts failed integrity validation",
        "artifact_matches": {
            "dataset": None,
            "manifest": None,
            "spec": None,
            "plotted_table": None,
            "vega_lite": None,
        },
        "payload_match": None,
        "version_match": None,
        "drift": [],
        "svg_match": None,
        "exact": False,
    }


def test_archive_schema_fault_is_logged_and_returns_generic_500(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=_DATA, state_dir=tmp_path / "state"))
    archive = cast("Archive", app.state["archive"])
    handler = _ListHandler()
    logger = logging.getLogger("verifier.service.app")

    with TestClient(app=app) as client:
        plot_id = _render_plot(client)
        connection = sqlite3.connect(archive.database_path)
        try:
            connection.execute("DROP INDEX attempts_by_plot")
            connection.commit()
        finally:
            connection.close()

        logger.addHandler(handler)
        try:
            response = client.get(f"/replay/{plot_id}")
        finally:
            logger.removeHandler(handler)

    _assert_problem(response, 500, "the verifier encountered an internal error")
    assert "attempts_by_plot" not in response.text
    assert handler.records
    record = handler.records[-1]
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
    cause = record.exc_info[1]
    assert isinstance(cause, ArchiveSchemaError)
    assert str(cause)
    assert str(cause) not in response.text


def test_replay_uses_shared_active_job_admission(tmp_path: Path) -> None:
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

    with TestClient(app=app) as client, held:
        response = client.get(f"/replay/{'0' * 64}")

    _assert_problem(
        response,
        429,
        "the process-local verifier work limit is currently exhausted",
    )
