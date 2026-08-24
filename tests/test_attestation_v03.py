# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""VCert v0.3 fixed-MIME routing, fixed-TCB payload identity, and refusal order."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

import msgspec
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from vector_tcb import FORMULA_TCB
from verifier import attestation, checks, formula_prepare, matplotlib_script, vcert
from verifier.errors import VerificationError
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.schema import decode_formula_spec

_ROOT = Path(__file__).resolve().parent.parent
_FORMULA_SPEC = _ROOT / "examples" / "formula_good_specs" / "f02_linear.json"
_FIXED_SEED = bytes(range(32))
_FIXED_SEED_HEX = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
_FIXED_KEYID = "sha256:" + "a" * 64
_FIXED_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(_FIXED_SEED)
_FIXED_PUBLIC_KEY = _FIXED_PRIVATE_KEY.public_key()
_V02_PAYLOAD_TYPE = "application/vnd.figure-verification.vcert.v0.2+json"
_V03_PAYLOAD_TYPE = "application/vnd.figure-verification.vcert.v0.3+json"
_NEAR_MISS_PAYLOAD_TYPE = "application/vnd.figure-verification.vcert.v0.4+json"


@dataclass(frozen=True, slots=True)
class _EnvelopeVector:
    seed_hex: str
    keyid: str
    envelope_b64: str
    envelope_sha256: str
    payload_length: int
    payload_sha256: str


