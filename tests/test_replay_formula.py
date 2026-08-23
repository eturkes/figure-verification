# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M9.9 formula replay trust, layer ordering, non-steering, drift, and purity."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn, cast, get_args

import msgspec
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from formula_plot_bundle_helpers import (
    FormulaBundleParts,
    dataset_bundle,
    dataset_certificate,
    dataset_v03_certificate,
    formula_bundle_parts,
    signer,
)
from verifier import (
    attestation,
    canon,
    checks,
    formula_prepare,
    matplotlib_script,
    replay,
    schema,
    vcert,
)
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
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
    DatasetPlotBundle,
    FormulaPlotBundle,
    materialize_attempt_bundle,
)
from verifier.service.identity import Signer, load_identity
from verifier.service.models import Verdict
from verifier.service.settings import Settings

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_RAW_FORMULA_SPEC = (_ROOT / "examples/formula_good_specs/f02_linear.json").read_bytes()
_RAW_DATASET_SPEC = (_ROOT / "examples/good_specs/g01_total_revenue_by_month.json").read_bytes()
_TIME = datetime(2026, 8, 22, 1, 2, 3, 456789, tzinfo=UTC)
_ENCODER = msgspec.json.Encoder(order="deterministic")

_FORMULA_BINDING_FIELDS: tuple[tuple[BlobKind, str], ...] = (
    (BlobKind.CANONICAL_SPEC, "canonical_spec"),
    (BlobKind.FORMULA_SOURCE, "formula_source"),
    (BlobKind.PLOTTED_TABLE, "plotted_table"),
    (BlobKind.VERDICT, "verdict"),
    (BlobKind.MATPLOTLIB_SCRIPT, "matplotlib_script"),
    (BlobKind.VCERT_PAYLOAD, "vcert_payload"),
    (BlobKind.VCERT_ENVELOPE, "vcert_envelope"),
    (BlobKind.TOOL_VERSIONS, "tool_versions"),
    (BlobKind.ED25519_PUBLIC_KEY, "public_key"),
)
_ATTEMPT_BINDING_FIELDS: tuple[tuple[BlobKind, str], ...] = (
    (BlobKind.RAW_CSV, "raw_csv"),
    (BlobKind.RAW_MANIFEST, "raw_manifest"),
    (BlobKind.RAW_SPEC, "raw_spec"),
    (BlobKind.VERDICT, "verdict"),
    (BlobKind.MODEL_REQUEST, "model_request"),
    (BlobKind.MODEL_RESPONSE, "model_response"),
    (BlobKind.MODEL_REPLY, "model_reply"),
)


type _ReplayCallable = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class _Fixture:
    snapshot: Any
    bundle: AttemptBundle
    parts: FormulaBundleParts
    signer: Signer
    settings: Settings


def _formula_plot_type() -> type[Any]:
    value = replay.__dict__.get("ReplayFormulaPlotSnapshot")
    assert isinstance(value, type), "ReplayFormulaPlotSnapshot is absent"
    return value


def _formula_snapshot_type() -> type[Any]:
    value = replay.__dict__.get("ReplayFormulaSnapshot")
    assert isinstance(value, type), "ReplayFormulaSnapshot is absent"
    return value


def _formula_struct_type(name: str) -> type[Any]:
    value = replay.__dict__.get(name)
    assert isinstance(value, type), f"{name} is absent"
    return value


def _formula_replay() -> _ReplayCallable:
    value = replay.__dict__.get("replay_formula_snapshot")
    assert callable(value), "replay_formula_snapshot is absent"
    return cast("_ReplayCallable", value)


def _snapshot(bundle: AttemptBundle) -> Any:
    plot = cast("FormulaPlotBundle", bundle.plot)
    artifacts = bundle.artifacts
    replay_plot = _formula_plot_type()(
        plot_id=plot.plot_id,
        keyid=plot.keyid,
        canonical_spec=plot.canonical_spec,
        formula_source=plot.formula_source,
        plotted_table=plot.plotted_table,
        verdict=plot.verdict,
        matplotlib_script=plot.matplotlib_script,
        vcert_payload=plot.vcert_payload,
        vcert_envelope=plot.vcert_envelope,
        tool_versions=plot.tool_versions,
        public_key=plot.public_key,
    )
    return _formula_snapshot_type()(
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
        plot=replay_plot,
    )


def _fixture(tmp_path: Path) -> _Fixture:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "formula-replay")
    signer = load_identity(settings).signer
    parts = formula_bundle_parts(signing=signer)
    draft = AttemptDraft(
        occurred_at=_TIME,
        route=AttemptRoute.VERIFY_FORMULA,
        http_status=200,
        outcome=AttemptOutcome.VERIFIED,
        artifacts=AttemptArtifacts(raw_spec=_RAW_FORMULA_SPEC, verdict=parts.bundle.verdict),
        plot=parts.bundle,
    )
    bundle = materialize_attempt_bundle(
        draft,
        signer,
        nonce="9" * 32,
        limits=settings.limits,
    )
    return _Fixture(
        snapshot=_snapshot(bundle),
        bundle=bundle,
        parts=parts,
        signer=signer,
        settings=settings,
    )


def _trusted(fixture: _Fixture) -> dict[str, Ed25519PublicKey]:
    return {fixture.signer.keyid: fixture.signer.public_key}


def _run(
    fixture: _Fixture,
    snapshot: Any | None = None,
    *,
    limits: VerificationLimits | None = None,
) -> Any:
    selected = fixture.snapshot if snapshot is None else snapshot
    selected_limits = fixture.settings.limits if limits is None else limits
    return _formula_replay()(selected, _trusted(fixture), limits=selected_limits)


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _different_keyid(keyid: str) -> str:
    return keyid[:-1] + ("0" if keyid[-1] != "0" else "1")


def _mutate(payload: bytes) -> bytes:
    return payload[:-1] + bytes([payload[-1] ^ 1])


def _artifact_bindings(artifacts: replay.ReplayAttemptArtifacts) -> tuple[BlobBinding, ...]:
    return tuple(
        BlobBinding(role=role, digest=_digest(payload))
        for role, name in _ATTEMPT_BINDING_FIELDS
        if (payload := cast("bytes | None", getattr(artifacts, name))) is not None
    )


def _plot_bindings(plot: Any) -> tuple[BlobBinding, ...]:
    return tuple(
        BlobBinding(role=role, digest=_digest(cast("bytes", getattr(plot, name))))
        for role, name in _FORMULA_BINDING_FIELDS
    )


def _resign_payload(fixture: _Fixture, payload: bytes, *, snapshot: Any | None = None) -> Any:
    base = fixture.snapshot if snapshot is None else snapshot
    envelope = attestation.sign_dsse(
        payload,
        fixture.signer.private_key,
        keyid=fixture.signer.keyid,
        payload_type=ATTEMPT_PAYLOAD_TYPE,
        max_payload_bytes=fixture.settings.limits.max_attestation_bytes,
    )
    return replace(
        base,
        attempt_id=hashlib.sha256(envelope).hexdigest(),
        attempt_payload=payload,
        attempt_envelope=envelope,
    )


def _resign_manifest(
    fixture: _Fixture,
    manifest: AttemptManifest,
    *,
    snapshot: Any | None = None,
) -> Any:
    return _resign_payload(fixture, _ENCODER.encode(manifest), snapshot=snapshot)


def _rebind(
    fixture: _Fixture,
    plot: Any,
    *,
    artifacts: replay.ReplayAttemptArtifacts | None = None,
    manifest_changes: dict[str, Any] | None = None,
) -> Any:
    rebound_artifacts = fixture.snapshot.artifacts if artifacts is None else artifacts
    snapshot = replace(fixture.snapshot, plot=plot, artifacts=rebound_artifacts)
    changes: dict[str, Any] = {
        "artifacts": _artifact_bindings(rebound_artifacts),
        "plot_artifacts": _plot_bindings(plot),
        "plot_id": plot.plot_id,
    }
    if manifest_changes is not None:
        changes.update(manifest_changes)
    manifest = msgspec.structs.replace(fixture.bundle.manifest, **changes)
    return _resign_manifest(fixture, manifest, snapshot=snapshot)


def _replace_plot(fixture: _Fixture, **changes: Any) -> Any:
    return replace(fixture.snapshot.plot, **changes)


def _signed_certificate_plot(
    fixture: _Fixture,
    certificate: vcert.VCertV03,
    **changes: Any,
) -> Any:
    payload = vcert.vcert_v03_bytes(certificate)
    envelope = attestation.sign_vcert_v03(
        certificate,
        fixture.signer.private_key,
        keyid=fixture.signer.keyid,
    )
    updates: dict[str, Any] = {
        "plot_id": hashlib.sha256(envelope).hexdigest(),
        "vcert_payload": payload,
        "vcert_envelope": envelope,
    }
    updates.update(changes)
    return _replace_plot(fixture, **updates)


