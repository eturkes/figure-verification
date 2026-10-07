# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Project raw measurements onto published claims; expectations are never an input."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILDS = ("0280", "0281")
FUNCTIONS = ("sin", "cos", "tan", "exp", "log", "sqrt")


def load(name):
    return json.loads((ROOT / name).read_text())


def fields(data, *names):
    return {name: data[name] for name in names}


def unary(data):
    return {name: fields(data[name], "samples", "disagreements", "max_ulp") for name in FUNCTIONS}


def s2():
    return {build: unary(load(f"s2-{build}.json")["functions"]) for build in BUILDS}


def s3():
    return {
        build: {
            name: {
                **fields(grid, "cases", "value_disagreements", "length_disagreements", "max_ulp"),
                "all_values_compared": grid["compared_values"] == grid["expected_values"],
            }
            for name, grid in load(f"s3-{build}.json")["grids"].items()
        }
        for build in BUILDS
    }


def s6():
    return {
        build: fields(load(f"s6-{build}.json"), "values", "disagreements", "max_ulp")
        for build in BUILDS
    }


def pow_band(data):
    return fields(data, "samples", "disagreements", "max_ulp", "category_splits")


def s7():
    return {
        **{build: pow_band(load(f"s7-{build}.json")) for build in BUILDS},
        "mapping": fields(
            load("s7-mapping.json"),
            "samples",
            "specific_mapping_disagreements",
            "blanket_value_error_to_nan_disagreements",
        ),
    }


def t3():
    return [fields(row, "digits", "samples", "mismatches") for row in load("t3.json")["results"]]


def t4():
    data = load("t4.json")["results"]
    return {
        name: data[name]["minimal_same_rows_or_same_rejection"]
        for name in (
            "utf8_bom",
            "ragged_short_then_full",
            "ragged_long_then_full",
            "junk_after_quote",
        )
    }


def t5():
    data = load("t5.json")
    return {
        "count": data["na_token_count"],
        "spellings": data["str_na_values"],
        "unrecognized_forms": sum(
            not form["is_na"] for forms in data["na_results"].values() for form in forms.values()
        ),
        "forms_tested": sum(len(forms) for forms in data["na_results"].values()),
    }


def t6():
    results = {}
    for build in BUILDS:
        data = load(f"t6-{build}.json")
        probes = data["integer_paths"]["bar_boundary_probes"]
        results[build] = {
            "line": fields(data["line"], "rows", "bit_mismatches"),
            "scatter": fields(data["scatter"], "rows", "bit_mismatches"),
            "float_bar": fields(data["float_bar"], "rows", "bit_mismatches", "mismatch_hex_pairs"),
            "integer_probes": len(probes),
            "integer_profile_holds": all(
                row["ok"] == (-2147483648 <= row["value"] <= 2147483647)
                and (
                    row["ok"]
                    or row["error"] == "OverflowError: Python int too large to convert to C long"
                )
                for row in probes
            ),
        }
    return results


def t7():
    return {
        build: {
            name: fields(row, "rows", "source_dtype", "bit_mismatches_vs_host_stdlib_float")
            for name, row in load(f"t7-{build}.json")["results"].items()
        }
        for build in BUILDS
    }


def t8():
    results = {}
    for build in (*BUILDS, "0283"):
        data = load(f"t8-{build}.json")
        renderer = data["renderer"]
        probes = renderer["integer_controls"]
        results[build] = {
            "versions": fields(data["versions"], "pyodide", "numpy", "pandas"),
            "corpora": {
                name: {
                    form: {
                        "dtype": row["dtype"],
                        "rows": row["vs_host_pandas"]["rows"],
                        "host_bit_mismatches": row["vs_host_pandas"]["bit_mismatches"],
                        "stdlib_bit_mismatches": row["vs_stdlib_float"]["bit_mismatches"],
                        "max_measured_abs": row["vs_host_pandas"]["max_measured_abs"],
                        "retained_digit_profile": fields(
                            row["vs_stdlib_float"]["retained_digit_profile"],
                            "rows",
                            "bit_mismatches",
                            "max_measured_abs",
                        ),
                        "injected_one_bit_control": row["injected_one_bit_control"],
                    }
                    for form, row in forms.items()
                }
                for name, forms in data["corpora"].items()
            },
            "renderer": {
                "matplotlib": renderer["matplotlib"],
                "float64_paths": {
                    name: fields(
                        row,
                        "rows",
                        "input_dtype",
                        "height_types",
                        "min_height",
                        "max_height",
                        "bit_mismatches_before_draw",
                        "bit_mismatches_after_draw",
                        "draw_completed",
                    )
                    for name, row in renderer["float64_paths"].items()
                },
                "integer_probes": len(probes),
                "integer_profile_holds": all(
                    row["ok"] == (-2147483648 <= row["value"] <= 2147483647)
                    and (
                        row["height"] == row["value"]
                        if row["ok"]
                        else row["error"]
                        == "OverflowError: Python int too large to convert to C long"
                    )
                    for row in probes
                ),
            },
        }
    return results


