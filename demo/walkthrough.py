# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Self-contained M5.5d hardening walkthrough used by ``python -m demo``.

Every scenario owns a temporary service state directory, drives the Litestar app in process, and
checks an operator-visible hardening property. Expected faults are induced with scoped patches;
no socket, model, accelerator, or external service is used.
"""

import hashlib
import io
import json
import logging
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import closing, redirect_stdout
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, cast
from unittest.mock import patch

import httpx
import msgspec
from litestar import Litestar
from litestar.testing import TestClient

from verifier import attestation, canon, formal, render
from verifier.service import archive as archive_module
from verifier.service import audit, model_client
from verifier.service.__main__ import main as service_main
from verifier.service.admission import AdmissionController
from verifier.service.app import create_app
from verifier.service.archive import (
    Archive,
    ArchiveBatch,
    ArchiveIntegrityError,
    ArchiveSchemaError,
    ArchiveStats,
    AttemptBundle,
    BlobKind,
    BlobWrite,
    open_archive,
)
from verifier.service.identity import SigningIdentity
from verifier.service.settings import Settings
from verifier.service.store import ArtifactStore

_LOGGER = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_GOOD_SPEC = _ROOT / "examples" / "good_specs" / "g01_total_revenue_by_month.json"
_SECOND_SPEC = _ROOT / "examples" / "good_specs" / "g02_revenue_by_region.json"
_WEATHER_SPEC = _ROOT / "examples" / "good_specs" / "g07_temp_over_time_by_city.json"
_JSON = {"content-type": "application/json"}
_PROBLEM_JSON = "application/problem+json"

_HTTP_OK = 200
_HTTP_NOT_FOUND = 404
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_INTERNAL_SERVER_ERROR = 500
_HTTP_INSUFFICIENT_STORAGE = 507
_ATTEMPT_ID_LENGTH = 64
_CACHE_BYTES = 2 * 1024 * 1024
_DRIFT_VERSION = "demo-verifier-drift"

ScenarioStatus = Literal["PASS", "FAIL"]
Scenario = Callable[[Path], str]


class DemoError(RuntimeError):
    """An explicit walkthrough check failed."""


class ScenarioResult(msgspec.Struct, frozen=True, kw_only=True):
    """One independently executed walkthrough scenario."""

    name: str
    status: ScenarioStatus
    detail: str


class WalkthroughReport(msgspec.Struct, frozen=True, kw_only=True):
    """Machine-readable result written to ``demo/reports/report.json``."""

    generated_at: str
    status: ScenarioStatus
    passed: int
    failed: int
    total: int
    results: tuple[ScenarioResult, ...]


class _ListHandler(logging.Handler):
    """Collect expected service error records without printing their tracebacks."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class _StdoutCapture(io.StringIO):
    """A StringIO usable with redirect_stdout and binary-writing CLIs."""

    def __init__(self) -> None:
        super().__init__()
        self._binary = io.BytesIO()

    @property
    def buffer(self) -> io.BytesIO:
        return self._binary

    def output(self) -> str:
        return super().getvalue() + self._binary.getvalue().decode("ascii")


def _require(condition: object, detail: str) -> None:
    if not condition:
        raise DemoError(detail)


