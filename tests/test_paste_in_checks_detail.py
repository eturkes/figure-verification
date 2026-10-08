# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M18.2 E1-E9b: each "Show checks" row opens to what it does, the code it read, why, the link.

Contract: `.agent/contracts/m18u2.md`. Skeleton: each body is a module-level skip naming M18.2.
"""

import pytest

pytestmark = pytest.mark.skip(reason="M18.2 skeleton: the tester fills each body from the contract")


def test_e1_new_texts_obey_the_text_law_and_anchors_are_byte_exact() -> None:
    """E1: EXPLAIN keys, CODE_ROLES map, UI words; C3 law; hand-stated anchors."""


def test_e2_every_row_is_its_own_collapsed_disclosure() -> None:
    """E2: 69 reasons + None x EN/JA x anchorings x evidence; parsed row structure."""


def test_e3_listings_are_the_hand_stated_lines_and_marks() -> None:
    """E3: per-case line numbers, `at` classes, mark text, gaps, elision, invisible characters."""


def test_e4_each_row_links_its_reference_section() -> None:
    """E4: one a.spec per row; href = language URL + #check-<id>; escaping plant."""


def test_e5_documents_stay_self_contained_and_trigger_free() -> None:
    """E5: one fixed script; href on a.spec alone; no same-origin trigger; size cap."""


def test_e6_untrusted_bytes_enter_through_the_program_alone() -> None:
    """E6: request/name/CSV/stdout/stderr sentinels absent; program sentinel inside .src only."""


def test_e7_each_outlet_arm_passes_the_evidence_it_holds() -> None:
    """E7: per arm EN + JA: program/at/trace presence; the JA URL on a kana request."""


def test_e9b_rendering_work_is_bounded() -> None:
    """E9b: 5,000,000-character programs render fast, capped, identical past the scan cap."""


def test_e9_diagnostics_stay_total_with_evidence() -> None:
    """E9: M16.1 C8 cases rerun with evidence supplied."""
