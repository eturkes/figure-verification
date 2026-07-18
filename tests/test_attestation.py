# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M5.3a DSSE v1.0.2 / Ed25519 profile vectors, adversarial decode, and resource order."""

import base64
from collections.abc import Callable
from typing import Any, cast

import msgspec
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from verifier import attestation, render
from verifier.errors import VerificationError
from verifier.limits import DEFAULT_LIMITS, VerificationLimits

_KEYID = "sha256:" + "a" * 64
_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
_PUBLIC_KEY = _PRIVATE_KEY.public_key()


def _certificate() -> render.VCert:
    return render.VCert(
        version="vcert-0.2",
        dataset_hash="sha256:" + "0" * 64,
        spec_hash="sha256:" + "1" * 64,
        plotted_table_hash="sha256:" + "2" * 64,
        manifest_hash="sha256:" + "3" * 64,
        vega_lite_hash="sha256:" + "4" * 64,
        checks=(
            render.CertifiedCheck(
                id="dataset.hash_matches_source", method="deterministic_recompute", status="pass"
            ),
        ),
        filters=(render.DisclosedFilter(field="region", cmp="eq", value="West"),),
        sorts=(render.DisclosedSort(field="month", order="ascending"),),
        tcb=render.Tcb(
            verifier_version="0.2.0",
            z3_version="4.16.0",
            canon_version="canon-0.1",
            python="3.13.0",
            msgspec="0.21.0",
            unidata="16.0.0",
            vl_convert_python="1.9.0",
            vl_version="5.21",
            font_family="DejaVu Sans",
            vendored_font_sha256="sha256:" + "5" * 64,
        ),
    )


def _limits(max_payload_bytes: int) -> VerificationLimits:
    return msgspec.structs.replace(DEFAULT_LIMITS, max_attestation_bytes=max_payload_bytes)


def _wire(envelope: bytes) -> dict[str, Any]:
    return cast("dict[str, Any]", msgspec.json.decode(envelope))


def _encoded(wire: dict[str, Any]) -> bytes:
    return msgspec.json.encode(wire)


def _signed(
    payload: bytes,
    *,
    payload_type: str = attestation.VCERT_PAYLOAD_TYPE,
    keyid: str = _KEYID,
) -> bytes:
    signature = _PRIVATE_KEY.sign(attestation.pae(payload_type, payload))
    return attestation._encode_envelope(payload, signature, keyid, payload_type=payload_type)


def _envelope() -> bytes:
    return attestation.sign_vcert(_certificate(), _PRIVATE_KEY, keyid=_KEYID)


def test_official_dsse_v1_0_2_pae_and_envelope_vector() -> None:
    """Vector from secure-systems-lab/dsse v1.0.2 protocol + reference implementation."""
    payload_type = "http://example.com/HelloWorld"
    payload = b"hello world"
    signature_text = (
        "A3JqsQGtVsJ2O2xqrI5IcnXip5GToJ3F+FnZ+O88SjtR6rDAajabZKciJTfUiHqJPcIAriEGAHTVeCUjW2JIZA=="
    )
    signature = base64.standard_b64decode(signature_text)

    assert attestation.pae(payload_type, payload) == (
        b"DSSEv1 29 http://example.com/HelloWorld 11 hello world"
    )
    expected = (
        b'{"payload":"aGVsbG8gd29ybGQ=","payloadType":"http://example.com/HelloWorld",'
        b'"signatures":[{"keyid":"66301bbf","sig":"' + signature_text.encode() + b'"}]}'
    )
    assert (
        attestation._encode_envelope(payload, signature, "66301bbf", payload_type=payload_type)
        == expected
    )
    decoded = attestation._parse_envelope(expected)
    assert decoded.payload_type == payload_type
    assert attestation._decode_base64(decoded.signatures[0].sig, field="signature") == signature


def test_pae_lengths_utf8_bytes_not_code_points() -> None:
    assert attestation.pae("é", "ø".encode()) == b"DSSEv1 2 \xc3\xa9 2 \xc3\xb8"


def test_generated_key_sign_verify_is_canonical_and_deterministic() -> None:
    certificate = _certificate()
    generated_key = Ed25519PrivateKey.generate()
    first = attestation.sign_vcert(certificate, generated_key, keyid=_KEYID)
    second = attestation.sign_vcert(certificate, generated_key, keyid=_KEYID)
    assert first == second  # Ed25519 + canonical envelope are deterministic.

    wire = _wire(first)
    assert list(wire) == ["payload", "payloadType", "signatures"]
    assert list(wire["signatures"][0]) == ["keyid", "sig"]
    assert wire["signatures"][0]["keyid"] == _KEYID
    assert wire["payloadType"] == attestation.VCERT_PAYLOAD_TYPE
    assert len(first) <= attestation.envelope_byte_limit(DEFAULT_LIMITS.max_attestation_bytes)

    verified = attestation.verify_vcert(first, {_KEYID: generated_key.public_key()})
    assert verified.payload == render.vcert_bytes(certificate)
    assert verified.certificate == certificate


