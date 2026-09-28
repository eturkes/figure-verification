# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Every mutation catalogue names kill tests that still exist.

A renamed test strands its catalogue's `kills` selector; pytest then exits 4 without running
anything, and a driver scoring any nonzero exit as a kill credits a test that never ran (M10.10
review F1). `tools/mutate.py` now refuses that at run time; this check catches it at gate time,
where no catalogue is run.
"""

import ast
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_CATALOGUES = (
    "adapter",
    "admit",
    "aggregate",
    "certificate",
    "csvread",
    "filter",
    "observe",
    "project",
    "receipt",
    "request",
    "score",
    "selection",
    "verify",
)


def test_the_catalogue_set_is_exactly_the_stated_thirteen() -> None:
    """A deleted or added catalogue shows here, so the parametrized sweep below never narrows."""
    assert {path.stem for path in (_ROOT / "tools" / "mutants").glob("*.toml")} == set(_CATALOGUES)


@pytest.mark.parametrize("name", _CATALOGUES)
def test_every_kill_names_an_existing_test_function(name: str) -> None:
    catalogue = tomllib.loads((_ROOT / "tools" / "mutants" / f"{name}.toml").read_text("utf-8"))
    mutants = catalogue["mutant"]
    assert mutants, f"{name}.toml holds no mutant"
    missing = []
    for mutant in mutants:
        filename, _, selector = mutant["kills"].partition("::")
        test_file = _ROOT / filename
        functions = (
            {
                node.name
                for node in ast.parse(test_file.read_text("utf-8")).body
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            }
            if test_file.is_file()
            else set()
        )
        if selector.partition("[")[0] not in functions:
            missing.append((mutant["id"], mutant["kills"]))
    assert not missing, f"{name}.toml credits tests that do not exist: {missing}"
