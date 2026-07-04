# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""OpenVINO GenAI engine wrapper — the untrusted local proposer (M3.1b).

Isolates the one untyped native import (openvino_genai; a mypy override in pyproject makes it
resolve to Any so `mypy --strict` type-checks this package without the native runtime present)
and serializes generation behind a single lock: one compiled LLMPipeline, one iGPU. Transcribes
the gate-validated recipe in .agent/m3_1_design.md — cross-check that doc, do not re-derive:

- Chat is STATELESS: apply the chat template to the full messages array each call (never
  start_chat/finish_chat, which keep server-side history — wrong for OpenAI /v1).
- Start from the model's BUNDLED GenerationConfig and mutate in place; a fresh
  GenerationConfig() drops eos/stop tokens and defaults max_new_tokens to 2**64-1.
- Greedy when temperature == 0 (the deterministic proposer path M3.2 uses); do_sample alone
  leaves temperature at 1.0, so set cfg.temperature only when sampling.
- Bound the emitted RESPONSE size: after generation, reject a decoded reply whose UTF-8 byte
  length exceeds the ceiling (over-cap -> BackendError, read as an upstream fault). A
  post-generation guard on response bytes; max_new_tokens (per call) bounds the work itself.
"""

import threading
from typing import Any, Literal, Self

import msgspec
import openvino_genai as ov_genai

from model_backend.settings import Settings


class BackendError(Exception):
    """A backend fault carrying an HTTP status + machine-readable type; app.py renders it as
    an OpenAI-style error body. The verifier client treats any non-2xx as an upstream fault
    (POC_SCOPE error split), so this is how an over-cap generation reaches the client."""

    def __init__(self, message: str, *, status: int, error_type: str) -> None:
        super().__init__(message)
        self.status = status
        self.error_type = error_type


class GenResult(msgspec.Struct, frozen=True, kw_only=True):
    """One generation: decoded text, token usage, and a finish reason ("stop" hit EOS,
    "length" hit the max_tokens cap)."""

    text: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: Literal["stop", "length"]


class Engine:
    """A loaded LLMPipeline guarded by a lock. Build via Engine.load (blocking compile)."""

    def __init__(self, pipe: Any, tokenizer: Any, *, max_response_bytes: int) -> None:
        self._pipe = pipe
        self._tok = tokenizer
        self._max_response_bytes = max_response_bytes
        # One compiled pipeline on one GPU: serialize generation. Re-entrancy was not probed
        # (see memory M3); the lock is the safe default.
        self._lock = threading.Lock()

    @classmethod
    def load(cls, settings: Settings) -> Self:
        """Compile the model onto settings.device (blocking; ~seconds, slower on a cold GPU
        kernel cache). Raises loudly if the model path or device is unusable."""
        pipe = ov_genai.LLMPipeline(str(settings.model_dir), settings.device)
        tokenizer = pipe.get_tokenizer()
        return cls(pipe, tokenizer, max_response_bytes=settings.max_response_bytes)

    def generate(
        self, messages: list[dict[str, str]], *, temperature: float, max_tokens: int
    ) -> GenResult:
        """Generate one completion for the full messages array (stateless chat template).

        Serialized behind the lock (one pipeline, one GPU). Greedy when temperature == 0.
        Raises BackendError if the decoded text exceeds the response-byte ceiling.
        """
        with self._lock:
            # apply_chat_template / generate / perf_metrics come from the Any-typed native
            # module; annotate each extracted value to keep the boundary well-typed.
            prompt: str = self._tok.apply_chat_template(messages, add_generation_prompt=True)
            cfg = self._pipe.get_generation_config()
            cfg.max_new_tokens = max_tokens
            cfg.do_sample = temperature > 0
            if cfg.do_sample:
                cfg.temperature = temperature
            result = self._pipe.generate([prompt], cfg)
            text: str = result.texts[0]
            metrics = result.perf_metrics
            prompt_tokens: int = metrics.get_num_input_tokens()
            completion_tokens: int = metrics.get_num_generated_tokens()
            # Native per-sequence finish reason (authoritative). LENGTH iff the cap truncated
            # the output; a natural EOS landing exactly on max_new_tokens reports STOP, which a
            # completion_tokens>=max_tokens heuristic would mislabel "length". Extract the bool
            # at the boundary (result.finish_reasons is Any from the native module).
            hit_cap: bool = result.finish_reasons[0] == ov_genai.GenerationFinishReason.LENGTH
        if len(text.encode("utf-8")) > self._max_response_bytes:
            msg = f"generated response exceeded the {self._max_response_bytes}-byte ceiling"
            raise BackendError(msg, status=500, error_type="response_too_large")
        # Only LENGTH means the cap cut the reply; STOP/NONE/TOOL_CALL all end on the model's
        # own accord -> "stop" (this backend surfaces text only, no tool-call handling).
        finish_reason: Literal["stop", "length"] = "length" if hit_cap else "stop"
        return GenResult(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=finish_reason,
        )
