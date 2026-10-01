// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// M16.1 L1-L5: the "Show checks" embed between the status line and the verdict text.
//
//   node m16u1_checks.mjs <browser-url> <webui-url> <csv> <checks.json> <out-dir>
//
// Drives a `webui/launch.sh --stub` instance, one fresh chat per case. checks.json = every
// "Show checks" text + the stub's expected PASS reply, written by `m16u1_dump.py` (README).
// Per case: the embed is the ONE frame in the reply, sits after the status line and before the
// verdict, opens collapsed, grows to its content once `Show checks` is clicked (frame = wrapper, no
// inner scroll), lists the expected row states with their texts, and shrinks again on `Hide
// checks`; the same holds after a reload, and the REST readback keeps `content`/`output` fixed with
// one stored embed. The expanded FAIL must also fit at a 760 px viewport. Then every expanded reply
// is captured under the light AND the dark theme for inspection. Exit code 0 = every check holds.
// FV_CASES=<name,...> runs a subset.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import puppeteer from "puppeteer-core";

const [browserURL, webuiURL, csvPath, checksPath, outDir] = process.argv.slice(2);
if (!outDir) throw new Error("usage: m16u1_checks.mjs <browser-url> <webui-url> <csv> <checks.json> <out-dir>");
const PASS = "Figure verification passed";
const FAIL = "Figure verification failed, no image produced";
const launcher = readFileSync(new URL("../../webui/launch.sh", import.meta.url), "utf8");
const pinned = (name) => new RegExp(`${name}="([^"]+)"`).exec(launcher)[1];
const table = JSON.parse(readFileSync(checksPath, "utf8"));
// Row states are hand-stated per case: the failing check of each expected reason.
const states = (failing) => table.checks.map((_, i) => (i < failing ? "pass" : i === failing ? "fail" : "skip"));
const CASES = [
  { name: "refused", prompt: pinned("elaborate_prompt"), csv: true, reason: "expression_not_admitted", lang: 0, states: states(3) },
  { name: "japanese", prompt: "地域ごとの売上を棒グラフにしてください。", csv: false, reason: "no_tool_call", lang: 1, states: states(0) },
  { name: "pass", prompt: pinned("simple_prompt"), csv: true, reason: null, lang: 0, states: states(11) },
].filter((item) => !process.env.FV_CASES || process.env.FV_CASES.split(",").includes(item.name));
// An unknown or empty FV_CASES selection would otherwise grade zero cases green.
const requested = process.env.FV_CASES ? process.env.FV_CASES.split(",") : [];
if (CASES.length === 0 || requested.some((name) => !CASES.some((item) => item.name === name))) {
  throw new Error(`FV_CASES names no case or an unknown case: ${process.env.FV_CASES}`);
}
mkdirSync(outDir, { recursive: true });

const browser = await puppeteer.connect({ browserURL, protocolTimeout: 0 });
const page = (await browser.pages()).find((p) => p.url().startsWith(webuiURL)) ?? (await browser.newPage());
await page.setViewport({ width: 1280, height: 900 });
const cdp = await page.createCDPSession();

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
const settle = (ms) => new Promise((r) => setTimeout(r, ms));
const verdictShown = () =>
  page.waitForFunction(
    (pass, fail) => document.body.innerText.includes(pass) || document.body.innerText.includes(fail),
    { timeout: 300000 },
    PASS,
    FAIL,
  );

