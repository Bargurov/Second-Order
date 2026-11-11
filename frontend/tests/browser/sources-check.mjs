// Browser acceptance check for the Event Inbox's energy and trade sources, in one headless Chrome against
// tests/review_browser_server.py with --simulated-feeds sources (SYNTHETIC feeds behind the five allowlisted URLs,
// the energy and trade ones shaped like EIA's and WTO's real feeds) and --simulated-triage (an in-process fake that
// records every triage request it receives). The journey: five source cards with their topics, kinds and credits ->
// Refresh events: each feed once -> energy articles and trade news labelled apart from statistical releases, with
// their feed timestamps undisturbed -> topic and source filters over what is held, requesting nothing -> a second
// refresh in which one energy article leaves its feed (retained history) and the trade feed fails (its entries kept)
// -> triage of energy and trade entries, current and retained, on the simulated fake -> Analyze this event fills only
// the headline and official link -> a reload served from the local cache. No model, provider or real feed is
// contacted, and the page requests nothing outside the local server.
//
//   cd frontend; npm run build; npm run test:browser:sources
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const python = process.env.SECOND_ORDER_PYTHON ?? "python";
const chromePath = [process.env.SECOND_ORDER_CHROME, "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
  "/usr/bin/chromium-browser"].find((path) => path && existsSync(path));
if (!chromePath) throw new Error("Chrome was not found; set SECOND_ORDER_CHROME to its executable.");
if (!existsSync(join(repo, "frontend/dist/index.html"))) throw new Error("Build the client first: npm run build");

const FEEDS = ["https://www.federalreserve.gov/feeds/press_monetary.xml", "https://www.bls.gov/feed/empsit.rss",
               "https://www.bls.gov/feed/cpi.rss", "https://www.eia.gov/rss/todayinenergy.xml",
               "https://www.wto.org/library/rss/latest_news_e.xml"];
const KEYS = ["fed-monetary", "bls-empsit", "bls-cpi", "eia-todayinenergy", "wto-news"];
const STATEMENT = "Simulated: Federal Reserve issues FOMC statement";
const PAYROLL = "Simulated: Payroll employment changes little in September";
const CPI = "Simulated: CPI rises 0.4 percent in August";
const EXPORTS = "Simulated: Hydro-Québec electricity exports to New England fell";
const MARGINS = "Simulated: Refinery margins rose in the third quarter";
const WINTER = "Simulated: Winter heating expenditures will vary by fuel";
const MORATORIUM = "Simulated: Members agree to extend the e-commerce moratorium";
const FORECAST = "Simulated: Trade forecast raised for 2026";
const EXPORTS_LINK = "https://www.eia.gov/todayinenergy/detail.php?id=90001";
const MORATORIUM_LINK = "https://www.wto.org/english/news_e/news26_e/synth_08oct26_e.htm";

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const root = mkdtempSync(join(tmpdir(), "second-order-sources-check-"));
const served = join(root, "served");
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const folder = (...parts) => (existsSync(join(served, ...parts)) ? readdirSync(join(served, ...parts)).sort() : []);
const feedRequests = () => existsSync(join(served, "simulated-feeds", "requests.jsonl"))
  ? readFileSync(join(served, "simulated-feeds", "requests.jsonl"), "utf8").trim().split("\n").filter(Boolean).map(JSON.parse)
  : [];
const calls = () => folder("simulated-triage").filter((name) => name.startsWith("request-")).length;
const sent = (n) => JSON.parse(readFileSync(join(served, "simulated-triage", `request-${n}.json`), "utf8"));
const payload = (request) => { const text = request.messages[0].content; return JSON.parse(text.slice(text.indexOf("\n\n{") + 2)); };

