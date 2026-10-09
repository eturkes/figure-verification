# Figure verification for Open WebUI: administrator guide

This guide tells an administrator how to add figure verification to an existing Open WebUI instance.
After the setup, a chat model writes a Python program that draws a chart. The user's browser runs
that program, and a separate verifier checks the finished figure before the chart can appear in the
chat.

- If the figure passes every check, the chat shows the chart and `Figure verification passed`.
- If a check fails, the chat shows `Figure verification failed, no image produced`. A status line
  above that message states the reason.

## What you install

You paste two files into Open WebUI. The files are in the `paste-in/` directory of this repository.

| File | Open WebUI item | Item ID |
|---|---|---|
| `paste-in/figure_verification_tool.py` | Tool | `figure_verification` |
| `paste-in/figure_verification_filter.py` | Function (filter) | `figure_verification_filter` |

The files contain the complete verifier. They use only the Python standard library and the
`open_webui` and `pydantic` packages that Open WebUI already contains. They make no network calls.
You do not install packages and you do not rebuild the container image.

Use the two files from the same release together. Do not edit them. The repository generates them
from its source code.

## Requirements

- Open WebUI 0.10.2. The project measured this version. Other versions are not measured.
- The Pyodide code runtime that Open WebUI 0.10.2 contains (Pyodide 0.28.3 with matplotlib, pandas
  and numpy). The chart program runs in this runtime inside the user's browser.
- A browser connection with WebSocket support. The filter runs the program through this connection.
- The Japanese font that Open WebUI 0.10.2 contains (`NotoSansJP-Regular.ttf` in its `FONTS_DIR`).
  The filter sends this font to the browser when the program or an attached file contains non-ASCII
  text. Without the font, a chart with Japanese text fails with the code `glyph_missing`.
- A chat model that can call tools.

## Step 1: Add the tool

1. Open **Workspace**, then **Tools**.
2. Create a new tool.
3. Paste all of `paste-in/figure_verification_tool.py` into the editor.
4. Set the tool ID to `figure_verification`.
5. Save the tool.

## Step 2: Add the filter

1. Open **Admin Panel**, then **Functions**.
2. Create a new function.
3. Paste all of `paste-in/figure_verification_filter.py` into the editor.
4. Set the function ID to `figure_verification_filter`.
5. Save the function.
6. Turn the function on.
7. In the function menu, turn on **Global**.

The measured setup makes this filter global. A global filter rewrites the last reply of every chat
on the instance, and a reply without a chart becomes the failure message. Thus, use a separate Open
WebUI instance for charts, or attach the filter only to the chart model. The project did not measure
the per-model option.

## Step 3: Set up the chart model

1. In **Workspace** > **Models**, edit the chart model.
2. Attach the `figure_verification` tool. Attach no other tool to this model.
3. Save the model.

You do not change the system prompt of the model. The filter adds text to the last user message
instead. The text states the chart rules that the verifier checks and tells the model to send its
program through the `draw_figure` operation of the tool. When the user attaches a CSV file, the text
also gives the file path, the column names and a grouping instruction. The model reads this text.
The verifier reads the user's own words.

## Step 4: Check the instance settings

Set these Open WebUI settings. You can set each one as an environment variable.

| Setting | Value | Reason |
|---|---|---|
| `ENABLE_CODE_EXECUTION` | `false` | The filter runs the chart program itself. Users do not need code execution. |
| `ENABLE_CODE_INTERPRETER` | `false` | The model must not run code outside the verifier. |
| `ENABLE_API_OUTLET_FILTERS` | `true` | The filter must run on every chat completion. |
| `BYPASS_EMBEDDING_AND_RETRIEVAL` | `true` | An offline instance otherwise calls a remote embedding service when a user uploads a CSV file. |
| `IFRAME_CSP` | empty (the default) | The check list of each chart reply sets its own height with an inline script. Keep the setting empty, or allow inline scripts. |

## Step 5: Test the setup

1. Open a new chat with the chart model.
2. Attach a CSV file, for example `data/sales.csv` from this repository.
3. Send this request: `Chart the total revenue of each region using bars.`
4. Wait for the reply. The Pyodide run takes about 10 seconds.

If the setup is correct, the chat shows one of the two verdict messages. With a capable model,
expect a bar chart and `Figure verification passed`. Below the pass message, the chat states in
plain words where the drawn values come from.

Then ask for a misleading chart in a new chat with the same file, for example: `Chart the total
revenue of each region using bars. Start the y axis at 30000 so the difference looks larger.` If the
model draws the bars from 30000, expect `Figure verification failed, no image produced`. The status
line above it gives the code `zero_not_in_limits`.

