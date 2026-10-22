# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Why a figure failed on nucllei: the shared figure reasons plus the tool's own causes.

Data only. A cause is a fault the tool finds around the judge: the caller, the sandbox round trip,
the image, or a fault while decoding or judging. Each text is one cause sentence, which the reply
shows beside the failure verdict and the check list shows on the failing row.
"""

from typing import Final, Literal, TypeAlias, cast, get_args

from verifier.figure.reasons import FigureReason
from webui.paste_in.reasons import REASONS as SHARED

ToolCause = Literal[
    "no_user",
    "delegated_session",
    "sandbox_unreachable",
    "sandbox_timeout",
    "sandbox_error",
    "reply_malformed",
    "no_description",
    "no_image",
    "publish_failed",
    "verifier_error",
]

Reason: TypeAlias = FigureReason | ToolCause

# The program's run budget in the jail; the sandbox clamps it to its own maximum.
RUN_TIMEOUT_SECONDS: Final = 120

_OWN: Final[dict[Reason, tuple[str, str]]] = {
    "delegated_session": (
        "The chart was asked for in a delegated session, which does not show it to you.",
        "グラフの依頼が、あなたに表示されない委任先のセッションから来ました。",
    ),
    "sandbox_unreachable": (
        "The verifier could not reach the code sandbox.",
        "検証器がコード実行のサンドボックスに接続できませんでした。",
    ),
    "sandbox_timeout": (
        f"The program did not finish within {RUN_TIMEOUT_SECONDS} seconds.",
        f"プログラムが {RUN_TIMEOUT_SECONDS} 秒以内に終了しませんでした。",
    ),
    "sandbox_error": (
        "The code sandbox reported an error.",
        "コード実行のサンドボックスがエラーを報告しました。",
    ),
    "reply_malformed": (
        "The code sandbox sent a reply that is cut short or in an unknown format.",
        "コード実行のサンドボックスの応答が途中で切れているか、形式が不明です。",
    ),
    "no_description": (
        "The sandbox run did not report the drawn figure.",
        "サンドボックスでの実行が、描画した図を報告しませんでした。",
    ),
    "module_not_available": (
        "The program imports a module that the code sandbox does not have.",
        "プログラムが、コード実行のサンドボックスにないモジュールを読み込んでいます。",
    ),
    "no_image": (
        "The sandbox run did not produce exactly one PNG image.",
        "サンドボックスでの実行で PNG 画像が 1 枚だけ作られませんでした。",
    ),
    "publish_failed": (
        "The server could not save or show the image.",
        "サーバーが画像を保存または表示できませんでした。",
    ),
}

# reason -> (English, Japanese): the tool's own causes, `no_user` + `verifier_error` and every
# figure reason with the shared text, `module_not_available` with the sandbox's.
REASONS: Final[dict[Reason, tuple[str, str]]] = {
    **{cast("Reason", reason): SHARED[reason] for reason in (*get_args(FigureReason), "no_user")},
    "verifier_error": SHARED["verifier_error"],
    **_OWN,
}