def test_urlsafe_payload_and_signature_base64_are_accepted() -> None:
    wire = _wire(_envelope())
    for field, value in (
        ("payload", wire["payload"]),
        ("sig", wire["signatures"][0]["sig"]),
    ):
        raw = base64.standard_b64decode(value)
        replacement = base64.urlsafe_b64encode(raw).decode()
        if field == "payload":
            wire[field] = replacement
        else:
            wire["signatures"][0][field] = replacement
    assert "-" in wire["signatures"][0]["sig"] or "_" in wire["signatures"][0]["sig"]
    assert (
        attestation.verify_vcert(_encoded(wire), {_KEYID: _PUBLIC_KEY}).certificate
        == _certificate()
    )


def test_keyid_tampered_missing_and_empty_are_equivalent_untrusted_hints() -> None:
    wrong_private = Ed25519PrivateKey.generate()
    trusted = {"wrong": wrong_private.public_key(), _KEYID: _PUBLIC_KEY}
    original = _wire(_envelope())
    tampered = _wire(_envelope())
    tampered["signatures"][0]["keyid"] = "wrong"  # wrong key is tried, then fallback succeeds.
    missing = _wire(_envelope())
    del missing["signatures"][0]["keyid"]
    empty = _wire(_envelope())
    empty["signatures"][0]["keyid"] = ""

    results = [
        attestation.verify_vcert(_encoded(item), trusted)
        for item in (original, tampered, missing, empty)
    ]
    assert results == [results[0]] * 4


@pytest.mark.parametrize("field", ["payload", "payloadType", "sig"])
def test_payload_type_and_signature_tamper_are_rejected(field: str) -> None:
    wire = _wire(_envelope())
    if field == "payload":
        raw = bytearray(base64.standard_b64decode(wire[field]))
        raw[0] ^= 1
        wire[field] = base64.standard_b64encode(raw).decode()
    elif field == "payloadType":
        wire[field] = "application/vnd.example.wrong+json"
    else:
        raw = bytearray(base64.standard_b64decode(wire["signatures"][0][field]))
        raw[0] ^= 1
        wire["signatures"][0][field] = base64.standard_b64encode(raw).decode()

    with pytest.raises(attestation.AttestationError, match="signature is not valid"):
        attestation.verify_vcert(_encoded(wire), {_KEYID: _PUBLIC_KEY})


def test_wrong_trusted_key_is_rejected() -> None:
    wrong_key = Ed25519PrivateKey.generate().public_key()
    with pytest.raises(attestation.AttestationError, match="signature is not valid"):
        attestation.verify_vcert(_envelope(), {"wrong": wrong_key})


@pytest.mark.parametrize(
    "envelope",
    [
        b"{",
        b"[]",
        b'{"payloadType":"x","signatures":[{"sig":""}]}',
        b'{"payload":1,"payloadType":"x","signatures":[{"sig":""}]}',
        b'{"payload":"","payloadType":"x"}',
        b'{"payload":"","payloadType":"x","signatures":[]}',
        (b'{"payload":"","payloadType":"x","signatures":[{"sig":""},{"sig":""}]}'),
        b'{"payload":"","payloadType":"x","signatures":[{}]}',
        b'{"payload":"","payloadType":"x","signatures":[{"sig":1}]}',
        b'{"payload":"","payloadType":"x","signatures":[{"sig":"","keyid":null}]}',
        (b'{"payload":"","payload":"AA==","payloadType":"x","signatures":[{"sig":""}]}'),
        (b'{"payload":"","payloadType":"x","signatures":[{"sig":"","sig":"AA=="}]}'),
    ],
    ids=[
        "malformed",
        "non-object",
        "missing-payload",
        "payload-type",
        "missing-signatures",
        "zero-signatures",
        "two-signatures",
        "missing-sig",
        "sig-type",
        "keyid-null",
        "duplicate-outer",
        "duplicate-inner",
    ],
)
def test_envelope_json_duplicate_and_known_shape_fail_closed(envelope: bytes) -> None:
    with pytest.raises(attestation.AttestationError, match="envelope JSON or shape"):
        attestation.verify_vcert(envelope, {_KEYID: _PUBLIC_KEY})


