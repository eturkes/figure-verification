# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Backend-state, embedded-class and sandbox-source witnesses for M10.1."""

import ast
import asyncio
import base64
import contextlib
import io
import sys
import types
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from filter_checks_support import embed_event, normalized_events
from observe_support import stdout_for, stdout_for_verified
from paste_in_support import REPO_ROOT, StoredFile, execute_artifact, fake_open_webui
from verifier.pysrc import DatasetTarget, Verified, verify_python_source
from webui.paste_in import filter as outlet
from webui.paste_in import selection, tool
from webui.paste_in.receipt import RECEIPT_ATTR, RECEIPT_TAG, Receipt, read_receipt

_PROGRAM = (
    "import pandas as pd\n"
    "import matplotlib.pyplot as plt\n"
    'df = pd.read_csv("/mnt/uploads/sales.csv")\n'
    'plt.bar(df["region"], df["revenue"])\n'
    "plt.show()\n"
)
_CSV = b"region,revenue\nUS,12\nEU,9\n"
_PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nbytes").decode()


def _request() -> types.SimpleNamespace:
    return types.SimpleNamespace(state=types.SimpleNamespace())


def _body() -> dict[str, object]:
    return {
        "messages": [
            {"role": "user", "content": "user text"},
            {"role": "assistant", "content": "model text", "output": [{"old": "model"}]},
        ]
    }


def _text(body: dict[str, object]) -> str:
    messages = cast(list[dict[str, object]], body["messages"])
    return cast(str, messages[-1]["content"])


def test_state_carrier_is_builtin_and_replaces_prior_call(tmp_path: Path) -> None:
    """F1/A3: only typed tagged data crosses independently embedded paste-in classes."""
    assert vars(tool)["first_verdict"] is selection.first_verdict
    assert vars(outlet)["first_verdict"] is selection.first_verdict
    request = _request()
    stored = [StoredFile("owned", "caller", "sales.csv", _CSV)]
    metadata: dict[str, object] = {
        "files": [{"id": "foreign"}, {"id": "owned"}],
        "user_message": {"content": "chart revenue by region"},
    }
    with fake_open_webui(stored, tmp_path) as lookups:
        first = asyncio.run(
            tool.Tools().draw_figure(
                _PROGRAM,
                __metadata__=metadata,
                __user__={"id": "caller"},
                __request__=request,
            )
        )
        second = asyncio.run(
            tool.Tools().draw_figure(
                "import os\n",
                __metadata__=metadata,
                __user__={"id": "caller"},
                __request__=request,
            )
        )
    assert (first, second) == ("The chart is ready.", "No chart was produced.")
    assert lookups == [("foreign", "caller"), ("owned", "caller")] * 2
    assert getattr(request.state, RECEIPT_ATTR) == (
        RECEIPT_TAG,
        "import os\n",
        ("owned",),
        "chart revenue by region",
        (),
    )
    assert read_receipt(request) == Receipt(
        "import os\n", ("owned",), "chart revenue by region", ()
    )


@pytest.mark.parametrize(
    "carrier",
    [None, "The chart is ready.", ("wrong-tag", "x", (), None, ()), (RECEIPT_TAG, 9, (), None, ())],
)
def test_receipt_reader_refuses_non_carrier(carrier: object) -> None:
    request = _request()
    setattr(request.state, RECEIPT_ATTR, carrier)
    assert read_receipt(request) is None


def test_png_uri_rejects_a_second_uri_embedded_in_prose() -> None:
    """F4: another PNG anywhere in stdout must withhold, not publish the first line."""
    assert outlet._png_uri(_PNG + "\nother output " + _PNG) is None


def test_png_uri_ignores_data_suffix_inside_unrelated_prose() -> None:
    """F5: unrelated stdout text must not make one valid PNG look like two URI tokens."""
    assert outlet._png_uri("患者data: rendering started\n" + _PNG) == _PNG
    assert outlet._png_uri("metadata: rendering started\n" + _PNG) == _PNG


