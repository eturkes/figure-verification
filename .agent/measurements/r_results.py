# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Project the measured outputs onto each published M13.6 claim; read no expected files."""

import json
from pathlib import Path

from r_compare import compare
from r_probe import bits, ulp

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "r-data"
RUNTIMES = ("host", "host-optional", "pyodide", "pyodide0281")


def load(name):
    return json.loads((DATA / f"{name}.json").read_text())


def mismatches(stats):
    return sum(
        stats[key]
        for key in (
            "finite_bit_mismatches",
            "category_splits",
            "nonfinite_bit_mismatches",
            "raised",
        )
    )


def cohorts(data):
    return [data["exact"], *data["csv"].values()]


def reduction(data, case, operation):
    return data["special"][case]["default"][operation]


def rows(data, case, operation):
    return reduction(data, case, operation)["rows"]


def canonical(witness):
    return {
        "pandas": witness["pandas"]["hex"],
        **{key: value["value"]["hex"] for key, value in witness["algorithms"].items()},
    }


def sum_results(data):
    profile = data["csv"]["profile"]["comparisons"]
    return {
        "kahan": {
            "groups": sum(
                value["comparisons"]["kahan_reset"]["compared"] for value in cohorts(data)
            ),
            "differences": sum(
                mismatches(value["comparisons"]["kahan_reset"]) for value in cohorts(data)
            ),
        },
        **{
            name: {
                "groups": profile[name]["compared"],
                "differences": mismatches(profile[name]),
                "max_ulp": profile[name]["max_ulp"],
            }
            for name in ("naive", "fsum")
        },
    }


def int_results(data):
    case = data["special"]["integer_exact"]
    mean = rows(data, "integer_exact", "mean")[0][1]["hex"]
    exact_mean = case["python_exact_sum_div_count"]["hex"]
    return {
        "sum_dtype": reduction(data, "integer_exact", "sum")["dtype"],
        "sum_exact": rows(data, "integer_exact", "sum")[0][1]["dec"] == case["python_exact_sum"],
        "mean_dtype": reduction(data, "integer_exact", "mean")["dtype"],
        "mean": mean,
        "cast_kahan_mean": case["float_kahan_div_count"]["hex"],
        "exact_integer_mean": exact_mean,
        "split_ulp": ulp(float.fromhex(mean), float.fromhex(exact_mean)),
        "in_profile_sum": float(rows(data, "integer_profile_sum", "sum")[0][1]["dec"]).hex(),
    }


def key_results(data):
    string_keys = [key["value"] for key, _ in rows(data, "string_order", "sum")]
    numeric_keys = [float.fromhex(key["hex"]) for key, _ in rows(data, "numeric_order", "sum")]
    return {
        "string_keys_in_codepoint_order": string_keys
        == sorted({key["value"] for key in data["special"]["string_order"]["input_keys"]}),
        "numeric_keys_in_numeric_order": numeric_keys
        == sorted(
            {float.fromhex(key["hex"]) for key in data["special"]["numeric_order"]["input_keys"]}
        ),
    }


def renderer_results(data):
    renderer = data["renderer"]
    reference = [bits(int(value)) for value in renderer["sum_ints"]]
    return {
        "sums": renderer["sum_ints"],
        "dtype": renderer["pandas_dtype"],
        "marks": {
            name: {
                key: value
                for key, value in renderer["marks"][name].items()
                if key in {"ok", "error"}
            }
            for name in ("bar", "barh", "plot", "scatter")
        },
        "bit_mismatches": {
            name: sum(
                left != right
                for left, right in zip(reference, renderer["marks"][name]["le"], strict=True)
            )
            for name in ("plot", "scatter")
        },
        "int32_controls": renderer["positive_control"],
    }


