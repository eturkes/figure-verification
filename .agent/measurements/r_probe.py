# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Same executable experiment on host and both pinned Pyodide builds."""

import csv
import hashlib
import importlib
import io
import json
import locale
import math
import platform
import struct
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent / "r-data"
OPERATIONS = ("sum", "mean", "min", "max", "count", "size")


def bits(value):
    return struct.pack("<d", float(value)).hex()


def encode(value):
    if isinstance(value, (float, np.floating)):
        value = float(value)
        return {"kind": "float", "hex": value.hex(), "le": bits(value)}
    if isinstance(value, (bool, np.bool_)):
        return {"kind": "bool", "value": bool(value)}
    if isinstance(value, (int, np.integer)):
        return {"kind": "int", "dec": str(value)}
    if value is None:
        return {"kind": "none"}
    return {"kind": type(value).__name__, "value": str(value)}


def ordered(value):
    word = int.from_bytes(struct.pack("<d", float(value)), "little")
    return (~word & ((1 << 64) - 1)) if word >> 63 else (word | (1 << 63))


def ulp(left, right):
    return abs(ordered(left) - ordered(right))


def sum_left(values):
    acc = 0.0
    for value in values:
        acc += value
    return acc


def kahan(values, *, reset_nan=True):
    acc = comp = 0.0
    for value in values:
        corrected = value - comp
        total = acc + corrected
        comp = (total - acc) - corrected
        if reset_nan and math.isnan(comp):
            comp = 0.0
        acc = total
    return acc


def neumaier(values):
    acc = comp = 0.0
    for value in values:
        total = acc + value
        comp += (acc - total) + value if abs(acc) >= abs(value) else (value - total) + acc
        acc = total
    return acc + comp


def series_encode(series):
    return {
        "dtype": str(series.dtype),
        "index_dtype": str(series.index.dtype),
        "rows": [[encode(key), encode(value)] for key, value in series.items()],
    }


def frame_result(frame, **kwargs):
    grouped = frame.groupby("k", **kwargs)["v"]
    return {operation: series_encode(getattr(grouped, operation)()) for operation in OPERATIONS}


def mismatch_stats():
    return {
        "compared": 0,
        "finite_bit_mismatches": 0,
        "category_splits": 0,
        "nonfinite_bit_mismatches": 0,
        "raised": 0,
        "max_ulp": 0,
        "worst": None,
        "first": None,
    }


def compare(stats, actual, candidate, witness):
    stats["compared"] += 1
    actual = float(actual)
    if isinstance(candidate, str):
        stats["raised"] += 1
        if stats["first"] is None:
            stats["first"] = {"witness": witness, "actual": encode(actual), "error": candidate}
        return
    candidate = float(candidate)
    if math.isfinite(actual) and math.isfinite(candidate):
        if bits(actual) != bits(candidate):
            stats["finite_bit_mismatches"] += 1
            distance = ulp(actual, candidate)
            detail = {
                "witness": witness,
                "actual": encode(actual),
                "candidate": encode(candidate),
                "ulp": distance,
            }
            if stats["first"] is None:
                stats["first"] = detail
            if distance > stats["max_ulp"]:
                stats["max_ulp"] = distance
                stats["worst"] = detail
    else:
        same_category = (math.isnan(actual) and math.isnan(candidate)) or actual == candidate
        if not same_category:
            stats["category_splits"] += 1
            if stats["first"] is None:
                stats["first"] = {
                    "witness": witness,
                    "actual": encode(actual),
                    "candidate": encode(candidate),
                }
        elif bits(actual) != bits(candidate):
            stats["nonfinite_bit_mismatches"] += 1


def safe_call(function, values):
    try:
        return function(values)
    except (OverflowError, ValueError) as exc:
        return f"{type(exc).__name__}: {exc}"


