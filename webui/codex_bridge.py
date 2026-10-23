# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""OpenAI /v1 front over `codex app-server`: a ChatGPT-subscription model as Open WebUI's proposer.

The launcher's `--codex` arm serves this on the model port in place of model_backend. One chat
completion = one ephemeral app-server thread: the request's system text = the thread's base
instructions, its tools = dynamic tools, every other message = a raw Responses item injected before
an empty-input turn. So the model sees the request Open WebUI sent and nothing else (captured
against a mock Responses provider: the system text as one developer message, the tools as one
`functions` namespace, the messages verbatim; against the ChatGPT backend its `response.created`
echo lists that namespace alone with `instructions: null`). A dynamic tool call ends the completion
as one OpenAI `tool_calls` reply and interrupts the turn (no further sampling); Open WebUI runs the
tool and sends its result back as history.

Isolation: the child runs under its own CODEX_HOME (`BridgeSettings.home`, gitignored) with
`_CONFIG`, so the operator's ~/.codex (AGENTS.md, MCP servers, plugins, skills, memories) never
reaches the model. It logs in with the access token read from the operator's auth file, held in
memory alone (`chatgptAuthTokens`, which the protocol marks unstable): the bridge never writes that
file and never sends its refresh token, so the operator's own Codex login cannot rotate under it;
on a 401 the child asks for a fresh token and the bridge re-reads the file.