def _object(value: object, context: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{context} was not a JSON object")
    return cast("dict[str, Any]", value)


def _object_list(value: object, context: str) -> list[dict[str, Any]]:
    _require(isinstance(value, list), f"{context} was not a JSON array")
    return [_object(item, f"{context} item") for item in cast("list[object]", value)]


def _response_object(response: httpx.Response, context: str) -> dict[str, Any]:
    return _object(response.json(), context)


def _expect_status(response: httpx.Response, status: int, context: str) -> None:
    _require(
        response.status_code == status,
        f"{context} returned HTTP {response.status_code}, expected {status}",
    )


def _expect_problem(response: httpx.Response, status: int, detail: str) -> None:
    _expect_status(response, status, "problem response")
    _require(response.headers.get("content-type") == _PROBLEM_JSON, "problem MIME type drifted")
    _require(
        response.headers.get("x-content-type-options") == "nosniff",
        "problem response lost nosniff",
    )
    expected = {
        "title": httpx.codes.get_reason_phrase(status),
        "status": status,
        "detail": detail,
    }
    _require(_response_object(response, "problem response") == expected, "problem body drifted")


def _attempt_id(body: dict[str, Any]) -> str:
    value = body.get("attempt_id")
    _require(isinstance(value, str), "attempt_id was missing or non-string")
    attempt_id = cast("str", value)
    _require(len(attempt_id) == _ATTEMPT_ID_LENGTH, "attempt_id was not a SHA-256 hex digest")
    try:
        int(attempt_id, 16)
    except ValueError as exc:
        detail = "attempt_id contained non-hexadecimal characters"
        raise DemoError(detail) from exc
    return attempt_id


def _render_verified(client: TestClient[Litestar], spec: bytes) -> dict[str, Any]:
    response = client.post("/verify-and-render", content=spec, headers=_JSON)
    _expect_status(response, _HTTP_OK, "verify-and-render")
    body = _response_object(response, "verify-and-render response")
    _require(body.get("verified") is True, "verify-and-render did not verify the valid spec")
    return body


def _render_plot(client: TestClient[Litestar]) -> str:
    body = _render_verified(client, _GOOD_SPEC.read_bytes())
    plot_id = body.get("plot_id")
    _require(isinstance(plot_id, str), "verified response omitted plot_id")
    return cast("str", plot_id)


def _certificate(client: TestClient[Litestar], app: Litestar, plot_id: str) -> render.VCert:
    response = client.get(f"/certificate/{plot_id}")
    _expect_status(response, _HTTP_OK, "certificate fetch")
    identity = cast("SigningIdentity", app.state["identity"])
    return attestation.verify_vcert(response.content, identity.trusted_keys).certificate


def _read_attempt(settings: Settings, attempt_id: str) -> AttemptBundle:
    return open_archive(settings).read_attempt(
        attempt_id,
        max_bytes=settings.max_archive_bytes,
        limits=settings.limits,
    )


def _render_attempt_bundle(settings: Settings) -> AttemptBundle:
    with TestClient(app=create_app(settings)) as client:
        body = _render_verified(client, _GOOD_SPEC.read_bytes())
    return _read_attempt(settings, _attempt_id(body))


def _copy_sales_dataset(data_dir: Path) -> tuple[Path, Path]:
    source = data_dir / "sales.csv"
    manifest = data_dir / "schemas" / "sales.json"
    manifest.parent.mkdir()
    source.write_bytes((_DATA / "sales.csv").read_bytes())
    manifest.write_bytes((_DATA / "schemas" / "sales.json").read_bytes())
    return source, manifest


def _three_obligation_spec() -> bytes:
    document = cast("dict[str, Any]", json.loads(_GOOD_SPEC.read_bytes()))
    transforms = cast("list[dict[str, Any]]", document["transform"])
    transforms[0]["keys"] = ["month", "region"]
    encoding = cast("dict[str, Any]", document["encoding"])
    encoding["color"] = {"field": "region", "type": "nominal"}
    return msgspec.json.encode(document)


def _propose(client: TestClient[Litestar]) -> httpx.Response:
    request = msgspec.json.encode(
        {"user_request": "Plot total revenue by month", "dataset_name": "sales.csv"}
    )
    return client.post("/propose-spec", content=request, headers=_JSON)


def _model_client_builder(content: bytes) -> Callable[[Settings], httpx.AsyncClient]:
    """Build the same socket-free MockTransport seam used by the capstone test."""

    class Stream(httpx.AsyncByteStream):
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield self._payload

    def handler(_request: httpx.Request) -> httpx.Response:
        envelope = {"choices": [{"message": {"content": content.decode("utf-8")}}]}
        return httpx.Response(_HTTP_OK, json=envelope)

    def stream_handler(request: httpx.Request) -> httpx.Response:
        response = handler(request)
        if not response.is_stream_consumed:
            return response
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            stream=Stream(response.content),
        )

    def build(settings: Settings) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(stream_handler),
            timeout=settings.model_timeout,
        )

    return build


def _scenario_direct_render_and_invalid_utf8(tmp_path: Path) -> str:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    app = create_app(settings)
    invalid = b'{"version":"\xff\xfe"}'

    with TestClient(app=app) as client:
        for route in ("/verify-only", "/verify-and-render"):
            response = client.post(route, content=invalid, headers=_JSON)
            _expect_status(response, _HTTP_OK, f"invalid UTF-8 {route}")
            body = _response_object(response, f"invalid UTF-8 {route}")
            _require(body.get("verified") is False, f"{route} accepted invalid UTF-8")
            _require(body.get("layer") == "decode", f"{route} did not return a decode verdict")
            results = _object_list(body.get("results"), f"{route} results")
            _require(len(results) == 1, f"{route} returned an unbounded decode result list")
            _require(results[0].get("check") == "spec.decode", f"{route} check drifted")
            message = results[0].get("message")
            _require(
                isinstance(message, str) and "valid UTF-8" in message,
                f"{route} lost the readable UTF-8 explanation",
            )

        verified = _render_verified(client, _GOOD_SPEC.read_bytes())
        plot_id = cast("str", verified["plot_id"])
        certificate = _certificate(client, app, plot_id)

    _require(
        any(check.method == "z3_smt" for check in certificate.checks),
        "direct-render certificate omitted formal-method checks",
    )
    return "bounded decode verdicts and direct-render formal certificate verified"


