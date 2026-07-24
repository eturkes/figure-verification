# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Verified render, signed-certificate retrieval, and chart-page transport contracts.

The good corpus renders through the service byte-for-byte as a direct render.render (the SVG,
the five cert-verbatim hashes, and the content-addressed plot_id/spec_id); a repeat POST is
idempotent (same plot_id). The service signs exact VCert bytes into deterministic DSSE, defines
plot_id as SHA-256(envelope), and durably serves exact certificate/spec/raw-key bytes from the
archive across chart-LRU eviction and app restart. Every public read independently rechecks its
address and archive relations; certificate reads authenticate canonical DSSE signature/type under
the digest-matching archived key without elevating it to trust. Malformed/unknown addresses share
one 404; relation/blob/hash/signature/type corruption — even after repeated reads — becomes logged
generic 500. The never-a-chart pin still holds over all bad specs. X-Content-Type-Options: nosniff
rides every response, success and problem alike.

GET /chart/{plot_id} serves the offline HTML page built + stored on EVERY verified render, so it
resolves even when the JSON body omitted the inline copy (include_html=false), as text/html under
a Content-Security-Policy: sandbox allow-scripts. The page is rebuilt from authoritative Vega
bytes after signing and visibly carries the VCert badge, signer keyid, plot_id, and exact envelope
link. Its chart LRU (html_cap) is process-local, while certificates remain archive-durable, so a
certificate can outlive its chart page; an absent or malformed plot_id 404s as problem+json carrying
neither the CSP nor text/html (only the app-default nosniff).
"""

import hashlib
import json
import logging
import sqlite3
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NoReturn, cast
from unittest.mock import AsyncMock

import httpx
import msgspec
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from litestar import Litestar
from litestar.testing import TestClient

from verifier import attestation, canon, checks, limits, render
from verifier.errors import VerificationError
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.schema import VPlotSpec, decode_spec
from verifier.service import app as service_app
from verifier.service import archive as archive_module
from verifier.service import pipeline
from verifier.service.app import create_app
from verifier.service.archive import Archive, ArchiveBatch, BlobKind, BlobWrite, KeyRecord
from verifier.service.identity import SigningIdentity, keyid_for_public_key
from verifier.service.model_client import ModelProposal, ProposalTrace
from verifier.service.models import Verdict
from verifier.service.settings import Settings

_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLES = _ROOT / "examples"
_GOOD_DIR = _EXAMPLES / "good_specs"
_BAD_DIR = _EXAMPLES / "bad_specs"
_DATA = _ROOT / "data"

_INDEX: dict[str, Any] = json.loads((_EXAMPLES / "index.json").read_text(encoding="utf-8"))
_GOOD: list[dict[str, Any]] = _INDEX["good_specs"]
_BAD: list[dict[str, Any]] = _INDEX["bad_specs"]

_JSON = {"content-type": "application/json"}
_PROBLEM_JSON = "application/problem+json"
_NOSNIFF = "nosniff"
_SALES_GOOD = "g01_total_revenue_by_month.json"


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _ids(entries: list[dict[str, Any]]) -> list[str]:
    return [Path(e["file"]).stem for e in entries]


def _manifest_bytes(dataset_name: str) -> bytes:
    return (_DATA / "schemas" / f"{Path(dataset_name).stem}.json").read_bytes()


def _direct_render(raw: bytes, *, include_html: bool = False) -> render.RenderResult:
    """render.render on the raw spec, off the transport — the byte-identity oracle."""
    spec = decode_spec(raw)
    result = render.render(
        spec, _manifest_bytes(spec.dataset.name), data_dir=_DATA, include_html=include_html
    )
    assert result is not None
    return result


def _copy_sales_dataset(data_dir: Path) -> tuple[Path, Path]:
    source = data_dir / "sales.csv"
    manifest = data_dir / "schemas" / "sales.json"
    manifest.parent.mkdir()
    source.write_bytes((_DATA / "sales.csv").read_bytes())
    manifest.write_bytes((_DATA / "schemas" / "sales.json").read_bytes())
    return source, manifest


def _post_render_route(
    client: TestClient[Litestar], raw: bytes, route: Literal["direct", "propose"]
) -> httpx.Response:
    if route == "direct":
        return client.post("/verify-and-render", content=raw, headers=_JSON)
    spec = decode_spec(raw)
    body = msgspec.json.encode(
        {"user_request": "Plot total revenue by month", "dataset_name": spec.dataset.name}
    )
    return client.post("/propose-spec", content=body, headers=_JSON)


def _proposal(reply: bytes) -> ModelProposal:
    """A successful typed proposer result for route tests that stub the model boundary."""
    trace = ProposalTrace(b"model request", b"model response", reply, fault=None)
    return ModelProposal(reply, trace)


def _render_verdict(
    response: httpx.Response, route: Literal["direct", "propose"]
) -> dict[str, Any]:
    if route == "direct":
        return cast("dict[str, Any]", response.json())
    payload = cast("list[Any]", response.json())
    result = cast("dict[str, Any]", payload[0])
    return cast("dict[str, Any]", result["verdict"])


def test_proposer_decoder_receives_traced_reply_buffer_verbatim(
    client: TestClient[Litestar], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route must not decode/re-encode between model extraction and schema decode."""
    reply = bytes(bytearray(b'```json\n{"not":"a spec"}\n```'))
    proposal = _proposal(reply)
    observed: list[bytes] = []
    original_decode = pipeline.decode_stage

    def recording_decode(candidate: bytes) -> VPlotSpec | Verdict:
        observed.append(candidate)
        return original_decode(candidate)

    monkeypatch.setattr(service_app, "propose_spec", AsyncMock(return_value=proposal))
    monkeypatch.setattr(service_app, "decode_stage", recording_decode)
    request = msgspec.json.encode(
        {"user_request": "Plot total revenue", "dataset_name": "sales.csv"}
    )

    response = client.post("/propose-spec", content=request, headers=_JSON)

    assert response.status_code == 200
    assert observed == [reply]
    assert observed[0] is proposal.trace.reply_bytes
    assert response.json()["model_reply"] == reply.decode()


