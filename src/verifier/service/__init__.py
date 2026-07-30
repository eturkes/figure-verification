# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""verifier.service — local HTTP transport around the trusted verifier.

Transport only: it runs the core pipeline and serializes structured verdicts, adding
no trust of its own (POC_SCOPE service boundary). The dependency is one-way — the
core verifier modules never import this subpackage.
"""
