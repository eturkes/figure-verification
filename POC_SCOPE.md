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

The emitted Vega-Lite carries no model-supplied data transforms — no encoding-level
aggregate, bin, or impute, no scale-domain override, no top-level `transform`; the only
`stack`/`sort`/`order` keys are the builder's own `null`s, emitted to switch Vega-Lite's
implicit stacking and sorting OFF — so the marks show the recomputed rows, nothing
re-derived downstream.

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

One quantization inside that trusted zone is KNOWN, not merely unproven: the JS runtime
parses the inlined JSON numbers as IEEE-754 doubles, so a value beyond exact-double range
(integer part past 2^53, or more than ~16 significant digits — the DECIMAL(38) data model
admits both) can display rounded, even though the emitted Vega-Lite and the certified
plotted-table hash carry it exactly.

## Service boundary

`verifier.service` (M2) wraps this same verifier in a local HTTP transport — one uvicorn
worker, bound to `127.0.0.1` by default. It adds no trust of its own: a verify request runs
the pipeline above unchanged and the service serializes the result, mapping a decode failure
or an unprovisioned manifest to its own fail-closed verdict that can never falsely verify. The
metadata and artifact GETs serve what a prior verified render already produced, so the
verification claim and the trusted-computing-base line both hold verbatim. `data_dir` stays trusted operator config,
supplied through the environment before the process binds — never anything a caller sends.

The transport reports two kinds of outcome and never confuses them:

- A **verification outcome** — verified, decoded-but-failed a check, or failed to decode at
  all — is a `200` carrying a structured verdict. A decode failure is an expected model
  failure mode, not a transport error, so it rides the verdict envelope like any other
  blocked spec; a chart is attached only when the verdict is verified, never otherwise.
- **Transport misuse or a server-config fault** — a wrong `Content-Type` (415), an oversize
  body (413), a wrong method (405), an uncoercible query parameter like a non-boolean
  `include_html` (400), an unknown or malformed artifact id (404), or a broken trusted
  manifest (500) — answers an RFC 9457 `application/problem+json` document. The model controls
  only the dataset name, never the trusted bytes at that path, so over a correctly provisioned
  deploy no request reaches the 500 path; it signals operator misconfiguration — a
  present-but-broken manifest — whose cause stays in the server log, never in the caller's
  response.

Verified renders and their certificates live in a bounded in-memory store (the
least-recently-used render evicts first), addressable by the content-derived `plot_id` and
`spec_id` the render returns; nothing is written to disk. Durable on-disk provenance and replay are deferred (M5).

Endpoints, exercised with `curl` (defaults: loopback, port 8000):

```sh
# start the service (binds 127.0.0.1:8000)
VERIFIER_DATA_DIR=data python -m verifier.service

# liveness and running version
curl -sS http://127.0.0.1:8000/health

# verify a spec, get a structured verdict (never a chart)
curl -sS http://127.0.0.1:8000/verify-only \
  -H 'Content-Type: application/json' \
  --data-binary @examples/good_specs/g01_total_revenue_by_month.json

# verify and, only if verified, render the certified chart
# (add ?include_html=true for the offline HTML view)
curl -sS 'http://127.0.0.1:8000/verify-and-render?include_html=false' \
  -H 'Content-Type: application/json' \
  --data-binary @examples/good_specs/g01_total_revenue_by_month.json

# fetch a stored certificate / spec by the ids a verify-and-render returned
# (plot_id and spec_id come from that response; shown here as shell variables)
curl -sS "http://127.0.0.1:8000/certificate/${plot_id}"
curl -sS "http://127.0.0.1:8000/spec/${spec_id}"

# the hand-authored OpenAPI 3.1 document
curl -sS http://127.0.0.1:8000/schema/openapi.json
```

## Model proposer

`verifier.service` (M3) puts a weak local model in front of that same verifier through one more
endpoint, `POST /propose-spec`. The request is a small `{user_request, dataset_name}` object;
the service builds the VPlot proposer prompt, asks the local backend for a spec, and feeds
whatever it returns straight through `verify-and-render` above. The claim boundary does not
move: the model proposes only a spec, never plotted values, and the verifier recomputes the
whole plotted table and re-binds the source CSV by hash exactly as before — so the model earns
no new trust, and a chart still rides only a verified outcome.

The error split extends the service boundary's rule to the model as an upstream dependency.
Once the backend returns a reply with extractable content, that content is a spec proposal —
however malformed — so it rides a `200` verdict just like a spec posted directly, including a
decode failure (the model's most common failure mode). Only a fault outside that flow answers
problem+json: an unknown dataset name (`404`, the name never echoed back), an unreachable or
timed-out backend (`503`), a backend reply that is not a usable chat completion (`502`), or a
malformed request body, wrong `Content-Type`, or wrong method (`400`/`415`/`405`). The model
proposes the whole spec, but of the verifier's trusted inputs it names only the dataset — never
the trusted files at that path — so it cannot provoke the operator-config `500`.

```sh
# propose a spec with the local model, then verify and render it
curl -sS http://127.0.0.1:8000/propose-spec \
  -H 'Content-Type: application/json' \
  --data-binary '{"user_request": "total revenue by month", "dataset_name": "sales.csv"}'
```
