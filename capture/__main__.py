# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""`python -m capture` — the capture instrument's entry point.

A shim: every subcommand, argument and exit code lives in capture.harness, so the CLI is testable
through harness.main without a subprocess. The two validators keep their own module entries
(`python -m capture.corpus`, `python -m capture.record`).
"""

from capture.harness import main

if __name__ == "__main__":
    raise SystemExit(main())
