# bench — M3.4 failure-oriented eval

Out-of-tree observer of the weak NPU proposer. Drives ONLY the verifier's public HTTP surface
(`/propose-spec` + `/verify-only`), never imports `verifier` internals → adds no trust. Sync
`httpx.Client`, RNG-free, fixed ordered prompts → byte-reproducible per (device, config).

## What it measures — two things, never conflated
- **GUARANTEE** (deterministic, the ONLY bound): re-POST the 18 M1 bad goldens to `/verify-only`
  → `bad_corpus_false_accept_count` MUST = 0. A nonzero value = a real verifier regression → the
  run is INVALID (exit 1). Pinned to `bad_corpus_size = 18` so a short/empty/wrong-dir corpus
  fails LOUD (never a vacuous pass).
- **OBSERVATIONS** (statistical, characterize the model — NOT a bound): over the `n` HTTP-200
  `/propose-spec` verdicts → tool_call / json_validity / schema|semantic|policy_failure /
  verified_render rates + top-5 failing checks, overall + per category (normal · ambiguous ·
  adversarial · bad_aggregation · hidden_filter, 20 each). NO automatic model "false_accept" — a
  chart verified for an unfair request needs manual labels, out of scope (POC_SCOPE).

Buckets partition the 200 denominator (`verified + schema + semantic + policy = 1.0`). Non-200
faults sit OUTSIDE `n`: `off_request` (a 502 pin-mismatch = model named a different dataset, a
MODEL failure) · `upstream_fault` (any other 5xx = backend infra) · `harness_error` (4xx = a
harness bug, expect 0). Bucket ≠ check family: the `schema` bucket = a decode-LAYER failure; the
`schema.*`/`dataset.*`/`encoding.*`/`transform.*` check families all bucket SEMANTIC; only
`label`/`security`/`scale` = POLICY.

## Run recipe (hardware-gated — needs both servers up)
Backend :8001 (NPU; accel env + OpenVINO `PYTHONPATH`, call the venv python DIRECTLY — never
isolated `-E`/`-I`/`uv run`, which strip `PYTHONPATH`):
```
source /var/home/eturkes/.local/app/intel-accel/env.sh
export PYTHONPATH=/var/home/eturkes/.local/app/openvino_genai/python:$PYTHONPATH
.venv-model/bin/python -m model_backend        # wait for GET /health = 200 (~7s cold compile)
```
Verifier :8000 (defaults already point `VERIFIER_MODEL_BASE_URL` → :8001/v1; imports no OpenVINO):
```
.venv/bin/python -m verifier.service
```
Eval:
```
.venv/bin/python -m bench                      # ~10 min: 100 prompts, greedy, ~6s each on NPU
```

## Defaults (all overridable, see `python -m bench --help`)
`--verifier-url http://127.0.0.1:8000` · `--model-url http://127.0.0.1:8001/v1` ·
`--examples-dir examples` (bad corpus) · `--out bench/reports/report.json` ·
`--details bench/reports/details.jsonl` · `--timeout 180`. Datasets resolve from the verifier's
`VERIFIER_DATA_DIR` (default `data/`) — the prompts reference `sales.csv` + `weather.csv`.

## Outputs (`bench/reports/`, gitignored — host+model-coupled)
- `report.json` — `meta` + `guarantee` + `observations{overall, by_category, top_failure_modes}`.
- `details.jsonl` — one row per prompt (`category`/`dataset_name`/`user_request`/`http_status`/
  `bucket`/`model_reply`). Non-200 rows carry the problem `detail` as `model_reply`.

Headline numbers live in `.agent/roadmap.md` (M3 close-out) as durable evidence — reports/ is not
committed. Exit 0 = valid run (a weak model failing most prompts is the EXPECTED success); exit 1
= INVALID run only (guarantee broken/not-exercised, `harness_error > 0`, or `n == 0` void).
