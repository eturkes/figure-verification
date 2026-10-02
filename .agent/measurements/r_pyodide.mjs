// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const packageName = process.argv[2] ?? "pyodide";
const outputName = process.argv[3] ?? `${packageName}.json`;
const mode = process.argv[4] ?? "probe";
if (!["pyodide", "pyodide0281"].includes(packageName)) {
  throw new Error(`Unknown Pyodide package: ${packageName}`);
}
if (!["probe", "supplement"].includes(mode)) {
  throw new Error(`Unknown reduction leg: ${mode}`);
}
const { loadPyodide } = await import(packageName);
const version = JSON.parse(
  readFileSync(join(root, "node_modules", packageName, "package.json"), "utf8"),
).version;
const py = await loadPyodide({
  packageBaseUrl: `https://cdn.jsdelivr.net/pyodide/v${version}/full/`,
  packageCacheDir: join(root, "node_modules", packageName),
});
await py.loadPackage(mode === "probe" ? ["numpy", "pandas"] : ["numpy", "pandas", "matplotlib"]);
py.FS.mkdir("/r");
py.FS.mkdir("/r/r-data");
for (const name of ["r_probe.py", "r_supplement.py"]) {
  py.FS.writeFile(`/r/${name}`, readFileSync(join(root, name)));
}
if (mode === "probe") {
  for (const name of ["cases.json", "stress.csv", "profile.csv"]) {
    py.FS.writeFile(`/r/r-data/${name}`, readFileSync(join(root, "r-data", name)));
  }
}
const result = py.runPython(mode === "probe" ? `
import json, sys, warnings
sys.path.insert(0, '/r')
from r_probe import run, summary
with warnings.catch_warnings():
    warnings.simplefilter('ignore', FutureWarning)
    result = run()
json.dumps(result, sort_keys=True, separators=(',', ':'))
` : `
import json, sys, pyodide
sys.path.insert(0, '/r')
from r_supplement import renderer, canonical_witness, pd, np
result = {
    'pyodide': pyodide.__version__, 'pandas': pd.__version__, 'numpy': np.__version__,
    'python': sys.version.split()[0], 'compute_use_numba': pd.get_option('compute.use_numba'),
    'renderer': renderer(), 'canonical_witness': canonical_witness(),
}
json.dumps(result, sort_keys=True)
`);
writeFileSync(join(root, "r-data", outputName), `${result}\n`);
console.log(mode === "probe" ? py.runPython("json.dumps(summary(result), sort_keys=True)") : result);
