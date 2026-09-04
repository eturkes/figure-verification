# M12.3b acceptance contract (NON-attached; DELETE at the M12.3b close)

M12.3a is SHIPPED and its predicates `G1`-`G18` + `G2b` + `G6b` live in `tests/test_m12u3_guidance.py`
and `tests/test_rev_m12u3_contract.py`. What remains here is the LIVE ORACLE unit: predicates
`O1`-`O8` in §3, run on the host of record against `.venv-model`, gate = oracle rc 0.

Read §0 (measured API facts), §3's oracle rows, §6 (claim boundary) and §7 (session state). §1's
invariant surfaces and §2's design rulings are retained because the oracle must not silently
contradict shipped behaviour, but they are now DESCRIPTIONS of the shipped engine rather than
instructions - `model_backend/engine.py` is the authority wherever the two disagree.

---

## §0 — Confirmed API facts (MAIN-measured, `.venv-model` introspection)

Cross-check these against `map-m12u3` S1; a disagreement is a finding, not a tie.

- `import xgrammar` ITSELF puts `torch` in `sys.modules`. The root `.venv` (py3.13, where the gate
  suite runs) has NO torch, NO transformers, NO xgrammar ⇒ **a `sys.modules` fake for `xgrammar`
  is mandatory**, exactly as for `transformers`.
- `GrammarCompiler(tokenizer_info, *, max_threads=8, cache_enabled=True, cache_limit_bytes=-1)`
- `GrammarCompiler.compile_json_schema(schema: str | type[BaseModel] | dict, *, any_whitespace=True,
  indent=None, separators=None, strict_mode=True, max_whitespace_cnt=None, any_order=False)
  -> CompiledGrammar`. **`strict_mode=True` is the library default; `any_order=False` is the library
  default.** A `str` schema is accepted, which is what `load_guidance_schema` already returns.
- `TokenizerInfo.from_huggingface(tokenizer, *, vocab_size=None, stop_token_ids=None)`
- `xgrammar.contrib.hf.LogitsProcessor(compiled_grammar: CompiledGrammar | list[CompiledGrammar])`,
  `__call__(input_ids, scores) -> scores`, and it SUBCLASSES `transformers`' own `LogitsProcessor`.

**Processor plumbing (MAIN-measured in `transformers/generation/utils.py`).** `generate` passes a
non-None `logits_processor` straight through (`:2508`) into `_get_logits_processor` (`:2647-2652`),
which merges it with the library's own list at `:1293` via `_merge_criteria_processor_list`
(`:1396-1430`): defaults first, a custom instance REPLACING a default of the same type, then any
remaining customs APPENDED LAST. So the grammar mask runs after every default processor. Sampling
warpers are appended after the merge (`:1296-1297`) but only when `do_sample` is true — and a
`-inf` mask survives temperature, top-k and top-p, so no warper can re-admit a masked token. The
declared parameter type is `LogitsProcessorList` throughout ⇒ **G13 is RULED: pass
`transformers.LogitsProcessorList([processor])`**, not a bare list, so the engine matches the
declared contract rather than an accident of duck typing that a library version can withdraw.

Four `map-m12u3` findings that MOVED this contract (MAIN-validated against the cited bytes):

- **Measured silent fail-open on vocab width.** `TokenizerInfo.from_huggingface`'s DEFAULT
  `vocab_size` is `max(len(get_vocab()), max_token_id + 1)` — here **151665** — while
  `models/Qwen2.5-Coder-0.5B-Instruct/config.json:29` declares **151936**. The processor then
  allocates a 151665-bit mask and applies it to 151936-wide scores **with no width check**: exactly
  **256** logits go UNMASKED. Silent, not an exception. (`xgrammar/tokenizer_info.py:172-252`,
  `xgrammar/contrib/hf.py:50-92`.) This is the reference register's fail-open class, measured
  inside the chosen library ⇒ D6 plus the new D10 guard.
- **`any_order=True` is weaker than order-freedom alone.** It ALSO drops required-key presence and
  uniqueness enforcement, keeping only key/value validity and an entry-count interval, recursively
  (`xgrammar/compiler.py:144-211`). It is therefore the correct choice under the calibration
  ruling AND the reason guided output can be schema-shaped yet strict-invalid.
