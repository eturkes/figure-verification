---
paths:
  - "**/src/verifier/figure/**"
  - "**/tests/test_figure*.py"
  - "**/tests/figure_corpus/**"
  - "**/webui/paste_in/**"
  - "**/.agent/contracts/m19*.md"
---

# Figure integrity — the verification model (M19 law)

Binding sources: `.agent/spec.md` `Intent` + Decisions "Integrity-redesign rulings" + "M19 readings". This file = the rule matrix every M19 unit implements; a rule changes here first.

## Trust + flow

- Program = model-authored bytes, run UNCHANGED in OWUI's Pyodide sandbox; non-adversarial (ruling 7): no pre-run gate, the program shares the reader's interpreter. Python itself rejects invalid Python.
- Wrapper (RPC code) = loader prelude → reader source (base64, `<figure-reader>`) installs hooks → program exec'd as `<verified-figure>` (its stdout → a sink, warnings recorded, any exception caught) → every figure the program shows, or leaves open at its end, is drawn once + described → stdout = ONE tagged description line + ONE PNG line (exactly one figure only).
- Reader = trusted FACT reporter (`src/verifier/figure/reader.py`, matplotlib + pandas imported lazily; the one `verifier` module outside stdlib). Judge = stdlib core (`src/verifier/figure/`) = every DECISION. A fact the judge needs is reported; a decision never lives in the reader.
- Hooks: `Artist.__init__` → `site` = innermost `<verified-figure>` frame line, `origin` = qualname of the OUTERMOST frame in `matplotlib.axes._axes` / `matplotlib.axes._base` / `matplotlib.stackplot` (pyplot + pandas frames skipped; `plt.bar` ≡ `ax.bar`; `hist` wins over its inner `bar`). Call recorder on axis-altering methods → `calls` (slot → first program line). Input recorders on `hist` / `pie` / `fill_between` / `stackplot` attach the call's arrays to the artists they return. `site` + `calls` are DISPLAY ONLY (ruling 13); `origin` = family attribution, never proof of geometry — final artist properties decide every rule.
- Sandbox = Pyodide 0.28.3: matplotlib 3.8.4, pandas 2.3.1, numpy 2.2.5. Gate host = matplotlib 3.9.4 (3.8.4 ships no cp313 wheel) ⇒ every host-green corpus claim is a 3.9.4 claim until its Pyodide leg (`.agent/measurements/`) reruns. Measured divergence: `axhspan`/`axvspan` = `Rectangle` (3.9) vs `Polygon` (3.8) ⇒ both shapes judged.

## Checks (Show checks rows, in order; a reason maps to its check)

| check | reasons |
|---|---|
| `program` | `no_tool_call` `no_user` |
| `run` | `no_browser` `browser_timeout` `browser_error` `browser_no_answer` `reply_malformed` `sandbox_unavailable` `sandbox_error` `no_image` `no_description` `program_syntax_error` `program_error` `module_not_available` `figure_too_large` |
| `figure` | `no_figure` `multiple_figures` `glyph_missing` |
| `parts` | `raster_image` `axes_not_judged` `axes_twin` `axes_overlap` `artist_not_judged` `no_data` |
| `axes` | `mark_not_in_data` `scale_not_linear` `axis_inverted` `tick_label_mismatch` `point_clipped` `zero_not_in_limits` |
| `marks` | `mark_hidden` `value_not_finite` `bar_not_from_zero` `bars_overlap` `category_not_unique` `x_not_ordered` `hist_counts` `pie_not_whole` `area_not_from_zero` `marker_size_varies` `marker_color_varies` `legend_mismatch` |
| `values` | `csv_too_large` `csv_not_parsable` `work_budget_exceeded` `value_not_found` `label_not_in_request` |
| `columns` | `column_not_requested` `column_not_named` `label_not_consistent` |
| `attach` | `publish_failed` |

Judge order = figure → parts → axes → marks → values → columns; inside a stage: figures, axes, artists in description order, first failure wins. Each failure carries the `site` (artist) or the LAST program `calls` line (call) that set the offending property, else none (listing unmarked).

## Closed artist set (parts)

