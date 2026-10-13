// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

// The one sandbox every Pyodide leg measures: the bundle the installed Open WebUI serves.
export const BUNDLE_VERSION = "314.0.3";

export function bundleDirectory(root) {
  const gitDir = execFileSync("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"], {
    cwd: resolve(root, "../.."),
    encoding: "utf8",
  }).trim();
  return resolve(gitDir, "../.venv-webui/lib/python3.11/site-packages/open_webui/frontend/pyodide");
}

export async function selectBundle(root, name) {
  if (name !== "owui") {
    throw new Error(`Unknown Pyodide bundle: ${name} (only the installed Open WebUI bundle, owui)`);
  }
  const directory = bundleDirectory(root);
  const packageVersion = JSON.parse(readFileSync(join(directory, "package.json"), "utf8")).version;
  if (packageVersion !== BUNDLE_VERSION) {
    throw new Error(`The installed OWUI bundle must be ${BUNDLE_VERSION}, got ${packageVersion}`);
  }
  const { loadPyodide } = await import(pathToFileURL(join(directory, "pyodide.mjs")).href);
  // Node Pyodide fetches wheels from the CDN by default; the bundle's own wheel bytes are measured.
  return {
    loadPyodide,
    packageVersion,
    options: { indexURL: directory, packageBaseUrl: `${directory}/` },
  };
}
