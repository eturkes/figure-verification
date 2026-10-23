#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# The one gate command. A human, an agent and CI all run exactly this, so the recorded
# result is the same claim in all three places.
#
#     bash tools/gate.sh               # every stage
#     bash tools/gate.sh <stage> ...   # the named stages alone: CI's fan-out runs one per job
#
# Stages run to completion even after one fails: a single run reports every problem
# rather than only the first, which is what makes one invocation enough. `set -e` is
# therefore deliberately absent.
set -uo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$REPO_ROOT" || exit 1

# Non-interactive shells inherit no uv project env; the nested .venv-model / .venv-webui
# layers make an unset UV_PROJECT_ENVIRONMENT ambiguous rather than merely default.
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-.venv}"
export UV_LINK_MODE="${UV_LINK_MODE:-copy}"

failed=()
skipped=()
# The stages a run names; empty = every stage. `seen` collects each stage the run reaches, so a
# name matching none fails the run instead of passing with nothing checked.
selected=()
unselected=()
seen=()

# Every run blocks the critical path, so each result line carries its wall-clock (`CLAUDE.md`
# `Execution`). A stamp = EPOCHREALTIME in microseconds; stripping every non-digit drops the
# locale's decimal separator, whichever it is.
stamp() {
    printf '%s' "${EPOCHREALTIME//[!0-9]/}"
}

elapsed() {
    local us=$(($(stamp) - $1))
    printf '%d.%d' $((us / 1000000)) $((us / 100000 % 10))
}

member() {
    local needle="$1" item
    shift
    for item in "$@"; do
        [ "$item" = "$needle" ] && return 0
    done
    return 1
}

is_selected() {
    seen+=("$1")
    if [ "${#selected[@]}" -eq 0 ] || member "$1" "${selected[@]}"; then
        return 0
    fi
    unselected+=("$1")
    return 1
}

stage() {
    local name="$1" start
    is_selected "$name" || return 0
    start="$(stamp)"
    shift
    printf '\n=== %s ===\n' "$name"
    "$@"
    local rc=$?
    printf '%s rc=%d %ss\n' "$name" "$rc" "$(elapsed "$start")"
    if [ "$rc" -ne 0 ]; then
        failed+=("$name")
    fi
    return 0
}

secret_scan() {
    # Tracked files only: .verifier-state/signing.key and every other gitignored local
    # artifact must never be read, let alone hashed into the baseline.
    local files=()
    mapfile -t files < <(git ls-files)
    uv run --locked detect-secrets-hook --baseline .secrets.baseline "${files[@]}"
}

# Demo Open WebUI residuals, ignored only while no fix exists (a release with a fix turns the stage
# red). Chroma: the four cover its HTTP server's endpoints + RBAC provider; with CHROMA_HTTP_HOST
# unset Open WebUI runs the embedded PersistentClient and no Chroma server listens.
WEBUI_RESIDUALS=(
    GHSA-f4j7-r4q5-qw2c # chromadb: pre-auth code injection, collections endpoint
    GHSA-36p7-vc44-83pf # chromadb: code injection, collection update endpoint
    GHSA-xph7-9rjv-w5fr # chromadb: SimpleRBACAuthorizationProvider ignores the scope
    GHSA-2wm9-hf6c-p5cr # chromadb: server authorization missing per tenant
)

audit_locks() {
    local root_rc=0 runtime_rc=0 webui_rc=0 suite_rc=0 harness_rc=0 ignores=() id
    for id in "${WEBUI_RESIDUALS[@]}"; do
        ignores+=(--ignore-until-fixed "$id")
    done
    uv audit --preview-features audit-command || root_rc=$?
    printf 'root-lock audit rc=%d\n' "$root_rc"
    uv audit --preview-features audit-command --locked --project model_backend/runtime || runtime_rc=$?
    printf 'model_backend/runtime audit rc=%d\n' "$runtime_rc"
    uv audit --preview-features audit-command --locked --project webui/runtime "${ignores[@]}" || webui_rc=$?
    printf 'webui/runtime audit rc=%d\n' "$webui_rc"
    uv audit --preview-features audit-command --locked --project tools/py311 || suite_rc=$?
    printf 'tools/py311 audit rc=%d\n' "$suite_rc"
    # The Node measurement harness: pnpm comes from the harness's own `packageManager` pin, exits 1
    # on any advisory and fails on a registry error. A host without pnpm fails the stage.
    pnpm audit --dir .agent/measurements || harness_rc=$?
    printf '.agent/measurements audit rc=%d\n' "$harness_rc"
    if [ "$root_rc" -ne 0 ] || [ "$runtime_rc" -ne 0 ] || [ "$webui_rc" -ne 0 ] || [ "$suite_rc" -ne 0 ] ||
        [ "$harness_rc" -ne 0 ]; then
        return 1
    fi
    return 0
}