def cohort(frame, names):
    groupby = frame.groupby("k")["v"]
    reductions = {operation: getattr(groupby, operation)() for operation in OPERATIONS}
    algorithms = {
        "naive": sum_left,
        "fsum": math.fsum,
        "kahan_reset": kahan,
        "kahan_plain": lambda values: kahan(values, reset_nan=False),
        "neumaier": neumaier,
    }
    comparisons = {algorithm: mismatch_stats() for algorithm in algorithms}
    mean_comparisons = {
        "pandas_sum_div_count": mismatch_stats(),
        "kahan_div_count": mismatch_stats(),
        "naive_div_count": mismatch_stats(),
        "fsum_div_count": mismatch_stats(),
    }
    extrema_comparisons = {name: mismatch_stats() for name in ["min", "max"]}
    witnesses = {}
    grouped_rows = {}
    for key, value in zip(frame["k"], frame["v"], strict=True):
        if pd.isna(key):
            continue
        grouped_rows.setdefault(key, []).append(float(value))
    for key, raw_values in grouped_rows.items():
        values = [value for value in raw_values if not math.isnan(value)]
        name = names.get(key, str(key))
        actual = float(reductions["sum"].loc[key])
        candidate = {
            algorithm: safe_call(function, values) for algorithm, function in algorithms.items()
        }
        for algorithm, value in candidate.items():
            compare(comparisons[algorithm], actual, value, name)
        n = len(values)
        mean = float(reductions["mean"].loc[key])
        mean_values = {"pandas_sum_div_count": actual / n if n else math.nan}
        for label in ["kahan_reset", "naive", "fsum"]:
            value = candidate[label]
            mean_values[("kahan" if label == "kahan_reset" else label) + "_div_count"] = (
                value if isinstance(value, str) else value / n if n else math.nan
            )
        for algorithm, value in mean_values.items():
            compare(mean_comparisons[algorithm], mean, value, name)
        for operation, function in [("min", min), ("max", max)]:
            compare(
                extrema_comparisons[operation],
                reductions[operation].loc[key],
                function(values, default=math.nan),
                name,
            )
        if not name.startswith(("random-", "g")):
            witnesses[name] = {
                "count": n,
                "size": len(raw_values),
                "prefix": [encode(value) for value in raw_values[:4]],
                "suffix": [encode(value) for value in raw_values[-3:]],
                "pandas": {
                    operation: encode(reductions[operation].loc[key]) for operation in OPERATIONS
                },
                "algorithms": {
                    algorithm: value if isinstance(value, str) else encode(value)
                    for algorithm, value in candidate.items()
                },
            }
    encoded = {operation: series_encode(series) for operation, series in reductions.items()}
    return {
        "rows": len(frame),
        "groups": len(grouped_rows),
        "dtypes": {key: str(value) for key, value in frame.dtypes.items()},
        "input_value_bits_sha256": hashlib.sha256(
            frame["v"].to_numpy(dtype="<f8").tobytes()
        ).hexdigest(),
        "comparisons": comparisons,
        "mean_comparisons": mean_comparisons,
        "extrema_comparisons": extrema_comparisons,
        "witnesses": witnesses,
        "reductions": encoded,
    }