def w1():
    text = (ROOT / "all-data/W1.log").read_text()
    result = {}
    for name, pattern in (
        ("verified", r"=== design simple: (\d+)/(\d+) VERIFIED"),
        ("faithful", r"=== design simple: (\d+)/(\d+) FAITHFUL"),
        ("blocked", r"=== design complicated: (\d+)/(\d+) BLOCKED"),
    ):
        match = re.search(pattern, text)
        if match is None:
            message = f"W1 missing {name} denominator"
            raise ValueError(message)
        result[name] = {"count": int(match[1]), "total": int(match[2])}
    return result


def a1():
    data = load("a1-result.json")
    result = {
        language: {
            "faithful": leg["faithful"],
            "false_refusals": len(leg["false_refusals"]),
            "series": leg["series"],
            "series_refused": len(leg["series_refused"]),
            "swaps_verified": leg["swaps_verified"],
            "swaps_caught": leg["swaps_caught"],
            "stop_false_refusals": len(leg["stop_false_refusals"]),
            "negation_false_refusals": len(leg["negation_false_refusals"]),
            "strict_false_refusals": len(leg["strict_false_refusals"]),
            "strict_swaps_caught": leg["strict_swaps_caught"],
        }
        for language, leg in data.items()
        if language != "capture"
    }
    result["capture"] = fields(
        data["capture"],
        "design_rows",
        "baseline_verified",
        "changed",
        "faithful_refused",
        "strict_changed",
        "strict_faithful_refused",
    )
    return result


def a2():
    data = load("a2-result.json")
    result = {
        form: fields(
            leg,
            "faithful",
            "series",
            "column_plants",
            "column_caught",
            "summary_plants",
            "summary_caught",
        )
        | {
            "false_refusals": len(leg["false_refusals"]),
            "series_refused": len(leg["series_refused"]),
        }
        for form, leg in data.items()
        if form != "capture"
    }
    result["capture"] = data["capture"]
    return result


def f7():
    data = load("f7-0283.json")
    return {
        "build": data["pyodide"],
        "cases": {
            name: fields(
                row,
                "stdout_lines",
                "observation_lines",
                "observation_parseable",
                "png_lines",
                "png_second",
                "stderr",
                "result",
                "png_signature",
                "error",
            )
            for name, row in data["results"].items()
            if name != "literal-control"
        },
        "literal_control_syntax_error": "SyntaxError"
        in (data["results"]["literal-control"]["stderr"] or ""),
    }


def o8():
    data = load("o8-0283.json")
    return {
        "unary": {
            name: fields(row, "samples", "max_ulp")
            for name, row in load("s2-0283.json")["functions"].items()
        },
        "pow": fields(load("s7-0283.json"), "samples", "max_ulp", "category_splits"),
        "wrapper": fields(
            data, "build", "cases", "observations", "pngs", "stderr", "fixture_differences"
        ),
    }


def versions():
    return {
        build: fields(load(f"versions-{build}.json"), "pyodide", "numpy", "pandas")
        for build in BUILDS
    }


def m15():
    data = load("all-data/m15/m15u1_status.json")
    return {
        "cases": {row["case"]: row["ok"] for row in data["results"]},
        "texts": data["width"]["texts"],
        "clamped": len(data["width"]["clamped"]),
        "width_ok": data["width"]["ok"],
        "ok": data["ok"],
    }


def m16():
    data = load("all-data/m16/m16u1_checks.json")
    return {
        "cases": {row["case"]: row["ok"] for row in data["results"]},
        "narrow_ok": data["narrow"]["ok"],
        "screenshots": len(data["shots"]),
        "ok": data["ok"],
    }


PROJECTORS = {
    "S1": lambda: unary(load("all-data/S1.log")),
    "S2": s2,
    "S3": s3,
    "S6": s6,
    "S7": s7,
    "T3": t3,
    "T4": t4,
    "T5": t5,
    "T6": t6,
    "T7": t7,
    "T8": t8,
    "W1": w1,
    "A1": a1,
    "A2": a2,
    "F7": f7,
    "O8": o8,
    "Versions": versions,
    "M15": m15,
    "M16": m16,
}

if __name__ == "__main__":
    name = sys.argv[1]
    result = PROJECTORS[name]()
    destination = ROOT / "results" / f"{name}.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
