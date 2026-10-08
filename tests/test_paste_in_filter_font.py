# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M17.1 F1-F5: byte-preserving fallback-font transport.

Contract: `.agent/archive/contracts/m17u1.md`.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib
import logging
import sys
import threading
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from filter_checks_support import embed_event, normalized_events
from filter_font_support import FONT_BYTES, PLOTTING, encoded_payloads, run_font_wrapper
from observe_support import stdout_for_verified
from paste_in_support import (
    StoredFile,
    assert_filter_text,
    fake_open_webui,
    filter_body,
    invoke_filter,
    load_filter_module,
    recorded_request,
    valid_png_uri,
)
from verifier.pysrc import DatasetTarget, FormulaTarget, Verified, verify_python_source
from verifier.pysrc.request import formula_target
from webui import model_stub
from webui.paste_in.owui_files import UploadedFile

_CSV = b"region,revenue\nUS,12\nEU,9\n"
_PROGRAM = (
    "import pandas as pd\n"
    f"import {PLOTTING}.pyplot as plt\n"
    'df = pd.read_csv("/mnt/uploads/sales.csv")\n'
    'plt.bar(df["region"], df["revenue"])\n'
    "plt.show()\n"
)
_REQUEST = "y = sin(x), x in [0, 1], n = 3"
_FORMULA = (
    "import numpy as np\n"
    f"import {PLOTTING}.pyplot as plt\n"
    "x = np.linspace(0, 1, num=3)\n"
    "plt.plot(x, np.sin(x))\n"
    "plt.show()\n"
)


def _wrapper(program: str, font: bytes | None = None) -> str:
    return cast(str, load_filter_module().wrapper_code(program, font))


def _verified(program: str = _PROGRAM, content: bytes = _CSV) -> Verified:
    verdict = verify_python_source(
        program, declared_target=DatasetTarget("/mnt/uploads/sales.csv", content)
    )
    assert isinstance(verdict, Verified), verdict
    return verdict


def _formula_verified() -> Verified:
    target = formula_target(_REQUEST)
    assert isinstance(target, FormulaTarget)
    verdict = verify_python_source(_FORMULA, declared_target=target)
    assert isinstance(verdict, Verified), verdict
    return verdict


def _needs(verdict: Verified, upload: UploadedFile | None) -> bool:
    return cast(bool, load_filter_module()._needs_font(verdict, upload))


@pytest.mark.parametrize(
    "program,digest",
    [
        (
            model_stub._captured_program("sentinel-simple"),
            "ce3e46dd84fd1114d8af3f2a0a8469e05aba935546a8a674c108e97080d97490",
        ),
        (
            f"import {PLOTTING}.pyplot as plt\nplt.plot([1, 2], [3, 4])\nplt.show()\n",
            "3a3dc0589c4db94fa0f4a889960b44e3da2c9bb6502a69af200c19a1ce5b592d",
        ),
    ],
    ids=["sentinel-simple", "plotting-name"],
)
def test_f1_no_font_wrapper_is_byte_identical_to_the_pre_unit_wrapper(
    program: str, digest: str
) -> None:
    implicit = cast(str, load_filter_module().wrapper_code(program))
    assert hashlib.sha256(implicit.encode()).hexdigest() == digest
    explicit = _wrapper(program, None)
    assert explicit == implicit


