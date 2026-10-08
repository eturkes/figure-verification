# Figure verification: what the verifier checks

This reference describes the checks that the figure verifier runs in Open WebUI. It applies to the
current release on the `main` branch. Each row of the **Show checks** list under a chart reply links
to its section here. For the Japanese version, read [verification.ja.md](verification.ja.md).

## What a verified figure means

A language model writes a short Python program that draws one chart. The model never supplies a
plotted number. The verifier examines the program, recomputes every plotted value from data that
you supplied, and releases the chart only when every check passes. Otherwise the reply shows
`Figure verification failed, no image produced`.

The verifier gives three kinds of assurance:

1. **Provenance.** The verifier's own code computes every plotted value again from your CSV file,
   or from the formula in your request.
2. **Integrity.** The chart obeys a closed set of drawing rules: for example, bars start at zero and
   no row is left out.
3. **Interpretation.** A passed reply states in plain words what the verifier checked: the chart
   type, the columns, the grouping and the row counts.

The verifier never claims that the chart answers your question. A chart can show correct numbers of
a different quantity than you meant, for example a sum where you wanted a mean. Read the
interpretation under the chart to see what the verifier checked.

The verifier trusts these parts and does not verify them. They are the browser, the Python sandbox
of Open WebUI (Pyodide), its plotting library and the image pixels.

## How to read "Show checks"

**Show checks** lists the 11 checks in the order that they run. Each row shows one of three states:

- ✓ **passed**: the check completed.
- ✗ **failed**: the check stopped the figure. The row shows the reason.
- – **not checked**: an earlier check failed, so this check did not run.

Click a row to open it. The opened row shows what the check does, the program lines that it read,
the reason for a failure, and a link to this reference. When the verifier knows the exact place of
a fault, it marks that code in the listing. A fault in your file, your request or a limit has no
place in the program. The listing then shows the related lines without a mark.

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

<a id="check-data"></a>

### 2. An attached file or a formula in your request

The verifier needs data that you supplied. It reads one of these:

- a CSV file that you attached to the chat, or
- one formula and one interval that you wrote in your request (see
  [Formulas in a request](#formulas-in-a-request)).

| Reason | Meaning |
|---|---|
| `no_user` | The request has no signed-in user. |
| `no_target` | No CSV file or request formula is available that the verifier can read. |

<a id="check-readable"></a>

### 3. Readable Python

Before it examines the program, the verifier reads it as text. The program must be valid UTF-8,
contain no NUL character, and stay within the size limits in [Limits](#limits). Then the verifier
splits the program into Python tokens, checks the brackets and the indentation, and parses the
syntax.

| Reason | Meaning |
|---|---|
| `source_too_large` | The program is too long. |
| `source_not_utf8` | The program is not valid UTF-8 text. |
| `source_has_nul` | The program contains a NUL character. |
| `line_too_long` | A line of the program is too long. |
| `source_not_tokenizable` | The program cannot be read as Python tokens. |
| `too_many_tokens` | The program has too many tokens. |
| `nesting_too_deep` | The program nests brackets too deeply. |
| `unbalanced_brackets` | The program has unbalanced brackets. |
| `indent_too_deep` | The program indents too deeply. |
| `source_not_parsable` | The program is not valid Python. |

<a id="check-accepted"></a>

### 4. Accepted Python only

The verifier accepts a fixed set of Python. Anything outside the set stops the check, also when
Python could run it. The set is small on purpose: every accepted construct has a known effect on the
chart.

**Imports.** Exactly these three, each with its fixed alias:

- `import matplotlib.pyplot as plt`
- `import numpy as np`
- `import pandas as pd`

**Statements.** The verifier accepts an import, an assignment to one plain name (`name = ...`), and
a function call as a statement. It refuses loops, conditions, function definitions, `with`, `try`,
`from ... import` and augmented assignment (`+=`). The program must assign a name before it uses
the name. The verifier does not accept a name that starts with `_`.

**Function calls and their arguments.** Each call accepts only the keyword arguments listed.

| Call | Accepted keyword arguments |
|---|---|
| `pd.read_csv` | none |
| `np.linspace` | `num` |
| `np.arange` | none |
| `np.sin`, `np.cos`, `np.tan`, `np.exp`, `np.log`, `np.sqrt`, `np.abs` | none |
| `plt.plot` | `label`, `color`, `marker`, `linestyle` |
| `plt.scatter` | `label`, `color`, `marker` |
| `plt.bar`, `plt.barh` | `label`, `color` |
| `plt.title`, `plt.xlabel`, `plt.ylabel`, `plt.legend`, `plt.grid` | none |
| `plt.figure` | `figsize` (a pair of numbers) |
| `plt.tight_layout` | none |
| `plt.xticks` | `rotation` |
| `plt.show` | none |

`plt.figure`, `plt.tight_layout` and `plt.xticks` accept no positional argument.

**Grouping.** One chain groups the rows of a CSV file and reduces one column per group:

```python
totals = df.groupby("region")["revenue"].sum()
```

The reduction is one of `sum`, `mean`, `min` or `max`, with no argument. The group key and the
column must each be one fixed name in quotes. The chart then draws `totals.index` (the groups) as x
and `totals.values` as y, or the series draws itself with `.plot(kind=...)`.

The chain can also end in `.reset_index()`. That call turns the series back into a table with two
columns, so the chart must select both columns by name:

```python
table = df.groupby("region")["revenue"].sum().reset_index()
plt.bar(table["region"], table["revenue"])
```

The chart cannot use the `index` of such a table, which numbers its rows, and the table cannot draw
itself with `.plot`.

**Pandas plotting.** A reduced series can draw itself with `.plot(kind=...)`, where `kind` is `bar`,
`barh` or `line`. This call takes no positional argument and accepts the keywords `kind` and `color`
alone.

**Values.** The verifier accepts number literals, text literals, `True`, `False`, `np.pi` and
`np.e`. It also accepts the attributes `index` and `values` of a bound name, and a column that one
fixed name selects: `df["revenue"]`.

**Operators.** The verifier accepts `+`, `-`, `*`, `/`, `**` and a leading minus sign. It refuses
comparisons, lists, dictionaries, comprehensions, f-strings and `lambda`. It also refuses tuples,
except the `figsize` pair.

| Reason | Meaning |
|---|---|
| `statement_not_admitted` | The program uses a statement that the verifier does not accept. |
| `expression_not_admitted` | The program uses an expression that the verifier does not accept. |
| `import_not_admitted` | The program has an import that the verifier does not accept. |
| `assign_target_not_admitted` | The program assigns to a target that the verifier does not accept. |
| `call_target_not_admitted` | The program calls a function that the verifier does not accept. |
| `keyword_not_admitted` | A call passes an argument that the verifier does not accept. |
| `attribute_not_admitted` | The program uses an attribute that the verifier does not accept. |
| `operator_not_admitted` | The program uses an operator that the verifier does not accept. |
| `literal_not_admitted` | The program uses a literal value that the verifier does not accept. |
| `name_not_bound` | The program uses a name that it does not define. |
| `column_not_literal` | A column selection or grouping is not written as one fixed column name. |

<a id="check-chart"></a>

### 5. Chart read from the program

The verifier reads which chart the program draws. Every statement must contribute to that chart: a
statement whose effect the verifier cannot state stops the check.

A chart from a **CSV file** has this shape:

1. One `df = pd.read_csv("/mnt/uploads/<file name>")` with one fixed file name.
2. One plot call of x and y. The x and y are columns of that file, `df["region"]` or a name
   assigned to one. They can also be the `index` and `values` of a grouping, or the two named
   columns of a reset grouping. A grouping can also draw itself with `.plot(kind=...)`.

A chart from a **formula** has this shape:

1. One grid of x values from `np.linspace(start, stop, count)` or `np.arange(start, stop, step)`.
   The `np.linspace` count is a whole number written as a number; without it, the grid has 50
   points. The `np.arange` start, stop and step must each be a whole number within ±2\*\*52, written
   as a number or as simple arithmetic on numbers. The step must not be zero and must point from
   start toward stop, and the grid stops before `stop`. A grid has between 2 and 100,000 points.
2. One y expression computed from that grid with the accepted functions and operators.
3. One `plt.plot(x, y)` or `plt.scatter(x, y)`. A formula chart cannot be a bar chart.

A program cannot import pandas and also use a formula grid. In both shapes:

- A direct plot call (`plt.plot`, `plt.scatter`, `plt.bar` or `plt.barh`) takes exactly two
  positional arguments, x and y. The program draws one series.
- `plt.title`, `plt.xlabel` and `plt.ylabel` take one text literal each, and the program calls each
  at most once. `plt.legend()` and `plt.grid()` can appear once.
- `plt.figure(figsize=(width, height))` must come before any statement that draws.
- The program assigns each name once and uses every name that it assigns.
- `plt.show()` is the last statement.

| Reason | Meaning |
|---|---|
| `no_mark` | The verifier finds no plot call that it can read as the chart. |
| `multiple_marks` | The program draws more than one series. |
| `mark_arity_not_projected` | A plot call does not take exactly two arguments, x and y. |
| `mark_not_valid_for_arm` | A formula chart cannot use this plot type. |
| `x_not_a_grid` | The plot call does not take x directly from np.linspace or np.arange. |
| `y_not_over_grid` | The y values are not computed from the x grid. |
| `grid_not_representable` | The verifier cannot use the bounds or point count of the x grid. |
| `expression_not_projected` | The verifier cannot state what an expression computes. |
| `label_not_literal` | A label, title or style call has a form that the verifier does not accept. |
| `name_rebound` | The program assigns the same name twice. |
| `no_terminal` | The program does not call plt.show(). |
| `statement_after_terminal` | The program has statements after plt.show(). |
| `statement_not_projected` | The verifier cannot state what a statement draws. |
| `arm_ambiguous` | The program imports pandas and also uses a formula grid. |
| `no_source` | The program does not read the CSV file. |
| `multiple_sources` | The program calls pd.read_csv more than once. |
| `source_not_literal` | The pd.read_csv call does not take exactly one fixed file name. |
| `column_not_from_source` | A plotted column does not come from the CSV file. |
| `aggregation_not_projected` | The verifier cannot state what a grouping computes. |
| `figure_orphans_mark` | The program calls plt.figure() after it draws. |

<a id="check-binding"></a>

### 6. Program matches your file or formula

The verifier checks that the program uses your data.

**A CSV file.** The file name in `pd.read_csv` must be the path of a file that you attached, as
`/mnt/uploads/<file name>`. When you attach more than one file, the verifier tries each one.

**Column names in your request.** The verifier compares the column names that your request writes
with the columns that the chart draws. Two rules exist:

- **Strict rule (production).** This rule applies when your request names or excludes a column of
  the file. Then your request must name every drawn column that a request can name (see the name
  lengths below). Otherwise the check fails with `column_not_named`.
- **Substitution rule (demonstration).** The check fails when two things are true. Your request
  names a column that the chart does not draw, and the chart draws a column that your request
  does not name.

A request that names no column leaves the choice to the program. The comparison reads words, not
meaning:

- Letter case and full-width forms do not matter. An underscore in a column name reads as a space,
  so `unit_price` is the two words `unit price`.
- A request names a column whose name has only ASCII characters when it holds the name's words in
  order. Such a name needs at least three characters. A name with any other character, such as
  Japanese or `é`, needs at least two characters, and the request must contain it.
- A one-word name of five or more characters also matches a word with one character changed, added
  or removed.
- A request word that fits the names of two columns is a tie. Under both rules, a tie fails the
  check with `column_not_requested`.
- The verifier reads a column name after a word such as `not`, `without`, `except` or `instead of`,
  or before `ではなく` or `以外`, as an exclusion.
- Under the strict rule alone, a Japanese short word can name a short Japanese column. The word is
  a whole run of kanji, and the verifier cuts one grouping suffix such as `別` from it. The run
  must equal a two- to four-character column name without its first or last character. So
  `月ごと` and `月別` name `年月`. A run that fits two columns names neither, and a Japanese column
  name inside the run comes first.
- An administrator can declare other names for a column in the tool settings (column aliases). Each
  alias then counts as a name of its column. An alias that two columns share is a tie.

<a id="formulas-in-a-request"></a>

**Formulas in a request.** The verifier first normalizes the request text (Unicode NFKC), so
full-width characters read as ASCII. A request supplies a formula target when it holds exactly one
formula and exactly one interval:

- the formula: `y = <expression>` or `f(x) = <expression>`;
- the interval: `x ∈ [a, b]`, `x in [a, b]`, `from a to b` or `aからbまで`;
- optionally, the point count: `n = <count>`.

The expression can use numbers, `x`, `+ - * /`, parentheses, `sin cos tan exp log sqrt abs`, `pi`
and `e`. A power `**` takes a whole-number exponent written as a number, for example `x**2` or
`x**-1`. The program's y expression must be the same expression, and its grid must start and stop
at the interval's bounds. When the request gives `n`, the grid must have that many points. A
request with no formula, two formulas or two intervals supplies no target.

| Reason | Meaning |
|---|---|
| `source_not_supplied` | The program reads a CSV file, but no CSV file is attached. |
| `target_mismatch` | The program does not match the attached file or the requested formula. |
| `column_not_requested` | The chart replaces a requested column, or a request word fits two columns. |
| `column_not_named` | Your request does not name a drawn column. Use the file's column names. |

<a id="check-recompute"></a>

### 7. Plotted values recomputed from your data

The verifier computes every plotted value again with its own code, from your file or from the
formula.

**CSV files.** The verifier reads only files that the browser's pandas reads in exactly the same
way:

- The file is UTF-8 text without a byte order mark or NUL character. It is comma-separated, with one
  header row of unique, non-empty names and the same number of cells in each row. A cell can be in
  double quotes. Rows end in `\n` or `\r\n`.
- The verifier checks each cell of the two plotted columns. Other columns count only toward the
  file limits.
- A numeric cell holds a plain decimal number, for example `-12.5`. It has at most six digits after
  the point and at most 15 significant digits. It has no plus sign, exponent or leading zero. The
  verifier refuses a negative zero, such as `-0` or `-0.0`.
- When no cell of a column has a decimal point, the column holds whole numbers within -2147483648
  to 2147483647. When any cell has a decimal point, the column holds decimal numbers, and the
  15-digit limit bounds them.
- In a plotted column, the verifier refuses an empty cell and every pandas missing-value spelling,
  so no row disappears silently. The spellings are `#N/A`, `#N/A N/A`, `#NA`, `-1.#IND`,
  `-1.#QNAN`, `-NaN`, `-nan`, `1.#IND`, `1.#QNAN`, `<NA>`, `N/A`, `NA`, `NULL`, `NaN`, `None`,
  `n/a`, `nan` and `null`. It also refuses `true` and `false` in any letter case.
- The y column must be numeric. The x column is numeric, or text categories for bar and line charts.
- A grouping reduces each group in file order, as pandas does. It sorts the groups as pandas does:
  numbers by value, text by Unicode code point.
- A bar chart of a grouping must stay in the range that the browser draws exactly. A sum, minimum or
  maximum of whole numbers stays within -2147483648 to 2147483647. Any other result stays within
  ±2\*\*53.

**Formulas.** The verifier evaluates the expression at every grid point in 64-bit floating point,
one operation at a time, as numpy does.

Every result must be a finite number, and the work must stay within the limit in [Limits](#limits).

| Reason | Meaning |
|---|---|
| `csv_too_large` | The CSV file is too large. |
| `csv_not_parsable` | The CSV file cannot be read. |
| `column_not_present` | A column that the program uses is not in the CSV file. |
| `column_not_numeric` | A plotted column holds a value that is not a number. |
| `value_not_in_profile` | The verifier does not accept the form or size of a CSV value or group value. |
| `value_not_finite` | A computed value is not a finite number. |
| `work_budget_exceeded` | The chart needs more computation than the limit allows. |

<a id="check-integrity"></a>

### 8. Chart integrity

The verifier keeps a chart from misrepresenting its data. The first eight rules hold because the
accepted Python has no way to break them. The verifier checks the last three on the recomputed
table.

- **Bars start at zero.** No axis limit can be set, so a bar's length shows its value.
- **One set of axes.** No second axis or second panel can exist.
- **Linear scales.** No logarithmic or other scale can be set.
- **Ticks.** The program can rotate the x tick labels, but it cannot set tick positions or labels.
- **Formula charts.** A formula chart is a line or a scatter chart, never bars.
- **Marker size.** The verifier refuses the scatter size keyword `s=`, so no marker size encodes a
  value.
- **Whole data range.** The program cannot filter, slice or limit the rows or the axis range, so the
  chart covers each plotted column whole.
- **No row is left out.** The chart draws every row of the file, or counts the row in its group. A
  passed reply publishes the row count of each group.
- **No repeated category.** A bar chart over text categories draws each category once, because a
  repeated category would draw one bar over another.
- **Line x values in order.** A line chart of two columns keeps file order. Its numeric x values
  never decrease, and each text category appears once. A line chart of a grouping draws each group
  once, in sorted order.
- **Labels.** A title, axis label or legend label must not name another column of the file that the
  verifier recognizes. For a grouped chart, it must not name another kind of summary, for example
  `average` on a chart of sums. The verifier reads the words alone, so it cannot judge every label.

| Reason | Meaning |
|---|---|
| `category_not_unique` | The same category occurs more than once in the chart. |
| `x_not_ordered` | The x values of the line are not in increasing order. |
| `label_not_consistent` | A chart label names a CSV column or a summary that the chart does not show. |

<a id="check-render"></a>

### 9. Chart drawn in your browser

Your browser runs the model's program, unchanged, in the Open WebUI sandbox (Pyodide). The verifier
adds only an outer step that records the drawn values and saves one PNG image. When a label or the
file holds Japanese text, the verifier also sends Open WebUI's Japanese font with the program. The
chat tab must stay open while the chart draws.

| Reason | Meaning |
|---|---|
| `no_browser` | No browser session is available to draw the chart. |
| `browser_timeout` | The browser did not answer within 60 seconds. |
| `browser_error` | The call to the browser failed. |
| `browser_no_answer` | The chat tab did not answer. Keep the tab open and try again. |
| `reply_malformed` | The browser sent a reply in an unknown format. |
| `sandbox_unavailable` | The browser could not load Pyodide. Turn off the ad blocker for this site. |
| `sandbox_error` | The browser runtime reported an error. |
| `no_image` | The browser run did not produce exactly one PNG image. |

<a id="check-match"></a>

### 10. Drawn values checked against recomputed values

The verifier compares the values that the browser reports drawing with the values that it computed.
The run must draw exactly one series on one set of axes.

- **File values** must equal the recomputed values exactly, with no numerical tolerance.
- **Formula values** must stay within the checked numerical bounds. The browser's math library can
  differ from the verifier's in the last binary digit of `sin`, `cos`, `tan`, `exp`, `log` and powers.
  So each drawn value must lie within a bound that the verifier computes around its own value.

| Reason | Meaning |
|---|---|
| `no_observation` | The browser run did not report the drawn values. |
| `observation_mismatch` | The drawn values differ from the recomputed values. |

<a id="check-attach"></a>

### 11. Image attached to the reply

Open WebUI stores the chart image with the reply. When it cannot, the verifier shows no image.

| Reason | Meaning |
|---|---|
| `publish_failed` | Open WebUI could not attach the image. |

<a id="limits"></a>

## Limits

The verifier refuses work beyond these limits.

| Limit | Value | Applies to |
|---|---|---|
| `max_source_bytes` | 20,000 | program size in bytes |
| `max_tokens` | 4,000 | Python tokens in the program |
| `max_bracket_depth` | 16 | nested brackets |
| `max_indent_depth` | 4 | nested indentation |
| `max_line_bytes` | 400 | bytes in one program line |
| `min_grid_samples` | 2 | fewest points in a formula grid |
| `max_grid_samples` | 100,000 | most points in a formula grid |
| `max_csv_bytes` | 8,000,000 | CSV file size in bytes |
| `max_csv_rows` | 100,000 | data rows in the CSV file |
| `max_csv_columns` | 128 | columns in the CSV file |
| `max_csv_cell_bytes` | 512 | bytes in one CSV cell |
| `max_table_rows` | 100,000 | rows in the plotted table |
| `max_expr_nodes` | 1,000 | parts of one formula expression |
| `max_groups` | 1,000 | groups in a grouped chart |
| `max_work` | 390,000 | units of recomputation work, about one second |
