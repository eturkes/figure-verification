# bench — weak-proposer eval (raw baseline + schema-guided default)

This benchmark is an out-of-tree observer of the weak JSON-spec proposers.
By default, it measures the dataset proposer. With `--mode formula`, it measures the formula proposer.
It uses only the verifier's public HTTP endpoints: `/propose-spec` and `/verify-only` for the dataset proposer, `/propose-formula` and `/verify-formula` for the formula proposer.
It never imports `verifier` internals, so it adds no trust.
It uses a synchronous `httpx.Client`, no random-number generator, and a fixed prompt order.
For each `(device, config)`, its output is byte-reproducible.
The bench numbers in `.agent/archive/m3.md` and `.agent/archive/m8.md` come from the earlier ORIGIN host and its NPU model.
These numbers are historical.
The CURRENT-host baseline is in `bench/baselines/m12-cuda/`, as the CURRENT-host baseline section describes.

## What it measures — two things, never conflated

This section describes a dataset run.
The formula-mode section describes the changes for a formula run.

- **GUARANTEE:** This deterministic check provides the only bounds.
  Bench re-posts the `18` bad dataset goldens and the `10` good dataset goldens to `/verify-only`.
  `bad_corpus_false_accept_count` and `good_corpus_false_reject_count` must both equal `0`.
  Either nonzero value is a real verifier regression and makes the run INVALID (`exit 1`).
  The good leg prevents reject-everything vacuity.
  Without this leg, a verifier that blocks all specs satisfies the bad bound trivially.
  Bench pins each corpus by its size (`18/10`) and an identity digest.
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

## Formula mode (`--mode formula`)

Formula mode measures the formula proposer through `/propose-formula`.
Its guarantee leg posts the `20` bad formula goldens and the `6` good formula goldens to `/verify-formula`.
Bench pins both formula corpora by size and identity digest, as it does for the dataset corpora.
The run is INVALID under the same conditions as a dataset run.

The formula prompts are `FORMULA_PROMPTS` in `bench/prompts.py`: two categories of `20` prompts each.
The categories partition the prompts by intended difficulty against the formula grammar.

- `simple`: one curve that the grammar can state, over a given interval.
  A faithful specification can verify.
- `complex`: a faithful specification cannot verify.
  The prompt asks for a function outside the grammar, several curves or panels, a curve that is not a function, styling, or an axis change.

The formula route binds no request text.
Thus, a verified `complex` reply draws a DIFFERENT curve than the request asks for.
`verified_render_rate` counts verified verdicts, because the formula route renders no chart.
Read the gradient per category, never as one overall rate.
The rate is not a faithfulness measure.

```
.venv/bin/python -m bench --mode formula --out bench/reports/report-formula.json \
  --details bench/reports/details-formula.jsonl
```

A formula report records `meta.mode = formula` and bench's own `formula_schema_sha256`.
The backend's `formula_schema_sha256` appears in `meta.backend`.

`bench/baselines/m12-cuda-formula/` holds one guided formula run on the CURRENT host.
It ran at commit `4a52176`, on the same model, runtime and verifier process as the guided dataset baseline.

| Category | n | Verified | Schema | Policy |
|---|---|---|---|---|
| simple | 20 | 1 | 3 | 16 |
| complex | 20 | 0 | 7 | 13 |

The guarantee held: 0 of the 20 bad formula goldens verified, and 6 of the 6 good formula goldens verified.
All 40 replies were bare JSON objects.
The one verified reply plotted `y = x` with the 11 points that the prompt asked for.
In 35 replies, the model asked for 100000 samples, which is the maximum that the system prompt states.
The verifier's default limit is 10000 samples, so 29 of these replies failed `resource.formula_samples`.
On this host, the gradient between the two categories is 1 of 20 against 0 of 20.
This sample-count failure hides most of the difference between the categories.

## CURRENT-host baseline (`bench/baselines/m12-cuda/`)

This directory holds one guided run of the full 100-prompt corpus on the CURRENT host.
Git tracks the run, and `tests/test_bench_harness.py` checks it.

- `report.json` and `details.jsonl` are the bench outputs.
- `provenance.json` is the sidecar from `bench/sidecar.py`.
  It records the host, the GPU state, the model runtime versions and the SHA-256 digest of each model file.

The run used commit `5a97b5d` with a clean tree.
The model was `Qwen2.5-Coder-0.5B-Instruct` in float16 on the NVIDIA MX150 with torch 2.13.0+cu126.
Schema guidance was on, the token cap was 512 and the temperature was 0.

| Scope | n | Verified | Schema | Semantic | Policy |
|---|---|---|---|---|---|
| overall | 100 | 26 | 3 | 70 | 1 |
| normal | 20 | 2 | 0 | 18 | 0 |
| ambiguous | 20 | 8 | 0 | 12 | 0 |
| adversarial | 20 | 6 | 2 | 12 | 0 |
| bad_aggregation | 20 | 0 | 1 | 19 | 0 |
| hidden_filter | 20 | 10 | 0 | 9 | 1 |

The guarantee held: 0 of the 18 bad goldens verified, and 10 of the 10 good goldens verified.
All 100 replies were bare JSON objects.
The most frequent failing check was `transform.group_by_placement`, in 43 replies.

This number is a CURRENT-host observation for one `(device, config)`.
The ORIGIN guided run also verified 26 of 100, but the two runs differ in host, model, quantization and guidance stack.
Thus, the two results are not a comparison.

