# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Successful-plot archive graph, bounded public reads, migration, and round-trip."""

import hashlib
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import msgspec
import pytest

from verifier import attestation, canon, render
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.schema import decode_spec
from verifier.service import archive as archive_module
from verifier.service import pipeline
from verifier.service.archive import (
    ArchiveIntegrityError,
    ArchiveNotFoundError,
    ArchiveReadLimitError,
    ArchiveStats,
    BlobKind,
    BlobWrite,
    PlotBundle,
    PlotRole,
    materialize_plot_bundle,
    open_archive,
)
from verifier.service.identity import Signer, load_identity
from verifier.service.models import Verdict
from verifier.service.settings import Settings

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_RAW_SPEC = (_ROOT / "examples/good_specs/g01_total_revenue_by_month.json").read_bytes()


def _parts(
    tmp_path: Path,
) -> tuple[Settings, Signer, render.PreparedArtifact, render.RenderResult, PlotBundle]:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    signer = load_identity(settings).signer
    outcome = pipeline.verify_only(_RAW_SPEC, settings)
    prepared = cast("render.PreparedArtifact", outcome.prepared)
    rendered = render.render_prepared(prepared, limits=settings.limits)
    envelope = attestation.sign_vcert(
        rendered.certificate,
        signer.private_key,
        keyid=signer.keyid,
        limits=settings.limits,
    )
    bundle = materialize_plot_bundle(
        prepared,
        rendered,
        envelope,
        signer,
        limits=settings.limits,
    )
    return settings, signer, prepared, rendered, bundle


def _bundle_bytes(bundle: PlotBundle) -> int:
    return sum(
        len(cast("bytes", getattr(bundle, name)))
        for name in archive_module._PLOT_BUNDLE_BYTE_FIELDS
    )


def _resign_bundle(
    bundle: PlotBundle,
    signer: Signer,
    certificate: render.VCert,
    *,
    payload: bytes | None = None,
    keyid: str | None = None,
) -> PlotBundle:
    if payload is None:
        payload = render.vcert_bytes(certificate)
    if keyid is None:
        keyid = signer.keyid
    signature = signer.private_key.sign(attestation.pae(attestation.VCERT_PAYLOAD_TYPE, payload))
    envelope = attestation._encode_envelope(payload, signature, keyid)
    return replace(
        bundle,
        plot_id=hashlib.sha256(envelope).hexdigest(),
        vcert_payload=payload,
        vcert_envelope=envelope,
    )


def test_materialized_plot_resolves_every_certified_byte_and_round_trips_reopen(
    tmp_path: Path,
) -> None:
    settings, signer, prepared, rendered, bundle = _parts(tmp_path)
    evidence = prepared.evidence
    certified = rendered.certificate
    assert bundle.plot_id == hashlib.sha256(bundle.vcert_envelope).hexdigest()
    assert bundle.keyid == signer.keyid
    assert bundle.raw_csv == evidence.source_bytes
    assert bundle.raw_manifest == evidence.manifest_bytes
    assert bundle.canonical_spec == canon.spec_bytes(prepared.spec)
    assert bundle.plotted_table == canon.serialize_table(evidence.plotted_table).encode()
    assert bundle.vega_lite == prepared.vega_lite == rendered.vega_lite
    assert bundle.svg == rendered.svg.encode()
    assert bundle.vcert_payload == render.vcert_bytes(certified)
    assert msgspec.json.decode(bundle.tool_versions) == msgspec.to_builtins(certified.tcb)
    assert canon.hash_dataset(bundle.raw_csv) == certified.dataset_hash
    assert canon.hash_manifest(bundle.raw_manifest) == certified.manifest_hash
    assert canon.hash_table_bytes(bundle.plotted_table) == certified.plotted_table_hash
    assert render.hash_vega_lite(bundle.vega_lite) == certified.vega_lite_hash

    verdict = msgspec.json.decode(bundle.verdict)
    assert verdict["verified"] is True
    assert [(item["check"], item["method"], item["status"]) for item in verdict["results"]] == [
        (item.id, item.method, item.status) for item in certified.checks
    ]
    verified = attestation.verify_vcert(bundle.vcert_envelope, {signer.keyid: signer.public_key})
    assert verified.payload == bundle.vcert_payload
    assert verified.certificate == certified

    archive = open_archive(settings)
    archive.publish_plot(bundle, limits=settings.limits)
    expected_bytes = _bundle_bytes(bundle)
    assert archive.stats() == ArchiveStats(expected_bytes, 11, 1, 1, 0)
    assert archive.read_plot_envelope(bundle.plot_id, max_bytes=len(bundle.vcert_envelope)) == (
        bundle.vcert_envelope
    )
    assert archive.read_key(bundle.keyid, max_bytes=len(bundle.public_key)) == bundle.public_key

    role_payloads = {
        PlotRole.RAW_CSV: bundle.raw_csv,
        PlotRole.RAW_MANIFEST: bundle.raw_manifest,
        PlotRole.CANONICAL_SPEC: bundle.canonical_spec,
        PlotRole.PLOTTED_TABLE: bundle.plotted_table,
        PlotRole.VERDICT: bundle.verdict,
        PlotRole.VEGA_LITE: bundle.vega_lite,
        PlotRole.SVG: bundle.svg,
        PlotRole.VCERT_PAYLOAD: bundle.vcert_payload,
        PlotRole.TOOL_VERSIONS: bundle.tool_versions,
    }
    assert {
        role: archive.read_plot_blob(bundle.plot_id, role, max_bytes=len(payload))
        for role, payload in role_payloads.items()
    } == role_payloads

    reopened = open_archive(settings)
    assert (
        reopened.read_plot(bundle.plot_id, max_bytes=expected_bytes, limits=settings.limits)
        == bundle
    )
    reopened.publish_plot(bundle, limits=settings.limits)
    assert reopened.stats() == archive.stats()


