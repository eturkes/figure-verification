# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M9.8a formula materialization + plotless-attempt acceptance."""

from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
from collections.abc import Callable
from dataclasses import fields, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast, get_args, get_type_hints

import msgspec
import pytest
from msgspec.structs import replace as struct_replace

from formula_plot_bundle_helpers import (
    FormulaBundleParts,
    dataset_bundle,
    dataset_v03_certificate,
    formula_bundle_parts,
)
from verifier import attestation, canon, matplotlib_script, replay, vcert
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.service import archive as archive_module
from verifier.service import audit, pipeline
from verifier.service.archive import (
    ArchiveIntegrityError,
    ArchiveReadLimitError,
    AttemptArtifacts,
    AttemptBundle,
    AttemptDraft,
    AttemptManifest,
    AttemptOutcome,
    AttemptRole,
    AttemptRoute,
    DatasetPlotBundle,
    FormulaPlotBundle,
    PlotBundle,
    PlotSourceKind,
    materialize_attempt_bundle,
    open_archive,
)
from verifier.service.identity import Signer, load_identity
from verifier.service.settings import Settings

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_RAW_DATASET_SPEC = (_ROOT / "examples/good_specs/g01_total_revenue_by_month.json").read_bytes()
_RAW_FORMULA_SPEC = (_ROOT / "examples/formula_good_specs/f02_linear.json").read_bytes()
_TIME = datetime(2026, 8, 14, 1, 2, 3, 456789, tzinfo=UTC)
_ENCODER = msgspec.json.Encoder(order="deterministic")
_FORMULA_ROUTE = "/verify-formula"
_READS_DATASET_INPUTS = True
_OUTCOME_STATUS = {
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
_NONJUDGEMENT_OUTCOMES = tuple(
    outcome
    for outcome in AttemptOutcome
    if outcome not in {AttemptOutcome.VERIFIED, AttemptOutcome.REJECTED}
)

type _ModelRoleSelector = Callable[[AttemptManifest], set[AttemptRole]]


class _FormulaMaterializer(Protocol):
    def __call__(
        self,
        artifact: matplotlib_script.MatplotlibScriptArtifact,
        certificate: vcert.VCertV03,
        envelope: bytes,
        signer: Signer,
        *,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> FormulaPlotBundle: ...


def _formula_route() -> AttemptRoute:
    return AttemptRoute(_FORMULA_ROUTE)


def _formula_materializer() -> _FormulaMaterializer:
    value: object = archive_module.__dict__.get("materialize_formula_plot_bundle")
    assert callable(value), "production formula plot materializer is absent"
    return cast("_FormulaMaterializer", value)


def _route_model_roles() -> dict[AttemptRoute, _ModelRoleSelector]:
    value: object = archive_module.__dict__.get("_ROUTE_MODEL_ROLES")
    assert isinstance(value, dict), "_ROUTE_MODEL_ROLES is absent"
    return cast("dict[AttemptRoute, _ModelRoleSelector]", value)


def _route_plot_sources() -> dict[AttemptRoute, frozenset[PlotSourceKind]]:
    value: object = archive_module.__dict__.get("_ROUTE_PLOT_SOURCES")
    assert isinstance(value, dict), "_ROUTE_PLOT_SOURCES is absent"
    return cast("dict[AttemptRoute, frozenset[PlotSourceKind]]", value)


def _route_reads_dataset_inputs() -> dict[AttemptRoute, bool]:
    value: object = archive_module.__dict__.get("_ROUTE_READS_DATASET_INPUTS")
    assert isinstance(value, dict), "_ROUTE_READS_DATASET_INPUTS is absent"
    return cast("dict[AttemptRoute, bool]", value)


def _model_role_selector(name: str) -> _ModelRoleSelector:
    value: object = archive_module.__dict__.get(name)
    assert callable(value), f"{name} is absent"
    return cast("_ModelRoleSelector", value)


def _formula_rejected_artifacts(settings: Settings) -> AttemptArtifacts:
    raw_spec = b"{"
    return AttemptArtifacts(
        raw_spec=raw_spec,
        verdict=_ENCODER.encode(pipeline.verify_only(raw_spec, settings).verdict),
    )


def _formula_draft(
    settings: Settings,
    *,
    outcome: AttemptOutcome = AttemptOutcome.REJECTED,
    artifacts: AttemptArtifacts | None = None,
    plot: DatasetPlotBundle | None = None,
) -> AttemptDraft:
    return AttemptDraft(
        occurred_at=_TIME,
        route=_formula_route(),
        http_status=_OUTCOME_STATUS[outcome],
        outcome=outcome,
        artifacts=(_formula_rejected_artifacts(settings) if artifacts is None else artifacts),
        plot=plot,
    )


def _manifest_from_draft(draft: AttemptDraft, signer: Signer) -> AttemptManifest:
    return AttemptManifest(
        version="attempt-0.1",
        nonce="0" * 32,
        occurred_at="2026-08-14T01:02:03.456789Z",
        route=draft.route,
        http_status=draft.http_status,
        outcome=draft.outcome,
        plot_id=None if draft.plot is None else draft.plot.plot_id,
        artifacts=archive_module._artifact_bindings(draft.artifacts),
        plot_artifacts=archive_module._plot_bindings(draft.plot),
        keyid=signer.keyid,
        verifier_version="test",
    )


def _dataset_success_attempt(tmp_path: Path) -> tuple[Settings, Signer, AttemptBundle]:
    settings, raw_plot = dataset_bundle(tmp_path / "dataset")
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
    return settings, signer, materialize_attempt_bundle(draft, signer, nonce="1" * 32)


def _formula_success_draft(
    tmp_path: Path,
) -> tuple[Settings, Signer, FormulaBundleParts, AttemptDraft]:
    """Build one verified /verify-formula occurrence whose plot carries the attempt's own signer."""
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "formula-success")
    signer = load_identity(settings).signer
    parts = formula_bundle_parts(signing=signer)
    draft = AttemptDraft(
        occurred_at=_TIME,
        route=_formula_route(),
        http_status=_OUTCOME_STATUS[AttemptOutcome.VERIFIED],
        outcome=AttemptOutcome.VERIFIED,
        artifacts=AttemptArtifacts(raw_spec=_RAW_FORMULA_SPEC, verdict=parts.bundle.verdict),
        plot=parts.bundle,
    )
    return settings, signer, parts, draft


def _resign_bundle(
    base: AttemptBundle,
    signer: Signer,
    manifest: AttemptManifest,
    *,
    artifacts: AttemptArtifacts | None = None,
) -> AttemptBundle:
    payload = _ENCODER.encode(manifest)
    envelope = attestation.sign_dsse(
        payload,
        signer.private_key,
        keyid=signer.keyid,
        payload_type=archive_module.ATTEMPT_PAYLOAD_TYPE,
        max_payload_bytes=DEFAULT_LIMITS.max_attestation_bytes,
    )
    return replace(
        base,
        attempt_id=hashlib.sha256(envelope).hexdigest(),
        manifest=manifest,
        artifacts=base.artifacts if artifacts is None else artifacts,
        attempt_payload=payload,
        attempt_envelope=envelope,
    )


def _replay_snapshot(bundle: AttemptBundle) -> replay.ReplaySnapshot:
    plot = cast("DatasetPlotBundle", bundle.plot)
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


def _arm_signing_bombs(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = {"sign": 0, "envelope_limit": 0}

    def sign_bomb(*_args: object, **_kwargs: object) -> bytes:
        calls["sign"] += 1
        pytest.fail("attempt signing ran after a required pre-signing refusal")

    def envelope_limit_bomb(*_args: object, **_kwargs: object) -> int:
        calls["envelope_limit"] += 1
        pytest.fail("attempt envelope work ran after a required pre-signing refusal")

    monkeypatch.setattr(attestation, "sign_dsse", sign_bomb)
    monkeypatch.setattr(attestation, "envelope_byte_limit", envelope_limit_bomb)
    return calls


def _decoded_audit(output: bytes) -> dict[str, Any]:
    assert output.isascii()
    return cast("dict[str, Any]", json.loads(output))


def _alias_values(alias: Any) -> set[str]:
    return set(cast("tuple[str, ...]", get_args(alias.__value__)))


def test_a1_attempt_route_is_exact() -> None:
    assert {(route.name, route.value) for route in AttemptRoute} == {
        ("VERIFY_AND_RENDER", "/verify-and-render"),
        ("PROPOSE_SPEC", "/propose-spec"),
        ("VERIFY_FORMULA", "/verify-formula"),
    }


def test_a2_attempt_outcome_is_exact() -> None:
    assert {(outcome.name, outcome.value) for outcome in AttemptOutcome} == {
        ("VERIFIED", "verified"),
        ("REJECTED", "rejected"),
        ("DATASET_NOT_FOUND", "dataset_not_found"),
        ("PROPOSER_POLICY", "proposer_policy"),
        ("DATASET_MISMATCH", "dataset_mismatch"),
        ("MODEL_TRANSPORT", "model_transport"),
        ("MODEL_CONTENT_ENCODING", "model_content_encoding"),
        ("MODEL_RESPONSE_TOO_LARGE", "model_response_too_large"),
        ("MODEL_HTTP_STATUS", "model_http_status"),
        ("MODEL_PROMPT_TOKENS", "model_prompt_tokens"),
        ("MODEL_INVALID_ENVELOPE", "model_invalid_envelope"),
        ("MODEL_NO_CHOICES", "model_no_choices"),
        ("MODEL_EMPTY_CONTENT", "model_empty_content"),
    }


def test_a3_formula_route_dataset_plot_refuses_before_signing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, raw_plot = dataset_bundle(tmp_path / "formula-route")
    plot = cast("DatasetPlotBundle", raw_plot)
    calls = _arm_signing_bombs(monkeypatch)
    draft = _formula_draft(settings, outcome=AttemptOutcome.VERIFIED, plot=plot)

    with pytest.raises(
        ArchiveIntegrityError,
        match=r"^attempt manifest route /verify-formula cannot attach a dataset plot$",
    ):
        materialize_attempt_bundle(draft, load_identity(settings).signer, nonce="2" * 32)
    assert calls == {"sign": 0, "envelope_limit": 0}


@pytest.mark.parametrize("route", [AttemptRoute.VERIFY_AND_RENDER, AttemptRoute.PROPOSE_SPEC])
def test_a3_dataset_routes_refuse_a_formula_plot_before_signing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route: AttemptRoute,
) -> None:
    """Cover the direction a dataset-only attempt layer left silent: formula plot, dataset route."""
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / f"formula-plot-{route.name}")
    signer = load_identity(settings).signer
    draft = AttemptDraft(
        occurred_at=_TIME,
        route=route,
        http_status=200,
        outcome=AttemptOutcome.VERIFIED,
        artifacts=_formula_rejected_artifacts(settings),
        plot=formula_bundle_parts().bundle,
    )
    calls = _arm_signing_bombs(monkeypatch)

    with pytest.raises(
        ArchiveIntegrityError,
        match=rf"^attempt manifest route {route.value} cannot attach a formula plot$",
    ):
        materialize_attempt_bundle(draft, signer, nonce="5" * 32)
    assert calls == {"sign": 0, "envelope_limit": 0}