_V02_VECTOR = _EnvelopeVector(
    seed_hex=_FIXED_SEED_HEX,
    keyid=_FIXED_KEYID,
    envelope_b64=(
        "eyJwYXlsb2FkIjoiZXlKMlpYSnphVzl1SWpvaWRtTmxjblF0TUM0eUlpd2laR0YwWVhObGRGOW9ZWE5vSWpvaWMyaGhN"
        "alUyT2pBd01EQXdNREF3TURBd01EQXdNREF3TURBd01EQXdNREF3TURBd01EQXdNREF3TURBd01EQXdNREF3TURBd01E"
        "QXdNREF3TURBd01EQXdNREF3TURBaUxDSnpjR1ZqWDJoaGMyZ2lPaUp6YUdFeU5UWTZNVEV4TVRFeE1URXhNVEV4TVRF"
        "eE1URXhNVEV4TVRFeE1URXhNVEV4TVRFeE1URXhNVEV4TVRFeE1URXhNVEV4TVRFeE1URXhNVEV4TVRFeE1URXhNU0lz"
        "SW5Cc2IzUjBaV1JmZEdGaWJHVmZhR0Z6YUNJNkluTm9ZVEkxTmpveU1qSXlNakl5TWpJeU1qSXlNakl5TWpJeU1qSXlN"
        "akl5TWpJeU1qSXlNakl5TWpJeU1qSXlNakl5TWpJeU1qSXlNakl5TWpJeU1qSXlNakl5TWpJeUlpd2liV0Z1YVdabGMz"
        "UmZhR0Z6YUNJNkluTm9ZVEkxTmpvek16TXpNek16TXpNek16TXpNek16TXpNek16TXpNek16TXpNek16TXpNek16TXpN"
        "ek16TXpNek16TXpNek16TXpNek16TXpNek16TXpNek16TXpNeklpd2lkbVZuWVY5c2FYUmxYMmhoYzJnaU9pSnphR0V5"
        "TlRZNk5EUTBORFEwTkRRME5EUTBORFEwTkRRME5EUTBORFEwTkRRME5EUTBORFEwTkRRME5EUTBORFEwTkRRME5EUTBO"
        "RFEwTkRRME5EUTBORFEwTkRRME5DSXNJbU5vWldOcmN5STZXM3NpYVdRaU9pSmtZWFJoYzJWMExtaGhjMmhmYldGMFky"
        "aGxjMTl6YjNWeVkyVWlMQ0p0WlhSb2IyUWlPaUprWlhSbGNtMXBibWx6ZEdsalgzSmxZMjl0Y0hWMFpTSXNJbk4wWVhS"
        "MWN5STZJbkJoYzNNaWZWMHNJbVpwYkhSbGNuTWlPbHQ3SW1acFpXeGtJam9pY21WbmFXOXVJaXdpWTIxd0lqb2laWEVp"
        "TENKMllXeDFaU0k2SWxkbGMzUWlmVjBzSW5OdmNuUnpJanBiZXlKbWFXVnNaQ0k2SW0xdmJuUm9JaXdpYjNKa1pYSWlP"
        "aUpoYzJObGJtUnBibWNpZlYwc0luUmpZaUk2ZXlKMlpYSnBabWxsY2w5MlpYSnphVzl1SWpvaVptbDRaV1F0ZG1WeWFX"
        "WnBaWElpTENKNk0xOTJaWEp6YVc5dUlqb2labWw0WldRdGVqTWlMQ0pqWVc1dmJsOTJaWEp6YVc5dUlqb2labWw0WldR"
        "dFkyRnViMjRpTENKd2VYUm9iMjRpT2lKbWFYaGxaQzF3ZVhSb2IyNGlMQ0p0YzJkemNHVmpJam9pWm1sNFpXUXRiWE5u"
        "YzNCbFl5SXNJblZ1YVdSaGRHRWlPaUptYVhobFpDMTFibWxrWVhSaElpd2lkbXhmWTI5dWRtVnlkRjl3ZVhSb2IyNGlP"
        "aUptYVhobFpDMTJiQzFqYjI1MlpYSjBJaXdpZG14ZmRtVnljMmx2YmlJNklqVXVNakVpTENKbWIyNTBYMlpoYldsc2VT"
        "STZJa1JsYW1GV2RTQlRZVzV6SWl3aWRtVnVaRzl5WldSZlptOXVkRjl6YUdFeU5UWWlPaUp6YUdFeU5UWTZOVFUxTlRV"
        "MU5UVTFOVFUxTlRVMU5UVTFOVFUxTlRVMU5UVTFOVFUxTlRVMU5UVTFOVFUxTlRVMU5UVTFOVFUxTlRVMU5UVTFOVFUx"
        "TlRVMU5UVTFOU0o5ZlE9PSIsInBheWxvYWRUeXBlIjoiYXBwbGljYXRpb24vdm5kLmZpZ3VyZS12ZXJpZmljYXRpb24u"
        "dmNlcnQudjAuMitqc29uIiwic2lnbmF0dXJlcyI6W3sia2V5aWQiOiJzaGEyNTY6YWFhYWFhYWFhYWFhYWFhYWFhYWFh"
        "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYSIsInNpZyI6IlFoeFNDb1dXTERkK1RqdlRk"
        "SlRFUmt6TVRUVUZoNmFyRHgrN1V1YXYxSGJ4azRaN1htRVR1TFdIeWcxa0FISEgrMWg4SkpmTCs5WjF4aklaajRtL0Nn"
        "PT0ifV19"
    ),
    envelope_sha256="32c56a965e8c823a80e750ab67a926a35f33bd6c79309ac585e9f02a3d2e60f2",
    payload_length=1036,
    payload_sha256="bf72f1ccd6f4ea5043b6b2871e4ee492dbe4a8acc7d3a490390770dab979d20a",
)
_V03_VECTOR = _EnvelopeVector(
    seed_hex=_FIXED_SEED_HEX,
    keyid=_FIXED_KEYID,
    envelope_b64=(
        "eyJwYXlsb2FkIjoiZXlKMlpYSnphVzl1SWpvaWRtTmxjblF0TUM0eklpd2ljMjkxY21ObElqcDdJbXRwYm1RaU9pSm1i"
        "M0p0ZFd4aElpd2labTl5YlhWc1lWOW9ZWE5vSWpvaWMyaGhNalUyT2pBd01EQXdNREF3TURBd01EQXdNREF3TURBd01E"
        "QXdNREF3TURBd01EQXdNREF3TURBd01EQXdNREF3TURBd01EQXdNREF3TURBd01EQXdNREF3TURBaWZTd2ljM0JsWTE5"
        "b1lYTm9Jam9pYzJoaE1qVTJPakV4TVRFeE1URXhNVEV4TVRFeE1URXhNVEV4TVRFeE1URXhNVEV4TVRFeE1URXhNVEV4"
        "TVRFeE1URXhNVEV4TVRFeE1URXhNVEV4TVRFeE1URXhNVEVpTENKd2JHOTBkR1ZrWDNSaFlteGxYMmhoYzJnaU9pSnph"
        "R0V5TlRZNk1qSXlNakl5TWpJeU1qSXlNakl5TWpJeU1qSXlNakl5TWpJeU1qSXlNakl5TWpJeU1qSXlNakl5TWpJeU1q"
        "SXlNakl5TWpJeU1qSXlNakl5TWpJeU1pSXNJbUZ5ZEdsbVlXTjBJanA3SW10cGJtUWlPaUp0WVhSd2JHOTBiR2xpTFhO"
        "amNtbHdkQ0lzSW0xaGRIQnNiM1JzYVdKZmMyTnlhWEIwWDJoaGMyZ2lPaUp6YUdFeU5UWTZNek16TXpNek16TXpNek16"
        "TXpNek16TXpNek16TXpNek16TXpNek16TXpNek16TXpNek16TXpNek16TXpNek16TXpNek16TXpNek16TXpNek16TXpN"
        "eUo5TENKamFHVmphM01pT2x0N0ltbGtJam9pWm05eWJYVnNZUzV6YjNWeVkyVmZjR0Z5YzJWeklpd2liV1YwYUc5a0lq"
        "b2ljMk5vWlcxaFgzWmhiR2xrWVhScGIyNGlMQ0p6ZEdGMGRYTWlPaUp3WVhOekluMWRMQ0owWTJJaU9uc2lhMmx1WkNJ"
        "NkltWnZjbTExYkdFaUxDSjJaWEpwWm1sbGNsOTJaWEp6YVc5dUlqb2labWw0WldRdGRtVnlhV1pwWlhJaUxDSjZNMTky"
        "WlhKemFXOXVJam9pWm1sNFpXUXRlak1pTENKallXNXZibDkyWlhKemFXOXVJam9pWm1sNFpXUXRZMkZ1YjI0aUxDSndl"
        "WFJvYjI0aU9pSm1hWGhsWkMxd2VYUm9iMjRpTENKdGMyZHpjR1ZqSWpvaVptbDRaV1F0YlhObmMzQmxZeUlzSW5WdWFX"
        "UmhkR0VpT2lKbWFYaGxaQzExYm1sa1lYUmhJaXdpWjNKaGJXMWhjbDkyWlhKemFXOXVJam9pWm1sNFpXUXRaM0poYlcx"
        "aGNpSXNJbTUxYldWeWFXTmZjSEp2Wm1sc1pTSTZJbkpoZEdsdmJtRnNMV2hoYkdZdFpYWmxiaTEyTVNJc0luTmpjbWx3"
        "ZEY5MFpXMXdiR0YwWlY5MlpYSnphVzl1SWpvaVptbDRaV1F0ZEdWdGNHeGhkR1VpZlgwPSIsInBheWxvYWRUeXBlIjoi"
        "YXBwbGljYXRpb24vdm5kLmZpZ3VyZS12ZXJpZmljYXRpb24udmNlcnQudjAuMytqc29uIiwic2lnbmF0dXJlcyI6W3si"
        "a2V5aWQiOiJzaGEyNTY6YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFh"
        "YWFhYWFhYWFhYSIsInNpZyI6Ijg5eWduYnpCbWNZc3liL0hQZ0VET2xnNWMrc2E0SDVIUjAwOWRFYUpqdXZFWWNPN0di"
        "djVJeStBZFF0U0dzUlFRSGxoU2Z0MWlvdExKeVNCVHU4Y0FBPT0ifV19"
    ),
    envelope_sha256="840494c69aa07c06f1f41f4d2b5ae57fb91bf0d7093d92bea720dcba3e8e5883",
    payload_length=857,
    payload_sha256="e1a14d36d84f703499568998016cb369b73d82994f0f5b06bbbf4ff02de3c078",
)


