# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Why a figure failed, in the words the chat user reads above the fixed failure verdict.

Data only; `filter.py` picks the reason and the language. The outlet shows one of these texts as an
Open WebUI status line, which the chat keeps in `statusHistory` and never sends back to the model.
Each text is a short cause, plus a fix where one is known, because Open WebUI clamps a status line
to one line.
"""

from typing import Final, Literal

from verifier.figure.reasons import FigureReason

# Faults the outlet finds around the judge: the model's call, the browser round trip, the image.
OutletCause = Literal[
    "no_tool_call",
    "no_user",
    "no_browser",
    "browser_timeout",
    "browser_error",
    "browser_no_answer",
    "reply_malformed",
    "sandbox_unavailable",
    "sandbox_error",
    "no_description",
    "no_image",
    "publish_failed",
]

type Reason = FigureReason | OutletCause

# reason -> (English, Japanese).
REASONS: Final[dict[Reason, tuple[str, str]]] = {
    "no_tool_call": (
        "The model did not send a chart program.",
        "モデルからグラフのプログラムが届きませんでした。",
    ),
    "no_user": (
        "The request has no signed-in user.",
        "サインインしているユーザーがいません。",
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
    "no_description": (
        "The browser run did not report the drawn figure.",
        "ブラウザが描画した図を報告しませんでした。",
    ),
    "program_syntax_error": (
        "The program is not valid Python.",
        "プログラムが正しい Python ではありません。",
    ),
    "program_error": (
        "The program stopped with an error.",
        "プログラムがエラーで停止しました。",
    ),
    "module_not_available": (
        "The program imports a module that the browser sandbox does not have.",
        "プログラムが、ブラウザのサンドボックスにないモジュールを読み込んでいます。",
    ),
    "figure_too_large": (
        "The figure is too large to check.",
        "図が大きすぎるため、チェックできません。",
    ),
    "no_figure": (
        "The program did not draw a matplotlib figure.",
        "プログラムが matplotlib の図を描いていません。",
    ),
    "multiple_figures": (
        "The program drew more than one figure. Put all panels in one figure.",
        "プログラムが複数の図を描きました。すべてのパネルを 1 つの図に入れてください。",
    ),
    "glyph_missing": (
        "The figure has characters that the available fonts cannot draw.",
        "図に、使用できるフォントで描けない文字があります。",
    ),
    "raster_image": (
        "The figure contains an image, which the verifier cannot check.",
        "図に画像が含まれています。検証器は画像をチェックできません。",
    ),
    "axes_not_judged": (
        "The figure uses axes that the verifier cannot check, such as polar, 3D or inset axes.",
        "図に、検証器がチェックできない軸 (極座標、3D、挿入図など) があります。",
    ),
    "axes_twin": (
        "Two axes share one panel, for example a second y axis.",
        "1 つのパネルに 2 つの軸があります (2 つ目の y 軸など)。",
    ),
    "axes_overlap": (
        "Two panels overlap.",
        "2 つのパネルが重なっています。",
    ),
    "artist_not_judged": (
        "The figure contains a chart element that the verifier cannot check.",
        "図に、検証器がチェックできないグラフ要素があります。",
    ),
    "no_data": (
        "A panel shows no data.",
        "データを表示していないパネルがあります。",
    ),
    "mark_not_in_data": (
        "A chart element is not placed by its data values.",
        "データの値で配置されていないグラフ要素があります。",
    ),
    "scale_not_linear": (
        "An axis is not linear. A log axis must name its scale in its label or the panel title.",
        "線形でない軸があります。対数軸の場合は、軸ラベルかパネルのタイトルに対数と書いてください。",
    ),
    "axis_inverted": (
        "An axis is inverted.",
        "反転している軸があります。",
    ),
    "zero_not_in_limits": (
        "The value axis of a bar, histogram or area chart does not include zero.",
        "棒グラフ、ヒストグラム、面グラフの値の軸にゼロが含まれていません。",
    ),
    "tick_label_mismatch": (
        "A tick label does not show the value at its position.",
        "目盛りのラベルが、その位置の値を示していません。",
    ),
    "point_clipped": (
        "A data point is outside the axis limits.",
        "軸の範囲の外にあるデータ点があります。",
    ),
    "mark_hidden": (
        "A chart element or panel is hidden or draws nothing visible.",
        "非表示のグラフ要素やパネル、または何も見えないグラフ要素があります。",
    ),
    "value_not_finite": (
        "A drawn value is missing or not finite, or a point was dropped.",
        "描画する値に欠損値や有限でない値があるか、点が欠落しています。",
    ),
    "bar_not_from_zero": (
        "A bar does not start at zero.",
        "ゼロから始まっていない棒があります。",
    ),
    "bars_overlap": (
        "Two bars overlap.",
        "重なっている棒があります。",
    ),
    "category_not_unique": (
        "A category occurs more than once in one series.",
        "1 つの系列に同じカテゴリが複数あります。",
    ),
    "x_not_ordered": (
        "The x values of a line are not in order.",
        "折れ線の x の値が順序どおりではありません。",
    ),
    "hist_counts": (
        "The histogram bars do not show the counts of its data.",
        "ヒストグラムの棒が、データの度数を示していません。",
    ),
    "pie_not_whole": (
        "The pie slices do not show the shares of its values.",
        "円グラフの扇形が、値の割合を示していません。",
    ),
    "area_not_from_zero": (
        "A filled area does not start at zero or on another area.",
        "ゼロからも他の面からも始まっていない面があります。",
    ),
    "marker_size_varies": (
        "Marker sizes vary, but no size legend explains them.",
        "マーカーの大きさが異なりますが、大きさの凡例がありません。",
    ),
    "marker_color_varies": (
        "Marker colors vary, but no color bar or color legend explains them.",
        "マーカーの色が異なりますが、カラーバーも色の凡例もありません。",
    ),
    "legend_mismatch": (
        "The legend does not name the chart's series correctly.",
        "凡例がグラフの系列を正しく示していません。",
    ),
    "csv_too_large": (
        "The CSV file is too large.",
        "CSV ファイルが大きすぎます。",
    ),
    "csv_not_parsable": (
        "The CSV file cannot be read.",
        "CSV ファイルを読み取れません。",
    ),
    "work_budget_exceeded": (
        "Checking the values needs more computation than the limit allows.",
        "値のチェックに必要な計算量が上限を超えています。",
    ),
    "value_not_found": (
        "A drawn value is not in your data. Attach a CSV file or write the values in your request.",
        "描画した値がデータにありません。CSV ファイルを添付するか、依頼文に値を書いてください。",
    ),
    "label_not_in_request": (
        "A category label is not in your request. Write each label in your request.",
        "カテゴリのラベルが依頼文にありません。依頼文に各ラベルを書いてください。",
    ),
    "column_not_requested": (
        "The chart replaces a requested column, or its values fit two columns. Name the column.",
        "グラフが依頼の列を別の列に置き換えたか、値が 2 つの列に当てはまります。"
        "列名を書いてください。",
    ),
    "column_not_named": (
        "Your request does not name a drawn column. Use the file's column names.",
        "描いた列の名前が依頼にありません。列名はファイルのとおりに書いてください。",
    ),
    "label_not_consistent": (
        "A chart label names a CSV column or a summary that the chart does not show.",
        "グラフのラベルが、グラフにない CSV の列または集計を挙げています。",
    ),
    "no_image": (
        "The browser run did not produce exactly one PNG image.",
        "ブラウザでの実行で PNG 画像が 1 枚だけ作られませんでした。",
    ),
    "publish_failed": (
        "Open WebUI could not attach the image.",
        "Open WebUI が画像を添付できませんでした。",
    ),
}
