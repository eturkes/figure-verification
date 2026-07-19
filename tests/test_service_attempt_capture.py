# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M5.4e mandatory endpoint capture, restart diagnosis, and fail-closed publication."""

import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import msgspec
import pytest
from litestar.testing import TestClient

from verifier import render
from verifier.service import app as service_app
from verifier.service import archive as archive_module
from verifier.service.archive import (
    Archive,
    ArchiveError,
    AttemptBundle,
    AttemptOutcome,
    AttemptRoute,
    open_archive,
)
from verifier.service.model_client import (
    ModelProposal,
    ModelUpstreamError,
    ProposalFault,
    ProposalTrace,
)
from verifier.service.settings import Settings
from verifier.service.store import ArtifactStore

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_GOOD = (_ROOT / "examples/good_specs/g01_total_revenue_by_month.json").read_bytes()
_MISMATCH = (_ROOT / "examples/good_specs/g06_max_temp_by_city.json").read_bytes()
_SEMANTIC_FAIL = (_ROOT / "examples/bad_specs/b08_dataset_hash_mismatch.json").read_bytes()
_JSON = {"content-type": "application/json"}


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    tmp_path.mkdir(parents=True, exist_ok=True)
    return Settings(data_dir=_DATA, state_dir=tmp_path / "state", **overrides)


def _attempt_id(body: dict[str, Any]) -> str:
    attempt_id = body["attempt_id"]
    assert isinstance(attempt_id, str)
    assert len(attempt_id) == 64
    int(attempt_id, 16)
    return attempt_id


def _reopened_attempt(settings: Settings, attempt_id: str) -> AttemptBundle:
    """Create fresh app/archive objects, then authenticate the complete committed occurrence."""
    restarted = service_app.create_app(settings)
    archive = cast("Archive", restarted.state["archive"])
    return archive.read_attempt(
        attempt_id,
        max_bytes=settings.max_archive_bytes,
        limits=settings.limits,
    )


def _proposal(reply: bytes) -> ModelProposal:
    trace = ProposalTrace(
        request_body=b'{"messages":[{"content":"private prompt"}]}',
        response_body=b'{"choices":[{"message":{"content":"private reply"}}]}',
        reply_bytes=reply,
        fault=None,
    )
    return ModelProposal(reply, trace)


def _propose_body() -> bytes:
    return msgspec.json.encode(
        {"user_request": "Plot total revenue by month", "dataset_name": "sales.csv"}
    )


def test_model_fault_archive_classifier_is_total() -> None:
    assert service_app._FAULT_OUTCOME == {
        ProposalFault.TRANSPORT: AttemptOutcome.MODEL_TRANSPORT,
        ProposalFault.CONTENT_ENCODING: AttemptOutcome.MODEL_CONTENT_ENCODING,
        ProposalFault.RESPONSE_TOO_LARGE: AttemptOutcome.MODEL_RESPONSE_TOO_LARGE,
        ProposalFault.HTTP_STATUS: AttemptOutcome.MODEL_HTTP_STATUS,
        ProposalFault.PROMPT_TOKENS: AttemptOutcome.MODEL_PROMPT_TOKENS,
        ProposalFault.INVALID_ENVELOPE: AttemptOutcome.MODEL_INVALID_ENVELOPE,
        ProposalFault.NO_CHOICES: AttemptOutcome.MODEL_NO_CHOICES,
        ProposalFault.EMPTY_CONTENT: AttemptOutcome.MODEL_EMPTY_CONTENT,
    }


