// Plumbing for metals-check.mjs: the review server, headless Chrome over the DevTools protocol, real key presses, and
// the whole-figure text match the withholding checks use. Nothing here checks the page itself.
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { createServer } from "node:net";
import { join, relative } from "node:path";

export const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
export const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
export const lower = (value) => value.toLowerCase().replace(/\s+/g, " ");
export const given = (value) => typeof value === "string" && value.trim() !== "";
export const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => { const { port } = server.address(); server.close(() => done(port)); });
});
export const chromePath = [process.env.SECOND_ORDER_CHROME, "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
  "/usr/bin/chromium-browser"].find((path) => path && existsSync(path));

/** Every file under a folder with its sha256 and modification time, to prove a run changed nothing. */
export const tree = (folder) => {
  const found = {};
  if (!existsSync(folder)) return found;
  const walk = (path) => {
    for (const name of readdirSync(path)) {
      const full = join(path, name);
      if (statSync(full).isDirectory()) walk(full);
      else found[relative(folder, full).replaceAll("\\", "/")] =
        `${createHash("sha256").update(readFileSync(full)).digest("hex")}:${statSync(full).mtimeMs}`;
    }
  };
  walk(folder);
  return found;
};
/** Every string inside a reply, however deep. */
export const strings = (value, out = []) => {
  if (typeof value === "string") out.push(value);
  else if (Array.isArray(value)) value.forEach((item) => strings(item, out));
  else if (value && typeof value === "object") Object.values(value).forEach((item) => strings(item, out));
  return out;
};

// Affirmative recommendation and price-direction phrasings, never bare stems (thesis-check.mjs): the page's lines that
// name what they deny ("No price view, projection or advice") must pass.
const AFFIRMATIVE = [
  /\b(?:we|i) (?:recommend|suggest|advise)\b/, /(?<!not a )\brecommendation to (?:buy|sell|hold)\b/,
  /\b(?:should|must|time to|consider) (?:buy|sell)(?:ing)?\b/, /\b(?:buy|sell|hold) (?:signal|rating|now|call)\b/,
  /\bstrong (?:buy|sell)\b/, /\bgo (?:long|short)\b/, /\b(?:over|under)weight\b/, /\b(?:out|under)perform/,
  /\bprice target (?:of|is)\b/, /\btarget price\b/,
  /\bprices? (?:will|would|should|could|may|is likely to|are likely to|is expected to|are expected to) (?:rise|fall|climb|drop|increase|decrease|go up|go down)\b/,
  /\bprices? (?:rises?|rising|falls?|falling|climbs?|climbing|drops?|dropping|rall(?:y|ies)|surges?|slumps?|spikes?)\b/,
  /\b(?:higher|lower|rising|falling) (?:copper )?prices?\b/, /\b(?:upside|downside)\b/, /\b(?:bullish|bearish)\b/,
  /\b(?:upward|downward|price) pressure\b/,
  /\b(?:there is|there will be|faces?|facing) a (?:copper )?(?:shortage|deficit)\b/, /\bshortage of \d/,
  /\bwill (?:close|be built)\b/, /\bnot at risk of clos/,
];
export const affirmative = (text) => AFFIRMATIVE.filter((pattern) => pattern.test(lower(text))).map(String);
/** The page's own words: its text with every multi-word string of the replies cut out. */
export const chromeOf = (pageText, ...replies) => {
  let rest = lower(pageText);
  const all = [...new Set(replies.flatMap((reply) => strings(reply)))].filter((value) => /\s/.test(value.trim()))
    .map(lower).sort((a, b) => b.length - a.length);
  for (const value of all) rest = rest.split(value).join(" ¦ ");
  return rest;
};

// A string occurs in a text only whole: "5" is not in "2025" or "0.5", "300" not in "2,300", "W" not in "Where", and
// "2,000" not in ">2,000,000"; "W" in “W”, "74.2" in "74.2%", "x,74.2" and "Congo,74.2", and "Congo (Kinshasa)" in
// "Congo (Kinshasa)74.2%" are. Only an end that is a letter or digit needs a boundary, and a comma or period before
// a string hides it only when a digit stands before that comma or period (a grouped or decimal number).
const escapeRe = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
export const figure = (value) => new RegExp((/^[\p{L}\p{N}]/u.test(value) ? "(?<![\\p{L}\\p{N}])(?<!\\p{N}[.,])" : "") +
  escapeRe(value) + (/[\p{L}\p{N}]$/u.test(value) ? "(?![\\p{L}\\p{N}]|[.,]\\p{N})" : ""), "u");
