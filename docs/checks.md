# Figure checks: a short guide

The verifier shows a chart only when the chart passes the 9 checks below. Each row of **Show
checks** links to its check here. For every rule in detail, read the [full
reference](verification.md). [日本語版](checks.ja.md)

A pass means that the chart obeys these rules and, if you supplied data, that its values come from
that data. A pass does not mean that the chart answers your question. The verifier does not judge
text on the chart. It trusts the program, so a program that sets out to deceive it can do so. Like
any code that Open WebUI runs, the program can read your attached files and reach your browser's
network.

<a id="check-program"></a>

### 1. Chart program received from the model

The model must send its program through the chart tool. If this check fails, ask again.
[Details](verification.md#check-program)

<a id="check-run"></a>

### 2. Program run in your browser

The program must run without an error in the Open WebUI sandbox. It can use numpy, pandas and
matplotlib, but not seaborn. If this check fails, keep the chat tab open and try again.
[Details](verification.md#check-run)

<a id="check-figure"></a>

### 3. One figure drawn

The program must draw exactly one matplotlib figure. One figure can hold several panels.
[Details](verification.md#check-figure)

<a id="check-parts"></a>

### 4. Only chart parts the verifier checks

The chart can use lines, points, bars, histograms, pies, filled areas, reference lines and text. Any
other part stops the chart, for example error bars, a box plot, an image or a second y axis.
[Details](verification.md#check-parts)

<a id="check-axes"></a>

### 5. Honest axes

Each axis must be linear and run in its normal direction, and every data point must be inside the
axis limits. The value axis of a bar, histogram or area chart must include zero. A log axis passes
only when its label or the panel title says `log`. If you want an axis without zero, ask for a line
or scatter chart. [Details](verification.md#check-axes)

<a id="check-marks"></a>

### 6. Honest marks

Bars and filled areas must start at zero or on top of a stack, and bars must not overlap. Histogram
bars must show the true counts, and pie wedges the true shares. The points of a line must be in x
order. Marker sizes or colors that vary need a legend or a color bar, and a legend must name every
series. [Details](verification.md#check-marks)

<a id="check-values"></a>

### 7. Drawn values come from your data

Each drawn value must be a value in your CSV file or a number in your request. It can also be a
summary per group, such as a total, or a simple computation, such as a running total or a share. If
this check fails, attach the CSV file or write the values and labels in your request. With no file
and no numbers, the verifier checks the other rules alone. [Details](verification.md#check-values)

<a id="check-columns"></a>

### 8. Drawn columns match your request

If you attach a CSV file, write in your request the name of each column that the chart must draw. A
title, axis label or legend must not name a column or a summary that the chart does not show.
[Details](verification.md#check-columns)

<a id="check-attach"></a>

### 9. Image attached to the reply

Open WebUI must store the chart image with the reply. If this check fails, try again.
[Details](verification.md#check-attach)
