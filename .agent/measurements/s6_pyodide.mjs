import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const packageName = process.argv[2] ?? "pyodide0281";
const outputName = process.argv[3] ?? "s6.json";
const indexURL = process.argv[4];
const { loadPyodide } = await import(packageName);
const pyodide = await loadPyodide(indexURL ? { indexURL } : {});
await pyodide.loadPackage(["numpy", "pandas"]);
const dataRoot = join(root, "s6-data");
pyodide.FS.writeFile("/floats.csv", readFileSync(join(dataRoot, "floats.csv")));
pyodide.FS.writeFile("/host.f64le", readFileSync(join(dataRoot, "host.f64le")));
const result = pyodide.runPython(`
import json, platform, sys, time
import numpy as np
import pandas as pd
import pyodide
_started = time.perf_counter()
_frame = pd.read_csv("/floats.csv")
_actual = _frame.to_numpy(dtype=np.float64)
_host = np.frombuffer(open("/host.f64le", "rb").read(), dtype="<f8").reshape(_actual.shape)
_actual_bits = _actual.view(np.uint64)
_host_bits = _host.view(np.uint64)
_mismatch = _actual_bits != _host_bits
_sign = np.uint64(1 << 63)
_actual_ordered = np.where(_actual_bits & _sign, ~_actual_bits, _actual_bits | _sign)
_host_ordered = np.where(_host_bits & _sign, ~_host_bits, _host_bits | _sign)
_distance = np.maximum(_actual_ordered, _host_ordered) - np.minimum(_actual_ordered, _host_ordered)
_worst_flat = int(np.argmax(_distance))
_worst_row, _worst_column = np.unravel_index(_worst_flat, _distance.shape)
_result = {
    "python": sys.version.split()[0],
    "platform": platform.platform(),
    "pyodide": pyodide.__version__,
    "numpy": np.__version__,
    "pandas": pd.__version__,
    "rows": int(_actual.shape[0]),
    "columns": list(_frame.columns),
    "dtypes": [str(dtype) for dtype in _frame.dtypes],
    "values": int(_actual.size),
    "disagreements": int(np.count_nonzero(_mismatch)),
    "column_disagreements": {
        str(_frame.columns[index]): int(np.count_nonzero(_mismatch[:, index]))
        for index in range(_actual.shape[1])
    },
    "max_ulp": int(_distance.flat[_worst_flat]),
    "worst_row": int(_worst_row),
    "worst_column": str(_frame.columns[_worst_column]),
    "host_hex": float(_host[_worst_row, _worst_column]).hex(),
    "wasm_hex": float(_actual[_worst_row, _worst_column]).hex(),
    "seconds": round(time.perf_counter() - _started, 6),
}
json.dumps(_result)
`);
writeFileSync(join(root, outputName), `${JSON.stringify(JSON.parse(result), null, 2)}\n`);
console.log(result);