export const occurs = (value, text) => figure(value).test(text);
/** The script that collects everything the metals page holds now: every text node (hidden or collapsed ones too) and
 * every attribute value but the layout ones, leaving out the page's own words that are checked apart: the picker's count
 * and status, the notes, the ranking line, the how-to (which name "Other countries" and "less than 1 year", as a file or
 * reply can) and the new parts' fixed words: link labels ("Hypothesis — …", whose dash a file can print too), the About
 * notes, the selects (their options are the IEA's scenarios and years), each chain's link count and `skip` (the new
 * folds' teasers, checked apart). The IEA years the page prints as its own labels are left out where they stand, and
 * only there: the year headings (th[data-year]), [data-year-label] spans, the year-keyed attributes (data-year,
 * data-uses, data-demand, data-energy-share, data-label-year) and the year a scroll frame's name ends with
 * ([data-label-year]); the same year printed anywhere else is scanned. `root` selects the page's own element (another
 * page's check passes its own; none of the metals page's own selectors match there). */
export const shownScript = (skip, root = "article[data-metals]") => `(() => { const page = document.querySelector(${
  JSON.stringify(root)}).cloneNode(true);
  page.querySelectorAll("[data-count], #mt-picker-status, dl[data-notes], [data-ranking-scope], [data-howto], .mt-badge, " +
    ".mt-aside-text, select, .mt-chain-count, ${skip}, [data-concentration-scope], [data-concentration-howto], " +
    "th[data-year], [data-year-label]").forEach((e) => e.remove());
  page.querySelectorAll("[data-label-year]").forEach((e) => e.setAttribute("aria-label",
    e.getAttribute("aria-label").replace(new RegExp(", " + e.dataset.labelYear + "$"), "")));
  const own = ["colspan", "rowspan", "tabindex", "data-year", "data-uses", "data-demand", "data-energy-share", "data-label-year"];
  const texts = [], walk = document.createTreeWalker(page, NodeFilter.SHOW_TEXT);
  while (walk.nextNode()) texts.push(walk.currentNode.nodeValue);
  return { text: texts.join(" \\n "), attributes: [page, ...page.querySelectorAll("*")].flatMap((e) => [...e.attributes]
    .filter((a) => !own.includes(a.name)).map((a) => ({ name: a.name, value: a.value }))) }; })()`;
/** How often `value` occurs in what shownScript collected (text and attribute values). */
export const occurrences = (value, shown) => (shown.text.match(new RegExp(figure(value).source, "gu")) ?? []).length
  + shown.attributes.filter((a) => occurs(value, a.value)).length;
/** The strings of `values` that occur in the shown text or in any shown attribute value. */
export const leaks = (shown, values) => [...new Set(values)]
  .filter((value) => occurs(value, shown.text) || shown.attributes.some((a) => occurs(value, a.value)));
/** Where a leaked value stands: a little of the text around it, or the attribute that holds it. */
export const where = (value, shown) => {
  const at = shown.text.search(figure(value));
  if (at >= 0) return `${value} in text "${shown.text.slice(Math.max(0, at - 40), at + 40).replace(/\s+/g, " ")}"`;
  const attribute = shown.attributes.find((a) => occurs(value, a.value));
  return `${value} in ${attribute?.name}="${attribute?.value}"`;
};

/** The review server on `port`, serving `served` with the given arguments; resolves once /api/metals answers. */
export async function startServer({ python, repo, served, port, args, children }) {
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    ...args], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  for (let i = 0; i < 300; i++) {
    try { if ((await fetch(`http://127.0.0.1:${port}/api/metals`)).ok) return server; } catch { /* starting */ }
    await sleep(200);
  }
  throw new Error("The review server did not start.");
}

const KEYS = {
  Tab: { key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 },
  Space: { key: " ", code: "Space", windowsVirtualKeyCode: 32, text: " " },
  Enter: { key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, text: "\r" },
  Escape: { key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 },
  Backspace: { key: "Backspace", code: "Backspace", windowsVirtualKeyCode: 8 },
  ArrowDown: { key: "ArrowDown", code: "ArrowDown", windowsVirtualKeyCode: 40 },
  ArrowUp: { key: "ArrowUp", code: "ArrowUp", windowsVirtualKeyCode: 38 },
  ArrowRight: { key: "ArrowRight", code: "ArrowRight", windowsVirtualKeyCode: 39 },
  ArrowLeft: { key: "ArrowLeft", code: "ArrowLeft", windowsVirtualKeyCode: 37 },
  Home: { key: "Home", code: "Home", windowsVirtualKeyCode: 36 },
  End: { key: "End", code: "End", windowsVirtualKeyCode: 35 },
};

