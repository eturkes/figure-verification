# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Application factory: the trusted verifier behind Litestar routes (M2.1 + M2.2).

create_app builds a fully configured Litestar app from a trusted Settings container —
routes registered, settings on app.state, the framework body cap set to
settings.max_body_bytes. Transport only: no verification trust lives here (POC_SCOPE
service boundary).

Routes: /health (liveness), POST /verify-only (M2.2), POST /verify-and-render + GET
/certificate/{plot_id} + GET /spec/{spec_id} (M2.3). Both POST handlers read the RAW
request body via request.body() before any verifier work, so decode_spec's strict decode
stays authoritative (a framework-parsed `data: bytes` would JSON-decode first, collapsing
duplicate keys), and Litestar's body cap raises 413 the moment that read exceeds
settings.max_body_bytes — keeping oversize input off the verifier. verify-and-render stores
each verified render in the app's bounded ArtifactStore; the GETs serve the stored canonical
bytes verbatim (a malformed or absent id both answer the same 404 problem+json at the store
lookup — no leak of which ids were stored; a path that does not match the id route shape gets
Litestar's own 404 instead, still problem+json, still disclosing nothing about the store).

Error split: a verification outcome (verified, decoded-but-failed, or a decode failure)
is a 200 Verdict (or, when verified, a 200 RenderVerdict — a failing render answers a plain
Verdict, so a chart never rides an unverified outcome); only transport misuse (wrong
content-type -> 415, oversize -> 413, wrong method -> 405, unknown/malformed artifact id ->
404) or a server-config fault (a broken or unreadable trusted manifest, or a render that
returns None for a verified spec -> 500) answers RFC 9457 application/problem+json, shaped
by the two exception handlers below. Every response carries X-Content-Type-Options: nosniff
as an app default.

OpenAPI/schema surface stays off here (owned by M2.4's deterministic OpenAPIConfig +
committed golden); explicit operation_id + summary on each route forward-prep it (M4 Open
WebUI maps operationId -> tool name).
"""

import re
from collections.abc import Callable
from http import HTTPStatus
from typing import Any, cast

from litestar import Litestar, Request, Response, get, post
from litestar.concurrency import sync_to_thread
from litestar.datastructures import ResponseHeader, State
from litestar.exceptions import HTTPException
from litestar.params import FromPath, FromQuery
from litestar.status_codes import (
    HTTP_200_OK,
    HTTP_404_NOT_FOUND,
    HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from verifier import __version__
from verifier.service.models import Problem, RenderVerdict, Verdict
from verifier.service.pipeline import verify_and_render, verify_only
from verifier.service.settings import Settings
from verifier.service.store import ArtifactStore

# A content-addressed artifact id: exactly 64 lowercase hex (a SHA-256 hexdigest). fullmatch
# confines a path param to this shape, so a wrong-case, short, or traversal id never reaches
# the store (and a malformed id and a miss answer the same 404 — no validity leak).
_HEX64 = re.compile(r"[0-9a-f]{64}")

# X-Content-Type-Options: nosniff on every response. The app-level response_headers cover
# handler responses; the exception handlers re-set it via _problem_response, since layered
# response_headers do NOT reach exception-handler responses (one source of truth, no drift).
_NOSNIFF = ResponseHeader(name="x-content-type-options", value="nosniff")


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
    outcome = await sync_to_thread(verify_only, raw, settings)
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
    return await sync_to_thread(verify_and_render, raw, settings, store, include_html=include_html)


def _fetch_artifact(artifact_id: str, fetch: Callable[[str], bytes | None]) -> Response[bytes]:
    """Serve a stored artifact's canonical bytes verbatim as application/json. A malformed id
    (not 64 lowercase hex) or a store miss both raise 404 problem+json — the same answer, so a
    caller learns nothing about which ids ever existed."""
    if _HEX64.fullmatch(artifact_id) is None:
        raise HTTPException(detail="no such artifact", status_code=HTTP_404_NOT_FOUND)
    payload = fetch(artifact_id)
    if payload is None:
        raise HTTPException(detail="no such artifact", status_code=HTTP_404_NOT_FOUND)
    return Response(payload, media_type="application/json", status_code=HTTP_200_OK)


@get(
    "/certificate/{plot_id:str}",
    operation_id="getCertificate",
    summary="Fetch a stored verified-plot certificate by plot_id",
    sync_to_thread=False,
)
def certificate_route(plot_id: FromPath[str], state: State) -> Response[bytes]:
    """Serve the stored provenance certificate for plot_id (its canonical bytes verbatim)."""
    store = cast("ArtifactStore", state["store"])
    return _fetch_artifact(plot_id, store.certificate)


@get(
    "/spec/{spec_id:str}",
    operation_id="getSpec",
    summary="Fetch a stored verified spec's canonical bytes by spec_id",
    sync_to_thread=False,
)
def spec_route(spec_id: FromPath[str], state: State) -> Response[bytes]:
    """Serve the stored canonical spec bytes for spec_id (verbatim, as first hashed)."""
    store = cast("ArtifactStore", state["store"])
    return _fetch_artifact(spec_id, store.spec)


def _problem_response(status: int, detail: str) -> Response[Problem]:
    """An RFC 9457 application/problem+json response (transport/server faults only). Carries the
    nosniff default explicitly — layered response_headers do not reach exception responses."""
    problem = Problem(title=HTTPStatus(status).phrase, status=status, detail=detail)
    return Response(
        problem,
        status_code=status,
        media_type="application/problem+json",
        headers={_NOSNIFF.name: cast("str", _NOSNIFF.value)},
    )


def _http_exception_handler(_request: Request[Any, Any, Any], exc: Exception) -> Response[Problem]:
    """Render a Litestar HTTPException (415/413/405/404/...) as problem+json."""
    http_exc = cast("HTTPException", exc)
    return _problem_response(http_exc.status_code, http_exc.detail)


def _internal_exception_handler(
    _request: Request[Any, Any, Any], _exc: Exception
) -> Response[Problem]:
    """Render any uncaught exception as a generic 500 problem+json.

    Reached only by an operator-config fault escaping the pipeline (a broken, unreadable,
    or mispaired trusted manifest); the cause is withheld from the untrusted
    caller (it surfaces in the server log). The model cannot provoke this path — see the
    pipeline error split.
    """
    return _problem_response(
        HTTP_500_INTERNAL_SERVER_ERROR, "the verifier encountered an internal error"
    )


def create_app(settings: Settings) -> Litestar:
    """Build the Litestar app from trusted operator settings."""
    store = ArtifactStore(settings.store_cap)
    return Litestar(
        route_handlers=[
            health,
            verify_only_route,
            verify_and_render_route,
            certificate_route,
            spec_route,
        ],
        state=State({"settings": settings, "store": store}),
        request_max_body_size=settings.max_body_bytes,
        # nosniff on every response: the GETs and render serve stored/JSON-embedded bytes, and
        # the M1 hardening note keeps nosniff on any served artifact (M4 will add CSP for HTML).
        response_headers=[_NOSNIFF],
        # OpenAPI/schema routes (Swagger, Redoc, openapi.json) are owned by M2.4, which
        # adds a deterministic config + golden; the surface here stays the routes above.
        openapi_config=None,
        exception_handlers={
            HTTPException: _http_exception_handler,
            Exception: _internal_exception_handler,
        },
    )
