# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Feedback loop for the Open WebUI provisioning client + smoke (M4.3b).

webui/ is a coverage-excluded harness, so these are a bench-style regression net (like
test_webui_settings.py) rather than a 100%-branch gate. The OWUI request shapes are the reviewed
0.10.2 contracts summarized in memory M4, not re-probed; here they are pinned against an
httpx.MockTransport (no socket binds, every branch deterministic), plus a structural fake for the
bootstrap orchestration. Locked:

- wait_ready: returns on the first 200, retries through transport errors, raises on timeout;
- authenticate: signup-200 stores the JWT; a non-200 signup falls back to signin; both non-200 or an
  empty/malformed token response raises; signup/signin transport failures normalize to the client
  error boundary; the stored token rides authed reads as a Bearer header;
- model_ids / tool_server_ids / model_tool_ids: the served-model envelope, BARE tool array, and
  workspace-model `meta.toolIds` readbacks; server filtering, Bearer wiring, 404-as-no-config, and
  every other non-200/transport/malformed response failing loudly;
- ensure_global_filter / ensure_model_tool: filter create/update/toggle convergence plus
  model-config create-or-merge, exact payload/paths, operator-key preservation, final verification,
  and idempotent no-write behavior;
- run_persisted_chat: exact create/completion/poll wire shapes, pending/done extraction, optional
  embed, and transport/status/JSON/timeout/malformed-output failures;
- smoke / run_bootstrap: membership + ok truth table, exact filter source/metadata,
  wait->auth->converge->smoke order, failure barrier, and rerun idempotency (closed signup falls
  back to signin over a stateful transport, and the existing filter updates).
