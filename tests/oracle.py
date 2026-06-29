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
    continues on. SQL emits exact SUM + COUNT for a mean; eval.mean_at_scale does the division.
    Output columns are read back BY POSITION, never by name: a measure's SUM/COUNT is unaliased,
    so a user field/output named like an internal alias cannot collide in the result mapping."""
    select_exprs: list[str] = [_q(k) for k in keys]
    # plan entry = (output column, fn, sum/agg record index, count record index | None)
    plans: list[tuple[canon.Column, str, int, int | None]] = []
    col = len(keys)  # the record index just past the group-key columns
    for measure in op.measures:
        out_col = _measure_column(_find(schema, measure.field), measure.fn, measure.output)
        if measure.fn == "mean":
            select_exprs += [f"SUM({_q(measure.field)})", f"COUNT({_q(measure.field)})"]
            plans.append((out_col, "mean", col, col + 1))
            col += 2
        else:
            select_exprs.append(f"{_SQL_AGG[measure.fn]}({_q(measure.field)})")
            plans.append((out_col, measure.fn, col, None))
            col += 1

    sql = f"SELECT {', '.join(select_exprs)} FROM {cur}"  # noqa: S608 — identifiers only, validated
    if keys:
        sql += f" GROUP BY {', '.join(_q(k) for k in keys)}"
    fetched = con.execute(sql).fetchall()

    out_schema = [_find(schema, k) for k in keys] + [plan[0] for plan in plans]
    out_rows: list[tuple[object, ...]] = []
    for record in fetched:
        row: list[object] = list(record[: len(keys)])
        for out_col, fn, idx, cnt_idx in plans:
            if fn == "mean" and cnt_idx is not None:
                total = record[idx]
                if total is None:
                    row.append(None)
                else:
                    assert isinstance(
                        out_col, canon.NumericColumn
                    )  # mean -> numeric (_measure_column)
                    row.append(mean_at_scale(total, record[cnt_idx], out_col.scale))
            else:
                row.append(record[idx])
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
