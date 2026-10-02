# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Compare encoded reduction bits/dtypes/order; named one-bit positive control."""

import json
import math
import struct
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "r-data"


def compare(left, right):
    details = []
    rows = floats = 0
    sections = [("exact", left["exact"], right["exact"])]
    sections += [("csv/" + name, left["csv"][name], right["csv"][name]) for name in left["csv"]]
    for section, lhs, rhs in sections:
        if lhs["input_value_bits_sha256"] != rhs["input_value_bits_sha256"]:
            details.append(
                {
                    "path": section + "/input_hash",
                    "left": lhs["input_value_bits_sha256"],
                    "right": rhs["input_value_bits_sha256"],
                }
            )
        for operation in lhs["reductions"]:
            ls, rs = lhs["reductions"][operation], rhs["reductions"][operation]
            details.extend(
                {"path": f"{section}/{operation}/{field}", "left": ls[field], "right": rs[field]}
                for field in ("dtype", "index_dtype")
                if ls[field] != rs[field]
            )
            if len(ls["rows"]) != len(rs["rows"]):
                details.append(
                    {
                        "path": f"{section}/{operation}/length",
                        "left": len(ls["rows"]),
                        "right": len(rs["rows"]),
                    }
                )
            for index, (lv, rv) in enumerate(zip(ls["rows"], rs["rows"], strict=False)):
                rows += 1
                floats += lv[1]["kind"] == "float"
                if lv != rv:
                    details.append(
                        {"path": f"{section}/{operation}/{index}", "left": lv, "right": rv}
                    )
    special_cases = 0
    for name, lhs in left["special"].items():
        rhs = right["special"][name]
        special_cases += 1
        if lhs != rhs:
            details.append({"path": "special/" + name, "left": lhs, "right": rhs})
    return {
        "reduction_rows_compared": rows,
        "float_results_compared": floats,
        "special_cases_compared": special_cases,
        "differences": len(details),
        "details": details,
    }


def main():
    host = json.loads((ROOT / "host.json").read_text())
    # The control changes exactly one output row before the same comparison runs on WASM.
    changed = deepcopy(host)
    value = changed["exact"]["reductions"]["sum"]["rows"][0][1]
    following = math.nextafter(float.fromhex(value["hex"]), math.inf)
    value.update(hex=following.hex(), le=struct.pack("<d", following).hex())
    positive = compare(host, changed)
    assert positive["differences"] == 1, positive
    answer = {
        "positive_control": {
            "expected_differences": 1,
            "observed_differences": positive["differences"],
            "detail": positive["details"],
        }
    }
    for name in ("pyodide", "pyodide0281"):
        sandbox = json.loads((ROOT / (name + ".json")).read_text())
        answer[name] = {"environment": sandbox["environment"], **compare(host, sandbox)}
    (ROOT / "comparison.json").write_text(json.dumps(answer, indent=2, sort_keys=True) + "\n")
    print(json.dumps(answer, sort_keys=True))


if __name__ == "__main__":
    main()
