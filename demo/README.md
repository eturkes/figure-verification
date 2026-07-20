# Hardware-free hardening walkthrough

Run the verifier hardening walkthrough from the repository root:

```console
.venv/bin/python -m demo
```

The equivalent locked-environment command is:

```console
uv run --locked python -m demo
```

The walkthrough builds a fresh in-process verifier for each scenario and exercises the M5.5d
formal-method, archive, replay, audit, integrity, capacity, and transaction hardening paths. It
uses temporary state directories and deterministic model stubs, so it needs no model download,
accelerator, network connection, socket, or operator `.verifier-state/` directory.

Each scenario logs one `PASS` or `FAIL` line. The final machine-readable report is written to
`demo/reports/report.json` (gitignored). The command exits `0` only when every scenario passes and
exits `1` after recording all results if any scenario fails.

## Real-socket end-to-end demo

Run the hardware-free M6 driver from the repository root:

```console
uv run --locked python -m demo.e2e
```

It starts its own verifier subprocess and exercises three cases over real loopback sockets:

1. `g01` renders a verified chart, verifies its DSSE-signed certificate, restarts the service, and
   replays the archived plot exactly.
2. `b07` is blocked by `schema.fields_exist` with
   `field 'profit' does not exist in the table`.
3. `b13` is blocked by `label.quantitative_units_present`; a crafted `scale.zero:false` variant is
   separately decode-refused because that misleading baseline is unrepresentable in VPlot v0.1.

The machine-readable report is `demo/reports/e2e_report.json` (gitignored). The command exits `0`
only when all three outcomes match those expectations.

The opt-in `--with-webui` and `--with-model` legs are both off by default. They require the live
stack in [webui/README.md](../webui/README.md) and run as separate passes because port `8001` serves
either the deterministic WebUI stub or the NPU model backend, not both.
