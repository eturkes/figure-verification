# Figure verification: what the verifier checks

This reference describes the checks that the figure verifier runs in Open WebUI. It applies to the
current release on the `main` branch. Each row of the **Show checks** list under a chart reply links
to its section here. For the Japanese version, read [verification.ja.md](verification.ja.md).

## What a verified figure means

A language model writes a Python program that draws a chart with matplotlib. Your browser runs that
program, unchanged, in the Python sandbox of Open WebUI (Pyodide). The verifier then reads the
finished figure and decides whether the chart may appear. The reply shows the chart and `Figure
verification passed` only when every check passes. Otherwise the reply shows `Figure verification
failed, no image produced` and the reason.

The verifier gives three kinds of assurance:

1. **Integrity.** Every part of the figure belongs to a closed set of chart parts that the verifier
   checks. Every part obeys a closed set of rules: for example, bars start at zero and every axis
   runs in its normal direction.
2. **Provenance.** When you attach a CSV file or type numbers in your request, every drawn value
   comes from that data. A value that the verifier cannot find in your data stops the chart.
3. **Interpretation.** A passed reply states in plain words where each drawn value comes from. It
   names the file, the columns, the summary per group and the row counts.

The verifier never claims that the chart answers your question. A chart can show correct values of a
different quantity than you meant, for example a sum where you wanted a mean. Read the
interpretation under the chart to see what the verifier checked.

Every decision follows a fixed rule. The verifier uses no model and no guesswork. It trusts the
browser, the Pyodide sandbox, matplotlib and the image pixels, and it does not verify them.

## Where the values come from

The verifier compares the drawn values with the data that you supplied:

- **An attached CSV file.** Each drawn value must be a value of one column, or one summary per group
  of one column. A summary is a total, a mean, a minimum, a maximum or a row count. A chart can draw
  part of the rows. The reply then states how many it drew, for example `2 of 6 drawn`.
- **Numbers in your request.** Each drawn value must be a number that your request contains. The
  verifier expands a typed range into every whole number between its ends. For example, `1 through
  10`, `1 to 10`, `1–10`, `1〜10` and `1から10まで` each give the numbers 1 to 10. A plain hyphen, as in
  `1-10`, never makes a range, because dates and negative numbers use it. A category label must also
  occur in your request.
- **No data.** When you attach no file and type no number, the verifier checks the chart for
  integrity alone. The reply says so.

When both sources exist, each value can come from either source. For example, a chart can draw your
file's totals with a target line at a number that you typed.

The verifier reads the CSV file with the same profile as `pandas.read_csv`. The verifier compares
values exactly, with no numerical tolerance. Each row of the file backs one drawn value at most.

Some special cases:

- **A series named by a legend.** A legend can name a series with a value of a column, for example
  `London` in a `city` column. The series must then come from the rows that hold that value.
- **Reference lines and bands.** This applies to `axhline`, `axvline`, `axhspan` and `axvspan`. Each
  value must be zero, a number in your request, a value of a numeric column, or one summary of a
  whole column.
- **Marker colors and sizes.** A color bar or a legend can show the colors or the sizes of scatter
  markers. Those values then count as drawn values. Each one must come from the same row or group as
  its marker.
- **Pie labels.** The verifier reads each wedge label as the chart shows it.

## How to read "Show checks"

**Show checks** lists the 9 checks in the order that they run. Each row shows one of three states:

- ✓ **passed**: the check completed.
- ✗ **failed**: the check stopped the figure. The row shows the reason.
- – **not checked**: an earlier check failed, so this check did not run.

Click a row to open it. The opened row shows what the check does, the reason for a failure, and a
link to this reference. The first row and the failed row also show the model's program. In the
failed row, the verifier marks the program line that drew the failed part or made the failed call.
An example is the `plt.ylim` call that cut off the bars. A failure without such a line shows the
program without a mark.

The listing shows the model's program exactly as it was sent. It can contain any text that the
program holds, for example a file name or a word copied from your request. Characters that are not
visible, such as control characters, show as visible symbols.

## The checks

<a id="check-program"></a>

### 1. Chart program received from the model

The model must call the chart tool and send one Python program. A program written as reply text is
not a chart: only a program sent through the tool can produce a figure. When the model calls the
tool more than once in a reply, the verifier checks the last program.

| Reason | Meaning |
|---|---|
| `no_tool_call` | The model did not send a chart program. |
| `no_user` | The request has no signed-in user. |

<a id="check-run"></a>

### 2. Program run in your browser

Your browser runs the model's program, unchanged, in the Open WebUI sandbox (Pyodide). The verifier
adds only an outer step: it records the finished figure and saves one PNG image. Python itself rejects a program that is not valid Python. The program can import numpy, pandas,
matplotlib and the Python standard library; the verifier loads these three packages before the
program runs. When the program or an attached file holds Japanese
text, the verifier also sends Open WebUI's Japanese font with the program. The chat tab must stay
open while the program runs.