def _route_plot_case(
    route: AttemptRoute,
    dataset_plot: DatasetPlotBundle,
    formula_plot: FormulaPlotBundle,
) -> tuple[AttemptArtifacts, PlotBundle]:
    """Name the observations and plot one route accepts, so only plot presence can be at fault."""
    if route is AttemptRoute.VERIFY_FORMULA:
        return AttemptArtifacts(
            raw_spec=_RAW_FORMULA_SPEC, verdict=formula_plot.verdict
        ), formula_plot
    dataset = AttemptArtifacts(
        raw_csv=dataset_plot.raw_csv,
        raw_manifest=dataset_plot.raw_manifest,
        raw_spec=_RAW_DATASET_SPEC,
        verdict=dataset_plot.verdict,
    )
    if route is AttemptRoute.PROPOSE_SPEC:
        return replace(
            dataset,
            model_request=b"{}",
            model_response=b"{}",
            model_reply=_RAW_DATASET_SPEC,
        ), dataset_plot
    return dataset, dataset_plot


@pytest.mark.parametrize("route", list(AttemptRoute))
@pytest.mark.parametrize("verified", [True, False])
def test_a3_plot_presence_must_match_the_verified_outcome_on_every_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route: AttemptRoute,
    *,
    verified: bool,
) -> None:
    """Both mismatch directions refuse before signing on every route; nothing else is at fault."""
    settings, raw_plot = dataset_bundle(tmp_path / f"presence-{route.name}-{verified}")
    signer = load_identity(settings).signer
    formula_plot = formula_bundle_parts(signing=signer).bundle
    artifacts, plot = _route_plot_case(route, cast("DatasetPlotBundle", raw_plot), formula_plot)
    outcome = AttemptOutcome.VERIFIED if verified else AttemptOutcome.REJECTED
    draft = AttemptDraft(
        occurred_at=_TIME,
        route=route,
        http_status=_OUTCOME_STATUS[outcome],
        outcome=outcome,
        artifacts=artifacts,
        plot=None if verified else plot,
    )
    calls = _arm_signing_bombs(monkeypatch)

    with pytest.raises(
        ArchiveIntegrityError,
        match=r"^attempt manifest plot presence disagrees with its outcome$",
    ):
        materialize_attempt_bundle(draft, signer, nonce="6" * 32)
    assert calls == {"sign": 0, "envelope_limit": 0}


