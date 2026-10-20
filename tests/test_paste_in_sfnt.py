# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q74: the stdlib font cut (`webui/paste_in/sfnt.py`), graded against fontTools + FreeType.

Contract `.agent/archive/contracts/q74.md`. The cut is part of the trusted font, so every kept
character must draw as it draws with the whole font: fontTools (a test-only dev pin) and
matplotlib's FT2Font (the sandbox's FreeType) are the oracles for the outline, advance, hints, CFF
program and kerning of each kept glyph. Every structure the cut does not handle must refuse, so the
filter sends the whole font.
"""

from __future__ import annotations

import functools
import io
import struct
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import matplotlib as mpl
import pytest
from fontTools.cffLib import GlobalSubrsIndex, SubrsIndex  # type: ignore[import-untyped]
from fontTools.fontBuilder import FontBuilder  # type: ignore[import-untyped]
from fontTools.misc.psCharStrings import T2CharString  # type: ignore[import-untyped]
from fontTools.pens.recordingPen import DecomposingRecordingPen  # type: ignore[import-untyped]
from fontTools.pens.ttGlyphPen import TTGlyphPen  # type: ignore[import-untyped]
from fontTools.ttLib import TTCollection, TTFont, newTable  # type: ignore[import-untyped]
from fontTools.ttLib.tables._k_e_r_n import KernTable_format_0  # type: ignore[import-untyped]
from fontTools.ttLib.tables.ttProgram import Program  # type: ignore[import-untyped]
from hypothesis import given, settings
from hypothesis import strategies as st
from matplotlib.ft2font import FT2Font, Kerning, LoadFlags

from webui.paste_in import fonts, sfnt

_FONTS = Path(__file__).parent / "fonts"
TRUETYPE = (_FONTS / "NotoSansJP-subset.ttf").read_bytes()
CFF = (_FONTS / "NotoSansCJKjp-subset.otf").read_bytes()
# matplotlib's own DejaVu Sans: TrueType composites, hinting programs and a format 0 `kern` table.
DEJAVU = (Path(mpl.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf").read_bytes()
_REAL = {"truetype": TRUETYPE, "cff": CFF, "dejavu": DEJAVU}
_TEXT = "Aj7 \u2212患者数診療科ごとのアイウエオ、。éÅﬁ"


def _load(font: bytes) -> Any:
    return TTFont(io.BytesIO(font), fontNumber=0, lazy=False)


def _ft(font: bytes, hinting_factor: int = 8) -> FT2Font:
    return FT2Font(io.BytesIO(font), hinting_factor=hinting_factor)


@functools.cache
def _desubroutinized(font: bytes) -> Any:
    """The source's CFF with every subroutine inlined by fontTools: the program each glyph runs."""
    loaded = _load(font)
    loaded["CFF "].cff.desubroutinize()
    return loaded["CFF "].cff.topDictIndex[0].CharStrings


def _program(charstrings: Any, name: str) -> list[object]:
    charstring = charstrings[name]
    charstring.decompile()
    return list(charstring.program)


def _instructions(glyph: Any) -> bytes:
    program = getattr(glyph, "program", None)
    return b"" if program is None else bytes(program.getBytecode())


def _assert_same(source: bytes, cut: bytes, keep: Iterable[str]) -> None:
    """C2 + C3 + C3b: the cut maps exactly the kept characters the source maps, and each draws
    the outline, advance, hints and kerning it draws with the whole font."""
    kept = _assert_tables_same(source, cut, keep)
    _assert_drawn_same(source, cut, keep, kept)


def _assert_tables_same(source: bytes, cut: bytes, keep: Iterable[str]) -> list[int]:
    """fontTools' reading: cmap, decomposed outlines, metrics, CFF programs, TrueType hints."""
    whole, part = _load(source), _load(cut)
    whole_map, part_map = whole.getBestCmap(), part.getBestCmap()
    # FreeType's mapping decides what the sandbox draws: a code fontTools maps past the font is
    # unmapped there.
    kept = sorted(
        code for code in {ord(character) for character in keep} if _ft(source).get_char_index(code)
    )
    assert set(part_map) == set(kept)
    whole_glyphs, part_glyphs = whole.getGlyphSet(), part.getGlyphSet()
    pairs = [(whole_map[code], part_map[code]) for code in kept]
    for before, after in [(".notdef", ".notdef"), *pairs]:
        drawn = [DecomposingRecordingPen(glyphs) for glyphs in (whole_glyphs, part_glyphs)]
        whole_glyphs[before].draw(drawn[0])
        part_glyphs[after].draw(drawn[1])
        assert drawn[0].value == drawn[1].value, (before, after)
        assert whole["hmtx"][before] == part["hmtx"][after]
        if "vmtx" in whole:
            assert whole["vmtx"][before] == part["vmtx"][after]
    if "CFF " in whole:
        assert all(before == after for before, after in pairs)  # charset: each SID / CID kept
        part_programs = part["CFF "].cff.topDictIndex[0].CharStrings
        for before, after in pairs:
            assert _program(part_programs, after) == _program(_desubroutinized(source), before)
    if "glyf" in whole:
        for before, after in pairs:
            whole_code, part_code = (
                _instructions(font["glyf"][name]) for font, name in ((whole, before), (part, after))
            )
            assert whole_code == part_code
    return kept


def _natively_hinted(font: bytes) -> bool:
    """Whether FreeType hints `font` natively under `DEFAULT`: CFF, or TrueType carrying
    instructions. An instruction-free TrueType font falls back to the autohinter
    (`FT_Load_Glyph`), whose global metrics follow the glyph repertoire, so any cut may move its
    hinted points (Q44 accepted such raster differences); unhinted geometry stays the claim."""
    loaded = _load(font)
    return "CFF " in loaded or bool(
        {"fpgm", "prep"} & set(loaded.keys()) or loaded["maxp"].maxSizeOfInstructions
    )


def _assert_drawn_same(source: bytes, cut: bytes, keep: Iterable[str], kept: list[int]) -> None:
    """FreeType's reading (the sandbox's): mapping, unhinted outlines + advances, natively hinted
    outlines + advances (vmtx feeds TrueType's phantom points, hdmx its advances), kerning."""
    whole_ft, part_ft = _ft(source), _ft(cut)
    for code in kept:
        assert part_ft.get_char_index(code) != 0
        whole_glyph, part_glyph = (
            font.load_char(code, flags=LoadFlags.NO_HINTING) for font in (whole_ft, part_ft)
        )
        assert (whole_glyph.horiAdvance, whole_glyph.linearHoriAdvance, whole_glyph.bbox) == (
            part_glyph.horiAdvance,
            part_glyph.linearHoriAdvance,
            part_glyph.bbox,
        )
        paths = [font.get_path() for font in (whole_ft, part_ft)]
        assert (paths[0][0] == paths[1][0]).all()
        assert (paths[0][1] == paths[1][1]).all()
    for code in {ord(character) for character in keep} - set(kept):
        assert part_ft.get_char_index(code) == 0
    for size in (12, 100) if _natively_hinted(source) else ():
        whole_hinted, part_hinted = (_ft(font, hinting_factor=1) for font in (source, cut))
        for font in (whole_hinted, part_hinted):
            font.set_size(size, 72)
        for code in kept:
            whole_glyph, part_glyph = (
                font.load_char(code, flags=LoadFlags.DEFAULT)
                for font in (whole_hinted, part_hinted)
            )
            assert whole_glyph.horiAdvance == part_glyph.horiAdvance, (size, code)
            whole_path, part_path = whole_hinted.get_path(), part_hinted.get_path()
            assert (whole_path[0] == part_path[0]).all(), (size, code)
    for left in kept[:24]:
        for right in kept[:24]:
            indices = [
                (font.get_char_index(left), font.get_char_index(right))
                for font in (whole_ft, part_ft)
            ]
            assert whole_ft.get_kerning(*indices[0], Kerning.UNSCALED) == part_ft.get_kerning(
                *indices[1], Kerning.UNSCALED
            )


