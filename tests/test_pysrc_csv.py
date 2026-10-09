# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The safe CSV profile, read through its consumer `verifier.figure.sources.read_table`.

The sandbox parses the user's file with `pandas.read_csv`; the verifier may not depend on pandas
and parses with stdlib `csv` + `float`. A file whose STRUCTURE the two would read differently is
refused whole (`Unreadable`); a CELL the two would read differently makes its column unusable as
numbers (`numbers is None`), so no explanation reads it as a value. Profile + evidence =
`.agent/archive/contracts/m13u5.md` C6-C11 + Q12 (re-rooted from the retired static path, M19.7b).
"""

import pytest

from verifier.figure.sources import Column, Table, Unreadable, read_table
from verifier.pysrc.budget import WorkBudget
from verifier.pysrc.csvread import _read_csv
from verifier.pysrc.errors import PysrcRefusalError
from verifier.pysrc.limits import DEFAULT_LIMITS, PysrcLimits

_NA_SPELLINGS = (
    "",
    "#N/A",
    "#N/A N/A",
    "#NA",
    "-1.#IND",
    "-1.#QNAN",
    "-NaN",
    "-nan",
    "1.#IND",
    "1.#QNAN",
    "<NA>",
    "N/A",
    "NA",
    "NULL",
    "NaN",
    "None",
    "n/a",
    "nan",
    "null",
)


def _table(content: bytes) -> Table:
    table = read_table("measurements.csv", content)
    assert isinstance(table, Table)
    return table


def _value(content: bytes) -> Column:
    return _table(content).columns[1]


def test_c6_strict_structural_profile() -> None:
    """UTF-8 without BOM, one header, at least one data row, fixed width, no post-quote junk.

    Accept: BOM, header-only, short row, long row, post-quote junk, a duplicate or empty header
    name, NUL, a bare CR, invalid UTF-8 and empty content each refuse the file
    `csv_not_parsable`; the same rows with CRLF endings read.
    """
    assert _table(b"site,value\nwest,1\neast,2\n").header == ("site", "value")
    assert _table(b"a,b\r\n1,2\r\n").header == ("a", "b")
    malformed = {
        "bom": b"\xef\xbb\xbfsite,value\nwest,1\n",
        "header-only": b"site,value\n",
        "short-row": b"site,value\nwest\n",
        "long-row": b"site,value\nwest,1,extra\n",
        "post-quote-junk": b'site,value\nwest,"1"junk\n',
        "duplicate-name": b"site,value,site\nwest,1,east\n",
        "empty-name": b"site,value,\nwest,1,2\n",
        "nul": b"site,value\nwest,\x001\n",
        "bare-cr": b"a,b\r1,2\n",
        "invalid-utf8": b"a,b\n\xff\xfe,2\n",
        "empty": b"",
    }
    for name, content in malformed.items():
        assert read_table("m.csv", content) == Unreadable("m.csv", "csv_not_parsable"), name


@pytest.mark.parametrize(
    ("content", "numbers", "keys"),
    [
        (b"site,value\n1,10\n2,20\n", (10.0, 20.0), (10.0, 20.0)),
        (b"site,value\n1,ten\n2,twelve\n", None, ("ten", "twelve")),
        (b"site,value\n1,ten\n2,20\n", None, ("ten", "20")),
        (
            (
                "site,value\n"
                "1,\N{FULLWIDTH DIGIT ONE}\N{FULLWIDTH DIGIT TWO}\N{FULLWIDTH DIGIT THREE}\n"
                "2,\N{FULLWIDTH DIGIT FOUR}\N{FULLWIDTH DIGIT FIVE}\N{FULLWIDTH DIGIT SIX}\n"
            ).encode(),
            None,
            None,
        ),
    ],
    ids=["numeric", "categorical", "mixed", "fullwidth-digits"],
)
def test_c8_a_column_is_numbers_only_when_every_cell_is_in_profile(
    content: bytes, numbers: tuple[float, ...] | None, keys: tuple[float | str, ...] | None
) -> None:
    """Classify by stdlib `float(text)` success, then apply profile admission.

    Accept: numeric cells read as numbers + numeric keys; categorical + mixed columns keep their
    text as keys and offer no numbers; full-width digits (`float` parses them, pandas does not)
    offer no numbers and stay text keys.
    """
    column = _value(content)
    assert column.numbers == numbers
    assert column.keys == (keys if keys is not None else column.texts)


def test_c9_no_null_or_bool_survives_as_a_number() -> None:
    """Every NA spelling, plain and quoted, and bool-like text leave a column with no numbers.

    Accept: each of the 19 spellings + `True` `FALSE` `true` in an otherwise-numeric column; the
    case variant `NuLL` stays plain text, and `NAN` (stdlib parses it, pandas keeps it as a string)
    refuses as a number -- the conservative direction.
    """
    assert len(_NA_SPELLINGS) == 19
    for spelling in (*_NA_SPELLINGS, "True", "FALSE", "true", "NAN"):
        for cell in (spelling, f'"{spelling}"'):
            column = _value(f"site,value\n1,1\n2,{cell}\n".encode())
            assert column.numbers is None, (spelling, cell)
    near_miss = _value(b"site,value\n1,NuLL\n")
    assert (near_miss.numbers, near_miss.keys) == (None, ("NuLL",))


def test_c10_profile_boundaries_leave_no_numbers() -> None:
    """Every out-of-profile numeric candidate makes its column unusable as numbers.

    Accept: all 13 named boundary families; representative values inside the measured region read
    as exact binary64 numbers.
    """
    outside_profile: dict[str, tuple[str, ...]] = {
        "exponent": ("1e2",),
        "leading-plus": ("+1",),
        "surrounding-whitespace": (" 1", "1 "),
        "leading-or-trailing-point": (".5", "1."),
        "redundant-leading-zero": ("01",),
        "underscore": ("1_0",),
        "thousands-separator": ("1,000",),
        "hex": ("0x1f",),
        "seven-decimals": ("0.1234567",),
        "sixteen-significant-digits": ("1234567890.123456",),
        "out-of-range": ("2147483648",),
        "non-finite": ("inf",),
        "negative-zero": ("-0.0",),
    }
    assert len(outside_profile) == 13
    for boundary, candidates in outside_profile.items():
        for candidate in candidates:
            cell = f'"{candidate}"' if "," in candidate else candidate
            column = _value(f"site,value\n1,1\n2,{cell}\n".encode())
            assert column.numbers is None, (boundary, candidate)
    inside = _value(
        b"site,value\n1,-2147483648\n2,2147483647\n3,123456789.123456\n4,0\n5,0.000001\n"
    )
    assert inside.numbers == (-2147483648.0, 2147483647.0, 123456789.123456, 0.0, 0.000001)


def test_c10_an_integer_column_admits_both_int32_endpoints() -> None:
    """C10's int32 clause is inclusive at both ends, in an integer-only column (a decimal point
    would make the column float64 and lift the clause); one past either end offers no numbers."""
    column = _value(b"site,value\n1,2147483647\n2,-2147483648\n")
    assert column.integer
    assert column.numbers == (2147483647.0, -2147483648.0)
    assert _value(b"site,value\n1,2147483648\n").numbers is None
    assert _value(b"site,value\n1,-2147483649\n").numbers is None


def test_c11_source_order_is_preserved() -> None:
    """Rows stay in file order: a CSV not sorted by any column reads in file order."""
    table = _table(b"site,value\n3,30\n1,10\n2,20\n")
    assert table.columns[0].numbers == (3.0, 1.0, 2.0)
    assert table.columns[1].numbers == (30.0, 10.0, 20.0)
    assert table.rows == 3


def test_q12_a_float64_column_admits_magnitudes_past_int32() -> None:
    """Q12 (user ruling): a column pandas infers float64 -- any token with a decimal point --
    admits cells past int32, its integer tokens included, up to the 15-digit cap; an integer
    column keeps the int32 clause."""
    float_column = _value(b"site,value\n1,-999999999999999\n2,3000000000\n3,99999999999999.9\n")
    assert float_column.numbers == (-999999999999999.0, 3000000000.0, 99999999999999.9)
    assert not float_column.integer
    assert _value(b"site,value\n1,3000000000\n2,1\n").numbers is None
    assert _value(b"site,value\n1,1234567890123456.0\n2,1\n").numbers is None
    assert _value(b"site,value\n1,3\n2,1\n").integer


@pytest.mark.parametrize(
    ("limits", "content", "code"),
    [
        (PysrcLimits(max_csv_bytes=10), b"site,value\nwest,1\n", "csv_too_large"),
        (PysrcLimits(max_csv_cell_bytes=4), b"site,value\nwest,1\n", "csv_too_large"),
        (PysrcLimits(max_csv_columns=1), b"site,value\nwest,1\n", "csv_too_large"),
        (PysrcLimits(max_csv_rows=1), b"site,value\nwest,1\neast,2\n", "csv_too_large"),
        (PysrcLimits(max_table_rows=1), b"site,value\nwest,1\neast,2\n", "work_budget_exceeded"),
    ],
    ids=["bytes", "cell", "columns", "rows", "table-rows"],
)
def test_each_ceiling_refuses_before_the_work_it_bounds(
    limits: PysrcLimits, content: bytes, code: str
) -> None:
    """Every ceiling refuses its own code; the same file reads under the default ceilings."""
    with pytest.raises(PysrcRefusalError) as refused:
        _read_csv(content, limits, WorkBudget(DEFAULT_LIMITS.max_work))
    assert refused.value.code == code
    assert _read_csv(content, DEFAULT_LIMITS, WorkBudget(DEFAULT_LIMITS.max_work))[0] == (
        "site",
        "value",
    )
