# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Independent wire-format builders for the M10.2 observation-gate tests.

These are hand-constructed artist records, not the implementation's observer. The fixture tests
exercise the real Pyodide artist records separately; a synthetic record lets each comparison
conjunct be perturbed without relying on matplotlib in the host test environment.
"""

import json
from pathlib import Path
from typing import Any, Literal, cast

from verifier.pysrc import Verified, verify_python_source
from verifier.pysrc.spec import DatasetTarget

OBS_TAG = "FIGURE_VERIFICATION_OBSERVATION:"
# Q16: committed captures whose verbatim program G10 refuses -- design-simple-06's x label names
# `date` over x = `city`, design-simple-09's title names `orders` over y = `revenue`. Production
# never observes a refused program, so each fixture suite pins that refusal in place of a release.
LABEL_REFUSED = frozenset({"design-simple-06", "design-simple-09"})
OBS_MAX_BYTES = 16_777_216
ROOT = Path(__file__).resolve().parent.parent

type Binding = Literal["categorical", "numeric", "accessor"]


def dataset_verdict(
    mark: Literal["line", "scatter", "bar", "barh"],
    binding: Binding = "categorical",
    *,
    numeric_keys: bool = False,
    grouped: bool = False,
) -> Verified:
    """Return a real core verdict, with source bytes independent of the synthetic observation."""
    if binding == "accessor":
        content = (
            b"key,value\n10,1.25\n10,2.5\n20,3.5\n20,4.25\n"
            if numeric_keys
            else b"key,value\nwest,1.25\neast,2.5\nwest,3.5\neast,4.25\n"
        )
        assert mark in {"bar", "barh"}
        body = f'g = df.groupby("key")["value"].sum()\ng.plot(kind="{mark}")\n'
    else:
        content = (
            b"key,value\n0.000001,1.25\n0.1,2.5\n0.2,3.75\n"
            if binding == "numeric"
            else b"key,value\nwest,1.25\neast,2.5\nnorth,3\n"
        )
        if grouped:
            content = (
                b"key,value\n10,1.25\n10,2.5\n20,3.5\n20,4.25\n"
                if binding == "numeric"
                else b"key,value\nwest,1.25\neast,2.5\nwest,3.5\neast,4.25\n"
            )
            body = (
                'g = df.groupby("key")["value"].sum()\n'
                f"plt.{'plot' if mark == 'line' else mark}(g.index, g.values)\n"
            )
        else:
            body = f'plt.{"plot" if mark == "line" else mark}(df["key"], df["value"])\n'
    path = "/mnt/uploads/observe.csv"
    source = (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        f'df = pd.read_csv("{path}")\n'
        f"{body}"
        "plt.show()\n"
    )
    verdict = verify_python_source(source, declared_target=DatasetTarget(path, content))
    assert isinstance(verdict, Verified), verdict
    assert verdict.spec.mark == mark
    return verdict


def committed_sales_verdict(
    mark: Literal["line", "scatter", "bar", "barh"], *, accessor: bool = False
) -> Verified:
    """Read the committed dataset as truth, independent of the record's plotted floats."""
    assert not accessor or mark in {"bar", "barh"}
    path = "/mnt/uploads/sales.csv"
    if mark == "scatter":
        body = 'plt.scatter(df["orders"], df["revenue"])\n'
    else:
        body = 'g = df.groupby("region")["revenue"].sum()\n'
        body += (
            f'g.plot(kind="{mark}")\n'
            if accessor
            else f"plt.{'plot' if mark == 'line' else mark}(g.index, g.values)\n"
        )
    source = (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        f'df = pd.read_csv("{path}")\n'
        f"{body}"
        "plt.show()\n"
    )
    verdict = verify_python_source(
        source, declared_target=DatasetTarget(path, (ROOT / "data" / "sales.csv").read_bytes())
    )
    assert isinstance(verdict, Verified), verdict
    assert verdict.spec.mark == mark
    return verdict


def formula_verdict(
    expression: str = "np.sin(x)",
    *,
    bounds: tuple[str, str] = ("0", "1"),
    samples: int = 3,
    mark: Literal["line", "scatter"] = "line",
) -> Verified:
    """Return a real formula verdict, without a model-supplied expected value table."""
    source = (
        "import numpy as np\n"
        "import matplotlib.pyplot as plt\n"
        f"x = np.linspace({bounds[0]}, {bounds[1]}, num={samples})\n"
        f"y = {expression}\n"
        f"plt.{'plot' if mark == 'line' else 'scatter'}(x, y)\n"
        "plt.show()\n"
    )
    verdict = verify_python_source(source)
    assert isinstance(verdict, Verified), verdict
    assert verdict.spec.mark == mark
    return verdict


def observation_for(verified: Verified, binding: Binding = "numeric") -> dict[str, Any]:
    """Construct the contract's wire record from recomputed values and forward artist geometry."""
    mark = verified.spec.mark
    x_values = verified.table.x
    y_values = verified.table.y
    positions: list[float]
    units: list[list[str]] | None = None
    if binding == "categorical":
        assert all(type(x) is str for x in x_values)
        positions = [float(index) for index in range(len(x_values))]
        units = [
            [cast(str, key), position.hex()]
            for key, position in zip(x_values, positions, strict=True)
        ]
    elif binding == "accessor":
        assert mark in {"bar", "barh"}
        positions = [float(index) for index in range(len(x_values))]
    else:
        assert all(type(x) is float for x in x_values)
        positions = [cast(float, value) for value in x_values]

    ticks = [[position.hex(), str(key)] for position, key in zip(positions, x_values, strict=True)]
    position_axis: dict[str, Any] = {"units": units, "ticks": ticks}
    magnitude_axis: dict[str, Any] = {"units": None, "ticks": [[(0.0).hex(), "0"]]}
    result: dict[str, Any] = {
        "axes": 1,
        "lines": [],
        "collections": [],
        "containers": [],
        "patches": 0,
        "images": 0,
        "texts": 0,
        "xaxis": position_axis if mark != "barh" else magnitude_axis,
        "yaxis": magnitude_axis if mark != "barh" else position_axis,
    }
    if mark in {"line", "scatter"}:
        pairs = [[position.hex(), y.hex()] for position, y in zip(positions, y_values, strict=True)]
        result["lines" if mark == "line" else "collections"] = [pairs]
    else:
        if binding == "numeric":
            span = (positions[0] + 0.8) - positions[0]
        else:
            span = 0.5 if binding == "accessor" else 0.8
        patches = []
        for position, y in zip(positions, y_values, strict=True):
            edge = position - span / 2
            xywh = (edge, 0.0, span, y) if mark == "bar" else (0.0, edge, y, span)
            patches.append([value.hex() for value in xywh])
        result["containers"] = [patches]
    return result


def stdout_for(payload: dict[str, Any], *, prefix: str = "") -> str:
    """Serialize one tagged line without importing production's parser or constants."""
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return prefix + OBS_TAG + encoded + "\n"


def stdout_for_verified(verified: Verified, png: str, *, prefix: str = "") -> str:
    """Fake the sandbox's observation-first stdout from the recomputed table, not the observer."""
    binding: Binding = "categorical" if isinstance(verified.table.x[0], str) else "numeric"
    return stdout_for(observation_for(verified, binding), prefix=prefix) + png
