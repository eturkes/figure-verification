# M1.4f oracle — transcription recipe   (delete at M1 review)

Pre-derived so the implementing session TRANSCRIBES, not re-derives. M1.4f overflowed once: writing
`oracle.py` live fit a window (≈66%), but oracle + parity test + 3 Hypothesis properties + gate in
ONE window did not → split f→f+g (this = f: oracle + parity; g: determinism properties). This doc
removes the oracle re-derivation entirely. The code below is a CORRECTED reference (the earlier live
draft used `read_csv`-forced-DECIMAL = the banned source CAST; see "Architecture"). It has NOT been
gate-run → transcribe ~verbatim, then RUN THE GATE and fix the VERIFICATION POINTS at the end.

## Scope (M1.4f only)
`tests/oracle.py` (below, full) + `tests/test_oracle_parity.py` (recipe below) + `pyproject` edits
(duckdb TID251 ban + import wiring). Properties (`tests/test_eval_properties.py`) → M1.4g, not here.

## Architecture (corrected)
`ingest.load_table(csv, manifest)` → coerced `canon.Table` (SHARED trusted ingestion) → typed DuckDB
temp table `t0` seeded by INSERT of the coerced cells → SQL filter / select / group_by / aggregate
(a mean's `SUM`+`COUNT` exact in SQL, the division in PYTHON via `eval.mean_at_scale`) → ONE closing
`ORDER BY` (§6) → `canon.Table`.
- WHY INSERT coerced Decimals, NEVER `read_csv`-forced-DECIMAL (settled M1.4b codex-review + §3):
  DuckDB's string→DECIMAL CAST on RAW source ROUNDS excess precision (the verifier REJECTS it, §3
  exact-at-scale) and rejects in-domain boundaries (`1E-38`@38) → re-parsing manufactures FALSE
  divergences. Goldens are clean so `read_csv` would pass green, hiding the violation — that is the
  trap. The oracle cross-checks the TRANSFORM PIPELINE; ingestion is SHARED (it has its own M1.4b
  tests). Feeding coerced cells also SIMPLIFIES the oracle (no temp file / `read_csv` / manifest
  projection).
- §6 deferral: only `sort` sets the closure keys; every other op is row-order-insensitive → NO
  intermediate `ORDER BY`. One closing `ORDER BY` (active sort keys, then remaining columns ASC
  null-greatest) realizes the total order. An aggregate breaks the SQL chain (mean needs Python) →
  materialize its rows into a typed temp table and continue.

## VERIFIED FACTS (probe-confirmed — do NOT re-probe)
- `duckdb` ships `py.typed` → NO `[[tool.mypy.overrides]]` needed (mypy --strict checks `tests/`; clean).
- `read_csv` relations are LAZY → dangle after the temp file is deleted. (Moot now: we INSERT coerced
  cells, no temp file.)
- mean via SQL `avg` or `SUM/COUNT` divide → through DOUBLE → HALF-AWAY ≠ HALF_EVEN (`mean(0.00,0.01)`@2
  → SQL `0.01` vs eval `0.00`). So SUM+COUNT exact in SQL, ONE division in Python (`mean_at_scale`).
- `NULLS LAST` (asc) / `NULLS FIRST` (desc) = null greatest (§6). Binary collation = code-point order
  (matches eval). `GROUP BY` NULL = one group. `COUNT(col)` = non-null; `SUM`/`MIN`/`MAX` over all-null
  = NULL. All DuckDB defaults; assert by parity.
- `executemany` accepts a list of tuples with `Decimal` / `str` / `None` / `date` / `datetime` params
  into a typed temp table (probe2: `Decimal` into `DECIMAL(38,0)`).

## CONSUMED SURFACE (so you needn't read the source modules)
- `canon`: `Table(columns: tuple[Column,...], rows: tuple[tuple[Cell,...],...])`; `Cell = Decimal|str|None`;
  `Column` = `NumericColumn{name,scale}` | `TemporalColumn{name,granularity∈date|datetime}` |
  `StringColumn{name}` (`.kind` ClassVar); `serialize_table(Table) -> bytes` (quantizes Decimals to
  column scale — so only VALUES + schema must match for parity); `hash_table(Table) -> str`;
  `hash_dataset(csv_bytes) -> str` (raw bytes, used in M1.4g).
- `ingest`: `load_table(csv_bytes: bytes, manifest: Manifest) -> canon.Table` (coerced, SOURCE order);
  `Manifest` (frozen struct, `.columns`); `load_manifest(bytes) -> Manifest`.
