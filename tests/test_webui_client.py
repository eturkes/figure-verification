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
- model_ids / tool_server_ids: the `{data: [...]}` envelope vs the BARE array, the `server:` filter
  that drops a python-function tool, the Bearer wiring, and a non-200 readback raising LOUD;
- ensure_global_filter: missing-create vs existing-update, all active/global flag combinations,
  exact payload/paths/Bearer wiring, final-state verification, and fail-closed seams;
- smoke / run_bootstrap: the membership derivation, the ok truth table, the wait->auth->smoke order,
  and restart-idempotency (a re-run's closed signup falls back to signin over a stateful transport).
"""

import itertools
import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import httpx
import pytest

from webui.bootstrap import SmokeResult, run_bootstrap, smoke
from webui.client import WebUIClient, WebUIProvisionError
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


def test_run_bootstrap_idempotent_across_restart_via_signin() -> None:
    # The real restart-idempotency: the first run signs up (200); a second run over the same OWUI
    # hits a closed signup (403) and falls back to signin (200). Both runs provision-OK and equal.
    settings = Settings()
    signups = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/ready":
            return httpx.Response(200)
        if path == "/api/v1/auths/signup":
            signups["n"] += 1
            if signups["n"] == 1:
                return httpx.Response(200, json={"token": "jwt-signup"})
            return httpx.Response(403, json={"detail": "signup closed"})
        if path == "/api/v1/auths/signin":
            return httpx.Response(200, json={"token": "jwt-signin"})
        if path == "/api/models":
            return httpx.Response(200, json={"data": [{"id": settings.model_id}]})
        if path == "/api/v1/tools/":
            return httpx.Response(200, json=[{"id": f"server:{settings.tool_server_id}"}])
        pytest.fail(f"unexpected path {path}")

    with _webui_client(handler, settings) as client:
        first = run_bootstrap(client, settings)
        second = run_bootstrap(client, settings)
    assert first == second
    assert first.ok
    assert signups["n"] == 2  # both runs attempted signup; the re-run fell back to signin


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
