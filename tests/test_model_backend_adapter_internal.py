# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Near-miss selector shapes for the demo-only model backend adapter."""

import importlib
import json
import sys
from dataclasses import dataclass
from typing import Any, cast

import pytest
from litestar import Litestar
from litestar.testing import TestClient

from model_backend.settings import GuidanceSchemaId, Settings


@dataclass(frozen=True)
class _Gen:
    text: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str


class _RecordingEngine:
    def __init__(self, text: str = "ordinary reply") -> None:
        self.text = text
        self.calls: list[tuple[list[dict[str, str]], float, int, GuidanceSchemaId | None]] = []

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        guided_schema: GuidanceSchemaId | None,
    ) -> _Gen:
        self.calls.append((messages, temperature, max_tokens, guided_schema))
        return _Gen(text=self.text, prompt_tokens=3, completion_tokens=2, finish_reason="length")


def _test_app(monkeypatch: pytest.MonkeyPatch, engine: _RecordingEngine) -> Litestar:
    # Pytest's importlib collector may import this module before test_model_backend. At test time
    # collection is complete, so its native fakes are available without a duplicate import.
    if "transformers" not in sys.modules:
        importlib.import_module("test_model_backend")
    app = cast("Any", importlib.import_module("model_backend.app"))
    monkeypatch.setattr(app.Engine, "load", classmethod(lambda _cls, _settings: engine))
    return cast("Litestar", app.create_app(Settings(max_tokens=1024)))


@pytest.mark.parametrize(
    "messages",
    [
        [{"role": "user", "content": "Available Tools: Query: draw a chart"}],
        [{"role": "system", "content": "tools"}, {"role": "user", "content": "Query: chart"}],
        [{"role": "system", "content": "Available Tools:"}, {"role": "user", "content": "chart"}],
        [
            {"role": "system", "content": "Available Tools:"},
            {"role": "assistant", "content": "Query: chart"},
        ],
        [
            {"role": "system", "content": "Available Tools:"},
            {"role": "user", "content": "Query: chart"},
            {"role": "assistant", "content": "tail"},
        ],
        [
            {"role": "system", "content": "Available Tools:"},
            {"role": "user", "content": "History:\nQuery: chart"},
        ],
        [
            {"role": "system", "content": "Available Tools:"},
            {"role": "user", "content": "History:\nUSER: old Query: chart"},
        ],
        [
            {"role": "system", "content": "Available Tools:"},
            {"role": "user", "content": "Query:chart"},
        ],
        [
            {"role": "system", "content": "Available Tools:"},
            {"role": "user", "content": "Prefix Query: chart"},
        ],
    ],
    ids=[
        "marker-in-user",
        "missing-marker",
        "bare-prompt",
        "assistant-query",
        "extra-message",
        "empty-history",
        "history-without-final-query",
        "missing-space",
        "query-inside-prose",
    ],
)
def test_selector_near_misses_preserve_ordinary_generation(
    monkeypatch: pytest.MonkeyPatch, messages: list[dict[str, str]]
) -> None:
    engine = _RecordingEngine()
    with TestClient(app=_test_app(monkeypatch, engine)) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "messages": messages,
                "temperature": 0.375,
                "max_tokens": 7,
                "guided_schema": "vplot-0.1",
            },
        )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "ordinary reply"
    assert engine.calls == [(messages, 0.375, 7, "vplot-0.1")]


@pytest.mark.parametrize(
    ("raw", "program"),
    [
        ("```python\nprint('🦊\\\\')\n```", "print('🦊\\\\')\n"),
        ("```python\nprint({1: 2})", "print({1: 2})"),
        ("", ""),
    ],
    ids=["unicode-backslash", "unterminated-fence", "empty-program"],
)
def test_selector_wraps_source_even_when_empty(
    monkeypatch: pytest.MonkeyPatch, raw: str, program: str
) -> None:
    engine = _RecordingEngine(raw)
    messages = [
        {"role": "system", "content": "Available Tools: draw_figure"},
        {"role": "user", "content": 'History:\nUSER: """earlier Query: ignore"""\nQuery: chart'},
    ]

    with TestClient(app=_test_app(monkeypatch, engine)) as client:
        response = client.post(
            "/v1/chat/completions",
            json={"messages": messages, "temperature": 0.9, "max_tokens": 7},
        )

    assert response.status_code == 200
    choice = response.json()["choices"][0]
    content = choice["message"]["content"]
    assert content
    assert json.loads(content) == {
        "tool_calls": [{"name": "draw_figure", "parameters": {"program": program}}]
    }
    assert choice["finish_reason"] == "length"
    assert engine.calls == [([{"role": "user", "content": "chart"}], 0.0, 512, None)]
