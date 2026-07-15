# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""webui — the Open WebUI integration harness (M4.3).

Provisions and drives a headless Open WebUI over its REST API: it registers the verifier as an
OpenAPI tool server, bootstraps an admin, and launches OWUI under a canonical hermetic env so the
weak local model proposes chart specs the verifier certifies before render. NOT part of the
verifier trust claim: an out-of-tree harness like model_backend and bench -- type-checked under
mypy --strict but excluded from coverage and the wheel, importing only gate-venv deps (the
.venv-webui open-webui binary is exec'd, never imported).

settings.py owns the frozen config every other module imports; the REST client, bootstrap, model
stub, and CLI keep their wire/process boundaries separate.
"""
