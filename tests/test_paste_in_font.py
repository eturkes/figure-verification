# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q44: Open WebUI's Japanese font cut to the characters one figure can draw.

Contract `.agent/archive/contracts/q44.md` (F1-F6). The cut keeps printable ASCII, the minus sign
and every character of the program and the attached files; a character outside it fails
`glyph_missing`.
Open WebUI keeps one Pyodide runtime per tab, so a later reply's cut must replace an earlier one.
The reader witnesses cut with fontTools directly, so their red is the reader's alone.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import logging
import sys
import threading
from collections.abc import Callable, Iterable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest
from fontTools import subset  # type: ignore[import-untyped]
from fontTools.ttLib import TTFont  # type: ignore[import-untyped]

from outlet_support import PASS, Browser, patched_filter
from paste_in_support import REPO_ROOT, StoredFile, fake_open_webui
from verifier.figure import reader
from verifier.figure.description import parse_description
from verifier.figure.judge import Passed, Sources, judge
from webui.paste_in import sandbox

SOURCE = (REPO_ROOT / "tests" / "fonts" / "NotoSansJP-subset.ttf").read_bytes()
ASCII = frozenset(chr(code) for code in range(0x20, 0x7F))
_PLT = "import matplotlib.pyplot as plt\n"


def _fonts() -> ModuleType:
    return importlib.import_module("webui.paste_in.fonts")


def _cut(font: bytes, keep: Iterable[str]) -> bytes:
    return cast(bytes, _fonts().cut(font, frozenset(keep)))


def _characters(program: str, contents: list[bytes]) -> frozenset[str]:
    return cast(frozenset[str], _fonts().characters(program, contents))


def _subset(text: str) -> bytes:
    """The test's own cut of the test font, independent of the filter's."""
    options = subset.Options()
    font = TTFont(io.BytesIO(SOURCE))
    subsetter = subset.Subsetter(options)
    subsetter.populate(text=text)
    subsetter.subset(font)
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


def _cmap(font: bytes) -> set[int]:
    return set(TTFont(io.BytesIO(font)).getBestCmap())


def _write(font: bytes, directory: Path) -> str:
    path = directory / f"{hashlib.sha256(font).hexdigest()[:16]}.ttf"
    path.write_bytes(font)
    return str(path)


def _glyphs(output: str) -> int:
    described = parse_description(output)
    assert described is not None
    return described.glyphs


def test_q44_f1_characters_are_ascii_the_minus_and_every_program_and_file_character() -> None:
    program = _PLT + "plt.title('患者')\n"
    contents = ["年,1\n".encode(), b"\xff\x00", "é".encode("latin-1")]
    assert _characters(program, contents) == ASCII | {"\u2212", "\n", "\x00", "患", "者", "年"}


def test_q44_f1_the_cut_keeps_the_kept_characters_and_the_family_name() -> None:
    keep = {"A", "7", "\u2212", "患", "者"}
    cut = _cut(SOURCE, keep)
    assert _cmap(cut) == {ord(character) for character in keep}
    assert ord("診") in _cmap(SOURCE)
    assert TTFont(io.BytesIO(cut))["name"].getDebugName(1) == "Noto Sans JP"
    assert len(cut) * 10 < len(SOURCE)


@pytest.mark.parametrize("module", ["fontTools", "fontTools.ttLib"])
def test_q44_f2_without_fonttools_the_whole_font_is_sent(
    monkeypatch: pytest.MonkeyPatch, module: str
) -> None:
    monkeypatch.setitem(sys.modules, module, None)
    assert _cut(SOURCE, {"患"}) == SOURCE


def test_q44_f2_a_fault_while_cutting_sends_the_whole_font(monkeypatch: pytest.MonkeyPatch) -> None:
    garbage = b"\x00\x01\x00\x00not a font"
    assert _cut(garbage, {"患"}) == garbage

    def explode(*_args: object) -> None:
        message = "planted fault"
        raise RuntimeError(message)

    monkeypatch.setattr(subset.Subsetter, "subset", explode)
    assert _cut(SOURCE, {"患"}) == SOURCE


def test_q44_f1_a_program_naming_the_family_alone_draws_with_the_cut(tmp_path: Path) -> None:
    """The cut keeps ASCII + U+2212: Noto Sans JP alone then draws digits and the minus sign."""
    program = (
        _PLT + "plt.rcParams['font.family'] = 'Noto Sans JP'\n"
        "plt.bar(['内科', '外科'], [-3, 5])\nplt.title('患者数 (人)')\nplt.show()\n"
    )
    font = _write(_cut(SOURCE, _characters(program, [])), tmp_path)
    assert _glyphs(reader.run(program, font)) == 0


