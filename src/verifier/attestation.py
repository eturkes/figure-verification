# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""DSSE v1.0.2 + Ed25519 profile for exact VCert v0.2 bytes.

This module is deliberately small and algorithm-closed. ``sign_vcert`` canonical-encodes one
JSON DSSE envelope carrying ``render.vcert_bytes(certificate)`` and exactly one PyCA Ed25519
signature. ``verify_vcert`` accepts standard or URL-safe RFC-4648 base64, tries only explicitly
trusted Ed25519 keys, authenticates payload bytes + the application-specific payload type, then
strictly parses those SAME bytes as VCert. It never re-reads the envelope after authentication.

DSSE ``keyid`` is unauthenticated. It is bounded and may reorder candidate keys, but cannot add a
key, remove fallback candidates, affect the returned value, or establish identity. Unknown envelope
fields remain forward-compatible per DSSE; duplicate keys and malformed known-field shapes fail
closed. The envelope/payload ceilings bound both JSON parsing and application parsing. Persistent
signer + independent trust-pin policy live in ``service.identity``; ``service.pipeline`` signs
successful render payloads, while durable archive replay belongs to later M5 units.
"""

import base64
import binascii
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated

import msgspec
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from msgspec import Meta

from verifier.errors import VerificationError
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.render import VCert, vcert_bytes
from verifier.schema import _reject_duplicate_keys

__all__ = [
    "MAX_KEYID_BYTES",
    "VCERT_PAYLOAD_TYPE",
    "AttestationError",
    "VerifiedVCert",
    "envelope_byte_limit",
    "pae",
    "sign_vcert",
    "verify_vcert",
]

VCERT_PAYLOAD_TYPE = "application/vnd.figure-verification.vcert.v0.2+json"
MAX_KEYID_BYTES = 128
_ED25519_SIGNATURE_BYTES = 64


class AttestationError(Exception):
    """A DSSE envelope, signature, payload type, or VCert payload failed verification."""


@dataclass(frozen=True, slots=True)
class VerifiedVCert:
    """Authenticated exact payload bytes and the VCert parsed from that same byte object."""

    payload: bytes
    certificate: VCert


# Decode structs intentionally tolerate unknown fields. Required fields have no defaults; keyid is
# DSSE's sole optional known field and absent normalizes to empty. The one-signature restriction is
# this application's profile, not a claim about general DSSE.
class _DecodedSignature(msgspec.Struct, frozen=True, kw_only=True):
    sig: str
    keyid: str = ""


type _OneDecodedSignature = Annotated[
    tuple[_DecodedSignature, ...], Meta(min_length=1, max_length=1)
]


class _DecodedEnvelope(msgspec.Struct, frozen=True, kw_only=True):
    payload: str
    payload_type: str = msgspec.field(name="payloadType")
    signatures: _OneDecodedSignature


# Separate producer structs keep the canonical DSSE field order (keyid, sig) while the decoder can
# model optional keyid without making required sig a defaulted field.
class _EncodedSignature(msgspec.Struct, frozen=True, kw_only=True):
    keyid: str
    sig: str


class _EncodedEnvelope(msgspec.Struct, frozen=True, kw_only=True):
    payload: str
    payload_type: str = msgspec.field(name="payloadType")
    signatures: tuple[_EncodedSignature, ...]


_ENVELOPE_DECODER = msgspec.json.Decoder(_DecodedEnvelope, strict=True)
_VCERT_DECODER = msgspec.json.Decoder(VCert, strict=True)
_ENVELOPE_ENCODER = msgspec.json.Encoder(order="deterministic")


def _base64_length(raw_bytes: int) -> int:
    """Canonical padded RFC-4648 length for ``raw_bytes`` bytes."""
    return 4 * ((raw_bytes + 2) // 3)


_EMPTY_ENVELOPE = _ENVELOPE_ENCODER.encode(
    _EncodedEnvelope(
        payload="",
        payload_type=VCERT_PAYLOAD_TYPE,
        signatures=(_EncodedSignature(keyid="", sig=""),),
    )
)
_SIGNATURE_BASE64_BYTES = _base64_length(_ED25519_SIGNATURE_BYTES)


def envelope_byte_limit(max_payload_bytes: int) -> int:
    """Raw-envelope ceiling derived from one canonical profile envelope.

    The variable terms are padded base64 payload, fixed-size Ed25519 signature, and a bounded
    keyid. Six JSON source bytes per keyid UTF-8 byte is the worst case (``\\u00xx`` for an ASCII
    control). Unknown/non-canonical envelopes are accepted only while they fit this same resource
    ceiling; protocol extensibility does not grant unbounded parser input.
    """
    if type(max_payload_bytes) is not int or max_payload_bytes < 0:
        msg = f"max_payload_bytes must be a non-negative integer, got {max_payload_bytes!r}"
        raise ValueError(msg)
    return (
        len(_EMPTY_ENVELOPE)
        + _base64_length(max_payload_bytes)
        + _SIGNATURE_BASE64_BYTES
        + 6 * MAX_KEYID_BYTES
    )


def pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE v1 pre-authentication encoding over UTF-8 type bytes + exact payload bytes."""
    type_bytes = payload_type.encode("utf-8")
    return b" ".join(
        (b"DSSEv1", str(len(type_bytes)).encode(), type_bytes, str(len(payload)).encode(), payload)
    )