The untrusted proposer, like model_backend: the verifier judges the figure, whatever the model
wrote. Unshipped + coverage-excluded like the rest of webui/.
"""

import asyncio
import contextlib
import ipaddress
import json
import logging
import os
import shutil
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal, Self, cast
from urllib.parse import urlparse

import msgspec
import uvicorn
from litestar import Litestar, Request, Response, get, post
from litestar.datastructures import State
from litestar.response import Stream
from litestar.status_codes import HTTP_200_OK

from model_backend.origin import hosts, json_only
from webui.settings import Settings

_LOGGER = logging.getLogger(__name__)

# The catalog entry the child reads (`model_catalog_json`), the fields a real run needs. Codex's own
# entry serves gpt-6-luna with `tool_mode: code_mode_only` (every tool nested inside a JavaScript
# `exec` tool) + `multi_agent_version: v2` (spawn/send/wait tools + a role text); this one omits
# both, so a request's tools reach the model as plain functions, and `apply_patch_tool_type`, which
# makes codex-cli 0.164.0 offer a freeform `apply_patch` tool. `base_instructions: ""` = no
# developer message when a request carries no system text (an absent entry fails catalog parsing).
_LEVELS: Final = ("low", "medium", "high", "xhigh", "max")
_CATALOG: Final[dict[str, object]] = {
    "models": [
        {
            "slug": "gpt-6-luna",
            "display_name": "GPT-6-Luna",
            "description": "Fast and affordable model for easier tasks.",
            "default_reasoning_level": "medium",
            "supported_reasoning_levels": [
                {"effort": level, "description": level} for level in _LEVELS
            ],
            "shell_type": "unified_exec",
            "visibility": "list",
            "supported_in_api": True,
            "priority": 5,
            "context_window": 272000,
            "input_modalities": ["text", "image"],
            "truncation_policy": {"mode": "tokens", "limit": 10000},
            "support_verbosity": True,
            "default_verbosity": "low",
            "use_responses_lite": True,
            "web_search_tool_type": "text_and_image",
            "default_reasoning_summary": "none",
            "experimental_supported_tools": [],
            "base_instructions": "",
        }
    ]
}
_MODELS: Final = frozenset(
    cast("str", entry["slug"]) for entry in cast("list[dict[str, object]]", _CATALOG["models"])
)

# Every context layer + built-in tool Codex adds, off: environment (cwd, shell, date, timezone),
# sandbox + app + collaboration text, the code-mode `exec` wrapper, multi-agent tools, the shell,
# skills, plugins, apps, goals, image generation (the ChatGPT provider adds it; a mock provider
# does not), image viewing (codex-cli 0.164.0), request_user_input, web search, analytics. Each was
# seen in a captured request before its line here removed it.
_CONFIG: Final = (
    "include_environment_context=false",
    "include_permissions_instructions=false",
    "include_apps_instructions=false",
    "include_collaboration_mode_instructions=false",
    "features.code_mode_host=false",
    "features.multi_agent=false",
    "features.shell_tool=false",
    "features.unified_exec=false",
    "features.skill_search=false",
    "skills.bundled.enabled=false",
    "features.plugins=false",
    "features.apps=false",
    "features.goals=false",
    "features.image_generation=false",
    "features.view_image=false",
    "tools.experimental_request_user_input={enabled=false}",
    'web_search="disabled"',
    "analytics.enabled=false",
)
# `environments: []` = no environment access; `explicitRequestOnly` = no delegation text.
_THREAD: Final[dict[str, object]] = {
    "ephemeral": True,
    "sandbox": "read-only",
    "approvalPolicy": "never",
    "multiAgentMode": "explicitRequestOnly",
    "environments": [],
}
_TURN_TIMEOUT_S: Final = 600.0
_CALL_TIMEOUT_S: Final = 60.0
# JSON-RPC: the method this client does not serve (an approval, an elicitation, user input).
_NOT_SERVED: Final = -32601


class CodexError(Exception):
    """The app-server refused a call, failed a turn, or exited."""


class BridgeSettings(msgspec.Struct, frozen=True, kw_only=True):
    """The bridge's own inputs; `Settings` supplies the model id + bind URL."""

    codex_bin: str = "codex"
    auth_file: Path = Path.home() / ".codex" / "auth.json"
    home: Path = Path(".codex-bridge")
    # User: `low` in this repo. Empty = no effort sent = the model's own default (`medium`).
    effort: str = "low"
    # Measurement aid: each request body + its outcome, one JSON file per completion (what the
    # model saw: the inlet's rewrite, file context, tool spec). Empty = off.
    dump_dir: Path | None = None

    def __post_init__(self) -> None:
        if self.effort and self.effort not in _LEVELS:
            msg = f"CODEX_BRIDGE_EFFORT must be one of {', '.join(_LEVELS)}, got {self.effort!r}"
            raise ValueError(msg)

    @classmethod
    def from_env(cls) -> Self:
        """Build from CODEX_BRIDGE_* env vars, falling back to the field defaults."""
        env = os.environ
        default = cls()
        return cls(
            codex_bin=env.get("CODEX_BRIDGE_BIN", default.codex_bin),
            auth_file=Path(env.get("CODEX_BRIDGE_AUTH_FILE", str(default.auth_file))),
            home=Path(env.get("CODEX_BRIDGE_HOME", str(default.home))),
            effort=env.get("CODEX_BRIDGE_EFFORT", default.effort),
            dump_dir=Path(env["CODEX_BRIDGE_DUMP_DIR"])
            if env.get("CODEX_BRIDGE_DUMP_DIR")
            else None,
        )


# --- the OpenAI request Open WebUI sends (unknown fields tolerated, like model_backend) ---


class _Function(msgspec.Struct, frozen=True):
    name: str
    arguments: str = ""


class _ToolCall(msgspec.Struct, frozen=True):
    id: str
    function: _Function


class _Message(msgspec.Struct, frozen=True):
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[dict[str, object]] | None = None
    tool_calls: tuple[_ToolCall, ...] = ()
    tool_call_id: str | None = None


class _FunctionSpec(msgspec.Struct, frozen=True):
    name: str
    description: str = ""
    parameters: dict[str, object] = msgspec.field(default_factory=dict)


class _ToolSpec(msgspec.Struct, frozen=True):
    function: _FunctionSpec
    type: Literal["function"] = "function"


