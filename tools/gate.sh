#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# The one gate command. A human, an agent and CI all run exactly this, so the recorded
# result is the same claim in all three places.
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

stage() {
    local name="$1"
    shift
    printf '\n=== %s ===\n' "$name"
    "$@"
    local rc=$?
    printf '%s rc=%d\n' "$name" "$rc"
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

main() {
    stage format uv run --locked ruff format --check .
    stage lint uv run --locked ruff check .
    stage types uv run --locked mypy
    stage tests uv run --locked pytest
    stage audit uv audit --preview-features audit-command
    stage secrets secret_scan
    stage workflows uv run --locked zizmor .github/

    if command -v shellcheck >/dev/null 2>&1; then
        stage shell shell_lint
    else
        skipped+=(shell)
        printf '\n=== shell ===\nshell SKIPPED (shellcheck absent from PATH)\n'
    fi

    printf '\n=== gate ===\n'
    if [ "${#skipped[@]}" -ne 0 ]; then
        printf 'skipped: %s\n' "${skipped[*]}"
    fi
    if [ "${#failed[@]}" -ne 0 ]; then
        printf 'FAILED: %s\n' "${failed[*]}"
        exit 1
    fi
    printf 'gate rc=0\n'
}

# Sourcing exposes the stage helpers without running the gate, which is how tools/gate-probe.sh
# fires the shipped shell_lint itself.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main
fi
