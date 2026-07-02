# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Shared Hypothesis row strategies + CSV writer for the property suites (M1 review
consolidation of the M1.4g / M1.5a duplicates; tests-local like the DuckDB oracle).

Every draw is an ingest-valid cell (VPlot_SEMANTICS.md sections 2-3): numeric -> exact
fixed-point text at the column scale, temporal -> canonical ISO date, string -> any UTF-8
text; "" -> the section-2 null. codec="utf-8" excludes the one non-encodable input (lone
surrogates); an embedded comma / quote / CR-LF / NUL is quoted by csv.writer and round-trips
through ingest's csv.reader(strict=True) (verified end-to-end in the M1.4g suite).
"""

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal

from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy


def decimal_text(scaled: int, scale: int) -> str:
    """Render `scaled * 10**-scale` as exact fixed-point text at `scale` places — ingest
    accepts it verbatim (finite, within DECIMAL(38, scale), no excess precision)."""
    quantum = Decimal(1).scaleb(-scale)
    return str(Decimal(scaled).scaleb(-scale).quantize(quantum))


def numeric_cell(scale: int, magnitude: int = 10**9) -> SearchStrategy[str]:
    """An exact-at-scale numeric cell text (scaled integer in ±`magnitude`), or "" (null)."""
    scaled = st.integers(min_value=-magnitude, max_value=magnitude)
    return st.just("") | st.builds(decimal_text, scaled, st.just(scale))


def date_cell() -> SearchStrategy[str]:
    """A canonical ISO date cell, or "" (null)."""
    return st.just("") | st.dates().map(date.isoformat)


def string_cell(max_size: int = 8) -> SearchStrategy[str]:
    """Any UTF-8 text cell ("" doubles as the null)."""
    return st.text(st.characters(codec="utf-8"), max_size=max_size)


def csv_bytes(header: Sequence[str], rows: Iterable[Sequence[str]]) -> bytes:
    """Header + rows via csv.writer (CR-LF dialect), UTF-8 — exactly what ingest reads back."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")