/** Headless Chrome with one page, driven over the DevTools protocol; records requests, page errors and log errors. */
export async function startChrome({ profile, children }) {
  const chrome = spawn(chromePath, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
    "--no-first-run", "--disable-gpu", "--hide-scrollbars", "about:blank"], { stdio: "ignore" });
  children.push(chrome);
  let socketUrl;
  for (let i = 0; i < 150 && !socketUrl; i++) {
    try {
      const devtools = readFileSync(join(profile, "DevToolsActivePort"), "utf8").split("\n")[0].trim();
      socketUrl = (await (await fetch(`http://127.0.0.1:${devtools}/json/list`)).json())
        .find((target) => target.type === "page")?.webSocketDebuggerUrl;
    } catch { /* starting */ }
    if (!socketUrl) await sleep(200);
  }
  if (!socketUrl) throw new Error("Chrome's DevTools endpoint did not start.");
  const ws = new WebSocket(socketUrl);
  await new Promise((done) => ws.addEventListener("open", done, { once: true }));
  let counter = 0;
  const pending = new Map();
  const requests = [];
  const errors = [];
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else if (message.method === "Network.requestWillBeSent") {
      requests.push({ method: message.params.request.method, url: message.params.request.url });
    } else if (message.method === "Runtime.exceptionThrown") {
      const details = message.params.exceptionDetails;
      errors.push({ text: details.exception?.description ?? details.text, url: details.url ?? "" });
    } else if (message.method === "Log.entryAdded" && message.params.entry.level === "error") {
      errors.push({ text: message.params.entry.text, url: message.params.entry.url ?? "" });
    }
  });
  /** One DevTools command; one that does not answer within two minutes fails the run by name instead of hanging. */
  const send = (method, params = {}) => new Promise((done, fail) => {
    const id = ++counter;
    const timer = setTimeout(() => { pending.delete(id); fail(new Error(`${method} did not answer in 120 s`)); }, 120000);
    pending.set(id, (message) => {
      clearTimeout(timer);
      if (message.error) fail(new Error(message.error.message)); else done(message.result);
    });
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) =>
    (await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })).result.value;
  const waitFor = async (expression, timeout = 30000) => {
    for (const start = Date.now(); Date.now() - start < timeout; await sleep(80)) {
      if (await evaluate(expression)) return true;
    }
    return false;
  };
  /** A real key press through Chrome's input pipeline, not a synthetic DOM event. */
  const press = async (name) => {
    const { text, ...key } = KEYS[name];
    await send("Input.dispatchKeyEvent", { type: "keyDown", ...key, ...(text ? { text } : {}) });
    await send("Input.dispatchKeyEvent", { type: "keyUp", ...key });
    await sleep(70);
  };
  const type = async (text) => { await send("Input.insertText", { text }); await sleep(120); };
  /** The focused element: what it is, and whether it shows its focus (:focus-visible and a drawn outline). */
  const focused = () => evaluate(`(() => { const e = document.activeElement; if (!e || e === document.body) return null;
    const style = getComputedStyle(e); return { tag: e.tagName.toLowerCase(), value: e.value ?? "", id: e.id,
    type: e.type ?? "", role: e.getAttribute("role") ?? "", text: (e.innerText ?? "").trim().slice(0, 60),
    tab: e.dataset.tab ?? "", picker: e.matches(".mt-picker-button"), search: e.matches(".mt-picker-find input"),
    box: e.matches('.mt-picker-list input[type="checkbox"]'), summary: e.tagName === "SUMMARY",
    visible: e.matches(":focus-visible") && style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0 }; })()`);
  /** Press Tab until `test` holds for the focused element; the presses it took, or -1. */
  const tabTo = async (test, limit = 150) => {
    for (let count = 1; count <= limit; count++) {
      await press("Tab");
      const now = await focused();
      if (now && test(now)) return count;
    }
    return -1;
  };
  /** Every other DevTools event (request headers, held requests, dialogs) goes to `listener` as {method, params}. */
  const on = (listener) => ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.method) listener(message);
  });
  return { send, evaluate, waitFor, press, type, focused, tabTo, on, requests, errors, close: () => ws.close() };
}