class ChatRequest(msgspec.Struct, frozen=True):
    """The fields of an OpenAI chat-completion request this bridge reads."""

    messages: tuple[_Message, ...]
    tools: tuple[_ToolSpec, ...] = ()
    stream: bool = False
    reasoning_effort: str | None = None


def _text(content: str | list[dict[str, object]] | None) -> str:
    """A message's text: a string, or its text parts joined (system + assistant messages)."""
    if content is None or isinstance(content, str):
        return content or ""
    return "".join(str(part.get("text", "")) for part in content if part.get("type") == "text")


def _input_parts(content: str | list[dict[str, object]] | None) -> list[dict[str, object]]:
    """User content as Responses input parts: text + images; any other part is refused."""
    if content is None or isinstance(content, str):
        return [{"type": "input_text", "text": content or ""}]
    parts: list[dict[str, object]] = []
    for part in content:
        kind = part.get("type")
        if kind in {"text", "input_text"}:
            parts.append({"type": "input_text", "text": str(part.get("text", ""))})
        elif kind in {"image_url", "input_image"}:
            image = part.get("image_url")
            url = image.get("url") if isinstance(image, dict) else image
            parts.append({"type": "input_image", "image_url": str(url)})
        else:
            msg = f"unsupported content part type {kind!r}"
            raise ValueError(msg)
    return parts


def instructions(messages: tuple[_Message, ...]) -> str:
    """The thread's base instructions: every system/developer text, in order."""
    return "\n\n".join(
        _text(message.content) for message in messages if message.role in {"system", "developer"}
    )


def history(messages: tuple[_Message, ...]) -> list[dict[str, object]]:
    """Every non-system message as the raw Responses item(s) the model reads."""
    items: list[dict[str, object]] = []
    for message in messages:
        if message.role == "user":
            items.append(
                {"type": "message", "role": "user", "content": _input_parts(message.content)}
            )
        elif message.role == "assistant":
            if text := _text(message.content):
                items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": text}],
                    }
                )
            items.extend(
                {
                    "type": "function_call",
                    "call_id": call.id,
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                }
                for call in message.tool_calls
            )
        elif message.role == "tool":
            output: object = (
                message.content
                if message.content is None or isinstance(message.content, str)
                else _input_parts(message.content)
            )
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.tool_call_id or "",
                    "output": output or "",
                }
            )
    return items


def dynamic_tools(tools: tuple[_ToolSpec, ...]) -> list[dict[str, object]]:
    """The request's function tools as app-server dynamic tools."""
    return [
        {
            "type": "function",
            "name": tool.function.name,
            "description": tool.function.description,
            "inputSchema": tool.function.parameters or {"type": "object", "properties": {}},
        }
        for tool in tools
    ]


# --- the app-server child ---


@dataclass
class _Thread:
    """Events of one thread: notifications + the server requests that name it."""

    events: asyncio.Queue[dict[str, object]] = field(default_factory=asyncio.Queue)


def _tokens(auth_file: Path) -> dict[str, object]:
    """The access token + account id of the operator's Codex login (read-only)."""
    tokens = cast("dict[str, str]", json.loads(auth_file.read_text(encoding="utf-8"))["tokens"])
    return {"accessToken": tokens["access_token"], "chatgptAccountId": tokens["account_id"]}


