# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Litestar app for the local model backend — OpenAI /v1 surface (M3.1b).

Two routes the verifier client (M3.2) and Open WebUI (M4) use — POST /v1/chat/completions
(one non-streaming completion) and GET /v1/models (the single served model) — plus /health.
The model compiles once at create_app time (Engine.load, blocking); each generation runs off
the event loop in a worker thread behind the engine lock (asyncio.to_thread — one pipeline,
one accelerator). This is the UNTRUSTED proposer: request parsing is lenient (OpenAI-compat via the
typed msgspec body, unknown fields tolerated), and the verifier re-decodes every reply
strictly (POC_SCOPE). A BackendError (e.g. a reply over the response-byte ceiling) renders as
an OpenAI-style error body via the handler below; the verifier client reads any non-2xx as an
upstream fault.
Streaming is out of scope for this unit. Litestar's OpenAPI auto-gen stays off — the backend
is consumed by a hardcoded client shape, not via a served document.
"""

import asyncio
import time
import uuid
from typing import Any, cast

from litestar import Litestar, Request, Response, get, post
from litestar.datastructures import State
from litestar.status_codes import HTTP_200_OK

from model_backend.engine import BackendError, Engine
from model_backend.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    ErrorDetail,
    ErrorResponse,
    ModelCard,
    ModelList,
    Usage,
)
from model_backend.settings import Settings


@get("/health", sync_to_thread=False)
def health() -> dict[str, str]:
    """Report backend liveness."""
    return {"status": "ok"}


@post("/v1/chat/completions", status_code=HTTP_200_OK)
async def chat_completions(data: ChatCompletionRequest, state: State) -> ChatCompletionResponse:
    """Generate one non-streaming chat completion from the local model.

    The requested max_tokens is clamped into [1, settings.max_tokens]: the ceiling guards the
    single accelerator/lock against a caller inducing an unbounded generation, and the floor keeps a
    zero/omitted value from starving the reply (an omitted max_tokens uses the ceiling). The
    response reports settings.model_name (the one served model), never the caller's requested
    `model` — echoing an arbitrary name would misreport which model produced the spec.
    """
    settings = cast("Settings", state["settings"])
    engine = cast("Engine", state["engine"])
    requested = data.max_tokens if data.max_tokens is not None else settings.max_tokens
    max_tokens = max(1, min(requested, settings.max_tokens))
    messages = [{"role": m.role, "content": m.content} for m in data.messages]
    gen = await asyncio.to_thread(
        engine.generate, messages, temperature=data.temperature, max_tokens=max_tokens
    )
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex}",
        created=int(time.time()),
        model=settings.model_name,
        choices=(
            Choice(
                index=0,
                message=ChatMessage(role="assistant", content=gen.text),
                finish_reason=gen.finish_reason,
            ),
        ),
        usage=Usage(
            prompt_tokens=gen.prompt_tokens,
            completion_tokens=gen.completion_tokens,
            total_tokens=gen.prompt_tokens + gen.completion_tokens,
        ),
    )


@get("/v1/models", sync_to_thread=False)
def list_models(state: State) -> ModelList:
    """List the single served model (OpenAI /v1/models shape)."""
    settings = cast("Settings", state["settings"])
    return ModelList(data=(ModelCard(id=settings.model_name, created=int(time.time())),))


def _backend_error_handler(
    _request: Request[Any, Any, Any], exc: Exception
) -> Response[ErrorResponse]:
    """Render a BackendError as an OpenAI-style error body at its carried status."""
    err = cast("BackendError", exc)
    body = ErrorResponse(error=ErrorDetail(message=str(err), type=err.error_type))
    return Response(body, status_code=err.status, media_type="application/json")


def create_app(settings: Settings) -> Litestar:
    """Compile the model (blocking) and build the Litestar app around it."""
    engine = Engine.load(settings)
    return Litestar(
        route_handlers=[health, chat_completions, list_models],
        state=State({"settings": settings, "engine": engine}),
        openapi_config=None,
        exception_handlers={BackendError: _backend_error_handler},
    )