def _validate_required_keyid(keyid: str, *, subject: str) -> None:
    """Validate a producer/trusted-map keyid; these are trusted caller inputs."""
    keyid_object: object = keyid  # retain a hostile-runtime check across the typed API boundary
    if not isinstance(keyid_object, str) or not keyid:
        msg = f"{subject} keyid must be a non-empty string"
        raise ValueError(msg)
    try:
        size = len(keyid.encode("utf-8"))
    except UnicodeEncodeError as exc:
        msg = f"{subject} keyid is not valid UTF-8"
        raise ValueError(msg) from exc
    if size > MAX_KEYID_BYTES:
        msg = f"{subject} keyid has {size} UTF-8 bytes; limit is {MAX_KEYID_BYTES}"
        raise ValueError(msg)


def _validate_keyid_hint(keyid: str) -> None:
    """Bound the untrusted optional hint without granting it trust semantics."""
    if not keyid:
        return
    try:
        size = len(keyid.encode("utf-8"))
    except UnicodeEncodeError as exc:
        msg = "DSSE keyid hint is not valid UTF-8"
        raise AttestationError(msg) from exc
    if size > MAX_KEYID_BYTES:
        msg = f"DSSE keyid hint has {size} UTF-8 bytes; limit is {MAX_KEYID_BYTES}"
        raise AttestationError(msg)


def _enforce_payload_limit(payload: bytes, max_payload_bytes: int) -> None:
    if len(payload) > max_payload_bytes:
        msg = f"VCert payload has {len(payload)} bytes; limit is {max_payload_bytes}"
        raise VerificationError(msg, check="resource.attestation_bytes")


def _encode_base64(payload: bytes) -> str:
    return base64.standard_b64encode(payload).decode("ascii")


def _decode_base64(value: str, *, field: str) -> bytes:
    """Strict canonical padded standard/URL-safe base64 decode."""
    try:
        raw = value.encode("ascii")
    except UnicodeEncodeError as exc:
        msg = f"DSSE {field} is not ASCII base64"
        raise AttestationError(msg) from exc

    has_standard = b"+" in raw or b"/" in raw
    has_urlsafe = b"-" in raw or b"_" in raw
    if has_standard and has_urlsafe:
        msg = f"DSSE {field} mixes standard and URL-safe base64 alphabets"
        raise AttestationError(msg)
    try:
        decoded = base64.b64decode(raw, altchars=b"-_" if has_urlsafe else None, validate=True)
    except binascii.Error as exc:
        msg = f"DSSE {field} is not valid base64"
        raise AttestationError(msg) from exc

    canonical = (
        base64.urlsafe_b64encode(decoded) if has_urlsafe else base64.standard_b64encode(decoded)
    )
    if raw != canonical:
        msg = f"DSSE {field} is not canonical padded base64"
        raise AttestationError(msg)
    return decoded


def _encode_envelope(
    payload: bytes,
    signature: bytes,
    keyid: str,
    *,
    payload_type: str = VCERT_PAYLOAD_TYPE,
) -> bytes:
    return _ENVELOPE_ENCODER.encode(
        _EncodedEnvelope(
            payload=_encode_base64(payload),
            payload_type=payload_type,
            signatures=(_EncodedSignature(keyid=keyid, sig=_encode_base64(signature)),),
        )
    )


def _parse_envelope(envelope_bytes: bytes) -> _DecodedEnvelope:
    try:
        envelope = _ENVELOPE_DECODER.decode(envelope_bytes)
        json.loads(envelope_bytes, object_pairs_hook=_reject_duplicate_keys)
    except (ValueError, RecursionError) as exc:
        msg = "invalid DSSE envelope JSON or shape"
        raise AttestationError(msg) from exc
    return envelope