# --- C2 + C3 on real fonts ------------------------------------------------------------------------


def test_q74_the_cff_witness_calls_subroutines_and_masks_hints() -> None:
    """Vacuity guard: the tracked CFF font exercises what the cut inlines."""
    cff = _load(CFF)["CFF "].cff
    top = cff.topDictIndex[0]
    assert len(cff.GlobalSubrs) > 0
    assert sum(len(getattr(font.Private, "Subrs", [])) > 0 for font in top.FDArray) >= 2
    programs = [_program(top.CharStrings, name) for name in top.charset]
    assert any("hintmask" in program for program in programs)
    assert any("callsubr" in program for program in programs)
    assert any("callgsubr" in program for program in programs)


@pytest.mark.parametrize("name", sorted(_REAL))
def test_q74_c3_a_cut_draws_each_kept_character_as_the_whole_font(name: str) -> None:
    source = _REAL[name]
    cut = sfnt.cut(source, _TEXT)
    _assert_same(source, cut, _TEXT)
    assert len(cut) < len(source)


@settings(max_examples=25, deadline=None)
@given(data=st.data())
@pytest.mark.parametrize("name", sorted(_REAL))
def test_q74_c3_any_kept_set_draws_as_the_whole_font(name: str, data: st.DataObject) -> None:
    source = _REAL[name]
    mapped = sorted(map(chr, _load(source).getBestCmap()))
    keep = data.draw(
        st.sets(st.sampled_from(mapped), max_size=30)
        | st.sets(st.sampled_from([*mapped[:40], "週", "\U00020b9f", "\x00"]), max_size=8)
    )
    _assert_same(source, sfnt.cut(source, keep), keep)


def test_q74_c4_the_cut_keeps_names_metrics_and_drops_layout() -> None:
    cut = _load(sfnt.cut(CFF, "患"))
    assert set(cut.keys()) == {
        "GlyphOrder",
        "CFF ",
        "OS/2",
        "cmap",
        "head",
        "hhea",
        "hmtx",
        "maxp",
        "name",
        "post",
        "vhea",
        "vmtx",
    }
    source = _load(CFF)
    assert cut["name"].getDebugName(1) == source["name"].getDebugName(1)
    assert cut["OS/2"].usWeightClass == source["OS/2"].usWeightClass
    assert cut["post"].formatType == 3.0
    assert cut["maxp"].numGlyphs == 2
    assert cut["hhea"].numberOfHMetrics == 2
    assert len(cut["CFF "].cff.GlobalSubrs) == 0
    assert all(
        not hasattr(font.Private, "Subrs") for font in cut["CFF "].cff.topDictIndex[0].FDArray
    )


def test_q74_c4_checksums_hold() -> None:
    for font in (sfnt.cut(TRUETYPE, _TEXT), sfnt.cut(CFF, _TEXT)):
        padded = font + bytes(-len(font) % 4)
        assert sum(struct.unpack(f">{len(padded) // 4}I", padded)) & 0xFFFFFFFF == 0xB1B0AFBA
        loaded = TTFont(io.BytesIO(font), checkChecksums=2)
        for tag in sorted(loaded.reader.tables):
            assert loaded.reader[tag]


def test_q74_c1_a_collection_cuts_its_first_face() -> None:
    collection = TTCollection()
    collection.fonts = [_load(CFF), _load(TRUETYPE)]
    out = io.BytesIO()
    collection.save(out)
    cut = sfnt.cut(out.getvalue(), _TEXT)
    _assert_same(CFF, cut, _TEXT)


def test_q74_c5_the_filter_cut_needs_no_fonttools(monkeypatch: pytest.MonkeyPatch) -> None:
    for module in [name for name in sys.modules if name.split(".")[0] == "fontTools"]:
        monkeypatch.setitem(sys.modules, module, None)
    monkeypatch.setitem(sys.modules, "fontTools", None)
    cut = fonts.cut(CFF, frozenset(_TEXT))
    assert cut != CFF
    assert len(cut) * 2 < len(CFF)


def test_q74_c5_a_refusal_sends_the_whole_font() -> None:
    font = CFF[:5000]
    assert fonts.cut(font, frozenset("患")) == font


# --- built fonts: name-keyed CFF, TrueType composites + kerning, format 12 -----------------------


def _name_keyed(
    programs: Mapping[str, list[object] | bytes],
    local: Iterable[list[object] | bytes] = (),
    global_: Iterable[list[object]] = (),
    order: list[str] | None = None,
    top: Mapping[str, object] | None = None,
) -> bytes:
    """A name-keyed CFF font of `programs` (Type 2 programs, fontTools spelling) mapped A, B, C…"""
    order = order or [".notdef", *sorted(set(programs) - {".notdef"})]
    builder = FontBuilder(1000, isTTF=False)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({0x41 + index: name for index, name in enumerate(order[1:])})
    charstrings = {
        name: T2CharString(bytecode=program)
        if isinstance(program := programs.get(name, [500, "endchar"]), bytes)
        else T2CharString(program=program)
        for name in order
    }
    builder.setupCFF("Built-Regular", {"FullName": "Built"}, charstrings, {})
    builder.setupHorizontalMetrics(dict.fromkeys(order, (600, 0)))
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Built", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    cff = builder.font["CFF "].cff
    font = cff.topDictIndex[0]
    subrs = SubrsIndex()
    for program in local:
        subrs.append(
            T2CharString(bytecode=program)
            if isinstance(program, bytes)
            else T2CharString(program=program)
        )
    if len(subrs):
        font.Private.Subrs = subrs
    shared = GlobalSubrsIndex()
    for program in global_:
        shared.append(T2CharString(program=program))
    cff.GlobalSubrs = shared
    for name in order:
        font.CharStrings[name].private = font.Private
        font.CharStrings[name].globalSubrs = shared
    for key, value in (top or {}).items():
        setattr(font, key, value)
    builder.font.recalcBBoxes = False  # the refusal cases hold programs fontTools cannot run
    out = io.BytesIO()
    builder.font.save(out)
    return out.getvalue()


