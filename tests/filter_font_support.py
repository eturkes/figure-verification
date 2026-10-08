# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M17.1: independent payload decoding + strict sandbox fakes, without a plotting dependency."""

from __future__ import annotations

import ast
import asyncio
import base64
import builtins
import contextlib
import importlib
import io
import os
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from observe_support import stdout_for

PLOTTING = "mat" + "plotlib"
FONT_BYTES = b"\x00\x01\x00\x00independent fake font\xff"


def encoded_payloads(code: str) -> tuple[bytes, ...]:
    """Resolve literal concatenations/names only; reject executable base64 source expressions."""
    tree = ast.parse(code)
    assignments = {
        target.id: node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    def literal(node: ast.expr, seen: frozenset[str] = frozenset()) -> str | bytes:
        if isinstance(node, ast.Constant) and isinstance(node.value, str | bytes):
            return node.value
        if isinstance(node, ast.Name) and node.id in assignments and node.id not in seen:
            return literal(assignments[node.id], seen | {node.id})
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = literal(node.left, seen), literal(node.right, seen)
            if isinstance(left, str) and isinstance(right, str):
                return left + right
            if isinstance(left, bytes) and isinstance(right, bytes):
                return left + right
        failure = "unmapped base64 source shape"
        raise AssertionError(failure)

    sources = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if (isinstance(function, ast.Name) and function.id == "b64decode") or (
            isinstance(function, ast.Attribute) and function.attr == "b64decode"
        ):
            assert node.args, "b64decode call has no source argument"
            sources.append(base64.b64decode(literal(node.args[0]), validate=True))
    return tuple(sources)


def run_font_wrapper(  # noqa: PLR0915 - one strict fake per sandbox-side effect
    code: str, font: bytes, family: str, patch: pytest.MonkeyPatch
) -> tuple[str, list[str], tuple[str, ...]]:
    """Execute the generated wrapper; all I/O stays in memory and every font call is counted."""
    history: list[str] = []
    paths: list[str] = []
    written: dict[str, bytes] = {}
    real_import_module = importlib.import_module
    real_import = builtins.__import__

    class Environment(dict[str, str]):
        def __setitem__(self, key: str, value: str) -> None:
            assert key == "MPLBACKEND" and value == "AGG"
            history.append("backend")
            super().__setitem__(key, value)

    class Parameters(dict[str, object]):
        def __setitem__(self, key: str, value: object) -> None:
            assert key == "font.family"
            assert value == ["DejaVu Sans", family]
            history.append("family")
            super().__setitem__(key, value)

    def write(path: str | Path, data: bytes) -> int:
        assert data == font
        name = os.fspath(path)
        assert Path(name).is_absolute(), "font path must be a fixed sandbox absolute path"
        paths.append(name)
        written[name] = data
        history.append("write")
        return len(data)

    class BinaryFile(io.BytesIO):
        def __init__(self, path: str | Path) -> None:
            super().__init__()
            self.path = path

        def write(self, data: object) -> int:
            assert isinstance(data, bytes)
            write(self.path, data)
            return super().write(data)

    def open_binary(path: str | Path, mode: str = "r") -> BinaryFile:
        assert mode == "wb"
        return BinaryFile(path)

    def write_bytes(path: Path, data: bytes) -> int:
        return write(path, data)

    def addfont(path: str | Path) -> None:
        assert written[os.fspath(path)] == font
        assert paths == [os.fspath(path)]
        history.append("addfont")

    class FontProperties:
        def __init__(self, *, fname: str | Path) -> None:
            assert written[os.fspath(fname)] == font
            assert paths == [os.fspath(fname)]

        def get_name(self) -> str:
            history.append("name")
            return family

    def draw() -> None:
        history.append("draw")

    def savefig(output: io.BytesIO, *, format: str) -> None:  # noqa: A002 - real API keyword
        assert format == "png"
        history.append("save")
        output.write(b"\x89PNG\r\n\x1a\nbytes")

    def close(scope: object) -> None:
        assert scope == "all" or scope is figure
        history.append("close")

    def run() -> None:
        assert history[-1] == "family"
        history.append("program")

    axis = SimpleNamespace(units=None, get_ticklocs=lambda: (), get_ticklabels=lambda: ())
    axes = SimpleNamespace(
        lines=[],
        collections=[],
        containers=[],
        patches=[],
        images=[],
        texts=[],
        xaxis=axis,
        yaxis=axis,
    )
    figure = SimpleNamespace(canvas=SimpleNamespace(draw=draw), axes=[axes], savefig=savefig)
    package = ModuleType(PLOTTING)
    package.__path__ = []
    pyplot = ModuleType(PLOTTING + ".pyplot")
    manager = ModuleType(PLOTTING + ".font_manager")
    parameters = Parameters()
    vars(package).update(pyplot=pyplot, font_manager=manager, rcParams=parameters)
    vars(pyplot).update(gcf=lambda: figure, close=close, rcParams=parameters)
    vars(manager).update(
        fontManager=SimpleNamespace(addfont=addfont), FontProperties=FontProperties
    )
    probe = ModuleType("_font_probe")
    vars(probe)["run"] = run
    pyodide = ModuleType("pyodide_js")

    async def load_package(
        packages: list[str],
        *,
        messageCallback: Callable[[str], None],  # noqa: N803 - JS API
    ) -> None:
        assert packages == ["numpy", "pandas", PLOTTING]
        history.append("load")
        messageCallback("loader output must stay silent")

    vars(pyodide)["loadPackage"] = load_package

    def imported(name: str) -> None:
        if name == PLOTTING + ".pyplot" and "pyplot" not in history:
            assert os.environ["MPLBACKEND"] == "AGG"
            history.append("pyplot")

    def import_module(name: str, package: str | None = None) -> ModuleType:
        imported(name)
        return real_import_module(name, package)

    def import_builtin(
        name: str,
        globals: dict[str, object] | None = None,  # noqa: A002 - real import signature
        locals: dict[str, object] | None = None,  # noqa: A002 - real import signature
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> ModuleType:
        imported(name)
        return real_import(name, globals, locals, fromlist, level)

    output = io.StringIO()
    with patch.context() as scoped:
        for module in (package, pyplot, manager, probe, pyodide):
            scoped.setitem(sys.modules, module.__name__, module)
        scoped.setattr(os, "environ", Environment(os.environ))
        scoped.setattr(builtins, "open", open_binary)
        scoped.setattr(Path, "write_bytes", write_bytes)
        scoped.setattr(importlib, "import_module", import_module)
        scoped.setattr(builtins, "__import__", import_builtin)
        with contextlib.redirect_stdout(output):
            coroutine = eval(  # noqa: S307 - generated sandbox source is the test subject
                compile(code, "<font-wrapper>", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT), {}
            )
            asyncio.run(coroutine)
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
    png = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\nbytes").decode()
    assert output.getvalue().splitlines() == [stdout_for(observation).rstrip("\n"), png]
    assert [event for event in history if event != "name"] == [
        "load",
        "backend",
        "pyplot",
        "write",
        "addfont",
        "family",
        "program",
        "draw",
        "save",
        "close",
    ]
    assert history.count("name") == 1
    assert history.index("write") < history.index("name") < history.index("family")
    assert len(paths) == 1
    return output.getvalue(), history, tuple(paths)
