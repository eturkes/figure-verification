# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Application factory: the trusted verifier behind Litestar routes (M2.1 + M2.2).

create_app builds a fully configured Litestar app from a trusted Settings container —
routes registered, settings on app.state, the framework body cap set to
settings.max_body_bytes, one persistent signing identity loaded, and the exact versioned provenance
archive initialized before the app can serve. Every admitted outcome-bearing artifact POST commits
a signed attempt there before its response or cache publication. Transport only: no verification
trust lives here (POC_SCOPE service boundary).

Routes: /health (liveness), POST /verify-only (M2.2), POST /verify-and-render + GET
/certificate/{plot_id} + GET /spec/{spec_id} (M2.3) + GET /chart/{plot_id} (M4.1c), POST
/propose-spec (M3.3a), GET /key/{keyid} (M5.4g), GET /replay/{plot_id} (M5.5c), GET
/schema/openapi.json (M2.4). The
verify POST handlers read the RAW request body via request.body() before any verifier work, so
decode_spec's strict decode stays authoritative (a framework-parsed `data: bytes` would
JSON-decode first, collapsing duplicate keys), and Litestar's body cap raises 413 the moment that
read exceeds settings.max_body_bytes — keeping oversize input off the verifier.

Successful artifact POSTs commit the exact canonical DSSE envelope, canonical spec, and raw
signing public key to the SQLite archive before mutating any LRU. Certificate/spec/key GETs use
that archive as authority on every request, with narrow metadata-first bounded reads: they re-hold
the requested address, typed relations, exact bytes, and canonical spec/key form; certificate
reads additionally authenticate the canonical DSSE signature + exact VCert payload type under the
digest-matching archived key. That key proves archive self-consistency only, never identity or
operator trust. A malformed or truly absent address answers the same 404 problem+json; archive,
SQLite, relation, hash, signature, or type faults escape to the logged content-free 500. No warm
render LRU can bypass these checks. GET /chart/{plot_id} deliberately remains independent and
ephemeral: it serves only the chart LRU's offline HTML under Content-Security-Policy: sandbox
allow-scripts, and restart/eviction may 404 even while the durable public artifacts resolve.
/propose-spec instead decodes a small typed {user_request, dataset_name} JSON body, runs the
untrusted local model (service/model_client.py) to PROPOSE a spec, and hands the model's reply
— not the caller's body — through verify-and-render, pinned to the requested dataset name
(_verify_render_pinned); the model supplies only a spec (never plotted values) and cannot
redirect the verdict onto a different dataset than asked, so the verification claim is unmoved. A
VERIFIED proposal is returned as the Open WebUI Location-variant chart embed (a [ProposeResult,
summary] array under Content-Disposition: inline + a Location at GET /chart/{plot_id}; see
propose_spec_route); every committed success/failure carries its signed occurrence address.

Error split: a verification outcome (verified, semantic/resource-failed, or decode-failed)
is a 200 Verdict (or, when verified, a 200 RenderVerdict — a failing render answers a plain
Verdict, so a chart never rides an unverified outcome); transport misuse (wrong
content-type -> 415, oversize -> 413, wrong method -> 405, unknown/malformed artifact id ->
404, a malformed /propose-spec body -> 400), proposer input/token policy refusal (422),
process-local admission refusal (429), or a trusted config / implementation fault (a broken
manifest or invariant/native render fault -> 500)
answers RFC 9457 application/problem+json, shaped by the exception handlers below. /propose-spec
adds two more
problem+json outcomes over the model boundary — an unknown dataset name -> 404 (the name never
echoed); a caller/dataset/prompt context over resource policy before the backend call OR an exact
backend prompt-token refusal before native generation -> 422; and a backend that is unreachable
(503) or returned any other unusable/oversized reply (502). The route catches these closed typed
outcomes while it still owns the admission permit, commits their attempts in a worker, then returns
the fixed public Problem. A proposal that decodes but names a DIFFERENT dataset than requested is
refused 502 too, by the dataset-name pin (_verify_render_pinned) — never a verified 200 for an
off-request chart. These admitted classified proposer faults commit a signed attempt before their
Problem response. An archive logical-quota refusal replaces the original outcome with 507; another
archive fault becomes generic 500; neither leaks the original response, an attempt id, or a cache
entry. Every response carries X-Content-Type-Options: nosniff as an app default.

