# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.6 the verification core carries no proposer prompt text.

Contract: `.agent/contracts/m10u6.md`. Each docstring carries its predicate's acceptance check; the
check is the test's specification and the contract's wording wins wherever a body would assert
more.

Skeleton: each body is `pytest.skip`, retired at M10.6's close together with this line.
"""

import pytest


def test_g1_verification_core_holds_no_prompt_text() -> None:
    """G1: `src/verifier/**` holds no line of the capture template, no `CAPTURE_PROMPT_SHA256` value
    and no corpus prompt text. The test reads every corpus prompt through `capture.corpus` (design
    + held-out manifests alike) and compares in memory; a failure message names the source file
    and the prompt's row id, never its text.

    Accept: red on a planted DESIGN prompt line and on a planted template line in one
    `src/verifier/pysrc/*.py` file, green on the tree.
    """
    pytest.skip("owned by **M10.6** (`.agent/spec.md` Deferred)")
