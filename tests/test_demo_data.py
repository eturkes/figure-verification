# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The demo CSVs hold no cell pandas reads as missing (code review R305).

A program reads `data/*.csv` with `pd.read_csv`, whose default NA spellings turn a region code `NA`
or a label `None` into NaN: the chart then draws a gap or drops a category the file holds, and a
banner arm or a corpus case grades that instead of the data. `data/deliberately_dirty.csv` holds
them on purpose and is the control.
"""

from pathlib import Path

import pandas as pd  # type: ignore[import-untyped]

_DATA = Path(__file__).resolve().parents[1] / "data"
_DIRTY = _DATA / "deliberately_dirty.csv"


def test_no_demo_csv_cell_reads_as_missing() -> None:
    sources = sorted(path for path in _DATA.glob("*.csv") if path != _DIRTY)
    assert sources, "no demo CSVs found"
    missing = {
        path.name: int(frame.isna().to_numpy().sum())
        for path in sources
        if (frame := pd.read_csv(path)).isna().to_numpy().any()
    }
    assert not missing, f"demo CSV cells pandas reads as missing: {missing}"


def test_the_dirty_control_holds_cells_pandas_reads_as_missing() -> None:
    assert pd.read_csv(_DIRTY).isna().to_numpy().any()
