# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Transactional SQLite archive, typed references, quotas, and corruption gates."""

import os
import sqlite3
import stat
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import pytest

from schema_downgrade import downgrade_to_v3
from verifier.service import archive as archive_module
from verifier.service.app import create_app
from verifier.service.archive import (
    Archive,
    ArchiveBatch,
    ArchiveError,
    ArchiveIntegrityError,
    ArchiveNotFoundError,
    ArchiveQuotaError,
    ArchiveReadLimitError,
    ArchiveSchemaError,
    AttemptRecord,
    AttemptReference,
    AttemptRole,
    BlobKind,
    BlobRef,
    BlobWrite,
    KeyRecord,
    PlotRecord,
    PlotReference,
    PlotRole,
    PlotSourceKind,
    SpecRecord,
    open_archive,
)
from verifier.service.settings import Settings

_MAX_SQLITE_INTEGER = 2**63 - 1
_PUBLIC_KEY_BYTES = b"K" * 32
_BOOL_AS_INT = cast("int", bool(1))


def _settings(tmp_path: Path, *, quota: int = 1_024 * 1_024) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        state_dir=tmp_path / "state",
        max_archive_bytes=quota,
    )


def _archive(tmp_path: Path, *, quota: int = 1_024 * 1_024) -> Archive:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return open_archive(_settings(tmp_path, quota=quota))


def _address(blob: BlobWrite) -> str:
    return blob.ref.digest.removeprefix("sha256:")


def _complete_batch() -> tuple[ArchiveBatch, dict[str, BlobWrite]]:
    blobs = {
        "key": BlobWrite(BlobKind.ED25519_PUBLIC_KEY, _PUBLIC_KEY_BYTES),
        "certificate": BlobWrite(BlobKind.VCERT_ENVELOPE, b"signed-vcert-envelope"),
        "attempt": BlobWrite(BlobKind.ATTEMPT_ENVELOPE, b"signed-attempt-envelope"),
        "csv": BlobWrite(BlobKind.RAW_CSV, b"month,revenue\nJan,10\n"),
        "manifest": BlobWrite(BlobKind.RAW_MANIFEST, b'{"dataset":"sales"}'),
        "spec": BlobWrite(BlobKind.CANONICAL_SPEC, b'{"vplot":"canonical"}'),
        "raw_spec": BlobWrite(BlobKind.RAW_SPEC, b"```json\n{}\n```"),
        "verdict": BlobWrite(BlobKind.VERDICT, b'{"verified":true}'),
        "table": BlobWrite(BlobKind.PLOTTED_TABLE, b'[["Jan","10"]]'),
        "vega": BlobWrite(BlobKind.VEGA_LITE, b'{"mark":"bar"}'),
        "svg": BlobWrite(BlobKind.SVG, b"<svg></svg>"),
        "vcert_payload": BlobWrite(BlobKind.VCERT_PAYLOAD, b'{"certificate":"v0.2"}'),
        "versions": BlobWrite(BlobKind.TOOL_VERSIONS, b'{"verifier":"0.2.0"}'),
        "model_request": BlobWrite(BlobKind.MODEL_REQUEST, b'{"messages":[]}'),
        "model_response": BlobWrite(BlobKind.MODEL_RESPONSE, b'{"choices":[]}'),
        "model_reply": BlobWrite(BlobKind.MODEL_REPLY, b"{}"),
        "attempt_payload": BlobWrite(BlobKind.ATTEMPT_PAYLOAD, b'{"attempt":"v0.1"}'),
    }
    keyid = blobs["key"].ref.digest
    plot_id = _address(blobs["certificate"])
    attempt_id = _address(blobs["attempt"])
    batch = ArchiveBatch(
        blobs=tuple(blobs.values()),
        keys=(KeyRecord(keyid, blobs["key"].ref),),
        plots=(PlotRecord(plot_id, blobs["certificate"].ref, keyid, PlotSourceKind.DATASET),),
        attempts=(AttemptRecord(attempt_id, blobs["attempt"].ref, keyid, plot_id),),
        plot_references=(
            PlotReference(plot_id, PlotRole.RAW_CSV, blobs["csv"].ref),
            PlotReference(plot_id, PlotRole.RAW_MANIFEST, blobs["manifest"].ref),
            PlotReference(plot_id, PlotRole.CANONICAL_SPEC, blobs["spec"].ref),
            PlotReference(plot_id, PlotRole.PLOTTED_TABLE, blobs["table"].ref),
            PlotReference(plot_id, PlotRole.VERDICT, blobs["verdict"].ref),
            PlotReference(plot_id, PlotRole.VEGA_LITE, blobs["vega"].ref),
            PlotReference(plot_id, PlotRole.SVG, blobs["svg"].ref),
            PlotReference(plot_id, PlotRole.VCERT_PAYLOAD, blobs["vcert_payload"].ref),
            PlotReference(plot_id, PlotRole.TOOL_VERSIONS, blobs["versions"].ref),
        ),
        attempt_references=(
            AttemptReference(attempt_id, AttemptRole.RAW_CSV, blobs["csv"].ref),
            AttemptReference(attempt_id, AttemptRole.RAW_MANIFEST, blobs["manifest"].ref),
            AttemptReference(attempt_id, AttemptRole.RAW_SPEC, blobs["raw_spec"].ref),
            AttemptReference(attempt_id, AttemptRole.VERDICT, blobs["verdict"].ref),
            AttemptReference(attempt_id, AttemptRole.MODEL_REQUEST, blobs["model_request"].ref),
            AttemptReference(attempt_id, AttemptRole.MODEL_RESPONSE, blobs["model_response"].ref),
            AttemptReference(attempt_id, AttemptRole.MODEL_REPLY, blobs["model_reply"].ref),
            AttemptReference(attempt_id, AttemptRole.ATTEMPT_PAYLOAD, blobs["attempt_payload"].ref),
        ),
    )
    return batch, blobs


@contextmanager
def _database_connection(archive: Archive) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(archive.database_path, autocommit=True)
    try:
        yield connection
    finally:
        connection.close()


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)


def test_create_reopen_uses_exact_strict_schema_and_connection_profile(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    archive = open_archive(settings)
    assert archive.database_path == settings.state_dir / "archive.sqlite3"
    assert archive.max_logical_bytes == settings.max_archive_bytes
    assert (_mode(settings.state_dir), _mode(archive.database_path)) == (0o700, 0o600)
    assert archive.stats() == archive_module.ArchiveStats(0, 0, 0, 0, 0)

    connection = archive._connect()
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert connection.execute("PRAGMA synchronous").fetchone() == (3,)
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert connection.execute("PRAGMA trusted_schema").fetchone() == (0,)
        assert connection.execute("PRAGMA busy_timeout").fetchone() == (5_000,)
        assert connection.getconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE)
        assert not connection.getconfig(sqlite3.SQLITE_DBCONFIG_TRUSTED_SCHEMA)
        assert connection.getconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_FKEY)
        table_rows = connection.execute("PRAGMA table_list").fetchall()
        assert connection.execute("PRAGMA user_version").fetchone() == (4,)
        assert connection.execute(
            "SELECT schema_version FROM meta WHERE singleton = 1"
        ).fetchone() == (4,)
        assert archive_module._schema_rows(connection) == tuple(
            sorted(archive_module._SCHEMA_OBJECTS, key=lambda row: (row[0], row[1]))
        )
        assert connection.execute(
            "SELECT sql FROM sqlite_schema WHERE name = ?", ("attempts_by_plot",)
        ).fetchone() == (archive_module._CREATE_ATTEMPTS_BY_PLOT,)
    finally:
        connection.close()
    expected_tables = {
        "meta",
        "blobs",
        "keys",
        "plots",
        "specs",
        "attempts",
        "plot_references",
        "attempt_references",
    }
    strict_by_name = {
        cast("str", row[1]): cast("int", row[5]) for row in table_rows if row[1] in expected_tables
    }
    assert strict_by_name == dict.fromkeys(expected_tables, 1)

    reopened = open_archive(settings)
    assert reopened.database_path == archive.database_path
    assert reopened.stats() == archive.stats()


