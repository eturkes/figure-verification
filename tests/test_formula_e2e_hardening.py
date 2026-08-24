# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""From-empty-state formula capstone: verify, restart, replay, and the archived retrieval routes.

The shipped formula suites each pin one layer. This file pins the JOIN no other committed test
makes: an empty state directory, a verified occurrence over HTTP, a NEW app instance over that
SAME directory, and the durable reads that survive it. Both entry routes are covered — direct
`/verify-formula` and the model-proposed `/propose-formula` — because the proposer adds no
verification stage and must therefore reach an identical durable occurrence.

`/chart` stays 404 throughout: the verifier AUTHORS the matplotlib script and never executes it,
so formula replay repopulates nothing. `/table` and `/script` serve typed-relation, digest-addressed
bytes; their digests are DOMAIN-TAGGED, never a raw SHA-256 of the body.
"""

import hashlib
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import httpx
import msgspec
import pytest
from litestar import Litestar
from litestar.testing import TestClient

from demo import formula_walkthrough
from demo.walkthrough import DemoError, WalkthroughReport
from verifier import attestation, canon, vcert
from verifier.service import model_client
from verifier.service.app import create_app
from verifier.service.archive import AttemptOutcome, AttemptRoute, open_archive
from verifier.service.identity import SigningIdentity
from verifier.service.settings import Settings

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_FORMULA_SPEC = _ROOT / "examples" / "formula_good_specs" / "f02_linear.json"
_JSON = {"content-type": "application/json"}
_PROBLEM_JSON = "application/problem+json"
_REPORT_PATH = _ROOT / "demo" / "reports" / "formula_report.json"
_DRIVER_TIMEOUT_S = 180.0
_USER_REQUEST = "Plot the line 2x + 1 from 0 to 10"

# Hand-stated closed sets. A test that derives its expectation from the production constant pins
# nothing about that constant.
_HASH_FIELDS = ("formula_hash", "spec_hash", "plotted_table_hash", "matplotlib_script_hash")
_REPLAY_KEYS = {
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
_ARTIFACT_MATCHES = {
    "formula": True,
    "spec": True,
    "plotted_table": True,
    "matplotlib_script": True,
}
_CERTIFIED_METHODS = {"construction", "deterministic_recompute", "z3_smt"}
_INJECTED_FAULT = "injected scenario fault"
_CHECK_FIELDS = ("id", "method", "status")
_SCENARIO_NAMES = {
    "formula direct flow",
    "formula proposed flow",
    "formula certificate check shape",
}
# Hand-stated so a later rewrite cannot quietly upgrade a hedged claim into one the run never
# establishes. `/table` and `/script` are digest-addressed, so no detail may call them
# authenticated.
_SCENARIO_DETAILS = {
    "direct formula verify, restart, exact replay, certificate-matched table and script",
    "stubbed formula proposal verified, archived, and replayed exactly after a restart",
    "fetched VCert v0.3 exposed non-empty {id, method, status} triples across three methods",
}
_FORGED_DIGEST = "sha256:" + "0" * 64


def _settings(tmp_path: Path, name: str) -> Settings:
    """Build settings over a state directory that does not yet exist: a true first boot."""
    state_dir = tmp_path / name
    assert not state_dir.exists()
    return Settings(data_dir=_DATA, state_dir=state_dir)


def _reopened(settings: Settings) -> Settings:
    """A FRESH Settings over the same path, so a reused object cannot satisfy a restart."""
    return Settings(data_dir=_DATA, state_dir=settings.state_dir)


def _install_model_reply(monkeypatch: pytest.MonkeyPatch, content: bytes) -> None:
    """Install the socket-free MockTransport seam, leaving the real proposer path in play."""

    class Stream(httpx.AsyncByteStream):
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield self._payload

    def handler(_request: httpx.Request) -> httpx.Response:
        envelope = {"choices": [{"message": {"content": content.decode("utf-8")}}]}
        return httpx.Response(200, json=envelope)

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


def _verify_formula(client: TestClient[Litestar]) -> dict[str, Any]:
    response = client.post("/verify-formula", content=_FORMULA_SPEC.read_bytes(), headers=_JSON)
    assert response.status_code == 200
    body = cast("dict[str, Any]", response.json())
    assert body["verified"] is True
    assert body["layer"] == "verify"
    return body


def _propose_formula(client: TestClient[Litestar]) -> dict[str, Any]:
    request = msgspec.json.encode({"user_request": _USER_REQUEST})
    response = client.post("/propose-formula", content=request, headers=_JSON)
    assert response.status_code == 200
    result = cast("dict[str, Any]", response.json())
    assert result["model_reply"] == _FORMULA_SPEC.read_bytes().decode()
    body = cast("dict[str, Any]", result["verdict"])
    assert body["verified"] is True
    return body


def _hash_fields(body: dict[str, Any]) -> tuple[str, ...]:
    """Read the four certified digests. There is no fifth, and the order is part of the shape."""
    assert tuple(name for name in body if name.endswith("_hash")) == _HASH_FIELDS
    values = tuple(cast("str", body[name]) for name in _HASH_FIELDS)
    assert all(value.startswith("sha256:") for value in values)
    return values


def _certificate(
    client: TestClient[Litestar], app: Litestar, plot_id: str
) -> tuple[bytes, vcert.VCertV03]:
    response = client.get(f"/certificate/{plot_id}")
    assert response.status_code == 200
    identity = cast("SigningIdentity", app.state["identity"])
    verified = attestation.verify_vcert_v03(response.content, identity.trusted_keys)
    return response.content, verified.certificate


def _certified_bindings(certificate: vcert.VCertV03) -> tuple[str, ...]:
    source = certificate.source
    artifact = certificate.artifact
    assert type(source) is vcert.FormulaSourceCert
    assert type(artifact) is vcert.MatplotlibScriptArtifactCert
    return (
        source.formula_hash,
        certificate.spec_hash,
        certificate.plotted_table_hash,
        artifact.matplotlib_script_hash,
    )


def _replay(client: TestClient[Litestar], plot_id: str) -> dict[str, Any]:
    response = client.get(f"/replay/{plot_id}")
    assert response.status_code == 200
    return cast("dict[str, Any]", response.json())


def _table(client: TestClient[Litestar], plot_id: str) -> bytes:
    response = client.get(f"/table/{plot_id}")
    assert response.status_code == 200
    return response.content


def _script(client: TestClient[Litestar], plot_id: str) -> bytes:
    response = client.get(f"/script/{plot_id}")
    assert response.status_code == 200
    return response.content


def _assert_no_chart(client: TestClient[Litestar], plot_id: str) -> None:
    response = client.get(f"/chart/{plot_id}")
    assert response.status_code == 404
    assert response.headers["content-type"] == _PROBLEM_JSON
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.json() == {"title": "Not Found", "status": 404, "detail": "no such artifact"}


def _assert_exact_replay(body: dict[str, Any]) -> None:
    assert set(body) == _REPLAY_KEYS
    assert body["status"] == "exact"
    assert body["integrity_ok"] is True
    assert body["artifact_matches"] == _ARTIFACT_MATCHES
    assert body["payload_match"] is True
    assert body["version_match"] is True
    assert body["drift"] == []
    assert body["exact"] is True
    assert body["failure_stage"] is None
    assert cast("str", body["trusted_keyid"]).startswith("sha256:")


def _assert_verified_occurrence(
    settings: Settings, body: dict[str, Any], route: AttemptRoute
) -> None:
    attempt = open_archive(settings).read_attempt(
        cast("str", body["attempt_id"]),
        max_bytes=settings.max_archive_bytes,
        limits=settings.limits,
    )
    assert attempt.manifest.route is route
    assert attempt.manifest.outcome is AttemptOutcome.VERIFIED


def test_direct_verify_formula_from_empty_state_certifies_four_hashes(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "direct")
    app = create_app(settings)
    with TestClient(app=app) as client:
        body = _verify_formula(client)
        published = _hash_fields(body)
        _envelope, certificate = _certificate(client, app, cast("str", body["plot_id"]))

    assert published == _certified_bindings(certificate)
    _assert_verified_occurrence(settings, body, AttemptRoute.VERIFY_FORMULA)


def test_direct_formula_replay_after_restart_is_exact(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "direct-replay")
    with TestClient(app=create_app(settings)) as client:
        body = _verify_formula(client)
        plot_id = cast("str", body["plot_id"])
        published = _hash_fields(body)

    with TestClient(app=create_app(_reopened(settings))) as restarted:
        _assert_exact_replay(_replay(restarted, plot_id))
        assert canon.hash_table_bytes(_table(restarted, plot_id)) == published[2]
        assert canon.hash_matplotlib_script(_script(restarted, plot_id)) == published[3]


def test_formula_replay_body_carries_no_artifact_bytes_or_signature(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "replay-disclosure")
    app = create_app(settings)
    with TestClient(app=app) as client:
        body = _verify_formula(client)
        plot_id = cast("str", body["plot_id"])
        envelope, _certificate_payload = _certificate(client, app, plot_id)
        table_bytes = _table(client, plot_id)
        script_bytes = _script(client, plot_id)

    with TestClient(app=create_app(_reopened(settings))) as restarted:
        response = restarted.get(f"/replay/{plot_id}")
    assert response.status_code == 200
    assert set(cast("dict[str, Any]", response.json())) == _REPLAY_KEYS

    signature = cast("dict[str, Any]", msgspec.json.decode(envelope))["signatures"][0]["sig"]
    raw = response.content
    assert script_bytes not in raw
    assert table_bytes not in raw
    assert signature.encode() not in raw


def test_direct_formula_table_bytes_match_certified_digest(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "table")
    with TestClient(app=create_app(settings)) as client:
        plot_id = cast("str", _verify_formula(client)["plot_id"])

    restarted_app = create_app(_reopened(settings))
    with TestClient(app=restarted_app) as restarted:
        table_bytes = _table(restarted, plot_id)
        _envelope, certificate = _certificate(restarted, restarted_app, plot_id)

    assert canon.hash_table_bytes(table_bytes) == certificate.plotted_table_hash
    # The certified digest is domain-tagged, so a raw body digest is a DIFFERENT value.
    assert hashlib.sha256(table_bytes).hexdigest() not in certificate.plotted_table_hash


def test_direct_formula_script_bytes_match_certified_digest(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "script")
    with TestClient(app=create_app(settings)) as client:
        plot_id = cast("str", _verify_formula(client)["plot_id"])

    restarted_app = create_app(_reopened(settings))
    with TestClient(app=restarted_app) as restarted:
        script_bytes = _script(restarted, plot_id)
        _envelope, certificate = _certificate(restarted, restarted_app, plot_id)

    artifact = certificate.artifact
    assert type(artifact) is vcert.MatplotlibScriptArtifactCert
    assert canon.hash_matplotlib_script(script_bytes) == artifact.matplotlib_script_hash
    assert hashlib.sha256(script_bytes).hexdigest() not in artifact.matplotlib_script_hash


def test_direct_formula_chart_is_404_before_and_after_restart(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "direct-chart")
    with TestClient(app=create_app(settings)) as client:
        plot_id = cast("str", _verify_formula(client)["plot_id"])
        _assert_no_chart(client, plot_id)

    with TestClient(app=create_app(_reopened(settings))) as restarted:
        _assert_no_chart(restarted, plot_id)
        _assert_exact_replay(_replay(restarted, plot_id))
        # Dataset replay repopulates the chart LRU. Formula replay must not.
        _assert_no_chart(restarted, plot_id)


def test_proposed_formula_stub_verifies_and_signs_occurrence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reply = _FORMULA_SPEC.read_bytes()
    _install_model_reply(monkeypatch, reply)
    settings = _settings(tmp_path, "proposed")
    app = create_app(settings)
    with TestClient(app=app) as client:
        body = _propose_formula(client)
        published = _hash_fields(body)
        _envelope, certificate = _certificate(client, app, cast("str", body["plot_id"]))

    assert published == _certified_bindings(certificate)
    _assert_verified_occurrence(settings, body, AttemptRoute.PROPOSE_FORMULA)
    attempt = open_archive(settings).read_attempt(
        cast("str", body["attempt_id"]),
        max_bytes=settings.max_archive_bytes,
        limits=settings.limits,
    )
    assert attempt.artifacts.model_reply == reply
    assert attempt.artifacts.raw_spec == reply


def test_proposed_formula_survives_restart_replay_and_artifact_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_model_reply(monkeypatch, _FORMULA_SPEC.read_bytes())
    settings = _settings(tmp_path, "proposed-replay")
    with TestClient(app=create_app(settings)) as client:
        body = _propose_formula(client)
        plot_id = cast("str", body["plot_id"])
        published = _hash_fields(body)

    with TestClient(app=create_app(_reopened(settings))) as restarted:
        _assert_exact_replay(_replay(restarted, plot_id))
        assert canon.hash_table_bytes(_table(restarted, plot_id)) == published[2]
        assert canon.hash_matplotlib_script(_script(restarted, plot_id)) == published[3]


def test_proposed_formula_chart_is_404_before_and_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_model_reply(monkeypatch, _FORMULA_SPEC.read_bytes())
    settings = _settings(tmp_path, "proposed-chart")
    with TestClient(app=create_app(settings)) as client:
        plot_id = cast("str", _propose_formula(client)["plot_id"])
        _assert_no_chart(client, plot_id)

    with TestClient(app=create_app(_reopened(settings))) as restarted:
        _assert_no_chart(restarted, plot_id)
        _assert_exact_replay(_replay(restarted, plot_id))
        _assert_no_chart(restarted, plot_id)


def test_formula_certificate_exposes_exact_id_method_status_triples(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "cert-shape")
    app = create_app(settings)
    with TestClient(app=app) as client:
        body = _verify_formula(client)
        _envelope, certificate = _certificate(client, app, cast("str", body["plot_id"]))

    assert vcert.CertifiedCheck.__struct_fields__ == _CHECK_FIELDS
    assert certificate.checks
    assert all(check.id for check in certificate.checks)
    assert {check.status for check in certificate.checks} == {"pass"}


def test_formula_certificate_methods_are_the_exact_declared_set(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "cert-methods")
    app = create_app(settings)
    with TestClient(app=app) as client:
        body = _verify_formula(client)
        _envelope, certificate = _certificate(client, app, cast("str", body["plot_id"]))

    assert {check.method for check in certificate.checks} == _CERTIFIED_METHODS


def test_archived_bytes_are_matched_against_the_authenticated_certificate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The comparison authority must be the fetched VCert, never the unsigned POST verdict.

    Forging one digest inside the authenticated certificate has to fail the scenario. A
    walkthrough that compares archived bytes against the verdict's own `*_hash` fields passes
    this mutation, because those fields carry no signature and nothing cross-checks them.
    """
    control = tmp_path / "control"
    forged_root = tmp_path / "forged"
    control.mkdir()
    forged_root.mkdir()

    assert formula_walkthrough._scenario_formula_direct_flow(control)
    real = formula_walkthrough._certificate

    def forged(client: TestClient[Litestar], app: Litestar, plot_id: str) -> vcert.VCertV03:
        certificate = real(client, app, plot_id)
        return msgspec.structs.replace(certificate, plotted_table_hash=_FORGED_DIGEST)

    monkeypatch.setattr(formula_walkthrough, "_certificate", forged)
    with pytest.raises(DemoError) as caught:
        formula_walkthrough._scenario_formula_direct_flow(forged_root)

    assert "authenticated certificate" in str(caught.value)


