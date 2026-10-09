# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M19.4 values, columns + interpretation: branch witnesses beside the corpus (`m19u4.md`)."""

import json
from pathlib import Path
from typing import Any

import pytest

from verifier.figure import explain, reader
from verifier.figure.description import TAG, parse_description
from verifier.figure.judge import Passed, Sources, judge
from verifier.figure.reasons import Blocked
from verifier.figure.request import read_request

_DATA = Path(__file__).resolve().parents[1] / "data"
_PLT = "import matplotlib.pyplot as plt\n"
_PD = "import pandas as pd\nimport matplotlib.pyplot as plt\n"
_SALES = (_DATA / "sales.csv").read_bytes()
_WEATHER = (_DATA / "weather.csv").read_bytes()


_NO_SOURCES = Sources()


def _judge(program: str, sources: Sources = _NO_SOURCES) -> Passed | Blocked:
    described = parse_description(reader.run(program))
    assert described is not None
    return judge(described, sources)


def _sales(request: str | None = None, anchoring: str = "strict") -> Sources:
    return Sources((("sales.csv", _SALES),), request, anchoring)  # type: ignore[arg-type]


def test_v1_index_explanation_reads_row_positions() -> None:
    program = _PD + f"pd.read_csv({str(_DATA / 'sales.csv')!r})['revenue'].plot()\n"
    verdict = _judge(program, _sales("revenue"))
    assert isinstance(verdict, Passed)
    assert verdict.choices[0].explanation is not None
    assert verdict.choices[0].explanation.family == "index"


def test_v1_count_explanation() -> None:
    program = _PD + (
        f"pd.read_csv({str(_DATA / 'sales.csv')!r})['region'].value_counts().plot(kind='bar')\n"
    )
    verdict = _judge(program, _sales("rows per region"))
    assert isinstance(verdict, Passed)
    assert verdict.choices[0].explanation is not None
    assert verdict.choices[0].explanation.family == "count"


def test_v1_dates_match_iso_cells() -> None:
    program = _PD + (
        f"df = pd.read_csv({str(_DATA / 'weather.csv')!r}, parse_dates=['date'])\n"
        "df.groupby('date')['temp_c'].mean().plot()\n"
    )
    sources = Sources((("weather.csv", _WEATHER),), "mean temp_c by date")
    verdict = _judge(program, sources)
    assert isinstance(verdict, Passed), verdict


def test_v2_a_subset_publishes_n_of_m() -> None:
    program = _PD + (
        f"t = pd.read_csv({str(_DATA / 'sales.csv')!r}).groupby('region')['revenue'].sum()\n"
        "plt.bar(t.index[1:], t.values[1:])\n"
    )
    verdict = _judge(program, _sales("Total revenue by region"))
    assert isinstance(verdict, Passed)
    assert "1 of 2 drawn" in verdict.interpretation
    assert "2 件中 1 件を描画" in verdict.interpretation_ja


def test_v3_request_dates_and_positions() -> None:
    dated = _PLT + "import datetime as dt\nplt.plot([dt.date(2026, 1, 1)], [5])\n"
    assert isinstance(_judge(dated, Sources(request="5 on 2026-01-01")), Passed)
    assert _judge(dated, Sources(request="5 on another day")) == Blocked("label_not_in_request", 3)


def test_v3_ranges_and_numbers() -> None:
    assert read_request("1 through 3").numbers == {1.0, 2.0, 3.0}
    assert read_request("3〜1").numbers == {1.0, 2.0, 3.0}
    assert read_request("1-3").numbers == {1.0}
    assert read_request("0 to 20000").numbers == {0.0, 20000.0}
    assert read_request("1,200").numbers == {1.0, 200.0, 1200.0}
    assert read_request(None).numbers == frozenset()


def test_v6_integrity_alone_is_disclosed() -> None:
    verdict = _judge(_PLT + "plt.plot([3, 1, 2])\nplt.text(0, 1, 'note')\n")
    assert isinstance(verdict, Passed) and verdict.integrity_only
    assert verdict.interpretation.startswith("No data was attached")
    assert '"note"' in verdict.interpretation


def test_v6_an_unreadable_file_names_its_fault() -> None:
    sources = Sources((("bad.csv", b"a,b\n1\n"),), "chart")
    assert _judge(_PLT + "plt.plot([7, 8])\n", sources) == Blocked("csv_not_parsable", 2)


