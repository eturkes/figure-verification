# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Service pipeline: raw spec bytes -> internal evidence -> verdict or verified render.

The transport hands raw request bytes straight here (never a framework-parsed object), so
schema.decode_spec's strict, fail-closed decode — its duplicate-key rescan included —
stays authoritative. verify_only strings the trusted M1 stages the core otherwise offers
no single orchestrator for, as two composable halves: decode_stage (decode_spec) then
verify_decoded (bounded manifest read -> checks.verify_run), mapping the public report onto
a Verdict while retaining the incremental trace and optional check-passed evidence internally.

Error split (POC_SCOPE service boundary): every verification outcome is a 200 Verdict —
including a spec that fails to decode (an expected model failure mode) or names a dataset
with no manifest (dataset.manifest_available) — a genuine absence the read reports as
FileNotFoundError. A trusted manifest that is PRESENT but unloadable (malformed JSON; a
non-file path raising a directory/permission/symlink-loop error at the read; or one whose
declared dataset mispairs with the spec) is operator misconfiguration: it escapes to the
app's 500 handler. Resource-policy breaches instead remain ordinary failed 200 Verdicts.
The untrusted model controls only the dataset name, not what the trusted data_dir holds at
that path, so a name with no manifest fails closed as a 200 Verdict.

Outcome is an internal dataclass, never serialized: it carries only inputs admitted so far,
plus RecomputedEvidence only after every core check passes. Sensitive bytes stay out of its
repr and every route returns only Outcome.verdict or a separately built RenderVerdict.

render_outcome (split from verify_and_render at M3.3b) is the render half: on a PASSING
verdict it renders the verified chart, content-addresses the artifacts (plot_id = SHA-256 of
the certificate bytes, spec_id = the certificate's spec_hash), stores them, and answers a
RenderVerdict; a failing verdict returns the plain Verdict with no chart. A passing outcome
is prepared and rendered directly from its immutable evidence, so no trusted file is read or
verification/build repeated after capture. A render resource refusal appends its tagged failure
and returns a plain Verdict before storage; invariant/native faults still escape to 500.
verify_and_render is the thin verify_only -> render_outcome composition; app.py's proposer
reuses these seams — decode_stage, dataset pin, verify_decoded, render_outcome — so an
off-request name is refused before the wrong dataset's trusted I/O.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

import msgspec

from verifier import canon, checks, render
from verifier.errors import VerificationError
from verifier.limits import read_bounded
from verifier.schema import VPlotSpec, decode_spec
from verifier.service.models import RenderVerdict, Verdict
from verifier.service.settings import Settings
from verifier.service.store import ArtifactStore

_EMPTY_TRACE = checks.VerificationTrace(manifest_bytes=None, source_bytes=None)


@dataclass(frozen=True, slots=True)
class Outcome:
    """Internal verification state; sensitive trace/evidence never serialize or enter repr."""

    verdict: Verdict
    spec: VPlotSpec | None = field(default=None, repr=False)
    trace: checks.VerificationTrace = field(default=_EMPTY_TRACE, repr=False)
    evidence: checks.RecomputedEvidence | None = field(default=None, repr=False)


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
        manifest_bytes = read_bounded(manifest_path, settings.limits.max_manifest_bytes)
    except VerificationError as exc:
        verdict = _single(exc.check, str(exc), layer="verify")
        return Outcome(verdict=verdict, spec=spec)
    except FileNotFoundError:
        # ENOENT = genuine absence (this dataset is simply not provisioned; a dangling
        # symlink resolves here too) -> the 200 verdict the model expects. Any OTHER
        # filesystem fault (a directory or regular-file collision, a permission or
        # symlink-loop error) is broken operator config like a malformed manifest, so it
        # propagates uncaught -> the app's generic 500.
        message = f"no trusted manifest for dataset {spec.dataset.name!r}"
        verdict = _single("dataset.manifest_available", message, layer="verify")
        return Outcome(verdict=verdict, spec=spec)

    # verify_run admits/decodes this exact snapshot; broken manifest/mispair -> raise -> 500.
    run = checks.verify_run(
        spec, manifest_bytes, data_dir=settings.data_dir, limits=settings.limits
    )
    verdict = Verdict(verified=run.report.passed, layer="verify", results=run.report.results)
    return Outcome(verdict=verdict, spec=spec, trace=run.trace, evidence=run.evidence)


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
    unverified outcome. CPU-bound + synchronous (the handler offloads it via sync_to_thread).
    Split from verify_and_render so app.py's proposer can pin the requested dataset name between
    decode and verification.

    The offline HTML page is built + stored on EVERY verified render (render(include_html=True)
    unconditionally, then store.put_chart under plot_id), so both entry routes — verify-and-render
    and the proposer — populate the chart store through this one seam; GET /chart/{plot_id} then
    serves that page until chart-LRU eviction (a verified chart can 404 while its certificate
    still lives — see store.py's mixed-state note). include_html now governs ONLY the JSON-body
    html copy (the large inline view the caller opts into); the stored page is not gated by it."""
    if not outcome.verdict.verified:
        return outcome.verdict
    # verified => the verify stage ran and passed, so spec + evidence are populated (cast, not
    # assert: an assert's never-taken branch fails the 100% gate — the M1.5a lesson).
    spec = cast("VPlotSpec", outcome.spec)
    evidence = cast("checks.RecomputedEvidence", outcome.evidence)
    try:
        prepared = render.prepare_render(spec, evidence, limits=settings.limits)
        result = render.render_prepared(prepared, include_html=True, limits=settings.limits)
    except VerificationError as exc:
        resource_failure = checks.CheckResult(
            check=exc.check,
            status="fail",
            severity="blocking",
            message=str(exc),
        )
        return Verdict(
            verified=False,
            layer=outcome.verdict.layer,
            results=(*outcome.verdict.results, resource_failure),
        )
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
