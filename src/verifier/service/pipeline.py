# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Service pipeline: raw spec bytes -> internal evidence -> verdict or verified render.

The transport hands raw request bytes straight here (never a framework-parsed object), so
schema.decode_spec's strict, fail-closed decode — its duplicate-key rescan included —
stays authoritative. verify_only strings the trusted M1 stages the core otherwise offers
no single orchestrator for, as two composable halves: decode_stage (decode_spec) then
verify_decoded (bounded manifest read -> checks.verify_run -> exact builder preparation -> SMT),
mapping the final merged report onto a Verdict while retaining input/formal traces, recomputation
evidence, and a native-renderable artifact only after every applicable obligation passes.

Error split (POC_SCOPE service boundary): every verification outcome is a 200 Verdict —
including a spec that fails to decode (an expected model failure mode) or names a dataset
with no manifest (dataset.manifest_available) — a genuine absence the read reports as
FileNotFoundError. A trusted manifest that is PRESENT but unloadable (malformed JSON; a
non-file path raising a directory/permission/symlink-loop error at the read; or one whose
declared dataset mispairs with the spec) is operator misconfiguration: it escapes to the
app's 500 handler. Resource-policy breaches instead remain ordinary failed 200 Verdicts.
The untrusted model controls only the dataset name, not what the trusted data_dir holds at
that path, so a name with no manifest fails closed as a 200 Verdict.

Outcome is an internal dataclass, never serialized: it carries inputs admitted so far,
RecomputedEvidence after every core check passes, the bounded formal trace, and a prepared builder
artifact only after the final merged report passes. Sensitive bytes stay out of its repr and every
route returns only Outcome.verdict or a separately built RenderVerdict.

