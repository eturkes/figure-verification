# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Operator-only signed-attempt audit — ``python -m verifier.service audit ATTEMPT_ID``.

The command reads the owner-private archive; it has no HTTP surface. ``Archive.read_attempt``
first revalidates every typed blob, digest, address, attempt signature, and optional plot graph.
The audit then authenticates the attempt and any plot envelope under the current signing key or
an explicitly pinned historical key: an archived public key alone grants no trust.

Output is stable ASCII JSON. It defaults to occurrence metadata, byte counts, and SHA-256 digests.
``--reveal-sensitive`` adds the exact attempt observations (raw CSV/manifest/spec, verdict, and
model request/response/reply) as JSON-escaped UTF-8 where valid, otherwise padded base64. Archived
terminal controls, Unicode bidi/format characters, and invalid UTF-8 bytes are therefore never
written directly.
"""

import argparse
import base64
import hashlib
import json
import sys
from collections.abc import Sequence
from typing import cast

from verifier import attestation
from verifier.errors import VerificationError
from verifier.limits import VerificationLimits
from verifier.service.archive import (
    ATTEMPT_PAYLOAD_TYPE,
    ArchiveError,
    AttemptBundle,
    BlobBinding,
    BlobKind,
    open_archive,
)
from verifier.service.identity import IdentityError, SigningIdentity, load_identity
from verifier.service.settings import Settings

__all__ = ["AuditError", "audit_attempt", "main"]

_AUDIT_VERSION = "attempt-audit-0.1"
_CLI_FAILURE = "attempt audit failed: archive or configured-key verification failed\n"
_ATTEMPT_ID_LENGTH = 64

_ATTEMPT_FIELDS: tuple[tuple[BlobKind, str], ...] = (
    (BlobKind.RAW_CSV, "raw_csv"),
    (BlobKind.RAW_MANIFEST, "raw_manifest"),
    (BlobKind.RAW_SPEC, "raw_spec"),
    (BlobKind.VERDICT, "verdict"),
    (BlobKind.MODEL_REQUEST, "model_request"),
    (BlobKind.MODEL_RESPONSE, "model_response"),
    (BlobKind.MODEL_REPLY, "model_reply"),
)
_PLOT_FIELDS: tuple[tuple[BlobKind, str], ...] = (
    (BlobKind.RAW_CSV, "raw_csv"),
    (BlobKind.RAW_MANIFEST, "raw_manifest"),
    (BlobKind.CANONICAL_SPEC, "canonical_spec"),
    (BlobKind.PLOTTED_TABLE, "plotted_table"),
    (BlobKind.VERDICT, "verdict"),
    (BlobKind.VEGA_LITE, "vega_lite"),
    (BlobKind.SVG, "svg"),
    (BlobKind.VCERT_PAYLOAD, "vcert_payload"),
    (BlobKind.VCERT_ENVELOPE, "vcert_envelope"),
    (BlobKind.TOOL_VERSIONS, "tool_versions"),
    (BlobKind.ED25519_PUBLIC_KEY, "public_key"),
)


class AuditError(RuntimeError):
    """Archive integrity or independently configured-key authentication failed."""


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _summary(payload: bytes) -> dict[str, object]:
    return {"digest": _digest(payload), "bytes": len(payload)}


def _safe_content(payload: bytes) -> dict[str, object]:
    try:
        value = payload.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "encoding": "base64",
            "value": base64.b64encode(payload).decode("ascii"),
        }
    return {"encoding": "utf-8", "value": value}


def _payload_map(
    value: object,
    fields: tuple[tuple[BlobKind, str], ...],
) -> dict[BlobKind, bytes]:
    payloads: dict[BlobKind, bytes] = {}
    for role, field_name in fields:
        payload = cast("bytes | None", getattr(value, field_name))
        if payload is not None:
            payloads[role] = payload
    return payloads


def _artifact_summaries(
    bindings: tuple[BlobBinding, ...],
    payloads: dict[BlobKind, bytes],
    *,
    reveal_sensitive: bool,
) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for binding in bindings:
        payload = payloads[binding.role]
        item: dict[str, object] = {
            "role": binding.role.value,
            "digest": binding.digest,
            "bytes": len(payload),
        }
        if reveal_sensitive:
            item["content"] = _safe_content(payload)
        summaries.append(item)
    return summaries


def _plot_document(bundle: AttemptBundle) -> dict[str, object] | None:
    plot = bundle.plot
    if plot is None:
        return None
    payloads = _payload_map(plot, _PLOT_FIELDS)
    return {
        "id": plot.plot_id,
        "keyid": plot.keyid,
        "artifacts": _artifact_summaries(
            bundle.manifest.plot_artifacts,
            payloads,
            reveal_sensitive=False,
        ),
    }


def _document(bundle: AttemptBundle, *, reveal_sensitive: bool) -> dict[str, object]:
    manifest = bundle.manifest
    attempt_payloads = _payload_map(bundle.artifacts, _ATTEMPT_FIELDS)
    return {
        "audit_version": _AUDIT_VERSION,
        "disclosure": "sensitive-attempt-bytes" if reveal_sensitive else "redacted",
        "authentication": {
            "key_policy": "current-or-explicitly-pinned",
            "attempt_dsse": "valid",
            "plot_vcert_dsse": "valid" if bundle.plot is not None else None,
        },
        "attempt": {
            "id": bundle.attempt_id,
            "version": manifest.version,
            "nonce": manifest.nonce,
            "occurred_at": manifest.occurred_at,
            "route": manifest.route.value,
            "http_status": manifest.http_status,
            "outcome": manifest.outcome.value,
            "plot_id": manifest.plot_id,
            "keyid": manifest.keyid,
            "verifier_version": manifest.verifier_version,
            "attestation": {
                "payload_type": ATTEMPT_PAYLOAD_TYPE,
                "payload": _summary(bundle.attempt_payload),
                "envelope": _summary(bundle.attempt_envelope),
            },
            "artifacts": _artifact_summaries(
                manifest.artifacts,
                attempt_payloads,
                reveal_sensitive=reveal_sensitive,
            ),
        },
        "plot": _plot_document(bundle),
    }


def _authenticate_configured_key(
    bundle: AttemptBundle,
    identity: SigningIdentity,
    limits: VerificationLimits,
) -> None:
    public_key = identity.trusted_keys.get(bundle.keyid)
    if public_key is None:
        message = "attempt audit failed configured-key authentication"
        raise AuditError(message)
    trusted_key = {bundle.keyid: public_key}
    attestation.verify_dsse(
        bundle.attempt_envelope,
        trusted_key,
        payload_type=ATTEMPT_PAYLOAD_TYPE,
        max_payload_bytes=limits.max_attestation_bytes,
    )
    plot = bundle.plot
    if plot is not None:
        attestation.verify_vcert(plot.vcert_envelope, trusted_key, limits=limits)


def audit_attempt(
    settings: Settings,
    attempt_id: str,
    *,
    reveal_sensitive: bool = False,
) -> bytes:
    """Authenticate one archived occurrence and return terminal-safe deterministic JSON."""
    try:
        bundle = open_archive(settings).read_attempt(
            attempt_id,
            max_bytes=settings.max_archive_bytes,
            limits=settings.limits,
        )
    except (ArchiveError, ValueError) as exc:
        message = "attempt audit failed archive verification"
        raise AuditError(message) from exc

    try:
        identity = load_identity(settings)
        _authenticate_configured_key(bundle, identity, settings.limits)
    except AuditError:
        raise
    except (IdentityError, attestation.AttestationError, VerificationError, ValueError) as exc:
        message = "attempt audit failed configured-key authentication"
        raise AuditError(message) from exc

    encoded = json.dumps(
        _document(bundle, reveal_sensitive=reveal_sensitive),
        ensure_ascii=True,
        allow_nan=False,
        indent=2,
    )
    return (encoded + "\n").encode("ascii")


def _attempt_id(value: str) -> str:
    if len(value) != _ATTEMPT_ID_LENGTH or any(
        character not in "0123456789abcdef" for character in value
    ):
        message = "ATTEMPT_ID must contain exactly 64 lowercase hexadecimal characters"
        raise argparse.ArgumentTypeError(message)
    return value


def _parse_args(argv: Sequence[str] | None) -> tuple[str, bool]:
    parser = argparse.ArgumentParser(
        prog="python -m verifier.service audit",
        description="Authenticate and inspect one operator-local signed attempt.",
    )
    parser.add_argument("attempt_id", type=_attempt_id, metavar="ATTEMPT_ID")
    parser.add_argument(
        "--reveal-sensitive",
        action="store_true",
        help=(
            "include raw attempt observations as ASCII JSON-escaped UTF-8 or base64 "
            "(default: hashes and metadata only)"
        ),
    )
    parsed = parser.parse_args(argv)
    return cast("str", parsed.attempt_id), cast("bool", parsed.reveal_sensitive)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the operator audit command; expected failures emit one content-free diagnostic."""
    attempt_id, reveal_sensitive = _parse_args(argv)
    try:
        settings = Settings.from_env()
        output = audit_attempt(
            settings,
            attempt_id,
            reveal_sensitive=reveal_sensitive,
        )
    except (AuditError, ValueError):
        sys.stderr.write(_CLI_FAILURE)
        return 1
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
