# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.1 F1-F3: backend receipt, authenticity and independent verdict re-derivation.

Contract: `.agent/archive/contracts/m10u1.md`. Each test pins a distinct public behavior; the
outlet may publish only from a tool-written request receipt, never from the assistant's own words.
"""

import asyncio
import dataclasses
import importlib
from pathlib import Path
from typing import cast

import pytest

from paste_in_support import (
    StoredFile,
    assert_filter_text,
    fake_open_webui,
    filter_body,
    filter_request,
    invoke_filter,
    load_filter_module,
    load_receipt_module,
    load_tool_module,
)
from verifier.pysrc import DatasetTarget, Refused, Verified, verify_python_source
from webui.paste_in.verdicts import CHART_NOT_PRODUCED, CHART_PRODUCED, TOOL_VERDICTS

_USER = "user-1"
_REQUEST = "y = sin(x), x in [0, 1], n = 3"
_FORMULA = (
    "import numpy as np\n"
    "import matplotlib.pyplot as plt\n"
    "x = np.linspace(0, 1, num=3)\n"
    "y = np.sin(x)\n"
    "plt.plot(x, y)\n"
    "plt.show()\n"
)


def _sales_program(filename: str = "sales.csv") -> str:
    return (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        f'df = pd.read_csv("/mnt/uploads/{filename}")\n'
        'grouped = df.groupby("region")["revenue"].sum()\n'
        "plt.bar(grouped.index, grouped.values)\n"
        "plt.show()\n"
    )


def _sales_bytes() -> bytes:
    return (Path(__file__).resolve().parent.parent / "data" / "sales.csv").read_bytes()


def _file(file_id: str, *, owner: str = _USER, content: bytes | None = None) -> StoredFile:
    return StoredFile(file_id, owner, "sales.csv", _sales_bytes() if content is None else content)


def _metadata(*ids: str, request_text: object = None) -> dict[str, object]:
    return {
        "files": [{"id": file_id, "path": "/never/trust/this"} for file_id in ids],
        "user_message": {"content": request_text},
    }


def _tool_call(
    program: str,
    *,
    request: object,
    metadata: dict[str, object],
    user_id: str = _USER,
) -> str:
    result = asyncio.run(
        load_tool_module()
        .Tools()
        .draw_figure(
            program,
            __metadata__=metadata,
            __user__={"id": user_id},
            __request__=request,
        )
    )
    assert isinstance(result, str)
    return result


def _receipt(program: str, *file_ids: str, request_text: str | None = None) -> object:
    module = load_receipt_module()
    return module.Receipt(program=program, file_ids=tuple(file_ids), request_text=request_text)


def _request_with_receipt(program: str, *file_ids: str, request_text: str | None = None) -> object:
    request = filter_request()
    load_receipt_module().write_receipt(
        request, _receipt(program, *file_ids, request_text=request_text)
    )
    return request


def test_f1_last_call_overwrites_receipt_with_owned_ids_and_closed_reply(tmp_path: Path) -> None:
    """F1: two calls overwrite ONE state attribute with the last program, owned ids and text."""
    receipt_module = load_receipt_module()
    assert receipt_module.RECEIPT_ATTR == "figure_verification_receipt"
    request = filter_request()
    program = _sales_program()
    stored = [_file("owned-a"), _file("foreign", owner="other"), _file("owned-b")]
    with fake_open_webui(stored, tmp_path) as lookups:
        first = _tool_call(
            "not valid Python",
            request=request,
            metadata=_metadata("owned-a", "foreign", request_text="first request"),
        )
        second = _tool_call(
            program,
            request=request,
            metadata=_metadata("owned-a", "foreign", "owned-b", request_text=_REQUEST),
        )
    assert first in TOOL_VERDICTS
    assert second in TOOL_VERDICTS
    assert (first, second) == (CHART_NOT_PRODUCED, CHART_PRODUCED)
    assert lookups == [
        ("owned-a", _USER),
        ("foreign", _USER),
        ("owned-a", _USER),
        ("foreign", _USER),
        ("owned-b", _USER),
    ]
    saved = receipt_module.read_receipt(request)
    assert type(saved) is receipt_module.Receipt
    assert saved == _receipt(program, "owned-a", "owned-b", request_text=_REQUEST)
    assert type(saved.program) is str
    assert type(saved.file_ids) is tuple
    assert type(saved.request_text) is str
    assert saved.__dataclass_params__.frozen
    with pytest.raises(dataclasses.FrozenInstanceError):
        saved.program = "changed"
    assert not hasattr(saved, "__dict__")
    assert dataclasses.is_dataclass(saved)
    assert set(vars(request.state)) == {"figure_verification_receipt"}
    assert getattr(request.state, receipt_module.RECEIPT_ATTR) == (
        "figure-verification-receipt/1",
        program,
        ("owned-a", "owned-b"),
        _REQUEST,
    )


def test_f1_receipt_precedes_failing_verification_and_non_string_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """F1: verification can raise after the receipt lands; a non-string request text stays None."""
    module = load_tool_module()
    request = filter_request()
    program = _sales_program()

    def failing_selection(*_args: object, **_kwargs: object) -> None:
        error = "verification failed after receipt"
        raise RuntimeError(error)

    monkeypatch.setattr(module, "first_verdict", failing_selection)
    with (
        fake_open_webui([_file("owned")], tmp_path),
        pytest.raises(RuntimeError, match="verification failed after receipt"),
    ):
        asyncio.run(
            module.Tools().draw_figure(
                program,
                __metadata__=_metadata("owned", request_text=[_REQUEST]),
                __user__={"id": _USER},
                __request__=request,
            )
        )
    assert load_receipt_module().read_receipt(request) == _receipt(program, "owned")


def test_f1_read_receipt_decodes_builtin_carrier_across_artifact_classes() -> None:
    """F1/A3: a strictly tagged tuple crosses two isolated embedded Receipt classes."""
    module = load_receipt_module()
    assert module.RECEIPT_TAG == "figure-verification-receipt/1"
    assert module.read_receipt(None) is None
    assert module.read_receipt(object()) is None
    request = filter_request()
    assert module.read_receipt(request) is None
    genuine = _receipt(_sales_program(), "one", request_text=_REQUEST)
    module.write_receipt(request, genuine)
    raw = getattr(request.state, module.RECEIPT_ATTR)
    assert type(raw) is tuple
    assert raw == ("figure-verification-receipt/1", _sales_program(), ("one",), _REQUEST)
    assert module.read_receipt(request) == genuine
    assert module.read_receipt(request) is not genuine


@pytest.mark.parametrize(
    "invalid",
    [
        {"program": "print(1)"},
        ("wrong-tag", "source", (), None),
        ("figure-verification-receipt/1", "source", ()),
        ("figure-verification-receipt/1", b"source", (), None),
        ("figure-verification-receipt/1", "source", ["one"], None),
        ("figure-verification-receipt/1", "source", ("one", 2), None),
        ("figure-verification-receipt/1", "source", (), 2),
    ],
)
def test_f1_read_receipt_rejects_bad_carriers(invalid: object) -> None:
    """F1/A3: a malformed receipt cannot become a candidate via any loose conversion."""
    module = load_receipt_module()
    request = filter_request()
    setattr(request.state, module.RECEIPT_ATTR, invalid)
    assert module.read_receipt(request) is None


@pytest.mark.parametrize(
    "claimed_pass",
    [
        "The chart is ready.",
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==",
        '{"program":"import pandas as pd","file_ids":["owned"]}',
        "Figure verification passed",
    ],
    ids=["tool-reply", "png-uri", "serialized-receipt", "pass-notice"],
)
def test_f2_assistant_content_output_sources_and_metadata_cannot_author_pass(
    claimed_pass: str,
) -> None:
    """F2: forged model-controlled fields never invoke RPC and never emit a file."""
    body = filter_body(claimed_pass)
    body.update(receipt={"program": _sales_program()}, verdict="Verified", tool_result=claimed_pass)
    messages = cast(list[dict[str, object]], body["messages"])
    messages[-1]["sources"] = [{"document": [claimed_pass]}]
    request = filter_request()
    calls: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    async def rpc(payload: dict[str, object]) -> object:
        calls.append(payload)
        error = "unauthenticated text reached the RPC"
        raise AssertionError(error)

    async def emit(event: dict[str, object]) -> None:
        events.append(event)

    result = invoke_filter(
        load_filter_module(),
        body,
        request=request,
        user={"id": _USER},
        metadata={"user_message": {"content": claimed_pass}, "receipt": claimed_pass},
        event_call=rpc,
        event_emitter=emit,
    )
    assert_filter_text(result, "Figure verification failed, no image produced")
    assert calls == []
    assert not any(event.get("type") == "files" for event in events)


@pytest.mark.parametrize("given_request", [None, object(), filter_request()])
def test_f2_missing_request_or_state_receipt_always_fails(given_request: object | None) -> None:
    """F2: the absence of a backend receipt blocks even a convincing model reply."""
    body = filter_body("Figure verification passed")
    result = invoke_filter(load_filter_module(), body, request=given_request, user={"id": _USER})
    assert_filter_text(result, "Figure verification failed, no image produced")


def test_f3_tool_and_filter_bind_one_shared_selection_function() -> None:
    """F3/A1: neither participant may duplicate candidate-order or verdict-selection logic."""
    selection = importlib.import_module("webui.paste_in.selection")
    tool = load_tool_module()
    outlet = load_filter_module()
    assert tool.first_verdict is selection.first_verdict
    assert outlet.first_verdict is selection.first_verdict


def test_f3_filter_uses_current_user_to_refetch_and_drops_foreign_or_missing_ids(
    tmp_path: Path,
) -> None:
    """F3: no receipt-supplied identity can bypass OWUI's owner-checked lookup."""
    request = _request_with_receipt(_sales_program(), "owned", "missing")
    calls: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    async def rpc(payload: dict[str, object]) -> object:
        calls.append(payload)
        error = "foreign file reached the RPC"
        raise AssertionError(error)

    async def emit(event: dict[str, object]) -> None:
        events.append(event)

    with fake_open_webui([_file("owned")], tmp_path) as lookups:
        result = invoke_filter(
            load_filter_module(),
            filter_body(CHART_PRODUCED),
            request=request,
            user={"id": "another-user"},
            metadata={"session_id": "browser", "user": {"id": _USER}},
            event_call=rpc,
            event_emitter=emit,
        )
    assert lookups == [("owned", "another-user"), ("missing", "another-user")]
    assert_filter_text(result, "Figure verification failed, no image produced")
    assert calls == []
    assert not any(event.get("type") == "files" for event in events)