def _decoded_verdict(payload: bytes) -> Verdict:
    return msgspec.json.decode(payload, type=Verdict, strict=True)


def _replace_verdict(fixture: _Fixture, verdict: Verdict, *, plot: Any | None = None) -> Any:
    payload = _ENCODER.encode(verdict)
    base_plot = fixture.snapshot.plot if plot is None else plot
    changed_plot = replace(base_plot, verdict=payload)
    artifacts = replace(fixture.snapshot.artifacts, verdict=payload)
    return _rebind(fixture, changed_plot, artifacts=artifacts)


def _arm_downstream_bombs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    include_spec_decode: bool = True,
) -> dict[str, int]:
    calls = {
        "spec_decode": 0,
        "verify": 0,
        "prepare": 0,
        "emit": 0,
        "build": 0,
        "recompute": 0,
    }

    def bomb(name: str) -> Callable[..., NoReturn]:
        def fail(*_args: object, **_kwargs: object) -> NoReturn:
            calls[name] += 1
            msg = f"pre-recompute failure reached {name}"
            raise AssertionError(msg)

        return fail

    if include_spec_decode:
        monkeypatch.setattr(replay, "_decode_formula_spec", bomb("spec_decode"))
    monkeypatch.setattr(checks, "verify_formula_run", bomb("verify"))
    monkeypatch.setattr(formula_prepare, "prepare_formula", bomb("prepare"))
    monkeypatch.setattr(matplotlib_script, "emit_matplotlib_script", bomb("emit"))
    monkeypatch.setattr(vcert, "build_formula_certificate", bomb("build"))
    monkeypatch.setattr(replay, "_recompute_formula_certificate", bomb("recompute"))
    return calls


def _assert_empty_comparison(verdict: Any) -> None:
    """Every pre-recompute refusal reports the same empty comparison payload."""
    assert verdict.artifact_matches == replay.FormulaArtifactHashMatches()
    assert verdict.artifact_matches.formula is None
    assert verdict.artifact_matches.spec is None
    assert verdict.artifact_matches.plotted_table is None
    assert verdict.artifact_matches.matplotlib_script is None
    assert verdict.payload_match is None
    assert verdict.version_match is None
    assert verdict.drift == ()
    assert verdict.exact is False


def _assert_integrity_failure(
    verdict: Any,
    stage: str,
    calls: dict[str, int],
    *,
    diagnostic: str | None = None,
) -> None:
    assert verdict.status == "integrity_failed"
    assert verdict.integrity_ok is False
    assert verdict.failure_stage == stage
    if diagnostic is not None:
        assert verdict.diagnostic == diagnostic
    _assert_empty_comparison(verdict)
    assert calls == dict.fromkeys(calls, 0)


def test_control_real_chain_formula_attempt_is_valid(tmp_path: Path) -> None:
    """GREEN CONTROL: fixture chain is real + valid before replay symbols exist."""
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "control")
    signer = load_identity(settings).signer
    parts = formula_bundle_parts(signing=signer)
    draft = AttemptDraft(
        occurred_at=_TIME,
        route=AttemptRoute.VERIFY_FORMULA,
        http_status=200,
        outcome=AttemptOutcome.VERIFIED,
        artifacts=AttemptArtifacts(raw_spec=_RAW_FORMULA_SPEC, verdict=parts.bundle.verdict),
        plot=parts.bundle,
    )
    bundle = materialize_attempt_bundle(draft, signer, nonce="8" * 32)
    authenticated = attestation.verify_vcert_v03(
        parts.bundle.vcert_envelope,
        {signer.keyid: signer.public_key},
        require_canonical_envelope=True,
        expected_keyid_hint=signer.keyid,
    )

    assert bundle.manifest.route is AttemptRoute.VERIFY_FORMULA
    assert bundle.manifest.outcome is AttemptOutcome.VERIFIED
    assert tuple(binding.role for binding in bundle.manifest.artifacts) == (
        BlobKind.RAW_SPEC,
        BlobKind.VERDICT,
    )
    assert tuple(binding.role for binding in bundle.manifest.plot_artifacts) == tuple(
        role for role, _name in _FORMULA_BINDING_FIELDS
    )
    assert authenticated.certificate == parts.certificate


def test_v01_absent_trust_pin_stops_before_every_formula_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    verdict = _formula_replay()(fixture.snapshot, {}, limits=fixture.settings.limits)

    assert verdict.status == "untrusted_key"
    assert verdict.failure_stage == "trust"
    assert verdict.trusted_keyid is None
    assert calls == dict.fromkeys(calls, 0)


def test_v02_attempt_address_predicates_precede_trust_and_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    payload_limit = len(fixture.snapshot.attempt_payload) - 1
    payload_limits = msgspec.structs.replace(
        fixture.settings.limits,
        max_attestation_bytes=payload_limit,
    )
    envelope_limit = attestation.envelope_byte_limit(
        len(fixture.snapshot.attempt_payload),
        payload_type=ATTEMPT_PAYLOAD_TYPE,
    )
    oversized_envelope = fixture.snapshot.attempt_envelope + b" " * (
        envelope_limit - len(fixture.snapshot.attempt_envelope) + 1
    )
    envelope_snapshot = replace(
        fixture.snapshot,
        attempt_id=hashlib.sha256(oversized_envelope).hexdigest(),
        attempt_envelope=oversized_envelope,
    )
    envelope_limits = msgspec.structs.replace(
        fixture.settings.limits,
        max_attestation_bytes=len(fixture.snapshot.attempt_payload),
    )
    cases = (
        (fixture.snapshot, payload_limits),
        (envelope_snapshot, envelope_limits),
        (replace(fixture.snapshot, attempt_id="0" * 64), fixture.settings.limits),
        (
            replace(fixture.snapshot, keyid=_different_keyid(fixture.snapshot.keyid)),
            fixture.settings.limits,
        ),
    )

    for snapshot, limits in cases:
        verdict = _formula_replay()(snapshot, {}, limits=limits)
        assert verdict.status == "integrity_failed"
        assert verdict.failure_stage == "attempt_address"
    assert calls == dict.fromkeys(calls, 0)


def test_v03_attempt_signature_failure_stops_before_manifest_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    # DSSE signs the pre-authentication encoding, not the envelope bytes, so the attempt layer
    # accepts envelope reserialization. Flipping a signature byte is what the signature stage owns.
    document = json.loads(fixture.snapshot.attempt_envelope)
    signature = bytearray(base64.b64decode(document["signatures"][0]["sig"]))
    signature[0] ^= 0x01
    document["signatures"][0]["sig"] = base64.b64encode(bytes(signature)).decode("ascii")
    envelope = json.dumps(document, separators=(",", ":")).encode("utf-8")
    snapshot = replace(
        fixture.snapshot,
        attempt_id=hashlib.sha256(envelope).hexdigest(),
        attempt_envelope=envelope,
    )

    _assert_integrity_failure(_run(fixture, snapshot), "attempt_signature", calls)


def test_v04_stored_attempt_payload_must_equal_authenticated_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    snapshot = replace(
        fixture.snapshot,
        attempt_payload=fixture.snapshot.attempt_payload + b" ",
    )

    _assert_integrity_failure(_run(fixture, snapshot), "attempt_signature", calls)


def test_v05_invalid_and_noncanonical_attempt_payloads_fail_at_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)

    for payload in (b"{", fixture.snapshot.attempt_payload + b" "):
        verdict = _run(fixture, _resign_payload(fixture, payload))
        _assert_integrity_failure(verdict, "attempt_manifest", calls)


def test_v06_impossible_attempt_timestamp_fails_at_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    manifest = msgspec.structs.replace(
        fixture.bundle.manifest,
        occurred_at="2026-02-30T01:02:03.456789Z",
    )

    _assert_integrity_failure(
        _run(fixture, _resign_manifest(fixture, manifest)),
        "attempt_manifest",
        calls,
    )


def test_v07_attempt_status_must_match_closed_outcome_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    manifest = msgspec.structs.replace(fixture.bundle.manifest, http_status=201)

    _assert_integrity_failure(
        _run(fixture, _resign_manifest(fixture, manifest)),
        "attempt_manifest",
        calls,
    )


def test_v08_each_attempt_binding_tuple_rejects_duplicate_roles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    manifest = fixture.bundle.manifest
    duplicate_artifacts = (
        manifest.artifacts[0],
        msgspec.structs.replace(manifest.artifacts[1], role=manifest.artifacts[0].role),
    )
    duplicate_plot = (
        manifest.plot_artifacts[0],
        msgspec.structs.replace(
            manifest.plot_artifacts[1],
            role=manifest.plot_artifacts[0].role,
        ),
        *manifest.plot_artifacts[2:],
    )

    for changed in (
        msgspec.structs.replace(manifest, artifacts=duplicate_artifacts),
        msgspec.structs.replace(manifest, plot_artifacts=duplicate_plot),
    ):
        _assert_integrity_failure(
            _run(fixture, _resign_manifest(fixture, changed)),
            "attempt_manifest",
            calls,
        )


