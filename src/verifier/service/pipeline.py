# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Verify-only pipeline: raw spec bytes -> internal Outcome (M2.2).

The transport hands raw request bytes straight here (never a framework-parsed object), so
schema.decode_spec's strict, fail-closed decode — its duplicate-key rescan included —
stays authoritative. verify_only strings the trusted M1 stages the core otherwise offers
no single orchestrator for: decode_spec -> resolve the trusted manifest -> load_manifest
-> checks.verify, mapping each result onto a Verdict.

Error split (POC_SCOPE service boundary): every verification outcome is a 200 Verdict —
including a spec that fails to decode (an expected model failure mode) or names a dataset
with no manifest (dataset.manifest_available) — a genuine absence the read reports as
FileNotFoundError. A trusted manifest that is PRESENT but unloadable (malformed JSON; a
non-file path raising a directory/permission/symlink-loop error at the read; or one whose
declared dataset mispairs with the spec) is operator misconfiguration: the read,
load_manifest, or checks.verify raises, escaping to the app's 500 handler. The untrusted
model controls only the dataset name, not what the trusted data_dir holds at that path, so
it cannot provoke that 500 — a name with no manifest fails closed as a 200 Verdict.

Outcome is internal, never serialized: on a passed stage it carries the decoded spec and
the manifest bytes forward so M2.3's render path reuses them without re-deriving.
"""

from pathlib import Path
from typing import Literal

import msgspec

from verifier import checks, ingest
from verifier.schema import VPlotSpec, decode_spec
from verifier.service.models import Verdict
from verifier.service.settings import Settings


class Outcome(msgspec.Struct, frozen=True, kw_only=True):
    """Internal verify-only result (never serialized). spec and manifest_bytes populate
    once their stage passes, so a subsequent render reuses them without re-deriving."""

    verdict: Verdict
    spec: VPlotSpec | None = None
    manifest_bytes: bytes | None = None


def _single(check: str, message: str, *, layer: Literal["decode", "verify"]) -> Verdict:
    """A blocking Verdict carrying one synthetic fail result at `layer`."""
    result = checks.CheckResult(check=check, status="fail", severity="blocking", message=message)
    return Verdict(verified=False, layer=layer, results=(result,))


def verify_only(raw: bytes, settings: Settings) -> Outcome:
    """Run the trusted verify-only pipeline over raw spec bytes (see the module docstring)."""
    try:
        spec = decode_spec(raw)
    except (msgspec.ValidationError, msgspec.DecodeError) as exc:
        return Outcome(verdict=_single("spec.decode", str(exc), layer="decode"))

    # The manifest's filename is Path(name).stem + ".json"; .stem collapses any directory
    # or traversal in the decode-validated, .csv-suffixed name to a flat component, so the
    # path stays under data_dir/schemas by construction (no runtime confinement branch is
    # reachable here, unlike checks.py's whole-name CSV resolution).
    manifest_path = settings.data_dir / "schemas" / f"{Path(spec.dataset.name).stem}.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
    except FileNotFoundError:
        # ENOENT = genuine absence (this dataset is simply not provisioned; a dangling
        # symlink resolves here too) -> the 200 verdict the model expects. Any OTHER
        # filesystem fault (a directory or regular-file collision, a permission or
        # symlink-loop error) is broken operator config like a malformed manifest, so it
        # propagates uncaught -> the app's generic 500.
        message = f"no trusted manifest for dataset {spec.dataset.name!r}"
        verdict = _single("dataset.manifest_available", message, layer="verify")
        return Outcome(verdict=verdict, spec=spec)

    manifest = ingest.load_manifest(manifest_bytes)  # broken manifest -> raise -> 500
    report = checks.verify(spec, manifest, data_dir=settings.data_dir)  # mispair -> raise -> 500
    verdict = Verdict(verified=report.passed, layer="verify", results=report.results)
    return Outcome(verdict=verdict, spec=spec, manifest_bytes=manifest_bytes)
