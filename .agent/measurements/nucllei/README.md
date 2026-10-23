# NL — the nucllei skill live (Q82.3)

Observation, never acceptance (the rule corpus + NS are): one `(device, config)` = a private stack on this desktop — `localhost/nucllei:v20261020-01` + `localhost/nucllei-sandbox:v20261020-01` (local builds of nucllei's tag) + `gpt-6-luna` through the codex bridge (reasoning effort `low`, the bridge default) — provisioned by llens `e6a1b6f`'s own `scripts/nucllei/sync.py` (llens functions `markitdown_extract` + `large_file_gate`, the generated tool + skill), one preset (`skillIds` = the skill, `toolIds` = `builtin_sandbox`, `filterIds` = `large_file_gate`).

Run: `uv run --locked python .agent/measurements/nucllei_live.py <llens checkout> <out dir> [arm …]` (`NL_REPEAT=<n>` repeats each arm; `NL_KEEP=1` leaves the stack up (served on `127.0.0.1` alone, signup off) and writes `<out>/stack.json` (mode 0600) for browser QA; `NL_EXT=<dir>` serves `<dir>` as the server's `/ext/public`). Per arm: the stored assistant message (every tool exchange: call, `results[]` display + render + error kind) + `summary.json`; the server log → `<out>/nucllei.log`. Program digests + notes + replies of the recorded runs: `programs.json`; summaries: `live2-summary.json`, `live3-summary.json`.

| run | arms | first draw | notes |
|---|---|---|---|
| 1 (pre reply-language rule) | `simple` | pass | the model answered the English request in Japanese → the skill now names the reply language |
| 2 | 6 banner arms (`webui/banner.json`: EN + JA honest + misleading over `sales.csv` + `clinic_ja.csv`), `typed`, `typed-ja`, `twin-axis`, `oversize` | 10/10 pass | the 3 misleading banner arms + `twin-axis` = corrections (no truncated / inverted / second axis drawn), each with a labelled note in the request's language; replies in the request's language; `oversize` bound to `big_sales.csv` |
| 3 | `twin-axis` ×3, `oversize` ×3 | 6/6 pass | `twin-axis` corrected 3/3; `oversize` bound to `big_sales.csv` 3/3 while `nucllei.log` reads `[large-file-gate] 注記 1 件: big_sales.csv(840014tok)` each time (the gate removed the file from the request; the tool read it from the stored branch) |

Classification (`.claude/rules/claims.md`): a misleading arm whose figure lacks the requested distortion is a correction, never a block. No live first-draw block was observed: gpt-6-luna corrected 7/7 misleading runs (Q78's Open WebUI record had it draw the second axis in 2 of 3). The blocking path is evidenced by the rule corpus (host + NS, 250 cases) and the hand smoke against the real sandbox (`zero_not_in_limits` with the `set_ylim` line marked).

Visual QA (`NL_KEEP=1`, scratch headless Chromium over CDP, the a93232d tool): the collapsed `draw_figure` block shows its display beneath it (verdict, chart, interpretation with code spans, the note label bold through KaTeX in Japanese) and the model's reply below; opened, the check list reads one row per title, covers line, explanation, program lines (fenced) and guide link. An earlier list layout ran each row's paragraphs together (nucllei's list renderer), hence top-level rows.

Guide copy (`NL_EXT=llens/ext/public`): signed out, `/ext/public/figure-verification/*` answers 403 (nucllei's `/ext` gate); signed in, `checks.ja.html#check-axes` renders under nucllei's `/ext` CSP with its diagram loaded (1/1 images) and the anchor resolved.
