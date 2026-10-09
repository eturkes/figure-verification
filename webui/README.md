# webui - Open WebUI provisioning harness

This out-of-tree, unshipped harness starts Open WebUI in a hermetic environment. It creates the
first administrator and installs the generated global outlet filter. It also installs the generated
figure-verification tool and attaches it to the model's default tools. Bootstrap checks eight facts
from four readbacks. The project type-checks and lint-checks this harness. It excludes the harness
from coverage, like `model_backend/`.

```text
browser → Open WebUI :8080
             ├─ global Figure Verification Filter (generated paste-in)
             ├─ OpenAI /v1 → model backend or stub :8001
             └─ Figure Verification tool (generated paste-in, in-process)
```

The tool is the demo's one operation. The harness provisions it from the committed artifact
`webui/demo-paste-in/figure_verification_tool.py`. It provisions the filter from
`webui/demo-paste-in/figure_verification_filter.py` in the same way. The generator builds the demo
files from the same sources as the production files in `paste-in/`. The two pairs differ in two
places. First, the anchoring rule: the demo refuses a chart that replaces a column the request
names. Production also refuses a chart that draws an unnamed column when the request names or
excludes at least one column. A column with a short name, such as `id`, is exempt. An alias of
recognized length (three ASCII characters, or two of another script) in the tool's valves ends that
exemption. Second, the inlet template differs. The demo filter asks the model for bare source text,
which the demo adapter turns into a tool call. The production filter asks for the tool call
directly. The harness registers no tool server.

Open WebUI is a trusted display and orchestration layer. The filter reads a backend-owned tool
receipt. It runs the receipt's program unchanged in the user's browser, with the trusted figure
reader around it. It then judges the finished figure against the user's own files and request. It
only publishes a PNG after the figure passes. Each reply also has a `Show checks` list. Click a
check to open it: it shows what the check does, the program line that drew the failed part and why
it failed. It also links to the [verification reference](../docs/verification.md). Bootstrap proves provisioning only. It sends no
chat request and makes no model-reliability claim.

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
per-terminal recipe below. The launcher starts the model tier and Open WebUI in that order. It
waits for each readiness endpoint. It runs `bootstrap` and prints the browser
URL and administrator login. It then blocks until an interrupt. At exit, it stops each child and
frees both ports. Bootstrap makes Figure Verifier a default tool on the configured model.
Thus, browser chats offer it without a manual tool toggle.

```sh
webui/launch.sh          # real local model on the dGPU (needs .venv-model)
webui/launch.sh --stub   # deterministic stub, no accelerator required
webui/launch.sh --fresh  # wipe the persisted .webui-data instance before starting
```

The model tier is the CUDA `model_backend` on the dGPU by default. Alternatively, use the
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
```

Start the OpenAI-compatible hardware-free stub. Then wait for its model list:

```sh
uv run --locked python -m webui stub
curl -fsS http://127.0.0.1:8001/v1/models
```

The stub is a deterministic integration fixture. It is not a model. On the legacy selector turn
for each banner prompt, it calls `draw_figure` with that prompt's scripted Python program from
`webui/banner.json`. Other requests receive prose. The stub tests wiring, not model selection or
generation quality.

For a real-model run, use the CUDA backend through the launcher. Keep its URL and model ID aligned
with the provisioner settings below.

Only after the stub answers, start Open WebUI. Then wait for application readiness:

```sh
uv run --locked python -m webui serve
curl -fsS http://127.0.0.1:8080/ready
```

The pasted tool and filter run in Open WebUI and call no other server.

In a third terminal, run the provisioning smoke-check:

```sh
uv run --locked python -m webui bootstrap
uv run --locked python -m webui bootstrap
```

Each command creates or updates `Figure Verification Filter` from
`webui/demo-paste-in/figure_verification_filter.py`. It reads back the exact generated bytes and confirms that
this is the only active filter and that it is global. It creates or updates the `Figure Verification`
tool from `webui/demo-paste-in/figure_verification_tool.py`. It reads back the tool bytes. It then attaches
`figure_verification` to the workspace model without removing existing tool IDs. Bootstrap exits 0
only when eight checks across four readbacks pass. The readbacks must enumerate the model and the
tool. They must show no `server:`-prefixed tool ID. The model's attached tool IDs must equal
`[figure_verification]`; an extra ID blocks startup. On a clean instance, the success banner
reports `models=1 tools=1 model_tools=1`.
The first run signs up the administrator and creates the filter. It enables both flags, creates
the tool, and creates the model configuration. Expect 403 → signin on the second signup. That run updates the existing filter
source and the existing tool source. It does not invert flags that are already true. When the tool
is already attached, it makes no model write.
The launcher disables persistent configuration for its settings. The launch environment supplies the
tool, model, and legacy-function-calling configuration. The administrator user, owned function, and
workspace model configuration persist in `.webui-data/`.

## Persisted-chat CLI

Use the persisted-chat CLI to send one prompt and read the stored reply:

```sh
uv run --locked python -m webui chat --prompt \
  "Create a verified bar chart of total revenue by month from sales.csv."
```

The CLI calls `WebUIClient.run_persisted_chat`. It waits for the persisted assistant message. It
then prints the final text: the first `output_text` content of a `message` output item. When an
embed is an `http://` or `https://` URL, the CLI also prints the first such URL. It never prints an
HTML embed, such as the Show-checks list that the filter adds.

## Live outlet assertion

With the clean hardware-free stack and the two bootstraps above still running, exercise the
server-side outlet. Use this direct probe instead of model generation:

```sh
uv run --locked python - <<'PY'
import httpx

from webui.paste_in.filter import FAIL_TEXT
from webui.settings import Settings

settings = Settings.from_env()
chart = """```python
# SENSITIVE_OUTLET_PROBE
import matplotlib.pyplot as plt
plt.plot([1, 2], [3, 4])
```"""
prose = "Ordinary prose has no backend tool receipt."

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

    assert outlet("outlet-chart", chart) == FAIL_TEXT
    assert outlet("outlet-prose", prose) == FAIL_TEXT

print("outlet no-receipt chart/prose: PASS")
PY
```

This direct endpoint sends no backend tool receipt. It checks that both a fenced chart and plain
prose receive the exact failure text. It does not test tool selection, the pass path, browser
rendering, model generation, or persisted-chat behavior.

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
`WEBUI_PROVISION_MODEL_BACKEND_URL` | `http://127.0.0.1:8001/v1` | Sets the canonical OpenAI-compatible backend `/v1` base URL.
`WEBUI_PROVISION_MODEL_ID` | `Qwen2.5-Coder-0.5B-Instruct` | Sets the model that the smoke requires.
`WEBUI_PROVISION_WEBUI_BIN` | `.venv-webui/bin/open-webui` | Sets the binary execution target.
`WEBUI_PROVISION_REQUEST_TIMEOUT` | `30` | Sets the timeout in seconds for each provisioning request.
`WEBUI_PROVISION_READY_TIMEOUT` | `60` | Sets the seconds allowed for `/ready`.

The default credentials are constant, throwaway PoC values. Both services bind to loopback.
For the verified recipe, keep that boundary. For any network-exposed deployment, use fresh
credentials. Generate a secret for that deployment. Obtain a separate production security review.
