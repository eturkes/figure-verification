# VPlot — semantics

Schema is syntax; this is meaning. VPlot has TWO decode gates, one per MODE: `decode_spec` +
`schema/vplot-0.1.schema.json` for DATASET mode (`vplot-0.1`), `decode_formula_spec` +
`schema/vplot-formula-0.1.schema.json` for FORMULA mode (`vplot-formula-0.1`). Each gate settles
shape, types, enums, bounds. **This file is the MEANING contract for both modes** — evaluator,
checks, renderer, script emitter, and both dev/test oracles conform to it. Boundary + the modest
claim: `POC_SCOPE.md`.

A spec that passes its decoder is syntactically total (every field present, typed, never coerced).
Semantics add MEANING rules that need inputs the decoder never sees, so they run post-decode
(eval + checks). Decode-valid ⊉ semantically-valid in BOTH modes: a well-formed dataset spec
naming a missing column decodes, then blocks; a well-formed formula spec naming a disallowed
function decodes, then blocks. Neither renders.

**Mode split.** Part A = DATASET meaning (`§1`–`§11` + settled decisions): a proposed transform
pipeline over a trusted CSV + manifest. Part B = FORMULA meaning (`§F1`–`§F9`): a proposed
expression sampled over a declared domain. Every section names its mode in its own heading and
nothing here is mode-neutral. A dataset rule NEVER transfers to formula mode by default — where
the modes agree, Part B states the agreement explicitly.

## Part A — dataset mode (`vplot-0.1`)

### 1. Trust spine — dataset mode

- The untrusted model emits ONLY the spec: `transform` + `encoding` + declared `dataset.hash`.
  Never plotted values, labels, units, scales, or policy.
- The trusted verifier recomputes ALL plotted data from the source CSV; the renderer inlines
  ONLY that recomputed table → a model-supplied PLOTTED value cannot reach `data.values`
  (impossible by construction, not a check). Model-supplied spec PARAMETERS (filter literals,
  field names, channel types) shape the selection and are disclosed in the badge — never inlined
  as mark data. `transform.aggregates_match_recomputation` is an AFFIRMATION (constant pass): `verify`
  recomputes the table (correctness oracle-backed) and the renderer inlines ONLY that
  recomputation, so no model value can diverge -- true by construction, NOT an active
  byte-comparison (`verify_run()` retains the recomputation only in check-passed internal
  evidence; core `render()` reads the source once, `prepare_render()` binds the decoded spec to
  that evidence, serializes its `plotted_table` once, and formally checks facts from the same
  builder object; `render_prepared()` consumes only a passing artifact's exact Vega-Lite bytes
  without reopening the live dataset or rebuilding/re-solving).
- Only allowlisted ops decode → `transform.ops_allowed` + `security.no_arbitrary_code` hold by
  construction: dataset mode admits no `eval`/`exec`/SQL/JS/free-form-expression path. This
  affirmation is DATASET-ONLY and never transfers — formula mode's input IS an expression, and
  `§F1` states its separately worded safety claim.
- Checks prove mechanical consistency (spec ↔ encoding ↔ binding), NOT representativeness or
  intent: a valid cherry-picked `filter` passes. The VCert badge discloses every
  applied filter and active sort, so a reader sees the selected subset; the verifier guarantees the
  chart faithfully shows that selection, not that the selection is fair.
- VCert v0.2 binds the exact emitted Vega-Lite bytes alongside dataset, manifest, canonical spec,
  and recomputed-table hashes. Its `checks` reproduce every passing final result as
  `{id, method, status:"pass"}` in report order; its TCB stamps verifier + Z3 versions as well as
  canonicalization/display versions. The service signs those exact canonical payload bytes and
  their application type into deterministic one-signature DSSE. `plot_id` hashes the complete
  envelope, so changing bound bytes, a stamped version, or the signing key changes service plot
  identity. `keyid` remains an unauthenticated hint; authenticity requires an independently pinned
  Ed25519 public key.
- Axis titles + units = trusted manifest, never the spec (their VALUE is correct by
  construction). `label.quantitative_units_present` still ENFORCES that a unit is present
  per quantitative channel — manifest units are optional, so presence is checked, not given.
  A quantitative channel tracing (via §7 position-aware reverse lineage) to a `count` is
  dimensionless → unit-exempt; every other quantitative channel must resolve to a manifest numeric
  column that declares a `unit`.

### 2. Data model — dataset mode

- Source = a CSV under `data/`. Cells parse as TEXT, then coerce to the column's MANIFEST
  type (a CSV alone carries no types/units/labels). The manifest is the trusted column
  schema; it is hashed into the VCert.