def test_direct_success_and_decode_failure_commit_before_response_then_survive_restart(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    app = service_app.create_app(settings)
    with TestClient(app=app) as client:
        success_response = client.post("/verify-and-render", content=_GOOD, headers=_JSON)
        failure_response = client.post("/verify-and-render", content=b"{", headers=_JSON)

    success = cast("dict[str, Any]", success_response.json())
    failure = cast("dict[str, Any]", failure_response.json())
    success_id = _attempt_id(success)
    failure_id = _attempt_id(failure)
    assert success_id != failure_id
    assert success["verified"] is True and failure["verified"] is False

    successful = _reopened_attempt(settings, success_id)
    assert successful.manifest.route is AttemptRoute.VERIFY_AND_RENDER
    assert successful.manifest.outcome is AttemptOutcome.VERIFIED
    assert successful.manifest.plot_id == success["plot_id"]
    assert successful.plot is not None
    assert successful.artifacts.raw_spec == _GOOD
    assert successful.artifacts.raw_csv == successful.plot.raw_csv
    assert successful.artifacts.raw_manifest == successful.plot.raw_manifest
    assert successful.artifacts.verdict == successful.plot.verdict
    assert b"attempt_id" not in successful.artifacts.verdict

    rejected = _reopened_attempt(settings, failure_id)
    assert rejected.manifest.route is AttemptRoute.VERIFY_AND_RENDER
    assert rejected.manifest.outcome is AttemptOutcome.REJECTED
    assert rejected.plot is None
    assert rejected.artifacts.raw_spec == b"{"
    assert rejected.artifacts.raw_csv is None
    assert rejected.artifacts.raw_manifest is None
    assert rejected.artifacts.verdict is not None
    assert b"attempt_id" not in rejected.artifacts.verdict


def test_semantic_and_resource_failures_capture_only_admitted_verifier_inputs(
    tmp_path: Path,
) -> None:
    semantic_settings = _settings(tmp_path / "semantic")
    with TestClient(app=service_app.create_app(semantic_settings)) as client:
        semantic_response = client.post("/verify-and-render", content=_SEMANTIC_FAIL, headers=_JSON)
    semantic_body = cast("dict[str, Any]", semantic_response.json())
    semantic = _reopened_attempt(semantic_settings, _attempt_id(semantic_body))
    assert semantic.manifest.outcome is AttemptOutcome.REJECTED
    assert semantic.artifacts.raw_manifest == (_DATA / "schemas/sales.json").read_bytes()
    assert semantic.artifacts.raw_csv == (_DATA / "sales.csv").read_bytes()

    resource_settings = _settings(tmp_path / "resource", max_csv_bytes=1)
    with TestClient(app=service_app.create_app(resource_settings)) as client:
        resource_response = client.post("/verify-and-render", content=_GOOD, headers=_JSON)
    resource_body = cast("dict[str, Any]", resource_response.json())
    assert any(
        result["check"] == "resource.file_bytes" and result["status"] == "fail"
        for result in resource_body["results"]
    )
    resource = _reopened_attempt(resource_settings, _attempt_id(resource_body))
    assert resource.manifest.outcome is AttemptOutcome.REJECTED
    assert resource.artifacts.raw_manifest == (_DATA / "schemas/sales.json").read_bytes()
    assert resource.artifacts.raw_csv is None


def test_formal_failure_is_durable_and_never_calls_native_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_build = render.build_vega_lite

    def corrupt_zero(*args: Any, **kwargs: Any) -> dict[str, Any]:
        built = original_build(*args, **kwargs)
        built["encoding"]["y"]["scale"]["zero"] = False
        return built

    def forbidden_native(_vega: str) -> str:
        msg = "native render reached after formal rejection"
        raise AssertionError(msg)

    monkeypatch.setattr(render, "build_vega_lite", corrupt_zero)
    monkeypatch.setattr(render, "render_svg", forbidden_native)
    settings = _settings(tmp_path)
    with TestClient(app=service_app.create_app(settings)) as client:
        response = client.post("/verify-and-render", content=_GOOD, headers=_JSON)
    body = cast("dict[str, Any]", response.json())
    assert body["verified"] is False
    assert [
        (item["check"], item["method"]) for item in body["results"] if item["status"] == "fail"
    ] == [("scale.bar_zero", "z3_smt")]
    bundle = _reopened_attempt(settings, _attempt_id(body))
    assert bundle.manifest.outcome is AttemptOutcome.REJECTED
    assert bundle.artifacts.raw_csv == (_DATA / "sales.csv").read_bytes()
    assert bundle.plot is None


def test_proposer_decode_failure_binds_lossless_exchange_and_survives_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fenced = b'```json\n{"not":"vplot"}\n```'
    proposal = _proposal(fenced)
    monkeypatch.setattr(service_app, "propose_spec", AsyncMock(return_value=proposal))
    settings = _settings(tmp_path)
    with TestClient(app=service_app.create_app(settings)) as client:
        response = client.post("/propose-spec", content=_propose_body(), headers=_JSON)
    body = cast("dict[str, Any]", response.json())
    verdict = cast("dict[str, Any]", body["verdict"])
    bundle = _reopened_attempt(settings, _attempt_id(verdict))
    assert bundle.manifest.route is AttemptRoute.PROPOSE_SPEC
    assert bundle.manifest.outcome is AttemptOutcome.REJECTED
    assert bundle.artifacts.raw_spec == fenced
    assert bundle.artifacts.model_reply == fenced
    assert bundle.artifacts.model_request == proposal.trace.request_body
    assert bundle.artifacts.model_response == proposal.trace.response_body
    assert bundle.artifacts.verdict is not None


def test_proposer_success_commits_exchange_and_plot_before_embed_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proposal = _proposal(_GOOD)
    monkeypatch.setattr(service_app, "propose_spec", AsyncMock(return_value=proposal))
    settings = _settings(tmp_path)
    with TestClient(app=service_app.create_app(settings)) as client:
        response = client.post("/propose-spec", content=_propose_body(), headers=_JSON)
    payload = cast("list[Any]", response.json())
    result = cast("dict[str, Any]", payload[0])
    verdict = cast("dict[str, Any]", result["verdict"])
    bundle = _reopened_attempt(settings, _attempt_id(verdict))
    assert bundle.manifest.route is AttemptRoute.PROPOSE_SPEC
    assert bundle.manifest.outcome is AttemptOutcome.VERIFIED
    assert bundle.manifest.plot_id == verdict["plot_id"]
    assert bundle.plot is not None
    assert bundle.artifacts.raw_spec == _GOOD
    assert bundle.artifacts.model_reply == _GOOD
    assert bundle.artifacts.model_request == proposal.trace.request_body
    assert bundle.artifacts.model_response == proposal.trace.response_body
    assert bundle.artifacts.verdict == bundle.plot.verdict


def test_classified_backend_fault_returns_attempt_extension_with_exact_available_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trace = ProposalTrace(
        request_body=b"private request",
        response_body=b"private malformed response",
        reply_bytes=None,
        fault=ProposalFault.INVALID_ENVELOPE,
    )
    fault = ModelUpstreamError("sensitive failure", status=502, trace=trace)
    monkeypatch.setattr(service_app, "propose_spec", AsyncMock(side_effect=fault))
    settings = _settings(tmp_path)
    with TestClient(app=service_app.create_app(settings)) as client:
        response = client.post("/propose-spec", content=_propose_body(), headers=_JSON)
    assert response.status_code == 502
    body = cast("dict[str, Any]", response.json())
    assert "sensitive" not in json.dumps(body)
    bundle = _reopened_attempt(settings, _attempt_id(body))
    assert bundle.manifest.outcome is AttemptOutcome.MODEL_INVALID_ENVELOPE
    assert bundle.artifacts.model_request == trace.request_body
    assert bundle.artifacts.model_response == trace.response_body
    assert bundle.artifacts.model_reply is None
    assert bundle.artifacts.raw_spec is None
    assert bundle.artifacts.verdict is None


def test_dataset_mismatch_commits_problem_trace_without_verifier_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proposal = _proposal(_MISMATCH)
    monkeypatch.setattr(service_app, "propose_spec", AsyncMock(return_value=proposal))
    settings = _settings(tmp_path)
    with TestClient(app=service_app.create_app(settings)) as client:
        response = client.post("/propose-spec", content=_propose_body(), headers=_JSON)
    assert response.status_code == 502
    body = cast("dict[str, Any]", response.json())
    bundle = _reopened_attempt(settings, _attempt_id(body))
    assert bundle.manifest.outcome is AttemptOutcome.DATASET_MISMATCH
    assert bundle.artifacts.raw_spec == _MISMATCH
    assert bundle.artifacts.model_reply == _MISMATCH
    assert bundle.artifacts.raw_csv is None
    assert bundle.artifacts.raw_manifest is None
    assert bundle.artifacts.verdict is None
    assert bundle.plot is None


def test_verify_only_and_pre_admission_refusals_remain_outside_occurrence_ledger(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path, max_active_jobs=1, work_burst=10)
    app = service_app.create_app(settings)
    admission = app.state["admission"]
    with TestClient(app=app) as client:
        verify_only = client.post("/verify-only", content=b"{", headers=_JSON)
        malformed = client.post("/propose-spec", content=b"{}", headers=_JSON)
        wrong_media = client.post(
            "/verify-and-render", content=b"{}", headers={"content-type": "text/plain"}
        )
        held = admission.try_acquire()
        assert held is not None
        with held:
            refused = client.post("/verify-and-render", content=b"{}", headers=_JSON)
    assert verify_only.status_code == 200
    assert "attempt_id" not in verify_only.json()
    assert (malformed.status_code, wrong_media.status_code, refused.status_code) == (400, 415, 429)
    assert all(
        "attempt_id" not in response.json() for response in (malformed, wrong_media, refused)
    )
    assert cast("Archive", app.state["archive"]).stats().attempts == 0


@pytest.mark.parametrize(
    ("fault", "expected_status"),
    [("quota", 507), ("ledger", 500)],
)
def test_archive_fault_replaces_verified_outcome_before_chart_lru_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    expected_status: int,
) -> None:
    cache_calls: list[str] = []

    def observe_chart(_store: ArtifactStore, _plot_id: str, _chart: bytes) -> None:
        cache_calls.append("chart")

    monkeypatch.setattr(ArtifactStore, "put_chart", observe_chart)
    settings = _settings(tmp_path, max_archive_bytes=1 if fault == "quota" else 1_000_000)
    app = service_app.create_app(settings)
    if fault == "ledger":

        def fail_record(_archive: Archive, *_args: object, **_kwargs: object) -> AttemptBundle:
            msg = "injected private ledger failure"
            raise ArchiveError(msg)

        monkeypatch.setattr(Archive, "record_attempt", fail_record)

    with TestClient(app=app) as client:
        response = client.post("/verify-and-render", content=_GOOD, headers=_JSON)
    assert response.status_code == expected_status
    body = cast("dict[str, Any]", response.json())
    assert set(body) == {"title", "status", "detail"}
    assert "verified" not in body and "attempt_id" not in body
    assert "ledger" not in json.dumps(body)
    assert cache_calls == []
    if fault == "quota":
        reopened = open_archive(settings)
        assert reopened.stats() == archive_module.ArchiveStats(0, 0, 0, 0, 0)
