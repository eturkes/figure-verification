# figure-verification

## What the PoC is

A weak local LLM may propose only a restricted VPlot JSON chart specification. A separate trusted
verifier re-binds the named source CSV by hash. It deterministically recomputes every plotted value
and runs structured checks. It blocks failures and renders only verified charts with a signed
provenance certificate.

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
  DatasetEvidence
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
├── bench/                 weak-model proposer evaluation and deterministic verifier-corpus guarantee
├── webui/                 Open WebUI provisioning, guardrail, stub, and persisted-chat harness
├── demo/                  hardware-free hardening and real-socket end-to-end walkthroughs
├── tests/                 hardware-free pytest unit and integration suite
├── examples/              10 known-good and 18 known-bad VPlot specifications
├── data/                  synthetic source CSVs and trusted column manifests
├── schema/                exported VPlot JSON Schema golden
├── POC_SCOPE.md           claim, service, replay, and display trust boundaries
└── VPlot_SEMANTICS.md     executable VPlot semantics and determinism contract
```

## PoC acceptance

This section is the single acceptance record for the PoC's ten criteria. Each item identifies the
committed evidence. It also states the boundary that keeps the claim modest.

1. **The model cannot render a chart directly through the approved path.**

   **Evidence:** `POST /propose-spec` in `src/verifier/service/app.py` accepts a request and obtains
   the raw model reply bytes. It strictly decodes and verifies the reply. Only then does it reach
   `render.prepare_render`. The render handoff requires `DatasetEvidence`.
   **Boundary:** `Verified Plot Guard` is bypassable and is never authority. This construction claim
   covers the approved verifier path. It does not cover every possible UI output channel.

2. **The model can only propose a restricted VPlot spec.**

   **Evidence:** The request is exactly `{user_request, dataset_name}` (`ProposeRequest`). The raw
   reply then enters `schema.decode_spec`. VPlot v0.1 uses `forbid_unknown_fields`, closed marks and
   transforms, and no field for plotted values. The verifier blocks malformed or out-of-language
   replies.
   **Boundary:** The weak model may emit arbitrary junk. Only a successfully decoded restricted spec
   can proceed.

3. **The verifier recomputes plotted data independently.**

   **Evidence:** `checks.verify_run` reads and hashes the source bytes. It checks the declared dataset
   hash. It calls `eval.evaluate_run` to recompute the complete plotted table from the CSV. The
   recomputation uses deterministic Decimal-exact semantics.
   **Boundary:** This proves faithful execution of the declared selection. It does not prove that the
   selected data or chart intent is representative or fair.

4. **The renderer only receives verifier-computed data.**

   **Evidence:** `render.prepare_render` consumes `DatasetEvidence`. `render.build_vega_lite` copies
   no model Vega key. It constructs `data.values` solely from `evidence.plotted_table`.
   **Boundary:** `vl-convert`, Vega, SVG rasterization, browser behavior, and pixels remain trusted
   display components, not verified components.

5. **Known-bad specs are blocked.**

   **Evidence:** The deterministic `python -m bench` guarantee records all 18 bad goldens as blocked,
   with `false_accept=0`. In `python -m demo.e2e`, case 2 blocks `b07` at `schema.fields_exist`. The
   pinned corpus is in `examples/bad_specs/`.
   **Boundary:** 18/18 is a bound over that hand-authored corpus. It is not a bound over every possible
   hostile specification.

6. **Known-good specs render.**

   **Evidence:** The same benchmark guarantee records all 10 good goldens as accepted, with
   `false_reject=0`. In `python -m demo.e2e`, case 1 renders `g01`, verifies its certificate, restarts
   the service, and replays exactly. The pinned corpus is in `examples/good_specs/`.
   **Boundary:** 10/10 is a corpus result, not a claim that every useful chart request is supported.

7. **Failures are specific enough to debug.**

   **Evidence:** Each `CheckResult` carries a check ID, method, status, severity, and message. Demo
   case 2 prints `field 'profit' does not exist in the table`. To inspect a committed occurrence,
   run `python -m verifier.service audit ATTEMPT_ID`.
   **Boundary:** Classified verification failures are specific. Unclassified implementation faults
   intentionally remain generic `500` responses. Their details remain confined to operator logs.

8. **Open WebUI shows verified charts inline.**

   **Evidence:** `WebUIClient.run_persisted_chat` and
   `python -m webui chat --prompt "…"` read the final text from `output[0].content[0].text`. They read
   the chart URL from `embeds[0]`. A live run records a verified
   `http://127.0.0.1:8000/chart/<hash>` embed in a sandboxed iframe.
   **Boundary:** The retained browser evidence here is textual DOM and CSP evidence. Browser
   rendering and pixels remain in the trusted computing base.

9. **Unverified chart-like output is blocked or clearly labeled.**

   **Evidence:** The global `Verified Plot Guard` outlet replaces recognized direct-chart replies
   with `BLOCKED_NOTICE`. Ordinary prose passes unchanged. [webui/README.md](webui/README.md) shows
   the block/pass differential.
   **Boundary:** The classifier is heuristic, bypassable, and false-positive-prone. It is a usability
   guardrail only and never evidence of verification.