def test_formula_walkthrough_runs_every_scenario_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    report = formula_walkthrough.run_formula_walkthrough()
    assert report.status == "PASS"
    assert (report.total, report.passed, report.failed) == (3, 3, 0)
    assert {result.name for result in report.results} == _SCENARIO_NAMES
    assert all(result.status == "PASS" for result in report.results)
    assert {result.detail for result in report.results} == _SCENARIO_DETAILS
    assert not [result for result in report.results if "authenticated" in result.detail]

    def boom(_tmp_path: Path) -> str:
        raise RuntimeError(_INJECTED_FAULT)

    # main() logs the report path relative to the repo root, so the failure arm writes inside the
    # gitignored reports directory under its own name rather than into a temporary directory.
    failure_report = _REPORT_PATH.with_name("formula_report_failure_arm.json")
    survivors = (("injected failure", boom), *formula_walkthrough._FORMULA_SCENARIOS)
    monkeypatch.setattr(formula_walkthrough, "_FORMULA_SCENARIOS", survivors)
    monkeypatch.setattr(formula_walkthrough, "_REPORT_PATH", failure_report)
    try:
        assert formula_walkthrough.main() == 1
        written = msgspec.json.Decoder(WalkthroughReport).decode(failure_report.read_bytes())
    finally:
        failure_report.unlink(missing_ok=True)

    assert written.status == "FAIL"
    assert (written.total, written.passed, written.failed) == (4, 3, 1)
    assert written.results[0].detail == "RuntimeError: injected scenario fault"
    assert {result.name for result in written.results[1:]} == _SCENARIO_NAMES


def test_formula_walkthrough_subprocess_exits_zero_and_writes_report() -> None:
    _REPORT_PATH.unlink(missing_ok=True)
    completed = subprocess.run(
        [sys.executable, "-m", "demo.formula_walkthrough"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=_DRIVER_TIMEOUT_S,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert _REPORT_PATH.is_file()

    report = msgspec.json.Decoder(WalkthroughReport).decode(_REPORT_PATH.read_bytes())
    assert report.status == "PASS"
    assert (report.total, report.passed, report.failed) == (3, 3, 0)
    assert {result.name for result in report.results} == _SCENARIO_NAMES
