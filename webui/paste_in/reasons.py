# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Why a figure failed, in the words the chat user reads above the fixed failure verdict.

Data only; `filter.py` picks the reason and the language. The outlet shows one of these texts as an
Open WebUI status line, which the chat keeps in `statusHistory` and never sends back to the model,
so the admission vocabulary in the refusal codes stays out of model context (ruling 6). Each text is
a short cause, plus a fix where one is known, because Open WebUI clamps a status line to one line.
"""

from typing import Final, Literal

from verifier.pysrc.errors import RefusalCode

# Faults the outlet finds around the verifier: the model's call, the browser round trip, the render.
OutletCause = Literal[
    "no_tool_call",
    "no_user",
    "no_target",
    "no_browser",
    "browser_timeout",
    "browser_error",
    "browser_no_answer",
    "reply_malformed",
    "sandbox_unavailable",
    "sandbox_error",
    "no_image",
    "no_observation",
    "observation_mismatch",
    "publish_failed",
]

type Reason = RefusalCode | OutletCause

# reason -> (English, Japanese).
REASONS: Final[dict[Reason, tuple[str, str]]] = {
    "source_too_large": (
        "The program is too long.",
        "プログラムが長すぎます。",
    ),
    "source_not_utf8": (
        "The program is not valid UTF-8 text.",
        "プログラムが正しい UTF-8 テキストではありません。",
    ),
    "source_has_nul": (
        "The program contains a NUL character.",
        "プログラムに NUL 文字が含まれています。",
    ),
    "line_too_long": (
        "A line of the program is too long.",
        "プログラムに長すぎる行があります。",
    ),
    "source_not_tokenizable": (
        "The program cannot be read as Python tokens.",
        "プログラムを Python のトークンとして読み取れません。",
    ),
    "too_many_tokens": (
        "The program has too many tokens.",
        "プログラムのトークンが多すぎます。",
    ),
    "nesting_too_deep": (
        "The program nests brackets too deeply.",
        "プログラムの括弧の入れ子が深すぎます。",
    ),
    "unbalanced_brackets": (
        "The program has unbalanced brackets.",
        "プログラムの括弧の対応が取れていません。",
    ),
    "indent_too_deep": (
        "The program indents too deeply.",
        "プログラムのインデントが深すぎます。",
    ),
    "source_not_parsable": (
        "The program is not valid Python.",
        "プログラムが正しい Python ではありません。",
    ),
    "statement_not_admitted": (
        "The program uses a statement that the verifier does not accept.",
        "検証器が受け入れない文が使われています。",
    ),
    "expression_not_admitted": (
        "The program uses an expression that the verifier does not accept.",
        "検証器が受け入れない式が使われています。",
    ),
    "import_not_admitted": (
        "The program has an import that the verifier does not accept.",
        "検証器が受け入れない import 文があります。",
    ),
    "assign_target_not_admitted": (
        "The program assigns to a target that the verifier does not accept.",
        "検証器が受け入れない代入先が使われています。",
    ),
    "call_target_not_admitted": (
        "The program calls a function that the verifier does not accept.",
        "検証器が受け入れない関数が呼び出されています。",
    ),
    "keyword_not_admitted": (
        "A call passes an argument that the verifier does not accept.",
        "検証器が受け入れない引数を渡す呼び出しがあります。",
    ),
    "attribute_not_admitted": (
        "The program uses an attribute that the verifier does not accept.",
        "検証器が受け入れない属性が使われています。",
    ),
    "operator_not_admitted": (
        "The program uses an operator that the verifier does not accept.",
        "検証器が受け入れない演算子が使われています。",
    ),
    "literal_not_admitted": (
        "The program uses a literal value that the verifier does not accept.",
        "検証器が受け入れないリテラル値が使われています。",
    ),
    "name_not_bound": (
        "The program uses a name that it does not define.",
        "定義されていない名前が使われています。",
    ),
    "no_mark": (
        "The verifier finds no plot call that it can read as the chart.",
        "グラフとして読み取れる描画の呼び出しがありません。",
    ),
    "multiple_marks": (
        "The program draws more than one series.",
        "プログラムが複数の系列を描いています。",
    ),
    "mark_arity_not_projected": (
        "A plot call does not take exactly two arguments, x and y.",
        "描画の呼び出しの引数が x と y の 2 つではありません。",
    ),
    "mark_not_valid_for_arm": (
        "A formula chart cannot use this plot type.",
        "数式のグラフではこの種類のグラフを使えません。",
    ),
    "x_not_a_grid": (
        "The plot call does not take x directly from np.linspace or np.arange.",
        "描画の呼び出しが x を np.linspace または np.arange から直接受け取っていません。",
    ),
    "y_not_over_grid": (
        "The y values are not computed from the x grid.",
        "y の値が x のグリッドから計算されていません。",
    ),
    "grid_not_representable": (
        "The verifier cannot use the bounds or point count of the x grid.",
        "x のグリッドの範囲または点の数を使えません。",
    ),
    "expression_not_projected": (
        "The verifier cannot state what an expression computes.",
        "式が何を計算するかを特定できません。",
    ),
    "label_not_literal": (
        "A label, title or style call has a form that the verifier does not accept.",
        "ラベル、タイトル、またはスタイルの呼び出しの形式を、検証器が受け入れません。",
    ),
    "name_rebound": (
        "The program assigns the same name twice.",
        "同じ名前に 2 回代入しています。",
    ),
    "no_terminal": (
        "The program does not call plt.show().",
        "プログラムが plt.show() を呼び出していません。",
    ),
    "statement_after_terminal": (
        "The program has statements after plt.show().",
        "plt.show() の後に文があります。",
    ),
    "statement_not_projected": (
        "The verifier cannot state what a statement draws.",
        "文が何を描くかを特定できません。",
    ),
    "arm_ambiguous": (
        "The program imports pandas and also uses a formula grid.",
        "プログラムが pandas をインポートし、数式のグリッドも使っています。",
    ),
    "no_source": (
        "The program does not read the CSV file.",
        "プログラムが CSV ファイルを読み込んでいません。",
    ),
    "multiple_sources": (
        "The program calls pd.read_csv more than once.",
        "プログラムが pd.read_csv を 2 回以上呼び出しています。",
    ),
    "source_not_literal": (
        "The pd.read_csv call does not take exactly one fixed file name.",
        "pd.read_csv の呼び出しが、固定のファイル名 1 つだけを受け取っていません。",
    ),
    "column_not_literal": (
        "A column selection or grouping is not written as one fixed column name.",
        "列の選択またはグループ化が、固定の列名 1 つで書かれていません。",
    ),
    "column_not_from_source": (
        "A plotted column does not come from the CSV file.",
        "描画する列が CSV ファイルから取られていません。",
    ),
    "aggregation_not_projected": (
        "The verifier cannot state what a grouping computes.",
        "グループ集計が何を計算するかを特定できません。",
    ),
    "figure_orphans_mark": (
        "The program calls plt.figure() after it draws.",
        "描画の後に plt.figure() が呼び出されています。",
    ),
    "source_not_supplied": (
        "The program reads a CSV file, but no CSV file is attached.",
        "プログラムは CSV ファイルを読み込みますが、添付がありません。",
    ),
    "target_mismatch": (
        "The program does not match the attached file or the requested formula.",
        "プログラムが添付ファイルにも依頼の数式にも一致しません。",
    ),
    "column_not_requested": (
        "The chart replaces a requested column, or a request word fits two columns.",
        "グラフが依頼の列を別の列に置き換えたか、依頼の語が 2 つの列に当てはまります。",
    ),
    "column_not_named": (
        "Your request does not name a drawn column. Use the file's column names.",
        "描いた列の名前が依頼にありません。列名はファイルのとおりに書いてください。",
    ),
    "csv_too_large": (
        "The CSV file is too large.",
        "CSV ファイルが大きすぎます。",
    ),
    "csv_not_parsable": (
        "The CSV file cannot be read.",
        "CSV ファイルを読み取れません。",
    ),
    "column_not_present": (
        "A column that the program uses is not in the CSV file.",
        "プログラムが使う列が CSV ファイルにありません。",
    ),
    "column_not_numeric": (
        "A plotted column holds a value that is not a number.",
        "描画する列に数値でない値があります。",
    ),
    "value_not_in_profile": (
        "The verifier does not accept the form or size of a CSV value or group value.",
        "CSV の値またはグループの値の形式や大きさを、検証器が受け入れません。",
    ),
    "value_not_finite": (
        "A computed value is not a finite number.",
        "計算した値に有限でない値があります。",
    ),
    "work_budget_exceeded": (
        "The chart needs more computation than the limit allows.",
        "グラフに必要な計算量が上限を超えています。",
    ),
    "category_not_unique": (
        "The same category occurs more than once in the chart.",
        "グラフに同じカテゴリが 2 回以上あります。",
    ),
    "x_not_ordered": (
        "The x values of the line are not in increasing order.",
        "折れ線の x の値が昇順ではありません。",
    ),
    "label_not_consistent": (
        "A chart label names a CSV column or a summary that the chart does not show.",
        "グラフのラベルが、グラフにない CSV の列または集計を挙げています。",
    ),
    "no_tool_call": (
        "The model did not send a chart program.",
        "モデルからグラフのプログラムが届きませんでした。",
    ),
    "no_user": (
        "The request has no signed-in user.",
        "サインインしているユーザーがいません。",
    ),
    "no_target": (
        "No CSV file or request formula is available that the verifier can read.",
        "検証器が読み取れる CSV ファイルも、依頼文の数式もありません。",
    ),
    "no_browser": (
        "No browser session is available to draw the chart.",
        "グラフを描くブラウザのセッションがありません。",
    ),
    "browser_timeout": (
        "The browser did not answer within 60 seconds.",
        "ブラウザが 60 秒以内に応答しませんでした。",
    ),
    "browser_error": (
        "The call to the browser failed.",
        "ブラウザの呼び出しに失敗しました。",
    ),
    "browser_no_answer": (
        "The chat tab did not answer. Keep the tab open and try again.",
        "チャットのタブが応答しませんでした。タブを開いたままにしてください。",
    ),
    "reply_malformed": (
        "The browser sent a reply in an unknown format.",
        "ブラウザの応答の形式が不明です。",
    ),
    "sandbox_unavailable": (
        "The browser could not load Pyodide. Turn off the ad blocker for this site.",
        "Pyodide を読み込めません。このサイトの広告ブロッカーをオフにしてください。",
    ),
    "sandbox_error": (
        "The browser runtime reported an error.",
        "ブラウザの実行環境がエラーを報告しました。",
    ),
    "no_image": (
        "The browser run did not produce exactly one PNG image.",
        "ブラウザでの実行で PNG 画像が 1 枚だけ作られませんでした。",
    ),
    "no_observation": (
        "The browser run did not report the drawn values.",
        "ブラウザが描画した値を報告しませんでした。",
    ),
    "observation_mismatch": (
        "The drawn values differ from the recomputed values.",
        "描画された値が再計算した値と一致しません。",
    ),
    "publish_failed": (
        "Open WebUI could not attach the image.",
        "Open WebUI が画像を添付できませんでした。",
    ),
}