- `eval`: `evaluate(spec, manifest, csv_bytes) -> canon.Table`; `mean_at_scale(total: Decimal, count: int,
  scale: int) -> Decimal`.
- `schema`: `VPlotSpec.transform: tuple[Transform,...]`; `Select{fields: tuple[str,...]}`,
  `Filter{field, cmp, value: int|str}`, `GroupBy{keys: tuple[str,...]}`,
  `Aggregate{measures: tuple[Measure,...]}` w/ `Measure{field, fn, output}` (`output` is the JSON `as`),
  `Sort{by: tuple[SortKey,...]}` w/ `SortKey{field, order∈ascending|descending}`; `decode_spec(bytes)`.

## tests/oracle.py   (transcribe, then gate)
```python
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""DuckDB recompute oracle — an independent second engine for the M1.4d evaluator.

Dev/test only (duckdb is a dev dep; a ruff TID251 ban keeps it out of src/). It reproduces a
validated spec's plotted table per VPlot_SEMANTICS.md sections 3-6 + 10 with DuckDB SQL, so
tests/test_oracle_parity can byte-compare it against verifier.eval on the M1.3 goldens — two
independent engines that must agree. Independence is in the COMPUTATION: DuckDB runs
filter / group_by / aggregate / sort itself. Ingestion is SHARED (verifier.ingest.load_table) —
section 3 + the M1.4b codex-review settle that the oracle feeds ALREADY-COERCED Decimals via a typed
INSERT, never DuckDB's string->DECIMAL CAST on raw source text (which silently rounds excess
precision the verifier rejects, manufacturing false divergences). Only mean borrows eval.mean_at_scale,
because section 10 mandates the division round identically in Python (SQL avg / SUM/COUNT go through
DOUBLE, HALF-AWAY — the wrong way). Everything else is derived from the semantics, not eval.

Pipeline = the section 6 deferral: only sort sets the closure's primary keys (every other op is
row-order-insensitive), so no op runs an intermediate ORDER BY — the single closing ORDER BY (the
active sort, then every remaining column ascending, nulls greatest) realizes the total order. An
aggregate breaks the SQL chain (mean needs Python), so its rows are materialized back into a typed
temp table and the pipeline continues on that.
"""

from datetime import date, datetime
from typing import Any

import duckdb

from verifier import canon
from verifier.eval import mean_at_scale
from verifier.ingest import Manifest, load_table
from verifier.schema import Aggregate, Filter, GroupBy, Select, Sort, VPlotSpec

# CmpOp (VPlot_SEMANTICS section 4) -> SQL operator. A null cell makes `cell op X` UNKNOWN, so
# DuckDB's WHERE drops it for every operator (ne included) — the three-valued-logic drop, matching
# eval and section 4.
_CMP_SQL = {"eq": "=", "ne": "<>", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}
_SQL_AGG = {"count": "COUNT", "sum": "SUM", "min": "MIN", "max": "MAX"}


def _q(name: str) -> str:
    """Quote an identifier. Field names match the schema FieldName pattern
    (`[A-Za-z_][A-Za-z0-9_]*`, no quote/separator), so a double-quote wrap is injection-free."""
    return f'"{name}"'


def _duckdb_type(column: canon.Column) -> str:
    """The DuckDB column type for a canon column (section 10): numeric -> DECIMAL(38,scale),
    temporal -> DATE | TIMESTAMP, string -> VARCHAR."""
    if isinstance(column, canon.NumericColumn):
        return f"DECIMAL(38,{column.scale})"
    if isinstance(column, canon.TemporalColumn):
        return "DATE" if column.granularity == "date" else "TIMESTAMP"
    return "VARCHAR"


def _measure_column(src: canon.Column, fn: str, output: str) -> canon.Column:
    """The output column of a measure (VPlot_SEMANTICS sections 3-4), derived independently of
    eval._measure_output_column: count -> scale-0 numeric for any input; sum/mean -> numeric source
    at its scale; min/max -> the source kind preserved."""
    if fn == "count":
        return canon.NumericColumn(name=output, scale=0)
    if fn in ("sum", "mean"):
        if not isinstance(src, canon.NumericColumn):
            msg = f"oracle: {fn!r} needs a numeric column, got {src.name!r}"
            raise TypeError(msg)
        return canon.NumericColumn(name=output, scale=src.scale)
    if isinstance(src, canon.NumericColumn):
        return canon.NumericColumn(name=output, scale=src.scale)
    if isinstance(src, canon.TemporalColumn):
        return canon.TemporalColumn(name=output, granularity=src.granularity)
    return canon.StringColumn(name=output)


def _find(schema: list[canon.Column], name: str) -> canon.Column:
    """The current-schema column named `name` (the pipeline keeps fields unique)."""
    for column in schema:
        if column.name == name:
            return column
    msg = f"oracle: field {name!r} absent from the current schema"
    raise KeyError(msg)


def _to_duckdb(column: canon.Column, cell: canon.Cell) -> object:
    """A coerced canon.Cell -> a DuckDB-insertable value: temporal canonical-ISO text -> a native
    date/datetime (DuckDB stores DATE/TIMESTAMP with no string CAST), numeric Decimal + string + None
    pass through unchanged."""
    if isinstance(column, canon.TemporalColumn) and isinstance(cell, str):
        return date.fromisoformat(cell) if column.granularity == "date" else datetime.fromisoformat(cell)
    return cell


def _to_cell(column: canon.Column, value: Any) -> canon.Cell:  # noqa: ANN401 — DuckDB row value
    """A fetched DuckDB value as a canon.Cell: temporal DATE/TIMESTAMP -> canonical ISO text,
    numeric -> Decimal, string -> str, NULL -> None."""
    if value is None:
        return None
    if isinstance(column, canon.TemporalColumn):
        return str(value.isoformat())
    return value  # Decimal | str, already native


def _filter_clause(op: Filter, column: canon.Column) -> tuple[str, list[object]]:
    """A WHERE predicate + its bound parameter, coercing the spec literal to the column domain
    (section 3) via an explicit CAST so DuckDB, not eval, does the coercion. A good spec's literal is
    valid-at-scale (where CAST agrees with eval's coercion); eval rejects an invalid one before the
    oracle ever runs."""
    pred = f"{_q(op.field)} {_CMP_SQL[op.cmp]}"
    if isinstance(column, canon.NumericColumn):
        return f"{pred} CAST(? AS DECIMAL(38,{column.scale}))", [str(op.value)]
    if isinstance(column, canon.TemporalColumn):
        sql_type = "DATE" if column.granularity == "date" else "TIMESTAMP"
        return f"{pred} CAST(? AS {sql_type})", [op.value]
    return f"{pred} ?", [op.value]


def _closure_order(schema: list[canon.Column], active_keys: list[tuple[str, str]]) -> str:
    """The section 6 ORDER BY: the active sort keys (their directions, null greatest), then every
    remaining column ascending null-greatest. Null greatest = ASC NULLS LAST / DESC NULLS FIRST."""
    used = {field for field, _ in active_keys}
    parts = [
        f"{_q(field)} {'DESC NULLS FIRST' if order == 'descending' else 'ASC NULLS LAST'}"
        for field, order in active_keys
    ]
    parts += [f"{_q(c.name)} ASC NULLS LAST" for c in schema if c.name not in used]
    return ", ".join(parts)


def _aggregate(
    con: duckdb.DuckDBPyConnection,
    cur: str,
    schema: list[canon.Column],
    keys: list[str],
    op: Aggregate,
    step: int,
) -> tuple[str, list[canon.Column]]:
    """Collapse `cur` to one row per group (or one row whole-table when keys is empty), then
    materialize the result — mean resolved in Python — into a typed temp table the pipeline
    continues on. SQL emits exact SUM + COUNT for a mean; eval.mean_at_scale does the division."""
    select_names: list[str] = list(keys)
    select_exprs: list[str] = [_q(k) for k in keys]
    # plan[i] = (output column, fn, (sum_alias, count_alias) | None)
    plans: list[tuple[canon.Column, str, tuple[str, str] | None]] = []
    for i, measure in enumerate(op.measures):
        out_col = _measure_column(_find(schema, measure.field), measure.fn, measure.output)
        if measure.fn == "mean":
            sum_a, cnt_a = f"__sum_{step}_{i}", f"__cnt_{step}_{i}"
            select_exprs += [
                f"SUM({_q(measure.field)}) AS {_q(sum_a)}",
                f"COUNT({_q(measure.field)}) AS {_q(cnt_a)}",
            ]
            select_names += [sum_a, cnt_a]
            plans.append((out_col, "mean", (sum_a, cnt_a)))
        else:
            select_exprs.append(f"{_SQL_AGG[measure.fn]}({_q(measure.field)}) AS {_q(out_col.name)}")
            select_names.append(out_col.name)
            plans.append((out_col, measure.fn, None))

    sql = f"SELECT {', '.join(select_exprs)} FROM {cur}"  # noqa: S608 — identifiers only, validated
    if keys:
        sql += f" GROUP BY {', '.join(_q(k) for k in keys)}"
    fetched = con.execute(sql).fetchall()

    out_schema = [_find(schema, k) for k in keys] + [plan[0] for plan in plans]
    out_rows: list[tuple[object, ...]] = []
    for record in fetched:
        cells = dict(zip(select_names, record, strict=True))
        row: list[object] = [cells[k] for k in keys]
        for out_col, fn, aliases in plans:
            if fn == "mean" and aliases is not None:
                total = cells[aliases[0]]
                row.append(None if total is None else mean_at_scale(total, cells[aliases[1]], out_col.scale))
            else:
                row.append(cells[out_col.name])
        out_rows.append(tuple(row))

    table = f"agg{step}"
    col_defs = ", ".join(f"{_q(c.name)} {_duckdb_type(c)}" for c in out_schema)
    con.execute(f"CREATE TEMP TABLE {table} ({col_defs})")  # noqa: S608 — identifiers + fixed types
    if out_rows:
        placeholders = ", ".join("?" for _ in out_schema)
        con.executemany(f"INSERT INTO {table} VALUES ({placeholders})", out_rows)  # noqa: S608
    return table, out_schema


def _run(con: duckdb.DuckDBPyConnection, spec: VPlotSpec, manifest: Manifest, csv_bytes: bytes) -> canon.Table:
    source = load_table(csv_bytes, manifest)  # SHARED trusted ingestion -> coerced canon.Table
    schema = list(source.columns)
    # Seed DuckDB from the COERCED cells (section 3 + M1.4b codex-review: never read_csv's
    # string->DECIMAL CAST on raw source — it rounds excess precision the verifier rejects).
    col_defs = ", ".join(f"{_q(c.name)} {_duckdb_type(c)}" for c in schema)
    con.execute(f"CREATE TEMP TABLE t0 ({col_defs})")  # noqa: S608 — identifiers + fixed types
    if source.rows:
        placeholders = ", ".join("?" for _ in schema)
        seed = [tuple(_to_duckdb(col, cell) for col, cell in zip(schema, row, strict=True)) for row in source.rows]
        con.executemany(f"INSERT INTO t0 VALUES ({placeholders})", seed)  # noqa: S608 — identifiers

    cur = "t0"
    step = 0
    pending_keys: list[str] | None = None
    active_keys: list[tuple[str, str]] = []
    for op in spec.transform:
        if isinstance(op, GroupBy):
            if pending_keys is not None:
                msg = "oracle: consecutive group_by"
                raise ValueError(msg)
            pending_keys = list(op.keys)
            continue
        if isinstance(op, Aggregate):
            step += 1
            cur, schema = _aggregate(con, cur, schema, pending_keys or [], op, step)
            pending_keys, active_keys = None, []
            continue
        if pending_keys is not None:
            msg = "oracle: group_by not immediately followed by aggregate"
            raise ValueError(msg)
        if isinstance(op, Select):
            step += 1
            schema = [_find(schema, f) for f in op.fields]
            con.execute(  # noqa: S608 — identifiers only, validated
                f"CREATE TEMP VIEW v{step} AS SELECT {', '.join(_q(f) for f in op.fields)} FROM {cur}"
            )
            cur = f"v{step}"
        elif isinstance(op, Filter):
            step += 1
            pred, params = _filter_clause(op, _find(schema, op.field))
            con.execute(f"CREATE TEMP VIEW v{step} AS SELECT * FROM {cur} WHERE {pred}", params)  # noqa: S608
            cur = f"v{step}"
        elif isinstance(op, Sort):
            active_keys = [(key.field, key.order) for key in op.by]
    if pending_keys is not None:
        msg = "oracle: trailing group_by without aggregate"
        raise ValueError(msg)

    select_cols = ", ".join(_q(c.name) for c in schema)
    rows = con.execute(  # noqa: S608 — identifiers only, validated
        f"SELECT {select_cols} FROM {cur} ORDER BY {_closure_order(schema, active_keys)}"
    ).fetchall()
    out = tuple(tuple(_to_cell(schema[i], v) for i, v in enumerate(record)) for record in rows)
    return canon.Table(columns=tuple(schema), rows=out)


def recompute(spec: VPlotSpec, manifest: Manifest, csv_bytes: bytes) -> canon.Table:
    """Independently recompute the plotted table for a validated spec (the DuckDB engine). Mirrors
    verifier.eval.evaluate's signature so test_oracle_parity can byte-compare both serializations."""
    con = duckdb.connect(config={"threads": 1})
    try:
        return _run(con, spec, manifest, csv_bytes)
    finally:
        con.close()
```

