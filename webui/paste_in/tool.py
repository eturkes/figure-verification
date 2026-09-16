# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The one model-visible operation: a program in, a fixed string out.

Transport, never authority. The method hands the model's exact bytes and the user's exact uploaded
bytes to `verify_python_source` and reports what that returns. It re-parses nothing, normalizes
nothing and decides nothing -- a second opinion here would be a pass/fail boundary outside the
verifier, which ruling 5 forbids.

Target selection is the one choice it makes, and it moves no boundary because every candidate is a
user artifact and the core decides each one. Zero attachments cannot verify at all. One attachment
gets one call. Several get one call each, in chat order, and the first verdict that is not
`target_mismatch` wins -- so the program's own `read_csv` literal picks the file, decided inside
the core by a byte-for-byte path comparison.

`Tools` is Open WebUI's fixed entry name; it instantiates the class once and exposes every public
method to the model (`utils/plugin.py`, `utils/tools.py`), so a helper here must stay private or it
becomes a second operation. The reserved `__…__` parameters are injected by Open WebUI and are
absent from the model-facing schema: pydantic's `create_model` drops a leading-underscore field
name, and `get_tools()` strips the same names again before the spec reaches the model.

Publication is the outlet filter's, not this return value: only a backend-recorded tool call may
publish a figure (transport ruling), and the filter re-derives the verdict from that record.
"""

from verifier.pysrc.spec import DatasetTarget
from verifier.pysrc.verify import Refused, Verdict, Verified, verify_python_source
from webui.paste_in.owui_files import UploadedFile, uploaded_files
from webui.paste_in.verdicts import CHART_NOT_PRODUCED, CHART_PRODUCED

# The one code that says "right program, wrong file": it is the only verdict that another
# attachment could still answer, so it alone keeps the loop going.
_TARGET_MISMATCH = "target_mismatch"


def _first_verdict(program: str, attachments: tuple[UploadedFile, ...]) -> Verdict | None:
    """The first verdict about the file the program named, else the last mismatch, else nothing."""
    outcome: Verdict | None = None
    for attachment in attachments:
        outcome = verify_python_source(
            program,
            declared_target=DatasetTarget(path=attachment.path, content=attachment.content),
        )
        if not (isinstance(outcome, Refused) and outcome.code == _TARGET_MISMATCH):
            return outcome
    return outcome


class Tools:
    """The pasted tool. One public method, so the model sees one operation."""

    async def draw_figure(
        self,
        program: str,
        __metadata__: dict[str, object] | None = None,
        __user__: dict[str, object] | None = None,
    ) -> str:
        """Draw a chart from a complete Python program over the attached CSV file.

        :param program: The complete Python program that draws the chart.
        """
        user_id = (__user__ or {}).get("id")
        if not isinstance(user_id, str):
            return CHART_NOT_PRODUCED
        attachments = await uploaded_files(__metadata__, user_id)
        verdict = _first_verdict(program, attachments)
        return CHART_PRODUCED if isinstance(verdict, Verified) else CHART_NOT_PRODUCED
