# VPlot v0.1 — semantics

Schema is syntax; this is meaning. `src/verifier/schema.py` (+ `schema/vplot-0.1.schema.json`)
is the DECODE gate: shape, types, enums, bounds. **This file is the MEANING contract** —
M1.4 evaluator, M1.5 checks, M1.6 renderer, and the DuckDB oracle (dev/test) all conform
to it. Co-versioned `vplot-0.1`. Boundary + the modest claim: `POC_SCOPE.md`.

A spec that passes `decode_spec` is syntactically total (every field present, typed, never
coerced). Semantics add MEANING rules that need the dataset + its column manifest (M1.3),
so they run post-decode (M1.4 eval, M1.5 checks). Decode-valid ⊉ semantically-valid: a
well-formed spec naming a missing column decodes, then blocks — never renders.

## 1. Trust spine

- The untrusted model emits ONLY the spec: `transform` + `encoding` + declared `dataset.hash`.
  Never plotted values, labels, units, scales, or policy.
- The trusted verifier recomputes ALL plotted data from the source CSV; the renderer inlines
  ONLY that recomputed table → a model-supplied PLOTTED value cannot reach `data.values`
  (impossible by construction, not a check). Model-supplied spec PARAMETERS (filter literals,
  field names, channel types) shape the selection and are disclosed in the badge — never inlined
  as mark data. `transform.aggregates_match_recomputation` (M1.5) asserts the inlined
  `data.values` are byte-identical to the recomputation, backed by the oracle.
- Only allowlisted ops decode → `transform.ops_allowed` + `security.no_arbitrary_code` hold by
  construction: no `eval`/`exec`/SQL/JS/free-form-expr path exists anywhere.
- Checks prove mechanical consistency (spec ↔ encoding ↔ binding), NOT representativeness or
  intent: a valid cherry-picked `filter` passes. The VCert badge (M1.6) discloses every
  applied filter + sort, so a reader sees the selected subset; the verifier guarantees the
  chart faithfully shows that selection, not that the selection is fair.
- Axis titles + units = trusted manifest, never the spec (their VALUE is correct by
  construction). `label.quantitative_units_present` (M1.5) still ENFORCES that a unit is present
  per quantitative channel — manifest units are optional (M1.3), so presence is checked, not given.

## 2. Data model

- Source = a CSV under `data/`. Cells parse as TEXT, then coerce to the column's MANIFEST
  type (M1.3 — a CSV alone carries no types/units/labels). The manifest is the trusted column
  schema; it is hashed into the VCert.
- Column types: `numeric` (scale s ≥ 0 decimal places; integer = scale 0), `temporal`
  (canonical zero-padded ISO-8601 — date `YYYY-MM-DD` or datetime `YYYY-MM-DDThh:mm:ss[.ffffff]`,
  granularity per manifest; lexical order = chronological), `string` (nominal/ordinal text,
  Unicode after decode).
- ONE null token: an empty cell → null. No other null source. Null prints as a single reserved
  sentinel in the canonical table (M1.4). NaN never exists (no float math, §3).
- No floats in data OR spec: spec numerics are `int | string` (float/bool/null tokens rejected
  at decode, schema finding 3); column numerics are `Decimal` (§3).

## 3. Numbers + rounding

- Numeric cells → `Decimal` at the column's manifest scale. The cell must be EXACTLY representable
  at scale s (≤ s decimal places); excess precision = a SEMANTIC error — source data is never
  silently rounded (only computed aggregates quantize, below). Integer = scale 0.
- Aggregation is EXACT, then QUANTIZE `ROUND_HALF_EVEN`. Exact summation + count are
  order-independent → hash-stable; `mean` adds ONE final division + quantize (its inputs are
  order-independent, so the result is too — division itself is not associative). No float, no Kahan.
  - `sum` → exact Σ; output scale = input scale.
  - `mean` → (exact Σ) / (non-null count), ONE division, quantize HALF_EVEN to the
    manifest-declared output scale (M1.3; default = input scale).
  - `min`/`max` → exact; output type = input type.
  - `count` → non-null count → integer (scale 0).
- Filter-value coercion — the spec `value: int | string` is coerced to the field's column type
  BEFORE comparison:

  | column | spec int | spec string |
  |---|---|---|
  | numeric | `Decimal(int)` @ scale | `Decimal(string)`, exact at scale; unparsable OR over-precise (> s places) → semantic error |
  | temporal | semantic error | parse canonical ISO; bad format → semantic error |
  | string | semantic error | used verbatim |

  Coercion failure = a SEMANTIC error → block (M1.4 eval raises, surfaced as a failed check),
  never a silent drop-all. Comparison then happens within one coerced type domain.

