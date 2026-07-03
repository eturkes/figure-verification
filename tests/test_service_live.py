# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Live-socket smoke test: serve the package in a subprocess, drive it over real TCP (M2.5).

The in-process TestClient suites (test_service*.py) already pin the full verdict/transport
matrix; this proves the one thing they cannot — that `python -m verifier.service` really binds
a socket and serves ASGI through uvicorn from a foreign working directory, the shape a real
deploy (and M4's Open WebUI tool server) uses. So it stays a single health + verify-only check.

VERIFIER_DATA_DIR points at the project's real data/ (absolute) so the good spec's sales.csv
binding resolves; cwd is a throwaway tmp dir purely to prove the installed package resolves
independently of where the process runs. The child runs uninstrumented, so its lines stay
covered by the in-process suites rather than this one.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import NoReturn

import httpx
import pytest

from verifier import __version__

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_GOOD_SPEC = _ROOT / "examples" / "good_specs" / "g01_total_revenue_by_month.json"

_STARTUP_DEADLINE_S = 20.0
_POLL_INTERVAL_S = 0.1


def _free_port() -> int:
    """Reserve an ephemeral loopback port by binding then releasing it. A brief window opens
    before the child rebinds, which the OS is unlikely to fill on loopback during a test."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _fail_with_stderr(message: str, stderr_path: Path) -> NoReturn:
    """Fail the test, appending the child's captured stderr for diagnosis."""
    tail = stderr_path.read_text(encoding="utf-8", errors="replace")
    pytest.fail(f"{message}\n--- server stderr ---\n{tail}")


def _wait_for_health(base_url: str, proc: subprocess.Popen[bytes], stderr_path: Path) -> None:
    """Poll /health until it answers 200, failing fast if the child exits before it does."""
    deadline = time.monotonic() + _STARTUP_DEADLINE_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            _fail_with_stderr(f"server exited early with code {proc.returncode}", stderr_path)
        try:
            response = httpx.get(f"{base_url}/health", timeout=1.0)
        except httpx.TransportError:
            time.sleep(_POLL_INTERVAL_S)  # not bound yet — retry until the deadline
            continue
        if response.status_code == 200:
            return
        time.sleep(_POLL_INTERVAL_S)
    _fail_with_stderr("server did not become healthy before the deadline", stderr_path)


def test_live_socket_health_and_verify(tmp_path: Path) -> None:
    # The good spec binds data/schemas/sales.json + data/sales.csv, so point the child at the
    # real data/ (absolute); cwd is a throwaway dir to prove the install resolves from anywhere.
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    stderr_path = tmp_path / "server.stderr"
    # Inherit the parent environment but drop PYTHONPATH, so the child can resolve `verifier`
    # only through the venv install -- a pass then proves cwd- AND path-independent resolution
    # (an inherited src/ on PYTHONPATH could otherwise satisfy the import for the wrong reason).
    env = {
        **os.environ,
        "VERIFIER_DATA_DIR": str(_DATA),
        "VERIFIER_HOST": "127.0.0.1",
        "VERIFIER_PORT": str(port),
    }
    env.pop("PYTHONPATH", None)
    with stderr_path.open("wb") as stderr_file:
        proc = subprocess.Popen(
            [sys.executable, "-m", "verifier.service"],
            env=env,
            cwd=tmp_path,
            stdout=subprocess.DEVNULL,
            stderr=stderr_file,
        )
        try:
            _wait_for_health(base_url, proc, stderr_path)

            health = httpx.get(f"{base_url}/health", timeout=5.0)
            assert health.status_code == 200
            assert health.json() == {"status": "ok", "version": __version__}

            verdict = httpx.post(
                f"{base_url}/verify-only",
                content=_GOOD_SPEC.read_bytes(),
                headers={"content-type": "application/json"},
                timeout=10.0,
            )
            assert verdict.status_code == 200
            body = verdict.json()
            assert body["verified"] is True
            assert body["layer"] == "verify"
            # Prove the trusted pipeline really ran over the socket, not a hardcoded 200:
            # dataset.hash_matches_source passes only once the verifier has read and hashed the
            # bound CSV, so its presence among the passing results certifies a real recompute.
            results = body["results"]
            assert results, "verify stage returned no checks"
            assert all(result["status"] == "pass" for result in results)
            assert "dataset.hash_matches_source" in {result["check"] for result in results}
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
