// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// M10.3 + M17.4, arms re-keyed by M19.5: drive the launcher's banner prompts through the signed-in
// Open WebUI chat, one fresh chat per attempt, and record what the user saw before AND after a
// reload.
//
//   node m10u3_demo.mjs <browser-url> <webui-url> <csv> <arm> <attempts> <out-dir>
//
// arm = simple | misleading | ja-simple | ja-misleading | ja-clinic-simple | ja-clinic-misleading; its
// prompt is read from the webui/launch.sh assignment, and <csv> must be the file the arm names.
// The harness signs in with FV_WEBUI_EMAIL / FV_WEBUI_PASSWORD when the page asks for it. Records
// land as <out-dir>/<arm>-<n>.json + <arm>-<n>-<moment>.png; the PNG attachment itself is hashed,
// never trusted as a verdict.
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, join } from "node:path";
import puppeteer from "puppeteer-core";

const [browserURL, webuiURL, csvPath, arm, attemptsText, outDir] = process.argv.slice(2);
const ARMS = {
  simple: ["simple_prompt", "sales.csv"],
  misleading: ["misleading_prompt", "sales.csv"],
  "ja-simple": ["ja_simple_prompt", "sales.csv"],
  "ja-misleading": ["ja_misleading_prompt", "sales.csv"],
  "ja-clinic-simple": ["ja_clinic_simple_prompt", "clinic_ja.csv"],
  "ja-clinic-misleading": ["ja_clinic_misleading_prompt", "clinic_ja.csv"],
};
const PASS = "Figure verification passed";
const FAIL = "Figure verification failed, no image produced";
if (!Object.hasOwn(ARMS, arm) || !outDir) {
  throw new Error("usage: m10u3_demo.mjs <browser-url> <webui-url> <csv> <arm> <attempts> <out-dir>");
}
const [variable, dataset] = ARMS[arm];
if (basename(csvPath) !== dataset) throw new Error(`arm ${arm} needs ${dataset}, got ${csvPath}`);
const launcher = readFileSync(new URL("../../webui/launch.sh", import.meta.url), "utf8");
const assigned = launcher.match(new RegExp(`^${variable}="([^"\\n]*)"$`, "m"));
if (!assigned) throw new Error(`${variable} missing from webui/launch.sh`);
const PROMPT = assigned[1];
const attempts = Number.parseInt(attemptsText, 10);
mkdirSync(outDir, { recursive: true });
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

// protocolTimeout 0: puppeteer's 180 s default cut the verdict wait mid-generation on every
// long attempt (generation ~180 s on the MX150), so the wait timeouts below are the only bound.
const browser = await puppeteer.connect({ browserURL, protocolTimeout: 0 });
const page = (await browser.pages()).find((p) => p.url().startsWith(webuiURL)) ?? (await browser.newPage());
await page.setViewport({ width: 1440, height: 900 });
const cdp = await page.createCDPSession();

// Sign in once when the page shows the login form. The launcher prints the admin login; the harness
// reads it from FV_WEBUI_EMAIL / FV_WEBUI_PASSWORD and never writes it to a record.
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
    return {
      done: assistant?.done ?? false,
      content: assistant?.content ?? null,
      output: assistant?.output ?? null,
      files: (assistant?.files ?? []).map((f) => ({ type: f.type ?? null, url: String(f.url ?? "") })),
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
  const verdict = String(state.content ?? "").startsWith(PASS)
    ? "pass"
    : state.content === FAIL
      ? "fail"
      : "other";
  return {
    done: state.done,
    verdict,
    content: state.content,
    output_items: Array.isArray(state.output) ? state.output.length : null,
    file_pngs: state.files.filter((f) => f.url.startsWith("data:image/png;base64,")).length,
    dom_pngs: state.dom_images.map(({ width, height }) => ({ width, height })),
    png_sha256: [...new Set(pngs)],
    messages: state.messages,
    user_files: state.user_files,
    status: state.status,
  };
}

const settled = (text) => text.includes(PASS) || text.includes(FAIL);
for (let n = 1; n <= attempts; n += 1) {
  const record = { arm, attempt: n, prompt: PROMPT, dataset, csv_sha256: sha256(readFileSync(csvPath)) };
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
    const input = await page.$("input[type=file][multiple]");
    if (!input) throw new Error("Open WebUI multi-file input missing");
    await input.uploadFile(csvPath);
    await page.waitForFunction((name) => document.body.innerText.includes(name), { timeout: 90000 }, dataset);
    // Settle time for the upload to finish server-side; `user_files` in the record shows whether
    // the sent message actually carried the attachment.
    await new Promise((r) => setTimeout(r, 3000));
    await page.click("#chat-input");
    await cdp.send("Input.insertText", { text: PROMPT });
    const composed = await page.$eval("#chat-input", (node) => node.textContent);
    record.composed_identical = composed === PROMPT;
    if (!record.composed_identical) throw new Error("composer changed the pinned prompt");
    await page.waitForSelector("#send-message-button", { visible: true, timeout: 30000 });
    await page.click("#send-message-button");
    await page.waitForFunction(() => location.pathname.startsWith("/c/"), { timeout: 120000 });
    record.chat_id = new URL(page.url()).pathname.split("/")[2];
    await page.waitForFunction(
      (pass, fail) => document.body.innerText.includes(pass) || document.body.innerText.includes(fail),
      { timeout: 600000 },
      PASS,
      FAIL,
    );
    let before;
    for (let i = 0; i < 60; i += 1) {
      before = await readback(record.chat_id);
      if (before.done && settled(String(before.content))) break;
      await new Promise((r) => setTimeout(r, 1000));
    }
    await page.screenshot({ path: join(outDir, `${arm}-${n}-before.png`) });
    record.before = summarize(before);
    await page.reload({ waitUntil: "domcontentloaded", timeout: 90000 });
    await page.waitForFunction(
      (pass, fail) => document.body.innerText.includes(pass) || document.body.innerText.includes(fail),
      { timeout: 120000 },
      PASS,
      FAIL,
    );
    await new Promise((r) => setTimeout(r, 2000));
    const after = await readback(record.chat_id);
    await page.screenshot({ path: join(outDir, `${arm}-${n}-after.png`) });
    record.after = summarize(after);
    const png = [...after.files, ...after.dom_images.map((i) => ({ url: i.src }))].find((f) =>
      String(f.url).startsWith("data:image/png;base64,"),
    );
    if (png) {
      writeFileSync(
        join(outDir, `${arm}-${n}-figure.png`),
        Buffer.from(png.url.slice("data:image/png;base64,".length), "base64"),
      );
    }
    record.error = null;
  } catch (error) {
    record.error = String(error).slice(0, 400);
  }
  record.seconds = Math.round((Date.now() - started) / 1000);
  writeFileSync(join(outDir, `${arm}-${n}.json`), `${JSON.stringify(record, null, 2)}\n`);
  console.log(JSON.stringify({ arm, attempt: n, chat: record.chat_id ?? null,
    before: record.before?.verdict ?? null, after: record.after?.verdict ?? null,
    pngs: record.after?.png_sha256?.length ?? null, error: record.error, seconds: record.seconds }));
}
await browser.disconnect();
