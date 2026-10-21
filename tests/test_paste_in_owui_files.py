# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""U2 (`.agent/archive/contracts/u2-font.md`): the server's Japanese font, read in-process. The
admin's Valve file first, then discovery over the system font dirs; only a regular font file
within the cap leaves the server; every fault degrades to `None` off the event loop.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import sys
import threading
from pathlib import Path
from types import ModuleType

import pytest

TRUETYPE = b"\x00\x01\x00\x00independent fake TrueType font\xff"
OPENTYPE = b"OTTOindependent fake CFF font"


def _module() -> ModuleType:
    return importlib.import_module("webui.paste_in.owui_files")


def _font(configured: str = "") -> bytes | None:
    module = _module()

    async def invoke() -> bytes | None:
        return await module.cjk_font(configured)  # type: ignore[no-any-return]

    return asyncio.run(invoke())


def _roots(patch: pytest.MonkeyPatch, *roots: Path) -> None:
    patch.setattr(_module(), "_FONT_DIRS", tuple(str(root) for root in roots))


def _write(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_u2_the_known_font_files_and_the_size_cap_are_stated() -> None:
    module = _module()
    assert module.CJK_FONT_FILES == (
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
    assert module.MAX_FONT_BYTES == 33_554_432
    assert module._WALK_LIMIT == 20_000
    assert module._FONT_DIRS == ("/usr/share/fonts", "/usr/local/share/fonts")


def test_u2_d1_the_admins_font_file_wins_and_skips_the_walk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write(tmp_path / "fonts" / "NotoSansJP-Regular.ttf", TRUETYPE)
    configured = _write(tmp_path / "admin" / "custom-name.otf", OPENTYPE)
    _roots(monkeypatch, tmp_path / "fonts")
    assert _font("") == TRUETYPE
    walks: list[object] = []
    real = _module()._discovered

    def spy(roots: object) -> object:
        walks.append(roots)
        return real(roots)

    monkeypatch.setattr(_module(), "_discovered", spy)
    assert _font(str(configured)) == OPENTYPE
    assert walks == []


@pytest.mark.parametrize("unusable", ["missing", "directory", "not-a-font", "too-large"], ids=str)
def test_u2_d1_an_unusable_admin_file_falls_back_to_discovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, unusable: str
) -> None:
    _write(tmp_path / "fonts" / "ipag.ttf", TRUETYPE)
    _roots(monkeypatch, tmp_path / "fonts")
    configured = tmp_path / "admin" / "font.ttf"
    if unusable == "directory":
        configured.mkdir(parents=True)
    elif unusable == "not-a-font":
        _write(configured, b"user:secret\n")
    elif unusable == "too-large":
        monkeypatch.setattr(_module(), "MAX_FONT_BYTES", len(TRUETYPE))
        _write(configured, OPENTYPE + b"\x00" * len(TRUETYPE))
    assert _font(str(configured)) == TRUETYPE


def test_u2_d2_discovery_ranks_by_the_list_then_by_path(tmp_path: Path) -> None:
    root = tmp_path / "fonts"
    collection = _write(root / "a" / "NotoSansCJK-Regular.ttc", b"ttcf" + b"\x00" * 8)
    later = _write(root / "c" / "IPAG.TTF", TRUETYPE)
    earlier = _write(root / "b" / "ipag.ttf", TRUETYPE)
    _write(root / "a" / "DejaVuSans.ttf", TRUETYPE)
    second_root = tmp_path / "local"
    best = _write(second_root / "SourceHanSansJP-Regular.otf", OPENTYPE)
    assert _module()._discovered((str(root), str(second_root))) == [
        best,
        earlier,
        later,
        collection,
    ]


def test_u2_d2_a_symlinked_file_is_read_a_symlinked_dir_is_not_walked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    _write(elsewhere / "NotoSansJP-Regular.ttf", OPENTYPE)
    target = _write(tmp_path / "packages" / "ipaexg.ttf", TRUETYPE)
    root = tmp_path / "fonts"
    root.mkdir()
    (root / "linked-dir").symlink_to(elsewhere, target_is_directory=True)
    (root / "fonts-japanese-gothic.ttf").symlink_to(target)
    _roots(monkeypatch, root)
    assert _module()._discovered((str(root),)) == [root / "fonts-japanese-gothic.ttf"]
    assert _font("") == TRUETYPE


@pytest.mark.parametrize(("limit", "depth"), [(4, 0), (5, 1), (6, 2)], ids=["4", "5", "6"])
def test_u2_d2_the_walk_stops_past_its_entry_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, limit: int, depth: int
) -> None:
    """The root holds 4 files + 1 directory (5 entries), the directory 1 file: past the limit the
    walk returns what it found before that directory."""
    root = tmp_path / "fonts"
    font = _write(root / "NotoSansJP-Regular.ttf", TRUETYPE)
    for name in ("a.ttf", "b.ttf", "c.ttf"):
        _write(root / name, TRUETYPE)
    deeper = _write(root / "deeper" / "ipag.ttf", TRUETYPE)
    monkeypatch.setattr(_module(), "_WALK_LIMIT", limit)
    assert _module()._discovered((str(root),)) == [font, deeper][:depth]


