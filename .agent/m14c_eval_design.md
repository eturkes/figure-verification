# M1.4c/d eval design — pre-derived recipe (SCAFFOLDING → delete at M1 review)

Implement `verifier/eval.py` from THIS doc; do not re-derive. Goldens + branch map + refactor code below are
hand-derived vs `VPlot_SEMANTICS.md` §3–6 and design-verified, NOT run-verified — the prior session overflowed
before writing code. Run-verified THIS session: the goldens (re-checked arithmetically vs the CSVs) and the Step-0
exponent guard (DoS + naive-equivalence); the eval recipe itself stays design-verified only. The M1.4e DuckDB
oracle WILL independently confirm the goldens → treat them as expected-values to implement toward, confirm each by
running the gate. Skip a full LINEAR re-read of §3–6 — this doc distills it; still spot-check the cited § per helper
against the contract as you implement, opening the specific § for any uncertainty.

## Reads (minimal — the overflow cause was over-reading)
`src/verifier/`: `canon.py` (Cell/Column/Table + `_format_decimal`), `ingest.py` (`load_table`, `Manifest`,
`_coerce_numeric`/`_coerce_temporal` + the refactor below), `schema.py` (transform types), `errors.py`
(`VerificationError`). `examples/index.json` (corpus). `tests/test_ingest.py` (test STYLE: explicit hand-verified
`canon.Table` asserts, NOT syrupy). `data/sales.csv` + `data/weather.csv` (confirm the weather goldens g06/g07/g10).
`.agent/memory.md` eval-relevant invariants (already durable, do not restate in code): the `Column` kind-union +
`Cell`/`_format_decimal` rules, deferred string-canonicalization, the PARSE-vs-VERIFY error layering
(`VerificationError(msg, *, check=…)`), and the M1.4c filter-coercion entry.

## Step 0 — ingest refactor (do FIRST; then run existing ingest tests = cheap green check)
Split `_coerce_numeric` so eval's filter coercion reuses parse+precision WITHOUT the table magnitude bound
(§3 bounds a filter LITERAL by parse+precision+format only — it is COMPARED, never stored). Design-verified
coverage-safe with existing ingest tests (check names unchanged; tests assert `.check` only; precision-before-
magnitude reorder confirmed for `"9"*39`@scale1 → precision passes/magnitude fails → `data.numeric_value`, and
`"0.5"`@scale0 → precision fails → `data.numeric_value`). CONFIRM by running `pytest tests/test_ingest.py`.
The exponent guard (skip quantize when `exponent >= -scale`) is DoS prevention AND a VALUE no-op: a finite Decimal
with `exponent >= -scale` already has <= scale fractional places, so quantize cannot change its VALUE. The guard
matters because the UNGUARDED quantize crashes on a huge-exponent literal (e.g. `"1e999999999999999999"`, 20 chars,
within filter max_length=128) two ways: for that exact literal `value.adjusted() == MAX_PREC`, so `precision =
adjusted()+scale+2 > MAX_PREC` → `Context(prec=…)` raises ValueError BEFORE any digit materializes; for a slightly
smaller huge exponent (`adjusted() < MAX_PREC`) `precision` stays in range → quantize then materializes ~1e18 digits
→ MemoryError/hang. The guard skips both. It is VALUE-preserving only — the at-scale STORED representation (exponent)
is restored by `_coerce_numeric`'s re-quantize below (the filter path skips that, a literal is only COMPARED),
proven byte-identical to the prior `_coerce_numeric` this session (28/28 edge cases: value + as_tuple + raised check
all identical). It adds ONE branch → cover BOTH arms: the skip arm via an integral value (the existing `"9"*39`
magnitude case, or `"12000"`@scale0) and the quantize arm via a fractional value (`"0.5"`@scale0). ingest.py must
import `cast` (extend `from typing import Annotated, Literal` → `…, cast`); `as_tuple().exponent` is typed `int |
Literal['n','N','F']` so `cast(int, …)` is required for mypy (a finite Decimal always yields the int branch).

