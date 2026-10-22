// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Live cases through a signed-in Open WebUI chat (the `--codex` arm: gpt-6-luna, production pair),
// one fresh chat per attempt: what the user saw before AND after a reload, the status line's
// reason code, and the program the "Show checks" embed lists. m10u3_demo.mjs (frozen: the banner
// arms' record) is the flow this generalizes to a case file.
//
//   node luna_live.mjs <browser-url> <webui-url> <cases.json> <attempts> <out-dir> [<id-regex>]
//
// A case = {id, csv: repo-relative path | null, prompt}. Records land as <out-dir>/<id>-<n>.json
// (+ <id>-<n>-figure.png on a pass); an existing record is kept, so a rerun resumes. The harness
// signs in with FV_WEBUI_EMAIL / FV_WEBUI_PASSWORD and never writes them to a record.
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, join, resolve } from "node:path";
import puppeteer from "puppeteer-core";

const [browserURL, webuiURL, casesPath, attemptsText, outDir, only] = process.argv.slice(2);
if (!outDir) {
  throw new Error("usage: luna_live.mjs <browser-url> <webui-url> <cases.json> <attempts> <out-dir> [<id-regex>]");
}
// Q81: a kana request reads the verdict in Japanese.
const PASS_TEXTS = ["Figure verification passed", "図の検証に合格しました。"];
const FAIL_TEXTS = ["Figure verification failed, no image produced", "図の検証に合格しませんでした。画像は表示されません。"];
const ROOT = resolve(new URL("../..", import.meta.url).pathname);
const cases = JSON.parse(readFileSync(casesPath, "utf8")).cases.filter(
  (c) => !only || new RegExp(only).test(c.id),
);
const attempts = Number.parseInt(attemptsText, 10);
mkdirSync(outDir, { recursive: true });
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

// protocolTimeout 0: the verdict wait below is the only bound on a long generation.
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

async function readback(chatId) {
  return await page.evaluate(async (id) => {
    const reply = await fetch(`/api/v1/chats/${id}`, {
      headers: { Authorization: `Bearer ${localStorage.token}` },
    });
    if (!reply.ok) throw new Error(`chat readback HTTP ${reply.status}`);
    const payload = await reply.json();
    const messages = Object.values(payload.chat?.history?.messages ?? {});
    const assistant = messages.filter((m) => m.role === "assistant").at(-1);
    const user = messages.filter((m) => m.role === "user").at(-1);
    const status = (assistant?.statusHistory ?? []).at(-1);
    const last = [...document.querySelectorAll(".chat-assistant")].at(-1);
    const embed = new DOMParser().parseFromString(String(assistant?.embeds?.[0] ?? ""), "text/html");
    const listing = embed.querySelector("li details.row .listing");
    const failing = [...embed.querySelectorAll("li details.row")].find((row) =>
      row.textContent?.includes("✗"),
    );
    return {
      program: listing ? [...listing.querySelectorAll(".src")].map((s) => s.textContent).join("\n") : null,
      failing_row: failing ? (failing.querySelector("summary")?.textContent ?? "").trim() : null,
      done: assistant?.done ?? false,
      content: assistant?.content ?? null,
      files: (assistant?.files ?? []).map((f) => ({ type: f.type ?? null, url: String(f.url ?? "") })),
      tool_calls: (assistant?.output ?? []).filter((o) => o.type === "function_call").length,
      messages: messages.length,
      user_files: (user?.files ?? []).map((f) => String(f.name ?? f.file?.filename ?? f.type ?? "")),
      status: typeof status?.description === "string" ? status.description : null,
      dom_images: last
        ? [...last.querySelectorAll("img")]
            .filter((img) => img.src.startsWith("data:image/png;base64,"))
            .map((img) => ({ width: img.naturalWidth, height: img.naturalHeight, src: img.src }))
        : [],
    };
  }, chatId);
}