- Figure: exactly one shown figure (`no_figure` / `multiple_figures`). Children: patch · judged axes · `suptitle` (judged title) · figure legends (judged) · figure texts (listed) · anything else → `artist_not_judged`; `FigureImage` → `raster_image`.
- Axes: class exactly `Axes`, owned by the figure (`fig.axes`), never a child of another axes (inset) → else `axes_not_judged` (polar, 3D, `SecondaryAxis`, inset). A colorbar axes passes only as the colorbar of a judged scatter, holding its own solids + dividers alone, its tick labels naming their values. A rotated bar is no bar. Two judged axes sharing an axis at the same position = `axes_twin` (G2); overlapping positions otherwise = `axes_overlap`. Each panel judged alone.
- Axes children = structural slots (patch, 4 spines, x/y axis, 3 titles, legend) + data artists keyed (class, origin):

| family | class | origin |
|---|---|---|
| line | `Line2D` | `Axes.plot` `Axes.step` |
| scatter | `PathCollection` | `Axes.scatter` |
| bar | `Rectangle` in a `BarContainer` | `Axes.bar` `Axes.barh` |
| hist | `Rectangle` in a `BarContainer` | `Axes.hist` (histtype `bar`, one dataset) |
| pie | `Wedge` (+ its label/autopct `Text`) | `Axes.pie` |
| area | `PolyCollection` with recorded arrays | `Axes.fill_between` `stackplot` |
| area outline | `Line2D` = an area band's top edge | `Axes.plot` |
| reference | `Line2D` / `Rectangle` / `Polygon` | `Axes.axhline` `Axes.axvline` `Axes.axhspan` `Axes.axvspan` |
| text (listed, never judged) | `Text` `Annotation` | `Axes.text` `Axes.annotate` `Axes.bar_label` |

  Anything else → `artist_not_judged` naming class + origin (errorbar, boxplot, violin, contour, hexbin, quiver, table, user patches, `fill_betweenx`, step/stepfilled hist, …); `AxesImage` / `QuadMesh` from `imshow`/`pcolormesh`/`matshow` → `raster_image`. An axes holding no data artist → `no_data`.

## Axes rules

- `mark_not_in_data`: a data artist's data-bearing transform ≠ `transData` (line/area/pie: `get_transform`; bar: `get_data_transform`; scatter: `get_offset_transform`); reference marks: their data coordinate on the blended data axis (user: closed reference family).
- `scale_not_linear` (R3): a non-linear axis passes only when it is `log` AND that axis label or the panel title names it (`log`, `logarithmic`, `対数`, word-bounded / containment for JA); every other scale blocks.
- `axis_inverted`: either axis inverted (ruling 3; both axes).
- `tick_label_mismatch`: a visible non-empty major tick label in view must denote its position. Category axis: the category at that position. Date axis: a trusted date formatter (matplotlib.dates / pandas) passes; any other label must parse (ISO `YYYY-MM-DD[ HH:MM[:SS]]` | `YYYY-MM`) to the reader's date at that position. Numeric axis with a value role: the label parses as a number (NFKC; `−`→`-`; mathtext `$\mathdefault{…}$`, `10^{k}`, `a\times10^{k}`; `,` thousands; one leading `$ ¥ € £`; trailing `%` ⇒ candidates v/100 and v; one SI prefix (`1k` at 1000), powers `b^{k}` exact) whose value × 10^order + offset (ScalarFormatter) lies within half a unit of its last shown digit of the position. Numeric key axis carrying set labels (`set_ticklabels` / pandas / FixedFormatter) = a LABELLED KEY axis: its labels are keys (values row), not numbers.
- `point_clipped`: any drawn data coordinate (points, bar base + top, band vertices, every reference coordinate) outside the view interval; pie wedges are exempt (matplotlib draws them unclipped).
- `zero_not_in_limits` (R1): a magnitude mark (bar, hist, area) ⇒ 0 inside its value-axis view interval. Line + scatter may autoscale.

## Mark rules

