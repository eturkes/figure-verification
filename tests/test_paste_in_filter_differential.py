# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Differential: the outlet's effects versus an independent publication model."""

from __future__ import annotations

import asyncio
import base64
import binascii
import copy
import importlib
import uuid
from collections.abc import Awaitable
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.strategies import DrawFn

from filter_checks_support import embed_event, normalize_event
from filter_font_support import encoded_payloads
from observe_support import stdout_for_verified
from oracle_filter import (
    FAIL_TEXT,
    PASS_TEXT,
    Expected,
    FileRow,
    ReceiptValue,
    RpcFacts,
    RpcOutcome,
    Scenario,
    oracle_outlet,
    status_event,
)
from paste_in_support import REPO_ROOT, StoredFile, fake_open_webui
from verifier.pysrc import DatasetTarget, FormulaTarget, Verified, verify_python_source
from verifier.pysrc.request import formula_target

_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jVEkAAAAASUVORK5CYII="
)
_SALES = b"region,revenue\nUS,12\nEU,9\n"
_BAD_VALUES = b"region,revenue\nUS,bad\nEU,9\n"
_FORMULA_REQUEST = "y = sin(x), x in [0, 1], n = 3"
_FORMULA_PROGRAM = (
    "import numpy as np\n"
    "import matplotlib.pyplot as plt\n"
    "x = np.linspace(0, 1, num=3)\n"
    "plt.plot(x, np.sin(x))\n"
    "plt.show()\n"
)
_FAILING_PROGRAM = "print('no plotted mark')\n"


def _program(filename: str) -> str:
    return (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        f'frame = pd.read_csv("/mnt/uploads/{filename}")\n'
        'plt.bar(frame["region"], frame["revenue"])\n'
        "plt.show()\n"
    )


def _assistant(text: str = "Untrusted model prose") -> dict[str, object]:
    return {
        "role": "assistant",
        "content": text,
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": text}]},
            {"type": "reasoning", "content": [{"text": "old private reasoning"}]},
        ],
    }


def _reply(stdout: str = _PNG, stderr: str = "", result: object = None) -> RpcOutcome:
    return RpcOutcome("returns", {"stdout": stdout, "stderr": stderr, "result": result})


def _dataset_verdict(filename: str) -> Verified:
    program = _program(filename)
    verdict = verify_python_source(
        program, declared_target=DatasetTarget(f"/mnt/uploads/{filename}", _SALES)
    )
    assert isinstance(verdict, Verified)
    return verdict


def _formula_verdict() -> Verified:
    target = formula_target(_FORMULA_REQUEST)
    assert isinstance(target, FormulaTarget)
    verdict = verify_python_source(_FORMULA_PROGRAM, declared_target=target)
    assert isinstance(verdict, Verified)
    return verdict


def _dataset(filename: str = "a.csv", *, rpc: RpcOutcome | None = None) -> Scenario:
    return Scenario(
        ReceiptValue(_program(filename), ("file-a",), None),
        "caller",
        (FileRow("file-a", "caller", filename, _SALES),),
        _assistant(),
        {"session_id": "session-1"},
        rpc if rpc is not None else _reply(stdout_for_verified(_dataset_verdict(filename), _PNG)),
    )


def _formula(*, rpc: RpcOutcome | None = None) -> Scenario:
    return Scenario(
        ReceiptValue(_FORMULA_PROGRAM, (), _FORMULA_REQUEST),
        "caller",
        (),
        _assistant(),
        {"session_id": "session-2"},
        rpc if rpc is not None else _reply(stdout_for_verified(_formula_verdict(), _PNG)),
    )


