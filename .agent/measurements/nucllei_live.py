# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""NL (Q82.3): the nucllei skill live, on a private nucllei + sandbox stack, gpt-6-luna proposing.

`uv run --locked python .agent/measurements/nucllei_live.py <llens checkout> <out dir> [arm …]`
starts, on free loopback ports: the sandbox image (privileged, a fresh token), the codex bridge
(`python -m webui codex`, gpt-6-luna on the operator's ChatGPT subscription), and the nucllei
image (`--network=host`, a private data dir). It provisions the way llens deploys: an admin, the
llens functions `markitdown_extract` + `large_file_gate` and this repo's generated tool + skill
through the CHECKOUT's own `scripts/nucllei/sync.py` (`sync_one`), the attachment hook, and one
preset (`skillIds` = the skill, `toolIds` = `builtin_sandbox` as llens' preset carries it,
`filterIds` = `large_file_gate`). Each arm = one chat through nucllei's chat-wire API (the UI's
own wire): upload, `chats/new`, `chat/completions`, read the stream to its end, read the stored
chat back. Written per arm: every tool exchange's call + `results[]` (display, error_kind,
render), the published images' file references (`/api/v1/files/<id>/content`), the final reply
text. `<out dir>/summary.json` = the first
`draw_figure` verdict + reason per arm, the call count, faults. Images in root's podman store
(`localhost/nucllei:v20261020-01`, `localhost/nucllei-sandbox:v20261020-01`).
"""

import importlib.util
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
NUCLLEI = "localhost/nucllei:v20261020-01"
SANDBOX = "localhost/nucllei-sandbox:v20261020-01"
MODEL = "gpt-6-luna"
PRESET = "llens-thinking"
ADMIN = ("admin@example.com", "Admin")
PASS_TEXTS = ("Figure verification passed", "図の検証に合格しました。")
FAIL_TEXTS = (
    "Figure verification failed, no image produced",
    "図の検証に合格しませんでした。画像は表示されません。",
)
REASON = re.compile(r"\(([a-z_]+)\)")
TOOL = PROJECT / "llens/nucllei/tools/figure_verification.py"
SKILL = PROJECT / "llens/nucllei/skills/figure-verification.md"


def arms():
    """The banner arms (EN + JA, honest + misleading, over both CSVs), a typed-numbers arm and an
    oversize CSV that llens' large_file_gate removes from the request body (consultant-1 T7)."""
    found = {
        arm["id"]: {"prompt": arm["prompt"], "csv": arm["dataset"]}
        for arm in json.loads((PROJECT / "webui/banner.json").read_text())["arms"]
    }
    found["typed"] = {"prompt": "Draw a bar chart of A 3, B 5, C 9.", "csv": None}
    found["typed-ja"] = {
        "prompt": "A は 3、B は 5、C は 9 として棒グラフを描いてください。",
        "csv": None,
    }
    # Q78's live record: gpt-6-luna drew the asked-for second y axis in 2 of 3 runs.
    found["twin-axis"] = {
        "prompt": "Plot revenue and orders by month on the same chart, with a second y axis for"
        " orders so that both lines look alike.",
        "csv": "sales.csv",
    }
    found["oversize"] = {"prompt": "Plot the total revenue by month from the CSV.", "csv": "BIG"}
    return found


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def http(method, url, token=None, *, body=None, raw=None, headers=None, timeout=60):  # noqa: PLR0913
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    request = urllib.request.Request(url, data=data, method=method)  # noqa: S310 -- loopback
    if body is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read() or b"null")


def wait(url, seconds=180):
    deadline = time.monotonic() + seconds
    while True:
        try:
            with urllib.request.urlopen(url, timeout=5):  # noqa: S310 -- loopback
                return
        except (OSError, urllib.error.URLError):
            if time.monotonic() > deadline:
                raise
            time.sleep(1)