def _scenario_model_stub_success(tmp_path: Path) -> str:
    reply = _three_obligation_spec()
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    app = create_app(settings)

    with (
        patch.object(model_client, "_build_async_client", _model_client_builder(reply)),
        TestClient(app=app) as client,
    ):
        response = _propose(client)
        _expect_status(response, _HTTP_OK, "successful model proposal")
        payload = response.json()
        _require(isinstance(payload, list) and bool(payload), "successful proposal was not wrapped")
        result = _object(cast("list[object]", payload)[0], "successful model proposal result")
        verdict = _object(result.get("verdict"), "successful proposal verdict")
        _require(result.get("model_reply") == reply.decode(), "model reply was not preserved")
        _require(verdict.get("verified") is True, "model proposal did not verify")
        plot_id = cast("str", verdict["plot_id"])
        _expect_status(client.get(f"/chart/{plot_id}"), _HTTP_OK, "model-proposed chart")
        certificate = _certificate(client, app, plot_id)

    attempt = _read_attempt(settings, _attempt_id(verdict))
    _require(attempt.artifacts.model_reply == reply, "archived model reply drifted")
    _require(
        any(check.method == "z3_smt" for check in certificate.checks),
        "model-success certificate omitted SMT checks",
    )
    return "stubbed proposal traversed verify, archive, certificate, and chart serving"


def _scenario_model_stub_decode_failure(tmp_path: Path) -> str:
    reply = b'```json\n{"not":"vplot"}\n```'
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")

    with (
        patch.object(model_client, "_build_async_client", _model_client_builder(reply)),
        TestClient(app=create_app(settings)) as client,
    ):
        response = _propose(client)

    _expect_status(response, _HTTP_OK, "fenced non-VPlot proposal")
    body = _response_object(response, "fenced non-VPlot proposal")
    verdict = _object(body.get("verdict"), "fenced non-VPlot verdict")
    _require(body.get("model_reply") == reply.decode(), "failed model reply was not preserved")
    _require(verdict.get("verified") is False, "fenced non-VPlot reply unexpectedly verified")
    _require(verdict.get("layer") == "decode", "fenced reply did not fail at decode")
    _require("plot_id" not in verdict and "svg" not in verdict, "failed reply produced a chart")
    attempt = _read_attempt(settings, _attempt_id(verdict))
    _require(attempt.artifacts.model_reply == reply, "failed model reply was not archived")
    _require(attempt.artifacts.raw_spec == reply, "failed raw spec was not archived")
    return "fenced non-VPlot reply stayed a 200 decode verdict and durable failed attempt"


def _scenario_three_formal_obligations(tmp_path: Path) -> str:
    app = create_app(Settings(data_dir=_DATA, state_dir=tmp_path / "state"))
    required = {
        "sort.canonical_order",
        "scale.bar_zero",
        "encoding.legend_domain_exact",
    }
    with TestClient(app=app) as client:
        body = _render_verified(client, _three_obligation_spec())
        certificate = _certificate(client, app, cast("str", body["plot_id"]))

    observed = {check.id for check in certificate.checks if check.method == "z3_smt"}
    _require(required <= observed, "verified certificate omitted a required SMT obligation")
    _require(
        all(check.status == "pass" for check in certificate.checks), "certificate had a failure"
    )
    return "verified VCert retained sort, bar-zero, and legend-domain SMT obligations"


def _scenario_unknown_solver_fails_closed(tmp_path: Path) -> str:
    def unknown_solver(_solver: object) -> str:
        return "unknown"

    expected_obligations = (
        "sort.canonical_order",
        "scale.bar_zero",
        "encoding.legend_domain_exact",
    )
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    with (
        patch.object(formal, "_check_solver", unknown_solver),
        TestClient(app=create_app(settings)) as client,
    ):
        response = client.post(
            "/verify-and-render",
            content=_three_obligation_spec(),
            headers=_JSON,
        )

    _expect_status(response, _HTTP_OK, "forced-unknown solver verdict")
    body = _response_object(response, "forced-unknown solver verdict")
    _require(body.get("verified") is False, "unknown solver result verified")
    failures = [
        item
        for item in _object_list(body.get("results"), "solver verdict results")
        if item.get("check") == "formal.solver_completed"
    ]
    messages = {item.get("message") for item in failures}
    expected_messages = {
        f"SMT solver returned unknown or timed out while checking {obligation!r}"
        for obligation in expected_obligations
    }
    _require(messages == expected_messages, "unknown solver messages lost obligation context")
    _require(
        all(item.get("method") == "z3_smt" and item.get("status") == "fail" for item in failures),
        "unknown solver results did not carry z3_smt/fail metadata",
    )
    _require("plot_id" not in body and "svg" not in body, "unknown solver result produced a chart")
    return "all three forced-unknown SMT obligations failed closed with readable messages"


def _scenario_certificate_check_shape(tmp_path: Path) -> str:
    app = create_app(Settings(data_dir=_DATA, state_dir=tmp_path / "state"))
    with TestClient(app=app) as client:
        body = _render_verified(client, _three_obligation_spec())
        certificate = _certificate(client, app, cast("str", body["plot_id"]))

    triples = {(check.id, check.method, check.status) for check in certificate.checks}
    methods = {method for _check_id, method, _status in triples}
    _require("z3_smt" in methods, "fetched VCert omitted z3_smt method labels")
    _require(
        "deterministic_recompute" in methods,
        "fetched VCert omitted deterministic_recompute method labels",
    )
    _require(
        all(check_id and status == "pass" for check_id, _method, status in triples), "bad check"
    )
    return "fetched VCert exposed non-empty {id, method, status} check triples"


