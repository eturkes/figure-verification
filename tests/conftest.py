# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Hypothesis profiles for the test suite.

The default profile is deterministic ("ci"), so every run reproduces; export
HYPOTHESIS_PROFILE=dev for broader, randomized exploratory fuzzing.
"""

import os

from hypothesis import settings

settings.register_profile("ci", derandomize=True, deadline=None)
settings.register_profile("dev", deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))
