# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M18.2 contract literals + structural projections; production implementation unread."""

from __future__ import annotations

from importlib import import_module
from typing import Protocol, cast

from test_paste_in_checks import _Document, _Node, _one
from verifier.pysrc.spec import Anchoring
from webui.paste_in.reasons import Reason

ORDER = (
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
ROLES = {
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
UI = {
    "WHAT": ("What this check does", "このチェックの内容"),
    "CODE": ("Code checked", "チェックしたコード"),
    "WHY": ("Why it failed", "不合格の理由"),
    "NOT_RUN": (
        "This check did not run, because an earlier check failed.",
        "前のチェックが不合格だったため、このチェックは実施していません。",
    ),
    "STOPPED": (
        "The check stopped at the marked code.",
        "印の付いたコードでチェックが止まりました。",
    ),
    "SPEC": ("Read the full specification of this check", "このチェックの詳しい仕様を読む"),
    "ELIDED": ("Lines not shown: {n}.", "表示していない行: {n} 行。"),
    "BEYOND": (
        "The program is too long to show in full.",
        "プログラムが長すぎるため、すべては表示できません。",
    ),
}
EXPLAIN = {
    "program": (
        "The model must send its chart program through the chart tool. "
        "The verifier checks the last program sent in this reply.",
        "モデルはグラフのプログラムをグラフ用のツールで送る必要があります。"
        "検証器は、この返信で最後に送られたプログラムをチェックします。",
    ),
    "data": (
        "The verifier needs data that you supplied. This is a CSV file attached to the chat, "
        "or one formula and one interval in your request.",
        "検証器には、あなたが用意したデータが必要です。チャットに添付した CSV ファイル、"
        "または依頼文にある 1 つの数式と 1 つの区間です。",
    ),
    "readable": (
        "The verifier reads the program as Python text before it examines it. "
        "It checks the size, text encoding, line length, tokens, brackets and indentation, "
        "then parses the syntax.",
        "検証器は、内容を調べる前にプログラムを Python のテキストとして読み取ります。"
        "サイズ、文字コード、行の長さ、トークン、括弧、インデントを確認してから、構文を解析します。",
    ),
    "accepted": (
        "The verifier accepts only a fixed set of Python statements, imports, function calls "
        "and arguments. Anything outside that set stops the check, also when Python could run it.",
        "検証器が受け入れるのは、決まった範囲の Python の文、import、関数呼び出し、引数だけです。"
        "その範囲の外にあるものは、Python で実行できる場合でもチェックを止めます。",
    ),
    "chart": (
        "The verifier reads which chart the program draws: one data source, one plot call, "
        "the labels, and plt.show() at the end. Every statement must contribute to that chart.",
        "検証器は、プログラムが描くグラフを読み取ります。データの読み込み 1 つ、描画呼び出し 1 つ、"
        "ラベル、最後の plt.show() です。すべての文がそのグラフに関係する必要があります。",
    ),
    "binding": (
        "The verifier checks that the program uses your data: it reads your attached file, "
        "or it plots the formula in your request. Column names in your request are compared "
        "with the columns that the chart draws.",
        "検証器は、プログラムがあなたのデータを使うことを確認します。添付ファイルを読み込むこと、"
        "または依頼文の数式を描くことです。依頼文にある列名は、グラフが描く列と比べます。",
    ),
    "recompute": (
        "The verifier computes every plotted value again from your file or formula, with its "
        "own code. Then it checks that each result is a finite number within the limits.",
        "検証器は、描画するすべての値を、ファイルまたは数式から独自のコードで計算し直します。"
        "その後、各結果が上限内の有限の数であることを確認します。",
    ),
    "integrity": (
        "The verifier checks rules that keep the chart honest. Bars start at zero, there is "
        "one set of axes with linear scales, and no row is left out. Categories do not repeat, "
        "and line x values are in order. A label must not name another file column that the "
        "verifier recognizes.",
        "検証器は、グラフを正しく見せるための規則を確認します。棒はゼロから始まり、軸は 1 組で"
        "目盛りは線形、行の欠落はありません。カテゴリは重複せず、折れ線の x の値は順序どおりです。"
        "ラベルは、検証器が認識できるファイルの列名のうち、グラフが描かない列名を挙げてはいけません。",
    ),
    "render": (
        "Your browser runs the model's program, unchanged, in the Open WebUI sandbox. "
        "The run must return one PNG image and the values that it drew.",
        "ブラウザは、モデルのプログラムを変更せずに Open WebUI のサンドボックスで実行します。"
        "実行結果として、PNG 画像 1 枚と描画した値を返す必要があります。",
    ),
    "match": (
        "The verifier compares the values that the browser drew with the values that it "
        "computed. File values must be equal. Formula values must stay within the checked "
        "numerical bounds.",
        "検証器は、ブラウザが描画した値と、検証器が計算した値を比べます。ファイルの値は完全に一致"
        "する必要があります。数式の値は、定めた数値誤差の範囲内である必要があります。",
    ),
    "attach": (
        "The chart image is stored with this reply. If storing fails, the verifier shows no image.",
        "グラフの画像をこの返信と一緒に保存します。保存できない場合、検証器は画像を表示しません。",
    ),
}
URLS = (
    "https://github.com/eturkes/figure-verification/blob/main/docs/verification.md",
    "https://github.com/eturkes/figure-verification/blob/main/docs/verification.ja.md",
)
TRIGGERS = (
    "x-data",
    "x-init",
    "x-show",
    "x-bind",
    "x-on",
    "x-text",
    "x-html",
    "x-model",
    "x-modelable",
    "x-ref",
    "x-for",
    "x-if",
    "x-effect",
    "x-transition",
    "x-cloak",
    "x-ignore",
    "x-teleport",
    "x-id",
    "new Chart(",
    "Chart.",
)

# Literals describe every statement, independent of the production classifier.
PROGRAM = (
    "import pandas as pd\n"
    "import matplotlib.pyplot as plt\n"
    "df = pd.read_csv('/mnt/uploads/chart.csv')\n"
    "totals = df.groupby('region')['revenue'].sum()\n"
    "totals.plot(kind='bar')\n"
    "plt.title('Totals')\n"
    "plt.xlabel('Region')\n"
    "plt.ylabel('Revenue')\n"
    "plt.show()"
)
TRACE = (
    ("import", (1, 0, 1, 19)),
    ("import", (2, 0, 2, 31)),
    ("source", (3, 0, 3, 42)),
    ("data", (4, 0, 4, 46)),
    ("mark", (5, 0, 5, 23)),
    ("title", (6, 0, 6, 19)),
    ("xlabel", (7, 0, 7, 20)),
    ("ylabel", (8, 0, 8, 21)),
    ("show", (9, 0, 9, 10)),
)
PASS_LINES = {
    "program": (1, 2, 3, 4, 5, 6, 7, 8, 9),
    "data": (),
    "readable": (1, 2, 3, 4, 5, 6, 7, 8, 9),
    "accepted": (1, 2, 3, 4, 5, 6, 7, 8, 9),
    "chart": (1, 2, 3, 4, 5, 6, 7, 8, 9),
    "binding": (3, 4, 5),
    "recompute": (3, 4, 5),
    "integrity": (4, 5, 6, 7, 8),
    "render": (1, 2, 3, 4, 5, 6, 7, 8, 9),
    "match": (5,),
    "attach": (),
}
type SpanTuple = tuple[int, int, int, int]
type TraceTuple = tuple[tuple[str, SpanTuple], ...]


class SpanView(Protocol):
    line: int
    column: int
    end_line: int
    end_column: int


class StepView(Protocol):
    role: str
    span: SpanView


class EvidenceView(Protocol):
    program: str | None
    at: tuple[SpanView, ...]
    trace: tuple[StepView, ...]


class PositionAPI(Protocol):
    def Span(  # noqa: N802 - public dataclass factory
        self, line: int, column: int, end_line: int, end_column: int
    ) -> SpanView: ...
    def Step(self, role: str, span: SpanView) -> StepView: ...  # noqa: N802 - public dataclass factory


class DetailAPI(Protocol):
    EXPLAIN: dict[str, tuple[str, str]]
    CODE_ROLES: dict[str, object]
    SPECIFICATION: tuple[str, str]

    def Evidence(  # noqa: N802 - public dataclass factory
        self,
        program: str | None = None,
        at: tuple[SpanView, ...] = (),
        trace: tuple[StepView, ...] = (),
    ) -> EvidenceView: ...

    def breakdown_html(
        self,
        reason: Reason | None,
        *,
        japanese: bool,
        anchoring: Anchoring,
        evidence: EvidenceView = ...,
    ) -> str: ...


def api() -> DetailAPI:
    return cast(DetailAPI, import_module("webui.paste_in.checks"))


def evidence(
    program: str | None = None,
    at: tuple[SpanTuple, ...] = (),
    trace: TraceTuple = (),
) -> EvidenceView:
    positions = cast(PositionAPI, import_module("verifier.pysrc.position"))
    return api().Evidence(
        program,
        tuple(positions.Span(*span) for span in at),
        tuple(positions.Step(role, positions.Span(*span)) for role, span in trace),
    )


def rows(source: str) -> dict[str, _Node]:
    parsed = _Document(source).root
    items = _one(parsed.nodes(tag="ol")).nodes(tag="li")
    assert len(items) == 11
    return dict(zip(ORDER, items, strict=True))


def direct(node: _Node) -> list[_Node]:
    return [child for child in node.children if isinstance(child, _Node)]


def listing(row: _Node) -> tuple[tuple[int, bool, str, tuple[str, ...]], ...]:
    return tuple(
        (
            int(_one(line.nodes(cls="ln")).text()),
            "at" in (line.attrs.get("class") or "").split(),
            _one(line.nodes(cls="src")).text(),
            tuple(mark.text() for mark in line.nodes(tag="mark")),
        )
        for line in row.nodes(cls="line")
    )


def numbers(row: _Node) -> tuple[int, ...]:
    return tuple(item[0] for item in listing(row))
