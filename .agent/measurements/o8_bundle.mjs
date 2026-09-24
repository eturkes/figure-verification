// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

export async function selectBundle(root, name) {
  if (name === "owui") {
    const gitDir = execFileSync("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"], {
      cwd: resolve(root, "../.."),
      encoding: "utf8",
    }).trim();
    const directory = resolve(
      gitDir,
      "../.venv-webui/lib/python3.12/site-packages/open_webui/frontend/pyodide",
    );
    const packageVersion = JSON.parse(readFileSync(join(directory, "package.json"), "utf8")).version;
    if (packageVersion !== "0.28.3") {
      throw new Error(`The installed OWUI bundle must be 0.28.3, got ${packageVersion}`);
    }
    const { loadPyodide } = await import(pathToFileURL(join(directory, "pyodide.mjs")).href);
    return { loadPyodide, packageVersion, options: { indexURL: directory } };
  }
  if (!["pyodide", "pyodide0281"].includes(name)) {
    throw new Error(`Unknown Pyodide package: ${name}`);
  }
  const { loadPyodide } = await import(name);
  const packageVersion = JSON.parse(
    readFileSync(join(root, "node_modules", name, "package.json"), "utf8"),
  ).version;
  return {
    loadPyodide,
    packageVersion,
    options: {
      packageBaseUrl: `https://cdn.jsdelivr.net/pyodide/v${packageVersion}/full/`,
      packageCacheDir: join(root, "node_modules", name),
    },
  };
}
