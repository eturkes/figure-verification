# webui - Open WebUI provisioning harness

This out-of-tree, unshipped harness starts Open WebUI in a hermetic environment. It creates the
first administrator and converges the repository-owned global outlet filter. It attaches the
verifier server to the configured model's default tools. It then smoke-checks all three readbacks.
The project type-checks and lint-checks this harness. The project excludes it from coverage, like
`bench/` and `model_backend/`.

```text
browser → Open WebUI :8080
             ├─ global Verified Plot Guard outlet filter
             ├─ OpenAI /v1 → model backend or stub :8001
             └─ global proposeSpec tool → verifier :8000
```

Open WebUI is a trusted display and orchestration layer. It is not part of the verifier claim. The
filter is a bypassable and false-positive-prone guardrail. It is not a security boundary. Bootstrap
proves provisioning only. It sends no chat request and makes no model-reliability claim.

## One-time setup

From the repository root, run:

```sh
uv sync --locked
uv venv --python 3.12 .venv-webui
uv pip install --python .venv-webui/bin/python 'open-webui==0.10.2'
```

Open WebUI 0.10.2 refuses the project's Python 3.13 line. For this reason, the ignored
`.venv-webui/` is a separate Python 3.12 environment. The harness executes the Open WebUI binary.
It never imports Open WebUI into the verifier environment.

## One-command interactive instance

From the repository root, run `webui/launch.sh`. This single command automates the complete
per-terminal recipe below. The launcher starts the verifier, the model tier, and Open WebUI in the
load-bearing order. It waits for each readiness endpoint. It runs `bootstrap` and prints the browser
URL and administrator login. It then blocks until an interrupt. At exit, it stops each child and
frees all three ports. Bootstrap makes Figure Verifier a default tool on the configured model.
Thus, browser chats offer it without a manual tool toggle.

```sh
webui/launch.sh          # real local model on the NPU (needs .venv-model and the accel farm)
webui/launch.sh --stub   # deterministic stub, no accelerator required
webui/launch.sh --fresh  # wipe the persisted .webui-data instance before starting
```

The model tier is the real OpenVINO `model_backend` on the NPU by default. Alternatively, use the
hardware-free stub with `--stub`. The alternatives are mutually exclusive on port `8001`. You can
override every host path, device, credential, port, and timeout with an environment variable. The
script header documents each default. For an interactive instance, press `Ctrl-C` to stop it. A
scripted, backgrounded launcher does not receive `SIGINT`. To stop that launcher, send `SIGTERM` or
use `.launch-logs/launch.pid`.

Use the per-terminal recipe below to run each service separately. Use it to debug one service or
create a custom topology. The recipe documents exactly what the launcher automates.

## Clean hardware-free smoke

Run each long-lived service in a separate terminal. Before you delete state, stop any existing Open
WebUI process. The project ignores `.webui-data/`. You can discard that directory.

```sh
rm -rf .webui-data
VERIFIER_WORK_RATE_PER_MINUTE=10000 VERIFIER_WORK_BURST=10000 \
  uv run --locked python -m verifier.service
```

This deterministic integration smoke raises the process-local work rate. Thus, repeated tool probes
exercise Open WebUI instead of the admission policy. When these overrides are absent, the
production defaults stay in force.

Before you continue, wait for the verifier:

```sh
curl -fsS http://127.0.0.1:8000/health
```

Start the OpenAI-compatible hardware-free stub. Then wait for its model list:

```sh
uv run --locked python -m webui stub
curl -fsS http://127.0.0.1:8001/v1/models
```

The stub is a deterministic integration fixture. It is not a model. It recognizes Open WebUI's
legacy tool-selector and VPlot-proposer system prompts. It then returns an exact `proposeSpec` call,
the tracked known-good `sales.csv` spec, and a lean final answer. This isolates tool execution,
embed persistence, and browser rendering from model reliability. No stub result supports a
tool-selection or generation-quality claim.

For an NPU run, replace the stub with the live `model_backend` launch in the
[bench recipe](../bench/README.md). Keep the backend URL and model ID aligned with the provisioner
settings below.

Only after both upstreams answer, start Open WebUI. Then wait for application readiness:

```sh
uv run --locked python -m webui serve
curl -fsS http://127.0.0.1:8080/ready
```

The order is load-bearing. `/api/v1/tools/` re-fetches each server's OpenAPI document. It drops an
unreachable server. Therefore, the verifier must be ready before Open WebUI starts. Otherwise, the
bootstrap readback fails.

