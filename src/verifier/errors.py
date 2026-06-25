# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The verifier's single failure type.

Every blocking failure raised by the trusted core — data-integrity (ingest, `data.*`),
semantic (eval, `transform.*`/`filter.*`/...), and the M1.5 checks — is a
VerificationError carrying a dotted `.check` name, so a caller categorizes a failure
without parsing the message. Decode/parse failures stay msgspec.ValidationError /
DecodeError (schema.decode_spec, ingest.load_manifest): the parse layer is distinct
from the verify layer (VPlot_SEMANTICS.md section 9, error layers).
"""


class VerificationError(Exception):
    """A verification check failed; the spec must be blocked, not rendered.

    `check` is the dotted check name (e.g. "data.numeric_value", "filter.value_type")
    that failed — the machine-readable category behind the human-readable message.
    """

    def __init__(self, message: str, *, check: str) -> None:
        super().__init__(message)
        self.check = check
