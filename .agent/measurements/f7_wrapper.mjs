// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Replay the installed OWUI package detector and iframe execute path against its Pyodide bundle.
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { performance } from "node:perf_hooks";
import { fileURLToPath, pathToFileURL } from "node:url";
import { runInNewContext } from "node:vm";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const bundle = resolve(process.argv[2] ?? "");
const output = process.argv[3];
if (!process.argv[2] || !output) {
  throw new Error("usage: node f7_wrapper.mjs <OWUI-pyodide-dir> <output.json>");
}
const frontend = resolve(bundle, "../_app/immutable");
const handler = readFileSync(resolve(frontend, "nodes/0.VsCm_E_x.js"), "utf8");
const iframe = readFileSync(resolve(frontend, "chunks/BTl0LwHk.js"), "utf8");

function anchored(source, start, end, label) {
  const first = source.indexOf(start);
  const last = first < 0 ? -1 : source.indexOf(end, first + start.length);
  if (first < 0 || last < 0 || source.indexOf(start, first + 1) >= 0) {
    throw new Error(`installed OWUI ${label} anchor missing or ambiguous`);
  }
  return source.slice(first + start.length, last);
}

const detector = anchored(
  handler,
  "Ue=async(e,n,P,g=[])=>{",
  ";const S=ue()",
  "execute:python package detector",
);
const entries = anchored(detector, "j=[", "].filter(Boolean)", "package regex list").split(",");
const rules = entries.map((entry) => {
  const parsed = /^\/((?:\\.|[^/])+)\/\.test\(n\)\?"([^"]+)":null$/.exec(entry);
  if (!parsed) throw new Error(`installed OWUI package regex changed: ${entry}`);
  return { pattern: new RegExp(parsed[1]), package: parsed[2] };
});
if (
  !["numpy", "pandas", "matplotlib"].every((name) => rules.some((rule) => rule.package === name)) ||
  !handler.includes('S.postMessage({type:"execute",id:e,code:n,packages:j,files:')
) {
  throw new Error("installed OWUI package routing changed");
}
for (const anchor of [
  "let w=null,i=null,R=null,Z=!0",
  "c.stdout&&(i=c.stdout)",
  "c.stderr&&(R=c.stderr)",
  "c.result&&(w=c.result)",
  "P&&P(JSON.parse(JSON.stringify({stdout:i,stderr:R,result:w}",
]) {
  if (!handler.includes(anchor)) throw new Error(`installed OWUI reply anchor missing: ${anchor}`);
}
const sandbox = anchored(iframe, "const u=String.raw`", "`;var o;", "iframe source");
for (const anchor of [
  "let stdout = null;\n\tlet stderr = null;",
  "stdout = stdout ? stdout + text + '\\n' : text + '\\n';",
  "stderr = stderr ? stderr + text + '\\n' : text + '\\n';",
  "stdout = null;\n\t\tstderr = null;\n\t\tlet result = null;",
  "await ensureRuntime(data.packages || []);",
  "if (code.includes('matplotlib')) await patchMatplotlib();",
  "result = clean(await pyodide.runPythonAsync(code));",
  "stderr = error && error.message ? error.message : String(error);",
  "post({ id: id, result: result, stdout: stdout, stderr: stderr });",
]) {
  if (!sandbox.includes(anchor)) throw new Error(`installed OWUI iframe anchor missing: ${anchor}`);
}
const prelude = anchored(
  sandbox,
  "async function patchMatplotlib() {\n\t\tawait pyodide.runPythonAsync([",
  "].join('\\n'));\n\t}",
  "patchMatplotlib prelude",
);
const preludeLines = runInNewContext(`[${prelude}]`);
if (!Array.isArray(preludeLines) || !preludeLines.every((line) => typeof line === "string")) {
  throw new Error("installed OWUI patchMatplotlib prelude is not a string array");
}

function shapeReply(worker) {
  const reply = { stdout: null, stderr: null, result: null };
  for (const key of ["stdout", "stderr", "result"]) {
    if (worker[key]) reply[key] = worker[key];
  }
  return JSON.parse(
    JSON.stringify(reply, (_key, value) => (typeof value === "bigint" ? value.toString() : value)),
  );
}

const { version } = JSON.parse(readFileSync(resolve(bundle, "package.json"), "utf8"));
const { loadPyodide } = await import(pathToFileURL(resolve(bundle, "pyodide.mjs")).href);
// M17.1: the Japanese legs carry the font the installed Open WebUI ships beside this bundle.
const font = resolve(bundle, "../../static/fonts/NotoSansJP-Regular.ttf");
const exported = JSON.parse(
  execFileSync(
    "uv",
    ["run", "--no-sync", "--locked", "python", ".agent/measurements/f7_export.py", font],
    {
      cwd: root,
      encoding: "utf8",
      maxBuffer: 64 * 1024 * 1024,
      env: { ...process.env, PYTHONPATH: `${root}:${resolve(root, "src")}` },
    },
  ),
);
async function runtime() {
  const fresh = await loadPyodide({ indexURL: `${bundle}/` });
  fresh.FS.mkdirTree("/mnt/uploads");
  fresh.FS.writeFile("/mnt/uploads/sales.csv", Uint8Array.fromHex(exported.dataset));
  fresh.FS.writeFile("/mnt/uploads/clinic_ja.csv", Uint8Array.fromHex(exported.clinic));
  return fresh;
}
const pyodide = await runtime();

