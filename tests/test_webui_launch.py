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

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_LAUNCHER = _ROOT / "webui" / "launch.sh"


@pytest.mark.skip(reason="M12.4b: unwritten")
def test_l1_default_arm_runs_the_real_model_child_through_model_backend_python() -> None:
    """L1: no `--stub` ⇒ `MODEL_BACKEND_DEVICE` defaults to `cuda` and the model child is
    `"$MODEL_BACKEND_PYTHON" -m model_backend` — no `source`d accel env, no prepended
    `PYTHONPATH`. Acceptance: the fake interpreter's argv log records `-m model_backend`, and the
    child's environment carries `MODEL_BACKEND_DEVICE=cuda`."""


@pytest.mark.skip(reason="M12.4b: unwritten")
def test_l2_origin_accelerator_names_are_absent_from_the_launcher() -> None:
    """L2: `INTEL_ACCEL_ENV` and `OPENVINO_GENAI_PYTHON` appear nowhere in `webui/launch.sh`.
    Acceptance: exact-zero search over the file plus a positive control proving the search would
    have found a term that IS present."""


@pytest.mark.skip(reason="M12.4b: unwritten")
def test_l3_preflight_refuses_in_order_with_an_actionable_message() -> None:
    """L3: the default arm preflights `UV_PROJECT_ENVIRONMENT` dir → OWUI bin →
    `MODEL_BACKEND_PYTHON` executable → torch-CUDA probe, and each failure `die`s naming the
    missing thing and a next step. Acceptance: the ORDER is pinned by breaking two stages at once
    and asserting the EARLIER message, which no single-stage matrix can distinguish."""


@pytest.mark.skip(reason="M12.4b: unwritten")
def test_l4_a_refusal_installs_no_teardown_trap() -> None:
    """L4: every preflight refusal and the port-already-in-use refusal exit non-zero having
    installed no `trap cleanup EXIT`. Acceptance: a call-counting fake `fuser` records ZERO calls
    across every refusal path, and the pre-existing foreign listener is still connectable
    afterwards. Exit code alone proves nothing — the trap changes no status."""


@pytest.mark.skip(reason="M12.4b: unwritten")
def test_l5_stub_bypasses_every_cuda_preflight() -> None:
    """L5: `--stub` reaches past the real-arm conditional with `MODEL_BACKEND_PYTHON` pointed at a
    nonexistent path and the torch probe armed to fail. Acceptance: a LATER refusal (an occupied
    port) is what stops the run, proving the stub arm passed the CUDA stages rather than never
    reaching them, and the fake interpreter's argv log is empty."""


@pytest.mark.skip(reason="M12.4b: unwritten")
def test_l6_a_foreign_listener_is_refused_and_survives() -> None:
    """L6: a foreign listener on `VERIFIER_PORT` / `MODEL_BACKEND_PORT` / `WEBUI_PROVISION_PORT` is
    refused, not adopted, and survives. Acceptance: parametrized over all three ports — non-zero
    exit naming that port, the socket still accepting a connection, and zero fake-`fuser` calls."""


@pytest.mark.skip(reason="M12.4b: unwritten")
def test_l7_teardown_frees_all_three_ports_and_removes_the_pidfile() -> None:
    """L7: a full fake stack reaches READY, then SIGINT tears it down. Acceptance: launcher exit
    130, all three ports refuse connections, `${LAUNCH_LOG_DIR}/launch.pid` is gone, and no helper
    process survives — process-group teardown, so real `setsid` must not be stubbed."""


@pytest.mark.skip(reason="M12.4b: unwritten")
def test_l8_help_exits_clean_and_an_unknown_argument_dies() -> None:
    """L8: `--help` exits 0 before any preflight and its text names no ORIGIN accelerator term;
    an unknown argument `die`s non-zero. Acceptance: `--help` succeeds with the whole environment
    unsatisfiable, which is what proves it short-circuits."""


@pytest.mark.skip(reason="M12.4b: unwritten")
def test_l9_shellcheck_is_clean() -> None:
    """L9: `shellcheck webui/launch.sh` exits 0. Acceptance: rc 0 with no new blanket disables —
    the file carries one targeted `disable=SC2016` and the test pins that the directive count has
    not grown. Skip only if `shellcheck` is absent from PATH."""
