# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The `--codex` bridge (`webui/codex_bridge.py`): OpenAI /v1 in, `codex app-server` JSON-RPC out.

Hardware- and network-free: a fake app-server (a script speaking the stdio JSON-RPC the real one
does) records every message it receives under its CODEX_HOME and plays one scripted turn, so each
case asserts what the bridge SENDS — the isolation overrides, the in-memory login, the thread the
model sees — beside what Open WebUI gets back. The real child's behaviour behind these messages
(the captured request, the interrupt ending sampling) is the live record in
`.agent/measurements/luna/README.md`; this file pins the bridge's side of that contract.

webui/ is coverage-excluded; this file imports no `verifier` symbol.
"""

import json
import logging
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import msgspec
import pytest
from litestar import Litestar
from litestar.testing import TestClient

from webui import codex_bridge
from webui.codex_bridge import BridgeSettings, ChatRequest, chunks, completion, create_app, hosts
from webui.settings import Settings

_TOKEN = "access-token-under-test"  # noqa: S105 - fixture value, never a credential
_ACCOUNT = "account-under-test"
_PROGRAM = "import matplotlib.pyplot as plt\nplt.bar(['A'], [1])\nplt.show()"
# What Open WebUI addresses: the launcher's model_backend_url (M23.1 F2).
_URL = "http://127.0.0.1:8001"
_ALLOWED = hosts("127.0.0.1", 8001)
_PARAMETERS = {
    "type": "object",
    "properties": {"program": {"type": "string"}},
    "required": ["program"],
}
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "draw_figure",
            "description": "Draw one chart.",
            "parameters": _PARAMETERS,
        },
    }
]

# The fake app-server: one JSON message per line on stdio, like the real one. It answers the
# bridge's requests, logs every received line to $CODEX_HOME/received.jsonl, and plays the turn
# named in $CODEX_HOME/scenario (tool | text | fail | exit).
_FAKE = """
import json, os, sys
home = os.environ["CODEX_HOME"]
log = open(os.path.join(home, "received.jsonl"), "a")
log.write(json.dumps({"argv": sys.argv[1:], "home": home, "cwd": os.getcwd(),
                      "env": sorted(os.environ)}) + "\\n")
log.flush()

def send(message):
    sys.stdout.write(json.dumps(message) + "\\n")
    sys.stdout.flush()

def scenario():
    with open(os.path.join(home, "scenario")) as f:
        return f.read().strip()

thread = "thread-1"
for line in sys.stdin:
    message = json.loads(line)
    log.write(line)
    log.flush()
    method, ident = message.get("method"), message.get("id")
    if method is None and ident == "srv-r":
        send({"method": "item/completed", "params": {"threadId": thread, "item": {
            "type": "agentMessage", "text": "Refreshed."}}})
        send({"method": "turn/completed", "params": {"threadId": thread,
            "turn": {"status": "completed"}}})
    if method is None or ident is None:
        continue
    if method == "thread/start":
        send({"id": ident, "result": {"thread": {"id": thread}}})
    elif method == "turn/start":
        send({"id": ident, "result": {"turn": {"id": "turn-1", "status": "inProgress"}}})
        kind = scenario()
        if kind == "tool":
            send({"id": "srv-1", "method": "item/tool/call", "params": {
                "threadId": thread, "turnId": "turn-1", "callId": "call_abc", "tool": "draw_figure",
                "arguments": {"program": "PROGRAM"}}})
        elif kind == "text":
            send({"method": "item/completed", "params": {"threadId": thread, "item": {
                "type": "agentMessage", "text": "Done."}}})
            send({"method": "thread/tokenUsage/updated", "params": {"threadId": thread,
                "tokenUsage": {"total": {"inputTokens": 11, "outputTokens": 3}}}})
            send({"method": "turn/completed", "params": {"threadId": thread,
                "turn": {"status": "completed"}}})
        elif kind == "fail":
            send({"method": "error", "params": {"threadId": thread, "willRetry": False,
                "error": {"message": "usage limit reached"}}})
            send({"method": "turn/completed", "params": {"threadId": thread,
                "turn": {"status": "failed", "error": None}}})
        elif kind == "exit":
            sys.exit(3)
        elif kind == "refresh":
            sys.stdout.write("not json at all\\n")
            send({"id": "srv-t", "method": "currentTime/read", "params": {"threadId": thread}})
            send({"id": "srv-r", "method": "account/chatgptAuthTokens/refresh",
                  "params": {"reason": "unauthorized"}})
    elif method == "turn/interrupt":
        send({"id": ident, "result": {}})
        send({"method": "turn/completed", "params": {"threadId": thread,
            "turn": {"status": "interrupted"}}})
    else:
        send({"id": ident, "result": {}})