def _font_scenario(kind: str, *, label: str = "年") -> Scenario:
    scenario = _formula() if kind == "formula-label" else _dataset()
    receipt = cast(ReceiptValue, scenario.receipt)
    labels = (label,) if kind != "csv" else ()
    program = (
        receipt.program.replace("plt.show()", f"plt.title({label!r})\nplt.show()")
        if labels
        else receipt.program
    )
    if kind == "formula-label":
        target = formula_target(_FORMULA_REQUEST)
        assert isinstance(target, FormulaTarget)
        verdict = verify_python_source(program, declared_target=target)
        rows = scenario.stored
    else:
        content = "region,revenue\n日本,12\nEU,9\n".encode() if kind == "csv" else _SALES
        verdict = verify_python_source(
            program, declared_target=DatasetTarget("/mnt/uploads/a.csv", content)
        )
        rows = (FileRow("file-a", "caller", "a.csv", content),)
    assert isinstance(verdict, Verified), verdict
    return replace(
        scenario,
        receipt=replace(receipt, program=program),
        stored=rows,
        labels=labels,
        rpc=_reply(stdout_for_verified(verdict, _PNG)),
        font_bytes=None if kind == "unavailable" else scenario.font_bytes,
    )


def _anchors() -> tuple[tuple[str, Scenario, bool, int, int], ...]:
    dataset = _dataset()
    formula = _formula()
    receipt = cast(ReceiptValue, dataset.receipt)
    mismatch_then_match = replace(
        _dataset("b.csv"),
        receipt=ReceiptValue(_program("b.csv"), ("file-a", "file-b"), None),
        stored=(
            FileRow("file-a", "caller", "a.csv", _SALES),
            FileRow("file-b", "caller", "b.csv", _SALES),
        ),
    )
    refusal_then_match = replace(
        dataset,
        receipt=ReceiptValue(_program("a.csv"), ("file-a", "file-b"), None),
        stored=(
            FileRow("file-a", "caller", "a.csv", _BAD_VALUES),
            FileRow("file-b", "caller", "a.csv", _SALES),
        ),
    )
    return (
        ("dataset-pass", dataset, True, 1, 1),
        ("formula-pass", formula, True, 1, 1),
        ("ja-label-pass", _font_scenario("label"), True, 1, 1),
        ("ja-csv-pass", _font_scenario("csv"), True, 1, 1),
        ("ja-formula-label-pass", _font_scenario("formula-label"), True, 1, 1),
        ("ja-font-unavailable-pass", _font_scenario("unavailable"), True, 1, 1),
        ("mismatch-continues-to-second", mismatch_then_match, True, 1, 1),
        ("first-other-refusal-stops", refusal_then_match, False, 0, 0),
        ("no-receipt-prose", replace(dataset, receipt=None), False, 0, 0),
        ("no-backend-request", replace(dataset, request_present=False), False, 0, 0),
        (
            "no-receipt-pass-claim",
            replace(dataset, receipt=None, assistant=_assistant(PASS_TEXT)),
            False,
            0,
            0,
        ),
        ("no-receipt-png", replace(dataset, receipt=None, assistant=_assistant(_PNG)), False, 0, 0),
        (
            "no-receipt-serialized-text",
            replace(dataset, receipt=None, assistant=_assistant(repr(receipt))),
            False,
            0,
            0,
        ),
        (
            "no-receipt-body-field",
            replace(dataset, receipt=None, body_fields={"receipt": receipt}),
            False,
            0,
            0,
        ),
        (
            "no-receipt-citation",
            replace(dataset, receipt=None, body_fields={"sources": [PASS_TEXT, receipt]}),
            False,
            0,
            0,
        ),
        (
            "no-receipt-fenced-program",
            replace(
                dataset, receipt=None, assistant=_assistant(f"```python\n{_program('a.csv')}```")
            ),
            False,
            0,
            0,
        ),
        (
            "no-receipt-client-metadata",
            replace(
                dataset, receipt=None, metadata={"session_id": "session-1", "receipt": receipt}
            ),
            False,
            0,
            0,
        ),
        ("foreign-state-value", replace(dataset, receipt="serialized receipt"), False, 0, 0),
        (
            "foreign-state-tuple-tag",
            replace(dataset, receipt=("forged-tag", receipt.program, receipt.file_ids, None)),
            False,
            0,
            0,
        ),
        (
            "foreign-state-tuple-fields",
            replace(
                dataset,
                receipt=("figure-verification-receipt/2", receipt.program, ["file-a"], None, ()),
            ),
            False,
            0,
            0,
        ),
        ("no-request-user", replace(dataset, user_id=None), False, 0, 0),
        ("other-user", replace(dataset, user_id="other"), False, 0, 0),
        ("missing-file-id", replace(dataset, stored=()), False, 0, 0),
        (
            "foreign-file-id",
            replace(dataset, stored=(FileRow("file-a", "owner", "a.csv", _SALES),)),
            False,
            0,
            0,
        ),
        (
            "formula-last-after-csv-mismatch",
            replace(
                formula,
                receipt=ReceiptValue(_FORMULA_PROGRAM, ("file-a",), _FORMULA_REQUEST),
                stored=(FileRow("file-a", "caller", "a.csv", _SALES),),
            ),
            True,
            1,
            1,
        ),
        (
            "refused-program",
            replace(dataset, receipt=ReceiptValue(_FAILING_PROGRAM, ("file-a",), None)),
            False,
            0,
            0,
        ),
        ("rpc-absent", replace(dataset, rpc=RpcOutcome("absent")), False, 0, 0),
        ("rpc-raises", replace(dataset, rpc=RpcOutcome("raises")), False, 1, 0),
        ("rpc-times-out", replace(dataset, rpc=RpcOutcome("timeout")), False, 1, 0),
        ("rpc-non-dict", replace(dataset, rpc=RpcOutcome("returns", "wrong shape")), False, 1, 0),
        ("rpc-stderr", replace(dataset, rpc=_reply(stderr="sandbox exception")), False, 1, 0),
        ("rpc-no-observation", replace(dataset, rpc=_reply(stdout=_PNG)), False, 1, 0),
        (
            "rpc-null-stderr",
            replace(
                dataset,
                rpc=RpcOutcome(
                    "returns",
                    {
                        "stdout": stdout_for_verified(_dataset_verdict("a.csv"), _PNG) + "\n",
                        "stderr": None,
                        "result": None,
                    },
                ),
            ),
            True,
            1,
            1,
        ),
        (
            "rpc-missing-stderr",
            replace(
                dataset,
                rpc=RpcOutcome(
                    "returns",
                    {
                        "stdout": stdout_for_verified(_dataset_verdict("a.csv"), _PNG) + "\n",
                        "result": None,
                    },
                ),
            ),
            False,
            1,
            0,
        ),
        ("rpc-no-png", replace(dataset, rpc=_reply(stdout="ordinary stdout")), False, 1, 0),
        ("rpc-two-pngs", replace(dataset, rpc=_reply(stdout=f"{_PNG}\n{_PNG}")), False, 1, 0),
        (
            "rpc-wrong-mime",
            replace(dataset, rpc=_reply(stdout=_PNG.replace("image/png", "image/jpeg"))),
            False,
            1,
            0,
        ),
        (
            "rpc-invalid-base64",
            replace(dataset, rpc=_reply(stdout="data:image/png;base64,!!!!")),
            False,
            1,
            0,
        ),
        (
            "rpc-mislabeled-bytes",
            replace(dataset, rpc=_reply(stdout="data:image/png;base64,YWJj")),
            False,
            1,
            0,
        ),
        (
            "rpc-valid-png-plus-invalid-uri",
            replace(dataset, rpc=_reply(stdout=f"{_PNG}\ndata:image/jpeg;base64,YWJj")),
            False,
            1,
            0,
        ),
        (
            "rpc-result-ignored",
            replace(
                dataset,
                rpc=_reply(
                    stdout=stdout_for_verified(_dataset_verdict("a.csv"), _PNG),
                    result={"untrusted_result": PASS_TEXT},
                ),
            ),
            True,
            1,
            1,
        ),
    )