def _limits(max_payload_bytes: int) -> VerificationLimits:
    return msgspec.structs.replace(DEFAULT_LIMITS, max_attestation_bytes=max_payload_bytes)


def _wire(envelope: bytes) -> dict[str, Any]:
    return cast("dict[str, Any]", msgspec.json.decode(envelope))


def _encoded(wire: dict[str, Any]) -> bytes:
    return msgspec.json.encode(wire)


def _vector_envelope(vector: _EnvelopeVector) -> bytes:
    return base64.b64decode(vector.envelope_b64, validate=True)


def _vector_payload(vector: _EnvelopeVector) -> bytes:
    encoded = cast("str", _wire(_vector_envelope(vector))["payload"])
    return base64.b64decode(encoded, validate=True)


def _signed(payload: bytes, *, payload_type: str) -> bytes:
    return attestation.sign_dsse(
        payload,
        _FIXED_PRIVATE_KEY,
        keyid=_FIXED_KEYID,
        payload_type=payload_type,
        max_payload_bytes=DEFAULT_LIMITS.max_attestation_bytes,
    )


def _decoder_bomb(
    monkeypatch: pytest.MonkeyPatch,
    decoder_name: str,
    refusal: str,
) -> list[bytes]:
    calls: list[bytes] = []

    def bomb(payload: bytes) -> NoReturn:
        calls.append(payload)
        pytest.fail(f"{refusal} reached application decoder {decoder_name}")

    monkeypatch.setattr(attestation, decoder_name, bomb)
    return calls


def _formula_certificate() -> vcert.VCertV03:
    """Real f02 certificate under the fixed vector TCB, byte-stable across measured interpreters."""
    spec = decode_formula_spec(_FORMULA_SPEC.read_bytes())
    evidence = checks.verify_formula_run(spec).require_evidence()
    prepared = cast(
        "formula_prepare.PreparedFormula",
        formula_prepare.prepare_formula(spec, evidence).prepared,
    )
    artifact = cast(
        "matplotlib_script.MatplotlibScriptArtifact",
        matplotlib_script.emit_matplotlib_script(prepared).artifact,
    )
    return vcert.build_formula_certificate(artifact, tcb=FORMULA_TCB)


def _v03_payload_failure(kind: str) -> bytes:  # noqa: PLR0911
    payload = _vector_payload(_V03_VECTOR)
    if kind == "malformed":
        return b"{"
    if kind == "unknown-field":
        wire = _wire(payload)
        wire["future"] = True
        return _encoded(wire)
    if kind == "duplicate-top-level":
        return payload.replace(
            b'{"version":"vcert-0.3",',
            b'{"version":"vcert-0.3","version":"vcert-0.3",',
            1,
        )
    if kind == "duplicate-nested":
        return payload.replace(
            b'{"kind":"formula",',
            b'{"kind":"formula","kind":"formula",',
            1,
        )
    if kind == "near-miss-version":
        wire = _wire(payload)
        wire["version"] = "vcert-0.30"
        return _encoded(wire)
    if kind == "mixed-correlation":
        wire = _wire(payload)
        wire["artifact"] = {
            "kind": "vega-lite",
            "vega_lite_hash": "sha256:" + "4" * 64,
        }
        return _encoded(wire)
    if kind == "invalid-utf8":
        return payload.replace(b'"fixed-verifier"', b'"\xff"', 1)
    if kind == "lone-surrogate":
        return payload.replace(b'"fixed-verifier"', b'"\\ud800"', 1)
    message = f"unknown payload failure kind: {kind}"
    raise AssertionError(message)


