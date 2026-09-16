# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The ONLY module that imports `open_webui`: the user's uploaded bytes, fetched in-process.

The truth source for every recomputed number is the user's own upload (`.claude/rules/pysrc.md`,
comparison class II), so the bytes come from Open WebUI's own store and not from the chat metadata,
which is client-supplied end to end -- the item's nested `path` included. Only the top-level `id`
is trusted, and it is re-resolved against the requesting user:
`Files.get_file_by_id_and_user_id` returns `None` for a file that is missing, foreign or
unreadable, so a file the caller does not own is never read and no second path exists that could
read it.

The `open_webui` imports are function-local, and that is load-bearing rather than stylistic: this
module must import in the gate environment, which has no `open_webui` and cannot have one, while
binding the real API inside the image. A test injects fakes into `sys.modules` and drives the same
call chain.
"""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

# Where Open WebUI's Pyodide worker writes each attached file before it runs the program. An
# admitted `read_csv` literal must name exactly this, and the core compares byte-for-byte.
UPLOAD_DIR = "/mnt/uploads/"


@dataclass(frozen=True, slots=True)
class UploadedFile:
    """One attachment, named as the sandbox will name it, carrying the store's exact bytes."""

    path: str
    content: bytes


def attachment_ids(metadata: Mapping[str, object] | None) -> list[str]:
    """Top-level ids from `__metadata__["files"]`, in chat order. Every other key is untrusted."""
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
    return ids


async def uploaded_files(
    metadata: Mapping[str, object] | None,
    user_id: str,
) -> tuple[UploadedFile, ...]:
    """Every attachment the requesting user owns, in chat order, carrying its stored bytes.

    Async because the ownership lookup is: a synchronous handler would have to trust the metadata's
    nested path instead, which is the one thing this module exists to avoid.
    """
    from open_webui.models.files import Files  # noqa: PLC0415 - see the module docstring
    from open_webui.storage.provider import Storage  # noqa: PLC0415 - see the module docstring

    found: list[UploadedFile] = []
    for file_id in attachment_ids(metadata):
        record = await Files.get_file_by_id_and_user_id(file_id, user_id)
        if record is None:
            continue  # missing or foreign: skipped, never re-fetched by another route
        local_path = await asyncio.to_thread(Storage.get_file, record.path)
        content = await asyncio.to_thread(Path(local_path).read_bytes)
        found.append(UploadedFile(path=UPLOAD_DIR + record.filename, content=content))
    return tuple(found)
