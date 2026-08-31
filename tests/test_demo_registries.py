# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Exact-name and literal-cardinality pins for both demo scenario registries.

Each ``run_walkthrough``-shaped loop reports PASS over an EMPTY scenario tuple, so an
emptied or silently shortened registry ships a 0/0 success while every other gate stays
green. Both registries therefore need their exact NAME set AND their cardinality pinned
as hand-stated literals, never derived from the production tuple under test.
"""

from pathlib import Path

import pytest

from demo import formula_walkthrough, walkthrough

_DATASET_SCENARIO_NAMES = (
    "direct render + invalid UTF-8",
    "model stub success",
    "model stub decode failure",
    "three formal obligations",
    "unknown solver fail-closed",
    "certificate check shape",
    "restart + LRU + archived replay",
    "distinct dataset certificate hashes",
    "verifier-version drift",
    "durable failed-attempt audit CLI",
    "archive integrity guards",
    "capacity + quota fail-closed",
    "transaction rollback",
)

_FORMULA_SCENARIO_NAMES = (
    "formula direct flow",
    "formula proposed flow",
    "formula certificate check shape",
    "formula failed attempt audit cli",
    "formula archive integrity guards",
)


def test_dataset_registry_holds_exactly_thirteen_named_scenarios() -> None:
    names = tuple(name for name, _ in walkthrough._SCENARIOS)
    assert names == _DATASET_SCENARIO_NAMES
    assert len(walkthrough._SCENARIOS) == 13


def test_formula_registry_holds_exactly_five_named_scenarios() -> None:
    names = tuple(name for name, _ in formula_walkthrough._FORMULA_SCENARIOS)
    assert names == _FORMULA_SCENARIO_NAMES
    assert len(formula_walkthrough._FORMULA_SCENARIOS) == 5


@pytest.mark.parametrize(
    ("registry", "expected"),
    [
        (walkthrough._SCENARIOS, _DATASET_SCENARIO_NAMES),
        (formula_walkthrough._FORMULA_SCENARIOS, _FORMULA_SCENARIO_NAMES),
    ],
)
def test_registry_entries_bind_distinct_callables(
    registry: tuple[tuple[str, object], ...],
    expected: tuple[str, ...],
) -> None:
    assert len({name for name, _ in registry}) == len(expected)
    assert len({id(scenario) for _, scenario in registry}) == len(expected)


def test_dataset_loop_reports_exactly_the_registry_it_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the loop to the module attribute, so a bypassing refactor cannot report 0/0."""

    def _ok(_temp_dir: Path) -> str:
        return "ok"

    monkeypatch.setattr(walkthrough, "_SCENARIOS", (("only", _ok),))
    report = walkthrough.run_walkthrough()
    assert (report.total, report.passed, report.failed) == (1, 1, 0)
    assert tuple(result.name for result in report.results) == ("only",)


def test_formula_loop_reports_exactly_the_registry_it_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _ok(_temp_dir: Path) -> str:
        return "ok"

    monkeypatch.setattr(formula_walkthrough, "_FORMULA_SCENARIOS", (("only", _ok),))
    report = formula_walkthrough.run_formula_walkthrough()
    assert (report.total, report.passed, report.failed) == (1, 1, 0)
    assert tuple(result.name for result in report.results) == ("only",)