def _check_restart_replay(tmp_path: Path) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "restart-state")
    with TestClient(app=create_app(settings)) as first_client:
        plot_id = _render_plot(first_client)

    restarted_app = create_app(settings)
    with TestClient(app=restarted_app) as restarted_client:
        _expect_status(
            restarted_client.get(f"/chart/{plot_id}"),
            _HTTP_NOT_FOUND,
            "post-restart ephemeral chart",
        )
        certificate = _certificate(restarted_client, restarted_app, plot_id)
        _require(
            bool(certificate.dataset_hash), "independently fetched certificate lacked dataset hash"
        )
        replay = restarted_client.get(f"/replay/{plot_id}")
        _expect_status(replay, _HTTP_OK, "post-restart replay")
        replay_body = _response_object(replay, "post-restart replay")
        _require(replay_body.get("status") == "exact", "post-restart replay was not exact")
        _require(replay_body.get("integrity_ok") is True, "post-restart integrity failed")
        _require(replay_body.get("exact") is True, "post-restart replay did not reproduce exactly")
        chart = restarted_client.get(f"/chart/{plot_id}")
        _expect_status(chart, _HTTP_OK, "repopulated chart")
        _require(
            chart.headers.get("content-security-policy") == "sandbox allow-scripts",
            "repopulated chart lost its CSP",
        )
        _require(plot_id.encode() in chart.content, "repopulated chart bytes lost their plot id")


def _check_lru_archive_durability(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=_DATA,
        state_dir=tmp_path / "lru-state",
        html_cap=1,
        max_html_bytes=_CACHE_BYTES,
        chart_cache_bytes=_CACHE_BYTES,
    )
    app = create_app(settings)
    with TestClient(app=app) as client:
        first = _render_verified(client, _GOOD_SPEC.read_bytes())
        first_plot_id = cast("str", first["plot_id"])
        first_spec_id = cast("str", first["spec_id"])
        first_certificate_response = client.get(f"/certificate/{first_plot_id}")
        first_spec_response = client.get(f"/spec/{first_spec_id}")
        _expect_status(first_certificate_response, _HTTP_OK, "pre-eviction certificate")
        _expect_status(first_spec_response, _HTTP_OK, "pre-eviction spec")
        first_certificate = first_certificate_response.content
        first_spec = first_spec_response.content

        second = _render_verified(client, _SECOND_SPEC.read_bytes())
        second_plot_id = cast("str", second["plot_id"])
        _require(first_plot_id != second_plot_id, "LRU exercise produced duplicate plot ids")
        _expect_status(client.get(f"/chart/{first_plot_id}"), _HTTP_NOT_FOUND, "evicted chart")
        _expect_status(client.get(f"/chart/{second_plot_id}"), _HTTP_OK, "resident chart")
        _require(
            client.get(f"/certificate/{first_plot_id}").content == first_certificate,
            "LRU eviction changed the archived certificate",
        )
        _require(
            client.get(f"/spec/{first_spec_id}").content == first_spec,
            "LRU eviction changed the archived spec",
        )

    with TestClient(app=create_app(settings)) as restarted:
        _expect_status(restarted.get(f"/chart/{first_plot_id}"), _HTTP_NOT_FOUND, "restarted LRU")
        _require(
            restarted.get(f"/certificate/{first_plot_id}").content == first_certificate,
            "restart changed the LRU-evicted certificate",
        )
        _require(
            restarted.get(f"/spec/{first_spec_id}").content == first_spec,
            "restart changed the LRU-evicted spec",
        )


def _check_archived_dataset_replay(tmp_path: Path) -> None:
    data_dir = tmp_path / "mutable-data"
    data_dir.mkdir()
    source, manifest = _copy_sales_dataset(data_dir)
    settings = Settings(data_dir=data_dir, state_dir=tmp_path / "dataset-state")
    original_csv = source.read_bytes()

    with TestClient(app=create_app(settings)) as client:
        original = _render_verified(client, _GOOD_SPEC.read_bytes())
        mutated_csv = original_csv + b"2099-01,NA,1,1\n"
        source.write_bytes(mutated_csv)
        document = cast("dict[str, Any]", json.loads(_GOOD_SPEC.read_bytes()))
        dataset = cast("dict[str, Any]", document["dataset"])
        dataset["hash"] = canon.hash_dataset(mutated_csv)
        mutated = _render_verified(client, msgspec.json.encode(document))

    _require(
        original.get("dataset_hash") == canon.hash_dataset(original_csv), "original hash drifted"
    )
    _require(mutated.get("dataset_hash") == canon.hash_dataset(mutated_csv), "mutated hash drifted")
    _require(original.get("dataset_hash") != mutated.get("dataset_hash"), "CSV hashes collided")
    _require(manifest.is_file(), "copied schema manifest disappeared")
    source.unlink()

    expected_matches = {
        "dataset": True,
        "manifest": True,
        "spec": True,
        "plotted_table": True,
        "vega_lite": True,
    }
    with TestClient(app=create_app(settings)) as restarted:
        for plot_id in (cast("str", original["plot_id"]), cast("str", mutated["plot_id"])):
            replay = restarted.get(f"/replay/{plot_id}")
            _expect_status(replay, _HTTP_OK, "deleted-live-CSV replay")
            body = _response_object(replay, "deleted-live-CSV replay")
            _require(body.get("status") == "exact", "archived CSV replay was not exact")
            _require(
                body.get("artifact_matches") == expected_matches,
                "archived CSV replay artifact matches drifted",
            )
            _require(body.get("exact") is True, "archived CSV replay did not reproduce exactly")


