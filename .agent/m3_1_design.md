# M3.1 design — local model proposer backend (OpenVINO, gate-validated)

Probe-VALIDATED recipe (M3.1a, this box: Intel Lunar Lake iGPU). Source = the live probe, not
memory → M3.1b TRANSCRIBES this verbatim into `model_backend/`; cross-check each snippet here,
don't re-derive. Consumed + deletable at M3 review (like M1's recipes). Gate = RESOLVED: greedy
chat generation reproducibly runs on the Arc iGPU (evidence below).

## Gate acceptance (M3.1a) — MET
- Explicit `GPU`, greedy: coherent text ("What is a bar chart?" → one correct sentence),
  byte-deterministic across a warm repeat (gpu.log).
- `AUTO:GPU,CPU`, greedy: coherent text, byte-deterministic across a repeat (auto_verify.log);
  stops at EOS (18 tok < cap); load ~3.0s, TTFT ~205ms, ~100 tok/s.
- Determinism holds per FIXED (device, config); the greedy TEXT is config-sensitive — the AUTO run
  (bundled config, `repetition_penalty` 1.1) differs byte-for-byte from the GPU run (fresh config,
  penalty 1.0). Expected, NOT a determinism break; no claim that AUTO and GPU emit identical bytes.

## Environment (hardware-gated — NOT portable `uv run --locked`)
- Accel env FIRST, per shell, before python: `source /var/home/eturkes/.local/app/intel-accel/env.sh`
  (sets `LD_LIBRARY_PATH` driver farm + `OCL_ICD_VENDORS` + `ZE_ENABLE_ALT_DRIVERS`; read at exec).
- `openvino` + `openvino_genai` resolve via login-profile `PYTHONPATH`
  (`/var/home/eturkes/.local/app/openvino_genai/python`), NOT pip. v2026.2.1 / GenAI 2026.2.1.0.
- Backend venv (project-local) needs ONLY: `numpy` (OpenVINO imports it eagerly) + the web deps
  (`litestar`, `uvicorn`). NOT `openvino*` (PYTHONPATH provides it; a wheel would be harmless but
  redundant). Python MUST ∈ {3.10–3.13} (compiled `_pyopenvino` cpython tag); this box = 3.13.5.
- Run = call the venv python DIRECTLY (`.venv/bin/python`), never isolated (`-E`/`-I`/some
  `uv run` modes strip `PYTHONPATH` → OpenVINO vanishes).
- Probe venv (M3.1a, throwaway scratchpad): `uv venv --python 3.13` + `numpy huggingface_hub`.

## Model
- `OpenVINO/Qwen2-0.5B-Instruct-int4-ov` — Apache-2.0. Pulled (download.log) via
  `huggingface_hub.snapshot_download(repo_id, local_dir=…)`; pre-converted OV IR (no optimum-cli step).
- Local path (gitignored `models/`, host+container-coupled): `models/Qwen2-0.5B-Instruct-int4-ov`.
  368 MiB total (`openvino_model.bin` 343 MiB, int4 weights). config.json: qwen2, ctx 32768,
  vocab 151936. Bundled OV tokenizer+detokenizer (`openvino_{tokenizer,detokenizer}.{xml,bin}`) +
  `chat_template` in `tokenizer_config.json` → `LLMPipeline` tokenizes natively, template built-in.

## Device — `AUTO:GPU,CPU` (GPU primary, CPU fallback)
- GPU (Arc 140V iGPU) = target. CPU = correctness fallback.
- **NPU EXCLUDED**: `LLMPipeline(model, "NPU")` → `RuntimeError … [NPU_VCL] Compilation failed`
  (`vclAllocatedExecutableCreate3 0x78000004`; compiler diagnostic `StopLocationVerifierPass …
  Found 73 duplicated names`, dev.log). Root cause NOT established; a dedicated static-shape NPU
  export is the likely-but-UNPROVEN remediation → not pursued (out of PoC scope). So the
  CLAUDE.local NPU>GPU>CPU default does NOT apply to THIS model → use `AUTO:GPU,CPU`.