_LOCAL = [
    [300, 0, "rlineto", "return"],
    [0, 400, "rlineto", "endchar"],
    [*range(0, 180, 10), "hstemhm", "return"],
    [50, "return"],
]
_GLOBAL = [[0, 300, "rlineto", -107, "callsubr", "return"]]
_PROGRAMS: dict[str, list[object]] = {
    "A": [600, 100, 0, "rmoveto", -107, "callsubr", 0, 500, "rlineto", "endchar"],
    "B": [
        600,
        0,
        50,
        100,
        50,
        "hstemhm",
        20,
        30,
        "hintmask",
        b"\xe0",
        100,
        0,
        "rmoveto",
        -107,
        "callgsubr",
        "endchar",
    ],
    "C": [600, 50, 50, "rmoveto", -106, "callsubr"],
    "E": [
        600,
        *range(0, 160, 10),
        "hstemhm",
        5,
        6,
        "hintmask",
        b"\xff\x80",
        0,
        0,
        "rmoveto",
        "endchar",
    ],
    "F": [
        600,
        -105,
        "callsubr",
        "hintmask",
        b"\xff\x80",
        0,
        0,
        "rmoveto",
        10,
        10,
        "rlineto",
        "endchar",
    ],
    "G": [600, 0, 0, "rmoveto", 100, -104, "callsubr", "rlineto", "endchar"],
    "D": [
        600,
        *range(10, 190, 10),
        "vstemhm",
        "hintmask",
        b"\xff\x80",
        0,
        0,
        "rmoveto",
        10,
        10,
        "rlineto",
        "endchar",
    ],
}


def test_q74_c3_name_keyed_subroutines_inline_in_place() -> None:
    """Local + global calls, a nested call, `endchar` inside a subroutine, masks of 3 stems (an
    implicit `vstem`, 1 byte) + 9 stems (2 bytes: declared in place, 8 + an implicit one, or inside
    a subroutine), operands split across a call."""
    source = _name_keyed(_PROGRAMS, _LOCAL, _GLOBAL)
    cut = sfnt.cut(source, "ABCDEFG")
    _assert_same(source, cut, "ABCDEFG")
    programs = _load(cut)["CFF "].cff.topDictIndex[0].CharStrings
    assert _program(programs, "A") == [
        600,
        100,
        0,
        "rmoveto",
        300,
        0,
        "rlineto",
        0,
        500,
        "rlineto",
        "endchar",
    ]
    assert _program(programs, "C") == [600, 50, 50, "rmoveto", 0, 400, "rlineto", "endchar"]
    assert _program(programs, "G") == [600, 0, 0, "rmoveto", 100, 50, "rlineto", "endchar"]


def test_q74_c3_a_subroutine_deeper_than_ten_calls_refuses() -> None:
    """Ten nested calls inline; an eleventh refuses (TN5177's nesting limit)."""

    def chain(length: int) -> list[list[object]]:
        """Subroutine i calls i + 1; the last returns: `length` nested calls from the glyph."""
        return [[index + 1 - 107, "callsubr", "return"] for index in range(length - 1)] + [
            ["return"]
        ]

    glyph: dict[str, list[object] | bytes] = {"A": [600, -107, "callsubr", "endchar"]}
    allowed = _name_keyed(glyph, chain(10))
    _assert_same(allowed, sfnt.cut(allowed, "A"), "A")
    with pytest.raises(sfnt.RefusedError):
        sfnt.cut(_name_keyed(glyph, chain(11)), "A")


@pytest.mark.parametrize(
    "program",
    [
        [600, 1, 2, "add", 100, 0, "rmoveto", "endchar"],  # arithmetic
        [600, 100, 0, "rmoveto", "callsubr", "endchar"],  # an index not just pushed
        [600, 0, 0, 65, 66, "endchar"],  # seac with a width
        [0, 0, 65, 66, "endchar"],  # seac
        [600, "return"],  # return outside a subroutine
        [600, 100, 0, "rmoveto"],  # no endchar
        [600, 5 - 107, "callsubr", "endchar"],  # index past the subroutines
        [600, -107, "callgsubr", "endchar"],  # no global subroutine
        [600, -107, "callsubr", "endchar"],  # no local subroutines
        bytes((248, 236, 139, 140, 18, 19)),  # 600 0 1 hstemhm hintmask, its mask byte missing
    ],
    ids=[
        "arithmetic",
        "computed-index",
        "seac-width",
        "seac",
        "top-return",
        "no-endchar",
        "index-range",
        "no-global",
        "no-local",
        "mask-truncated",
    ],
)
def test_q74_c1_a_charstring_outside_the_cut_s_reading_refuses(
    request: pytest.FixtureRequest, program: list[object] | bytes
) -> None:
    local = [] if request.node.callspec.id == "no-local" else _LOCAL[:1]
    source = _name_keyed({"A": program}, local)
    with pytest.raises((sfnt.RefusedError, IndexError, struct.error)):
        sfnt.cut(source, "A")
    assert fonts.cut(source, frozenset("A")) == source


def test_q74_c1_cff_refusals() -> None:
    """A Type 1 charstring type, SyntheticBase and the predefined ISOAdobe charset refuse."""
    for top in ({"CharstringType": 1}, {"SyntheticBase": 0}):
        with pytest.raises(sfnt.RefusedError):
            sfnt.cut(_name_keyed({"A": [500, "endchar"]}, top=top), "A")
    iso = _name_keyed({}, order=[".notdef", "space", "exclam"])
    with pytest.raises(sfnt.RefusedError):
        sfnt.cut(iso, "A")


def _truetype(kern: dict[tuple[str, str], int] | None = None, *, extra: bool = False) -> bytes:
    """A TrueType font: `A` a box, `B` = `A` scaled; composites whose first component's transform
    (scale, two-by-two, x/y scale) decides where the next component's index sits: `C` = `B` + `A`
    moved by word arguments, `D` = `A` + `B`, `F` = `A` + `C` (nested twice); `kern` = a format 0
    table; `extra` maps U+20B9F (format 12)."""
    builder = FontBuilder(1000, isTTF=True)
    order = [".notdef", "A", "B", "C", "D", "E", "F"]
    builder.setupGlyphOrder(order)
    cmap = {0x41: "A", 0x42: "B", 0x43: "C", 0x44: "D", 0x45: "E", 0x46: "F"}
    if extra:
        cmap[0x20B9F] = "E"
    builder.setupCharacterMap(cmap)
    glyphs: dict[str, Any] = {}
    pen = TTGlyphPen(None)
    for x, y in ((100, 0), (500, 0), (500, 700), (100, 700)):
        (pen.lineTo if x != 100 or y != 0 else pen.moveTo)((x, y))
    pen.closePath()
    glyphs["A"] = pen.glyph()
    glyphs[".notdef"] = glyphs["E"] = TTGlyphPen(None).glyph()
    for name, components in (
        ("B", [("A", (0.5, 0, 0, 0.5, 10, 10))]),
        ("C", [("B", (0.5, 0, 0, 0.5, 0, 0)), ("A", (1, 0, 0, 1, 300, 1000))]),
        ("D", [("A", (0.5, 0.25, -0.25, 0.75, 0, 0)), ("B", (1, 0, 0, 1, 0, 0))]),
        ("F", [("A", (0.5, 0, 0, 0.75, 0, 0)), ("C", (1, 0, 0, 1, -20, 5))]),
    ):
        pen = TTGlyphPen(glyphs)
        for component, transform in components:
            pen.addComponent(component, transform)
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(dict.fromkeys(order, (600, 100)))
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "BuiltTT", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    if kern is not None:
        table = KernTable_format_0()
        table.version, table.coverage, table.format, table.apple = 0, 1, 0, False
        table.kernTable = kern
        builder.font["kern"] = newTable("kern")
        builder.font["kern"].version = 0
        builder.font["kern"].kernTables = [table]
    out = io.BytesIO()
    builder.font.save(out)
    return out.getvalue()


