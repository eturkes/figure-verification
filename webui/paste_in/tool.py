# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The one model-visible operation: a program in, a fixed string out.

Transport, never authority. The method records the model's exact program bytes, the chat's
attachment ids (the outlet re-resolves each against the requesting user), the request text and the
admin's aliases in backend request state, and returns one fixed string. It runs nothing and decides
nothing: the outlet filter runs the recorded program in the user's browser and judges the finished
figure, and only that outlet may publish (tool-call-only PASS transport).

`Tools` is Open WebUI's fixed entry name; it instantiates the class once and exposes every public
method to the model (`utils/plugin.py`, `utils/tools.py`), so a helper here must stay private or it
becomes a second operation. The reserved `__…__` parameters are injected by Open WebUI and are
absent from the model-facing schema: pydantic's `create_model` drops a leading-underscore field
name, and `get_tools()` strips the same names again before the spec reaches the model.

`Valves` = the admin's settings (Q43: column aliases). Open WebUI builds it on every save
(`Valves(**form)`, a failed validation refuses the save) and on every load, and sets it on the
instance only when the instance already holds `valves`; the model never supplies it. The tool
records the parsed aliases in its receipt, so the outlet's verdict reads the same aliases.
`pydantic` is part of the Open WebUI image, as `open_webui` is.
"""

from pydantic import BaseModel, Field, field_validator

from webui.paste_in.aliases import parse_aliases
from webui.paste_in.owui_files import attachment_ids
from webui.paste_in.receipt import Receipt, write_receipt
from webui.paste_in.verdicts import CHART_SENT


def _request_text(metadata: dict[str, object] | None) -> str | None:
    user_message = (metadata or {}).get("user_message")
    if not isinstance(user_message, dict):
        return None
    content = user_message.get("content")
    return content if isinstance(content, str) else None


class Tools:
    """The pasted tool. One public method, so the model sees one operation."""

    class Valves(BaseModel):
        """The admin's settings for this tool."""

        column_aliases: str = Field(
            default="",
            description=(
                "Other names for CSV columns, one line per column: column = alias, alias."
                " A request or chart label that writes an alias names its column."
            ),
        )

        @field_validator("column_aliases")
        @classmethod
        def check_column_aliases(cls, value: str) -> str:
            """Refuse the save of text that `parse_aliases` cannot read."""
            parse_aliases(value)
            return value

    def __init__(self) -> None:
        self.valves = self.Valves()

    async def draw_figure(
        self,
        program: str,
        __metadata__: dict[str, object] | None = None,
        __request__: object | None = None,
    ) -> str:
        """Draw one chart with matplotlib from a complete Python program.

        Plot only values from the attached CSV file or numbers written in the request, as they
        are or as one total, mean, minimum, maximum or row count per group. Keep the chart honest:
        bars and filled areas start at zero, axes stay linear and not inverted, every value stays
        inside the axis limits, each panel has one set of axes, a legend names every series when
        there are two or more, and varying marker sizes or colors have a size legend or a color
        bar. The reply shows the chart only when it follows these rules.

        :param program: The complete Python program that draws the chart.
        """
        if __request__ is not None:
            write_receipt(
                __request__,
                Receipt(
                    program,
                    tuple(attachment_ids(__metadata__)),
                    _request_text(__metadata__),
                    parse_aliases(self.valves.column_aliases),
                ),
            )
        return CHART_SENT