def _shape_failure(kind: str) -> bytes:  # noqa: PLR0911, PLR0912
    if kind == "malformed":
        return b"{"
    if kind == "non-object":
        return b"[]"
    if kind == "missing-payload":
        return b'{"payloadType":"x","signatures":[{"sig":""}]}'
    if kind == "missing-payload-type":
        return b'{"payload":"","signatures":[{"sig":""}]}'
    if kind == "missing-signatures":
        return b'{"payload":"","payloadType":"x"}'
    if kind == "payload-wrong-type":
        return b'{"payload":1,"payloadType":"x","signatures":[{"sig":""}]}'
    if kind == "payload-type-wrong-type":
        return b'{"payload":"","payloadType":1,"signatures":[{"sig":""}]}'
    if kind == "signatures-wrong-type":
        return b'{"payload":"","payloadType":"x","signatures":{}}'
    if kind == "zero-signatures":
        return b'{"payload":"","payloadType":"x","signatures":[]}'
    if kind == "two-signatures":
        return b'{"payload":"","payloadType":"x","signatures":[{"sig":""},{"sig":""}]}'
    if kind == "missing-sig":
        return b'{"payload":"","payloadType":"x","signatures":[{}]}'
    if kind == "sig-wrong-type":
        return b'{"payload":"","payloadType":"x","signatures":[{"sig":1}]}'
    if kind == "keyid-wrong-type":
        return b'{"payload":"","payloadType":"x","signatures":[{"sig":"","keyid":null}]}'
    envelope = _vector_envelope(_V03_VECTOR)
    if kind == "duplicate-outer":
        return envelope.replace(b'{"payload":', b'{"payload":"","payload":', 1)
    if kind == "duplicate-inner":
        return envelope.replace(b'{"keyid":', b'{"sig":"","keyid":', 1)
    message = f"unknown envelope failure kind: {kind}"
    raise AssertionError(message)


def test_v02_fixed_envelope_vector_remains_byte_exact() -> None:
    """P1/P8: the v0.2 wrapper remains byte-identical for a fixed payload/key/keyid."""
    payload = _vector_payload(_V02_VECTOR)
    certificate = vcert.decode_vcert(payload)
    actual = attestation.sign_vcert(
        certificate,
        Ed25519PrivateKey.from_private_bytes(bytes.fromhex(_V02_VECTOR.seed_hex)),
        keyid=_V02_VECTOR.keyid,
    )
    expected = _vector_envelope(_V02_VECTOR)
    assert _V02_VECTOR.seed_hex == _FIXED_SEED.hex()
    assert _V02_VECTOR.keyid == _FIXED_KEYID
    assert len(payload) == _V02_VECTOR.payload_length
    assert hashlib.sha256(payload).hexdigest() == _V02_VECTOR.payload_sha256
    assert actual == expected
    assert hashlib.sha256(actual).hexdigest() == _V02_VECTOR.envelope_sha256


def test_v03_fixed_envelope_vector_is_independently_pinned() -> None:
    """P8: fixed expected bytes are static; only the actual envelope uses the producer."""
    payload = _vector_payload(_V03_VECTOR)
    certificate = vcert.decode_vcert_v03(payload)
    actual = attestation.sign_vcert_v03(
        certificate,
        Ed25519PrivateKey.from_private_bytes(bytes.fromhex(_V03_VECTOR.seed_hex)),
        keyid=_V03_VECTOR.keyid,
    )
    expected = _vector_envelope(_V03_VECTOR)
    assert _V03_VECTOR.seed_hex == _FIXED_SEED.hex()
    assert _V03_VECTOR.keyid == _FIXED_KEYID
    assert len(payload) == _V03_VECTOR.payload_length
    assert hashlib.sha256(payload).hexdigest() == _V03_VECTOR.payload_sha256
    assert actual == expected
    assert hashlib.sha256(actual).hexdigest() == _V03_VECTOR.envelope_sha256


def test_v03_real_f02_round_trip_preserves_decoder_payload_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    certificate = _formula_certificate()
    payload = vcert.vcert_v03_bytes(certificate)
    assert certificate.tcb is FORMULA_TCB
    assert len(payload) == 1_847
    assert hashlib.sha256(payload).hexdigest() == (
        "8ebacb571133365af951ddc435f0d80765ce560235ba7a8253ea5121c28e5905"
    )
    envelope = attestation.sign_vcert_v03(certificate, _FIXED_PRIVATE_KEY, keyid=_FIXED_KEYID)
    assert _wire(envelope)["payloadType"] == attestation.VCERT_V03_PAYLOAD_TYPE

    original = cast(
        "Callable[[bytes], vcert.VCertV03]",
        attestation._decode_vcert_v03_payload,
    )
    observed: list[bytes] = []

    def recording_decoder(payload: bytes) -> vcert.VCertV03:
        observed.append(payload)
        return original(payload)

    monkeypatch.setattr(attestation, "_decode_vcert_v03_payload", recording_decoder)
    verified = attestation.verify_vcert_v03(envelope, {_FIXED_KEYID: _FIXED_PUBLIC_KEY})
    assert type(verified) is attestation.VerifiedVCertV03
    assert verified.certificate == certificate
    assert len(observed) == 1
    assert verified.payload is observed[0]


def test_v03_sign_rejects_direct_construction_bypass_before_signing() -> None:
    certificate = msgspec.structs.replace(_formula_certificate())
    msgspec.structs.force_setattr(certificate, "version", "vcert-0.2")

    with pytest.raises(msgspec.ValidationError, match=r"\$\.version"):
        attestation.sign_vcert_v03(certificate, _FIXED_PRIVATE_KEY, keyid=_FIXED_KEYID)


def test_verified_v03_result_is_a_frozen_slotted_value() -> None:
    result = attestation.VerifiedVCertV03(payload=b"payload", certificate=_formula_certificate())

    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.payload = b"mutated"  # type: ignore[misc]


