# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M16.1 C1-C5: the "Show checks" vocabulary, row soundness, texts and the rendered document.

Contract: `.agent/contracts/m16u1.md`. Skeleton: each body is a module-level skip naming M16.1.
"""

import pytest

pytestmark = pytest.mark.skip(reason="M16.1 skeleton: the tester fills each body from the contract")


def test_c1_check_order_and_reason_map_are_the_hand_stated_tables() -> None:
    """C1: CHECKS = 11 ids in order; CHECK_OF = the contract table over all 66 reasons."""


def test_c2_each_refusal_maps_to_its_earliest_raise_site_check() -> None:
    """C2: AST scan incl. class methods; unmapped site or a later check -> red."""


def test_c3_every_text_obeys_the_text_law_and_anchors_are_byte_exact() -> None:
    """C3: EN ASCII + word caps; JA kana; no markup chars, `Chart.`, `x-`; anchors exact."""


def test_c4_document_rows_follow_the_failing_check() -> None:
    """C4: 134 documents: lang, closed details, 11 rows, marks + labels, cause, unrun; escaping."""


def test_c5_document_is_self_contained_and_inert() -> None:
    """C5: no external refs; one fixed height script; no OWUI injection triggers; <=16 KiB."""
