# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Application factory: the trusted verifier behind Litestar routes (M2.1 + M2.2).

create_app builds a fully configured Litestar app from a trusted Settings container —
routes registered, settings on app.state, the framework body cap set to
settings.max_body_bytes. Transport only: no verification trust lives here (POC_SCOPE
service boundary).

Routes: /health (liveness) and POST /verify-only (M2.2). The verify-only handler reads
the RAW request body via request.body() before any verifier work, so decode_spec's strict
decode stays authoritative (a framework-parsed `data: bytes` would JSON-decode first,
collapsing duplicate keys), and Litestar's body cap raises 413 the moment that read
exceeds settings.max_body_bytes — keeping oversize input off the verifier.

Error split: a verification outcome (verified, decoded-but-failed, or a decode failure)
is a 200 Verdict; only transport misuse (wrong content-type -> 415, oversize -> 413,
wrong method -> 405) or a server-config fault (a broken or unreadable trusted manifest ->
500) answers
RFC 9457 application/problem+json, shaped by the two exception handlers below.

OpenAPI/schema surface stays off here (owned by M2.4's deterministic OpenAPIConfig +
committed golden); explicit operation_id + summary on each route forward-prep it (M4 Open
WebUI maps operationId -> tool name).
"""

from http import HTTPStatus
from typing import Any, cast

from litestar import Litestar, Request, Response, get, post
from litestar.concurrency import sync_to_thread
from litestar.datastructures import State
from litestar.exceptions import HTTPException
from litestar.status_codes import (
    HTTP_200_OK,
    HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from verifier import __version__
from verifier.service.models import Problem, Verdict
from verifier.service.pipeline import verify_only
from verifier.service.settings import Settings


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


def _problem_response(status: int, detail: str) -> Response[Problem]:
    """An RFC 9457 application/problem+json response (transport/server faults only)."""
    problem = Problem(title=HTTPStatus(status).phrase, status=status, detail=detail)
    return Response(problem, status_code=status, media_type="application/problem+json")


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
    return Litestar(
        route_handlers=[health, verify_only_route],
        state=State({"settings": settings}),
        request_max_body_size=settings.max_body_bytes,
        # OpenAPI/schema routes (Swagger, Redoc, openapi.json) are owned by M2.4, which
        # adds a deterministic config + golden; the surface here stays /health + verify-only.
        openapi_config=None,
        exception_handlers={
            HTTPException: _http_exception_handler,
            Exception: _internal_exception_handler,
        },
    )
