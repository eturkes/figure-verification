# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Hardware-free subprocess suite over `webui/launch.sh` — contract `.agent/contracts/m12u4.md` §L.

The launcher is the only orchestration surface no in-process suite reaches: it selects the model
tier, preflights the CUDA runtime, refuses foreign listeners, and tears three process groups down.
M12.4a shipped its CUDA arm with L1-L3 smoked by hand and L4-L9 unencoded; this file is where every
one of them becomes a rerunnable predicate.

Every dependency is redirected rather than installed (`map-m12u4` D4): `PATH` carries a fake `uv`
and a fake `fuser`, `MODEL_BACKEND_PYTHON` carries a fake interpreter, and each fake service is a
real loopback HTTP listener so the launcher's own `curl` readiness poll runs unmodified. Real
`setsid` stays — the lifecycle test asserts process-group teardown, which a stub would forge.

Two design rules bind every case here:

- A fake must refuse whatever the real command refuses. A tolerant fake un-pins the predicate it
  was built for (`.agent/memory.md`, test design).
- L4 is an ORDERING predicate, so it needs a call-counting bomb on the teardown, never an exit
  code: hoisting `trap cleanup EXIT` above the port refusal leaves every exit status unchanged
  while the launcher starts `fuser -k`-ing a listener it never bound.

This file imports no `verifier` symbol: coverage source stays `verifier` only, so an import here
would add launcher lines to a gate that never runs them.
"""

import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_LAUNCHER = _ROOT / "webui" / "launch.sh"
_SUBPROCESS_TIMEOUT_S = 10.0
_READY_TIMEOUT_S = 10.0
_CONNECT_TIMEOUT_S = 0.25


@dataclass(frozen=True)
class _Harness:
    env: dict[str, str]
    ports: tuple[int, int, int]
    fuser_log: Path
    model_log: Path
    uv_log: Path
    pid_dir: Path
    log_dir: Path


class _ModelCall(TypedDict):
    argv: list[str]
    device: str | None
    pythonpath: str | None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _free_ports() -> tuple[int, int, int]:
    ports: list[int] = []
    while len(ports) < 3:
        port = _free_port()
        if port not in ports:
            ports.append(port)
    return ports[0], ports[1], ports[2]


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _make_harness(tmp_path: Path) -> _Harness:
    tmp_path.mkdir(parents=True, exist_ok=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    project_venv = tmp_path / "project-venv"
    project_venv.mkdir()
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()
    log_dir = tmp_path / "launch-logs"
    fuser_log = tmp_path / "fuser.log"
    model_log = tmp_path / "model.log"
    uv_log = tmp_path / "uv.log"
    helper = tmp_path / "http_helper.py"
    model_python = tmp_path / "model-python"
    owui_bin = tmp_path / "open-webui"
    ports = _free_ports()
    shebang = f"#!{sys.executable}\n"

    helper.write_text(
        shebang
        + """import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, _format, *args):
        pass


name = sys.argv[2]
(Path(os.environ["FAKE_PID_DIR"]) / f"{name}.pid").write_text(str(os.getpid()))
ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
""",
        encoding="utf-8",
    )
    _write_executable(
        fake_bin / "uv",
        shebang
        + """import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
with Path(os.environ["FAKE_UV_LOG"]).open("a", encoding="utf-8") as stream:
    print(json.dumps(args), file=stream)
routes = {
    ("run", "--locked", "python", "-m", "verifier.service"): ("VERIFIER_PORT", "verifier"),
    ("run", "--locked", "python", "-m", "webui", "stub"): ("MODEL_BACKEND_PORT", "model"),
    ("run", "--locked", "python", "-m", "webui", "serve"): ("WEBUI_PROVISION_PORT", "webui"),
}
route = routes.get(tuple(args))
if route is not None:
    port_name, service_name = route
    os.execv(
        sys.executable,
        [sys.executable, os.environ["FAKE_HTTP_HELPER"], os.environ[port_name], service_name],
    )
if tuple(args) == ("run", "--locked", "python", "-m", "webui", "bootstrap"):
    raise SystemExit(int(os.environ.get("FAKE_BOOTSTRAP_RC", "0")))
print(f"fake uv refused argv: {args!r}", file=sys.stderr)
raise SystemExit(64)
""",
    )
    _write_executable(
        fake_bin / "fuser",
        shebang
        + """import json
import os
import re
import sys
from pathlib import Path

args = sys.argv[1:]
with Path(os.environ["FAKE_FUSER_LOG"]).open("a", encoding="utf-8") as stream:
    print(json.dumps(args), file=stream)
