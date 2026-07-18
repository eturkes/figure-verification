# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Pure snapshot replay trust, integrity, recomputation, and drift boundaries."""

import ast
import hashlib
import inspect
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn, cast

import msgspec
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from verifier import attestation, canon, checks, render, replay
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.service import archive as archive_module
from verifier.service import pipeline
from verifier.service.archive import (
    ATTEMPT_PAYLOAD_TYPE,
    AttemptArtifacts,
    AttemptBundle,
    AttemptDraft,
    AttemptManifest,
    AttemptOutcome,
    AttemptRoute,
    BlobBinding,
    BlobKind,
    PlotBundle,
    PlotRole,
    materialize_attempt_bundle,
    materialize_plot_bundle,
)
from verifier.service.identity import Signer, load_identity
from verifier.service.settings import Settings

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_RAW_SPEC = (_ROOT / "examples/good_specs/g01_total_revenue_by_month.json").read_bytes()
_TIME = datetime(2026, 7, 18, 1, 2, 3, 456789, tzinfo=UTC)
_ENCODER = msgspec.json.Encoder(order="deterministic")


@dataclass(frozen=True, slots=True)
class _Fixture:
    snapshot: replay.ReplaySnapshot
    bundle: AttemptBundle
    signer: Signer
    settings: Settings


def _snapshot(bundle: AttemptBundle) -> replay.ReplaySnapshot:
    plot = cast("PlotBundle", bundle.plot)
    artifacts = bundle.artifacts
    return replay.ReplaySnapshot(
        attempt_id=bundle.attempt_id,
        keyid=bundle.keyid,
        artifacts=replay.ReplayAttemptArtifacts(
            raw_csv=artifacts.raw_csv,
            raw_manifest=artifacts.raw_manifest,
            raw_spec=artifacts.raw_spec,
            verdict=artifacts.verdict,
            model_request=artifacts.model_request,
            model_response=artifacts.model_response,
            model_reply=artifacts.model_reply,
        ),
        attempt_payload=bundle.attempt_payload,
        attempt_envelope=bundle.attempt_envelope,
        public_key=bundle.public_key,
        plot=replay.ReplayPlotSnapshot(
            plot_id=plot.plot_id,
            keyid=plot.keyid,
            raw_csv=plot.raw_csv,
            raw_manifest=plot.raw_manifest,
            canonical_spec=plot.canonical_spec,
            plotted_table=plot.plotted_table,
            verdict=plot.verdict,
            vega_lite=plot.vega_lite,
            svg=plot.svg,
            vcert_payload=plot.vcert_payload,
            vcert_envelope=plot.vcert_envelope,
            tool_versions=plot.tool_versions,
            public_key=plot.public_key,
        ),
    )


def _fixture(tmp_path: Path, *, route: AttemptRoute = AttemptRoute.VERIFY_AND_RENDER) -> _Fixture:
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
    plot = materialize_plot_bundle(
        prepared,
        rendered,
        envelope,
        signer,
        limits=settings.limits,
    )
    if route is AttemptRoute.PROPOSE_SPEC:
        artifacts = AttemptArtifacts(
            raw_csv=plot.raw_csv,
            raw_manifest=plot.raw_manifest,
            raw_spec=_RAW_SPEC,
            verdict=plot.verdict,
            model_request=b"request",
            model_response=b"response",
            model_reply=_RAW_SPEC,
        )
    else:
        artifacts = AttemptArtifacts(
            raw_csv=plot.raw_csv,
            raw_manifest=plot.raw_manifest,
            raw_spec=_RAW_SPEC,
            verdict=plot.verdict,
        )
    draft = AttemptDraft(
        occurred_at=_TIME,
        route=route,
        http_status=200,
        outcome=AttemptOutcome.VERIFIED,
        artifacts=artifacts,
        plot=plot,
    )
    bundle = materialize_attempt_bundle(draft, signer, nonce="5" * 32, limits=settings.limits)
    return _Fixture(snapshot=_snapshot(bundle), bundle=bundle, signer=signer, settings=settings)


