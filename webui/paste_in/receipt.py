# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""One backend-owned record of the last model-visible tool call.

The generated paste-ins embed this module in separate namespaces. A tagged built-in tuple crosses
their class-identity boundary; the reader validates its shape and accepts no other state value.
"""

from dataclasses import dataclass
from typing import Final

from verifier.figure.anchoring import Aliases

RECEIPT_ATTR: Final = "figure_verification_receipt"
# `/2` carries the admin's column aliases (Q43); a `/1` value decodes to no receipt.
RECEIPT_TAG: Final = "figure-verification-receipt/2"
_RECEIPT_LENGTH = 5
_PAIR = 2


@dataclass(frozen=True, slots=True)
class Receipt:
    """Program, user-owned candidate ids and admin aliases, never a verdict or uploaded bytes."""

    program: str
    file_ids: tuple[str, ...]
    request_text: str | None
    aliases: Aliases


def write_receipt(request: object, receipt: Receipt) -> None:
    """Replace the prior call with a tagged, class-identity-independent value."""
    state = getattr(request, "state", None)
    if state is None:
        return
    setattr(
        state,
        RECEIPT_ATTR,
        (RECEIPT_TAG, receipt.program, receipt.file_ids, receipt.request_text, receipt.aliases),
    )


def read_receipt(request: object) -> Receipt | None:
    """Decode only the backend state's tagged, exactly typed carrier."""
    state = getattr(request, "state", None)
    value = getattr(state, RECEIPT_ATTR, None)
    if type(value) is not tuple or len(value) != _RECEIPT_LENGTH or value[0] != RECEIPT_TAG:
        return None
    _, program, file_ids, request_text, aliases = value
    if (
        type(program) is not str
        or type(file_ids) is not tuple
        or any(type(file_id) is not str for file_id in file_ids)
        or (request_text is not None and type(request_text) is not str)
        or type(aliases) is not tuple
        or any(
            type(pair) is not tuple or len(pair) != _PAIR or any(type(n) is not str for n in pair)
            for pair in aliases
        )
    ):
        return None
    return Receipt(program, file_ids, request_text, aliases)