def _cause_anchors() -> tuple[tuple[str, Scenario, str], ...]:
    dataset = _dataset()
    return (
        ("no-tool-call", replace(dataset, receipt=None), "no_tool_call"),
        ("no-user", replace(dataset, user_id=None), "no_user"),
        ("no-target", replace(dataset, stored=()), "no_target"),
        (
            "lone-csv-mismatch",
            replace(dataset, receipt=ReceiptValue(_program("b.csv"), ("file-a",), None)),
            "target_mismatch",
        ),
        ("no-metadata", replace(dataset, metadata=None), "no_browser"),
        ("no-session", replace(dataset, metadata={}), "no_browser"),
        ("no-emitter", replace(dataset, emitter_present=False), "no_browser"),
        ("timeout", replace(dataset, rpc=RpcOutcome("timeout")), "browser_timeout"),
        ("rpc-error", replace(dataset, rpc=RpcOutcome("raises")), "browser_error"),
        (
            "caller-error",
            replace(dataset, rpc=RpcOutcome("returns", {"error": "gone"})),
            "browser_no_answer",
        ),
        ("malformed-reply", replace(dataset, rpc=RpcOutcome("returns", {})), "reply_malformed"),
        (
            "non-string-stderr",
            replace(dataset, rpc=RpcOutcome("returns", {"stderr": False, "error": "caller"})),
            "reply_malformed",
        ),
        (
            "str-subclass-stderr",
            replace(dataset, rpc=_reply(stderr=type("EmptyText", (str,), {})(""))),
            "reply_malformed",
        ),
        (
            "loader-chromium",
            replace(dataset, rpc=_reply(stderr="loadPyodide is not defined")),
            "sandbox_unavailable",
        ),
        (
            "loader-webkit",
            replace(dataset, rpc=_reply(stderr="Can't find variable: loadPyodide")),
            "sandbox_unavailable",
        ),
        (
            "traceback-loader",
            replace(dataset, rpc=_reply(stderr="Traceback (most recent call last):\nloadPyodide")),
            "sandbox_error",
        ),
        ("sandbox", replace(dataset, rpc=_reply(stderr="upload failed")), "sandbox_error"),
        ("no-image", replace(dataset, rpc=_reply(stdout="")), "no_image"),
        ("no-observation", replace(dataset, rpc=_reply()), "no_observation"),
        ("publish-error", replace(dataset, publish_raises=True), "publish_failed"),
        (
            "kana-no-receipt",
            replace(dataset, receipt=None, metadata={"user_message": {"content": "ｶ"}}),
            "no_tool_call",
        ),
        (
            "kanji-no-receipt",
            replace(dataset, receipt=None, metadata={"user_message": {"content": "漢字・漢字ー"}}),
            "no_tool_call",
        ),
    )


