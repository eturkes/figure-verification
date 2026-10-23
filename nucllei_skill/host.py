# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The nucllei server's own APIs, the tool's one door into them.

Every import of `nucllei` sits inside a function: the module loads anywhere, and on the server
each call reaches the live API. Each function projects what it reads into plain values, so no
nucllei object leaves this module. Signatures are those of nucllei `v20261020-01`:
`Files.get_file_by_id(id)` + its `user_id` (the owner check nucllei's own sandbox tool makes),
`Storage.get_file(path) -> local path`, `Storage.upload_file(file, filename) -> (bytes, path)`,
`Files.insert_new_file(user_id, FileForm)`, `Chats.get_chat_by_id_and_user_id(id, user_id)`,
`utils.misc.get_message_list(messages, message_id)`, `builtin_tools.sandbox.sandbox_post(path,
payload, timeout_s)`.
"""

import io
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from verifier.pysrc.limits import DEFAULT_LIMITS

# The judge refuses a larger file from its length alone, so no upload enters memory whole.
_READ_BYTES = DEFAULT_LIMITS.max_csv_bytes + 1
# nucllei's default `TOOL_RESULT_MAX_CHARS`.
_RESULT_CAP = 65_536


@dataclass(frozen=True, slots=True)
class Attachment:
    """One owned attachment: its sandbox file name and its first `_READ_BYTES` bytes."""

    name: str
    content: bytes


class SandboxRefusedError(RuntimeError):
    """The sandbox answered with an HTTP error status."""


def python_code() -> object:
    """The program argument's type: nucllei shows it as highlighted Python in the tool block
    (README_API §5.4); plain `str` where nucllei is absent."""
    try:
        from nucllei.utils.tool_render import Code  # noqa: PLC0415 - see the module docstring
    except Exception:
        return str
    return Code("python")


def sandbox_configured() -> bool:
    """nucllei's own gate for its sandbox tool: a non-empty `SANDBOX_URL`."""
    from nucllei.builtin_tools import sandbox  # noqa: PLC0415 - see the module docstring

    return bool(sandbox.SANDBOX_URL)


async def sandbox_call(path: str, payload: dict[str, object], timeout_s: float) -> object:
    """One POST (`/files/write`, `/exec`) through nucllei's single sandbox exit, which carries
    `SANDBOX_TOKEN`."""
    from nucllei.builtin_tools import sandbox  # noqa: PLC0415 - see the module docstring

    try:
        return await sandbox.sandbox_post(path, payload, timeout_s)
    except sandbox.SandboxHTTPError as error:
        raise SandboxRefusedError(str(error.status)) from error


def _head(path: str, limit: int) -> bytes:
    with Path(path).open("rb") as handle:
        return handle.read(limit)


def message_text(content: object) -> str | None:
    """A message's text: a `str`, or the text parts of a content list joined by a line break."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            part["text"]
            for part in content
            if isinstance(part, Mapping)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
        ]
        return "\n".join(parts) if parts else None
    return None


def _refs(items: object) -> list[tuple[str, str | None]]:
    """`(file_id, name)` per attachment item, each id once, first place kept: the top-level `id`,
    else `file.id`; the top-level `name`, else `file.filename`, else `file.meta.name` (nucllei's
    own reading, `builtin_tools/sandbox.py::_iter_context_files`)."""
    refs: dict[str, str | None] = {}
    for item in items if isinstance(items, list | tuple) else ():
        if not isinstance(item, Mapping):
            continue
        inner = item.get("file")
        inner = inner if isinstance(inner, Mapping) else {}
        meta = inner.get("meta")
        file_id = item.get("id") or inner.get("id")
        name = (
            item.get("name")
            or inner.get("filename")
            or (meta.get("name") if isinstance(meta, Mapping) else None)
        )
        if isinstance(file_id, str) and file_id and file_id not in refs:
            refs[file_id] = name if isinstance(name, str) and name else None
    return list(refs.items())


def request_refs(files: object, metadata: object) -> list[tuple[str, str | None]]:
    """The request body's attachment refs: `__files__`, else `__metadata__["files"]`. An inlet
    may have removed refs from both (llens `large_file_gate` drops an oversize file)."""
    found = files or (metadata.get("files") if isinstance(metadata, Mapping) else None)
    return _refs(found)


@dataclass(frozen=True, slots=True)
class Branch:
    """The human side of the caller's stored chat branch: the user's own messages, oldest first,
    and the files attached to them."""

    texts: tuple[str, ...]
    refs: tuple[tuple[str, str | None], ...]
    latest: str | None  # the last human message's text: `""` or `None` for one with no text


def _human(message: object) -> bool:
    """A message the user wrote: role `user`, never a server notice (a background task's delivery
    is stored as a `user` row whose `meta.system_notice` is set, and it quotes tool output)."""
    if not isinstance(message, Mapping) or message.get("role") != "user":
        return False
    meta = message.get("meta")
    return not (isinstance(meta, Mapping) and meta.get("system_notice"))


def branch(chat_id: object, message_id: object, user_id: str) -> Branch | None:
    """The caller's stored branch that ends in `message_id` (the pending assistant message), or
    `None` when no such branch is stored for this caller (a headless call, another user's chat)."""
    if not (isinstance(chat_id, str) and chat_id and isinstance(message_id, str) and message_id):
        return None
    from nucllei.models.chats import Chats  # noqa: PLC0415 - see the module docstring
    from nucllei.utils.misc import get_message_list  # noqa: PLC0415 - see the module docstring

    chat = Chats.get_chat_by_id_and_user_id(chat_id, user_id)
    history = chat.chat.get("history") if chat is not None else None
    messages = history.get("messages") if isinstance(history, Mapping) else None
    chain = get_message_list(messages, message_id) if isinstance(messages, Mapping) else None
    if not chain:
        return None
    human = [message for message in chain if _human(message)]
    said = [message_text(message.get("content")) for message in human]
    files = [item for message in human for item in message.get("files") or ()]
    texts = tuple(text for text in said if text is not None)
    return Branch(texts, tuple(_refs(files)), said[-1] if said else None)


def owned_attachment(
    file_id: str, name: str | None, user_id: str, limit: int = _READ_BYTES
) -> Attachment | None:
    """The caller's own file, named as the jail stores it (`imports/<basename>`), its first
    `limit` bytes, or `None` for a missing, foreign, deleted or unreadable one."""
    from nucllei.models.files import Files  # noqa: PLC0415 - see the module docstring
    from nucllei.storage.provider import Storage  # noqa: PLC0415 - see the module docstring

    record = Files.get_file_by_id(file_id)
    if record is None or not record.path or getattr(record, "user_id", None) != user_id:
        return None
    base = PurePosixPath(name or record.filename or "").name
    if base in {"", ".", ".."}:
        return None
    try:
        return Attachment(base, _head(Storage.get_file(record.path), limit))
    except Exception:
        return None


def save_png(user_id: str, data: bytes) -> str:
    """Store the published PNG as the caller's file, the way nucllei stores a generated one;
    returns its id (`/api/v1/files/<id>/content` serves it to its owner)."""
    from nucllei.models.files import FileForm, Files  # noqa: PLC0415 - see the module docstring
    from nucllei.storage.provider import Storage  # noqa: PLC0415 - see the module docstring

    file_id = str(uuid.uuid4())
    name = "figure.png"
    _contents, path = Storage.upload_file(io.BytesIO(data), f"{file_id}_{name}")
    meta = {"name": name, "content_type": "image/png", "size": len(data)}
    record = Files.insert_new_file(
        user_id, FileForm(id=file_id, filename=name, path=path, data={}, meta=meta)
    )
    if record is None:
        msg = "the file record was not stored"
        raise RuntimeError(msg)
    return file_id


def result_cap() -> int:
    """The longest result nucllei keeps whole (`TOOL_RESULT_MAX_CHARS`, default 65,536); a longer
    one is cut and loses its markdown render."""
    try:
        from nucllei.env import TOOL_RESULT_MAX_CHARS  # noqa: PLC0415 - see the module docstring
    except Exception:
        return _RESULT_CAP
    return TOOL_RESULT_MAX_CHARS if isinstance(TOOL_RESULT_MAX_CHARS, int) else _RESULT_CAP


def mark_error_kind(kind: str) -> None:
    """Flag this call's result (`call`, `failure`, `fatal`) without raising: the check list stays
    the result's text."""
    from nucllei.utils.tool_output import mark_error_kind as mark  # noqa: PLC0415 - as above

    mark(kind)


def rendered_markdown(text: str) -> object:
    """A result nucllei renders as markdown inside the collapsed tool block; `text` is also what
    the model reads."""
    from nucllei.utils.tool_render import Rendered  # noqa: PLC0415 - see the module docstring

    return Rendered(text, "markdown")