def test_unknown_envelope_and_signature_fields_are_tolerated() -> None:
    wire = _wire(_envelope())
    wire["future"] = {"version": 2}
    wire["signatures"][0]["futureSignatureMetadata"] = [1, 2]
    assert (
        attestation.verify_vcert(_encoded(wire), {_KEYID: _PUBLIC_KEY}).certificate
        == _certificate()
    )


@pytest.mark.parametrize(
    ("encoded", "message"),
    [
        ("é", "not ASCII"),
        ("A===", "not valid"),
        ("AB==", "not canonical"),  # non-zero pad bits; canonical spelling is AA==.
        ("+/8_", "mixes standard and URL-safe"),
    ],
)
def test_base64_strict_rejections(encoded: str, message: str) -> None:
    with pytest.raises(attestation.AttestationError, match=message):
        attestation._decode_base64(encoded, field="test")


def test_base64_standard_urlsafe_and_shared_alphabet_paths() -> None:
    assert attestation._decode_base64("YQ==", field="test") == b"a"  # shared alphabet
    assert attestation._decode_base64("//8=", field="test") == b"\xff\xff"  # standard
    assert attestation._decode_base64("__8=", field="test") == b"\xff\xff"  # URL-safe


def test_signature_base64_length_encoding_and_raw_size_fail_closed() -> None:
    cases = [
        ("", "invalid base64 length"),
        ("!" + "A" * 87, "not valid base64"),
        (base64.standard_b64encode(b"x" * 66).decode(), "not a 64-byte"),
    ]
    for value, message in cases:
        wire = _wire(_envelope())
        wire["signatures"][0]["sig"] = value
        with pytest.raises(attestation.AttestationError, match=message):
            attestation.verify_vcert(_encoded(wire), {_KEYID: _PUBLIC_KEY})


def test_envelope_ceiling_rejects_before_json_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    ceiling = attestation.envelope_byte_limit(1)

    def parse_tripwire(_: bytes) -> attestation._DecodedEnvelope:
        pytest.fail("oversized envelope reached JSON parsing")

    monkeypatch.setattr(attestation, "_parse_envelope", parse_tripwire)
    with pytest.raises(VerificationError, match=rf"limit is {ceiling}") as caught:
        attestation.verify_vcert(b"x" * (ceiling + 1), {_KEYID: _PUBLIC_KEY}, limits=_limits(1))
    assert caught.value.check == "resource.attestation_bytes"


def test_sign_payload_limit_boundary_and_overage() -> None:
    certificate = _certificate()
    size = len(render.vcert_bytes(certificate))
    envelope = attestation.sign_vcert(certificate, _PRIVATE_KEY, keyid=_KEYID, limits=_limits(size))
    assert (
        attestation.verify_vcert(envelope, {_KEYID: _PUBLIC_KEY}, limits=_limits(size)).certificate
        == certificate
    )

    with pytest.raises(VerificationError, match=rf"limit is {size - 1}") as caught:
        attestation.sign_vcert(certificate, _PRIVATE_KEY, keyid=_KEYID, limits=_limits(size - 1))
    assert caught.value.check == "resource.attestation_bytes"


@pytest.mark.parametrize(
    ("max_payload", "payload", "message"),
    [
        (3, b"four", "base64 exceeds"),  # encoded length proves overage before decode.
        (1, b"xx", "payload has 2 bytes"),  # same b64 length as one byte; decoded check catches.
    ],
)
def test_verified_payload_limit_rejects_before_application_parse(
    monkeypatch: pytest.MonkeyPatch, max_payload: int, payload: bytes, message: str
) -> None:
    def application_tripwire(_: bytes) -> render.VCert:
        pytest.fail("oversized payload reached VCert parsing")

    monkeypatch.setattr(attestation, "_decode_vcert_payload", application_tripwire)
    with pytest.raises(VerificationError, match=message) as caught:
        attestation.verify_vcert(
            _signed(payload), {_KEYID: _PUBLIC_KEY}, limits=_limits(max_payload)
        )
    assert caught.value.check == "resource.attestation_bytes"


@pytest.mark.parametrize("value", [-1, cast("int", bool(1)), cast("int", 1.5)])
def test_envelope_byte_limit_rejects_invalid_ceiling(value: int) -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        attestation.envelope_byte_limit(value)


def test_envelope_byte_limit_formula_includes_base64_growth() -> None:
    assert attestation.envelope_byte_limit(0) < attestation.envelope_byte_limit(1)
    assert attestation.envelope_byte_limit(1) == attestation.envelope_byte_limit(2)
    assert attestation.envelope_byte_limit(2) == attestation.envelope_byte_limit(3)
    assert attestation.envelope_byte_limit(3) < attestation.envelope_byte_limit(4)


