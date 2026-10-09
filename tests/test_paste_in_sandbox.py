# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M19.2 wrapper: the RPC code runs the reader over the exact program bytes (`m19u2.md` U3).

The wrapper runs here as Pyodide runs it: compiled with top-level `await` beside a stand-in
`pyodide_js` whose `loadPackage` the host already satisfies.
"""

import ast
import asyncio
import base64
import contextlib
import io
import re
import sys
import types
from pathlib import Path

import pytest

from verifier.figure import reader
from verifier.figure.description import Text, parse_description
from webui.paste_in import sandbox

_PLT = "import matplotlib.pyplot as plt\n"
# OWUI 0.10.2's package detector, one entry per bundled module it routes (`.claude/rules/owui.md`).
_DETECTOR = re.compile(r"\bimport\s+matplotlib\b|\bfrom\s+matplotlib\b")


def _execute(code: str) -> str:
    loads: list[list[str]] = []

    async def load_package(packages: list[str], **_kwargs: object) -> None:
        loads.append(packages)

    fake = types.ModuleType("pyodide_js")
    fake.loadPackage = load_package  # type: ignore[attr-defined]
    compiled = compile(code, "<rpc>", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
    out = io.StringIO()
    with pytest.MonkeyPatch.context() as patch, contextlib.redirect_stdout(out):
        patch.setitem(sys.modules, "pyodide_js", fake)
        result = eval(compiled, {"__name__": "__main__"})  # noqa: S307 - the RPC code under test
        if asyncio.iscoroutine(result):
            asyncio.run(result)
    assert loads == [["numpy", "pandas", "matplotlib"]]
    return out.getvalue()


def test_u3_the_rpc_never_spells_the_plotting_name() -> None:
    code = sandbox.wrapper_code(_PLT + "import matplotlib\nplt.plot([1])\n", b"font matplotlib")
    assert "matplotlib" not in code
    assert _DETECTOR.search(code) is None


def test_u3_the_wrapper_prints_what_the_reader_returns() -> None:
    program = _PLT + "print('noise')\nplt.bar(['a', 'b'], [1, 2])\n"
    assert _execute(sandbox.wrapper_code(program)) == reader.run(program)


def test_u3_program_bytes_survive_exactly() -> None:
    """Non-ASCII text and a lone surrogate reach the reader unchanged (a surrogate: syntax)."""
    title = _PLT + "plt.plot([1])\nplt.title('売上 ✓')\n"
    described = parse_description(_execute(sandbox.wrapper_code(title)))
    assert described is not None
    assert described.figures[0].axes[0].titles[1] == Text("売上 ✓", 3)
    surrogate = _execute(sandbox.wrapper_code("x = '\ud800'\n"))
    assert '"kind":"syntax"' in surrogate


def test_u3_the_font_is_written_then_registered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import matplotlib as mpl  # noqa: PLC0415 - the reader imports it lazily too

    target = tmp_path / "font.ttf"
    monkeypatch.setattr(sandbox, "FONT_PATH", str(target))
    font = (Path(mpl.get_data_path()) / "fonts" / "ttf" / "DejaVuSerif.ttf").read_bytes()
    _execute(sandbox.wrapper_code(_PLT + "plt.plot([1])\n", font))
    assert target.read_bytes() == font
    assert mpl.rcParams["font.family"] == ["DejaVu Sans", "DejaVu Serif"]


def test_u3_the_shipped_reader_is_the_tracked_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    """A checkout ships the tracked file; a paste-in ships the text its loader kept."""
    tracked = Path(reader.__file__).read_text(encoding="utf-8")
    assert sandbox.reader_source() == tracked
    monkeypatch.setattr(reader, "__paste_in_source__", "embedded text", raising=False)
    assert sandbox.reader_source() == "embedded text"
    code = sandbox.wrapper_code("x = 1\n")
    encoded = base64.b64encode(b"embedded text").decode("ascii")
    assert repr(encoded) in code
