# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The only outlet that can publish a verified figure in Open WebUI.

The model's reply and tool-result prose never grant permission. A tool call leaves a tagged record
in backend request state; this outlet refetches the user's files and runs the same verifier over
that record. The browser sandbox is trusted to render a passing program, not to admit it.
"""

import asyncio
import base64
import binascii
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Final

from verifier.pysrc.verify import Verified
from webui.paste_in.owui_files import owned_files
from webui.paste_in.receipt import read_receipt
from webui.paste_in.selection import first_verdict

PASS_TEXT: Final = "Figure verification passed"  # noqa: S105 - a verdict, not a credential
FAIL_TEXT: Final = "Figure verification failed, no image produced"
RPC_TIMEOUT_SECONDS: Final = 60
_PNG_PREFIX = "data:image/png;base64,"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_URI = re.compile(r"data:image/png;base64,[A-Za-z0-9+/]+={0,2}")
_DATA_PREFIX = re.compile(r"(?<!\w)data:")

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
                "_shown = False",
                "def _show(*_args, **_kwargs):",
                "    global _shown",
                "    if _shown:",
                "        return",
                "    _shown = True",
                "    _png = _io.BytesIO()",
                "    _plt.gcf().savefig(_png, format='png')",
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


class Filter:
    """The global active outlet; all paths publish a verdict rather than model narration."""

    async def outlet(  # noqa: PLR0913, PLR0911 - fixed OWUI hook; every refusal returns a verdict
        self,
        body: dict[str, object],
        __user__: dict[str, object] | None = None,
        __request__: object | None = None,
        __event_call__: Callable[[dict[str, object]], Awaitable[object]] | None = None,
        __event_emitter__: Callable[[dict[str, object]], Awaitable[object]] | None = None,
        __metadata__: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Re-derive, render once, publish only when verification and rendering both succeed."""
        receipt = read_receipt(__request__)
        user_id = (__user__ or {}).get("id")
        if receipt is None or not isinstance(user_id, str):
            return _rewrite(body, FAIL_TEXT)

        attachments = await owned_files(receipt.file_ids, user_id)
        verdict, consumed = first_verdict(receipt.program, attachments, receipt.request_text)
        if not isinstance(verdict, Verified):
            return _rewrite(body, FAIL_TEXT)

        if __event_call__ is None or __event_emitter__ is None or __metadata__ is None:
            return _rewrite(body, FAIL_TEXT)
        if "session_id" not in __metadata__:
            return _rewrite(body, FAIL_TEXT)
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
        except Exception:
            return _rewrite(body, FAIL_TEXT)
        if not isinstance(response, dict) or "stderr" not in response:
            return _rewrite(body, FAIL_TEXT)
        stderr = response["stderr"]
        # OWUI reports a clean sandbox run with null stderr.
        if stderr is not None and (type(stderr) is not str or stderr != ""):
            return _rewrite(body, FAIL_TEXT)
        uri = _png_uri(response.get("stdout"))
        if uri is None:
            return _rewrite(body, FAIL_TEXT)
        try:
            await __event_emitter__(
                {"type": "files", "data": {"files": [{"type": "image", "url": uri}]}}
            )
        except Exception:
            return _rewrite(body, FAIL_TEXT)
        return _rewrite(body, f"{PASS_TEXT}\n\n{verdict.certificate.interpretation}")