```python
def _decimal_at_scale(text: str, scale: int, *, check: str) -> Decimal:
    """parse + finite + exact-at-scale (NO magnitude); fold -0. Magnitude is added by _coerce_numeric (a stored
    cell must fit DECIMAL(38,scale)); a filter LITERAL is only COMPARED so §3 bounds it by parse+precision alone.
    Reused by eval (re-tagged check='filter.value_type')."""
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        msg = f"numeric value {text!r} is not a valid decimal"
        raise VerificationError(msg, check=check) from exc
    if not value.is_finite():
        msg = f"numeric value {text!r} is not finite"
        raise VerificationError(msg, check=check)
    # exponent guard (DoS prevention): a constructible huge-exponent literal (e.g. "1e999999999999999999",
    # within filter max_length=128) has exponent >= -scale, already exact at this scale -> skip quantize.
    # Unguarded it crashes: Context(prec>MAX_PREC) ValueError when adjusted()==MAX_PREC, else ~1e18-digit
    # materialization (MemoryError/hang). Only exponent < -scale carries excess fractional places (bounded).
    exponent = cast(int, value.as_tuple().exponent)  # finite -> int, never the 'n'/'N'/'F' specials
    if exponent < -scale:
        quantum = Decimal((0, (1,), -scale))
        precision = max(value.adjusted() + scale + 2, 1)
        context = Context(prec=precision, Emax=MAX_EMAX, Emin=MIN_EMIN, rounding=ROUND_HALF_EVEN)
        if value.quantize(quantum, context=context) != value:
            msg = f"numeric value {text!r} has more than {scale} fractional place(s)"
            raise VerificationError(msg, check=check)
    if value.is_zero():
        return value.copy_abs()
    return value

def _coerce_numeric(text: str, scale: int) -> Decimal:
    value = _decimal_at_scale(text, scale, check="data.numeric_value")
    if not (value.is_zero() or value.adjusted() <= _MAX_PRECISION - 1 - scale):
        msg = f"numeric value {text!r} exceeds DECIMAL({_MAX_PRECISION}, {scale}) magnitude"
        raise VerificationError(msg, check="data.numeric_value")
    # canonical stored form: re-quantize to exactly `scale` places (value was proved exact at scale by
    # _decimal_at_scale; the magnitude bound above — zero exempt — keeps this quantize bounded, no DoS).
    # Restores the original at-scale stored-cell behavior (byte-identical, verified); the filter path skips
    # this (a literal is only COMPARED).
    quantum = Decimal((0, (1,), -scale))
    precision = max(value.adjusted() + scale + 2, 1)
    context = Context(prec=precision, Emax=MAX_EMAX, Emin=MIN_EMIN, rounding=ROUND_HALF_EVEN)
    normalized = value.quantize(quantum, context=context)
    return normalized.copy_abs() if normalized.is_zero() else normalized
```
`_coerce_temporal(text, granularity, *, check: str = "data.temporal_value")` — add the kw-only `check` param, use
it at all 4 raise sites (date-parse ValueError, datetime-parse ValueError, timezone `tzinfo is not None`,
canonical-mismatch `canonical != text`; default preserves ingest behavior; eval passes `check="filter.value_type"`).

## eval.py recipe
Imports: `operator`; `from decimal import Decimal`; `from fractions import Fraction`; `from typing import Any, cast`;
`from collections.abc import Callable`; `from verifier import canon, ingest`; `from verifier.errors import
VerificationError`; `from verifier.schema import (Aggregate, CmpOp, Filter, GroupBy, Select, Sort, VPlotSpec)` (CmpOp for the
`_CMP` annotation; + any op types used in isinstance). `_CMP: dict[CmpOp, Callable[[Any, Any], bool]]` = {"eq":operator.eq,"ne":operator.ne,
"lt":operator.lt,"le":operator.le,"gt":operator.gt,"ge":operator.ge}.