async function execute(code, pyodide) {
  let stdout = null;
  let stderr = null;
  let result = null;
  let error = null;
  pyodide.setStdout({ batched: (text) => (stdout = stdout ? stdout + `${text}\n` : `${text}\n`) });
  pyodide.setStderr({ batched: (text) => (stderr = stderr ? stderr + `${text}\n` : `${text}\n`) });
  const packages = rules.filter((rule) => rule.pattern.test(code)).map((rule) => rule.package);
  const started = performance.now();
  try {
    await pyodide.loadPackage(packages);
    // OWUI clears loadRuntime/ensureRuntime output at the start of execute().
    stdout = null;
    stderr = null;
    if (code.includes("matplotlib")) await pyodide.runPythonAsync(preludeLines.join("\n"));
    result = await pyodide.runPythonAsync(code);
  } catch (exception) {
    error = exception?.message ?? String(exception);
    stderr = error;
  }
  const reply = shapeReply({ stdout, stderr, result });
  const lines = typeof reply.stdout === "string" ? reply.stdout.trimEnd().split("\n").filter(Boolean) : [];
  const tag = "FIGURE_VERIFICATION_DESCRIPTION:";
  const tagged = lines.filter((line) => line.startsWith(tag));
  let descriptionParseable = false;
  let glyphs = null;
  if (tagged.length === 1 && lines[0] === tagged[0]) {
    try {
      const value = JSON.parse(tagged[0].slice(tag.length));
      descriptionParseable = value !== null && typeof value === "object" && !Array.isArray(value);
      glyphs = Number.isInteger(value?.glyphs) ? value.glyphs : null;
    } catch {
      descriptionParseable = false;
    }
  }
  const pngs = lines.filter((line) => line.startsWith("data:image/png;base64,"));
  const png = pngs.length === 1 ? Buffer.from(pngs[0].slice(22), "base64") : Buffer.alloc(0);
  return {
    packages,
    stdout_lines: lines.length,
    stdout_other: lines.filter((line) => !line.startsWith("data:image/png;base64,")).map((line) => line.slice(0, 200)),
    description_lines: tagged.length,
    description_parseable: descriptionParseable,
    glyphs,
    png_lines: pngs.length,
    png_second: lines.length === 2 && /^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/.test(lines[1]),
    stderr_bytes: Buffer.byteLength(reply.stderr ?? ""),
    stderr: reply.stderr,
    result: reply.result,
    png_signature: png.subarray(0, 8).equals(Buffer.from("89504e470d0a1a0a", "hex")),
    reply: {
      stdout_lines: lines.length,
      stderr: reply.stderr,
      result: reply.result,
      png_signature: png.subarray(0, 8).equals(Buffer.from("89504e470d0a1a0a", "hex")),
    },
    wall_ms: Math.round(performance.now() - started),
    error,
  };
}

const results = {};
for (const [name, code] of Object.entries(exported.wrappers)) results[name] = await execute(code, pyodide);
results["literal-control"] = await execute("import matplotlib.pyplot as plt\nplt.show()\n", pyodide);
for (const [name, code] of Object.entries(exported.japanese)) {
  results[name] = await execute(code, await runtime());
}
const report = {
  pyodide: version,
  python: pyodide.runPython("import sys; sys.version.split()[0]"),
  detector_entries: rules.length,
  results,
};
writeFileSync(output, `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify(report));
// Every plot, the two glyph legs included, replies one parseable description line + one PNG line
// with an empty stderr (the reader catches the program's warnings). ja-no-font (control) +
// ja-mathtext (declared limit) report missing glyphs in the description; every other plot none.
const controls = ["ja-no-font", "ja-mathtext"];
const plots = Object.entries(results).filter(([name]) => name !== "literal-control");
if (
  plots.length !== 7 ||
  plots.some(
    ([name, {
      stdout_lines, description_lines, description_parseable, glyphs, png_lines, png_second,
      stderr_bytes, stderr, result, png_signature, error,
    }]) =>
      stdout_lines !== 2 || description_lines !== 1 || !description_parseable ||
      png_lines !== 1 || !png_second || stderr_bytes !== 0 || stderr !== null ||
      result !== null || !png_signature || error ||
      (controls.includes(name) ? !(glyphs > 0) : glyphs !== 0),
  ) ||
  !results["literal-control"].stderr.includes("SyntaxError")
) {
  process.exitCode = 1;
}
