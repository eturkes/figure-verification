import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const root = "/home/eturkes/Projects/figure-verification/.scratch/spike-m13u5b";
const source = "/home/eturkes/Projects/figure-verification/.scratch/spike-m13u5/s6-data/floats.csv";
const modulePath = "/home/eturkes/Projects/figure-verification/.scratch/spike-m13u5b/pyodide-index/pyodide.mjs";
const { loadPyodide } = await import(pathToFileURL(modulePath).href);
const pyodide = await loadPyodide();
await pyodide.loadPackage(["numpy", "pandas", "matplotlib"]);
pyodide.FS.writeFile("/floats.csv", readFileSync(source));
const result = await pyodide.runPythonAsync(`
import csv, io, json, sys
from collections import Counter
from typing import Any
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyodide

LINE_ROWS = 20_000
BAR_ROWS = 1_024

def mismatch_count(left, right):
    left64 = np.asarray(left, dtype=np.float64)
    right64 = np.asarray(right, dtype=np.float64)
    assert left64.shape == right64.shape
    return int(np.count_nonzero(left64.view(np.uint64) != right64.view(np.uint64)))

def typename(value: Any):
    cls = type(value)
    return f"{cls.__module__}.{cls.__qualname__}"

frame = pd.read_csv("/floats.csv")
with open("/floats.csv", newline="", encoding="ascii") as source_file:
    stress_tokens = [row["stress"] for row in csv.DictReader(source_file)][:BAR_ROWS]
x = frame["shortest"].iloc[:LINE_ROWS]
y = frame["g17"].iloc[:LINE_ROWS]
assert x.dtype == np.dtype(np.float64) and y.dtype == np.dtype(np.float64)
expected_xy = np.column_stack((x.to_numpy(copy=False), y.to_numpy(copy=False)))

figure, axis = plt.subplots()
axis.set_autoscale_on(False)
axis.set(xlim=(-1.0, 1.0), ylim=(-1.0, 1.0))
line = axis.plot(x, y)[0]
figure.canvas.draw()
line_xy = line.get_xydata()
line_result = {
    "rows": LINE_ROWS,
    "artist_dtype": str(line_xy.dtype),
    "artist_shape": list(line_xy.shape),
    "bit_mismatches": mismatch_count(expected_xy, line_xy),
}
plt.close(figure)

figure, axis = plt.subplots()
axis.set_autoscale_on(False)
axis.set(xlim=(-1.0, 1.0), ylim=(-1.0, 1.0))
collection = axis.scatter(x, y)
figure.canvas.draw()
offsets = np.asarray(collection.get_offsets())
scatter_result = {
    "rows": LINE_ROWS,
    "artist_dtype": str(offsets.dtype),
    "artist_shape": list(offsets.shape),
    "bit_mismatches": mismatch_count(expected_xy, offsets),
}
plt.close(figure)

bar_y = frame["stress"].iloc[:BAR_ROWS]
bar_x = pd.Series(np.arange(BAR_ROWS), dtype=np.int64)
assert bar_y.dtype == np.dtype(np.float64)
figure, axis = plt.subplots()
axis.set_autoscale_on(False)
axis.set(xlim=(-1.0, 1.0), ylim=(-1.0, 1.0))
container = axis.bar(bar_x, bar_y)
figure.canvas.draw()
heights = [rectangle.get_height() for rectangle in container.patches]
height_array = np.asarray(heights, dtype=np.float64)
bar_expected = bar_y.to_numpy(copy=False)
bar_mismatch = np.flatnonzero(bar_expected.view(np.uint64) != height_array.view(np.uint64))
bar_pairs = Counter((bar_expected[int(i)].item().hex(), height_array[int(i)].item().hex()) for i in bar_mismatch)
bar_result = {
    "rows": BAR_ROWS,
    "height_types": sorted(set(map(typename, heights))),
    "array_dtype": str(height_array.dtype),
    "bit_mismatches": int(bar_mismatch.size),
    "mismatch_tokens": dict(sorted(Counter(stress_tokens[int(i)] for i in bar_mismatch).items())),
    "mismatch_hex_pairs": {f"{left} -> {right}": count for (left, right), count in sorted(bar_pairs.items())},
}
plt.close(figure)

figure, axis = plt.subplots()
stress_line = axis.plot(bar_x, bar_y)[0]
stress_scatter = axis.scatter(bar_x, bar_y)
figure.canvas.draw()
stress_expected = np.column_stack((bar_x.to_numpy(dtype=np.float64), bar_expected))
stress_result = {
    "rows": BAR_ROWS,
    "line_bit_mismatches": mismatch_count(stress_expected, stress_line.get_xydata()),
    "scatter_bit_mismatches": mismatch_count(stress_expected, np.asarray(stress_scatter.get_offsets())),
}
plt.close(figure)

integer_csv = b"x,y\\n0,-9223372036854775808\\n1,-9007199254740993\\n2,-9007199254740992\\n3,-1\\n4,0\\n5,9007199254740991\\n6,9007199254740992\\n7,9223372036854775807\\n"
integer_frame = pd.read_csv(io.BytesIO(integer_csv))
assert list(map(str, integer_frame.dtypes)) == ["int64", "int64"]
figure, axis = plt.subplots()
axis.set_autoscale_on(False)
axis.set(xlim=(-1.0, 1.0), ylim=(-1.0, 1.0))
integer_line = axis.plot(integer_frame["x"], integer_frame["y"])[0]
figure.canvas.draw()
integer_line_xy = integer_line.get_xydata()
plt.close(figure)

safe_integer_frame = pd.read_csv(io.BytesIO(b"x,y\\n0,-1073741824\\n1,-1\\n2,0\\n3,1\\n4,1073741824\\n"))
figure, axis = plt.subplots()
safe_integer_bars = axis.bar(safe_integer_frame["x"], safe_integer_frame["y"])
figure.canvas.draw()
safe_integer_heights = [rectangle.get_height() for rectangle in safe_integer_bars.patches]
plt.close(figure)

bar_probe_values = [
    -(2**63), -(2**53), -(2**32), -(2**31) - 1, -(2**31), -(2**31) + 1,
    -1, 0, 1, 2**31 - 1, 2**31, 2**31 + 1, 2**32, 2**53, 2**63 - 1,
]
integer_bar_probes = []
for value in bar_probe_values:
    figure, axis = plt.subplots()
    try:
        probe = axis.bar(pd.Series([0], dtype=np.int64), pd.Series([value], dtype=np.int64))
        height = probe.patches[0].get_height()
        integer_bar_probes.append({"value": value, "ok": True, "height": int(height), "height_type": typename(height)})
    except Exception as exc:
        integer_bar_probes.append({"value": value, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        plt.close(figure)
integer_result = {
    "line_rows": len(integer_frame),
    "line_dtype": str(integer_line_xy.dtype),
    "line_y_bit_mismatches_vs_numpy_float64_cast": mismatch_count(integer_frame["y"].to_numpy(dtype=np.float64), integer_line_xy[:, 1]),
    "safe_bar_rows": len(safe_integer_frame),
    "safe_rectangle_height_types": sorted(set(map(typename, safe_integer_heights))),
    "safe_rectangle_heights_exact_as_int": bool(safe_integer_heights == safe_integer_frame["y"].tolist()),
    "safe_height_float64_bit_mismatches_vs_numpy_float64_cast": mismatch_count(safe_integer_frame["y"].to_numpy(dtype=np.float64), np.asarray(safe_integer_heights, dtype=np.float64)),
    "bar_boundary_probes": integer_bar_probes,
}

labels = pd.Series(["beta", "alpha", "beta", "gamma"], dtype=object)
label_heights = pd.Series([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
figure, axis = plt.subplots()
string_container = axis.bar(labels, label_heights)
figure.canvas.draw()
lefts = [rectangle.get_x() for rectangle in string_container.patches]
widths = [rectangle.get_width() for rectangle in string_container.patches]
centers = [left + width / 2 for left, width in zip(lefts, widths, strict=True)]
string_result = {
    "input_labels": labels.tolist(),
    "input_dtype": str(labels.dtype),
    "left_edges": [float(value) for value in lefts],
    "left_edge_types": [typename(value) for value in lefts],
    "widths": [float(value) for value in widths],
    "width_types": [typename(value) for value in widths],
    "centers": [float(value) for value in centers],
    "center_types": [typename(value) for value in centers],
    "axis_mapping": [[key, float(value)] for key, value in axis.xaxis.units._mapping.items()],
}
plt.close(figure)

json.dumps({
    "python": sys.version.split()[0],
    "pyodide": pyodide.__version__,
    "pandas": pd.__version__,
    "numpy": np.__version__,
    "matplotlib": matplotlib.__version__,
    "line": line_result,
    "scatter": scatter_result,
    "float_bar": bar_result,
    "float_stress_line_scatter": stress_result,
    "integer_paths": integer_result,
    "string_bar": string_result,
})
`);
writeFileSync(`${root}/t6.json`, `${result}\n`);
console.log(result);