- Column types: `numeric` (scale s ≥ 0 decimal places; integer = scale 0), `temporal`
  (canonical zero-padded ISO-8601 — date `YYYY-MM-DD` or datetime `YYYY-MM-DDThh:mm:ss[.ffffff]`,
  the `.ffffff` present iff sub-second ≠ 0 so each instant has ONE form — `.000000` is
  non-canonical; granularity per manifest; lexical order = chronological), `string` (nominal/ordinal text,
  Unicode after decode).
- ONE null token: an empty cell → null. No other null source. Null prints as a single reserved
  sentinel in the canonical table. NaN never exists (no float math, §3).
- No floats in data OR spec: spec numerics are `int | string` (float/bool/null tokens rejected
  at decode, schema finding 3); column numerics are `Decimal` (§3).

### 3. Numbers + rounding — dataset mode

- Numeric cells → `Decimal` at the column's manifest scale. The cell must be EXACTLY representable
  at scale s (≤ s decimal places); excess precision = a SEMANTIC error — source data is never
  silently rounded (only computed aggregates quantize, below). Integer = scale 0.
- Aggregation is EXACT, then QUANTIZE `ROUND_HALF_EVEN`. Exact summation + count are
  order-independent → hash-stable; `mean` adds ONE final division + quantize (its inputs are
  order-independent, so the result is too — division itself is not associative). No float, no Kahan.
  - `sum` → exact Σ; output scale = input scale.
  - `mean` → (exact Σ) / (non-null count), ONE division, quantize HALF_EVEN to the output
    scale = the input scale (v0.1 declares no separate output scale anywhere).
  - `min`/`max` → exact; output type = input type.
  - `count` → non-null count → integer (scale 0).
- Filter-value coercion — the spec `value: int | string` is coerced to the field's column type
  BEFORE comparison:

  | column | spec int | spec string |
  |---|---|---|
  | numeric | `Decimal(int)` @ scale | `Decimal(string)`, exact at scale; unparsable OR over-precise (> s places) → semantic error |
  | temporal | semantic error | parse canonical ISO; bad format → semantic error |
  | string | semantic error | used verbatim |

  Coercion failure = a SEMANTIC error → block (eval raises, surfaced as a failed check),
  never a silent drop-all. Comparison then happens within one coerced type domain.

### 4. Transform pipeline — dataset mode

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

### 5. Distinctness + collision — dataset mode (semantic, enforced in eval)

- `select.fields` distinct; `group_by.keys` distinct; `sort.by` fields distinct.
- aggregate `as` names: mutually unique AND disjoint from the group keys (no output-column
  collision) — enforced PER AGGREGATE only (`aggregate.output_unique`). Each aggregate REBUILDS
  the schema (group keys ++ measure outputs), so an output name MAY recur across separate
  aggregate ops (e.g. `count(x) as v` then `sum(v) as v`). A backward unit-lineage walk (§7)
  must therefore resolve POSITION-AWARE — latest producer first, each measure input against
  STRICTLY EARLIER aggregates — else it mis-resolves a reused name or fails to terminate.
- Every TRANSFORM-referenced field exists in the CURRENT schema at that pipeline step
  (`schema.fields_exist` — eval ENFORCES it, raising during recompute; `checks.py`
  SURFACES it as a structured result); encoding channels reference existing PLOTTED-table columns
  (`encoding.fields_exist_in_plotted_table`).

### 6. Canonical total ordering — dataset mode (eval)

The plotted table is closed under a TOTAL order so its hash is permutation-invariant:
1. the ACTIVE declared sort — the LAST `sort` op in the pipeline (an earlier `sort` superseded by
   a later one, or discarded by an intervening `aggregate`, does NOT apply); its keys in order +
   direction + null-greatest, THEN
2. every remaining column, in plotted-table column order, ascending null-greatest — a fixed
   tiebreak.

No `sort` op → step 1 is empty and step 2 alone is already total.

An active sort key MUST survive into the plotted table: if a later op (e.g. a `select` after the
`sort`) projects it away, the declared ordering is unrealizable → fail-closed semantic error
(`sort.field_in_plotted_table`).

Any remaining ties fall only between byte-identical rows, so the serialization is identical
regardless of their relative order → the plotted-table hash is permutation-invariant under
input-row permutation. (The dataset hash is NOT permutation-invariant — it is raw source
bytes, §8.)

Before any native render, `sort.canonical_order` (`z3_smt`) independently checks adjacent
rows projected from the exact built `data.values` under the active declared keys + canonical tail.
SAT supplies the lowest inversion; solver uncertainty or resource refusal blocks the artifact.

### 7. Encoding + labels — dataset mode

- A channel = `{field, type}` ONLY (`type` = Vega-Lite channel type; schema key `type` → struct
  `kind`). No model-proposed title/unit/scale/format.
- `type` ↔ plotted-column type (`encoding.axis_types_match_fields`):

  | channel `type` | column type |
  |---|---|
  | quantitative | numeric |
  | temporal | temporal |
  | ordinal | numeric \| string |
  | nominal | string \| numeric |

