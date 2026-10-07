# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M13.8 width: the pandas plotting accessor, `.reset_index()` after a reduction, the declared gap.

Contract: `.agent/archive/contracts/m13u8.md` predicate groups P, R and G1. Each docstring
carries its predicate's acceptance check; the check is the test's specification and the contract's
wording wins wherever a body would assert more.

Both idioms are new SPELLINGS of marks the verifier already projects, so neither may widen
`CorePlotSpec`, the 55-member refusal set, or the one-mark rule. The measured inputs are verbatim
from `corpus/python/captures/m13-design`: `kind='bar'` in 4 of 4 accessor rows, `color='skyblue'` in
3 of 4, a positional argument in 0 of 4, and no other keyword anywhere. Two of the four group
`weather.csv`, so nothing here may assume `sales.csv`.
"""

from pathlib import Path

import pytest

from verifier.pysrc import spec
from verifier.pysrc.admit import (
    ADMITTED_ACCESSOR_KEYWORDS,
    ADMITTED_ACCESSOR_KINDS,
    ADMITTED_UNWRAPPED_ATTRS,
    parse_admitted,
)
from verifier.pysrc.errors import PysrcRefusalError
from verifier.pysrc.project import project

_PRELUDE = "import pandas as pd\nimport matplotlib.pyplot as plt\n"
_ROOT = Path(__file__).resolve().parent.parent


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


def _admission_code(source: str) -> str:
    with pytest.raises(PysrcRefusalError) as caught:
        parse_admitted(source)
    return str(caught.value.code)


def _projection_code(source: str) -> str:
    with pytest.raises(PysrcRefusalError) as caught:
        project(parse_admitted(source))
    return str(caught.value.code)


def test_p1_the_accessor_projects_equal_to_the_plt_bar_spelling() -> None:
    """P1: `g.plot(kind="bar")` verifies and projects to the SAME `DatasetPlot` as
    `plt.bar(g.index, g.values)` over the same program. Accept: structural equality between the two
    projections, not merely that both verify -- two spellings of one figure must project equal, or
    the certificate publishes a different figure for a cosmetic rewrite."""
    accessor = project(parse_admitted(_accessor_source('kind="bar"')))
    series = project(parse_admitted(_series_source()))
    assert accessor == series


def test_p2_an_unadmitted_kind_refuses_call_target_not_admitted() -> None:
    """P2: `kind` is part of TARGET IDENTITY. `g.plot(kind="pie")` refuses
    `call_target_not_admitted`. Accept: that exact code. `<agg>.plot(kind="bar")` IS `plt.bar`
    spelled differently, so the accessor-plus-kind PAIR is the target and an unlisted pair is the
    same fault `plt.pie` would be."""
    assert _admission_code(_accessor_source('kind="pie"')) == "call_target_not_admitted"


def test_p2_a_non_literal_kind_refuses_call_target_not_admitted() -> None:
    """P2: `g.plot(kind=chart_kind)` refuses `call_target_not_admitted`. Accept: that exact code.
    The map is a closed dispatch over string LITERALS; a name is not a target."""
    source = _source(
        'chart_kind = "bar"\n'
        'g = df.groupby("region")["revenue"].sum()\n'
        "g.plot(kind=chart_kind)\n"
        "plt.show()\n"
    )
    assert _admission_code(source) == "call_target_not_admitted"


def test_p2_a_missing_kind_refuses_call_target_not_admitted() -> None:
    """P2: `g.plot()` refuses `call_target_not_admitted`. Accept: that exact code. pandas defaults a
    missing `kind` to a LINE plot; admitting that default is width no measured row asks for."""
    assert _admission_code(_accessor_source("")) == "call_target_not_admitted"


def test_p2_the_admitted_kind_map_is_exactly_bar_barh_and_line() -> None:
    """P2, widened by M10.10 A2: exactly three hand-stated call targets; barh still projects."""
    assert ADMITTED_ACCESSOR_KINDS == {"bar": "plt.bar", "barh": "plt.barh", "line": "plt.plot"}
    horizontal = project(parse_admitted(_accessor_source('kind="barh"')))
    assert isinstance(horizontal, spec.DatasetPlot)
    assert horizontal.mark == "barh"


def test_p3_an_unadmitted_keyword_refuses_keyword_not_admitted() -> None:
    """P3: `g.plot(kind="bar", figsize=(8, 5))` refuses `keyword_not_admitted`. Accept: that exact
    code. The accessor's keyword allowlist is exactly `{kind, color}`, measured over all four
    capture rows."""
    assert _admission_code(_accessor_source('kind="bar", figsize=(8, 5)')) == "keyword_not_admitted"


def test_p3_a_positional_argument_refuses_keyword_not_admitted() -> None:
    """P3: `g.plot("bar")` refuses `keyword_not_admitted`. Accept: that exact code. Zero of the four
    measured rows pass a positional argument, so the positional form buys no conversion."""
    assert _admission_code(_accessor_source('"bar"')) == "keyword_not_admitted"


def test_p3_the_accessor_keyword_set_is_exactly_kind_and_color() -> None:
    """P3: an exact-set assertion on the admitted keyword set, hand-stated as literals, so a later
    widening is a visible edit rather than a silent one. Accept: the set equals `{"kind", "color"}`
    and an added member fails here."""
    assert frozenset({"kind", "color"}) == ADMITTED_ACCESSOR_KEYWORDS


def test_p4_a_non_literal_color_refuses_label_not_literal() -> None:
    """P4: `g.plot(kind="bar", color=df["region"])` refuses `label_not_literal`. Accept: that exact
    code. Colour-by-category is a DATA EFFECT wearing a cosmetic keyword's name, and the accessor
    must not become the hole that admits the mark the user cancelled.

    At PROJECTION, because the contract says `identically to plt.bar's` and that is where
    `plt.bar(x, y, color=df["region"])` lands: `color` is an admitted keyword carrying an admitted
    expression, and the literal check belongs to the one seam both spellings share. Pinning it at
    admission would assert more than the predicate and would duplicate the seam to do it."""
    assert (
        _projection_code(_accessor_source('kind="bar", color=df["region"]')) == "label_not_literal"
    )


def test_p4_color_does_not_change_the_projection() -> None:
    """P4: `color` is validated as a string literal then DISCARDED, identically to `plt.bar`'s.
    Accept: `g.plot(kind="bar", color="skyblue")` and `g.plot(kind="bar")` project EQUAL.

    Keyword ORDER is covered here too. All four measured rows write `kind` first, and nothing makes
    a proposer keep that order; reading `kind` off a scan that stops at the first keyword would pass
    every measured row and refuse `call_target_not_admitted` on the reversed one."""
    aggregation = 'g = df.groupby("city")["temp_c"].mean()\n'
    colored_source = _source(
        aggregation + 'g.plot(kind="bar", color="skyblue")\nplt.show()\n', path="weather.csv"
    )
    reversed_source = _source(
        aggregation + 'g.plot(color="skyblue", kind="bar")\nplt.show()\n', path="weather.csv"
    )
    plain_source = _source(aggregation + 'g.plot(kind="bar")\nplt.show()\n', path="weather.csv")
    plain = project(parse_admitted(plain_source))
    assert project(parse_admitted(colored_source)) == plain
    assert project(parse_admitted(reversed_source)) == plain


def test_p5_the_frame_accessor_refuses_column_not_from_source() -> None:
    """P5: `df.plot(kind="bar")` refuses `column_not_from_source`. Accept: that exact code, raised
    at PROJECTION. It refuses at ADMISSION today; opening the accessor route makes it structurally
    admissible, so this predicate pins where the refusal moves to."""
    tree = parse_admitted(_source('df.plot(kind="bar")\nplt.show()\n'))
    with pytest.raises(PysrcRefusalError) as caught:
        project(tree)
    assert str(caught.value.code) == "column_not_from_source"


def test_p5_a_raw_column_accessor_refuses_column_not_from_source() -> None:
    """P5: `df["revenue"].plot(kind="bar")` refuses `column_not_from_source`. Accept: that exact
    code. The accessor is admitted on a REDUCED SERIES alone; a raw column receiver does not name a
    projected aggregate, which is the fault `_aggregate_channels` already names."""
    source = _source('df["revenue"].plot(kind="bar")\nplt.show()\n')
    assert _projection_code(source) == "column_not_from_source"


def test_p5_a_subscripted_aggregate_accessor_refuses_column_not_from_source() -> None:
    """P5: `g["revenue"].plot(kind="bar")` over a REDUCED `g` refuses `column_not_from_source`.

    Accept: that exact code at PROJECTION. P5 admits the accessor on a reduced series ALONE, and
    `g["revenue"]` is not one -- it selects a single element of that series by GROUP KEY, so the
    executed receiver is a scalar. Admission prices the subscript's slice and routes the call on
    its ROOT name, which leaves projection the only place the selection can be priced; reading the
    root alone verifies `g` for a program that draws something else entirely."""
    source = _accessor_source('kind="bar"', receiver='g["revenue"]')
    assert _projection_code(source) == "column_not_from_source"


def test_p5_the_accessor_without_a_source_refuses_no_source() -> None:
    """P5: an accessor in a program that binds NO `pd.read_csv` frame refuses `no_source`.

    MAIN added this at close, for the precondition the 26 contracted rows leave uncovered. The arm
    reads before the channels, exactly as `_resolve_dataset_mark` reads it: with no source bound,
    `column_not_from_source` would report a symptom where `no_source` names the cause. It carries
    the formula arm as well -- only `pd.read_csv` binds a frame."""
    source = _PRELUDE + 'g = 1\ng.plot(kind="bar")\nplt.show()\n'
    assert _projection_code(source) == "no_source"


def test_p6_the_accessor_then_plt_bar_refuses_multiple_marks() -> None:
    """P6: `g.plot(kind="bar")` followed by `plt.bar(g.index, g.values)` refuses `multiple_marks`.
    Accept: that exact code. The accessor enters the same mark-counting seam as every other mark;
    a parallel route publishes one of two figures with no refusal."""
    source = _source(
        'g = df.groupby("region")["revenue"].sum()\n'
        'g.plot(kind="bar")\n'
        "plt.bar(g.index, g.values)\n"
        "plt.show()\n"
    )
    assert _projection_code(source) == "multiple_marks"


def test_p6_plt_bar_then_the_accessor_refuses_multiple_marks() -> None:
    """P6: the reverse order refuses `multiple_marks` too. Accept: that exact code. Order-dependent
    mark counting is the half a single-direction test leaves unpinned."""
    source = _source(
        'g = df.groupby("region")["revenue"].sum()\n'
        "plt.bar(g.index, g.values)\n"
        'g.plot(kind="bar")\n'
        "plt.show()\n"
    )
    assert _projection_code(source) == "multiple_marks"


def test_p7_the_alias_allowlist_stays_closed_to_plot() -> None:
    """P7: `_admit_call`'s `<alias>.<attr>` shape is NOT loosened. Accept: `plt.plot_wrong`,
    `np.plot` and `pd.plot` each still refuse `call_target_not_admitted`. The accessor resolves
    through its own route, keyed on a name the aggregation bound.

    The `kind="bar"` pair carries the alias exclusion itself: without a `kind`, an alias that DID
    reach the accessor route would refuse the same code for a different reason, so the bare pair
    alone leaves `accessor_receiver`'s `_IMPORT_ALIASES` conjunct unpinned."""
    sources = {
        "plt.plot_wrong": _source("plt.plot_wrong()\n"),
        "np.plot": "import numpy as np\n" + _source("np.plot()\n"),
        "pd.plot": _source("pd.plot()\n"),
        "np.plot kind": "import numpy as np\n" + _source('np.plot(kind="bar")\n'),
        "pd.plot kind": _source('pd.plot(kind="bar")\n'),
    }
    for name, source in sources.items():
        assert _admission_code(source) == "call_target_not_admitted", name