## 4. Transform pipeline

An ordered list applied left → right over the loaded table; the schema (columns + types) flows
through each op. Empty list → the loaded table unchanged.

- **select**`{fields}` → projection: keep the listed columns, in listed order; rows unchanged
  (NO dedup — projection, not `DISTINCT`). Sets downstream column order.
- **filter**`{field, cmp, value}` → keep rows where `cell cmp coerced-value` is TRUE.
  - `cmp` ∈ {eq, ne, lt, le, gt, ge}; numeric/temporal compare by value; string compares by
    Unicode code-point order (= UTF-8 byte order; matches DuckDB binary collation).
  - NULL cell → comparison is UNKNOWN (SQL three-valued logic) → row DROPPED (incl. `ne`).
    Matches `WHERE`.
- **group_by**`{keys}` → establishes the grouping for the aggregate that IMMEDIATELY follows.
  NULL key = its own single group (SQL `GROUP BY`). v0.1 placement rule: a `group_by` is valid
  only immediately before an `aggregate`; a `group_by` elsewhere → semantic error.
- **aggregate**`{measures}` → collapse to one row per group, or ONE row over the whole table
  when no `group_by` immediately precedes.
  - Output columns = group keys (group_by order) ++ measure outputs (measures order); types
    per §3. This is the schema downstream ops then see.
  - `count` = non-null count; `sum`/`mean`/`min`/`max` over ZERO non-nulls → NULL (SQL-matching,
    never 0 or empty).
  - Input-type rule: `sum`/`mean` → numeric only; `min`/`max` → numeric | temporal | string;
    `count` → any. A measure `fn` on an incompatible column type → semantic error.
  - Measure `as` renames the output column (schema `as` → `output`).
- **sort**`{by:[{field, order}…]}` → reorder rows by the keys in order; schema unchanged. Each
  key direction ∈ {ascending, descending}. NULL = greatest (ascending → nulls last; descending
  → nulls first).

## 5. Distinctness + collision (semantic, enforced M1.4)

- `select.fields` distinct; `group_by.keys` distinct; `sort.by` fields distinct.
- aggregate `as` names: mutually unique AND disjoint from the group keys (no output-column
  collision).
- Every referenced field exists in the CURRENT schema at that pipeline step (`schema.fields_exist`,
  M1.5); encoding channels reference existing PLOTTED-table columns
  (`encoding.fields_exist_in_plotted_table`, M1.5).

## 6. Canonical total ordering (M1.4)

The plotted table is closed under a TOTAL order so its hash is permutation-invariant:
1. the ACTIVE declared sort — the LAST `sort` op in the pipeline (an earlier `sort` superseded by
   a later one, or discarded by an intervening `aggregate`, does NOT apply); its keys in order +
   direction + null-greatest, THEN
2. every remaining column, in plotted-table column order, ascending null-greatest — a fixed
   tiebreak.

No `sort` op → step 1 is empty and step 2 alone is already total.

Any remaining ties fall only between byte-identical rows, so the serialization is identical
regardless of their relative order → the plotted-table hash is permutation-invariant under
input-row permutation. (The dataset hash is NOT permutation-invariant — it is raw source
bytes, §8.)

## 7. Encoding + labels

- A channel = `{field, type}` ONLY (`type` = Vega-Lite channel type; schema key `type` → struct
  `kind`). No model-proposed title/unit/scale/format.
- `type` ↔ plotted-column type (`encoding.axis_types_match_fields`, M1.5):

  | channel `type` | column type |
  |---|---|
  | quantitative | numeric |
  | temporal | temporal |
  | ordinal | numeric \| string |
  | nominal | string \| numeric |

- `x`, `y` required; `color` optional = a third channel, same rules. The color legend domain =
  the data's distinct values (`encoding.legend_domain_matches_data`, M1.5).
- Axis title = manifest display label + manifest unit appended (M1.6); the title VALUE is
  manifest-sourced, never model-proposed. `label.quantitative_units_present` (M1.5) verifies the
  manifest supplies a unit for each quantitative channel and BLOCKS when absent (units are optional
  in the manifest, M1.3 — presence is checked, not guaranteed by construction).
- A DERIVED plotted column (an aggregate `as`) inherits manifest metadata through its measure to
  the source field: `sum`/`mean`/`min`/`max` carry the source `unit` + `label`, so
  `label.quantitative_units_present` resolves a derived quantitative channel through this lineage
  (`count` is dimensionless — no inherited unit). A group_by KEY keeps its source column's
  metadata; a derived column's numeric scale follows §3.
