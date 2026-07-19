# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M5.5d from-empty-state hardening capstone across formal, archive, audit, and replay."""

import hashlib
import json
import logging
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import httpx
import msgspec
import pytest
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

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_GOOD_SPEC = _ROOT / "examples" / "good_specs" / "g01_total_revenue_by_month.json"
_SECOND_SPEC = _ROOT / "examples" / "good_specs" / "g02_revenue_by_region.json"
_WEATHER_SPEC = _ROOT / "examples" / "good_specs" / "g07_temp_over_time_by_city.json"
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


def _install_model_handler(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    """Install the source-test MockTransport seam without opening a socket."""

    class Stream(httpx.AsyncByteStream):
        def __init__(self, content: bytes) -> None:
            self._content = content

        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield self._content

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

    monkeypatch.setattr(model_client, "_build_async_client", build)


def _install_model_reply(monkeypatch: pytest.MonkeyPatch, content: bytes) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        envelope = {"choices": [{"message": {"content": content.decode("utf-8")}}]}
        return httpx.Response(200, json=envelope)

    _install_model_handler(monkeypatch, handler)


def _propose(client: TestClient[Litestar]) -> httpx.Response:
    body = msgspec.json.encode(
        {"user_request": "Plot total revenue by month", "dataset_name": "sales.csv"}
    )
    return client.post("/propose-spec", content=body, headers=_JSON)


def _attempt_id(body: dict[str, Any]) -> str:
    attempt_id = body["attempt_id"]
    assert isinstance(attempt_id, str)
    assert len(attempt_id) == 64
    int(attempt_id, 16)
    return attempt_id


def _certificate(client: TestClient[Litestar], app: Litestar, plot_id: str) -> render.VCert:
    response = client.get(f"/certificate/{plot_id}")
    assert response.status_code == 200
    identity = cast("SigningIdentity", app.state["identity"])
    return attestation.verify_vcert(response.content, identity.trusted_keys).certificate


def _copy_sales_dataset(data_dir: Path) -> tuple[Path, Path]:
    source = data_dir / "sales.csv"
    manifest = data_dir / "schemas" / "sales.json"
    manifest.parent.mkdir()
    source.write_bytes((_DATA / "sales.csv").read_bytes())
    manifest.write_bytes((_DATA / "schemas" / "sales.json").read_bytes())
    return source, manifest


def _read_attempt(settings: Settings, attempt_id: str) -> AttemptBundle:
    archive = open_archive(settings)
    return archive.read_attempt(
        attempt_id,
        max_bytes=settings.max_archive_bytes,
        limits=settings.limits,
    )


def _render_attempt_bundle(settings: Settings) -> AttemptBundle:
    with TestClient(app=create_app(settings)) as client:
        response = client.post("/verify-and-render", content=_GOOD_SPEC.read_bytes(), headers=_JSON)
    assert response.status_code == 200
    body = cast("dict[str, Any]", response.json())
    assert body["verified"] is True
    return _read_attempt(settings, _attempt_id(body))


def _three_obligation_spec() -> bytes:
    """Derive one valid bar+sort+legend spec so every seed-13 SMT obligation applies."""
    document = cast("dict[str, Any]", json.loads(_GOOD_SPEC.read_bytes()))
    transforms = cast("list[dict[str, Any]]", document["transform"])
    transforms[0]["keys"] = ["month", "region"]
    encoding = cast("dict[str, Any]", document["encoding"])
    encoding["color"] = {"field": "region", "type": "nominal"}
    return msgspec.json.encode(document)


def test_01_direct_render_and_invalid_utf8_decode_contract(tmp_path: Path) -> None:
    """Direct render certifies formal methods; malformed UTF-8 stays a bounded verdict."""
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    app = create_app(settings)
    invalid = b'{"version":"\xff\xfe"}'

    with TestClient(app=app) as client:
        for route in ("/verify-only", "/verify-and-render"):
            response = client.post(route, content=invalid, headers=_JSON)
            assert response.status_code == 200
            body = cast("dict[str, Any]", response.json())
            assert body["verified"] is False
            assert body["layer"] == "decode"
            assert [item["check"] for item in body["results"]] == ["spec.decode"]
            assert "valid UTF-8" in cast("str", body["results"][0]["message"])

        formal_response = client.post(
            "/verify-and-render", content=_three_obligation_spec(), headers=_JSON
        )
        assert formal_response.status_code == 200
        formal_verdict = cast("dict[str, Any]", formal_response.json())
        assert formal_verdict["verified"] is True
        plot_id = cast("str", formal_verdict["plot_id"])
        certificate = _certificate(client, app, plot_id)  # Seed 14 route: /certificate/{id}.

    # Seed 13(a): one verified VCert retains all three required SMT-backed obligations.
    assert {check.id for check in certificate.checks if check.method == "z3_smt"} >= {
        "sort.canonical_order",
        "scale.bar_zero",
        "encoding.legend_domain_exact",
    }
    # Seed 13(c): the VCert distinguishes SMT from deterministic recomputation.
    assert {check.method for check in certificate.checks} >= {
        "z3_smt",
        "deterministic_recompute",
    }
    # Seed 13(c): certified checks carry the full {id, method, status} shape.
    assert all(check.status == "pass" for check in certificate.checks)


def test_02_model_stub_success_reaches_verified_chart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deterministic model reply traverses propose, verify, archive, and chart serving."""
    reply = _three_obligation_spec()
    _install_model_reply(monkeypatch, reply)
    app = create_app(Settings(data_dir=_DATA, state_dir=tmp_path / "state"))

    with TestClient(app=app) as client:
        response = _propose(client)
        assert response.status_code == 200
        payload = cast("list[Any]", response.json())
        result = cast("dict[str, Any]", payload[0])
        verdict = cast("dict[str, Any]", result["verdict"])
        assert result["model_reply"] == reply.decode("utf-8")
        assert verdict["verified"] is True
        plot_id = cast("str", verdict["plot_id"])
        assert client.get(f"/chart/{plot_id}").status_code == 200
        certificate = _certificate(client, app, plot_id)

    # Seeds 13(a,c): proposer success reaches the same method-bearing verified VCert.
    assert {check.id for check in certificate.checks if check.method == "z3_smt"} >= {
        "sort.canonical_order",
        "scale.bar_zero",
        "encoding.legend_domain_exact",
    }
    assert any(check.method == "deterministic_recompute" for check in certificate.checks)
    # Seed 13(c): certified checks carry the full {id, method, status} shape.
    assert all(check.status == "pass" for check in certificate.checks)


def test_03_model_stub_decode_failure_is_archived_without_chart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fenced non-VPlot reply is a captured 200 decode verdict, never a chart."""
    reply = b'```json\n{"not":"vplot"}\n```'
    _install_model_reply(monkeypatch, reply)
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")

    with TestClient(app=create_app(settings)) as client:
        response = _propose(client)
    assert response.status_code == 200
    body = cast("dict[str, Any]", response.json())
    verdict = cast("dict[str, Any]", body["verdict"])
    assert body["model_reply"] == reply.decode("utf-8")
    assert verdict["verified"] is False
    assert verdict["layer"] == "decode"
    assert "plot_id" not in verdict and "svg" not in verdict
    attempt = _read_attempt(settings, _attempt_id(verdict))
    # Seed 14(d) prerequisite: the failed model occurrence remains available for later audit.
    assert attempt.artifacts.model_reply == reply
    assert attempt.artifacts.raw_spec == reply


def test_04_restart_replay_repopulates_ephemeral_chart(tmp_path: Path) -> None:
    """A restart drops the chart LRU; exact replay rebuilds it from durable artifacts."""
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    with TestClient(app=create_app(settings)) as first_client:
        plot_id = _render_plot(first_client)

    restarted_app = create_app(settings)
    with TestClient(app=restarted_app) as restarted_client:
        assert restarted_client.get(f"/chart/{plot_id}").status_code == 404
        # Seed 14(a): the certificate independently re-verifies from the archive before replay.
        certificate = _certificate(restarted_client, restarted_app, plot_id)
        assert certificate.dataset_hash
        replay = restarted_client.get(f"/replay/{plot_id}")
        assert replay.status_code == 200
        body = cast("dict[str, Any]", replay.json())
        # Seed 14(a) + required /replay/{id}: stored artifacts reproduce the chart exactly.
        assert body["status"] == "exact"
        assert body["integrity_ok"] is True
        assert body["exact"] is True
        chart = restarted_client.get(f"/chart/{plot_id}")
        assert chart.status_code == 200
        assert chart.headers["content-security-policy"] == "sandbox allow-scripts"
        assert plot_id.encode() in chart.content


def test_05_lru_eviction_preserves_archive_certificate_and_spec(tmp_path: Path) -> None:
    """Count/byte-bounded LRUs evict a chart while the archive remains authoritative."""
    settings = Settings(
        data_dir=_DATA,
        state_dir=tmp_path / "state",
        store_cap=1,
        html_cap=1,
        max_html_bytes=2 * 1024 * 1024,
        chart_cache_bytes=2 * 1024 * 1024,
    )
    with TestClient(app=create_app(settings)) as client:
        first = cast(
            "dict[str, Any]",
            client.post(
                "/verify-and-render", content=_GOOD_SPEC.read_bytes(), headers=_JSON
            ).json(),
        )
        first_certificate = client.get(f"/certificate/{first['plot_id']}").content
        first_spec = client.get(f"/spec/{first['spec_id']}").content
        second = cast(
            "dict[str, Any]",
            client.post(
                "/verify-and-render", content=_SECOND_SPEC.read_bytes(), headers=_JSON
            ).json(),
        )
        assert first["plot_id"] != second["plot_id"]
        assert client.get(f"/chart/{first['plot_id']}").status_code == 404
        assert client.get(f"/chart/{second['plot_id']}").status_code == 200
        # Seed 14(a): LRU absence does not erase the stored reproduction inputs.
        assert client.get(f"/certificate/{first['plot_id']}").content == first_certificate
        assert client.get(f"/spec/{first['spec_id']}").content == first_spec

    with TestClient(app=create_app(settings)) as restarted:
        assert restarted.get(f"/chart/{first['plot_id']}").status_code == 404
        assert restarted.get(f"/certificate/{first['plot_id']}").content == first_certificate
        assert restarted.get(f"/spec/{first['spec_id']}").content == first_spec


def test_06_archived_replay_ignores_live_dataset_mutation_and_deletion(
    tmp_path: Path,
) -> None:
    """Two CSV snapshots hash distinctly and replay after the live source disappears."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    source, manifest = _copy_sales_dataset(data_dir)
    settings = Settings(data_dir=data_dir, state_dir=tmp_path / "state")
    original_csv = source.read_bytes()

    with TestClient(app=create_app(settings)) as client:
        original_response = client.post(
            "/verify-and-render", content=_GOOD_SPEC.read_bytes(), headers=_JSON
        )
        assert original_response.status_code == 200
        original = cast("dict[str, Any]", original_response.json())
        assert original["verified"] is True

        mutated_csv = original_csv + b"2099-01,NA,1,1\n"
        source.write_bytes(mutated_csv)
        mutated_document = cast("dict[str, Any]", json.loads(_GOOD_SPEC.read_bytes()))
        dataset = cast("dict[str, Any]", mutated_document["dataset"])
        dataset["hash"] = canon.hash_dataset(mutated_csv)
        mutated_response = client.post(
            "/verify-and-render", content=msgspec.json.encode(mutated_document), headers=_JSON
        )
        assert mutated_response.status_code == 200
        mutated = cast("dict[str, Any]", mutated_response.json())
        assert mutated["verified"] is True

    # Seed 14(b): byte-distinct CSV snapshots produce byte-distinct dataset hashes.
    assert original["dataset_hash"] == canon.hash_dataset(original_csv)
    assert mutated["dataset_hash"] == canon.hash_dataset(mutated_csv)
    assert original["dataset_hash"] != mutated["dataset_hash"]
    assert manifest.is_file()
    source.unlink()

    with TestClient(app=create_app(settings)) as restarted:
        for plot_id in (original["plot_id"], mutated["plot_id"]):
            replay = restarted.get(f"/replay/{plot_id}")
            body = cast("dict[str, Any]", replay.json())
            # Seed 14(a): replay uses archived snapshots, not the mutated/deleted live CSV.
            assert replay.status_code == 200
            assert body["status"] == "exact"
            assert body["artifact_matches"] == {
                "dataset": True,
                "manifest": True,
                "spec": True,
                "plotted_table": True,
                "vega_lite": True,
            }
            assert body["exact"] is True


def test_06b_distinct_datasets_bind_distinct_fetched_certificate_hashes(
    tmp_path: Path,
) -> None:
    """Fetched certificates bind hashes from two genuinely distinct datasets."""
    app = create_app(Settings(data_dir=_DATA, state_dir=tmp_path / "state"))

    with TestClient(app=app) as client:
        sales_response = client.post(
            "/verify-and-render", content=_GOOD_SPEC.read_bytes(), headers=_JSON
        )
        weather_response = client.post(
            "/verify-and-render", content=_WEATHER_SPEC.read_bytes(), headers=_JSON
        )
        assert sales_response.status_code == 200
        assert weather_response.status_code == 200
        sales = cast("dict[str, Any]", sales_response.json())
        weather = cast("dict[str, Any]", weather_response.json())
        assert sales["verified"] is True
        assert weather["verified"] is True
        sales_cert = _certificate(client, app, cast("str", sales["plot_id"]))
        weather_cert = _certificate(client, app, cast("str", weather["plot_id"]))

    # Seed 14(b): two distinct datasets bind distinct fetched-certificate dataset hashes.
    assert sales_cert.dataset_hash != weather_cert.dataset_hash
    assert sales_cert.dataset_hash == canon.hash_dataset((_DATA / "sales.csv").read_bytes())
    assert weather_cert.dataset_hash == canon.hash_dataset((_DATA / "weather.csv").read_bytes())


def test_07_replay_is_bounded_and_reports_verifier_version_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay exposes bounded equality/drift metadata, never stored raw artifacts."""
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    app = create_app(settings)
    with TestClient(app=app) as client:
        plot_id = _render_plot(client)
        certificate = _certificate(client, app, plot_id)
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
        # Seed 14(a): the bounded verdict reports an exact stored-artifact reproduction.
        assert body["status"] == "exact"
        assert body["integrity_ok"] is True
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
        assert body["exact"] is True  # SVG equality remains diagnostic-only.
        for forbidden in (
            b'"raw_csv"',
            b'"raw_manifest"',
            b'"raw_spec"',
            b'"prompt"',
            b'"snapshot"',
            b'"chart_html"',
            b'"svg"',
        ):
            assert forbidden not in response.content

        with monkeypatch.context() as drift_patch:
            drift_patch.setattr(render, "__version__", "capstone-drift")
            drift_response = client.get(f"/replay/{plot_id}")

    drift = cast("dict[str, Any]", drift_response.json())
    # Seed 14(c): VCert TCB provenance and replay identify verifier-version drift explicitly.
    assert certificate.tcb.verifier_version != "capstone-drift"
    assert drift["status"] == "drift"
    assert drift["integrity_ok"] is True
    assert drift["artifact_matches"] == body["artifact_matches"]
    assert drift["version_match"] is False
    assert drift["drift"] == [
        {
            "field": "verifier_version",
            "archived": certificate.tcb.verifier_version,
            "current": "capstone-drift",
        }
    ]
    assert drift["exact"] is False


def test_08_failed_attempt_audit_survives_restart_and_explains_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Direct API and actual CLI audit one durable failed occurrence without unsafe defaults."""
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    with TestClient(app=create_app(settings)) as client:
        success_response = client.post(
            "/verify-and-render", content=_GOOD_SPEC.read_bytes(), headers=_JSON
        )
        failure_response = client.post("/verify-and-render", content=b"{", headers=_JSON)

    success = cast("dict[str, Any]", success_response.json())
    failure = cast("dict[str, Any]", failure_response.json())
    success_id = _attempt_id(success)
    failure_id = _attempt_id(failure)
    assert success_id != failure_id
    failure_reason = cast("str", failure["results"][0]["message"])
    assert failure_reason

    with TestClient(app=create_app(settings)) as restarted:
        assert restarted.get(f"/certificate/{success['plot_id']}").status_code == 200

    redacted = audit.audit_attempt(settings, failure_id)
    assert redacted == audit.audit_attempt(settings, failure_id)
    revealed = audit.audit_attempt(settings, failure_id, reveal_sensitive=True)
    assert revealed == audit.audit_attempt(settings, failure_id, reveal_sensitive=True)
    redacted_document = cast("dict[str, Any]", json.loads(redacted))
    assert redacted_document["disclosure"] == "redacted"
    assert b'"content"' not in redacted

    monkeypatch.setattr(Settings, "from_env", staticmethod(lambda: settings))
    capfd.readouterr()
    assert service_main(("audit", failure_id)) == 0
    default_cli = capfd.readouterr()
    assert default_cli.err == ""
    assert '"content"' not in default_cli.out
    default_document = cast("dict[str, Any]", json.loads(default_cli.out))
    assert default_document["attempt"]["id"] == failure_id

    assert service_main(("audit", failure_id, "--reveal-sensitive")) == 0
    revealed_cli = capfd.readouterr()
    assert revealed_cli.err == ""
    assert revealed_cli.out.encode("ascii") == revealed
    revealed_document = cast("dict[str, Any]", json.loads(revealed_cli.out))
    artifacts = cast("list[dict[str, Any]]", revealed_document["attempt"]["artifacts"])
    verdict_artifact = next(item for item in artifacts if item["role"] == "verdict")
    content = cast("dict[str, Any]", verdict_artifact["content"])
    assert content["encoding"] == "utf-8"
    audited_verdict = cast("dict[str, Any]", json.loads(cast("str", content["value"])))
    # Seed 14(d): the authenticated retained verdict explains the failed attempt after restart.
    assert audited_verdict["results"][0]["message"] == failure_reason


def test_09_rotated_signer_is_untrusted_without_an_explicit_pin(tmp_path: Path) -> None:
    """Archived public material is self-consistency evidence, not a trust anchor."""
    state_dir = tmp_path / "state"
    with TestClient(app=create_app(Settings(data_dir=_DATA, state_dir=state_dir))) as first:
        plot_id = _render_plot(first)

    rotated = Settings(
        data_dir=_DATA,
        state_dir=state_dir,
        signing_key_file=state_dir / "rotated.key",
    )
    with TestClient(app=create_app(rotated)) as client:
        assert client.get(f"/chart/{plot_id}").status_code == 404
        response = client.get(f"/replay/{plot_id}")
        assert response.status_code == 200
        body = cast("dict[str, Any]", response.json())
        # Seed 14(a) trust guard: unpinned archived keys cannot claim successful reproduction.
        assert body["status"] == "untrusted_key"
        assert body["integrity_ok"] is False
        assert body["exact"] is False
        assert client.get(f"/chart/{plot_id}").status_code == 404


def test_10_sqlite_schema_corruption_is_logged_and_returns_generic_500(
    tmp_path: Path,
) -> None:
    """Replay fails closed on schema damage without disclosing the SQLite cause."""
    app = create_app(Settings(data_dir=_DATA, state_dir=tmp_path / "state"))
    archive = cast("Archive", app.state["archive"])
    handler = _ListHandler()
    logger = logging.getLogger("verifier.service.app")

    with TestClient(app=app) as client:
        plot_id = _render_plot(client)
        with closing(sqlite3.connect(archive.database_path)) as connection:
            connection.execute("DROP INDEX attempts_by_plot")
            connection.commit()

        logger.addHandler(handler)
        try:
            response = client.get(f"/replay/{plot_id}")
        finally:
            logger.removeHandler(handler)

    # Seed 14(a) integrity guard: corrupted storage never masquerades as a replay result.
    _assert_problem(response, 500, "the verifier encountered an internal error")
    assert "attempts_by_plot" not in response.text
    assert handler.records
    record = handler.records[-1]
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
    cause = record.exc_info[1]
    assert isinstance(cause, ArchiveSchemaError)
    assert str(cause) and str(cause) not in response.text


def test_11_blob_corruption_is_detected_after_immutable_trigger_bypass(
    tmp_path: Path,
) -> None:
    """Archive triggers reject ordinary mutation; streamed digest verification catches bypass."""
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    archive = open_archive(settings)
    blob = BlobWrite(BlobKind.RAW_CSV, b"trusted")
    archive.publish(ArchiveBatch(blobs=(blob,)))

    with closing(sqlite3.connect(archive.database_path, autocommit=True)) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE blobs SET content = ? WHERE digest = ?",
                (b"hostile", blob.ref.digest),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM blobs WHERE digest = ?", (blob.ref.digest,))
        connection.execute("DROP TRIGGER blobs_reject_update")
        connection.execute(
            "UPDATE blobs SET content = ? WHERE digest = ?",
            (b"hostile", blob.ref.digest),
        )

    # Seed 14(a) integrity guard: corrupted snapshot bytes fail before replay can use them.
    with pytest.raises(ArchiveIntegrityError, match="digest verification"):
        archive.read_blob(blob.ref, max_bytes=len(blob.payload))


def test_12_attempt_signature_corruption_fails_before_archive_mutation(
    tmp_path: Path,
) -> None:
    """A canonical DSSE envelope with one changed signature byte is rejected atomically."""
    source_settings = Settings(data_dir=_DATA, state_dir=tmp_path / "source")
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
    assert tampered_envelope != bundle.attempt_envelope
    tampered = replace(
        bundle,
        attempt_id=hashlib.sha256(tampered_envelope).hexdigest(),
        attempt_envelope=tampered_envelope,
    )

    target_settings = Settings(data_dir=_DATA, state_dir=tmp_path / "target")
    target = open_archive(target_settings)
    # Seed 14(d) authentication guard: a modified occurrence cannot become auditable history.
    with pytest.raises(ArchiveIntegrityError):
        target.publish_attempt(tampered, limits=target_settings.limits)
    assert target.stats() == ArchiveStats(0, 0, 0, 0, 0)


def test_13_solver_capacity_quota_and_transaction_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown SMT, admission exhaustion, archive quota, and commit faults all fail closed."""
    with monkeypatch.context() as solver_patch:
        solver_patch.setattr(formal, "_check_solver", lambda _solver: "unknown")
        solver_settings = Settings(data_dir=_DATA, state_dir=tmp_path / "solver")
        with TestClient(app=create_app(solver_settings)) as client:
            response = client.post(
                "/verify-and-render", content=_three_obligation_spec(), headers=_JSON
            )
        assert response.status_code == 200
        solver_body = cast("dict[str, Any]", response.json())
        assert solver_body["verified"] is False
        solver_fails = [
            item for item in solver_body["results"] if item["check"] == "formal.solver_completed"
        ]
        # Seed 13(b): every forced-unknown obligation yields the exact readable HTTP message.
        assert {item["message"] for item in solver_fails} == {
            f"SMT solver returned unknown or timed out while checking {obligation!r}"
            for obligation in (
                "sort.canonical_order",
                "scale.bar_zero",
                "encoding.legend_domain_exact",
            )
        }
        assert all(item["method"] == "z3_smt" and item["status"] == "fail" for item in solver_fails)
        assert "plot_id" not in solver_body and "svg" not in solver_body

    capacity_app = create_app(
        Settings(
            data_dir=_DATA,
            state_dir=tmp_path / "capacity",
            max_active_jobs=1,
            work_rate_per_minute=10,
            work_burst=10,
        )
    )
    admission = cast("AdmissionController", capacity_app.state["admission"])
    held = admission.try_acquire()
    assert held is not None
    with TestClient(app=capacity_app) as client, held:
        capacity_response = client.get(f"/replay/{'0' * 64}")
    _assert_problem(
        capacity_response,
        429,
        "the process-local verifier work limit is currently exhausted",
    )

    cache_calls: list[str] = []

    def observe_render(_store: ArtifactStore, **_kwargs: object) -> None:
        cache_calls.append("render")

    def observe_chart(_store: ArtifactStore, _plot_id: str, _chart: bytes) -> None:
        cache_calls.append("chart")

    quota_settings = Settings(
        data_dir=_DATA,
        state_dir=tmp_path / "quota",
        max_archive_bytes=1,
    )
    with monkeypatch.context() as quota_patch:
        quota_patch.setattr(ArtifactStore, "put", observe_render)
        quota_patch.setattr(ArtifactStore, "put_chart", observe_chart)
        with TestClient(app=create_app(quota_settings)) as client:
            quota_response = client.post(
                "/verify-and-render", content=_GOOD_SPEC.read_bytes(), headers=_JSON
            )
    _assert_problem(
        quota_response,
        507,
        "the provenance archive has insufficient logical storage capacity",
    )
    assert "attempt_id" not in quota_response.json()
    assert cache_calls == []
    assert open_archive(quota_settings).stats() == ArchiveStats(0, 0, 0, 0, 0)

    bundle = _render_attempt_bundle(
        Settings(data_dir=_DATA, state_dir=tmp_path / "rollback-source")
    )
    rollback_settings = Settings(data_dir=_DATA, state_dir=tmp_path / "rollback-target")
    rollback_archive = open_archive(rollback_settings)

    class InjectedError(Exception):
        pass

    def fail() -> None:
        raise InjectedError

    with monkeypatch.context() as rollback_patch:
        rollback_patch.setattr(archive_module, "_before_archive_commit", fail)
        with pytest.raises(InjectedError):
            rollback_archive.publish_attempt(bundle, limits=rollback_settings.limits)
    # Seed 14(a,d) durability guard: an interrupted all-row publish leaves no partial history.
    assert rollback_archive.stats() == ArchiveStats(0, 0, 0, 0, 0)
