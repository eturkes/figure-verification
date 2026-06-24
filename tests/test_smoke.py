# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Smoke test: the package imports and exposes its version."""

import verifier


def test_package_exposes_version() -> None:
    assert verifier.__version__ == "0.1.0"
