# bench — proposer eval (M3 raw baseline + M8 schema-guided default)

Out-of-tree observer of the weak NPU proposer. Drives ONLY the verifier's public HTTP surface
(`/propose-spec` + `/verify-only`), never imports `verifier` internals → adds no trust. Sync
`httpx.Client`, RNG-free, fixed ordered prompts → byte-reproducible per (device, config).

## What it measures — two things, never conflated
- **GUARANTEE** (deterministic, the ONLY bounds): re-POST the 18 M1 bad goldens AND the 10 good
  ones to `/verify-only` → `bad_corpus_false_accept_count` MUST = 0 AND
  `good_corpus_false_reject_count` MUST = 0. Either nonzero = a real verifier regression → the
  run is INVALID (exit 1). The good leg closes the reject-everything vacuity: without it a
  verifier that blocked ALL specs would satisfy the bad bound trivially. Each corpus is pinned
  two ways — size (18/10) AND an identity digest, a SHA-256 over the sorted (filename,
  content-hash) pairs — so a short/empty corpus OR a wrong `--examples-dir` (even one holding
  same-sized sets of OTHER specs, which size alone cannot catch) fails LOUD (never a vacuous
  pass). Recompute `_EXPECTED_*_CORPUS_DIGEST` (`bench/__main__.py`) after any deliberate corpus
  edit; `tests/test_bench_harness.py` re-derives both from the tree, so drift also fails the
  portable gate. The good goldens bake `data/`'s live CSV hashes → the verifier under eval must
  serve the repo's own `VERIFIER_DATA_DIR=data`.
- **OBSERVATIONS** (statistical, characterize the model — NOT a bound): over the `n` HTTP-200
  `/propose-spec` verdicts → `json_object_rate` / `json_validity_rate` /
  schema|semantic|policy failure / verified-render rates + top-5 failing checks, overall + per
  category (normal · ambiguous · adversarial · bad_aggregation · hidden_filter, 20 each).
  `json_object_rate` = fraction of 200-replies parsing as a JSON object (formerly mislabeled
  "tool-call rate"); it says nothing about tool calls. NO automatic model "false_accept" — a
  chart verified for an unfair request needs manual labels, out of scope (POC_SCOPE).

Buckets partition the 200 denominator (`verified + schema + semantic + policy = 1.0`). Non-200
faults sit OUTSIDE `n`: `off_request` (a 502 pin-mismatch = model named a different dataset, a
MODEL failure) · `prompt_policy` (a 422 context or pre-generation token-policy refusal) ·
`upstream_fault` (any other 5xx = backend infra) · `harness_error` (remaining 4xx = a harness bug,
expect 0).
Bucket ≠ check family: the `schema` bucket = a decode-LAYER failure; the
`schema.*`/`dataset.*`/`encoding.*`/`transform.*` check families all bucket SEMANTIC; only
`label`/`security`/`scale` or a result whose method is `resource_policy` = POLICY. Every result
must carry one method from the 0.2 wire vocabulary; a missing/unknown method invalidates decode
instead of silently misclassifying an older response.

## Run provenance (`report.json` → `meta`)

Every report explicitly records `git_commit` (or `null`), `git_dirty` (tracked OR untracked),
bench's own raw-byte `vplot_schema_sha256` for `schema/vplot-0.1.schema.json`, and the exact
`model_probe_url` supplied by `--model-url`. `backend` is either `null` (unreachable, non-200, or
undecodable probe) or the backend root `/health` block: `model_name`, `device`,
`structured_output`, `vplot_schema_sha256`. When bench and backend both report a schema digest,
`_log_summary` warns on divergence; provenance remains observational and never changes exit
status.

`--model-url` selects ONLY the backend that bench probes (`/v1/models` + root `/health`). The
verifier independently selects its proposal backend with `VERIFIER_MODEL_BASE_URL`. Point both at
the same backend so `meta.backend` describes the actual proposer; the schema-digest cross-check
surfaces schema-version divergence, but cannot prove endpoint identity when equal digests are
served.

**Reply shape** (`reply_shape` block — a first-class classifier over the same `n` replies)
partitions each by SURFACE FORM — `fenced` (carries a markdown code fence) · `bare_object` (no
fence; the stripped reply opens with `{`) · `empty` · `other` (prose / a truncated fragment) —
plus `defenced_json_valid` = how many parse as JSON once de-fenced. De-fence = the first fence
match's inner text (else the whole reply), stripped, then `msgspec.json.decode`; fence pattern
(indented so the backticks read literally):

    ```(?:json)?\s*(.*?)```

This isolates the SYNTACTIC failure (fence-wrapping, which `decode_spec` rejects) from deeper
malformation — e.g. the pre-M8 raw run's `fenced=97 defenced_json_valid=24` (M8's schema-guided default eliminates the fence: `fenced=0`).

## OpenVINO wiring (this Debian container)
Consolidated repo-local copy of the former `CLAUDE.local.md` guidance and its host guide:

- OpenVINO + GenAI live outside the repo at
  `/var/home/eturkes/.local/app/openvino_genai`; Python resolves that build through
  `PYTHONPATH=/var/home/eturkes/.local/app/openvino_genai/python`. They stay absent from
  `pyproject.toml`; `.venv-model` supplies numpy + the Python web stack. The installed bindings
  support CPython 3.10–3.13; this repo uses 3.13.
- Source `/var/home/eturkes/.local/app/intel-accel/env.sh` **before** Python starts. It points
  `LD_LIBRARY_PATH` at the host-driver symlink farm, registers the GPU OpenCL ICD through
  `OCL_ICD_VENDORS`, and registers the GPU + NPU Level Zero drivers through
  `ZE_ENABLE_ALT_DRIVERS`. Loader paths are consumed at process exec; changing `os.environ`
  after Python starts is too late. Run the venv interpreter directly: `-E`, `-I`, and isolated
  `uv run` modes can discard `PYTHONPATH`.
- The live self-test must enumerate `CPU,GPU,NPU` and report `correct=True` for each:
  ```
  source /var/home/eturkes/.local/app/intel-accel/env.sh
  export PYTHONPATH=/var/home/eturkes/.local/app/openvino_genai/python:$PYTHONPATH
  .venv-model/bin/python /var/home/eturkes/.local/app/intel-accel/selftest.py
  ```
- Keep benchmark observations pinned to the default `MODEL_BACKEND_DEVICE=NPU` for one-device
  reproducibility. `AUTO:GPU,CPU` is the documented dynamic-shape fallback. Generic
  `AUTO:NPU,GPU,CPU` orders candidates but AUTO may temporarily execute on CPU while compiling an
  accelerator; `HETERO:NPU,GPU,CPU` requests graph partitioning rather than fallback selection,
  and NPU HETERO support is model-specific. Treat either as a probed experiment, not this
  benchmark's default.
- The driver farm is host+container-coupled and stays outside git. After a host Intel-driver
  update, rebuild it with
  `python3 /var/home/eturkes/.local/app/intel-accel/make_farm.py`, then rerun the self-test.

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
VERIFIER_WORK_RATE_PER_MINUTE=10000 VERIFIER_WORK_BURST=10000 \
  .venv/bin/python -m verifier.service
```
The explicit high admission rate keeps this 128-request measurement recipe from classifying an
operator throttle as model behavior; production defaults remain unchanged.
Eval:
```
.venv/bin/python -m bench                      # ~10 min: 100 prompts, greedy, ~6s each on NPU
```

## Paired raw-vs-guided A/B (same commit)

Hold git commit, verifier config, prompts, model, and device fixed; restart only the backend between
arms (source the accelerator environment exactly as above in each backend shell):

RAW arm — schema guidance OFF; the verifier's hardcoded `guided_json` request becomes a no-op:
```
MODEL_BACKEND_STRUCTURED_OUTPUT=false .venv-model/bin/python -m model_backend
# In the eval shell, after /health is ready:
.venv/bin/python -m bench --out bench/reports/report-raw.json \
  --details bench/reports/details-raw.jsonl
```
Stop that backend, then launch the GUIDED arm — default `structured_output=true`:
```
.venv-model/bin/python -m model_backend
# In the eval shell, after /health is ready:
.venv/bin/python -m bench --out bench/reports/report-guided.json \
  --details bench/reports/details-guided.jsonl
```
Compare `observations.overall.verified_render_rate` in the two reports. This paired ablation, not an
unpaired historical 0→26 comparison, isolates schema guidance; `meta.git_commit`, `git_dirty`, and
`backend.structured_output` make accidental arm drift visible.

## Defaults (all overridable, see `python -m bench --help`)
`--verifier-url http://127.0.0.1:8000` · `--model-url http://127.0.0.1:8001/v1` ·
`--examples-dir examples` (golden-corpora root, bad + good) · `--out bench/reports/report.json` ·
`--details bench/reports/details.jsonl` · `--timeout 180`. Datasets resolve from the verifier's
`VERIFIER_DATA_DIR` (default `data/`) — the prompts reference `sales.csv` + `weather.csv`.

## Outputs (`bench/reports/`, gitignored — host+model-coupled)
- `report.json` — `meta` (git/schema/backend provenance above) + `guarantee` (incl. both corpus
  digests) + `observations{overall, by_category, top_failure_modes, reply_shape}`.
- `details.jsonl` — one row per prompt (`category`/`dataset_name`/`user_request`/`http_status`/
  `bucket`/`model_reply`). Non-200 rows carry the problem `detail` as `model_reply`.

Headline numbers live in `.agent/roadmap.md` (the M3 and M8 close-outs) as durable evidence — reports/ is not
committed. Exit 0 = valid run (a weak model failing most prompts is the EXPECTED success); exit 1
= INVALID run only: the guarantee broken (`false_accept > 0`, `false_reject > 0`, or transport
errors) or NOT exercised (either corpus size or identity digest mismatches),
`prompt_policy > 0`, `harness_error > 0`, or `n == 0` void.
