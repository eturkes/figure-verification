# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""webui — the Open WebUI integration harness.

Provisions and drives a headless Open WebUI over its REST API: it installs the generated paste-in
pair (the `draw_figure` tool + the global filter), bootstraps an admin, and launches OWUI under a
canonical hermetic env, so the model's program is drawn and the filter judges the figure. NOT part
of the verifier trust claim: an out-of-tree harness like model_backend -- type-checked under
mypy --strict but excluded from coverage and the wheel, importing only gate-venv deps (the
.venv-webui open-webui binary is exec'd, never imported).

settings.py owns the frozen config every other module imports; the REST client, bootstrap, model
stub, and CLI keep their wire/process boundaries separate.
"""
