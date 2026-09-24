# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.1 F4-F7: total outlet decision, exact publication and bounded sandbox transport.

Contract: `.agent/archive/contracts/m10u1.md`. The rendering callback is faked, not a second
verdict; Pyodide behavior is measured outside the gate over the installed bundle.
"""

import ast
import asyncio
import base64
import copy
import uuid
from pathlib import Path
from typing import cast

import pytest

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

_FAIL = "Figure verification failed, no image produced"
_PASS = "Figure verification passed"  # noqa: S105 - verdict text, not a password
_USER = "owner-1"
_REQUEST = "y = sin(x), x in [0, 1], n = 3"
_FORMULA = (
    "import numpy as np\n"
    "import matplotlib.pyplot as plt\n"
    "x = np.linspace(0, 1, num=3)\n"
    "y = np.sin(x)\n"
    "plt.plot(x, y)\n"
    "plt.show()\n"
)


def _sales_program() -> str:
    return (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        'df = pd.read_csv("/mnt/uploads/sales.csv")\n'
        'grouped = df.groupby("region")["revenue"].sum()\n'
        "plt.bar(grouped.index, grouped.values)\n"
        "plt.show()\n"
    )


def _sales_bytes() -> bytes:
    return (Path(__file__).resolve().parent.parent / "data" / "sales.csv").read_bytes()


def _expected_formula_pass() -> str:
    target = formula_target(_REQUEST)
    assert isinstance(target, FormulaTarget)
    verdict = verify_python_source(_FORMULA, declared_target=target)
    assert isinstance(verdict, Verified)
    return _PASS + "\n\n" + verdict.certificate.interpretation


def _png_response(uri: str | None = None) -> dict[str, object]:
    return {"stdout": valid_png_uri() if uri is None else uri, "stderr": "", "result": None}


def _files_events(events: list[dict[str, object]]) -> list[dict[str, object]]:
    return [event for event in events if event.get("type") == "files"]


async def _record_event(event: dict[str, object]) -> None:
    assert event["type"] == "files"


def _assert_encoded_program(code: str, program: str) -> None:
    """F6's exact model bytes must travel as a base64 literal, never a source rewrite."""
    assert "matplotlib" not in code
    encoded = base64.b64encode(program.encode("utf-8")).decode("ascii")
    assert encoded in code
    assert base64.b64decode(encoded, validate=True).decode("utf-8") == program
    compile(code, "<sandbox-wrapper>", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
    tree = ast.parse(code)
    assert any(
        isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "exec")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "exec")
        )
        for node in ast.walk(tree)
    )


@pytest.mark.parametrize("case", ["prose-only", "refused", "no-candidate"])
def test_f4_absent_refused_or_unbound_receipt_blocks_every_reply(case: str, tmp_path: Path) -> None:
    """F4: prose without a call, a verifier refusal, and no target all rewrite both surfaces."""
    request: object | None = None
    if case == "refused":
        request = recorded_request("import os\n", request_text=_REQUEST)
    elif case == "no-candidate":
        request = recorded_request(_FORMULA)
    calls: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    async def rpc(payload: dict[str, object]) -> object:
        calls.append(payload)
        return _png_response()

    async def emit(event: dict[str, object]) -> None:
        events.append(event)

    with fake_open_webui([], tmp_path):
        result = invoke_filter(
            load_filter_module(),
            filter_body("The model says the chart is ready."),
            request=request,
            user={"id": _USER},
            metadata={"session_id": "browser-session"},
            event_call=rpc,
            event_emitter=emit,
        )
    assert_filter_text(result, _FAIL)
    assert calls == []
    assert _files_events(events) == []


