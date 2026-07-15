# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Provisioning REST client for a headless Open WebUI (M4.3b, M4.4b).

A thin sync httpx wrapper over the OWUI provisioning endpoints, with request shapes + fallbacks
settled against 0.10.2 (memory M4 provisioning + filter contracts) -- TRANSCRIBED here, not
re-probed. Every step fails closed via WebUIProvisionError so a misconfigured deploy raises loud
rather than leaving a half-provisioned, silently-unauthenticated client.

The client is injected an httpx.Client (base_url + request_timeout wired by the launcher, M4.3d; a
test injects a MockTransport-backed one), and holds the admin JWT after authenticate(). Responses
decode through loose msgspec structs (unknown OWUI keys ignored) -- only load-bearing fields are
modelled, matching the bench consumer-struct convention.
"""

import time
from typing import Never

import httpx
import msgspec

from webui.settings import Settings

# OWUI names every tool-SERVER group "server:<info.id>" (routers/tools.py); the prefix tells a
# server tool from a python-function tool in the GET /api/v1/tools/ readback. bootstrap reuses it.
_TOOL_SERVER_ID_PREFIX = "server:"

_FILTER_FUNCTION_TYPE = "filter"

# Seconds between GET /ready polls while OWUI finishes startup (cold boot ~7-10s here, memory M4).
_READY_POLL_INTERVAL = 1.0


class WebUIProvisionError(RuntimeError):
    """A provisioning step failed unrecoverably or returned an invalid state."""


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


class _FunctionState(msgspec.Struct):
    """Loose function reply; create omits content, while model/toggle/update replies include it."""

    id: str
    type: str
    is_active: bool
    is_global: bool
    content: str | None = None


class WebUIClient:
    """Drives the OWUI provisioning REST surface over an injected httpx.Client.

    Stateful only in the stored admin JWT (_token, set by authenticate()); authed reads/writes send
    it as a Bearer header and raise if authenticate() has not run.
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

        Idempotent across restarts (memory M4 provisioning contract): a first signup on a fresh
        DATA_DIR auto-promotes admin (200 + token); a re-run hits a closed signup (403 same-process,
        400 EMAIL_TAKEN post-restart), so ANY non-200 signup falls back to signin. Both non-200, or
        a 200 with an empty token, raise WebUIProvisionError (no silently-unauthenticated client).
        """
        response = self._request(
            "POST",
            "/api/v1/auths/signup",
            json_body={
                "name": self._settings.admin_name,
                "email": self._settings.admin_email,
                "password": self._settings.admin_password,
            },
        )
        signup_status = response.status_code
        if signup_status != httpx.codes.OK:
            response = self._request(
                "POST",
                "/api/v1/auths/signin",
                json_body={
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
        try:
            token = msgspec.json.decode(response.content, type=_AuthResponse).token
        except (msgspec.DecodeError, UnicodeDecodeError) as exc:
            msg = f"authentication returned an invalid response: {exc}"
            raise WebUIProvisionError(msg) from exc
        if not token:
            msg = "authentication succeeded but returned an empty token"
            raise WebUIProvisionError(msg)
        self._token = token
        return token

    def model_ids(self) -> list[str]:
        """Authed GET /api/models -> the served model ids (the `{data: [...]}` envelope's ids)."""
        body = self._authed_get("/api/models")
        try:
            envelope = msgspec.json.decode(body, type=_ModelsEnvelope)
        except (msgspec.DecodeError, UnicodeDecodeError) as exc:
            msg = f"GET /api/models returned an invalid response: {exc}"
            raise WebUIProvisionError(msg) from exc
        return [model.id for model in envelope.data]

    def tool_server_ids(self) -> list[str]:
        """Authed GET /api/v1/tools/ -> the registered tool-SERVER ids (`server:`-prefixed).

        The body is a BARE `list[ToolUserResponse]` (routers/tools.py), NOT a `data` envelope; keep
        only `server:`-prefixed ids so a python-function tool never counts as a registered server.
        """
        body = self._authed_get("/api/v1/tools/")
        try:
            tools = msgspec.json.decode(body, type=tuple[_ToolServer, ...])
        except (msgspec.DecodeError, UnicodeDecodeError) as exc:
            msg = f"GET /api/v1/tools/ returned an invalid response: {exc}"
            raise WebUIProvisionError(msg) from exc
        return [tool.id for tool in tools if tool.id.startswith(_TOOL_SERVER_ID_PREFIX)]

    def ensure_global_filter(
        self,
        *,
        function_id: str,
        name: str,
        content: str,
        description: str,
    ) -> None:
        """Create/update one owned filter, converge active+global flags, then prove final state.

        Open WebUI reports a missing function as 401. A present function is always updated so a
        bootstrap rerun deploys current source; create/update share one exact payload. Toggle calls
        are conditional because each endpoint inverts its flag. Every 200 is decoded, every desired
        state is checked, and a final GET closes response-vs-persistence gaps.
        """
        function_path = f"/api/v1/functions/id/{function_id}"
        discovery = self._authed_request("GET", function_path)
        if discovery.status_code == httpx.codes.UNAUTHORIZED:
            phase = "create"
            write_path = "/api/v1/functions/create"
        elif discovery.status_code == httpx.codes.OK:
            self._checked_function_state(
                discovery,
                phase="discovery",
                function_id=function_id,
            )
            phase = "update"
            write_path = f"{function_path}/update"
        else:
            self._raise_status(discovery)

        payload: dict[str, object] = {
            "id": function_id,
            "name": name,
            "content": content,
            "meta": {"description": description},
        }
        state = self._checked_function_state(
            self._authed_request("POST", write_path, json_body=payload),
            phase=phase,
            function_id=function_id,
            content=content if phase == "update" else None,
        )
        self._require_state_field(
            condition=state.type == _FILTER_FUNCTION_TYPE,
            phase=phase,
            field="type",
        )
        if not state.is_active:
            toggle_path = f"{function_path}/toggle"
            state = self._checked_function_state(
                self._authed_request("POST", toggle_path),
                phase="active toggle",
                function_id=function_id,
                content=content,
            )
            self._require_state_field(
                condition=state.is_active,
                phase="active toggle",
                field="is_active",
            )
        if not state.is_global:
            toggle_path = f"{function_path}/toggle/global"
            state = self._checked_function_state(
                self._authed_request("POST", toggle_path),
                phase="global toggle",
                function_id=function_id,
                content=content,
            )
            self._require_state_field(
                condition=state.is_global,
                phase="global toggle",
                field="is_global",
            )

        final = self._checked_function_state(
            self._authed_request("GET", function_path),
            phase="final",
            function_id=function_id,
            content=content,
        )
        self._require_state_field(condition=final.is_active, phase="final", field="is_active")
        self._require_state_field(condition=final.is_global, phase="final", field="is_global")

    def _authed_request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, object] | None = None,
    ) -> httpx.Response:
        """Send one authenticated function request; normalize transport failures."""
        return self._request(
            method,
            path,
            headers=self._auth_headers(),
            json_body=json_body,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> httpx.Response:
        """Send one request and normalize a transport failure into the client error boundary."""
        try:
            return self._http.request(
                method,
                path,
                headers=headers,
                json=json_body,
            )
        except httpx.HTTPError as exc:
            msg = f"{method} {path} failed: {exc}"
            raise WebUIProvisionError(msg) from exc

    @classmethod
    def _checked_function_state(
        cls,
        response: httpx.Response,
        *,
        phase: str,
        function_id: str,
        content: str | None = None,
    ) -> _FunctionState:
        """Require HTTP 200 + a decodable owned-function state, optionally current filter source."""
        if response.status_code != httpx.codes.OK:
            cls._raise_status(response)
        try:
            state = msgspec.json.decode(response.content, type=_FunctionState)
        except (msgspec.DecodeError, UnicodeDecodeError) as exc:
            msg = f"{phase} returned invalid function state: {exc}"
            raise WebUIProvisionError(msg) from exc
        cls._require_state_field(condition=state.id == function_id, phase=phase, field="id")
        if content is not None:
            cls._require_state_field(
                condition=state.type == _FILTER_FUNCTION_TYPE,
                phase=phase,
                field="type",
            )
            cls._require_state_field(
                condition=state.content == content,
                phase=phase,
                field="content",
            )
        return state

    @staticmethod
    def _require_state_field(*, condition: bool, phase: str, field: str) -> None:
        """Raise one stable fail-closed error for an inexact function-state field."""
        if not condition:
            msg = f"{phase} function state mismatch: {field}"
            raise WebUIProvisionError(msg)

    @staticmethod
    def _raise_status(response: httpx.Response) -> Never:
        """Raise one stable fail-closed error for an unexpected function HTTP status."""
        request = response.request
        msg = f"{request.method} {request.url.path} returned HTTP {response.status_code}"
        raise WebUIProvisionError(msg)

    def _authed_get(self, path: str) -> bytes:
        """Authed GET that fails closed on non-200 -> the raw body for the caller to decode.

        Gates the readbacks the way authenticate() gates auth: a non-200 (401 on a stale/rejected
        token, 5xx upstream) raises WebUIProvisionError with path + status, so a broken readback
        surfaces LOUD instead of decoding an error body to an empty list (a silent ok=False). The
        readback endpoints are verified-user-gated (routers/tools.py, main.py get_verified_user), so
        a wrong/unverified principal lands here as a 401 rather than as filtered-empty data.
        """
        response = self._authed_request("GET", path)
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