def test_version_two_archive_migrates_partial_attempt_index_atomically(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    with _database_connection(archive) as connection:
        downgrade_to_v3(connection)
        connection.execute("DROP INDEX attempts_by_plot")
        connection.execute("UPDATE meta SET schema_version = 2 WHERE singleton = 1")
        connection.execute("PRAGMA user_version=2")

    reopened = _archive(tmp_path)
    with _database_connection(reopened) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (4,)
        assert connection.execute(
            "SELECT schema_version FROM meta WHERE singleton = 1"
        ).fetchone() == (4,)
        assert connection.execute(
            "SELECT sql FROM sqlite_schema WHERE name = ?", ("attempts_by_plot",)
        ).fetchone() == (archive_module._CREATE_ATTEMPTS_BY_PLOT,)


def test_app_initializes_archive_and_rejects_schema_version_drift_at_startup(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    app = create_app(settings)
    archive = cast("Archive", app.state["archive"])
    with _database_connection(archive) as connection:
        connection.execute("PRAGMA user_version=99")
    with pytest.raises(ArchiveSchemaError, match="schema version"):
        create_app(settings)


def test_schema_validation_detects_like_wildcard_alias_object(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    archive = open_archive(settings)
    with _database_connection(archive) as connection:
        connection.execute("CREATE INDEX sqliteXevil ON blobs(size)")

    with pytest.raises(ArchiveSchemaError, match="exact versioned STRICT schema"):
        open_archive(settings)


def test_complete_batch_round_trips_every_relation_and_typed_read(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    batch, blobs = _complete_batch()
    archive.publish(batch)
    archive.publish(batch)  # every immutable row's byte-identical idempotent path

    expected_bytes = sum(len(blob.payload) for blob in blobs.values())
    assert archive.stats() == archive_module.ArchiveStats(expected_bytes, len(blobs), 1, 1, 1)
    plot_id = batch.plots[0].plot_id
    attempt_id = batch.attempts[0].attempt_id
    keyid = batch.keys[0].keyid
    assert archive.read_key(keyid, max_bytes=32) == _PUBLIC_KEY_BYTES
    assert archive.read_plot_envelope(plot_id, max_bytes=1_000) == blobs["certificate"].payload
    assert archive.read_attempt_envelope(attempt_id, max_bytes=1_000) == blobs["attempt"].payload
    assert (
        archive.read_plot_blob(plot_id, PlotRole.RAW_CSV, max_bytes=1_000) == blobs["csv"].payload
    )
    assert (
        archive.read_attempt_blob(attempt_id, AttemptRole.RAW_CSV, max_bytes=1_000)
        == blobs["csv"].payload
    )
    assert archive.read_blob(blobs["svg"].ref, max_bytes=1_000) == b"<svg></svg>"

    reopened = _archive(tmp_path)
    assert (
        reopened.read_plot_blob(plot_id, PlotRole.VEGA_LITE, max_bytes=1_000) == b'{"mark":"bar"}'
    )
    with _database_connection(reopened) as connection:
        assert connection.execute("SELECT COUNT(*) FROM plot_references").fetchone() == (9,)
        assert connection.execute("SELECT COUNT(*) FROM attempt_references").fetchone() == (8,)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_lowest_verified_attempt_id_is_indexed_bounded_and_corruption_safe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = _archive(tmp_path)
    batch, _blobs = _complete_batch()
    archive.publish(batch)
    plot_id = batch.plots[0].plot_id
    keyid = batch.keys[0].keyid

    extra_envelopes = tuple(
        BlobWrite(BlobKind.ATTEMPT_ENVELOPE, payload)
        for payload in (b"second signed attempt", b"third signed attempt")
    )
    plotless_envelope = BlobWrite(BlobKind.ATTEMPT_ENVELOPE, b"plotless signed attempt")
    extra_attempts = tuple(
        AttemptRecord(_address(envelope), envelope.ref, keyid, plot_id)
        for envelope in extra_envelopes
    )
    plotless_attempt = AttemptRecord(
        _address(plotless_envelope),
        plotless_envelope.ref,
        keyid,
    )
    archive.publish(
        ArchiveBatch(
            blobs=(*extra_envelopes, plotless_envelope),
            attempts=(*extra_attempts, plotless_attempt),
        )
    )

    expected = min(batch.attempts[0].attempt_id, *(item.attempt_id for item in extra_attempts))
    assert archive.lowest_verified_attempt_id(plot_id) == expected
    with _database_connection(archive) as connection:
        plan = connection.execute(
            "EXPLAIN QUERY PLAN " + archive_module._SELECT_LOWEST_PLOT_ATTEMPT,
            (plot_id,),
        ).fetchall()
    assert any("USING COVERING INDEX attempts_by_plot" in cast("str", row[3]) for row in plan)
    absent_plot_id = "0" * 64 if plot_id != "0" * 64 else "1" * 64
    assert archive.lowest_verified_attempt_id(absent_plot_id) is None
    with pytest.raises(ValueError, match="64 lowercase"):
        archive.lowest_verified_attempt_id(cast("str", 1))
    with pytest.raises(ValueError, match="64 lowercase"):
        archive.lowest_verified_attempt_id("bad")

    valid_row = ("a" * 64,)
    assert archive_module._validated_lowest_attempt_id(valid_row) == valid_row[0]
    malformed_rows: tuple[object, ...] = (None, [], (), ("a" * 64, "b" * 64))
    for malformed_row in malformed_rows:
        with pytest.raises(ArchiveIntegrityError, match="row is malformed"):
            archive_module._validated_lowest_attempt_id(malformed_row)
    for corrupt_row in ((1,), ("bad",)):
        with pytest.raises(ArchiveIntegrityError, match="address is corrupt"):
            archive_module._validated_lowest_attempt_id(corrupt_row)

    with _database_connection(archive) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute(
            "UPDATE attempts SET attempt_id = ? WHERE attempt_id = ?", ("!", expected)
        )
    with pytest.raises(ArchiveIntegrityError, match="address is corrupt"):
        archive.lowest_verified_attempt_id(plot_id)

    monkeypatch.setattr(
        archive_module,
        "_SELECT_LOWEST_PLOT_ATTEMPT",
        "SELECT absent_column FROM attempts",
    )
    with pytest.raises(ArchiveError, match="selecting the lowest verified"):
        archive.lowest_verified_attempt_id(plot_id)


def test_blob_dedup_is_typed_idempotent_and_cross_kind_equal_bytes_are_representable(
    tmp_path: Path,
) -> None:
    archive = _archive(tmp_path)
    blob = BlobWrite(BlobKind.RAW_CSV, b"same bytes")
    duplicate_batch = ArchiveBatch(blobs=(blob, blob))
    archive.publish(duplicate_batch)
    archive.publish(duplicate_batch)
    assert archive.stats() == archive_module.ArchiveStats(len(blob.payload), 1, 0, 0, 0)

    conflicting_kind = BlobWrite(BlobKind.RAW_MANIFEST, blob.payload)
    archive.publish(ArchiveBatch(blobs=(conflicting_kind,)))
    assert archive.read_blob(blob.ref, max_bytes=100) == blob.payload
    assert archive.read_blob(conflicting_kind.ref, max_bytes=100) == blob.payload
    assert archive.stats() == archive_module.ArchiveStats(2 * len(blob.payload), 2, 0, 0, 0)

    # The load-bearing future case: proposer extraction passes the model reply bytes verbatim to
    # spec decode, so one byte string can truthfully be observed under both roles.
    raw_spec = BlobWrite(BlobKind.RAW_SPEC, b'{"same":"candidate"}')
    model_reply = BlobWrite(BlobKind.MODEL_REPLY, raw_spec.payload)
    archive.publish(ArchiveBatch(blobs=(raw_spec, model_reply)))
    assert archive.read_blob(raw_spec.ref, max_bytes=100) == model_reply.payload
    assert archive.read_blob(model_reply.ref, max_bytes=100) == raw_spec.payload


def test_quota_exact_boundary_then_refuses_without_eviction_or_mutation(tmp_path: Path) -> None:
    archive = _archive(tmp_path, quota=3)
    exact = BlobWrite(BlobKind.RAW_CSV, b"abc")
    archive.publish(ArchiveBatch(blobs=(exact,)))
    assert archive.stats().logical_blob_bytes == 3

    over = BlobWrite(BlobKind.RAW_MANIFEST, b"d")
    with pytest.raises(ArchiveQuotaError, match=r"3 stored \+ 1 new"):
        archive.publish(ArchiveBatch(blobs=(over,)))
    assert archive.stats() == archive_module.ArchiveStats(3, 1, 0, 0, 0)
    assert archive.read_blob(exact.ref, max_bytes=3) == b"abc"
    with pytest.raises(ArchiveNotFoundError):
        archive.read_blob(over.ref, max_bytes=1)

    lowered = _archive(tmp_path, quota=2)
    lowered.publish(ArchiveBatch(blobs=(exact,)))  # zero new bytes remains idempotent
    with pytest.raises(ArchiveQuotaError, match=r"3 stored \+ 1 new"):
        lowered.publish(ArchiveBatch(blobs=(over,)))


def test_concurrent_writers_serialize_quota_check_without_race(tmp_path: Path) -> None:
    archive = _archive(tmp_path, quota=1)
    barrier = threading.Barrier(2)
    blobs = (
        BlobWrite(BlobKind.RAW_CSV, b"a"),
        BlobWrite(BlobKind.RAW_MANIFEST, b"b"),
    )

    def publish(blob: BlobWrite) -> str:
        barrier.wait()
        try:
            archive.publish(ArchiveBatch(blobs=(blob,)))
        except ArchiveQuotaError:
            return "quota"
        return "published"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(publish, blobs))
    assert sorted(results) == ["published", "quota"]
    assert archive.stats() == archive_module.ArchiveStats(1, 1, 0, 0, 0)


def test_concurrent_unique_writers_all_commit_without_lost_accounting(tmp_path: Path) -> None:
    payloads = tuple(f"payload-{index}".encode() for index in range(12))
    archive = _archive(tmp_path, quota=sum(map(len, payloads)))
    barrier = threading.Barrier(len(payloads))

    def publish(payload: bytes) -> None:
        barrier.wait()
        archive.publish(ArchiveBatch(blobs=(BlobWrite(BlobKind.RAW_CSV, payload),)))

    with ThreadPoolExecutor(max_workers=len(payloads)) as pool:
        tuple(pool.map(publish, payloads))
    assert archive.stats() == archive_module.ArchiveStats(
        sum(map(len, payloads)), len(payloads), 0, 0, 0
    )


def test_injected_fault_rolls_back_all_rows_and_trigger_accounting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = _archive(tmp_path)
    batch, _blobs = _complete_batch()

    class InjectedError(Exception):
        pass

    def fail() -> None:
        raise InjectedError

    monkeypatch.setattr(archive_module, "_before_archive_commit", fail)
    with pytest.raises(InjectedError):
        archive.publish(batch)
    assert archive.stats() == archive_module.ArchiveStats(0, 0, 0, 0, 0)


def test_foreign_key_failure_rolls_back_preceding_blob_and_accounting(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    certificate = BlobWrite(BlobKind.VCERT_ENVELOPE, b"certificate")
    absent_keyid = "sha256:" + "a" * 64
    plot = PlotRecord(_address(certificate), certificate.ref, absent_keyid, PlotSourceKind.DATASET)
    with pytest.raises(ArchiveIntegrityError, match="typed reference"):
        archive.publish(ArchiveBatch(blobs=(certificate,), plots=(plot,)))
    assert archive.stats() == archive_module.ArchiveStats(0, 0, 0, 0, 0)


def test_conflicting_immutable_record_rolls_back_new_key_and_blob(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    batch, blobs = _complete_batch()
    archive.publish(batch)
    before = archive.stats()

    second_key = BlobWrite(BlobKind.ED25519_PUBLIC_KEY, b"R" * 32)
    conflicting_plot = PlotRecord(
        batch.plots[0].plot_id,
        blobs["certificate"].ref,
        second_key.ref.digest,
        PlotSourceKind.DATASET,
    )
    with pytest.raises(ArchiveIntegrityError, match="immutable plot"):
        archive.publish(
            ArchiveBatch(
                blobs=(second_key,),
                keys=(KeyRecord(second_key.ref.digest, second_key.ref),),
                plots=(conflicting_plot,),
            )
        )
    assert archive.stats() == before
    with pytest.raises(ArchiveNotFoundError):
        archive.read_key(second_key.ref.digest, max_bytes=32)


def test_bounded_multichunk_read_opens_blob_only_after_metadata_admission(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = _archive(tmp_path)
    payload = b"x" * (64 * 1024 + 3)
    blob = BlobWrite(BlobKind.RAW_CSV, payload)
    archive.publish(ArchiveBatch(blobs=(blob,)))

    class TrackingConnection(sqlite3.Connection):
        blob_opens = 0

        def blobopen(self, *args: Any, **kwargs: Any) -> sqlite3.Blob:
            type(self).blob_opens += 1
            return super().blobopen(*args, **kwargs)

    monkeypatch.setattr(archive_module, "_CONNECTION_FACTORY", TrackingConnection)
    with pytest.raises(ArchiveReadLimitError, match="read limit"):
        archive.read_blob(blob.ref, max_bytes=len(payload) - 1)
    assert TrackingConnection.blob_opens == 0
    assert archive.read_blob(blob.ref, max_bytes=len(payload)) == payload
    assert TrackingConnection.blob_opens == 1


def test_blob_triggers_reject_mutation_then_stream_read_detects_content_corruption(
    tmp_path: Path,
) -> None:
    archive = _archive(tmp_path)
    blob = BlobWrite(BlobKind.RAW_CSV, b"trusted")
    archive.publish(ArchiveBatch(blobs=(blob,)))
    with _database_connection(archive) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE blobs SET content = ? WHERE digest = ?", (b"hostile", blob.ref.digest)
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM blobs WHERE digest = ?", (blob.ref.digest,))
        connection.execute("DROP TRIGGER blobs_reject_update")
        connection.execute(
            "UPDATE blobs SET content = ? WHERE digest = ?", (b"hostile", blob.ref.digest)
        )

    with pytest.raises(ArchiveIntegrityError, match="digest verification"):
        archive.read_blob(blob.ref, max_bytes=len(blob.payload))


def test_wrong_stored_kind_fails_before_payload_read(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    blob = BlobWrite(BlobKind.RAW_CSV, b"trusted")
    archive.publish(ArchiveBatch(blobs=(blob,)))
    with _database_connection(archive) as connection:
        connection.execute("DROP TRIGGER blobs_reject_update")
        connection.execute(
            "UPDATE blobs SET kind = ? WHERE digest = ?",
            (BlobKind.RAW_MANIFEST.value, blob.ref.digest),
        )
    with pytest.raises(ArchiveIntegrityError, match="expected kind"):
        archive.read_blob(blob.ref, max_bytes=len(blob.payload))


def test_unknown_schema_version_shape_meta_and_unversioned_database_fail_closed(
    tmp_path: Path,
) -> None:
    versioned = _archive(tmp_path / "versioned")
    with _database_connection(versioned) as connection:
        connection.execute("PRAGMA user_version=5")
    with pytest.raises(ArchiveSchemaError, match="schema version"):
        _archive(tmp_path / "versioned")

    shape = _archive(tmp_path / "shape")
    with _database_connection(shape) as connection:
        connection.execute("DROP TRIGGER blobs_reject_delete")
    with pytest.raises(ArchiveSchemaError, match="schema objects"):
        _archive(tmp_path / "shape")

    missing_index = _archive(tmp_path / "missing-index")
    with _database_connection(missing_index) as connection:
        connection.execute("DROP INDEX attempts_by_plot")
    with pytest.raises(ArchiveSchemaError, match="schema objects"):
        missing_index.lowest_verified_attempt_id("a" * 64)
    with pytest.raises(ArchiveSchemaError, match="schema objects"):
        _archive(tmp_path / "missing-index")

    extra_index = _archive(tmp_path / "extra-index")
    with _database_connection(extra_index) as connection:
        connection.execute("CREATE INDEX attempts_extra ON attempts(keyid)")
    with pytest.raises(ArchiveSchemaError, match="schema objects"):
        _archive(tmp_path / "extra-index")

    meta = _archive(tmp_path / "meta")
    with _database_connection(meta) as connection:
        connection.execute("UPDATE meta SET schema_version = 5 WHERE singleton = 1")
    with pytest.raises(ArchiveSchemaError, match="meta row"):
        _archive(tmp_path / "meta")

    unknown_settings = _settings(tmp_path / "unknown")
    unknown_settings.state_dir.mkdir(mode=0o700, parents=True)
    unknown_database = unknown_settings.state_dir / "archive.sqlite3"
    connection = sqlite3.connect(unknown_database, autocommit=True)
    try:
        connection.execute("CREATE TABLE alien(value TEXT)")
    finally:
        connection.close()
    unknown_database.chmod(0o600)
    with pytest.raises(ArchiveSchemaError, match="unversioned non-empty"):
        open_archive(unknown_settings)


def test_logical_accounting_corruption_fails_reopen_and_stats(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    blob = BlobWrite(BlobKind.RAW_CSV, b"abc")
    archive.publish(ArchiveBatch(blobs=(blob,)))
    with _database_connection(archive) as connection:
        connection.execute("UPDATE meta SET logical_blob_bytes = 2 WHERE singleton = 1")
    with pytest.raises(ArchiveIntegrityError, match="logical-byte accounting"):
        archive.stats()
    with pytest.raises(ArchiveIntegrityError, match="logical-byte accounting"):
        _archive(tmp_path)


def test_database_and_state_path_security_rejects_unsafe_final_entries(tmp_path: Path) -> None:
    wrong_db_mode = _archive(tmp_path / "mode")
    wrong_db_mode.database_path.chmod(0o640)
    with pytest.raises(ArchiveError, match=r"archive database|secure provenance"):
        _archive(tmp_path / "mode")

    unsafe_state = _settings(tmp_path / "state-mode")
    unsafe_state.state_dir.mkdir(mode=0o750, parents=True)
    with pytest.raises(ArchiveError, match="secure provenance"):
        open_archive(unsafe_state)

    symlink_settings = _settings(tmp_path / "symlink")
    symlink_settings.state_dir.mkdir(mode=0o700, parents=True)
    target = tmp_path / "target.sqlite3"
    target.touch(mode=0o600)
    (symlink_settings.state_dir / "archive.sqlite3").symlink_to(target)
    with pytest.raises(ArchiveError, match="secure provenance"):
        open_archive(symlink_settings)

    directory_settings = _settings(tmp_path / "directory")
    directory_settings.state_dir.mkdir(mode=0o700, parents=True)
    (directory_settings.state_dir / "archive.sqlite3").mkdir(mode=0o700)
    with pytest.raises(ArchiveError, match="secure provenance"):
        open_archive(directory_settings)


def test_archive_database_rejects_hard_linked_inode(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    alias = tmp_path / "archive-alias.sqlite3"
    os.link(archive.database_path, alias)
    assert archive.database_path.stat().st_nlink == 2

    with pytest.raises(ArchiveError, match="exactly one hard link"):
        _archive(tmp_path)


def test_constructor_and_wire_record_runtime_validation(tmp_path: Path) -> None:
    absolute = tmp_path.resolve()
    for state in (Path("relative"), cast("Path", "not-a-path")):
        with pytest.raises(ValueError, match="absolute Path"):
            Archive(state, max_logical_bytes=1, max_spec_bytes=1)
    for bad in (0, -1, _BOOL_AS_INT, cast("int", 1.5), 2**63):
        with pytest.raises(ValueError, match="max_logical_bytes"):
            Archive(absolute, max_logical_bytes=bad, max_spec_bytes=1)
    with pytest.raises(TypeError, match="validated service Settings"):
        open_archive(cast("Settings", object()))

    for digest in ("", "sha256:" + "A" * 64, "a" * 64, cast("str", 7)):
        with pytest.raises(ValueError, match="blob digest"):
            BlobRef(digest, BlobKind.RAW_CSV)
    with pytest.raises(TypeError, match="blob kind"):
        BlobRef("sha256:" + "a" * 64, cast("BlobKind", "raw_csv"))
    with pytest.raises(TypeError, match="blob kind"):
        BlobWrite(cast("BlobKind", "raw_csv"), b"x")
    with pytest.raises(TypeError, match="payload must be bytes"):
        BlobWrite(BlobKind.RAW_CSV, cast("bytes", "x"))

    key_blob = BlobWrite(BlobKind.ED25519_PUBLIC_KEY, _PUBLIC_KEY_BYTES)
    csv_blob = BlobWrite(BlobKind.RAW_CSV, b"x")
    cert_blob = BlobWrite(BlobKind.VCERT_ENVELOPE, b"cert")
    attempt_blob = BlobWrite(BlobKind.ATTEMPT_ENVELOPE, b"attempt")
    bad_id = "A" * 64
    with pytest.raises(ValueError, match="keyid"):
        KeyRecord("bad", key_blob.ref)
    with pytest.raises(ValueError, match="ed25519_public_key"):
        KeyRecord(csv_blob.ref.digest, csv_blob.ref)
    with pytest.raises(ValueError, match="must equal"):
        KeyRecord("sha256:" + "b" * 64, key_blob.ref)
    with pytest.raises(ValueError, match="plot_id"):
        PlotRecord(bad_id, cert_blob.ref, key_blob.ref.digest, PlotSourceKind.DATASET)
    with pytest.raises(ValueError, match="vcert_envelope"):
        PlotRecord(_address(csv_blob), csv_blob.ref, key_blob.ref.digest, PlotSourceKind.DATASET)
    with pytest.raises(ValueError, match="VCert envelope"):
        PlotRecord("b" * 64, cert_blob.ref, key_blob.ref.digest, PlotSourceKind.DATASET)
    with pytest.raises(TypeError, match="PlotSourceKind"):
        PlotRecord(
            _address(cert_blob),
            cert_blob.ref,
            key_blob.ref.digest,
            cast("PlotSourceKind", "dataset"),
        )
    with pytest.raises(ValueError, match="attempt_id"):
        AttemptRecord(bad_id, attempt_blob.ref, key_blob.ref.digest)
    with pytest.raises(ValueError, match="attempt plot_id"):
        AttemptRecord(_address(attempt_blob), attempt_blob.ref, key_blob.ref.digest, bad_id)
    with pytest.raises(ValueError, match="attempt_envelope"):
        AttemptRecord(_address(csv_blob), csv_blob.ref, key_blob.ref.digest)
    with pytest.raises(ValueError, match="attempt envelope"):
        AttemptRecord("b" * 64, attempt_blob.ref, key_blob.ref.digest)


def test_reference_record_runtime_validation() -> None:
    key_blob = BlobWrite(BlobKind.ED25519_PUBLIC_KEY, _PUBLIC_KEY_BYTES)
    csv_blob = BlobWrite(BlobKind.RAW_CSV, b"x")
    plot_id = _address(BlobWrite(BlobKind.VCERT_ENVELOPE, b"cert"))
    attempt_id = _address(BlobWrite(BlobKind.ATTEMPT_ENVELOPE, b"attempt"))
    with pytest.raises(TypeError, match="PlotRole"):
        PlotReference(plot_id, cast("PlotRole", "raw_csv"), csv_blob.ref)
    with pytest.raises(ValueError, match="requires blob kind"):
        PlotReference(plot_id, PlotRole.RAW_CSV, key_blob.ref)
    with pytest.raises(TypeError, match="AttemptRole"):
        AttemptReference(attempt_id, cast("AttemptRole", "raw_csv"), csv_blob.ref)
    with pytest.raises(ValueError, match="requires blob kind"):
        AttemptReference(attempt_id, AttemptRole.RAW_CSV, key_blob.ref)


def test_spec_record_and_migration_limit_runtime_validation(tmp_path: Path) -> None:
    absolute = tmp_path.resolve()
    for bad in (0, -1, _BOOL_AS_INT, cast("int", 1.5), 2**63):
        with pytest.raises(ValueError, match="max_spec_bytes"):
            Archive(absolute, max_logical_bytes=1, max_spec_bytes=bad)

    spec_blob = BlobWrite(BlobKind.CANONICAL_SPEC, b"{}")
    csv_blob = BlobWrite(BlobKind.RAW_CSV, b"{}")
    with pytest.raises(ValueError, match="spec_id"):
        SpecRecord("A" * 64, spec_blob.ref)
    with pytest.raises(ValueError, match="canonical_spec"):
        SpecRecord("b" * 64, csv_blob.ref)


def test_batch_and_read_api_runtime_validation(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    blob = BlobWrite(BlobKind.RAW_CSV, b"x")
    with pytest.raises(TypeError, match="ArchiveBatch"):
        archive.publish(cast("ArchiveBatch", object()))
    malformed = ArchiveBatch(blobs=cast("tuple[BlobWrite, ...]", [blob]))
    with pytest.raises(TypeError, match="batch blobs"):
        archive.publish(malformed)
    with pytest.raises(TypeError, match="BlobRef"):
        archive.read_blob(cast("BlobRef", object()), max_bytes=1)
    for bad in (-1, _BOOL_AS_INT, cast("int", 1.5), _MAX_SQLITE_INTEGER + 1):
        with pytest.raises(ValueError, match="max_bytes"):
            archive.read_blob(blob.ref, max_bytes=bad)
    with pytest.raises(ValueError, match="plot_id"):
        archive.read_plot_blob("bad", PlotRole.RAW_CSV, max_bytes=1)
    with pytest.raises(TypeError, match="PlotRole"):
        archive.read_plot_blob("a" * 64, cast("PlotRole", "raw_csv"), max_bytes=1)
    with pytest.raises(ValueError, match="attempt_id"):
        archive.read_attempt_blob("bad", AttemptRole.RAW_CSV, max_bytes=1)
    with pytest.raises(TypeError, match="AttemptRole"):
        archive.read_attempt_blob("a" * 64, cast("AttemptRole", "raw_csv"), max_bytes=1)


def test_connection_readback_and_scalar_shape_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real_read_scalar = archive_module._read_scalar

    def wrong_journal(connection: sqlite3.Connection, statement: str) -> object:
        if statement == "PRAGMA journal_mode":
            return "wal"
        return real_read_scalar(connection, statement)

    monkeypatch.setattr(archive_module, "_read_scalar", wrong_journal)
    with pytest.raises(ArchiveError, match="journal_mode"):
        _archive(tmp_path)

    monkeypatch.setattr(archive_module, "_read_scalar", real_read_scalar)
    connection = sqlite3.connect(":memory:", autocommit=True)
    try:
        with pytest.raises(ArchiveIntegrityError, match="exactly one scalar"):
            archive_module._read_scalar(connection, "CREATE TABLE example(value TEXT)")
    finally:
        connection.close()


def test_database_precreation_closes_descriptor_on_fsync_fault(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    real_fsync = os.fsync
    database_descriptor: int | None = None

    def fail_first_regular(descriptor: int) -> None:
        nonlocal database_descriptor
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            database_descriptor = descriptor
            msg = "injected fsync fault"
            raise OSError(msg)
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_first_regular)
    with pytest.raises(ArchiveError, match="secure provenance"):
        open_archive(settings)
    assert database_descriptor is not None
    with pytest.raises(OSError):
        os.fstat(database_descriptor)


def test_private_metadata_modes_are_exact_not_only_owner_private(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    database = state / "archive.sqlite3"
    database.touch(mode=0o600)

    state_descriptor = os.open(state, os.O_RDONLY | os.O_DIRECTORY)
    database_descriptor = os.open(database, os.O_RDONLY)
    try:
        database.chmod(0o400)
        with pytest.raises(ArchiveError, match="mode 0600"):
            archive_module._validate_database_file(database_descriptor, state_descriptor)
        database.chmod(0o600)
        state.chmod(0o500)
        with pytest.raises(ArchiveError, match="mode 0700"):
            archive_module._validate_database_file(database_descriptor, state_descriptor)
    finally:
        os.close(database_descriptor)
        os.close(state_descriptor)


def test_blob_metadata_and_stream_short_read_corruption_guards() -> None:
    valid_blob = BlobWrite(BlobKind.RAW_CSV, b"abc")
    valid_row = (1, valid_blob.ref.digest, BlobKind.RAW_CSV.value, 3)
    for malformed in (None, (1, valid_blob.ref.digest, BlobKind.RAW_CSV.value)):
        with pytest.raises(ArchiveIntegrityError, match="metadata row"):
            archive_module._validated_blob_row(malformed)
    for corrupt in (
        (0, valid_blob.ref.digest, BlobKind.RAW_CSV.value, 3),
        (1, "bad", BlobKind.RAW_CSV.value, 3),
        (1, valid_blob.ref.digest, BlobKind.RAW_CSV.value, -1),
    ):
        with pytest.raises(ArchiveIntegrityError, match="types or values"):
            archive_module._validated_blob_row(corrupt)
    with pytest.raises(ArchiveIntegrityError, match="unknown kind"):
        archive_module._validated_blob_row((1, valid_blob.ref.digest, "unknown", 3))

    class FakeBlob:
        def __init__(self, *, reported_size: int, value: bytes) -> None:
            self.reported_size = reported_size
            self.value = value

        def __enter__(self) -> "FakeBlob":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def __len__(self) -> int:
            return self.reported_size

        def read(self, _length: int) -> bytes:
            return self.value

    class FakeConnection:
        def __init__(self, blob: FakeBlob) -> None:
            self.blob = blob

        def blobopen(self, *_args: object, **_kwargs: object) -> FakeBlob:
            return self.blob

    expected = valid_blob.ref
    collect = archive_module._BlobReadPolicy(max_bytes=3, expected_payload=None, collect=True)
    with pytest.raises(ArchiveIntegrityError, match="payload length"):
        archive_module._consume_blob(
            cast("sqlite3.Connection", FakeConnection(FakeBlob(reported_size=2, value=b"ab"))),
            valid_row,
            expected,
            collect,
        )
    with pytest.raises(ArchiveIntegrityError, match="ended during"):
        archive_module._consume_blob(
            cast("sqlite3.Connection", FakeConnection(FakeBlob(reported_size=3, value=b"ab"))),
            valid_row,
            expected,
            collect,
        )
    with pytest.raises(ArchiveIntegrityError, match="size disagrees"):
        archive_module._consume_blob(
            cast("sqlite3.Connection", FakeConnection(FakeBlob(reported_size=3, value=b"abc"))),
            valid_row,
            expected,
            archive_module._BlobReadPolicy(max_bytes=4, expected_payload=b"abcd", collect=False),
        )
    with pytest.raises(ArchiveIntegrityError, match="incoming typed payload"):
        archive_module._consume_blob(
            cast(
                "sqlite3.Connection",
                FakeConnection(FakeBlob(reported_size=3, value=b"abc")),
            ),
            valid_row,
            expected,
            archive_module._BlobReadPolicy(max_bytes=3, expected_payload=b"abd", collect=False),
        )


def test_batch_digest_collision_and_wrong_element_types_fail_before_sql(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    first = BlobWrite(BlobKind.RAW_CSV, b"first")
    forged = object.__new__(BlobWrite)
    object.__setattr__(forged, "kind", BlobKind.RAW_MANIFEST)
    object.__setattr__(forged, "payload", b"different")
    object.__setattr__(forged, "ref", first.ref)
    with pytest.raises(ArchiveIntegrityError, match="conflicting typed bytes"):
        archive.publish(ArchiveBatch(blobs=(first, forged)))

    malformed = ArchiveBatch(keys=cast("tuple[KeyRecord, ...]", (object(),)))
    with pytest.raises(TypeError, match="batch keys"):
        archive.publish(malformed)
    assert archive.stats().blobs == 0


def test_accounting_tripwire_rolls_back_if_postinsert_total_disagrees(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = _archive(tmp_path)
    blob = BlobWrite(BlobKind.RAW_CSV, b"abc")
    real_validate = archive_module._validate_schema
    calls = 0

    def drift_after_insert(connection: sqlite3.Connection, *, verify_accounting: bool) -> int:
        nonlocal calls
        calls += 1
        actual = real_validate(connection, verify_accounting=verify_accounting)
        return actual + 1 if calls == 2 else actual

    monkeypatch.setattr(archive_module, "_validate_schema", drift_after_insert)
    with pytest.raises(ArchiveIntegrityError, match="trigger did not account"):
        archive.publish(ArchiveBatch(blobs=(blob,)))
    monkeypatch.setattr(archive_module, "_validate_schema", real_validate)
    assert archive.stats().blobs == 0


def test_sqlite_faults_are_normalized_and_connections_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = _archive(tmp_path / "runtime")
    blob = BlobWrite(BlobKind.RAW_CSV, b"abc")
    archive.publish(ArchiveBatch(blobs=(blob,)))

    real_publish = archive_module._publish_batch

    def fail_publish(*_args: object) -> None:
        msg = "publish fault"
        raise sqlite3.OperationalError(msg)

    monkeypatch.setattr(archive_module, "_publish_batch", fail_publish)
    with pytest.raises(ArchiveError, match="publishing"):
        archive.publish(ArchiveBatch())
    monkeypatch.setattr(archive_module, "_publish_batch", real_publish)

    real_consume = archive_module._consume_blob

    def fail_read(*_args: object) -> None:
        msg = "read fault"
        raise sqlite3.DatabaseError(msg)

    monkeypatch.setattr(archive_module, "_consume_blob", fail_read)
    with pytest.raises(ArchiveError, match="bounded archive blob read"):
        archive.read_blob(blob.ref, max_bytes=3)
    monkeypatch.setattr(archive_module, "_consume_blob", real_consume)

    real_scalar = archive_module._read_scalar

    def bad_count(connection: sqlite3.Connection, statement: str) -> object:
        if statement == "SELECT COUNT(*) FROM blobs":
            return "corrupt"
        return real_scalar(connection, statement)

    monkeypatch.setattr(archive_module, "_read_scalar", bad_count)
    with pytest.raises(ArchiveIntegrityError, match="row counts"):
        archive.stats()

    def fail_count(connection: sqlite3.Connection, statement: str) -> object:
        if statement == "SELECT COUNT(*) FROM blobs":
            msg = "stats fault"
            raise sqlite3.DatabaseError(msg)
        return real_scalar(connection, statement)

    monkeypatch.setattr(archive_module, "_read_scalar", fail_count)
    with pytest.raises(ArchiveError, match="statistics"):
        archive.stats()
    monkeypatch.setattr(archive_module, "_read_scalar", real_scalar)

    real_initialize = archive_module._create_or_validate_schema

    def fail_initialize(_connection: sqlite3.Connection, **_kwargs: object) -> None:
        msg = "initialize fault"
        raise sqlite3.DatabaseError(msg)

    monkeypatch.setattr(archive_module, "_create_or_validate_schema", fail_initialize)
    (tmp_path / "initialize").mkdir(mode=0o700)
    with pytest.raises(ArchiveError, match="initializing"):
        _archive(tmp_path / "initialize")
    monkeypatch.setattr(archive_module, "_create_or_validate_schema", real_initialize)


_V3_CREATE_BLOBS = """CREATE TABLE blobs (
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

_V3_CREATE_PLOTS = """CREATE TABLE plots (
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

_V3_CREATE_PLOT_REFERENCES = """CREATE TABLE plot_references (
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

_DATASET_ONLY_ROLES = ("raw_csv", "raw_manifest", "vega_lite", "svg")
_FORMULA_ONLY_ROLES = ("formula_source", "matplotlib_script")
_SHARED_ROLES = ("canonical_spec", "plotted_table", "verdict", "vcert_payload", "tool_versions")
_RELATION_TABLES = ("plots", "specs", "attempts", "plot_references", "attempt_references", "keys")


def _relation_snapshot(connection: sqlite3.Connection) -> dict[str, list[Any]]:
    return {
        table: connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()  # noqa: S608
        for table in _RELATION_TABLES
    }


def _blob_snapshot(connection: sqlite3.Connection) -> list[Any]:
    return connection.execute(
        "SELECT digest, kind, size, content FROM blobs ORDER BY digest, kind"
    ).fetchall()


def _rootpages(connection: sqlite3.Connection) -> dict[str, int]:
    rows = connection.execute(
        "SELECT name, rootpage FROM sqlite_schema WHERE sql IS NOT NULL"
    ).fetchall()
    return {cast("str", row[0]): cast("int", row[1]) for row in rows}


def _is_exact_schema(
    connection: sqlite3.Connection, objects: tuple[tuple[str, str, str, str], ...]
) -> bool:
    return archive_module._schema_rows(connection) == tuple(
        sorted(objects, key=lambda row: (row[0], row[1]))
    )


def _install_recording_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[str], list[tuple[object, object]]]:
    """Record every statement the archive executes, plus its guard state captured at close().

    Both suspended settings are per-connection, so the archive's own connection is the only place
    restoration is observable, and it is closed before construction returns either way.
    """
    statements: list[str] = []
    closing_state: list[tuple[object, object]] = []

    class RecordingConnection(sqlite3.Connection):
        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            statements.append(sql)
            return super().execute(sql, parameters)

        def close(self) -> None:
            closing_state.append(
                (
                    self.getconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE),
                    super().execute("PRAGMA writable_schema").fetchone()[0],
                )
            )
            super().close()

    monkeypatch.setattr(archive_module, "_CONNECTION_FACTORY", RecordingConnection)
    return statements, closing_state


def _downgraded_archive(tmp_path: Path) -> Archive:
    archive = _archive(tmp_path)
    batch, _blobs = _complete_batch()
    archive.publish(batch)
    with _database_connection(archive) as connection:
        downgrade_to_v3(connection)
    return archive


def test_historic_v3_ddl_derivations_reproduce_the_shipped_v3_text() -> None:
    """P25: v2/v1 validation derives from these, so a wrong derivation rejects real old archives."""
    assert archive_module._CREATE_BLOBS_V3 == _V3_CREATE_BLOBS
    assert archive_module._CREATE_PLOTS_V3 == _V3_CREATE_PLOTS
    assert archive_module._CREATE_PLOT_REFERENCES_V3 == _V3_CREATE_PLOT_REFERENCES
    assert archive_module._CREATE_BLOBS_V3 != archive_module._CREATE_BLOBS
    assert archive_module._CREATE_PLOTS_V3 != archive_module._CREATE_PLOTS
    assert archive_module._CREATE_PLOT_REFERENCES_V3 != archive_module._CREATE_PLOT_REFERENCES
    guard = "plot_references_match_source"
    assert not any(row[1] == guard for row in archive_module._SCHEMA_OBJECTS_V3)
    assert any(row[1] == guard for row in archive_module._SCHEMA_OBJECTS)


def test_version_three_archive_migrates_to_exact_v4_preserving_every_stored_byte(
    tmp_path: Path,
) -> None:
    """P02-P05, P08, P10, P11, P23, P24, P31 on the direct v3 arm."""
    archive = _archive(tmp_path)
    batch, blobs = _complete_batch()
    archive.publish(batch)
    plot_id = batch.plots[0].plot_id
    attempt_id = batch.attempts[0].attempt_id
    before_stats = archive.stats()
    before_envelope = archive.read_plot_envelope(plot_id, max_bytes=1_000)

    with _database_connection(archive) as connection:
        downgrade_to_v3(connection)
        assert _is_exact_schema(connection, archive_module._SCHEMA_OBJECTS_V3)
        before_blobs = _blob_snapshot(connection)
        before_relations = _relation_snapshot(connection)
        before_rootpages = _rootpages(connection)
        before_logical = connection.execute("SELECT logical_blob_bytes FROM meta").fetchone()

    reopened = _archive(tmp_path)
    assert reopened.stats() == before_stats
    assert reopened.read_plot_envelope(plot_id, max_bytes=1_000) == before_envelope
    assert reopened.read_attempt_envelope(attempt_id, max_bytes=1_000) == blobs["attempt"].payload
    assert (
        reopened.read_plot_blob(plot_id, PlotRole.RAW_CSV, max_bytes=1_000) == blobs["csv"].payload
    )

    with _database_connection(reopened) as connection:
        assert _is_exact_schema(connection, archive_module._SCHEMA_OBJECTS)
        assert connection.execute("PRAGMA user_version").fetchone() == (4,)
        assert connection.execute("SELECT schema_version FROM meta").fetchone() == (4,)
        assert _blob_snapshot(connection) == before_blobs
        after_relations = _relation_snapshot(connection)
        assert after_relations["plots"] == [
            (*cast("tuple[Any, ...]", row), "dataset") for row in before_relations["plots"]
        ]
        for table in _RELATION_TABLES[1:]:
            assert after_relations[table] == before_relations[table]
        assert (
            connection.execute("SELECT logical_blob_bytes FROM meta").fetchone() == before_logical
        )
        after_rootpages = _rootpages(connection)
        assert {name: after_rootpages[name] for name in before_rootpages} == before_rootpages
        assert set(after_rootpages) - set(before_rootpages) == {"plot_references_match_source"}
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        columns = [cast("str", row[1]) for row in connection.execute("PRAGMA table_info(plots)")]
        assert columns[-1] == "source_kind"
        stored = connection.execute("SELECT sql FROM sqlite_schema WHERE name = 'plots'").fetchone()
        assert "DEFAULT" not in stored[0]
        null_rows = connection.execute("SELECT COUNT(*) FROM plots WHERE source_kind IS NULL")
        assert null_rows.fetchone() == (0,)
        with pytest.raises(sqlite3.IntegrityError, match="archive blobs are immutable"):
            connection.execute("DELETE FROM blobs")

    fresh = _archive(tmp_path / "fresh")
    with (
        _database_connection(fresh) as fresh_connection,
        _database_connection(reopened) as migrated_connection,
    ):
        assert archive_module._schema_rows(fresh_connection) == archive_module._schema_rows(
            migrated_connection
        )
        assert [tuple(row) for row in fresh_connection.execute("PRAGMA table_info(plots)")] == [
            tuple(row) for row in migrated_connection.execute("PRAGMA table_info(plots)")
        ]


@pytest.mark.parametrize(
    "target", ["_validate_schema_version", "_rewrite_stored_schema_text", "_validate_schema"]
)
def test_injected_migration_failure_rolls_back_to_exact_version_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    """P09, P30: faults before, during, and after the mutations all restore the prior version."""
    archive = _downgraded_archive(tmp_path)
    with _database_connection(archive) as connection:
        before_rows = archive_module._schema_rows(connection)
        before_relations = _relation_snapshot(connection)

    def explode(*_args: object, **_kwargs: object) -> None:
        msg = "injected migration fault"
        raise ArchiveIntegrityError(msg)

    monkeypatch.setattr(archive_module, target, explode)
    with pytest.raises(ArchiveIntegrityError, match="injected migration fault"):
        _archive(tmp_path)

    with _database_connection(archive) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (3,)
        assert connection.execute("SELECT schema_version FROM meta").fetchone() == (3,)
        assert archive_module._schema_rows(connection) == before_rows
        assert _relation_snapshot(connection) == before_relations
        assert "source_kind" not in [
            cast("str", row[1]) for row in connection.execute("PRAGMA table_info(plots)")
        ]
        guard_rows = connection.execute(
            "SELECT COUNT(*) FROM sqlite_schema WHERE name = 'plot_references_match_source'"
        )
        assert guard_rows.fetchone() == (0,)


def test_defensive_window_is_entered_before_any_schema_write_and_always_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P21, P22, P26: failing the in-window readback leaves zero rewrite work behind."""
    archive = _downgraded_archive(tmp_path)
    with _database_connection(archive) as connection:
        before_rows = archive_module._schema_rows(connection)

    _statements, closing_state = _install_recording_factory(monkeypatch)
    original = archive_module._require_connection_setting

    def refuse(name: str, actual: object, expected: object) -> None:
        if name != "writable_schema":
            original(name, actual, expected)
            return
        msg = "injected writable_schema refusal"
        raise ArchiveError(msg)

    monkeypatch.setattr(archive_module, "_require_connection_setting", refuse)
    with pytest.raises(ArchiveError, match="injected writable_schema refusal"):
        _archive(tmp_path)

    assert closing_state[-1] == (True, 0)
    with _database_connection(archive) as connection:
        assert archive_module._schema_rows(connection) == before_rows


def test_migration_statement_order_matches_the_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P26-P30: presence assertions cannot see order, so record the executed statements."""
    archive = _downgraded_archive(tmp_path)
    statements, closing_state = _install_recording_factory(monkeypatch)
    _archive(tmp_path)

    def first(fragment: str) -> int:
        return next(index for index, sql in enumerate(statements) if fragment in sql)

    order = [
        first("ALTER TABLE plots ADD COLUMN source_kind"),
        first("UPDATE plots SET source_kind"),
        first("PRAGMA writable_schema=ON"),
        first("UPDATE sqlite_schema SET sql"),
        first("PRAGMA schema_version="),
        first("PRAGMA writable_schema=RESET"),
        first("PRAGMA writable_schema=OFF"),
        first("CREATE TRIGGER plot_references_match_source"),
        first("PRAGMA user_version=4"),
        first("COMMIT"),
    ]
    assert order == sorted(order)
    assert statements.index("BEGIN IMMEDIATE") < order[0]
    assert sum(1 for sql in statements if "UPDATE sqlite_schema SET sql" in sql) == 3
    assert closing_state[-1] == (True, 0)
    assert archive.stats().plots == 1


def test_widened_domains_still_reject_an_unknown_kind_and_role(tmp_path: Path) -> None:
    """P12, P13: widening the CHECK domains must not open them.

    The insert-time trigger refuses an unknown role first, so the role domain is only observable
    once that trigger is out of the way on this throwaway connection.
    """
    archive = _archive(tmp_path)
    batch, blobs = _complete_batch()
    archive.publish(batch)
    plot_id = batch.plots[0].plot_id
    with _database_connection(archive) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            connection.execute(
                "INSERT INTO blobs(digest, kind, size, content) VALUES (?, ?, ?, ?)",
                ("sha256:" + "e" * 64, "formula_script", 1, b"x"),
            )
        connection.execute("DROP TRIGGER plot_references_match_source")
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            connection.execute(
                "INSERT INTO plot_references VALUES (?, ?, ?, ?)",
                (plot_id, "formula_table", blobs["csv"].ref.digest, "formula_table"),
            )


@pytest.mark.parametrize("mode", ["dataset", "formula"])
def test_plot_reference_mode_guard_admits_exactly_that_modes_roles(
    tmp_path: Path, mode: str
) -> None:
    """P14, P15: one case per role in both directions - a full matrix, not one sample."""
    archive = _archive(tmp_path)
    batch, blobs = _complete_batch()
    archive.publish(batch)
    admitted = _SHARED_ROLES + (_DATASET_ONLY_ROLES if mode == "dataset" else _FORMULA_ONLY_ROLES)
    refused = _FORMULA_ONLY_ROLES if mode == "dataset" else _DATASET_ONLY_ROLES
    with _database_connection(archive) as connection:
        plot_id = "2" * 64
        connection.execute(
            "INSERT INTO blobs(digest, kind, size, content) VALUES (?, ?, ?, ?)",
            (f"sha256:{plot_id}", "vcert_envelope", 1, b"e"),
        )
        connection.execute(
            "INSERT INTO plots VALUES (?, ?, ?, ?, ?)",
            (plot_id, f"sha256:{plot_id}", "vcert_envelope", blobs["key"].ref.digest, mode),
        )
        for index, role in enumerate(admitted + refused):
            digest = "sha256:" + f"{index:x}".rjust(64, "a")
            connection.execute(
                "INSERT INTO blobs(digest, kind, size, content) VALUES (?, ?, ?, ?)",
                (digest, role, 1, b"b"),
            )
            statement = "INSERT INTO plot_references VALUES (?, ?, ?, ?)"
            values = (plot_id, role, digest, role)
            if role in admitted:
                connection.execute(statement, values)
            else:
                with pytest.raises(sqlite3.IntegrityError, match="disagrees with plot source kind"):
                    connection.execute(statement, values)
        stored = connection.execute(
            "SELECT role FROM plot_references WHERE plot_id = ? ORDER BY role", (plot_id,)
        ).fetchall()
        assert [cast("str", row[0]) for row in stored] == sorted(admitted)


def test_plot_reference_mode_guard_refuses_a_reference_without_its_plot(tmp_path: Path) -> None:
    """P16: the guard's EXISTS arm is a distinct refusal from its role arm."""
    archive = _archive(tmp_path)
    batch, blobs = _complete_batch()
    archive.publish(batch)
    with (
        _database_connection(archive) as connection,
        pytest.raises(sqlite3.IntegrityError, match="disagrees with plot source kind"),
    ):
        connection.execute(
            "INSERT INTO plot_references VALUES (?, ?, ?, ?)",
            ("f" * 64, "raw_csv", blobs["csv"].ref.digest, "raw_csv"),
        )


def test_mode_flipped_plot_row_is_refused_by_each_reader_that_interprets_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P20: a direct UPDATE past the INSERT-only trigger leaves corrupt, not supported, state.

    Both modes decode at this version, so the readers no longer share one blanket mode guard. Each
    refuses on its own terms instead: the complete read against the formula role set the tag now
    claims, the certificate read under the v0.3 wrapper that tag selects, and the attempt read
    against that same role set through its nested plot. P20b: the byte reader interprets nothing
    and stays excluded.
    """
    archive = _archive(tmp_path)
    batch, blobs = _complete_batch()
    archive.publish(batch)
    plot_id = batch.plots[0].plot_id
    attempt_id = batch.attempts[0].attempt_id
    with _database_connection(archive) as connection:
        connection.execute("UPDATE plots SET source_kind = 'formula' WHERE plot_id = ?", (plot_id,))

    with pytest.raises(ArchiveIntegrityError, match="every required role exactly once"):
        archive.read_plot(plot_id, max_bytes=100_000)
    with pytest.raises(ArchiveIntegrityError, match="every required role exactly once"):
        archive.read_attempt(attempt_id, max_bytes=100_000)

    def unreachable(*_args: object, **_kwargs: object) -> None:
        msg = "the dataset certificate wrapper ran on a formula-tagged plot"
        raise AssertionError(msg)

    # The tag alone must move certificate authentication onto the v0.3 wrapper, where these stored
    # v0.2 envelope bytes fail. Bombing the dataset wrapper proves selection, not merely refusal.
    monkeypatch.setattr(archive_module, "_authenticate_archive_certificate", unreachable)
    with pytest.raises(ArchiveIntegrityError, match="archived formula VCert envelope"):
        archive.read_certificate(plot_id, max_bytes=100_000)
    monkeypatch.undo()

    assert archive.read_plot_envelope(plot_id, max_bytes=1_000) == blobs["certificate"].payload


def test_exact_schema_validator_refuses_near_miss_version_four_text(tmp_path: Path) -> None:
    """P18: the validator must refuse a reordered role list, not merely accept the right text."""
    archive = _archive(tmp_path)
    near_miss = archive_module._CREATE_PLOT_REFERENCES.replace(
        "'tool_versions', 'formula_source',", "'formula_source', 'tool_versions',"
    )
    assert near_miss != archive_module._CREATE_PLOT_REFERENCES
    with _database_connection(archive) as connection:
        connection.execute("PRAGMA writable_schema=ON")
        connection.execute(
            "UPDATE sqlite_schema SET sql = ? WHERE type = 'table' AND name = 'plot_references'",
            (near_miss,),
        )
        cookie = cast("int", connection.execute("PRAGMA schema_version").fetchone()[0])
        connection.execute(f"PRAGMA schema_version={cookie + 1}")
        connection.execute("PRAGMA writable_schema=RESET")
        connection.execute("PRAGMA writable_schema=OFF")
    with pytest.raises(ArchiveSchemaError, match="schema objects disagree"):
        _archive(tmp_path)