_CAUSE_ANCHORS = _cause_anchors()
_ANCHORS = _anchors() + tuple(
    (
        name,
        scenario,
        False,
        0
        if reason in {"no_tool_call", "no_user", "no_target", "target_mismatch", "no_browser"}
        else 1,
        1 if reason == "publish_failed" else 0,
    )
    for name, scenario, reason in _CAUSE_ANCHORS
)


@pytest.mark.parametrize(
    "name,scenario,reason", _CAUSE_ANCHORS, ids=[row[0] for row in _CAUSE_ANCHORS]
)
def test_d9_oracle_causes_are_hand_stated(name: str, scenario: Scenario, reason: str) -> None:
    expected = oracle_outlet(scenario)
    assert expected.content == FAIL_TEXT, name
    statuses = (status_event(reason, scenario.metadata),) if scenario.emitter_present else ()
    assert expected.status_events == statuses, name
    embeds = (embed_event(reason, scenario.metadata),) if scenario.emitter_present else ()
    assert expected.embed_events == embeds, name


@pytest.mark.parametrize(
    "name,scenario,passes,rpc_count,event_count", _ANCHORS, ids=[case[0] for case in _ANCHORS]
)
def test_oracle_hand_stated_contract_cases(
    name: str, scenario: Scenario, passes: object, rpc_count: int, event_count: int
) -> None:
    """F2-F6: independently named outcomes pin the model before production is loaded."""
    assert isinstance(passes, bool)
    expected = oracle_outlet(scenario)
    assert (expected.content.startswith(PASS_TEXT + "\n\n")) is passes, name
    if not passes:
        assert expected.content == FAIL_TEXT, name
    assert expected.rpc.count == rpc_count, name
    assert len(expected.files_events) == event_count, name
    assert len(expected.output) == 1, name
    assert expected.output[0]["status"] == "completed", name
    if passes:
        assert expected.content.split("\n\n", 1)[1].startswith("Chart type: ")


