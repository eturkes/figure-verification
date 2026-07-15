# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""verifier — trusted core for the verified-plot PoC.

Its job, as the trusted core: the model proposes only a restricted VPlot spec;
this package validates it, independently recomputes the plotted table from the
source data, runs the verification checks, and emits only verified output with a
provenance badge. See POC_SCOPE.md for the boundary and the claim this PoC makes.
"""

__version__ = "0.2.0"
