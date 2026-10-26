# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Every mutation catalogue names kill tests that still exist.

A renamed test or parameter strands its catalogue's `kills` selector; pytest then exits 4 without
running anything, and a driver scoring any nonzero exit as a kill credits a test that never ran.
`tools/mutate.py` refuses that at run time; this check catches it at gate time, where no catalogue
is run, against what pytest itself collects.
"""

import functools
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_CATALOGUES = (
    "adapter",
    "aggregate",
    "aliases",
    "anchoring",
    "backend_settings",
    "checks",
    "columns",
    "computed",
    "csvread",
    "description",
    "excerpts",
    "explain",
    "figure_judge",
    "figure_request",
    "filter",
    "fonts",
    "inert",
    "interpret",
    "judge",
    "keys",
    "legends",
    "mark_rules",
    "nucllei_checks",
    "nucllei_host",
    "nucllei_run",
    "nucllei_texts",
    "nucllei_tool",
    "origin",
    "owui_files",
    "parts",
    "reader",
    "receipt",
    "reply",
    "series",
    "sfnt",
    "shapes",
    "ticks",
    "tool",
    "webui_settings",
)


def test_the_catalogue_set_is_exactly_the_stated_set() -> None:
    """A deleted or added catalogue shows here, so the parametrized sweep below never narrows."""
    assert {path.stem for path in (_ROOT / "tools" / "mutants").glob("*.toml")} == set(_CATALOGUES)


@functools.cache
def _selectors() -> frozenset[str]:
    """Every selector that runs a collected test: a node id, or a prefix of one -- a parametrized
    function without its `[id]`, or a class -- since pytest runs each."""
    argv = [sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-cov", "-p"]
    completed = subprocess.run(  # noqa: S603 - fixed argv
        [*argv, "no:cacheprovider", "tests"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    selectors = set()
    for node in completed.stdout.splitlines():
        parts = node.partition("[")[0].split("::")
        if len(parts) > 1:
            selectors |= {node} | {"::".join(parts[:end]) for end in range(2, len(parts) + 1)}
    return frozenset(selectors)


@pytest.mark.parametrize("name", _CATALOGUES)
def test_every_kill_names_an_existing_test_function(name: str) -> None:
    catalogue = tomllib.loads((_ROOT / "tools" / "mutants" / f"{name}.toml").read_text("utf-8"))
    mutants = catalogue["mutant"]
    assert mutants, f"{name}.toml holds no mutant"
    # pytest collects `test_*` functions alone: a helper name exists but still exits rc 4.
    missing = [
        (mutant["id"], mutant["kills"]) for mutant in mutants if mutant["kills"] not in _selectors()
    ]
    assert not missing, f"{name}.toml credits tests that do not exist: {missing}"


@pytest.mark.parametrize(
    "kills",
    [
        "tests/test_pysrc_aggregate.py::_aggregate",  # a helper pytest never collects
        "tests/test_mutation_catalogues.py::test_every_kill_names_an_existing_test_function[none]",
        "tests/test_no_such_module.py::test_every_kill_names_an_existing_test_function",
    ],
)
def test_a_selector_pytest_does_not_collect_is_not_a_kill(
    monkeypatch: pytest.MonkeyPatch, kills: str
) -> None:
    """A helper, a stale parameter id and a missing file each run nothing."""
    catalogue = tomllib.loads((_ROOT / "tools/mutants/aggregate.toml").read_text("utf-8"))
    catalogue["mutant"][0]["kills"] = kills
    monkeypatch.setattr(tomllib, "loads", lambda _text: catalogue)
    with pytest.raises(AssertionError, match=r"aggregate\.toml credits tests that do not exist"):
        test_every_kill_names_an_existing_test_function("aggregate")
