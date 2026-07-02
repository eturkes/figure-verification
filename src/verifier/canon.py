# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Canonical forms + provenance hashing — the deterministic backbone of the VCert.

Evaluator-independent foundation (M1.4b's ingest, M1.4d's eval, and M1.4f's oracle
import it; no transform logic lives here). It pins ONE textual canonical form for a recomputed
table and FOUR SHA-256 hashes over text — never Arrow/Parquet bytes, which couple
to a library version. The hashes split by purpose:

  - dataset  : raw CSV bytes, `sha256:`-prefixed, NO domain tag. This IS the source
               identity the spec's `dataset.hash` declares, so it must stay format-free
               and is row-order / CRLF / BOM sensitive by design.
  - table    : the typed-NDJSON serialization (serialize_table) of the recomputed
               plotted table; domain-tagged.
  - spec     : the validated VPlotSpec re-encoded deterministically (msgspec finding 8);
               domain-tagged. Byte-faithful — NO Unicode normalization — matching the
               evaluator + DuckDB oracle, which compare string filters verbatim by UTF-8
               code-point order (VPlot_SEMANTICS sections 3/4/10); folding here would collide
               specs that select different rows. The re-encode still folds JSON surface
               noise (whitespace, key order, escaping) to one form.
  - manifest : the trusted per-column manifest's raw bytes; domain-tagged.