def _scenario_restart_lru_and_archived_replay(tmp_path: Path) -> str:
    _check_restart_replay(tmp_path)
    _check_lru_archive_durability(tmp_path)
    _check_archived_dataset_replay(tmp_path)
    return "restart, LRU eviction, and deleted-live-CSV replay preserved durable artifacts"


def _scenario_distinct_dataset_certificate_hashes(tmp_path: Path) -> str:
    app = create_app(Settings(data_dir=_DATA, state_dir=tmp_path / "state"))
    with TestClient(app=app) as client:
        sales = _render_verified(client, _GOOD_SPEC.read_bytes())
        weather = _render_verified(client, _WEATHER_SPEC.read_bytes())
        sales_cert = _certificate(client, app, cast("str", sales["plot_id"]))
        weather_cert = _certificate(client, app, cast("str", weather["plot_id"]))

    _require(
        sales_cert.dataset_hash != weather_cert.dataset_hash, "dataset hashes were not distinct"
    )
    _require(
        sales_cert.dataset_hash == canon.hash_dataset((_DATA / "sales.csv").read_bytes()),
        "sales certificate hash did not bind sales.csv",
    )
    _require(
        weather_cert.dataset_hash == canon.hash_dataset((_DATA / "weather.csv").read_bytes()),
        "weather certificate hash did not bind weather.csv",
    )
    return "sales and weather fetched certificates bound distinct dataset hashes"


