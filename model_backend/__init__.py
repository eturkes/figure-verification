# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""model_backend — the local model server (untrusted proposer).

Serves an OpenAI-compatible /v1 chat-completions surface backed by a weak local model: an fp16
Qwen2.5-Coder-0.5B-Instruct snapshot on settings.device, run by transformers + torch and pinned
by content in model_backend/runtime/snapshot.json. NOT the trusted verifier: it only PROPOSES a
chart spec; the verifier re-decodes and independently checks every reply (POC_SCOPE). So request
parsing here is lenient by design — the trust boundary is the verifier's strict decode, not this
server. Hardware-gated (the isolated .venv-model py3.12 runtime project, never the portable uv
gate) and shipped separately from the verifier package: type-checked under mypy --strict but
excluded from coverage and the wheel. Run recipe: model_backend/runtime/README.md.
"""