// The values a part of the reply shows, and the words its file holds beside them (for the withholding checks).
export const usgsValues = (part) => part.chapters.flatMap((chapter) => [
  ...chapter.series.flatMap((series) => [series.world, series.other, ...series.countries].filter(Boolean)
    .flatMap((cell) => [cell.value, cell.share?.shown]).concat([series.leader.shown, series.top3.shown])),
  ...chapter.years_of_reserves.map((years) => years.shown),
  ...chapter.imports.flatMap((group) => group.rows.map((row) => row.value)),
  ...chapter.reliance.map((row) => row.value),
]).filter(given);
export const ieaValues = (part) => part.minerals.flatMap((mineral) => [
  ...mineral.demand.rows.flatMap((row) => Object.values(row.values)), ...Object.values(mineral.demand.energy_share),
  ...mineral.supply.flatMap((block) => [
    ...[...block.countries, ...(block.rest ? [block.rest] : [])]
      .flatMap((line) => [...Object.values(line.values), ...Object.values(line.shares)]),
    ...Object.values(block.total), ...Object.values(block.top3_published)]),
]).filter(given);
export const usgsLabels = (part) => part.chapters.flatMap((chapter) => [
  ...chapter.data_notes,
  ...chapter.series.flatMap((series) => [series.detail, series.no_shares, series.unit_issue, series.leader.reason,
    series.top3.reason, ...series.leader.countries, ...series.top3.countries,
    ...[series.world, series.other, ...series.countries].filter(Boolean)
      .flatMap((cell) => [cell.country, cell.notes, cell.share?.reason])]),
  ...chapter.years_of_reserves.map((years) => years.reason),
  ...chapter.imports.flatMap((group) => [group.detail, ...group.rows.map((row) => row.country)]),
  ...chapter.reliance.map((row) => row.detail),
]).filter(given);
export const ieaLabels = (part) => part.minerals.flatMap((mineral) => [
  mineral.scope_note, ...mineral.notes.demand, ...mineral.notes.supply, ...mineral.demand.rows.map((row) => row.label),
  ...mineral.supply.flatMap((block) => [block.stage, block.total_label, ...block.countries.map((line) => line.country)]),
]).filter(given);

// Stage 2 parts. The figures the risk part (concentration, supply chain, US imports) and the uses part (IEA energy
// technologies) show, and the words only their files hold, so the whole-page leak scan covers them too. A figure is
// also listed as the page writes it (grouped digits).
const grouped = (digits) => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
export const riskValues = (part) => part.chapters.flatMap((chapter) => [
  ...Object.values(chapter.series).flatMap((s) => [s.named_share, s.hhi_low, s.hhi_high,
    s.hhi_low && grouped(s.hhi_low), s.hhi_high && grouped(s.hhi_high)]),
  ...(chapter.alternatives ?? []).flatMap((row) => [row.reserves, row.production]),
  ...(chapter.reserves_only ?? []).map((row) => row.reserves),
  chapter.us.reliance?.value, ...chapter.us.secondary.map((row) => row.value),
  ...chapter.us.imports.flatMap((group) => [group.leader?.value, group.top3, group.named_share, group.hhi_low,
    group.hhi_high, group.hhi_low && grouped(group.hhi_low), group.hhi_high && grouped(group.hhi_high)]),
]).filter(given);
export const riskLabels = (part) => part.chapters.flatMap((chapter) => [
  ...Object.values(chapter.series).map((s) => s.reason),
  ...(chapter.alternatives ?? []).map((row) => row.country), ...(chapter.reserves_only ?? []).map((row) => row.country),
  chapter.us.reliance?.detail, ...chapter.us.secondary.flatMap((row) => [row.detail, row.unit]),
  ...chapter.us.imports.flatMap((group) => [group.detail, group.years, group.leader?.country, group.reason]),
]).filter(given);
export const usesValues = (part) => part.entries.flatMap((entry) => [
  ...Object.values(entry.total),
  ...(entry.technologies ?? []).flatMap((tech) => [...Object.values(tech.values), tech.share_2025]),
]).filter(given);
export const usesLabels = (part) => part.entries.flatMap((entry) => [
  entry.name, entry.scope_note, ...(entry.technologies ?? []).map((tech) => tech.label),
]).filter(given);

/** The accessibility node (role, name, ignored) of every control inside the metals page, one DevTools call each. */
export async function controlNames(send) {
  const { root } = await send("DOM.getDocument", { depth: 0 });
  const { nodeIds } = await send("DOM.querySelectorAll", { nodeId: root.nodeId,
    selector: "article[data-metals] :is(a[href], button, input, select, textarea, summary, [tabindex])" });
  const controls = [];
  for (const nodeId of nodeIds) {
    const { nodes } = await send("Accessibility.getPartialAXTree", { nodeId, fetchRelatives: false });
    const node = nodes[0] ?? {};
    controls.push({ role: String(node.role?.value ?? ""), name: String(node.name?.value ?? "").trim(), ignored: node.ignored !== false });
  }
  return controls;
}
