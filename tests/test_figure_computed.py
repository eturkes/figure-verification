# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q45 computed values (`.agent/archive/contracts/q45.md`): the variants' bits, the request's
sequence, the judge's two passes, the canonical reading, G10 and publication. The rule corpus
(`tests/figure_corpus/computed.toml`) carries the honest twins + wrong-value programs."""

import dataclasses
import math
import random
from pathlib import Path

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

from verifier.figure import computed, explain, reader
from verifier.figure.description import parse_description
from verifier.figure.explain import Explanation, summary
from verifier.figure.explain import explain as first_explain
from verifier.figure.judge import Passed, Sources, judge
from verifier.figure.keys import Key
from verifier.figure.parts import Mark
from verifier.figure.reasons import Blocked
from verifier.figure.request import MAX_RANGE, read_request
from verifier.figure.series import Point, Series
from verifier.figure.sources import Table, read_table
from verifier.pysrc.aggregate import kahan_sum
from verifier.pysrc.budget import WorkBudget, WorkBudgetExceededError

_DATA = Path(__file__).resolve().parents[1] / "data"
_SALES = (_DATA / "sales.csv").read_bytes()
_PD = "import pandas as pd\nimport matplotlib.pyplot as plt\n"
_PLT = "import matplotlib.pyplot as plt\n"
_READ = f"df = pd.read_csv({str(_DATA / 'sales.csv')!r})\n"


def _judge(program: str, sources: Sources) -> Passed | Blocked:
    described = parse_description(reader.run(program))
    assert described is not None
    return judge(described, sources)


def _sales(request: str) -> Sources:
    return Sources((("sales.csv", _SALES),), request)


def _vectors() -> list[list[float]]:
    rng = random.Random(45)  # noqa: S311 - a seeded sample, not a secret
    sizes = (1, 2, 7, 8, 9, 15, 16, 17, 127, 128, 129, 300, 1031, 8192, 8193, 20000)
    return [
        [round(rng.uniform(-1e6, 1e6), rng.choice((0, 2, 6))) for _ in range(size)]
        for size in sizes
        for _ in range(20)
    ]


# --- the variants' bits --------------------------------------------------------------------------


def test_pairwise_sum_is_numpy_and_pandas_sum() -> None:
    for values in _vectors():
        expected = float(np.asarray(values, dtype=np.float64).sum())
        assert computed.pairwise_sum(values) == expected
        assert float(pd.Series(values, dtype="float64").sum()) == expected


def test_the_other_totals_are_their_spellings() -> None:
    for values in _vectors():
        assert computed.neumaier_sum(values) == sum(values)  # CPython >= 3.12 over floats
        assert computed.sequential_sum(values) == sum(np.asarray(values, dtype=np.float64))
        frame = pd.DataFrame({"k": [0] * len(values), "v": values})
        assert kahan_sum(values) == float(frame.groupby("k")["v"].sum().iloc[0])


def test_the_neumaier_sum_keeps_cpython_s_final_guard() -> None:
    assert computed.neumaier_sum([1e308, 1e308, -1e308]) == sum([1e308, 1e308, -1e308])
    assert computed.neumaier_sum([0.1] * 10) == 1.0 != computed.sequential_sum([0.1] * 10)


def test_each_unary_variant_is_a_pandas_spelling() -> None:
    values = [0.1, 0.7, 2.2, 1e-3, 5.5]
    found: dict[str, set[tuple[float | None, ...]]] = {}
    for transform, result in computed.unary(values):
        found.setdefault(transform, set()).add(result)
    series = pd.Series(values)
    assert found["square"] == {tuple(series**2)}
    assert found["cumsum"] == {tuple(series.cumsum())}
    assert found["diff"] == {(None, *series.diff().iloc[1:])}
    totals = {series.sum(), sum(values), sum(np.asarray(values)), math.fsum(values)}
    assert {tuple(series / total) for total in totals} <= found["share"]
    assert tuple(series / series.sum() * 100) in found["percent"]
    assert tuple(100 * series / series.sum()) in found["percent"]
    assert tuple(series * (100 / series.sum())) in found["percent"]
    assert len(found["share"]) <= 5 and len(found["percent"]) <= 15


# Each total's witness: a series on which that total alone gives its value (searched, seed fixed).
_ALONE = {
    "pairwise": (
        computed.pairwise_sum,
        [731.48, -96.335, -620.196, -48.474, 586.0, -106.8, -818.659, 268.906],
    ),
    "sequential": (
        computed.sequential_sum,
        [929.516, 477.832, -685.0, 663.4, -880.9, 759.13, -939.83, -347.413],
    ),
    "neumaier": (computed.neumaier_sum, [-21.0, 0.001, 1e17, -0.003, -1e17, 10.5]),
    "kahan": (
        kahan_sum,
        [
            -609.4,
            280.58,
            -990.8,
            -85.34,
            -186.443,
            991.4,
            415.62,
            515.98,
            -421.9,
            126.3,
            -199.2,
            -227.0,
        ],
    ),
    "fsum": (math.fsum, [-21.0, 0.001, 1e17, -0.003, -1e17, 10.5]),
}


@pytest.mark.parametrize("total", sorted(_ALONE))
def test_each_total_is_a_share_variant(total: str) -> None:
    function, values = _ALONE[total]
    others = [f(values) for name, (f, _v) in _ALONE.items() if name != total]
    assert function(values) not in others
    shares = {found for transform, found in computed.unary(values) if transform == "share"}
    assert tuple(value / function(values) for value in values) in shares


def test_an_overflowing_or_infinite_total_is_no_total() -> None:
    assert computed.exact_sum([1e308, 1e308, -1e308]) == math.inf
    assert computed.exact_sum([math.inf, -math.inf]) == math.inf
    assert dict(computed.typed([1e308, 1e308]))["square"] == frozenset()


@pytest.mark.parametrize("form", ["100*v/t", "v/t*100", "v*(100/t)"])
def test_each_percent_order_is_a_variant(form: str) -> None:
    """A series on which the three operation orders differ (searched, seed fixed)."""
    values = [69.34, 37.585, 93.681]
    total = computed.pairwise_sum(values)
    orders = {
        "100*v/t": tuple((100.0 * v) / total for v in values),
        "v/t*100": tuple((v / total) * 100.0 for v in values),
        "v*(100/t)": tuple(v * (100.0 / total) for v in values),
    }
    assert len(set(orders.values())) == len(orders)
    percents = {found for transform, found in computed.unary(values) if transform == "percent"}
    assert orders[form] in percents


def test_an_integer_series_yields_one_variant_per_transform() -> None:
    assert [t for t, _values in computed.unary([3.0, 5.0, 2.0])] == list(computed.UNARY)


def test_undefined_values_are_no_candidates() -> None:
    zero = dict(computed.unary([2.0, -2.0]))
    assert "share" not in zero and "percent" not in zero
    assert dict(computed.unary([1e200]))["square"] == (None,)
    assert computed.binary("ratio", [1.0, 2.0], [0.0, 4.0]) == (None, 0.5)
    assert computed.binary("product", [1e200], [1e200]) == (None,)
    assert computed.binary("difference", [5.0], [2.0]) == (3.0,)
    assert computed.binary("total", [5.0], [2.0]) == (7.0,)


def test_typed_sets() -> None:
    sets = dict(computed.typed([1.0, 2.0, 3.0]))
    assert sets["square"] == frozenset({1.0, 4.0, 9.0})
    assert sets["cumsum"] == frozenset({1.0, 3.0, 6.0})
    assert sets["diff"] == frozenset({1.0})
    assert sets["share"] == frozenset({1 / 6, 2 / 6, 3 / 6})


# --- the request's sequence -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "sequence"),
    [
        ("Running total of 3, 5, 2 and 8", (3.0, 5.0, 2.0, 8.0)),
        ("from 5 to 2, then 9", (5.0, 4.0, 3.0, 2.0, 9.0)),
        ("1から3まで", (1.0, 2.0, 3.0)),
        ("1,200 units", (1200.0,)),
        ("1, 200 units", (1.0, 200.0)),
        ("7, 7, 7", (7.0, 7.0, 7.0)),
        ("For 2026, shares of 1, 2, 3", (2026.0, 1.0, 2.0, 3.0)),
        (f"1 to {MAX_RANGE + 1}", (1.0, float(MAX_RANGE + 1))),
        ("1-3", (1.0,)),
    ],
)
def test_the_sequence_is_the_typed_order(text: str, sequence: tuple[float, ...]) -> None:
    assert read_request(text).sequence == sequence


def test_no_request_has_no_sequence() -> None:
    assert read_request(None).sequence == ()


# --- two passes -----------------------------------------------------------------------------------


def test_a_figure_the_first_pass_passes_never_runs_the_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    passes: list[bool] = []

    def spy(*args: object, admitted: bool = False) -> object:
        passes.append(admitted)
        return first_explain(*args, admitted=admitted)  # type: ignore[arg-type]

    monkeypatch.setattr("verifier.figure.judge.explain", spy)
    program = _PD + _READ + "plt.bar(df.groupby('region')['revenue'].sum().index,"
    program += " df.groupby('region')['revenue'].sum().values)\n"
    assert isinstance(_judge(program, _sales("Total revenue by region")), Passed)
    assert passes == [False]
    computed_program = _PD + _READ + "plt.plot(df['orders'] ** 2)\n"
    assert isinstance(_judge(computed_program, _sales("orders squared")), Passed)
    assert passes == [False, False, True]


def test_the_second_pass_reason_shows_only_once_it_explains_every_value() -> None:
    made_up = _PLT + "plt.bar(['EU', 'US'], [50000, 60000])\n"
    assert _judge(made_up, _sales("Total revenue by region")) == Blocked("value_not_found", 2)
    mislabelled = _PD + _READ + "plt.plot(df['orders'] ** 2)\nplt.title('Revenue squared')\n"
    assert _judge(mislabelled, _sales("orders squared")) == Blocked("label_not_consistent", 5)


def test_an_exhausted_second_pass_leaves_the_first_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    program = _PD + _READ + "plt.plot(df['orders'] ** 2)\n"
    assert isinstance(_judge(program, _sales("orders squared")), Passed)
    calls: list[bool] = []

    def starved(*args: object, admitted: bool = False) -> object:
        calls.append(admitted)
        if admitted:
            monkeypatch.setattr(explain, "MAX_WORK", 10)
        return first_explain(*args, admitted=admitted)  # type: ignore[arg-type]

    monkeypatch.setattr("verifier.figure.judge.explain", starved)
    assert _judge(program, _sales("orders squared")) == Blocked("value_not_found", 4)
    assert calls == [False, True]


def test_one_ulp_off_blocks() -> None:
    program = _PD + _READ + "import math\nplt.plot([math.nextafter(v * v, math.inf) "
    program += "for v in df['orders']])\n"
    assert _judge(program, _sales("orders squared")) == Blocked("value_not_found", 5)


# --- the canonical reading ------------------------------------------------------------------------


def test_a_whole_computation_beats_one_drawn_in_part() -> None:
    program = _PD + _READ + "monthly = df.groupby('month')['revenue'].sum()\n"
    program += "plt.plot(monthly.index, monthly.cumsum())\n"
    verdict = _judge(program, _sales("Running total of revenue by month"))
    assert isinstance(verdict, Passed)
    chosen = verdict.choices[0].explanation
    assert chosen is not None
    assert (chosen.family, chosen.transform, len(chosen.pairs)) == ("sum", "cumsum", 3)


def test_the_vocabulary_beats_a_computation_of_the_same_columns() -> None:
    raw = Explanation("t", "raw", "k", "v", None, (("a", 1.0),), None)
    square = Explanation("t", "raw", "k", "v", None, (("a", 1.0),), None, transform="square")
    picked = explain._pick([square, raw], _context(), _series(1))
    assert picked is raw


def _context() -> explain.Context:
    return explain.Context((), read_request(None), None, (), strict=True)


def _series(points: int) -> Series:
    return Series(0, Mark("bar", (0,)), "keyed", None, (Point(Key(), 1.0),) * points, 1)


# --- G10 + keys -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("family", "transform", "reduction"),
    [
        ("sum", None, "sum"),
        ("raw", None, None),
        ("mean", "square", "mean"),
        ("sum", "cumsum", "sum"),
        ("raw", "share", None),
        ("sum", "ratio", "mean"),
        ("sum", "difference", "sum"),
        ("sum", "product", "sum"),
        ("sum", "total", "sum"),
        ("raw", "ratio", None),
        ("index", "total", None),
    ],
)
def test_the_summary_a_label_may_name(family: str, transform: str | None, reduction: str) -> None:
    explanation = Explanation("t", family, "k", "v", None, (), None, transform=transform)  # type: ignore[arg-type]
    assert summary(explanation) == reduction


def test_a_typed_computation_needs_typed_keys() -> None:
    program = _PLT + "plt.bar(['apples', 'pears'], [1, 4])\n"
    assert _judge(program, Sources(request="squares of 1 and 2")) == Blocked(
        "label_not_in_request", 2
    )
    named = _judge(program, Sources(request="squares of 1 and 2 for apples and pears"))
    assert isinstance(named, Passed)
    assert named.choices[0].typed == "square"


# --- channels bound through a computed main -------------------------------------------------------


def test_a_channel_binds_to_its_row_when_the_main_drops_one() -> None:
    program = _PD + _READ + "change = df['revenue'].diff().dropna()\n"
    program += "dots = plt.scatter(change.index, change, c=df['orders'].iloc[1:])\n"
    program += "plt.colorbar(dots)\n"
    verdict = _judge(program, _sales("change of revenue, coloured by orders"))
    assert isinstance(verdict, Passed)
    colours = verdict.choices[1].explanation
    assert colours is not None and colours.value == "orders"
    shuffled = program.replace("c=df['orders'].iloc[1:]", "c=df['orders'].iloc[:-1]")
    assert isinstance(_judge(shuffled, _sales("change of revenue, coloured by orders")), Blocked)


def test_a_channel_binds_to_its_group_when_the_main_drops_one() -> None:
    program = _PD + _READ + "sums = df.groupby('month')[['revenue', 'orders']].sum()\n"
    program += "change = sums['revenue'].diff().dropna()\n"
    program += "dots = plt.scatter(change.index, change, c=sums['orders'].iloc[1:])\n"
    program += "plt.colorbar(dots)\n"
    verdict = _judge(program, _sales("change of revenue by month, coloured by orders"))
    assert isinstance(verdict, Passed), verdict


# --- publication ----------------------------------------------------------------------------------


def test_each_computation_is_named_in_both_languages() -> None:
    cases = {
        _PD + _READ + "plt.plot(df['orders'] ** 2)\n": (
            "Line: the square of orders in row order from sales.csv.",
            "折れ線: sales.csv の orders 列 (行の順)の2乗。",
        ),
        _PD + _READ + "plt.plot(df['revenue'] - df['orders'])\n": (
            "Line: revenue minus orders in row order from sales.csv.",
            "折れ線: sales.csv の revenue 列から orders 列を引いた値 (行の順)。",
        ),
    }
    for program, (english, japanese) in cases.items():
        verdict = _judge(program, _sales("orders squared, revenue minus orders"))
        assert isinstance(verdict, Passed)
        assert (verdict.interpretation, verdict.interpretation_ja) == (english, japanese)
    typed = _judge(_PLT + "plt.plot([1, 4, 9])\n", Sources(request="squares of 1, 2, 3"))
    assert isinstance(typed, Passed)
    assert typed.interpretation == "Line: the square of the numbers typed in the request (1, 2, 3)."
    assert typed.interpretation_ja == "折れ線: 依頼文の数値 (1、2、3) の2乗。"
    long = _judge(
        _PLT + "plt.plot([n * n for n in range(1, 11)])\n", Sources(request="squares of 1 to 10")
    )
    assert isinstance(long, Passed)
    assert "(1, 2, 3, 4, 5, 6, 7, 8, …)" in long.interpretation


# --- the remaining predicates, each pinned against its own mutant ---------------------------------


def test_a_computation_keeps_pandas_pair_order() -> None:
    raw = Explanation("t", "raw", "k", "v", None, (("b", 1.0), ("a", 2.0)), None)
    assert explain._orders(raw) == [[0, 1], [1, 0]]
    assert explain._orders(dataclasses.replace(raw, transform="cumsum")) == [[0, 1]]


def test_same_columns_publish_the_first_computation_in_order() -> None:
    square = Explanation("t", "raw", "k", "v", None, (("a", 1.0),), None, transform="square")
    total = dataclasses.replace(square, transform="cumsum")
    assert explain._pick([total, square], _context(), _series(1)) is square


def test_a_group_computation_never_groups_by_its_own_operand() -> None:
    table = read_table("sales.csv", _SALES)
    assert isinstance(table, Table)
    found = list(explain.computations(table, None, WorkBudget(10**9)))
    grouped = [e for e in found if e.transform in computed.BINARY and e.family == "sum"]
    assert grouped
    assert all(e.key not in (e.value, e.other) for e in grouped)
    per_row = [e for e in found if e.transform in computed.BINARY and e.family == "raw"]
    assert any(e.key in (e.value, e.other) for e in per_row)


def test_a_stacked_typed_computation_reads_its_base() -> None:
    program = _PLT + "plt.fill_between([0, 1], [1, 4])\n"
    program += "plt.fill_between([0, 1], [1, 4], [10, 20])\n"
    verdict = _judge(program, Sources(request="squares of 1, 2, 3 and 4"))
    assert isinstance(verdict, Passed)
    assert [choice.typed for choice in verdict.choices] == [None, "square"]


def test_a_column_tie_is_never_resolved_by_a_typed_computation() -> None:
    content = (Path(__file__).parent / "figure_corpus" / "twins.csv").read_bytes()
    program = _PLT + "plt.bar(['x', 'y'], [3, 7])\n"
    sources = Sources((("twins.csv", content),), "running total of 3 and 4 for x and y by name")
    assert _judge(program, sources) == Blocked("column_not_requested", 2)


def test_the_second_column_of_a_computation_is_drawn() -> None:
    shop = (Path(__file__).parent / "figure_corpus" / "shop.csv").read_bytes()
    program = _PD + "df = pd.read_csv(" + repr(str(Path(__file__).parent / "figure_corpus"))
    program += " + '/shop.csv')\nplt.bar(df['product'], df['cost'] / df['price'])\n"
    named = _judge(program, Sources((("shop.csv", shop),), "cost divided by price by product"))
    assert isinstance(named, Passed)
    unnamed = _judge(program, Sources((("shop.csv", shop),), "cost by product"))
    assert unnamed == Blocked("column_not_named")


def test_a_second_pass_tie_never_hides_a_later_invented_series() -> None:
    """Pass 2 stops at a tie on the first series; the second series' values are invented, so
    pass 1's reason stands (kernel review: the tie used to surface)."""
    content = (Path(__file__).parent / "figure_corpus" / "twins.csv").read_bytes()
    program = _PLT + "plt.plot(['x', 'y'], [9, 49])\nplt.plot(['x', 'y'], [991, 1991])\n"
    sources = Sources((("twins.csv", content),), "squares by name")
    assert _judge(program, sources) == Blocked("value_not_found", 2)


