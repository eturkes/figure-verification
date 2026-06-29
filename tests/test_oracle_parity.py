# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Dual-engine parity: verifier.eval's hand-rolled Decimal pipeline vs the DuckDB oracle must
produce the byte-identical canonical plotted table on every M1.3 good spec. This is the real
correctness oracle behind the M1.4d-e self-locked goldens — two independent engines agreeing.

eval runs FIRST (it is the trusted reference + the validation gate): a spec it rejects never
reaches the oracle, which recomputes only eval-validated specs (oracle module docstring)."""

import pathlib

import pytest

from oracle import recompute
from verifier import canon
from verifier.eval import evaluate
from verifier.ingest import load_manifest
from verifier.schema import decode_spec

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
