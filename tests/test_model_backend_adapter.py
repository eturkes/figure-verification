# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.6 the demo-only backend adapter wraps the selector turn's bare source as one tool call.

Contract: `.agent/contracts/m10u6.md`. Each docstring carries its predicate's acceptance check; the
check is the test's specification and the contract's wording wins wherever a body would assert
more.

Skeleton: each body is `pytest.skip`, retired at M10.6's close together with this line.
"""

import pytest


def test_x4_adapter_wraps_the_selector_turn_as_one_draw_figure_call() -> None:
    """X4: `model_backend/app.py` recognizes ONLY OWUI's legacy selector turn (a system message
    holding `Available Tools:` + ONE user message `Query: <P>` or
    `History:\\n<lines>\\nQuery: <P>`), generates from ONE user message = the text after the LAST
    `Query: ` with the capture request's
    generation parameters (`capture.harness` `DEFAULT_MAX_TOKENS` = 512, `DEFAULT_TEMPERATURE` =
    0.0, no guided schema), de-fences through `capture.harness.defence`, and replies
    `{"tool_calls":[{"name":"draw_figure","parameters":{"program": <source>}}]}` via `json.dumps`,
    the parsed `program` byte-equal to the de-fenced source. Every other turn is unchanged. The
    reply is never empty.

    Accept: round-trip tests over newline/backslash/Unicode/brace sources; a history whose earlier
    text contains `Query: ` extracts the LAST segment; a non-selector turn reaches
    `engine.generate` with its messages intact.
    """
    pytest.skip("owned by **M10.6** (`.agent/spec.md` Deferred)")
