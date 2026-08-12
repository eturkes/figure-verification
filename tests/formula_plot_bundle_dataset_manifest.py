# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""T42: isolated finite dataset-preservation manifest against baseline e432bd9."""

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
from pathlib import Path
from verifier import attestation, render
from verifier.service import archive as a, pipeline
from verifier.service.identity import load_identity
from verifier.service.settings import Settings

root = Path.cwd()
with tempfile.TemporaryDirectory() as td:
    settings = Settings(data_dir=root / "data", state_dir=Path(td) / "state")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from verifier.service.identity import Signer, keyid_for_public_key
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public_key = private_key.public_key()
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    signer = Signer(
        keyid=keyid_for_public_key(public_key_bytes), public_key_bytes=public_key_bytes,
        public_key=public_key, private_key=private_key
    )
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
            for role, name in a._PLOT_ROLE_FIELDS
        },
        "attempt": "covered by the existing signed-attempt suite",
        "audit": "covered by the existing audit suite",
        "replay": "covered by the existing replay suites",
        "refusals": "covered by existing named-refusal tests",
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