@pytest.mark.parametrize("path", ["fail", "pass"])
def test_f4_multiturn_rewrites_only_last_assistant_on_fail_and_pass(
    path: str, tmp_path: Path
) -> None:
    """F4: an earlier assistant turn survives intact while only the current turn gets a verdict."""
    body = filter_body("current model narration")
    messages = cast(list[dict[str, object]], body["messages"])
    earlier: dict[str, object] = {
        "id": "earlier-assistant",
        "role": "assistant",
        "content": "prior model answer",
        "output": [
            {
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "prior output text"}],
            }
        ],
    }
    messages[1:1] = [earlier, {"id": "followup", "role": "user", "content": "next request"}]
    original_earlier = copy.deepcopy(earlier)
    calls: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    uri = valid_png_uri()

    async def rpc(payload: dict[str, object]) -> object:
        calls.append(payload)
        return _png_response(uri)

    async def emit(event: dict[str, object]) -> None:
        events.append(event)

    with fake_open_webui([], tmp_path):
        result = invoke_filter(
            load_filter_module(),
            body,
            request=recorded_request(_FORMULA, request_text=_REQUEST) if path == "pass" else None,
            user={"id": _USER},
            metadata={"session_id": "browser-session"},
            event_call=rpc,
            event_emitter=emit,
        )
    assert len(cast(list[dict[str, object]], result["messages"])) == 4
    assert cast(list[dict[str, object]], result["messages"])[1] == original_earlier
    assert_filter_text(result, _expected_formula_pass() if path == "pass" else _FAIL)
    assert len(calls) == (1 if path == "pass" else 0)
    assert _files_events(events) == (
        [{"type": "files", "data": {"files": [{"type": "image", "url": uri}]}}]
        if path == "pass"
        else []
    )


