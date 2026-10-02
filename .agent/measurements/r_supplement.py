# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Locale-order control and integer aggregate renderer boundary probes."""

import io
import json
import locale
import struct
from math import fsum
from pathlib import Path

import numpy as np
import pandas as pd
from r_probe import encode, kahan, neumaier, sum_left, ulp

ROOT = Path(__file__).resolve().parent / "r-data"


def locales():
    keys = ["z", "Z", "a", "A", "ä", "é", "2", "10", "β", "\uff21", "a"]
    frame = pd.DataFrame({"k": keys, "v": range(len(keys))})
    result = {}
    original = locale.setlocale(locale.LC_COLLATE)
    try:
        for name in ["C", "C.utf8", "en_US.utf8"]:
            try:
                locale.setlocale(locale.LC_COLLATE, name)
            except locale.Error as exc:
                result[name] = {"error": str(exc)}
                continue
            result[name] = {
                "pandas": frame.groupby("k")["v"].sum().index.tolist(),
                "unicode_sorted": sorted(set(keys)),
                "locale_sorted": sorted(set(keys), key=locale.strxfrm),
            }
    finally:
        locale.setlocale(locale.LC_COLLATE, original)
    # Expected control: en_US locale collation and Unicode order MUST differ.
    if "error" not in result["en_US.utf8"]:
        assert result["en_US.utf8"]["locale_sorted"] != result["en_US.utf8"]["unicode_sorted"]
    return result


def renderer():
    # The host locale leg needs no matplotlib; only the Pyodide renderer loads it.
    import matplotlib as mpl  # noqa: PLC0415

    mpl.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415

    text = "k,v\na,2147483647\na,2147483647\nb,-2147483648\nb,-2147483648\n"
    frame = pd.read_csv(io.StringIO(text))
    data = frame.groupby("k")["v"].sum()
    result = {
        "csv": text,
        "pandas_dtype": str(data.dtype),
        "sum_ints": [str(value) for value in data],
        "matplotlib": mpl.__version__,
        "marks": {},
    }
    for mark in ["bar", "barh", "plot", "scatter"]:
        fig, ax = plt.subplots()
        try:
            if mark == "bar":
                artist = ax.bar(data.index, data)
                values = [patch.get_height() for patch in artist.patches]
            elif mark == "barh":
                artist = ax.barh(data.index, data)
                values = [patch.get_width() for patch in artist.patches]
            elif mark == "plot":
                artist = ax.plot(data.index, data)[0]
                values = artist.get_xydata()[:, 1]
            else:
                artist = ax.scatter(np.arange(len(data)), data)
                values = np.asarray(artist.get_offsets())[:, 1]
            fig.canvas.draw()
            result["marks"][mark] = {
                "ok": True,
                "types": [type(value).__name__ for value in values],
                "hex": [float(value).hex() for value in values],
                "le": [struct.pack("<d", float(value)).hex() for value in values],
            }
        except Exception as exc:
            result["marks"][mark] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        finally:
            plt.close(fig)
    # Expected positive control: both endpoint int32 bar/barh still succeeds.
    controls = {}
    for mark in ["bar", "barh"]:
        fig, ax = plt.subplots()
        try:
            getattr(ax, mark)(["a", "b"], pd.Series([-(2**31), 2**31 - 1], dtype="int64"))
            fig.canvas.draw()
            controls[mark] = True
        finally:
            plt.close(fig)
    result["positive_control"] = controls
    return result


def canonical_witness():
    text = "k,v\na,1000000000.0\na,0.000001\na,0.000001\na,-1000000000.0\n"
    frame = pd.read_csv(io.StringIO(text))
    values = frame["v"].tolist()
    actual = float(frame.groupby("k")["v"].sum().iloc[0])
    candidates = {
        "naive": sum_left(values),
        "kahan": kahan(values),
        "fsum": fsum(values),
        "neumaier": neumaier(values),
    }
    assert encode(actual) == encode(candidates["kahan"])
    assert (
        len(
            {
                encode(actual)["le"],
                encode(candidates["naive"])["le"],
                encode(candidates["fsum"])["le"],
            }
        )
        == 3
    )
    return {
        "csv": text,
        "dtype": str(frame["v"].dtype),
        "pandas": encode(actual),
        "algorithms": {
            name: {"value": encode(value), "ulp": ulp(actual, value)}
            for name, value in candidates.items()
        },
    }


if __name__ == "__main__":
    cell = "1e-23"
    parsed = float(pd.read_csv(io.StringIO("v\n" + cell + "\n"))["v"].iloc[0])
    expected = float(cell)
    parser_control = {
        "token": cell,
        "stdlib_hex": expected.hex(),
        "pandas_hex": parsed.hex(),
        "expected_mismatches": 1,
        "observed_mismatches": int(struct.pack("<d", expected) != struct.pack("<d", parsed)),
    }
    assert parser_control["observed_mismatches"] == 1
    result = {
        "locales": locales(),
        "compute_use_numba": pd.get_option("compute.use_numba"),
        "parser_control": parser_control,
        "canonical_witness": canonical_witness(),
    }
    (ROOT / "locales.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