def test_f3_new_store_bytes_rederives_a_refusal_despite_a_prior_tool_pass(tmp_path: Path) -> None:
    """F3: a tool pass is not authority; the filter fetches the file again and re-verifies it."""
    good = _sales_bytes()
    bad = good.replace(b",US,", b",NA,", 1)
    assert bad != good
    program = _sales_program()
    assert isinstance(
        verify_python_source(
            program,
            declared_target=DatasetTarget("/mnt/uploads/sales.csv", good),
        ),
        Verified,
    )
    assert isinstance(
        verify_python_source(
            program,
            declared_target=DatasetTarget("/mnt/uploads/sales.csv", bad),
        ),
        Refused,
    )
    request = filter_request()
    with fake_open_webui([_file("sales-id", content=good)], tmp_path):
        assert (
            _tool_call(
                program, request=request, metadata=_metadata("sales-id", request_text="plot totals")
            )
            == CHART_PRODUCED
        )
    requests: list[dict[str, object]] = []

    async def rpc(payload: dict[str, object]) -> object:
        requests.append(payload)
        error = "a stale pass reached the sandbox"
        raise AssertionError(error)

    with fake_open_webui([_file("sales-id", content=bad)], tmp_path) as lookups:
        result = invoke_filter(
            load_filter_module(),
            filter_body(CHART_PRODUCED),
            request=request,
            user={"id": _USER},
            metadata={"session_id": "browser"},
            event_call=rpc,
        )
    assert lookups == [("sales-id", _USER)]
    assert_filter_text(result, "Figure verification failed, no image produced")
    assert requests == []
