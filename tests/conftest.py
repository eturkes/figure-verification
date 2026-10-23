# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Hypothesis profiles for the test suite + the CI skip guard (G18).

The default profile is deterministic ("ci"), so every run reproduces; export
HYPOTHESIS_PROFILE=dev for broader, randomized exploratory fuzzing.
"""

import os
import re

import pytest
from hypothesis import settings

settings.register_profile("ci", derandomize=True, deadline=None)
settings.register_profile("dev", deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))

# CI exists to run every check: a skip there is a runner-image or workflow change that turned a
# check off, which only a log read would catch. Under `CI=true` a skip whose reason names no
# tracker (S8's two forms, `tests/test_spec.py`) fails the session. The xdist controller sees
# every worker's report, so it alone collects.
_TRACKER = re.compile(r"\*\*M\d+(?:\.\d+)?[a-z]?\*\*|\.agent/deferred\.md")
_collecting = False
_untracked: list[str] = []


def pytest_configure(config: pytest.Config) -> None:
    global _collecting  # noqa: PLW0603 - one flag per session, read by the report hook
    _collecting = os.environ.get("CI") == "true" and not hasattr(config, "workerinput")


def _collect(report: pytest.TestReport | pytest.CollectReport) -> None:
    if _collecting and report.skipped:
        reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
        if not _TRACKER.search(reason):
            _untracked.append(f"{report.nodeid}: {reason}")


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    _collect(report)


def pytest_collectreport(report: pytest.CollectReport) -> None:
    # A module-level `pytest.importorskip` skips at collection: no test report ever names it.
    _collect(report)


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    for line in _untracked:
        terminalreporter.write_line(f"untracked skip under CI: {line}")


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if _untracked and exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
