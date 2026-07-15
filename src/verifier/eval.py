# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Deterministic VPlot evaluator — the trust spine's recompute step.

Given a validated VPlotSpec, the trusted per-column manifest, and the raw CSV bytes,
evaluate() applies the spec's transform pipeline to the ingested source table and closes
with the canonical total sort, returning the plotted canon.Table the renderer later inlines.
The model proposes ONLY the spec; every plotted value is recomputed here, never model-supplied
(see roadmap data-flow). This realizes VPlot_SEMANTICS.md sections 3-6 (transform pipeline +
the section 6 closure); that document is the meaning, this module the implementation.

Decimal-exact throughout (no float, no NaN): numerics stay Decimal at the manifest scale and
mean rounds ONCE HALF_EVEN via Fraction (no float, no double-round). Spec-semantic violations
the schema gate cannot catch — a field absent from the running table, a group_by not immediately
before an aggregate, a filter literal that cannot coerce to its column, a non-distinct/colliding
name — raise VerificationError mid-recompute with a dotted `.check` (the enforce half of
VPlot_SEMANTICS.md section 5; M1.5 surfaces each as a structured blocking result). The renderer is
never reached when a check fails.

M5.1i adds deterministic logical-work admission. ``evaluate_run`` returns the same table plus
consumed units for internal audit; ``evaluate`` remains its table-only projection. Every transform
and the final closure charges before its implementation starts. The formulas model bounded logical
visits, not CPU time: select=fields*(rows+columns), filter=rows+columns,
group_by=keys*columns, aggregate=(keys+measures)*(rows+columns), and each declared sort=
rows*ceil(log2(max(rows,2)))*keys. The closure uses that sort formula with every final column.
"""

import operator
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from decimal import Decimal
from fractions import Fraction
from typing import Any, cast

from verifier import canon, ingest
from verifier.errors import VerificationError
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.schema import (
    AggFn,
    Aggregate,
    CmpOp,
    Filter,
    GroupBy,
    Measure,
    Select,
    Sort,
    Transform,
    VPlotSpec,
)

# Comparison operators by name (CmpOp closes the set). Each takes Any/Any because a cell is
# Decimal | str | None; the call sites guard out None and coerce the literal to the column's
# type, so a comparison only ever sees (Decimal, Decimal) or (str, str).
_CMP: dict[CmpOp, Callable[[Any, Any], bool]] = {
    "eq": operator.eq,
    "ne": operator.ne,
    "lt": operator.lt,
    "le": operator.le,
    "gt": operator.gt,
    "ge": operator.ge,
}


class EvaluationError(VerificationError):
    """An evaluator failure carrying work admitted before the failure.

    This preserves every existing ``VerificationError`` check/message contract while allowing the
    verification spine to retain deterministic work consumption on semantic and resource failures.
    """

    def __init__(self, message: str, *, check: str, work_units: int) -> None:
        super().__init__(message, check=check)
        self.work_units = work_units


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    """Successful recomputation plus its internal deterministic work consumption."""

    table: canon.Table = dataclass_field(repr=False)
    work_units: int


@dataclass(slots=True)
class _WorkBudget:
    """One evaluator's cumulative inclusive work ceiling."""

    limit: int
    consumed: int = 0

    def charge(self, operation: str, required: int) -> None:
        """Admit ``required`` atomically, or fail before ``operation`` starts."""
        if required > self.limit - self.consumed:
            msg = (
                f"evaluator work limit {self.limit} would be exceeded before {operation}: "
                f"{self.consumed} consumed + {required} required"
            )
            raise EvaluationError(
                msg,
                check="resource.eval_work",
                work_units=self.consumed,
            )
        self.consumed += required


def _linear_work(table: canon.Table, width: int) -> int:
    """Logical visits for a row/column-linear operation of ``width`` fields/keys."""
    return (len(table.rows) + len(table.columns)) * width


