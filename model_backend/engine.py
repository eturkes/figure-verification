# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Transformers engine wrapper — the untrusted local proposer.

Isolates the one untyped native import (transformers; a mypy override in pyproject makes it
resolve to Any so `mypy --strict` type-checks this package without the native runtime present)
and serializes generation behind a single lock: one model, one accelerator. The module imports
NO torch: `dtype=` accepts a string that transformers resolves itself, `generate` is already
decorated `@torch.no_grad()`, and `from_pretrained` already returns an eval-mode module, so
tensors are handled opaquely through `.shape`, slicing and `int()`. Durable API facts:
.agent/reference.md "transformers 5.16.1 pinned behaviours".

- Chat is STATELESS: apply the chat template to the full messages array each call, in ONE
  tokenizing call (`tokenize=True, return_dict=True`). That form tokenizes its own rendered text
  with add_special_tokens=False internally, so no second special-token pass is possible.
- Admission is by IDENTITY: capture input_ids AFTER the device transfer, reject a shape over
  max_prompt_len as ``prompt_too_long`` before any generation call, then forward that exact
  mapping. This stops a string overload from re-templating or retokenizing a different sequence
  after admission.
- Special-token ids come from the MODEL's generation_config, never the tokenizer's config: the
  two disagree on this snapshot, and the model's set is what the stopping criterion uses. The
  engine reads that set for finish-reason classification and passes NO eos override, so one set
  drives both sides.
- No finish reason exists in the transformers API: stopping criteria return bare booleans. The
  caller derives it. A stopping EOS is always the suffix's TERMINAL token (the token is appended
  before criteria run), so classify on the terminal token, never on membership anywhere.
- Bound the emitted RESPONSE size: after generation, reject a decoded reply whose UTF-8 byte
  length exceeds the ceiling (over-cap -> BackendError, read as an upstream fault). A
  post-generation guard on response bytes; max_new_tokens (per call) bounds the work itself.
- Schema guidance is loaded and digested at load, and REFUSED loudly at apply time on this build
  (M12.3 restores the application). Refusal fires after admission, at the former application
  site, so a request's wire outcome stays identical across the two units.
