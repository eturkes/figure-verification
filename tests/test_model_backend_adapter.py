# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""X4: a demo-only selector carries de-fenced model bytes as one tool call."""

from __future__ import annotations

import copy
import importlib
import json
import sys
from typing import TYPE_CHECKING, Any, cast

import pytest
from litestar.testing import TestClient

from model_backend.adapter import defence
from model_backend.settings import Settings

if TYPE_CHECKING:
    from model_backend.engine import GenResult

_SELECTOR_SYSTEM = "Choose a tool. Available Tools: draw_figure"
# Settings' default bind, the origin the backend answers (M23.1 F4).
_URL = "http://127.0.0.1:8001"
_PROGRAM = 'print("日本語 {brace} \\\\path and a \'quote\'")\nprint("next line")\n'


class _RecordingEngine:
    def __init__(self, output: str) -> None:
        self.output = output
        self.calls: list[tuple[list[dict[str, str]], dict[str, object]]] = []

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> GenResult:
        self.calls.append(
            (
                copy.deepcopy(messages),
                {
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
        )
        engine_module = cast("Any", importlib.import_module("model_backend.engine"))
        return cast(
            "GenResult",
            engine_module.GenResult(
                text=self.output,
                prompt_tokens=3,
                completion_tokens=len(self.output.split()),
                finish_reason="stop",
            ),
        )


class _CappedEngine(_RecordingEngine):
    """Refuses, as the real engine does before generating, a prompt over `limit` messages."""

    def __init__(self, output: str, limit: int, error_type: str = "prompt_too_long") -> None:
        super().__init__(output)
        self.limit = limit
        self.error_type = error_type

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> GenResult:
        if len(messages) <= self.limit:
            return super().generate(messages, temperature=temperature, max_tokens=max_tokens)
        self.calls.append((copy.deepcopy(messages), {"refused": self.error_type}))
        engine_module = cast("Any", importlib.import_module("model_backend.engine"))
        message = "over the cap"
        raise engine_module.BackendError(message, status=400, error_type=self.error_type)


def _post(
    monkeypatch: pytest.MonkeyPatch,
    messages: list[dict[str, str]],
    engine: _RecordingEngine,
    *,
    temperature: float = 0.75,
    max_tokens: int = 7,
) -> Any:
    if "transformers" not in sys.modules:
        importlib.import_module("test_model_backend")
    app = cast("Any", importlib.import_module("model_backend.app"))

    monkeypatch.setattr(app.Engine, "load", classmethod(lambda _cls, _settings: engine))
    with TestClient(app=app.create_app(Settings(max_tokens=1024)), base_url=_URL) as client:
        return client.post(
            "/v1/chat/completions",
            json={
                "stream": False,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )


def _completion(
    monkeypatch: pytest.MonkeyPatch,
    messages: list[dict[str, str]],
    output: str,
    *,
    temperature: float = 0.75,
    max_tokens: int = 7,
) -> tuple[_RecordingEngine, dict[str, Any]]:
    engine = _RecordingEngine(output)
    response = _post(monkeypatch, messages, engine, temperature=temperature, max_tokens=max_tokens)
    assert response.status_code == 200, response.text
    return engine, response.json()


def _reply(body: dict[str, Any]) -> str:
    choices = body["choices"]
    assert len(choices) == 1
    message = choices[0]["message"]
    assert message["role"] == "assistant"
    reply: str = message["content"]
    assert isinstance(reply, str)
    return reply


_QUERY = {"role": "user", "content": "Draw the requested figure."}


@pytest.mark.parametrize(
    ("user", "prompt"),
    [
        ("Query: Draw the requested figure.", [_QUERY]),
        (
            'History:\nUSER: """Earlier Query: decoy"""\nASSISTANT: """old"""\n'
            "Query: Draw the requested figure.",
            [
                {"role": "user", "content": "Earlier Query: decoy"},
                {"role": "assistant", "content": "old"},
                _QUERY,
            ],
        ),
    ],
    ids=["fresh", "history-last-query"],
)
@pytest.mark.parametrize(
    "output",
    [
        _PROGRAM,
        "```python\n" + _PROGRAM + "```\n",
        "```python\n" + _PROGRAM,
        "",
    ],
    ids=["bare", "fenced", "unterminated-fence", "empty"],
)
def test_x4_selector_reuses_capture_params_and_round_trips_program(
    monkeypatch: pytest.MonkeyPatch, user: str, prompt: list[dict[str, str]], output: str
) -> None:
    """X4: fresh/history selector requests force 512/0.0, carry the history turns before the
    final query and preserve de-fenced bytes."""
    messages = [
        {"role": "system", "content": _SELECTOR_SYSTEM},
        {"role": "user", "content": user},
    ]
    engine, body = _completion(monkeypatch, messages, output)
    assert engine.calls == [(prompt, {"temperature": 0.0, "max_tokens": 512})]
    reply = _reply(body)
    assert reply
    parsed = json.loads(reply)
    assert parsed == {
        "tool_calls": [{"name": "draw_figure", "parameters": {"program": defence(output)[1]}}]
    }


@pytest.mark.parametrize(
    "messages",
    [
        [{"role": "user", "content": "Query: draw"}],
        [
            {"role": "system", "content": "Available Items: draw_figure"},
            {"role": "user", "content": "Query: draw"},
        ],
        [
            {"role": "system", "content": _SELECTOR_SYSTEM},
            {"role": "user", "content": "Query: first"},
            {"role": "user", "content": "Query: second"},
        ],
        [
            {"role": "system", "content": _SELECTOR_SYSTEM},
            {"role": "user", "content": "draw without the Query prefix"},
        ],
    ],
    ids=["no-system", "no-marker", "two-users", "bare-user-prompt"],
)
def test_x4_non_selector_keeps_original_generation_and_reply(
    monkeypatch: pytest.MonkeyPatch, messages: list[dict[str, str]]
) -> None:
    """X4: a near-miss request keeps its messages, requested parameters and raw reply."""
    engine, body = _completion(
        monkeypatch, messages, "ordinary answer", temperature=0.25, max_tokens=31
    )
    assert engine.calls == [
        (
            messages,
            {"temperature": 0.25, "max_tokens": 31},
        )
    ]
    assert _reply(body) == "ordinary answer"


def _selector(user: str) -> list[dict[str, str]]:
    return [{"role": "system", "content": _SELECTOR_SYSTEM}, {"role": "user", "content": user}]


# Open WebUI's own shape: up to four `ROLE: """content"""` entries joined by newlines.
_FOLLOW_UP = (
    'History:\nUSER: """Chart the total revenue of each region using bars."""\n'
    'ASSISTANT: """Figure verification passed\n\nBars `revenue`: the sum of `revenue`."""\n'
    "Query: Change the color of the bars to red"
)
_FOLLOW_UP_TURNS = [
    {"role": "user", "content": "Chart the total revenue of each region using bars."},
    {
        "role": "assistant",
        "content": "Figure verification passed\n\nBars `revenue`: the sum of `revenue`.",
    },
    {"role": "user", "content": "Change the color of the bars to red"},
]


@pytest.mark.parametrize(
    ("user", "prompt"),
    [
        (_FOLLOW_UP, _FOLLOW_UP_TURNS),
        (
            'History:\nSYSTEM: """Be brief."""\nUSER: """first"""\nTOOL: """sent"""\n'
            'ASSISTANT: """a "quoted" reply"""\nQuery: next',
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": 'a "quoted" reply'},
                {"role": "user", "content": "next"},
            ],
        ),
        (
            'History:\nUSER: """"""\nQuery: next',
            [{"role": "user", "content": ""}, {"role": "user", "content": "next"}],
        ),
        ("History:\nan earlier line\nQuery: next", [{"role": "user", "content": "next"}]),
        ('History:\nUSER: """first"""trailing\nQuery: next', [{"role": "user", "content": "next"}]),
        (
            'History:\nUSER: """first"""\nUSER: """second"""tail\nQuery: next',
            [{"role": "user", "content": "next"}],
        ),
    ],
    ids=[
        "follow-up",
        "closed-roles",
        "empty-content",
        "unparsable",
        "entry-tail",
        "partial-entries",
    ],
)
def test_x4_selector_history_becomes_chat_turns(
    monkeypatch: pytest.MonkeyPatch, user: str, prompt: list[dict[str, str]]
) -> None:
    """X4: USER + ASSISTANT entries reach the model as turns before the query, every other role
    is dropped, and a history that is not wholly entries leaves the query alone."""
    engine, _body = _completion(monkeypatch, _selector(user), _PROGRAM)
    assert engine.calls == [(prompt, {"temperature": 0.0, "max_tokens": 512})]


@pytest.mark.parametrize(
    ("limit", "prompts"),
    [
        (3, [_FOLLOW_UP_TURNS]),
        (2, [_FOLLOW_UP_TURNS, _FOLLOW_UP_TURNS[1:]]),
        (1, [_FOLLOW_UP_TURNS, _FOLLOW_UP_TURNS[1:], _FOLLOW_UP_TURNS[2:]]),
    ],
    ids=["fits", "drops-oldest", "query-alone"],
)
def test_x4_selector_over_the_cap_drops_the_oldest_turn(
    monkeypatch: pytest.MonkeyPatch, limit: int, prompts: list[list[dict[str, str]]]
) -> None:
    """X4: a refused prompt_too_long retries without its oldest turn until the prompt fits."""
    engine = _CappedEngine(_PROGRAM, limit)
    response = _post(monkeypatch, _selector(_FOLLOW_UP), engine)
    assert response.status_code == 200, response.text
    assert [messages for messages, _parameters in engine.calls] == prompts
    assert json.loads(_reply(response.json())) == {
        "tool_calls": [{"name": "draw_figure", "parameters": {"program": _PROGRAM}}]
    }


@pytest.mark.parametrize(
    ("limit", "error_type", "calls"),
    [(0, "prompt_too_long", 3), (2, "response_too_large", 1)],
    ids=["query-alone-too-long", "other-error"],
)
def test_x4_selector_refusal_past_the_query_alone_reaches_the_caller(
    monkeypatch: pytest.MonkeyPatch, limit: int, error_type: str, calls: int
) -> None:
    """X4: a query alone over the cap, or any other backend error, answers that error at once."""
    engine = _CappedEngine(_PROGRAM, limit, error_type)
    response = _post(monkeypatch, _selector(_FOLLOW_UP), engine)
    assert response.status_code == 400
    assert response.json() == {"error": {"message": "over the cap", "type": error_type}}
    assert len(engine.calls) == calls