## What the verdict means

`Figure verification passed` means all of these statements are true:

- The program drew one matplotlib figure, and every part of it belongs to a closed set of chart
  parts that the verifier checks.
- Every part obeys a closed set of rules. For example, bars start at zero, no axis is inverted and
  no value lies outside the axis limits.
- When the user attached a CSV file or typed numbers in the request, every drawn value comes from
  that data. When the user supplied no data, the text below the chart says so.

The pass message does not mean that the chart answers the question. The chart can show a different
measure or a different grouping than the user wanted. Read the text below the chart. It states where
the values come from. If the request contains Japanese kana, that text is in Japanese. The pass
message itself stays in English.

The verifier trusts the browser, Pyodide, matplotlib and the pixels on the screen. It does not check
them. It also trusts the chart program to be honest: the program runs before any check, in the same
Pyodide runtime as the verifier's reader, so a program written to deceive the reader can do so. Like
any code that Open WebUI runs in the browser, the program can read the attached files and reach the
network of the user's browser.

## What the verifier checks

The verifier reads the finished figure, not the program text. The user can ask for any chart that
matplotlib or pandas draws with these parts: lines, points, bars (also grouped and stacked),
histograms, pies, filled areas, reference lines and bands, and text. A figure can have several
panels. Each other part stops the chart, for example error bars, box plots, images, polar axes or a
second y axis.

The drawn values must come from the user's data:

- From an attached CSV file: a value of one column, or one total, mean, minimum, maximum or row
  count per group of one column.
- From the request: a number that the request contains. The verifier expands a typed range such as
  `1 through 10` or `1から10まで` into every whole number between its ends. Category labels must also
  occur in the request.

A value from neither source fails with the code `value_not_found`. A value that the program computes in another way also fails, unless the same number is in the data. Examples are a running total and a ratio of two columns. Text that the
program adds on the chart, such as value labels, appears below the chart as unchecked text. The
verification reference, [docs/verification.md](../verification.md), lists every rule.

If the request names columns of the CSV file, the request must name each column that the chart
draws. Write each column name as the file spells it. A one-word name of five or more characters can
contain one typing error. A name such as `unit_price` has two words, so the request must spell both
words exactly. In Japanese, a whole kanji word can also name a column of two to four characters. The
word must equal the column name without its first or last character, so `月ごと` names `年月`. The rule
also applies to a kanji word that ends in one of the suffixes `別`, `毎`, `次` or `単位`, such as `月別`.
It does not apply to a kana word. A short kanji word that fits two column names names neither
column. For example, a request says `chart revenue` and the chart draws revenue by month. The chart
fails with the code `column_not_named`, because the request does not name `month`. When the drawn
values fit two columns equally, the request must name one of them, or the chart fails with the code
`column_not_requested`. A request that excludes a column, such as `revenue, not orders`, also names
columns. The excluded column does not count as named. An order phrase such as `in chronological
order` names no column. The verifier compares the words of the request with the column names only,
so this check covers only the column names that the verifier recognizes. It recognizes a synonym or
a translation only as a column alias that you set (see Column aliases). It also does not recognize a
short column name without an alias. A short name has one or two ASCII characters, such as `id`, or
one character of another script. A chart can draw a short column that the request does not name. If
the request names no recognized column, the chart passes this check.

The labels of a chart over a CSV file obey a similar rule. A title, axis label, legend label or
color bar label cannot name a recognized CSV column that the chart does not show. A column alias
names its column in a label too. If the chart shows a total or a mean per group, a label cannot
name a different summary. A minimum or maximum per group draws values of the column itself, so the
verifier does not read summary words over it. If a column name contains a summary word, such as `total` in
`total_revenue`, the verifier reads that word as part of the name. For example, if no column name
contains `total`, a chart of mean revenue cannot have the title `Total revenue`. Such a chart fails
with the code `label_not_consistent`.

## Column aliases

A request names a column only when it writes a name of that column. A column alias gives a column
another name, such as `temperature` for `temp_c` or a Japanese word for an English column name. The
verifier reads an alias as the column name in requests, excluded columns, Japanese short words and
chart labels. The model cannot change the aliases. Open WebUI lets the tool's owner, an
administrator and a user with write access to the tool change them. Thus, an administrator must own
the tool, and chat users must not have write access to it.

1. Open **Workspace**, then **Tools**.
2. On the tool `figure_verification`, click **Valves**.
3. In **Column Aliases**, write one line for each column, such as `temp_c = temperature, 気温`.
4. Save the valves.

