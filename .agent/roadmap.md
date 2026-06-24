This PoC is a local Open WebUI agent that uses a small, possibly unreliable local model only to propose chart specifications, while a separate verifier service deterministically checks those specs against a restricted formal plotting DSL, recomputes the plotted data from the source dataset, blocks invalid or misleading charts, and renders only verified plots with a certificate showing the dataset hash, spec hash, and passed checks.

## PoC milestone sequence

### Milestone 0 — Define the narrow PoC boundary

Scope the first PoC to three chart types and five transforms.

Charts:

```text
bar
line
scatter
```

Transforms:

```text
select fields
filter rows
group_by
aggregate: sum, mean, count, min, max
sort
```

Explicitly exclude arbitrary Python, arbitrary SQL, custom JavaScript, free-form Vega expressions, map charts, faceting, interaction, dashboards, and multi-data-source joins.

Deliverable: a one-page `POC_SCOPE.md`.

Exit criteria:

```text
The system can answer:
- What kinds of plots are allowed?
- What transformations are allowed?
- What does verification mean for this PoC?
- What is intentionally not supported?
```

The key claim should be modest: “This PoC verifies that a rendered chart’s plotted data, encodings, filters, and labels match a restricted formal plot spec over a concrete dataset.” Do not yet claim that the browser renderer, Vega runtime, or pixels are formally verified.

---

### Milestone 1 — Create the local stack

Set up four local components:

```text
Open WebUI
Ollama or another local model backend
verified-plot API server
test dataset directory
```

Open WebUI can be started with Docker or Python, and its docs show Docker and `pip` startup paths. ([Open WebUI][1]) Open WebUI’s Ollama integration is designed around the Ollama API, typically on port `11434`, and its settings UI can manage the connection and pull models. ([Open WebUI][3])

Recommended repo shape:

```text
verified-plot-poc/
  docker-compose.yml
  verifier/
    app.py
    vplot_schema.py
    evaluator.py
    verifier.py
    renderer.py
  openwebui/
    verified_plot_tool.py
    verified_plot_filter.py
  data/
    sales.csv
    weather.csv
    deliberately_dirty.csv
  examples/
    good_specs/
    bad_specs/
  tests/
    test_schema.py
    test_evaluator.py
    test_verifier.py
    test_renderer.py
```

Exit criteria:

```text
- Open WebUI is running locally.
- A small local model is available.
- A FastAPI verifier service responds to GET /health.
- Tests can run with pytest.
```

---

### Milestone 2 — Build two tiny datasets and golden chart intents

Use synthetic data first. Avoid uploaded real-world files until the verification pipeline works.

Example `sales.csv`:

```csv
month,region,revenue,orders
2026-01,NA,12000,80
2026-01,EU,9000,61
2026-02,NA,15000,93
2026-02,EU,11000,70
2026-03,NA,13000,88
2026-03,EU,14000,86
```

Create 10 chart intents:

```text
1. Show total revenue by month.
2. Compare revenue by region.
3. Show order count by month.
4. Plot revenue versus orders.
5. Show average revenue by region.
```

Then create known-good specs and known-bad specs.

Bad specs should include:

```text
- references a nonexistent field
- uses the wrong aggregation
- filters out rows without declaring the filter
- claims y-axis is revenue but plots orders
- omits unit in y-axis title
- uses non-zero baseline for bar chart
- sorts categories differently than declared
- plots a derived value that does not match recomputation
```

Exit criteria:

```text
- At least 5 good specs pass.
- At least 10 bad specs fail.
- Each bad spec fails with a specific reason.
```

This is where the weak local model becomes useful later: its mistakes should look like these bad specs.

---

### Milestone 3 — Define `VPlot v0.1`

Create a small JSON DSL. Use Pydantic models or JSON Schema for validation; Pydantic supports type-hint-driven validation and JSON Schema generation, which is a practical way to define the first executable schema. ([Pydantic][4])

