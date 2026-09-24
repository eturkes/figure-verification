# Measurement harnesses

Committed scripts re-derive the numeric bands and profiles cited in `.claude/rules/pysrc.md` and
`.agent/archive/contracts/m13u5.md`. The gate does not run them, and `mypy` excludes them: each
Pyodide leg needs Node and package downloads. Generated corpora and JSON results are gitignored.
`S1` and `W1` print to stdout instead of writing a result JSON.

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
`corpus/python/captures/m13-design`.

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

F7 reads the installed frontend's `execute:python` package regexes and iframe prelude at runtime.
It loads only source-detected packages, runs the literal-trigger prelude, then executes the wrapper.
Missing or changed anchors fail loudly. The four wrappers must each emit one PNG line with no stderr;
a literal plotting import must trigger the installed prelude's `SyntaxError`.

For the other Node commands:

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
| W1 | `w1_width.py [run-dir]` | none | host only |
| F7 | `f7_export.py` (called by the Node leg) | `node f7_wrapper.mjs <B> f7-0283.json` | installed Open WebUI bundle, 0.28.3 |
| Versions | none | `node versions.mjs <P> versions-<v>.json` | selected build |

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
| W1 | shipped verifier's verdict over one committed capture run, per category, idiom, and row | M13.6's measured width aim; M13.7's capture-prompt delta |
| F7 | the production `wrapper_code` in the installed bundle: sentinel-simple, a line, a scatter and a program that never calls `show` | M10.1 F7: the four `Ue`-shaped replies each have one PNG line, `stderr: null`, `result: null` and a valid PNG signature; a literal plotting import still triggers `SyntaxError` |

Each result JSON carries environment details and a per-region breakdown when regions apply. A
region's `disagreements` is the count that matters. `max_ulp` applies only where both values are
finite; S7 reports category splits separately.
