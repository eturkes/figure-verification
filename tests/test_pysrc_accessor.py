# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M13.8 width: the pandas plotting accessor, `.reset_index()` after a reduction, the declared gap.

Contract: `.agent/contracts/m13u8.md` predicate groups P, R and G1. Each docstring carries its
predicate's acceptance check; the check is the test's specification and the contract's wording wins
wherever a body would assert more.

Skeleton: each body is `pytest.skip` until M13.8's implementation lands. The close deletes every
skip, this line, and nothing else.

Both idioms are new SPELLINGS of marks the verifier already projects, so neither may widen
`CorePlotSpec`, the 50-member refusal set, or the one-mark rule. The measured inputs are verbatim
from `corpus/python/captures/m13-design`: `kind='bar'` in 4 of 4 accessor rows, `color='skyblue'` in
3 of 4, a positional argument in 0 of 4, and no other keyword anywhere. Two of the four group
`weather.csv`, so nothing here may assume `sales.csv`.
"""

import pytest

_PRELUDE = "import pandas as pd\nimport matplotlib.pyplot as plt\n"


def _source(body: str, *, path: str = "sales.csv") -> str:
    return _PRELUDE + f'df = pd.read_csv("{path}")\n' + body


def _accessor_source(args: str, *, reduction: str = "sum", receiver: str = "g") -> str:
    """`g = df.groupby(...)[...].<reduction>()` then `<receiver>.plot(<args>)` then `plt.show()`."""
    return _source(
        f'g = df.groupby("region")["revenue"].{reduction}()\n{receiver}.plot({args})\nplt.show()\n'
    )


def _series_source(reduction: str = "sum") -> str:
    """The `plt.bar(g.index, g.values)` spelling of the same figure the accessor draws."""
    return _source(
        f'g = df.groupby("region")["revenue"].{reduction}()\n'
        "plt.bar(g.index, g.values)\n"
        "plt.show()\n"
    )


def _reset_source(
    x: str = 'g["region"]', y: str = 'g["revenue"]', *, trailing: str = "reset_index"
) -> str:
    """`…max().<trailing>()` then `plt.bar(<x>, <y>)`, the shape both measured rows write."""
    return _source(
        f'g = df.groupby("region")["revenue"].max().{trailing}()\nplt.bar({x}, {y})\nplt.show()\n'
    )


def test_p1_the_accessor_projects_equal_to_the_plt_bar_spelling() -> None:
    """P1: `g.plot(kind="bar")` verifies and projects to the SAME `DatasetPlot` as
    `plt.bar(g.index, g.values)` over the same program. Accept: structural equality between the two
    projections, not merely that both verify -- two spellings of one figure must project equal, or
    the certificate publishes a different figure for a cosmetic rewrite."""
    pytest.skip("M13.8 skeleton: the accessor route is unwritten.")


def test_p2_an_unadmitted_kind_refuses_call_target_not_admitted() -> None:
    """P2: `kind` is part of TARGET IDENTITY. `g.plot(kind="pie")` refuses
    `call_target_not_admitted`. Accept: that exact code. `<agg>.plot(kind="bar")` IS `plt.bar`
    spelled differently, so the accessor-plus-kind PAIR is the target and an unlisted pair is the
    same fault `plt.pie` would be."""
    pytest.skip("M13.8 skeleton: the accessor route is unwritten.")


def test_p2_kind_line_refuses_call_target_not_admitted() -> None:
    """P2: `g.plot(kind="line")` refuses `call_target_not_admitted`. Accept: that exact code. Named
    apart from `pie` because `line` is pandas' own default and is the shape a permissive map admits
    by accident."""
    pytest.skip("M13.8 skeleton: the accessor route is unwritten.")


def test_p2_a_non_literal_kind_refuses_call_target_not_admitted() -> None:
    """P2: `g.plot(kind=chart_kind)` refuses `call_target_not_admitted`. Accept: that exact code.
    The map is a closed dispatch over string LITERALS; a name is not a target."""
    pytest.skip("M13.8 skeleton: the accessor route is unwritten.")


def test_p2_a_missing_kind_refuses_call_target_not_admitted() -> None:
    """P2: `g.plot()` refuses `call_target_not_admitted`. Accept: that exact code. pandas defaults a
    missing `kind` to a LINE plot; admitting that default is width no measured row asks for."""
    pytest.skip("M13.8 skeleton: the accessor route is unwritten.")


def test_p2_the_admitted_kind_map_is_exactly_bar_and_barh() -> None:
    """P2: the admitted map is `{"bar": "bar", "barh": "barh"}` and nothing else. Accept: an
    exact-set assertion on the map, hand-stated as literals rather than read from production, plus
    `g.plot(kind="barh")` verifying. A test reading the production constant pins nothing."""
    pytest.skip("M13.8 skeleton: the accessor route is unwritten.")


def test_p3_an_unadmitted_keyword_refuses_keyword_not_admitted() -> None:
    """P3: `g.plot(kind="bar", figsize=(8, 5))` refuses `keyword_not_admitted`. Accept: that exact
    code. The accessor's keyword allowlist is exactly `{kind, color}`, measured over all four
    capture rows."""
    pytest.skip("M13.8 skeleton: the accessor route is unwritten.")


def test_p3_a_positional_argument_refuses_keyword_not_admitted() -> None:
    """P3: `g.plot("bar")` refuses `keyword_not_admitted`. Accept: that exact code. Zero of the four
    measured rows pass a positional argument, so the positional form buys no conversion."""
    pytest.skip("M13.8 skeleton: the accessor route is unwritten.")


def test_p3_the_accessor_keyword_set_is_exactly_kind_and_color() -> None:
    """P3: an exact-set assertion on the admitted keyword set, hand-stated as literals, so a later
    widening is a visible edit rather than a silent one. Accept: the set equals `{"kind", "color"}`
    and an added member fails here."""
    pytest.skip("M13.8 skeleton: the accessor route is unwritten.")


def test_p4_a_non_literal_color_refuses_label_not_literal() -> None:
    """P4: `g.plot(kind="bar", color=df["region"])` refuses `label_not_literal`. Accept: that exact
    code. Colour-by-category is a DATA EFFECT wearing a cosmetic keyword's name, and the accessor
    must not become the hole that admits the mark the user cancelled."""
    pytest.skip("M13.8 skeleton: the accessor route is unwritten.")


def test_p4_color_does_not_change_the_projection() -> None:
    """P4: `color` is validated as a string literal then DISCARDED, identically to `plt.bar`'s.
    Accept: `g.plot(kind="bar", color="skyblue")` and `g.plot(kind="bar")` project EQUAL."""
    pytest.skip("M13.8 skeleton: the accessor route is unwritten.")


def test_p5_the_frame_accessor_refuses_column_not_from_source() -> None:
    """P5: `df.plot(kind="bar")` refuses `column_not_from_source`. Accept: that exact code, raised
    at PROJECTION. It refuses at ADMISSION today; opening the accessor route makes it structurally
    admissible, so this predicate pins where the refusal moves to."""
    pytest.skip("M13.8 skeleton: the accessor route is unwritten.")


def test_p5_a_raw_column_accessor_refuses_column_not_from_source() -> None:
    """P5: `df["revenue"].plot(kind="bar")` refuses `column_not_from_source`. Accept: that exact
    code. The accessor is admitted on a REDUCED SERIES alone; a raw column receiver does not name a
    projected aggregate, which is the fault `_aggregate_channels` already names."""
    pytest.skip("M13.8 skeleton: the accessor route is unwritten.")


def test_p6_the_accessor_then_plt_bar_refuses_multiple_marks() -> None:
    """P6: `g.plot(kind="bar")` followed by `plt.bar(g.index, g.values)` refuses `multiple_marks`.
    Accept: that exact code. The accessor enters the same mark-counting seam as every other mark;
    a parallel route publishes one of two figures with no refusal."""
    pytest.skip("M13.8 skeleton: the accessor route is unwritten.")


def test_p6_plt_bar_then_the_accessor_refuses_multiple_marks() -> None:
    """P6: the reverse order refuses `multiple_marks` too. Accept: that exact code. Order-dependent
    mark counting is the half a single-direction test leaves unpinned."""
    pytest.skip("M13.8 skeleton: the accessor route is unwritten.")


def test_p7_the_alias_allowlist_stays_closed_to_plot() -> None:
    """P7: `_admit_call`'s `<alias>.<attr>` shape is NOT loosened. Accept: `plt.plot_wrong`,
    `np.plot` and `pd.plot` each still refuse `call_target_not_admitted`. The accessor resolves
    through its own route, keyed on a name the aggregation bound."""
    pytest.skip("M13.8 skeleton: the accessor route is unwritten.")


def test_p7_an_unbound_receiver_refuses_name_not_bound() -> None:
    """P7: `nosuch.plot(kind="bar")` refuses `name_not_bound`. Accept: that exact code. The
    bound-name route opens beside the alias allowlist, never inside it."""
    pytest.skip("M13.8 skeleton: the accessor route is unwritten.")


def test_r1_reset_index_projects_equal_to_the_series_spelling() -> None:
    """R1: `…max().reset_index()` then `plt.bar(g["region"], g["revenue"])` verifies and projects to
    the SAME `DatasetPlot` as its `.index`/`.values` spelling. Accept: structural equality between
    the two projections, as in P1."""
    pytest.skip("M13.8 skeleton: the reset-index unwrap is unwritten.")


def test_r2_swapped_channels_refuse_column_not_from_source() -> None:
    """R2: `plt.bar(g["revenue"], g["region"])` refuses `column_not_from_source`. Accept: that exact
    code. The x channel must be the chain KEY and the y channel the chain VALUE column."""
    pytest.skip("M13.8 skeleton: the reset-index unwrap is unwritten.")


def test_r2_a_column_the_reset_frame_lacks_refuses_column_not_from_source() -> None:
    """R2: `plt.bar(g["region"], g["price"])` refuses `column_not_from_source`. Accept: that exact
    code. The reset frame carries exactly two columns and neither is invented."""
    pytest.skip("M13.8 skeleton: the reset-index unwrap is unwritten.")


def test_r2_the_key_on_both_axes_refuses_column_not_from_source() -> None:
    """R2: `plt.bar(g["region"], g["region"])` refuses `column_not_from_source`. Accept: that exact
    code. A key plotted against itself is not a magnitude."""
    pytest.skip("M13.8 skeleton: the reset-index unwrap is unwritten.")


def test_r3_sort_values_still_refuses_aggregation_not_projected() -> None:
    """R3: the unwrap is BY NAME. `…max().sort_values()` keeps refusing
    `aggregation_not_projected`, with its ADMISSION unchanged. Accept: that exact code. This is the
    unit's load-bearing negative -- `.sort_values()` is ALREADY admitted and is refused at the same
    site with the same code as `.reset_index()`, so an unwrap that takes whatever trailing call it
    finds admits a REORDERING silently and G8's row coverage and G9's ordering both stop holding
    with nothing red."""
    pytest.skip("M13.8 skeleton: the reset-index unwrap is unwritten.")


def test_r3_the_unwrapped_attribute_set_is_exactly_reset_index() -> None:
    """R3: an exact-set assertion on the unwrapped attribute set, hand-stated as literals. Accept:
    the set equals `{"reset_index"}`. Written as a set rather than as one `.sort_values()` case
    because the next trailing call added would slip through a one-case test."""
    pytest.skip("M13.8 skeleton: the reset-index unwrap is unwritten.")


def test_r4_rebinding_a_reset_frame_refuses_name_rebound() -> None:
    """R4: a program binding `g` from `pd.read_csv` AND from a reset aggregation refuses
    `name_rebound`. Accept: that exact code. The reset-frame name must not leak into the raw-column
    namespace."""
    pytest.skip("M13.8 skeleton: the reset-index unwrap is unwritten.")


def test_r4_a_subscript_without_an_aggregation_refuses_column_not_from_source() -> None:
    """R4: `g["region"]` in a program with NO aggregation still refuses `column_not_from_source`.
    Accept: that exact code. `g["region"]` resolves ONLY as an aggregate channel."""
    pytest.skip("M13.8 skeleton: the reset-index unwrap is unwritten.")


def test_g1_the_accessor_tick_placement_gap_is_stated() -> None:
    """G1: the accessor's TICK PLACEMENT differs from `plt.bar` for a NUMERIC group key -- pandas
    draws categorically at positions 0..n-1, `plt.bar` at the data positions. Ruled TRUSTED, not
    closed: the gap is inside the renderer, the recomputed table is identical, no plotted VALUE
    differs. Accept: the gap is STATED in `.claude/rules/pysrc.md` under the projection law, in the
    same register as the existing per-construct gap rulings. Projection law admits a gap closed by
    construction or declared trusted, never unstated, so an UNSTATED gap is the defect."""
    pytest.skip("M13.8 skeleton: the gap ruling is unwritten.")
