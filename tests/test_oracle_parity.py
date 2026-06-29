# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Dual-engine parity: verifier.eval's hand-rolled Decimal pipeline vs the DuckDB oracle must
produce the byte-identical canonical plotted table. This is the real correctness oracle behind
the M1.4d-e self-locked goldens -- two engines INDEPENDENT in their computation (DuckDB runs
filter/select/group_by/aggregate/sort itself) that must agree. The shared surface is deliberate
+ minimal: ingestion (verifier.ingest.load_table, so both see the same coerced cells) and mean's
final division (verifier.eval.mean_at_scale, since SQL division rounds the wrong way) -- so mean
ROUNDING is not independently cross-checked here (test_eval pins half-even directly); the rest is.

Two layers: test_oracle_matches_eval over the 10 M1.3 goldens, and
test_oracle_matches_eval_synthetic over adversarial in-process specs the fixed corpus leaves
cold -- every comparator + the null three-valued drop, scientific-notation filter literals (a
positive-exponent DuckDB bind bug, regression), count vs sum, whole-table + all-null aggregates,
multi-measure / multi-key group + sort, min/max over temporal + string, a 38-digit in-domain sum.

eval runs FIRST (it is the trusted reference + the validation gate): a spec it rejects never
reaches the oracle, which recomputes only eval-validated specs (oracle module docstring)."""

import hashlib
import json
import pathlib
from typing import Any

import msgspec
import pytest

from oracle import recompute
from verifier import canon
from verifier.errors import VerificationError
from verifier.eval import evaluate
from verifier.ingest import Manifest, load_manifest
from verifier.schema import VPlotSpec, decode_spec

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EXAMPLES = ROOT / "examples"

# (good-spec filename, dataset stem) — the 10 M1.3 goldens.
_GOLDENS = [
    ("g01_total_revenue_by_month.json", "sales"),
    ("g02_revenue_by_region.json", "sales"),
    ("g03_order_count_by_month.json", "sales"),
    ("g04_revenue_vs_orders.json", "sales"),
    ("g05_avg_revenue_by_region.json", "sales"),
    ("g06_max_temp_by_city.json", "weather"),
    ("g07_temp_over_time_by_city.json", "weather"),
    ("g08_na_revenue_by_month.json", "sales"),
    ("g09_min_revenue_by_month.json", "sales"),
    ("g10_temp_vs_precip.json", "weather"),
]


@pytest.mark.parametrize(("filename", "stem"), _GOLDENS)
def test_oracle_matches_eval(filename: str, stem: str) -> None:
    spec = decode_spec((EXAMPLES / "good_specs" / filename).read_bytes())
    manifest = load_manifest((DATA / "schemas" / f"{stem}.json").read_bytes())
    csv_bytes = (DATA / f"{stem}.csv").read_bytes()

    expected = evaluate(spec, manifest, csv_bytes)
    actual = recompute(spec, manifest, csv_bytes)

    assert canon.serialize_table(actual) == canon.serialize_table(expected)
    assert canon.hash_table(actual) == canon.hash_table(expected)


# --- synthetic adversarial parity --------------------------------------------
# The goldens are fixed-shape; these in-process specs exercise the oracle branches they leave cold.
# Each manifest is a minimal per-column schema; the helpers build the transform compactly.
_NUM = b'{"dataset":"t.csv","columns":[{"name":"v","type":"numeric","scale":0,"label":"V"}]}'
_NUM2 = b'{"dataset":"t.csv","columns":[{"name":"v","type":"numeric","scale":2,"label":"V"}]}'
_KV = (
    b'{"dataset":"t.csv","columns":['
    b'{"name":"k","type":"string","label":"K"},'
    b'{"name":"v","type":"numeric","scale":0,"label":"V"}]}'
)
_AB = (
    b'{"dataset":"t.csv","columns":['
    b'{"name":"a","type":"string","label":"A"},'
    b'{"name":"b","type":"string","label":"B"},'
    b'{"name":"v","type":"numeric","scale":0,"label":"V"}]}'
)
_DATE = (
    b'{"dataset":"t.csv","columns":'
    b'[{"name":"d","type":"temporal","granularity":"date","label":"D"}]}'
)
_DT = (
    b'{"dataset":"t.csv","columns":'
    b'[{"name":"d","type":"temporal","granularity":"datetime","label":"D"}]}'
)
_STR = b'{"dataset":"t.csv","columns":[{"name":"s","type":"string","label":"S"}]}'
_KD = (
    b'{"dataset":"t.csv","columns":['
    b'{"name":"k","type":"string","label":"K"},'
    b'{"name":"d","type":"temporal","granularity":"date","label":"D"}]}'
)
_KS = (
    b'{"dataset":"t.csv","columns":['
    b'{"name":"k","type":"string","label":"K"},'
    b'{"name":"s","type":"string","label":"S"}]}'
)

# k,v rows with a null measure (row z's empty field) -- the comparator + count fixtures.
_KV_NULLS = b"k,v\na,1\nb,2\nc,3\nz,\n"
_KV_MIX = b"k,v\na,10\na,\na,20\nb,5\n"  # a: count 2 / sum 30 / mean 15; the null is excluded.


def _flt(field: str, cmp: str, value: object) -> list[dict[str, Any]]:
    return [{"op": "filter", "field": field, "cmp": cmp, "value": value}]


def _grp_agg(keys: list[str], measures: list[tuple[str, str, str]]) -> list[dict[str, Any]]:
    ops: list[dict[str, Any]] = []
    if keys:
        ops.append({"op": "group_by", "keys": keys})
    rows = [{"field": f, "fn": fn, "as": out} for f, fn, out in measures]
    ops.append({"op": "aggregate", "measures": rows})
    return ops


def _sort(keys: list[tuple[str, str]]) -> list[dict[str, Any]]:
    return [{"op": "sort", "by": [{"field": f, "order": o} for f, o in keys]}]


def _spec_manifest(
    manifest_json: bytes, csv: bytes, transform: list[dict[str, Any]]
) -> tuple[VPlotSpec, Manifest]:
    """A decoded spec + manifest for a synthetic case. encoding is recompute/evaluate-irrelevant
    (only M1.6 render reads it), so x/y just name real columns to satisfy the schema gate."""
    cols = [c["name"] for c in json.loads(manifest_json)["columns"]]
    raw = msgspec.json.encode(
        {
            "version": "vplot-0.1",
            "dataset": {"name": "t.csv", "hash": "sha256:" + hashlib.sha256(csv).hexdigest()},
            "transform": transform,
            "mark": "bar",
            "encoding": {
                "x": {"field": cols[0], "type": "nominal"},
                "y": {"field": cols[-1], "type": "quantitative"},
            },
        }
    )
    return decode_spec(raw), load_manifest(manifest_json)


_SYNTHETIC: dict[str, tuple[bytes, bytes, list[dict[str, Any]]]] = {
    # Finding 1 regression: positive-exponent literals DuckDB's binder mis-bound (1e2 -> 1.00).
    "filter_sci_1e2_gt": (_NUM, b"v\n99\n100\n101\n", _flt("v", "gt", "1e2")),
    "filter_sci_1.0e2_le": (_NUM, b"v\n99\n100\n101\n", _flt("v", "le", "1.0e2")),
    "filter_sci_12e1_ge": (_NUM, b"v\n119\n120\n121\n", _flt("v", "ge", "12e1")),
    "filter_sci_scale2_gt": (_NUM2, b"v\n99.99\n100.00\n100.01\n", _flt("v", "gt", "1e2")),
    "filter_sci_1e37_lt": (
        _NUM,
        b"v\n" + b"9" * 37 + b"\n1" + b"0" * 37 + b"\n",
        _flt("v", "lt", "1e37"),
    ),
    # Every comparator + the null three-valued drop (row z's v is null -> dropped under each op).
    "filter_eq": (_KV, _KV_NULLS, _flt("v", "eq", 2)),
    "filter_ne": (_KV, _KV_NULLS, _flt("v", "ne", 2)),
    "filter_lt": (_KV, _KV_NULLS, _flt("v", "lt", 2)),
    "filter_le": (_KV, _KV_NULLS, _flt("v", "le", 2)),
    "filter_gt": (_KV, _KV_NULLS, _flt("v", "gt", 2)),
    "filter_ge": (_KV, _KV_NULLS, _flt("v", "ge", 2)),
    # Temporal (native date/datetime bind, T-separator round-trip) + verbatim string filters.
    "filter_date_gt": (
        _DATE,
        b"d\n2026-01-01\n2026-01-02\n2026-01-03\n",
        _flt("d", "gt", "2026-01-02"),
    ),
    "filter_datetime_gt": (
        _DT,
        b"d\n2026-01-01T00:00:00\n2026-01-01T12:30:00\n",
        _flt("d", "gt", "2026-01-01T06:00:00"),
    ),
    "filter_string_gt": (_STR, b"s\napple\nbanana\ncherry\n", _flt("s", "gt", "apple")),
    "filter_string_eq": (_STR, b"s\napple\nbanana\ncherry\n", _flt("s", "eq", "banana")),
    # count != sum, and the null is excluded from count(non-null).
    "agg_count_vs_sum": (_KV, _KV_MIX, _grp_agg(["k"], [("v", "count", "c"), ("v", "sum", "s")])),
    # multi-measure: every fn in one aggregate (positional result mapping; scale-0 mean division).
    "agg_multi_measure": (
        _KV,
        _KV_MIX,
        _grp_agg(
            ["k"],
            [
                ("v", "sum", "sv"),
                ("v", "count", "cv"),
                ("v", "mean", "mv"),
                ("v", "min", "mn"),
                ("v", "max", "mx"),
            ],
        ),
    ),
    # whole-table aggregate (no group_by -> one row).
    "agg_whole_table": (
        _KV,
        b"k,v\na,10\nb,20\nc,30\n",
        _grp_agg([], [("v", "sum", "sv"), ("v", "count", "cv")]),
    ),
    # all-null measure in group b: sum/mean/min/max -> null, count -> 0.
    "agg_all_null_group": (
        _KV,
        b"k,v\na,1\nb,\nb,\n",
        _grp_agg(
            ["k"],
            [
                ("v", "sum", "s"),
                ("v", "mean", "m"),
                ("v", "min", "mn"),
                ("v", "max", "mx"),
                ("v", "count", "c"),
            ],
        ),
    ),
    # multi-key group + multi-key sort with mixed directions (then the section 6 closure tiebreak).
    "agg_multikey_group_sort": (
        _AB,
        b"a,b,v\nx,p,1\nx,q,2\ny,p,3\nx,p,4\n",
        _grp_agg(["a", "b"], [("v", "sum", "sv")])
        + _sort([("a", "ascending"), ("sv", "descending")]),
    ),
    # min/max preserve a temporal source kind.
    "agg_minmax_temporal": (
        _KD,
        b"k,d\na,2026-01-03\na,2026-01-01\nb,2026-02-01\n",
        _grp_agg(["k"], [("d", "min", "mn"), ("d", "max", "mx")]),
    ),
    # min/max preserve a string source kind (lexical).
    "agg_minmax_string": (
        _KS,
        b"k,s\na,cherry\na,apple\nb,banana\n",
        _grp_agg(["k"], [("s", "min", "mn"), ("s", "max", "mx")]),
    ),
    # 38-digit in-domain sum: exact through DuckDB's DECIMAL(38) (fifty * 10**36 = 5e37).
    "agg_large_in_domain_sum": (
        _NUM,
        b"v\n" + (b"1" + b"0" * 36 + b"\n") * 50,
        _grp_agg([], [("v", "sum", "s")]),
    ),
}


@pytest.mark.parametrize(
    ("manifest_json", "csv", "transform"), _SYNTHETIC.values(), ids=list(_SYNTHETIC)
)
def test_oracle_matches_eval_synthetic(
    manifest_json: bytes, csv: bytes, transform: list[dict[str, Any]]
) -> None:
    spec, manifest = _spec_manifest(manifest_json, csv, transform)
    expected = evaluate(spec, manifest, csv)
    actual = recompute(spec, manifest, csv)
    assert canon.serialize_table(actual) == canon.serialize_table(expected)
    assert canon.hash_table(actual) == canon.hash_table(expected)


def test_oracle_raises_loudly_on_over_domain_filter_literal() -> None:
    """A numeric filter literal beyond DuckDB's DECIMAL(38) domain: eval compares it symbolically
    (an empty result here), the oracle's exactness is DECIMAL(38)-scoped, so it raises LOUDLY
    rather than silently mis-binding -- the filter analogue of the aggregate-overflow guard."""
    csv = b"v\n1\n2\n"
    spec, manifest = _spec_manifest(_NUM, csv, _flt("v", "gt", "1e40"))
    evaluate(spec, manifest, csv)  # eval accepts an over-magnitude literal (no raise)
    with pytest.raises(VerificationError):
        recompute(spec, manifest, csv)
