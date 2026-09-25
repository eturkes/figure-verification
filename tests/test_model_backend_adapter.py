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

from capture.harness import defence
from model_backend.settings import GuidanceSchemaId, Settings

if TYPE_CHECKING:
    from model_backend.engine import GenResult

_SELECTOR_SYSTEM = "Choose a tool. Available Tools: draw_figure"
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
        guided_schema: GuidanceSchemaId | None,
    ) -> GenResult:
        self.calls.append(
            (
                copy.deepcopy(messages),
                {
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "guided_schema": guided_schema,
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


def _completion(  # noqa: PLR0913 - independent request parameters expose selector overrides
    monkeypatch: pytest.MonkeyPatch,
    messages: list[dict[str, str]],
    output: str,
    *,
    temperature: float = 0.75,
    max_tokens: int = 7,
    guided_schema: str | None = "vplot-0.1",
) -> tuple[_RecordingEngine, dict[str, Any]]:
    if "transformers" not in sys.modules:
        importlib.import_module("test_model_backend")
    app = cast("Any", importlib.import_module("model_backend.app"))

    engine = _RecordingEngine(output)
    monkeypatch.setattr(app.Engine, "load", classmethod(lambda _cls, _settings: engine))
    with TestClient(
        app=app.create_app(Settings(structured_output=False, max_tokens=1024))
    ) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "stream": False,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "guided_schema": guided_schema,
            },
        )
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


@pytest.mark.parametrize(
    ("user", "query"),
    [
        ("Query: Draw the requested figure.", "Draw the requested figure."),
        (
            'History:\nUSER: """Earlier Query: decoy"""\nASSISTANT: """old"""\n'
            "Query: Draw the requested figure.",
            "Draw the requested figure.",
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
    monkeypatch: pytest.MonkeyPatch, user: str, query: str, output: str
) -> None:
    """X4: fresh/history selector requests force 512/0.0/None and preserve de-fenced bytes."""
    messages = [
        {"role": "system", "content": _SELECTOR_SYSTEM},
        {"role": "user", "content": user},
    ]
    engine, body = _completion(monkeypatch, messages, output)
    assert engine.calls == [
        (
            [{"role": "user", "content": query}],
            {"temperature": 0.0, "max_tokens": 512, "guided_schema": None},
        )
    ]
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
            {"temperature": 0.25, "max_tokens": 31, "guided_schema": "vplot-0.1"},
        )
    ]
    assert _reply(body) == "ordinary answer"
