#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# Positive controls for the gate's purpose-built checks.
#
# A check that cannot fire and a clean tree emit the same green. The proven scanners (ruff,
# mypy, uv audit, detect-secrets, zizmor, shellcheck) carry their own upstream suites; the
# checks written HERE have no such backstop, so each ships the input that makes it fail and this
# script fires it: tests/test_gate.py G6-G25, tests/test_spec.py S1-S11, shell_lint's ban.
#
# Each probe mutates one tracked file (s8-ticked-row-not-a-tracker alone writes two: the skip and
# its ticked Tasks row), runs the single check that owns the invariant, and demands a nonzero rc
# whose output names the expected cause: attribution rides the message, since eleven tests carry
# more than one probe -- G6, G7, G10, G13 and S9 two each, S3 three, G16 and G17 four each, S4 six, S6 five, S8 five -- one
# per conjunct of a compound guard, per detection path, or per widened surface. Targets are
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
OWUI=.claude/rules/owui.md
TEST_GATE=tests/test_gate.py
SPEC=.agent/spec.md
PHASE_RECORD=.agent/archive/phase.md
DEFERRED=.agent/deferred.md
REVIEW=.agent/review.md
ARTIFACT=paste-in/figure_verification_tool.py
SPDX_PROBE=tools/mutate.py
PYPROJECT=pyproject.toml
WEBUI_RUNTIME=webui/runtime/pyproject.toml
CONFTEST=tests/conftest.py
TRACKERS=tests/trackers.py
FAST_GATE=tools/fast-gate.sh
SPEC_LINT=.agent/spec-lint
RESTORE=tools/probe-restore.sh
TARGETS=("$RESTORE" "$GATE" "$LAUNCH" "$WORKFLOW" "$DEPENDABOT" "$OPS" "$OWUI" "$TEST_GATE" "$SPEC" "$PHASE_RECORD" "$DEFERRED" "$REVIEW" "$ARTIFACT" "$SPDX_PROBE" "$PYPROJECT" "$WEBUI_RUNTIME" "$CONFTEST" "$TRACKERS" "$FAST_GATE" "$SPEC_LINT")

BACKUP="$(mktemp -d)"
sha256sum "${TARGETS[@]}" >"$BACKUP/sha256"
for target in "${TARGETS[@]}"; do
    mkdir -p "$BACKUP/$(dirname -- "$target")"
    cp -a -- "$target" "$BACKUP/$target"
done

fired=()
missed=()
skipped=()

# shellcheck source=tools/probe-restore.sh
source "tools/probe-restore.sh"
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
    # Assembled at run time: this file sits inside the surface the ban scans. The trailing
    # function keeps shellcheck clean -- a directive with no command after it is SC1072, which
    # fails shell_lint one step before its ban and leaves the ban unproven.
    printf '# %s %s=SC2086\nprobe_target() { :; }\n' shellcheck 'disable' >>"$1"
}

plant_shellcheck_finding() {
    printf 'probe_finding() { echo %s1; }\n' '$' >>"$GATE"
}

plant_unquoted_test() {
    printf '[ %sf = x ] && :\n' '$' >>"$1"
}

plant_uncovered_check() {
    # Name assembled at run time: G12 scans this file, so a literal would read as covered.
    printf '\n\ndef test_g%s_uncovered_probe() -> None:\n    """Probe."""\n' 99 >>"$TEST_GATE"
}

strip_spdx_header() {
    local header
    IFS= read -r header <"$SPDX_PROBE"
    [[ $header == '# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception' ]] || return 1
    sed -i '1d' "$SPDX_PROBE"
}

# Both S8 plants may carry literal names: S8 parses `.py` sources, so this script is outside its
# sweep, and G12 reads names in one direction only -- a suite name must appear here, never the
# reverse. The reason cites no unit and no queue path, which is the whole firing input.
plant_untracked_skip_marker() {
    printf '\n\n@pytest.mark.skip(reason="probe")\ndef test_g97_untracked_marker_probe() -> None:\n    """Probe."""\n' >>"$TEST_GATE"
}

