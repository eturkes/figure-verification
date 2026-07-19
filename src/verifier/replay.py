# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Pure replay of one archived successful plot occurrence from exact snapshot bytes.

The caller's explicit ``trusted_keys`` mapping is the only trust anchor. Snapshot ``keyid`` and
``public_key`` bytes are self-consistency addresses only: archive presence, a digest-matching
embedded public key, or a valid self-signed envelope never grants trust. Replay authenticates the
signed attempt association and VCert under caller-pinned keys before any recomputation.

Recomputation consumes only archived ``raw_csv``, ``raw_manifest``, and ``canonical_spec`` bytes.
Stored plotted-table, Vega-Lite, verdict, SVG, and certificate bytes are authenticated comparison
artifacts, never computation inputs. Native SVG equality is diagnostic because display remains in
the TCB; the exact verdict is gated by the five certified hashes, TCB versions, and VCert payload.
This module deliberately imports no ``verifier.service`` module.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Annotated, Literal, cast

import msgspec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from verifier import attestation, canon, checks, errors, render, schema
from verifier.limits import DEFAULT_LIMITS, VerificationLimits

ATTEMPT_PAYLOAD_TYPE = "application/vnd.figure-verification.attempt.v0.1+json"

BLOB_ROLE_VALUES = (
    "raw_csv",
    "raw_manifest",
    "canonical_spec",
    "raw_spec",
    "plotted_table",
    "verdict",
    "vega_lite",
    "svg",
    "vcert_payload",
    "vcert_envelope",
    "ed25519_public_key",
    "tool_versions",
    "model_request",
    "model_response",
    "model_reply",
    "attempt_payload",
    "attempt_envelope",
)
PLOT_ROLE_VALUES = (
    "raw_csv",
    "raw_manifest",
    "canonical_spec",
    "plotted_table",
    "verdict",
    "vega_lite",
    "svg",
    "vcert_payload",
    "tool_versions",
)

_ATTEMPT_ARTIFACT_FIELDS = (
    ("raw_csv", "raw_csv"),
    ("raw_manifest", "raw_manifest"),
    ("raw_spec", "raw_spec"),
    ("verdict", "verdict"),
    ("model_request", "model_request"),
    ("model_response", "model_response"),
    ("model_reply", "model_reply"),
)
_PLOT_BINDING_FIELDS = (
    ("raw_csv", "raw_csv"),
    ("raw_manifest", "raw_manifest"),
    ("canonical_spec", "canonical_spec"),
    ("plotted_table", "plotted_table"),
    ("verdict", "verdict"),
    ("vega_lite", "vega_lite"),
    ("svg", "svg"),
    ("vcert_payload", "vcert_payload"),
    ("vcert_envelope", "vcert_envelope"),
    ("tool_versions", "tool_versions"),
    ("ed25519_public_key", "public_key"),
)
_ATTEMPT_BYTE_FIELDS = (
    "attempt_payload",
    "attempt_envelope",
    "public_key",
)
_PLOT_BYTE_FIELDS = (
    "raw_csv",
    "raw_manifest",
    "canonical_spec",
    "plotted_table",
    "verdict",
    "vega_lite",
    "svg",
    "vcert_payload",
    "vcert_envelope",
    "tool_versions",
    "public_key",
)

_HEX_DIGITS = frozenset("0123456789abcdef")
_MAX_VERSION_BYTES = 128
_ED25519_PUBLIC_KEY_BYTES = 32
_MAX_HOUR = 23
_MAX_MINUTE_SECOND = 59


def _is_lower_hex(value: str, length: int) -> bool:
    return len(value) == length and all(character in _HEX_DIGITS for character in value)


def _require_address(value: object, *, subject: str) -> None:
    if not isinstance(value, str):
        msg = f"{subject} must be str, got {type(value).__name__}"
        raise TypeError(msg)
    if not _is_lower_hex(value, 64):
        msg = f"{subject} must contain 64 lowercase hexadecimal characters"
        raise ValueError(msg)


def _require_keyid(value: object, *, subject: str) -> None:
    if not isinstance(value, str):
        msg = f"{subject} must be str, got {type(value).__name__}"
        raise TypeError(msg)
    if not value.startswith("sha256:") or not _is_lower_hex(value[7:], 64):
        msg = f"{subject} must match sha256:<64 lowercase hex>"
        raise ValueError(msg)


