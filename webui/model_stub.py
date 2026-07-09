# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Hardware-free OpenAI /v1 stub — the model-backend stand-in for the M4.3e smoke (M4.3c).

The three-service smoke needs an OpenAI-compatible backend on :8001, but the live model_backend is
NPU-gated (OpenVINO resolves via PYTHONPATH, the intel-accel env sourced). This stub serves the two
routes OWUI touches -- GET /v1/models (the LOAD-BEARING one: OWUI enumerates it into /api/models)
and POST /v1/chat/completions -- with NO accelerator: it REUSES model_backend.models (msgspec
structs only, no openvino import), so OWUI sees the SAME /v1 wire SHAPE as the live backend (same
routes, status codes, object literals, and msgspec field order), and returns a fixed reply instead
of generating one -- the response VALUES are synthetic (see chat_completions). It proposes no real
spec, so the smoke exercises provisioning + model enumeration + tool registration, never the verify
path; M4.5 runs that against the live backend.

Not the trusted verifier and not even the real proposer -- a test fixture. Like the rest of webui/
it is coverage-excluded and unshipped, importing only gate-venv deps (msgspec / litestar / uvicorn),
so the gate runs it with no hardware. _STUB_REPLY is inert placeholder content until M4.5 settles
the live E2E reply.
"""

import time
import uuid
from typing import cast
from urllib.parse import urlparse

import uvicorn
from litestar import Litestar, get, post
from litestar.datastructures import State
from litestar.status_codes import HTTP_200_OK

from model_backend.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    ModelCard,
    ModelList,
    Usage,
)
from webui.settings import Settings

# The fixed assistant reply. The stub proposes nothing, so this is inert placeholder text until M4.5
# settles the live E2E behavior; it stays non-empty so its word count (completion_tokens) is >= 1.
_STUB_REPLY = "Stub backend online; the hardware-free stand-in proposes no chart spec."


@get("/v1/models", sync_to_thread=False)
def list_models(state: State) -> ModelList:
    """List the single served model (OpenAI /v1/models shape) -- the smoke's load-bearing route."""
    model_id = cast("str", state["model_id"])
    return ModelList(data=(ModelCard(id=model_id, created=int(time.time())),))


@post("/v1/chat/completions", status_code=HTTP_200_OK, sync_to_thread=False)
def chat_completions(data: ChatCompletionRequest, state: State) -> ChatCompletionResponse:
    """Return the fixed stub reply in an OpenAI chat-completion envelope.

    Builds the same ChatCompletionResponse SHAPE as model_backend/app.py (Choice wraps a
    ChatMessage, every field required) so the wire schema and field order match, but the VALUES are
    synthetic: static _STUB_REPLY content, always finish_reason "stop" (the live backend may also
    emit "length"), and a word-count usage proxy (prompt = summed message words, completion = reply
    words). Generation params (temperature / max_tokens) are ignored.
    """
    model_id = cast("str", state["model_id"])
    prompt_tokens = sum(len(m.content.split()) for m in data.messages)
    completion_tokens = len(_STUB_REPLY.split())
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex}",
        created=int(time.time()),
        model=model_id,
        choices=(
            Choice(
                index=0,
                message=ChatMessage(role="assistant", content=_STUB_REPLY),
                finish_reason="stop",
            ),
        ),
        usage=Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


def create_app(model_id: str) -> Litestar:
    """Build the stub Litestar app serving model_id on the OpenAI /v1 surface.

    OpenAPI auto-gen stays off (like model_backend): the backend is consumed by a hardcoded client
    shape, not via a served document. Handlers read model_id from app state.
    """
    return Litestar(
        route_handlers=[list_models, chat_completions],
        state=State({"model_id": model_id}),
        openapi_config=None,
    )


def serve(settings: Settings) -> None:
    """Serve the stub on the host/port from settings.model_backend_url (one uvicorn worker).

    Settings validates model_backend_url as an http(s) URL with a host, but not that the stub can
    actually bind and serve it: the stub mounts plain-HTTP routes under a fixed /v1, so only
    http://<host>:<port>/v1 is honorable. A base-url OWUI would be handed but the stub cannot serve
    (https, a non-/v1 path, a missing or non-numeric port) passes construction yet would surface as
    a TLS error or a 404 deep in the smoke -- fail loud here instead. .port raises on a non-numeric
    port, so read it defensively. One worker matches model_backend's serve.
    """
    parsed = urlparse(settings.model_backend_url)
    try:
        port = parsed.port
    except ValueError:
        port = None
    host = parsed.hostname
    if (
        parsed.scheme != "http"
        or host is None
        or port is None
        or parsed.path.rstrip("/") != "/v1"
        or parsed.query
        or parsed.fragment
    ):
        msg = (
            "model_backend_url must be http://<host>:<port>/v1 for the stub to bind and serve it, "
            f"got {settings.model_backend_url!r}"
        )
        raise ValueError(msg)
    uvicorn.run(create_app(settings.model_id), host=host, port=port, workers=1)
