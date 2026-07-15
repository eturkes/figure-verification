# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Corpus + payload feedback loop for the standalone Open WebUI enforcement filter (M4.4a)."""

import copy
import logging
import types
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from webui import enforcement_filter
from webui.enforcement_filter import (
    BLOCKED_NOTICE,
    FILTER_ID,
    Filter,
    chart_signals,
    function_source,
)


@pytest.mark.parametrize(
    ("text", "signal"),
    [
        (
            "```python\nimport matplotlib.pyplot as plt\nplt.bar(['A'], [3])\n```",
            "matplotlib",
        ),
        ("```python\nimport plotly.express as px\npx.scatter(df, x='a', y='b')\n```", "plotly"),
        ("```python\nimport altair as alt\nalt.Chart(df).mark_line()\n```", "altair"),
        ("```python\nimport seaborn as sns\nsns.histplot(df['amount'])\n```", "seaborn"),
        ("```mermaid\ngraph LR\n  A --> B\n```", "mermaid"),
        ("Here it is:\n<SVG viewBox='0 0 10 10'><path d='M0 0'/></SVG>", "svg"),
        (
            '{"$schema":"https://vega.github.io/schema/vega-lite/v6.json",'
            '"data":{"values":[]},"mark":"bar","encoding":{}}',
            "vega-lite",
        ),
        (
            '```json\n{"data":{"values":[]},"mark":"line","encoding":{}}\n```',
            "vega-lite",
        ),
        ("![chart](data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==)", "data-image"),
    ],
)
def test_each_chart_class_is_detected(text: str, signal: str) -> None:
    assert chart_signals(text) == (signal,)


def test_signals_are_deduplicated_in_canonical_order() -> None:
    text = """data:image/svg+xml;base64,PHN2Zz4=
```python
import plotly.express as px
px.bar(df, x="month", y="amount")
```
<svg></svg>
```plotly
plotly.express.line(df)
```
"""
    assert chart_signals(text) == ("plotly", "svg", "data-image")


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Matplotlib, Plotly, Altair, and Seaborn are plotting libraries.",
        "Use inline `sns.scatterplot` only after verifying the source data.",
        "The literal <svgroup> is not an SVG element.",
        '{"mark":"bar","encoding":{}}',  # no data/composition structure
        '{"$schema":"https://vega.github.io/schema/vega-lite/v6.json",',  # invalid JSON
        "The schema URL is https://vega.github.io/schema/vega-lite/v6.json.",
        "data:text/plain;base64,aGVsbG8=",
        "Verified chart for sales.csv: all 12 checks passed.",
        "Chart ready: http://127.0.0.1:8000/chart/abc123",
    ],
)
def test_prose_and_verified_embed_context_are_not_chart_signals(text: str) -> None:
    assert chart_signals(text) == ()


def test_eof_terminated_code_fence_is_detected() -> None:
    assert chart_signals("```python\nimport matplotlib.pyplot as plt\nplt.plot([1, 2])") == (
        "matplotlib",
    )


def test_outlet_rewrites_only_content_and_logs_metadata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    content = "<svg data-secret='TOP-SECRET'><path/></svg>"
    body: dict[str, object] = {
        "id": "message-1",
        "messages": [
            {"role": "user", "content": "draw it"},
            {
                "id": "assistant-1",
                "role": "assistant",
                "content": content,
                "embeds": [{"type": "iframe", "url": "http://verifier/chart/verified"}],
            },
        ],
        "session_id": "session-1",
    }
    expected = copy.deepcopy(body)
    cast("list[dict[str, object]]", expected["messages"])[-1]["content"] = BLOCKED_NOTICE

    with caplog.at_level(logging.WARNING, logger=FILTER_ID):
        returned = Filter().outlet(body)

    assert returned is body
    assert body == expected
    assert len(caplog.records) == 1
    assert caplog.records[0].getMessage() == (
        f"Blocked unverified chart-like assistant output: signals=svg chars={len(content)}"
    )
    assert "TOP-SECRET" not in caplog.text


def test_outlet_passes_verified_embed_message_byte_for_byte(
    caplog: pytest.LogCaptureFixture,
) -> None:
    body: dict[str, object] = {
        "messages": [
            {
                "role": "assistant",
                "content": "Verified chart for sales.csv: all 12 checks passed.",
                "embeds": [{"url": "http://127.0.0.1:8000/chart/abc123"}],
            }
        ]
    }
    before = copy.deepcopy(body)

    with caplog.at_level(logging.WARNING, logger=FILTER_ID):
        assert Filter().outlet(body) is body

    assert body == before
    assert not caplog.records


def test_outlet_inspects_only_the_final_assistant_message() -> None:
    body: dict[str, object] = {
        "messages": [
            {"role": "assistant", "content": "<svg><path/></svg>"},
            {"role": "assistant", "content": "I will use Figure Verifier."},
        ]
    }
    before = copy.deepcopy(body)
    assert Filter().outlet(body) == before


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"messages": []},
        {"messages": "not-a-list"},
        {"messages": ["not-a-message"]},
        {"messages": [{"role": "user", "content": "<svg></svg>"}]},
        {"messages": [{"role": "assistant", "content": None}]},
    ],
)
def test_outlet_malformed_or_ineligible_bodies_are_noops(body: dict[str, object]) -> None:
    before = copy.deepcopy(body)
    assert Filter().outlet(body) is body
    assert body == before


def test_function_source_is_exact_and_import_executes_standalone() -> None:
    source = function_source()
    assert source == Path(enforcement_filter.__file__).read_text(encoding="utf-8")
    assert "from webui" not in source
    assert "pydantic" not in source.casefold()

    module = types.ModuleType("function_verified_plot_guard")
    exec(compile(source, "function_verified_plot_guard.py", "exec"), module.__dict__)  # noqa: S102
    posted_filter = cast("Callable[[], Filter]", module.__dict__["Filter"])()
    assert not hasattr(posted_filter, "toggle")  # global+active applies without per-chat opt-in
    body: dict[str, object] = {
        "messages": [{"role": "assistant", "content": "```mermaid\ngraph LR\nA-->B\n```"}]
    }
    assert posted_filter.outlet(body) is body
    assert cast("list[dict[str, object]]", body["messages"])[0]["content"] == BLOCKED_NOTICE
