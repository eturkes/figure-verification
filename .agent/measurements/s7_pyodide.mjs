import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const packageName = process.argv[2] ?? "pyodide";
const outputName = process.argv[3] ?? "s7.json";
const { loadPyodide } = await import(packageName);
const pyodide = await loadPyodide();
await pyodide.loadPackage("numpy");

const dataRoot = join(root, "s7-data");
const manifest = JSON.parse(readFileSync(join(dataRoot, "manifest.json"), "utf8"));
for (const name of ["base.f64le", "exp.f64le", "host-np.f64le"]) {
  pyodide.FS.writeFile(`/${name}`, readFileSync(join(dataRoot, name)));
}
const regions = JSON.stringify(manifest.regions);

const result = pyodide.runPython(`
import hashlib, json, platform, sys, time
import numpy as np
import pyodide
_started = time.perf_counter()
_base = np.frombuffer(open("/base.f64le", "rb").read(), dtype="<f8")
_exp = np.frombuffer(open("/exp.f64le", "rb").read(), dtype="<f8")
_host = np.frombuffer(open("/host-np.f64le", "rb").read(), dtype="<f8")
with np.errstate(all="ignore"):
    _wasm = np.power(_base, _exp)

_host_bits = _host.view(np.uint64)
_wasm_bits = _wasm.view(np.uint64)
_both_nan = np.isnan(_host) & np.isnan(_wasm)
_agree = (_host_bits == _wasm_bits) | _both_nan

# ULP distance is only meaningful where BOTH sides are finite; a nan/inf split is a category
# disagreement, which is a different and worse finding than a last-bit one.
_both_finite = np.isfinite(_host) & np.isfinite(_wasm)
_sign = np.uint64(1 << 63)
_host_ordered = np.where(_host_bits & _sign, ~_host_bits, _host_bits | _sign)
_wasm_ordered = np.where(_wasm_bits & _sign, ~_wasm_bits, _wasm_bits | _sign)
_distances = np.where(
    _both_finite,
    np.maximum(_host_ordered, _wasm_ordered) - np.minimum(_host_ordered, _wasm_ordered),
    np.uint64(0),
)
_category_split = int(np.count_nonzero(~_agree & ~_both_finite))
_worst = int(np.argmax(_distances))

_region_results = []
for _start, _stop, _label in ${regions}:
    _region_results.append({
        "region": _label,
        "samples": _stop - _start,
        "disagreements": int(np.count_nonzero(~_agree[_start:_stop])),
        "max_ulp": int(np.max(_distances[_start:_stop])),
        "category_splits": int(np.count_nonzero((~_agree & ~_both_finite)[_start:_stop])),
    })

_witnesses = []
for _index in np.flatnonzero(~_agree)[:20].tolist():
    _witnesses.append({
        "index": int(_index),
        "base_hex": float(_base[_index]).hex(),
        "exp_hex": float(_exp[_index]).hex(),
        "host_hex": float(_host[_index]).hex(),
        "wasm_hex": float(_wasm[_index]).hex(),
        "ulp": int(_distances[_index]),
    })

_result = {
    "python": sys.version.split()[0],
    "platform": platform.platform(),
    "pyodide": pyodide.__version__,
    "numpy": np.__version__,
    "samples": int(_base.size),
    "disagreements": int(np.count_nonzero(~_agree)),
    "max_ulp": int(_distances[_worst]),
    "category_splits": _category_split,
    "worst_index": _worst,
    "worst_base_hex": float(_base[_worst]).hex(),
    "worst_exp_hex": float(_exp[_worst]).hex(),
    "host_output_hex": float(_host[_worst]).hex(),
    "wasm_output_hex": float(_wasm[_worst]).hex(),
    "wasm_output_sha256": hashlib.sha256(_wasm.astype("<f8", copy=False).tobytes()).hexdigest(),
    "regions": _region_results,
    "witnesses": _witnesses,
    "seconds": round(time.perf_counter() - _started, 6),
}
json.dumps(_result)
`);
writeFileSync(join(root, outputName), `${result}\n`);
console.log(result);
