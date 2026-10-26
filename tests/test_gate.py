# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""G6-G20: static-config invariants of the one gate command.

Contracts: `.agent/archive/contracts/m13u0.md` (G6-G12), `.agent/archive/contracts/m10u5.md` (G13),
`.agent/archive/contracts/m10u7.md` (G14), `.agent/archive/contracts/m21u2.md` P1 (G16); G15 = queue
row Q47 (its row text is the contract); G17 = `CLAUDE.md` `CI gate` (the CI fan-out); G18 = queue
row "CI skips pass silently" (its row text is the contract).

Every gate run re-decides G1-G5 (the stages either pass or they do not), so those need no pin. The
invariants here have NO downstream re-check: a dropped scanner stage, an unpinned `uses:`, a
widened `GITHUB_TOKEN` or a CI step that calls a tool directly instead of the gate all leave a
green gate behind while quietly deleting coverage. Each is stated as a literal rather than read
back from the file it guards -- a test that derives its expectation from the artifact pins nothing.

This file imports no `verifier` symbol: coverage measures the verifier core, so an import here
would add gate-tooling lines to a suite that never runs them.
"""

import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tomllib
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
_GATE_WORKFLOW = _WORKFLOWS / "gate.yml"
_DEPENDABOT = _REPO_ROOT / ".github" / "dependabot.yml"
_OPS_RULES = _REPO_ROOT / ".claude" / "rules" / "ops.md"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_WEBUI_RUNTIME = _REPO_ROOT / "webui" / "runtime" / "pyproject.toml"

# The shipped pair runs inside Open WebUI's interpreter: CPython 3.11 in the official image.
_SHIPPED_GLOBS = (
    "src/verifier/**",
    "webui/paste_in/**",
    "paste-in/**",
    "webui/demo-paste-in/**",
    "nucllei_skill/**",
    "llens/**",
)

# Hand-stated, in the order tools/gate.sh runs them. Dropping a stage from the script must fail
# here rather than silently shrink the gate.
_EXPECTED_STAGES = (
    "format",
    "lint",
    "types",
    "tests",
    "tests311",
    "audit",
    "secrets",
    "workflows",
    "spec",
    "shell",
)

# A gate step may name only the gate. These are the tools it runs BEHIND that entry point; seeing
# one in a workflow means CI and the local gate have become two different claims.
_TOOLS_CI_MUST_NOT_CALL_DIRECTLY = (
    "ruff",
    "mypy",
    "pytest",
    "uv audit",
    "pnpm audit",
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
    # YAML types a bare `run: true` as a bool; str() keeps the membership test reporting the
    # missing gate step rather than crashing on it.
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
    """G7: update automation spans the four uv projects, the Node measurement harness and the
    actions themselves, each behind a cooldown. Acceptance: a removed ecosystem or a dropped
    cooldown fails."""
    config = _load_yaml(_DEPENDABOT)
    assert config["version"] == 2
    updates = cast(list[dict[str, Any]], config["updates"])
    covered = {(u["package-ecosystem"], u["directory"]) for u in updates}
    assert covered == {
        ("uv", "/"),
        ("uv", "/model_backend/runtime"),
        ("uv", "/webui/runtime"),
        ("uv", "/tools/py311"),
        ("npm", "/.agent/measurements"),
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


def test_g6_checkout_fetches_full_history() -> None:
    """G6: CI checks out the whole history, so its gate is the local gate's claim. Acceptance:
    a missing or non-zero `fetch-depth` fails -- three baseline tests read a historical commit
    through `git show` and `git worktree add`, which a depth-1 checkout cannot serve, and the
    tempting repair is to skip them where the object is absent, turning CI green over a check
    that no longer runs."""
    for path in _workflow_paths():
        for step in _run_steps(_load_yaml(path)):
            uses = cast(str, step.get("uses", ""))
            if "actions/checkout@" in uses:
                assert step["with"]["fetch-depth"] == 0, path.name


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


def test_g15_every_probe_node_names_a_test() -> None:
    """G15: every pytest node `tools/gate-probe.sh` runs is one pytest collects -- a function, or
    a parameter of one. Acceptance: a renamed test or parameter strands its probe, which then
    reports MISSED for a reason the check never saw (or plants an input nothing reads); this
    names the stale node instead."""
    probe = _GATE_PROBE.read_text(encoding="utf-8")
    nodes = sorted(set(re.findall(r"tests/[\w/]+\.py::[\w\[\]./-]+", probe)))
    assert nodes, "no probe nodes found"
    collected = subprocess.run(  # noqa: S603 - fixed argv
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--no-cov",
            "-p",
            "no:cacheprovider",
            *nodes,
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    stale = re.findall(r"ERROR: not found: \S*?(tests/\S+)", collected.stdout + collected.stderr)
    assert collected.returncode == 0 and not stale, f"gate-probe.sh names no such test: {stale}"


def test_g13_audit_stage_covers_every_lock() -> None:
    """G13: the audited (tool, project) pairs equal the tracked locks -- each `uv.lock` directory
    through `uv audit`, each `pnpm-lock.yaml` directory through `pnpm audit`. Acceptance: dropping
    one audit line fails, naming its lock directory."""
    script = _GATE.read_text(encoding="utf-8")
    function = re.search(r"^audit_locks\(\) \{\n(?P<body>.*?)^\}", script, re.MULTILINE | re.DOTALL)
    assert function is not None, "audit_locks is missing"
    assert "stage audit audit_locks" in script

    audited = set()
    for line in function.group("body").splitlines():
        words = line.strip().split()
        if words[:2] == ["uv", "audit"]:
            assert words[2:4] == ["--preview-features", "audit-command"]
            project = words[words.index("--project") + 1] if "--project" in words else "."
            audited.add(("uv", project))
        elif words[:2] == ["pnpm", "audit"]:
            audited.add(("pnpm", words[words.index("--dir") + 1]))

    tracked = subprocess.run(
        [
            "/usr/bin/git",
            "ls-files",
            "--",
            "uv.lock",
            "**/uv.lock",
            "pnpm-lock.yaml",
            "**/pnpm-lock.yaml",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    locks = {
        ("uv" if Path(path).name == "uv.lock" else "pnpm", Path(path).parent.as_posix())
        for path in tracked.stdout.splitlines()
    }
    assert audited == locks, f"audited {sorted(audited)} != tracked locks {sorted(locks)}"


def test_g14_tracked_sources_carry_spdx_header() -> None:
    """G14: tracked sources carry the licensed comment in their first three lines.

    Generated lockfiles (`uv.lock`, `pnpm-lock.yaml`) are exempt.
    Acceptance: every missing source path appears in the failure message.
    """
    tracked = subprocess.run(
        ["/usr/bin/git", "ls-files", "-z"],
        cwd=_REPO_ROOT,
        capture_output=True,
        check=True,
    )
    suffixes = {".py", ".sh", ".mjs", ".js", ".toml", ".yml", ".yaml"}
    lockfiles = {"uv.lock", "pnpm-lock.yaml"}
    missing = []
    for name in sorted(tracked.stdout.decode("utf-8").split("\0")):
        if not name:
            continue
        path = Path(name)
        if path.suffix not in suffixes or path.name in lockfiles:
            continue
        marker = "//" if path.suffix in {".mjs", ".js"} else "#"
        header = f"{marker} SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception"
        with (_REPO_ROOT / path).open(encoding="utf-8") as source:
            first_three = (source.readline().strip() for _ in range(3))
            if header not in first_three:
                missing.append(name)
    assert not missing, "tracked source files missing SPDX header:\n" + "\n".join(missing)


def test_g16_shipped_sources_are_checked_at_the_image_python() -> None:
    """G16: ruff reads every shipped glob as py311, the `types` stage keeps the bare mypy run plus
    one 3.11 pass over the shipped packages, and the demo's Open WebUI runs on 3.11 too.
    Acceptance: a dropped glob, a dropped 3.11 pass, a narrowed bare run or another demo
    interpreter line each fails, naming which."""
    demo = tomllib.loads(_WEBUI_RUNTIME.read_text(encoding="utf-8"))["project"]["requires-python"]
    assert demo == "==3.11.*", f"demo interpreter drifted: {demo}"
    config = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    targets = cast(dict[str, str], config["tool"]["ruff"].get("per-file-target-version", {}))
    floors = {glob: targets.get(glob) for glob in _SHIPPED_GLOBS}
    assert floors == dict.fromkeys(_SHIPPED_GLOBS, "py311"), f"ruff floor drifted: {floors}"

    script = _GATE.read_text(encoding="utf-8")
    assert "stage types type_check" in script
    function = re.search(r"^type_check\(\) \{\n(?P<body>.*?)^\}", script, re.MULTILINE | re.DOTALL)
    assert function is not None, "type_check is missing"
    runs = [
        line.split("||")[0].split()
        for line in function.group("body").splitlines()
        if line.strip().startswith("uv run --locked mypy")
    ]
    assert ["uv", "run", "--locked", "mypy"] in runs, f"bare mypy run missing: {runs}"
    shipped = [words for words in runs if "--python-version" in words]
    assert len(shipped) == 1, f"3.11 mypy pass missing: {runs}"
    words = shipped[0]
    assert words[words.index("--python-version") + 1] == "3.11"
    assert {"src/verifier", "webui/paste_in", "nucllei_skill"} <= set(words), (
        f"3.11 pass narrowed: {words}"
    )


def test_g17_ci_fans_out_every_stage_on_ci_branches() -> None:
    """G17: the CI gate = one job per gate stage, each reporting, on every `ci/**` push.
    Acceptance: a dropped `ci/**` trigger, a stage missing from or duplicated in the matrix, a
    fail-fast matrix or a gate step that ignores its matrix stage each fails, naming which -- each
    leaves CI green over a gate that ran fewer stages, or never ran on the branch an agent pushed.
    """
    # YAML 1.1 reads the bare key `on` as the boolean True.
    workflow = cast(dict[Any, Any], _load_yaml(_GATE_WORKFLOW))
    branches = workflow[True]["push"]["branches"]
    assert "ci/**" in branches, f"no ci/** push trigger: {branches}"
    jobs = cast(dict[str, Any], workflow["jobs"])
    fan_out = [
        job
        for job in jobs.values()
        if any("tools/gate.sh" in str(step.get("run", "")) for step in job["steps"])
    ]
    assert len(fan_out) == 1, f"expected one gate job, got {len(fan_out)}"
    job = fan_out[0]
    strategy = cast(dict[str, Any], job.get("strategy", {}))
    stages = tuple(strategy.get("matrix", {}).get("stage", ()))
    assert stages == _EXPECTED_STAGES, f"fan-out stages drifted: {stages}"
    assert strategy.get("fail-fast") is False, "fail-fast matrix: a failure cancels its siblings"
    step = next(step for step in job["steps"] if "tools/gate.sh" in str(step.get("run", "")))
    passes_stage = step.get("env", {}).get("STAGE") == "${{ matrix.stage }}" and str(
        step["run"]
    ).endswith('tools/gate.sh "$STAGE"')
    assert passes_stage, f"gate step does not pass its matrix stage: {step}"


def _ci_env(*, ci: bool, **extra: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key != "CI"} | extra
    return env | {"CI": "true"} if ci else env


def test_g18_a_stage_skipped_under_ci_fails_the_gate(tmp_path: Path) -> None:
    """G18: under `CI=true` a stage the gate skips fails the run; elsewhere it is announced and
    passes. Acceptance: the `shell` stage with shellcheck off `PATH` (only `dirname`, which the
    script's own root lookup runs) -> rc 1 naming `skipped under CI: shell`; the same run outside CI
    -> rc 0 with `skipped: shell`."""
    bash, dirname = shutil.which("bash"), shutil.which("dirname")
    assert bash is not None and dirname is not None
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "dirname").symlink_to(dirname)
    runs = {
        ci: subprocess.run(  # noqa: S603 - fixed argv
            [bash, str(_GATE), "shell"],
            env=_ci_env(ci=ci, PATH=str(bin_dir)),
            capture_output=True,
            text=True,
            check=False,
        )
        for ci in (True, False)
    }
    assert runs[True].returncode == 1 and "skipped under CI: shell" in runs[True].stdout, (
        f"a stage skipped under CI passed the gate: {runs[True].stdout}"
    )
    assert runs[False].returncode == 0 and "skipped: shell" in runs[False].stdout, runs[
        False
    ].stdout
    assert "skipped under CI" not in runs[False].stdout


def _ci_guard(root: Path) -> None:
    """The suite's own CI skip guard in `root`: `tests/conftest.py` + the tracker reader it
    imports."""
    for name in ("conftest.py", "trackers.py"):
        shutil.copy(_REPO_ROOT / "tests" / name, root / name)


def test_g18_an_untracked_pytest_skip_under_ci_fails_the_suite(tmp_path: Path) -> None:
    """G18: under `CI=true` a pytest skip whose reason names no LIVE S8 tracker fails the session,
    also through xdist (both suites run `-n auto`); a tracked skip and any skip outside CI pass.
    Acceptance: the suite's own guard beside one skipping test, under a spec whose `Tasks` holds
    `**M1.1**` open + `**M1.2**` ticked -> rc 1 naming `untracked skip under CI` serial and under
    `-n 2`; a `**M1.1**` or queue reason under CI -> rc 0; a `**M1.2**` (closed) or `**M1.3**`
    (absent) reason under CI -> rc 1, since a spelling alone names nothing that re-enables the
    case; the untracked skip outside CI -> rc 0."""
    _ci_guard(tmp_path)
    (tmp_path / ".agent").mkdir()
    (tmp_path / ".agent" / "spec.md").write_text(
        "## Tasks\n\n- [ ] **M1.1** open unit\n- [x] abcdef0 **M1.2** closed unit\n\n## Phase\n",
        encoding="utf-8",
    )

    def run(reason: str, *options: str, ci: bool) -> subprocess.CompletedProcess[str]:
        (tmp_path / "test_planted.py").write_text(
            f"import pytest\n\n\ndef test_planted() -> None:\n    pytest.skip({reason!r})\n",
            encoding="utf-8",
        )
        argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
        return subprocess.run(  # noqa: S603 - fixed argv
            [*argv, f"--rootdir={tmp_path}", *options],
            cwd=tmp_path,
            env=_ci_env(ci=ci),
            capture_output=True,
            text=True,
            check=False,
        )

    for options in ((), ("-n", "2")):
        failed = run("dependency absent", *options, ci=True)
        assert failed.returncode == 1 and "untracked skip under CI" in failed.stdout, (
            f"an untracked skip under CI passed the suite {options}: {failed.stdout}"
        )
    for reason in ("skeleton of **M1.1**", "queued in .agent/deferred.md"):
        tracked = run(reason, ci=True)
        assert tracked.returncode == 0, tracked.stdout
    for reason in ("skeleton of **M1.2**", "skeleton of **M1.3**"):
        stale = run(reason, ci=True)
        assert stale.returncode == 1 and "untracked skip under CI" in stale.stdout, (
            f"a skip naming no open Tasks unit passed under CI ({reason}): {stale.stdout}"
        )
    outside = run("dependency absent", ci=False)
    assert outside.returncode == 0, outside.stdout


def test_g18_a_collection_time_skip_under_ci_fails_the_suite(tmp_path: Path) -> None:
    """G18: a module-level `pytest.importorskip` skips at collection, where no test report names it
    (reviewer-1 F2). Acceptance: the suite's own guard beside one passing module and
    one importing an absent dependency -> rc 1 naming `untracked skip under CI` serial and under
    `-n 2`; outside CI -> rc 0."""
    _ci_guard(tmp_path)
    (tmp_path / "test_present.py").write_text("def test_present() -> None:\n    pass\n")
    (tmp_path / "test_absent.py").write_text(
        "import pytest\n\npytest.importorskip('a_dependency_no_host_installs')\n\n\n"
        "def test_absent() -> None:\n    pass\n",
        encoding="utf-8",
    )

    def run(*options: str, ci: bool) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - fixed argv
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *options],
            cwd=tmp_path,
            env=_ci_env(ci=ci),
            capture_output=True,
            text=True,
            check=False,
        )

    for options in ((), ("-n", "2")):
        failed = run(*options, ci=True)
        assert failed.returncode == 1 and "untracked skip under CI" in failed.stdout, (
            f"a collection-time skip under CI passed the suite {options}: {failed.stdout}"
        )
    outside = run(ci=False)
    assert outside.returncode == 0, outside.stdout


def test_g19_the_secret_scan_runs_beside_the_earlier_stages(tmp_path: Path) -> None:
    """G19: the single-threaded secret scan starts at the gate's start, in the background, and
    reports in its own place, so a local run pays it beside the suites. Acceptance (fake `uv`): a
    `format` stage that waits for the scan to start finishes (`format rc=0`), and `secrets rc=0`
    prints once; a scan started in its usual place leaves `format` waiting until it fails."""
    tools = {
        name: shutil.which(name) for name in ("dirname", "git", "mktemp", "cat", "rm", "sleep")
    }
    shell = shutil.which("sh")
    assert shell is not None and all(tools.values()), tools
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, path in tools.items():
        (bin_dir / name).symlink_to(cast("str", path))
    mark = tmp_path / "scan-started"
    fake = bin_dir / "uv"
    fake.write_text(
        f"#!{shell}\n"
        'case "$*" in\n'
        f'  *detect-secrets-hook*) : > "{mark}"; exit 0 ;;\n'
        f'  *"ruff format"*) i=0; while [ ! -e "{mark}" ]; do i=$((i + 1));'
        " [ $i -gt 50 ] && exit 9; sleep 0.1; done; exit 0 ;;\n"
        "esac\nexit 64\n",
        encoding="utf-8",
    )
    fake.chmod(0o700)
    bash = shutil.which("bash")
    assert bash is not None
    run = subprocess.run(  # noqa: S603 - fixed argv
        [bash, str(_GATE), "format", "secrets"],
        env=_ci_env(ci=False, PATH=str(bin_dir)),
        capture_output=True,
        text=True,
        check=False,
    )
    lines = run.stdout.splitlines()
    assert run.returncode == 0 and any(line.startswith("format rc=0 ") for line in lines), (
        f"the secret scan did not start beside the earlier stages: {run.stdout}"
    )
    assert [line for line in lines if line.startswith("secrets rc=")] == [
        next(line for line in lines if line.startswith("secrets rc=0 "))
    ], run.stdout


def test_g20_a_probe_run_whose_targets_did_not_restore_fails(tmp_path: Path) -> None:
    """G20 (code review R306 + R315): the probe script's EXIT cleanup (`tools/probe-restore.sh`)
    fails a run whose restored targets do not check out; it printed `RESTORE FAILED` and kept rc
    0. Acceptance: `cleanup` under its EXIT trap: a failing checksum => rc 3 + the message + the
    backup kept; a passing one => rc 0 + the backup gone; a probe failure's rc survives."""
    helper = (_REPO_ROOT / "tools" / "probe-restore.sh").read_text()
    target = tmp_path / "target"
    target.write_text("x")

    def run(checksum: str, rc: int, name: str) -> subprocess.CompletedProcess[str]:
        backup = tmp_path / name
        backup.mkdir()
        (backup / "sha256").write_text(f"{checksum}  {target}\n")
        source = f"BACKUP={str(backup)!r}; GATE=/bin/sh; TARGETS=()\n{helper}\n"
        source += "restore() { :; }\ntrap cleanup EXIT\n" + f"exit {rc}\n"
        return subprocess.run(  # noqa: S603 - the tracked helper + a fixed harness
            ["bash", "-c", source],  # noqa: S607 - bash from PATH, as the gate runs it
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=False,
        )

    good = hashlib.sha256(b"x").hexdigest()
    failed = run("0" * 64, 0, "failed")
    assert (failed.returncode, "RESTORE FAILED" in failed.stderr) == (3, True), (
        "a failed restore kept the run green",
        failed.returncode,
    )
    assert (tmp_path / "failed").is_dir()
    assert run(good, 0, "good").returncode == 0
    assert not (tmp_path / "good").exists()
    assert run(good, 1, "probe-failed").returncode == 1
