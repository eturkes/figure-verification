# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M5.4d signed occurrence manifests, collision safety, and atomic archive round-trips."""

import hashlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, cast

import msgspec
import pytest

from verifier import attestation, render
from verifier.errors import VerificationError
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.service import archive as archive_module
from verifier.service import pipeline
from verifier.service.archive import (
    ATTEMPT_PAYLOAD_TYPE,
    ArchiveCollisionError,
    ArchiveIntegrityError,
    ArchiveNotFoundError,
    ArchiveReadLimitError,
    AttemptArtifacts,
    AttemptBundle,
    AttemptDraft,
    AttemptManifest,
    AttemptOutcome,
    AttemptRole,
    AttemptRoute,
    BlobBinding,
    BlobKind,
    BlobWrite,
    PlotBundle,
    materialize_attempt_bundle,
    materialize_plot_bundle,
    open_archive,
)
from verifier.service.identity import Signer, load_identity
from verifier.service.settings import Settings

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_RAW_SPEC = (_ROOT / "examples/good_specs/g01_total_revenue_by_month.json").read_bytes()
_TIME = datetime(2026, 7, 17, 3, 4, 5, 678901, tzinfo=UTC)
_ENCODER = msgspec.json.Encoder(order="deterministic")


def _plot_parts(tmp_path: Path) -> tuple[Settings, Signer, PlotBundle]:
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
    plot = materialize_plot_bundle(prepared, rendered, envelope, signer, limits=settings.limits)
    return settings, signer, plot


def _success_draft(plot: PlotBundle, *, route: AttemptRoute) -> AttemptDraft:
    model = (
        {}
        if route is AttemptRoute.VERIFY_AND_RENDER
        else {
            "model_request": b'{"messages":[{"role":"user","content":"plot"}]}',
            "model_response": b'{"choices":[{"message":{"content":"spec"}}]}',
            "model_reply": _RAW_SPEC,
        }
    )
    return AttemptDraft(
        occurred_at=_TIME,
        route=route,
        http_status=200,
        outcome=AttemptOutcome.VERIFIED,
        artifacts=AttemptArtifacts(
            raw_csv=plot.raw_csv,
            raw_manifest=plot.raw_manifest,
            raw_spec=_RAW_SPEC,
            verdict=plot.verdict,
            **model,
        ),
        plot=plot,
    )


def _rejected_draft(settings: Settings, *, route: AttemptRoute) -> AttemptDraft:
    raw = b"{"
    verdict = _ENCODER.encode(pipeline.verify_only(raw, settings).verdict)
    model = (
        {}
        if route is AttemptRoute.VERIFY_AND_RENDER
        else {
            "model_request": b'{"messages":[]}',
            "model_response": b'{"choices":[{"message":{"content":"{"}}]}',
            "model_reply": raw,
        }
    )
    return AttemptDraft(
        occurred_at=_TIME,
        route=route,
        http_status=200,
        outcome=AttemptOutcome.REJECTED,
        artifacts=AttemptArtifacts(raw_spec=raw, verdict=verdict, **model),
    )


def _bundle_size(bundle: AttemptBundle) -> int:
    batch = archive_module._attempt_bundle_batch(bundle)
    return sum(len(blob.payload) for blob in archive_module._unique_blob_writes(batch.blobs))


def _resign(
    bundle: AttemptBundle,
    signer: Signer,
    manifest: AttemptManifest,
    *,
    payload: bytes | None = None,
    payload_type: str = ATTEMPT_PAYLOAD_TYPE,
) -> AttemptBundle:
    if payload is None:
        payload = _ENCODER.encode(manifest)
    envelope = attestation.sign_dsse(
        payload,
        signer.private_key,
        keyid=signer.keyid,
        payload_type=payload_type,
        max_payload_bytes=DEFAULT_LIMITS.max_attestation_bytes,
    )
    return replace(
        bundle,
        attempt_id=hashlib.sha256(envelope).hexdigest(),
        manifest=manifest,
        attempt_payload=payload,
        attempt_envelope=envelope,
    )