render_outcome (split from verify_and_render at M3.3b) is the render half: on a PASSING
verdict it renders the verified chart, signs the exact VCert bytes into deterministic DSSE,
content-addresses the envelope (plot_id = SHA-256(envelope), spec_id = the payload's spec_hash),
rebuilds the off-chain chart page from returned authoritative Vega with the signed provenance
display, stores the artifacts, and answers a RenderVerdict. A failing verdict returns the plain
Verdict with no chart. A passing outcome's already-formal-passed artifact is rendered directly,
so no trusted file is read and no verification/build/solver work repeats. A render resource
refusal appends its tagged failure and returns a plain Verdict before storage; invariant/native
faults still escape to 500.
verify_and_render is the thin verify_only -> render_outcome composition; app.py's proposer
reuses these seams — decode_stage, dataset pin, verify_decoded, render_outcome — so an
off-request name is refused before the wrong dataset's trusted I/O.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

import msgspec

from verifier import attestation, canon, checks, formal, render
from verifier.errors import VerificationError
from verifier.limits import read_bounded
from verifier.schema import VPlotSpec, decode_spec
from verifier.service.identity import Signer
from verifier.service.models import RenderVerdict, Verdict
from verifier.service.settings import Settings
from verifier.service.store import ArtifactStore

_EMPTY_TRACE = checks.VerificationTrace(manifest_bytes=None, source_bytes=None)


@dataclass(frozen=True, slots=True)
class Outcome:
    """Internal final-verification state; trace/evidence/build never serialize or enter repr."""

    verdict: Verdict
    spec: VPlotSpec | None = field(default=None, repr=False)
    trace: checks.VerificationTrace = field(default=_EMPTY_TRACE, repr=False)
    evidence: checks.RecomputedEvidence | None = field(default=None, repr=False)
    formal_trace: tuple[formal.FormalTrace, ...] = field(default=(), repr=False)
    prepared: render.PreparedArtifact | None = field(default=None, repr=False)


def _single(check: str, message: str, *, layer: Literal["decode", "verify"]) -> Verdict:
    """A blocking Verdict carrying one synthetic fail result at `layer`."""
    result = checks.make_result(check, status="fail", message=message)
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
    if not run.report.passed:
        verdict = Verdict(verified=False, layer="verify", results=run.report.results)
        return Outcome(verdict=verdict, spec=spec, trace=run.trace)

    # A passing core report owns recomputation evidence. Preparation builds/serializes once, then
    # runs every applicable formal obligation over that exact builder object. Resource refusals at
    # either boundary remain ordinary failed verdicts; invariant/builder faults still escape -> 500.
    evidence = cast("checks.RecomputedEvidence", run.evidence)
    try:
        preparation = render.prepare_render(spec, evidence, limits=settings.limits)
    except VerificationError as exc:
        failure = checks.make_result(exc.check, status="fail", message=str(exc))
        verdict = Verdict(
            verified=False,
            layer="verify",
            results=(*run.report.results, failure),
        )
        return Outcome(
            verdict=verdict,
            spec=spec,
            trace=run.trace,
            evidence=evidence,
        )

    verdict = Verdict(
        verified=preparation.report.passed,
        layer="verify",
        results=preparation.report.results,
    )
    return Outcome(
        verdict=verdict,
        spec=spec,
        trace=run.trace,
        evidence=evidence,
        formal_trace=preparation.formal_trace,
        prepared=preparation.prepared,
    )


def verify_only(raw: bytes, settings: Settings) -> Outcome:
    """Run the trusted verify-only pipeline over raw spec bytes: decode_stage -> verify_decoded
    (see the module docstring). A decode failure is a 200 decode Verdict; otherwise the decoded
    spec is verified against its trusted manifest."""
    decoded = decode_stage(raw)
    if isinstance(decoded, Verdict):
        return Outcome(verdict=decoded)
    return verify_decoded(decoded, settings)


def render_outcome(
    outcome: Outcome,
    settings: Settings,
    store: ArtifactStore,
    signer: Signer,
    *,
    include_html: bool,
) -> Verdict | RenderVerdict:
    """Render the verified chart for a passing Outcome, store the artifacts content-addressed, and
    answer a RenderVerdict. A failing verdict answers the plain Verdict — never a chart on an
    unverified outcome. CPU-bound + synchronous (the handler offloads it via sync_to_thread).
    Split from verify_and_render so app.py's proposer can pin the requested dataset name between
    decode and verification.

    The signed offline HTML page is rebuilt + stored on EVERY verified render from the returned
    authoritative Vega bytes + VCert, then final-byte-admitted after adding the badge, signer
    keyid, plot_id, and exact certificate URL. Both entry routes — verify-and-render and the
    proposer — populate the chart store through this one seam; GET /chart/{plot_id} serves that
    page until chart-LRU eviction (a verified chart can 404 while its certificate still lives —
    see store.py's mixed-state note). include_html governs ONLY the JSON-body html copy (the large
    inline view the caller opts into); the stored page is not gated by it."""
    if not outcome.verdict.verified:
        return outcome.verdict
    # verified => the final verify/formal stage passed, so spec + prepared are populated (cast, not
    # assert: an assert's never-taken branch fails the 100% gate — the M1.5a lesson).
    spec = cast("VPlotSpec", outcome.spec)
    prepared = cast("render.PreparedArtifact", outcome.prepared)
    try:
        result = render.render_prepared(prepared, include_html=False, limits=settings.limits)
        cert = result.certificate
        envelope = attestation.sign_vcert(
            cert,
            signer.private_key,
            keyid=signer.keyid,
            limits=settings.limits,
        )
        plot_id = hashlib.sha256(envelope).hexdigest()
        base = cast("str", settings.public_base_url)
        certificate_url = f"{base}/certificate/{plot_id}"
        chart_html = render.signed_chart_html(
            result.vega_lite.decode("utf-8"),
            cert,
            keyid=signer.keyid,
            plot_id=plot_id,
            certificate_url=certificate_url,
        )
        chart_bytes = render.admit_html(chart_html, settings.limits)
    except VerificationError as exc:
        resource_failure = checks.make_result(exc.check, status="fail", message=str(exc))
        return Verdict(
            verified=False,
            layer=outcome.verdict.layer,
            results=(*outcome.verdict.results, resource_failure),
        )
    spec_id = cert.spec_hash.removeprefix("sha256:")
    store.put(
        plot_id=plot_id,
        cert_bytes=envelope,
        spec_id=spec_id,
        spec_bytes=canon.spec_bytes(spec),
    )
    store.put_chart(plot_id, chart_bytes)
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
        vega_lite_hash=cert.vega_lite_hash,
        svg=result.svg,
        html=chart_html if include_html else None,
    )


def verify_and_render(
    raw: bytes,
    settings: Settings,
    store: ArtifactStore,
    signer: Signer,
    *,
    include_html: bool,
) -> Verdict | RenderVerdict:
    """Verify raw spec bytes, then render + store on a passing verdict (verify_only ->
    render_outcome). A failing verdict answers the plain Verdict — never a chart. CPU-bound +
    synchronous (the handler offloads it via sync_to_thread)."""
    return render_outcome(
        verify_only(raw, settings),
        settings,
        store,
        signer,
        include_html=include_html,
    )
