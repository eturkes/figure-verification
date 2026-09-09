#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# Positive controls for the gate's purpose-built checks.
#
# A check that cannot fire and a clean tree emit the same green. The proven scanners (ruff,
# mypy, uv audit, detect-secrets, zizmor, shellcheck) carry their own upstream suites; the
# checks written HERE have no such backstop, so each ships the input that makes it fail and this
# script fires it: tests/test_gate.py G6-G12, tests/test_spec.py S1-S5, shell_lint's ban.
#
# Each probe mutates one tracked file, runs the single check that owns the invariant, and
# demands a nonzero rc whose output names the expected cause -- rc alone cannot say WHICH
# conjunct of a compound guard fired, and two probes here share a test on purpose. Targets are
# restored from a byte backup after every probe and again in an EXIT trap, then re-verified by
# sha256 and execute bit, so an interrupted or failing run still leaves the tree clean.
#
#     bash tools/gate-probe.sh    # every probe must report FIRED
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$REPO_ROOT" || exit 1

export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-.venv}"
export UV_LINK_MODE="${UV_LINK_MODE:-copy}"

GATE=tools/gate.sh
LAUNCH=webui/launch.sh
WORKFLOW=.github/workflows/gate.yml
DEPENDABOT=.github/dependabot.yml
OPS=.claude/rules/ops.md
TEST_GATE=tests/test_gate.py
SPEC=.agent/spec.md
DEFERRED=.agent/deferred.md
TARGETS=("$GATE" "$LAUNCH" "$WORKFLOW" "$DEPENDABOT" "$OPS" "$TEST_GATE" "$SPEC" "$DEFERRED")

BACKUP="$(mktemp -d)"
sha256sum "${TARGETS[@]}" >"$BACKUP/sha256"
for target in "${TARGETS[@]}"; do
    mkdir -p "$BACKUP/$(dirname -- "$target")"
    cp -a -- "$target" "$BACKUP/$target"
done

fired=()
missed=()
skipped=()

restore() {
    for target in "${TARGETS[@]}"; do
        cp -a -- "$BACKUP/$target" "$target"
    done
}

cleanup() {
    restore
    if sha256sum -c --quiet "$BACKUP/sha256" && [ -x "$GATE" ]; then
        rm -rf -- "$BACKUP"
    else
        printf 'RESTORE FAILED -- byte backup kept at %s\n' "$BACKUP" >&2
    fi
}
trap cleanup EXIT

verdict() {
    local name="$1" rc="$2" expect="$3" output="$4"
    if [ "$rc" -ne 0 ] && [[ $output == *"$expect"* ]]; then
        fired+=("$name")
        printf '%s FIRED rc=%d on %s\n' "$name" "$rc" "$expect"
        return 0
    fi
    missed+=("$name")
    printf '%s MISSED rc=%d -- expected nonzero rc naming %s\n' "$name" "$rc" "$expect"
    printf '%s\n' "$output" | tail -20
}

# probe <name> <suite::node> <expected cause in the output> <mutation command...>
probe() {
    local name="$1" node="$2" expect="$3"
    shift 3
    printf '\n--- %s ---\n' "$name"
    if ! "$@"; then
        missed+=("$name")
        printf '%s MUTATION FAILED\n' "$name"
        restore
        return 0
    fi
    local output rc
    output="$(uv run --locked pytest "$node" -x -q --no-cov -p no:cacheprovider 2>&1)"
    rc=$?
    restore
    verdict "$name" "$rc" "$expect" "$output"
}

append_direct_tool_step() {
    printf '      - name: Probe step outside the gate\n        run: uv run --locked pytest\n' \
        >>"$WORKFLOW"
}

plant_blanket_disable() {
    # Assembled at run time: the literal would trip the very ban this probe fires. The trailing
    # function is load-bearing -- a directive with no command after it is SC1072, which would
    # fail shell_lint one step before its ban and leave the ban itself unproven.
    printf '# %s %s=SC2086\nprobe_target() { :; }\n' shellcheck 'disable' >>"$1"
}

plant_shellcheck_finding() {
    printf 'probe_finding() { echo %s1; }\n' '$' >>"$GATE"
}

plant_uncovered_check() {
    # The name is assembled at run time: spelled in full here it would appear in this very file
    # and G12 would read it as covered.
    printf '\n\ndef test_g%s_uncovered_probe() -> None:\n    """Probe."""\n' 99 >>"$TEST_GATE"
}

plant_unarchived_closed_unit() {
    # `Phase` is the last section, so an appended line lands inside it.
    printf ' M%s.%s CLOSED (probe).\n' 99 9 >>"$SPEC"
}

probe g6-ci-gate-step tests/test_gate.py::test_g6_ci_runs_the_gate_script_and_no_tool_directly \
    'expected exactly one gate invocation' \
    sed -i 's|run: bash tools/gate.sh|run: true|' "$WORKFLOW"

probe g6-ci-direct-tool tests/test_gate.py::test_g6_ci_runs_the_gate_script_and_no_tool_directly \
    "calls 'pytest' outside the gate" \
    append_direct_tool_step

