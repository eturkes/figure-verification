# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""One candidate order and one verdict selection shared by tool and outlet.

Only a target mismatch means a later user-owned artifact might answer the same program. Every
other refusal is final. The formula target comes from the user's request, after attached files.
"""

from verifier.pysrc.request import formula_target
from verifier.pysrc.spec import DatasetTarget, FormulaTarget
from verifier.pysrc.verify import Refused, Verdict, verify_python_source
from webui.paste_in.owui_files import UploadedFile

_TARGET_MISMATCH = "target_mismatch"


def first_verdict(
    program: str, attachments: tuple[UploadedFile, ...], request_text: str | None
) -> tuple[Verdict | None, UploadedFile | None]:
    """Return the first final verdict and the attachment it consumed, if any."""
    formula = formula_target(request_text) if request_text is not None else None
    candidates: tuple[tuple[DatasetTarget | FormulaTarget, UploadedFile | None], ...] = tuple(
        (DatasetTarget(path=file.path, content=file.content), file) for file in attachments
    ) + (((formula, None),) if formula is not None else ())
    outcome: Verdict | None = None
    consumed: UploadedFile | None = None
    for candidate, consumed in candidates:
        outcome = verify_python_source(program, declared_target=candidate)
        if not (isinstance(outcome, Refused) and outcome.code == _TARGET_MISMATCH):
            return outcome, consumed
    return outcome, consumed
