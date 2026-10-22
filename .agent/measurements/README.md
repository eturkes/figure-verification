# Measurement harnesses

Committed scripts re-derive the numeric bands and profiles cited in `.claude/rules/pysrc.md` and
`.agent/archive/contracts/m13u5.md` + `m13u6.md`. Gate + `mypy` exclude them; Pyodide legs need
Node + package downloads. Generated corpora/results are gitignored; `expected/` is tracked.
All 28 table IDs compare against hand-stated published predicates in `expected/<id>.json`, X1
aside: its expectation is its own first run's full projection (seeded, so a replay reproduces it
exactly), a reproducibility record of the rates `docs/verification.md` publishes.
`all_results.py` projects raw measurements without reading expectations. `check.py` compares exact
JSON shape/types/values; a singleton `{"$le": n}` or `{"$ge": n}` encodes a published numeric bound.

## All-id check

After the environment + Node setup below, from the repository root:

```
nice -n 19 ionice -c3 uv run --locked python .agent/measurements/rerun_all.py
```

The driver replays every ID, compares its independent `results/<id>.json`, and prints `<id>: PASS`
or `<id>: FAIL <cause>`. Missing dependencies/results and mismatches return nonzero; later IDs still
run. README table IDs, driver IDs and expected-file IDs must match. Optional positional IDs select
an explicit subset; `--check-only` compares prior results without rerunning measurements.

Logs + raw results → `all-data/`; reduction evidence → `r-data/`. The driver shares successful
input generators within one invocation. Both npm builds run wherever the table names both.
F7/T8/I1/I3/C1 read the installed Open WebUI bundle through the repository's common Git directory.

M15/M16 start a private `webui/launch.sh --stub` stack with fresh loopback ports and a headless
Chromium from `$CHROME` (a path or `PATH` name) over CDP: the environment's, else the gitignored
repo-root `.env`'s (copy `.env.example`); unset ⇒ the leg fails. Open WebUI must already exist in
`.venv-webui` of the primary checkout.
Runtime data, verifier state, browser profile and service logs use `.scratch/measurements-live/`.
The driver stops its processes and removes that private state; copied service logs stay in
`all-data/stack-logs/`. It never attaches to the user's live stack/browser or uses ports 8000/8001/8080.
M16 theme PNGs still need visual inspection; a machine PASS claims its measured DOM predicates,
not inspected pixels. M16's scheme passes need a `$CHROME` that honours CDP `prefers-color-scheme`
emulation; a build that pins the scheme fails them.

Positive control after a successful replay: run the one-count R1 probe below. It uses the driver
with `--check-only R1`; require nonzero + `R1: FAIL`, then restore byte-identical expectations.

## Rerun

From the repository root, install the pinned root environment and Node packages:

```
export UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy
uv sync --locked
(cd .agent/measurements && pnpm install --frozen-lockfile)
```

