# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The only outlet that can publish a verified figure in Open WebUI.

The model's reply and tool-result prose never grant permission. A tool call leaves a tagged record
in backend request state; this outlet refetches the user's files and runs the same verifier over
that record. The browser sandbox is trusted to render a passing program, not to admit it.
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
from typing import Final

from verifier.pysrc.budget import WorkBudget, WorkBudgetExceededError
from verifier.pysrc.csvread import _read_csv
from verifier.pysrc.errors import PysrcRefusalError
from verifier.pysrc.limits import DEFAULT_LIMITS
from verifier.pysrc.verify import Refused, Verified
from webui.paste_in.capture_template import CAPTURE_TEMPLATE
from webui.paste_in.checks import breakdown_html
from webui.paste_in.observe import (
    OBSERVATION_TAG,
    OBSERVER_SOURCE,
    observation_matches,
    parse_observation,
)
from webui.paste_in.owui_files import UPLOAD_DIR, owned_files, uploaded_files
from webui.paste_in.reasons import REASONS, Reason
from webui.paste_in.receipt import read_receipt
from webui.paste_in.selection import first_verdict

type _Emit = Callable[[dict[str, object]], Awaitable[object]]

PASS_TEXT: Final = "Figure verification passed"  # noqa: S105 - a verdict, not a credential
FAIL_TEXT: Final = "Figure verification failed, no image produced"
RPC_TIMEOUT_SECONDS: Final = 60
STATUS_TIMEOUT_SECONDS: Final = 5
_PNG_PREFIX = "data:image/png;base64,"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_URI = re.compile(r"data:image/png;base64,[A-Za-z0-9+/]+={0,2}")
_DATA_PREFIX = re.compile(r"(?<!\w)data:")
_TRACEBACK = "Traceback (most recent call last):"
# A kana LETTER alone marks a Japanese request (user ruling): kanji are shared with Chinese, and
# marks such as `・` or `ー` occur beside kanji alone.
_KANA_LETTERS = ("HIRAGANA LETTER", "KATAKANA LETTER", "HALFWIDTH KATAKANA LETTER")
_LOGGER = logging.getLogger(__name__)

# Admin-facing identity; the function source itself comes from the generated paste-in artifact.
FILTER_ID: Final = "figure_verification_filter"
FILTER_NAME: Final = "Figure Verification Filter"
FILTER_DESCRIPTION: Final = "Shows a chart only after the verifier checks its program and data."


def wrapper_code(program: str) -> str:
    """Run the submitted program bytes inside the browser, with one trusted PNG output hook.

    OWUI detects packages only from literal imports in the RPC source, missing encoded programs.
    Load the stack quietly through Pyodide; select Agg as OWUI's own patch prelude does, without
    triggering that broken prelude. Split the plotting name and any matching base64 RPC payload.
    """
    encoded = base64.b64encode(program.encode("utf-8")).decode("ascii")
    parts = encoded.split("matplotlib")
    payload = " + 'mat' + 'plotlib' + ".join(repr(part) for part in parts)
    return (
        "\n".join(
            (
                "import pyodide_js as _pyodide",
                "await _pyodide.loadPackage(['numpy', 'pandas', 'mat' + 'plotlib'],",
                "                              messageCallback=lambda _message: None)",
                "import base64 as _b64",
                "import io as _io",
                "import importlib as _imports",
                "import os as _os",
                "_os.environ['MPLBACKEND'] = 'AGG'",
                "_plt = _imports.import_module('mat' + 'plotlib.pyplot')",
                "plt = _plt",
                *OBSERVER_SOURCE.splitlines(),
                "_shown = False",
                "def _show(*_args, **_kwargs):",
                "    global _shown",
                "    if _shown:",
                "        return",
                "    _shown = True",
                "    _fig = _plt.gcf()",
                "    _fig.canvas.draw()",
                f"    print({OBSERVATION_TAG!r} + _figure_verification_observe())",
                "    _png = _io.BytesIO()",
                "    _fig.savefig(_png, format='png')",
                "    print('data:image/png;base64,' +",
                "          _b64.b64encode(_png.getvalue()).decode('ascii'))",
                "    _plt.close('all')",
                "_plt.show = _show",
                f"_source = _b64.b64decode({payload})",
                "exec(compile(_source, '<verified-figure>', 'exec'), {'__name__': '__main__'})",
                "if not _shown:",
                "    _show()",
            )
        )
        + "\n"
    )


