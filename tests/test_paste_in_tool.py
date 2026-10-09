# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M19.5 O6: the tool records a program; only the later outlet decides publication."""

from __future__ import annotations

import asyncio
import inspect
import subprocess
import sys
from collections.abc import Coroutine, Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from outlet_support import Bomb, load
from paste_in_support import REPO_ROOT, fake_open_webui, filter_request, public_tool_operation


@pytest.fixture(autouse=True)
def _empty_store(tmp_path: Path) -> Iterator[None]:
    with fake_open_webui((), tmp_path):
        yield


def test_o6_one_model_operation_has_only_the_program_parameter() -> None:
    for module in (load("tool"), load("demo_tool")):
        name, operation = public_tool_operation(module)
        assert name == "draw_figure"
        assert [
            name for name in inspect.signature(operation).parameters if not name.startswith("__")
        ] == ["program"]
        assert inspect.iscoroutinefunction(operation)
        assert getattr(load("verdicts"), "CHART_SENT", None) is not None


@example(program="")
@example(program="not valid Python :\n\x00\r\n# model bytes")
@example(program="import matplotlib.pyplot as plt\nplt.bar([0], [1])\n")
@given(program=st.text(alphabet=st.characters(codec="utf-8"), max_size=500))
@settings(max_examples=50, deadline=None)
def test_o6_arbitrary_program_bytes_are_receipted_without_a_verdict(program: str) -> None:
    module = load("tool")
    tools = module.Tools()
    request = filter_request()
    result = asyncio.run(
        cast(
            Coroutine[Any, Any, object],
            tools.draw_figure(
                program,
                __metadata__={"user_message": {"content": "original request"}},
                __request__=request,
            ),
        )
    )
    receipt = load("receipt").read_receipt(request)
    assert receipt == load("receipt").Receipt(program, (), "original request", ())
    assert isinstance(result, str) and result == load("verdicts").CHART_SENT


@pytest.mark.parametrize("demo", [False, True], ids=["production", "demo"])
def test_o6_last_call_wins_with_all_ids_request_and_parsed_aliases(*, demo: bool) -> None:
    module = load("demo_tool" if demo else "tool")
    tool = module.Tools()
    tool.valves = module.Tools.Valves(column_aliases="revenue = sales, income\nregion = area")
    request = filter_request()
    metadata: dict[str, object] = {
        "files": [{"id": "older"}, {"id": "foreign"}, {"id": "newer"}],
        "user_message": {"content": "sales by area"},
    }
    results = [
        asyncio.run(
            cast(
                Coroutine[Any, Any, object],
                tool.draw_figure(
                    program,
                    __metadata__=metadata,
                    __request__=request,
                ),
            )
        )
        for program in ("previous bytes", "latest\x00bytes\r\n")
    ]
    assert load("receipt").read_receipt(request) == load("receipt").Receipt(
        "latest\x00bytes\r\n",
        ("older", "foreign", "newer"),
        "sales by area",
        (("revenue", "sales"), ("revenue", "income"), ("region", "area")),
    )
    assert results == [load("verdicts").CHART_SENT] * 2


def test_o6_tool_neither_imports_nor_calls_judge_or_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    script = (
        "import importlib, sys\n"
        "importlib.import_module('webui.paste_in.tool')\n"
        "assert 'verifier.figure.judge' not in sys.modules\n"
        "assert 'verifier.figure.reader' not in sys.modules\n"
        "assert 'verifier.pysrc.verify' not in sys.modules\n"
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter and hand-authored import probe
        [sys.executable, "-c", script], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    bomb = Bomb()
    monkeypatch.setattr("verifier.figure.judge.judge", bomb)
    monkeypatch.setattr("verifier.figure.reader.run", bomb)
    request = filter_request()
    reply = asyncio.run(
        cast(
            Coroutine[Any, Any, object],
            load("tool").Tools().draw_figure("plt.invalid(", __request__=request),
        )
    )
    assert reply == load("verdicts").CHART_SENT
    assert load("receipt").read_receipt(request).program == "plt.invalid("
    assert bomb.calls == 0
