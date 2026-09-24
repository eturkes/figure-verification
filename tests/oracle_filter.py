# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Independent publication model: backend receipt, owned targets, sandbox result."""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass, field
from typing import Literal

from oracle_paste_in_tool import ToolContext, oracle_draw_figure
from paste_in_support import StoredFile
from verifier.pysrc import DatasetTarget, DeclaredTarget, Verified, verify_python_source
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


def _verified_candidate(
    receipt: ReceiptValue, user_id: str, stored: tuple[FileRow, ...]
) -> tuple[Verified | None, FileRow | None]:
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
        return None, None
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


def oracle_outlet(scenario: Scenario) -> Expected:
    """Model F2-F6 without reading message text, output, metadata files, or tool result."""
    receipt = scenario.receipt
    rpc = RpcFacts(0)
    published: str | None = None
    uri: str | None = None
    if (
        scenario.request_present
        and isinstance(receipt, ReceiptValue)
        and isinstance(scenario.user_id, str)
    ):
        verdict, consumed = _verified_candidate(receipt, scenario.user_id, scenario.stored)
        if verdict is not None and scenario.rpc.kind != "absent":
            files = ((consumed.file_id, consumed.filename),) if consumed is not None else ()
            session = (scenario.metadata or {}).get("session_id")
            rpc = RpcFacts(1, files, receipt.program, session)
            if scenario.rpc.kind == "returns" and isinstance(scenario.rpc.value, dict):
                response = scenario.rpc.value
                if response.get("stderr") == "":
                    uri = _png_uri(response.get("stdout"))
                    if uri is not None:
                        published = PASS_TEXT + "\n\n" + verdict.certificate.interpretation
    text = published if published is not None else FAIL_TEXT
    events: tuple[dict[str, object], ...] = ()
    if uri is not None and published is not None:
        events = ({"type": "files", "data": {"files": [{"type": "image", "url": uri}]}},)
    return Expected(text, (_message_item(text),), events, rpc)
