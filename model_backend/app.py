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
import re
import time
import uuid
from typing import Any, Final, cast

from litestar import Litestar, Request, Response, get, post
from litestar.datastructures import State
from litestar.status_codes import HTTP_200_OK

from model_backend.adapter import ADAPTER_MAX_TOKENS, ADAPTER_TEMPERATURE, defence
from model_backend.engine import BackendError, Engine, GenResult
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
from model_backend.settings import Settings

_SELECTOR_MESSAGE_COUNT = 2
# OWUI's selector history (`utils/middleware.py` `get_tools_function_calling_payload`): up to four
# earlier messages, each `f'{role.upper()}: """{content}"""'`, joined by newlines. A content holding
# `"""` + a newline + another entry's opening splits there; the model then reads a shifted turn.
_HISTORY_ENTRY: Final = re.compile(r'([A-Z]+): """(.*?)"""(?:\n(?=[A-Z]+: """)|\Z)', re.DOTALL)
_HISTORY_ROLES: Final = {"USER": "user", "ASSISTANT": "assistant"}


@get("/health", sync_to_thread=False)
def health(state: State) -> HealthResponse:
    """Report backend liveness and the loaded model."""
    settings = cast("Settings", state["settings"])
    return HealthResponse(model_name=settings.model_name, device=settings.device)


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


def _history_turns(history: str) -> list[dict[str, str]]:
    """The selector's `ROLE: \"\"\"content\"\"\"` lines as chat turns, oldest first.

    USER + ASSISTANT entries become turns, any other role is dropped, and text that does not
    decompose into entries yields none: the query alone, the pre-history reading.
    """
    turns: list[dict[str, str]] = []
    position = 0
    while position < len(history):
        entry = _HISTORY_ENTRY.match(history, position)
        if entry is None:
            return []
        if entry[1] in _HISTORY_ROLES:
            turns.append({"role": _HISTORY_ROLES[entry[1]], "content": entry[2]})
        position = entry.end()
    return turns


def _selector_prompt(messages: tuple[ChatMessage, ...]) -> tuple[list[dict[str, str]], str] | None:
    """Recognize OWUI's two-message legacy selector, never an ordinary chat turn: its history
    turns + the final query."""
    if (
        len(messages) != _SELECTOR_MESSAGE_COUNT
        or messages[0].role != "system"
        or "Available Tools:" not in messages[0].content
        or messages[1].role != "user"
    ):
        return None
    user = messages[1].content
    if user.startswith("Query: "):
        return [], user.rsplit("Query: ", 1)[-1]
    history, marker, _ = user.rpartition("\nQuery: ")
    if marker and history.startswith("History:\n") and history != "History:\n":
        return _history_turns(history.removeprefix("History:\n")), user.rsplit("Query: ", 1)[-1]
    return None


async def _selector_generation(
    engine: Engine, turns: list[dict[str, str]], query: str
) -> GenResult:
    """Generate the program from the conversation + the query at the capture parameters.

    A follow-up ("make the bars red") names no chart, so the model needs the earlier turns; a
    prompt past the token ceiling drops the oldest turn until it fits, down to the query alone.
    """
    while True:
        try:
            return await asyncio.to_thread(
                engine.generate,
                [*turns, {"role": "user", "content": query}],
                temperature=ADAPTER_TEMPERATURE,
                max_tokens=ADAPTER_MAX_TOKENS,
            )
        except BackendError as error:
            if error.error_type != "prompt_too_long" or not turns:
                raise
            turns = turns[1:]


@post("/v1/chat/completions", status_code=HTTP_200_OK)
async def chat_completions(data: ChatCompletionRequest, state: State) -> ChatCompletionResponse:
    """Generate one non-streaming chat completion from the local model.

    Open WebUI's legacy selector generates bare source from its history + the demo inlet's request
    and wraps the de-fenced bytes as one `draw_figure` tool call. All other turns run the model as
    asked.

    Ordinary requested max_tokens is clamped into [1, settings.max_tokens]: the ceiling guards the
    single accelerator/lock against a caller inducing an unbounded generation, and the floor keeps a
    zero/omitted value from starving the reply (an omitted max_tokens uses the ceiling).
    """
    settings = cast("Settings", state["settings"])
    engine = cast("Engine", state["engine"])
    selector = _selector_prompt(data.messages)
    if selector is not None:
        gen = await _selector_generation(engine, *selector)
        _, program = defence(gen.text)
        text = json.dumps(
            {"tool_calls": [{"name": "draw_figure", "parameters": {"program": program}}]}
        )
    else:
        requested = data.max_tokens if data.max_tokens is not None else settings.max_tokens
        gen = await asyncio.to_thread(
            engine.generate,
            [{"role": m.role, "content": m.content} for m in data.messages],
            temperature=data.temperature,
            max_tokens=max(1, min(requested, settings.max_tokens)),
        )
        text = gen.text
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