@pytest.mark.parametrize(
    ("head", "admitted"),
    [
        (b"\x00\x01\x00\x00", True),
        (b"OTTO", True),
        (b"true", True),
        (b"ttcf", True),
        (b"\x00\x01\x00\x01", False),
        (b"OTT0", False),
        (b"wOFF", False),
        (b"wOF2", False),
        (b"%PDF", False),
        (b"", False),
    ],
    ids=[
        "truetype",
        "cff",
        "apple",
        "collection",
        "near-truetype",
        "near-cff",
        "woff",
        "woff2",
        "pdf",
        "empty",
    ],
)
def test_u2_d3_only_an_sfnt_or_collection_tag_is_admitted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, head: bytes, *, admitted: bool
) -> None:
    configured = _write(tmp_path / "admin.ttf", head + b"font body" if head else b"")
    _roots(monkeypatch)
    assert _font(str(configured)) == (configured.read_bytes() if admitted else None)


@pytest.mark.parametrize(
    ("size", "admitted"), [(16, True), (17, False)], ids=["at-cap", "past-cap"]
)
def test_u2_d3_a_file_past_the_cap_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, size: int, *, admitted: bool
) -> None:
    content = (b"OTTO" + b"x" * size)[:size]
    configured = _write(tmp_path / "admin.otf", content)
    _roots(monkeypatch)
    monkeypatch.setattr(_module(), "MAX_FONT_BYTES", 16)
    assert _font(str(configured)) == (content if admitted else None)


def test_u2_d3_a_growing_file_past_the_cap_is_refused_from_its_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The stat saw a small file; the read sees one byte more than the cap."""
    configured = _write(tmp_path / "admin.otf", b"OTTO" + b"x" * 12)
    _roots(monkeypatch)
    monkeypatch.setattr(_module(), "MAX_FONT_BYTES", 16)
    real_open = Path.open

    def grown(path: Path, *args: object, **kwargs: object) -> object:
        if path == configured:
            configured.write_bytes(b"OTTO" + b"x" * 13)
        return real_open(path, *args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(Path, "open", grown)
    assert _font(str(configured)) is None


def test_u2_d3_a_fifo_is_never_opened(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Opening a FIFO with no writer blocks: the stat refuses it first, so the open never runs
    (a regression raises here rather than hanging the suite)."""
    fifo = tmp_path / "font.ttf"
    os.mkfifo(fifo)
    _roots(monkeypatch)
    opened: list[Path] = []

    def guarded(path: Path, *_args: object, **_kwargs: object) -> object:
        opened.append(path)
        raise OSError(path)

    monkeypatch.setattr(Path, "open", guarded)
    assert _font(str(fifo)) is None
    assert opened == []


def test_u2_d4_the_walk_and_the_read_run_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write(tmp_path / "fonts" / "ipag.ttf", TRUETYPE)
    _roots(monkeypatch, tmp_path / "fonts")
    owner = threading.get_ident()
    seen: list[int] = []
    real_walk = os.walk

    def walk(top: str) -> object:
        seen.append(threading.get_ident())
        return real_walk(top)

    monkeypatch.setattr(os, "walk", walk)
    assert _font("") == TRUETYPE
    assert seen and owner not in seen, "font discovery ran on the event-loop thread"


