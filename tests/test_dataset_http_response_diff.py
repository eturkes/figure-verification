# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Adversarial closure for the dataset HTTP differential's source isolation."""

from __future__ import annotations

import runpy
from pathlib import Path
from types import FunctionType
from typing import cast

_ROOT = Path(__file__).resolve().parent.parent


def test_differential_child_imports_verifier_from_target_tree(tmp_path: Path) -> None:
    target = tmp_path / "target"
    package = target / "src/verifier"
    package.mkdir(parents=True)
    expected = package / "__init__.py"
    expected.write_text("# isolated target package\n", encoding="utf-8")

    namespace = runpy.run_path(str(_ROOT / "tests/dataset_http_response_diff.py"))
    run = cast("FunctionType", namespace["_run"])
    run.__globals__["_PROGRAM"] = (
        "from pathlib import Path\nimport verifier\nprint(Path(verifier.__file__).resolve())\n"
    )

    observed = Path(run(target).decode("utf-8").strip())

    assert observed == expected.resolve()