## Load + generate recipe (exact API — M3.1b transcribes)
```python
import openvino_genai as ov_genai
pipe = ov_genai.LLMPipeline("models/Qwen2-0.5B-Instruct-int4-ov", "AUTO:GPU,CPU")
tok = pipe.get_tokenizer()

# STATELESS per request: apply the chat template to the FULL messages array each call.
# NOT start_chat()/finish_chat() (those keep server-side history — wrong for OpenAI /v1).
prompt = tok.apply_chat_template(              # -> str
    [{"role": "system", "content": sys}, {"role": "user", "content": user}],
    add_generation_prompt=True,                # keyword arg (verified)
)

# Start from the model's BUNDLED config, then override — do NOT use a fresh GenerationConfig():
# fresh drops eos_token_id (→ -1) + stop_token_ids + repetition_penalty (1.1) and defaults
# max_new_tokens to 2**64-1. Bundled keeps correct termination across models.
# (`GenerationConfig(other)` is NOT a copy ctor — takes a json_path/kwargs; mutate in place.)
cfg = pipe.get_generation_config()
cfg.max_new_tokens = max_tokens                # ALWAYS set (VERIFIER_MODEL_MAX_TOKENS); fresh = unbounded
cfg.do_sample = temperature > 0               # greedy when temperature == 0 (deterministic proposer)
if cfg.do_sample:                              # honor a nonzero temperature (e.g. M4 chat)
    cfg.temperature = temperature             # do_sample alone leaves temp at 1.0 → set the value
# greedy (do_sample=False): temp/top_k/top_p ignored; bundled repetition_penalty=1.1 STILL applies —
# M3.2 may reset cfg.repetition_penalty=1.0 (json.log's naive failure signal used penalty 1.0).

res = pipe.generate([prompt], cfg)             # LIST arg -> DecodedResults; bare str -> plain str
text = res.texts[0]
pm = res.perf_metrics
prompt_tokens = pm.get_num_input_tokens()      # OpenAI usage.prompt_tokens
completion_tokens = pm.get_num_generated_tokens()   # usage.completion_tokens; total = sum
```
- **Caps (two, distinct)**: `max_new_tokens` bounds TOKENS generated; the M3.1b wrapper ALSO
  enforces a response-BYTE ceiling (over-cap → the M3.2 client treats it as upstream fault). Both
  guard the single backend lock/GPU against a prompt inducing unbounded local generation.
  (`max_body_bytes` is the SEPARATE inbound-caller cap in the verifier service, not here.)
- **Concurrency**: serialize conservatively — M3.1b runs `generate()` under `asyncio.to_thread` +
  one lock (one compiled pipeline, one GPU). Re-entrancy was NOT probed; the lock is the safe default.
- **OpenAI /v1 mapping** (M3.1b): request `{model, messages, temperature, max_tokens}` →
  `apply_chat_template(messages)` + bundled cfg with `max_new_tokens=max_tokens`,
  `do_sample=(temperature>0)`, and `cfg.temperature=temperature` when sampling (do_sample alone
  leaves temp 1.0 → `0.2`/`2.0` behave alike). M3.2 sends `temperature:0` → greedy. Response →
  `{choices:[{message:{role:"assistant", content:text}}], usage:{prompt_tokens, completion_tokens,
  total_tokens}, model}` with `prompt_tokens=get_num_input_tokens()`,
  `completion_tokens=get_num_generated_tokens()`, `total_tokens` = their sum.

## Perf (this iGPU, indicative — logged values only; the greedy TEXT is what's pinned)
- Load+compile: explicit `GPU` 1.45s warm (gpu.log); `AUTO:GPU,CPU` ~2.8–3.0s (auto_verify.log,
  adds the device probe). First-ever IGC kernel compile is slower (observed once, log not retained);
  set OV `CACHE_DIR` to persist the GPU kernel cache across backend restarts.
- Generate: explicit `GPU` TTFT 138ms, 125 tok/s (gpu.log); `AUTO:GPU,CPU` TTFT ~205ms, ~100 tok/s
  (auto_verify.log). Short replies sub-second.
- Greedy `do_sample=False` → byte-identical output across a repeat for a FIXED (device, config)
  (observed on GPU and on AUTO:GPU,CPU); the output text varies with config (e.g. `repetition_penalty`).

## Behavioral characterization — validates the "weak proposer" premise (informs M3.2 prompt, M3.4)
- OBSERVED (json.log; 3 requests, fresh greedy config): the 0.5B emits SYNTACTICALLY valid JSON
  (all 3 parse) but SEMANTICALLY wrong — it echoes enum PLACEHOLDERS verbatim
  (`"mark":"bar|line|point"`, `"aggregate":"sum|mean|count|none"`) instead of picking one, and
  emits field names not present in the request (`total_sales`, `orders`). It DID bind some fields
  sensibly (x=region, x=date, x=category).
- EXPECTED (design, not yet run): VPlot strict-decode WILL reject the pipe-string enum (a strict
  `Literal` — deductive); a manifest/field check (M3.3/M3.4) rejects columns absent from the TRUSTED
  manifest. So (a) the model is weak enough to be a real failure signal; (b) raw prompting, NO
  grammar/JSON-mode → M3.4 meters these failures. Re-characterize under the recipe's bundled config
  (penalty 1.1) at M3.2 — json.log used a fresh config (penalty 1.0), so exact text/failure-rate may shift.

## Diversity alternatives (HF model IDs; re-confirm on HF before download — for M3.4 diversity)
- `OpenVINO/TinyLlama-1.1B-Chat-v1.0-int4-ov` (Apache-2.0) — different family, ~1.1B.
- `OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov` (Apache-2.0) — same family, stronger (fewer failures).
- `OpenVINO/Phi-3.5-mini-instruct-int4-ov` (MIT) — different family, larger.
- (`OpenVINO/Qwen2.5-0.5B-Instruct-int4-ov`, `…/SmolLM2-360M-Instruct-int4-ov` → probed 404, do not cite.)
- All pre-converted `-int4-ov` → same `snapshot_download` + `LLMPipeline` recipe, swap repo_id +
  local path. Keep `AUTO:GPU,CPU`; re-probe NPU per-model (its support is export-specific).
