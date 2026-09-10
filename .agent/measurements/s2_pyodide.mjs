import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadPyodide } from "pyodide";

const root = dirname(fileURLToPath(import.meta.url));
const dataRoot = join(root, "s2-data");
const manifest = JSON.parse(readFileSync(join(dataRoot, "manifest.json"), "utf8"));
const families = {
  sin: "trig",
  cos: "trig",
  tan: "trig",
  exp: "exp",
  log: "positive",
  sqrt: "positive",
};

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
const results = {
  ...metadata,
  seed: manifest.seed,
  samples_per_function: manifest.samples_per_function,
  functions: {},
};

for (const [fn, family] of Object.entries(families)) {
  pyodide.FS.writeFile("/input.f64le", readFileSync(join(dataRoot, `input-${family}.f64le`)));
  pyodide.FS.writeFile("/host.f64le", readFileSync(join(dataRoot, `host-${fn}.f64le`)));
  const regions = JSON.stringify(manifest.regions[family]);
  const result = pyodide.runPython(`
import hashlib, json, time
import numpy as np
_started = time.perf_counter()
_values = np.frombuffer(open("/input.f64le", "rb").read(), dtype="<f8")
_host = np.frombuffer(open("/host.f64le", "rb").read(), dtype="<f8")
with np.errstate(all="ignore"):
    _wasm = np.${fn}(_values)
_host_bits = _host.view(np.uint64)
_wasm_bits = _wasm.view(np.uint64)
_mismatch = _host_bits != _wasm_bits
_sign = np.uint64(1 << 63)
_host_ordered = np.where(_host_bits & _sign, ~_host_bits, _host_bits | _sign)
_wasm_ordered = np.where(_wasm_bits & _sign, ~_wasm_bits, _wasm_bits | _sign)
_distances = np.maximum(_host_ordered, _wasm_ordered) - np.minimum(_host_ordered, _wasm_ordered)
_worst_index = int(np.argmax(_distances))
_regions = ${regions}
_region_results = []
for _start, _stop, _label in _regions:
    _region_dist = _distances[_start:_stop]
    _region_mismatch = _mismatch[_start:_stop]
    _region_results.append({
        "region": _label,
        "samples": _stop - _start,
        "disagreements": int(np.count_nonzero(_region_mismatch)),
        "max_ulp": int(np.max(_region_dist)),
    })
_result = {
    "samples": int(_values.size),
    "disagreements": int(np.count_nonzero(_mismatch)),
    "max_ulp": int(_distances[_worst_index]),
    "worst_index": _worst_index,
    "worst_input_hex": float(_values[_worst_index]).hex(),
    "host_output_hex": float(_host[_worst_index]).hex(),
    "wasm_output_hex": float(_wasm[_worst_index]).hex(),
    "wasm_output_sha256": hashlib.sha256(_wasm.astype("<f8", copy=False).tobytes()).hexdigest(),
    "regions": _region_results,
    "seconds": round(time.perf_counter() - _started, 6),
}
del _values, _host, _wasm, _host_bits, _wasm_bits, _mismatch, _host_ordered, _wasm_ordered, _distances
json.dumps(_result)
`);
  results.functions[fn] = JSON.parse(result);
  pyodide.FS.unlink("/input.f64le");
  pyodide.FS.unlink("/host.f64le");
}
writeFileSync(join(root, "s2.json"), `${JSON.stringify(results, null, 2)}\n`);
console.log(JSON.stringify(results));
