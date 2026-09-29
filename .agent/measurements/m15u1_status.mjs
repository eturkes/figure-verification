// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// M15.1 L1-L5: the failure reason a user reads above `Figure verification failed, no image produced`.
//
//   node m15u1_status.mjs <browser-url> <webui-url> <csv> <reasons.json> <webui.log> <out-dir>
//
// Drives a `webui/launch.sh --stub` instance, one fresh chat per case, and records the status line
// the DOM shows before AND after a reload beside the REST readback of that message. reasons.json =
// {reason: [english, japanese]}, dumped from `webui.paste_in.reasons.REASONS`; the width case sets
// each text into the live status element, because Open WebUI clamps a status to one line. A FAIL
// case also needs its one record in <webui.log>. Exit code 0 = every case, the log records and the
// width sweep hold.
// The block case needs `--disable-features=IsolateSandboxedIframes` on the browser: OWUI's Pyodide
// iframe is sandboxed, so Chromium otherwise runs it out of process, where page-level request
// interception never sees its `pyodide.js`. FV_CASES=<name,...> runs a subset.
import { mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import puppeteer from "puppeteer-core";

const [browserURL, webuiURL, csvPath, reasonsPath, logPath, outDir] = process.argv.slice(2);
if (!outDir) {
  throw new Error("usage: m15u1_status.mjs <browser-url> <webui-url> <csv> <reasons.json> <webui.log> <out-dir>");
}
const logRecords = (from) =>
  // `from` is a byte offset (statSync), so slice the bytes before decoding them.
  readFileSync(logPath)
    .subarray(from)
    .toString("utf8")
    .split("\n")
    .filter((line) => line.includes("figure verification failed reason="))
    .map((line) => line.slice(line.indexOf("figure verification failed reason=")).trim());
const PASS = "Figure verification passed";
const FAIL = "Figure verification failed, no image produced";
const launcher = readFileSync(new URL("../../webui/launch.sh", import.meta.url), "utf8");
const pinned = (name) => new RegExp(`${name}="([^"]+)"`).exec(launcher)[1];
const reasons = JSON.parse(readFileSync(reasonsPath, "utf8"));
// csv: attach the CSV; block: abort every pyodide.js load, as a LAN-blocking ad blocker does.
const CASES = [
  { name: "refused", prompt: pinned("elaborate_prompt"), csv: true, block: false, expect: "expression_not_admitted", lang: 0 },
  { name: "japanese", prompt: "地域ごとの売上を棒グラフにしてください。", csv: false, block: false, expect: "no_tool_call", lang: 1 },
  { name: "blocked", prompt: pinned("simple_prompt"), csv: true, block: true, expect: "sandbox_unavailable", lang: 0 },
  { name: "pass", prompt: pinned("simple_prompt"), csv: true, block: false, expect: null, lang: 0 },
].filter((item) => !process.env.FV_CASES || process.env.FV_CASES.split(",").includes(item.name));
mkdirSync(outDir, { recursive: true });
const ours = new Set(Object.entries(reasons).flatMap(([code, pair]) => pair.map((text) => `${text} (${code})`)));

const browser = await puppeteer.connect({ browserURL, protocolTimeout: 0 });
const page = (await browser.pages()).find((p) => p.url().startsWith(webuiURL)) ?? (await browser.newPage());
await page.setViewport({ width: 1280, height: 800 });
const cdp = await page.createCDPSession();
let blocking = false;
let blocked = 0;
await page.setRequestInterception(true);
page.on("request", (request) => {
  if (blocking && request.url().includes("/pyodide/pyodide.js")) {
    blocked += 1;
    request.abort("blockedbyclient");
  } else request.continue();
});

await page.goto(`${webuiURL}/`, { waitUntil: "domcontentloaded", timeout: 90000 });
// The SPA re-renders its first form once its config loads, which detaches an early handle.
await new Promise((r) => setTimeout(r, 3000));
const entry = await page.waitForSelector("#email, #chat-input", { timeout: 120000 });
if (await entry.evaluate((node) => node.id === "email")) {
  await page.click("#email");
  await cdp.send("Input.insertText", { text: process.env.FV_WEBUI_EMAIL ?? "" });
  await page.click("#password");
  await cdp.send("Input.insertText", { text: process.env.FV_WEBUI_PASSWORD ?? "" });
  await page.keyboard.press("Enter");
  await page.waitForSelector("#chat-input", { timeout: 120000 });
}

const statusText = () =>
  page.evaluate(() => {
    const last = [...document.querySelectorAll(".chat-assistant")].at(-1);
    return last?.querySelector(".status-description .line-clamp-1")?.textContent?.trim() ?? null;
  });

async function readback(chatId) {
  return await page.evaluate(async (id) => {
    const reply = await fetch(`/api/v1/chats/${id}`, { headers: { Authorization: `Bearer ${localStorage.token}` } });
    const payload = await reply.json();
    const assistant = Object.values(payload.chat?.history?.messages ?? {}).filter((m) => m.role === "assistant").at(-1);
    return {
      done: assistant?.done ?? false,
      content: assistant?.content ?? null,
      output_text: (assistant?.output ?? []).flatMap((item) => item.content ?? []).map((part) => part.text ?? "").join(""),
      status: (assistant?.statusHistory ?? []).map((s) => s.description ?? null),
      files: (assistant?.files ?? []).length,
      pngs: (assistant?.files ?? []).filter(
        (f) => f.type === "image" && String(f.url ?? "").startsWith("data:image/png;base64,"),
      ).length,
      dom_pngs: [...([...document.querySelectorAll(".chat-assistant")].at(-1)?.querySelectorAll("img") ?? [])]
        .filter((img) => img.src.startsWith("data:image/png;base64,")).length,
    };
  }, chatId);
}

const results = [];
for (const item of CASES) {
  const record = { case: item.name, expect: item.expect };
  blocked = 0;
  const logFrom = statSync(logPath).size;
  try {
    blocking = item.block;
    await page.goto(`${webuiURL}/`, { waitUntil: "domcontentloaded", timeout: 90000 });
    await page.waitForSelector("#chat-input", { timeout: 120000 });
    // A fresh instance opens its release-notes dialog over the composer.
    await page.evaluate(() => {
      [...document.querySelectorAll('[role="dialog"] button')]
        .find((b) => b.textContent?.includes("Okay, Let's Go!"))
        ?.click();
    });
    while (await page.$('button[aria-label="Remove File"]')) await page.click('button[aria-label="Remove File"]');
    if (item.csv) {
      await (await page.$("input[type=file][multiple]")).uploadFile(csvPath);
      await page.waitForFunction(() => document.body.innerText.includes("sales.csv"), { timeout: 90000 });
      await new Promise((r) => setTimeout(r, 3000));
    }
    await page.click("#chat-input");
    await cdp.send("Input.insertText", { text: item.prompt });
    await page.waitForSelector("#send-message-button", { visible: true, timeout: 30000 });
    await page.click("#send-message-button");
    await page.waitForFunction(() => location.pathname.startsWith("/c/"), { timeout: 120000 });
    record.chat_id = new URL(page.url()).pathname.split("/")[2];
    await page.waitForFunction(
      (pass, fail) => document.body.innerText.includes(pass) || document.body.innerText.includes(fail),
      { timeout: 300000 },
      PASS,
      FAIL,
    );
    await new Promise((r) => setTimeout(r, 2000));
    record.dom_before = await statusText();
    record.rest = await readback(record.chat_id);
    await page.screenshot({ path: join(outDir, `${item.name}.png`) });
    blocking = false;
    await page.reload({ waitUntil: "domcontentloaded", timeout: 90000 });
    await page.waitForFunction(
      (pass, fail) => document.body.innerText.includes(pass) || document.body.innerText.includes(fail),
      { timeout: 120000 },
      PASS,
      FAIL,
    );
    await new Promise((r) => setTimeout(r, 2000));
    record.dom_after = await statusText();
    record.blocked_requests = blocked;
    record.log = logRecords(logFrom);
    const mine = record.rest.status.filter((text) => ours.has(text));
    const want = item.expect === null ? null : `${reasons[item.expect][item.lang]} (${item.expect})`;
    record.want = want;
    record.ok =
      (item.expect === null
        ? record.rest.content.startsWith(PASS) && mine.length === 0 && record.rest.files === 1 &&
          record.rest.pngs === 1 && record.rest.dom_pngs >= 1 && record.log.length === 0 &&
          !ours.has(record.dom_before) && !ours.has(record.dom_after)
        : record.rest.content === FAIL && record.rest.output_text === FAIL && record.rest.files === 0 &&
          mine.length === 1 && record.rest.status.at(-1) === want &&
          record.dom_before === want && record.dom_after === want &&
          record.log.length === 1 && record.log[0] === `figure verification failed reason=${item.expect}`) &&
      (!item.block || blocked > 0);
  } catch (error) {
    record.error = String(error).slice(0, 400);
    record.ok = false;
  }
  results.push(record);
  console.log(JSON.stringify({ case: record.case, ok: record.ok, chat: record.chat_id ?? null, dom: record.dom_after ?? null, error: record.error ?? null }));
}

// L4 on the last FAIL chat that showed a status: every text, in both languages, on one line.
const failed = results.filter((r) => r.expect !== null && r.chat_id).at(-1);
const width = { viewport: page.viewport(), texts: 0, clamped: [] };
if (failed) {
  await page.goto(`${webuiURL}/c/${failed.chat_id}`, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForSelector(".chat-assistant .status-description .line-clamp-1", { timeout: 60000 });
  // The open sidebar is the narrowest chat column at this viewport.
  const toggle = await page.$('button[aria-label="Open Sidebar"]');
  if (toggle) {
    await toggle.click();
    await new Promise((r) => setTimeout(r, 1500));
  }
  width.sidebar_px = await page.evaluate(() => document.querySelector("#sidebar")?.getBoundingClientRect().width ?? 0);
  const texts = Object.entries(reasons).flatMap(([code, pair]) => pair.map((sentence) => `${sentence} (${code})`));
  width.texts = texts.length;
  width.clamped = await page.evaluate((all) => {
    const node = [...document.querySelectorAll(".chat-assistant")].at(-1).querySelector(".status-description .line-clamp-1");
    return all.filter((text) => {
      node.textContent = text;
      return node.scrollHeight > node.clientHeight;
    });
  }, texts);
}
const expectedTexts = Object.keys(reasons).length * 2;
// The open sidebar is the narrowest chat column; a closed one measures an easier width.
width.ok = width.texts === expectedTexts && width.clamped.length === 0 && (width.sidebar_px ?? 0) >= 200;
const ok = results.length === CASES.length && results.every((r) => r.ok) && width.ok;
console.log(JSON.stringify({ width_texts: width.texts, clamped: width.clamped.length, sidebar_px: width.sidebar_px ?? null, ok }));
writeFileSync(join(outDir, "m15u1_status.json"), `${JSON.stringify({ ok, results, width }, null, 2)}\n`);
await browser.disconnect();
process.exitCode = ok ? 0 : 1;
