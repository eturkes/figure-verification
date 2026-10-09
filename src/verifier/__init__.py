# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""verifier — trusted core of the figure verifier.

The model writes a chart program; `verifier.figure.reader` reports what the finished matplotlib
figure holds, and the stdlib judge (`verifier.figure`) decides whether it may appear.
"""

__version__ = "0.2.0"
