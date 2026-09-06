---
paths:
  - "model_backend/engine.py"
  - "model_backend/schema_guidance.py"
  - "model_backend/guidance_oracle.py"
---

# xgrammar 0.2.3 pinned behaviours

Read BEFORE editing any guidance call site. Cited into
`.venv-model/lib/python3.12/site-packages/xgrammar/`; paths below are relative to it.

- **`import xgrammar` ALONE pulls `torch` into `sys.modules`**, before `contrib.hf` is touched. The
  root `.venv` (py3.13, where the gate suite runs) has no torch/transformers/xgrammar ⇒ any
  `model_backend` module importing xgrammar needs a `sys.modules` FAKE in tests, exactly like
  `transformers`. This is why `schema_guidance.py` stays pure stdlib: its pure-JSON tests import it
  before any fake is installed.
- **`TokenizerInfo.from_huggingface(tokenizer, *, vocab_size=None, stop_token_ids=None)` fails OPEN
  on vocab width.** The default `vocab_size` is `max(len(get_vocab()), max_token_id + 1)` — 151665
  for the pinned Qwen snapshot — while `config.json` declares 151936. The processor then allocates a
  151665-bit mask and applies it to 151936-wide scores **with no width check**, leaving the excess
  logits UNMASKED. Silent, never an exception (`tokenizer_info.py:172-252`, `contrib/hf.py:50-92`).
  Always pass `vocab_size=model.config.vocab_size` AND verify the built
  `TokenizerInfo.vocab_size` equals it.
- **The unmasked count is exactly 256, and the naive vocab difference 271 is WRONG.** The bitmask is
  int32-packed, so 151665 bits round UP to 4740 words = 151680 describable positions;
  `fill_next_token_bitmask` writes padding bits 151665–151679 as DENIED, and
  `apply_token_bitmask_inplace` accepts a WIDER logits tensor silently, touching only its first
  151680 columns. Unmasked = 151936 − 151680 = 256, every one an id ≥ 151680. Any citation of 271
  double-counts the 15 padding bits.
- **The coupling lives in `model_backend/engine.py` and nowhere else.** Compilation needs the loaded
  tokenizer AND `model.config.vocab_size`, which exist only inside `Engine.load`. `schema_guidance.py`
  stays PURE stdlib: `tests/test_model_backend.py` imports it before installing any fake, so a native
  import there forces a fake onto every pure-JSON test. Shipped shape (M12.3a): `_compile_guidance`
  builds one grammar per `GuidanceSchemaId` at load, `generate` attaches a FRESH
  `xgrammar.contrib.hf.LogitsProcessor` per call inside `transformers.LogitsProcessorList` — the
  declared parameter type, not a bare list — selected by direct subscript on a map total over the
  closed id set. Load order: schemas → tokenizer → model → id normalization → grammar compile →
  `.to(device)`. Every preparation fault raises 500 `guidance_unusable`; the vocab-width check sits
  BETWEEN two `try` blocks so its own refusal cannot be swallowed by the handler around it, and only
  `Exception` is caught so a `BaseException` still escapes.
- **Always pass `stop_token_ids=sorted(eos_ids)` from `model.generation_config`.** Omitted, xgrammar
  derives stop ids from the TOKENIZER — `[151645]` here against the model's `[151645, 151643]` — so
  the grammar's termination authority would NARROW the stopping criterion's set and could mask an
  EOS the model relies on.
- **`compile_json_schema(schema, *, any_whitespace=True, indent=None, separators=None,
  strict_mode=True, max_whitespace_cnt=None, any_order=False)`** (`compiler.py:144-211`). `str` is
  accepted unchanged and is not pre-validated. `strict_mode=True` acts as
  `unevaluatedProperties/items=false`.
- **TWO of those defaults DO NOT TERMINATE under greedy decode; both are measured, both are now
  spelled explicitly at the call site.** (a) **`any_order=True` is markedly WEAKER than
  order-freedom alone** — it drops required-key presence and uniqueness, keeping key/value validity
  and an entry-count interval whose UPPER end is open, recursively; an endless run of one property
  is therefore grammar-admissible and greedy decode walks into it (`vplot-0.1`: `"hash"` repeated to
  the 768-token cap; both schemas cap-truncated, neither parsed). (b) **`any_whitespace=True` with
  `max_whitespace_cnt=None` admits an unbounded whitespace run AFTER a complete document**, so a
  greedy model pads with spaces instead of emitting EOS (`vplot-0.1` capped this way even under
  `any_order=False`). Shipped call = `strict_mode=True, any_order=False,
  max_whitespace_cnt=_MAX_GUIDANCE_WHITESPACE` (=8, `engine.py`); the sweep {1, 8} × both schemas ×
  {task, adversarial} prompt = 8/8 `finish_reason="stop"` + parseable, 127–217 tokens, and 8 is the
  weaker of the two bounds that works. **Never re-enable `any_order=True` for calibration reasons:
  it does not terminate.** Its residual cost is real and stands — key ORDER in guided output is now
  the grammar's, not the proposer's, so ordering is not evidence about the model.