def test_q44_f4_a_later_cut_of_the_family_draws_every_glyph(tmp_path: Path) -> None:
    """One runtime, two replies, two paths: the second cut holds glyphs the first lacks."""
    first, second = (
        _PLT + f"plt.bar(['a', 'b'], [1, 2])\nplt.title('{title}')\n"
        for title in ("患者", "診療科")
    )
    early = _write(_subset("患者"), tmp_path)
    late = _write(_subset("診療科"), tmp_path)
    assert _glyphs(reader.run(first, early)) == 0
    assert _glyphs(reader.run(second, late)) == 0


@pytest.mark.parametrize(
    "drawn",
    ["'\\u6708'", "chr(0x6708)", "b'\\xe6\\x9c\\x88'.decode()"],
    ids=["escape", "chr", "bytes"],
)
def test_q44_f3_a_character_outside_the_cut_fails_glyph_missing(tmp_path: Path, drawn: str) -> None:
    """`月` drawn, never spelled: the cut lacks it, so the figure fails; the whole font draws it."""
    program = (
        _PLT + "plt.bar(['a', 'b'], [1, 2])\nplt.title('患者数')\n"
        f"plt.xlabel({drawn})\nplt.show()\n"
    )
    assert "月" not in _characters(program, [])
    described = parse_description(
        reader.run(program, _write(_cut(SOURCE, _characters(program, [])), tmp_path))
    )
    assert described is not None
    verdict = judge(described, Sources())
    assert not isinstance(verdict, Passed)
    assert verdict.reason == "glyph_missing"
    assert _glyphs(reader.run(program, _write(SOURCE, tmp_path))) == 0


def test_q44_f4_each_font_has_its_own_sandbox_path() -> None:
    path = "/tmp/figure-verification-cjk-ba7816bf8f01cfea.ttf"  # noqa: S108 - Pyodide's FS
    assert _fonts().path(b"abc") == path
    assert _fonts().path(b"abd") != path
    assert repr(path) in sandbox.wrapper_code(_PLT + "plt.plot([1])\n", b"abc")


def test_q44_outlet_sends_the_cut_made_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    program = _PLT + "plt.bar([0, 1, 2], [3, 5, 9])\nplt.show()\n# 年\n"
    content = "name,value\n診,100\n".encode()
    keep = ASCII | {"\u2212", "\n", "年", "診"}
    real = _fonts().cut
    seen: list[tuple[bytes, frozenset[str], int]] = []

    async def read_font(_configured: str) -> bytes:
        return SOURCE

    def spy(font: bytes, kept: frozenset[str]) -> bytes:
        seen.append((font, kept, threading.get_ident()))
        return cast(bytes, real(font, kept))

    browser = Browser(
        program, files=[{"id": "owned", "filename": "extra.csv"}], font=_cut(SOURCE, keep)
    )
    with (
        fake_open_webui((StoredFile("owned", "outlet-owner", "extra.csv", content),), tmp_path),
        patched_filter(
            monkeypatch,
            (
                ("webui.paste_in.owui_files", "cjk_font", read_font),
                ("webui.paste_in.fonts", "cut", spy),
            ),
        ),
    ):
        result = browser.exercise(file_ids=("owned",), request_text="3 5 9")
    assert [(font, kept) for font, kept, _thread in seen] == [(SOURCE, keep)]
    assert seen[0][2] != threading.get_ident()
    assert len(browser.calls) == 1
    reply = cast(list[dict[str, object]], result["messages"])[-1]["content"]
    assert isinstance(reply, str) and reply.startswith(PASS)


def test_q44_r_a_repeated_mathtext_marker_miss_fails_every_reply() -> None:
    """One runtime, two replies: the text-marker parse cache must not hide the second miss."""
    program = _PLT + "plt.plot([1, 2], [1, 2], marker='$週$')\nplt.show()\n"
    assert [_glyphs(reader.run(program)) > 0 for _ in range(2)] == [True, True]


def test_q44_r_a_later_cut_reaches_a_cached_mathtext_marker(tmp_path: Path) -> None:
    """A mathtext font set naming the family: the second reply's cut holds `週`, so its marker
    draws the glyph, never the first reply's cached dummy."""
    program = (
        _PLT + "plt.rcParams.update({'font.family': ['Noto Sans JP'], 'mathtext.fontset': 'custom',"
        " 'mathtext.rm': 'Noto Sans JP', 'mathtext.it': 'Noto Sans JP',"
        " 'mathtext.default': 'regular'})\n"
        "plt.plot([1, 2], [1, 2], marker='$' + chr(0x9031) + '$')\nplt.show()\n"
    )
    early = reader.run(program, _write(_cut(SOURCE, _characters(program, [])), tmp_path))
    late = reader.run(program, _write(_cut(SOURCE, _characters(program + "# 週\n", [])), tmp_path))
    assert (_glyphs(early), _glyphs(late)) == (1, 0)
    assert early.splitlines()[1] != late.splitlines()[1]


