# bench — weak-proposer eval (raw baseline + schema-guided default)

This benchmark is an out-of-tree observer of the weak NPU proposer.
It uses only the verifier's public HTTP endpoints: `/propose-spec` and `/verify-only`.
It never imports `verifier` internals, so it adds no trust.
It uses a synchronous `httpx.Client`, no random-number generator, and a fixed prompt order.
For each `(device, config)`, its output is byte-reproducible.

## What it measures — two things, never conflated
- **GUARANTEE:** This deterministic check provides the only bounds.
  Bench re-posts the `18` bad goldens and the `10` good goldens to `/verify-only`.
  `bad_corpus_false_accept_count` and `good_corpus_false_reject_count` must both equal `0`.
  Either nonzero value is a real verifier regression and makes the run INVALID (`exit 1`).
  The good leg prevents reject-everything vacuity.
  Without this leg, a verifier that blocks all specs satisfies the bad bound trivially.
  Each corpus is pinned by its size (`18/10`) and an identity digest.
  The digest is a SHA-256 over the sorted `(filename, content-hash)` pairs.
  These pins make a short or empty corpus fail loudly.
  They also catch a wrong `--examples-dir`, even if it contains same-sized sets of other specs.
  Such a mismatch never produces a vacuous pass.
  After any deliberate corpus edit, recompute `_EXPECTED_*_CORPUS_DIGEST` in `bench/__main__.py`.
  `tests/test_bench_harness.py` re-derives both digests from the tree, so drift also fails the portable gate.
  The good goldens contain the live CSV hashes from `data/`.
  The verifier under evaluation must serve the repository's own `VERIFIER_DATA_DIR=data`.
- **OBSERVATIONS:** These statistical values characterize the model; they are not bounds.
  Bench calculates them over the `n` HTTP-200 `/propose-spec` verdicts.
  It reports `json_object_rate`, `json_validity_rate`, and the `schema`, `semantic`, and `policy` failure rates.
  It also reports verified-render rates and the top-5 failing checks.
  These results appear overall and by category.
  The categories are normal · ambiguous · adversarial · bad_aggregation · hidden_filter, with `20` prompts each.
  `json_object_rate` is the fraction of HTTP-200 replies that parse as a JSON object.
  It says nothing about tool calls.
  Bench does not calculate an automatic model "false_accept".
  Classifying a verified chart as unfair requires manual labels.
  That classification is outside this benchmark and `POC_SCOPE`.

The buckets partition the HTTP-200 denominator: `verified + schema + semantic + policy = 1.0`.
Non-200 faults are outside `n`.
Bench uses `off_request` for a 502 pin-mismatch.
It means that the model named a different dataset, which is a MODEL failure.
`prompt_policy` covers a 422 context refusal or pre-generation token-policy refusal.
`upstream_fault` covers any other 5xx and indicates backend infrastructure.
`harness_error` covers the remaining 4xx responses.
It indicates a harness bug, and its expected value is `0`.

A bucket and a check family are different classifications.
The `schema` bucket records a decode-layer failure.
The `schema.*`, `dataset.*`, `encoding.*`, and `transform.*` check families all enter SEMANTIC.
Only the `label`, `security`, and `scale` check families enter POLICY.
A result whose method is `resource_policy` also enters POLICY.
Every result must carry one method from the 0.2 wire vocabulary.
A missing or unknown method invalidates decode.
It never silently misclassifies an older response.

## Run provenance (`report.json` → `meta`)

Every report records `git_commit`, which can be `null`.
It records `git_dirty` for tracked or untracked changes.
It records bench's raw-byte `vplot_schema_sha256` for `schema/vplot-0.1.schema.json`.
It also records the exact `model_probe_url` supplied by `--model-url`.

`backend` is `null` when the probe is unreachable, non-200, or undecodable.
Otherwise, it contains these four root `/health` fields: `model_name`, `device`, `structured_output`, and `vplot_schema_sha256`.
The backend also serves `formula_schema_sha256` for the formula proposer schema, which bench ignores.
When bench and backend both report a schema digest, `_log_summary` warns about divergence.
This provenance is observational and never changes the exit status.

