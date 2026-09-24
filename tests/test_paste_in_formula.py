# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.4 the tool's formula candidate.

Contract: `.agent/contracts/m10u4.md` predicate group T. Each docstring carries its
predicate's acceptance check; the check is the test's specification and the contract's wording
wins wherever a body would assert more.

Skeleton: each body is `pytest.skip`, retired at M10.4's close together with this line.
"""

import pytest


def test_t7_candidates_the_owned_attachments_in_chat() -> None:
    """T7: Candidates = the owned attachments in chat order, then the request's formula target LAST;
    the scan is unchanged (first non-`target_mismatch` verdict wins).

    Accept: Dataset program + matching CSV + a formula carrier → produced; a formula-first-order
    mutant → red. Formula program + unrelated CSV + carrier → produced.
    """
    pytest.skip("owned by **M10.4** (`.agent/spec.md` Deferred)")


def test_t8_the_request_text_metadata_user_message() -> None:
    """T8: The request text = `__metadata__["user_message"]["content"]` when it is a `str`, else no
    formula target. Nothing else reaches `formula_target`: not `__messages__`, not the program, not
    file bytes, not earlier turns.

    Accept: Spy: called once with exactly that string; carriers planted in the program, an assistant
    message or `__messages__` → no target.
    """
    pytest.skip("owned by **M10.4** (`.agent/spec.md` Deferred)")


def test_t9_a_formula_program_needs_no_attachment() -> None:
    """T9: A formula program needs no attachment: zero attachments + a valid carrier → `The chart is
    ready.`; no carrier → `No chart was produced.`

    Accept: Both witnesses.
    """
    pytest.skip("owned by **M10.4** (`.agent/spec.md` Deferred)")


def test_t10_the_m10_0_gap_is_closed() -> None:
    """T10: The M10.0 gap is closed: formula program + attached CSV + no carrier → `No chart was
    produced.`

    Accept: Witness red at the M10.0 close revision.
    """
    pytest.skip("owned by **M10.4** (`.agent/spec.md` Deferred)")


def test_t11_paste_in_regenerated_b1_b8_green() -> None:
    """T11: Paste-in regenerated; B1-B8 green; the import surface stays stdlib + `open_webui`
    (`unicodedata`, `re` are stdlib).

    Accept: `tools/generate_paste_in.py --check` rc=0.
    """
    pytest.skip("owned by **M10.4** (`.agent/spec.md` Deferred)")
