# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Property tests for verifier.eval determinism (M1.4g).

A test-only Hypothesis layer over the already-100%-covered M1.4d evaluator (no new verifier
code, no oracle -- duckdb is absent here). A FIXED small manifest + two FIXED specs hold the
spec side constant; Hypothesis generates only the CSV ROWS over it (per column: numeric ->
exact-at-scale decimal text, date -> canonical ISO, string -> UTF-8 text; "" -> the section-2
null, since an empty cell ingests as None). Three determinism properties of the
evaluate -> canon.hash_table pipeline:
  - permutation-invariance: reordering the source rows leaves hash_table fixed (the section-6
    total-sort closure re-derives one plotted order), for both a group_by/aggregate and a
    select spec;
  - dataset-order-sensitivity: a distinct row order is a distinct SOURCE identity
    (hash_dataset moves) yet the same PLOTTED identity (hash_table fixed) -- row order is
    source provenance, not plotted data;
  - PYTHONHASHSEED-stability: the whole pipeline is byte-identical across two interpreter
    processes seeded differently (no dict/set iteration order leaks into a hash).
Rows go through csv.writer (CR-LF dialect), so an embedded comma / quote / CR-LF / NUL in a
string field round-trips through ingest's csv.reader(strict=True) without hand-escaping
(verified end-to-end against load_table).
"""

import csv
import io
import os
import subprocess
import sys
from datetime import date
from decimal import Decimal

import msgspec
from hypothesis import assume, given
from hypothesis import strategies as st
from hypothesis.strategies import DrawFn, SearchStrategy

from verifier import canon
from verifier.eval import evaluate
from verifier.ingest import Manifest, NumericColumnSpec, StringColumnSpec, TemporalColumnSpec
from verifier.schema import VPlotSpec, decode_spec

type _Row = tuple[str, str, str, str]  # (k, a, b, d) cell texts; "" = null (section 2 empty->None)

_HEADER = ("k", "a", "b", "d")
_MANIFEST = Manifest(
    dataset="t.csv",
    columns=(
        StringColumnSpec(name="k"),
        NumericColumnSpec(name="a", scale=0),
        NumericColumnSpec(name="b", scale=1),
        TemporalColumnSpec(name="d", granularity="date"),
    ),
)


def _spec(transform: list[dict[str, object]]) -> VPlotSpec:
    """A valid spec over the fixed manifest (placeholder dataset hash + encoding -- evaluate
    inspects neither), decoded so it carries the same frozen op types a real spec would."""
    raw: dict[str, object] = {
        "version": "vplot-0.1",
        "dataset": {"name": "t.csv", "hash": "sha256:" + "0" * 64},
        "transform": transform,
        "mark": "bar",
        "encoding": {
            "x": {"field": "k", "type": "nominal"},
            "y": {"field": "a", "type": "quantitative"},
        },
    }
    return decode_spec(msgspec.json.encode(raw))


# group_by + aggregate (sum + mean) + sort, and a select + sort: two shapes whose plotted order
# is fixed by the section-6 closure, so both must be row-permutation-invariant.
_GROUP_SPEC = _spec(
    [
        {"op": "group_by", "keys": ["k"]},
        {
            "op": "aggregate",
            "measures": [
                {"field": "a", "fn": "sum", "as": "sum_a"},
                {"field": "b", "fn": "mean", "as": "mean_b"},
            ],
        },
        {"op": "sort", "by": [{"field": "sum_a", "order": "ascending"}]},
    ]
)
_SELECT_SPEC = _spec(
    [
        {"op": "select", "fields": ["d", "k", "a", "b"]},
        {"op": "sort", "by": [{"field": "d", "order": "ascending"}]},
    ]
)
_SPECS = (_GROUP_SPEC, _SELECT_SPEC)


# --- per-column cell strategies (every draw is an ingest-valid cell) ----------
_SCALED_INT = st.integers(min_value=-(10**9), max_value=10**9)


def _decimal_text(scaled: int, scale: int) -> str:
    """Render `scaled * 10**-scale` as exact fixed-point text at `scale` places -- ingest accepts
    it verbatim (finite, within DECIMAL(38, scale), no excess precision)."""
    quantum = Decimal(1).scaleb(-scale)
    return str(Decimal(scaled).scaleb(-scale).quantize(quantum))


def _numeric_cell(scale: int) -> SearchStrategy[str]:
    return st.just("") | st.builds(_decimal_text, _SCALED_INT, st.just(scale))


def _date_cell() -> SearchStrategy[str]:
    return st.just("") | st.dates().map(date.isoformat)


def _string_cell() -> SearchStrategy[str]:
    # Any UTF-8 text -- commas / quotes / CR-LF / NUL are quoted by csv.writer and round-trip;
    # "" is the deliberate null. A lone surrogate is excluded by codec="utf-8".
    return st.text(st.characters(codec="utf-8"), max_size=8)


@st.composite
def _row(draw: DrawFn) -> _Row:
    return (
        draw(_string_cell()),
        draw(_numeric_cell(0)),
        draw(_numeric_cell(1)),
        draw(_date_cell()),
    )


def _csv(rows: list[_Row]) -> bytes:
    """Header + rows via csv.writer (CR-LF dialect), UTF-8 -- exactly what ingest reads back."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(_HEADER)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _table_hashes(rows: list[_Row]) -> tuple[str, ...]:
    """The plotted-table hash of each fixed spec over `rows`."""
    csv_bytes = _csv(rows)
    return tuple(canon.hash_table(evaluate(spec, _MANIFEST, csv_bytes)) for spec in _SPECS)


