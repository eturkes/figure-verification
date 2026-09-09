# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""G6-G11: static-config invariants of the one gate command.

Contract: `.agent/contracts/m13u0.md`.

Every gate run re-decides G1-G5 (the stages either pass or they do not), so those need no pin. The
invariants here have NO downstream re-check: a dropped scanner stage, an unpinned `uses:`, a
widened `GITHUB_TOKEN` or a CI step that calls a tool directly instead of the gate all leave a
green gate behind while quietly deleting coverage. Each is stated as a literal rather than read
back from the file it guards -- a test that derives its expectation from the artifact pins nothing.

This file imports no `verifier` symbol: coverage source stays `verifier` only, so an import here
would add gate-tooling lines to a suite that never runs them.
"""

import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GATE = _REPO_ROOT / "tools" / "gate.sh"
_GATE_PROBE = _REPO_ROOT / "tools" / "gate-probe.sh"
# Both purpose-built static suites: neither has a downstream re-check, so both owe firing inputs.
_PROBED_SUITES = (Path(__file__).resolve(), _REPO_ROOT / "tests" / "test_spec.py")
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"
_DEPENDABOT = _REPO_ROOT / ".github" / "dependabot.yml"
_OPS_RULES = _REPO_ROOT / ".claude" / "rules" / "ops.md"

# Hand-stated, in the order tools/gate.sh runs them. Dropping a stage from the script must fail
# here rather than silently shrink the gate.
_EXPECTED_STAGES = (
    "format",
    "lint",
    "types",
    "tests",
    "audit",
    "secrets",
    "workflows",
    "shell",
)

# A gate step may name only the gate. These are the tools it runs BEHIND that entry point; seeing
# one in a workflow means CI and the local gate have become two different claims.
_TOOLS_CI_MUST_NOT_CALL_DIRECTLY = (
    "ruff",
    "mypy",
    "pytest",
    "uv audit",
    "detect-secrets",
    "zizmor",
    "shellcheck",
)

_SHA_PIN = re.compile(r"^[0-9a-f]{40}$")


def _load_yaml(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(path.read_text(encoding="utf-8")))


def _workflow_paths() -> list[Path]:
    return sorted(_WORKFLOWS.glob("*.yml")) + sorted(_WORKFLOWS.glob("*.yaml"))


def _run_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for job in cast(dict[str, Any], workflow["jobs"]).values():
        steps.extend(cast(list[dict[str, Any]], job["steps"]))
    return steps


def test_g6_ci_runs_the_gate_script_and_no_tool_directly() -> None:
    """G6: CI's only build step is the gate script. Acceptance: some `run:` invokes
    `tools/gate.sh`, and no `run:` names a tool the gate runs behind it."""
    paths = _workflow_paths()
    assert paths, "no workflows found"
    # str(): YAML types a bare `run: true` as a bool, which would crash the membership test
    # instead of reporting the missing gate step it actually is.
    invocations = [
        step["run"]
        for path in paths
        for step in _run_steps(_load_yaml(path))
        if "run" in step and "tools/gate.sh" in str(step["run"])
    ]
    assert len(invocations) == 1, f"expected exactly one gate invocation, got {invocations}"

    for path in paths:
        for step in _run_steps(_load_yaml(path)):
            run = str(step.get("run", ""))
            if "tools/gate.sh" in run:
                continue
            for tool in _TOOLS_CI_MUST_NOT_CALL_DIRECTLY:
                assert tool not in run, f"{path.name} calls {tool!r} outside the gate: {run!r}"


def test_g6_gate_script_runs_every_expected_stage() -> None:
    """G6: the script's stage list matches the hand-stated one exactly, in order. Acceptance:
    deleting or renaming a `stage <name>` line fails this test."""
    script = _GATE.read_text(encoding="utf-8")
    declared = tuple(re.findall(r"^\s*stage (\w+)", script, re.MULTILINE))
    assert declared == _EXPECTED_STAGES


def test_g7_dependabot_covers_every_lock_and_cools_down() -> None:
    """G7: update automation spans both uv projects plus the actions themselves, each behind a
    cooldown. Acceptance: a removed ecosystem or a dropped cooldown fails."""
    config = _load_yaml(_DEPENDABOT)
    assert config["version"] == 2
    updates = cast(list[dict[str, Any]], config["updates"])
    covered = {(u["package-ecosystem"], u["directory"]) for u in updates}
    assert covered == {
        ("uv", "/"),
        ("uv", "/model_backend/runtime"),
        ("github-actions", "/"),
    }
    for update in updates:
        assert update["schedule"]["interval"] == "weekly"
        # A brand-new release is the highest-risk window for a compromised package.
        assert update["cooldown"]["default-days"] >= 7


def test_g8_every_action_reference_is_sha_pinned() -> None:
    """G8: `uses:` refs are 40-hex commit SHAs. Acceptance: a `@v4`-style tag ref fails --
    a moving tag lets an upstream compromise reach CI without a commit here."""
    seen = 0
    for path in _workflow_paths():
        for step in _run_steps(_load_yaml(path)):
            uses = step.get("uses")
            if uses is None:
                continue
            seen += 1
            _, _, ref = cast(str, uses).partition("@")
            assert _SHA_PIN.fullmatch(ref), f"{path.name}: {uses!r} is not SHA-pinned"
    assert seen, "no `uses:` references found to check"


def test_g9_workflows_declare_least_privilege_permissions() -> None:
    """G9: every workflow sets a top-level read-only token. Acceptance: a missing block (which
    inherits the repository default, possibly write) or any write scope fails."""
    for path in _workflow_paths():
        workflow = _load_yaml(path)
        assert workflow["permissions"] == {"contents": "read"}, path.name


def test_g9_checkout_does_not_persist_credentials() -> None:
    """G9: the checkout step drops its token. Acceptance: omitting `persist-credentials: false`
    leaves a usable credential in `.git/config` for every later step (zizmor: artipacked)."""
    for path in _workflow_paths():
        for step in _run_steps(_load_yaml(path)):
            uses = cast(str, step.get("uses", ""))
            if "actions/checkout@" in uses:
                assert step["with"]["persist-credentials"] is False, path.name


def test_g10_gate_script_is_executable_and_free_of_blanket_disables() -> None:
    """G10: the script is directly runnable and suppresses no shellcheck finding. Acceptance: a
    cleared execute bit or any `shellcheck disable=` fails."""
    assert _GATE.stat().st_mode & stat.S_IXUSR
    assert "shellcheck disable=" not in _GATE.read_text(encoding="utf-8")


def test_g10_gate_script_passes_shellcheck() -> None:
    """G10: `shellcheck tools/gate.sh` exits 0. Acceptance: rc 0; skipped only where shellcheck is
    absent from PATH."""
    shellcheck = shutil.which("shellcheck")
    if shellcheck is None:
        pytest.skip("shellcheck is absent from PATH")
    completed = subprocess.run(  # noqa: S603
        [shellcheck, str(_GATE)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_g11_ops_rules_record_the_gate_invocation() -> None:
    """G11: the documented gate IS the committed gate. Acceptance: `.claude/rules/ops.md` names
    `tools/gate.sh`, so a session reading the rules runs the same command CI runs."""
    assert "tools/gate.sh" in _OPS_RULES.read_text(encoding="utf-8")


def test_g12_every_static_config_check_ships_a_positive_control() -> None:
    """G12: every check in this file and in `tests/test_spec.py` is named by
    `tools/gate-probe.sh`, which mutates the tree until each one fires. Acceptance: adding a check
    to either suite without its firing input fails -- a check that cannot fire and a clean tree
    emit the same green."""
    probe = _GATE_PROBE.read_text(encoding="utf-8")
    checks = [
        name
        for path in _PROBED_SUITES
        for name in re.findall(r"^def (test_\w+)", path.read_text(encoding="utf-8"), re.MULTILINE)
    ]
    assert checks, "no checks found to cover"
    missing = [name for name in checks if name not in probe]
    assert not missing, f"no positive control in gate-probe.sh for {missing}"