def test_q74_c3_composites_close_over_their_components() -> None:
    """`F` keeps `C`, `B` + `A` though only `F` is kept; every transform form survives."""
    source = _truetype()
    cut = sfnt.cut(source, "FD")
    _assert_same(source, cut, "FD")
    assert _load(cut)["maxp"].numGlyphs == 6


def test_q74_c2_a_glyph_past_the_font_stays_unmapped() -> None:
    """`Z` maps to glyph 99 of a 7-glyph font: FreeType and the cut both leave it unmapped."""
    format4 = struct.pack(">7H", 4, 40, 0, 6, 4, 1, 2) + struct.pack(
        ">3H2x3H3H3H",
        0x41,
        0x5A,
        0xFFFF,
        0x41,
        0x5A,
        0xFFFF,
        (1 - 0x41) & 0xFFFF,
        99 - 0x5A,
        1,
        0,
        0,
        0,
    )
    source = _patched(_truetype(), cmap=_cmap((3, 1, format4)))
    assert [_ft(source).get_char_index(code) for code in (0x41, 0x5A)] == [1, 0]
    _assert_same(source, sfnt.cut(source, "AZ"), "AZ")


def test_q74_c3_kerning_keeps_the_kept_pairs() -> None:
    source = _truetype({("A", "B"): -50, ("B", "A"): 30, ("A", "D"): 7, ("D", "A"): -9})
    cut = sfnt.cut(source, "AB")
    _assert_same(source, cut, "AB")
    pairs = _load(cut)["kern"].kernTables[0].kernTable
    assert sorted(pairs.values()) == [-50, 30]


def test_q74_c4_a_supplementary_character_maps_through_format_12() -> None:
    source = _truetype(extra=True)
    cut = sfnt.cut(source, "A\U00020b9f")
    _assert_same(source, cut, "A\U00020b9f")
    assert {
        (table.platformID, table.platEncID, table.format) for table in _load(cut)["cmap"].tables
    } == {(3, 1, 4), (3, 10, 12)}


# --- C1 refusals on table structure ---------------------------------------------------------------


def _tables(font: bytes) -> dict[bytes, bytes]:
    count = struct.unpack_from(">H", font, 4)[0]
    found = {}
    for record in range(12, 12 + 16 * count, 16):
        offset, length = struct.unpack_from(">II", font, record + 8)
        found[font[record : record + 4]] = font[offset : offset + length]
    return found


def _sfnt(version: bytes, tables: dict[bytes, bytes]) -> bytes:
    """An sfnt of `tables` in the given order, checksums zero: the test's own writer."""
    out = version + struct.pack(">HHHH", len(tables), 0, 0, 0)
    offset = 12 + 16 * len(tables)
    body = b""
    for tag, data in tables.items():
        out += tag + struct.pack(">III", 0, offset + len(body), len(data))
        body += data + bytes(-len(data) % 4)
    return out + body


def _patched(font: bytes, **changes: bytes | None) -> bytes:
    tables = _tables(font)
    for name, data in changes.items():
        tag = name.replace("_", " ").encode().ljust(4)[:4] if name != "OS2" else b"OS/2"
        if data is None:
            tables.pop(tag)
        else:
            tables[tag] = data
    return _sfnt(font[:4], tables)


def _cmap(*subtables: tuple[int, int, bytes]) -> bytes:
    out = struct.pack(">HH", 0, len(subtables))
    offset = 4 + 8 * len(subtables)
    for platform, encoding, data in subtables:
        out += struct.pack(">HHI", platform, encoding, offset)
        offset += len(data)
    return out + b"".join(data for _platform, _encoding, data in subtables)


_FORMAT_6 = struct.pack(">HHHHH", 6, 12, 0, 0x41, 1) + struct.pack(">H", 1)
_FORMAT_4_A = struct.pack(
    ">HHHHHHHHHHHHHHHH",
    4,
    32,
    0,
    4,
    4,
    1,
    0,
    0x41,
    0xFFFF,
    0,
    0x41,
    0xFFFF,
    (1 - 0x41) & 0xFFFF,
    1,
    0,
    0,
)


def _kern(*subtables: bytes, version: int = 0) -> bytes:
    return struct.pack(">HH", version, len(subtables)) + b"".join(subtables)


def _kern_subtable(
    pairs: list[tuple[int, int, int]], coverage: int = 1, length: int | None = None
) -> bytes:
    body = b"".join(struct.pack(">HHh", *pair) for pair in pairs)
    size = 14 + len(body) if length is None else length
    return struct.pack(">HHHHHHH", 0, size, coverage, len(pairs), 0, 0, 0) + body