# The one TWO-file probe: S8's ticked-row exclusion is only reachable when a skip cites a unit AND
# that unit's Tasks row is ticked, so the plant writes both (both files sit in TARGETS).
plant_ticked_row_skip() {
    printf '\n\n@pytest.mark.skip(reason="M99.7 probe")\ndef test_g94_ticked_row_probe() -> None:\n    """Probe."""\n' >>"$TEST_GATE"
    sed -i '0,/^## Tasks$/s//## Tasks\n\n- [x] abcdef0 **M99.7** probe row/' "$SPEC"
}

plant_untracked_body_skip() {
    printf '\n\ndef test_g96_untracked_body_probe() -> None:\n    """Probe."""\n    pytest.skip("probe")\n' >>"$TEST_GATE"
}

plant_untracked_param_marks() {
    printf '\n\n@pytest.mark.parametrize("v", [pytest.param(1, marks=pytest.mark.skip(reason="probe"))])\ndef test_g95_untracked_param_probe(v: int) -> None:\n    """Probe."""\n' >>"$TEST_GATE"
}

# Disables the whole planted module, which is harmless: the probe runs the S8 node in test_spec.py.
plant_untracked_module_pytestmark() {
    printf '\n\npytestmark = pytest.mark.skip(reason="probe")\n' >>"$TEST_GATE"
}

plant_untracked_class_decorator() {
    printf '\n\n@pytest.mark.skip(reason="probe")\nclass TestG94ClassDecoratorProbe:\n    def test_case(self) -> None:\n        """Probe."""\n' >>"$TEST_GATE"
}

plant_untracked_class_pytestmark() {
    printf '\n\nclass TestG93ClassPytestmarkProbe:\n    pytestmark = pytest.mark.skip(reason="probe")\n\n    def test_case(self) -> None:\n        """Probe."""\n' >>"$TEST_GATE"
}

plant_dangling_symlink() {
    rm -f -- "$DEPENDABOT"
    ln -s no-such-target "$DEPENDABOT"
}

# Assembled at run time: G22 scans this script too.
plant_machine_path() {
    printf '\nSee %shome/%s/notes.\n' / probe-user >>"$OWUI"
}

plant_loaded_import() {
    printf '\n@.claude/rules/owui.md\n' >>"$OPS"
}

plant_untracked_import() {
    printf '\n@.agent/no-such-file.md\n' >>"$OPS"
}

plant_unarchived_closed_unit() {
    # A unit's close appends its entry to the record, so the plant does too. The letter suffix is
    # the firing input for the id shape (`M12.6b` -> `m12u6b.md`) that a suffix-blind pattern skips.
    printf ' M%s.%sz CLOSED (probe).\n' 99 9 >>"$PHASE_RECORD"
}

plant_open_unit_in_phase() {
    # `Phase` is the last section, so an appended line lands inside it.
    printf ' M%s.%s OPEN (probe).\n' 99 8 >>"$SPEC"
}

plant_open_unit_in_record() {
    printf ' M%s.%s OPEN (probe).\n' 99 8 >>"$PHASE_RECORD"
}

plant_dangling_rules_pointer() {
    local bt
    bt="$(printf '\140')"
    printf '\n- Probe: %s.agent/archive/absent.md%s\n' "$bt" "$bt" >>"$OWUI"
}

plant_dangling_live_law_pointer() {
    # S4 reads backticked spans only, so the plant must carry backticks -- built from `\140`
    # because a literal one inside single quotes is SC2016, which fails shell_lint one step
    # before its ban and leaves that check unproven.
    local bt
    bt="$(printf '\140')"
    printf '\n- Probe: %s.claude/rules/absent.md%s\n' "$bt" "$bt" >>"$REVIEW"
}

plant_row_closed_past_its_entry() {
    printf '%s\n' '- Planted row with no closing check.' '' 'Accept: a paragraph after the row.' \
        >>"$DEFERRED"
}

plant_rules_pointer_after_accept() {
    local bt
    bt="$(printf '\140')"
    printf '\n- Probe: %sAccept:%s then %s.agent/archive/absent.md%s\n' "$bt" "$bt" "$bt" "$bt" >>"$OWUI"
}