Run each host script in the table with `uv run --locked python .agent/measurements/<script>.py`.
pandas 3.0.2 is in the root development environment; the driver still passes
`--with pandas==3.0.2` to the host legs that measure pandas itself (`make_s6_csv.py`, `t3.py`,
`t4.py`, `t5.py`, `t7_profile.py`, `t7_quoted.py`, `t8_profile.py`), so the pin stays explicit.
Run a generator before its dependent host or sandbox leg.
`I1` (M19) runs 52 chart programs over the M19 scope and its out-of-scope census, and records each
axes child as (class, origin, data transform) — origin = the outermost Axes-module frame
(`.claude/rules/figure.md`). The projection compares the host leg with the installed bundle and
publishes the bundle's family set. `I2` measures keyed value-explanation ambiguity over `data/*.csv`:
cross-column full-series ties, shared points, tied k-point subsets and chance matches of made-up
keyed series of k distinct keys from one key column holding at least k (seed 19, 10,000 trials per
size, k = 1-5; `null` where no key column holds k: these CSVs hold 2-4 keys per key column). `I3` (M19.2) runs the same 52 programs through the
reader on the host and through the production `wrapper_code` in the installed bundle, one runtime
in order (the reader's holder reused across replies), and publishes, per program, the description
fields that differ (on 0.11.3 + 0.12.3: `subplots` positions after `tight_layout` alone). `C1` (M19.6) runs
every rule-corpus case (`tests/figure_corpus/`) through the production `wrapper_code` in the
installed bundle (matplotlib 3.10.8, one runtime, no font, the CSVs under `/mnt/uploads`), judges
each bundle description on the host with the case's own Sources, and publishes the cases whose
bundle verdict misses the case's expectation or differs from the host verdict.

Every Node leg runs in ONE sandbox: the Pyodide 314.0.3 bundle the installed Open WebUI 0.12.3
serves (`../../.venv-webui/lib/python3.11/site-packages/open_webui/frontend/pyodide`, runtime
CPython 3.14.2). `o8_bundle.mjs` loads it and reads every wheel from that directory, never from
the CDN Node Pyodide defaults to; a bundle of another version fails loudly. Run each Node command
from `.agent/measurements/`. Every `.mjs` takes `owui` as its first argument and an optional result
filename as its second. `f7_wrapper.mjs` is the exception: it takes `<B>`, the installed bundle
directory above, and a required result filename. It calls `f7_export.py` through
`uv run --no-sync --locked`; set `UV_PROJECT_ENVIRONMENT` to the ready root environment. From the
repo root, run:

```
export UV_PROJECT_ENVIRONMENT="$PWD/.venv" UV_LINK_MODE=copy UV_NO_SYNC=1 PYTHONPATH="$PWD/src"
node .agent/measurements/f7_wrapper.mjs "$PWD/.venv-webui/lib/python3.11/site-packages/open_webui/frontend/pyodide" f7-31403.json
```

F7 finds the installed frontend's `execute:python` handler and sandbox chunk by content (build
hashes rename the files, the minifier renames the variables), then reads the package regexes, the
iframe prelude and the reply shaping at runtime. It loads only source-detected packages, runs the
literal-trigger prelude, then executes the wrapper. Missing or changed anchors fail loudly. Every
wrapper must emit one tagged description line before one PNG line with a valid signature; the
shaped reply must have `stderr: null` and `result: null`. The description's glyph count is nonzero
exactly for the five glyph legs. A literal plotting import must trigger the installed prelude,
whose patched `show` prints one PNG line (0.10.2's prelude raised `SyntaxError` instead). The font
cuts are the filter's own stdlib cut (`fonts.cut`, Q74), run with every fontTools import blocked;
a collection cuts its first face. The `identity` leg draws every character the `ja-font` cut keeps
with the bundle's FT2Font from the whole font and from the cut, unhinted and natively hinted
(12 + 100 ppem), and must find no difference. The Japanese PNGs land beside the result as
`f7-31403.<leg>.png` for inspection.

The other Node commands:

```
cd .agent/measurements
node t6_pyodide.mjs owui t6-31403.json
node versions.mjs owui versions-31403.json
```

`versions.mjs` prints Python, platform, Pyodide, NumPy, and pandas versions for the bundle.

| id | host script(s), in run order | Node command | build behind the published number |
|---|---|---|---|
| S6 | `make_s6_csv.py` | `node s6_pyodide.mjs owui s6-31403.json` | Open WebUI 0.12.3 bundle, Pyodide 314.0.3 |
| T3 | `t3.py` | none | host only (pandas 3.0.2) |
| T4 | `t4.py` | none | host only (pandas 3.0.2) |
| T5 | `t5.py` | none | host only (pandas 3.0.2) |
| T6 | `make_s6_csv.py` (same S6 corpus) | `node t6_pyodide.mjs owui t6-31403.json` | Open WebUI 0.12.3 bundle, Pyodide 314.0.3 |
| T7 | `t7_profile.py`, then `t7_quoted.py` | `node t7_pyodide.mjs owui t7-31403.json` | Open WebUI 0.12.3 bundle, Pyodide 314.0.3 |
| T8 | `make_t8_inputs.py`, then `t8_profile.py` | `node t8_pyodide.mjs owui t8-31403.json` | Open WebUI 0.12.3 bundle, Pyodide 314.0.3 |
| I1 | `i1_census.py` | `node i1_pyodide.mjs owui i1-31403.json` | host matplotlib 3.10.8 vs the installed Open WebUI 0.12.3 bundle (matplotlib 3.10.8) |
| I2 | `i2_ambiguity.py` | none | host only |
| I3 | `i3_export.py` | `node i3_pyodide.mjs owui i3-31403.json` | host reader (matplotlib 3.10.8) vs production wrapper in the installed Open WebUI 0.12.3 bundle |
| C1 | `c1_export.py` | `node c1_pyodide.mjs owui c1-31403.json` | rule corpus: host judge (matplotlib 3.10.8) vs production wrapper in the installed Open WebUI 0.12.3 bundle (matplotlib 3.10.8) |
| X1 | `x1_transforms.py` | none | host only |
| Image | `image_import.py` (its image leg `image_leg.py` runs inside the image through `podman`, network off) | none | `ghcr.io/open-webui/open-webui:v0.12.3` (CPython 3.11.17) |
| F7 | `f7_export.py` (called by the Node leg) | `node f7_wrapper.mjs <B> f7-31403.json` | installed Open WebUI 0.12.3 bundle, Pyodide 314.0.3 |
| Versions | none | `node versions.mjs owui versions-31403.json` | installed Open WebUI 0.12.3 bundle |
| M15 | none (dump `REASONS` first, below) | `node m15u1_status.mjs <browser-url> <webui-url> ../../data/sales.csv <reasons.json> <webui.log> <out-dir>` | installed Open WebUI 0.12.3, `webui/launch.sh --stub` |
| M16 | `m16u1_dump.py <checks.json>` (texts + the stub's expected PASS reply) | `node m16u1_checks.mjs <browser-url> <webui-url> ../../data/sales.csv <checks.json> <out-dir>` | installed Open WebUI 0.12.3, `webui/launch.sh --stub` |
| M17 | none | `node m10u3_demo.mjs <browser-url> <webui-url> ../../data/<csv> <arm> 1 <out-dir>` per Japanese arm (`ja-simple`, `ja-misleading` over `sales.csv`; `ja-clinic-simple`, `ja-clinic-misleading` over `clinic_ja.csv`) | installed Open WebUI 0.12.3, `webui/launch.sh --stub` |

## Live MX150 record — Q46

`q46_mx150.sh <out-prefix>` starts `.venv-model/bin/python -m model_backend` (port 8001, the dGPU),
sends the smoke prompt and one chart prompt three times each at temperature 0 (content SHA-256 per
reply), then runs `python -m model_backend.smoke` three times; `LONG=' '` skips the chart prompt.
Host tuple: NVIDIA GeForce MX150, driver 580.178.04, torch 2.13.0+cu126, transformers 5.16.1,
accelerate 1.15.0, fp16 Qwen2.5-Coder-0.5B-Instruct. Same probe on the unpruned runtime lock
(`ee9518e`, `.venv-model` then one audit bump behind its lock: multidict 6.7.1 vs 6.9.1) and on
the pruned lock (Q46, synced): the short reply `print(2 + 3)` (8 tokens) and the 420-token chart
reply are byte-identical in all 3 runs of each, and identical across the two locks (SHA-256
`bdee2c42f73aed06…`, `e440fe5711654d55…`). Cool start (GPU 59 °C, smoke 63-64 °C, 1657-1670 MHz):
smoke 26.01-26.25 tok/s unpruned, 25.86-26.30 pruned (M10.5 baseline: 24.397 at 52-53 °C). Under
sustained chart replies both decay as the host heats (69 °C, 1480 MHz): pruned 25.8, 23.5, 18.5
tok/s, then smoke 11.5-22.6; unpruned 25.1, 21.2, 12.6, then smoke 11.8-12.1.

## Live MX150 record — M19.9

`m19u9/` = the six banner arms on the real model, 5 runs each, against `webui/launch.sh --fresh` at
`97247a7` (demo pair `webui/demo-paste-in/`: tool sha256 `a52a8bfbd216e33e…`, filter
`df7023fd1ddb67a1…`). Host tuple: NVIDIA GeForce MX150, driver 580.178.04, torch 2.13.0+cu126,
transformers 5.16.1, fp16 Qwen2.5-Coder-0.5B-Instruct, greedy (the demo adapter: temperature 0.0,
512 tokens), Open WebUI 0.10.2, headless Chromium 151. Per run: `<arm>-<n>.json` (verdict before +
after reload, PNG count, status line) + screenshots + the figure PNG of a pass; `summary.json` =
per run the verdicts, PNGs, status code, program SHA-256 + whether a misleading program carries
the requested call, and each distinct program's text (read back from the chat's "Show checks"
listing).

Result: honest arms (`simple`, `ja-simple`, `ja-clinic-simple`) 15/15 pass with 1 PNG, before and
after reload; misleading arms 15/15 carry the requested call and block with 0 PNGs —
`misleading` + `ja-misleading` `zero_not_in_limits`, `ja-clinic-misleading` `axis_inverted`.
Greedy decoding wrote one program per arm (5 distinct across the six arms). Exploratory batches
(not recorded): with the pre-M19.9 plain-word misleading prompts, 0/15 misleading runs carried the
distortion, so each passed as an honest chart; that is why the misleading arms name the call.

Rerun from the repository root with `.venv-model` + `.venv-webui` set up, one terminal each:

```
webui/launch.sh --fresh
set -a; . ./.env; set +a
"$CHROME" --headless=new --remote-debugging-port=9333 --user-data-dir="$(mktemp -d)" about:blank &
cd .agent/measurements
export FV_WEBUI_EMAIL=operator@localhost FV_WEBUI_PASSWORD=loopback-dev-password
node m10u3_demo.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 ../../data/sales.csv simple 0 /tmp/warmup
for arm in simple misleading ja-simple ja-misleading; do node m10u3_demo.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 ../../data/sales.csv "$arm" 5 m19u9; done
for arm in ja-clinic-simple ja-clinic-misleading; do node m10u3_demo.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 ../../data/clinic_ja.csv "$arm" 5 m19u9; done
```

The zero-attempt first call signs in once: on a fresh instance the harness's first sign-in can
race the page (`Node is detached from document`); rerun it until it exits 0.

## Live MX150 record — Q68

`q68/` = the Q68 typed-number prompts and the six banner arms on the real model, 5 runs each, against
`webui/launch.sh --fresh` with the Q68 demo pair (`webui/demo-paste-in/`: tool sha256
`f5ba9e175040d501…`, filter `70a5b691127b6da8…`). Host tuple: NVIDIA GeForce MX150, driver 580.178.04,
torch 2.13.0+cu126, transformers 5.16.1, fp16 Qwen2.5-Coder-0.5B-Instruct, greedy (the demo adapter:
temperature 0.0, 512 tokens), Open WebUI 0.11.3, headless Chromium 151. Per run: `<label>-<n>.json`
(verdict before + after reload, PNG count + SHA-256, status line, the program the "Show checks"
embed lists) + the figure PNG of each passing turn; screenshots are not kept.

`chain_demo.mjs` drives a chain: one fresh chat per attempt, each prompt a follow-up in it.
- `single` (`Draw bars for A 3, B 5, C 9.`): 5/5 pass with 1 PNG, before and after reload.
- `red` (`Draw a bar chart with categories A, B, C and values 3, 5, 9.`, then `Make the bars red.`):
  5/5 chains pass on both turns with 1 PNG each, before and after reload; turn 2 calls
  `plt.bar(categories, values, color='red')` and its PNG shows red bars (one PNG SHA-256 across
  the 5 runs).
- Before Q68 (bf52d39 demo pair, same stack, 1 run each): `single` and turn 2 of `red` fail
  `program_error`.

Banner arms (`m10u3_demo.mjs`, the M19.9 protocol): each arm wrote the same program in all 5 runs, byte-identical
to its M19.9 program (the file template's bytes are unchanged). Honest arms 15/15 pass with 1 PNG,
before and after reload. `misleading` + `ja-misleading` 10/10 carry the requested call and block
with 0 PNGs, `zero_not_in_limits`. `ja-clinic-misleading` carries the requested call but blocks
`program_error` in 5/5: the program draws `grouped_df.plot(kind='bar')` over a `DatetimeIndex`, which
pandas 3.0.2 (the Open WebUI 0.12.3 bundle) refuses with `ValueError: Must supply freq for datetime
value` (host pandas 2.3.3 draws it), so its figure never exists and no run shows the inverted axis
block (M19.9 on Open WebUI 0.10.2: `axis_inverted`). Q70 below: the arm now also names `plt.plot`.

Rerun from the repository root with the M19.9 setup (stack, browser, sign-in variables), then:

```
cd .agent/measurements
node chain_demo.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 single 5 q68 'Draw bars for A 3, B 5, C 9.'
node chain_demo.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 red 5 q68 'Draw a bar chart with categories A, B, C and values 3, 5, 9.' 'Make the bars red.'
for arm in simple misleading ja-simple ja-misleading; do node m10u3_demo.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 ../../data/sales.csv "$arm" 5 q68; done
for arm in ja-clinic-simple ja-clinic-misleading; do node m10u3_demo.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 ../../data/clinic_ja.csv "$arm" 5 q68; done
```

`chain_demo.mjs` takes `--csv <path>` before the prompts to attach a file to the first turn.

## Live MX150 record — Q69

`q69/` = Q68's two typed prompts and three colour follow-ups on the real model, 5 runs each, against
`webui/launch.sh --fresh` with the Q69 demo pair (the no-file template puts the request after its
guidance; `webui/demo-paste-in/`: tool sha256 `f5ba9e175040d501…`, filter `ea8b689279ffe846…`).
Host tuple and record format: as Q68. Each label wrote the same programs in all 5 runs, and every
turn passed with 1 PNG, before and after reload:
- `single` (`Draw bars for A 3, B 5, C 9.`): `ax.bar(labels, values)`.
- `red` (A/B/C chart, then `Make the bars red.`): `plt.bar(categories, values, color='red')`, the
  Q68 red PNG byte for byte.
- `green` (`Draw a bar chart of cats 4, dogs 6.`, then `Make it green.`): `color='green'`.
- `orange` (`Draw bars for X 2, Y 7.`, then `Make the bars orange.`): `color='orange'`.
- `same` (A/B/C chart, then `Draw the same chart with red bars.`): `plt.bar(categories, values)`,
  default blue; the colour reaches the title alone (queue row Q69).

Rerun as Q68, with these chains:

```
cd .agent/measurements
node chain_demo.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 single 5 q69 'Draw bars for A 3, B 5, C 9.'
node chain_demo.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 red 5 q69 'Draw a bar chart with categories A, B, C and values 3, 5, 9.' 'Make the bars red.'
node chain_demo.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 green 5 q69 'Draw a bar chart of cats 4, dogs 6.' 'Make it green.'
node chain_demo.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 orange 5 q69 'Draw bars for X 2, Y 7.' 'Make the bars orange.'
node chain_demo.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 same 5 q69 'Draw a bar chart with categories A, B, C and values 3, 5, 9.' 'Draw the same chart with red bars.'
```

## Live MX150 record — Q70

`q70/` = the six banner arms on the real model, 5 runs each (the M19.9 protocol), against
`webui/launch.sh --fresh` with the Q69 demo pair, after `ja-clinic-misleading` also names `plt.plot`
(`…待ち時間が短く見えるように、plt.plot で線を描き、plt.ylim(60, 0) で y 軸を反転してください。`). Host tuple and
record format: as Q68. Honest arms 15/15 pass with 1 PNG, before and after reload. Misleading arms
15/15 carry the requested call and block with 0 PNGs: `misleading` + `ja-misleading`
`zero_not_in_limits`, `ja-clinic-misleading` `axis_inverted` (its program draws
`plt.plot(grouped_df.index, grouped_df.values, …)`, then `plt.ylim(60, 0)`). Each arm wrote the same
program in all 5 runs; the five unchanged arms' programs equal their M19.9 programs byte for byte.
The stub replay M17 passes on the new prompt.

Rerun: the M19.9 commands, with `q70` as the output directory.

## Live MX150 record — deps U3

`deps-u3/` = the six banner arms on the real model, 5 runs each (the M19.9 protocol), against
`gpu-run webui/launch.sh --fresh` at `dbe434a` (demo pair `webui/demo-paste-in/`: tool sha256
`60cc89fceb0f075b…`, filter `c60b979959ed93b8…`). Host tuple: NVIDIA GeForce MX150, driver
580.178.04, CPython 3.15.0, torch 2.14.1+cu126, transformers 5.20.2, tokenizers 0.23.3, fp16
Qwen2.5-Coder-0.5B-Instruct, greedy (temperature 0.0, 512 tokens), Open WebUI 0.12.3, headless
Chromium 151; `gpu-run` keeps the backend in the normal CPU class. Honest arms 15/15 pass with 1 PNG,
before and after reload. Misleading arms 15/15 carry the requested call and block with 0 PNGs:
`misleading` + `ja-misleading` `zero_not_in_limits`, `ja-clinic-misleading` `axis_inverted`. Each
arm wrote one program in all 5 runs, byte-identical to its Q70 program. Same tuple,
`q46_mx150.sh` under `gpu-run`: the short reply 3/3 `bdee2c42f73aed06…`; the chart prompt 3/3
`e577107d8e3c4a59…` (423 tokens; the transformers 5.16.1 stacks wrote `e440fe5711654d55…`),
42.0-42.3 s each; smoke 20.5-20.7 tok/s at 66 °C / 1657 MHz.

Rerun: the M19.9 commands with `gpu-run webui/launch.sh --fresh` and `deps-u3` as the output
directory.

## Live gpt-6-luna record — luna

`luna/` = 55 live cases (`luna/cases.json`: honest, misleading and out-of-scope requests over
`data/*.csv` + typed data, EN + JA), 3 fresh chats each, through `webui/launch.sh --codex`
(`gpt-6-luna` on the user's ChatGPT subscription via `codex app-server`, the production pair, native
function calling). Protocol, config tuple, per-case table and findings: `luna/README.md`.

Rerun from the repository root with `.venv-webui` set up, an idle CPU (`heavy --status` shows no
holder) and Codex signed in with ChatGPT:

```
WEBUI_PROVISION_DATA_DIR=.scratch/luna/webui-data CODEX_BRIDGE_DUMP_DIR=.scratch/luna/requests CODEX_BRIDGE_EFFORT=medium webui/launch.sh --codex
set -a; . ./.env; set +a
"$CHROME" --headless=new --remote-debugging-port=9333 --user-data-dir="$(mktemp -d)" about:blank &
cd .agent/measurements
export FV_WEBUI_EMAIL=operator@localhost FV_WEBUI_PASSWORD=loopback-dev-password
node luna_live.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 luna/cases.json 3 luna/records
cd ../.. && uv run --locked python .agent/measurements/luna_classify.py .scratch/luna/requests
```

`luna_live.mjs` keeps an existing record, so a rerun resumes; a new output directory starts over.


## Live gpt-6-luna record — Q78

`q78/` = the model's note (`.agent/archive/contracts/q78.md`): the six banner prompts × 3 fresh chats
+ banner prompt 7 (`luna/cases.json` `m05`, `q78/prompt7/`) × 3, through `webui/launch.sh --codex`
on a scratch instance (ports 8090/8011): `gpt-6-luna` at the arm's default reasoning effort `low`,
codex-cli 0.163.0, the production pair (tool sha256 `c5ed9c5b3dddc4da…`, filter
`80702c4c0261153d…`, Valve `model_note` on), Open WebUI 0.12.3, headless BrowserOS neo
151.0.8162.137 at normal scheduling class (`systemd-run --user`). Per run `<arm>-<n>.json`
(`m10u3_demo.mjs`: verdict before + after reload, the persisted reply, the listed program);
`summary.json` = `q78_summary.py` over them (verdict, the note as the reply shows it, its language,
whether the program carries the call the prompt names).

Result: honest prompts 9/9 pass with no note; misleading prompts 2, 4, 6: 9/9 drew the honest chart
(the named call absent) and pass, each with a note stating the conflict — the English request's
notes in English 3/3, the Japanese ones in Japanese 6/6. Prompt 7: 2/3 block `axes_twin`, both
notes claiming the chart avoided the misleading scaling while the program kept the second axis (the
note = the model's statement, never checked); 1/3 drew one y axis and passed with a note.
`q78/batch1/` = the same 18 runs on the approved wording "in the language of the request": every
note of the English request in Spanish (3/3; a bridge replay of that request: French, Spanish,
Spanish), the Japanese ones in Japanese, one `ja-clinic-misleading` run without a note ⇒ the shipped
sentence names the language by the kana rule.

Rerun from the repository root with `.venv-webui` set up and Codex signed in with ChatGPT:

```
WEBUI_PROVISION_DATA_DIR=.scratch/q78/data webui/launch.sh --codex --fresh
set -a; . ./.env; set +a
systemd-run --user --collect "$CHROME" --headless=new --remote-debugging-port=9333 --user-data-dir="$(mktemp -d)" about:blank
cd .agent/measurements
export FV_WEBUI_EMAIL=operator@localhost FV_WEBUI_PASSWORD=loopback-dev-password
for arm in simple misleading ja-simple ja-misleading; do node m10u3_demo.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 ../../data/sales.csv "$arm" 3 q78; done
for arm in ja-clinic-simple ja-clinic-misleading; do node m10u3_demo.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 ../../data/clinic_ja.csv "$arm" 3 q78; done
node luna_live.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 luna/cases.json 3 q78/prompt7 '^m05$'
cd ../.. && uv run --locked python .agent/measurements/q78_summary.py .agent/measurements/q78 .agent/measurements/q78/summary.json
```
## Live render record — Q79

`q79/` = the model's note as plain text under its bold label (`.agent/archive/contracts/q79.md`),
read by Open WebUI 0.12.3's own renderer: `q79_corpus.py` writes 12 hostile notes × EN + JA through
the production `filter.py::_note_line` (links, images, bare URLs, raw HTML, `<details>`, KaTeX in
every delimiter, emphasis, headings, citations, `{{…}}` replacements, mentions, entities, literal
backslashes, line breaks, bidi, NUL); `q79_render.mjs` stores each as an assistant reply in a new
chat of a scratch `--stub` instance, opens it in headless BrowserOS neo 151.0.8162.137 and reads the
reply DOM. `result.json`: 24/24 plain text — the label alone styled (English `strong` at weight 500, Japanese KaTeX `\textbf` at 700, Q80), no `a`, `img`,
`iframe`, `video`, `details`, `u`, `code`, `em`, `del`, `sup` or KaTeX element, the paragraph text
equal to the label + the note as written. Positive control `control-result.json` (the same notes
unescaped): 18/24 render markup — links, autolinks, `<u>`, emphasis + code spans, a footnote, an
`<iframe>` from `{{HTML_FILE_ID_…}}`. The first escaped run rendered `\[w\]` as math (the KaTeX
block `start()` scans escape pairs), which the word joiner after an escaped backslash closed.

Rerun from the repository root with `.venv-webui` set up:

```
WEBUI_PROVISION_DATA_DIR=.scratch/q79/data webui/launch.sh --stub --fresh
set -a; . ./.env; set +a
systemd-run --user --collect "$CHROME" --headless=new --remote-debugging-port=9333 --user-data-dir="$(mktemp -d)" about:blank
PYTHONPATH="$PWD" uv run --locked python .agent/measurements/q79_corpus.py /tmp/q79-corpus.json
cd .agent/measurements
FV_WEBUI_EMAIL=operator@localhost FV_WEBUI_PASSWORD=loopback-dev-password node q79_render.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 /tmp/q79-corpus.json q79/result.json
```

## Reduction claims — M13.6

Rerun all reduction IDs from the repository root after the pinned environment + Node install:

```
nice -n 19 ionice -c3 bash .agent/measurements/r_run.sh
```

`r_run.sh` runs 9 stages: corpus · host · host-optional · bundle (Pyodide 314.0.3) ·
comparison · locales · bundle renderer supplement · result projection · checks.
Logs + raw results → `r-data/`; normalized per-id results → `results/<id>.json`.
`check.py <id>…` reads those results; it does not rerun the experiment. It compares exact types,
keys, list order/length + values against `expected/<id>.json`; a missing file or mismatch returns
nonzero with the id + cause. Expected files state the cited claims, never a fresh run's output.
The all-id driver runs this reduction replay once alongside the other table IDs.

Host pins = root NumPy 2.4.3 + pandas 3.0.2; optional leg adds bottleneck 1.6.0 + numexpr 2.14.2.
Sandbox = the installed Open WebUI 0.12.3 bundle: pandas 3.0.2 + NumPy 2.4.3 on Pyodide 314.0.3.
Each host leg uses `uv run --locked --with pandas==3.0.2`; the optional leg adds the two pinned
`--with` arguments. The bundle leg loads the bundle's own wheels (`o8_bundle.mjs`).
Locales `C`, `C.utf8`, `en_US.utf8` must exist. Only the sandbox supplement loads matplotlib.
`make_r_inputs.py` retains the fixed seed, exact-float cases + interleaved CSVs.
`r_probe.py` runs unchanged inputs in every environment; `r_compare.py` compares encoded
bits/dtypes/order and detects a one-bit planted control. `r_supplement.py` supplies the locale,
parser + renderer controls. `r_results.py` projects measured data; it reads no expected files.

Every row's rerun command is `bash .agent/measurements/r_run.sh`; the last column rechecks its
result separately after that command.

| id | published claim | source predicate | compare command from repository root |
|---|---|---|---|
| R1 | Kahan 0/16,062 groups; naive 2,761/4,000, worst 8,192 ulp; fsum 1,483/4,000, worst 5,252 ulp; four-cell witness separates Kahan, naive + fsum/Neumaier | `m13u6.md` R1; `pysrc.md` aggregation bullet | `uv run --locked python .agent/measurements/check.py R1` |
| R2 | float mean = Kahan sum / non-NaN count, zero disagreements | `m13u6.md` R2; `pysrc.md` aggregation bullet | `uv run --locked python .agent/measurements/check.py R2` |
| R3 | int64 mean casts each cell first: `0x1.5555555555555p+51` vs exact-divide `0x1.5555555555556p+51`, 1 ulp; int sum exact; in-profile sum `0x1.0000000000000p+31` | `m13u6.md` R3 + R3 closing clarification | `uv run --locked python .agent/measurements/check.py R3` |
| R4 | min/max keep the first tied zero's sign: [-0,+0] → -0; reversed → +0 | `m13u6.md` R4; `pysrc.md` aggregation bullet | `uv run --locked python .agent/measurements/check.py R4` |
| R5 | int64 `[2**63-1,1]` sum wraps to `-2**63` | `m13u6.md` R5 | `uv run --locked python .agent/measurements/check.py R5` |
| R7 | string keys follow code-point order in all three locales; en_US collation differs; numeric keys sort numerically | `m13u6.md` R7; `pysrc.md` aggregation bullet | `uv run --locked python .agent/measurements/check.py R7` |
| R8 | CSV keys ['2','a','10','2'] type as strings and group to ['10','2','a'] | `m13u6.md` R8 | `uv run --locked python .agent/measurements/check.py R8` |
| R-ACCEL | optional modules present vs absent: 0 changed sections; all four flag pairs: 0 changed results in every runtime | `pysrc.md` aggregation bullet | `uv run --locked python .agent/measurements/check.py R-ACCEL` |
| R-PORT | host vs each Pyodide build: 0 differences over 96,372 reduction rows | `m13u6.md` closing review G3; `pysrc.md` aggregation bullet | `uv run --locked python .agent/measurements/check.py R-PORT` |
| R-BAR | int64 sums [4294967294,-4294967296] raise the named OverflowError in bar/barh on both builds; both int32 endpoints draw; line/scatter preserve float64 bits | `m13u6.md` B3; `pysrc.md` renderer-bound bullet | `uv run --locked python .agent/measurements/check.py R-BAR` |

Comparison control: after the rerun, plant one count in R1's expected result. Require rc=1 +
`R1: FAIL $.sum.host.kahan.differences: observed 0 != expected 1`; restore byte-identical bytes.

```
uv run --locked python - <<'PY'
import json, subprocess, sys
from pathlib import Path
root = Path('.agent/measurements')
path = root / 'expected/R1.json'
saved = path.read_bytes()
try:
    expected = json.loads(saved)
    assert expected['sum']['host']['kahan']['differences'] == 0
    expected['sum']['host']['kahan']['differences'] = 1
    path.write_text(json.dumps(expected, indent=2, sort_keys=True) + '\n')
    result = subprocess.run([sys.executable, str(root / 'rerun_all.py'), '--check-only', 'R1'], capture_output=True, text=True)
    print(f'one-count probe rc={result.returncode}\n{result.stderr}', end='')
    assert result.returncode == 1
    assert 'R1: FAIL $.sum.host.kahan.differences: observed 0 != expected 1' in result.stderr
finally:
    path.write_bytes(saved)
assert path.read_bytes() == saved
PY
```

Add a new self-checking id by committing `expected/<id>.json` from its published predicate and
emitting an independent `results/<id>.json` from its measurement. Register its replay in
`rerun_all.py`; the inventory check keeps the driver, README and expectations equal.

## What each one backs

| id | measures | backs |
|---|---|---|
| S6 | host pandas vs Pyodide pandas, parsed cells | CSV divergence is stdlib-vs-pandas, not host-vs-wasm |
| T3 | whether ANY significant-digit cap makes stdlib `float` agree with default `pd.read_csv` | C10's "no cap repairs it" |
| T4 | stdlib-vs-pandas structural divergences (BOM, ragged rows, post-quote junk) | C6's four refusal witnesses |
| T5 | default NA spellings pandas recognises | C9's 19-spelling literal |
| T6 | whether the RENDERER alters plotted values | C10 clause 6: matplotlib bar's `-0.0` and Pyodide bar's int32 raise |
| T7 | candidate admitted region, plain and quoted, against target Pyodide | C10's 0/4,000,000 |
| T8 | beyond-int32 fixed-point parsing vs host pandas AND stdlib `float`; float64-column bar heights; mixed integer/decimal tokens | Q12 production range changed: integer columns keep int32; float64 cells retain the 15-digit cap; float64 bar reductions stay within ±2**53. Evidence: 0/1,345,852 host↔Pyodide decimal disagreements/form/build through ±2**53; ≤15-digit subset 0/623,350 vs stdlib, unrestricted 215,269 disagreements; mixed column 0/1,000,049 vs both; 0/2,364 boundary + 0/2,097 mixed artist-height changes/build |
| F7 | the production `wrapper_code` in the installed bundle: the banner's simple program, a line, a scatter, a program that never calls `show`, and six Japanese legs + `identity` (M17.1, Q44, Q74: Japanese title + category ticks with the font the filter finds on this host (`owui_files.find_cjk_font`, `FV_CJK_FONT` = the admin's Valve; a collection cuts its first face) cut by `fonts.cut`, the filter's stdlib cut, with every fontTools import blocked (`ja-font`) and whole, as a refused cut sends it (`ja-whole`); `identity` = every character the `ja-font` cut keeps drawn by the bundle's FT2Font from both fonts; the same without the font; a `$…$` Japanese title; a y label built by `chr` outside the cut (`ja-miss`); each in a fresh runtime; `ja-second` = `ja-font` then a second figure whose cut holds two glyphs the first lacks, in ONE runtime; `ja-marker-repeat` = one `$週$` text-marker figure twice in ONE runtime; `ja-textpath` = a `TextPath` marker built by `chr` outside the cut) | M19.5 wiring: all twelve replies have one tagged parseable description line before one PNG line, `stderr: null`, `result: null` and a valid PNG signature; a literal plotting import still triggers the installed prelude (0.12.3: once the import loaded the package, its patched `show` prints a PNG); the reader counts missing glyphs for `ja-no-font` (control), `ja-mathtext` (declared limit) + `ja-miss` (a miss blocks) + both replies of `ja-marker-repeat` (the parse cache hides no repeat) + `ja-textpath` (path text counts its `.notdef` glyphs) and none for the rest, `ja-second`'s earlier reply included; Q44: Q74: cut by the filter's stdlib cut with fontTools blocked, `ja-font` RPC source ≤ 99,999 B (measured 80,069 with `SourceHanSansJP-Regular.otf`, cut 16,004 B in 14 ms, one sample; `ja-whole` 6,141,697); `identity`: the bundle's FreeType 2.13.3 draws each of ≥ 100 kept characters (117 here) unhinted + natively hinted as the whole font (0 differences; autohinted outlines follow the glyph repertoire, 9, unprojected) |
| M15 | the failure status line in a live `--stub` chat: the misleading banner prompt, a kana prompt, a blocked `pyodide.js`, the simple prompt; DOM before + after reload + REST `statusHistory`/`content`/`output`/`files`; every `REASONS` text set into the live `line-clamp-1` element at 1280×800, sidebar open | M15.1 L1-L5: exit code 0 = 4/4 cases + their log records + 0/102 texts clamped (M19.5 reasons) |
| M16 | the "Show checks" embed in a live `--stub` chat: the misleading banner prompt, a kana prompt, the simple prompt; one frame after the status line + before the verdict, collapsed < 60 px, expanded = its content (no inner scroll), collapsed again, rows + marks + texts + cause per state, before + after reload; REST `content`/`output`/`embeds`; the expanded FAIL at 760 px; Q62: per (Open WebUI theme, OS scheme) pass — light/light, dark/dark, dark/light, light/dark, the scheme CDP-emulated — the frame reads the emulated scheme, its surface = Open WebUI's behind it in a matching pass + another in a mismatch (published `surfaces`: light `#ffffff`, dark `#161616`), and in each matching pass Tab from the frame reaches every summary + the opened row's link, each `:focus-visible` with an outline ≥ 2 px; M18.4 + M20.2 + M20.4 (M19.5 rows): per case each listed row opened (misleading: `axes` = related lines 12-16 with `plt.ylim(30000, 45000)` marked, `run` = its note, not-checked `values` = nothing; kana: `program`; pass: `program` = all 18 lines, `axes` = 12-16 (`plt.xticks(rotation=45)` at 16, M20.4), `values` = 5 · 8 · 12, `columns` = 5 · 8 · 12-15, `attach` = its note) = hand-stated listing label + lines + marked line + mark text or note + `#check-<id>` link, frame grows to the row and fits, the first row's link opens one new tab at that URL (live), the row closes again, live + reload | M16.1 L1-L5 + M18.4 L1-L3 + M20.2: exit code 0 = 3/3 cases with all their rows + the narrow re-size; screenshots inspected by hand; needs a Chromium that honours CDP `prefers-color-scheme` emulation (chromiumfish 151 pins the scheme light ⇒ its scheme passes fail; BrowserOS Neo 151.0.8162 honours it); (`chromiumfish` draws every font family, generic `monospace` included, in one serif face, so its PNGs show the listing proportional; BrowserOS Neo measured the shipped stack monospace) |
| M17 | the Japanese banner prompts in a live `--stub` chat, one attempt per arm over its own CSV: verdict before + after reload, the verdict line, the interpretation's first sentence, the PNG attachment count, the status line's code + language | M17.4 L2 (M19.5 arms; Q81: the verdict line in Japanese): `ja-simple` + `ja-clinic-simple` pass with `図の検証に合格しました。`, 1 PNG and a Japanese interpretation (`棒: sales.csv の region 列ごとの revenue 列の合計。`, `折れ線: clinic_ja.csv の 年月 列ごとの 平均待ち時間 列の平均。`); `ja-misleading` + `ja-clinic-misleading` fail with `図の検証に合格しませんでした。画像は表示されません。`, 0 PNGs and a Japanese status line ending `(zero_not_in_limits)`, `(axis_inverted)` |
| X1 | chance matches of the nine admitted computations (Q45) through the SHIPPED candidates + matcher (`explain.py::computations`, `_coverage`; `computed.py::typed`): a made-up series counts for a computation when one of its candidates explains every point and no vocabulary candidate does; CSV leg = keyed series of n distinct keys from one non-numeric column holding ≥ n keys (`null` where none does: these CSVs hold 2-4), request leg = values alone over `1 to m` and m random integers, membership as the judge matches typed numbers; 10,000 trials per size per grid (`int`, `dec2` over [0, 2M], M = the computation's largest value); each computation on its own grid, so the rates do not combine | the rates `docs/verification.md` § Computed values publishes beside each computation |
| Image | the generated production + demo pairs inside the official Open WebUI image, network off: each file imports and constructs (`Tools`, `Filter`) in the image's interpreter; each banner arm's host-drawn description (host reader, test font for Japanese text) judged by the filter's embedded judge with its own anchoring | M21.2 F11: both pairs load on the image's CPython 3.11 (red before: `SyntaxError` at `verifier.figure.anchoring` line 13 in all four files); all six arms reach their banner verdict in both pairs; Q74: no fontTools in the image, and each pair's embedded stdlib cut of both tracked test fonts (TrueType + CID-keyed CFF, the `ja-clinic-simple` arm's characters) is byte-identical to the host's and smaller than the font |

T8's `t8-data/` corpus separates ≤15-significant-digit candidates from 16–22-digit diagnostic
probes. Every decimal token has a point and 1–6 fractional digits; magnitudes span 2**31 through
2**53, both signs. One decimal token makes the mixed column float64. Plain and quoted forms
contain the same sampled rows, not independent samples. Host references and corpora are hash-bound;
one injected bit flip checks each comparison observer. Sandbox legs also draw clipped-limit bar
artists and read their heights before and after the canvas draw. `owui` uses the installed bundle
through `o8_bundle.mjs`; T8 directs cache writes into its own `node_modules/t8-owui-cache/`.
Q12 changes C10 by column branch: integer columns keep int32; float64 cells keep the ≤15-digit
cap and all other C10 clauses; float64 bar reductions stay within ±2**53. Host↔Pyodide agreement
alone does not establish the stdlib recomputation's agreement. The ≤15-digit cap's measured maxima
are `99999999999999.9` for decimal tokens and `999999999999999` for integer tokens in float64 columns.
T8 measures these environment pairs and samples, not exhaustive parser correctness or pixels.
Replay with `uv run --locked python .agent/measurements/rerun_all.py T8`; recheck with
`uv run --locked python .agent/measurements/rerun_all.py --check-only T8`.
T8's one-count control plants `expected/T8.json`'s `31403.corpora.decimals.plain.host_bit_mismatches`
0→1; require nonzero + `T8: FAIL`, then restore SHA-256-identical expected bytes.

Each result JSON carries environment details and a per-region breakdown when regions apply. A
region's `disagreements` is the count that matters. `max_ulp` applies only where both values are
finite.

Rerun M15 against a stub instance and a browser that exposes CDP. OWUI hosts its Pyodide iframe
out of process unless the browser runs with `--disable-features=IsolateSandboxedIframes`, and the
blocked case then sees no request to abort. The script exits 0 only when every case, its
`webui.log` record and the width sweep hold. `FV_CASES=<name,...>` runs a subset of `refused`,
`japanese`, `blocked` and `pass`; the width sweep needs one failing case.

In one terminal, start the stub stack and keep it running:

```
webui/launch.sh --stub
```

In a second terminal, from the repository root, run:

```
set -a; . ./.env; set +a
"$CHROME" --remote-debugging-port=9333 --user-data-dir="$(mktemp -d)" \
  --disable-features=IsolateSandboxedIframes --window-size=1280,800 about:blank &
uv run --locked python -c 'import json; from webui.paste_in.reasons import REASONS; print(json.dumps(REASONS, ensure_ascii=False))' > /tmp/reasons.json
cd .agent/measurements
FV_WEBUI_EMAIL=operator@localhost FV_WEBUI_PASSWORD=loopback-dev-password \
  node m15u1_status.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 ../../data/sales.csv /tmp/reasons.json \
  ../../.launch-logs/webui.log m15u1
```

Rerun M16 against the same stub stack and CDP browser (the M15 browser flag is harmless here). The
script exits 0 only when every case, the 760 px re-size and every scheme pass hold; it writes one PNG per
case and (theme, scheme) pass + one Tab-focus PNG per case and matching pass into `<out-dir>` for a
person to inspect. `FV_CASES=<name,...>` runs a subset of `refused`,
`japanese` and `pass`.

```
PYTHONPATH="$PWD" uv run --locked python .agent/measurements/m16u1_dump.py /tmp/checks.json
cd .agent/measurements
FV_WEBUI_EMAIL=operator@localhost FV_WEBUI_PASSWORD=loopback-dev-password \
  node m16u1_checks.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 ../../data/sales.csv /tmp/checks.json m16u1
```
