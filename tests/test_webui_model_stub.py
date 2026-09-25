# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Feedback loop for the hardware-free model-backend stub.

webui/ is a coverage-excluded harness, so these are a bench-style regression net (like
test_webui_client.py) rather than a 100%-branch gate. They pin the OpenAI /v1 wire shapes the
smoke depends on (driven in-process through Litestar's TestClient, no socket binds), the unknown-
field tolerance real OWUI chat traffic needs, and serve's url guard. The stub reuses
model_backend.models, so shape drift versus the live backend surfaces here without an accelerator.
"""

import json

import msgspec
import pytest
import uvicorn
from litestar import Litestar
from litestar.testing import TestClient

from capture.corpus import CORPUS_ROOT, PromptSet, render_capture_prompt
from webui.model_stub import (
    _COMPLICATED_PROMPT as _STUB_COMPLICATED_PROMPT,
)
from webui.model_stub import (
    _FINAL_REPLY,
    _SELECTOR_MARKER,
    _TOOL_CALL_REPLY,
    create_app,
    serve,
)
from webui.model_stub import (
    _SIMPLE_PROMPT as _STUB_SIMPLE_PROMPT,
)
from webui.settings import Settings

_PUBLIC_SENTINELS = {
    row.id: row
    for row in msgspec.json.decode(
        (CORPUS_ROOT / "sentinels.json").read_bytes(), type=PromptSet
    ).prompts
}
_SIMPLE_PROMPT = render_capture_prompt(_PUBLIC_SENTINELS["sentinel-simple"])
_COMPLICATED_PROMPT = render_capture_prompt(_PUBLIC_SENTINELS["sentinel-complicated"])
_HISTORY_PREFIX = 'History:\nUSER: """Earlier request"""\nASSISTANT: """Earlier reply"""\nQuery: '


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
    assert card["owned_by"] == "local"
    assert isinstance(card["created"], int)


# --- /v1/chat/completions -------------------------------------------------------------------
def test_chat_returns_final_reply_in_openai_envelope() -> None:
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
    assert choice["message"]["content"] == _FINAL_REPLY
    # The synthetic word-count proxy: prompt = the 3 message words, completion = the reply words.
    usage = body["usage"]
    assert set(usage) == {"prompt_tokens", "completion_tokens", "total_tokens"}
    assert usage["prompt_tokens"] == 3
    assert usage["completion_tokens"] == len(_FINAL_REPLY.split())
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
    assert body["choices"][0]["message"]["content"] == _FINAL_REPLY


@pytest.mark.parametrize(
    ("selector", "prompt", "kind"),
    [
        (_SELECTOR_MARKER, f"Query: {_SIMPLE_PROMPT}", "simple"),
        (
            _SELECTOR_MARKER,
            f"{_HISTORY_PREFIX}{_SIMPLE_PROMPT}",
            "simple",
        ),
        (_SELECTOR_MARKER, f"Query: {_COMPLICATED_PROMPT}", "complicated"),
        (
            _SELECTOR_MARKER,
            f"{_HISTORY_PREFIX}{_COMPLICATED_PROMPT}",
            "complicated",
        ),
        (_SELECTOR_MARKER, _SIMPLE_PROMPT, "prose"),
        (_SELECTOR_MARKER, _COMPLICATED_PROMPT, "prose"),
        (_SELECTOR_MARKER, f"Query: {_PUBLIC_SENTINELS['sentinel-simple'].prompt}", "prose"),
        (_SELECTOR_MARKER, f"Query: {_PUBLIC_SENTINELS['sentinel-complicated'].prompt}", "prose"),
        (_SELECTOR_MARKER, "Query: other request", "prose"),
        (_SELECTOR_MARKER, f"Query: {_SIMPLE_PROMPT} please", "prose"),
        (_SELECTOR_MARKER, f"Query: {_COMPLICATED_PROMPT} please", "prose"),
        ("ordinary chat", f"Query: {_SIMPLE_PROMPT}", "prose"),
        ("ordinary chat", f"Query: {_COMPLICATED_PROMPT}", "prose"),
        (_SELECTOR_MARKER, "other request", "prose"),
    ],
    ids=[
        "simple-fresh",
        "simple-history",
        "complicated-fresh",
        "complicated-history",
        "simple-bare",
        "complicated-bare",
        "simple-unrendered",
        "complicated-unrendered",
        "other-query",
        "simple-suffix",
        "complicated-suffix",
        "simple-non-selector",
        "complicated-non-selector",
        "other-prose",
    ],
)
def test_chat_selects_scripted_e2e_reply(selector: str, prompt: str, kind: str) -> None:
    # OWUI 0.10.2 utils/middleware.py:1102-1124 sends one user message with these literal shapes.
    with TestClient(app=create_app("stub-model")) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [
                    {"role": "system", "content": selector},
                    {"role": "user", "content": prompt},
                ]
            },
        )
    assert response.status_code == 200
    body = response.json()
    reply = body["choices"][0]["message"]["content"]
    if kind == "simple":
        assert reply == _TOOL_CALL_REPLY
    elif kind == "complicated":
        calls = json.loads(reply)["tool_calls"]
        assert len(calls) == 1
        assert calls[0]["name"] == "draw_figure"
        assert "plt.subplots(2, 2" in calls[0]["parameters"]["program"]
    else:
        assert reply == _FINAL_REPLY
    assert body["usage"]["completion_tokens"] == len(reply.split())


def test_chat_final_turn_does_not_repeat_tool_call() -> None:
    # A model turn after legacy tool execution is NOT the selector's `Query: ` message.
    with TestClient(app=create_app("stub-model")) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": [
                    {"role": "system", "content": _SELECTOR_MARKER},
                    {"role": "assistant", "content": _TOOL_CALL_REPLY},
                    {"role": "user", "content": _SIMPLE_PROMPT},
                ]
            },
        )
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == _FINAL_REPLY


def test_scripted_tool_call_is_exact_draw_figure_request() -> None:
    assert _STUB_SIMPLE_PROMPT == _SIMPLE_PROMPT
    assert _STUB_COMPLICATED_PROMPT == _COMPLICATED_PROMPT
    reply = json.loads(_TOOL_CALL_REPLY)
    assert set(reply) == {"tool_calls"}
    assert len(reply["tool_calls"]) == 1
    call = reply["tool_calls"][0]
    assert call["name"] == "draw_figure"
    assert set(call["parameters"]) == {"program"}
    program = call["parameters"]["program"]
    assert isinstance(program, str)
    assert program.startswith("import pandas as pd\nimport matplotlib.pyplot as plt\n")
    assert "pd.read_csv('/mnt/uploads/sales.csv')" in program
    assert "df.groupby('region')['revenue'].sum()" in program
    assert program.endswith("plt.show()\n")


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
        "https://127.0.0.1:8001/v1",  # https: the stub serves plain HTTP only
    ],
    ids=["portless", "https"],
)
def test_serve_rejects_urls_the_stub_cannot_serve(
    bad_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each passes Settings' canonical /v1 endpoint validation but is not one the stub can bind and
    # serve, so serve must fail loud before reaching uvicorn -- else it surfaces as a TLS error or
    # an implicit-port bind deep in the smoke rather than a clear launch-time config error.
    def unreachable(*_args: object, **_kwargs: object) -> None:
        pytest.fail("uvicorn.run must not be reached for an unservable url")

    monkeypatch.setattr(uvicorn, "run", unreachable)
    with pytest.raises(ValueError, match="bind and serve"):
        serve(Settings(model_backend_url=bad_url))
