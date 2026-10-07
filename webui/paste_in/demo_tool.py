# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The demo's tool: the production tool under the demo's substitution anchoring (Q37).

The demo keeps Q8's substitution rule, the rule its OWUI ran before Q37, while production
(`paste-in/`) runs strict anchoring. Everything else is the production tool, inherited.
"""

from verifier.pysrc.spec import Anchoring
from webui.paste_in.tool import Tools as ProductionTools


class Tools(ProductionTools):
    """The demo's pasted tool; `draw_figure` is inherited unchanged."""

    _ANCHORING: Anchoring = "substitution"
