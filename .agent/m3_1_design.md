# M3.1 design — local model proposer backend (OpenVINO, gate-validated)

Probe-VALIDATED recipe (M3.1a, this box: Intel Lunar Lake iGPU). Source = the live probe, not
memory → M3.1b TRANSCRIBES this verbatim into `model_backend/`; cross-check each snippet here,
don't re-derive. Consumed + deletable at M3 review (like M1's recipes). Gate = RESOLVED: greedy
chat generation reproducibly runs on the Arc iGPU (evidence below).

## Gate acceptance (M3.1a) — MET
- `LLMPipeline(model, "GPU")` + `generate([prompt], greedy)` → coherent text, `deterministic=True`
  across repeat calls. "What is a bar chart?" → one correct sentence. Device `AUTO:GPU,CPU` = same.

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
- `OpenVINO/Qwen2-0.5B-Instruct-int4-ov` — Apache-2.0, HF-verified. Pre-converted OV IR (no
  optimum-cli convert step). Pulled via `huggingface_hub.snapshot_download(repo_id, local_dir=…)`.
- Local path (gitignored `models/`, host+container-coupled): `models/Qwen2-0.5B-Instruct-int4-ov`.
  368M total (`openvino_model.bin` 359M int4 weights; embeddings/output int8). qwen2, ctx 32768,
  vocab 151936. Bundled OV tokenizer+detokenizer (`openvino_{tokenizer,detokenizer}.{xml,bin}`) +
  `chat_template` in `tokenizer_config.json` → `LLMPipeline` tokenizes natively, template built-in.

## Device — `AUTO:GPU,CPU` (GPU primary, CPU fallback)
- GPU (Arc 140V iGPU) = target. CPU = correctness fallback.
- **NPU EXCLUDED**: `LLMPipeline(model, "NPU")` → `RuntimeError … [NPU_VCL] Compilation failed`
  (`vclAllocatedExecutableCreate3 0x78000004`). The general int4 IR (dynamic shapes) needs a
  dedicated static-shape NPU export → out of PoC scope. So the CLAUDE.local NPU>GPU>CPU default
  does NOT apply to THIS model → use `AUTO:GPU,CPU`, not `AUTO:NPU,GPU,CPU`.

## Load + generate recipe (exact API — M3.1b transcribes)
```python
import openvino_genai as ov_genai
pipe = ov_genai.LLMPipeline("models/Qwen2-0.5B-Instruct-int4-ov", "AUTO:GPU,CPU")
tok = pipe.get_tokenizer()

# STATELESS per request: apply the chat template to the FULL messages array each call.
# NOT start_chat()/finish_chat() (those keep server-side history — wrong for OpenAI /v1).
prompt = tok.apply_chat_template(              # -> str
    [{"role": "system", "content": sys}, {"role": "user", "content": user}],
    add_generation_prompt=True,                # 2nd positional arg
)

cfg = ov_genai.GenerationConfig()
cfg.max_new_tokens = max_tokens                # bound generation (VERIFIER_MODEL_MAX_TOKENS)
cfg.do_sample = False                          # greedy == temperature 0 (deterministic proposer)

res = pipe.generate([prompt], cfg)             # LIST arg -> DecodedResults; bare str -> plain str
text = res.texts[0]
pm = res.perf_metrics                          # pm.get_num_generated_tokens() → OpenAI usage
```
- **Caps (two, distinct)**: `max_new_tokens` bounds TOKENS generated; the wrapper ALSO enforces a
  response-BYTE ceiling (over-cap → the M3.2 client treats it as upstream fault). Both guard the
  single backend lock/GPU against a prompt inducing unbounded local generation. (`max_body_bytes`
  is the SEPARATE inbound-caller cap in the verifier service, not here.)
- **Concurrency**: one `LLMPipeline` is not re-entrant → M3.1b serializes with `asyncio.to_thread`
  + a lock (one compiled pipeline, one GPU).
- **OpenAI /v1 mapping** (M3.1b): request `{model, messages, temperature, max_tokens}` →
  `apply_chat_template(messages)` + `GenerationConfig(max_new_tokens=max_tokens,
  do_sample=(temperature>0))` (M3.2 client sends `temperature:0` → greedy). Response →
  `{choices:[{message:{role:"assistant", content:text}}], usage:{prompt_tokens,
  completion_tokens, total_tokens}, model}` (`pm.get_num_generated_tokens()` = completion_tokens).

## Perf (this iGPU, indicative — not a determinism claim; the greedy TEXT is what's pinned)
- Load+compile: first-ever ~4.9s (IGC kernel compile), subsequent ~1.5s (kernel/page cache);
  `AUTO:GPU,CPU` ~6.3s cold (adds device probe). Optional: set OV `CACHE_DIR` to persist the GPU
  kernel cache across backend restarts.
- Generate: TTFT ~138ms; throughput ~115–125 tok/s; 24-token reply ~0.3s cold / ~0.15s warm.
- Greedy `do_sample=False` → byte-identical output across repeat calls (`deterministic=True`).

## Behavioral characterization — validates the "weak proposer" premise (informs M3.2 prompt, M3.4)
- Prompted for a strict-JSON chart spec, the 0.5B model emits SYNTACTICALLY valid JSON but
  SEMANTICALLY wrong: it echoes enum PLACEHOLDERS verbatim (`"mark":"bar|line|point"`,
  `"aggregate":"sum|mean|count|none"`) instead of picking one, and hallucinates field names
  (`total_sales`, `orders`) absent from the dataset. → exactly the failure the trusted verifier
  catches: VPlot strict-decode rejects the pipe-string enum; a manifest/field check rejects the
  hallucinated column. Confirms: (a) model is weak enough to be a real failure signal; (b) NO
  generation constraints (grammar/JSON-mode) — raw prompting yields the failures M3.4 meters;
  (c) it's coherent enough to sometimes bind fields right (region→…, date→…).

## Diversity alternatives (HF-verified to exist; NOT downloaded — for M3.4 proposer diversity)
- `OpenVINO/TinyLlama-1.1B-Chat-v1.0-int4-ov` (Apache-2.0) — different family, ~1.1B.
- `OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov` (Apache-2.0) — same family, stronger (fewer failures).
- `OpenVINO/Phi-3.5-mini-instruct-int4-ov` (MIT) — different family, larger.
- (`OpenVINO/Qwen2.5-0.5B-Instruct-int4-ov`, `…/SmolLM2-360M-Instruct-int4-ov` → 404, do not cite.)
- All pre-converted `-int4-ov` → same `snapshot_download` + `LLMPipeline` recipe, swap repo_id +
  local path. Keep `AUTO:GPU,CPU`; re-probe NPU per-model (its support is export-specific).
