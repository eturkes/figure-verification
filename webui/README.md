# webui - Open WebUI provisioning harness

Out-of-tree, unshipped M4 harness: starts Open WebUI under a hermetic environment, bootstraps its
first admin, and smoke-checks the model + verifier registrations. It is type/lint checked but
coverage-excluded, like `bench/` and `model_backend/`.

```text
browser → Open WebUI :8080
             ├─ OpenAI /v1 → model backend or stub :8001
             └─ global proposeSpec tool → verifier :8000
```

Open WebUI is a trusted display/orchestration layer, not part of the verifier claim. The bootstrap
proves provisioning only; it sends no chat request and makes no model-reliability claim.

## One-time setup

From the repository root:

```sh
uv sync --locked
uv venv --python 3.12 .venv-webui
uv pip install --python .venv-webui/bin/python 'open-webui==0.10.2'
```

Open WebUI 0.10.2 refuses the project's Python 3.13 line, so its ignored `.venv-webui/` is a
separate Python 3.12 environment. The harness executes its binary; it never imports Open WebUI into
the verifier environment.

## Clean hardware-free smoke

Run each long-lived service in its own terminal. Stop any prior Open WebUI process before deleting
state; `.webui-data/` is ignored and disposable.

```sh
rm -rf .webui-data
uv run --locked python -m verifier.service
```

Wait for the verifier before proceeding:

```sh
curl -fsS http://127.0.0.1:8000/health
```

Start the OpenAI-compatible hardware-free stub, then wait for its model list:

```sh
uv run --locked python -m webui stub
curl -fsS http://127.0.0.1:8001/v1/models
```

For an NPU run, replace the stub with the live `model_backend` launch in the
[M3 bench recipe](../bench/README.md); keep the backend URL and model ID aligned with the
provisioner settings below.

Only after both upstreams answer, start Open WebUI and wait for application readiness:

```sh
uv run --locked python -m webui serve
curl -fsS http://127.0.0.1:8080/ready
```

Ordering is load-bearing: `/api/v1/tools/` re-fetches each server's OpenAPI and drops an unreachable
server, so the verifier must be ready before Open WebUI starts or the bootstrap readback fails.

In a fourth terminal, provision and smoke-check:

```sh
uv run --locked python -m webui bootstrap
uv run --locked python -m webui bootstrap
```

Each command exits 0 only when the configured model ID and `server:verifier` are both present. A
clean first run signs up the admin; the second signup's 403 followed by a successful signin is the
expected idempotency path. Persistent-config is disabled: tool/model/legacy-function-calling config
comes from the launch environment, while only the admin user persists in `.webui-data/`.

## Operator inputs

All harness inputs use the `WEBUI_PROVISION_*` namespace. Export overrides before the relevant
`python -m webui …` command; the launcher translates them into Open WebUI config and drops unrelated
ambient variables.

| Variable | Default | Purpose |
|---|---|---|
| `WEBUI_PROVISION_HOST` | `127.0.0.1` | Open WebUI bind host + bootstrap host |
| `WEBUI_PROVISION_PORT` | `8080` | Open WebUI bind port |
| `WEBUI_PROVISION_DATA_DIR` | `.webui-data` | SQLite/uploads/cache root; resolved absolute from launch cwd |
| `WEBUI_PROVISION_SECRET_KEY` | fixed loopback dev value | JWT key; minimum 32 UTF-8 bytes |
| `WEBUI_PROVISION_ADMIN_NAME` | `operator` | first-admin display name |
| `WEBUI_PROVISION_ADMIN_EMAIL` | `operator@localhost` | signup/signin identity |
| `WEBUI_PROVISION_ADMIN_PASSWORD` | fixed loopback dev value | signup/signin password |
| `WEBUI_PROVISION_VERIFIER_URL` | `http://127.0.0.1:8000` | global verifier tool-server origin |
| `WEBUI_PROVISION_MODEL_BACKEND_URL` | `http://127.0.0.1:8001/v1` | OpenAI-compatible backend base URL |
| `WEBUI_PROVISION_MODEL_ID` | `Qwen2-0.5B-Instruct-int4-sym-ov` | model required by the smoke |
| `WEBUI_PROVISION_WEBUI_BIN` | `.venv-webui/bin/open-webui` | binary exec target |
| `WEBUI_PROVISION_REQUEST_TIMEOUT` | `30` | seconds per provisioning request |
| `WEBUI_PROVISION_READY_TIMEOUT` | `60` | seconds allowed for `/ready` |

Defaults are fixed, throwaway PoC credentials and all three services bind loopback. Keep that
boundary for the verified recipe; any network-exposed deployment needs fresh credentials, a secret
generated for that deployment, and a separate production security review.
