# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Transformers engine wrapper — the untrusted local proposer.

Isolates the untyped native imports (transformers and xgrammar; mypy overrides in pyproject make
both resolve to Any so `mypy --strict` type-checks this package without the native runtime
present) and serializes generation behind a single lock: one model, one accelerator. Tests
therefore install TWO `sys.modules` fakes here, not one. The module states NO torch import:
`dtype=` accepts a string that transformers resolves itself, `generate` is already decorated
`@torch.no_grad()`, and `from_pretrained` already returns an eval-mode module, so tensors stay
opaque behind `.shape`, slicing and `int()`. That is a rule about this module's own import
statements — `import xgrammar` pulls torch in transitively and always has. Durable API facts:
.agent/reference.md "transformers 5.16.1 pinned behaviours" + "xgrammar 0.2.3 pinned behaviours".

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
- Schema guidance is loaded, digested and COMPILED into one grammar per operator-pinned schema at
  load, then applied per request as a fresh logits processor. A compilation fault refuses loudly
  at load rather than degrading to unconstrained output. What the grammar buys is bounded: it
  constrains generation TOWARD the guidance schema, evidenced by the live oracle's named
  witnesses, while strict verifier re-decode remains the sole authority on admission. The grammar
  is compiled from the pattern/format-STRIPPED guidance schema, so guided output can satisfy that
  schema and still be strict-invalid; xgrammar also silently ignores schema keywords it does not
  support — never describe the grammar as enforcing the schema.
