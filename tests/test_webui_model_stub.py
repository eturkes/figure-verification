# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Feedback loop for the hardware-free model-backend stub (M4.3c).

webui/ is a coverage-excluded harness, so these are a bench-style regression net (like
test_webui_client.py) rather than a 100%-branch gate. They pin the OpenAI /v1 wire shapes the M4.3e
smoke depends on (driven in-process through Litestar's TestClient, no socket binds) plus serve's url
parsing. The stub reuses model_backend.models, so a shape drift versus the live backend shows up
here without any accelerator.
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
    assert body["object"] == "list"
    assert len(body["data"]) == 1
    card = body["data"][0]
    assert card["id"] == "stub-model"
    assert card["object"] == "model"


# --- /v1/chat/completions -------------------------------------------------------------------
def test_chat_returns_stub_reply_in_openai_envelope() -> None:
    with TestClient(app=create_app("stub-model")) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hello there world"}]},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == "stub-model"
    choice = body["choices"][0]
    assert choice["message"]["role"] == "assistant"
    assert choice["message"]["content"] == _STUB_REPLY
    assert choice["finish_reason"] == "stop"
    # The synthetic word-count proxy: prompt = the 3 message words, completion = the reply words.
    usage = body["usage"]
    assert usage["prompt_tokens"] == 3
    assert usage["completion_tokens"] == len(_STUB_REPLY.split())
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
    assert usage["total_tokens"] >= 1


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


def test_serve_rejects_a_portless_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # model_backend_url passes Settings validation (scheme + host) but carries no port, so serve
    # must fail loud before reaching uvicorn rather than let it default to an unintended bind.
    def unreachable(*_args: object, **_kwargs: object) -> None:
        pytest.fail("uvicorn.run must not be reached for a port-less url")

    monkeypatch.setattr(uvicorn, "run", unreachable)
    with pytest.raises(ValueError, match="host and port"):
        serve(Settings(model_backend_url="http://127.0.0.1/v1"))