In a fourth terminal, run the provisioning smoke-check:

```sh
uv run --locked python -m webui bootstrap
uv run --locked python -m webui bootstrap
```

Each command first creates or updates `Verified Plot Guard` from the exact
`webui/enforcement_filter.py` source. It proves that the filter is active and global. It then creates
or non-destructively updates the workspace model configuration. It ensures that the configuration's
`meta.toolIds` includes `server:verifier`. It exits 0 only when all three readbacks succeed. The
readbacks must enumerate the configured model ID. They must show the server registration. They must
show that the model has the tool ID. On a clean instance, the success banner reports
`models=1 tool_servers=1 model_tools=1`. On a clean instance, the first run signs up the
administrator and creates the filter. It enables both flags and creates the model configuration.
Expect 403 → signin on the second signup. That run updates the existing filter source. It does
not invert flags that are already true. When the tool is already attached, it makes no model write.
The launcher disables persistent configuration for its settings. The launch environment supplies the
tool, model, and legacy-function-calling configuration. The administrator user, owned function, and
workspace model configuration persist in `.webui-data/`.

## Deterministic successful E2E (`--stub`)

With the hardware-free stack provisioned, run this synchronous request. It proves the legacy
selector, server tool, VPlot proposal, verifier, and clean verdict-context chain:

```sh
uv run --locked python - <<'PY'
import json

import httpx

from webui.settings import Settings

settings = Settings.from_env()
prompt = "Create a verified bar chart of total revenue by month from sales.csv."

with httpx.Client(base_url=settings.base_url, timeout=settings.request_timeout) as client:
    auth = client.post(
        "/api/v1/auths/signin",
        json={"email": settings.admin_email, "password": settings.admin_password},
    )
    auth.raise_for_status()
    client.headers["Authorization"] = f"Bearer {auth.json()['token']}"
    response = client.post(
        "/api/chat/completions",
        json={
            "model": settings.model_id,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "tool_ids": ["server:verifier"],
        },
    )
    response.raise_for_status()
    result = response.json()

assert result["choices"][0]["message"]["content"] == (
    "Figure Verifier confirmed the chart; all checks passed."
)
assert result["sources"][0]["source"]["name"] == "server:verifier/proposeSpec"
assert "Verified chart for sales.csv: all 10 checks passed." in json.dumps(result["sources"])
print("legacy-FC tool/verifier chain: PASS")
PY
```

For persisted browser evidence, send the same completion with `parent_id: null` and a non-empty
`session_id`. Include an assistant `id`. Include a complete `user_message` with its own ID, role,
content, timestamp, `parentId: null`, and `childrenIds: [<assistant-id>]`. The response supplies
`chat_id`. Poll `GET /api/v1/chats/{chat_id}` until that assistant has `done: true`. Then open
`/c/{chat_id}`. In Open WebUI 0.10.2, the persisted final text is
`output[0].content[0].text`. The legacy `content` stays empty. The verifier URL is in `embeds[0]`.
The rendered iframe must contain the verified chart. Its sandbox must omit `allow-same-origin`.

Use the persisted-chat CLI to run that flow without duplicate request construction:

```sh
uv run --locked python -m webui chat --prompt \
  "Create a verified bar chart of total revenue by month from sales.csv."
```

The CLI calls `WebUIClient.run_persisted_chat`. It waits for the persisted assistant message. It
then prints the final text from `output[0].content[0].text`. When a chart URL is present, it prints
that URL from `embeds[0]`.

An NPU run replaces the stub and measures the weak model separately. For that device and
configuration, a raw, unconstrained ten-prompt sample selected the tool on 5/10 prompts. The sample
produced no verified chart. Four calls reached the verifier with undecodable fenced specs. One call
omitted a required argument. That observation is not a bound. The deterministic fixture above
proves only that the integration works when its untrusted proposer supplies valid protocol
messages.

The shipped default schema-guides a selected `proposeSpec` generation. It steers the weak model
toward schema-representable structure instead of fenced prose. In the fixed 100-prompt live NPU
run, `verified_render=0.26`, compared with `0.00` in the same-commit unguided arm. Every reply had
the `bare_object` surface form and began `{`. The run had 0 fenced replies, compared with 52 in that
arm. Also, 83/100 replies parsed as JSON. However, 51/100 replies still failed strict VPlot decode.
Also, 23/100 replies failed a semantic check. Thus, the real model can render a verified chart
for some well-formed requests. However, the verifier blocks most attempts. These results are observations,
not bounds. They are reproducible only for the measured device and configuration. They do not
expand what the deterministic fixture proves. The 100-prompt bench calls `/propose-spec` directly.
Therefore, it measures neither Open WebUI tool selection nor guard coverage. The
`webui/launch.sh` two-example banner gives the pinned verified and blocked prompts. The
[bench recipe](../bench/README.md) documents reproduction and the session-logged, gitignored
reports.

