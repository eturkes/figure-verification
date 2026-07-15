# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Hardware-free OpenAI /v1 stub — provisioning stand-in + scripted M4.5 E2E fixture.

The three-service smoke needs an OpenAI-compatible backend on :8001, but the live model_backend is
NPU-gated (OpenVINO resolves via PYTHONPATH, the intel-accel env sourced). This stub serves the two
routes OWUI touches -- GET /v1/models (the LOAD-BEARING one: OWUI enumerates it into /api/models)
and POST /v1/chat/completions -- with NO accelerator: it REUSES model_backend.models (msgspec
structs only, no openvino import), so OWUI sees the SAME /v1 wire SHAPE as the live backend (same
routes, status codes, object literals, and msgspec field order). Reply VALUES are synthetic and
prompt-classified (see _scripted_reply): exact legacy tool selection -> one known-good VPlot -> a
lean final summary. This makes tool execution, Location embed persistence, and browser rendering
deterministically testable after the NPU model's reliability is measured separately.

Not the trusted verifier and not even a model -- a scripted test fixture. It cannot support model
quality or tool-selection claims. Like the rest of webui/ it is coverage-excluded and unshipped,
importing only gate-venv deps (msgspec / litestar / uvicorn), so the gate runs it with no hardware.
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

_SELECTOR_MARKER = "Available Tools:"
_VPLOT_MARKER = "You are proposing a VPlot v0.1 chart specification."
_TOOL_CALL_REPLY = (
    '{"tool_calls":[{"name":"proposeSpec","parameters":'
    '{"user_request":"total revenue by month","dataset_name":"sales.csv"}}]}'
)
# Minified examples/good_specs/g01_total_revenue_by_month.json. Keep this runtime fixture CWD-
# independent; its test compares the decoded value to the tracked golden so a data/hash drift fails.
_VPLOT_REPLY = (
    '{"version":"vplot-0.1","dataset":{"name":"sales.csv","hash":'
    '"sha256:76356bebaa43bc76ee98fd6a1f1aa29cd7f127408fd43de87adcb7ed5df0478f"},'
    '"transform":[{"op":"group_by","keys":["month"]},{"op":"aggregate","measures":['
    '{"field":"revenue","fn":"sum","as":"total_revenue"}]},{"op":"sort","by":['
    '{"field":"month","order":"ascending"}]}],"mark":"bar","encoding":{"x":'
    '{"field":"month","type":"ordinal"},"y":{"field":"total_revenue",'
    '"type":"quantitative"}}}'
)
_FINAL_REPLY = "Figure Verifier confirmed the chart; all checks passed."


def _scripted_reply(messages: tuple[ChatMessage, ...]) -> str:
    """Classify the two system prompts in the E2E chain; otherwise return the final summary."""
    system = "\n".join(message.content for message in messages if message.role == "system")
    if _SELECTOR_MARKER in system:
        return _TOOL_CALL_REPLY
    if _VPLOT_MARKER in system:
        return _VPLOT_REPLY
    return _FINAL_REPLY


@get("/v1/models", sync_to_thread=False)
def list_models(state: State) -> ModelList:
    """List the single served model (OpenAI /v1/models shape) -- the smoke's load-bearing route."""
    model_id = cast("str", state["model_id"])
    return ModelList(data=(ModelCard(id=model_id, created=int(time.time())),))


@post("/v1/chat/completions", status_code=HTTP_200_OK, sync_to_thread=False)
def chat_completions(data: ChatCompletionRequest, state: State) -> ChatCompletionResponse:
    """Return the prompt-classified fixture reply in an OpenAI chat-completion envelope.

    Builds the same ChatCompletionResponse SHAPE as model_backend/app.py (Choice wraps a
    ChatMessage, every field required) so the wire schema and field order match, but the VALUES are
    synthetic: _scripted_reply selects one of three constants, finish_reason is always "stop" (the
    live backend may also emit "length"), and usage is a word-count proxy (prompt = summed message
    words, completion = reply words). Generation params (temperature / max_tokens) are ignored.
    """
    model_id = cast("str", state["model_id"])
    reply = _scripted_reply(data.messages)
    prompt_tokens = sum(len(m.content.split()) for m in data.messages)
    completion_tokens = len(reply.split())
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex}",
        created=int(time.time()),
        model=model_id,
        choices=(
            Choice(
                index=0,
                message=ChatMessage(role="assistant", content=reply),
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