# --- permutation-invariance: row order does not move the plotted-table hash ---
@st.composite
def _rows_and_permutation(draw: DrawFn) -> tuple[list[_Row], list[_Row]]:
    rows = draw(st.lists(_row(), max_size=6))
    return rows, list(draw(st.permutations(rows)))


@given(_rows_and_permutation())
def test_row_permutation_preserves_table_hash(case: tuple[list[_Row], list[_Row]]) -> None:
    rows, permuted = case
    assert _table_hashes(rows) == _table_hashes(permuted)


# --- dataset-order-sensitivity: source identity moves, plotted identity holds --
def test_dataset_order_sensitivity_anchor() -> None:
    """Two byte-distinct row orders: hash_dataset differs (raw-byte source identity) while every
    spec's hash_table is identical (the closure re-derives one plotted order)."""
    forward: list[_Row] = [("x", "1", "1.0", "2026-01-01"), ("y", "2", "2.0", "2026-01-02")]
    backward = list(reversed(forward))
    assert canon.hash_dataset(_csv(forward)) != canon.hash_dataset(_csv(backward))
    assert _table_hashes(forward) == _table_hashes(backward)


@given(st.lists(_row(), min_size=2, max_size=6))
def test_dataset_order_sensitivity(rows: list[_Row]) -> None:
    reversed_rows = list(reversed(rows))
    forward, backward = _csv(rows), _csv(reversed_rows)
    assume(forward != backward)  # exclude all-duplicate / palindromic orders (raw bytes unchanged)
    assert canon.hash_dataset(forward) != canon.hash_dataset(backward)
    assert _table_hashes(rows) == _table_hashes(reversed_rows)


# --- PYTHONHASHSEED-stability of the full evaluate -> hash_table pipeline -------
# Multiple string-keyed groups, so a leak of dict/set iteration order into a hash would surface
# as a seed-dependent digest. The closure's total sort is what defeats it -- this proves it.
_DETERMINISM_PROG = """
import csv, io
import msgspec
from verifier import canon
from verifier.eval import evaluate
from verifier.ingest import Manifest, NumericColumnSpec, StringColumnSpec, TemporalColumnSpec
from verifier.schema import decode_spec

manifest = Manifest(
    dataset="t.csv",
    columns=(
        StringColumnSpec(name="k"),
        NumericColumnSpec(name="a", scale=0),
        NumericColumnSpec(name="b", scale=1),
        TemporalColumnSpec(name="d", granularity="date"),
    ),
)


def spec(transform):
    return decode_spec(
        msgspec.json.encode(
            {
                "version": "vplot-0.1",
                "dataset": {"name": "t.csv", "hash": "sha256:" + "0" * 64},
                "transform": transform,
                "mark": "bar",
                "encoding": {
                    "x": {"field": "k", "type": "nominal"},
                    "y": {"field": "a", "type": "quantitative"},
                },
            }
        )
    )


group_spec = spec([
    {"op": "group_by", "keys": ["k"]},
    {"op": "aggregate", "measures": [
        {"field": "a", "fn": "sum", "as": "sum_a"},
        {"field": "b", "fn": "mean", "as": "mean_b"},
    ]},
    {"op": "sort", "by": [{"field": "sum_a", "order": "ascending"}]},
])
select_spec = spec([
    {"op": "select", "fields": ["d", "k", "a", "b"]},
    {"op": "sort", "by": [{"field": "d", "order": "ascending"}]},
])

rows = [
    ["gamma", "3", "3.0", "2026-01-03"],
    ["alpha", "1", "1.0", "2026-01-01"],
    ["beta", "2", "2.0", "2026-01-02"],
    ["alpha", "5", "5.5", "2026-01-04"],
    ["", "", "", ""],
]
buf = io.StringIO(newline="")
w = csv.writer(buf)
w.writerow(["k", "a", "b", "d"])
w.writerows(rows)
csv_bytes = buf.getvalue().encode("utf-8")

print(canon.hash_table(evaluate(group_spec, manifest, csv_bytes)))
print(canon.hash_table(evaluate(select_spec, manifest, csv_bytes)))
"""


def _pipeline_hashes_under_seed(seed: str) -> str:
    result = subprocess.run(  # noqa: S603 -- fixed interpreter + constant program
        [sys.executable, "-c", _DETERMINISM_PROG],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": seed},
    )
    return result.stdout


def test_pipeline_hash_stable_across_pythonhashseed() -> None:
    out = _pipeline_hashes_under_seed("0")
    assert out == _pipeline_hashes_under_seed("1")
    assert out.count("sha256:") == 2  # both specs emitted a plotted-table hash
