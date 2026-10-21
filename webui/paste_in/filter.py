# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The only outlet that can publish a figure in Open WebUI.

The model's reply and tool-result prose never grant permission. A tool call leaves a tagged record
in backend request state; this outlet refetches the user's files, runs the recorded program
unchanged in the user's browser sandbox with the trusted reader around it, and judges the finished
figure the reader describes. The browser, the sandbox and matplotlib are trusted to draw and to
report; every decision is the judge's.
"""

import asyncio
import base64
import binascii
import contextlib
import logging
import re
import unicodedata
import uuid
from collections.abc import Awaitable, Callable
from typing import Final, TypeAlias

from pydantic import BaseModel, Field

from verifier.figure.anchoring import Anchoring
from verifier.figure.description import MAX_BYTES, TAG, Description, parse_description
from verifier.figure.inert import prose
from verifier.figure.judge import Passed, Sources, judge
from verifier.figure.reader import MAX_PNG_CHARACTERS
from verifier.pysrc.budget import WorkBudget, WorkBudgetExceededError
from verifier.pysrc.csvread import _read_csv
from verifier.pysrc.errors import PysrcRefusalError
from verifier.pysrc.limits import DEFAULT_LIMITS
from webui.paste_in.checks import CHECK_OF, Evidence, breakdown_html
from webui.paste_in.excerpts import excerpts
from webui.paste_in.fonts import cut_for
from webui.paste_in.owui_files import (
    UPLOAD_DIR,
    UploadedFile,
    cjk_font,
    last_owned_file,
    owned_files,
    sandbox_isolated,
)
from webui.paste_in.reasons import REASONS, Reason
from webui.paste_in.receipt import read_receipt
from webui.paste_in.sandbox import wrapper_code
from webui.paste_in.templates import (
    NOTE_LANGUAGES,
    NOTE_REQUEST,
    PRODUCTION_TEMPLATES,
    Templates,
)

_Emit: TypeAlias = Callable[[dict[str, object]], Awaitable[object]]

PASS_TEXT: Final = "Figure verification passed"  # noqa: S105 - a verdict, not a credential
FAIL_TEXT: Final = "Figure verification failed, no image produced"
# Q78 (user): the speaker of the line under the verdict, EN + JA, in bold (Q79); no check reads
# the note. Open WebUI's chat CSS draws `strong` at weight 500, which a Japanese font without a
# medium face (Yu Gothic UI, Meiryo) draws regular, and browsers synthesize bold from 600 alone;
# KaTeX's `\textbf` is 700, at `\footnotesize` = the body size (Q80, measured live).
NOTE_LABELS: Final = ("**Model note:**", "$\\footnotesize\\textbf{モデルの注記:}$")
MODEL_NOTE_TITLE: Final = "Model Note"
MODEL_NOTE_DESCRIPTION: Final = (
    "Ask the model to say when the request asks for something that the chart rules do not allow,"
    " and show that statement under the verdict. The verifier does not check the statement."
)
RPC_TIMEOUT_SECONDS: Final = 60
STATUS_TIMEOUT_SECONDS: Final = 5
_PNG_PREFIX = "data:image/png;base64,"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_URI = re.compile(r"data:image/png;base64,[A-Za-z0-9+/]+={0,2}")
_DATA_PREFIX = re.compile(r"(?<!\w)data:")
_TRACEBACK = "Traceback (most recent call last):"
# The longest stdout the reader writes (`reader.py::run`): the tagged description within the
# decoder's cap, then one PNG line within the reader's, each ending in a line break. Open WebUI
# 0.12.3 takes a 16 MiB browser frame, and 16 MiB of line breaks took 1.5 s to decode (M22.1 F4).
_MAX_REPLY = len(TAG) + MAX_BYTES + 1 + MAX_PNG_CHARACTERS + 1
# A kana LETTER alone marks a Japanese request (user ruling): kanji are shared with Chinese, and
# marks such as `・` or `ー` occur beside kanji alone. The letters form one character class, since
# the test runs on Open WebUI's event loop over a message of any length, and a name lookup per
# character took 0.17 s per MB (CPython 3.11, M22.1 F1); kana letters lie in these blocks alone.
_KANA_LETTERS = ("HIRAGANA LETTER", "KATAKANA LETTER", "HALFWIDTH KATAKANA LETTER")
_KANA_BLOCKS = ((0x3040, 0x3100), (0x31F0, 0x3200), (0xFF65, 0xFFA0), (0x1AFF0, 0x1B170))
_KANA_LETTER = re.compile(
    "["
    + "".join(
        chr(code)
        for start, end in _KANA_BLOCKS
        for code in range(start, end)
        if unicodedata.name(chr(code), "").startswith(_KANA_LETTERS)
    )
    + "]"
)
_LOGGER = logging.getLogger(__name__)

# Admin-facing identity; the function source itself comes from the generated paste-in artifact.
FILTER_ID: Final = "figure_verification_filter"
FILTER_NAME: Final = "Figure Verification Filter"
FILTER_DESCRIPTION: Final = "Shows a chart only after the verifier checks the finished figure."


def _needs_font(program: str, files: tuple[UploadedFile, ...]) -> bool:
    """Whether the figure can draw text outside ASCII, which the sandbox fonts may lack: the
    program or an attached file holds a non-ASCII character (over-inclusion costs bytes alone)."""
    return not program.isascii() or any(not file.content.isascii() for file in files)


async def _font(program: str, files: tuple[UploadedFile, ...], configured: str) -> bytes | None:
    """The server's Japanese font cut to what the figure can draw, when it can draw text outside
    ASCII. The cut parses a font of several MB, so it runs off the event loop."""
    if not _needs_font(program, files):
        return None
    font = await cjk_font(configured)
    if font is None:
        return None
    return await asyncio.to_thread(cut_for, font, program, [file.content for file in files])


def _png_uri(stdout: str) -> str | None:
    """Accept exactly one complete PNG data-URI line, outside the description line, carrying a
    valid base64 PNG signature."""
    lines = [
        line.strip()
        for line in stdout.splitlines()
        if not line.startswith(TAG) and _DATA_PREFIX.search(line)
    ]
    if (
        len(lines) != 1
        or len(lines[0]) > MAX_PNG_CHARACTERS
        or _PNG_URI.fullmatch(lines[0]) is None
    ):
        return None
    try:
        image = base64.b64decode(lines[0][len(_PNG_PREFIX) :], validate=True)
    except (binascii.Error, ValueError):
        return None
    return lines[0] if image.startswith(_PNG_SIGNATURE) else None


def _rewrite(body: dict[str, object], text: str) -> dict[str, object]:
    """Replace every user-visible narration of the final assistant message, never earlier ones."""
    messages = body.get("messages")
    if not isinstance(messages, list):
        messages = []
        body["messages"] = messages
    assistant = next(
        (
            message
            for message in reversed(messages)
            if isinstance(message, dict) and message.get("role") == "assistant"
        ),
        None,
    )
    if assistant is None:
        assistant = {"role": "assistant"}
        messages.append(assistant)
    assistant["content"] = text
    # OWUI persists output only when a new value differs from its pre-outlet snapshot.
    assistant["output"] = [
        {
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text}],
        }
    ]
    return body


def _reply_fault(response: dict[object, object]) -> Reason | None:
    """Why a sandbox reply cannot carry a clean run, or `None` when its stderr is empty.

    OWUI's own caller answers `{'error': ...}` for a closed or timed-out tab, and reports a clean
    run with null stderr. A content blocker that stops `pyodide.js` leaves `loadPyodide` unbound,
    and OWUI's sandbox host replies with the engine's ReferenceError, which names it; only that
    measured shape earns the ad-blocker fix. The host reports other faults in the same bare shape
    (an upload throwing outside the program's `try`), so the rest stay generic.
    """
    if "stderr" not in response:
        return "browser_no_answer" if "error" in response else "reply_malformed"
    stderr = response["stderr"]
    if stderr is None or (type(stderr) is str and stderr == ""):
        return None
    if type(stderr) is not str:
        return "reply_malformed"
    if "loadPyodide" in stderr and not stderr.startswith(_TRACEBACK):
        return "sandbox_unavailable"
    return "sandbox_error"


def _japanese(metadata: object) -> bool:
    """The user's own request text decides, on every arm; the receipt exists on only some.

    Total, because it runs on diagnostic paths that must never cost the verdict.
    """
    message = metadata.get("user_message") if isinstance(metadata, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    return isinstance(content, str) and _KANA_LETTER.search(content) is not None


def _note_line(note: str, metadata: object) -> str:
    """The model's own statement of what the chart rules overrode, after its bold label as escaped
    plain text (Q79: Open WebUI renders the reply as markdown), or nothing for a blank note.

    Display alone: it is built after the verdict and read by no check. Total, because a failed
    reply builds it, and a raise there would fail open.
    """
    try:
        shown = note.strip()
        return f"\n\n{NOTE_LABELS[_japanese(metadata)]} {prose(shown)}" if shown else ""
    except Exception:
        return ""


async def _emit_bounded(emit: _Emit, event: dict[str, object], deadline: float) -> None:
    """Deliver one diagnostic event unless `deadline` (event-loop time) passes first.

    The emit runs as its own task and a late one is cancelled but never awaited: `wait_for` would
    wait for the emitter's cancellation cleanup, so a slow cleanup would hold back the verdict. An
    emit not started by the deadline is skipped, and the wait gets only the time left once the
    emitter has returned its awaitable, since that call can itself block. An `Exception` from the
    emitter is dropped; a cancellation propagates.
    """
    loop = asyncio.get_running_loop()
    if loop.time() >= deadline:
        return
    try:
        task = asyncio.ensure_future(emit(event))
    except Exception:  # an emitter that raises before it returns an awaitable
        return
    try:
        done, _pending = await asyncio.wait({task}, timeout=max(0.0, deadline - loop.time()))
    except asyncio.CancelledError:
        task.cancel()
        raise
    if not done:
        task.cancel()
        # Retrieve the eventual outcome, so asyncio never reports it as unhandled.
        task.add_done_callback(lambda late: late.cancelled() or late.exception())
        return
    error = task.exception()  # raises CancelledError when the emitter cancelled itself
    if error is not None and not isinstance(error, Exception):
        raise error


async def _diagnose(
    emit: _Emit | None,
    reason: Reason | None,
    metadata: dict[str, object] | None,
    anchoring: Anchoring,
    evidence: Evidence,
) -> None:
    """Show the user why a figure failed, then every check it faced (`reason` None = published).

    Open WebUI keeps a status line in `statusHistory` and an embed in `embeds`; its chat flows
    send neither to a model, since a rewritten reply always carries `output`, which is what they
    read. So a refusal code reaches the user without entering model context. Both are diagnosis
    only: together they wait at most `STATUS_TIMEOUT_SECONDS`, and no failure of theirs costs the
    verdict.
    """
    if emit is None:
        return
    deadline = asyncio.get_running_loop().time() + STATUS_TIMEOUT_SECONDS
    japanese = _japanese(metadata)
    if reason is not None:
        english, japanese_text = REASONS[reason]
        text = f"{japanese_text if japanese else english} ({reason})"
        status: dict[str, object] = {"type": "status", "data": {"description": text, "done": True}}
        await _emit_bounded(emit, status, deadline)
    try:
        document = breakdown_html(reason, japanese=japanese, anchoring=anchoring, evidence=evidence)
    except Exception:
        return
    # `replace` keeps exactly this document on the message; Open WebUI otherwise appends.
    embed: dict[str, object] = {"type": "embeds", "data": {"embeds": [document], "replace": True}}
    await _emit_bounded(emit, embed, deadline)


def _evidence(
    program: str | None, description: Description | None, reason: Reason | None, site: int | None
) -> Evidence:
    """The program, the line a failure points at and each check's related lines, for display
    alone: a fault while finding the lines leaves the program and the line, never the verdict."""
    if program is None:
        return Evidence(None, site)
    try:
        lines = excerpts(program, description, None if reason is None else CHECK_OF[reason], site)
    except Exception:
        return Evidence(program, site)
    return Evidence(program, site, lines)


async def _fail(  # noqa: PLR0913 - the reply body plus the five diagnostic inputs + the note
    body: dict[str, object],
    reason: Reason,
    metadata: dict[str, object] | None,
    emit: _Emit | None,
    anchoring: Anchoring,
    *,
    evidence: Evidence,
    note: str = "",
) -> dict[str, object]:
    """Block the figure: one log record for the admin, the diagnostics for the user.

    Neither the log nor the status line carries sandbox output, program bytes or request text,
    because an error message can quote the user's clinical data; the check list quotes the
    program alone, inside the user's own chat.
    """
    with contextlib.suppress(Exception):
        _LOGGER.info("figure verification failed reason=%s", reason)
    await _diagnose(emit, reason, metadata, anchoring, evidence)
    try:
        line = await asyncio.to_thread(_note_line, note, metadata) if note else ""
    except Exception:
        line = ""
    return _rewrite(body, FAIL_TEXT + line)


class Filter:
    """The global active filter; the inlet carries context, and the outlet authors the verdict."""

    # Production = strict request anchoring; the demo's generated filter overrides it (Q37).
    _ANCHORING: Anchoring = "strict"
    # Production's inlet templates carry no format sentence: Kimi calls `draw_figure` (Q40).
    _TEMPLATES: Templates = PRODUCTION_TEMPLATES

    class Valves(BaseModel):
        """The admin's settings for this filter."""

        cjk_font_path: str = Field(
            default="",
            title="Japanese Font Path",
            description=(
                "Path of a Japanese font file (.ttf, .otf or .ttc) on the Open WebUI server."
                " When it is empty, the filter uses the first Japanese font it finds in the"
                " server's font folders."
            ),
        )
        model_note: bool = Field(
            default=True, title=MODEL_NOTE_TITLE, description=MODEL_NOTE_DESCRIPTION
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    async def inlet(
        self,
        body: dict[str, object],
        __user__: dict[str, object] | None = None,
        __metadata__: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Render the prompt template around the last user message, with the last owned CSV's
        path and header when one is attached, without changing the user's evidence."""
        user_id = (__user__ or {}).get("id")
        messages = body.get("messages")
        if not isinstance(user_id, str) or not isinstance(messages, list):
            return body
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            task = message.get("content")
            if not isinstance(task, str):
                return body
            attachment = await last_owned_file(__metadata__, user_id)
            # The header parse reads up to 8 MB: keep Open WebUI's event loop free.
            rendered = await asyncio.to_thread(self._render, task, attachment)
            if self.valves.model_note:
                japanese = _KANA_LETTER.search(task) is not None
                rendered += NOTE_REQUEST.format(language=NOTE_LANGUAGES[japanese])
            updated = list(messages)
            updated[index] = {**message, "content": rendered}
            return {**body, "messages": updated}
        return body

    def _render(self, task: str, attachment: UploadedFile | None) -> str:
        if attachment is None:
            return self._TEMPLATES.no_file.format(task=task)
        try:
            header, _rows = _read_csv(
                attachment.content, DEFAULT_LIMITS, WorkBudget(DEFAULT_LIMITS.max_work)
            )
        except (PysrcRefusalError, WorkBudgetExceededError):
            return self._TEMPLATES.no_file.format(task=task)
        return self._TEMPLATES.file.format(
            task=task,
            dataset=attachment.path.removeprefix(UPLOAD_DIR),
            columns=", ".join(header),
        )

    async def outlet(  # noqa: PLR0911, PLR0912, PLR0913, PLR0917 - OWUI hook; a guard per refusal
        self,
        body: dict[str, object],
        __user__: dict[str, object] | None = None,
        __request__: object | None = None,
        __event_call__: _Emit | None = None,
        __event_emitter__: _Emit | None = None,
        __metadata__: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Run the recorded program in the browser, judge the figure, publish only a pass."""
        program: str | None = None
        description: Description | None = None
        note = ""

        async def fail(reason: Reason, site: int | None = None) -> dict[str, object]:
            # The listing walks the program's syntax tree: 0.26 s near its work budget (CPython
            # 3.11, M22.1 F5).
            evidence = await asyncio.to_thread(_evidence, program, description, reason, site)
            return await _fail(
                body,
                reason,
                __metadata__,
                __event_emitter__,
                self._ANCHORING,
                evidence=evidence,
                note=note,
            )

        try:
            receipt = read_receipt(__request__)
            if receipt is None:
                return await fail("no_tool_call")
            program = receipt.program
            note = receipt.note if self.valves.model_note else ""
            user_id = (__user__ or {}).get("id")
            if not isinstance(user_id, str) or not user_id:
                return await fail("no_user")
            session = __metadata__.get("session_id") if isinstance(__metadata__, dict) else None
            if not isinstance(session, str):
                session = None
            if __event_call__ is None or __event_emitter__ is None or not session:
                return await fail("no_browser")
            if not sandbox_isolated():
                return await fail("sandbox_not_isolated")
            files = await owned_files(receipt.file_ids, user_id)
            font = await _font(receipt.program, files, self.valves.cjk_font_path)
            payload: dict[str, object] = {
                "type": "execute:python",
                "data": {
                    "id": str(uuid.uuid4()),
                    "code": wrapper_code(receipt.program, font),
                    "session_id": session,
                    "files": [
                        {"id": file.file_id, "filename": file.path.removeprefix(UPLOAD_DIR)}
                        for file in files
                    ],
                },
            }
            try:
                response = await asyncio.wait_for(
                    __event_call__(payload), timeout=RPC_TIMEOUT_SECONDS
                )
            except TimeoutError:
                return await fail("browser_timeout")
            except Exception:
                return await fail("browser_error")
            if not isinstance(response, dict):
                return await fail("reply_malformed")
            fault = _reply_fault(response)
            if fault is not None:
                return await fail(fault)
            stdout = response.get("stdout")
            if not isinstance(stdout, str):
                return await fail("no_description")
            if len(stdout) > _MAX_REPLY:
                return await fail("reply_malformed")
            # Decoding reads up to `_MAX_REPLY` characters, and the judge is pure CPU (seconds on a
            # large CSV, two passes): both run off Open WebUI's event loop.
            description = await asyncio.to_thread(parse_description, stdout)
            if description is None:
                return await fail("no_description")
            sources = Sources(
                tuple((file.path.removeprefix(UPLOAD_DIR), file.content) for file in files),
                receipt.request_text,
                self._ANCHORING,
                receipt.aliases,
            )
            verdict = await asyncio.to_thread(judge, description, sources)
            if not isinstance(verdict, Passed):
                return await fail(verdict.reason, verdict.site)
            uri = await asyncio.to_thread(_png_uri, stdout)
            if uri is None:
                return await fail("no_image")
            try:
                await __event_emitter__(
                    {"type": "files", "data": {"files": [{"type": "image", "url": uri}]}}
                )
            except Exception:
                return await fail("publish_failed")
            evidence = await asyncio.to_thread(_evidence, program, description, None, None)
            await _diagnose(__event_emitter__, None, __metadata__, self._ANCHORING, evidence)
            japanese = _japanese(__metadata__)
            interpretation = verdict.interpretation_ja if japanese else verdict.interpretation
            # No length limit (user): an 8 MB note took 2.7 s to render (CPython 3.14).
            note_line = await asyncio.to_thread(_note_line, note, __metadata__) if note else ""
            return _rewrite(body, f"{PASS_TEXT}\n\n{interpretation}{note_line}")
        except Exception:
            # Open WebUI swallows an outlet exception and keeps the model's reply, a forged pass
            # included (`utils/filter.py`, `utils/middleware.py`): any fault fails closed.
            return await fail("verifier_error")
