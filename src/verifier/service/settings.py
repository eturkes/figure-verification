# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Service settings — trusted operator config for the HTTP transport (M2.1).

A frozen container struct, never decoded from an untrusted body (unlike the schema
structs): the operator supplies it through the environment before the process binds.
data_dir stays trusted config — checks.py path confinement rests on it (the TOCTOU
precondition documented there). Defaults bind loopback only and cap bodies far under
the VPlot schema's real size, so a bare or misconfigured deploy fails closed rather
than exposing the verifier. The field defaults and the from_env fallbacks share one
set of constants so the two construction paths cannot drift.
"""

import os
from pathlib import Path
from typing import Self

import msgspec

_DEFAULT_DATA_DIR = "data"
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000
# Real specs are far under 64 KiB (VPlot schema bounds); the cap lets the framework
# reject oversize bodies at the edge (413) before any handler runs.
_DEFAULT_MAX_BODY_BYTES = 65536
_DEFAULT_STORE_CAP = 256


class Settings(msgspec.Struct, frozen=True, kw_only=True):
    """Immutable service configuration. See the module docstring for the trust note."""

    data_dir: Path
    host: str = _DEFAULT_HOST
    port: int = _DEFAULT_PORT
    max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES
    store_cap: int = _DEFAULT_STORE_CAP

    @classmethod
    def from_env(cls) -> Self:
        """Build from VERIFIER_* environment variables, falling back to the field defaults."""
        env = os.environ
        return cls(
            data_dir=Path(env.get("VERIFIER_DATA_DIR", _DEFAULT_DATA_DIR)),
            host=env.get("VERIFIER_HOST", _DEFAULT_HOST),
            port=int(env.get("VERIFIER_PORT", str(_DEFAULT_PORT))),
            max_body_bytes=int(env.get("VERIFIER_MAX_BODY_BYTES", str(_DEFAULT_MAX_BODY_BYTES))),
            store_cap=int(env.get("VERIFIER_STORE_CAP", str(_DEFAULT_STORE_CAP))),
        )
