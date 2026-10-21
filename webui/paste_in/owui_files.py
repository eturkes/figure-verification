# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The ONLY module that imports `open_webui`: uploaded bytes + the user's stored messages,
in-process; plus the server's Japanese font (Open WebUI ships none since 0.12).

The truth source for every recomputed number is the user's own upload (`.claude/rules/pysrc.md`,
comparison class II), so the bytes come from Open WebUI's own store and not from the chat metadata,
which is client-supplied end to end -- the item's nested `path` included. Only the top-level `id`
is trusted, and it is re-resolved against the requesting user:
`Files.get_file_by_id_and_user_id` returns `None` for a file that is missing, foreign or
unreadable, so a file the caller does not own is never read and no second path exists that could
read it. The request text comes from the same store, read only for a chat the requesting user owns.

The `open_webui` imports are function-local, and that is load-bearing rather than stylistic: this
module must import in the gate environment, which has no `open_webui` and cannot have one, while
binding the real API inside the image. A test injects fakes into `sys.modules` and drives the same
call chain.
"""

import asyncio
import itertools
import logging
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from verifier.pysrc.limits import DEFAULT_LIMITS

# Where Open WebUI's Pyodide worker writes each attached file before it runs the program. An
# admitted `read_csv` literal must name exactly this, and the core compares byte-for-byte.
UPLOAD_DIR = "/mnt/uploads/"
# Japanese-capable fonts that container font packages install, best first: Japanese-only faces,
# then pan-CJK collections whose first face is Japanese (matplotlib draws a collection's face 0).
# Debian links `fonts-japanese-gothic.ttf` to whichever Japanese gothic is installed.
CJK_FONT_FILES = (
    "NotoSansJP-Regular.ttf",
    "NotoSansJP-Regular.otf",
    "NotoSansCJKjp-Regular.otf",
    "SourceHanSansJP-Regular.otf",
    "fonts-japanese-gothic.ttf",
    "ipaexg.ttf",
    "ipag.ttf",
    "TakaoPGothic.ttf",
    "VL-PGothic-Regular.ttf",
    "NotoSansCJK-Regular.ttc",
    "SourceHanSans-Regular.ttc",
)
_FONT_DIRS = ("/usr/share/fonts", "/usr/local/share/fonts")
# Bounds the walk on a host with many font packages; a container image holds a few hundred files.
_WALK_LIMIT = 20_000
# Noto Sans CJK's collection is 19.5 MB; the bytes ride inside one RPC to the user's browser. The
# read stops one byte past it, so the length alone refuses a larger file.
MAX_FONT_BYTES = 32 * 1024 * 1024
# sfnt (TrueType, CFF, Apple) + collection tags: no other file's bytes may leave the server.
_FONT_TAGS = frozenset({b"\x00\x01\x00\x00", b"OTTO", b"true", b"ttcf"})
# The judge refuses a file past `max_csv_bytes` from its length alone, so one byte more decides it,
# and an upload of any size never enters the server's memory whole.
_READ_BYTES = DEFAULT_LIMITS.max_csv_bytes + 1


@dataclass(frozen=True, slots=True)
class UploadedFile:
    """One attachment, named as the sandbox will name it, carrying the store's exact bytes."""

    file_id: str
    path: str
    content: bytes


def attachment_ids(metadata: Mapping[str, object] | None) -> list[str]:
    """Top-level ids from `__metadata__["files"]`, in chat order, each once. Every other key is
    untrusted, and so is the list itself: it comes from the request body, where one upload listed
    50 times made the inlet hold 493 MB (M22.1 F3). A repeat keeps its first place, as Open
    WebUI's own frontend does."""
    if metadata is None:
        return []
    items = metadata.get("files")
    if not isinstance(items, Sequence) or isinstance(items, str | bytes):
        return []
    ids: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        file_id = item.get("id")
        if isinstance(file_id, str) and file_id:
            ids.append(file_id)
    return list(dict.fromkeys(ids))


def _head(path: str) -> bytes:
    with Path(path).open("rb") as handle:
        return handle.read(_READ_BYTES)


async def owned_files(file_ids: Sequence[str], user_id: str) -> tuple[UploadedFile, ...]:
    """Fetch only owned, readable ids through Open WebUI's store, preserving chat order."""
    from open_webui.models.files import Files  # noqa: PLC0415 - see the module docstring
    from open_webui.storage.provider import Storage  # noqa: PLC0415 - see the module docstring

    found: list[UploadedFile] = []
    for file_id in file_ids:
        record = await Files.get_file_by_id_and_user_id(file_id, user_id)
        if record is None:
            continue
        try:
            local_path = await asyncio.to_thread(Storage.get_file, record.path)
            content = await asyncio.to_thread(_head, local_path)
        except Exception:
            logging.getLogger(__name__).debug("Unreadable owned file omitted")
            continue
        found.append(
            UploadedFile(file_id=file_id, path=UPLOAD_DIR + record.filename, content=content)
        )
    return tuple(found)


