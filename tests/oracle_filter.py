# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Independent publication model: backend receipt, owned targets, sandbox result."""

from __future__ import annotations

import base64
import binascii
import importlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal, cast

from filter_checks_support import embed_event
from oracle_observe import oracle_matches, oracle_parse
from oracle_paste_in_tool import ToolContext, oracle_draw_figure
from paste_in_support import StoredFile
from verifier.pysrc import DatasetTarget, DeclaredTarget, Refused, Verified, verify_python_source
from verifier.pysrc.verify import Verdict
from webui.paste_in.verdicts import CHART_PRODUCED

PASS_TEXT = "Figure verification passed"  # noqa: S105 - fixed product verdict, not a credential
FAIL_TEXT = "Figure verification failed, no image produced"
_UPLOAD_ROOT = "/mnt/uploads/"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_DATA_URI = re.compile(r"data:[^\s\"'<>]+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ReceiptValue:
    """The three fields the backend request records, without a verdict or file bytes."""

    program: str
    file_ids: tuple[str, ...]
    request_text: str | None


@dataclass(frozen=True, slots=True)
class FileRow:
    file_id: str
    owner: str
    filename: str
    content: bytes


@dataclass(frozen=True, slots=True)
class RpcOutcome:
    kind: Literal["returns", "raises", "timeout", "absent"]
    value: object = None


@dataclass(frozen=True, slots=True)
class Scenario:
    receipt: object
    user_id: str | None
    stored: tuple[FileRow, ...]
    assistant: dict[str, object]
    metadata: dict[str, object] | None
    rpc: RpcOutcome
    request_present: bool = True
    body_fields: dict[str, object] = field(default_factory=dict)
    emitter_present: bool = True
    publish_raises: bool = False


@dataclass(frozen=True, slots=True)
class RpcFacts:
    count: int
    files: tuple[tuple[str, str], ...] = ()
    program: str | None = None
    session_id: object = None
    valid_uuid4: bool = True
    code_without_literal: bool = True


@dataclass(frozen=True, slots=True)
class Expected:
    content: str
    output: tuple[dict[str, object], ...]
    files_events: tuple[dict[str, object], ...]
    rpc: RpcFacts
    status_events: tuple[dict[str, object], ...]
    embed_events: tuple[dict[str, object], ...]


def _candidate(
    receipt: ReceiptValue, user_id: str, stored: tuple[FileRow, ...]
) -> tuple[Verdict | None, FileRow | None]:
    """Reuse the earlier independent tool oracle for candidate order and continuation."""
    rows = {row.file_id: row for row in stored}
    candidates: list[tuple[DeclaredTarget, Verdict]] = []

    def record(source: str, *, declared_target: DeclaredTarget) -> Verdict:
        verdict = verify_python_source(source, declared_target=declared_target)
        candidates.append((declared_target, verdict))
        return verdict

    context = ToolContext(
        user_id=user_id,
        attachments=tuple({"id": file_id} for file_id in receipt.file_ids),
        stored={
            file_id: StoredFile(row.file_id, row.owner, row.filename, row.content)
            for file_id, row in rows.items()
        },
        user_message=receipt.request_text,
    )
    if oracle_draw_figure(receipt.program, context, verify=record) != CHART_PRODUCED:
        if not candidates:
            return None, None
        # Every candidate ran: the last verdict stands, a target mismatch included (arm row 4).
        _target, refused = candidates[-1]
        assert isinstance(refused, Refused)
        return refused, None
    target, verdict = candidates[-1]
    assert isinstance(verdict, Verified), "independent tool oracle published a refusal"
    if isinstance(target, DatasetTarget):
        for file_id in receipt.file_ids:
            row = rows.get(file_id)
            if (
                row is not None
                and row.owner == user_id
                and target == DatasetTarget(_UPLOAD_ROOT + row.filename, row.content)
            ):
                return verdict, row
        failure = "independent tool oracle returned an unowned target"
        raise AssertionError(failure)
    return verdict, None


def _png_uri(stdout: object) -> str | None:
    if not isinstance(stdout, str):
        return None
    candidates = _DATA_URI.findall(stdout)
    pngs: list[str] = []
    for candidate in candidates:
        prefix, separator, encoded = candidate.partition(",")
        if prefix.lower() != "data:image/png;base64" or not separator:
            return None
        pngs.append(candidate)
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            return None
        if not data.startswith(_PNG_SIGNATURE):
            return None
    return pngs[0] if len(pngs) == 1 else None


def _message_item(text: str) -> dict[str, object]:
    return {
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text}],
    }


