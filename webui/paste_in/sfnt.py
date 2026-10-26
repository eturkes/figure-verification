# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""An sfnt font cut to the glyphs of some characters, with the standard library alone (Q74).

The filter sends the server's Japanese font inside the RPC (`fonts.py`), and Open WebUI 0.12.3's
image holds no fontTools, so this cut is what keeps that RPC small on every server. The cut is part
of the trusted font: no later check reads glyph shapes, so a kept character must draw exactly as it
draws with the whole font. Glyph programs therefore stay byte for byte -- a CFF glyph with its
subroutine calls inlined in place, a TrueType composite with its component indices renumbered --
and the horizontal metrics, naming and OS/2 tables come along unchanged.

A structure this module does not fully handle raises `RefusedError`, damaged bytes raise a parse
error, and the caller sends the whole font: a refusal costs bytes, never a glyph.
"""

import bisect
import itertools
import struct
from collections.abc import Callable, Iterable
from typing import Final

_TRUETYPE: Final = frozenset({b"\x00\x01\x00\x00", b"true"})
_CFF_VERSION: Final = b"OTTO"
_COLLECTION: Final = b"ttcf"
# The closed table set. Copied unchanged: tables that name no glyph -- names, OS/2 metrics, the
# TrueType hinting programs + per-size tables. Rebuilt: every table indexed by glyph that FreeType
# reads while drawing a horizontal glyph, natively hinted included (vertical metrics feed TrueType's
# phantom points, `hdmx` its hinted advances). Dropped: tables only layout engines or vertical
# text read. Any other table (variations, CFF2, embedded bitmaps, colour) refuses the cut.
_VERBATIM: Final = frozenset({b"OS/2", b"name", b"cvt ", b"fpgm", b"prep", b"gasp", b"VDMX"})
_REBUILT: Final = frozenset(
    {
        b"head",
        b"hhea",
        b"hmtx",
        b"maxp",
        b"cmap",
        b"post",
        b"glyf",
        b"loca",
        b"CFF ",
        b"kern",
        b"vhea",
        b"vmtx",
        b"hdmx",
        b"LTSH",
    }
)
_DROPPED: Final = frozenset(
    {
        b"GSUB",
        b"GPOS",
        b"GDEF",
        b"BASE",
        b"JSTF",
        b"MATH",
        b"VORG",
        b"DSIG",
        b"meta",
        b"STAT",
        b"FFTM",
        b"PCLT",
    }
)
_HEAD_ADJUSTMENT: Final = 8
_HEAD_LOCA_FORMAT: Final = 50
_HHEA_METRICS: Final = 34
_MAXP_GLYPHS: Final = 4
_POST_HEADER: Final = 32
_CHECKSUM_MAGIC: Final = 0xB1B0AFBA

# TrueType composite component flags.
_ARGS_ARE_WORDS: Final = 0x0001
_HAVE_SCALE: Final = 0x0008
_MORE_COMPONENTS: Final = 0x0020
_HAVE_XY_SCALE: Final = 0x0040
_HAVE_TWO_BY_TWO: Final = 0x0080

# Type 2 charstring operators (Adobe TN5177); an escaped `12 x` is 1200 + x.
_HSTEM, _VSTEM, _HSTEMHM, _VSTEMHM = 1, 3, 18, 23
_CALLSUBR, _RETURN, _ENDCHAR, _HINTMASK, _CNTRMASK, _CALLGSUBR = 10, 11, 14, 19, 20, 29
_STEMS: Final = frozenset({_HSTEM, _VSTEM, _HSTEMHM, _VSTEMHM})
_MASKS: Final = frozenset({_HINTMASK, _CNTRMASK})
# Path, hint and flex operators: each clears the stack. Arithmetic and storage operators would make
# a subroutine index computed rather than read, and `vsindex`/`blend` belong to CFF2.
_DRAWING: Final = frozenset(
    {4, 5, 6, 7, 8, 21, 22, 24, 25, 26, 27, 30, 31, 1200, 1234, 1235, 1236, 1237}
)
_MAX_NESTING: Final = 10
_MAX_CHARSTRING: Final = 65_535  # TN5177 Appendix B
_SEAC_OPERANDS: Final = 4

# CFF DICT operators the cut rewrites or refuses.
_CHARSET, _ENCODING, _CHARSTRINGS, _PRIVATE, _SUBRS = 15, 16, 17, 18, 19
_CHARSTRING_TYPE, _SYNTHETIC_BASE, _ROS, _FD_ARRAY, _FD_SELECT = 1206, 1220, 1230, 1236, 1237
# Offsets 0-2 name the predefined ISOAdobe, Expert and ExpertSubset charsets.
_PREDEFINED_CHARSETS: Final = 3

_FORMAT_4_END: Final = 0xFFFF
_MAX_U16: Final = 0xFFFF


class RefusedError(Exception):
    """The font holds a structure this cut does not handle: the caller sends it whole."""


def _u16(data: bytes, at: int) -> int:
    return int(struct.unpack_from(">H", data, at)[0])


def _i16(data: bytes, at: int) -> int:
    return int(struct.unpack_from(">h", data, at)[0])


def _u32(data: bytes, at: int) -> int:
    return int(struct.unpack_from(">I", data, at)[0])


def cut(font: bytes, keep: Iterable[str]) -> bytes:
    """Face 0 of `font` holding `.notdef` and the glyphs of the `keep` characters it maps alone.

    A kept character keeps its outline, hints, advance, side bearing and kerning; a character the
    font does not map stays unmapped, so the sandbox's reader still counts it as missing.
    """
    version, tables = _face(font)
    if tables.keys() - _VERBATIM - _REBUILT - _DROPPED:
        raise RefusedError
    count = _u16(tables[b"maxp"], _MAXP_GLYPHS)
    lookup = _unicode_cmap(tables[b"cmap"])
    mapping: dict[int, int] = {0: 0}
    codes: dict[int, int] = {}
    for code in sorted({ord(character) for character in keep}):
        glyph = lookup(code)
        if 0 < glyph < count:
            codes[code] = mapping.setdefault(glyph, len(mapping))
    head = bytearray(tables[b"head"])
    head[_HEAD_ADJUSTMENT : _HEAD_ADJUSTMENT + 4] = bytes(4)
    out: dict[bytes, bytes] = {tag: tables[tag] for tag in _VERBATIM & tables.keys()}
    truetype = version in _TRUETYPE and b"CFF " not in tables
    if truetype and b"glyf" in tables:
        out[b"glyf"], out[b"loca"] = _truetype(tables, mapping, count)
        head[_HEAD_LOCA_FORMAT : _HEAD_LOCA_FORMAT + 2] = struct.pack(">h", 1)
    elif version == _CFF_VERSION and b"CFF " in tables and b"glyf" not in tables:
        out[b"CFF "] = _Cff(tables[b"CFF "], count).write(list(mapping), _Budget(len(font)))
    else:
        raise RefusedError
    out[b"head"] = bytes(head)
    out[b"cmap"] = _cmap(codes)
    out |= _per_glyph(tables, list(mapping), count)
    if b"kern" in tables:
        out[b"kern"] = _kern(tables[b"kern"], mapping)
    return _sfnt(version, out)


def _per_glyph(tables: dict[bytes, bytes], order: list[int], count: int) -> dict[bytes, bytes]:
    """The tables holding one entry per glyph, in the cut's glyph order."""
    out: dict[bytes, bytes] = {}
    maxp = tables[b"maxp"]
    out[b"maxp"] = maxp[:_MAXP_GLYPHS] + struct.pack(">H", len(order)) + maxp[_MAXP_GLYPHS + 2 :]
    out[b"hhea"], out[b"hmtx"] = _metrics(tables[b"hhea"], tables[b"hmtx"], order)
    if (b"vhea" in tables) != (b"vmtx" in tables):
        raise RefusedError
    if b"vhea" in tables:
        out[b"vhea"], out[b"vmtx"] = _metrics(tables[b"vhea"], tables[b"vmtx"], order)
    if b"post" in tables:
        if len(tables[b"post"]) < _POST_HEADER:
            raise RefusedError
        out[b"post"] = b"\x00\x03\x00\x00" + tables[b"post"][4:_POST_HEADER]
    if b"hdmx" in tables:
        out[b"hdmx"] = _hdmx(tables[b"hdmx"], order, count)
    if b"LTSH" in tables:
        version, glyphs = struct.unpack_from(">HH", tables[b"LTSH"], 0)
        if glyphs != count or len(tables[b"LTSH"]) < 4 + count:
            raise RefusedError
        out[b"LTSH"] = struct.pack(">HH", version, len(order)) + bytes(
            tables[b"LTSH"][4 + glyph] for glyph in order
        )
    return out


