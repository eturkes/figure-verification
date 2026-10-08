# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M18.2 E6/E7/E9: receipt evidence is threaded without changing the outlet verdict."""

from __future__ import annotations

import asyncio
import importlib
import logging
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import replace
from types import ModuleType
from typing import cast

import pytest

from observe_support import formula_verdict
from paste_in_support import assert_filter_text, load_filter_module
from test_paste_in_checks import _Document, _one
from test_paste_in_checks_detail_support import (
    URLS,
    EvidenceView,
    api,
    evidence,
    listing,
    rows,
)
from test_paste_in_filter_checks import (
    _EXCEPTION_CASES,
    _assert_events,
    _assert_result,
    _case,
    _Harness,
)
from test_paste_in_filter_reasons import (
    _CASES,
    _FAIL,
    _LOGGER,
    _Case,
    _exercise,
)
from verifier.pysrc import Refused
from verifier.pysrc.spec import Anchoring
from webui.paste_in.reasons import Reason


@pytest.fixture(autouse=True)
def _restore_filter_binding() -> Iterator[None]:
    """A missing new API can fail during spy setup; always release the imported spy alias."""
    module = load_filter_module()
    yield
    importlib.reload(module)


def _held_evidence(program: str | None) -> EvidenceView:
    return evidence(program, ((1, 0, 1, 6),), (("mark", (2, 0, 2, 3)),))


def _patch_verdict(
    monkeypatch: pytest.MonkeyPatch, module: object, *, refused: bool
) -> EvidenceView:
    expected = _held_evidence(None)
    verdict = (
        cast(Callable[..., Refused], Refused)(
            "call_target_not_admitted", at=expected.at, trace=expected.trace
        )
        if refused
        else cast(Callable[..., object], replace)(formula_verdict(), trace=expected.trace)
    )
    monkeypatch.setattr(module, "first_verdict", lambda *_args: (verdict, None))
    return expected


def _patch_pass_trace(monkeypatch: pytest.MonkeyPatch, module: ModuleType) -> EvidenceView:
    """The real verdict, so the PASS reply stays the harness's; only its trace is planted."""
    expected = _held_evidence(None)
    original = cast(Callable[..., tuple[object, object]], module.first_verdict)

    def verdict(*args: object) -> tuple[object, object]:
        found, consumed = original(*args)
        return cast(Callable[..., object], replace)(found, trace=expected.trace), consumed

    monkeypatch.setattr(module, "first_verdict", verdict)
    return expected


@pytest.mark.parametrize("case", (*_CASES, _Case("pass", "", 1)), ids=lambda case: case.name)
@pytest.mark.parametrize("japanese", [False, True], ids=["en", "ja"])
def test_e7_each_outlet_arm_passes_the_evidence_it_holds(
    case: _Case,
    monkeypatch: pytest.MonkeyPatch,
    *,
    japanese: bool,
) -> None:
    """Every exit arm; fake positions at first_verdict, not a co-derived verifier expectation."""
    module = load_filter_module()
    renderer = importlib.import_module("webui.paste_in.checks")
    real = api().breakdown_html
    observed: list[tuple[Reason | None, bool, EvidenceView]] = []

    def spy(
        reason: Reason | None, *, japanese: bool, anchoring: Anchoring, evidence: EvidenceView
    ) -> str:
        observed.append((reason, japanese, evidence))
        return real(reason, japanese=japanese, anchoring=anchoring, evidence=evidence)

    with monkeypatch.context() as patch:
        patch.setattr(renderer, "breakdown_html", spy)
        importlib.reload(module)
        refused = case.name.startswith("04-")
        held = (
            _patch_verdict(patch, module, refused=refused)
            if case.name.startswith("04-")
            or case.rpc_count
            or case.reason == "no_browser"
            or case.name == "pass"
            else None
        )
        if refused:
            case = replace(case, reason="call_target_not_admitted")
        case = replace(
            case,
            metadata={
                **(case.metadata or {}),
                "user_message": {"content": "あ" if japanese else "English"},
            },
        )
        if case.rpc == "timeout":
            patch.setattr(module, "RPC_TIMEOUT_SECONDS", 0.001)
        try:
            result, calls, events, _completed = _exercise(case, module)
        finally:
            patch.undo()
            importlib.reload(module)
    assert len(calls) == case.rpc_count
    if case.name == "pass":
        assert "Figure verification passed" in str(result)
    else:
        assert_filter_text(result, _FAIL)
    if not case.emitter:
        assert observed == []
        return
    assert len(observed) == 1
    reason, language, sent = observed[0]
    assert reason == (None if case.name == "pass" else case.reason)
    assert language is japanese
    assert sent.program == (case.program if case.receipt else None)
    assert sent.at == (held.at if refused and held is not None else ())
    assert sent.trace == (held.trace if held is not None else ())
    if held is not None:
        assert sent.trace is held.trace
        if refused:
            assert sent.at is held.at
    embed = next(event for event in events if event["type"] == "embeds")
    document = cast(list[str], cast(dict[str, object], embed["data"])["embeds"])[0]
    for check, row in rows(document).items():
        assert _one(row.nodes(tag="a")).attrs["href"] == URLS[int(japanese)] + "#check-" + check


