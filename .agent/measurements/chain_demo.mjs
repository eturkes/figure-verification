// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Q68: drive one chat CHAIN through the signed-in Open WebUI — each prompt a follow-up in the same
// chat, an optional CSV attached before the first — and record what the user saw per turn before
// AND after a reload, plus the program the "Show checks" embed lists (its `program` row).
//
//   node chain_demo.mjs <browser-url> <webui-url> <label> <attempts> <out-dir> [--csv <path>] <prompt>...
//
// One fresh chat per attempt. Sign-in reads FV_WEBUI_EMAIL / FV_WEBUI_PASSWORD (never recorded).
// Records land as <out-dir>/<label>-<n>.json + <label>-<n>-t<turn>-figure.png per published PNG
// + <label>-<n>-after.png (the reloaded chat). The PNG is hashed, never trusted as a verdict.
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, join } from "node:path";
import puppeteer from "puppeteer-core";

const [browserURL, webuiURL, label, attemptsText, outDir, ...rest] = process.argv.slice(2);
const csvAt = rest[0] === "--csv" ? rest[1] : null;
const prompts = csvAt ? rest.slice(2) : rest;
const USAGE = "usage: chain_demo.mjs <browser-url> <webui-url> <label> <attempts> <out-dir> [--csv <path>] <prompt>...";
const attempts = Number.parseInt(attemptsText ?? "", 10);
if (!outDir || !(attempts >= 1) || prompts.length === 0) throw new Error(USAGE);
const PASS = "Figure verification passed";
const FAIL = "Figure verification failed, no image produced";
const PNG = "data:image/png;base64,";
mkdirSync(outDir, { recursive: true });
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

// protocolTimeout 0: puppeteer's 180 s default cuts a verdict wait mid-generation on the MX150;
// the wait timeouts below are the only bound.
const browser = await puppeteer.connect({ browserURL, protocolTimeout: 0 });
const page = (await browser.pages()).find((p) => p.url().startsWith(webuiURL)) ?? (await browser.newPage());
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

// The assistant replies on the chat's current branch, oldest first, each with its listed program.
async function replies(chatId) {
  return await page.evaluate(
    async (id, png) => {
      const reply = await fetch(`/api/v1/chats/${id}`, {
        headers: { Authorization: `Bearer ${localStorage.token}` },
      });
      if (!reply.ok) throw new Error(`chat readback HTTP ${reply.status}`);
      const history = (await reply.json()).chat?.history ?? {};
      const branch = [];
      for (let at = history.currentId; at && history.messages?.[at]; at = history.messages[at].parentId) {
        branch.unshift(history.messages[at]);
      }
      return branch
        .filter((m) => m.role === "assistant")
        .map((m) => {
          const embed = new DOMParser().parseFromString(String(m.embeds?.[0] ?? ""), "text/html");
          const listing = embed.querySelector("li details.row .listing");
          const lines = listing ? [...listing.querySelectorAll(".src")].map((s) => s.textContent) : null;
          const status = (m.statusHistory ?? []).at(-1);
          return {
            done: m.done ?? false,
            content: m.content ?? null,
            pngs: (m.files ?? []).map((f) => String(f.url ?? "")).filter((u) => u.startsWith(png)),
            status: typeof status?.description === "string" ? status.description : null,
            program: lines ? lines.join("\n") : null,
            elided: Boolean(listing?.parentElement?.querySelector(".elided, .gap")),
          };
        });
    },
    chatId,
    PNG,
  );
}

const settled = (m) => m?.done && (String(m.content).startsWith(PASS) || m.content === FAIL);
function summarize(m) {
  return {
    verdict: String(m.content ?? "").startsWith(PASS) ? "pass" : m.content === FAIL ? "fail" : "other",
    content: m.content,
    file_pngs: m.pngs.length,
    png_sha256: m.pngs.map((u) => sha256(Buffer.from(u.slice(PNG.length), "base64"))),
    status: m.status,
  };
}

