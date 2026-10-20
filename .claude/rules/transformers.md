---
paths:
  - "model_backend/engine.py"
  - "model_backend/smoke.py"
  - "model_backend/snapshot.py"
---

# transformers 5.20.2 pinned behaviours

Read BEFORE editing any `transformers`/`torch` call site. Every claim is cited into
`.venv-model/lib/python3.15/site-packages/`; paths below are relative to it. Training data is 4.x-era
and contradicts several of these — the installed bytes win.

- **`dtype=` takes a STRING** (`getattr(torch, dtype)`, `modeling_utils.py:858`, documented `:3967`)
  ⇒ a caller needs NO `import torch` for dtype alone. `torch_dtype=` still works silently in
  `from_pretrained`, loses to `dtype` when both are passed, and warns only on the `_from_config`
  path (`modeling_utils.py:4069-4107,1394-1407`).
- **`generate` is already `@torch.no_grad()`** (`generation/utils.py:2568-2570`) and
  `from_pretrained` already calls `.eval()` (`modeling_utils.py:3842-3845,4357`) ⇒ a caller `.eval()`
  is redundant; an outer `inference_mode()` would add only what it disables beyond `no_grad` (view
  tracking + version-counter bumps, torch `autograd/grad_mode.py`) — a gain unmeasured here.
- **`pad_token_id` is SCALAR-ONLY; `eos_token_id` accepts `int | list[int]`**
  (`generation/configuration_utils.py:301-306`). A list PAD reaches `self.pad_token_id < 0` and
  raises `TypeError` (`:652-685`). **`pad_token_id=tokenizer.eos_token_id` is therefore a LATENT
  BUG** — correct only while that tokenizer's EOS is scalar. `pad=None` silently becomes the FIRST
  eos element (`generation/utils.py:2388-2398`). Both ids are read from the GenerationConfig, never
  from the tokenizer; precedence = generate kwargs > explicit config > `model.generation_config`.
  Python `bool` is an `int` subclass ⇒ exclude it explicitly at every token-ID position.
- **No finish-reason exists in `generate`'s output or its stopping criteria.**
  `GenerateDecoderOnlyOutput` carries only sequences, scores/logits, attentions/hidden states,
  cache (`generation/utils.py:184-216`); stopping criteria
  return bare booleans and record no matched reason (`stopping_criteria.py:590-599,618-625`). The
  caller must derive it. The generated token is appended BEFORE criteria are evaluated
  (`generation/utils.py:3267-3270`; 5.17's deferred stop check runs on MPS alone, `:442-450`, so CUDA
  stops on the step that matched) ⇒ an EOS that stopped generation is always the suffix's TERMINAL
  element, so classify on the terminal token, never on membership anywhere. At the exact cap
  `MaxLengthCriteria` and `EosTokenCriteria` both fire, OR-combined with no precedence
  (`stopping_criteria.py:62-87,543-599,618-625`) — which is why the caller, not the library, decides
  EOS-at-cap.
- **`do_sample=False` + a non-default `temperature` = logged warning, never an error**
  (`configuration_utils.py:713-733,869-894`; only `validate(strict=True)` raises). `do_sample=False`
  ALONE does not defeat beam/constrained/contrastive modes — greedy additionally needs
  `num_beams in {None,1}` and no constraints/forced words/contrastive pair (`:539-571`).
- **`apply_chat_template(tokenize=True, return_dict=True)` returns a `BatchEncoding`** with exactly
  `{input_ids, attention_mask}` for Qwen (`models/qwen2/tokenization_qwen2.py:36-38`;
  `tokenization_utils_tokenizers.py:794-811`; the engine's default kwargs — a requested offset or
  length adds keys) and tokenizes its rendered text with `add_special_tokens=False` internally
  (`tokenization_utils_base.py:3176-3185`; 5.20's `sanitize_control_tokens` defaults `False`,
  `:3012`, and stays off: it would change the admitted ids) ⇒ NO second special-token pass, and a
  separate `encode(add_special_tokens=False)` step has no remaining job.
- **`BatchEncoding.to(device)` returns `self` but REBUILDS `.data`**
  (`tokenization_utils_base.py:765-789`) ⇒ capture `input_ids` AFTER the transfer; a device change
  yields new tensor objects, a same-device call preserves identity.
- **Decoder-only `generate` returns prompt+suffix and does not mutate the caller's tensor**
  (`generation/utils.py:1185-1196,2905-2913,3267-3268`) ⇒ slice `output[:, prompt_len:]`.
- **`local_files_only=True` is NOT needed to resolve a valid local directory**
  (`utils/hub.py:455-484`) — it is needed because a MISSING or typo'd path is otherwise treated as a
  Hub REPOSITORY IDENTIFIER and reaches the network before failing (`:538-595`; a fully cached
  immutable commit now resolves offline, `:518-531`, which covers no arbitrary name). State that reason,
  not the false one. A malformed local directory has no single exception family: `OSError` from hub
  resolution, `ValueError` from `AutoConfig`/backend construction.
- **`device_map` requires accelerate** (`integrations/accelerate.py:96-141`); a device STRING
  (`"cpu"`, `"cuda"`, `"cuda:0"`) is accepted and normalized to `{"": torch.device(...)}`
  (`check_and_set_device_map`, `:110-120`). Its only real gain is lower PEAK HOST memory, since a
  mapped load materializes each weight straight onto the device for this dense fp16 mapping
  (`core_model_loading.py:1637-1642,1749-1767`; a force-CPU converter path is the exception) while
  `.to()` builds the full CPU model first. Final device residency is identical.
- **Concurrent `generate` on one model = UNSETTLED BY EVIDENCE, so keep a lock.** Per-call config is
  deep-copied (`generation/utils.py:2058-2098`), but shared mutation exists on
  `_previous_max_cache_length` (static-cache paths, `:2153-2198`),
  `_last_compile_config`/`_compiled_call` (compiling, `modeling_utils.py:4727-4743`; torch 2.14
  does not compile on CPython 3.15), a
  temporarily swapped MoE expert implementation (`generation/utils.py:2485-2509`) and dynamic/longrope
  rotary buffers (`modeling_rope_utils.py:43-80,82-130`) — none of them on this dense, default-rope
  eager path, so the lock stays as the cheap guard. Never record this as "proved
  unsafe".
- **A single unpadded sequence needs no `attention_mask`** — `generate` synthesizes one
  (`generation/utils.py:921-950,2863-2870`) and, since 5.18, drops an all-ones mask after building
  position ids (`:2877-2887`) — but forward the one the tokenizer produced anyway; the drop is
  internal and leaves the caller's mapping intact.

Engine rulings (`engine.py`): EOS/PAD authority is `model.generation_config`, never the tokenizer, and no `eos_token_id` reaches `generate` (EOS refuses at load → `generation_config_unusable` 500; PAD degrades to `min(eos_ids)`). ADMISSION PRECEDES GENERATION: an over-cap prompt answers 400 `prompt_too_long` with zero `generate` calls.
