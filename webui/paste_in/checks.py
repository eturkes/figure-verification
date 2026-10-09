# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The "Show checks" breakdown: every check a figure faces, as one self-contained HTML document.

Data plus one pure renderer; `filter.py` sends the document as an Open WebUI message embed, which
the chat renders in a sandboxed iframe and never sends to a model. Each row opens to what its check
does, why it failed and a link to its section of the reference; the passed `program` row and the
failing row also quote the program, the failing row marking the line that drew the offending part
or made the offending call (ruling 13: display only, never a verdict input). Every text slot comes
from the tables here or from `REASONS`; the one exception is the program itself, quoted escaped
inside a code listing with whatever it spells. Request text, file contents and sandbox output are
never added from any other source.

A check shows as passed only when it completed, so each reason maps to the check whose stage
raises it, in the judge's stage order (`.claude/rules/figure.md` § Checks).
"""

import html
import re
import unicodedata
from dataclasses import dataclass
from typing import Final, Literal

from verifier.figure.anchoring import Anchoring
from webui.paste_in.reasons import REASONS, Reason

Check = Literal["program", "run", "figure", "parts", "axes", "marks", "values", "columns", "attach"]
type _State = Literal["pass", "fail", "skip"]

CHECKS: Final[tuple[Check, ...]] = (
    "program",
    "run",
    "figure",
    "parts",
    "axes",
    "marks",
    "values",
    "columns",
    "attach",
)

_REASONS_OF: Final[dict[Check, tuple[Reason, ...]]] = {
    "program": ("no_tool_call", "no_user"),
    "run": (
        "no_browser",
        "browser_timeout",
        "browser_error",
        "browser_no_answer",
        "reply_malformed",
        "sandbox_unavailable",
        "sandbox_error",
        "no_description",
        "program_syntax_error",
        "program_error",
        "module_not_available",
        "figure_too_large",
    ),
    "figure": ("no_figure", "multiple_figures", "glyph_missing"),
    "parts": (
        "raster_image",
        "axes_not_judged",
        "axes_twin",
        "axes_overlap",
        "artist_not_judged",
        "no_data",
    ),
    "axes": (
        "mark_not_in_data",
        "scale_not_linear",
        "axis_inverted",
        "zero_not_in_limits",
        "tick_label_mismatch",
        "point_clipped",
    ),
    "marks": (
        "mark_hidden",
        "value_not_finite",
        "bar_not_from_zero",
        "bars_overlap",
        "x_not_ordered",
        "hist_counts",
        "pie_not_whole",
        "area_not_from_zero",
        "marker_size_varies",
        "marker_color_varies",
        "legend_mismatch",
    ),
    "values": (
        "csv_too_large",
        "csv_not_parsable",
        "work_budget_exceeded",
        "category_not_unique",
        "value_not_found",
        "label_not_in_request",
    ),
    "columns": ("column_not_requested", "column_not_named", "label_not_consistent"),
    "attach": ("no_image", "publish_failed"),
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
    "run": (
        (
            "Program run in your browser",
            "the program runs unchanged in the Open WebUI sandbox and finishes without an error",
        ),
        (
            "ブラウザでプログラムを実行",
            "プログラムを変更せずに Open WebUI のサンドボックスで実行し、エラーなく終了",
        ),
    ),
    "figure": (
        ("One figure drawn", "one matplotlib figure, every character drawable"),
        ("図を 1 つ描画", "matplotlib の図が 1 つ、すべての文字を描画可能"),
    ),
    "parts": (
        (
            "Only chart parts the verifier checks",
            "plain axes with bars, lines, points, histograms, pies, areas, reference lines and"
            " text; no images, second axes or overlapping panels",
        ),
        (
            "検証器がチェックできる部品だけを使用",
            "通常の軸と、棒、折れ線、点、ヒストグラム、円、面、基準線、テキスト。"
            "画像、2 つ目の軸、重なるパネルはなし",
        ),
    ),
    "axes": (
        (
            "Honest axes",
            "marks at their values, linear or named log scales, no inverted axis, zero on bar"
            " and area axes, true tick labels, all points inside",
        ),
        (
            "正しい軸",
            "データの値の位置に描画、線形または明記した対数、反転なし、棒と面の軸にゼロ、"
            "正しい目盛りラベル、範囲外の点なし",
        ),
    ),
    "marks": (
        (
            "Honest marks",
            "visible finite values, bars and areas from zero, no overlapping bars, true"
            " histograms and pies, ordered lines, keyed sizes and colors, a true legend",
        ),
        (
            "正しいグラフ要素",
            "見える有限の値、ゼロから始まる棒と面、重ならない棒、正しいヒストグラムと円、"
            "順序どおりの折れ線、凡例のある大きさと色、正しい凡例",
        ),
    ),
    "values": (
        (
            "Drawn values come from your data",
            "each value is in your CSV file, one summary per group of it, or a number in your"
            " request; each category once",
        ),
        (
            "描画した値があなたのデータにある",
            "各値が CSV ファイルの値、そのグループごとの集計、または依頼文の数値。"
            "カテゴリの重複なし",
        ),
    ),
    "columns": (
        (
            "Drawn columns match your request",
            "no drawn column replaces a column your request names; labels name only drawn columns",
        ),
        (
            "描いた列が依頼と一致",
            "依頼にある列を別の列に置き換えない。ラベルは描いた列だけを挙げる",
        ),
    ),
    "attach": (
        ("Image attached to the reply", "one PNG image, stored with this reply"),
        ("返信に画像を添付", "PNG 画像 1 枚をこの返信と一緒に保存"),
    ),
}
# The columns row under production's strict anchoring (Q37); TEXTS holds the demo's rule.
STRICT_COLUMNS: Final[tuple[tuple[str, str], tuple[str, str]]] = (
    (
        "Drawn columns match your request",
        "if your request names a column, it names every drawn column; labels name only drawn"
        " columns",
    ),
    (
        "描いた列が依頼と一致",
        "依頼が列名を含む場合は、描いた列をすべて含む。ラベルは描いた列だけを挙げる",
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
    "run": (
        "Your browser runs the model's program, unchanged, in the Open WebUI sandbox. The program"
        " must finish without an error, and the run reports the figure that it drew.",
        "ブラウザは、モデルのプログラムを変更せずに Open WebUI のサンドボックスで実行します。"
        "プログラムはエラーなく終了し、実行結果として描いた図を報告する必要があります。",
    ),
    "figure": (
        "The program must draw exactly one matplotlib figure. Charts from pandas are matplotlib"
        " figures too. The available fonts must draw every character of its text.",
        "プログラムは matplotlib の図をちょうど 1 つ描く必要があります。"
        "pandas のグラフも matplotlib の図です。"
        "使用できるフォントで、図のすべての文字を描ける必要があります。",
    ),
    "parts": (
        "Each part of the figure must be a kind that the verifier checks. These are plain axes,"
        " bars, lines, points, histograms, pies, filled areas, reference lines and text. Images,"
        " polar or 3D axes, a second y axis and overlapping panels stop the figure.",
        "図の各部品は、検証器がチェックできる種類である必要があります。"
        "通常の軸、棒、折れ線、点、ヒストグラム、円、面、基準線、テキストです。"
        "画像、極座標や 3D の軸、2 つ目の y 軸、重なるパネルがあると、図は表示されません。",
    ),
    "axes": (
        "Each axis must show the data honestly. Marks sit at their data values, scales are"
        " linear unless an axis label or title names a log scale, and no axis is inverted. Bar,"
        " histogram and area axes include zero, each tick label shows the value at its position,"
        " and no data point is outside the axis limits.",
        "各軸はデータを正しく示す必要があります。"
        "グラフ要素はデータの値の位置にあり、軸ラベルかタイトルが対数と明記しない限り目盛りは線形で、"
        "反転した軸はありません。"
        "棒グラフ、ヒストグラム、面グラフの軸はゼロを含み、各目盛りのラベルはその位置の値を示し、"
        "軸の範囲の外にデータ点はありません。",
    ),
    "marks": (
        "Each mark must show its values honestly. Bars and filled areas start at zero or on"
        " another bar or area, bars do not overlap, and histograms and pies match their data."
        " Lines run in one direction, varying sizes and colors have a legend or color bar, and"
        " the legend names the series.",
        "各グラフ要素は値を正しく示す必要があります。"
        "棒と面はゼロまたは他の棒や面から始まり、棒は重ならず、ヒストグラムと円はデータと一致します。"
        "折れ線は一方向に進み、異なる大きさや色には凡例かカラーバーがあり、凡例は系列を正しく示します。",
    ),
    "values": (
        "Each drawn value must come from your data. It is a value in your CSV file or a number in"
        " your request. It can also be one total, mean, minimum, maximum or row count per group"
        " of the file. Category labels come from the same rows or from your request.",
        "描画した各値は、あなたのデータにある必要があります。"
        "CSV ファイルの値、そのグループごとの合計、平均、最小値、最大値、行数、"
        "または依頼文の数値です。"
        "カテゴリのラベルは、同じ行または依頼文にある必要があります。",
    ),
    "columns": (
        "When your request names columns, the chart must draw those columns. A title, axis label"
        " or legend must not name a column or summary that the chart does not draw.",
        "依頼文に列名がある場合、グラフはその列を描く必要があります。"
        "タイトル、軸ラベル、凡例は、グラフが描いていない列や集計を挙げてはいけません。",
    ),
    "attach": (
        "The run returns one PNG image, and Open WebUI stores it with this reply. If either"
        " step fails, the verifier shows no image.",
        "実行結果として PNG 画像が 1 枚返り、Open WebUI がそれをこの返信と一緒に保存します。"
        "どちらかに失敗した場合、検証器は画像を表示しません。",
    ),
}
WHAT: Final = ("What this check does", "このチェックの内容")
CODE: Final = ("Program", "プログラム")
WHY: Final = ("Why it failed", "不合格の理由")
NOT_RUN: Final = (
    "This check did not run, because an earlier check failed.",
    "前のチェックが不合格だったため、このチェックは実施していません。",
)
DREW: Final = (
    "The marked line drew the part, or made the call, that failed this check.",
    "印の付いた行が、このチェックで不合格になった部分を描いたか、その呼び出しを行いました。",
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


@dataclass(frozen=True, slots=True)
class Evidence:
    """The program the outlet ran and the line the judge's failure points at (display only).
    Empty = no program reached the outlet."""

    program: str | None = None
    site: int | None = None


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


def _line(number: int, line: str, *, marked: bool) -> str:
    shown = _code(line[:_LINE_CHARACTERS])
    if marked and shown:
        shown = f"<mark>{shown}</mark>"
    if len(line) > _LINE_CHARACTERS:
        shown += "\N{HORIZONTAL ELLIPSIS}"
    kind = "line at" if marked else "line"
    return (
        f'<span class="{kind}"><span class="ln">{number}</span><span class="src">{shown}</span>'
        "</span>"
    )


def _listing(program: str, site: int | None, language: int) -> tuple[str, bool]:
    """The program's lines within the caps, the `site` line first and marked with its context;
    and whether a mark is shown."""
    lines = _BREAK.split(program[:_SCAN])
    marked = site if site is not None and 1 <= site <= len(lines) else None
    near = [] if marked is None else [marked + d for d in range(-_CONTEXT, _CONTEXT + 1)]
    taken: set[int] = set()
    cost = 0
    for number in (*near, *range(1, len(lines) + 1)):
        if not 1 <= number <= len(lines) or number in taken:
            continue
        weight = min(len(lines[number - 1]), _LINE_CHARACTERS)
        if len(taken) == _MAX_LINES or cost + weight > _MAX_CHARACTERS:
            continue
        taken.add(number)
        cost += weight
    rows: list[str] = []
    for number in sorted(taken):
        if rows and number - 1 not in taken:
            rows.append('<span class="gap">\N{VERTICAL ELLIPSIS}</span>')
        rows.append(_line(number, lines[number - 1], marked=number == marked))
    listing = f'<pre class="listing">{"".join(rows)}</pre>'
    if len(lines) > len(taken):
        elided = ELIDED[language].format(n=len(lines) - len(taken))
        listing += f'<p class="elided">{_text(elided)}</p>'
    if len(program) > _SCAN:
        listing += f'<p class="beyond">{_text(BEYOND[language])}</p>'
    return listing, marked in taken


def _section(kind: str, label: str, body: str) -> str:
    return f'<div class="{kind}"><span class="label">{_text(label)}</span>{body}</div>'


def _more(
    check: Check, state: _State, reason: Reason | None, language: int, evidence: Evidence
) -> str:
    """The opened row: what the check does, whether it ran, the program, why, the link."""
    sections = [_section("what", WHAT[language], f"<p>{_text(EXPLAIN[check][language])}</p>")]
    if state == "skip":
        sections.append(f'<div class="unrun-note"><p>{_text(NOT_RUN[language])}</p></div>')
    quoted = state == "fail" or (check == "program" and state == "pass")
    drew = False
    if quoted and evidence.program is not None:
        site = evidence.site if state == "fail" else None
        listing, drew = _listing(evidence.program, site, language)
        sections.append(_section("code", CODE[language], listing))
    if reason is not None and state == "fail":
        why = f"<p>{_text(f'{REASONS[reason][language]} ({reason})')}</p>"
        if drew:
            why += f'<p class="drew">{_text(DREW[language])}</p>'
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
    `anchoring` picks the columns row's text, so each artifact describes the rule it runs;
    `evidence` = the program + the line the failure points at.
    """
    language = 1 if japanese else 0
    failing = len(CHECKS) if reason is None else CHECKS.index(CHECK_OF[reason])
    cause = "" if reason is None else REASONS[reason][language]
    rows: list[str] = []
    for index, check in enumerate(CHECKS):
        state: _State = "pass" if index < failing else "fail" if index == failing else "skip"
        glyph, labels = MARKS[state]
        texts = STRICT_COLUMNS if check == "columns" and anchoring == "strict" else TEXTS[check]
        title, covers = texts[language]
        unrun = f' <span class="unrun">{_text(UNRUN[language])}</span>' if state == "skip" else ""
        detail = f'<div class="covers">{_text(covers)}</div>'
        if state == "fail":
            detail += f'<div class="cause">{_text(cause)}</div>'
        rows.append(
            f'<li class="{state}"><details class="row"><summary><span class="mark" role="img"'
            f' aria-label="{_text(labels[language])}">{glyph}</span>'
            f'<div><div class="title">{_text(title)}{unrun}</div>{detail}</div></summary>'
            f"{_more(check, state, reason, language, evidence)}</details></li>"
        )
    return (
        f'<!DOCTYPE html><html lang="{"ja" if japanese else "en"}"><head><meta charset="utf-8">'
        f'<style>{_STYLE}</style></head><body><div id="r"><details><summary>'
        f'<span class="show">{_text(SHOW[language])}</span>'
        f'<span class="hide">{_text(HIDE[language])}</span></summary>'
        f"<ol>{''.join(rows)}</ol></details></div><script>{_HEIGHT_SCRIPT}</script></body></html>"
    )
