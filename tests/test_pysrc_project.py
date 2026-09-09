# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Diff-blind red suite for M13.3 projection. Contract: `.agent/contracts/m13u3.md`.

Every test below carries its predicate's acceptance check in the docstring and is skipped until it
is written. A test that asserts more than the ratified predicate loses to the predicate.
"""

import pytest


@pytest.mark.skip(reason="M13.3 P1 unwritten")
def test_p1_no_mark_refuses() -> None:
    """An admitted decoration-only program refuses `no_mark`; an empty program refuses `no_mark`."""
    raise NotImplementedError


@pytest.mark.skip(reason="M13.3 P2 unwritten")
def test_p2_exactly_one_mark() -> None:
    """Two `plt.plot` calls refuse `multiple_marks`; one projects to a spec."""
    raise NotImplementedError


@pytest.mark.skip(reason="M13.3 P3 unwritten")
def test_p3_x_resolves_to_grid() -> None:
    """`plt.plot(3, y)` refuses `x_not_a_grid`; bound and inline grid forms give equal specs."""
    raise NotImplementedError


@pytest.mark.skip(reason="M13.3 P4 unwritten")
def test_p4_y_over_grid_only() -> None:
    """A y expression with a second free name refuses `y_not_over_grid`."""
    raise NotImplementedError


@pytest.mark.skip(reason="M13.3 P5 unwritten")
def test_p5_grid_forms_agree() -> None:
    """`linspace` and `arange` project to one `Grid` shape; defaults 50 and 1 pinned as literals."""
    raise NotImplementedError


@pytest.mark.skip(reason="M13.3 P6 unwritten")
def test_p6_sample_count_representable() -> None:
    """`num=0`, `num=2.5` and a non-literal `num` each refuse `grid_not_representable`."""
    raise NotImplementedError


@pytest.mark.skip(reason="M13.3 P7 unwritten")
def test_p7_labels_are_literals() -> None:
    """`plt.title(x)` refuses `label_not_literal`; `plt.title("t")` reaches `labels.title`."""
    raise NotImplementedError


@pytest.mark.skip(reason="M13.3 P8 unwritten")
def test_p8_single_terminal_last() -> None:
    """Zero `plt.show()` refuses `no_terminal`; a late one refuses `statement_after_terminal`."""
    raise NotImplementedError


@pytest.mark.skip(reason="M13.3 P9 unwritten")
def test_p9_no_rebinding() -> None:
    """Rebinding an already-bound name refuses `name_rebound`."""
    raise NotImplementedError


@pytest.mark.skip(reason="M13.3 P10 unwritten")
def test_p10_bar_refused_in_formula_arm() -> None:
    """`plt.bar` over a grid refuses `mark_not_valid_for_arm` (G5)."""
    raise NotImplementedError


@pytest.mark.skip(reason="M13.3 P11 unwritten")
def test_p11_total_statement_coverage() -> None:
    """An assignment that never reaches the mark refuses `statement_not_projected`."""
    raise NotImplementedError


@pytest.mark.skip(reason="M13.3 P12 unwritten")
def test_p12_projection_is_pure() -> None:
    """Two parses of one source give equal specs; no `ast` node, line number or text rides."""
    raise NotImplementedError
