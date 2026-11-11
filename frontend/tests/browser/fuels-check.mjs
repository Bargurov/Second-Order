// Browser check of the fuels page (/fuels), against tests/review_browser_server.py serving a new, empty folder with
// --fuels synthetic (a SYNTHETIC EIA-shaped snapshot and a SYNTHETIC note; see tests/fuels_fakes.py). No real price,
// no data/fuels folder and no EIA request is involved. It checks the nav link, the hero (amounts, stamp, dates, note
// meta, barrel data attributes), reduced motion, the four tiles and the coverage strip with their EIA credits, the
// method block (each series' credit and its four dates), a later negative snapshot (then/now sentence, the
// no-newer-observation sentence, negative crack), a missing snapshot, and, across the loads, that the served
// root is unchanged, only local requests are made, nothing errors, 375 px does not scroll sideways and no banned
// phrase appears. Stage 2 adds the section nav and the synthetic mark, Situation Now (summary, windows, levels with
// P for published prices and C for computed values, split bars, what it can show), Drivers, Transmission and the
// Method's legend and sources on the positive snapshot, and, after the 375 px checks on the negative snapshot, a stale
// snapshot, then a snapshot with one refused series and a FRED-era snapshot whose prices are withheld, and last a
// fuels-note-0.2 analysis: current (closed, then open below the summary and the barrel, by click and by Enter, at
// 1280 and 375 px), earlier after a refresh, unbound without its snapshot. Then the two edge cases: a crack change
// under a cent beside the offsetting label (shown with its direction and <0.01, with the key), diesel a year behind (its price
// kept and marked, the barrel, crack and Situation Now withheld, the page not refused) and WTI a year behind (marked in
// its coverage entry, the barrel computed). SECOND_ORDER_FUELS_SCREENS=<folder> also saves viewport screenshots of the
// page top, the hero and the Stage 2 sections (not a check).
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const python = process.env.SECOND_ORDER_PYTHON ?? "python";
const screens = process.env.SECOND_ORDER_FUELS_SCREENS ? resolve(process.env.SECOND_ORDER_FUELS_SCREENS) : undefined;
const chromePath = [process.env.SECOND_ORDER_CHROME, "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
  "/usr/bin/chromium-browser"].find((path) => path && existsSync(path));
if (!chromePath) throw new Error("Chrome was not found; set SECOND_ORDER_CHROME to its executable.");
if (!existsSync(join(repo, "frontend/dist/index.html"))) throw new Error("Build the client first: npm run build");

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => { const { port } = server.address(); server.close(() => done(port)); });
});
const root = mkdtempSync(join(tmpdir(), "second-order-fuels-check-"));
const served = join(root, "served");
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const tree = (folder) => {
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
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const lower = (value) => value.toLowerCase().replace(/\s+/g, " ");
// Affirmative recommendation and price-direction phrasings (the copper-tools list), plus the word "today".
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
  /\btoday\b/,
];
const affirmative = (text) => AFFIRMATIVE.filter((pattern) => pattern.test(lower(text))).map(String);
const CREDIT = "Spot prices from the U.S. Energy Information Administration (EIA), retrieved through its open data API. "
  + "EIA does not endorse this page.";
const TERMS = ["https://www.eia.gov/about/copyrights_reuse.php", "https://www.eia.gov/opendata/terms-of-service.php",
  "https://www.eia.gov/dnav/pet/TblDefs/pet_pri_spt_tbldef2.asp", "https://www.eia.gov/dnav/ng/TblDefs/ng_pri_fut_tbldef2.asp"];
const EIA = "Source: U.S. Energy Information Administration";
const VENDOR = "Data: Refinitiv, an LSEG business, as EIA states.";
const MINUS = "\u2212";
const SERIES_IDS = ["RBRTE", "RWTC", "EER_EPMRU_PF4_Y35NY_DPG", "EER_EPD2DXL0_PF4_Y35NY_DPG", "RNGWHHD"];

async function startServer(port) {
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    "--fuels", "synthetic"], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  for (let i = 0; i < 300; i++) {
    try { if ((await fetch(`http://127.0.0.1:${port}/api/fuels`)).ok) return server; } catch { /* starting */ }
    await sleep(200);
  }
  throw new Error("The review server did not start.");
}

