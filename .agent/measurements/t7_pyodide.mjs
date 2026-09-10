import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const root = "/home/eturkes/Projects/figure-verification/.scratch/spike-m13u5b";
const modulePath = `${root}/pyodide-index/pyodide.mjs`;
const { loadPyodide } = await import(pathToFileURL(modulePath).href);
const pyodide = await loadPyodide();
await pyodide.loadPackage(["numpy", "pandas"]);
for (const name of [
  "t7-decimals.csv",
  "t7-decimals-quoted.csv",
  "t7-decimals.f64le",
  "t7-integers.csv",
  "t7-integers-quoted.csv",
  "t7-integers.f64le",
]) {
  pyodide.FS.writeFile(`/${name}`, readFileSync(`${root}/${name}`));
}
pyodide.FS.writeFile(
  "/utf8.csv",
  new TextEncoder().encode('地域,売上\n東京,1.25\n"大阪,中央",2.50\n"名古屋""北",3.75\n'),
);
const result = pyodide.runPython(`
import csv, json, sys
import numpy as np
import pandas as pd
import pyodide

out = {}
for kind in ("decimals", "integers"):
    reference = np.frombuffer(open(f"/t7-{kind}.f64le", "rb").read(), dtype="<f8")
    for form, suffix in (("plain", ""), ("quoted", "-quoted")):
        frame = pd.read_csv(f"/t7-{kind}{suffix}.csv")
        observed = frame["x"].to_numpy(dtype=np.float64)
        out[f"{kind}_{form}"] = {
            "rows": len(frame),
            "source_dtype": str(frame["x"].dtype),
            "bit_mismatches_vs_host_stdlib_float": int(np.count_nonzero(observed.view(np.uint64) != reference.view(np.uint64))),
        }
with open("/utf8.csv", newline="", encoding="utf-8") as source:
    raw_rows = list(csv.reader(source, strict=True))
utf8_frame = pd.read_csv("/utf8.csv")
utf8_result = {
    "stdlib_rows": raw_rows,
    "pandas_columns": utf8_frame.columns.tolist(),
    "pandas_x": utf8_frame["地域"].tolist(),
    "pandas_y_hex": [value.hex() for value in utf8_frame["売上"].tolist()],
    "x_text_equal": utf8_frame["地域"].tolist() == [row[0] for row in raw_rows[1:]],
    "y_bit_mismatches": int(np.count_nonzero(
        utf8_frame["売上"].to_numpy().view(np.uint64)
        != np.asarray([float(row[1]) for row in raw_rows[1:]], dtype=np.float64).view(np.uint64)
    )),
}
json.dumps({
    "python": sys.version.split()[0],
    "pyodide": pyodide.__version__,
    "pandas": pd.__version__,
    "numpy": np.__version__,
    "results": out,
    "utf8_spot_check": utf8_result,
})
`);
writeFileSync(`${root}/t7-pyodide.json`, `${result}\n`);
console.log(result);