def test_v6_reference_values_from_a_column() -> None:
    program = _PLT + "plt.plot([1, 2], [9000, 15000])\nplt.axhline(15000)\nplt.axhline(0)\n"
    verdict = _judge(program, _sales())
    assert isinstance(verdict, Passed)  # the line = revenue rows 1-2 by row position
    assert [choice.reference for choice in verdict.choices[1:]] == [(("sales.csv", "revenue"),), ()]
    reference = _PD + (
        f"df = pd.read_csv({str(_DATA / 'sales.csv')!r})\n"
        "t = df.groupby('month')['revenue'].sum()\n"
        "plt.plot(t.index, t.values)\nplt.axhline(df['revenue'].mean())\n"
    )
    assert isinstance(_judge(reference, _sales("revenue by month")), Passed)


def test_work_budget_bounds_the_search(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(explain, "MAX_WORK", 1)
    program = _PLT + "plt.bar(['EU', 'US'], [1, 2])\n"
    assert _judge(program, _sales("chart")) == Blocked("work_budget_exceeded", 2)


def test_sources_profile_faults_leave_columns_as_text(monkeypatch: pytest.MonkeyPatch) -> None:
    from verifier.figure import sources  # noqa: PLC0415 - the module whose limits are moved
    from verifier.pysrc.limits import PysrcLimits  # noqa: PLC0415

    table = sources.read_table("t.csv", b"k,v,w\na,NA,1e5\nb,2,3\n")
    assert isinstance(table, sources.Table)
    assert [(c.name, c.numbers) for c in table.columns] == [
        ("k", None),
        ("v", None),
        ("w", None),
    ]
    assert table.columns[2].keys == ("1e5", "3")
    monkeypatch.setattr(sources, "DEFAULT_LIMITS", PysrcLimits(max_work=1))
    assert sources.read_table("t.csv", b"k,v\na,1\n") == sources.Unreadable(
        "t.csv", "work_budget_exceeded"
    )


def test_series_unlabelled_pie_takes_legend_names() -> None:
    program = _PLT + "w, _ = plt.pie([1, 2, 3])\nplt.legend(w, ['a', 'b', 'c'])\n"
    assert isinstance(_judge(program, Sources(request="a 1, b 2, c 3")), Passed)
    assert _judge(program, Sources(request="1, 2, 3")) == Blocked("label_not_in_request", 2)


def test_keys_a_point_off_every_label_has_no_key() -> None:
    """Off every label, an integral position is a slot; any other position shows no key."""
    program = _PLT + "plt.bar([0.6], [1])\nplt.xticks([0], ['a'])\n"
    assert _judge(program, Sources(request="a 1")) == Blocked("label_not_in_request", 2)
    ticks = "plt.xticks([0, 1], ['a', 'b'])\n"
    between = _PLT + "plt.bar([0, 1, 2.5], [1, 2, 3], width=0.4)\n" + ticks
    assert _judge(between, Sources(request="a 1, b 2, 3")) == Blocked("label_not_in_request", 2)
    slot = _PLT + "plt.bar([0, 1, 3], [1, 2, 3], width=0.4)\n" + ticks
    assert isinstance(_judge(slot, Sources(request="a 1, b 2, 3")), Passed)


def test_keys_labels_within_half_the_tick_gap() -> None:
    program = _PLT + "plt.bar([0.6, 1.6], [1, 2])\nplt.xticks([0, 1, 2], ['a', 'b', 'c'])\n"
    assert isinstance(_judge(program, Sources(request="b 1, c 2")), Passed)


def test_g10_reads_figure_legends() -> None:
    program = _PLT + (
        "plt.bar(['EU', 'US'], [34000, 40000], label='total orders')\nplt.gcf().legend()\n"
    )
    assert _judge(program, _sales("Total revenue by region")) == Blocked("label_not_consistent", 3)
    honest = program.replace("total orders", "total revenue")
    assert isinstance(_judge(honest, _sales("Total revenue by region")), Passed)


def test_columns_a_file_that_drew_nothing_anchors_nothing() -> None:
    program = _PLT + "plt.bar(['a'], [5])\n"
    assert isinstance(_judge(program, _sales("a 5, nothing from revenue")), Passed)


def test_columns_an_ambiguous_request_word_is_a_tie() -> None:
    content = b"name,revenue,revenues\nx,1,2\ny,3,4\n"
    program = _PD + "plt.bar(['x', 'y'], [1, 3])\n"
    sources = Sources((("t.csv", content),), "revenuex by name")
    assert _judge(program, sources) == Blocked("column_not_requested")


def test_interpretation_counts_request_values_beside_a_file() -> None:
    program = _PLT + "plt.bar(['EU', 'US', 'goal'], [34000, 40000, 50000])\n"
    verdict = _judge(program, _sales("total revenue by region and a goal of 50000"))
    assert isinstance(verdict, Passed)
    assert "1 value(s) typed in the request" in verdict.interpretation
    assert "依頼文の数値 1 件" in verdict.interpretation_ja


def test_explain_edge_keys_and_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Calendar-invalid and non-finite cell text stays text; a positional slot binds by order;
    a reference no source holds blocks; a reduction past the group bound is no explanation."""
    slotted = b"k,v\n" + b"".join(f"k{i:02d},{i}\n".encode() for i in range(12))
    slots = _PD + "pd.Series(range(12), index=[f'k{i:02d}' for i in range(12)]).plot()\n"
    assert isinstance(_judge(slots, Sources((("t.csv", slotted),), "v by k")), Passed)
    texts = _PLT + "plt.bar(['2026-13', 'inf'], [1, 2])\n"
    keyed = Sources((("t.csv", b"k,v\n2026-13,1\ninf,2\n"),), "v by k")
    assert isinstance(_judge(texts, keyed), Passed)
    stray = _PLT + "plt.plot([1, 2], [9000, 15000])\nplt.axhline(12345)\n"
    assert _judge(stray, _sales()) == Blocked("value_not_found", 3)
    monkeypatch.setattr(explain, "MAX_GROUPS", 1)
    grouped = _PD + (
        f"t = pd.read_csv({str(_DATA / 'sales.csv')!r}).groupby('region')['revenue'].sum()\n"
        "plt.bar(t.index, t.values)\n"
    )
    assert _judge(grouped, _sales("revenue by region")) == Blocked("value_not_found", 4)


def test_spans_explain_both_edges_in_either_shape() -> None:
    """3.9 draws `axhspan` as a Rectangle (host), 3.8 as a Polygon (sandbox): both edges count."""
    program = _PLT + "plt.plot([1, 2], [1, 4])\nplt.axhspan(2, 3)\n"
    assert isinstance(_judge(program, Sources(request="1 to 4, band 2 to 3")), Passed)
    raw = json.loads(reader.run(program).splitlines()[0][len(TAG) :])
    span: dict[str, Any] = raw["figures"][0]["axes"][0]["artists"][1]
    span["cls"] = "Polygon"
    span["geometry"] = {
        "kind": "polygon",
        "xy": [[0.0, 2.0], [0.0, 3.0], [1.0, 3.0], [1.0, 2.0], [0.0, 2.0]],
        "color": span["geometry"]["color"],
        "edge": span["geometry"]["edge"],
        "linewidth": span["geometry"]["linewidth"],
    }
    described = parse_description(TAG + json.dumps(raw))
    assert described is not None
    assert isinstance(judge(described, Sources(request="1 to 4, band 2 to 3")), Passed)
    assert judge(described, Sources(request="1, 4, band 2")) == Blocked("value_not_found", 3)
    assert _judge(program, Sources(request="1, 4, band 2")) == Blocked("value_not_found", 3)


def test_keyless_series_need_values_alone() -> None:
    """An unnamed pie and a histogram show no key, so the request supplies their values alone."""
    pie = _PLT + "plt.pie([1, 2, 3])\n"
    assert isinstance(_judge(pie, Sources(request="1, 2, 3")), Passed)
    assert _judge(pie, Sources(request="1, 2")) == Blocked("value_not_found", 2)
    hist = _PLT + "plt.hist([1, 2, 2, 3], bins=[0, 2, 4])\n"
    assert isinstance(_judge(hist, Sources(request="1, 2, 2, 3 in bins 0, 2, 4")), Passed)
    assert _judge(hist, Sources(request="1, 2")) == Blocked("value_not_found", 2)


def test_numeric_text_keys_and_keyless_points_against_a_file() -> None:
    """A text cell that reads as a number matches a numeric key; a point no label names
    matches no cell."""
    table = Sources((("t.csv", b"k,v\n1,5\nx,6\n"),), "v by k")
    numeric = _PLT + "plt.plot([1, 2], [5, 5])\nplt.bar(['x'], [6])\n"
    assert isinstance(_judge(_PLT + "plt.bar(['1', 'x'], [5, 6])\n", table), Passed)
    assert _judge(numeric, table) == Blocked("value_not_found", 2)
    keyless = _PLT + "plt.bar([0.6], [5])\nplt.xticks([0], ['1'])\n"
    assert _judge(keyless, table) == Blocked("value_not_found", 2)


def test_a_tie_with_no_request_is_unbroken() -> None:
    content = b"name,first,second\nx,1,1\ny,2,2\n"
    program = _PLT + "plt.bar(['x', 'y'], [1, 2])\n"
    assert _judge(program, Sources((("t.csv", content),))) == Blocked("column_not_requested", 2)


_DF = f"df = pd.read_csv({str(_DATA / 'sales.csv')!r})\n"
_BY_REGION = "t = df.groupby('region')['revenue'].sum()\n"
_GROUPS_EN = "rows per group: EU 3, US 3"
_GROUPS_JA = "各グループの行数: EU 3 行、US 3 行"
_SUM_EN = "the sum of revenue per region from sales.csv"
_SUM_JA = "sales.csv の region 列ごとの revenue 列の合計"


@pytest.mark.parametrize(
    ("program", "sources", "english", "japanese"),
    [
        pytest.param(
            _DF + "plt.scatter(df['orders'], df['revenue'])\n",
            _sales("Revenue against orders"),
            "Points: revenue by orders from sales.csv.",
            "散布点: sales.csv の revenue 列 (orders 列ごと)。",
            id="raw",
        ),
        pytest.param(
            _DF + _BY_REGION + "plt.bar(t.index, t.values)\n",
            _sales("Total revenue by region"),
            f"Bars: {_SUM_EN}; {_GROUPS_EN}.",
            f"棒: {_SUM_JA}。{_GROUPS_JA}。",
            id="group",
        ),
        pytest.param(
            _DF + "df['region'].value_counts().plot(kind='bar')\n",
            _sales("Rows per region"),
            "Bars: the number of rows per region from sales.csv.",
            "棒: sales.csv の region 列ごとの行数。",
            id="count",
        ),
        pytest.param(
            _DF + _BY_REGION + "plt.bar(t.index[1:], t.values[1:])\n",
            _sales("Total revenue for the US region"),
            f"Bars: {_SUM_EN}; 1 of 2 drawn; {_GROUPS_EN}.",
            f"棒: {_SUM_JA}。2 件中 1 件を描画。{_GROUPS_JA}。",
            id="subset",
        ),
        pytest.param(
            f"df = pd.read_csv({str(_DATA / 'weather.csv')!r}, parse_dates=['date'])\n"
            "london = df[df['city'] == 'London']\n"
            "plt.plot(london['date'], london['temp_c'], label='London')\nplt.legend()\n",
            Sources((("weather.csv", _WEATHER),), "London temp_c by date"),
            'Line "London": temp_c by date from weather.csv, rows where city is London.',
            '折れ線 "London": weather.csv の temp_c 列 (date 列ごと) (city 列が London の行)。',
            id="filter",
        ),
        pytest.param(
            "plt.plot([3, 1, 4], label='typed')\nplt.legend()\n",
            Sources(request="Plot 3, 1, 4"),
            'Line "typed": numbers typed in the request.',
            '折れ線 "typed": 依頼文に入力された数値。',
            id="request",
        ),
        pytest.param(
            "plt.bar(['EU', 'US', 'goal'], [34000, 40000, 50000])\n",
            _sales("total revenue by region and a goal of 50000"),
            f"Bars: {_SUM_EN}; {_GROUPS_EN}; 1 value(s) typed in the request.",
            f"棒: {_SUM_JA}。{_GROUPS_JA}。依頼文の数値 1 件。",
            id="mixed",
        ),
        pytest.param(
            _DF + "t = df.groupby('month')['revenue'].sum()\nplt.plot(t.index, t.values)\n"
            "plt.axhline(df['revenue'].mean())\nplt.axhline(25000)\n",
            _sales("revenue by month, target 25000"),
            "Line: the sum of revenue per month from sales.csv; rows per group: 2026-01 2, "
            "2026-02 2, 2026-03 2.\nReference mark: a value of revenue from sales.csv.\n"
            "Reference mark: zero or a number typed in the request.",
            "折れ線: sales.csv の month 列ごとの revenue 列の合計。各グループの行数: 2026-01 2 行、"
            "2026-02 2 行、2026-03 2 行。\n基準線: sales.csv の revenue 列の値。\n"
            "基準線: ゼロまたは依頼文の数値。",
            id="reference",
        ),
        pytest.param(
            "plt.plot([3, 1, 2])\nplt.title('Trend')\nplt.text(0, 1, 'note')\n",
            Sources(),
            "No data was attached or typed in the request, so the values were not compared with "
            "data. The chart passed the integrity checks alone.\n"
            'Text on the chart was not checked: "note".',
            "データが添付されておらず、依頼文にも数値がないため、値はデータと照合していません。"
            "グラフは完全性のチェックだけに合格しました。\n"
            'グラフ上の文字は確認していません: "note"。',
            id="integrity-only-listed-text",
        ),
    ],
)
def test_v9_interpretation_sentences(
    program: str, sources: Sources, english: str, japanese: str
) -> None:
    verdict = _judge(_PD + program, sources)
    assert isinstance(verdict, Passed)
    assert (verdict.interpretation, verdict.interpretation_ja) == (english, japanese)


def test_stacked_bands_read_their_own_values() -> None:
    """An upper band's value = its far edge minus the band it sits on (fl(base + c) = top)."""
    program = _PD + (
        f"df = pd.read_csv({str(_DATA / 'sales.csv')!r})\n"
        "df.pivot(index='month', columns='region', values='revenue').plot.area()\n"
    )
    verdict = _judge(program, _sales("Revenue by month for each region, stacked"))
    assert isinstance(verdict, Passed)
    assert [choice.explanation.where for choice in verdict.choices if choice.explanation] == [
        ("region", "EU"),
        ("region", "US"),
    ]


def test_matching_is_injective() -> None:
    """A row backs one point: a CSV row drawn twice is a value the file does not hold twice."""
    once = Sources((("t.csv", b"k,v\na,1\nb,2\n"),), "v by k")
    assert isinstance(_judge(_PLT + "plt.scatter(['a', 'b'], [1, 2])\n", once), Passed)
    twice = _PLT + "plt.scatter(['a', 'a', 'b'], [1, 1, 2])\n"
    assert _judge(twice, once) == Blocked("value_not_found", 2)
    hist = _PLT + "plt.hist([1, 1, 2], bins=[0, 1.5, 3])\n"
    assert _judge(hist, once) == Blocked("value_not_found", 2)


def test_a_scatter_may_repeat_a_category() -> None:
    program = _PLT + "plt.scatter(['a', 'a'], [1, 2])\n"
    assert isinstance(_judge(program, Sources(request="a: 1 and 2")), Passed)


def test_a_tie_named_on_both_sides_stays_a_tie() -> None:
    content = (Path(__file__).parent / "figure_corpus" / "twins.csv").read_bytes()
    program = _PLT + "plt.bar(['x', 'y'], [1, 2])\n"
    sources = Sources((("twins.csv", content),), "first and second by name")
    assert _judge(program, sources) == Blocked("column_not_requested", 2)


def test_same_columns_prefer_the_raw_reading() -> None:
    """Group minima that are each one row's cell publish as those rows (raw), not as `min`."""
    program = _PD + (
        f"lows = pd.read_csv({str(_DATA / 'sales.csv')!r}).groupby('month')['orders'].min()\n"
        "plt.bar(lows.index, lows.values)\n"
    )
    verdict = _judge(program, _sales("Lowest orders by month"))
    assert isinstance(verdict, Passed)
    assert verdict.choices[0].explanation is not None
    assert verdict.choices[0].explanation.family == "raw"


def test_a_reference_two_columns_hold_names_no_column() -> None:
    content = (Path(__file__).parent / "figure_corpus" / "twins.csv").read_bytes()
    program = _PLT + "plt.bar(['x', 'y'], [1, 2])\nplt.axhline(2)\n"
    verdict = _judge(program, Sources((("twins.csv", content),), "first by name, line at 2"))
    assert isinstance(verdict, Passed)
    assert (verdict.choices[1].reference, verdict.choices[1].shared) == ((), 0)
    held = _judge(program, Sources((("twins.csv", content),), "first by name"))
    assert isinstance(held, Passed)
    assert (held.choices[1].reference, held.choices[1].shared) == ((), 1)


def test_an_unreadable_file_leaves_other_reasons_alone() -> None:
    sources = Sources((("bad.csv", b"a,b\n1\n"),), "Plot 3, 5, 9")
    program = _PLT + "plt.bar(['apples', 'pears', 'plums'], [3, 5, 9])\n"
    assert _judge(program, sources) == Blocked("label_not_in_request", 2)


def test_slots_bind_a_pivot_sorted_table() -> None:
    """A raw table in another row order binds its slots in key-sorted order (a pivot sorts)."""
    rows = b"".join(f"k{i:02d},{i}\n".encode() for i in reversed(range(12)))
    program = _PD + "pd.Series(range(12), index=[f'k{i:02d}' for i in range(12)]).plot()\n"
    assert isinstance(_judge(program, Sources((("t.csv", b"k,v\n" + rows),), "v by k")), Passed)


def test_strict_anchoring_needs_a_named_column_first() -> None:
    program = _PLT + "plt.bar(['EU', 'US'], [34000, 40000])\n"
    assert isinstance(_judge(program, _sales("Make a chart")), Passed)
    assert _judge(program, _sales("Chart by region")) == Blocked("column_not_named")


def test_aliases_reach_anchoring() -> None:
    program = _PLT + "plt.bar(['EU', 'US'], [34000, 40000])\n"
    aliased = Sources(
        (("sales.csv", _SALES),), "sales by region", "strict", (("revenue", "sales"),)
    )
    assert isinstance(_judge(program, aliased), Passed)
    assert _judge(program, _sales("sales by region")) == Blocked("column_not_named")


def test_request_ranges_need_their_words() -> None:
    assert read_request("1から3").numbers == {1.0, 3.0}
    assert read_request("1から3まで").numbers == {1.0, 2.0, 3.0}
    assert read_request("Q1 sales").numbers == frozenset()
    assert read_request("1 to 20000").numbers == {1.0, 20000.0}


def test_v1_raw_reads_repeated_keys() -> None:
    """Cells under a repeated key are raw rows, which no reduction of one group reproduces."""
    program = _PD + _DF + "plt.scatter(df['region'], df['revenue'])\n"
    verdict = _judge(program, _sales("Revenue by region"))
    assert isinstance(verdict, Passed)
    assert verdict.choices[0].explanation is not None
    assert verdict.choices[0].explanation.family == "raw"


def test_v3_numeric_keys_must_be_typed() -> None:
    program = _PLT + "plt.plot([5, 7], [1, 2])\n"
    assert _judge(program, Sources(request="Plot 1 and 2")) == Blocked("label_not_in_request", 2)
    assert isinstance(_judge(program, Sources(request="Plot 1 at 5 and 2 at 7")), Passed)


def test_v3_slots_bind_key_sorted_rows() -> None:
    """Unlabelled integral positions bind to the explanation's key order, pandas' or sorted."""
    program = _PLT + "plt.plot(range(4), [0, 1, 2, 3])\nplt.xticks([0, 1], ['k0', 'k1'])\n"
    reversed_rows = Sources((("t.csv", b"k,v\nk3,3\nk2,2\nk1,1\nk0,0\n"),), "v by k")
    verdict = _judge(program, reversed_rows)
    assert isinstance(verdict, Passed)  # a group of one sorts too; the raw reading publishes
    assert verdict.choices[0].explanation is not None
    assert verdict.choices[0].explanation.family == "raw"


def test_channels_show_only_where_displayed() -> None:
    """A colour array no colorbar or key shows is no drawn value; a constant size a size key
    shows applies to every point."""
    unshown = _PLT + "plt.scatter([1, 2], [3, 4], c=[5, 5])\n"
    assert isinstance(_judge(unshown, Sources(request="Points 1 3 and 2 4")), Passed)
    constant = _PLT + (
        "dots = plt.scatter([1, 2], [3, 4], s=50)\nplt.legend(*dots.legend_elements('sizes'))\n"
    )
    assert isinstance(_judge(constant, Sources(request="Points 1 3 and 2 4, size 50")), Passed)
    assert _judge(constant, Sources(request="Points 1 3 and 2 4")) == Blocked("value_not_found", 2)


def test_channels_publish_their_own_sentence() -> None:
    program = (
        _PD
        + _DF
        + ("dots = plt.scatter(df['orders'], df['revenue'], c=df['orders'])\nplt.colorbar(dots)\n")
    )
    verdict = _judge(program, _sales("Revenue against orders, coloured by orders"))
    assert isinstance(verdict, Passed)
    assert verdict.interpretation == (
        "Points: revenue by orders from sales.csv.\nPoint colours: orders from sales.csv."
    )
    assert verdict.interpretation_ja == (
        "散布点: sales.csv の revenue 列 (orders 列ごと)。\n点の色: sales.csv の orders 列。"
    )


def test_g10_figure_labels_read_every_panel() -> None:
    """A suptitle or figure legend over sum and mean panels names both summaries honestly."""
    program = (
        _PD
        + _DF
        + (
            "fig, (left, right) = plt.subplots(1, 2)\n"
            "left.bar(['EU', 'US'], df.groupby('region')['revenue'].sum().values,"
            " label='Total revenue')\n"
            "right.bar(['EU', 'US'], df.groupby('region')['revenue'].mean().values,"
            " label='Average revenue')\n"
            "fig.legend()\nfig.suptitle('Total and average revenue by region')\n"
        )
    )
    sources = _sales("Total and average revenue by region")
    assert isinstance(_judge(program, sources), Passed)
    panel = program.replace("label='Average revenue'", "label='Average revenue'").replace(
        "fig.legend()\n", "right.legend(['Total revenue'])\n"
    )
    assert _judge(panel, sources) == Blocked("label_not_consistent", 7)


def test_r6_a_filtered_series_may_key_by_its_label() -> None:
    program = _PLT + "plt.bar(['US'], [40000], label='US')\nplt.legend()\n"
    verdict = _judge(program, _sales("Total revenue for the US region"))
    assert isinstance(verdict, Passed)
    assert verdict.choices[0].explanation is not None
    assert verdict.choices[0].explanation.where == ("region", "US")


def test_r6_two_filter_columns_with_one_reading_are_no_tie() -> None:
    """The filter column draws nothing: two filters over the same drawn columns are one reading,
    published by the first filter column; a key either column could supply is an R7 tie."""
    content = b"region,zone,month,revenue\nUS,US,2026-01,5\nEU,EU,2026-01,7\n"
    program = _PLT + "plt.bar(['2026-01'], [5], label='US')\nplt.legend()\n"
    verdict = _judge(program, Sources((("t.csv", content),), "revenue by month for US"))
    assert isinstance(verdict, Passed)
    assert verdict.choices[0].explanation is not None
    assert verdict.choices[0].explanation.where == ("region", "US")
    keyed = _PLT + "plt.bar(['US'], [5], label='US')\nplt.legend()\n"
    tied = _judge(keyed, Sources((("t.csv", content),), "revenue for US"))
    assert tied == Blocked("column_not_requested", 2)
    named = _judge(keyed, Sources((("t.csv", content),), "revenue for US by zone"))
    assert isinstance(named, Passed)


def test_slots_bind_before_keyed_points() -> None:
    """A text point must not take the row a slot needs when another row of its key is free."""
    content = b"k,v\na,1\nb,2\na,1\n"
    program = _PLT + "plt.scatter([0, 1, 2], [1, 2, 1])\nplt.xticks([0, 1], ['a', 'b'])\n"
    assert isinstance(_judge(program, Sources((("t.csv", content),), "v by k")), Passed)


def test_span_edges_from_two_columns_draw_both() -> None:
    content = b"name,lower,upper\nx,10,90\n"
    program = _PLT + "plt.bar(['x'], [10])\nplt.axhspan(10, 90)\n"
    sources = Sources((("t.csv", content),), "lower by name")
    assert _judge(program, sources) == Blocked("column_not_named")
    verdict = _judge(program, Sources((("t.csv", content),), "lower by name, band to upper"))
    assert isinstance(verdict, Passed)
    assert verdict.choices[1].reference == (("t.csv", "lower"), ("t.csv", "upper"))
    assert verdict.interpretation.endswith("Reference mark: a value of lower and upper from t.csv.")


def test_a_shared_reference_value_says_so() -> None:
    content = (Path(__file__).parent / "figure_corpus" / "twins.csv").read_bytes()
    program = _PLT + "plt.bar(['x', 'y'], [1, 2])\nplt.axhline(2)\nplt.axhline(0)\n"
    verdict = _judge(program, Sources((("twins.csv", content),), "first by name"))
    assert isinstance(verdict, Passed)
    assert verdict.interpretation.split("\n")[1:] == [
        "Reference mark: 1 value(s) held by several columns.",
        "Reference mark: zero or a number typed in the request.",
    ]
    assert verdict.interpretation_ja.split("\n")[1:] == [
        "基準線: 複数の列にある値 1 件。",
        "基準線: ゼロまたは依頼文の数値。",
    ]


def test_pie_keys_are_the_drawn_labels() -> None:
    """A wedge label changed after the call is the key the chart shows; a removed, hidden or
    blank label shows none, and drawn labels count as checked text once values are compared."""
    base = _PLT + "w, t = plt.pie([2, 3], labels=['a', 'b'])\n"
    typed = Sources(request="a 2 b 3")
    honest = _judge(base, typed)
    assert isinstance(honest, Passed)
    assert "not checked" not in honest.interpretation
    relabelled = base + "t[0].set_text('invented')\n"
    assert _judge(relabelled, typed) == Blocked("label_not_in_request", 2)
    for hidden in (
        "t[0].remove()\nt[1].remove()\n",
        "t[0].set_visible(False)\nt[1].set_text(' ')\n",
    ):
        assert isinstance(_judge(base + hidden, Sources(request="2 3")), Passed)
    listed = _judge(base, Sources())
    assert isinstance(listed, Passed)
    assert listed.interpretation.endswith('Text on the chart was not checked: "a", "b".')


@pytest.mark.parametrize(
    "encode",
    [
        "dots = plt.scatter(df['key'], df['amount'], c={c})\nplt.colorbar(dots)\n",
        "dots = plt.scatter(df['key'], df['amount'], s={c})\n"
        "plt.legend(*dots.legend_elements('sizes'))\n",
    ],
    ids=["colour", "size"],
)
def test_r8_a_channel_stays_with_its_own_point(encode: str) -> None:
    """Under a repeated key, a colour or size swapped between two points is a different chart."""
    content = b"key,amount,encoded\n10,101,6\n10,102,7\n20,103,8\n"
    sources = Sources((("t.csv", content),), "amount by key, encoded")
    csv = "key,amount,encoded\\n10,101,6\\n10,102,7\\n20,103,8\\n"
    read = f"import io\ndf = pd.read_csv(io.StringIO('{csv}'))\n"
    honest = _PD + read + encode.format(c="df['encoded']")
    assert isinstance(_judge(honest, sources), Passed)
    swapped = _PD + read + encode.format(c="[7, 6, 8]")
    assert _judge(swapped, sources) == Blocked("value_not_found", 5)


def test_r8_grouped_channels_bind_to_their_group() -> None:
    program = (
        _PD
        + _DF
        + (
            "t = df.groupby('month').agg({'revenue': 'sum', 'orders': 'mean'})\n"
            "dots = plt.scatter(t.index, t['revenue'], c=t['orders'])\nplt.colorbar(dots)\n"
        )
    )
    verdict = _judge(program, _sales("Total revenue by month, coloured by mean orders"))
    assert isinstance(verdict, Passed)
    assert verdict.choices[1].explanation is not None
    assert verdict.choices[1].explanation.family == "mean"
    typed = _PLT + "dots = plt.scatter([1, 2], [3, 4], c=[5, 6])\nplt.colorbar(dots)\n"
    assert isinstance(_judge(typed, Sources(request="points 1 3 and 2 4, colours 5 and 6")), Passed)
    assert _judge(typed, Sources(request="points 1 3 and 2 4")) == Blocked("value_not_found", 2)


def test_attribution_reads_only_unbacked_points() -> None:
    """A file already backs Alpha = 5: the missing value is Beta's 6, not Alpha's label."""
    content = b"key,value\nAlpha,5\nGamma,9\n"
    program = _PLT + "plt.bar(['Alpha', 'Beta'], [5, 6])\n"
    sources = Sources((("t.csv", content),), "value by key and Beta target 5")
    assert _judge(program, sources) == Blocked("value_not_found", 2)


def test_v1_a_column_against_itself() -> None:
    program = _PD + _DF + "plt.scatter(df['orders'], df['orders'])\n"
    verdict = _judge(program, _sales("orders against orders"))
    assert isinstance(verdict, Passed)
    assert verdict.interpretation == "Points: orders from sales.csv."


def test_slots_take_their_rows_before_keyed_points() -> None:
    """The keyed point's first candidate row is the one the slot needs; a later twin row is free."""
    content = b"k,v\nc,9\nb,5\na,1\na,1\n"
    program = _PLT + "plt.scatter([0, 2], [1, 1])\nplt.xticks([0], ['a'])\n"
    verdict = _judge(program, Sources((("t.csv", content),), "v by k"))
    assert isinstance(verdict, Passed)
    assert verdict.choices[0].explanation is not None
    assert verdict.choices[0].explanation.family == "raw"