def test_p7_an_unbound_receiver_refuses_name_not_bound() -> None:
    """P7: `nosuch.plot(kind="bar")` refuses `name_not_bound`. Accept: that exact code. The
    bound-name route opens beside the alias allowlist, never inside it."""
    source = _source('nosuch.plot(kind="bar")\n')
    assert _admission_code(source) == "name_not_bound"


def test_r1_reset_index_projects_equal_to_the_series_spelling() -> None:
    """R1: `…max().reset_index()` then `plt.bar(g["region"], g["revenue"])` verifies and projects to
    the SAME `DatasetPlot` as its `.index`/`.values` spelling. Accept: structural equality between
    the two projections, as in P1."""
    reset_frame = project(parse_admitted(_reset_source()))
    series = project(parse_admitted(_series_source(reduction="max")))
    assert reset_frame == series


def test_r2_swapped_channels_refuse_column_not_from_source() -> None:
    """R2: `plt.bar(g["revenue"], g["region"])` refuses `column_not_from_source`. Accept: that exact
    code. The x channel must be the chain KEY and the y channel the chain VALUE column."""
    source = _reset_source(x='g["revenue"]', y='g["region"]')
    assert _projection_code(source) == "column_not_from_source"


def test_r2_a_column_the_reset_frame_lacks_refuses_column_not_from_source() -> None:
    """R2: `plt.bar(g["region"], g["price"])` refuses `column_not_from_source`. Accept: that exact
    code. The reset frame carries exactly two columns and neither is invented."""
    source = _reset_source(y='g["price"]')
    assert _projection_code(source) == "column_not_from_source"


