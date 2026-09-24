# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.6 the launcher banner and the stub speak the sentinel prompts the capture measured.

Contract: `.agent/contracts/m10u6.md`. Each docstring carries its predicate's acceptance check; the
check is the test's specification and the contract's wording wins wherever a body would assert
more.

Skeleton: each body is `pytest.skip`, retired at M10.6's close together with this line.
"""

import pytest


def test_x5_banner_prompts_equal_the_sentinels() -> None:
    """X5 (banner): `webui/launch.sh` `simple_prompt` and `elaborate_prompt` = the two
    `corpus/python/sentinels.json` prompt texts byte for byte (the ` dataset_name: sales.csv`
    suffix goes).

    Accept: a test reads both banner prompts from `webui/launch.sh` and compares them with
    `sentinels.json`.
    """
    pytest.skip("owned by **M10.6** (`.agent/spec.md` Deferred)")


def test_x5_stub_answers_the_rendered_selector_turn() -> None:
    """X5 (stub): `webui/model_stub.py` answers the selector turn whose `Query:` holds the
    INLET-RENDERED sentinel prompt (over `data/sales.csv`) with that sentinel's program from the
    NEW design run as one `draw_figure` call — simple ⇒ the verified program, complicated ⇒ the
    refused program (the M10.1 amendment A4 shape) — and every other turn with prose.

    Accept: F9 tests re-pinned to the rendered selector text.
    """
    pytest.skip("owned by **M10.6** (`.agent/spec.md` Deferred)")