async function send(text) {
  await page.click("#chat-input");
  await cdp.send("Input.insertText", { text });
  const composed = await page.$eval("#chat-input", (node) => node.textContent);
  if (composed !== text) throw new Error("composer changed the prompt");
  await page.waitForSelector("#send-message-button", { visible: true, timeout: 30000 });
  await page.click("#send-message-button");
}

for (let n = 1; n <= attempts; n += 1) {
  const record = { label, attempt: n, prompts, csv: csvAt ? basename(csvAt) : null, turns: [] };
  if (csvAt) record.csv_sha256 = sha256(readFileSync(csvAt));
  const started = Date.now();
  try {
    await page.goto(`${webuiURL}/`, { waitUntil: "domcontentloaded", timeout: 90000 });
    await page.waitForSelector("#chat-input", { timeout: 120000 });
    await page.evaluate(() => {
      [...document.querySelectorAll('[role="dialog"] button')]
        .find((b) => b.textContent?.includes("Okay, Let's Go!"))
        ?.click();
    });
    while (await page.$('button[aria-label="Remove File"]')) {
      await page.click('button[aria-label="Remove File"]');
    }
    if (csvAt) {
      const input = await page.$("input[type=file][multiple]");
      if (!input) throw new Error("Open WebUI multi-file input missing");
      await input.uploadFile(csvAt);
      await page.waitForFunction((name) => document.body.innerText.includes(name), { timeout: 90000 }, basename(csvAt));
      await new Promise((r) => setTimeout(r, 3000));
    }
    for (const [index, text] of prompts.entries()) {
      await send(text);
      if (index === 0) {
        await page.waitForFunction(() => location.pathname.startsWith("/c/"), { timeout: 120000 });
        record.chat_id = new URL(page.url()).pathname.split("/")[2];
      }
      let latest = [];
      for (let waited = 0; ; waited += 2) {
        if (waited > 900) throw new Error(`turn ${index + 1}: no verdict within 900 s`);
        latest = await replies(record.chat_id);
        if (latest.length === index + 1 && settled(latest[index])) break;
        await new Promise((r) => setTimeout(r, 2000));
      }
      // The outlet writes the verdict before its embed + files events land; let them settle.
      await new Promise((r) => setTimeout(r, 3000));
      latest = await replies(record.chat_id);
      const turn = latest[index];
      record.turns.push({ prompt: text, program: turn.program, program_elided: turn.elided, before: summarize(turn) });
      await page.waitForSelector("#chat-input", { timeout: 120000 });
    }
    await page.reload({ waitUntil: "domcontentloaded", timeout: 90000 });
    await page.waitForFunction(
      (pass, fail) => document.body.innerText.includes(pass) || document.body.innerText.includes(fail),
      { timeout: 120000 },
      PASS,
      FAIL,
    );
    await new Promise((r) => setTimeout(r, 2000));
    await page.screenshot({ path: join(outDir, `${label}-${n}-after.png`) });
    const after = await replies(record.chat_id);
    after.forEach((m, index) => {
      if (record.turns[index]) record.turns[index].after = summarize(m);
      if (m.pngs[0]) {
        writeFileSync(join(outDir, `${label}-${n}-t${index + 1}-figure.png`), Buffer.from(m.pngs[0].slice(PNG.length), "base64"));
      }
    });
    record.error = null;
  } catch (error) {
    record.error = String(error).slice(0, 400);
  }
  record.seconds = Math.round((Date.now() - started) / 1000);
  writeFileSync(join(outDir, `${label}-${n}.json`), `${JSON.stringify(record, null, 2)}\n`);
  console.log(JSON.stringify({ label, attempt: n, chat: record.chat_id ?? null, error: record.error, seconds: record.seconds,
    turns: record.turns.map((t) => [t.before.verdict, t.after?.verdict ?? null, t.after?.file_pngs ?? null, t.before.status]) }));
}
await browser.disconnect();