""".replace("PROGRAM", _PROGRAM.replace("\n", "\\n"))


@pytest.fixture
def bridge(tmp_path: Path) -> Iterator[tuple[TestClient[Litestar], Path, list[str]]]:
    fake = tmp_path / "codex"
    fake.write_text(f"#!{sys.executable}\n{_FAKE}", encoding="utf-8")
    fake.chmod(0o755)
    auth = tmp_path / "auth.json"
    auth.write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": _TOKEN,
                    "account_id": _ACCOUNT,
                    "refresh_token": "refresh-never-sent",
                }
            }
        ),
        encoding="utf-8",
    )
    home = tmp_path / "home"
    exits: list[str] = []
    settings = BridgeSettings(codex_bin=str(fake), auth_file=auth, home=home)
    app = create_app("gpt-6-luna", settings, lambda: exits.append("exit"), allowed=_ALLOWED)
    home.mkdir()
    (home / "scenario").write_text("tool", encoding="utf-8")
    with TestClient(app=app, base_url=_URL) as client:
        yield client, home, exits


def _received(home: Path) -> list[dict[str, object]]:
    lines = (home / "received.jsonl").read_text(encoding="utf-8").splitlines()
    return [cast("dict[str, object]", json.loads(line)) for line in lines]


def _calls(home: Path) -> dict[str, dict[str, object]]:
    return {
        str(m["method"]): cast("dict[str, object]", m.get("params") or {})
        for m in _received(home)[1:]
        if "method" in m
    }


def _request(**extra: object) -> dict[str, object]:
    return {
        "model": "gpt-6-luna",
        "messages": [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "Chart A as 1."},
        ],
        "tools": _TOOLS,
        **extra,
    }


def test_the_child_runs_isolated_with_every_context_layer_off(
    bridge: tuple[TestClient[Litestar], Path, list[str]],
) -> None:
    """The operator's ~/.codex never reaches the model: own CODEX_HOME + HOME, the closed override
    list, the catalog entry without code mode or multi-agent, and a token login that sends no
    refresh token."""
    _, home, _ = bridge
    start = _received(home)[0]
    argv = cast("list[str]", start["argv"])
    assert argv[0] == "app-server"
    overrides = [argv[i + 1] for i, arg in enumerate(argv) if arg == "-c"]
    assert overrides[:-1] == [
        "include_environment_context=false",
        "include_permissions_instructions=false",
        "include_apps_instructions=false",
        "include_collaboration_mode_instructions=false",
        "features.code_mode_host=false",
        "features.multi_agent=false",
        "features.shell_tool=false",
        "features.unified_exec=false",
        "features.skill_search=false",
        "skills.bundled.enabled=false",
        "features.plugins=false",
        "features.apps=false",
        "features.goals=false",
        "features.image_generation=false",
        "tools.experimental_request_user_input={enabled=false}",
        'web_search="disabled"',
        "analytics.enabled=false",
    ]
    catalog_path = home.resolve() / "catalog.json"
    assert overrides[-1] == f'model_catalog_json="{catalog_path}"'
    entry = json.loads(catalog_path.read_text(encoding="utf-8"))["models"][0]
    assert entry["slug"] == "gpt-6-luna"
    assert entry["base_instructions"] == ""
    assert "tool_mode" not in entry
    assert "multi_agent_version" not in entry
    assert start["home"] == str(home.resolve())
    assert start["cwd"] == str(home.resolve())
    assert "HOME" in cast("list[str]", start["env"])
    login = _calls(home)["account/login/start"]
    assert login == {
        "type": "chatgptAuthTokens",
        "accessToken": _TOKEN,
        "chatgptAccountId": _ACCOUNT,
    }
    initialize = _calls(home)["initialize"]
    assert initialize["capabilities"] == {"experimentalApi": True}


def test_a_tool_call_ends_the_completion_and_interrupts_the_turn(
    bridge: tuple[TestClient[Litestar], Path, list[str]],
) -> None:
    client, home, _ = bridge
    reply = client.post("/v1/chat/completions", json=_request())
    assert reply.status_code == 200
    body = reply.json()
    choice = body["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"] == [
        {
            "id": "call_abc",
            "type": "function",
            "function": {"name": "draw_figure", "arguments": json.dumps({"program": _PROGRAM})},
        }
    ]
    calls = _calls(home)
    thread = calls["thread/start"]
    assert thread["baseInstructions"] == "Be brief."
    assert thread["ephemeral"] is True
    assert thread["environments"] == []
    assert thread["dynamicTools"] == [
        {
            "type": "function",
            "name": "draw_figure",
            "description": "Draw one chart.",
            "inputSchema": _PARAMETERS,
        }
    ]
    assert calls["thread/inject_items"]["items"] == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Chart A as 1."}],
        }
    ]
    # No request effort: the bridge's default, `low` (user: this repo's setting).
    assert calls["turn/start"] == {"threadId": "thread-1", "input": [], "effort": "low"}
    # ORDER: the interrupt goes out before the tool call's answer, so the model never samples on.
    received = _received(home)
    interrupt = next(i for i, m in enumerate(received) if m.get("method") == "turn/interrupt")
    answer = next(i for i, m in enumerate(received) if m.get("id") == "srv-1")
    assert interrupt < answer
    assert received[answer]["result"] == {
        "contentItems": [{"type": "inputText", "text": "stopped"}],
        "success": False,
    }
    assert "thread/unsubscribe" in calls


def test_a_streamed_reply_carries_the_call_after_an_empty_content_delta(
    bridge: tuple[TestClient[Litestar], Path, list[str]],
) -> None:
    client, _, _ = bridge
    reply = client.post("/v1/chat/completions", json=_request(stream=True))
    assert reply.status_code == 200
    assert reply.headers["content-type"].startswith("text/event-stream")
    events = [line[6:] for line in reply.text.split("\n\n") if line.startswith("data: ")]
    assert events[-1] == "[DONE]"
    deltas = [json.loads(event)["choices"][0] for event in events[:-1]]
    assert deltas[0]["delta"] == {"role": "assistant", "content": ""}
    assert deltas[1]["delta"]["tool_calls"][0]["index"] == 0
    assert deltas[1]["delta"]["tool_calls"][0]["function"]["name"] == "draw_figure"
    assert deltas[-1]["finish_reason"] == "tool_calls"


def test_history_replays_the_tool_round_and_text_turns_stop(
    bridge: tuple[TestClient[Litestar], Path, list[str]],
) -> None:
    client, home, _ = bridge
    (home / "scenario").write_text("text", encoding="utf-8")
    arguments = json.dumps({"program": _PROGRAM})
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "Chart A as 1."}]},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_abc",
                    "type": "function",
                    "function": {"name": "draw_figure", "arguments": arguments},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_abc", "content": "sent"},
    ]
    reply = client.post(
        "/v1/chat/completions",
        json={"messages": messages, "tools": _TOOLS, "reasoning_effort": "high"},
    )
    assert reply.status_code == 200
    body = reply.json()
    assert body["choices"][0] == {
        "index": 0,
        "message": {"role": "assistant", "content": "Done."},
        "finish_reason": "stop",
    }
    assert body["usage"] == {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14}
    calls = _calls(home)
    assert calls["thread/start"]["baseInstructions"] == ""
    assert calls["thread/inject_items"]["items"] == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Chart A as 1."}],
        },
        {
            "type": "function_call",
            "call_id": "call_abc",
            "name": "draw_figure",
            "arguments": arguments,
        },
        {"type": "function_call_output", "call_id": "call_abc", "output": "sent"},
    ]
    assert calls["turn/start"] == {"threadId": "thread-1", "input": [], "effort": "high"}


def test_a_failed_turn_is_an_http_error_naming_the_cause(
    bridge: tuple[TestClient[Litestar], Path, list[str]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, home, _ = bridge
    (home / "scenario").write_text("fail", encoding="utf-8")
    with caplog.at_level(logging.INFO, logger="webui.codex_bridge"):
        reply = client.post("/v1/chat/completions", json=_request())
    assert reply.status_code == 502
    assert reply.json()["error"]["message"] == "codex: turn failed: usage limit reached"
    assert _TOKEN not in caplog.text


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"messages": [{"role": "tool-x", "content": "x"}]}, "role"),
        ({"messages": [{"role": "user", "content": [{"type": "file", "file": {}}]}]}, "'file'"),
        ({"messages": [{"role": "user", "content": "x"}], "reasoning_effort": "extreme"}, "effort"),
    ],
    ids=["unknown-role", "file-part", "unknown-effort"],
)
def test_a_request_the_bridge_cannot_carry_is_refused_before_any_thread(
    bridge: tuple[TestClient[Litestar], Path, list[str]],
    body: dict[str, object],
    fragment: str,
) -> None:
    client, home, _ = bridge
    reply = client.post("/v1/chat/completions", json=body)
    assert reply.status_code == 400
    assert fragment in reply.json()["error"]["message"]
    assert "thread/start" not in _calls(home)


def test_a_dead_child_fails_the_completion_and_ends_the_bridge(
    bridge: tuple[TestClient[Litestar], Path, list[str]],
) -> None:
    client, home, exits = bridge
    (home / "scenario").write_text("exit", encoding="utf-8")
    reply = client.post("/v1/chat/completions", json=_request())
    assert reply.status_code == 502
    assert "exited" in reply.json()["error"]["message"]
    assert exits == ["exit"]


def test_models_lists_the_one_served_model(
    bridge: tuple[TestClient[Litestar], Path, list[str]],
) -> None:
    client, _, _ = bridge
    assert [model["id"] for model in client.get("/v1/models").json()["data"]] == ["gpt-6-luna"]


def test_m23_f2_a_cross_site_or_rebound_request_reaches_no_thread(
    bridge: tuple[TestClient[Litestar], Path, list[str]],
) -> None:
    """The bridge spends the operator's subscription and authenticates no caller. A page in the
    operator's browser posts `text/plain` to loopback with no CORS preflight; a DNS-rebound page
    names its own domain in `Host`, on any route. Neither starts a thread; Open WebUI's own request
    (JSON, the bind name) still does."""
    client, home, _ = bridge
    body = json.dumps(_request())
    plain = client.post(
        "/v1/chat/completions", content=body, headers={"content-type": "text/plain"}
    )
    rebound = client.post(
        "/v1/chat/completions", json=_request(), headers={"host": "rebound.example:8001"}
    )
    listed = client.get("/v1/models", headers={"host": "rebound.example:8001"})
    assert (plain.status_code, rebound.status_code, listed.status_code) == (415, 400, 400)
    assert "thread/start" not in _calls(home)
    assert client.post("/v1/chat/completions", json=_request()).status_code == 200
    assert "thread/start" in _calls(home)


def test_m23_f2_the_bridge_answers_its_bind_name_and_the_loopback_spellings() -> None:
    assert hosts("127.0.0.1", 8001) == ("127.0.0.1:8001", "localhost:8001", "[::1]:8001")
    assert hosts("::1", 9) == ("[::1]:9", "127.0.0.1:9", "localhost:9")
    assert hosts("localhost", 5) == ("localhost:5", "127.0.0.1:5", "[::1]:5")


def test_the_bridge_refuses_a_model_its_catalog_lacks(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="gpt-6-luna"):
        create_app(
            "Qwen2.5-Coder-0.5B-Instruct",
            BridgeSettings(home=tmp_path),
            lambda: None,
            allowed=_ALLOWED,
        )


@pytest.mark.parametrize("effort", ["", "low", "max"])
def test_settings_admit_the_model_efforts(effort: str) -> None:
    assert BridgeSettings(effort=effort).effort == effort


def test_the_default_effort_is_low_and_empty_means_the_model_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User: `low` for this repo; an empty CODEX_BRIDGE_EFFORT sends none (the model's `medium`)."""
    monkeypatch.delenv("CODEX_BRIDGE_EFFORT", raising=False)
    assert BridgeSettings.from_env().effort == "low"
    monkeypatch.setenv("CODEX_BRIDGE_EFFORT", "")
    assert BridgeSettings.from_env().effort == ""
    monkeypatch.setenv("CODEX_BRIDGE_EFFORT", "high")
    assert BridgeSettings.from_env().effort == "high"


