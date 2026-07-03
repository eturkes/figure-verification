# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Serialized response models for the verifier service (M2.2).

Two shapes cross the transport boundary. Verdict is the verification-outcome envelope,
answered HTTP 200 whether the spec verified, decoded but failed a check, or failed to
decode (a decode failure is an expected model failure mode M3 meters, not transport
misuse). Problem is the RFC 9457 application/problem+json body the app's exception
handlers emit for transport misuse or a server-config fault (wrong content-type, oversize
body, a broken trusted manifest) — never a verification outcome. CheckResult is reused
verbatim from the trusted core (verifier.checks); the transport adds no verdict vocabulary
of its own.
"""

from typing import Literal

import msgspec

from verifier.checks import CheckResult

__all__ = ["Problem", "Verdict"]


class Verdict(msgspec.Struct, frozen=True, kw_only=True):
    """The verification outcome (HTTP 200 regardless of the judgement).

    `layer` names the stage that produced it: "decode" when the raw body failed to decode
    (a lone synthetic spec.decode result), "verify" once decoding passed and the trusted
    pipeline ran (dataset binding, eval, encoding/label). `verified` is true only when
    every result passed. Every field is always present, so no omit_defaults is needed.
    """

    verified: bool
    layer: Literal["decode", "verify"]
    results: tuple[CheckResult, ...]


class Problem(msgspec.Struct, frozen=True, kw_only=True, omit_defaults=True):
    """RFC 9457 problem detail for a transport or server-config fault.

    `type` defaults to the RFC's "about:blank" (omitted when default), `title` is the HTTP
    status reason phrase, `status` the code, `detail` the occurrence-specific message. A
    verification outcome never travels as a Problem — it is always a 200 Verdict.
    """

    title: str
    status: int
    detail: str
    type: str = "about:blank"
