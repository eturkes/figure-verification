// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Q79: Open WebUI's own renderer over the model-note corpus (`q79_corpus.py`). Each case is stored
// as an assistant reply in a new chat of the signed-in user; the page renders it, and the record
// counts the elements markup would have made + reads the note paragraph's text.
//
//   node q79_render.mjs <browser-url> <webui-url> <corpus.json> <result.json>
//
// Signs in with FV_WEBUI_EMAIL / FV_WEBUI_PASSWORD when the page asks. Exit 1 on any case whose
// paragraph text differs, which holds a markup element, or whose label is not its language's kind:
// the one `strong` (EN) or the KaTeX `\textbf` label (JA, Q80).
import { readFileSync, writeFileSync } from "node:fs";
import puppeteer from "puppeteer-core";

const [browserURL, webuiURL, corpusPath, resultPath] = process.argv.slice(2);
if (!resultPath) throw new Error("usage: q79_render.mjs <browser-url> <webui-url> <corpus.json> <result.json>");
const cases = JSON.parse(readFileSync(corpusPath, "utf8"));
const MARKUP = "a, img, iframe, video, audio, details, u, b, script, code, em, del, s, mark, h1, h2, blockquote, ul, ol, li, table, .katex, sup";

const browser = await puppeteer.connect({ browserURL, protocolTimeout: 0 });
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900 });
const cdp = await page.createCDPSession();
await page.goto(`${webuiURL}/`, { waitUntil: "domcontentloaded", timeout: 90000 });
const entry = await page.waitForSelector("#email, #chat-input", { timeout: 120000 });
if (await entry.evaluate((node) => node.id === "email")) {
  await page.click("#email");
  await cdp.send("Input.insertText", { text: process.env.FV_WEBUI_EMAIL ?? "" });
  await page.click("#password");
  await cdp.send("Input.insertText", { text: process.env.FV_WEBUI_PASSWORD ?? "" });
  await page.keyboard.press("Enter");
  await page.waitForSelector("#chat-input", { timeout: 120000 });
}

const results = [];
for (const [index, item] of cases.entries()) {
  const chatId = await page.evaluate(async (content) => {
    const user = crypto.randomUUID();
    const assistant = crypto.randomUUID();
    const now = Math.floor(Date.now() / 1000);
    const messages = {
      [user]: { id: user, parentId: null, childrenIds: [assistant], role: "user", content: "Chart", timestamp: now },
      [assistant]: { id: assistant, parentId: user, childrenIds: [], role: "assistant", content, done: true, timestamp: now },
    };
    const reply = await fetch("/api/v1/chats/new", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${localStorage.token}` },
      body: JSON.stringify({
        chat: { title: "q79", models: [], messages: Object.values(messages), history: { messages, currentId: assistant } },
      }),
    });
    if (!reply.ok) throw new Error(`chat create HTTP ${reply.status}`);
    return (await reply.json()).id;
  }, item.content);
  await page.goto(`${webuiURL}/c/${chatId}`, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForFunction(
    // Q81: the Japanese cases carry the Japanese verdict.
    () =>
      ["Figure verification passed", "図の検証に合格しました。"].some((verdict) =>
        [...document.querySelectorAll(".chat-assistant")].at(-1)?.textContent?.includes(verdict),
      ),
    { timeout: 60000 },
  );
  // KaTeX loads after the reply text: wait for the label before reading (none ⇒ the case fails).
  await page
    .waitForFunction(() => [...document.querySelectorAll(".chat-assistant")].at(-1)?.querySelector("strong, .katex"), { timeout: 20000 })
    .catch(() => {});
  const observed = await page.evaluate((markup) => {
    const reply = [...document.querySelectorAll(".chat-assistant")].at(-1);
    // The label: a `strong` (English) or KaTeX bold (Japanese, Q80); every other element counts.
    const label = reply.querySelector("strong, .katex");
    const paragraph = label?.closest("p");
    const drawn = label?.querySelector(".textbf") ?? label;
    const clone = paragraph?.cloneNode(true);
    clone?.querySelectorAll(".katex-mathml").forEach((node) => node.remove());
    return {
      label_kind: label ? (label.matches(".katex") ? "katex" : "strong") : null,
      label_text: label ? (label.querySelector(".katex-html") ?? label).textContent.trim() : null,
      label_weight: drawn ? Number(getComputedStyle(drawn).fontWeight) : null,
      strong: reply.querySelectorAll("strong").length,
      markup: [...reply.querySelectorAll(markup)]
        .filter((node) => !label?.contains(node))
        .map((node) => node.tagName.toLowerCase() + (node.className ? `.${String(node.className).split(" ")[0]}` : "")),
      // Svelte keeps template whitespace around tokens; the word joiner after an escaped
      // backslash (`inert.py::_JOINER`) draws nothing.
      text: clone ? clone.textContent.trim().replaceAll("\u2060", "") : null,
    };
  }, MARKUP);
  const ok =
    observed.text === item.expected &&
    observed.markup.length === 0 &&
    observed.label_kind === item.label_kind &&
    observed.label_text === item.label &&
    observed.strong === (item.label_kind === "strong" ? 1 : 0);
  results.push({ index, ok, note: item.note, expected: item.expected, ...observed });
  console.log(JSON.stringify({ index, ok, markup: observed.markup, label: observed.label_kind, weight: observed.label_weight }));
}
writeFileSync(resultPath, `${JSON.stringify(results, null, 1)}\n`);
await page.close();
await browser.disconnect();
const failed = results.filter((r) => !r.ok).length;
console.log(`${results.length - failed}/${results.length} cases rendered as plain text`);
process.exit(failed ? 1 : 0);