`evaluate(spec: VPlotSpec, manifest: ingest.Manifest, csv_bytes: bytes) -> canon.Table` — sole public entry:
```
table = ingest.load_table(csv_bytes, manifest)        # source rows, source order (csv_bytes FIRST)
pending_keys: tuple[str,...] | None = None            # group_by awaiting its aggregate
active_keys: list[tuple[str, str]] = []               # last sort with NO later aggregate → closure
for op in spec.transform:
    if pending_keys is not None and not isinstance(op, Aggregate):
        raise VerificationError(..., check="transform.group_by_placement")   # group_by not immediately pre-aggregate (b14, double group_by)
    if   isinstance(op, Select):   table = _apply_select(table, op)
    elif isinstance(op, Filter):   table = _apply_filter(table, op)
    elif isinstance(op, GroupBy):
        _require_distinct(op.keys, "group_by.keys_distinct", "group_by key")
        for k in op.keys: _field_index(table, k)       # schema.fields_exist
        pending_keys = op.keys
    elif isinstance(op, Aggregate):
        table = _apply_aggregate(table, op, pending_keys)
        pending_keys = None
        active_keys = []                                # an aggregate RESETS the active sort
    else:                                               # Sort — last union variant in else (reachable; warn_unreachable-safe; mypy narrows)
        _validate_sort(table, op)                       # fields exist + distinct (sort.fields_distinct)
        active_keys = [(k.field, k.order) for k in op.by]
if pending_keys is not None:
    raise VerificationError(..., check="transform.group_by_placement")        # group_by as LAST op
return _total_sort(table, active_keys)
```
`spec.transform` = the ops tuple (confirm attr name in schema.py: VPlotSpec.transform). isinstance chain (NOT match)
keeps it simple; Sort in `else` so mypy/`warn_unreachable` see a reachable exhaustive tail.

Helpers:
- `_field_index(table, name) -> int` — `table.columns.index where .name==name`, else raise `schema.fields_exist`.
- `_require_distinct(names, check, label) -> None` — `len(set(names)) != len(names)` → raise `check`.
- `_apply_select(table, op)` — `_require_distinct(op.fields, "select.fields_distinct", "select field")`; idxs =
  `[_field_index(table,f) for f in op.fields]`; new columns/rows projected to idxs, NO dedup.
- `_apply_filter(table, op)` — `i = _field_index(table, op.field)`; `coerced = _coerce_filter_value(op.value,
  table.columns[i])`; keep row iff `row[i] is not None and _CMP[op.cmp](row[i], coerced)` (null cell → drop, incl ne).
- `_coerce_filter_value(value, column) -> Decimal | str` per §3 (ALL failures → `filter.value_type`; dispatch on
  column TYPE via `isinstance(column, canon.NumericColumn/TemporalColumn/StringColumn)`, NOT `.kind ==`, so mypy
  narrows `.scale`/`.granularity`; the third arm is the `else` tail like `evaluate`'s Sort — exhaustive, reachable.
  INVARIANT — specs reaching `evaluate` are decode-origin (`schema.decode_spec`) and msgspec rejects `bool` for
  `FilterValue = int | str` at the parse boundary, so `value` is a genuine `int | str` here; M1.4c filter-value
  tests build specs via decode, NOT direct `Filter(value=…)` construction that would bypass it):
    - `isinstance(column, canon.NumericColumn)`: `isinstance(value,int)` (genuine int per the decode-origin invariant above, no bool) → `Decimal(value)`
      [exact, compares by value]; `isinstance(value,str)` → `ingest._decimal_at_scale(value, column.scale,
      check="filter.value_type")` [parse+precision, NO magnitude].
    - `elif isinstance(column, canon.TemporalColumn)`: str → `ingest._coerce_temporal(value, column.granularity, check="filter.value_type")`
      [canonical ISO text]; int → raise `filter.value_type`.
    - `else` (StringColumn): str → `value` verbatim; int → raise `filter.value_type`.
  Cells: numeric=Decimal, temporal=canonical ISO str (sorts lexically=chronologically), string=str → `_CMP`
  compares (Decimal,Decimal)|(str,str) uniformly.
- `_validate_sort(table, op)` — fields = `[k.field for k in op.by]`; `_require_distinct(fields,
  "sort.fields_distinct", "sort field")`; `for f in fields: _field_index(table, f)`.
