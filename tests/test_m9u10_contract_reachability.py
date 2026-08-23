# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Reachability pins for the three M9.10 claims that a PREP-certified contract got wrong.

Each case began as an executable counterexample: the contract asserted something unreachable or
false, and the test demonstrated it. The rulings amended the contract, so each now pins the
AMENDED claim instead. Keeping them is what stops the refuted wording from returning — a
regression would have to make the attestation ceiling reachable with zero upstream calls, shrink
the shared resource inventory again, or reorder signing behind the archive commit.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import msgspec
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from formula_plot_bundle_helpers import formula_bundle_parts
from verifier import attestation, checks, formula_prepare, vcert
from verifier.errors import VerificationError
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.matplotlib_script import MatplotlibScriptArtifact
from verifier.schema import decode_formula_spec
from verifier.service.archive import (
    ArchiveQuotaError,
    AttemptArtifacts,
    AttemptDraft,
    AttemptOutcome,
    AttemptRoute,
    open_archive,
)
from verifier.service.identity import load_identity
from verifier.service.settings import Settings


def test_s4_attestation_refusal_cannot_keep_builder_and_signer_at_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S4's attestation-ceiling family requires both named upstream calls to execute."""
    parts = formula_bundle_parts()
    calls = {"build_formula_certificate": 0, "sign_vcert_v03": 0}
    original_build: Callable[..., vcert.VCertV03] = vcert.build_formula_certificate
    original_sign: Callable[..., bytes] = attestation.sign_vcert_v03

    def observe_build(artifact: MatplotlibScriptArtifact) -> vcert.VCertV03:
        calls["build_formula_certificate"] += 1
        return original_build(artifact)

    def observe_sign(
        certificate: vcert.VCertV03,
        private_key: Ed25519PrivateKey,
        *,
        keyid: str,
        limits: VerificationLimits,
    ) -> bytes:
        calls["sign_vcert_v03"] += 1
        return original_sign(
            certificate,
            private_key,
            keyid=keyid,
            limits=limits,
        )

    monkeypatch.setattr(vcert, "build_formula_certificate", observe_build)
    monkeypatch.setattr(attestation, "sign_vcert_v03", observe_sign)
    certificate = vcert.build_formula_certificate(parts.artifact)
    payload = vcert.vcert_v03_bytes(certificate)
    limits = msgspec.structs.replace(DEFAULT_LIMITS, max_attestation_bytes=len(payload) - 1)

    with pytest.raises(VerificationError, match=r"VCert payload has .* bytes; limit is"):
        attestation.sign_vcert_v03(
            certificate,
            parts.signer.private_key,
            keyid=parts.signer.keyid,
            limits=limits,
        )

    # Only sign_vcert_v03 can emit resource.attestation_bytes, and it needs a built certificate,
    # so S4's blanket zero was unimplementable. The amended family stages the counts.
    assert calls == {"build_formula_certificate": 1, "sign_vcert_v03": 1}


def test_s4_resource_inventory_includes_reachable_shared_limits() -> None:
    """S4 omits two source-neutral resource tags the formula path can produce."""
    root = Path(__file__).resolve().parent.parent
    spec = decode_formula_spec((root / "examples/formula_good_specs/f02_linear.json").read_bytes())
    plotted_cell_run = checks.verify_formula_run(
        spec,
        limits=msgspec.structs.replace(DEFAULT_LIMITS, max_plotted_cells=1),
    )
    reached = {plotted_cell_run.report.results[-1].check}

    evidence = checks.verify_formula_run(spec).require_evidence()
    with pytest.raises(VerificationError) as raised:
        formula_prepare.prepare_formula(
            spec,
            evidence,
            limits=msgspec.structs.replace(DEFAULT_LIMITS, max_smt_terms=1),
        )
    reached.add(raised.value.check)

    # Both tags are source-neutral and reachable through the formula worker, so the amended
    # inventory carries them; S4's original three-family list did not.
    assert reached == {"resource.plotted_cells", "resource.smt_terms"}
    declared_shared = {
        "resource.render_rows",
        "resource.matplotlib_script_bytes",
        "resource.attestation_bytes",
        "resource.plotted_cells",
        "resource.smt_terms",
    }
    assert reached <= declared_shared


def test_r8_archive_quota_failure_occurs_after_formula_signing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A supported 507 path signs v0.3 before transactional quota can refuse commit."""
    root = Path(__file__).resolve().parent.parent
    settings = Settings(
        data_dir=root / "data",
        state_dir=tmp_path / "state",
        max_archive_bytes=1,
    )
    signer = load_identity(settings).signer
    calls = 0
    original_sign: Callable[..., bytes] = attestation.sign_vcert_v03

    def observe_sign(
        certificate: vcert.VCertV03,
        private_key: Ed25519PrivateKey,
        *,
        keyid: str,
        limits: VerificationLimits = DEFAULT_LIMITS,
    ) -> bytes:
        nonlocal calls
        calls += 1
        return original_sign(
            certificate,
            private_key,
            keyid=keyid,
            limits=limits,
        )

    monkeypatch.setattr(attestation, "sign_vcert_v03", observe_sign)
    parts = formula_bundle_parts(signing=signer)
    raw_spec = (root / "examples/formula_good_specs/f02_linear.json").read_bytes()
    draft = AttemptDraft(
        occurred_at=datetime.now(UTC),
        route=AttemptRoute.VERIFY_FORMULA,
        http_status=200,
        outcome=AttemptOutcome.VERIFIED,
        artifacts=AttemptArtifacts(raw_spec=raw_spec, verdict=parts.bundle.verdict),
        plot=parts.bundle,
    )
    archive = open_archive(settings)

    with pytest.raises(ArchiveQuotaError):
        archive.record_attempt(draft, signer, limits=settings.limits)
    assert archive.stats().attempts == 0

    # Signing precedes the transactional commit, so a capacity refusal lands AFTER a
    # script-binding envelope exists in memory. The ratified claim is therefore stated over
    # verdicts: this 507 answers a Problem, archives nothing, and returns no script.
    assert calls == 1
