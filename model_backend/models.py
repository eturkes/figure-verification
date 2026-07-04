# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""OpenAI-shaped request/response models for the local backend (M3.1b).

A minimal subset of the OpenAI Chat Completions + Models schema — enough for the M3.2
verifier client (and, later, Open WebUI) to talk to the local proposer. The REQUEST struct
deliberately does NOT forbid unknown fields: this is an OpenAI-compatible endpoint and
callers send extra params (stream, top_p, ...) the backend simply ignores. That tolerance is
NOT a trust weakening — this backend is the untrusted proposer; the verifier re-decodes every
reply with the strict VPlot decoder (POC_SCOPE). RESPONSE structs are built here and
serialized by Litestar's msgspec encoder.

Arrays are tuples (deeply immutable + hashable — the msgspec house rule; see memory Stack).
temperature is a real float here (unlike VPlot specs, which forbid floats): msgspec strict
accepts a JSON int token for a float field (0 -> 0.0), so a caller may send either.
"""

from typing import Annotated, Literal

import msgspec

__all__ = [
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "ChatMessage",
    "Choice",
    "ErrorDetail",
    "ErrorResponse",
    "ModelCard",
    "ModelList",
    "Usage",
]


class ChatMessage(msgspec.Struct, frozen=True, kw_only=True):
    """One chat message. role in {system,user,assistant}; content is text (this PoC is
    text-only — a structured/multimodal content array is out of scope)."""

    role: str
    content: str


class ChatCompletionRequest(msgspec.Struct, frozen=True, kw_only=True):
    """An OpenAI chat-completion request (unknown fields tolerated — see module docstring).

    messages is required and non-empty; model/temperature/max_tokens are optional (the server
    supplies model_name, greedy temperature 0, and the configured max_tokens ceiling).
    """

    messages: Annotated[tuple[ChatMessage, ...], msgspec.Meta(min_length=1)]
    model: str | None = None
    temperature: float = 0.0
    max_tokens: int | None = None


class Choice(msgspec.Struct, frozen=True, kw_only=True):
    """One completion choice. finish_reason is "stop" (hit EOS) or "length" (hit the cap)."""

    index: int
    message: ChatMessage
    finish_reason: str


class Usage(msgspec.Struct, frozen=True, kw_only=True):
    """Token accounting (prompt + completion tokens, from the pipeline's perf metrics)."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(msgspec.Struct, frozen=True, kw_only=True):
    """A non-streaming chat-completion response. `object` is the OpenAI type marker."""

    id: str
    created: int
    model: str
    choices: tuple[Choice, ...]
    usage: Usage
    object: Literal["chat.completion"] = "chat.completion"


class ModelCard(msgspec.Struct, frozen=True, kw_only=True):
    """One entry in the /v1/models listing."""

    id: str
    created: int
    object: Literal["model"] = "model"
    owned_by: str = "openvino"


class ModelList(msgspec.Struct, frozen=True, kw_only=True):
    """The /v1/models response: the single served model."""

    data: tuple[ModelCard, ...]
    object: Literal["list"] = "list"


class ErrorDetail(msgspec.Struct, frozen=True, kw_only=True, omit_defaults=True):
    """The inner body of an OpenAI-style error (message + machine-readable type)."""

    message: str
    type: str
    param: str | None = None
    code: str | None = None


class ErrorResponse(msgspec.Struct, frozen=True, kw_only=True):
    """An OpenAI-style error envelope. Emitted for a BackendError; the verifier client reads
    any non-2xx as an upstream fault, so the exact shape is informational."""

    error: ErrorDetail
