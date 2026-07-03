# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Application factory — wires the trusted verifier behind Litestar routes (M2.1).

create_app builds a fully configured Litestar app from a Settings container: routes
registered, settings placed on app.state for handlers to read, and the framework body
cap set from settings.max_body_bytes. Litestar enforces that cap while the body is
consumed, so an oversize body raises 413 the moment a handler reads it — M2.2 handlers
read the raw body first, before any verifier work runs. Adds /health as a liveness
probe. Transport only — no verification trust lives here (POC_SCOPE service boundary).
The OpenAPI/schema surface is deliberately off here and owned by M2.4 (deterministic
OpenAPIConfig + committed golden); the explicit operation_id + summary on each route are
forward-prep for it (M4 Open WebUI maps operationId to the tool name).
"""

from litestar import Litestar, get
from litestar.datastructures import State

from verifier import __version__
from verifier.service.settings import Settings


@get(
    "/health",
    operation_id="health",
    summary="Liveness and version probe",
    sync_to_thread=False,
)
def health() -> dict[str, str]:
    """Report service liveness and the running package version."""
    return {"status": "ok", "version": __version__}


def create_app(settings: Settings) -> Litestar:
    """Build the Litestar app from trusted operator settings."""
    return Litestar(
        route_handlers=[health],
        state=State({"settings": settings}),
        request_max_body_size=settings.max_body_bytes,
        # OpenAPI/schema routes (Swagger, Redoc, openapi.json) are owned by M2.4, which
        # enables them with a deterministic config + golden; M2.1's surface stays /health.
        openapi_config=None,
    )
