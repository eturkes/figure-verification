// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// I1 sandbox leg: the artist census inside a Pyodide bundle (`owui` = the installed Open WebUI one).
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { selectBundle } from "./o8_bundle.mjs";

const root = dirname(fileURLToPath(import.meta.url));
const packageName = process.argv[2] ?? "owui";
const output = resolve(root, process.argv[3] ?? "i1-0283.json");
const { loadPyodide, packageVersion, options } = await selectBundle(root, packageName);
if (packageName === "owui") {
  options.packageCacheDir = join(root, "node_modules", "i1-owui-cache");
  mkdirSync(options.packageCacheDir, { recursive: true });
}
const pyodide = await loadPyodide(options);
await pyodide.loadPackage(["numpy", "pandas", "matplotlib"], { messageCallback: () => {} });
const data = join(root, "../../data");
pyodide.FS.mkdirTree("/i1-data");
for (const name of readdirSync(data).filter((n) => n.endsWith(".csv"))) {
  pyodide.FS.writeFile(`/i1-data/${name}`, readFileSync(join(data, name)));
}
pyodide.FS.writeFile("/i1_census.py", readFileSync(join(root, "i1_census.py")));
const report = JSON.parse(await pyodide.runPythonAsync(`
import json, os, runpy
os.environ["MPLBACKEND"] = "AGG"
json.dumps(runpy.run_path("/i1_census.py", run_name="i1_module")["measure"]("/i1-data"))
`));
report.bundle = { selection: packageName, version: packageVersion };
writeFileSync(output, `${JSON.stringify(report, null, 1)}\n`);
console.log(JSON.stringify(report.versions));
