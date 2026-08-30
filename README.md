# figure-verification

## What the PoC is

A caller submits a restricted JSON plot specification. In dataset mode a weak local LLM may propose
that specification. A separate trusted verifier deterministically recomputes every plotted value
and runs structured checks. It blocks failures and certifies only verified plots with a signed
provenance certificate.

The verifier has two plot modes. Dataset mode re-binds the named source CSV by hash and renders a
verified chart. Formula mode evaluates a closed-form expression exactly and emits a matplotlib
script. The verifier writes that script and never runs it.

## The modest claim

The verification claim is exactly the boundary stated in [POC_SCOPE.md](POC_SCOPE.md):

> The verifier has TWO plot modes with DISJOINT carriers. DATASET MODE is the original: a source
> CSV plus a trusted column manifest, emitted as Vega-Lite, certified by VCert v0.2. FORMULA MODE
> plots a closed-form expression over an explicit domain: no CSV, no manifest, no Vega-Lite, no SVG,
> and a verifier-authored matplotlib script the service NEVER executes, certified by VCert v0.3.
> Every sentence below naming a CSV, manifest, Vega-Lite, SVG, renderer, or chart is a DATASET-MODE
> sentence.

Dataset mode binds four artifacts:

> The untrusted model proposes ONLY a VPlot spec — transforms, encoding, and a declared
> source-dataset hash — never plotted values. In dataset mode, "verified" means these four artifacts
> are mutually consistent and every check passed:
>
> 1. the spec validated against the VPlot v0.1 DSL (unknown fields, ops, and marks are
>    rejected before any computation runs);
> 2. the plotted table the verifier recomputed independently from the source CSV;
> 3. the emitted Vega-Lite, which inlines only that recomputed table;
> 4. the VCert v0.2 provenance record and badge representation: source-dataset, trusted-manifest,
>    canonical-spec, recomputed-table, and exact emitted-Vega hashes; every passing check with its
>    method; and the verifier, Z3, canonicalization, and display-tool versions in the trusted base.

Formula mode binds four different artifacts:

> Formula mode verifies its own four artifacts instead: the spec validated against the
> `vplot-formula-0.1` DSL; the plotted table the verifier recomputed by EXACT rational evaluation of
> the declared formula over the declared domain, never floating point; the canonical matplotlib
> script the verifier itself authored from that table; and the VCert v0.3 provenance record binding
> exactly four hashes — RESOLVED formula source, canonical spec, recomputed table, and emitted
> script. The resolved formula source is the verifier's own canonical rendering of nine fixed fields
> — grammar version, numeric profile, rounding mode, printed AST, resolved domain endpoints, sample
> count, and both axis scales — never the submitted formula string verbatim, so two equivalent
> respellings share one formula source hash while a changed domain or scale does not. Only that
> hash is respelling-invariant: the canonical spec preserves the submitted text, so the spec hash,
> the certificate payload, and the derived plot and spec ids still differ between two spellings of
> the same function. There is no fifth. The same structured checks, resource ceilings, and Z3 second-checking apply, over
> formula-mode obligations. matplotlib, the interpreter that would run the script, and the resulting
> pixels are display trust, exactly as SVG rasterization is for dataset mode.

The trusted-computing-base boundary is also unchanged:

> Z3 is a trusted second checker for three bounded, concrete obligations; it does not prove the
> evaluator, builder, renderer, or whole verifier. `vl-convert` and the Vega runtime, SVG
> rasterization, the browser, and the final pixels are likewise trusted, not formally verified -
> trusted to render verified data faithfully, not proven to. In formula mode, matplotlib and the
> Python interpreter that would execute the emitted script hold exactly that position; the verifier
> authors those bytes and never runs them, so nothing downstream of the script is proven. The claim
> is about the mutually bound data, spec, emitted artifact, and certificate layer, not what reaches
> the screen.

## Trust spine

Dataset mode:

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

Formula mode keeps that spine and replaces the source and the artifact:

```text
UNTRUSTED
  caller-supplied formula spec, or one proposed by the model at POST /propose-formula
       |
       | carries ONLY vplot-formula-0.1:
       | formula + domain + encoding
       | THE SPEC SUPPLIES NO PLOTTED VALUES
       v
TRUSTED VERIFIER
  strict decode + schema/resource gates
       |
       v
  closed AST parse; NO source CSV and NO manifest is read
       |
       v
  EXACT rational evaluation of every plotted point
       |
       v
  core structured checks + Z3 second-checking over formula obligations
       |
       v
  fixed-template emitter: float64-fidelity gate, construction checks,
  and script-size admission over the bytes it AUTHORS
       |
       v
  VCert v0.3 payload: RESOLVED-formula-source + canonical-spec
       + recomputed-table + emitted-script hashes
       (resolved source = nine canonical fields: grammar, numeric profile,
        rounding, printed AST, endpoints, samples, and both scales —
        not the submitted formula string)
       |
       v
  Ed25519 DSSE envelope --> certificate
       |
       +--> script TEXT answered inline by POST /verify-formula
       |      the verifier NEVER executes those bytes
       |
       +--> matplotlib / interpreter / figure pixels
              trusted display only; outside the verified claim
```

The v0.3 certificate binds four hashes and the exact script bytes, not the rendered figure.

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

10. **Every plot the dataset service renders is replayable to a certificate.**

    **Evidence:** Every verified service render emits a DSSE-signed VCert v0.2. It commits its plot
    bundle to the SQLite provenance archive. `GET /certificate/{plot_id}` serves the envelope.
    `GET /replay/{plot_id}` re-executes archived inputs. Demo case 1 proves exact replay after a
    service restart.
    **Boundary:** Replay does not rerun the weak model or prove browser pixels. A chart is regenerated
    only for an exact dataset replay under configured trust. Drift and integrity failures return
    diagnostics. Formula plots are archived and certified under VCert v0.3. `POST /verify-formula`
    mints them. The pure formula replay engine is renderer-free. `GET /replay/{plot_id}` answers a
    bounded formula verdict for an archived formula plot that has a signed verified attempt. That
    verdict reports per-artifact hash matches and version drift. A formula replay builds no chart,
    so it never repopulates the chart cache. A plot without such an attempt answers 404 in both
    modes. `GET /table/{plot_id}` serves the archived plotted-table bytes for either mode.
    `GET /script/{plot_id}` serves the archived matplotlib script, which only a formula plot carries.

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

4. Run the real-socket four-case end-to-end demo. It starts and stops its own verifier subprocess.

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