def _sort_work(table: canon.Table, key_count: int) -> int:
    """Roadmap formula using integer-only ceil(log2(max(rows, 2)))."""
    rows = len(table.rows)
    log_rows = (max(rows, 2) - 1).bit_length()
    return rows * log_rows * key_count


def evaluate(
    spec: VPlotSpec,
    manifest: ingest.Manifest,
    csv_bytes: bytes,
    *,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> canon.Table:
    """Public table-only projection of :func:`evaluate_run`."""
    return evaluate_run(spec, manifest, csv_bytes, limits=limits).table


def evaluate_run(
    spec: VPlotSpec,
    manifest: ingest.Manifest,
    csv_bytes: bytes,
    *,
    limits: VerificationLimits = DEFAULT_LIMITS,
) -> EvaluationRun:
    """Recompute with deterministic work admission and retain consumed units internally.

    Every ``VerificationError`` arising after entry is re-raised as ``EvaluationError`` with the
    already-admitted work count. Programming/configuration exceptions retain their native types.
    """
    budget = _WorkBudget(limit=limits.max_eval_work_units)
    try:
        return _evaluate(spec, manifest, csv_bytes, limits=limits, budget=budget)
    except EvaluationError:
        raise
    except VerificationError as exc:
        raise EvaluationError(
            str(exc),
            check=exc.check,
            work_units=budget.consumed,
        ) from exc


def _evaluate(
    spec: VPlotSpec,
    manifest: ingest.Manifest,
    csv_bytes: bytes,
    *,
    limits: VerificationLimits,
    budget: _WorkBudget,
) -> EvaluationRun:
    """Implementation behind ``evaluate_run``; all costly calls follow their charge.

    Loads the source table (ingest), folds the transform ops in declared order, then applies
    the section 6 total-sort closure. A group_by must be immediately followed by an aggregate
    (it stages keys in `pending_keys`); the most recent sort with no later aggregate seeds the
    closure ordering (`active_keys`), which an aggregate resets (it rebuilds the table).
    """
    table = ingest.load_table(csv_bytes, manifest, limits=limits)
    pending_keys: tuple[str, ...] | None = None  # group_by awaiting its aggregate
    for op in spec.transform:
        if pending_keys is not None and not isinstance(op, Aggregate):
            msg = "group_by must be immediately followed by an aggregate"
            raise VerificationError(msg, check="transform.group_by_placement")
        if isinstance(op, Select):
            budget.charge("select", _linear_work(table, len(op.fields)))
            table = _apply_select(table, op)
        elif isinstance(op, Filter):
            budget.charge("filter", _linear_work(table, 1))
            table = _apply_filter(table, op)
        elif isinstance(op, GroupBy):
            budget.charge("group_by", len(table.columns) * len(op.keys))
            _require_distinct(op.keys, "group_by.keys_distinct", "group_by key")
            for key in op.keys:
                _field_index(table, key)  # schema.fields_exist (raises if absent)
            pending_keys = op.keys
        elif isinstance(op, Aggregate):
            key_count = len(pending_keys) if pending_keys is not None else 0
            budget.charge(
                "aggregate",
                _linear_work(table, key_count + len(op.measures)),
            )
            table = _apply_aggregate(table, op, pending_keys)
            pending_keys = None
        else:  # Sort (last union variant; reachable, so warn_unreachable stays satisfied)
            budget.charge("sort", _sort_work(table, len(op.by)))
            _validate_sort(table, op)  # every sort is validated; active_sort picks the applied one
    if pending_keys is not None:
        msg = "group_by must be immediately followed by an aggregate"
        raise VerificationError(msg, check="transform.group_by_placement")
    active = active_sort(spec.transform)
    active_keys: list[tuple[str, str]] = (
        [(key.field, key.order) for key in active.by] if active is not None else []
    )
    budget.charge("closure", _sort_work(table, len(table.columns)))
    plotted = _total_sort(table, active_keys)
    return EvaluationRun(table=plotted, work_units=budget.consumed)


def active_sort(transform: tuple[Transform, ...]) -> Sort | None:
    """The lone declared sort that survives into the plotted table (section 6): the last `sort`
    op with no later `aggregate`. An aggregate rebuilds the table, discarding any earlier sort,
    and a later sort supersedes an earlier one. `evaluate`'s closure seed and the certificate's
    sort disclosure both read this, so "which sort applied" has ONE definition and cannot drift."""
    active: Sort | None = None
    for op in transform:
        if isinstance(op, Aggregate):
            active = None
        elif isinstance(op, Sort):
            active = op
    return active


# --- field / distinctness helpers --------------------------------------------
def _field_index(table: canon.Table, name: str) -> int:
    """The column position of `name`, or raise schema.fields_exist. The single point where a
    transform's field reference is checked against the running table's columns."""
    for index, column in enumerate(table.columns):
        if column.name == name:
            return index
    msg = f"field {name!r} does not exist in the table"
    raise VerificationError(msg, check="schema.fields_exist")


def _require_distinct(names: Sequence[str], check: str, label: str) -> None:
    """Raise `check` if `names` repeats a value (section 5 distinctness)."""
    if len(set(names)) != len(names):
        msg = f"{label} names must be distinct: {tuple(names)!r}"
        raise VerificationError(msg, check=check)


# --- per-op transforms -------------------------------------------------------
def _apply_select(table: canon.Table, op: Select) -> canon.Table:
    """Project to the listed fields, in listed order, no dedup (section 3 select)."""
    _require_distinct(op.fields, "select.fields_distinct", "select field")
    idxs = [_field_index(table, field) for field in op.fields]
    columns = tuple(table.columns[i] for i in idxs)
    rows = tuple(tuple(row[i] for i in idxs) for row in table.rows)
    return canon.Table(columns=columns, rows=rows)


def _apply_filter(table: canon.Table, op: Filter) -> canon.Table:
    """Keep rows whose cell is non-null and satisfies the comparison (section 3 filter:
    a null cell drops under every operator, including ne — three-valued logic collapses to drop)."""
    i = _field_index(table, op.field)
    coerced = _coerce_filter_value(op.value, table.columns[i])
    compare = _CMP[op.cmp]
    rows = tuple(row for row in table.rows if row[i] is not None and compare(row[i], coerced))
    return canon.Table(columns=table.columns, rows=rows)


def _coerce_filter_value(value: int | str, column: canon.Column) -> Decimal | str:
    """Lift a filter literal to the column's comparison type, or raise filter.value_type
    (section 3). Dispatch on the Column type (isinstance, not `.kind ==`, so mypy narrows
    `.scale`/`.granularity`). The literal is COMPARED, never stored, so a numeric literal
    carries no DECIMAL(38, scale) magnitude bound (ingest._decimal_at_scale bounds parse +
    precision only). The spec reached evaluate via schema.decode_spec, which rejects bool for
    FilterValue = int | str at the parse boundary, so `value` is a genuine int | str here."""
    if isinstance(column, canon.NumericColumn):
        if isinstance(value, int):  # genuine int (no bool: decode rejected it) -> exact Decimal
            return Decimal(value)
        return ingest._decimal_at_scale(value, column.scale, check="filter.value_type")
    if isinstance(column, canon.TemporalColumn):
        if isinstance(value, str):
            return ingest._coerce_temporal(value, column.granularity, check="filter.value_type")
        msg = f"temporal column {column.name!r} needs an ISO date/datetime literal, got {value!r}"
        raise VerificationError(msg, check="filter.value_type")
    if isinstance(value, str):  # StringColumn (the exhaustive else of the Column union)
        return value
    msg = f"string column {column.name!r} needs a string literal, got integer {value!r}"
    raise VerificationError(msg, check="filter.value_type")


def _validate_sort(table: canon.Table, op: Sort) -> None:
    """Sort keys must be distinct and exist in the running table (section 5/6); ordering itself
    is applied by the closure so the declared order survives a later aggregate-free pipeline."""
    fields = [key.field for key in op.by]
    _require_distinct(fields, "sort.fields_distinct", "sort field")
    for field in fields:
        _field_index(table, field)


# --- aggregation -------------------------------------------------------------
def _apply_aggregate(
    table: canon.Table, op: Aggregate, pending_keys: tuple[str, ...] | None
) -> canon.Table:
    """Group by the staged keys (or the whole table when none) and emit one row per group:
    the key cells followed by each measure's aggregate (section 4/5). A null key forms its own
    group (section 5); group order is first-seen and irrelevant — the closure re-sorts."""
    key_idxs = (
        [_field_index(table, key) for key in pending_keys] if pending_keys is not None else []
    )

    groups: list[tuple[tuple[canon.Cell, ...], list[tuple[canon.Cell, ...]]]]
    if pending_keys is None:
        groups = [((), list(table.rows))]  # whole-table aggregate -> one group, empty key
    else:
        grouped: dict[tuple[canon.Cell, ...], list[tuple[canon.Cell, ...]]] = {}
        for row in table.rows:
            grouped.setdefault(tuple(row[idx] for idx in key_idxs), []).append(row)
        groups = list(grouped.items())

    # Resolve each measure once (source index, output column, mean scale) BEFORE the per-group
    # loop, so a multi-measure aggregate over different source columns keeps each measure's own
    # index/scale rather than reusing the last measure's.
    measure_plans: list[tuple[Measure, int, canon.Column, int]] = []
    for measure in op.measures:
        src_idx = _field_index(table, measure.field)
        src_col = table.columns[src_idx]
        out_col = _measure_output_column(src_col, measure.fn, measure.output)
        scale = src_col.scale if isinstance(src_col, canon.NumericColumn) else 0
        measure_plans.append((measure, src_idx, out_col, scale))

    key_columns = [table.columns[idx] for idx in key_idxs]
    out_columns = tuple(key_columns) + tuple(col for (_m, _i, col, _s) in measure_plans)
    out_names = [col.name for col in out_columns]
    if len(set(out_names)) != len(out_names):
        msg = f"aggregate output names collide with a group key or each other: {out_names!r}"
        raise VerificationError(msg, check="aggregate.output_unique")

    out_rows: list[tuple[canon.Cell, ...]] = []
    for gkey, group_rows in groups:
        cells = [
            _aggregate_one(measure.fn, [grp[src_idx] for grp in group_rows], scale)
            for (measure, src_idx, _col, scale) in measure_plans
        ]
        out_rows.append(gkey + tuple(cells))
    return canon.Table(columns=out_columns, rows=tuple(out_rows))


def _measure_output_column(src_col: canon.Column, fn: AggFn, output: str) -> canon.Column:
    """The output column for a measure, or raise schema.field_types_match. count yields a scale-0
    numeric for any input; sum/mean require a numeric source (output at the source scale, the
    section 3 default); min/max keep the source kind (any of numeric/temporal/string)."""
    if fn == "count":
        return canon.NumericColumn(name=output, scale=0)
    if fn in ("sum", "mean"):
        if isinstance(src_col, canon.NumericColumn):
            return canon.NumericColumn(name=output, scale=src_col.scale)
        msg = f"aggregate {fn!r} requires a numeric column; {src_col.name!r} is {src_col.kind}"
        raise VerificationError(msg, check="schema.field_types_match")
    if isinstance(src_col, canon.NumericColumn):  # min | max -> source kind preserved
        return canon.NumericColumn(name=output, scale=src_col.scale)
    if isinstance(src_col, canon.TemporalColumn):
        return canon.TemporalColumn(name=output, granularity=src_col.granularity)
    return canon.StringColumn(name=output)


def _exact_total(decimals: list[Decimal], scale: int) -> Decimal:
    """Exact Σ of same-scale Decimals (section 3). `sum()`/`+` round to the ambient decimal
    context (prec 28 < the DECIMAL(38) domain), dropping digits and making the result depend on
    accumulation order — which would break exactness and the plotted-table hash's
    permutation-invariance. Fraction sums losslessly and stays associative; each cell is a
    multiple of 10**-scale, so scaling by 10**scale clears the denominator to an exact int."""
    total = sum((Fraction(cell) for cell in decimals), Fraction(0))
    return _scaled_int_to_decimal((total * 10**scale).numerator, scale)


def _aggregate_one(fn: AggFn, cells: list[canon.Cell], scale: int) -> canon.Cell:
    """One group's aggregate over one column's cells (section 4). count = non-null count;
    sum/mean/min/max over zero non-nulls = null (SQL-matching). mean rounds once HALF_EVEN."""
    non_null = [cell for cell in cells if cell is not None]
    if fn == "count":
        return Decimal(len(non_null))
    if not non_null:
        return None
    # min/max read non_null directly (temporal/string compare as canonical str); only sum/mean
    # need the Decimal view. The cast is a no-op the min/max paths never read.
    decimals = cast(list[Decimal], non_null)
    if fn == "sum":
        return _exact_total(decimals, scale)
    if fn == "mean":
        return mean_at_scale(_exact_total(decimals, scale), len(non_null), scale)
    if fn == "min":
        return min(non_null)
    return max(non_null)


def mean_at_scale(total: Decimal, count: int, scale: int) -> Decimal:
    """The mean total/count quantized to `scale` places, HALF_EVEN, exactly. Public so the
    M1.4f DuckDB oracle recomputes mean identically (SQL avg rounds through double). Fraction
    keeps the division exact and rounds ONCE (no float, no Decimal double-round); the scaled
    result is integer-valued (denominator 1) so .numerator is exact."""
    rounded = round(Fraction(total) / count, scale)
    scaled = rounded * 10**scale
    return _scaled_int_to_decimal(scaled.numerator, scale)


def _scaled_int_to_decimal(scaled: int, scale: int) -> Decimal:
    """An integer scaled by 10**scale back to a Decimal with exactly `scale` fractional places."""
    sign = 1 if scaled < 0 else 0
    digits = tuple(int(char) for char in str(abs(scaled)))
    return Decimal((sign, digits, -scale))


# --- canonical total sort (section 6 closure) --------------------------------
def _row_sorter(
    index: int, column: canon.Column
) -> Callable[[tuple[canon.Cell, ...]], tuple[bool, Decimal | str]]:
    """Bind a column's position into a row-key, evaluated per call (no B023 late-binding)."""
    return lambda row: _sort_key(row[index], column)


def _total_sort(table: canon.Table, active_keys: list[tuple[str, str]]) -> canon.Table:
    """Close the pipeline with a deterministic total order: the declared sort keys first, then
    every remaining column ascending (column order), nulls greatest. This makes the plotted
    table permutation-invariant, so its hash depends only on the recomputed contents."""
    names = [column.name for column in table.columns]
    for field, _order in active_keys:
        if field not in names:  # a key projected away by a post-sort select
            msg = f"sort field {field!r} is not in the plotted table"
            raise VerificationError(msg, check="sort.field_in_plotted_table")
    used = {field for field, _ in active_keys}
    tail = [(name, "ascending") for name in names if name not in used]
    full = active_keys + tail
    rows = list(table.rows)
    # Stable multi-pass, least-significant key last: sort by each key from least to most
    # significant. _row_sorter binds index/column per call, so the closure is late-binding-safe.
    for field, order in reversed(full):
        i = names.index(field)
        rows.sort(key=_row_sorter(i, table.columns[i]), reverse=(order == "descending"))
    return canon.Table(columns=table.columns, rows=tuple(rows))


def _sort_key(cell: canon.Cell, column: canon.Column) -> tuple[bool, Decimal | str]:
    """Order key for one cell: (is_null, value), with a typed non-null sentinel in slot 2 so a
    null never compares Decimal-against-str. True > False puts nulls greatest, which under a
    per-key reverse means null-last ascending and null-first descending (section 6)."""
    if cell is None:
        return (True, Decimal(0) if column.kind == "numeric" else "")
    return (False, cell)