probe g6-stage-list tests/test_gate.py::test_g6_gate_script_runs_every_expected_stage \
    'assert declared == _EXPECTED_STAGES' \
    sed -i 's|^\( *\)stage secrets |\1# stage secrets |' "$GATE"

probe g7-ecosystem tests/test_gate.py::test_g7_dependabot_covers_every_lock_and_cools_down \
    'assert covered == {' \
    sed -i 's|package-ecosystem: "github-actions"|package-ecosystem: "npm"|' "$DEPENDABOT"

probe g7-cooldown tests/test_gate.py::test_g7_dependabot_covers_every_lock_and_cools_down \
    'assert update["cooldown"]["default-days"] >= 7' \
    sed -i '0,/default-days: 7/s//default-days: 1/' "$DEPENDABOT"

probe g8-sha-pin tests/test_gate.py::test_g8_every_action_reference_is_sha_pinned \
    'is not SHA-pinned' \
    sed -i 's|actions/checkout@[0-9a-f]\{40\}|actions/checkout@v7|' "$WORKFLOW"

probe g9-permissions tests/test_gate.py::test_g9_workflows_declare_least_privilege_permissions \
    'assert workflow["permissions"] == {"contents": "read"}' \
    sed -i 's|^  contents: read$|  contents: write|' "$WORKFLOW"

probe g9-persist-credentials tests/test_gate.py::test_g9_checkout_does_not_persist_credentials \
    'assert step["with"]["persist-credentials"] is False' \
    sed -i 's|persist-credentials: false|persist-credentials: true|' "$WORKFLOW"

probe g10-exec-bit tests/test_gate.py::test_g10_gate_script_is_executable_and_free_of_blanket_disables \
    'S_IXUSR' \
    chmod -x "$GATE"

probe g10-blanket-disable tests/test_gate.py::test_g10_gate_script_is_executable_and_free_of_blanket_disables \
    'not in _GATE.read_text' \
    plant_blanket_disable "$GATE"

probe g11-ops-records-the-gate tests/test_gate.py::test_g11_ops_rules_record_the_gate_invocation \
    'assert "tools/gate.sh" in _OPS_RULES.read_text' \
    sed -i 's|tools/gate\.sh|tools/gate-renamed.sh|g' "$OPS"

probe g12-probe-coverage tests/test_gate.py::test_g12_every_static_config_check_ships_a_positive_control \
    'no positive control in gate-probe.sh for' \
    plant_uncovered_check

probe s1-section-set tests/test_spec.py::test_s1_spec_carries_the_five_sections_in_order \
    'assert headings == _EXPECTED_SECTIONS' \
    sed -i 's|^## Deferred$|## Backlog|' "$SPEC"

probe s2-artifacts-path tests/test_spec.py::test_s2_every_artifacts_path_is_tracked \
    'Artifacts names untracked paths' \
    sed -i 's|tools/gate-probe\.sh|tools/gate-absent.sh|' "$SPEC"

probe s3-acceptance-check tests/test_spec.py::test_s3_every_deferral_carries_an_acceptance_check \
    'deferral rows with no acceptance check' \
    sed -i '0,/Accept:/s//Someday:/' "$DEFERRED"

probe s4-dangling-pointer tests/test_spec.py::test_s4_every_rules_docs_and_archive_pointer_resolves \
    'dangling pointers' \
    sed -i 's|\.claude/rules/ops\.md|.claude/rules/absent.md|' "$SPEC"

probe s5-unarchived-contract tests/test_spec.py::test_s5_every_closed_unit_has_its_contract_archived \
    'm99u9.md absent from .agent/archive/contracts/' \
    plant_unarchived_closed_unit

# The last two need the binary itself: without it the pytest node skips (rc 0, indistinguishable
# from a check that cannot fire) and shell_lint would fail at 127 rather than on its own ban.
if command -v shellcheck >/dev/null 2>&1; then
    probe g10-shellcheck tests/test_gate.py::test_g10_gate_script_passes_shellcheck \
        'assert completed.returncode == 0' \
        plant_shellcheck_finding

    printf '\n--- shell-ban ---\n'
    plant_blanket_disable "$LAUNCH"
    # Sourced, never reimplemented: the probe must fire the shipped function's own grep.
    shell_output="$(bash -c 'source tools/gate.sh; shell_lint' 2>&1)"
    shell_rc=$?
    restore
    verdict shell-ban "$shell_rc" 'blanket shellcheck disables are banned' "$shell_output"
else
    skipped+=(g10-shellcheck shell-ban)
    printf '\nSKIPPED (shellcheck absent from PATH): g10-shellcheck shell-ban\n'
fi

printf '\n=== gate-probe ===\n'
printf 'fired: %d\n' "${#fired[@]}"
if [ "${#skipped[@]}" -ne 0 ]; then
    printf 'skipped: %s\n' "${skipped[*]}"
fi
if [ "${#missed[@]}" -ne 0 ]; then
    printf 'MISSED: %s\n' "${missed[*]}"
    exit 1
fi
printf 'gate-probe rc=0\n'