@pytest.mark.parametrize("effort", ["none", "MAX", "minimal"])
def test_settings_refuse_an_unknown_effort(effort: str) -> None:
    with pytest.raises(ValueError, match="CODEX_BRIDGE_EFFORT"):
        BridgeSettings(effort=effort)


def test_wire_shapes_without_a_call_or_usage() -> None:
    outcome = codex_bridge.Outcome("Hello.", None, {})
    body = completion(outcome, "gpt-6-luna")
    assert body["choices"] == [
        {"index": 0, "message": {"role": "assistant", "content": "Hello."}, "finish_reason": "stop"}
    ]
    assert "usage" not in body
    events = [json.loads(e[6:]) for e in (c.decode() for c in chunks(outcome, "m")) if "{" in e]
    assert [event["choices"][0]["delta"] for event in events] == [
        {"role": "assistant", "content": ""},
        {"content": "Hello."},
        {},
    ]
    assert "usage" not in events[-1]


def test_image_parts_reach_the_model_as_input_images() -> None:
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is this?"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                ],
            }
        ]
    }
    request = msgspec.json.decode(json.dumps(body), type=ChatRequest)
    assert codex_bridge.history(request.messages) == [
        {
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": "What is this?"},
                {"type": "input_image", "image_url": "data:image/png;base64,AAAA"},
            ],
        }
    ]