def _hdmx(table: bytes, order: list[int], count: int) -> bytes:
    """Each pixel size's hinted advances of the kept glyphs, records padded to 4 bytes."""
    version, records, size = struct.unpack_from(">HhI", table, 0)
    if records < 0 or size < 2 + count or len(table) < 8 + records * size:
        raise RefusedError
    width = 2 + len(order) + (-(2 + len(order)) % 4)
    out = struct.pack(">HhI", version, records, width)
    for record in range(8, 8 + records * size, size):
        kept = bytes(table[record + 2 + glyph] for glyph in order)
        out += table[record : record + 2] + kept + bytes(width - 2 - len(order))
    return out


def _face(font: bytes) -> tuple[bytes, dict[bytes, bytes]]:
    """Face 0's sfnt version and tables: matplotlib draws a collection's first face."""
    if font[:4] == _COLLECTION and _u32(font, 8) == 0:
        raise RefusedError
    start = _u32(font, 12) if font[:4] == _COLLECTION else 0
    version = font[start : start + 4]
    tables: dict[bytes, bytes] = {}
    for record in range(start + 12, start + 12 + 16 * _u16(font, start + 4), 16):
        tag = font[record : record + 4]
        offset, length = struct.unpack_from(">II", font, record + 8)
        if tag in tables or offset + length > len(font):
            raise RefusedError
        tables[tag] = font[offset : offset + length]
    return version, tables