@pytest.mark.parametrize("show", ["plt.show()\nplt.show()\n", ""])
def test_f2_font_prelude_registers_the_fallback_before_the_program_runs(
    show: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2: one fixed path, file-derived family, no loader chatter, one observation then one PNG."""
    program = (
        "import _font_probe\n_font_probe.run()\n" + f"import {PLOTTING}.pyplot as plt\n" + show
    )
    paths: list[str] = []
    for font, family in ((FONT_BYTES, "Fixture JP A"), (b"second font", "Fixture JP B")):
        for suffix in ("", "# different program bytes\n"):
            source = program + suffix
            code = _wrapper(source, font)
            assert PLOTTING not in code
            assert sorted(encoded_payloads(code)) == sorted((font, source.encode()))
            _stdout, _history, written_paths = run_font_wrapper(code, font, family, monkeypatch)
            paths.extend(written_paths)
    assert len(set(paths)) == 1, "font payload must not change the fixed sandbox pathname"


@given(program=st.text(st.characters(codec="utf-8"), max_size=120), font=st.binary(max_size=128))
@settings(max_examples=40)
def test_f2_payloads_preserve_arbitrary_program_text_and_font_bytes(
    program: str, font: bytes
) -> None:
    code = _wrapper(program, font)
    assert PLOTTING not in code
    assert sorted(encoded_payloads(code)) == sorted((font, program.encode("utf-8")))


def test_f2_font_payload_splits_the_plotting_name() -> None:
    font = base64.b64decode(PLOTTING + "AA", validate=True)
    assert PLOTTING in base64.b64encode(font).decode()
    code = _wrapper(_PROGRAM, font)
    assert PLOTTING not in code
    assert sorted(encoded_payloads(code)) == sorted((font, _PROGRAM.encode()))


@pytest.mark.parametrize("arm", ["dataset", "formula"])
@pytest.mark.parametrize("field", ["title", "xlabel", "ylabel", "series"])
@pytest.mark.parametrize(
    "text,expected", [("", False), ("ASCII\x7f", False), ("年", True), ("é", True)]
)
def test_f3_trigger_is_non_ascii_in_labels_or_consumed_csv(
    arm: str, field: str, text: str, *, expected: bool
) -> None:
    verdict = _verified() if arm == "dataset" else _formula_verified()
    labels = replace(
        verdict.spec.labels,
        title=text if field == "title" else None,
        xlabel=text if field == "xlabel" else None,
        ylabel=text if field == "ylabel" else None,
        series=text if field == "series" else None,
    )
    verdict = replace(verdict, spec=replace(verdict.spec, labels=labels))
    upload = UploadedFile("owned", "/mnt/uploads/sales.csv", _CSV) if arm == "dataset" else None
    assert _needs(verdict, upload) is expected


@pytest.mark.parametrize(
    "content,expected",
    [
        (_CSV, False),
        (b"", False),
        ("region,revenue,年月\nUS,12,2026\nEU,9,2027\n".encode(), True),
        ("region,revenue\n日本,12\nEU,9\n".encode(), True),
        ("region,revenue,unused\nUS,12,é\nEU,9,a\n".encode(), True),
        (b"region,revenue,unused\nUS,12,\x80\n", True),
    ],
    ids=["ascii", "empty", "undrawn-ja-header", "ja-tick", "undrawn-latin1-cell", "byte-boundary"],
)
def test_f3_every_consumed_csv_byte_counts(content: bytes, *, expected: bool) -> None:
    assert _needs(_verified(), UploadedFile("owned", "/mnt/uploads/sales.csv", content)) is expected


def test_f3_escaped_label_counts_but_source_comments_and_upload_names_do_not() -> None:
    escaped_label = 'plt.title("' + chr(92) + 'u5e74")\nplt.show()'
    escaped = _PROGRAM.replace("plt.show()", escaped_label)
    assert escaped.isascii()
    verdict = _verified(escaped)
    assert verdict.spec.labels.title == "年"
    assert _needs(verdict, None) is True
    comment = _verified("# 年\n" + _PROGRAM)
    assert _needs(comment, UploadedFile("年", "/mnt/uploads/年.csv", _CSV)) is False


@given(
    labels=st.lists(st.text(st.characters(codec="utf-8"), max_size=24), min_size=4, max_size=4),
    content=st.binary(max_size=48),
    dataset=st.booleans(),
)
@settings(max_examples=60)
def test_f3_trigger_property_is_exact(labels: list[str], content: bytes, *, dataset: bool) -> None:
    verdict = _verified() if dataset else _formula_verified()
    projected = replace(
        verdict.spec.labels, title=labels[0], xlabel=labels[1], ylabel=labels[2], series=labels[3]
    )
    verdict = replace(verdict, spec=replace(verdict.spec, labels=projected))
    upload = UploadedFile("owned", "/mnt/uploads/sales.csv", content) if dataset else None
    expected = any(ord(char) > 127 for text in labels for char in text) or (
        dataset and any(byte > 127 for byte in content)
    )
    assert _needs(verdict, upload) is expected


def _install_env(patch: pytest.MonkeyPatch, directory: object = None) -> ModuleType:
    package = ModuleType("open_webui")
    package.__path__ = []
    env = ModuleType("open_webui.env")
    if directory is not None:
        vars(env)["FONTS_DIR"] = directory
    vars(package)["env"] = env
    patch.setitem(sys.modules, "open_webui", package)
    patch.setitem(sys.modules, "open_webui.env", env)
    return env


def _font() -> bytes | None:
    module = importlib.import_module("webui.paste_in.owui_files")
    function = cast(Callable[[], Awaitable[bytes | None]], module.cjk_font)

    async def invoke() -> bytes | None:
        return await function()

    return asyncio.run(invoke())


@pytest.mark.parametrize("payload", [b"", FONT_BYTES], ids=["empty-file", "opaque-bytes"])
def test_f4_font_source_reads_owui_fonts_dir_off_the_loop_and_never_raises(
    payload: bytes, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = importlib.import_module("webui.paste_in.owui_files")
    assert getattr(module, "CJK_FONT_NAME", None) == "NotoSansJP-Regular.ttf"
    env = _install_env(monkeypatch, tmp_path)
    owner_thread = threading.get_ident()
    seen: list[tuple[Path, int]] = []

    def read_bytes(path: Path) -> bytes:
        seen.append((path, threading.get_ident()))
        return payload

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    assert _font() == payload
    second = tmp_path / "changed-after-import"
    vars(env)["FONTS_DIR"] = str(second)
    assert _font() == payload
    assert [path for path, _thread in seen] == [
        tmp_path / "NotoSansJP-Regular.ttf",
        second / "NotoSansJP-Regular.ttf",
    ]
    assert all(thread != owner_thread for _path, thread in seen), "font read on event-loop thread"


@pytest.mark.parametrize(
    "fault", ["import", "attribute", "file", "permission", "runtime", "value", "dir"]
)
def test_f4_font_source_swallows_each_exception_family(
    fault: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env = _install_env(monkeypatch, tmp_path)
    if fault == "import":
        monkeypatch.setitem(sys.modules, "open_webui.env", None)
    elif fault == "attribute":
        del vars(env)["FONTS_DIR"]
    elif fault == "dir":
        vars(env)["FONTS_DIR"] = object()
    else:
        failures = {
            "file": FileNotFoundError("font absent"),
            "permission": PermissionError("font unreadable"),
            "runtime": RuntimeError("read fault"),
            "value": ValueError("read fault"),
        }

        def read_bytes(_path: Path) -> bytes:
            raise failures[fault]

        monkeypatch.setattr(Path, "read_bytes", read_bytes)
    assert _font() is None


def test_f4_font_source_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_env(monkeypatch, tmp_path)

    def read_bytes(_path: Path) -> bytes:
        raise asyncio.CancelledError

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    with pytest.raises(asyncio.CancelledError):
        _font()


def test_f4_open_webui_import_is_function_local(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = importlib.import_module("webui.paste_in.owui_files")
    with monkeypatch.context() as blocked:
        blocked.setitem(sys.modules, "open_webui", None)
        blocked.setitem(sys.modules, "open_webui.env", None)
        importlib.reload(module)
    (tmp_path / "NotoSansJP-Regular.ttf").write_bytes(FONT_BYTES)
    _install_env(monkeypatch, tmp_path)
    assert _font() == FONT_BYTES


@pytest.mark.parametrize("case", ["ascii", "label", "csv", "unavailable", "formula-label"])
def test_f5_outlet_reads_the_font_only_on_a_verified_non_ascii_figure(
    case: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_filter_module()
    formula = case == "formula-label"
    program = _FORMULA if formula else _PROGRAM
    if case in {"label", "unavailable", "formula-label"}:
        program = program.replace("plt.show()", 'plt.title("年")\nplt.show()')
    content = "region,revenue\n日本,12\nEU,9\n".encode() if case == "csv" else _CSV
    if formula:
        target = formula_target(_REQUEST)
        assert isinstance(target, FormulaTarget)
        verdict = verify_python_source(program, declared_target=target)
        assert isinstance(verdict, Verified)
    else:
        verdict = _verified(program, content)
    font = None if case in {"ascii", "unavailable"} else FONT_BYTES
    calls: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    history: list[str] = []
    original = module.first_verdict

    def select(
        source: str, attachments: object, request: object, anchoring: str, aliases: object
    ) -> object:
        result = original(source, attachments, request, anchoring, aliases)
        history.append("verdict")
        return result

    async def cjk_font() -> bytes | None:
        history.append("font")
        assert history == ["verdict", "font"]
        assert case != "ascii", "ASCII PASS read the font"
        return font

    async def rpc(payload: dict[str, object]) -> object:
        history.append("rpc")
        calls.append(payload)
        return {
            "stdout": stdout_for_verified(verdict, valid_png_uri()),
            "stderr": None,
            "result": None,
        }

    async def emit(event: dict[str, object]) -> None:
        events.append(event)

    monkeypatch.setattr(module, "first_verdict", select)
    monkeypatch.setattr(module, "cjk_font", cjk_font, raising=False)
    files = [] if formula else [StoredFile("owned", "caller", "sales.csv", content)]
    with fake_open_webui(files, tmp_path):
        body = invoke_filter(
            module,
            filter_body("untrusted"),
            request=recorded_request(
                program, () if formula else ("owned",), _REQUEST if formula else None
            ),
            user={"id": "caller"},
            metadata={"session_id": "session"},
            event_call=rpc,
            event_emitter=emit,
        )
    assert history == (["verdict", "rpc"] if case == "ascii" else ["verdict", "font", "rpc"])
    assert len(calls) == 1
    data = cast(dict[str, object], calls[0]["data"])
    expected_code = module.wrapper_code(program) if font is None else _wrapper(program, font)
    assert data["code"] == expected_code
    assert_filter_text(body, "Figure verification passed\n\n" + verdict.certificate.interpretation)
    assert normalized_events(events) == [
        {"type": "files", "data": {"files": [{"type": "image", "url": valid_png_uri()}]}},
        embed_event(None),
    ]


@pytest.mark.parametrize(
    "case",
    [
        "no-tool-call",
        "no-user",
        "no-target",
        "refused",
        "mismatch",
        "no-caller",
        "no-emitter",
        "no-metadata",
        "no-session",
    ],
)
def test_f5_pre_rpc_failures_never_read_a_font(
    case: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_filter_module()
    program = _PROGRAM.replace("plt.show()", 'plt.title("年")\nplt.show()')
    if case == "refused":
        program = "import os\n# 年\n"
    if case == "mismatch":
        program = program.replace("sales.csv", "another.csv")
    calls: list[str] = []

    async def cjk_font() -> bytes:
        calls.append("font")
        pytest.fail("font read before a pre-RPC failure")

    async def rpc(_payload: dict[str, object]) -> object:
        calls.append("rpc")
        pytest.fail("pre-RPC failure invoked the browser")

    async def emit(_event: dict[str, object]) -> None:
        return None

    monkeypatch.setattr(module, "cjk_font", cjk_font, raising=False)
    request = None if case == "no-tool-call" else recorded_request(program, ("owned",))
    files = [] if case == "no-target" else [StoredFile("owned", "caller", "sales.csv", _CSV)]
    metadata: dict[str, object] | None = (
        None if case == "no-metadata" else {} if case == "no-session" else {"session_id": "s"}
    )
    with fake_open_webui(files, tmp_path):
        body = invoke_filter(
            module,
            filter_body("年"),
            request=request,
            user=None if case == "no-user" else {"id": "caller"},
            metadata=metadata,
            event_call=None if case == "no-caller" else rpc,
            event_emitter=None if case == "no-emitter" else emit,
        )
    assert_filter_text(body, "Figure verification failed, no image produced")
    assert calls == []


def test_f3_mathtext_marker_is_outside_the_font_trigger() -> None:
    program = _FORMULA.replace("plt.plot(x, np.sin(x))", 'plt.plot(x, np.sin(x), marker="$年$")')
    target = formula_target(_REQUEST)
    assert isinstance(target, FormulaTarget)
    verdict = verify_python_source(program, declared_target=target)
    assert isinstance(verdict, Verified), verdict
    assert _needs(verdict, None) is False


def test_f4_font_source_survives_a_raising_log_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    """F4 (review R1): a DEBUG logger whose sink raises still leaves an absent font as None."""

    class BrokenSink(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            raise OSError(record.getMessage())

    monkeypatch.setitem(sys.modules, "open_webui.env", None)
    logger = logging.getLogger("webui.paste_in.owui_files")
    monkeypatch.setattr(logger, "level", logging.DEBUG)
    monkeypatch.setattr(logger, "propagate", False)
    monkeypatch.setattr(logger, "handlers", [BrokenSink()])
    module = importlib.import_module("webui.paste_in.owui_files")
    assert asyncio.run(module.cjk_font()) is None
