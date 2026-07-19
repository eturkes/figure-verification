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
