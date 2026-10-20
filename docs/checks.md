# Figure checks

Every rule a chart must pass, in run order: what the verifier checks, how it checks it, and the code
that a failure shows. Each row of **Show checks** links to its section here. Rules in full:
[verification.md](verification.md). Each blocked behavior beside an honest chart:
[gallery.md](gallery.md). [日本語版](checks.ja.md)

## How the verifier works

![Diagram of the verifier: the tool records a receipt, the filter runs the model's program inside
the trusted reader in your browser, and the nine checks follow in run order, each summarised in one
line; each check can stop the chart](diagrams/verifier.svg)

Each check shows a one-line summary; the tables below list every rule. Dashed boxes: what the
language model writes. Red dashed arrows: where a failed check stops the chart.

1. **Receipt.** The `draw_figure` tool records the model's program, the ids of your attached files
   and your request: every message that you wrote on this chat branch, read from Open WebUI storage.
   The tool decides nothing.
2. **Run.** The filter reads that receipt alone. It sends one `execute:python` call to the Pyodide
   sandbox in your browser: the trusted figure reader, then the program, unchanged. The browser
   fetches your attached files by id.
3. **Read.** The reader hooks matplotlib, runs the program, and draws each figure once. It reports
   one JSON description of every artist: class, the plotting call that made it, transform, data
   coordinates, axis limits and scales, tick labels, colors, sizes, visibility, and the inputs of
   each `hist`, `pie`, `fill_between` and `stackplot` call. It also returns one PNG.
4. **Judge.** On the Open WebUI server, standard-library Python applies the rules below to that
   description, in order. The first failure stops the chart. The judge compares values with the
   bytes of your attached files and with your request. No model and no guesswork take part.
5. **Publish.** On a pass, the filter attaches the PNG. On a failure, the reply has no image, and
   the status line shows the code.

Not checked: whether the chart answers your question; text on the chart (`text`, `annotate`,
`bar_label`), which the reply lists; the program itself. The verifier trusts the program: it runs
before the checks, in the same interpreter as the reader, and can read your attached files and reach
your browser's network.

<a id="check-program"></a>

### 1. Chart program received from the model

| Rule | How | Code |
|---|---|---|
| program sent through the chart tool | the filter finds a receipt from `draw_figure`; the last call in a reply counts | `no_tool_call` |
| request from a signed-in user | the filter call carries a user id | `no_user` |