- **Unsupported/unknown JSON-Schema keywords raise NOTHING and are silently ignored**, while
  structurally malformed schemas and malformed JSON raise bare `RuntimeError`
  (`xgrammar/compiler.py:144-214`). Per-keyword fail-open is a PROPERTY of the library, not a bug
  this unit can close ⇒ §6 claim boundary.
- **The library itself mandates a fresh processor per `generate`** — the processor holds matchers,
  bitmask and `prefilled`/`batch_size` state, exposes no reset, and its own note says EOS can
  bypass `__call__` (`xgrammar/contrib/hf.py:14-41,43-114`). D7 is the library's contract, not a
  preference. `CompiledGrammar` is immutable and expressly shareable across matchers
  (`xgrammar/compiler.py:19-42`), so compile-once-per-id is correct.

---

## §1 — Invariant surfaces (must survive the unit unchanged; each no-edit claim proven by a named
search + rc + a positive control)

| id | invariant | why |
|---|---|---|
| I1 | `model_backend/schema_guidance.py` stays PURE stdlib — no native import, no xgrammar. | `tests/test_model_backend.py:28` imports it BEFORE the fake install at `:209`, and the root venv has no xgrammar. Making it native forces a fake on every pure-JSON test. **This OVERRIDES the roadmap plan's "`schema_guidance.py` compile-at-load" wording** — see §2 D1. |
| I2 | `model_backend/engine.py` contains NO `import torch` and no `torch` import statement. | Roadmap "Engine rulings still binding after M12.2" §1. A transitive torch import through `xgrammar` does NOT violate it; the rule is about this module's own imports and its single-fake test seam. The seam becomes TWO fakes, which is a docstring correction, not a violation. |
| I3 | Admission precedes guidance: an over-cap prompt refuses `400 prompt_too_long` even when `guided_schema` is named, with ZERO grammar/processor work. | M12.2 ruling 3, measured live at its close. M12.3 is the unit that could silently flip it. |
| I4 | EOS/PAD authority stays `model.generation_config`; no `eos_token_id` reaches `generate`; `pad_token_id` still does. | M12.2 §8 R01 / ruling A19. |
| I5 | Refusal envelope bytes for `prompt_too_long` unchanged: backend `400`, media essence exactly `application/json`, body exactly `{"error":{"message":…,"type":"prompt_too_long"}}`. | `.agent/reference.md` "two contracts byte-exactly" — drift reclassifies a policy refusal as a 502. |
| I6 | `model_backend/{app,models,settings,verified_chart}.py` unedited. | `app.py:99` already documents "Schema guidance applies only when guided_schema names an operator-pinned schema"; `models.py:59` already documents best-effort. Prove each, do not assume. |
| I7 | Greedy pins survive on the recorded `generate` call: `do_sample`, `num_beams=1`, `max_new_tokens`, `pad_token_id` all present and unchanged when a processor is added. | A logits processor is an easy place to drop sibling kwargs. |
| I8 | The response-byte ceiling still applies to guided output, after generation. | Unchanged path; pin it so guidance cannot bypass it. |

---

## §2 — MAIN design rulings

