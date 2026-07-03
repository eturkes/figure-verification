# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Service settings — trusted operator config for the HTTP transport (M2.1).

A frozen container struct, never decoded from an untrusted body (unlike the schema
structs): the operator supplies it through the environment before the process binds.
data_dir stays trusted config — checks.py path confinement rests on it (the TOCTOU
precondition documented there). Defaults bind loopback only and cap bodies far under
the VPlot schema's real size, and __post_init__ rejects a non-positive max_body_bytes
(which the framework would otherwise read as an unlimited body) or store_cap (which would
make the artifact store drop every render at once or crash on its first eviction), so a
bare or misconfigured deploy fails closed rather than exposing the verifier. The field defaults
and the from_env fallbacks share one set of constants so the two construction paths
cannot drift.
"""

import os
from pathlib import Path
from typing import Self

import msgspec

_DEFAULT_DATA_DIR = "data"
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000
# Real specs are far under 64 KiB (VPlot schema bounds); the cap raises 413 when an
# oversize body is read (M2.2 reads the raw body before any verifier work).
_DEFAULT_MAX_BODY_BYTES = 65536
_DEFAULT_STORE_CAP = 256


class Settings(msgspec.Struct, frozen=True, kw_only=True):
    """Immutable service configuration. See the module docstring for the trust note."""

    data_dir: Path
    host: str = _DEFAULT_HOST
    port: int = _DEFAULT_PORT
    max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES
    store_cap: int = _DEFAULT_STORE_CAP

    def __post_init__(self) -> None:
        # A non-positive cap is falsy, so Litestar reads it as an unlimited body
        # (`... or math.inf`) and the fail-closed guard silently vanishes; reject it
        # here on every construction path (direct and from_env).
        if self.max_body_bytes < 1:
            msg = f"max_body_bytes must be >= 1, got {self.max_body_bytes}"
            raise ValueError(msg)
        # A non-positive store_cap makes the bounded artifact store drop every render at
        # once (cap 0) or crash on its first eviction (cap < 0); reject it here too.
        if self.store_cap < 1:
            msg = f"store_cap must be >= 1, got {self.store_cap}"
            raise ValueError(msg)

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