def _trusted(fixture: _Fixture) -> dict[str, Any]:
    return {fixture.signer.keyid: fixture.signer.public_key}


def _all_hashes_match(verdict: replay.ReplayVerdict) -> bool:
    matches = verdict.artifact_matches
    return all(
        value is True
        for value in (
            matches.dataset,
            matches.manifest,
            matches.spec,
            matches.plotted_table,
            matches.vega_lite,
        )
    )


def _resign_payload(fixture: _Fixture, payload: bytes) -> replay.ReplaySnapshot:
    envelope = attestation.sign_dsse(
        payload,
        fixture.signer.private_key,
        keyid=fixture.signer.keyid,
        payload_type=ATTEMPT_PAYLOAD_TYPE,
        max_payload_bytes=DEFAULT_LIMITS.max_attestation_bytes,
    )
    return replace(
        fixture.snapshot,
        attempt_id=hashlib.sha256(envelope).hexdigest(),
        attempt_payload=payload,
        attempt_envelope=envelope,
    )


def _resign_manifest(
    fixture: _Fixture,
    manifest: AttemptManifest,
    *,
    snapshot: replay.ReplaySnapshot | None = None,
) -> replay.ReplaySnapshot:
    base = fixture.snapshot if snapshot is None else snapshot
    payload = _ENCODER.encode(manifest)
    resigned = _resign_payload(fixture, payload)
    return replace(
        base,
        attempt_id=resigned.attempt_id,
        attempt_payload=resigned.attempt_payload,
        attempt_envelope=resigned.attempt_envelope,
    )


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _replace_plot_bytes(
    plot: replay.ReplayPlotSnapshot, field: str, payload: bytes
) -> replay.ReplayPlotSnapshot:
    updates: Any = {field: payload}
    return replace(plot, **updates)


def _plot_bindings(plot: replay.ReplayPlotSnapshot) -> tuple[BlobBinding, ...]:
    return tuple(
        BlobBinding(role=role, digest=_digest(cast("bytes", getattr(plot, name))))
        for role, name in archive_module._PLOT_BINDING_FIELDS
    )


def _artifact_bindings(artifacts: replay.ReplayAttemptArtifacts) -> tuple[BlobBinding, ...]:
    return tuple(
        BlobBinding(role=BlobKind(role.value), digest=_digest(payload))
        for role, name in archive_module._ATTEMPT_ARTIFACT_FIELDS
        if (payload := cast("bytes | None", getattr(artifacts, name))) is not None
    )


def _rebind_plot(
    fixture: _Fixture,
    plot: replay.ReplayPlotSnapshot,
    *,
    artifacts: replay.ReplayAttemptArtifacts | None = None,
) -> replay.ReplaySnapshot:
    rebound_artifacts = fixture.snapshot.artifacts if artifacts is None else artifacts
    snapshot = replace(fixture.snapshot, plot=plot, artifacts=rebound_artifacts)
    manifest = msgspec.structs.replace(
        fixture.bundle.manifest,
        artifacts=_artifact_bindings(rebound_artifacts),
        plot_artifacts=_plot_bindings(plot),
        plot_id=plot.plot_id,
    )
    return _resign_manifest(fixture, manifest, snapshot=snapshot)


def test_exact_same_version_replay_matches_every_certified_artifact(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    verdict = replay.replay_snapshot(fixture.snapshot, _trusted(fixture))

    assert verdict.status == "exact"
    assert verdict.integrity_ok
    assert verdict.trusted_keyid == fixture.signer.keyid
    assert verdict.failure_stage is None
    assert _all_hashes_match(verdict)
    assert verdict.payload_match is True
    assert verdict.version_match is True
    assert verdict.drift == ()
    assert verdict.svg_match is True
    assert verdict.exact
    encoded = msgspec.json.encode(verdict)
    assert fixture.snapshot.plot.raw_csv not in encoded
    assert fixture.snapshot.plot.vega_lite not in encoded
    assert fixture.snapshot.plot.svg not in encoded


def test_proposer_success_replay_accepts_its_complete_model_trace(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, route=AttemptRoute.PROPOSE_SPEC)
    verdict = replay.replay_snapshot(fixture.snapshot, _trusted(fixture))

    assert verdict.status == "exact"
    assert verdict.exact


def test_replay_imports_only_allowed_core_and_never_service_modules() -> None:
    tree = ast.parse(inspect.getsource(replay))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    )
    assert not {module for module in imported if module.startswith("verifier.service")}
    allowed = {
        "hashlib",
        "collections.abc",
        "dataclasses",
        "typing",
        "msgspec",
        "cryptography.hazmat.primitives.asymmetric.ed25519",
        "verifier",
        "verifier.limits",
    }
    assert imported <= allowed