10. **Every rendered plot is replayable to a certificate.**

    **Evidence:** Every verified service render emits a DSSE-signed VCert v0.2. It commits its plot
    bundle to the SQLite provenance archive. `GET /certificate/{plot_id}` serves the envelope.
    `GET /replay/{plot_id}` re-executes archived inputs. Demo case 1 proves exact replay after a
    service restart.
    **Boundary:** Replay does not rerun the weak model or prove browser pixels. A chart is regenerated
    only for exact replay under configured trust. Drift and integrity failures return diagnostics.

## Quickstart

A clean checkout requires no model backend or accelerator:

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

## Try it in your browser

Use one command to start and fully provision the whole instance. The instance includes the verifier,
a local model, and Open WebUI. Then use the verified-plot pipeline from a browser:

```sh
webui/launch.sh          # real local model on the NPU (hardware-gated)
webui/launch.sh --stub   # deterministic stub, no accelerator required
```

The launcher waits for the verifier (`:8000`), the model backend (`:8001`), and Open WebUI (`:8080`).
It then bootstraps Open WebUI. Finally, it prints a banner with the browser URL and the admin login.
[webui/README.md](webui/README.md) explains the one-time `.venv-webui` setup. For the real model, it
also explains the accelerator wiring. Use `--fresh` to wipe the persisted instance. Press `Ctrl-C`
to free all three ports.

Open `http://127.0.0.1:8080`. Log in with the printed credentials. If you use the defaults, enter
`operator@localhost` / `loopback-dev-password`. Type a chart request. For example, enter
`Plot a scatter chart of revenue versus orders. dataset_name: sales.csv`.

Bootstrap makes Figure Verifier a default tool on the configured model. Browser chats then offer it
automatically, without a manual tool toggle. The result depends on the model tier. For the real model,
it also depends on the exact prompt:

- **Real local model (default).**

  Open WebUI's first call selects a tool without guidance. Only a selected `proposeSpec` call is
  schema-guided. This guidance steers the weak model toward schema-representable structure instead of
  the raw model's markdown-fenced prose.

  The `webui/launch.sh` banner pins both live outcomes. The verified prompt is
  `Plot a scatter chart of revenue versus orders. dataset_name: sales.csv`. For the pinned model,
  device, and config, this prompt drives `proposeSpec`. Under the same conditions, it renders a real
  **verified chart inline**. This is a deterministic observation, not a reliability bound.

  The blocked example is deliberately over-elaborate:

  ```text
  Build a fancy sales.csv dashboard: a 2x2 grid of subplots with a gradient-filled revenue area chart, a grouped orders-by-region bar chart, a revenue-versus-orders bubble scatter colored by region, and a KPI panel, on a dark theme with the peak month annotated.
  ```

  No verifiable VPlot spec can express that request. The weak model therefore answers with its own
  unverified chart code. The bypassable `Verified Plot Guard` replaces that code with
  `BLOCKED_NOTICE`. The exact blocked reply depends on the weak model. The guard never proves
  verification.

  A separate 100-prompt bench calls `/propose-spec` directly. It exercises neither Open WebUI tool
  selection nor the guard. It fully verified 26/100 of its fixed benchmark prompts. Another 51/100
  failed strict decode, and 23/100 failed a semantic check.

  In a same-commit A/B, only schema guidance changes. The unguided arm is at 0/100. JSON validity
  changes from 0.01→0.83. Markdown fencing changes from 52→0. Both arms are observations, not bounds.
  Blocking remains common and expected when output truncates. It also remains common and expected
  when a structurally valid proposal fails semantic checks.

  Guidance constrains structure only. It does not establish values, semantics, dataset binding,
  recomputation, provenance, or acceptance. The strict verifier still re-decodes every proposal. It
  recomputes the plotted table and re-binds the CSV by SHA-256. The verifier alone decides whether a
  chart is verified. To audit each admitted attempt, run
  `uv run --locked python -m verifier.service audit <attempt_id>`.

- **`--stub`.**

  The deterministic stub proposes a known-good `sales.csv` spec. Therefore, a **verified chart
  renders inline** with its provenance badge. The badge shows the dataset, manifest, spec,
  recomputed-table, and emitted Vega-Lite hashes. It also shows every passing check with its method,
  the signer keyid, and a certificate link. This is the verified happy path, and it is hardware-free.

Open WebUI, its iframe, the browser, and the pixels stay trusted display components. The modest claim
above and [POC_SCOPE.md](POC_SCOPE.md) hold this boundary. The `Verified Plot Guard` remains a
bypassable usability guardrail. It is never evidence of verification.

## Live full-stack recipes

[bench/README.md](bench/README.md) contains the hardware-gated two-server NPU evaluation recipe.
[webui/README.md](webui/README.md) contains the Open WebUI provisioning, deterministic stub,
persisted chat, and live-stack recipe.

The optional `python -m demo.e2e --with-webui` and `python -m demo.e2e --with-model` legs are both
off by default. They require that live stack. Port `8001` serves either the deterministic WebUI stub
or the NPU model backend. It cannot serve both at once. Therefore, run the two legs as separate live
passes. Use the WebUI recipe instead of starting both providers on that port.

## License

This project uses the `Apache-2.0 WITH LLVM-exception` license. See [LICENSE](LICENSE).