def test_exported_certificate_surface_is_closed_to_two_fixed_versions() -> None:
    expected = {
        "MAX_KEYID_BYTES",
        "VCERT_PAYLOAD_TYPE",
        "VCERT_V03_PAYLOAD_TYPE",
        "AttestationError",
        "VerifiedPayload",
        "VerifiedVCert",
        "VerifiedVCertV03",
        "envelope_byte_limit",
        "pae",
        "sign_dsse",
        "sign_vcert",
        "sign_vcert_v03",
        "verify_dsse",
        "verify_vcert",
        "verify_vcert_v03",
    }
    assert set(attestation.__all__) == expected
    assert attestation.VCERT_V03_PAYLOAD_TYPE == _V03_PAYLOAD_TYPE


@pytest.mark.parametrize(
    ("wrapper_name", "decoder_name", "vector"),
    [
        ("verify_vcert", "_decode_vcert_payload", _V02_VECTOR),
        ("verify_vcert_v03", "_decode_vcert_v03_payload", _V03_VECTOR),
    ],
    ids=["v02-wrapper", "v03-wrapper"],
)
def test_each_fixed_wrapper_refuses_correctly_signed_unknown_mime_before_decode(
    monkeypatch: pytest.MonkeyPatch,
    wrapper_name: str,
    decoder_name: str,
    vector: _EnvelopeVector,
) -> None:
    calls = _decoder_bomb(monkeypatch, decoder_name, "correctly signed unknown MIME")
    envelope = _signed(_vector_payload(vector), payload_type=_NEAR_MISS_PAYLOAD_TYPE)
    wrapper = cast(
        "Callable[[bytes, dict[str, Ed25519PublicKey]], object]",
        getattr(attestation, wrapper_name),
    )
    with pytest.raises(attestation.AttestationError, match="unsupported DSSE payload type"):
        wrapper(envelope, {_FIXED_KEYID: _FIXED_PUBLIC_KEY})
    assert calls == []


@pytest.mark.parametrize(
    "payload_type",
    [
        attestation.VCERT_PAYLOAD_TYPE,
        _V03_PAYLOAD_TYPE + ";profile=longer",
    ],
    ids=["sibling-v02", "v03-prefix-extension"],
)
def test_v03_wrapper_refuses_each_nonexact_mime_before_decode(
    monkeypatch: pytest.MonkeyPatch,
    payload_type: str,
) -> None:
    calls = _decoder_bomb(monkeypatch, "_decode_vcert_v03_payload", payload_type)
    envelope = _signed(_vector_payload(_V03_VECTOR), payload_type=payload_type)

    with pytest.raises(attestation.AttestationError, match="unsupported DSSE payload type"):
        attestation.verify_vcert_v03(envelope, {_FIXED_KEYID: _FIXED_PUBLIC_KEY})
    assert calls == []


def test_v02_payload_declared_as_v03_reaches_v03_decoder_and_refuses() -> None:
    envelope = _signed(_vector_payload(_V02_VECTOR), payload_type=_V03_PAYLOAD_TYPE)
    with pytest.raises(attestation.AttestationError, match=r"not a valid VCert v0\.3"):
        attestation.verify_vcert_v03(envelope, {_FIXED_KEYID: _FIXED_PUBLIC_KEY})


def test_v03_payload_declared_as_v02_reaches_v02_decoder_and_refuses() -> None:
    envelope = _signed(_vector_payload(_V03_VECTOR), payload_type=attestation.VCERT_PAYLOAD_TYPE)
    with pytest.raises(attestation.AttestationError, match=r"not a valid VCert v0\.2"):
        attestation.verify_vcert(envelope, {_FIXED_KEYID: _FIXED_PUBLIC_KEY})


