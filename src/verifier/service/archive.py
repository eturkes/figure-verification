# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Transactional, content-addressed plot + signed-attempt provenance storage.

One ``BEGIN IMMEDIATE`` transaction publishes every blob, key, plot, signed attempt, and typed
reference in a batch. Blob payload bytes are SHA-256-addressed within a closed kind and deduplicated
by ``(digest, kind)``; identical bytes may legitimately carry multiple observed roles and each
typed payload counts toward quota once. A trigger maintains the tracked logical-payload total. The
configured quota gates new typed bytes while the writer lock is held, before inserts, and never
evicts history. It intentionally excludes SQLite pages, row/index metadata, rollback journals, and
filesystem overhead. Startup and operator statistics reconcile the counter against all blob
metadata; per-bundle admission remains O(schema-size + bundle-size), not O(archive-history).

Every operation owns a fresh connection. Each connection forces + verifies rollback-journal
``DELETE` mode, ``EXTRA`` synchronous writes, foreign keys, defensive mode, trusted-schema off, and
a finite busy timeout. The database lives as a 0600 regular file under the service's 0700
owner-private state directory. Startup transactionally creates or exact-matches one versioned
STRICT schema; unknown/unversioned non-empty schemas fail closed.

Reads first validate the requested role/kind and stored digest/kind/size metadata, then enforce the
caller's byte limit before opening the BLOB. ``sqlite3.Blob`` is consumed in fixed chunks while its
SHA-256 digest is recomputed; neither a metadata lie nor corruption can become trusted payload.
Application values use SQL parameters exclusively; the only literal SQL is fixed schema/PRAGMA
text owned by this module. Schema v2 adds an immutable domain-separated spec-address index; the
atomic v1 migration reads only each plot's canonical-spec blob under the configured spec ceiling.
Schema v3 adds a partial ``(plot_id, attempt_id)`` index for bounded lowest-attempt selection,
without reading raw CSV, prompt, or model bytes.

Narrow public reads avoid full plot materialization: certificate reads resolve only plot envelope
+ key rows/blobs and recheck canonical DSSE form, address, signature, exact VCert type, and payload;
spec reads resolve one indexed canonical-spec blob then decode/re-encode/hash it; key reads require
one exact raw 32-byte Ed25519 blob under its keyid. Archived keys prove self-consistency only.

The high-level successful-plot API materializes one immutable ``PlotBundle`` from the exact
formal-passed evidence/render chain, publishes all eleven typed payloads atomically, and reads them
only after aggregate-size admission. Publish + read recheck canonical spec/verdict/version forms,
the DSSE signature, plot/key content addresses, and every VCert hash/check edge. Verification under
the bundle's archived public key establishes internal cryptographic consistency only; it never
grants that key operator trust. Replay applies independently configured trust policy in a later
unit. Plot bundles contain no occurrence time, route, request, prompt, or model trace.

``AttemptManifest`` adds that occurrence layer under a distinct DSSE application type: canonical
UTC time, 128-bit CSPRNG nonce, route, status/outcome classifier, signer/verifier identifiers, every
available observed-byte digest, and all eleven optional plot-byte digests. Its payload omits the
derived attempt ID to avoid a self-hash cycle; SHA-256 of the signed envelope becomes that ID.
``record_attempt`` retries a bounded generated-ID collision while holding archive uniqueness, and
``publish_attempt`` atomically adds the new occurrence plus a new or deduplicated plot. Complete
reads pre-admit unique aggregate blob bytes, authenticate the exact manifest, reconstruct every
available byte, and revalidate the signed attempt + plot graph. Archived-key verification proves
self-consistency only, never independent trust or archive completeness.
"""

import hashlib
import os
import re
import secrets
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from types import GenericAlias
from typing import Literal, cast

import msgspec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from verifier import __version__, attestation, canon, render
from verifier.errors import VerificationError
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.schema import VPlotSpec, decode_spec
from verifier.service.identity import (
    IdentityError,
    Signer,
    keyid_for_public_key,
    open_state_directory,
    validate_state_metadata,
)
from verifier.service.models import Verdict
from verifier.service.settings import Settings

__all__ = [
    "ATTEMPT_PAYLOAD_TYPE",
    "Archive",
    "ArchiveBatch",
    "ArchiveCollisionError",
    "ArchiveError",
    "ArchiveIntegrityError",
    "ArchiveNotFoundError",
    "ArchiveQuotaError",
    "ArchiveReadLimitError",
    "ArchiveSchemaError",
    "ArchiveStats",
    "AttemptArtifacts",
    "AttemptBundle",
    "AttemptDraft",
    "AttemptManifest",
    "AttemptOutcome",
    "AttemptRecord",
    "AttemptReference",
    "AttemptRole",
    "AttemptRoute",
    "BlobBinding",
    "BlobKind",
    "BlobRef",
    "BlobWrite",
    "KeyRecord",
    "PlotBundle",
    "PlotRecord",
    "PlotReference",
    "PlotRole",
    "SpecRecord",
    "materialize_attempt_bundle",
    "materialize_plot_bundle",
    "open_archive",
]

_SCHEMA_VERSION_V2 = 2
_SCHEMA_VERSION = 3
_DATABASE_NAME = "archive.sqlite3"
_BUSY_TIMEOUT_MS = 5_000
_BLOB_CHUNK_BYTES = 64 * 1024
_MAX_SQLITE_INTEGER = 2**63 - 1
_HEX64 = re.compile(r"[0-9a-f]{64}")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_DATABASE_OPEN_FLAGS = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
_DATABASE_CREATE_FLAGS = _DATABASE_OPEN_FLAGS | os.O_CREAT | os.O_EXCL
_CONFIG_ON = True
_CONFIG_OFF = False
_EXTRA_SYNCHRONOUS = 3
_META_COLUMNS = 2
_BLOB_METADATA_COLUMNS = 4
_KEY_RECORD_COLUMNS = 2
_SPEC_RECORD_COLUMNS = 2
_MIGRATION_SPEC_COLUMNS = 5
_ED25519_PUBLIC_KEY_BYTES = 32
_DATABASE_MODE = 0o600
_STATE_DIRECTORY_MODE = 0o700
_CONNECTION_FACTORY: type[sqlite3.Connection] = sqlite3.Connection
_PLOT_RECORD_COLUMNS = 3
_PLOT_REFERENCE_COLUMNS = 5
_ATTEMPT_RECORD_COLUMNS = 4
_ATTEMPT_REFERENCE_COLUMNS = 5
_ATTEMPT_VERSION: Literal["attempt-0.1"] = "attempt-0.1"
ATTEMPT_PAYLOAD_TYPE = "application/vnd.figure-verification.attempt.v0.1+json"
_ATTEMPT_NONCE_BYTES = 16
_ATTEMPT_NONCE_ATTEMPTS = 3
_NONCE_HEX = re.compile(r"[0-9a-f]{32}")
_TABLE_COLUMN_DESCRIPTOR = re.compile(
    r"(.*):(?:numeric:([0-9]+)|temporal:(date|datetime)|(string))", re.DOTALL
)
_UTC_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z")
_MAX_VERSION_BYTES = 128


class ArchiveError(RuntimeError):
    """Persistent provenance state is unsafe, unavailable, corrupt, or inconsistent."""


class ArchiveSchemaError(ArchiveError):
    """The database does not carry this implementation's exact schema version/shape."""


class ArchiveIntegrityError(ArchiveError):
    """A content address, immutable record, typed reference, or stored byte disagrees."""


class ArchiveNotFoundError(ArchiveError):
    """A requested archive address or typed reference is absent."""


class ArchiveQuotaError(ArchiveError):
    """Publishing new unique payload bytes would exceed the configured logical quota."""


class ArchiveReadLimitError(ArchiveError):
    """A stored blob exceeds the caller's role-specific read ceiling."""


class ArchiveCollisionError(ArchiveError):
    """A generated signed occurrence address already exists in the append-only archive."""


class BlobKind(StrEnum):
    """Closed byte roles needed by the planned plot + attempt provenance bundles."""

    RAW_CSV = "raw_csv"
    RAW_MANIFEST = "raw_manifest"
    CANONICAL_SPEC = "canonical_spec"
    RAW_SPEC = "raw_spec"
    PLOTTED_TABLE = "plotted_table"
    VERDICT = "verdict"
    VEGA_LITE = "vega_lite"
    SVG = "svg"
    VCERT_PAYLOAD = "vcert_payload"
    VCERT_ENVELOPE = "vcert_envelope"
    ED25519_PUBLIC_KEY = "ed25519_public_key"
    TOOL_VERSIONS = "tool_versions"
    MODEL_REQUEST = "model_request"
    MODEL_RESPONSE = "model_response"
    MODEL_REPLY = "model_reply"
    ATTEMPT_PAYLOAD = "attempt_payload"
    ATTEMPT_ENVELOPE = "attempt_envelope"


class PlotRole(StrEnum):
    """Blob roles carried by a content-deduplicated successful plot."""

    RAW_CSV = BlobKind.RAW_CSV
    RAW_MANIFEST = BlobKind.RAW_MANIFEST
    CANONICAL_SPEC = BlobKind.CANONICAL_SPEC
    PLOTTED_TABLE = BlobKind.PLOTTED_TABLE
    VERDICT = BlobKind.VERDICT
    VEGA_LITE = BlobKind.VEGA_LITE
    SVG = BlobKind.SVG
    VCERT_PAYLOAD = BlobKind.VCERT_PAYLOAD
    TOOL_VERSIONS = BlobKind.TOOL_VERSIONS


class AttemptRole(StrEnum):
    """Observed-byte roles carried by one signed admitted attempt occurrence."""

    RAW_CSV = BlobKind.RAW_CSV
    RAW_MANIFEST = BlobKind.RAW_MANIFEST
    RAW_SPEC = BlobKind.RAW_SPEC
    VERDICT = BlobKind.VERDICT
    MODEL_REQUEST = BlobKind.MODEL_REQUEST
    MODEL_RESPONSE = BlobKind.MODEL_RESPONSE
    MODEL_REPLY = BlobKind.MODEL_REPLY
    ATTEMPT_PAYLOAD = BlobKind.ATTEMPT_PAYLOAD


class AttemptRoute(StrEnum):
    """Artifact-producing service entry routes included in the occurrence ledger."""

    VERIFY_AND_RENDER = "/verify-and-render"
    PROPOSE_SPEC = "/propose-spec"


class AttemptOutcome(StrEnum):
    """Closed outcome/fault classifier; the signed manifest also carries its HTTP status."""

    VERIFIED = "verified"
    REJECTED = "rejected"
    DATASET_NOT_FOUND = "dataset_not_found"
    PROPOSER_POLICY = "proposer_policy"
    DATASET_MISMATCH = "dataset_mismatch"
    MODEL_TRANSPORT = "model_transport"
    MODEL_CONTENT_ENCODING = "model_content_encoding"
    MODEL_RESPONSE_TOO_LARGE = "model_response_too_large"
    MODEL_HTTP_STATUS = "model_http_status"
    MODEL_PROMPT_TOKENS = "model_prompt_tokens"
    MODEL_INVALID_ENVELOPE = "model_invalid_envelope"
    MODEL_NO_CHOICES = "model_no_choices"
    MODEL_EMPTY_CONTENT = "model_empty_content"


_PLOT_BUNDLE_BYTE_FIELDS = (
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


@dataclass(frozen=True, slots=True, kw_only=True)
class PlotBundle:
    """One successful plot's exact content-deduplicated provenance snapshot.

    Every byte field maps to one closed archive kind. ``plot_id`` addresses the signed VCert
    envelope; ``keyid`` addresses the raw Ed25519 key that actually verifies it. Occurrence data
    (time, route, request/model trace) belongs to a later signed attempt bundle, never here.
    Construction checks only wire shape; materialization and archive publish/read revalidate the
    complete signature, canonical forms, verdict, and VCert hash graph under explicit limits.
    """

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
        _require_address(self.plot_id, subject="plot bundle id")
        _require_sha256(self.keyid, subject="plot bundle keyid")
        for name in _PLOT_BUNDLE_BYTE_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, bytes):
                msg = f"plot bundle {name} must be bytes, got {type(value).__name__}"
                raise TypeError(msg)


class BlobBinding(msgspec.Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    """One signed, closed blob role + exact SHA-256 content digest."""

    role: BlobKind
    digest: str


class AttemptManifest(msgspec.Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    """Canonical occurrence payload authenticated under ``ATTEMPT_PAYLOAD_TYPE``.

    ``attempt_id`` is deliberately absent: it is the SHA-256 of the DSSE envelope created only
    after this payload is signed. ``artifacts`` binds every available attempt-observation byte;
    ``plot_artifacts`` binds all eleven bytes of the optional complete plot bundle. The attempt
    payload/envelope cannot bind their own digest without a hash cycle, while DSSE directly
    authenticates the payload and the final ID directly addresses the envelope.
    """

    version: Literal["attempt-0.1"]
    nonce: str
    occurred_at: str
    route: AttemptRoute
    http_status: int
    outcome: AttemptOutcome
    plot_id: str | None
    artifacts: tuple[BlobBinding, ...]
    plot_artifacts: tuple[BlobBinding, ...]
    keyid: str
    verifier_version: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AttemptArtifacts:
    """Exact observed bytes available for one admitted attempt; absence stays ``None``."""

    raw_csv: bytes | None = field(default=None, repr=False)
    raw_manifest: bytes | None = field(default=None, repr=False)
    raw_spec: bytes | None = field(default=None, repr=False)
    verdict: bytes | None = field(default=None, repr=False)
    model_request: bytes | None = field(default=None, repr=False)
    model_response: bytes | None = field(default=None, repr=False)
    model_reply: bytes | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for _role, name in _ATTEMPT_ARTIFACT_FIELDS:
            value = getattr(self, name)
            if value is not None and not isinstance(value, bytes):
                msg = f"attempt artifact {name} must be bytes or None, got {type(value).__name__}"
                raise TypeError(msg)


@dataclass(frozen=True, slots=True, kw_only=True)
class AttemptDraft:
    """Unsigned occurrence facts + available bytes supplied to the archive recorder."""

    occurred_at: datetime
    route: AttemptRoute
    http_status: int
    outcome: AttemptOutcome
    artifacts: AttemptArtifacts
    plot: PlotBundle | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class AttemptBundle:
    """One signed occurrence plus exact observed bytes and its optional complete plot.

    The nested plot lets publish/read validate the manifest's complete plot digest namespace and
    makes successful occurrence publication one transaction. Repeated plots still deduplicate at
    the archive's typed-blob layer; only the fresh attempt payload/envelope need be new.
    """

    attempt_id: str
    keyid: str
    manifest: AttemptManifest
    artifacts: AttemptArtifacts
    attempt_payload: bytes = field(repr=False)
    attempt_envelope: bytes = field(repr=False)
    public_key: bytes = field(repr=False)
    plot: PlotBundle | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _require_address(self.attempt_id, subject="attempt bundle id")
        _require_sha256(self.keyid, subject="attempt bundle keyid")
        manifest_object: object = self.manifest
        artifacts_object: object = self.artifacts
        plot_object: object = self.plot
        if not isinstance(manifest_object, AttemptManifest):
            msg = (
                "attempt bundle manifest must be AttemptManifest, "
                f"got {type(self.manifest).__name__}"
            )
            raise TypeError(msg)
        if not isinstance(artifacts_object, AttemptArtifacts):
            msg = (
                "attempt bundle artifacts must be AttemptArtifacts, "
                f"got {type(self.artifacts).__name__}"
            )
            raise TypeError(msg)
        if plot_object is not None and not isinstance(plot_object, PlotBundle):
            msg = f"attempt bundle plot must be PlotBundle or None, got {type(self.plot).__name__}"
            raise TypeError(msg)
        for name in ("attempt_payload", "attempt_envelope", "public_key"):
            value = getattr(self, name)
            if not isinstance(value, bytes):
                msg = f"attempt bundle {name} must be bytes, got {type(value).__name__}"
                raise TypeError(msg)


_ATTEMPT_ARTIFACT_FIELDS: tuple[tuple[AttemptRole, str], ...] = (
    (AttemptRole.RAW_CSV, "raw_csv"),
    (AttemptRole.RAW_MANIFEST, "raw_manifest"),
    (AttemptRole.RAW_SPEC, "raw_spec"),
    (AttemptRole.VERDICT, "verdict"),
    (AttemptRole.MODEL_REQUEST, "model_request"),
    (AttemptRole.MODEL_RESPONSE, "model_response"),
    (AttemptRole.MODEL_REPLY, "model_reply"),
)
_PLOT_BINDING_FIELDS: tuple[tuple[BlobKind, str], ...] = (
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


def _require_sha256(value: str, *, subject: str) -> None:
    value_object: object = value
    if not isinstance(value_object, str) or _SHA256.fullmatch(value) is None:
        msg = f"{subject} must match sha256:<64 lowercase hex>, got {value!r}"
        raise ValueError(msg)


def _require_address(value: str, *, subject: str) -> None:
    value_object: object = value
    if not isinstance(value_object, str) or _HEX64.fullmatch(value) is None:
        msg = f"{subject} must contain exactly 64 lowercase hex characters, got {value!r}"
        raise ValueError(msg)


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class BlobRef:
    """One expected content digest + closed byte kind."""

    digest: str
    kind: BlobKind

    def __post_init__(self) -> None:
        _require_sha256(self.digest, subject="blob digest")
        kind_object: object = self.kind
        if not isinstance(kind_object, BlobKind):
            msg = f"blob kind must be a BlobKind, got {self.kind!r}"
            raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class BlobWrite:
    """Exact bytes plus their constructor-derived immutable content reference."""

    kind: BlobKind
    payload: bytes = field(repr=False)
    ref: BlobRef = field(init=False)

    def __post_init__(self) -> None:
        kind_object: object = self.kind
        payload_object: object = self.payload
        if not isinstance(kind_object, BlobKind):
            msg = f"blob kind must be a BlobKind, got {self.kind!r}"
            raise TypeError(msg)
        if not isinstance(payload_object, bytes):
            msg = f"blob payload must be bytes, got {type(self.payload).__name__}"
            raise TypeError(msg)
        object.__setattr__(self, "ref", BlobRef(_digest(self.payload), self.kind))


@dataclass(frozen=True, slots=True)
class KeyRecord:
    """A content-derived Ed25519 keyid bound to its raw public-key blob."""

    keyid: str
    public_key: BlobRef

    def __post_init__(self) -> None:
        _require_sha256(self.keyid, subject="keyid")
        if self.public_key.kind is not BlobKind.ED25519_PUBLIC_KEY:
            msg = "key record must reference an ed25519_public_key blob"
            raise ValueError(msg)
        if self.keyid != self.public_key.digest:
            msg = "keyid must equal the raw public-key blob digest"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class PlotRecord:
    """A plot address bound to its VCert DSSE envelope and signing-key record."""

    plot_id: str
    certificate: BlobRef
    keyid: str

    def __post_init__(self) -> None:
        _require_address(self.plot_id, subject="plot_id")
        _require_sha256(self.keyid, subject="plot keyid")
        if self.certificate.kind is not BlobKind.VCERT_ENVELOPE:
            msg = "plot record must reference a vcert_envelope blob"
            raise ValueError(msg)
        if self.certificate.digest != f"sha256:{self.plot_id}":
            msg = "plot_id must equal the VCert envelope SHA-256"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class SpecRecord:
    """A canonical domain-separated spec address bound to its exact canonical bytes."""

    spec_id: str
    canonical_spec: BlobRef

    def __post_init__(self) -> None:
        _require_address(self.spec_id, subject="spec_id")
        if self.canonical_spec.kind is not BlobKind.CANONICAL_SPEC:
            msg = "spec record must reference a canonical_spec blob"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """An occurrence address bound to its attempt DSSE envelope, signer, and optional plot."""

    attempt_id: str
    envelope: BlobRef
    keyid: str
    plot_id: str | None = None

    def __post_init__(self) -> None:
        _require_address(self.attempt_id, subject="attempt_id")
        _require_sha256(self.keyid, subject="attempt keyid")
        if self.plot_id is not None:
            _require_address(self.plot_id, subject="attempt plot_id")
        if self.envelope.kind is not BlobKind.ATTEMPT_ENVELOPE:
            msg = "attempt record must reference an attempt_envelope blob"
            raise ValueError(msg)
        if self.envelope.digest != f"sha256:{self.attempt_id}":
            msg = "attempt_id must equal the attempt envelope SHA-256"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class PlotReference:
    """One role-typed blob edge from a successful plot."""

    plot_id: str
    role: PlotRole
    blob: BlobRef

    def __post_init__(self) -> None:
        _require_address(self.plot_id, subject="plot reference id")
        role_object: object = self.role
        if not isinstance(role_object, PlotRole):
            msg = f"plot reference role must be a PlotRole, got {self.role!r}"
            raise TypeError(msg)
        if self.blob.kind.value != self.role.value:
            msg = f"plot role {self.role.value} requires blob kind {self.role.value}"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class AttemptReference:
    """One role-typed observed-byte edge from an attempt occurrence."""

    attempt_id: str
    role: AttemptRole
    blob: BlobRef

    def __post_init__(self) -> None:
        _require_address(self.attempt_id, subject="attempt reference id")
        role_object: object = self.role
        if not isinstance(role_object, AttemptRole):
            msg = f"attempt reference role must be an AttemptRole, got {self.role!r}"
            raise TypeError(msg)
        if self.blob.kind.value != self.role.value:
            msg = f"attempt role {self.role.value} requires blob kind {self.role.value}"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True, kw_only=True)
class ArchiveBatch:
    """All rows to publish atomically; references may target existing deduplicated rows."""

    blobs: tuple[BlobWrite, ...] = ()
    keys: tuple[KeyRecord, ...] = ()
    plots: tuple[PlotRecord, ...] = ()
    specs: tuple[SpecRecord, ...] = ()
    attempts: tuple[AttemptRecord, ...] = ()
    plot_references: tuple[PlotReference, ...] = ()
    attempt_references: tuple[AttemptReference, ...] = ()


@dataclass(frozen=True, slots=True)
class ArchiveStats:
    """Logical payload accounting + durable record counts (never filesystem byte usage)."""

    logical_blob_bytes: int
    blobs: int
    keys: int
    plots: int
    attempts: int


_PLOT_ROLE_FIELDS: tuple[tuple[PlotRole, str], ...] = (
    (PlotRole.RAW_CSV, "raw_csv"),
    (PlotRole.RAW_MANIFEST, "raw_manifest"),
    (PlotRole.CANONICAL_SPEC, "canonical_spec"),
    (PlotRole.PLOTTED_TABLE, "plotted_table"),
    (PlotRole.VERDICT, "verdict"),
    (PlotRole.VEGA_LITE, "vega_lite"),
    (PlotRole.SVG, "svg"),
    (PlotRole.VCERT_PAYLOAD, "vcert_payload"),
    (PlotRole.TOOL_VERSIONS, "tool_versions"),
)
_BUNDLE_ENCODER = msgspec.json.Encoder(order="deterministic")
_VERDICT_DECODER = msgspec.json.Decoder(Verdict, strict=True)
_TABLE_HEADER_DECODER = msgspec.json.Decoder(tuple[str, ...], strict=True)
_TOOL_VERSIONS_DECODER = msgspec.json.Decoder(render.Tcb, strict=True)
_ATTEMPT_DECODER = msgspec.json.Decoder(AttemptManifest, strict=True)
_ATTEMPT_STATUS: dict[AttemptOutcome, int] = {
    AttemptOutcome.VERIFIED: 200,
    AttemptOutcome.REJECTED: 200,
    AttemptOutcome.DATASET_NOT_FOUND: 404,
    AttemptOutcome.PROPOSER_POLICY: 422,
    AttemptOutcome.DATASET_MISMATCH: 502,
    AttemptOutcome.MODEL_TRANSPORT: 503,
    AttemptOutcome.MODEL_CONTENT_ENCODING: 502,
    AttemptOutcome.MODEL_RESPONSE_TOO_LARGE: 502,
    AttemptOutcome.MODEL_HTTP_STATUS: 502,
    AttemptOutcome.MODEL_PROMPT_TOKENS: 422,
    AttemptOutcome.MODEL_INVALID_ENVELOPE: 502,
    AttemptOutcome.MODEL_NO_CHOICES: 502,
    AttemptOutcome.MODEL_EMPTY_CONTENT: 502,
}
_MODEL_REQUEST_ONLY = {
    AttemptOutcome.MODEL_TRANSPORT,
    AttemptOutcome.MODEL_CONTENT_ENCODING,
    AttemptOutcome.MODEL_RESPONSE_TOO_LARGE,
}
_MODEL_REQUEST_RESPONSE = {
    AttemptOutcome.MODEL_HTTP_STATUS,
    AttemptOutcome.MODEL_PROMPT_TOKENS,
    AttemptOutcome.MODEL_INVALID_ENVELOPE,
    AttemptOutcome.MODEL_NO_CHOICES,
    AttemptOutcome.MODEL_EMPTY_CONTENT,
}


def _require_limits(limits: VerificationLimits) -> None:
    limits_object: object = limits
    if not isinstance(limits_object, VerificationLimits):
        msg = f"limits must be VerificationLimits, got {type(limits).__name__}"
        raise TypeError(msg)


def _decode_table_column(descriptor: str) -> canon.Column:
    match = _TABLE_COLUMN_DESCRIPTOR.fullmatch(descriptor)
    if match is None:
        msg = f"invalid plotted-table column descriptor: {descriptor!r}"
        raise ValueError(msg)
    name = match.group(1)
    scale = match.group(2)
    granularity = match.group(3)
    if scale is not None:
        return canon.NumericColumn(name=name, scale=int(scale))
    if granularity is not None:
        return canon.TemporalColumn(
            name=name, granularity=cast("Literal['date', 'datetime']", granularity)
        )
    return canon.StringColumn(name=name)


def _decode_canonical_table(payload: bytes) -> canon.Table:
    try:
        header, _separator, row_bytes = payload.partition(b"\n")
        columns = tuple(
            _decode_table_column(descriptor) for descriptor in _TABLE_HEADER_DECODER.decode(header)
        )
        cell_types = tuple(
            Decimal | None if isinstance(column, canon.NumericColumn) else str | None
            for column in columns
        )
        row_type = cast("type[tuple[canon.Cell, ...]]", GenericAlias(tuple, cell_types))
        row_decoder = msgspec.json.Decoder(row_type, strict=True)
        rows = tuple(row_decoder.decode(row) for row in row_bytes.splitlines())
        table = canon.Table(columns=columns, rows=rows)
        canonical = canon.serialize_table(table).encode("utf-8")
    except (msgspec.DecodeError, UnicodeDecodeError, ValueError, TypeError, ArithmeticError) as exc:
        msg = "plot bundle plotted table is not valid typed NDJSON"
        raise ArchiveIntegrityError(msg) from exc
    if canonical != payload:
        msg = "plot bundle plotted table bytes are not canonical"
        raise ArchiveIntegrityError(msg)
    return table


def _decode_canonical_verdict(payload: bytes, *, subject: str = "plot bundle") -> Verdict:
    try:
        verdict = _VERDICT_DECODER.decode(payload)
    except (ValueError, RecursionError) as exc:
        msg = f"{subject} verdict is not valid structured JSON"
        raise ArchiveIntegrityError(msg) from exc
    if _BUNDLE_ENCODER.encode(verdict) != payload:
        msg = f"{subject} verdict is not in the canonical deterministic JSON form"
        raise ArchiveIntegrityError(msg)
    if verdict.attempt_id is not None:
        msg = f"{subject} verdict must omit attempt_id before archival"
        raise ArchiveIntegrityError(msg)
    return verdict


def _decode_canonical_versions(payload: bytes) -> render.Tcb:
    try:
        versions = _TOOL_VERSIONS_DECODER.decode(payload)
    except (ValueError, RecursionError) as exc:
        msg = "plot bundle tool versions are not valid structured JSON"
        raise ArchiveIntegrityError(msg) from exc
    if _BUNDLE_ENCODER.encode(versions) != payload:
        msg = "plot bundle tool versions are not in the canonical deterministic JSON form"
        raise ArchiveIntegrityError(msg)
    return versions


def _decode_canonical_spec(payload: bytes) -> VPlotSpec:
    try:
        spec = decode_spec(payload)
    except (ValueError, RecursionError) as exc:
        msg = "plot bundle canonical spec is not a valid VPlot specification"
        raise ArchiveIntegrityError(msg) from exc
    if canon.spec_bytes(spec) != payload:
        msg = "plot bundle canonical spec bytes are not canonical"
        raise ArchiveIntegrityError(msg)
    return spec


def _authenticate_archive_certificate(
    *,
    plot_id: str,
    keyid: str,
    envelope: bytes,
    public_key_bytes: bytes,
    limits: VerificationLimits,
) -> attestation.VerifiedVCert:
    """Re-hold one archived certificate's addresses, producer form, signature, type, and payload.

    The digest-matching archived key proves archive self-consistency only. Callers must never add
    it to the operator's independent trust policy merely because this check succeeds.
    """
    envelope_limit = attestation.envelope_byte_limit(limits.max_attestation_bytes)
    if len(envelope) > envelope_limit:
        msg = f"archived VCert envelope has {len(envelope)} bytes; limit is {envelope_limit}"
        raise ArchiveReadLimitError(msg)
    if hashlib.sha256(envelope).hexdigest() != plot_id:
        msg = "plot id does not address its exact canonical VCert envelope bytes"
        raise ArchiveIntegrityError(msg)
    try:
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        actual_keyid = keyid_for_public_key(public_key_bytes)
        verified = attestation.verify_vcert(
            envelope,
            {keyid: public_key},
            limits=limits,
            require_canonical_envelope=True,
            expected_keyid_hint=keyid,
        )
    except (ValueError, attestation.AttestationError, VerificationError) as exc:
        msg = "archived VCert envelope or signing public key failed verification"
        raise ArchiveIntegrityError(msg) from exc
    if actual_keyid != keyid:
        msg = "archived keyid does not address its signing public key bytes"
        raise ArchiveIntegrityError(msg)
    if render.vcert_bytes(verified.certificate) != verified.payload:
        msg = "archived VCert payload is not in the canonical deterministic JSON form"
        raise ArchiveIntegrityError(msg)
    return verified


def _authenticated_bundle_certificate(
    bundle: PlotBundle, limits: VerificationLimits
) -> render.VCert:
    if len(bundle.vcert_payload) > limits.max_attestation_bytes:
        msg = (
            f"plot bundle VCert payload has {len(bundle.vcert_payload)} bytes; "
            f"limit is {limits.max_attestation_bytes}"
        )
        raise ArchiveReadLimitError(msg)
    verified = _authenticate_archive_certificate(
        plot_id=bundle.plot_id,
        keyid=bundle.keyid,
        envelope=bundle.vcert_envelope,
        public_key_bytes=bundle.public_key,
        limits=limits,
    )
    if verified.payload != bundle.vcert_payload:
        msg = "plot bundle VCert payload differs from the authenticated envelope payload"
        raise ArchiveIntegrityError(msg)
    return verified.certificate


def _validate_bundle_contents(bundle: PlotBundle, certificate: render.VCert) -> None:
    """Check canonical content + every VCert slot after envelope authentication."""

    spec = _decode_canonical_spec(bundle.canonical_spec)
    _decode_canonical_table(bundle.plotted_table)
    verdict = _decode_canonical_verdict(bundle.verdict)
    versions = _decode_canonical_versions(bundle.tool_versions)
    try:
        bundle.svg.decode("utf-8")
    except UnicodeDecodeError as exc:
        msg = "plot bundle SVG is not valid UTF-8"
        raise ArchiveIntegrityError(msg) from exc

    actual_hashes = (
        ("dataset", canon.hash_dataset(bundle.raw_csv), certificate.dataset_hash),
        ("manifest", canon.hash_manifest(bundle.raw_manifest), certificate.manifest_hash),
        ("spec", canon.hash_spec(spec), certificate.spec_hash),
        (
            "plotted table",
            canon.hash_table_bytes(bundle.plotted_table),
            certificate.plotted_table_hash,
        ),
        ("Vega-Lite", render.hash_vega_lite(bundle.vega_lite), certificate.vega_lite_hash),
    )
    for subject, actual, certified in actual_hashes:
        if actual != certified:
            msg = f"plot bundle {subject} bytes disagree with the certified hash"
            raise ArchiveIntegrityError(msg)
    if spec.dataset.hash != certificate.dataset_hash:
        msg = "plot bundle canonical spec dataset binding disagrees with the certified dataset"
        raise ArchiveIntegrityError(msg)

    if (
        not verdict.verified
        or verdict.layer != "verify"
        or any(result.status != "pass" for result in verdict.results)
    ):
        msg = "plot bundle verdict must be a complete passing verification outcome"
        raise ArchiveIntegrityError(msg)
    certified_checks = tuple(
        render.CertifiedCheck(id=result.check, method=result.method, status="pass")
        for result in verdict.results
    )
    if certificate.checks != certified_checks:
        msg = "plot bundle full method-aware verdict disagrees with certified checks"
        raise ArchiveIntegrityError(msg)
    if versions != certificate.tcb:
        msg = "plot bundle tool versions disagree with the VCert TCB"
        raise ArchiveIntegrityError(msg)


def _validate_plot_bundle(bundle: PlotBundle, limits: VerificationLimits) -> None:
    """Revalidate one bundle's signature + full byte/hash graph before trust or persistence."""
    _require_limits(limits)
    certificate = _authenticated_bundle_certificate(bundle, limits)
    _validate_bundle_contents(bundle, certificate)


def materialize_plot_bundle(
    prepared: render.PreparedArtifact,
    rendered: render.RenderResult,
    envelope: bytes,
    signer: Signer,
    *,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> PlotBundle:
    """Materialize exact successful-plot bytes from one evidence/render/signing chain.

    The function performs no I/O and invents no occurrence metadata. ``PreparedArtifact`` already
    retains the one exact ``RecomputedEvidence`` that crossed the core + formal gates; this binds
    its raw snapshots and recomputation to the native result and signed certificate. The complete
    method-aware verdict is projected from that final passing result tuple, never accepted as a
    second independently pairable input.
    """
    typed_values: tuple[tuple[object, type[object], str], ...] = (
        (prepared, render.PreparedArtifact, "prepared"),
        (rendered, render.RenderResult, "rendered"),
        (signer, Signer, "signer"),
    )
    for value, expected_type, name in typed_values:
        if not isinstance(value, expected_type):
            msg = f"{name} must be {expected_type.__name__}, got {type(value).__name__}"
            raise TypeError(msg)
    envelope_object: object = envelope
    if not isinstance(envelope_object, bytes):
        msg = f"envelope must be bytes, got {type(envelope).__name__}"
        raise TypeError(msg)
    _require_limits(limits)
    if rendered.vega_lite != prepared.vega_lite:
        msg = "rendered Vega-Lite bytes differ from the formal-passed prepared artifact"
        raise ValueError(msg)

    evidence = prepared.evidence
    verdict = Verdict(verified=True, layer="verify", results=prepared.results)
    bundle = PlotBundle(
        plot_id=hashlib.sha256(envelope).hexdigest(),
        keyid=signer.keyid,
        raw_csv=evidence.source_bytes,
        raw_manifest=evidence.manifest_bytes,
        canonical_spec=canon.spec_bytes(prepared.spec),
        plotted_table=canon.serialize_table(evidence.plotted_table).encode("utf-8"),
        verdict=_BUNDLE_ENCODER.encode(verdict),
        vega_lite=rendered.vega_lite,
        svg=rendered.svg.encode("utf-8"),
        vcert_payload=render.vcert_bytes(rendered.certificate),
        vcert_envelope=envelope,
        tool_versions=_BUNDLE_ENCODER.encode(rendered.certificate.tcb),
        public_key=signer.public_key_bytes,
    )
    _validate_plot_bundle(bundle, limits)
    return bundle


def _canonical_utc_timestamp(occurred_at: datetime) -> str:
    occurred_object: object = occurred_at
    if not isinstance(occurred_object, datetime) or occurred_at.utcoffset() is None:
        msg = "occurred_at must be a timezone-aware datetime"
        raise ValueError(msg)
    return occurred_at.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _artifact_bindings(artifacts: AttemptArtifacts) -> tuple[BlobBinding, ...]:
    return tuple(
        BlobBinding(role=BlobKind(role.value), digest=_digest(payload))
        for role, name in _ATTEMPT_ARTIFACT_FIELDS
        if (payload := cast("bytes | None", getattr(artifacts, name))) is not None
    )


def _plot_bindings(plot: PlotBundle | None) -> tuple[BlobBinding, ...]:
    if plot is None:
        return ()
    return tuple(
        BlobBinding(role=role, digest=_digest(cast("bytes", getattr(plot, name))))
        for role, name in _PLOT_BINDING_FIELDS
    )


def _validate_binding_tuple(bindings: tuple[BlobBinding, ...], *, subject: str) -> None:
    bindings_object: object = bindings
    if not isinstance(bindings_object, tuple):
        msg = f"attempt manifest {subject} must be a tuple"
        raise ArchiveIntegrityError(msg)
    seen: set[BlobKind] = set()
    for binding in bindings:
        binding_object: object = binding
        if not isinstance(binding_object, BlobBinding):
            msg = f"attempt manifest {subject} carries a malformed blob binding"
            raise ArchiveIntegrityError(msg)
        role_object: object = binding_object.role
        if not isinstance(role_object, BlobKind):
            msg = f"attempt manifest {subject} carries a malformed blob binding"
            raise ArchiveIntegrityError(msg)
        try:
            _require_sha256(binding.digest, subject=f"attempt manifest {subject} digest")
        except ValueError as exc:
            msg = f"attempt manifest {subject} carries a malformed blob digest"
            raise ArchiveIntegrityError(msg) from exc
        if binding.role in seen:
            msg = f"attempt manifest {subject} repeats blob role {binding.role.value}"
            raise ArchiveIntegrityError(msg)
        seen.add(binding.role)


def _validate_manifest_nonce_time(manifest: AttemptManifest) -> None:
    version_object: object = manifest.version
    nonce_object: object = manifest.nonce
    occurred_at_object: object = manifest.occurred_at
    if version_object != _ATTEMPT_VERSION:
        msg = f"attempt manifest version must be {_ATTEMPT_VERSION!r}"
        raise ArchiveIntegrityError(msg)
    if not isinstance(nonce_object, str) or _NONCE_HEX.fullmatch(nonce_object) is None:
        msg = "attempt manifest nonce must contain exactly 128 bits as lowercase hex"
        raise ArchiveIntegrityError(msg)
    if (
        not isinstance(occurred_at_object, str)
        or _UTC_TIMESTAMP.fullmatch(occurred_at_object) is None
    ):
        msg = "attempt manifest occurrence time is not canonical UTC"
        raise ArchiveIntegrityError(msg)
    try:
        parsed_time = datetime.fromisoformat(manifest.occurred_at)
    except ValueError as exc:
        msg = "attempt manifest occurrence time is not a real UTC instant"
        raise ArchiveIntegrityError(msg) from exc
    _canonical_utc_timestamp(parsed_time)


def _validate_manifest_route_status(manifest: AttemptManifest) -> None:
    route_object: object = manifest.route
    outcome_object: object = manifest.outcome
    if not isinstance(route_object, AttemptRoute):
        msg = "attempt manifest route is not a closed AttemptRoute"
        raise ArchiveIntegrityError(msg)
    if not isinstance(outcome_object, AttemptOutcome):
        msg = "attempt manifest outcome is not a closed AttemptOutcome"
        raise ArchiveIntegrityError(msg)
    if (
        type(manifest.http_status) is not int
        or manifest.http_status != _ATTEMPT_STATUS[manifest.outcome]
    ):
        msg = "attempt manifest HTTP status disagrees with its closed outcome"
        raise ArchiveIntegrityError(msg)


def _validate_manifest_identity(manifest: AttemptManifest) -> None:
    plot_id_object: object = manifest.plot_id
    version_object: object = manifest.verifier_version
    if plot_id_object is not None:
        try:
            _require_address(cast("str", plot_id_object), subject="attempt manifest plot_id")
        except ValueError as exc:
            msg = "attempt manifest plot_id is malformed"
            raise ArchiveIntegrityError(msg) from exc
    try:
        _require_sha256(manifest.keyid, subject="attempt manifest keyid")
    except ValueError as exc:
        msg = "attempt manifest keyid is malformed"
        raise ArchiveIntegrityError(msg) from exc
    if not isinstance(version_object, str) or not version_object:
        msg = "attempt manifest verifier version must be a non-empty string"
        raise ArchiveIntegrityError(msg)
    try:
        version_bytes = version_object.encode("utf-8")
    except UnicodeEncodeError as exc:
        msg = "attempt manifest verifier version is not valid UTF-8"
        raise ArchiveIntegrityError(msg) from exc
    if len(version_bytes) > _MAX_VERSION_BYTES:
        msg = f"attempt manifest verifier version exceeds {_MAX_VERSION_BYTES} UTF-8 bytes"
        raise ArchiveIntegrityError(msg)


def _validate_attempt_manifest_shape(manifest: AttemptManifest) -> None:
    manifest_object: object = manifest
    if not isinstance(manifest_object, AttemptManifest):
        msg = f"manifest must be AttemptManifest, got {type(manifest).__name__}"
        raise TypeError(msg)
    _validate_manifest_nonce_time(manifest)
    _validate_manifest_route_status(manifest)
    _validate_manifest_identity(manifest)
    _validate_binding_tuple(manifest.artifacts, subject="artifacts")
    _validate_binding_tuple(manifest.plot_artifacts, subject="plot artifacts")


def _present_model_roles(artifacts: AttemptArtifacts) -> set[AttemptRole]:
    return {
        role
        for role, name in _ATTEMPT_ARTIFACT_FIELDS
        if role in {AttemptRole.MODEL_REQUEST, AttemptRole.MODEL_RESPONSE, AttemptRole.MODEL_REPLY}
        and getattr(artifacts, name) is not None
    }


def _expected_model_roles(manifest: AttemptManifest) -> set[AttemptRole]:
    if manifest.route is AttemptRoute.VERIFY_AND_RENDER:
        if manifest.outcome not in {AttemptOutcome.VERIFIED, AttemptOutcome.REJECTED}:
            msg = "direct render attempts may only carry verified or rejected outcomes"
            raise ArchiveIntegrityError(msg)
        return set()
    if manifest.outcome in {
        AttemptOutcome.VERIFIED,
        AttemptOutcome.REJECTED,
        AttemptOutcome.DATASET_MISMATCH,
    }:
        return {
            AttemptRole.MODEL_REQUEST,
            AttemptRole.MODEL_RESPONSE,
            AttemptRole.MODEL_REPLY,
        }
    if manifest.outcome in _MODEL_REQUEST_ONLY:
        return {AttemptRole.MODEL_REQUEST}
    if manifest.outcome in _MODEL_REQUEST_RESPONSE:
        return {AttemptRole.MODEL_REQUEST, AttemptRole.MODEL_RESPONSE}
    return set()


def _validate_attempt_outcome(bundle: AttemptBundle) -> None:
    manifest = bundle.manifest
    artifacts = bundle.artifacts
    has_plot = bundle.plot is not None
    if has_plot != (manifest.outcome is AttemptOutcome.VERIFIED):
        msg = "attempt plot presence must exactly match a verified outcome"
        raise ArchiveIntegrityError(msg)
    if (artifacts.verdict is not None) != (
        manifest.outcome in {AttemptOutcome.VERIFIED, AttemptOutcome.REJECTED}
    ):
        msg = "attempt verdict presence disagrees with its outcome"
        raise ArchiveIntegrityError(msg)
    needs_raw_spec = manifest.outcome in {
        AttemptOutcome.VERIFIED,
        AttemptOutcome.REJECTED,
        AttemptOutcome.DATASET_MISMATCH,
    }
    if (artifacts.raw_spec is not None) != needs_raw_spec:
        msg = "attempt raw-spec presence disagrees with its outcome"
        raise ArchiveIntegrityError(msg)

    if _present_model_roles(artifacts) != _expected_model_roles(manifest):
        msg = "attempt model trace presence disagrees with its route/outcome"
        raise ArchiveIntegrityError(msg)

    if (
        manifest.route is AttemptRoute.PROPOSE_SPEC
        and artifacts.model_reply is not None
        and artifacts.model_reply != artifacts.raw_spec
    ):
        msg = "attempt model reply differs from the exact raw spec handed to decode"
        raise ArchiveIntegrityError(msg)
    if artifacts.verdict is not None:
        verdict = _decode_canonical_verdict(artifacts.verdict, subject="attempt bundle")
        expected_verified = manifest.outcome is AttemptOutcome.VERIFIED
        if verdict.verified != expected_verified:
            msg = "attempt canonical verdict judgement disagrees with its outcome"
            raise ArchiveIntegrityError(msg)
    if artifacts.verdict is None and (
        artifacts.raw_csv is not None or artifacts.raw_manifest is not None
    ):
        msg = "attempt without a verification verdict cannot invent verifier input trace bytes"
        raise ArchiveIntegrityError(msg)


@dataclass(frozen=True, slots=True)
class _AttemptAuthentication:
    attempt_id: str
    keyid: str
    payload: bytes
    envelope: bytes
    public_key: bytes


def _authenticate_attempt_payload(
    parts: _AttemptAuthentication, limits: VerificationLimits
) -> AttemptManifest:
    attempt_id = parts.attempt_id
    keyid = parts.keyid
    payload = parts.payload
    envelope = parts.envelope
    if len(payload) > limits.max_attestation_bytes:
        msg = f"attempt payload has {len(payload)} bytes; limit is {limits.max_attestation_bytes}"
        raise ArchiveReadLimitError(msg)
    envelope_limit = attestation.envelope_byte_limit(
        limits.max_attestation_bytes, payload_type=ATTEMPT_PAYLOAD_TYPE
    )
    if len(envelope) > envelope_limit:
        msg = f"attempt envelope has {len(envelope)} bytes; limit is {envelope_limit}"
        raise ArchiveReadLimitError(msg)
    if hashlib.sha256(envelope).hexdigest() != attempt_id:
        msg = "attempt bundle id does not address its exact DSSE envelope bytes"
        raise ArchiveIntegrityError(msg)
    try:
        public_key = Ed25519PublicKey.from_public_bytes(parts.public_key)
        actual_keyid = keyid_for_public_key(parts.public_key)
        if actual_keyid != keyid:
            msg = "attempt keyid does not address its signing public key bytes"
            raise ArchiveIntegrityError(msg)
        verified = attestation.verify_dsse(
            envelope,
            {keyid: public_key},
            payload_type=ATTEMPT_PAYLOAD_TYPE,
            max_payload_bytes=limits.max_attestation_bytes,
            require_canonical_envelope=True,
            expected_keyid_hint=keyid,
        )
    except (ValueError, attestation.AttestationError, VerificationError) as exc:
        msg = "attempt envelope or signing public key failed verification"
        raise ArchiveIntegrityError(msg) from exc
    if verified.payload != payload:
        msg = "attempt payload differs from the authenticated envelope payload"
        raise ArchiveIntegrityError(msg)
    try:
        manifest = _ATTEMPT_DECODER.decode(verified.payload)
    except (ValueError, RecursionError) as exc:
        msg = "authenticated attempt payload is not a valid v0.1 manifest"
        raise ArchiveIntegrityError(msg) from exc
    if _BUNDLE_ENCODER.encode(manifest) != verified.payload:
        msg = "attempt payload is not in the canonical deterministic JSON form"
        raise ArchiveIntegrityError(msg)
    return manifest


def _authenticated_attempt_manifest(
    bundle: AttemptBundle, limits: VerificationLimits
) -> AttemptManifest:
    manifest = _authenticate_attempt_payload(
        _AttemptAuthentication(
            bundle.attempt_id,
            bundle.keyid,
            bundle.attempt_payload,
            bundle.attempt_envelope,
            bundle.public_key,
        ),
        limits,
    )
    if manifest != bundle.manifest:
        msg = "attempt bundle manifest differs from its authenticated payload"
        raise ArchiveIntegrityError(msg)
    return manifest


def _validate_attempt_bundle(bundle: AttemptBundle, limits: VerificationLimits) -> None:
    _require_limits(limits)
    manifest = _authenticated_attempt_manifest(bundle, limits)
    _validate_attempt_manifest_shape(manifest)
    if manifest.keyid != bundle.keyid:
        msg = "attempt manifest keyid disagrees with the bundle signer"
        raise ArchiveIntegrityError(msg)
    if manifest.artifacts != _artifact_bindings(bundle.artifacts):
        msg = "attempt manifest artifact bindings disagree with observed bytes"
        raise ArchiveIntegrityError(msg)
    if manifest.plot_artifacts != _plot_bindings(bundle.plot):
        msg = "attempt manifest plot bindings disagree with the complete plot bytes"
        raise ArchiveIntegrityError(msg)
    plot_id = None if bundle.plot is None else bundle.plot.plot_id
    if manifest.plot_id != plot_id:
        msg = "attempt manifest plot_id disagrees with the complete plot"
        raise ArchiveIntegrityError(msg)
    _validate_attempt_outcome(bundle)
    if bundle.plot is not None:
        _validate_plot_bundle(bundle.plot, limits)
        if bundle.plot.keyid != bundle.keyid or bundle.plot.public_key != bundle.public_key:
            msg = "attempt signer differs from the successful plot signer"
            raise ArchiveIntegrityError(msg)
        if (
            bundle.artifacts.raw_csv != bundle.plot.raw_csv
            or bundle.artifacts.raw_manifest != bundle.plot.raw_manifest
            or bundle.artifacts.verdict != bundle.plot.verdict
        ):
            msg = "attempt observed verifier bytes disagree with the successful plot bundle"
            raise ArchiveIntegrityError(msg)
        versions = _decode_canonical_versions(bundle.plot.tool_versions)
        if manifest.verifier_version != versions.verifier_version:
            msg = "attempt verifier version disagrees with the successful plot TCB"
            raise ArchiveIntegrityError(msg)


def materialize_attempt_bundle(
    draft: AttemptDraft,
    signer: Signer,
    *,
    nonce: str,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> AttemptBundle:
    """Purely materialize and sign one occurrence using an explicit 128-bit nonce."""
    draft_object: object = draft
    signer_object: object = signer
    if not isinstance(draft_object, AttemptDraft):
        msg = f"draft must be AttemptDraft, got {type(draft).__name__}"
        raise TypeError(msg)
    route_object: object = draft.route
    outcome_object: object = draft.outcome
    artifacts_object: object = draft.artifacts
    plot_object: object = draft.plot
    if not isinstance(route_object, AttemptRoute):
        msg = f"draft route must be AttemptRoute, got {type(draft.route).__name__}"
        raise TypeError(msg)
    if not isinstance(outcome_object, AttemptOutcome):
        msg = f"draft outcome must be AttemptOutcome, got {type(draft.outcome).__name__}"
        raise TypeError(msg)
    if not isinstance(artifacts_object, AttemptArtifacts):
        msg = f"draft artifacts must be AttemptArtifacts, got {type(draft.artifacts).__name__}"
        raise TypeError(msg)
    if not isinstance(signer_object, Signer):
        msg = f"signer must be Signer, got {type(signer).__name__}"
        raise TypeError(msg)
    if plot_object is not None and not isinstance(plot_object, PlotBundle):
        msg = f"draft plot must be PlotBundle or None, got {type(draft.plot).__name__}"
        raise TypeError(msg)
    _require_limits(limits)
    occurred_at_text = _canonical_utc_timestamp(draft.occurred_at)
    manifest = AttemptManifest(
        version=_ATTEMPT_VERSION,
        nonce=nonce,
        occurred_at=occurred_at_text,
        route=draft.route,
        http_status=draft.http_status,
        outcome=draft.outcome,
        plot_id=None if draft.plot is None else draft.plot.plot_id,
        artifacts=_artifact_bindings(draft.artifacts),
        plot_artifacts=_plot_bindings(draft.plot),
        keyid=signer.keyid,
        verifier_version=__version__,
    )
    _validate_attempt_manifest_shape(manifest)
    payload = _BUNDLE_ENCODER.encode(manifest)
    envelope = attestation.sign_dsse(
        payload,
        signer.private_key,
        keyid=signer.keyid,
        payload_type=ATTEMPT_PAYLOAD_TYPE,
        max_payload_bytes=limits.max_attestation_bytes,
    )
    bundle = AttemptBundle(
        attempt_id=hashlib.sha256(envelope).hexdigest(),
        keyid=signer.keyid,
        manifest=manifest,
        artifacts=draft.artifacts,
        attempt_payload=payload,
        attempt_envelope=envelope,
        public_key=signer.public_key_bytes,
        plot=draft.plot,
    )
    _validate_attempt_bundle(bundle, limits)
    return bundle


def _attempt_nonce() -> str:
    """Return one CSPRNG 128-bit nonce in the manifest's canonical wire form."""
    return secrets.token_hex(_ATTEMPT_NONCE_BYTES)


_CREATE_META = """CREATE TABLE meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    logical_blob_bytes INTEGER NOT NULL CHECK (logical_blob_bytes >= 0)
) STRICT"""

_CREATE_BLOBS = """CREATE TABLE blobs (
    blob_id INTEGER PRIMARY KEY,
    digest TEXT NOT NULL CHECK (
        length(digest) = 71
        AND substr(digest, 1, 7) = 'sha256:'
        AND substr(digest, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    kind TEXT NOT NULL CHECK (kind IN (
        'raw_csv', 'raw_manifest', 'canonical_spec', 'raw_spec', 'plotted_table',
        'verdict', 'vega_lite', 'svg', 'vcert_payload', 'vcert_envelope',
        'ed25519_public_key', 'tool_versions', 'model_request', 'model_response',
        'model_reply', 'attempt_payload', 'attempt_envelope'
    )),
    size INTEGER NOT NULL CHECK (size >= 0),
    content BLOB NOT NULL,
    UNIQUE (digest, kind),
    CHECK (size = length(content))
) STRICT"""

_CREATE_KEYS = """CREATE TABLE keys (
    keyid TEXT PRIMARY KEY CHECK (
        length(keyid) = 71
        AND substr(keyid, 1, 7) = 'sha256:'
        AND substr(keyid, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    public_key_digest TEXT NOT NULL,
    public_key_kind TEXT NOT NULL CHECK (public_key_kind = 'ed25519_public_key'),
    CHECK (keyid = public_key_digest),
    FOREIGN KEY (public_key_digest, public_key_kind) REFERENCES blobs(digest, kind)
) STRICT, WITHOUT ROWID"""

_CREATE_PLOTS = """CREATE TABLE plots (
    plot_id TEXT PRIMARY KEY CHECK (
        length(plot_id) = 64 AND plot_id NOT GLOB '*[^0-9a-f]*'
    ),
    certificate_digest TEXT NOT NULL,
    certificate_kind TEXT NOT NULL CHECK (certificate_kind = 'vcert_envelope'),
    keyid TEXT NOT NULL,
    CHECK (certificate_digest = 'sha256:' || plot_id),
    FOREIGN KEY (certificate_digest, certificate_kind) REFERENCES blobs(digest, kind),
    FOREIGN KEY (keyid) REFERENCES keys(keyid)
) STRICT, WITHOUT ROWID"""

_CREATE_SPECS = """CREATE TABLE specs (
    spec_id TEXT PRIMARY KEY CHECK (
        length(spec_id) = 64 AND spec_id NOT GLOB '*[^0-9a-f]*'
    ),
    canonical_spec_digest TEXT NOT NULL,
    canonical_spec_kind TEXT NOT NULL CHECK (canonical_spec_kind = 'canonical_spec'),
    FOREIGN KEY (canonical_spec_digest, canonical_spec_kind) REFERENCES blobs(digest, kind)
) STRICT, WITHOUT ROWID"""

_CREATE_ATTEMPTS = """CREATE TABLE attempts (
    attempt_id TEXT PRIMARY KEY CHECK (
        length(attempt_id) = 64 AND attempt_id NOT GLOB '*[^0-9a-f]*'
    ),
    envelope_digest TEXT NOT NULL,
    envelope_kind TEXT NOT NULL CHECK (envelope_kind = 'attempt_envelope'),
    keyid TEXT NOT NULL,
    plot_id TEXT,
    CHECK (envelope_digest = 'sha256:' || attempt_id),
    FOREIGN KEY (envelope_digest, envelope_kind) REFERENCES blobs(digest, kind),
    FOREIGN KEY (keyid) REFERENCES keys(keyid),
    FOREIGN KEY (plot_id) REFERENCES plots(plot_id)
) STRICT, WITHOUT ROWID"""

_CREATE_PLOT_REFERENCES = """CREATE TABLE plot_references (
    plot_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN (
        'raw_csv', 'raw_manifest', 'canonical_spec', 'plotted_table', 'verdict',
        'vega_lite', 'svg', 'vcert_payload', 'tool_versions'
    )),
    blob_digest TEXT NOT NULL,
    blob_kind TEXT NOT NULL CHECK (blob_kind = role),
    PRIMARY KEY (plot_id, role),
    FOREIGN KEY (plot_id) REFERENCES plots(plot_id),
    FOREIGN KEY (blob_digest, blob_kind) REFERENCES blobs(digest, kind)
) STRICT, WITHOUT ROWID"""

_CREATE_ATTEMPT_REFERENCES = """CREATE TABLE attempt_references (
    attempt_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN (
        'raw_csv', 'raw_manifest', 'raw_spec', 'verdict', 'model_request',
        'model_response', 'model_reply', 'attempt_payload'
    )),
    blob_digest TEXT NOT NULL,
    blob_kind TEXT NOT NULL CHECK (blob_kind = role),
    PRIMARY KEY (attempt_id, role),
    FOREIGN KEY (attempt_id) REFERENCES attempts(attempt_id),
    FOREIGN KEY (blob_digest, blob_kind) REFERENCES blobs(digest, kind)
) STRICT, WITHOUT ROWID"""

_CREATE_BLOB_ACCOUNTING = """CREATE TRIGGER blobs_track_logical_bytes
AFTER INSERT ON blobs
BEGIN
    UPDATE meta SET logical_blob_bytes = logical_blob_bytes + NEW.size WHERE singleton = 1;
END"""

_CREATE_BLOB_UPDATE_GUARD = """CREATE TRIGGER blobs_reject_update
BEFORE UPDATE ON blobs
BEGIN
    SELECT RAISE(ABORT, 'archive blobs are immutable');
END"""

_CREATE_BLOB_DELETE_GUARD = """CREATE TRIGGER blobs_reject_delete
BEFORE DELETE ON blobs
BEGIN
    SELECT RAISE(ABORT, 'archive blobs are immutable');
END"""

# fmt: off
_CREATE_ATTEMPTS_BY_PLOT = "CREATE INDEX attempts_by_plot ON attempts(plot_id, attempt_id) WHERE plot_id IS NOT NULL"  # noqa: E501
# fmt: on

_SCHEMA_OBJECTS = (
    ("table", "meta", "meta", _CREATE_META),
    ("table", "blobs", "blobs", _CREATE_BLOBS),
    ("table", "keys", "keys", _CREATE_KEYS),
    ("table", "plots", "plots", _CREATE_PLOTS),
    ("table", "specs", "specs", _CREATE_SPECS),
    ("table", "attempts", "attempts", _CREATE_ATTEMPTS),
    ("table", "plot_references", "plot_references", _CREATE_PLOT_REFERENCES),
    ("table", "attempt_references", "attempt_references", _CREATE_ATTEMPT_REFERENCES),
    ("trigger", "blobs_track_logical_bytes", "blobs", _CREATE_BLOB_ACCOUNTING),
    ("trigger", "blobs_reject_update", "blobs", _CREATE_BLOB_UPDATE_GUARD),
    ("trigger", "blobs_reject_delete", "blobs", _CREATE_BLOB_DELETE_GUARD),
    ("index", "attempts_by_plot", "attempts", _CREATE_ATTEMPTS_BY_PLOT),
)
_SCHEMA_OBJECTS_V2 = tuple(row for row in _SCHEMA_OBJECTS if row[1] != "attempts_by_plot")
_SCHEMA_OBJECTS_V1 = tuple(row for row in _SCHEMA_OBJECTS_V2 if row[1] != "specs")

_INSERT_BLOB = "INSERT INTO blobs(digest, kind, size, content) VALUES (?, ?, ?, ?)"
_SELECT_BLOB = """SELECT blob_id, digest, kind, size
FROM blobs
WHERE digest = ?
ORDER BY kind = ? DESC, kind
LIMIT 1"""
_SELECT_EXACT_BLOB = """SELECT blob_id, digest, kind, size
FROM blobs
WHERE digest = ? AND kind = ?"""
_SELECT_PLOT_REFERENCE = """SELECT b.blob_id, b.digest, b.kind, b.size
FROM plot_references AS r
JOIN blobs AS b ON b.digest = r.blob_digest AND b.kind = r.blob_kind
WHERE r.plot_id = ? AND r.role = ?"""
_SELECT_ATTEMPT_REFERENCE = """SELECT b.blob_id, b.digest, b.kind, b.size
FROM attempt_references AS r
JOIN blobs AS b ON b.digest = r.blob_digest AND b.kind = r.blob_kind
WHERE r.attempt_id = ? AND r.role = ?"""
_SELECT_KEY_BLOB = """SELECT b.blob_id, b.digest, b.kind, b.size
FROM keys AS k
JOIN blobs AS b ON b.digest = k.public_key_digest AND b.kind = k.public_key_kind
WHERE k.keyid = ?"""
_SELECT_KEY_RECORD = """SELECT public_key_digest, public_key_kind
FROM keys
WHERE keyid = ?"""
_SELECT_SPEC_RECORD = """SELECT canonical_spec_digest, canonical_spec_kind
FROM specs
WHERE spec_id = ?"""
_SELECT_MIGRATION_SPECS = """SELECT p.plot_id, b.blob_id, b.digest, b.kind, b.size
FROM plots AS p
JOIN plot_references AS r ON r.plot_id = p.plot_id AND r.role = 'canonical_spec'
JOIN blobs AS b ON b.digest = r.blob_digest AND b.kind = r.blob_kind
ORDER BY p.plot_id"""
_SELECT_PLOT_ENVELOPE = """SELECT b.blob_id, b.digest, b.kind, b.size
FROM plots AS p
JOIN blobs AS b ON b.digest = p.certificate_digest AND b.kind = p.certificate_kind
WHERE p.plot_id = ?"""
_SELECT_ATTEMPT_ENVELOPE = """SELECT b.blob_id, b.digest, b.kind, b.size
FROM attempts AS a
JOIN blobs AS b ON b.digest = a.envelope_digest AND b.kind = a.envelope_kind
WHERE a.attempt_id = ?"""
_SELECT_PLOT_RECORD = """SELECT certificate_digest, certificate_kind, keyid
FROM plots
WHERE plot_id = ?"""
_SELECT_PLOT_REFERENCES = """SELECT r.role, b.blob_id, b.digest, b.kind, b.size
FROM plot_references AS r
JOIN blobs AS b ON b.digest = r.blob_digest AND b.kind = r.blob_kind
WHERE r.plot_id = ?
ORDER BY r.role"""
_SELECT_ATTEMPT_RECORD = """SELECT envelope_digest, envelope_kind, keyid, plot_id
FROM attempts
WHERE attempt_id = ?"""
_SELECT_ATTEMPT_REFERENCES = """SELECT r.role, b.blob_id, b.digest, b.kind, b.size
FROM attempt_references AS r
JOIN blobs AS b ON b.digest = r.blob_digest AND b.kind = r.blob_kind
WHERE r.attempt_id = ?
ORDER BY r.role"""
_SELECT_LOWEST_PLOT_ATTEMPT = (
    "SELECT attempt_id FROM attempts WHERE plot_id = ? ORDER BY attempt_id LIMIT 1"
)
_SELECT_ATTEMPT_EXISTS = "SELECT 1 FROM attempts WHERE attempt_id = ?"


def _read_scalar(connection: sqlite3.Connection, statement: str) -> object:
    row = connection.execute(statement).fetchone()
    if not isinstance(row, tuple) or len(row) != 1:
        msg = "SQLite setting/meta query did not return exactly one scalar"
        raise ArchiveIntegrityError(msg)
    return row[0]


def _require_connection_setting(name: str, actual: object, expected: object) -> None:
    if type(actual) is not type(expected) or actual != expected:
        msg = f"SQLite connection refused required {name}={expected!r}; got {actual!r}"
        raise ArchiveError(msg)


def _configure_connection(connection: sqlite3.Connection) -> None:
    connection.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_FKEY, _CONFIG_ON)
    connection.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, _CONFIG_ON)
    connection.setconfig(sqlite3.SQLITE_DBCONFIG_TRUSTED_SCHEMA, _CONFIG_OFF)
    connection.execute("PRAGMA journal_mode=DELETE").fetchone()
    connection.execute("PRAGMA synchronous=EXTRA")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.execute("PRAGMA busy_timeout=5000")

    _require_connection_setting(
        "journal_mode", _read_scalar(connection, "PRAGMA journal_mode"), "delete"
    )
    _require_connection_setting(
        "synchronous", _read_scalar(connection, "PRAGMA synchronous"), _EXTRA_SYNCHRONOUS
    )
    _require_connection_setting("foreign_keys", _read_scalar(connection, "PRAGMA foreign_keys"), 1)
    _require_connection_setting(
        "trusted_schema", _read_scalar(connection, "PRAGMA trusted_schema"), 0
    )
    _require_connection_setting(
        "busy_timeout", _read_scalar(connection, "PRAGMA busy_timeout"), _BUSY_TIMEOUT_MS
    )
    _require_connection_setting(
        "defensive",
        connection.getconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE),
        _CONFIG_ON,
    )
    _require_connection_setting(
        "trusted-schema config",
        connection.getconfig(sqlite3.SQLITE_DBCONFIG_TRUSTED_SCHEMA),
        _CONFIG_OFF,
    )
    _require_connection_setting(
        "foreign-key config",
        connection.getconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_FKEY),
        _CONFIG_ON,
    )


@contextmanager
def _immediate_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    else:
        connection.execute("COMMIT")


def _before_archive_commit() -> None:
    """Fault-injection seam: production is intentionally empty."""


def _schema_rows(connection: sqlite3.Connection) -> tuple[tuple[object, ...], ...]:
    rows = connection.execute(
        """SELECT type, name, tbl_name, sql
        FROM sqlite_schema
        WHERE name NOT GLOB ? AND sql IS NOT NULL
        ORDER BY type, name""",
        ("sqlite_*",),
    ).fetchall()
    return tuple(tuple(row) for row in rows)


def _validate_schema_version(
    connection: sqlite3.Connection,
    *,
    schema_version: int,
    schema_objects: tuple[tuple[str, str, str, str], ...],
    verify_accounting: bool,
) -> int:
    user_version = _read_scalar(connection, "PRAGMA user_version")
    if type(user_version) is not int or user_version != schema_version:
        msg = f"archive schema version must be {schema_version}; found {user_version!r}"
        raise ArchiveSchemaError(msg)

    expected_schema = tuple(sorted(schema_objects, key=lambda row: (row[0], row[1])))
    if _schema_rows(connection) != expected_schema:
        msg = "archive schema objects disagree with the exact versioned STRICT schema"
        raise ArchiveSchemaError(msg)

    row = connection.execute(
        "SELECT schema_version, logical_blob_bytes FROM meta WHERE singleton = ?", (1,)
    ).fetchone()
    if (
        not isinstance(row, tuple)
        or len(row) != _META_COLUMNS
        or type(row[0]) is not int
        or row[0] != schema_version
        or type(row[1]) is not int
        or not 0 <= row[1] <= _MAX_SQLITE_INTEGER
    ):
        msg = "archive meta row is absent, malformed, or version-inconsistent"
        raise ArchiveSchemaError(msg)
    logical_bytes = row[1]
    if verify_accounting:
        stored_sum = _read_scalar(connection, "SELECT COALESCE(SUM(size), 0) FROM blobs")
        if type(stored_sum) is not int or stored_sum != logical_bytes:
            msg = "archive logical-byte accounting disagrees with stored blob metadata"
            raise ArchiveIntegrityError(msg)
    return logical_bytes


def _validate_schema(connection: sqlite3.Connection, *, verify_accounting: bool) -> int:
    return _validate_schema_version(
        connection,
        schema_version=_SCHEMA_VERSION,
        schema_objects=_SCHEMA_OBJECTS,
        verify_accounting=verify_accounting,
    )


def _migrate_v1_to_v2(connection: sqlite3.Connection, *, max_spec_bytes: int) -> None:
    """Add the durable semantic-spec index from existing complete plot references atomically."""
    _validate_schema_version(
        connection,
        schema_version=1,
        schema_objects=_SCHEMA_OBJECTS_V1,
        verify_accounting=True,
    )
    connection.execute(_CREATE_SPECS)
    rows = connection.execute(_SELECT_MIGRATION_SPECS).fetchall()
    plot_count = _read_scalar(connection, "SELECT COUNT(*) FROM plots")
    if type(plot_count) is not int or len(rows) != plot_count:
        msg = "version-1 archive plots do not each resolve one canonical spec relation"
        raise ArchiveIntegrityError(msg)
    for row in rows:
        if not isinstance(row, tuple) or len(row) != _MIGRATION_SPEC_COLUMNS:
            msg = "version-1 archive canonical spec relation row is malformed"
            raise ArchiveIntegrityError(msg)
        plot_id, *blob_values = row
        if not isinstance(plot_id, str) or _HEX64.fullmatch(plot_id) is None:
            msg = "version-1 archive plot address is corrupt"
            raise ArchiveIntegrityError(msg)
        blob_row = _validated_blob_row(tuple(blob_values))
        reference = BlobRef(blob_row[1], BlobKind.CANONICAL_SPEC)
        if blob_row[2] != reference.kind.value:
            msg = "version-1 archive canonical spec relation resolves the wrong byte kind"
            raise ArchiveIntegrityError(msg)
        _admit_blob_row(blob_row, max_bytes=max_spec_bytes, subject="canonical spec migration")
        payload = _collect_blob(connection, reference, blob_row)
        spec = _decode_canonical_spec(payload)
        spec_id = canon.hash_spec(spec).removeprefix("sha256:")
        _put_spec(connection, SpecRecord(spec_id, reference))
    connection.execute(
        "UPDATE meta SET schema_version = ? WHERE singleton = ?", (_SCHEMA_VERSION_V2, 1)
    )
    connection.execute("PRAGMA user_version=2")


def _migrate_v2_to_v3(connection: sqlite3.Connection) -> None:
    """Add the indexed lowest-attempt lookup derived from existing attempt rows."""
    _validate_schema_version(
        connection,
        schema_version=_SCHEMA_VERSION_V2,
        schema_objects=_SCHEMA_OBJECTS_V2,
        verify_accounting=True,
    )
    connection.execute(_CREATE_ATTEMPTS_BY_PLOT)
    connection.execute(
        "UPDATE meta SET schema_version = ? WHERE singleton = ?", (_SCHEMA_VERSION, 1)
    )
    connection.execute("PRAGMA user_version=3")


def _create_or_validate_schema(connection: sqlite3.Connection, *, max_spec_bytes: int) -> None:
    _require_read_limit(max_spec_bytes)
    with _immediate_transaction(connection):
        version = _read_scalar(connection, "PRAGMA user_version")
        if version == 0:
            if _schema_rows(connection):
                msg = "refusing an unversioned non-empty SQLite schema"
                raise ArchiveSchemaError(msg)
            for _object_type, _name, _table, statement in _SCHEMA_OBJECTS:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO meta(singleton, schema_version, logical_blob_bytes) VALUES (?, ?, ?)",
                (1, _SCHEMA_VERSION, 0),
            )
            connection.execute("PRAGMA user_version=3")
        elif version == 1:
            _migrate_v1_to_v2(connection, max_spec_bytes=max_spec_bytes)
            _migrate_v2_to_v3(connection)
        elif version == _SCHEMA_VERSION_V2:
            _migrate_v2_to_v3(connection)
        _validate_schema(connection, verify_accounting=True)


def _validate_database_file(descriptor: int, state_descriptor: int) -> None:
    metadata = os.fstat(descriptor)
    validate_state_metadata(metadata, subject="archive database", expect_directory=False)
    if metadata.st_nlink != 1:
        msg = f"archive database must have exactly one hard link; got {metadata.st_nlink}"
        raise ArchiveError(msg)
    database_mode = stat.S_IMODE(metadata.st_mode)
    if database_mode != _DATABASE_MODE:
        msg = f"archive database must have mode 0600; got {database_mode:#05o}"
        raise ArchiveError(msg)
    state_mode = stat.S_IMODE(os.fstat(state_descriptor).st_mode)
    if state_mode != _STATE_DIRECTORY_MODE:
        msg = f"archive state directory must have mode 0700; got {state_mode:#05o}"
        raise ArchiveError(msg)


def _open_database_descriptor(state_descriptor: int) -> int:
    try:
        descriptor = os.open(_DATABASE_NAME, _DATABASE_CREATE_FLAGS, 0o600, dir_fd=state_descriptor)
    except FileExistsError:
        return os.open(_DATABASE_NAME, _DATABASE_OPEN_FLAGS, dir_fd=state_descriptor)
    try:
        os.fchmod(descriptor, _DATABASE_MODE)
        os.fsync(descriptor)
        os.fsync(state_descriptor)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _require_read_limit(max_bytes: int) -> None:
    if type(max_bytes) is not int or not 0 <= max_bytes <= _MAX_SQLITE_INTEGER:
        msg = f"max_bytes must be an integer in 0..{_MAX_SQLITE_INTEGER}, got {max_bytes!r}"
        raise ValueError(msg)


type _BlobRow = tuple[int, str, str, int]


@dataclass(frozen=True, slots=True)
class _BlobReadPolicy:
    max_bytes: int
    expected_payload: bytes | None
    collect: bool


@dataclass(frozen=True, slots=True)
class _ExpectedBlob:
    kind: BlobKind
    digest: str | None
    max_bytes: int


@dataclass(frozen=True, slots=True)
class _ImmutableWrite:
    select_sql: str
    insert_sql: str
    identity: tuple[object, ...]
    values: tuple[object, ...]
    subject: str


def _validated_blob_row(row: object) -> _BlobRow:
    if not isinstance(row, tuple) or len(row) != _BLOB_METADATA_COLUMNS:
        msg = "archive blob metadata row is malformed"
        raise ArchiveIntegrityError(msg)
    blob_id, digest, kind, size = row
    if (
        type(blob_id) is not int
        or blob_id <= 0
        or not isinstance(digest, str)
        or _SHA256.fullmatch(digest) is None
        or not isinstance(kind, str)
        or type(size) is not int
        or not 0 <= size <= _MAX_SQLITE_INTEGER
    ):
        msg = "archive blob metadata types or values are corrupt"
        raise ArchiveIntegrityError(msg)
    try:
        BlobKind(kind)
    except ValueError as exc:
        msg = f"archive blob carries unknown kind {kind!r}"
        raise ArchiveIntegrityError(msg) from exc
    return blob_id, digest, kind, size


def _validated_key_record(row: object, keyid: str) -> BlobRef:
    if not isinstance(row, tuple) or len(row) != _KEY_RECORD_COLUMNS:
        msg = "archive signing-key record is malformed"
        raise ArchiveIntegrityError(msg)
    public_key_digest, public_key_kind = row
    if public_key_digest != keyid or public_key_kind != BlobKind.ED25519_PUBLIC_KEY.value:
        msg = "archive signing-key record resolves the wrong address or byte kind"
        raise ArchiveIntegrityError(msg)
    return BlobRef(keyid, BlobKind.ED25519_PUBLIC_KEY)


def _admit_blob_row(
    row: _BlobRow,
    *,
    max_bytes: int,
    subject: str,
    exact_bytes: int | None = None,
) -> None:
    _require_read_limit(max_bytes)
    size = row[3]
    if size > max_bytes:
        msg = f"archive {subject} has {size} bytes; read limit is {max_bytes}"
        raise ArchiveReadLimitError(msg)
    if exact_bytes is not None and size != exact_bytes:
        msg = f"archive {subject} must have exactly {exact_bytes} bytes; found {size}"
        raise ArchiveIntegrityError(msg)


def _collect_blob(
    connection: sqlite3.Connection,
    reference: BlobRef,
    row: _BlobRow,
) -> bytes:
    payload = _consume_blob(
        connection,
        row,
        reference,
        _BlobReadPolicy(max_bytes=row[3], expected_payload=None, collect=True),
    )
    return cast("bytes", payload)


def _validated_spec_record(row: object, spec_id: str) -> BlobRef:
    if not isinstance(row, tuple) or len(row) != _SPEC_RECORD_COLUMNS:
        msg = "archive spec record is malformed"
        raise ArchiveIntegrityError(msg)
    canonical_spec_digest, canonical_spec_kind = row
    if (
        not isinstance(canonical_spec_digest, str)
        or _SHA256.fullmatch(canonical_spec_digest) is None
        or canonical_spec_kind != BlobKind.CANONICAL_SPEC.value
    ):
        msg = "archive spec record resolves the wrong address or byte kind"
        raise ArchiveIntegrityError(msg)
    _require_address(spec_id, subject="stored spec_id")
    return BlobRef(canonical_spec_digest, BlobKind.CANONICAL_SPEC)


def _blob_row(connection: sqlite3.Connection, reference: BlobRef) -> _BlobRow | None:
    row = connection.execute(
        _SELECT_EXACT_BLOB, (reference.digest, reference.kind.value)
    ).fetchone()
    if row is None:
        return None
    return _validated_blob_row(row)


def _consume_blob(
    connection: sqlite3.Connection,
    row: _BlobRow,
    expected: BlobRef,
    policy: _BlobReadPolicy,
) -> bytes | None:
    blob_id, digest, kind, size = row
    if digest != expected.digest or kind != expected.kind.value:
        msg = f"archive blob {expected.digest} does not carry expected kind {expected.kind.value}"
        raise ArchiveIntegrityError(msg)
    if policy.expected_payload is not None and size != len(policy.expected_payload):
        msg = f"archive blob {digest} size disagrees with the immutable content address"
        raise ArchiveIntegrityError(msg)
    if size > policy.max_bytes:
        msg = f"archive blob {digest} has {size} bytes; read limit is {policy.max_bytes}"
        raise ArchiveReadLimitError(msg)

    chunks: list[bytes] = []
    digest_state = hashlib.sha256()
    with connection.blobopen("blobs", "content", blob_id, readonly=True) as blob:
        if len(blob) != size:
            msg = f"archive blob {digest} payload length disagrees with metadata"
            raise ArchiveIntegrityError(msg)
        for offset in range(0, size, _BLOB_CHUNK_BYTES):
            expected_chunk = min(_BLOB_CHUNK_BYTES, size - offset)
            chunk = blob.read(expected_chunk)
            if len(chunk) != expected_chunk:
                msg = f"archive blob {digest} changed or ended during bounded read"
                raise ArchiveIntegrityError(msg)
            if (
                policy.expected_payload is not None
                and chunk != policy.expected_payload[offset : offset + expected_chunk]
            ):
                msg = f"archive blob {digest} content disagrees with the incoming typed payload"
                raise ArchiveIntegrityError(msg)
            digest_state.update(chunk)
            if policy.collect:
                chunks.append(chunk)
    if f"sha256:{digest_state.hexdigest()}" != digest:
        msg = f"archive blob {digest} failed content-digest verification"
        raise ArchiveIntegrityError(msg)
    if policy.collect:
        return b"".join(chunks)
    return None


def _plot_bundle_batch(bundle: PlotBundle) -> ArchiveBatch:
    role_blobs = {
        role: BlobWrite(BlobKind(role.value), cast("bytes", getattr(bundle, field_name)))
        for role, field_name in _PLOT_ROLE_FIELDS
    }
    envelope = BlobWrite(BlobKind.VCERT_ENVELOPE, bundle.vcert_envelope)
    public_key = BlobWrite(BlobKind.ED25519_PUBLIC_KEY, bundle.public_key)
    canonical_spec = role_blobs[PlotRole.CANONICAL_SPEC]
    spec_id = canon.hash_spec(_decode_canonical_spec(bundle.canonical_spec)).removeprefix("sha256:")
    return ArchiveBatch(
        blobs=(*role_blobs.values(), envelope, public_key),
        keys=(KeyRecord(bundle.keyid, public_key.ref),),
        plots=(PlotRecord(bundle.plot_id, envelope.ref, bundle.keyid),),
        specs=(SpecRecord(spec_id, canonical_spec.ref),),
        plot_references=tuple(
            PlotReference(bundle.plot_id, role, role_blobs[role].ref)
            for role, _field_name in _PLOT_ROLE_FIELDS
        ),
    )


def _attempt_bundle_batch(bundle: AttemptBundle) -> ArchiveBatch:
    artifact_blobs = {
        role: BlobWrite(BlobKind(role.value), payload)
        for role, name in _ATTEMPT_ARTIFACT_FIELDS
        if (payload := cast("bytes | None", getattr(bundle.artifacts, name))) is not None
    }
    attempt_payload_blob = BlobWrite(BlobKind.ATTEMPT_PAYLOAD, bundle.attempt_payload)
    envelope = BlobWrite(BlobKind.ATTEMPT_ENVELOPE, bundle.attempt_envelope)
    public_key = BlobWrite(BlobKind.ED25519_PUBLIC_KEY, bundle.public_key)
    plot_batch = ArchiveBatch() if bundle.plot is None else _plot_bundle_batch(bundle.plot)
    plot_id = None if bundle.plot is None else bundle.plot.plot_id
    return ArchiveBatch(
        blobs=(
            *plot_batch.blobs,
            *artifact_blobs.values(),
            attempt_payload_blob,
            envelope,
            public_key,
        ),
        keys=(*plot_batch.keys, KeyRecord(bundle.keyid, public_key.ref)),
        plots=plot_batch.plots,
        specs=plot_batch.specs,
        attempts=(AttemptRecord(bundle.attempt_id, envelope.ref, bundle.keyid, plot_id),),
        plot_references=plot_batch.plot_references,
        attempt_references=(
            *(
                AttemptReference(bundle.attempt_id, role, blob.ref)
                for role, blob in artifact_blobs.items()
            ),
            AttemptReference(
                bundle.attempt_id,
                AttemptRole.ATTEMPT_PAYLOAD,
                attempt_payload_blob.ref,
            ),
        ),
    )


def _validated_plot_record(row: object, plot_id: str) -> tuple[BlobRef, str]:
    if not isinstance(row, tuple) or len(row) != _PLOT_RECORD_COLUMNS:
        msg = "archive plot record is malformed"
        raise ArchiveIntegrityError(msg)
    certificate_digest, certificate_kind, keyid = row
    if (
        not isinstance(certificate_digest, str)
        or certificate_digest != f"sha256:{plot_id}"
        or certificate_kind != BlobKind.VCERT_ENVELOPE.value
        or not isinstance(keyid, str)
        or _SHA256.fullmatch(keyid) is None
    ):
        msg = "archive plot record types, address, certificate kind, or keyid are corrupt"
        raise ArchiveIntegrityError(msg)
    return BlobRef(certificate_digest, BlobKind.VCERT_ENVELOPE), keyid


def _plot_bundle_blob_rows(
    connection: sqlite3.Connection,
    plot_id: str,
    certificate: BlobRef,
    keyid: str,
) -> tuple[
    tuple[BlobRef, _BlobRow],
    tuple[BlobRef, _BlobRow],
    dict[PlotRole, tuple[BlobRef, _BlobRow]],
]:
    certificate_row = _blob_row(connection, certificate)
    key_row_value = connection.execute(_SELECT_KEY_BLOB, (keyid,)).fetchone()
    if certificate_row is None or key_row_value is None:
        msg = "archive plot certificate or signing-key relation is broken"
        raise ArchiveIntegrityError(msg)
    key_row = _validated_blob_row(key_row_value)
    key_ref = BlobRef(keyid, BlobKind.ED25519_PUBLIC_KEY)
    if key_row[1] != key_ref.digest or key_row[2] != key_ref.kind.value:
        msg = "archive plot signing-key record resolves to the wrong typed blob"
        raise ArchiveIntegrityError(msg)

    role_rows: dict[PlotRole, tuple[BlobRef, _BlobRow]] = {}
    rows = connection.execute(_SELECT_PLOT_REFERENCES, (plot_id,)).fetchall()
    for row in rows:
        if not isinstance(row, tuple) or len(row) != _PLOT_REFERENCE_COLUMNS:
            msg = "archive plot reference row is malformed"
            raise ArchiveIntegrityError(msg)
        role_value = row[0]
        try:
            role = PlotRole(role_value)
        except (TypeError, ValueError) as exc:
            msg = f"archive plot carries unknown role {role_value!r}"
            raise ArchiveIntegrityError(msg) from exc
        blob_row = _validated_blob_row(tuple(row[1:]))
        reference = BlobRef(blob_row[1], BlobKind(role.value))
        if blob_row[2] != reference.kind.value or role in role_rows:
            msg = "archive plot role resolves to a wrong-kind or duplicate blob"
            raise ArchiveIntegrityError(msg)
        role_rows[role] = (reference, blob_row)
    if set(role_rows) != set(PlotRole):
        msg = "archive plot does not carry every required role exactly once"
        raise ArchiveIntegrityError(msg)
    return (certificate, certificate_row), (key_ref, key_row), role_rows


def _read_complete_plot_bundle(
    connection: sqlite3.Connection,
    plot_id: str,
    *,
    max_bytes: int,
) -> PlotBundle:
    record_row = connection.execute(_SELECT_PLOT_RECORD, (plot_id,)).fetchone()
    if record_row is None:
        msg = "archive plot address was not found"
        raise ArchiveNotFoundError(msg)
    certificate, keyid = _validated_plot_record(record_row, plot_id)
    certificate_entry, key_entry, role_rows = _plot_bundle_blob_rows(
        connection, plot_id, certificate, keyid
    )

    entries = (certificate_entry, key_entry, *(role_rows[role] for role in PlotRole))
    admitted_bytes = 0
    for _reference, row in entries:
        size = row[3]
        if size > max_bytes - admitted_bytes:
            msg = f"archive plot bundle exceeds aggregate read limit of {max_bytes} bytes"
            raise ArchiveReadLimitError(msg)
        admitted_bytes += size

    def read_entry(entry: tuple[BlobRef, _BlobRow]) -> bytes:
        reference, row = entry
        payload = _consume_blob(
            connection,
            row,
            reference,
            _BlobReadPolicy(max_bytes=row[3], expected_payload=None, collect=True),
        )
        return cast("bytes", payload)

    certificate_payload = read_entry(certificate_entry)
    public_key = read_entry(key_entry)
    role_payloads = {role: read_entry(role_rows[role]) for role in PlotRole}
    return PlotBundle(
        plot_id=plot_id,
        keyid=keyid,
        raw_csv=role_payloads[PlotRole.RAW_CSV],
        raw_manifest=role_payloads[PlotRole.RAW_MANIFEST],
        canonical_spec=role_payloads[PlotRole.CANONICAL_SPEC],
        plotted_table=role_payloads[PlotRole.PLOTTED_TABLE],
        verdict=role_payloads[PlotRole.VERDICT],
        vega_lite=role_payloads[PlotRole.VEGA_LITE],
        svg=role_payloads[PlotRole.SVG],
        vcert_payload=role_payloads[PlotRole.VCERT_PAYLOAD],
        vcert_envelope=certificate_payload,
        tool_versions=role_payloads[PlotRole.TOOL_VERSIONS],
        public_key=public_key,
    )


def _validated_lowest_attempt_id(row: object) -> str:
    if not isinstance(row, tuple) or len(row) != 1:
        msg = "archive lowest plot-attempt row is malformed"
        raise ArchiveIntegrityError(msg)
    attempt_id = row[0]
    if not isinstance(attempt_id, str) or _HEX64.fullmatch(attempt_id) is None:
        msg = "archive lowest plot-attempt address is corrupt"
        raise ArchiveIntegrityError(msg)
    return attempt_id


def _validated_attempt_record(row: object, attempt_id: str) -> tuple[BlobRef, str, str | None]:
    if not isinstance(row, tuple) or len(row) != _ATTEMPT_RECORD_COLUMNS:
        msg = "archive attempt record is malformed"
        raise ArchiveIntegrityError(msg)
    envelope_digest, envelope_kind, keyid, plot_id = row
    if (
        not isinstance(envelope_digest, str)
        or envelope_digest != f"sha256:{attempt_id}"
        or envelope_kind != BlobKind.ATTEMPT_ENVELOPE.value
        or not isinstance(keyid, str)
        or _SHA256.fullmatch(keyid) is None
        or (
            plot_id is not None
            and (not isinstance(plot_id, str) or _HEX64.fullmatch(plot_id) is None)
        )
    ):
        msg = "archive attempt record types, address, envelope kind, keyid, or plot_id are corrupt"
        raise ArchiveIntegrityError(msg)
    return BlobRef(envelope_digest, BlobKind.ATTEMPT_ENVELOPE), keyid, plot_id


def _attempt_bundle_blob_rows(
    connection: sqlite3.Connection,
    attempt_id: str,
    envelope: BlobRef,
    keyid: str,
) -> tuple[
    tuple[BlobRef, _BlobRow],
    tuple[BlobRef, _BlobRow],
    dict[AttemptRole, tuple[BlobRef, _BlobRow]],
]:
    envelope_row = _blob_row(connection, envelope)
    key_row_value = connection.execute(_SELECT_KEY_BLOB, (keyid,)).fetchone()
    if envelope_row is None or key_row_value is None:
        msg = "archive attempt envelope or signing-key relation is broken"
        raise ArchiveIntegrityError(msg)
    key_row = _validated_blob_row(key_row_value)
    key_ref = BlobRef(keyid, BlobKind.ED25519_PUBLIC_KEY)
    if key_row[1] != key_ref.digest or key_row[2] != key_ref.kind.value:
        msg = "archive attempt signing-key record resolves to the wrong typed blob"
        raise ArchiveIntegrityError(msg)

    role_rows: dict[AttemptRole, tuple[BlobRef, _BlobRow]] = {}
    rows = connection.execute(_SELECT_ATTEMPT_REFERENCES, (attempt_id,)).fetchall()
    for row in rows:
        if not isinstance(row, tuple) or len(row) != _ATTEMPT_REFERENCE_COLUMNS:
            msg = "archive attempt reference row is malformed"
            raise ArchiveIntegrityError(msg)
        role_value = row[0]
        try:
            role = AttemptRole(role_value)
        except (TypeError, ValueError) as exc:
            msg = f"archive attempt carries unknown role {role_value!r}"
            raise ArchiveIntegrityError(msg) from exc
        blob_row = _validated_blob_row(tuple(row[1:]))
        reference = BlobRef(blob_row[1], BlobKind(role.value))
        if blob_row[2] != reference.kind.value or role in role_rows:
            msg = "archive attempt role resolves to a wrong-kind or duplicate blob"
            raise ArchiveIntegrityError(msg)
        role_rows[role] = (reference, blob_row)
    if AttemptRole.ATTEMPT_PAYLOAD not in role_rows:
        msg = "archive attempt does not carry its authenticated payload role"
        raise ArchiveIntegrityError(msg)
    return (envelope, envelope_row), (key_ref, key_row), role_rows


type _BlobEntry = tuple[BlobRef, _BlobRow]


def _read_unique_entries(
    connection: sqlite3.Connection,
    entries: tuple[_BlobEntry, ...],
    *,
    max_bytes: int,
) -> dict[BlobRef, bytes]:
    unique: dict[BlobRef, _BlobRow] = {}
    for reference, row in entries:
        previous = unique.get(reference)
        if previous is not None and previous != row:
            msg = "archive bundle resolves one typed digest to conflicting blob metadata"
            raise ArchiveIntegrityError(msg)
        unique[reference] = row
    admitted_bytes = 0
    for row in unique.values():
        size = row[3]
        if size > max_bytes - admitted_bytes:
            msg = f"archive attempt bundle exceeds aggregate read limit of {max_bytes} bytes"
            raise ArchiveReadLimitError(msg)
        admitted_bytes += size

    payloads: dict[BlobRef, bytes] = {}
    for reference, row in unique.items():
        payload = _consume_blob(
            connection,
            row,
            reference,
            _BlobReadPolicy(max_bytes=row[3], expected_payload=None, collect=True),
        )
        payloads[reference] = cast("bytes", payload)
    return payloads


@dataclass(frozen=True, slots=True)
class _PlotEntries:
    plot_id: str
    keyid: str
    certificate: _BlobEntry
    key: _BlobEntry
    roles: dict[PlotRole, _BlobEntry]


def _plot_from_entries(entries: _PlotEntries, payloads: dict[BlobRef, bytes]) -> PlotBundle:
    role_payloads = {role: payloads[entries.roles[role][0]] for role in PlotRole}
    return PlotBundle(
        plot_id=entries.plot_id,
        keyid=entries.keyid,
        raw_csv=role_payloads[PlotRole.RAW_CSV],
        raw_manifest=role_payloads[PlotRole.RAW_MANIFEST],
        canonical_spec=role_payloads[PlotRole.CANONICAL_SPEC],
        plotted_table=role_payloads[PlotRole.PLOTTED_TABLE],
        verdict=role_payloads[PlotRole.VERDICT],
        vega_lite=role_payloads[PlotRole.VEGA_LITE],
        svg=role_payloads[PlotRole.SVG],
        vcert_payload=role_payloads[PlotRole.VCERT_PAYLOAD],
        vcert_envelope=payloads[entries.certificate[0]],
        tool_versions=role_payloads[PlotRole.TOOL_VERSIONS],
        public_key=payloads[entries.key[0]],
    )


def _read_complete_attempt_bundle(
    connection: sqlite3.Connection,
    attempt_id: str,
    *,
    max_bytes: int,
    limits: VerificationLimits,
) -> AttemptBundle:
    record_row = connection.execute(_SELECT_ATTEMPT_RECORD, (attempt_id,)).fetchone()
    if record_row is None:
        msg = "archive attempt address was not found"
        raise ArchiveNotFoundError(msg)
    envelope, keyid, plot_id = _validated_attempt_record(record_row, attempt_id)
    envelope_entry, key_entry, role_rows = _attempt_bundle_blob_rows(
        connection, attempt_id, envelope, keyid
    )

    plot_parts: _PlotEntries | None = None
    plot_entries: tuple[_BlobEntry, ...] = ()
    if plot_id is not None:
        plot_record = connection.execute(_SELECT_PLOT_RECORD, (plot_id,)).fetchone()
        if plot_record is None:
            msg = "archive attempt's linked plot record is absent"
            raise ArchiveIntegrityError(msg)
        certificate, plot_keyid = _validated_plot_record(plot_record, plot_id)
        certificate_entry, plot_key_entry, plot_role_rows = _plot_bundle_blob_rows(
            connection, plot_id, certificate, plot_keyid
        )
        plot_parts = _PlotEntries(
            plot_id,
            plot_keyid,
            certificate_entry,
            plot_key_entry,
            plot_role_rows,
        )
        plot_entries = (
            certificate_entry,
            plot_key_entry,
            *(plot_role_rows[role] for role in PlotRole),
        )

    entries = (
        envelope_entry,
        key_entry,
        *(role_rows[role] for role in role_rows),
        *plot_entries,
    )
    payloads = _read_unique_entries(connection, entries, max_bytes=max_bytes)
    attempt_payload = payloads[role_rows[AttemptRole.ATTEMPT_PAYLOAD][0]]
    attempt_envelope = payloads[envelope_entry[0]]
    public_key = payloads[key_entry[0]]
    manifest = _authenticate_attempt_payload(
        _AttemptAuthentication(
            attempt_id,
            keyid,
            attempt_payload,
            attempt_envelope,
            public_key,
        ),
        limits,
    )

    def artifact(role: AttemptRole) -> bytes | None:
        entry = role_rows.get(role)
        return None if entry is None else payloads[entry[0]]

    artifacts = AttemptArtifacts(
        raw_csv=artifact(AttemptRole.RAW_CSV),
        raw_manifest=artifact(AttemptRole.RAW_MANIFEST),
        raw_spec=artifact(AttemptRole.RAW_SPEC),
        verdict=artifact(AttemptRole.VERDICT),
        model_request=artifact(AttemptRole.MODEL_REQUEST),
        model_response=artifact(AttemptRole.MODEL_RESPONSE),
        model_reply=artifact(AttemptRole.MODEL_REPLY),
    )
    plot = None if plot_parts is None else _plot_from_entries(plot_parts, payloads)
    bundle = AttemptBundle(
        attempt_id=attempt_id,
        keyid=keyid,
        manifest=manifest,
        artifacts=artifacts,
        attempt_payload=attempt_payload,
        attempt_envelope=attempt_envelope,
        public_key=public_key,
        plot=plot,
    )
    _validate_attempt_bundle(bundle, limits)
    return bundle


def _require_batch_items(batch: ArchiveBatch) -> None:
    fields: tuple[tuple[object, type[object], str], ...] = (
        (batch.blobs, BlobWrite, "blobs"),
        (batch.keys, KeyRecord, "keys"),
        (batch.plots, PlotRecord, "plots"),
        (batch.specs, SpecRecord, "specs"),
        (batch.attempts, AttemptRecord, "attempts"),
        (batch.plot_references, PlotReference, "plot_references"),
        (batch.attempt_references, AttemptReference, "attempt_references"),
    )
    for items, item_type, name in fields:
        if not isinstance(items, tuple) or any(not isinstance(item, item_type) for item in items):
            msg = f"archive batch {name} must be a tuple of {item_type.__name__} values"
            raise TypeError(msg)


def _unique_blob_writes(blobs: tuple[BlobWrite, ...]) -> tuple[BlobWrite, ...]:
    by_reference: dict[BlobRef, BlobWrite] = {}
    for blob in blobs:
        previous = by_reference.get(blob.ref)
        if previous is None:
            by_reference[blob.ref] = blob
        elif previous.payload != blob.payload:
            msg = f"batch reuses blob digest {blob.ref.digest} for conflicting typed bytes"
            raise ArchiveIntegrityError(msg)
    return tuple(by_reference.values())


def _put_immutable_row(connection: sqlite3.Connection, write: _ImmutableWrite) -> None:
    existing = connection.execute(write.select_sql, write.identity).fetchone()
    if existing is None:
        connection.execute(write.insert_sql, write.values)
    elif tuple(existing) != write.values:
        msg = f"existing immutable {write.subject} disagrees with the requested record"
        raise ArchiveIntegrityError(msg)


def _put_key(connection: sqlite3.Connection, record: KeyRecord) -> None:
    values = (record.keyid, record.public_key.digest, record.public_key.kind.value)
    _put_immutable_row(
        connection,
        _ImmutableWrite(
            select_sql=(
                "SELECT keyid, public_key_digest, public_key_kind FROM keys WHERE keyid = ?"
            ),
            insert_sql=(
                "INSERT INTO keys(keyid, public_key_digest, public_key_kind) VALUES (?, ?, ?)"
            ),
            identity=(record.keyid,),
            values=values,
            subject="key",
        ),
    )


def _put_plot(connection: sqlite3.Connection, record: PlotRecord) -> None:
    values = (
        record.plot_id,
        record.certificate.digest,
        record.certificate.kind.value,
        record.keyid,
    )
    _put_immutable_row(
        connection,
        _ImmutableWrite(
            select_sql=(
                "SELECT plot_id, certificate_digest, certificate_kind, keyid "
                "FROM plots WHERE plot_id = ?"
            ),
            insert_sql=(
                "INSERT INTO plots(plot_id, certificate_digest, certificate_kind, keyid) "
                "VALUES (?, ?, ?, ?)"
            ),
            identity=(record.plot_id,),
            values=values,
            subject="plot",
        ),
    )


def _put_spec(connection: sqlite3.Connection, record: SpecRecord) -> None:
    values = (
        record.spec_id,
        record.canonical_spec.digest,
        record.canonical_spec.kind.value,
    )
    _put_immutable_row(
        connection,
        _ImmutableWrite(
            select_sql=(
                "SELECT spec_id, canonical_spec_digest, canonical_spec_kind "
                "FROM specs WHERE spec_id = ?"
            ),
            insert_sql=(
                "INSERT INTO specs(spec_id, canonical_spec_digest, canonical_spec_kind) "
                "VALUES (?, ?, ?)"
            ),
            identity=(record.spec_id,),
            values=values,
            subject="spec",
        ),
    )


def _put_attempt(connection: sqlite3.Connection, record: AttemptRecord) -> None:
    values = (
        record.attempt_id,
        record.envelope.digest,
        record.envelope.kind.value,
        record.keyid,
        record.plot_id,
    )
    _put_immutable_row(
        connection,
        _ImmutableWrite(
            select_sql=(
                "SELECT attempt_id, envelope_digest, envelope_kind, keyid, plot_id "
                "FROM attempts WHERE attempt_id = ?"
            ),
            insert_sql=(
                "INSERT INTO attempts(attempt_id, envelope_digest, envelope_kind, keyid, plot_id) "
                "VALUES (?, ?, ?, ?, ?)"
            ),
            identity=(record.attempt_id,),
            values=values,
            subject="attempt",
        ),
    )


def _put_plot_reference(connection: sqlite3.Connection, reference: PlotReference) -> None:
    values = (
        reference.plot_id,
        reference.role.value,
        reference.blob.digest,
        reference.blob.kind.value,
    )
    _put_immutable_row(
        connection,
        _ImmutableWrite(
            select_sql=(
                "SELECT plot_id, role, blob_digest, blob_kind FROM plot_references "
                "WHERE plot_id = ? AND role = ?"
            ),
            insert_sql=(
                "INSERT INTO plot_references(plot_id, role, blob_digest, blob_kind) "
                "VALUES (?, ?, ?, ?)"
            ),
            identity=(reference.plot_id, reference.role.value),
            values=values,
            subject="plot reference",
        ),
    )


def _put_attempt_reference(connection: sqlite3.Connection, reference: AttemptReference) -> None:
    values = (
        reference.attempt_id,
        reference.role.value,
        reference.blob.digest,
        reference.blob.kind.value,
    )
    _put_immutable_row(
        connection,
        _ImmutableWrite(
            select_sql=(
                "SELECT attempt_id, role, blob_digest, blob_kind FROM attempt_references "
                "WHERE attempt_id = ? AND role = ?"
            ),
            insert_sql=(
                "INSERT INTO attempt_references(attempt_id, role, blob_digest, blob_kind) "
                "VALUES (?, ?, ?, ?)"
            ),
            identity=(reference.attempt_id, reference.role.value),
            values=values,
            subject="attempt reference",
        ),
    )


def _partition_new_blobs(
    connection: sqlite3.Connection, blobs: tuple[BlobWrite, ...]
) -> tuple[tuple[BlobWrite, ...], int]:
    new_blobs: list[BlobWrite] = []
    new_bytes = 0
    for blob in blobs:
        existing = _blob_row(connection, blob.ref)
        if existing is None:
            new_blobs.append(blob)
            new_bytes += len(blob.payload)
        else:
            _consume_blob(
                connection,
                existing,
                blob.ref,
                _BlobReadPolicy(
                    max_bytes=len(blob.payload),
                    expected_payload=blob.payload,
                    collect=False,
                ),
            )
    return tuple(new_blobs), new_bytes


def _enforce_quota(current_bytes: int, new_bytes: int, max_logical_bytes: int) -> None:
    if new_bytes > 0 and (
        current_bytes > max_logical_bytes or new_bytes > max_logical_bytes - current_bytes
    ):
        msg = (
            f"archive logical payload would exceed {max_logical_bytes} bytes "
            f"({current_bytes} stored + {new_bytes} new)"
        )
        raise ArchiveQuotaError(msg)


def _insert_batch_rows(
    connection: sqlite3.Connection,
    batch: ArchiveBatch,
    new_blobs: tuple[BlobWrite, ...],
) -> None:
    for blob in new_blobs:
        connection.execute(
            _INSERT_BLOB,
            (blob.ref.digest, blob.kind.value, len(blob.payload), blob.payload),
        )
    for key_record in batch.keys:
        _put_key(connection, key_record)
    for plot_record in batch.plots:
        _put_plot(connection, plot_record)
    for spec_record in batch.specs:
        _put_spec(connection, spec_record)
    for attempt_record in batch.attempts:
        _put_attempt(connection, attempt_record)
    for plot_reference in batch.plot_references:
        _put_plot_reference(connection, plot_reference)
    for attempt_reference in batch.attempt_references:
        _put_attempt_reference(connection, attempt_reference)


def _publish_batch(
    connection: sqlite3.Connection,
    batch: ArchiveBatch,
    blobs: tuple[BlobWrite, ...],
    max_logical_bytes: int,
) -> None:
    current_bytes = _validate_schema(connection, verify_accounting=False)
    new_blobs, new_bytes = _partition_new_blobs(connection, blobs)
    _enforce_quota(current_bytes, new_bytes, max_logical_bytes)
    _insert_batch_rows(connection, batch, new_blobs)
    expected_bytes = current_bytes + new_bytes
    if _validate_schema(connection, verify_accounting=False) != expected_bytes:
        msg = "archive logical-byte trigger did not account for the complete batch"
        raise ArchiveIntegrityError(msg)
    _before_archive_commit()


def _publish_unique_attempt(
    connection: sqlite3.Connection,
    bundle: AttemptBundle,
    batch: ArchiveBatch,
    blobs: tuple[BlobWrite, ...],
    max_logical_bytes: int,
) -> None:
    if connection.execute(_SELECT_ATTEMPT_EXISTS, (bundle.attempt_id,)).fetchone() is not None:
        msg = f"signed attempt address {bundle.attempt_id} already exists"
        raise ArchiveCollisionError(msg)
    _publish_batch(connection, batch, blobs, max_logical_bytes)


class Archive:
    """Versioned SQLite archive; construction initializes and validates durable state."""

    __slots__ = ("_database_path", "_max_logical_bytes", "_state_dir")

    def __init__(
        self,
        state_dir: Path,
        *,
        max_logical_bytes: int,
        max_spec_bytes: int,
    ) -> None:
        state_object: object = state_dir
        if not isinstance(state_object, Path) or not state_dir.is_absolute():
            msg = "archive state_dir must be an absolute Path"
            raise ValueError(msg)
        if type(max_logical_bytes) is not int or not 1 <= max_logical_bytes <= _MAX_SQLITE_INTEGER:
            msg = (
                "max_logical_bytes must be an integer in "
                f"1..{_MAX_SQLITE_INTEGER}, got {max_logical_bytes!r}"
            )
            raise ValueError(msg)
        if type(max_spec_bytes) is not int or not 1 <= max_spec_bytes <= _MAX_SQLITE_INTEGER:
            msg = (
                "max_spec_bytes must be an integer in "
                f"1..{_MAX_SQLITE_INTEGER}, got {max_spec_bytes!r}"
            )
            raise ValueError(msg)
        self._state_dir = state_dir
        self._database_path = state_dir / _DATABASE_NAME
        self._max_logical_bytes = max_logical_bytes
        connection = self._connect()
        try:
            _create_or_validate_schema(connection, max_spec_bytes=max_spec_bytes)
        except sqlite3.Error as exc:
            msg = "SQLite failed while initializing the provenance schema"
            raise ArchiveError(msg) from exc
        finally:
            connection.close()

    @property
    def database_path(self) -> Path:
        return self._database_path

    @property
    def max_logical_bytes(self) -> int:
        return self._max_logical_bytes

    def _connect(self) -> sqlite3.Connection:
        try:
            state_descriptor = open_state_directory(self._state_dir)
            try:
                database_descriptor = _open_database_descriptor(state_descriptor)
                try:
                    _validate_database_file(database_descriptor, state_descriptor)
                    proc_path = f"/proc/self/fd/{state_descriptor}/{_DATABASE_NAME}"
                    connection = sqlite3.connect(
                        proc_path,
                        timeout=_BUSY_TIMEOUT_MS / 1_000,
                        factory=_CONNECTION_FACTORY,
                        autocommit=True,
                    )
                    try:
                        _configure_connection(connection)
                    except Exception:
                        connection.close()
                        raise
                    return connection
                finally:
                    os.close(database_descriptor)
            finally:
                os.close(state_descriptor)
        except ArchiveError:
            raise
        except (IdentityError, OSError, sqlite3.Error) as exc:
            msg = "could not open the secure provenance archive"
            raise ArchiveError(msg) from exc

    def publish(self, batch: ArchiveBatch) -> None:
        """Atomically publish a complete low-level batch, deduplicating exact typed blobs."""
        batch_object: object = batch
        if not isinstance(batch_object, ArchiveBatch):
            msg = f"batch must be an ArchiveBatch, got {type(batch).__name__}"
            raise TypeError(msg)
        _require_batch_items(batch)
        blobs = _unique_blob_writes(batch.blobs)
        connection = self._connect()
        try:
            with _immediate_transaction(connection):
                _publish_batch(connection, batch, blobs, self._max_logical_bytes)
        except ArchiveError:
            raise
        except sqlite3.IntegrityError as exc:
            msg = "archive batch violates an immutable typed reference"
            raise ArchiveIntegrityError(msg) from exc
        except sqlite3.Error as exc:
            msg = "SQLite failed while publishing the provenance transaction"
            raise ArchiveError(msg) from exc
        finally:
            connection.close()

    def publish_plot(
        self,
        bundle: PlotBundle,
        *,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> None:
        """Revalidate and atomically publish one complete successful-plot bundle."""
        bundle_object: object = bundle
        if not isinstance(bundle_object, PlotBundle):
            msg = f"bundle must be a PlotBundle, got {type(bundle).__name__}"
            raise TypeError(msg)
        _validate_plot_bundle(bundle, limits)
        self.publish(_plot_bundle_batch(bundle))

    def publish_attempt(
        self,
        bundle: AttemptBundle,
        *,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> None:
        """Validate and atomically publish one occurrence plus its optional complete plot.

        Unlike content-idempotent plots, an occurrence address must be new. A duplicate raises
        ``ArchiveCollisionError`` so ``record_attempt`` can regenerate its nonce without silently
        aliasing two requests.
        """
        bundle_object: object = bundle
        if not isinstance(bundle_object, AttemptBundle):
            msg = f"bundle must be an AttemptBundle, got {type(bundle).__name__}"
            raise TypeError(msg)
        _validate_attempt_bundle(bundle, limits)
        batch = _attempt_bundle_batch(bundle)
        _require_batch_items(batch)
        blobs = _unique_blob_writes(batch.blobs)
        connection = self._connect()
        try:
            with _immediate_transaction(connection):
                _publish_unique_attempt(
                    connection,
                    bundle,
                    batch,
                    blobs,
                    self._max_logical_bytes,
                )
        except ArchiveError:
            raise
        except sqlite3.IntegrityError as exc:
            msg = "archive attempt violates an immutable typed reference"
            raise ArchiveIntegrityError(msg) from exc
        except sqlite3.Error as exc:
            msg = "SQLite failed while publishing the attempt transaction"
            raise ArchiveError(msg) from exc
        finally:
            connection.close()

    def record_attempt(
        self,
        draft: AttemptDraft,
        signer: Signer,
        *,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> AttemptBundle:
        """Generate/sign/publish one occurrence, retrying bounded CSPRNG nonce collisions."""
        for _attempt in range(_ATTEMPT_NONCE_ATTEMPTS):
            bundle = materialize_attempt_bundle(
                draft,
                signer=signer,
                nonce=_attempt_nonce(),
                limits=limits,
            )
            try:
                self.publish_attempt(bundle, limits=limits)
            except ArchiveCollisionError:
                continue
            return bundle
        msg = f"attempt nonce collisions exhausted {_ATTEMPT_NONCE_ATTEMPTS} signed candidates"
        raise ArchiveCollisionError(msg)

    def _read_payload(
        self,
        statement: str,
        identity: tuple[object, ...],
        expected: _ExpectedBlob,
    ) -> bytes:
        _require_read_limit(expected.max_bytes)
        connection = self._connect()
        try:
            row = connection.execute(statement, identity).fetchone()
            if row is None:
                msg = "archive address or typed reference was not found"
                raise ArchiveNotFoundError(msg)
            blob_row = _validated_blob_row(row)
            digest = blob_row[1] if expected.digest is None else expected.digest
            payload = _consume_blob(
                connection,
                blob_row,
                BlobRef(digest, expected.kind),
                _BlobReadPolicy(
                    max_bytes=expected.max_bytes,
                    expected_payload=None,
                    collect=True,
                ),
            )
            return cast("bytes", payload)
        except ArchiveError:
            raise
        except sqlite3.Error as exc:
            msg = "SQLite failed during a bounded archive blob read"
            raise ArchiveError(msg) from exc
        finally:
            connection.close()

    def read_blob(self, reference: BlobRef, *, max_bytes: int) -> bytes:
        """Read one exact kind-bound digest after metadata-first byte admission."""
        reference_object: object = reference
        if not isinstance(reference_object, BlobRef):
            msg = f"reference must be a BlobRef, got {type(reference).__name__}"
            raise TypeError(msg)
        return self._read_payload(
            _SELECT_BLOB,
            (reference.digest, reference.kind.value),
            _ExpectedBlob(reference.kind, reference.digest, max_bytes),
        )

    def read_certificate(
        self,
        plot_id: str,
        *,
        max_bytes: int,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> bytes:
        """Read and independently authenticate one public VCert envelope without other plot data.

        The plot/key rows and both bounded typed blobs resolve on one connection. The archived key
        proves self-consistency only; this method never consults or extends operator trust policy.
        """
        _require_address(plot_id, subject="plot_id")
        _require_read_limit(max_bytes)
        _require_limits(limits)
        connection = self._connect()
        result: bytes
        try:
            _validate_schema(connection, verify_accounting=False)
            record_row = connection.execute(_SELECT_PLOT_RECORD, (plot_id,)).fetchone()
            if record_row is None:
                msg = "archive plot address was not found"
                raise ArchiveNotFoundError(msg)
            certificate, keyid = _validated_plot_record(record_row, plot_id)
            certificate_row = _blob_row(connection, certificate)
            if certificate_row is None:
                msg = "archive plot certificate relation is broken"
                raise ArchiveIntegrityError(msg)
            key_record = connection.execute(_SELECT_KEY_RECORD, (keyid,)).fetchone()
            if key_record is None:
                msg = "archive plot signing-key relation is broken"
                raise ArchiveIntegrityError(msg)
            key_reference = _validated_key_record(key_record, keyid)
            key_row = _blob_row(connection, key_reference)
            if key_row is None:
                msg = "archive plot signing-key blob is absent"
                raise ArchiveIntegrityError(msg)

            _admit_blob_row(certificate_row, max_bytes=max_bytes, subject="VCert envelope")
            _admit_blob_row(
                key_row,
                max_bytes=_ED25519_PUBLIC_KEY_BYTES,
                subject="Ed25519 public key",
                exact_bytes=_ED25519_PUBLIC_KEY_BYTES,
            )
            envelope = _collect_blob(connection, certificate, certificate_row)
            public_key = _collect_blob(connection, key_reference, key_row)
            _authenticate_archive_certificate(
                plot_id=plot_id,
                keyid=keyid,
                envelope=envelope,
                public_key_bytes=public_key,
                limits=limits,
            )
            result = envelope
        except ArchiveError:
            raise
        except sqlite3.Error as exc:
            msg = "SQLite failed during a bounded public-certificate read"
            raise ArchiveError(msg) from exc
        finally:
            connection.close()
        return result

    def read_spec(self, spec_id: str, *, max_bytes: int) -> bytes:
        """Read verified canonical spec bytes by their domain-separated public address."""
        _require_address(spec_id, subject="spec_id")
        _require_read_limit(max_bytes)
        connection = self._connect()
        result: bytes
        try:
            _validate_schema(connection, verify_accounting=False)
            record_row = connection.execute(_SELECT_SPEC_RECORD, (spec_id,)).fetchone()
            if record_row is None:
                msg = "archive canonical spec address was not found"
                raise ArchiveNotFoundError(msg)
            reference = _validated_spec_record(record_row, spec_id)
            blob_row = _blob_row(connection, reference)
            if blob_row is None:
                msg = "archive canonical spec relation is broken"
                raise ArchiveIntegrityError(msg)
            _admit_blob_row(blob_row, max_bytes=max_bytes, subject="canonical spec")
            payload = _collect_blob(connection, reference, blob_row)
            spec = _decode_canonical_spec(payload)
            if canon.hash_spec(spec) != f"sha256:{spec_id}":
                msg = "archive spec_id does not address the decoded canonical spec"
                raise ArchiveIntegrityError(msg)
            result = payload
        except ArchiveError:
            raise
        except sqlite3.Error as exc:
            msg = "SQLite failed during a bounded public-spec read"
            raise ArchiveError(msg) from exc
        finally:
            connection.close()
        return result

    def read_key(self, keyid: str, *, max_bytes: int) -> bytes:
        """Read one exact raw 32-byte Ed25519 public key under its canonical SHA-256 keyid."""
        _require_sha256(keyid, subject="keyid")
        _require_read_limit(max_bytes)
        connection = self._connect()
        result: bytes
        try:
            _validate_schema(connection, verify_accounting=False)
            record_row = connection.execute(_SELECT_KEY_RECORD, (keyid,)).fetchone()
            if record_row is None:
                msg = "archive public-key address was not found"
                raise ArchiveNotFoundError(msg)
            reference = _validated_key_record(record_row, keyid)
            blob_row = _blob_row(connection, reference)
            if blob_row is None:
                msg = "archive public-key relation is broken"
                raise ArchiveIntegrityError(msg)
            _admit_blob_row(
                blob_row,
                max_bytes=max_bytes,
                subject="Ed25519 public key",
                exact_bytes=_ED25519_PUBLIC_KEY_BYTES,
            )
            payload = _collect_blob(connection, reference, blob_row)
            try:
                Ed25519PublicKey.from_public_bytes(payload)
                actual_keyid = keyid_for_public_key(payload)
            except ValueError as exc:
                msg = "archive public-key bytes are not a raw Ed25519 public key"
                raise ArchiveIntegrityError(msg) from exc
            if actual_keyid != keyid:
                msg = "archive keyid does not address its raw public-key bytes"
                raise ArchiveIntegrityError(msg)
            result = payload
        except ArchiveError:
            raise
        except sqlite3.Error as exc:
            msg = "SQLite failed during a bounded public-key read"
            raise ArchiveError(msg) from exc
        finally:
            connection.close()
        return result

    def read_plot_envelope(self, plot_id: str, *, max_bytes: int) -> bytes:
        """Read + verify the VCert DSSE envelope whose SHA-256 is ``plot_id``."""
        _require_address(plot_id, subject="plot_id")
        expected = _ExpectedBlob(BlobKind.VCERT_ENVELOPE, f"sha256:{plot_id}", max_bytes)
        return self._read_payload(_SELECT_PLOT_ENVELOPE, (plot_id,), expected)

    def read_attempt_envelope(self, attempt_id: str, *, max_bytes: int) -> bytes:
        """Read + verify the attempt DSSE envelope whose SHA-256 is ``attempt_id``."""
        _require_address(attempt_id, subject="attempt_id")
        expected = _ExpectedBlob(BlobKind.ATTEMPT_ENVELOPE, f"sha256:{attempt_id}", max_bytes)
        return self._read_payload(_SELECT_ATTEMPT_ENVELOPE, (attempt_id,), expected)

    def read_plot_blob(self, plot_id: str, role: PlotRole, *, max_bytes: int) -> bytes:
        """Resolve one plot role and read only the byte kind fixed by that role."""
        _require_address(plot_id, subject="plot_id")
        role_object: object = role
        if not isinstance(role_object, PlotRole):
            msg = f"role must be a PlotRole, got {role!r}"
            raise TypeError(msg)
        expected = _ExpectedBlob(BlobKind(role.value), None, max_bytes)
        return self._read_payload(_SELECT_PLOT_REFERENCE, (plot_id, role.value), expected)

    def read_attempt_blob(self, attempt_id: str, role: AttemptRole, *, max_bytes: int) -> bytes:
        """Resolve one attempt role and read only the byte kind fixed by that role."""
        _require_address(attempt_id, subject="attempt_id")
        role_object: object = role
        if not isinstance(role_object, AttemptRole):
            msg = f"role must be an AttemptRole, got {role!r}"
            raise TypeError(msg)
        expected = _ExpectedBlob(BlobKind(role.value), None, max_bytes)
        return self._read_payload(
            _SELECT_ATTEMPT_REFERENCE,
            (attempt_id, role.value),
            expected,
        )

    def read_plot(
        self,
        plot_id: str,
        *,
        max_bytes: int,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> PlotBundle:
        """Read one complete plot under an aggregate cap, then revalidate its signed hash graph."""
        _require_address(plot_id, subject="plot_id")
        _require_read_limit(max_bytes)
        _require_limits(limits)
        connection = self._connect()
        try:
            bundle = _read_complete_plot_bundle(connection, plot_id, max_bytes=max_bytes)
            _validate_plot_bundle(bundle, limits)
        except ArchiveError:
            raise
        except sqlite3.Error as exc:
            msg = "SQLite failed while reading a complete plot bundle"
            raise ArchiveError(msg) from exc
        else:
            return bundle
        finally:
            connection.close()

    def lowest_verified_attempt_id(self, plot_id: str) -> str | None:
        """Return the lexicographically lowest signed verified attempt for one plot."""
        _require_address(plot_id, subject="plot_id")
        connection = self._connect()
        result: str | None
        try:
            _validate_schema(connection, verify_accounting=False)
            row = connection.execute(_SELECT_LOWEST_PLOT_ATTEMPT, (plot_id,)).fetchone()
            result = None if row is None else _validated_lowest_attempt_id(row)
        except ArchiveError:
            raise
        except sqlite3.Error as exc:
            msg = "SQLite failed while selecting the lowest verified plot attempt"
            raise ArchiveError(msg) from exc
        finally:
            connection.close()
        return result

    def read_attempt(
        self,
        attempt_id: str,
        *,
        max_bytes: int,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> AttemptBundle:
        """Read one complete occurrence under an aggregate cap, then verify all signed bindings."""
        _require_address(attempt_id, subject="attempt_id")
        _require_read_limit(max_bytes)
        _require_limits(limits)
        connection = self._connect()
        try:
            bundle = _read_complete_attempt_bundle(
                connection,
                attempt_id,
                max_bytes=max_bytes,
                limits=limits,
            )
        except ArchiveError:
            raise
        except sqlite3.Error as exc:
            msg = "SQLite failed while reading a complete attempt bundle"
            raise ArchiveError(msg) from exc
        else:
            return bundle
        finally:
            connection.close()

    def stats(self) -> ArchiveStats:
        """Return checked logical accounting + row counts from one fresh connection."""
        connection = self._connect()
        try:
            logical_bytes = _validate_schema(connection, verify_accounting=True)
            counts = tuple(
                _read_scalar(connection, statement)
                for statement in (
                    "SELECT COUNT(*) FROM blobs",
                    "SELECT COUNT(*) FROM keys",
                    "SELECT COUNT(*) FROM plots",
                    "SELECT COUNT(*) FROM attempts",
                )
            )
            if any(type(value) is not int or value < 0 for value in counts):
                msg = "archive row counts are malformed"
                raise ArchiveIntegrityError(msg)
            return ArchiveStats(logical_bytes, *cast("tuple[int, int, int, int]", counts))
        except ArchiveError:
            raise
        except sqlite3.Error as exc:
            msg = "SQLite failed while reading archive statistics"
            raise ArchiveError(msg) from exc
        finally:
            connection.close()


def open_archive(settings: Settings) -> Archive:
    """Initialize/reopen the service archive from one validated operator snapshot."""
    settings_object: object = settings
    if not isinstance(settings_object, Settings):
        msg = "settings must be a validated service Settings instance"
        raise TypeError(msg)
    return Archive(
        settings.state_dir,
        max_logical_bytes=settings.max_archive_bytes,
        max_spec_bytes=settings.max_body_bytes + settings.max_model_response_bytes,
    )
