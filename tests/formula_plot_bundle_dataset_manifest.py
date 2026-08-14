# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""T42: isolated finite dataset-preservation manifest against baseline e432bd9.

One program runs in both trees and its whole stdout is compared, so every emitted value is a
differential: dataset plot materialization, its archive round trip, and the signed attempt,
audit, and replay bytes layered on it. Constants would compare equal in any pair of trees, so
each surface enters as bytes derived from the run.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PROGRAM = r"""
import json
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from verifier import attestation, render
from verifier.service import archive as a, pipeline
from verifier.service.audit import audit_attempt
from verifier.service.identity import load_identity
from verifier.service.replay import replay_plot_from_settings
from verifier.service.settings import Settings

root = Path.cwd()
with tempfile.TemporaryDirectory() as td:
    settings = Settings(data_dir=root / "data", state_dir=Path(td) / "state")
    # Audit and replay authenticate against the configured identity, so this signs with that
    # identity: let it create the key file with its required mode, then seed it deterministically.
    load_identity(settings)
    Path(settings.signing_key_file).write_bytes(bytes(range(32)))
    signer = load_identity(settings).signer
    # One program runs in both trees, so it resolves the dataset role tuple under either name:
    # the baseline's single `_PLOT_ROLE_FIELDS` or the per-mode split that replaced it.
    dataset_role_fields = getattr(a, "_DATASET_PLOT_ROLE_FIELDS", None) or a._PLOT_ROLE_FIELDS
    raw = (root / "examples/good_specs/g01_total_revenue_by_month.json").read_bytes()
    outcome = pipeline.verify_only(raw, settings)
    prepared = outcome.prepared
    rendered = render.render_prepared(prepared, limits=settings.limits)
    envelope = attestation.sign_vcert(
        rendered.certificate, signer.private_key, keyid=signer.keyid, limits=settings.limits
    )
    bundle = a.materialize_plot_bundle(
        prepared, rendered, envelope, signer, limits=settings.limits
    )
    field_names = (
        "raw_csv", "raw_manifest", "canonical_spec", "plotted_table", "verdict",
        "vega_lite", "svg", "vcert_payload", "vcert_envelope", "tool_versions", "public_key",
    )
    batch = a._plot_bundle_batch(bundle)
    archive = a.open_archive(settings)
    archive.publish_plot(bundle, limits=settings.limits)
    budget = sum(len(getattr(bundle, n)) for n in field_names)
    read = archive.read_plot(bundle.plot_id, max_bytes=budget)
    cert_bytes = archive.read_certificate(
        bundle.plot_id, max_bytes=len(bundle.vcert_envelope)
    )
    spec_bytes = archive.read_spec(
        rendered.certificate.spec_hash.removeprefix("sha256:"),
        max_bytes=len(bundle.canonical_spec),
    )
    envelope_bytes = archive.read_plot_envelope(
        bundle.plot_id, max_bytes=len(bundle.vcert_envelope)
    )
    attempt = a.materialize_attempt_bundle(
        a.AttemptDraft(
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            route=a.AttemptRoute.VERIFY_AND_RENDER,
            http_status=200,
            outcome=a.AttemptOutcome.VERIFIED,
            artifacts=pipeline._attempt_artifacts(outcome, raw, bundle.verdict, None),
            plot=bundle,
        ),
        signer,
        nonce="0" * 32,
        limits=settings.limits,
    )
    archive.publish_attempt(attempt, limits=settings.limits)
    read_attempt = archive.read_attempt(
        attempt.attempt_id, max_bytes=settings.max_archive_bytes, limits=settings.limits
    )
    output = {
        "materialized": {n: getattr(bundle, n).hex() for n in field_names},
        "batch": repr(batch),
        "read": {n: getattr(read, n).hex() for n in field_names},
        "ids": [read.plot_id, read.keyid],
        "certificate": cert_bytes.hex(),
        "spec": spec_bytes.hex(),
        "envelope": envelope_bytes.hex(),
        "roles": {
            role.value: archive.read_plot_blob(
                bundle.plot_id, role, max_bytes=len(getattr(bundle, name))
            ).hex()
            for role, name in dataset_role_fields
        },
        "attempt": {
            "id": attempt.attempt_id,
            "manifest": repr(attempt.manifest),
            "payload": attempt.attempt_payload.hex(),
            "envelope": attempt.attempt_envelope.hex(),
            "batch": repr(a._attempt_bundle_batch(attempt)),
            "read": repr(read_attempt.manifest),
            "read_envelope": archive.read_attempt_envelope(
                attempt.attempt_id, max_bytes=len(attempt.attempt_envelope)
            ).hex(),
            "roles": {
                role.value: archive.read_attempt_blob(
                    attempt.attempt_id, role, max_bytes=len(observed)
                ).hex()
                for role, name in a._ATTEMPT_ARTIFACT_FIELDS
                if (observed := getattr(attempt.artifacts, name)) is not None
            },
        },
        "audit": audit_attempt(settings, attempt.attempt_id).hex(),
        "replay": repr(replay_plot_from_settings(settings, bundle.plot_id)),
    }
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
"""


def _run(source_root: Path) -> bytes:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_root / "src")
    return subprocess.run(  # noqa: S603 — fixed interpreter and literal child program
        [sys.executable, "-c", _PROGRAM],
        cwd=_ROOT,
        env=env,
        check=True,
        capture_output=True,
    ).stdout


def main() -> None:
    candidate = _run(_ROOT)
    with tempfile.TemporaryDirectory() as td:
        baseline = Path(td) / "baseline"
        subprocess.run(  # noqa: S603 — fixed literal argv
            ["git", "worktree", "add", "--detach", str(baseline), "e432bd9"],  # noqa: S607
            cwd=_ROOT,
            check=True,
            capture_output=True,
        )
        try:
            expected = _run(baseline)
        finally:
            subprocess.run(  # noqa: S603 — fixed literal argv
                ["git", "worktree", "remove", "--force", str(baseline)],  # noqa: S607
                cwd=_ROOT,
                check=True,
                capture_output=True,
            )
    if candidate != expected:
        msg = "T42 dataset-preservation manifest differs from e432bd9"
        raise SystemExit(msg)


if __name__ == "__main__":
    main()