Every admitted POST and the replay GET enter one process-local
``AdmissionController`` shared across the application. A refusal answers RFC 9457 429 before
model, verifier/replay, or native-render work. An admitted permit spans async model wait and
transfers to the worker for verification, rendering, archive commit, and cache publication;
request cancellation cannot release it while that uncancellable worker remains active. This is
per-process logical admission — the canonical single uvicorn worker has one controller. Multiple
worker processes multiply the configured aggregate capacity and rate.

The OpenAPI 3.1 document is hand-authored (service/openapi.py) and served verbatim by
openapi_route at GET /schema/openapi.json; Litestar's auto-gen stays off (openapi_config=None)
because it introspects RenderVerdict.verified: Literal[True] and crashes. Each route still
carries an explicit operation_id + summary that MIRROR the document's hand-authored values (M4
Open WebUI maps operationId -> tool name; model-visible text = description, else summary); with
auto-gen off nothing consumes
these route-level copies — openapi.py hand-authors the operationIds it serves — but they keep
each handler self-describing and would feed auto-gen if it were ever re-enabled.
"""

import logging
import re
from collections.abc import Callable
from http import HTTPStatus
from typing import Any, cast

import msgspec
from litestar import Litestar, Request, Response, get, post
from litestar.datastructures import ResponseHeader, State
from litestar.exceptions import HTTPException
from litestar.params import FromPath, FromQuery
from litestar.status_codes import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_429_TOO_MANY_REQUESTS,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_502_BAD_GATEWAY,
    HTTP_507_INSUFFICIENT_STORAGE,
)

from verifier import __version__, attestation
from verifier import replay as replay_core
from verifier.service.admission import AdmissionController, JobPermit
from verifier.service.archive import (
    Archive,
    ArchiveIntegrityError,
    ArchiveNotFoundError,
    ArchiveQuotaError,
    AttemptOutcome,
    AttemptRoute,
    open_archive,
)
from verifier.service.identity import SigningIdentity, load_identity
from verifier.service.model_client import (
    DatasetNotFoundError,
    ModelUpstreamError,
    ProposalFault,
    ProposerPolicyError,
    propose_spec,
)
from verifier.service.models import Problem, ProposeRequest, ProposeResult, RenderVerdict, Verdict
from verifier.service.openapi import openapi_json_bytes
from verifier.service.pipeline import (
    AttemptWriter,
    Outcome,
    RenderContext,
    decode_stage,
    render_outcome,
    verify_and_render,
    verify_decoded,
    verify_only,
)
from verifier.service.replay import replay_plot_chart
from verifier.service.settings import Settings
from verifier.service.store import ArtifactStore

_LOGGER = logging.getLogger(__name__)

# Public artifact addresses are exact canonical strings. A malformed address and an archive miss
# answer the same 404, so callers learn nothing about which values have ever existed.
_HEX64 = re.compile(r"[0-9a-f]{64}")
_KEYID = re.compile(r"sha256:[0-9a-f]{64}")
_ED25519_PUBLIC_KEY_BYTES = 32

# X-Content-Type-Options: nosniff on every response. The app-level response_headers cover
# handler responses; the exception handlers re-set it via _problem_response, since layered
# response_headers do NOT reach exception-handler responses (one source of truth, no drift).
_NOSNIFF = ResponseHeader(name="x-content-type-options", value="nosniff")

_ADMISSION_REFUSAL_DETAIL = "the process-local verifier work limit is currently exhausted"
_PROPOSER_POLICY_DETAIL = "the proposer input exceeds the configured resource policy"
_ARCHIVE_QUOTA_DETAIL = "the provenance archive has insufficient logical storage capacity"
_FAULT_OUTCOME = {
    ProposalFault.TRANSPORT: AttemptOutcome.MODEL_TRANSPORT,
    ProposalFault.CONTENT_ENCODING: AttemptOutcome.MODEL_CONTENT_ENCODING,
    ProposalFault.RESPONSE_TOO_LARGE: AttemptOutcome.MODEL_RESPONSE_TOO_LARGE,
    ProposalFault.HTTP_STATUS: AttemptOutcome.MODEL_HTTP_STATUS,
    ProposalFault.PROMPT_TOKENS: AttemptOutcome.MODEL_PROMPT_TOKENS,
    ProposalFault.INVALID_ENVELOPE: AttemptOutcome.MODEL_INVALID_ENVELOPE,
    ProposalFault.NO_CHOICES: AttemptOutcome.MODEL_NO_CHOICES,
    ProposalFault.EMPTY_CONTENT: AttemptOutcome.MODEL_EMPTY_CONTENT,
}


class _RecordedProblem(msgspec.Struct, frozen=True):
    """One classified Problem whose signed attempt already committed."""

    status: int
    detail: str
    attempt_id: str


@get("/health", operation_id="health", summary="Liveness and version probe", sync_to_thread=False)
def health() -> dict[str, str]:
    """Report service liveness and the running package version."""
    return {"status": "ok", "version": __version__}


def _require_json(request: Request[Any, Any, Any]) -> None:
    """Reject a non-JSON request with 415. request.content_type[0] is the media-type
    essence — lowercased, parameters (charset) stripped; a missing header yields ""."""
    essence = request.content_type[0]
    if essence != "application/json":
        msg = f"Content-Type must be application/json, got {essence or 'none'!r}"
        raise HTTPException(detail=msg, status_code=HTTP_415_UNSUPPORTED_MEDIA_TYPE)


def _admit_work(state: State) -> JobPermit:
    """Acquire the application-global rate token + active slot, or refuse without waiting.

    Every admitted POST calls this only after bounded transport validation, and replay calls it
    after validating its path id, but always before model/verifier/worker work. The seam is shared
    by every admitted POST plus the replay GET.
    """
    admission = cast("AdmissionController", state["admission"])
    permit = admission.try_acquire()
    if permit is None:
        raise HTTPException(
            detail=_ADMISSION_REFUSAL_DETAIL, status_code=HTTP_429_TOO_MANY_REQUESTS
        )
    return permit


@post(
    "/verify-only",
    operation_id="verifyOnly",
    summary="Verify a VPlot spec and return a structured verdict",
    status_code=HTTP_200_OK,
)
async def verify_only_route(request: Request[Any, Any, Any], state: State) -> Verdict:
    """Verify a raw VPlot spec body; answer a structured verdict, never a chart.

    Raw-body-first: content-type is checked, then request.body() is read (raising 413 on an
    oversize body) and handed straight to the pipeline, which runs off the event loop in a
    worker thread (the verifier is CPU-bound and synchronous).
    """
    _require_json(request)
    raw = await request.body()
    settings = cast("Settings", state["settings"])
    with _admit_work(state) as permit:
        outcome = await permit.run_sync(verify_only, raw, settings)
    return outcome.verdict


@post(
    "/verify-and-render",
    operation_id="verifyAndRender",
    summary="Verify a VPlot spec and, only if verified, render the certified chart",
    status_code=HTTP_200_OK,
)
async def verify_and_render_route(
    request: Request[Any, Any, Any], state: State, *, include_html: FromQuery[bool] = False
) -> Verdict | RenderVerdict:
    """Verify a raw VPlot spec body; on a passing verdict return the rendered SVG plus its
    provenance certificate and content-addressed ids (and, with include_html=true, an offline
    HTML view), storing them for retrieval. A failing verdict returns a plain Verdict — never a
    chart. Raw-body-first like /verify-only; the verify+render work (CPU-bound) runs off the
    event loop in a worker thread.
    """
    _require_json(request)
    raw = await request.body()
    settings = cast("Settings", state["settings"])
    store = cast("ArtifactStore", state["store"])
    identity = cast("SigningIdentity", state["identity"])
    archive = cast("Archive", state["archive"])
    context = RenderContext(
        writer=AttemptWriter(settings=settings, archive=archive, signer=identity.signer),
        store=store,
        route=AttemptRoute.VERIFY_AND_RENDER,
        raw_spec=raw,
    )
    with _admit_work(state) as permit:
        return await permit.run_sync(
            verify_and_render,
            context,
            include_html=include_html,
        )


# The /propose-spec request body is a small typed JSON object (unlike the raw-body POSTs, whose
# body IS the untrusted spec decode_spec must own). Decode it strictly here — an unknown field,
# a missing field, or a traversal/non-.csv dataset name is transport misuse, not a spec proposal.
_PROPOSE_DECODER = msgspec.json.Decoder(ProposeRequest)


def _decode_propose_request(raw: bytes) -> ProposeRequest:
    """Strictly decode a /propose-spec body; a malformed or invalid body is a 400 (transport
    misuse), never a spec proposal — the model has not run yet, so there is no verdict to ride."""
    try:
        return _PROPOSE_DECODER.decode(raw)
    except (msgspec.DecodeError, msgspec.ValidationError, UnicodeDecodeError) as exc:
        msg = f"malformed propose request body: {exc}"
        raise HTTPException(detail=msg, status_code=HTTP_400_BAD_REQUEST) from exc


# checks._check_dataset_binding hashes the file NAMED IN THE SPEC, so absent this pin the model
# could propose a spec for a DIFFERENT provisioned dataset (its own valid name + hash) and verify
# honestly-but-off-request. The pin refuses that 502 right after decode, BEFORE verify_decoded
# reads the off-request dataset's trusted manifest — so an off-request name never triggers a
# manifest load (no 500 path, no present/broken/absent oracle) and no artifact is stored. The
# other dataset's name never leaks (a fixed detail).
_PIN_MISMATCH_DETAIL = "the model proposed a specification for a different dataset than requested"


def _verify_render_pinned(
    context: RenderContext,
    dataset_name: str,
) -> Verdict | RenderVerdict | _RecordedProblem:
    """Decode the model's proposed spec, refuse (502) a spec that names a dataset other than
    requested, then verify + render + store on the requested dataset. Pinning on the decoded name
    between decode_stage and verify_decoded keeps the request notion out of the trusted pipeline
    and refuses an off-request name BEFORE any trusted dataset I/O: a decode failure has no name to
    pin, so the 200 decode verdict flows (the metered failure mode); any other off-request name
    (its manifest present, broken, or absent alike) is a uniform 502, never a 500 or a store.
    CPU-bound + synchronous (the route offloads it via the admitted permit); the fixed 502 Problem
    carries the committed attempt id while naming no dataset."""
    raw = context.raw_spec
    decoded = decode_stage(raw)
    if isinstance(decoded, Verdict):
        return render_outcome(
            Outcome(verdict=decoded),
            context,
            include_html=False,
        )
    if decoded.dataset.name != dataset_name:
        attempt_id = context.writer.record_problem(
            AttemptOutcome.DATASET_MISMATCH,
            HTTP_502_BAD_GATEWAY,
            proposal_trace=context.proposal_trace,
            raw_spec=raw,
        )
        return _RecordedProblem(HTTP_502_BAD_GATEWAY, _PIN_MISMATCH_DETAIL, attempt_id)
    return render_outcome(
        verify_decoded(decoded, context.writer.settings),
        context,
        include_html=False,
    )


@post(
    "/propose-spec",
    operation_id="proposeSpec",
    summary="Propose a VPlot spec with the local model, then verify and render it",
    status_code=HTTP_200_OK,
)
async def propose_spec_route(
    request: Request[Any, Any, Any], state: State
) -> ProposeResult | Response[bytes] | Response[Problem]:
    """Ask the untrusted local model to propose a VPlot spec for the request over the named
    dataset, then verify + render that proposal pinned to the requested dataset name
    (_verify_render_pinned). The model supplies only a spec, never plotted values, so the claim
    boundary is unmoved: a malformed proposal rides a failing verdict (a 200), a proposal naming a
    DIFFERENT dataset than requested is refused 502 (never a verified 200 for an off-request
    chart), and a fault outside that flow (unknown dataset, an unreachable or unusable backend, a
    malformed body) answers problem+json. A VERIFIED proposal answers the Open WebUI
    Location-variant embed instead of a bare ProposeResult: a [ProposeResult, summary] JSON array
    under Content-Disposition: inline plus a Location header at GET /chart/{plot_id} on
    settings.public_base_url, so the chat UI renders the certified chart in a sandboxed iframe
    while the model sees only the lean summary string; every classified admitted outcome adds only
    its non-secret attempt id to the prior public shape. The model call is async; the admitted
    permit spans it, then transfers to the CPU-bound verify+render/archive worker off the event
    loop.
    """
    _require_json(request)
    raw = await request.body()
    settings = cast("Settings", state["settings"])
    store = cast("ArtifactStore", state["store"])
    identity = cast("SigningIdentity", state["identity"])
    archive = cast("Archive", state["archive"])
    writer = AttemptWriter(settings=settings, archive=archive, signer=identity.signer)
    req = _decode_propose_request(raw)
    with _admit_work(state) as permit:
        try:
            proposal = await propose_spec(req.user_request, req.dataset_name, settings)
        except DatasetNotFoundError as not_found:
            _LOGGER.info("propose-spec named an unknown dataset: %r", not_found.dataset_name)
            attempt_id = await permit.run_sync(
                writer.record_problem,
                AttemptOutcome.DATASET_NOT_FOUND,
                HTTP_404_NOT_FOUND,
            )
            return _problem_response(HTTP_404_NOT_FOUND, "no such dataset", attempt_id=attempt_id)
        except ProposerPolicyError as policy:
            _LOGGER.info("proposer resource policy refusal (%s)", policy.resource)
            attempt_outcome = (
                AttemptOutcome.PROPOSER_POLICY
                if policy.trace is None
                else _FAULT_OUTCOME[cast("ProposalFault", policy.trace.fault)]
            )
            attempt_id = await permit.run_sync(
                writer.record_problem,
                attempt_outcome,
                HTTP_422_UNPROCESSABLE_ENTITY,
                policy.trace,
            )
            return _problem_response(
                HTTP_422_UNPROCESSABLE_ENTITY,
                _PROPOSER_POLICY_DETAIL,
                attempt_id=attempt_id,
            )
        except ModelUpstreamError as upstream:
            fault = cast("ProposalFault", upstream.trace.fault)
            _LOGGER.warning(
                "model backend upstream fault serving /propose-spec (status=%d, fault=%s)",
                upstream.status,
                fault.value,
            )
            attempt_id = await permit.run_sync(
                writer.record_problem,
                _FAULT_OUTCOME[fault],
                upstream.status,
                upstream.trace,
            )
            return _problem_response(
                upstream.status,
                "the model backend did not return a usable proposal",
                attempt_id=attempt_id,
            )
        content = proposal.reply_bytes
        context = RenderContext(
            writer=writer,
            store=store,
            route=AttemptRoute.PROPOSE_SPEC,
            raw_spec=content,
            proposal_trace=proposal.trace,
        )
        verdict = await permit.run_sync(
            _verify_render_pinned,
            context,
            req.dataset_name,
        )
    if isinstance(verdict, _RecordedProblem):
        return _problem_response(verdict.status, verdict.detail, attempt_id=verdict.attempt_id)
    result = ProposeResult(model_reply=content.decode("utf-8"), verdict=verdict)
    if not isinstance(verdict, RenderVerdict):
        return result
    # Verified success -> the Open WebUI Location-variant embed. The body is a [ProposeResult,
    # summary] JSON array: element0 is the full structured result (raw reply + verdict), read by
    # direct and bench clients; element1 is a lean human summary string. Open WebUI discards
    # element0, str()-ifies element1 into the model's tool-result context (so it MUST stay a clean
    # string, never a dict/list), and renders the Location as a sandboxed chart iframe.
    # Content-Disposition: inline + Location is the embed trigger; the app-default nosniff already
    # rides the Response (the _fetch_artifact/chart precedent). Only verified-success bodies take
    # this shape — every failing admitted outcome keeps the bare ProposeResult shape (now extended
    # only by its nested verdict's attempt_id).
    base = cast("str", settings.public_base_url)
    summary = f"Verified chart for {req.dataset_name}: all {len(verdict.results)} checks passed."
    return Response(
        msgspec.json.encode([result, summary]),
        media_type="application/json",
        headers={
            "content-disposition": "inline",
            "location": f"{base}/chart/{verdict.plot_id}",
        },
    )


def _replay_plot_worker(
    plot_id: str,
    settings: Settings,
    archive: Archive,
    identity: SigningIdentity,
    store: ArtifactStore,
) -> bytes:
    """Replay synchronously in the admitted worker and publish only an exact rebuilt chart."""
    try:
        replay = replay_plot_chart(
            archive,
            identity.trusted_keys,
            plot_id,
            public_base_url=cast("str", settings.public_base_url),
            max_bytes=settings.max_archive_bytes,
            limits=settings.limits,
        )
    except ArchiveIntegrityError:
        return msgspec.json.encode(replay_core.archive_integrity_verdict())
    if replay.chart_html is not None:
        store.put_chart(plot_id, replay.chart_html)
    return msgspec.json.encode(replay.verdict)


@get(
    "/replay/{plot_id:str}",
    operation_id="replayPlot",
    summary="Replay an archived verified plot and report reproduction status",
    status_code=HTTP_200_OK,
)
async def replay_route(plot_id: FromPath[str], state: State) -> Response[bytes]:
    """Replay one durable plot under configured trust; regenerate its chart only if exact."""
    if _HEX64.fullmatch(plot_id) is None:
        raise HTTPException(detail="no such plot", status_code=HTTP_404_NOT_FOUND)
    settings = cast("Settings", state["settings"])
    archive = cast("Archive", state["archive"])
    identity = cast("SigningIdentity", state["identity"])
    store = cast("ArtifactStore", state["store"])
    with _admit_work(state) as permit:
        try:
            body = await permit.run_sync(
                _replay_plot_worker,
                plot_id,
                settings,
                archive,
                identity,
                store,
            )
        except ArchiveNotFoundError as exc:
            raise HTTPException(detail="no such plot", status_code=HTTP_404_NOT_FOUND) from exc
    return Response(body, media_type="application/json", status_code=HTTP_200_OK)


def _fetch_artifact(
    artifact_id: str,
    fetch: Callable[[str], bytes | None],
    *,
    address_pattern: re.Pattern[str] = _HEX64,
    media_type: str = "application/json",
    headers: dict[str, str] | None = None,
) -> Response[bytes]:
    """Serve exact artifact bytes after canonical-address validation and authoritative lookup.

    ``ArchiveNotFoundError`` and malformed addresses share one 404. Every archive integrity,
    schema, SQLite, authentication, or implementation fault escapes to the logged generic 500.
    The chart callback remains an ephemeral LRU read and reports its miss as ``None``.
    """
    if address_pattern.fullmatch(artifact_id) is None:
        raise HTTPException(detail="no such artifact", status_code=HTTP_404_NOT_FOUND)
    try:
        payload = fetch(artifact_id)
    except ArchiveNotFoundError as exc:
        raise HTTPException(detail="no such artifact", status_code=HTTP_404_NOT_FOUND) from exc
    if payload is None:
        raise HTTPException(detail="no such artifact", status_code=HTTP_404_NOT_FOUND)
    return Response(payload, media_type=media_type, status_code=HTTP_200_OK, headers=headers)


@get(
    "/certificate/{plot_id:str}",
    operation_id="getCertificate",
    summary="Fetch a durable verified-plot certificate by plot_id",
    sync_to_thread=True,
)
def certificate_route(plot_id: FromPath[str], state: State) -> Response[bytes]:
    """Serve an archive-authenticated canonical DSSE VCert envelope verbatim."""
    archive = cast("Archive", state["archive"])
    settings = cast("Settings", state["settings"])
    max_bytes = attestation.envelope_byte_limit(settings.max_attestation_bytes)
    return _fetch_artifact(
        plot_id,
        lambda address: archive.read_certificate(
            address,
            max_bytes=max_bytes,
            limits=settings.limits,
        ),
    )


@get(
    "/spec/{spec_id:str}",
    operation_id="getSpec",
    summary="Fetch a durable verified spec's canonical bytes by spec_id",
    sync_to_thread=True,
)
def spec_route(spec_id: FromPath[str], state: State) -> Response[bytes]:
    """Serve archive-validated canonical spec bytes under canon's exact spec address."""
    archive = cast("Archive", state["archive"])
    settings = cast("Settings", state["settings"])
    max_bytes = settings.max_body_bytes + settings.max_model_response_bytes
    return _fetch_artifact(
        spec_id,
        lambda address: archive.read_spec(address, max_bytes=max_bytes),
    )