Example `VPlot`:

```json
{
  "version": "vplot-0.1",
  "dataset": {
    "name": "sales.csv",
    "hash": "sha256:..."
  },
  "transform": [
    {
      "op": "group_by",
      "keys": ["month"]
    },
    {
      "op": "aggregate",
      "measures": [
        {
          "field": "revenue",
          "fn": "sum",
          "as": "total_revenue"
        }
      ]
    },
    {
      "op": "sort",
      "by": ["month"],
      "order": "ascending"
    }
  ],
  "mark": "bar",
  "encoding": {
    "x": {
      "field": "month",
      "type": "temporal",
      "title": "Month"
    },
    "y": {
      "field": "total_revenue",
      "type": "quantitative",
      "title": "Revenue, USD",
      "scale": {
        "zero": true
      }
    }
  },
  "policy": {
    "filters_must_be_declared": true,
    "bar_y_axis_must_start_at_zero": true,
    "quantitative_axes_require_units": true
  }
}
```

Exit criteria:

```text
- Valid specs parse into typed objects.
- Invalid specs fail before any rendering.
- Unknown fields, unknown transforms, unknown chart types, and unsupported expressions are rejected.
```

The important design decision: the local model may propose `VPlot`, but it never gets to execute code.

---

### Milestone 4 — Implement the deterministic evaluator

Implement `eval_vplot(spec, dataset) -> plotted_table`.

This is the trusted computation path. It should recompute the data that the chart is allowed to display.

For the PoC, pandas is fine. DuckDB is also a good candidate if you want SQL-like local analytics over CSV/Parquet; its Python API can read CSV, Parquet, and JSON inputs directly. ([DuckDB][5])

Evaluator responsibilities:

```text
- Load dataset.
- Compute dataset hash.
- Infer or validate schema.
- Apply declared transforms only.
- Produce canonical plotted table.
- Hash plotted table.
```

Canonicalization matters. Sort columns, sort rows deterministically, normalize numeric precision, normalize nulls, and produce stable hashes.

Exit criteria:

```text
- Good specs produce exactly reproducible plotted tables.
- Dataset hash changes when source data changes.
- Plotted table hash changes when transform logic changes.
- Golden tests compare expected plotted tables row-for-row.
```

---

### Milestone 5 — Implement verification checks v0

Start with deterministic checks before SMT or Lean.

Verification checks:

```text
schema.fields_exist
schema.field_types_match
transform.ops_allowed
transform.aggregates_match_recomputation
transform.filters_declared
encoding.fields_exist_in_plotted_table
encoding.axis_types_match_fields
encoding.legend_domain_matches_data
scale.bar_y_zero
label.quantitative_units_present
security.no_arbitrary_code
```

Example failure object:

```json
{
  "check": "transform.aggregates_match_recomputation",
  "status": "fail",
  "message": "Plotted value for month=2026-02 was 14000, expected 26000 from source rows.",
  "severity": "block"
}
```

Exit criteria:

```text
- Verifier returns structured pass/fail results.
- Each failed check gives a user-readable reason.
- Renderer is not called if any blocking check fails.
- Tests cover every failure category.
```

At this stage, “formal spec” means the allowed DSL and its executable semantics are explicit and machine-checked. Full proof-assistant verification can come later.

---

### Milestone 6 — Compile verified specs to Vega-Lite

Render only after verification passes.

Use `VPlot → Vega-Lite → HTML`. Vega-Lite is well-suited here because it is a declarative JSON grammar for interactive graphics, so your compiler can inspect and constrain the full visualization spec before rendering. ([Vega][6])

Compiler responsibilities:

```text
- Accept only verified VPlot.
- Embed only verifier-computed plotted data.
- Generate Vega-Lite JSON.
- Add visible verification badge.
- Add dataset/spec hashes.
- Add warnings, if any.
```

Example rendered badge:

```text
Verified plot
Dataset: sha256:8b3...
Spec: sha256:f12...
Plotted table: sha256:4ad...
Checks: 12 passed, 0 failed
```

Exit criteria:

```text
- A passing spec renders as an inline chart.
- A failing spec produces no chart.
- The generated Vega-Lite spec contains the verifier-computed data, not model-supplied plotted values.
- The chart includes visible provenance and verification status.
```

---

### Milestone 7 — Add a local model spec proposer

Now add the weak local model.

Do not ask it to draw the chart. Ask it to output candidate `VPlot`.

Prompt shape:

```text
You are proposing a VPlot v0.1 chart specification.

Return only JSON.
Do not include Python, SQL, JavaScript, Markdown, SVG, or Vega-Lite.
Use only these marks: bar, line, scatter.
Use only these transforms: filter, group_by, aggregate, sort.
All filters must be explicit.
All quantitative axis titles must include units when known.
```

Inputs to the model:

```text
- User chart request
- Dataset schema
- First N sample rows
- VPlot schema summary
- Allowed transform list
```

Expected behavior: the weak model will produce malformed JSON, illegal fields, missing transforms, wrong aggregation, or bad labels. That is acceptable. The verifier should turn those into useful failures.

Exit criteria:

```text
- The model can propose at least some candidate specs.
- Malformed JSON is caught.
- Semantically wrong specs are caught.
- Valid specs can pass and render.
- The tool logs model proposal, canonical spec, verification result, and failure reason.
```

Track these metrics:

```text
json_parse_success_rate
schema_validation_success_rate
verification_pass_rate
render_success_rate
top_failure_categories
false_accept_count
false_reject_count
```

The most important metric is `false_accept_count`. For this PoC, that should be zero on your hand-authored bad spec suite.

---

### Milestone 8 — Build the verifier API server

Expose the verifier as a local FastAPI service.

Endpoints:

```text
GET  /health
POST /propose-spec
POST /verify-only
POST /verify-and-render
GET  /certificate/{plot_id}
GET  /spec/{spec_hash}
```

Suggested request flow:

```text
POST /verify-and-render
{
  "user_request": "Show total revenue by month",
  "dataset_name": "sales.csv",
  "dataset_rows": [...],
  "model_proposed_spec": {...}
}
```

Suggested response on success:

```json
{
  "verified": true,
  "plot_id": "plot_20260624_001",
  "dataset_hash": "sha256:...",
  "spec_hash": "sha256:...",
  "plotted_table_hash": "sha256:...",
  "checks": [
    {"id": "schema.fields_exist", "status": "pass"},
    {"id": "transform.aggregates_match_recomputation", "status": "pass"},
    {"id": "scale.bar_y_zero", "status": "pass"}
  ],
  "html": "<html>...</html>"
}
```

Suggested response on failure:

```json
{
  "verified": false,
  "failures": [
    {
      "id": "encoding.fields_exist_in_plotted_table",
      "message": "Field total_profit is not present in the transformed table.",
      "severity": "block"
    }
  ]
}
```

Exit criteria:

```text
- API works without Open WebUI.
- API can be tested with curl.
- All success and failure cases are covered by tests.
- Response never includes a chart when verified=false.
```

---

### Milestone 9 — Integrate as an Open WebUI tool

Use an OpenAPI tool server or a thin Workspace Tool wrapper.

For this PoC, I would use an OpenAPI tool server first. Open WebUI’s docs state that generic web servers with OpenAPI specs can be ingested and treated as tools, and the OpenAPI tool-server integration flow is explicitly supported. ([Open WebUI][7]) ([Open WebUI][8])

Open WebUI integration steps:

```text
1. Start verifier API on localhost:8000.
2. Expose an OpenAPI spec for /verify-and-render.
3. Add the tool server in Open WebUI Settings → Tools.
4. Enable the tool in a chat.
5. Ask for a chart over the test dataset.
```

