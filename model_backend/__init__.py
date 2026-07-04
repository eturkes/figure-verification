# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""model_backend — the local OpenVINO model server (untrusted proposer, M3.1b).

Serves an OpenAI-compatible /v1 chat-completions surface backed by a weak local model
(Qwen2-0.5B-int4 on the Intel iGPU). NOT the trusted verifier: it only PROPOSES a chart
spec; the verifier re-decodes and independently checks every reply (POC_SCOPE). So request
parsing here is lenient by design — the trust boundary is the verifier's strict decode, not
this server. Hardware-gated (OpenVINO resolves via PYTHONPATH, the intel-accel env sourced)
and shipped separately from the verifier package: type-checked under mypy --strict but
excluded from coverage and the wheel. Transcribes the gate-validated recipe in
.agent/m3_1_design.md.
"""
