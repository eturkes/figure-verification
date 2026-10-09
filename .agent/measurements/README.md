# Measurement harnesses

Committed scripts re-derive the numeric bands and profiles cited in `.claude/rules/pysrc.md` and
`.agent/archive/contracts/m13u5.md` + `m13u6.md`. Gate + `mypy` exclude them; Pyodide legs need
Node + package downloads. Generated corpora/results are gitignored; `expected/` is tracked.
All 26 table IDs compare against hand-stated published predicates in `expected/<id>.json`.
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
`chromiumfish` CDP browser. Open WebUI must already exist in `.venv-webui` of the primary checkout.
Runtime data, verifier state, browser profile and service logs use `.scratch/measurements-live/`.
The driver stops its processes and removes that private state; copied service logs stay in
`all-data/stack-logs/`. It never attaches to the user's live stack/browser or uses ports 8000/8001/8080.
M16 theme PNGs still need visual inspection; a machine PASS claims its measured DOM predicates,
not inspected pixels.

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
For `make_s6_csv.py`, `t3.py`, `t4.py`, `t5.py`, `t7_profile.py`, `t7_quoted.py`, and
`t8_profile.py`, use `uv run --locked --with pandas==2.3.1 python .agent/measurements/<script>.py`: pandas is not in
the root development environment. Run a generator before its dependent host or sandbox leg.
`I1` (M19) runs 52 chart programs over the M19 scope and its out-of-scope census, and records each
axes child as (class, origin, data transform) — origin = the outermost Axes-module frame
(`.claude/rules/figure.md`). The projection compares the host leg with the installed bundle and
publishes the bundle's family set. `I2` measures keyed value-explanation ambiguity over `data/*.csv`:
cross-column full-series ties, shared points, tied k-point subsets and chance matches of made-up
keyed series (seed 19, 10,000 trials per size). `I3` (M19.2) runs the same 52 programs through the
reader on the host and through the production `wrapper_code` in the installed bundle, one runtime
in order (the reader's holder reused across replies), and publishes, per program, the description
fields that differ: `boxplot` labels, `reference` span shape (`Rectangle` vs `Polygon`), `subplots`
positions after `tight_layout`. `C1` (M19.6) runs every rule-corpus case (`tests/figure_corpus/`)
through the production `wrapper_code` in the installed bundle (matplotlib 3.8.4, one runtime, no
font, the CSVs under `/mnt/uploads`), judges each bundle description on the host with the case's
own Sources, and publishes the cases whose bundle verdict misses the case's expectation or differs
from the host verdict (its first run found the 3.8 glyph-warning wording the reader missed).

Run each Node command from `.agent/measurements/`. Replace `<P>` with `pyodide` (0.28.0) or
`pyodide0281` (0.28.1), and `<v>` with `0280` or `0281`, respectively. Every `.mjs` takes `<P>` as
its first argument and an optional result filename as its second. `s6_pyodide.mjs` alone also
accepts a compatible local `indexURL` as its third argument. `f7_wrapper.mjs` is the exception: it takes `<B>`, the installed Open WebUI Pyodide directory
(`../../.venv-webui/lib/python3.12/site-packages/open_webui/frontend/pyodide`, 0.28.3), and a
required result filename. It calls `f7_export.py` through `uv run --no-sync --locked`; set
`UV_PROJECT_ENVIRONMENT` to the ready root environment. From the repo root, run:

```
export UV_PROJECT_ENVIRONMENT="$PWD/.venv" UV_LINK_MODE=copy UV_NO_SYNC=1 PYTHONPATH="$PWD/src"
node .agent/measurements/f7_wrapper.mjs "$PWD/.venv-webui/lib/python3.12/site-packages/open_webui/frontend/pyodide" f7-0283.json
```

F7 reads the installed frontend's `execute:python` package regexes, iframe prelude and reply
shaping at runtime. It loads only source-detected packages, runs the literal-trigger prelude, then
executes the wrapper. Missing or changed anchors fail loudly. Every wrapper must emit one tagged
description line before one PNG line with a valid signature; the shaped reply must have
`stderr: null` and `result: null`. The description's glyph count is nonzero exactly for the two
glyph legs. A literal plotting import must trigger the installed prelude's `SyntaxError`.

The other Node commands:

```
cd .agent/measurements
node t6_pyodide.mjs pyodide t6-0280.json
node t6_pyodide.mjs pyodide0281 t6-0281.json
node versions.mjs pyodide0281 versions-0281.json
```

The `pyodide0281` npm package omits its wheels. Each sandbox script reads the installed package
version and fetches missing wheels from that version's jsDelivr Pyodide build. Pyodide caches the
wheels in the ignored `node_modules/`; the first run requires network access. The Node scripts
write their result JSON beside themselves. `versions.mjs` prints Python, platform, Pyodide, NumPy,
and pandas versions for the selected build.

| id | host script(s), in run order | Node command | build behind the published number |
|---|---|---|---|
| S6 | `make_s6_csv.py` | `node s6_pyodide.mjs <P> s6-<v>.json` | 0.28.1; 0.28.0 rerun |
| T3 | `t3.py` | none | host only |
| T4 | `t4.py` | none | host only |
| T5 | `t5.py` | none | host only |
| T6 | `make_s6_csv.py` (same S6 corpus) | `node t6_pyodide.mjs <P> t6-<v>.json` | 0.28.1; 0.28.0 rerun |
| T7 | `t7_profile.py`, then `t7_quoted.py` | `node t7_pyodide.mjs <P> t7-<v>.json` | 0.28.1; 0.28.0 rerun |
| T8 | `make_t8_inputs.py`, then `t8_profile.py` | `node t8_pyodide.mjs <P> t8-<v>.json`; `node t8_pyodide.mjs owui t8-0283.json` | 0.28.0, 0.28.1; installed OWUI 0.28.3 |
| I1 | `i1_census.py` | `node i1_pyodide.mjs owui i1-0283.json` | host matplotlib 3.9.4 vs installed Open WebUI bundle, 0.28.3 (matplotlib 3.8.4) |
| I2 | `i2_ambiguity.py` | none | host only |
| I3 | `i3_export.py` | `node i3_pyodide.mjs owui i3-0283.json` | host reader (matplotlib 3.9.4) vs production wrapper in the installed Open WebUI bundle, 0.28.3 |
| C1 | `c1_export.py` | `node c1_pyodide.mjs owui c1-0283.json` | rule corpus: host judge (matplotlib 3.9.4) vs production wrapper in the installed Open WebUI bundle, 0.28.3 (matplotlib 3.8.4) |
| F7 | `f7_export.py` (called by the Node leg) | `node f7_wrapper.mjs <B> f7-0283.json` | installed Open WebUI bundle, 0.28.3 |
| Versions | none | `node versions.mjs <P> versions-<v>.json` | selected build |
| M15 | none (dump `REASONS` first, below) | `node m15u1_status.mjs <browser-url> <webui-url> ../../data/sales.csv <reasons.json> <webui.log> <out-dir>` | installed Open WebUI 0.10.2, `webui/launch.sh --stub` |
| M16 | `m16u1_dump.py <checks.json>` (texts + the stub's expected PASS reply) | `node m16u1_checks.mjs <browser-url> <webui-url> ../../data/sales.csv <checks.json> <out-dir>` | installed Open WebUI 0.10.2, `webui/launch.sh --stub` |
| M17 | none | `node m10u3_demo.mjs <browser-url> <webui-url> ../../data/<csv> <arm> 1 <out-dir>` per Japanese arm (`ja-simple`, `ja-misleading` over `sales.csv`; `ja-clinic-simple`, `ja-clinic-misleading` over `clinic_ja.csv`) | installed Open WebUI 0.10.2, `webui/launch.sh --stub` |

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
"$(chromiumfish path)" --headless=new --remote-debugging-port=9333 --user-data-dir="$(mktemp -d)" about:blank &
cd .agent/measurements
export FV_WEBUI_EMAIL=operator@localhost FV_WEBUI_PASSWORD=loopback-dev-password
node m10u3_demo.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 ../../data/sales.csv simple 0 /tmp/warmup
for arm in simple misleading ja-simple ja-misleading; do node m10u3_demo.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 ../../data/sales.csv "$arm" 5 m19u9; done
for arm in ja-clinic-simple ja-clinic-misleading; do node m10u3_demo.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 ../../data/clinic_ja.csv "$arm" 5 m19u9; done
```

The zero-attempt first call signs in once: on a fresh instance the harness's first sign-in can
race the page (`Node is detached from document`); rerun it until it exits 0.

## Reduction claims — M13.6

Rerun all reduction IDs from the repository root after the pinned environment + Node install:

```
nice -n 19 ionice -c3 bash .agent/measurements/r_run.sh
```

`r_run.sh` runs 11 stages: corpus · host · host-optional · Pyodide 0.28.0 · Pyodide 0.28.1 ·
comparison · locales · both sandbox renderer supplements · result projection · checks.
Logs + raw results → `r-data/`; normalized per-id results → `results/<id>.json`.
`check.py <id>…` reads those results; it does not rerun the experiment. It compares exact types,
keys, list order/length + values against `expected/<id>.json`; a missing file or mismatch returns
nonzero with the id + cause. Expected files state the cited claims, never a fresh run's output.
The all-id driver runs this reduction replay once alongside the other table IDs.

Host pins = root NumPy 2.2.5 + pandas 2.3.1; optional leg adds bottleneck 1.6.0 + numexpr 2.14.2.
Sandbox pandas = 2.3.0 on Pyodide 0.28.0; 2.3.1 on Pyodide 0.28.1; both carry NumPy 2.2.5.
Each host leg uses `uv run --locked --with pandas==2.3.1`; the optional leg adds the two pinned
`--with` arguments. Node legs reuse the existing frozen lock, loading the selected build's wheels.
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
| F7 | the production `wrapper_code` in the installed bundle: the banner's simple program, a line, a scatter, a program that never calls `show`, and three Japanese legs, each in a fresh runtime (M17.1: Japanese title + category ticks with the installed Open WebUI's `NotoSansJP-Regular.ttf`; the same without the font; a `$…$` Japanese title with the font) | M19.5 wiring: all seven replies have one tagged parseable description line before one PNG line, `stderr: null`, `result: null` and a valid PNG signature; a literal plotting import still triggers `SyntaxError`; the reader counts missing glyphs for `ja-no-font` (control) + `ja-mathtext` (declared limit) and none for `ja-font` |
| M15 | the failure status line in a live `--stub` chat: the misleading banner prompt, a kana prompt, a blocked `pyodide.js`, the simple prompt; DOM before + after reload + REST `statusHistory`/`content`/`output`/`files`; every `REASONS` text set into the live `line-clamp-1` element at 1280×800, sidebar open | M15.1 L1-L5: exit code 0 = 4/4 cases + their log records + 0/102 texts clamped (M19.5 reasons) |
| M16 | the "Show checks" embed in a live `--stub` chat: the misleading banner prompt, a kana prompt, the simple prompt; one frame after the status line + before the verdict, collapsed < 60 px, expanded = its content (no inner scroll), collapsed again, rows + marks + texts + cause per state, before + after reload; REST `content`/`output`/`embeds`; the expanded FAIL at 760 px; light + dark screenshots; M18.4 (M19.5 rows): per case one row opened (misleading `axes` with `plt.ylim(30000, 45000)` marked, kana `program`, pass `program` unmarked) = hand-stated listing lines + marked line + mark text + `#check-<id>` link, frame grows to the row and fits, the link opens one new tab at that URL (live), the row closes again, live + reload | M16.1 L1-L5 + M18.4 L1-L3: exit code 0 = 3/3 cases with their rows + the narrow re-size; screenshots inspected by hand (`chromiumfish` draws every font family, generic `monospace` included, in one serif face, so its PNGs show the listing proportional; BrowserOS Neo measured the shipped stack monospace) |
| M17 | the Japanese banner prompts in a live `--stub` chat, one attempt per arm over its own CSV: verdict before + after reload, the verdict line, the interpretation's first sentence, the PNG attachment count, the status line's code + language | M17.4 L2 (M19.5 arms): `ja-simple` + `ja-clinic-simple` pass with 1 PNG and a Japanese interpretation (`棒: sales.csv の region 列ごとの revenue 列の合計。`, `折れ線: clinic_ja.csv の 年月 列ごとの 平均待ち時間 列の平均。`); `ja-misleading` + `ja-clinic-misleading` fail with 0 PNGs and a Japanese status line ending `(zero_not_in_limits)`, `(axis_inverted)` |

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
T8's one-count control plants `expected/T8.json`'s `0280.corpora.decimals.plain.host_bit_mismatches`
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
"$(chromiumfish path)" --remote-debugging-port=9333 --user-data-dir="$(mktemp -d)" \
  --disable-features=IsolateSandboxedIframes --window-size=1280,800 about:blank &
uv run --locked python -c 'import json; from webui.paste_in.reasons import REASONS; print(json.dumps(REASONS, ensure_ascii=False))' > /tmp/reasons.json
cd .agent/measurements
FV_WEBUI_EMAIL=operator@localhost FV_WEBUI_PASSWORD=loopback-dev-password \
  node m15u1_status.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 ../../data/sales.csv /tmp/reasons.json \
  ../../.launch-logs/webui.log m15u1
```

Rerun M16 against the same stub stack and CDP browser (the M15 browser flag is harmless here). The
script exits 0 only when every case and the 760 px re-size hold; it writes one PNG per case and
theme into `<out-dir>` for a person to inspect. `FV_CASES=<name,...>` runs a subset of `refused`,
`japanese` and `pass`.

```
PYTHONPATH="$PWD" uv run --locked python .agent/measurements/m16u1_dump.py /tmp/checks.json
cd .agent/measurements
FV_WEBUI_EMAIL=operator@localhost FV_WEBUI_PASSWORD=loopback-dev-password \
  node m16u1_checks.mjs http://127.0.0.1:9333 http://127.0.0.1:8080 ../../data/sales.csv /tmp/checks.json m16u1
```