def _unicode_cmap(table: bytes) -> Callable[[int], int]:
    """The character-to-glyph lookup of the subtable FreeType selects (`find_unicode_charmap`):
    the last UCS-4 subtable, else the last Unicode one -- a format 14 one included, which maps no
    character, so FreeType then draws none and the cut refuses rather than map more."""
    records = [struct.unpack_from(">HHI", table, 4 + 8 * index) for index in range(_u16(table, 2))]
    unicode = [
        record for record in records if record[0] in {0, 2} or record[:2] in {(3, 1), (3, 10)}
    ]
    wide = [record for record in unicode if record[:2] in {(3, 10), (0, 4)}]
    if not unicode:
        raise RefusedError
    offset = (wide or unicode)[-1][2]
    form = _u16(table, offset)
    if form == 4:
        return _format4(table, offset)
    if form == 12:
        return _format12(table, offset)
    raise RefusedError


def _format4(table: bytes, at: int) -> Callable[[int], int]:
    """A format 4 lookup. FreeType reads a subtable that fails its checks differently (another
    subtable, a linear search, its own repairs), so anything short of sorted, disjoint segments
    inside the table, the last one ending at U+FFFF, refuses."""
    length = _u16(table, at + 2)
    segments = _u16(table, at + 6) // 2
    ends = [_u16(table, at + 14 + 2 * index) for index in range(segments)]
    starts_at = at + 16 + 2 * segments
    deltas_at = starts_at + 2 * segments
    ranges_at = deltas_at + 2 * segments
    starts = [_u16(table, starts_at + 2 * index) for index in range(segments)]
    offsets = [_u16(table, ranges_at + 2 * index) for index in range(segments)]
    limit = at + length
    if (
        _u16(table, at + 6) % 2
        or limit > len(table)
        or ranges_at + 2 * segments > limit
        or not ends
        or ends[-1] != _FORMAT_4_END
        or any(start > end for start, end in zip(starts, ends, strict=True))
        or any(start <= end for start, end in zip(starts[1:], ends, strict=False))
        or any(
            offset
            and ranges_at + 2 * index + offset + 2 * (ends[index] - starts[index] + 1) > limit
            for index, offset in enumerate(offsets)
        )
    ):
        raise RefusedError

    def lookup(code: int) -> int:
        index = bisect.bisect_left(ends, code)
        if code > _MAX_U16 or index == segments or code < starts[index]:
            return 0
        delta = _u16(table, deltas_at + 2 * index)
        if offsets[index] == 0:
            return (code + delta) & _MAX_U16
        glyph = _u16(table, ranges_at + 2 * index + offsets[index] + 2 * (code - starts[index]))
        return 0 if glyph == 0 else (glyph + delta) & _MAX_U16

    return lookup


def _format12(table: bytes, at: int) -> Callable[[int], int]:
    """A format 12 lookup; as format 4's, groups out of order, overlapping or past the table
    refuse."""
    count = _u32(table, at + 12)
    if at + _u32(table, at + 4) > len(table) or 16 + 12 * count > _u32(table, at + 4):
        raise RefusedError
    groups: list[tuple[int, int, int]] = [
        struct.unpack_from(">III", table, at + 16 + 12 * index) for index in range(count)
    ]
    starts = [group[0] for group in groups]
    if any(start > end for start, end, _glyph in groups) or any(
        later[0] <= earlier[1] for earlier, later in itertools.pairwise(groups)
    ):
        raise RefusedError

    def lookup(code: int) -> int:
        index = bisect.bisect_right(starts, code) - 1
        if index < 0 or code > groups[index][1]:
            return 0
        return groups[index][2] + code - starts[index]

    return lookup


