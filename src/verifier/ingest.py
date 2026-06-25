# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Typed ingest: trusted `(manifest, raw CSV bytes)` -> a typed `canon.Table`.

The spec-independent layer between `canon` (value model + hashing) and `eval` (the
transform pipeline). It turns the trusted per-column manifest plus the raw CSV bytes
into a `canon.Table` of SOURCE rows in SOURCE order (the M1.4c evaluator applies the
transforms and the total-sort closure), or raises on a data-integrity violation.
Decimal-exact, no float. Implements VPlot_SEMANTICS.md sections 2-3 (data model +
numeric/temporal parse).

Two layers, two failure types (VPlot_SEMANTICS.md section 9):
  - parse  : load_manifest strict-decodes the trusted manifest, raising msgspec
             ValidationError / DecodeError (mirrors schema.decode_spec — a malformed
             manifest is a broken config, not a verification failure).
  - verify : load_table coerces each CSV cell to its manifest type, raising
             VerificationError(check="data.*") on any data-integrity breach (charset,
             header, row width, un-coercible numeric/temporal cell).

The numeric/temporal coercers are reused by the M1.4c evaluator for filter-value
coercion (re-tagged filter.value_type there); they raise the data.* check here.
"""

import csv
import io
import json
from datetime import date, datetime
from decimal import MAX_EMAX, MIN_EMIN, ROUND_HALF_EVEN, Context, Decimal, InvalidOperation
from typing import Annotated, Literal

import msgspec
from msgspec import Meta

from verifier import canon
from verifier.errors import VerificationError
from verifier.schema import DatasetName, FieldName, _Base, _reject_duplicate_keys

# DECIMAL(38, scale) is the M1.4d DuckDB oracle's column type: 38 total significant
# digits, `scale` of them fractional. The two numeric bounds below (magnitude + excess
# precision) keep every source cell inside that domain so the dual engines never diverge.
_MAX_PRECISION = 38


# --- manifest model ----------------------------------------------------------
# A tagged union on the JSON `type` key (here `type` is free to be the tag field -- no
# channel `type` collides, unlike schema.py's transforms which tag on `op`, finding 2).
# Each repeats frozen=True, kw_only=True (finding 1); arrays are tuples (finding 7). The
# display metadata (unit/label) lives here, never on a canon.Column -> out of the data
# hash; numeric carries the scale, temporal the granularity, so illegal column shapes are
# unrepresentable.
class NumericColumnSpec(_Base, frozen=True, kw_only=True, tag_field="type", tag="numeric"):
    name: FieldName
    scale: Annotated[int, Meta(ge=0, le=_MAX_PRECISION)]
    unit: str | None = None
    label: str | None = None


class TemporalColumnSpec(_Base, frozen=True, kw_only=True, tag_field="type", tag="temporal"):
    name: FieldName
    granularity: Literal["date", "datetime"]
    label: str | None = None


class StringColumnSpec(_Base, frozen=True, kw_only=True, tag_field="type", tag="string"):
    name: FieldName
    label: str | None = None


ManifestColumn = NumericColumnSpec | TemporalColumnSpec | StringColumnSpec


class Manifest(_Base, frozen=True, kw_only=True):
    """The trusted per-column schema for one CSV (data/schemas/<name>.json). Hashed into
    the VCert (canon.hash_manifest over raw bytes); the source of truth the evaluator
    coerces to and the M1.5 type/unit/label checks read from."""

    dataset: DatasetName
    columns: Annotated[tuple[ManifestColumn, ...], Meta(min_length=1)]


_MANIFEST_DECODER = msgspec.json.Decoder(Manifest)


def load_manifest(manifest_bytes: bytes) -> Manifest:
    """Strict-decode the trusted manifest, or raise msgspec ValidationError / DecodeError.

    Fail-closed like schema.decode_spec: unknown fields, an unknown column tag, or a
    bad scale are rejected, and a duplicate-key rescan (finding 4) rejects the last-wins
    ambiguity msgspec tolerates so the decoded manifest matches its hashed bytes."""
    manifest = _MANIFEST_DECODER.decode(manifest_bytes)
    json.loads(manifest_bytes, object_pairs_hook=_reject_duplicate_keys)
    return manifest


def _canon_column(column: ManifestColumn) -> canon.Column:
    """Project a manifest column onto its canon.Column, dropping unit/label so display
    metadata never enters the table hash (it stays on the Manifest for the section 7 lineage)."""
    if isinstance(column, NumericColumnSpec):
        return canon.NumericColumn(name=column.name, scale=column.scale)
    if isinstance(column, TemporalColumnSpec):
        return canon.TemporalColumn(name=column.name, granularity=column.granularity)
    return canon.StringColumn(name=column.name)


# --- cell coercion (VPlot_SEMANTICS.md section 3) ----------------------------
def _coerce_numeric(text: str, scale: int) -> Decimal:
    """A non-empty numeric cell -> an at-scale Decimal, or raise data.numeric_value.

    Rejects: an unparsable token, a non-finite value (NaN/Infinity carry no scale), a
    magnitude beyond DECIMAL(38, scale), and excess precision (> scale fractional places
    -- source data is never silently rounded; only computed aggregates quantize). A value
    exactly representable at `scale` (trailing zeros included) passes; -0 folds to 0.
    Reused by the evaluator for string->numeric filter coercion (re-tagged there)."""
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        msg = f"numeric value {text!r} is not a valid decimal"
        raise VerificationError(msg, check="data.numeric_value") from exc
    if not value.is_finite():
        msg = f"numeric value {text!r} is not finite"
        raise VerificationError(msg, check="data.numeric_value")
    # adjusted() is the most-significant digit's exponent; an integer part of d digits has
    # adjusted == d-1, so the DECIMAL(38, scale) integer width caps it at 37 - scale. The
    # is_zero() guard admits 0 at any scale (its adjusted() is 0, which would fail at high scale).
    if not (value.is_zero() or value.adjusted() <= _MAX_PRECISION - 1 - scale):
        msg = f"numeric value {text!r} exceeds DECIMAL({_MAX_PRECISION}, {scale}) magnitude"
        raise VerificationError(msg, check="data.numeric_value")
    # Excess-precision check, mirroring canon._format_decimal's widened context so quantize
    # stays total over every finite magnitude: a value with > scale places rounds away from
    # itself, so quantized != value flags it (exact-at-scale values, trailing zeros included,
    # are unchanged).
    quantum = Decimal((0, (1,), -scale))
    precision = max(value.adjusted() + scale + 2, 1)
    context = Context(prec=precision, Emax=MAX_EMAX, Emin=MIN_EMIN, rounding=ROUND_HALF_EVEN)
    quantized = value.quantize(quantum, context=context)
    if quantized != value:
        msg = f"numeric value {text!r} has more than {scale} fractional place(s)"
        raise VerificationError(msg, check="data.numeric_value")
    if quantized.is_zero():
        return quantized.copy_abs()
    return quantized


def _coerce_temporal(text: str, granularity: Literal["date", "datetime"]) -> str:
    """A non-empty temporal cell -> its canonical ISO-8601 text, or raise data.temporal_value.

    Accepts ONLY the canonical zero-padded form (date YYYY-MM-DD or naive datetime
    YYYY-MM-DDThh:mm:ss[.ffffff]) by round-tripping through isoformat() == text: this
    rejects basic `20240101`, unpadded `2024-1-1`, missing-seconds, and non-canonical
    fractions (isoformat emits exactly 6 fractional digits or none). Datetimes carrying a
    timezone are rejected (naive only, section 2). Reused by the evaluator for
    string->temporal filter coercion (re-tagged there)."""
    if granularity == "date":
        try:
            parsed_date = date.fromisoformat(text)
        except ValueError as exc:
            msg = f"temporal value {text!r} is not an ISO-8601 date"
            raise VerificationError(msg, check="data.temporal_value") from exc
        canonical = parsed_date.isoformat()
    else:
        try:
            parsed_dt = datetime.fromisoformat(text)
        except ValueError as exc:
            msg = f"temporal value {text!r} is not an ISO-8601 datetime"
            raise VerificationError(msg, check="data.temporal_value") from exc
        if parsed_dt.tzinfo is not None:
            msg = f"temporal value {text!r} carries a timezone; naive datetimes only"
            raise VerificationError(msg, check="data.temporal_value")
        canonical = parsed_dt.isoformat()
    if canonical != text:
        msg = f"temporal value {text!r} is not canonical ISO-8601 (canonical: {canonical!r})"
        raise VerificationError(msg, check="data.temporal_value")
    return canonical


def _coerce_cell(column: canon.Column, text: str) -> canon.Cell:
    """Coerce one raw CSV field by its column kind: empty -> the one null token (None);
    else numeric -> Decimal, temporal -> canonical ISO text, string -> verbatim (a literal
    `NA` stays the string "NA"; only an empty cell is null, section 2)."""
    if text == "":
        return None
    if isinstance(column, canon.NumericColumn):
        return _coerce_numeric(text, column.scale)
    if isinstance(column, canon.TemporalColumn):
        return _coerce_temporal(text, column.granularity)
    return text


def load_table(csv_bytes: bytes, manifest: Manifest) -> canon.Table:
    """Trusted `(raw CSV bytes, manifest)` -> a typed canon.Table of source rows in source
    order, or raise VerificationError(check="data.*").

    The CSV decodes as UTF-8 (data.charset), its header must equal the manifest column
    names in order (data.header), and every row's field count must match (data.row_width);
    each cell coerces to its column type (data.numeric_value / data.temporal_value). The
    rows are NOT yet total-sorted -- that closure is the M1.4c evaluator's."""
    columns = tuple(_canon_column(c) for c in manifest.columns)
    try:
        text = csv_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        msg = "CSV bytes are not valid UTF-8"
        raise VerificationError(msg, check="data.charset") from exc
    # newline="" hands raw line endings to csv, which parses LF/CRLF identically (the
    # dataset hash, not this parse, is the CRLF-sensitive source identity).
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration:
        msg = "CSV is empty; expected a header row"
        raise VerificationError(msg, check="data.header") from None
    expected = [c.name for c in columns]
    if header != expected:
        msg = f"CSV header {header!r} does not match manifest columns {expected!r}"
        raise VerificationError(msg, check="data.header")
    rows: list[tuple[canon.Cell, ...]] = []
    for record in reader:
        if len(record) != len(columns):
            msg = f"CSV row has {len(record)} field(s); expected {len(columns)}: {record!r}"
            raise VerificationError(msg, check="data.row_width")
        rows.append(
            tuple(_coerce_cell(col, cell) for col, cell in zip(columns, record, strict=True))
        )
    return canon.Table(columns=columns, rows=tuple(rows))