def _load_filter() -> ModuleType:
    module = importlib.import_module("webui.paste_in.filter")
    assert Path(cast(str, module.__file__)).resolve() == REPO_ROOT / "webui/paste_in/filter.py"
    assert (
        Path(oracle_outlet.__code__.co_filename).resolve() == REPO_ROOT / "tests/oracle_filter.py"
    )
    assert (
        Path(verify_python_source.__code__.co_filename).resolve()
        == REPO_ROOT / "src/verifier/pysrc/verify.py"
    )
    return module


def test_filter_and_tool_bind_one_selection_function() -> None:
    """F3: both artefacts bind the SAME selection function, not lookalike copies."""
    filter_module = _load_filter()
    tool_module = importlib.import_module("webui.paste_in.tool")
    selection = importlib.import_module("webui.paste_in.selection")
    assert filter_module.first_verdict is tool_module.first_verdict is selection.first_verdict


def _state(scenario: Scenario) -> SimpleNamespace:
    state = SimpleNamespace()
    receipt = scenario.receipt
    if isinstance(receipt, ReceiptValue):
        value: object = (
            "figure-verification-receipt/2",
            receipt.program,
            receipt.file_ids,
            receipt.request_text,
            (),
        )
    else:
        value = receipt
    if value is not None:
        state.figure_verification_receipt = value
    return state


def _b64_program(code: str, scenario: Scenario) -> tuple[str, bytes | None]:
    """Classify decoded content, independently of payload variable names or their source order."""
    try:
        payloads = list(encoded_payloads(code))
    except (SyntaxError, binascii.Error, ValueError) as exc:
        failure = "RPC source is not parseable base64 Python"
        raise AssertionError(failure) from exc
    receipt = scenario.receipt
    assert isinstance(receipt, ReceiptValue), "RPC without a program receipt"
    program = receipt.program.encode("utf-8")
    assert payloads.count(program) == 1, "RPC must contain exactly one unchanged program"
    payloads.remove(program)
    if not payloads:
        return receipt.program, None
    assert len(payloads) == 1, "RPC contains extra encoded payloads"
    assert payloads[0] == scenario.font_bytes, "RPC font differs from the supplied font bytes"
    return receipt.program, payloads[0]


def _rpc_facts(calls: list[dict[str, object]], scenario: Scenario) -> RpcFacts:
    if not calls:
        return RpcFacts(0)
    if len(calls) != 1:
        return RpcFacts(len(calls))
    payload = calls[0]
    if set(payload) != {"type", "data"} or payload["type"] != "execute:python":
        failure = "unmapped RPC type or keys"
        raise AssertionError(failure)
    data = payload["data"]
    if not isinstance(data, dict) or set(data) != {"id", "code", "session_id", "files"}:
        failure = "unmapped execute:python data"
        raise AssertionError(failure)
    code = data["code"]
    identifier = data["id"]
    files = data["files"]
    assert isinstance(code, str) and isinstance(identifier, str) and isinstance(files, list), (
        "unmapped RPC fields"
    )
    mapped_files: list[tuple[str, str]] = []
    for file in files:
        if not isinstance(file, dict) or set(file) != {"id", "filename"}:
            failure = "unmapped RPC file entry"
            raise AssertionError(failure)
        file_id, filename = file["id"], file["filename"]
        assert isinstance(file_id, str) and isinstance(filename, str), "unmapped RPC file value"
        mapped_files.append((file_id, filename))
    try:
        parsed_id = uuid.UUID(identifier)
    except ValueError:
        uuid4_valid = False
    else:
        uuid4_valid = str(parsed_id) == identifier and parsed_id.version == 4
    program, font = _b64_program(code, scenario)
    return RpcFacts(
        count=1,
        files=tuple(mapped_files),
        program=program,
        session_id=data["session_id"],
        valid_uuid4=uuid4_valid,
        code_without_literal="matplotlib" not in code,
        font=font,
    )