- `x`, `y` required; `color` optional = a third channel, same rules. For nominal/ordinal color,
  the builder emits an explicit scale domain = distinct non-null recomputed values in canonical
  first-occurrence order (empty/all-null → `[]`). `encoding.legend_domain_exact`
  `z3_smt`) checks set equality between that exact emitted domain and exact built `data.values`;
  missing/extra categories, solver uncertainty, or resource refusal blocks the artifact.
- Axis title = manifest display label + manifest unit appended; the title VALUE is
  manifest-sourced, never model-proposed. `label.quantitative_units_present` verifies the
  manifest supplies a unit for each quantitative channel and BLOCKS when absent (units are optional
  in the manifest — presence is checked, not guaranteed by construction). A channel tracing
  to a `count` is dimensionless → unit-exempt (no inherited unit); every other quantitative channel
  resolves to a manifest numeric column that MUST declare a `unit`.
- A DERIVED plotted column (an aggregate `as`) inherits manifest metadata through its measure to
  the source field — RECURSIVELY and position-aware (§5: a reused output name resolves to its
  LATEST producer, each measure input against strictly earlier aggregates, always terminating):
  `sum`/`mean`/`min`/`max` carry the source `unit` + `label`, so
  `label.quantitative_units_present` resolves a derived quantitative channel through this lineage
  (`count` is dimensionless — no inherited unit). A group_by KEY keeps its source column's
  metadata; a derived column's numeric scale follows §3.
- `bar` mark: the builder emits `scale.zero=true` on every quantitative positional channel (the
  model proposes no scale). `scale.bar_zero` (`z3_smt`) reads the exact built mark/channels
  and blocks a missing/false baseline, solver uncertainty, or resource refusal before native Vega.

### 8. Dataset binding — dataset mode

- `dataset.hash` = `sha256:` + 64 lowercase hex = SHA-256 over the RAW CSV file bytes, exactly
  as stored (sensitive to row order / CRLF / BOM by design = byte-exact SOURCE identity).
- Resolved by `dataset.name` under `data/` ONLY: the name matches
  `^[A-Za-z0-9][A-Za-z0-9._-]*\.csv$` — no path separator and no leading separator, so it is a
  relative single segment. (The pattern still admits a literal `..` substring, e.g. `a..csv`,
  harmless without a separator.) Traversal is prevented by the separator-free pattern PLUS the
  resolved-path-within-`data/` check. `dataset.hash_matches_source` recomputes the source
  hash, confirms path-confinement, and compares; mismatch → block.

### 9. Error layers — dataset mode

- DECODE (`decode_spec`) = SYNTAX: unknown field/op/mark/enum, wrong container/type,
  float/bool/null token, length/pattern breach, duplicate key, malformed or non-UTF-8 JSON.
  Outcome for any `bytes | str` input (the `decode_spec` signature): a total `VPlotSpec`, or
  `msgspec.ValidationError` / `msgspec.DecodeError` — never a partial or coerced object. (A
  non-`bytes|str` argument is a caller type error → `TypeError`, outside this data contract.)
- RESOURCE POLICY (`resource.*`) = inclusive logical ceilings over trusted inputs and later
  work/artifacts. Admission at the ceiling proceeds; the first ceiling+1 observation surfaces its
  tagged failure before work at that boundary. Core verification covers raw manifest/CSV bytes,
  manifest columns, source rows/cells, deterministic evaluator work, and final plotted cells.
  Rendering/service boundaries additionally cover render rows/artifact bytes, SMT term count/time,
  request/prompt/model response bytes, prompt tokens, request rate, active jobs, and transactional
  logical archive payload. Evaluator work units are deterministic
  logical-visit formulas declared in `eval.py`, not elapsed-time or CPU guarantees.
- SEMANTIC (eval + checks) = MEANING (needs dataset + manifest): field exists, type
  matches, hash matches source, distinctness/collision, filter coercion, encoding type, units
  present. Outcome: structured `{check, method, status, severity, message}`; any
  blocking failure → no render. Each result carries the closed verification method that established
  it: `schema_validation`, `resource_policy`, `deterministic_recompute`, `construction`, or
  `z3_smt`. A passing result's ID + method enter VCert v0.2 verbatim; there is no name-only
  certificate compatibility field.

A spec can pass DECODE yet fail RESOURCE POLICY or SEMANTIC.

### 10. Oracle parity — dataset mode (DuckDB, dev/test)

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

Every v0.1 op reproduces bit-for-bit (goldens + adversarial synthetic parity). Outside
DuckDB's DECIMAL(38)/HUGEINT domain — where eval's unbounded exact arithmetic still succeeds —
the oracle raises LOUDLY (filter-literal magnitude bound; SUM-accumulator or typed-reinsert
overflow, both sites pinned by tests), never a silent divergence.