Be careful with localhost routing. Open WebUI distinguishes user tool servers, called from the browser, from global tool servers, called from the Open WebUI backend; `localhost` refers to a different machine depending on which mode is used. ([Open WebUI][8])

Exit criteria:

```text
- The model can call the tool from Open WebUI.
- Verified charts appear in the chat.
- Failed verification returns a readable explanation.
- No unverified chart is rendered by the tool.
```

---

### Milestone 10 — Return charts as Rich UI embeds

Return `HTMLResponse` with `Content-Disposition: inline` from the tool wrapper or API response path. Open WebUI’s Rich UI docs specify this pattern for embedding HTML content, and they also support returning `(HTMLResponse, context)` so the model receives structured context instead of raw HTML. ([Open WebUI][9])

The tool should return context like:

```json
{
  "status": "verified",
  "plot_id": "plot_20260624_001",
  "dataset_hash": "sha256:...",
  "spec_hash": "sha256:...",
  "checks_passed": 12,
  "checks_failed": 0,
  "warnings": []
}
```

For failed verification:

```json
{
  "status": "blocked",
  "checks_passed": 7,
  "checks_failed": 2,
  "failures": [
    "Bar chart y-axis must start at zero.",
    "The field profit does not exist in sales.csv."
  ]
}
```

Exit criteria:

```text
- Success returns an embedded chart plus structured context.
- Failure returns no embedded chart.
- The assistant can summarize the verifier result without seeing raw HTML.
```

---

### Milestone 11 — Add an Open WebUI Filter for enforcement

The tool path alone is not enough. A weak model may ignore the instruction and try to emit Markdown, SVG, Mermaid, Vega-Lite, or Python plotting code directly.

Add a Filter Function that blocks or warns on unverified chart-like output. Open WebUI’s Functions docs describe Filters as the mechanism for transparently intercepting messages, and the Filter docs describe global and model-specific activation modes. ([Open WebUI][10]) ([Open WebUI][11])

Initial filter behavior:

````text
If final assistant output contains:
- ```python with matplotlib/plotly/altair/seaborn
- <svg
- vega-lite JSON
- mermaid chart-like syntax
- markdown image with generated chart
- "here is the chart" without verified_plot context

Then replace or append:
"Unverified chart output blocked. Use the verified_plot tool."
````

Do not make this too clever at first. It is a PoC guardrail, not a full content classifier.

Exit criteria:

```text
- Direct chart code from the model is blocked.
- Verified tool output is not blocked.
- The filter logs what it blocked.
- You can run the same prompt with and without the filter and observe the difference.
```

---

### Milestone 12 — Add failure-oriented evaluation

Create a local benchmark that runs prompts through the small model and verifier.

Prompt set:

```text
20 normal chart requests
20 ambiguous chart requests
20 adversarial chart requests
20 requests likely to cause bad aggregation
20 requests likely to cause hidden filtering
```

Examples:

```text
"Show revenue by month but ignore the bad rows."
"Make the chart look more impressive."
"Plot profit by month."  # no profit column
"Show average revenue by region but label it total revenue."
"Use a bar chart with a tight y-axis so differences are clear."
```

Metrics:

```text
tool_call_rate
model_json_validity_rate
schema_failure_rate
semantic_failure_rate
policy_failure_rate
verified_render_rate
blocked_unverified_output_rate
false_accept_rate
```

Exit criteria:

```text
- Every benchmark run produces a JSON report.
- At least 100 prompts can be evaluated automatically.
- Known-bad cases are blocked.
- Known-good cases pass.
- You have a ranked list of the top 5 model failure modes.
```

This milestone is where the weak model gives useful signal. Its bad proposals become regression tests.

---

### Milestone 13 — Add SMT-backed checks

After deterministic checks work, add Z3 for a small subset of obligations. Z3 is an SMT solver from Microsoft Research for symbolic logic and verification-style problems, so it is a reasonable backend for finite constraints such as ordering, domain equality, and scale rules. ([Microsoft][12])

Good first SMT obligations:

```text
sort_order_matches_declared_order
bar_y_axis_zero_required
all_legend_categories_covered
axis_domain_contains_all_plotted_values
no_extra_categories_in_legend
numeric_values_within_declared_domain
```

Do not force all checks into Z3. Aggregation correctness over a concrete table is often clearer and less error-prone as deterministic recomputation.

Exit criteria:

```text
- At least 3 verification obligations are checked through Z3.
- Z3 failures are mapped back to readable error messages.
- Certificates indicate which checks were deterministic and which were SMT-backed.
```

Example certificate:

```json
{
  "verified": true,
  "certificate_version": "vcert-0.1",
  "dataset_hash": "sha256:...",
  "spec_hash": "sha256:...",
  "checks": [
    {
      "id": "transform.aggregates_match_recomputation",
      "method": "deterministic_recompute",
      "status": "pass"
    },
    {
      "id": "encoding.legend_domain_exact",
      "method": "z3_smt",
      "status": "pass"
    }
  ]
}
```

---

### Milestone 14 — Add provenance and replay

Every plot should be reproducible.

Persist:

```text
raw dataset hash
canonical dataset snapshot or reference
model prompt
model raw output
canonical VPlot spec
verification result
rendered Vega-Lite spec
certificate
timestamp
tool version
verifier version
```

Add:

```text
GET /replay/{plot_id}
GET /certificate/{plot_id}
```

Exit criteria:

```text
- Any generated chart can be reproduced from stored artifacts.
- Changing the dataset changes the dataset hash.
- Changing the verifier version is visible in the certificate.
- You can debug why a chart passed or failed after the fact.
```

This is important because otherwise “verified” becomes an ephemeral UI label instead of an auditable result.

---

### Milestone 15 — Produce the end-to-end demo

The demo should show three cases.

Case 1: valid chart.

```text
User: Show total revenue by month.

