# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M17.1 F4: Open WebUI's bundled Japanese font, read in-process; every fault degrades to `None`.

The font source (`owui_files.cjk_font`) is unchanged by M19.5; these witnesses moved here from the
retired wrapper suite, whose other predicates belonged to the static-path wrapper.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import sys
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

FONT_BYTES = b"\x00\x01\x00\x00independent fake font\xff"


def _install_env(patch: pytest.MonkeyPatch, directory: object = None) -> ModuleType:
    package = ModuleType("open_webui")
    package.__path__ = []
    env = ModuleType("open_webui.env")
    if directory is not None:
        vars(env)["FONTS_DIR"] = directory
    vars(package)["env"] = env
    patch.setitem(sys.modules, "open_webui", package)
    patch.setitem(sys.modules, "open_webui.env", env)
    return env


def _font() -> bytes | None:
    module = importlib.import_module("webui.paste_in.owui_files")
    function = cast(Callable[[], Awaitable[bytes | None]], module.cjk_font)

    async def invoke() -> bytes | None:
        return await function()

    return asyncio.run(invoke())


@pytest.mark.parametrize("payload", [b"", FONT_BYTES], ids=["empty-file", "opaque-bytes"])
def test_f4_font_source_reads_owui_fonts_dir_off_the_loop_and_never_raises(
    payload: bytes, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = importlib.import_module("webui.paste_in.owui_files")
    assert getattr(module, "CJK_FONT_NAME", None) == "NotoSansJP-Regular.ttf"
    env = _install_env(monkeypatch, tmp_path)
    owner_thread = threading.get_ident()
    seen: list[tuple[Path, int]] = []

    def read_bytes(path: Path) -> bytes:
        seen.append((path, threading.get_ident()))
        return payload

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    assert _font() == payload
    second = tmp_path / "changed-after-import"
    vars(env)["FONTS_DIR"] = str(second)
    assert _font() == payload
    assert [path for path, _thread in seen] == [
        tmp_path / "NotoSansJP-Regular.ttf",
        second / "NotoSansJP-Regular.ttf",
    ]
    assert all(thread != owner_thread for _path, thread in seen), "font read on event-loop thread"


@pytest.mark.parametrize(
    "fault", ["import", "attribute", "file", "permission", "runtime", "value", "dir"]
)
def test_f4_font_source_swallows_each_exception_family(
    fault: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env = _install_env(monkeypatch, tmp_path)
    if fault == "import":
        monkeypatch.setitem(sys.modules, "open_webui.env", None)
    elif fault == "attribute":
        del vars(env)["FONTS_DIR"]
    elif fault == "dir":
        vars(env)["FONTS_DIR"] = object()
    else:
        failures = {
            "file": FileNotFoundError("font absent"),
            "permission": PermissionError("font unreadable"),
            "runtime": RuntimeError("read fault"),
            "value": ValueError("read fault"),
        }

        def read_bytes(_path: Path) -> bytes:
            raise failures[fault]

        monkeypatch.setattr(Path, "read_bytes", read_bytes)
    assert _font() is None


def test_f4_font_source_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_env(monkeypatch, tmp_path)

    def read_bytes(_path: Path) -> bytes:
        raise asyncio.CancelledError

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    with pytest.raises(asyncio.CancelledError):
        _font()


def test_f4_open_webui_import_is_function_local(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = importlib.import_module("webui.paste_in.owui_files")
    with monkeypatch.context() as blocked:
        blocked.setitem(sys.modules, "open_webui", None)
        blocked.setitem(sys.modules, "open_webui.env", None)
        importlib.reload(module)
    (tmp_path / "NotoSansJP-Regular.ttf").write_bytes(FONT_BYTES)
    _install_env(monkeypatch, tmp_path)
    assert _font() == FONT_BYTES


def test_f4_font_source_survives_a_raising_log_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    """F4 (review R1): a DEBUG logger whose sink raises still leaves an absent font as None."""

    class BrokenSink(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            raise OSError(record.getMessage())

    monkeypatch.setitem(sys.modules, "open_webui.env", None)
    logger = logging.getLogger("webui.paste_in.owui_files")
    monkeypatch.setattr(logger, "level", logging.DEBUG)
    monkeypatch.setattr(logger, "propagate", False)
    monkeypatch.setattr(logger, "handlers", [BrokenSink()])
    module = importlib.import_module("webui.paste_in.owui_files")
    assert asyncio.run(module.cjk_font()) is None
