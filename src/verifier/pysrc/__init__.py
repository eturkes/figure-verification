# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Portable verification core for `pysrc-0.1` (model-authored Python).

Stdlib-only and importing no `verifier` sibling on purpose: M14 inlines this package into a
single file an admin pastes into an Open WebUI instance that has no outside network access, so a
dependency here becomes a dependency there. Where reuse of the shipped service code conflicts with
that isolation, isolation wins (`.claude/rules/pysrc.md`).
"""