def _scenario_verifier_version_drift(tmp_path: Path) -> str:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    app = create_app(settings)
    expected_keys = {
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
    with TestClient(app=app) as client:
        plot_id = _render_plot(client)
        certificate = _certificate(client, app, plot_id)
        exact_response = client.get(f"/replay/{plot_id}")
        _expect_status(exact_response, _HTTP_OK, "exact replay")
        exact = _response_object(exact_response, "exact replay")
        _require(set(exact) == expected_keys, "replay response exposed an unexpected field")
        _require(exact.get("status") == "exact", "baseline replay was not exact")
        _require(exact.get("version_match") is True, "baseline verifier version did not match")
        _require(exact.get("drift") == [], "baseline replay reported drift")
        for forbidden in (
            b'"raw_csv"',
            b'"raw_manifest"',
            b'"raw_spec"',
            b'"prompt"',
            b'"snapshot"',
            b'"chart_html"',
            b'"svg"',
        ):
            _require(
                forbidden not in exact_response.content, "replay response disclosed raw artifacts"
            )

        with patch.object(render, "__version__", _DRIFT_VERSION):
            drift_response = client.get(f"/replay/{plot_id}")

    _expect_status(drift_response, _HTTP_OK, "version-drift replay")
    drift = _response_object(drift_response, "version-drift replay")
    _require(
        certificate.tcb.verifier_version != _DRIFT_VERSION, "VCert provenance was not archived"
    )
    _require(drift.get("status") == "drift", "version drift was not surfaced")
    _require(drift.get("integrity_ok") is True, "version drift incorrectly failed integrity")
    _require(drift.get("version_match") is False, "version drift incorrectly matched")
    _require(
        drift.get("drift")
        == [
            {
                "field": "verifier_version",
                "archived": certificate.tcb.verifier_version,
                "current": _DRIFT_VERSION,
            }
        ],
        "version-drift detail was not exact",
    )
    _require(drift.get("exact") is False, "version drift incorrectly claimed exact replay")
    return "VCert TCB provenance and bounded replay exposed verifier-version drift"


def _run_audit_cli(settings: Settings, argv: tuple[str, ...]) -> tuple[int, str]:
    capture = _StdoutCapture()
    with patch.object(Settings, "from_env", return_value=settings), redirect_stdout(capture):
        exit_code = service_main(argv)
    return exit_code, capture.output()


def _scenario_failed_attempt_audit_cli(tmp_path: Path) -> str:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    with TestClient(app=create_app(settings)) as client:
        success_response = client.post(
            "/verify-and-render",
            content=_GOOD_SPEC.read_bytes(),
            headers=_JSON,
        )
        failure_response = client.post("/verify-and-render", content=b"{", headers=_JSON)

    _expect_status(success_response, _HTTP_OK, "audit setup success")
    _expect_status(failure_response, _HTTP_OK, "audit setup failure")
    success = _response_object(success_response, "audit setup success")
    failure = _response_object(failure_response, "audit setup failure")
    success_id = _attempt_id(success)
    failure_id = _attempt_id(failure)
    _require(success_id != failure_id, "success and failure attempts shared an id")
    result = _object_list(failure.get("results"), "failed verdict results")[0]
    _require(failure.get("verified") is False, "audit failure unexpectedly verified")
    _require(failure.get("layer") == "decode", "audit failure was not a decode failure")
    _require(result.get("check") == "spec.decode", "audited check name drifted")
    _require(result.get("method") == "schema_validation", "audited method drifted")
    _require(result.get("severity") == "blocking", "audited severity drifted")
    failure_reason = result.get("message")
    _require(isinstance(failure_reason, str) and bool(failure_reason), "failure reason was empty")

    with TestClient(app=create_app(settings)) as restarted:
        _expect_status(
            restarted.get(f"/certificate/{success['plot_id']}"),
            _HTTP_OK,
            "post-restart certificate",
        )

    redacted = audit.audit_attempt(settings, failure_id)
    revealed = audit.audit_attempt(settings, failure_id, reveal_sensitive=True)
    _require(redacted == audit.audit_attempt(settings, failure_id), "redacted audit was unstable")
    _require(
        revealed == audit.audit_attempt(settings, failure_id, reveal_sensitive=True),
        "revealed audit was unstable",
    )
    redacted_document = _object(json.loads(redacted), "redacted audit")
    _require(redacted_document.get("disclosure") == "redacted", "default audit was not redacted")
    _require(b'"content"' not in redacted, "default audit disclosed content")

    default_code, default_output = _run_audit_cli(settings, ("audit", failure_id))
    _require(default_code == 0, "default audit CLI failed")
    _require('"content"' not in default_output, "default audit CLI disclosed content")
    default_document = _object(json.loads(default_output), "default audit CLI")
    attempt = _object(default_document.get("attempt"), "default audit CLI attempt")
    _require(attempt.get("id") == failure_id, "default audit CLI returned the wrong attempt")

    reveal_code, reveal_output = _run_audit_cli(
        settings,
        ("audit", failure_id, "--reveal-sensitive"),
    )
    _require(reveal_code == 0, "revealed audit CLI failed")
    _require(reveal_output.encode("ascii") == revealed, "revealed audit CLI bytes drifted")
    revealed_document = _object(json.loads(reveal_output), "revealed audit CLI")
    revealed_attempt = _object(revealed_document.get("attempt"), "revealed audit attempt")
    artifacts = _object_list(revealed_attempt.get("artifacts"), "revealed audit artifacts")
    verdict_artifact = next((item for item in artifacts if item.get("role") == "verdict"), None)
    _require(verdict_artifact is not None, "revealed audit omitted the verdict artifact")
    content = _object(cast("dict[str, Any]", verdict_artifact).get("content"), "verdict content")
    _require(content.get("encoding") == "utf-8", "revealed verdict encoding drifted")
    audited_verdict = _object(json.loads(cast("str", content["value"])), "audited verdict")
    audited_result = _object_list(audited_verdict.get("results"), "audited results")[0]
    _require(audited_result.get("message") == failure_reason, "audit lost the failure reason")
    return "real audit CLI stayed redacted by default and explained the durable failed attempt"


def _check_rotated_signer_guard(tmp_path: Path) -> None:
    state_dir = tmp_path / "rotated-state"
    with TestClient(app=create_app(Settings(data_dir=_DATA, state_dir=state_dir))) as first:
        plot_id = _render_plot(first)

    rotated = Settings(
        data_dir=_DATA,
        state_dir=state_dir,
        signing_key_file=state_dir / "rotated.key",
    )
    with TestClient(app=create_app(rotated)) as client:
        _expect_status(client.get(f"/chart/{plot_id}"), _HTTP_NOT_FOUND, "rotated-key chart")
        replay = client.get(f"/replay/{plot_id}")
        _expect_status(replay, _HTTP_OK, "rotated-key replay")
        body = _response_object(replay, "rotated-key replay")
        _require(body.get("status") == "untrusted_key", "rotated unpinned key was trusted")
        _require(body.get("integrity_ok") is False, "untrusted key claimed integrity")
        _require(body.get("exact") is False, "untrusted key claimed exact replay")
        _expect_status(client.get(f"/chart/{plot_id}"), _HTTP_NOT_FOUND, "untrusted replay chart")


def _check_schema_corruption_guard(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=_DATA, state_dir=tmp_path / "schema-state"))
    archive = cast("Archive", app.state["archive"])
    handler = _ListHandler()
    logger = logging.getLogger("verifier.service.app")
    propagate = logger.propagate

    with TestClient(app=app) as client:
        plot_id = _render_plot(client)
        with closing(sqlite3.connect(archive.database_path)) as connection:
            connection.execute("DROP INDEX attempts_by_plot")
            connection.commit()

        logger.addHandler(handler)
        logger.propagate = False
        previous_disable = logging.root.manager.disable
        logging.disable(logging.NOTSET)
        try:
            with patch.object(logging.getLogger("httpx"), "disabled", new=True):
                response = client.get(f"/replay/{plot_id}")
        finally:
            logging.disable(previous_disable)
            logger.propagate = propagate
            logger.removeHandler(handler)

    _expect_problem(
        response, _HTTP_INTERNAL_SERVER_ERROR, "the verifier encountered an internal error"
    )
    _require("attempts_by_plot" not in response.text, "schema error leaked through HTTP")
    _require(bool(handler.records), "schema corruption was not logged")
    record = handler.records[-1]
    _require(record.levelno == logging.ERROR, "schema corruption did not log at ERROR")
    _require(record.exc_info is not None, "schema corruption log omitted exception info")
    cause = cast("tuple[type[BaseException], BaseException, object]", record.exc_info)[1]
    _require(isinstance(cause, ArchiveSchemaError), "logged schema cause had the wrong type")
    _require(str(cause) not in response.text, "schema cause leaked through the problem response")