class Codex:
    """One `codex app-server` over stdio JSON-RPC, shared by every completion."""

    def __init__(self, settings: BridgeSettings, on_exit: Callable[[], None]) -> None:
        self._settings = settings
        self._on_exit = on_exit
        self._process: asyncio.subprocess.Process | None = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, object]]] = {}
        self._threads: dict[str, _Thread] = {}
        self._reader: asyncio.Task[None] | None = None
        self._stopping = False
        self._alive = False

    async def start(self) -> None:
        """Spawn the child under its own CODEX_HOME, initialize, log in."""
        if shutil.which(self._settings.codex_bin) is None:
            msg = f"{self._settings.codex_bin!r} not found: install Codex, or set CODEX_BRIDGE_BIN"
            raise CodexError(msg)
        if not self._settings.auth_file.is_file():
            msg = (
                f"{self._settings.auth_file} not found: sign in with `codex login` (ChatGPT), "
                "or set CODEX_BRIDGE_AUTH_FILE"
            )
            raise CodexError(msg)
        home = self._settings.home.resolve()
        home.mkdir(parents=True, exist_ok=True)
        catalog = home / "catalog.json"
        catalog.write_text(json.dumps(_CATALOG), encoding="utf-8")
        argv = [self._settings.codex_bin, "app-server"]
        for override in (*_CONFIG, f"model_catalog_json={json.dumps(str(catalog))}"):
            argv += ["-c", override]
        # HOME too: Codex reads user-level skills + agents files from it.
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home), "CODEX_HOME": str(home)}
        self._process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            env=env,
            cwd=home,
            limit=64 * 1024 * 1024,
        )
        self._alive = True
        self._reader = asyncio.create_task(self._read())
        await self.call(
            "initialize",
            {
                "clientInfo": {"name": "figure-verification-bridge", "version": "1"},
                "capabilities": {"experimentalApi": True},
            },
        )
        self._send({"method": "initialized", "params": {}})
        await self.call(
            "account/login/start",
            {"type": "chatgptAuthTokens", **_tokens(self._settings.auth_file)},
        )

    async def stop(self) -> None:
        """Terminate the child; every waiter fails."""
        self._stopping = True
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._process.wait(), 10)
        if self._reader is not None:
            self._reader.cancel()

    def _send(self, message: dict[str, object]) -> None:
        process = self._process
        if process is None or process.stdin is None or not self._alive:
            msg = "codex app-server is not running"
            raise CodexError(msg)
        process.stdin.write(json.dumps(message).encode() + b"\n")

    def send(self, method: str, params: dict[str, object]) -> Awaitable[dict[str, object]]:
        """Write one JSON-RPC request NOW; await the returned result (`CodexError` on refusal)."""
        self._next_id += 1
        ident = self._next_id
        future: asyncio.Future[dict[str, object]] = asyncio.get_running_loop().create_future()
        self._pending[ident] = future
        try:
            self._send({"id": ident, "method": method, "params": params})
        except CodexError:
            self._pending.pop(ident, None)
            raise

        async def result() -> dict[str, object]:
            try:
                return await asyncio.wait_for(future, _CALL_TIMEOUT_S)
            finally:
                self._pending.pop(ident, None)

        return result()

    async def call(self, method: str, params: dict[str, object]) -> dict[str, object]:
        """One JSON-RPC request; the result, else `CodexError` naming the server's message."""
        return await self.send(method, params)

    def reply(self, ident: object, result: dict[str, object]) -> None:
        """Answer one server request."""
        self._send({"id": ident, "result": result})

    @property
    def cwd(self) -> str:
        """Every thread's working directory: the child's own home (no environment access)."""
        return str(self._settings.home.resolve())

    def open_thread(self, thread_id: str) -> _Thread:
        """Route this thread's events to a fresh queue."""
        thread = self._threads[thread_id] = _Thread()
        return thread

    def close_thread(self, thread_id: str) -> None:
        """Stop routing this thread's events."""
        self._threads.pop(thread_id, None)

    async def _read(self) -> None:
        process = cast("asyncio.subprocess.Process", self._process)
        stdout = cast("asyncio.StreamReader", process.stdout)
        try:
            while line := await stdout.readline():
                # One bad message must not end the routing of every other thread.
                try:
                    self._dispatch(cast("dict[str, object]", json.loads(line)))
                except (ValueError, CodexError, OSError, KeyError, TypeError):
                    _LOGGER.exception("dropped app-server message bytes=%d", len(line))
        finally:
            self._alive = False
            failure = CodexError("codex app-server exited")
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(failure)
            for thread in self._threads.values():
                thread.events.put_nowait({"method": "bridge/exited", "params": {}})
            if not self._stopping:
                _LOGGER.error("codex app-server exited rc=%s", process.returncode)
                self._on_exit()

    def _dispatch(self, message: dict[str, object]) -> None:
        method = message.get("method")
        params = cast("dict[str, object]", message.get("params") or {})
        if method is None:
            future = self._pending.get(cast("int", message.get("id")))
            if future is not None and not future.done():
                error = message.get("error")
                if error is not None:
                    detail = cast("dict[str, object]", error).get("message", error)
                    future.set_exception(CodexError(str(detail)))
                else:
                    future.set_result(cast("dict[str, object]", message.get("result") or {}))
            return
        if "id" in message:
            self._serve(message, cast("str", method), params)
            return
        thread = self._threads.get(str(params.get("threadId")))
        if thread is not None:
            thread.events.put_nowait(message)

    def _serve(self, message: dict[str, object], method: str, params: dict[str, object]) -> None:
        ident = message["id"]
        if method == "account/chatgptAuthTokens/refresh":
            try:
                tokens = _tokens(self._settings.auth_file)
            except (OSError, ValueError, KeyError, TypeError):
                _LOGGER.exception("token refresh: %s unreadable", self._settings.auth_file)
                self._send({"id": ident, "error": {"code": _NOT_SERVED, "message": "no token"}})
            else:
                self.reply(ident, tokens)
        elif method == "currentTime/read":
            self.reply(ident, {"currentTimeAt": int(time.time())})
        elif method == "item/tool/call" and str(params.get("threadId")) in self._threads:
            self._threads[str(params["threadId"])].events.put_nowait(message)
        else:
            _LOGGER.warning("declined app-server request method=%s", method)
            self._send({"id": ident, "error": {"code": _NOT_SERVED, "message": "not served"}})


