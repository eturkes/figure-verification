# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Independent M10.0 tool oracle: authenticated uploads bound to the unmodified core verdict."""

from collections.abc import Mapping, Sequence
from typing import Protocol

from paste_in_support import StoredFile
from verifier.pysrc import DatasetTarget, Verdict, Verified, verify_python_source
from webui.paste_in.verdicts import CHART_NOT_PRODUCED, CHART_PRODUCED


class Verifier(Protocol):
    def __call__(self, source: str, /, *, declared_target: DatasetTarget) -> Verdict: ...


def oracle_draw_figure(
    program: str,
    *,
    user_id: str | None,
    attachments: Sequence[Mapping[str, object]],
    stored: Mapping[str, StoredFile],
    verify: Verifier = verify_python_source,
) -> str:
    """Try owned uploads in chat order; only a path mismatch permits another candidate.

    The metadata item authorizes no bytes or path: only its top-level id selects a row, and the
    ownership-checked row supplies both the filename and its content. No file means no core call.
    """
    if not user_id:
        return CHART_NOT_PRODUCED
    for attachment in attachments:
        file_id = attachment.get("id")
        if not isinstance(file_id, str):
            continue
        row = stored.get(file_id)
        if row is None or row.user_id != user_id:
            continue
        target = DatasetTarget(path=f"/mnt/uploads/{row.filename}", content=row.content)
        verdict = verify(program, declared_target=target)
        if isinstance(verdict, Verified):
            return CHART_PRODUCED
        if verdict.code != "target_mismatch":
            return CHART_NOT_PRODUCED
    return CHART_NOT_PRODUCED
