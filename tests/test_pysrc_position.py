# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M18.1 P1-P9: refusal places + the statement-role trace, positions only, no source bytes.

Contract: `.agent/contracts/m18u1.md`. Skeleton: each body is a module-level skip naming M18.1.
"""

import pytest

pytestmark = pytest.mark.skip(reason="M18.1 skeleton: the tester fills each body from the contract")


def test_p1_role_span_step_vocabulary_is_hand_stated() -> None:
    """P1: the 10 roles in order; Span + Step field names in order; stdlib imports alone."""


def test_p2_every_emitted_span_is_valid_and_verify_never_raises() -> None:
    """P2: line/column bounds over universal-newline pieces + UTF-8 boundaries; Hypothesis."""


def test_p3_prescan_places() -> None:
    """P3: one Span literal per prescan row; byte != char column; bare CR; NEL; EOF string."""


def test_p4_admission_places() -> None:
    """P4: innermost instrumented node; statement fallback; `;` joins; SyntaxError ends."""


def test_p5_projection_places() -> None:
    """P5: second mark; labels; terminal; figure; rebound; substituted binding; arm; unused."""


def test_p6_post_projection_places() -> None:
    """P6: source hint for source_not_supplied + dataset target_mismatch; label hints; `()` rest."""


def test_p7_trace_literals() -> None:
    """P7: exact Trace per PASS shape; statement_trace == Verified.trace; Refused.trace rule."""


def test_p8_positions_stay_outside_verdict_identity() -> None:
    """P8: equality + hash ignore `at`/`trace`; default exception fields."""


def test_p9_positions_hold_no_source_bytes() -> None:
    """P9: every `at`/`trace` leaf is an int or a Role member."""
