# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q82.1 (`.agent/archive/contracts/q82.md` T3-T16): the nucllei tool, against strict fakes of
nucllei and the real reader + judge. Expected texts are hand-stated literals, never read from the
module."""

from __future__ import annotations

import ast
import asyncio
import base64
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from nucllei_skill import run as jail
from nucllei_support import (
    ASSISTANT_ID,
    CHAT_ID,
    OTHER_ID,
    USER_ID,
    SandboxHTTPError,
    World,
    history,
    install,
    invoke,
    ref,
    text_of,
)
from verifier.figure.description import parse_description

SALES = b"month,revenue\nJan,100\nFeb,120\nMar,90\n"
HONEST = (
    "import matplotlib.pyplot as plt\n"
    "fig, ax = plt.subplots()\n"
    "ax.bar(['Jan', 'Feb', 'Mar'], [100, 120, 90])\n"
    "ax.set_ylabel('revenue')\n"
    "plt.show()\n"
)
INVENTED = HONEST.replace("90]", "999]")
TRUNCATED = HONEST.replace("plt.show()", "ax.set_ylim(80, 130)\nplt.show()")
REQUEST = "Plot revenue by month"
REQUEST_JA = "revenue を month ごとに棒グラフにしてください"
PASS_EN = "Figure verification passed"  # noqa: S105 - public verdict, not a credential
FAIL_EN = "Figure verification failed, no image produced"
PASS_JA = "図の検証に合格しました。"  # noqa: S105 - public verdict, not a credential
FAIL_JA = "図の検証に合格しませんでした。画像は表示されません。"
OK_TAIL = (
    "図は検証に合格し、画像と判定と解釈をユーザーの画面に表示した。"
    "次の手: 画像を本文に貼り直さない。合否を言い直さず、上のチェック項目も本文に写さない。"
    "図が示す内容を本文で短く説明する。"
)
_ROW = re.compile("^\\*\\*(\N{CHECK MARK}|\N{BALLOT X}|\N{EN DASH}) ", re.MULTILINE)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    found = World(root=tmp_path)
    install(monkeypatch, found)
    return found


def _stored(world: World, *turns: dict[str, object]) -> None:
    world.chats[(CHAT_ID, USER_ID)] = history(*turns)


def _sales_chat(world: World, request: str = REQUEST) -> None:
    world.attach("f1", "sales.csv", SALES)
    _stored(world, {"role": "user", "content": request, "files": [ref("f1", "sales.csv")]})


def _shown(world: World) -> str:
    assert len(world.displays) == 1, world.displays
    content, kind = world.displays[0]
    assert kind == "markdown"
    return content


# --- T3 spec ------------------------------------------------------------------------------------


def test_q82_t3_the_model_sees_one_function_and_no_toolkit_note() -> None:
    """nucllei exposes every public non-class callable but its two hooks
    (`utils/tools.py::get_functions_from_tool`) and prepends a class docstring as a note."""
    from nucllei_skill.tool import Tools  # noqa: PLC0415

    tools = Tools()
    exposed = [
        name
        for name in dir(tools)
        if callable(getattr(tools, name))
        and not name.startswith("_")
        and not isinstance(getattr(tools, name), type)
        and name not in {"available", "spec_overrides"}
    ]
    assert exposed == ["draw_figure"]
    assert Tools.__doc__ is None


def test_q82_t3_each_parameter_line_reaches_the_model_whole() -> None:
    """nucllei cuts the description at the first `:param` and reads each `:param` line alone."""
    from nucllei_skill.tool import Tools  # noqa: PLC0415

    doc = cast("str", Tools.draw_figure.__doc__)
    head, _, params = doc.partition(":param")
    assert "draw_figure" not in head or "skill" in head
    assert ":return" not in doc
    lines = [line.strip() for line in (":param" + params).splitlines() if line.strip()]
    assert [re.match(r":param (\w+):\s*(.+)", line).group(1) for line in lines] == [  # type: ignore[union-attr]
        "program",
        "note",
    ]


# --- T4 available -------------------------------------------------------------------------------


def test_q82_t4_the_tool_exists_only_where_the_sandbox_does(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from nucllei_skill.tool import Tools  # noqa: PLC0415

    assert world.sandbox_url
    assert Tools().available(None, None, None, {}) is True
    monkeypatch.setattr(sys.modules["nucllei.builtin_tools.sandbox"], "SANDBOX_URL", "")
    assert Tools().available(None, None, None, {}) is False
    monkeypatch.delitem(sys.modules, "nucllei.builtin_tools.sandbox")
    monkeypatch.delattr(sys.modules["nucllei.builtin_tools"], "sandbox")
    assert Tools().available(None, None, None, {}) is False


# --- T5 spec_overrides --------------------------------------------------------------------------


def _base() -> str:
    from nucllei_skill.tool import Tools  # noqa: PLC0415

    return cast("str", Tools.draw_figure.__doc__).split(":param", 1)[0].strip()


def test_q82_t5_the_description_lists_this_turn_s_files_from_the_stored_branch(
    world: World,
) -> None:
    from nucllei_skill.tool import Tools  # noqa: PLC0415

    _sales_chat(world)
    world.attach("f2", "body-only.csv", b"a,b\n1,2\n")
    metadata = {"chat_id": CHAT_ID, "message_id": ASSISTANT_ID, "files": [ref("f2", "x.csv")]}
    patch = Tools().spec_overrides(None, type("U", (), {"id": USER_ID})(), None, metadata)
    assert patch == {
        "draw_figure": {
            "description": _base()
            + "\n\nこのターンの添付ファイル (プログラムはこのパスで読む):"
            + "\n- /workspace/imports/sales.csv (列: month, revenue)"
        }
    }


def test_q82_t5_no_file_and_the_note_switch(world: World) -> None:
    from nucllei_skill.tool import Tools  # noqa: PLC0415

    _stored(world, {"role": "user", "content": REQUEST})
    tools = Tools()
    tools.valves = tools.Valves(model_note=False)
    metadata = {"chat_id": CHAT_ID, "message_id": ASSISTANT_ID}
    assert tools.spec_overrides(None, {"id": USER_ID}, None, metadata) == {
        "draw_figure": {
            "description": _base()
            + "\n\n添付ファイルはない。依頼文に書かれた数値とラベルだけを描く。",
            "parameters": {"properties": {"note": {"description": "常に空にする。"}}},
        }
    }


def test_q82_t5_a_fault_keeps_the_stored_spec() -> None:
    from nucllei_skill.tool import Tools  # noqa: PLC0415

    class Broken:
        @property
        def id(self) -> str:
            raise RuntimeError

    assert Tools().spec_overrides(None, Broken(), None, {}) == {}


# --- T6 run -------------------------------------------------------------------------------------


def test_q82_t6_one_exec_call_carries_the_exact_program_and_the_owned_csv(world: World) -> None:
    world.program = HONEST
    _sales_chat(world)
    invoke(world)
    assert len(world.calls) == 1
    path, payload, timeout = world.calls[0]
    assert (path, timeout) == ("/exec", 150)
    assert payload == {
        "user_id": USER_ID,
        "lang": "python",
        "code": jail.wrapper_code(HONEST),
        "timeout_s": 120,
        "imports": [{"name": "sales.csv", "b64": base64.b64encode(SALES).decode("ascii")}],
    }


@pytest.mark.parametrize(
    ("user", "metadata", "reason"),
    [
        ({"id": ""}, None, "no_user"),
        ({}, None, "no_user"),
        ({"id": USER_ID}, {"agent_session": {"id": "s"}}, "delegated_session"),
    ],
    ids=["empty-user", "no-user", "delegated"],
)
def test_q82_t6_a_refused_caller_runs_nothing(
    world: World, user: dict[str, object], metadata: dict[str, object] | None, reason: str
) -> None:
    world.program = HONEST
    _sales_chat(world)
    result = text_of(invoke(world, user=user, metadata=metadata))
    assert world.calls == []
    assert world.inserted == []
    assert f"({reason})" in _shown(world)
    assert f"({reason})。" in result


def test_q82_t6_the_wrapper_runs_the_exact_program_through_the_reader() -> None:
    """The code the jail receives, executed: the reader describes the program's figure, and the
    program literal decodes to the program's exact text, a lone surrogate included (reviewer-1
    R3: the sandbox fake checks the wrapper but runs the reader directly)."""
    program = "import matplotlib.pyplot as plt\nlabel = '\udcff'\nplt.bar([0, 1], [3, 5])\n"
    code = jail.wrapper_code(program)
    literals = [
        node.args[0].value
        for node in ast.walk(ast.parse(code))
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", "") == "b64decode"
        and isinstance(node.args[0], ast.Constant)
    ]
    assert base64.b64decode(cast("str", literals[-1])).decode("utf-8", "surrogatepass") == program
    plain = jail.wrapper_code(program.replace("\udcff", "ok"))
    ran = subprocess.run(  # noqa: S603 - this interpreter, the generated code
        [sys.executable, "-c", plain],
        capture_output=True,
        text=True,
        errors="surrogateescape",
        env={**os.environ, "MPLBACKEND": "Agg"},
        timeout=120,
        check=True,
    )
    described = parse_description(ran.stdout)
    assert described is not None
    assert described.error is None
    assert len(described.figures) == 1


# --- T7 sources ---------------------------------------------------------------------------------


def test_q82_t7_a_csv_an_inlet_stripped_from_the_body_still_binds_the_values(
    world: World,
) -> None:
    """llens `large_file_gate` drops an oversize CSV from `__files__` + metadata (consultant-1 T7):
    the stored branch keeps it, so an invented value blocks instead of passing on integrity."""
    world.program = INVENTED
    _sales_chat(world)
    invoke(world, files=[], metadata={"files": []})
    assert _shown(world).startswith(FAIL_EN)
    assert "(value_not_found)" in _shown(world)
    imports = cast("list[dict[str, str]]", world.calls[0][1]["imports"])
    assert [item["name"] for item in imports] == ["sales.csv"]


def test_q82_t7_the_body_s_files_count_only_for_an_unstored_chat(world: World) -> None:
    world.program = INVENTED
    world.attach("f1", "sales.csv", SALES)
    invoke(world, messages=[{"role": "user", "content": REQUEST}], files=[ref("f1", "sales.csv")])
    assert "(value_not_found)" in _shown(world)


def test_q82_t7_foreign_and_notice_files_are_no_user_data(world: World) -> None:
    world.program = HONEST
    world.attach("f1", "sales.csv", SALES, owner=OTHER_ID)
    world.attach("f3", "made.csv", SALES)
    _stored(
        world,
        {"role": "user", "content": REQUEST, "files": [ref("f1", "sales.csv")]},
        {"role": "assistant", "content": "working"},
        {
            "role": "user",
            "content": "task done",
            "meta": {"system_notice": "task"},
            "files": [ref("f3", "made.csv")],
        },
    )
    invoke(world)
    assert world.calls[0][1]["imports"] == []
    assert "integrity" in _shown(world).lower() or "完全性" in _shown(world)


def test_q82_t7_a_later_file_of_the_same_name_replaces_the_earlier(world: World) -> None:
    world.program = HONEST.replace("[100, 120, 90]", "[1, 2, 3]")
    world.attach("f1", "sales.csv", SALES)
    world.attach("f4", "sales.csv", b"month,revenue\nJan,1\nFeb,2\nMar,3\n")
    _stored(
        world,
        {"role": "user", "content": REQUEST, "files": [ref("f1", "sales.csv")]},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "use the new file", "files": [ref("f4", "sales.csv")]},
    )
    invoke(world)
    imports = world.calls[0][1]["imports"]
    assert imports == [
        {
            "name": "sales.csv",
            "b64": base64.b64encode(b"month,revenue\nJan,1\nFeb,2\nMar,3\n").decode(),
        }
    ]
    assert _shown(world).startswith(PASS_EN)


def test_q82_t7_a_nested_ref_resolves_by_its_file_id(world: World) -> None:
    world.program = HONEST
    world.attach("f1", "sales.csv", SALES)
    nested = {"type": "file", "file": {"id": "f1", "filename": "sales.csv"}}
    _stored(world, {"role": "user", "content": REQUEST, "files": [nested]})
    invoke(world)
    assert _shown(world).startswith(PASS_EN)


# --- T8 request ---------------------------------------------------------------------------------


def test_q82_t8_an_earlier_message_s_number_is_typed_data(world: World) -> None:
    world.program = "import matplotlib.pyplot as plt\nplt.bar([0, 1], [3, 5])\nplt.show()\n"
    _stored(
        world,
        {"role": "user", "content": "The values are 3 and 5."},
        {"role": "assistant", "content": "Noted."},
        {"role": "user", "content": "Draw them as bars."},
    )
    invoke(world, messages=[{"role": "user", "content": "Draw them as bars."}])
    assert _shown(world).startswith(PASS_EN)


def test_q82_t8_a_server_notice_is_not_the_user_s_request(world: World) -> None:
    world.program = "import matplotlib.pyplot as plt\nplt.bar([0], [12345])\nplt.show()\n"
    _stored(
        world,
        {"role": "user", "content": "Plot 7 as a bar."},
        {"role": "assistant", "content": "Running."},
        {"role": "user", "content": "A=12345", "meta": {"system_notice": "task"}},
    )
    invoke(world, messages=[{"role": "user", "content": "A=12345"}])
    assert "(value_not_found)" in _shown(world)


def test_q82_t8_the_latest_human_message_sets_the_language(world: World) -> None:
    world.program = HONEST
    _sales_chat(world, REQUEST_JA)
    world.chats[(CHAT_ID, USER_ID)] = history(
        {"role": "user", "content": REQUEST_JA, "files": [ref("f1", "sales.csv")]},
        {"role": "assistant", "content": "…"},
        {"role": "user", "content": "Task finished.", "meta": {"system_notice": "task"}},
    )
    invoke(world, messages=[{"role": "user", "content": "Task finished."}])
    assert _shown(world).startswith(PASS_JA)


@pytest.mark.parametrize(
    "content",
    ["", [{"type": "image_url", "image_url": {"url": "/api/v1/files/i/content"}}]],
    ids=["empty", "image-only"],
)
def test_q82_t8_a_textless_latest_message_reads_english(world: World, content: object) -> None:
    """The language follows the latest human message even when it holds no text (an attachment
    alone), never an earlier one (reviewer-1 F2)."""
    world.program = HONEST
    world.attach("f1", "sales.csv", SALES)
    world.chats[(CHAT_ID, USER_ID)] = history(
        {"role": "user", "content": REQUEST_JA},
        {"role": "assistant", "content": "…"},
        {"role": "user", "content": content, "files": [ref("f1", "sales.csv")]},
    )
    invoke(world, messages=[{"role": "user", "content": content}])
    assert _shown(world).startswith(PASS_EN)


# --- T9 reply -----------------------------------------------------------------------------------


_GOOD = {"exit_code": 0, "timed_out": False, "stdout": "", "stdout_truncated": False}


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        ([], "reply_malformed"),
        ({**_GOOD, "timed_out": True, "exit_code": -9}, "sandbox_timeout"),
        ({**_GOOD, "exit_code": 1}, "sandbox_error"),
        ({**_GOOD, "exit_code": "0"}, "reply_malformed"),
        ({**_GOOD, "stdout": None}, "reply_malformed"),
        ({**_GOOD, "stdout_truncated": True}, "reply_malformed"),
        ({k: v for k, v in _GOOD.items() if k != "stdout_truncated"}, "reply_malformed"),
        ({k: v for k, v in _GOOD.items() if k != "timed_out"}, "reply_malformed"),
        ({**_GOOD, "timed_out": "false"}, "reply_malformed"),
        ({**_GOOD, "stdout": "x" * 900_100}, "reply_malformed"),
        (_GOOD, "no_description"),
    ],
    ids=[
        "not-a-map",
        "timed-out",
        "nonzero-exit",
        "exit-not-int",
        "no-stdout",
        "cut",
        "cut-unknown",
        "timeout-unknown",
        "timeout-not-bool",
        "too-long",
        "empty",
    ],
)
def test_q82_t9_a_reply_without_a_clean_run_names_its_cause(
    world: World, reply: object, reason: str
) -> None:
    world.program = HONEST
    world.reply = lambda _payload: reply
    _sales_chat(world)
    invoke(world)
    assert f"({reason})" in _shown(world)
    assert world.inserted == []


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (SandboxHTTPError(401, "token"), "sandbox_error"),
        (TimeoutError(), "sandbox_timeout"),
        (OSError("refused"), "sandbox_unreachable"),
    ],
    ids=["http-status", "deadline", "transport"],
)
def test_q82_t9_a_failed_call_names_its_cause(
    world: World, error: BaseException, reason: str
) -> None:
    world.program = HONEST
    world.reply = error
    _sales_chat(world)
    invoke(world)
    assert f"({reason})" in _shown(world)


# --- T10 publish --------------------------------------------------------------------------------


def test_q82_t10_a_pass_stores_the_png_and_shows_it_once(world: World) -> None:
    world.program = HONEST
    _sales_chat(world)
    result = text_of(invoke(world))
    ((owner, form),) = world.inserted
    assert owner == USER_ID
    assert form.meta["content_type"] == "image/png"
    assert world.uploads[form.path].startswith(b"\x89PNG\r\n\x1a\n")
    assert _shown(world) == (
        f"{PASS_EN}\n\n![Verified chart](/api/v1/files/{form.id}/content)\n\n"
        "Bars: `revenue` by `month` from `sales.csv`."
    )
    assert result.endswith(OK_TAIL)


def test_q82_t10_an_unstored_file_record_publishes_nothing(world: World) -> None:
    world.program = HONEST
    world.insert_none = True
    _sales_chat(world)
    invoke(world)
    assert _shown(world).startswith(FAIL_EN)
    assert "(publish_failed)" in _shown(world)


def test_q82_t10_a_fault_after_the_store_never_shows_a_pass(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fault while building the pass is a failed publication, and the failure path never runs
    the renderer that failed again (reviewer-1 F3)."""
    world.program = HONEST
    _sales_chat(world)
    calls: list[object] = []

    def broken(reason: object, **_: object) -> str:
        calls.append(reason)
        raise RuntimeError

    monkeypatch.setattr("nucllei_skill.tool.checklist", broken)
    result = text_of(invoke(world))
    assert _shown(world).startswith(FAIL_EN)
    assert "(publish_failed)" in _shown(world)
    assert calls == [None]
    assert world.marks == ["fatal"]
    assert result.endswith("次の手: 呼び直さない。図を表示できなかったことをユーザーに伝える。")