@get(
    "/key/{keyid:str}",
    operation_id="getPublicKey",
    summary="Fetch an archived raw Ed25519 public key by exact keyid",
    sync_to_thread=True,
)
def public_key_route(keyid: FromPath[str], state: State) -> Response[bytes]:
    """Serve exact raw public-key bytes.

    Archive presence establishes no signer trust or identity.
    """
    archive = cast("Archive", state["archive"])
    return _fetch_artifact(
        keyid,
        lambda address: archive.read_key(address, max_bytes=_ED25519_PUBLIC_KEY_BYTES),
        address_pattern=_KEYID,
        media_type="application/octet-stream",
    )


# The chart page ships Content-Security-Policy: sandbox allow-scripts. A bare `sandbox` blocks the
# page's own inlined Vega + height-reporter JS; allow-scripts re-enables them; allow-same-origin
# is deliberately withheld so the embedded page stays a null origin. The app-default nosniff rides
# it too; a 404 (malformed or missing id) carries neither this CSP nor the text/html content-type.
_CHART_HEADERS = {"content-security-policy": "sandbox allow-scripts"}


@get(
    "/chart/{plot_id:str}",
    operation_id="getChart",
    summary="Fetch a stored verified chart page by plot_id",
    sync_to_thread=False,
)
def chart_route(plot_id: FromPath[str], state: State) -> Response[bytes]:
    """Serve the stored offline chart HTML page for plot_id (its bytes verbatim, as text/html
    under the sandbox CSP). Built + stored on every verified render regardless of the entry route
    (verify-and-render or the proposer), then served until chart-LRU eviction — a verified chart
    can 404 here while its certificate still lives (see store.py's mixed-state note)."""
    store = cast("ArtifactStore", state["store"])
    return _fetch_artifact(plot_id, store.chart, media_type="text/html", headers=_CHART_HEADERS)