try {
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    "--simulated-feeds", "sources", "--simulated-triage"], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  let started = false;
  for (let i = 0; i < 150 && !started; i++) {
    try { started = (await fetch(`${base}/api/drafts`)).ok; } catch { await sleep(200); }
  }
  if (!started) throw new Error("The review server did not start.");

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
  const listeners = [];
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else listeners.forEach((listener) => listener(message));
  });
  const send = (method, params = {}) => new Promise((done, fail) => {
    const id = ++counter;
    pending.set(id, (message) => message.error ? fail(new Error(message.error.message)) : done(message.result));
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) =>
    (await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })).result.value;
  const waitFor = async (expression, timeout = 10000) => {
    for (const start = Date.now(); Date.now() - start < timeout; await sleep(80)) {
      if (await evaluate(expression)) return true;
    }
    return false;
  };
  const setValue = (selector, value) => evaluate(`(() => {
    const element = document.querySelector(${JSON.stringify(selector)});
    if (!element) return false;
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(element, ${JSON.stringify(value)});
    element.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`);
  const click = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.click()`);
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);

  const requests = [];
  const consoleErrors = [];
  listeners.push((message) => {
    if (message.method === "Network.requestWillBeSent") {
      requests.push({ url: message.params.request.url, method: message.params.request.method });
    }
    if (message.method === "Runtime.exceptionThrown") consoleErrors.push({ text: message.params.exceptionDetails.text, url: "" });
    if (message.method === "Log.entryAdded" && message.params.entry.level === "error") {
      consoleErrors.push({ text: message.params.entry.text, url: message.params.entry.url ?? "" });
    }
  });
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Log.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete' && !!document.querySelector('.event-inbox .inbox-sources')");
  };
  const apiCalls = () => requests.filter((r) => r.url.startsWith(`${base}/api/`)).length;
  const entries = (list = ".inbox-items:not(.inbox-retained-items)") => evaluate(`[...document.querySelectorAll(
    ${JSON.stringify(`${list} > .inbox-item`)})].map((li) => li.querySelector("h3").textContent)`);
  const entryJs = (title) => `[...document.querySelectorAll(".inbox-item")].find((li) =>
    li.querySelector("h3").textContent === ${JSON.stringify(title)})`;
  const entry = (title) => evaluate(`(() => { const li = ${entryJs(title)}; if (!li) return null;
    const a = li.querySelector(".inbox-item-meta a");
    return { source: li.dataset.source, kind: li.dataset.kind, meta: li.querySelector(".inbox-item-meta").textContent,
             label: a?.textContent ?? null, href: a?.getAttribute("href") ?? null,
             time: li.querySelector(".inbox-item-time").textContent, code: li.querySelector(".inbox-item-time code").textContent,
             fresh: li.querySelector(".inbox-item-fresh").textContent, text: li.textContent }; })()`);
  const card = (key) => text(`.inbox-source[data-source="${key}"]`);
  const select = (title) => evaluate(`(() => { const input = (${entryJs(title)})?.querySelector(".inbox-select input");
    if (!input || input.disabled) return false; input.click(); return true; })()`);
  const choose = (title) => evaluate(`(() => { const button = (${entryJs(title)})?.querySelector(".inbox-analyze");
    if (!button || button.disabled) return false; button.click(); return true; })()`);
  const options = (name) => evaluate(`[...document.querySelectorAll('select[name="${name}"] option')].map((o) => o.textContent)`);
  const preview = async () => {
    const before = await evaluate(`document.querySelector(".triage-message")?.textContent ?? ""`);
    await click(".triage-preview");
    await waitFor(`!document.querySelector(".triage-preview").textContent.includes("Resolving")`);
    return waitFor(`!!document.querySelector(".triage-plan") && (document.querySelector(".triage-message")?.textContent ?? "") !== ${JSON.stringify(before)}`);
  };
  const counts = () => evaluate(`Object.fromEntries([...document.querySelectorAll(".triage-plan-counts span")].map((s) =>
    [s.textContent.replace(/^\\d+\\s*/, ""), Number(s.querySelector("strong").textContent)]))`);
  const formValues = () => evaluate(`({
    headline: document.querySelector('.intake-form input:not([type="url"]):not([type="date"]):not([type="time"]):not([type="checkbox"])')?.value,
    url: document.querySelector('.intake-form input[type="url"]')?.value,
    date: document.querySelector('.intake-form input[type="date"]')?.value,
    time: document.querySelector('.intake-form input[type="time"]')?.value,
    offset: document.querySelector(".intake-time select")?.value,
    text: document.querySelector(".intake-form textarea")?.value })`);

  // 1. A first visit: five sources with topics, kinds and credits; nothing requested.
  await open("/");
  check("the inbox lists the five fixed sources in order, never refreshed",
    JSON.stringify(await evaluate(`[...document.querySelectorAll(".inbox-source")].map((li) => li.dataset.source)`)) ===
      JSON.stringify(KEYS) &&
    await evaluate(`[...document.querySelectorAll(".inbox-source")].every((li) => li.dataset.state === "never_refreshed")`));
  const energyCard = await card("eia-todayinenergy");
  const tradeCard = await card("wto-news");
  check("the energy source states its topic, its kind and the credit EIA's reuse terms ask for",
    energyCard.includes("EIA: Today in Energy") && energyCard.includes("Energy · Analysis article, not a statistical release") &&
    energyCard.includes("credited as “Source: U.S. Energy Information Administration”") &&
    await evaluate(`document.querySelector('.inbox-source[data-source="eia-todayinenergy"] .inbox-source-credit a')
      .getAttribute("href") === "https://www.eia.gov/about/copyrights_reuse.php"`), energyCard);
  check("the trade source states its topic, its kind and the credit the WTO asks for",
    tradeCard.includes("WTO: Latest news") && tradeCard.includes("International trade · News announcement, not a statistical release") &&
    tradeCard.includes("World Trade Organization") && tradeCard.includes("credited as “WTO news”") &&
    await evaluate(`document.querySelector('.inbox-source[data-source="wto-news"] .inbox-source-credit a')
      .getAttribute("href") === "https://www.wto.org/english/info_e/copyrights_permissions_e.htm"`), tradeCard);
  check("only the BLS sources are described as formal statistical releases",
    (await card("bls-cpi")).includes("Inflation · Formal statistical release") &&
    (await card("fed-monetary")).includes("Monetary policy · Policy announcement, not a statistical release"));
  await sleep(300);
  check("loading the page requested no feed", feedRequests().length === 0 && !existsSync(join(served, "event-inbox")));

  // 2. Refresh events: each of the five feeds once.
  await click(".inbox-refresh");
  check("Refresh events lists every usable entry of the five feeds",
    await waitFor(`document.querySelectorAll(".inbox-items .inbox-item").length === 8`, 15000), JSON.stringify(await entries()));
  const first = feedRequests();
  check("the refresh requested each allowlisted feed exactly once, in order, and nothing else",
    JSON.stringify(first.map((r) => r.url)) === JSON.stringify(FEEDS) && first.every((r) => r.method === "GET"),
    JSON.stringify(first.map((r) => r.url)));
  check("entries with a usable feed instant come first; the energy and trade entries follow in feed order",
    JSON.stringify(await entries()) === JSON.stringify([PAYROLL, STATEMENT, CPI, EXPORTS, MARGINS, WINTER, MORATORIUM, FORECAST]),
    JSON.stringify(await entries()));
  check("each source card counts what was kept and what was skipped",
    (await card("eia-todayinenergy")).includes("3 entries kept of 5 listed, 2 skipped") &&
    (await card("wto-news")).includes("2 entries kept of 3 listed, 1 skipped"));
  const energy = await entry(EXPORTS);
  check("an energy article keeps its ISO-8859-1 headline and shows its topic, kind, publisher, credit and link",
    energy.source === "eia-todayinenergy" && energy.kind === "Analysis article" && energy.meta.includes("Energy") &&
    energy.meta.includes("U.S. Energy Information Administration") &&
    energy.meta.includes("credited as “Source: U.S. Energy Information Administration”") &&
    energy.label === "Official article" && energy.href === EXPORTS_LINK, JSON.stringify(energy));
  check("its fixed 09:00:00 EST stamp is shown raw, with no instant, because EST contradicts an October date",
    energy.code === "Wed, 07 Oct 2026  09:00:00 EST" && !energy.time.includes(" UTC.") &&
    energy.time.includes("names EST (UTC-05:00), but US Eastern time was UTC-04:00") &&
    energy.time.includes("Not a verified release time"), energy.time);
  const trade = await entry(MORATORIUM);
  check("a trade item shows its topic, kind, credit and link, and only its date",
    trade.source === "wto-news" && trade.kind === "News announcement" && trade.meta.includes("International trade") &&
    trade.meta.includes("credited as “WTO news”") && trade.label === "Official news item" && trade.href === MORATORIUM_LINK &&
    trade.code === "Thu, 08 Oct 2026 00:00:00 GMT" && trade.time.includes("the date 2026-10-08 with a 00:00:00 placeholder time") &&
    !trade.time.includes("2026-10-08 00:00 UTC"), JSON.stringify(trade));
  check("the trade feed's full-article content is never stored or shown",
    !(await text(".event-inbox")).includes("full article body") &&
    !readFileSync(join(served, "event-inbox", "wto-news.json"), "utf8").includes("full article body"));
  const release = await entry(CPI);
  check("statistical releases are labelled as such, apart from articles and news",
    release.kind === "Statistical release" && release.label === "Official release" &&
    (await entry(STATEMENT)).kind === "Policy announcement");

  // 3. Topic and source filters narrow what is held and request nothing.
  check("the filters offer every topic and every source",
    JSON.stringify(await options("inbox-topic")) === JSON.stringify(["All topics", "Monetary policy", "Employment", "Inflation",
      "Energy", "International trade"]) &&
    JSON.stringify(await options("inbox-source")) === JSON.stringify(["All sources", "Federal Reserve: monetary policy press releases",
      "BLS: The Employment Situation", "BLS: Consumer Price Index", "EIA: Today in Energy", "WTO: Latest news"]));
  const quiet = { api: apiCalls(), feeds: feedRequests().length };
  await setValue('select[name="inbox-topic"]', "Energy");
  check("the Energy topic shows only the three energy articles",
    await waitFor(`document.querySelectorAll(".inbox-items .inbox-item").length === 3`) &&
    JSON.stringify(await entries()) === JSON.stringify([EXPORTS, MARGINS, WINTER]) &&
    (await text(".inbox-filter-count")).startsWith("Showing 3 of 8 current entries and 0 of 0 retained."));
  await setValue('select[name="inbox-topic"]', "");
  await setValue('select[name="inbox-source"]', "wto-news");
  check("the WTO source shows only its two news items",
    await waitFor(`document.querySelectorAll(".inbox-items .inbox-item").length === 2`) &&
    JSON.stringify(await entries()) === JSON.stringify([MORATORIUM, FORECAST]));
  await setValue('select[name="inbox-topic"]', "Energy");
  check("a topic and a source that do not meet show none, and say so",
    await waitFor(`document.querySelectorAll(".inbox-items .inbox-item").length === 0`) &&
    (await text(".event-inbox")).includes("No current entries match this topic and source."));
  await click(".inbox-filter-reset");
  check("Show all entries clears both filters",
    await waitFor(`document.querySelectorAll(".inbox-items .inbox-item").length === 8`) &&
    (await evaluate(`document.querySelector('select[name="inbox-topic"]').value + "|" + document.querySelector('select[name="inbox-source"]').value`)) === "|");
  await sleep(200);
  check("filtering requested nothing: no API call and no feed request",
    apiCalls() === quiet.api && feedRequests().length === quiet.feeds, JSON.stringify({ quiet, api: apiCalls() }));

  // 4. A second refresh: one energy article leaves its feed, and the trade feed fails.
  await click(".inbox-refresh");
  check("a partly failed refresh says so",
    await waitFor(`(document.querySelector(".inbox-message")?.textContent ?? "").includes("did not refresh")`, 15000));
  check("the second refresh again requested each feed once, with no retry",
    feedRequests().length === 10 && JSON.stringify(feedRequests().slice(5).map((r) => r.url)) === JSON.stringify(FEEDS));
  const failedCard = await card("wto-news");
  check("the failed trade source reports the error and keeps its last good entries, marked as earlier",
    failedCard.includes("HTTP 503") && failedCard.includes("showing its last successful retrieval") &&
    (await entry(MORATORIUM)).fresh.includes("did not succeed") && (await entry(FORECAST)).fresh.includes("did not succeed"),
    failedCard);
  check("the energy source refreshed: its departed article left the current list and was retained",
    (await card("eia-todayinenergy")).includes("Local archive: 3 entries, 3 versions; 1 no longer in the feed.") &&
    !(await entries()).includes(WINTER) && (await text(".inbox-history-toggle")) === "Show retained headlines (1)");
  await setValue('select[name="inbox-topic"]', "Energy");
  await waitFor(`(document.querySelector(".inbox-history-toggle")?.textContent ?? "").includes("1 of 1")`);
  await click(".inbox-history-toggle");
  check("the retained energy article is shown under the Energy filter, as history",
    await waitFor(`document.querySelectorAll(".inbox-retained-items .inbox-item").length === 1`) &&
    JSON.stringify(await entries(".inbox-retained-items")) === JSON.stringify([WINTER]) &&
    (await entry(WINTER)).fresh.startsWith("Retained history: last seen in its feed"));
  await setValue('select[name="inbox-topic"]', "");
  await setValue('select[name="inbox-source"]', "wto-news");
  check("the trade filter holds no retained history, and says so",
    await waitFor(`(document.querySelector(".inbox-history")?.textContent ?? "").includes("No retained headlines match")`));
  await click(".inbox-filter-reset");

  // 5. Triage of energy and trade entries, current and retained, on the simulated fake.
  for (const title of [EXPORTS, WINTER, MORATORIUM, FORECAST, STATEMENT]) await select(title);
  check("five entries from three publishers are selected, the retained article included",
    (await text(".triage-count")) === "5 of 25 selected");
  await preview();
  check("the plan triages all five and compares only within each publisher",
    JSON.stringify(await counts()) === JSON.stringify({ "saved results reused": 0, "need a result": 5,
      "earlier entries as comparison context only": 0, "unresolved": 0, "from an earlier version": 0 }) &&
    (await text(".triage-plan-requests")).startsWith("Planned requests: 1, with 5 entries to triage and 2 pairs to compare") &&
    (await text(".triage-plan-pairs")).includes("0 of 2 candidate"), JSON.stringify(await counts()));
  check("previewing sent nothing", calls() === 0);
  await click(".triage-confirm input");
  await click(".triage-approve");
  await waitFor(`(document.querySelector(".triage-message")?.textContent ?? "").includes("recorded")`, 15000);
  const request = payload(sent(1));
  const byTitle = Object.fromEntries(request.entries.map((item) => [item.title, item]));
  check("one simulated request carried the five entries as recorded, timestamps unconverted and no article text",
    calls() === 1 && request.entries.length === 5 && request.comparison_context.length === 0 &&
    byTitle[EXPORTS].feed_timestamp.raw === "Wed, 07 Oct 2026  09:00:00 EST" && byTitle[EXPORTS].feed_timestamp.utc === null &&
    byTitle[MORATORIUM].feed_timestamp.utc === null && byTitle[EXPORTS].feed_category === "Energy" &&
    byTitle[MORATORIUM].publisher === "World Trade Organization" && !JSON.stringify(request).includes("full article body"),
    JSON.stringify(request.entries.map((item) => [item.title, item.feed_timestamp])));
  check("all five then reuse their saved results",
    await waitFor(`[...document.querySelectorAll(".triage-results .triage-row")].length === 5 &&
      [...document.querySelectorAll(".triage-results .triage-row")].every((r) => r.dataset.status === "reuse")`));
  await preview();
  check("previewing the same entries again requests nothing",
    (await text(".triage-message")).includes("Nothing to request") && calls() === 1);

  // 6. Analyze this event fills only the headline and official link, for an article and for a news item.
  const before = { feeds: feedRequests().length, calls: calls() };
  check("Analyze this event on an energy article fills only its headline and link",
    await choose(EXPORTS) && await waitFor(`!!document.querySelector(".intake-origin")`) &&
    JSON.stringify(await formValues()) === JSON.stringify({ headline: EXPORTS, url: EXPORTS_LINK, date: "", time: "",
                                                             offset: "", text: "" }), JSON.stringify(await formValues()));
  const energyOrigin = await text(".intake-origin");
  check("the form says what the entry is and how to credit it, and offers no time from the contradictory stamp",
    energyOrigin.includes("U.S. Energy Information Administration · Energy · Official article") &&
    energyOrigin.includes("Analysis article, not a statistical release.") &&
    energyOrigin.includes("Credit the publisher as “Source: U.S. Energy Information Administration”.") &&
    energyOrigin.includes("No suggestion: The feed's timestamp names EST") &&
    !(await evaluate(`!!document.querySelector(".intake-use-suggestion")`)), energyOrigin);
  check("Analyze this event on a trade item fills only its headline and link, with no time from its placeholder",
    await choose(MORATORIUM) && await waitFor(`(document.querySelector(".intake-origin")?.textContent ?? "").includes("WTO news")`) &&
    JSON.stringify(await formValues()) === JSON.stringify({ headline: MORATORIUM, url: MORATORIUM_LINK, date: "", time: "",
                                                             offset: "", text: "" }) &&
    (await text(".intake-origin")).includes("No suggestion: The feed gives the date 2026-10-08 with a 00:00:00 placeholder time"));
  await sleep(300);
  check("choosing entries fetched no article, requested no feed and sent nothing",
    feedRequests().length === before.feeds && calls() === before.calls &&
    requests.filter((r) => r.method === "POST" && r.url.includes("/api/intake")).length === 0);

  // 7. A reload and a narrow window: everything comes from the local cache.
  await open("/");
  await waitFor(`document.querySelectorAll(".inbox-items .inbox-item").length === 7`);
  check("after a reload the same entries and retained history are read locally, with no feed request",
    JSON.stringify(await entries()) === JSON.stringify([PAYROLL, STATEMENT, CPI, EXPORTS, MARGINS, MORATORIUM, FORECAST]) &&
    (await text(".inbox-history-toggle")) === "Show retained headlines (1)" && feedRequests().length === 10);
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 1, mobile: true });
  await sleep(300);
  check("at phone width the filters and source cards fit without horizontal scrolling",
    await evaluate(`document.documentElement.scrollWidth <= window.innerWidth &&
      [...document.querySelectorAll(".inbox-filter select")].every((s) => s.getBoundingClientRect().right <= window.innerWidth)`));
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  // 8. Only explicit actions wrote, and nothing outside the local server was requested.
  const writes = requests.filter((r) => r.method !== "GET").map((r) => new URL(r.url).pathname
    .replace(/\/api\/triage\/triage-[0-9a-f]{24}\//, "/api/triage/*/"));
  const allowed = new Set(["/api/inbox/refresh", "/api/triage", "/api/triage/*/simulated"]);
  check("every write was an explicit action: two refreshes, triage previews and one approval",
    writes.every((path) => allowed.has(path)) && writes.filter((p) => p === "/api/inbox/refresh").length === 2 &&
    writes.filter((p) => p.endsWith("/simulated")).length === 1, JSON.stringify(writes));
  check("no paid triage was possible or attempted", !folder("headline-triage", "requests").some((id) =>
    folder("headline-triage", "requests", id).includes("paid")));
  const outside = requests.filter(({ url }) => !url.startsWith(base) && !url.startsWith("data:") && url !== "about:blank");
  check("the page requested nothing outside the local server", outside.length === 0, outside.map((r) => r.url).join(", "));
  const pageErrors = consoleErrors.filter((error) => !/\/favicon\.ico$/.test(error.url));
  check("the page logged no errors (the favicon probe aside)", pageErrors.length === 0, JSON.stringify(pageErrors));
  ws.close();
} catch (error) {
  check("the sources browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(500);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
