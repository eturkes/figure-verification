# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""`canon.parse_table`: the one deserializer of typed-NDJSON plotted tables.

It decodes, then re-serializes and demands the original bytes, so a returned table always hashes
to the digest of the bytes it came from. Every expectation is a hand-written byte string.
"""

from decimal import Decimal

import pytest

from verifier import canon

_TABLE = canon.Table(
    columns=(
        canon.StringColumn(name="region"),
        canon.TemporalColumn(name="month", granularity="date"),
        canon.NumericColumn(name="revenue", scale=2),
    ),
    rows=(
        ("East", "2024-01-01", Decimal("10.50")),
        (None, None, None),
        ('Nor"th\nwest', "2024-02-01", Decimal("-3.00")),
        ("日本", "2024-03-01", Decimal("0.00")),
    ),
)
_BYTES = (
    b'["region:string","month:temporal:date","revenue:numeric:2"]\n'
    b'["East","2024-01-01",10.50]\n'
    b"[null,null,null]\n"
    b'["Nor\\"th\\nwest","2024-02-01",-3.00]\n'
    b'["\xe6\x97\xa5\xe6\x9c\xac","2024-03-01",0.00]\n'
)


def test_parse_table_inverts_serialize_table() -> None:
    assert canon.serialize_table(_TABLE).encode("utf-8") == _BYTES
    assert canon.parse_table(_BYTES) == _TABLE
    assert canon.hash_table(canon.parse_table(_BYTES)) == canon.hash_table_bytes(_BYTES)


def test_parse_table_reads_a_header_only_table() -> None:
    table = canon.parse_table(b'["x:numeric:0","y:temporal:datetime"]\n')
    assert table == canon.Table(
        columns=(
            canon.NumericColumn(name="x", scale=0),
            canon.TemporalColumn(name="y", granularity="datetime"),
        ),
        rows=(),
    )


@pytest.mark.parametrize(
    "payload",
    [
        b"not-typed-ndjson",
        b"",
        b'["x:float"]\n',
        b'["x:numeric:-1"]\n',
        b'["x:temporal:week"]\n',
        b'["x:stringy"]\n',
        b'["x:numeric:1x"]\n',
        b'["x:numeric:0"]\n[1,2]\n',
        b'["x:numeric:1"]\n[1.5]\n\n',
        b'["x:string"]\n[1]\n',
        b'["x:numeric:0"]\n[1]\n\n[2]\n',
        b'["x:string"]\n["\xff"]\n',
        b'["x:numeric:0"]\n[true]\n',
    ],
)
def test_parse_table_refuses_bytes_that_are_not_typed_ndjson(payload: bytes) -> None:
    with pytest.raises(canon.TableDecodeError):
        canon.parse_table(payload)


@pytest.mark.parametrize(
    "payload",
    [
        b'["x:numeric:1"]\n[1.5]',
        b'["x:numeric:1"]\n[1.50]\n',
        b'["x:numeric:1"]\n[-0.0]\n',
        b'["x:numeric:0"]\n["1"]\n',
        b'["x:numeric:1"] \n[1.5]\n',
        b'["x:numeric:1"]\n[ 1.5]\n',
        b'["x:string"]\n["\\u0041"]\n',
        b'["x:numeric:1", "y:string"]\n[1.5,"a"]\n',
    ],
)
def test_parse_table_refuses_typed_ndjson_that_is_not_canonical(payload: bytes) -> None:
    with pytest.raises(canon.NonCanonicalTableError):
        canon.parse_table(payload)