def test_version_one_archive_chains_spec_and_attempt_index_migrations_atomically(
    tmp_path: Path,
) -> None:
    settings, _signer, _prepared, rendered, bundle = _parts(tmp_path)
    archive = open_archive(settings)
    archive.publish_plot(bundle, limits=settings.limits)
    connection = sqlite3.connect(archive.database_path, autocommit=True)
    try:
        connection.execute("DROP INDEX attempts_by_plot")
        connection.execute("DROP TABLE specs")
        connection.execute("UPDATE meta SET schema_version = 1 WHERE singleton = 1")
        connection.execute("PRAGMA user_version=1")
    finally:
        connection.close()

    reopened = open_archive(settings)
    spec_id = rendered.certificate.spec_hash.removeprefix("sha256:")
    assert (
        reopened.read_spec(spec_id, max_bytes=len(bundle.canonical_spec)) == bundle.canonical_spec
    )
    connection = sqlite3.connect(reopened.database_path, autocommit=True)
    try:
        assert connection.execute("PRAGMA user_version").fetchone() == (3,)
        assert connection.execute(
            "SELECT schema_version FROM meta WHERE singleton = 1"
        ).fetchone() == (3,)
        assert connection.execute(
            "SELECT sql FROM sqlite_schema WHERE name = ?", ("attempts_by_plot",)
        ).fetchone() == (archive_module._CREATE_ATTEMPTS_BY_PLOT,)
    finally:
        connection.close()


def test_rotated_signature_creates_second_plot_while_shared_role_blobs_deduplicate(
    tmp_path: Path,
) -> None:
    settings, _signer, prepared, rendered, first = _parts(tmp_path)
    archive = open_archive(settings)
    archive.publish_plot(first, limits=settings.limits)

    rotated_settings = Settings(
        data_dir=_DATA,
        state_dir=settings.state_dir,
        signing_key_file=settings.state_dir / "rotated.key",
    )
    rotated = load_identity(rotated_settings).signer
    envelope = attestation.sign_vcert(
        rendered.certificate,
        rotated.private_key,
        keyid=rotated.keyid,
        limits=rotated_settings.limits,
    )
    second = materialize_plot_bundle(
        prepared,
        rendered,
        envelope,
        rotated,
        limits=rotated_settings.limits,
    )
    archive.publish_plot(second, limits=rotated_settings.limits)

    assert first.plot_id != second.plot_id
    assert first.keyid != second.keyid
    for name in archive_module._PLOT_BUNDLE_BYTE_FIELDS:
        if name not in {"vcert_envelope", "public_key"}:
            assert getattr(first, name) == getattr(second, name)
    shared_bytes = _bundle_bytes(first) - len(first.vcert_envelope) - len(first.public_key)
    expected_bytes = (
        shared_bytes
        + len(first.vcert_envelope)
        + len(first.public_key)
        + len(second.vcert_envelope)
        + len(second.public_key)
    )
    assert archive.stats() == ArchiveStats(expected_bytes, 13, 2, 2, 0)
    assert archive.read_plot(first.plot_id, max_bytes=_bundle_bytes(first)) == first
    assert archive.read_plot(second.plot_id, max_bytes=_bundle_bytes(second)) == second


