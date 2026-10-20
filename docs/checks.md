# Figure checks: a short guide

This guide explains what each check of the figure verifier means, and what to do when a check
fails. Each row of the **Show checks** list under a chart reply links to its section here. For every
rule, reason code and limit in full, read the reference, [verification.md](verification.md). For the
Japanese version, read [checks.ja.md](checks.ja.md).

## What a passed chart means

A language model writes a Python program that draws your chart. Your browser runs the program, and
the verifier then checks the finished figure. The reply shows the chart and `Figure verification
passed` only when every check passes. Otherwise the reply shows `Figure verification failed, no
image produced` and the reason.

A passed chart tells you two things:

- Every part of the chart is a kind that the verifier checks, and every part obeys the integrity
  rules. For example, bars start at zero and no axis runs backwards.
- If you supplied data, every drawn value comes from that data.

A pass does not tell you that the chart answers your question. For example, a chart can show the
correct totals when you wanted the means. Read the text under the chart. It states where each drawn
value comes from.

## Where values can come from

- **An attached CSV file.** A drawn value can be a value of one column. It can also be one total,
  mean, minimum, maximum or row count per group.
- **Numbers in your request.** A drawn value can be a number that you typed. A range such as `1 to
  10` or `1から10まで` gives every whole number from 1 to 10. Each category label must also occur in
  your request.
- **One computation of that data.** The verifier also accepts a running total, a share or percent of
  the total, the change from the previous point and a square. For two columns of a CSV file, it
  accepts their ratio, difference, product or sum.
- **No data.** If you attach no file and type no number, the verifier checks the chart's integrity
  alone. The reply says so.

Your request includes your earlier messages in this chat. Thus a follow-up such as `Make the bars
red` keeps the numbers and the column names of your earlier messages. In a temporary chat, only your
last message counts.

## How to read "Show checks"

**Show checks** lists the 9 checks in the order that they run. Each row shows one of three states:

- ✓ **passed**: the check completed.
- ✗ **failed**: the check stopped the chart. The row states the reason.
- – **not checked**: an earlier check failed, so this check did not run.

Click a row to open it. The opened row shows what the check does and the related program lines or a
note. A failed row also shows why the check failed. If one program line drew the failed part or made
the failed call, the failed row marks that line. After a failure, the status line above the reply
and the opened row show a code in parentheses, such as `(zero_not_in_limits)`. The [full
reference](verification.md) explains each code.

## The checks

<a id="check-program"></a>

### 1. Chart program received from the model

The model must send its chart program through the chart tool. A program in the text of the reply
does not count, because only the tool can produce a chart.

If this check fails, ask again. You can also ask the model to use the chart tool.