def _decode_vcert_payload(payload: bytes) -> VCert:
    """Strictly parse the already-authenticated byte object, including duplicate rejection."""
    try:
        certificate = _VCERT_DECODER.decode(payload)
        json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
    except (ValueError, RecursionError) as exc:
        msg = "authenticated payload is not a valid VCert v0.2"
        raise AttestationError(msg) from exc
    return certificate


def sign_vcert(
    certificate: VCert,
    private_key: Ed25519PrivateKey,
    *,
    keyid: str,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> bytes:
    """Sign canonical exact VCert bytes into one canonical, keyid-bearing DSSE envelope."""
    private_key_object: object = private_key
    if not isinstance(private_key_object, Ed25519PrivateKey):
        msg = "private_key must be an Ed25519PrivateKey"
        raise TypeError(msg)
    _validate_required_keyid(keyid, subject="signer")
    payload = vcert_bytes(certificate)
    _enforce_payload_limit(payload, limits.max_attestation_bytes)
    signature = private_key.sign(pae(VCERT_PAYLOAD_TYPE, payload))
    return _encode_envelope(payload, signature, keyid)


def _trusted_key_items(
    trusted_keys: Mapping[str, Ed25519PublicKey],
) -> tuple[tuple[str, Ed25519PublicKey], ...]:
    items = tuple(trusted_keys.items())
    if not items:
        msg = "at least one trusted Ed25519 public key is required"
        raise ValueError(msg)
    for keyid, public_key in items:
        _validate_required_keyid(keyid, subject="trusted")
        public_key_object: object = public_key
        if not isinstance(public_key_object, Ed25519PublicKey):
            msg = "trusted key values must be Ed25519PublicKey instances"
            raise TypeError(msg)
    return items


def verify_vcert(
    envelope_bytes: bytes,
    trusted_keys: Mapping[str, Ed25519PublicKey],
    *,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> VerifiedVCert:
    """Authenticate one DSSE envelope, then parse and return its exact VCert payload bytes.

    The untrusted keyid only puts a matching trusted candidate first. Every remaining trusted key
    is still tried, so changing/removing the hint cannot change acceptance or the returned value.
    """
    max_payload_bytes = limits.max_attestation_bytes
    max_envelope_bytes = envelope_byte_limit(max_payload_bytes)
    if len(envelope_bytes) > max_envelope_bytes:
        msg = f"DSSE envelope has {len(envelope_bytes)} bytes; limit is {max_envelope_bytes}"
        raise VerificationError(msg, check="resource.attestation_bytes")

    envelope = _parse_envelope(envelope_bytes)
    signature_record = envelope.signatures[0]
    _validate_keyid_hint(signature_record.keyid)

    max_payload_base64 = _base64_length(max_payload_bytes)
    if len(envelope.payload) > max_payload_base64:
        msg = f"VCert payload base64 exceeds encoded byte limit of {max_payload_base64}"
        raise VerificationError(msg, check="resource.attestation_bytes")
    payload = _decode_base64(envelope.payload, field="payload")
    _enforce_payload_limit(payload, max_payload_bytes)

    if len(signature_record.sig) != _SIGNATURE_BASE64_BYTES:
        msg = "DSSE Ed25519 signature has an invalid base64 length"
        raise AttestationError(msg)
    signature = _decode_base64(signature_record.sig, field="signature")
    if len(signature) != _ED25519_SIGNATURE_BYTES:
        msg = "DSSE signature is not a 64-byte Ed25519 signature"
        raise AttestationError(msg)

    trusted = _trusted_key_items(trusted_keys)
    candidates = tuple(item for item in trusted if item[0] == signature_record.keyid) + tuple(
        item for item in trusted if item[0] != signature_record.keyid
    )
    authenticated = pae(envelope.payload_type, payload)
    for _, public_key in candidates:
        try:
            public_key.verify(signature, authenticated)
        except InvalidSignature:
            continue
        break
    else:
        msg = "DSSE signature is not valid under any trusted Ed25519 key"
        raise AttestationError(msg)

    if envelope.payload_type != VCERT_PAYLOAD_TYPE:
        msg = f"unsupported DSSE payload type: {envelope.payload_type!r}"
        raise AttestationError(msg)
    certificate = _decode_vcert_payload(payload)
    return VerifiedVCert(payload=payload, certificate=certificate)