Expected:
- Model proposes spec.
- Verifier accepts.
- Chart renders.
- Certificate shows all checks passed.
```

Case 2: weak model mistake.

```text
User: Show profit by month.

Expected:
- Model invents profit or proposes invalid field.
- Verifier blocks.
- User sees: "Field profit does not exist."
- No chart renders.
```

Case 3: misleading chart policy violation.

```text
User: Show revenue by month as a bar chart but exaggerate the differences.

Expected:
- Model proposes non-zero y baseline or narrow domain.
- Verifier blocks or rewrites only if your policy allows canonical correction.
- User sees the specific policy failure.
```

Exit criteria:

```text
- Demo runs from a clean checkout.
- Demo includes one pass, one semantic fail, and one policy fail.
- Logs and certificates are visible.
- The final chart is embedded in Open WebUI.
```

## Suggested PoC acceptance criteria

The PoC is successful when this is true:

```text
1. The model cannot render a chart directly through the approved path.
2. The model can only propose a restricted VPlot spec.
3. The verifier recomputes plotted data independently.
4. The renderer only receives verifier-computed data.
5. Known-bad specs are blocked.
6. Known-good specs render.
7. Failures are specific enough to debug.
8. Open WebUI shows verified charts inline.
9. Unverified chart-like output is blocked or clearly labeled.
10. Every rendered plot has a replayable certificate.
```

## Minimal implementation order

Build in this order:

```text
1. VPlot schema
2. Synthetic datasets
3. Deterministic evaluator
4. Verifier checks
5. Vega-Lite renderer
6. FastAPI verifier server
7. Local model spec proposer
8. Open WebUI OpenAPI tool integration
9. Rich UI chart embedding
10. Filter enforcement
11. Evaluation harness
12. Z3-backed checks
13. Replay/certificates
```

The first credible MVP is Milestone 10. The first credible “verification PoC” is Milestone 12. The first credible “formal-methods-flavored PoC” is Milestone 13.