# The shipped pair runs in Open WebUI's own interpreter, CPython 3.11 in the official image
# (M21.2 F11), and so does the nucllei tool (its image: python:3.11-slim-bookworm, Q82). The bare run holds the repository at the project's 3.14; the second pass re-reads
# the shipped sources against 3.11 syntax + stdlib, in its own cache so the two never evict.
type_check() {
    local bare_rc=0 shipped_rc=0
    uv run --locked mypy || bare_rc=$?
    uv run --locked mypy --python-version 3.11 --cache-dir .mypy_cache/py311 src/verifier webui/paste_in nucllei_skill || shipped_rc=$?
    printf 'shipped-sources py3.11 types rc=%d\n' "$shipped_rc"
    if [ "$bare_rc" -ne 0 ] || [ "$shipped_rc" -ne 0 ]; then
        return 1
    fi
    return 0
}

shell_lint() {
    local files=()
    mapfile -t files < <(git ls-files '*.sh')
    shellcheck -- "${files[@]}" || return $?
    # A blanket disable would let a real finding ride through a green gate. The pattern is a
    # regex rather than the literal so this line does not match itself.
    if git grep -nE 'shellcheck +disable=' -- '*.sh'; then
        printf 'blanket shellcheck disables are banned\n' >&2
        return 1
    fi
    return 0
}

# pytest's own coverage report holds the verifier core at 100% branch (pyproject `[tool.coverage]`).
# `--durations` names the slowest tests: a suite's wall-clock alone says nothing about where it goes.
# `-n auto` = one pytest-xdist worker per CPU: the suite was 62% of the serial gate, and pytest-cov
# combines the workers' coverage data before the floor is read.
run_tests() {
    uv run --locked pytest -n auto --durations=10
}

# The same suite on CPython 3.11, the official image's line (M21.2 F16): `tests` runs 3.14, whose
# stdlib differs in behaviour as well as names (builtin `sum` is Neumaier from 3.12). Its own lock,
# since some root pins need 3.12; `verifier` from `src`. The interpreter runs directly, so a test's
# own `uv` call keeps the root `.venv`.
run_tests_py311() {
    UV_PROJECT_ENVIRONMENT="$REPO_ROOT/.venv-py311" uv sync --locked --quiet --project tools/py311 || return $?
    PYTHONPATH=src .venv-py311/bin/python -m pytest -n auto -q -p no:cacheprovider --no-cov --durations=10 \
        -o 'pythonpath=src tests .'
}

# Named so tools/fast-gate.sh runs the same commands.
format_check() {
    uv run --locked ruff format --check .
}

lint_check() {
    uv run --locked ruff check .
}

workflow_check() {
    uv run --locked zizmor .github/
}

# Shape of the attached state. A template file (`CLAUDE.md` `Session flow`): each refresh copies
# it in whole, so a fix lands in the template, never here.
spec_check() {
    sh .agent/spec-lint .agent/spec.md
}

main() {
    local gate_start name
    gate_start="$(stamp)"
    selected=("$@")
    stage format format_check
    stage lint lint_check
    stage types type_check
    stage tests run_tests
    stage tests311 run_tests_py311
    stage audit audit_locks
    stage secrets secret_scan
    stage workflows workflow_check
    stage spec spec_check

    if command -v shellcheck >/dev/null 2>&1; then
        stage shell shell_lint
    elif is_selected shell; then
        skipped+=(shell)
        printf '\n=== shell ===\nshell SKIPPED (shellcheck absent from PATH)\n'
    fi

    printf '\n=== gate ===\n'
    for name in "${selected[@]}"; do
        if ! member "$name" "${seen[@]}"; then
            printf 'unknown stage: %s\n' "$name"
            failed+=("$name")
        fi
    done
    if [ "${#unselected[@]}" -ne 0 ]; then
        printf 'not selected: %s\n' "${unselected[*]}"
    fi
    if [ "${#skipped[@]}" -ne 0 ]; then
        printf 'skipped: %s\n' "${skipped[*]}"
        # CI exists to run every check: a skip there is a runner-image or workflow change that
        # turned a check off, which only a log read would catch.
        if [ "${CI:-}" = true ]; then
            printf 'skipped under CI: %s\n' "${skipped[*]}"
            failed+=("${skipped[@]}")
        fi
    fi
    if [ "${#failed[@]}" -ne 0 ]; then
        printf 'FAILED: %s\n' "${failed[*]}"
        printf 'gate rc=1 %ss\n' "$(elapsed "$gate_start")"
        exit 1
    fi
    printf 'gate rc=0 %ss\n' "$(elapsed "$gate_start")"
}

# Sourcing exposes the stage helpers without running the gate, which is how tools/gate-probe.sh
# fires the shipped shell_lint itself.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main "$@"
fi