@pytest.mark.parametrize(
    "case",
    [
        "rpc-absent",
        "rpc-raises",
        "rpc-timeout",
        "rpc-not-dict",
        "stderr",
        "zero-png",
        "two-png",
        "not-base64",
        "not-png",
    ],
)
def test_f4_render_failures_withhold_image_and_model_prose(
    case: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """F4: every non-F5 RPC result produces exact FAIL, no image, no surviving model prose."""
    module = load_filter_module()
    if case == "rpc-timeout":
        monkeypatch.setattr(module, "RPC_TIMEOUT_SECONDS", 0.001)
    request = recorded_request(_FORMULA, request_text=_REQUEST)
    uri = valid_png_uri()
    cases: dict[str, object] = {
        "rpc-not-dict": [uri],
        "stderr": {"stdout": uri, "stderr": "render failed", "result": None},
        "zero-png": {"stdout": "nothing printed", "stderr": "", "result": None},
        "two-png": {"stdout": f"{uri}\n{uri}\n", "stderr": "", "result": None},
        "not-base64": {"stdout": "data:image/png;base64,%%%", "stderr": "", "result": None},
        "not-png": {
            "stdout": "data:image/png;base64," + base64.b64encode(b"not PNG").decode(),
            "stderr": "",
            "result": None,
        },
    }
    calls: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    async def rpc(payload: dict[str, object]) -> object:
        calls.append(payload)
        if case == "rpc-raises":
            error = "sandbox disconnected"
            raise RuntimeError(error)
        if case == "rpc-timeout":
            await asyncio.sleep(0.05)
            return _png_response()
        return cases[case]

    async def emit(event: dict[str, object]) -> None:
        events.append(event)

    with fake_open_webui([], tmp_path):
        result = invoke_filter(
            module,
            filter_body("model-supplied answer that must disappear"),
            request=request,
            user={"id": _USER},
            metadata={"session_id": "browser-session"},
            event_call=None if case == "rpc-absent" else rpc,
            event_emitter=emit,
        )
    assert_filter_text(result, _FAIL)
    assert len(calls) == (0 if case == "rpc-absent" else 1)
    assert _files_events(events) == []


def test_f5_verified_formula_publishes_one_file_and_recomputed_interpretation(
    tmp_path: Path,
) -> None:
    """F5: re-derived certificate interpretation and the unique PNG are the only publication."""
    module = load_filter_module()
    assert module.PASS_TEXT == _PASS
    assert module.FAIL_TEXT == _FAIL
    uri = valid_png_uri()
    body = filter_body("model claims different numbers and a different interpretation")
    messages = cast(list[dict[str, object]], body["messages"])
    messages[-1]["certificate"] = {"interpretation": "forged by model"}
    calls: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    async def rpc(payload: dict[str, object]) -> object:
        calls.append(payload)
        return _png_response(uri)

    async def emit(event: dict[str, object]) -> None:
        events.append(event)

    with fake_open_webui([], tmp_path):
        result = invoke_filter(
            module,
            body,
            request=recorded_request(_FORMULA, request_text=_REQUEST),
            user={"id": _USER},
            metadata={"session_id": "browser-session"},
            event_call=rpc,
            event_emitter=emit,
        )
    assert_filter_text(result, _expected_formula_pass())
    assert _files_events(events) == [
        {"type": "files", "data": {"files": [{"type": "image", "url": uri}]}}
    ]
    assert len(calls) == 1


def test_f6_dataset_rpc_uses_only_the_owned_file_consumed_by_verification(tmp_path: Path) -> None:
    """F6: exact RPC keys, uuid4 and one selected store file, never every attached file."""
    program = _sales_program()
    wrong = StoredFile("other", _USER, "other.csv", _sales_bytes())
    matching = StoredFile("selected", _USER, "sales.csv", _sales_bytes())
    verdict = verify_python_source(
        program, declared_target=DatasetTarget("/mnt/uploads/sales.csv", _sales_bytes())
    )
    assert isinstance(verdict, Verified)
    calls: list[dict[str, object]] = []

    async def rpc(payload: dict[str, object]) -> object:
        calls.append(payload)
        return _png_response()

    with fake_open_webui([wrong, matching], tmp_path) as lookups:
        result = invoke_filter(
            load_filter_module(),
            filter_body("not the certificate"),
            request=recorded_request(program, ("other", "selected")),
            user={"id": _USER},
            metadata={"session_id": "browser-session"},
            event_call=rpc,
            event_emitter=_record_event,
        )
    assert_filter_text(result, _PASS + "\n\n" + verdict.certificate.interpretation)
    assert lookups == [("other", _USER), ("selected", _USER)]
    assert len(calls) == 1
    payload = calls[0]
    assert payload["type"] == "execute:python"
    assert set(payload) == {"type", "data"}
    data = cast(dict[str, object], payload["data"])
    assert set(data) == {"id", "code", "session_id", "files"}
    assert isinstance(data["id"], str)
    assert uuid.UUID(data["id"]).version == 4
    assert data["session_id"] == "browser-session"
    assert data["files"] == [{"id": "selected", "filename": "sales.csv"}]
    assert isinstance(data["code"], str)
    _assert_encoded_program(data["code"], program)


def test_f6_formula_candidate_follows_unrelated_csv_and_rpc_files_are_empty(
    tmp_path: Path,
) -> None:
    """F6/F3: formula target follows a mismatching owned CSV and consumes no CSV in the RPC."""
    request = recorded_request(_FORMULA, ("unrelated",), _REQUEST)
    other = StoredFile("unrelated", _USER, "unrelated.csv", _sales_bytes())
    calls: list[dict[str, object]] = []

    async def rpc(payload: dict[str, object]) -> object:
        calls.append(payload)
        return _png_response()

    with fake_open_webui([other], tmp_path) as lookups:
        result = invoke_filter(
            load_filter_module(),
            filter_body("model reply"),
            request=request,
            user={"id": _USER},
            metadata={"session_id": "formula-session"},
            event_call=rpc,
            event_emitter=_record_event,
        )
    assert_filter_text(result, _expected_formula_pass())
    assert lookups == [("unrelated", _USER)]
    assert len(calls) == 1
    data = cast(dict[str, object], calls[0]["data"])
    assert data["files"] == []
    assert data["session_id"] == "formula-session"
    assert isinstance(data["code"], str)
    _assert_encoded_program(data["code"], _FORMULA)


def test_f6_rpc_timeout_is_bounded_by_sixty_seconds() -> None:
    """F6/A1: wrapper's asynchronous callback deadline has an explicit <=60 s bound."""
    module = load_filter_module()
    assert module.RPC_TIMEOUT_SECONDS == 60
    assert 0 < module.RPC_TIMEOUT_SECONDS <= 60


def test_f7_wrapper_compiles_with_own_show_hook_and_no_literal_plotting_module() -> None:
    """F7: gate-side source shape; the installed Pyodide run is F7's separate live witness."""
    module = load_filter_module()
    for program in (_FORMULA, _sales_program(), _FORMULA.replace("plt.show()\n", "")):
        code = module.wrapper_code(program)
        _assert_encoded_program(code, program)
        tree = ast.parse(code)
        nodes = tuple(ast.walk(tree))
        assert any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "savefig"
            for node in nodes
        )
        assert any(
            (
                isinstance(node, ast.Attribute)
                and node.attr == "show"
                and isinstance(node.ctx, ast.Store)
            )
            or (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "setattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "show"
            )
            for node in nodes
        )