@pytest.fixture
def service(tmp_path: Path) -> Litestar:
    """One isolated persistent signer over the real corpus data."""
    return create_app(Settings(data_dir=_DATA, state_dir=tmp_path / "state"))


@pytest.fixture
def signing_identity(service: Litestar) -> SigningIdentity:
    return cast("SigningIdentity", service.state["identity"])


@pytest.fixture
def client(service: Litestar) -> Iterator[TestClient[Litestar]]:
    """A client over the real data_dir (the golden corpus binds to it)."""
    with TestClient(app=service) as test_client:
        yield test_client


# --- good specs: verified renders match a direct render byte-for-byte --------
@pytest.mark.parametrize("entry", _GOOD, ids=_ids(_GOOD))
def test_good_spec_renders_and_matches_direct(
    client: TestClient[Litestar], signing_identity: SigningIdentity, entry: dict[str, Any]
) -> None:
    raw = (_GOOD_DIR / entry["file"]).read_bytes()
    response = client.post("/verify-and-render", content=raw, headers=_JSON)
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == _NOSNIFF
    body: dict[str, Any] = response.json()
    assert body["verified"] is True
    assert body["layer"] == "verify"
    assert "html" not in body  # default omits the offline view (omit_defaults on None)

    direct = _direct_render(raw)
    cert = direct.certificate
    envelope = attestation.sign_vcert(
        cert,
        signing_identity.signer.private_key,
        keyid=signing_identity.signer.keyid,
    )
    assert body["svg"] == direct.svg  # determinism THROUGH the service
    assert body["plot_id"] == hashlib.sha256(envelope).hexdigest()
    assert body["spec_id"] == cert.spec_hash.removeprefix("sha256:")
    assert body["dataset_hash"] == cert.dataset_hash
    assert body["spec_hash"] == cert.spec_hash
    assert body["plotted_table_hash"] == cert.plotted_table_hash
    assert body["manifest_hash"] == cert.manifest_hash
    assert body["vega_lite_hash"] == cert.vega_lite_hash
    assert [(item.id, item.method, item.status) for item in cert.checks] == [
        (item["check"], item["method"], item["status"])
        for item in body["results"]
        if item["status"] == "pass"
    ]


@pytest.mark.parametrize("route", ["direct", "propose"])
def test_render_routes_read_each_verification_input_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route: Literal["direct", "propose"],
) -> None:
    source, manifest = _copy_sales_dataset(tmp_path)
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    # Stub the upstream proposal so this counts the proposer route's verification/render leg;
    # model prompt context has its own reads and is bounded separately in M5.1g.
    monkeypatch.setattr(service_app, "propose_spec", AsyncMock(return_value=_proposal(raw)))
    reads: Counter[Path] = Counter()

    def counted_read(path: Path, max_bytes: int) -> bytes:
        reads[path.resolve()] += 1
        return limits.read_bounded(path, max_bytes)

    monkeypatch.setattr(pipeline, "read_bounded", counted_read)
    monkeypatch.setattr(checks, "read_bounded", counted_read)
    with TestClient(
        app=create_app(Settings(data_dir=tmp_path, state_dir=tmp_path / "state"))
    ) as client:
        response = _post_render_route(client, raw, route)
    assert response.status_code == 200
    assert _render_verdict(response, route)["verified"] is True
    assert reads == Counter({source.resolve(): 1, manifest.resolve(): 1})
    for internal_name in (b'"trace"', b'"evidence"', b'"source_bytes"', b'"manifest_bytes"'):
        assert internal_name not in response.content