## tests/test_oracle_parity.py   (recipe — parametrize the 10 good-spec goldens)
- Header SPDX + a docstring (dual-engine parity; eval's hand-rolled pipeline vs DuckDB must produce
  the byte-identical canonical plotted table on every M1.3 good spec — the real correctness oracle
  behind the M1.4d-e self-locked goldens).
- `from oracle import recompute` (resolves via the `pythonpath`/`mypy_path` edits below).
- Path constants mirror `test_eval.py`: `ROOT = pathlib.Path(__file__).resolve().parent.parent`,
  `DATA = ROOT/"data"`, `EXAMPLES = ROOT/"examples"`.
- `_GOLDENS = [(filename, stem), ...]` (10; verify the filenames via `ls examples/good_specs/`):
  `g01_total_revenue_by_month`→sales, `g02_revenue_by_region`→sales, `g03_order_count_by_month`→sales,
  `g04_revenue_vs_orders`→sales, `g05_avg_revenue_by_region`→sales, `g06_max_temp_by_city`→weather,
  `g07_temp_over_time_by_city`→weather, `g08_na_revenue_by_month`→sales, `g09_min_revenue_by_month`→sales,
  `g10_temp_vs_precip`→weather (each `+ ".json"`).
- One `@pytest.mark.parametrize(("filename","stem"), _GOLDENS)` test: load like `test_eval._evaluate_example`
  (`decode_spec((EXAMPLES/"good_specs"/filename).read_bytes())`, `load_manifest((DATA/"schemas"/f"{stem}.json").read_bytes())`,
  `(DATA/f"{stem}.csv").read_bytes()`), then
  `assert canon.serialize_table(recompute(...)) == canon.serialize_table(evaluate(...))` AND
  `assert canon.hash_table(recompute(...)) == canon.hash_table(evaluate(...))`.