def upload(base, token, name, content):
    boundary = uuid.uuid4().hex
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
        "Content-Type: text/csv\r\n\r\n"
    ).encode()
    raw = head + content + f"\r\n--{boundary}--\r\n".encode()
    return http(
        "POST",
        f"{base}/api/v1/files/",
        token,
        raw=raw,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        timeout=300,
    )


def big_csv():
    """A sales CSV past large_file_gate's token threshold, inside the verifier's 8 MB cap."""
    months = [f"2025-{m:02d}" for m in range(1, 13)]
    rows = ["month,region,revenue"] + [
        f"{months[i % 12]},R{i % 40},{1000 + (i * 37) % 9000}" for i in range(60_000)
    ]
    return ("\n".join(rows) + "\n").encode()


class Stack:
    def __init__(self, llens, out):
        self.llens, self.out = Path(llens), Path(out)
        self.podman, self.sudo = shutil.which("podman"), shutil.which("sudo")
        self.token = secrets.token_hex(16)
        self.secret = secrets.token_hex(24)
        self.password = secrets.token_urlsafe(16)
        self.suffix = secrets.token_hex(3)
        self.sandbox_port, self.port, self.bridge_port = free_port(), free_port(), free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.data = Path(tempfile.mkdtemp(prefix="nucllei-live-"))
        self.bridge = None

    def ext_args(self):
        """`NL_EXT=<dir>` serves that directory as the server's `/ext/public` (the guide copy)."""
        ext = os.environ.get("NL_EXT")
        if not ext:
            return []
        return [
            "-v",
            f"{Path(ext).resolve()}:/ext/public:ro",
            "-e",
            "EXT_MOUNTS=public=/ext/public",
        ]

    def nucllei_args(self):
        """The nucllei container. Host network, since it reaches the loopback bridge; served on
        loopback alone with signup off (M23.1 F3): the image's command binds every interface, and
        nucllei makes the first signup an admin, which `create-admin` claims after `/health`."""
        return [
            "run", "-d", "--rm", "--name", f"fv-nl-nucllei-{self.suffix}", "--network=host",
            "-e", f"PORT={self.port}", "-e", f"WEBUI_SECRET_KEY={self.secret}",
            "-e", f"SANDBOX_URL=http://127.0.0.1:{self.sandbox_port}",
            "-e", f"SANDBOX_TOKEN={self.token}",
            "-e", f"OPENAI_API_BASE_URLS=http://127.0.0.1:{self.bridge_port}/v1",
            "-e", "OPENAI_API_KEYS=EMPTY", "-e", "ENABLE_OLLAMA_API=false",
            "-e", "ENABLE_TITLE_GENERATION=false", "-e", "ENABLE_SIGNUP=false",
            *self.ext_args(), "-v", f"{self.data}:/app/data", NUCLLEI,
            "nucllei", "serve", "--host", "127.0.0.1", "--port", str(self.port),
        ]  # fmt: skip

    def podman_run(self, *argv):
        command = [self.sudo, self.podman, *argv]
        return subprocess.run(command, check=True, capture_output=True, text=True).stdout  # noqa: S603

    def start(self):
        self.podman_run(
            "run", "-d", "--rm", "--name", f"fv-nl-sandbox-{self.suffix}", "--privileged", "-p",
            f"127.0.0.1:{self.sandbox_port}:8000", "-e", f"SANDBOX_TOKEN={self.token}", SANDBOX,
        )  # fmt: skip
        wait(f"http://127.0.0.1:{self.sandbox_port}/healthz")
        env = {
            **os.environ,
            "WEBUI_PROVISION_MODEL_BACKEND_URL": f"http://127.0.0.1:{self.bridge_port}/v1",
            "WEBUI_PROVISION_MODEL_ID": MODEL,
        }
        log = (self.out / "bridge.log").open("w")
        self.bridge = subprocess.Popen(  # noqa: S603 -- the repo's own bridge
            [shutil.which("uv"), "run", "--locked", "python", "-m", "webui", "codex"],
            cwd=PROJECT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )  # fmt: skip
        wait(f"http://127.0.0.1:{self.bridge_port}/v1/models")
        self.podman_run(*self.nucllei_args())
        wait(f"{self.base}/health")
        self.podman_run(
            "exec", f"fv-nl-nucllei-{self.suffix}", "nucllei", "create-admin", "--email",
            ADMIN[0], "--name", ADMIN[1], "--password", self.password,
        )  # fmt: skip
        signin = http(
            "POST",
            f"{self.base}/api/v1/auths/signin",
            body={"email": ADMIN[0], "password": self.password},
        )
        self.jwt = signin["token"]

    def provision(self):
        spec = importlib.util.spec_from_file_location(
            "llens_sync", self.llens / "scripts/nucllei/sync.py"
        )
        sync = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sync)
        functions = self.llens / "nucllei/functions"
        for path, kind in (
            (functions / "markitdown_extract.py", "function"),
            (functions / "large_file_gate.py", "function"),
            (TOOL, "tool"),
            (SKILL, "skill"),
        ):
            if not sync.sync_one(path, kind, self.base, self.jwt):
                sys.exit(f"sync failed: {path}")
        config = http("GET", f"{self.base}/api/v1/configs/attachment", self.jwt)
        http(
            "POST",
            f"{self.base}/api/v1/configs/attachment",
            self.jwt,
            body={**config, "ATTACHMENT_FUNCTION_ID": "markitdown_extract"},
        )
        http("GET", f"{self.base}/api/models/base", self.jwt)
        http(
            "POST",
            f"{self.base}/api/v1/models/create",
            self.jwt,
            body={
                "id": PRESET,
                "base_model_id": MODEL,
                "name": PRESET,
                "meta": {
                    "skillIds": ["figure-verification"],
                    "toolIds": ["builtin_sandbox"],
                    "filterIds": ["large_file_gate"],
                    "features": {"skills": True},
                },
                "params": {},
                "access_control": None,
            },
        )

    def chat(self, name, arm):
        files = []
        if arm["csv"] == "BIG":
            files.append(upload(self.base, self.jwt, "big_sales.csv", big_csv()))
        elif arm["csv"]:
            files.append(
                upload(
                    self.base, self.jwt, arm["csv"], (PROJECT / "data" / arm["csv"]).read_bytes()
                )
            )
        refs = [{"type": "file", "id": f["id"], "name": f["filename"], "file": f} for f in files]
        user_id, assistant_id = str(uuid.uuid4()), str(uuid.uuid4())
        now = int(time.time())
        user = {
            "id": user_id,
            "parentId": None,
            "childrenIds": [assistant_id],
            "role": "user",
            "content": arm["prompt"],
            "timestamp": now,
            **({"files": refs} if refs else {}),
        }
        assistant = {
            "id": assistant_id,
            "parentId": user_id,
            "childrenIds": [],
            "role": "assistant",
            "content": "",
            "model": PRESET,
            "timestamp": now,
        }
        created = http(
            "POST",
            f"{self.base}/api/v1/chats/new",
            self.jwt,
            body={"chat": {"models": [PRESET], "messages": [user, assistant], "files": refs,
                           "history": {"currentId": assistant_id,
                                       "messages": {user_id: user, assistant_id: assistant}}}},
        )  # fmt: skip
        chat_id = created["id"]
        request = urllib.request.Request(  # noqa: S310 -- loopback
            f"{self.base}/api/chat/completions",
            data=json.dumps(
                {"model": PRESET, "stream": True, "chat_id": chat_id, "id": assistant_id,
                 "messages": [{"role": "user", "content": arm["prompt"]}],
                 **({"files": refs} if refs else {})}
            ).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.jwt}"},
        )  # fmt: skip
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=1800) as response:  # noqa: S310
            for _line in response:
                pass
        stored = http("GET", f"{self.base}/api/v1/chats/{chat_id}", self.jwt)
        message = stored["chat"]["history"]["messages"][assistant_id]
        record = {"arm": name, "chat_id": chat_id, "seconds": round(time.monotonic() - started, 1),
                  "message": message}  # fmt: skip
        (self.out / f"{name}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1))
        return record

    def stop(self):
        logs = subprocess.run(  # noqa: S603 -- resolved sudo + podman, closed argv
            [self.sudo, self.podman, "logs", f"fv-nl-nucllei-{self.suffix}"],
            check=False, capture_output=True, text=True,
        )  # fmt: skip
        (self.out / "nucllei.log").write_text(logs.stdout + logs.stderr)
        if os.environ.get("NL_KEEP"):
            stack = {"base": self.base, "email": ADMIN[0], "password": self.password,
                     "containers": [f"fv-nl-nucllei-{self.suffix}", f"fv-nl-sandbox-{self.suffix}"],
                     "bridge_pid": self.bridge.pid if self.bridge else None}  # fmt: skip
            # The kept stack's admin login, for its operator alone (M23.1 F3).
            path = self.out / "stack.json"
            path.unlink(missing_ok=True)
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
                file.write(json.dumps(stack, indent=1))
            return
        if self.bridge is not None and self.bridge.poll() is None:
            os.killpg(self.bridge.pid, signal.SIGTERM)
            self.bridge.wait(timeout=30)
        for name in (f"fv-nl-nucllei-{self.suffix}", f"fv-nl-sandbox-{self.suffix}"):
            subprocess.run(  # noqa: S603 -- resolved sudo + podman, closed argv
                [self.sudo, self.podman, "stop", "-t", "5", name], check=False, capture_output=True
            )
        subprocess.run([self.sudo, "rm", "-rf", str(self.data)], check=False)  # noqa: S603


def draw_results(message):
    """Every draw_figure exchange of the stored reply: the call's program + its result."""
    found = []
    for block in message.get("content_blocks") or []:
        if not isinstance(block, dict) or block.get("type") != "tool_calls":
            continue
        calls = {call.get("id"): call for call in block.get("calls") or []}
        for result in block.get("results") or []:
            call = calls.get(result.get("tool_call_id")) or {}
            function = (call.get("function") or {}).get("name") or call.get("name")
            if function == "draw_figure":
                found.append({"call": call, "result": result})
    return found


def verdict(result):
    displays = [item.get("content", "") for item in result.get("display") or []]
    shown = "\n".join(displays)
    if shown.startswith(PASS_TEXTS):
        return "pass", None
    if shown.startswith(FAIL_TEXTS):
        match = REASON.search(shown.split("\n\n", 2)[1] if "\n\n" in shown else shown)
        return "block", match.group(1) if match else None
    return "none", None


def main(llens, out, chosen):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    stack = Stack(llens, out)
    summary = {}
    try:
        stack.start()
        stack.provision()
        repeat = int(os.environ.get("NL_REPEAT", "1"))
        runs = [(f"{n}-{k}" if repeat > 1 else n, n) for n in arms() for k in range(1, repeat + 1)]
        for name, key in runs:
            arm = arms()[key]
            if chosen and key not in chosen:
                continue
            try:
                record = stack.chat(name, arm)
            except Exception as error:
                summary[name] = {"fault": f"{type(error).__name__}: {error}"}
                continue
            draws = draw_results(record["message"])
            first = verdict(draws[0]["result"]) if draws else ("no_call", None)
            summary[name] = {
                "draw_calls": len(draws),
                "first": first[0],
                "first_reason": first[1],
                "last": verdict(draws[-1]["result"])[0] if draws else None,
                "error_kinds": [d["result"].get("error_kind") for d in draws],
                "seconds": record["seconds"],
            }
            print(name, json.dumps(summary[name], ensure_ascii=False), flush=True)
    finally:
        stack.stop()
        (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], set(sys.argv[3:]))
