# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Figure integrity (M19): a sandbox reader reports the finished figure, a stdlib judge decides.

Law = `.claude/rules/figure.md`. `reader` is the one module importing matplotlib, numpy and pandas,
lazily; every other module here is stdlib-only, so the paste-in inlines it.
"""