"""

import threading
from collections.abc import Mapping
from typing import Any, Literal, Self, TypeGuard

import msgspec
from transformers import AutoModelForCausalLM, AutoTokenizer, LogitsProcessorList
from xgrammar import GrammarCompiler, TokenizerInfo
from xgrammar.contrib.hf import LogitsProcessor

from model_backend.schema_guidance import load_guidance_schema, schema_digest
from model_backend.settings import GuidanceSchemaId, Settings

# transformers resolves this string via getattr(torch, ...) — a module constant, not a settings
# field: fp16 is the sole supported path for the pinned snapshot on the pinned accelerator.
_DTYPE = "float16"
# Closed container domain for token-id metadata. str and bytes are iterable and a generator is
# single-shot; none of them carries token ids, so all three refuse rather than being coerced.
_TOKEN_ID_CONTAINERS = (list, tuple, set, frozenset)
# Longest whitespace run the grammar admits between elements. Unbounded whitespace lets a greedy
# model pad a finished document instead of emitting EOS; 8 still admits ordinary separators and
# shallow indentation, and every measured arm terminated under it.
_MAX_GUIDANCE_WHITESPACE = 8


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


def _compile_guidance(
    tokenizer: Any,
    model: Any,
    guidance_schemas: Mapping[GuidanceSchemaId, str],
    eos_ids: frozenset[int],
) -> dict[GuidanceSchemaId, Any]:
    """Compile one immutable grammar per operator-pinned schema, or refuse loudly.

    Every preparation fault lands on ONE surface (500 ``guidance_unusable``): a schema→grammar
    converter that fails OPEN would leave a green-looking run serving unconstrained output, so
    the whole defense is failing closed here, at load, before the device transfer. Only
    Exception is caught — a BaseException signalling interpreter teardown must still escape.

    Two arguments are load-bearing and are spelled explicitly:

    - ``vocab_size`` comes from the MODEL config, never from len(tokenizer) and never from the
      library default. The default derives its width from the tokenizer (151665 on this
      snapshot, against a declared 151936), then masks 151936-wide scores through a bitmask
      rounded up to 151680 bits and applied WITHOUT a width check, leaving exactly 256 logits
      unconstrained. That failure is silent by construction, so passing the right width is
      necessary but not sufficient: the built width is verified too, and a library version that
      re-derived it internally would refuse here rather than pass every test while guiding
      nothing.
    - ``stop_token_ids`` comes from the same normalized model set that drives finish-reason
      classification. Omitted, xgrammar derives stop ids from the TOKENIZER, whose set is
      NARROWER here — the grammar's termination authority would then disagree with the
      stopping criterion's and could mask an EOS the model relies on.

    The two FORMAT bounds are measured, not chosen. any_order=True reads weaker — properties in
    any order — but it also drops uniqueness and leaves the entry count unbounded above, so an
    endless run of one property is admissible; greedy decoding walks straight into it and neither
    schema terminated within 768 tokens. Unbounded whitespace is the other half: at the library
    default a finished document can still be padded with spaces instead of an EOS. Under
    any_order=False with an 8-character whitespace bound every measured arm stopped inside 217
    tokens and parsed. Both bounds constrain FORMAT alone: strict verifier re-decode still owns
    admission, and the model still chooses every value. strict_mode=True matches the current
    library default and is spelled so a default change cannot silently move guidance strength.
    """
    vocab_size: Any = model.config.vocab_size
    try:
        tokenizer_info: Any = TokenizerInfo.from_huggingface(
            tokenizer,
            vocab_size=vocab_size,
            stop_token_ids=sorted(eos_ids),
        )
    except Exception as exc:
        msg = f"schema guidance could not read the tokenizer: {exc}"
        raise BackendError(msg, status=500, error_type="guidance_unusable") from exc
    if tokenizer_info.vocab_size != vocab_size:
        msg = (
            f"schema guidance derived a {tokenizer_info.vocab_size}-token vocabulary against the "
            f"model's {vocab_size}: the mask would leave the excess logits unconstrained"
        )
        raise BackendError(msg, status=500, error_type="guidance_unusable")
    try:
        compiler: Any = GrammarCompiler(tokenizer_info)
        compiled = {
            schema_id: compiler.compile_json_schema(
                text,
                strict_mode=True,
                any_order=False,
                max_whitespace_cnt=_MAX_GUIDANCE_WHITESPACE,
            )
            for schema_id, text in guidance_schemas.items()
        }
    except Exception as exc:
        msg = f"schema guidance could not be compiled into a grammar: {exc}"
        raise BackendError(msg, status=500, error_type="guidance_unusable") from exc
    return compiled


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
        compiled_grammars: Mapping[GuidanceSchemaId, Any] | None = None,
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
        # Total over GuidanceSchemaId whenever guidance is enabled, None when it is disabled —
        # the same all-or-nothing rule as the two maps above. One immutable grammar per id,
        # compiled once at load and shared across every matcher that follows.
        self._compiled_grammars = compiled_grammars
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

        Order is schemas -> tokenizer -> model -> id normalization -> grammar compile -> device
        transfer, so a schema or tokenizer fault costs zero model loads, unusable id metadata
        costs zero grammar work, and a grammar fault costs zero device transfers. Every one of
        those faults is decidable from metadata; deferring any to generation time would spend a
        full host allocation and an accelerator context first.

        local_files_only is NOT what resolves a valid local directory — local resolution already
        precedes every Hub path. It is what keeps a MISSING or typo'd model_dir from being read as
        a Hub repository identifier and reaching the network before it fails.

        Structured guidance is derived once at load when settings.structured_output is enabled —
        for EVERY operator-pinned schema, so a mode can never be selected at request time and find
        its schema unloaded. A missing, unreadable, or invalid JSON schema aborts loading rather
        than silently serving unconstrained output, and so does a schema that reaches xgrammar but
        yields no grammar. Disabled, the whole path is skipped: zero tokenizer introspection, zero
        compiler construction, zero compiles.
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
        # Grammar compilation sits HERE — after id normalization, before the device transfer.
        # Unusable ids cost zero grammar work, and a grammar fault costs zero device transfers.
        compiled_grammars = (
            None
            if guidance_schemas is None
            else _compile_guidance(tokenizer, model, guidance_schemas, eos_ids)
        )
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
            compiled_grammars=compiled_grammars,
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
        before generation if the exact templated prompt exceeds the token ceiling, and after
        generation if decoded text exceeds the response-byte ceiling.

        A named guided_schema attaches that id's compiled grammar as a fresh logits processor.
        Naming one while guidance is DISABLED generates unguided and does not raise: the wire
        contract is best-effort, honored only while structured_output is enabled.

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
            options: dict[str, Any] = {
                "do_sample": temperature > 0,
                "num_beams": 1,
                "max_new_tokens": max_tokens,
                "pad_token_id": self._pad_token_id,
            }
            if options["do_sample"]:
                options["temperature"] = temperature
            if guided_schema is not None and self._compiled_grammars is not None:
                # Applied AFTER admission, at the site the previous build refused from, so an
                # over-cap-plus-guided request keeps the same wire outcome across both units.
                # A FRESH processor per call: it owns matcher, bitmask and prefill state and
                # exposes no reset, so reuse would carry a finished matcher into the next
                # request. Subscripts directly — the map is total over the closed id set, so
                # there is no default arm to hide a mode whose grammar failed to compile.
                # LogitsProcessorList rather than a bare list: that is generate's declared
                # parameter type. The merge appends this mask after every default processor,
                # and a -inf survives temperature, top-k and top-p alike, so no sampling warper
                # can re-admit a masked token.
                processor: Any = LogitsProcessor(self._compiled_grammars[guided_schema])
                options["logits_processor"] = LogitsProcessorList([processor])
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