@pytest.mark.parametrize("japanese", [False, True], ids=["en", "ja"])
def test_e6_program_bytes_are_escaped_and_confined_to_source_spans(*, japanese: bool) -> None:
    program = (
        '# PROGRAM_SENTINEL <b title="x-data">Chart.(\'&\')</b>\npath = "/mnt/uploads/chart.csv"'
    )
    source = api().breakdown_html(
        "source_not_parsable",
        japanese=japanese,
        anchoring="strict",
        evidence=evidence(program, ((1, 0, 1, 7),)),
    )
    root = _Document(source).root
    assert "PROGRAM_SENTINEL" in root.text()
    assert "PROGRAM_SENTINEL" not in root.text(excluding="src")
    assert "/mnt/uploads/chart.csv" not in root.text(excluding="src")
    assert not root.nodes(tag="b")
    assert "x-data" not in source and "Chart." not in source
    assert "&lt;b" in source and "&quot;" in source and "&amp;" in source
    assert "&#45;" in source and "&#46;" in source and "&#40;" in source
    assert listing(rows(source)["readable"])[0][2] == program.split("\n", maxsplit=1)[0]
    for row in rows(source).values():
        for src in row.nodes(cls="src"):
            assert any(src in code.nodes(cls="src") for code in row.nodes(cls="code"))


@pytest.mark.parametrize("name", _EXCEPTION_CASES)
@pytest.mark.parametrize(
    "fault", ["renderer", "status-call", "status-await", "embeds-call", "embeds-await"]
)
def test_e9_diagnostics_stay_total_with_evidence(
    name: str,
    fault: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    module = load_filter_module()
    renderer = importlib.import_module("webui.paste_in.checks")
    real = api().breakdown_html
    seen: list[EvidenceView] = []

    def render(
        reason: Reason | None, *, japanese: bool, anchoring: Anchoring, evidence: EvidenceView
    ) -> str:
        seen.append(evidence)
        if fault == "renderer":
            message = "renderer-fault"
            raise ValueError(message)
        return real(reason, japanese=japanese, anchoring=anchoring, evidence=evidence)

    with monkeypatch.context() as patch:
        patch.setattr(renderer, "breakdown_html", render)
        importlib.reload(module)
        if name == "01-no-receipt":
            held = None
        elif name == "pass":
            held = _patch_pass_trace(patch, module)
        else:
            held = _patch_verdict(patch, module, refused=name == "04-call-refusal")
        harness = _Harness(_case(name), module)

        async def complete(event: dict[str, object]) -> None:
            if fault == str(event["type"]) + "-await":
                message = "emit-await-fault"
                raise ValueError(message)

        def emit(event: dict[str, object]) -> Awaitable[object]:
            if fault == str(event["type"]) + "-call":
                message = "emit-call-fault"
                raise ValueError(message)
            return complete(event)

        try:
            result = asyncio.run(harness.run(emit))
        finally:
            patch.undo()
            importlib.reload(module)
    _assert_result(harness.case, result, caplog)
    _assert_events(harness.case, harness.events, embed=fault != "renderer")
    assert len(harness.calls) == harness.case.rpc_count
    assert len(seen) == 1
    assert seen[0].program == (None if name == "01-no-receipt" else harness.case.program)
    assert seen[0].trace == (() if held is None else held.trace)
    assert seen[0].at == (held.at if held is not None and name == "04-call-refusal" else ())