def _expect_immutable_sqlite(operation: Callable[[], object]) -> None:
    try:
        operation()
    except sqlite3.IntegrityError as exc:
        _require("immutable" in str(exc), "SQLite trigger rejected mutation for the wrong reason")
    else:
        detail = "SQLite archive mutation bypassed an immutable trigger"
        raise DemoError(detail)


def _check_blob_corruption_guard(tmp_path: Path) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "blob-state")
    archive = open_archive(settings)
    blob = BlobWrite(BlobKind.RAW_CSV, b"trusted")
    archive.publish(ArchiveBatch(blobs=(blob,)))

    with closing(sqlite3.connect(archive.database_path, autocommit=True)) as connection:
        _expect_immutable_sqlite(
            lambda: connection.execute(
                "UPDATE blobs SET content = ? WHERE digest = ?",
                (b"hostile", blob.ref.digest),
            )
        )
        _expect_immutable_sqlite(
            lambda: connection.execute("DELETE FROM blobs WHERE digest = ?", (blob.ref.digest,))
        )
        connection.execute("DROP TRIGGER blobs_reject_update")
        connection.execute(
            "UPDATE blobs SET content = ? WHERE digest = ?",
            (b"hostile", blob.ref.digest),
        )

    try:
        archive.read_blob(blob.ref, max_bytes=len(blob.payload))
    except ArchiveIntegrityError as exc:
        _require("digest verification" in str(exc), "blob corruption failed for the wrong reason")
    else:
        detail = "blob digest corruption was not detected"
        raise DemoError(detail)


def _check_attempt_signature_guard(tmp_path: Path) -> None:
    source_settings = Settings(data_dir=_DATA, state_dir=tmp_path / "signature-source")
    bundle = _render_attempt_bundle(source_settings)
    marker = b'"sig":"'
    signature_index = bundle.attempt_envelope.index(marker) + len(marker)
    original_byte = bundle.attempt_envelope[signature_index : signature_index + 1]
    replacement_byte = b"A" if original_byte != b"A" else b"B"
    tampered_envelope = (
        bundle.attempt_envelope[:signature_index]
        + replacement_byte
        + bundle.attempt_envelope[signature_index + 1 :]
    )
    tampered = replace(
        bundle,
        attempt_id=hashlib.sha256(tampered_envelope).hexdigest(),
        attempt_envelope=tampered_envelope,
    )

    target_settings = Settings(data_dir=_DATA, state_dir=tmp_path / "signature-target")
    target = open_archive(target_settings)
    try:
        target.publish_attempt(tampered, limits=target_settings.limits)
    except ArchiveIntegrityError:
        pass
    else:
        detail = "tampered attempt signature was published"
        raise DemoError(detail)
    _require(target.stats() == ArchiveStats(0, 0, 0, 0, 0), "signature failure mutated archive")


def _scenario_archive_integrity_guards(tmp_path: Path) -> str:
    _check_rotated_signer_guard(tmp_path)
    _check_schema_corruption_guard(tmp_path)
    _check_blob_corruption_guard(tmp_path)
    _check_attempt_signature_guard(tmp_path)
    return "rotated keys, schema damage, blob mutation, and signature tampering all failed closed"


