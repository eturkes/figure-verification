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

M3.2a adds the model-proposer config (base URL / name / timeout / sample rows / max tokens):
the operator points the verifier at the local backend, and these stay trusted config too —
the untrusted model never supplies them. __post_init__ bounds them fail-closed alongside the
caps above (see the inline notes for each rejection's downstream failure mode).
"""

import math
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
# Model proposer (M3.2a): the local backend's OpenAI /v1 base (M3.1b binds port 8001; the
# client appends /chat/completions), the single served model name copied into requests,
# a generation timeout with slow-accelerator headroom, the sample-row count handed to the prompt,
# and the new-token ceiling (matches the backend default, bounds the backend's lock-hold time).
_DEFAULT_MODEL_BASE_URL = "http://127.0.0.1:8001/v1"
_DEFAULT_MODEL_NAME = "Qwen2-0.5B-Instruct-int4-sym-ov"
_DEFAULT_MODEL_TIMEOUT = 120.0
_DEFAULT_MODEL_SAMPLE_ROWS = 5
_DEFAULT_MODEL_MAX_TOKENS = 512


class Settings(msgspec.Struct, frozen=True, kw_only=True):
    """Immutable service configuration. See the module docstring for the trust note."""

    data_dir: Path
    host: str = _DEFAULT_HOST
    port: int = _DEFAULT_PORT
    max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES
    store_cap: int = _DEFAULT_STORE_CAP
    model_base_url: str = _DEFAULT_MODEL_BASE_URL
    model_name: str = _DEFAULT_MODEL_NAME
    model_timeout: float = _DEFAULT_MODEL_TIMEOUT
    model_sample_rows: int = _DEFAULT_MODEL_SAMPLE_ROWS
    model_max_tokens: int = _DEFAULT_MODEL_MAX_TOKENS

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
        # Model-proposer bounds, fail-closed like the caps above. httpx does not validate
        # its timeout, and not every non-None value is bounded, so guard the value itself.
        # A value of 0 times out every request immediately; a negative is an undefined
        # deadline; inf runs unbounded (the wedged-backend hang the timeout prevents); nan
        # poisons the asyncio deadline (ValueError at request time) and slips a bare `<= 0`
        # check. float() parses "inf"/"nan" from the env, so require a finite value > 0. A
        # negative sample-row count is nonsensical for the header+rows prompt slice, and a
        # max_tokens below 1 is not a valid ceiling (the swappable backend clamps to >= 1,
        # but the verifier fails closed itself rather than lean on that).
        if not math.isfinite(self.model_timeout) or self.model_timeout <= 0:
            msg = f"model_timeout must be a finite value > 0, got {self.model_timeout}"
            raise ValueError(msg)
        if self.model_sample_rows < 0:
            msg = f"model_sample_rows must be >= 0, got {self.model_sample_rows}"
            raise ValueError(msg)
        if self.model_max_tokens < 1:
            msg = f"model_max_tokens must be >= 1, got {self.model_max_tokens}"
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
            model_base_url=env.get("VERIFIER_MODEL_BASE_URL", _DEFAULT_MODEL_BASE_URL),
            model_name=env.get("VERIFIER_MODEL_NAME", _DEFAULT_MODEL_NAME),
            model_timeout=float(env.get("VERIFIER_MODEL_TIMEOUT", str(_DEFAULT_MODEL_TIMEOUT))),
            model_sample_rows=int(
                env.get("VERIFIER_MODEL_SAMPLE_ROWS", str(_DEFAULT_MODEL_SAMPLE_ROWS))
            ),
            model_max_tokens=int(
                env.get("VERIFIER_MODEL_MAX_TOKENS", str(_DEFAULT_MODEL_MAX_TOKENS))
            ),
        )
