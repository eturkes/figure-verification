# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Transactional, content-addressed provenance storage.

The archive is an append-only SQLite substrate for later plot/attempt bundle units. One
``BEGIN IMMEDIATE`` transaction publishes every blob, key, plot, attempt, and typed reference in a
batch. Blob payload bytes are SHA-256-addressed within a closed kind and deduplicated by
``(digest, kind)``; identical bytes may legitimately carry multiple observed roles and each typed
payload counts toward quota once. A trigger maintains the tracked logical-payload total. The
configured quota gates new typed bytes while the writer lock is held, before inserts, and never
evicts history. It intentionally excludes SQLite pages, row/index metadata, rollback journals, and
filesystem overhead. Startup and operator statistics reconcile the counter against all blob
metadata; per-bundle admission remains O(schema-size + bundle-size), not O(archive-history).

Every operation owns a fresh connection. Each connection forces + verifies rollback-journal
``DELETE` mode, ``FULL`` synchronous writes, foreign keys, defensive mode, trusted-schema off, and
a finite busy timeout. The database lives as a 0600 regular file under the service's 0700
owner-private state directory. Startup transactionally creates or exact-matches one versioned
STRICT schema; unknown/unversioned non-empty schemas fail closed.

Reads first validate the requested role/kind and stored digest/kind/size metadata, then enforce the
caller's byte limit before opening the BLOB. ``sqlite3.Blob`` is consumed in fixed chunks while its
SHA-256 digest is recomputed; neither a metadata lie nor corruption can become trusted payload.
Application values use SQL parameters exclusively; the only literal SQL is fixed schema/PRAGMA
text owned by this module.
"""

import hashlib
import os
import re
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import cast

from verifier.service.identity import (
    IdentityError,
    open_state_directory,
    validate_state_metadata,
)
from verifier.service.settings import Settings

__all__ = [
    "Archive",
    "ArchiveBatch",
    "ArchiveError",
    "ArchiveIntegrityError",
    "ArchiveNotFoundError",
    "ArchiveQuotaError",
    "ArchiveReadLimitError",
    "ArchiveSchemaError",
    "ArchiveStats",
    "AttemptRecord",
    "AttemptReference",
    "AttemptRole",
    "BlobKind",
    "BlobRef",
    "BlobWrite",
    "KeyRecord",
    "PlotRecord",
    "PlotReference",
    "PlotRole",
    "open_archive",
]

_SCHEMA_VERSION = 1
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
_FULL_SYNCHRONOUS = 2
_META_COLUMNS = 2
_BLOB_METADATA_COLUMNS = 4
_DATABASE_MODE = 0o600
_STATE_DIRECTORY_MODE = 0o700
_CONNECTION_FACTORY: type[sqlite3.Connection] = sqlite3.Connection


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

_SCHEMA_OBJECTS = (
    ("table", "meta", "meta", _CREATE_META),
    ("table", "blobs", "blobs", _CREATE_BLOBS),
    ("table", "keys", "keys", _CREATE_KEYS),
    ("table", "plots", "plots", _CREATE_PLOTS),
    ("table", "attempts", "attempts", _CREATE_ATTEMPTS),
    ("table", "plot_references", "plot_references", _CREATE_PLOT_REFERENCES),
    ("table", "attempt_references", "attempt_references", _CREATE_ATTEMPT_REFERENCES),
    ("trigger", "blobs_track_logical_bytes", "blobs", _CREATE_BLOB_ACCOUNTING),
    ("trigger", "blobs_reject_update", "blobs", _CREATE_BLOB_UPDATE_GUARD),
    ("trigger", "blobs_reject_delete", "blobs", _CREATE_BLOB_DELETE_GUARD),
)

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
_SELECT_PLOT_ENVELOPE = """SELECT b.blob_id, b.digest, b.kind, b.size
FROM plots AS p
JOIN blobs AS b ON b.digest = p.certificate_digest AND b.kind = p.certificate_kind
WHERE p.plot_id = ?"""
_SELECT_ATTEMPT_ENVELOPE = """SELECT b.blob_id, b.digest, b.kind, b.size
FROM attempts AS a
JOIN blobs AS b ON b.digest = a.envelope_digest AND b.kind = a.envelope_kind
WHERE a.attempt_id = ?"""


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
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.execute("PRAGMA busy_timeout=5000")

    _require_connection_setting(
        "journal_mode", _read_scalar(connection, "PRAGMA journal_mode"), "delete"
    )
    _require_connection_setting(
        "synchronous", _read_scalar(connection, "PRAGMA synchronous"), _FULL_SYNCHRONOUS
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
        WHERE name NOT LIKE ? AND sql IS NOT NULL
        ORDER BY type, name""",
        ("sqlite_%",),
    ).fetchall()
    return tuple(tuple(row) for row in rows)


def _validate_schema(connection: sqlite3.Connection, *, verify_accounting: bool) -> int:
    user_version = _read_scalar(connection, "PRAGMA user_version")
    if type(user_version) is not int or user_version != _SCHEMA_VERSION:
        msg = f"archive schema version must be {_SCHEMA_VERSION}; found {user_version!r}"
        raise ArchiveSchemaError(msg)

    expected_schema = tuple(sorted(_SCHEMA_OBJECTS, key=lambda row: (row[0], row[1])))
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
        or row[0] != _SCHEMA_VERSION
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


def _create_or_validate_schema(connection: sqlite3.Connection) -> None:
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
            connection.execute("PRAGMA user_version=1")
        _validate_schema(connection, verify_accounting=True)


def _validate_database_file(descriptor: int, state_descriptor: int) -> None:
    validate_state_metadata(
        os.fstat(descriptor), subject="archive database", expect_directory=False
    )
    database_mode = stat.S_IMODE(os.fstat(descriptor).st_mode)
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


def _require_batch_items(batch: ArchiveBatch) -> None:
    fields: tuple[tuple[object, type[object], str], ...] = (
        (batch.blobs, BlobWrite, "blobs"),
        (batch.keys, KeyRecord, "keys"),
        (batch.plots, PlotRecord, "plots"),
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


class Archive:
    """Versioned SQLite archive; construction initializes and validates durable state."""

    __slots__ = ("_database_path", "_max_logical_bytes", "_state_dir")

    def __init__(self, state_dir: Path, *, max_logical_bytes: int) -> None:
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
        self._state_dir = state_dir
        self._database_path = state_dir / _DATABASE_NAME
        self._max_logical_bytes = max_logical_bytes
        connection = self._connect()
        try:
            _create_or_validate_schema(connection)
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

    def read_key(self, keyid: str, *, max_bytes: int) -> bytes:
        """Read + verify one preserved raw Ed25519 public-key blob."""
        _require_sha256(keyid, subject="keyid")
        expected = _ExpectedBlob(BlobKind.ED25519_PUBLIC_KEY, keyid, max_bytes)
        return self._read_payload(_SELECT_KEY_BLOB, (keyid,), expected)

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
    return Archive(settings.state_dir, max_logical_bytes=settings.max_archive_bytes)