@pytest.mark.parametrize("display", ["raises", "missing"])
def test_q82_t10_a_pass_nobody_saw_is_no_pass(world: World, display: str) -> None:
    """A display that refuses the push, or none at all (a headless call), never yields the
    'shown to the user' result, and no second push follows a refused one (reviewer-1 F4)."""
    world.program = HONEST
    _sales_chat(world)
    pushes: list[str] = []

    def refuse(content: str, kind: str = "markdown") -> None:  # noqa: ARG001
        pushes.append(content)
        raise RuntimeError

    if display == "raises":
        world.display = refuse  # type: ignore[method-assign]
    else:
        world.display = None  # type: ignore[assignment,method-assign]
    result = text_of(invoke(world))
    assert "画像と判定と解釈をユーザーの画面に表示した" not in result
    assert "(publish_failed)。" in result
    assert world.marks == ["fatal"]
    assert len(pushes) == (1 if display == "raises" else 0)


# --- T11 fail -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("program", "reply", "reason", "kind"),
    [
        (TRUNCATED, None, "zero_not_in_limits", "call"),
        ("x = (", None, "program_syntax_error", "call"),
        (HONEST, TimeoutError(), "sandbox_timeout", "failure"),
        (HONEST, lambda _p: _GOOD, "no_description", "fatal"),
    ],
    ids=["chart", "program", "sandbox", "protocol"],
)
def test_q82_t11_the_result_names_who_can_fix_the_block(  # noqa: PLR0913, PLR0917 - the case + fixtures
    world: World,
    caplog: pytest.LogCaptureFixture,
    program: str,
    reply: object,
    reason: str,
    kind: str,
) -> None:
    world.program = program
    world.reply = reply  # type: ignore[assignment]
    _sales_chat(world)
    with caplog.at_level(logging.INFO, logger="nucllei_skill.tool"):
        invoke(world)
    assert world.marks == [kind]
    assert [r.getMessage() for r in caplog.records if r.name == "nucllei_skill.tool"] == [
        f"figure verification failed reason={reason}"
    ]