def _translate_outlet(  # noqa: PLR0915 - preserve every publication-shape conjunct
    scenario: Scenario, module: ModuleType, root: Path, patch: pytest.MonkeyPatch
) -> Expected:
    """Drive the real outlet through strict fakes; reject every effect outside F2-F6."""
    previous: dict[str, object] = {"role": "user", "content": "original question"}
    body: dict[str, object] = {
        **copy.deepcopy(scenario.body_fields),
        "messages": [copy.deepcopy(previous), copy.deepcopy(scenario.assistant)],
    }
    calls: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    async def call(payload: dict[str, object]) -> object:
        calls.append(copy.deepcopy(payload))
        if scenario.rpc.kind == "raises":
            failure = "sandbox failed"
            raise RuntimeError(failure)
        if scenario.rpc.kind == "timeout":
            pending: asyncio.Future[object] = asyncio.Future()
            return await pending
        assert scenario.rpc.kind == "returns"
        return scenario.rpc.value

    async def emit(event: dict[str, object]) -> None:
        events.append(copy.deepcopy(event))
        if scenario.publish_raises and event.get("type") == "files":
            failure = "file publication failed"
            raise RuntimeError(failure)

    async def cjk_font() -> bytes | None:
        return scenario.font_bytes

    patch.setattr(module, "cjk_font", cjk_font, raising=False)
    if scenario.rpc.kind == "timeout":
        patch.setattr(module, "RPC_TIMEOUT_SECONDS", 0.002)
    else:
        assert module.RPC_TIMEOUT_SECONDS == 60
    fake_rows = tuple(
        StoredFile(row.file_id, row.owner, row.filename, row.content) for row in scenario.stored
    )
    with fake_open_webui(fake_rows, root) as lookups:
        function = module.Filter().outlet

        async def complete() -> dict[str, object]:
            return await asyncio.wait_for(
                cast(
                    Awaitable[dict[str, object]],
                    function(
                        body,
                        __user__={"id": scenario.user_id} if scenario.user_id is not None else None,
                        __request__=(
                            SimpleNamespace(state=_state(scenario))
                            if scenario.request_present
                            else None
                        ),
                        __event_call__=call if scenario.rpc.kind != "absent" else None,
                        __event_emitter__=emit if scenario.emitter_present else None,
                        __metadata__=scenario.metadata,
                    ),
                ),
                timeout=0.5,
            )

        returned = asyncio.run(complete())
    assert returned is body, "outlet replaced body rather than editing last assistant message"
    messages = body.get("messages")
    if not isinstance(messages, list) or len(messages) != 2 or messages[0] != previous:
        failure = "outlet changed earlier messages or message count"
        raise AssertionError(failure)
    assistant = messages[-1]
    assert isinstance(assistant, dict), "outlet produced a non-dict assistant"
    if set(assistant) - set(scenario.assistant) != {"content", "output"} - set(scenario.assistant):
        failure = "outlet changed assistant fields other than content/output"
        raise AssertionError(failure)
    if any(
        assistant.get(key) != value
        for key, value in scenario.assistant.items()
        if key not in {"content", "output"}
    ):
        failure = "outlet rewrote unrelated assistant fields"
        raise AssertionError(failure)
    content, output = assistant.get("content"), assistant.get("output")
    assert isinstance(content, str) and isinstance(output, list), (
        "outlet did not emit content and output"
    )
    if not all(isinstance(item, dict) for item in output):
        failure = "unmapped output item"
        raise AssertionError(failure)
    files_events: list[dict[str, object]] = []
    status_events: list[dict[str, object]] = []
    embed_events: list[dict[str, object]] = []
    mapped_events = [normalize_event(event) for event in events]
    for event in mapped_events:
        if event.get("type") == "status":
            status_events.append(event)
        elif event.get("type") == "embeds":
            embed_events.append(event)
        else:
            if set(event) != {"type", "data"} or event["type"] != "files":
                failure = "unmapped files event"
                raise AssertionError(failure)
            files_events.append(event)
    expected = oracle_outlet(scenario)
    assert tuple(status_events) == expected.status_events, "unmapped status event"
    assert tuple(embed_events) == expected.embed_events, "unmapped embed event"
    assert mapped_events == files_events + status_events + embed_events, "diagnostics must be last"
    receipt = scenario.receipt
    expected_lookups = (
        [(file_id, scenario.user_id) for file_id in receipt.file_ids]
        if scenario.request_present
        and isinstance(receipt, ReceiptValue)
        and isinstance(scenario.user_id, str)
        else []
    )
    assert lookups == expected_lookups, "every receipt id must use caller-owned lookup in order"
    assert all(body.get(key) == value for key, value in scenario.body_fields.items())
    return Expected(
        content,
        tuple(output),
        tuple(files_events),
        _rpc_facts(calls, scenario),
        tuple(status_events),
        tuple(embed_events),
    )