| Reason | Meaning |
|---|---|
| `no_browser` | No browser session is available to run the program. |
| `browser_timeout` | The browser did not answer within 60 seconds. |
| `browser_error` | The call to the browser failed. |
| `browser_no_answer` | The chat tab did not answer. Keep the tab open and try again. |
| `reply_malformed` | The browser sent a reply in an unknown format. |
| `sandbox_unavailable` | The browser could not load Pyodide. Turn off the ad blocker for this site. |
| `sandbox_error` | The browser runtime reported an error. |
| `no_description` | The browser run did not report the drawn figure. |
| `program_syntax_error` | The program is not valid Python. |
| `program_error` | The program stopped with an error. |
| `module_not_available` | The program imports a module that the sandbox does not have. |
| `figure_too_large` | The figure is too large to check. |

<a id="check-figure"></a>

### 3. One figure drawn

The program must draw exactly one matplotlib figure. Charts from pandas are matplotlib figures too.
The Pyodide runtime of Open WebUI 0.10.2 has no seaborn, so a seaborn program stops at its import. A figure can hold several panels, made with `plt.subplots`. The available
fonts must draw every character of the figure's text.

| Reason | Meaning |
|---|---|
| `no_figure` | The program did not draw a matplotlib figure. |
| `multiple_figures` | The program drew more than one figure. |
| `glyph_missing` | The figure has characters that the available fonts cannot draw. |

<a id="check-parts"></a>

### 4. Only chart parts the verifier checks

Each part of the figure must be a kind that the verifier checks. Each panel must use plain axes. The
verifier checks each panel on its own. It checks these chart parts:

| Part | Made by |
|---|---|
| Line | `plot`, `step` |
| Points | `scatter` |
| Bars | `bar`, `barh`, grouped and stacked bars |
| Histogram | `hist` with filled bars and one data set |
| Pie | `pie`, with its labels |
| Filled area | `fill_between`, `stackplot` |
| Reference line or band | `axhline`, `axvline`, `axhspan`, `axvspan` |
| Text | titles, axis labels, legends, tick labels, `text`, `annotate`, `bar_label` |

Any other part stops the figure, for example error bars, box plots, contours or a shape that the
program adds itself. An image, polar or 3D axes, an inset, a second y axis and overlapping panels
also stop it. The verifier accepts a color bar only for the colors of a scatter chart.

| Reason | Meaning |
|---|---|
| `raster_image` | The figure contains an image, which the verifier cannot check. |
| `axes_not_judged` | The figure uses axes that the verifier cannot check, such as polar, 3D or inset axes. |
| `axes_twin` | Two axes share one panel, for example a second y axis. |
| `axes_overlap` | Two panels overlap. |
| `artist_not_judged` | The figure contains a chart part that the verifier cannot check. |
| `no_data` | A panel shows no data. |

<a id="check-axes"></a>

### 5. Honest axes

Each axis must show the data honestly:

- **Data coordinates.** Each chart part sits at its data values on the axes.
- **Linear scales.** An axis is linear. The verifier accepts a log axis only when its axis label or
  the panel title says `log`, `logarithmic` or `対数`. Any other scale stops the figure.
- **No inverted axis.** Values increase upward on the y axis and to the right on the x axis.
- **Zero on value axes of bars, histograms and areas.** The value axis of these charts includes
  zero, so a bar's length shows its value. Line and scatter charts can zoom to their data.
- **True tick labels.** Each visible tick label shows the value at its position. A category axis
  shows its categories. A date axis shows its dates.
- **No data point outside the limits.** Every drawn point, bar end and reference line lies inside
  the axis limits.

| Reason | Meaning |
|---|---|
| `mark_not_in_data` | A chart part does not sit at its data values. |
| `scale_not_linear` | An axis is not linear, and no label names a log scale. |
| `axis_inverted` | An axis is inverted. |
| `zero_not_in_limits` | The value axis of a bar, histogram or area chart does not include zero. |
| `tick_label_mismatch` | A tick label does not show the value at its position. |
| `point_clipped` | A data point is outside the axis limits. |

<a id="check-marks"></a>

### 6. Honest marks

Each chart part must show its values honestly:

- **Visible values.** Every chart part and panel is visible, and no drawn value is missing or
  infinite. A point that a chart part received but does not show stops the figure.
- **Bars from zero.** Each bar starts at zero, or on top of another bar in a stack.
- **No overlapping bars.** Grouped bars stand side by side.
- **True histograms.** The bars of a histogram show the counts, or the density, of its data over its
  bins.
- **Whole pies.** The wedges of a pie fill the circle, and each wedge shows its share of the total.
- **Areas from zero.** Each filled area starts at zero, or on another area in a stack.
- **Ordered lines.** The x values of a line run in one direction.
- **Explained sizes and colors.** Marker sizes or colors that vary need a size legend, a color
  legend or a color bar.
- **True legends.** Each legend entry names a series of the chart. With two or more series in a
  panel that has a legend, the legend names every series.

