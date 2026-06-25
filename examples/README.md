# examples — M1.3 golden corpus

Goldens for M1.4 (eval) · M1.5 (checks) · M1.6 (render). `index.json` = machine source of
truth: decode/bind expectations, per-bad-spec `layer`/`check`/`reason`, the by-construction
list. Specs decode via `verifier.schema.decode_spec`; meaning = `VPlot_SEMANTICS.md`.
Enforced by `tests/test_examples.py`.

## Layout
- `good_specs/g01..g10` — 1 per NL chart intent; decode-valid AND semantically valid (M1.4/M1.5 pass-goldens).
- `bad_specs/b01..b18` — each fails exactly ONE way (`index.json.bad_specs[].layer/check/reason`).
- `../data/{sales,weather,deliberately_dirty}.csv` + `../data/schemas/<stem>.json` — CSVs + trusted per-column manifest (`type`, numeric `scale`, optional `unit`/`label`, temporal `granularity`).

## Bad-spec layers (rejection point)
- `decode` (×8) → now, at `decode_spec`. `decodes=false`. Bad enum/op/fn, float value, unknown key, wrong version, Vega-Lite injection keys (`encoding.aggregate`, top-level `url`) refused by `forbid_unknown_fields`.
- `dataset-binding` (×4) → M1.4/M1.5. Missing field, `dataset.hash` mismatch, sum-on-string, int-vs-string filter. `decodes=true`.
- `encoding` (×3) → M1.5. Axis-type mismatch, field absent from plotted table, missing y-unit.
- `transform` (×3) → M1.4. group_by placement (§4), aggregate-`as`/group-key collision (§5), sort-field distinctness (§5).

## By construction — no bad spec (`index.json.enforced_by_construction`)
`aggregates_match_recomputation` · `filters_declared` · `scale.bar_quantitative_axis_zero` ·
`legend_domain_matches_data` are unrepresentable as a model spec (the verifier recomputes all
data; the renderer owns scales + legend). `derived_value_mismatch` is dropped — the model
emits no plotted values.

## Data notes
`month` = `YYYY-MM` string → encoded `ordinal` (lexical = chronological; semantics temporal is
`YYYY-MM-DD`/datetime only, §2). `weather.date` exercises `temporal`. `region`/`city` value
`NA` = literal string, never null (only an empty cell is null, §2). `aqi` is deliberately
unit-less (the B13 missing-unit fixture). `deliberately_dirty.csv` = the null/edge fixture for
M1.4 (empty cells across numeric + string + group key; still loadable).
