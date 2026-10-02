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
F7/O8 read the installed Open WebUI bundle through the repository's common Git directory.
O8 uses `--check-fixtures`: emitted fixture bytes must match, and tracked fixtures stay untouched.

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
For `make_s6_csv.py`, `t3.py`, `t4.py`, `t5.py`, `t7_profile.py`, and `t7_quoted.py`, use
`uv run --locked --with pandas==2.3.1 python .agent/measurements/<script>.py`: pandas is not in
the root development environment. Run a generator before its dependent host or sandbox leg.
`W1` reads committed capture records and accepts an optional run directory; its default is
`corpus/python/captures/m10-design`. Re-run the design-only outcome and intent counts with:

```
uv run --locked python .agent/measurements/w1_width.py corpus/python/captures/m10-design
```

The 24-row denominators exclude sentinels. `design_intent.json` binds each design-simple task's mark,
x column, y column and reduction; six tasks also require a separate city series or city color, which
one `DatasetPlot` cannot express. A row is FAITHFUL only when the verified projected spec equals
those fields and the task requires no unrepresented series.

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
executes the wrapper. Missing or changed anchors fail loudly. The four wrappers must each emit one
tagged observation line before one PNG line with a valid signature; the shaped reply must have
`stderr: null` and `result: null`. A literal plotting import must trigger the installed prelude's
`SyntaxError`.