def _assert_agrees(scenario: Scenario, module: ModuleType, patch: pytest.MonkeyPatch) -> None:
    expected = oracle_outlet(scenario)
    with TemporaryDirectory(prefix="filter-oracle-") as directory, patch.context() as scoped:
        observed = _translate_outlet(scenario, module, Path(directory), scoped)
    assert observed.rpc.font == expected.rpc.font, (
        "RPC font payload differs from independent trigger"
    )
    assert observed == expected, (scenario, expected, observed)


@st.composite
def _pass_scenarios(draw: DrawFn) -> Scenario:
    arm = draw(st.sampled_from(("dataset", "formula", "font")))
    if arm == "font":
        kind = draw(st.sampled_from(("label", "csv", "formula-label", "unavailable")))
        label = draw(st.sampled_from(("年", "平均", "é", "ASCII", "")))
        return _font_scenario(kind, label=label)
    prose = draw(st.sampled_from((False, True)))
    if arm == "formula":
        verdict = _formula_verdict()
        filename = None
    else:
        filename = draw(st.sampled_from(("a.csv", "b.csv", "clinical.csv")))
        verdict = _dataset_verdict(filename)
    stdout = stdout_for_verified(verdict, _PNG, prefix="output\n" if prose else "")
    if prose:
        stdout += "\n"
    response = _reply(stdout=stdout)
    return _formula(rpc=response) if filename is None else _dataset(filename, rpc=response)


@st.composite
def _arbitrary_scenarios(draw: DrawFn) -> Scenario:
    anchor = draw(st.sampled_from(_ANCHORS))[1]
    content = draw(st.sampled_from(("English", "あ", "ｶ", "漢字", "漢字・漢字ー", ["かな"], None)))
    metadata = (
        {**anchor.metadata, "user_message": {"content": content}}
        if anchor.metadata is not None
        else None
    )
    return replace(
        anchor,
        metadata=metadata,
        assistant=_assistant(
            draw(
                st.sampled_from(
                    (
                        "ordinary prose",
                        PASS_TEXT,
                        _PNG,
                        "```python\n" + _FORMULA_PROGRAM + "```",
                        "Figure verification failed, no image produced",
                    )
                )
            )
        ),
    )


@st.composite
def _batches(draw: DrawFn) -> tuple[Scenario, ...]:
    # Four forced passing scenarios per ten: a regression that makes every case FAIL cannot be
    # hidden by a run's random mix, and the >=25% PASS guard is checked against actual verdicts.
    cases = [draw(_pass_scenarios()) for _ in range(4)]
    cases.extend(draw(_arbitrary_scenarios()) for _ in range(6))
    order = draw(st.permutations(tuple(range(len(cases)))))
    return tuple(cases[index] for index in order)