def test_replay_role_vocabulary_matches_archive_producer() -> None:
    assert tuple(role.value for role in BlobKind) == replay.BLOB_ROLE_VALUES
    assert tuple(role.value for role in PlotRole) == replay.PLOT_ROLE_VALUES


def test_absent_trusted_key_is_untrusted_and_stops_before_recompute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)

    def _unexpected_recompute(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "untrusted snapshot reached recomputation"
        raise AssertionError(msg)

    monkeypatch.setattr(checks, "verify_snapshot", _unexpected_recompute)
    verdict = replay.replay_snapshot(fixture.snapshot, {})

    assert verdict.status == "untrusted_key"
    assert not verdict.integrity_ok
    assert verdict.trusted_keyid is None
    assert verdict.failure_stage == "trust"
    assert not verdict.exact


def test_pinned_keyid_mapped_to_wrong_key_is_signature_failure_without_recompute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    wrong_key = Ed25519PrivateKey.generate().public_key()

    def _unexpected_recompute(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "bad signature reached recomputation"
        raise AssertionError(msg)

    monkeypatch.setattr(checks, "verify_snapshot", _unexpected_recompute)
    verdict = replay.replay_snapshot(fixture.snapshot, {fixture.signer.keyid: wrong_key})

    assert verdict.status == "integrity_failed"
    assert not verdict.integrity_ok
    assert verdict.trusted_keyid is None
    assert verdict.failure_stage == "attempt_signature"
    assert not verdict.exact


@pytest.mark.parametrize(
    "field",
    (
        "raw_csv",
        "raw_manifest",
        "canonical_spec",
        "plotted_table",
        "vega_lite",
        "svg",
        "verdict",
    ),
)
def test_mutated_plot_blob_fails_authenticated_digest_binding(tmp_path: Path, field: str) -> None:
    fixture = _fixture(tmp_path)
    original = cast("bytes", getattr(fixture.snapshot.plot, field))
    mutated = original[:-1] + bytes([original[-1] ^ 1])
    plot = _replace_plot_bytes(fixture.snapshot.plot, field, mutated)
    snapshot = replace(fixture.snapshot, plot=plot)

    assert mutated != original
    assert _digest(mutated) != _digest(original)
    verdict = replay.replay_snapshot(snapshot, _trusted(fixture))
    assert verdict.status == "integrity_failed"
    assert verdict.failure_stage == "plot_artifacts"
    assert not verdict.exact


def test_authenticated_role_swap_fails_attempt_artifact_graph(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    bindings = fixture.bundle.manifest.artifacts
    swapped = (
        msgspec.structs.replace(bindings[0], role=bindings[1].role),
        msgspec.structs.replace(bindings[1], role=bindings[0].role),
        *bindings[2:],
    )
    manifest = msgspec.structs.replace(fixture.bundle.manifest, artifacts=swapped)
    snapshot = _resign_manifest(fixture, manifest)

    assert swapped != bindings
    verdict = replay.replay_snapshot(snapshot, _trusted(fixture))
    assert verdict.status == "integrity_failed"
    assert verdict.failure_stage == "attempt_artifacts"


def test_authenticated_binding_digest_tamper_fails_attempt_artifact_graph(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    bindings = fixture.bundle.manifest.artifacts
    tampered = (
        msgspec.structs.replace(bindings[0], digest="sha256:" + "0" * 64),
        *bindings[1:],
    )
    manifest = msgspec.structs.replace(fixture.bundle.manifest, artifacts=tampered)
    snapshot = _resign_manifest(fixture, manifest)

    assert tampered != bindings
    verdict = replay.replay_snapshot(snapshot, _trusted(fixture))
    assert verdict.status == "integrity_failed"
    assert verdict.failure_stage == "attempt_artifacts"


def test_current_tcb_version_drift_preserves_all_five_artifact_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    monkeypatch.setattr(render, "__version__", "replay-drift")

    verdict = replay.replay_snapshot(fixture.snapshot, _trusted(fixture))

    assert verdict.status == "drift"
    assert verdict.integrity_ok
    assert _all_hashes_match(verdict)
    assert verdict.version_match is False
    assert verdict.payload_match is False
    assert [(item.field, item.archived, item.current) for item in verdict.drift] == [
        ("verifier_version", fixture.bundle.manifest.verifier_version, "replay-drift")
    ]
    assert not verdict.exact


def test_recomputation_hash_divergence_is_reported_without_integrity_confusion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)

    def _different_table_hash(_table: canon.Table) -> str:
        return "sha256:" + "0" * 64

    monkeypatch.setattr(canon, "hash_table", _different_table_hash)
    verdict = replay.replay_snapshot(fixture.snapshot, _trusted(fixture))

    assert verdict.status == "recomputation_failed"
    assert verdict.integrity_ok
    assert verdict.failure_stage == "recomputation"
    assert verdict.artifact_matches.dataset is True
    assert verdict.artifact_matches.manifest is True
    assert verdict.artifact_matches.spec is True
    assert verdict.artifact_matches.plotted_table is False
    assert verdict.artifact_matches.vega_lite is True
    assert verdict.version_match is True
    assert not verdict.exact


def test_native_svg_difference_is_diagnostic_and_does_not_gate_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    original_render = render.render_prepared

    def _different_svg(
        prepared: render.PreparedArtifact,
        *,
        include_html: bool = False,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> render.RenderResult:
        result = original_render(prepared, include_html=include_html, limits=limits)
        return msgspec.structs.replace(result, svg=result.svg + " ")

    monkeypatch.setattr(render, "render_prepared", _different_svg)
    verdict = replay.replay_snapshot(fixture.snapshot, _trusted(fixture))

    assert verdict.status == "exact"
    assert _all_hashes_match(verdict)
    assert verdict.payload_match is True
    assert verdict.version_match is True
    assert verdict.svg_match is False
    assert verdict.exact


@pytest.mark.parametrize("field", ("plotted_table", "vega_lite"))
def test_stored_derived_artifacts_cannot_steer_recomputation(tmp_path: Path, field: str) -> None:
    fixture = _fixture(tmp_path)
    original = cast("bytes", getattr(fixture.snapshot.plot, field))
    mutated = original + b" "
    tampered_plot = _replace_plot_bytes(fixture.snapshot.plot, field, mutated)
    tampered = replace(fixture.snapshot, plot=tampered_plot)

    public_verdict = replay.replay_snapshot(tampered, _trusted(fixture))
    assert public_verdict.status == "integrity_failed"
    assert public_verdict.failure_stage == "plot_artifacts"

    authenticated = replay._authenticate_snapshot(
        fixture.snapshot,
        _trusted(fixture),
        fixture.settings.limits,
    )
    isolated = replace(authenticated, snapshot=tampered)
    recomputed = replay._recompute_authenticated(
        isolated,
        fixture.settings.limits,
    )
    assert mutated != original
    assert _all_hashes_match(recomputed)
    assert recomputed.payload_match is True
    assert recomputed.exact


def test_snapshot_dataclasses_reject_hostile_runtime_shapes(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    snapshot = fixture.snapshot

    with pytest.raises(TypeError, match="attempt id must be str"):
        replace(snapshot, attempt_id=cast("str", 7))
    with pytest.raises(ValueError, match="64 lowercase"):
        replace(snapshot, attempt_id="g" * 64)
    with pytest.raises(TypeError, match="attempt keyid must be str"):
        replace(snapshot, keyid=cast("str", 7))
    with pytest.raises(ValueError, match="sha256"):
        replace(snapshot, keyid="sha512:" + "0" * 64)
    with pytest.raises(TypeError, match="ReplayAttemptArtifacts"):
        replace(snapshot, artifacts=cast("replay.ReplayAttemptArtifacts", object()))
    with pytest.raises(TypeError, match="ReplayPlotSnapshot"):
        replace(snapshot, plot=cast("replay.ReplayPlotSnapshot", object()))
    with pytest.raises(TypeError, match="attempt attempt_payload must be bytes"):
        replace(snapshot, attempt_payload=cast("bytes", "bad"))
    with pytest.raises(TypeError, match="artifact model_request must be bytes or None"):
        replace(snapshot.artifacts, model_request=cast("bytes", "bad"))
    with pytest.raises(TypeError, match="replay plot id must be str"):
        replace(snapshot.plot, plot_id=cast("str", 7))
    with pytest.raises(ValueError, match="64 lowercase"):
        replace(snapshot.plot, plot_id="g" * 64)
    with pytest.raises(TypeError, match="replay plot keyid must be str"):
        replace(snapshot.plot, keyid=cast("str", 7))
    with pytest.raises(ValueError, match="sha256"):
        replace(snapshot.plot, keyid="bad")
    with pytest.raises(TypeError, match="replay plot svg must be bytes"):
        replace(snapshot.plot, svg=cast("bytes", "bad"))


def test_public_replay_rejects_non_snapshot_programmer_misuse() -> None:
    with pytest.raises(TypeError, match="snapshot must be ReplaySnapshot"):
        replay.replay_snapshot(cast("replay.ReplaySnapshot", object()), {})


def test_authenticated_invalid_and_noncanonical_attempt_payloads_fail_closed(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    invalid = _resign_payload(fixture, b"{")
    noncanonical = _resign_payload(fixture, fixture.snapshot.attempt_payload + b" ")

    invalid_verdict = replay.replay_snapshot(invalid, _trusted(fixture))
    noncanonical_verdict = replay.replay_snapshot(noncanonical, _trusted(fixture))
    assert invalid_verdict.failure_stage == "attempt_manifest"
    assert noncanonical_verdict.failure_stage == "attempt_manifest"
    assert not invalid_verdict.exact
    assert not noncanonical_verdict.exact


def test_authenticated_manifest_shape_rejects_impossible_time_status_and_duplicate_role(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    manifest = fixture.bundle.manifest
    impossible_time = _resign_manifest(
        fixture,
        msgspec.structs.replace(manifest, occurred_at="2026-02-30T01:02:03.456789Z"),
    )
    wrong_status = _resign_manifest(
        fixture,
        msgspec.structs.replace(manifest, http_status=201),
    )
    duplicate = _resign_manifest(
        fixture,
        msgspec.structs.replace(
            manifest,
            artifacts=(
                manifest.artifacts[0],
                msgspec.structs.replace(manifest.artifacts[1], role=manifest.artifacts[0].role),
                *manifest.artifacts[2:],
            ),
        ),
    )

    for snapshot in (impossible_time, wrong_status, duplicate):
        verdict = replay.replay_snapshot(snapshot, _trusted(fixture))
        assert verdict.status == "integrity_failed"
        assert verdict.failure_stage == "attempt_manifest"


def test_manifest_runtime_validation_rejects_non_utf8_encodable_version(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    mirrored = replay._ATTEMPT_DECODER.decode(fixture.snapshot.attempt_payload)
    hostile = msgspec.structs.replace(mirrored, verifier_version="\ud800")

    with pytest.raises(replay._ReplayFailureError, match="not valid UTF-8"):
        replay._validate_manifest(hostile, trusted_keyid=fixture.signer.keyid)


def test_authenticated_attempt_outcome_and_version_cross_edges_fail_closed(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    rejected = _resign_manifest(
        fixture,
        msgspec.structs.replace(fixture.bundle.manifest, outcome=AttemptOutcome.REJECTED),
    )
    wrong_version = _resign_manifest(
        fixture,
        msgspec.structs.replace(fixture.bundle.manifest, verifier_version="other"),
    )

    rejected_verdict = replay.replay_snapshot(rejected, _trusted(fixture))
    version_verdict = replay.replay_snapshot(wrong_version, _trusted(fixture))
    assert rejected_verdict.failure_stage == "attempt_outcome"
    assert version_verdict.failure_stage == "attempt_plot"


def test_proposer_reply_must_equal_exact_raw_spec_observation(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, route=AttemptRoute.PROPOSE_SPEC)
    artifacts = replace(fixture.snapshot.artifacts, raw_spec=_RAW_SPEC + b" ")
    snapshot = replace(fixture.snapshot, artifacts=artifacts)
    manifest = msgspec.structs.replace(
        fixture.bundle.manifest,
        artifacts=_artifact_bindings(artifacts),
    )
    resigned = _resign_manifest(fixture, manifest, snapshot=snapshot)

    verdict = replay.replay_snapshot(resigned, _trusted(fixture))
    assert verdict.status == "integrity_failed"
    assert verdict.failure_stage == "attempt_outcome"


def test_authenticated_invalid_and_noncanonical_plot_payloads_fail_closed(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    cases: tuple[tuple[str, bytes, str], ...] = (
        ("canonical_spec", b"{", "plot_contents"),
        ("canonical_spec", fixture.snapshot.plot.canonical_spec + b" ", "plot_contents"),
        ("tool_versions", b"{", "plot_contents"),
        ("tool_versions", fixture.snapshot.plot.tool_versions + b" ", "plot_contents"),
    )
    for field, payload, stage in cases:
        plot = _replace_plot_bytes(fixture.snapshot.plot, field, payload)
        snapshot = _rebind_plot(fixture, plot)
        verdict = replay.replay_snapshot(snapshot, _trusted(fixture))
        assert verdict.status == "integrity_failed"
        assert verdict.failure_stage == stage


def test_authenticated_invalid_and_noncanonical_verdicts_fail_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    for payload in (b"{", fixture.snapshot.plot.verdict + b" "):
        plot = replace(fixture.snapshot.plot, verdict=payload)
        artifacts = replace(fixture.snapshot.artifacts, verdict=payload)
        snapshot = _rebind_plot(fixture, plot, artifacts=artifacts)
        verdict = replay.replay_snapshot(snapshot, _trusted(fixture))
        assert verdict.status == "integrity_failed"
        assert verdict.failure_stage == "plot_contents"


def test_rebound_plot_hash_svg_and_tool_version_mismatches_fail_at_plot_contents(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    archived_tcb = msgspec.json.decode(
        fixture.snapshot.plot.tool_versions,
        type=render.Tcb,
        strict=True,
    )
    different_tcb = msgspec.structs.replace(archived_tcb, verifier_version="different")
    cases = (
        replace(fixture.snapshot.plot, plotted_table=fixture.snapshot.plot.plotted_table + b" "),
        replace(fixture.snapshot.plot, svg=b"\xff"),
        replace(fixture.snapshot.plot, tool_versions=_ENCODER.encode(different_tcb)),
    )
    for plot in cases:
        snapshot = _rebind_plot(fixture, plot)
        verdict = replay.replay_snapshot(snapshot, _trusted(fixture))
        assert verdict.status == "integrity_failed"
        assert verdict.failure_stage == "plot_contents"


def test_vcert_signature_canonical_payload_and_stored_payload_edges_fail_closed(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    broken_envelope = fixture.snapshot.plot.vcert_envelope + b" "
    bad_signature_plot = replace(
        fixture.snapshot.plot,
        plot_id=hashlib.sha256(broken_envelope).hexdigest(),
        vcert_envelope=broken_envelope,
    )
    bad_signature = _rebind_plot(fixture, bad_signature_plot)

    noncanonical_payload = fixture.snapshot.plot.vcert_payload + b" "
    noncanonical_envelope = attestation.sign_dsse(
        noncanonical_payload,
        fixture.signer.private_key,
        keyid=fixture.signer.keyid,
        payload_type=attestation.VCERT_PAYLOAD_TYPE,
        max_payload_bytes=fixture.settings.limits.max_attestation_bytes,
    )
    noncanonical_plot = replace(
        fixture.snapshot.plot,
        plot_id=hashlib.sha256(noncanonical_envelope).hexdigest(),
        vcert_payload=noncanonical_payload,
        vcert_envelope=noncanonical_envelope,
    )
    noncanonical = _rebind_plot(fixture, noncanonical_plot)

    mismatched_payload_plot = replace(
        fixture.snapshot.plot,
        vcert_payload=fixture.snapshot.plot.vcert_payload + b" ",
    )
    mismatched_payload = _rebind_plot(fixture, mismatched_payload_plot)

    for snapshot in (bad_signature, noncanonical, mismatched_payload):
        verdict = replay.replay_snapshot(snapshot, _trusted(fixture))
        assert verdict.status == "integrity_failed"
        assert verdict.failure_stage == "plot_signature"


def test_recompute_exception_is_bounded_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)

    def _raise_verify(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "recompute fault"
        raise ValueError(msg)

    monkeypatch.setattr(checks, "verify_snapshot", _raise_verify)
    verdict = replay.replay_snapshot(fixture.snapshot, _trusted(fixture))
    assert verdict.status == "recomputation_failed"
    assert verdict.integrity_ok
    assert verdict.failure_stage == "recomputation"
    assert verdict.diagnostic.endswith("ValueError")


def test_current_core_verification_failure_is_bounded_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    authenticated = replay._authenticate_snapshot(
        fixture.snapshot,
        _trusted(fixture),
        fixture.settings.limits,
    )
    failed_run = checks.verify_snapshot(
        authenticated.spec,
        fixture.snapshot.plot.raw_manifest,
        fixture.snapshot.plot.raw_csv + b" ",
        limits=fixture.settings.limits,
    )

    def _failed_verify(*_args: object, **_kwargs: object) -> checks.VerificationRun:
        return failed_run

    monkeypatch.setattr(checks, "verify_snapshot", _failed_verify)
    verdict = replay.replay_snapshot(fixture.snapshot, _trusted(fixture))
    assert verdict.status == "recomputation_failed"
    assert "no longer pass current core" in verdict.diagnostic


def test_prepare_exception_is_bounded_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)

    def _raise_prepare(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "prepare fault"
        raise ValueError(msg)

    monkeypatch.setattr(render, "prepare_render", _raise_prepare)
    verdict = replay.replay_snapshot(fixture.snapshot, _trusted(fixture))
    assert verdict.status == "recomputation_failed"
    assert verdict.diagnostic.endswith("ValueError")


def test_formal_preparation_failure_is_bounded_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    authenticated = replay._authenticate_snapshot(
        fixture.snapshot,
        _trusted(fixture),
        fixture.settings.limits,
    )
    run = checks.verify_snapshot(
        authenticated.spec,
        fixture.snapshot.plot.raw_manifest,
        fixture.snapshot.plot.raw_csv,
        limits=fixture.settings.limits,
    )
    evidence = cast("checks.RecomputedEvidence", run.evidence)
    preparation = render.prepare_render(
        authenticated.spec,
        evidence,
        limits=fixture.settings.limits,
    )
    failed_preparation = replace(preparation, prepared=None)

    def _failed_prepare(*_args: object, **_kwargs: object) -> render.PreparationRun:
        return failed_preparation

    monkeypatch.setattr(render, "prepare_render", _failed_prepare)
    verdict = replay.replay_snapshot(fixture.snapshot, _trusted(fixture))
    assert verdict.status == "recomputation_failed"
    assert "formal verification" in verdict.diagnostic


def test_native_render_exception_is_bounded_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)

    def _raise_render(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "render fault"
        raise ValueError(msg)

    monkeypatch.setattr(render, "render_prepared", _raise_render)
    verdict = replay.replay_snapshot(fixture.snapshot, _trusted(fixture))
    assert verdict.status == "recomputation_failed"
    assert verdict.diagnostic.endswith("ValueError")
