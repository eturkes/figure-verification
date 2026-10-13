// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { selectBundle } from "./o8_bundle.mjs";

const root = dirname(fileURLToPath(import.meta.url));
const packageName = process.argv[2] ?? "owui";
const outputName = process.argv[3] ?? "versions.json";
const { loadPyodide, packageVersion, options } = await selectBundle(root, packageName);
const pyodide = await loadPyodide(options);
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