def test_a3_declared_plot_and_carried_bytes_disagree_at_one_owner(tmp_path: Path) -> None:
    """Both presence directions die at binding equality, so the bundle layer rechecks nothing."""
    settings, signer, base = _dataset_success_attempt(tmp_path)
    archive = open_archive(settings)
    disagreement = r"^attempt manifest plot bindings disagree with the complete plot bytes$"

    with pytest.raises(ArchiveIntegrityError, match=disagreement):
        archive.publish_attempt(replace(base, plot=None))

    undeclared = _resign_bundle(
        base,
        signer,
        msgspec.structs.replace(
            base.manifest,
            outcome=AttemptOutcome.REJECTED,
            plot_id=None,
            plot_artifacts=(),
        ),
    )
    with pytest.raises(ArchiveIntegrityError, match=disagreement):
        archive.publish_attempt(undeclared)


@pytest.mark.parametrize("dropped", ["plot_id", "plot_artifacts"])
@pytest.mark.parametrize("verified", [True, False])
def test_a3_plot_address_and_bindings_each_refuse_alone(
    tmp_path: Path,
    dropped: str,
    *,
    verified: bool,
) -> None:
    """Dropping either view leaves the other agreeing, so each arm refuses on its own.

    Materialization derives the address and the bindings from one drafted plot, so only an
    external occurrence can split them; neither arm is redundant with the other.
    """
    settings, signer, base = _dataset_success_attempt(tmp_path)
    outcome = AttemptOutcome.VERIFIED if verified else AttemptOutcome.REJECTED
    manifest = msgspec.structs.replace(
        base.manifest,
        outcome=outcome,
        http_status=_OUTCOME_STATUS[outcome],
        plot_id=None if dropped == "plot_id" else base.manifest.plot_id,
        plot_artifacts=() if dropped == "plot_artifacts" else base.manifest.plot_artifacts,
    )
    mutant = _resign_bundle(base, signer, manifest)

    with pytest.raises(
        ArchiveIntegrityError,
        match=r"^attempt manifest plot presence disagrees with its outcome$",
    ):
        open_archive(settings).publish_attempt(mutant)