[Read the full rules for this check](verification.md#check-program).

<a id="check-run"></a>

### 2. Program run in your browser

Your browser runs the model's program, unchanged, in the Open WebUI sandbox (Pyodide). The program
can use numpy, pandas, matplotlib and the Python standard library. Keep the chat tab open until the
reply is complete.

If this check fails:

- If the program has an error, ask again or ask for a simpler chart.
- If the program imports a module that the sandbox does not have, such as seaborn, ask for a chart
  with matplotlib or pandas.
- If the browser cannot load the sandbox, turn off the ad blocker for this site.
- If the browser does not answer, keep the tab open and try again.

[Read the full rules for this check](verification.md#check-run).

<a id="check-figure"></a>

### 3. One figure drawn

The program must draw exactly one matplotlib figure. A chart from pandas is a matplotlib figure too.
One figure can hold several panels, for example from `plt.subplots`. The available fonts must draw
every character of the chart's text.

If this check fails, ask for one chart. To compare several charts, ask for panels in one figure.

[Read the full rules for this check](verification.md#check-figure).

<a id="check-parts"></a>

### 4. Only chart parts the verifier checks

Each part of the chart must be a kind that the verifier checks:

- lines, points, bars (also grouped and stacked), pies and filled areas;
- histograms with filled bars and one data set;
- reference lines and bands, from `axhline`, `axvline`, `axhspan` and `axvspan`;
- text: titles, axis labels, legends, tick labels and notes on the chart.

Any other part stops the chart. Examples are error bars, box plots, contours, images, polar or 3D
axes, insets, a second y axis and overlapping panels. The verifier accepts a color bar only for the
colors of a scatter chart.

If this check fails, ask for one of the chart types above. To show a second measure, ask for a
second panel instead of a second y axis.

[Read the full rules for this check](verification.md#check-parts).

<a id="check-axes"></a>

### 5. Honest axes

Each axis must show the data honestly:

- The value axis of bars, histograms and filled areas includes zero. Line and scatter charts can
  zoom in on their data.
- No axis runs backwards.
- Each axis is linear. A log axis passes only when its axis label or the panel title says `log`,
  `logarithmic` or `対数`.
- Each tick label shows the true value at its position.
- Every data point lies inside the axis limits.
- Each chart part sits at its data values on the axes.

If this check fails, ask for the chart without the axis limits or the reversed axis. If you want a
value axis that does not include zero, ask for a line chart or a scatter chart. If you want a log
scale, ask for a log axis whose label says `log`.

[Read the full rules for this check](verification.md#check-axes).

<a id="check-marks"></a>

### 6. Honest marks

Each chart part must show its values honestly:

- Bars and filled areas start at zero, or on top of another bar or area in a stack.
- Grouped bars stand side by side and do not overlap.
- Histogram bars show the true counts, or the density, of their data.
- Pie wedges fill the circle, and each wedge shows its true share.
- The points of a line run in one direction along the x axis.
- Marker sizes or colors that vary have a legend or a color bar that explains them.
- If a panel with two or more series has a legend, the legend names every series.
- Every chart part is visible, and every drawn value is a finite number.

If this check fails, ask for the chart in its plain form. For example, ask for bars from zero and for
a legend entry for each series.

[Read the full rules for this check](verification.md#check-marks).

<a id="check-values"></a>

### 7. Drawn values come from your data

Each drawn value must come from your data, as [Where values can come
from](#where-values-can-come-from) describes. One series cannot show the same category twice.

If this check fails:

- Attach a CSV file that holds the values, or write each value and each label in your request.
- A rounded or scaled value fails, unless the same number is in your data or comes from one of the
  computations above. Ask for the values as your data holds them.

[Read the full rules for this check](verification.md#check-values).

<a id="check-columns"></a>

### 8. Drawn columns match your request

If you attach a CSV file, the verifier compares the columns that the chart draws with the column
names in your request:

- **Production.** If your request names a column, it must name every column that the chart draws.
- **Demo.** The chart must not draw another column in place of a column that your request names.
- If the values fit two columns equally, your request must name one of them.
- A title, axis label or legend must not name a column that the chart does not draw. It also must
  not name another summary, for example `average` on a chart of totals.

The verifier also knows the other names that your administrator declares for a column, and short
Japanese forms such as `月` for `年月`.

If this check fails, write in your request the name of each column that the chart must draw, as the
file spells it.

[Read the full rules for this check](verification.md#check-columns).

<a id="check-attach"></a>

### 9. Image attached to the reply

The browser run returns one PNG image, and Open WebUI stores it with the reply.

If this check fails, try again.

[Read the full rules for this check](verification.md#check-attach).

## What the verifier does not check

- **The program's honesty.** The verifier trusts the program. The program runs before any check, in
  the same sandbox as the verifier's reader. Thus a program that sets out to deceive the verifier
  can do so. The program can also read your attached files and reach your browser's network, as any
  Open WebUI code run can.
- **Text on the chart.** The verifier lists notes and value labels under the chart, but it does not
  judge them.
- **Your intent.** The verifier does not check that the chart shows the quantity that you meant. The
  column names in your request are the only link to your intent.
- **The image itself.** The verifier trusts the browser, matplotlib and the image pixels.
