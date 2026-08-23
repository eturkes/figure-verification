# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Service pipeline: raw spec bytes -> internal evidence -> verdict or verified render.

The transport hands raw request bytes straight here (never a framework-parsed object), so
schema.decode_spec's strict, fail-closed decode — its duplicate-key rescan included —
stays authoritative. verify_only strings the trusted core stages it otherwise offers
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
app's 500 handler. Resource-policy breaches instead remain ordinary failed 200 Verdicts, with ONE
operator-configuration exception common to both modes (POC_SCOPE.md): max_attestation_bytes bounds
the signed OCCURRENCE as well as the certificate, so a value too small to sign even the rejection
record turns that failed verdict into a generic 500 with no attempt.
The untrusted model controls only the dataset name, not what the trusted data_dir holds at
that path, so a name with no manifest fails closed as a 200 Verdict.

Outcome is an internal union of two CONCRETE per-mode dataclasses, never serialized:
DatasetOutcome and FormulaOutcome each carry the inputs admitted so far, that mode's evidence
after every core check passes, the bounded formal trace, and a prepared artifact only after the
final merged report passes. Keeping them concrete is what makes `verdict.verified` imply a static
artifact family, so a cross-mode misroute is a type error rather than a cast the checker cannot
see through. Sensitive bytes stay out of both repr forms and every route returns only
outcome.verdict or a separately built RenderVerdict / FormulaScriptVerdict.

