# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The "Show checks" breakdown: every check a figure faces, as one self-contained HTML document.

Data plus one pure renderer; `filter.py` sends the document as an Open WebUI message embed, which
the chat renders in a sandboxed iframe and never sends to a model. Each row opens to what its check
does, the program lines it read, why it failed and a link to its section of the reference. Every
text slot comes from the tables here or from `REASONS`; the one exception is the program itself,
quoted escaped inside a code listing with whatever it spells. Request text, file contents and
sandbox output are never added from any other source.

A check shows as passed only when it completed, so each reason maps to the EARLIEST check that can
raise it: admission raises `column_not_literal` before projection could raise its own copy.
"""

import html
import itertools
import re
import unicodedata
from dataclasses import dataclass
from typing import Final, Literal

from verifier.pysrc.position import Role, Span, Trace
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

# check -> (EN, JA): what the check does, shown when its row is opened.
EXPLAIN: Final[dict[Check, tuple[str, str]]] = {
    "program": (
        "The model must send its chart program through the chart tool. The verifier checks the"
        " last program sent in this reply.",
        "モデルはグラフのプログラムをグラフ用のツールで送る必要があります。"
        "検証器は、この返信で最後に送られたプログラムをチェックします。",
    ),
    "data": (
        "The verifier needs data that you supplied. This is a CSV file attached to the chat, or"
        " one formula and one interval in your request.",
        "検証器には、あなたが用意したデータが必要です。"
        "チャットに添付した CSV ファイル、または依頼文にある 1 つの数式と 1 つの区間です。",
    ),
    "readable": (
        "The verifier reads the program as Python text before it examines it. It checks the size,"
        " text encoding, line length, tokens, brackets and indentation, then parses the syntax.",
        "検証器は、内容を調べる前にプログラムを Python のテキストとして読み取ります。"
        "サイズ、文字コード、行の長さ、トークン、括弧、インデントを確認してから、構文を解析します。",
    ),
    "accepted": (
        "The verifier accepts only a fixed set of Python statements, imports, function calls and"
        " arguments. Anything outside that set stops the check, also when Python could run it.",
        "検証器が受け入れるのは、決まった範囲の Python の文、import、関数呼び出し、引数だけです。"
        "その範囲の外にあるものは、Python で実行できる場合でもチェックを止めます。",
    ),
    "chart": (
        "The verifier reads which chart the program draws: one data source, one plot call, the"
        " labels, and plt.show() at the end. Every statement must contribute to that chart.",
        "検証器は、プログラムが描くグラフを読み取ります。"
        "データの読み込み 1 つ、描画呼び出し 1 つ、ラベル、最後の plt.show() です。"
        "すべての文がそのグラフに関係する必要があります。",
    ),
    "binding": (
        "The verifier checks that the program uses your data: it reads your attached file, or it"
        " plots the formula in your request. Column names in your request are compared with the"
        " columns that the chart draws.",
        "検証器は、プログラムがあなたのデータを使うことを確認します。"
        "添付ファイルを読み込むこと、または依頼文の数式を描くことです。"
        "依頼文にある列名は、グラフが描く列と比べます。",
    ),
    "recompute": (
        "The verifier computes every plotted value again from your file or formula, with its own"
        " code. Then it checks that each result is a finite number within the limits.",
        "検証器は、描画するすべての値を、ファイルまたは数式から独自のコードで計算し直します。"
        "その後、各結果が上限内の有限の数であることを確認します。",
    ),
    "integrity": (
        "The verifier checks rules that keep the chart honest. Bars start at zero, there is one"
        " set of axes with linear scales, and no row is left out. Categories do not repeat, and"
        " line x values are in order. A label must not name another file column that the"
        " verifier recognizes.",
        "検証器は、グラフを正しく見せるための規則を確認します。"
        "棒はゼロから始まり、軸は 1 組で目盛りは線形、行の欠落はありません。"
        "カテゴリは重複せず、折れ線の x の値は順序どおりです。"
        "ラベルは、検証器が認識できるファイルの列名のうち、グラフが描かない列名を挙げてはいけません。",
    ),
    "render": (
        "Your browser runs the model's program, unchanged, in the Open WebUI sandbox. The run must"
        " return one PNG image and the values that it drew.",
        "ブラウザは、モデルのプログラムを変更せずに Open WebUI のサンドボックスで実行します。"
        "実行結果として、PNG 画像 1 枚と描画した値を返す必要があります。",
    ),
    "match": (
        "The verifier compares the values that the browser drew with the values that it computed."
        " File values must be equal. Formula values must stay within the checked numerical"
        " bounds.",
        "検証器は、ブラウザが描画した値と、検証器が計算した値を比べます。"
        "ファイルの値は完全に一致する必要があります。"
        "数式の値は、定めた数値誤差の範囲内である必要があります。",
    ),
    "attach": (
        "The chart image is stored with this reply. If storing fails, the verifier shows no image.",
        "グラフの画像をこの返信と一緒に保存します。保存できない場合、検証器は画像を表示しません。",
    ),
}
WHAT: Final = ("What this check does", "このチェックの内容")
CODE: Final = ("Code checked", "チェックしたコード")
WHY: Final = ("Why it failed", "不合格の理由")
NOT_RUN: Final = (
    "This check did not run, because an earlier check failed.",
    "前のチェックが不合格だったため、このチェックは実施していません。",
)
STOPPED: Final = (
    "The check stopped at the marked code.",
    "印の付いたコードでチェックが止まりました。",
)
SPEC: Final = ("Read the full specification of this check", "このチェックの詳しい仕様を読む")
ELIDED: Final = ("Lines not shown: {n}.", "表示していない行: {n} 行。")
BEYOND: Final = (
    "The program is too long to show in full.",
    "プログラムが長すぎるため、すべては表示できません。",
)
# The python-mode reference on GitHub, one section per check (`#check-<id>`). A fixed link: the
# instance may have no network, but the browser a user reads it in does (user ruling, M18).
SPECIFICATION: Final = (
    "https://github.com/eturkes/figure-verification/blob/main/docs/verification.md",
    "https://github.com/eturkes/figure-verification/blob/main/docs/verification.ja.md",
)

# Which program lines each check reads: every line, the statements of these roles, or none.
# A check after projection reads the spec, not the source, so its lines are the statements that
# spec came from: related code, marked only where the core's `at` points at a genuine location.
CODE_ROLES: Final[dict[Check, tuple[Role, ...] | Literal["all"] | None]] = {
    "program": "all",
    "data": None,
    "readable": "all",
    "accepted": "all",
    "chart": "all",
    "binding": ("source", "data", "mark"),
    "recompute": ("source", "data", "mark"),
    "integrity": ("data", "mark", "title", "xlabel", "ylabel"),
    "render": "all",
    "match": ("mark",),
    "attach": None,
}


@dataclass(frozen=True, slots=True)
class Evidence:
    """What the outlet holds about one reply's program: its text, where a refusal points, and the
    role of each statement. Empty = no program reached the verifier."""

    program: str | None = None
    at: tuple[Span, ...] = ()
    trace: Trace = ()


# The frame cannot see Open WebUI's theme class, so every colour is a mid tone that reads on the
# light and the dark theme alike; a `prefers-color-scheme` rule would pick the wrong extreme when
# the theme and the OS disagree.
_STYLE = (
    "body{margin:0;color:#7d7d7d;font:14px/1.45 ui-sans-serif,system-ui,-apple-system,"
    '"Segoe UI",Roboto,"Noto Sans JP","Hiragino Sans",sans-serif}'
    "#r{padding:2px 0}"
    "#r>details>summary{cursor:pointer;width:max-content;user-select:none}"
    "#r>details[open]>summary .show,#r>details:not([open])>summary .hide{display:none}"
    "ol{list-style:none;margin:6px 0 0;padding:0}"
    "li{padding:3px 0}"
    ".row>summary{display:flex;gap:8px;cursor:pointer;list-style:none}"
    ".row>summary::before{content:'\\25B8';flex:none;width:.8em}"
    ".row[open]>summary::before{content:'\\25BE'}"
    ".mark{flex:none;width:1.1em;text-align:center;font-weight:700}"
    ".pass .mark{color:#2a9354}"
    ".fail .mark,.cause{color:#d64541}"
    ".title{font-weight:500}"
    ".covers,.unrun,.more{font-size:12.5px}"
    ".skip{opacity:.7}"
    ".more{margin:2px 0 8px 2.6em}"
    ".more p{margin:2px 0}"
    ".label{display:block;font-weight:600;margin-top:6px}"
    ".listing{margin:4px 0;padding:6px 8px;border-radius:6px;background:rgba(125,125,125,.12);"
    'font:12px/1.5 ui-monospace,Menlo,Consolas,"Noto Sans Mono CJK JP",monospace;'
    "white-space:pre-wrap;overflow-wrap:anywhere}"
    ".line,.gap{display:block}"
    ".ln{display:inline-block;min-width:2.4em;padding-right:8px;text-align:right;opacity:.7;"
    "user-select:none}"
    ".at{background:rgba(214,69,65,.14)}"
    "mark{background:rgba(214,69,65,.38);color:inherit;border-radius:2px}"
    "a.spec{color:#3d8bd9}"
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


# A listing reads at most this much of the program, so a huge receipt costs bounded work; past it,
# the row says the program is not shown in full.
_SCAN = 65_536
_MAX_LINES = 60
_MAX_CHARACTERS = 3_000
_LINE_CHARACTERS = 400
_CONTEXT = 2
_BREAK = re.compile(r"\r\n|\r|\n")
_HIDDEN = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
# Open WebUI injects Alpine.js or Chart.js into an embed whose raw text holds `x-<directive>`,
# `new Chart(` or `Chart.` (same-origin frames). Character references keep the program from
# spelling one, or a resource reference (`src=`, `url(`, `@import`, `https:`) a static check could
# mistake for a load; the browser shows the same characters.
_TRIGGER_SAFE = str.maketrans(
    {"-": "&#45;", ".": "&#46;", "(": "&#40;", ":": "&#58;", "=": "&#61;", "@": "&#64;"}
)


def _visible(character: str) -> str:
    """A character that would draw nothing, or reorder the text around it, as a visible symbol."""
    if character == "\t" or unicodedata.category(character) not in _HIDDEN:
        return character
    code = ord(character)
    if code < 0x20:  # noqa: PLR2004 - the C0 controls map onto U+2400-U+241F
        return chr(0x2400 + code)
    return "\N{SYMBOL FOR DELETE}" if code == 0x7F else "\N{REPLACEMENT CHARACTER}"  # noqa: PLR2004


def _code(value: str) -> str:
    return _text("".join(map(_visible, value))).translate(_TRIGGER_SAFE)


def _character(line: str, column: int) -> int:
    """The character index at UTF-8 byte offset `column` of `line` (the `Span` convention)."""
    width = 0
    for index, character in enumerate(line):
        if width >= column:
            return index
        width += len(character.encode("utf-8", "surrogatepass"))
    return len(line)


def _numbers(span: Span, count: int) -> range:
    return range(max(span.line, 1), min(span.end_line, count) + 1)


def _marked(lines: list[str], at: tuple[Span, ...]) -> dict[int, set[int]]:
    """Line number -> the shown character indices the spans cover; a point covers none."""
    marked: dict[int, set[int]] = {}
    for span in at:
        for number in _numbers(span, len(lines)):
            line = lines[number - 1]
            start = _character(line, span.column) if number == span.line else 0
            end = _character(line, span.end_column) if number == span.end_line else len(line)
            marked.setdefault(number, set()).update(range(start, min(end, _LINE_CHARACTERS)))
    return marked


def _line(number: int, line: str, marks: set[int] | None) -> str:
    shown = line[:_LINE_CHARACTERS]
    pieces: list[str] = []
    for inside, run in itertools.groupby(
        range(len(shown)), key=lambda index: index in (marks or ())
    ):
        indices = list(run)
        text = _code(shown[indices[0] : indices[-1] + 1])
        pieces.append(f"<mark>{text}</mark>" if inside else text)
    if len(line) > _LINE_CHARACTERS:
        pieces.append("\N{HORIZONTAL ELLIPSIS}")
    kind = "line" if marks is None else "line at"
    return (
        f'<span class="{kind}"><span class="ln">{number}</span>'
        f'<span class="src">{"".join(pieces)}</span></span>'
    )


@dataclass(frozen=True, slots=True)
class _Quoted:
    """The program as the rows quote it: its scanned lines, whether the scan cut it, and where."""

    lines: list[str]
    cut: bool
    at: tuple[Span, ...]
    trace: Trace


def _quoted(evidence: Evidence) -> _Quoted | None:
    program = evidence.program
    if program is None:
        return None
    return _Quoted(_BREAK.split(program[:_SCAN]), len(program) > _SCAN, evidence.at, evidence.trace)


def _listing(
    quoted: _Quoted, selected: set[int], at: tuple[Span, ...], language: int
) -> tuple[str, bool]:
    """The selected lines within the caps, refused spans marked; and whether a mark is shown."""
    lines = quoted.lines
    chosen = sorted(selected)
    marked = {number: marks for number, marks in _marked(lines, at).items() if number in selected}
    # A set, not a scan per marked line: a refusal can span thousands of lines (reviewer-2 K5-F1).
    around = {m + d for m in marked for d in range(-_CONTEXT, _CONTEXT + 1)}
    near = [n for n in chosen if n in around]
    taken: set[int] = set()
    cost = 0
    for number in (*sorted(marked), *near, *chosen):
        weight = min(len(lines[number - 1]), _LINE_CHARACTERS)
        if number in taken or len(taken) == _MAX_LINES or cost + weight > _MAX_CHARACTERS:
            continue
        taken.add(number)
        cost += weight
    rows: list[str] = []
    for number in sorted(taken):
        if rows and number - 1 not in taken:
            rows.append('<span class="gap">\N{VERTICAL ELLIPSIS}</span>')
        rows.append(_line(number, lines[number - 1], marked.get(number)))
    listing = f'<pre class="listing">{"".join(rows)}</pre>'
    if len(chosen) > len(taken):
        elided = ELIDED[language].format(n=len(chosen) - len(taken))
        listing += f'<p class="elided">{_text(elided)}</p>'
    if quoted.cut:
        listing += f'<p class="beyond">{_text(BEYOND[language])}</p>'
    return listing, any(number in marked for number in taken)


def _selected(check: Check, quoted: _Quoted, *, failing: bool) -> set[int]:
    roles = CODE_ROLES[check]
    count = len(quoted.lines)
    if roles is None:
        return set()
    if roles == "all":
        numbers = set(range(1, count + 1))
    else:
        numbers = {
            n for step in quoted.trace if step.role in roles for n in _numbers(step.span, count)
        }
    if failing:
        numbers.update(n for span in quoted.at for n in _numbers(span, count))
    return numbers


def _section(kind: str, label: str, body: str) -> str:
    return f'<div class="{kind}"><span class="label">{_text(label)}</span>{body}</div>'


def _more(
    check: Check, state: _State, reason: Reason | None, language: int, quoted: _Quoted | None
) -> str:
    """The opened row: what the check does, whether it ran, the code it read, why, the link."""
    sections = [_section("what", WHAT[language], f"<p>{_text(EXPLAIN[check][language])}</p>")]
    if state == "skip":
        sections.append(f'<div class="unrun-note"><p>{_text(NOT_RUN[language])}</p></div>')
    stopped = False
    if state != "skip" and quoted is not None:
        selected = _selected(check, quoted, failing=state == "fail")
        if selected:
            at = quoted.at if state == "fail" else ()
            listing, stopped = _listing(quoted, selected, at, language)
            sections.append(_section("code", CODE[language], listing))
    if reason is not None and state == "fail":
        why = f"<p>{_text(f'{REASONS[reason][language]} ({reason})')}</p>"
        if stopped:
            why += f'<p class="stopped">{_text(STOPPED[language])}</p>'
        sections.append(_section("why", WHY[language], why))
    href = _code(f"{SPECIFICATION[language]}#check-{check}")
    sections.append(
        f'<p class="link"><a class="spec" href="{href}" target="_blank"'
        f' rel="noopener noreferrer">{_text(SPEC[language])}</a></p>'
    )
    return f'<div class="more">{"".join(sections)}</div>'


def breakdown_html(
    reason: Reason | None,
    *,
    japanese: bool,
    anchoring: Anchoring,
    evidence: Evidence = Evidence(),  # noqa: B008 - frozen, so one shared default is safe
) -> str:
    """Render every check for one reply: passed, the failing one with its cause, the unrun rest.

    `reason` is the failure reason, or `None` for a published figure, whose checks all passed;
    `anchoring` picks the binding row's text, so each artifact describes the rule it runs;
    `evidence` = the program + its positions, quoted in each row that read it.
    """
    language = 1 if japanese else 0
    failing = len(CHECKS) if reason is None else CHECKS.index(CHECK_OF[reason])
    cause = "" if reason is None else REASONS[reason][language]
    quoted = _quoted(evidence)
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
            f'<li class="{state}"><details class="row"><summary><span class="mark" role="img"'
            f' aria-label="{_text(labels[language])}">{glyph}</span>'
            f'<div><div class="title">{_text(title)}{unrun}</div>{detail}</div></summary>'
            f"{_more(check, state, reason, language, quoted)}</details></li>"
        )
    return (
        f'<!DOCTYPE html><html lang="{"ja" if japanese else "en"}"><head><meta charset="utf-8">'
        f'<style>{_STYLE}</style></head><body><div id="r"><details><summary>'
        f'<span class="show">{_text(SHOW[language])}</span>'
        f'<span class="hide">{_text(HIDE[language])}</span></summary>'
        f"<ol>{''.join(rows)}</ol></details></div><script>{_HEIGHT_SCRIPT}</script></body></html>"
    )