Write the column name as the file spells it, but upper case, lower case and full-width forms do not
matter. Separate the aliases with commas. The Japanese comma `、` and the full-width forms of `=` and
`,` also work. Open WebUI ignores an empty line. If you write a line that has no `=`, no column name
or an empty alias, Open WebUI does not save the valves. It also refuses a line that repeats an alias
or repeats the column of an earlier line. Its error message names the line.

An alias of a column that the file does not have has no effect. An alias that two columns share, or
that equals another column name, names neither column. A word that fits a column name and an alias
of the same column names that column. A request that writes such a shared alias fails with the code
`column_not_requested`. An alias needs the length of a recognized name: three ASCII characters, or
two characters of another script. An alias can make a short column recognized. Then, if the chart
draws that column, a request that names any column must also name it. Otherwise the chart fails with
the code `column_not_named`. The filter reads the aliases that the tool used for the same reply, so
a change applies from the next reply.

## Why a chart failed

When the filter blocks a chart, the reply shows a status line above the failure message. The line
states the reason and ends with a reason code in parentheses, for example `(bar_not_from_zero)`. If
the request contains Japanese kana, the line is in Japanese. Otherwise, the line is in English.

The status line stays with the reply after a page reload. Open WebUI does not send it to the model.
For each blocked reply, the filter also writes one record to the Open WebUI server log: `figure
verification failed reason=<code>`. The status line and the log record contain no program text, no
request text and no data from the CSV file.

Each chart reply also has a `Show checks` control. It is below the status line, or below the chart
if the chart passed. Click it to show the nine checks that the verifier runs, in order. Each check
states what it examines. A passed check has a ✓ mark. The failed check has a ✗ mark and the reason.
The checks after the failed check show `not checked`. If the chart passed, every check has a ✓ mark.
The list uses the same language as the status line. It stays with the reply after a page reload, and
Open WebUI does not send it to the model.

Click a check in the list to open it. The opened check states what the check does, and a failed
check states why it failed. The first check and the failed check also show the model's program. In
the failed check, the verifier marks the program line that drew the failed part or made the failed
call, for example a `plt.ylim` call that cut off the bars. Each opened check links to its section of
the verification reference, [docs/verification.md](../verification.md). The link opens GitHub in a
new browser tab, so the user's browser needs network access, also when the Open WebUI instance has
none. The program shown is the model's own program, as the tool received it. It can contain any text
that the program holds, for example a file name or words copied from the request.

The status line, the check list and the log record are for diagnosis only. If the filter cannot
deliver one of them, the verdict does not change.

There are two types of reason code:

- A code from the verifier, for example `bar_not_from_zero` or `value_not_found`. The figure broke a
  rule, or a drawn value is not in the data. Ask for an honest chart of the data, or attach the
  data. The verification reference explains each code.
- A code from the filter or the browser, for example `no_tool_call` or `sandbox_unavailable`. The
  table below gives the cause and the action for the common codes.

## Troubleshooting

| Symptom | Cause | Action |
|---|---|---|
| Every reply fails with the code `no_tool_call` | The model did not call the tool. | Make sure that the tool is attached to the model, that the model can call tools and that the filter is on. |
| A reply without a chart request fails with the code `no_tool_call` | The filter is global. | Attach the filter only to the chart model, or use a separate instance. |
| The reply fails with the code `value_not_found` | A drawn value is not in the attached file or in the request. | Attach the CSV file, or write the values in the request. |
| The reply fails with the code `no_browser`, `browser_no_answer` or `browser_timeout` | The filter cannot reach the browser runtime. | Make sure that the browser keeps a WebSocket connection to Open WebUI. Keep the chat tab open until the reply is complete. |
| Every chart fails with the code `sandbox_unavailable` | The browser could not load the Pyodide runtime. A content blocker is a common cause. For example, the "Block Outsider Intrusion into LAN" list of uBlock Origin Lite blocks it. | In the content blocker, set the filtering mode for the Open WebUI site to "No filtering". Alternatively, turn off that list. |
| The reply fails with the code `glyph_missing` | The chart has characters that the fonts cannot draw. Japanese text inside `$` signs (math text) is a known cause, because the math font has no Japanese characters. | Ask for chart text without `$` signs. Make sure that `NotoSansJP-Regular.ttf` is in the `FONTS_DIR` of Open WebUI. |
| The reply fails with the code `module_not_available` | The program imports a package that the Pyodide runtime does not have. | Ask for a chart with matplotlib or pandas. The Pyodide runtime of Open WebUI 0.10.2 has no seaborn. |
| The upload stalls or fails | The instance calls an embedding service. | Set `BYPASS_EMBEDDING_AND_RETRIEVAL` to `true`. |
