# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Litestar app for the local model backend — OpenAI /v1 surface.

Two routes the verifier client and Open WebUI use — POST /v1/chat/completions
(one non-streaming completion) and GET /v1/models (the single served model) — plus /health.
The model compiles once at create_app time (Engine.load, blocking); each generation runs off
the event loop in a worker thread behind the engine lock (asyncio.to_thread — one pipeline,
one accelerator). This is the UNTRUSTED proposer: request parsing is lenient (OpenAI-compat via the
typed msgspec body, unknown fields tolerated), and the verifier re-decodes every reply
strictly (POC_SCOPE). Litestar bounds a request before body decode. A BackendError renders as an
OpenAI-style error body via the handler below; the verifier recognizes only the exact
``prompt_too_long`` shape as policy refusal and treats every other non-2xx as an upstream fault.
Streaming is out of scope for this unit. Litestar's OpenAPI auto-gen stays off — the backend
is consumed by a hardcoded client shape, not via a served document.
"""

import asyncio
import json
import time
import uuid
from typing import Any, cast

from litestar import Litestar, Request, Response, get, post
from litestar.datastructures import State
from litestar.status_codes import HTTP_200_OK

from capture.harness import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE, defence
from model_backend.engine import BackendError, Engine
from model_backend.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    ModelCard,
    ModelList,
    Usage,
)
from model_backend.settings import DATASET_SCHEMA_ID, FORMULA_SCHEMA_ID, Settings
from model_backend.verified_chart import VERIFIED_CHART_REPLY, is_verified_chart_summary

_SELECTOR_MESSAGE_COUNT = 2


@get("/health", sync_to_thread=False)
def health(state: State) -> HealthResponse:
    """Report backend liveness and loaded model/schema provenance.

    One digest per operator-pinned schema: an operator reading /health can tell which pinned
    document each proposer mode is actually guided by, and both go None together when
    structured_output is disabled.
    """
    settings = cast("Settings", state["settings"])
    engine = cast("Engine", state["engine"])
    return HealthResponse(
        model_name=settings.model_name,
        device=settings.device,
        structured_output=settings.structured_output,
        vplot_schema_sha256=engine.schema_sha256(DATASET_SCHEMA_ID),
        formula_schema_sha256=engine.schema_sha256(FORMULA_SCHEMA_ID),
    )


def _completion(
    settings: Settings,
    *,
    text: str,
    finish_reason: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> ChatCompletionResponse:
    """Wrap one reply in the OpenAI chat-completion envelope.

    Reports settings.model_name (the one served model), never the caller's requested `model` —
    echoing an arbitrary name would misreport which model produced the reply.
    """
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex}",
        created=int(time.time()),
        model=settings.model_name,
        choices=(
            Choice(
                index=0,
                message=ChatMessage(role="assistant", content=text),
                finish_reason=finish_reason,
            ),
        ),
        usage=Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


def _selector_prompt(messages: tuple[ChatMessage, ...]) -> str | None:
    """Recognize OWUI's two-message legacy selector, never an ordinary chat turn."""
    if (
        len(messages) != _SELECTOR_MESSAGE_COUNT
        or messages[0].role != "system"
        or "Available Tools:" not in messages[0].content
        or messages[1].role != "user"
    ):
        return None
    user = messages[1].content
    if user.startswith("Query: "):
        return user.rsplit("Query: ", 1)[-1]
    history, marker, _ = user.rpartition("\nQuery: ")
    if marker and history.startswith("History:\n") and history != "History:\n":
        return user.rsplit("Query: ", 1)[-1]
    return None


@post("/v1/chat/completions", status_code=HTTP_200_OK)
async def chat_completions(data: ChatCompletionRequest, state: State) -> ChatCompletionResponse:
    """Generate one non-streaming chat completion from the local model.

    Open WebUI's post-verified-chart summarize turn returns a fixed reply. Its legacy selector
    instead generates bare source from the capture request and wraps the de-fenced bytes as one
    tool call. All other turns preserve the original generation route and optional schema guidance.

    Ordinary requested max_tokens is clamped into [1, settings.max_tokens]: the ceiling guards the
    single accelerator/lock against a caller inducing an unbounded generation, and the floor keeps a
    zero/omitted value from starving the reply (an omitted max_tokens uses the ceiling).
    """
    settings = cast("Settings", state["settings"])
    engine = cast("Engine", state["engine"])
    if is_verified_chart_summary(data.messages):
        # The verifier already certified and embedded the chart, and OWUI re-prompts for a
        # human-facing closing line. Return one fixed sentence rather than let the 0.5B proposer
        # emit unrelated filler. The ONLY canned path — tool selection, the verifier's guided spec
        # generation, and ordinary chat all still run the model below.
        return _completion(
            settings,
            text=VERIFIED_CHART_REPLY,
            finish_reason="stop",
            prompt_tokens=sum(len(m.content.split()) for m in data.messages),
            completion_tokens=len(VERIFIED_CHART_REPLY.split()),
        )
    requested = data.max_tokens if data.max_tokens is not None else settings.max_tokens
    max_tokens = max(1, min(requested, settings.max_tokens))
    messages = [{"role": m.role, "content": m.content} for m in data.messages]
    selector = _selector_prompt(data.messages)
    if selector is not None:
        messages = [{"role": "user", "content": selector}]
        max_tokens = DEFAULT_MAX_TOKENS
    gen = await asyncio.to_thread(
        engine.generate,
        messages,
        temperature=DEFAULT_TEMPERATURE if selector is not None else data.temperature,
        max_tokens=max_tokens,
        guided_schema=None if selector is not None else data.guided_schema,
    )
    text = gen.text
    if selector is not None:
        _, program = defence(text)
        text = json.dumps(
            {"tool_calls": [{"name": "draw_figure", "parameters": {"program": program}}]}
        )
    return _completion(
        settings,
        text=text,
        finish_reason=gen.finish_reason,
        prompt_tokens=gen.prompt_tokens,
        completion_tokens=gen.completion_tokens,
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
        request_max_body_size=settings.max_body_bytes,
    )
