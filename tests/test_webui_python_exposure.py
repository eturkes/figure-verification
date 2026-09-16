# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.0 exposure: python mode is the demo's ONE operation and JSON mode is unreachable.

Contract: `.agent/contracts/m10u0.md` predicate group E. Each docstring carries its predicate's
acceptance check; the check is the test's specification and the contract's wording wins wherever a
body would assert more.

Skeleton: each body is `pytest.skip`, retired at M10.0's close together with this line.

Open WebUI filters the model-visible callable set by `function_name_filter_list` for a tool server
and by the workspace model's attached tool ids for a provisioned tool. Two independent surfaces can
each re-admit `proposeSpec`, so the predicate is stated over the ENUMERATED set rather than over
either surface's configuration.
"""

import pytest

_TRACKER = "owned by **M10.0** (`.agent/spec.md` Deferred)"


def test_e1_model_visible_callable_set_is_exactly_the_python_operation() -> None:
    """E1: the enumerated set equals `{<operation name>}` over settings + provisioned state.

    A re-added tool-server registration fails the test, so JSON mode cannot return by config drift.
    """
    pytest.skip(_TRACKER)


def test_e2_tool_provisioning_converges_to_the_artifact_bytes() -> None:
    """E2: two `ensure_tool` runs leave one row whose content equals the committed artifact.

    Idempotence is the predicate; the second run must update rather than duplicate.
    """
    pytest.skip(_TRACKER)


def test_e3_tool_description_carries_no_admission_vocabulary() -> None:
    """E3: `capture/corpus.py`'s banned-stem regex finds no match in the model-facing description.

    A planted stem fires it. Ruling 6 binds every model-facing string, not only corpus prompts.
    """
    pytest.skip(_TRACKER)


def test_e4_bootstrap_smoke_reports_the_python_tool_attached() -> None:
    """E4: the readback flag is false with the tool row absent and true with it present.

    Smoke proves provisioning took, so a silent provisioning failure cannot read as a demo defect.
    """
    pytest.skip(_TRACKER)