`--model-url` selects only the backend that bench probes through `/v1/models` and root `/health`.
The verifier independently selects its proposal backend with `VERIFIER_MODEL_BASE_URL`.
To make `meta.backend` describe the actual proposer, point both settings at the same backend.
The schema-digest cross-check surfaces schema-version divergence.
However, equal served digests cannot prove that the endpoints are identical.

**Reply shape:** The `reply_shape` block is a first-class classifier over the same `n` replies.
It partitions the replies by surface form.
It uses `fenced` for a reply that carries a markdown code fence.
It uses `bare_object` when no fence exists and the stripped reply opens with `{`.
The remaining classes are `empty` and `other`; `other` covers prose or a truncated fragment.
It also reports `defenced_json_valid`, which counts replies that parse as JSON after de-fencing.
De-fencing selects the first fence match's inner text.
If no fence matches, it selects the whole reply.
It strips the selected text and applies `msgspec.json.decode`.
The fence pattern is ```` ```(?:json)?\s*(.*?)``` ````.

Fence-wrapping is a syntactic failure that `decode_spec` rejects.
The classifier separates it from deeper malformation.
For example, an unguided run had `fenced=97 defenced_json_valid=24`; the schema-guided default had `fenced=0`.

## OpenVINO wiring (this Debian container)

- OpenVINO and GenAI are outside the repository at `/var/home/eturkes/.local/app/openvino_genai`.
  Python resolves that build through `PYTHONPATH=/var/home/eturkes/.local/app/openvino_genai/python`.
  They remain absent from `pyproject.toml`.
  `.venv-model` supplies NumPy and the Python web stack.
  The installed bindings support CPython 3.10–3.13.
  This repository uses CPython 3.13.
- Before Python starts, source `/var/home/eturkes/.local/app/intel-accel/env.sh`.
  It points `LD_LIBRARY_PATH` at the host-driver symlink farm.
  It registers the GPU OpenCL ICD through `OCL_ICD_VENDORS`.
  It registers the GPU and NPU Level Zero drivers through `ZE_ENABLE_ALT_DRIVERS`.
  Process execution consumes the loader paths.
  Changing `os.environ` after Python starts is too late.
  Run the virtual-environment interpreter directly.
  The `-E`, `-I`, and isolated `uv run` modes can discard `PYTHONPATH`.
- The live self-test must enumerate `CPU,GPU,NPU` and report `correct=True` for each.
  ```
  source /var/home/eturkes/.local/app/intel-accel/env.sh
  export PYTHONPATH=/var/home/eturkes/.local/app/openvino_genai/python:$PYTHONPATH
  .venv-model/bin/python /var/home/eturkes/.local/app/intel-accel/selftest.py
  ```
- Keep benchmark observations pinned to the default `MODEL_BACKEND_DEVICE=NPU` for one-device reproducibility.
  `AUTO:GPU,CPU` is the documented dynamic-shape fallback.
  `AUTO:NPU,GPU,CPU` orders candidates, but AUTO may temporarily use the CPU while it compiles an accelerator.
  `HETERO:NPU,GPU,CPU` requests graph partitioning instead of fallback selection.
  NPU HETERO support is model-specific.
  Treat either configuration as a probed experiment, not this benchmark's default.
- The driver farm is host+container-coupled and remains outside Git.
  After a host Intel-driver update, rebuild it with `python3 /var/home/eturkes/.local/app/intel-accel/make_farm.py`.
  Then rerun the self-test.