@pytest.mark.parametrize("route", ["direct", "propose"])
def test_render_routes_ignore_source_mutation_after_evidence_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route: Literal["direct", "propose"],
) -> None:
    source, manifest = _copy_sales_dataset(tmp_path)
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    spec = decode_spec(raw)
    expected = render.render(spec, manifest.read_bytes(), data_dir=tmp_path)
    assert expected is not None
    monkeypatch.setattr(service_app, "propose_spec", AsyncMock(return_value=_proposal(raw)))
    original_verify_run = checks.verify_run
    calls = 0
    replacement = b"month,region,revenue,orders\n2099-01,NA,1.00,1\n"

    def capture_then_mutate(
        captured_spec: VPlotSpec,
        manifest_bytes: bytes,
        *,
        data_dir: Path,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> checks.VerificationRun:
        nonlocal calls
        run = original_verify_run(captured_spec, manifest_bytes, data_dir=data_dir, limits=limits)
        calls += 1
        source.write_bytes(replacement)
        return run

    monkeypatch.setattr(checks, "verify_run", capture_then_mutate)
    with TestClient(
        app=create_app(Settings(data_dir=tmp_path, state_dir=tmp_path / "state"))
    ) as client:
        response = _post_render_route(client, raw, route)
    assert response.status_code == 200
    verdict = _render_verdict(response, route)
    assert verdict["verified"] is True
    assert verdict["svg"] == expected.svg
    assert verdict["dataset_hash"] == expected.certificate.dataset_hash
    assert calls == 1
    assert source.read_bytes() == replacement


def test_proposer_formal_gate_blocks_built_bar_zero_corruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A builder-scale defect becomes a 200 failed verdict, with no native render or store."""
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    original_build = render.build_vega_lite

    def corrupt_zero(*args: Any, **kwargs: Any) -> dict[str, Any]:
        built = original_build(*args, **kwargs)
        built["encoding"]["y"]["scale"]["zero"] = False
        return built

    def forbidden_native(_: str) -> str:
        msg = "native render reached after a formal bar-zero failure"
        raise AssertionError(msg)

    monkeypatch.setattr(service_app, "propose_spec", AsyncMock(return_value=_proposal(raw)))
    monkeypatch.setattr(render, "build_vega_lite", corrupt_zero)
    monkeypatch.setattr(render, "render_svg", forbidden_native)
    request = msgspec.json.encode(
        {"user_request": "Plot total revenue by month", "dataset_name": "sales.csv"}
    )
    with TestClient(
        app=create_app(Settings(data_dir=_DATA, state_dir=tmp_path / "state"))
    ) as client:
        response = client.post("/propose-spec", content=request, headers=_JSON)
        assert response.status_code == 200
        body = cast("dict[str, Any]", response.json())
        verdict = cast("dict[str, Any]", body["verdict"])
        assert verdict["verified"] is False
        assert b'"svg"' not in response.content
        assert b'"html"' not in response.content
        failed = [item for item in verdict["results"] if item["status"] == "fail"]
        assert [(item["check"], item["method"]) for item in failed] == [
            ("scale.bar_zero", "z3_smt")
        ]
        spec_id = canon.hash_spec(decode_spec(raw)).removeprefix("sha256:")
        assert client.get(f"/spec/{spec_id}").status_code == 404


# --- the never-a-chart pin: no svg/html key over the whole bad corpus --------
@pytest.mark.parametrize("entry", _BAD, ids=_ids(_BAD))
def test_bad_spec_never_renders(client: TestClient[Litestar], entry: dict[str, Any]) -> None:
    raw = (_BAD_DIR / entry["file"]).read_bytes()
    response = client.post("/verify-and-render", content=raw, headers=_JSON)
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == _NOSNIFF
    # Byte level: neither the svg nor the html key appears in the raw response (a failing
    # verify-and-render answers a plain Verdict, which structurally has no such fields).
    assert b'"svg"' not in response.content
    assert b'"html"' not in response.content
    body: dict[str, Any] = response.json()
    assert body["verified"] is False
    assert "svg" not in body
    assert "html" not in body


# --- idempotent: a repeat POST content-addresses to the same plot -----------
def test_repeat_post_is_idempotent(client: TestClient[Litestar]) -> None:
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    first: dict[str, Any] = client.post("/verify-and-render", content=raw, headers=_JSON).json()
    second: dict[str, Any] = client.post("/verify-and-render", content=raw, headers=_JSON).json()
    assert first["plot_id"] == second["plot_id"]
    assert first["spec_id"] == second["spec_id"]
    assert first["svg"] == second["svg"]


# --- retrieval GETs serve the stored canonical bytes verbatim ---------------
def test_certificate_get_round_trips_signed_envelope(
    client: TestClient[Litestar], signing_identity: SigningIdentity
) -> None:
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    posted: dict[str, Any] = client.post("/verify-and-render", content=raw, headers=_JSON).json()
    response = client.get(f"/certificate/{posted['plot_id']}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-content-type-options"] == _NOSNIFF
    direct = _direct_render(raw)
    assert posted["plot_id"] == hashlib.sha256(response.content).hexdigest()
    verified = attestation.verify_vcert(response.content, signing_identity.trusted_keys)
    assert verified.payload == render.vcert_bytes(direct.certificate)
    assert verified.certificate == direct.certificate

    external_wrong_key = Ed25519PrivateKey.generate().public_key()
    with pytest.raises(attestation.AttestationError, match="not valid under any trusted"):
        attestation.verify_vcert(
            response.content,
            {"sha256:" + "f" * 64: external_wrong_key},
        )


def test_restart_preserves_envelope_and_rotation_changes_identity(tmp_path: Path) -> None:
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    state_dir = tmp_path / "state"
    stable_settings = Settings(data_dir=_DATA, state_dir=state_dir)

    def rendered(app: Litestar) -> tuple[dict[str, Any], bytes, SigningIdentity]:
        identity = cast("SigningIdentity", app.state["identity"])
        with TestClient(app=app) as scoped:
            verdict = cast(
                "dict[str, Any]",
                scoped.post("/verify-and-render", content=raw, headers=_JSON).json(),
            )
            envelope = scoped.get(f"/certificate/{verdict['plot_id']}").content
        return verdict, envelope, identity

    first, first_envelope, first_identity = rendered(create_app(stable_settings))
    restarted, restarted_envelope, restarted_identity = rendered(create_app(stable_settings))
    assert restarted["plot_id"] == first["plot_id"]
    assert restarted_envelope == first_envelope
    assert restarted_identity.signer.keyid == first_identity.signer.keyid

    rotated_settings = Settings(
        data_dir=_DATA,
        state_dir=state_dir,
        signing_key_file=state_dir / "rotated.key",
    )
    rotated, rotated_envelope, rotated_identity = rendered(create_app(rotated_settings))
    assert rotated["plot_id"] != first["plot_id"]
    assert rotated_envelope != first_envelope
    assert rotated_identity.signer.keyid != first_identity.signer.keyid
    assert (
        attestation.verify_vcert(rotated_envelope, rotated_identity.trusted_keys).payload
        == attestation.verify_vcert(first_envelope, first_identity.trusted_keys).payload
    )


def test_archived_public_key_presence_does_not_extend_rotated_trust(tmp_path: Path) -> None:
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    state_dir = tmp_path / "state"
    first_app = create_app(Settings(data_dir=_DATA, state_dir=state_dir))
    first_identity = cast("SigningIdentity", first_app.state["identity"])
    with TestClient(app=first_app) as client:
        response = client.post("/verify-and-render", content=raw, headers=_JSON)
        assert response.status_code == 200
    old_keyid = first_identity.signer.keyid
    old_public_key = first_identity.signer.public_key_bytes

    rotated_app = create_app(
        Settings(
            data_dir=_DATA,
            state_dir=state_dir,
            signing_key_file=state_dir / "rotated.key",
        )
    )
    rotated_identity = cast("SigningIdentity", rotated_app.state["identity"])
    assert old_keyid not in rotated_identity.trusted_keys
    with TestClient(app=rotated_app) as client:
        response = client.get(f"/key/{old_keyid}")
    assert response.status_code == 200
    assert response.content == old_public_key


def test_direct_and_propose_routes_share_one_signing_seam(
    client: TestClient[Litestar],
    service: Litestar,
    signing_identity: SigningIdentity,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    monkeypatch.setattr(service_app, "propose_spec", AsyncMock(return_value=_proposal(raw)))
    original = attestation.sign_vcert
    calls: list[tuple[render.VCert, Ed25519PrivateKey, str, VerificationLimits]] = []

    def recording_sign(
        certificate: render.VCert,
        private_key: Ed25519PrivateKey,
        *,
        keyid: str,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> bytes:
        calls.append((certificate, private_key, keyid, limits))
        return original(certificate, private_key, keyid=keyid, limits=limits)

    monkeypatch.setattr(attestation, "sign_vcert", recording_sign)
    direct = _render_verdict(_post_render_route(client, raw, "direct"), "direct")
    proposed = _render_verdict(_post_render_route(client, raw, "propose"), "propose")
    assert direct["plot_id"] == proposed["plot_id"]
    assert len(calls) == 2
    assert {call[2] for call in calls} == {signing_identity.signer.keyid}
    assert all(call[1] is signing_identity.signer.private_key for call in calls)
    assert all(call[3] is service.state["settings"].limits for call in calls)


def test_spec_get_serves_canonical_bytes(client: TestClient[Litestar]) -> None:
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    posted: dict[str, Any] = client.post("/verify-and-render", content=raw, headers=_JSON).json()
    response = client.get(f"/spec/{posted['spec_id']}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.content == canon.spec_bytes(decode_spec(raw))  # canonical, not the raw file
    assert decode_spec(response.content) == decode_spec(raw)  # yet decodes to the same spec


@dataclass(frozen=True, slots=True)
class _PublicArtifacts:
    archive: Archive
    plot_id: str
    spec_id: str
    keyid: str
    envelope: bytes
    public_key: bytes
    canonical_spec: bytes


def _replace_blob(
    connection: sqlite3.Connection,
    old_digest: str,
    kind: BlobKind,
    payload: bytes,
    new_digest: str | None = None,
) -> str:
    digest = old_digest if new_digest is None else new_digest
    connection.execute("DROP TRIGGER blobs_reject_update")
    try:
        cursor = connection.execute(
            "UPDATE blobs SET digest = ?, size = ?, content = ? WHERE digest = ? AND kind = ?",
            (digest, len(payload), payload, old_digest, kind.value),
        )
    finally:
        connection.execute(archive_module._CREATE_BLOB_UPDATE_GUARD)
    assert cursor.rowcount == 1
    return digest


def _readdress_envelope(
    connection: sqlite3.Connection, artifacts: _PublicArtifacts, corrupted: bytes
) -> str:
    new_plot_id = hashlib.sha256(corrupted).hexdigest()
    new_digest = f"sha256:{new_plot_id}"
    _replace_blob(
        connection,
        f"sha256:{artifacts.plot_id}",
        BlobKind.VCERT_ENVELOPE,
        corrupted,
        new_digest,
    )
    cursor = connection.execute(
        "UPDATE plots SET plot_id = ?, certificate_digest = ? WHERE plot_id = ?",
        (new_plot_id, new_digest, artifacts.plot_id),
    )
    assert cursor.rowcount == 1
    return f"/certificate/{new_plot_id}"


def _corrupt_envelope(
    connection: sqlite3.Connection, fault: str, artifacts: _PublicArtifacts
) -> str:
    if fault == "envelope_blob":
        corrupted = artifacts.envelope[:-1] + b"!"
        _replace_blob(
            connection,
            f"sha256:{artifacts.plot_id}",
            BlobKind.VCERT_ENVELOPE,
            corrupted,
        )
        return f"/certificate/{artifacts.plot_id}"
    if fault == "envelope_noncanonical":
        return _readdress_envelope(connection, artifacts, artifacts.envelope + b" ")

    document = cast("dict[str, Any]", json.loads(artifacts.envelope))
    if fault == "envelope_signature":
        signatures = cast("list[dict[str, Any]]", document["signatures"])
        signature = cast("str", signatures[0]["sig"])
        signatures[0]["sig"] = ("A" if signature[0] != "A" else "B") + signature[1:]
    elif fault == "envelope_keyid":
        signatures = cast("list[dict[str, Any]]", document["signatures"])
        signatures[0]["keyid"] = "sha256:" + "f" * 64
    else:
        payload_type = cast("str", document["payloadType"])
        document["payloadType"] = payload_type[:-1] + ("x" if payload_type[-1] != "x" else "y")
    corrupted = json.dumps(document, separators=(",", ":")).encode()
    return _readdress_envelope(connection, artifacts, corrupted)


def _corrupt_key(connection: sqlite3.Connection, fault: str, artifacts: _PublicArtifacts) -> str:
    if fault == "key_blob":
        corrupted = bytes([artifacts.public_key[0] ^ 1]) + artifacts.public_key[1:]
        _replace_blob(
            connection,
            artifacts.keyid,
            BlobKind.ED25519_PUBLIC_KEY,
            corrupted,
        )
        return f"/key/{artifacts.keyid}"

    second_public_key = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    second_blob = BlobWrite(BlobKind.ED25519_PUBLIC_KEY, second_public_key)
    second_keyid = keyid_for_public_key(second_public_key)
    artifacts.archive.publish(
        ArchiveBatch(
            blobs=(second_blob,),
            keys=(KeyRecord(second_keyid, second_blob.ref),),
        )
    )
    cursor = connection.execute(
        "UPDATE plots SET keyid = ? WHERE plot_id = ?",
        (second_keyid, artifacts.plot_id),
    )
    assert cursor.rowcount == 1
    return f"/certificate/{artifacts.plot_id}"


def _corrupt_spec(connection: sqlite3.Connection, fault: str, artifacts: _PublicArtifacts) -> str:
    if fault == "spec_relation":
        cursor = connection.execute(
            "UPDATE specs SET canonical_spec_digest = ? WHERE spec_id = ?",
            ("sha256:" + "f" * 64, artifacts.spec_id),
        )
        assert cursor.rowcount == 1
        return f"/spec/{artifacts.spec_id}"

    replacement = (
        artifacts.canonical_spec + b"\n"
        if fault == "spec_noncanonical"
        else canon.spec_bytes(decode_spec((_GOOD_DIR / _GOOD[1]["file"]).read_bytes()))
    )
    assert replacement != artifacts.canonical_spec
    old_digest = "sha256:" + hashlib.sha256(artifacts.canonical_spec).hexdigest()
    new_digest = "sha256:" + hashlib.sha256(replacement).hexdigest()
    _replace_blob(connection, old_digest, BlobKind.CANONICAL_SPEC, replacement, new_digest)
    cursor = connection.execute(
        "UPDATE specs SET canonical_spec_digest = ? WHERE spec_id = ?",
        (new_digest, artifacts.spec_id),
    )
    assert cursor.rowcount == 1
    return f"/spec/{artifacts.spec_id}"


def _corrupt_public_artifact(
    connection: sqlite3.Connection, fault: str, artifacts: _PublicArtifacts
) -> str:
    connection.execute("PRAGMA foreign_keys=OFF")
    if fault.startswith("envelope_"):
        return _corrupt_envelope(connection, fault, artifacts)
    if fault.startswith("key_"):
        return _corrupt_key(connection, fault, artifacts)
    return _corrupt_spec(connection, fault, artifacts)


@pytest.mark.parametrize(
    "fault",
    [
        "envelope_blob",
        "envelope_signature",
        "envelope_keyid",
        "envelope_type",
        "envelope_noncanonical",
        "key_relation",
        "key_blob",
        "spec_relation",
        "spec_noncanonical",
        "spec_hash",
    ],
)
def test_public_artifact_corruption_is_logged_generic_500(tmp_path: Path, fault: str) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    app = create_app(settings)
    archive = cast("Archive", app.state["archive"])
    identity = cast("SigningIdentity", app.state["identity"])
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    canonical_spec = canon.spec_bytes(decode_spec(raw))

    with TestClient(app=app) as client:
        posted = cast(
            "dict[str, Any]",
            client.post("/verify-and-render", content=raw, headers=_JSON).json(),
        )
        plot_id = cast("str", posted["plot_id"])
        spec_id = cast("str", posted["spec_id"])
        keyid = identity.signer.keyid
        envelope = client.get(f"/certificate/{plot_id}").content
        public_key = client.get(f"/key/{keyid}").content
        assert client.get(f"/spec/{spec_id}").content == canonical_spec
        artifacts = _PublicArtifacts(
            archive,
            plot_id,
            spec_id,
            keyid,
            envelope,
            public_key,
            canonical_spec,
        )

        connection = sqlite3.connect(archive.database_path, autocommit=True)
        try:
            target = _corrupt_public_artifact(connection, fault, artifacts)
        finally:
            connection.close()

        handler = _ListHandler()
        logger = logging.getLogger("verifier.service.app")
        logger.addHandler(handler)
        try:
            response = client.get(target)
        finally:
            logger.removeHandler(handler)

    assert response.status_code == 500
    assert response.headers["content-type"] == _PROBLEM_JSON
    assert response.json() == {
        "title": "Internal Server Error",
        "status": 500,
        "detail": "the verifier encountered an internal error",
    }
    assert fault not in response.text
    assert handler.records
    assert handler.records[-1].levelno == logging.ERROR
    assert handler.records[-1].exc_info is not None


@pytest.mark.parametrize("artifact", ["certificate", "spec", "key"])
@pytest.mark.parametrize("schema_fault", ["version", "guard_trigger"])
def test_public_artifact_schema_drift_is_logged_generic_500(
    tmp_path: Path, artifact: str, schema_fault: str
) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    app = create_app(settings)
    archive = cast("Archive", app.state["archive"])
    identity = cast("SigningIdentity", app.state["identity"])
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()

    with TestClient(app=app) as client:
        posted = cast(
            "dict[str, Any]",
            client.post("/verify-and-render", content=raw, headers=_JSON).json(),
        )
        targets = {
            "certificate": f"/certificate/{posted['plot_id']}",
            "spec": f"/spec/{posted['spec_id']}",
            "key": f"/key/{identity.signer.keyid}",
        }
        target = targets[artifact]
        artifact_bytes = client.get(target).content
        assert artifact_bytes

        connection = sqlite3.connect(archive.database_path, autocommit=True)
        try:
            if schema_fault == "version":
                connection.execute("PRAGMA user_version=4")
            else:
                connection.execute("DROP TRIGGER blobs_reject_delete")
        finally:
            connection.close()

        handler = _ListHandler()
        logger = logging.getLogger("verifier.service.app")
        logger.addHandler(handler)
        try:
            response = client.get(target)
        finally:
            logger.removeHandler(handler)

    assert response.status_code == 500
    assert response.headers["content-type"] == _PROBLEM_JSON
    assert response.json() == {
        "title": "Internal Server Error",
        "status": 500,
        "detail": "the verifier encountered an internal error",
    }
    assert artifact_bytes not in response.content
    assert handler.records
    assert handler.records[-1].levelno == logging.ERROR
    assert handler.records[-1].exc_info is not None


# --- the offline HTML view: attached on request, omitted by default ---------
def test_include_html_attaches_signed_chart_view(client: TestClient[Litestar]) -> None:
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    response = client.post(
        "/verify-and-render", content=raw, headers=_JSON, params={"include_html": "true"}
    )
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    served = client.get(f"/chart/{body['plot_id']}")
    assert body["html"] == served.text
    assert body["svg"] == _direct_render(raw).svg


# --- GET /chart serves the page built on every verified render (even include_html=false) -----
def test_chart_get_serves_compact_verified_page_and_certificate_link(
    client: TestClient[Litestar], signing_identity: SigningIdentity
) -> None:
    # The offline page is built + stored on every verified render, so GET /chart resolves even
    # when the JSON body omitted the inline copy (include_html=false). The served page is the
    # COMPACT in-chat view: the chart, a "Verified plot" badge with the passing-check count, and a
    # link to the signed certificate envelope -- and it deliberately drops the raw hashes / TCB /
    # per-check dump (kept only in the linked envelope) so it blends into the chat.
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    posted: dict[str, Any] = client.post(
        "/verify-and-render", content=raw, headers=_JSON, params={"include_html": "false"}
    ).json()
    assert "html" not in posted  # the JSON body still omits the inline view
    response = client.get(f"/chart/{posted['plot_id']}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["content-security-policy"] == "sandbox allow-scripts"
    assert response.headers["x-content-type-options"] == _NOSNIFF
    envelope = client.get(f"/certificate/{posted['plot_id']}").content
    certificate = attestation.verify_vcert(envelope, signing_identity.trusted_keys).certificate
    page = response.text
    assert 'id="vplot-chart"' in page  # the chart card
    assert "Verified plot" in page  # the compact verified badge
    assert f"{len(certificate.checks)} checks passed" in page  # honest, low-noise signal
    certificate_url = f"http://127.0.0.1:8000/certificate/{posted['plot_id']}"
    assert f'href="{certificate_url}"' in page  # the sole path to the full signed record
    # The verbose technical dump is gone -- this is the "fits the chat" regression guard.
    for digest in (
        certificate.dataset_hash,
        certificate.spec_hash,
        certificate.plotted_table_hash,
        certificate.manifest_hash,
        certificate.vega_lite_hash,
    ):
        assert digest not in page
    assert certificate.tcb.verifier_version not in page
    assert signing_identity.signer.keyid not in page


def test_signed_chart_final_html_limit_is_reapplied_before_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(render, "signed_chart_html", lambda *_args, **_kwargs: "éxx")
    settings = Settings(
        data_dir=_DATA,
        state_dir=tmp_path / "state",
        max_html_bytes=3,
        chart_cache_bytes=3,
    )
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    with TestClient(app=create_app(settings)) as scoped:
        response = scoped.post("/verify-and-render", content=raw, headers=_JSON)
        body = cast("dict[str, Any]", response.json())
        assert body["verified"] is False
        assert body["results"][-1]["check"] == "resource.html_bytes"
        assert body["results"][-1]["message"] == "HTML has 4 bytes; limit is 3"
        spec_id = canon.hash_spec(decode_spec(raw)).removeprefix("sha256:")
        assert scoped.get(f"/spec/{spec_id}").status_code == 404


# --- chart-LRU eviction leaves archive-durable certificates available -------------------------
def test_chart_lru_eviction_leaves_archive_certificate_available(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            data_dir=_DATA,
            state_dir=tmp_path / "state",
            html_cap=1,
        )
    )
    with TestClient(app=app) as client:
        a: dict[str, Any] = client.post(
            "/verify-and-render", content=(_GOOD_DIR / _GOOD[0]["file"]).read_bytes(), headers=_JSON
        ).json()
        b: dict[str, Any] = client.post(
            "/verify-and-render", content=(_GOOD_DIR / _GOOD[1]["file"]).read_bytes(), headers=_JSON
        ).json()
        assert a["plot_id"] != b["plot_id"]
        assert client.get(f"/certificate/{a['plot_id']}").status_code == 200
        assert client.get(f"/certificate/{b['plot_id']}").status_code == 200
        assert client.get(f"/chart/{a['plot_id']}").status_code == 404
        assert client.get(f"/chart/{b['plot_id']}").status_code == 200


# --- an absent or malformed chart id 404s without the CSP (uniform with the other GETs) ------
def test_chart_absent_or_malformed_404_without_csp(client: TestClient[Litestar]) -> None:
    # A never-stored valid-shape id and a malformed id both 404 as problem+json — the same uniform
    # answer the other retrieval GETs give — carrying NEITHER the chart CSP nor a text/html
    # content-type; only the app-default nosniff rides the problem response.
    for bad_id in ("0" * 64, "abc", "g" * 64):
        response = client.get(f"/chart/{bad_id}")
        assert response.status_code == 404
        assert response.headers["content-type"] == _PROBLEM_JSON
        assert "content-security-policy" not in response.headers
        assert response.headers["x-content-type-options"] == _NOSNIFF


# --- archive artifacts survive chart-LRU eviction and restart -----------------
def test_archive_artifacts_survive_chart_lru_eviction_and_restart(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=_DATA,
        state_dir=tmp_path / "state",
        html_cap=1,
    )
    app = create_app(settings)
    identity = cast("SigningIdentity", app.state["identity"])
    raw_a = (_GOOD_DIR / _GOOD[0]["file"]).read_bytes()
    raw_b = (_GOOD_DIR / _GOOD[1]["file"]).read_bytes()
    expected_spec = canon.spec_bytes(decode_spec(raw_a))
    keyid = identity.signer.keyid
    expected_key = identity.signer.public_key_bytes

    with TestClient(app=app) as client:
        a = cast(
            "dict[str, Any]",
            client.post("/verify-and-render", content=raw_a, headers=_JSON).json(),
        )
        expected_certificate = client.get(f"/certificate/{a['plot_id']}").content
        assert client.get(f"/spec/{a['spec_id']}").content == expected_spec
        key_response = client.get(f"/key/{keyid}")
        assert key_response.status_code == 200
        assert key_response.headers["content-type"] == "application/octet-stream"
        assert key_response.content == expected_key

        b = cast(
            "dict[str, Any]",
            client.post("/verify-and-render", content=raw_b, headers=_JSON).json(),
        )
        assert a["plot_id"] != b["plot_id"]
        assert client.get(f"/certificate/{a['plot_id']}").content == expected_certificate
        assert client.get(f"/spec/{a['spec_id']}").content == expected_spec
        assert client.get(f"/key/{keyid}").content == expected_key
        assert client.get(f"/chart/{a['plot_id']}").status_code == 404

    restarted = create_app(settings)
    with TestClient(app=restarted) as client:
        assert client.get(f"/certificate/{a['plot_id']}").content == expected_certificate
        assert client.get(f"/spec/{a['spec_id']}").content == expected_spec
        assert client.get(f"/key/{keyid}").content == expected_key
        assert client.get(f"/chart/{a['plot_id']}").status_code == 404


# --- id discipline: malformed and absent ids 404 alike (no validity leak) ----
@pytest.mark.parametrize(
    "bad_id",
    [
        "A" * 64,  # uppercase hex
        "abc",  # too short
        "0" * 63,  # one short of 64
        "0" * 65,  # one past 64
        "g" * 64,  # right length, non-hex
        "." * 64,  # right length, traversal-flavoured chars
    ],
)
def test_malformed_id_404_problem(client: TestClient[Litestar], bad_id: str) -> None:
    for path in (f"/certificate/{bad_id}", f"/spec/{bad_id}"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.headers["content-type"] == _PROBLEM_JSON
        assert response.headers["x-content-type-options"] == _NOSNIFF


def test_well_formed_but_absent_id_404_problem(client: TestClient[Litestar]) -> None:
    # A valid-shape id that was never stored: the store-miss branch, same 404 as a malformed id.
    assert client.get("/certificate/" + "0" * 64).status_code == 404
    response = client.get("/spec/" + "f" * 64)
    assert response.status_code == 404
    assert response.headers["content-type"] == _PROBLEM_JSON


def test_public_key_malformed_and_unknown_addresses_share_uniform_404(
    client: TestClient[Litestar],
) -> None:
    unknown = client.get("/key/sha256:" + "0" * 64)
    assert unknown.status_code == 404
    expected = unknown.json()
    for keyid in ("abc", "sha256:abc", "sha256:" + "A" * 64, "0" * 64):
        response = client.get(f"/key/{keyid}")
        assert response.status_code == 404
        assert response.headers["content-type"] == _PROBLEM_JSON
        assert response.headers["x-content-type-options"] == _NOSNIFF
        assert response.json() == expected


# --- transport misuse on the new route -> problem+json ----------------------
def test_verify_and_render_wrong_content_type_415(client: TestClient[Litestar]) -> None:
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    response = client.post(
        "/verify-and-render", content=raw, headers={"content-type": "text/plain"}
    )
    assert response.status_code == 415
    assert response.headers["content-type"] == _PROBLEM_JSON
    assert response.headers["x-content-type-options"] == _NOSNIFF


# --- a decodable spec for an unprovisioned dataset -> 200 Verdict, no chart --
def test_verify_and_render_manifest_unavailable_is_verdict(tmp_path: Path) -> None:
    # A decodable good spec whose dataset has no trusted manifest under data_dir fails closed as
    # a 200 Verdict — never a chart — through verify-and-render's early return on an unverified
    # outcome (a real data-domain path that 100% branch coverage does not otherwise pin here).
    app = create_app(Settings(data_dir=tmp_path, state_dir=tmp_path / "state"))
    with TestClient(app=app) as no_manifest_client:
        raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
        response = no_manifest_client.post("/verify-and-render", content=raw, headers=_JSON)
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == _NOSNIFF
    assert b'"svg"' not in response.content
    assert b'"html"' not in response.content
    body: dict[str, Any] = response.json()
    assert body["verified"] is False
    assert body["layer"] == "verify"
    assert [result["check"] for result in body["results"]] == ["dataset.manifest_available"]


# --- render policy refusals stay verification outcomes and never store -------
@pytest.mark.parametrize("stage", ["prepare_render", "render_prepared"])
def test_render_resource_failure_is_verdict_without_store(
    client: TestClient[Litestar], monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    def refused(*_args: object, **_kwargs: object) -> NoReturn:
        message = "artifact exceeds test limit"
        raise VerificationError(message, check="resource.vega_bytes")

    monkeypatch.setattr(render, stage, refused)
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    response = client.post("/verify-and-render", content=raw, headers=_JSON)
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == _NOSNIFF
    assert b'"svg"' not in response.content
    assert b'"html"' not in response.content
    body: dict[str, Any] = response.json()
    assert body["verified"] is False
    assert body["layer"] == "verify"
    assert body["results"][-1] == {
        "check": "resource.vega_bytes",
        "method": "resource_policy",
        "status": "fail",
        "severity": "blocking",
        "message": "artifact exceeds test limit",
    }
    spec_id = canon.hash_spec(decode_spec(raw)).removeprefix("sha256:")
    assert client.get(f"/spec/{spec_id}").status_code == 404


def test_render_uses_operator_resource_limits_without_store(tmp_path: Path) -> None:
    raw = (_GOOD_DIR / _SALES_GOOD).read_bytes()
    settings = Settings(
        data_dir=_DATA,
        state_dir=tmp_path / "state",
        max_render_rows=1,
    )
    with TestClient(app=create_app(settings)) as scoped:
        response = scoped.post("/verify-and-render", content=raw, headers=_JSON)
        body: dict[str, Any] = response.json()
        assert response.status_code == 200
        assert body["verified"] is False
        assert body["results"][-1]["check"] == "resource.render_rows"
        spec_id = canon.hash_spec(decode_spec(raw)).removeprefix("sha256:")
        assert scoped.get(f"/spec/{spec_id}").status_code == 404
