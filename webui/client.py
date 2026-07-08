# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Provisioning REST client for a headless Open WebUI (M4.3b).

A thin sync httpx wrapper over the four OWUI endpoints the provisioning smoke needs, with the
request shapes + fallbacks settled live against 0.10.2 (memory M4 Provisioning-SETTLED-LIVE) --
TRANSCRIBED here, not re-probed. Every step fails closed via WebUIProvisionError so a misconfigured
deploy raises loud rather than leaving a half-provisioned, silently-unauthenticated client.

The client is injected an httpx.Client (base_url + request_timeout wired by the launcher, M4.3c; a
test injects a MockTransport-backed one), and holds the admin JWT after authenticate(). Responses
decode through loose msgspec structs (unknown OWUI keys ignored) -- only the load-bearing fields
(token, model id, tool-server id) are modelled, matching the bench consumer-struct convention.
"""

import time

import httpx
import msgspec

from webui.settings import Settings

# OWUI names every tool-SERVER group "server:<info.id>" (routers/tools.py); the prefix tells a
# server tool from a python-function tool in the GET /api/v1/tools/ readback. bootstrap reuses it.
_TOOL_SERVER_ID_PREFIX = "server:"

# Seconds between GET /ready polls while OWUI finishes startup (cold boot ~7-10s here, memory M4).
_READY_POLL_INTERVAL = 1.0


class WebUIProvisionError(RuntimeError):
    """A provisioning step failed unrecoverably: readiness timeout, auth failure, or empty token."""


class _AuthResponse(msgspec.Struct):
    """Loose OWUI signup/signin reply; only the JWT is load-bearing (empty default => we raise)."""

    token: str = ""


class _Model(msgspec.Struct):
    """One entry of the GET /api/models `data` envelope; only the id is read."""

    id: str


class _ModelsEnvelope(msgspec.Struct):
    """GET /api/models body: a `{data: [...]}` envelope (default empty => enumerated-none)."""

    data: tuple[_Model, ...] = ()


class _ToolServer(msgspec.Struct):
    """One entry of the BARE GET /api/v1/tools/ array (list[ToolUserResponse]); only id is read."""

    id: str


class WebUIClient:
    """Drives the OWUI provisioning REST surface over an injected httpx.Client.

    Stateful only in the stored admin JWT (_token, set by authenticate()); the authed readbacks
    (model_ids/tool_server_ids) send it as a Bearer header and raise if authenticate() has not run.
    """

    def __init__(self, http: httpx.Client, settings: Settings) -> None:
        self._http = http
        self._settings = settings
        self._token: str | None = None

    def wait_ready(self) -> None:
        """Poll GET /ready until 200 or the ready_timeout deadline; raise on timeout.

        /health 200s before startup finishes; /ready gates on startup_complete (503 until, memory
        M4 Standup), and a pre-bind poll raises httpx.HTTPError (connection refused) -- both mean
        still-booting, so swallow and retry every _READY_POLL_INTERVAL against a monotonic deadline.
        """
        deadline = time.monotonic() + self._settings.ready_timeout
        while True:
            try:
                if self._http.get("/ready").status_code == httpx.codes.OK:
                    return
            except httpx.HTTPError:
                pass  # still booting (pre-bind connection refused / transport error): retry
            if time.monotonic() >= deadline:
                msg = f"Open WebUI not ready after {self._settings.ready_timeout}s"
                raise WebUIProvisionError(msg)
            time.sleep(_READY_POLL_INTERVAL)

    def authenticate(self) -> str:
        """Sign up the first-run admin (else sign in); store + return the JWT.

        Idempotent across restarts (memory M4 Provisioning-SETTLED-LIVE): a first signup on a fresh
        DATA_DIR auto-promotes admin (200 + token); a re-run hits a closed signup (403 same-process,
        400 EMAIL_TAKEN post-restart), so ANY non-200 signup falls back to signin. Both non-200, or
        a 200 with an empty token, raise WebUIProvisionError (no silently-unauthenticated client).
        """
        response = self._http.post(
            "/api/v1/auths/signup",
            json={
                "name": self._settings.admin_name,
                "email": self._settings.admin_email,
                "password": self._settings.admin_password,
            },
        )
        signup_status = response.status_code
        if signup_status != httpx.codes.OK:
            response = self._http.post(
                "/api/v1/auths/signin",
                json={
                    "email": self._settings.admin_email,
                    "password": self._settings.admin_password,
                },
            )
        if response.status_code != httpx.codes.OK:
            msg = (
                f"authentication failed: signup HTTP {signup_status}, "
                f"signin HTTP {response.status_code}"
            )
            raise WebUIProvisionError(msg)
        token = msgspec.json.decode(response.content, type=_AuthResponse).token
        if not token:
            msg = "authentication succeeded but returned an empty token"
            raise WebUIProvisionError(msg)
        self._token = token
        return token

    def model_ids(self) -> list[str]:
        """Authed GET /api/models -> the served model ids (the `{data: [...]}` envelope's ids)."""
        body = self._authed_get("/api/models")
        envelope = msgspec.json.decode(body, type=_ModelsEnvelope)
        return [model.id for model in envelope.data]

    def tool_server_ids(self) -> list[str]:
        """Authed GET /api/v1/tools/ -> the registered tool-SERVER ids (`server:`-prefixed).

        The body is a BARE `list[ToolUserResponse]` (routers/tools.py), NOT a `data` envelope; keep
        only `server:`-prefixed ids so a python-function tool never counts as a registered server.
        """
        body = self._authed_get("/api/v1/tools/")
        tools = msgspec.json.decode(body, type=tuple[_ToolServer, ...])
        return [tool.id for tool in tools if tool.id.startswith(_TOOL_SERVER_ID_PREFIX)]

    def _authed_get(self, path: str) -> bytes:
        """Authed GET that fails closed on non-200 -> the raw body for the caller to decode.

        Gates the readbacks the way authenticate() gates auth: a non-200 (401 on a stale/rejected
        token, 5xx upstream) raises WebUIProvisionError with path + status, so a broken readback
        surfaces LOUD instead of decoding an error body to an empty list (a silent ok=False). The
        readback endpoints are verified-user-gated (routers/tools.py, main.py get_verified_user), so
        a wrong/unverified principal lands here as a 401 rather than as filtered-empty data.
        """
        response = self._http.get(path, headers=self._auth_headers())
        if response.status_code != httpx.codes.OK:
            msg = f"GET {path} returned HTTP {response.status_code}"
            raise WebUIProvisionError(msg)
        return response.content

    def _auth_headers(self) -> dict[str, str]:
        """The Bearer header for an authed request; raise if authenticate() has not run."""
        if self._token is None:
            msg = "authenticate() must run before an authed request"
            raise WebUIProvisionError(msg)
        return {"Authorization": f"Bearer {self._token}"}
