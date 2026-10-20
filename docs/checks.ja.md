# 図のチェック

グラフが合格する必要があるすべての規則を、実行順に、不合格のときに表示されるコードとともに示します。
**チェック項目を表示** の各行は、ここにある対応する節にリンクしています。規則の詳細:
[verification.ja.md](verification.ja.md)。[English](checks.md)

チェックしない内容: グラフが質問に答えているかどうか。グラフ上の文字 (`text`、`annotate`、
`bar_label`)。返信はこれを一覧にします。プログラムそのもの。検証器はプログラムを信頼しています。
プログラムはチェックの前に実行され、添付ファイルを読み取り、ブラウザのネットワークにアクセスできます。

<a id="check-program"></a>

### 1. モデルからグラフのプログラムを受信

| 規則 | コード |
|---|---|
| グラフ用のツールで送られたプログラム (1 つの返信では最後の呼び出し) | `no_tool_call` |
| サインインしているユーザーからの依頼 | `no_user` |

[詳細](verification.ja.md#check-program)

<a id="check-run"></a>

### 2. ブラウザでプログラムを実行

| 規則 | コード |
|---|---|
| プログラムを実行するブラウザのセッションがある | `no_browser` |
| Pyodide のファイル保存がオフ (`ENABLE_PYODIDE_FILE_PERSISTENCE`) | `sandbox_not_isolated` |
| ブラウザが 60 秒以内に応答 | `browser_timeout` |
| ブラウザの呼び出しが成功 | `browser_error` |
| チャットのタブが応答 | `browser_no_answer` |
| 応答が想定の形式 | `reply_malformed` |
| Pyodide を読み込める (このサイトの広告ブロッカーはオフ) | `sandbox_unavailable` |
| ブラウザの実行環境にエラーがない | `sandbox_error` |
| 実行結果が図を報告 | `no_description` |
| 正しい Python | `program_syntax_error` |
| プログラムが例外なく最後まで実行 | `program_error` |
| 読み込むのは numpy、pandas、matplotlib、標準ライブラリだけ | `module_not_available` |
| 軸 24 個、部品 2,000 個、座標 20,000 個、1 つのテキスト 1,000 文字まで。図の記述 400,000 バイト、PNG 500,000 文字まで | `figure_too_large` |

[詳細](verification.ja.md#check-run)

<a id="check-figure"></a>

### 3. 図を 1 つ描画

| 規則 | コード |
|---|---|
| matplotlib の図がある (pandas のグラフも該当) | `no_figure` |
| 図は 1 つだけ (`plt.subplots` のパネルは可) | `multiple_figures` |
| すべての文字が使用できるフォントにある (日本語フォントはプログラムと添付ファイルの文字を含む) | `glyph_missing` |
| 検証器が内部エラーなく終了 | `verifier_error` |

[詳細](verification.ja.md#check-figure)

<a id="check-parts"></a>

### 4. 検証器がチェックできる部品だけを使用

使える部品: 折れ線 (`plot`、`step`)、点 (`scatter`)、棒 (`bar`、`barh`、グループ化、積み上げ)、
ヒストグラム (`hist`、塗りつぶし、データセット 1 つ)、円 (`pie`)、面 (`fill_between`、
`stackplot`)、基準線と帯 (`axhline`、`axvline`、`axhspan`、`axvspan`)、テキスト (タイトル、
軸ラベル、凡例、目盛りのラベル、`text`、`annotate`、`bar_label`)、散布図の色を示すカラーバー。

| 規則 | コード |
|---|---|
| 画像なし (`imshow`、`pcolormesh`、`matshow`) | `raster_image` |
| 通常の軸だけ。極座標、3D、挿入図、副軸なし | `axes_not_judged` |
| 2 軸なし (`twinx`、`twiny`) | `axes_twin` |
| 重なるパネルなし | `axes_overlap` |
| ほかの部品なし (エラーバー、箱ひげ図、等高線、追加した図形、step のヒストグラム) | `artist_not_judged` |
| すべてのパネルにデータ | `no_data` |

[詳細](verification.ja.md#check-parts)

<a id="check-axes"></a>

### 5. 正しい軸

| 規則 | コード |
|---|---|
| 各部品がデータの値の位置にある (`transData`) | `mark_not_in_data` |
| 線形の目盛り。対数は、軸ラベルかパネルのタイトルに `log`、`logarithmic`、`対数` がある場合だけ | `scale_not_linear` |
| x 軸も y 軸も反転なし | `axis_inverted` |
| 棒、ヒストグラム、面の値の軸の範囲にゼロ (折れ線と散布図は拡大可) | `zero_not_in_limits` |
| 表示される各目盛りのラベル = その位置の値 (カテゴリ、日付、数値) | `tick_label_mismatch` |
| すべてのデータ点、棒の端、基準線が軸の範囲内 (円は対象外) | `point_clipped` |

[詳細](verification.ja.md#check-axes)

<a id="check-marks"></a>

### 6. 正しいグラフ要素

| 規則 | コード |
|---|---|
| すべての部品とパネルが表示され、見える | `mark_hidden` |
| すべての値が有限。欠落した点なし | `value_not_finite` |
| 棒はゼロ、または積み上げた棒の上端から | `bar_not_from_zero` |
| 重なる棒なし | `bars_overlap` |
| 折れ線の x の値は一方向 | `x_not_ordered` |
| ヒストグラムの高さ = ビンごとのデータの度数または密度。すべてのデータがビンの中。重みと `cumulative` なし | `hist_counts` |
| 円の扇形が 360° を満たし、各扇形 = 合計に対する割合 | `pie_not_whole` |
| 面はゼロ、または積み上げた面の上端から | `area_not_from_zero` |
| 散布図の大きさが異なる場合: 大きさの凡例 (`legend_elements("sizes")`) | `marker_size_varies` |
| 散布図の色が異なる場合: カラーバーまたは色の凡例 | `marker_color_varies` |
| 凡例の項目は描いた系列を示す。凡例のあるパネルに系列が 2 つ以上: すべての系列を示す | `legend_mismatch` |

[詳細](verification.ja.md#check-marks)

<a id="check-values"></a>

### 7. 描画した値があなたのデータにある

描画した各値は、次のいずれかの出所の値と完全に一致する必要があります。

- **CSV ファイル**: 列の値、またはグループごとの `sum`、`mean`、`min`、`max`、`count` のいずれか
  1 つ。1 行が裏付けるのは 1 つの値だけ。一部の行だけでも合格し、返信はそれを示します (たとえば `6 件中 2 件を描画`)。
- **依頼文** (このチャットの分岐のすべてのメッセージ。一時チャットでは最後のメッセージ): 入力した
  数値、展開した範囲 (`1 to 10`、`1 through 10`、`1–10`、`1〜10`、`1から10まで`。`1-10` は範囲に
  なりません。最大 10,000 個)、入力したカテゴリのラベル。
- **それらの 1 つの計算**: 1 つの系列の 2 乗、累計、変化、割合、百分率。CSV の 2 つの列の比率、差、
  積、和 (各行またはグループごと)。
- **基準線と帯**: ゼロ、または列全体の集計 1 つも可。
- **セルの値と同じ凡例のラベル**: その系列は、その値を持つ行から作られている必要があります。
- **キーが示す散布図の色と大きさ**: 描画した値として扱い、その点と同じ行またはグループから。
- **ファイルも数値もない場合**: 完全性だけをチェックし、返信にそのことを示します。

| 規則 | コード |
|---|---|
| CSV は 8 MB、100,000 行、128 列、1 セル 512 バイトまで | `csv_too_large` |
| CSV を読み取れる (`pandas.read_csv` と同じ方式) | `csv_not_parsable` |
| 照合が作業上限内 (`MAX_WORK`、5,000,000) | `work_budget_exceeded` |
| 1 つの系列で各カテゴリは 1 回 | `category_not_unique` |
| 描画したすべての値が出所にある | `value_not_found` |
| 入力したすべてのカテゴリのラベルが依頼文にある | `label_not_in_request` |

[詳細](verification.ja.md#check-values)

<a id="check-columns"></a>

### 8. 描いた列が依頼と一致

CSV のグラフだけが対象です。依頼文が列を挙げるのは、列の見出し、管理者が登録した別名、または
1 文字の誤りを含む 5 文字以上の 1 語の名前を書いた場合です。本番環境では、日本語の短い形
(`年月` に対する `月`、`月別`) も列を挙げます。

| 規則 | コード |
|---|---|
| 依頼文にある列を別の列に置き換えない | `column_not_requested` |
| 値が 2 つの列に当てはまる場合: 依頼文がどちらかを挙げる | `column_not_requested` |
| 本番環境: 依頼文が列を挙げるか除外する場合、描いた列をすべて挙げる | `column_not_named` |
| タイトル、軸ラベル、凡例、カラーバーのラベル: 描いていない列なし。グループごとの合計または平均には、ほかの集計なし | `label_not_consistent` |

[詳細](verification.ja.md#check-columns)

<a id="check-attach"></a>

### 9. 返信に画像を添付

| 規則 | コード |
|---|---|
| 実行結果の PNG がちょうど 1 枚 | `no_image` |
| Open WebUI が画像を添付 | `publish_failed` |

[詳細](verification.ja.md#check-attach)
