// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Replay the installed OWUI package detector and iframe execute path against its Pyodide bundle.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
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
// Build hashes name the files and the minifier names the variables, both per release: find each
// part by what it does, then read the variable names off the detector itself.
function single(directory, needles, label) {
  const names = readdirSync(resolve(frontend, directory)).filter((name) => name.endsWith(".js"));
  const found = names.filter((name) => {
    const text = readFileSync(resolve(frontend, directory, name), "utf8");
    return needles.every((needle) => text.includes(needle));
  });
  if (found.length !== 1) throw new Error(`installed OWUI ${label}: ${found.length} candidates`);
  return readFileSync(resolve(frontend, directory, found[0]), "utf8");
}
const handler = single("nodes", ['"execute:python"', 'postMessage({type:"execute",'], "handler");
const iframe = single("chunks", ["async function patchMatplotlib()", "String.raw`"], "iframe");

function anchored(source, start, end, label) {
  const first = source.indexOf(start);
  const last = first < 0 ? -1 : source.indexOf(end, first + start.length);
  if (first < 0 || last < 0 || source.indexOf(start, first + 1) >= 0) {
    throw new Error(`installed OWUI ${label} anchor missing or ambiguous`);
  }
  return source.slice(first + start.length, last);
}

const detected = [
  ...handler.matchAll(
    /([\w$]+)=async\(([\w$]+),([\w$]+),([\w$]+),([\w$]+)=\[\]\)=>\{let ([\w$]+)=null,([\w$]+)=null,([\w$]+)=null,([\w$]+)=!0,([\w$]+)=\[(.*?)\]\.filter\(Boolean\);/g,
  ),
];
if (detected.length !== 1) {
  throw new Error(`installed OWUI execute:python package detector: ${detected.length} matches`);
}
const [, , idName, codeName, , , resultName, stdoutName, stderrName, , listName, detector] =
  detected[0];
// A minified name may hold `$`, a regex anchor: escape it wherever a name enters a pattern.
const literal = (name) => name.replaceAll("$", "\\$");
const entries = detector.split(",");
const rules = entries.map((entry) => {
  const parsed = new RegExp(`^/((?:\\\\.|[^/])+)/\\.test\\(${literal(codeName)}\\)\\?"([^"]+)":null$`).exec(entry);
  if (!parsed) throw new Error(`installed OWUI package regex changed: ${entry}`);
  return { pattern: new RegExp(parsed[1]), package: parsed[2] };
});
if (
  !["numpy", "pandas", "matplotlib"].every((name) => rules.some((rule) => rule.package === name)) ||
  !handler.includes(`postMessage({type:"execute",id:${idName},code:${codeName},packages:${listName},files:`)
) {
  throw new Error("installed OWUI package routing changed");
}
// The reply starts every field at null and overwrites one only with a truthy worker value.
const shaping = new RegExp(
  `([\\w$]+)\\.stdout&&\\(${literal(stdoutName)}=\\1\\.stdout\\),\\1\\.stderr&&\\(${literal(stderrName)}=\\1\\.stderr\\),\\1\\.result&&\\(${literal(resultName)}=\\1\\.result\\)`,
);
if (
  !shaping.test(handler) ||
  !handler.includes(`JSON.stringify({stdout:${stdoutName},stderr:${stderrName},result:${resultName}}`)
) {
  throw new Error("installed OWUI reply shaping changed");
}
const sandbox = anchored(iframe, "=String.raw`", "`;var ", "iframe source");
for (const anchor of [
  "let stdout = null;\n\tlet stderr = null;",
  "stdout = stdout ? stdout + text + '\\n' : text + '\\n';",
  "stderr = stderr ? stderr + text + '\\n' : text + '\\n';",
  "stdout = null;\n\t\tstderr = null;\n\t\tlet result = null;",
  "await ensureRuntime(data.packages || []);",
  "if (code.includes('matplotlib') && 'matplotlib' in pyodide.loadedPackages) await patchMatplotlib();",
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
const exported = JSON.parse(
  execFileSync(
    "uv",
    ["run", "--no-sync", "--locked", "python", ".agent/measurements/f7_export.py"],
    {
      cwd: root,
      encoding: "utf8",
      maxBuffer: 64 * 1024 * 1024,
      env: { ...process.env, PYTHONPATH: `${root}:${resolve(root, "src")}` },
    },
  ),
);
async function runtime() {
  // The bundle's own wheel bytes, never the CDN copies Node Pyodide fetches by default.
  const fresh = await loadPyodide({ indexURL: `${bundle}/`, packageBaseUrl: `${bundle}/` });
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
    if (code.includes("matplotlib") && "matplotlib" in pyodide.loadedPackages) {
      await pyodide.runPythonAsync(preludeLines.join("\n"));
    }
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
    png,
    packages,
    source_bytes: Buffer.byteLength(code),
    png_sha256: createHash("sha256").update(png).digest("hex"),
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
// Q44: each sequence = replies in ONE runtime; the leg is its last reply, every earlier one clean.
const earlier = {};
for (const [name, codes] of Object.entries(exported.sequences)) {
  const shared = await runtime();
  earlier[name] = [];
  for (const code of codes.slice(0, -1)) earlier[name].push(await execute(code, shared));
  results[name] = await execute(codes.at(-1), shared);
}
// Q74: the bundle's FreeType compares every kept character of the ja-font cut with the whole font.
const identityReply = await execute(exported.identity, await runtime());
const identity =
  identityReply.stdout_other.length === 1
    ? JSON.parse(identityReply.stdout_other[0])
    : { error: identityReply.error, stderr: identityReply.stderr };
// Q44: the Japanese PNGs beside the result, for inspection.
for (const [name, { png }] of Object.entries(results)) {
  if (name.startsWith("ja-") && png.length) writeFileSync(`${output.replace(/\.json$/, "")}.${name}.png`, png);
}
for (const row of [...Object.values(results), ...Object.values(earlier).flat()]) delete row.png;
const report = {
  pyodide: version,
  cut: exported.cut,
  identity,
  python: pyodide.runPython("import sys; sys.version.split()[0]"),
  detector_entries: rules.length,
  results,
  earlier,
};
writeFileSync(output, `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify(report));
// Every plot, the two glyph legs included, replies one parseable description line + one PNG line
// with an empty stderr (the reader catches the program's warnings). Five glyph controls report
// missing glyphs in the description: ja-no-font (no font), ja-mathtext (declared limit), ja-miss (a
// character outside its cut), both replies of ja-marker-repeat (the text marker) and ja-textpath
// (a `TextPath` marker); every other plot none, ja-second's earlier reply included. The cut lacks FreeType's CJK autohinter reference glyphs, so its PNG differs from ja-whole's
// in antialiasing alone (inspect both PNGs).
const controls = ["ja-no-font", "ja-mathtext", "ja-miss", "ja-marker-repeat", "ja-textpath"];
const plots = Object.entries(results).filter(([name]) => name !== "literal-control");
if (
  plots.length !== 12 ||
  earlier["ja-marker-repeat"].some((reply) => !(reply.glyphs > 0)) ||
  earlier["ja-second"].some((reply) => reply.glyphs !== 0 || !reply.png_signature) ||
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
  // 0.12.3's prelude runs on the literal substring once the package is loaded, and replaces `show`
  // with a PNG printer: a source spelling the name would print OWUI's own PNG beside the reader's.
  results["literal-control"].png_lines !== 1 ||
  // Q74: unhinted + natively hinted outlines and advances equal the whole font's.
  ["unhinted", "native-12", "native-100"].some((mode) => identity.differ?.[mode] !== 0) ||
  results["literal-control"].description_lines !== 0 ||
  results["literal-control"].stderr !== null
) {
  process.exitCode = 1;
}
