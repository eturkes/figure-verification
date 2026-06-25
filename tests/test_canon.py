# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Deterministic tests for canonical forms + provenance hashing (M1.4a).

Asserts: the dataset hash is a tag-free raw-byte identity sensitive to row order /
CRLF / BOM; serialize_table emits stable typed-NDJSON (HALF_EVEN numerics, negative
zero folded, null distinct from "null"); the table/spec/manifest hashes are domain-
tagged; the spec hash is NFC-stable, flips on an edit, and asserts the pinned Unicode
database; and all four hashes are byte-identical across two PYTHONHASHSEED subprocesses.
"""

import hashlib
import os
import platform
import subprocess
import sys
import unicodedata
from decimal import Decimal
from pathlib import Path
from typing import Any

import msgspec
import pytest

from verifier import canon
from verifier.canon import (
    NumericColumn,
    StringColumn,
    Table,
    TemporalColumn,
    hash_dataset,
    hash_manifest,
    hash_spec,
    hash_table,
    runtime_versions,
    serialize_table,
)
from verifier.schema import VPlotSpec, decode_spec

ZERO_HASH = "sha256:" + "0" * 64


def _spec(value: object = "West", *, mark: str = "bar") -> VPlotSpec:
    """A valid spec whose single filter carries `value` (the lone NFC-sensitive site —
    field/dataset names are ASCII by pattern) and whose mark is editable for hash flips."""
    raw: dict[str, Any] = {
        "version": "vplot-0.1",
        "dataset": {"name": "sales.csv", "hash": ZERO_HASH},
        "transform": [{"op": "filter", "field": "region", "cmp": "eq", "value": value}],
        "mark": mark,
        "encoding": {
            "x": {"field": "region", "type": "nominal"},
            "y": {"field": "revenue", "type": "quantitative"},
        },
    }
    return decode_spec(msgspec.json.encode(raw))


def _table() -> Table:
    """A two-column table exercising a string column, a scale-2 numeric, and a null."""
    return Table(
        columns=(StringColumn(name="region"), NumericColumn(name="revenue", scale=2)),
        rows=(("West", Decimal("10.50")), ("East", Decimal("20.00")), (None, None)),
    )


# --- dataset hash: tag-free raw-byte source identity -------------------------
def test_hash_dataset_is_tag_free_sha256_of_raw_bytes() -> None:
    raw = b"region,revenue\nWest,10\n"
    assert hash_dataset(raw) == "sha256:" + hashlib.sha256(raw).hexdigest()  # no domain tag


def test_hash_dataset_sensitive_to_order_crlf_and_bom() -> None:
    base = b"region,revenue\nWest,10\nEast,20\n"
    assert hash_dataset(base) == hash_dataset(base)  # identity is stable
    reordered = b"region,revenue\nEast,20\nWest,10\n"
    crlf = base.replace(b"\n", b"\r\n")
    bom = b"\xef\xbb\xbf" + base
    assert len({hash_dataset(x) for x in (base, reordered, crlf, bom)}) == 4  # all distinct


# --- serialize_table: the typed-NDJSON canonical form ------------------------
def test_serialize_table_shape() -> None:
    assert serialize_table(_table()) == (
        '["region:string","revenue:numeric:2"]\n["West",10.50]\n["East",20.00]\n[null,null]\n'
    )


def test_serialize_temporal_descriptor_and_scale_zero() -> None:
    table = Table(
        columns=(TemporalColumn(name="date", granularity="date"), NumericColumn(name="v", scale=0)),
        rows=(("2024-01-01", Decimal(5)),),
    )
    assert serialize_table(table) == '["date:temporal:date","v:numeric:0"]\n["2024-01-01",5]\n'


def test_serialize_escapes_string_cells() -> None:
    """A newline inside a cell is JSON-escaped, so it cannot break the NDJSON line layout."""
    table = Table(columns=(StringColumn(name="s"),), rows=(("a\nb",),))
    assert serialize_table(table) == '["s:string"]\n["a\\nb"]\n'


@pytest.mark.parametrize(
    ("value", "scale", "rendered"),
    [
        (Decimal("1.005"), 2, "1.00"),  # HALF_EVEN: ties to the even (0) digit
        (Decimal("1.015"), 2, "1.02"),  # HALF_EVEN: ties to the even (2) digit
        (Decimal("9.9999"), 2, "10.00"),  # rounding carry within the computed precision
        (Decimal("0.004"), 2, "0.00"),  # magnitude below scale -> precision floor of 1
        (Decimal("12345678901234567890123456789012.5"), 0, "12345678901234567890123456789012"),
    ],
)
def test_format_decimal_half_even_and_precision(value: Decimal, scale: int, rendered: str) -> None:
    table = Table(columns=(NumericColumn(name="v", scale=scale),), rows=((value,),))
    assert serialize_table(table).splitlines()[1] == f"[{rendered}]"


def test_negative_zero_is_folded() -> None:
    pos = Table(columns=(NumericColumn(name="v", scale=2),), rows=((Decimal("0.00"),),))
    neg = Table(columns=(NumericColumn(name="v", scale=2),), rows=((Decimal("-0.00"),),))
    assert serialize_table(pos) == serialize_table(neg) == '["v:numeric:2"]\n[0.00]\n'
    assert hash_table(pos) == hash_table(neg)


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_serialize_rejects_non_finite_numeric(bad: Decimal) -> None:
    table = Table(columns=(NumericColumn(name="v", scale=2),), rows=((bad,),))
    with pytest.raises(ValueError, match="non-finite"):
        serialize_table(table)


def test_serialize_rejects_type_mismatched_cells() -> None:
    num_got_str = Table(columns=(NumericColumn(name="v", scale=2),), rows=(("x",),))
    with pytest.raises(TypeError, match="non-Decimal"):
        serialize_table(num_got_str)
    text_got_decimal = Table(columns=(StringColumn(name="s"),), rows=((Decimal(1),),))
    with pytest.raises(TypeError, match="non-str"):
        serialize_table(text_got_decimal)


def test_serialize_rejects_row_width_mismatch() -> None:
    table = Table(columns=(StringColumn(name="a"), StringColumn(name="b")), rows=(("x",),))
    with pytest.raises(ValueError, match="shorter"):  # zip(strict=True)
        serialize_table(table)


def test_serialize_handles_empty_rows_and_columns() -> None:
    assert serialize_table(Table(columns=(StringColumn(name="a"),), rows=())) == '["a:string"]\n'
    assert serialize_table(Table(columns=(), rows=((),))) == "[]\n[]\n"


def test_column_kind_discriminator() -> None:
    assert NumericColumn(name="v", scale=2).kind == "numeric"
    assert TemporalColumn(name="d", granularity="datetime").kind == "temporal"
    assert StringColumn(name="s").kind == "string"


# --- table hash: domain-tagged over the canonical form -----------------------
def test_hash_table_is_domain_tagged() -> None:
    table = _table()
    tag = f"vplot-table/{canon.CANON_VERSION}\n".encode()
    expected = "sha256:" + hashlib.sha256(tag + serialize_table(table).encode()).hexdigest()
    assert hash_table(table) == expected


def test_hash_table_flips_on_cell_column_or_scale() -> None:
    base = hash_table(_table())
    other_cell = Table(
        columns=(StringColumn(name="region"), NumericColumn(name="revenue", scale=2)),
        rows=(("West", Decimal("10.51")), ("East", Decimal("20.00")), (None, None)),
    )
    other_name = Table(
        columns=(StringColumn(name="area"), NumericColumn(name="revenue", scale=2)),
        rows=(("West", Decimal("10.50")), ("East", Decimal("20.00")), (None, None)),
    )
    other_scale = Table(
        columns=(StringColumn(name="region"), NumericColumn(name="revenue", scale=3)),
        rows=(("West", Decimal("10.50")), ("East", Decimal("20.00")), (None, None)),
    )
    assert len({base, *(hash_table(t) for t in (other_cell, other_name, other_scale))}) == 4


def test_hash_table_equal_for_independently_built_identical_tables() -> None:
    assert hash_table(_table()) == hash_table(_table())


# --- spec hash: deterministic re-encode, NFC-stable, UCD-pinned --------------
def test_hash_spec_is_sha256_prefixed_and_stable_across_reencode() -> None:
    digest = hash_spec(_spec())
    assert digest.startswith("sha256:") and len(digest) == len("sha256:") + 64
    assert hash_spec(_spec()) == digest  # a fresh decode of the same spec hashes alike


def test_hash_spec_flips_on_edit() -> None:
    assert hash_spec(_spec(mark="bar")) != hash_spec(_spec(mark="line"))


def test_hash_spec_folds_nfc_equivalent_strings() -> None:
    composed, decomposed = "café", "café"  # é vs e + combining acute
    assert composed != decomposed
    assert unicodedata.normalize("NFC", decomposed) == composed
    assert hash_spec(_spec(composed)) == hash_spec(_spec(decomposed))


def test_hash_spec_rejects_unicode_database_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(unicodedata, "unidata_version", "16.0.0")
    with pytest.raises(RuntimeError, match="Unicode database"):
        hash_spec(_spec())


# --- manifest hash: domain-tagged over raw bytes -----------------------------
def test_hash_manifest_is_domain_tagged_and_flips_on_bytes() -> None:
    raw = (Path(__file__).resolve().parent.parent / "data" / "schemas" / "sales.json").read_bytes()
    tag = f"vplot-manifest/{canon.CANON_VERSION}\n".encode()
    assert hash_manifest(raw) == "sha256:" + hashlib.sha256(tag + raw).hexdigest()
    assert hash_manifest(raw) != hash_manifest(raw + b"\n")


# --- runtime versions --------------------------------------------------------
def test_runtime_versions_reports_the_running_environment() -> None:
    versions = runtime_versions()
    assert versions.canon_version == canon.CANON_VERSION
    assert versions.python == platform.python_version()
    assert versions.msgspec == msgspec.__version__
    assert versions.unidata == unicodedata.unidata_version == canon.EXPECTED_UNIDATA


# --- cross-process determinism (PYTHONHASHSEED) ------------------------------
_DETERMINISM_PROG = """
from decimal import Decimal
import msgspec
from verifier import canon
from verifier.schema import decode_spec