def test_a6_owui_clean_reply_null_stderr_publishes_pass(tmp_path: Path) -> None:
    """A6: OWUI returns null stderr and a PNG line even when rendering succeeds."""
    uri = valid_png_uri()
    events: list[dict[str, object]] = []

    async def rpc(_payload: dict[str, object]) -> object:
        return {"stdout": uri + "\n", "stderr": None, "result": None}

    async def emit(event: dict[str, object]) -> None:
        events.append(event)

    with fake_open_webui([], tmp_path):
        result = invoke_filter(
            load_filter_module(),
            filter_body("untrusted model narration"),
            request=recorded_request(_FORMULA, request_text=_REQUEST),
            user={"id": _USER},
            metadata={"session_id": "browser-session"},
            event_call=rpc,
            event_emitter=emit,
        )
    assert_filter_text(result, _expected_formula_pass())
    assert _files_events(events) == [
        {"type": "files", "data": {"files": [{"type": "image", "url": uri}]}}
    ]


def test_a6_reply_without_stderr_key_fails(tmp_path: Path) -> None:
    """A6: a missing stderr field never means a clean sandbox run."""
    events: list[dict[str, object]] = []

    async def rpc(_payload: dict[str, object]) -> object:
        return {"stdout": valid_png_uri() + "\n", "result": None}

    async def emit(event: dict[str, object]) -> None:
        events.append(event)

    with fake_open_webui([], tmp_path):
        result = invoke_filter(
            load_filter_module(),
            filter_body("untrusted model narration"),
            request=recorded_request(_FORMULA, request_text=_REQUEST),
            user={"id": _USER},
            metadata={"session_id": "browser-session"},
            event_call=rpc,
            event_emitter=emit,
        )
    assert_filter_text(result, _FAIL)
    assert _files_events(events) == []


@pytest.mark.parametrize("stderr", [0, False, [], {}])
def test_a6_non_string_stderr_fails(stderr: object, tmp_path: Path) -> None:
    """A6: falsy values of other types cannot masquerade as empty stderr."""
    events: list[dict[str, object]] = []

    async def rpc(_payload: dict[str, object]) -> object:
        return {"stdout": valid_png_uri() + "\n", "stderr": stderr, "result": None}

    async def emit(event: dict[str, object]) -> None:
        events.append(event)

    with fake_open_webui([], tmp_path):
        result = invoke_filter(
            load_filter_module(),
            filter_body("untrusted model narration"),
            request=recorded_request(_FORMULA, request_text=_REQUEST),
            user={"id": _USER},
            metadata={"session_id": "browser-session"},
            event_call=rpc,
            event_emitter=emit,
        )
    assert_filter_text(result, _FAIL)
    assert _files_events(events) == []