async def last_owned_file(
    metadata: Mapping[str, object] | None, user_id: str
) -> UploadedFile | None:
    """The last attachment the user owns and the store can read, through the filter's ownership
    path: the inlet renders that one alone, so it reads back from the last id and stops there."""
    for file_id in reversed(attachment_ids(metadata)):
        if found := await owned_files((file_id,), user_id):
            return found[0]
    return None


def _latest(metadata: Mapping[str, object] | None) -> str | None:
    """The text of the message that asked for this chart."""
    message = (metadata or {}).get("user_message")
    content = message.get("content") if isinstance(message, Mapping) else None
    return content if isinstance(content, str) else None


async def request_text(metadata: Mapping[str, object] | None, user_id: object) -> str | None:
    """The request the verifier reads: every user message on this chat's branch, oldest first,
    as Open WebUI stored it, joined by a blank line, so a follow-up such as
    `make the bars red` keeps the columns and numbers that earlier messages named.

    Stored rows only: the model-facing messages hold the inlet's rewrite of the latest message,
    which names every CSV column, and after compaction a model-written summary. Anything short of
    an owned chat whose branch ends in the current message reads as that message alone: Open
    WebUI lets an admin continue a chat it does not own, and a temporary chat stores none. A range
    or a negation cue can join across the blank line (`… 3` then `to 7 …`), as inside a message.
    """
    latest = _latest(metadata)
    chat_id = (metadata or {}).get("chat_id")
    message_id = (metadata or {}).get("user_message_id")
    if latest is None or not all(
        isinstance(key, str) and key for key in (user_id, chat_id, message_id)
    ):
        return latest
    try:
        from open_webui.models.chats import Chats  # noqa: PLC0415 - see the module docstring
        from open_webui.utils.misc import get_message_list  # noqa: PLC0415 - as above

        if not await Chats.is_chat_owner(chat_id, user_id):
            return latest
        branch = get_message_list(await Chats.get_messages_map_by_chat_id(chat_id), message_id)
        if not branch or branch[-1].get("role") != "user" or branch[-1].get("content") != latest:
            return latest
        texts = [
            message["content"]
            for message in branch
            if message.get("role") == "user" and isinstance(message.get("content"), str)
        ]
    except Exception:
        return latest
    return "\n\n".join(texts)


def sandbox_isolated() -> bool:
    """Whether Open WebUI runs Pyodide in its `origin null` sandbox iframe, where a program cannot
    act as the user. File persistence moves it into a worker of the instance's own origin
    (`createPyodideWorker.ts`), whose requests carry the session cookie the API accepts
    (`utils/auth.py` reads `token`). A setting that cannot be read counts as not isolated."""
    try:
        from open_webui.env import ENABLE_PYODIDE_FILE_PERSISTENCE  # noqa: PLC0415
    except Exception:
        return False
    return ENABLE_PYODIDE_FILE_PERSISTENCE is False


def _font_bytes(path: Path) -> bytes | None:
    """`path`'s bytes when it is a regular font file within `MAX_FONT_BYTES`, else `None`, on any
    fault too. The stat precedes the open: opening a FIFO would block this thread."""
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            return None
        with path.open("rb") as handle:
            content = handle.read(MAX_FONT_BYTES + 1)
    except Exception:
        return None
    return content if len(content) <= MAX_FONT_BYTES and content[:4] in _FONT_TAGS else None


def _discovered(roots: Sequence[str]) -> list[Path]:
    """Every `CJK_FONT_FILES` file under `roots`, best rank first, then by path."""
    ranks = {name.casefold(): rank for rank, name in enumerate(CJK_FONT_FILES)}
    found: list[tuple[int, str]] = []
    visited = 0
    for directory, subdirectories, names in itertools.chain.from_iterable(map(os.walk, roots)):
        visited += len(subdirectories) + len(names)
        if visited > _WALK_LIMIT:
            break
        found.extend(
            (ranks[name.casefold()], str(Path(directory, name)))
            for name in names
            if name.casefold() in ranks
        )
    return [Path(name) for _rank, name in sorted(found)]


def find_cjk_font(configured: str) -> bytes | None:
    """The admin's font file when it is one, else the best Japanese font on this server. The walk
    runs only when the admin's file is unset or no font."""
    if configured and (content := _font_bytes(Path(configured))) is not None:
        return content
    return next(
        (content for path in _discovered(_FONT_DIRS) if (content := _font_bytes(path)) is not None),
        None,
    )


async def cjk_font(configured: str = "") -> bytes | None:
    """The Japanese font the figure may draw with, read off the event loop, else `None`.

    A missing font only withholds Japanese text from the figure, which then fails as before, so
    every fault here degrades to `None` instead of costing the verdict.
    """
    try:
        return await asyncio.to_thread(find_cjk_font, configured)
    except Exception:
        return None
