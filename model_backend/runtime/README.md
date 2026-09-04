# Proposer runtime

This directory pins the environment and the model weights that `model_backend` runs on. It holds
declarations only. The server code stays in the package above it.

The runtime is a separate `uv` project. The repository gate runs on Python 3.13, but the CUDA
wheels for `torch` stop at Python 3.12. A separate project keeps the two locks apart.

| File | Content |
| --- | --- |
| `pyproject.toml` | The eight direct pins, the probe validator group, and the CUDA 12.6 wheel index. |
| `uv.lock` | The full transitive resolution. The file lists 75 entries, including this project. |
| `snapshot.json` | The model revision and one SHA-256 digest per file. |

## Build the environment

The environment lives at `.venv-model` in the repository root. Git ignores it.

Run every command below from the repository root.

```sh
UV_PROJECT_ENVIRONMENT="$PWD/.venv-model" UV_LINK_MODE=copy \
  uv sync --locked --project model_backend/runtime
```

`--locked` installs the committed resolution. If `uv` reports that the lock is stale, then stop and
report it. Do not relock to make the command pass.

The command also installs the `dev` group. That group holds one package: the schema validator that
`model_backend/guidance_oracle.py` needs. The server itself never imports it. Add `--no-dev` to
install the served packages alone.

Check the installed metadata:

```sh
uv pip check --python "$PWD/.venv-model/bin/python"
```

The `--python` option is necessary. A bare `uv pip check` reads the root `.venv`, which holds the
Python 3.13 gate environment.

## Fetch the model snapshot

Git ignores `models/`. Fetch the weights once per machine:

```sh
UV_PROJECT_ENVIRONMENT="$PWD/.venv-model" \
  uv run --locked --project model_backend/runtime \
  hf download Qwen/Qwen2.5-Coder-0.5B-Instruct \
  --revision ea3f2471cf1b1f0db85067f1ef93848e38e88c25 \
  --local-dir models/Qwen2.5-Coder-0.5B-Instruct
```

The download writes 10 revision files and 953.3 MiB. It also writes `.cache/huggingface/` metadata
below the same directory. The verifier ignores that metadata.

## Verify the model snapshot

The verifier runs on the root gate environment, not on the runtime environment. It imports the
standard library and `msgspec` only.

```sh
uv run --locked python -m model_backend.snapshot --verify
```

The command returns 0 when the tree matches `snapshot.json`. It returns 1 when the tree disagrees,
and it then names each path under one of four labels: `missing`, `mismatched`, `unexpected` or
`unreadable`. It returns 2 when the manifest itself is unusable.

`--verify` never rewrites the manifest. To pin a different revision, edit `SNAPSHOT_REPO_ID` and
`SNAPSHOT_REVISION` in `model_backend/snapshot.py`, fetch the new weights, then run:

```sh
uv run --locked python -m model_backend.snapshot --write
```

## Measured facts

The values below come from this host. Read them as one `(device, config)` baseline.

| Item | Value |
| --- | --- |
| Device | NVIDIA MX150, compute capability 6.1, 1994 MiB |
| Precision | fp16, the supported path on this device |
| Model | `Qwen/Qwen2.5-Coder-0.5B-Instruct`, 494M parameters, Apache-2.0 |
| Weights | 942.3 MiB resident |
| Rate | 5.5-5.7 tokens per second at a full 1536-token context |

A rate depends on the context length. A short prompt measures faster. The smoke probe records 10.3
tokens per second on an 8-token reply. Always state the context length beside a rate.

The model family and the number format both changed with this port. Earlier proposer measurements
used a different family and INT4 weights, so they do not compare with numbers taken here. Measure
each new claim on this baseline.

The 1994 MiB of video memory sets the model size. A model near 0.9B parameters is the fp16 ceiling
on this device.