@get(
    "/schema/openapi.json",
    operation_id="openapiSchema",
    summary="Fetch the service's hand-authored OpenAPI 3.1 document",
    sync_to_thread=False,
)
def openapi_route() -> Response[bytes]:
    """Serve the hand-authored OpenAPI 3.1 document (its committed canonical bytes verbatim).
    Litestar's auto-gen stays off — see create_app's openapi_config note."""
    return Response(openapi_json_bytes(), media_type="application/json", status_code=HTTP_200_OK)


def _problem_response(
    status: int, detail: str, *, attempt_id: str | None = None
) -> Response[Problem]:
    """An RFC 9457 response for a non-verdict HTTP outcome (misuse/admission/system fault).

    Carries the nosniff default explicitly — layered response headers do not reach exception
    responses.
    """
    problem = Problem(
        title=HTTPStatus(status).phrase,
        status=status,
        detail=detail,
        attempt_id=attempt_id,
    )
    return Response(
        problem,
        status_code=status,
        media_type="application/problem+json",
        headers={_NOSNIFF.name: cast("str", _NOSNIFF.value)},
    )


def _http_exception_handler(_request: Request[Any, Any, Any], exc: Exception) -> Response[Problem]:
    """Render a Litestar HTTPException (415/413/429/405/404/...) as problem+json."""
    http_exc = cast("HTTPException", exc)
    return _problem_response(http_exc.status_code, http_exc.detail)