if len(args) == 2 and args[0] == "-k" and re.fullmatch(r"[0-9]+/tcp", args[1]):
    raise SystemExit(0)
print(f"fake fuser refused argv: {args!r}", file=sys.stderr)
raise SystemExit(64)
""",
    )
    _write_executable(
        model_python,
        shebang
        + """import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
record = {
    "argv": args,
    "device": os.environ.get("MODEL_BACKEND_DEVICE"),
    "pythonpath": os.environ.get("PYTHONPATH"),
}
with Path(os.environ["FAKE_MODEL_LOG"]).open("a", encoding="utf-8") as stream:
    print(json.dumps(record), file=stream)
if len(args) == 2 and args[0] == "-c":
    rc = int(os.environ.get("FAKE_MODEL_PROBE_RC", "0"))
    if rc:
        print("fake CUDA probe refusal", file=sys.stderr)
    else:
        print("Fake CUDA GPU")
    raise SystemExit(rc)
if args == ["-m", "model_backend"]:
    os.execv(
        sys.executable,
        [
            sys.executable,
            os.environ["FAKE_HTTP_HELPER"],
            os.environ["MODEL_BACKEND_PORT"],
            "model",
        ],
    )
print(f"fake model python refused argv: {args!r}", file=sys.stderr)
raise SystemExit(64)
""",
    )
    _write_executable(owui_bin, shebang + "raise SystemExit(97)\n")

    env = dict(os.environ)
    for inherited in (
        "MODEL_BACKEND_DEVICE",
        "WEBUI_PROVISION_VERIFIER_URL",
        "WEBUI_PROVISION_MODEL_BACKEND_URL",
        "VERIFIER_MODEL_BASE_URL",
    ):
        env.pop(inherited, None)
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
            "LAUNCH_HEALTH_HOST": "127.0.0.1",
            "VERIFIER_PORT": str(ports[0]),
            "MODEL_BACKEND_PORT": str(ports[1]),
            "WEBUI_PROVISION_PORT": str(ports[2]),
            "UV_PROJECT_ENVIRONMENT": str(project_venv),
            "UV_LINK_MODE": "copy",
            "WEBUI_PROVISION_WEBUI_BIN": str(owui_bin),
            "MODEL_BACKEND_PYTHON": str(model_python),
            "WEBUI_PROVISION_DATA_DIR": str(tmp_path / "webui-data"),
            "LAUNCH_LOG_DIR": str(log_dir),
            "LAUNCH_VERIFIER_READY_S": "5",
            "LAUNCH_MODEL_READY_S": "5",
            "LAUNCH_WEBUI_READY_S": "5",
            "WEBUI_PROVISION_VERIFIER_URL": f"http://127.0.0.1:{ports[0]}",
            "WEBUI_PROVISION_MODEL_BACKEND_URL": f"http://127.0.0.1:{ports[1]}/v1",
            "VERIFIER_MODEL_BASE_URL": f"http://127.0.0.1:{ports[1]}/v1",
            "FAKE_HTTP_HELPER": str(helper),
            "FAKE_PID_DIR": str(pid_dir),
            "FAKE_FUSER_LOG": str(fuser_log),
            "FAKE_MODEL_LOG": str(model_log),
            "FAKE_UV_LOG": str(uv_log),
            "FAKE_MODEL_PROBE_RC": "0",
            "FAKE_BOOTSTRAP_RC": "0",
        }
    )
    return _Harness(env, ports, fuser_log, model_log, uv_log, pid_dir, log_dir)


def _run_launcher(
    harness: _Harness, *args: str, timeout_s: float = _SUBPROCESS_TIMEOUT_S
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["/bin/bash", str(_LAUNCHER), *args],
        cwd=_ROOT,
        env=harness.env,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )


def _listen(port: int) -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(8)
    return listener


def _can_connect(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=_CONNECT_TIMEOUT_S):
            return True
    except OSError:
        return False


def _log_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _model_calls(path: Path) -> list[_ModelCall]:
    return [cast(_ModelCall, json.loads(line)) for line in _log_lines(path)]


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _start_launcher(harness: _Harness, *args: str) -> tuple[subprocess.Popen[str], Path]:
    stderr_path = harness.log_dir.parent / "launcher.stderr"
    with stderr_path.open("w", encoding="utf-8") as stderr_file:
        process = subprocess.Popen(  # noqa: S603
            ["/bin/bash", str(_LAUNCHER), *args],
            cwd=_ROOT,
            env=harness.env,
            stdout=subprocess.DEVNULL,
            stderr=stderr_file,
            text=True,
            start_new_session=True,
        )
    return process, stderr_path


def _wait_for_text(path: Path, needle: str, process: subprocess.Popen[str]) -> str:
    deadline = time.monotonic() + _READY_TIMEOUT_S
    while time.monotonic() < deadline:
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        if needle in text:
            return text
        if process.poll() is not None:
            pytest.fail(f"launcher exited {process.returncode} before {needle!r}\n{text}")
        time.sleep(0.05)
    message = f"launcher did not emit {needle!r} within {_READY_TIMEOUT_S}s"
    raise TimeoutError(message)


def _force_stop(process: subprocess.Popen[str], harness: _Harness) -> None:
    if process.poll() is None:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
    for pid_path in harness.pid_dir.glob("*.pid"):
        pid = int(pid_path.read_text(encoding="utf-8"))
        if _pid_is_alive(pid):
            with suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGKILL)


def test_l1_default_arm_runs_the_real_model_child_through_model_backend_python(
    tmp_path: Path,
) -> None:
    """L1: no `--stub` ⇒ `MODEL_BACKEND_DEVICE` defaults to `cuda` and the model child is
    `"$MODEL_BACKEND_PYTHON" -m model_backend` — no `source`d accel env, no prepended
    `PYTHONPATH`. Acceptance: the fake interpreter's argv log records `-m model_backend`, and the
    child's environment carries `MODEL_BACKEND_DEVICE=cuda`."""
    harness = _make_harness(tmp_path)
    harness.env["PYTHONPATH"] = "launcher-test-sentinel"
    process, stderr_path = _start_launcher(harness)
    try:
        _wait_for_text(stderr_path, "READY --", process)
        os.kill(process.pid, signal.SIGINT)
        assert process.wait(timeout=_SUBPROCESS_TIMEOUT_S) == 130
        calls = _model_calls(harness.model_log)
        probe_calls = [call for call in calls if call["argv"][:1] == ["-c"]]
        model_calls = [call for call in calls if call["argv"] == ["-m", "model_backend"]]
        assert len(probe_calls) == 1
        assert len(model_calls) == 1
        assert model_calls[0]["device"] == "cuda"
        assert model_calls[0]["pythonpath"] == "launcher-test-sentinel"
    finally:
        _force_stop(process, harness)


