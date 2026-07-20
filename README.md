# figure-verification

## What the PoC is

A weak local LLM may propose only a restricted VPlot JSON chart specification. A separate trusted
verifier re-binds the named source CSV by hash, deterministically recomputes every plotted value,
runs structured checks, blocks failures, and renders only verified charts with a signed provenance
certificate.

## The modest claim

The verification claim is exactly the boundary stated in [POC_SCOPE.md](POC_SCOPE.md):

> The untrusted model proposes ONLY a VPlot spec — transforms, encoding, and a declared
> source-dataset hash — never plotted values. "Verified" means these four artifacts are
> mutually consistent and every check passed:
>
> 1. the spec validated against the VPlot v0.1 DSL (unknown fields, ops, and marks are
>    rejected before any computation runs);
> 2. the plotted table the verifier recomputed independently from the source CSV;
> 3. the emitted Vega-Lite, which inlines only that recomputed table;
> 4. the VCert v0.2 provenance record and badge representation: source-dataset, trusted-manifest,
>    canonical-spec, recomputed-table, and exact emitted-Vega hashes; every passing check with its
>    method; and the verifier, Z3, canonicalization, and display-tool versions in the trusted base.

The trusted-computing-base boundary is also unchanged:

> Z3 is a trusted second checker for three bounded, concrete obligations; it does not prove the
> evaluator, builder, renderer, or whole verifier. `vl-convert` and the Vega runtime, SVG
> rasterization, the browser, and the final pixels are likewise trusted, not formally verified -
> trusted to render verified data faithfully, not proven to. The claim is about the mutually bound
> data, spec, emitted Vega-Lite, and certificate layer, not what reaches the screen.

## Trust spine

```text
UNTRUSTED
  weak local LLM
       |
       | proposes ONLY VPlot v0.1:
       | transforms + encoding + declared dataset hash
       | MODEL SUPPLIES NO PLOTTED VALUES
       v
TRUSTED VERIFIER
  strict decode + schema/resource gates
       |
source CSV --bounded read--> SHA-256 dataset re-binding
       |                         |
       +-------------------------+
       |
       v
  deterministic Decimal-exact recomputation of ALL plotted rows
       |
       v
  structured checks:
  schema_validation | resource_policy | deterministic_recompute
  construction      | z3_smt
       |
       v
  RecomputedEvidence
       |
       v
  positive-allowlist builder copies no model Vega key
  and inlines ONLY the recomputed table
       |
       v
  exact emitted Vega-Lite bytes
       |
       v
  renderer produces:
       +--> vl-convert / Vega --> SVG / HTML --> browser / pixels
       |      trusted display only; not formally verified or replay proof
       |
       +--> VCert v0.2 payload: dataset + manifest + canonical-spec
              + recomputed-table + exact emitted-Vega hashes
                    |
                    v
              Ed25519 DSSE envelope --> certificate
```

The certificate binds the exact emitted Vega-Lite bytes, not SVG rasterization or final pixels.

## Repo layout

```text
.
├── src/verifier/          trusted verifier core
│   └── service/           `verifier.service` local HTTP transport, archive, audit, and replay
├── model_backend/         hardware-gated OpenVINO NPU wrapper; unshipped
├── bench/                 weak-model failure evaluation and deterministic corpus guarantee
├── webui/                 Open WebUI provisioning, guardrail, stub, and persisted-chat harness
├── demo/                  hardware-free hardening and real-socket end-to-end walkthroughs
├── examples/              10 known-good and 18 known-bad VPlot specifications
├── data/                  synthetic source CSVs and trusted column manifests
├── schema/                exported VPlot JSON Schema golden
├── POC_SCOPE.md           claim, service, replay, and display trust boundaries
└── VPlot_SEMANTICS.md     executable VPlot semantics and determinism contract
```

## PoC acceptance

This is the single acceptance record for the ten criteria in the original scope seed. Each item
points to landed evidence and states the boundary that keeps the claim modest.

1. **The model cannot render a chart directly through the approved path.**
   **Evidence:** `POST /propose-spec` in `src/verifier/service/app.py` accepts a request, obtains raw
   model reply bytes, strictly decodes them, verifies them, and only then reaches
   `render.prepare_render`; the render handoff requires `RecomputedEvidence`.
   **Boundary:** `Verified Plot Guard` is bypassable and is never authority. This construction claim
   covers the approved verifier path, not every possible UI output channel.

2. **The model can only propose a restricted VPlot spec.**
   **Evidence:** the request is exactly `{user_request, dataset_name}` (`ProposeRequest`), while the
   raw reply enters `schema.decode_spec`; VPlot v0.1 uses `forbid_unknown_fields`, closed marks and
   transforms, and no field for plotted values. Malformed or out-of-language replies are blocked.
   **Boundary:** the weak model may emit arbitrary junk; only a successfully decoded restricted spec
   can proceed.