def test_v09_attempt_decoder_is_closed_and_duplicate_key_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    manifest = fixture.bundle.manifest
    object_payload = json.loads(fixture.snapshot.attempt_payload)
    object_payload["extra"] = 1
    unknown_field = _ENCODER.encode(object_payload)
    duplicate_key = fixture.snapshot.attempt_payload.replace(
        b'"version":"attempt-0.1"',
        b'"version":"attempt-0.1","version":"attempt-0.1"',
        1,
    )
    cases = (
        _ENCODER.encode(msgspec.structs.replace(manifest, version=cast("Any", "attempt-9.9"))),
        _ENCODER.encode(msgspec.structs.replace(manifest, route=cast("Any", "/unknown"))),
        unknown_field,
        duplicate_key,
    )

    for payload in cases:
        _assert_integrity_failure(
            _run(fixture, _resign_payload(fixture, payload)),
            "attempt_manifest",
            calls,
        )


def test_v10_manifest_keyid_mismatch_has_its_own_formula_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    manifest = msgspec.structs.replace(
        fixture.bundle.manifest,
        keyid=_different_keyid(fixture.signer.keyid),
    )

    _assert_integrity_failure(
        _run(fixture, _resign_manifest(fixture, manifest)),
        "attempt_manifest",
        calls,
    )


def test_v10_verifier_version_bounds_and_unicode_are_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)

    for version in ("", "x" * 129):
        manifest = msgspec.structs.replace(fixture.bundle.manifest, verifier_version=version)
        _assert_integrity_failure(
            _run(fixture, _resign_manifest(fixture, manifest)),
            "attempt_manifest",
            calls,
        )

    mirrored = replay._ATTEMPT_DECODER.decode(fixture.snapshot.attempt_payload)
    hostile = msgspec.structs.replace(mirrored, verifier_version="\ud800")
    with pytest.raises(replay._ReplayFailureError, match="not valid UTF-8"):
        replay._validate_manifest(hostile, trusted_keyid=fixture.signer.keyid)
    assert calls == dict.fromkeys(calls, 0)


def test_v11_observed_attempt_carrier_must_match_authenticated_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    artifacts = replace(
        fixture.snapshot.artifacts,
        raw_spec=cast("bytes", fixture.snapshot.artifacts.raw_spec) + b" ",
    )
    snapshot = replace(fixture.snapshot, artifacts=artifacts)

    _assert_integrity_failure(_run(fixture, snapshot), "attempt_artifacts", calls)


def test_v12_every_formula_plot_carrier_is_bound_before_plot_authentication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)

    for _role, name in _FORMULA_BINDING_FIELDS:
        original = cast("bytes", getattr(fixture.snapshot.plot, name))
        plot = _replace_plot(fixture, **{name: _mutate(original)})
        snapshot = replace(fixture.snapshot, plot=plot)
        _assert_integrity_failure(_run(fixture, snapshot), "plot_artifacts", calls)


def test_v13_formula_binding_order_roles_and_digests_are_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    bindings = fixture.bundle.manifest.plot_artifacts
    role_swap = (
        msgspec.structs.replace(bindings[0], role=bindings[1].role),
        msgspec.structs.replace(bindings[1], role=bindings[0].role),
        *bindings[2:],
    )
    digest_tamper = (
        msgspec.structs.replace(bindings[0], digest="sha256:" + "0" * 64),
        *bindings[1:],
    )
    dataset_role = (
        msgspec.structs.replace(bindings[0], role=BlobKind.RAW_CSV),
        *bindings[1:],
    )

    for changed in (role_swap, digest_tamper, dataset_role):
        manifest = msgspec.structs.replace(
            fixture.bundle.manifest,
            plot_artifacts=changed,
        )
        _assert_integrity_failure(
            _run(fixture, _resign_manifest(fixture, manifest)),
            "plot_artifacts",
            calls,
        )


@pytest.mark.parametrize(
    "route",
    (AttemptRoute.VERIFY_AND_RENDER, AttemptRoute.PROPOSE_SPEC),
)
def test_v14_v15_dataset_routes_cannot_attach_formula_plots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route: AttemptRoute,
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    manifest = msgspec.structs.replace(fixture.bundle.manifest, route=route)

    _assert_integrity_failure(
        _run(fixture, _resign_manifest(fixture, manifest)),
        "attempt_outcome",
        calls,
    )


def test_v16_formula_replay_requires_verified_attempt_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    manifest = msgspec.structs.replace(
        fixture.bundle.manifest,
        outcome=AttemptOutcome.REJECTED,
        http_status=200,
    )

    _assert_integrity_failure(
        _run(fixture, _resign_manifest(fixture, manifest)),
        "attempt_outcome",
        calls,
    )


@pytest.mark.parametrize("field", ("verdict", "raw_spec"))
def test_v17_verified_formula_attempt_requires_both_observations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    artifacts = replace(fixture.snapshot.artifacts, **{field: None})
    snapshot = replace(fixture.snapshot, artifacts=artifacts)
    manifest = msgspec.structs.replace(
        fixture.bundle.manifest,
        artifacts=_artifact_bindings(artifacts),
    )
    resigned = _resign_manifest(fixture, manifest, snapshot=snapshot)

    _assert_integrity_failure(_run(fixture, resigned), "attempt_outcome", calls)


@pytest.mark.parametrize(
    "field",
    ("model_request", "model_response", "model_reply"),
)
def test_v18_formula_route_refuses_every_model_trace_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    artifacts = replace(fixture.snapshot.artifacts, **{field: b"trace"})
    snapshot = replace(fixture.snapshot, artifacts=artifacts)
    manifest = msgspec.structs.replace(
        fixture.bundle.manifest,
        artifacts=_artifact_bindings(artifacts),
    )
    resigned = _resign_manifest(fixture, manifest, snapshot=snapshot)

    _assert_integrity_failure(_run(fixture, resigned), "attempt_outcome", calls)


@pytest.mark.parametrize("field", ("raw_csv", "raw_manifest"))
def test_v19_resigned_formula_attempt_refuses_dataset_observations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    artifacts = replace(fixture.snapshot.artifacts, **{field: b"dataset-observation"})
    snapshot = replace(fixture.snapshot, artifacts=artifacts)
    manifest = msgspec.structs.replace(
        fixture.bundle.manifest,
        artifacts=_artifact_bindings(artifacts),
    )
    resigned = _resign_manifest(fixture, manifest, snapshot=snapshot)

    _assert_integrity_failure(
        _run(fixture, resigned),
        "attempt_outcome",
        calls,
        diagnostic="formula attempt observed dataset input bytes its route never reads",
    )


