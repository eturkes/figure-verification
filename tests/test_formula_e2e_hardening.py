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
import json
import logging
import sqlite3
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import closing
from dataclasses import replace
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
from verifier.service.__main__ import main as service_main
from verifier.service.app import create_app
from verifier.service.archive import (
    Archive,
    ArchiveIntegrityError,
    ArchiveSchemaError,
    ArchiveStats,
    AttemptBundle,
    AttemptOutcome,
    AttemptRoute,
    open_archive,
)
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
_CERTIFIED_CHECK_COUNT = 13
_INJECTED_FAULT = "injected scenario fault"
_CHECK_FIELDS = ("id", "method", "status")
_SCENARIO_NAMES = {
    "formula direct flow",
    "formula proposed flow",
    "formula certificate check shape",
    "formula failed attempt audit cli",
    "formula archive integrity guards",
}
_SCENARIO_COUNT = 5
# Hand-stated so a later rewrite cannot quietly upgrade a hedged claim into one the run never
# establishes. `/table` and `/script` are digest-addressed, so no detail may call them
# authenticated.
_SCENARIO_DETAILS = {
    "direct formula verify, restart, exact replay, certificate-matched table and script",
    "stubbed formula proposal verified, archived, and replayed exactly after a restart",
    "fetched VCert v0.3 exposed 13 distinct non-empty {id, method, status} triples "
    "across three methods",
    "real audit CLI explained a durable rejected formula attempt, redacted by default",
    "rotated signer, schema damage, and formula signature tampering all failed closed",
}
_FORGED_DIGEST = "sha256:" + "0" * 64
_MALFORMED_SPEC = b"{"
_REJECTED_VERDICT_KEYS = {"attempt_id", "layer", "results", "verified"}
_REJECTED_RESULT = ("spec.decode", "schema_validation", "blocking")
_DAMAGED_INDEX = "attempts_by_plot"
_SIGNATURE_MARKER = b'"sig":"'
_CONNECT_BOMB = "publish_attempt connected before authenticating the bundle"
# A rejected formula occurrence carries exactly these two carriers, in this order.
_FORMULA_AUDIT_ROLES = ("raw_spec", "verdict")
_DATASET_AUDIT_ROLES = ("raw_csv", "raw_manifest", "vega_lite", "svg")
# Trust fails ahead of recomputation, so every formula artifact key is present and None. The key
# set is what makes the verdict formula-shaped; a mode-neutral failure would not carry it.
_UNMATCHED_ARTIFACTS = {
    "formula": None,
    "spec": None,
    "plotted_table": None,
    "matplotlib_script": None,
}