def test_q82_t11_the_error_kind_and_next_step_tables() -> None:
    from nucllei_skill.texts import error_kind, next_step  # noqa: PLC0415

    expected = {
        "no_user": ("failure", "stop"),
        "delegated_session": ("failure", "stop"),
        "sandbox_unreachable": ("failure", "retry"),
        "sandbox_timeout": ("failure", "retry"),
        "sandbox_error": ("failure", "retry"),
        "reply_malformed": ("fatal", "stop"),
        "no_description": ("fatal", "stop"),
        "no_image": ("fatal", "stop"),
        "publish_failed": ("fatal", "stop"),
        "verifier_error": ("fatal", "stop"),
        "program_error": ("call", "fix"),
        "value_not_found": ("call", "fix"),
        "glyph_missing": ("call", "fix"),
    }
    assert {r: (error_kind(r), next_step(r)) for r in expected} == expected  # type: ignore[arg-type]


# --- T12 result ---------------------------------------------------------------------------------


def test_q82_t12_the_result_holds_every_check_then_the_model_s_tail(world: World) -> None:
    world.program = TRUNCATED
    _sales_chat(world)
    result = text_of(invoke(world))
    passed, failed, unrun = "\N{CHECK MARK}", "\N{BALLOT X}", "\N{EN DASH}"
    assert [match.group(1) for match in _ROW.finditer(result)] == [
        *[passed] * 4,
        failed,
        *[unrun] * 4,
    ]
    assert result.endswith(
        "図は検証に合格しなかったので、画像は表示していない。"
        "理由は「棒グラフ、ヒストグラム、面グラフの値の軸にゼロが含まれていません。」"
        "(zero_not_in_limits)。"
        "次の手: 依頼が図の規則に反していなければ、理由と上のチェック項目に沿って"
        "プログラムを直し、draw_figure を呼び直す (呼び直しは 2 回まで)。"
        "依頼そのものが規則に反するなら、規則に沿った図を描き、note に依頼との違いを書く。"
        "直せないときは、図が表示されなかったことと理由をユーザーに伝える。"
    )


