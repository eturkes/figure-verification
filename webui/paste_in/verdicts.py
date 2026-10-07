# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The closed string set the tool returns to the model.

Two members, fixed, and no refusal code among them. Five of the 55 closed codes carry the banned
stem `admit` (`call_target_not_admitted`, `keyword_not_admitted`, `statement_not_admitted`,
`attribute_not_admitted`, `assign_target_not_admitted`), so returning a code would teach admission
vocabulary through exactly the surface ruling 6 keeps clean. Nothing needs it either: the outlet
filter re-derives the verdict from the backend-recorded call, never from this reply.

These strings are MODEL-facing. The strings a USER reads are the filter's (`Intent`, ruling 4), and
no surface may depend on the model narrating a verdict (`.claude/rules/owui.md`).
"""

CHART_PRODUCED = "The chart is ready."
CHART_NOT_PRODUCED = "No chart was produced."

TOOL_VERDICTS = frozenset({CHART_PRODUCED, CHART_NOT_PRODUCED})
