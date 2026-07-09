# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Hardware-free OpenAI /v1 stub — the model-backend stand-in for the M4.3e smoke (M4.3c).

The three-service smoke needs an OpenAI-compatible backend on :8001, but the live model_backend is
NPU-gated (OpenVINO resolves via PYTHONPATH, the intel-accel env sourced). This stub serves the two
routes OWUI touches -- GET /v1/models (the LOAD-BEARING one: OWUI enumerates it into /api/models)
and POST /v1/chat/completions -- with NO accelerator: it REUSES model_backend.models (msgspec
structs only, no openvino import), so OWUI sees a BYTE-IDENTICAL wire contract versus the live
backend, and returns a fixed reply instead of generating one. It proposes no real spec, so the smoke
exercises provisioning + model enumeration + tool registration, never the verify path; M4.5 runs
that against the live backend.

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

    Mirrors model_backend/app.py's response constructor exactly (Choice wraps a ChatMessage, every
    field required) so the wire contract is byte-identical, but skips generation: the content is the
    static _STUB_REPLY and usage is a synthetic word-count proxy (prompt = summed message words,
    completion = reply words). Generation params (temperature / max_tokens) are ignored.
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
    """Serve the stub on the host/port parsed from settings.model_backend_url (one uvicorn worker).

    _require_http_url (Settings.__post_init__) validates the url's scheme + host but NOT a port, so
    a port-less base-url passes construction yet cannot pick a bind target -- fail loud here rather
    than letting uvicorn default to an unintended port. One worker matches model_backend's serve.
    """
    parsed = urlparse(settings.model_backend_url)
    host, port = parsed.hostname, parsed.port
    if host is None or port is None:
        msg = f"model_backend_url must include a host and port, got {settings.model_backend_url!r}"
        raise ValueError(msg)
    uvicorn.run(create_app(settings.model_id), host=host, port=port, workers=1)