try {
  check("the phrasing scan flags affirmative phrasings and the word today, and passes the lines that name what they deny",
    affirmative("The crack is a gross margin; it is not any refinery's profit. No price view.").length === 0 &&
    ["PRICES WILL RISE", "the upside case", "time to sell", "Brent today"].every((phrase) => affirmative(phrase).length > 0));

  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  await startServer(port);
  const snapshots = join(served, "fuels-snapshots");

  const chrome = spawn(chromePath, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
    "--no-first-run", "--disable-gpu", "about:blank"], { stdio: "ignore" });
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
  const send = (method, params = {}) => new Promise((done, fail) => {
    const id = ++counter;
    pending.set(id, (message) => message.error ? fail(new Error(message.error.message)) : done(message.result));
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
  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("Log.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  const q = JSON.stringify;
  const navigate = (path) => send("Page.navigate", { url: `${base}${path}` });
  const text = (selector) => evaluate(`document.querySelector(${q(selector)})?.textContent ?? ""`);
  const pageReady = `!!document.querySelector('article.fu-page .fu-barrel-card svg[role="img"], article.fu-page .fu-problem')`;
  const texts = [];  // The text of every load of the page, for the banned-phrase scan.
  const keepText = async () => texts.push(await evaluate(`document.querySelector("article.fu-page")?.textContent ?? ""`));
  const load = async (path = "/fuels") => {
    await navigate(path);
    const ready = await waitFor(pageReady);
    await sleep(250);
    await keepText();
    return ready;
  };
  const svg = (name) => evaluate(`document.querySelector('.fu-barrel-card svg[role="img"]')?.getAttribute(${q(name)})`);
  /** Viewport screenshots of the hero at 1280x900 and at 375 px, each under a watchdog; not a pass/fail check. */
  const capture = async (state) => {
    if (!screens) return;
    mkdirSync(screens, { recursive: true });
    for (const [label, width, height, mobile] of [["1280", 1280, 900, false], ["375", 375, 812, true]]) {
      try {
        await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile });
        await sleep(200);
        await evaluate(`(document.querySelector("#barrel") ?? document.body).scrollIntoView(); true`);
        await sleep(3200);  // The load animation runs about 2.6 s.
        const shot = await Promise.race([send("Page.captureScreenshot", { format: "png" }),
          sleep(20000).then(() => { throw new Error("screenshot watchdog"); })]);
        writeFileSync(join(screens, `fuels-hero-${state}-${label}.png`), Buffer.from(shot.data, "base64"));
      } catch (error) { console.log(`NOTE  no screenshot for ${state} at ${label}: ${error.message}`); }
    }
    await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  };
  /** Viewport screenshots of one Stage 2 section at 1280x900 and at 375 px, each under a watchdog; not a check. */
  const captureSection = async (name, selector, prepare = "") => {
    if (!screens) return;
    mkdirSync(screens, { recursive: true });
    for (const [label, width, height, mobile] of [["1280", 1280, 900, false], ["375", 375, 812, true]]) {
      try {
        await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile });
        await sleep(200);
        await evaluate(`${prepare}; document.querySelector(${q(selector)}).scrollIntoView(); true`);
        await sleep(600);
        const shot = await Promise.race([send("Page.captureScreenshot", { format: "png" }),
          sleep(20000).then(() => { throw new Error("screenshot watchdog"); })]);
        writeFileSync(join(screens, `fuels-${name}-${label}.png`), Buffer.from(shot.data, "base64"));
      } catch (error) { console.log(`NOTE  no screenshot for ${name} at ${label}: ${error.message}`); }
    }
    await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  };
  const beforeLoads = tree(served);

  // 1. The top bar.
  await navigate("/library");
  await waitFor(`!!document.querySelector('.site-nav a[href="/fuels"]')`);
  const nav = await evaluate(`[...document.querySelectorAll(".site-nav a")].map((a) => a.textContent.trim())`);
  check("the top bar has a Fuels link between Market context and Library",
    nav.indexOf("Fuels") > 0 && nav[nav.indexOf("Fuels") - 1] === "Market context" && nav[nav.indexOf("Fuels") + 1] === "Library",
    nav.join());
  await evaluate(`document.querySelector('.site-nav a[href="/fuels"]').click()`);
  const opened = await waitFor(pageReady);
  await sleep(250);
  await keepText();
  check("clicking it opens /fuels with aria-current page",
    opened && await evaluate(`location.pathname`) === "/fuels" &&
    await evaluate(`document.querySelector('.site-nav a[href="/fuels"]').getAttribute("aria-current")`) === "page");

  // 2. The hero on the positive snapshot.
  const hero = await text("#barrel");
  const aria = await svg("aria-label");
  check("the hero text names $112.00, $32.00 and $80.00", ["$112.00", "$32.00", "$80.00"].every((v) => hero.includes(v)), hero.slice(0, 300));
  check("the barrel's aria-label names the same three amounts", ["$112.00", "$32.00", "$80.00"].every((v) => aria?.includes(v)), String(aria));
  check("the stamp reads Observed 3 Nov 2026", (await text("#barrel .stamp")).includes("Observed 3 Nov 2026"), await text("#barrel .stamp"));
  check("the hero says EIA gives no publication date, and when the prices were retrieved",
    (await text("#barrel .fu-dates")).includes("publication date not given by EIA · retrieved 6 Nov 2026"),
    await text("#barrel .fu-dates"));
  const meta = await text(".fu-note-meta");
  check("the note's meta line and AI-drafted are shown", /Written/.test(meta) && /covers data through/.test(meta) &&
    (await text(".fu-review")).includes("AI-drafted"), `${meta} | ${await text(".fu-review")}`);
  const fillTop = Number(await svg("data-fill-top")), lineY = Number(await svg("data-line-y"));
  check("the crack band is drawn and the Brent line sits below the basket line",
    await svg("data-band") === "yes" && await svg("data-drawable") === "true" && lineY > fillTop, `${fillTop} ${lineY}`);
  await capture("positive");

  // 3. Reduced motion.
  const animation = () => evaluate(`getComputedStyle(document.querySelector(".fu-fill")).animationName`);
  const normal = await animation();
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
  await load();
  const reduced = await animation();
  check("under prefers-reduced-motion the fill's animation is none (and it animates otherwise)",
    reduced === "none" && normal !== "none", `${normal} / ${reduced}`);
  await send("Emulation.setEmulatedMedia", { features: [] });

  // 4. The tiles and the coverage strip.
  await load();
  const tiles = await evaluate(`[...document.querySelectorAll("#prices li.fu-tile")].map((li) => ({ id: li.dataset.tile,
    kind: li.querySelector(".ct-kind")?.textContent.trim(), text: li.textContent }))`);
  check("four tiles with kinds P, P, P, C", tiles.map((t) => t.kind).join() === "P,P,P,C", tiles.map((t) => t.kind).join());
  check("each P tile credits EIA and says the publication date is not given",
    tiles.filter((t) => t.kind === "P").length === 3 && tiles.filter((t) => t.kind === "P").every((t) =>
      t.text.includes(EIA) && t.text.includes("publication date not given by EIA") && !t.text.includes("FRED")));
  const coverage = await evaluate(`Object.fromEntries([...document.querySelectorAll(".fu-coverage li[data-coverage]")]
    .map((li) => [li.dataset.coverage, li.querySelector(".ct-kind")?.textContent.trim()]))`);
  check("the coverage strip shows WTI and Henry Hub as P and Europe natural gas, urea and helium as M",
    same(coverage, { wti: "P", henry_hub: "P", europe_gas: "M", urea: "M", helium: "M" }), JSON.stringify(coverage));
  const credits = await evaluate(`Object.fromEntries(["wti", "henry_hub"].map((id) => [id,
    document.querySelector(\`.fu-coverage li[data-coverage="\${id}"] .fu-coverage-credit\`)?.textContent ?? ""]))`);
  check("the WTI and Henry Hub values carry their EIA credit, and only Henry Hub names a data vendor",
    credits.wti.includes(EIA) && credits.wti.includes("[RWTC]") && !credits.wti.includes("Refinitiv") &&
    credits.henry_hub.includes(EIA) && credits.henry_hub.includes("[RNGWHHD]") && credits.henry_hub.includes(VENDOR),
    JSON.stringify(credits));

  // 5. The method.
  const method = await text("#method");
  check("method shows the EIA credit verbatim and no FRED notice",
    (await text(".fu-credit")).trim() === CREDIT && !method.includes("FRED"), await text(".fu-credit"));
  const hrefs = await evaluate(`[...document.querySelectorAll(".fu-terms a")].map((a) => a.getAttribute("href"))`);
  check("method links the four EIA terms and notes pages", same(hrefs, TERMS), hrefs.join());
  const formula = await text(".fu-formula");
  check("method shows the page label, the formula and the refresh command",
    method.includes("Personal and educational use. Not for redistribution.") &&
    formula.includes("Crack 3-2-1 =") && formula.includes("3-2-1 basket value =") &&
    method.includes("python -m second_order fuels refresh"), formula.slice(0, 200));
  await evaluate(`document.querySelector("details.fu-more").open = true`);
  await sleep(150);
  const example = await text(".fu-example");
  check("the opened details show the synthetic example labelled not market data",
    /not market data/i.test(await text(".fu-example .fu-example-label")) && example.length > 40, example.slice(0, 120));
  check("no button anywhere inside the page", await evaluate(`document.querySelectorAll("article.fu-page button").length`) === 0);
  const sourceCells = await evaluate(`Object.fromEntries(${q(SERIES_IDS)}.map((id) => [id,
    document.querySelector(\`.fu-sources-table tr[data-series="\${id}"] td\`)?.textContent ?? ""]))`);
  check("the method table credits all five series to EIA",
    SERIES_IDS.every((id) => sourceCells[id].startsWith("EIA · ") && sourceCells[id].includes(EIA) &&
      sourceCells[id].includes(`[${id}]`)),
    JSON.stringify(sourceCells).slice(0, 400));
  const headers = await evaluate(`[...document.querySelectorAll(".fu-sources-table thead th")].map((th) => th.textContent.trim())`);
  const published = await evaluate(`${q(SERIES_IDS)}.map((id) => document.querySelector(\`.fu-sources-table tr[data-series="\${id}"]\`)
    ?.children[${headers.indexOf("Published")}]?.textContent.trim())`);
  check("the method table shows observed, published and retrieved, with no FRED column and no publication date inferred",
    ["Observed", "Published", "Retrieved"].every((name) => headers.includes(name)) && !headers.includes("FRED updated") &&
    published.every((cell) => cell === "not given by EIA"), `${headers.join()} | ${published.join()}`);
  const retrievalNote = await text('#situation p.fu-sit-note[data-note="retrieval"]');
  check("Situation Now says its values come from one refresh, not from what was known on the earlier dates",
    retrievalNote.includes("retrieved 6 Nov 2026") && retrievalNote.includes("not necessarily as EIA first published them"),
    retrievalNote);

  // 8a. The served root is unchanged by the loads above.
  check("the served root is unchanged by loading the page", same(tree(served), beforeLoads));

  // 9. Stage 2 on the positive world: nav, Situation Now, Drivers, Transmission, Method.
  const chromeVersion = await evaluate(`navigator.userAgent`);
  const major = Number(/Chrome\/(\d+)/.exec(chromeVersion)?.[1] ?? 0);
  console.log(`NOTE  browser ${chromeVersion}`);
  const sectionLinks = await evaluate(`[...document.querySelectorAll("nav.fu-sections a")].map((a) => [a.getAttribute("href"), a.textContent.trim()])`);
  check("the section nav holds six links in order",
    same(sectionLinks, [["#barrel", "Barrel"], ["#prices", "Prices"], ["#situation", "Situation"], ["#drivers", "Drivers"],
      ["#transmission", "Transmission"], ["#method", "Method"]]), JSON.stringify(sectionLinks));
  const mark = await evaluate(`({ banner: document.querySelector('article.fu-page [data-synthetic="banner"]')?.textContent ?? "",
    stamp: document.querySelector('nav.fu-sections [data-synthetic="stamp"]')?.textContent ?? "",
    beforeHero: ((document.querySelector('article.fu-page [data-synthetic="banner"]')?.compareDocumentPosition(
      document.querySelector("#barrel")) ?? 0) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0 })`);
  check("the synthetic world is marked as test data: a banner above the barrel and a stamp in the sticky section nav",
    /synthetic/i.test(mark.banner) && /not market prices/i.test(mark.banner) && /synthetic/i.test(mark.stamp) &&
    mark.beforeHero, JSON.stringify(mark));
  const reached = [];
  for (const [href] of sectionLinks) {
    await evaluate(`window.scrollTo(0, 0); document.querySelector('nav.fu-sections a[href="${href}"]').click(); true`);
    reached.push(await waitFor(`location.hash === ${q(href)} && document.querySelector(${q(href)}) !== null &&
      Math.abs(document.querySelector(${q(href)}).getBoundingClientRect().top) < 200`, 3000));
  }
  check("each nav link opens its section (hash set and the section at the top)", reached.every(Boolean), reached.join());
  await evaluate(`window.scrollTo(0, 0); history.replaceState(null, "", "/fuels"); true`);

  const summary = await text("#situation p.fu-summary");
  check("Situation Now shows the summary line, with a C badge",
    summary.startsWith("Over about a week to 3 Nov 2026,") &&
    await evaluate(`!!document.querySelector('#situation p.fu-summary .ct-kind[data-kind="computed"]')`), summary);
  const prevBrent = await text('#situation tr[data-window="previous"] td[data-row="brent"] .fu-change');
  check("the previous-window row shows the Brent change +0.96", prevBrent.trim() === "+0.96", prevBrent);
  const parts = await evaluate(`Object.fromEntries(["crude", "crack", "basket"].map((part) => [part,
    document.querySelector('#situation li.fu-split[data-window="previous"] .fu-split-value[data-part="' + part + '"]')?.dataset.shown]))`);
  const cents = (value) => Math.round(Number(String(value).replace(MINUS, "-")) * 100);
  const basketCell = await evaluate(`document.querySelector('#situation tr[data-window="previous"] td[data-row="basket"]')?.dataset.shown`);
  check("the previous window's split: crude plus crack equals the basket change, and the basket cell agrees",
    parts.crude !== undefined && parts.crack !== undefined && parts.basket !== undefined &&
    cents(parts.crude) + cents(parts.crack) === cents(parts.basket) && cents(basketCell) === cents(parts.basket),
    `${JSON.stringify(parts)} basket cell ${basketCell}`);
  const splitText = await text('#situation li.fu-split[data-window="previous"] p.fu-split-values');
  check("the split's values read as text, with Brent, Crack and Basket",
    splitText.includes("Brent +$0.96") && splitText.includes("Crack") && splitText.includes("Basket"), splitText);
  await evaluate(`document.querySelector("#situation details.fu-levels").open = true; true`);
  /** Each value cell of a Situation table as [row, badge kind, badge accessible name]. */
  const badgesOf = (table) => `[...document.querySelectorAll('#situation table.${table} tbody td[data-row]')].map((td) => {
    const badge = td.querySelector(".ct-kind");
    return [td.dataset.row, badge?.dataset.kind ?? "", badge?.getAttribute("aria-label") ?? ""]; })`;
  const levels = await evaluate(`({ open: document.querySelector("#situation details.fu-levels")?.open ?? false,
    rows: [...document.querySelectorAll("#situation table.fu-levels-table tbody tr")].map((tr) => tr.dataset.window),
    computed: [...document.querySelectorAll('#situation table.fu-windows tr[data-state="computed"]')].map((tr) => tr.dataset.window),
    brent: document.querySelector('#situation table.fu-levels-table tr[data-window="previous"] td[data-row="brent"] .fu-level')?.textContent ?? "",
    cells: ${badgesOf("fu-levels-table")} })`);
  check("the levels at both dates open as text: previous Brent 79.04 \u2192 80.00",
    levels.open && same(levels.rows, levels.computed) && levels.brent === "79.04 \u2192 80.00", JSON.stringify(levels));
  const publishedRow = (row) => ["brent", "gasoline", "diesel"].includes(row);
  check("the levels of Brent, gasoline and diesel are P (published), the basket's and crack's C, and each badge's name says so",
    levels.cells.length === 5 * levels.computed.length && levels.cells.every(([row, kind, name]) => (publishedRow(row)
      ? kind === "published" && name.startsWith("Published by EIA")
      : kind === "computed" && name.startsWith("Computed"))), JSON.stringify(levels.cells));
  const changes = await evaluate(badgesOf("fu-windows"));
  check("every change in the windows table is C (computed), named Computed from its two levels",
    changes.length === 5 * levels.computed.length &&
    changes.every(([, kind, name]) => kind === "computed" && name.startsWith("Computed from ")), JSON.stringify(changes));
  await evaluate(`document.querySelector("#situation details.fu-levels").open = false; true`);
  const canBadges = await evaluate(`[...document.querySelectorAll("#situation details.fu-can ul.fu-can-say > li")]
    .map((li) => li.querySelector('.ct-kind[data-kind="explanation"]') ? "E" : "-").join("")`);
  check("in What it shows, only the line that points to the Market Drivers carries an E badge", canBadges === "--E", canBadges);
  const cBadges = await evaluate(`document.querySelectorAll('#situation .ct-kind[data-kind="computed"]').length`);
  check("C badges are present in Situation Now", cBadges >= 10, String(cBadges));
  const withheld = await evaluate(`({ state: document.querySelector("#situation").dataset.state,
    problem: document.querySelectorAll("#situation .fu-sit-problem").length,
    unavailableWithNumbers: [...document.querySelectorAll('#situation tr[data-state="unavailable"]')]
      .filter((tr) => tr.querySelector("td[data-row]")).length })`);
  check("on the positive snapshot Situation Now is computed, with no problem panel and no unavailable row holding values",
    withheld.state === "computed" && withheld.problem === 0 && withheld.unavailableWithNumbers === 0, JSON.stringify(withheld));

  const drivers = await evaluate(`[...document.querySelectorAll("#drivers li.fu-mech")].map((li) => ({
    acts: li.querySelector("p.fu-acts")?.textContent ?? "",
    sources: li.querySelectorAll("details.fu-mech-more ul.fu-src-list li").length,
    none: li.querySelector("details.fu-mech-more p.fu-no-source")?.textContent ?? "" }))`);
  check("Drivers: eight rows, each with Acts mainly on", drivers.length === 8 && drivers.every((d) => d.acts.includes("Acts mainly on")),
    JSON.stringify(drivers.map((d) => d.acts)));
  check("every driver shows its sources or No source attached yet",
    drivers.every((d) => d.sources > 0 || d.none.includes("No source attached yet")), JSON.stringify(drivers));
  await evaluate(`document.querySelector("#drivers li.fu-mech details.fu-mech-more").open = true`);
  await sleep(100);
  check("opening a driver row shows its sources", await evaluate(`(() => { const d = document.querySelector("#drivers li.fu-mech details.fu-mech-more");
    return d.open && (d.querySelectorAll("ul.fu-src-list li").length > 0 || /No source attached yet/.test(d.textContent)); })()`));
  check("the events box text is present", (await text("#drivers aside.fu-events p.fu-events-text")).trim().length > 10,
    await text("#drivers aside.fu-events"));
  check("E badges are present in Drivers and Transmission",
    await evaluate(`document.querySelectorAll('#drivers .ct-kind[data-kind="explanation"]').length`) >= 8 &&
    await evaluate(`document.querySelectorAll('#transmission .ct-kind[data-kind="explanation"]').length`) >= 7);

  const cards = await evaluate(`[...document.querySelectorAll('#transmission details.fu-sector[name="fu-sector"]')]
    .map((d) => d.querySelectorAll("ol.fu-chain > li").length)`);
  check("Transmission: seven cards, each chain with at least three steps", cards.length === 7 && cards.every((n) => n >= 3), cards.join());
  if (major >= 120) {
    const exclusive = await evaluate(`(async () => {
      const [first, second] = document.querySelectorAll('#transmission details.fu-sector[name="fu-sector"]');
      first.open = true; await new Promise((r) => setTimeout(r, 150));
      const firstOpen = first.open;
      second.open = true; await new Promise((r) => setTimeout(r, 150));
      return { firstOpen, firstNow: first.open, secondNow: second.open,
        openCount: document.querySelectorAll('#transmission details.fu-sector[open]').length }; })()`);
    check("opening one transmission card closes the previous one (shared name)",
      exclusive.firstOpen && !exclusive.firstNow && exclusive.secondNow && exclusive.openCount === 1, JSON.stringify(exclusive));
  } else {
    console.log(`NOTE  Chrome ${major} is older than 120: details[name] exclusivity was NOT checked`);
    check("Chrome supports details[name] exclusivity (needs 120+)", false, chromeVersion);
  }

  const legendKinds = await evaluate(`[...document.querySelectorAll("#method p.ct-legend .ct-kind")].map((k) => k.textContent.trim()).join("")`);
  check("the method legend lists P, C, E, S, A and M", ["P", "C", "E", "S", "A", "M"].every((k) => legendKinds.includes(k)), legendKinds);
  const mechSources = await evaluate(`document.querySelectorAll("#method ul.fu-mech-sources > li").length`);
  const anySources = drivers.some((d) => d.sources > 0);
  check("the synthetic content gives at least one driver its sources", anySources, JSON.stringify(drivers.map((d) => d.sources)));
  check("the mechanism source list is non-empty when any driver has sources", !anySources || mechSources > 0, String(mechSources));

  await captureSection("top", "article.fu-page");
  await captureSection("situation", "#situation", `document.querySelector("#situation details.fu-levels").open = true`);
  await captureSection("situation-can", "#situation details.fu-can",
    `document.querySelector("#situation details.fu-levels").open = false;
    document.querySelector("#situation details.fu-can").open = true`);
  await captureSection("drivers-open", "#drivers",
    `document.querySelector("#drivers li.fu-mech details.fu-mech-more").open = true`);
  await captureSection("transmission-open", "#transmission",
    `document.querySelector('#transmission details.fu-sector[name="fu-sector"]').open = true`);

  // 6. A later, negative snapshot, written by the fake's own script into the served folder.
  const written = spawn(python, [join(repo, "tests/fuels_fakes.py"), "snapshot", snapshots, "--variant", "negative",
    "--retrieved", "2026-11-06T16:00:00+00:00"], { cwd: repo, stdio: ["ignore", "ignore", "inherit"] });
  const code = await new Promise((done) => written.on("exit", done));
  check("the fake writes a later negative snapshot", code === 0, String(code));
  await load();
  check("the note says prices have been refreshed, with then and now",
    (await text(".fu-refreshed")).includes(`Prices have been refreshed since this note: Brent then $80.00, now $115.00; crack then $32.00, now ${MINUS}$3.00.`),
    await text(".fu-refreshed"));
  check("the same observation date adds that the refresh found no newer observation",
    (await text(".fu-refreshed .fu-no-newer")) === "The latest refresh found no observation newer than 3 Nov 2026.",
    await text(".fu-refreshed"));
  check("the crack label reads Crack \u2212$3.00 (negative)",
    (await text('.fu-label[data-label="crack"] .fu-label-n')).includes(`Crack ${MINUS}$3.00 (negative)`), await text('.fu-label[data-label="crack"]'));
  check("the Brent line is above the basket line and there is no band",
    await svg("data-line-above") === "true" && await svg("data-band") === "no");
  await capture("negative");

  // 7. A missing snapshot folder.
  const away = join(root, "fuels-snapshots-away");
  renameSync(snapshots, away);
  await load();
  const missing = await text(".fu-barrel-card");
  check("without a snapshot the barrel is not drawable and shows M labels, with no dollar sign",
    await svg("data-drawable") === "false" && !missing.includes("$") &&
    await evaluate(`document.querySelectorAll('.fu-barrel-card .ct-kind[data-kind="missing"]').length`) === 3, missing.slice(0, 200));
  const missingTiles = await evaluate(`[...document.querySelectorAll("#prices li.fu-tile")].map((li) => li.querySelector(".ct-kind")?.textContent.trim())`);
  check("without a snapshot the four tiles are M", missingTiles.join() === "M,M,M,M", missingTiles.join());
  const sitMissing = await evaluate(`({ state: document.querySelector("#situation")?.dataset.state,
    problem: document.querySelector("#situation .fu-sit-problem")?.textContent ?? "",
    withheldText: document.querySelector("#situation")?.textContent ?? "",
    tableOrBar: document.querySelectorAll("#situation table, #situation svg, #situation .fu-summary").length })`);
  check("without a snapshot Situation Now shows its problem and no numbers, table or bar",
    sitMissing.state === "withheld" && sitMissing.problem.length > 10 && sitMissing.tableOrBar === 0 &&
    !/\d/.test(sitMissing.withheldText.replace(/^.*?Situation Now/, "")), JSON.stringify(sitMissing));
  check("without a snapshot Drivers and Transmission still render (they come from committed content)",
    await evaluate(`document.querySelectorAll("#drivers li.fu-mech").length`) === 8 &&
    await evaluate(`document.querySelectorAll('#transmission details.fu-sector').length`) === 7);
  renameSync(away, snapshots);

  // 8. Narrow screen, wording, requests and errors.
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  await load();
  const overflow = await evaluate(`document.documentElement.scrollWidth - document.documentElement.clientWidth`);
  check("no sideways scrolling at 375 px", overflow <= 0, String(overflow));
  await evaluate(`document.querySelector('#transmission details.fu-sector[name="fu-sector"]').open = true;
    document.querySelector("#drivers li.fu-mech details.fu-mech-more").open = true;
    document.querySelector("#situation details.fu-levels").open = true; true`);
  await sleep(200);
  const overflowOpen = await evaluate(`document.documentElement.scrollWidth - document.documentElement.clientWidth`);
  check("no sideways scrolling at 375 px with a transmission card, a driver row and the levels open", overflowOpen <= 0,
    String(overflowOpen));

  // 8b. A stale snapshot: retrieved 17 days after the latest common observation (3 Nov 2026). It runs after the 375 px
  // checks above, so those still run on the negative snapshot.
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const staleWritten = spawn(python, [join(repo, "tests/fuels_fakes.py"), "snapshot", snapshots, "--variant", "positive",
    "--retrieved", "2026-11-20T14:00:00+00:00"], { cwd: repo, stdio: ["ignore", "ignore", "inherit"] });
  check("the fake writes a later positive snapshot for the stale case", await new Promise((done) => staleWritten.on("exit", done)) === 0);
  await load();
  const staleNote = await text('#situation p.fu-sit-note[data-note="stale"]');
  check("the stale snapshot shows the staleness note with 17 days, and still shows the windows",
    staleNote.includes("17 days") && await evaluate(`document.querySelectorAll('#situation table.fu-windows tr[data-state="computed"]').length`) > 0,
    staleNote);

  // 8c. A refresh in which one series came back with other units: that series is refused, the barrel is withheld.
  const refusedWritten = spawn(python, [join(repo, "tests/fuels_fakes.py"), "refused-snapshot", snapshots,
    "--retrieved", "2026-11-21T14:00:00+00:00"], { cwd: repo, stdio: ["ignore", "ignore", "inherit"] });
  check("the fake writes a later snapshot with a refused series", await new Promise((done) => refusedWritten.on("exit", done)) === 0);
  await load();
  const refusedTiles = await evaluate(`Object.fromEntries([...document.querySelectorAll("#prices li.fu-tile")].map((li) =>
    [li.dataset.tile, li.querySelector(".ct-kind")?.textContent.trim()]))`);
  const gasolineRow = await evaluate(`(() => { const tr = document.querySelector('.fu-sources-table tr[data-series="EER_EPMRU_PF4_Y35NY_DPG"]');
    return { state: tr?.dataset.state ?? "", text: tr?.textContent ?? "" }; })()`);
  check("a refused series is M with its reason, and the barrel built on it is withheld",
    refusedTiles.gasoline === "M" && refusedTiles.brent === "P" && await svg("data-drawable") === "false" &&
    gasolineRow.state === "refused" && gasolineRow.text.includes("units changed"), `${JSON.stringify(refusedTiles)} ${gasolineRow.text.slice(0, 160)}`);

  // 8d. A FRED-era snapshot alone (as one written before the move could still be on a machine): kept and listed, its
  // prices withheld.
  const eiaAway = join(root, "fuels-snapshots-eia");
  renameSync(snapshots, eiaAway);
  const fredWritten = spawn(python, [join(repo, "tests/fuels_fakes.py"), "fred-snapshot", snapshots],
    { cwd: repo, stdio: ["ignore", "ignore", "inherit"] });
  check("the fake writes a FRED-era snapshot", await new Promise((done) => fredWritten.on("exit", done)) === 0);
  await load();
  const fredState = await evaluate(`({ tiles: [...document.querySelectorAll("#prices li.fu-tile")].map((li) => li.querySelector(".ct-kind")?.textContent.trim()).join(),
    rows: [...document.querySelectorAll(".fu-sources-table tbody tr[data-state]")].map((tr) => tr.dataset.state),
    reasons: document.querySelector(".fu-sources-table")?.textContent ?? "",
    log: [...document.querySelectorAll("details.fu-more table")].map((t) => t.textContent).join(" ") })`);
  check("a FRED-era snapshot shows no price, says it came from FRED, and is listed as kept",
    fredState.tiles === "M,M,M,M" && fredState.rows.slice(0, 5).every((state) => state === "terms_changed") &&
    fredState.reasons.includes("came from FRED") && fredState.log.includes("FRED (kept; prices withheld)") &&
    await svg("data-drawable") === "false", JSON.stringify(fredState).slice(0, 300));
  rmSync(snapshots, { recursive: true, force: true });
  renameSync(eiaAway, snapshots);

  // 8e. An analysis (fuels-note-0.2) bound to a new positive snapshot: summary, one button, four labelled sections.
  const content = join(served, "fuels-content");
  const fake = (...args) => new Promise((done) => spawn(python, [join(repo, "tests/fuels_fakes.py"), ...args],
    { cwd: repo, stdio: ["ignore", "ignore", "inherit"] }).on("exit", done));
  check("the fake writes a positive snapshot and an analysis bound to it",
    await fake("snapshot", snapshots, "--variant", "positive", "--retrieved", "2026-11-22T14:00:00+00:00") === 0 &&
    await fake("analysis-note", content, snapshots) === 0);
  await load();
  const ANALYSIS = `(() => { const b = document.querySelector("#barrel button.fu-analysis-toggle");
    const d = document.querySelector("#barrel #fu-analysis-body");
    const lede = document.querySelector('#barrel .fu-lede[data-summary="analysis"]')?.textContent ?? "";
    const box = (e) => { if (!e || e.hidden) return null; const r = e.getBoundingClientRect();
      return { top: r.top + scrollY, bottom: r.bottom + scrollY, width: r.width }; };
    return { lede, words: lede.split(/\\s+/).filter(Boolean).length, headline: document.querySelector("#barrel .fu-headline")?.textContent ?? "",
      present: !!b && !!d, open: !!b && b.getAttribute("aria-expanded") === "true" && !!d && !d.hidden,
      closedState: !!b && b.getAttribute("aria-expanded") === "false" && !!d && d.hidden,
      state: b?.dataset.analysis ?? null, bodyState: d?.dataset.analysis ?? null, button: b?.textContent.trim() ?? "",
      controls: !!b && !!d && b.getAttribute("aria-controls") === d.id, inText: !!b?.closest(".fu-hero-text"),
      focusable: !!b && b.tabIndex >= 0, focused: !!b && document.activeElement === b,
      visibleSources: !!document.querySelector("#barrel .fu-note-sources"),
      card: box(document.querySelector("#barrel .fu-barrel-card")), text: box(document.querySelector("#barrel .fu-hero-text")),
      body: box(d), viewport: innerWidth,
      parts: [...(d?.querySelectorAll(".fu-an-part") ?? [])].map((p) => [p.dataset.part, p.querySelectorAll("li").length]),
      kinds: [...new Set([...(d?.querySelectorAll(".fu-an-list li") ?? [])].map((li) => li.dataset.kind))],
      labelled: [...(d?.querySelectorAll(".fu-an-list li") ?? [])].every((li) => !!li.querySelector(".fu-an-kind .ct-kind") && !!li.querySelector(".fu-an-kind-label")),
      mechanisms: [...(d?.querySelectorAll(".fu-an-mech a") ?? [])].map((a) => a.textContent.trim()),
      refs: [...(d?.querySelectorAll(".fu-an-refs a") ?? [])].every((a) => !!document.querySelector(a.getAttribute("href"))),
      sources: d?.querySelectorAll(".fu-an-sources li a.library-external").length ?? 0,
      braces: (d?.textContent ?? "").includes("{") || lede.includes("{") };
  })()`;
  const toggle = async () => { await evaluate(`document.querySelector("#barrel button.fu-analysis-toggle").click(); true`); await sleep(150); };
  const closed = await evaluate(ANALYSIS);
  check("the analysis shows a filled headline and a 40-70 word summary, and one short closed button under it",
    closed.present && closed.closedState && closed.state === "current" && !closed.braces &&
    closed.headline.startsWith("SYNTHETIC: Brent ") && !closed.headline.includes("{") &&
    closed.words >= 40 && closed.words <= 70 && closed.lede.includes("From 27 Oct 2026 to 3 Nov 2026") &&
    closed.button === "Read the analysis" && closed.controls && closed.inText && closed.focusable && !closed.visibleSources,
    JSON.stringify(closed).slice(0, 400));
  await capture("analysis-closed");
  await toggle();
  const analysisOpen = await evaluate(ANALYSIS);
  check("open, it holds the four questions, caveats and sources, every statement labelled by one of the five kinds",
    analysisOpen.open && same(analysisOpen.parts.map((p) => p[0]), ["what_happened", "meaning", "relevance", "watch", "caveats", "sources"]) &&
    analysisOpen.parts.every((p) => p[1] > 0) && analysisOpen.labelled && analysisOpen.refs && analysisOpen.sources === 2 &&
    same([...analysisOpen.kinds].sort(), ["computed", "hypothesis", "observation", "source_projection", "sourced"]),
    JSON.stringify(analysisOpen).slice(0, 400));
  check("its statements of who it may touch name the page's transmission mechanisms",
    analysisOpen.mechanisms.includes("Refiners and oil producers") && analysisOpen.mechanisms.includes("Shipping, trucking and logistics"),
    analysisOpen.mechanisms.join());
  const stays = (a, b) => !!a.card && !!b.card && Math.abs(a.card.top - b.card.top) < 1 && Math.abs(a.card.bottom - b.card.bottom) < 1 &&
    Math.abs(a.text.top - b.text.top) < 1;
  check("opening leaves the barrel and the summary where they were; the analysis starts below both, at a reading width",
    stays(closed, analysisOpen) && analysisOpen.body.top >= analysisOpen.card.bottom &&
    analysisOpen.body.top >= analysisOpen.text.bottom && analysisOpen.body.width <= 760,
    JSON.stringify({ closed: [closed.card, closed.text], open: [analysisOpen.card, analysisOpen.text, analysisOpen.body] }));
  await capture("analysis-open");
  await toggle();
  const reclosed = await evaluate(ANALYSIS);
  await evaluate(`document.querySelector("#barrel button.fu-analysis-toggle").focus(); true`);
  for (const type of ["keyDown", "keyUp"]) {
    await send("Input.dispatchKeyEvent", { type, key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, ...(type === "keyDown" ? { text: "\r" } : {}) });
  }
  await sleep(150);
  const keyed = await evaluate(ANALYSIS);
  check("the button closes it again, and Enter on the focused button opens it",
    reclosed.closedState && keyed.open && keyed.focused, JSON.stringify({ reclosed: reclosed.closedState, keyed: keyed.open, focused: keyed.focused }));
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  await load();
  const phoneClosed = await evaluate(ANALYSIS);
  await toggle();
  const phoneOpen = await evaluate(ANALYSIS);
  check("at 375 px the barrel stays above the summary, the analysis opens below the summary and nothing scrolls sideways",
    phoneOpen.open && stays(phoneClosed, phoneOpen) && phoneOpen.card.bottom <= phoneOpen.text.top + 1 &&
    phoneOpen.body.top >= phoneOpen.text.bottom &&
    await evaluate(`document.documentElement.scrollWidth - document.documentElement.clientWidth`) <= 0,
    JSON.stringify({ card: phoneOpen.card, text: phoneOpen.text, body: phoneOpen.body }));
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  check("the fake writes a later snapshot",
    await fake("snapshot", snapshots, "--variant", "negative", "--retrieved", "2026-11-22T16:00:00+00:00") === 0);
  await load();
  const earlier = await evaluate(ANALYSIS);
  check("after a refresh the analysis says it was written for an earlier refresh, beside the then-and-now line",
    earlier.state === "earlier" && earlier.bodyState === "earlier" && earlier.button === "Read the earlier analysis" &&
    (await text(".fu-refreshed")).startsWith("Prices have been refreshed since this note"), JSON.stringify(earlier).slice(0, 200));
  const analysisAway = join(root, "fuels-snapshots-analysis");
  renameSync(snapshots, analysisAway);
  await load();
  const unbound = await evaluate(ANALYSIS);
  check("without its snapshot the analysis is not shown as a reading, and the page says why",
    !unbound.present && unbound.button === "" && unbound.lede === "" && (await text("#barrel")).includes("is not among the verified snapshots"),
    (await text("#barrel")).slice(0, 200));
  renameSync(analysisAway, snapshots);

  // 8f. A crack change under a cent beside the offsetting label: shown with its direction and "<0.01", never as a bare
  // 0.00, with the key under the table; the exact split and label are the server's (checked by the reader).
  check("the fake writes a snapshot whose crack moves under a cent",
    await fake("snapshot", snapshots, "--variant", "subcent", "--retrieved", "2026-11-23T14:00:00+00:00") === 0);
  await load();
  const SMALL = `(() => { const cell = (w) => document.querySelector('#situation tr[data-window="' + w + '"] td[data-row="crack"] .fu-change')?.textContent ?? "";
    return { previous: cell("previous"), week: cell("week"), summary: document.querySelector("#situation .fu-summary")?.textContent ?? "",
      label: document.querySelector("#situation .fu-summary")?.dataset.label ?? "",
      key: document.querySelector('#situation p.fu-sit-note[data-note="small"]')?.textContent ?? "",
      part: document.querySelector('#situation li.fu-split[data-window="week"] .fu-split-value[data-part="crack"]')?.textContent ?? "",
      refused: !document.querySelector("article.fu-page") }; })()`;
  const small = await evaluate(SMALL);
  check("a crack change under a cent shows its direction and <0.01 in the table, the split and the summary, with the key",
    !small.refused && small.previous === `${MINUS}<0.01` && small.week === `${MINUS}<0.01` && small.label === "offsetting" &&
    small.summary.includes("Brent and the crack moved in opposite directions; the crack fell by less than $0.01.") &&
    small.part.includes(`${MINUS}<$0.01`) && small.key.includes("0.00 is no change"), JSON.stringify(small));
  await captureSection("small-change", "#situation table.fu-windows");

  // 8g. Diesel a year behind the other series: its price stays, dated and marked; the barrel, the crack and Situation
  // Now are withheld with the reason; the page is not refused.
  check("the fake writes a snapshot with diesel a year behind",
    await fake("behind-snapshot", snapshots, "--behind", "diesel", "--retrieved", "2026-11-24T14:00:00+00:00") === 0);
  await load();
  const BEHIND = `(() => { const tile = (r) => document.querySelector('#prices li.fu-tile[data-tile="' + r + '"]');
    return { refused: !document.querySelector("article.fu-page"),
      diesel: tile("diesel")?.querySelector(".fu-tile-value")?.textContent ?? "", dieselKind: tile("diesel")?.querySelector(".ct-kind")?.textContent.trim() ?? "",
      dieselDate: tile("diesel")?.querySelector(".fu-tile-dates")?.textContent ?? "",
      dieselBehind: tile("diesel")?.querySelector(".fu-behind")?.textContent ?? "",
      brentBehind: !!tile("brent")?.querySelector(".fu-behind"), brentKind: tile("brent")?.querySelector(".ct-kind")?.textContent.trim() ?? "",
      crack: tile("crack")?.textContent ?? "", situation: document.querySelector("#situation")?.dataset.state ?? "",
      situationNumbers: document.querySelectorAll("#situation table, #situation svg").length,
      wtiBehind: document.querySelector('.fu-coverage li[data-coverage="wti"] .fu-behind')?.textContent ?? "" }; })()`;
  const dieselLate = await evaluate(BEHIND);
  check("diesel a year behind keeps its P price, its own date and a line saying how far behind, and the page reads",
    !dieselLate.refused && dieselLate.dieselKind === "P" && dieselLate.diesel.startsWith("$") &&
    dieselLate.dieselDate.includes("3 Nov 2025") && dieselLate.dieselBehind.startsWith("365 days behind the newest price") &&
    dieselLate.dieselBehind.includes("not computed from it") && !dieselLate.brentBehind && dieselLate.brentKind === "P",
    JSON.stringify(dieselLate).slice(0, 500));
  check("the barrel, the crack and Situation Now are withheld, saying prices from different dates are never combined",
    await svg("data-drawable") === "false" && dieselLate.crack.includes("Withheld") && dieselLate.crack.includes("never combined") &&
    dieselLate.situation === "withheld" && dieselLate.situationNumbers === 0, JSON.stringify(dieselLate).slice(0, 500));
  await capture("diesel-behind");
  await captureSection("prices-diesel-behind", "#prices");

  // 8h. WTI a year behind: its coverage entry keeps its price and date with the line; the barrel and Situation Now stay.
  check("the fake writes a snapshot with WTI a year behind",
    await fake("behind-snapshot", snapshots, "--behind", "wti", "--retrieved", "2026-11-25T14:00:00+00:00") === 0);
  await load();
  const wtiLate = await evaluate(BEHIND);
  check("WTI a year behind is marked in its coverage entry, and the barrel and Situation Now are computed as usual",
    !wtiLate.refused && wtiLate.wtiBehind.startsWith("365 days behind the newest price") && !wtiLate.wtiBehind.includes("barrel") &&
    await svg("data-drawable") === "true" && wtiLate.situation === "computed" && wtiLate.dieselBehind === "",
    JSON.stringify(wtiLate).slice(0, 500));
  await captureSection("coverage-wti-behind", "#prices ul.fu-coverage");
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  await load();
  check("at 375 px the WTI-behind page does not scroll sideways",
    await evaluate(`document.documentElement.scrollWidth - document.documentElement.clientWidth`) <= 0);
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  const found = texts.flatMap((page) => affirmative(page));
  check("no page load contains today or a banned phrase", found.length === 0, [...new Set(found)].join());
  const outside = requests.filter((r) => !r.url.startsWith(base) && !r.url.startsWith("data:") && !r.url.startsWith("about:"));
  check("only requests to the local server", outside.length === 0, outside.map((r) => r.url).join());
  const writes = requests.filter((r) => r.method !== "GET" && r.method !== "HEAD");
  check("the page makes no write request", writes.length === 0, writes.map((r) => r.url).join());
  const real = errors.filter((e) => !e.url.endsWith("/favicon.ico"));
  check("no page errors", real.length === 0, real.map((e) => `${e.text} @ ${e.url}`).join(" | "));
} catch (error) {
  check("the check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(300);
  try { rmSync(root, { recursive: true, force: true }); } catch { /* Windows may hold a file briefly */ }
  const failed = results.filter((ok) => !ok).length;
  console.log(`\n${results.length - failed}/${results.length} checks passed`);
  process.exitCode = failed ? 1 : 0;
}
