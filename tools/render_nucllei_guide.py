# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q82: shared checklist → nucllei transport → offline HTML + local gallery/diagrams.

    uv run --locked python tools/render_nucllei_guide.py [--check]

Only transport sections/rows differ. Integrity tables remain the shared guide's bytes. Markdown
and HTML are generated together; diagram rendering stays `tools/render_diagrams.py`'s job.
"""

import argparse
import re
from html import escape
from pathlib import Path

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = "https://github.com/eturkes/figure-verification/blob/main/docs/verification"
_ANCHOR = re.compile(r'<a id="check-([a-z]+)"></a>')

_INTRO = (
    """# Figure checks for nucllei

Every rule a chart must pass through `draw_figure`, in run order: what the verifier checks,
how it checks it, and the code that a failure shows. Open the collapsed tool block to read the
check list. Each row links to its section here. [Full rules (online)]({reference}) describes the
shared figure rules and the Open WebUI transport. Examples: [gallery.md](../gallery.md).
[日本語版](checks.ja.md)

## How the verifier works

![The nucllei skill loads draw_figure; one sandbox run reports the figure; the server judges it
and shows only a passing image](../diagrams/verifier-nucllei.svg)

Each check shows a one-line summary; the tables below list every rule. Dashed boxes: what the
language model writes. Red dashed arrows: where a failed check stops the chart.

1. **Load.** nucllei loads the `figure-verification` skill through `load_skill`, or automatically
   for a CSV attachment. The skill makes `draw_figure` available to the model.
2. **Call.** The model sends one complete Python program to `draw_figure`. The tool reads your
   own messages and files from the stored chat branch. It checks the caller before any run.
3. **Run and read.** The tool sends one `/exec` request to your code sandbox, with the trusted
   figure reader and the program, unchanged. Your attached files enter `/workspace/imports/`.
   The reader hooks matplotlib, runs the program and draws each figure once. It reports every
   artist as JSON: class, plotting call, transform, coordinates, axes, ticks, colors, sizes,
   visibility and the recorded inputs of `hist`, `pie`, `fill_between` and `stackplot`. It also
   returns one PNG. There is no separate receipt or browser code runtime.
4. **Judge.** On the nucllei server, standard-library Python applies the rules below to that
   description, in order. The first failure stops the chart. The judge compares drawn values
   with your files and request. No model and no guesswork take part.
5. **Display.** On a pass, the tool saves the PNG as your file and shows it with the verdict,
   interpretation and any model note. On a failure, it shows the verdict and cause, without an
   image or a note. These appear outside the collapsed tool block. The check list appears
   inside that block and also reaches the model. If the display fails, read the cause in the
   tool result.

Not checked: whether the chart answers your question; text on the chart (`text`, `annotate`,
`bar_label`), which the reply lists; the model's note or its reply text; the program itself.
The program must be non-adversarial: it runs before the checks, in the reader's interpreter,
and can read your attached files. The verifier trusts the sandbox, interpreter, matplotlib,
fonts, browser and pixels. The sandbox has no network. Other tools, such as `run_python` and
`fetch_from_workspace`, can show a chart outside this skill and its checks.

""",
    """# nucllei の図のチェック

`draw_figure` でグラフを表示するためのすべての規則を、実行順に示します。チェックする内容、その方法、
不合格のときのコードです。折りたたまれたツール欄を開くと、チェック項目を読めます。
各行は、ここにある対応する節にリンクします。[詳細 (オンライン)]({reference}) は、共通の図の規則と
Open WebUI の実行経路を説明します。例: [gallery.ja.md](../gallery.ja.md)。[English](checks.md)

## 検証器のしくみ

![nucllei のスキルが draw_figure を読み込み、サンドボックスでの 1 回の実行が図を報告します。
サーバーが判定し、合格した画像だけを表示します](../diagrams/verifier-nucllei.ja.svg)

各チェックは 1 行の要約です。すべての規則は下の表にあります。破線の枠: 言語モデルが書くもの。
赤い破線の矢印: 不合格のチェックでグラフが止まる場所。

1. **読み込み。** nucllei は `load_skill` で `figure-verification` スキルを読み込みます。
   CSV の添付時には自動で読み込みます。このスキルで、モデルが `draw_figure` を使えるようになります。
2. **呼び出し。** モデルは完全な Python プログラムを `draw_figure` に送ります。ツールは、保存した
   チャットの分岐から、あなた自身のメッセージとファイルを読みます。実行の前に呼び出し元を確認します。