| id | ruling | rationale |
|---|---|---|
| D1 | **The xgrammar coupling lives in `model_backend/engine.py`.** Not `schema_guidance.py` (I1), not a new module. | Compilation needs the loaded tokenizer AND `model.config.vocab_size`, both of which exist only inside `Engine.load`; `engine.py` is the module whose documented job is isolating native imports and owning the load/generate lifecycle. Keeps the unit at ~one module per the sizing rule. |
| D2 | **Compile order = schemas(text) → tokenizer → model → id normalization → GRAMMAR COMPILE → `.to(device)`.** | Extends the shipped rationale ("a schema or tokenizer fault costs zero model loads and unusable id metadata costs zero device transfers"): a grammar-compile fault must cost zero device transfers too. Pinned by `model.to_calls == []` on compile failure. |
| D3 | **A compile failure refuses LOUDLY** — `BackendError(status=500, error_type="guidance_unusable")` at load — never a silent unguided degrade. | `.agent/reference.md`: "A schema→grammar CONVERTER can fail OPEN and a green-looking run hides it." Fail-closed at load is the whole defense. |
| D4 | **`structured_output=False` + a named `guided_schema` ⇒ generation proceeds UNGUIDED, no error.** | This is the SHIPPED, documented contract (`models.py:59` "Best-effort: the backend honors it only while structured_output is enabled"). Reversing it is scope the unit does not need. Because it IS a silently-unguided path, it gets its own explicit pin (G12) rather than passing by default. |
| D5 | **`compile_json_schema` is called with `strict_mode=True` and `any_order=True`, both spelled explicitly.** `any_order=True` is the LIBRARY-NON-DEFAULT and the WEAKER grammar (properties admitted in any order); `strict_mode=True` matches the library default but is spelled so a library default change cannot silently move guidance strength. | The calibration ruling (`.agent/reference.md`) forbids silently RAISING guidance strength. `any_order=False` would force a canonical property order — strictly stronger steering than ORIGIN's, and it would flatten the gradient the demo depends on. |
| D6 | **`vocab_size=model.config.vocab_size`, never `len(tokenizer)` and never the library default.** | `res-port` F4 measured this exact spelling and `map-m12u3` S1-04 measured the mechanism: the default derives 151665 against a 151936-wide score tensor and the mask is applied without a width check. Pinned by a fake whose two sizes DISAGREE. |
| D10 | **The engine VERIFIES the built `TokenizerInfo.vocab_size` equals `model.config.vocab_size` and refuses `guidance_unusable` on mismatch.** | Passing the right argument is necessary, not sufficient: the failure mode is silent by construction, so the only durable defense is an equality check at the seam. A library change that re-derives the size internally would otherwise re-open the hole with every test still green. `TokenizerInfo.vocab_size` is public and confirmed present. |
| D7 | **One `CompiledGrammar` per id, compiled once at load; one FRESH `LogitsProcessor` per `generate` call.** | The matcher is stateful per generation; reuse across calls would carry a finished matcher into the next request. |
| D8 | **The planned oracle predicate (a) is CORRECTED.** REQUIRED: guided output parses as JSON and validates against the STRIPPED GUIDANCE schema the grammar was compiled from. RECORDED-AS-OBSERVATION per id: whether it also validates STRICT. | Guidance is structure-only by design and the shipped suite already proves the formula guidance ADMITS text that strict decode REJECTS (`tests/test_model_backend.py:371`). Requiring strict validation per id would assert a claim the project deliberately does not make. `res-port` measured strict-valid output for the DATASET schema only. |
| D9 | **Declared FALLBACK split, numeric trigger.** If MAIN's window crosses **65%** before the live oracle script is written, the unit splits: **M12.3a** = guidance compile + apply + hardware-free suite + full gate green (DONE on the gate alone); **M12.3b** = the live both-ways oracle + determinism + JOINT-corner probe. | Sizing rule: opposite-verdict seams get recorded with a numeric trigger rather than discarded. M12.2 spent three windows; this unit bundles a live oracle onto a kernel edit. |

---

## §3 — Predicates (the red suite encodes every row; ids are stable and cited by test name)

### Load time

