// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// I3 sandbox leg: each census program's production wrapper, run in one Pyodide runtime in order.
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { selectBundle } from "./o8_bundle.mjs";

const root = dirname(fileURLToPath(import.meta.url));
const packageName = process.argv[2] ?? "owui";
const output = resolve(root, process.argv[3] ?? "i3-0283.json");
const wrappers = JSON.parse(readFileSync(join(root, "i3-wrappers.json"), "utf8"));
const { loadPyodide, packageVersion, options } = await selectBundle(root, packageName);
if (packageName === "owui") {
  options.packageCacheDir = join(root, "node_modules", "i3-owui-cache");
  mkdirSync(options.packageCacheDir, { recursive: true });
}
const pyodide = await loadPyodide(options);
const data = join(root, "../../data");
pyodide.FS.mkdirTree("/mnt/uploads");
for (const name of readdirSync(data).filter((n) => n.endsWith(".csv"))) {
  pyodide.FS.writeFile(`/mnt/uploads/${name}`, readFileSync(join(data, name)));
}
const results = {};
for (const [name, code] of Object.entries(wrappers)) {
  let stdout = "";
  let stderr = "";
  pyodide.setStdout({ batched: (text) => (stdout += `${text}\n`) });
  pyodide.setStderr({ batched: (text) => (stderr += `${text}\n`) });
  let error = null;
  try {
    await pyodide.runPythonAsync(code);
  } catch (exception) {
    error = exception?.message ?? String(exception);
  }
  const lines = stdout.split("\n").filter(Boolean);
  results[name] = {
    description: lines[0] ?? null,
    png_lines: lines.filter((line) => line.startsWith("data:image/png;base64,")).length,
    lines: lines.length,
    stderr,
    error,
  };
}
const report = { bundle: { selection: packageName, version: packageVersion }, results };
writeFileSync(output, `${JSON.stringify(report, null, 1)}\n`);
console.log(JSON.stringify({ programs: Object.keys(results).length }));