## pyproject edits (exact)
1. `[tool.ruff.lint.flake8-tidy-imports.banned-api]` — add a line beside `jsonschema`:
   `"duckdb".msg = "test-only (dual-engine oracle); do not import from src/"`
   (`per-file-ignores` `"tests/**" = [..., "TID251"]` ALREADY exempts tests/ → no other ruff edit.)
2. `[tool.mypy]` — `mypy_path = "src"` → `mypy_path = ["src", "tests"]` (so `import oracle` resolves;
   mypy already type-checks `tests/`). NO duckdb override (py.typed present).
3. `[tool.pytest.ini_options]` — add `pythonpath = ["tests"]` (with `--import-mode=importlib`, this puts
   `tests/` on `sys.path` so `import oracle` works).
- NO re-lock (duckdb is already in the M1.1 dev group; ruff/mypy/pytest config edits change no deps).
- `tests/oracle.py` is OUT of coverage (`source = ["verifier"]`) → its branches are NOT 100%-gated; the
  parity test exercising the common paths suffices. Defensive raises (`_find` KeyError, group_by guards)
  may stay uncovered.

## VERIFICATION POINTS (never gate-run — confirm + fix while running the gate)
- `import oracle` resolves under BOTH pytest (`pythonpath`) and mypy (`mypy_path`). If mypy still can't
  find it, the fallback is `files`/explicit-module config — but `mypy_path = ["src","tests"]` should suffice.
- `ingest.load_table` arg order is `(csv_bytes, manifest)` and it is exported from `verifier.ingest`
  (confirm; `evaluate` calls it internally).
- `canon` exports `NumericColumn` / `TemporalColumn` / `StringColumn` / `Column` / `Cell` / `Table` /
  `serialize_table` / `hash_table` (used unqualified-as-`canon.X`).
- `executemany` with a string-param into a typed col is avoided (we convert temporal via `_to_duckdb`),
  so all INSERT params are native (`Decimal`/`str`/`None`/`date`/`datetime`). Confirm DuckDB accepts a
  `datetime.date` into a `DATE` column and a `Decimal` at scale into `DECIMAL(38,scale)`.
- A temporal `TIMESTAMP` round-trip (INSERT datetime → fetch → `.isoformat()`) yields the canonical
  6-digit-or-no fraction eval emits. (Goldens use only DATE; this matters only for generality.)
- mypy --strict on the duckdb API surface (`DuckDBPyConnection`, `.execute().fetchall()`,
  `.executemany`) is clean; add precise per-call annotations if a return is `Any`.
- ruff S608 noqas sit on every f-string-SQL execute (identifiers are schema-validated FieldNames; the
  only bound values are `?` params). Confirm no S608 site is unmarked.
