// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// M10.3: reopen recorded chats AFTER the fact and read what Open WebUI persisted -- the verdict
// text, the attached PNGs and the inline PNG count once the page settles. Used for attempts whose
// live read failed; it observes the persisted outcome, never the live stream.
//
//   node m10u3_readback.mjs <browser-url> <webui-url> <out-dir> <record.json>...
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { basename, join } from "node:path";
import puppeteer from "puppeteer-core";

const [browserURL, webuiURL, outDir, ...records] = process.argv.slice(2);
const PASS = "Figure verification passed";
const FAIL = "Figure verification failed, no image produced";
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const browser = await puppeteer.connect({ browserURL, protocolTimeout: 0 });
const page = (await browser.pages()).find((p) => p.url().startsWith(webuiURL)) ?? (await browser.newPage());
for (const path of records) {
  const record = JSON.parse(readFileSync(path, "utf8"));
  await page.goto(`${webuiURL}/c/${record.chat_id}`, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForFunction(
    (pass, fail) => document.body.innerText.includes(pass) || document.body.innerText.includes(fail),
    { timeout: 120000 },
    PASS,
    FAIL,
  );
  await new Promise((r) => setTimeout(r, 2000));
  const state = await page.evaluate(async (id) => {
    const reply = await fetch(`/api/v1/chats/${id}`, {
      headers: { Authorization: `Bearer ${localStorage.token}` },
    });
    const payload = await reply.json();
    const messages = Object.values(payload.chat?.history?.messages ?? {});
    const assistant = messages.filter((m) => m.role === "assistant").at(-1);
    const last = [...document.querySelectorAll(".chat-assistant")].at(-1);
    return {
      done: assistant?.done ?? false,
      content: assistant?.content ?? null,
      files: (assistant?.files ?? []).map((f) => String(f.url ?? "")),
      dom_pngs: last
        ? [...last.querySelectorAll("img")].filter((i) => i.src.startsWith("data:image/png;base64,")).length
        : 0,
    };
  }, record.chat_id);
  const pngs = state.files
    .filter((u) => u.startsWith("data:image/png;base64,"))
    .map((u) => sha256(Buffer.from(u.slice(22), "base64")));
  const verdict = String(state.content).startsWith(PASS) ? "pass" : state.content === FAIL ? "fail" : "other";
  const out = { chat_id: record.chat_id, done: state.done, verdict, content: state.content,
    file_pngs: pngs.length, dom_pngs: state.dom_pngs, png_sha256: pngs };
  const name = basename(path, ".json");
  await page.screenshot({ path: join(outDir, `${name}-readback.png`) });
  writeFileSync(join(outDir, `${name}-readback.json`), `${JSON.stringify(out, null, 2)}\n`);
  console.log(JSON.stringify({ name, verdict, file_pngs: pngs.length, dom_pngs: state.dom_pngs }));
}
await browser.disconnect();