| id | predicate |
|---|---|
| G1 | `structured_output=True` ⇒ exactly ONE `compile_json_schema` call per `GuidanceSchemaId`, i.e. exactly 2, one per id, and every id in `get_args(GuidanceSchemaId.__value__)` is covered. (`get_args` on a PEP-695 alias returns `()` without `.__value__` — a closure test written the obvious way passes vacuously.) |
| G2 | `TokenizerInfo.from_huggingface` receives the loaded tokenizer object BY IDENTITY and `vocab_size=model.config.vocab_size`. Witness: the fake's `config.vocab_size` and `len(tokenizer)` DISAGREE, so an equal-value substitute cannot pass, and the `vocab_size` kwarg must be present — omitting it (library default) must FAIL the test. |
| G2b | A built `TokenizerInfo` whose `vocab_size` disagrees with `model.config.vocab_size` ⇒ `BackendError` 500 `guidance_unusable` and ZERO device transfers (D10). Witness: a fake `TokenizerInfo` that IGNORES the passed `vocab_size` and reports the tokenizer-derived one — i.e. the exact silent-fail-open shape, reproduced. |
| G3 | The text handed to `compile_json_schema` for an id equals `load_guidance_schema(<that id's path>)` — the pattern/format-STRIPPED guidance, never the raw strict schema bytes. Witness: the two differ (`'"pattern"' not in guidance_text`). |
| G4 | `compile_json_schema` receives `strict_mode=True` AND `any_order=True` as explicit keyword arguments, asserted on the RECORDED call. Both are hand-stated literals, not read back from a production constant. |
| G5 | A `compile_json_schema` failure ⇒ `BackendError` status 500, `error_type="guidance_unusable"`, AND `model.to_calls == []` (D2/D3). Distinct assertion: zero device transfers, not merely "it raised". **AMENDED (rev B-02): a `GrammarCompiler(...)` CONSTRUCTOR failure gets the SAME assertion.** One fault class, one surface — a constructor fault must not escape as a bare exception. |
| G6 | A `TokenizerInfo.from_huggingface` failure produces the same loud refusal shape as G5 (one fault class, one surface) and likewise zero device transfers. |
| G6b | **ADDED (rev B-02): D2's order is pinned POSITIVELY, not merely by `to_calls == []`.** Unusable EOS/id metadata ⇒ the existing shipped refusal, with ZERO `TokenizerInfo.from_huggingface` calls, ZERO `GrammarCompiler` constructions and ZERO `compile_json_schema` calls. Zero device transfers alone cannot distinguish "id normalization ran first" from "grammar work ran first and the transfer never happened"; call counts can. |
| G7 | `structured_output=False` ⇒ ZERO `TokenizerInfo.from_huggingface` calls, ZERO `GrammarCompiler` constructions, ZERO `compile_json_schema` calls. |
| G8 | `schema_sha256(id)` behavior is unchanged in both states (present digest when enabled, `None` when disabled) — the existing pins still pass untouched. |

### Generate time

| id | predicate |
|---|---|
| G9 | **On an engine loaded with `structured_output=True`** (precondition ADDED, rev B-03 — without it the shipped disabled-state helper satisfies this row while enabled guidance is wholly broken), `guided_schema=None` ⇒ ZERO `LogitsProcessor` constructions AND no `logits_processor` key in the recorded `generate` kwargs. Both halves asserted; a present-but-empty list would pass the first alone. |
| G10 | `guided_schema=<id>` with guidance enabled ⇒ exactly ONE `LogitsProcessor` construction, its `compiled_grammar` argument being THAT id's compiled object BY IDENTITY (`is`), and that processor reaching `generate`. Witness: the two ids compile to DISTINCT fake objects, so a wrong-id selection is observable. |
| G11 | Two successive `generate` calls with the SAME id construct TWO DISTINCT processor objects (`is not`). Objects retained through the assertion (an `id()`-only witness lets CPython reuse the address). |
| G12 | `structured_output=False` + `guided_schema=<id>` ⇒ generation SUCCEEDS, ZERO processor constructions, no `logits_processor` key, no error (D4). |
| G13 | The recorded `generate` call's `logits_processor` value is a `transformers.LogitsProcessorList` (exact type assertion, RULED in §0) holding exactly one element — the processor constructed for this call. A bare `list` must FAIL this test. |
| G14 | **On an engine loaded with `structured_output=True`** (precondition ADDED, rev B-03 — the shipped disabled-state pin P28 already passes and would mask a broken enabled path), over-cap prompt + named schema ⇒ `BackendError` 400 `prompt_too_long`, ZERO processor constructions, ZERO `generate` calls (I3). Call-counting bomb, not an outcome assertion — the outcome is identical whichever order the guards run in. |
| G15 | With a processor attached, the recorded `generate` call still carries `do_sample`, `num_beams=1`, `max_new_tokens`, `pad_token_id`, and still carries NO `eos_token_id` (I4/I7). **AMENDED (rev B-04): assert VALUES, not key presence.** Key-set equality lets sampling mode, token cap or PAD authority drift under guidance alone while every assertion passes. Each expected value is a HAND-STATED literal matching the fixture's request — never read back from a production constant (same discipline as G4). |
| G16 | Guided generation still enforces the response-byte ceiling: an over-ceiling guided reply raises `response_too_large` 500 (I8). |
| G17 | The engine module's source contains no `torch` import (I2), asserted by a word-bounded regex over `model_backend/engine.py` with a pattern positive control (a bare substring scan matches `torch` inside unrelated words — M12.2 ruling A20 paid for this). |
| G18 | `TokenizerInfo.from_huggingface` receives `stop_token_ids=sorted(eos_ids)` derived from `model.generation_config`, asserted on the RECORDED call as a real `list` whose SET equals the fixture's full EOS set (live values: `{151643, 151645}`). Omitting the kwarg must FAIL: xgrammar's default derives stop ids from the TOKENIZER (live: `[151645]`), which NARROWS the authoritative stop set and can mask model EOS 151643 — §8 R01's defect resurfacing through a different library, and the one place the grammar's termination authority can silently disagree with the engine's (I4). Witness: the fake tokenizer's `eos_token_id` DISAGREES with the fake model's `generation_config.eos_token_id`. |