def test_l2_origin_accelerator_names_are_absent_from_the_launcher() -> None:
    """L2: `INTEL_ACCEL_ENV` and `OPENVINO_GENAI_PYTHON` appear nowhere in `webui/launch.sh`.
    Acceptance: exact-zero search over the file plus a positive control proving the search would
    have found a term that IS present."""
    source = _LAUNCHER.read_text(encoding="utf-8")

    def present(terms: tuple[str, ...]) -> list[str]:
        return [term for term in terms if term in source]

    assert present(("INTEL_ACCEL_ENV", "OPENVINO_GENAI_PYTHON")) == []
    assert present(("MODEL_BACKEND_PYTHON",)) == ["MODEL_BACKEND_PYTHON"]


def test_l3_preflight_refuses_in_order_with_an_actionable_message(tmp_path: Path) -> None:
    """L3: the default arm preflights `UV_PROJECT_ENVIRONMENT` dir → OWUI bin →
    `MODEL_BACKEND_PYTHON` executable → torch-CUDA probe, and each failure `die`s naming the
    missing thing and a next step. Acceptance: the ORDER is pinned by breaking two stages at once
    and asserting the EARLIER message, which no single-stage matrix can distinguish."""

    def assert_refusal(
        harness: _Harness,
        expected: tuple[str, ...],
        forbidden: tuple[str, ...] = (),
    ) -> None:
        result = _run_launcher(harness)
        assert result.returncode != 0
        for fragment in expected:
            assert fragment in result.stderr
        for fragment in forbidden:
            assert fragment not in result.stderr
        assert _log_lines(harness.fuser_log) == []
        assert _log_lines(harness.uv_log) == []

    venv_first = _make_harness(tmp_path / "venv-first")
    absent_venv = tmp_path / "venv-first" / "absent-venv"
    absent_owui = tmp_path / "venv-first" / "absent-open-webui"
    venv_first.env.update(
        {
            "UV_PROJECT_ENVIRONMENT": str(absent_venv),
            "WEBUI_PROVISION_WEBUI_BIN": str(absent_owui),
        }
    )
    assert_refusal(
        venv_first,
        (f"project venv {absent_venv} missing", "run: uv sync --locked"),
        (str(absent_owui),),
    )

    owui_first = _make_harness(tmp_path / "owui-first")
    absent_owui = tmp_path / "owui-first" / "absent-open-webui"
    absent_model = tmp_path / "owui-first" / "absent-model-python"
    owui_first.env.update(
        {
            "WEBUI_PROVISION_WEBUI_BIN": str(absent_owui),
            "MODEL_BACKEND_PYTHON": str(absent_model),
        }
    )
    assert_refusal(
        owui_first,
        (f"{absent_owui} missing", "see webui/README.md one-time setup"),
        (str(absent_model),),
    )

    model_first = _make_harness(tmp_path / "model-first")
    model_path = Path(model_first.env["MODEL_BACKEND_PYTHON"])
    model_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    model_first.env["FAKE_MODEL_PROBE_RC"] = "91"
    assert_refusal(
        model_first,
        (f"{model_path} missing", "uv sync --locked --project model_backend/runtime"),
        ("CUDA preflight failed",),
    )

    probe_last = _make_harness(tmp_path / "probe-last")
    probe_last.env["FAKE_MODEL_PROBE_RC"] = "91"
    assert_refusal(
        probe_last,
        (
            f"CUDA preflight failed via {probe_last.env['MODEL_BACKEND_PYTHON']}",
            "fake CUDA probe refusal",
            "rebuild: uv sync --locked --project model_backend/runtime",
            "or run with --stub",
        ),
    )
    assert [call["argv"][:1] for call in _model_calls(probe_last.model_log)] == [["-c"]]