def test_r2_the_key_on_both_axes_refuses_column_not_from_source() -> None:
    """R2: `plt.bar(g["region"], g["region"])` refuses `column_not_from_source`. Accept: that exact
    code. A key plotted against itself is not a magnitude."""
    source = _reset_source(y='g["region"]')
    assert _projection_code(source) == "column_not_from_source"


def test_r3_sort_values_still_refuses_aggregation_not_projected() -> None:
    """R3: the unwrap is BY NAME. `…max().sort_values()` keeps refusing
    `aggregation_not_projected`, with its ADMISSION unchanged. Accept: that exact code. This is the
    unit's load-bearing negative -- `.sort_values()` is ALREADY admitted and is refused at the same
    site with the same code as `.reset_index()`, so an unwrap that takes whatever trailing call it
    finds admits a REORDERING silently and G8's row coverage and G9's ordering both stop holding
    with nothing red."""
    source = _source(
        'g = df.groupby("region")["revenue"].max().sort_values()\n'
        "plt.bar(g.index, g.values)\n"
        "plt.show()\n"
    )
    assert _projection_code(source) == "aggregation_not_projected"


def test_r3_the_unwrapped_attribute_set_is_exactly_reset_index() -> None:
    """R3: an exact-set assertion on the unwrapped attribute set, hand-stated as literals. Accept:
    the set equals `{"reset_index"}`. Written as a set rather than as one `.sort_values()` case
    because the next trailing call added would slip through a one-case test."""
    assert frozenset({"reset_index"}) == ADMITTED_UNWRAPPED_ATTRS


