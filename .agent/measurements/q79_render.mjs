// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Q79: Open WebUI's own renderer over the model-note corpus (`q79_corpus.py`). Each case is stored
// as an assistant reply in a new chat of the signed-in user; the page renders it, and the record
// counts the elements markup would have made + reads the note paragraph's text.
//
//   node q79_render.mjs <browser-url> <webui-url> <corpus.json> <result.json>
//
// Signs in with FV_WEBUI_EMAIL / FV_WEBUI_PASSWORD when the page asks. Exit 1 on any case whose
// paragraph text differs, which holds a markup element, or whose label is not the one `strong`.
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
    () => [...document.querySelectorAll(".chat-assistant")].at(-1)?.textContent?.includes("Figure verification passed"),
    { timeout: 60000 },
  );
  const observed = await page.evaluate((markup) => {
    const reply = [...document.querySelectorAll(".chat-assistant")].at(-1);
    const strong = [...reply.querySelectorAll("strong")];
    const paragraph = strong[0]?.closest("p");
    return {
      strong: strong.map((node) => node.textContent.trim()),
      markup: [...reply.querySelectorAll(markup)].map((node) => node.tagName.toLowerCase() + (node.className ? `.${String(node.className).split(" ")[0]}` : "")),
      // Svelte keeps template whitespace around tokens; the word joiner after an escaped
      // backslash (`inert.py::_JOINER`) draws nothing.
      text: paragraph ? paragraph.textContent.trim().replaceAll("\u2060", "") : null,
    };
  }, MARKUP);
  const label = item.label;
  const ok = observed.text === item.expected && observed.markup.length === 0 && observed.strong.length === 1 && observed.strong[0] === label;
  results.push({ index, ok, note: item.note, expected: item.expected, ...observed });
  console.log(JSON.stringify({ index, ok, markup: observed.markup, strong: observed.strong.length }));
}
writeFileSync(resultPath, `${JSON.stringify(results, null, 1)}\n`);
await page.close();
await browser.disconnect();
const failed = results.filter((r) => !r.ok).length;
console.log(`${results.length - failed}/${results.length} cases rendered as plain text`);
process.exit(failed ? 1 : 0);
