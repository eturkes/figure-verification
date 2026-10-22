# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q82 oracle: strict fakes of the nucllei APIs the tool calls, and a sandbox running the reader.

Each fake keeps the real signature (nucllei `v20261020-01`): `Files.get_file_by_id(id,
include_deleted=False)`, `Files.insert_new_file(user_id, form_data)` returning the record or
`None`, `FileForm` as a pydantic model, `Storage.get_file(path)`, `Storage.upload_file(file,
filename)`, `Chats.get_chat_by_id_and_user_id(id, user_id)`, `get_message_list(messages,
message_id)` (root first, cycle-safe), `sandbox_post(path, payload, timeout_s)` raising
`SandboxHTTPError(status, detail)`, `mark_error_kind(kind)` refusing an unknown kind,
`Rendered(text, kind, language=None, meta=None)`. The sandbox fake demands that the code it
receives is the wrapper of the expected program, byte for byte, then runs the real reader on it.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import BinaryIO, cast

import pytest
from pydantic import BaseModel

from nucllei_skill import run as jail
from verifier.figure.reader import run as read_figure

USER_ID = "user-owner"
OTHER_ID = "user-other"
CHAT_ID = "chat-1"
ASSISTANT_ID = "assistant-pending"
SANDBOX_URL = "http://sandbox:8000"
ERROR_KINDS = frozenset({"call", "failure", "outcome", "violation", "fatal"})


class SandboxHTTPError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"sandbox HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


@dataclass
class FileModel:
    id: str
    user_id: str
    filename: str
    path: str
    meta: dict[str, object] = field(default_factory=dict)
    data: dict[str, object] = field(default_factory=dict)


class FileForm(BaseModel):
    id: str
    hash: str | None = None
    filename: str
    path: str
    data: dict[str, object] = {}
    meta: dict[str, object] = {}


@dataclass
class ChatModel:
    chat: dict[str, object]


@dataclass
class Rendered:
    text: str
    kind: str
    language: str | None = None
    meta: dict[str, object] | None = None


Reply = Callable[[dict[str, object]], object]


@dataclass
class World:
    """One nucllei server's state as the tool can see it, and every effect the tool has."""

    root: Path
    program: str = ""
    files: dict[str, FileModel] = field(default_factory=dict)
    chats: dict[tuple[str, str], dict[str, object]] = field(default_factory=dict)
    sandbox_url: str = SANDBOX_URL
    reply: Reply | BaseException | None = None
    insert_none: bool = False
    result_cap: int = 65_536
    calls: list[tuple[str, dict[str, object], float]] = field(default_factory=list)
    displays: list[tuple[str, str]] = field(default_factory=list)
    marks: list[str] = field(default_factory=list)
    uploads: dict[str, bytes] = field(default_factory=dict)
    inserted: list[tuple[str, FileForm]] = field(default_factory=list)

    def attach(self, file_id: str, name: str, content: bytes, owner: str = USER_ID) -> None:
        path = self.root / f"{file_id}_{name}"
        path.write_bytes(content)
        self.files[file_id] = FileModel(file_id, owner, name, str(path))

    def display(self, content: str, kind: str = "markdown") -> None:
        self.displays.append((content, kind))


def ref(file_id: str, name: str) -> dict[str, object]:
    """One attachment item, as nucllei's frontend stores and sends it."""
    return {"type": "file", "id": file_id, "name": name, "file": {"id": file_id, "filename": name}}


def history(*turns: Mapping[str, object]) -> dict[str, object]:
    """A stored branch: each turn a message (role, content, optional files + meta), chained root
    first, ending in the pending assistant message `ASSISTANT_ID`."""
    messages: dict[str, dict[str, object]] = {}
    parent: str | None = None
    for index, turn in enumerate((*turns, {"role": "assistant", "content": ""})):
        message_id = ASSISTANT_ID if index == len(turns) else f"m{index}"
        messages[message_id] = {"id": message_id, "parentId": parent, **turn}
        parent = message_id
    return {"history": {"messages": messages, "currentId": ASSISTANT_ID}}


def _get_message_list(messages: Mapping[str, object], message_id: str) -> list[object] | None:
    current = messages.get(message_id)
    if not current:
        return None
    chain: list[object] = []
    visited = {message_id}
    while isinstance(current, dict):
        chain.append(current)
        parent_id = current.get("parentId")
        if not parent_id or parent_id in visited:
            break
        visited.add(parent_id)
        current = messages.get(parent_id)
    chain.reverse()
    return chain


def _module(monkeypatch: pytest.MonkeyPatch, name: str, **attrs: object) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    monkeypatch.setitem(sys.modules, name, module)
    parent, _, child = name.rpartition(".")
    if parent:
        setattr(sys.modules[parent], child, module)
    return module