def test_plot_publish_fault_rolls_back_every_high_level_row_and_blob(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, _signer, _prepared, _rendered, bundle = _parts(tmp_path)
    archive = open_archive(settings)

    class InjectedError(Exception):
        pass

    def fail() -> None:
        raise InjectedError

    monkeypatch.setattr(archive_module, "_before_archive_commit", fail)
    with pytest.raises(InjectedError):
        archive.publish_plot(bundle)
    assert archive.stats() == ArchiveStats(0, 0, 0, 0, 0)
    with pytest.raises(ArchiveNotFoundError):
        archive.read_plot(bundle.plot_id, max_bytes=_bundle_bytes(bundle))


def test_complete_plot_read_admits_aggregate_size_before_opening_any_blob(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, _signer, _prepared, _rendered, bundle = _parts(tmp_path)
    archive = open_archive(settings)
    archive.publish_plot(bundle)
    size = _bundle_bytes(bundle)

    class TrackingConnection(sqlite3.Connection):
        blob_opens = 0

        def blobopen(self, *args: Any, **kwargs: Any) -> sqlite3.Blob:
            type(self).blob_opens += 1
            return super().blobopen(*args, **kwargs)

    monkeypatch.setattr(archive_module, "_CONNECTION_FACTORY", TrackingConnection)
    with pytest.raises(ArchiveReadLimitError, match="aggregate read limit"):
        archive.read_plot(bundle.plot_id, max_bytes=size - 1)
    assert TrackingConnection.blob_opens == 0
    assert archive.read_plot(bundle.plot_id, max_bytes=size) == bundle
    assert TrackingConnection.blob_opens == 11


def test_public_artifact_reads_admit_metadata_before_opening_blobs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, _signer, _prepared, rendered, bundle = _parts(tmp_path)
    archive = open_archive(settings)
    archive.publish_plot(bundle, limits=settings.limits)
    spec_id = rendered.certificate.spec_hash.removeprefix("sha256:")

    class TrackingConnection(sqlite3.Connection):
        blob_opens = 0

        def blobopen(self, *args: Any, **kwargs: Any) -> sqlite3.Blob:
            type(self).blob_opens += 1
            return super().blobopen(*args, **kwargs)

    monkeypatch.setattr(archive_module, "_CONNECTION_FACTORY", TrackingConnection)
    with pytest.raises(ArchiveReadLimitError, match="VCert envelope"):
        archive.read_certificate(
            bundle.plot_id,
            max_bytes=len(bundle.vcert_envelope) - 1,
            limits=settings.limits,
        )
    with pytest.raises(ArchiveReadLimitError, match="canonical spec"):
        archive.read_spec(spec_id, max_bytes=len(bundle.canonical_spec) - 1)
    with pytest.raises(ArchiveReadLimitError, match="public key"):
        archive.read_key(bundle.keyid, max_bytes=len(bundle.public_key) - 1)
    assert TrackingConnection.blob_opens == 0


def test_bundle_api_runtime_shape_and_direct_materialization_invariants(
    tmp_path: Path,
) -> None:
    settings, signer, prepared, rendered, bundle = _parts(tmp_path)
    archive = open_archive(settings)
    with pytest.raises(ValueError, match="bundle id"):
        replace(bundle, plot_id="bad")
    with pytest.raises(ValueError, match="bundle keyid"):
        replace(bundle, keyid="bad")
    with pytest.raises(TypeError, match="raw_csv must be bytes"):
        replace(bundle, raw_csv=cast("bytes", "bad"))

    with pytest.raises(TypeError, match="prepared must be PreparedArtifact"):
        materialize_plot_bundle(cast("render.PreparedArtifact", object()), rendered, b"x", signer)
    with pytest.raises(TypeError, match="rendered must be RenderResult"):
        materialize_plot_bundle(prepared, cast("render.RenderResult", object()), b"x", signer)
    with pytest.raises(TypeError, match="signer must be Signer"):
        materialize_plot_bundle(prepared, rendered, b"x", cast("Signer", object()))
    with pytest.raises(TypeError, match="envelope must be bytes"):
        materialize_plot_bundle(prepared, rendered, cast("bytes", "bad"), signer)
    with pytest.raises(TypeError, match="limits must be VerificationLimits"):
        materialize_plot_bundle(
            prepared,
            rendered,
            b"x",
            signer,
            limits=cast("VerificationLimits", object()),
        )
    with pytest.raises(ValueError, match="Vega-Lite bytes differ"):
        materialize_plot_bundle(
            prepared,
            msgspec.structs.replace(rendered, vega_lite=rendered.vega_lite + b" "),
            b"x",
            signer,
        )

    with pytest.raises(TypeError, match="bundle must be a PlotBundle"):
        archive.publish_plot(cast("PlotBundle", object()))
    with pytest.raises(TypeError, match="limits must be VerificationLimits"):
        archive.publish_plot(bundle, limits=cast("VerificationLimits", object()))
    with pytest.raises(ValueError, match="plot_id"):
        archive.read_plot("bad", max_bytes=1)
    with pytest.raises(ValueError, match="max_bytes"):
        archive.read_plot(bundle.plot_id, max_bytes=-1)
    with pytest.raises(TypeError, match="limits must be VerificationLimits"):
        archive.read_plot(
            bundle.plot_id,
            max_bytes=_bundle_bytes(bundle),
            limits=cast("VerificationLimits", object()),
        )


def test_publish_rejects_noncanonical_or_invalid_plotted_table_bytes(tmp_path: Path) -> None:
    settings, signer, _prepared, rendered, bundle = _parts(tmp_path)
    archive = open_archive(settings)
    payloads = (
        bundle.plotted_table + b"\xff",
        b'["value:unknown"]\n["x"]\n',
        bundle.plotted_table.replace(b"[", b"[ ", 1),
    )

    for payload in payloads:
        certificate = msgspec.structs.replace(
            rendered.certificate,
            plotted_table_hash=canon.hash_table_bytes(payload),
        )
        mutant = _resign_bundle(
            replace(bundle, plotted_table=payload),
            signer,
            certificate,
        )
        with pytest.raises(ArchiveIntegrityError, match="plotted table"):
            archive.publish_plot(mutant)

    archive_module._decode_canonical_table(b'["when:temporal:date"]\n["2026-07-17"]\n')
    assert archive.stats() == ArchiveStats(0, 0, 0, 0, 0)


def test_publish_rejects_tampered_signed_graph_before_archive_mutation(tmp_path: Path) -> None:
    settings, _signer, _prepared, _rendered, bundle = _parts(tmp_path)
    archive = open_archive(settings)
    mutants = (
        replace(bundle, raw_csv=bundle.raw_csv + b"x"),
        replace(bundle, raw_manifest=bundle.raw_manifest + b"x"),
        replace(bundle, canonical_spec=b"{"),
        replace(bundle, canonical_spec=bundle.canonical_spec + b" "),
        replace(bundle, plotted_table=bundle.plotted_table + b"x"),
        replace(bundle, verdict=b"{"),
        replace(bundle, verdict=bundle.verdict + b" "),
        replace(bundle, vega_lite=bundle.vega_lite + b" "),
        replace(bundle, svg=b"\xff"),
        replace(bundle, vcert_payload=bundle.vcert_payload + b" "),
        replace(bundle, tool_versions=b"{"),
        replace(bundle, tool_versions=bundle.tool_versions + b" "),
        replace(bundle, vcert_envelope=bundle.vcert_envelope + b" "),
        replace(bundle, public_key=b"x" * 32),
    )
    for mutant in mutants:
        with pytest.raises(ArchiveIntegrityError):
            archive.publish_plot(mutant)
    assert archive.stats() == ArchiveStats(0, 0, 0, 0, 0)


def test_publish_rejects_archived_verdict_attempt_id(tmp_path: Path) -> None:
    settings, _signer, _prepared, _rendered, bundle = _parts(tmp_path)
    archive = open_archive(settings)
    verdict = archive_module._VERDICT_DECODER.decode(bundle.verdict)
    archived_verdict = archive_module._BUNDLE_ENCODER.encode(
        msgspec.structs.replace(verdict, attempt_id="f" * 64)
    )

    with pytest.raises(ArchiveIntegrityError, match="plot bundle verdict must omit attempt_id"):
        archive.publish_plot(replace(bundle, verdict=archived_verdict))
    assert archive.stats() == ArchiveStats(0, 0, 0, 0, 0)


def test_signed_but_cross_inconsistent_plot_components_fail_closed(tmp_path: Path) -> None:
    settings, signer, _prepared, rendered, bundle = _parts(tmp_path)
    archive = open_archive(settings)

    # Archive publication requires both the unauthenticated envelope hint and the independently
    # stored relation to agree, then separately requires that relation to address the key bytes.
    wrong_keyid = "sha256:" + "f" * 64
    with pytest.raises(ArchiveIntegrityError, match="failed verification"):
        archive.publish_plot(replace(bundle, keyid=wrong_keyid))

    wrong_key_relation = _resign_bundle(
        replace(bundle, keyid=wrong_keyid),
        signer,
        rendered.certificate,
        keyid=wrong_keyid,
    )
    with pytest.raises(ArchiveIntegrityError, match="keyid does not address"):
        archive.publish_plot(wrong_key_relation)

    noncanonical_payload = bundle.vcert_payload + b"\n"
    noncanonical = _resign_bundle(
        bundle,
        signer,
        rendered.certificate,
        payload=noncanonical_payload,
    )
    with pytest.raises(ArchiveIntegrityError, match="payload is not in the canonical"):
        archive.publish_plot(noncanonical)

    spec = decode_spec(bundle.canonical_spec)
    rebound_spec = msgspec.structs.replace(
        spec,
        dataset=msgspec.structs.replace(spec.dataset, hash="sha256:" + "f" * 64),
    )
    rebound_certificate = msgspec.structs.replace(
        rendered.certificate,
        spec_hash=canon.hash_spec(rebound_spec),
    )
    rebound = _resign_bundle(
        replace(bundle, canonical_spec=canon.spec_bytes(rebound_spec)),
        signer,
        rebound_certificate,
    )
    with pytest.raises(ArchiveIntegrityError, match="dataset binding disagrees"):
        archive.publish_plot(rebound)

    decoded_verdict = archive_module._VERDICT_DECODER.decode(bundle.verdict)
    invalid_outcomes = (
        Verdict(verified=False, layer="verify", results=decoded_verdict.results),
        Verdict(verified=True, layer="decode", results=decoded_verdict.results),
        Verdict(
            verified=True,
            layer="verify",
            results=(
                msgspec.structs.replace(decoded_verdict.results[0], status="fail"),
                *decoded_verdict.results[1:],
            ),
        ),
    )
    for invalid in invalid_outcomes:
        with pytest.raises(ArchiveIntegrityError, match="complete passing"):
            archive.publish_plot(
                replace(bundle, verdict=archive_module._BUNDLE_ENCODER.encode(invalid))
            )

    shortened = Verdict(
        verified=True,
        layer="verify",
        results=decoded_verdict.results[:-1],
    )
    with pytest.raises(ArchiveIntegrityError, match="verdict disagrees"):
        archive.publish_plot(
            replace(bundle, verdict=archive_module._BUNDLE_ENCODER.encode(shortened))
        )

    wrong_versions = msgspec.structs.replace(rendered.certificate.tcb, python="other")
    with pytest.raises(ArchiveIntegrityError, match="tool versions disagree"):
        archive.publish_plot(
            replace(bundle, tool_versions=archive_module._BUNDLE_ENCODER.encode(wrong_versions))
        )
    assert archive.stats() == ArchiveStats(0, 0, 0, 0, 0)


def test_publish_enforces_attestation_limits_before_signature_work(tmp_path: Path) -> None:
    settings, _signer, _prepared, _rendered, bundle = _parts(tmp_path)
    archive = open_archive(settings)
    payload_limit = msgspec.structs.replace(
        DEFAULT_LIMITS, max_attestation_bytes=len(bundle.vcert_payload) - 1
    )
    with pytest.raises(ArchiveReadLimitError, match="VCert payload"):
        archive.publish_plot(bundle, limits=payload_limit)

    envelope_limit = msgspec.structs.replace(
        DEFAULT_LIMITS,
        max_attestation_bytes=max(1, len(bundle.vcert_payload) // 2),
    )
    oversized_payload = replace(bundle, vcert_payload=b"")
    with pytest.raises(ArchiveReadLimitError, match="VCert envelope"):
        archive.publish_plot(oversized_payload, limits=envelope_limit)


def test_plot_record_and_reference_corruption_guards_cover_impossible_sql_shapes() -> None:
    plot_id = "a" * 64
    key = BlobWrite(BlobKind.ED25519_PUBLIC_KEY, b"k" * 32)
    certificate = BlobWrite(BlobKind.VCERT_ENVELOPE, b"certificate")
    with pytest.raises(ArchiveIntegrityError, match="record is malformed"):
        archive_module._validated_plot_record(None, plot_id)
    with pytest.raises(ArchiveIntegrityError, match="record types"):
        archive_module._validated_plot_record(
            (certificate.ref.digest, BlobKind.VCERT_ENVELOPE.value, key.ref.digest),
            plot_id,
        )

    def blob_row(blob_id: int, blob: BlobWrite) -> tuple[int, str, str, int]:
        return blob_id, blob.ref.digest, blob.kind.value, len(blob.payload)

    cert_row = blob_row(1, certificate)
    key_row = blob_row(2, key)
    role_blobs = {role: BlobWrite(BlobKind(role.value), role.value.encode()) for role in PlotRole}
    valid_references = [
        (role.value, *blob_row(index, role_blobs[role]))
        for index, role in enumerate(PlotRole, start=3)
    ]

    class Result:
        def __init__(self, *, one: object = None, many: list[tuple[object, ...]] | None = None):
            self.one = one
            self.many = [] if many is None else many

        def fetchone(self) -> object:
            return self.one

        def fetchall(self) -> list[tuple[object, ...]]:
            return self.many

    class FakeConnection:
        def __init__(self, mode: str):
            self.mode = mode

        def execute(self, statement: str, _parameters: object) -> Result:
            if statement == archive_module._SELECT_EXACT_BLOB:
                return Result(one=None if self.mode == "missing_relation" else cert_row)
            if statement == archive_module._SELECT_KEY_BLOB:
                if self.mode == "wrong_key":
                    return Result(
                        one=(2, "sha256:" + "b" * 64, BlobKind.ED25519_PUBLIC_KEY.value, 32)
                    )
                return Result(one=key_row)
            if statement == archive_module._SELECT_PLOT_REFERENCES:
                rows: list[tuple[object, ...]] = list(valid_references)
                if self.mode == "malformed_reference":
                    rows = [(PlotRole.RAW_CSV.value,)]
                elif self.mode == "unknown_role":
                    rows = [("unknown", *blob_row(3, role_blobs[PlotRole.RAW_CSV]))]
                elif self.mode == "wrong_kind":
                    rows = [
                        (
                            PlotRole.RAW_CSV.value,
                            *blob_row(3, role_blobs[PlotRole.RAW_MANIFEST]),
                        )
                    ]
                elif self.mode == "duplicate_role":
                    rows = [valid_references[0], valid_references[0]]
                elif self.mode == "missing_role":
                    rows.pop()
                return Result(many=rows)
            raise AssertionError(statement)

    cases = (
        ("missing_relation", "relation is broken"),
        ("wrong_key", "resolves to the wrong typed blob"),
        ("malformed_reference", "reference row is malformed"),
        ("unknown_role", "unknown role"),
        ("wrong_kind", "wrong-kind or duplicate"),
        ("duplicate_role", "wrong-kind or duplicate"),
        ("missing_role", "every required role"),
    )
    for mode, message in cases:
        with pytest.raises(ArchiveIntegrityError, match=message):
            archive_module._plot_bundle_blob_rows(
                cast("sqlite3.Connection", FakeConnection(mode)),
                plot_id,
                certificate.ref,
                key.ref.digest,
            )


def test_complete_plot_read_normalizes_sqlite_fault(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, _signer, _prepared, _rendered, bundle = _parts(tmp_path)
    archive = open_archive(settings)

    def fail_read(*_args: object, **_kwargs: object) -> PlotBundle:
        msg = "read fault"
        raise sqlite3.DatabaseError(msg)

    monkeypatch.setattr(archive_module, "_read_complete_plot_bundle", fail_read)
    with pytest.raises(archive_module.ArchiveError, match="complete plot bundle"):
        archive.read_plot(bundle.plot_id, max_bytes=_bundle_bytes(bundle))


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("count_type", "do not each resolve"),
        ("count_mismatch", "do not each resolve"),
        ("row_type", "relation row is malformed"),
        ("row_size", "relation row is malformed"),
        ("plot_address", "plot address is corrupt"),
        ("wrong_kind", "wrong byte kind"),
    ],
)
def test_version_one_migration_rejects_corrupt_spec_index_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fault: str,
    message: str,
) -> None:
    settings, _signer, _prepared, _rendered, bundle = _parts(tmp_path)
    archive = open_archive(settings)
    archive.publish_plot(bundle, limits=settings.limits)
    connection = sqlite3.connect(archive.database_path, autocommit=True)
    try:
        connection.execute("DROP INDEX attempts_by_plot")
        connection.execute("DROP TABLE specs")
        connection.execute("UPDATE meta SET schema_version = 1 WHERE singleton = 1")
        connection.execute("PRAGMA user_version=1")
    finally:
        connection.close()

    class MigrationResult:
        def __init__(self, rows: list[object]) -> None:
            self._rows = rows

        def fetchall(self) -> list[object]:
            return self._rows

    class MigrationConnection:
        def __init__(self, raw: sqlite3.Connection) -> None:
            self._raw = raw

        def execute(
            self, statement: str, parameters: tuple[object, ...] = ()
        ) -> sqlite3.Cursor | MigrationResult:
            cursor = self._raw.execute(statement, parameters)
            if statement != archive_module._SELECT_MIGRATION_SPECS:
                return cursor
            rows: list[object] = list(cursor.fetchall())
            row = cast("tuple[object, ...]", rows[0])
            if fault == "row_type":
                rows[0] = list(row)
            elif fault == "row_size":
                rows[0] = (row[0],)
            elif fault == "plot_address":
                rows[0] = (1, *row[1:])
            elif fault == "wrong_kind":
                rows[0] = (*row[:3], BlobKind.RAW_CSV.value, row[4])
            return MigrationResult(rows)

        def blobopen(self, *args: Any, **kwargs: Any) -> sqlite3.Blob:
            return self._raw.blobopen(*args, **kwargs)

    real_read_scalar = archive_module._read_scalar

    def corrupt_plot_count(raw: sqlite3.Connection, statement: str) -> object:
        value = real_read_scalar(raw, statement)
        if statement != "SELECT COUNT(*) FROM plots":
            return value
        if fault == "count_type":
            return "corrupt"
        assert type(value) is int
        return value + 1

    if fault.startswith("count_"):
        monkeypatch.setattr(archive_module, "_read_scalar", corrupt_plot_count)

    connection = sqlite3.connect(archive.database_path, autocommit=True)
    connection.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(ArchiveIntegrityError, match=message):
            archive_module._migrate_v1_to_v2(
                cast("sqlite3.Connection", MigrationConnection(connection)),
                max_spec_bytes=len(bundle.canonical_spec),
            )
    finally:
        connection.rollback()
        connection.close()


def test_public_record_rows_and_exact_key_size_fail_closed() -> None:
    keyid = "sha256:" + "a" * 64
    spec_id = "b" * 64
    spec_digest = "sha256:" + "c" * 64

    for malformed_key_row in (None, (keyid,)):
        with pytest.raises(ArchiveIntegrityError, match="signing-key record is malformed"):
            archive_module._validated_key_record(malformed_key_row, keyid)
    for wrong_key_row in (
        ("sha256:" + "d" * 64, BlobKind.ED25519_PUBLIC_KEY.value),
        (keyid, BlobKind.RAW_CSV.value),
    ):
        with pytest.raises(ArchiveIntegrityError, match="wrong address or byte kind"):
            archive_module._validated_key_record(wrong_key_row, keyid)

    for malformed_spec_row in (None, (spec_digest,)):
        with pytest.raises(ArchiveIntegrityError, match="spec record is malformed"):
            archive_module._validated_spec_record(malformed_spec_row, spec_id)
    for wrong_spec_row in (
        (1, BlobKind.CANONICAL_SPEC.value),
        ("not-a-digest", BlobKind.CANONICAL_SPEC.value),
        (spec_digest, BlobKind.RAW_CSV.value),
    ):
        with pytest.raises(ArchiveIntegrityError, match="wrong address or byte kind"):
            archive_module._validated_spec_record(wrong_spec_row, spec_id)

    short_key_row = (1, keyid, BlobKind.ED25519_PUBLIC_KEY.value, 31)
    with pytest.raises(ArchiveIntegrityError, match="exactly 32 bytes"):
        archive_module._admit_blob_row(
            short_key_row,
            max_bytes=32,
            subject="Ed25519 public key",
            exact_bytes=32,
        )


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("certificate_blob", "certificate relation is broken"),
        ("key_record", "signing-key relation is broken"),
        ("key_blob", "signing-key blob is absent"),
    ],
)
def test_certificate_read_rejects_absent_related_rows(
    tmp_path: Path, fault: str, message: str
) -> None:
    settings, _signer, _prepared, _rendered, bundle = _parts(tmp_path)
    archive = open_archive(settings)
    archive.publish_plot(bundle, limits=settings.limits)
    connection = sqlite3.connect(archive.database_path, autocommit=True)
    try:
        if fault != "key_record":
            connection.execute("DROP TRIGGER blobs_reject_delete")
        if fault == "certificate_blob":
            connection.execute(
                "DELETE FROM blobs WHERE digest = ? AND kind = ?",
                (f"sha256:{bundle.plot_id}", BlobKind.VCERT_ENVELOPE.value),
            )
        elif fault == "key_record":
            connection.execute("DELETE FROM keys WHERE keyid = ?", (bundle.keyid,))
        else:
            connection.execute(
                "DELETE FROM blobs WHERE digest = ? AND kind = ?",
                (bundle.keyid, BlobKind.ED25519_PUBLIC_KEY.value),
            )
        if fault != "key_record":
            connection.execute(archive_module._CREATE_BLOB_DELETE_GUARD)
    finally:
        connection.close()

    with pytest.raises(ArchiveIntegrityError, match=message):
        archive.read_certificate(
            bundle.plot_id,
            max_bytes=len(bundle.vcert_envelope),
            limits=settings.limits,
        )
    if fault == "key_blob":
        with pytest.raises(ArchiveIntegrityError, match="public-key relation is broken"):
            archive.read_key(bundle.keyid, max_bytes=len(bundle.public_key))