plant_dangling_queue_pointer() {
    local bt
    bt="$(printf '\140')"
    printf '%s\n' '- Probe row. Accept: none.' \
        "- Probe row naming ${bt}.agent/archive/absent.md${bt}. Accept: none." >>"$DEFERRED"
}

plant_pointer_after_stray_backtick() {
    local bt
    bt="$(printf '\140')"
    printf '%s\n' "- Probe row with a stray ${bt} opener," \
        "  then ${bt}.agent/archive/absent.md${bt}. Accept: none." >>"$DEFERRED"
}

plant_stranded_contract_citation() {
    # Path assembled at run time: S7 scans every tracked file, this script included, so a literal
    # would strand permanently and fail the check it exists to fire. Planted unquoted -- a
    # backtick inside single quotes is SC2016, which fails shell_lint before its ban is reached.
    # ops.md rather than the spec, because S4 sweeps the spec too and each probe names ONE check.
    printf '\n- Probe: .agent/contracts/m%su%s.md\n' 99 9 >>"$OPS"
}

plant_artifact_byte() {
    printf ' ' >>"$ARTIFACT"
}

plant_embedded_blob() {
    # Preserve a valid wrapper while changing ONLY the tool's embedded source. B2 compares the
    # bytes and B6 parses that source; the artifact remains the sole mutated tracked file.
    "$UV_PROJECT_ENVIRONMENT/bin/python" - "$ARTIFACT" "$1" <<'PY'
from pathlib import Path
from sys import argv

path = Path(argv[1])
data = path.read_bytes()
marker = b'_SOURCES["webui.paste_in.tool"] = r' + bytes([39]) * 3 + b"\n"
assert data.count(marker) == 1
path.write_bytes(data.replace(marker, marker + argv[2].encode() + b"\n", 1))
PY
}

plant_model_description_rule() {
    "$UV_PROJECT_ENVIRONMENT/bin/python" - "$ARTIFACT" <<'PY'
from pathlib import Path
from sys import argv

path = Path(argv[1])
data = path.read_bytes()
old = b'start at zero'
assert data.count(old) == 1
path.write_bytes(data.replace(old, b'start at one', 1))
PY
}

