# Measurement harnesses

Frozen record of how each published number in `.claude/rules/pysrc.md` and
`.agent/contracts/m13u5.md` was obtained. These are evidence, not project tooling: nothing imports
them, the gate does not run them, and they sit outside `mypy`'s `files` list on purpose. What makes
a number here durable is that the script reproducing it is in committed state.

Each script writes its corpus and its result JSON beside itself; both are gitignored, and the
corpora run to hundreds of megabytes. Rerun to regenerate.

## Running

Host legs need numpy (already a dev dep, pinned exactly at 2.2.5):

```
uv run --locked python .agent/measurements/make_s7_pow.py
```

Sandbox legs need Node plus the two pinned Pyodide builds. `package.json` maps `pyodide` → 0.28.0
and `pyodide0281` → 0.28.1; every `.mjs` takes the package name as its first argument, so one script
measures both builds:

```
cd .agent/measurements && pnpm install
node s7_pyodide.mjs pyodide      s7-0280.json
node s7_pyodide.mjs pyodide0281  s7-0281.json
```

Generate the corpus before its sandbox leg — the `.mjs` reads what the `make_*.py` wrote.

## What each one backs

| id | files | measures | backs |
|---|---|---|---|
| S1 | `s1_host.py` | host CPython `math` vs host numpy, 6 unary functions | that the host leg contributes 0 ulp, so S2's band is the WASM gap alone |
| S2 | `make_s2_inputs.py` · `s2_pyodide.mjs` | host numpy vs Pyodide numpy, `sin cos tan exp log sqrt` | `binary64-libm-v1`'s 1-ulp band; N7 |
| S3 | `make_s3_grids.py` · `s3_pyodide.mjs` | `linspace` + `arange` agreement, values and lengths | N6's bit-for-bit grid claim; the int64-vs-int32 dtype note |
| S6 | `make_s6_csv.py` · `s6_pyodide.mjs` | host pandas vs Pyodide pandas, parsed cells | that the CSV divergence is stdlib-vs-pandas, not host-vs-wasm |
| S7 | `make_s7_pow.py` · `s7_mapping.py` · `s7_pyodide.mjs` | `pow` band; `math.pow` and `**` exception classes against numpy's value categories; the C99 mapping | § The N8 ruling — the 1-ulp band, the 0 category splits, N3p's mapping at 0/1,000,000 against the blanket rule's 184,343 |
| T3 | `t3.py` | whether ANY significant-digit cap makes stdlib `float` agree with default `pd.read_csv` | § The C10 ruling's "no cap repairs it" |
| T4 | `t4.py` | stdlib-vs-pandas structural divergences (BOM, ragged rows, post-quote junk) | C6's four refusal witnesses |
| T5 | `t5.py` | the default NA spellings pandas recognises | C9's 19-spelling literal |
| T6 | `t6_pyodide.mjs` | whether the RENDERER alters plotted values | C10 clause 6 — matplotlib bar's `-0.0`, Pyodide bar's int32 raise |
| T7 | `t7_profile.py` · `t7_quoted.py` · `t7_pyodide.mjs` | the candidate admitted region, plain and quoted, against target Pyodide | § The C10 ruling's 0/4,000,000 |

`versions.mjs` prints the interpreter, platform, Pyodide, numpy and pandas versions of a build —
run it first when a result needs its environment named.

## Reading a result

Every result JSON carries its own environment block and a per-region breakdown. A region's
`disagreements` is the count that matters; `max_ulp` is only meaningful where both sides are finite,
so S7 reports `category_splits` separately — a `finite`/`±inf`/`nan` split is a different and worse
finding than a last-bit one.