def test_a4_signed_plot_binding_order_is_pinned_per_mode() -> None:
    """The signed carrier order is stated here, so a reorder cannot ride the production tuple."""
    kind = archive_module.BlobKind
    dataset = (
        (kind.RAW_CSV, "raw_csv"),
        (kind.RAW_MANIFEST, "raw_manifest"),
        (kind.CANONICAL_SPEC, "canonical_spec"),
        (kind.PLOTTED_TABLE, "plotted_table"),
        (kind.VERDICT, "verdict"),
        (kind.VEGA_LITE, "vega_lite"),
        (kind.SVG, "svg"),
        (kind.VCERT_PAYLOAD, "vcert_payload"),
        (kind.VCERT_ENVELOPE, "vcert_envelope"),
        (kind.TOOL_VERSIONS, "tool_versions"),
        (kind.ED25519_PUBLIC_KEY, "public_key"),
    )
    formula = (
        (kind.CANONICAL_SPEC, "canonical_spec"),
        (kind.FORMULA_SOURCE, "formula_source"),
        (kind.PLOTTED_TABLE, "plotted_table"),
        (kind.VERDICT, "verdict"),
        (kind.MATPLOTLIB_SCRIPT, "matplotlib_script"),
        (kind.VCERT_PAYLOAD, "vcert_payload"),
        (kind.VCERT_ENVELOPE, "vcert_envelope"),
        (kind.TOOL_VERSIONS, "tool_versions"),
        (kind.ED25519_PUBLIC_KEY, "public_key"),
    )

    assert dataset == archive_module._DATASET_PLOT_BINDING_FIELDS
    assert formula == archive_module._FORMULA_PLOT_BINDING_FIELDS
    expected = {PlotSourceKind.DATASET: dataset, PlotSourceKind.FORMULA: formula}
    assert expected == archive_module._PLOT_BINDING_FIELDS_BY_SOURCE


def test_a4_attempt_plot_shared_fields_are_pinned_per_mode() -> None:
    """Each mode's attempt/plot byte equalities are stated here, so no deletion rides the map."""
    expected = {
        PlotSourceKind.DATASET: ("raw_csv", "raw_manifest", "verdict"),
        PlotSourceKind.FORMULA: ("verdict",),
    }
    assert expected == archive_module._ATTEMPT_PLOT_SHARED_FIELDS


def test_a4_plot_source_topology_map_is_exact_and_derived() -> None:
    expected = {
        tuple(role for role, _name in archive_module._DATASET_PLOT_BINDING_FIELDS): (
            PlotSourceKind.DATASET
        ),
        tuple(role for role, _name in archive_module._FORMULA_PLOT_BINDING_FIELDS): (
            PlotSourceKind.FORMULA
        ),
    }
    assert expected == archive_module._PLOT_SOURCE_KIND_BY_BINDING_ROLES


def test_a4_unmatched_plot_binding_topology_refuses_at_source_inference(tmp_path: Path) -> None:
    """A near-miss carrier sequence names no mode, so no default arm can admit it."""
    settings, raw_plot = dataset_bundle(tmp_path / "near-miss")
    plot = cast("DatasetPlotBundle", raw_plot)
    signer = load_identity(settings).signer
    manifest = AttemptManifest(
        version="attempt-0.1",
        nonce="0" * 32,
        occurred_at="2026-01-01T00:00:00.000000Z",
        route=AttemptRoute.VERIFY_AND_RENDER,
        http_status=200,
        outcome=AttemptOutcome.VERIFIED,
        plot_id=plot.plot_id,
        artifacts=archive_module._artifact_bindings(
            AttemptArtifacts(
                raw_csv=plot.raw_csv,
                raw_manifest=plot.raw_manifest,
                raw_spec=_RAW_DATASET_SPEC,
                verdict=plot.verdict,
            )
        ),
        plot_artifacts=archive_module._plot_bindings(plot)[:-1],
        keyid=signer.keyid,
        verifier_version="test",
    )

    with pytest.raises(
        ArchiveIntegrityError,
        match=r"^attempt manifest plot bindings match no closed plot source mode$",
    ):
        archive_module._validate_attempt_manifest_shape(manifest)


def test_a3_external_formula_route_dataset_plot_refuses_at_manifest_shape(
    tmp_path: Path,
) -> None:
    settings, signer, base = _dataset_success_attempt(tmp_path)
    manifest = msgspec.structs.replace(base.manifest, route=_formula_route())
    mutant = _resign_bundle(base, signer, manifest)

    with pytest.raises(
        ArchiveIntegrityError,
        match=r"^attempt manifest route /verify-formula cannot attach a dataset plot$",
    ):
        open_archive(settings).publish_attempt(mutant)


def test_a3_external_formula_route_plot_binding_bypass_refuses(tmp_path: Path) -> None:
    settings, signer, base = _dataset_success_attempt(tmp_path)
    artifacts = AttemptArtifacts(
        raw_spec=cast("bytes", base.artifacts.raw_spec),
        verdict=cast("bytes", base.artifacts.verdict),
    )
    manifest = msgspec.structs.replace(
        base.manifest,
        route=_formula_route(),
        outcome=AttemptOutcome.REJECTED,
        http_status=200,
        plot_id=None,
        artifacts=archive_module._artifact_bindings(artifacts),
        plot_artifacts=(),
    )
    mutant = _resign_bundle(base, signer, manifest, artifacts=artifacts)

    with pytest.raises(
        ArchiveIntegrityError,
        match=r"^attempt manifest plot bindings disagree with the complete plot bytes$",
    ):
        open_archive(settings).publish_attempt(mutant)


def test_a3_formula_route_rejected_outcome_materializes(tmp_path: Path) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "rejected")
    signer = load_identity(settings).signer
    bundle = materialize_attempt_bundle(
        _formula_draft(settings),
        signer,
        nonce="3" * 32,
    )

    assert bundle.manifest.outcome is AttemptOutcome.REJECTED
    assert bundle.plot is None