def test_success_manifest_binds_every_observed_and_plot_blob_then_round_trips(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, signer, plot = _plot_parts(tmp_path)
    archive = open_archive(settings)
    nonces = iter(("0" * 32, "1" * 32))
    monkeypatch.setattr(archive_module, "_attempt_nonce", lambda: next(nonces))
    draft = _success_draft(plot, route=AttemptRoute.VERIFY_AND_RENDER)

    first = archive.record_attempt(draft, signer, limits=settings.limits)
    assert first.attempt_id == hashlib.sha256(first.attempt_envelope).hexdigest()
    assert first.manifest.nonce == "0" * 32
    assert first.manifest.occurred_at == "2026-07-17T03:04:05.678901Z"
    assert first.manifest.plot_id == plot.plot_id
    assert [binding.role for binding in first.manifest.artifacts] == [
        BlobKind.RAW_CSV,
        BlobKind.RAW_MANIFEST,
        BlobKind.RAW_SPEC,
        BlobKind.VERDICT,
    ]
    assert [binding.role for binding in first.manifest.plot_artifacts] == [
        role for role, _name in archive_module._PLOT_BINDING_FIELDS
    ]
    assert len(first.manifest.plot_artifacts) == 11
    assert b"attempt_id" not in first.attempt_payload
    assert _ENCODER.encode(first.manifest) == first.attempt_payload
    verified = attestation.verify_dsse(
        first.attempt_envelope,
        {signer.keyid: signer.public_key},
        payload_type=ATTEMPT_PAYLOAD_TYPE,
        max_payload_bytes=settings.limits.max_attestation_bytes,
    )
    assert verified.payload is not first.attempt_payload
    assert verified.payload == first.attempt_payload

    size = _bundle_size(first)
    assert archive.read_attempt(first.attempt_id, max_bytes=size, limits=settings.limits) == first
    reopened = open_archive(settings)
    assert reopened.read_attempt(first.attempt_id, max_bytes=size) == first
    assert reopened.read_attempt_envelope(
        first.attempt_id, max_bytes=len(first.attempt_envelope)
    ) == (first.attempt_envelope)
    for role, field_name in archive_module._ATTEMPT_ARTIFACT_FIELDS:
        value = cast("bytes | None", getattr(first.artifacts, field_name))
        if value is not None:
            assert reopened.read_attempt_blob(first.attempt_id, role, max_bytes=len(value)) == value
    assert (
        reopened.read_attempt_blob(
            first.attempt_id,
            AttemptRole.ATTEMPT_PAYLOAD,
            max_bytes=len(first.attempt_payload),
        )
        == first.attempt_payload
    )

    before = archive.stats()
    second = archive.record_attempt(draft, signer, limits=settings.limits)
    after = archive.stats()
    assert second.attempt_id != first.attempt_id
    assert second.manifest.nonce == "1" * 32
    assert after.attempts == before.attempts + 1
    assert after.plots == before.plots
    assert after.blobs == before.blobs + 2
    assert after.logical_blob_bytes - before.logical_blob_bytes == (
        len(second.attempt_payload) + len(second.attempt_envelope)
    )


def test_failure_bundle_omits_unavailable_inputs_and_round_trips_without_plot(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    signer = load_identity(settings).signer
    archive = open_archive(settings)
    draft = _rejected_draft(settings, route=AttemptRoute.VERIFY_AND_RENDER)
    bundle = materialize_attempt_bundle(draft, signer, nonce="a" * 32)
    archive.publish_attempt(bundle)

    assert bundle.plot is None
    assert bundle.manifest.plot_id is None
    assert bundle.manifest.plot_artifacts == ()
    assert [binding.role for binding in bundle.manifest.artifacts] == [
        BlobKind.RAW_SPEC,
        BlobKind.VERDICT,
    ]
    assert bundle.artifacts.raw_csv is None
    assert bundle.artifacts.model_request is None
    assert archive.read_attempt(bundle.attempt_id, max_bytes=_bundle_size(bundle)) == bundle
    assert archive.stats().plots == 0
    with pytest.raises(ArchiveNotFoundError):
        archive.read_attempt("f" * 64, max_bytes=1)


@pytest.mark.parametrize(
    ("outcome", "artifacts", "status"),
    [
        (AttemptOutcome.DATASET_NOT_FOUND, AttemptArtifacts(), 404),
        (AttemptOutcome.PROPOSER_POLICY, AttemptArtifacts(), 422),
        (
            AttemptOutcome.DATASET_MISMATCH,
            AttemptArtifacts(
                raw_spec=b"spec",
                model_request=b"request",
                model_response=b"response",
                model_reply=b"spec",
            ),
            502,
        ),
        (AttemptOutcome.MODEL_TRANSPORT, AttemptArtifacts(model_request=b"request"), 503),
        (
            AttemptOutcome.MODEL_CONTENT_ENCODING,
            AttemptArtifacts(model_request=b"request"),
            502,
        ),
        (
            AttemptOutcome.MODEL_RESPONSE_TOO_LARGE,
            AttemptArtifacts(model_request=b"request"),
            502,
        ),
        (
            AttemptOutcome.MODEL_HTTP_STATUS,
            AttemptArtifacts(model_request=b"request", model_response=b"response"),
            502,
        ),
        (
            AttemptOutcome.MODEL_PROMPT_TOKENS,
            AttemptArtifacts(model_request=b"request", model_response=b"response"),
            422,
        ),
        (
            AttemptOutcome.MODEL_INVALID_ENVELOPE,
            AttemptArtifacts(model_request=b"request", model_response=b"response"),
            502,
        ),
        (
            AttemptOutcome.MODEL_NO_CHOICES,
            AttemptArtifacts(model_request=b"request", model_response=b"response"),
            502,
        ),
        (
            AttemptOutcome.MODEL_EMPTY_CONTENT,
            AttemptArtifacts(model_request=b"request", model_response=b"response"),
            502,
        ),
    ],
)
def test_proposer_problem_outcome_matrix_has_exact_status_and_trace_shape(
    tmp_path: Path,
    outcome: AttemptOutcome,
    artifacts: AttemptArtifacts,
    status: int,
) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    signer = load_identity(settings).signer
    draft = AttemptDraft(
        occurred_at=datetime(
            2026,
            7,
            17,
            12,
            4,
            5,
            678901,
            tzinfo=timezone(timedelta(hours=9)),
        ),
        route=AttemptRoute.PROPOSE_SPEC,
        http_status=status,
        outcome=outcome,
        artifacts=artifacts,
    )
    bundle = materialize_attempt_bundle(draft, signer, nonce="b" * 32)
    assert bundle.manifest.http_status == status
    assert bundle.manifest.occurred_at == "2026-07-17T03:04:05.678901Z"
    assert bundle.manifest.plot_id is None
    assert {binding.role for binding in bundle.manifest.artifacts} == {
        BlobKind(role.value)
        for role, name in archive_module._ATTEMPT_ARTIFACT_FIELDS
        if getattr(artifacts, name) is not None
    }


def test_proposer_verified_and_rejected_outcomes_bind_lossless_model_exchange(
    tmp_path: Path,
) -> None:
    settings, signer, plot = _plot_parts(tmp_path)
    for index, draft in enumerate(
        (
            _success_draft(plot, route=AttemptRoute.PROPOSE_SPEC),
            _rejected_draft(settings, route=AttemptRoute.PROPOSE_SPEC),
        ),
        start=1,
    ):
        bundle = materialize_attempt_bundle(draft, signer, nonce=f"{index:032x}")
        assert bundle.artifacts.model_reply is bundle.artifacts.raw_spec
        assert {binding.role for binding in bundle.manifest.artifacts}.issuperset(
            {BlobKind.MODEL_REQUEST, BlobKind.MODEL_RESPONSE, BlobKind.MODEL_REPLY}
        )


def test_collision_retries_are_bounded_and_never_alias_occurrences(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    generated_nonce = archive_module._attempt_nonce()
    assert len(generated_nonce) == 32
    int(generated_nonce, 16)
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    signer = load_identity(settings).signer
    archive = open_archive(settings)
    draft = _rejected_draft(settings, route=AttemptRoute.VERIFY_AND_RENDER)
    first = materialize_attempt_bundle(draft, signer, nonce="0" * 32)
    archive.publish_attempt(first)
    with pytest.raises(ArchiveCollisionError, match="already exists"):
        archive.publish_attempt(first)

    nonces = iter(("0" * 32, "1" * 32))
    monkeypatch.setattr(archive_module, "_attempt_nonce", lambda: next(nonces))
    second = archive.record_attempt(draft, signer)
    assert second.manifest.nonce == "1" * 32
    assert second.attempt_id != first.attempt_id

    before = archive.stats()
    monkeypatch.setattr(archive_module, "_attempt_nonce", lambda: "0" * 32)
    with pytest.raises(ArchiveCollisionError, match="exhausted 3"):
        archive.record_attempt(draft, signer)
    assert archive.stats() == before


def test_plot_and_attempt_publish_roll_back_together_on_final_commit_fault(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, signer, plot = _plot_parts(tmp_path)
    archive = open_archive(settings)
    bundle = materialize_attempt_bundle(
        _success_draft(plot, route=AttemptRoute.VERIFY_AND_RENDER),
        signer,
        nonce="c" * 32,
    )

    class InjectedError(Exception):
        pass

    def fail() -> None:
        raise InjectedError

    monkeypatch.setattr(archive_module, "_before_archive_commit", fail)
    with pytest.raises(InjectedError):
        archive.publish_attempt(bundle)
    assert archive.stats() == archive_module.ArchiveStats(0, 0, 0, 0, 0)


def test_complete_attempt_read_admits_aggregate_bytes_before_opening_any_blob(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, signer, plot = _plot_parts(tmp_path)
    archive = open_archive(settings)
    bundle = materialize_attempt_bundle(
        _success_draft(plot, route=AttemptRoute.VERIFY_AND_RENDER),
        signer,
        nonce="d" * 32,
    )
    archive.publish_attempt(bundle)
    size = _bundle_size(bundle)

    class TrackingConnection(sqlite3.Connection):
        blob_opens = 0

        def blobopen(self, *args: Any, **kwargs: Any) -> sqlite3.Blob:
            type(self).blob_opens += 1
            return super().blobopen(*args, **kwargs)

    monkeypatch.setattr(archive_module, "_CONNECTION_FACTORY", TrackingConnection)
    with pytest.raises(ArchiveReadLimitError, match="aggregate read limit"):
        archive.read_attempt(bundle.attempt_id, max_bytes=size - 1)
    assert TrackingConnection.blob_opens == 0
    assert archive.read_attempt(bundle.attempt_id, max_bytes=size) == bundle
    assert TrackingConnection.blob_opens == len(
        archive_module._unique_blob_writes(archive_module._attempt_bundle_batch(bundle).blobs)
    )


def test_tampered_signature_roles_bytes_and_cross_bundle_edges_fail_before_mutation(
    tmp_path: Path,
) -> None:
    _settings, signer, plot = _plot_parts(tmp_path)
    base = materialize_attempt_bundle(
        _success_draft(plot, route=AttemptRoute.VERIFY_AND_RENDER),
        signer,
        nonce="e" * 32,
    )
    duplicate_role_manifest = msgspec.structs.replace(
        base.manifest,
        artifacts=(
            base.manifest.artifacts[0],
            msgspec.structs.replace(
                base.manifest.artifacts[1], role=base.manifest.artifacts[0].role
            ),
            *base.manifest.artifacts[2:],
        ),
    )
    wrong_status = _resign(
        base,
        signer,
        msgspec.structs.replace(base.manifest, http_status=201),
    )
    noncanonical_payload = base.attempt_payload + b"\n"
    mutants = (
        replace(base, attempt_id="f" * 64),
        replace(base, attempt_envelope=base.attempt_envelope + b" "),
        replace(base, attempt_payload=base.attempt_payload + b" "),
        replace(base, public_key=b"x" * 32),
        replace(base, manifest=msgspec.structs.replace(base.manifest, nonce="f" * 32)),
        replace(
            base,
            artifacts=replace(
                base.artifacts,
                raw_spec=cast("bytes", base.artifacts.raw_spec) + b" ",
            ),
        ),
        replace(base, plot=replace(plot, svg=plot.svg + b" ")),
        _resign(base, signer, duplicate_role_manifest),
        wrong_status,
        _resign(base, signer, base.manifest, payload=noncanonical_payload),
        _resign(base, signer, base.manifest, payload_type="application/example+json"),
    )
    for index, mutant in enumerate(mutants):
        archive = open_archive(Settings(data_dir=_DATA, state_dir=tmp_path / f"mutant-{index}"))
        with pytest.raises(ArchiveIntegrityError):
            archive.publish_attempt(mutant)
        assert archive.stats() == archive_module.ArchiveStats(0, 0, 0, 0, 0)


def test_wrong_signer_verdict_trace_and_version_relationships_fail_closed(tmp_path: Path) -> None:
    settings, signer, plot = _plot_parts(tmp_path)
    success = _success_draft(plot, route=AttemptRoute.VERIFY_AND_RENDER)
    rotated_settings = Settings(
        data_dir=_DATA,
        state_dir=settings.state_dir,
        signing_key_file=settings.state_dir / "rotated.key",
    )
    rotated = load_identity(rotated_settings).signer
    with pytest.raises(ArchiveIntegrityError, match="plot signer"):
        materialize_attempt_bundle(success, rotated, nonce="1" * 32)

    invalid_drafts = (
        replace(success, artifacts=replace(success.artifacts, raw_csv=b"other")),
        replace(success, artifacts=replace(success.artifacts, verdict=None)),
        replace(success, artifacts=replace(success.artifacts, raw_spec=None)),
        replace(success, plot=None),
        replace(success, http_status=201),
        replace(success, outcome=AttemptOutcome.REJECTED),
    )
    for index, draft in enumerate(invalid_drafts, start=2):
        with pytest.raises(ArchiveIntegrityError):
            materialize_attempt_bundle(draft, signer, nonce=f"{index:032x}")

    wrong_version_manifest = replace(cast("PlotBundle", success.plot), tool_versions=b"{}")
    with pytest.raises(ArchiveIntegrityError):
        materialize_attempt_bundle(
            replace(success, plot=wrong_version_manifest), signer, nonce="9" * 32
        )


def test_attempt_api_runtime_types_and_attestation_limits(tmp_path: Path) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    signer = load_identity(settings).signer
    draft = _rejected_draft(settings, route=AttemptRoute.VERIFY_AND_RENDER)
    bundle = materialize_attempt_bundle(draft, signer, nonce="f" * 32)
    archive = open_archive(settings)

    with pytest.raises(TypeError, match="draft must"):
        materialize_attempt_bundle(cast("AttemptDraft", object()), signer, nonce="0" * 32)
    with pytest.raises(TypeError, match="signer must"):
        materialize_attempt_bundle(draft, cast("Signer", object()), nonce="0" * 32)
    with pytest.raises(TypeError, match="limits must"):
        materialize_attempt_bundle(
            draft,
            signer,
            nonce="0" * 32,
            limits=cast("VerificationLimits", object()),
        )
    for malformed in (
        replace(draft, route=cast("AttemptRoute", "bad")),
        replace(draft, outcome=cast("AttemptOutcome", "bad")),
        replace(draft, artifacts=cast("AttemptArtifacts", object())),
        replace(draft, plot=cast("PlotBundle", object())),
    ):
        with pytest.raises(TypeError):
            materialize_attempt_bundle(malformed, signer, nonce="0" * 32)
    with pytest.raises(ValueError, match="timezone-aware"):
        materialize_attempt_bundle(
            replace(
                draft,
                occurred_at=datetime(2026, 7, 17),  # noqa: DTZ001 - hostile naive input
            ),
            signer,
            nonce="0" * 32,
        )
    with pytest.raises(ArchiveIntegrityError, match="128 bits"):
        materialize_attempt_bundle(draft, signer, nonce="bad")
    with pytest.raises(TypeError, match="AttemptBundle"):
        archive.publish_attempt(cast("AttemptBundle", object()))
    with pytest.raises(ValueError, match="attempt_id"):
        archive.read_attempt("bad", max_bytes=1)
    with pytest.raises(ValueError, match="max_bytes"):
        archive.read_attempt(bundle.attempt_id, max_bytes=-1)
    with pytest.raises(TypeError, match="limits must"):
        archive.read_attempt(
            bundle.attempt_id,
            max_bytes=_bundle_size(bundle),
            limits=cast("VerificationLimits", object()),
        )

    payload_limit = msgspec.structs.replace(
        DEFAULT_LIMITS, max_attestation_bytes=len(bundle.attempt_payload) - 1
    )
    with pytest.raises(ArchiveReadLimitError, match="attempt payload"):
        archive.publish_attempt(bundle, limits=payload_limit)
    envelope_limit = msgspec.structs.replace(DEFAULT_LIMITS, max_attestation_bytes=1)
    oversized_envelope = b"x" * (
        attestation.envelope_byte_limit(1, payload_type=ATTEMPT_PAYLOAD_TYPE) + 1
    )
    with pytest.raises(ArchiveReadLimitError, match="attempt envelope"):
        archive.publish_attempt(
            replace(
                bundle,
                attempt_id=hashlib.sha256(oversized_envelope).hexdigest(),
                attempt_payload=b"",
                attempt_envelope=oversized_envelope,
            ),
            limits=envelope_limit,
        )


def test_attempt_wire_constructors_and_manifest_validation_reject_hostile_runtime_shapes(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    signer = load_identity(settings).signer
    draft = _rejected_draft(settings, route=AttemptRoute.VERIFY_AND_RENDER)
    base = materialize_attempt_bundle(draft, signer, nonce="1" * 32)

    with pytest.raises(TypeError, match="bytes or None"):
        AttemptArtifacts(raw_csv=cast("bytes", "bad"))
    with pytest.raises(ValueError, match="bundle id"):
        replace(base, attempt_id="bad")
    with pytest.raises(ValueError, match="bundle keyid"):
        replace(base, keyid="bad")
    constructor_mutants = (
        {"manifest": cast("AttemptManifest", object())},
        {"artifacts": cast("AttemptArtifacts", object())},
        {"plot": cast("PlotBundle", object())},
        {"attempt_payload": cast("bytes", "bad")},
        {"attempt_envelope": cast("bytes", "bad")},
        {"public_key": cast("bytes", "bad")},
    )
    for fields in constructor_mutants:
        with pytest.raises(TypeError, match="attempt bundle"):
            replace(base, **fields)

    manifest = base.manifest
    malformed_manifests = (
        msgspec.structs.replace(manifest, version=cast('Literal["attempt-0.1"]', "other")),
        msgspec.structs.replace(manifest, occurred_at="bad"),
        msgspec.structs.replace(manifest, occurred_at="2026-99-99T03:04:05.678901Z"),
        msgspec.structs.replace(manifest, route=cast("AttemptRoute", "bad")),
        msgspec.structs.replace(manifest, outcome=cast("AttemptOutcome", "bad")),
        msgspec.structs.replace(manifest, plot_id="bad"),
        msgspec.structs.replace(manifest, keyid="bad"),
        msgspec.structs.replace(manifest, verifier_version=""),
        msgspec.structs.replace(manifest, verifier_version="\ud800"),
        msgspec.structs.replace(manifest, verifier_version="v" * 129),
        msgspec.structs.replace(
            manifest,
            artifacts=cast("tuple[BlobBinding, ...]", [*manifest.artifacts]),
        ),
        msgspec.structs.replace(
            manifest,
            artifacts=(cast("BlobBinding", object()),),
        ),
        msgspec.structs.replace(
            manifest,
            artifacts=(
                msgspec.structs.replace(manifest.artifacts[0], role=cast("BlobKind", "bad")),
            ),
        ),
        msgspec.structs.replace(
            manifest,
            artifacts=(msgspec.structs.replace(manifest.artifacts[0], digest="bad"),),
        ),
    )
    for mutant in malformed_manifests:
        with pytest.raises(ArchiveIntegrityError):
            archive_module._validate_attempt_manifest_shape(mutant)
    with pytest.raises(TypeError, match="AttemptManifest"):
        archive_module._validate_attempt_manifest_shape(cast("AttemptManifest", object()))


def test_attempt_outcome_and_authenticated_cross_edge_guards_are_independently_pinned(
    tmp_path: Path,
) -> None:
    settings, signer, plot = _plot_parts(tmp_path)
    rejected = materialize_attempt_bundle(
        _rejected_draft(settings, route=AttemptRoute.VERIFY_AND_RENDER),
        signer,
        nonce="2" * 32,
    )
    with pytest.raises(ArchiveIntegrityError, match="direct render"):
        archive_module._expected_model_roles(
            msgspec.structs.replace(
                rejected.manifest,
                outcome=AttemptOutcome.DATASET_NOT_FOUND,
                http_status=404,
            )
        )
    with pytest.raises(ArchiveIntegrityError, match="model trace presence"):
        archive_module._validate_attempt_outcome(
            replace(
                rejected,
                artifacts=replace(rejected.artifacts, model_request=b"invented"),
            )
        )

    proposed = materialize_attempt_bundle(
        _rejected_draft(settings, route=AttemptRoute.PROPOSE_SPEC),
        signer,
        nonce="3" * 32,
    )
    with pytest.raises(ArchiveIntegrityError, match="reply differs"):
        archive_module._validate_attempt_outcome(
            replace(proposed, artifacts=replace(proposed.artifacts, model_reply=b"other"))
        )

    success = materialize_attempt_bundle(
        _success_draft(plot, route=AttemptRoute.VERIFY_AND_RENDER),
        signer,
        nonce="4" * 32,
    )
    with pytest.raises(ArchiveIntegrityError, match="judgement disagrees"):
        archive_module._validate_attempt_outcome(
            replace(
                success, artifacts=replace(success.artifacts, verdict=rejected.artifacts.verdict)
            )
        )
    problem_draft = AttemptDraft(
        occurred_at=_TIME,
        route=AttemptRoute.PROPOSE_SPEC,
        http_status=404,
        outcome=AttemptOutcome.DATASET_NOT_FOUND,
        artifacts=AttemptArtifacts(),
    )
    problem = materialize_attempt_bundle(problem_draft, signer, nonce="5" * 32)
    with pytest.raises(ArchiveIntegrityError, match="cannot invent"):
        archive_module._validate_attempt_outcome(
            replace(problem, artifacts=replace(problem.artifacts, raw_csv=b"invented"))
        )

    wrong_keyid = "sha256:" + "f" * 64
    with pytest.raises(ArchiveIntegrityError, match="keyid does not address"):
        archive_module._validate_attempt_bundle(
            replace(rejected, keyid=wrong_keyid), DEFAULT_LIMITS
        )

    invalid_payload = b"[]"
    invalid_envelope = attestation.sign_dsse(
        invalid_payload,
        signer.private_key,
        keyid=signer.keyid,
        payload_type=ATTEMPT_PAYLOAD_TYPE,
        max_payload_bytes=DEFAULT_LIMITS.max_attestation_bytes,
    )
    with pytest.raises(ArchiveIntegrityError, match=r"not a valid v0\.1 manifest"):
        archive_module._validate_attempt_bundle(
            replace(
                rejected,
                attempt_id=hashlib.sha256(invalid_envelope).hexdigest(),
                attempt_payload=invalid_payload,
                attempt_envelope=invalid_envelope,
            ),
            DEFAULT_LIMITS,
        )

    wrong_manifest_key = _resign(
        rejected,
        signer,
        msgspec.structs.replace(rejected.manifest, keyid=wrong_keyid),
    )
    with pytest.raises(ArchiveIntegrityError, match="manifest keyid"):
        archive_module._validate_attempt_bundle(wrong_manifest_key, DEFAULT_LIMITS)
    wrong_plot_id = _resign(
        success,
        signer,
        msgspec.structs.replace(success.manifest, plot_id="f" * 64),
    )
    with pytest.raises(ArchiveIntegrityError, match="plot_id disagrees"):
        archive_module._validate_attempt_bundle(wrong_plot_id, DEFAULT_LIMITS)
    wrong_version = _resign(
        success,
        signer,
        msgspec.structs.replace(success.manifest, verifier_version="other"),
    )
    with pytest.raises(ArchiveIntegrityError, match="plot TCB"):
        archive_module._validate_attempt_bundle(wrong_version, DEFAULT_LIMITS)


def test_attempt_record_reference_and_unique_entry_corruption_guards() -> None:
    attempt_id = "a" * 64
    key = BlobWrite(BlobKind.ED25519_PUBLIC_KEY, b"k" * 32)
    envelope = BlobWrite(BlobKind.ATTEMPT_ENVELOPE, b"envelope")
    with pytest.raises(ArchiveIntegrityError, match="record is malformed"):
        archive_module._validated_attempt_record(None, attempt_id)
    with pytest.raises(ArchiveIntegrityError, match="record types"):
        archive_module._validated_attempt_record(
            (envelope.ref.digest, BlobKind.ATTEMPT_ENVELOPE.value, key.ref.digest, "bad"),
            attempt_id,
        )

    def blob_row(blob_id: int, blob: BlobWrite) -> tuple[int, str, str, int]:
        return blob_id, blob.ref.digest, blob.kind.value, len(blob.payload)

    envelope_row = blob_row(1, envelope)
    key_row = blob_row(2, key)
    role_blobs = {
        role: BlobWrite(BlobKind(role.value), role.value.encode()) for role in AttemptRole
    }
    valid_references = [
        (role.value, *blob_row(index, role_blobs[role]))
        for index, role in enumerate(AttemptRole, start=3)
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
                return Result(one=None if self.mode == "missing_relation" else envelope_row)
            if statement == archive_module._SELECT_KEY_BLOB:
                if self.mode == "wrong_key":
                    return Result(
                        one=(2, "sha256:" + "b" * 64, BlobKind.ED25519_PUBLIC_KEY.value, 32)
                    )
                return Result(one=key_row)
            if statement == archive_module._SELECT_ATTEMPT_REFERENCES:
                rows: list[tuple[object, ...]] = list(valid_references)
                if self.mode == "malformed_reference":
                    rows = [(AttemptRole.RAW_CSV.value,)]
                elif self.mode == "unknown_role":
                    rows = [("unknown", *blob_row(3, role_blobs[AttemptRole.RAW_CSV]))]
                elif self.mode == "wrong_kind":
                    rows = [
                        (
                            AttemptRole.RAW_CSV.value,
                            *blob_row(3, role_blobs[AttemptRole.RAW_MANIFEST]),
                        )
                    ]
                elif self.mode == "duplicate_role":
                    rows = [valid_references[0], valid_references[0]]
                elif self.mode == "missing_payload":
                    rows = [row for row in rows if row[0] != AttemptRole.ATTEMPT_PAYLOAD.value]
                return Result(many=rows)
            raise AssertionError(statement)

    cases = (
        ("missing_relation", "relation is broken"),
        ("wrong_key", "wrong typed blob"),
        ("malformed_reference", "reference row is malformed"),
        ("unknown_role", "unknown role"),
        ("wrong_kind", "wrong-kind or duplicate"),
        ("duplicate_role", "wrong-kind or duplicate"),
        ("missing_payload", "authenticated payload role"),
    )
    for mode, message in cases:
        with pytest.raises(ArchiveIntegrityError, match=message):
            archive_module._attempt_bundle_blob_rows(
                cast("sqlite3.Connection", FakeConnection(mode)),
                attempt_id,
                envelope.ref,
                key.ref.digest,
            )

    reference = envelope.ref
    with pytest.raises(ArchiveIntegrityError, match="conflicting blob metadata"):
        archive_module._read_unique_entries(
            cast("sqlite3.Connection", object()),
            (
                (reference, envelope_row),
                (reference, (99, *envelope_row[1:])),
            ),
            max_bytes=100,
        )


def test_linked_plot_absence_and_sqlite_faults_normalize_without_partial_publish(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings, signer, plot = _plot_parts(tmp_path)
    archive = open_archive(settings)
    bundle = materialize_attempt_bundle(
        _success_draft(plot, route=AttemptRoute.VERIFY_AND_RENDER),
        signer,
        nonce="6" * 32,
    )
    archive.publish_attempt(bundle)
    connection = sqlite3.connect(archive.database_path, autocommit=True)
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("DELETE FROM plots WHERE plot_id = ?", (plot.plot_id,))
    finally:
        connection.close()
    with pytest.raises(ArchiveIntegrityError, match="linked plot record is absent"):
        archive.read_attempt(bundle.attempt_id, max_bytes=_bundle_size(bundle))

    clean_settings = Settings(data_dir=_DATA, state_dir=tmp_path / "faults")
    clean_archive = open_archive(clean_settings)
    failure = materialize_attempt_bundle(
        _rejected_draft(clean_settings, route=AttemptRoute.VERIFY_AND_RENDER),
        load_identity(clean_settings).signer,
        nonce="7" * 32,
    )

    def integrity_fault(*_args: object, **_kwargs: object) -> None:
        msg = "injected integrity fault"
        raise sqlite3.IntegrityError(msg)

    monkeypatch.setattr(archive_module, "_publish_unique_attempt", integrity_fault)
    with pytest.raises(ArchiveIntegrityError, match="immutable typed reference"):
        clean_archive.publish_attempt(failure)
    assert clean_archive.stats() == archive_module.ArchiveStats(0, 0, 0, 0, 0)

    def database_fault(*_args: object, **_kwargs: object) -> None:
        msg = "injected database fault"
        raise sqlite3.DatabaseError(msg)

    monkeypatch.setattr(archive_module, "_publish_unique_attempt", database_fault)
    with pytest.raises(archive_module.ArchiveError, match="attempt transaction"):
        clean_archive.publish_attempt(failure)

    monkeypatch.setattr(archive_module, "_publish_unique_attempt", integrity_fault)

    def read_fault(*_args: object, **_kwargs: object) -> AttemptBundle:
        msg = "injected read fault"
        raise sqlite3.DatabaseError(msg)

    monkeypatch.setattr(archive_module, "_read_complete_attempt_bundle", read_fault)
    with pytest.raises(archive_module.ArchiveError, match="complete attempt bundle"):
        clean_archive.read_attempt("f" * 64, max_bytes=1)


def test_generic_dsse_profile_validates_payload_type_types_and_exact_limits(tmp_path: Path) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "state")
    signer = load_identity(settings).signer
    payload = b"exact application bytes"
    envelope = attestation.sign_dsse(
        payload,
        signer.private_key,
        keyid=signer.keyid,
        payload_type=ATTEMPT_PAYLOAD_TYPE,
        max_payload_bytes=len(payload),
    )
    assert (
        attestation.verify_dsse(
            envelope,
            {signer.keyid: signer.public_key},
            payload_type=ATTEMPT_PAYLOAD_TYPE,
            max_payload_bytes=len(payload),
        ).payload
        == payload
    )
    with pytest.raises(VerificationError, match="payload has"):
        attestation.sign_dsse(
            payload,
            signer.private_key,
            keyid=signer.keyid,
            payload_type=ATTEMPT_PAYLOAD_TYPE,
            max_payload_bytes=len(payload) - 1,
        )
    with pytest.raises(attestation.AttestationError, match="unsupported DSSE payload type"):
        attestation.verify_dsse(
            envelope,
            {signer.keyid: signer.public_key},
            payload_type="application/other",
            max_payload_bytes=len(payload),
        )
    for bad_type in ("", cast("str", 7), "\ud800"):
        with pytest.raises(ValueError, match="payload type"):
            attestation.envelope_byte_limit(1, payload_type=bad_type)
    with pytest.raises(TypeError, match="payload must be bytes"):
        attestation.sign_dsse(
            cast("bytes", "bad"),
            signer.private_key,
            keyid=signer.keyid,
            payload_type=ATTEMPT_PAYLOAD_TYPE,
            max_payload_bytes=1,
        )
    with pytest.raises(TypeError, match="envelope_bytes must be bytes"):
        attestation.verify_dsse(
            cast("bytes", "bad"),
            {signer.keyid: signer.public_key},
            payload_type=ATTEMPT_PAYLOAD_TYPE,
            max_payload_bytes=1,
        )