def test_signature_and_type_reject_before_application_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def application_tripwire(_: bytes) -> render.VCert:
        pytest.fail("unverified/wrong-type payload reached VCert parsing")

    monkeypatch.setattr(attestation, "_decode_vcert_payload", application_tripwire)
    wire = _wire(_envelope())
    raw_signature = bytearray(base64.standard_b64decode(wire["signatures"][0]["sig"]))
    raw_signature[-1] ^= 1
    wire["signatures"][0]["sig"] = base64.standard_b64encode(raw_signature).decode()
    with pytest.raises(attestation.AttestationError, match="signature is not valid"):
        attestation.verify_vcert(_encoded(wire), {_KEYID: _PUBLIC_KEY})

    with pytest.raises(attestation.AttestationError, match="unsupported DSSE payload type"):
        attestation.verify_vcert(
            _signed(render.vcert_bytes(_certificate()), payload_type="application/example+json"),
            {_KEYID: _PUBLIC_KEY},
        )


def test_parser_receives_and_result_returns_same_verified_payload_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original: Callable[[bytes], render.VCert] = attestation._decode_vcert_payload
    observed: list[bytes] = []

    def recording_parser(payload: bytes) -> render.VCert:
        observed.append(payload)
        return original(payload)

    monkeypatch.setattr(attestation, "_decode_vcert_payload", recording_parser)
    result = attestation.verify_vcert(_envelope(), {_KEYID: _PUBLIC_KEY})
    assert len(observed) == 1
    assert result.payload is observed[0]


@pytest.mark.parametrize("kind", ["malformed", "unknown", "duplicate"])
def test_authenticated_vcert_payload_is_strictly_parsed(kind: str) -> None:
    canonical = render.vcert_bytes(_certificate())
    if kind == "malformed":
        payload = b"{"
    elif kind == "unknown":
        wire = cast("dict[str, Any]", msgspec.json.decode(canonical))
        wire["unknown"] = True
        payload = msgspec.json.encode(wire)
    else:
        payload = canonical.replace(
            b'"version":"vcert-0.2"', b'"version":"vcert-0.2","version":"vcert-0.2"'
        )

    with pytest.raises(attestation.AttestationError, match="not a valid VCert"):
        attestation.verify_vcert(_signed(payload), {_KEYID: _PUBLIC_KEY})


def test_keyid_limits_and_utf8_are_enforced_for_producer_and_hint() -> None:
    for keyid in ("", "x" * (attestation.MAX_KEYID_BYTES + 1), "\ud800"):
        with pytest.raises(ValueError, match="keyid"):
            attestation.sign_vcert(_certificate(), _PRIVATE_KEY, keyid=keyid)

    with pytest.raises(attestation.AttestationError, match="keyid hint"):
        attestation._validate_keyid_hint("\ud800")
    wire = _wire(_envelope())
    wire["signatures"][0]["keyid"] = "x" * (attestation.MAX_KEYID_BYTES + 1)
    with pytest.raises(attestation.AttestationError, match="keyid hint"):
        attestation.verify_vcert(_encoded(wire), {_KEYID: _PUBLIC_KEY})


def test_runtime_key_types_and_trusted_key_policy_inputs_fail_closed() -> None:
    with pytest.raises(TypeError, match="private_key"):
        attestation.sign_vcert(_certificate(), cast("Ed25519PrivateKey", object()), keyid=_KEYID)
    with pytest.raises(ValueError, match="at least one"):
        attestation.verify_vcert(_envelope(), {})
    with pytest.raises(ValueError, match="trusted keyid"):
        attestation.verify_vcert(_envelope(), {"": _PUBLIC_KEY})
    with pytest.raises(ValueError, match="trusted keyid"):
        attestation.verify_vcert(
            _envelope(), {"x" * (attestation.MAX_KEYID_BYTES + 1): _PUBLIC_KEY}
        )
    with pytest.raises(TypeError, match="Ed25519PublicKey"):
        attestation.verify_vcert(_envelope(), {_KEYID: cast("Ed25519PublicKey", object())})


def test_required_keyid_runtime_type_and_utf8_fail_closed() -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        attestation._validate_required_keyid(cast("str", 1), subject="test")
    with pytest.raises(ValueError, match="not valid UTF-8"):
        attestation._validate_required_keyid("\ud800", subject="test")
    with pytest.raises(TypeError, match="must be a bool"):
        attestation.verify_vcert(
            _envelope(),
            {_KEYID: _PUBLIC_KEY},
            require_canonical_envelope=cast("bool", 1),
        )
