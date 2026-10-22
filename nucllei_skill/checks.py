# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The check list a nucllei reply carries: every check, as markdown inside the collapsed tool block.

nucllei renders a tool's result inside the collapsed block (Q82 ruling 10: the user opens it with
the block's toggle) and sends the same text to the model; its markdown shows block HTML as text,
so a row is plain markdown: the mark + title, what the check covers and does, its program lines
inside a backtick fence, why it failed, a link to its section of the guide copy on the server.
Row data, the line selection and the related lines are the Open WebUI check list's
(`webui/paste_in/checks.py`, `excerpts.py`); the program, run and attach rows name this host.
"""

import re
from typing import Final, Literal, TypeAlias, cast, get_args

from nucllei_skill.reasons import REASONS, Reason
from verifier.figure.inert import visible
from verifier.figure.reasons import FigureReason
from webui.paste_in.checks import (
    _BREAK,
    _LINE_CHARACTERS,
    _SCAN,
    BEYOND,
    CHECKS,
    CODE,
    DREW,
    ELIDED,
    GUIDE_LINK,
    MARKS,
    NO_LINES,
    NOT_RUN,
    RAN,
    RELATED,
    STRICT_COLUMNS,
    UNRUN,
    WHAT,
    WHY,
    Check,
    Evidence,
    select_lines,
)
from webui.paste_in.checks import (
    CHECK_OF as SHARED_CHECK_OF,
)
from webui.paste_in.checks import (
    EXPLAIN as SHARED_EXPLAIN,
)
from webui.paste_in.checks import (
    TEXTS as SHARED_TEXTS,
)

_State: TypeAlias = Literal["pass", "fail", "skip"]

_OWN_CHECK: Final[dict[Reason, Check]] = {
    "no_user": "program",
    "delegated_session": "program",
    "sandbox_unreachable": "run",
    "sandbox_timeout": "run",
    "sandbox_error": "run",
    "reply_malformed": "run",
    "no_description": "run",
    "verifier_error": "figure",
    "no_image": "attach",
    "publish_failed": "attach",
}
CHECK_OF: Final[dict[Reason, Check]] = {
    **{cast("Reason", reason): SHARED_CHECK_OF[reason] for reason in get_args(FigureReason)},
    **_OWN_CHECK,
}

TEXTS: Final[dict[Check, tuple[tuple[str, str], tuple[str, str]]]] = {
    **SHARED_TEXTS,
    "program": (
        ("Chart program received from the model", "one program, sent through draw_figure"),
        ("モデルからグラフのプログラムを受信", "draw_figure で送られた 1 つのプログラム"),
    ),
    "run": (
        (
            "Program run in the code sandbox",
            "the program runs unchanged in your sandbox and finishes without an error",
        ),
        (
            "サンドボックスでプログラムを実行",
            "プログラムを変更せずにあなたのサンドボックスで実行し、エラーなく終了",
        ),
    ),
    "columns": STRICT_COLUMNS,
    "attach": (
        ("Image shown with the reply", "one PNG image, saved on the server"),
        ("返信に画像を表示", "PNG 画像 1 枚をサーバーに保存"),
    ),
}
EXPLAIN: Final[dict[Check, tuple[str, str]]] = {
    **SHARED_EXPLAIN,
    "program": (
        "The model sends its chart program through the draw_figure tool. The verifier checks the"
        " program of this call, which the tool block shows above.",
        "モデルはグラフのプログラムを draw_figure ツールで送ります。"
        "検証器はこの呼び出しのプログラムをチェックします。プログラムはこの欄の上に表示されています。",
    ),
    "run": (
        "The code sandbox runs the model's program, unchanged, with your attached files. The"
        " program must finish without an error, and the run reports the figure that it drew.",
        "コード実行のサンドボックスが、モデルのプログラムを変更せずに、添付ファイルと一緒に実行します。"
        "プログラムはエラーなく終了し、実行結果として描いた図を報告する必要があります。",
    ),
    "attach": (
        "The run returns one PNG image, and the server saves it and shows it with this reply. If"
        " either step fails, the verifier shows no image.",
        "実行結果として PNG 画像が 1 枚返り、サーバーがそれを保存してこの返信に表示します。"
        "どちらかに失敗した場合、検証器は画像を表示しません。",
    ),
}
HEADING: Final = ("Checks", "チェック項目")
# The guide copy an administrator places on the server (Q82 ruling 6): the hospital network's
# browsers reach the server, never GitHub.
GUIDE: Final = (
    "/ext/public/figure-verification/checks.html",
    "/ext/public/figure-verification/checks.ja.html",
)
_MARKED = "\N{BLACK RIGHT-POINTING TRIANGLE}"
_TICKS = re.compile("`+")


def _fence(lines: list[str]) -> list[str]:
    """`lines` inside a backtick fence longer than any backtick run in them, so no program text
    can close it."""
    longest = max((len(run) for line in lines for run in _TICKS.findall(line)), default=0)
    fence = "`" * max(3, longest + 1)
    return [fence, *lines, fence]


def _listing(
    program: str, related: frozenset[int] | None, site: int | None, language: int
) -> tuple[list[str], bool]:
    """The selected program lines, numbered, the site's marked; and whether a mark is shown."""
    lines = _BREAK.split(program[:_SCAN])
    selection = select_lines(lines, related, site)
    width = len(str(max(selection.numbers, default=1)))
    shown: list[str] = []
    for number in selection.numbers:
        if shown and number - 1 not in selection.numbers:
            shown.append("\N{VERTICAL ELLIPSIS}")
        line = "".join(map(visible, lines[number - 1][:_LINE_CHARACTERS]))
        if len(lines[number - 1]) > _LINE_CHARACTERS:
            line += "\N{HORIZONTAL ELLIPSIS}"
        mark = _MARKED if number == selection.marked else " "
        shown.append(f"{mark} {number:>{width}} | {line}".rstrip())
    body = ["", *_fence(shown)]
    if selection.pool > len(selection.numbers):
        body += ["", ELIDED[language].format(n=selection.pool - len(selection.numbers))]
    if len(program) > _SCAN:
        body += ["", BEYOND[language]]
    return body, selection.marked is not None