@pytest.mark.parametrize(
    "quiet",
    ["plt.set_loglevel('error')", "import logging\nlogging.disable(logging.CRITICAL)"],
    ids=["set-loglevel", "logging-disable"],
)
def test_q44_r_a_quieted_logger_still_counts_a_mathtext_miss(quiet: str) -> None:
    """A program that quiets matplotlib's logging still fails a mathtext miss, on this reply and
    on the next one, which quiets nothing."""
    marker = _PLT + "plt.plot([1, 2], [1, 2], marker='${}$')\nplt.show()\n"
    level = logging.getLogger("matplotlib").level
    try:
        quieted = _glyphs(reader.run(_PLT + quiet + "\n" + marker.format("週")))
        later = _glyphs(reader.run(marker.format("診")))
    finally:
        logging.disable(logging.NOTSET)
        logging.getLogger("matplotlib").setLevel(level)
    assert (quieted > 0, later > 0) == (True, True)


def test_q44_r_a_fault_reading_the_cut_back_sends_the_whole_font(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Unreadable(io.BytesIO):
        def getvalue(self) -> bytes:
            message = "planted allocation failure"
            raise MemoryError(message)

    def buffer(*initial: bytes) -> io.BytesIO:
        return io.BytesIO(*initial) if initial else Unreadable()

    monkeypatch.setattr(_fonts(), "io", SimpleNamespace(BytesIO=buffer))
    assert _cut(SOURCE, {"患"}) == SOURCE


def test_q44_r_a_later_reader_text_installs_its_own_hooks() -> None:
    """Open WebUI's tab keeps its runtime across a filter update: a reader whose hook set differs
    (here, the older one without the mathtext counter) must not lend its hooks to the next reader,
    which would then count no mathtext miss (re-review RR-R1)."""
    hook = (
        '    holder.replace(module("_mathtext"), "_log", lambda log: _MathtextLog(log, holder))\n'
    )
    source = Path(reader.__file__).read_text(encoding="utf-8")
    assert source.count(hook) == 1
    older: dict[str, object] = {"__name__": "older_reader"}
    exec(compile(source.replace(hook, ""), "<older-reader>", "exec"), older)  # noqa: S102
    cast(Callable[[str], str], older["run"])(_PLT + "plt.plot([0, 1], [1, 2])\n")
    assert _glyphs(reader.run(_PLT + "plt.plot([0, 1], [1, 2], marker='$週$')\n")) > 0


def test_q44_r_a_mathtext_miss_outside_a_run_is_matplotlib_s_own(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Between replies the counter counts nothing and the warning still reaches matplotlib's
    logger."""
    import matplotlib.pyplot as plt  # noqa: PLC0415 - imported where the reader imports it

    reader.run(_PLT + "plt.plot([1])\n")
    importlib.import_module("matplotlib.mathtext").MathTextParser._parse_cached.cache_clear()
    with caplog.at_level(logging.WARNING, logger="matplotlib.mathtext"):
        plt.plot([1, 2], [1, 2], marker="$鬱$")
    plt.close("all")
    assert ["does not have a glyph" in r.getMessage() for r in caplog.records] == [True]


def test_q44_r_a_fault_collecting_the_characters_sends_the_whole_font(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closing review G2: the collection runs inside the cut's fallback."""

    def explode(*_args: object) -> frozenset[str]:
        message = "planted collection failure"
        raise MemoryError(message)

    monkeypatch.setattr(_fonts(), "characters", explode)
    assert _fonts().cut_for(SOURCE, _PLT + "plt.title('患者')\n", [b"x"]) == SOURCE


def test_q44_r_a_path_text_glyph_outside_the_cut_fails(tmp_path: Path) -> None:
    """Closing review G1: a `TextPath` marker lays its glyphs out without a warning; a glyph the
    cut lacks draws `.notdef` and must still fail, while the whole font draws it."""
    program = (
        _PLT + "from matplotlib.textpath import TextPath\nplt.title('患者')\n"
        "plt.plot([1, 2], [1, 2], marker=TextPath((0, 0), chr(0x9031)))\nplt.show()\n"
    )
    assert "週" not in _characters(program, [])
    cut = _write(_cut(SOURCE, _characters(program, [])), tmp_path)
    assert _glyphs(reader.run(program, cut)) > 0
    assert _glyphs(reader.run(program, _write(SOURCE, tmp_path))) == 0
    assert _glyphs(reader.run(program.replace("chr(0x9031)", "'患'"), cut)) == 0