def test_r4_rebinding_a_reset_frame_refuses_name_rebound() -> None:
    """R4: a program binding `g` from `pd.read_csv` AND from a reset aggregation refuses
    `name_rebound`. Accept: that exact code. The reset-frame name must not leak into the raw-column
    namespace.

    The second case rebinds a name bound by NOTHING but a reset, which is what pins the guard's own
    `self._resets` conjunct: the first case already refuses through `self._frames`."""
    source = _PRELUDE + (
        'g = pd.read_csv("sales.csv")\n'
        'g = g.groupby("region")["revenue"].max().reset_index()\n'
        'plt.bar(g["region"], g["revenue"])\n'
        "plt.show()\n"
    )
    assert _projection_code(source) == "name_rebound"
    reset_only = _source(
        'g = df.groupby("region")["revenue"].max().reset_index()\n'
        'g = df.groupby("region")["orders"].max().reset_index()\n'
        'plt.bar(g["region"], g["orders"])\n'
        "plt.show()\n"
    )
    assert _projection_code(reset_only) == "name_rebound"


def test_r4_a_subscript_without_an_aggregation_refuses_column_not_from_source() -> None:
    """R4: `g["region"]` in a program with NO aggregation still refuses `column_not_from_source`.
    Accept: that exact code. `g["region"]` resolves ONLY as an aggregate channel."""
    source = _source('g = df\nplt.bar(g["region"], df["revenue"])\nplt.show()\n')
    assert _projection_code(source) == "column_not_from_source"


def test_g1_the_accessor_tick_placement_gap_is_stated() -> None:
    """G1: the accessor's TICK PLACEMENT differs from `plt.bar` for a NUMERIC group key -- pandas
    draws categorically at positions 0..n-1, `plt.bar` at the data positions. Ruled TRUSTED, not
    closed: the gap is inside the renderer, the recomputed table is identical, no plotted VALUE
    differs. Accept: the gap is STATED in `.claude/rules/pysrc.md` under the projection law, in the
    same register as the existing per-construct gap rulings. Projection law admits a gap closed by
    construction or declared trusted, never unstated, so an UNSTATED gap is the defect."""
    law = (_ROOT / ".claude" / "rules" / "pysrc.md").read_text(encoding="utf-8")
    projection_law = law.partition("## Projection law")[2].partition("\n## ")[0]
    paragraphs = [
        " ".join(paragraph.lower().split())
        for paragraph in projection_law.split("\n\n")
        if "accessor" in paragraph.lower()
        and "numeric group key" in " ".join(paragraph.lower().split())
    ]
    assert len(paragraphs) == 1
    gap = paragraphs[0]
    for fact in (
        "numeric group key",
        "0..n-1",
        "`plt.bar`",
        "data positions",
        "trusted",
        "recomputed table",
        "no plotted value",
    ):
        assert fact in gap
