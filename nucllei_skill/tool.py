# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The only path that can publish a figure through the figure-verification skill on nucllei.

`draw_figure` receives the model's program, runs it unchanged in the caller's sandbox with the
trusted reader around it, judges the finished figure the reader describes, and alone shows the
verdict: on a pass the image, the interpretation and the model's note through `__display__`
(outside the collapsed tool block, never sent to the model); on a block the cause alone.
Its result is the check list (inside the collapsed block, also the model's text) plus a Japanese
fact and `次の手:` for the model. The sandbox, matplotlib and the browser are trusted to draw and to
report; every decision is the judge's.

nucllei loads `Tools` once per resolution, exposes every public non-class callable but the hooks
`available` + `spec_overrides` as a function, and prepends a `Tools` class docstring to the first
function's model-facing description: so `Tools` carries none, and every helper is private.
"""

import asyncio
import base64
import contextlib
import csv
import io
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, Field, field_validator

from nucllei_skill import host, run
from nucllei_skill.checks import CHECK_OF, checklist
from nucllei_skill.reasons import REASONS, Reason
from nucllei_skill.texts import (
    ALIASES_DESCRIPTION,
    FAILED,
    IMAGE_ALT,
    NEXT,
    NOTE_DESCRIPTION,
    NOTE_TITLE,
    PASSED,
    error_kind,
    next_step,
)
from verifier.figure.description import Description, parse_description
from verifier.figure.judge import Passed, Sources, judge
from webui.paste_in.aliases import parse_aliases
from webui.paste_in.checks import Evidence
from webui.paste_in.excerpts import excerpts
from webui.paste_in.reply import FAIL_TEXTS, PASS_TEXTS, is_japanese, note_line, png_uri

if TYPE_CHECKING:
    PythonCode = str
else:
    PythonCode = host.python_code()

_LOGGER = logging.getLogger(__name__)
_PNG_PREFIX = "data:image/png;base64,"
# A spec header read per turn for the attachment list in `draw_figure`'s description.
_HEADER_BYTES = 65_536
# nucllei's own description cut (`utils/tools.py` `tool_description_from_docstring`).
_PARAMS = re.compile(":(param|return)")
# Room for nucllei's own cut marker below its result cap.
_CAP_MARGIN: Final = 512
_NOTE_OFF: Final = "常に空にする。"
_NO_FILE: Final = "\n\n添付ファイルはない。依頼文に書かれた数値とラベルだけを描く。"
_FILES: Final = "\n\nこのターンの添付ファイル (プログラムはこのパスで読む):"


def _user_id(user: object) -> str | None:
    """The caller's id: `__user__` is a dict, a hook's `user` the user model."""
    found = user.get("id") if isinstance(user, Mapping) else getattr(user, "id", None)
    return found if isinstance(found, str) and found else None


def _latest(messages: object) -> str | None:
    """The text of the last `user` entry the model received: the request of a call whose chat is
    not stored (a headless call carries no server notice)."""
    for message in reversed(messages if isinstance(messages, list) else []):
        if isinstance(message, Mapping) and message.get("role") == "user":
            return host.message_text(message.get("content"))
    return None


@dataclass(frozen=True, slots=True)
class _Request:
    """What the user supplied: the request text (Q66), its latest message and the attachments."""

    text: str | None
    latest: str | None
    refs: tuple[tuple[str, str | None], ...]


def _request(  # noqa: PLR0913, PLR0917 - nucllei's reserved arguments, passed through
    chat_id: object,
    message_id: object,
    user_id: str,
    messages: object,
    files: object,
    metadata: object,
) -> _Request:
    """The human side of the caller's stored branch; the request body alone where no branch is
    stored, since an inlet may strip an attachment from the body (llens `large_file_gate`) and a
    server notice is stored as a `user` row (consultant-1 T7, T8)."""
    try:
        stored = host.branch(chat_id, message_id, user_id)
    except Exception:
        stored = None
    if stored is None:
        latest = _latest(messages)
        return _Request(latest, latest, tuple(host.request_refs(files, metadata)))
    return _Request("\n\n".join(stored.texts) or None, stored.latest, stored.refs)


def _owned(refs: Sequence[tuple[str, str | None]], user_id: str) -> tuple[host.Attachment, ...]:
    """The caller's readable attachments, one per jail name: a later file with a name an earlier
    one holds replaces it in the jail, so it replaces it here."""
    found: dict[str, host.Attachment] = {}
    for file_id, name in refs:
        attachment = host.owned_attachment(file_id, name, user_id)
        if attachment is not None:
            found[attachment.name] = attachment
    return tuple(found.values())


def _header(content: bytes) -> list[str] | None:
    """The first CSV record, for the model's guidance alone (the judge reads the whole file)."""
    try:
        text = content.decode("utf-8-sig")
        return next(csv.reader(io.StringIO(text)), None)
    except (UnicodeDecodeError, csv.Error):
        return None


def _evidence(
    program: str, description: Description | None, reason: Reason | None, site: int | None
) -> Evidence:
    """The program, the line a failure points at and each check's related lines, for display
    alone: a fault while finding the lines leaves the program and the line, never the verdict."""
    try:
        failing = None if reason is None else CHECK_OF[reason]
        return Evidence(program, site, excerpts(program, description, failing, site))
    except Exception:
        return Evidence(program, site)


def _show(display: object, text: str) -> bool:
    """Push the verdict outside the collapsed block; whether the push went through (a headless call
    has no display)."""
    if not callable(display):
        return False
    try:
        display(text)
    except Exception:
        return False
    return True


def _result(text: str) -> object:
    """The result nucllei renders as markdown, or the bare text when it cannot wrap it."""
    try:
        return host.rendered_markdown(text)
    except Exception:
        return text


def _bounded(reason: Reason | None, evidence: Evidence, tail: str, *, japanese: bool) -> str:
    """The check list + the model's tail within the server's result cap (nucllei cuts a longer
    result and drops its markdown render; an admin can lower the cap): rows drop their program
    listings first, then the list goes; the cause + the tail stay while the cap can hold them."""
    room = host.result_cap() - _CAP_MARGIN
    for shown in (evidence, Evidence(None, evidence.site)):
        text = f"{checklist(reason, japanese=japanese, evidence=shown)}\n{tail}"
        if len(text) <= room:
            return text
    return tail


class Tools:
    # nucllei reads a class docstring here as a model-facing note on every function: none.

    class Valves(BaseModel):
        """The admin's settings for this tool."""

        column_aliases: str = Field(
            default="", title="CSV の列の別名", description=ALIASES_DESCRIPTION
        )
        model_note: bool = Field(default=True, title=NOTE_TITLE, description=NOTE_DESCRIPTION)

        @field_validator("column_aliases")
        @classmethod
        def check_column_aliases(cls, value: str) -> str:
            """Refuse the save of text that `parse_aliases` cannot read."""
            parse_aliases(value)
            return value

    def __init__(self) -> None:
        self.valves = self.Valves()

    def available(self, _request: object, _user: object, _model: object, _metadata: object) -> bool:
        """nucllei's per-turn gate: the tool exists only where nucllei's sandbox does."""
        try:
            return host.sandbox_configured()
        except Exception:
            return False

    def spec_overrides(
        self, _http: object, user: object, _model: object, metadata: object
    ) -> dict[str, dict[str, object]]:
        """This turn's attachments (sandbox path + header) in `draw_figure`'s description, and the
        note parameter emptied while the admin's `model_note` is off. Any fault keeps the stored
        spec."""
        try:
            user_id = _user_id(user)
            meta = metadata if isinstance(metadata, Mapping) else {}
            refs = (
                _request(
                    meta.get("chat_id"), meta.get("message_id"), user_id, None, None, meta
                ).refs
                if user_id
                else ()
            )
            lines: list[str] = []
            for file_id, name in refs:
                found = host.owned_attachment(file_id, name, user_id or "", _HEADER_BYTES)
                if found is None:
                    continue
                header = _header(found.content)
                columns = f" (列: {', '.join(header)})" if header else ""
                lines.append(f"- /workspace/imports/{found.name}{columns}")
            doc = self.draw_figure.__doc__ or ""
            base = _PARAMS.split(doc, maxsplit=1)[0]
            description = base.strip() + (_FILES + "\n" + "\n".join(lines) if lines else _NO_FILE)
            patch: dict[str, object] = {"description": description}
            if not self.valves.model_note:
                patch["parameters"] = {"properties": {"note": {"description": _NOTE_OFF}}}
        except Exception:
            return {}
        return {"draw_figure": patch}

    async def draw_figure(  # noqa: PLR0913, PLR0917 - two model arguments + nucllei's reserved ones
        self,
        program: PythonCode,
        note: str = "",
        __user__: dict[str, object] | None = None,
        __metadata__: dict[str, object] | None = None,
        __messages__: list[object] | None = None,
        __files__: list[object] | None = None,
        __chat_id__: str | None = None,
        __message_id__: str | None = None,
        __display__: Callable[..., object] | None = None,
    ) -> object:
        """matplotlib でグラフを 1 つ描く、完全な Python プログラムを受け取る。

        プログラムはユーザーのサンドボックスで変更せずに実行され、できた図を検証器がチェックする。
        合格した図だけが、判定と解釈と一緒にユーザーの画面に表示される。
        結果はチェック項目と、合否と理由と次の手。描き方の規則は skill figure-verification にある。

        :param program: グラフを描く完全な Python プログラム。
        :param note: 依頼が図の規則に反するときだけ、依頼が求めたことと図の内容を書く。通常は空。
        """
        return await _Draw(self.valves, program, note, __display__).run(
            __user__, __metadata__, __messages__, __files__, __chat_id__, __message_id__
        )


class _Draw:
    """One `draw_figure` call: its inputs, the language of its reply, its verdict."""

    def __init__(
        self, valves: Tools.Valves, program: object, note: object, display: object
    ) -> None:
        self.valves = valves
        self.program = program if isinstance(program, str) else ""
        # nucllei passes the model's JSON value unchecked; a non-string note is none (Q78).
        self.note = note if isinstance(note, str) and valves.model_note else ""
        self.display = display
        self.japanese = False
        self.description: Description | None = None
        self.listing_failed = False

    async def run(  # noqa: PLR0911, PLR0913, PLR0917 - reserved arguments; a guard per refusal
        self,
        user: object,
        metadata: object,
        messages: object,
        files: object,
        chat_id: object,
        message_id: object,
    ) -> object:
        """Run, judge, publish only a pass; any fault fails closed."""
        try:
            self.japanese = is_japanese(_latest(messages))
            if isinstance(metadata, Mapping) and metadata.get("agent_session"):
                return await self.fail("delegated_session")
            user_id = _user_id(user)
            if user_id is None:
                return await self.fail("no_user")
            request = await asyncio.to_thread(
                _request, chat_id, message_id, user_id, messages, files, metadata
            )
            self.japanese = is_japanese(request.latest)
            attachments = await asyncio.to_thread(_owned, request.refs, user_id)
            payload = run.exec_payload(user_id, self.program, attachments)
            try:
                reply = await host.run_python(payload, run.HTTP_TIMEOUT_SECONDS)
            except host.SandboxRefusedError:
                return await self.fail("sandbox_error")
            except TimeoutError:
                return await self.fail("sandbox_timeout")
            except Exception:
                return await self.fail("sandbox_unreachable")
            try:
                stdout = run.reply_stdout(reply)
            except run.ReplyFaultError as fault:
                return await self.fail(fault.reason)
            # Decoding reads up to `MAX_REPLY` characters, and the judge is pure CPU (seconds on a
            # large CSV, two passes): both run off nucllei's event loop.
            self.description = await asyncio.to_thread(parse_description, stdout)
            if self.description is None:
                return await self.fail("no_description")
            sources = Sources(
                tuple((item.name, item.content) for item in attachments),
                request.text,
                "strict",
                parse_aliases(self.valves.column_aliases),
            )
            verdict = await asyncio.to_thread(judge, self.description, sources)
            if not isinstance(verdict, Passed):
                return await self.fail(verdict.reason, verdict.site)
            uri = await asyncio.to_thread(png_uri, stdout)
            if uri is None:
                return await self.fail("no_image")
            try:
                image = base64.b64decode(uri[len(_PNG_PREFIX) :])
                file_id = await asyncio.to_thread(host.save_png, user_id, image)
            except Exception:
                return await self.fail("publish_failed")
            return await self.publish(file_id, verdict)
        except Exception:
            return await self.fail("verifier_error")

    async def publish(self, file_id: str, verdict: Passed) -> object:
        """Show the image, the verdict, the interpretation and the note; return the check list.

        Everything is built before the one display push, and a fault in building it is a failed
        publication (T10): nucllei appends each push, so a fault after a shown pass would set a
        failure beside the image (consultant-1 T10). A push that does not go through returns the
        failure without a second push, since the sink may hold the pass already (reviewer-1 F4).
        """
        language = int(self.japanese)
        try:
            interpretation = verdict.interpretation_ja if self.japanese else verdict.interpretation
            # No length limit (user): an 8 MB note took 2.7 s to render (CPython 3.14).
            note = await asyncio.to_thread(note_line, self.note, japanese=self.japanese)
            evidence = await asyncio.to_thread(
                _evidence, self.program, self.description, None, None
            )
            result = _result(_bounded(None, evidence, PASSED, japanese=self.japanese))
        except Exception:
            self.listing_failed = True
            return await self.fail("publish_failed")
        shown = (
            f"{PASS_TEXTS[language]}\n\n![{IMAGE_ALT[language]}](/api/v1/files/{file_id}/content)"
            f"\n\n{interpretation}{note}"
        )
        if not _show(self.display, shown):
            return await self.fail("publish_failed", show=False)
        return result

    async def fail(self, reason: Reason, site: int | None = None, *, show: bool = True) -> object:
        """Block the figure: one log record for the admin, the cause for the user, the check list
        and the next step for the model.

        Neither the log nor the shown cause carries sandbox output, program bytes or request text,
        since an error message can quote the user's clinical data; the check list quotes the
        program alone, inside the user's own chat.
        """
        with contextlib.suppress(Exception):
            _LOGGER.info("figure verification failed reason=%s", reason)
        language = int(self.japanese)
        # A blocked reply shows no model note (user ruling): it describes a chart the user never
        # sees, and it can contradict the verdict.
        if show:
            _show(self.display, f"{FAIL_TEXTS[language]}\n\n{REASONS[reason][language]} ({reason})")
        with contextlib.suppress(Exception):
            host.mark_error_kind(error_kind(reason))
        tail = FAILED.format(cause=REASONS[reason][1], reason=reason) + NEXT[next_step(reason)]
        if self.listing_failed:  # never re-enter a renderer that failed (consultant-1 T13)
            return _result(tail)
        try:
            evidence = await asyncio.to_thread(
                _evidence, self.program, self.description, reason, site
            )
            return _result(_bounded(reason, evidence, tail, japanese=self.japanese))
        except Exception:
            return _result(tail)
