# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M15.1 D1-D8: the outlet's failure reason -- one status line + one log record per FAIL reply.

Contract: `.agent/contracts/m15u1.md`. Skeleton: each body is a module-level skip naming M15.1.
"""

import pytest

pytestmark = pytest.mark.skip(reason="M15.1 skeleton: the tester fills each body from the contract")


def test_d1_reason_key_set_is_every_refusal_code_plus_the_fourteen_outlet_causes() -> None:
    """D1: key set = get_args(RefusalCode) | 14 hand-stated causes, disjoint."""


def test_d2_every_reason_text_obeys_the_text_law() -> None:
    """D2: EN ASCII + `.` + <=25 words/sentence; JA kana + `。`; no newline/braces; width <=100."""


def test_d2_anchor_texts_are_byte_exact() -> None:
    """D2: the four hand-stated anchors in EN and JA."""


def test_d3_each_arm_yields_its_reason_and_the_fixed_fail_verdict() -> None:
    """D3: one case per arm-map row; content + output = FAIL_TEXT; no files event; RPC count."""


def test_d4_one_status_event_per_fail_and_none_on_pass() -> None:
    """D4: exact event list per row; the status event is last; PASS emits no status event."""


def test_d5_language_follows_kana_in_the_metadata_request_text() -> None:
    """D5: hiragana/half-width katakana -> JA; kanji-only/list/None -> EN; receipt text ignored."""


def test_d6_one_info_record_per_fail_with_sanitized_ids() -> None:
    """D6: exact message on logger webui.paste_in.filter; unsafe ids -> `-`; PASS logs nothing."""


def test_d7_status_and_log_carry_no_untrusted_bytes() -> None:
    """D7: planted stderr/stdout/program/request/file-name/CSV sentinels absent from both."""


def test_d8_a_raising_or_absent_emitter_never_costs_the_verdict() -> None:
    """D8: status emit raising Exception -> FAIL rewrite + record; None emitter -> record only."""