def _cmap(codes: dict[int, int]) -> bytes:
    """A format 4 subtable (3, 1), plus format 12 (3, 10) when a kept code lies past U+FFFF."""
    runs = _runs(sorted(codes.items()))
    basic = [run for run in runs if run[1] < _FORMAT_4_END]
    segments = [*basic, (_FORMAT_4_END, _FORMAT_4_END, 0)]
    count = len(segments)
    power = 1 << (count.bit_length() - 1)
    form4 = b"".join(
        (
            struct.pack(
                ">HHHHHHH",
                4,
                16 + 8 * count,
                0,
                2 * count,
                2 * power,
                power.bit_length() - 1,
                2 * count - 2 * power,
            ),
            struct.pack(f">{count}H", *(end for _start, end, _glyph in segments)),
            b"\x00\x00",
            struct.pack(f">{count}H", *(start for start, _end, _glyph in segments)),
            struct.pack(
                f">{count}H", *((glyph - start) & _MAX_U16 for start, _end, glyph in segments)
            ),
            bytes(2 * count),
        )
    )
    if len(form4) > _MAX_U16:
        raise RefusedError
    subtables = [(1, form4)]
    if basic != runs:
        groups = b"".join(struct.pack(">III", *run) for run in runs)
        subtables.append(
            (10, struct.pack(">HHIII", 12, 0, 16 + len(groups), 0, len(runs)) + groups)
        )
    header = struct.pack(">HH", 0, len(subtables))
    offset = 4 + 8 * len(subtables)
    records = b""
    for encoding, data in subtables:
        records += struct.pack(">HHI", 3, encoding, offset)
        offset += len(data)
    return header + records + b"".join(data for _encoding, data in subtables)