def test_v19b_resigned_formula_proposer_attempt_binds_its_reply_to_the_decoder_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Archive refuses this shape before signing, so only a re-signed occurrence reaches replay.

    That is exactly the key holder the replay guard exists for: the two engines authenticate
    independently, so replay may not inherit the publish path's refusal.
    """
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    artifacts = replace(
        fixture.snapshot.artifacts,
        model_request=b"request",
        model_response=b"response",
        model_reply=b"a reply the decoder never saw",
    )
    snapshot = replace(fixture.snapshot, artifacts=artifacts)
    manifest = msgspec.structs.replace(
        fixture.bundle.manifest,
        route=AttemptRoute.PROPOSE_FORMULA,
        artifacts=_artifact_bindings(artifacts),
    )
    resigned = _resign_manifest(fixture, manifest, snapshot=snapshot)

    _assert_integrity_failure(
        _run(fixture, resigned),
        "attempt_outcome",
        calls,
        diagnostic="attempt model reply differs from the exact raw spec handed to decode",
    )


def test_v19b_control_the_same_proposer_occurrence_replays_when_the_reply_is_the_spec(
    tmp_path: Path,
) -> None:
    """Isolate the refusal above to `model_reply` alone: the route swap itself must replay clean."""
    fixture = _fixture(tmp_path)
    artifacts = replace(
        fixture.snapshot.artifacts,
        model_request=b"request",
        model_response=b"response",
        model_reply=fixture.snapshot.artifacts.raw_spec,
    )
    snapshot = replace(fixture.snapshot, artifacts=artifacts)
    manifest = msgspec.structs.replace(
        fixture.bundle.manifest,
        route=AttemptRoute.PROPOSE_FORMULA,
        artifacts=_artifact_bindings(artifacts),
    )

    assert _run(fixture, _resign_manifest(fixture, manifest, snapshot=snapshot)).status == "exact"


def test_v20_authenticated_attempt_plot_id_must_name_nested_formula_plot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    manifest = msgspec.structs.replace(fixture.bundle.manifest, plot_id="0" * 64)

    _assert_integrity_failure(
        _run(fixture, _resign_manifest(fixture, manifest)),
        "attempt_plot",
        calls,
    )


def test_v21_formula_plot_signer_must_equal_attempt_signer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    # The oracle builder runs the real chain, so it must finish before the bombs are armed.
    other = formula_bundle_parts()
    calls = _arm_downstream_bombs(monkeypatch)
    plot = _replace_plot(
        fixture,
        keyid=other.bundle.keyid,
        public_key=other.bundle.public_key,
    )
    snapshot = _rebind(fixture, plot)

    _assert_integrity_failure(_run(fixture, snapshot), "attempt_plot", calls)


def test_v22_formula_attempt_and_plot_share_only_exact_verdict_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    artifacts = replace(
        fixture.snapshot.artifacts,
        verdict=cast("bytes", fixture.snapshot.artifacts.verdict) + b" ",
    )
    snapshot = replace(fixture.snapshot, artifacts=artifacts)
    manifest = msgspec.structs.replace(
        fixture.bundle.manifest,
        artifacts=_artifact_bindings(artifacts),
    )
    resigned = _resign_manifest(fixture, manifest, snapshot=snapshot)

    _assert_integrity_failure(_run(fixture, resigned), "attempt_plot", calls)


def test_v23_formula_plot_address_guards_have_ratified_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    id_plot = _replace_plot(fixture, plot_id="0" * 64)
    id_snapshot = _rebind(fixture, id_plot)

    payload_limit = len(fixture.snapshot.plot.vcert_payload) - 1
    payload_limits = msgspec.structs.replace(
        fixture.settings.limits,
        max_attestation_bytes=payload_limit,
    )

    envelope_limit = attestation.envelope_byte_limit(
        len(fixture.snapshot.plot.vcert_payload),
        payload_type=attestation.VCERT_V03_PAYLOAD_TYPE,
    )
    envelope = fixture.snapshot.plot.vcert_envelope + b" " * (
        envelope_limit - len(fixture.snapshot.plot.vcert_envelope) + 1
    )
    envelope_plot = _replace_plot(
        fixture,
        plot_id=hashlib.sha256(envelope).hexdigest(),
        vcert_envelope=envelope,
    )
    envelope_snapshot = _rebind(fixture, envelope_plot)
    envelope_limits = msgspec.structs.replace(
        fixture.settings.limits,
        max_attestation_bytes=len(fixture.snapshot.plot.vcert_payload),
    )

    for snapshot, limits in (
        (id_snapshot, fixture.settings.limits),
        (fixture.snapshot, payload_limits),
        (envelope_snapshot, envelope_limits),
    ):
        _assert_integrity_failure(
            _run(fixture, snapshot, limits=limits),
            "plot_address",
            calls,
        )


def test_v24a_formula_plot_key_address_guard_is_total_in_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    plot = _replace_plot(
        fixture,
        keyid=_different_keyid(fixture.snapshot.plot.keyid),
    )
    archived_verdict = replay._decode_verdict(
        fixture.snapshot.plot.verdict,
        trusted_keyid=fixture.signer.keyid,
    )

    with pytest.raises(replay._ReplayFailureError) as caught:
        replay._authenticate_formula_plot(
            plot,
            archived_verdict,
            _trusted(fixture),
            fixture.settings.limits,
            trusted_keyid=fixture.signer.keyid,
        )
    assert caught.value.status == "integrity_failed"
    assert caught.value.stage == "plot_address"
    assert calls == dict.fromkeys(calls, 0)


def test_v24b_public_graph_preempts_plot_key_address_at_attempt_plot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    plot = _replace_plot(
        fixture,
        keyid=_different_keyid(fixture.snapshot.plot.keyid),
    )
    snapshot = replace(fixture.snapshot, plot=plot)

    _assert_integrity_failure(_run(fixture, snapshot), "attempt_plot", calls)


def test_v25_bad_v03_signature_stops_before_formula_content_decode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    # A padded envelope fails the canonical form; a foreign signer under the archived keyid fails
    # the cryptography itself. Both are the same refusal, and neither reaches the content decode.
    foreign = attestation.sign_vcert_v03(
        fixture.parts.certificate,
        signer().private_key,
        keyid=fixture.signer.keyid,
    )
    for envelope in (fixture.snapshot.plot.vcert_envelope + b" ", foreign):
        plot = _replace_plot(
            fixture,
            plot_id=hashlib.sha256(envelope).hexdigest(),
            vcert_envelope=envelope,
        )
        snapshot = _rebind(fixture, plot)
        _assert_integrity_failure(
            _run(fixture, snapshot),
            "plot_signature",
            calls,
            diagnostic="VCert v0.3 envelope failed caller-pinned signature verification",
        )


def test_v26_formula_auth_refuses_v02_and_dataset_family_v03(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    v02_payload = vcert.vcert_bytes(dataset_certificate())
    v02_envelope = attestation.sign_dsse(
        v02_payload,
        fixture.signer.private_key,
        keyid=fixture.signer.keyid,
        payload_type=attestation.VCERT_V03_PAYLOAD_TYPE,
        max_payload_bytes=fixture.settings.limits.max_attestation_bytes,
    )
    dataset_v03 = dataset_v03_certificate()
    dataset_v03_payload = vcert.vcert_v03_bytes(dataset_v03)
    dataset_v03_envelope = attestation.sign_vcert_v03(
        dataset_v03,
        fixture.signer.private_key,
        keyid=fixture.signer.keyid,
    )
    cases = (
        (v02_payload, v02_envelope),
        (dataset_v03_payload, dataset_v03_envelope),
    )

    for payload, envelope in cases:
        plot = _replace_plot(
            fixture,
            plot_id=hashlib.sha256(envelope).hexdigest(),
            vcert_payload=payload,
            vcert_envelope=envelope,
        )
        snapshot = _rebind(fixture, plot)
        _assert_integrity_failure(_run(fixture, snapshot), "plot_signature", calls)


def test_v27_v03_payload_under_v02_wrapper_refuses_at_exact_decoder_control() -> None:
    """GREEN CONTROL: reverse cross-family wrapper refusal predates formula replay."""
    parts = formula_bundle_parts()
    payload = vcert.vcert_v03_bytes(parts.certificate)
    envelope = attestation.sign_dsse(
        payload,
        parts.signer.private_key,
        keyid=parts.signer.keyid,
        payload_type=attestation.VCERT_PAYLOAD_TYPE,
        max_payload_bytes=DEFAULT_LIMITS.max_attestation_bytes,
    )

    with pytest.raises(attestation.AttestationError, match=r"not a valid VCert v0\.2"):
        attestation.verify_vcert(envelope, {parts.signer.keyid: parts.signer.public_key})


def test_v28_authenticated_v03_payload_must_be_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    payload = fixture.snapshot.plot.vcert_payload + b" "
    envelope = attestation.sign_dsse(
        payload,
        fixture.signer.private_key,
        keyid=fixture.signer.keyid,
        payload_type=attestation.VCERT_V03_PAYLOAD_TYPE,
        max_payload_bytes=fixture.settings.limits.max_attestation_bytes,
    )
    plot = _replace_plot(
        fixture,
        plot_id=hashlib.sha256(envelope).hexdigest(),
        vcert_payload=payload,
        vcert_envelope=envelope,
    )
    snapshot = _rebind(fixture, plot)

    _assert_integrity_failure(_run(fixture, snapshot), "plot_signature", calls)


def test_v29_stored_v03_payload_must_equal_authenticated_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    plot = _replace_plot(
        fixture,
        vcert_payload=fixture.snapshot.plot.vcert_payload + b" ",
    )
    snapshot = _rebind(fixture, plot)

    _assert_integrity_failure(_run(fixture, snapshot), "plot_signature", calls)


def test_v30_v03_payload_type_reaches_ceiling_and_exact_wrapper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    original_limit = attestation.envelope_byte_limit
    original_v03 = attestation.verify_vcert_v03
    original_certificate_verify = attestation._verify_certificate_envelope
    calls: dict[str, Any] = {
        "ceiling_types": [],
        "wrapper": 0,
        "verify_types": [],
        "v02": 0,
    }

    def limit_spy(max_payload_bytes: int, *, payload_type: str) -> int:
        cast("list[str]", calls["ceiling_types"]).append(payload_type)
        return original_limit(max_payload_bytes, payload_type=payload_type)

    def v03_spy(*args: Any, **kwargs: Any) -> object:
        calls["wrapper"] += 1
        return original_v03(*args, **kwargs)

    def certificate_verify_spy(*args: Any, **kwargs: Any) -> object:
        cast("list[str]", calls["verify_types"]).append(cast("str", kwargs["payload_type"]))
        return original_certificate_verify(*args, **kwargs)

    def v02_bomb(*_args: object, **_kwargs: object) -> NoReturn:
        calls["v02"] += 1
        msg = "formula replay selected the v0.2 wrapper"
        raise AssertionError(msg)

    monkeypatch.setattr(attestation, "envelope_byte_limit", limit_spy)
    monkeypatch.setattr(attestation, "verify_vcert_v03", v03_spy)
    monkeypatch.setattr(attestation, "_verify_certificate_envelope", certificate_verify_spy)
    monkeypatch.setattr(attestation, "verify_vcert", v02_bomb)

    verdict = _run(fixture)
    assert verdict.status == "exact"
    assert calls == {
        # Each envelope is measured twice: once by replay, once inside the attestation verifier.
        "ceiling_types": [
            ATTEMPT_PAYLOAD_TYPE,
            ATTEMPT_PAYLOAD_TYPE,
            attestation.VCERT_V03_PAYLOAD_TYPE,
            attestation.VCERT_V03_PAYLOAD_TYPE,
        ],
        "wrapper": 1,
        "verify_types": [attestation.VCERT_V03_PAYLOAD_TYPE],
        "v02": 0,
    }


def test_v31_stored_formula_source_must_match_certified_raw_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch, include_spec_decode=False)
    plot = _replace_plot(
        fixture,
        formula_source=fixture.snapshot.plot.formula_source + b" ",
    )
    snapshot = _rebind(fixture, plot)

    _assert_integrity_failure(_run(fixture, snapshot), "plot_contents", calls)


def test_v32_canonical_formula_spec_must_match_certified_spec_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch, include_spec_decode=False)
    other_raw = (_ROOT / "examples/formula_good_specs/f01_square.json").read_bytes()
    other_spec = schema.decode_formula_spec(other_raw)
    plot = _replace_plot(fixture, canonical_spec=canon.spec_bytes(other_spec))
    snapshot = _rebind(fixture, plot)

    _assert_integrity_failure(_run(fixture, snapshot), "plot_contents", calls)


def test_v33_stored_formula_table_must_match_certified_raw_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch, include_spec_decode=False)
    plot = _replace_plot(
        fixture,
        plotted_table=fixture.snapshot.plot.plotted_table + b" ",
    )
    snapshot = _rebind(fixture, plot)

    _assert_integrity_failure(_run(fixture, snapshot), "plot_contents", calls)


def test_v34_valid_utf8_script_mutation_reaches_certified_hash_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch, include_spec_decode=False)
    script = fixture.snapshot.plot.matplotlib_script + b" "
    assert script.decode("utf-8")
    plot = _replace_plot(fixture, matplotlib_script=script)
    snapshot = _rebind(fixture, plot)

    _assert_integrity_failure(_run(fixture, snapshot), "plot_contents", calls)


def test_v35_formula_spec_decode_and_canonicality_fail_at_plot_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch, include_spec_decode=False)

    for payload in (b"{", fixture.snapshot.plot.canonical_spec + b" "):
        plot = _replace_plot(fixture, canonical_spec=payload)
        snapshot = _rebind(fixture, plot)
        _assert_integrity_failure(_run(fixture, snapshot), "plot_contents", calls)


def test_v36_formula_verdict_decode_and_canonicality_fail_at_plot_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch, include_spec_decode=False)

    for payload in (b"{", fixture.snapshot.plot.verdict + b" ", b"\xff"):
        plot = _replace_plot(fixture, verdict=payload)
        artifacts = replace(fixture.snapshot.artifacts, verdict=payload)
        snapshot = _rebind(fixture, plot, artifacts=artifacts)
        _assert_integrity_failure(_run(fixture, snapshot), "plot_contents", calls)


def test_v37_archived_verdict_must_be_verify_layer_and_all_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch, include_spec_decode=False)
    verdict = _decoded_verdict(fixture.snapshot.plot.verdict)
    first = verdict.results[0]
    cases = (
        msgspec.structs.replace(verdict, layer="decode"),
        msgspec.structs.replace(
            verdict,
            results=(msgspec.structs.replace(first, status="fail"), *verdict.results[1:]),
        ),
    )

    for changed in cases:
        snapshot = _replace_verdict(fixture, changed)
        _assert_integrity_failure(_run(fixture, snapshot), "plot_contents", calls)

    # The attempt graph owns the verified flag and runs first, so a verdict that fails BOTH the
    # flag and the layer is reported at the earlier stage.
    both = msgspec.structs.replace(verdict, verified=False, layer="decode")
    _assert_integrity_failure(
        _run(fixture, _replace_verdict(fixture, both)),
        "attempt_outcome",
        calls,
        diagnostic="authenticated attempt verdict disagrees with its verified outcome",
    )


def test_v38_verdict_check_sequence_must_equal_certificate_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch, include_spec_decode=False)
    verdict = _decoded_verdict(fixture.snapshot.plot.verdict)
    assert len(verdict.results) > 1
    changed = msgspec.structs.replace(
        verdict,
        results=(verdict.results[1], verdict.results[0], *verdict.results[2:]),
    )
    snapshot = _replace_verdict(fixture, changed)

    _assert_integrity_failure(_run(fixture, snapshot), "plot_contents", calls)


def test_v39_formula_versions_are_canonical_and_equal_certificate_tcb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch, include_spec_decode=False)
    archived_tcb = msgspec.json.decode(
        fixture.snapshot.plot.tool_versions,
        type=vcert.FormulaTcb,
        strict=True,
    )
    different_tcb = msgspec.structs.replace(archived_tcb, canon_version="different")

    for payload in (
        b"{",
        fixture.snapshot.plot.tool_versions + b" ",
        b"\xff",
        _ENCODER.encode(different_tcb),
    ):
        plot = _replace_plot(fixture, tool_versions=payload)
        snapshot = _rebind(fixture, plot)
        _assert_integrity_failure(_run(fixture, snapshot), "plot_contents", calls)


def test_v40_real_chain_formula_replay_is_exact_and_bounded(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    verdict = _run(fixture)

    assert verdict.status == "exact"
    assert verdict.integrity_ok is True
    assert verdict.trusted_keyid == fixture.signer.keyid
    assert verdict.failure_stage is None
    assert verdict.diagnostic == "authenticated formula snapshot recomputed exactly"
    assert (
        verdict.artifact_matches.formula,
        verdict.artifact_matches.spec,
        verdict.artifact_matches.plotted_table,
        verdict.artifact_matches.matplotlib_script,
    ) == (True, True, True, True)
    assert verdict.payload_match is True
    assert verdict.version_match is True
    assert verdict.drift == ()
    assert verdict.exact is True
    assert not hasattr(verdict, "svg_match")
    encoded = msgspec.json.encode(verdict)
    assert fixture.snapshot.plot.formula_source not in encoded
    assert fixture.snapshot.plot.matplotlib_script not in encoded


def _assert_recomputation_failure(verdict: Any) -> None:
    assert verdict.status == "recomputation_failed"
    assert verdict.integrity_ok is True
    assert verdict.failure_stage == "recomputation"
    assert verdict.exact is False


def _assert_bounded_recomputation_failure(verdict: Any, diagnostic: str) -> None:
    """A chain stage that never reached comparison reports the empty comparison payload."""
    _assert_recomputation_failure(verdict)
    assert verdict.diagnostic == diagnostic
    _assert_empty_comparison(verdict)


def test_v41_verify_exception_is_a_bounded_recomputation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)

    def raise_verify(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "verify fault"
        raise ValueError(msg)

    monkeypatch.setattr(checks, "verify_formula_run", raise_verify)
    verdict = _run(fixture)
    _assert_bounded_recomputation_failure(
        verdict, "archived inputs could not be recomputed: ValueError"
    )


def test_v41_failed_formula_report_stops_before_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    failure = checks.make_result(
        "formula.grammar_allowed",
        status="fail",
        message="forced failure",
    )
    run = checks.FormulaVerificationRun(
        report=checks.VerificationReport(results=(failure,)),
        trace=checks.FormulaVerificationTrace(),
        evidence=None,
    )
    prepare_calls = 0

    def failed_verify(*_args: object, **_kwargs: object) -> checks.FormulaVerificationRun:
        return run

    def prepare_bomb(*_args: object, **_kwargs: object) -> NoReturn:
        nonlocal prepare_calls
        prepare_calls += 1
        msg = "failed report reached preparation"
        raise AssertionError(msg)

    monkeypatch.setattr(checks, "verify_formula_run", failed_verify)
    monkeypatch.setattr(formula_prepare, "prepare_formula", prepare_bomb)
    verdict = _run(fixture)
    _assert_bounded_recomputation_failure(
        verdict, "archived inputs no longer pass current core verification"
    )
    assert prepare_calls == 0


def test_v41_prepare_exception_is_a_bounded_recomputation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)

    def raise_prepare(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "prepare fault"
        raise ValueError(msg)

    monkeypatch.setattr(formula_prepare, "prepare_formula", raise_prepare)
    verdict = _run(fixture)
    _assert_bounded_recomputation_failure(
        verdict, "archived inputs could not be prepared: ValueError"
    )


def test_v41_missing_prepared_formula_stops_before_emission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    evidence = checks.verify_formula_run(fixture.parts.spec).require_evidence()
    preparation = formula_prepare.prepare_formula(fixture.parts.spec, evidence)
    missing = replace(preparation, prepared=None)
    emit_calls = 0

    def missing_prepare(*_args: object, **_kwargs: object) -> formula_prepare.FormulaPreparationRun:
        return missing

    def emit_bomb(*_args: object, **_kwargs: object) -> NoReturn:
        nonlocal emit_calls
        emit_calls += 1
        msg = "missing prepared formula reached emission"
        raise AssertionError(msg)

    monkeypatch.setattr(formula_prepare, "prepare_formula", missing_prepare)
    monkeypatch.setattr(matplotlib_script, "emit_matplotlib_script", emit_bomb)
    verdict = _run(fixture)
    _assert_bounded_recomputation_failure(
        verdict, "archived inputs no longer pass current formal verification"
    )
    assert emit_calls == 0


def test_v41_emit_exception_is_a_bounded_recomputation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)

    def raise_emit(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "emit fault"
        raise ValueError(msg)

    monkeypatch.setattr(matplotlib_script, "emit_matplotlib_script", raise_emit)
    verdict = _run(fixture)
    _assert_bounded_recomputation_failure(
        verdict, "archived inputs could not be emitted: ValueError"
    )


def test_v41_missing_emitted_artifact_stops_before_certificate_builder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    evidence = checks.verify_formula_run(fixture.parts.spec).require_evidence()
    preparation = formula_prepare.prepare_formula(fixture.parts.spec, evidence)
    prepared = cast("formula_prepare.PreparedFormula", preparation.prepared)
    emission = matplotlib_script.emit_matplotlib_script(prepared)
    missing = replace(emission, artifact=None)
    build_calls = 0

    def missing_emit(*_args: object, **_kwargs: object) -> matplotlib_script.MatplotlibScriptRun:
        return missing

    def build_bomb(*_args: object, **_kwargs: object) -> NoReturn:
        nonlocal build_calls
        build_calls += 1
        msg = "missing artifact reached certificate builder"
        raise AssertionError(msg)

    monkeypatch.setattr(matplotlib_script, "emit_matplotlib_script", missing_emit)
    monkeypatch.setattr(vcert, "build_formula_certificate", build_bomb)
    verdict = _run(fixture)
    _assert_bounded_recomputation_failure(
        verdict, "archived inputs no longer emit an admitted matplotlib script"
    )
    assert build_calls == 0


def test_v41_certificate_builder_exception_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)

    def raise_build(*_args: object, **_kwargs: object) -> NoReturn:
        msg = "builder fault"
        raise ValueError(msg)

    monkeypatch.setattr(vcert, "build_formula_certificate", raise_build)
    verdict = _run(fixture)
    _assert_bounded_recomputation_failure(
        verdict, "archived inputs could not be certified: ValueError"
    )


@pytest.mark.parametrize("field", ("formula", "spec", "plotted_table", "matplotlib_script"))
def test_v42_each_fresh_formula_hash_has_an_independent_match_bit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    fixture = _fixture(tmp_path)
    original = vcert.build_formula_certificate

    def changed_builder(*args: Any, **kwargs: Any) -> vcert.VCertV03:
        certificate = original(*args, **kwargs)
        if field == "formula":
            source = msgspec.structs.replace(
                cast("vcert.FormulaSourceCert", certificate.source),
                formula_hash="sha256:" + "0" * 64,
            )
            return msgspec.structs.replace(certificate, source=source)
        if field == "spec":
            return msgspec.structs.replace(certificate, spec_hash="sha256:" + "0" * 64)
        if field == "plotted_table":
            return msgspec.structs.replace(
                certificate,
                plotted_table_hash="sha256:" + "0" * 64,
            )
        artifact = msgspec.structs.replace(
            cast("vcert.MatplotlibScriptArtifactCert", certificate.artifact),
            matplotlib_script_hash="sha256:" + "0" * 64,
        )
        return msgspec.structs.replace(certificate, artifact=artifact)

    monkeypatch.setattr(vcert, "build_formula_certificate", changed_builder)
    verdict = _run(fixture)
    _assert_recomputation_failure(verdict)
    observed = {
        "formula": verdict.artifact_matches.formula,
        "spec": verdict.artifact_matches.spec,
        "plotted_table": verdict.artifact_matches.plotted_table,
        "matplotlib_script": verdict.artifact_matches.matplotlib_script,
    }
    assert observed == {
        "formula": field != "formula",
        "spec": field != "spec",
        "plotted_table": field != "plotted_table",
        "matplotlib_script": field != "matplotlib_script",
    }


def test_v43_payload_mismatch_is_independent_from_hash_and_version_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    original = vcert.build_formula_certificate

    def changed_checks(*args: Any, **kwargs: Any) -> vcert.VCertV03:
        certificate = original(*args, **kwargs)
        return msgspec.structs.replace(certificate, checks=tuple(reversed(certificate.checks)))

    monkeypatch.setattr(vcert, "build_formula_certificate", changed_checks)
    verdict = _run(fixture)
    _assert_recomputation_failure(verdict)
    assert (
        verdict.artifact_matches.formula,
        verdict.artifact_matches.spec,
        verdict.artifact_matches.plotted_table,
        verdict.artifact_matches.matplotlib_script,
    ) == (True, True, True, True)
    assert verdict.version_match is True
    assert verdict.payload_match is False


def test_v44_tcb_only_drift_has_matching_hashes_and_mismatching_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    monkeypatch.setattr(vcert, "__version__", "replay-drift")

    verdict = _run(fixture)
    assert verdict.status == "drift"
    assert verdict.failure_stage is None
    assert (
        verdict.artifact_matches.formula,
        verdict.artifact_matches.spec,
        verdict.artifact_matches.plotted_table,
        verdict.artifact_matches.matplotlib_script,
    ) == (True, True, True, True)
    assert verdict.version_match is False
    assert verdict.payload_match is False
    assert [(item.field, item.archived, item.current) for item in verdict.drift] == [
        (
            "verifier_version",
            fixture.parts.certificate.tcb.verifier_version,
            "replay-drift",
        )
    ]
    assert verdict.exact is False
    assert (
        verdict.diagnostic == "authenticated artifacts match but the current TCB versions drifted"
    )


def test_v44_script_template_drift_is_reported_on_its_own_tcb_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second TCB field drifts alone, so the drift tuple follows the field, not one fixed row."""
    fixture = _fixture(tmp_path)
    monkeypatch.setattr(matplotlib_script, "SCRIPT_TEMPLATE_VERSION", "replay-template-drift")

    verdict = _run(fixture)
    assert verdict.status == "drift"
    assert verdict.exact is False
    assert [(item.field, item.current) for item in verdict.drift] == [
        ("script_template_version", "replay-template-drift")
    ]


