// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// M16.1 L1-L5 + M18.4 L1-L3 + M20.2: the "Show checks" embed between the status line and the
// verdict text, and each row's own disclosure (what the check does, its program lines, why, link).
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
// is captured under the light AND the dark theme for inspection. M18.4 + M20.2: with the list
// expanded, each of the case's rows opens on click, grows the frame to its content, shows its
// hand-stated program lines (label, marked line) or note + reference link, the first row's link opens
// in a new tab, and each row closes again; live + reload.
// Exit code 0 = every check holds. FV_CASES=<name,...> runs a subset.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import puppeteer from "puppeteer-core";

const [browserURL, webuiURL, csvPath, checksPath, outDir] = process.argv.slice(2);
if (!outDir) throw new Error("usage: m16u1_checks.mjs <browser-url> <webui-url> <csv> <checks.json> <out-dir>");
// Q81: a kana request reads the verdict in Japanese; each case expects its own language's.
const PASS_TEXTS = ["Figure verification passed", "図の検証に合格しました。"];
const FAIL_TEXTS = ["Figure verification failed, no image produced", "図の検証に合格しませんでした。画像は表示されません。"];
const launcher = readFileSync(new URL("../../webui/launch.sh", import.meta.url), "utf8");
const pinned = (name) => new RegExp(`${name}="([^"]+)"`).exec(launcher)[1];
const table = JSON.parse(readFileSync(checksPath, "utf8"));
// Row states are hand-stated per case: the failing check of each expected reason.
const states = (failing) => table.checks.map((_, i) => (i < failing ? "pass" : i === failing ? "fail" : "skip"));
// M18.4 + M19.5 + M20.2: the rows each case opens, hand-stated from the stub's banner programs
// (`webui/banner.json`, 18 lines each). `misleading`: the axes row lists the axes line 12, title +
// labels 13-15 and `plt.ylim(30000, 45000)` at 16, marked; the run row its note; the not-checked
// values row nothing. `simple`: the program row all 18 lines; the axes row the axes line 12, title +
// labels 13-15 and `plt.xticks(rotation=45)` at 16 (M20.4); the values row `read_csv` 5, `groupby`
// 8 and the drawing line 12; the columns row those + title + labels 13-15; attach its note.
const GUIDE = [
  "https://github.com/eturkes/figure-verification/blob/main/docs/checks.md",
  "https://github.com/eturkes/figure-verification/blob/main/docs/checks.ja.md",
];
const span = (n) => Array.from({ length: n }, (_, i) => i + 1);
// `label` / `note` name a checks.json text: the listing's label (`code` | `related`), the note.
const row = (check, lines = null, extra = {}) =>
  ({ check, lines, at: [], marks: [], label: lines && "related", note: null, ...extra });
const CASES = [
  { name: "refused", prompt: pinned("misleading_prompt"), csv: true, reason: "zero_not_in_limits", lang: 0, states: states(4),
    rows: [
      row("axes", [12, 13, 14, 15, 16], { at: [16], marks: ["plt.ylim(30000, 45000)"] }),
      row("run", null, { note: "ran" }),
      row("values"),
    ] },
  { name: "japanese", prompt: "地域ごとの売上を棒グラフにしてください。", csv: false, reason: "no_tool_call", lang: 1, states: states(0),
    rows: [row("program")] },
  { name: "pass", prompt: pinned("simple_prompt"), csv: true, reason: null, lang: 0, states: states(9),
    rows: [
      row("program", span(18), { label: "code" }),
      row("axes", [12, 13, 14, 15, 16]),
      row("values", [5, 8, 12]),
      row("columns", [5, 8, 12, 13, 14, 15]),
      row("attach", null, { note: "no_lines" }),
    ] },
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
    (verdicts) => verdicts.some((verdict) => document.body.innerText.includes(verdict)),
    { timeout: 300000 },
    [...PASS_TEXTS, ...FAIL_TEXTS],
  );