def special_probes():
    answer = {}
    specials = {
        "nan_values": pd.DataFrame(
            {
                "k": ["mixed", "mixed", "mixed", "all", "all", "single"],
                "v": [1.0, math.nan, 2.0, math.nan, math.nan, 7.0],
            }
        ),
        "signed_zeros": pd.DataFrame(
            {
                "k": ["np", "np", "pn", "pn", "nn", "nn", "pp", "pp"],
                "v": [-0.0, 0.0, 0.0, -0.0, -0.0, -0.0, 0.0, 0.0],
            }
        ),
        "nan_keys": pd.DataFrame(
            {"k": ["b", None, "a", math.nan, "b"], "v": [1.0, 2.0, 3.0, 4.0, 5.0]}
        ),
        "empty_float": pd.DataFrame(
            {"k": pd.Series([], dtype=object), "v": pd.Series([], dtype="float64")}
        ),
        "empty_category": pd.DataFrame(
            {
                "k": pd.Categorical(["present", "present"], categories=["empty", "present"]),
                "v": [1.0, math.nan],
            }
        ),
        "string_order": pd.DataFrame(
            {
                "k": ["z", "Z", "a", "A", "ä", "é", "2", "10", "β", "\uff21", "a"],
                "v": [float(i) for i in range(11)],
            }
        ),
        "numeric_order": pd.DataFrame(
            {"k": [10.0, -2.0, 2.0, 0.0, -0.0, 1.5, 10.0], "v": [float(i) for i in range(7)]}
        ),
        "mixed_order": pd.DataFrame(
            {
                "k": pd.Series(["2", 2, "a", -1, 1.5, "10", 0, "A"], dtype=object),
                "v": [float(i) for i in range(8)],
            }
        ),
        "mixed_numeric_equality": pd.DataFrame(
            {
                "k": pd.Series([1, True, 1.0, "1", False, 0.0], dtype=object),
                "v": [float(i) for i in range(6)],
            }
        ),
        "integer_profile_sum": pd.DataFrame(
            {"k": ["int"] * 2, "v": pd.Series([2**31 - 1, 1], dtype="int64")}
        ),
        "integer_exact": pd.DataFrame(
            {"k": ["int"] * 3, "v": pd.Series([2**53, 1, 0], dtype="int64")}
        ),
        "integer_max_overflow": pd.DataFrame(
            {"k": ["int"] * 2, "v": pd.Series([2**63 - 1, 1], dtype="int64")}
        ),
        "integer_min_overflow": pd.DataFrame(
            {"k": ["int"] * 2, "v": pd.Series([-(2**63), -1], dtype="int64")}
        ),
        "integer_mean_cast": pd.DataFrame(
            {"k": ["int"] * 3, "v": pd.Series([2**53 + 1, 2**53 + 1, 2**53 + 1], dtype="int64")}
        ),
        "integer_cancel_mean": pd.DataFrame(
            {"k": ["int"] * 3, "v": pd.Series([2**53 + 1, -(2**53), 1], dtype="int64")}
        ),
        "admitted_int_bar_overflow": pd.DataFrame(
            {"k": ["int"] * 2, "v": pd.Series([2**31 - 1, 2**31 - 1], dtype="int64")}
        ),
    }
    for name, frame in specials.items():
        kwargs = {"observed": False} if name == "empty_category" else {}
        answer[name] = {
            "dtypes": {key: str(value) for key, value in frame.dtypes.items()},
            "input_keys": [encode(value) for value in frame["k"]],
            "default": frame_result(frame, **kwargs),
        }
        if "order" in name or "keys" in name or "equality" in name:
            answer[name]["sort_false"] = frame_result(frame, sort=False, **kwargs)
        if name == "nan_keys":
            answer[name]["dropna_false"] = frame_result(frame, dropna=False)
        if name == "empty_category":
            answer[name]["observed_true"] = frame_result(frame, observed=True)
        if name.startswith("integer"):
            ints = [int(value) for value in frame["v"]]
            exact = sum(ints)
            answer[name]["python_exact_sum"] = str(exact)
            answer[name]["python_exact_sum_div_count"] = encode(exact / len(ints))
            answer[name]["float_kahan_div_count"] = encode(
                kahan([float(value) for value in ints]) / len(ints)
            )
            summed = frame.groupby("k")["v"].sum().iloc[0]
            answer[name]["pandas_int_sum_div_count"] = encode(int(summed) / len(ints))
    csvs = {
        "string_numeric_mix": "k,v\n2,1\na,2\n10,3\n2,4\n",
        "numeric_keys": "k,v\n10,1\n2,2\n-1,3\n2.0,4\n",
        "leading_zeros": "k,v\n01,1\n1,2\n001,3\n",
        "bool_keys": "k,v\nTrue,1\nFalse,2\nTrue,3\n",
        "integer_profile": "k,v\na,2147483647\na,2147483647\nb,-2147483648\nb,-2147483648\n",
    }
    for name, text in csvs.items():
        frame = pd.read_csv(io.StringIO(text))
        answer["csv_" + name] = {
            "csv": text,
            "dtypes": {key: str(value) for key, value in frame.dtypes.items()},
            "default": frame_result(frame),
        }
    return answer