def test_the_dump_dir_records_each_request_with_its_outcome(tmp_path: Path) -> None:
    """Measurement aid: what Open WebUI sent the model (the inlet's rewrite included) + the call."""
    fake = tmp_path / "codex"
    fake.write_text(f"#!{sys.executable}\n{_FAKE}", encoding="utf-8")
    fake.chmod(0o755)
    auth = tmp_path / "auth.json"
    auth.write_text(
        json.dumps({"tokens": {"access_token": _TOKEN, "account_id": _ACCOUNT}}), encoding="utf-8"
    )
    home, dump = tmp_path / "home", tmp_path / "dump"
    home.mkdir()
    (home / "scenario").write_text("tool", encoding="utf-8")
    settings = BridgeSettings(codex_bin=str(fake), auth_file=auth, home=home, dump_dir=dump)
    app = create_app("gpt-6-luna", settings, lambda: None, allowed=_ALLOWED)
    with TestClient(app=app, base_url=_URL) as client:
        assert client.post("/v1/chat/completions", json=_request()).status_code == 200
    (record,) = [json.loads(path.read_text(encoding="utf-8")) for path in dump.iterdir()]
    assert record["request"] == _request()
    assert record["call"] == ["call_abc", "draw_figure", json.dumps({"program": _PROGRAM})]
    assert _TOKEN not in json.dumps(record)