def _program(
    check: Check, state: _State, language: int, evidence: Evidence
) -> tuple[list[str], bool]:
    """A row's program part and whether it marks a line: the program row points at the call's
    own argument, the attach row and a passed run row carry a note, a failing row with no related
    line lists the whole program, any other row that ran its related lines."""
    if check == "attach":
        return [NO_LINES[language]], False
    if check == "run" and state == "pass":
        return [RAN[language]], False
    if check == "program" or evidence.program is None:
        return [], False
    count = len(_BREAK.split(evidence.program[:_SCAN]))
    related = frozenset(n for n in dict(evidence.lines).get(check, ()) if 1 <= n <= count)
    site = evidence.site if state == "fail" else None
    if state == "fail" and not related:
        listing, drew = _listing(evidence.program, None, site, language)
        return [f"{CODE[language]}:", *listing], drew
    if not related:
        return [], False
    listing, drew = _listing(evidence.program, related, site, language)
    return [f"{RELATED[language]}:", *listing], drew


def _row(
    check: Check, state: _State, reason: Reason | None, language: int, evidence: Evidence
) -> list[str]:
    glyph, _labels = MARKS[state]
    title, covers = TEXTS[check][language]
    unrun = f" ({UNRUN[language]})" if state == "skip" else ""
    parts: list[list[str]] = [[covers], [f"{WHAT[language]}: {EXPLAIN[check][language]}"]]
    drew = False
    if state == "skip":
        parts.append([NOT_RUN[language]])
    else:
        program, drew = _program(check, state, language, evidence)
        if program:
            parts.append(program)
    if reason is not None and state == "fail":
        parts.append([f"{WHY[language]}: {REASONS[reason][language]} ({reason})"])
        if drew:
            parts.append([f"{_MARKED} {DREW[language]}"])
    parts.append([f"[{GUIDE_LINK[language]}]({GUIDE[language]}#check-{check})"])
    body = [f"- {glyph} **{title}**{unrun}"]
    for part in parts:
        body += ["", *(f"  {line}" if line else "" for line in part)]
    return body


def checklist(reason: Reason | None, *, japanese: bool, evidence: Evidence) -> str:
    """Every check for one reply: passed, the failing one with its cause, the unrun rest.

    `reason` is the failure reason, or `None` for a published figure, whose checks all passed.
    """
    language = 1 if japanese else 0
    failing = len(CHECKS) if reason is None else CHECKS.index(CHECK_OF[reason])
    lines = [f"**{HEADING[language]}**", ""]
    for index, check in enumerate(CHECKS):
        state: _State = "pass" if index < failing else "fail" if index == failing else "skip"
        lines += [*_row(check, state, reason, language, evidence), ""]
    return "\n".join(lines).rstrip("\n") + "\n"