def _internal_exception_handler(
    _request: Request[Any, Any, Any], exc: Exception
) -> Response[Problem]:
    """Log any uncaught exception, then answer a generic 500 problem+json.

    Reached by a trusted operator-config fault (a broken, unreadable, or mispaired manifest)
    or an implementation/native-render fault. Core resource-policy refusals stay structured 200
    verdicts; pre-work service admission refuses separately with 429. Neither reaches this
    handler. The handler logs the cause and traceback itself —
    Litestar does NOT log an exception a custom handler catches, so without this the fault
    would vanish from every log — then withholds the cause from the untrusted caller; see the
    pipeline error split.
    """
    _LOGGER.error("unhandled internal error serving a request", exc_info=exc)
    return _problem_response(
        HTTP_500_INTERNAL_SERVER_ERROR, "the verifier encountered an internal error"
    )


def _archive_quota_handler(_request: Request[Any, Any, Any], exc: Exception) -> Response[Problem]:
    """Replace an uncommitted endpoint outcome with a fixed RFC-9457 507 and no attempt id."""
    _LOGGER.warning("provenance archive logical quota refused an attempt", exc_info=exc)
    return _problem_response(HTTP_507_INSUFFICIENT_STORAGE, _ARCHIVE_QUOTA_DETAIL)