def run():
    started = time.perf_counter()
    optional = {}
    for name in ["bottleneck", "numexpr"]:
        try:
            module = importlib.import_module(name)
            optional[name] = {"importable": True, "version": module.__version__}
        except ImportError as exc:
            optional[name] = {"importable": False, "error": str(exc)}
    environment = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "locale": locale.setlocale(locale.LC_COLLATE),
        "optional": optional,
        "options": {
            key: pd.get_option(key) for key in ["compute.use_bottleneck", "compute.use_numexpr"]
        },
    }
    try:
        environment["pyodide"] = importlib.import_module("pyodide").__version__
    except ImportError:
        environment["pyodide"] = None
    cases = json.loads((ROOT / "cases.json").read_text())["cases"]
    names = {index: case["name"] for index, case in enumerate(cases)}
    keys = []
    values = []
    for index, case in enumerate(cases):
        keys.extend([index] * len(case["hex"]))
        values.extend(float.fromhex(value) for value in case["hex"])
    exact_frame = pd.DataFrame({"k": keys, "v": pd.Series(values, dtype="float64")})
    results = {
        "environment": environment,
        "exact": cohort(exact_frame, names),
        "special": special_probes(),
        "csv": {},
    }
    for name in ["stress", "profile"]:
        frame = pd.read_csv(ROOT / (name + ".csv"))
        results["csv"][name] = cohort(frame, names if name == "stress" else {})
        if name == "profile":
            with (ROOT / "profile.csv").open(newline="") as stream:
                stdlib = [float(row["v"]) for row in csv.DictReader(stream)]
            results["csv"][name]["stdlib_parse_bit_mismatches"] = sum(
                bits(left) != bits(right) for left, right in zip(stdlib, frame["v"], strict=True)
            )
    results["option_matrix"] = []
    for use_bottleneck in [False, True]:
        for use_numexpr in [False, True]:
            with pd.option_context(
                "compute.use_bottleneck", use_bottleneck, "compute.use_numexpr", use_numexpr
            ):
                option_result = frame_result(exact_frame)
                special_result = special_probes()
            results["option_matrix"].append(
                {
                    "use_bottleneck": use_bottleneck,
                    "use_numexpr": use_numexpr,
                    "exact_result_identical": option_result == results["exact"]["reductions"],
                    "special_result_identical": special_result == results["special"],
                }
            )
    results["options_off"] = {
        key: results["option_matrix"][0][key]
        for key in ["exact_result_identical", "special_result_identical"]
    }
    # Expected positive control: the tiny-tail witness distinguishes naive from pandas.
    control = results["exact"]["witnesses"]["one-plus-tiny-1000"]
    assert control["pandas"]["sum"]["le"] != control["algorithms"]["naive"]["le"]
    assert control["pandas"]["sum"]["le"] == control["algorithms"]["kahan_reset"]["le"]
    results["positive_control"] = {
        "expected": "naive differs; kahan-reset matches on one-plus-tiny-1000",
        "fired": True,
        "witness": control,
    }
    results["seconds"] = round(time.perf_counter() - started, 3)
    return results


def summary(result):
    return {
        "environment": result["environment"],
        "cohorts": {
            name: {
                "rows": data["rows"],
                "groups": data["groups"],
                "sum": {
                    algorithm: {
                        key: value for key, value in stats.items() if key not in {"first", "worst"}
                    }
                    for algorithm, stats in data["comparisons"].items()
                },
                "mean": {
                    algorithm: {
                        key: value for key, value in stats.items() if key not in {"first", "worst"}
                    }
                    for algorithm, stats in data["mean_comparisons"].items()
                },
            }
            for name, data in [("exact", result["exact"]), *result["csv"].items()]
        },
        "options_off": result["options_off"],
        "positive_control": result["positive_control"]["fired"],
        "seconds": result["seconds"],
    }


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        result = run()
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "host.json"
    destination.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps(summary(result), sort_keys=True))