- `mark_hidden`: a hidden axes, or a data artist not visible, alpha 0, or drawing no ink (transparent face + edge, no line and no marker, zero marker size).
- `value_not_finite`: NaN / ±inf among drawn data or recorded inputs, or a band that drew fewer points than its call received (a dropped point).
- `bar_not_from_zero` (G1, R1): every bar's base = 0, or (stacked) exactly the far end of another bar at the same position + thickness on the same side of 0.
- `bars_overlap`: two bars' rectangles overlap with positive area (grouped bars sit side by side).
- `category_not_unique`: two points of one series share a key (G8 overplot).
- `x_not_ordered` (G9): a line's key positions run both ways (monotone either way passes).
- `hist_counts`: hist rects contiguous on the recorded bin edges, heights = counts (or density) of the recorded inputs over those edges (numpy semantics, last bin closed); an input outside the edges, weights, `cumulative` or > 1 dataset blocks.
- `pie_not_whole`: wedges share one radius + width (an exploded centre passes), spans contiguous, total 360°, each span = 360 · value / Σ values (recorded inputs; |Δ| ≤ 1e-4°: matplotlib computes angles in float32); a partial `normalize=False` pie misses 360°.
- `area_not_from_zero`: each band GROUNDED: its base edge all zero, or exactly the far edge of a grounded band at the same x (bands resting only on each other block); arrays = the final polygon read back in the `fill_between` layout.
- `marker_size_varies` / `marker_color_varies`: a scatter collection whose sizes / face colours vary passes only with a size legend from that collection's `legend_elements` / a colorbar of that collection.
- `legend_mismatch`: each legend entry names one judged mark (handle = that artist/container anywhere in the figure, or a proxy with a mark's label + colour), or is a `legend_elements` key of a judged scatter; with ≥ 2 series (line, points, bars, area) in a legended axes, every one named; pies + reference marks may stay unnamed.

## Values (ruling 4; R2, R4; user: series filter, ties)

- Series = one line · scatter collection · bar container · pie · area band · reference mark · hist input. Point = (key, value); key = category (category axis), reader ISO date (date axis), number (numeric axis), label text or position slot (labelled key axis: slot j = round(p) when |p − j| < 0.5; an unlabelled slot binds positionally to the explanation's key order).
- Sources: each attached CSV (`csvread` profile; non-profile columns unusable) + the request (NFKC numbers incl. `,` thousands as both readings; integer ranges `a through b`, `a to b`, `a–b`, `a〜b`/`a~b`, `aからbまで`, ≤ 10,000 terms; ASCII hyphen never a range).
- CSV explanations (closed): `raw(K,V)` · `index(V)` (row position) · `group(K,V,r)` r ∈ sum mean min max · `count(K)` · scalar `reduce(V,r)` / raw cell (reference marks). A series whose legend label equals cell values of column C draws from rows where C = label (user). Matching = injective rows (a row backs one point) with exact binary64 values (stacked: fl(base + c) = top); a strict subset passes + publishes `N of M` (R2); no other pre-reduction filter.
- Per value EITHER (ruling 4): one CSV explanation per series, any point it leaves explained by request numbers (value) + request keys (numeric key ∈ numbers or default positions; text key ∈ casefolded NFKC request, R4 → else `label_not_in_request`). Mark-intrinsic arithmetic (stack offsets, hist counts, pie shares) is the mark's rule. Unexplained point ⇒ `value_not_found` (fix: attach a CSV or write the values out). No source at all ⇒ integrity alone, disclosed.
- Ties: ≥ 2 explanations with different column sets fully explain one series ⇒ the request breaks it when it names the columns of exactly one, else `column_not_requested` (user). Same columns, different reductions (group of 1 ≡ raw) ⇒ canonical = raw, then the first of sum mean min max.

## Columns

- Drawn columns per CSV = every explanation's K and V; a label column C filters rows (R6) and draws nothing. Anchoring = the shipped matcher (`anchoring.py`, moved from `pysrc/verify.py`): substitution (demo) | strict (production), aliases, short words + suffixes, Q38 stops + negation.
- G10 (`label_not_consistent`): titles, axis labels, suptitle, legend entries, colorbar label naming a header column not drawn; over a reduction, another reduction's summary word.
- Publication (tier 3): per-group counts beside every reduction (G11), `N of M` subsets, listed on-chart text, integrity-only status.
