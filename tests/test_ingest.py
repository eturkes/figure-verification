# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Tests for verifier.ingest — typed (manifest, CSV) -> canon.Table (M1.4b).

Golden loads (sales / weather / deliberately_dirty) lock the full coerced table against
its CSV by hand-verified explicit asserts (stronger than a self-blessed snapshot); inline
tiny fixtures drive every data.* rejection branch and the manifest parse layer.
"""

import pathlib
from decimal import Decimal

import msgspec
import pytest

from verifier import canon, ingest
from verifier.errors import VerificationError
from verifier.ingest import (
    Manifest,
    ManifestColumn,
    NumericColumnSpec,
    StringColumnSpec,
    TemporalColumnSpec,
    load_manifest,
    load_table,
)

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"


def _load_golden(name: str) -> canon.Table:
    manifest = load_manifest((DATA / "schemas" / f"{name}.json").read_bytes())
    return load_table((DATA / f"{name}.csv").read_bytes(), manifest)


# --- golden loads ------------------------------------------------------------
def test_sales_golden() -> None:
    table = _load_golden("sales")
    assert table.columns == (
        canon.StringColumn(name="month"),
        canon.StringColumn(name="region"),
        canon.NumericColumn(name="revenue", scale=0),
        canon.NumericColumn(name="orders", scale=0),
    )
    assert table.rows == (
        ("2026-01", "NA", Decimal(12000), Decimal(80)),
        ("2026-01", "EU", Decimal(9000), Decimal(61)),
        ("2026-02", "NA", Decimal(15000), Decimal(93)),
        ("2026-02", "EU", Decimal(11000), Decimal(70)),
        ("2026-03", "NA", Decimal(13000), Decimal(88)),
        ("2026-03", "EU", Decimal(14000), Decimal(86)),
    )


def test_weather_golden() -> None:
    table = _load_golden("weather")
    assert table.columns == (
        canon.TemporalColumn(name="date", granularity="date"),
        canon.StringColumn(name="city"),
        canon.NumericColumn(name="temp_c", scale=1),
        canon.NumericColumn(name="precip_mm", scale=1),
        canon.NumericColumn(name="aqi", scale=0),
    )
    # Decimal("0.0") precip cells exercise the zero-normalization branch (is_zero -> copy_abs,
    # here on +0); the -0 -> +0 SIGN fold itself is locked separately in
    # test_coerce_numeric_folds_negative_zero. The temporal column stores canonical ISO text
    # in source order (no total sort yet).
    assert table.rows == (
        ("2026-01-01", "London", Decimal("4.5"), Decimal("2.0"), Decimal(42)),
        ("2026-01-01", "Cairo", Decimal("14.0"), Decimal("0.0"), Decimal(88)),
        ("2026-01-02", "London", Decimal("5.1"), Decimal("3.5"), Decimal(40)),
        ("2026-01-02", "Cairo", Decimal("15.2"), Decimal("0.0"), Decimal(91)),
        ("2026-01-03", "London", Decimal("3.8"), Decimal("0.0"), Decimal(55)),
        ("2026-01-03", "Cairo", Decimal("16.4"), Decimal("0.0"), Decimal(84)),
        ("2026-01-04", "London", Decimal("6.0"), Decimal("1.2"), Decimal(38)),
        ("2026-01-04", "Cairo", Decimal("13.9"), Decimal("0.5"), Decimal(95)),
    )


def test_deliberately_dirty_golden() -> None:
    # empty cell -> None (string region AND numeric revenue/orders); literal "NA" stays a
    # string (only an empty cell is null, section 2).
    table = _load_golden("deliberately_dirty")
    assert table.rows == (
        ("2026-01", "NA", Decimal(12000), Decimal(80)),
        ("2026-01", "EU", None, Decimal(61)),
        ("2026-02", "NA", Decimal(15000), None),
        ("2026-02", None, Decimal(11000), Decimal(70)),
        ("2026-03", "NA", Decimal(13000), Decimal(88)),
        ("2026-03", "EU", Decimal(14000), Decimal(86)),
    )


# --- coercion semantics ------------------------------------------------------
def test_numeric_trailing_zeros_normalize() -> None:
    # > scale literal places but exactly representable at scale -> accepted, normalized.
    manifest = Manifest(dataset="t.csv", columns=(NumericColumnSpec(name="v", scale=1),))
    table = load_table(b"v\n2.50\n", manifest)
    assert table.rows == ((Decimal("2.5"),),)


def test_coerce_numeric_folds_negative_zero() -> None:
    result = ingest._coerce_numeric("-0.0", 1)
    assert result == Decimal(0)
    assert not result.is_signed()  # -0 folded to +0


def test_numeric_grammar_is_decimal_string() -> None:
    # Section 3 coerces numerics via Decimal(string) (the SAME coercer the evaluator reuses for
    # filter values), so the source grammar is deliberately Decimal's -- NOT a stricter canonical
    # form. Numerics canonicalize by VALUE (every form below collapses to one Decimal), unlike
    # temporals which canonicalize by TEXT and so must be canonical-strict. DuckDB's DECIMAL cast
    # accepts these same forms (measured); the M1.4f oracle ingests already-coerced Decimals and
    # never re-parses source text, so the lax grammar raises no dual-engine divergence.
    cases = [
        ("1_000", 0, Decimal(1000)),
        ("  12 ", 0, Decimal(12)),  # surrounding whitespace
        ("+12", 0, Decimal(12)),
        ("1e2", 0, Decimal(100)),  # scientific notation
        ("01", 0, Decimal(1)),
        (".5", 1, Decimal("0.5")),
    ]
    for text, scale, expected in cases:
        assert ingest._coerce_numeric(text, scale) == expected


def test_numeric_scale_38_min_value() -> None:
    # The smallest positive DECIMAL(38,38) value: in-domain by magnitude, accepted. DuckDB's
    # string CAST rejects this boundary (measured), but the oracle ingests coerced Decimals, not
    # source text, so the verifier accepts the mathematically valid value.
    assert ingest._coerce_numeric("1E-38", 38) == Decimal("1E-38")


def test_coerce_numeric_zero_with_huge_exponent_does_not_crash() -> None:
    # A zero carries the column's scale at any exponent; a hostile cell like "0E+999..." (whose
    # adjusted() is the huge exponent in the C decimal impl, not 0) must coerce to the canonical
    # at-scale zero, never drive the quantize context past MAX_PREC into an uncaught ValueError
    # (a load_table DoS reachable from a 19-char CSV cell).
    assert ingest._coerce_numeric("0E+999999999999999999", 0) == Decimal(0)
    z38 = ingest._coerce_numeric("0E+999999999999999999", 38)
    assert z38 == 0 and z38.as_tuple().exponent == -38
    neg = ingest._coerce_numeric("-0E+999999999999999999", 2)
    assert neg == 0 and not neg.is_signed()  # -0 still folds to +0


def test_datetime_cell_canonical() -> None:
    manifest = Manifest(
        dataset="t.csv", columns=(TemporalColumnSpec(name="ts", granularity="datetime"),)
    )
    table = load_table(b"ts\n2026-01-01T08:30:00.123456\n2026-06-01T00:00:00\n", manifest)
    assert table.rows == (("2026-01-01T08:30:00.123456",), ("2026-06-01T00:00:00",))


def test_crlf_and_lf_yield_the_same_table() -> None:
    # Line endings are source identity for the dataset hash, not for the typed table:
    # a CRLF CSV and its LF twin must coerce to the same canon.Table.
    manifest = Manifest(
        dataset="t.csv",
        columns=(StringColumnSpec(name="a"), NumericColumnSpec(name="b", scale=0)),
    )
    lf = load_table(b"a,b\nx,1\ny,2\n", manifest)
    crlf = load_table(b"a,b\r\nx,1\r\ny,2\r\n", manifest)
    assert crlf == lf
    assert lf.rows == (("x", Decimal(1)), ("y", Decimal(2)))


# --- data.* rejection branches ----------------------------------------------
@pytest.mark.parametrize(
    ("column", "cell", "check"),
    [
        (NumericColumnSpec(name="v", scale=1), "abc", "data.numeric_value"),  # unparsable
        (NumericColumnSpec(name="v", scale=1), "NaN", "data.numeric_value"),  # non-finite
        (NumericColumnSpec(name="v", scale=1), "Infinity", "data.numeric_value"),  # non-finite
        (NumericColumnSpec(name="v", scale=1), "1.23", "data.numeric_value"),  # > scale places
        (NumericColumnSpec(name="v", scale=0), "0.5", "data.numeric_value"),  # > scale @ 0
        (NumericColumnSpec(name="v", scale=0), "9" * 39, "data.numeric_value"),  # over-magnitude
        (
            TemporalColumnSpec(name="d", granularity="date"),
            "2026-1-1",
            "data.temporal_value",
        ),  # unpadded
        (
            TemporalColumnSpec(name="d", granularity="date"),
            "20260101",
            "data.temporal_value",
        ),  # basic form
        (
            TemporalColumnSpec(name="d", granularity="datetime"),
            "2026-01-01T00:00:00+00:00",
            "data.temporal_value",
        ),  # tz
        (
            TemporalColumnSpec(name="d", granularity="datetime"),
            "2026-01-01T00:00",
            "data.temporal_value",
        ),  # no seconds
        (
            TemporalColumnSpec(name="d", granularity="datetime"),
            "not-a-date",
            "data.temporal_value",
        ),  # unparsable
    ],
)
def test_cell_coercion_rejects(column: ManifestColumn, cell: str, check: str) -> None:
    manifest = Manifest(dataset="t.csv", columns=(column,))
    csv_bytes = f"{column.name}\n{cell}\n".encode()
    with pytest.raises(VerificationError) as excinfo:
        load_table(csv_bytes, manifest)
    assert excinfo.value.check == check


def test_rejects_bad_header() -> None:
    manifest = Manifest(dataset="t.csv", columns=(StringColumnSpec(name="x"),))
    with pytest.raises(VerificationError) as excinfo:
        load_table(b"y\nval\n", manifest)
    assert excinfo.value.check == "data.header"


def test_rejects_empty_csv() -> None:
    manifest = Manifest(dataset="t.csv", columns=(StringColumnSpec(name="x"),))
    with pytest.raises(VerificationError) as excinfo:
        load_table(b"", manifest)
    assert excinfo.value.check == "data.header"


def test_rejects_row_width() -> None:
    manifest = Manifest(
        dataset="t.csv", columns=(StringColumnSpec(name="x"), StringColumnSpec(name="y"))
    )
    with pytest.raises(VerificationError) as excinfo:
        load_table(b"x,y\nonly-one\n", manifest)
    assert excinfo.value.check == "data.row_width"


def test_rejects_invalid_utf8() -> None:
    manifest = Manifest(dataset="t.csv", columns=(StringColumnSpec(name="x"),))
    with pytest.raises(VerificationError) as excinfo:
        load_table(b"\xff\xfe", manifest)
    assert excinfo.value.check == "data.charset"


def test_rejects_utf8_bom() -> None:
    manifest = Manifest(dataset="t.csv", columns=(StringColumnSpec(name="x"),))
    with pytest.raises(VerificationError) as excinfo:
        load_table(b"\xef\xbb\xbfx\nval\n", manifest)
    assert excinfo.value.check == "data.charset"  # BOM rejected, never silently stripped


def test_rejects_malformed_csv_quote() -> None:
    # strict=True fails closed on a stray/unterminated quote rather than silently normalizing it.
    # A first-record (header) and a later-record (body) malformation exercise both csv.Error paths.
    manifest = Manifest(dataset="t.csv", columns=(StringColumnSpec(name="a"),))
    for bad in (b'"a"x\n', b'a\n"x"y\n'):
        with pytest.raises(VerificationError) as excinfo:
            load_table(bad, manifest)
        assert excinfo.value.check == "data.csv_syntax"


def test_quoted_field_with_embedded_comma() -> None:
    # strict=True still honors RFC-4180 quoting: a quoted comma is ONE string cell, not two.
    manifest = Manifest(
        dataset="t.csv", columns=(StringColumnSpec(name="a"), NumericColumnSpec(name="b", scale=0))
    )
    table = load_table(b'a,b\n"x,y",1\n', manifest)
    assert table.rows == (("x,y", Decimal(1)),)


# --- manifest parse layer ----------------------------------------------------
def test_load_manifest_preserves_unit_and_label() -> None:
    manifest = load_manifest((DATA / "schemas" / "weather.json").read_bytes())
    assert manifest.dataset == "weather.csv"
    temp_c = manifest.columns[2]
    assert isinstance(temp_c, NumericColumnSpec)
    assert (temp_c.name, temp_c.scale, temp_c.unit, temp_c.label) == (
        "temp_c",
        1,
        "°C",
        "Temperature",
    )
    aqi = manifest.columns[4]
    assert isinstance(aqi, NumericColumnSpec)
    assert aqi.unit is None  # the optional unit is absent on aqi


def test_load_manifest_rejects_unknown_field() -> None:
    with pytest.raises(msgspec.ValidationError):
        load_manifest(b'{"dataset":"t.csv","columns":[{"type":"string","name":"x","bogus":1}]}')


def test_load_manifest_rejects_unknown_tag() -> None:
    with pytest.raises(msgspec.ValidationError):
        load_manifest(b'{"dataset":"t.csv","columns":[{"type":"weird","name":"x"}]}')


def test_load_manifest_rejects_duplicate_key() -> None:
    raw = b'{"dataset":"t.csv","dataset":"t.csv","columns":[{"type":"string","name":"x"}]}'
    with pytest.raises(msgspec.ValidationError):
        load_manifest(raw)


def test_load_manifest_rejects_duplicate_column_name() -> None:
    # Distinct JSON keys, but a repeated column NAME -> an ambiguous field key downstream ->
    # rejected at the parse layer (the schema analog of the duplicate-JSON-key guard above).
    raw = (
        b'{"dataset":"t.csv","columns":['
        b'{"type":"string","name":"x"},{"type":"numeric","name":"x","scale":0}]}'
    )
    with pytest.raises(msgspec.ValidationError):
        load_manifest(raw)
