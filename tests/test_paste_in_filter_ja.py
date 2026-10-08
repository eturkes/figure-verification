# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M17.2 I5-I6: a kana request's PASS reply carries the Japanese interpretation.

Contract: `.agent/contracts/m17u2.md`. Skeleton: each body is a module-level skip naming M17.2.
"""

import pytest

pytestmark = pytest.mark.skip(reason="M17.2 skeleton: the tester fills each body from the contract")


def test_i5_pass_reply_language_follows_the_request() -> None:
    """I5: dataset + formula PASS x (kana, kanji-only, ASCII, non-dict metadata); FAIL untouched."""


def test_i6_differential_expects_the_language_from_its_own_rule() -> None:
    """I6: oracle's own kana rule; content + output compared exactly."""
