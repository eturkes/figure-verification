# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The "Show checks" breakdown: every check a figure faces, as one self-contained HTML document.

Data plus one pure renderer; `filter.py` sends the document as an Open WebUI message embed, which
the chat renders in a sandboxed iframe and never sends to a model. Every text slot comes from the
tables here or from `REASONS`, so no program, request, file or sandbox byte reaches the user.

A check shows as passed only when it completed, so each reason maps to the EARLIEST check that can
raise it: admission raises `column_not_literal` before projection could raise its own copy.
"""

import html
from typing import Final, Literal

from verifier.pysrc.spec import Anchoring
from webui.paste_in.reasons import REASONS, Reason

Check = Literal[
    "program",
    "data",
    "readable",
    "accepted",
    "chart",
    "binding",
    "recompute",
    "integrity",
    "render",
    "match",
    "attach",
]
type _State = Literal["pass", "fail", "skip"]

CHECKS: Final[tuple[Check, ...]] = (
    "program",
    "data",
    "readable",
    "accepted",
    "chart",
    "binding",
    "recompute",
    "integrity",
    "render",
    "match",
    "attach",
)

_REASONS_OF: Final[dict[Check, tuple[Reason, ...]]] = {
    "program": ("no_tool_call",),
    "data": ("no_user", "no_target"),
    "readable": (
        "source_too_large",
        "source_not_utf8",
        "source_has_nul",
        "line_too_long",
        "source_not_tokenizable",
        "too_many_tokens",
        "nesting_too_deep",
        "unbalanced_brackets",
        "indent_too_deep",
        "source_not_parsable",
    ),
    "accepted": (
        "statement_not_admitted",
        "expression_not_admitted",
        "import_not_admitted",
        "assign_target_not_admitted",
        "call_target_not_admitted",
        "keyword_not_admitted",
        "attribute_not_admitted",
        "operator_not_admitted",
        "literal_not_admitted",
        "name_not_bound",
        "column_not_literal",
    ),
    "chart": (
        "no_mark",
        "multiple_marks",
        "mark_arity_not_projected",
        "mark_not_valid_for_arm",
        "x_not_a_grid",
        "y_not_over_grid",
        "grid_not_representable",
        "expression_not_projected",
        "label_not_literal",
        "name_rebound",
        "no_terminal",
        "statement_after_terminal",
        "statement_not_projected",
        "arm_ambiguous",
        "no_source",
        "multiple_sources",
        "source_not_literal",
        "column_not_from_source",
        "aggregation_not_projected",
        "figure_orphans_mark",
    ),
    "binding": (
        "source_not_supplied",
        "target_mismatch",
        "column_not_requested",
        "column_not_named",
    ),
    "recompute": (
        "csv_too_large",
        "csv_not_parsable",
        "column_not_present",
        "column_not_numeric",
        "value_not_in_profile",
        "value_not_finite",
        "work_budget_exceeded",
    ),
    "integrity": ("category_not_unique", "x_not_ordered", "label_not_consistent"),
    "render": (
        "no_browser",
        "browser_timeout",
        "browser_error",
        "browser_no_answer",
        "reply_malformed",
        "sandbox_unavailable",
        "sandbox_error",
        "no_image",
    ),
    "match": ("no_observation", "observation_mismatch"),
    "attach": ("publish_failed",),
}
CHECK_OF: Final[dict[Reason, Check]] = {
    reason: check for check, reasons in _REASONS_OF.items() for reason in reasons
}

# check -> ((EN title, EN covers), (JA title, JA covers)).
TEXTS: Final[dict[Check, tuple[tuple[str, str], tuple[str, str]]]] = {
    "program": (
        ("Chart program received from the model", "one program, sent through the chart tool"),
        ("モデルからグラフのプログラムを受信", "グラフ用のツールで送られた 1 つのプログラム"),
    ),
    "data": (
        (
            "An attached file or a formula in your request",
            "your uploaded file, or one formula and one interval in your request",
        ),
        (
            "添付ファイルまたは依頼文の数式",
            "アップロードしたファイル、または依頼文にある 1 つの数式と 1 つの区間",
        ),
    ),
    "readable": (
        (
            "Readable Python",
            "size, text encoding, line length, tokens, brackets, indentation, syntax",
        ),
        (
            "Python として読み取り可能",
            "サイズ、文字コード、行の長さ、トークン、括弧、インデント、構文",
        ),
    ),
    "accepted": (
        (
            "Accepted Python only",
            "statements, imports, function calls, arguments, attributes, operators,"
            " literal values, fixed column names, defined names",
        ),
        (
            "検証器が受け入れる Python のみ使用",
            "文、import、関数呼び出し、引数、属性、演算子、リテラル値、固定の列名、定義済みの名前",
        ),
    ),
    "chart": (
        (
            "Chart read from the program",
            "one plot call of x and y, one CSV read or one formula grid, columns from that CSV,"
            " labels, plt.show() last",
        ),
        (
            "プログラムからグラフを読み取り可能",
            "x と y の描画呼び出し 1 つ、CSV の読み込み 1 回または数式のグリッド 1 つ、"
            "その CSV の列、ラベル、最後の plt.show()",
        ),
    ),
    "binding": (
        (
            "Program matches your file or formula",
            "it reads your attached file without swapping a column your request names, if the"
            " verifier recognizes the name, or it plots your requested formula",
        ),
        (
            "プログラムが添付ファイルまたは依頼の数式と一致",
            "添付ファイルを読み込み、依頼にある列名のうち検証器が認識した列を"
            "別の列に置き換えていないこと、"
            "または依頼した数式を描くこと",
        ),
    ),
    "recompute": (
        (
            "Plotted values recomputed from your data",
            "file readable, columns present, y numeric, x numeric or categories, values in"
            " accepted form and size, results finite, computation within the limit",
        ),
        (
            "描画する値をデータから再計算",
            "ファイルの読み取り、列の有無、y は数値、x は数値またはカテゴリ、値の形式と大きさ、"
            "結果が有限、計算量の上限",
        ),
    ),
    "integrity": (
        (
            "Chart integrity",
            "bars from zero, one set of axes, linear scales, no row dropped, no repeated"
            " category, ordered line x, no label naming another recognized file column",
        ),
        (
            "グラフの完全性",
            "棒はゼロから、軸は 1 組、線形の目盛り、行の欠落なし、カテゴリの重複なし、"
            "折れ線の x は減少しないかファイルの順序どおり、"
            "ラベルは検証器が認識したファイルの列名のうち、描いていない列名を挙げない",
        ),
    ),
    "render": (
        (
            "Chart drawn in your browser",
            "the program runs in your browser and returns one PNG image",
        ),
        ("ブラウザでグラフを描画", "プログラムをブラウザで実行し、PNG 画像を 1 枚返す"),
    ),
    "match": (
        (
            "Drawn values checked against recomputed values",
            "the values the browser reports drawing: file values equal exactly, formula values"
            " stay within the checked numerical bounds",
        ),
        (
            "描画された値を再計算した値と照合",
            "ブラウザが報告した描画値。ファイルの値は完全に一致し、"
            "数式の値は定めた数値誤差の範囲内",
        ),
    ),
    "attach": (
        ("Image attached to the reply", "the chart image is stored with this reply"),
        ("返信に画像を添付", "グラフの画像をこの返信と一緒に保存"),
    ),
}
# The binding row under production's strict anchoring (Q37); TEXTS holds the demo's rule.
STRICT_BINDING: Final[tuple[tuple[str, str], tuple[str, str]]] = (
    (
        "Program matches your file or formula",
        "it reads your attached file, your request names each drawn column the verifier"
        " recognizes if it names any column, or it plots your requested formula",
    ),
    (
        "プログラムが添付ファイルまたは依頼の数式と一致",
        "添付ファイルを読み込み、依頼が列名を含む場合は、描く列のうち検証器が認識できる列が"
        "すべて依頼にあること、または依頼した数式を描くこと",
    ),
)

# (EN, JA) per UI word.
SHOW: Final = ("Show checks", "チェック項目を表示")
HIDE: Final = ("Hide checks", "チェック項目を隠す")
UNRUN: Final = ("not checked", "未実施")
MARKS: Final[dict[_State, tuple[str, tuple[str, str]]]] = {
    "pass": ("\N{CHECK MARK}", ("passed", "合格")),
    "fail": ("\N{BALLOT X}", ("failed", "不合格")),
    "skip": ("\N{EN DASH}", UNRUN),
}

# The frame cannot see Open WebUI's theme class, so every colour is a mid tone that reads on the
# light and the dark theme alike; a `prefers-color-scheme` rule would pick the wrong extreme when
# the theme and the OS disagree.
_STYLE = (
    "body{margin:0;color:#7d7d7d;font:14px/1.45 ui-sans-serif,system-ui,-apple-system,"
    '"Segoe UI",Roboto,"Noto Sans JP","Hiragino Sans",sans-serif}'
    "#r{padding:2px 0}"
    "summary{cursor:pointer;width:max-content;user-select:none}"
    "details[open] .show,details:not([open]) .hide{display:none}"
    "ol{list-style:none;margin:6px 0 0;padding:0}"
    "li{display:flex;gap:8px;padding:3px 0}"
    ".mark{flex:none;width:1.1em;text-align:center;font-weight:700}"
    ".pass .mark{color:#2a9354}"
    ".fail .mark,.cause{color:#d64541}"
    ".title{font-weight:500}"
    ".covers,.unrun{font-size:12.5px}"
    ".skip{opacity:.7}"
)
# Open WebUI sizes an embed only from the frame's own `iframe:height` message, since the sandbox
# denies it access to the frame's document.
_HEIGHT_SCRIPT = (
    'const r=document.getElementById("r");'
    "new ResizeObserver(()=>parent.postMessage("
    '{type:"iframe:height",height:Math.ceil(r.getBoundingClientRect().height)},"*")'
    ").observe(r);"
)


def _text(value: str) -> str:
    return html.escape(value, quote=True)


def breakdown_html(reason: Reason | None, *, japanese: bool, anchoring: Anchoring) -> str:
    """Render every check for one reply: passed, the failing one with its cause, the unrun rest.

    `reason` is the failure reason, or `None` for a published figure, whose checks all passed;
    `anchoring` picks the binding row's text, so each artifact describes the rule it runs.
    """
    language = 1 if japanese else 0
    failing = len(CHECKS) if reason is None else CHECKS.index(CHECK_OF[reason])
    cause = "" if reason is None else REASONS[reason][language]
    rows: list[str] = []
    for index, check in enumerate(CHECKS):
        state: _State = "pass" if index < failing else "fail" if index == failing else "skip"
        glyph, labels = MARKS[state]
        texts = STRICT_BINDING if check == "binding" and anchoring == "strict" else TEXTS[check]
        title, covers = texts[language]
        unrun = f' <span class="unrun">{_text(UNRUN[language])}</span>' if state == "skip" else ""
        detail = f'<div class="covers">{_text(covers)}</div>'
        if state == "fail":
            detail += f'<div class="cause">{_text(cause)}</div>'
        rows.append(
            f'<li class="{state}"><span class="mark" role="img"'
            f' aria-label="{_text(labels[language])}">{glyph}</span>'
            f'<div><div class="title">{_text(title)}{unrun}</div>{detail}</div></li>'
        )
    return (
        f'<!DOCTYPE html><html lang="{"ja" if japanese else "en"}"><head><meta charset="utf-8">'
        f'<style>{_STYLE}</style></head><body><div id="r"><details><summary>'
        f'<span class="show">{_text(SHOW[language])}</span>'
        f'<span class="hide">{_text(HIDE[language])}</span></summary>'
        f"<ol>{''.join(rows)}</ol></details></div><script>{_HEIGHT_SCRIPT}</script></body></html>"
    )
