# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Tests for verifier.eval — the deterministic recompute pipeline (M1.4d).

Three layers: (1) the M1.3 eval-bad specs each raise their specific semantic `check`;
(2) verified anchor goldens (g01/g04/g05) reproduced row-for-row against the sales CSV by
hand-verified explicit asserts (the M1.4f DuckDB oracle independently confirms these);
(3) inline constructed-table fixtures driving every remaining branch (distinctness, group_by
placement, whole-table + multi-measure aggregates, count/min/max/null semantics, filter
coercion, and the section 6 closure's null-greatest ordering). The full good-spec corpus and
the determinism anchor land in M1.4e.
"""

import itertools
import pathlib
from decimal import Decimal

import msgspec
import pytest

from verifier import canon
from verifier.errors import VerificationError
from verifier.eval import evaluate, mean_at_scale
from verifier.ingest import (
    Manifest,
    ManifestColumn,
    NumericColumnSpec,
    StringColumnSpec,
    TemporalColumnSpec,
    load_manifest,
)
from verifier.schema import VPlotSpec, decode_spec

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EXAMPLES = ROOT / "examples"
_PLACEHOLDER_HASH = "sha256:" + "0" * 64


def _evaluate_example(category: str, filename: str, dataset_stem: str) -> canon.Table:
    """Evaluate a committed corpus spec against its dataset (manifest + CSV resolved by stem)."""
    spec = decode_spec((EXAMPLES / category / filename).read_bytes())
    manifest = load_manifest((DATA / "schemas" / f"{dataset_stem}.json").read_bytes())
    return evaluate(spec, manifest, (DATA / f"{dataset_stem}.csv").read_bytes())


def _spec(transform: list[dict[str, object]]) -> VPlotSpec:
    """Decode an inline spec from its transform list (placeholder dataset/encoding; evaluate
    inspects neither). Built through decode_spec so the FilterValue = int | str parse boundary
    holds — a bool literal could not slip into a filter value."""
    raw: dict[str, object] = {
        "version": "vplot-0.1",
        "dataset": {"name": "t.csv", "hash": _PLACEHOLDER_HASH},
        "transform": transform,
        "mark": "bar",
        "encoding": {
            "x": {"field": "x", "type": "nominal"},
            "y": {"field": "y", "type": "quantitative"},
        },
    }
    return decode_spec(msgspec.json.encode(raw))


def _evaluate(
    transform: list[dict[str, object]], columns: tuple[ManifestColumn, ...], csv_bytes: bytes
) -> canon.Table:
    """Evaluate an inline spec against an inline (manifest columns, CSV bytes) fixture."""
    return evaluate(_spec(transform), Manifest(dataset="t.csv", columns=columns), csv_bytes)


# --- the M1.3 eval-bad specs each raise their semantic check ------------------
@pytest.mark.parametrize(
    ("filename", "check"),
    [
        ("b07_nonexistent_field.json", "schema.fields_exist"),
        ("b09_sum_on_string_field.json", "schema.field_types_match"),
        ("b10_filter_int_vs_string.json", "filter.value_type"),
        ("b14_group_by_without_aggregate.json", "transform.group_by_placement"),
        ("b15_aggregate_as_collides_group_key.json", "aggregate.output_unique"),
        ("b16_sort_fields_not_distinct.json", "sort.fields_distinct"),
    ],
)
def test_eval_bad_spec_raises_its_check(filename: str, check: str) -> None:
    spec = decode_spec((EXAMPLES / "bad_specs" / filename).read_bytes())
    manifest = load_manifest((DATA / "schemas" / "sales.json").read_bytes())
    csv_bytes = (DATA / "sales.csv").read_bytes()
    with pytest.raises(VerificationError) as excinfo:
        evaluate(spec, manifest, csv_bytes)
    assert excinfo.value.check == check


# --- verified anchor goldens (row-for-row, semantics-checked) -----------------
def test_g01_total_revenue_by_month() -> None:
    table = _evaluate_example("good_specs", "g01_total_revenue_by_month.json", "sales")
    assert table.columns == (
        canon.StringColumn(name="month"),
        canon.NumericColumn(name="total_revenue", scale=0),
    )
    assert table.rows == (
        ("2026-01", Decimal(21000)),
        ("2026-02", Decimal(26000)),
        ("2026-03", Decimal(27000)),
    )


def test_g04_revenue_vs_orders() -> None:
    # No sort op: the closure orders by every column ascending (revenue, then orders).
    table = _evaluate_example("good_specs", "g04_revenue_vs_orders.json", "sales")
    assert table.columns == (
        canon.NumericColumn(name="revenue", scale=0),
        canon.NumericColumn(name="orders", scale=0),
    )
    assert table.rows == (
        (Decimal(9000), Decimal(61)),
        (Decimal(11000), Decimal(70)),
        (Decimal(12000), Decimal(80)),
        (Decimal(13000), Decimal(88)),
        (Decimal(14000), Decimal(86)),
        (Decimal(15000), Decimal(93)),
    )


def test_g05_avg_revenue_by_region() -> None:
    # NA 40000/3 = 13333.33 -> 13333; EU 34000/3 = 11333.33 -> 11333 (HALF_EVEN at scale 0).
    table = _evaluate_example("good_specs", "g05_avg_revenue_by_region.json", "sales")
    assert table.columns == (
        canon.StringColumn(name="region"),
        canon.NumericColumn(name="avg_revenue", scale=0),
    )
    assert table.rows == (("EU", Decimal(11333)), ("NA", Decimal(13333)))


# --- distinctness + group_by placement ---------------------------------------
def test_select_fields_must_be_distinct() -> None:
    with pytest.raises(VerificationError) as excinfo:
        _evaluate(
            [{"op": "select", "fields": ["a", "a"]}],
            (NumericColumnSpec(name="a", scale=0),),
            b"a\n1\n",
        )
    assert excinfo.value.check == "select.fields_distinct"


def test_group_by_keys_must_be_distinct() -> None:
    with pytest.raises(VerificationError) as excinfo:
        _evaluate(
            [{"op": "group_by", "keys": ["a", "a"]}],
            (StringColumnSpec(name="a"),),
            b"a\nx\n",
        )
    assert excinfo.value.check == "group_by.keys_distinct"


def test_sort_field_must_survive_into_plotted_table() -> None:
    # group_by g -> sum v as total -> sort total -> select [g]: the trailing select projects the
    # sort key away, so the closure cannot order by it.
    with pytest.raises(VerificationError) as excinfo:
        _evaluate(
            [
                {"op": "group_by", "keys": ["g"]},
                {"op": "aggregate", "measures": [{"field": "v", "fn": "sum", "as": "total"}]},
                {"op": "sort", "by": [{"field": "total", "order": "ascending"}]},
                {"op": "select", "fields": ["g"]},
            ],
            (StringColumnSpec(name="g"), NumericColumnSpec(name="v", scale=0)),
            b"g,v\nx,1\ny,2\n",
        )
    assert excinfo.value.check == "sort.field_in_plotted_table"


def test_group_by_as_last_op_is_rejected() -> None:
    with pytest.raises(VerificationError) as excinfo:
        _evaluate(
            [{"op": "group_by", "keys": ["g"]}],
            (StringColumnSpec(name="g"),),
            b"g\nx\n",
        )
    assert excinfo.value.check == "transform.group_by_placement"


def test_consecutive_group_by_is_rejected() -> None:
    with pytest.raises(VerificationError) as excinfo:
        _evaluate(
            [{"op": "group_by", "keys": ["g"]}, {"op": "group_by", "keys": ["g"]}],
            (StringColumnSpec(name="g"),),
            b"g\nx\n",
        )
    assert excinfo.value.check == "transform.group_by_placement"


# --- aggregation -------------------------------------------------------------
def test_whole_table_aggregate_yields_one_row() -> None:
    table = _evaluate(
        [{"op": "aggregate", "measures": [{"field": "v", "fn": "sum", "as": "total"}]}],
        (NumericColumnSpec(name="v", scale=0),),
        b"v\n1\n2\n3\n",
    )
    assert table.columns == (canon.NumericColumn(name="total", scale=0),)
    assert table.rows == ((Decimal(6),),)


def test_multi_measure_reads_each_source_column() -> None:
    # Two measures over DIFFERENT source columns: a single-plan transcription bug would read the
    # last measure's source index for both, so sum_a must come from a (30), not b.
    table = _evaluate(
        [
            {"op": "group_by", "keys": ["g"]},
            {
                "op": "aggregate",
                "measures": [
                    {"field": "a", "fn": "sum", "as": "sum_a"},
                    {"field": "b", "fn": "mean", "as": "mean_b"},
                ],
            },
        ],
        (
            StringColumnSpec(name="g"),
            NumericColumnSpec(name="a", scale=0),
            NumericColumnSpec(name="b", scale=0),
        ),
        b"g,a,b\nx,10,2\nx,20,4\n",
    )
    assert table.columns == (
        canon.StringColumn(name="g"),
        canon.NumericColumn(name="sum_a", scale=0),
        canon.NumericColumn(name="mean_b", scale=0),
    )
    assert table.rows == (("x", Decimal(30), Decimal(3)),)


def test_pre_aggregate_sort_is_discarded() -> None:
    # A sort BEFORE the aggregate is reset by it; the output order is the closure re-sort (group
    # key ascending: a, b), not the pre-aggregate descending order (b, a).
    table = _evaluate(
        [
            {"op": "sort", "by": [{"field": "g", "order": "descending"}]},
            {"op": "group_by", "keys": ["g"]},
            {"op": "aggregate", "measures": [{"field": "v", "fn": "sum", "as": "total"}]},
        ],
        (StringColumnSpec(name="g"), NumericColumnSpec(name="v", scale=0)),
        b"g,v\na,1\nb,2\n",
    )
    assert table.rows == (("a", Decimal(1)), ("b", Decimal(2)))


def test_count_counts_non_null_and_empty_group_aggregates_to_null() -> None:
    # count = non-null count (0 here); sum/mean/min/max over zero non-nulls = null (SQL-matching).
    table = _evaluate(
        [
            {"op": "group_by", "keys": ["g"]},
            {
                "op": "aggregate",
                "measures": [
                    {"field": "v", "fn": "count", "as": "n"},
                    {"field": "v", "fn": "sum", "as": "s"},
                    {"field": "v", "fn": "mean", "as": "m"},
                    {"field": "v", "fn": "min", "as": "mn"},
                    {"field": "v", "fn": "max", "as": "mx"},
                ],
            },
        ],
        (StringColumnSpec(name="g"), NumericColumnSpec(name="v", scale=0)),
        b"g,v\nx,\nx,\n",  # both v cells empty -> None
    )
    assert table.rows == (("x", Decimal(0), None, None, None, None),)


def test_aggregate_functions_over_a_populated_group() -> None:
    # count > 0 (scale 0), numeric min/max (source scale 1).
    table = _evaluate(
        [
            {"op": "group_by", "keys": ["g"]},
            {
                "op": "aggregate",
                "measures": [
                    {"field": "v", "fn": "count", "as": "n"},
                    {"field": "v", "fn": "min", "as": "mn"},
                    {"field": "v", "fn": "max", "as": "mx"},
                ],
            },
        ],
        (StringColumnSpec(name="g"), NumericColumnSpec(name="v", scale=1)),
        b"g,v\nx,2.5\nx,1.0\nx,9.0\n",
    )
    assert table.columns == (
        canon.StringColumn(name="g"),
        canon.NumericColumn(name="n", scale=0),
        canon.NumericColumn(name="mn", scale=1),
        canon.NumericColumn(name="mx", scale=1),
    )
    assert table.rows == (("x", Decimal(3), Decimal("1.0"), Decimal("9.0")),)


def test_min_max_on_temporal_column() -> None:
    # Canonical ISO text sorts lexically == chronologically, so min/max are the bounds.
    table = _evaluate(
        [
            {"op": "group_by", "keys": ["g"]},
            {
                "op": "aggregate",
                "measures": [
                    {"field": "d", "fn": "min", "as": "first"},
                    {"field": "d", "fn": "max", "as": "last"},
                ],
            },
        ],
        (StringColumnSpec(name="g"), TemporalColumnSpec(name="d", granularity="date")),
        b"g,d\nx,2026-03-01\nx,2026-01-01\nx,2026-02-01\n",
    )
    assert table.columns == (
        canon.StringColumn(name="g"),
        canon.TemporalColumn(name="first", granularity="date"),
        canon.TemporalColumn(name="last", granularity="date"),
    )
    assert table.rows == (("x", "2026-01-01", "2026-03-01"),)


def test_min_max_on_string_column() -> None:
    table = _evaluate(
        [
            {"op": "group_by", "keys": ["g"]},
            {
                "op": "aggregate",
                "measures": [
                    {"field": "s", "fn": "min", "as": "lo"},
                    {"field": "s", "fn": "max", "as": "hi"},
                ],
            },
        ],
        (StringColumnSpec(name="g"), StringColumnSpec(name="s")),
        b"g,s\nx,banana\nx,apple\nx,cherry\n",
    )
    assert table.columns == (
        canon.StringColumn(name="g"),
        canon.StringColumn(name="lo"),
        canon.StringColumn(name="hi"),
    )
    assert table.rows == (("x", "apple", "cherry"),)


def test_null_group_key_forms_its_own_group() -> None:
    # A null in the group key is its own group (section 5), emitted not dropped, and sorts
    # greatest (last) under the ascending closure.
    table = _evaluate(
        [
            {"op": "group_by", "keys": ["g"]},
            {"op": "aggregate", "measures": [{"field": "v", "fn": "sum", "as": "total"}]},
        ],
        (StringColumnSpec(name="g"), NumericColumnSpec(name="v", scale=0)),
        b"g,v\nx,1\n,2\nx,3\n",  # second row has empty g -> None key
    )
    assert table.columns == (
        canon.StringColumn(name="g"),
        canon.NumericColumn(name="total", scale=0),
    )
    assert table.rows == (("x", Decimal(4)), (None, Decimal(2)))


# --- the section 6 closure under descending order ----------------------------
def test_descending_sort_places_null_first() -> None:
    # Null is greatest, so a descending sort (per-key reverse) puts it first.
    table = _evaluate(
        [{"op": "sort", "by": [{"field": "v", "order": "descending"}]}],
        (StringColumnSpec(name="k"), NumericColumnSpec(name="v", scale=0)),
        b"k,v\na,1\nb,\nc,3\n",  # b has null v
    )
    assert table.rows == (("b", None), ("c", Decimal(3)), ("a", Decimal(1)))


# --- filter value coercion (section 3) ---------------------------------------
def test_filter_int_literal_on_numeric_column() -> None:
    table = _evaluate(
        [{"op": "filter", "field": "v", "cmp": "ge", "value": 2}],
        (NumericColumnSpec(name="v", scale=0),),
        b"v\n1\n2\n3\n",
    )
    assert table.rows == ((Decimal(2),), (Decimal(3),))


def test_filter_string_literal_on_numeric_column() -> None:
    # A string numeric literal coerces via _decimal_at_scale (parse + precision, no magnitude).
    table = _evaluate(
        [{"op": "filter", "field": "v", "cmp": "lt", "value": "2.5"}],
        (NumericColumnSpec(name="v", scale=1),),
        b"v\n1.0\n2.5\n3.0\n",
    )
    assert table.rows == ((Decimal("1.0"),),)


def test_filter_string_literal_on_temporal_column() -> None:
    table = _evaluate(
        [{"op": "filter", "field": "d", "cmp": "ge", "value": "2026-02-01"}],
        (TemporalColumnSpec(name="d", granularity="date"),),
        b"d\n2026-01-01\n2026-02-01\n2026-03-01\n",
    )
    assert table.rows == (("2026-02-01",), ("2026-03-01",))


def test_filter_string_literal_on_string_column() -> None:
    table = _evaluate(
        [{"op": "filter", "field": "s", "cmp": "eq", "value": "keep"}],
        (StringColumnSpec(name="s"),),
        b"s\nkeep\ndrop\nkeep\n",
    )
    assert table.rows == (("keep",), ("keep",))


@pytest.mark.parametrize(
    ("columns", "value", "csv_bytes"),
    [
        (
            (NumericColumnSpec(name="v", scale=1),),
            "1.234",
            b"v\n1.0\n",
        ),  # str->numeric over-precise
        ((NumericColumnSpec(name="v", scale=1),), "abc", b"v\n1.0\n"),  # str->numeric unparsable
        ((TemporalColumnSpec(name="d", granularity="date"),), "2026-13-01", b"d\n2026-01-01\n"),
        (
            (TemporalColumnSpec(name="d", granularity="date"),),
            5,
            b"d\n2026-01-01\n",
        ),  # int->temporal
        ((StringColumnSpec(name="s"),), 5, b"s\nx\n"),  # int->string
    ],
)
def test_filter_value_coercion_failures(
    columns: tuple[ManifestColumn, ...], value: int | str, csv_bytes: bytes
) -> None:
    with pytest.raises(VerificationError) as excinfo:
        _evaluate(
            [{"op": "filter", "field": columns[0].name, "cmp": "eq", "value": value}],
            columns,
            csv_bytes,
        )
    assert excinfo.value.check == "filter.value_type"


def test_filter_drops_null_cells_including_ne() -> None:
    # A null cell fails every comparison, ne included (three-valued logic collapses to drop).
    table = _evaluate(
        [{"op": "filter", "field": "v", "cmp": "ne", "value": 99}],
        (StringColumnSpec(name="k"), NumericColumnSpec(name="v", scale=0)),
        b"k,v\na,1\nb,\nc,2\n",  # b has null v -> dropped despite ne 99
    )
    assert table.rows == (("a", Decimal(1)), ("c", Decimal(2)))


def test_filter_huge_exponent_literal_does_not_hang() -> None:
    # A huge-exponent numeric filter literal coerces instantly via the _decimal_at_scale exponent
    # guard (no ~1e18-digit quantize materialization), locking the M1.4c DoS fix on this path.
    table = _evaluate(
        [{"op": "filter", "field": "v", "cmp": "lt", "value": "1e999999999999999999"}],
        (NumericColumnSpec(name="v", scale=0),),
        b"v\n1\n2\n",
    )
    assert table.rows == ((Decimal(1),), (Decimal(2),))


# --- mean rounding (exact, HALF_EVEN, no float) -------------------------------
def test_mean_at_scale_rounds_half_to_even() -> None:
    # 0.005 at scale 2 -> 0.00 (HALF_EVEN: round to the even digit), via Fraction (no float).
    assert mean_at_scale(Decimal("0.01"), 2, 2) == Decimal("0.00")


def test_mean_at_scale_handles_negative_total() -> None:
    # A negative mean exercises the _scaled_int_to_decimal sign branch (the corpus is all positive).
    assert mean_at_scale(Decimal(-1), 2, 1) == Decimal("-0.5")


# --- exact aggregation over the DECIMAL(38) domain (codex-review M1.4d) -------
# 1e28 is a 29-digit summand, one digit past the ambient decimal context (prec 28); a
# context-bound `sum()` rounds mid-accumulation and so depends on source row order, whereas
# section 3 mandates exact Sigma. These drive the real CSV -> coerce -> aggregate -> hash path
# that mean_at_scale's direct tests above never reach -- the data-domain gap behind 100%
# branch coverage. `_CANCELS` sums to exactly 3; a context-bound sum collapses it toward 0.
_E28 = "10000000000000000000000000000"  # 1e28; adjusted 28 <= DECIMAL(38, 0) magnitude bound
_CANCELS = (_E28, "3", "-" + _E28)
_NUMS = (NumericColumnSpec(name="v", scale=0),)


def _csv(order: tuple[str, ...]) -> bytes:
    return ("v\n" + "\n".join(order) + "\n").encode()


def _agg(fn: str, out: str) -> list[dict[str, object]]:
    return [{"op": "aggregate", "measures": [{"field": "v", "fn": fn, "as": out}]}]


def test_sum_is_exact_beyond_context_precision() -> None:
    table = _evaluate(_agg("sum", "total"), _NUMS, _csv(_CANCELS))
    assert table.rows == ((Decimal(3),),)  # exact Sigma keeps the +3; a rounded sum gives 0


def test_mean_is_exact_beyond_context_precision() -> None:
    table = _evaluate(_agg("mean", "avg"), _NUMS, _csv(_CANCELS))
    assert table.rows == ((Decimal(1),),)  # 3 / 3 over an exact total; a rounded sum gives 0


def test_aggregation_hash_is_row_permutation_invariant() -> None:
    # The plotted-table hash must not depend on source row order: every permutation of a
    # cancelling group must yield the same exact sum and so the same canon.hash_table.
    hashes = {
        canon.hash_table(_evaluate(_agg("sum", "total"), _NUMS, _csv(order)))
        for order in itertools.permutations(_CANCELS)
    }
    assert len(hashes) == 1
