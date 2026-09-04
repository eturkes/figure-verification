# Reference — subsystem mechanics (read on demand; NOT attached)

Every rule here fires from an unmissable trigger: you are editing the named subsystem. `.agent/memory.md` carries the rules that bind work which never names a subsystem, and a live stub there points at each section below. Maintain this file like memory — add a mechanic the moment a unit establishes one, delete it when obsolete.

| touching | read |
|---|---|
| `schema.py`, decode of untrusted bytes, the tagged Transform union (M11 `Derive`), the exported JSON Schema | msgspec pinned behaviours |
| `model_backend/`, `service/model_client.py`, `bench/`, proposer runtime, any engine port, M10 planning | Host machines + model-tier runtime |
| `model_backend/engine.py`, `smoke.py`, any `transformers`/`torch` call site | transformers 5.16.1 pinned behaviours |
| schema-guided decoding, `schema_guidance.py`, any grammar/logits-processor call site | xgrammar 0.2.3 pinned behaviours |
| `archive.py`, any schema migration, `replay.py` storage reads | SQLite provenance archive |
| `attestation.py`, `vcert.py` envelope sizing, `formal.py`, capacity/permits | DSSE · z3 · capacity |
| `render.py`, Vega-Lite spec building, offline HTML, badges | Renderer + Vega-Lite |
| `service/` handlers, error mapping, `openapi.py`, response unions | Litestar service + OpenAPI |
| a ruff `S603`/`ARG001`/format surprise, `httpx` clients, a second-interpreter run, VCert vector regeneration | Tooling mechanics |
| planning M10 (OWUI sandbox execution) or M11 (`derive` columns) | Future-milestone design seeds |
| `corpus/python/`, a capture harness, or any python-mode prompt surface | Python corpus |
| a README, CLI help, launcher banner, filter notice, badge/chart label or OpenAPI `summary=` | Human-facing surface list + authoring pins |
| `VPlot_SEMANTICS.md` — any heading, section number or `§` citation | `VPlot_SEMANTICS.md` structure + citation pins |
| `.claude/settings.json` `permissions.deny`, `.serena/project.yml` `ignored_paths`, consuming a persisted design recipe | Read-exclusion set + blueprint-recipe discharge |
| a `demo/` scenario registry, a walkthrough aggregate guard, `demo/e2e.py` imports, or a by-construction row deletion | Demo + walkthrough mechanics |
| adding or renaming an `AttemptRoute` member, a route-keyed map, or a proposer outcome selector | Attempt-route totality |

## msgspec pinned behaviours

Transcribe, never re-derive; `schema.py` cites these BY NUMBER.

1. `frozen`/`forbid_unknown_fields` propagate to subclasses at RUNTIME but `kw_only` does NOT, and mypy reads each class's own kwargs ⇒ EVERY concrete struct repeats `frozen=True` AND `kw_only=True`. `__struct_config__` does not expose `kw_only` ⇒ a separate test asserts positional construction raises.
2. A tagged union needs explicit `tag_field` + per-member `tag`, else msgspec defaults to the class name under field `type`.
3. Strict mode rejects float→int and bool→int but ACCEPTS JSON float→`Decimal` ⇒ model spec numerics as `int | str`, decimals as strings, ints bounded to signed int64.
4. Duplicate object keys silently LAST-WIN with no switch ⇒ reject via a stdlib `json.loads(raw, object_pairs_hook=…)` pre-scan.
5. `msgspec.json.schema()` emits NO `$schema`, is deterministic cross-process, sorts `Literal` enums alphabetically, renders a tagged union as `anyOf` + discriminator, maps `forbid_unknown_fields` → `additionalProperties:false`. The exported golden is ADVISORY, not the gate — JSON Schema `integer` admits `1.0`/`1e3` that strict decode rejects.
6. `msgspec.field(name=…)` renames in decode + encode + schema; when the attribute is itself named `field`, call `msgspec.field(…)` via the module or mypy reads the annotation as shadowing.
7. A frozen struct holding a `list` is only SHALLOWLY immutable and unhashable ⇒ model every JSON array as a bounded `tuple[T, ...]`.
8. `Encoder(order="deterministic")` keeps struct field order while sorting dict/set keys, renders Decimal→string, does NO Unicode normalization.
9. `Decoder.decode` raises the BUILTIN `UnicodeDecodeError` on invalid UTF-8 inside a JSON string ⇒ any guard over UNTRUSTED bytes must catch it alongside `DecodeError`/`ValidationError`, or the fault escapes its intended mapping.

## Host machines + model-tier runtime