"""

import threading
from collections.abc import Mapping
from typing import Any, Literal, Self, TypeGuard

import msgspec
from transformers import AutoModelForCausalLM, AutoTokenizer

from model_backend.schema_guidance import load_guidance_schema, schema_digest
from model_backend.settings import GuidanceSchemaId, Settings

# transformers resolves this string via getattr(torch, ...) — a module constant, not a settings
# field: fp16 is the sole supported path for the pinned snapshot on the pinned accelerator.
_DTYPE = "float16"
# Closed container domain for token-id metadata. str and bytes are iterable and a generator is
# single-shot; none of them carries token ids, so all three refuse rather than being coerced.
_TOKEN_ID_CONTAINERS = (list, tuple, set, frozenset)


def _is_token_id(value: object) -> TypeGuard[int]:
    """Admit exactly a non-negative, non-bool int.

    bool is an int subclass, so a config reporting False would otherwise bind vocabulary token 0
    as end-of-sequence. No int() coercion anywhere: it would accept floats and numeric text.
    """
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _admit_token_ids(value: object) -> frozenset[int] | None:
    """Normalize a scalar or container of token ids, or None when the value is inadmissible."""
    if _is_token_id(value):
        return frozenset({value})
    if not isinstance(value, _TOKEN_ID_CONTAINERS):
        return None
    admitted: set[int] = set()
    for member in value:
        if not _is_token_id(member):
            return None
        admitted.add(member)
    if not admitted:
        return None
    return frozenset(admitted)


class BackendError(Exception):
    """A backend fault carrying an HTTP status + machine-readable type; app.py renders it as
    an OpenAI-style error body. The verifier recognizes only the exact prompt-too-long protocol
    shape as policy refusal; every other backend error stays an upstream fault."""

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
    """A loaded model + tokenizer guarded by a lock. Build via Engine.load (blocking)."""

    def __init__(  # noqa: PLR0913
        self,
        model: Any,
        tokenizer: Any,
        *,
        device: str,
        eos_ids: frozenset[int],
        pad_token_id: int,
        max_prompt_len: int,
        max_response_bytes: int,
        guidance_schemas: Mapping[GuidanceSchemaId, str] | None = None,
        schema_digests: Mapping[GuidanceSchemaId, str] | None = None,
    ) -> None:
        self._model = model
        self._tok = tokenizer
        self._device = device
        self._eos_ids = eos_ids
        self._pad_token_id = pad_token_id
        self._max_prompt_len = max_prompt_len
        self._max_response_bytes = max_response_bytes
        # Both maps are total over GuidanceSchemaId or both are None: None means guidance is
        # disabled wholesale (settings.structured_output false), never that one mode is missing.
        self._guidance_schemas = guidance_schemas
        self._schema_digests = schema_digests
        # One model on one accelerator: serialize generation. Per-call generation state is
        # deep-copied upstream, but shared mutation exists on cache-length, compile-config and
        # rotary buffers, and the installed source declares no concurrency contract, so
        # re-entrancy stays UNSETTLED BY EVIDENCE and the lock is the safe default.
        self._lock = threading.Lock()

    def schema_sha256(self, schema_id: GuidanceSchemaId) -> str | None:
        """Return that operator schema's raw-byte digest, or None while guidance is disabled.

        Subscripts the loaded map directly: a member of the closed id set is always present, so
        there is no default arm to hide a mode whose schema silently failed to load.
        """
        if self._schema_digests is None:
            return None
        return self._schema_digests[schema_id]

    @classmethod
    def load(cls, settings: Settings) -> Self:
        """Load the tokenizer and the model, then move the model onto settings.device (blocking).
        Raises loudly if the model path, its metadata, or a pinned schema is unusable.

        Order is schemas -> tokenizer -> model -> id normalization -> device transfer, so a schema
        or tokenizer fault costs zero model loads and unusable id metadata costs zero device
        transfers. Both faults are decidable from metadata; deferring them to generation time
        would spend a full host allocation and an accelerator context first.

        local_files_only is NOT what resolves a valid local directory — local resolution already
        precedes every Hub path. It is what keeps a MISSING or typo'd model_dir from being read as
        a Hub repository identifier and reaching the network before it fails.

        Structured guidance is derived once at load when settings.structured_output is enabled —
        for EVERY operator-pinned schema, so a mode can never be selected at request time and find
        its schema unloaded. A missing, unreadable, or invalid JSON schema aborts loading rather
        than silently serving unconstrained output.
        """
        if settings.structured_output:
            paths = settings.guidance_schema_paths()
            guidance_schemas = {sid: load_guidance_schema(path) for sid, path in paths.items()}
            # Intentionally re-read raw bytes after parsing: tiny static files, blocking load path.
            schema_digests = {sid: schema_digest(path) for sid, path in paths.items()}
        else:
            guidance_schemas = None
            schema_digests = None
        model_dir = str(settings.model_dir)
        tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
        model = AutoModelForCausalLM.from_pretrained(model_dir, dtype=_DTYPE, local_files_only=True)
        # The generation config is the stopping criterion's own authority. Reading the tokenizer's
        # ids instead can only NARROW that set — this snapshot's tokenizer names one EOS while the
        # model names two — which would misreport a terminal drop of the unnamed id as "length".
        generation_config = model.generation_config
        eos_ids = _admit_token_ids(generation_config.eos_token_id)
        if eos_ids is None:
            msg = "model generation config declares no usable eos_token_id"
            raise BackendError(msg, status=500, error_type="generation_config_unusable")
        # Deliberate asymmetry: EOS refuses, PAD degrades. EOS is load-bearing twice (finish-reason
        # classification AND the stopping criterion) while PAD only fills masked positions that a
        # single unpadded sequence never generates into, and it has a principled fallback.
        # min() rather than the library's own first-element pick: order-independent, reproducible.
        declared_pad: Any = generation_config.pad_token_id
        pad_token_id: int = declared_pad if _is_token_id(declared_pad) else min(eos_ids)
        return cls(
            model.to(settings.device),
            tokenizer,
            device=settings.device,
            eos_ids=eos_ids,
            pad_token_id=pad_token_id,
            max_prompt_len=settings.max_prompt_len,
            max_response_bytes=settings.max_response_bytes,
            guidance_schemas=guidance_schemas,
            schema_digests=schema_digests,
        )

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        guided_schema: GuidanceSchemaId | None,
    ) -> GenResult:
        """Generate one completion for the full messages array (stateless chat template).

        Serialized behind the lock (one tokenizer/model/accelerator). Greedy when temperature == 0
        — do_sample False alone does not defeat beam, constrained or contrastive modes, so
        num_beams is pinned too, and temperature is passed only when sampling. Raises BackendError
        before generation if the exact templated prompt exceeds the token ceiling or if the request
        names a guidance schema, and after generation if decoded text exceeds the response-byte
        ceiling.

        No eos override reaches generate: the model's own generation_config already carries the
        authoritative set, and this method classifies against that same set.
        """
        with self._lock:
            # apply_chat_template / generate / decode come from the Any-typed native module;
            # annotate each extracted value to keep the boundary well-typed.
            admitted: Any = self._tok.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_tensors="pt",
                return_dict=True,
            ).to(self._device)
            if "input_ids" not in admitted:
                msg = "chat template produced no input_ids"
                raise BackendError(msg, status=500, error_type="tokenizer_unusable")
            # Captured AFTER the transfer: a device change rebuilds every mapped tensor, so the
            # pre-transfer object is not the one generation would receive. Identity holds from
            # here to the handoff; every companion key is forwarded unchanged.
            input_ids: Any = admitted["input_ids"]
            prompt_tokens = int(input_ids.shape[-1])
            if prompt_tokens > self._max_prompt_len:
                msg = f"tokenized prompt exceeds the {self._max_prompt_len}-token ceiling"
                raise BackendError(msg, status=400, error_type="prompt_too_long")
            if guided_schema is not None:
                # Fires at the former application site, AFTER admission: M12.3 restores guidance
                # here, so an over-cap-plus-guided request keeps the same wire outcome across both
                # units. Status 500 with its own type keeps this an upstream fault — 400 +
                # prompt_too_long is the only shape the verifier maps to a policy refusal.
                msg = f"schema guidance is not available on this backend build: {guided_schema}"
                raise BackendError(msg, status=500, error_type="guidance_unavailable")
            options: dict[str, Any] = {
                "do_sample": temperature > 0,
                "num_beams": 1,
                "max_new_tokens": max_tokens,
                "pad_token_id": self._pad_token_id,
            }
            if options["do_sample"]:
                options["temperature"] = temperature
            output: Any = self._model.generate(**admitted, **options)
            # Decoder-only output is prompt+suffix and the caller's tensor is never mutated.
            suffix: Any = output[0, prompt_tokens:]
            completion_tokens = int(suffix.shape[-1])
            text: str = self._tok.decode(suffix, skip_special_tokens=True)
            # A stopping EOS lands as the terminal token, so an EOS arriving exactly at the cap
            # means the model finished ("stop"); only a suffix that reached the cap WITHOUT one
            # was cut by it. Guard the empty suffix before indexing.
            stopped = completion_tokens > 0 and int(suffix[-1]) in self._eos_ids
        if len(text.encode("utf-8")) > self._max_response_bytes:
            msg = f"generated response exceeded the {self._max_response_bytes}-byte ceiling"
            raise BackendError(msg, status=500, error_type="response_too_large")
        finish_reason: Literal["stop", "length"] = (
            "length" if not stopped and completion_tokens >= max_tokens else "stop"
        )
        return GenResult(
            text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            finish_reason=finish_reason,
        )