## Live outlet assertion

With the clean hardware-free stack and the two bootstraps above still running, exercise the
server-side outlet. Use this direct probe instead of model generation:

```sh
uv run --locked python - <<'PY'
import httpx

from webui.enforcement_filter import BLOCKED_NOTICE
from webui.settings import Settings

settings = Settings.from_env()
chart = """```python
# SENSITIVE_OUTLET_PROBE
import matplotlib.pyplot as plt
plt.plot([1, 2], [3, 4])
```"""
prose = "Ordinary prose survives the global outlet unchanged."

with httpx.Client(base_url=settings.base_url, timeout=settings.request_timeout) as client:
    auth = client.post(
        "/api/v1/auths/signin",
        json={"email": settings.admin_email, "password": settings.admin_password},
    )
    auth.raise_for_status()
    client.headers["Authorization"] = f"Bearer {auth.json()['token']}"

    def outlet(message_id: str, content: str) -> str:
        response = client.post(
            "/api/chat/completed",
            json={
                "model": settings.model_id,
                "id": message_id,
                "chat_id": "local",
                "session_id": "outlet-probe",
                "messages": [{"role": "assistant", "content": content}],
            },
        )
        response.raise_for_status()
        result = response.json()["messages"][-1]["content"]
        assert isinstance(result, str)
        return result

    assert outlet("outlet-block", chart) == BLOCKED_NOTICE
    assert outlet("outlet-pass", prose) == prose

print("outlet block/pass differential: PASS")
PY
```

For the blocked call, the Open WebUI terminal must emit one content-free warning. It can resemble
`signals=matplotlib chars=<n>`. The log must contain neither the reply nor its unique marker. For
the prose call, the terminal emits no filter warning. This endpoint isolates the outlet contract.
It does not test model generation, tool selection, chart embedding, or persisted-chat behavior.
The steps above cover those.

## Operator inputs

All harness inputs use the `WEBUI_PROVISION_*` namespace. Before the relevant
`python -m webui …` command, export the overrides. The launcher translates them into Open WebUI
configuration. It drops unrelated ambient variables.

Variable | Default | Purpose
---|---|---
`WEBUI_PROVISION_HOST` | `127.0.0.1` | Sets the bare ASCII Open WebUI bind host and bootstrap host.
`WEBUI_PROVISION_PORT` | `8080` | Sets the Open WebUI bind port.
`WEBUI_PROVISION_DATA_DIR` | `.webui-data` | Sets the SQLite, uploads, and cache root. The launcher resolves it from the launch working directory.
`WEBUI_PROVISION_SECRET_KEY` | fixed loopback dev value | Sets the JWT key. It must contain at least 32 UTF-8 bytes.
`WEBUI_PROVISION_ADMIN_NAME` | `operator` | Sets the first administrator's display name.
`WEBUI_PROVISION_ADMIN_EMAIL` | `operator@localhost` | Sets the signup and signin identity.
`WEBUI_PROVISION_ADMIN_PASSWORD` | fixed loopback dev value | Sets the signup and signin password.
`WEBUI_PROVISION_VERIFIER_URL` | `http://127.0.0.1:8000` | Sets the canonical global verifier tool-server origin without a path.
`WEBUI_PROVISION_MODEL_BACKEND_URL` | `http://127.0.0.1:8001/v1` | Sets the canonical OpenAI-compatible backend `/v1` base URL.
`WEBUI_PROVISION_MODEL_ID` | `Qwen2-0.5B-Instruct-int4-sym-ov` | Sets the model that the smoke requires.
`WEBUI_PROVISION_WEBUI_BIN` | `.venv-webui/bin/open-webui` | Sets the binary execution target.
`WEBUI_PROVISION_REQUEST_TIMEOUT` | `30` | Sets the timeout in seconds for each provisioning request.
`WEBUI_PROVISION_READY_TIMEOUT` | `60` | Sets the seconds allowed for `/ready`.

The default credentials are fixed, throwaway PoC credentials. All three services bind to loopback.
For the verified recipe, keep that boundary. For any network-exposed deployment, use fresh
credentials. Generate a secret for that deployment. Obtain a separate production security review.
