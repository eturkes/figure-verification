# M1.4f — oracle transcription recipe   (delete at M1 review)

Pre-derived so the M1.4f session TRANSCRIBES, not re-derives. M1.4f overflowed once: writing oracle.py
live fit one window (≈66%), but oracle + parity test + 3 Hypothesis properties + gate in ONE window did
not → split f→f+g (THIS = f: oracle + parity test; g: determinism properties, separate window).

The two code files below were VALIDATED END-TO-END during the M1.4-re-split codex-review: written to
tests/, then ruff check + ruff format --check + mypy --strict + full pytest ALL GREEN (268 passed, 100%
branch), parity PASSING on all 10 goldens (g08's filter + g05's mean included). They were reverted after
(committing them IS M1.4f). So: TRANSCRIBE BOTH VERBATIM, apply the 3 pyproject edits, run the gate to
CONFIRM. The VERIFICATION POINTS at the end are now post-transcription confirmations, not open risks.

## Scope (M1.4f only)
tests/oracle.py (full, below) + tests/test_oracle_parity.py (full, below) + 3 pyproject edits. The 3
Hypothesis determinism properties → M1.4g (NOT here). duckdb>=1.1 is already a dev dep (committed in the
re-split) → no dependency edit needed.

## Architecture (corrected + validated)
ingest.load_table(csv, manifest) → coerced canon.Table (SHARED trusted ingestion) → a typed DuckDB temp
table t0 seeded by INSERT of the coerced cells → SQL filter / select / group_by / aggregate (a mean's
SUM+COUNT in SQL, its division in PYTHON via eval.mean_at_scale) → ONE closing ORDER BY (§6) → canon.Table.

- INSERT the coerced Decimals; NEVER read_csv-forced-DECIMAL (settled M1.4b codex-review + §3). DuckDB's
  string→DECIMAL CAST on RAW source ROUNDS excess precision the verifier REJECTS (§3 exact-at-scale) and
  rejects in-domain boundaries → re-parsing manufactures FALSE divergences. The goldens are clean so a
  read_csv path would pass GREEN while hiding the violation — that is the trap. The oracle cross-checks the
  TRANSFORM pipeline; ingestion is SHARED (its own M1.4b tests). Coerced cells also SIMPLIFY the oracle (no
  temp file, no read_csv, no manifest projection).
- FILTER materializes via CTAS (CREATE TEMP TABLE vN AS SELECT * ... WHERE pred), NOT CREATE VIEW: DuckDB
  REJECTS a bound parameter inside CREATE VIEW (BinderException) but ACCEPTS it in CTAS + a plain SELECT.
- FILTER literals bind as NATIVE coerced values (Decimal / date / datetime), NOT a DECIMAL(38,scale) CAST:
  eval compares filter literals UNBOUNDED in magnitude (compared, not stored → no §3 cell-bound), so a CAST
  would wrongly reject an over-magnitude or 1E-38@38 literal and round an over-precision one. The literal in
  a GOOD spec is valid (eval — the gate — rejects a bad one before the oracle runs); the oracle just binds it.
- §6 deferral: only sort sets the closure keys; every other op is row-order-insensitive → NO intermediate
  ORDER BY. One closing ORDER BY (active sort keys, then every remaining column ASC, null-greatest) realizes
  the total order → the plotted-table hash is permutation-invariant. An aggregate breaks the SQL chain (mean
  needs Python) → its rows materialize into a typed temp table and the chain continues.
- EXACTNESS holds within DuckDB's DECIMAL(38) domain: SUM/COUNT are exact while the accumulator stays ≤38
  digits, which ingest._coerce_numeric guarantees for every cell + the whole golden corpus. A pathological
  >38-digit aggregate overflows DuckDB LOUDLY (a raised error, never a silent divergence); eval's Fraction
  sum is unbounded, so on the in-domain corpus the two agree and the oracle never silently diverges.

