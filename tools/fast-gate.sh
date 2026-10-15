#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# The iteration gate (`CLAUDE.md` `Execution`): the cheap stages of tools/gate.sh over the whole
# tree in parallel, then only the tests a change reaches. It is never the claim: tests311, audit,
# secrets and coverage stay unrun, so it names them as skipped and only the full gate says green.
#
# Usage: bash tools/fast-gate.sh [<pytest node or path> ...]
set -uo pipefail

# shellcheck source=tools/gate.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/gate.sh"

fast_start="$(stamp)"
logs="$(mktemp -d)"
trap 'rm -rf -- "$logs"' EXIT
skipped=(tests311 audit secrets coverage)
names=()
pids=()

# Each stage runs in its own subshell, so its rc comes back through `wait`, never `failed`.
parallel() {
    local name="$1"
    shift
    (
        stage "$name" "$@"
        [ "${#failed[@]}" -eq 0 ]
    ) >"$logs/$name" 2>&1 &
    names+=("$name")
    pids+=("$!")
}

parallel format format_check
parallel lint lint_check
parallel types type_check
parallel workflows workflow_check
parallel spec spec_check
if command -v shellcheck >/dev/null 2>&1; then
    parallel shell shell_lint
else
    skipped+=(shell)
fi

for i in "${!names[@]}"; do
    wait "${pids[$i]}" || failed+=("${names[$i]}")
    cat -- "$logs/${names[$i]}"
done

if [ "$#" -gt 0 ]; then
    stage tests uv run --locked pytest --no-cov -q --durations=5 "$@"
else
    skipped+=(tests)
fi

printf '\n=== fast-gate ===\nskipped: %s\n' "${skipped[*]}"
if [ "${#failed[@]}" -ne 0 ]; then
    printf 'FAILED: %s\nfast-gate rc=1 %ss\n' "${failed[*]}" "$(elapsed "$fast_start")"
    exit 1
fi
printf 'fast-gate rc=0 %ss\n' "$(elapsed "$fast_start")"
