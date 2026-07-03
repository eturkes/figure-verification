# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Application factory — wires the trusted verifier behind Litestar routes (M2.1).

create_app builds a fully configured Litestar app from a Settings container: routes
registered, settings placed on app.state for handlers to read, and the framework body
cap set from settings.max_body_bytes so oversize bodies are rejected at the edge (413)
before any handler runs. /health is the liveness probe. Transport only — no
verification trust lives here (POC_SCOPE service boundary). Every route carries an
explicit operation_id + summary (M4 Open WebUI maps operationId to the tool name).
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
    )
