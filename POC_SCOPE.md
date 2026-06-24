# POC_SCOPE — verified-plot PoC

A weak local LLM proposes a restricted JSON chart spec (VPlot). A separate trusted
verifier independently recomputes the plotted data from the source CSV, runs
structured checks, blocks charts whose spec, data binding, or encoding fail those
checks, and renders only the rest with a provenance certificate. This document fixes
the boundary.

## What kinds of plots are allowed?

`bar` · `line` · `scatter`

## What transformations are allowed?

- `select` — choose fields
- `filter` — keep rows by an explicit, declared predicate
- `group_by` — group by one or more keys
- `aggregate` — `sum` · `mean` · `count` · `min` · `max`
- `sort` — order rows by declared key(s) and direction

## What does verification mean for this PoC?

The untrusted model proposes ONLY a VPlot spec — transforms, encoding, and a declared
source-dataset hash — never plotted values. "Verified" means these four artifacts are
mutually consistent and every check passed:

1. the spec validated against the VPlot v0.1 DSL (unknown fields, ops, and marks are
   rejected before any computation runs);
2. the plotted table the verifier recomputed independently from the source CSV;
3. the emitted Vega-Lite, which inlines only that recomputed table;
4. the provenance badge: dataset hash, spec hash, plotted-table hash, passed checks.

Because the renderer only ever receives verifier-recomputed data, a chart cannot
display model-supplied numbers — that class of lie is impossible by construction, not a
check. Checks instead target spec, encoding, policy, and dataset-binding consistency:
fields exist in the plotted table, axis types match their fields, a bar chart's
quantitative axis includes zero, a quantitative axis carries the unit the trusted
column manifest declares for its field, the declared dataset hash matches the source
bytes, and only allowlisted ops ever reach the evaluator.

The emitted Vega-Lite carries no data transforms of its own — no encoding-level
aggregate, bin, stack, impute, or sort, no scale-domain override, no top-level
`transform`, and implicit stacking and sorting switched off — so the marks show exactly
the recomputed rows, nothing re-derived downstream.

What verification does NOT cover: representativeness or intent. A spec that filters to
an unflattering-but-real subset, or picks a valid-but-misleading encoding, still passes
every check — honest selection is the author's job. The badge records the full spec,
every filter and sort included, so a reader can see which rows were chosen; the verifier
guarantees the chart faithfully shows that selection, not that the selection is fair.

## What is intentionally not supported?

arbitrary Python · arbitrary SQL · custom JavaScript · free-form Vega expressions ·
Vega-Lite's own data transforms (aggregate, bin, stack, impute, sort, scale-domain
override) · map charts · faceting · interaction · dashboards · multi-source joins.

## The line we hold (trusted computing base)

Trusted but NOT formally verified: `vl-convert` and the Vega runtime, SVG
rasterization, the browser, and the final pixels — trusted to render verified data
faithfully, not proven to. The claim is about the data-and-spec layer, not the renderer
or what reaches the screen.
