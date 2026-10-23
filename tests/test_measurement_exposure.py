# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M23.1 F3: the live nucllei harness serves its private stack on loopback alone, with signup off,
and keeps the kept stack's login in a file its operator alone reads.

The image's own command (`nucllei serve`) binds every interface, and nucllei makes the first signup
an admin, a role the harness's `create-admin` claims only after `/health` answers. The harness runs
outside the gate; its module imports the standard library alone, so this test loads it by path.
"""

import importlib.util
import os
import shutil
import stat
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

_HARNESS = Path(__file__).resolve().parents[1] / ".agent" / "measurements" / "nucllei_live.py"


def _harness() -> ModuleType:
    spec = importlib.util.spec_from_file_location("nucllei_live", _HARNESS)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_m23_f3_the_private_nucllei_serves_loopback_alone_with_signup_off(tmp_path: Path) -> None:
    """The container's command = `nucllei serve --host 127.0.0.1 --port <port>` after the image,
    and its environment turns signup off."""
    harness = _harness()
    stack = harness.Stack(tmp_path, tmp_path)
    try:
        argv = stack.nucllei_args()
    finally:
        shutil.rmtree(stack.data, ignore_errors=True)
    image = argv.index(harness.NUCLLEI)
    served = ["nucllei", "serve", "--host", "127.0.0.1", "--port", str(stack.port)]
    assert argv[image + 1 :] == served
    assert argv[argv.index("ENABLE_SIGNUP=false") - 1] == "-e"
    assert "--network=host" in argv


def test_m23_f3_a_kept_stack_s_login_is_written_for_its_owner_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`NL_KEEP` writes `stack.json` mode 0600 under a permissive umask, over an older readable
    file, and runs no container command."""
    harness = _harness()
    stack = harness.Stack(tmp_path, tmp_path)
    shutil.rmtree(stack.data, ignore_errors=True)
    old = tmp_path / "stack.json"
    old.write_text("{}", encoding="utf-8")
    old.chmod(0o644)
    calls: list[list[str]] = []

    def run(argv: list[str], **_options: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(harness.subprocess, "run", run)
    monkeypatch.setenv("NL_KEEP", "1")
    previous = os.umask(0o022)
    try:
        stack.stop()
    finally:
        os.umask(previous)
    assert stat.S_IMODE(old.stat().st_mode) == 0o600
    assert '"password"' in old.read_text(encoding="utf-8")
    assert len(calls) == 1  # the log read alone: a kept stack keeps running