### Live oracle (`kernel` evidence; MAIN-run on the host of record; rc 0 required)

| id | predicate |
|---|---|
| O1 | Per schema id: guided generation output parses as JSON and validates against the STRIPPED GUIDANCE schema the grammar was compiled from (D8). Strict-schema validity RECORDED per id as an observation. |
| O2 | Per schema id: a schema-specific negative that a GENERIC JSON grammar would accept is REFUSED. The refusal is proved by direct matcher rejection, not by a generation that merely happened not to emit it. `OPEN(map)` — S1 must name the matcher API that decides accept/reject for a given string. |
| O3 | Selector identity: the OTHER mode's golden object is refused by this mode's grammar. **Risk RETIRED at the schema level, MAIN-measured:** with `Draft202012Validator` over the two STRIPPED guidance schemas, `examples/good_specs/g01_total_revenue_by_month.json` is valid under dataset guidance and INVALID under formula guidance, and `examples/formula_good_specs/f01_square.json` is the mirror image. The discriminator is property NAMES plus the `version` const, which survives `any_order=True` (that flag drops required-key and uniqueness enforcement, not property-name admission under `strict_mode=True`). The oracle still measures it at GRAMMAR level, because schema-level discrimination is not grammar-level discrimination; a grammar-level failure here is a finding about xgrammar's coverage, not a reason to drop O3. |
| O4 | Adversarial prompt explicitly demanding out-of-schema output still yields in-schema output. **"In-schema" DEFINED (rev B-08): parses as JSON AND validates against the STRIPPED GUIDANCE schema — the same standard as O1 — with strict validity recorded as an observation.** An undefined "in-schema" would let natural model compliance be reported as live processor causality. |
| O5 | 3/3 greedy generations byte-identical under guidance. |
| O6 | JOINT-corner probe: 1536-token prompt + 512 new tokens under guidance. If VRAM refuses, lower ONE bound, record the exact tuple that ran, and state the refused one. **AMENDED (rev B-05): the corner is credited ONLY on measured `prompt_tokens == 1536` AND ACTUAL `completion_tokens == 512`.** The cache grows with real decode length, so an early EOS reaches the corner in neither dimension — and under guidance a valid JSON object terminating well short of 512 is the EXPECTED outcome, which makes this the likely path. Early EOS ⇒ record "corner NOT reached at N tokens" plainly, never a pass. `min_new_tokens` is NOT used under guidance (it fights the matcher's own EOS decision); establish the allocation envelope with a companion UNGUIDED run at `min_new_tokens=512`, labelled as the unguided corner. "Guided 1536+512 passed" may be written only when the guided run itself emitted 512. |
| O7 | Guided-vs-free per-token cost recorded as an observation on this `(device, config)`. Never framed as ORIGIN-comparable. **Method stated (rev A-O7 `WEAK`): discard a warm-up run, repeat ≥3, divide by ACTUAL completion tokens, and time the generate call alone.** Absent those four, report no per-token number at all. |
| O8 | **ADDED — ports the vocab-width measurement into committed, rerunnable form (§9 ruling 2).** With the DEFAULT `vocab_size`, the bitmask is int32-rounded to 151680 describable positions, the 15 padding bits 151665–151679 are written DENIED, `apply_token_bitmask_inplace` accepts a WIDER logits tensor without complaint, and exactly **256** logits (all ids ≥ 151680) survive unmasked. With `vocab_size=model.config.vocab_size` the count is ZERO. Both arms measured in one run; the 256 is the number every doc may cite. |

---

## §4 — Gate identity

`uv run --locked` × `ruff format --check .` · `ruff check .` · bare `mypy` · `pytest` — all rc 0,
run by MAIN on the primary tree, edit-free. Plus the live oracle rc 0 (or D9's split).
Coverage source is `verifier` only, so `model_backend/` carries no coverage obligation; its tests
are its only coverage.

## §5 — Probe-corpus seed

`schema/vplot-0.1.schema.json` · `schema/vplot-formula-0.1.schema.json` ·
`examples/good_specs/` · the formula goldens the shipped suite already loads.

## §6 — Claim boundary (what this unit may NOT say)

- Guidance grants NO semantic trust. It constrains STRUCTURE; strict verifier re-decode owns
  rejection. (`.agent/roadmap.md` M9.12 ruling.)
- No ORIGIN comparison. Every number here is a fresh `(device, config)` baseline.
- No error-gradient / calibration claim. That is M12.8's per-category re-baseline.
- Enforcement is credited only from BOTH-WAYS evidence (admitted AND refused), never from a
  success return.
- **"The grammar enforces the guidance schema" is FALSE as stated and may not be shipped.**
  xgrammar 0.2.3 SILENTLY IGNORES JSON-Schema keywords it does not support (S1-08b), and
  `any_order=True` additionally drops required-key and uniqueness enforcement (S1-02). The
  shippable claim is: *the grammar constrains generation toward the guidance schema; what it
  actually enforces is evidenced by the named live-oracle witnesses, and strict verifier re-decode
  remains the sole authority on admission.* Every docstring, README line and health-surface
  description this unit writes must match that wording.
- **"the subset xgrammar supports" is WITHDRAWN from the shippable claim (rev B-08).** That phrase
  reads as exhaustive coverage of a delimited keyword set, while the actual evidence is a handful
  of witnesses: O2 proves ONE refusal per schema and O1/O4 sample generated outputs. Nothing in
  this unit enumerates which keywords survive the silent-ignore path. Credit only the exact
  admitted and refused witnesses, by name.
- The load-time refusal (D3/D10) covers compile ERRORS and vocab-width mismatch. It does NOT and
  cannot cover per-keyword silent ignoring. Do not let a green load stand in for enforcement.

---

## §7 — session state (read FIRST on resume)

MODE = WORK-UNIT, unit **M12.3b**. M12.3a is DONE and SHIPPED at `4c2b9ef`; every prep teammate is
harvested, stopped, and its worktree and `wt/` branch removed. Nothing is in flight.

**What M12.3b builds.** `model_backend/guidance_oracle.py` — a sibling to `smoke.py`: NOT
pytest-collected, still lint- and type-gated, run by MAIN on the host of record against
`.venv-model` (py3.12, torch 2.7.1+cu126 / transformers 5.16.1 / xgrammar 0.2.3, MX150 cc 6.1
fp16, ~1.95 GiB VRAM). Gate = oracle rc 0. Predicates `O1`-`O8` in §3.

**Start here.**
1. Read `model_backend/engine.py` `_compile_guidance` + the `generate` apply site. The oracle
   drives the SHIPPED engine, never a re-implementation of it.
2. Read `model_backend/smoke.py` — it is the working precedent for a `.venv-model` entry point,
   including how it is excluded from collection and still passes `ruff` and `mypy`.
3. O8 is the cheapest and is already written: `.scratch/probe_mask_width.py` is the throwaway MAIN
   used to measure 256. Port it, do not re-derive it - the point of O8 is that the number stops
   living in a scratch file.
4. O2 needs the matcher API that decides accept/reject for a concrete string
   (`GrammarMatcher.accept_string`) - confirm the exact spelling against the installed bytes before
   building predicates on it.

**Live-stack binder.** `.venv-model` and the dGPU are single-holder resources; no other wave may
hold them concurrently.

**Sizing.** M12.3a spent one full prep window plus one implementation window. M12.3b is a single
new file with no test-suite fan-out, so a prep wave is likely unnecessary — but every predicate
here is measured on hardware, and hardware measurement is the cost driver, not the code.

## §8–§11 — REMOVED at the M12.3a close

Prep ruling history (12 `test-m12u3` readings, `map-m12u3`'s five routed decisions, `rev-m12u3`'s
3 HIGH + 5 MED findings). Every one of them is now encoded in the shipped suite or in shipped code.
Read them only for provenance: `.agent/archive/m12.md` "M12.3a", or `git log e56ec40..4c2b9ef`.