render_outcome (split from verify_and_render) is the render half: on a PASSING
verdict it renders the verified chart, signs the exact VCert bytes into deterministic DSSE,
content-addresses the envelope (plot_id = SHA-256(envelope), spec_id = the payload's spec_hash),
rebuilds the off-chain chart page from returned authoritative Vega with the signed provenance
display, atomically archives the complete plot + signed attempt, then caches the chart page and
answers a RenderVerdict. A failing verdict commits a signed attempt and returns the plain Verdict
with no chart. Both public shapes gain the derived attempt id only after commit. A passing
outcome's already-formal-passed artifact is rendered directly, so no trusted file is read and no
verification/build/solver work repeats. A render resource
refusal appends its tagged failure and commits a rejected attempt before return; archive failure
escapes before cache publication, while invariant/native faults still escape to 500.
verify_and_render is the thin verify_only -> render_outcome composition; app.py's proposer
reuses these seams — decode_stage, dataset pin, verify_decoded, render_outcome — so an
off-request name is refused before the wrong dataset's trusted I/O.

Formula mode mirrors that whole shape with its own seams and its own carriers, sharing only the
occurrence machinery: decode_formula_stage -> verify_formula_decoded (exact rational evaluation ->
core checks -> formal x-order preparation) -> emit_formula_outcome (fixed-template script emission
-> VCert v0.3 -> DSSE -> atomic archive commit), composed by verify_formula_and_emit.
verify_formula_decoded reads no dataset and no manifest, so it has no manifest-absence verdict and
no dataset-filesystem 500 branch; emission still runs the shared signer/archive seam, whose
config, invariant, and native faults escape to 500 exactly as they do in dataset mode. It produces
script BYTES the verifier never executes, so it writes no chart cache and its context carries no
store. A failing formula verdict answers the plain Verdict, never a script.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypedDict, cast

import msgspec

from verifier import attestation, checks, formal, matplotlib_script, render, vcert
from verifier.errors import VerificationError
from verifier.formula_prepare import PreparedFormula, prepare_formula
from verifier.limits import read_bounded
from verifier.schema import FormulaPlotSpec, VPlotSpec, decode_formula_spec, decode_spec
from verifier.service.archive import (
    Archive,
    AttemptArtifacts,
    AttemptDraft,
    AttemptOutcome,
    AttemptRoute,
    DatasetPlotBundle,
    FormulaPlotBundle,
    PlotBundle,
    materialize_formula_plot_bundle,
    materialize_plot_bundle,
)
from verifier.service.identity import Signer
from verifier.service.model_client import ProposalTrace
from verifier.service.models import FormulaScriptVerdict, RenderVerdict, Verdict
from verifier.service.settings import Settings
from verifier.service.store import ArtifactStore

_EMPTY_TRACE = checks.VerificationTrace(manifest_bytes=None, source_bytes=None)
_EMPTY_FORMULA_TRACE = checks.FormulaVerificationTrace()
_ENCODER = msgspec.json.Encoder(order="deterministic")


@dataclass(frozen=True, slots=True)
class DatasetOutcome:
    """Internal final-verification state; trace/evidence/build never serialize or enter repr."""

    verdict: Verdict
    spec: VPlotSpec | None = field(default=None, repr=False)
    trace: checks.VerificationTrace = field(default=_EMPTY_TRACE, repr=False)
    evidence: checks.DatasetEvidence | None = field(default=None, repr=False)
    formal_trace: tuple[formal.FormalTrace, ...] = field(default=(), repr=False)
    prepared: render.PreparedArtifact | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class FormulaOutcome:
    """Formula mode's sibling carrier; no dataset byte trace exists to retain."""

    verdict: Verdict
    spec: FormulaPlotSpec | None = field(default=None, repr=False)
    trace: checks.FormulaVerificationTrace = field(default=_EMPTY_FORMULA_TRACE, repr=False)
    evidence: checks.FormulaEvidence | None = field(default=None, repr=False)
    formal_trace: tuple[formal.FormalTrace, ...] = field(default=(), repr=False)
    prepared: PreparedFormula | None = field(default=None, repr=False)


# Concrete per-mode carriers, never one widened Outcome.prepared: a shared artifact field would
# stop `verdict.verified` from implying a static artifact family, so every consumer would need a
# cast that hides a misroute from mypy instead of surfacing it (the same shape the formula
# verification run rejected for its own evidence field).
type Outcome = DatasetOutcome | FormulaOutcome


class _ModelTraceRoles(TypedDict):
    """The three model-trace byte roles, named exactly as `AttemptArtifacts` carries them."""

    model_request: bytes | None
    model_response: bytes | None
    model_reply: bytes | None


def _model_trace_roles(proposal_trace: ProposalTrace | None) -> _ModelTraceRoles:
    """Project one observed model exchange onto its three archived roles.

    A route that called no model has no trace, and then all three roles are absent together. Every
    occurrence writer shares this projection so the two proposer routes cannot drift into
    describing the same exchange with different role sets."""
    if proposal_trace is None:
        return {"model_request": None, "model_response": None, "model_reply": None}
    return {
        "model_request": proposal_trace.request_body,
        "model_response": proposal_trace.response_body,
        "model_reply": proposal_trace.reply_bytes,
    }


@dataclass(frozen=True, slots=True, kw_only=True)
class AttemptWriter:
    """One app's durable occurrence writer: archive + signer + exact active limits."""

    settings: Settings
    archive: Archive
    signer: Signer

    def record_problem(
        self,
        route: AttemptRoute,
        outcome: AttemptOutcome,
        http_status: int,
        proposal_trace: ProposalTrace | None = None,
        raw_spec: bytes | None = None,
    ) -> str:
        """Sign + commit one classified admitted proposer fault before its Problem returns.

        The caller names its own route: a formula proposer fault is recorded against
        `/propose-formula`, never against the dataset proposer that once was the only caller."""
        artifacts = AttemptArtifacts(raw_spec=raw_spec, **_model_trace_roles(proposal_trace))
        draft = AttemptDraft(
            occurred_at=datetime.now(UTC),
            route=route,
            http_status=http_status,
            outcome=outcome,
            artifacts=artifacts,
        )
        return self.archive.record_attempt(
            draft, self.signer, limits=self.settings.limits
        ).attempt_id


@dataclass(frozen=True, slots=True, kw_only=True)
class AttemptContext:
    """The writer + observed route bytes every artifact-producing route commits an attempt from."""

    writer: AttemptWriter
    route: AttemptRoute
    raw_spec: bytes = field(repr=False)
    proposal_trace: ProposalTrace | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class RenderContext(AttemptContext):
    """A dataset render attempt: the shared occurrence state plus the ephemeral chart store."""

    store: ArtifactStore


@dataclass(frozen=True, slots=True, kw_only=True)
class FormulaContext(AttemptContext):
    """A formula attempt: the shared occurrence state and deliberately nothing else.

    Formula mode emits script BYTES it never executes, so it produces no chart page and holds no
    ArtifactStore reference at all — the never-cached property is structural here, not a
    convention a future edit could quietly drop."""


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


def verify_decoded(spec: VPlotSpec, settings: Settings) -> DatasetOutcome:
    """Verify an already-decoded spec: resolve + load the trusted manifest, run checks, map the
    report onto a DatasetOutcome. A dataset with no manifest fails closed as a 200 Verdict; a
    PRESENT but unloadable manifest (or a checks mispair) raises -> the app's 500 (see the module
    docstring). Split from verify_only so the proposer pins the name between decode_stage
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
        return DatasetOutcome(verdict=verdict, spec=spec)
    except FileNotFoundError:
        # ENOENT = genuine absence (this dataset is not provisioned; a dangling
        # symlink resolves here too) -> the 200 verdict the model expects. Any OTHER
        # filesystem fault (a directory or regular-file collision, a permission or
        # symlink-loop error) is broken operator config like a malformed manifest, so it
        # propagates uncaught -> the app's generic 500.
        message = f"no trusted manifest for dataset {spec.dataset.name!r}"
        verdict = _single("dataset.manifest_available", message, layer="verify")
        return DatasetOutcome(verdict=verdict, spec=spec)

    # verify_run admits/decodes this exact snapshot; broken manifest/mispair -> raise -> 500.
    run = checks.verify_run(
        spec, manifest_bytes, data_dir=settings.data_dir, limits=settings.limits
    )
    if not run.report.passed:
        verdict = Verdict(verified=False, layer="verify", results=run.report.results)
        return DatasetOutcome(verdict=verdict, spec=spec, trace=run.trace)

    # A passing core report owns recomputation evidence. Preparation builds/serializes once, then
    # runs every applicable formal obligation over that exact builder object. Resource refusals at
    # either boundary remain ordinary failed verdicts; invariant/builder faults still escape -> 500.
    evidence = run.require_evidence()
    try:
        preparation = render.prepare_render(spec, evidence, limits=settings.limits)
    except VerificationError as exc:
        failure = checks.make_result(exc.check, status="fail", message=str(exc))
        verdict = Verdict(
            verified=False,
            layer="verify",
            results=(*run.report.results, failure),
        )
        return DatasetOutcome(
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
    return DatasetOutcome(
        verdict=verdict,
        spec=spec,
        trace=run.trace,
        evidence=evidence,
        formal_trace=preparation.formal_trace,
        prepared=preparation.prepared,
    )


def verify_only(raw: bytes, settings: Settings) -> DatasetOutcome:
    """Run the trusted verify-only pipeline over raw spec bytes: decode_stage -> verify_decoded
    (see the module docstring). A decode failure is a 200 decode Verdict; otherwise the decoded
    spec is verified against its trusted manifest."""
    decoded = decode_stage(raw)
    if isinstance(decoded, Verdict):
        return DatasetOutcome(verdict=decoded)
    return verify_decoded(decoded, settings)


def decode_formula_stage(raw: bytes) -> FormulaPlotSpec | Verdict:
    """Strictly decode raw formula-spec bytes: the decoded FormulaPlotSpec, or a 200
    layer="decode" Verdict on a decode failure (an expected model failure mode, metered exactly
    like the dataset one). The formula decoder is its OWN strict decoder — a dataset VPlotSpec
    body fails here on its version literal, so the two modes can never cross at this seam.
    decode_formula_spec already re-raises a builtin UnicodeDecodeError as msgspec.DecodeError, so
    these two arms are the complete guard."""
    try:
        return decode_formula_spec(raw)
    except (msgspec.ValidationError, msgspec.DecodeError) as exc:
        return _single("spec.decode", str(exc), layer="decode")


def verify_formula_decoded(spec: FormulaPlotSpec, settings: Settings) -> FormulaOutcome:
    """Verify an already-decoded formula spec: parse, evaluate exactly, quantize, run the core
    checks, then formally prepare that recomputation. No dataset and no manifest is read, so this
    stage has no manifest-absence verdict and no dataset-filesystem 500 branch — the dataset error
    split simply has nothing to split here. A resource refusal at the preparation boundary stays an
    ordinary failed 200 verdict; an invariant fault still escapes to the app's 500, as does any
    signer/archive fault raised later by emit_formula_outcome."""
    run = checks.verify_formula_run(spec, limits=settings.limits)
    if not run.report.passed:
        verdict = Verdict(verified=False, layer="verify", results=run.report.results)
        return FormulaOutcome(verdict=verdict, spec=spec, trace=run.trace)

    evidence = run.require_evidence()
    try:
        preparation = prepare_formula(spec, evidence, limits=settings.limits)
    except VerificationError as exc:
        failure = checks.make_result(exc.check, status="fail", message=str(exc))
        verdict = Verdict(
            verified=False,
            layer="verify",
            results=(*run.report.results, failure),
        )
        return FormulaOutcome(verdict=verdict, spec=spec, trace=run.trace, evidence=evidence)

    verdict = Verdict(
        verified=preparation.report.passed,
        layer="verify",
        results=preparation.report.results,
    )
    return FormulaOutcome(
        verdict=verdict,
        spec=spec,
        trace=run.trace,
        evidence=evidence,
        formal_trace=preparation.formal_trace,
        prepared=preparation.prepared,
    )


def verify_formula(raw: bytes, settings: Settings) -> FormulaOutcome:
    """Run the trusted formula pipeline over raw spec bytes: decode_formula_stage ->
    verify_formula_decoded. A decode failure is a 200 decode Verdict."""
    decoded = decode_formula_stage(raw)
    if isinstance(decoded, Verdict):
        return FormulaOutcome(verdict=decoded)
    return verify_formula_decoded(decoded, settings)


def _dataset_attempt_artifacts(
    outcome: DatasetOutcome,
    raw_spec: bytes,
    verdict: bytes,
    proposal_trace: ProposalTrace | None,
) -> AttemptArtifacts:
    """Project one final dataset verdict onto only the exact bytes observed along its route."""
    return AttemptArtifacts(
        raw_csv=outcome.trace.source_bytes,
        raw_manifest=outcome.trace.manifest_bytes,
        raw_spec=raw_spec,
        verdict=verdict,
        **_model_trace_roles(proposal_trace),
    )


def _formula_attempt_artifacts(
    raw_spec: bytes, verdict: bytes, proposal_trace: ProposalTrace | None
) -> AttemptArtifacts:
    """Project one final formula verdict onto the byte families its route observes.

    Formula mode reads no CSV and no manifest, so raw_csv and raw_manifest stay absent by
    construction on both formula routes. The three model-trace roles follow the caller's trace:
    direct /verify-formula carries none, and /propose-formula carries the exchange that produced
    raw_spec. This takes no FormulaOutcome at all — a formula verdict projects no dataset trace —
    which is what makes a cross-mode misroute a type error rather than a runtime lookup that could
    silently pick the wrong arm."""
    return AttemptArtifacts(
        raw_spec=raw_spec, verdict=verdict, **_model_trace_roles(proposal_trace)
    )


def _verdict_bytes(verdict: Verdict, plot: PlotBundle | None) -> bytes:
    """The archived canonical verdict: a verified plot's own signed copy, else this encoding."""
    return plot.verdict if plot is not None else _ENCODER.encode(verdict)


def _record_attempt(
    context: AttemptContext,
    artifacts: AttemptArtifacts,
    plot: PlotBundle | None,
) -> str:
    """Sign + commit one verified/rejected occurrence and return its derived address."""
    draft = AttemptDraft(
        occurred_at=datetime.now(UTC),
        route=context.route,
        http_status=200,
        outcome=AttemptOutcome.VERIFIED if plot is not None else AttemptOutcome.REJECTED,
        artifacts=artifacts,
        plot=plot,
    )
    writer = context.writer
    return writer.archive.record_attempt(
        draft, writer.signer, limits=writer.settings.limits
    ).attempt_id


def _record_verdict_attempt(
    outcome: DatasetOutcome,
    verdict: Verdict,
    context: RenderContext,
    plot: DatasetPlotBundle | None,
) -> str:
    """Sign + commit one dataset occurrence and return its derived address."""
    artifacts = _dataset_attempt_artifacts(
        outcome,
        context.raw_spec,
        _verdict_bytes(verdict, plot),
        context.proposal_trace,
    )
    return _record_attempt(context, artifacts, plot)


def _record_formula_attempt(
    verdict: Verdict,
    context: FormulaContext,
    plot: FormulaPlotBundle | None,
) -> str:
    """Sign + commit one formula occurrence and return its derived address.

    The concrete bundle annotation is the static half of the cross-mode closure: passing a
    DatasetPlotBundle here is a type error, so the archive's pre-sign route/source refusal
    never has to be the only thing standing between a misroute and a signed occurrence."""
    artifacts = _formula_attempt_artifacts(
        context.raw_spec, _verdict_bytes(verdict, plot), context.proposal_trace
    )
    return _record_attempt(context, artifacts, plot)


def _extended_failure(verdict: Verdict, exc: VerificationError) -> Verdict:
    """Append one tagged resource refusal to an otherwise passing verdict, blocking it."""
    failure = checks.make_result(exc.check, status="fail", message=str(exc))
    return Verdict(
        verified=False,
        layer=verdict.layer,
        results=(*verdict.results, failure),
    )


def render_outcome(
    outcome: DatasetOutcome,
    context: RenderContext,
    *,
    include_html: bool,
) -> Verdict | RenderVerdict:
    """Render, durably capture, then cache one admitted artifact-producing outcome.

    A failing verdict commits its exact observed inputs + canonical pre-address verdict and returns
    the same verdict extended with the derived attempt id. A passing outcome renders/signs once,
    atomically commits the complete plot + occurrence, and only then publishes the chart cache.
    Archive failure therefore escapes before an outcome or cache entry can leak. CPU-bound +
    synchronous (the handler offloads the entire operation through its admission permit).

    The signed offline HTML page is rebuilt + stored on EVERY verified render from the returned
    authoritative Vega bytes + VCert, then final-byte-admitted after adding the badge, signer
    keyid, plot_id, and exact certificate URL. Both entry routes — verify-and-render and the
    proposer — populate the chart store through this one seam; GET /chart/{plot_id} serves that
    page until chart-LRU eviction (a verified chart can 404 while its certificate remains durable
    in the archive). include_html governs ONLY the JSON-body html copy (the large
    inline view the caller opts into); the stored page is not gated by it."""
    if not outcome.verdict.verified:
        attempt_id = _record_verdict_attempt(
            outcome,
            outcome.verdict,
            context,
            None,
        )
        return msgspec.structs.replace(outcome.verdict, attempt_id=attempt_id)
    # verified => the final verify/formal stage passed, so prepared is populated (cast, not assert:
    # an assert's never-taken branch fails the 100% gate).
    prepared = cast("render.PreparedArtifact", outcome.prepared)
    try:
        settings = context.writer.settings
        signer = context.writer.signer
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
            certificate_url=certificate_url,
        )
        chart_bytes = render.admit_html(chart_html, settings.limits)
    except VerificationError as exc:
        verdict = _extended_failure(outcome.verdict, exc)
        attempt_id = _record_verdict_attempt(
            outcome,
            verdict,
            context,
            None,
        )
        return msgspec.structs.replace(verdict, attempt_id=attempt_id)
    plot = materialize_plot_bundle(
        prepared,
        result,
        envelope,
        signer,
        limits=settings.limits,
    )
    attempt_id = _record_verdict_attempt(
        outcome,
        outcome.verdict,
        context,
        plot,
    )
    spec_id = cert.spec_hash.removeprefix("sha256:")
    context.store.put_chart(plot_id, chart_bytes)
    return RenderVerdict(
        verified=True,
        layer=outcome.verdict.layer,
        results=outcome.verdict.results,
        attempt_id=attempt_id,
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
    context: RenderContext,
    *,
    include_html: bool,
) -> Verdict | RenderVerdict:
    """Verify raw spec bytes, then render + store on a passing verdict (verify_only ->
    render_outcome). A failing verdict answers the plain Verdict — never a chart. CPU-bound +
    synchronous (the handler offloads it via sync_to_thread)."""
    return render_outcome(
        verify_only(context.raw_spec, context.writer.settings),
        context,
        include_html=include_html,
    )