@pytest.mark.parametrize("fault", ["missing", "permission", "runtime", "value", "walk"])
def test_u2_d4_each_fault_family_degrades_to_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fault: str
) -> None:
    configured = _write(tmp_path / "admin.ttf", OPENTYPE)
    _write(tmp_path / "fonts" / "ipag.ttf", TRUETYPE)
    _roots(monkeypatch, tmp_path / "fonts")
    failures: dict[str, BaseException] = {
        "missing": FileNotFoundError("font absent"),
        "permission": PermissionError("font unreadable"),
        "runtime": RuntimeError("read fault"),
        "value": ValueError("read fault"),
    }
    if fault == "walk":
        fault_message = "walk fault"

        def walk(*_args: object, **_kwargs: object) -> object:
            raise OSError(fault_message)

        monkeypatch.setattr(os, "walk", walk)
        assert _font("") is None
        return

    real_stat = Path.stat

    def stat(path: Path, **kwargs: bool) -> object:
        if path == configured:
            raise failures[fault]
        return real_stat(path, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    # The fault costs the admin's file alone: the lookup falls through to discovery.
    assert _font(str(configured)) == TRUETYPE


def test_u2_d4_cancellation_propagates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    configured = _write(tmp_path / "admin.ttf", TRUETYPE)
    _roots(monkeypatch)

    def stat(_path: Path, **_kwargs: object) -> object:
        raise asyncio.CancelledError

    monkeypatch.setattr(Path, "stat", stat)
    with pytest.raises(asyncio.CancelledError):
        _font(str(configured))


def test_u2_d4_the_degrade_path_survives_a_raising_log_sink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A walk fault under a DEBUG logger whose sink raises still reads as None: the degrade path
    logs nothing."""

    class BrokenSink(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            raise OSError(record.getMessage())

    fault_message = "walk fault"

    def walk(_top: str) -> object:
        raise OSError(fault_message)

    _roots(monkeypatch, tmp_path)
    monkeypatch.setattr(os, "walk", walk)
    logger = logging.getLogger("webui.paste_in.owui_files")
    monkeypatch.setattr(logger, "level", logging.DEBUG)
    monkeypatch.setattr(logger, "propagate", False)
    monkeypatch.setattr(logger, "handlers", [BrokenSink()])
    assert _font(str(tmp_path / "missing.ttf")) is None


def test_u2_the_font_read_needs_no_open_webui(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    with monkeypatch.context() as blocked:
        blocked.setitem(sys.modules, "open_webui", None)
        blocked.setitem(sys.modules, "open_webui.env", None)
        importlib.reload(module)
        _write(tmp_path / "fonts" / "ipag.ttf", TRUETYPE)
        _roots(blocked, tmp_path / "fonts")
        assert _font("") == TRUETYPE
    importlib.reload(module)


def test_m21_owned_files_read_at_most_one_byte_past_the_csv_limit(tmp_path: Path) -> None:
    """M21.1 F4: every owned file was read whole, at any size, on every inlet and outlet call. The
    judge refuses a file past `max_csv_bytes` from its length alone, so one more byte decides it."""
    from paste_in_support import StoredFile, fake_open_webui  # noqa: PLC0415
    from verifier.figure.sources import Unreadable, read_table  # noqa: PLC0415

    limit = 8_000_000
    big = b"a,b\n" + b"1,2\n" * (limit // 4)
    small = b"a,b\n1,2\n"
    stored = (
        StoredFile("big", "owner", "big.csv", big),
        StoredFile("small", "owner", "small.csv", small),
    )
    module = importlib.import_module("webui.paste_in.owui_files")
    with fake_open_webui(stored, tmp_path):
        files = asyncio.run(module.owned_files(["big", "small"], "owner"))
    assert [file.content for file in files] == [big[: limit + 1], small]
    refused = Unreadable("big.csv", "csv_too_large")
    assert read_table("big.csv", files[0].content) == read_table("big.csv", big) == refused


def test_m22_attachment_ids_drop_a_repeated_id() -> None:
    """M22.1 F3: the chat's `files` list comes from the request body, which Open WebUI does not
    check, and one 8 MB upload listed 50 times made the inlet hold 493 MB. A repeat names the same
    bytes, so its first place counts, as in Open WebUI's own frontend."""
    files = [{"id": "a"}, {"id": "b"}, {"id": "a"}, {"id": "b"}, {"id": "c"}]
    assert _module().attachment_ids({"files": files}) == ["a", "b", "c"]