# --- one completion ---


@dataclass
class Outcome:
    """What one turn produced: the model's text, its first tool call, token usage."""

    text: str
    call: tuple[str, str, str] | None  # (call id, tool name, JSON arguments)
    usage: dict[str, int]


def _usage(params: dict[str, object]) -> dict[str, int]:
    total = cast("dict[str, dict[str, int]]", params.get("tokenUsage") or {}).get("total", {})
    prompt, completion = total.get("inputTokens", 0), total.get("outputTokens", 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


async def complete(codex: Codex, request: ChatRequest, model: str, effort: str) -> Outcome:
    """Run the request as one ephemeral thread; stop at the first tool call."""
    started = await codex.call(
        "thread/start",
        {
            **_THREAD,
            "model": model,
            "baseInstructions": instructions(request.messages),
            "dynamicTools": dynamic_tools(request.tools),
            "cwd": codex.cwd,
        },
    )
    thread_id = str(cast("dict[str, object]", started["thread"])["id"])
    thread = codex.open_thread(thread_id)
    try:
        await codex.call(
            "thread/inject_items", {"threadId": thread_id, "items": history(request.messages)}
        )
        turn: dict[str, object] = {"threadId": thread_id, "input": []}
        if effort:
            turn["effort"] = effort
        await codex.call("turn/start", turn)
        return await asyncio.wait_for(_drain(codex, thread), _TURN_TIMEOUT_S)
    finally:
        codex.close_thread(thread_id)
        with contextlib.suppress(CodexError, TimeoutError):
            await codex.call("thread/unsubscribe", {"threadId": thread_id})


async def _drain(codex: Codex, thread: _Thread) -> Outcome:
    texts: list[str] = []
    call: tuple[str, str, str] | None = None
    usage: dict[str, int] = {}
    failure = ""
    while True:
        event = await thread.events.get()
        method = event.get("method")
        params = cast("dict[str, object]", event.get("params") or {})
        if method == "item/tool/call":
            if call is None:
                call = (
                    str(params["callId"]),
                    str(params["tool"]),
                    json.dumps(params.get("arguments"), ensure_ascii=False),
                )
                # The interrupt is on the wire before the answer, so the model never samples on.
                interrupt = codex.send(
                    "turn/interrupt", {"threadId": params["threadId"], "turnId": params["turnId"]}
                )
                codex.reply(
                    event["id"],
                    {"contentItems": [{"type": "inputText", "text": "stopped"}], "success": False},
                )
                with contextlib.suppress(CodexError, TimeoutError):
                    await interrupt
            else:
                codex.reply(event["id"], {"contentItems": [], "success": False})
        elif method == "item/completed":
            item = cast("dict[str, object]", params.get("item") or {})
            if item.get("type") == "agentMessage" and call is None:
                texts.append(str(item.get("text", "")))
        elif method == "thread/tokenUsage/updated":
            usage = _usage(params)
        elif method == "error" and not params.get("willRetry"):
            failure = str(cast("dict[str, object]", params.get("error") or {}).get("message"))
        elif method == "bridge/exited":
            msg = "codex app-server exited"
            raise CodexError(msg)
        elif method == "turn/completed":
            turn = cast("dict[str, object]", params.get("turn") or {})
            status = turn.get("status")
            if status == "completed" or (status == "interrupted" and call is not None):
                return Outcome("\n\n".join(texts), call, usage)
            error = cast("dict[str, object]", turn.get("error") or {}).get("message")
            msg = f"turn {status}: {error or failure or 'no cause reported'}"
            raise CodexError(msg)


# --- the OpenAI wire ---


def _message(outcome: Outcome) -> dict[str, object]:
    message: dict[str, object] = {"role": "assistant", "content": outcome.text or None}
    if outcome.call is not None:
        call_id, name, arguments = outcome.call
        message["tool_calls"] = [
            {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}
        ]
    return message


def _finish(outcome: Outcome) -> str:
    return "stop" if outcome.call is None else "tool_calls"


def completion(outcome: Outcome, model: str) -> dict[str, object]:
    """A non-streaming chat.completion body."""
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": _message(outcome), "finish_reason": _finish(outcome)}],
        **({"usage": outcome.usage} if outcome.usage else {}),
    }