Only the table hash is permutation-invariant (M1.4d closes every plot with a total
sort); the dataset hash deliberately is not. Display metadata (unit/label) lives in
the manifest, never in a Column, so it never enters the table hash. See memory Stack
(Hashing); VPlot_SEMANTICS.md is the meaning these realize.
"""

import hashlib
import platform
import unicodedata
from decimal import MAX_EMAX, MIN_EMIN, ROUND_HALF_EVEN, Context, Decimal
from typing import ClassVar, Literal

import msgspec
from msgspec import Struct

from verifier.schema import VPlotSpec

# Serialization-format pin: a CANON_VERSION bump invalidates stale domain-tagged hashes
# (the raw dataset hash stays format-free). Golden hex vectors (tests) lock the canonical
# bytes, so encoder/runtime drift under a fixed CANON_VERSION fails loudly.
CANON_VERSION = "canon-0.1"

# order="deterministic" sorts dict/set keys and renders Decimal->string with no Unicode
# pass (finding 8); a VPlotSpec has neither dicts nor Decimals, so this only locks struct
# field order (already definition order) — belt-and-suspenders for the spec hash.
_SPEC_ENCODER = msgspec.json.Encoder(order="deterministic")


# --- value model -------------------------------------------------------------
# A cell is a numeric (Decimal), a temporal/string canonical text (str), or the one
# null token (None) — no NaN, no float, no bool (VPlot_SEMANTICS.md section 2).
type Cell = Decimal | str | None


# Columns split by kind so illegal states (a numeric column without a scale, a string
# column carrying a granularity) are unrepresentable. Each carries a `kind` ClassVar so
# the union exposes a uniform discriminator; none carries unit/label — display metadata
# stays in the manifest, out of the data hash.
class NumericColumn(Struct, frozen=True, kw_only=True):
    kind: ClassVar[Literal["numeric"]] = "numeric"
    name: str
    scale: int  # fixed fractional places in the canonical render (>= 0)


class TemporalColumn(Struct, frozen=True, kw_only=True):
    kind: ClassVar[Literal["temporal"]] = "temporal"
    name: str
    granularity: Literal["date", "datetime"]


class StringColumn(Struct, frozen=True, kw_only=True):
    kind: ClassVar[Literal["string"]] = "string"
    name: str


type Column = NumericColumn | TemporalColumn | StringColumn


class Table(Struct, frozen=True, kw_only=True):
    """A recomputed plotted table: columns plus rows already in canonical total order
    (M1.4d's closure produces that order; this module only serializes/hashes it)."""

    columns: tuple[Column, ...]
    rows: tuple[tuple[Cell, ...], ...]


class Versions(Struct, frozen=True, kw_only=True):
    """The determinism-relevant runtime versions the M1.6 VCert badge stamps."""

    canon_version: str
    python: str
    msgspec: str
    unidata: str


# --- typed-NDJSON serialization ----------------------------------------------
def _format_decimal(value: Decimal, scale: int) -> str:
    """A numeric cell as a fixed-point JSON number token with exactly `scale` fractional
    places, ROUND_HALF_EVEN. The per-value context sets precision = (0 if zero else
    adjusted())+scale+2 AND widens the exponent range to the decimal-module max, so quantize
    is total over every finite magnitude whose needed precision fits decimal.MAX_PREC (~1e18
    on 64-bit; +2 covers a rounding carry; the default Emax/Emin would already reject ~1e6,
    e.g. Decimal("1e1000000"), which formats fine here). Past that astronomic bound
    Context(prec=...) raises a LOUD ValueError (test-pinned) -- unreachable through ingest/
    eval, whose cells are DECIMAL(38)-bounded; never a silent wrong render. The
    zero clamp is load-bearing: the C decimal impl returns adjusted() == the exponent for a
    zero (not 0), so a "0E+999..." cell would else push precision past MAX_PREC -> Context()
    raises an uncaught ValueError. Negative zero folds to positive so 0 and -0 share a canonical
    form. Magnitude-bounding the trusted dataset is M1.4b's parse-boundary job, not canon's."""
    if not value.is_finite():
        msg = f"non-finite numeric cell: {value!r}"
        raise ValueError(msg)
    quantum = Decimal((0, (1,), -scale))  # exact 10**-scale, context-free
    precision = max((0 if value.is_zero() else value.adjusted()) + scale + 2, 1)
    context = Context(prec=precision, Emax=MAX_EMAX, Emin=MIN_EMIN, rounding=ROUND_HALF_EVEN)
    quantized = value.quantize(quantum, context=context)
    if quantized.is_zero():
        quantized = quantized.copy_abs()
    return format(quantized, f".{scale}f")


def _cell_token(column: Column, cell: Cell) -> str:
    """One cell as its JSON token: null -> `null` (distinct from the string "null"),
    numeric -> fixed-point number, temporal/string -> an escaped JSON string. The header
    descriptor carries the temporal-vs-string distinction, so both render as strings."""
    if cell is None:
        return "null"
    if isinstance(column, NumericColumn):
        if not isinstance(cell, Decimal):
            msg = f"numeric column {column.name!r} got a non-Decimal cell: {cell!r}"
            raise TypeError(msg)
        return _format_decimal(cell, column.scale)
    if not isinstance(cell, str):
        msg = f"text column {column.name!r} got a non-str cell: {cell!r}"
        raise TypeError(msg)
    return msgspec.json.encode(cell).decode("utf-8")


def _descriptor(column: Column) -> str:
    """A self-describing header descriptor: `name:numeric:<scale>` / `name:temporal:
    <granularity>` / `name:string`. Field names are identifier-shaped (no colon), so the
    delimiter is unambiguous, and the kind+scale/granularity make the header injective."""
    if isinstance(column, NumericColumn):
        return f"{column.name}:numeric:{column.scale}"
    if isinstance(column, TemporalColumn):
        return f"{column.name}:temporal:{column.granularity}"
    return f"{column.name}:string"


def serialize_table(table: Table) -> str:
    """The table's typed-NDJSON canonical form: a header JSON array of column descriptors,
    then one compact JSON array per row, newline-terminated. Compact + UTF-8 (no ASCII
    escaping beyond JSON's own) so the byte form is stable; this is the table hash input.

    msgspec.json.encode renders each string cell with canonical JSON escaping (control
    chars escaped, so a newline in a cell cannot break the line structure)."""
    header = msgspec.json.encode([_descriptor(c) for c in table.columns]).decode("utf-8")
    lines = [header]
    for row in table.rows:
        tokens = [_cell_token(col, cell) for col, cell in zip(table.columns, row, strict=True)]
        lines.append("[" + ",".join(tokens) + "]")
    return "\n".join(lines) + "\n"


# --- hashes ------------------------------------------------------------------
def _digest(domain: Literal["table", "spec", "manifest"], payload: bytes) -> str:
    """SHA-256 over a `vplot-<domain>/<CANON_VERSION>\\n` tag + payload, `sha256:`-prefixed.
    The tag domain-separates table/spec/manifest hashes and ties them to the format version
    so a serialization bump cannot collide with a stale hash. The tag/payload split is
    injective only because `domain` is a closed, slash-free literal set — an arbitrary
    domain string must not be threaded in."""
    tag = f"vplot-{domain}/{CANON_VERSION}\n".encode()
    return "sha256:" + hashlib.sha256(tag + payload).hexdigest()


def hash_dataset(csv_bytes: bytes) -> str:
    """The source-identity hash: raw CSV bytes, `sha256:`-prefixed, NO domain tag. Equals
    what a spec's `dataset.hash` declares (= `sha256sum` of the file), so it stays format-
    free and byte-exact (row order, CRLF, and a BOM all change it). Untagged, a crafted CSV
    could share a preimage with a tagged digest; that is inert because the VCert separates
    the four hashes by SLOT (dataset/table/spec/manifest) and never compares bare digests
    across domains, and the dataset is trusted source (the model emits only the spec)."""
    return "sha256:" + hashlib.sha256(csv_bytes).hexdigest()


def hash_table(table: Table) -> str:
    """The recomputed plotted table's hash, over its typed-NDJSON form; domain-tagged."""
    return _digest("table", serialize_table(table).encode("utf-8"))


def hash_spec(spec: VPlotSpec) -> str:
    """The validated spec's hash: a deterministic msgspec re-encode (finding 8), domain-tagged.
    Byte-faithful (NO Unicode normalization): the evaluator + DuckDB oracle compare string
    filters verbatim by UTF-8 code-point order (VPlot_SEMANTICS sections 3/4/10), so the hash must
    distinguish exactly what they distinguish — folding combining-mark variants here would
    collide specs that select different rows. The re-encode still canonicalizes JSON surface
    noise (whitespace, key order, escaping) to one form."""
    return _digest("spec", _SPEC_ENCODER.encode(spec))


def hash_manifest(manifest_bytes: bytes) -> str:
    """The trusted per-column manifest's hash, over its raw bytes; domain-tagged."""
    return _digest("manifest", manifest_bytes)


def runtime_versions() -> Versions:
    """The determinism-relevant runtime versions, for the M1.6 VCert badge."""
    return Versions(
        canon_version=CANON_VERSION,
        python=platform.python_version(),
        msgspec=msgspec.__version__,
        unidata=unicodedata.unidata_version,
    )
