# Hardware-free hardening walkthrough

From the repository root, run the verifier hardening walkthrough:

```console
.venv/bin/python -m demo
```

To use the locked environment, run this equivalent command:

```console
uv run --locked python -m demo
```

The walkthrough builds a new in-process verifier for each scenario. It exercises the formal-method, archive, replay, audit, integrity, capacity, and transaction hardening paths.
It uses temporary state directories and deterministic model stubs. Therefore, it does not require a model download, accelerator, network connection, socket, or operator `.verifier-state/` directory.

Each scenario logs one `PASS` or `FAIL` line. The command writes the final machine-readable report to
`demo/reports/report.json` (gitignored). It exits with `0` only if every scenario passes.
If a scenario fails, the command records all results and exits with `1`.

## Real-socket end-to-end demo

From the repository root, run the hardware-free driver:

```console
uv run --locked python -m demo.e2e
```

The driver starts its own verifier subprocess. It exercises four cases over real loopback sockets:

1. `g01` renders a verified chart and verifies its DSSE-signed certificate.
   The driver restarts the service and replays the archived plot exactly.
2. `b07` is blocked by `schema.fields_exist` with
   `field 'profit' does not exist in the table`.
3. `b13` is blocked by `label.quantitative_units_present`.
   A crafted `scale.zero:false` variant is separately decode-refused because that misleading baseline is unrepresentable in VPlot v0.1.
4. `f02` verifies a formula spec and authenticates its VCert v0.3.
   The driver takes the signing key from the service over HTTP.
   It matches the archived table and script against the digests that certificate binds.
   The driver then restarts the service and replays the plot exactly.
   `/chart` answers 404 throughout, because formula mode builds no chart page.

The command writes the machine-readable report to `demo/reports/e2e_report.json` (gitignored).
It exits with `0` only if all four outcomes match those expectations.

The opt-in `--with-webui` and `--with-model` legs are disabled by default. Both legs require the live
stack in [webui/README.md](../webui/README.md). Run the legs as separate passes.
Port `8001` serves either the deterministic WebUI stub or the NPU model backend, not both.