## Run recipe (hardware-gated — needs both servers up)
Start the NPU backend on :8001 with the accelerator environment and OpenVINO `PYTHONPATH`.
Call the virtual-environment Python directly.
Do not use isolated `-E`, `-I`, or `uv run`. These modes strip `PYTHONPATH`.
```
source /var/home/eturkes/.local/app/intel-accel/env.sh
export PYTHONPATH=/var/home/eturkes/.local/app/openvino_genai/python:$PYTHONPATH
.venv-model/bin/python -m model_backend        # wait for GET /health = 200 (~7s cold compile)
```
Start the verifier on :8000.
Defaults already point `VERIFIER_MODEL_BASE_URL` to :8001/v1. The verifier imports no OpenVINO.
```
VERIFIER_WORK_RATE_PER_MINUTE=10000 VERIFIER_WORK_BURST=10000 \
  .venv/bin/python -m verifier.service
```
The explicit high admission rate prevents this 128-request measurement recipe from classifying an operator throttle as model behavior.
It does not change the production defaults.
Run the evaluation:
```
.venv/bin/python -m bench                      # ~10 min: 100 prompts, greedy, ~6s each on NPU
```

## Paired raw-vs-guided A/B (same commit)

Keep the Git commit, verifier configuration, prompts, model, and device fixed.
Restart only the backend between the two arms.
In each backend shell, source the accelerator environment exactly as shown above.

Run the RAW arm with schema guidance off.
The verifier's hardcoded `guided_json` request then becomes a no-op:
```
MODEL_BACKEND_STRUCTURED_OUTPUT=false .venv-model/bin/python -m model_backend
# In the eval shell, after /health is ready:
.venv/bin/python -m bench --out bench/reports/report-raw.json \
  --details bench/reports/details-raw.jsonl
```
Stop that backend.
Then launch the GUIDED arm with the default `structured_output=true`:
```
.venv-model/bin/python -m model_backend
# In the eval shell, after /health is ready:
.venv/bin/python -m bench --out bench/reports/report-guided.json \
  --details bench/reports/details-guided.jsonl
```
Compare `observations.overall.verified_render_rate` in the two reports.
This paired ablation isolates schema guidance.
An unpaired cross-run comparison cannot isolate it.
Each report records `meta.git_commit`, `git_dirty`, and `backend.structured_output`.
Diff the two `meta` blocks to find accidental drift in the commit, tree state, or guidance flag.
This evidence covers only the backend that `--model-url` probes.
Keep `--model-url` on the verifier's proposal backend, as the Run provenance section describes.
Otherwise, `backend.structured_output` describes the wrong server.

## Defaults (all overridable, see `python -m bench --help`)
- `--verifier-url http://127.0.0.1:8000`.
- `--model-url http://127.0.0.1:8001/v1`.
- `--examples-dir examples`: the golden-corpora root for the bad and good corpora.
- `--out bench/reports/report.json`.
- `--details bench/reports/details.jsonl`.
- `--timeout 180`.

The verifier resolves datasets from `VERIFIER_DATA_DIR`, which defaults to `data/`.
The prompts reference `sales.csv` and `weather.csv`.

## Outputs (`bench/reports/`, gitignored — host+model-coupled)
- `report.json` contains `meta`, `guarantee`, and `observations{overall, by_category, top_failure_modes, reply_shape}`.
  `meta` contains the Git, schema, and backend provenance described above.
  `guarantee` includes both corpus digests.
- `details.jsonl` contains one row for each prompt.
  Each row contains `category`, `dataset_name`, `user_request`, `http_status`, `bucket`, and `model_reply`.
  Non-200 rows store the problem `detail` as `model_reply`.

Headline numbers remain in `.agent/archive/m3.md` and `.agent/archive/m8.md` as durable evidence.
The `reports/` directory is not committed.

Exit 0 means a valid run.
A weak model that fails most prompts is the EXPECTED success.
Exit 1 means an INVALID run only.
It never means that the weak model failed prompts.
These conditions make a run INVALID:

- The guarantee is broken: `false_accept > 0`, `false_reject > 0`, or transport errors.
- The guarantee is not exercised: either corpus size or identity digest mismatches.
- `prompt_policy > 0`.
- `harness_error > 0`.
- `n == 0`, which makes the observation void.