`o8_observe.mjs` takes `owui`, a result filename, then `wrapper`; it exports the production
`wrapper_code` through `o8_export.py` and overwrites 58 self-contained fixtures. For the other
Node commands:

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
| S1 | `s1_host.py` | none | host only |
| S2 | `make_s2_inputs.py` | `node s2_pyodide.mjs <P> s2-<v>.json` | 0.28.0 and 0.28.1 |
| S3 | `make_s3_grids.py` | `node s3_pyodide.mjs <P> s3-<v>.json` | 0.28.0 and 0.28.1 |
| S6 | `make_s6_csv.py` | `node s6_pyodide.mjs <P> s6-<v>.json` | 0.28.1; 0.28.0 rerun |
| S7 | `make_s7_pow.py`, then `s7_mapping.py` | `node s7_pyodide.mjs <P> s7-<v>.json` | 0.28.0 and 0.28.1 |
| T3 | `t3.py` | none | host only |
| T4 | `t4.py` | none | host only |
| T5 | `t5.py` | none | host only |
| T6 | `make_s6_csv.py` (same S6 corpus) | `node t6_pyodide.mjs <P> t6-<v>.json` | 0.28.1; 0.28.0 rerun |
| T7 | `t7_profile.py`, then `t7_quoted.py` | `node t7_pyodide.mjs <P> t7-<v>.json` | 0.28.1; 0.28.0 rerun |
| W1 | `w1_width.py corpus/python/captures/m10-design` | none | host only |
| F7 | `f7_export.py` (called by the Node leg) | `node f7_wrapper.mjs <B> f7-0283.json` | installed Open WebUI bundle, 0.28.3 |
| O8 | `make_s2_inputs.py`, `make_s7_pow.py`; `o8_export.py` called by Node | `node s2_pyodide.mjs owui s2-0283.json`; `node s7_pyodide.mjs owui s7-0283.json`; `node o8_observe.mjs owui o8-0283.json wrapper` | installed Open WebUI bundle, 0.28.3; 1M unary values/function and 1M pow pairs; 58 production-wrapper figures |
| Versions | none | `node versions.mjs <P> versions-<v>.json` | selected build |
| M15 | none (dump `REASONS` first, below) | `node m15u1_status.mjs <browser-url> <webui-url> ../../data/sales.csv <reasons.json> <webui.log> <out-dir>` | installed Open WebUI 0.10.2, `webui/launch.sh --stub` |
| M16 | `m16u1_dump.py <checks.json>` (texts + the stub's expected PASS reply) | `node m16u1_checks.mjs <browser-url> <webui-url> ../../data/sales.csv <checks.json> <out-dir>` | installed Open WebUI 0.10.2, `webui/launch.sh --stub` |

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
| S1 | host CPython `math` vs host NumPy, 6 unary functions | host leg contributes 0 ulp; S2's band is the WASM gap alone |
| S2 | host NumPy vs Pyodide NumPy, `sin cos tan exp log sqrt` | `binary64-libm-v1`'s 1-ulp band; N7 |
| S3 | `linspace` + `arange` agreement, values and lengths | N6's bit-for-bit grid claim; the int64-vs-int32 dtype note |
| S6 | host pandas vs Pyodide pandas, parsed cells | CSV divergence is stdlib-vs-pandas, not host-vs-wasm |
| S7 | `pow` band; `math.pow` and `**` exception classes against NumPy's value categories; C99 mapping | N8's 1-ulp band and 0 category splits; N3p's 0/1,000,000 vs a blanket rule's 184,343 |
| T3 | whether ANY significant-digit cap makes stdlib `float` agree with default `pd.read_csv` | C10's "no cap repairs it" |
| T4 | stdlib-vs-pandas structural divergences (BOM, ragged rows, post-quote junk) | C6's four refusal witnesses |
| T5 | default NA spellings pandas recognises | C9's 19-spelling literal |
| T6 | whether the RENDERER alters plotted values | C10 clause 6: matplotlib bar's `-0.0` and Pyodide bar's int32 raise |
| T7 | candidate admitted region, plain and quoted, against target Pyodide | C10's 0/4,000,000 |
| W1 | shipped verifier's verdict and task-intent comparison over one design run, per 24-row category, idiom, row, and separate sentinel | M13.6's measured width aim; M10.6's design-only proposer guard |
| F7 | the production `wrapper_code` in the installed bundle: sentinel-simple, a line, a scatter and a program that never calls `show` | M10.1 F7 + M10.2 O1: four `Ue`-shaped replies each have one tagged parseable observation line before one PNG line, `stderr: null`, `result: null` and a valid PNG signature; a literal plotting import still triggers `SyntaxError` |
| O8 | installed bundle libm band and production wrapper artist reports: S2 sin/cos/tan/exp/log/sqrt ≤1/1/1/1/0/0 ulp, S7 pow ≤1 ulp with zero category splits, 58 fixture observations + PNGs (M10.10 added 6 accessor lines), zero stderr | M10.2 O8's interval bound and the recorded artists underlying O3/O5/O7 |
| M15 | the failure status line in a live `--stub` chat: elaborate prompt, a kana prompt, a blocked `pyodide.js`, the simple prompt; DOM before + after reload + REST `statusHistory`/`content`/`output`/`files`; every `REASONS` text set into the live `line-clamp-1` element at 1280×800, sidebar open | M15.1 L1-L5: exit code 0 = 4/4 cases + their log records + 0/132 texts clamped |
| M16 | the "Show checks" embed in a live `--stub` chat: elaborate prompt, a kana prompt, the simple prompt; one frame after the status line + before the verdict, collapsed < 60 px, expanded = its content (no inner scroll), collapsed again, rows + marks + texts + cause per state, before + after reload; REST `content`/`output`/`embeds`; the expanded FAIL at 760 px; light + dark screenshots | M16.1 L1-L5: exit code 0 = 3/3 cases + the narrow re-size; screenshots inspected by hand |

Rerun O8 from the repository root after the host input generators. `o8_observe.mjs` obtains the wrapper from the tracked filter and writes the observed JSON into `tests/fixtures/observe/`; a second run should leave those bytes unchanged.

```
uv run --locked python .agent/measurements/make_s2_inputs.py
uv run --locked python .agent/measurements/make_s7_pow.py
node .agent/measurements/s2_pyodide.mjs owui s2-0283.json
node .agent/measurements/s7_pyodide.mjs owui s7-0283.json
node .agent/measurements/o8_observe.mjs owui o8-0283.json wrapper
```

Each result JSON carries environment details and a per-region breakdown when regions apply. A
region's `disagreements` is the count that matters. `max_ulp` applies only where both values are
finite; S7 reports category splits separately.

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
