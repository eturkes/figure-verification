# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The one string the tool returns to the model.

The tool decides nothing: the outlet filter runs the recorded program in the user's browser and
judges the finished figure, so no verdict exists when the tool returns. The string is MODEL-facing;
the strings a USER reads are the filter's (`Intent`), and no surface may depend on the model
narrating a verdict (`.claude/rules/owui.md`).
"""

from typing import Final

CHART_SENT: Final = "The chart program was sent. The reply shows the chart if it passes the checks."
