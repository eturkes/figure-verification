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
    """One chat message. role is the closed set {system, user, assistant}, enforced at decode
    (an unknown role — e.g. a control-token string — is rejected 400, never rendered into the
    chat template); content is text (this PoC is text-only, no multimodal content array). The
    set matches this proposer's traffic (the M3.2 client sends system+user, the reply is
    assistant); widen it if a tool/multimodal role is ever needed. Content-level control tokens
    are NOT sanitized here — harmless, since the verifier re-decodes every reply strictly."""

    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionRequest(msgspec.Struct, frozen=True, kw_only=True):
    """An OpenAI chat-completion request (unknown fields tolerated — see module docstring).

    Schema-guided (constrained) decoding is opt-in per request via guided_json: verifier's
    proposeSpec sets it true to force valid VPlot structure, while generic OpenAI/OWUI callers omit
    it (default false) and stay unconstrained.

    messages is required and non-empty; model/temperature/max_tokens are optional (the server
    supplies model_name, greedy temperature 0, the configured max_tokens ceiling). temperature
    is bounded to OpenAI's [0, 2] at decode (a negative would silently mean greedy, an absurd
    value feeds the sampler garbage → both rejected 400); an out-of-range max_tokens is instead
    clamped by the handler (a token bound has a sane in-range meaning).
    """

    messages: Annotated[tuple[ChatMessage, ...], msgspec.Meta(min_length=1)]
    model: str | None = None
    temperature: Annotated[float, msgspec.Meta(ge=0.0, le=2.0)] = 0.0
    max_tokens: int | None = None
    guided_json: bool = False


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
    """An OpenAI-style error envelope. The verifier recognizes only canonical HTTP-400
    ``prompt_too_long`` as policy refusal; every other non-success shape is an upstream fault."""

    error: ErrorDetail
