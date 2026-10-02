#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
set -euo pipefail
root=$(readlink -f "$(dirname "${BASH_SOURCE[0]}")")
project=$(readlink -f "$root/../..")
export UV_PROJECT_ENVIRONMENT="$project/.venv" UV_LINK_MODE=copy
export UV_CACHE_DIR="$project/.scratch/r-uv-cache" TMPDIR="$project/.scratch/r-tmp"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$root/r-data" "$UV_CACHE_DIR" "$TMPDIR"
run() {
    local name=$1 rc
    shift
    if "$@" > "$root/r-data/$name.log" 2>&1; then
        printf '%s rc=0\n' "$name"
    else
        rc=$?
        printf '%s rc=%s log=%s\n' "$name" "$rc" "$root/r-data/$name.log"
        cat "$root/r-data/$name.log"
        exit "$rc"
    fi
}
python=(uv run --locked --project "$project" python)
pandas=(uv run --locked --project "$project" --with pandas==2.3.1 python)
optional=(uv run --locked --project "$project" --with pandas==2.3.1 --with bottleneck==1.6.0 --with numexpr==2.14.2 python)
run corpus "${python[@]}" "$root/make_r_inputs.py"
run host "${pandas[@]}" "$root/r_probe.py" "$root/r-data/host.json"
run host-optional "${optional[@]}" "$root/r_probe.py" "$root/r-data/host-optional.json"
run pyodide node "$root/r_pyodide.mjs" pyodide pyodide.json
run pyodide0281 node "$root/r_pyodide.mjs" pyodide0281 pyodide0281.json
run comparison "${python[@]}" "$root/r_compare.py"
run locales "${pandas[@]}" "$root/r_supplement.py"
run supplement-pyodide node "$root/r_pyodide.mjs" pyodide supplement-pyodide.json supplement
run supplement-pyodide0281 node "$root/r_pyodide.mjs" pyodide0281 supplement-pyodide0281.json supplement
run results "${pandas[@]}" "$root/r_results.py"
run checks "${python[@]}" "$root/check.py" R1 R2 R3 R4 R5 R7 R8 R-ACCEL R-PORT R-BAR
cat "$root/r-data/checks.log"
