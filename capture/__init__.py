# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Model-authored-Python capture tier: prompt corpus schema, capture record format, harness.

corpus -- the committed prompt sets, their strict schema and the byte-pinned capture template.
record -- what one capture run IS on disk: record + manifest schema, canonical bytes, the sole
outbound-body speller, provenance collection and the R1-R11 validator.

Repo-root package like bench/model_backend/webui/demo -- type-checked under mypy --strict,
outside the verifier coverage source, absent from the wheel. It never imports verifier.
"""