def status_event(reason: str, metadata: dict[str, object] | None = None) -> dict[str, object]:
    """M15.1: independent carrier, kana predicate and shape; production provides text ONLY."""
    user_message = (metadata or {}).get("user_message")
    content = user_message.get("content") if isinstance(user_message, dict) else None
    prefixes = ("HIRAGANA LETTER", "KATAKANA LETTER", "HALFWIDTH KATAKANA LETTER")
    japanese = isinstance(content, str) and any(
        unicodedata.name(char, "").startswith(prefixes) for char in content
    )
    texts = cast(
        dict[str, tuple[str, str]], importlib.import_module("webui.paste_in.reasons").REASONS
    )
    sentence = texts[reason][1 if japanese else 0]
    return {"type": "status", "data": {"description": f"{sentence} ({reason})", "done": True}}


def _render_cause(  # noqa: PLR0911 - one return per ordered contract arm
    response: object, verdict: Verified
) -> tuple[str | None, str | None]:
    """M15.1 rows 8-14: derive the first cause independently of the outlet implementation."""
    if isinstance(response, dict) and "error" in response and "stderr" not in response:
        return "browser_no_answer", None
    if not isinstance(response, dict) or "stderr" not in response:
        return "reply_malformed", None
    stderr = response["stderr"]
    if stderr is not None and type(stderr) is not str:
        return "reply_malformed", None
    if type(stderr) is str and stderr:
        loader = "loadPyodide" in stderr and not stderr.startswith(
            "Traceback (most recent call last):"
        )
        return ("sandbox_unavailable" if loader else "sandbox_error"), None
    stdout = response.get("stdout")
    uri = _png_uri(stdout)
    if uri is None:
        return "no_image", None
    observation = oracle_parse(stdout) if isinstance(stdout, str) else None
    if observation is None:
        return "no_observation", None
    if not oracle_matches(verdict, observation):
        return "observation_mismatch", None
    return None, uri


def oracle_outlet(scenario: Scenario) -> Expected:  # noqa: PLR0911 - ordered contract arms
    """Model F2-F6 + M15.1 causes; message/model bytes never decide publication or reason."""
    rpc = RpcFacts(0)

    def failed(reason: str, files: tuple[dict[str, object], ...] = ()) -> Expected:
        statuses = (status_event(reason, scenario.metadata),) if scenario.emitter_present else ()
        embeds = (embed_event(reason, scenario.metadata),) if scenario.emitter_present else ()
        return Expected(FAIL_TEXT, (_message_item(FAIL_TEXT),), files, rpc, statuses, embeds)

    receipt = scenario.receipt
    if not scenario.request_present or not isinstance(receipt, ReceiptValue):
        return failed("no_tool_call")
    if not isinstance(scenario.user_id, str):
        return failed("no_user")
    verdict, consumed = _candidate(receipt, scenario.user_id, scenario.stored)
    if verdict is None:
        return failed("no_target")
    if isinstance(verdict, Refused):
        return failed(verdict.code)
    if (
        scenario.rpc.kind == "absent"
        or not scenario.emitter_present
        or scenario.metadata is None
        or "session_id" not in scenario.metadata
    ):
        return failed("no_browser")
    files = ((consumed.file_id, consumed.filename),) if consumed is not None else ()
    rpc = RpcFacts(1, files, receipt.program, scenario.metadata["session_id"])
    if scenario.rpc.kind == "timeout":
        return failed("browser_timeout")
    if scenario.rpc.kind == "raises":
        return failed("browser_error")
    cause, uri = _render_cause(scenario.rpc.value, verdict)
    if cause is not None:
        return failed(cause)
    assert uri is not None
    events: tuple[dict[str, object], ...] = (
        {"type": "files", "data": {"files": [{"type": "image", "url": uri}]}},
    )
    if scenario.publish_raises:
        return failed("publish_failed", events)
    text = PASS_TEXT + "\n\n" + verdict.certificate.interpretation
    return Expected(
        text, (_message_item(text),), events, rpc, (), (embed_event(None, scenario.metadata),)
    )
