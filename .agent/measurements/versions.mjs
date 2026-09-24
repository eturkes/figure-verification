// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const packageName = process.argv[2] ?? "pyodide";
const outputName = process.argv[3] ?? "versions.json";
if (!["pyodide", "pyodide0281"].includes(packageName)) {
  throw new Error(`Unknown Pyodide package: ${packageName}`);
}
const { loadPyodide } = await import(packageName);
const packageVersion = JSON.parse(
  readFileSync(join(root, "node_modules", packageName, "package.json"), "utf8"),
).version;
const pyodide = await loadPyodide({
  packageBaseUrl: `https://cdn.jsdelivr.net/pyodide/v${packageVersion}/full/`,
  packageCacheDir: join(root, "node_modules", packageName),
});
await pyodide.loadPackage(["numpy", "pandas"]);
const versions = pyodide.runPython(`
import json, platform, sys
import numpy, pandas, pyodide
json.dumps({
    "python": sys.version,
    "platform": platform.platform(),
    "pyodide": pyodide.__version__,
    "numpy": numpy.__version__,
    "pandas": pandas.__version__,
})
`);
writeFileSync(join(root, outputName), `${versions}\n`);
console.log(versions);
