# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Backend settings — operator config for the local model server (M3.1b).

A frozen container built from MODEL_BACKEND_* env, mirroring the verifier service's Settings
pattern: field defaults and from_env fallbacks share one set of constants (no drift), and
__post_init__ rejects non-positive bounds so a misconfigured deploy fails closed.
This server is the UNTRUSTED proposer, not the trusted verifier, so these bounds guard request
allocation, the single compiled pipeline / lock, and response size, never a verification claim.
Defaults bind loopback on port 8001 (the verifier service defaults to 8000) and target the
NPU (device "NPU") running a symmetric-INT4 export of Qwen2-0.5B: OpenVINO's NPU LLM path
wants symmetric int4 (the stock asymmetric -int4-ov IR fails the NPU VCL compiler — the
leading, not isolated, reason; see .agent/memory.md M3) and compiles to static shapes, so
max_prompt_len caps the prompt the pipeline accepts.
"""

import os
from pathlib import Path
from typing import Self

import msgspec

_DEFAULT_MODEL_DIR = "models/Qwen2-0.5B-Instruct-int4-sym-ov"
_DEFAULT_MODEL_NAME = "Qwen2-0.5B-Instruct-int4-sym-ov"
_DEFAULT_DEVICE = "NPU"
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8001
_DEFAULT_MAX_BODY_BYTES = 128 * 1024
# The NPU compiles to static shapes: max_prompt_len is the largest prompt (in tokens) the
# pipeline accepts. Engine pre-tokenizes every templated prompt and returns prompt_too_long before
# native generation; the verifier maps only that exact protocol shape to policy 422. 1536 clears
# the ~770-token proposer prompt with wide headroom while
# keeping the static allocation small. Passed only for an NPU device (GPU/CPU use dynamic
# shapes and reject the compile property, though Engine still enforces the logical cap there).
_DEFAULT_MAX_PROMPT_LEN = 1536
# A weak proposer's VPlot JSON spec is small; this caps generation both as the per-request
# ceiling and as the fallback when a caller omits max_tokens (the engine always sets
# max_new_tokens — a fresh GenerationConfig would otherwise generate up to 2**64-1 tokens).
_DEFAULT_MAX_TOKENS = 512
# The response-byte ceiling: a belt over the token cap, guarding the single accelerator/lock against
# a generation that outgrows the configured bound (over-cap -> upstream fault at the client).
_DEFAULT_MAX_RESPONSE_BYTES = 65536


class Settings(msgspec.Struct, frozen=True, kw_only=True):
    """Immutable backend configuration. See the module docstring for the trust note."""

    model_dir: Path = Path(_DEFAULT_MODEL_DIR)
    model_name: str = _DEFAULT_MODEL_NAME
    device: str = _DEFAULT_DEVICE
    max_prompt_len: int = _DEFAULT_MAX_PROMPT_LEN
    max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES
    host: str = _DEFAULT_HOST
    port: int = _DEFAULT_PORT
    max_tokens: int = _DEFAULT_MAX_TOKENS
    max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        # A request may omit max_tokens and fall back to this default, so it must be >= 1;
        # it is also the per-request ceiling (see app.py), so 0 would starve every caller.
        if self.max_tokens < 1:
            msg = f"max_tokens must be >= 1, got {self.max_tokens}"
            raise ValueError(msg)
        # A non-positive byte ceiling would reject every reply as over-cap.
        if self.max_response_bytes < 1:
            msg = f"max_response_bytes must be >= 1, got {self.max_response_bytes}"
            raise ValueError(msg)
        # Litestar treats a falsy request cap as unlimited, so zero must fail at startup.
        if self.max_body_bytes < 1:
            msg = f"max_body_bytes must be >= 1, got {self.max_body_bytes}"
            raise ValueError(msg)
        # A non-positive NPU prompt cap would compile a pipeline that accepts no prompt.
        if self.max_prompt_len < 1:
            msg = f"max_prompt_len must be >= 1, got {self.max_prompt_len}"
            raise ValueError(msg)

    @classmethod
    def from_env(cls) -> Self:
        """Build from MODEL_BACKEND_* environment variables, falling back to field defaults."""
        env = os.environ
        return cls(
            model_dir=Path(env.get("MODEL_BACKEND_MODEL_DIR", _DEFAULT_MODEL_DIR)),
            model_name=env.get("MODEL_BACKEND_MODEL_NAME", _DEFAULT_MODEL_NAME),
            device=env.get("MODEL_BACKEND_DEVICE", _DEFAULT_DEVICE),
            max_prompt_len=int(
                env.get("MODEL_BACKEND_MAX_PROMPT_LEN", str(_DEFAULT_MAX_PROMPT_LEN))
            ),
            max_body_bytes=int(
                env.get("MODEL_BACKEND_MAX_BODY_BYTES", str(_DEFAULT_MAX_BODY_BYTES))
            ),
            host=env.get("MODEL_BACKEND_HOST", _DEFAULT_HOST),
            port=int(env.get("MODEL_BACKEND_PORT", str(_DEFAULT_PORT))),
            max_tokens=int(env.get("MODEL_BACKEND_MAX_TOKENS", str(_DEFAULT_MAX_TOKENS))),
            max_response_bytes=int(
                env.get("MODEL_BACKEND_MAX_RESPONSE_BYTES", str(_DEFAULT_MAX_RESPONSE_BYTES))
            ),
        )