@pytest.mark.parametrize(
    "case",
    [
        "cff2",
        "fvar",
        "symbol-cmap",
        "format-6-cmap",
        "no-outline",
        "outline-mismatch",
        "apple-kern",
        "kern-format-2",
        "kern-length",
        "kern-duplicate",
        "no-long-metrics",
        "short-post",
        "table-past-end",
        "duplicate-tag",
        "empty-collection",
        "truncated",
    ],
)
def test_q74_c1_a_table_outside_the_cut_s_reading_refuses(case: str) -> None:
    font = _truetype()
    hhea = _tables(font)[b"hhea"]
    builds = {
        "cff2": lambda: _patched(font, CFF2=b"\x02\x00\x05\x00"),
        "fvar": lambda: _patched(font, fvar=bytes(16)),
        "symbol-cmap": lambda: _patched(font, cmap=_cmap((3, 0, _FORMAT_4_A))),
        "format-6-cmap": lambda: _patched(font, cmap=_cmap((3, 1, _FORMAT_6))),
        "no-outline": lambda: _patched(font, glyf=None, loca=None),
        "outline-mismatch": lambda: b"OTTO" + _patched(font)[4:],
        "apple-kern": lambda: _patched(font, kern=_kern(_kern_subtable([(1, 2, -5)]), version=1)),
        "kern-format-2": lambda: _patched(font, kern=_kern(_kern_subtable([], coverage=0x0201))),
        "kern-length": lambda: _patched(font, kern=_kern(_kern_subtable([(1, 2, -5)], length=26))),
        "kern-duplicate": lambda: _patched(
            font, kern=_kern(_kern_subtable([(1, 2, -5), (1, 2, -6)]))
        ),
        "no-long-metrics": lambda: _patched(font, hhea=hhea[:34] + b"\x00\x00"),
        "short-post": lambda: _patched(font, post=bytes(20)),
        "table-past-end": lambda: font[:20] + struct.pack(">I", len(font)) + font[24:],
        "duplicate-tag": lambda: font[:28] + font[12:16] + font[32:],
        "empty-collection": lambda: b"ttcf\x00\x01\x00\x00\x00\x00\x00\x00" + font,
        "truncated": lambda: font[: len(font) // 2],
    }
    refused = builds[case]()
    with pytest.raises((sfnt.RefusedError, struct.error, KeyError, IndexError)):
        sfnt.cut(refused, "AB")
    assert fonts.cut(refused, frozenset("AB")) == refused


def test_q74_c1_the_built_font_cuts_before_each_refusal() -> None:
    """Positive control for the refusals above: the unpatched font, re-written by the test's own
    writer, cuts and draws as the whole font."""
    font = _patched(_truetype({("A", "B"): -50}))
    _assert_same(font, sfnt.cut(font, "AB"), "AB")


# --- consultant-1's discriminators: what raw byte + pen equality alone would miss ----------------


def _hinted(*, hdmx: bool = False) -> bytes:
    """`A`'s instruction moves point 0 to vertical phantom point 6 (its `vmtx` metrics) under
    native hinting; `hdmx` gives each glyph its own advance at 100 ppem."""
    builder = FontBuilder(1000, isTTF=True)
    order = [".notdef", "A", "B"]
    builder.setupGlyphOrder(order)
    glyphs = {}
    for name in order:
        pen = TTGlyphPen(None)
        pen.moveTo((0, 0))
        for point in ((200, 0), (200, 200), (0, 200)):
            pen.lineTo(point)
        pen.closePath()
        glyphs[name] = pen.glyph()
    program = Program()
    program.fromAssembly(["SVTCA[0]", "PUSHB[ ]", "0", "6", "GC[0]", "SCFS[ ]"])
    glyphs["A"].program = program
    builder.setupCharacterMap({0x41: "A", 0x42: "B"})
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(dict.fromkeys(order, (500, 0)))
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupVerticalMetrics({".notdef": (900, 100), "A": (900, 150), "B": (700, 100)})
    builder.setupVerticalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Hinted", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupPost()
    builder.font["maxp"].maxStackElements = 16
    builder.font["maxp"].maxZones = 2
    builder.font["maxp"].maxSizeOfInstructions = len(program.getBytecode())
    if hdmx:
        builder.font["head"].flags |= 16  # instructions may alter advance widths
        table = newTable("hdmx")
        table.hdmx = {100: {".notdef": 70, "A": 88, "B": 60}}
        builder.font["hdmx"] = table
        thresholds = newTable("LTSH")
        thresholds.yPels = {".notdef": 1, "A": 9, "B": 5}
        builder.font["LTSH"] = thresholds
    out = io.BytesIO()
    builder.font.save(out)
    return out.getvalue()


@pytest.mark.parametrize("hdmx", [False, True], ids=["vmtx", "hdmx"])
def test_q74_c3_native_hinting_reads_the_kept_vertical_metrics_and_device_widths(
    *, hdmx: bool
) -> None:
    """Dropping `vmtx` moves `A`'s hinted point 0 at 100 ppem; dropping `hdmx` changes its hinted
    advance (consultant-1 Q3, measured on the host FreeType)."""
    source = _hinted(hdmx=hdmx)
    cut = sfnt.cut(source, "AB")  # 3 glyphs: a 5-byte hdmx record pads to 8
    _assert_same(source, cut, "AB")
    tables = _load(cut)
    assert tables["vmtx"]["A"] == (900, 150)
    if hdmx:
        assert tables["hdmx"].hdmx[100]["A"] == 88
        assert struct.unpack_from(">I", _tables(cut)[b"hdmx"], 4)[0] % 4 == 0  # 32-bit records
        assert tables["LTSH"].yPels["A"] == 9


def test_q74_c1_the_cut_reads_the_cmap_freetype_selects() -> None:
    """(0, 4) format 12 maps `A` to glyph 2 (`B`, a half-size composite), the later (3, 1) format 4
    to glyph 1: FreeType prefers the 32-bit subtable over the last one, so the cut keeps glyph 2
    under `A`."""
    font = _truetype()
    format12 = struct.pack(">HHIII", 12, 0, 28, 0, 1) + struct.pack(">III", 0x41, 0x41, 2)
    source = _patched(font, cmap=_cmap((0, 4, format12), (3, 1, _FORMAT_4_A)))
    assert _ft(source).get_char_index(0x41) == 2
    cut = sfnt.cut(source, "A")
    _assert_same(source, cut, "A")
    loaded = _load(cut)
    assert loaded["glyf"][loaded.getBestCmap()[0x41]].isComposite()


def test_q74_c4_font_matrices_stay_with_their_dicts() -> None:
    """A Top DICT matrix (name-keyed) and a Font DICT matrix (CID-keyed) scale what FreeType draws;
    raw program + pen equality alone would miss a lost one."""
    matrix = [0.002, 0, 0, 0.001, 0, 0]
    named = _name_keyed(_PROGRAMS, _LOCAL, _GLOBAL, top={"FontMatrix": matrix})
    _assert_same(named, sfnt.cut(named, "ABCD"), "ABCD")
    loaded = _load(CFF)
    top = loaded["CFF "].cff.topDictIndex[0]
    kanji = top.FDSelect[loaded.getGlyphID(loaded.getBestCmap()[ord("患")])]
    top.FDArray[kanji].FontMatrix = matrix
    out = io.BytesIO()
    loaded.save(out)
    _assert_same(out.getvalue(), sfnt.cut(out.getvalue(), _TEXT), _TEXT)


def test_q74_c3_kerning_keeps_each_subtable_and_its_override() -> None:
    loaded = _load(_truetype({("A", "B"): -50, ("B", "A"): 30}))
    second = KernTable_format_0()
    second.version, second.coverage, second.format, second.apple = 0, 1 | 8, 0, False
    second.kernTable = {("A", "B"): -20, ("C", "A"): 12}
    loaded["kern"].kernTables.append(second)
    out = io.BytesIO()
    loaded.save(out)
    source = out.getvalue()
    cut = sfnt.cut(source, "ABC")
    _assert_same(source, cut, "ABC")
    assert [table.coverage for table in _load(cut)["kern"].kernTables] == [1, 9]


@pytest.mark.parametrize("count", [1239, 1240, 33899, 33900])
def test_q74_c3_a_call_index_carries_its_index_s_bias(count: int) -> None:
    """TN5177: bias 107 below 1,240 subroutines, 1,131 below 33,900, else 32,768; the last one
    draws, every other returns at once."""
    bias = 107 if count < 1240 else 1131 if count < 33900 else 32768
    returns: list[object] = ["return"]
    local = [returns] * (count - 1) + [[0, 400, "rlineto", "return"]]
    glyph: dict[str, list[object] | bytes] = {
        "A": [600, 50, 50, "rmoveto", count - 1 - bias, "callsubr", "endchar"]
    }
    source = _name_keyed(glyph, local)
    cut = sfnt.cut(source, "A")
    _assert_same(source, cut, "A")
    assert _program(_load(cut)["CFF "].cff.topDictIndex[0].CharStrings, "A") == [
        600,
        50,
        50,
        "rmoveto",
        0,
        400,
        "rlineto",
        "endchar",
    ]


_FORMAT_4_ARRAY = struct.pack(">7H", 4, 36, 0, 4, 4, 1, 0) + struct.pack(
    ">2H2x2H2H2H2H", 0x42, 0xFFFF, 0x41, 0xFFFF, 0, 1, 4, 0, 2, 1
)
_FORMAT_14 = struct.pack(">HII", 14, 10, 0)


def test_q74_c1_format_4_glyph_arrays_map_as_freetype_maps() -> None:
    """A format 4 segment through `idRangeOffset` (A -> 2, B -> 1); a format 14 subtable before
    it leaves FreeType's choice (the last Unicode subtable) unchanged."""
    source = _patched(_truetype(), cmap=_cmap((0, 5, _FORMAT_14), (3, 1, _FORMAT_4_ARRAY)))
    assert [_ft(source).get_char_index(code) for code in (0x41, 0x42)] == [2, 1]
    _assert_same(source, sfnt.cut(source, "AB"), "AB")


def test_q74_c1_a_variation_subtable_freetype_selects_refuses() -> None:
    """Last among the Unicode subtables, a format 14 subtable is FreeType's choice, and it maps no
    character: the whole font draws none, so the cut refuses rather than map them."""
    source = _patched(_truetype(), cmap=_cmap((0, 3, _FORMAT_4_ARRAY), (0, 5, _FORMAT_14)))
    assert [_ft(source).get_char_index(code) for code in (0x41, 0x42)] == [0, 0]
    with pytest.raises(sfnt.RefusedError):
        sfnt.cut(source, "AB")


def test_q74_c4_tables_align_on_four_bytes() -> None:
    for font in (
        sfnt.cut(TRUETYPE, _TEXT),
        sfnt.cut(CFF, _TEXT),
        sfnt.cut(_hinted(hdmx=True), "A"),
    ):
        count = struct.unpack_from(">H", font, 4)[0]
        records = [struct.unpack_from(">4sIII", font, 12 + 16 * index) for index in range(count)]
        assert [record[0] for record in records] == sorted(record[0] for record in records)
        assert all(offset % 4 == 0 for _tag, _sum, offset, _length in records)
        assert max(offset + length for _tag, _sum, offset, length in records) <= len(font)


def _format4(segments: list[tuple[int, int, int, int]], length: int | None = None) -> bytes:
    """A format 4 subtable of (start, end, delta, range offset) segments, in the order given."""
    count = len(segments)
    body = struct.pack(f">{count}H", *(segment[1] for segment in segments)) + b"\x00\x00"
    for field in (0, 2, 3):
        body += struct.pack(f">{count}H", *(segment[field] & 0xFFFF for segment in segments))
    size = 14 + len(body) if length is None else length
    return struct.pack(">7H", 4, size, 0, 2 * count, 0, 0, 0) + body


def _format12(groups: list[tuple[int, int, int]], length: int | None = None) -> bytes:
    size = 16 + 12 * len(groups) if length is None else length
    return struct.pack(">HHIII", 12, 0, size, 0, len(groups)) + b"".join(
        struct.pack(">III", *group) for group in groups
    )


_END = (0xFFFF, 0xFFFF, 1, 0)


def _with_count(subtable: bytes, doubled: int) -> bytes:
    return subtable[:6] + struct.pack(">H", doubled) + subtable[8:]


def test_q74_c1_a_glyph_array_past_its_subtable_refuses() -> None:
    """The selected subtable's glyph array runs into the bytes of the subtable after it, inside
    the `cmap` table."""
    chosen = _format4([(0x41, 0x46, 0, 6), _END])
    other = _format4([(0x41, 0x46, 1 - 0x41, 0), _END])
    header = struct.pack(">HH", 0, 2)
    first = 4 + 16
    records = struct.pack(">HHI", 0, 3, first + len(chosen)) + struct.pack(">HHI", 3, 1, first)
    source = _patched(_truetype(), cmap=header + records + chosen + other)
    with pytest.raises(sfnt.RefusedError):
        sfnt.cut(source, "AB")


@pytest.mark.parametrize(
    "subtable",
    [
        _format4([(0x41, 0x46, 1 - 0x41, 0), (0x44, 0x48, 2 - 0x44, 0), _END]),  # overlapping
        _format4([(0x44, 0x46, 1 - 0x44, 0), (0x41, 0x42, 2 - 0x41, 0), _END]),  # unsorted
        _format4([(0x41, 0x46, 1 - 0x41, 0)]),  # no U+FFFF end
        _format4([(0x46, 0x41, 1 - 0x41, 0), _END]),  # start past end
        _format4([(0x41, 0x46, 0, 0xFFFF), _END]),  # range offset 0xFFFF
        _format4([(0x41, 0x46, 0, 40), _END]),  # glyph array past the subtable
        _format4([(0x41, 0x46, 1 - 0x41, 0), _END], length=400),  # past the table
        _with_count(_format4([(0x41, 0x46, 1 - 0x41, 0), _END]), 5),  # odd count, else valid
        _format4([(0x41, 0x46, 1 - 0x41, 0), _END], length=20),  # arrays past its length
        _format4([]),  # no segment
        _format12([(0x44, 0x46, 1), (0x41, 0x42, 2)]),  # unsorted groups
        _format12([(0x41, 0x46, 1), (0x46, 0x48, 2)]),  # overlapping groups
        _format12([(0x46, 0x41, 1)]),  # start past end
        _format12([(0x41, 0x46, 1)], length=400),  # past the table
        _format12([(0x41, 0x46, 1), (0x47, 0x48, 2)], length=28),  # groups past its length
    ],
    ids=[
        "4-overlap",
        "4-unsorted",
        "4-no-end",
        "4-start-past-end",
        "4-offset-ffff",
        "4-array-past-subtable",
        "4-past-table",
        "4-odd-count",
        "4-short-length",
        "4-empty",
        "12-unsorted",
        "12-overlap",
        "12-start-past-end",
        "12-past-table",
        "12-groups-past-length",
    ],
)
def test_q74_c1_a_cmap_freetype_may_read_otherwise_refuses(subtable: bytes) -> None:
    source = _patched(_truetype(), cmap=_cmap((3, 1 if subtable[1] == 4 else 10, subtable)))
    with pytest.raises(sfnt.RefusedError):
        sfnt.cut(source, "AB")


def test_q74_c1_the_cmap_fixtures_cut_when_well_formed() -> None:
    """Positive control for the refusals above: the same builders, well formed."""
    for subtable in (
        _format4([(0x41, 0x43, 1 - 0x41, 0), (0x44, 0x46, 4 - 0x44, 0), _END]),
        _format12([(0x41, 0x43, 1), (0x44, 0x46, 4)]),
    ):
        source = _patched(_truetype(), cmap=_cmap((3, 1 if subtable[1] == 4 else 10, subtable)))
        _assert_same(source, sfnt.cut(source, "ABCDEF"), "ABCDEF")


@pytest.mark.parametrize("case", ["vmtx-alone", "vhea-alone", "hdmx-short", "ltsh-count"])
def test_q74_c1_a_per_glyph_table_the_cut_cannot_subset_refuses(case: str) -> None:
    font = _hinted(hdmx=True)
    tables = _tables(font)
    hdmx, ltsh = tables[b"hdmx"], tables[b"LTSH"]
    edits: dict[str, dict[str, bytes | None]] = {
        "vmtx-alone": {"vhea": None},
        "vhea-alone": {"vmtx": None},
        "hdmx-short": {"hdmx": hdmx[:4] + struct.pack(">I", 4) + hdmx[8:]},
        "ltsh-count": {"LTSH": ltsh[:2] + struct.pack(">H", 2) + ltsh[4:]},
    }
    changes = edits[case]
    refused = _patched(font, **changes)
    with pytest.raises(sfnt.RefusedError):
        sfnt.cut(refused, "A")
    assert fonts.cut(refused, frozenset("A")) == refused


def test_q74_c3_a_format_0_font_select_cuts() -> None:
    loaded = _load(CFF)
    loaded["CFF "].cff.topDictIndex[0].FDSelect.format = 0
    out = io.BytesIO()
    loaded.save(out)
    source = out.getvalue()
    assert _load(source)["CFF "].cff.topDictIndex[0].FDSelect.format == 0
    _assert_same(source, sfnt.cut(source, _TEXT), _TEXT)


def test_q74_c2_two_characters_of_one_glyph_share_it() -> None:
    """`A` + `B` map to one glyph, so the cut's runs of consecutive codes must not run on."""
    builder = _load(_truetype())
    for table in builder["cmap"].tables:
        table.cmap[0x42] = "A"
    out = io.BytesIO()
    builder.save(out)
    source = out.getvalue()
    _assert_same(source, sfnt.cut(source, "ABC"), "ABC")


def _kern_pairs(font: bytes) -> list[tuple[int, int]]:
    table = _tables(font)[b"kern"]
    count = struct.unpack_from(">H", table, 10)[0]
    return [struct.unpack_from(">HH", table, 18 + 6 * index) for index in range(count)]


def test_q74_c3_kern_pairs_stay_sorted_after_renumbering() -> None:
    """`Z` precedes `A` in the source's glyph order, the cut's codes put `A` first: the pairs the
    renumbering unsorts sort again (OpenType kern format 0)."""
    builder = FontBuilder(1000, isTTF=True)
    order = [".notdef", "Z", "A"]
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({0x41: "A", 0x5A: "Z"})
    builder.setupGlyf({name: TTGlyphPen(None).glyph() for name in order})
    builder.setupHorizontalMetrics(dict.fromkeys(order, (600, 0)))
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Kerned", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    table = KernTable_format_0()
    table.version, table.coverage, table.format, table.apple = 0, 1, 0, False
    table.kernTable = {("Z", "A"): -5, ("A", "Z"): 7}
    builder.font["kern"] = newTable("kern")
    builder.font["kern"].version = 0
    builder.font["kern"].kernTables = [table]
    out = io.BytesIO()
    builder.font.save(out)
    source = out.getvalue()
    cut = sfnt.cut(source, "AZ")
    _assert_same(source, cut, "AZ")
    assert _kern_pairs(cut) == sorted(_kern_pairs(cut)) == [(1, 2), (2, 1)]


def test_q74_c4_a_cut_keeping_some_font_dicts_renumbers_them() -> None:
    """One kanji keeps `.notdef`'s Font DICT + its own of the CFF witness's several."""
    cut = sfnt.cut(CFF, "患")
    _assert_same(CFF, cut, "患")
    assert len(_load(cut)["CFF "].cff.topDictIndex[0].FDArray) < len(
        _load(CFF)["CFF "].cff.topDictIndex[0].FDArray
    )


# Local subroutine 4 starts a path, so a call may directly follow a mask.
_PATH_LOCAL = [*_LOCAL, [10, 10, "rmoveto", 300, 0, "rlineto", "return"]]


@pytest.mark.parametrize(
    "program",
    [
        [600, 0, 50, 100, 50, "hstemhm", 20, 30, "hintmask", b"\x1c", -103, "callsubr", "endchar"],
        [
            600,
            *range(0, 160, 10),
            "hstemhm",
            5,
            6,
            "hintmask",
            b"\xff\x1c",
            -103,
            "callsubr",
            "endchar",
        ],
    ],
    ids=["three-stems", "implicit-ninth-stem"],
)
def test_q74_c3_a_call_after_a_mask_inlines(program: list[object]) -> None:
    """Each mask's last byte is 28, an integer's prefix: miscounted mask bytes would read the call
    after it as an operand and leave it unexpanded."""
    source = _name_keyed({"A": program}, _PATH_LOCAL)
    cut = sfnt.cut(source, "A")
    _assert_same(source, cut, "A")
    assert "callsubr" not in _program(_load(cut)["CFF "].cff.topDictIndex[0].CharStrings, "A")


def test_q74_c1_a_mask_cut_short_by_its_subroutine_refuses() -> None:
    """A subroutine ending in `hintmask` without its mask byte: the caller's bytes would become the
    mask in the flattened glyph."""
    local: list[list[object] | bytes] = [bytes((139, 140, 18, 19))]  # 0 1 hstemhm hintmask
    source = _name_keyed({"A": [600, -107, "callsubr", 10, 10, "rmoveto", "endchar"]}, local)
    with pytest.raises(sfnt.RefusedError):
        sfnt.cut(source, "A")


def test_q74_c1_a_repeated_table_tag_refuses() -> None:
    """`post`'s record renamed `name`: the second `name` would replace the first unseen."""
    font = _truetype()
    count = struct.unpack_from(">H", font, 4)[0]
    record = next(
        12 + 16 * index for index in range(count) if font[12 + 16 * index :][:4] == b"post"
    )
    refused = font[:record] + b"name" + font[record + 4 :]
    with pytest.raises(sfnt.RefusedError):
        sfnt.cut(refused, "AB")


def test_q74_c3_a_subroutine_ends_in_return_or_endchar() -> None:
    """TN5177: bytes after a subroutine's `return`, or a subroutine running off its end, refuse
    (reviewer-1 R1)."""
    glyph: dict[str, list[object] | bytes] = {
        "A": [600, 50, 50, "rmoveto", -107, "callsubr", "endchar"]
    }
    for subroutine in ([0, 400, "rlineto", "return", 0, 10, "rlineto"], [0, 400, "rlineto"]):
        with pytest.raises(sfnt.RefusedError):
            sfnt.cut(_name_keyed(glyph, [subroutine]), "A")
    well_formed = _name_keyed(glyph, [[0, 400, "rlineto", "return"]])
    _assert_same(well_formed, sfnt.cut(well_formed, "A"), "A")


def test_q74_c4_inlining_reads_at_most_the_font_s_length() -> None:
    """Each subroutine calls the next eight times: a font under 1 KB would inline 8 ** 4 leaf
    calls; the cut reads no more bytes than the font holds, then refuses (reviewer-1 R5)."""
    fan: list[list[object] | bytes] = [
        [*([index + 1 - 107, "callsubr"] * 8), "return"] for index in range(4)
    ]
    fan.append([0, 1, "rlineto", "return"])
    source = _name_keyed({"A": [600, 0, 0, "rmoveto", -107, "callsubr", "endchar"]}, fan)
    with pytest.raises(sfnt.RefusedError):
        sfnt.cut(source, "A")
    assert fonts.cut(source, frozenset("A")) == source


def test_q74_c4_per_glyph_tables_follow_the_kept_glyph_order() -> None:
    """`B` alone moves from glyph 2 to glyph 1: its own hdmx width + LTSH threshold come along,
    not the ones of the glyph that held its new index (reviewer-1 F4)."""
    source = _hinted(hdmx=True)
    cut = sfnt.cut(source, "B")
    _assert_same(source, cut, "B")
    tables = _load(cut)
    assert tables["hdmx"].hdmx[100]["B"] == 60
    assert tables["LTSH"].yPels["B"] == 5


def _cff_index(items: list[bytes]) -> bytes:
    offsets = [1]
    for item in items:
        offsets.append(offsets[-1] + len(item))
    return struct.pack(">HB", len(items), 1) + bytes(offsets) + b"".join(items)


def _repeated_charstrings() -> bytes:
    """A name-keyed CFF whose Top DICT names `CharStrings` twice: `A` draws 100 wide in the
    first, 500 in the second, which FreeType keeps (reviewer-1 F1)."""

    def program(width: int) -> bytes:
        charstring = T2CharString(
            program=[600, 0, 0, "rmoveto", width, 0, "rlineto", 0, 400, "rlineto", "endchar"]
        )
        charstring.compile()
        return bytes(charstring.bytecode)

    def integer(value: int) -> bytes:
        return b"\x1d" + struct.pack(">i", value)

    notdef = T2CharString(program=[600, "endchar"])
    notdef.compile()
    names = _cff_index([b"Built-Regular"])
    first, second = (_cff_index([bytes(notdef.bytecode), program(w)]) for w in (100, 500))
    charset = b"\x00\x00\x22"  # SID 34 = A

    def top(charset_at: int, first_at: int, second_at: int, end: int) -> bytes:
        return _cff_index(
            [
                integer(charset_at)
                + b"\x0f"
                + integer(first_at)
                + b"\x11"
                + integer(second_at)
                + b"\x11"
                + integer(0)
                + integer(end)
                + b"\x12"
            ]
        )

    start = 4 + len(names) + len(top(0, 0, 0, 0)) + 4
    first_at = start + len(charset)
    second_at = first_at + len(first)
    end = second_at + len(second)
    cff = b"\x01\x00\x04\x04" + names + top(start, first_at, second_at, end) + bytes(4)
    cff += charset + first + second
    return _patched(_name_keyed({"A": [600, "endchar"]}), CFF_=cff)


def test_q74_c1_a_repeated_dict_operator_refuses() -> None:
    """FreeType keeps a repeated DICT operator's last value; a cut reading one would draw `A` from
    the other `CharStrings`."""
    source = _repeated_charstrings()
    whole = _ft(source)
    whole.load_char(ord("A"), flags=LoadFlags.NO_HINTING)
    assert whole.get_path()[0][:, 0].max() > 5  # FreeType drew the second, 500-unit `A`
    with pytest.raises(sfnt.RefusedError):
        sfnt.cut(source, "A")
    assert fonts.cut(source, frozenset("A")) == source


def test_q74_c1_a_cff_version_or_font_select_outside_the_reading_refuses() -> None:
    """A CFF header other than version 1; an FDSelect format other than 0 or 3, kept to `、`, the
    one character in Font DICT 0, so no other refusal can stand in (reviewer-1 F5)."""
    named = _name_keyed({"A": [500, "endchar"]})
    cff = _tables(named)[b"CFF "]
    at = _load(CFF)["CFF "].cff.topDictIndex[0].rawDict["FDSelect"]
    table = _tables(CFF)[b"CFF "]
    for font, keep in (
        (_patched(named, CFF_=b"\x02" + cff[1:]), "A"),
        (_patched(CFF, CFF_=table[:at] + b"\x04" + table[at + 1 :]), "\u3001"),
    ):
        with pytest.raises(sfnt.RefusedError):
            sfnt.cut(font, keep)
        assert fonts.cut(font, frozenset(keep)) == font


def test_q74_c4_an_inlined_glyph_past_65535_bytes_refuses() -> None:
    """TN5177 Appendix B caps a charstring at 65,535 bytes: `A` calls a 40 KB subroutine twice.
    An unused 100 KB subroutine makes the font longer than what the cut reads, so the length
    limit decides, not the read budget (reviewer-1 F2)."""
    stroke: list[object] = [0, 0, "rlineto"] * 13_334 + ["return"]
    padding: list[object] = [0, 0, "rlineto"] * 33_334 + ["return"]
    glyph: dict[str, list[object] | bytes] = {
        "A": [600, 0, 0, "rmoveto", -107, "callsubr", -107, "callsubr", "endchar"]
    }
    source = _name_keyed(glyph, [stroke, padding])
    assert len(source) > 2 * 40_002 + 4
    with pytest.raises(sfnt.RefusedError):
        sfnt.cut(source, "A")
    once = _name_keyed({"A": [600, 0, 0, "rmoveto", -107, "callsubr", "endchar"]}, [stroke])
    assert len(sfnt.cut(once, "A")) < len(once)


def test_q74_c4_mask_bytes_count_against_the_read_budget() -> None:
    """96 stems make every hint mask 12 bytes: 160 calls into a subroutine holding one mask read
    more bytes than the font holds, masks included (reviewer-1 RF2)."""
    glyph: list[object] = [600]
    for pairs in (22, 22, 22, 22, 8):
        glyph += [0, 1] * pairs + ["hstemhm"]
    glyph += [-107, "callsubr"] * 160 + [0, 0, "rmoveto", 100, 100, "rlineto", "endchar"]
    source = _name_keyed({"A": glyph}, [["hintmask", bytes([255] * 12), "return"]])
    with pytest.raises(sfnt.RefusedError):
        sfnt.cut(source, "A")
    assert fonts.cut(source, frozenset("A")) == source