def _png_uri(stdout: object) -> str | None:
    """Accept exactly one complete PNG data-URI line with a valid base64 PNG signature."""
    if not isinstance(stdout, str):
        return None
    lines = [line.strip() for line in stdout.splitlines() if _DATA_PREFIX.search(line)]
    if len(lines) != 1 or _PNG_URI.fullmatch(lines[0]) is None:
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
    return isinstance(content, str) and any(
        unicodedata.name(character, "").startswith(_KANA_LETTERS) for character in content
    )


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
    emit: _Emit | None, reason: Reason | None, metadata: dict[str, object] | None
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
        document = breakdown_html(reason, japanese=japanese)
    except Exception:
        return
    # `replace` keeps exactly this document on the message; Open WebUI otherwise appends.
    embed: dict[str, object] = {"type": "embeds", "data": {"embeds": [document], "replace": True}}
    await _emit_bounded(emit, embed, deadline)


async def _fail(
    body: dict[str, object],
    reason: Reason,
    metadata: dict[str, object] | None,
    emit: _Emit | None,
) -> dict[str, object]:
    """Block the figure: one log record for the admin, the diagnostics for the user.

    Neither surface carries sandbox output, program bytes or request text, because an error
    message can quote the user's clinical data.
    """
    with contextlib.suppress(Exception):
        _LOGGER.info("figure verification failed reason=%s", reason)
    await _diagnose(emit, reason, metadata)
    return _rewrite(body, FAIL_TEXT)


class Filter:
    """The global active filter; the inlet carries context, and the outlet authors the verdict."""

    async def inlet(
        self,
        body: dict[str, object],
        __user__: dict[str, object] | None = None,
        __metadata__: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Render the capture prompt over an owned CSV without changing the user's evidence."""
        user_id = (__user__ or {}).get("id")
        messages = body.get("messages")
        if not isinstance(user_id, str) or not isinstance(messages, list):
            return body
        attachments = await uploaded_files(__metadata__, user_id)
        if not attachments:
            return body
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            task = message.get("content")
            if not isinstance(task, str):
                return body
            try:
                header, _rows = _read_csv(
                    attachments[-1].content,
                    DEFAULT_LIMITS,
                    WorkBudget(DEFAULT_LIMITS.max_work),
                )
            except (PysrcRefusalError, WorkBudgetExceededError):
                return body
            rendered = CAPTURE_TEMPLATE.format(
                task=task,
                dataset=attachments[-1].path.removeprefix(UPLOAD_DIR),
                columns=", ".join(header),
            )
            updated = list(messages)
            updated[index] = {**message, "content": rendered}
            return {**body, "messages": updated}
        return body

    async def outlet(  # noqa: PLR0911, PLR0912, PLR0913 - fixed OWUI hook; one guard per FAIL arm
        self,
        body: dict[str, object],
        __user__: dict[str, object] | None = None,
        __request__: object | None = None,
        __event_call__: _Emit | None = None,
        __event_emitter__: _Emit | None = None,
        __metadata__: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Re-derive, render once, publish only when verification and rendering both succeed."""

        async def fail(reason: Reason) -> dict[str, object]:
            return await _fail(body, reason, __metadata__, __event_emitter__)

        receipt = read_receipt(__request__)
        user_id = (__user__ or {}).get("id")
        if receipt is None:
            return await fail("no_tool_call")
        if not isinstance(user_id, str):
            return await fail("no_user")

        attachments = await owned_files(receipt.file_ids, user_id)
        verdict, consumed = first_verdict(receipt.program, attachments, receipt.request_text)
        if isinstance(verdict, Refused):
            return await fail(verdict.code)
        if not isinstance(verdict, Verified):
            return await fail("no_target")

        if (
            __event_call__ is None
            or __event_emitter__ is None
            or not isinstance(__metadata__, dict)
            or "session_id" not in __metadata__
        ):
            return await fail("no_browser")
        payload: dict[str, object] = {
            "type": "execute:python",
            "data": {
                "id": str(uuid.uuid4()),
                "code": wrapper_code(receipt.program),
                "session_id": __metadata__["session_id"],
                "files": (
                    [{"id": consumed.file_id, "filename": consumed.path.rsplit("/", 1)[-1]}]
                    if consumed is not None
                    else []
                ),
            },
        }
        try:
            response = await asyncio.wait_for(__event_call__(payload), timeout=RPC_TIMEOUT_SECONDS)
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
            return await fail("no_image")
        uri = _png_uri(stdout)
        if uri is None:
            return await fail("no_image")
        observed = parse_observation(stdout)
        if observed is None:
            return await fail("no_observation")
        if not observation_matches(verdict, observed):
            return await fail("observation_mismatch")
        try:
            await __event_emitter__(
                {"type": "files", "data": {"files": [{"type": "image", "url": uri}]}}
            )
        except Exception:
            return await fail("publish_failed")
        await _diagnose(__event_emitter__, None, __metadata__)
        return _rewrite(body, f"{PASS_TEXT}\n\n{verdict.certificate.interpretation}")