def test_a_channel_computation_runs_over_the_whole_column() -> None:
    """A share's total is the whole column's, whatever rows the main series keeps (kernel review:
    the share was taken over the main's rows alone)."""
    program = _PD + _READ + "change = df['revenue'].diff().dropna()\n"
    program += "share = df['orders'] / df['orders'].sum()\n"
    program += "dots = plt.scatter(change.index, change, c=share.iloc[1:])\nplt.colorbar(dots)\n"
    request = "change of revenue, coloured by each row's share of orders"
    verdict = _judge(program, _sales(request))
    assert isinstance(verdict, Passed)
    colours = verdict.choices[1].explanation
    assert colours is not None and (colours.value, colours.transform) == ("orders", "share")
    subset = program.replace(
        "share = df['orders'] / df['orders'].sum()",
        "share = df['orders'] / df['orders'].iloc[1:].sum()",
    )
    assert _judge(subset, _sales(request)) == Blocked("value_not_found", 6)


def test_a_typed_scatter_s_channel_takes_a_typed_computation() -> None:
    program = _PLT + "dots = plt.scatter([0, 1, 2], [2, 3, 5], c=[4, 9, 25])\nplt.colorbar(dots)\n"
    verdict = _judge(program, Sources(request="2, 3 and 5, coloured by their squares"))
    assert isinstance(verdict, Passed)
    assert [choice.typed for choice in verdict.choices] == [None, "square"]


def test_a_computed_row_count_publishes_its_counts() -> None:
    program = _PD + _READ + "counts = df.groupby('region').size()\n"
    program += "plt.bar(counts.index, counts ** 2)\n"
    verdict = _judge(program, _sales("square of the rows per region"))
    assert isinstance(verdict, Passed)
    assert verdict.interpretation == (
        "Bars: the square of the number of rows per region from sales.csv;"
        " rows per group: EU 3, US 3."
    )


def test_a_typed_computation_charges_the_work_meter() -> None:
    series = Series(0, Mark("line", (0,)), "keyed", None, (Point(Key(number=0.0), 4.0),), 1)
    budget = WorkBudget(10)
    with pytest.raises(WorkBudgetExceededError):
        explain._typed(series, read_request(" ".join(str(n) for n in range(2, 40))), budget)