def _require_bytes(value: object, *, subject: str, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, bytes):
        suffix = " or None" if nullable else ""
        msg = f"{subject} must be bytes{suffix}, got {type(value).__name__}"
        raise TypeError(msg)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayAttemptArtifacts:
    """Exact nullable observation bytes carried by one archived attempt occurrence."""

    raw_csv: bytes | None = field(default=None, repr=False)
    raw_manifest: bytes | None = field(default=None, repr=False)
    raw_spec: bytes | None = field(default=None, repr=False)
    verdict: bytes | None = field(default=None, repr=False)
    model_request: bytes | None = field(default=None, repr=False)
    model_response: bytes | None = field(default=None, repr=False)
    model_reply: bytes | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for _role, name in _ATTEMPT_ARTIFACT_FIELDS:
            _require_bytes(
                getattr(self, name),
                subject=f"replay attempt artifact {name}",
                nullable=True,
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayPlotSnapshot:
    """Every exact byte required to authenticate one archived successful plot."""

    plot_id: str
    keyid: str
    raw_csv: bytes = field(repr=False)
    raw_manifest: bytes = field(repr=False)
    canonical_spec: bytes = field(repr=False)
    plotted_table: bytes = field(repr=False)
    verdict: bytes = field(repr=False)
    vega_lite: bytes = field(repr=False)
    svg: bytes = field(repr=False)
    vcert_payload: bytes = field(repr=False)
    vcert_envelope: bytes = field(repr=False)
    tool_versions: bytes = field(repr=False)
    public_key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _require_address(self.plot_id, subject="replay plot id")
        _require_keyid(self.keyid, subject="replay plot keyid")
        for name in _PLOT_BYTE_FIELDS:
            _require_bytes(getattr(self, name), subject=f"replay plot {name}")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplaySnapshot:
    """One signed successful attempt with a required plot and no producer manifest object."""

    attempt_id: str
    keyid: str
    artifacts: ReplayAttemptArtifacts
    attempt_payload: bytes = field(repr=False)
    attempt_envelope: bytes = field(repr=False)
    public_key: bytes = field(repr=False)
    plot: ReplayPlotSnapshot = field(repr=False)

    def __post_init__(self) -> None:
        _require_address(self.attempt_id, subject="replay attempt id")
        _require_keyid(self.keyid, subject="replay attempt keyid")
        artifacts_object: object = self.artifacts
        plot_object: object = self.plot
        if not isinstance(artifacts_object, ReplayAttemptArtifacts):
            msg = (
                "replay artifacts must be ReplayAttemptArtifacts, "
                f"got {type(self.artifacts).__name__}"
            )
            raise TypeError(msg)
        if not isinstance(plot_object, ReplayPlotSnapshot):
            msg = f"replay plot must be ReplayPlotSnapshot, got {type(self.plot).__name__}"
            raise TypeError(msg)
        for name in _ATTEMPT_BYTE_FIELDS:
            _require_bytes(getattr(self, name), subject=f"replay attempt {name}")


type ReplayStatus = Literal[
    "exact",
    "drift",
    "untrusted_key",
    "integrity_failed",
    "recomputation_failed",
]
type ReplayFailureStage = Literal[
    "trust",
    "attempt_address",
    "attempt_signature",
    "attempt_manifest",
    "attempt_artifacts",
    "attempt_outcome",
    "plot_artifacts",
    "plot_address",
    "plot_signature",
    "plot_contents",
    "attempt_plot",
    "recomputation",
]
type TcbField = Literal[
    "verifier_version",
    "z3_version",
    "canon_version",
    "python",
    "msgspec",
    "unidata",
    "vl_convert_python",
    "vl_version",
    "font_family",
    "vendored_font_sha256",
]


class ArtifactHashMatches(
    msgspec.Struct,
    frozen=True,
    forbid_unknown_fields=True,
    kw_only=True,
):
    """Fresh-vs-authenticated VCert hash equality for each certified artifact."""

    dataset: bool | None = None
    manifest: bool | None = None
    spec: bool | None = None
    plotted_table: bool | None = None
    vega_lite: bool | None = None


class VersionDrift(msgspec.Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    """One bounded TCB field whose archived and current values differ."""

    field: TcbField
    archived: str
    current: str


class ReplayVerdict(msgspec.Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    """Bounded replay result; carries hashes/flags/versions but no source or rendered artifacts."""

    status: ReplayStatus
    integrity_ok: bool
    trusted_keyid: str | None
    failure_stage: ReplayFailureStage | None
    diagnostic: str
    artifact_matches: ArtifactHashMatches
    payload_match: bool | None
    version_match: bool | None
    drift: tuple[VersionDrift, ...]
    svg_match: bool | None
    exact: bool


type _BlobRole = Literal[
    "raw_csv",
    "raw_manifest",
    "canonical_spec",
    "raw_spec",
    "plotted_table",
    "verdict",
    "vega_lite",
    "svg",
    "vcert_payload",
    "vcert_envelope",
    "ed25519_public_key",
    "tool_versions",
    "model_request",
    "model_response",
    "model_reply",
    "attempt_payload",
    "attempt_envelope",
]
type _AttemptRoute = Literal["/verify-and-render", "/propose-spec"]
type _AttemptOutcome = Literal[
    "verified",
    "rejected",
    "dataset_not_found",
    "proposer_policy",
    "dataset_mismatch",
    "model_transport",
    "model_content_encoding",
    "model_response_too_large",
    "model_http_status",
    "model_prompt_tokens",
    "model_invalid_envelope",
    "model_no_choices",
    "model_empty_content",
]
type _Sha256 = Annotated[str, msgspec.Meta(pattern="^sha256:[0-9a-f]{64}$")]
type _Address = Annotated[str, msgspec.Meta(pattern="^[0-9a-f]{64}$")]
type _Nonce = Annotated[str, msgspec.Meta(pattern="^[0-9a-f]{32}$")]
type _Timestamp = Annotated[
    str,
    msgspec.Meta(pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{6}Z$"),
]


class _BlobBinding(msgspec.Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    role: _BlobRole
    digest: _Sha256


class _AttemptManifest(msgspec.Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    version: Literal["attempt-0.1"]
    nonce: _Nonce
    occurred_at: _Timestamp
    route: _AttemptRoute
    http_status: int
    outcome: _AttemptOutcome
    plot_id: _Address | None
    artifacts: tuple[_BlobBinding, ...]
    plot_artifacts: tuple[_BlobBinding, ...]
    keyid: _Sha256
    verifier_version: str


class _ArchivedCheck(msgspec.Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    check: str
    method: checks.CheckMethod
    status: Literal["pass", "fail"]
    severity: Literal["blocking"]
    message: str


class _ArchivedVerdict(
    msgspec.Struct,
    frozen=True,
    forbid_unknown_fields=True,
    kw_only=True,
    omit_defaults=True,
):
    verified: bool
    layer: Literal["decode", "verify"]
    results: tuple[_ArchivedCheck, ...]
    attempt_id: _Address | None = None


_ATTEMPT_STATUS: dict[_AttemptOutcome, int] = {
    "verified": 200,
    "rejected": 200,
    "dataset_not_found": 404,
    "proposer_policy": 422,
    "dataset_mismatch": 502,
    "model_transport": 503,
    "model_content_encoding": 502,
    "model_response_too_large": 502,
    "model_http_status": 502,
    "model_prompt_tokens": 422,
    "model_invalid_envelope": 502,
    "model_no_choices": 502,
    "model_empty_content": 502,
}
_EXPECTED_MODEL_ROLES: dict[_AttemptRoute, frozenset[_BlobRole]] = {
    "/verify-and-render": frozenset(),
    "/propose-spec": frozenset({"model_request", "model_response", "model_reply"}),
}
_TCB_FIELDS: tuple[TcbField, ...] = (
    "verifier_version",
    "z3_version",
    "canon_version",
    "python",
    "msgspec",
    "unidata",
    "vl_convert_python",
    "vl_version",
    "font_family",
    "vendored_font_sha256",
)
_ENCODER = msgspec.json.Encoder(order="deterministic")
_ATTEMPT_DECODER = msgspec.json.Decoder(_AttemptManifest, strict=True)
_VERDICT_DECODER = msgspec.json.Decoder(_ArchivedVerdict, strict=True)
_VERSIONS_DECODER = msgspec.json.Decoder(render.Tcb, strict=True)


class _ReplayFailureError(Exception):
    def __init__(
        self,
        status: Literal["untrusted_key", "integrity_failed"],
        stage: ReplayFailureStage,
        diagnostic: str,
        *,
        trusted_keyid: str | None = None,
    ) -> None:
        super().__init__(diagnostic)
        self.status = status
        self.stage = stage
        self.diagnostic = diagnostic
        self.trusted_keyid = trusted_keyid


def _integrity_error(
    stage: ReplayFailureStage,
    diagnostic: str,
    *,
    trusted_keyid: str | None = None,
) -> _ReplayFailureError:
    return _ReplayFailureError(
        "integrity_failed",
        stage,
        diagnostic,
        trusted_keyid=trusted_keyid,
    )


def _untrusted_key_error(diagnostic: str) -> _ReplayFailureError:
    return _ReplayFailureError("untrusted_key", "trust", diagnostic)


@dataclass(frozen=True, slots=True)
class _AuthenticatedSnapshot:
    snapshot: ReplaySnapshot = field(repr=False)
    manifest: _AttemptManifest = field(repr=False)
    spec: schema.VPlotSpec = field(repr=False)
    certificate: render.VCert
    archived_svg: str = field(repr=False)
    trusted_keyid: str


def _require(
    condition: bool,  # noqa: FBT001 - shared invariant guard reads naturally at call sites
    stage: ReplayFailureStage,
    diagnostic: str,
    *,
    trusted_keyid: str | None = None,
) -> None:
    if not condition:
        raise _integrity_error(stage, diagnostic, trusted_keyid=trusted_keyid)


def _raw_digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _artifact_bindings(artifacts: ReplayAttemptArtifacts) -> tuple[_BlobBinding, ...]:
    return tuple(
        _BlobBinding(role=cast("_BlobRole", role), digest=_raw_digest(payload))
        for role, name in _ATTEMPT_ARTIFACT_FIELDS
        if (payload := cast("bytes | None", getattr(artifacts, name))) is not None
    )


def _plot_bindings(plot: ReplayPlotSnapshot) -> tuple[_BlobBinding, ...]:
    return tuple(
        _BlobBinding(
            role=cast("_BlobRole", role),
            digest=_raw_digest(cast("bytes", getattr(plot, name))),
        )
        for role, name in _PLOT_BINDING_FIELDS
    )


def _timestamp_is_real(value: str) -> bool:
    year = int(value[0:4])
    month = int(value[5:7])
    day = int(value[8:10])
    hour = int(value[11:13])
    minute = int(value[14:16])
    second = int(value[17:19])
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    month_days = {
        1: 31,
        2: 28 + int(leap),
        3: 31,
        4: 30,
        5: 31,
        6: 30,
        7: 31,
        8: 31,
        9: 30,
        10: 31,
        11: 30,
        12: 31,
    }
    return (
        year >= 1
        and 1 <= day <= month_days.get(month, 0)
        and 0 <= hour <= _MAX_HOUR
        and 0 <= minute <= _MAX_MINUTE_SECOND
        and 0 <= second <= _MAX_MINUTE_SECOND
    )


def _validate_bindings(
    bindings: tuple[_BlobBinding, ...],
    *,
    subject: str,
    trusted_keyid: str,
) -> None:
    roles = tuple(binding.role for binding in bindings)
    _require(
        len(set(roles)) == len(roles),
        "attempt_manifest",
        f"authenticated attempt manifest repeats a {subject} role",
        trusted_keyid=trusted_keyid,
    )


def _validate_manifest(manifest: _AttemptManifest, *, trusted_keyid: str) -> None:
    _require(
        _timestamp_is_real(manifest.occurred_at),
        "attempt_manifest",
        "authenticated attempt occurrence time is not a real UTC instant",
        trusted_keyid=trusted_keyid,
    )
    _require(
        manifest.http_status == _ATTEMPT_STATUS[manifest.outcome],
        "attempt_manifest",
        "authenticated attempt HTTP status disagrees with its closed outcome",
        trusted_keyid=trusted_keyid,
    )
    try:
        version_bytes = manifest.verifier_version.encode("utf-8")
    except UnicodeEncodeError as exc:
        stage: ReplayFailureStage = "attempt_manifest"
        diagnostic = "authenticated attempt verifier version is not valid UTF-8"
        raise _integrity_error(stage, diagnostic, trusted_keyid=trusted_keyid) from exc
    _require(
        bool(manifest.verifier_version) and len(version_bytes) <= _MAX_VERSION_BYTES,
        "attempt_manifest",
        "authenticated attempt verifier version is empty or over its byte limit",
        trusted_keyid=trusted_keyid,
    )
    _validate_bindings(manifest.artifacts, subject="artifact", trusted_keyid=trusted_keyid)
    _validate_bindings(
        manifest.plot_artifacts,
        subject="plot artifact",
        trusted_keyid=trusted_keyid,
    )


def _decode_attempt_payload(payload: bytes, *, trusted_keyid: str) -> _AttemptManifest:
    try:
        manifest = _ATTEMPT_DECODER.decode(payload)
    except (ValueError, RecursionError) as exc:
        stage: ReplayFailureStage = "attempt_manifest"
        diagnostic = "authenticated attempt payload is not a valid v0.1 manifest"
        raise _integrity_error(stage, diagnostic, trusted_keyid=trusted_keyid) from exc
    _require(
        _ENCODER.encode(manifest) == payload,
        "attempt_manifest",
        "authenticated attempt payload is not canonical deterministic JSON",
        trusted_keyid=trusted_keyid,
    )
    _validate_manifest(manifest, trusted_keyid=trusted_keyid)
    return manifest


def _decode_verdict(payload: bytes, *, trusted_keyid: str) -> _ArchivedVerdict:
    try:
        verdict = _VERDICT_DECODER.decode(payload)
    except (ValueError, RecursionError) as exc:
        stage: ReplayFailureStage = "plot_contents"
        diagnostic = "archived verdict is not valid structured JSON"
        raise _integrity_error(stage, diagnostic, trusted_keyid=trusted_keyid) from exc
    _require(
        _ENCODER.encode(verdict) == payload,
        "plot_contents",
        "archived verdict is not canonical deterministic JSON",
        trusted_keyid=trusted_keyid,
    )
    return verdict


def _decode_versions(payload: bytes, *, trusted_keyid: str) -> render.Tcb:
    try:
        versions = _VERSIONS_DECODER.decode(payload)
    except (ValueError, RecursionError) as exc:
        stage: ReplayFailureStage = "plot_contents"
        diagnostic = "archived tool versions are not valid structured JSON"
        raise _integrity_error(stage, diagnostic, trusted_keyid=trusted_keyid) from exc
    _require(
        _ENCODER.encode(versions) == payload,
        "plot_contents",
        "archived tool versions are not canonical deterministic JSON",
        trusted_keyid=trusted_keyid,
    )
    return versions


def _decode_spec(payload: bytes, *, trusted_keyid: str) -> schema.VPlotSpec:
    try:
        spec = schema.decode_spec(payload)
    except (ValueError, RecursionError) as exc:
        stage: ReplayFailureStage = "plot_contents"
        diagnostic = "archived canonical spec is not a valid VPlot specification"
        raise _integrity_error(stage, diagnostic, trusted_keyid=trusted_keyid) from exc
    _require(
        canon.spec_bytes(spec) == payload,
        "plot_contents",
        "archived canonical spec bytes are not canonical",
        trusted_keyid=trusted_keyid,
    )
    return spec


def _trusted_key(
    keyid: str,
    trusted_keys: Mapping[str, Ed25519PublicKey],
) -> Ed25519PublicKey:
    if keyid not in trusted_keys:
        diagnostic = "snapshot signer keyid is not pinned by the caller"
        raise _untrusted_key_error(diagnostic)
    return trusted_keys[keyid]


def _authenticate_attempt(
    snapshot: ReplaySnapshot,
    trusted_keys: Mapping[str, Ed25519PublicKey],
    limits: VerificationLimits,
) -> tuple[_AttemptManifest, Ed25519PublicKey]:
    _require(
        len(snapshot.attempt_payload) <= limits.max_attestation_bytes,
        "attempt_address",
        "attempt payload exceeds the attestation byte limit",
    )
    envelope_limit = attestation.envelope_byte_limit(
        limits.max_attestation_bytes,
        payload_type=ATTEMPT_PAYLOAD_TYPE,
    )
    _require(
        len(snapshot.attempt_envelope) <= envelope_limit,
        "attempt_address",
        "attempt envelope exceeds its canonical byte limit",
    )
    _require(
        hashlib.sha256(snapshot.attempt_envelope).hexdigest() == snapshot.attempt_id,
        "attempt_address",
        "attempt id does not address the exact DSSE envelope bytes",
    )
    _require(
        len(snapshot.public_key) == _ED25519_PUBLIC_KEY_BYTES
        and _raw_digest(snapshot.public_key) == snapshot.keyid,
        "attempt_address",
        "attempt keyid does not address a raw Ed25519 public key",
    )
    trusted_key = _trusted_key(snapshot.keyid, trusted_keys)
    try:
        verified = attestation.verify_dsse(
            snapshot.attempt_envelope,
            {snapshot.keyid: trusted_key},
            payload_type=ATTEMPT_PAYLOAD_TYPE,
            max_payload_bytes=limits.max_attestation_bytes,
        )
    except (TypeError, ValueError, attestation.AttestationError, errors.VerificationError) as exc:
        stage: ReplayFailureStage = "attempt_signature"
        diagnostic = "attempt DSSE envelope failed caller-pinned signature verification"
        raise _integrity_error(stage, diagnostic) from exc
    trusted_keyid = snapshot.keyid
    _require(
        verified.payload == snapshot.attempt_payload,
        "attempt_signature",
        "attempt payload differs from its authenticated envelope payload",
        trusted_keyid=trusted_keyid,
    )
    manifest = _decode_attempt_payload(verified.payload, trusted_keyid=trusted_keyid)
    _require(
        manifest.keyid == snapshot.keyid,
        "attempt_manifest",
        "authenticated attempt manifest keyid disagrees with its signer",
        trusted_keyid=trusted_keyid,
    )
    return manifest, trusted_key


def _validate_attempt_graph(
    snapshot: ReplaySnapshot,
    manifest: _AttemptManifest,
    *,
    trusted_keyid: str,
) -> _ArchivedVerdict:
    _require(
        manifest.artifacts == _artifact_bindings(snapshot.artifacts),
        "attempt_artifacts",
        "authenticated attempt artifact bindings disagree with observed bytes",
        trusted_keyid=trusted_keyid,
    )
    _require(
        manifest.plot_artifacts == _plot_bindings(snapshot.plot),
        "plot_artifacts",
        "authenticated plot artifact bindings disagree with complete plot bytes",
        trusted_keyid=trusted_keyid,
    )
    _require(
        manifest.plot_id == snapshot.plot.plot_id,
        "attempt_plot",
        "authenticated attempt plot id disagrees with its nested plot",
        trusted_keyid=trusted_keyid,
    )
    _require(
        manifest.outcome == "verified",
        "attempt_outcome",
        "replay requires an authenticated verified attempt outcome",
        trusted_keyid=trusted_keyid,
    )
    artifacts = snapshot.artifacts
    _require(
        artifacts.verdict is not None and artifacts.raw_spec is not None,
        "attempt_outcome",
        "verified attempt is missing its verdict or raw spec observation",
        trusted_keyid=trusted_keyid,
    )
    present_model_roles = frozenset(
        cast("_BlobRole", role)
        for role, name in _ATTEMPT_ARTIFACT_FIELDS
        if role in {"model_request", "model_response", "model_reply"}
        and getattr(artifacts, name) is not None
    )
    _require(
        present_model_roles == _EXPECTED_MODEL_ROLES[manifest.route],
        "attempt_outcome",
        "attempt model trace presence disagrees with its authenticated route",
        trusted_keyid=trusted_keyid,
    )
    _require(
        manifest.route != "/propose-spec" or artifacts.model_reply == artifacts.raw_spec,
        "attempt_outcome",
        "attempt model reply differs from the exact raw spec handed to decode",
        trusted_keyid=trusted_keyid,
    )
    _require(
        snapshot.plot.keyid == snapshot.keyid and snapshot.plot.public_key == snapshot.public_key,
        "attempt_plot",
        "attempt signer differs from the successful plot signer",
        trusted_keyid=trusted_keyid,
    )
    _require(
        artifacts.raw_csv == snapshot.plot.raw_csv
        and artifacts.raw_manifest == snapshot.plot.raw_manifest
        and artifacts.verdict == snapshot.plot.verdict,
        "attempt_plot",
        "attempt observed verifier bytes disagree with the successful plot",
        trusted_keyid=trusted_keyid,
    )
    verdict = _decode_verdict(cast("bytes", artifacts.verdict), trusted_keyid=trusted_keyid)
    _require(
        verdict.verified,
        "attempt_outcome",
        "authenticated attempt verdict disagrees with its verified outcome",
        trusted_keyid=trusted_keyid,
    )
    return verdict


def _authenticate_plot(
    plot: ReplayPlotSnapshot,
    verdict: _ArchivedVerdict,
    trusted_keys: Mapping[str, Ed25519PublicKey],
    limits: VerificationLimits,
    *,
    trusted_keyid: str,
) -> tuple[schema.VPlotSpec, render.VCert, render.Tcb, str]:
    _require(
        hashlib.sha256(plot.vcert_envelope).hexdigest() == plot.plot_id,
        "plot_address",
        "plot id does not address the exact canonical VCert envelope bytes",
        trusted_keyid=trusted_keyid,
    )
    _require(
        len(plot.public_key) == _ED25519_PUBLIC_KEY_BYTES
        and _raw_digest(plot.public_key) == plot.keyid,
        "plot_address",
        "plot keyid does not address a raw Ed25519 public key",
        trusted_keyid=trusted_keyid,
    )
    _require(
        len(plot.vcert_payload) <= limits.max_attestation_bytes,
        "plot_address",
        "VCert payload exceeds the attestation byte limit",
        trusted_keyid=trusted_keyid,
    )
    envelope_limit = attestation.envelope_byte_limit(limits.max_attestation_bytes)
    _require(
        len(plot.vcert_envelope) <= envelope_limit,
        "plot_address",
        "VCert envelope exceeds its canonical byte limit",
        trusted_keyid=trusted_keyid,
    )
    plot_key = _trusted_key(plot.keyid, trusted_keys)
    try:
        verified = attestation.verify_vcert(
            plot.vcert_envelope,
            {plot.keyid: plot_key},
            limits=limits,
            require_canonical_envelope=True,
            expected_keyid_hint=plot.keyid,
        )
    except (TypeError, ValueError, attestation.AttestationError, errors.VerificationError) as exc:
        stage: ReplayFailureStage = "plot_signature"
        diagnostic = "VCert envelope failed caller-pinned signature verification"
        raise _integrity_error(stage, diagnostic, trusted_keyid=trusted_keyid) from exc
    certificate = verified.certificate
    _require(
        render.vcert_bytes(certificate) == verified.payload,
        "plot_signature",
        "authenticated VCert payload is not canonical deterministic JSON",
        trusted_keyid=trusted_keyid,
    )
    _require(
        verified.payload == plot.vcert_payload,
        "plot_signature",
        "stored VCert payload differs from its authenticated envelope payload",
        trusted_keyid=trusted_keyid,
    )

    spec = _decode_spec(plot.canonical_spec, trusted_keyid=trusted_keyid)
    versions = _decode_versions(plot.tool_versions, trusted_keyid=trusted_keyid)
    try:
        archived_svg = plot.svg.decode("utf-8")
    except UnicodeDecodeError as exc:
        content_stage: ReplayFailureStage = "plot_contents"
        diagnostic = "archived SVG is not valid UTF-8"
        raise _integrity_error(
            content_stage,
            diagnostic,
            trusted_keyid=trusted_keyid,
        ) from exc

    archived_hashes = (
        canon.hash_dataset(plot.raw_csv) == certificate.dataset_hash,
        canon.hash_manifest(plot.raw_manifest) == certificate.manifest_hash,
        canon.hash_spec(spec) == certificate.spec_hash,
        canon.hash_table_bytes(plot.plotted_table) == certificate.plotted_table_hash,
        render.hash_vega_lite(plot.vega_lite) == certificate.vega_lite_hash,
    )
    _require(
        all(archived_hashes),
        "plot_contents",
        "archived plot artifact bytes disagree with one or more certified hashes",
        trusted_keyid=trusted_keyid,
    )
    _require(
        spec.dataset.hash == certificate.dataset_hash,
        "plot_contents",
        "archived canonical spec dataset binding disagrees with the certified dataset",
        trusted_keyid=trusted_keyid,
    )
    _require(
        verdict.layer == "verify" and all(result.status == "pass" for result in verdict.results),
        "plot_contents",
        "archived verdict is not a complete passing verification outcome",
        trusted_keyid=trusted_keyid,
    )
    certified_checks = tuple(
        render.CertifiedCheck(id=result.check, method=result.method, status="pass")
        for result in verdict.results
    )
    _require(
        certificate.checks == certified_checks,
        "plot_contents",
        "archived method-aware verdict disagrees with certified checks",
        trusted_keyid=trusted_keyid,
    )
    _require(
        versions == certificate.tcb,
        "plot_contents",
        "archived tool versions disagree with the VCert TCB",
        trusted_keyid=trusted_keyid,
    )
    return spec, certificate, versions, archived_svg


def _authenticate_snapshot(
    snapshot: ReplaySnapshot,
    trusted_keys: Mapping[str, Ed25519PublicKey],
    limits: VerificationLimits,
) -> _AuthenticatedSnapshot:
    manifest, _attempt_key = _authenticate_attempt(snapshot, trusted_keys, limits)
    trusted_keyid = snapshot.keyid
    verdict = _validate_attempt_graph(snapshot, manifest, trusted_keyid=trusted_keyid)
    spec, certificate, versions, archived_svg = _authenticate_plot(
        snapshot.plot,
        verdict,
        trusted_keys,
        limits,
        trusted_keyid=trusted_keyid,
    )
    _require(
        manifest.verifier_version == versions.verifier_version,
        "attempt_plot",
        "attempt verifier version disagrees with the successful plot TCB",
        trusted_keyid=trusted_keyid,
    )
    return _AuthenticatedSnapshot(
        snapshot=snapshot,
        manifest=manifest,
        spec=spec,
        certificate=certificate,
        archived_svg=archived_svg,
        trusted_keyid=trusted_keyid,
    )


def _failure_verdict(failure: _ReplayFailureError) -> ReplayVerdict:
    return ReplayVerdict(
        status=failure.status,
        integrity_ok=False,
        trusted_keyid=failure.trusted_keyid,
        failure_stage=failure.stage,
        diagnostic=failure.diagnostic,
        artifact_matches=ArtifactHashMatches(),
        payload_match=None,
        version_match=None,
        drift=(),
        svg_match=None,
        exact=False,
    )


def archive_integrity_verdict() -> ReplayVerdict:
    """Bound an archive integrity fault that occurs before a replay snapshot can be built."""
    return _failure_verdict(
        _integrity_error(
            "attempt_artifacts",
            "archived replay artifacts failed integrity validation",
        )
    )


def _recomputation_failure(diagnostic: str, *, trusted_keyid: str) -> ReplayVerdict:
    return ReplayVerdict(
        status="recomputation_failed",
        integrity_ok=True,
        trusted_keyid=trusted_keyid,
        failure_stage="recomputation",
        diagnostic=diagnostic,
        artifact_matches=ArtifactHashMatches(),
        payload_match=None,
        version_match=None,
        drift=(),
        svg_match=None,
        exact=False,
    )


def _version_drift(archived: render.Tcb, current: render.Tcb) -> tuple[VersionDrift, ...]:
    return tuple(
        VersionDrift(
            field=name,
            archived=cast("str", getattr(archived, name)),
            current=cast("str", getattr(current, name)),
        )
        for name in _TCB_FIELDS
        if getattr(archived, name) != getattr(current, name)
    )


def _recompute_authenticated(
    authenticated: _AuthenticatedSnapshot,
    limits: VerificationLimits,
) -> ReplayVerdict:
    plot = authenticated.snapshot.plot
    try:
        run = checks.verify_snapshot(
            authenticated.spec,
            plot.raw_manifest,
            plot.raw_csv,
            limits=limits,
        )
    except (ValueError, errors.VerificationError, RecursionError) as exc:
        return _recomputation_failure(
            f"archived inputs could not be recomputed: {type(exc).__name__}",
            trusted_keyid=authenticated.trusted_keyid,
        )
    if not run.report.passed:
        return _recomputation_failure(
            "archived inputs no longer pass current core verification",
            trusted_keyid=authenticated.trusted_keyid,
        )
    evidence = cast("checks.RecomputedEvidence", run.evidence)

    try:
        preparation = render.prepare_render(authenticated.spec, evidence, limits=limits)
    except (ValueError, errors.VerificationError) as exc:
        return _recomputation_failure(
            f"archived inputs could not be prepared: {type(exc).__name__}",
            trusted_keyid=authenticated.trusted_keyid,
        )
    if preparation.prepared is None:
        return _recomputation_failure(
            "archived inputs no longer pass current formal verification",
            trusted_keyid=authenticated.trusted_keyid,
        )
    prepared = preparation.prepared
    try:
        result = render.render_prepared(prepared, include_html=False, limits=limits)
    except (ValueError, errors.VerificationError) as exc:
        return _recomputation_failure(
            f"archived inputs could not be rendered: {type(exc).__name__}",
            trusted_keyid=authenticated.trusted_keyid,
        )

    fresh = result.certificate
    archived = authenticated.certificate
    matches = ArtifactHashMatches(
        dataset=fresh.dataset_hash == archived.dataset_hash,
        manifest=fresh.manifest_hash == archived.manifest_hash,
        spec=fresh.spec_hash == archived.spec_hash,
        plotted_table=fresh.plotted_table_hash == archived.plotted_table_hash,
        vega_lite=fresh.vega_lite_hash == archived.vega_lite_hash,
    )
    artifact_values = (
        matches.dataset,
        matches.manifest,
        matches.spec,
        matches.plotted_table,
        matches.vega_lite,
    )
    all_artifacts_match = all(value is True for value in artifact_values)
    drift = _version_drift(archived.tcb, fresh.tcb)
    version_match = not drift
    payload_match = render.vcert_bytes(fresh) == authenticated.snapshot.plot.vcert_payload
    svg_match = result.svg == authenticated.archived_svg
    exact = all_artifacts_match and version_match and payload_match
    status: ReplayStatus
    diagnostic: str
    failure_stage: ReplayFailureStage | None
    if exact:
        status = "exact"
        diagnostic = "authenticated snapshot recomputed exactly"
        failure_stage = None
    elif all_artifacts_match and not version_match:
        status = "drift"
        diagnostic = "authenticated artifacts match but the current TCB versions drifted"
        failure_stage = None
    else:
        status = "recomputation_failed"
        diagnostic = "current recomputation disagrees with the authenticated certificate"
        failure_stage = "recomputation"
    return ReplayVerdict(
        status=status,
        integrity_ok=True,
        trusted_keyid=authenticated.trusted_keyid,
        failure_stage=failure_stage,
        diagnostic=diagnostic,
        artifact_matches=matches,
        payload_match=payload_match,
        version_match=version_match,
        drift=drift,
        svg_match=svg_match,
        exact=exact,
    )


def replay_snapshot(
    snapshot: ReplaySnapshot,
    trusted_keys: Mapping[str, Ed25519PublicKey],
    *,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> ReplayVerdict:
    """Authenticate and replay one required-plot snapshot under explicit caller trust pins."""
    snapshot_object: object = snapshot
    if not isinstance(snapshot_object, ReplaySnapshot):
        msg = f"snapshot must be ReplaySnapshot, got {type(snapshot).__name__}"
        raise TypeError(msg)
    try:
        authenticated = _authenticate_snapshot(snapshot, trusted_keys, limits)
    except _ReplayFailureError as failure:
        return _failure_verdict(failure)
    return _recompute_authenticated(authenticated, limits)
