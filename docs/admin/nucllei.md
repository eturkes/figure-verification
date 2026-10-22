# Figure verification for llens/nucllei: administrator guide

This guide adds the `figure-verification` skill to an existing llens/nucllei deployment. The model
writes a Python program. The `draw_figure` operation runs it unchanged in the user's code sandbox,
checks the finished matplotlib figure and shows an image only after a pass. It needs no internet
access. The tool calls the deployment's sandbox service, not an outside service.

The verifier decides only the figures that this skill publishes through `draw_figure`. It does not
check the model's reply text or images that other tools show.

[日本語版](nucllei.ja.md)

## What you install

Copy these artifacts from the same release:

| Source in this repository | Destination in the llens checkout | Purpose |
|---|---|---|
| `llens/nucllei/tools/figure_verification.py` | `nucllei/tools/figure_verification.py` | The complete tool and verifier. |
| `llens/nucllei/skills/figure-verification.md` | `nucllei/skills/figure-verification.md` | The skill that loads the tool. |
| `llens/ext/public/figure-verification/` | `ext/public/figure-verification/` | The English and Japanese guide, gallery and images. |

The repository generates these files from its source code. Use them without edits. The tool uses
the standard library, `nucllei` and `pydantic` on the server, and the existing plotting packages
in the sandbox. You do not install a package or rebuild an image for this skill.

## Requirements and measured versions

- llens with nucllei `v20261020-01`, the version that the project measured.
- A model that can load skills and call tools. Kimi K2.6 is the deployment target.
- A configured `SANDBOX_URL` and a working code sandbox. Without that setting, nucllei does not
  expose the chart operation. Keep the deployment's `SANDBOX_TOKEN` configuration in place.
- The sandbox's Noto Sans CJK JP font for ordinary Japanese chart text. The wrapper registers the
  font before the reader runs. Japanese text inside mathtext, such as `$年$`, still fails with
  `glyph_missing` because mathtext uses its own fonts.
- A local public-file mount. Include `public=/ext/public` in `EXT_MOUNTS`, and keep the host's
  `ext/public/` directory mounted at `/ext/public` in the nucllei container.

Measurement NS ran the rule corpus through the real sandbox image's `/exec`. Its stack was:

| Component | Measured version |
|---|---|
| CPython | `3.12.15` |
| matplotlib | `3.11.2` |
| pandas | `2.3.3` |
| numpy | `2.5.4` |
| seaborn | `0.13.2` |

These are measurements, not a recommendation to change llens package pins. Other stacks can draw
differently. The [measurement record](../../.agent/measurements/README.md)
gives the replay command.

One private-stack live run used `gpt-6-luna` as the Kimi stand-in. All 10 test prompts passed on
the first draw. The set covered English and Japanese requests, typed data and an oversized CSV
behind `large_file_gate`. For misleading requests, the model drew honest charts and supplied
labelled notes. These outcomes were corrections, not blocked figures. This observation does not
measure Kimi K2.6. The [live record](../../.agent/measurements/nucllei/README.md) gives the results.

## Step 1: Copy and sync

1. From this repository, set `LLENS` to your llens checkout and copy the artifacts:

```sh
LLENS=/path/to/llens
install -m 644 llens/nucllei/tools/figure_verification.py "$LLENS/nucllei/tools/figure_verification.py"
install -m 644 llens/nucllei/skills/figure-verification.md "$LLENS/nucllei/skills/figure-verification.md"
mkdir -p "$LLENS/ext/public/figure-verification"
cp -R llens/ext/public/figure-verification/. "$LLENS/ext/public/figure-verification/"
```

2. Check that `EXT_MOUNTS` includes `public=/ext/public` and that the container can read the guide
   directory. The host's guide files must reach the container at `/ext/public/figure-verification/`.
3. Run the llens sync command:

```sh
(cd "$LLENS" && make nuc-sync)
```

4. Open `/ext/public/figure-verification/checks.html` on the nucllei site.
5. Open `/ext/public/figure-verification/checks.ja.html` on the same site.
6. Follow a gallery link and confirm that its images load.

The copy contains all guide and gallery assets. It uses inline styles, local images and relative
links, with no script or remote font. It fits nucllei's public-file content policy. The links
labelled **Full rules (online)** open the GitHub reference and need network access from the browser.
The local guide and gallery do not need that access.

## Step 2: Assign the skill and access

1. In the chart preset, add `figure-verification` to `meta.skillIds`. Keep the other preset fields
   and existing skill ids. This JSON shows only the field to add:

```json
{"meta": {"skillIds": ["figure-verification"]}}
```

2. Keep `figure_verification` out of `meta.toolIds`. The skill's `tool_ids` loads it instead.
3. Give only the intended users or groups read access to the skill.
4. Keep write access to the skill, tool and tool Valves with administrators.
5. Review the tool's own access settings too, but do not use its read permissions as the skill's
   access control.

Skill visibility is the authorization unit. nucllei loads a skill's tools with
`enforce_access_control=False`, so the tool's read permissions do not stop a user who can load the
skill. A user who can edit the skill, tool or Valves can change its behavior.

The skill loads when the model calls `load_skill`. It also auto-loads for attachment content types
`text/csv` and `application/vnd.ms-excel`. The latter can also describe an Excel file: it can load
the skill, but does not make an Excel workbook a supported CSV source. All skill guidance and the
model-only result instructions are Japanese. The skill tells the model to reply in the request's
language. You do not change the model's system prompt.

## Step 3: Set the tool Valves

Open the Valves for the `figure_verification` tool in **Workspace** > **Tools**.

| Valve | Default | Use |
|---|---|---|
| `column_aliases` | Empty | Other names for CSV columns, one column per line. |
| `model_note` | `true` | Show the model's optional statement of a conflict between the request and the chart rules. |