| Reason | Meaning |
|---|---|
| `mark_hidden` | A chart part or panel is hidden or draws nothing visible. |
| `value_not_finite` | A drawn value is missing or not finite, or a point was dropped. |
| `bar_not_from_zero` | A bar does not start at zero. |
| `bars_overlap` | Two bars overlap. |
| `x_not_ordered` | The x values of a line are not in order. |
| `hist_counts` | The histogram bars do not show the counts of its data. |
| `pie_not_whole` | The pie wedges do not show the shares of its values. |
| `area_not_from_zero` | A filled area does not start at zero or on another area. |
| `marker_size_varies` | Marker sizes vary, but no size legend explains them. |
| `marker_color_varies` | Marker colors vary, but no color bar or color legend explains them. |
| `legend_mismatch` | The legend does not name the chart's series correctly. |

<a id="check-values"></a>

### 7. Drawn values come from your data

The verifier compares each drawn value with your data, as [Where the values come
from](#where-the-values-come-from) describes. One series cannot show the same category twice,
because one value would cover the other.

| Reason | Meaning |
|---|---|
| `csv_too_large` | The attached file is too large. |
| `csv_not_parsable` | The attached file cannot be read as CSV. |
| `work_budget_exceeded` | Checking the values needs more computation than the limit allows. |
| `category_not_unique` | A category occurs more than once in one series. |
| `value_not_found` | A drawn value is not in your data. Attach a CSV file or write the values in your request. |
| `label_not_in_request` | A category label is not in your request. Write each label in your request. |

<a id="check-columns"></a>

### 8. Drawn columns match your request

The drawn columns are the columns that the drawn values come from. The verifier compares them with
the column names in your request. It knows each column by its name and by any other names that your
administrator declared. It also knows a short Japanese form, such as `月` for `年月`, also with a
suffix such as `月別`.

- **Production.** When your request names a column, it must name every drawn column.
- **Demo.** The chart must not replace a column that your request names with another column.

When the values fit two columns equally, your request must name one of them. A title, axis label,
legend or color bar label must not name a column that the chart does not draw. Over a total or a
mean per group, it must not name another kind of summary, for example `average` on a chart of
totals. A minimum or maximum per group draws values of the column itself, so this rule does not
read its labels.

| Reason | Meaning |
|---|---|
| `column_not_requested` | The chart replaces a requested column, or its values fit two columns. |
| `column_not_named` | Your request does not name a drawn column. |
| `label_not_consistent` | A label names a column or a summary that the chart does not show. |

<a id="check-attach"></a>

### 9. Image attached to the reply

The browser run returns one PNG image, and Open WebUI stores it with the reply. When either step
fails, the verifier shows no image.

| Reason | Meaning |
|---|---|
| `no_image` | The browser run did not produce exactly one PNG image. |
| `publish_failed` | Open WebUI could not attach the image. |

<a id="limits"></a>

## Limits

The verifier stops work beyond these limits.

| Limit | Value | Applies to |
|---|---|---|
| `MAX_AXES` | 24 | axes in the figure |
| `MAX_CHILDREN` | 2,000 | parts in all axes of the figure |
| `MAX_COORDINATES` | 20,000 | drawn coordinates in the figure |
| `MAX_TEXT` | 1,000 | characters in one text |
| `MAX_DESCRIPTION_BYTES` | 400,000 | bytes in the figure description |
| `MAX_PNG_CHARACTERS` | 500,000 | characters in the PNG image line |
| `max_csv_bytes` | 8,000,000 | CSV file size in bytes |
| `max_csv_rows` | 100,000 | data rows in a CSV file |
| `max_csv_columns` | 128 | columns in a CSV file |
| `max_csv_cell_bytes` | 512 | bytes in one CSV cell |
| `MAX_GROUPS` | 1,000 | groups in one summary per group |
| `MAX_WORK` | 5,000,000 | units of value-matching work |
| `MAX_RANGE` | 10,000 | numbers in one typed range |
| `RPC_TIMEOUT_SECONDS` | 60 | seconds for the browser run |

## What the verifier does not check

- **The verifier trusts the program to be honest.** The program runs before any check, in the same
  Python sandbox as the verifier's reader. A program written to deceive the reader can do so. The
  sandbox can also read your attached files and reach the network of your browser, as any Open WebUI
  code run can.
- **Text on the chart.** The verifier lists free text, such as `text`, `annotate` and `bar_label`
  labels, under the chart. It does not judge that text.
- **Your intent.** The verifier checks that the values come from your data. It does not check that
  the chart shows the quantity that you meant. Column names in your request are the one link to your
  intent.
- **Computed values.** The verifier looks for each drawn value in your data. It does not check how
  the program computed it. A value that the program computes in another way stops the chart,
  unless the same number is also in your data. Examples are a running total, a ratio of two columns
  and a scaled marker size.
- **The image itself.** The verifier trusts the browser, matplotlib and the image pixels.