- TWO hosts, incompatible model tiers. ORIGIN (source of all M3–M8 proposer evidence): Debian container on an ostree host, Intel NPU + iGPU, OpenVINO GenAI. CURRENT: CachyOS/Arch, i7-8650U Kaby Lake-R = **NO NPU** (no `/dev/accel*`, no `ivpu`; `/sys/class/accel` EXISTS but is EMPTY ⇒ the class dir is not evidence of a device), Intel UHD 620, NVIDIA MX150 (Pascal cc 6.1, ~1.95 GiB usable), driver 580.178.04 (res-port probe logs recorded 580.173.02 — scope their measurements to that tuple), 62 GiB RAM. `.venv-model` EXISTS on CURRENT (uv py3.12, torch 2.7.1+cu126 + transformers 5.16.1 + xgrammar 0.2.3) while the OpenVINO launcher arm stays unusable until M12.4.
- Measured runtime verdict on CURRENT: **torch 2.7.1+cu126 + transformers + xgrammar (fp16) = the sole GO** — GPU, xgrammar accepts the stripped schema, output validates strict VPlot, 3/3 byte-identical greedy, ~17.5 gen tok/s. Disqualified backups: llama.cpp native CUDA sm_61 + GBNF works but at 3–6 tok/s; llama-cpp-python's convenience schema API is NO-GO, FAIL-OPEN; OpenVINO `GPU` resolves to NVIDIA via NVIDIA OpenCL, NO-GO on speed; llama.cpp Vulkan cannot get `vkCreateInstance` from the NVIDIA GLX loader. Pascal pins: CUDA 13 REMOVED sm_61 and torch ≥2.11+cu128 dropped Pascal; `nvidia-cuda-nvcc-cu12` wheels ship no `nvcc`; upstream llama.cpp Linux CUDA prebuilts do not exist. Intel UHD 620 is unreachable by OpenVINO here even with the compute runtime installed; OpenVINO on **CPU** stays the untested zero-code-change option. VRAM envelope at ~1.95 GiB: Qwen2-0.5B fp16 = 1134 MiB at the real prompt, 1356 MiB at the 1536-token cap; ~1.5B Q4_K_M is the conservative 4-bit ceiling.
- `_DEFAULT_DEVICE` is `cuda` since M12.1 and the engine is torch/transformers since M12.2, so the backend LOADS on CURRENT. What stays impossible here is REPRODUCING the ORIGIN tuple: `bench/README.md`'s OpenVINO recipes are ORIGIN-only, so the real-model arms of the M3/M4/M6/M7/M8 live-stack gates + M9.12's live formula smoke cannot be re-taken on CURRENT, while those REVIEWED verdicts STAND on ORIGIN evidence. M12's stack is a NEW `(device, config)` and never a substitute reading for them. Milestone consequences → the roadmap's "Host change" paragraph.
- **The BROWSER tier runs fully on CURRENT.** `.venv-webui` (uv-managed CPython 3.12 + `open-webui==0.10.2`, gitignored) + `webui/launch.sh --stub` bring up verifier :8000 + stub :8001 + OWUI :8080, bootstrap reports `models=1 tool_servers=1 model_tools=1`, and the browser renders the verified chart inline with its `Verified plot / 10 checks passed / View certificate` badge. `--fresh` wipes `.webui-data`; a backgrounded launcher stops on SIGTERM to `.launch-logs/launch.pid`, never SIGINT. `--stub` remains the only LAUNCHER-reachable model tier until M12.4 rewrites the default arm: `.venv-model` now exists and serves real dGPU completions directly (`python -m model_backend`), but `launch.sh` still preflights the ORIGIN paths (`INTEL_ACCEL_ENV`, `OPENVINO_GENAI_PYTHON`, `/dev/accel`), which are absent here, so it refuses the default arm.
- **Remote browsing needs TWO forwarded ports, 8080 AND 8000.** The chart rides an ABSOLUTE `http://127.0.0.1:8000/chart/<plot_id>` embed that the OPERATOR's browser resolves, so an 8080-only tunnel loads OWUI while every chart iframe + every `/script`//`certificate`//`table` link silently fails. Keep the local port NUMBERS identical, or restart the verifier with `VERIFIER_PUBLIC_BASE_URL` set to the browser-facing origin (`public_base_url` = chart `Location` origin, independent of `VERIFIER_HOST` bind). Never forward 8001 — the stub is server-side only. Prefer an SSH tunnel over rebinding: the launcher's admin password is fixed and printed in its banner, so any non-loopback bind publishes that console.
- **Port seam is small + already isolated**: `app.py` touches only `Engine.load` / `engine.generate(messages, *, temperature, max_tokens, guided_schema)` / `engine.schema_sha256` / `BackendError`, and `tests/test_model_backend.py` injects a FAKE native module ⇒ the suite is hardware-free and a second engine gates without a GPU. Since M12.2 `engine.py`'s sole native import is `transformers` — NO torch — and the fake seam is a single module.
- **Any replacement engine must reproduce two contracts byte-exactly**, else outcomes silently reclassify: (1) refusal envelope = backend `400` + media essence exactly `application/json` + canonical bytes `{"error":{"message":…,"type":"prompt_too_long"}}`, which `model_client` re-encodes + compares before mapping to policy 422, so any drift becomes an upstream 502; (2) exact-admitted-token handoff = preflight the tokenized buffer, refuse over-cap BEFORE generation, generate from THAT buffer. A llama-server `/v1/chat/completions` owns templating + exposes no pre-tokenized handoff ⇒ only in-process runtimes can hold the `POC_SCOPE.md` claim.
- **Evidence split under a port.** SURVIVES any backend swap (verifier+corpus, model-free): the GUARANTEE (18 bad blocked / 10 good accepted + both corpus digests), the dataset hashes, the deterministic demo cases. INVALIDATED (every proposer OBSERVATION is `(device, config)`-scoped): the M3 raw 100-prompt baseline, the M8 A/B (`0→26/100`), the pre-M8 OWUI `5/10` selection, the pinned chart id, every latency figure. `bench/` is HTTP-only + verifier-import-free ⇒ the re-baseline INSTRUMENT survives intact.
- Model IDENTITY is duplicated beyond `model_backend/`: `src/verifier/service/settings.py`, `webui/settings.py`, `webui/README.md`, byte-pinned in `tests/test_service_model_client.py` + `tests/test_service.py` ⇒ changing the served model touches 5 tracked files outside the backend package. `POC_SCOPE.md` holds NO identity match (searched, rc 1) — it is not on this list.
- **Calibration intent binds the port** (user-stated): the proposer stays deliberately WEAK — low error on SIMPLE figures, high error on COMPLEX ones. The accelerator does not set that profile; MODEL + QUANTIZATION + guidance STRENGTH + token cap do. Choices that silently raise competence (INT4→fp16, xgrammar's stripped schema → a GBNF enforcing `pattern`) FLATTEN the gradient the demo depends on ⇒ hold model/quant-class/guidance-strength/`max_tokens` fixed across a swap, then re-read `bench` PER CATEGORY; the simple-vs-complex gradient is the aim, not the overall rate. **The CURRENT-host GO CONFLICTS with that constraint by construction**: ORIGIN served INT4 (`Qwen2-0.5B-Instruct-int4-sym-ov`) while the sole measured GO here is fp16 ⇒ a GPU port CANNOT hold quant class fixed. Do not read the GO as constraint-satisfying; budget the per-category `bench` re-baseline as its own unit of the port milestone, and treat the re-measured gradient — not the ORIGIN numbers — as the demo's calibration evidence.
- **A shared transport's flag can be ACTIVELY WRONG for a new mode** — check what a flag SELECTS, never that it merely exists. The retired `guided_json: true` read like a generic "use guidance" switch, but the backend pins ONE schema at load ⇒ sending it from a formula caller constrained formula output toward the DATASET schema. Corollary: a legacy-alias-plus-new-selector pair is a two-key precedence surface (the catch-all defect class) ⇒ prefer one symmetric CLOSED selector + pay the request-byte sweep, cheap because `model_backend`'s request struct tolerates unknown fields BY DESIGN (untrusted OpenAI-compatible tier; strictness lives in the verifier).
- **A schema→grammar CONVERTER can fail OPEN and a green-looking run hides it.** `llama-cpp-python`'s helper raises on a Draft-2020-12 root `$ref`, then its wrapper SILENTLY substitutes a generic JSON grammar — guidance reports active while enforcing almost nothing. Never credit a guidance path from a success return; prove enforcement by validating emitted output against the STRICT schema AND by feeding a construct the grammar must refuse. Binds every future guidance backend. Companion to the flag rule above: both are guidance defects that REPORT SUCCESS.

## transformers 5.16.1 pinned behaviours

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

## xgrammar 0.2.3 pinned behaviours

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

## SQLite provenance archive

- Schema = **v4**. `_validate_schema_version` compares live `sqlite_schema` rows against exact DDL **TEXT** ⇒ any constraint change must reach the STORED text, and SQLite cannot `ALTER` a `CHECK`. Two migration instruments, both probed at ~60 MB / ~2,000 blobs: `PRAGMA writable_schema` text rewrite = 0.30 s, ZERO file growth, moves no content byte (blob-content invariance true BY CONSTRUCTION) but needs defensive mode temporarily off, a physical backfill for any new NOT-NULL column + preserved physical column order; conventional table rebuild = 1.17 s, permanent 2.00× file growth, 3.00× peak with journal. `PRAGMA foreign_keys=OFF` is a NO-OP inside an open transaction (needs `Connection.setconfig`) while `defer_foreign_keys` still fails at COMMIT. **Six** tables reference `blobs(digest, kind)`.
- **An exact-DDL-text validator is BLIND to rootpage remapping**: swapping two tables' rootpages inside one transaction leaves DDL text, `integrity_check` AND `foreign_key_check` all passing while queries return the other table's content ⇒ any `writable_schema` migration must pin `SELECT name, rootpage` unchanged for pre-existing objects. Nothing else in a normal battery catches that class.
- Migration order is forced: validate prior version → `ADD COLUMN … NOT NULL DEFAULT` → explicit backfill `UPDATE` (ADD COLUMN writes no existing row) → stored-text rewrite dropping the DEFAULT → trigger → both version fields. Keep `UPDATE meta … WHERE singleton = ?` at `1`.
- Historic DDL that current code DERIVES (`_CREATE_*_V3 = _CREATE_*.replace(…)`) must be pinned against the bytes actually SHIPPED, extracted from git, never hand-retyped: those derivations are what v1/v2/v3 validation trusts ⇒ a wrong one rejects real archives on disk while every fresh-archive test stays green.
- Connection profile = `journal_mode=DELETE` + **`synchronous=EXTRA` (value 3, NOT `FULL`)** + `foreign_keys=ON` + `trusted_schema=OFF` + `busy_timeout=5000`, each forced then READ BACK. `Archive` keeps NO long-lived connection — every public op opens one + closes it in a `finally` ⇒ per-connection state is observable ONLY inside that lifetime. Monkeypatch the module-global connection factory with a `sqlite3.Connection` subclass recording `execute` + snapshotting settings in `close()` (snapshot via `super().execute`, else the probe pollutes its own record); that one seam pins migration STATEMENT ORDER + guard restoration on both success and injected-failure paths.
- `_insert_batch_rows` order is forced by `foreign_keys=ON`: blobs → keys → **plots → specs → attempts → plot_references** → attempt_references ⇒ a `BEFORE INSERT ON plot_references` trigger can always resolve its parent `plots` row.
- SQLite runs BEFORE INSERT triggers AHEAD of column CHECK constraints ⇒ where a trigger's admitted set ⊆ a CHECK domain, the trigger message MASKS the CHECK for every unknown value; isolate the CHECK with `DROP TRIGGER` on a throwaway connection.
- Typed blob identity is `(sha256, kind)`: same-role bytes deduplicate, while equal bytes under two truthful roles stay separately representable + each count once against the logical quota.
- **The attempt layer is source-neutral in SQL**: `attempts` stores address/envelope/key/nullable `plot_id` while route + outcome live ONLY inside the opaque signed payload ⇒ no SQL route/outcome domain exists to widen. The cross-edge to a formula plot is `attempts.plot_id → plots.source_kind`. `attempt_references.role` is correctly attempt-OBSERVATION-only + refuses carrier roles — that refusal is the design, not a gap. **Plot present ⇔ `VERIFIED`** is owned by pre-sign `_validate_manifest_plot_presence` (via `_validate_manifest_route_relations`) over `plot_id` + `plot_artifacts` + `outcome`; `_validate_attempt_outcome` deliberately does NOT recheck it + owns role presence, model-trace roles, occurrence claim + verdict/outcome agreement.
- `tests/test_service_archive.py::_complete_batch` publishes SYNTHETIC envelopes ⇒ signature-verifying readers cannot consume it; use the byte readers + `stats()`. `tests/schema_downgrade.py::downgrade_to_v3` is the EXACT v4→v3 fixture — a partial downgrade leaves a fixture that keeps passing while testing nothing.

## DSSE · z3 · capacity

- Z3 contexts are NOT thread-safe ⇒ every worker invocation owns an explicit `Context`.
- DSSE: verify signature + payload type, then parse the SAME verified payload byte buffer; never re-parse the envelope.
- A cancelled request keeps its admission permit until the uncancellable worker exits ⇒ it still occupies capacity. Canonical `workers=1` = one gate; extra processes multiply the policy instead of sharing it.
- Envelope ceilings carry base64+JSON headroom — `envelope_byte_limit(x, payload_type=…)` ≈ 1.88·x ⇒ a probe wanting the ceiling to bite cannot use `len(payload) - 1`. Both certificate MIMEs are 51 bytes ⇒ the two ceilings are NUMERICALLY EQUAL and only an argument spy proves which MIME was selected.

## Renderer + Vega-Lite

- **vl-convert-python** (pinned `vl_version` + lockfile build) → static SVG in the display TCB; pixels unhashed/trusted. SVG sits outside the VCert hashes + is diagnostic-only for exact replay, but the signed archive DOES digest-bind it.
- Positive-allowlist Vega builder copies no model key, disables implicit stack/sorts, inlines only recomputation. Badge rendering keeps filter literals injective then HTML-escapes all fields.
- JS parses JSON numerics as f64 ⇒ DISPLAY can round while certified bytes stay exact.
- Offline HTML stays outside the cert, fully bundled with inert JSON + every-`<` escape + `actions:false`; vendored DejaVu guarantees font availability, not byte selection over a same-name system font.
- Pinned Vega-Lite 5.21 compiles an explicit empty nominal color domain (`[]`, all-null data) + numeric ordinal domains — transcribe those forms without re-probing.

## Litestar service + OpenAPI

- Service: **Litestar** + **uvicorn** single-worker, 127.0.0.1 default (no loopback enforcement). Chosen over FastAPI for msgspec-native structs + OpenAPI — ergonomics, NOT a security property. Fail-closed invariant: POST bodies reach the decoder as RAW BYTES via `await request.body()` ONLY (`data: bytes` is framework-PARSED — JSON-decoded first, duplicate keys silently collapsed). CPU-bound work → async handler + `litestar.concurrency.sync_to_thread`. `@post` defaults 201 ⇒ set `status_code=200`. Body cap = `request_max_body_size`, 413 firing at the `request.body()` read (handler entered, content-type guard already run, NOT pre-dispatch); 2.24's `create_test_client` rejects the kwarg ⇒ build the app + wrap `TestClient(app=…)`. Content-type guard = `request.content_type[0] == "application/json"` else 415.
- Error split: verification outcomes INCLUDING decode failure (an expected model failure mode bench meters) = 200 verdict envelope; ONLY transport misuse / server config = RFC 9457 `application/problem+json`. Two `exception_handlers`: `HTTPException → problem+json`; `Exception → generic 500, cause LOGGED then WITHHELD`. Litestar does NOT log an exception a custom handler catches ⇒ the handler calls `_LOGGER.error(..., exc_info=exc)` itself; testing that log needs a handler on the NAMED logger AFTER app startup (startup logging config swaps root's handlers ⇒ caplog misses it).
- OpenAPI: Litestar auto-generation stays OFF (`openapi_config=None`) — it introspects response models via msgspec, whose response-encode-only `Literal[True]` arm breaks the document ⇒ hand-authored. `openapi_document()` rebases `$defs`, imports msgspec schemas + derives verdict strings; golden bytes + real-payload jsonschema tests pin it. Response unions use `anyOf` (a `RenderVerdict` also satisfies `Verdict`). `Response(content=bytes, media_type=…)` preserves canonical artifact bytes.

## Tooling mechanics (ruff · httpx · second interpreter · vector regeneration)

- ruff `S603` fires when argv is not visibly constant: the `-c <code-var>` form needs `# noqa: S603`, an inline literal argv list does NOT (a proactive noqa trips RUF100). `ARG001` exempts leading-underscore names but NOT an unused pytest fixture param (which cannot be `_`-prefixed) ⇒ omit the fixture. `ruff format` UN-wraps a parenthesized single string fitting ≤100 cols but KEEPS a multi-segment implicit concatenation split, flipping each segment to double quotes except one holding a `"`.
- `httpx` imports directly in tests (transitive via Litestar's TestClient, lockfile-pinned). `AsyncClient(timeout=N).timeout == httpx.Timeout(N)` (one arg fans out to every component). Neither `httpx.Timeout` nor `AsyncClient(timeout=)` VALIDATES: `0` times out every request immediately (NOT disabled), negative undefined, `None` disables, non-finite passes through (`inf` hangs unbounded, `nan` raises at request time) ⇒ guard `math.isfinite(t) and t > 0`.
- Second interpreter: `UV_PROJECT_ENVIRONMENT=.scratch/venv-py3135 UV_LINK_MODE=copy COVERAGE_FILE=.scratch/coverage-py3135 uv run --locked --python 3.13.5 pytest -q -p no:cacheprovider`. VCert vectors: `PYTHONPATH=$PWD/tests uv run --locked python tests/regenerate_vcert_vectors.py` (idempotent; rewrites only the two real-pipeline entries, copies `synthetic_*` verbatim).

## Read-exclusion set + blueprint-recipe discharge

- Do-not-read set (mechanism → `CLAUDE.md`). BOTH fronts (`permissions.deny` + `ignored_paths`) = the non-gitignored trio `LICENSE`, `uv.lock`, `**/*.ttf`. `permissions.deny` `Read()` ALONE for gitignored paths (Serena skips them via `.gitignore`): `.tokensave/`, `**/.serena/cache/`, `.verifier-state/`, `.launch-logs/`, `**/bench/reports/details.jsonl` (`report.json` readable), `.webui-data` binaries (`webui.db*`, `cache/`, `uploads/`, `vector_db/`; logs/JSON readable). Every rule stays depth-agnostic (slash-free name, else `**/` prefix) so each `.scratch/worktrees/<name>` copy inherits it while teammate reports stay readable. No LSP-hostile-but-readable path exists here (every served format answers `documentSymbol`; an unserved extension errors instantly, no stall) ⇒ `ignored_paths` mirrors the trio alone. Sync as new not-worth-reading files land; no project gate names a denied path.
- Persisted blueprint recipes drift silently from their source spec ⇒ cross-check each recipe against its spec section verbatim before implementing, never from memory. DISCHARGE: a recipe stamped "source-VERIFIED, drift-check DISCHARGED" carries the baseline commit OID of its certified consumed surface ⇒ confirm those files byte-UNCHANGED (`git diff --exit-code <baseline-OID> -- <files>`), then transcribe. Trust boundary: the discharge propagates the one-time stamp unchecked, so a transcription error made while stamping survives every later no-drift check.

## Human-facing surface list + authoring pins

- Authoring audience split (`CLAUDE.md` Authoring). HUMAN-FACING ⇒ ASD-STE100 binds: the five shipped READMEs (`README.md` + `webui`/`bench`/`demo`/`model_backend/runtime` operator recipes) + product/operator strings. `examples/README.md` stays OFF this list — `memory.md` holds it in the agent-optimized CLASS, so audit it against `CLAUDE.md` Authoring alone and keep its rows dense — `webui/launch.sh` `usage()` + READY banner, `enforcement_filter` `FILTER_NAME`/`FILTER_DESCRIPTION`/`BLOCKED_NOTICE`, `render.badge_html`/`signed_chart_html` labels + `<title>`, `VERIFIED_CHART_REPLY`, `app.py` OpenAPI `summary=` + chat success summary, CLI `description=`/`help=` literals, `audit._CLI_FAILURE`. `--help` is human-facing, a docstring is not ⇒ give `ArgumentParser` an explicit register-conformant `description=` + leave the docstring agent-optimized. A `README.md` block quote of an internal doc is a QUOTATION first: quoted claim/TCB lines stay byte-identical to the cited `POC_SCOPE.md` lines, so the register binds the README's OWN prose alone — re-diff the quoted substring after editing either file. Re-registering is free EXCEPT three pins: `audit._CLI_FAILURE` byte-pinned; `app.py`'s success summary regex-pinned by `verified_chart._SUMMARY_RE`; each OpenAPI `summary=` triplicated across `app.py` + `service/openapi.py` + the `schema/openapi.json` golden. `tests/test_webui_client.py` `_CHAT_TEXT` mirrors `VERIFIED_CHART_REPLY` as an INDEPENDENT fake-server fixture, not a pin.

## `VPlot_SEMANTICS.md` structure + citation pins

- **NOT human-facing.** It is an agent-consumed meaning contract that the evaluator, checks, renderer, script emitter and both dev/test oracles conform to ⇒ the `CLAUDE.md` dense/symbol-forward default governs it, NOT ASD-STE100. Do not "fix" its sentence lengths; Part A carries 26 sentences over 25 words by design and has passed two milestone reviews that way. The five shipped READMEs remain human-facing — the split above still binds them.
- **Structure.** One shared H1 + intro (the ONLY mode-neutral text) → `## Part A — dataset mode (vplot-0.1)` → `## Part B — formula mode (vplot-formula-0.1)`. 21 `###` sections: 12 dataset (`§1`–`§11` + `Settled decisions`), 9 formula (`§F1`–`§F9`). EVERY `###` heading contains its mode label, `— dataset mode` or `— formula mode`, so the invariant is one script away.
- **Section NUMBERS are load-bearing; heading TEXT is not.** No citation anywhere uses a `#anchor` fragment, so titles are free to reword. Numbers are cited from 7 external sites — `examples/index.json`, `examples/README.md` (×3), `tests/test_checks.py`, `tests/test_examples.py`, `tests/test_schema_properties.py` — pointing at Part A `§2`/`§4`/`§5`/`§7`/`§9`. Renumbering requires sweeping all 7.
- **Two consumers cite number + PROSE TITLE** — `src/verifier/errors.py:9` and `src/verifier/ingest.py:8` ⇒ a Part A TITLE rename must sweep those two even though anchors are unused.
- **Single-authority rule.** Each ruling is stated exactly once at true scope; a second statement is a defect because the copies drift independently. Current pointers rather than copies: `§F7` → `§F4` for the 13-check success count, `§F9` → `§F4` for the normalization contract, `§F1` → `§F6` for the operational no-execution rule, `§F7` → `POC_SCOPE.md` for verdict/route/storage claims. This file's authority ENDS at script emission.

## Demo + walkthrough mechanics

- **The shared `run_walkthrough`-shaped loop reports PASS over an EMPTY scenario tuple.** An emptied registry exits 0 with a 0/0 report while every gate stays green ⇒ every scenario registry needs its exact NAME set AND its cardinality pinned as hand-stated literals. Current registries: `demo/walkthrough.py` `_SCENARIOS` (13 dataset) + `demo/formula_walkthrough.py` `_FORMULA_SCENARIOS` (5: direct flow · proposed flow · certificate check shape · failed attempt audit cli · archive integrity guards).
- **A BY-CONSTRUCTION row deletion must be applied consistently or not at all.** Deleting a mode twin because "the guard reads no source column, so the dataset pin covers both" also deletes any SIBLING guard that faults ahead of mode dispatch — for M9.13b's aggregate, schema damage (`_replay_lowest` calls `lowest_verified_attempt_id` BEFORE mode dispatch) fell to the same argument as tampered publication, leaving one guard and dissolving the named gap, which was the THREE guards JOINED. Ruling: where the assured property is the JOIN, mode-neutrality of an individual leg is NOT grounds to delete it; record the residual instead (M9.13b's formula carrier is incidental to the publication guard it exercises).
- **The socket driver must never import `demo/formula_walkthrough.py`** — that module imports `litestar`, `TestClient`, `unittest.mock.patch` and `create_app` at MODULE scope, contradicting `demo/e2e.py`'s loopback-TCP-only claim at import level, called or not. Socket-transport formula logic is hand-written against `verifier.attestation`/`canon`/`vcert` plus the `demo.walkthrough` seam, and that twin is STRICTER than the in-process helper, which reaches into `app.state["identity"]` and passes neither `require_canonical_envelope` nor `expected_keyid_hint`. Binds M10.

## Attempt-route totality

- **A new `AttemptRoute` member must reach all NINE route surfaces**, each with hand-stated exact-set literals + its own dedicated mutant: enum widening alone type-checks while a map silently goes missing. The nine = `service/archive.py` `AttemptRoute` enum · its three route-keyed maps `_ROUTE_PLOT_SOURCES`, `_ROUTE_READS_DATASET_INPUTS`, `_ROUTE_MODEL_ROLES` · the pre-sign reply↔raw-spec identity guard `_validate_attempt_outcome` · the import-pure `replay.py` mirror's four, route literal `type _AttemptRoute`, `_EXPECTED_MODEL_ROLES`, `_ROUTE_ATTACHES_DATASET_PLOT`, `_ROUTE_ATTACHES_FORMULA_PLOT`. Every route-keyed map is pinned total by `set(<map>) == set(AttemptRoute)`, which kills a missing entry even where no behavioural test reaches the route. `_ROUTE_ATTACHES_PLOT` was SPLIT into the two attach maps and no longer exists — the archived M9.8a body still names it, so never copy it forward. Outcome-keyed maps stay source-neutral; `_PLOT_SOURCE_KIND_BY_BINDING_ROLES` derives the source from signed binding-role TOPOLOGY.
- **REJECTED — a second `_ROUTE_ALLOWED_OUTCOMES` map for the proposer.** The formula proposer keeps its OWN narrowing selector that refuses dataset-only outcomes then delegates. Strict schema decode admits grammar-shaped invalid expressions ON PURPOSE; parser `formula.names_allowed` owns those refusals.

## Python corpus

- Layout (M12.5 fixes it): `corpus/python/` — `design/` manifest+prompts (24+24; ids, category+idiom labels, dataset binding) · `heldout/` 20+20 PLAINTEXT (ruling 7: read only at the frozen-config acceptance run; subset design + tuning read the design set + its captures alone) · `sentinels.json` (2 public demo prompts, outside both sets + both denominators) · `captures/<run>/` records. Capture prompt = ruling 6 (task/format/dataset-binding only, zero few-shots, byte-pinned, sha in every record).
- ONE structural validator: counts · unique ids · category balance · design↔held-out prompt disjointness · zero admission vocabulary in any prompt (ruling 6). Crypto seal/escrow/contamination batteries = REJECTED over-engineering (ruling 7) — do not re-propose.
- M13 static guard: no prompt text, prompt hash, sample-specific field list or raw model reply may appear in production code — one committed search test; admission is justified by AST idiom class.

## Future-milestone design seeds (read at M10 / M11 PLANNING)

**M10 (deferred — browser-live OWUI; planned when M9 REVIEWED): OWUI sandbox execution + formula demo.** Source-CONFIRMED mechanism: a trusted async OUTLET Function filter reads the verifier tool-result from backend-owned state → verifies script sha256/signature → calls `execute:python` RPC DIRECTLY (bypassing `sanitize_code`) with the verifier's canonical script → Pyodide (sandbox iframe `allow-scripts`, no `allow-same-origin`) runs it, patched `plt.show()` → base64 PNG → emits an inline message file → else falls through to the unverified-chart block. Keep `ENABLE_CODE_INTERPRETER`/`ENABLE_CODE_EXECUTION` OFF (the internal RPC is not gated by them; model-driven exec stays off); `ENABLE_PYODIDE_FILE_PERSISTENCE` off; `ENABLE_WEBSOCKET_SUPPORT` on; bound `WEBSOCKET_EVENT_CALLER_TIMEOUT`. `execute:python` NEEDS a live browser socket → the headless harness (`webui/client.py`, random session_id, no socket) returns "Client session disconnected" → sandbox render = OPERATOR/browser step (like today's chart render; agent-container GL blocked per M6.3/M7); headless tests cover the gate logic/provenance/rewrite only. `enforcement_filter.py` reworked into verify-authentic-result → execute → publish → replace-content, else block (it currently treats matplotlib as an unverified signal — the user-reported bug). 3 units: (1) live OWUI feasibility gate; (2) conditional execution integration + browser E2E; (3) live demo + banner/blocked-visibility + close. Measured pre-M10 browser surface, all three UNCHANGED by M9 ⇒ formula mode has ZERO OWUI surface today: `webui/settings.py:84` allowlists `function_name_filter_list=["proposeSpec"]`, so OWUI exposes ONE of the document's 13 operations and never sees `proposeFormula`/`verifyFormula`; `webui/model_stub.py` classifies only `"You are proposing a VPlot v0.1 chart specification."`, which the formula system prompt's `"…VPlot formula chart specification."` does NOT match ⇒ a formula proposal falls through to the fixed final-summary reply and cannot decode; and `chart_signals()` returns `("matplotlib",)` on the verifier's OWN certified `matplotlib-script-0.1` bytes when fenced ⇒ the guard blocks the artifact M10 must publish. Live formula evidence is reachable only off the verifier port: `POST /verify-formula` → `verified:true` + `plot_id`, then co-located 200s on `/script` + `/certificate` + `/table` with `/chart` 404 (formula builds no chart page — the M9.13c R3 discrimination, measured live).

**M11 (deferred — dataset-mode derived columns; planned when M9 REVIEWED, sequence adjustable): computed columns via a `derive` transform.** New requirement (user): dataset mode must express per-row cross-column arithmetic (`profit = revenue - cost`) — the v0.1 transform grammar (select/filter/group_by/aggregate/sort) has NONE (aggregation is per-group, not per-row). Design: add a `Derive` op to the `schema.py` Transform union `{output: FieldName (distinct), expr: formula-source, out_scale}`; evaluate per row by binding the referenced columns into the SHARED M9 expression engine (exact `Fraction`, HALF_EVEN quantize to `out_scale`) → append one exact column; NO reinvention. Provenance: `expr` canonicalized folds into `spec_hash` (like `formula_hash`); derived values ride `plotted_table_hash`; replay reparses + recomputes per row; reuses M9 checks/cert/archive/replay. OPEN for M11 planning: per-row fail-closed policy (one undefined/div0/null row → reject the plot vs. drop the row; likely reject, total-or-nothing); pipeline placement + interaction with group_by/aggregate (a per-row map, so allowed broadly but aggregated-column rules needed); null-cell semantics; derived output type (quantitative) + encoding eligibility + name-distinctness; whether the dataset proposer emits derive ops. Transcendentals gated as in formula mode (exact-rational-first; interval profile later). No hardware gate (headless, pytest-gated).