@given(batch=_batches())
@settings(max_examples=16, deadline=None)
def test_outlet_differential(batch: tuple[Scenario, ...]) -> None:
    """F2-F6: 160 scenarios/run plus the fixed anchors; >=25% must expect PASS."""
    assert sum(oracle_outlet(case).content.startswith(PASS_TEXT + "\n\n") for case in batch) >= 3
    module = _load_filter()
    with pytest.MonkeyPatch.context() as patch:
        for case in batch:
            _assert_agrees(case, module, patch)


@pytest.mark.parametrize(
    "name,scenario,passes,rpc_count,event_count", _ANCHORS, ids=[case[0] for case in _ANCHORS]
)
def test_outlet_fixed_anchor(
    name: str, scenario: Scenario, passes: object, rpc_count: int, event_count: int
) -> None:
    """Each F2-F6 conjunct has a fixed, named witness in addition to generated scenarios."""
    assert isinstance(passes, bool)
    assert oracle_outlet(scenario).content.startswith(PASS_TEXT + "\n\n") is passes, name
    del rpc_count, event_count
    module = _load_filter()
    with pytest.MonkeyPatch.context() as patch:
        _assert_agrees(scenario, module, patch)


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("ascii", None),
        ("label", b"\x00\x01\x00\x00independent fake font\xff"),
        ("csv", b"\x00\x01\x00\x00independent fake font\xff"),
        ("formula-label", b"\x00\x01\x00\x00independent fake font\xff"),
        ("unavailable", None),
    ],
)
def test_f6_oracle_font_expectations_are_hand_stated(kind: str, expected: bytes | None) -> None:
    scenario = _dataset() if kind == "ascii" else _font_scenario(kind)
    assert oracle_outlet(scenario).rpc.font == expected


def _payload_source(*payloads: bytes) -> str:
    return "\n".join(f"base64.b64decode({base64.b64encode(value)!r})" for value in payloads)


@pytest.mark.parametrize("reverse", [False, True])
def test_f6_differential_separates_font_and_program_payloads(*, reverse: bool) -> None:
    scenario = _font_scenario("label")
    receipt = cast(ReceiptValue, scenario.receipt)
    assert scenario.font_bytes is not None
    payloads: tuple[bytes, ...] = (receipt.program.encode(), scenario.font_bytes)
    if reverse:
        payloads = tuple(reversed(payloads))
    assert _b64_program(_payload_source(*payloads), scenario) == (
        receipt.program,
        scenario.font_bytes,
    )


@pytest.mark.parametrize(
    "fault", ["corrupt-font", "duplicate-font", "duplicate-program", "wrong-program"]
)
def test_f6_translation_rejects_altered_or_extra_payloads(fault: str) -> None:
    scenario = _font_scenario("label")
    receipt = cast(ReceiptValue, scenario.receipt)
    assert scenario.font_bytes is not None
    program, font = receipt.program.encode(), scenario.font_bytes
    payloads = {
        "corrupt-font": (program, b"another font"),
        "duplicate-font": (program, font, font),
        "duplicate-program": (program, program, font),
        "wrong-program": (b"print('substituted')", font),
    }
    with pytest.raises(AssertionError):
        _b64_program(_payload_source(*payloads[fault]), scenario)


def test_f6_translation_exposes_absent_and_unexpected_font() -> None:
    ascii_scenario = _dataset()
    ja_scenario = _font_scenario("label")
    for scenario in (ascii_scenario, ja_scenario):
        receipt = cast(ReceiptValue, scenario.receipt)
        assert scenario.font_bytes is not None
        expected_font = oracle_outlet(scenario).rpc.font
        payloads: tuple[bytes, ...] = (receipt.program.encode(),)
        if expected_font is None:
            payloads += (scenario.font_bytes,)
        _program_text, observed_font = _b64_program(_payload_source(*payloads), scenario)
        assert observed_font != expected_font
