# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Feedback loop for the hardware-free model-backend stub (M4.3c).

webui/ is a coverage-excluded harness, so these are a bench-style regression net (like
test_webui_client.py) rather than a 100%-branch gate. They pin the OpenAI /v1 wire shapes the M4.3e
smoke depends on (driven in-process through Litestar's TestClient, no socket binds), the unknown-
field tolerance real OWUI chat traffic needs, and serve's url guard. The stub reuses
model_backend.models, so shape drift versus the live backend surfaces here without an accelerator.
"""

import pytest
import uvicorn
from litestar import Litestar
from litestar.testing import TestClient

from webui.model_stub import _STUB_REPLY, create_app, serve
from webui.settings import Settings


# --- /v1/models -----------------------------------------------------------------------------
def test_models_lists_only_the_configured_id() -> None:
    with TestClient(app=create_app("stub-model")) as client:
        response = client.get("/v1/models")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"data", "object"}
    assert body["object"] == "list"
    assert len(body["data"]) == 1
    # Pin the full card shape: a dropped/renamed field (created, owned_by) must fail the net.
    card = body["data"][0]
    assert set(card) == {"id", "created", "object", "owned_by"}
    assert card["id"] == "stub-model"
    assert card["object"] == "model"
    assert card["owned_by"] == "openvino"
    assert isinstance(card["created"], int)


# --- /v1/chat/completions -------------------------------------------------------------------
def test_chat_returns_stub_reply_in_openai_envelope() -> None:
    with TestClient(app=create_app("stub-model")) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hello there world"}]},
        )
    assert response.status_code == 200
    body = response.json()
    # Full envelope shape: exact top-level, choice, message, and usage key sets pin any drift.
    assert set(body) == {"id", "created", "model", "choices", "usage", "object"}
    assert body["object"] == "chat.completion"
    assert body["model"] == "stub-model"
    assert body["id"].startswith("chatcmpl-")
    assert isinstance(body["created"], int)
    assert len(body["choices"]) == 1
    choice = body["choices"][0]
    assert set(choice) == {"index", "message", "finish_reason"}
    assert choice["index"] == 0
    assert choice["finish_reason"] == "stop"
    assert set(choice["message"]) == {"role", "content"}
    assert choice["message"]["role"] == "assistant"
    assert choice["message"]["content"] == _STUB_REPLY
    # The synthetic word-count proxy: prompt = the 3 message words, completion = the reply words.
    usage = body["usage"]
    assert set(usage) == {"prompt_tokens", "completion_tokens", "total_tokens"}
    assert usage["prompt_tokens"] == 3
    assert usage["completion_tokens"] == len(_STUB_REPLY.split())
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
    assert usage["total_tokens"] >= 1


def test_chat_tolerates_owui_extra_fields_without_streaming() -> None:
    # The stub stands in for the live backend under real OWUI traffic, which sends fields beyond
    # {messages} -- model, stream, tools, tool_choice, top_p, ... ChatCompletionRequest does not
    # forbid unknown fields, so (like the live backend) the stub ignores them and returns a single
    # non-streaming JSON envelope, never an SSE stream. A future forbid_unknown_fields, or a dropped
    # struct field, would 400 real OWUI chats while the minimal-payload tests above stayed green.
    payload = {
        "model": "stub-model",
        "stream": True,
        "tools": [],
        "tool_choice": "auto",
        "top_p": 0.9,
        "messages": [{"role": "user", "content": "hello there world"}],
    }
    with TestClient(app=create_app("stub-model")) as client:
        response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == _STUB_REPLY


# --- serve ----------------------------------------------------------------------------------
def test_serve_binds_the_default_backend_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # Patch the SHARED uvicorn module (serve calls uvicorn.run on the same singleton); assert it
    # binds the host/port parsed from the default model_backend_url, one worker, a Litestar app.
    calls: dict[str, object] = {}

    def fake_run(app: object, *, host: str, port: int, workers: int) -> None:
        calls.update(app=app, host=host, port=port, workers=workers)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    serve(Settings())
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8001
    assert calls["workers"] == 1
    assert isinstance(calls["app"], Litestar)


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://127.0.0.1/v1",  # no port -> nothing to bind
        "http://127.0.0.1:bad/v1",  # non-numeric port: .port raises, caught before the guard
        "https://127.0.0.1:8001/v1",  # https: the stub serves plain HTTP only
        "http://127.0.0.1:8001/openai/v1",  # a path the stub does not mount (routes live under /v1)
        "http://127.0.0.1:8001",  # no /v1 path at all
    ],
    ids=["portless", "nonnumeric-port", "https", "wrong-path", "no-path"],
)
def test_serve_rejects_urls_the_stub_cannot_serve(
    bad_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each passes Settings validation (http(s) + host) but is not one the stub can bind and serve,
    # so serve must fail loud before reaching uvicorn -- else it surfaces as a TLS error or a 404
    # deep in the smoke rather than a clear launch-time config error.
    def unreachable(*_args: object, **_kwargs: object) -> None:
        pytest.fail("uvicorn.run must not be reached for an unservable url")

    monkeypatch.setattr(uvicorn, "run", unreachable)
    with pytest.raises(ValueError, match="bind and serve"):
        serve(Settings(model_backend_url=bad_url))
