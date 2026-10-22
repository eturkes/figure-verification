# Blocked chart gallery

Each pair shows a chart that the verifier blocks, beside an honest chart that passes. Every chart is a test case: the generator, `tools/render_gallery.py`, runs each program through the figure reader and the judge, and it stops unless each verdict matches. The rules: [checks.md](checks.md). [日本語版](gallery.ja.md)

- Check 3: [`glyph_missing`](#glyph_missing)
- Check 4: [`raster_image`](#raster_image), [`axes_not_judged`](#axes_not_judged), [`axes_twin`](#axes_twin), [`axes_overlap`](#axes_overlap), [`artist_not_judged`](#artist_not_judged), [`no_data`](#no_data)
- Check 5: [`mark_not_in_data`](#mark_not_in_data), [`scale_not_linear`](#scale_not_linear), [`axis_inverted`](#axis_inverted), [`zero_not_in_limits`](#zero_not_in_limits), [`tick_label_mismatch`](#tick_label_mismatch), [`point_clipped`](#point_clipped)
- Check 6: [`mark_hidden`](#mark_hidden), [`value_not_finite`](#value_not_finite), [`bar_not_from_zero`](#bar_not_from_zero), [`bars_overlap`](#bars_overlap), [`x_not_ordered`](#x_not_ordered), [`hist_counts`](#hist_counts), [`pie_not_whole`](#pie_not_whole), [`area_not_from_zero`](#area_not_from_zero), [`marker_size_varies`](#marker_size_varies), [`marker_color_varies`](#marker_color_varies), [`legend_mismatch`](#legend_mismatch)
- Check 7: [`category_not_unique`](#category_not_unique), [`value_not_found`](#value_not_found), [`label_not_in_request`](#label_not_in_request)
- Check 8: [`column_not_requested`](#column_not_requested), [`column_not_named`](#column_not_named), [`label_not_consistent`](#label_not_consistent)

<a id="check-figure"></a>

## Check 3: One figure drawn

<a id="glyph_missing"></a>

### `glyph_missing`: every character in an available font

The title puts a Japanese character inside mathtext (`$年$`). Mathtext draws with its own fonts, which hold no Japanese characters, so the reader would see an empty box. The Japanese font that the reader registers reaches ordinary text, not mathtext.

| Blocked | Passes |
|---|---|
| ![Blocked: every character in an available font](gallery/mathtext-missing-glyph.png) | ![Passes: every character in an available font](gallery/mathtext-honest.png) |

Request: `Plot 1, 4, 9`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
plt.plot([1, 4, 9])
plt.title("$年$")
```

Passes:

```python
import matplotlib.pyplot as plt
plt.plot([1, 4, 9])
plt.title("$x^2$ growth")
```

</details>

<a id="check-parts"></a>

## Check 4: Only chart parts the verifier checks

<a id="raster_image"></a>

### `raster_image`: no image (`imshow`, `pcolormesh`, `matshow`)

The program draws an image of an array. The verifier cannot read values back from pixels, so it blocks every image.

| Blocked | Passes |
|---|---|
| ![Blocked: no image (`imshow`, `pcolormesh`, `matshow`)](gallery/imshow.png) | ![Passes: no image (`imshow`, `pcolormesh`, `matshow`)](gallery/vector-chart.png) |

Blocked chart's request: `Image of 1, 2, 3, 4`. Passing chart's request: `Bars a 1 and b 2`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
plt.imshow([[1, 2], [3, 4]])
```

Passes:

```python
import matplotlib.pyplot as plt
plt.bar(["a", "b"], [1, 2])
```

</details>

<a id="axes_not_judged"></a>

### `axes_not_judged`: plain axes only: no polar, 3D, inset or secondary axes

The program draws the line on polar axes. The verifier has rules for plain x and y axes alone.

| Blocked | Passes |
|---|---|
| ![Blocked: plain axes only: no polar, 3D, inset or secondary axes](gallery/polar.png) | ![Passes: plain axes only: no polar, 3D, inset or secondary axes](gallery/cartesian-axes.png) |

Blocked chart's request: `Plot 1 and 2`. Passing chart's request: `Plot 0 and 1, then 1 and 2`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
ax = plt.subplot(projection="polar")
ax.plot([0, 1], [1, 2])
```

Passes:

```python
import matplotlib.pyplot as plt
ax = plt.subplot()
ax.plot([0, 1], [1, 2])
```

</details>

<a id="axes_twin"></a>

### `axes_twin`: no twin axes (`twinx`, `twiny`)

A second y axis gives orders a scale of their own, so the crossing and the relative height of the two lines carry no meaning. The chart that passes puts each measure in its own panel.

| Blocked | Passes |
|---|---|
| ![Blocked: no twin axes (`twinx`, `twiny`)](gallery/twin-axes.png) | ![Passes: no twin axes (`twinx`, `twiny`)](gallery/twin-axes-twin.png) |

Request: `Revenue and orders by month`. File: `sales.csv`.

<details><summary>Programs</summary>

Blocked:

```python
import pandas as pd
import matplotlib.pyplot as plt
df = pd.read_csv("/mnt/uploads/sales.csv").groupby("month").sum(numeric_only=True)
ax = plt.gca()
ax.plot(df.index, df["revenue"])
ax.twinx().plot(df.index, df["orders"], color="red")
```

Passes:

```python
import pandas as pd
import matplotlib.pyplot as plt
df = pd.read_csv("/mnt/uploads/sales.csv").groupby("month").sum(numeric_only=True)
fig, (top, bottom) = plt.subplots(2, 1, sharex=True)
top.plot(df.index, df["revenue"])
top.set_ylabel("revenue")
bottom.plot(df.index, df["orders"])
bottom.set_ylabel("orders")
```

</details>

<a id="axes_overlap"></a>

### `axes_overlap`: no overlapping panels

A second panel sits on top of the first and hides part of it.

| Blocked | Passes |
|---|---|
| ![Blocked: no overlapping panels](gallery/overlapping-axes.png) | ![Passes: no overlapping panels](gallery/side-by-side-axes.png) |

Blocked chart's request: `Plot 1 and 2`. Passing chart's request: `Plot 1 and 2, then 2 and 1`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
fig = plt.figure()
fig.add_axes([0.1, 0.1, 0.8, 0.8]).plot([1, 2], [1, 2])
fig.add_axes([0.5, 0.5, 0.4, 0.4]).plot([1, 2], [2, 1])
```

Passes:

```python
import matplotlib.pyplot as plt
fig = plt.figure()
fig.add_axes([0.1, 0.1, 0.35, 0.8]).plot([1, 2], [1, 2])
fig.add_axes([0.55, 0.1, 0.35, 0.8]).plot([1, 2], [2, 1])
```

</details>

<a id="artist_not_judged"></a>

### `artist_not_judged`: no other part (error bars, box plots, contours, added shapes, step histograms)

Error bars fall outside the closed set of chart parts that the verifier checks, so it blocks them. The chart that passes uses checked parts alone: bars, a line, points, a reference line and value labels.

| Blocked | Passes |
|---|---|
| ![Blocked: no other part (error bars, box plots, contours, added shapes, step histograms)](gallery/errorbar.png) | ![Passes: no other part (error bars, box plots, contours, added shapes, step histograms)](gallery/judged-families.png) |

Blocked chart's request: `Plot 3 and 4`. Passing chart's request: `Revenue by region: bars, a line, points, a reference line at 30000 and value labels` with `sales.csv`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
plt.errorbar([1, 2], [3, 4], yerr=[1, 1])
```

Passes:

```python
import pandas as pd
import matplotlib.pyplot as plt
totals = pd.read_csv("/mnt/uploads/sales.csv").groupby("region")["revenue"].sum()
bars = plt.bar(totals.index, totals.values, label="revenue")
plt.plot(totals.index, totals.values, color="black", label="line")
plt.scatter(totals.index, totals.values, color="red", label="points")
plt.axhline(30000, color="gray", linestyle="--")
plt.bar_label(bars)
plt.text(0, 1000, "note")
plt.legend()
```

</details>

<a id="no_data"></a>

### `no_data`: data in every panel

The panel has a title but no data.

| Blocked | Passes |
|---|---|
| ![Blocked: data in every panel](gallery/empty-axes.png) | ![Passes: data in every panel](gallery/axes-with-data.png) |

Request: `Plot 1 and 2`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.set_title("Nothing")
```

Passes:

```python
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.set_title("Something")
ax.plot([1, 2], [1, 2])
```

</details>

<a id="check-axes"></a>

## Check 5: Honest axes

<a id="mark_not_in_data"></a>

### `mark_not_in_data`: each mark at its data values

The line uses axes coordinates (`transform=plt.gca().transAxes`), so it runs from corner to corner whatever the data holds. The two charts look alike; the line that passes sits at its data values.

| Blocked | Passes |
|---|---|
| ![Blocked: each mark at its data values](gallery/line-in-axes-coordinates.png) | ![Passes: each mark at its data values](gallery/line-in-data.png) |

Request: `Plot 0 and 1`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
plt.plot([0, 1], [0, 1], transform=plt.gca().transAxes)
```

Passes:

```python
import matplotlib.pyplot as plt
plt.plot([0, 1], [0, 1])
```

</details>

<a id="scale_not_linear"></a>

### `scale_not_linear`: linear scales; log only when the axis label or panel title says `log`, `logarithmic` or `対数`

A log y axis that no label names makes 1, 10, 100 and 1000 look evenly spaced. The chart that passes says `log scale` in its axis label.

| Blocked | Passes |
|---|---|
| ![Blocked: linear scales; log only when the axis label or panel title says `log`, `logarithmic` or `対数`](gallery/log-scale-unstated.png) | ![Passes: linear scales; log only when the axis label or panel title says `log`, `logarithmic` or `対数`](gallery/log-scale-stated.png) |

Request: `Plot 1, 10, 100, 1000`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
plt.plot([1, 10, 100, 1000])
plt.yscale("log")
```

Passes:

```python
import matplotlib.pyplot as plt
plt.plot([1, 10, 100, 1000])
plt.yscale("log")
plt.ylabel("Value (log scale)")
```

</details>

<a id="axis_inverted"></a>

### `axis_inverted`: no inverted x or y axis

The y axis runs downward, so a rise looks like a fall.

| Blocked | Passes |
|---|---|
| ![Blocked: no inverted x or y axis](gallery/inverted-value-axis.png) | ![Passes: no inverted x or y axis](gallery/upright-axes.png) |

Request: `Plot 1, 4, 9`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
plt.plot([1, 4, 9])
plt.gca().invert_yaxis()
```

Passes:

```python
import matplotlib.pyplot as plt
plt.plot([1, 4, 9])
plt.ylim(0, 10)
```

</details>

<a id="zero_not_in_limits"></a>

### `zero_not_in_limits`: zero inside the value-axis limits of bars, histograms and areas (line and scatter may zoom)

The y axis starts at 30,000, so US revenue (40,000) looks 2.5 times EU revenue (34,000).

| Blocked | Passes |
|---|---|
| ![Blocked: zero inside the value-axis limits of bars, histograms and areas (line and scatter may zoom)](gallery/truncated-bars.png) | ![Passes: zero inside the value-axis limits of bars, histograms and areas (line and scatter may zoom)](gallery/truncated-bars-twin.png) |

Request: `Total revenue by region`. File: `sales.csv`.

<details><summary>Programs</summary>

Blocked:

```python
import pandas as pd
import matplotlib.pyplot as plt
totals = pd.read_csv("/mnt/uploads/sales.csv").groupby("region")["revenue"].sum()
plt.bar(totals.index, totals.values)
plt.ylim(30000, 41000)
```

Passes:

```python
import pandas as pd
import matplotlib.pyplot as plt
totals = pd.read_csv("/mnt/uploads/sales.csv").groupby("region")["revenue"].sum()
plt.bar(totals.index, totals.values)
plt.ylabel("revenue")
```

</details>

<a id="tick_label_mismatch"></a>

### `tick_label_mismatch`: each visible tick label = the value at its position

The tick formatter divides each value by 10, so the axis reads 4,000 where the bar reaches 40,000.

| Blocked | Passes |
|---|---|
| ![Blocked: each visible tick label = the value at its position](gallery/money-labels-scaled.png) | ![Passes: each visible tick label = the value at its position](gallery/money-labels.png) |

Request: `Total revenue by region`. File: `sales.csv`.

<details><summary>Programs</summary>

Blocked:

```python
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
totals = pd.read_csv("/mnt/uploads/sales.csv").groupby("region")["revenue"].sum()
plt.bar(totals.index, totals.values)
plt.gca().yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f"{v / 10:,.0f}"))
```

Passes:

```python
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
totals = pd.read_csv("/mnt/uploads/sales.csv").groupby("region")["revenue"].sum()
plt.bar(totals.index, totals.values)
plt.gca().yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
```

</details>

<a id="point_clipped"></a>

### `point_clipped`: every data point, bar end and reference mark inside the axis limits (pies exempt)

The y limit stops at 5, so the point at 9 falls outside the chart and disappears.

| Blocked | Passes |
|---|---|
| ![Blocked: every data point, bar end and reference mark inside the axis limits (pies exempt)](gallery/clipped-point.png) | ![Passes: every data point, bar end and reference mark inside the axis limits (pies exempt)](gallery/upright-axes.png) |

Request: `Plot 1, 4, 9`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
plt.plot([1, 4, 9], marker="o")
plt.ylim(0, 5)
```

Passes:

```python
import matplotlib.pyplot as plt
plt.plot([1, 4, 9])
plt.ylim(0, 10)
```

</details>

<a id="check-marks"></a>

## Check 6: Honest marks

<a id="mark_hidden"></a>

### `mark_hidden`: every mark and panel visible, with ink

The program hides the bar for b, so the chart seems to hold a alone.

| Blocked | Passes |
|---|---|
| ![Blocked: every mark and panel visible, with ink](gallery/hidden-bars.png) | ![Passes: every mark and panel visible, with ink](gallery/vector-chart.png) |

Request: `Bars a 1 and b 2`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
bars = plt.bar(["a", "b"], [1, 2])
bars[1].set_visible(False)
```

Passes:

```python
import matplotlib.pyplot as plt
plt.bar(["a", "b"], [1, 2])
```

</details>

<a id="value_not_finite"></a>

### `value_not_finite`: every value finite; no point dropped

A missing value (NaN) leaves a silent gap in the line. The chart that passes draws only the points that exist.

| Blocked | Passes |
|---|---|
| ![Blocked: every value finite; no point dropped](gallery/gap-in-line.png) | ![Passes: every value finite; no point dropped](gallery/complete-line.png) |

Blocked chart's request: `Plot 1, 4, 9`. Passing chart's request: `Plot 1, 4, 9 at 0, 1 and 3`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
plt.plot([0, 1, 2, 3], [1, 4, float("nan"), 9])
```

Passes:

```python
import matplotlib.pyplot as plt
plt.plot([0, 1, 3], [1, 4, 9])
```

</details>

<a id="bar_not_from_zero"></a>

### `bar_not_from_zero`: bars from 0, or from the top of a stacked bar

The bars float from 1, so their tops read 2 and 3 on the axis for the values 1 and 2.

| Blocked | Passes |
|---|---|
| ![Blocked: bars from 0, or from the top of a stacked bar](gallery/floating-bars.png) | ![Passes: bars from 0, or from the top of a stacked bar](gallery/vector-chart.png) |

Request: `Bars a 1 and b 2`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
plt.bar(["a", "b"], [1, 2], bottom=1)
plt.ylim(0, 4)
```

Passes:

```python
import matplotlib.pyplot as plt
plt.bar(["a", "b"], [1, 2])
```

</details>

<a id="bars_overlap"></a>

### `bars_overlap`: no overlapping bars

The second series sits exactly on the first and hides it: the chart shows two bars where the data holds four.

| Blocked | Passes |
|---|---|
| ![Blocked: no overlapping bars](gallery/overplotted-bars.png) | ![Passes: no overlapping bars](gallery/overplotted-bars-side-by-side.png) |

Request: `Bars a 1 and b 2, then a 3 and b 4`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
plt.bar(["a", "b"], [1, 2])
plt.bar(["a", "b"], [3, 4])
```

Passes:

```python
import matplotlib.pyplot as plt
plt.bar([-0.2, 0.8], [1, 2], width=0.4, label="first")
plt.bar([0.2, 1.2], [3, 4], width=0.4, label="second")
plt.xticks([0, 1], ["a", "b"])
plt.legend()
```

</details>

<a id="x_not_ordered"></a>

### `x_not_ordered`: line x values in one direction

The points are not in x order, so the line runs forward, doubles back and suggests a loop that the data does not hold.

| Blocked | Passes |
|---|---|
| ![Blocked: line x values in one direction](gallery/unordered-line.png) | ![Passes: line x values in one direction](gallery/unordered-line-sorted.png) |

Request: `Points 1 1, 3 9, 2 4`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
plt.plot([1, 3, 2], [1, 9, 4])
```

Passes:

```python
import matplotlib.pyplot as plt
plt.plot([1, 2, 3], [1, 4, 9])
```

</details>

<a id="hist_counts"></a>

### `hist_counts`: histogram heights = counts or density of its data over its bins

The bin range stops at 4, so the value 9 drops out of the histogram without a trace.

| Blocked | Passes |
|---|---|
| ![Blocked: histogram heights = counts or density of its data over its bins](gallery/hist-dropped-values.png) | ![Passes: histogram heights = counts or density of its data over its bins](gallery/hist-all-values.png) |

Request: `Histogram of 1, 2, 2, 3, 9`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
plt.hist([1, 2, 2, 3, 9], bins=3, range=(0, 4))
```

Passes:

```python
import matplotlib.pyplot as plt
plt.hist([1, 2, 2, 3, 9], bins=3)
```

</details>

<a id="pie_not_whole"></a>

### `pie_not_whole`: pie wedges fill 360°; each span = its share of the total

With `normalize=False`, the wedges for 0.1, 0.2 and 0.3 fill 60 % of the circle, and the gap reads as a missing slice.

| Blocked | Passes |
|---|---|
| ![Blocked: pie wedges fill 360°; each span = its share of the total](gallery/partial-pie.png) | ![Passes: pie wedges fill 360°; each span = its share of the total](gallery/whole-pie.png) |

Blocked chart's request: `Pie of 0.1, 0.2 and 0.3`. Passing chart's request: `Pie of a 0.1, b 0.2 and c 0.3`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
plt.pie([0.1, 0.2, 0.3], labels=["a", "b", "c"], normalize=False)
```

Passes:

```python
import matplotlib.pyplot as plt
plt.pie([0.1, 0.2, 0.3], labels=["a", "b", "c"])
```

</details>

<a id="area_not_from_zero"></a>

### `area_not_from_zero`: areas from 0, or from the top of a stacked area

The area starts at 5, so its filled heights show 1, 3 and 2 for the values 6, 8 and 7.

| Blocked | Passes |
|---|---|
| ![Blocked: areas from 0, or from the top of a stacked area](gallery/floating-area.png) | ![Passes: areas from 0, or from the top of a stacked area](gallery/area-from-zero.png) |

Blocked chart's request: `Fill between 5 and 6, 8, 7`. Passing chart's request: `Fill 6, 8, 7 at 1, 2, 3`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
plt.fill_between([1, 2, 3], [5, 5, 5], [6, 8, 7])
plt.ylim(0, 10)
```

Passes:

```python
import matplotlib.pyplot as plt
plt.fill_between([1, 2, 3], [6, 8, 7])
plt.ylim(0, 10)
```

</details>

<a id="marker_size_varies"></a>

### `marker_size_varies`: varying scatter sizes: a size legend

The points have different sizes, and nothing says what a size means.

| Blocked | Passes |
|---|---|
| ![Blocked: varying scatter sizes: a size legend](gallery/sizes-unexplained.png) | ![Passes: varying scatter sizes: a size legend](gallery/sizes-explained.png) |

Blocked chart's request: `Points 1 3 and 2 4`. Passing chart's request: `Points 1 3 and 2 4, sized 10 and 400`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
plt.scatter([1, 2], [3, 4], s=[10, 400])
```

Passes:

```python
import matplotlib.pyplot as plt
dots = plt.scatter([1, 2], [3, 4], s=[10, 400])
plt.legend(*dots.legend_elements("sizes"))
```

</details>

<a id="marker_color_varies"></a>

### `marker_color_varies`: varying scatter colors: a colorbar or a color legend

The points have different colors, and nothing says what a color means.

| Blocked | Passes |
|---|---|
| ![Blocked: varying scatter colors: a colorbar or a color legend](gallery/colors-unexplained.png) | ![Passes: varying scatter colors: a colorbar or a color legend](gallery/colors-explained.png) |

Request: `Points 1 3 and 2 4`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
plt.scatter([1, 2], [3, 4], c=[1, 2])
```

Passes:

```python
import matplotlib.pyplot as plt
dots = plt.scatter([1, 2], [3, 4], c=[1, 2])
plt.colorbar(dots)
```

</details>

<a id="legend_mismatch"></a>

### `legend_mismatch`: legend entries name drawn series; 2 or more series in a panel with a legend: every series named

The legend names one of the two lines, so the reader cannot tell what the other line shows.

| Blocked | Passes |
|---|---|
| ![Blocked: legend entries name drawn series; 2 or more series in a panel with a legend: every series named](gallery/legend-misses-a-series.png) | ![Passes: legend entries name drawn series; 2 or more series in a panel with a legend: every series named](gallery/legend-names-both.png) |

Request: `Plot 1, 4, 9 and 2, 3, 5`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
first, = plt.plot([1, 4, 9], label="first")
plt.plot([2, 3, 5], label="second")
plt.legend(handles=[first])
```

Passes:

```python
import matplotlib.pyplot as plt
plt.plot([1, 4, 9], label="first")
plt.plot([2, 3, 5], label="second")
plt.legend()
```

</details>

<a id="check-values"></a>

## Check 7: Drawn values come from your data

<a id="category_not_unique"></a>

### `category_not_unique`: each category once per series

Two bars carry the label a, so the reader cannot tell which value belongs to a.

| Blocked | Passes |
|---|---|
| ![Blocked: each category once per series](gallery/repeated-category.png) | ![Passes: each category once per series](gallery/unique-categories.png) |

Blocked chart's request: `Bars a 1 and a 2`. Passing chart's request: `Bars a 1 and b 2`.

<details><summary>Programs</summary>

Blocked:

```python
import pandas as pd
import matplotlib.pyplot as plt
pd.Series([1, 2], index=["a", "a"]).plot(kind="bar")
```

Passes:

```python
import pandas as pd
import matplotlib.pyplot as plt
pd.Series([1, 2], index=["a", "b"]).plot(kind="bar")
```

</details>

<a id="value_not_found"></a>

### `value_not_found`: every drawn value found in a source

The bars show 50,000 and 60,000, but the file's revenue totals are 34,000 and 40,000.

| Blocked | Passes |
|---|---|
| ![Blocked: every drawn value found in a source](gallery/made-up-values.png) | ![Passes: every drawn value found in a source](gallery/truncated-bars-twin.png) |

Request: `Total revenue by region`. File: `sales.csv`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
plt.bar(["EU", "US"], [50000, 60000])
```

Passes:

```python
import pandas as pd
import matplotlib.pyplot as plt
totals = pd.read_csv("/mnt/uploads/sales.csv").groupby("region")["revenue"].sum()
plt.bar(totals.index, totals.values)
plt.ylabel("revenue")
```

</details>

<a id="label_not_in_request"></a>

### `label_not_in_request`: every typed category label in the request

The request types numbers alone, and the program invents the labels apples, pears and plums. The two charts look the same; the request makes the difference.

| Blocked | Passes |
|---|---|
| ![Blocked: every typed category label in the request](gallery/labels-not-typed.png) | ![Passes: every typed category label in the request](gallery/labels-typed.png) |

Blocked chart's request: `Plot 3, 5, 9`. Passing chart's request: `Plot apples 3, pears 5, plums 9`.

<details><summary>Programs</summary>

Blocked:

```python
import matplotlib.pyplot as plt
plt.bar(["apples", "pears", "plums"], [3, 5, 9])
```

Passes:

```python
import matplotlib.pyplot as plt
plt.bar(["apples", "pears", "plums"], [3, 5, 9])
```

</details>

<a id="check-columns"></a>

## Check 8: Drawn columns match your request

<a id="column_not_requested"></a>

### `column_not_requested`: no column that the request names replaced by another

The request asks for revenue, and the chart draws orders, a column that the request does not name.

| Blocked | Passes |
|---|---|
| ![Blocked: no column that the request names replaced by another](gallery/substituted-column.png) | ![Passes: no column that the request names replaced by another](gallery/truncated-bars-twin.png) |

Blocked chart's request: `Chart revenue by region` with `sales.csv`. Passing chart's request: `Total revenue by region` with `sales.csv`.

<details><summary>Programs</summary>

Blocked:

```python
import pandas as pd
import matplotlib.pyplot as plt
totals = pd.read_csv("/mnt/uploads/sales.csv").groupby("region")["orders"].sum()
plt.bar(totals.index, totals.values)
```

Passes:

```python
import pandas as pd
import matplotlib.pyplot as plt
totals = pd.read_csv("/mnt/uploads/sales.csv").groupby("region")["revenue"].sum()
plt.bar(totals.index, totals.values)
plt.ylabel("revenue")
```

</details>

<a id="column_not_named"></a>

### `column_not_named`: production: if the request names or excludes a column, it names every drawn column

Production rule: the request names revenue but not month, which the chart also draws. The two charts are the same; the request that also names month passes.

| Blocked | Passes |
|---|---|
| ![Blocked: production: if the request names or excludes a column, it names every drawn column](gallery/unnamed-column-strict.png) | ![Passes: production: if the request names or excludes a column, it names every drawn column](gallery/named-columns-strict.png) |

Blocked chart's request: `Total revenue` with `sales.csv`. Passing chart's request: `Total revenue by month` with `sales.csv`.

<details><summary>Programs</summary>

Blocked:

```python
import pandas as pd
import matplotlib.pyplot as plt
totals = pd.read_csv("/mnt/uploads/sales.csv").groupby("month")["revenue"].sum()
plt.bar(totals.index, totals.values)
```

Passes:

```python
import pandas as pd
import matplotlib.pyplot as plt
totals = pd.read_csv("/mnt/uploads/sales.csv").groupby("month")["revenue"].sum()
plt.bar(totals.index, totals.values)
```

</details>

<a id="label_not_consistent"></a>

### `label_not_consistent`: titles, axis labels, legends and colorbar labels: no undrawn column; over a total or mean per group, no other summary

The bars show revenue, but the title names orders, another column of the file.

| Blocked | Passes |
|---|---|
| ![Blocked: titles, axis labels, legends and colorbar labels: no undrawn column; over a total or mean per group, no other summary](gallery/title-names-another-column.png) | ![Passes: titles, axis labels, legends and colorbar labels: no undrawn column; over a total or mean per group, no other summary](gallery/title-consistent.png) |

Request: `Total revenue by region`. File: `sales.csv`.

<details><summary>Programs</summary>

Blocked:

```python
import pandas as pd
import matplotlib.pyplot as plt
totals = pd.read_csv("/mnt/uploads/sales.csv").groupby("region")["revenue"].sum()
plt.bar(totals.index, totals.values)
plt.title("Orders by region")
```

Passes:

```python
import pandas as pd
import matplotlib.pyplot as plt
totals = pd.read_csv("/mnt/uploads/sales.csv").groupby("region")["revenue"].sum()
plt.bar(totals.index, totals.values)
plt.title("Total revenue by region")
plt.xlabel("region")
plt.ylabel("revenue")
```

</details>