3. **実行と読み取り。** ツールは、あなたのコード実行用サンドボックスに `/exec` の呼び出しを 1 回
   送ります。中身は、信頼できる図の読み取り処理と、変更しないプログラムです。添付ファイルは
   `/workspace/imports/` に入ります。読み取り処理は matplotlib にフックを入れ、プログラムを実行し、
   各図を 1 回描画します。すべての描画要素を JSON で報告します。クラス、描画の呼び出し、変換、座標、
   軸、目盛り、色、大きさ、表示状態、各 `hist`、`pie`、`fill_between`、`stackplot` の入力です。
   PNG も 1 枚返します。別の受領記録やブラウザ内のコード実行環境は使いません。
4. **判定。** nucllei のサーバーで、標準ライブラリの Python が記述に次の規則を順に適用します。
   最初の不合格でグラフが止まります。描画した値をファイルと依頼文に照らして比べます。
   モデルも推測も使いません。
5. **表示。** 合格した場合、ツールは PNG をあなたのファイルとして保存し、判定、解釈、モデルの注記
   があればその注記と一緒に表示します。不合格の場合、画像と注記なしで判定と理由を表示します。
   これらは折りたたまれたツール欄の外に表示します。チェック項目はその欄の中に表示し、モデルにも送ります。
   表示処理に失敗した場合は、ツールの結果で理由を確認してください。

チェックしない内容: グラフが質問に答えているかどうか。グラフ上の文字 (`text`、`annotate`、
`bar_label`)。返信はこれを一覧にします。モデルの注記や返信文。プログラムそのもの。
プログラムは検証器を欺かないことが前提です。チェックの前に、読み取り処理と同じインタープリターで
実行し、添付ファイルを読めます。検証器は、サンドボックス、インタープリター、matplotlib、フォント、
ブラウザ、画面上のピクセルを信頼しています。サンドボックスにはネットワークがありません。
`run_python` や `fetch_from_workspace` などの別のツールは、このスキルのチェックを通さずに
グラフを表示できます。

