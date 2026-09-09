# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Graphical-integrity tripwires for the G-rules that hold BY CONSTRUCTION.

Contract: `.agent/contracts/m13u3.md`. Each test asserts BOTH halves — the target is absent from the
allowlist AND a program using it is refused — so widening `admit.py` breaks the rule's test instead
of silently deleting the rule. Rule text: `.claude/rules/pysrc.md` § Integrity rule set.
"""

import pytest


@pytest.mark.skip(reason="M13.3 G1 unwritten")
def test_g1_bar_baseline_unreachable() -> None:
    """`plt.ylim` absent from the allowlist; `plt.ylim(50, 100)` refuses by call target."""
    raise NotImplementedError


@pytest.mark.skip(reason="M13.3 G2 unwritten")
def test_g2_single_axes() -> None:
    """`twinx`, `subplots`, `subplot`, `gca`, `figure` absent; each refuses."""
    raise NotImplementedError


@pytest.mark.skip(reason="M13.3 G3 unwritten")
def test_g3_linear_scale_only() -> None:
    """`yscale`, `xscale`, `semilogy`, `loglog` absent; each refuses."""
    raise NotImplementedError


@pytest.mark.skip(reason="M13.3 G6 unwritten")
def test_g6_scatter_size_keyword_unreachable() -> None:
    """Keyword `s` unadmitted on `plt.scatter`; `s=v` refuses `keyword_not_admitted`."""
    raise NotImplementedError
