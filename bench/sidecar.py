# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Run-provenance sidecar -- `python -m bench.sidecar <out.json> start|end [key=value ...]`.

A report's `meta` holds only what bench observes over HTTP (git state, schema digests, the
backend's /health). A proposer observation is scoped to its full `(device, config)` tuple, so a
committed baseline also carries this sidecar: host, GPU state, the model runtime's package
versions and the model files' SHA-256 digests. `start` writes it before the run; `end` merges the
end time, the GPU state and any `key=value` pairs (exit code, server commands) into the same file.
Git state is read from the working directory -- the checkout bench runs from, which may be a
worktree pinned at the measured commit -- while the model files and `.venv-model` are read from
the checkout holding this file, since a worktree carries neither.
"""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_MODEL_DIR = Path("models") / "Qwen2.5-Coder-0.5B-Instruct"
_MODEL_PYTHON = _ROOT / ".venv-model" / "bin" / "python"
_GPU_FIELDS = "name,driver_version,vbios_version,memory.total,memory.used,temperature.gpu,clocks.sm"
_RUNTIME_PROBE = (
    "import sys, json, importlib.metadata as m, torch; print(json.dumps({"
    "'python': sys.version.split()[0], 'torch': torch.__version__, "
    "'torch_cuda': torch.version.cuda, "
    "**{p: m.version(p) for p in ('transformers', 'xgrammar', 'accelerate', 'tokenizers')}, "
    "'device': torch.cuda.get_device_name(0), "
    "'capability': list(torch.cuda.get_device_capability(0))}))"
)
_MODEL_SUFFIXES = frozenset({".json", ".safetensors", ".txt"})


def _run(*argv: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed argv per call site
        argv, capture_output=True, text=True, check=True
    ).stdout.strip()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _gpu() -> dict[str, str]:
    values = _run("nvidia-smi", f"--query-gpu={_GPU_FIELDS}", "--format=csv,noheader")
    return dict(zip(_GPU_FIELDS.split(","), values.split(", "), strict=True))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _cpu() -> str:
    for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return "unknown"


def _start(extra: dict[str, str]) -> dict[str, object]:
    model_dir = _ROOT / _MODEL_DIR
    return {
        "kind": "bench provenance sidecar",
        "started_utc": _now(),
        "git_commit": _run("git", "rev-parse", "HEAD"),
        "git_status_porcelain": _run("git", "status", "--porcelain", "--untracked-files=normal"),
        "host": {"kernel": _run("uname", "-r"), "cpu": _cpu(), "gpu_start": _gpu()},
        "model_runtime": json.loads(_run(str(_MODEL_PYTHON), "-c", _RUNTIME_PROBE)),
        "model": {
            "dir": _MODEL_DIR.as_posix(),
            "files": {
                path.name: _sha256(path)
                for path in sorted(model_dir.iterdir())
                if path.suffix in _MODEL_SUFFIXES
            },
        },
        **extra,
    }


def main(argv: list[str]) -> int:
    """Write (`start`) or complete (`end`) the sidecar at argv[0]; return the exit code."""
    out, phase, *pairs = argv
    extra = dict(pair.split("=", 1) for pair in pairs)
    if phase == "start":
        data = _start(extra)
    elif phase == "end":
        data = json.loads(Path(out).read_text(encoding="utf-8"))
        data |= {"ended_utc": _now(), "gpu_end": _gpu(), **extra}
    else:
        print(f"unknown phase {phase!r}; use start or end", file=sys.stderr)  # noqa: T201
        return 2
    Path(out).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
