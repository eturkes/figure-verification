# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Diff-blind red suite for M13.4 dataset-arm projection.

Contract: `.agent/contracts/m13u4.md`. Each test names ONE predicate and its docstring carries that
predicate's acceptance check verbatim, so a red states which ruling it defends.

Every test here is skip-marked until the `test` teammate fills it. A filled test drops its marker.
"""

import pytest

pytestmark = pytest.mark.skip(reason="M13.4 skeleton -- filled by the `test` teammate")


def test_d1_arm_selection_is_closed() -> None:
    """D1: a pandas import selects the dataset arm, a grid call the formula arm.

    Accept: a program importing pandas AND using `np.linspace` refuses `arm_ambiguous`; no `else:`
    tail picks an arm.
    """


def test_d2_exactly_one_source() -> None:
    """D2: exactly one `read_csv`, bound to exactly one name.

    Accept: two `read_csv` assignments refuse `multiple_sources`; zero in the dataset arm refuses
    `no_source`.
    """


def test_d3_source_argument_is_a_string_literal() -> None:
    """D3: the `read_csv` argument is a single positional string literal.

    Accept: `pd.read_csv(p)` refuses `source_not_literal`; `pd.read_csv("a.csv", sep=";")` refuses
    `keyword_not_admitted`.
    """


def test_d4_column_reference_shape() -> None:
    """D4: a column is `<bound frame>["<string literal>"]`.

    Accept: `df[c]` refuses `column_not_literal`; `other["a"]` refuses `column_not_from_source`.
    """


def test_d5_both_channels_share_one_frame() -> None:
    """D5: both mark channels are columns of the SAME bound frame.

    Accept: `plt.scatter(df["a"], other["b"])` refuses `column_not_from_source`.
    """


def test_d6_dataset_mark_admits_bar() -> None:
    """D6: `DatasetMark` is line | scatter | bar; bar is VALID in this arm.

    Accept: `plt.bar(df["region"], df["revenue"])` projects with `mark == "bar"`.
    """


def test_d7_exactly_one_mark() -> None:
    """D7: exactly one mark call, refusal precedence LOCAL before GLOBAL.

    Accept: two marks refuse `multiple_marks`.
    """


def test_d8_labels_match_the_formula_arm() -> None:
    """D8: decorations project to the same `Labels` record as the formula arm.

    Accept: a non-string-literal argument refuses `label_not_literal`.
    """


def test_d9_terminal_show_is_last() -> None:
    """D9: exactly one `plt.show()`, and it is final.

    Accept: zero refuses `no_terminal`; a non-final one refuses `statement_after_terminal`.
    """


def test_d10_total_statement_coverage() -> None:
    """D10: every admitted statement contributes to the returned spec.

    Accept: an unused column assignment refuses `statement_not_projected`.
    """


def test_d11_projection_is_pure() -> None:
    """D11: projection is a pure function of the tree, holding no `ast` node or source text.

    Accept: equality over two parses of the same bytes; a search test over `spec.py` for `ast.`.
    """


def test_d12_core_plot_spec_union_is_exact() -> None:
    """D12: `CorePlotSpec` is EXACTLY `FormulaPlot | DatasetPlot`.

    Accept: `get_args(CorePlotSpec.__value__)` equals the hand-stated two-member tuple. A PEP-695
    alias needs `__value__` -- `get_args()` on the alias itself returns `()`.
    """


def test_g1_dataset_bar_baseline_holds_by_construction() -> None:
    """G1: axis limits stay unadmitted, so a dataset bar's baseline is at zero by construction.

    Accept: `plt.ylim(50, 100)` after a dataset bar refuses `call_target_not_admitted`.
    """


def test_g5_bar_is_arm_dependent() -> None:
    """G5: the same `plt.bar` call is refused in the formula arm and admitted in the dataset arm.

    Accept: BOTH halves asserted in one test -- this row is also the unit's probe seed, so admitting
    bar in the formula arm must turn it red.
    """


def test_g2_g3_g6_survive_the_widening() -> None:
    """G2/G3/G6: re-asserted against a DATASET program so the widening cannot silently delete them.

    Accept: `plt.twinx`, `plt.yscale` refuse `call_target_not_admitted`; `s=` on `plt.scatter`
    refuses `keyword_not_admitted`.
    """
