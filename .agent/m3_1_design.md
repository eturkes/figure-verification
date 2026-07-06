# M3.1 design — local model proposer backend (OpenVINO, gate-validated)

Probe-VALIDATED recipe (Intel Lunar Lake, this box). Source = live probes, not memory →
`model_backend/` TRANSCRIBES this; cross-check each snippet, don't re-derive. Consumed +
deletable at M3 review (like M1's recipes). Gate = RESOLVED: greedy chat generation reproducibly
runs on the AI Boost **NPU** (default) and the Arc iGPU (fallback).

UPDATE (post-M3.3, direct task "change the local LLM model to an NPU model"): the default device
is now the **NPU**, serving a LOCALLY re-quantized SYMMETRIC-int4 export of Qwen2-0.5B. This
supersedes M3.1a's `AUTO:GPU,CPU` decision — M3.1a's "NPU EXCLUDED" is now RESOLVED empirically:
a local INT4_**SYM** re-export loads+runs on the NPU where the stock **ASYM** `-int4-ov` IR failed
VCL. Symmetric int4 (what OpenVINO's NPU LLM path calls for) is the LEADING cause, not isolated —
the re-export also rebuilt the graph (the VCL error was a duplicate-names defect); one before/after,
not an ablation.
GPU/CPU still run (dynamic shapes) and stay a documented fallback via `MODEL_BACKEND_DEVICE`.

## Gate acceptance — MET
NPU (default, symmetric export — npu_perf.log):
- Greedy chat: coherent text ("Name three primary colors" → "Red, Green, Blue."),
  byte-deterministic across a warm repeat (identical sha256), stops at EOS (finish_reason=stop).
- Steady-state ~68 tok/s (123 generated tok / 1.80s); small replies sub-400ms. The response echoes
  the backend's own `settings.model_name` (provenance honesty), not the caller's `model`.
- End-to-end: the verifier's `propose_spec` against the live NPU backend returns a malformed VPlot
  reply that strict `decode_spec` REJECTS (DecodeError) — the metered weak-proposer failure signal
  is intact under the symmetric export.

iGPU (M3.1a original — still valid as fallback; gpu.log / auto_verify.log):
- Explicit `GPU` + `AUTO:GPU,CPU`, greedy: coherent, byte-deterministic per warm repeat; stops at
  EOS; load ~3.0s, TTFT ~205ms, ~100 tok/s.
- Determinism holds per FIXED (device, config); greedy TEXT is config-sensitive — the AUTO run
  (bundled config, `repetition_penalty` 1.1) differs byte-for-byte from the GPU run (fresh config,
  penalty 1.0). Expected, NOT a determinism break. TEXT also varies with QUANTIZATION (sym ≠ asym).

## Environment (hardware-gated — NOT portable `uv run --locked`)
- Accel env FIRST, per shell, before python: `source /var/home/eturkes/.local/app/intel-accel/env.sh`
  (sets `LD_LIBRARY_PATH` driver farm + `OCL_ICD_VENDORS` + `ZE_ENABLE_ALT_DRIVERS`; read at exec).
- `openvino` + `openvino_genai` resolve via login-profile `PYTHONPATH`
  (`/var/home/eturkes/.local/app/openvino_genai/python`), NOT pip. v2026.2.1 / GenAI 2026.2.1.0.
- Backend venv (project-local) needs ONLY: `numpy` (OpenVINO imports it eagerly) + the web deps
  (`litestar`, `uvicorn`, `httpx`). NOT `openvino*` (PYTHONPATH provides it; a wheel would be
  harmless but redundant). Python MUST ∈ {3.10–3.13} (compiled `_pyopenvino` cpython tag).
- Run = call the venv python DIRECTLY (`.venv-model/bin/python`), never isolated (`-E`/`-I`/some
  `uv run` modes strip `PYTHONPATH` → OpenVINO vanishes).
- Re-export needs `nncf` + `huggingface_hub` + `openvino` (a throwaway scratch venv:
  `uv venv --python 3.13` + `numpy nncf huggingface_hub`, openvino via the same `PYTHONPATH`);
  one-off, off the backend's runtime deps.

## Model — a symmetric-int4 export for the NPU
- Served model (gitignored `models/`, host+container-coupled): `models/Qwen2-0.5B-Instruct-int4-sym-ov`,
  ~332 MiB. A LOCAL symmetric-INT4 re-quantization of Qwen2-0.5B-Instruct (Apache-2.0). Bundled OV
  tokenizer+detokenizer + `chat_template` → `LLMPipeline` tokenizes natively, template built-in.
- WHY re-quantize: the NPU VCL compiler REJECTS the stock ASYMMETRIC `OpenVINO/Qwen2-0.5B-Instruct-
  int4-ov` — `LLMPipeline(model, "NPU")` → `RuntimeError … [NPU_VCL] Compilation failed`
  (`vclAllocatedExecutableCreate3 0x78000004`; `StopLocationVerifierPass … Found 73 duplicated
  names`, dev.log). OpenVINO's NPU LLM path calls for SYMMETRIC int4, and the INT4_SYM re-export
  loads+runs (npu_perf.log) — the LEADING explanation for M3.1a's NPU-EXCLUDED (then a bare
  hypothesis). NOT isolated: the re-export also rebuilt the graph (that VCL error is a
  duplicate-names defect), so symmetry-vs-graph isn't teased apart — one before/after, no ablation.
- Re-export recipe (gate-validated; no torch/optimum — pure OpenVINO + nncf, see scratch compress.py):
  1. Fetch an FP16 OV IR: `huggingface_hub.snapshot_download("OpenVINO/qwen2-0.5b-instruct-fp16-ov",
     local_dir=…)` → `openvino_model.{xml,bin}` (~942 MiB bin) + tokenizer/detokenizer/config/
     generation_config/chat_template/merges/added_tokens.
  2. Re-quantize the weights to symmetric int4:
     ```python
     import nncf, openvino as ov
     model = ov.Core().read_model(src / "openvino_model.xml")     # the FP16 IR
     compressed = nncf.compress_weights(
         model, mode=nncf.CompressWeightsMode.INT4_SYM,           # SYM = the NPU-compatible mode
         group_size=128,                                          # 128 suits a sub-1B model
         ratio=1.0,                                               # all layers int4 (no fp16 tail)
     )
     ov.save_model(compressed, dst / "openvino_model.xml")
     ```
  3. Copy every non-`openvino_model.*` file from the FP16 IR to `dst` verbatim (tokenizer/detokenizer/
     config/chat_template/merges/added_tokens) — the export reuses them unchanged.

## Device — `NPU` (default); `AUTO:GPU,CPU` fallback
- NPU (AI Boost) = default target: dedicated AI silicon, best perf/W (CLAUDE.local NPU>GPU>CPU now
  APPLIES to this symmetric export, unlike the asymmetric model M3.1a excluded).
- NPU compiles to STATIC shapes → pass `MAX_PROMPT_LEN` at load (largest prompt in tokens the
  pipeline accepts). A prompt longer than it raises at `generate()` → backend 500 → the M3.2 client
  reads the non-2xx as a 502 upstream fault (OpenVINO static-shape contract; this over-length→raise
  branch was NOT exercised this session — the smoke prompt was ~770 tok, under the cap. The
  input-size budget is deferred to M5). `Engine.load` passes `MAX_PROMPT_LEN` ONLY for an NPU device.
- GPU (Arc 140V iGPU) / CPU = documented fallback: DYNAMIC shapes, which REJECT `MAX_PROMPT_LEN`, so
  it is omitted for them. Set `MODEL_BACKEND_DEVICE=AUTO:GPU,CPU` (GPU primary, CPU correctness).

## Load + generate recipe (exact API — model_backend transcribes)

```python
import openvino_genai as ov_genai
# NPU compiles to static shapes → cap the prompt at load; GPU/CPU use dynamic shapes + omit it.
pipeline_config = {"MAX_PROMPT_LEN": max_prompt_len} if "NPU" in device else {}
pipe = ov_genai.LLMPipeline("models/Qwen2-0.5B-Instruct-int4-sym-ov", device, **pipeline_config)
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
# greedy (do_sample=False): temp/top_k/top_p ignored. The proposer path is greedy (temperature 0);
# a nonzero temperature is not exercised on the NPU.

res = pipe.generate([prompt], cfg)             # LIST arg -> DecodedResults; bare str -> plain str
text = res.texts[0]
pm = res.perf_metrics
prompt_tokens = pm.get_num_input_tokens()      # OpenAI usage.prompt_tokens
completion_tokens = pm.get_num_generated_tokens()   # usage.completion_tokens; total = sum
# finish reason: res.finish_reasons[0] == GenerationFinishReason.LENGTH → "length" else "stop"
# (authoritative over a completion_tokens>=max_tokens heuristic — a natural EOS on the cap = STOP).
```

- **Caps (three, distinct)**: `max_new_tokens` bounds TOKENS generated; the wrapper ALSO enforces a
  response-BYTE ceiling (over-cap → the client treats it as an upstream fault); on the NPU,
  `MAX_PROMPT_LEN` bounds the INPUT (over-length → generate() raises → 502; static-shape contract,
  unexercised). All guard the single
  backend lock/accelerator. (`max_body_bytes` is the SEPARATE inbound-caller cap in the verifier
  service, not here.)
- **Concurrency**: serialize conservatively — `generate()` runs under `sync_to_thread` + one lock
  (one compiled pipeline, one accelerator). Re-entrancy was NOT probed; the lock is the safe default.
- **OpenAI /v1 mapping**: request `{model, messages, temperature, max_tokens}` →
  `apply_chat_template(messages)` + bundled cfg with `max_new_tokens=max_tokens`,
  `do_sample=(temperature>0)`, and `cfg.temperature=temperature` when sampling. M3.2 sends
  `temperature:0` → greedy. Response → `{choices:[{message:{role:"assistant", content:text}}],
  usage:{prompt_tokens, completion_tokens, total_tokens}, model}` with the backend's own model_name.

## Perf (indicative — logged values only; the greedy TEXT is what's pinned)
- NPU (npu_perf.log): steady-state ~68 tok/s (123 generated tok / 1.80s); small replies sub-400ms;
  byte-deterministic greedy across a repeat (identical sha256); finish_reason=stop. NPU compile is
  blocking (seconds; a cold kernel cache is slower) — not separately pinned this session.
- iGPU fallback (M3.1a): explicit `GPU` TTFT 138ms, 125 tok/s (gpu.log); `AUTO:GPU,CPU` TTFT ~205ms,
  ~100 tok/s (auto_verify.log). Set OV `CACHE_DIR` to persist the GPU kernel cache across restarts.
- Greedy `do_sample=False` → byte-identical output across a repeat for a FIXED (device, config,
  quantization); the text varies with config (e.g. `repetition_penalty`) and with quantization.

## Behavioral characterization — validates the "weak proposer" premise (informs M3.2 prompt, M3.4)
- One end-to-end smoke on the symmetric NPU export still returned a malformed VPlot reply that strict
  `decode_spec` REJECTS — a single observation that the failure signal M3.4 meters survives the quant
  swap (the failure TAXONOMY/RATE is re-characterized at M3.4, below).
- OBSERVED on the ASYMMETRIC model (M3.1a json.log; 3 requests, fresh greedy config): SYNTACTICALLY
  valid JSON (all parse) but SEMANTICALLY wrong — enum PLACEHOLDERS echoed verbatim
  (`"mark":"bar|line|point"`, `"aggregate":"sum|mean|count|none"`) + field names absent from the
  request. VPlot strict-decode rejects the pipe-string enum (a strict `Literal` — deductive); a
  manifest/field check (M3.3/M3.4) rejects absent columns.
- Raw prompting, NO grammar/JSON-mode → M3.4 meters these failures. Re-characterize the failure
  TAXONOMY (json-validity / failure-rate) on the SYMMETRIC model at M3.4 — QUANTIZATION shifts the
  exact text (the M3.1a taxonomy was on the asymmetric export, penalty 1.0).

## Diversity alternatives (HF model IDs; re-confirm on HF before download — for M3.4 diversity)
- `OpenVINO/TinyLlama-1.1B-Chat-v1.0-int4-ov` (Apache-2.0) — different family, ~1.1B.
- `OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov` (Apache-2.0) — same family, stronger (fewer failures).
- `OpenVINO/Phi-3.5-mini-instruct-int4-ov` (MIT) — different family, larger.
- (`OpenVINO/Qwen2.5-0.5B-Instruct-int4-ov`, `…/SmolLM2-360M-Instruct-int4-ov` → probed 404, do not cite.)
- The stock `-int4-ov` exports are ASYMMETRIC → for the NPU, re-export each to symmetric int4 via the
  recipe above (fetch its `-fp16-ov` IR → nncf INT4_SYM, group_size 128 for sub-1B else -1 channel-wise;
  larger models may need a proportionally larger `MAX_PROMPT_LEN`). For the GPU/CPU fallback the stock
  asymmetric `-int4-ov` loads directly — swap repo_id + local path, keep `AUTO:GPU,CPU`.
