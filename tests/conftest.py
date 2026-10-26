# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Hypothesis profiles for the test suite + the CI skip guard (G18).

The default profile is deterministic ("ci"), so every run reproduces; export
HYPOTHESIS_PROFILE=dev for broader, randomized exploratory fuzzing.
"""

import os

import pytest
from hypothesis import settings

from trackers import names_tracker, open_units

settings.register_profile("ci", derandomize=True, deadline=None)
settings.register_profile("dev", deadline=None)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))

# CI exists to run every check: a skip there is a runner-image or workflow change that turned a
# check off, which only a log read would catch. Under `CI=true` a skip whose reason names no LIVE
# tracker (S8's two forms, `trackers.py`: an open `Tasks` row of the rootdir's spec, or the queue)
# fails the session. The xdist controller sees every worker's report, so it alone collects.
_collecting = False
_spine: frozenset[str] = frozenset()
_untracked: list[str] = []


def pytest_configure(config: pytest.Config) -> None:
    global _collecting, _spine  # noqa: PLW0603 - one reading per session, used by the report hook
    _collecting = os.environ.get("CI") == "true" and not hasattr(config, "workerinput")
    spec = config.rootpath / ".agent" / "spec.md"
    if _collecting and spec.is_file():
        _spine = open_units(spec.read_text(encoding="utf-8"))


def _collect(report: pytest.TestReport | pytest.CollectReport) -> None:
    if _collecting and report.skipped:
        reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
        if not names_tracker(reason, _spine):
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
