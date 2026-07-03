# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""verifier.service — local HTTP transport around the trusted verifier (M2).

Transport only: it runs the M1 pipeline and serializes structured verdicts, adding
no trust of its own (POC_SCOPE service boundary). The dependency is one-way — the
core verifier modules never import this subpackage.
"""