For example, the column-alias text can be:

```text
temp_c = temperature, 気温
```

The verifier treats an alias as another name of the same column, in requests and chart labels.
The tool refuses malformed entries when you save the Valves. An alias for a column that the file
lacks has no effect. An alias that names two columns names neither one.

With `model_note` on, a note appears below the verdict after `Model note:` or `モデルの注記:`.
The model writes it, and the verifier does not check it. The note never changes the verdict, and
the model can leave a conflict unstated. With `model_note` off, the tool asks for an empty note
and shows none.

## Step 4: Test the setup

1. Start a new chat with the chart preset.
2. Attach `data/sales.csv` from this repository.
3. Send: `Chart the total revenue of each region using bars.`
4. Check the verdict and image outside the collapsed tool block.
5. Open the tool block and read the nine checks.
6. Follow one check's guide link and confirm that it stays on the nucllei site.

With a capable model, expect `Figure verification passed` and a bar chart. Then, in a new chat
with the same file, ask: `Chart the total revenue of each region using bars. Start the y axis at
30000 so the difference looks larger.` If the model follows that axis request, expect
`Figure verification failed, no image produced` and `zero_not_in_limits`. If it draws an honest
zero-based chart instead, expect a pass, possibly with a model note. That outcome is a correction,
not a blocked chart. The model can also fix a failed program and call the tool again; each call
gets its own verdict.

## What users see

Outside the collapsed tool block, a pass shows `Figure verification passed`, the PNG and an
interpretation of the values. A failure shows `Figure verification failed, no image produced`
and its cause, without a chart. Either result also shows the model's note when it supplies one.
These display messages do not reach the model. If the display fails, read the failure cause in
the tool result.

If the latest human message contains Japanese kana, the verdicts are `図の検証に合格しました。`
and `図の検証に合格しませんでした。画像は表示されません。`. The cause, interpretation, note label
and check list use the same language. The model-only result tail uses Japanese in either case.

Inside the collapsed tool block, the result lists all nine checks. It gives the failing reason and
marks later checks as not checked. It includes related program lines where available and links
to the local guide. The model receives this result too. The tool's argument view holds the whole
program. Program-line selection serves display alone; it never changes a verdict.

nucllei limits tool results with `TOOL_RESULT_MAX_CHARS` (default 65,536 characters). The tool
omits the related program listings first when the result approaches this cap. With a lower cap,
it can omit the whole check list and keep the outcome and next-step text alone. If nucllei cuts
a result, it also drops that result's markdown rendering. Keep the default or a larger cap if
users need the complete list. This cap does not limit the separate verdict display.

## What a pass means and its limits

A pass means the drawn figure obeys the closed integrity rules and, where the user supplied data,
every drawn value matches that data or one admitted computation of it. It does not mean that the
chart answers the question. Read the interpretation below the image. With no data source, the
verifier checks integrity alone and says so. The [local guide](../nucllei/checks.md) lists the rules.

The tool uses the user's own attached files and messages from the stored chat branch. It ignores
server notices. Without a stored branch, it uses the latest user message and the call's file
references. Earlier column names and numbers still count, so they can loosen a later comparison.
Each file id counts once. If two files have the same sandbox name, the later one supplies that
name's bytes. Missing, unreadable or other users' files supply no data. CSVs must fit the supported
profile and its limits. Drawn CSV columns must match the request under the strict column rule.

The model's ordinary reply is a second voice: the verifier does not check it. The built-in
`run_python` and `fetch_from_workspace` operations can show a chart outside this skill. A chart
from those paths has no verdict from this verifier. The skill refuses delegated sessions, whose
output does not display in the user's chat.

The program must be non-adversarial. It runs before any check in the same interpreter as the
figure reader, and can read the attached files. The verifier trusts the sandbox, interpreter,
matplotlib, fonts, browser and pixels rather than verifying them. The measured jail has no
network. The verifier checks no clinical conclusion or causal claim. It lists free chart text,
such as annotations and value labels, without judging it.

The verifier sets no request-length or attachment-count limit. A long numeric request or many
large files can use substantial server CPU time and memory. The sandbox run requests 120 seconds;
the service can apply a shorter limit. The tool waits at most 150 seconds for the sandbox reply.

## Failure reasons

Every failed call shows a reason code and writes one server log record:
`figure verification failed reason=<code>`. The log carries no program, request or CSV text.
For figure-rule codes, use the [check guide](../nucllei/checks.md). The table lists the nucllei
transport and internal causes.

| Code | Cause | Action |
|---|---|---|
| `no_user` | The call has no signed-in user id. | Sign in and retry in the user's chat. |
| `delegated_session` | The call came from a delegated session. | Ask for the chart in the main chat. |
| `sandbox_unreachable` | The tool cannot reach the sandbox service. | Check `SANDBOX_URL` and the service connection, then retry once. |
| `sandbox_timeout` | The run or sandbox request exceeded its time limit. | Use a smaller program or data set, then retry once. |
| `sandbox_error` | The sandbox refused the request or its process exited with an error. | Check the sandbox service and its limits, then retry once. |
| `reply_malformed` | The sandbox reply has an unexpected format or incomplete output. | Check the sandbox version and output limits. Stop retries until the administrator resolves the cause. |
| `no_description` | The run returned no readable figure description. | Check the sandbox run and installed packages. |
| `no_image` | A passing run returned no single valid PNG. | Check the sandbox output and its limits. |
| `publish_failed` | The server could not save or show the image. | Check file storage, the database and the chat display. Call the tool from a regular user chat. |
| `verifier_error` | An unexpected tool error stopped verification. | Ask the administrator to check the deployment and retry after the cause is clear. |