plant_stale_probe_node() {
    # Renames a test this script names; G15 must then name the node the probe still runs.
    sed -i 's/^def test_g11_ops_rules_record_the_gate_invocation(/def test_g11_renamed(/' "$TEST_GATE"
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

probe g13-nested-lock-audit tests/test_gate.py::test_g13_audit_stage_covers_every_lock \
    'model_backend/runtime' \
    sed -i '/^    uv audit --preview-features audit-command --locked --project model_backend\/runtime /d' "$GATE"

# The pnpm half of the widening: the Node harness's lock joined G13's set, so it carries its own
# control.
probe g13-pnpm-lock-audit tests/test_gate.py::test_g13_audit_stage_covers_every_lock \
    "('pnpm', '.agent/measurements')" \
    sed -i '/^    pnpm audit --dir \.agent\/measurements /d' "$GATE"

probe g14-spdx-header tests/test_gate.py::test_g14_tracked_sources_carry_spdx_header \
    "$SPDX_PROBE" \
    strip_spdx_header

probe g15-probe-node tests/test_gate.py::test_g15_every_probe_node_names_a_test \
    'test_gate.py::test_g11_ops_rules_record_the_gate_invocation' \
    plant_stale_probe_node

probe g16-ruff-floor tests/test_gate.py::test_g16_shipped_sources_are_checked_at_the_image_python \
    'ruff floor drifted' \
    sed -i '/^"webui\/paste_in\/\*\*" = "py311"$/d' "$PYPROJECT"

probe g16-mypy-floor tests/test_gate.py::test_g16_shipped_sources_are_checked_at_the_image_python \
    '3.11 mypy pass missing' \
    sed -i '/--python-version 3.11/d' "$GATE"

probe g16-demo-floor tests/test_gate.py::test_g16_shipped_sources_are_checked_at_the_image_python \
    'demo interpreter drifted' \
    sed -i 's/^requires-python = "==3.11.\*"$/requires-python = "==3.12.*"/' "$WEBUI_RUNTIME"

probe g16-bare-mypy tests/test_gate.py::test_g16_shipped_sources_are_checked_at_the_image_python \
    'bare mypy run missing' \
    sed -i 's/^    uv run --locked mypy || bare_rc/    uv run --locked mypy src || bare_rc/' "$GATE"

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

probe g6-fetch-depth tests/test_gate.py::test_g6_checkout_fetches_full_history \
    'assert step["with"]["fetch-depth"] == 0' \
    sed -i 's|fetch-depth: 0|fetch-depth: 1|' "$WORKFLOW"

# The CI fan-out, one probe per conjunct: each mutation leaves a CI that still goes green.
probe g17-ci-trigger tests/test_gate.py::test_g17_ci_fans_out_every_stage_on_ci_branches \
    'no ci/** push trigger' \
    sed -i 's|branches: \[main, "ci/\*\*"\]|branches: [main]|' "$WORKFLOW"

probe g17-stage-matrix tests/test_gate.py::test_g17_ci_fans_out_every_stage_on_ci_branches \
    'fan-out stages drifted' \
    sed -i 's|, secrets, workflows,|, workflows,|' "$WORKFLOW"

probe g17-fail-fast tests/test_gate.py::test_g17_ci_fans_out_every_stage_on_ci_branches \
    'fail-fast matrix' \
    sed -i 's|fail-fast: false|fail-fast: true|' "$WORKFLOW"

probe g17-stage-argument tests/test_gate.py::test_g17_ci_fans_out_every_stage_on_ci_branches \
    'gate step does not pass its matrix stage' \
    sed -i 's|tools/gate.sh "[^"]*"|tools/gate.sh tests|' "$WORKFLOW"

probe g18-ci-skipped-stage tests/test_gate.py::test_g18_a_stage_skipped_under_ci_fails_the_gate \
    'a stage skipped under CI passed the gate' \
    sed -i '/failed+=(".{skipped\[@\]}")/d' "$GATE"

probe g18-ci-untracked-skip tests/test_gate.py::test_g18_an_untracked_pytest_skip_under_ci_fails_the_suite \
    'an untracked skip under CI passed the suite' \
    sed -i 's/session.exitstatus = pytest.ExitCode.TESTS_FAILED/pass/' "$CONFTEST"

probe g18-ci-closed-tracker tests/test_gate.py::test_g18_an_untracked_pytest_skip_under_ci_fails_the_suite \
    'a skip naming no open Tasks unit passed under CI' \
    sed -i 's/any(unit in spine for unit in/any(True for unit in/' "$TRACKERS"

probe g18-ci-collection-skip tests/test_gate.py::test_g18_a_collection_time_skip_under_ci_fails_the_suite \
    'a collection-time skip under CI passed the suite' \
    sed -i '/importorskip/{n;s/_collect(report)/pass/}' "$CONFTEST"

probe g21-dangling-symlink tests/test_gate.py::test_g21_every_tracked_symlink_resolves_inside_the_repository \
    'dangling symlink' \
    plant_dangling_symlink

probe g22-machine-path tests/test_gate.py::test_g22_no_live_tracked_file_names_a_home_directory \
    'machine paths in live tracked files' \
    plant_machine_path

# G23: one probe per conjunct -- each suite's argv, then the stage lines' wall-clock.
probe g23-suite-argv tests/test_gate.py::test_g23_both_suites_run_parallel_with_their_slowest_tests_and_each_stage_times_itself \
    'run_tests lost its suite argv' \
    sed -i 's/pytest -n auto --durations=10$/pytest -n auto/' "$GATE"

probe g23-py311-argv tests/test_gate.py::test_g23_both_suites_run_parallel_with_their_slowest_tests_and_each_stage_times_itself \
    'run_tests_py311 lost its suite argv' \
    sed -i 's/--no-cov --durations=10 /--no-cov /' "$GATE"

probe g23-stage-timing tests/test_gate.py::test_g23_both_suites_run_parallel_with_their_slowest_tests_and_each_stage_times_itself \
    'stage lines without wall-clock' \
    sed -i 's/^    printf .%d\.%d. .*$/    :/' "$GATE"

probe g24-hypothesis-default tests/test_gate.py::test_g24_the_default_hypothesis_profile_is_derandomized \
    'the default Hypothesis profile randomizes' \
    sed -i 's/"HYPOTHESIS_PROFILE", "ci"/"HYPOTHESIS_PROFILE", "dev"/' "$CONFTEST"

# G25: a dropped stage, then a dropped skip name.
probe g25-fast-gate-stage tests/test_gate.py::test_g25_the_fast_gate_runs_every_cheap_stage_and_names_the_rest_skipped \
    'fast-gate stages drifted' \
    sed -i '/^parallel spec spec_check$/d' "$FAST_GATE"

probe g25-fast-gate-skips tests/test_gate.py::test_g25_the_fast_gate_runs_every_cheap_stage_and_names_the_rest_skipped \
    'fast-gate skip names drifted' \
    sed -i 's/^skipped=(tests311 audit secrets coverage)$/skipped=(tests311 audit coverage)/' "$FAST_GATE"

probe g20-restore-exit tests/test_gate.py::test_g20_a_probe_run_whose_targets_did_not_restore_fails \
    'a failed restore kept the run green' \
    sed -i '/|| rc=3$/d' "$RESTORE"

probe g19-early-secrets tests/test_gate.py::test_g19_the_secret_scan_runs_beside_the_earlier_stages \
    'the secret scan did not start beside the earlier stages' \
    sed -i '/^    early secrets secret_scan$/d' "$GATE"

probe g10-exec-bit tests/test_gate.py::test_g10_gate_script_is_executable_and_free_of_blanket_disables \
    'S_IXUSR' \
    chmod a-x "$GATE"

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
    sed -i 's|^## Tasks$|## Backlog|' "$SPEC"

probe s2-artifacts-path tests/test_spec.py::test_s2_every_artifacts_path_is_tracked \
    'Artifacts names untracked paths' \
    sed -i 's|tools/gate-probe\.sh|tools/gate-absent.sh|' "$SPEC"

# Both S3 plants append, so they fire on an empty queue too.
probe s3-acceptance-check tests/test_spec.py::test_s3_every_deferral_carries_an_acceptance_check \
    'deferral rows with no acceptance check' \
    sed -i "\$a - Planted row with no closing check." "$DEFERRED"

probe s3-row-shape tests/test_spec.py::test_s3_every_deferral_carries_an_acceptance_check \
    'deferral list items that are not' \
    sed -i "\$a * Planted row. Accept: a bullet S3 never reads." "$DEFERRED"

# A row = one entry, so its `Accept:` may wrap onto the lines under it; a blank line ends the
# entry, else any later paragraph would close the row above it.
probe s3-blank-line-ends-row tests/test_spec.py::test_s3_every_deferral_carries_an_acceptance_check \
    'deferral rows with no acceptance check' \
    plant_row_closed_past_its_entry

probe s4-dangling-pointer tests/test_spec.py::test_s4_every_rules_docs_and_archive_pointer_resolves \
    'spec.md: .claude/rules/absent.md' \
    sed -i 's|\.claude/rules/ops\.md|.claude/rules/absent.md|' "$SPEC"

# The widened half: S4 sweeps the live law surface, not the spec alone, so the files added to it
# need their own control -- the spec probe passes whether or not they are swept at all.
probe s4-live-law-pointer tests/test_spec.py::test_s4_every_rules_docs_and_archive_pointer_resolves \
    'review.md: .claude/rules/absent.md' \
    plant_dangling_live_law_pointer

# The rules half of the widening: `.claude/rules/*.md` joined S4's surface, so it carries its own
# control -- the two probes above pass whether or not a rules file is swept.
probe s4-rules-pointer tests/test_spec.py::test_s4_every_rules_docs_and_archive_pointer_resolves \
    'owui.md: .agent/archive/absent.md' \
    plant_dangling_rules_pointer

# Outside a queue row `Accept:` is prose: a rules line naming it keeps every later pointer swept.
probe s4-rules-accept-tail tests/test_spec.py::test_s4_every_rules_docs_and_archive_pointer_resolves \
    'owui.md: .agent/archive/absent.md' \
    plant_rules_pointer_after_accept

# The queue half, read one row = one entry: a row's `Accept:` clause runs to that entry's end,
# never into the next row.
probe s4-queue-pointer tests/test_spec.py::test_s4_every_rules_docs_and_archive_pointer_resolves \
    'deferred.md: .agent/archive/absent.md' \
    plant_dangling_queue_pointer

# Each line of a row pairs its own backticks: joined, a stray one on the row's first line would
# pair with the next line's pointer and hide it.
probe s4-queue-line-scan tests/test_spec.py::test_s4_every_rules_docs_and_archive_pointer_resolves \
    'deferred.md: .agent/archive/absent.md' \
    plant_pointer_after_stray_backtick

probe s5-unarchived-contract tests/test_spec.py::test_s5_every_closed_unit_has_its_contract_archived \
    'm99u9z.md absent from .agent/archive/contracts/' \
    plant_unarchived_closed_unit

probe s6-open-unit-in-phase tests/test_spec.py::test_s6_the_spine_lives_in_tasks_and_phase_records_only_closed_units \
    'Phase names units (state alone' \
    plant_open_unit_in_phase

probe s6-open-unit-in-record tests/test_spec.py::test_s6_the_spine_lives_in_tasks_and_phase_records_only_closed_units \
    'the closed-unit record names units not CLOSED' \
    plant_open_unit_in_record

probe s6-closed-unit-in-tasks tests/test_spec.py::test_s6_the_spine_lives_in_tasks_and_phase_records_only_closed_units \
    'Tasks names closed units' \
    sed -i 's|^## Tasks$|## Tasks\n\n- [ ] **M99.7** CLOSED (probe).|' "$SPEC"

# One probe per malformed row shape: a tick without its sha and a row that is neither form; the
# expected text is the planted row itself, which only the row-shape assertion prints whole.
probe s6-ticked-row-without-sha tests/test_spec.py::test_s6_the_spine_lives_in_tasks_and_phase_records_only_closed_units \
    'M99.1** probe row' \
    sed -i 's|^## Tasks$|## Tasks\n\n- [x] **M99.1** probe row|' "$SPEC"

probe s6-row-neither-shape tests/test_spec.py::test_s6_the_spine_lives_in_tasks_and_phase_records_only_closed_units \
    'M99.2** probe row' \
    sed -i 's|^## Tasks$|## Tasks\n\n- **M99.2** probe row|' "$SPEC"

probe s7-stranded-contract-citation tests/test_spec.py::test_s7_every_contract_citation_survives_the_archive_move \
    'stranded contract citations' \
    plant_stranded_contract_citation

# Six detection paths, six controls. They are materially different reads -- a decorator, a call
# statement, a keyword inside a parametrize list, a module-level assignment, a class decorator, a
# class-level assignment -- so deleting the helper behind one leaves the other probes green and the
# hole unproven.
probe s8-untracked-skip-marker tests/test_spec.py::test_s8_every_disabled_case_names_what_re_enables_it \
    'untracked disabled cases' \
    plant_untracked_skip_marker

probe s8-ticked-row-not-a-tracker tests/test_spec.py::test_s8_every_disabled_case_names_what_re_enables_it \
    'test_gate.py' \
    plant_ticked_row_skip

probe s8-untracked-body-skip tests/test_spec.py::test_s8_every_disabled_case_names_what_re_enables_it \
    'untracked disabled cases' \
    plant_untracked_body_skip

probe s8-untracked-param-marks tests/test_spec.py::test_s8_every_disabled_case_names_what_re_enables_it \
    'untracked disabled cases' \
    plant_untracked_param_marks

probe s8-untracked-module-pytestmark tests/test_spec.py::test_s8_every_disabled_case_names_what_re_enables_it \
    'untracked disabled cases' \
    plant_untracked_module_pytestmark

probe s8-untracked-class-decorator tests/test_spec.py::test_s8_every_disabled_case_names_what_re_enables_it \
    'untracked disabled cases' \
    plant_untracked_class_decorator

probe s8-untracked-class-pytestmark tests/test_spec.py::test_s8_every_disabled_case_names_what_re_enables_it \
    'untracked disabled cases' \
    plant_untracked_class_pytestmark

# S10: one probe per frontmatter fault -- YAML that does not parse, an unquoted glob, a glob that
# reaches no tracked file. S11: one per import fault -- a file Claude Code loads on its own, a path
# no commit carries. Each plants into a rule file (S10 + S11 read rule files alone, so literals).
probe s10-unparsable-frontmatter tests/test_spec.py::test_s10_every_rule_frontmatter_parses_and_each_glob_reaches_a_tracked_file \
    'frontmatter does not parse' \
    sed -i '2a\  - [unclosed' "$OWUI"

probe s10-unquoted-glob tests/test_spec.py::test_s10_every_rule_frontmatter_parses_and_each_glob_reaches_a_tracked_file \
    'unquoted glob' \
    sed -i '2a\  - webui/launch.sh' "$OWUI"

probe s10-dead-glob tests/test_spec.py::test_s10_every_rule_frontmatter_parses_and_each_glob_reaches_a_tracked_file \
    'matches no tracked file' \
    sed -i '2a\  - "no-such-dir/*.probe"' "$OWUI"

probe s11-loaded-import tests/test_spec.py::test_s11_every_import_names_a_tracked_file_claude_code_leaves_unloaded \
    'which Claude Code loads on its own' \
    plant_loaded_import

probe s11-untracked-import tests/test_spec.py::test_s11_every_import_names_a_tracked_file_claude_code_leaves_unloaded \
    'which no commit carries' \
    plant_untracked_import

probe s9-phase-without-name tests/test_spec.py::test_s9_phase_names_the_phase_and_its_scope \
    'Phase opens with no phase name' \
    sed -i '/^## Phase$/,$ s|^[A-Z]\+ — |PHASE — |' "$SPEC"

probe s9-phase-without-scope tests/test_spec.py::test_s9_phase_names_the_phase_and_its_scope \
    'Phase names no scope' \
    sed -i '/^## Phase$/,$ s| — | |' "$SPEC"

probe b1-artifact-freshness tests/test_paste_in_bundle.py::test_b1_committed_artifact_equals_a_fresh_generation \
    'committed artifact(s) differ from their sources' \
    plant_artifact_byte

probe b2-embedded-identity tests/test_paste_in_bundle.py::test_b2_each_embedded_source_is_its_tracked_file_plus_one_newline \
    'webui.paste_in.tool' \
    plant_embedded_blob '# planted embedded-source drift'

probe b6-import-surface tests/test_paste_in_bundle.py::test_b6_import_surface_is_stdlib_open_webui_pydantic \
    'numpy' \
    plant_embedded_blob 'import numpy'

probe e3-description-rule tests/test_webui_python_exposure.py::test_e3_tool_description_states_the_chart_rules \
    'AssertionError: start at zero' \
    plant_model_description_rule

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

    printf '\n--- shell-spec-lint ---\n'
    plant_unquoted_test "$SPEC_LINT"
    shell_output="$(bash -c 'source tools/gate.sh; shell_lint' 2>&1)"
    shell_rc=$?
    restore
    # The finding must sit under the file's own header: SC2086 elsewhere proves nothing.
    verdict shell-spec-lint "$shell_rc" SC2086 "$(grep -A3 "In $SPEC_LINT line" <<<"$shell_output")"
else
    skipped+=(g10-shellcheck shell-ban shell-spec-lint)
    printf '\nSKIPPED (shellcheck absent from PATH): g10-shellcheck shell-ban shell-spec-lint\n'
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
