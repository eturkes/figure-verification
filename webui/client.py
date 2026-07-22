# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Provisioning and persisted-chat REST client for Open WebUI (M4.3b, M4.4b, M6.2).

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
import uuid
from typing import NamedTuple, Never
from urllib.parse import quote

import httpx
import msgspec

from webui.settings import Settings

# OWUI names every tool-SERVER group "server:<info.id>" (routers/tools.py); the prefix tells a
# server tool from a python-function tool in the GET /api/v1/tools/ readback. bootstrap reuses it.
_TOOL_SERVER_ID_PREFIX = "server:"

_FILTER_FUNCTION_TYPE = "filter"

# Seconds between GET /ready polls while OWUI finishes startup (cold boot ~7-10s here, memory M4).
_READY_POLL_INTERVAL = 1.0

# Seconds between persisted-chat readbacks while the background completion runs.
_CHAT_POLL_INTERVAL = 1.0


class WebUIProvisionError(RuntimeError):
    """An Open WebUI client step failed unrecoverably or returned an invalid state."""


class PersistedChatResult(NamedTuple):
    """Final persisted assistant text and optional verified-chart embed URL."""

    final_text: str
    chart_url: str | None


class _AuthResponse(msgspec.Struct):
    """Loose OWUI signup/signin reply; only the JWT is load-bearing (empty default => we raise)."""

    token: str = ""


class _Model(msgspec.Struct):
    """One entry of the GET /api/models `data` envelope; only the id is read."""

    id: str


class _ModelsEnvelope(msgspec.Struct):
    """GET /api/models body: a `{data: [...]}` envelope (default empty => enumerated-none)."""

    data: tuple[_Model, ...] = ()


class _ModelConfig(msgspec.Struct):
    """Loose GET /api/v1/models/model reply: only fields needed to converge the model's tool list.

    ``meta``/``params`` stay raw mappings so an update preserves operator-set keys while adding the
    verifier tool id; Open WebUI stores default tool ids at ``meta.toolIds`` (read by the browser
    frontend Chat.svelte, never auto-resolved by the chat backend -- utils/automations.py).
    """

    id: str = ""
    base_model_id: str | None = None
    name: str = ""
    params: dict[str, object] = msgspec.field(default_factory=dict)
    meta: dict[str, object] = msgspec.field(default_factory=dict)
    is_active: bool = True


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


class _CreatedChat(msgspec.Struct):
    """Loose POST /api/v1/chats/new reply; only the top-level chat id is read."""

    id: str = ""


class _CompletionAck(msgspec.Struct):
    """Loose background-completion acknowledgement; only acceptance is load-bearing."""

    status: bool = False


class _OutputText(msgspec.Struct):
    """One persisted assistant content item; only final text is read."""

    text: str = ""


class _AssistantOutput(msgspec.Struct):
    """One persisted assistant output item; only its content list is read."""

    content: tuple[_OutputText, ...] = ()


class _ChatMessage(msgspec.Struct):
    """Loose persisted message; user entries decode through defaults and are ignored."""

    done: bool = False
    embeds: tuple[str, ...] = ()
    output: tuple[_AssistantOutput, ...] = ()


class _ChatHistory(msgspec.Struct):
    """Persisted history keyed by message id."""

    messages: dict[str, _ChatMessage] = msgspec.field(default_factory=dict)


class _ChatBody(msgspec.Struct):
    """The nested chat body containing persisted history."""

    history: _ChatHistory = msgspec.field(default_factory=_ChatHistory)