def main():
    data = {name: load(name) for name in RUNTIMES}
    sandbox = {name: load("supplement-" + name) for name in RUNTIMES[2:]}
    locales = load("locales")
    comparison = load("comparison")
    claims = {
        "R1": {
            "sum": {name: sum_results(value) for name, value in data.items()},
            "witness": {
                "host": canonical(locales["canonical_witness"]),
                **{name: canonical(value["canonical_witness"]) for name, value in sandbox.items()},
            },
        },
        "R2": {
            name: {
                "groups": sum(
                    value["mean_comparisons"]["kahan_div_count"]["compared"]
                    for value in cohorts(runtime)
                ),
                "differences": sum(
                    mismatches(value["mean_comparisons"]["kahan_div_count"])
                    for value in cohorts(runtime)
                ),
            }
            for name, runtime in data.items()
        },
        "R3": {name: int_results(value) for name, value in data.items()},
        "R4": {
            name: {
                operation: {
                    key["value"]: value["hex"]
                    for key, value in rows(runtime, "signed_zeros", operation)
                    if key["value"] in {"np", "pn"}
                }
                for operation in ("min", "max")
            }
            for name, runtime in data.items()
        },
        "R5": {
            name: rows(value, "integer_max_overflow", "sum")[0][1]["dec"]
            for name, value in data.items()
        },
        "R7": {
            "locale_orders": {
                name: value["pandas"] == value["unicode_sorted"]
                for name, value in locales["locales"].items()
            },
            "en_US_collation_differs": locales["locales"]["en_US.utf8"]["locale_sorted"]
            != locales["locales"]["en_US.utf8"]["unicode_sorted"],
            "runtime_orders": {name: key_results(value) for name, value in data.items()},
        },
        "R8": {
            name: {
                "dtype": value["special"]["csv_string_numeric_mix"]["dtypes"]["k"],
                "keys": [key["value"] for key, _ in rows(value, "csv_string_numeric_mix", "sum")],
            }
            for name, value in data.items()
        },
        "R-ACCEL": {
            "absent": {
                name: value["importable"]
                for name, value in data["host"]["environment"]["optional"].items()
            },
            "present": {
                name: value["importable"]
                for name, value in data["host-optional"]["environment"]["optional"].items()
            },
            "presence_changed_sections": sum(
                data["host"][key] != data["host-optional"][key]
                for key in (
                    "exact",
                    "csv",
                    "special",
                    "positive_control",
                    "options_off",
                    "option_matrix",
                )
            ),
            "runtime_flags": {
                name: {
                    "combinations": len(value["option_matrix"]),
                    "all_four": {
                        (row["use_bottleneck"], row["use_numexpr"])
                        for row in value["option_matrix"]
                    }
                    == {(False, False), (False, True), (True, False), (True, True)},
                    "changed_results": sum(
                        not row[key]
                        for row in value["option_matrix"]
                        for key in ("exact_result_identical", "special_result_identical")
                    ),
                }
                for name, value in data.items()
            },
        },
        "R-PORT": {
            "runtimes": {
                name: {
                    "rows": comparison[name]["reduction_rows_compared"],
                    "differences": comparison[name]["differences"],
                }
                for name in RUNTIMES[2:]
            },
            "one_bit_control": comparison["positive_control"]["observed_differences"],
        },
        "R-BAR": {name: renderer_results(value) for name, value in sandbox.items()},
    }
    # Retain the parser/control checks from the scratch experiment.
    assert locales["parser_control"]["observed_mismatches"] == 1
    assert all(value["positive_control"]["fired"] for value in data.values())
    assert compare(data["host"], data["host-optional"])["differences"] == 0
    for name, runtime in data.items():
        for value in cohorts(runtime):
            for operation in ("min", "max"):
                assert mismatches(value["extrema_comparisons"][operation]) == 0, (
                    "R4",
                    name,
                    operation,
                )
    destination = ROOT / "results"
    destination.mkdir(exist_ok=True)
    for name, result in claims.items():
        (destination / f"{name}.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n"
        )
        print(f"{name}: result={destination / (name + '.json')}")


if __name__ == "__main__":
    main()