def _runs(pairs: list[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """(first code, last code, first glyph) for each run of consecutive codes + glyphs, clipped so
    no run crosses U+FFFF into the supplementary planes."""
    runs: list[tuple[int, int, int]] = []
    for code, glyph in pairs:
        if runs:
            start, end, first = runs[-1]
            if code == end + 1 and glyph == first + code - start and end != _FORMAT_4_END - 1:
                runs[-1] = (start, code, first)
                continue
        runs.append((code, code, glyph))
    return runs


def _metrics(hhea: bytes, hmtx: bytes, order: list[int]) -> tuple[bytes, bytes]:
    """Each kept glyph's advance + side bearing, every one written in full (`hhea` + `hmtx`, or
    `vhea` + `vmtx`: one layout)."""
    long = _u16(hhea, _HHEA_METRICS)
    if long == 0:
        raise RefusedError

    def metric(glyph: int) -> bytes:
        advance = _u16(hmtx, 4 * min(glyph, long - 1))
        bearing = _i16(hmtx, 4 * glyph + 2 if glyph < long else 4 * long + 2 * (glyph - long))
        return struct.pack(">Hh", advance, bearing)

    head = hhea[:_HHEA_METRICS] + struct.pack(">H", len(order)) + hhea[_HHEA_METRICS + 2 :]
    return head, b"".join(map(metric, order))


def _kern(table: bytes, mapping: dict[int, int]) -> bytes:
    """The kept glyphs' pairs of each format 0 subtable (version 0 table, as FreeType reads it)."""
    version, count = struct.unpack_from(">HH", table, 0)
    if version != 0:
        raise RefusedError
    at = 4
    out = struct.pack(">HH", 0, count)
    for _ in range(count):
        sub_version, length, coverage, pairs = struct.unpack_from(">HHHH", table, at)
        if coverage >> 8 != 0 or length != 14 + 6 * pairs:
            raise RefusedError
        kept = sorted(
            (mapping[left], mapping[right], value)
            for left, right, value in struct.iter_unpack(">HHh", table[at + 14 : at + length])
            if left in mapping and right in mapping
        )
        if len({pair[:2] for pair in kept}) != len(kept):
            raise RefusedError
        power = 1 << (len(kept).bit_length() - 1) if kept else 0
        selector = power.bit_length() - 1 if kept else 0
        out += struct.pack(
            ">HHHHHHH",
            sub_version,
            14 + 6 * len(kept),
            coverage,
            len(kept),
            6 * power,
            selector,
            6 * (len(kept) - power),
        )
        out += b"".join(struct.pack(">HHh", *pair) for pair in kept)
        at += length
    return out


def _truetype(
    tables: dict[bytes, bytes], mapping: dict[int, int], count: int
) -> tuple[bytes, bytes]:
    """`glyf` + long `loca` for the kept glyphs and, transitively, every component they use."""
    glyf = tables[b"glyf"]
    loca = tables[b"loca"]
    # Closed: 0 = short, 1 = long. FreeType reads any nonzero format as long, so another value
    # read as short would cut other bytes than it draws (reviewer-7 F3): the whole font goes.
    loca_format = _i16(tables[b"head"], _HEAD_LOCA_FORMAT)
    if loca_format == 1:
        offsets = list(struct.unpack_from(f">{count + 1}I", loca))
    elif loca_format == 0:
        offsets = [2 * offset for offset in struct.unpack_from(f">{count + 1}H", loca)]
    else:
        raise RefusedError

    def data(glyph: int) -> bytes:
        start, end = offsets[glyph], offsets[glyph + 1]
        if not start <= end <= len(glyf):
            raise RefusedError
        return glyf[start:end]

    order = list(mapping)
    body = bytearray()
    places = [0]
    for glyph in order:  # grows while composites name components not yet kept
        source = data(glyph)
        program = bytearray(source)
        for at, component in _components(source):
            if component >= count:
                raise RefusedError
            program[at : at + 2] = struct.pack(">H", mapping.setdefault(component, len(mapping)))
            if len(order) < len(mapping):
                order.append(component)
        body += program + bytes(-len(program) % 4)
        places.append(len(body))
    return bytes(body), struct.pack(f">{len(places)}I", *places)


def _components(glyph: bytes) -> list[tuple[int, int]]:
    """(index offset, component glyph) of each component of a composite glyph, else none."""
    if len(glyph) < 10 or _i16(glyph, 0) >= 0:
        return []
    found: list[tuple[int, int]] = []
    at = 10
    while True:
        flags = _u16(glyph, at)
        found.append((at + 2, _u16(glyph, at + 2)))
        at += 8 if flags & _ARGS_ARE_WORDS else 6
        if flags & _HAVE_TWO_BY_TWO:
            at += 8
        elif flags & _HAVE_XY_SCALE:
            at += 4
        elif flags & _HAVE_SCALE:
            at += 2
        if not flags & _MORE_COMPONENTS:
            return found


class _Index:
    """A CFF INDEX read in place: its items load on demand, so a 65,535-glyph font costs only the
    glyphs the cut keeps."""

    def __init__(self, data: bytes, at: int) -> None:
        self.data = data
        self.count = _u16(data, at)
        if self.count == 0:
            self.size, self.base, self.end = 0, at + 2, at + 2
            return
        self.size = data[at + 2]
        if not 1 <= self.size <= 4:
            raise RefusedError
        self.offsets_at = at + 3
        self.base = at + 2 + (self.count + 1) * self.size
        self.end = self.base + self._offset(self.count)
        if self._offset(0) != 1 or self.end > len(data):
            raise RefusedError

    def _offset(self, index: int) -> int:
        at = self.offsets_at + index * self.size
        return int.from_bytes(self.data[at : at + self.size], "big")

    def __len__(self) -> int:
        return self.count

    def __getitem__(self, index: int) -> bytes:
        if not 0 <= index < self.count:
            raise RefusedError
        start, end = self._offset(index), self._offset(index + 1)
        if not 1 <= start <= end <= self.end - self.base:
            raise RefusedError
        return self.data[self.base + start : self.base + end]


def _index(items: list[bytes]) -> bytes:
    if not items:
        return b"\x00\x00"
    offsets = [1]
    for item in items:
        offsets.append(offsets[-1] + len(item))
    size = (offsets[-1].bit_length() + 7) // 8
    return (
        struct.pack(">HB", len(items), size)
        + b"".join(offset.to_bytes(size, "big") for offset in offsets)
        + b"".join(items)
    )


_Entry = tuple[int, list[int | None], bytes]


def _dict(data: bytes) -> list[_Entry]:
    """(operator, operands, raw bytes) per DICT entry; a real operand reads as `None`, since no
    offset the cut rewrites is ever real."""
    entries: list[_Entry] = []
    operands: list[int | None] = []
    start = at = 0
    while at < len(data):
        first = data[at]
        if first <= 21:
            at += 2 if first == 12 else 1
            operator = 1200 + data[at - 1] if first == 12 else first
            entries.append((operator, operands, data[start:at]))
            operands, start = [], at
        elif first == 28:
            operands.append(_i16(data, at + 1))
            at += 3
        elif first == 29:
            operands.append(int(struct.unpack_from(">i", data, at + 1)[0]))
            at += 5
        elif first == 30:
            at += 1
            while data[at] >> 4 != 0xF and data[at] & 0xF != 0xF:
                at += 1
            at += 1
            operands.append(None)
        elif first <= 246:
            operands.append(first - 139)
            at += 1
        elif first <= 254:
            magnitude = (first - 247) % 4 * 256 + data[at + 1] + 108
            operands.append(magnitude if first <= 250 else -magnitude)
            at += 2
        else:
            raise RefusedError
    # FreeType keeps a repeated operator's last value; the cut reads one, so a repeat refuses.
    if operands or len({entry[0] for entry in entries}) != len(entries):
        raise RefusedError
    return entries


def _offsets(entries: list[_Entry], operator: int, default: list[int] | None = None) -> list[int]:
    """The integer operands of `operator`'s entry, else `default`."""
    for found, operands, _raw in entries:
        if found == operator:
            if None in operands:
                raise RefusedError
            return [value for value in operands if value is not None]
    if default is None:
        raise RefusedError
    return default


def _encode(entries: list[_Entry], rewritten: dict[int, tuple[int, ...]]) -> bytes:
    """The DICT again: each rewritten operator's operands as 5-byte integers (so a layout computed
    with placeholders keeps its size), each other entry byte for byte."""
    out = bytearray()
    for operator, _operands, raw in entries:
        if operator not in rewritten:
            out += raw
            continue
        for value in rewritten[operator]:
            out += b"\x1d" + struct.pack(">i", value)
        out += bytes((12, operator - 1200)) if operator >= 1200 else bytes((operator,))
    return bytes(out)


class _Private:
    """A Private DICT without its `Subrs`, plus the local subroutines it named."""

    def __init__(self, table: bytes, size: int, offset: int) -> None:
        data = table[offset : offset + size]
        if len(data) != size:
            raise RefusedError
        entries = _dict(data)
        self.entries = [entry for entry in entries if entry[0] != _SUBRS]
        named = any(entry[0] == _SUBRS for entry in entries)
        self.subrs = _Index(table, offset + _offsets(entries, _SUBRS)[0]) if named else None


class _Cff:
    """A one-font `CFF ` table, read: what the cut copies, rewrites or reads glyphs from."""

    def __init__(self, table: bytes, count: int) -> None:
        if table[0] != 1:
            raise RefusedError
        names = _Index(table, table[2])
        tops = _Index(table, names.end)
        strings = _Index(table, tops.end)
        self.global_subrs = _Index(table, strings.end)
        if len(names) != 1 or len(tops) != 1:
            raise RefusedError
        top = _dict(tops[0])
        operators = {entry[0] for entry in top}
        if _SYNTHETIC_BASE in operators or _offsets(top, _CHARSTRING_TYPE, [2]) != [2]:
            raise RefusedError
        self.names = table[table[2] : names.end]
        self.strings = table[tops.end : strings.end]
        # A custom Encoding is the font's own glyph-name map; OpenType draws through `cmap`.
        self.top = [entry for entry in top if entry[0] != _ENCODING]
        self.charstrings = _Index(table, _offsets(top, _CHARSTRINGS)[0])
        if len(self.charstrings) != count:
            raise RefusedError
        self.names_of = _charset(table, _offsets(top, _CHARSET, [0])[0], count)
        # CID-keyed: a Private DICT per Font DICT, chosen per glyph; name-keyed: the top one.
        self.cid = _ROS in operators
        if self.cid == (_PRIVATE in operators):
            raise RefusedError
        if self.cid:
            fonts = _Index(table, _offsets(top, _FD_ARRAY)[0])
            self.fonts = [_dict(fonts[index]) for index in range(len(fonts))]
            self.privates = [_Private(table, *_offsets(font, _PRIVATE)) for font in self.fonts]
            self.select = _fd_select(table, _offsets(top, _FD_SELECT)[0], count, len(fonts))
        else:
            self.fonts = []
            self.privates = [_Private(table, *_offsets(top, _PRIVATE))]
            self.select = [0] * count

    def write(self, order: list[int], budget: "_Budget") -> bytes:
        """The table holding the `order` glyphs alone, each with its subroutines inlined."""
        programs = _index(
            [
                _flatten(
                    self.charstrings[glyph],
                    self.privates[self.select[glyph]].subrs,
                    self.global_subrs,
                    budget,
                )
                for glyph in order
            ]
        )
        charset = b"\x00" + b"".join(struct.pack(">H", self.names_of[glyph]) for glyph in order[1:])
        kept = sorted({self.select[glyph] for glyph in order})
        renumbered = {font: index for index, font in enumerate(kept)}
        select = _fd_select_format3([renumbered[self.select[glyph]] for glyph in order])
        select = select if self.cid else b""
        privates = [_encode(self.privates[font].entries, {}) for font in kept]

        def top(charset_at: int, select_at: int, programs_at: int, fonts_at: int) -> bytes:
            rewritten: dict[int, tuple[int, ...]] = {
                _CHARSET: (charset_at,),
                _CHARSTRINGS: (programs_at,),
            }
            if self.cid:
                rewritten |= {_FD_ARRAY: (fonts_at,), _FD_SELECT: (select_at,)}
            else:
                rewritten[_PRIVATE] = places[0]
            return _index([_encode(self.top, rewritten)])

        def fonts() -> bytes:
            if not self.cid:
                return b""
            return _index(
                [
                    _encode(self.fonts[font], {_PRIVATE: place})
                    for font, place in zip(kept, places, strict=True)
                ]
            )

        # Every rewritten operand is a 5-byte integer, so zeros lay the table out at its size.
        places = [(0, 0)] * len(kept)
        charset_at = 4 + len(self.names) + len(top(0, 0, 0, 0)) + len(self.strings) + 2
        select_at = charset_at + len(charset)
        programs_at = select_at + len(select)
        fonts_at = programs_at + len(programs)
        private_at = fonts_at + len(fonts())
        places = []
        for data in privates:
            places.append((len(data), private_at))
            private_at += len(data)
        out = b"".join(
            (
                b"\x01\x00\x04\x04",
                self.names,
                top(charset_at, select_at, programs_at, fonts_at),
                self.strings,
                b"\x00\x00",  # no global subroutines: every call is inlined
                charset,
                select,
                programs,
                fonts(),
                *privates,
            )
        )
        if len(out) != private_at:
            raise RefusedError
        return out


def _charset(table: bytes, at: int, count: int) -> list[int]:
    """Each glyph's SID (name-keyed) or CID (CID-keyed); `.notdef` = 0."""
    if at < _PREDEFINED_CHARSETS:
        raise RefusedError
    form = table[at]
    found = [0]
    at += 1
    if form == 0:
        found += struct.unpack_from(f">{count - 1}H", table, at)
    elif form in {1, 2}:
        while len(found) < count:
            first = _u16(table, at)
            more = table[at + 2] if form == 1 else _u16(table, at + 2)
            found += range(first, first + more + 1)
            at += 3 if form == 1 else 4
    else:
        raise RefusedError
    if len(found) != count:
        raise RefusedError
    return found


def _fd_select(table: bytes, at: int, count: int, fonts: int) -> list[int]:
    form = table[at]
    if form == 0:
        select = list(table[at + 1 : at + 1 + count])
    elif form == 3:
        ranges = _u16(table, at + 1)
        bounds = [_u16(table, at + 3 + 3 * index) for index in range(ranges + 1)]
        select = []
        for index in range(ranges):
            select += [table[at + 5 + 3 * index]] * (bounds[index + 1] - bounds[index])
        if bounds[0] != 0:
            raise RefusedError
    else:
        raise RefusedError
    if len(select) != count or any(font >= fonts for font in select):
        raise RefusedError
    return select


def _fd_select_format3(select: list[int]) -> bytes:
    ranges = [
        (glyph, font)
        for glyph, font in enumerate(select)
        if glyph == 0 or font != select[glyph - 1]
    ]
    return (
        struct.pack(">BH", 3, len(ranges))
        + b"".join(struct.pack(">HB", *entry) for entry in ranges)
        + struct.pack(">H", len(select))
    )


class _Budget:
    """The bytes the inlining may read across one cut: the font's own length. Inlining copies
    what it reads, and a subroutine called from many places is read once per call, so a font
    whose subroutines fan out can expand without bound; a cut costing more than the whole font is
    worth less than it, so past the budget the cut refuses."""

    def __init__(self, size: int) -> None:
        self.left = size

    def spend(self, size: int) -> None:
        self.left -= size
        if self.left < 0:
            raise RefusedError


def _bias(subrs: _Index) -> int:
    count = len(subrs)
    return 107 if count < 1240 else 1131 if count < 33900 else 32768


class _Flattening:
    """One glyph's program with every subroutine call replaced by the subroutine's own tokens.

    The tokens run in the order the interpreter runs them, so what they draw is unchanged. Two
    facts carry across calls: the operands pending since the last operator (a call's index is the
    one just pushed), and the stem hints declared so far, which fix how many mask bytes follow each
    `hintmask` / `cntrmask` (TN5177: one bit per stem, the operands pending at the first mask being
    an implicit `vstem`).
    """

    def __init__(self, local: _Index | None, global_: _Index, budget: _Budget) -> None:
        self.local = local
        self.global_ = global_
        self.budget = budget
        self.out = bytearray()
        self.pending = 0
        self.stems = 0
        self.last: tuple[int, int] | None = None  # (output offset, value) of an integer operand

    def run(self, data: bytes, depth: int) -> bool:
        """Copy `data`'s tokens; True once `endchar` ended the glyph."""
        at = 0
        while at < len(data):
            first = data[at]
            if first >= 32 or first == 28:
                at = self._operand(data, at)
                continue
            operator, size = (1200 + data[at + 1], 2) if first == 12 else (first, 1)
            self.budget.spend(size)
            if operator in {_CALLSUBR, _CALLGSUBR}:
                if self._call(operator, depth):
                    return True
            elif operator == _RETURN:
                # TN5177: a subroutine ends with `return` or `endchar`, so anything else refuses.
                if depth == 0 or at + size != len(data):
                    raise RefusedError
                return False
            elif operator == _ENDCHAR:
                if self.pending >= _SEAC_OPERANDS:
                    raise RefusedError
                self.out += data[at : at + size]
                return True
            else:
                size = self._operator(operator, data, at, size)
            at += size
        raise RefusedError  # a glyph without `endchar`, a subroutine without `return`

    def _operator(self, operator: int, data: bytes, at: int, size: int) -> int:
        """Copy one stack-clearing operator, with its mask bytes; its size."""
        if operator in _STEMS or operator in _MASKS:
            self.stems += self.pending // 2
        if operator in _MASKS:
            mask = (self.stems + 7) // 8
            self.budget.spend(mask)
            size += mask
        elif operator not in _STEMS and operator not in _DRAWING:
            raise RefusedError
        # Mask bytes cut short by their program's end leave it without `endchar` or `return`,
        # which refuses.
        self.out += data[at : at + size]
        self.pending = 0
        self.last = None
        return size

    def _operand(self, data: bytes, at: int) -> int:
        first = data[at]
        if first == 28:
            size, value = 3, _i16(data, at + 1)
        elif first <= 246:
            size, value = 1, first - 139
        elif first <= 254:
            magnitude = (first - 247) % 4 * 256 + data[at + 1] + 108
            size, value = 2, magnitude if first <= 250 else -magnitude
        else:
            size, value = 5, None  # 16.16 fixed: never a subroutine index
        if at + size > len(data):
            raise RefusedError
        self.budget.spend(size)
        self.last = None if value is None else (len(self.out), value)
        self.out += data[at : at + size]
        self.pending += 1
        return at + size

    def _call(self, operator: int, depth: int) -> bool:
        subrs = self.local if operator == _CALLSUBR else self.global_
        if self.last is None or subrs is None or depth >= _MAX_NESTING:
            raise RefusedError
        place, value = self.last
        del self.out[place:]
        self.pending -= 1
        self.last = None
        return self.run(subrs[value + _bias(subrs)], depth + 1)


def _flatten(program: bytes, local: _Index | None, global_: _Index, budget: _Budget) -> bytes:
    flattening = _Flattening(local, global_, budget)
    flattening.run(program, 0)
    if len(flattening.out) > _MAX_CHARSTRING:
        raise RefusedError
    return bytes(flattening.out)


def _checksum(data: bytes) -> int:
    padded = data + bytes(-len(data) % 4)
    words: tuple[int, ...] = struct.unpack(f">{len(padded) // 4}I", padded)
    return sum(words) & 0xFFFFFFFF


def _sfnt(version: bytes, tables: dict[bytes, bytes]) -> bytes:
    """The tables as one font: sorted records, 4-byte alignment, checksums, `head`'s adjustment."""
    tags = sorted(tables)
    power = 1 << (len(tags).bit_length() - 1)
    out = bytearray(
        version
        + struct.pack(
            ">HHHH", len(tags), 16 * power, power.bit_length() - 1, 16 * (len(tags) - power)
        )
    )
    offset = 12 + 16 * len(tags)
    places: dict[bytes, int] = {}
    for tag in tags:
        data = tables[tag]
        places[tag] = offset
        out += tag + struct.pack(">III", _checksum(data), offset, len(data))
        offset += len(data) + (-len(data) % 4)
    for tag in tags:
        out += tables[tag] + bytes(-len(tables[tag]) % 4)
    adjustment = (_CHECKSUM_MAGIC - _checksum(bytes(out))) & 0xFFFFFFFF
    at = places[b"head"] + _HEAD_ADJUSTMENT
    out[at : at + 4] = struct.pack(">I", adjustment)
    return bytes(out)