- **Under `any_order=False` the grammar measurably ENFORCES required-key presence, `maxItems`,
  `maxLength`, `minimum` and `maximum`** on the shipped guidance schemas ⇒ the classic
  dropped-key/duplicate-key witness does NOT exist there. The live gap is what the guidance schemas
  themselves dropped: `pattern`/`format` are STRIPPED before compilation, so `"formula": "x^2"` is
  grammar-admitted + guidance-valid + strict-REJECTED. That is the standing O2b witness, and the
  model emits it unprompted.
- **Unsupported/unknown JSON-Schema keywords raise NOTHING and are silently ignored** (per-keyword
  fail-open); structurally malformed schemas and malformed JSON raise a bare `RuntimeError`, never
  the registered `xgrammar.exception.InvalidJSONError` (`compiler.py:144-214`). ⇒ **"the grammar
  enforces the guidance schema" is FALSE and may not be shipped.** What it enforces is evidenced by
  a both-ways live oracle; strict verifier re-decode stays the sole admission authority. The
  load-time `guidance_unusable` refusal covers compile ERRORS and the vocab-width mismatch and
  NOTHING else — per-keyword silent ignoring is unreachable from it, so **a green load is never
  evidence of enforcement**, and enforcement is credited ONLY from both-ways witnesses (a document
  admitted AND a document refused), never from a successful return.
- **The standing instrument is `model_backend/guidance_oracle.py`** — predicates `O1`–`O8`, run
  `./.venv-model/bin/python -m model_backend.guidance_oracle` on the host of record, rc 0 required.
  It loads `Engine` in-process and holds the accelerator for its whole run ⇒ stop any serving
  backend first. Rerun it after ANY change to a guidance call site; the hardware-free suite asserts
  about the CALL (arguments, attachment, construction count) and by construction cannot observe
  what a grammar does to a real decode.
- **`contrib.hf.LogitsProcessor(compiled_grammar)` is STATEFUL and single-`generate` only** —
  matchers, bitmask, `prefilled`, `batch_size`; no reset; its own note says EOS can bypass
  `__call__` (`contrib/hf.py:14-41,43-114`) ⇒ construct a FRESH one per call. It subclasses
  transformers' `LogitsProcessor`. `CompiledGrammar` is immutable and expressly shareable across
  matchers (`compiler.py:19-42`) ⇒ compile ONCE per schema id at load.
- **`GrammarCompiler(tokenizer_info, *, max_threads=8, cache_enabled=True, cache_limit_bytes=-1)`**
  owns an enabled-by-default native compile cache (`compiler.py:100-140,349-364`) ⇒ a test that
  compiles the same schema twice on one compiler may observe a cache hit, not a second compile.
- **Processor plumbing.** `generate` forwards a non-None `logits_processor` unchanged
  (`transformers/generation/utils.py:2508,2647-2652`) and merges it at `:1293` via
  `_merge_criteria_processor_list` (`:1396-1430`): defaults first, a custom instance REPLACING a
  same-type default, remaining customs APPENDED LAST. Sampling warpers are appended after the merge
  (`:1296-1297`) and only when `do_sample`; a `-inf` mask survives temperature/top-k/top-p, so no
  warper re-admits a masked token. The declared type is `LogitsProcessorList` throughout ⇒ pass
  `LogitsProcessorList([processor])`, never a bare list.
- **Cross-mode discrimination measured** (`Draft202012Validator` over the two STRIPPED guidance
  schemas): `examples/good_specs/g01_*.json` is valid under dataset guidance and INVALID under
  formula guidance, and `examples/formula_good_specs/f01_square.json` mirrors it. The discriminator
  is property NAMES plus the `version` const, neither of which the stripping touches. Schema-level
  discrimination is NOT grammar-level discrimination — measure the grammar separately.
