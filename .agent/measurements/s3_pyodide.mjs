import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadPyodide } from "pyodide";

const root = dirname(fileURLToPath(import.meta.url));
const dataRoot = join(root, "s3-data");
const manifest = JSON.parse(readFileSync(join(dataRoot, "manifest.json"), "utf8"));
const pyodide = await loadPyodide();
await pyodide.loadPackage("numpy");
const metadata = JSON.parse(
  pyodide.runPython(`
import json, platform, sys
import numpy, pyodide
json.dumps({
    "python": sys.version.split()[0],
    "platform": platform.platform(),
    "pyodide": pyodide.__version__,
    "numpy": numpy.__version__,
})
`),
);
const results = { ...metadata, seed: manifest.seed, grids: {} };

for (const kind of ["linspace", "arange"]) {
  pyodide.FS.writeFile("/params.json", readFileSync(join(dataRoot, `${kind}.json`)));
  pyodide.FS.writeFile("/host.f64le", readFileSync(join(dataRoot, `host-${kind}.f64le`)));
  pyodide.FS.writeFile(
    "/offsets.u64le",
    readFileSync(join(dataRoot, `host-${kind}-offsets.u64le`)),
  );
  const result = pyodide.runPython(`
import json, time
import numpy as np
_started = time.perf_counter()
_kind = "${kind}"
_params = json.load(open("/params.json"))
_host = np.frombuffer(open("/host.f64le", "rb").read(), dtype="<f8")
_offsets = np.frombuffer(open("/offsets.u64le", "rb").read(), dtype="<u8")
_sign = np.uint64(1 << 63)
_case_disagreements = 0
_value_disagreements = 0
_length_disagreements = 0
_dtype_disagreements = 0
_compared_values = 0
_max_ulp = 0
_worst = None
_region_results = {}
for _case_index, _param in enumerate(_params):
    _start, _stop = int(_offsets[_case_index]), int(_offsets[_case_index + 1])
    _expected = _host[_start:_stop]
    if _kind == "linspace":
        _actual_native = np.linspace(float.fromhex(_param["a"]), float.fromhex(_param["b"]), int(_param["n"]))
        _expected_dtype = "float64"
    else:
        _a, _b = int(_param["a"]), int(_param["b"])
        _actual_native = np.arange(float(_a), float(_b)) if _param["style"] == "float" else np.arange(_a, _b)
        _expected_dtype = "float64" if _param["style"] == "float" else "int64"
    _actual = _actual_native.astype(np.float64, copy=False)
    _region = _param["region"]
    _stats = _region_results.setdefault(_region, {
        "cases": 0, "values": 0, "case_disagreements": 0,
        "value_disagreements": 0, "length_disagreements": 0,
        "dtype_disagreements": 0, "max_ulp": 0,
    })
    _stats["cases"] += 1
    _stats["values"] += int(_expected.size)
    _dtype_bad = str(_actual_native.dtype) != _expected_dtype
    if _dtype_bad:
        _dtype_disagreements += 1
        _stats["dtype_disagreements"] += 1
    if _actual.size != _expected.size:
        _length_disagreements += 1
        _case_disagreements += 1
        _stats["length_disagreements"] += 1
        _stats["case_disagreements"] += 1
        continue
    _compared_values += int(_expected.size)
    _expected_bits = _expected.view(np.uint64)
    _actual_bits = _actual.view(np.uint64)
    _mismatch = _expected_bits != _actual_bits
    _mismatch_count = int(np.count_nonzero(_mismatch))
    _expected_ordered = np.where(_expected_bits & _sign, ~_expected_bits, _expected_bits | _sign)
    _actual_ordered = np.where(_actual_bits & _sign, ~_actual_bits, _actual_bits | _sign)
    _distance = np.maximum(_expected_ordered, _actual_ordered) - np.minimum(_expected_ordered, _actual_ordered)
    _case_max = int(np.max(_distance)) if _distance.size else 0
    _stats["value_disagreements"] += _mismatch_count
    _stats["max_ulp"] = max(_stats["max_ulp"], _case_max)
    _value_disagreements += _mismatch_count
    if _mismatch_count or _dtype_bad:
        _case_disagreements += 1
        _stats["case_disagreements"] += 1
    if _case_max > _max_ulp:
        _max_ulp = _case_max
        _element_index = int(np.argmax(_distance))
        _worst = {
            "case_index": _case_index,
            "element_index": _element_index,
            "parameter": _param,
            "host_hex": float(_expected[_element_index]).hex(),
            "wasm_hex": float(_actual[_element_index]).hex(),
        }
_result = {
    "cases": len(_params),
    "expected_values": int(_host.size),
    "compared_values": _compared_values,
    "case_disagreements": _case_disagreements,
    "value_disagreements": _value_disagreements,
    "length_disagreements": _length_disagreements,
    "dtype_disagreements": _dtype_disagreements,
    "max_ulp": _max_ulp,
    "worst": _worst,
    "regions": _region_results,
    "seconds": round(time.perf_counter() - _started, 6),
}
del _params, _host, _offsets
json.dumps(_result)
`);
  results.grids[kind] = JSON.parse(result);
  pyodide.FS.unlink("/params.json");
  pyodide.FS.unlink("/host.f64le");
  pyodide.FS.unlink("/offsets.u64le");
}
writeFileSync(join(root, "s3.json"), `${JSON.stringify(results, null, 2)}\n`);
console.log(JSON.stringify(results));