def _reject_formula(verdict: Verdict, context: FormulaContext) -> Verdict:
    """Commit one rejected formula occurrence and return that verdict carrying its address."""
    attempt_id = _record_formula_attempt(verdict, context, None)
    return msgspec.structs.replace(verdict, attempt_id=attempt_id)


def emit_formula_outcome(
    outcome: FormulaOutcome,
    context: FormulaContext,
) -> Verdict | FormulaScriptVerdict:
    """Emit, certify, sign, then durably capture one admitted formula outcome.

    Formula mode's counterpart to render_outcome, under the same discipline and the same never-a-
    chart shape: a failing verdict commits its exact observed inputs plus the canonical pre-address
    verdict and returns the plain Verdict extended with the derived attempt id. A passing outcome
    emits the fixed-template script once, rebinds its four carriers into VCert v0.3, signs those
    exact bytes into deterministic DSSE, and atomically commits the complete formula plot and its
    occurrence before answering.

    ONLY A VERIFIED 200 RETURNS OR ARCHIVES A SCRIPT ARTIFACT; EVERY FAILED VERDICT DOES NEITHER.
    Script bytes ARE constructed before the size ceiling can measure them — that ceiling admits the
    EXACT emitted length by design — so the guarantee is about what leaves this function, not about
    what the emitter internally builds. Three refusal carriers reach here and each drops the
    artifact: prepare_formula returns prepared=None on a formal-semantic failure (never seen here,
    since the verdict is then unverified), emit_matplotlib_script returns artifact=None on a
    float64-fidelity failure, and every resource breach raises a tagged VerificationError. The
    claim is stated over VERDICTS, not over non-2xx responses, because emission/certification/
    signing necessarily precede the archive's transactional commit: a capacity 507 or an archive
    500 can land AFTER a script was built and signed in memory. Those answer a Problem, never a
    verdict and never a script, and the atomic commit is what keeps the signed bytes from becoming
    durable or observable.

    The service emits script BYTES and never executes them, so there is no chart page, no
    ArtifactStore write, and no display cache on any path — FormulaContext carries no store to
    write to. matplotlib, the interpreter that would run these bytes, and the resulting pixels stay
    display trust, exactly as SVG rasterization does for dataset mode. CPU-bound + synchronous
    (the handler offloads the whole operation through its admission permit).
    """
    if not outcome.verdict.verified:
        return _reject_formula(outcome.verdict, context)
    # verified => the final verify/formal stage passed, so prepared is populated (cast, not assert:
    # an assert's never-taken branch fails the 100% gate).
    prepared = cast("PreparedFormula", outcome.prepared)
    settings = context.writer.settings
    signer = context.writer.signer
    try:
        emission = matplotlib_script.emit_matplotlib_script(prepared, limits=settings.limits)
    except VerificationError as exc:
        return _reject_formula(_extended_failure(outcome.verdict, exc), context)

    artifact = emission.artifact
    if artifact is None:
        # A semantic emission failure: the merged report already carries the blocking result, so
        # it replaces the verdict wholesale rather than extending the passing one.
        semantic_failure = Verdict(
            verified=False,
            layer=outcome.verdict.layer,
            results=emission.report.results,
        )
        return _reject_formula(semantic_failure, context)

    try:
        certificate = vcert.build_formula_certificate(artifact)
        envelope = attestation.sign_vcert_v03(
            certificate,
            signer.private_key,
            keyid=signer.keyid,
            limits=settings.limits,
        )
    except VerificationError as exc:
        return _reject_formula(_extended_failure(outcome.verdict, exc), context)

    plot = materialize_formula_plot_bundle(
        artifact,
        certificate,
        envelope,
        signer,
        limits=settings.limits,
    )
    attempt_id = _record_formula_attempt(outcome.verdict, context, plot)
    # build_formula_certificate mints exactly the formula family, and VCertV03.__post_init__
    # correlates source, artifact, and TCB by exact type on construction, so no other member is
    # reachable here (cast, not assert, for the 100% gate).
    source = cast("vcert.FormulaSourceCert", certificate.source)
    certified_script = cast("vcert.MatplotlibScriptArtifactCert", certificate.artifact)
    return FormulaScriptVerdict(
        verified=True,
        layer=outcome.verdict.layer,
        results=artifact.results,
        attempt_id=attempt_id,
        plot_id=hashlib.sha256(envelope).hexdigest(),
        spec_id=certificate.spec_hash.removeprefix("sha256:"),
        formula_hash=source.formula_hash,
        spec_hash=certificate.spec_hash,
        plotted_table_hash=certificate.plotted_table_hash,
        matplotlib_script_hash=certified_script.matplotlib_script_hash,
        matplotlib_script=artifact.matplotlib_script.decode("utf-8"),
    )


def verify_formula_and_emit(context: FormulaContext) -> Verdict | FormulaScriptVerdict:
    """Verify raw formula-spec bytes, then emit + certify + capture on a passing verdict
    (verify_formula -> emit_formula_outcome). A failing verdict answers the plain Verdict — never
    a script. CPU-bound + synchronous (the handler offloads it via sync_to_thread)."""
    return emit_formula_outcome(
        verify_formula(context.raw_spec, context.writer.settings),
        context,
    )