function summarize(state) {
  const pngs = [...state.files.map((f) => f.url), ...state.dom_images.map((i) => i.src)]
    .filter((url) => url.startsWith("data:image/png;base64,"))
    .map((url) => sha256(Buffer.from(url.slice("data:image/png;base64,".length), "base64")));
  const content = String(state.content ?? "");
  const verdict = PASS_TEXTS.some((text) => content.startsWith(text))
    ? "pass"
    : FAIL_TEXTS.includes(content)
      ? "fail"
      : "other";
  return {
    done: state.done,
    verdict,
    reason: /\(([a-z_]+)\)$/.exec(state.status ?? "")?.[1] ?? null,
    status: state.status,
    content: state.content,
    failing_row: state.failing_row,
    tool_calls: state.tool_calls,
    file_pngs: state.files.filter((f) => f.url.startsWith("data:image/png;base64,")).length,
    png_sha256: [...new Set(pngs)],
    messages: state.messages,
    user_files: state.user_files,
    program: state.program,
  };
}

const settled = (text) => [...PASS_TEXTS, ...FAIL_TEXTS].some((verdict) => text.includes(verdict));
for (const item of cases) {
  for (let n = 1; n <= attempts; n += 1) {
    const recordPath = join(outDir, `${item.id}-${n}.json`);
    if (existsSync(recordPath)) continue;
    const record = { id: item.id, arm: item.arm, attempt: n, prompt: item.prompt, csv: item.csv };
    if (item.csv) record.csv_sha256 = sha256(readFileSync(join(ROOT, item.csv)));
    record.started = new Date().toISOString();
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
      if (item.csv) {
        const input = await page.$("input[type=file][multiple]");
        if (!input) throw new Error("Open WebUI multi-file input missing");
        await input.uploadFile(join(ROOT, item.csv));
        const name = basename(item.csv);
        await page.waitForFunction((n) => document.body.innerText.includes(n), { timeout: 90000 }, name);
        // Settle time for the upload to finish server-side; `user_files` shows what the message carried.
        await new Promise((r) => setTimeout(r, 3000));
      }
      await page.click("#chat-input");
      await cdp.send("Input.insertText", { text: item.prompt });
      const composed = await page.$eval("#chat-input", (node) => node.textContent);
      record.composed_identical = composed === item.prompt;
      if (!record.composed_identical) throw new Error("composer changed the prompt");
      await page.waitForSelector("#send-message-button", { visible: true, timeout: 30000 });
      await page.click("#send-message-button");
      await page.waitForFunction(() => location.pathname.startsWith("/c/"), { timeout: 120000 });
      record.chat_id = new URL(page.url()).pathname.split("/")[2];
      await page.waitForFunction(
        (verdicts) => {
          const text = document.body.innerText;
          return verdicts.some((verdict) => text.includes(verdict)) || /Error|error/.test(
            [...document.querySelectorAll(".chat-assistant")].at(-1)?.innerText ?? "",
          );
        },
        { timeout: 600000 },
        [...PASS_TEXTS, ...FAIL_TEXTS],
      );
      let before;
      for (let i = 0; i < 90; i += 1) {
        before = await readback(record.chat_id);
        if (before.done && settled(String(before.content))) break;
        await new Promise((r) => setTimeout(r, 1000));
      }
      record.before = summarize(before);
      await page.reload({ waitUntil: "domcontentloaded", timeout: 90000 });
      await new Promise((r) => setTimeout(r, 3000));
      const after = await readback(record.chat_id);
      record.after = summarize(after);
      const png = [...after.files, ...after.dom_images.map((i) => ({ url: i.src }))].find((f) =>
        String(f.url).startsWith("data:image/png;base64,"),
      );
      if (png) {
        writeFileSync(
          join(outDir, `${item.id}-${n}-figure.png`),
          Buffer.from(png.url.slice("data:image/png;base64,".length), "base64"),
        );
      }
      record.error = null;
    } catch (error) {
      record.error = String(error).slice(0, 400);
      await page.screenshot({ path: join(outDir, `${item.id}-${n}-error.png`) }).catch(() => {});
    }
    record.seconds = Math.round((Date.now() - started) / 1000);
    writeFileSync(recordPath, `${JSON.stringify(record, null, 2)}\n`);
    console.log(JSON.stringify({ id: item.id, attempt: n, chat: record.chat_id ?? null,
      before: record.before?.verdict ?? null, after: record.after?.verdict ?? null,
      reason: record.after?.reason ?? null, error: record.error, seconds: record.seconds }));
  }
}
await browser.disconnect();
