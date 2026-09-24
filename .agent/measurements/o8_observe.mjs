// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { selectBundle } from "./o8_bundle.mjs";

const root = dirname(fileURLToPath(import.meta.url));
const project = resolve(root, "../..");
const build = process.argv[2] ?? "owui";
const outputName = process.argv[3] ?? "o8.json";
const mode = process.argv[4] ?? "wrapper";
if (build !== "owui" || mode !== "wrapper") {
  throw new Error("Use the installed OWUI bundle and production wrapper mode");
}
const { loadPyodide, packageVersion, options } = await selectBundle(root, build);
const pyodide = await loadPyodide(options);
pyodide.FS.mkdirTree("/mnt/uploads");

const exportPath = join(root, "o8_export.py");
const pythonEnv = {
  ...process.env,
  UV_PROJECT_ENVIRONMENT: process.env.UV_PROJECT_ENVIRONMENT ?? resolve(project, ".venv"),
  UV_LINK_MODE: "copy",
  UV_NO_SYNC: "1",
  PYTHONPATH: `${project}/src:${project}`,
};
const exported = (kind, input = "") =>
  execFileSync("uv", ["run", "--no-sync", "--locked", "python", exportPath, kind], {
    cwd: project,
    env: pythonEnv,
    encoding: "utf8",
    input,
  });
const fixtureDir = join(project, "tests/fixtures/observe");
const names = readdirSync(fixtureDir).filter((name) => name.endsWith(".json")).sort();
if (names.length !== 52) {
  throw new Error(`Expected 52 fixtures, got ${names.length}`);
}
const observations = [];
for (const name of names) {
  const path = join(fixtureDir, name);
  const fixture = JSON.parse(readFileSync(path, "utf8"));
  if (`${fixture.id}.json` !== name) {
    throw new Error(`Fixture id does not match ${name}`);
  }
  if (fixture.dataset !== null) {
    const { path: csvPath, content } = fixture.dataset;
    if (!csvPath.startsWith("/mnt/uploads/") || csvPath.slice(13).includes("/")) {
      throw new Error(`Unexpected upload path in ${name}`);
    }
    pyodide.FS.writeFile(csvPath, new TextEncoder().encode(content));
  }
  const code = exported("wrapper", fixture.source);
  if (code.includes("matplotlib")) {
    throw new Error(`${name}: production wrapper triggers OWUI's code rewrite`);
  }
  const stdout = [];
  const stderr = [];
  pyodide.setStdout({ batched: (line) => stdout.push(line) });
  pyodide.setStderr({ batched: (line) => stderr.push(line) });
  try {
    await pyodide.runPythonAsync(code);
  } catch (error) {
    throw new Error(`${name}: sandbox raised ${error}`);
  }
  const tagged = stdout.filter((line) => line.startsWith("FIGURE_VERIFICATION_OBSERVATION:"));
  const pngs = stdout.filter((line) => line.startsWith("data:image/png;base64,"));
  if (tagged.length !== 1 || pngs.length !== 1 || stderr.length !== 0) {
    throw new Error(
      `${name}: observations=${tagged.length}, pngs=${pngs.length}, stderr=${stderr.join(" ").slice(0, 200)}`,
    );
  }
  const observation = tagged[0].slice("FIGURE_VERIFICATION_OBSERVATION:".length);
  JSON.parse(observation);
  observations.push({ path, fixture, observation });
}
const version = JSON.parse(
  await pyodide.runPythonAsync(`
import json, sys, pyodide, numpy, pandas
import matplotlib as _mpl
json.dumps({"python": sys.version.split()[0], "pyodide": pyodide.__version__,
            "numpy": numpy.__version__, "pandas": pandas.__version__, "renderer": _mpl.__version__})
`),
);
for (const { path, fixture, observation } of observations) {
  writeFileSync(path, `${JSON.stringify({ ...fixture, observation }, null, 2)}\n`);
}
const result = {
  build: packageVersion,
  runtime: version,
  mode,
  cases: observations.length,
  dataset: observations.filter(({ fixture }) => fixture.arm === "dataset").length,
  formula: observations.filter(({ fixture }) => fixture.arm === "formula").length,
  observations: observations.length,
  pngs: observations.length,
  stderr: 0,
};
writeFileSync(join(root, outputName), `${JSON.stringify(result, null, 2)}\n`);
console.log(JSON.stringify(result));