def test_no_state_receipt_rewrites_prose_with_no_rpc() -> None:
    """F2/F4: user text, citations and a serialized tool result cannot authorize a figure."""
    body = _body()
    body["receipt"] = (RECEIPT_TAG, _PROGRAM, (), None, ())
    messages = cast(list[dict[str, object]], body["messages"])
    messages[-1]["content"] = "The chart is ready. " + _PNG
    messages[-1]["sources"] = [{"document": ["The chart is ready."]}]
    earlier = messages[0].copy()

    async def bomb(_payload: dict[str, object]) -> object:
        pytest.fail("no state receipt must not invoke the browser")

    result = asyncio.run(
        outlet.Filter().outlet(body, __event_call__=bomb, __user__={"id": "caller"})
    )
    assert result is body
    assert messages[0] == earlier
    assert _text(body) == outlet.FAIL_TEXT
    assert messages[-1]["output"] == [
        {
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": outlet.FAIL_TEXT}],
        }
    ]


def test_cross_artifact_receipt_renders_one_consumed_attachment(tmp_path: Path) -> None:
    """F3/F5/F6: the tool and filter work despite separate embedded Receipt class identities."""
    modules = {}
    for name in ("tool", "filter"):
        artifact = REPO_ROOT / "paste-in" / f"figure_verification_{name}.py"
        modules[name] = execute_artifact(artifact.read_text(), artifact, f"_test_{name}")
    request = _request()
    files = [
        StoredFile("wrong", "caller", "wrong.csv", _CSV),
        StoredFile("matching", "caller", "sales.csv", _CSV),
    ]
    metadata = {"files": [{"id": "wrong"}, {"id": "matching"}]}
    verdict = verify_python_source(
        _PROGRAM, declared_target=DatasetTarget("/mnt/uploads/sales.csv", _CSV)
    )
    assert isinstance(verdict, Verified)
    rpc: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    async def event_call(payload: dict[str, object]) -> object:
        rpc.append(payload)
        return {"stdout": stdout_for_verified(verdict, _PNG) + "\n", "stderr": "", "result": None}

    async def emit(event: dict[str, object]) -> None:
        events.append(event)

    with fake_open_webui(files, tmp_path) as lookups:
        reply = asyncio.run(
            modules["tool"]
            .Tools()
            .draw_figure(
                _PROGRAM,
                __request__=request,
                __metadata__=metadata,
                __user__={"id": "caller"},
            )
        )
        body = asyncio.run(
            modules["filter"]
            .Filter()
            .outlet(
                _body(),
                __user__={"id": "caller"},
                __request__=request,
                __metadata__={"session_id": "session-1"},
                __event_call__=event_call,
                __event_emitter__=emit,
            )
        )
    assert reply == "The chart is ready."
    assert lookups == [("wrong", "caller"), ("matching", "caller")] * 2
    assert len(rpc) == 1
    assert rpc[0]["type"] == "execute:python"
    data = cast(dict[str, object], rpc[0]["data"])
    assert uuid.UUID(cast(str, data["id"])).version == 4
    assert data["session_id"] == "session-1"
    assert data["files"] == [{"id": "matching", "filename": "sales.csv"}]
    code = cast(str, data["code"])
    assert "matplotlib" not in code
    assert base64.b64encode(_PROGRAM.encode()).decode() in code
    assert normalized_events(events) == [
        {"type": "files", "data": {"files": [{"type": "image", "url": _PNG}]}},
        embed_event(None),
    ]
    assert _text(body).startswith(outlet.PASS_TEXT + "\n\n")
    message = cast(list[dict[str, object]], body["messages"])[-1]
    output = cast(list[dict[str, object]], message["output"])
    content = cast(list[dict[str, object]], output[0]["content"])
    assert _text(body) == content[0]["text"]