[Full rules](verification.md#check-program)

<a id="check-run"></a>

### 2. Program run in your browser

| Rule | How | Code |
|---|---|---|
| a browser session to run the program | the filter call carries the browser socket and a session id | `no_browser` |
| Pyodide file persistence off | reads `ENABLE_PYODIDE_FILE_PERSISTENCE` before any file read or browser call | `sandbox_not_isolated` |
| browser answers within 60 s | the `execute:python` call waits 60 s at most | `browser_timeout` |
| browser call succeeds | the call raises no error | `browser_error` |
| chat tab answers | an `error` reply without `stderr` fails | `browser_no_answer` |
| reply in the expected format | the reply is a `{stdout, stderr, result}` object | `reply_malformed` |
| Pyodide loads (ad blocker off for this site) | a `stderr` that names `loadPyodide`, without a traceback, fails | `sandbox_unavailable` |
| no error from the browser runtime | any other `stderr` text fails | `sandbox_error` |
| run reports its figure | `stdout` holds one parsable, tagged description line | `no_description` |
| valid Python | the reader compiles the program; no `SyntaxError` | `program_syntax_error` |
| program runs to its end without an exception | the reader runs the program and catches any exception with its line | `program_error` |
| imports only numpy, pandas, matplotlib and the standard library | the exception is no missing-module error | `module_not_available` |
| at most 24 axes, 2,000 parts, 20,000 coordinates and 1,000 characters per text; description at most 400,000 bytes, PNG at most 500,000 characters | the reader counts as it describes, and reports a figure past a cap as too large | `figure_too_large` |

[Full rules](verification.md#check-run)

<a id="check-figure"></a>

### 3. One figure drawn

| Rule | How | Code |
|---|---|---|
| a matplotlib figure (pandas plots count) | the reader collects every figure that the program shows or leaves open | `no_figure` |
| only one figure (panels from `plt.subplots` allowed) | the same count is 1 | `multiple_figures` |
| every character in an available font | the reader counts missing-glyph warnings, mathtext missing-glyph records and `.notdef` glyphs in path text; the filter sends the part of Open WebUI's Japanese font that holds the characters of the program and the files | `glyph_missing` |
| verifier finishes without an internal error | any exception while the filter decodes the description or judges it fails the chart | `verifier_error` |

[Full rules](verification.md#check-figure) [Examples](gallery.md#check-figure)

<a id="check-parts"></a>

### 4. Only chart parts the verifier checks

The reader records each artist's class and the plotting call that made it (the outermost
`matplotlib.axes` frame on the stack at the artist's creation). Each pair must be in this closed set: lines
(`plot`, `step`), points (`scatter`), bars (`bar`, `barh`, grouped, stacked), histograms (`hist`,
filled, one data set), pies (`pie`), areas (`fill_between`, `stackplot`), reference lines and bands
(`axhline`, `axvline`, `axhspan`, `axvspan`), text (titles, axis labels, legends, tick labels, `text`,
`annotate`, `bar_label`), a colorbar for scatter colors.

| Rule | How | Code |
|---|---|---|
| no image (`imshow`, `pcolormesh`, `matshow`) | no `AxesImage`, `QuadMesh` or `FigureImage` in the artist tree | `raster_image` |
| plain axes only: no polar, 3D, inset or secondary axes | each axes class is exactly `Axes`, owned by the figure, inside no other axes | `axes_not_judged` |
| no twin axes (`twinx`, `twiny`) | no two axes share an x or y axis at the same position | `axes_twin` |
| no overlapping panels | the axes positions do not overlap | `axes_overlap` |
| no other part (error bars, box plots, contours, added shapes, step histograms) | every (class, call) pair is in the set above | `artist_not_judged` |
| data in every panel | each axes holds a data artist | `no_data` |

[Full rules](verification.md#check-parts) [Examples](gallery.md#check-parts)

<a id="check-axes"></a>

### 5. Honest axes

| Rule | How | Code |
|---|---|---|
| each mark at its data values | each data artist's transform is the axes' `transData` (bars: the data transform; scatter: the offset transform) | `mark_not_in_data` |
| linear scales; log only when the axis label or panel title says `log`, `logarithmic` or `対数` | `axis.get_scale()`; for `log`, the label and title text after NFKC and case folding | `scale_not_linear` |
| no inverted x or y axis | `axis.get_inverted()` | `axis_inverted` |
| zero inside the value-axis limits of bars, histograms and areas (line and scatter may zoom) | `0` lies in the value axis's `get_view_interval()` | `zero_not_in_limits` |
| each visible tick label = the value at its position | each label in view, read as a category, a date or a number (with the formatter's order and offset), equals its tick position, within half a unit of its last digit | `tick_label_mismatch` |
| every data point, bar end and reference mark inside the axis limits (pies exempt) | every drawn coordinate lies in `get_view_interval()` | `point_clipped` |

[Full rules](verification.md#check-axes) [Examples](gallery.md#check-axes)

<a id="check-marks"></a>

### 6. Honest marks

| Rule | How | Code |
|---|---|---|
| every mark and panel visible, with ink | visibility, alpha, face and edge colors, line style and marker size of each artist | `mark_hidden` |
| every value finite; no point dropped | no NaN or infinity in the drawn data or the recorded call inputs; each band draws every point that its call received | `value_not_finite` |
| bars from 0, or from the top of a stacked bar | each bar's base is 0, or exactly the far end of a bar at the same position and width | `bar_not_from_zero` |
| no overlapping bars | no two bar rectangles intersect with an area above 0 | `bars_overlap` |
| line x values in one direction | each line's x positions are monotonic | `x_not_ordered` |
| histogram heights = counts or density of its data over its bins | the judge recounts the recorded `hist` input over the drawn bin edges (numpy rules, last bin closed); all data inside the bins; no weights, no `cumulative` | `hist_counts` |
| pie wedges fill 360°; each span = its share of the total | each wedge span = 360° × value / sum of the recorded `pie` input, within 0.0001°; one radius, no gaps | `pie_not_whole` |
| areas from 0, or from the top of a stacked area | each band's base edge is 0, or exactly the top edge of a grounded band at the same x | `area_not_from_zero` |
| varying scatter sizes: a size legend | the sizes vary only with a legend from that collection's `legend_elements("sizes")` | `marker_size_varies` |
| varying scatter colors: a colorbar or a color legend | the face colors vary only with a colorbar or a `legend_elements()` legend of that collection | `marker_color_varies` |
| legend entries name drawn series; 2 or more series in a panel with a legend: every series named | each legend handle is a judged artist, or a proxy with a mark's label and color | `legend_mismatch` |

[Full rules](verification.md#check-marks) [Examples](gallery.md#check-marks)

<a id="check-values"></a>

### 7. Drawn values come from your data

A series = one line, scatter collection, bar container, pie, area band, reference mark or histogram
input. For each series, the judge searches this closed list for one CSV explanation whose values
equal the points exactly (the same 64-bit float), each CSV row backing one point at most. Each point
that it leaves must be a typed number.

- **CSV file**: a column's values, or one `sum`, `mean`, `min`, `max` or `count` per group, computed
  as pandas computes it, bit for bit. A subset of rows passes, and the reply states it, for example
  `2 of 6 drawn`.
- **Request**: typed numbers after NFKC, ranges expanded (`1 to 10`, `1 through 10`, `1–10`,
  `1〜10`, `1から10まで`; never `1-10`; at most 10,000 numbers), and typed category labels.
- **One computation of these**: square, running total, change, share or percent of one series;
  ratio, difference, product or sum of two CSV columns, per row or per group.
- **Reference lines and bands**: also 0, or one summary of a whole column.
- **A legend label equal to a cell value**: the series comes from the rows that hold that value.
- **Scatter colors and sizes that a key shows**: drawn values, from their point's row or group.
- **No file and no numbers**: integrity alone; the reply says so.

| Rule | How | Code |
|---|---|---|
| CSV at most 8 MB, 100,000 rows, 128 columns, 512 bytes per cell | the filter reads your file's bytes from Open WebUI storage (owner checked); the judge checks the caps | `csv_too_large` |
| CSV readable | a reader restricted to what `pandas.read_csv` reads the same way | `csv_not_parsable` |
| matching within the work limit | the judge counts work units, 5,000,000 at most (`MAX_WORK`) | `work_budget_exceeded` |
| each category once per series | no two points of one series share a key | `category_not_unique` |
| every drawn value found in a source | the search above finds an explanation for every point | `value_not_found` |
| every typed category label in the request | the label occurs in the request after NFKC and case folding | `label_not_in_request` |

[Full rules](verification.md#check-values) [Examples](gallery.md#check-values)

<a id="check-columns"></a>

### 8. Drawn columns match your request

CSV figures only. The drawn columns are the columns of the explanations that check 7 found. The
judge matches the request against the file's header after NFKC and case folding: whole words
(Japanese names: containment), one typing error in a one-word name of 5 or more characters, the aliases that your administrator
declares and, in production, Japanese short forms (`月` for `年月`, also `月別`).

| Rule | How | Code |
|---|---|---|
| no column that the request names replaced by another | no named column undrawn while a drawn column is unnamed | `column_not_requested` |
| values that fit two columns: the request names one of them | two explanations with different columns: the request names the columns of exactly one | `column_not_requested` |
| production: if the request names or excludes a column, it names every drawn column | each drawn column is among the named columns | `column_not_named` |
| titles, axis labels, legends and colorbar labels: no undrawn column; over a total or mean per group, no other summary | the same matcher reads each label against the header and the summary words | `label_not_consistent` |

[Full rules](verification.md#check-columns) [Examples](gallery.md#check-columns)

<a id="check-attach"></a>

### 9. Image attached to the reply

| Rule | How | Code |
|---|---|---|
| exactly one PNG from the run | `stdout` holds exactly one PNG data-URI line | `no_image` |
| Open WebUI attaches the image | the filter's `files` event succeeds | `publish_failed` |

[Full rules](verification.md#check-attach)