spec = decode_spec(
    msgspec.json.encode(
        {
            "version": "vplot-0.1",
            "dataset": {"name": "sales.csv", "hash": "sha256:" + "0" * 64},
            "transform": [{"op": "filter", "field": "region", "cmp": "eq", "value": "café"}],
            "mark": "line",
            "encoding": {
                "x": {"field": "a", "type": "temporal"},
                "y": {"field": "b", "type": "quantitative"},
            },
        }
    )
)
table = canon.Table(
    columns=(canon.StringColumn(name="r"), canon.NumericColumn(name="v", scale=2)),
    rows=(("West", Decimal("10.50")), (None, None)),
)
print(canon.hash_dataset(b"region,rev\\nWest,10.50\\n"))
print(canon.hash_table(table))
print(canon.hash_spec(spec))
print(canon.hash_manifest(b"manifest-bytes"))
"""


def _hashes_under_seed(seed: str) -> str:
    result = subprocess.run(  # noqa: S603 — fixed interpreter + constant program
        [sys.executable, "-c", _DETERMINISM_PROG],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": seed},
    )
    return result.stdout


def test_all_four_hashes_are_stable_across_pythonhashseed() -> None:
    out = _hashes_under_seed("0")
    assert out == _hashes_under_seed("1")
    assert out.count("sha256:") == 4  # dataset, table, spec, manifest all emitted