## VERIFIED FACTS (probe-confirmed + review-validated — do NOT re-probe)
- duckdb ships py.typed → NO mypy override needed; mypy --strict checks tests/ clean.
- A bound parameter is REJECTED inside CREATE VIEW ("Unexpected prepared parameter. This type of statement
  can't be prepared!") but ACCEPTED by CREATE TEMP TABLE ... AS SELECT (CTAS) and a plain prepared SELECT →
  the filter step uses CTAS. (The earlier draft's CREATE VIEW + param crashed g08; this is the fix.)
- mean via SQL avg, or SUM/COUNT then divide, routes through DOUBLE → HALF-AWAY ≠ HALF_EVEN (mean(0.00,0.01)
  @2 → SQL 0.01 vs eval 0.00) → SUM+COUNT exact in SQL, the ONE division in Python via mean_at_scale.
- ORDER BY ... ASC NULLS LAST / DESC NULLS FIRST = null-greatest (§6). Binary string collation = code-point
  order (matches eval). GROUP BY over NULL = one group. COUNT(col) = non-null count; SUM/MIN/MAX over an
  all-null group = NULL. All DuckDB defaults; the parity test asserts them.
- executemany inserts a list of tuples carrying Decimal / str / None / date / datetime params into a typed
  temp table (Decimal→DECIMAL(38,scale), datetime.date→DATE, datetime→TIMESTAMP).
- ruff reports S608 on the f-string's PHYSICAL line → # noqa: S608 must sit on THAT line (a noqa on the
  preceding con.execute( line does NOT suppress it); multi-line SQL is hoisted to a single-line assignment
  carrying the same-line noqa. ANN is NOT in the ruff select → # noqa: ANN401 is an unused noqa (RUF100);
  a bare value: Any needs no noqa.

## CONSUMED SURFACE (so the source modules need not be reopened)
- canon: Table{columns: tuple[Column,...], rows: tuple[tuple[Cell,...],...]}; Cell = Decimal | str | None;
  Column = NumericColumn{name, scale} | TemporalColumn{name, granularity ∈ date|datetime} |
  StringColumn{name} (each carries a .kind ClassVar); serialize_table(Table) -> str (quantizes Decimals to
  column scale → only VALUES + schema must match for parity; equal UTF-8 strings ⇒ byte-identical);
  hash_table(Table) -> str.
- ingest: load_table(csv_bytes: bytes, manifest: Manifest) -> canon.Table (coerced, SOURCE order);
  load_manifest(bytes) -> Manifest.
- eval: evaluate(spec, manifest, csv_bytes) -> canon.Table; mean_at_scale(total: Decimal, count: int,
  scale: int) -> Decimal.
- schema: VPlotSpec.transform: tuple[Transform,...]; Select{fields}, Filter{field, cmp, value: int|str},
  GroupBy{keys}, Aggregate{measures} (Measure{field, fn, output} — output is the JSON "as"),
  Sort{by: tuple[SortKey,...]} (SortKey{field, order ∈ ascending|descending}); decode_spec(bytes) -> VPlotSpec.

## tests/oracle.py — transcribe VERBATIM
```python
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""DuckDB recompute oracle — an independent second engine for the M1.4d evaluator.

Dev/test only (duckdb is a dev dep; a ruff TID251 ban keeps it out of src/). It reproduces a
VALIDATED spec's plotted table per VPlot_SEMANTICS.md sections 3-6 + 10 with DuckDB SQL, so
tests/test_oracle_parity can byte-compare it against verifier.eval on the M1.3 goldens — two
independent engines that must agree. Independence is in the COMPUTATION: DuckDB runs
filter / group_by / aggregate / sort itself. Ingestion is SHARED (verifier.ingest.load_table) —
section 3 + the M1.4b codex-review settle that the oracle feeds ALREADY-COERCED Decimals via a typed
INSERT, never DuckDB's string->DECIMAL CAST on raw source text (which silently rounds excess
precision the verifier rejects, manufacturing false divergences). Only mean borrows
eval.mean_at_scale, because section 10 mandates the division round identically in Python (SQL avg /
SUM/COUNT go through DOUBLE, HALF-AWAY — the wrong way). Everything else is derived from the
semantics, not eval.

Scope = recompute a spec eval ACCEPTS. test_oracle_parity runs eval FIRST, so eval's validation gate
(distinct/existing fields, group_by placement, sort-key survival, output collisions) rejects a bad
spec before the oracle runs; the oracle is a faithful RECOMPUTE for valid specs, not a second
validator. Exactness holds inside DuckDB's DECIMAL(38) domain, which bounds every ingest cell
(ingest._coerce_numeric caps magnitude there) and the entire golden corpus; a pathological aggregate
exceeding 38 digits overflows DuckDB LOUDLY (a raised error, never a silent divergence) — eval's
Fraction sum is unbounded there, outside this oracle's representable domain.

Pipeline = the section 6 deferral: only sort sets the closure's primary keys (every other op is
row-order-insensitive), so no op runs an intermediate ORDER BY — the single closing ORDER BY (the
active sort, then every remaining column ascending, nulls greatest) realizes the total order. A
filter materializes via CREATE TEMP TABLE AS SELECT (CREATE VIEW rejects a bound parameter; CTAS
accepts it), an aggregate breaks the SQL chain (mean needs Python) into a typed temp table, and the
pipeline continues on that.
"""

from datetime import date, datetime
from decimal import Decimal
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
    date/datetime (DuckDB stores DATE/TIMESTAMP with no string CAST), numeric Decimal + string +
    None pass through unchanged."""
    if isinstance(column, canon.TemporalColumn) and isinstance(cell, str):
        if column.granularity == "date":
            return date.fromisoformat(cell)
        return datetime.fromisoformat(cell)
    return cell


def _to_cell(column: canon.Column, value: Any) -> canon.Cell:
    """A fetched DuckDB value as a canon.Cell: temporal DATE/TIMESTAMP -> canonical ISO text,
    numeric -> Decimal, string -> str, NULL -> None. The explicit per-kind narrowing keeps the
    return concrete (no Any leaks back into the value model)."""
    if value is None:
        return None
    if isinstance(column, canon.TemporalColumn):
        return str(value.isoformat())
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        return value
    msg = f"oracle: column {column.name!r} got an unexpected DuckDB value {value!r}"
    raise TypeError(msg)


def _filter_clause(op: Filter, column: canon.Column) -> tuple[str, list[object]]:
    """A WHERE predicate + its bound parameter, coercing the spec literal to the column domain
    (section 3) to match eval's filter coercion: numeric int|str -> the parsed Decimal (compared
    numerically, no DECIMAL(38,scale) CAST that would reject an over-magnitude or 1E-38 literal eval
    accepts), temporal -> a native date/datetime (canonical-ISO compares chronologically = eval's
    lexical order), string -> the literal. eval (run first by the parity test) rejects an
    over-precision or noncanonical literal before the oracle ever sees it."""
    pred = f"{_q(op.field)} {_CMP_SQL[op.cmp]} ?"
    if isinstance(column, canon.NumericColumn):
        return pred, [Decimal(op.value)]
    if isinstance(column, canon.TemporalColumn):
        text = op.value if isinstance(op.value, str) else str(op.value)
        native: date | datetime = (
            date.fromisoformat(text)
            if column.granularity == "date"
            else datetime.fromisoformat(text)
        )
        return pred, [native]
    return pred, [op.value]


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


def _aggregate(  # noqa: PLR0913 — 6 irreducible args: con, cur, schema, keys, op, step
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
            agg = f"{_SQL_AGG[measure.fn]}({_q(measure.field)}) AS {_q(out_col.name)}"
            select_exprs.append(agg)
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
                if total is None:
                    row.append(None)
                else:
                    assert isinstance(
                        out_col, canon.NumericColumn
                    )  # mean -> numeric (_measure_column)
                    row.append(mean_at_scale(total, cells[aliases[1]], out_col.scale))
            else:
                row.append(cells[out_col.name])
        out_rows.append(tuple(row))

    table = f"agg{step}"
    col_defs = ", ".join(f"{_q(c.name)} {_duckdb_type(c)}" for c in out_schema)
    con.execute(f"CREATE TEMP TABLE {table} ({col_defs})")
    if out_rows:
        placeholders = ", ".join("?" for _ in out_schema)
        con.executemany(f"INSERT INTO {table} VALUES ({placeholders})", out_rows)  # noqa: S608
    return table, out_schema


def _run(
    con: duckdb.DuckDBPyConnection, spec: VPlotSpec, manifest: Manifest, csv_bytes: bytes
) -> canon.Table:
    source = load_table(csv_bytes, manifest)  # SHARED trusted ingestion -> coerced canon.Table
    schema = list(source.columns)
    # Seed DuckDB from the COERCED cells (section 3 + M1.4b codex-review: never read_csv's
    # string->DECIMAL CAST on raw source — it rounds excess precision the verifier rejects).
    col_defs = ", ".join(f"{_q(c.name)} {_duckdb_type(c)}" for c in schema)
    con.execute(f"CREATE TEMP TABLE t0 ({col_defs})")
    if source.rows:
        placeholders = ", ".join("?" for _ in schema)
        seed = [
            tuple(_to_duckdb(col, cell) for col, cell in zip(schema, row, strict=True))
            for row in source.rows
        ]
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
            projection = ", ".join(_q(f) for f in op.fields)
            con.execute(f"CREATE TEMP VIEW v{step} AS SELECT {projection} FROM {cur}")  # noqa: S608
            cur = f"v{step}"
        elif isinstance(op, Filter):
            step += 1
            pred, params = _filter_clause(op, _find(schema, op.field))
            sql = f"CREATE TEMP TABLE v{step} AS SELECT * FROM {cur} WHERE {pred}"  # noqa: S608
            con.execute(sql, params)
            cur = f"v{step}"
        elif isinstance(op, Sort):
            active_keys = [(key.field, key.order) for key in op.by]
    if pending_keys is not None:
        msg = "oracle: trailing group_by without aggregate"
        raise ValueError(msg)

    select_cols = ", ".join(_q(c.name) for c in schema)
    query = f"SELECT {select_cols} FROM {cur} ORDER BY {_closure_order(schema, active_keys)}"  # noqa: S608
    rows = con.execute(query).fetchall()
    out = tuple(tuple(_to_cell(schema[i], v) for i, v in enumerate(record)) for record in rows)
    return canon.Table(columns=tuple(schema), rows=out)


def recompute(spec: VPlotSpec, manifest: Manifest, csv_bytes: bytes) -> canon.Table:
    """Independently recompute the plotted table for a validated spec (the DuckDB engine). Mirrors
    verifier.eval.evaluate's signature so test_oracle_parity can byte-compare both
    serializations."""
    con = duckdb.connect(config={"threads": 1})
    try:
        return _run(con, spec, manifest, csv_bytes)
    finally:
        con.close()
```

## tests/test_oracle_parity.py — transcribe VERBATIM
```python
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Dual-engine parity: verifier.eval's hand-rolled Decimal pipeline vs the DuckDB oracle must
produce the byte-identical canonical plotted table on every M1.3 good spec. This is the real
correctness oracle behind the M1.4d-e self-locked goldens — two independent engines agreeing.

eval runs FIRST (it is the trusted reference + the validation gate): a spec it rejects never
reaches the oracle, which recomputes only eval-validated specs (oracle module docstring)."""

import pathlib

import pytest

from oracle import recompute
from verifier import canon
from verifier.eval import evaluate
from verifier.ingest import load_manifest
from verifier.schema import decode_spec

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EXAMPLES = ROOT / "examples"

# (good-spec filename, dataset stem) — the 10 M1.3 goldens.
_GOLDENS = [
    ("g01_total_revenue_by_month.json", "sales"),
    ("g02_revenue_by_region.json", "sales"),
    ("g03_order_count_by_month.json", "sales"),
    ("g04_revenue_vs_orders.json", "sales"),
    ("g05_avg_revenue_by_region.json", "sales"),
    ("g06_max_temp_by_city.json", "weather"),
    ("g07_temp_over_time_by_city.json", "weather"),
    ("g08_na_revenue_by_month.json", "sales"),
    ("g09_min_revenue_by_month.json", "sales"),
    ("g10_temp_vs_precip.json", "weather"),
]


@pytest.mark.parametrize(("filename", "stem"), _GOLDENS)
def test_oracle_matches_eval(filename: str, stem: str) -> None:
    spec = decode_spec((EXAMPLES / "good_specs" / filename).read_bytes())
    manifest = load_manifest((DATA / "schemas" / f"{stem}.json").read_bytes())
    csv_bytes = (DATA / f"{stem}.csv").read_bytes()

    expected = evaluate(spec, manifest, csv_bytes)
    actual = recompute(spec, manifest, csv_bytes)

    assert canon.serialize_table(actual) == canon.serialize_table(expected)
    assert canon.hash_table(actual) == canon.hash_table(expected)
```

## pyproject.toml — 3 exact edits
1. [tool.ruff.lint.flake8-tidy-imports.banned-api], after the jsonschema line, add:
   `"duckdb".msg = "test-only (dual-engine oracle); do not import from src/"`
2. [tool.mypy]: `mypy_path = "src"` → `mypy_path = ["src", "tests"]`   (so `import oracle` resolves in mypy)
3. [tool.pytest.ini_options], add `pythonpath = ["tests"]`   (so `import oracle` resolves in pytest)

## VERIFICATION POINTS (all GREEN in the review — re-confirm post-transcription)
- import oracle resolves under BOTH pytest (pythonpath) and mypy (mypy_path).
- ingest.load_table arg order = (csv_bytes, manifest).
- canon exports NumericColumn / TemporalColumn / StringColumn / Cell / Table / serialize_table / hash_table.
- every INSERT param is native (Decimal/str/None/date/datetime); temporal converted via _to_duckdb.
- mypy --strict over the duckdb surface (DuckDBPyConnection, .execute(...).fetchall(), .executemany) is clean.
- every f-string-SQL execute carries a same-line # noqa: S608 (identifiers are schema-validated field
  names; the only bound values are ? params).
- tests/oracle.py is OUT of coverage (source = ["verifier"]) → its defensive raises need not be exercised;
  the parity test covers the common paths.
- gate: `export UV_PROJECT_ENVIRONMENT=.venv UV_LINK_MODE=copy` then `uv run --locked` { ruff check · ruff
  format --check · mypy · pytest }.