def test_wrapper_loads_plotting_stack_before_import() -> None:
    """F7/A5: the browser detector sees no hidden imports; the wrapper loads its own stack."""
    code = outlet.wrapper_code(_PROGRAM)
    assert "matplotlib" not in code
    statements = ast.parse(code).body
    assert isinstance(statements[0], ast.Import)
    assert [(item.name, item.asname) for item in statements[0].names] == [
        ("pyodide_js", "_pyodide")
    ]
    loader = statements[1]
    assert isinstance(loader, ast.Expr) and isinstance(loader.value, ast.Await)
    call = loader.value.value
    assert isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
    assert isinstance(call.func.value, ast.Name) and call.func.value.id == "_pyodide"
    assert call.func.attr == "loadPackage" and len(call.args) == 1
    assert len(call.keywords) == 1 and call.keywords[0].arg == "messageCallback"
    callback = call.keywords[0].value
    assert isinstance(callback, ast.Lambda) and len(callback.args.args) == 1
    assert isinstance(callback.body, ast.Constant) and callback.body.value is None
    packages = call.args[0]
    assert isinstance(packages, ast.List) and len(packages.elts) == 3
    numpy, pandas, plotting = packages.elts
    assert isinstance(numpy, ast.Constant) and numpy.value == "numpy"
    assert isinstance(pandas, ast.Constant) and pandas.value == "pandas"
    assert isinstance(plotting, ast.BinOp) and isinstance(plotting.op, ast.Add)
    assert isinstance(plotting.left, ast.Constant) and isinstance(plotting.right, ast.Constant)
    assert isinstance(plotting.left.value, str) and isinstance(plotting.right.value, str)
    assert plotting.left.value + plotting.right.value == "matplotlib"
    assert isinstance(statements[2], ast.Import)


def test_wrapper_runs_exact_program_and_prints_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """F7/O1: show draws one axes inventory before saving, once even after two show calls."""
    package = types.ModuleType("matplotlib")
    package.__path__ = []
    pyplot = types.ModuleType("matplotlib.pyplot")
    vars(package)["pyplot"] = pyplot
    history: list[str] = []

    def draw() -> None:
        history.append("draw")

    def savefig(output: io.BytesIO, **kwargs: str) -> None:
        assert kwargs == {"format": "png"}
        history.append("save")
        output.write(b"\x89PNG\r\n\x1a\nbytes")

    def axis() -> types.SimpleNamespace:
        return types.SimpleNamespace(units=None, get_ticklocs=lambda: (), get_ticklabels=lambda: ())

    axes = [
        types.SimpleNamespace(
            lines=[],
            collections=[],
            containers=[],
            patches=[],
            images=[],
            texts=[],
            xaxis=axis(),
            yaxis=axis(),
        )
    ]
    figure = types.SimpleNamespace(
        canvas=types.SimpleNamespace(draw=draw), axes=axes, savefig=savefig
    )
    vars(pyplot)["gcf"] = lambda: figure
    vars(pyplot)["close"] = lambda _scope: None
    monkeypatch.setitem(sys.modules, "matplotlib", package)
    monkeypatch.setitem(sys.modules, "matplotlib.pyplot", pyplot)
    observation: dict[str, object] = {
        "axes": 1,
        "lines": [],
        "collections": [],
        "containers": [],
        "patches": 0,
        "images": 0,
        "texts": 0,
        "xaxis": {"units": None, "ticks": []},
        "yaxis": {"units": None, "ticks": []},
    }
    pyodide_js = types.ModuleType("pyodide_js")

    async def load_package(
        packages: list[str],
        *,
        messageCallback: Callable[[str], None],  # noqa: N803 - JS keyword
    ) -> None:
        assert packages == ["numpy", "pandas", "matplotlib"]
        history.append("load")
        messageCallback("loaded")

    vars(pyodide_js)["loadPackage"] = load_package
    monkeypatch.setitem(sys.modules, "pyodide_js", pyodide_js)
    for program in (
        "import matplotlib.pyplot as plt\nplt.show()\nplt.show()\n",
        "import matplotlib.pyplot as plt\nx = 1\n",
    ):
        output = io.StringIO()
        code = outlet.wrapper_code(program)
        assert "matplotlib" not in code
        with contextlib.redirect_stdout(output):
            coroutine = eval(  # noqa: S307 - the generated sandbox source is the test subject
                compile(code, "<wrapper>", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT), {}
            )
            asyncio.run(coroutine)
        assert output.getvalue().splitlines() == [stdout_for(observation).rstrip("\n"), _PNG]
    assert history == ["load", "draw", "save", "load", "draw", "save"]
