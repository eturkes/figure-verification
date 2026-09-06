---
paths:
  - "model_backend/engine.py"
  - "model_backend/smoke.py"
  - "model_backend/snapshot.py"
---

# transformers 5.16.1 pinned behaviours

Read BEFORE editing any `transformers`/`torch` call site. Every claim is cited into
`.venv-model/lib/python3.12/site-packages/`; paths below are relative to it. Training data is 4.x-era
and contradicts several of these — the installed bytes win.

- **`dtype=` takes a STRING** (`getattr(torch, dtype)`, `modeling_utils.py:862`, documented `:4022`)
  ⇒ a caller needs NO `import torch` for dtype alone. `torch_dtype=` still works silently in
  `from_pretrained`, loses to `dtype` when both are passed, and warns only on the `_from_config`
  path (`modeling_utils.py:4124-4162,1481-1494`).
- **`generate` is already `@torch.no_grad()`** (`generation/utils.py:2260-2262`) and
  `from_pretrained` already calls `.eval()` (`modeling_utils.py:3900-3903,4392-4397`) ⇒ an outer
  `inference_mode()` and a caller `.eval()` are both redundant.
- **`pad_token_id` is SCALAR-ONLY; `eos_token_id` accepts `int | list[int]`**
  (`generation/configuration_utils.py:301-306`). A list PAD reaches `self.pad_token_id < 0` and
  raises `TypeError` (`:647-680`). **`pad_token_id=tokenizer.eos_token_id` is therefore a LATENT
  BUG** — correct only while that tokenizer's EOS is scalar. `pad=None` silently becomes the FIRST
  eos element (`generation/utils.py:2083-2093`). Both ids are read from the GenerationConfig, never
  from the tokenizer; precedence = generate kwargs > explicit config > `model.generation_config`.
  Python `bool` is an `int` subclass ⇒ exclude it explicitly at every token-ID position.
- **No finish-reason exists anywhere.** `GenerateDecoderOnlyOutput` carries only sequences,
  scores/logits, attentions/hidden states, cache (`generation/utils.py:169-197`); stopping criteria
  return bare booleans and record no matched reason (`stopping_criteria.py:590-599,618-625`). The
  caller must derive it. The generated token is appended BEFORE criteria are evaluated
  (`generation/utils.py:2932-2937`) ⇒ an EOS that stopped generation is always the suffix's TERMINAL
  element, so classify on the terminal token, never on membership anywhere. At the exact cap
  `MaxLengthCriteria` and `EosTokenCriteria` both fire, OR-combined with no precedence
  (`stopping_criteria.py:62-87,543-599,618-625`) — which is why the caller, not the library, decides
  EOS-at-cap.
- **`do_sample=False` + a non-default `temperature` = logged warning, never an error**
  (`configuration_utils.py:708-728,846-867`; only `validate(strict=True)` raises). `do_sample=False`
  ALONE does not defeat beam/constrained/contrastive modes — greedy additionally needs
  `num_beams in {None,1}` and no constraints/forced words/contrastive pair (`:534-566`).
- **`apply_chat_template(tokenize=True, return_dict=True)` returns a `BatchEncoding`** with exactly
  `{input_ids, attention_mask}` for Qwen (`models/qwen2/tokenization_qwen2.py:36-38`;
  `tokenization_utils_tokenizers.py:758-774`) and tokenizes its rendered text with
  `add_special_tokens=False` internally (`tokenization_utils_base.py:3122-3131`) ⇒ NO second
  special-token pass, and a separate `encode(add_special_tokens=False)` step has no remaining job.
- **`BatchEncoding.to(device)` returns `self` but REBUILDS `.data`**
  (`tokenization_utils_base.py:759-783`) ⇒ capture `input_ids` AFTER the transfer; a device change
  yields new tensor objects, a same-device call preserves identity.
- **Decoder-only `generate` returns prompt+suffix and does not mutate the caller's tensor**
  (`generation/utils.py:910-920,2585-2593,2932-2933`) ⇒ slice `output[:, prompt_len:]`.
- **`local_files_only=True` is NOT needed to resolve a valid local directory**
  (`utils/hub.py:381-410`) — it is needed because a MISSING or typo'd path is otherwise treated as a
  Hub REPOSITORY IDENTIFIER and reaches the network before failing (`:439-496`). State that reason,
  not the false one. A malformed local directory has no single exception family: `OSError` from hub
  resolution, `ValueError` from `AutoConfig`/backend construction.
- **`device_map` requires accelerate** (`integrations/accelerate.py:96-141`) and cannot express a
  device STRING; its only real gain is lower PEAK HOST memory, since a mapped load materializes each
  weight straight onto the device (`core_model_loading.py:1604-1609,1716-1734`) while `.to()` builds
  the full CPU model first. Final device residency is identical.
- **Concurrent `generate` on one model = UNSETTLED BY EVIDENCE, so keep a lock.** Per-call config is
  deep-copied (`generation/utils.py:1771-1811`), but shared mutation exists on
  `_previous_max_cache_length` (`:1860-1905`), `_last_compile_config`/`_compiled_call`
  (`modeling_utils.py:4748-4764`), a temporarily swapped expert implementation (`:2179-2208`) and
  Qwen's rotary buffers (`modeling_rope_utils.py:43-80,82-130`). Never record this as "proved
  unsafe".
- **A single unpadded sequence needs no `attention_mask`** — `generate` synthesizes one
  (`generation/utils.py:778-807,2509-2513`) — but forward the one the tokenizer produced anyway.