def test_a_token_refresh_rereads_the_auth_file_and_noise_is_dropped(
    bridge: tuple[TestClient[Litestar], Path, list[str]],
) -> None:
    """A 401 inside the child asks for a fresh token: the bridge answers from the auth file as it
    is NOW (the operator's Codex refreshed it), answers the clock, and a non-JSON stdout line costs
    nothing but a log record."""
    client, home, exits = bridge
    auth = home.parent / "auth.json"
    fresh = {"tokens": {"access_token": "renewed-token", "account_id": _ACCOUNT}}
    auth.write_text(json.dumps(fresh), encoding="utf-8")
    (home / "scenario").write_text("refresh", encoding="utf-8")
    reply = client.post("/v1/chat/completions", json=_request())
    assert reply.status_code == 200
    assert reply.json()["choices"][0]["message"]["content"] == "Refreshed."
    answers = {m.get("id"): m for m in _received(home) if "method" not in m}
    assert answers["srv-r"]["result"] == {
        "accessToken": "renewed-token",
        "chatgptAccountId": _ACCOUNT,
    }
    assert isinstance(cast("dict[str, int]", answers["srv-t"]["result"])["currentTimeAt"], int)
    assert exits == []


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "bridge.example"])  # noqa: S104
def test_the_bridge_refuses_a_bind_beyond_loopback(host: str) -> None:
    """No caller is authenticated and every call spends the operator's subscription."""
    settings = Settings(model_id="gpt-6-luna", model_backend_url=f"http://{host}:8001/v1")
    with pytest.raises(ValueError, match="loopback"):
        codex_bridge.serve(settings)