def test_l4_a_refusal_installs_no_teardown_trap(tmp_path: Path) -> None:
    """L4: every preflight refusal and the port-already-in-use refusal exit non-zero having
    installed no `trap cleanup EXIT`. Acceptance: a call-counting fake `fuser` records ZERO calls
    across every refusal path, and the pre-existing foreign listener is still connectable
    afterwards. Exit code alone proves nothing — the trap changes no status."""
    for case in ("missing-venv", "missing-owui", "missing-model", "probe", "port"):
        harness = _make_harness(tmp_path / case)
        expected: str
        if case == "missing-venv":
            missing = tmp_path / case / "absent-venv"
            harness.env["UV_PROJECT_ENVIRONMENT"] = str(missing)
            expected = f"project venv {missing} missing"
        elif case == "missing-owui":
            missing = tmp_path / case / "absent-open-webui"
            harness.env["WEBUI_PROVISION_WEBUI_BIN"] = str(missing)
            expected = f"{missing} missing"
        elif case == "missing-model":
            missing = tmp_path / case / "absent-model-python"
            harness.env["MODEL_BACKEND_PYTHON"] = str(missing)
            expected = f"{missing} missing"
        elif case == "probe":
            harness.env["FAKE_MODEL_PROBE_RC"] = "91"
            expected = "CUDA preflight failed"
        else:
            expected = f"port {harness.ports[0]} is already in use"
        listener_port = harness.ports[0] if case == "port" else harness.ports[2]
        listener = _listen(listener_port)
        try:
            result = _run_launcher(harness)
            assert result.returncode != 0
            assert expected in result.stderr
            assert _log_lines(harness.fuser_log) == []
            assert _can_connect(listener_port)
        finally:
            listener.close()


def test_l5_stub_bypasses_every_cuda_preflight(tmp_path: Path) -> None:
    """L5: `--stub` reaches past the real-arm conditional with `MODEL_BACKEND_PYTHON` pointed at a
    nonexistent path and the torch probe armed to fail. Acceptance: a LATER refusal (an occupied
    port) is what stops the run, proving the stub arm passed the CUDA stages rather than never
    reaching them, and the fake interpreter's argv log is empty."""
    for case in ("missing-model-python", "failing-probe"):
        harness = _make_harness(tmp_path / case)
        if case == "missing-model-python":
            harness.env["MODEL_BACKEND_PYTHON"] = str(tmp_path / case / "absent-python")
        else:
            harness.env["FAKE_MODEL_PROBE_RC"] = "91"
        occupied_port = harness.ports[0]
        listener = _listen(occupied_port)
        try:
            result = _run_launcher(harness, "--stub")
            assert result.returncode != 0
            assert f"port {occupied_port} is already in use" in result.stderr
            assert "missing -- rebuild it" not in result.stderr
            assert "CUDA preflight failed" not in result.stderr
            assert _model_calls(harness.model_log) == []
            assert _log_lines(harness.fuser_log) == []
            assert _can_connect(occupied_port)
        finally:
            listener.close()


