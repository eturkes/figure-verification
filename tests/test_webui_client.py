# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Feedback loop for the Open WebUI provisioning client + smoke (M4.3b).

webui/ is a coverage-excluded harness, so these are a bench-style regression net (like
test_webui_settings.py) rather than a 100%-branch gate. The OWUI request shapes are TRANSCRIBED
from memory M4 Provisioning-SETTLED-LIVE, not re-probed; here they are pinned against an
httpx.MockTransport (no socket binds, every branch deterministic), plus a structural fake for the
bootstrap orchestration. Locked:

- wait_ready: returns on the first 200, retries through transport errors, raises on timeout;
- authenticate: signup-200 stores the JWT; a non-200 signup falls back to signin; both non-200 or an
  empty token raise; the stored token rides authed reads as a Bearer header;
- model_ids / tool_server_ids: the `{data: [...]}` envelope vs the BARE array, and the `server:`
  filter that drops a python-function tool;
- smoke / run_bootstrap: the membership derivation, the ok truth table, the wait->auth->smoke order,
  and idempotency across repeated runs.
"""

import itertools
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import httpx
import pytest

from webui.bootstrap import SmokeResult, run_bootstrap, smoke
from webui.client import WebUIClient, WebUIProvisionError
from webui.settings import Settings

_Handler = Callable[[httpx.Request], httpx.Response]


@contextmanager
def _webui_client(handler: _Handler, settings: Settings | None = None) -> Iterator[WebUIClient]:
    """A WebUIClient over a MockTransport running `handler` (no real socket)."""
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://webui.test") as http:
        yield WebUIClient(http, settings if settings is not None else Settings())


class _FakeClient:
    """A structural _Provisioner: canned readbacks + a call log, so the bootstrap orchestration is
    tested without any HTTP."""

    def __init__(self, model_ids: list[str], tool_server_ids: list[str]) -> None:
        self._model_ids = model_ids
        self._tool_server_ids = tool_server_ids
        self.calls: list[str] = []

    def wait_ready(self) -> None:
        self.calls.append("wait_ready")

    def authenticate(self) -> str:
        self.calls.append("authenticate")
        return "jwt"

    def model_ids(self) -> list[str]:
        self.calls.append("model_ids")
        return list(self._model_ids)

    def tool_server_ids(self) -> list[str]:
        self.calls.append("tool_server_ids")
        return list(self._tool_server_ids)


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


def test_authenticate_raises_when_signup_and_signin_both_fail() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "nope"})

    with (
        _webui_client(handler) as client,
        pytest.raises(WebUIProvisionError, match="signup and signin"),
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


# --- authed readbacks -----------------------------------------------------------------------
def test_model_ids_parses_data_envelope_with_bearer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer tok"
        return httpx.Response(200, json={"data": [{"id": "m1"}, {"id": "m2"}]})

    with _webui_client(handler) as client:
        client._token = "tok"  # noqa: S105 (test literal, not a real secret)
        assert client.model_ids() == ["m1", "m2"]


def test_tool_server_ids_parses_bare_array_and_filters_non_server() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
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


def test_authed_read_before_authenticate_raises() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("no request should be sent before authenticate")

    with (
        _webui_client(handler) as client,
        pytest.raises(WebUIProvisionError, match="authenticate"),
    ):
        client.model_ids()


# --- smoke / run_bootstrap ------------------------------------------------------------------
@pytest.mark.parametrize(
    ("model_enumerated", "tool_registered", "expected_ok"),
    [(True, True, True), (True, False, False), (False, True, False), (False, False, False)],
)
def test_smoke_result_ok_is_conjunction(
    *, model_enumerated: bool, tool_registered: bool, expected_ok: bool
) -> None:
    result = SmokeResult(
        model_ids=(),
        tool_server_ids=(),
        model_enumerated=model_enumerated,
        tool_registered=tool_registered,
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
    assert result.model_ids == ("other-model", settings.model_id)
    assert fake.calls == ["model_ids", "tool_server_ids"]  # smoke alone: no wait_ready/authenticate


def test_run_bootstrap_ok_in_order() -> None:
    settings = Settings()
    fake = _FakeClient(
        model_ids=[settings.model_id],
        tool_server_ids=[f"server:{settings.tool_server_id}"],
    )
    result = run_bootstrap(fake, settings)
    assert result.ok
    assert fake.calls == ["wait_ready", "authenticate", "model_ids", "tool_server_ids"]


@pytest.mark.parametrize(
    ("model_ids", "tool_server_ids"),
    [
        ([], ["server:verifier"]),  # model missing
        (["Qwen2-0.5B-Instruct-int4-sym-ov"], []),  # tool server missing
    ],
)
def test_run_bootstrap_not_ok_when_either_missing(
    model_ids: list[str], tool_server_ids: list[str]
) -> None:
    settings = Settings()
    result = run_bootstrap(_FakeClient(model_ids, tool_server_ids), settings)
    assert not result.ok


def test_run_bootstrap_is_idempotent() -> None:
    settings = Settings()
    fake = _FakeClient(
        model_ids=[settings.model_id],
        tool_server_ids=[f"server:{settings.tool_server_id}"],
    )
    first = run_bootstrap(fake, settings)
    second = run_bootstrap(fake, settings)
    assert first == second
    assert first.ok


def test_run_bootstrap_end_to_end_over_mock_transport() -> None:
    settings = Settings()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/ready":
            return httpx.Response(200)
        if path == "/api/v1/auths/signup":
            return httpx.Response(200, json={"token": "jwt"})
        if path == "/api/models":
            return httpx.Response(200, json={"data": [{"id": settings.model_id}]})
        if path == "/api/v1/tools/":
            return httpx.Response(200, json=[{"id": f"server:{settings.tool_server_id}"}])
        pytest.fail(f"unexpected path {path}")

    with _webui_client(handler, settings) as client:
        result = run_bootstrap(client, settings)
    assert result.ok
    assert result.model_ids == (settings.model_id,)
    assert result.tool_server_ids == (f"server:{settings.tool_server_id}",)