def test_v45_builder_never_receives_archived_tcb_and_counterfactual_erases_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    original = vcert.build_formula_certificate
    seen: list[dict[str, Any]] = []

    def spy(*args: Any, **kwargs: Any) -> vcert.VCertV03:
        seen.append(dict(kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(vcert, "__version__", "replay-drift")
    monkeypatch.setattr(vcert, "build_formula_certificate", spy)
    shipped = _run(fixture)
    assert shipped.status == "drift"
    assert seen == [{}]

    def archived_tcb_builder(
        artifact: matplotlib_script.MatplotlibScriptArtifact,
    ) -> vcert.VCertV03:
        return original(artifact, tcb=cast("vcert.FormulaTcb", fixture.parts.certificate.tcb))

    monkeypatch.setattr(vcert, "build_formula_certificate", archived_tcb_builder)
    counterfactual = _run(fixture)
    assert counterfactual.status == "exact"
    assert counterfactual.payload_match is True
    assert counterfactual.version_match is True


def test_v46_each_stored_carrier_is_nonsteering_after_authentication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    authenticated = replay._authenticate_formula_snapshot(
        fixture.snapshot,
        _trusted(fixture),
        fixture.settings.limits,
    )
    original_verify = checks.verify_formula_run
    original_builder = vcert.build_formula_certificate
    observed_specs: list[object] = []
    fresh_artifacts: list[tuple[bytes, bytes, bytes]] = []

    def verify_spy(spec: schema.FormulaPlotSpec, **kwargs: Any) -> checks.FormulaVerificationRun:
        observed_specs.append(spec)
        return original_verify(spec, **kwargs)

    def builder_spy(
        artifact: matplotlib_script.MatplotlibScriptArtifact,
        **kwargs: Any,
    ) -> vcert.VCertV03:
        certificate = original_builder(artifact, **kwargs)
        fresh_artifacts.append(
            (
                canon.serialize_table(artifact.evidence.plotted_table).encode("utf-8"),
                artifact.matplotlib_script,
                vcert.vcert_v03_bytes(certificate),
            )
        )
        return certificate

    monkeypatch.setattr(checks, "verify_formula_run", verify_spy)
    monkeypatch.setattr(vcert, "build_formula_certificate", builder_spy)
    carriers = (
        ("plot", "formula_source"),
        ("plot", "plotted_table"),
        ("plot", "matplotlib_script"),
        ("plot", "verdict"),
        ("plot", "tool_versions"),
        ("plot", "vcert_payload"),
        ("attempt", "raw_spec"),
    )
    expected = (
        fixture.snapshot.plot.plotted_table,
        fixture.snapshot.plot.matplotlib_script,
        fixture.snapshot.plot.vcert_payload,
    )

    for owner, field in carriers:
        if owner == "plot":
            original = cast("bytes", getattr(fixture.snapshot.plot, field))
            plot = replace(fixture.snapshot.plot, **{field: original + b" "})
            snapshot = replace(fixture.snapshot, plot=plot)
        else:
            original = cast("bytes", getattr(fixture.snapshot.artifacts, field))
            artifacts = replace(fixture.snapshot.artifacts, **{field: original + b" "})
            snapshot = replace(fixture.snapshot, artifacts=artifacts)
        isolated = replace(authenticated, snapshot=snapshot)
        replay._recompute_authenticated_formula(isolated, fixture.settings.limits)
        assert fresh_artifacts[-1] == expected

    assert len(observed_specs) == len(carriers)
    assert all(spec is authenticated.spec for spec in observed_specs)


def test_v47_non_utf8_formula_source_is_digest_only_then_recomputation_mismatch(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    source = msgspec.structs.replace(
        cast("vcert.FormulaSourceCert", fixture.parts.certificate.source),
        formula_hash=canon.hash_formula_source(b"\xff"),
    )
    certificate = msgspec.structs.replace(fixture.parts.certificate, source=source)
    plot = _signed_certificate_plot(fixture, certificate, formula_source=b"\xff")
    snapshot = _rebind(fixture, plot)

    verdict = _run(fixture, snapshot)
    _assert_recomputation_failure(verdict)
    assert verdict.artifact_matches.formula is False
    assert verdict.artifact_matches.spec is True
    assert verdict.artifact_matches.plotted_table is True
    assert verdict.artifact_matches.matplotlib_script is True


def test_v48_closed_formula_and_dataset_selectors_are_hand_stated() -> None:
    assert replay._FORMULA_PLOT_BINDING_FIELDS == (
        ("canonical_spec", "canonical_spec"),
        ("formula_source", "formula_source"),
        ("plotted_table", "plotted_table"),
        ("verdict", "verdict"),
        ("matplotlib_script", "matplotlib_script"),
        ("vcert_payload", "vcert_payload"),
        ("vcert_envelope", "vcert_envelope"),
        ("tool_versions", "tool_versions"),
        ("ed25519_public_key", "public_key"),
    )
    assert replay._FORMULA_PLOT_BYTE_FIELDS == (
        "canonical_spec",
        "formula_source",
        "plotted_table",
        "verdict",
        "matplotlib_script",
        "vcert_payload",
        "vcert_envelope",
        "tool_versions",
        "public_key",
    )
    assert replay._ROUTE_ATTACHES_FORMULA_PLOT == {
        "/verify-and-render": False,
        "/propose-spec": False,
        "/verify-formula": True,
        "/propose-formula": True,
    }
    assert replay._FORMULA_TCB_FIELDS == (
        "verifier_version",
        "z3_version",
        "canon_version",
        "python",
        "msgspec",
        "unidata",
        "grammar_version",
        "numeric_profile",
        "script_template_version",
    )
    assert replay._DATASET_PLOT_BINDING_FIELDS == (
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
    assert replay._ROUTE_ATTACHES_DATASET_PLOT == {
        "/verify-and-render": True,
        "/propose-spec": True,
        "/verify-formula": False,
        "/propose-formula": False,
    }
    # `_BlobRole` is a PEP 695 alias, so the literal members live behind `__value__`.
    assert get_args(replay._BlobRole.__value__) == (
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
        "formula_source",
        "matplotlib_script",
        "model_request",
        "model_response",
        "model_reply",
        "attempt_payload",
        "attempt_envelope",
    )
    assert isinstance(replay._ROUTE_ATTACHES_FORMULA_PLOT, dict)
    assert isinstance(replay._ROUTE_ATTACHES_DATASET_PLOT, dict)


def test_v49_formula_public_types_are_concrete_exact_and_dataset_preserving(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    plot_type = _formula_plot_type()
    snapshot_type = _formula_snapshot_type()
    matches_type = _formula_struct_type("FormulaArtifactHashMatches")
    verdict_type = _formula_struct_type("FormulaReplayVerdict")
    drift_type = _formula_struct_type("FormulaVersionDrift")
    assert tuple(field.name for field in fields(plot_type)) == (
        "plot_id",
        "keyid",
        "canonical_spec",
        "formula_source",
        "plotted_table",
        "verdict",
        "matplotlib_script",
        "vcert_payload",
        "vcert_envelope",
        "tool_versions",
        "public_key",
    )
    assert tuple(field.name for field in fields(snapshot_type)) == (
        "attempt_id",
        "keyid",
        "artifacts",
        "attempt_payload",
        "attempt_envelope",
        "public_key",
        "plot",
    )
    assert matches_type.__struct_fields__ == (
        "formula",
        "spec",
        "plotted_table",
        "matplotlib_script",
    )
    assert verdict_type.__struct_fields__ == (
        "status",
        "integrity_ok",
        "trusted_keyid",
        "failure_stage",
        "diagnostic",
        "artifact_matches",
        "payload_match",
        "version_match",
        "drift",
        "exact",
    )
    assert drift_type.__struct_fields__ == ("field", "archived", "current")
    assert tuple(field.name for field in fields(replay.ReplayPlotSnapshot)) == (
        "plot_id",
        "keyid",
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

    artifacts_subtype = type(
        "ReplayAttemptArtifactsSubclass",
        (replay.ReplayAttemptArtifacts,),
        {},
    )
    artifacts_subclass = artifacts_subtype(
        **{
            field.name: getattr(fixture.snapshot.artifacts, field.name)
            for field in fields(replay.ReplayAttemptArtifacts)
        }
    )
    plot_subtype = type("ReplayFormulaPlotSnapshotSubclass", (plot_type,), {})
    plot_subclass = plot_subtype(
        **{field.name: getattr(fixture.snapshot.plot, field.name) for field in fields(plot_type)}
    )
    snapshot_subtype = type("ReplayFormulaSnapshotSubclass", (snapshot_type,), {})
    snapshot_subclass = snapshot_subtype(
        **{field.name: getattr(fixture.snapshot, field.name) for field in fields(snapshot_type)}
    )

    with pytest.raises(TypeError, match="ReplayAttemptArtifacts"):
        replace(fixture.snapshot, artifacts=artifacts_subclass)
    with pytest.raises(TypeError, match="ReplayFormulaPlotSnapshot"):
        replace(fixture.snapshot, plot=plot_subclass)
    with pytest.raises(TypeError, match="ReplayFormulaSnapshot"):
        _formula_replay()(snapshot_subclass, _trusted(fixture))


def _wire_bytes(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


def _formula_wire(snapshot: Any) -> dict[str, Any]:
    return {
        "attempt_id": snapshot.attempt_id,
        "keyid": snapshot.keyid,
        "attempt_payload": _wire_bytes(snapshot.attempt_payload),
        "attempt_envelope": _wire_bytes(snapshot.attempt_envelope),
        "public_key": _wire_bytes(snapshot.public_key),
        "artifacts": {
            name: None
            if (value := getattr(snapshot.artifacts, name)) is None
            else _wire_bytes(value)
            for name in (
                "raw_csv",
                "raw_manifest",
                "raw_spec",
                "verdict",
                "model_request",
                "model_response",
                "model_reply",
            )
        },
        "plot": {
            "plot_id": snapshot.plot.plot_id,
            "keyid": snapshot.plot.keyid,
            **{
                name: _wire_bytes(getattr(snapshot.plot, name))
                for name in (
                    "canonical_spec",
                    "formula_source",
                    "plotted_table",
                    "verdict",
                    "matplotlib_script",
                    "vcert_payload",
                    "vcert_envelope",
                    "tool_versions",
                    "public_key",
                )
            },
        },
    }


def _dataset_bundle_for_replay(tmp_path: Path) -> AttemptBundle:
    settings, raw_plot = dataset_bundle(tmp_path / "dataset-bundle")
    plot = cast("DatasetPlotBundle", raw_plot)
    signer = load_identity(settings).signer
    draft = AttemptDraft(
        occurred_at=_TIME,
        route=AttemptRoute.VERIFY_AND_RENDER,
        http_status=200,
        outcome=AttemptOutcome.VERIFIED,
        artifacts=AttemptArtifacts(
            raw_csv=plot.raw_csv,
            raw_manifest=plot.raw_manifest,
            raw_spec=_RAW_DATASET_SPEC,
            verdict=plot.verdict,
        ),
        plot=plot,
    )
    return materialize_attempt_bundle(draft, signer, nonce="7" * 32)


def _dataset_wire(bundle: AttemptBundle) -> dict[str, Any]:
    plot = cast("DatasetPlotBundle", bundle.plot)
    return {
        "attempt_id": bundle.attempt_id,
        "keyid": bundle.keyid,
        "attempt_payload": _wire_bytes(bundle.attempt_payload),
        "attempt_envelope": _wire_bytes(bundle.attempt_envelope),
        "public_key": _wire_bytes(bundle.public_key),
        "artifacts": {
            name: None if (value := getattr(bundle.artifacts, name)) is None else _wire_bytes(value)
            for name in (
                "raw_csv",
                "raw_manifest",
                "raw_spec",
                "verdict",
                "model_request",
                "model_response",
                "model_reply",
            )
        },
        "plot": {
            "plot_id": plot.plot_id,
            "keyid": plot.keyid,
            **{
                name: _wire_bytes(getattr(plot, name))
                for name in (
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
            },
        },
    }


def test_v50_formula_replay_fresh_process_never_loads_renderer_or_service(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    wire = tmp_path / "formula-snapshot.json"
    wire.write_text(json.dumps(_formula_wire(fixture.snapshot)), encoding="utf-8")
    program = r"""
import base64
import json
import sys
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
import verifier.replay as replay
assert "verifier.render" not in sys.modules
assert "vl_convert" not in sys.modules
assert not any(name.startswith("verifier.service") for name in sys.modules)
assert "matplotlib" not in sys.modules
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
def b(value):
    return base64.b64decode(value)
artifacts = replay.ReplayAttemptArtifacts(**{
    name: None if value is None else b(value)
    for name, value in data["artifacts"].items()
})
plot_data = data["plot"]
plot = replay.ReplayFormulaPlotSnapshot(
    plot_id=plot_data["plot_id"],
    keyid=plot_data["keyid"],
    **{name: b(value) for name, value in plot_data.items() if name not in {"plot_id", "keyid"}},
)
snapshot = replay.ReplayFormulaSnapshot(
    attempt_id=data["attempt_id"],
    keyid=data["keyid"],
    artifacts=artifacts,
    attempt_payload=b(data["attempt_payload"]),
    attempt_envelope=b(data["attempt_envelope"]),
    public_key=b(data["public_key"]),
    plot=plot,
)
trusted = {data["keyid"]: Ed25519PublicKey.from_public_bytes(b(data["public_key"]))}
assert replay.replay_formula_snapshot(snapshot, trusted).status == "exact"
assert "verifier.render" not in sys.modules
assert "vl_convert" not in sys.modules
assert not any(name.startswith("verifier.service") for name in sys.modules)
# Replay emits the script and never runs it, so matplotlib stays out of the process; Z3 is loaded
# by design, because the formula preparer needs the solver to reproduce the formal evidence.
assert "matplotlib" not in sys.modules
assert "z3" in sys.modules
"""
    completed = subprocess.run(  # noqa: S603 — fixed interpreter + literal program
        [sys.executable, "-c", program, str(wire)],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout == ""
    assert completed.stderr == ""


def test_v50_dataset_replay_fresh_process_loads_renderer_control(tmp_path: Path) -> None:
    """GREEN CONTROL: dataset replay intentionally loads render + vl_convert."""
    bundle = _dataset_bundle_for_replay(tmp_path)
    wire = tmp_path / "dataset-snapshot.json"
    wire.write_text(json.dumps(_dataset_wire(bundle)), encoding="utf-8")
    program = r"""
import base64
import json
import sys
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
import verifier.replay as replay
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
def b(value):
    return base64.b64decode(value)
artifacts = replay.ReplayAttemptArtifacts(**{
    name: None if value is None else b(value)
    for name, value in data["artifacts"].items()
})
plot_data = data["plot"]
plot = replay.ReplayPlotSnapshot(
    plot_id=plot_data["plot_id"],
    keyid=plot_data["keyid"],
    **{name: b(value) for name, value in plot_data.items() if name not in {"plot_id", "keyid"}},
)
snapshot = replay.ReplaySnapshot(
    attempt_id=data["attempt_id"],
    keyid=data["keyid"],
    artifacts=artifacts,
    attempt_payload=b(data["attempt_payload"]),
    attempt_envelope=b(data["attempt_envelope"]),
    public_key=b(data["public_key"]),
    plot=plot,
)
trusted = {data["keyid"]: Ed25519PublicKey.from_public_bytes(b(data["public_key"]))}
assert replay.replay_snapshot(snapshot, trusted).status == "exact"
assert "verifier.render" in sys.modules
assert "vl_convert" in sys.modules
"""
    completed = subprocess.run(  # noqa: S603 — fixed interpreter + literal program
        [sys.executable, "-c", program, str(wire)],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout == ""
    assert completed.stderr == ""


def test_v51_certified_checks_must_be_registered_with_exact_methods(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch, include_spec_decode=False)
    archived = _decoded_verdict(fixture.snapshot.plot.verdict)
    verdict_first = archived.results[0]
    certificate_first = fixture.parts.certificate.checks[0]
    assert verdict_first.method != "z3_smt"
    cases = (
        (
            msgspec.structs.replace(verdict_first, check="formula.unregistered"),
            msgspec.structs.replace(certificate_first, id="formula.unregistered"),
        ),
        (
            msgspec.structs.replace(verdict_first, method="z3_smt"),
            msgspec.structs.replace(certificate_first, method="z3_smt"),
        ),
    )

    for changed_result, changed_check in cases:
        changed_verdict = msgspec.structs.replace(
            archived,
            results=(changed_result, *archived.results[1:]),
        )
        changed_certificate = msgspec.structs.replace(
            fixture.parts.certificate,
            checks=(changed_check, *fixture.parts.certificate.checks[1:]),
        )
        verdict_payload = _ENCODER.encode(changed_verdict)
        plot = _signed_certificate_plot(
            fixture,
            changed_certificate,
            verdict=verdict_payload,
        )
        artifacts = replace(fixture.snapshot.artifacts, verdict=verdict_payload)
        snapshot = _rebind(fixture, plot, artifacts=artifacts)
        _assert_integrity_failure(_run(fixture, snapshot), "plot_contents", calls)


def test_v52_matplotlib_script_requires_utf8_before_certified_hash_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch, include_spec_decode=False)
    script = b"\xff"
    artifact = msgspec.structs.replace(
        cast("vcert.MatplotlibScriptArtifactCert", fixture.parts.certificate.artifact),
        matplotlib_script_hash=canon.hash_matplotlib_script(script),
    )
    certificate = msgspec.structs.replace(fixture.parts.certificate, artifact=artifact)
    plot = _signed_certificate_plot(
        fixture,
        certificate,
        matplotlib_script=script,
    )
    snapshot = _rebind(fixture, plot)

    _assert_integrity_failure(_run(fixture, snapshot), "plot_contents", calls)


def test_v53_attempt_and_formula_tcb_verifier_versions_must_agree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch, include_spec_decode=False)
    tcb = msgspec.structs.replace(
        cast("vcert.FormulaTcb", fixture.parts.certificate.tcb),
        verifier_version="other",
    )
    certificate = msgspec.structs.replace(fixture.parts.certificate, tcb=tcb)
    plot = _signed_certificate_plot(
        fixture,
        certificate,
        tool_versions=_ENCODER.encode(tcb),
    )
    snapshot = _rebind(fixture, plot)

    _assert_integrity_failure(_run(fixture, snapshot), "attempt_plot", calls)


def test_v54_verified_flag_is_checked_independently_of_passing_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A minted verdict can pass every check and still deny its own verified flag."""
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    verdict = msgspec.structs.replace(
        _decoded_verdict(cast("bytes", fixture.snapshot.artifacts.verdict)),
        verified=False,
    )
    snapshot = _replace_verdict(fixture, verdict)

    _assert_integrity_failure(_run(fixture, snapshot), "attempt_outcome", calls)


def test_v55_vcert_envelope_keyid_hint_must_address_the_plot_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The trusted map holds one key, so only the pinned hint rejects a relabelled envelope."""
    fixture = _fixture(tmp_path)
    calls = _arm_downstream_bombs(monkeypatch)
    envelope = attestation.sign_vcert_v03(
        fixture.parts.certificate,
        fixture.signer.private_key,
        keyid=_different_keyid(fixture.signer.keyid),
    )
    plot = _replace_plot(
        fixture,
        plot_id=hashlib.sha256(envelope).hexdigest(),
        vcert_envelope=envelope,
    )
    snapshot = _rebind(fixture, plot)

    _assert_integrity_failure(_run(fixture, snapshot), "plot_signature", calls)