class _ListHandler(logging.Handler):
    """Collect expected service error records without printing their tracebacks."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


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

    restarted_app = create_app(_reopened(settings))
    with TestClient(app=restarted_app) as restarted:
        _assert_exact_replay(_replay(restarted, plot_id))
        _envelope, certificate = _certificate(restarted, restarted_app, plot_id)
        certified = _certified_bindings(certificate)
        # The POST verdict's digests carry no signature, so they must AGREE with the
        # authenticated certificate rather than stand in for it as the comparison authority.
        assert published == certified
        assert canon.hash_table_bytes(_table(restarted, plot_id)) == certified[2]
        assert canon.hash_matplotlib_script(_script(restarted, plot_id)) == certified[3]


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

    restarted_app = create_app(_reopened(settings))
    with TestClient(app=restarted_app) as restarted:
        _assert_exact_replay(_replay(restarted, plot_id))
        _envelope, certificate = _certificate(restarted, restarted_app, plot_id)
        certified = _certified_bindings(certificate)
        # Same authority rule as the direct arm: the unsigned verdict agrees, never decides.
        assert published == certified
        assert canon.hash_table_bytes(_table(restarted, plot_id)) == certified[2]
        assert canon.hash_matplotlib_script(_script(restarted, plot_id)) == certified[3]


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
    # Cardinality carries what the method set cannot: dropping one construction check leaves all
    # three labels intact, so the certificate can under-report while this set stays exact.
    assert len(certificate.checks) == _CERTIFIED_CHECK_COUNT
    assert len({check.id for check in certificate.checks}) == _CERTIFIED_CHECK_COUNT


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


def _read_bundle(settings: Settings, attempt_id: str) -> AttemptBundle:
    return open_archive(settings).read_attempt(
        attempt_id,
        max_bytes=settings.max_archive_bytes,
        limits=settings.limits,
    )


def _audit_artifacts(output: str) -> list[dict[str, Any]]:
    document = cast("dict[str, Any]", json.loads(output))
    assert document["plot"] is None
    return cast("list[dict[str, Any]]", document["attempt"]["artifacts"])


def _audit_roles(output: str) -> tuple[str, ...]:
    return tuple(cast("str", item["role"]) for item in _audit_artifacts(output))


def _revealed_verdict(output: str) -> dict[str, Any]:
    """Decode the verdict the revealed audit discloses, so it can be compared with the POST."""
    verdict = next(item for item in _audit_artifacts(output) if item["role"] == "verdict")
    content = cast("dict[str, Any]", verdict["content"])
    assert content["encoding"] == "utf-8"
    return cast("dict[str, Any]", json.loads(cast("str", content["value"])))


def _tamper_signature(bundle: AttemptBundle) -> AttemptBundle:
    """Flip one byte inside the DSSE signature and re-address the occurrence.

    An occurrence address is a RAW digest of the envelope, not a domain-tagged artifact digest,
    so `hashlib.sha256` is the correct instrument here and only here.
    """
    index = bundle.attempt_envelope.index(_SIGNATURE_MARKER) + len(_SIGNATURE_MARKER)
    original_byte = bundle.attempt_envelope[index : index + 1]
    replacement_byte = b"A" if original_byte != b"A" else b"B"
    tampered_envelope = (
        bundle.attempt_envelope[:index] + replacement_byte + bundle.attempt_envelope[index + 1 :]
    )
    assert tampered_envelope != bundle.attempt_envelope
    return replace(
        bundle,
        attempt_id=hashlib.sha256(tampered_envelope).hexdigest(),
        attempt_envelope=tampered_envelope,
    )


def test_rejected_formula_attempt_survives_restart_and_the_real_audit_cli_explains_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """A refused formula spec still archives durably, and the CLI stays redacted by default."""
    settings = _settings(tmp_path, "audit-state")
    with TestClient(app=create_app(settings)) as client:
        verified = _verify_formula(client)
        response = client.post("/verify-formula", content=_MALFORMED_SPEC, headers=_JSON)

    assert response.status_code == 200
    rejected = cast("dict[str, Any]", response.json())
    # A rejected occurrence OMITS the plot keys rather than nulling them, so the exact key set is
    # the pin: a present-and-null `plot_id` would satisfy any `is None` assertion.
    assert set(rejected) == _REJECTED_VERDICT_KEYS
    assert rejected["verified"] is False
    assert rejected["layer"] == "decode"
    result = cast("dict[str, Any]", rejected["results"][0])
    assert (result["check"], result["method"], result["severity"]) == _REJECTED_RESULT
    failure_reason = cast("str", result["message"])
    assert failure_reason
    rejected_id = cast("str", rejected["attempt_id"])
    assert rejected_id != cast("str", verified["attempt_id"])

    attempt = _read_bundle(_reopened(settings), rejected_id)
    assert attempt.manifest.route is AttemptRoute.VERIFY_FORMULA
    assert attempt.manifest.outcome is AttemptOutcome.REJECTED

    # The audit must read a durable archive: the first app is gone before the CLI runs.
    with TestClient(app=create_app(_reopened(settings))) as restarted:
        assert restarted.get(f"/certificate/{verified['plot_id']}").status_code == 200

    monkeypatch.setattr(Settings, "from_env", staticmethod(lambda: settings))
    capfd.readouterr()
    assert service_main(("audit", rejected_id)) == 0
    default_cli = capfd.readouterr()
    assert default_cli.err == ""
    assert '"content"' not in default_cli.out
    default_document = cast("dict[str, Any]", json.loads(default_cli.out))
    assert default_document["disclosure"] == "redacted"
    assert default_document["attempt"]["id"] == rejected_id

    assert service_main(("audit", rejected_id, "--reveal-sensitive")) == 0
    revealed_cli = capfd.readouterr()
    assert revealed_cli.err == ""
    assert len(revealed_cli.out) > len(default_cli.out)
    assert '"content"' in revealed_cli.out

    # The redaction list is one SHARED attempt list, so this exercises a mode-neutral guarantee
    # on a formula occurrence. Both arms carry the same two carriers and no dataset carrier.
    for output in (default_cli.out, revealed_cli.out):
        roles = _audit_roles(output)
        assert roles == _FORMULA_AUDIT_ROLES
        assert not set(roles) & set(_DATASET_AUDIT_ROLES)
        # The audit names carriers in `role` values, so there is no slot a dataset carrier could
        # occupy as JSON null. Absence is therefore checked over the emitted bytes as well.
        assert not [name for name in _DATASET_AUDIT_ROLES if name in output]

    # Close the loop: the durable verdict must explain the SAME failure the caller was shown.
    # Without this the audit could disclose a well-formed verdict about a different rejection.
    audited = cast("dict[str, Any]", _revealed_verdict(revealed_cli.out)["results"][0])
    assert (audited["check"], audited["method"], audited["severity"]) == _REJECTED_RESULT
    assert audited["message"] == failure_reason


def test_rotated_signer_formula_replay_is_untrusted_and_formula_shaped(tmp_path: Path) -> None:
    """Archived public material is self-consistency evidence, never a trust anchor."""
    settings = _settings(tmp_path, "rotated-state")
    with TestClient(app=create_app(settings)) as first:
        plot_id = cast("str", _verify_formula(first)["plot_id"])

    rotated = Settings(
        data_dir=_DATA,
        state_dir=settings.state_dir,
        signing_key_file=settings.state_dir / "rotated.key",
    )
    with TestClient(app=create_app(rotated)) as client:
        body = _replay(client, plot_id)

    assert set(body) == _REPLAY_KEYS
    assert body["status"] == "untrusted_key"
    assert body["integrity_ok"] is False
    assert body["exact"] is False
    assert body["failure_stage"] == "trust"
    assert body["trusted_keyid"] is None
    assert body["payload_match"] is None
    assert body["version_match"] is None
    assert body["artifact_matches"] == _UNMATCHED_ARTIFACTS


def test_formula_schema_damage_logs_the_cause_and_returns_a_generic_500(tmp_path: Path) -> None:
    """Replay fails closed on schema damage, disclosing neither the object nor the cause."""
    app = create_app(_settings(tmp_path, "schema-state"))
    archive = cast("Archive", app.state["archive"])
    handler = _ListHandler()
    logger = logging.getLogger("verifier.service.app")

    with TestClient(app=app) as client:
        plot_id = cast("str", _verify_formula(client)["plot_id"])
        with closing(sqlite3.connect(archive.database_path)) as connection:
            connection.execute(f"DROP INDEX {_DAMAGED_INDEX}")
            connection.commit()

        logger.addHandler(handler)
        try:
            response = client.get(f"/replay/{plot_id}")
        finally:
            logger.removeHandler(handler)

    assert response.status_code == 500
    assert response.headers["content-type"] == _PROBLEM_JSON
    assert response.json() == {
        "title": "Internal Server Error",
        "status": 500,
        "detail": "the verifier encountered an internal error",
    }
    assert _DAMAGED_INDEX not in response.text
    assert handler.records
    record = handler.records[-1]
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
    cause = record.exc_info[1]
    assert isinstance(cause, ArchiveSchemaError)
    assert str(cause) and str(cause) not in response.text


def test_tampered_formula_attempt_is_refused_before_the_archive_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One changed signature byte is refused, and the refusal precedes any connection."""
    source = _settings(tmp_path, "signature-source")
    with TestClient(app=create_app(source)) as client:
        body = _verify_formula(client)
    tampered = _tamper_signature(_read_bundle(_reopened(source), cast("str", body["attempt_id"])))

    target_settings = _settings(tmp_path, "signature-target")
    target = open_archive(target_settings)
    with pytest.raises(ArchiveIntegrityError):
        target.publish_attempt(tampered, limits=target_settings.limits)
    assert target.stats() == ArchiveStats(0, 0, 0, 0, 0)

    # Ordering bomb on the layer BENEATH validation. An implementation that opened its connection
    # before authenticating the bundle surfaces AssertionError here, and no outcome assertion
    # above would have noticed: the refused publication looks identical either way.
    def _connect_bomb(_self: Archive) -> sqlite3.Connection:
        raise AssertionError(_CONNECT_BOMB)

    monkeypatch.setattr(Archive, "_connect", _connect_bomb)
    with pytest.raises(ArchiveIntegrityError):
        target.publish_attempt(tampered, limits=target_settings.limits)


def test_formula_walkthrough_runs_every_scenario_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    report = formula_walkthrough.run_formula_walkthrough()
    assert report.status == "PASS"
    assert len(_SCENARIO_NAMES) == _SCENARIO_COUNT
    assert (report.total, report.passed, report.failed) == (5, 5, 0)
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
    assert (written.total, written.passed, written.failed) == (6, 5, 1)
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
    assert (report.total, report.passed, report.failed) == (5, 5, 0)
    assert {result.name for result in report.results} == _SCENARIO_NAMES
    assert {result.detail for result in report.results} == _SCENARIO_DETAILS