3. **The verifier recomputes plotted data independently.**
   **Evidence:** `checks.verify_run` reads and hashes the source bytes, checks the declared dataset
   hash, and calls `eval.evaluate_run` to recompute the complete plotted table from the CSV with
   deterministic Decimal-exact semantics.
   **Boundary:** this proves faithful execution of the declared selection, not that the selected
   data or chart intent is representative or fair.

4. **The renderer only receives verifier-computed data.**
   **Evidence:** `render.prepare_render` consumes `RecomputedEvidence`; `render.build_vega_lite`
   copies no model Vega key and constructs `data.values` solely from `evidence.plotted_table`.
   **Boundary:** `vl-convert`, Vega, SVG rasterization, browser behavior, and pixels remain trusted
   display components, not verified components.

5. **Known-bad specs are blocked.**
   **Evidence:** the deterministic `python -m bench` guarantee records all 18 bad goldens blocked
   with `false_accept=0`; `python -m demo.e2e` case 2 blocks `b07` at
   `schema.fields_exist`; `examples/bad_specs/` is the pinned corpus.
   **Boundary:** 18/18 is a bound over that hand-authored corpus, not over every possible hostile
   specification.

6. **Known-good specs render.**
   **Evidence:** the same benchmark guarantee records all 10 good goldens accepted with
   `false_reject=0`; `python -m demo.e2e` case 1 renders `g01`, verifies its certificate, restarts
   the service, and replays exactly; `examples/good_specs/` is the pinned corpus.
   **Boundary:** 10/10 is a corpus result, not a claim that every useful chart request is supported.

7. **Failures are specific enough to debug.**
   **Evidence:** each `CheckResult` carries a check ID, method, status, severity, and message. Demo
   case 2 prints `field 'profit' does not exist in the table`; operators can inspect a committed
   occurrence with `python -m verifier.service audit ATTEMPT_ID`.
   **Boundary:** classified verification failures are specific; unclassified implementation faults
   intentionally remain generic `500` responses with details confined to operator logs.

8. **Open WebUI shows verified charts inline.**
   **Evidence:** `WebUIClient.run_persisted_chat` and
   `python -m webui chat --prompt "…"` read final text from `output[0].content[0].text` and the chart
   URL from `embeds[0]`; the M6.3 live run recorded a verified
   `http://127.0.0.1:8000/chart/<hash>` embed in a sandboxed iframe.
   **Boundary:** this repository's retained browser evidence is textual DOM/CSP evidence plus the
   earlier Chromium precedent. Browser rendering and pixels remain in the trusted computing base.

9. **Unverified chart-like output is blocked or clearly labeled.**
   **Evidence:** the global `Verified Plot Guard` outlet replaces recognized direct-chart replies
   with `BLOCKED_NOTICE`, while ordinary prose passes unchanged; the block/pass differential is in
   [webui/README.md](webui/README.md).
   **Boundary:** the classifier is heuristic, bypassable, and false-positive-prone. It is a usability
   guardrail only and never evidence of verification.

10. **Every rendered plot is replayable to a certificate.**
    **Evidence:** every verified service render emits a DSSE-signed VCert v0.2 and commits its plot
    bundle to the SQLite provenance archive; `GET /certificate/{plot_id}` serves the envelope and
    `GET /replay/{plot_id}` re-executes archived inputs. Demo case 1 proves exact replay after a
    service restart.
    **Boundary:** replay does not rerun the weak model or prove browser pixels. A chart is regenerated
    only for exact replay under configured trust; drift and integrity failures return diagnostics.

## Quickstart

From a clean checkout, no model backend or accelerator is required:

1. Install the locked environment.

   ```sh
   uv sync --locked
   ```

2. Run the locked quality gate.

   ```sh
   uv run --locked ruff format --check .
   uv run --locked ruff check .
   uv run --locked mypy
   uv run --locked pytest
   ```

3. Run the hardware-free 13-scenario hardening walkthrough.

   ```sh
   uv run --locked python -m demo
   ```

4. Run the real-socket three-case end-to-end demo. It starts and stops its own verifier subprocess.

   ```sh
   uv run --locked python -m demo.e2e
   ```

## Live full-stack recipes

The hardware-gated two-server NPU evaluation recipe is in [bench/README.md](bench/README.md).
Open WebUI provisioning, the deterministic stub, persisted chat, and the live-stack recipe are in
[webui/README.md](webui/README.md).

The optional `python -m demo.e2e --with-webui` and `python -m demo.e2e --with-model` legs are both
off by default and require that live stack. Port `8001` serves either the deterministic WebUI stub
or the NPU model backend, not both, so the two legs run as separate live passes; see the WebUI
recipe rather than starting both providers on the same port.

## License

Licensed under `Apache-2.0 WITH LLVM-exception`; see [LICENSE](LICENSE).