def _scenario_capacity_and_quota_fail_closed(tmp_path: Path) -> str:
    capacity_app = create_app(
        Settings(
            data_dir=_DATA,
            state_dir=tmp_path / "capacity-state",
            max_active_jobs=1,
            work_rate_per_minute=10,
            work_burst=10,
        )
    )
    admission = cast("AdmissionController", capacity_app.state["admission"])
    held = admission.try_acquire()
    if held is None:
        detail = "demo could not acquire the capacity token used to exhaust admission"
        raise DemoError(detail)
    with TestClient(app=capacity_app) as client, held:
        capacity_response = client.get(f"/replay/{'0' * _ATTEMPT_ID_LENGTH}")
    _expect_problem(
        capacity_response,
        _HTTP_TOO_MANY_REQUESTS,
        "the process-local verifier work limit is currently exhausted",
    )

    cache_calls: list[str] = []

    def observe_chart(_store: ArtifactStore, _plot_id: str, _chart: bytes) -> None:
        cache_calls.append("chart")

    quota_settings = Settings(
        data_dir=_DATA,
        state_dir=tmp_path / "quota-state",
        max_archive_bytes=1,
    )
    with (
        patch.object(ArtifactStore, "put_chart", observe_chart),
        TestClient(app=create_app(quota_settings)) as client,
    ):
        quota_response = client.post(
            "/verify-and-render",
            content=_GOOD_SPEC.read_bytes(),
            headers=_JSON,
        )
    _expect_problem(
        quota_response,
        _HTTP_INSUFFICIENT_STORAGE,
        "the provenance archive has insufficient logical storage capacity",
    )
    _require("attempt_id" not in quota_response.json(), "quota failure published an attempt id")
    _require(cache_calls == [], "quota failure populated an ephemeral cache")
    _require(
        open_archive(quota_settings).stats() == ArchiveStats(0, 0, 0, 0, 0),
        "quota failure partially mutated the archive",
    )
    return "admission exhaustion returned 429 and archive quota returned atomic 507"


def _scenario_transaction_rollback(tmp_path: Path) -> str:
    bundle = _render_attempt_bundle(
        Settings(data_dir=_DATA, state_dir=tmp_path / "rollback-source")
    )
    rollback_settings = Settings(data_dir=_DATA, state_dir=tmp_path / "rollback-target")
    rollback_archive = open_archive(rollback_settings)

    class InjectedError(Exception):
        pass

    def fail() -> None:
        raise InjectedError

    with patch.object(archive_module, "_before_archive_commit", fail):
        try:
            rollback_archive.publish_attempt(bundle, limits=rollback_settings.limits)
        except InjectedError:
            pass
        else:
            detail = "injected pre-commit fault did not interrupt publication"
            raise DemoError(detail)
    _require(
        rollback_archive.stats() == ArchiveStats(0, 0, 0, 0, 0),
        "interrupted attempt publication left partial archive rows",
    )
    return "injected pre-commit fault rolled back every archive row"


_SCENARIOS: tuple[tuple[str, Scenario], ...] = (
    ("direct render + invalid UTF-8", _scenario_direct_render_and_invalid_utf8),
    ("model stub success", _scenario_model_stub_success),
    ("model stub decode failure", _scenario_model_stub_decode_failure),
    ("three formal obligations", _scenario_three_formal_obligations),
    ("unknown solver fail-closed", _scenario_unknown_solver_fails_closed),
    ("certificate check shape", _scenario_certificate_check_shape),
    ("restart + LRU + archived replay", _scenario_restart_lru_and_archived_replay),
    ("distinct dataset certificate hashes", _scenario_distinct_dataset_certificate_hashes),
    ("verifier-version drift", _scenario_verifier_version_drift),
    ("durable failed-attempt audit CLI", _scenario_failed_attempt_audit_cli),
    ("archive integrity guards", _scenario_archive_integrity_guards),
    ("capacity + quota fail-closed", _scenario_capacity_and_quota_fail_closed),
    ("transaction rollback", _scenario_transaction_rollback),
)


def run_walkthrough() -> WalkthroughReport:
    """Run every scenario independently and retain failures instead of aborting the walkthrough."""
    results: list[ScenarioResult] = []
    for name, scenario in _SCENARIOS:
        logging.disable(logging.CRITICAL)
        try:
            with TemporaryDirectory(prefix="figure-verification-demo-") as temp_dir:
                detail = scenario(Path(temp_dir))
        except Exception as exc:  # one failed scenario must never suppress the remaining evidence
            result = ScenarioResult(
                name=name,
                status="FAIL",
                detail=f"{type(exc).__name__}: {exc}",
            )
        else:
            result = ScenarioResult(name=name, status="PASS", detail=detail)
        finally:
            logging.disable(logging.NOTSET)
        results.append(result)
        _LOGGER.info("%s %s: %s", result.status, result.name, result.detail)

    passed = sum(result.status == "PASS" for result in results)
    failed = len(results) - passed
    status: ScenarioStatus = "PASS" if failed == 0 else "FAIL"
    return WalkthroughReport(
        generated_at=datetime.now(tz=UTC).isoformat(),
        status=status,
        passed=passed,
        failed=failed,
        total=len(results),
        results=tuple(results),
    )


def encode_report(report: WalkthroughReport) -> bytes:
    """Encode an indented JSON report with one trailing newline."""
    return msgspec.json.format(msgspec.json.encode(report), indent=2) + b"\n"
