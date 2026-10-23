# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Codex context probe: what the model receives through the `--codex` bridge.

Law = `.claude/rules/codex-bridge.md` (rerun after every codex-cli upgrade). One completion through
`webui/codex_bridge.py` as shipped (`_CONFIG` + `_CATALOG` + `_THREAD`, reached only through `Codex`
+ `complete`) over a request of one system text, one user text and one tool; a wrapper around
<codex-bin> adds what the probe needs. Default: the child's provider = a loopback mock Responses
server recording each request body. `--chatgpt`: the ChatGPT backend under RUST_LOG=trace (ONE
completion on the operator's subscription); the backend's `response.created` echo of the turn
lists the tools the model saw — the provider-gated ones (`image_gen`) included, which a mock
provider never receives. The turn's echo = the last one: a warm-up echo with no tools comes first.
The trace can hold the auth header ⇒ it stays in a 0700 temp dir removed on exit, and the probe
prints parsed fields alone. Exit 0 = the model sees the request's tool alone, no instructions field
and (mock) exactly the system + user messages; 1 = anything more (printed); 2 = nothing captured.

usage: codex_context.py <codex-bin> [--chatgpt]
"""

import asyncio
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import msgspec

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from webui.codex_bridge import BridgeSettings, ChatRequest, Codex, CodexError, complete  # noqa: E402

SYSTEM, USER, TOOL = "SYSTEM-MARKER", "USER-MARKER", "draw_figure"
REQUEST = {
    "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}],
    "tools": [
        {
            "type": "function",
            "function": {
                "name": TOOL,
                "description": "TOOL-MARKER",
                "parameters": {
                    "type": "object",
                    "properties": {"program": {"type": "string"}, "note": {"type": "string"}},
                    "required": ["program"],
                },
            },
        }
    ],
}
EXPECTED: dict[str, object] = {"instructions": None, "tools": [TOOL]}
EXPECTED_MOCK: dict[str, object] = {
    **EXPECTED,
    "messages": [["developer", SYSTEM], ["user", USER]],
    "other_items": [],
}
# The smallest stream the child accepts as a finished turn.
EVENTS = [
    {"type": "response.created", "response": {"id": "resp_1"}},
    {
        "type": "response.output_item.done",
        "output_index": 0,
        "item": {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "ok", "annotations": []}],
        },
    },
    {
        "type": "response.completed",
        "response": {
            "id": "resp_1",
            "output": [],
            "usage": {
                "input_tokens": 1,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens": 1,
                "output_tokens_details": {"reasoning_tokens": 0},
                "total_tokens": 2,
            },
        },
    },
]
STREAM = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in EVENTS).encode()


def _mock(bodies: list[object]) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("content-length", "0")))
            if self.headers.get("content-encoding") == "zstd":
                from compression import zstd  # noqa: PLC0415 - CPython 3.14 stdlib

                body = zstd.decompress(body)
            if self.path.endswith("/responses"):
                bodies.append(json.loads(body))
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(STREAM)))
            self.end_headers()
            self.wfile.write(STREAM)

        def log_message(self, *_: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _names(tools: object) -> list[str]:
    names: list[str] = []
    for tool in tools if isinstance(tools, list) else []:
        if tool.get("type") == "namespace":
            names += _names(tool.get("tools"))
        else:
            names.append(str(tool.get("name") or tool.get("type")))
    return names


def mock_view(body: dict[str, object]) -> dict[str, object]:
    """Instructions, every tool name, the messages + any other input item of one request body."""
    tools, messages, other = _names(body.get("tools")), [], []
    for item in body.get("input") or []:
        if item.get("type") == "additional_tools":
            tools += _names(item.get("tools"))
        elif item.get("type") == "message":
            text = "".join(str(part.get("text", "")) for part in item.get("content") or [])
            messages.append([item.get("role"), text])
        else:
            other.append(item.get("type"))
    view = {"instructions": body.get("instructions"), "tools": tools}
    return {**view, "messages": messages, "other_items": other}


def echo_view(trace: Path) -> dict[str, object] | None:
    """Instructions + tool names of the last `response.created` echo in a trace log."""
    decoder, last = json.JSONDecoder(), None
    for line in trace.read_text(encoding="utf-8", errors="replace").splitlines():
        start = line.find('{"type":"response.created"')
        if start >= 0:
            last = decoder.raw_decode(line[start:])[0]["response"]
    if last is None:
        return None
    return {"instructions": last.get("instructions"), "tools": _names(last.get("tools"))}


async def _complete(binary: str, home: Path) -> None:
    codex = Codex(BridgeSettings(codex_bin=binary, home=home), lambda: None)
    await codex.start()
    try:
        request = msgspec.json.decode(json.dumps(REQUEST), type=ChatRequest)
        await asyncio.wait_for(complete(codex, request, "gpt-6-luna", "low"), 180)
    except (CodexError, TimeoutError) as exc:
        print(f"completion: {exc}")
    finally:
        await codex.stop()


def _wrapper(directory: Path, line: str) -> str:
    path = directory / "codex"
    path.write_text(f"#!/bin/sh\n{line}\n", encoding="utf-8")
    path.chmod(0o700)
    return str(path)


def main() -> int:
    """Run one probe; print the version, the view and PASS/FAIL."""
    if len(sys.argv) not in {2, 3} or sys.argv[2:] not in ([], ["--chatgpt"]):
        print(__doc__.strip().splitlines()[-1])
        return 2
    # Absolute: the child runs in its own home, where a relative path names nothing.
    binary, chatgpt = shutil.which(sys.argv[1]), sys.argv[2:] == ["--chatgpt"]
    if binary is None:
        print(f"{sys.argv[1]}: no such executable")
        return 2
    binary = str(Path(binary).resolve())
    version = subprocess.run([binary, "--version"], capture_output=True, text=True, check=True)  # noqa: S603
    print(version.stdout.strip(), "chatgpt" if chatgpt else "mock")
    # Under the repo (gitignored), as the bridge's home is: Codex makes no PATH helpers in /tmp.
    (ROOT / ".scratch").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / ".scratch") as temp:
        directory = Path(temp)
        if chatgpt:
            trace = directory / "trace.log"
            line = f'RUST_LOG=trace exec {shlex.quote(binary)} "$@" 2>>{shlex.quote(str(trace))}'
            asyncio.run(_complete(_wrapper(directory, line), directory / "home"))
            view, expected = echo_view(trace) if trace.exists() else None, EXPECTED
        else:
            bodies: list[object] = []
            server = _mock(bodies)
            url = f"http://127.0.0.1:{server.server_address[1]}/v1"
            provider = (
                f'model_providers.capture={{name="capture",base_url="{url}",wire_api="responses"}}'
            )
            overrides = ("-c", 'model_provider="capture"', "-c", provider)
            line = f'exec {shlex.quote(binary)} "$@" {shlex.join(overrides)}'
            asyncio.run(_complete(_wrapper(directory, line), directory / "home"))
            server.shutdown()
            view = mock_view(bodies[-1]) if bodies else None
            expected = EXPECTED_MOCK
    if view is None:
        print("nothing captured")
        return 2
    print(json.dumps(view, ensure_ascii=False))
    print("PASS" if view == expected else f"FAIL: expected {json.dumps(expected)}")
    return 0 if view == expected else 1


if __name__ == "__main__":
    sys.exit(main())