def chunks(outcome: Outcome, model: str) -> list[bytes]:
    """The SSE events of a streamed reply: role, text, tool call, finish + usage, [DONE]."""
    base = {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
    }
    deltas: list[dict[str, object]] = [{"role": "assistant", "content": ""}]
    if outcome.text:
        deltas.append({"content": outcome.text})
    if outcome.call is not None:
        call_id, name, arguments = outcome.call
        deltas.append(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": arguments},
                    }
                ]
            }
        )
    events = [
        {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
        for delta in deltas
    ]
    final: dict[str, object] = {
        **base,
        "choices": [{"index": 0, "delta": {}, "finish_reason": _finish(outcome)}],
    }
    if outcome.usage:
        final["usage"] = outcome.usage
    events.append(final)
    return [f"data: {json.dumps(event)}\n\n".encode() for event in events] + [b"data: [DONE]\n\n"]


def _error(status: int, message: str, kind: str) -> Response[dict[str, object]]:
    return Response({"error": {"message": message, "type": kind}}, status_code=status)


@get("/v1/models", sync_to_thread=False)
def list_models(state: State) -> dict[str, object]:
    """The one served model (OpenAI /v1/models shape)."""
    return {
        "object": "list",
        "data": [{"id": state["model"], "object": "model", "created": 0, "owned_by": "openai"}],
    }


@post("/v1/chat/completions", status_code=HTTP_200_OK, before_request=json_only)
async def chat_completions(
    request: Request[object, object, State], state: State
) -> Response[object]:
    """Run one completion through the app-server; reply whole (SSE when `stream`). A non-JSON body
    never gets here (`json_only`, M23.1 F2)."""
    raw = await request.body()
    try:
        body = msgspec.json.decode(raw, type=ChatRequest)
        history(body.messages)  # refuse an unsupported content part before any thread exists
    except (msgspec.ValidationError, msgspec.DecodeError, ValueError) as exc:
        return cast("Response[object]", _error(400, str(exc), "invalid_request_error"))
    effort = body.reasoning_effort or cast("str", state["effort"])
    if effort and effort not in _LEVELS:
        return cast(
            "Response[object]", _error(400, f"unknown effort {effort!r}", "invalid_request_error")
        )
    model = cast("str", state["model"])
    ident = uuid.uuid4().hex[:12]
    began = time.monotonic()
    try:
        outcome = await complete(cast("Codex", state["codex"]), body, model, effort)
    except (CodexError, TimeoutError) as exc:
        _LOGGER.exception("completion id=%s failed seconds=%.1f", ident, time.monotonic() - began)
        return cast("Response[object]", _error(502, f"codex: {exc}", "codex_error"))
    _LOGGER.info(
        "completion id=%s finish=%s tool=%s seconds=%.1f prompt_tokens=%d completion_tokens=%d",
        ident,
        _finish(outcome),
        outcome.call[1] if outcome.call else "-",
        time.monotonic() - began,
        outcome.usage.get("prompt_tokens", 0),
        outcome.usage.get("completion_tokens", 0),
    )
    dump_dir = cast("Path | None", state["dump_dir"])
    if dump_dir is not None:
        dump_dir.mkdir(parents=True, exist_ok=True)
        record = {"request": json.loads(raw), "text": outcome.text, "call": outcome.call}
        (dump_dir / f"{time.strftime('%Y%m%dT%H%M%S')}-{ident}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    if body.stream:
        events = chunks(outcome, model)

        async def emit() -> AsyncIterator[bytes]:
            for event in events:
                yield event

        return cast("Response[object]", Stream(emit(), media_type="text/event-stream"))
    return Response(completion(outcome, model))


def create_app(
    model: str, bridge: BridgeSettings, on_exit: Callable[[], None], *, allowed: tuple[str, ...]
) -> Litestar:
    """The bridge app, answering the `allowed` Host headers alone; the child starts with the app
    and stops with it."""
    if model not in _MODELS:
        msg = f"the codex bridge serves {', '.join(sorted(_MODELS))}, not {model!r}"
        raise ValueError(msg)
    codex = Codex(bridge, on_exit)

    async def startup() -> None:
        await codex.start()
        _LOGGER.info("codex app-server ready model=%s effort=%s", model, bridge.effort or "default")

    async def shutdown() -> None:
        await codex.stop()

    return Litestar(
        route_handlers=[list_models, chat_completions],
        state=State(
            {"model": model, "effort": bridge.effort, "codex": codex, "dump_dir": bridge.dump_dir}
        ),
        on_startup=[startup],
        on_shutdown=[shutdown],
        openapi_config=None,
        allowed_hosts=list(allowed),
    )


def _loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


def serve(settings: Settings) -> None:
    """Serve the bridge at settings.model_backend_url (http://<host>:<port>/v1, one worker)."""
    parsed = urlparse(settings.model_backend_url)
    if parsed.scheme != "http" or parsed.hostname is None or parsed.port is None:
        msg = (
            f"model_backend_url must be http://<host>:<port>/v1, got {settings.model_backend_url!r}"
        )
        raise ValueError(msg)
    # The bridge authenticates no caller and spends the operator's subscription: loopback alone.
    if not _loopback(parsed.hostname):
        msg = f"the codex bridge binds loopback alone, got {parsed.hostname!r}"
        raise ValueError(msg)
    holder: list[uvicorn.Server] = []

    def on_exit() -> None:
        # The child died: end the bridge too, so the launcher sees the model tier exit.
        for server in holder:
            server.should_exit = True

    allowed = hosts(parsed.hostname, parsed.port)
    app = create_app(settings.model_id, BridgeSettings.from_env(), on_exit, allowed=allowed)
    server = uvicorn.Server(uvicorn.Config(app, host=parsed.hostname, port=parsed.port, workers=1))
    holder.append(server)
    server.run()