### 11. Divergences from the outline — dataset mode (`.agent/outline.md`)

- Labels + units = the trusted MANIFEST, not model- or policy-proposed.
- NO `policy` block: policy folds into checks + the manifest (the model proposes no policy).
- Per-key `sort` (a list of `{field, order}`) vs the outline's single sort.
- Named cmp ops (eq/ne/lt/le/gt/ge) vs operator symbols.
- Filter values = `int | string` (no float/Decimal tokens); decimals travel as bounded strings,
  coerced per §3.
- The MODEL-SUPPLIED "derived-value mismatch" check is DROPPED — impossible by construction (the
  model supplies no plotted values, §1). The renderer-inlined-data-equals-recomputation check
  (`transform.aggregates_match_recomputation`, §1) REMAINS in force.

### Settled decisions — dataset mode (never re-litigate)

- Filter-literal STRINGS stay length-bound (≤ 128) + byte-faithful — control
  chars (NL/CR/TAB/NUL/U+2028) are admitted and handled at DISCLOSURE time (`badge_html` renders
  each literal in a visible INJECTIVE form — int bare, string JSON-quoted ASCII-escaped, so
  control/format/bidi chars display as `\uXXXX` and two distinct literals never render alike —
  then `html.escape(quote=True)`; the offline HTML view escapes every `<` → U+003C). Forbid-pattern
  and NFC both rejected: NFC-folding collides specs that select different rows (the hash must
  distinguish exactly what eval's verbatim compare distinguishes), and a forbid-pattern would
  reject valid filters on legitimate control-char cells.
- A dimensionless `count` on a quantitative channel is unit-exempt vs
  `label.quantitative_units_present` — `unit_source` (§5/§7) returns None for a count-derived
  column (the lineage carries no unit), as stated in §1/§7. Dedicated end-to-end `test_checks.py`
  specs (a direct count and a count→sum chain) plus `unit_source` lineage arms exercise it; no
  good-spec corpus golden uses `count`.

## Part B — formula mode (`vplot-formula-0.1`)

Formula mode plots a model-proposed EXPRESSION sampled over a model-proposed DOMAIN. It reads no
CSV and no manifest, so every Part A rule that depends on a dataset, a column manifest or a
transform pipeline is absent here rather than adapted. Where a Part A rule does carry over, the
section below says so and names it.

### F1. Trust spine — formula mode

- The untrusted model proposes ONLY the formula spec: `version`, `formula`, `domain`,
  `numeric_profile`, `mark`, `encoding` (`schema.py:164-170`). Never point values, never Python,
  never a rendered artifact.
- The verifier owns every stage between that spec and the plotted bytes: strict decode → closed
  parse → exact evaluation → sampling → quantization → semantic + SMT checks → script emission →
  certificate construction → signing → archive (`service/pipeline.py:317-672`). A model-supplied
  PLOTTED value cannot reach the script, because the verifier computes every point it emits —
  impossible by construction, not a check.
- **Formula input is executable expression DATA.** Part A's `security.no_arbitrary_code`
  affirmation — "pure data, no executable path" — does NOT transfer. Formula mode states its own
  claim: the text is LEXED and PARSED into a frozen, allowlisted, verifier-owned AST
  (`expr.py:2-118`), and `eval_expr` INTERPRETS only those node types (`expr.py:621-861`). No
  `eval`, `exec`, `compile` or `ast` path is reachable from the formula surface. The model
  supplies a program the verifier reads; it never supplies a program the host runs.
- The emitted artifact is a matplotlib SCRIPT the VERIFIER authors from a fixed byte template
  (`matplotlib_script.py:39-61`). Only verifier-derived x/y/domain literals vary between two
  emissions of the same template, so model-authored Python cannot enter the script.
- VCert v0.3 binds exactly four hashes for a formula plot — `formula_hash`, `spec_hash`,
  `plotted_table_hash`, `matplotlib_script_hash` — and `FormulaTcb` stamps nine fields:
  `verifier_version`, `z3_version`, `canon_version`, `python`, `msgspec`, `unidata`,
  `grammar_version`, `numeric_profile`, `script_template_version` (`vcert.py:118-268`). It
  EXCLUDES Vega, fonts, matplotlib, the browser and pixels, because the verifier neither renders
  nor executes in this mode.
- **The claim, stated at its true scope.** At every declared SAMPLED x, the closed evaluator
  produced the certified y under the declared numeric + rounding profile, and the emitted script
  inlines exactly those certified points. The claim covers nothing else. It does NOT assert
  finiteness, continuity or monotonicity BETWEEN samples; it does NOT assert that the formula
  matches any natural-language intent the model was asked to satisfy.
- **TCB.** matplotlib, Pyodide, the browser and the pixels stay TRUSTED, never proven. The
  executed script is verifier-authored, so its pixels are trusted-not-proven for exactly the
  reason Part A's SVG pixels are. M9 ships no execution at all — the verifier emits script bytes
  and imports no matplotlib, and no component of this milestone runs the script anywhere.

### F2. Carriers + sampled domain — formula mode

- **Spec carriers.** `FormulaPlotSpec` has exactly six fields (`schema.py:164-170`):
  `version: Literal["vplot-formula-0.1"]`, `formula: FormulaText`, `domain: FormulaDomain`,
  `numeric_profile: Literal["rational-half-even-v1"]`, `mark: Literal["line","scatter"]`,
  `encoding: FormulaEncoding`.
- `FormulaText` is ASCII-only, line-break-free, `≤ 1024` chars, over the v0.1 alphabet
  `[0-9A-Za-z_ ().*/+-]` (`schema.py:28-31`). The alphabet admits no `^`, no `,`, no comparison
  and no string literal.
- **Domain.** `FormulaDomain` has exactly `start`, `stop` (both `DecimalText` — decimal STRINGS,
  never JSON floats, matching Part A `§2`'s no-float rule), `samples` (`int`, decode bound
  `2 ≤ n ≤ 100_000`), `x_scale` and `y_scale` (`int`, `0 ≤ s ≤ 12`) (`schema.py:156-161`).
- **Sample schedule.** For `i = 0 … samples-1`, `xᵢ = quantize(start + i·(stop-start)/(samples-1),
  x_scale)` (`eval.py:240-268`). Both endpoints are sampled: `x₀ = quantize(start)` and
  `x_{samples-1} = quantize(stop)`. Those are the QUANTIZED endpoints — where `start` carries more
  decimal places than `x_scale`, `x₀ ≠ start`, by design.
- **Decode settles SHAPE alone.** Domain ordering, decimal representability, grammar,
  name/function/exponent admissibility and sample distinctness are all SEMANTIC checks, never
  struct post-init validation (`schema.py:154-155`). A domain whose `stop` precedes its `start`
  decodes cleanly, then blocks at `§F5`.
- **Decode bounds are not the operative ceilings.** The decoder's `samples ≤ 100_000` and
  `FormulaText ≤ 1024` are shape bounds; the operator's resource policy binds tighter and refuses
  first (`§F7`).
- **Formula mode reads no dataset.** The formula schema declares no CSV, manifest or
  `dataset.hash` field, and the formula pipeline accepts only a spec plus settings
  (`service/pipeline.py:317-324`). The formula attempt projection carries no `raw_csv` and no
  `raw_manifest` (`service/pipeline.py:377-397`). Every Part A rule resting on a dataset or a
  column manifest is therefore ABSENT here, not reinterpreted.
- **Canonical source.** `canon.FormulaSource` carries nine fields — `grammar_version`,
  `numeric_profile`, `rounding`, `ast`, `start`, `stop`, `samples`, `x_scale`, `y_scale`
  (`canon.py:102-118`). Two domain-tagged hash identities serve formula mode: `formula` over the
  resolved canonical source, and `matplotlib-script` over the exact emitted script bytes
  (`canon.py:202-293`).
- **Plotted table.** Two numeric columns, `x` then `y`, at the declared `x_scale`/`y_scale`, one
  row per admitted sample, in sample-schedule order (`eval.py:329-355`).

### F3. Exact-`Fraction` numerics + HALF_EVEN quantization — formula mode

- **Evaluation is exact.** Decimal literals and `Decimal` bindings convert directly to `Fraction`,
  and every arithmetic step stays rational (`schema.py:30-39`, `expr.py:692-717`). No evaluator
  API admits a float binding, so no rounding occurs before the single declared quantization.
- **Quantization is exact-integer HALF_EVEN.** It takes the signed integer quotient and remainder
  and constructs the `Decimal` directly (`eval.py:226-238`). Ambient `Decimal` context, float
  arithmetic and string conversion cannot affect the result. This matches Part A `§3`'s
  HALF_EVEN rule and is implemented separately for the rational domain.
- **Two declared scales, one quantization each.** `x_scale` quantizes every schedule position;
  `y_scale` quantizes each exact evaluated result (`eval.py:241-267`, `eval.py:329-346`). Both
  come from `FormulaDomain`, so the model declares them and the certificate binds them.
- **Float enters once, after verification.** The only float in the mode appears when the verified
  exact points project into the emitted script's literals (`matplotlib_script.py:95-105`). `§F6`
  states exactly what is and is not claimed about that projection.
- **One cumulative `WorkBudget` spans the whole run.** Tariff: a successful sample costs 5 units
  plus the AST tariff; a formula `x` reference costs 6 units per sample; `Pow` costs
  `1 + abs(exponent)` (`expr.py:17-21`, `expr.py:744-761`).
- **Charge precedes the guarded operation.** An over-limit charge raises BEFORE incrementing, so
  refused work consumes zero units; an operation that is admitted and then fails retains its full
  charge (`work.py:37-52`).
- **Intermediate size is bounded.** `max_formula_intermediate_bits` inclusively caps the maximum
  numerator/denominator bit width of each reduced rational; a breach reports
  `resource.formula_intermediate_bits` (`expr.py:669-687`). `Pow` preflights its components against
  the same ceiling without allocating the result (`expr.py:744-783`).

### F4. Parse → evaluate → sample pipeline — formula mode

- **Grammar.** `GRAMMAR_VERSION = "expr-0.1"`. A hand-written bounded recursive-descent parser
  produces six frozen msgspec AST variants — `Number`, `Variable`, `Neg`, `Abs`, `Pow`, `Binary`
  (`expr.py:55-121`, `expr.py:458-637`). `Binary` dispatches exactly four members: `add`, `sub`,
  `mul`, `div`.
- **Admitted constructs.** Decimal literals, the allowed variable, grouping, `abs`, unary `+`/`-`,
  binary `+ - * /`, and `**` with a signed INTEGER exponent (`expr.py:462-614`). `abs` is the SOLE
  admitted function.
- **Transcendentals are refused in v0.1** because they are irrational and therefore not exact in
  the declared rational/decimal profile. `sin`, `cos`, `tan`, `exp`, `log` and `sqrt` block on
  `formula.functions_allowed`; `pi` and `e` block on `formula.names_allowed`; both raise
  `VerificationError` (`expr.py:535-556`). **`sqrt` is refused UNCONDITIONALLY** — `sqrt(4)` blocks
  exactly like `sqrt(2)`, because refusal is by NAME at parse time and never inspects the argument.
- **Parse limits: eight, each a policy DEFAULT under an ABSOLUTE ceiling** (`limits.py:49-58`,
  `expr.py:152-162`):

  | limit | default | absolute ceiling |
  |---|---|---|
  | `max_formula_bytes` | 512 | none |
  | `max_formula_tokens` | 256 | none |
  | `max_formula_ast_nodes` | 256 | none |
  | `max_formula_ast_depth` | 32 | 64 |
  | `max_formula_paren_depth` | 32 | 64 |
  | `max_formula_digits` | 32 | 512 |
  | `max_formula_exponent` | 64 | none |
  | `max_formula_identifier_bytes` | 32 | none |

- The ceilings are TRUSTED-CALLER POLICY BOUNDS, not clamps. `_validate_limits` is the first call
  in `parse_expr`, ahead of allowlist, byte and lexing work, and a policy above a ceiling raises a
  native `ValueError` naming the field rather than silently lowering it (`expr.py:199-231`,
  `expr.py:621-637`).
- **Effective envelope.** A left-associative chain's AST height equals its term count, so
  `max_formula_ast_depth` binds a long flat sum FIRST — at the defaults, 32 terms parse and term 33
  raises `resource.formula_ast_depth`. Tokens are not the binding ceiling there: 33 terms spend 65
  of the 256 admitted tokens.
- **Canonical normalization is exactly five rewrites** (`expr.py:10-13`, `expr.py:858-875`):
  whitespace, redundant grouping, decimal-literal spelling as a lowest-terms `Fraction`, unary
  plus, and integer-exponent sign/leading-zero spelling. It performs NO constant folding and NO
  algebraic rewrite. That list is a PROVENANCE claim, not a convenience:
  `canon.FormulaSource.ast` hashes this printed text, so printer injectivity and determinism are
  provenance-critical.
- **Stage order.** A formula run evaluates `security.no_arbitrary_code`, then the four formula
  postconditions, then the two encoding checks, then `sort.canonical_order`, then the five render
  checks — 13 checks on the success path (`checks.py:643-689`, `formula_prepare.py:75-110`,
  `matplotlib_script.py:157-234`). A failure surfaces at its own guard and short-circuits every
  downstream stage, so a blocked run reports fewer than 13 results. `§F7` lists the IDs.

### F5. Sampled ordering + strictness authority — formula mode

- **Row order = the sample schedule.** Formula rows follow the strictly increasing sampled-x
  schedule (`eval.py:329-355`). There is no canonical re-sort, because the schedule is already the
  only order and it derives deterministically from the declared domain.
- **The formula table hash is order-sensitive.** Part A `§6` closes the DATASET table under a
  canonical TOTAL ORDER, which is what makes its hash permutation-invariant under input-row
  permutation. Formula mode needs no such closure and does not have one: typed-NDJSON preserves row
  sequence (`canon.py:174-190`), so reordering two rows changes `plotted_table_hash` — swapping
  f02's first two rows moved it from `6f9187…` to `0a17b7…`.
- **Two ordering authorities, deliberately different strengths.**
  - `formula.sample_points_strictly_increasing` (`deterministic_recompute`) is the SOLE
    strictly-increasing authority. It rejects every quantized `xᵢ` that is not greater than its
    predecessor (`eval.py:270-290`). Quantization at `x_scale` can collapse two distinct exact
    positions onto one decimal, and this check is what refuses that run.
  - `sort.canonical_order` (`z3_smt`) searches adjacent sampled-x ranks for an ascending inversion
    and proves NONDECREASING x only — it admits equality on purpose (`formula_prepare.py:2-9`,
    `formula_prepare.py:44-72`, `formal.py:285-296`). It proves nothing about y and nothing about
    behavior between samples.
- **Check order is a corpus obligation.** `formula.domain_ordered` runs before schedule
  construction (`eval.py:309-337`). Every reversed domain also yields a descending schedule, so no
  supported fixture isolates a strictness failure from an ordering failure. That is an
  input-coupled REACHABILITY limit, not a weaker ordering guarantee.

### F6. Fixed quantitative encoding + script emission — formula mode

- **Encoding is FIXED**, not proposed: `x` and `y`, both `quantitative`, with the literal field
  names `x` and `y` (`schema.py:82-95`). Formula mode admits no color channel, no
  ordinal/nominal/temporal channel type, and no model-supplied title, unit, scale or format. `mark`
  is `line` or `scatter` — never `bar`.
- **Three dataset checks have NO formula counterpart** because their inputs do not exist here
  (`schema.py:52-95`, `formula_prepare.py:92-99`): `label.quantitative_units_present` (no manifest,
  so no units), `encoding.legend_domain_exact` (no color channel, so no legend domain), and
  `scale.bar_zero` (no bar mark). Their absence is by construction, not an unchecked gap.
- **Script emission.** `SCRIPT_TEMPLATE_VERSION = "matplotlib-script-0.1"`. The verifier-recomputed
  `Decimal` rows become shortest-round-trip float literals inserted into the template's fixed x/y
  lists (`matplotlib_script.py:37-61`, `matplotlib_script.py:108-154`).
- **Float64 fidelity, at its exact scope.** Every projected point and endpoint round-trips at its
  declared decimal scale, and projected x stays strictly increasing
  (`matplotlib_script.py:95-137`, `matplotlib_script.py:199-216`). This is NOT binary64 identity,
  NOT pixels, and NOT execution.
- **Nothing executes the script in M9.** The verifier imports no matplotlib and executes no script;
  it emits bytes. Only M10's sandbox may execute the canonical verifier-authored
  `matplotlib-script-0.1` carrier, and no other Python.

### F7. Error layers — formula mode

The three-layer split of Part A `§9` holds, but each layer has different members here.

- **DECODE** (`decode_formula_spec`) = SYNTAX. A dedicated strict decoder plus a duplicate-key
  rescan; the outcome is a total `FormulaPlotSpec`, or `msgspec.ValidationError` /
  `msgspec.DecodeError` mapped to a decode verdict (`schema.py:177-251`,
  `service/pipeline.py:303-315`). Decode settles SHAPE alone — `§F2`.
- **RESOURCE POLICY** = inclusive logical ceilings. Formula mode adds ELEVEN
  (`checks.py:69-92`): `resource.formula_bytes`, `resource.formula_tokens`,
  `resource.formula_ast_nodes`, `resource.formula_ast_depth`, `resource.formula_paren_depth`,
  `resource.formula_digits`, `resource.formula_identifier_bytes`, `resource.formula_samples`,
  `resource.formula_work`, `resource.formula_intermediate_bits`,
  `resource.matplotlib_script_bytes`. The shared plotted-cell, render-row, SMT-term and attestation
  ceilings apply on top.
  - `resource.matplotlib_script_bytes` measures the EXACT emitted script length and admits equality
    at the ceiling (`matplotlib_script.py:216-222`). The script is therefore BUILT before the
    ceiling can refuse it: a 483-byte script exists in memory when a 482-byte ceiling rejects the
    run.
- **SEMANTIC** = MEANING. `evaluate_formula_run` wraps a parser or evaluator `VerificationError`
  with its check ID and the work consumed; `verify_formula_run` converts that into ONE blocking
  result and mints no evidence (`eval.py:292-307`, `checks.py:643-661`).
- **Check inventory — 28 formula-specific IDs** (`checks.py:65-125`): the twelve `formula.*` IDs
  (`grammar_allowed`, `functions_allowed`, `names_allowed`, `exponents_bounded`, `domain_ordered`,
  `domain_bounded`, `sample_points_strictly_increasing`, `values_defined`, `values_bounded`,
  `hash_matches_source`, `points_from_recomputation`, `rounding_unambiguous`), the eleven resource
  IDs above, and five `render.*` IDs (`float64_fidelity`, `axes_linear`, `x_domain_exact`,
  `points_match_evidence`, `matplotlib_script_allowlisted`).
- **Methods are assigned by MECHANISM, never by ID prefix.** `formula.exponents_bounded` is
  `schema_validation` despite bounding a magnitude; `formula.values_bounded` is
  `deterministic_recompute`; `formula.points_from_recomputation` and
  `formula.rounding_unambiguous` are `construction`. There is NO candidate-point match check, in
  any method (`checks.py:61-128`).
- **Register only a check ID whose emitter already exists.** Registration commits the project to
  emitting that ID, so a planned-but-unemitted ID stays unregistered and refusal-pinned.
- **A verified formula certificate is all-pass by construction.** The builder refuses every
  non-passing formula artifact, so a mixed-STATUS certificate is unreachable through any supported
  flow and reaching one needs forgery. The certified set is 13 checks over exactly three methods:
  `{construction, deterministic_recompute, z3_smt}`.
- A failing formula run blocks the artifact. The verdict-level claim about which responses return
  or archive a script belongs to the service boundary and is stated in `POC_SCOPE.md`; this file
  does not restate it.

### F8. Oracle boundary — formula mode

- The formula oracle is `tests/formula_oracle.py::evaluate_formula_oracle` (dev/test only). Part A
  `§10`'s DuckDB parity is DATASET-only and has no formula counterpart — DuckDB never sees a
  formula.
- **Independence is partial and stated.** The oracle evaluates by iterative postorder with its own
  integer HALF_EVEN rounding, importing neither the production evaluator nor its work meter
  (`tests/formula_oracle.py:1-12`, `tests/formula_oracle.py:155-236`). It deliberately SHARES the
  production parser AST and the contract carrier types, so it is an independent EVALUATOR and not
  an independent parser.
- **What agreement evidences.** The campaign compares end-to-end public evaluator output — the
  table and the check results. Agreement therefore evidences public-entry outcome equality and says
  nothing about any individual internal admission site
  (`tests/test_eval_formula_oracle.py:2-9`, `tests/test_eval_formula_oracle.py:421-458`).
- **The oracle ignores work accounting on purpose**, so it computes no tariff and no `work_units`.
  A run the production evaluator refuses with `resource.formula_work` while the oracle completes is
  an EXPECTED ONE-SIDED outcome, and the suite classifies it as such
  (`tests/test_eval_formula_oracle.py:790-798`). Counting a one-sided outcome as agreement, or as
  divergence, would both misreport the boundary.

### F9. Settled decisions — formula mode (never re-litigate)

- **Transcendentals stay out of v0.1** because they are irrational and therefore not exact in a
  Decimal/rational profile. Polynomial and rational expressions — the "basic math plot" case — are
  fully covered. A transcendental profile is a separately VERSIONED, interval-certified future
  profile: evaluate directed lower and upper bounds, quantize both, accept only on agreement, and
  otherwise raise precision within budget or fail. **Agreement between two precisions is NOT a
  correct-rounding proof**, which is why the profile must be versioned rather than bolted on.
- **The expression engine is REUSABLE, not formula-only.** `parse_expr` + `eval_expr`, the frozen
  AST, exact `Fraction` semantics, the caller-supplied allowlist and the cumulative work budget are
  consumer-neutral (`expr.py:2-23`, `expr.py:621-637`, `expr.py:837-853`). Domain sampling, the `x`
  binding, table construction, canonical-source construction, the SMT obligation and script
  emission are FORMULA-ONLY wrappers (`eval.py:309-371`). A future consumer that binds different
  names inherits the same exactness, quantization and allowlist discipline without inheriting the
  sampling wrapper.
- **An equivalent respelling does not certify identically, and the reason is narrow.** `2*x + 1`
  and `2 * x+1` produce the same canonical AST, so they share THREE of the four certified
  digests — `formula_hash`, `plotted_table_hash` and `matplotlib_script_hash` — because each
  derives from the canonical AST and the recomputed points, and the emitted script embeds no
  submitted text. They differ in `spec_hash`, in the VCert payload and in every derived id, because
  the canonical spec preserves the SUBMITTED text (`eval.py:350-369`, `canon.py:252-281`).
  `spec_hash` is the SOLE spelling-sensitive certified digest.
- **Canonicalization normalizes spelling, never algebra.** `x*2` and `2*x` are DIFFERENT canonical
  sources, because normalization performs no commutative reordering and no constant folding
  (`§F4`). Only the five listed rewrites collapse two texts onto one canonical form.
- **The evaluator owns the only work meter.** The parser is bounded structurally — bytes, tokens,
  nodes, depth, parentheses, digits, and the fixed digit ceiling — and charges nothing to
  `max_formula_work_units`. A second parser meter adds no guarantee and would collide with the
  evaluator's cumulative authority.
- **The emitted script is never self-scanned.** A post-emission allowlist scan over bytes the
  verifier itself authored from a fixed template duplicates the same authority and adds no
  independent assurance.
