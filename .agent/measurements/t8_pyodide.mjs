// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { selectBundle } from "./o8_bundle.mjs";

const root = dirname(fileURLToPath(import.meta.url));
const packageName = process.argv[2] ?? "pyodide0281";
const output = resolve(root, process.argv[3] ?? "t8-pyodide.json");
const dataRoot = join(root, "t8-data");
const manifestBytes = readFileSync(join(dataRoot, "manifest.json"));
const manifest = JSON.parse(manifestBytes);
const host = JSON.parse(readFileSync(join(root, "t8-host.json"), "utf8"));
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
if (host.manifest_sha256 !== sha256(manifestBytes)) {
  throw new Error("T8 host references belong to a different corpus");
}
const { loadPyodide, packageVersion, options } = await selectBundle(root, packageName);
if (packageName === "owui") {
  // The installed bundle is read-only; any wheel-cache writes stay in this worktree.
  options.packageCacheDir = join(root, "node_modules", "t8-owui-cache");
  mkdirSync(options.packageCacheDir, { recursive: true });
}
const pyodide = await loadPyodide(options);
await pyodide.loadPackage(["numpy", "pandas", "matplotlib"]);
pyodide.FS.mkdir("/t8-data");
pyodide.FS.writeFile("/t8-data/manifest.json", manifestBytes);
for (const name of Object.keys(manifest.sha256)) {
  const bytes = readFileSync(join(dataRoot, name));
  if (sha256(bytes) !== manifest.sha256[name]) throw new Error(`T8 corpus drift: ${name}`);
  pyodide.FS.writeFile(`/t8-data/${name}`, bytes);
}
for (const name of ["decimals", "mixed"]) {
  const bytes = readFileSync(join(dataRoot, `${name}.host.f64le`));
  if (sha256(bytes) !== host.corpora[name].plain.output_sha256) {
    throw new Error(`T8 host reference drift: ${name}`);
  }
  pyodide.FS.writeFile(`/t8-data/${name}.host.f64le`, bytes);
}
const script = readFileSync(join(root, "t8_profile.py"));
pyodide.FS.writeFile("/t8_profile.py", script);
const report = JSON.parse(await pyodide.runPythonAsync(`
import json, runpy
from pathlib import Path
measurement = runpy.run_path("/t8_profile.py", run_name="t8_module")
json.dumps(measurement["measure"](Path("/t8-data"), host=False, renderer=True))
`));
report.versions.pyodide = pyodide.version;
report.host_versions = host.versions;
report.bundle = { selection: packageName, version: packageVersion };
report.scripts_sha256 = Object.fromEntries(
  ["make_t8_inputs.py", "t8_profile.py", "t8_pyodide.mjs", "o8_bundle.mjs"].map(
    (name) => [name, sha256(readFileSync(join(root, name)))],
  ),
);
writeFileSync(output, `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify({
  versions: report.versions,
  corpora: Object.fromEntries(Object.entries(report.corpora).map(([name, forms]) => [name,
    Object.fromEntries(Object.entries(forms).map(([form, result]) => [form, {
      rows: result.vs_host_pandas.rows,
      host_mismatches: result.vs_host_pandas.bit_mismatches,
      stdlib_mismatches: result.vs_stdlib_float.bit_mismatches,
      retained_digit_profile: result.vs_stdlib_float.retained_digit_profile,
    }])),
  ])),
  renderer: report.renderer,
}));
