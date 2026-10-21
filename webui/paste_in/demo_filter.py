# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The demo's filter: the production filter under the demo's anchoring + inlet templates.

The demo keeps Q8's substitution rule, the rule its OWUI ran before Q37, while production
(`paste-in/`) runs strict anchoring. Everything else is the production filter, inherited.
"""

from pydantic import Field

from verifier.figure.anchoring import Anchoring
from webui.paste_in.filter import MODEL_NOTE_DESCRIPTION, MODEL_NOTE_TITLE
from webui.paste_in.filter import Filter as ProductionFilter
from webui.paste_in.templates import DEMO_TEMPLATES, Templates


class Filter(ProductionFilter):
    """The demo's global filter; the inlet and outlet are inherited unchanged."""

    _ANCHORING: Anchoring = "substitution"
    # The demo adapter wraps a bare-source reply as the tool call, so its templates ask for one.
    _TEMPLATES: Templates = DEMO_TEMPLATES

    class Valves(ProductionFilter.Valves):
        """The admin's settings for this filter."""

        # Q78 (user): off in the demo. Its adapter sends the bare program as the call, so the
        # 0.5B model has no note to write.
        model_note: bool = Field(
            default=False, title=MODEL_NOTE_TITLE, description=MODEL_NOTE_DESCRIPTION
        )
