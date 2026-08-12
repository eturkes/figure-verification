# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Tests-only real-chain FormulaPlotBundle construction + signed mutation helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

import msgspec
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from verifier import attestation, canon, checks, formula_prepare, matplotlib_script, render, vcert
from verifier.schema import FormulaPlotSpec, VPlotSpec, decode_formula_spec, decode_spec
from verifier.service import archive as archive_module
from verifier.service import pipeline
from verifier.service.identity import Signer, keyid_for_public_key, load_identity
from verifier.service.models import Verdict
from verifier.service.settings import Settings

_ROOT = Path(__file__).resolve().parent.parent
_FORMULA_SPEC = _ROOT / "examples/formula_good_specs/f02_linear.json"
_DATASET_SPEC = _ROOT / "examples/good_specs/g01_total_revenue_by_month.json"
_ENCODER = msgspec.json.Encoder(order="deterministic")


@dataclass(frozen=True, slots=True)
class FormulaBundleParts:
    signer: Signer
    spec: FormulaPlotSpec
    artifact: matplotlib_script.MatplotlibScriptArtifact
    certificate: vcert.VCertV03
    bundle: Any


def signer() -> Signer:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return Signer(
        keyid=keyid_for_public_key(public_key_bytes),
        public_key_bytes=public_key_bytes,
        public_key=public_key,
        private_key=private_key,
    )


def canonical_specs() -> tuple[VPlotSpec, FormulaPlotSpec]:
    return decode_spec(_DATASET_SPEC.read_bytes()), decode_formula_spec(_FORMULA_SPEC.read_bytes())


def formula_bundle_parts() -> FormulaBundleParts:
    """Build one bundle through the exact certified formula chain; no src producer exists."""
    spec = decode_formula_spec(_FORMULA_SPEC.read_bytes())
    evidence = checks.verify_formula_run(spec).require_evidence()
    preparation = formula_prepare.prepare_formula(spec, evidence)
    prepared = cast("formula_prepare.PreparedFormula", preparation.prepared)
    emission = matplotlib_script.emit_matplotlib_script(prepared)
    artifact = cast("matplotlib_script.MatplotlibScriptArtifact", emission.artifact)
    certificate = vcert.build_formula_certificate(artifact)
    signing = signer()
    envelope = attestation.sign_vcert_v03(
        certificate,
        signing.private_key,
        keyid=signing.keyid,
    )
    bundle_type = archive_module.FormulaPlotBundle
    bundle = bundle_type(
        plot_id=hashlib.sha256(envelope).hexdigest(),
        keyid=signing.keyid,
        canonical_spec=canon.spec_bytes(spec),
        formula_source=evidence.formula_source_bytes,
        plotted_table=canon.serialize_table(evidence.plotted_table).encode("utf-8"),
        verdict=_ENCODER.encode(Verdict(verified=True, layer="verify", results=artifact.results)),
        matplotlib_script=artifact.matplotlib_script,
        vcert_payload=vcert.vcert_v03_bytes(certificate),
        vcert_envelope=envelope,
        tool_versions=_ENCODER.encode(certificate.tcb),
        public_key=signing.public_key_bytes,
    )
    return FormulaBundleParts(signing, spec, artifact, certificate, bundle)


def dataset_bundle(tmp_path: Path) -> tuple[Settings, Any]:
    """Build today's real dataset bundle for exact-type and field-preservation probes."""
    settings = Settings(data_dir=_ROOT / "data", state_dir=tmp_path / "dataset-state")
    signing = load_identity(settings).signer
    raw_spec = (_ROOT / "examples/good_specs/g01_total_revenue_by_month.json").read_bytes()
    outcome = pipeline.verify_only(raw_spec, settings)
    prepared = cast("render.PreparedArtifact", outcome.prepared)
    rendered = render.render_prepared(prepared, limits=settings.limits)
    envelope = attestation.sign_vcert(
        rendered.certificate,
        signing.private_key,
        keyid=signing.keyid,
        limits=settings.limits,
    )
    return settings, archive_module.materialize_plot_bundle(
        prepared, rendered, envelope, signing, limits=settings.limits
    )


def dataset_certificate() -> render.VCert:
    """Minimal canonical v0.2 certificate for cross-wrapper routing probes."""
    tcb = vcert.dataset_tcb(verifier_version="test")
    return render.VCert(
        version="vcert-0.2",
        dataset_hash="sha256:" + "1" * 64,
        spec_hash="sha256:" + "2" * 64,
        plotted_table_hash="sha256:" + "3" * 64,
        manifest_hash="sha256:" + "4" * 64,
        vega_lite_hash="sha256:" + "5" * 64,
        checks=(),
        filters=(),
        sorts=(),
        tcb=tcb,
    )


def dataset_v03_certificate() -> vcert.VCertV03:
    """Correlated dataset-family v0.3 certificate for exact-family narrowing probes."""
    current = vcert.dataset_tcb(verifier_version="test")
    source = vcert.DatasetSourceCert(
        dataset_hash="sha256:" + "1" * 64,
        manifest_hash="sha256:" + "2" * 64,
        filters=(),
        sorts=(),
    )
    tcb = vcert.DatasetTcb(
        verifier_version=current.verifier_version,
        z3_version=current.z3_version,
        canon_version=current.canon_version,
        python=current.python,
        msgspec=current.msgspec,
        unidata=current.unidata,
        vl_convert_python=current.vl_convert_python,
        vl_version=current.vl_version,
        font_family=current.font_family,
        vendored_font_sha256=current.vendored_font_sha256,
    )
    return vcert.VCertV03(
        version="vcert-0.3",
        source=source,
        spec_hash="sha256:" + "3" * 64,
        plotted_table_hash="sha256:" + "4" * 64,
        artifact=vcert.VegaArtifactCert(vega_lite_hash="sha256:" + "5" * 64),
        checks=(),
        tcb=tcb,
    )


def resign_formula_bundle(
    parts: FormulaBundleParts,
    certificate: vcert.VCertV03,
    **bundle_changes: Any,
) -> Any:
    payload = vcert.vcert_v03_bytes(certificate)
    envelope = attestation.sign_vcert_v03(
        certificate,
        parts.signer.private_key,
        keyid=parts.signer.keyid,
    )
    return replace(
        parts.bundle,
        plot_id=hashlib.sha256(envelope).hexdigest(),
        vcert_payload=payload,
        vcert_envelope=envelope,
        **bundle_changes,
    )


def different_digest(value: str) -> str:
    return value[:-1] + ("0" if value[-1] != "0" else "1")
