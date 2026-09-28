# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.10 width: the pandas line accessor `<reduced series>.plot(kind="line")`.

Contract: `.agent/contracts/m10u10.md` predicate group A. Each docstring carries its predicate's
acceptance check; the contract's wording wins wherever a body would assert more.

Skeleton: each body is `pytest.skip` until M10.10's implementation lands. The close deletes every
skip, this line, and nothing else.

The accessor line is a new SPELLING of `plt.plot(g.index, g.values)`, so it may widen neither
`CorePlotSpec`, the 52-member refusal set, the accessor keyword set, nor the one-mark rule.
"""

import pytest


def test_a1_line_accessor_projects_equal_to_the_plt_plot_spelling() -> None:
    """A1: for each reduction `sum mean min max`, over a string key (`sales.csv` `month`) and a
    numeric key (`sales.csv` `orders`), `g.plot(kind="line")` projects EQUAL to
    `plt.plot(g.index, g.values)`; both verify with equal `Verified.table` and byte-equal
    `certificate.interpretation`. Accept: `==` on the projections, tables and interpretations."""
    pytest.skip("M10.10 skeleton: the line accessor is unwritten.")


def test_a2_the_admitted_kind_map_is_bar_barh_and_line() -> None:
    """A2: `ADMITTED_ACCESSOR_KINDS == {"bar": "plt.bar", "barh": "plt.barh", "line": "plt.plot"}`
    as hand-stated literals, and `g.plot(kind="line")` projects `mark == "line"`. Accept: exact
    dict equality + the mark."""
    pytest.skip("M10.10 skeleton: the line accessor is unwritten.")


def test_a3_near_miss_kinds_refuse_call_target_not_admitted() -> None:
    """A3: `kind="area"`, `"scatter"`, `"hist"`, `"pie"`, `"Line"`, `"line "`, a non-literal kind
    and a MISSING kind each refuse `call_target_not_admitted`. Accept: each exact code."""
    pytest.skip("M10.10 skeleton: the line accessor is unwritten.")


def test_a4_the_accessor_keyword_set_is_unchanged() -> None:
    """A4: `ADMITTED_ACCESSOR_KEYWORDS == {"kind", "color"}` hand-stated; `marker="o"`,
    `linestyle="--"`, `label="x"`, `figsize=(8, 5)` and a positional `g.plot("line")` each refuse
    `keyword_not_admitted`; `color="red"` verifies. Accept: each exact code + the verify."""
    pytest.skip("M10.10 skeleton: the line accessor is unwritten.")


def test_a5_receiver_rules_match_the_bar_twin() -> None:
    """A5: `df["revenue"].plot(kind="line")`, `g["US"].plot(kind="line")`, a reset frame
    `r.plot(kind="line")` and `df.plot(kind="line")` refuse `column_not_from_source`;
    `g.plot.line()` refuses `attribute_not_admitted`. Accept: each exact code, equal to its
    `kind="bar"` twin's code."""
    pytest.skip("M10.10 skeleton: the line accessor is unwritten.")


def test_a6_a_line_accessor_is_one_mark() -> None:
    """A6: accessor line + `plt.bar(g.index, g.values)`, accessor line + accessor bar, and
    `plt.plot(g.index, g.values)` + accessor line each refuse `multiple_marks`. Accept: each exact
    code."""
    pytest.skip("M10.10 skeleton: the line accessor is unwritten.")


def test_a7_the_int32_renderer_bound_binds_bars_alone() -> None:
    """A7: over `key,value` rows `a,2147483647` x2 + `b,-2147483648` x2, `g.plot(kind="line")`
    VERIFIES and `g.plot(kind="bar")` refuses `value_not_in_profile`. Accept: both outcomes."""
    pytest.skip("M10.10 skeleton: the line accessor is unwritten.")


def test_a8_the_width_invariants_hold() -> None:
    """A8: 52 refusal codes (`typing.get_args(RefusalCode.__value__)`), `CorePlotSpec` 2 members,
    `observe.READERS` keys exactly `{line, scatter, bar, barh}`. Accept: hand-stated counts/sets."""
    pytest.skip("M10.10 skeleton: the line accessor is unwritten.")