def test_a3_verified_outcome_without_a_plot_refuses_before_signing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "verified")
    signer = load_identity(settings).signer
    calls = _arm_signing_bombs(monkeypatch)

    with pytest.raises(
        ArchiveIntegrityError,
        match=r"^attempt manifest plot presence disagrees with its outcome$",
    ):
        materialize_attempt_bundle(
            _formula_draft(settings, outcome=AttemptOutcome.VERIFIED),
            signer,
            nonce="4" * 32,
        )
    assert calls == {"sign": 0, "envelope_limit": 0}


def test_a3_formula_route_nonjudgement_outcomes_refuse_before_signing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert set(_NONJUDGEMENT_OUTCOMES) == set(AttemptOutcome) - {
        AttemptOutcome.VERIFIED,
        AttemptOutcome.REJECTED,
    }
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "nonjudgement")
    signer = load_identity(settings).signer
    calls = _arm_signing_bombs(monkeypatch)

    for index, outcome in enumerate(_NONJUDGEMENT_OUTCOMES, start=5):
        with pytest.raises(
            ArchiveIntegrityError,
            match=(
                r"^direct formula verify attempts may only carry verified or rejected outcomes$"
            ),
        ):
            materialize_attempt_bundle(
                _formula_draft(settings, outcome=outcome),
                signer,
                nonce=f"{index:032x}",
            )
    assert calls == {"sign": 0, "envelope_limit": 0}


def test_a3_formula_route_requires_raw_spec_before_signing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "raw-spec")
    signer = load_identity(settings).signer
    artifacts = replace(_formula_rejected_artifacts(settings), raw_spec=None)
    calls = _arm_signing_bombs(monkeypatch)

    with pytest.raises(
        ArchiveIntegrityError,
        match=r"^attempt raw-spec presence disagrees with its outcome$",
    ):
        materialize_attempt_bundle(
            _formula_draft(settings, artifacts=artifacts),
            signer,
            nonce="6" * 32,
        )
    assert calls == {"sign": 0, "envelope_limit": 0}


def test_a3_formula_route_requires_verdict_before_signing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "verdict")
    signer = load_identity(settings).signer
    artifacts = replace(_formula_rejected_artifacts(settings), verdict=None)
    calls = _arm_signing_bombs(monkeypatch)

    with pytest.raises(
        ArchiveIntegrityError,
        match=r"^attempt verdict presence disagrees with its outcome$",
    ):
        materialize_attempt_bundle(
            _formula_draft(settings, artifacts=artifacts),
            signer,
            nonce="7" * 32,
        )
    assert calls == {"sign": 0, "envelope_limit": 0}


def test_a3_formula_route_refuses_dataset_traces_before_signing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "dataset-trace")
    signer = load_identity(settings).signer
    base = _formula_rejected_artifacts(settings)
    calls = _arm_signing_bombs(monkeypatch)

    for artifacts in (
        replace(base, raw_csv=b"forbidden"),
        replace(base, raw_manifest=b"forbidden"),
    ):
        with pytest.raises(
            ArchiveIntegrityError,
            match=r"^attempt manifest route /verify-formula observes no dataset input bytes$",
        ):
            materialize_attempt_bundle(
                _formula_draft(settings, artifacts=artifacts),
                signer,
                nonce="8" * 32,
            )
    assert calls == {"sign": 0, "envelope_limit": 0}


def test_a3_formula_route_refuses_model_traces_before_signing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "model-trace")
    signer = load_identity(settings).signer
    base = _formula_rejected_artifacts(settings)
    calls = _arm_signing_bombs(monkeypatch)

    for artifacts in (
        replace(base, model_request=b"forbidden"),
        replace(base, model_response=b"forbidden"),
        replace(base, model_reply=b"forbidden"),
    ):
        with pytest.raises(
            ArchiveIntegrityError,
            match=r"^attempt model trace presence disagrees with its route/outcome$",
        ):
            materialize_attempt_bundle(
                _formula_draft(settings, artifacts=artifacts),
                signer,
                nonce="9" * 32,
            )
    assert calls == {"sign": 0, "envelope_limit": 0}


def test_a4_outcome_policy_surfaces_are_unchanged() -> None:
    assert archive_module._ATTEMPT_STATUS == _OUTCOME_STATUS
    assert archive_module._MODEL_REQUEST_ONLY == _MODEL_REQUEST_ONLY
    assert archive_module._MODEL_REQUEST_RESPONSE == _MODEL_REQUEST_RESPONSE


def test_a4_route_model_roles_map_is_total_and_exact() -> None:
    assert _route_model_roles() == {
        AttemptRoute.VERIFY_AND_RENDER: _model_role_selector("_render_route_model_roles"),
        AttemptRoute.PROPOSE_SPEC: _model_role_selector("_proposer_route_model_roles"),
        _formula_route(): _model_role_selector("_formula_route_model_roles"),
    }


def test_a4_route_model_roles_dispatch_uses_map_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "model-role-map")
    signer = formula_bundle_parts().signer
    manifest = _manifest_from_draft(_formula_draft(settings), signer)
    calls: list[AttemptManifest] = []
    sentinel = {AttemptRole.MODEL_REQUEST}

    def spy(value: AttemptManifest) -> set[AttemptRole]:
        calls.append(value)
        return sentinel

    monkeypatch.setitem(_route_model_roles(), _formula_route(), spy)
    assert archive_module._expected_model_roles(manifest) is sentinel
    assert calls == [manifest]


def test_a4_route_plot_sources_map_is_total_and_exact() -> None:
    assert _route_plot_sources() == {
        AttemptRoute.VERIFY_AND_RENDER: frozenset({PlotSourceKind.DATASET}),
        AttemptRoute.PROPOSE_SPEC: frozenset({PlotSourceKind.DATASET}),
        _formula_route(): frozenset({PlotSourceKind.FORMULA}),
    }


