import csv
import io
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd
from pandas._libs.parsers import STR_NA_VALUES

ROOT = Path(__file__).resolve().parent


def csv_bytes(values: list[str], *, quote_all: bool = False) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(
        stream, quoting=csv.QUOTE_ALL if quote_all else csv.QUOTE_MINIMAL, lineterminator="\n"
    )
    writer.writerow(["id", "x"])
    for index, value in enumerate(values):
        writer.writerow([index, value])
    return stream.getvalue().encode("utf-8")


def scalar(value: Any) -> Any:
    if pd.isna(value):
        return "<NA>"
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        if math.isinf(value):
            return value.hex()
        return {"repr": repr(value), "hex": value.hex()}
    return value


na_results: dict[str, Any] = {}
for token in sorted(STR_NA_VALUES):
    modes: dict[str, Any] = {}
    for mode, quote_all in (("minimal_quoting", False), ("all_quoted", True)):
        data = csv_bytes(["1", token, "2"], quote_all=quote_all)
        frame = pd.read_csv(io.BytesIO(data))
        modes[mode] = {
            "bytes": repr(data),
            "dtype": str(frame["x"].dtype),
            "is_na": bool(pd.isna(frame.loc[1, "x"])),
            "rows": len(frame),
        }
    na_results[repr(token)] = modes

cases = {
    "all_integer": ["1", "2", "-3"],
    "integer_with_na": ["1", "NA", "2"],
    "integer_and_decimal": ["1", "2.5", "-3"],
    "integer_and_exponent": ["1", "2e3", "-3"],
    "ordinary_text": ["1", "abc", "2"],
    "hex_integer": ["1", "0x10", "2"],
    "underscore_integer": ["1", "1_000", "2"],
    "comma_thousands": ["1", "1,000", "2"],
    "overflow_float": ["1", "1e309", "2"],
    "positive_inf": ["1", "inf", "2"],
    "capital_nan_not_default_na": ["1", "NAN", "2"],
    "signed_int64": [str(-(2**63)), str(2**63 - 1)],
    "unsigned_int64": [str(2**63), str(2**64 - 1)],
    "beyond_uint64": ["1", str(2**64), "2"],
    "mixed_negative_and_above_int64": ["-1", str(2**63)],
    "leading_zero_integer": ["01", "002", "0003"],
    "plus_sign_integer": ["+1", "2", "+3"],
    "integer_negative_zero": ["-0", "0", "1"],
    "decimal_negative_zero": ["-0.0", "0.0", "1.0"],
    "spaces_around_integer": [" 1 ", "2", " -3"],
}
dtype_results: dict[str, Any] = {}
for name, values in cases.items():
    data = csv_bytes(values)
    frame = pd.read_csv(io.BytesIO(data))
    dtype_results[name] = {
        "bytes": repr(data),
        "dtype": str(frame["x"].dtype),
        "values": [scalar(value) for value in frame["x"].tolist()],
    }

payload = {
    "python": __import__("sys").version.split()[0],
    "pandas": pd.__version__,
    "str_na_values": sorted(STR_NA_VALUES),
    "na_token_count": len(STR_NA_VALUES),
    "na_results": na_results,
    "dtype_cases": len(cases),
    "dtype_results": dtype_results,
}
(ROOT / "t5.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
print(json.dumps(payload, sort_keys=True))