- `_apply_aggregate(table, op, pending_keys)`:
    - `key_idxs = [_field_index(table, k) for k in pending_keys]` if `pending_keys is not None` else `[]` (keys were
      validated at the group_by op + no op intervenes before aggregate, so this re-resolution never raises here).
    - groups: `pending_keys is None` → ONE group, key=() , rows=all (whole-table aggregate); else partition rows by
      key-tuple `tuple(row[idx] for idx in key_idxs)` (null key = its own group; first-seen dict order — closure
      re-sorts so order is irrelevant to the hash).
    - measure_plans (build in ONE pass, store per measure — do NOT recompute inside the per-group loop, else a
      two-loop transcription reuses the LAST measure's `src_idx`/`scale`): for each measure `m`, `src_idx =
      _field_index(table, m.field)` (raises `schema.fields_exist` if the measure field is absent); `src_col =
      table.columns[src_idx]`; `out_col = _measure_output_column(src_col, m.fn, m.output)`; `scale = src_col.scale if
      isinstance(src_col, canon.NumericColumn) else 0` (only mean consumes scale, and mean ⇒ numeric src ⇒ scale
      valid; count/min/max/string ignore it). Collect `measure_plans = [(m, src_idx, out_col, scale), ...]` (mypy
      infers `list[tuple[Measure, int, canon.Column, int]]`).
    - out columns = group-key columns (from pending_keys, original Column objects) ++ `[out_col for (_m, _idx,
      out_col, _scale) in measure_plans]`.
    - collision: all output names (keys ++ measure outputs) distinct → else raise `aggregate.output_unique`.
    - per group: per `(m, src_idx, _out_col, scale)` in measure_plans → `_aggregate_one(m.fn, [g_row[src_idx] for
      g_row in group_rows], scale)`; row = key cells ++ those measure cells.
- `_measure_output_column(src_col, fn, output) -> canon.Column` (raises `schema.field_types_match`; the three
  Column types are `kw_only` → construct BY KEYWORD; dispatch src kind via `isinstance(src_col, canon.NumericColumn)`
  etc. so mypy narrows `.scale`/`.granularity`):
    - count → `canon.NumericColumn(name=output, scale=0)` (any input kind).
    - sum|mean → src MUST be numeric (`isinstance(src_col, canon.NumericColumn)`) → `canon.NumericColumn(name=output,
      scale=src_col.scale)`; else raise. (Output scale = src scale per §3 "default = input scale"; v0.1 Measure +
      manifest declare no output scale, so mean is always at src scale.)
    - min|max → numeric→`canon.NumericColumn(name=output, scale=src_col.scale)`,
      temporal→`canon.TemporalColumn(name=output, granularity=src_col.granularity)`,
      string→`canon.StringColumn(name=output)` (any of the three kinds OK).
- `_aggregate_one(fn, cells, scale) -> Cell`: `non_null = [c for c in cells if c is not None]`; count →
  `Decimal(len(non_null))`. Else if `not non_null` → `None` (zero non-nulls → null for sum/mean/min/max). Then
  `decimals = cast(list[Decimal], non_null)` (no runtime branch; a no-op on the string/temporal min/max path, which
  never reads it) — sum → `sum(decimals, Decimal(0))`; mean → `mean_at_scale(sum(decimals, Decimal(0)),
  len(non_null), scale)`; min/max → `min`/`max(non_null)` (Decimal|str comparable within one kind). The `Decimal(0)`
  start is REQUIRED: `sum`'s no-start overload types as `Decimal | Literal[0]` (mypy-strict-verified), failing BOTH
  the `Cell` return AND `mean_at_scale`'s `Decimal` arg; confining `sum` to the sum/mean arms keeps a string/temporal
  min/max off the Decimal `sum`.
- `mean_at_scale(total: Decimal, count: int, scale: int) -> Decimal` (PUBLIC — M1.4e oracle reuses for parity;
  Decimal-exact, ONE HALF_EVEN rounding via Fraction → no float, no Decimal double-round):
```python
rounded = round(Fraction(total) / count, scale)          # Fraction rounded to `scale` places, HALF_EVEN
scaled = rounded * 10**scale                              # exact integer-valued Fraction (denominator==1, provable → assert omitted = branch-coverage-safe)
return _scaled_int_to_decimal(scaled.numerator, scale)
```
  verified mean(0.00,0.01)@2 → 0.005 → HALF_EVEN → 0.00 (to even) → Decimal('0.00').
- `_scaled_int_to_decimal(scaled: int, scale: int) -> Decimal`: `sign = 1 if scaled < 0 else 0`;
  `digits = tuple(int(c) for c in str(abs(scaled)))`; `return Decimal((sign, digits, -scale))`. Test negative directly.
- `_total_sort(table, active_keys) -> canon.Table` (§6 closure → permutation-invariant total order):
    - `names = [c.name for c in table.columns]`; for `(field,_) in active_keys`: `field in names` else raise
      `sort.field_in_plotted_table` (catches a key projected away by a post-sort select).
    - `used = {f for f,_ in active_keys}`; `tail = [(n,"ascending") for n in names if n not in used]` (remaining
      cols ascending, column order); `full = active_keys + tail`.
    - `rows = list(table.rows)`; `for field, order in reversed(full):` (stable multi-pass, least-significant first)
      `i = names.index(field); col = table.columns[i]`; `rows.sort(key=lambda r, i=i, c=col: _sort_key(r[i], c),
      reverse=(order=="descending"))` (default-arg bind i,c → ruff B023-safe).
    - `return canon.Table(columns=table.columns, rows=tuple(rows))`.
- `_sort_key(cell, column) -> tuple[bool, Cell]`: `cell is None` → `(True, Decimal(0) if column.kind == "numeric"
  else "")` (read-only `.kind` compare — no `.scale`/`.granularity` access → `isinstance` dispatch NOT needed here;
  typed sentinel → null-vs-null never compares Decimal-vs-str; True>False → null GREATEST, works under ascending
  null-last AND descending null-first via per-key reverse); else `(False, cell)`.

Coverage gotchas (already worked out — honor to avoid gate cycles): NO bare always-true `assert` (partial branch);
`cast` has no runtime branch; for-loops over always-non-empty iterables are coverage-safe; isinstance-`else`-Sort is
reachable. Decimal context imports (Context/MAX_EMAX/MIN_EMIN/ROUND_HALF_EVEN/InvalidOperation) live in ingest, not eval.

## Goldens (hand-derived vs §3–6; oracle confirms at M1.4e)
sales: month(str) region(str) revenue(num0) orders(num0); rows source order:
(2026-01,NA,12000,80)(2026-01,EU,9000,61)(2026-02,NA,15000,93)(2026-02,EU,11000,70)(2026-03,NA,13000,88)(2026-03,EU,14000,86).
weather: date(temporal/date) city(str) temp_c(num1) precip_mm(num1) aqi(num0); 8 rows — CONFIRM g06/g07/g10 vs data/weather.csv.

- g01 group_by month, sum revenue→total_revenue, sort month asc → cols(month:str,total_revenue:num0):
  (2026-01,21000)(2026-02,26000)(2026-03,27000)   [VERIFIED]
- g02 group_by region, sum revenue→total_revenue, sort total_revenue desc → cols(region:str,total_revenue:num0):
  (NA,40000)(EU,34000)
- g03 group_by month, sum orders→total_orders, sort month asc → cols(month:str,total_orders:num0):
  (2026-01,141)(2026-02,163)(2026-03,174)
- g04 select revenue,orders (no sort → closure revenue asc,orders asc) → cols(revenue:num0,orders:num0):
  (9000,61)(11000,70)(12000,80)(13000,88)(14000,86)(15000,93)   [VERIFIED]
- g05 group_by region, mean revenue→avg_revenue, sort region asc → cols(region:str,avg_revenue:num0):
  (EU,11333)(NA,13333)   [VERIFIED: NA 40000/3=13333.33→13333; EU 34000/3=11333.33→11333]
- g06 group_by city, max temp_c→max_temp, sort max_temp desc → cols(city:str,max_temp:num1): (Cairo,16.4)(London,6.0)
- g07 select date,city,temp_c (closure date asc,city asc,temp_c asc) → cols(date:temporal,city:str,temp_c:num1):
  (2026-01-01,Cairo,14.0)(2026-01-01,London,4.5)(2026-01-02,Cairo,15.2)(2026-01-02,London,5.1)
  (2026-01-03,Cairo,16.4)(2026-01-03,London,3.8)(2026-01-04,Cairo,13.9)(2026-01-04,London,6.0)
- g08 filter region eq NA, group_by month, sum revenue→total_revenue, sort month asc →
  cols(month:str,total_revenue:num0): (2026-01,12000)(2026-02,15000)(2026-03,13000)
- g09 group_by month, min revenue→min_revenue, sort month asc → cols(month:str,min_revenue:num0):
  (2026-01,9000)(2026-02,11000)(2026-03,13000)
- g10 select temp_c,precip_mm (closure temp_c asc,precip asc) → cols(temp_c:num1,precip_mm:num1):
  (3.8,0.0)(4.5,2.0)(5.1,3.5)(6.0,1.2)(13.9,0.5)(14.0,0.0)(15.2,0.0)(16.4,0.0)

## index.json normalize (corpus = check source-of-truth)
b07/b09 already machine-named (`schema.fields_exist` / `schema.field_types_match`). Set 4 prose values →
b10 `filter.value_type` (filter region gt 5/int) · b14 `transform.group_by_placement` (group_by month then sort) ·
b15 `aggregate.output_unique` (group_by region, sum revenue as region) · b16 `sort.fields_distinct` (sort [month
asc, month desc]). Eval-layer bad specs select via `decodes==true and "M1.4" in caught_by`.
M1.5-layer (eval SUCCEEDS — defer the failure): b08(hash) b11(axis) b12(enc-absent) b13(unit).

## Test allocation (each commit stays 100% branch coverage = code + its covering tests together)
### M1.4c — eval.py + ingest refactor + 100% coverage
- 6 eval-bad specs raise their check: b07 schema.fields_exist, b09 schema.field_types_match, b10 filter.value_type,
  b14 transform.group_by_placement, b15 aggregate.output_unique, b16 sort.fields_distinct.
- 3 VERIFIED anchor goldens (sales-only, real correctness asserts — not "runs"): g01, g04, g05.
- inline constructed-table branch tests (self-contained, no weather dep) covering EVERY remaining branch:
  - select.fields_distinct, group_by.keys_distinct, sort.fields_distinct (corpus-less distinctness raises).
  - sort.field_in_plotted_table: group_by month→aggregate sum revenue as total→sort total→select[month] → raise.
  - transform.group_by_placement: group_by as LAST op (post-loop) AND double group_by (top-of-loop) — b14 covers
    group_by-then-sort; add the last-op + double cases inline.
  - whole-table aggregate (no preceding group_by) → one row.
  - multi-measure aggregate over DIFFERENT source columns (measure_plans regression): group_by month, measures
    [sum revenue→r, mean orders→o] → assert BOTH output columns correct (r from revenue, o from orders — a
    last-measure-index bug would read orders for both).
  - pre-aggregate sort DISCARDED by the aggregate reset: sort revenue desc, then group_by month + sum revenue →
    assert output order = the closure re-sort (month asc), NOT the pre-agg desc order (aggregate locks
    `active_keys=[]`).
  - count fn (non-null count, scale 0); all-null group → count 0 + sum/mean/min/max null (zero non-nulls).
  - group_by with a NULL key cell → the null key forms its own group (emitted, not dropped; §5).
  - min/max on NUMERIC, TEMPORAL, and STRING — ALL inline in M1.4c (g06/g09 land in M1.4d, so the numeric min/max
    arm has NO M1.4c golden; cover numeric min AND max inline here).
  - filter §3 coercion rows beyond b10's int→numeric error: int→numeric ok, string→numeric ok, string→numeric
    over-precise→raise, string→numeric unparsable→raise, string→temporal ok, string→temporal bad→raise,
    int→temporal→raise, int→string→raise, string→string verbatim.
  - filter null cell → row dropped (incl cmp=ne).
  - exponent-guard regression (DoS): a numeric-column filter literal `"1e999999999999999999"` coerces via
    `_decimal_at_scale` instantly (exponent >= -scale → quantize skipped, no ~1e18-digit materialization) — assert
    it returns/compares without hang, locking the Step-0 fix.
  - closure null GREATEST — BOTH sentinel branches: (a) numeric null via all-null-group aggregate then closure;
    (b) temporal/string null — select a column holding a null cell (ingest empty→None) → closure null-last on "".
  - active DESCENDING sort with a null cell → assert the null sorts FIRST (§6 null-greatest ⇒ descending null-first
    via per-key reverse); complements the ascending null-last closure case above.
  - `_scaled_int_to_decimal` negative `scaled` (sign branch) — direct call.
  - mean HALF_EVEN-to-even (e.g. the 0.005@2→0.00 case) — direct `mean_at_scale` or a 2-row group.
- Accept: 6 bad → specific check; g01/g04/g05 row-for-row; aggregation Decimal-exact (no float); gate green @100% branch.

### M1.4d — golden-corpus completion + determinism anchor (test-only; code already 100% covered)
- remaining hand-verified goldens g02,g03,g06,g07,g08,g09,g10 (g06/g07/g10 confirm vs data/weather.csv).
- b08/b11/b12/b13 → eval SUCCEEDS (eval never inspects encoding/hash; failure is M1.5).
- no-op spec edit determinism: a semantically no-op edit (a sort superseded by a later sort, or a pre-aggregate
  sort) → identical plotted-table hash (`canon.hash_table`), only the spec hash (`canon.hash_spec`) moves. Build
  variants via `msgspec.structs.replace(spec, transform=...)` on the frozen spec.
- Accept: full corpus row-for-row; no-op edit leaves table hash fixed; gate green @100% branch.