def _capped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cap: int) -> str:
    world = World(root=tmp_path / str(cap), result_cap=cap)
    world.root.mkdir()
    install(monkeypatch, world)
    world.program = TRUNCATED
    _sales_chat(world)
    return text_of(invoke(world))


def test_q82_t12_the_result_fits_the_server_s_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """nucllei cuts a result past `TOOL_RESULT_MAX_CHARS` (an admin can lower it) and drops its
    render: the listings go first, then the rows; the cause and the model's tail always stay."""
    full = _capped(tmp_path, monkeypatch, 65_536)
    assert "ax.set_ylim(80, 130)" in full
    lowered = _capped(tmp_path, monkeypatch, len(full) + 511)
    assert len(lowered) < len(full)
    assert len(_ROW.findall(lowered)) == 9
    assert "ax.set_ylim(80, 130)" not in lowered
    tiny = _capped(tmp_path, monkeypatch, 2_000)
    assert _ROW.findall(tiny) == []
    for result in (full, lowered, tiny):
        assert result.endswith("ユーザーに伝える。")
        assert "(zero_not_in_limits)。" in result


# --- T13 totality -------------------------------------------------------------------------------


def test_q82_t13_a_judge_fault_fails_closed(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    world.program = HONEST
    _sales_chat(world)

    def boom(*_: object) -> object:
        raise RuntimeError

    monkeypatch.setattr("nucllei_skill.tool.judge", boom)
    text = text_of(invoke(world))
    assert "(verifier_error)" in _shown(world)
    assert world.marks == ["fatal"]
    assert text.endswith("次の手: 呼び直さない。図を表示できなかったことをユーザーに伝える。")


def test_q82_t13_cancellation_propagates(world: World) -> None:
    world.program = HONEST
    world.reply = asyncio.CancelledError()
    _sales_chat(world)
    with pytest.raises(asyncio.CancelledError):
        invoke(world)


# --- T15 note -----------------------------------------------------------------------------------


def test_q82_t15_the_note_is_shown_and_read_by_nothing(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    world.program = TRUNCATED
    note = "You asked for an axis from 80; the chart starts at zero. [x](http://e)"
    _sales_chat(world)
    with caplog.at_level(logging.DEBUG):
        result = text_of(invoke(world, note=note))
    assert "80; the chart" not in str(world.calls)
    assert "80; the chart" not in result
    assert all("80; the chart" not in record.getMessage() for record in caplog.records)
    assert _shown(world).endswith(
        "\n\n**Model note:** You asked for an axis from 80\\; the chart starts at zero\\."
        " [x\\](http\\:\\/\\/e\\)"
    )


def test_q82_t15_the_switch_off_hides_the_note(world: World) -> None:
    world.program = HONEST
    _sales_chat(world)
    invoke(world, note="hidden", valves={"model_note": False})
    assert "hidden" not in _shown(world)


# --- T16 language -------------------------------------------------------------------------------


def test_q82_t16_a_japanese_request_reads_one_language_and_the_tail_stays_japanese(
    world: World,
) -> None:
    world.program = TRUNCATED
    _sales_chat(world, REQUEST_JA)
    result = text_of(invoke(world))
    assert _shown(world).startswith(FAIL_JA)
    assert "**チェック項目**" in result
    assert "**✗ 正しい軸**  " in result
    world.displays.clear()
    world.program = HONEST
    world.chats[(CHAT_ID, USER_ID)] = history(
        {"role": "user", "content": REQUEST, "files": [ref("f1", "sales.csv")]}
    )
    english = text_of(invoke(world))
    assert "**Checks**" in english
    assert english.endswith(OK_TAIL)
