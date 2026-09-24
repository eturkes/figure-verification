// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Run the production wrapper against the Pyodide bundled in the installed Open WebUI image.
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const bundle = resolve(process.argv[2] ?? "");
const output = process.argv[3];
if (!process.argv[2] || !output) {
  throw new Error("usage: node f7_wrapper.mjs <OWUI-pyodide-dir> <output.json>");
}
const { version } = JSON.parse(readFileSync(resolve(bundle, "package.json"), "utf8"));
const { loadPyodide } = await import(pathToFileURL(resolve(bundle, "pyodide.mjs")).href);
const pyodide = await loadPyodide({ indexURL: `${bundle}/` });
await pyodide.loadPackage(["numpy", "pandas", "matplotlib"]);
pyodide.runPython("import os; os.environ['MPLBACKEND'] = 'AGG'");
pyodide.FS.mkdirTree("/mnt/uploads");

const exported = JSON.parse(
  execFileSync("uv", ["run", "--locked", "python", ".agent/measurements/f7_export.py"], {
    cwd: root,
    encoding: "utf8",
    env: { ...process.env, PYTHONPATH: `${root}:${resolve(root, "src")}` },
  }),
);
pyodide.FS.writeFile("/mnt/uploads/sales.csv", Uint8Array.fromHex(exported.dataset));
const results = {};
for (const [name, code] of Object.entries(exported.wrappers)) {
  const stdout = [];
  const stderr = [];
  pyodide.setStdout({ batched: (line) => stdout.push(line) });
  pyodide.setStderr({ batched: (line) => stderr.push(line) });
  let error = null;
  try {
    await pyodide.runPythonAsync(code);
  } catch (exception) {
    error = String(exception);
  }
  const pngs = stdout.filter((line) => line.startsWith("data:image/png;base64,"));
  const png = pngs.length === 1 ? Buffer.from(pngs[0].slice(22), "base64") : Buffer.alloc(0);
  results[name] = {
    stdout_lines: stdout.length,
    png_lines: pngs.length,
    stderr_bytes: Buffer.byteLength(stderr.join("\n")),
    png_signature: png.subarray(0, 8).equals(Buffer.from("89504e470d0a1a0a", "hex")),
    error,
  };
}
const report = {
  pyodide: version,
  python: pyodide.runPython("import sys; sys.version.split()[0]"),
  results,
};
writeFileSync(output, `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify(report));
if (
  Object.keys(results).length !== 4 ||
  Object.values(results).some(
    ({ stdout_lines, png_lines, stderr_bytes, png_signature, error }) =>
      stdout_lines !== 1 || png_lines !== 1 || stderr_bytes !== 0 || !png_signature || error,
  )
) {
  process.exitCode = 1;
}
