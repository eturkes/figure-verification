# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# The probe script's restore + EXIT cleanup (sourced by tools/gate-probe.sh, before its trap). Its
# own file so a probe can plant a fault here while the running script keeps the copy it sourced:
# G20 (tests/test_gate.py) runs `cleanup` from this file.
# shellcheck shell=bash

restore() {
    # Unlink first: `cp` writes THROUGH a destination symlink, and G21's probe plants one.
    for target in "${TARGETS[@]}"; do
        rm -f -- "$target"
        cp -a -- "$BACKUP/$target" "$target"
    done
}

cleanup() {
    local rc=$?
    restore
    if sha256sum -c --quiet "$BACKUP/sha256" && [ -x "$GATE" ]; then
        rm -rf -- "$BACKUP"
    else
        printf 'RESTORE FAILED -- byte backup kept at %s\n' "$BACKUP" >&2
        # A run whose targets did not restore certifies nothing, whatever its probes did.
        [ "$rc" -ne 0 ] || rc=3
    fi
    exit "$rc"
}
