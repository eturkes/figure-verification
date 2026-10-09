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


def s6():
    return {
        build: fields(load(f"s6-{build}.json"), "values", "disagreements", "max_ulp")
        for build in BUILDS
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
            if name not in {"literal-control", "ja-no-font", "ja-mathtext"}
        },
        # M17.1 controls: the outcome CLASS of each stderr, never its platform-specific bytes.
        "controls": {
            name: {
                "png_lines": data["results"][name]["png_lines"],
                "stderr_class": glyph_class(data["results"][name]["stderr"]),
            }
            for name in ("ja-no-font", "ja-mathtext")
        },
        "literal_control_syntax_error": "SyntaxError"
        in (data["results"]["literal-control"]["stderr"] or ""),
    }


def glyph_class(stderr):
    text = stderr or ""
    if "missing from current font" in text:
        return "missing-glyph"
    if "does not have a glyph" in text:
        return "mathtext-glyph"
    return "clean" if not text else "other"


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
        # M18.4: each case's opened row, live + reload (link followed live).
        "rows": {
            row["case"]: all(
                (row.get(phase) or {}).get("row", {}).get("ok") is True
                for phase in ("live", "reload")
            )
            for row in data["results"]
        },
        "narrow_ok": data["narrow"]["ok"],
        "screenshots": len(data["shots"]),
        "ok": data["ok"],
    }


def m17():
    arms = {}
    for arm in ("ja-simple", "ja-elaborate", "ja-clinic-simple", "ja-clinic-elaborate"):
        record = load(f"all-data/m17/{arm}-1.json")
        after = record.get("after") or {}
        verdict, _, interpretation = str(after.get("content") or "").partition("\n\n")
        status = after.get("status")
        code = re.search(r"\(([a-z_]+)\)$", status or "")
        head = interpretation.split("。", 1)[0] + "。" if interpretation else None
        arms[arm] = {
            "before": (record.get("before") or {}).get("verdict"),
            "after": after.get("verdict"),
            "verdict_line": verdict,
            "interpretation_head": head,
            "file_pngs": after.get("file_pngs"),
            "status_code": code[1] if code else None,
            "status_kana": bool(status) and re.search(r"[\u3041-\u30ff]", status) is not None,
            "error": record.get("error"),
        }
    return {"arms": arms}


def i1():
    host, sandbox = load("i1-host.json"), load("i1-0283.json")
    families = sorted(
        {
            f"{child[0]}|{child[1]}|{child[2]}"
            for case in sandbox["cases"].values()
            for figure in case["figures"]
            for axes in figure["axes"]
            for child in axes["children"]
        }
    )
    return {
        "cases": len(sandbox["cases"]),
        "same_case_names": sorted(host["cases"]) == sorted(sandbox["cases"]),
        "differing_cases": sorted(
            name for name in sandbox["cases"] if sandbox["cases"][name] != host["cases"][name]
        ),
        "matplotlib": {
            "host": host["versions"]["matplotlib"],
            "sandbox": sandbox["versions"]["matplotlib"],
        },
        "sandbox_families": families,
    }


def i2():
    data = load("i2-result.json")
    return {
        name: {
            key: leg[key]
            for key in (
                "rows",
                "numeric_columns",
                "full_ties",
                "shared_points",
                "subsets",
                "chance_hits",
                "trials",
            )
            if key in leg
        }
        for name, leg in data.items()
    }


def _difference(a, b, path, out):
    if type(a) is not type(b):
        out.add(path)
    elif isinstance(a, dict):
        for key in set(a) | set(b):
            if key in a and key in b:
                _difference(a[key], b[key], key, out)
            else:
                out.add(key)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.add(path)
        for x, y in zip(a, b, strict=False):
            _difference(x, y, path, out)
    elif a != b:
        out.add(path)


def i3():
    tag = "FIGURE_VERIFICATION_DESCRIPTION:"
    host, sandbox = load("i3-host.json"), load("i3-0283.json")["results"]
    differing = {}
    for name in sorted(host):
        run = sandbox[name]
        if run["error"] or run["stderr"] or run["description"] is None:
            differing[name] = ["sandbox-fault"]
            continue
        fields = set()
        _difference(
            json.loads(host[name][len(tag) :]),
            json.loads(run["description"][len(tag) :]),
            "",
            fields,
        )
        if fields:
            differing[name] = sorted(fields)
    return {
        "programs": len(host),
        "same_programs": sorted(host) == sorted(sandbox),
        "differing_fields": differing,
        "png_lines": {
            name: run["png_lines"] for name, run in sorted(sandbox.items()) if run["png_lines"] != 1
        },
    }


def c1():
    """Judge each bundle description with its case's Sources; report every verdict that differs
    from the case's expectation or from the host verdict."""
    sys.path[:0] = [str(ROOT.parents[1] / "src"), str(ROOT.parents[1])]
    from verifier.figure.description import parse_description  # noqa: PLC0415
    from verifier.figure.judge import Passed, Sources, judge  # noqa: PLC0415

    host, sandbox = load("c1-host.json"), load("c1-0283.json")["results"]
    corpus = ROOT.parents[1] / "tests" / "figure_corpus"
    data = ROOT.parents[1] / "data"
    faults, verdicts = [], {}
    for name in sorted(host):
        case, run = host[name], sandbox[name]
        described = parse_description(run["description"] or "")
        if run["error"] or run["stderr"] or described is None:
            faults.append(name)
            continue
        files = ()
        if case["csv"] is not None:
            path = data / case["csv"]
            files = (
                (case["csv"], (path if path.is_file() else corpus / case["csv"]).read_bytes()),
            )
        outcome = judge(described, Sources(files, case["request"], case["anchoring"]))
        verdicts[name] = "pass" if isinstance(outcome, Passed) else outcome.reason
    return {
        "cases": len(host),
        "same_cases": sorted(host) == sorted(sandbox),
        "sandbox_faults": faults,
        "host_misses": {
            n: [c["expect"], c["verdict"]] for n, c in host.items() if c["verdict"] != c["expect"]
        },
        "bundle_misses": {
            n: [host[n]["expect"], v] for n, v in verdicts.items() if v != host[n]["expect"]
        },
        "host_bundle_differ": sorted(n for n, v in verdicts.items() if v != host[n]["verdict"]),
    }


PROJECTORS = {
    "S6": s6,
    "T3": t3,
    "T4": t4,
    "T5": t5,
    "T6": t6,
    "T7": t7,
    "T8": t8,
    "F7": f7,
    "Versions": versions,
    "M15": m15,
    "M16": m16,
    "M17": m17,
    "I1": i1,
    "I2": i2,
    "I3": i3,
    "C1": c1,
}

if __name__ == "__main__":
    name = sys.argv[1]
    result = PROJECTORS[name]()
    destination = ROOT / "results" / f"{name}.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