def test_a4_route_plot_sources_dispatch_uses_map_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings, _signer, base = _dataset_success_attempt(tmp_path)
    route = _formula_route()
    manifest = msgspec.structs.replace(base.manifest, route=route)
    monkeypatch.setitem(
        _route_plot_sources(),
        route,
        frozenset({PlotSourceKind.DATASET}),
    )
    monkeypatch.setitem(_route_reads_dataset_inputs(), route, _READS_DATASET_INPUTS)

    archive_module._validate_attempt_manifest_shape(manifest)


def test_a4_route_reads_dataset_inputs_map_is_total_and_exact() -> None:
    assert _route_reads_dataset_inputs() == {
        AttemptRoute.VERIFY_AND_RENDER: True,
        AttemptRoute.PROPOSE_SPEC: True,
        _formula_route(): False,
    }


def test_a4_route_reads_dataset_inputs_dispatch_uses_map_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "reads-map")
    signer = load_identity(settings).signer
    artifacts = replace(_formula_rejected_artifacts(settings), raw_csv=b"admitted-by-spy")
    manifest = _manifest_from_draft(
        _formula_draft(settings, artifacts=artifacts),
        signer,
    )
    monkeypatch.setitem(
        _route_reads_dataset_inputs(),
        _formula_route(),
        _READS_DATASET_INPUTS,
    )

    archive_module._validate_attempt_manifest_shape(manifest)


def test_a5_formula_plot_materializer_public_contract() -> None:
    producer = _formula_materializer()
    assert "materialize_formula_plot_bundle" in archive_module.__all__
    signature = inspect.signature(producer)
    assert tuple(signature.parameters) == (
        "artifact",
        "certificate",
        "envelope",
        "signer",
        "limits",
    )
    assert tuple(parameter.kind for parameter in signature.parameters.values()) == (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    )
    assert tuple(parameter.default for parameter in signature.parameters.values()) == (
        inspect.Parameter.empty,
        inspect.Parameter.empty,
        inspect.Parameter.empty,
        inspect.Parameter.empty,
        DEFAULT_LIMITS,
    )
    assert get_type_hints(producer) == {
        "artifact": matplotlib_script.MatplotlibScriptArtifact,
        "certificate": vcert.VCertV03,
        "envelope": bytes,
        "signer": Signer,
        "limits": VerificationLimits,
        "return": FormulaPlotBundle,
    }