""",
)

_PROGRAM = (
    (
        "### 1. Chart program received from the model\n\n| Rule | How | Code |\n"
        "|---|---|---|\n| request from a signed-in user | `draw_figure` receives the "
        "caller's user id | `no_user` |\n| call in the user's chat, not a delegated "
        "session | the tool refuses a call whose metadata names `agent_session`, before "
        "reading files or running code | `delegated_session` |\n"
    ),
    (
        "### 1. モデルからグラフのプログラムを受信\n\n| 規則 | 方法 | コード |\n"
        "|---|---|---|\n| サインインしているユーザーからの依頼 | `draw_figure` "
        "が呼び出し元のユーザー ID を受け取る | `no_user` |\n| "
        "委任先ではなく、ユーザーのチャットでの呼び出し | メタデータに `agent_session` "
        "がある場合、ファイルの読み取りやコードの実行の前に拒否する | "
        "`delegated_session` |\n"
    ),
)
_RUN = (
    (
        "### 2. Program run in the code sandbox\n\n| Rule | How | Code |\n|---|---|---|\n| "
        "the code sandbox answers | one `POST /exec` through nucllei's sandbox client; a "
        "connection failure blocks | `sandbox_unreachable` |\n| program within the "
        "sandbox's time limit | requests 120 s for the run and waits at most 150 s for "
        "HTTP; the sandbox can apply a shorter limit | `sandbox_timeout` |\n| the sandbox "
        "run succeeds | an HTTP refusal or a nonzero `exit_code` blocks | "
        "`sandbox_error` |\n| complete reply in the expected format | `exit_code` is an "
        "integer, `stdout` is text within the reader's output bound, and "
        "`stdout_truncated` is false | `reply_malformed` |\n| run reports its figure | "
        "`stdout` holds one parsable, tagged description line | `no_description` |\n"
    ),
    (
        "### 2. サンドボックスでプログラムを実行\n\n| 規則 | 方法 | コード |\n|---|---|---|\n"
        "| コード実行のサンドボックスが応答 | nucllei のサンドボックス用クライアントで "
        "`POST /exec` を 1 回送り、接続に失敗したら不合格 | `sandbox_unreachable` |\n| "
        "プログラムがサンドボックスの制限時間内 | 実行には 120 秒を指定し、HTTP "
        "の応答は最大 150 秒待つ。サンドボックスが短い上限を適用する場合もある | "
        "`sandbox_timeout` |\n| サンドボックスの実行が成功 | HTTP "
        "の拒否、またはゼロ以外の `exit_code` は不合格 | `sandbox_error` |\n| "
        "応答が想定の形式で、途中で切れていない | `exit_code` が整数、`stdout` "
        "が読み取り処理の出力上限内のテキスト、`stdout_truncated` が false | "
        "`reply_malformed` |\n| 実行結果が図を報告 | `stdout` "
        "に、読み取れるタグ付きの記述の行が 1 つある | `no_description` |\n"
    ),
)
_ATTACH = (
    (
        "### 9. Image shown with the reply\n\n| Rule | How | Code |\n|---|---|---|\n| "
        "exactly one PNG from the run | `stdout` holds exactly one valid PNG data-URI "
        "line of at most 500,000 characters | `no_image` |\n| the server saves and shows the image "
        "| stores the PNG through `Storage.upload_file` and `Files.insert_new_file`, "
        "with the caller as owner; the display accepts the reply | `publish_failed` |\n"
    ),
    (
        "### 9. 返信に画像を表示\n\n| 規則 | 方法 | コード |\n|---|---|---|\n| 実行結果の "
        "PNG がちょうど 1 枚 | `stdout` に 500,000 文字以下の有効な PNG のデータ URI "
        "の行がちょうど 1 つある | `no_image` |\n| サーバーが画像を保存して表示 | "
        "`Storage.upload_file` と `Files.insert_new_file` で PNG "
        "を保存し、呼び出し元を所有者にする。表示処理が返信を受け入れる | `publish_failed` |\n"
    ),
)
_ROWS = {
    "glyph_missing": (
        (
            "| every character in an available font | the reader counts missing-glyph "
            "warnings, mathtext missing-glyph records and `.notdef` glyphs in path text; "
            "the wrapper registers the jail's Noto Sans CJK JP for ordinary text, not "
            "mathtext | `glyph_missing` |"
        ),
        (
            "| すべての文字が使用できるフォントにある | "
            "読み取り処理が、グリフ不足の警告、mathtext "
            "のグリフ不足の記録、パスのテキストの `.notdef` グリフを数える。ラッパーが "
            "jail の Noto Sans CJK JP を通常のテキストに登録する。mathtext は対象外 | "
            "`glyph_missing` |"
        ),
    ),
    "verifier_error": (
        (
            "| verifier finishes without an internal error | an unexpected exception in "
            "the tool fails the chart | `verifier_error` |"
        ),
        (
            "| 検証器が内部エラーなく終了 | ツールで想定外の例外が起きた場合は不合格 | "
            "`verifier_error` |"
        ),
    ),
    "csv_too_large": (
        (
            "| CSV at most 8 MB, 100,000 rows, 128 columns, 512 bytes per cell | the "
            "tool reads the user's own files from the stored chat branch and checks each "
            "file's owner before reading its bytes; the judge checks the caps | "
            "`csv_too_large` |"
        ),
        (
            "| CSV は 8 MB、100,000 行、128 列、1 セル 512 バイトまで | "
            "ツールが保存したチャットの分岐からユーザー自身のファイルを取得し、バイトの読"
            "み取り前に所有者を確認する。判定処理が上限を確認 | `csv_too_large` |"
        ),
    ),
    "module_not_available": (
        (
            "| imports available in the code sandbox | the exception is no "
            "missing-module error; the sandbox's installed packages decide availability "
            "| `module_not_available` |"
        ),
        (
            "| コード実行のサンドボックスにあるモジュールを読み込む | "
            "例外がモジュール不足のエラーではない。使用できるものはサンドボックスのインス"
            "トール済みパッケージで決まる | `module_not_available` |"
        ),
    ),
}

_STYLE = """\
:root {
  color-scheme: light dark;
  --paper: #ffffff; --ink: #202b33; --secondary: #55626b;
  --rule: #667984; --link: #07577a; --band: #e8f2f5;
  font-family: "Noto Sans", "Noto Sans CJK JP", system-ui, sans-serif;
  font-size: 100%; line-height: 1.6;
  color: var(--ink); background: var(--paper);
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper: #182127; --ink: #e7edf1; --secondary: #adbcc6;
    --rule: #7d909b; --link: #79cdea; --band: #263640;
  }
}
* { box-sizing: border-box; }
body { margin: 0 auto; max-width: 76ch; padding: 1.25rem; }
nav { display: flex; flex-wrap: wrap; gap: .75rem 1.5rem; margin-bottom: 2rem; }
a { color: var(--link); text-underline-offset: .18em; }
a:focus-visible, summary:focus-visible, .table-scroll:focus-visible {
  outline: 3px solid var(--link); outline-offset: 4px;
}
h1 { font-size: 2rem; line-height: 1.2; margin: 0 0 1.25rem; }
h2 { font-size: 1.5rem; line-height: 1.3; margin-top: 2.5rem; }
h3 { font-size: 1.125rem; line-height: 1.4; margin-top: 2rem; }
p, ul, ol { margin-block: 1rem; }
li { margin-block: .35rem; }
code { font-family: ui-monospace, monospace; font-size: .9em; overflow-wrap: anywhere; }
pre { padding: 1rem; overflow: auto; background: var(--band); line-height: 1.5; }
pre code { overflow-wrap: normal; }
img { display: block; max-width: 100%; height: auto; background: white; }
.diagram {
  width: min(70rem, calc(100vw - 2rem)); margin: 1.5rem 0 1.5rem 50%;
  transform: translateX(-50%);
}
.diagram img { margin-inline: auto; }
figcaption { text-align: center; font-size: .9375rem; margin-top: .5rem; }
.table-scroll { overflow-x: auto; margin: 1.5rem 0; }
table { border-collapse: collapse; width: 100%; font-size: .9375rem; }
th { background: var(--band); text-align: left; }
th, td { border: 1px solid var(--rule); padding: .6rem; vertical-align: top; }
td { overflow-wrap: anywhere; }
td:first-child { min-width: 9rem; }
td:nth-child(2) { min-width: 12rem; }
td:last-child { min-width: 9rem; }
.gallery td { width: 50%; min-width: 15rem; }
summary { color: var(--link); cursor: pointer; padding: .4rem 0; }
.skip { position: absolute; top: -10rem; }
.skip:focus { position: static; display: block; margin-bottom: 1rem; }
@media (max-width: 36rem) {
  body { padding: 1rem; }
  h1 { font-size: 1.75rem; }
  .table-scroll::before {
    content: attr(data-scroll-note); display: block; margin-bottom: .5rem;
    color: var(--secondary); font-size: .875rem;
  }
}
"""


def _replace_row(text: str, reason: str, row: str) -> str:
    result, count = re.subn(rf"^\|.*`{reason}` \|$", lambda _: row, text, flags=re.MULTILINE)
    if count != 1:
        msg = f"expected one {reason} row, found {count}"
        raise ValueError(msg)
    return result


def guide(language: str) -> str:
    """The shared guide with the nucllei-only flow and transport rows."""
    index = int(language == "ja")
    suffix = ".ja" if index else ""
    source = (ROOT / f"docs/checks{suffix}.md").read_text(encoding="utf-8")
    marks = list(_ANCHOR.finditer(source))
    sections = {
        mark.group(1): source[mark.end() : marks[i + 1].start() if i + 1 < len(marks) else None]
        for i, mark in enumerate(marks)
    }
    link_label = "詳細 (オンライン)" if index else "Full rules (online)"
    for check, base in (
        ("program", _PROGRAM[index]),
        ("run", _RUN[index]),
        ("attach", _ATTACH[index]),
    ):
        text = base
        if check == "run":
            # Interpreter + description bounds are shared, not a second handwritten rule table.
            text += (
                "\n".join(
                    line
                    for line in sections[check].splitlines()
                    if any(
                        f"`{reason}` |" in line
                        for reason in (
                            "program_syntax_error",
                            "program_error",
                            "module_not_available",
                            "figure_too_large",
                        )
                    )
                )
                + "\n"
            )
        sections[check] = f"\n\n{text}\n[{link_label}]({REFERENCE}{suffix}.md#check-{check})\n\n"
    text = _INTRO[index].format(reference=f"{REFERENCE}{suffix}.md") + "".join(
        f'<a id="check-{check}"></a>{section}' for check, section in sections.items()
    )
    for reason, rows in _ROWS.items():
        text = _replace_row(text, reason, rows[index])
    original_label = "詳細" if index else "Full rules"
    text = text.replace(
        f"[{original_label}](verification{suffix}.md", f"[{link_label}]({REFERENCE}{suffix}.md"
    ).replace(f"](gallery{suffix}.md", f"](../gallery{suffix}.md")
    return text.rstrip() + "\n"


def html(markdown: str, language: str, *, gallery: bool = False) -> str:
    """A CSP-compatible static page: inline CSS, local assets, labelled reference links only."""
    suffix = ".ja" if language == "ja" else ""
    for before, after in (
        ("checks.md", "checks.html"),
        ("checks.ja.md", "checks.ja.html"),
        ("gallery.md", "gallery.html"),
        ("gallery.ja.md", "gallery.ja.html"),
        ("../gallery.md", "gallery.html"),
        ("../gallery.ja.md", "gallery.ja.html"),
        ("../diagrams/verifier-nucllei.svg", "verifier.svg"),
        ("../diagrams/verifier-nucllei.ja.svg", "verifier.ja.svg"),
    ):
        markdown = markdown.replace(f"]({before})", f"]({after})").replace(
            f"]({before}#", f"]({after}#"
        )
    body = MarkdownIt("commonmark", {"html": True}).enable("table").render(markdown)
    labels = (
        ("Checks", "Gallery", "日本語", "Skip to content", "Rule table")
        if language == "en"
        else ("チェック", "グラフの例", "English", "本文へ移動", "規則の表")
    )
    scroll_note = (
        "Scroll the table sideways to see all columns."
        if language == "en"
        else "表を左右にスクロールすると、すべての列を読めます。"
    )
    body = body.replace(
        "<table>",
        f'<div class="table-scroll" tabindex="0" role="region" aria-label="{labels[4]}" '
        f'data-scroll-note="{scroll_note}"><table>',
    ).replace("</table>", "</table></div>")
    for name, label in (("checks", labels[0]), ("gallery", labels[1])):
        body = body.replace(f">{name}{suffix}.md</a>", f">{label}</a>")
    full_size = "Open the full-size diagram" if language == "en" else "図を原寸で開く"
    body = re.sub(
        r'<p>(<img src="(verifier(?:\.ja)?\.svg)"[^>]+>)</p>',
        rf'<figure class="diagram">\1<figcaption><a href="\2">{full_size}</a>'
        "</figcaption></figure>",
        body,
    )
    body = re.sub(r'<img src="(gallery/[^"]+\.png)"[^>]+>', r'<a href="\1">\g<0></a>', body)
    title = escape(markdown.splitlines()[0].removeprefix("# "))
    twin = ("gallery" if gallery else "checks") + (".ja" if language == "en" else "") + ".html"
    kind = ' class="gallery"' if gallery else ""
    return (
        f'<!doctype html>\n<html lang="{language}">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n<style>\n{_STYLE}</style>\n</head>\n<body{kind}>\n"
        f'<a class="skip" href="#content">{labels[3]}</a>\n<nav aria-label="'
        + ("Guide pages" if language == "en" else "ガイドのページ")
        + f'"><a href="checks{suffix}.html">{labels[0]}</a>'
        f'<a href="gallery{suffix}.html">{labels[1]}</a><a href="{twin}">{labels[2]}</a></nav>\n'
        f'<main id="content">\n{body}</main>\n</body>\n</html>\n'
    )


def artifacts() -> dict[Path, bytes]:
    """All generated bytes, including identical copies of the gallery PNGs and diagram SVGs."""
    public = ROOT / "llens/ext/public/figure-verification"
    result: dict[Path, bytes] = {}
    for language, suffix in (("en", ""), ("ja", ".ja")):
        markdown = guide(language)
        result[ROOT / f"docs/nucllei/checks{suffix}.md"] = markdown.encode()
        result[public / f"checks{suffix}.html"] = html(markdown, language).encode()
        gallery = (ROOT / f"docs/gallery{suffix}.md").read_text(encoding="utf-8")
        result[public / f"gallery{suffix}.html"] = html(gallery, language, gallery=True).encode()
        result[public / f"verifier{suffix}.svg"] = (
            ROOT / f"docs/diagrams/verifier-nucllei{suffix}.svg"
        ).read_bytes()
        for name in re.findall(r"\]\((gallery/[^)]+\.png)\)", gallery):
            result[public / name] = (ROOT / "docs" / name).read_bytes()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the nucllei guide and its offline HTML copy."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report files that need generation without writing them.",
    )
    args = parser.parse_args()
    expected = artifacts()
    stale = set((ROOT / "llens/ext/public/figure-verification").rglob("*")) - expected.keys()
    stale = {path for path in stale if path.is_file()}
    changed = [
        path
        for path, content in expected.items()
        if not path.is_file() or path.read_bytes() != content
    ]
    if args.check:
        for path in sorted([*changed, *stale]):
            print(f"out of date: {path.relative_to(ROOT)}")  # noqa: T201 - CLI report
        raise SystemExit(int(bool(changed or stale)))
    for path in stale:
        path.unlink()
    for path, content in expected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    print(f"wrote {len(expected)} files")  # noqa: T201 - CLI report


if __name__ == "__main__":
    main()
