# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M5.4b successful-plot materialization, signed hash graph, and archive round-trip."""

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
) -> PlotBundle:
    if payload is None:
        payload = render.vcert_bytes(certificate)
    signature = signer.private_key.sign(attestation.pae(attestation.VCERT_PAYLOAD_TYPE, payload))
    envelope = attestation._encode_envelope(payload, signature, signer.keyid)
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


def test_signed_but_cross_inconsistent_plot_components_fail_closed(tmp_path: Path) -> None:
    settings, signer, _prepared, rendered, bundle = _parts(tmp_path)
    archive = open_archive(settings)

    # keyid is a lookup hint during DSSE verification; the bundle additionally requires it to
    # content-address the actual verifying key.
    wrong_keyid = replace(bundle, keyid="sha256:" + "f" * 64)
    with pytest.raises(ArchiveIntegrityError, match="keyid does not address"):
        archive.publish_plot(wrong_keyid)

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
