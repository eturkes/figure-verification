# Figure verification for Open WebUI: administrator guide

This guide tells an administrator how to add figure verification to an existing Open WebUI
instance. After the setup, a chat model writes a Python program that draws a chart. A separate
verifier checks that program before the chart can appear in the chat.

- If the verifier accepts the program and the drawn chart matches the recomputed values, the chat
  shows the chart and `Figure verification passed`.
- If the verifier refuses the program, the chat shows `Figure verification failed, no image produced`.
  A status line above that message states the reason.

## What you install

You paste two files into Open WebUI. The files are in the `paste-in/` directory of this repository.

| File | Open WebUI item | Item ID |
|---|---|---|
| `paste-in/figure_verification_tool.py` | Tool | `figure_verification` |
| `paste-in/figure_verification_filter.py` | Function (filter) | `figure_verification_filter` |

Each file contains the complete verifier. The files use only the Python standard library and
the `open_webui` package that Open WebUI already contains. They make no network calls. You do
not install packages and you do not rebuild the container image.

Use the two files from the same release together. Do not edit them. The repository generates
them from its source code.

## Requirements

- Open WebUI 0.10.2. The project measured this version. Other versions are not measured.
- The Pyodide code runtime that Open WebUI 0.10.2 contains (Pyodide 0.28.3 with matplotlib,
  pandas and numpy). The chart program runs in this runtime inside the user's browser.
- A browser connection with WebSocket support. The filter runs the program through this
  connection.
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

The measured setup makes this filter global. A global filter rewrites the last reply of every
chat on the instance, and a reply without a chart becomes the failure message. Thus, use a
separate Open WebUI instance for charts, or attach the filter only to the chart model. The project
did not measure the per-model option.

## Step 3: Set up the chart model

1. In **Workspace** > **Models**, edit the chart model.
2. Attach the `figure_verification` tool. Attach no other tool to this model.
3. Paste the system prompt from `system_prompt.en.txt` into the system prompt field.
4. Save the model.

Use `system_prompt.ja.txt` when the users write in Japanese.

## Step 4: Check the instance settings

Set these Open WebUI settings. You can set each one as an environment variable.

| Setting | Value | Reason |
|---|---|---|
| `ENABLE_CODE_EXECUTION` | `false` | The filter runs the verified program itself. Users do not need code execution. |
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
plain words what the verifier checked.

Then send a request for a complex dashboard, for example a grid of four charts with a dark theme.
Expect `Figure verification failed, no image produced`, with a status line above it that states the
reason.

## What the verdict means

`Figure verification passed` means all of these statements are true:

- The verifier accepted the program. The program uses only a small set of pandas, numpy and
  matplotlib calls.
- The verifier recomputed every plotted value from the uploaded CSV file or from the function in
  the request. The model did not supply any plotted value.
- The values that Pyodide drew match the recomputed values. They match exactly for CSV data. For a
  function, each value lies inside a rounding range that the verifier computes from the formula.

The pass message does not mean that the chart answers the question. The chart can show a
different measure or a different grouping than the user wanted. Read the text below the chart. It
states what the chart shows.

The verifier trusts the browser, Pyodide, matplotlib and the pixels on the screen. It does not
check them.

## What the verifier accepts

The verifier accepts one chart per reply:

- A bar, horizontal bar, line or scatter chart over two columns of one uploaded CSV file.
- A chart of one value per group, where the value is a sum, mean, minimum or maximum.
- A line or scatter chart of a function over a stated interval. An example request is
  `y = sin(x) for x from 0 to 10`.

The verifier refuses everything else. For example, it refuses several charts in one figure, a
second axis, a changed axis scale and hand-typed data values.

If the request names columns of the CSV file, the chart cannot put a different column in place of
a named column. For example, if the request says `revenue by region`, a chart of revenue by month
fails with the code `column_not_requested`. A request word that fits two column names fails with the
same code. The verifier compares the words of the request with the
column names only. It does not know synonyms or translations, so a request that names no column
passes this check.

The chart labels obey a similar rule. A title, axis label or legend label cannot name a CSV column
that the chart does not show. If the chart shows a sum, mean, minimum or maximum per group, a label
cannot name a different summary. For example, a chart of means cannot have the label `Total`. Such
a chart fails with the code `label_not_consistent`.

## Why a chart failed

When the filter blocks a chart, the reply shows a status line above the failure message. The line
states the reason and ends with a reason code in parentheses, for example
`(call_target_not_admitted)`. If the request contains Japanese kana, the line is in Japanese.
Otherwise, the line is in English.

The status line stays with the reply after a page reload. Open WebUI does not send it to the model.
For each blocked reply, the filter also writes one record to the Open WebUI server log:
`figure verification failed reason=<code>`. The status line and the log record contain no program
text, no request text and no data from the CSV file.

Each chart reply also has a `Show checks` control. It is below the status line, or below the chart
if the chart passed. Click it to show every check that the verifier runs, in order. Each check
states what it examines. A passed check has a ✓ mark. The failed check has a ✗ mark and the reason.
The checks after the failed check show `not checked`. If the chart passed, every check has a ✓ mark.
The list uses the same language as the status line. It stays with the reply after a page reload, and
Open WebUI does not send it to the model.

The status line, the check list and the log record are for diagnosis only. If the filter cannot
deliver one of them, the verdict does not change.

There are two types of reason code:

- A code from the verifier, for example `call_target_not_admitted` or `target_mismatch`. The
  verifier refused the program. Ask for a simpler chart. The section "What the verifier accepts"
  lists the charts that can pass.
- A code from the filter or the browser, for example `no_tool_call` or `sandbox_unavailable`. The
  table below gives the cause and the action for the common codes.

## Troubleshooting

| Symptom | Cause | Action |
|---|---|---|
| Every reply fails with the code `no_tool_call` | The model did not call the tool. | Make sure that the tool is attached to the model and that the system prompt is set. |
| A reply without a chart request fails with the code `no_tool_call` | The filter is global. | Attach the filter only to the chart model, or use a separate instance. |
| The reply fails with the code `no_target` | The verifier cannot read a CSV file or a function in the request. | Attach a CSV file, or state the function and its interval. The section "What the verifier accepts" gives an example. |
| The reply fails with the code `no_browser`, `browser_no_answer` or `browser_timeout` | The filter cannot reach the browser runtime. | Make sure that the browser keeps a WebSocket connection to Open WebUI. Keep the chat tab open until the reply is complete. |
| Every chart fails with the code `sandbox_unavailable` | The browser could not load the Pyodide runtime. A content blocker is a common cause. For example, the "Block Outsider Intrusion into LAN" list of uBlock Origin Lite blocks it. | In the content blocker, set the filtering mode for the Open WebUI site to "No filtering". Alternatively, turn off that list. |
| The reply fails with the code `sandbox_error` | The browser runtime reported an error. | Reload the page and send the request again. |
| The reply fails with the code `observation_mismatch` | The values that Pyodide drew differ from the recomputed values. | Make sure that the browser uses the Pyodide runtime of Open WebUI 0.10.2. If the code stays, keep the chat and report it. |
| The upload stalls or fails | The instance calls an embedding service. | Set `BYPASS_EMBEDDING_AND_RETRIEVAL` to `true`. |