def create_app(settings: Settings) -> Litestar:
    """Build the Litestar app from trusted operator settings."""
    identity = load_identity(settings)
    archive = open_archive(settings)
    store = ArtifactStore(
        settings.store_cap,
        html_cap=settings.html_cap,
        render_cache_bytes=settings.render_cache_bytes,
        chart_cache_bytes=settings.chart_cache_bytes,
    )
    admission = AdmissionController(
        settings.max_active_jobs, settings.work_rate_per_minute, settings.work_burst
    )
    return Litestar(
        route_handlers=[
            health,
            verify_only_route,
            verify_and_render_route,
            propose_spec_route,
            replay_route,
            certificate_route,
            spec_route,
            public_key_route,
            chart_route,
            openapi_route,
        ],
        state=State(
            {
                "settings": settings,
                "identity": identity,
                "archive": archive,
                "store": store,
                "admission": admission,
            }
        ),
        request_max_body_size=settings.max_body_bytes,
        # nosniff on every response: the public GETs serve archive-validated exact bytes while
        # render responses embed trusted artifacts; the chart route layers a sandbox CSP on top
        # for its deliberately ephemeral HTML page (_CHART_HEADERS).
        response_headers=[_NOSNIFF],
        # Litestar's OpenAPI auto-gen stays OFF: it introspects response models via
        # msgspec.inspect, which raises on RenderVerdict.verified: Literal[True] (the M2.3
        # never-a-chart pin). The 3.1 document is hand-authored (service/openapi.py) and
        # served verbatim by openapi_route above.
        openapi_config=None,
        exception_handlers={
            ArchiveQuotaError: _archive_quota_handler,
            HTTPException: _http_exception_handler,
            Exception: _internal_exception_handler,
        },
    )