"""

import itertools
import json
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import httpx
import pytest

from webui.bootstrap import SmokeResult, run_bootstrap, smoke
from webui.client import PersistedChatResult, WebUIClient, WebUIProvisionError
from webui.enforcement_filter import (
    FILTER_DESCRIPTION,
    FILTER_ID,
    FILTER_NAME,
    function_source,
)
from webui.settings import Settings

_Handler = Callable[[httpx.Request], httpx.Response]

_FUNCTION_ID = "verified_plot_guard"
_FUNCTION_NAME = "Verified Plot Guard"
_FUNCTION_CONTENT = "class Filter:\n    pass\n"
_FUNCTION_DESCRIPTION = "Routes direct charts through Figure Verifier."
_FUNCTION_PATH = f"/api/v1/functions/id/{_FUNCTION_ID}"
_FUNCTION_PAYLOAD: dict[str, object] = {
    "id": _FUNCTION_ID,
    "name": _FUNCTION_NAME,
    "content": _FUNCTION_CONTENT,
    "meta": {"description": _FUNCTION_DESCRIPTION},
}


_CHAT_ID = "00000000-0000-4000-8000-000000000001"
_CHAT_PROMPT = "Create a verified chart."
_CHAT_TEXT = "Figure Verifier confirmed the chart; all checks passed."
_CHAT_URL = "http://127.0.0.1:8000/chart/plot-1"


def _chat_ack() -> httpx.Response:
    """One valid background-completion acknowledgement."""
    return httpx.Response(
        200,
        json={"status": True, "task_ids": ["task-1"], "chat_id": _CHAT_ID},
    )


def _chat_readback(
    assistant_id: str,
    *,
    include_assistant: bool = True,
    done: bool = True,
    embeds: tuple[str, ...] = (_CHAT_URL,),
    malformed_output: bool = False,
) -> httpx.Response:
    """One loose persisted-chat response with a controllable assistant entry."""
    messages: dict[str, object] = {}
    if include_assistant:
        output: list[object] = []
        if not malformed_output:
            output = [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": _CHAT_TEXT}],
                }
            ]
        messages[assistant_id] = {
            "id": assistant_id,
            "role": "assistant",
            "content": "",
            "done": done,
            "embeds": list(embeds),
            "output": output,
        }
    return httpx.Response(200, json={"chat": {"history": {"messages": messages}}})


@contextmanager
def _webui_client(handler: _Handler, settings: Settings | None = None) -> Iterator[WebUIClient]:
    """A WebUIClient over a MockTransport running `handler` (no real socket)."""
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://webui.test") as http:
        yield WebUIClient(http, settings if settings is not None else Settings())


def _function_state(
    *,
    active: bool = False,
    global_: bool = False,
    function_id: str = _FUNCTION_ID,
    function_type: str = "filter",
    content: str | None = _FUNCTION_CONTENT,
) -> dict[str, object]:
    """Minimal loose FunctionResponse shape consumed by WebUIClient."""
    state: dict[str, object] = {
        "id": function_id,
        "type": function_type,
        "is_active": active,
        "is_global": global_,
    }
    if content is not None:
        state["content"] = content
    return state


def _model_config(model_id: str, *tool_ids: str) -> dict[str, object]:
    """Minimal loose workspace-model config shape consumed by WebUIClient."""
    return {
        "id": model_id,
        "base_model_id": None,
        "name": model_id,
        "params": {},
        "meta": {"toolIds": list(tool_ids)},
        "is_active": True,
    }


def _ensure_global_filter(client: WebUIClient) -> None:
    """Call the unit surface with one canonical payload."""
    client.ensure_global_filter(
        function_id=_FUNCTION_ID,
        name=_FUNCTION_NAME,
        content=_FUNCTION_CONTENT,
        description=_FUNCTION_DESCRIPTION,
    )


class _FakeClient:
    """A structural _Provisioner: canned readbacks + a call log, so the bootstrap orchestration is
    tested without any HTTP."""

    def __init__(
        self,
        model_ids: list[str],
        tool_server_ids: list[str],
        model_tool_ids: list[str] | None = None,
        *,
        fail_filter: bool = False,
    ) -> None:
        self._model_ids = model_ids
        self._tool_server_ids = tool_server_ids
        self._model_tool_ids = (
            list(model_tool_ids) if model_tool_ids is not None else list(tool_server_ids)
        )
        self._fail_filter = fail_filter
        self.calls: list[str] = []
        self.filter_calls: list[tuple[str, str, str, str]] = []
        self.model_tool_calls: list[tuple[str, str]] = []

    def wait_ready(self) -> None:
        self.calls.append("wait_ready")

    def authenticate(self) -> str:
        self.calls.append("authenticate")
        return "jwt"

    def ensure_global_filter(
        self,
        *,
        function_id: str,
        name: str,
        content: str,
        description: str,
    ) -> None:
        self.calls.append("ensure_global_filter")
        self.filter_calls.append((function_id, name, content, description))
        if self._fail_filter:
            message = "filter convergence failed"
            raise WebUIProvisionError(message)

    def ensure_model_tool(self, *, model_id: str, tool_id: str) -> None:
        self.calls.append("ensure_model_tool")
        self.model_tool_calls.append((model_id, tool_id))

    def model_ids(self) -> list[str]:
        self.calls.append("model_ids")
        return list(self._model_ids)

    def tool_server_ids(self) -> list[str]:
        self.calls.append("tool_server_ids")
        return list(self._tool_server_ids)

    def model_tool_ids(self, model_id: str) -> list[str]:
        del model_id
        self.calls.append("model_tool_ids")
        return list(self._model_tool_ids)


class _BootstrapTransport:
    """Stateful MockTransport handler for one or more full bootstrap runs."""

    def __init__(self, settings: Settings, *, close_signup_after_first: bool) -> None:
        self.settings = settings
        self.close_signup_after_first = close_signup_after_first
        self.signups = 0
        self.filter_writes = {"create": 0, "update": 0}
        self.model_writes = {"create": 0, "update": 0}
        self.filter_content = function_source()
        self.filter_state: dict[str, object] | None = None
        self.model_config: dict[str, object] | None = None
        self.tool_id = f"server:{settings.tool_server_id}"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/ready":
            response = httpx.Response(200)
        elif path == "/api/v1/auths/signup":
            response = self._signup()
        elif path == "/api/v1/auths/signin":
            response = httpx.Response(200, json={"token": "jwt-signin"})
        else:
            assert request.headers["authorization"].startswith("Bearer jwt-")
            if path.startswith("/api/v1/functions"):
                response = self._handle_filter(request)
            elif path in {
                "/api/v1/models/model",
                "/api/v1/models/create",
                "/api/v1/models/model/update",
            }:
                response = self._handle_model(request)
            elif path == "/api/models":
                response = httpx.Response(
                    200,
                    json={"data": [{"id": self.settings.model_id}]},
                )
            elif path == "/api/v1/tools/":
                response = httpx.Response(200, json=[{"id": self.tool_id}])
            else:
                pytest.fail(f"unexpected path {path}")
        return response

    def _signup(self) -> httpx.Response:
        self.signups += 1
        if self.close_signup_after_first and self.signups > 1:
            return httpx.Response(403, json={"detail": "signup closed"})
        return httpx.Response(200, json={"token": "jwt-signup"})

    def _handle_filter(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == _FUNCTION_PATH and request.method == "GET":
            if self.filter_state is None:
                return httpx.Response(401, json={"detail": "Function not found"})
            return httpx.Response(200, json=self.filter_state)
        if path == "/api/v1/functions/create":
            self.filter_writes["create"] += 1
            assert json.loads(request.content) == {
                "id": FILTER_ID,
                "name": FILTER_NAME,
                "content": self.filter_content,
                "meta": {"description": FILTER_DESCRIPTION},
            }
            self.filter_state = _function_state(content=None)
        elif path == f"{_FUNCTION_PATH}/update":
            self.filter_writes["update"] += 1
            self.filter_state = _function_state(
                active=True,
                global_=True,
                content=self.filter_content,
            )
        elif path == f"{_FUNCTION_PATH}/toggle":
            self.filter_state = _function_state(active=True, content=self.filter_content)
        elif path == f"{_FUNCTION_PATH}/toggle/global":
            self.filter_state = _function_state(
                active=True,
                global_=True,
                content=self.filter_content,
            )
        else:
            pytest.fail(f"unexpected filter path {path}")
        return httpx.Response(200, json=self.filter_state)

    def _handle_model(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.url.params.get("id") == self.settings.model_id
            if self.model_config is None:
                return httpx.Response(404, json={"detail": "Model not found"})
            return httpx.Response(200, json=self.model_config)
        payload: dict[str, object] = json.loads(request.content)
        if request.url.path == "/api/v1/models/create":
            self.model_writes["create"] += 1
            assert payload == {
                "id": self.settings.model_id,
                "base_model_id": None,
                "name": self.settings.model_id,
                "meta": {"toolIds": [self.tool_id]},
                "params": {},
                "is_active": True,
            }
        elif request.url.path == "/api/v1/models/model/update":
            self.model_writes["update"] += 1
        else:
            pytest.fail(f"unexpected model path {request.url.path}")
        self.model_config = payload
        return httpx.Response(200, json=self.model_config)


# --- wait_ready -----------------------------------------------------------------------------
def test_wait_ready_returns_on_first_200() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    with _webui_client(handler) as client:
        client.wait_ready()  # returns without raising


def test_wait_ready_retries_through_transport_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pre-bind polls raise httpx.ConnectError (swallowed as still-booting); the third poll succeeds.
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    attempts = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            msg = "connection refused"
            raise httpx.ConnectError(msg)
        return httpx.Response(200)

    with _webui_client(handler) as client:
        client.wait_ready()
    assert attempts["n"] == 3


def test_wait_ready_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    # A never-ready /ready (503). A fake monotonic advances 1s per call so the 2s deadline trips on
    # the second post-poll check -- one retry (sleep) then raise, no real waiting.
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(time, "monotonic", itertools.count(0.0, 1.0).__next__)
    polls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        polls["n"] += 1
        return httpx.Response(503)

    with (
        _webui_client(handler, Settings(ready_timeout=2.0)) as client,
        pytest.raises(WebUIProvisionError, match="not ready"),
    ):
        client.wait_ready()
    assert polls["n"] == 2  # polled, retried once, then timed out


# --- authenticate ---------------------------------------------------------------------------
def test_authenticate_signup_200_stores_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/auths/signup"
        return httpx.Response(200, json={"token": "jwt-signup"})

    with _webui_client(handler) as client:
        assert client.authenticate() == "jwt-signup"
        assert client._token == "jwt-signup"  # noqa: S105 (test literal, not a real secret)


def test_authenticate_falls_back_to_signin_on_non_200_signup() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auths/signup":
            return httpx.Response(403, json={"detail": "signup closed"})
        if request.url.path == "/api/v1/auths/signin":
            return httpx.Response(200, json={"token": "jwt-signin"})
        pytest.fail(f"unexpected path {request.url.path}")

    with _webui_client(handler) as client:
        assert client.authenticate() == "jwt-signin"


def test_authenticate_raises_reporting_both_signup_and_signin_status() -> None:
    # Distinct statuses (signup 500, signin 400) pin that the error reports BOTH, not just signin's.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auths/signup":
            return httpx.Response(500, json={"detail": "boom"})
        return httpx.Response(400, json={"detail": "nope"})

    with (
        _webui_client(handler) as client,
        pytest.raises(WebUIProvisionError, match="signup HTTP 500, signin HTTP 400"),
    ):
        client.authenticate()


def test_authenticate_raises_on_empty_token() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})  # token defaults to "" -> fail closed

    with (
        _webui_client(handler) as client,
        pytest.raises(WebUIProvisionError, match="empty token"),
    ):
        client.authenticate()


@pytest.mark.parametrize(
    "body",
    [b"not JSON", b'{"token":"\xff"}'],
    ids=["malformed-json", "invalid-utf8"],
)
def test_authenticate_normalizes_malformed_response(body: bytes) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    with (
        _webui_client(handler) as client,
        pytest.raises(WebUIProvisionError, match="authentication returned an invalid response"),
    ):
        client.authenticate()


@pytest.mark.parametrize("phase", ["signup", "signin"])
def test_authenticate_normalizes_transport_error(phase: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if phase == "signin" and request.url.path.endswith("/signup"):
            return httpx.Response(403)
        msg = "connection reset"
        raise httpx.ConnectError(msg)

    expected_path = "/api/v1/auths/signup" if phase == "signup" else "/api/v1/auths/signin"
    with (
        _webui_client(handler) as client,
        pytest.raises(WebUIProvisionError, match=rf"POST {expected_path} failed: connection reset"),
    ):
        client.authenticate()


# --- authed readbacks -----------------------------------------------------------------------
def test_model_ids_parses_data_envelope_with_bearer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer tok"
        return httpx.Response(200, json={"data": [{"id": "m1"}, {"id": "m2"}]})

    with _webui_client(handler) as client:
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        assert client.model_ids() == ["m1", "m2"]


def test_tool_server_ids_parses_bare_array_and_filters_non_server() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer tok"
        return httpx.Response(
            200,
            json=[
                {"id": "server:verifier", "name": "Figure Verifier"},
                {"id": "server:other"},
                {"id": "python-function-tool"},  # not a server: dropped
            ],
        )

    with _webui_client(handler) as client:
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        assert client.tool_server_ids() == ["server:verifier", "server:other"]


def test_model_tool_ids_returns_workspace_model_tools_with_bearer() -> None:
    model_id = "model/id?variant=1"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auths/signup":
            return httpx.Response(200, json={"token": "tok"})
        assert request.headers["authorization"] == "Bearer tok"
        assert request.url.path == "/api/v1/models/model"
        assert request.url.params.get("id") == model_id
        return httpx.Response(
            200,
            json={
                "id": model_id,
                "base_model_id": None,
                "name": model_id,
                "params": {},
                "meta": {"toolIds": ["server:verifier", 7, "server:other"]},
                "is_active": True,
            },
        )

    with _webui_client(handler) as client:
        client.authenticate()
        assert client.model_tool_ids(model_id) == ["server:verifier", "server:other"]


def test_model_tool_ids_returns_empty_for_missing_workspace_config() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auths/signup":
            return httpx.Response(200, json={"token": "tok"})
        assert request.headers["authorization"] == "Bearer tok"
        return httpx.Response(404, json={"detail": "Model not found"})

    with _webui_client(handler) as client:
        client.authenticate()
        assert client.model_tool_ids("model") == []


def test_model_tool_ids_raises_loud_on_non_404_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auths/signup":
            return httpx.Response(200, json={"token": "tok"})
        return httpx.Response(500)

    with _webui_client(handler) as client:
        client.authenticate()
        with pytest.raises(WebUIProvisionError, match="HTTP 500"):
            client.model_tool_ids("model")


def test_model_tool_ids_requires_authentication() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("no request should be sent before authenticate")

    with (
        _webui_client(handler) as client,
        pytest.raises(WebUIProvisionError, match="authenticate"),
    ):
        client.model_tool_ids("model")


@pytest.mark.parametrize(
    "body",
    [b"not JSON", b'{"meta":{"toolIds":["\xff"]}}'],
    ids=["malformed-json", "invalid-utf8"],
)
def test_model_tool_ids_rejects_invalid_json(body: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auths/signup":
            return httpx.Response(200, json={"token": "tok"})
        return httpx.Response(200, content=body)

    with _webui_client(handler) as client:
        client.authenticate()
        with pytest.raises(WebUIProvisionError, match="invalid model config"):
            client.model_tool_ids("model")


# --- persisted chat -------------------------------------------------------------------------
def test_run_persisted_chat_sends_exact_wire_and_returns_result() -> None:
    settings = Settings(model_id="model-test")
    calls: list[tuple[str, str]] = []
    completion_body: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer tok"
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/v1/chats/new":
            assert request.method == "POST"
            assert json.loads(request.content) == {
                "chat": {
                    "models": [settings.model_id],
                    "messages": [],
                    "history": {"messages": {}, "currentId": None},
                }
            }
            return httpx.Response(200, json={"id": _CHAT_ID, "title": "New Chat"})
        if request.url.path == "/api/chat/completions":
            assert request.method == "POST"
            body: dict[str, object] = json.loads(request.content)
            completion_body.update(body)
            assert set(body) == {
                "model",
                "stream",
                "tool_ids",
                "chat_id",
                "session_id",
                "id",
                "parent_id",
                "messages",
                "user_message",
            }
            assert body["model"] == settings.model_id
            assert body["stream"] is False
            assert body["tool_ids"] == ["server:verifier"]
            assert body["chat_id"] == _CHAT_ID
            assert body["parent_id"] is None
            assert body["messages"] == [{"role": "user", "content": _CHAT_PROMPT}]
            session_id = body["session_id"]
            assistant_id = body["id"]
            user_message = body["user_message"]
            assert isinstance(session_id, str)
            assert isinstance(assistant_id, str)
            assert isinstance(user_message, dict)
            user_id = user_message["id"]
            assert isinstance(user_id, str)
            for generated_id in (session_id, assistant_id, user_id):
                assert uuid.UUID(generated_id).version == 4
            assert len({session_id, assistant_id, user_id}) == 3
            assert set(user_message) == {
                "id",
                "role",
                "content",
                "timestamp",
                "parentId",
                "childrenIds",
            }
            assert user_message["role"] == "user"
            assert user_message["content"] == _CHAT_PROMPT
            assert type(user_message["timestamp"]) is int
            assert user_message["parentId"] is None
            assert user_message["childrenIds"] == [assistant_id]
            return _chat_ack()

        assert request.method == "GET"
        assert request.url.path == f"/api/v1/chats/{_CHAT_ID}"
        assistant_id = completion_body["id"]
        assert isinstance(assistant_id, str)
        return _chat_readback(assistant_id)

    with _webui_client(handler, settings) as client:
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        result = client.run_persisted_chat(_CHAT_PROMPT)

    assert result == PersistedChatResult(final_text=_CHAT_TEXT, chart_url=_CHAT_URL)
    assert calls == [
        ("POST", "/api/v1/chats/new"),
        ("POST", "/api/chat/completions"),
        ("GET", f"/api/v1/chats/{_CHAT_ID}"),
    ]


def test_run_persisted_chat_polls_missing_assistant_until_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(time, "sleep", record_sleep)
    assistant_id = ""
    polls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal assistant_id, polls
        if request.url.path == "/api/v1/chats/new":
            return httpx.Response(200, json={"id": _CHAT_ID})
        if request.url.path == "/api/chat/completions":
            body: dict[str, object] = json.loads(request.content)
            value = body["id"]
            assert isinstance(value, str)
            assistant_id = value
            return _chat_ack()
        assert request.url.path == f"/api/v1/chats/{_CHAT_ID}"
        polls += 1
        if polls == 1:
            return _chat_readback(assistant_id, include_assistant=False)
        return _chat_readback(assistant_id)

    with _webui_client(handler) as client:
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        result = client.run_persisted_chat(_CHAT_PROMPT)

    assert result.final_text == _CHAT_TEXT
    assert polls == 2
    assert sleeps == [1.0]


def test_run_persisted_chat_allows_missing_embed() -> None:
    assistant_id = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal assistant_id
        if request.url.path == "/api/v1/chats/new":
            return httpx.Response(200, json={"id": _CHAT_ID})
        if request.url.path == "/api/chat/completions":
            body: dict[str, object] = json.loads(request.content)
            value = body["id"]
            assert isinstance(value, str)
            assistant_id = value
            return _chat_ack()
        return _chat_readback(assistant_id, embeds=())

    with _webui_client(handler) as client:
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        result = client.run_persisted_chat(_CHAT_PROMPT)

    assert result == PersistedChatResult(final_text=_CHAT_TEXT, chart_url=None)


@pytest.mark.parametrize("fault_phase", ["create", "completion", "poll"])
def test_run_persisted_chat_normalizes_transport_fault(fault_phase: str) -> None:
    assistant_id = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal assistant_id
        if request.url.path == "/api/v1/chats/new":
            phase = "create"
            response = httpx.Response(200, json={"id": _CHAT_ID})
        elif request.url.path == "/api/chat/completions":
            phase = "completion"
            body: dict[str, object] = json.loads(request.content)
            value = body["id"]
            assert isinstance(value, str)
            assistant_id = value
            response = _chat_ack()
        else:
            phase = "poll"
            response = _chat_readback(assistant_id)
        if phase == fault_phase:
            msg = "transport failed"
            raise httpx.ConnectError(msg)
        return response

    with (
        _webui_client(handler) as client,
        pytest.raises(WebUIProvisionError, match="failed"),
    ):
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        client.run_persisted_chat(_CHAT_PROMPT)


@pytest.mark.parametrize("fault_phase", ["create", "completion", "poll"])
def test_run_persisted_chat_rejects_non_200(fault_phase: str) -> None:
    assistant_id = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal assistant_id
        if request.url.path == "/api/v1/chats/new":
            phase = "create"
            response = httpx.Response(200, json={"id": _CHAT_ID})
        elif request.url.path == "/api/chat/completions":
            phase = "completion"
            body: dict[str, object] = json.loads(request.content)
            value = body["id"]
            assert isinstance(value, str)
            assistant_id = value
            response = _chat_ack()
        else:
            phase = "poll"
            response = _chat_readback(assistant_id)
        if phase == fault_phase:
            return httpx.Response(503)
        return response

    with (
        _webui_client(handler) as client,
        pytest.raises(WebUIProvisionError, match="returned HTTP 503"),
    ):
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        client.run_persisted_chat(_CHAT_PROMPT)


@pytest.mark.parametrize("fault_phase", ["create", "completion", "poll"])
@pytest.mark.parametrize(
    "bad_body",
    [
        pytest.param(b"{", id="malformed-json"),
        pytest.param(b"\xff", id="invalid-utf8"),
    ],
)
def test_run_persisted_chat_rejects_invalid_json(
    fault_phase: str,
    bad_body: bytes,
) -> None:
    assistant_id = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal assistant_id
        if request.url.path == "/api/v1/chats/new":
            phase = "create"
            response = httpx.Response(200, json={"id": _CHAT_ID})
        elif request.url.path == "/api/chat/completions":
            phase = "completion"
            body: dict[str, object] = json.loads(request.content)
            value = body["id"]
            assert isinstance(value, str)
            assistant_id = value
            response = _chat_ack()
        else:
            phase = "poll"
            response = _chat_readback(assistant_id)
        if phase == fault_phase:
            return httpx.Response(200, content=bad_body)
        return response

    with (
        _webui_client(handler) as client,
        pytest.raises(WebUIProvisionError, match="invalid response"),
    ):
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        client.run_persisted_chat(_CHAT_PROMPT)


def test_run_persisted_chat_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "monotonic", itertools.count(0.0, 1.0).__next__)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    assistant_id = ""
    polls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal assistant_id, polls
        if request.url.path == "/api/v1/chats/new":
            return httpx.Response(200, json={"id": _CHAT_ID})
        if request.url.path == "/api/chat/completions":
            body: dict[str, object] = json.loads(request.content)
            value = body["id"]
            assert isinstance(value, str)
            assistant_id = value
            return _chat_ack()
        polls += 1
        return _chat_readback(assistant_id, include_assistant=False)

    with (
        _webui_client(handler, Settings(ready_timeout=2.0)) as client,
        pytest.raises(WebUIProvisionError, match=r"did not complete after 2\.0s"),
    ):
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        client.run_persisted_chat(_CHAT_PROMPT)

    assert polls == 2


def test_run_persisted_chat_rejects_done_message_without_final_text() -> None:
    assistant_id = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal assistant_id
        if request.url.path == "/api/v1/chats/new":
            return httpx.Response(200, json={"id": _CHAT_ID})
        if request.url.path == "/api/chat/completions":
            body: dict[str, object] = json.loads(request.content)
            value = body["id"]
            assert isinstance(value, str)
            assistant_id = value
            return _chat_ack()
        return _chat_readback(assistant_id, malformed_output=True)

    with (
        _webui_client(handler) as client,
        pytest.raises(WebUIProvisionError, match="returned no final text"),
    ):
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        client.run_persisted_chat(_CHAT_PROMPT)


@pytest.mark.parametrize("readback", ["model_ids", "tool_server_ids"])
def test_authed_read_before_authenticate_raises(readback: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("no request should be sent before authenticate")

    with (
        _webui_client(handler) as client,
        pytest.raises(WebUIProvisionError, match="authenticate"),
    ):
        getattr(client, readback)()


@pytest.mark.parametrize("readback", ["model_ids", "tool_server_ids"])
def test_authed_read_raises_loud_on_non_200(readback: str) -> None:
    # A non-200 readback (401 rejected token) must raise, not decode an error body to [].
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Not authenticated"})

    with _webui_client(handler) as client:
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        with pytest.raises(WebUIProvisionError, match="HTTP 401"):
            getattr(client, readback)()


@pytest.mark.parametrize("readback", ["model_ids", "tool_server_ids"])
def test_authed_read_normalizes_transport_error(readback: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        msg = "connection reset"
        raise httpx.ConnectError(msg)

    with _webui_client(handler) as client:
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        with pytest.raises(WebUIProvisionError, match=r"GET .+ failed: connection reset"):
            getattr(client, readback)()


@pytest.mark.parametrize(
    ("readback", "path"),
    [("model_ids", "/api/models"), ("tool_server_ids", "/api/v1/tools/")],
)
@pytest.mark.parametrize(
    "body",
    [b"not JSON", b'[{"id":"\xff"}]'],
    ids=["malformed-json", "invalid-utf8"],
)
def test_authed_read_normalizes_malformed_response(readback: str, path: str, body: bytes) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    with _webui_client(handler) as client:
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        with pytest.raises(WebUIProvisionError, match=rf"GET {path} returned an invalid response"):
            getattr(client, readback)()


# --- global filter convergence --------------------------------------------------------------
def test_ensure_global_filter_creates_missing_then_activates_globally() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer tok"
        call = (request.method, request.url.path)
        calls.append(call)
        if call == ("GET", _FUNCTION_PATH):
            if calls == [call]:
                return httpx.Response(401, json={"detail": "Function not found"})
            return httpx.Response(200, json=_function_state(active=True, global_=True))
        if call == ("POST", "/api/v1/functions/create"):
            assert json.loads(request.content) == _FUNCTION_PAYLOAD
            return httpx.Response(200, json=_function_state(content=None))
        if call == ("POST", f"{_FUNCTION_PATH}/toggle"):
            return httpx.Response(200, json=_function_state(active=True))
        if call == ("POST", f"{_FUNCTION_PATH}/toggle/global"):
            return httpx.Response(200, json=_function_state(active=True, global_=True))
        pytest.fail(f"unexpected call {call}")

    with _webui_client(handler) as client:
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        _ensure_global_filter(client)

    assert calls == [
        ("GET", _FUNCTION_PATH),
        ("POST", "/api/v1/functions/create"),
        ("POST", f"{_FUNCTION_PATH}/toggle"),
        ("POST", f"{_FUNCTION_PATH}/toggle/global"),
        ("GET", _FUNCTION_PATH),
    ]


@pytest.mark.parametrize(
    ("active", "global_", "expected_toggles"),
    [
        (False, False, ("toggle", "toggle/global")),
        (False, True, ("toggle",)),
        (True, False, ("toggle/global",)),
        (True, True, ()),
    ],
)
def test_ensure_global_filter_updates_existing_without_toggling_true_flags_off(
    *, active: bool, global_: bool, expected_toggles: tuple[str, ...]
) -> None:
    calls: list[tuple[str, str]] = []
    state = _function_state(active=active, global_=global_, content="stale source")
    discoveries = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal discoveries, state
        assert request.headers["authorization"] == "Bearer tok"
        call = (request.method, request.url.path)
        calls.append(call)
        if call == ("GET", _FUNCTION_PATH):
            discoveries += 1
            return httpx.Response(200, json=state)
        if call == ("POST", f"{_FUNCTION_PATH}/update"):
            assert json.loads(request.content) == _FUNCTION_PAYLOAD
            state = _function_state(active=active, global_=global_)
            return httpx.Response(200, json=state)
        if call == ("POST", f"{_FUNCTION_PATH}/toggle"):
            state = _function_state(active=True, global_=global_)
            return httpx.Response(200, json=state)
        if call == ("POST", f"{_FUNCTION_PATH}/toggle/global"):
            state = _function_state(active=True, global_=True)
            return httpx.Response(200, json=state)
        pytest.fail(f"unexpected call {call}")

    with _webui_client(handler) as client:
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        _ensure_global_filter(client)

    assert discoveries == 2
    assert calls == [
        ("GET", _FUNCTION_PATH),
        ("POST", f"{_FUNCTION_PATH}/update"),
        *(("POST", f"{_FUNCTION_PATH}/{suffix}") for suffix in expected_toggles),
        ("GET", _FUNCTION_PATH),
    ]


@pytest.mark.parametrize(
    ("responses", "expected_paths"),
    [
        ([httpx.Response(500)], (_FUNCTION_PATH,)),
        (
            [httpx.Response(401), httpx.Response(500)],
            (_FUNCTION_PATH, "/api/v1/functions/create"),
        ),
        (
            [httpx.Response(200, json=_function_state()), httpx.Response(500)],
            (_FUNCTION_PATH, f"{_FUNCTION_PATH}/update"),
        ),
        (
            [
                httpx.Response(401),
                httpx.Response(200, json=_function_state()),
                httpx.Response(500),
            ],
            (_FUNCTION_PATH, "/api/v1/functions/create", f"{_FUNCTION_PATH}/toggle"),
        ),
        (
            [
                httpx.Response(401),
                httpx.Response(200, json=_function_state(active=True)),
                httpx.Response(500),
            ],
            (
                _FUNCTION_PATH,
                "/api/v1/functions/create",
                f"{_FUNCTION_PATH}/toggle/global",
            ),
        ),
        (
            [
                httpx.Response(401),
                httpx.Response(200, json=_function_state(active=True, global_=True)),
                httpx.Response(500),
            ],
            (_FUNCTION_PATH, "/api/v1/functions/create", _FUNCTION_PATH),
        ),
    ],
    ids=("discovery", "create", "update", "active-toggle", "global-toggle", "final-read"),
)
def test_ensure_global_filter_raises_on_non_200_at_every_seam(
    responses: list[httpx.Response], expected_paths: tuple[str, ...]
) -> None:
    response_iter = iter(responses)
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return next(response_iter)

    with (
        _webui_client(handler) as client,
        pytest.raises(WebUIProvisionError, match="HTTP 500"),
    ):
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        _ensure_global_filter(client)
    assert paths == list(expected_paths)


@pytest.mark.parametrize(
    "responses",
    [
        [httpx.Response(200, json={})],
        [httpx.Response(401), httpx.Response(200, json={})],
        [
            httpx.Response(401),
            httpx.Response(200, json=_function_state()),
            httpx.Response(200, json={}),
        ],
        [
            httpx.Response(401),
            httpx.Response(200, json=_function_state(active=True)),
            httpx.Response(200, json={}),
        ],
        [
            httpx.Response(401),
            httpx.Response(200, json=_function_state(active=True, global_=True)),
            httpx.Response(200, json={}),
        ],
    ],
    ids=("discovery", "write", "active-toggle", "global-toggle", "final-read"),
)
def test_ensure_global_filter_raises_on_malformed_200_at_every_seam(
    responses: list[httpx.Response],
) -> None:
    response_iter = iter(responses)

    def handler(_request: httpx.Request) -> httpx.Response:
        return next(response_iter)

    with (
        _webui_client(handler) as client,
        pytest.raises(WebUIProvisionError, match="invalid function state"),
    ):
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        _ensure_global_filter(client)


def test_ensure_global_filter_normalizes_invalid_utf8_state() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"id":"\xff"}')

    with (
        _webui_client(handler) as client,
        pytest.raises(WebUIProvisionError, match="invalid function state"),
    ):
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        _ensure_global_filter(client)


@pytest.mark.parametrize(
    ("responses", "match"),
    [
        (
            [httpx.Response(200, json=_function_state(function_id="other_filter"))],
            "discovery function state mismatch: id",
        ),
        (
            [
                httpx.Response(401),
                httpx.Response(
                    200,
                    json=_function_state(function_type="action", content=None),
                ),
            ],
            "create function state mismatch: type",
        ),
        (
            [
                httpx.Response(200, json=_function_state(content="stale source")),
                httpx.Response(200, json=_function_state(content="stale source")),
            ],
            "update function state mismatch: content",
        ),
    ],
    ids=("discovery-id", "create-type", "update-content"),
)
def test_ensure_global_filter_rejects_inexact_intermediate_state(
    responses: list[httpx.Response], match: str
) -> None:
    response_iter = iter(responses)

    def handler(_request: httpx.Request) -> httpx.Response:
        return next(response_iter)

    with _webui_client(handler) as client, pytest.raises(WebUIProvisionError, match=match):
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        _ensure_global_filter(client)


@pytest.mark.parametrize(
    ("responses", "phase", "field"),
    [
        (
            [
                httpx.Response(401),
                httpx.Response(200, json=_function_state()),
                httpx.Response(200, json=_function_state()),
            ],
            "active toggle",
            "is_active",
        ),
        (
            [
                httpx.Response(401),
                httpx.Response(200, json=_function_state(active=True)),
                httpx.Response(200, json=_function_state(active=True)),
            ],
            "global toggle",
            "is_global",
        ),
    ],
)
def test_ensure_global_filter_rejects_toggle_that_does_not_set_its_flag(
    responses: list[httpx.Response], phase: str, field: str
) -> None:
    response_iter = iter(responses)

    def handler(_request: httpx.Request) -> httpx.Response:
        return next(response_iter)

    with (
        _webui_client(handler) as client,
        pytest.raises(WebUIProvisionError, match=rf"{phase} function state mismatch: {field}"),
    ):
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        _ensure_global_filter(client)


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("id", "other_filter"),
        ("type", "action"),
        ("content", "stale source"),
        ("is_active", False),
        ("is_global", False),
    ],
)
def test_ensure_global_filter_rejects_inexact_final_state(field: str, wrong_value: object) -> None:
    final = _function_state(active=True, global_=True)
    final[field] = wrong_value
    responses = iter(
        [
            httpx.Response(401),
            httpx.Response(200, json=_function_state(active=True, global_=True)),
            httpx.Response(200, json=final),
        ]
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return next(responses)

    with (
        _webui_client(handler) as client,
        pytest.raises(WebUIProvisionError, match=rf"final function state mismatch: {field}"),
    ):
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        _ensure_global_filter(client)


def test_ensure_global_filter_requires_authentication_before_discovery() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("no request should be sent before authenticate")

    with (
        _webui_client(handler) as client,
        pytest.raises(WebUIProvisionError, match="authenticate"),
    ):
        _ensure_global_filter(client)


def test_ensure_global_filter_normalizes_transport_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        msg = "connection reset"
        raise httpx.ConnectError(msg)

    with (
        _webui_client(handler) as client,
        pytest.raises(WebUIProvisionError, match=r"GET .+ failed: connection reset"),
    ):
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        _ensure_global_filter(client)


# --- workspace-model tool convergence -------------------------------------------------------
def test_ensure_model_tool_creates_missing_config_and_verifies() -> None:
    model_id = "model/create"
    tool_id = "server:verifier"
    calls: list[tuple[str, str]] = []
    config: dict[str, object] | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal config
        if request.url.path == "/api/v1/auths/signup":
            return httpx.Response(200, json={"token": "tok"})
        assert request.headers["authorization"] == "Bearer tok"
        call = (request.method, request.url.path)
        calls.append(call)
        if call == ("GET", "/api/v1/models/model"):
            assert request.url.params.get("id") == model_id
            if config is None:
                return httpx.Response(404, json={"detail": "Model not found"})
            return httpx.Response(200, json=config)
        assert call == ("POST", "/api/v1/models/create")
        payload: dict[str, object] = json.loads(request.content)
        assert payload == {
            "id": model_id,
            "base_model_id": None,
            "name": model_id,
            "meta": {"toolIds": [tool_id]},
            "params": {},
            "is_active": True,
        }
        config = payload
        return httpx.Response(200, json=config)

    with _webui_client(handler) as client:
        client.authenticate()
        client.ensure_model_tool(model_id=model_id, tool_id=tool_id)

    assert calls == [
        ("GET", "/api/v1/models/model"),
        ("POST", "/api/v1/models/create"),
        ("GET", "/api/v1/models/model"),
    ]


def test_ensure_model_tool_updates_by_merging_operator_config() -> None:
    model_id = "model-update"
    tool_id = "server:verifier"
    config: dict[str, object] = {
        "id": model_id,
        "base_model_id": "base-model",
        "name": "Operator model name",
        "params": {"temperature": 0.25, "nested": {"keep": True}},
        "meta": {
            "toolIds": ["server:other"],
            "description": "keep me",
            "nested": {"keep": "also"},
        },
        "is_active": False,
    }
    writes = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal config, writes
        if request.url.path == "/api/v1/auths/signup":
            return httpx.Response(200, json={"token": "tok"})
        assert request.headers["authorization"] == "Bearer tok"
        if request.method == "GET":
            return httpx.Response(200, json=config)
        assert request.url.path == "/api/v1/models/model/update"
        writes += 1
        payload: dict[str, object] = json.loads(request.content)
        assert payload == {
            "id": model_id,
            "base_model_id": "base-model",
            "name": "Operator model name",
            "params": {"temperature": 0.25, "nested": {"keep": True}},
            "meta": {
                "toolIds": ["server:other", tool_id],
                "description": "keep me",
                "nested": {"keep": "also"},
            },
            "is_active": False,
        }
        assert "access_grants" not in payload
        config = payload
        return httpx.Response(200, json=config)

    with _webui_client(handler) as client:
        client.authenticate()
        client.ensure_model_tool(model_id=model_id, tool_id=tool_id)

    assert writes == 1


def test_ensure_model_tool_is_write_free_when_already_attached() -> None:
    model_id = "model"
    tool_id = "server:verifier"
    model_gets = 0
    writes = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal model_gets, writes
        if request.url.path == "/api/v1/auths/signup":
            return httpx.Response(200, json={"token": "tok"})
        if request.method == "POST":
            writes += 1
            return httpx.Response(500)
        model_gets += 1
        return httpx.Response(200, json=_model_config(model_id, tool_id))

    with _webui_client(handler) as client:
        client.authenticate()
        client.ensure_model_tool(model_id=model_id, tool_id=tool_id)

    assert model_gets == 1
    assert writes == 0


def test_ensure_model_tool_rejects_discovery_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auths/signup":
            return httpx.Response(200, json={"token": "tok"})
        return httpx.Response(500)

    with _webui_client(handler) as client:
        client.authenticate()
        with pytest.raises(WebUIProvisionError, match="HTTP 500"):
            client.ensure_model_tool(model_id="model", tool_id="server:verifier")


@pytest.mark.parametrize(
    ("existing", "write_path"),
    [
        (False, "/api/v1/models/create"),
        (True, "/api/v1/models/model/update"),
    ],
    ids=["create", "update"],
)
def test_ensure_model_tool_rejects_write_error(*, existing: bool, write_path: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auths/signup":
            return httpx.Response(200, json={"token": "tok"})
        if request.method == "GET":
            if existing:
                return httpx.Response(200, json=_model_config("model"))
            return httpx.Response(404)
        assert request.url.path == write_path
        return httpx.Response(503)

    with _webui_client(handler) as client:
        client.authenticate()
        with pytest.raises(WebUIProvisionError, match="HTTP 503"):
            client.ensure_model_tool(model_id="model", tool_id="server:verifier")


def test_ensure_model_tool_rejects_missing_tool_after_write() -> None:
    model_gets = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal model_gets
        if request.url.path == "/api/v1/auths/signup":
            return httpx.Response(200, json={"token": "tok"})
        if request.method == "GET":
            model_gets += 1
            if model_gets == 1:
                return httpx.Response(404)
            return httpx.Response(200, json=_model_config("model"))
        return httpx.Response(200, json=_model_config("model", "server:verifier"))

    with _webui_client(handler) as client:
        client.authenticate()
        with pytest.raises(WebUIProvisionError, match="did not persist"):
            client.ensure_model_tool(model_id="model", tool_id="server:verifier")


@pytest.mark.parametrize("phase", ["discovery", "write", "verify"])
@pytest.mark.parametrize(
    "bad_body",
    [b"not JSON", b'{"meta":{"toolIds":["\xff"]}}'],
    ids=["malformed-json", "invalid-utf8"],
)
def test_ensure_model_tool_rejects_invalid_json_at_every_phase(
    phase: str,
    bad_body: bytes,
) -> None:
    model_gets = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal model_gets
        if request.url.path == "/api/v1/auths/signup":
            return httpx.Response(200, json={"token": "tok"})
        if request.method == "GET":
            model_gets += 1
            if phase == "discovery" and model_gets == 1:
                return httpx.Response(200, content=bad_body)
            if model_gets == 1:
                return httpx.Response(404)
            if phase == "verify":
                return httpx.Response(200, content=bad_body)
            pytest.fail("unexpected model-config GET")
        if phase == "write":
            return httpx.Response(200, content=bad_body)
        return httpx.Response(200, json=_model_config("model", "server:verifier"))

    with _webui_client(handler) as client:
        client.authenticate()
        with pytest.raises(WebUIProvisionError, match="invalid model config"):
            client.ensure_model_tool(model_id="model", tool_id="server:verifier")


def test_ensure_model_tool_normalizes_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auths/signup":
            return httpx.Response(200, json={"token": "tok"})
        msg = "connection reset"
        raise httpx.ConnectError(msg)

    with _webui_client(handler) as client:
        client.authenticate()
        with pytest.raises(WebUIProvisionError, match=r"GET .+ failed: connection reset"):
            client.ensure_model_tool(model_id="model", tool_id="server:verifier")


def test_ensure_model_tool_requires_authentication() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("no request should be sent before authenticate")

    with (
        _webui_client(handler) as client,
        pytest.raises(WebUIProvisionError, match="authenticate"),
    ):
        client.ensure_model_tool(model_id="model", tool_id="server:verifier")


# --- smoke / run_bootstrap ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model_enumerated", "tool_registered", "model_tool_attached", "expected_ok"),
    [
        (True, True, True, True),
        (True, True, False, False),
        (True, False, True, False),
        (True, False, False, False),
        (False, True, True, False),
        (False, True, False, False),
        (False, False, True, False),
        (False, False, False, False),
    ],
)
def test_smoke_result_ok_is_conjunction(
    *,
    model_enumerated: bool,
    tool_registered: bool,
    model_tool_attached: bool,
    expected_ok: bool,
) -> None:
    result = SmokeResult(
        model_ids=(),
        tool_server_ids=(),
        model_tool_ids=(),
        model_enumerated=model_enumerated,
        tool_registered=tool_registered,
        model_tool_attached=model_tool_attached,
    )
    assert result.ok is expected_ok


def test_smoke_derives_membership_without_wait_or_auth() -> None:
    settings = Settings()
    fake = _FakeClient(
        model_ids=["other-model", settings.model_id],
        tool_server_ids=["server:x", f"server:{settings.tool_server_id}"],
    )
    result = smoke(fake, settings)
    assert result.model_enumerated
    assert result.tool_registered
    assert result.model_tool_attached
    assert result.model_ids == ("other-model", settings.model_id)
    assert result.model_tool_ids == ("server:x", f"server:{settings.tool_server_id}")
    assert fake.calls == [
        "model_ids",
        "tool_server_ids",
        "model_tool_ids",
    ]  # smoke alone: no wait_ready/authenticate


def test_run_bootstrap_ok_in_order() -> None:
    settings = Settings()
    fake = _FakeClient(
        model_ids=[settings.model_id],
        tool_server_ids=[f"server:{settings.tool_server_id}"],
    )
    result = run_bootstrap(fake, settings)
    assert result.ok
    assert fake.calls == [
        "wait_ready",
        "authenticate",
        "ensure_global_filter",
        "ensure_model_tool",
        "model_ids",
        "tool_server_ids",
        "model_tool_ids",
    ]
    assert fake.filter_calls == [(FILTER_ID, FILTER_NAME, function_source(), FILTER_DESCRIPTION)]
    assert fake.model_tool_calls == [(settings.model_id, f"server:{settings.tool_server_id}")]


def test_run_bootstrap_fake_rerun_reconverges_before_each_smoke() -> None:
    settings = Settings()
    fake = _FakeClient(
        model_ids=[settings.model_id],
        tool_server_ids=[f"server:{settings.tool_server_id}"],
    )
    expected_order = [
        "wait_ready",
        "authenticate",
        "ensure_global_filter",
        "ensure_model_tool",
        "model_ids",
        "tool_server_ids",
        "model_tool_ids",
    ]
    expected_filter_call = (FILTER_ID, FILTER_NAME, function_source(), FILTER_DESCRIPTION)
    expected_model_tool_call = (settings.model_id, f"server:{settings.tool_server_id}")

    first = run_bootstrap(fake, settings)
    second = run_bootstrap(fake, settings)

    assert first == second
    assert first.ok
    assert fake.calls == expected_order * 2
    assert fake.filter_calls == [expected_filter_call] * 2
    assert fake.model_tool_calls == [expected_model_tool_call] * 2


def test_run_bootstrap_does_not_smoke_after_filter_convergence_failure() -> None:
    settings = Settings()
    fake = _FakeClient(
        model_ids=[settings.model_id],
        tool_server_ids=[f"server:{settings.tool_server_id}"],
        fail_filter=True,
    )

    with pytest.raises(WebUIProvisionError, match="filter convergence failed"):
        run_bootstrap(fake, settings)

    assert fake.calls == ["wait_ready", "authenticate", "ensure_global_filter"]


@pytest.mark.parametrize(
    ("model_present", "tool_registered", "model_tool_attached"),
    [
        (False, True, True),
        (True, False, True),
        (True, True, False),
    ],
)
def test_run_bootstrap_not_ok_when_either_missing(
    *,
    model_present: bool,
    tool_registered: bool,
    model_tool_attached: bool,
) -> None:
    settings = Settings()
    tool_id = f"server:{settings.tool_server_id}"
    fake = _FakeClient(
        [settings.model_id] if model_present else [],
        [tool_id] if tool_registered else [],
        [tool_id] if model_tool_attached else [],
    )
    result = run_bootstrap(fake, settings)
    assert not result.ok


def test_run_bootstrap_rerun_is_idempotent_via_signin_and_filter_update() -> None:
    # First run signs up + creates; rerun signs in, updates the filter, and does no model write.
    settings = Settings()
    state = _BootstrapTransport(settings, close_signup_after_first=True)

    with _webui_client(state, settings) as client:
        first = run_bootstrap(client, settings)
        second = run_bootstrap(client, settings)

    assert first == second
    assert first.ok
    assert first.model_tool_ids == (state.tool_id,)
    assert first.model_tool_attached
    assert state.signups == 2  # both runs attempted signup; the re-run fell back to signin
    assert state.filter_writes == {"create": 1, "update": 1}
    assert state.model_writes == {"create": 1, "update": 0}


def test_run_bootstrap_end_to_end_over_mock_transport() -> None:
    settings = Settings()
    state = _BootstrapTransport(settings, close_signup_after_first=False)

    with _webui_client(state, settings) as client:
        result = run_bootstrap(client, settings)

    assert result.ok
    assert result.model_ids == (settings.model_id,)
    assert result.tool_server_ids == (state.tool_id,)
    assert result.model_tool_ids == (state.tool_id,)
    assert result.model_tool_attached