@pytest.mark.parametrize(
    "kind",
    [
        "malformed",
        "unknown-field",
        "duplicate-top-level",
        "duplicate-nested",
        "near-miss-version",
        "mixed-correlation",
        "invalid-utf8",
        "lone-surrogate",
    ],
)
def test_every_v03_payload_failure_is_normalized_before_result_construction(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    construction_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def construction_bomb(*args: object, **kwargs: object) -> NoReturn:
        construction_calls.append((args, kwargs))
        pytest.fail(f"{kind} payload reached VerifiedVCertV03 construction")

    monkeypatch.setattr(attestation, "VerifiedVCertV03", construction_bomb)
    envelope = _signed(_v03_payload_failure(kind), payload_type=_V03_PAYLOAD_TYPE)
    with pytest.raises(attestation.AttestationError) as caught:
        attestation.verify_vcert_v03(envelope, {_FIXED_KEYID: _FIXED_PUBLIC_KEY})
    assert type(caught.value) is attestation.AttestationError
    assert construction_calls == []


def test_v03_payload_wrapper_does_not_hide_unexpected_decoder_defects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defect = RuntimeError("unexpected decoder defect")

    def defective_decoder(_payload: bytes) -> NoReturn:
        raise defect

    monkeypatch.setattr(attestation, "decode_vcert_v03", defective_decoder)
    with pytest.raises(RuntimeError) as caught:
        attestation._decode_vcert_v03_payload(b"payload")
    assert caught.value is defect


def test_v03_unknown_envelope_and_signature_fields_pass_without_canonical_mode() -> None:
    wire = _wire(_vector_envelope(_V03_VECTOR))
    wire["future"] = {"version": 4}
    signatures = cast("list[dict[str, Any]]", wire["signatures"])
    signatures[0]["futureSignatureMetadata"] = [1, 2]
    verified = attestation.verify_vcert_v03(
        _encoded(wire),
        {_FIXED_KEYID: _FIXED_PUBLIC_KEY},
    )
    assert verified.payload == _vector_payload(_V03_VECTOR)
    assert verified.certificate == vcert.decode_vcert_v03(verified.payload)


def test_certificate_ceiling_uses_each_fixed_mime_and_length_not_identity() -> None:
    maximum = DEFAULT_LIMITS.max_attestation_bytes
    v02 = attestation.envelope_byte_limit(
        maximum,
        payload_type=attestation.VCERT_PAYLOAD_TYPE,
    )
    v03 = attestation.envelope_byte_limit(maximum, payload_type=_V03_PAYLOAD_TYPE)
    longer = attestation.envelope_byte_limit(
        maximum,
        payload_type=_V03_PAYLOAD_TYPE + ";profile=longer",
    )
    assert len(attestation.VCERT_PAYLOAD_TYPE.encode()) == 51
    assert len(_V03_PAYLOAD_TYPE.encode()) == 51
    assert v02 == v03 == 1_399_079
    assert longer > v03


def test_each_certificate_wrapper_derives_its_ceiling_from_its_own_declared_mime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P7: each public wrapper hands the ceiling helper its OWN fixed MIME, exactly once.

    Both certificate MIMEs are 51 bytes today, so the ceilings agree numerically and an
    implementation that hardcoded either type would produce identical output. Observing the
    argument rather than the result keeps the own-profile guarantee pinned once the lengths differ.
    """
    v02_certificate = vcert.decode_vcert(_vector_payload(_V02_VECTOR))
    v03_certificate = vcert.decode_vcert_v03(_vector_payload(_V03_VECTOR))
    trusted = {_FIXED_KEYID: _FIXED_PUBLIC_KEY}
    observed: list[str] = []
    original = attestation.envelope_byte_limit

    def recording_limit(max_payload_bytes: int, *, payload_type: str = _V02_PAYLOAD_TYPE) -> int:
        observed.append(payload_type)
        return original(max_payload_bytes, payload_type=payload_type)

    monkeypatch.setattr(attestation, "envelope_byte_limit", recording_limit)
    operations: tuple[tuple[Callable[[], object], str], ...] = (
        (
            lambda: attestation.sign_vcert(v02_certificate, _FIXED_PRIVATE_KEY, keyid=_FIXED_KEYID),
            _V02_PAYLOAD_TYPE,
        ),
        (
            lambda: attestation.verify_vcert(_vector_envelope(_V02_VECTOR), trusted),
            _V02_PAYLOAD_TYPE,
        ),
        (
            lambda: attestation.sign_vcert_v03(
                v03_certificate, _FIXED_PRIVATE_KEY, keyid=_FIXED_KEYID
            ),
            _V03_PAYLOAD_TYPE,
        ),
        (
            lambda: attestation.verify_vcert_v03(_vector_envelope(_V03_VECTOR), trusted),
            _V03_PAYLOAD_TYPE,
        ),
    )
    for operation, expected in operations:
        observed.clear()
        operation()
        assert observed == [expected]
    assert attestation.VCERT_PAYLOAD_TYPE == _V02_PAYLOAD_TYPE


def test_v02_invalid_utf8_authenticated_payload_refuses_before_result_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P9: the v0.2 profile refuses non-UTF-8 authenticated bytes as strictly as v0.3 does.

    The raw byte sits in a free-form string, so a tolerant codec would replacement-decode it into
    a schema-valid certificate and admit the tamper class instead of refusing it.
    """
    payload = _vector_payload(_V02_VECTOR).replace(b"DejaVu Sans", b"\xffejaVu Sans", 1)
    assert payload.count(b"\xff") == 1
    construction_calls: list[object] = []

    def construction_bomb(*args: object, **kwargs: object) -> NoReturn:
        construction_calls.append((args, kwargs))
        pytest.fail("invalid UTF-8 v0.2 payload reached VerifiedVCert construction")

    monkeypatch.setattr(attestation, "VerifiedVCert", construction_bomb)
    envelope = _signed(payload, payload_type=attestation.VCERT_PAYLOAD_TYPE)
    with pytest.raises(attestation.AttestationError, match=r"not a valid VCert v0\.2") as caught:
        attestation.verify_vcert(envelope, {_FIXED_KEYID: _FIXED_PUBLIC_KEY})
    assert isinstance(caught.value.__cause__, UnicodeDecodeError)
    assert construction_calls == []


def test_v03_sign_threads_stricter_caller_limit_before_pae(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _vector_payload(_V03_VECTOR)
    pae_calls: list[tuple[str, bytes]] = []

    def pae_bomb(payload_type: str, signed_payload: bytes) -> NoReturn:
        pae_calls.append((payload_type, signed_payload))
        pytest.fail("oversized VCert v0.3 reached PAE/signature construction")

    monkeypatch.setattr(attestation, "pae", pae_bomb)
    with pytest.raises(
        VerificationError,
        match=rf"^VCert payload has {len(payload)} bytes; limit is {len(payload) - 1}$",
    ) as caught:
        attestation.sign_vcert_v03(
            vcert.decode_vcert_v03(payload),
            _FIXED_PRIVATE_KEY,
            keyid=_FIXED_KEYID,
            limits=_limits(len(payload) - 1),
        )
    assert caught.value.check == "resource.attestation_bytes"
    assert pae_calls == []


def test_v03_oversized_envelope_refuses_before_json_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limits = _limits(1)
    ceiling = attestation.envelope_byte_limit(1, payload_type=_V03_PAYLOAD_TYPE)
    parse_calls: list[bytes] = []

    def parse_bomb(envelope: bytes) -> NoReturn:
        parse_calls.append(envelope)
        pytest.fail("oversized v0.3 envelope reached JSON parsing")

    monkeypatch.setattr(attestation, "_parse_envelope", parse_bomb)
    with pytest.raises(VerificationError, match=rf"limit is {ceiling}") as caught:
        attestation.verify_vcert_v03(
            b"x" * (ceiling + 1),
            {_FIXED_KEYID: _FIXED_PUBLIC_KEY},
            limits=limits,
        )
    assert caught.value.check == "resource.attestation_bytes"
    assert parse_calls == []


def test_v03_oversized_encoded_payload_refuses_before_base64_or_application_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application_calls = _decoder_bomb(
        monkeypatch,
        "_decode_vcert_v03_payload",
        "oversized encoded payload",
    )
    base64_calls: list[tuple[str, str]] = []

    def base64_bomb(value: str, *, field: str) -> NoReturn:
        base64_calls.append((value, field))
        pytest.fail("oversized encoded payload reached base64 decoding")

    monkeypatch.setattr(attestation, "_decode_base64", base64_bomb)
    envelope = _signed(b"four", payload_type=_V03_PAYLOAD_TYPE)
    with pytest.raises(VerificationError, match="base64 exceeds") as caught:
        attestation.verify_vcert_v03(
            envelope,
            {_FIXED_KEYID: _FIXED_PUBLIC_KEY},
            limits=_limits(3),
        )
    assert caught.value.check == "resource.attestation_bytes"
    assert base64_calls == []
    assert application_calls == []


def test_v03_oversized_decoded_payload_refuses_before_application_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _decoder_bomb(
        monkeypatch,
        "_decode_vcert_v03_payload",
        "oversized decoded payload",
    )
    envelope = _signed(b"xx", payload_type=_V03_PAYLOAD_TYPE)
    with pytest.raises(
        VerificationError,
        match=r"^VCert payload has 2 bytes; limit is 1$",
    ) as caught:
        attestation.verify_vcert_v03(
            envelope,
            {_FIXED_KEYID: _FIXED_PUBLIC_KEY},
            limits=_limits(1),
        )
    assert caught.value.check == "resource.attestation_bytes"
    assert calls == []


@pytest.mark.parametrize(
    "kind",
    [
        "bad-signature",
        "wrong-trusted-key",
        "mime-mutation-without-resigning",
        "payload-mutation-without-resigning",
    ],
)
def test_v03_unresigned_authentication_mutations_refuse_before_payload_decode(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    """These witnesses mutate authenticated material without re-signing."""
    calls = _decoder_bomb(monkeypatch, "_decode_vcert_v03_payload", kind)
    wire = _wire(_vector_envelope(_V03_VECTOR))
    trusted = {_FIXED_KEYID: _FIXED_PUBLIC_KEY}
    if kind == "bad-signature":
        signatures = cast("list[dict[str, Any]]", wire["signatures"])
        raw = bytearray(base64.b64decode(cast("str", signatures[0]["sig"]), validate=True))
        raw[0] ^= 1
        signatures[0]["sig"] = base64.b64encode(raw).decode()
    elif kind == "wrong-trusted-key":
        wrong = Ed25519PrivateKey.from_private_bytes(bytes(range(31, -1, -1)))
        trusted = {"wrong": wrong.public_key()}
    elif kind == "mime-mutation-without-resigning":
        wire["payloadType"] = _NEAR_MISS_PAYLOAD_TYPE
    elif kind == "payload-mutation-without-resigning":
        raw = bytearray(base64.b64decode(cast("str", wire["payload"]), validate=True))
        raw[0] ^= 1
        wire["payload"] = base64.b64encode(raw).decode()
    else:
        message = f"unknown authentication mutation kind: {kind}"
        raise AssertionError(message)
    with pytest.raises(attestation.AttestationError, match="signature is not valid"):
        attestation.verify_vcert_v03(_encoded(wire), trusted)
    assert calls == []


@pytest.mark.parametrize(
    "kind",
    [
        "malformed",
        "non-object",
        "missing-payload",
        "missing-payload-type",
        "missing-signatures",
        "payload-wrong-type",
        "payload-type-wrong-type",
        "signatures-wrong-type",
        "zero-signatures",
        "two-signatures",
        "missing-sig",
        "sig-wrong-type",
        "keyid-wrong-type",
        "duplicate-outer",
        "duplicate-inner",
    ],
)
def test_each_v03_envelope_shape_refusal_precedes_application_decode(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    calls = _decoder_bomb(monkeypatch, "_decode_vcert_v03_payload", kind)
    with pytest.raises(attestation.AttestationError, match="envelope JSON or shape"):
        attestation.verify_vcert_v03(
            _shape_failure(kind),
            {_FIXED_KEYID: _FIXED_PUBLIC_KEY},
        )
    assert calls == []


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("alphabet-mixing", "mixes standard and URL-safe"),
        ("noncanonical-padding", "not canonical padded"),
        ("signature-encoded-length", "invalid base64 length"),
        ("signature-raw-length", "not a 64-byte"),
    ],
)
def test_each_v03_base64_refusal_precedes_application_decode(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    message: str,
) -> None:
    calls = _decoder_bomb(monkeypatch, "_decode_vcert_v03_payload", kind)
    wire = _wire(_vector_envelope(_V03_VECTOR))
    signatures = cast("list[dict[str, Any]]", wire["signatures"])
    if kind == "alphabet-mixing":
        wire["payload"] = "+/8_"
    elif kind == "noncanonical-padding":
        wire["payload"] = "AB=="
    elif kind == "signature-encoded-length":
        signatures[0]["sig"] = ""
    elif kind == "signature-raw-length":
        signatures[0]["sig"] = base64.b64encode(b"x" * 66).decode()
    else:
        message = f"unknown base64 refusal kind: {kind}"
        raise AssertionError(message)
    with pytest.raises(attestation.AttestationError, match=message):
        attestation.verify_vcert_v03(_encoded(wire), {_FIXED_KEYID: _FIXED_PUBLIC_KEY})
    assert calls == []


def test_v03_overlength_envelope_keyid_refuses_before_application_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _decoder_bomb(monkeypatch, "_decode_vcert_v03_payload", "overlength keyid")
    wire = _wire(_vector_envelope(_V03_VECTOR))
    signatures = cast("list[dict[str, Any]]", wire["signatures"])
    signatures[0]["keyid"] = "x" * (attestation.MAX_KEYID_BYTES + 1)
    with pytest.raises(attestation.AttestationError, match="keyid hint"):
        attestation.verify_vcert_v03(_encoded(wire), {_FIXED_KEYID: _FIXED_PUBLIC_KEY})
    assert calls == []


def test_v03_expected_keyid_uses_caller_declaration_not_envelope_intrinsic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _decoder_bomb(monkeypatch, "_decode_vcert_v03_payload", "keyid disagreement")
    different_hint = "sha256:" + "b" * 64
    with pytest.raises(attestation.AttestationError, match="disagrees"):
        attestation.verify_vcert_v03(
            _vector_envelope(_V03_VECTOR),
            {_FIXED_KEYID: _FIXED_PUBLIC_KEY},
            expected_keyid_hint=different_hint,
        )
    assert calls == []


@pytest.mark.parametrize("wrapper_name", ["verify_vcert", "verify_vcert_v03"])
def test_certificate_bool_guard_precedes_dsse_verification(
    monkeypatch: pytest.MonkeyPatch,
    wrapper_name: str,
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def verification_bomb(*args: object, **kwargs: object) -> NoReturn:
        calls.append((args, kwargs))
        pytest.fail("invalid certificate wrapper flag reached DSSE verification")

    monkeypatch.setattr(attestation, "_verify_dsse", verification_bomb)
    wrapper = cast("Any", getattr(attestation, wrapper_name))
    with pytest.raises(TypeError, match="require_canonical_envelope must be a bool"):
        wrapper(b"unparsed", {}, require_canonical_envelope=cast("bool", 1))
    assert calls == []


@pytest.mark.parametrize("wrapper_name", ["verify_vcert", "verify_vcert_v03"])
def test_certificate_expected_keyid_guard_precedes_dsse_verification(
    monkeypatch: pytest.MonkeyPatch,
    wrapper_name: str,
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def verification_bomb(*args: object, **kwargs: object) -> NoReturn:
        calls.append((args, kwargs))
        pytest.fail("invalid expected keyid reached DSSE verification")

    monkeypatch.setattr(attestation, "_verify_dsse", verification_bomb)
    wrapper = cast("Any", getattr(attestation, wrapper_name))
    with pytest.raises(ValueError, match="expected keyid must be a non-empty string"):
        wrapper(b"unparsed", {}, expected_keyid_hint=cast("str", 1))
    assert calls == []


def test_v03_correctly_resigned_well_formed_mutation_is_authentic_attestation() -> None:
    """Trusted re-sign passes; archive/replay owns cross-artifact semantic disagreement."""
    original = vcert.decode_vcert_v03(_vector_payload(_V03_VECTOR))
    mutated = msgspec.structs.replace(original, spec_hash="sha256:" + "f" * 64)
    envelope = attestation.sign_vcert_v03(mutated, _FIXED_PRIVATE_KEY, keyid=_FIXED_KEYID)
    verified = attestation.verify_vcert_v03(envelope, {_FIXED_KEYID: _FIXED_PUBLIC_KEY})
    assert mutated != original
    assert verified.certificate == mutated
    assert verified.payload == vcert.vcert_v03_bytes(mutated)


def test_v03_require_canonical_envelope_is_threaded_to_the_shared_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-canonical producer bytes verify by default and refuse under the stricter caller flag."""
    wire = _wire(_vector_envelope(_V03_VECTOR))
    wire["future"] = {"unknown": True}
    noncanonical = _encoded(wire)
    assert noncanonical != _vector_envelope(_V03_VECTOR)
    relaxed = attestation.verify_vcert_v03(noncanonical, {_FIXED_KEYID: _FIXED_PUBLIC_KEY})
    assert relaxed.certificate == vcert.decode_vcert_v03(_vector_payload(_V03_VECTOR))

    calls = _decoder_bomb(monkeypatch, "_decode_vcert_v03_payload", "non-canonical envelope")
    with pytest.raises(attestation.AttestationError, match="canonical deterministic JSON"):
        attestation.verify_vcert_v03(
            noncanonical,
            {_FIXED_KEYID: _FIXED_PUBLIC_KEY},
            require_canonical_envelope=True,
        )
    assert calls == []