To repeat the run, start the two servers and run bench from the repository root:

```
.venv-model/bin/python -m model_backend
VERIFIER_MODEL_TIMEOUT=900 VERIFIER_WORK_RATE_PER_MINUTE=10000 VERIFIER_WORK_BURST=10000 \
  .venv/bin/python -m verifier.service
# In the eval shell, after both /health endpoints are ready:
B=bench/baselines/m12-cuda
.venv/bin/python -m bench.sidecar $B/provenance.json start
.venv/bin/python -m bench --timeout 1200 --out $B/report.json --details $B/details.jsonl
.venv/bin/python -m bench.sidecar $B/provenance.json end exit_code=0
```

On this laptop GPU, a thermal slowdown can make one reply take about one minute.
The long `--timeout` and `VERIFIER_MODEL_TIMEOUT=900` keep a slow reply from counting as an `upstream_fault`.
Greedy output does not depend on speed.

### Priced system-prompt variants (p34)

Both proposer system prompts close on a list of rejected output forms.
p34 priced two positive restatements of that rule.
Each variant ran at the commit that shipped it, with the guided arm's model, runtime and settings.
Both variants lost most of the verified dataset prompts, so the prompts keep the original rule.

| Variant | Commit | Output rule | Dataset verified | normal | Formula verified |
|---|---|---|---|---|---|
| original | `5a97b5d` | `Output only JSON: no prose, Markdown, fences, SQL, Python, JavaScript, or Vega-Lite.` | 26 of 100 | 2 of 20 | 1 of 40 |
| A | `43cc447` | `Emit that one JSON object as the entire reply, starting with { and ending with }.` | 2 of 100 | 0 of 20 | 1 of 40 |
| B | `caed70d` | `Output only JSON.` | 3 of 100 | 0 of 20 | not run |
| original, control | `42ac1db` | the original rule | 26 of 100 | 2 of 20 | not run |

The formula rows ran at `4a52176` (original) and `43cc447` (A).
Variant B did not run in formula mode, because its dataset result already failed.
Variant A changed 71 of the 100 dataset replies, and 25 verified replies failed a semantic check instead.
The failures of `encoding.axis_types_match_fields` rose from 6 to 42.
The cause of this change is not known.
Variant B changed 73 of the 100 dataset replies.
`bench/baselines/m12-cuda-p34a/` and `bench/baselines/m12-cuda-formula-p34a/` hold the variant A runs.
`bench/baselines/m12-cuda-p34b/` holds the variant B run.
The control restored the original rule and ran again after both variants.
All 100 control replies were byte-identical to the guided baseline, so greedy decoding held across backend restarts.
Thus, the prompt change alone caused each drop.
`bench/baselines/m12-cuda-p34-control/` holds the control run.

## Historical: OpenVINO wiring on the ORIGIN host

This section is historical. It records ORIGIN-host evidence.
Its Debian paths and its NPU self-test do not apply on the CURRENT host.
The CURRENT host has no NPU.
Before you start model-tier work on the CURRENT host, read `.claude/rules/host-runtime.md`.

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

## Historical: ORIGIN-only run recipe (hardware-gated — needs both servers up)

This recipe is historical. Run it on the ORIGIN host only.
The CURRENT host cannot run it, because the CURRENT host has no NPU.
A run of this recipe does not satisfy the unmet formula live smoke.
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
On the ORIGIN host, source the accelerator environment in each backend shell, as shown above.

Run the RAW arm with schema guidance off.
The verifier's hardcoded `guided_schema` request then becomes a no-op:
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

### The paired A/B on the CURRENT host

`bench/baselines/m12-cuda-raw/` holds the RAW arm of this recipe on the CURRENT host.
It ran at commit `5a97b5d`, which is the same commit as the guided baseline in `bench/baselines/m12-cuda/`.
The backend ran with `MODEL_BACKEND_STRUCTURED_OUTPUT=false`.
The verifier process, prompts, model and device were the same as in the guided arm.
`tests/test_bench_harness.py` checks that the two reports differ only in the guidance flag.

| Arm | Verified | Schema | Semantic | Policy | JSON valid | Fenced | Valid after de-fencing |
|---|---|---|---|---|---|---|---|
| RAW | 0 | 100 | 0 | 0 | 0 | 100 | 100 |
| GUIDED | 26 | 3 | 70 | 1 | 100 | 0 | 100 |

Each arm sent 100 prompts, and every RAW category verified 0 of 20.
Every RAW reply was valid JSON inside a Markdown fence, which the strict decode rejects.
The guarantee held in both arms.
On this host, schema guidance removes the fence and moves the first failure from decode to the semantic checks.

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

Headline ORIGIN numbers remain in `.agent/archive/m3.md` and `.agent/archive/m8.md` as durable evidence.
The `reports/` directory is not committed. Committed baselines are in `bench/baselines/`.

Exit 0 means a valid run.
A weak model that fails most prompts is the EXPECTED success.
Exit 1 means an INVALID run only.
It never means that the weak model failed prompts.
These conditions make a run INVALID:

- The guarantee fails: `false_accept > 0`, `false_reject > 0`, or transport errors.
- The guarantee is not exercised: either corpus size or identity digest mismatches.
- `prompt_policy > 0`.
- `harness_error > 0`.
- `n == 0`, which makes the observation void.
