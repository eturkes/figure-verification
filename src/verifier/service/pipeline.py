# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Service pipeline: raw spec bytes -> verdict (M2.2 verify-only) or verified render (M2.3).

The transport hands raw request bytes straight here (never a framework-parsed object), so
schema.decode_spec's strict, fail-closed decode — its duplicate-key rescan included —
stays authoritative. verify_only strings the trusted M1 stages the core otherwise offers
no single orchestrator for, as two composable halves: decode_stage (decode_spec) then
verify_decoded (resolve the trusted manifest -> load_manifest -> checks.verify), mapping
each result onto a Verdict.

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
the manifest bytes forward so render_outcome reuses them without re-deriving.

render_outcome (split from verify_and_render at M3.3b) is the render half: on a PASSING
verdict it renders the verified chart, content-addresses the artifacts (plot_id = SHA-256 of
the certificate bytes, spec_id = the certificate's spec_hash), stores them, and answers a
RenderVerdict; a failing verdict returns the plain Verdict with no chart. render() re-verifies
internally (defense in depth); since verify_only already passed the same gates, a None return
is a broken invariant, not a caller outcome, so it raises -> the app's generic 500 (the model
cannot provoke it). verify_and_render (M2.3) is the thin verify_only -> render_outcome
composition; app.py's proposer reuses these seams — decode_stage, then pin the requested
dataset name, then verify_decoded -> render_outcome — so an off-request name is refused right
after decode, before verify_decoded touches the wrong dataset's trusted files (no manifest
read, no 500, no store).
"""

import hashlib
from pathlib import Path
from typing import Literal, cast

import msgspec

from verifier import canon, checks, ingest, render
from verifier.schema import VPlotSpec, decode_spec
from verifier.service.models import RenderVerdict, Verdict
from verifier.service.settings import Settings
from verifier.service.store import ArtifactStore


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


def decode_stage(raw: bytes) -> VPlotSpec | Verdict:
    """Strictly decode raw spec bytes: the decoded VPlotSpec, or a 200 layer="decode" Verdict on
    a decode failure (an expected model failure mode). The first pipeline stage, split out so
    app.py's proposer pins the requested dataset name on the decoded spec BEFORE any trusted
    dataset I/O — an off-request name is refused without touching the wrong dataset's files."""
    try:
        return decode_spec(raw)
    except (msgspec.ValidationError, msgspec.DecodeError) as exc:
        return _single("spec.decode", str(exc), layer="decode")


def verify_decoded(spec: VPlotSpec, settings: Settings) -> Outcome:
    """Verify an already-decoded spec: resolve + load the trusted manifest, run checks, map the
    report onto an Outcome. A dataset with no manifest fails closed as a 200 Verdict; a PRESENT
    but unloadable manifest (or a checks mispair) raises -> the app's 500 (see the module
    docstring). Split from verify_only (M3.3b) so the proposer pins the name between decode_stage
    and this stage, keeping an off-request name off this dataset I/O entirely."""
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


def verify_only(raw: bytes, settings: Settings) -> Outcome:
    """Run the trusted verify-only pipeline over raw spec bytes: decode_stage -> verify_decoded
    (see the module docstring). A decode failure is a 200 decode Verdict; otherwise the decoded
    spec is verified against its trusted manifest."""
    decoded = decode_stage(raw)
    if isinstance(decoded, Verdict):
        return Outcome(verdict=decoded)
    return verify_decoded(decoded, settings)


def render_outcome(
    outcome: Outcome, settings: Settings, store: ArtifactStore, *, include_html: bool
) -> Verdict | RenderVerdict:
    """Render the verified chart for a passing Outcome, store the artifacts content-addressed, and
    answer a RenderVerdict. A failing verdict answers the plain Verdict — never a chart on an
    unverified outcome. CPU-bound + synchronous (the handler offloads it via sync_to_thread); see
    the module docstring for the render-None invariant. Split from verify_and_render (M3.3b) so
    app.py's proposer can pin the requested dataset name between verify_only and this render.

    The offline HTML page is built + stored on EVERY verified render (render(include_html=True)
    unconditionally, then store.put_chart under plot_id), so both entry routes — verify-and-render
    and the proposer — populate the chart store through this one seam; GET /chart/{plot_id} then
    serves that page until chart-LRU eviction (a verified chart can 404 while its certificate
    still lives — see store.py's mixed-state note). include_html now governs ONLY the JSON-body
    html copy (the large inline view the caller opts into); the stored page is not gated by it."""
    if not outcome.verdict.verified:
        return outcome.verdict
    # verified => the verify stage ran and passed, so spec and manifest_bytes are populated
    # (cast, not assert: an assert's never-taken branch fails the 100% gate — the M1.5a lesson).
    spec = cast("VPlotSpec", outcome.spec)
    manifest_bytes = cast("bytes", outcome.manifest_bytes)
    result = render.render(spec, manifest_bytes, data_dir=settings.data_dir, include_html=True)
    if result is None:
        msg = "render returned None for a verified spec"
        raise RuntimeError(msg)  # broken invariant -> app 500 (the model cannot reach here)
    # include_html=True => the offline page is always built; cast, not assert (the M1.5a lesson).
    chart_html = cast("str", result.html)
    cert = result.certificate
    cert_bytes = render.vcert_bytes(cert)
    plot_id = hashlib.sha256(cert_bytes).hexdigest()
    spec_id = cert.spec_hash.removeprefix("sha256:")
    store.put(
        plot_id=plot_id, cert_bytes=cert_bytes, spec_id=spec_id, spec_bytes=canon.spec_bytes(spec)
    )
    store.put_chart(plot_id, chart_html.encode("utf-8"))
    return RenderVerdict(
        verified=True,
        layer=outcome.verdict.layer,
        results=outcome.verdict.results,
        plot_id=plot_id,
        spec_id=spec_id,
        dataset_hash=cert.dataset_hash,
        spec_hash=cert.spec_hash,
        plotted_table_hash=cert.plotted_table_hash,
        manifest_hash=cert.manifest_hash,
        svg=result.svg,
        html=chart_html if include_html else None,
    )


def verify_and_render(
    raw: bytes, settings: Settings, store: ArtifactStore, *, include_html: bool
) -> Verdict | RenderVerdict:
    """Verify raw spec bytes, then render + store on a passing verdict (verify_only ->
    render_outcome). A failing verdict answers the plain Verdict — never a chart. CPU-bound +
    synchronous (the handler offloads it via sync_to_thread)."""
    return render_outcome(verify_only(raw, settings), settings, store, include_html=include_html)