def test_a5_formula_plot_materializer_rebinds_carriers() -> None:
    parts = formula_bundle_parts()
    produced = _formula_materializer()(
        parts.artifact,
        parts.certificate,
        parts.bundle.vcert_envelope,
        parts.signer,
    )

    assert type(produced) is FormulaPlotBundle
    assert produced == parts.bundle
    assert produced.plot_id == hashlib.sha256(parts.bundle.vcert_envelope).hexdigest()
    assert produced.keyid == parts.signer.keyid
    assert tuple(field.name for field in fields(produced)) == (
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


def test_a5_formula_plot_materializer_refuses_unpaired_certificate_before_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parts = formula_bundle_parts()
    script = parts.artifact.matplotlib_script + b"\n"
    artifact = replace(
        parts.artifact,
        matplotlib_script=script,
        matplotlib_script_hash=canon.hash_matplotlib_script(script),
    )
    calls = {"construct": 0, "validate": 0}

    def construct_bomb(**_kwargs: object) -> FormulaPlotBundle:
        calls["construct"] += 1
        pytest.fail("formula bundle constructed after a pairing refusal")

    def validate_bomb(*_args: object, **_kwargs: object) -> None:
        calls["validate"] += 1
        pytest.fail("formula graph validation ran after a pairing refusal")

    monkeypatch.setattr(archive_module, "FormulaPlotBundle", construct_bomb)
    monkeypatch.setattr(archive_module, "_validate_plot_bundle", validate_bomb)
    with pytest.raises(
        ValueError,
        match=r"^certified script digest differs from the emitted matplotlib script$",
    ):
        _formula_materializer()(
            artifact,
            parts.certificate,
            parts.bundle.vcert_envelope,
            parts.signer,
        )
    assert calls == {"construct": 0, "validate": 0}


def test_a5_formula_plot_materializer_refuses_a_dataset_bound_certificate() -> None:
    parts = formula_bundle_parts()

    with pytest.raises(
        ValueError,
        match=r"^certificate must bind a matplotlib script, got VegaArtifactCert$",
    ):
        _formula_materializer()(
            parts.artifact,
            dataset_v03_certificate(),
            parts.bundle.vcert_envelope,
            parts.signer,
        )


@pytest.mark.parametrize("field", ("artifact", "certificate", "envelope", "signer"))
def test_a5_formula_plot_materializer_type_guards(field: str) -> None:
    parts = formula_bundle_parts()
    values: list[object] = [
        parts.artifact,
        parts.certificate,
        parts.bundle.vcert_envelope,
        parts.signer,
    ]
    values[("artifact", "certificate", "envelope", "signer").index(field)] = object()

    with pytest.raises(TypeError):
        _formula_materializer()(*values)  # type: ignore[arg-type]


def test_a5_formula_plot_materializer_refuses_invalid_limits() -> None:
    parts = formula_bundle_parts()

    with pytest.raises(TypeError):
        _formula_materializer()(
            parts.artifact,
            parts.certificate,
            parts.bundle.vcert_envelope,
            parts.signer,
            limits=cast("VerificationLimits", object()),
        )


def test_a5_formula_plot_materializer_threads_strict_limits() -> None:
    parts = formula_bundle_parts()
    tight = struct_replace(
        DEFAULT_LIMITS,
        max_attestation_bytes=len(parts.bundle.vcert_payload) - 1,
    )

    with pytest.raises(ArchiveReadLimitError):
        _formula_materializer()(
            parts.artifact,
            parts.certificate,
            parts.bundle.vcert_envelope,
            parts.signer,
            limits=tight,
        )


def test_a5_formula_plot_materializer_threads_limits_by_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parts = formula_bundle_parts()
    caller_limits = struct_replace(
        DEFAULT_LIMITS,
        max_attestation_bytes=DEFAULT_LIMITS.max_attestation_bytes + 1,
    )
    calls: list[tuple[PlotBundle, VerificationLimits]] = []

    def validate_spy(bundle: PlotBundle, limits: VerificationLimits) -> None:
        calls.append((bundle, limits))

    monkeypatch.setattr(archive_module, "_validate_plot_bundle", validate_spy)
    produced = _formula_materializer()(
        parts.artifact,
        parts.certificate,
        parts.bundle.vcert_envelope,
        parts.signer,
        limits=caller_limits,
    )

    assert len(calls) == 1
    assert calls[0][0] is produced
    assert calls[0][1] is caller_limits


def test_a5_formula_plot_materializer_never_recomputes_certificate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parts = formula_bundle_parts()

    def recompute_bomb(*_args: object, **_kwargs: object) -> vcert.VCertV03:
        pytest.fail("formula certificate recomputed instead of rebound")

    monkeypatch.setattr(vcert, "build_formula_certificate", recompute_bomb)
    monkeypatch.setattr(
        archive_module,
        "build_formula_certificate",
        recompute_bomb,
        raising=False,
    )
    assert (
        _formula_materializer()(
            parts.artifact,
            parts.certificate,
            parts.bundle.vcert_envelope,
            parts.signer,
        )
        == parts.bundle
    )


def test_a7_plotless_formula_attempt_round_trips(tmp_path: Path) -> None:
    settings = Settings(data_dir=_DATA, state_dir=tmp_path / "formula-attempt-state")
    signer = load_identity(settings).signer
    draft = _formula_draft(settings)
    bundle = materialize_attempt_bundle(
        draft,
        signer,
        nonce="a" * 32,
        limits=settings.limits,
    )
    archive = open_archive(settings)
    archive.publish_attempt(bundle, limits=settings.limits)
    reopened = open_archive(settings)
    restored = reopened.read_attempt(
        bundle.attempt_id,
        max_bytes=settings.max_archive_bytes,
        limits=settings.limits,
    )

    assert restored == bundle
    assert restored.manifest.route is _formula_route()
    assert restored.manifest.outcome is AttemptOutcome.REJECTED
    assert restored.plot is None
    assert restored.manifest.plot_id is None
    assert restored.manifest.plot_artifacts == ()
    assert restored.artifacts.raw_spec is not None
    assert restored.artifacts.verdict is not None
    assert restored.artifacts.raw_csv is None
    assert restored.artifacts.raw_manifest is None
    assert restored.artifacts.model_request is None
    assert restored.artifacts.model_response is None
    assert restored.artifacts.model_reply is None
    assert reopened.stats().plots == 0
    document = _decoded_audit(audit.audit_attempt(settings, bundle.attempt_id))
    assert document["attempt"]["route"] == _FORMULA_ROUTE
    assert document["attempt"]["outcome"] == AttemptOutcome.REJECTED.value
    assert document["attempt"]["plot_id"] is None
    assert document["plot"] is None

    with sqlite3.connect(settings.state_dir / "archive.sqlite3") as connection:
        assert connection.execute(
            "SELECT plot_id FROM attempts WHERE attempt_id = ?",
            (bundle.attempt_id,),
        ).fetchone() == (None,)
        assert connection.execute("SELECT COUNT(*) FROM plot_references").fetchone() == (0,)


def test_a9_verified_formula_attempt_binds_its_nine_carriers_and_round_trips(
    tmp_path: Path,
) -> None:
    settings, _signer, parts, draft = _formula_success_draft(tmp_path)
    bundle = materialize_attempt_bundle(draft, _signer, nonce="a" * 32, limits=settings.limits)

    assert bundle.manifest.plot_id == parts.bundle.plot_id
    assert [binding.role for binding in bundle.manifest.plot_artifacts] == [
        role for role, _name in archive_module._FORMULA_PLOT_BINDING_FIELDS
    ]
    assert len(bundle.manifest.plot_artifacts) == 9
    assert _ENCODER.encode(bundle.manifest) == bundle.attempt_payload

    archive = open_archive(settings)
    archive.publish_attempt(bundle, limits=settings.limits)
    reopened = open_archive(settings)
    restored = reopened.read_attempt(
        bundle.attempt_id,
        max_bytes=settings.max_archive_bytes,
        limits=settings.limits,
    )

    assert restored == bundle
    assert type(restored.plot) is FormulaPlotBundle
    assert restored.plot == parts.bundle
    assert reopened.read_plot(parts.bundle.plot_id, max_bytes=settings.max_archive_bytes) == (
        parts.bundle
    )
    assert reopened.lowest_verified_attempt_id(parts.bundle.plot_id) == bundle.attempt_id
    assert reopened.stats().plots == 1


def test_a9_repeat_formula_occurrence_reuses_the_stored_plot_bytes(tmp_path: Path) -> None:
    settings, signer, parts, draft = _formula_success_draft(tmp_path)
    archive = open_archive(settings)
    first = materialize_attempt_bundle(draft, signer, nonce="a" * 32, limits=settings.limits)
    archive.publish_attempt(first, limits=settings.limits)
    before = archive.stats()
    second = materialize_attempt_bundle(draft, signer, nonce="b" * 32, limits=settings.limits)
    archive.publish_attempt(second, limits=settings.limits)
    after = archive.stats()

    assert second.attempt_id != first.attempt_id
    assert second.manifest.plot_id == parts.bundle.plot_id
    assert after.attempts == before.attempts + 1
    assert after.plots == before.plots
    assert after.blobs == before.blobs + 2
    assert after.logical_blob_bytes - before.logical_blob_bytes == (
        len(second.attempt_payload) + len(second.attempt_envelope)
    )


def test_a9_formula_attempt_and_plot_roll_back_together_on_commit_fault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, signer, _parts, draft = _formula_success_draft(tmp_path)
    bundle = materialize_attempt_bundle(draft, signer, nonce="c" * 32, limits=settings.limits)
    archive = open_archive(settings)

    class InjectedError(Exception):
        pass

    def fail() -> None:
        raise InjectedError

    monkeypatch.setattr(archive_module, "_before_archive_commit", fail)
    with pytest.raises(InjectedError):
        archive.publish_attempt(bundle, limits=settings.limits)
    assert archive.stats() == archive_module.ArchiveStats(0, 0, 0, 0, 0)


def test_a9_formula_attempt_audit_selects_the_formula_certificate_and_carriers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The audit's per-mode maps decide: the v0.3 authenticator and the nine formula carriers."""
    settings, signer, parts, draft = _formula_success_draft(tmp_path)
    bundle = materialize_attempt_bundle(draft, signer, nonce="d" * 32, limits=settings.limits)
    open_archive(settings).publish_attempt(bundle, limits=settings.limits)
    calls = {"formula": 0}

    def formula_spy(*args: Any, **kwargs: Any) -> object:
        calls["formula"] += 1
        return attestation.verify_vcert_v03(*args, **kwargs)

    monkeypatch.setitem(
        audit._PLOT_CERTIFICATE_VERIFIERS,
        DatasetPlotBundle,
        cast("Any", lambda *_args, **_kwargs: pytest.fail("dataset certificate verifier ran")),
    )
    monkeypatch.setitem(
        audit._PLOT_CERTIFICATE_VERIFIERS, FormulaPlotBundle, cast("Any", formula_spy)
    )
    document = _decoded_audit(audit.audit_attempt(settings, bundle.attempt_id))

    assert calls == {"formula": 1}
    assert document["authentication"]["plot_vcert_dsse"] == "valid"
    assert document["plot"]["id"] == parts.bundle.plot_id
    assert [item["role"] for item in document["plot"]["artifacts"]] == [
        role.value for role, _name in archive_module._FORMULA_PLOT_BINDING_FIELDS
    ]


def test_a8_replay_route_and_model_role_vocabulary_match_archive() -> None:
    expected_routes = {route.value for route in AttemptRoute}
    expected_model_roles = {
        "/verify-and-render": frozenset(),
        "/propose-spec": frozenset({"model_request", "model_response", "model_reply"}),
        "/verify-formula": frozenset(),
    }
    route_alias: Any = replay._AttemptRoute

    assert _alias_values(route_alias) == expected_routes
    assert expected_model_roles == replay._EXPECTED_MODEL_ROLES
    assert set(replay._EXPECTED_MODEL_ROLES) == expected_routes


def test_a8_replay_outcome_and_status_vocabulary_match_archive() -> None:
    expected_statuses = {outcome.value: status for outcome, status in _OUTCOME_STATUS.items()}
    outcome_alias: Any = replay._AttemptOutcome

    assert _alias_values(outcome_alias) == {outcome.value for outcome in AttemptOutcome}
    assert expected_statuses == replay._ATTEMPT_STATUS


def test_a8_formula_route_snapshot_decodes_then_refuses_at_attempt_outcome(
    tmp_path: Path,
) -> None:
    _settings, signer, bundle = _dataset_success_attempt(tmp_path)
    manifest = msgspec.structs.replace(bundle.manifest, route=_formula_route())
    payload = _ENCODER.encode(manifest)
    envelope = attestation.sign_dsse(
        payload,
        signer.private_key,
        keyid=signer.keyid,
        payload_type=archive_module.ATTEMPT_PAYLOAD_TYPE,
        max_payload_bytes=DEFAULT_LIMITS.max_attestation_bytes,
    )
    snapshot = replace(
        _replay_snapshot(bundle),
        attempt_id=hashlib.sha256(envelope).hexdigest(),
        attempt_payload=payload,
        attempt_envelope=envelope,
    )

    decoded = replay._ATTEMPT_DECODER.decode(payload)
    assert decoded.route == _FORMULA_ROUTE
    verdict = replay.replay_snapshot(snapshot, {signer.keyid: signer.public_key})
    assert verdict.status == "integrity_failed"
    assert verdict.failure_stage == "attempt_outcome"


def test_a10_formula_materialization_docstrings_are_truthful() -> None:
    module_doc = archive_module.__doc__ or ""

    assert "each mode has its own materializer" in module_doc
    assert "no pipeline here emits formula rows yet" not in module_doc
    # The dataset-only reader policy is gone: both modes reconstruct through the source maps.
    assert not hasattr(archive_module, "_require_dataset_plot")