def install(monkeypatch: pytest.MonkeyPatch, world: World) -> None:
    """Put the fakes where the tool's lazy imports find them."""

    async def sandbox_post(path: str, payload: dict[str, object], timeout_s: float) -> object:
        world.calls.append((path, payload, timeout_s))
        if isinstance(world.reply, BaseException):
            raise world.reply
        if world.reply is not None:
            return world.reply(payload)
        assert payload["code"] == jail.wrapper_code(world.program), "the program changed on its way"
        stdout = read_figure(world.program, None)
        return {
            "exit_code": 0,
            "timed_out": False,
            "duration_s": 1.0,
            "stdout": stdout,
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "cache_ttl_days": 30,
        }

    class Files:
        @staticmethod
        def get_file_by_id(id: str, include_deleted: bool = False) -> FileModel | None:  # noqa: A002, FBT001, FBT002
            assert include_deleted is False
            return world.files.get(id)

        @staticmethod
        def insert_new_file(user_id: str, form_data: FileForm) -> FileModel | None:
            assert isinstance(form_data, FileForm)
            world.inserted.append((user_id, form_data))
            if world.insert_none:
                return None
            return FileModel(form_data.id, user_id, form_data.filename, form_data.path)

    class Storage:
        @staticmethod
        def get_file(file_path: str) -> str:
            assert Path(file_path).is_file(), file_path
            return file_path

        @staticmethod
        def upload_file(file: BinaryIO, filename: str) -> tuple[bytes, str]:
            data = file.read()
            path = f"/data/uploads/{filename}"
            world.uploads[path] = data
            return data, path

    class Chats:
        @staticmethod
        def get_chat_by_id_and_user_id(id: str, user_id: str) -> ChatModel | None:  # noqa: A002
            found = world.chats.get((id, user_id))
            return None if found is None else ChatModel(found)

    def mark_error_kind(kind: str = "failure") -> None:
        if kind not in ERROR_KINDS or kind == "violation":
            msg = f"unknown result error kind: {kind!r}"
            raise ValueError(msg)
        world.marks.append(kind)

    for name in ("nucllei", "nucllei.builtin_tools", "nucllei.models", "nucllei.storage"):
        _module(monkeypatch, name)
    _module(monkeypatch, "nucllei.utils")
    _module(
        monkeypatch,
        "nucllei.builtin_tools.sandbox",
        SANDBOX_URL=world.sandbox_url,
        sandbox_post=sandbox_post,
        SandboxHTTPError=SandboxHTTPError,
    )
    _module(monkeypatch, "nucllei.models.files", Files=Files, FileForm=FileForm)
    _module(monkeypatch, "nucllei.models.chats", Chats=Chats)
    _module(monkeypatch, "nucllei.storage.provider", Storage=Storage)
    _module(monkeypatch, "nucllei.utils.misc", get_message_list=_get_message_list)
    _module(monkeypatch, "nucllei.env", TOOL_RESULT_MAX_CHARS=world.result_cap)
    _module(monkeypatch, "nucllei.utils.tool_output", mark_error_kind=mark_error_kind)
    _module(
        monkeypatch,
        "nucllei.utils.tool_render",
        Rendered=Rendered,
        Code=lambda language, base=str: base,  # noqa: ARG005 - the real one annotates for display
    )


def invoke(  # noqa: PLR0913 - every reserved argument a test varies
    world: World,
    *,
    note: object = "",
    user: object = None,
    messages: object = None,
    files: object = None,
    metadata: object = None,
    chat_id: object = CHAT_ID,
    message_id: object = ASSISTANT_ID,
    valves: Mapping[str, object] | None = None,
) -> object:
    """One `draw_figure` call through the repo's tool module, as nucllei makes it."""
    from nucllei_skill.tool import Tools  # noqa: PLC0415 - imported after the fakes

    tools = Tools()
    if valves is not None:
        tools.valves = tools.Valves.model_validate(dict(valves))
    return asyncio.run(
        tools.draw_figure(
            world.program,
            cast("str", note),
            __user__=cast("dict[str, object]", {"id": USER_ID} if user is None else user),
            __metadata__=cast("dict[str, object] | None", metadata),
            __messages__=cast("list[object] | None", messages),
            __files__=cast("list[object] | None", files),
            __chat_id__=cast("str | None", chat_id),
            __message_id__=cast("str | None", message_id),
            __display__=world.display,
        )
    )


def text_of(result: object) -> str:
    assert isinstance(result, Rendered), type(result)
    assert result.kind == "markdown"
    return result.text