def test_l6_a_foreign_listener_is_refused_and_survives(tmp_path: Path) -> None:
    """L6: a foreign listener on `VERIFIER_PORT` / `MODEL_BACKEND_PORT` / `WEBUI_PROVISION_PORT` is
    refused, not adopted, and survives. Acceptance: parametrized over all three ports — non-zero
    exit naming that port, the socket still accepting a connection, and zero fake-`fuser` calls."""
    for index, port_name in enumerate(
        ("VERIFIER_PORT", "MODEL_BACKEND_PORT", "WEBUI_PROVISION_PORT")
    ):
        harness = _make_harness(tmp_path / port_name.lower())
        occupied_port = harness.ports[index]
        listener = _listen(occupied_port)
        try:
            result = _run_launcher(harness)
            assert result.returncode != 0
            assert f"port {occupied_port} is already in use" in result.stderr
            assert harness.env[port_name] == str(occupied_port)
            assert _can_connect(occupied_port)
            assert _log_lines(harness.fuser_log) == []
            assert _log_lines(harness.uv_log) == []
        finally:
            listener.close()


def test_l7_teardown_frees_all_three_ports_and_removes_the_pidfile(tmp_path: Path) -> None:
    """L7: a full fake stack reaches READY, then SIGINT tears it down. Acceptance: launcher exit
    130, all three ports refuse connections, `${LAUNCH_LOG_DIR}/launch.pid` is gone, and no helper
    process survives — process-group teardown, so real `setsid` must not be stubbed."""
    harness = _make_harness(tmp_path)
    process, stderr_path = _start_launcher(harness, "--stub")
    try:
        _wait_for_text(stderr_path, "READY --", process)
        pidfile = harness.log_dir / "launch.pid"
        assert int(pidfile.read_text(encoding="utf-8")) == process.pid
        helper_pids = {
            pid_path.stem: int(pid_path.read_text(encoding="utf-8"))
            for pid_path in harness.pid_dir.glob("*.pid")
        }
        assert helper_pids.keys() == {"verifier", "model", "webui"}
        assert all(_pid_is_alive(pid) for pid in helper_pids.values())
        assert all(_can_connect(port) for port in harness.ports)

        os.kill(process.pid, signal.SIGINT)
        assert process.wait(timeout=_SUBPROCESS_TIMEOUT_S) == 130
        assert not pidfile.exists()
        assert not any(_can_connect(port) for port in harness.ports)
        assert not any(_pid_is_alive(pid) for pid in helper_pids.values())
        assert _log_lines(harness.fuser_log) == []
    finally:
        _force_stop(process, harness)


def test_l8_help_exits_clean_and_an_unknown_argument_dies(tmp_path: Path) -> None:
    """L8: `--help` exits 0 before any preflight and its text names no ORIGIN accelerator term;
    an unknown argument `die`s non-zero. Acceptance: `--help` succeeds with the whole environment
    unsatisfiable, which is what proves it short-circuits."""
    harness = _make_harness(tmp_path)
    harness.env.update(
        {
            "UV_PROJECT_ENVIRONMENT": str(tmp_path / "absent-venv"),
            "WEBUI_PROVISION_WEBUI_BIN": str(tmp_path / "absent-open-webui"),
            "MODEL_BACKEND_PYTHON": str(tmp_path / "absent-model-python"),
            "FAKE_MODEL_PROBE_RC": "91",
        }
    )

    help_result = _run_launcher(harness, "--help")
    assert help_result.returncode == 0
    assert "Usage:" in help_result.stdout
    assert "--stub" in help_result.stdout
    assert "--fresh" in help_result.stdout
    for origin_term in ("INTEL_ACCEL_ENV", "OPENVINO_GENAI_PYTHON"):
        assert origin_term not in help_result.stdout + help_result.stderr

    unknown_result = _run_launcher(harness, "--unknown")
    assert unknown_result.returncode != 0
    assert "unknown argument: --unknown" in unknown_result.stderr
    assert "absent-venv" not in unknown_result.stderr


def test_l9_shellcheck_is_clean() -> None:
    """L9: `shellcheck webui/launch.sh` exits 0. Acceptance: rc 0 with no blanket disables; the
    shipped file carries zero disable directives, and the test pins that count. Skip only if
    `shellcheck` is absent from PATH."""
    shellcheck = shutil.which("shellcheck")
    if shellcheck is None:
        pytest.skip("shellcheck is absent from PATH")
    result = subprocess.run(  # noqa: S603
        [shellcheck, str(_LAUNCHER)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    directives = [
        line
        for line in _LAUNCHER.read_text(encoding="utf-8").splitlines()
        if "shellcheck disable=" in line
    ]
    assert directives == []
