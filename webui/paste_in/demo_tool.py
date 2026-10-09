# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The demo's tool: the production tool, generated into the demo's own pair (Q37).

The tool decides nothing, so the demo and production tools are the same code; the demo's filter
carries the demo's anchoring rule and inlet templates.
"""

from webui.paste_in.tool import Tools as ProductionTools


class Tools(ProductionTools):
    """The demo's pasted tool; `draw_figure` is inherited unchanged."""
