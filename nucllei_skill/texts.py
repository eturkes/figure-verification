# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The words of the nucllei tool: what the model reads, what the user sees, what the admin sets.

Model-facing text is Japanese (Q82 ruling 7) and follows nucllei's result contract (README_API
§5.1): a fact sentence a user may read, then `次の手:` and the model-only part; plain style, no
internal names, and only tools of this toolkit named. The check list above it follows the kana
rule like the rest of the reply (Q81).
"""

from typing import Final, Literal, TypeAlias

from nucllei_skill.reasons import Reason

Next: TypeAlias = Literal["fix", "retry", "stop"]

# What the model reads after a pass; the user already sees the verdict + image + interpretation.
PASSED: Final = (
    "図は検証に合格し、画像と判定と解釈をユーザーの画面に表示した。"
    "次の手: 画像を本文に貼り直さない。合否を言い直さず、上のチェック項目も本文に写さない。"
    "図が示す内容を本文で短く説明する。"
)
FAILED: Final = "図は検証に合格しなかったので、画像は表示していない。理由は「{cause}」({reason})。"
NEXT: Final[dict[Next, str]] = {
    "fix": (
        "次の手: 依頼が図の規則に反していなければ、理由と上のチェック項目に沿って"
        "プログラムを直し、draw_figure を呼び直す (呼び直しは 2 回まで)。"
        "依頼そのものが規則に反するなら、規則に沿った図を描き、note に依頼との違いを書く。"
        "直せないときは、図が表示されなかったことと理由をユーザーに伝える。"
    ),
    "retry": (
        "次の手: draw_figure を 1 回だけ呼び直す。"
        "続くなら、図を表示できないことをユーザーに伝える。"
    ),
    "stop": "次の手: 呼び直さない。図を表示できなかったことをユーザーに伝える。",
}
# Who can fix a block (README_API §5.1): `failure` = the context or the sandbox (a runtime failure),
# `fatal` = the protocol, the store or the verifier itself (a fault no call fixes), `call` = the
# program the model wrote.
_FAILURES: Final[frozenset[Reason]] = frozenset(
    {"no_user", "delegated_session", "sandbox_unreachable", "sandbox_timeout", "sandbox_error"}
)
_FATAL: Final[frozenset[Reason]] = frozenset(
    {"reply_malformed", "no_description", "no_image", "publish_failed", "verifier_error"}
)
_RETRIED: Final[frozenset[Reason]] = frozenset(
    {"sandbox_unreachable", "sandbox_timeout", "sandbox_error"}
)


def error_kind(reason: Reason) -> Literal["call", "failure", "fatal"]:
    """nucllei's flag for the blocked call's result."""
    if reason in _FATAL:
        return "fatal"
    return "failure" if reason in _FAILURES else "call"


def next_step(reason: Reason) -> Next:
    """What the model may do after this block: fix its program, retry the sandbox once, or stop."""
    if reason in _RETRIED:
        return "retry"
    return "fix" if error_kind(reason) == "call" else "stop"


# The published image's text alternative, (EN, JA).
IMAGE_ALT: Final = ("Verified chart", "検証済みのグラフ")

# The tool row an administrator reads in the workspace (llens `sync.py` reads these two lines).
TOOL_TITLE: Final = "Figure Verification"
TOOL_DESCRIPTION: Final = "グラフを描くプログラムを実行し、検証に合格した図だけを表示します。"
ALIASES_DESCRIPTION: Final = (
    "CSV の列の別名です。1 行に 1 列ずつ「列名 = 別名, 別名」の形で書きます。"
    "依頼文やグラフのラベルに別名があると、その列を指したものとして扱います。"
)
NOTE_TITLE: Final = "モデルの注記"
NOTE_DESCRIPTION: Final = (
    "依頼が図の規則に反するとき、モデルにその内容を注記として書かせ、判定の下に表示します。"
    "検証器は注記の内容をチェックしません。"
)