// The embed frame of the last reply, its page-side box, and its order against status + verdict.
async function frameFacts() {
  const facts = await page.evaluate((verdicts) => {
    const reply = [...document.querySelectorAll(".chat-assistant")].at(-1);
    const frames = [...(reply?.querySelectorAll("iframe") ?? [])];
    const status = reply?.querySelector(".status-description");
    const verdict = [...(reply?.querySelectorAll("p, div") ?? [])].find(
      (node) => node.children.length === 0 && verdicts.some((text) => node.textContent?.trim().startsWith(text)),
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
  }, [...PASS_TEXTS, ...FAIL_TEXTS]);
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

// Open WebUI's fixed header and message box cover the chat's top and bottom, where a target still
// counts as in view: the chat scroller first brings the target to the viewport's middle.
async function centre(frame, target) {
  const box = await target.boundingBox();
  await (await frame.frameElement()).evaluate((node, dy) => {
    let scroller = node.parentElement;
    while (scroller && !(scroller.scrollHeight > scroller.clientHeight &&
      /auto|scroll/.test(getComputedStyle(scroller).overflowY))) scroller = scroller.parentElement;
    (scroller ?? document.scrollingElement).scrollBy(0, dy);
  }, box.y + box.height / 2 - page.viewport().height / 2);
}

// Open WebUI re-sizes the frame after each toggle and may scroll the chat after it; a click aimed
// while the target still moves lands beside it. Click once two reads 150 ms apart agree.
async function clickSteady(frame, selector) {
  const target = await frame.waitForSelector(selector);
  let last = null;
  for (let i = 0; i < 40; i += 1) {
    await centre(frame, target);
    const box = await target.boundingBox();
    if (box && last && Math.abs(box.x - last.x) < 0.5 && Math.abs(box.y - last.y) < 0.5) break;
    last = box;
    await settle(150);
  }
  await target.click();
}

// One click toggles the disclosure either way.
async function expand(frame) {
  await clickSteady(frame, "summary");
  await settle(800);
}
const collapse = expand;

// M18.4: a row, by its check's position in the check order.
const position = (want) => table.checks.indexOf(want.check) + 1;
const rowSelector = (want) => `ol > li:nth-child(${position(want)}) > details > summary`;
const readRow = (frame, want) =>
  frame.evaluate((index) => {
    const li = document.querySelectorAll("ol > li")[index];
    const details = li?.querySelector(":scope > details");
    const lines = [...(li?.querySelectorAll(".code .line") ?? [])];
    return {
      open: details?.open ?? null,
      sections: [...(li?.querySelectorAll(".more > div, .more > p") ?? [])].map((node) => node.className),
      label: li?.querySelector(".code .label")?.textContent ?? null,
      note: li?.querySelector(".lines-note")?.textContent?.trim() ?? null,
      lines: lines.length ? lines.map((line) => Number(line.querySelector(".ln")?.textContent)) : null,
      at: lines.filter((line) => line.classList.contains("at")).map((line) => Number(line.querySelector(".ln")?.textContent)),
      marks: [...(li?.querySelectorAll(".code mark") ?? [])].map((mark) => mark.textContent),
      href: li?.querySelector("a.spec")?.href ?? null,
      target: li?.querySelector("a.spec")?.target ?? null,
      inner_scroll: document.documentElement.scrollHeight - window.innerHeight,
      wrapper: Math.ceil(document.getElementById("r").getBoundingClientRect().height),
    };
  }, position(want) - 1);

function rowHolds(item, want, read) {
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  return (
    read.open === true &&
    same(read.lines, want.lines) &&
    same(read.at, want.at) &&
    same(read.marks, want.marks) &&
    read.label === (want.label ? table[want.label][item.lang] : null) &&
    read.note === (want.note ? table[want.note][item.lang] : null) &&
    read.sections.includes("what") &&
    read.sections.includes("code") === (want.lines !== null) &&
    read.sections.includes("why") === (item.states[position(want) - 1] === "fail") &&
    read.sections.includes("link") &&
    read.href === `${GUIDE[item.lang]}#check-${want.check}` &&
    read.target === "_blank"
  );
}

// L2: the opened row's link opens one NEW tab at the guide section (URL read over CDP).
// `waitForTarget` also matches targets that already exist, so only a target absent before the
// click counts, and exactly one such page must appear (reviewer-3 K5-F1).
async function followLink(frame, item) {
  const want = `${GUIDE[item.lang]}#check-${item.rows[0].check}`;
  const before = new Set(browser.targets());
  const fresh = () => browser.targets().filter((target) => !before.has(target) && target.type() === "page");
  await frame.click(`ol > li:nth-child(${position(item.rows[0])}) a.spec`);
  const target = await browser
    .waitForTarget((t) => !before.has(t) && t.type() === "page" && t.url() === want, { timeout: 30000 })
    .catch(() => null);
  await settle(500);
  const created = fresh();
  for (const extra of created) await (await extra.page().catch(() => null))?.close();
  return target !== null && created.length === 1 && created[0] === target;
}

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
      let row = null;
      if (frame) {
        const opened_rows = [];
        for (const [index, want] of item.rows.entries()) {
          await clickSteady(frame, rowSelector(want));
          await settle(800);
          const read = await readRow(frame, want);
          const opened = (await frameFacts()).facts.height;
          const link = phase === "live" && index === 0 ? await followLink(frame, item) : null;
          if (phase === "live") await page.screenshot({ path: join(outDir, `${item.name}-${want.check}-row.png`) });
          await clickSteady(frame, rowSelector(want));
          await settle(800);
          const closed = (await frameFacts()).facts.height;
          const shut = await readRow(frame, want);
          opened_rows.push({
            check: want.check, read, opened_height: opened, closed_height: closed, link,
            ok: rowHolds(item, want, read) && opened > expandedFacts.height &&
              Math.abs(opened - read.wrapper) <= 2 && read.inner_scroll <= 1 &&
              shut.open === false && Math.abs(closed - expandedFacts.height) <= 2 &&
              (phase !== "live" || index > 0 || link === true),
          });
        }
        row = { rows: opened_rows, ok: opened_rows.length === item.rows.length && opened_rows.every((r) => r.ok) };
      }
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
        row,
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
      p.collapsed_ok && p.expanded_ok && p.row?.ok === true;
    record.ok =
      phaseOk(record.live) && phaseOk(record.reload) && record.rest.embeds === 1 &&
      (item.reason === null
        ? record.rest.content === table.pass_text && record.rest.output_text === table.pass_text &&
          record.rest.pngs === 1
        : record.rest.content === FAIL_TEXTS[item.lang] && record.rest.output_text === FAIL_TEXTS[item.lang] &&
          record.rest.pngs === 0 &&
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

// L4: each expanded reply per (Open WebUI theme, OS colour scheme), the scheme emulated over CDP:
// the two matching pairs, then the two mismatches (an explicit theme the OS does not share). The
// frame follows the OS scheme (Open WebUI sets no `color-scheme`), so the embed paints its own
// surface per scheme: a matching pass must show Open WebUI's own surface behind the frame, a
// mismatch another one, and every pass the emulated scheme inside the frame (a browser that pins
// the scheme fails here rather than capturing the wrong pass). A person inspects the PNGs.
const PASSES = [
  { theme: "light", scheme: "light" },
  { theme: "dark", scheme: "dark" },
  { theme: "dark", scheme: "light" },
  { theme: "light", scheme: "dark" },
];
// sRGB hex of an element's own background through a 1×1 canvas, since Open WebUI's computed
// colours are oklch; null = transparent. Defined inside each evaluate: page + frame each need it.
// Q62: Tab from a blank spot of the expanded frame through its focusable elements (every summary,
// the opened row's link); each must match `:focus-visible` with an outline at least 2 px wide.
// The click lands beside the outer summary (`width: max-content`), so it focuses the frame and
// toggles nothing; the summary is centred first, clear of Open WebUI's fixed header.
async function focusWalk(frame, shot) {
  const outer = await frame.waitForSelector("#r > details > summary");
  await centre(frame, outer);
  await settle(300);
  const line = await outer.boundingBox();
  const box = await (await frame.frameElement()).boundingBox();
  await page.mouse.click(box.x + box.width - 8, line.y + line.height / 2);
  const steps = [];
  for (let i = 0; i < 40; i += 1) {
    await page.keyboard.press("Tab");
    const step = await frame.evaluate(() => {
      const node = document.activeElement;
      if (!node || node === document.body) return null;
      const style = getComputedStyle(node);
      return {
        tag: node.tagName.toLowerCase(),
        visible: node.matches(":focus-visible"),
        outline: style.outlineStyle,
        width: Number.parseFloat(style.outlineWidth),
      };
    });
    if (!step) break;
    steps.push(step);
    if (steps.length === 2) await page.screenshot({ path: shot });
  }
  const summaries = steps.filter((step) => step.tag === "summary").length;
  const links = steps.filter((step) => step.tag === "a").length;
  return {
    steps: steps.length,
    summaries,
    links,
    ok: summaries === table.checks.length + 1 && links === 1 &&
      steps.every((step) => step.visible && step.outline !== "none" && step.width >= 2),
  };
}
const shots = [];
const focusShots = [];
const schemes = [];
const surfaces = {};
for (const pass of PASSES) {
  await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: pass.scheme }]);
  await page.evaluate((t) => localStorage.setItem("theme", t), pass.theme);
  for (const record of results.filter((r) => r.chat_id)) {
    await page.goto(`${webuiURL}/c/${record.chat_id}`, { waitUntil: "domcontentloaded", timeout: 90000 });
    await verdictShown();
    await settle(2500);
    const { frame } = await frameFacts();
    const seen = { case: record.case, ...pass, ok: false };
    const name = `${record.case}-${pass.theme}-${pass.scheme}`;
    if (frame) {
      await expand(frame);
      const item = CASES.find((c) => c.name === record.case);
      await clickSteady(frame, rowSelector(item.rows[0]));
      await settle(800);
      seen.page = await page.evaluate(() => {
        const read = (node) => {
          const context = document.createElement("canvas").getContext("2d");
          context.fillStyle = getComputedStyle(node).backgroundColor;
          context.fillRect(0, 0, 1, 1);
          const [r, g, b, a] = context.getImageData(0, 0, 1, 1).data;
          return a === 0 ? null : `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`;
        };
        let node = [...document.querySelectorAll(".chat-assistant")].at(-1)?.querySelector("iframe");
        while (node && read(node) === null) node = node.parentElement;
        return {
          theme: document.documentElement.classList.contains("dark") ? "dark" : "light",
          surface: node ? read(node) : null,
        };
      });
      seen.frame = await frame.evaluate(() => {
        const read = (node) => {
          const context = document.createElement("canvas").getContext("2d");
          context.fillStyle = getComputedStyle(node).backgroundColor;
          context.fillRect(0, 0, 1, 1);
          const [r, g, b, a] = context.getImageData(0, 0, 1, 1).data;
          return a === 0 ? null : `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`;
        };
        return { dark: matchMedia("(prefers-color-scheme: dark)").matches, surface: read(document.body) };
      });
      const same = seen.page.surface !== null && seen.page.surface === seen.frame.surface;
      seen.ok = seen.frame.dark === (pass.scheme === "dark") && seen.page.theme === pass.theme &&
        same === (pass.theme === pass.scheme);
      if (pass.theme === pass.scheme) surfaces[pass.theme] = seen.page.surface;
    }
    await page.evaluate(() => [...document.querySelectorAll(".chat-assistant")].at(-1)?.querySelector("iframe")?.scrollIntoView({ block: "center" }));
    await settle(500);
    const path = join(outDir, `${name}.png`);
    await page.screenshot({ path });
    shots.push(path);
    if (frame && pass.theme === pass.scheme) {
      const shot = join(outDir, `${name}-focus.png`);
      seen.focus = await focusWalk(frame, shot);
      focusShots.push(shot);
    }
    schemes.push(seen);
    console.log(JSON.stringify(seen));
  }
}
await page.emulateMediaFeatures([]);
await page.evaluate(() => localStorage.setItem("theme", "system"));
const schemesOk = schemes.length === PASSES.length * results.filter((r) => r.chat_id).length &&
  schemes.every((seen) => seen.ok && (seen.theme !== seen.scheme || seen.focus?.ok === true));
const ok = results.length > 0 && results.length === CASES.length && results.every((r) => r.ok) &&
  (!refused || narrow.ok) && schemesOk;
console.log(JSON.stringify({ shots, focusShots, surfaces, ok }));
writeFileSync(
  join(outDir, "m16u1_checks.json"),
  `${JSON.stringify({ ok, results, narrow, shots, focus_shots: focusShots, schemes, surfaces }, null, 2)}\n`,
);
await browser.disconnect();
process.exitCode = ok ? 0 : 1;
