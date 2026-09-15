# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M13.6 presentation: the data-effect-free cosmetic cluster, and the G-rows this width re-pins.

Contract: `.agent/contracts/m13u6.md` predicate group W, plus G2r and G78r. Each docstring carries
its predicate's acceptance check; the contract's wording wins wherever a body would assert more.

These calls are admitted WITHOUT amending the law that nothing is silently ignored: each is carried
into `Labels`, so each still contributes to the spec, and the certificate may publish or omit it.
`plt.figure` is the one member that is not purely cosmetic — a second call starts a new figure and
would discard an already-resolved mark, which is a real data effect and W3's whole subject.

A by-construction G-row is only as durable as the refusal under it, so G2r and G78r pin their rules
against the constructs that would break them rather than against the current mark count.

Skeleton: each body is `pytest.skip` until M13.6 lands. Both the skips and this line clear at that
unit's close.
"""

import pytest

# --- W: the data-effect-free cluster -----------------------------------------


def test_w1_labels_gains_exactly_three_presentation_fields() -> None:
    """W1: `Labels.__dataclass_fields__` pinned as an exact set adding `figsize`, `tick_rotation`
    and `tight_layout` and nothing else. Two programs differing only in `figsize` project to UNEQUAL
    specs — the fields are carried, not discarded."""
    pytest.skip("M13.6: needs the cosmetic-cluster width; red until it lands")


def test_w2_figure_admits_only_a_literal_two_tuple_figsize() -> None:
    """W2: `plt.figure()` and `plt.figure(figsize=(10, 6))` admit. `plt.figure(1)`,
    `plt.figure(dpi=200)`, `plt.figure(figsize=(w, 6))` for a bound `w`,
    `plt.figure(figsize=(10, 6, 2))`, `plt.figure(figsize='big')` and `plt.figure(figsize=[10, 6])`
    each refuse."""
    pytest.skip("M13.6: needs the cosmetic-cluster width; red until it lands")


def test_w2_no_other_call_or_keyword_gained_tuple_admission() -> None:
    """W2: `figsize` is the ONLY admitted tuple in the language. A tuple in any other keyword or
    argument slot still refuses `expression_not_admitted` — the near-miss pin that keeps
    `ADMITTED_TUPLE_KEYWORDS` from being a general display rule."""
    pytest.skip("M13.6: needs the cosmetic-cluster width; red until it lands")


def test_w3_figure_after_a_mark_refuses_figure_orphans_mark() -> None:
    """W3: `plt.bar(...)` then `plt.figure()` refuses `figure_orphans_mark`, NOT
    `statement_not_projected`. Two `plt.figure()` calls refuse the same. `plt.figure()` then
    `plt.bar(...)` verifies. A mutant deleting the ordering check goes red on the first witness."""
    pytest.skip("M13.6: needs the cosmetic-cluster width; red until it lands")


def test_w4_tight_layout_admits_bare_and_once() -> None:
    """W4: `plt.tight_layout()` admits and sets the field; `plt.tight_layout(pad=2)` refuses; twice
    refuses `statement_not_projected`, like every other decoration."""
    pytest.skip("M13.6: needs the cosmetic-cluster width; red until it lands")


def test_w5_xticks_admits_rotation_only_and_no_positional() -> None:
    """W5: `plt.xticks(rotation=45)` admits. `plt.xticks([1, 2, 3])` and `plt.xticks(df['month'])`
    refuse `statement_not_projected` — a positional argument sets tick locations or labels, which
    changes what the figure asserts about x. `plt.xticks(rotation='vertical')` refuses
    `label_not_literal`."""
    pytest.skip("M13.6: needs the cosmetic-cluster width; red until it lands")


def test_w6_marks_admit_three_literal_only_keywords() -> None:
    """W6: `color=`, `marker=`, `linestyle=` admit a string literal, per target and matching
    matplotlib's own signature. `color=df['city']` refuses `label_not_literal` — that is the
    colour-by-category channel in disguise and the witness that matters."""
    pytest.skip("M13.6: needs the cosmetic-cluster width; red until it lands")


def test_w7_data_bearing_keywords_stay_refused() -> None:
    """W7: `c=`, `cmap=`, `edgecolors=`, `s=` and `alpha=` each refuse `keyword_not_admitted`.
    `c=`/`cmap=` are the colour-by-category channel the user ruled out and `s=` is G6's
    area-encoding channel; none may enter by the W6 door. This is the near-miss pin `assurance.md`
    requires beside W6's allowlist."""
    pytest.skip("M13.6: needs the cosmetic-cluster width; red until it lands")


# --- G2r + G78r: the by-construction rows, re-pinned -------------------------


def test_g2r_dual_axis_constructs_each_refuse() -> None:
    """G2r: `plt.twinx`, `plt.twiny`, `ax.secondary_yaxis` and `plt.subplots` each refuse. G2 stays
    true BY CONSTRUCTION and is pinned against these rather than against mark count, so a later
    widening cannot delete G2 silently."""
    pytest.skip("M13.6: needs the cosmetic-cluster width; red until it lands")


def test_g78r_row_selection_idioms_each_refuse() -> None:
    """G78r: `df[df['c'] == 'x']`, `df.head(3)`, `df.dropna()` and `df.iloc[:3]` each refuse. With
    no filter admitted the plotted column is still the whole column, which is what keeps G7 and G8
    unconditional rather than moving them to a published `Filter`."""
    pytest.skip("M13.6: needs the cosmetic-cluster width; red until it lands")
