# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The demo's filter: the production filter under the demo's anchoring + inlet template.

The demo keeps Q8's substitution rule, the rule its OWUI ran before Q37, while production
(`paste-in/`) runs strict anchoring. Everything else is the production filter, inherited.
"""

from verifier.pysrc.spec import Anchoring
from webui.paste_in.capture_template import CAPTURE_TEMPLATE
from webui.paste_in.filter import Filter as ProductionFilter


class Filter(ProductionFilter):
    """The demo's global filter; the inlet and outlet are inherited unchanged."""

    _ANCHORING: Anchoring = "substitution"
    # The demo adapter wraps a bare-source reply as the tool call, so its template asks for one.
    _TEMPLATE: str = CAPTURE_TEMPLATE
