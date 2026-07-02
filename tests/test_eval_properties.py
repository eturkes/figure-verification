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
  - dataset-order-sensitivity: a single anchor witness -- a distinct row order is a distinct
    SOURCE identity (hash_dataset moves on raw bytes) yet the same PLOTTED identity (hash_table
    fixed); row order is source provenance, not plotted data. A concrete anchor, not a property,
    on purpose: the hash_dataset-moves half is SHA-256 over distinct bytes (tautological), and the
    hash_table-holds half is a special case of permutation-invariance above -- a randomized form
    adds no falsifying power, one witness states the decoupling;
  - PYTHONHASHSEED-stability: the evaluate -> hash_table pipeline is byte-identical across four
    interpreter processes (seed 0 = randomization off, .. 3) over tie-heavy rows that force the
    closure's tail tie-break -- the spot any dict/set iteration-order leak would reach the plotted
    order; it samples for a leak, it does not prove absence.
Rows go through csv.writer (CR-LF dialect), so an embedded comma / quote / CR-LF / NUL in a
string field round-trips through ingest's csv.reader(strict=True) without hand-escaping
(verified end-to-end against load_table). Cell strategies + the writer are the shared
tests/corpus.py (M1-review consolidation with the M1.5a spine property).
"""

import os
import subprocess
import sys

import msgspec
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.strategies import DrawFn

from corpus import csv_bytes, date_cell, numeric_cell, string_cell
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


# --- per-column cell strategies (every draw is an ingest-valid cell; tests/corpus.py) ---
@st.composite
def _row(draw: DrawFn) -> _Row:
    return (
        draw(string_cell()),
        draw(numeric_cell(0)),
        draw(numeric_cell(1)),
        draw(date_cell()),
    )


def _csv(rows: list[_Row]) -> bytes:
    return csv_bytes(_HEADER, rows)


def _table_hashes(rows: list[_Row]) -> tuple[str, ...]:
    """The plotted-table hash of each fixed spec over `rows`."""
    data = _csv(rows)  # `data`, not `csv_bytes`: the corpus import keeps that name
    return tuple(canon.hash_table(evaluate(spec, _MANIFEST, data)) for spec in _SPECS)


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
# One anchor, deliberately not a property: hash_dataset moving is SHA-256 over distinct bytes
# (tautological), and hash_table holding is a special case of permutation-invariance -- so a
# randomized form would add no falsifying power. This witness states the decoupling concretely.
def test_dataset_order_sensitivity() -> None:
    """Two byte-distinct row orders: hash_dataset differs (raw-byte source identity) while every
    spec's hash_table is identical (the closure re-derives one plotted order)."""
    forward: list[_Row] = [("x", "1", "1.0", "2026-01-01"), ("y", "2", "2.0", "2026-01-02")]
    backward = list(reversed(forward))
    assert canon.hash_dataset(_csv(forward)) != canon.hash_dataset(_csv(backward))
    assert _table_hashes(forward) == _table_hashes(backward)


# --- PYTHONHASHSEED-stability of the full evaluate -> hash_table pipeline -------
# Tie-heavy rows force the closure's tail tie-break in BOTH specs (duplicate sum_a across groups
# p/q/r; duplicate d across rows) -- the spot a dict/set iteration-order leak would reach the
# plotted order. Seeds 0 (randomization off) .. 3 must all agree; the closure's total sort is what
# should defeat any leak -- this samples for one, it does not prove absence.
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
    ["p", "2", "1.0", "2026-01-01"],
    ["p", "4", "3.0", "2026-01-01"],
    ["q", "6", "2.0", "2026-01-01"],
    ["q", "0", "8.0", "2026-01-02"],
    ["r", "6", "5.0", "2026-01-02"],
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
    outputs = [_pipeline_hashes_under_seed(str(seed)) for seed in range(4)]
    assert len(set(outputs)) == 1  # byte-identical across seeds 0..3 -- no iteration-order leak
    assert outputs[0].count("sha256:") == 2  # both specs emitted a plotted-table hash
