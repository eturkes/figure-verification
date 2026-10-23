# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The one sandbox run per chart: the reader, then the model's program, unchanged, in the jail.

Each attachment goes to `/workspace/imports/<name>` first, through the sandbox's no-follow file
write; then nucllei's sandbox writes `code` to a file under `/workspace/.exec/` and runs it with the
jail's `/opt/venv/bin/python -u`, whose environment already sets `MPLBACKEND=Agg`, a writable
`MPLCONFIGDIR` and a matplotlibrc whose sans-serif family is Noto Sans CJK JP. The jail has no
network. The reader and the program travel as base64, so no byte of either is re-encoded on the
way, and stdout is the reader's alone: the description line, then at most one PNG line.
"""

import base64
from collections.abc import Mapping
from typing import Final

from nucllei_skill.host import Attachment
from nucllei_skill.reasons import RUN_TIMEOUT_SECONDS, Reason
from webui.paste_in.reader_text import reader_source
from webui.paste_in.reply import MAX_REPLY

# The sandbox clamps the run to its own maximum and waits 15 s past it; nucllei's own tool allows
# its client the run plus 30 s, which also covers the time waiting for the user's run lock.
HTTP_TIMEOUT_SECONDS: Final = RUN_TIMEOUT_SECONDS + 30
# nucllei's own attachment import (`builtin_tools/sandbox.py::_import_file`) waits 120 s per file.
WRITE_TIMEOUT_SECONDS: Final = 120
# A lone surrogate (a JSON `\ud800` escape in the call) reaches the jail as written.
_EXACT: Final = ("utf-8", "surrogatepass")


def _b64(data: bytes) -> str:
    return repr(base64.b64encode(data).decode("ascii"))


# The reader starts each run from matplotlib's internal defaults (`reader.py::_prepare`), which
# drops the jail's matplotlibrc; so the wrapper resolves the first family of that file's
# sans-serif list that is no DejaVu face to its font file first, and the reader registers it after
# DejaVu Sans, as on Open WebUI: Latin draws in DejaVu Sans, Japanese through the fallback.
_FONT_LINES: Final = (
    "import matplotlib as _fv_mpl",
    "from matplotlib import font_manager as _fv_fonts",
    "_fv_font = None",
    "for _fv_family in _fv_mpl.rcParams['font.sans-serif']:",
    "    if _fv_font is None and not _fv_family.startswith('DejaVu'):",
    "        try:",
    "            _fv_font = _fv_fonts.findfont(",
    "                _fv_fonts.FontProperties(family=_fv_family), fallback_to_default=False",
    "            )",
    "        except ValueError:",
    "            pass",
)


def wrapper_code(program: str) -> str:
    """The jail's code: find the jail's Japanese font, install the reader, then run the exact
    program through it."""
    return (
        "\n".join(
            (
                "import base64 as _fv_b64",
                *_FONT_LINES,
                "_fv_reader = {'__name__': 'figure_verification_reader'}",
                f"_fv_source = _fv_b64.b64decode({_b64(reader_source().encode('utf-8'))})",
                "exec(compile(_fv_source.decode('utf-8'), '<figure-reader>', 'exec'), _fv_reader)",
                f"_fv_program = _fv_b64.b64decode({_b64(program.encode(*_EXACT))})",
                "_fv_program = _fv_program.decode('utf-8', 'surrogatepass')",
                "print(_fv_reader['run'](_fv_program, _fv_font), end='')",
            )
        )
        + "\n"
    )


def write_payload(user_id: str, attachment: Attachment) -> dict[str, object]:
    """One `/files/write` body: an attachment at `imports/<name>` in the caller's workspace.

    `nofollow` takes the sandbox's descriptor-based write, which opens every path segment
    `O_NOFOLLOW` and refuses a link at the leaf; the user's own jail runs can plant links in that
    persistent workspace (M23.1 F1).
    """
    return {
        "user_id": user_id,
        "path": f"imports/{attachment.name}",
        "b64": base64.b64encode(attachment.content).decode("ascii"),
        "nofollow": True,
    }


def exec_payload(user_id: str, program: str) -> dict[str, object]:
    """The `/exec` body: a stateless run (no chat kernel shares the reader's hooks). It carries no
    `imports`: the sandbox writes those with a plain write that follows links (M23.1 F1), and
    nucllei's own tools never send them."""
    return {
        "user_id": user_id,
        "lang": "python",
        "code": wrapper_code(program),
        "timeout_s": RUN_TIMEOUT_SECONDS,
    }


class ReplyFaultError(Exception):
    """A `/exec` reply that carries no clean run of the reader."""

    def __init__(self, *, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


def reply_stdout(reply: object) -> str:
    """The reader's stdout from one `/exec` reply; `ReplyFaultError` names why there is none.

    The reader catches every outcome of the program, so the wrapper itself exits 0; anything else
    is the jail's: a kill past the time limit, a memory or process limit. Stderr carries no
    verdict (a font-cache notice is not a fault), and a stdout the sandbox cut, or one longer than
    the reader writes, is not read.
    """
    if not isinstance(reply, Mapping):
        raise ReplyFaultError(reason="reply_malformed")
    stdout = reply.get("stdout")
    exit_code = reply.get("exit_code")
    timed_out = reply.get("timed_out")
    if timed_out is True:
        raise ReplyFaultError(reason="sandbox_timeout")
    if timed_out is not False or type(exit_code) is not int or not isinstance(stdout, str):
        raise ReplyFaultError(reason="reply_malformed")
    if exit_code != 0:
        raise ReplyFaultError(reason="sandbox_error")
    if reply.get("stdout_truncated") is not False or len(stdout) > MAX_REPLY:
        raise ReplyFaultError(reason="reply_malformed")
    return stdout
