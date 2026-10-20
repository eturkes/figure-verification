# Figure checks

Every rule a chart must pass, in run order, with the code that a failure shows. Each row of **Show
checks** links to its section here. Rules in full: [verification.md](verification.md).
[日本語版](checks.ja.md)

Not checked: whether the chart answers your question; text on the chart (`text`, `annotate`,
`bar_label`), which the reply lists; the program itself. The verifier trusts the program: it runs
before the checks and can read your attached files and reach your browser's network.

<a id="check-program"></a>

### 1. Chart program received from the model

| Rule | Code |
|---|---|
| program sent through the chart tool (the last call in a reply counts) | `no_tool_call` |
| request from a signed-in user | `no_user` |

[Full rules](verification.md#check-program)

<a id="check-run"></a>

### 2. Program run in your browser

| Rule | Code |
|---|---|
| a browser session to run the program | `no_browser` |
| Pyodide file persistence off (`ENABLE_PYODIDE_FILE_PERSISTENCE`) | `sandbox_not_isolated` |
| browser answers within 60 s | `browser_timeout` |
| browser call succeeds | `browser_error` |
| chat tab answers | `browser_no_answer` |
| reply in the expected format | `reply_malformed` |
| Pyodide loads (ad blocker off for this site) | `sandbox_unavailable` |
| no error from the browser runtime | `sandbox_error` |
| run reports its figure | `no_description` |
| valid Python | `program_syntax_error` |
| program runs to its end without an exception | `program_error` |
| imports only numpy, pandas, matplotlib and the standard library | `module_not_available` |
| at most 24 axes, 2,000 parts, 20,000 coordinates and 1,000 characters per text; description at most 400,000 bytes, PNG at most 500,000 characters | `figure_too_large` |

[Full rules](verification.md#check-run)

<a id="check-figure"></a>

### 3. One figure drawn

| Rule | Code |
|---|---|
| a matplotlib figure (pandas plots count) | `no_figure` |
| only one figure (panels from `plt.subplots` allowed) | `multiple_figures` |
| every character in an available font (the Japanese font holds the characters of the program and the attached files) | `glyph_missing` |
| verifier finishes without an internal error | `verifier_error` |

[Full rules](verification.md#check-figure)

<a id="check-parts"></a>

### 4. Only chart parts the verifier checks

Allowed: lines (`plot`, `step`), points (`scatter`), bars (`bar`, `barh`, grouped, stacked),
histograms (`hist`, filled, one data set), pies (`pie`), areas (`fill_between`, `stackplot`),
reference lines and bands (`axhline`, `axvline`, `axhspan`, `axvspan`), text (titles, axis labels,
legends, tick labels, `text`, `annotate`, `bar_label`), a colorbar for scatter colors.

| Rule | Code |
|---|---|
| no image (`imshow`, `pcolormesh`, `matshow`) | `raster_image` |
| plain axes only: no polar, 3D, inset or secondary axes | `axes_not_judged` |
| no twin axes (`twinx`, `twiny`) | `axes_twin` |
| no overlapping panels | `axes_overlap` |
| no other part (error bars, box plots, contours, added shapes, step histograms) | `artist_not_judged` |
| data in every panel | `no_data` |

[Full rules](verification.md#check-parts)

<a id="check-axes"></a>

### 5. Honest axes

| Rule | Code |
|---|---|
| each mark at its data values (`transData`) | `mark_not_in_data` |
| linear scales; log only when the axis label or panel title says `log`, `logarithmic` or `対数` | `scale_not_linear` |
| no inverted x or y axis | `axis_inverted` |
| zero inside the value-axis limits of bars, histograms and areas (line and scatter may zoom) | `zero_not_in_limits` |
| each visible tick label = the value at its position (category, date or number) | `tick_label_mismatch` |
| every data point, bar end and reference mark inside the axis limits (pies exempt) | `point_clipped` |

[Full rules](verification.md#check-axes)

<a id="check-marks"></a>

### 6. Honest marks

| Rule | Code |
|---|---|
| every mark and panel visible, with ink | `mark_hidden` |
| every value finite; no point dropped | `value_not_finite` |
| bars from 0, or from the top of a stacked bar | `bar_not_from_zero` |
| no overlapping bars | `bars_overlap` |
| line x values in one direction | `x_not_ordered` |
| histogram heights = counts or density of its data over its bins; all data inside the bins; no weights, no `cumulative` | `hist_counts` |
| pie wedges fill 360°; each span = its share of the total | `pie_not_whole` |
| areas from 0, or from the top of a stacked area | `area_not_from_zero` |
| varying scatter sizes: a size legend (`legend_elements("sizes")`) | `marker_size_varies` |
| varying scatter colors: a colorbar or a color legend | `marker_color_varies` |
| legend entries name drawn series; 2 or more series in a panel with a legend: every series named | `legend_mismatch` |

[Full rules](verification.md#check-marks)

<a id="check-values"></a>

### 7. Drawn values come from your data

Each drawn value equals, exactly, a value from one of these sources:

- **CSV file**: a column's values, or one `sum`, `mean`, `min`, `max` or `count` per group. One row
  backs one value. A subset of rows passes, and the reply states it, for example `2 of 6 drawn`.
- **Request** (every message of this chat branch; a temporary chat: the last one): typed numbers,
  ranges expanded (`1 to 10`, `1 through 10`, `1–10`, `1〜10`, `1から10まで`; never `1-10`; at most
  10,000 numbers), and typed category labels.
- **One computation of these**: square, running total, change, share or percent of one series;
  ratio, difference, product or sum of two CSV columns, per row or per group.
- **Reference lines and bands**: also 0, or one summary of a whole column.
- **A legend label equal to a cell value**: the series comes from the rows that hold that value.
- **Scatter colors and sizes that a key shows**: drawn values, from their point's row or group.
- **No file and no numbers**: integrity alone; the reply says so.

| Rule | Code |
|---|---|
| CSV at most 8 MB, 100,000 rows, 128 columns, 512 bytes per cell | `csv_too_large` |
| CSV readable (the `pandas.read_csv` profile) | `csv_not_parsable` |
| matching within the work limit (`MAX_WORK`, 5,000,000) | `work_budget_exceeded` |
| each category once per series | `category_not_unique` |
| every drawn value found in a source | `value_not_found` |
| every typed category label in the request | `label_not_in_request` |

[Full rules](verification.md#check-values)

<a id="check-columns"></a>

### 8. Drawn columns match your request

CSV figures only. A request names a column by its header, by an alias that your administrator
declares, or with one typing error in a one-word name of 5 or more characters. In production, a
Japanese short form also names it (`月` for `年月`, also `月別`).

| Rule | Code |
|---|---|
| no column that the request names replaced by another | `column_not_requested` |
| values that fit two columns: the request names one of them | `column_not_requested` |
| production: if the request names or excludes a column, it names every drawn column | `column_not_named` |
| titles, axis labels, legends and colorbar labels: no undrawn column; over a total or mean per group, no other summary | `label_not_consistent` |

[Full rules](verification.md#check-columns)

<a id="check-attach"></a>

### 9. Image attached to the reply

| Rule | Code |
|---|---|
| exactly one PNG from the run | `no_image` |
| Open WebUI attaches the image | `publish_failed` |

[Full rules](verification.md#check-attach)