def test_public_reads_normalize_sqlite_faults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, _signer, _prepared, rendered, bundle = _parts(tmp_path)
    archive = open_archive(settings)
    archive.publish_plot(bundle, limits=settings.limits)
    spec_id = rendered.certificate.spec_hash.removeprefix("sha256:")

    def fail_blob_lookup(*_args: object, **_kwargs: object) -> None:
        msg = "public read fault"
        raise sqlite3.DatabaseError(msg)

    monkeypatch.setattr(archive_module, "_blob_row", fail_blob_lookup)
    with pytest.raises(archive_module.ArchiveError, match="public-certificate read"):
        archive.read_certificate(
            bundle.plot_id,
            max_bytes=len(bundle.vcert_envelope),
            limits=settings.limits,
        )
    with pytest.raises(archive_module.ArchiveError, match="public-spec read"):
        archive.read_spec(spec_id, max_bytes=len(bundle.canonical_spec))
    with pytest.raises(archive_module.ArchiveError, match="public-key read"):
        archive.read_key(bundle.keyid, max_bytes=len(bundle.public_key))


def test_public_key_read_rechecks_parse_and_address(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, _signer, _prepared, _rendered, bundle = _parts(tmp_path)
    archive = open_archive(settings)
    archive.publish_plot(bundle, limits=settings.limits)

    class RejectingPublicKey:
        @staticmethod
        def from_public_bytes(_payload: bytes) -> None:
            msg = "invalid key"
            raise ValueError(msg)

    with monkeypatch.context() as patch:
        patch.setattr(archive_module, "Ed25519PublicKey", RejectingPublicKey)
        with pytest.raises(ArchiveIntegrityError, match="not a raw Ed25519 public key"):
            archive.read_key(bundle.keyid, max_bytes=len(bundle.public_key))

    def wrong_keyid(_payload: bytes) -> str:
        return "sha256:" + "f" * 64

    with monkeypatch.context() as patch:
        patch.setattr(archive_module, "keyid_for_public_key", wrong_keyid)
        with pytest.raises(ArchiveIntegrityError, match="does not address"):
            archive.read_key(bundle.keyid, max_bytes=len(bundle.public_key))