// The embed frame of the last reply, its page-side box, and its order against status + verdict.
async function frameFacts() {
  const facts = await page.evaluate((pass, fail) => {
    const reply = [...document.querySelectorAll(".chat-assistant")].at(-1);
    const frames = [...(reply?.querySelectorAll("iframe") ?? [])];
    const status = reply?.querySelector(".status-description");
    const verdict = [...(reply?.querySelectorAll("p, div") ?? [])].find(
      (node) => node.children.length === 0 && [pass, fail].some((text) => node.textContent?.trim().startsWith(text)),
    );
    const after = (a, b) => Boolean(a && b && a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    const box = frames[0]?.getBoundingClientRect();
    const pngs = [...(reply?.querySelectorAll("img") ?? [])].filter((img) => img.src.startsWith("data:image/png;base64,"));
    return {
      frames: frames.length,
      pngs: pngs.length,
      png_before_frame: after(pngs[0], frames[0]),
      height: box ? Math.round(box.height) : null,
      status_before_frame: status ? after(status, frames[0]) : null,
      frame_before_verdict: after(frames[0], verdict),
    };
  }, PASS, FAIL);
  const handle = await page.evaluateHandle(() =>
    [...document.querySelectorAll(".chat-assistant")].at(-1)?.querySelector("iframe"),
  );
  const frame = handle.asElement() ? await handle.asElement().contentFrame() : null;
  return { facts, frame };
}

const readRows = (frame) =>
  frame.evaluate(() => ({
    lang: document.documentElement.lang,
    open: document.querySelector("details")?.open ?? null,
    summary: document.querySelector("summary")?.innerText.trim() ?? null,
    rows: [...document.querySelectorAll("li")].map((li) => ({
      state: li.className,
      mark: li.querySelector(".mark")?.textContent ?? null,
      label: li.querySelector(".mark")?.getAttribute("aria-label") ?? null,
      title: li.querySelector(".title")?.firstChild?.textContent?.trim() ?? null,
      covers: li.querySelector(".covers")?.textContent ?? null,
      cause: li.querySelector(".cause")?.textContent ?? null,
      unrun: li.querySelector(".unrun")?.textContent ?? null,
    })),
    inner_scroll: document.documentElement.scrollHeight - window.innerHeight,
    wrapper: Math.ceil(document.getElementById("r").getBoundingClientRect().height),
  }));

// One click toggles the disclosure either way.
async function expand(frame) {
  await frame.click("summary");
  await settle(800);
}
const collapse = expand;

function rowsHold(item, read, expanded) {
  const lang = item.lang;
  const hidden = expanded ? table.hide[lang] : table.show[lang];
  return (
    read.lang === (lang ? "ja" : "en") &&
    read.open === expanded &&
    read.summary === hidden &&
    read.rows.length === table.checks.length &&
    read.rows.every((row, i) => {
      const [title, covers] = table.texts[table.checks[i]][lang];
      const want = item.states[i];
      const [glyph, labels] = table.marks[want];
      return (
        row.state === want &&
        row.mark === glyph &&
        row.label === labels[lang] &&
        row.title === title &&
        row.covers === covers &&
        row.cause === (want === "fail" ? table.reasons[item.reason][lang] : null) &&
        row.unrun === (want === "skip" ? table.unrun[lang] : null)
      );
    })
  );
}

async function readback(chatId) {
  return await page.evaluate(async (id) => {
    const reply = await fetch(`/api/v1/chats/${id}`, { headers: { Authorization: `Bearer ${localStorage.token}` } });
    const payload = await reply.json();
    const assistant = Object.values(payload.chat?.history?.messages ?? {}).filter((m) => m.role === "assistant").at(-1);
    return {
      content: assistant?.content ?? null,
      output_text: (assistant?.output ?? []).flatMap((item) => item.content ?? []).map((part) => part.text ?? "").join(""),
      status: (assistant?.statusHistory ?? []).map((s) => s.description ?? null),
      embeds: (assistant?.embeds ?? []).length,
      pngs: (assistant?.files ?? []).filter((f) => f.type === "image" && String(f.url ?? "").startsWith("data:image/png;base64,")).length,
    };
  }, chatId);
}

const results = [];
for (const item of CASES) {
  const record = { case: item.name, reason: item.reason };
  try {
    await page.goto(`${webuiURL}/`, { waitUntil: "domcontentloaded", timeout: 90000 });
    await page.waitForSelector("#chat-input", { timeout: 120000 });
    await page.evaluate(() => {
      [...document.querySelectorAll('[role="dialog"] button')].find((b) => b.textContent?.includes("Okay, Let's Go!"))?.click();
    });
    while (await page.$('button[aria-label="Remove File"]')) await page.click('button[aria-label="Remove File"]');
    if (item.csv) {
      await (await page.$("input[type=file][multiple]")).uploadFile(csvPath);
      await page.waitForFunction(() => document.body.innerText.includes("sales.csv"), { timeout: 90000 });
      await settle(3000);
    }
    await page.click("#chat-input");
    await cdp.send("Input.insertText", { text: item.prompt });
    await page.waitForSelector("#send-message-button", { visible: true, timeout: 30000 });
    await page.click("#send-message-button");
    await page.waitForFunction(() => location.pathname.startsWith("/c/"), { timeout: 120000 });
    record.chat_id = new URL(page.url()).pathname.split("/")[2];
    await verdictShown();
    await settle(2500);
    for (const phase of ["live", "reload"]) {
      if (phase === "reload") {
        await page.reload({ waitUntil: "domcontentloaded", timeout: 90000 });
        await verdictShown();
        await settle(2500);
      }
      const { facts, frame } = await frameFacts();
      const collapsed = frame ? await readRows(frame) : null;
      if (frame) await expand(frame);
      const expandedFacts = (await frameFacts()).facts;
      const expanded = frame ? await readRows(frame) : null;
      if (phase === "live") await page.screenshot({ path: join(outDir, `${item.name}-expanded.png`) });
      if (frame) await collapse(frame);
      const recollapsed = (await frameFacts()).facts;
      record[phase] = {
        collapsed_facts: facts,
        expanded_height: expandedFacts.height,
        wrapper_height: expanded?.wrapper ?? null,
        recollapsed_height: recollapsed.height,
        collapsed_ok: Boolean(collapsed && rowsHold(item, collapsed, false)),
        expanded_ok: Boolean(expanded && rowsHold(item, expanded, true)),
        inner_scroll: expanded?.inner_scroll ?? null,
        states: expanded?.rows.map((row) => row.state) ?? null,
      };
    }
    record.rest = await readback(record.chat_id);
    const want = item.reason === null ? null : `${table.reasons[item.reason][item.lang]} (${item.reason})`;
    const phaseOk = (p) =>
      p.collapsed_facts.frames === 1 &&
      (item.reason === null
        ? p.collapsed_facts.pngs >= 1 && p.collapsed_facts.png_before_frame === true
        : p.collapsed_facts.pngs === 0) &&
      p.collapsed_facts.frame_before_verdict === true &&
      (item.reason === null || p.collapsed_facts.status_before_frame === true) &&
      p.collapsed_facts.height !== null && p.collapsed_facts.height < 60 &&
      p.expanded_height > 300 &&
      p.wrapper_height !== null && Math.abs(p.expanded_height - p.wrapper_height) <= 2 &&
      p.inner_scroll !== null && p.inner_scroll <= 1 &&
      p.recollapsed_height !== null && p.recollapsed_height < 60 &&
      p.collapsed_ok && p.expanded_ok;
    record.ok =
      phaseOk(record.live) && phaseOk(record.reload) && record.rest.embeds === 1 &&
      (item.reason === null
        ? record.rest.content === table.pass_text && record.rest.output_text === table.pass_text &&
          record.rest.pngs === 1
        : record.rest.content === FAIL && record.rest.output_text === FAIL && record.rest.pngs === 0 &&
          record.rest.status.at(-1) === want);
  } catch (error) {
    record.error = String(error).slice(0, 400);
    record.ok = false;
  }
  results.push(record);
  console.log(JSON.stringify({ case: record.case, ok: record.ok, chat: record.chat_id ?? null, error: record.error ?? null }));
}

// L4: the expanded FAIL at a narrow viewport re-sizes to its taller content.
const narrow = { case: "refused", ok: false };
const refused = results.find((r) => r.case === "refused" && r.chat_id);
if (refused) {
  await page.setViewport({ width: 760, height: 900 });
  await page.goto(`${webuiURL}/c/${refused.chat_id}`, { waitUntil: "domcontentloaded", timeout: 90000 });
  await verdictShown();
  await settle(2500);
  const { frame } = await frameFacts();
  if (frame) {
    await expand(frame);
    const read = await readRows(frame);
    const height = (await frameFacts()).facts.height;
    Object.assign(narrow, { height, wrapper: read.wrapper, inner_scroll: read.inner_scroll });
    narrow.ok = Math.abs(height - read.wrapper) <= 2 && read.inner_scroll <= 1 &&
      height > (refused.live?.expanded_height ?? Infinity);
    await page.screenshot({ path: join(outDir, "refused-narrow.png") });
  }
  await page.setViewport({ width: 1280, height: 900 });
}
console.log(JSON.stringify(narrow));

// L4: each expanded reply under the light and the dark theme; a person inspects the PNGs.
const shots = [];
for (const theme of ["light", "dark"]) {
  await page.evaluate((t) => localStorage.setItem("theme", t), theme);
  for (const record of results.filter((r) => r.chat_id)) {
    await page.goto(`${webuiURL}/c/${record.chat_id}`, { waitUntil: "domcontentloaded", timeout: 90000 });
    await verdictShown();
    await settle(2500);
    const { frame } = await frameFacts();
    if (frame) await expand(frame);
    await page.evaluate(() => [...document.querySelectorAll(".chat-assistant")].at(-1)?.querySelector("iframe")?.scrollIntoView({ block: "center" }));
    await settle(500);
    const path = join(outDir, `${record.case}-${theme}.png`);
    await page.screenshot({ path });
    shots.push(path);
  }
}
await page.evaluate(() => localStorage.setItem("theme", "system"));
const ok = results.length > 0 && results.length === CASES.length && results.every((r) => r.ok) &&
  (!refused || narrow.ok);
console.log(JSON.stringify({ shots, ok }));
writeFileSync(join(outDir, "m16u1_checks.json"), `${JSON.stringify({ ok, results, narrow, shots }, null, 2)}\n`);
await browser.disconnect();
process.exitCode = ok ? 0 : 1;
