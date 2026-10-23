// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// NR (M23.1 N7, N8): nucllei's own markdown pipeline over the tool's hostile-text corpus
// (`nucllei_render_corpus.py`). The chain = what `Markdown.svelte` runs on a tool display or
// result at the tag: `replaceTokens(processResponseContent(text))` → `segmentMarkdown` → `lex` per
// block (markdown-it 14 + markdown-it-attrs + nucllei's KaTeX and bracket-reference rules), each
// module read from the checkout and run as written (Node strips the types). Text tokens render as
// Svelte text, so the tokens decide: a case fails on any construct its kind does not admit, and the
// unescaped control must form one.
//
//   node nucllei_render.mjs <nucllei checkout> <corpus.json> <result.json>
//
// Exit 1 on any failed case or a silent control.
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const [checkout, corpusPath, resultPath] = process.argv.slice(2);
if (!resultPath) throw new Error("usage: nucllei_render.mjs <nucllei checkout> <corpus.json> <result.json>");
const lib = join(checkout, "src/lib");
const read = (path) => readFileSync(join(lib, path), "utf8");
const FILE_ID = "0a1b2c3d-0000-4000-8000-000000000000";
const GUIDE = "/ext/public/figure-verification/checks";
const JA_LABEL = "\\footnotesize\\textbf{モデルの注記:}";

function slice(text, start, end) {
  const from = text.indexOf(start);
  const to = text.indexOf(end, from);
  if (from < 0 || to < 0) throw new Error(`not found in the checkout: ${start}`);
  return text.slice(from, to);
}

// Bare imports resolve from this directory's node_modules; the copy is gitignored (`*-data/`).
const work = join(dirname(fileURLToPath(import.meta.url)), `nr-${process.pid}-data`);
mkdirSync(work, { recursive: true });
try {
  const constants = read("constants.ts").match(/^export const WEBUI_BASE_URL = .*$/m);
  if (!constants) throw new Error("WEBUI_BASE_URL not found in the checkout");
  const rewrite = (text) =>
    text
      .replaceAll("'$lib/utils/citations'", "'./citations.ts'")
      .replaceAll("'$lib/constants'", "'./constants.ts'")
      .replaceAll("from './katex'", "from './katex.ts'");
  writeFileSync(join(work, "constants.ts"), `${constants[0]}\n`);
  writeFileSync(join(work, "citations.ts"), rewrite(read("utils/citations.ts")));
  writeFileSync(join(work, "katex.ts"), read("utils/markdown-it/katex.ts"));
  writeFileSync(join(work, "index.ts"), rewrite(read("utils/markdown-it/index.ts")));
  writeFileSync(join(work, "segmenter.ts"), read("utils/markdown/segmenter.ts"));
  const utils = read("utils/index.ts");
  writeFileSync(
    join(work, "replace.ts"),
    "import { WEBUI_BASE_URL } from './constants.ts';\n" +
      slice(utils, "export const replaceTokens", "export const sanitizeResponseContent") +
      slice(utils, "export const processResponseContent", "export function unescapeHtml"),
  );
  const { lex } = await import(join(work, "index.ts"));
  const { segmentMarkdown, closeUnclosedFences } = await import(join(work, "segmenter.ts"));
  const { replaceTokens, processResponseContent } = await import(join(work, "replace.ts"));

  const env = { fileNames: new Map([[FILE_ID, "sales.csv"]]) };
  const tokensOf = (content) => {
    const { stable, tail } = segmentMarkdown(replaceTokens(processResponseContent(content), "Model", "User"));
    return [...stable.flatMap((block) => lex(block, env)), ...(tail ? lex(closeUnclosedFences(tail), env) : [])];
  };
  const inline = (token) => [token, ...(token.tokens ?? []).flatMap(inline)];
  const textOf = (tokens) => tokens.map((t) => (t.type === "text" ? t.text : "")).join("");

  const results = [];
  for (const item of JSON.parse(readFileSync(corpusPath, "utf8"))) {
    const blocks = tokensOf(item.content);
    const faults = [];
    const types = blocks.map((block) => block.type);
    const inlines = blocks.flatMap((block) => (block.tokens ?? []).flatMap(inline));
    const markup = inlines.filter((t) => !["text", "codespan"].includes(t.type));
    if (item.kind === "control") {
      if (markup.length === 0) faults.push("control formed no markup");
    } else if (item.kind === "result") {
      for (const type of types) if (!["paragraph", "code"].includes(type)) faults.push(`block ${type}`);
      for (const t of markup) {
        const guide = t.type === "link" && t.href.startsWith(GUIDE) && !t.cite;
        if (!guide && !["strong", "br"].includes(t.type)) faults.push(`inline ${t.type}`);
      }
      const lines = new Set(item.program);
      for (const block of blocks.filter((b) => b.type === "code")) {
        for (const line of block.text.split("\n")) {
          const body = line.replace(/^[▶ ] *\d+ \| ?/u, "");
          if (line !== "⋮" && !lines.has(body)) faults.push(`listing line ${JSON.stringify(line)}`);
        }
      }
      if (!blocks.some((b) => b.type === "code")) faults.push("no listing");
    } else {
      for (const type of types) if (type !== "paragraph") faults.push(`block ${type}`);
      if (item.kind === "fail") {
        for (const t of markup) faults.push(`inline ${t.type}`);
      } else {
        if (blocks.length !== 4) faults.push(`${blocks.length} paragraphs`);
        const [, image, names, note] = blocks;
        // markdown-it leaves an empty text token before a delimiter run such as the label's `**`.
        const parts = (note?.tokens ?? []).filter((t) => !(t.type === "text" && t.text === ""));
        for (const t of markup) {
          const own =
            (t.type === "image" && t.href === `/api/v1/files/${FILE_ID}/content` && image?.tokens.includes(t)) ||
            (t.type === "strong" && parts[0] === t && textOf(t.tokens) === "Model note:") ||
            (t.type === "inlineKatex" && parts[0] === t && t.text === JA_LABEL);
          if (!own) faults.push(`inline ${t.type}`);
        }
        const spans = (names?.tokens ?? []).filter((t) => t.type === "codespan").map((t) => t.text);
        if (JSON.stringify(spans) !== JSON.stringify(item.codespans)) faults.push("code spans differ");
        // `prose` puts a word joiner after each escaped backslash; it draws nothing.
        const shown = textOf(parts.slice(1)).replaceAll("\u2060", "");
        if (shown !== item.note) faults.push(`note text ${JSON.stringify(shown)}`);
      }
    }
    results.push({ kind: item.kind, faults, content: item.content, blocks: faults.length || item.kind === "control" ? blocks : undefined });
  }
  writeFileSync(resultPath, JSON.stringify(results, null, 1));
  const failed = results.filter((r) => r.faults.length > 0);
  for (const r of failed) console.log(`${r.kind}: ${r.faults.join("; ")}\n  ${JSON.stringify(r.content).slice(0, 300)}`);
  const controls = results.filter((r) => r.kind === "control");
  console.log(`${results.length} cases, ${failed.length} failed (${controls.length} controls)`);
  process.exitCode = failed.length > 0 ? 1 : 0;
} finally {
  rmSync(work, { recursive: true, force: true });
}
