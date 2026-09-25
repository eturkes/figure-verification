# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Hardware-free OpenAI /v1 stub — provisioning stand-in + scripted E2E fixture.

The three-service smoke needs an OpenAI-compatible backend on :8001, but the live model_backend is
dGPU-gated (torch CUDA + model weights, in its own .venv-model runtime). This stub serves the two
routes OWUI touches -- GET /v1/models (the LOAD-BEARING one: OWUI enumerates it into /api/models)
and POST /v1/chat/completions -- with NO accelerator: it REUSES model_backend.models (msgspec
structs only, no torch import), so OWUI sees the SAME /v1 wire SHAPE as the live backend (same
routes, status codes, object literals, and msgspec field order). Reply VALUES are synthetic and
prompt-classified (see _scripted_reply): the inlet-rendered simple banner prompt selects the
committed verified program, the rendered complicated prompt selects the refused program, and
other turns stay prose. This makes both outlet verdicts repeatable without measuring model quality.

Not the trusted verifier and not even a model -- a scripted test fixture. It cannot support model
quality or tool-selection claims. Like the rest of webui/ it is coverage-excluded and unshipped,
importing only gate-venv deps (msgspec / litestar / uvicorn), so the gate runs it with no hardware.
"""

import json
import time
import uuid
from typing import cast
from urllib.parse import urlparse

import msgspec
import uvicorn
from litestar import Litestar, get, post
from litestar.datastructures import State
from litestar.status_codes import HTTP_200_OK

from capture.corpus import CORPUS_ROOT, PromptSet, render_capture_prompt
from capture.harness import defence
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
_CAPTURE_RECORDS = CORPUS_ROOT / "captures" / "m10-design" / "records.ndjson"


def _rendered_sentinel(prompt_id: str) -> str:
    """Use the public task and the capture renderer, never a second authored template."""
    rows = msgspec.json.decode((CORPUS_ROOT / "sentinels.json").read_bytes(), type=PromptSet)
    prompt = next((row for row in rows.prompts if row.id == prompt_id), None)
    if prompt is None:
        msg = f"no public sentinel {prompt_id}"
        raise ValueError(msg)
    return render_capture_prompt(prompt)


def _captured_program(prompt_id: str) -> str:
    """Take the model-authored bytes from the committed run, de-fenced at the capture seam."""
    rows = (json.loads(line) for line in _CAPTURE_RECORDS.read_text().splitlines())
    captured = next((row for row in rows if row["prompt_id"] == prompt_id), None)
    if captured is None or not isinstance(captured["content"], str):
        msg = f"no captured program for {prompt_id}"
        raise ValueError(msg)
    fenced, source = defence(captured["content"])
    if not fenced or not source:
        msg = f"capture {prompt_id} has no de-fenced program"
        raise ValueError(msg)
    return source


_SIMPLE_PROMPT = _rendered_sentinel("sentinel-simple")
_COMPLICATED_PROMPT = _rendered_sentinel("sentinel-complicated")


def _tool_call_reply(program: str) -> str:
    return json.dumps(
        {"tool_calls": [{"name": "draw_figure", "parameters": {"program": program}}]},
        separators=(",", ":"),
    )


_TOOL_CALL_REPLY = _tool_call_reply(_captured_program("sentinel-simple"))
_COMPLICATED_TOOL_CALL_REPLY = _tool_call_reply(_captured_program("sentinel-complicated"))
# The filter, not the stub's prose, publishes the final verdict on either path.
_FINAL_REPLY = "Chart request completed."


def _selector_query(user: str, prompt: str) -> bool:
    # OWUI 0.10.2 middleware.py wraps the prompt in `Query:`, after `History:` on later turns.
    query = f"Query: {prompt}"
    return user == query or user.endswith(f"\n{query}")


def _scripted_reply(messages: tuple[ChatMessage, ...]) -> str:
    """Select each pinned call on the legacy selector turn; leave other requests as prose."""
    system = "\n".join(message.content for message in messages if message.role == "system")
    user = next((message.content for message in reversed(messages) if message.role == "user"), "")
    if _SELECTOR_MARKER in system:
        if _selector_query(user, _SIMPLE_PROMPT):
            return _TOOL_CALL_REPLY
        if _selector_query(user, _COMPLICATED_PROMPT):
            return _COMPLICATED_TOOL_CALL_REPLY
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

    Settings validates a canonical http(s) /v1 endpoint, but not that the stub can bind and serve
    it: the stub is plain HTTP and needs an explicit bind port, so https or an implicit port would
    otherwise surface as a TLS/bind error deep in the smoke. Fail loud here instead. Reading .port
    defensively keeps this boundary sound even for a direct-construction type escape. One worker
    matches model_backend's serve.
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