- `bar` mark: the renderer sets the quantitative-axis baseline to 0
  (`scale.bar_quantitative_axis_zero`, M1.6 renderer) — by construction (the model proposes no
  scale), not a spec check.

## 8. Dataset binding

- `dataset.hash` = `sha256:` + 64 lowercase hex = SHA-256 over the RAW CSV file bytes, exactly
  as stored (sensitive to row order / CRLF / BOM by design = byte-exact SOURCE identity).
- Resolved by `dataset.name` under `data/` ONLY: the name matches
  `^[A-Za-z0-9][A-Za-z0-9._-]*\.csv$` — no path separator and no leading separator, so it is a
  relative single segment. (The pattern still admits a literal `..` substring, e.g. `a..csv`,
  harmless without a separator.) Traversal is prevented by the separator-free pattern PLUS the
  resolved-path-within-`data/` check. `dataset.hash_matches_source` (M1.5) recomputes the source
  hash, confirms path-confinement, and compares; mismatch → block.

## 9. Error layers

- DECODE (M1.2a, `decode_spec`) = SYNTAX: unknown field/op/mark/enum, wrong container/type,
  float/bool/null token, length/pattern breach, duplicate key, malformed or non-UTF-8 JSON.
  Outcome for any `bytes | str` input (the `decode_spec` signature): a total `VPlotSpec`, or
  `msgspec.ValidationError` / `msgspec.DecodeError` — never a partial or coerced object. (A
  non-`bytes|str` argument is a caller type error → `TypeError`, outside this data contract.)
- SEMANTIC (M1.4 eval + M1.5 checks) = MEANING (needs dataset + manifest): field exists, type
  matches, hash matches source, distinctness/collision, filter coercion, encoding type, bar-zero
  baseline, units present. Outcome: structured `{check, status, message, severity}`; any blocking
  failure → no render.

A spec can pass DECODE yet fail SEMANTIC.

## 10. Oracle parity (DuckDB, dev/test)

The oracle (`threads=1`, columns as matching `DECIMAL`) must reproduce the evaluator's canonical
table byte-for-byte on goldens. Conform DuckDB to THESE semantics with explicit constructs (do
not rely on its defaults):
- `mean`: take the EXACT `SUM(col)` (DECIMAL) and `COUNT(col)` (BIGINT) from DuckDB, then do the
  ONE division + HALF_EVEN quantize in PYTHON (identical to the evaluator). Do NOT divide in SQL:
  both `avg()` and `SUM(col)/COUNT(col)` evaluate through DOUBLE, and the cast back to DECIMAL
  rounds HALF-AWAY, not HALF_EVEN (verified: mean(0.00, 0.01) @ scale 2 → SQL 0.01, evaluator
  0.00). SQL contributes only the exact SUM + COUNT.
- sort null placement via explicit `NULLS LAST` (ascending) / `NULLS FIRST` (descending).
- `group_by` NULL = single group; `COUNT(col)` = non-null; `SUM`/`MIN`/`MAX` over all-null =
  NULL — all match by default and are asserted, not assumed.

Any op the oracle cannot match bit-for-bit → a logged tolerance cross-check (dual-engine
determinism), never a silent pass.

## 11. Divergences from the outline (`.agent/outline.md`)

- Labels + units = the trusted MANIFEST, not model- or policy-proposed.
- NO `policy` block: policy folds into M1.5 checks + the manifest (the model proposes no policy).
- Per-key `sort` (a list of `{field, order}`) vs the outline's single sort.
- Named cmp ops (eq/ne/lt/le/gt/ge) vs operator symbols.
- Filter values = `int | string` (no float/Decimal tokens); decimals travel as bounded strings,
  coerced per §3.
- The MODEL-SUPPLIED "derived-value mismatch" check is DROPPED — impossible by construction (the
  model supplies no plotted values, §1). The renderer-inlined-data-equals-recomputation check
  (`transform.aggregates_match_recomputation`, §1) REMAINS in force.

## Open (resolve when the layer lands)

- Filter-literal STRINGS are length-bound (≤ 128) only → they still admit control chars
  (NL/CR/TAB/NUL/U+2028). Canonical handling (forbid-pattern vs NFC + escape-on-disclosure) is
  decided once the M1.4 text model + M1.6 badge format exist; constraining now risks rejecting
  valid filters on legitimate control-char cells.
- A dimensionless `count` on a quantitative channel vs `label.quantitative_units_present` (block
  it, or treat `count` as unit-exempt) — decided when M1.5 lands; no golden uses `count`.
