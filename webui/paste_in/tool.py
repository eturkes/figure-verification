# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The one model-visible operation: a program in, a fixed string out.

Transport, never authority. The method hands the model's exact bytes and the user's exact uploaded
bytes to `verify_python_source` and reports what that returns. It re-parses nothing, normalizes
nothing and decides nothing -- a second opinion here would be a pass/fail boundary outside the
verifier, which ruling 5 forbids.

Target selection is the one choice it makes, and it moves no boundary because every candidate is a
user artifact and the core decides each one. Owned attachments are tried in chat order; the formula
target parsed from the user's own request follows them. The first verdict other than
a `target_mismatch` wins. No program byte or assistant message supplies the formula target.

`Tools` is Open WebUI's fixed entry name; it instantiates the class once and exposes every public
method to the model (`utils/plugin.py`, `utils/tools.py`), so a helper here must stay private or it
becomes a second operation. The reserved `__…__` parameters are injected by Open WebUI and are
absent from the model-facing schema: pydantic's `create_model` drops a leading-underscore field
name, and `get_tools()` strips the same names again before the spec reaches the model.

Publication is the outlet filter's, not this return value: only a backend-recorded tool call may
publish a figure (transport ruling), and the filter re-derives the verdict from that record.
"""

from verifier.pysrc.verify import Verified
from webui.paste_in.owui_files import uploaded_files
from webui.paste_in.receipt import Receipt, write_receipt
from webui.paste_in.selection import first_verdict
from webui.paste_in.verdicts import CHART_NOT_PRODUCED, CHART_PRODUCED


def _request_text(metadata: dict[str, object] | None) -> str | None:
    user_message = (metadata or {}).get("user_message")
    if not isinstance(user_message, dict):
        return None
    content = user_message.get("content")
    return content if isinstance(content, str) else None


class Tools:
    """The pasted tool. One public method, so the model sees one operation."""

    async def draw_figure(
        self,
        program: str,
        __metadata__: dict[str, object] | None = None,
        __user__: dict[str, object] | None = None,
        __request__: object | None = None,
    ) -> str:
        """Draw a chart from a complete Python program over the attached CSV file.

        :param program: The complete Python program that draws the chart.
        """
        user_id = (__user__ or {}).get("id")
        request_text = _request_text(__metadata__)
        attachments = (
            await uploaded_files(__metadata__, user_id) if isinstance(user_id, str) else ()
        )
        if __request__ is not None:
            write_receipt(
                __request__,
                Receipt(
                    program,
                    tuple(attachment.file_id for attachment in attachments),
                    request_text,
                ),
            )
        if not isinstance(user_id, str):
            return CHART_NOT_PRODUCED
        verdict, _consumed = first_verdict(program, attachments, request_text)
        return CHART_PRODUCED if isinstance(verdict, Verified) else CHART_NOT_PRODUCED