class _ChatResponse(msgspec.Struct):
    """Loose GET /api/v1/chats/{id} reply; only chat.history is read."""

    chat: _ChatBody = msgspec.field(default_factory=_ChatBody)


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

    def model_tool_ids(self, model_id: str) -> list[str]:
        """Authed GET the workspace model config -> its default tool ids (``meta.toolIds``).

        A model with no workspace config row (Open WebUI 404) has no attached tools -> ``[]``; any
        other non-200 fails closed loudly, like the other readbacks.
        """
        path = f"/api/v1/models/model?id={quote(model_id, safe='')}"
        response = self._authed_request("GET", path)
        if response.status_code == httpx.codes.NOT_FOUND:
            return []
        config = self._decode_model_config(response, phase="model tool readback")
        return self._meta_tool_ids(config.meta)

    def ensure_model_tool(self, *, model_id: str, tool_id: str) -> None:
        """Attach one tool id to the model's default tool list so the browser auto-offers it.

        Open WebUI lists a global tool server (``server:<id>``) as *available* but never
        auto-attaches it to a chat: the chat backend resolves tools only from the request's
        ``tool_ids`` (utils/middleware.py), while the browser frontend (Chat.svelte) pre-selects a
        model's ``info.meta.toolIds`` (utils/automations.py notes the backend never resolves them).
        So without this step a browser chat is never offered the verifier and the operator must
        toggle it by hand. This converges the workspace model config for ``model_id`` so
        ``meta.toolIds`` carries ``tool_id`` -- create when no config row exists (Open WebUI reports
        that GET as 404), else a non-destructive update preserving ``params`` and any other ``meta``
        keys -- then a final GET proves the attach persisted. Idempotent: a config already carrying
        ``tool_id`` makes no write.
        """
        config_path = f"/api/v1/models/model?id={quote(model_id, safe='')}"
        discovery = self._authed_request("GET", config_path)
        payload: dict[str, object]
        if discovery.status_code == httpx.codes.NOT_FOUND:
            payload = {
                "id": model_id,
                "base_model_id": None,
                "name": model_id,
                "meta": {"toolIds": [tool_id]},
                "params": {},
                "is_active": True,
            }
            write_path = "/api/v1/models/create"
            phase = "model create"
        elif discovery.status_code == httpx.codes.OK:
            config = self._decode_model_config(discovery, phase="model discovery")
            tool_ids = self._meta_tool_ids(config.meta)
            if tool_id in tool_ids:
                return  # already attached: no write, fully idempotent
            payload = {
                "id": model_id,
                "base_model_id": config.base_model_id,
                "name": config.name or model_id,
                "meta": {**config.meta, "toolIds": [*tool_ids, tool_id]},
                "params": config.params,
                "is_active": config.is_active,
            }
            write_path = "/api/v1/models/model/update"
            phase = "model update"
        else:
            self._raise_status(discovery)
        self._decode_model_config(
            self._authed_request("POST", write_path, json_body=payload),
            phase=phase,
        )
        final = self._decode_model_config(
            self._authed_request("GET", config_path),
            phase="model tool verify",
        )
        if tool_id not in self._meta_tool_ids(final.meta):
            msg = f"model {model_id!r} tool did not persist: {tool_id!r} absent from toolIds"
            raise WebUIProvisionError(msg)

    def run_persisted_chat(self, prompt: str) -> PersistedChatResult:
        """Run one background persisted chat and return its final text plus chart URL.

        The client must already be authenticated. The background completion is bounded by
        ``settings.ready_timeout``: the harness reuses its existing Open WebUI operation-wait budget
        and a monotonic deadline rather than introducing a second operator timeout.
        """
        chat_id = self._create_chat()
        session_id = str(uuid.uuid4())
        assistant_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        self._post_chat_completion(
            prompt=prompt,
            chat_id=chat_id,
            session_id=session_id,
            assistant_id=assistant_id,
            user_id=user_id,
        )
        return self._poll_persisted_chat(chat_id=chat_id, assistant_id=assistant_id)

    def _create_chat(self) -> str:
        """Create the empty persisted chat container and return its top-level id."""
        path = "/api/v1/chats/new"
        response = self._authed_request(
            "POST",
            path,
            json_body={
                "chat": {
                    "models": [self._settings.model_id],
                    "messages": [],
                    "history": {"messages": {}, "currentId": None},
                }
            },
        )
        if response.status_code != httpx.codes.OK:
            self._raise_status(response)
        try:
            chat_id = msgspec.json.decode(response.content, type=_CreatedChat).id
        except (msgspec.DecodeError, UnicodeDecodeError) as exc:
            msg = f"POST {path} returned an invalid response: {exc}"
            raise WebUIProvisionError(msg) from exc
        if not chat_id:
            msg = f"POST {path} returned an empty chat id"
            raise WebUIProvisionError(msg)
        return chat_id

    def _post_chat_completion(
        self,
        *,
        prompt: str,
        chat_id: str,
        session_id: str,
        assistant_id: str,
        user_id: str,
    ) -> None:
        """Start the persisted background completion with OWUI's exact 0.10.2 wire shape."""
        path = "/api/chat/completions"
        response = self._authed_request(
            "POST",
            path,
            json_body={
                "model": self._settings.model_id,
                "stream": False,
                "tool_ids": [f"{_TOOL_SERVER_ID_PREFIX}{self._settings.tool_server_id}"],
                "chat_id": chat_id,
                "session_id": session_id,
                "id": assistant_id,
                "parent_id": None,
                "messages": [{"role": "user", "content": prompt}],
                "user_message": {
                    "id": user_id,
                    "role": "user",
                    "content": prompt,
                    "timestamp": int(time.time()),
                    "parentId": None,
                    "childrenIds": [assistant_id],
                },
            },
        )
        if response.status_code != httpx.codes.OK:
            self._raise_status(response)
        try:
            acknowledged = msgspec.json.decode(response.content, type=_CompletionAck).status
        except (msgspec.DecodeError, UnicodeDecodeError) as exc:
            msg = f"POST {path} returned an invalid response: {exc}"
            raise WebUIProvisionError(msg) from exc
        if not acknowledged:
            msg = f"POST {path} did not acknowledge the background completion"
            raise WebUIProvisionError(msg)

    def _poll_persisted_chat(
        self,
        *,
        chat_id: str,
        assistant_id: str,
    ) -> PersistedChatResult:
        """Poll the persisted chat until the named assistant message reports done."""
        path = f"/api/v1/chats/{chat_id}"
        deadline = time.monotonic() + self._settings.ready_timeout
        while True:
            body = self._authed_get(path)
            try:
                chat = msgspec.json.decode(body, type=_ChatResponse)
            except (msgspec.DecodeError, UnicodeDecodeError) as exc:
                msg = f"GET {path} returned an invalid response: {exc}"
                raise WebUIProvisionError(msg) from exc
            assistant = chat.chat.history.messages.get(assistant_id)
            if assistant is not None and assistant.done:
                return self._completed_chat_result(assistant)
            if time.monotonic() >= deadline:
                msg = f"persisted chat did not complete after {self._settings.ready_timeout}s"
                raise WebUIProvisionError(msg)
            time.sleep(_CHAT_POLL_INTERVAL)

    @staticmethod
    def _completed_chat_result(message: _ChatMessage) -> PersistedChatResult:
        """Extract the fail-closed final text and optional first embed from a done message."""
        if not message.output or not message.output[0].content:
            msg = "completed assistant message returned no final text"
            raise WebUIProvisionError(msg)
        final_text = message.output[0].content[0].text
        if not final_text:
            msg = "completed assistant message returned no final text"
            raise WebUIProvisionError(msg)
        chart_url = message.embeds[0] if message.embeds else None
        return PersistedChatResult(final_text=final_text, chart_url=chart_url)

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
        """Send one authenticated request; normalize transport failures."""
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

    def _decode_model_config(
        self,
        response: httpx.Response,
        *,
        phase: str,
    ) -> _ModelConfig:
        """Require HTTP 200 + decodable workspace model config, else fail closed."""
        if response.status_code != httpx.codes.OK:
            self._raise_status(response)
        try:
            return msgspec.json.decode(response.content, type=_ModelConfig)
        except (msgspec.DecodeError, UnicodeDecodeError) as exc:
            msg = f"{phase} returned invalid model config: {exc}"
            raise WebUIProvisionError(msg) from exc

    @staticmethod
    def _meta_tool_ids(meta: dict[str, object]) -> list[str]:
        """Return string ids from ``meta.toolIds``; defensively drop other shapes and entries."""
        raw = meta.get("toolIds")
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, str)]

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
        """Raise one stable fail-closed error for an unexpected authenticated HTTP status."""
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
