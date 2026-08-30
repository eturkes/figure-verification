# examples — golden corpus

Goldens for eval · checks · render. `index.json` = machine source of
truth: decode/bind expectations, per-bad-spec `layer`/`check`/`reason`, the by-construction
list. Dataset specs decode via `verifier.schema.decode_spec`, formula specs via
`verifier.schema.decode_formula_spec`; meaning = `VPlot_SEMANTICS.md` Part A (dataset) + Part B
(formula). Enforced by `tests/test_examples.py` + `tests/test_examples_formula.py`.

## Dataset-mode layout
- `good_specs/g01..g10` — 1 per NL chart intent; decode-valid AND semantically valid (eval + checks pass-goldens).
- `bad_specs/b01..b18` — each fails exactly ONE way (`index.json.bad_specs[].layer/check/reason`).
- `../data/{sales,weather,deliberately_dirty}.csv` + `../data/schemas/<stem>.json` — CSVs + trusted per-column manifest (`type`, numeric `scale`, optional `unit`/`label`, temporal `granularity`).

## Formula mode — contract corpus
- `formula_good_specs/f01..f06` — six decode-valid rational-profile functions: square · line · cubic · rational · absolute value · quadratic; line/scatter only.
- `formula_bad_specs/fb01..fb20` — each fails exactly one declared layer (`index.json.formula_bad_specs[].layer/check/reason`).
- Rejection points: `decode` (×14) → `decode_formula_spec`, `decodes=false`; later (×6), still decode by design → parser (×2), evaluation/sampling (×2), domain (×1), exponent policy (×1).
- Check ORDER is load-bearing, so `check` names the FIRST failing check: `formula.domain_ordered` precedes `formula.sample_points_strictly_increasing`, since a reversed domain always produces a descending schedule and no fixture can isolate one from the other. Evaluation must check ordering first, or fb17 stops discriminating.
- The verifier AUTHORS the matplotlib script and never runs it. No certified formula script has run in the Open WebUI sandbox; M10 gates that execution.

## Dataset-mode bad-spec layers (rejection point)
- `decode` (×8) → now, at `decode_spec`. `decodes=false`. Bad enum/op/fn, float value, unknown key, wrong version, Vega-Lite injection keys (`encoding.aggregate`, top-level `url`) refused by `forbid_unknown_fields`.
- `dataset-binding` (×4) → eval + checks. Missing field, `dataset.hash` mismatch, sum-on-string, int-vs-string filter. `decodes=true`.
- `encoding` (×3) → checks. Axis-type mismatch, field absent from plotted table, missing y-unit.
- `transform` (×3) → eval. group_by placement (§4), aggregate-`as`/group-key collision (§5), sort-field distinctness (§5).

## By construction — no bad spec (`index.json.enforced_by_construction`)

### Dataset mode

`security.no_arbitrary_code` · `transform.ops_allowed` hold because a `VPlotSpec` is data-only
(no expression, code, or URL field) and the transform tagged union admits only {select, filter,
group_by, aggregate, sort}. `transform.aggregates_match_recomputation` ·
`transform.filters_declared` hold because the verifier recomputes all plotted data from declared
transforms; dataset specs carry no plotted values.

### Formula mode

`security.no_arbitrary_code` records the only path: formula text can reach evaluation through the
closed verifier-owned AST interpreter, which never executes it as Python.
`formula.points_from_recomputation` records that the evaluator produces the sampled table and the
spec carries no candidate points. `formula.rounding_unambiguous` records the single fixed
rational-HALF_EVEN rule applied deterministically to x and y quantization.

## Pre-render formal checks (`index.json.formally_checked`)

### Dataset mode

`sort.canonical_order` · `scale.bar_zero` · `encoding.legend_domain_exact` consume the exact
Vega builder artifact and block row-order, bar-baseline, or discrete-domain corruption before
native Vega. VCert v0.2 records these and every deterministic dataset pass with its method.

### Formula mode

`sort.canonical_order` consumes exact x ranks from `FormulaEvidence`; UNSAT establishes that sampled
x values are nondecreasing in ascending order. Equality is not an inversion; evaluator sampling
alone establishes strict increase. `scale.bar_zero` and `encoding.legend_domain_exact` are
inapplicable because formula mode admits only line/scatter and has no color channel, bar baseline,
or legend domain.

## Dataset-mode data notes
`month` = `YYYY-MM` string → encoded `ordinal` (lexical = chronological; semantics temporal is
`YYYY-MM-DD`/datetime only, §2). `weather.date` exercises `temporal`. `region`/`city` value
`NA` = literal string, never null (only an empty cell is null, §2). `aqi` is deliberately
unit-less (the B13 missing-unit fixture). `deliberately_dirty.csv` = the null/edge fixture for
eval (empty cells across numeric + string + group key; still loadable).
