# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""model_backend — the local OpenVINO model server (untrusted proposer, M3.1b).

Serves an OpenAI-compatible /v1 chat-completions surface backed by a weak local model (a
symmetric-INT4 Qwen2-0.5B export on the Intel NPU). NOT the trusted verifier: it only
PROPOSES a chart spec; the verifier re-decodes and independently checks every reply
(POC_SCOPE). So request parsing here is lenient by design — the trust boundary is the
verifier's strict decode, not this server. Hardware-gated (OpenVINO resolves via PYTHONPATH,
the intel-accel env sourced) and shipped separately from the verifier package: type-checked
under mypy --strict but excluded from coverage and the wheel. Run recipe: bench/README.md;
durable OpenVINO facts: .agent/memory.md (M3). Probe provenance: the consumed
.agent/m3_1_design.md in git history.
"""
