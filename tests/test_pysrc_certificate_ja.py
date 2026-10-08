# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M17.2 I1-I4: the core certificate carries a Japanese interpretation beside the English one.

Contract: `.agent/contracts/m17u2.md`. Skeleton: each body is a module-level skip naming M17.2.
"""

import pytest

pytestmark = pytest.mark.skip(reason="M17.2 skeleton: the tester fills each body from the contract")


def test_i1_field_set_gains_interpretation_ja_last() -> None:
    """I1: the pre-unit 11 field names + interpretation_ja, in order, hand-stated."""


def test_i2_japanese_bytes_per_branch() -> None:
    """I2: column pair x4 marks, aggregate x4 reductions (one barh), formula x4 bounds, labels."""


def test_i3_english_bytes_unchanged_per_branch() -> None:
    """I3: the I2 branch set in English, hand-stated; the K6 witnesses unchanged."""


def test_i4_japanese_text_is_model_free_and_total() -> None:
    """I4: no submitted identifier survives; prefix on every Verified; closed maps exact-key."""
