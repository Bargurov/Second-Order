// Browser acceptance check for the case library: discovery from the Tracker and the top bar; all twenty-seven cases
// read in full, with the source check and reading aid on the two enriched BIS cases (flagged discrepancies, statuses,
// unread references, the historical comparison; no retained copy on the test machine); search, topic and sector filters (combined, case-insensitive, counts, multi-sector cases shown once,
// no results, reset) kept in the address across a reload and Back; keyboard use; moving between the library and its
// cases (links, previous/next, Back); date-only publication dates; a direct reload of a case; the official source
// links; an unknown case and an unknown sector; narrow-screen readability; and no request outside the local server.
// The server is tests/review_browser_server.py over an empty temporary folder: no runtime records, keys or providers.
// It reads the committed market-context bundle, as production does, so the twelve macro cases show their market
// context and the twelve sector cases say plainly that none is attached; the market context check covers that
// section in detail.
//
//   cd frontend; npm run build; npm run test:browser:library
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
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

const CASES = [  // In publication order: the library's one order.
  { id: "fomc-2025-01-29", category: "Monetary policy", published: "29 Jan 2025, 14:00 UTC−05:00 (19:00 UTC)", url: "https://www.federalreserve.gov/newsevents/pressreleases/monetary20250129a.htm" },
  { id: "fomc-2025-03-19", category: "Monetary policy", published: "19 Mar 2025, 14:00 UTC−04:00 (18:00 UTC)", url: "https://www.federalreserve.gov/newsevents/pressreleases/monetary20250319a.htm" },
  { id: "empsit-2025-04-04", category: "Employment", published: "4 Apr 2025, 08:30 UTC−04:00 (12:30 UTC)", url: "https://www.bls.gov/news.release/archives/empsit_04042025.htm" },
  { id: "cpi-2025-04-10", category: "Inflation", published: "10 Apr 2025, 08:30 UTC−04:00 (12:30 UTC)", url: "https://www.bls.gov/news.release/archives/cpi_04102025.htm" },
  { id: "empsit-2025-05-02", category: "Employment", published: "2 May 2025, 08:30 UTC−04:00 (12:30 UTC)", url: "https://www.bls.gov/news.release/archives/empsit_05022025.htm" },
  { id: "fomc-2025-05-07", category: "Monetary policy", published: "7 May 2025, 14:00 UTC−04:00 (18:00 UTC)", url: "https://www.federalreserve.gov/newsevents/pressreleases/monetary20250507a.htm" },
  { id: "cpi-2025-05-13", category: "Inflation", published: "13 May 2025, 08:30 UTC−04:00 (12:30 UTC)", url: "https://www.bls.gov/news.release/archives/cpi_05132025.htm" },
  { id: "empsit-2025-06-06", category: "Employment", published: "6 Jun 2025, 08:30 UTC−04:00 (12:30 UTC)", url: "https://www.bls.gov/news.release/archives/empsit_06062025.htm" },
  { id: "cpi-2025-06-11", category: "Inflation", published: "11 Jun 2025, 08:30 UTC−04:00 (12:30 UTC)", url: "https://www.bls.gov/news.release/archives/cpi_06112025.htm" },
  { id: "fomc-2025-06-18", category: "Monetary policy", published: "18 Jun 2025, 14:00 UTC−04:00 (18:00 UTC)", url: "https://www.federalreserve.gov/newsevents/pressreleases/monetary20250618a.htm" },
  { id: "empsit-2025-07-03", category: "Employment", published: "3 Jul 2025, 08:30 UTC−04:00 (12:30 UTC)", url: "https://www.bls.gov/news.release/archives/empsit_07032025.htm" },
  { id: "cpi-2025-07-15", category: "Inflation", published: "15 Jul 2025, 08:30 UTC−04:00 (12:30 UTC)", url: "https://www.bls.gov/news.release/archives/cpi_07152025.htm" },
  ...[
    ["bis-2026-02-12", "Export controls", "12 Feb 2026", "https://www.bis.gov/press-release/applied-materials-pay-252-million-penalty-bis-illegally-exporting-semiconductor-manufacturing-equipment", ["Technology & semiconductors"]],
    ["bis-2026-06-17", "Export controls", "17 Jun 2026", "https://www.bis.gov/press-release/robert-bosch-gmbh-bosch-pay-36-million-penalty-bis-violations-pertaining-shipments-huawei", ["Technology & semiconductors", "Manufacturing & automotive"]],
    ["bis-2026-07-10", "Export controls", "10 Jul 2026", "https://www.bis.gov/press-release/department-commerce-eases-export-controls-uae", ["Technology & semiconductors"]],
    ["g17-2026-07-17", "Industrial production", "17 Jul 2026", "https://www.federalreserve.gov/releases/g17/20260717/", ["Manufacturing & automotive", "Energy", "Mining & materials"]],
    ["g17-2026-08-18", "Industrial production", "18 Aug 2026", "https://www.federalreserve.gov/releases/g17/20260818/", ["Manufacturing & automotive", "Technology & semiconductors", "Mining & materials"]],
    ["h8-2026-09-11", "Bank balance sheets", "11 Sep 2026", "https://www.federalreserve.gov/releases/h8/20260911/", ["Banking & credit"]],
    ["g17-2026-09-18", "Industrial production", "18 Sep 2026", "https://www.federalreserve.gov/releases/g17/20260918/", ["Manufacturing & automotive", "Energy", "Mining & materials"]],
    ["h8-2026-09-18", "Bank balance sheets", "18 Sep 2026", "https://www.federalreserve.gov/releases/h8/20260918/", ["Banking & credit"]],
    ["eia-tie-2026-09-22", "Energy analysis", "22 Sep 2026", "https://www.eia.gov/todayinenergy/detail.php?id=68184", ["Energy"]],
    ["eia-tie-2026-09-25", "Energy analysis", "25 Sep 2026", "https://www.eia.gov/todayinenergy/detail.php?id=68204", ["Energy"]],
    ["h8-2026-09-25", "Bank balance sheets", "25 Sep 2026", "https://www.federalreserve.gov/releases/h8/20260925/", ["Banking & credit"]],
    ["wto-2026-09-28", "International trade", "28 Sep 2026", "https://www.wto.org/english/news_e/news26_e/envir_28sep26_501_e.htm", []],
    ["eia-tie-2026-09-30", "Energy analysis", "30 Sep 2026", "https://www.eia.gov/todayinenergy/detail.php?id=68224", ["Energy", "Manufacturing & automotive"]],
    ["wto-2026-10-05", "International trade", "5 Oct 2026", "https://www.wto.org/english/news_e/news26_e/gc_05oct26_508_e.htm", []],
    ["wto-2026-10-08", "International trade", "8 Oct 2026", "https://www.wto.org/english/news_e/news26_e/stat_08oct26_510_e.htm", []],
  ].map(([id, category, day, url, sectors]) =>
    ({ id, category, published: `${day} (date only: the source states no time)`, url, sectors })),
];
const SECTIONS = ["overview", "facts", "channels", "competing", "limits", "critique", "sources", "provenance"];
const WITH_CONTEXT = new Set(CASES.filter((item) => !item.sectors).map((item) => item.id));  // The twelve macro cases.
// The WTO entries (case-library-0.3): no sector, no market series; two report meeting proceedings and list no channels.
const TRADE = new Set(["wto-2026-09-28", "wto-2026-10-05", "wto-2026-10-08"]);
const PROCEEDINGS = new Set(["wto-2026-09-28", "wto-2026-10-05"]);
const TOTAL = CASES.length;
const TOPICS = ["Monetary policy", "Employment", "Inflation", "Energy analysis", "Export controls", "Industrial production",
                "Bank balance sheets", "International trade"];
const SECTORS = ["Energy", "Technology & semiconductors", "Manufacturing & automotive", "Banking & credit", "Mining & materials"];
const slug = (label) => label.toLowerCase().replace(/ & /g, "-").replace(/ /g, "-");
/** A case's sections: market context follows the channels on a case that declares it. */
// The two cases with a committed enrichment: what their source check must show (counts from the served checks).
const ENRICHED = {
  "bis-2026-07-10": { checks: 11, differs: ["Diversion risk and the durability of the easing"],
    flagged: ["#channels"], reference: "https://www.federalregister.gov/d/2026-14132", sources: 1,
    caseText: "BIS conditions the new status on the UAE's commitment to preventing diversion" },
  "bis-2026-02-12": { checks: 13, differs: ["Enforcement of past conduct, not a new rule", "Context: January 14, 2026"],
    flagged: ["#competing", "#sources"], reference: "https://www.bis.gov/media/2587", sources: 2,
    caseText: "Context: January 14, 2026." },
};
const sectionsOf = (id) => [...(ENRICHED[id] ? ["check"] : []),
  ...(WITH_CONTEXT.has(id) ? [...SECTIONS.slice(0, 3), "context", ...SECTIONS.slice(3)] : SECTIONS)];

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const root = mkdtempSync(join(tmpdir(), "second-order-library-check-"));
const served = join(root, "served");
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};

try {
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    "--market-context", "committed"], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  let started = false;
  for (let i = 0; i < 150 && !started; i++) {
    try { started = (await fetch(`${base}/api/case-library`)).ok; } catch { await sleep(200); }
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
  const requests = [];
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else if (message.method === "Network.requestWillBeSent") {
      requests.push(message.params.request.url);
    }
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
  const click = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.click()`);
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);
  const all = (selector, property = "textContent") =>
    evaluate(`[...document.querySelectorAll(${JSON.stringify(selector)})].map((e) => e.${property})`);
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  const viewport = (width, height, mobile) =>
    send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: mobile ? 2 : 1, mobile });
  await viewport(1280, 900, false);
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete'");
  };
  const caseShown = (id) => `location.pathname === "/library/${id}" && !!document.querySelector(".library-case h1")`;
  const pageTitle = () => text(".library-case h1");
  /** Everything a reader needs from one case, read from the page as rendered. */
  const readCase = () => evaluate(`(() => {
    const q = (s) => document.querySelector(s);
    const source = q(".library-source a.library-external");
    return {
      title: q(".library-case h1")?.textContent ?? "",
      category: q(".library-case-header .kicker")?.textContent ?? "",
      sections: [...document.querySelectorAll(".library-section-block")].map((e) => e.id),
      facts: document.querySelectorAll("#facts .library-facts tbody tr").length,
      factBases: [...document.querySelectorAll("#facts .library-facts tbody td:last-child")].every((e) => e.textContent.trim()),
      channels: [...document.querySelectorAll(".library-channel")].map((e) => ({
        fact: e.querySelector(".library-fact-side dt")?.textContent, factText: e.querySelector(".library-fact-side dd")?.textContent ?? "",
        reading: e.querySelector(".library-reading-side dt")?.textContent, readingText: e.querySelector(".library-reading-side dd")?.textContent ?? "" })),
      competing: document.querySelectorAll("#competing li").length,
      limits: [...document.querySelectorAll("#limits h3")].map((e) => e.textContent),
      limitItems: document.querySelectorAll("#limits li").length,
      critique: document.querySelectorAll(".library-critique li").length,
      critiqueNote: q("#critique .library-section-note")?.textContent ?? "",
      labels: [...document.querySelectorAll(".library-case-header .library-labels li")].map((e) => e.textContent),
      published: [...document.querySelectorAll(".library-source div")].find((d) => d.querySelector("dt")?.textContent === "Published")?.querySelector("dd")?.textContent ?? "",
      benchmark: q(".library-benchmark")?.textContent ?? "",
      provenance: q(".library-provenance")?.textContent ?? "",
      sourceHref: source?.getAttribute("href"), sourceTarget: source?.getAttribute("target"), sourceRel: source?.getAttribute("rel"),
      noteLinks: [...document.querySelectorAll("#sources a.library-external")].map((a) => a.getAttribute("href")),
      context: q("#context .context-unavailable")?.dataset.state ?? (q("#context") ? "shown" : "none"),
      contextNote: q("#context .context-unavailable")?.textContent ?? "",
      contextRows: document.querySelectorAll("#context .context-table tbody tr").length,
      contextPoints: document.querySelectorAll("#context .context-point").length,
      firstParagraph: q("#overview p:not(.kicker)")?.textContent ?? "",
      channelsTitle: q("#channels-title")?.textContent ?? "",
      sectorChips: [...document.querySelectorAll(".library-case-sectors a")].map((a) => a.textContent),
      precision: [...document.querySelectorAll(".library-source div")].find((d) => d.querySelector("dt")?.textContent === "Published")?.querySelector("dd")?.dataset.precision ?? "",
      docTitle: document.title,
    };
  })()`);

  const listed = (scope) => all(`${scope} .library-entry`, "dataset.case");
  const ids = (category, sector) => CASES.filter((item) => (!category || item.category === category) &&
    (!sector || (item.sectors ?? []).includes(sector))).map((item) => item.id);
  const filterState = () => evaluate(`({ path: location.pathname + location.search,
    query: document.querySelector("#library-search")?.value,
    pressed: [...document.querySelectorAll('.library-categories:not(.library-sectors) .library-category-button[aria-pressed="true"]')].map((b) => b.textContent),
    sectorPressed: [...document.querySelectorAll('.library-sectors .library-category-button[aria-pressed="true"]')].map((b) => b.textContent),
    count: document.querySelector(".library-result-count")?.textContent ?? "",
    scope: document.querySelector(".library-sector-scope")?.textContent ?? "",
    shown: [...document.querySelectorAll(".library-index .library-entry")].map((e) => e.dataset.case) })`);
  /** Replace the search text the way a person would: select what is there, then type over it. */
  const setSearch = async (value) => {
    await evaluate(`(() => { const input = document.querySelector("#library-search"); input.focus(); input.select(); })()`);
    await send("Input.insertText", { text: value });
  };
  const chooseCategory = (label) => evaluate(`[...document.querySelectorAll(".library-categories:not(.library-sectors) .library-category-button")]
    .find((b) => b.firstChild.textContent.trim() === ${JSON.stringify(label)})?.click()`);
  const chooseSector = (label) => evaluate(`[...document.querySelectorAll(".library-sectors .library-category-button")]
    .find((b) => b.firstChild.textContent.trim() === ${JSON.stringify(label)})?.click()`);
  const press = async (key, code, keyCode, typed) => {
    await send("Input.dispatchKeyEvent", { type: "keyDown", key, code, windowsVirtualKeyCode: keyCode, text: typed });
    await send("Input.dispatchKeyEvent", { type: "keyUp", key, code, windowsVirtualKeyCode: keyCode });
  };
  const focused = () => evaluate(`document.activeElement?.id || document.activeElement?.textContent?.trim() || ""`);
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

  // 1. Discovery: a compact Tracker section with the latest case in each topic, and links by topic and by sector.
  const latest = ["fomc-2025-06-18", "empsit-2025-07-03", "cpi-2025-07-15", "bis-2026-07-10", "g17-2026-09-18",
                  "h8-2026-09-25", "eia-tie-2026-09-30", "wto-2026-10-08"];
  await open("/");
  check("the Tracker shows a compact Case library section: the latest case in each of the eight topics",
    await waitFor(`document.querySelectorAll("#case-library .library-entry").length === 8`) &&
    same(await listed("#case-library"), latest));
  const entries = await evaluate(`[...document.querySelectorAll("#case-library .library-entry")].map((e) => ({
    category: e.querySelector(".library-category")?.textContent, meta: e.querySelector(".library-entry-meta")?.textContent,
    title: e.querySelector(".library-entry-title")?.textContent, summary: e.querySelector(".library-entry-summary")?.textContent }))`);
  check("each Tracker entry shows its title, topic, publication date and summary",
    entries.every((entry, i) => entry.category === CASES.find((item) => item.id === latest[i]).category &&
      entry.title.length > 20 && entry.summary.length > 80 && /\d{1,2} [A-Z][a-z]{2} 202[56]/.test(entry.meta)));
  const links = await evaluate(`[...document.querySelectorAll("#case-library .library-more a")]
    .map((a) => [a.textContent, a.getAttribute("href")])`);
  check("the Tracker links to the full collection, to each topic and to each sector",
    same(links, [[`Browse all ${TOTAL} cases`, "/library"],
      ...TOPICS.map((topic) => [`${topic} (${ids(topic).length})`, `/library?category=${slug(topic)}`]),
      ...SECTORS.map((sector) => [`${sector} (${ids(null, sector).length})`, `/library?sector=${slug(sector)}`])]),
    JSON.stringify(links));
  const labels = await all("#case-library .library-labels li");
  check("the collection is labelled retrospective, AI-assisted, not human-reviewed and never scored",
    labels.includes("AI-assisted editorial illustration") && labels.includes("Not human-reviewed") &&
    labels.includes("Never scored · not research evidence") && labels.includes("Retrospective"));
  check("the top bar links to the library", (await all(".site-nav a", "textContent")).includes("Library"));
  const tracker = await evaluate(`document.querySelector(".tracker")?.textContent ?? ""`);
  check("the library stays out of the Tracker's research sections, and research intake stays closed",
    (await text(".intake-closed")) === "Closed" && tracker.includes("No research cases are recorded.") &&
    entries.every((entry) => !tracker.includes(entry.title)));

  // 2. The full library: every case in publication order, then search and topic filters.
  await click('#case-library .library-more a[href="/library"]');
  check(`the full library lists all ${TOTAL} cases, oldest first`,
    await waitFor(`document.querySelectorAll(".library-index .library-entry").length === ${TOTAL}`) &&
    same(await listed(".library-index"), ids()) && (await text(".library-result-count")).startsWith(`Showing all ${TOTAL} cases`));
  check("the search is labelled for what it covers, not as full-text search",
    (await text(".library-search span")) === "Search titles, summaries, topics and publishers");
  for (const category of TOPICS) {
    await chooseCategory(category);
    await waitFor(`document.querySelector(".library-result-count")?.textContent.includes("in ${category}")`);
    const state = await filterState();
    const expected = ids(category);
    check(`topic ${category}: its ${expected.length} cases in order, a count, the control pressed and the address updated`,
      same(state.shown, expected) && state.count.startsWith(`Showing ${expected.length} of ${TOTAL} cases in ${category}`) &&
      same(state.pressed.map((label) => label.replace(/\s*\d+$/, "")), [category]) &&
      state.path === `/library?category=${slug(category)}`, JSON.stringify(state));
  }
  await chooseCategory("All");
  await setSearch("SHELTER");
  check("search is case-insensitive and covers summaries",
    await waitFor(`document.querySelectorAll(".library-index .library-entry").length === 3`) &&
    same((await filterState()).shown, ["cpi-2025-05-13", "cpi-2025-06-11", "cpi-2025-07-15"]));
  await setSearch("federal reserve");
  const fed = CASES.filter((item) => item.url.startsWith("https://www.federalreserve.gov/")).map((item) => item.id);
  check("search covers publishers, and every word must match",
    await waitFor(`document.querySelectorAll(".library-index .library-entry").length === ${fed.length}`) &&
    same((await filterState()).shown, fed), JSON.stringify(await filterState()));
  await setSearch("april");
  await chooseCategory("Inflation");
  await waitFor(`location.search === "?q=april&category=inflation"`);
  let state = await filterState();
  check("search and topic combine, and the count says so",
    same(state.shown, ["cpi-2025-05-13", "cpi-2025-06-11"]) &&
    state.count.startsWith(`Showing 2 of ${TOTAL} cases in Inflation matching “april”`), JSON.stringify(state));
  const counts = await all(".library-categories:not(.library-sectors) .library-category-count");
  check("each topic control shows how many cases it would show for the current search",
    same(counts, ["5", "1", "2", "2", "0", "0", "0", "0", "0"]), counts.join(","));

  // 3. The browsing state survives a reload and Back.
  await send("Page.reload", { ignoreCache: true });
  await waitFor(`document.querySelectorAll(".library-index .library-entry").length === 2`);
  state = await filterState();
  check("a reload restores the search, the category and the results",
    state.query === "april" && state.pressed.length === 1 && state.pressed[0].startsWith("Inflation") &&
    same(state.shown, ["cpi-2025-05-13", "cpi-2025-06-11"]), JSON.stringify(state));
  await click('.library-index .library-entry[data-case="cpi-2025-06-11"] .library-entry-title');
  await waitFor(caseShown("cpi-2025-06-11"));
  await evaluate("history.back()");
  await waitFor(`location.pathname === "/library" && document.querySelectorAll(".library-index .library-entry").length === 2`);
  state = await filterState();
  check("Back from a case returns to the same filtered list",
    state.path === "/library?q=april&category=inflation" && state.query === "april" &&
    same(state.shown, ["cpi-2025-05-13", "cpi-2025-06-11"]), JSON.stringify(state));

  // 4. No results, and resetting.
  await setSearch("unicorn");
  check("a search with no match says so, explains what is searched and offers a way back",
    await waitFor(`!!document.querySelector(".library-empty")`) &&
    (await text(".library-empty")).includes("No case matches “unicorn” in Inflation") &&
    (await text(".library-empty")).includes("not the full text") &&
    (await text(".library-result-count")).startsWith(`Showing 0 of ${TOTAL}`));
  await click(".library-empty .library-reset");
  check(`resetting shows all ${TOTAL} cases at the plain library address`,
    await waitFor(`location.pathname + location.search === "/library" &&
      document.querySelectorAll(".library-index .library-entry").length === ${TOTAL}`) &&
    (await evaluate(`document.querySelector("#library-search").value`)) === "");
  await setSearch("jobs");
  await chooseCategory("Employment");
  await waitFor(`location.search === "?q=jobs&category=employment"`);
  await click(".library-results-head .library-reset");
  check("the Clear search, topic and sector control resets them",
    await waitFor(`location.search === "" && document.querySelectorAll(".library-index .library-entry").length === ${TOTAL}`));

  // 4b. Sectors: additive membership, counts, the sector's stated coverage, combined filters and honest empties.
  for (const sector of SECTORS) {
    await chooseSector(sector);
    await waitFor(`document.querySelector(".library-result-count")?.textContent.includes("under ${sector}")`);
    const state = await filterState();
    const expected = ids(null, sector);
    check(`sector ${sector}: its ${expected.length} cases in order, the scope stated, the control pressed and the address updated`,
      expected.length >= 3 && same(state.shown, expected) &&
      state.count.startsWith(`Showing ${expected.length} of ${TOTAL} cases under ${sector}`) &&
      same(state.sectorPressed.map((label) => label.replace(/\s*\d+$/, "")), [sector]) &&
      state.scope.includes("on or before 30 September 2026") && state.scope.includes("stored once") &&
      state.path === `/library?sector=${slug(sector)}`, JSON.stringify(state));
  }
  await open("/library?sector=mining-materials");
  await waitFor(`document.querySelector(".library-sector-scope")?.dataset.sector === "mining-materials"`);
  const mining = await text(".library-sector-scope");
  check("Mining & materials states G.17's own categories, the releases it reuses and the evidence it does not hold",
    mining.includes("all industries in NAICS sector 21") && mining.includes("do not define further") &&
    mining.includes("not added as new cases") && mining.includes("no commodity or metal prices") &&
    mining.includes("mining companies' results"), mining);
  await chooseSector("All sectors");
  await waitFor(`location.search === ""`);
  const sectorCounts = await all(".library-sectors .library-category-count");
  const unfiltered = await filterState();
  check("a case in two sectors is counted under each and listed once: the sector counts exceed the total",
    same(sectorCounts, [String(TOTAL), ...SECTORS.map((sector) => String(ids(null, sector).length))]) &&
    unfiltered.shown.length === TOTAL && new Set(unfiltered.shown).size === TOTAL &&
    SECTORS.reduce((sum, sector) => sum + ids(null, sector).length, 0) > 12, sectorCounts.join(","));
  await chooseSector("Energy");
  await chooseCategory("Industrial production");
  await waitFor(`location.search === "?category=industrial-production&sector=energy"`);
  state = await filterState();
  check("a sector combines with a topic, and the count names both",
    same(state.shown, ["g17-2026-07-17", "g17-2026-09-18"]) &&
    state.count.startsWith(`Showing 2 of ${TOTAL} cases in Industrial production under Energy`), JSON.stringify(state));
  await send("Page.reload", { ignoreCache: true });
  await waitFor(`document.querySelectorAll(".library-index .library-entry").length === 2`);
  state = await filterState();
  check("a reload keeps the sector and the topic",
    same(state.shown, ["g17-2026-07-17", "g17-2026-09-18"]) && state.sectorPressed[0]?.startsWith("Energy") &&
    state.pressed[0]?.startsWith("Industrial production"), JSON.stringify(state));
  await click('.library-index .library-entry[data-case="g17-2026-09-18"] .library-entry-title');
  await waitFor(caseShown("g17-2026-09-18"));
  await evaluate("history.back()");
  await waitFor(`location.search === "?category=industrial-production&sector=energy" &&
    document.querySelectorAll(".library-index .library-entry").length === 2`);
  check("Back from a sector case returns to the same sector and topic",
    same((await filterState()).shown, ["g17-2026-07-17", "g17-2026-09-18"]));
  await chooseSector("Banking & credit");
  await chooseCategory("Export controls");
  await waitFor(`!!document.querySelector(".library-empty")`);
  const empty = await text(".library-empty");
  check("a topic and sector with no case in common say so, with counts for each on its own",
    empty.includes("No case is listed in Export controls under Banking & credit") &&
    empty.includes("3 cases match under Banking & credit in all topics") &&
    empty.includes("3 cases match in Export controls across all sectors"), empty);
  await click(".library-empty .library-reset");
  await waitFor(`location.search === ""`);
  await open("/library?sector=astrology");
  check("an address naming a sector the library does not have says so and shows every case",
    await waitFor(`document.querySelectorAll(".library-index .library-entry").length === ${TOTAL}`) &&
    (await text(".library-sector-note")).includes("“astrology”"));
  await open("/library");
  await waitFor(`document.querySelectorAll(".library-index .library-entry").length === ${TOTAL}`);
  const chips = await evaluate(`[...document.querySelectorAll('.library-entry[data-case="eia-tie-2026-09-30"] .library-sector-chips a')]
    .map((a) => [a.textContent, a.getAttribute("href")])`);
  const metaDate = await text('.library-entry[data-case="h8-2026-09-11"] .library-entry-meta [data-precision="date"]');
  check("entries show their sectors as links, and a date-only source's stated date with no time",
    same(chips, [["Energy", "/library?sector=energy"], ["Manufacturing & automotive", "/library?sector=manufacturing-automotive"]]) &&
    metaDate === "11 Sep 2026", JSON.stringify({ chips, metaDate }));
  const three = await evaluate(`[...document.querySelectorAll('.library-index .library-entry[data-case="g17-2026-08-18"]')]
    .map((e) => [...e.querySelectorAll(".library-sector-chips a")].map((a) => a.getAttribute("href")))`);
  check("a case under three sectors is one entry, with a link to each sector",
    same(three, [["/library?sector=manufacturing-automotive", "/library?sector=technology-semiconductors",
                  "/library?sector=mining-materials"]]), JSON.stringify(three));

  // 5. Keyboard: type in the search, Tab to a category, activate it, and open a case with Enter.
  await evaluate(`document.querySelector("#library-search").focus()`);
  await send("Input.insertText", { text: "revised" });
  for (let i = 0; i < 3; i++) await press("Tab", "Tab", 9);
  const onEmployment = (await focused()).startsWith("Employment");
  await press("Enter", "Enter", 13, "\r");
  check("the search and category controls work from the keyboard",
    onEmployment && await waitFor(`location.search === "?q=revised&category=employment"`) &&
    same((await filterState()).shown, ids("Employment")));
  await evaluate(`document.querySelector(".library-index .library-entry-title").focus()`);
  await press("Enter", "Enter", 13, "\r");
  check("a case opens from the keyboard", await waitFor(caseShown("empsit-2025-04-04")));

  // 6. Every case reads in full; previous and next walk the collection in publication order.
  await open(`/library/${CASES[0].id}`);
  const seen = [];
  for (const [i, expected] of CASES.entries()) {
    const shown = await waitFor(caseShown(expected.id)) &&
      (!WITH_CONTEXT.has(expected.id) || await waitFor(`!!document.querySelector("#context .context-table")`)) &&
      (!ENRICHED[expected.id] || await waitFor(`!!document.querySelector("#check .enrichment-panel")`));
    const read = await readCase();
    seen.push(read);
    check(`${expected.id}: opens with all ${sectionsOf(expected.id).length} sections, as case ${i + 1} of ${TOTAL}`,
      shown && read.category === expected.category && same(read.sections, sectionsOf(expected.id)) &&
      read.docTitle.includes(read.title) && (await text(".library-crumbs span")) === `Case ${i + 1} of ${TOTAL}`,
      JSON.stringify(read.sections));
    if (PROCEEDINGS.has(expected.id)) {
      check(`${expected.id}: facts with their basis, and no invented channels for meeting proceedings`,
        read.facts >= 4 && read.factBases && read.channels.length === 0 &&
        (await text("#channels")).includes("None: this entry reports meeting proceedings") &&
        (await text("#channels")).includes("does not show that none was taken elsewhere"));
    } else {
      check(`${expected.id}: facts with their basis, and channels that separate the source from interpretation`,
        read.facts >= 4 && read.factBases && read.channels.length >= 2 &&
        read.channels.every((c) => c.fact === "From the release" && c.reading === "Conditional interpretation" &&
          c.factText.length > 30 && c.readingText.length > 80), JSON.stringify(read.channels.map((c) => c.fact)));
    }
    check(`${expected.id}: competing explanations, assumptions, gaps, weakening observations and critique`,
      read.competing >= 1 && read.limits.join("|") === "Assumptions|Missing information|What would weaken this interpretation" &&
      read.limitItems >= 6 && read.critique >= 3 && read.critiqueNote.includes("not a saved human review"));
    check(WITH_CONTEXT.has(expected.id)
      ? `${expected.id}: market context from the committed bundle, 29 dated rows, labelled description only`
      : `${expected.id}: no market context section, and the case says why no market series is attached`,
      WITH_CONTEXT.has(expected.id)
        ? read.context === "shown" && read.contextRows === 29 && read.contextPoints >= 38 &&
          read.benchmark.includes("description only") && read.channelsTitle === "Possible channels to Treasury yields"
        : TRADE.has(expected.id)
          ? read.context === "none" && read.contextRows === 0 &&
            read.benchmark.includes("This case shows no market data, chart or outcome.") &&
            !read.benchmark.includes("sectors") &&
            read.channelsTitle === (PROCEEDINGS.has(expected.id) ? "Transmission channels" : "Possible transmission channels")
          : read.context === "none" && read.contextRows === 0 &&
            read.benchmark.includes("Treasury yields do not measure activity in this case's sectors") &&
            read.benchmark.includes("This case shows no market data, chart or outcome.") &&
            read.channelsTitle === "Possible transmission channels",
      `${read.context} | ${read.contextRows} | ${read.channelsTitle} | ${read.benchmark}`);
    if (TRADE.has(expected.id)) {
      const provenance = await text("#provenance");
      check(`${expected.id}: its date basis and retained copy are stated, the copy is not served, and it has no sector`,
        same(read.sectorChips, []) && read.precision === "date" && provenance.includes("Date basis.") &&
        provenance.includes("Kept privately, not served") && provenance.includes("wto-trade-sources-01") &&
        provenance.includes("None: not reviewed by a person"));
    } else if (expected.sectors) {
      check(`${expected.id}: its sectors link back to the library, and its date is shown as date only`,
        same(read.sectorChips, expected.sectors) && read.precision === "date", JSON.stringify(read.sectorChips));
    }
    if (ENRICHED[expected.id]) {
      const want = ENRICHED[expected.id];
      const panel = await evaluate(`(() => {
        const q = (s) => document.querySelector(s);
        return {
          note: q("#check .library-section-note")?.textContent ?? "",
          differs: [...document.querySelectorAll("#check .enrichment-discrepancies li strong")].map((e) => e.textContent),
          summary: q("#check .enrichment-summary")?.textContent ?? "",
          aspects: [...document.querySelectorAll("#check .enrichment-readout tbody th")].map((e) => e.textContent),
          statuses: [...document.querySelectorAll("#check .enrichment-readout li")].map((e) => e.dataset.status),
          chain: q("#check .enrichment-chain")?.textContent ?? "",
          references: [...document.querySelectorAll("#check .enrichment-references a")].map((a) => a.getAttribute("href")),
          comparison: q("#check .enrichment-comparison-link a")?.getAttribute("href") ?? "",
          checks: document.querySelectorAll("#check .enrichment-checks tbody tr").length,
          copies: [...document.querySelectorAll("#check .enrichment-source-ledger")].map((e) => e.textContent),
          flags: [...document.querySelectorAll(".enrichment-flag")].map((a) => [a.closest(".library-section-block")?.id,
            a.getAttribute("href")]),
          collapsed: [...document.querySelectorAll("#check details")].every((d) => !d.open),
          caseText: document.querySelector(".library-body")?.textContent ?? "",
        };
      })()`);
      check(`${expected.id}: a source check and reading aid comes first, says the case is unchanged and is historical`,
        panel.note.includes("The case's own text, provenance and review status below are unchanged") &&
        panel.note.includes("not current rules or legal guidance") && panel.collapsed, panel.note);
      check(`${expected.id}: each discrepancy is listed prominently and flagged where the claim appears`,
        same(panel.differs, want.differs.map((label) => `${label}.`)) &&
        same(panel.flags, want.flagged.map((section) => [section.slice(1), "#check"])) &&
        panel.caseText.includes(want.caseText), JSON.stringify(panel.flags));
      check(`${expected.id}: ${want.checks} claims checked, with counts, statuses and the chain as the curator's reading`,
        panel.checks === want.checks && panel.summary.startsWith(`${want.checks} claims of this case were checked`) &&
        same(panel.aspects, ["Instrument", "Scope", "Timing", "Conditions"]) &&
        panel.statuses.includes("stated") && panel.statuses.includes("not_stated") &&
        panel.chain.includes("Curator's reading, not BIS's wording"), panel.summary);
      check(`${expected.id}: unread references are named, not followed, and the historical comparison links to its case`,
        same(panel.references, [want.reference]) && panel.comparison === "/library/historical/bis-2022-10-07",
        JSON.stringify(panel.references));
      check(`${expected.id}: its ${want.sources} retained source(s) are recorded, not served, and absent on this machine`,
        panel.copies.length === want.sources &&
        panel.copies.every((text) => text.includes("Kept privately, not served") && text.includes("bis-semis-sources-01") &&
          text.includes("Not on this machine")), JSON.stringify(panel.copies.length));
    }
    check(`${expected.id}: labelled as unreviewed AI-assisted retrospective work, with no surprise claimed`,
      read.labels.includes("AI-assisted editorial illustration") && read.labels.includes("Not human-reviewed") &&
      read.labels.some((label) => label.startsWith("Prepared after publication")) &&
      read.benchmark.includes("does not say whether the release was a surprise") &&
      read.provenance.includes("not reviewed by a person") && read.provenance.includes("Claude Opus 5.5"));
    check(`${expected.id}: ${expected.sectors ? "the stated publication date only" : "publication time in the publisher's offset"}, and the official source link`,
      read.published === expected.published && read.sourceHref === expected.url && read.sourceTarget === "_blank" &&
      read.sourceRel === "noreferrer", `${read.published} | ${read.sourceHref}`);
    if (i < CASES.length - 1) await click('.library-pager a[rel="next"]');
  }
  check(`the ${TOTAL} cases are genuinely different readings`,
    new Set(seen.map((read) => read.firstParagraph)).size === TOTAL && new Set(seen.map((read) => read.title)).size === TOTAL);
  const employment = seen.filter((read, i) => CASES[i].category === "Employment");
  check("every jobs case discloses its later revisions with official links to the later releases",
    employment.every((read) => read.noteLinks.some((href) => href.includes("/empsit_"))));
  check("the last case offers the previous case and no next one",
    await evaluate(`!document.querySelector('.library-pager a[rel="next"]') && !!document.querySelector('.library-pager a[rel="prev"]')`));
  await click('.library-pager a[rel="prev"]');
  check("previous moves back a case", await waitFor(caseShown(CASES[TOTAL - 2].id)));
  await evaluate("history.back()");
  check("the browser's Back button returns to the case before", await waitFor(caseShown(CASES[TOTAL - 1].id)));
  await click(".library-case-category");
  check("a case's topic links to that topic in the library",
    await waitFor(`location.search === "?category=international-trade" && document.querySelectorAll(".library-index .library-entry").length === 3`));
  await open("/library/bis-2026-06-17");
  await waitFor(caseShown("bis-2026-06-17"));
  await click('.library-case-sectors a[href="/library?sector=manufacturing-automotive"]');
  check("a case's sector links to that sector in the library",
    await waitFor(`location.search === "?sector=manufacturing-automotive" &&
      document.querySelectorAll(".library-index .library-entry").length === ${ids(null, "Manufacturing & automotive").length}`));

  // 7. A reissued release says so; direct reloads; an unknown case.
  await open("/library/empsit-2025-05-02");
  await waitFor(caseShown("empsit-2025-05-02"));
  check("the reissued April jobs release discloses its reissue and later page date",
    (await text("#sources")).includes("Reissued June 3, 2025") && (await text(".library-provenance")).includes("2025-06-03"));
  await send("Page.reload", { ignoreCache: true });
  check("a direct reload of a case shows it again", await waitFor(caseShown("empsit-2025-05-02")) &&
    (await pageTitle()) === seen[4].title);
  await click('.site-nav a[href="/"]');
  check("the Tracker is one click away and still shows the library section",
    await waitFor(`location.pathname === "/" && document.querySelectorAll("#case-library .library-entry").length === 8`));
  await open("/library/no-such-case");
  check("an unknown case is reported within the app, with a way back",
    await waitFor(`document.querySelector("#missing-case-title")?.textContent === "There is no case at this address"`) &&
    await evaluate(`!!document.querySelector('.state-panel a[href="/library"]')`));

  // 8. Narrow screens: no sideways scrolling, readable text, usable controls, facts stacked.
  await viewport(375, 812, true);
  const narrow = ["/", "/library", "/library?q=april&category=employment", "/library?sector=energy",
                  ...CASES.map((item) => `/library/${item.id}`)];
  for (const path of narrow) {
    await open(path);
    await waitFor(path === "/" ? `document.querySelectorAll("#case-library .library-entry").length === 7`
      : path === "/library?sector=energy" ? `document.querySelectorAll(".library-index .library-entry").length === ${ids(null, "Energy").length}`
      : path.startsWith("/library?") ? `document.querySelectorAll(".library-index .library-entry").length === 2`
      : path === "/library" ? `document.querySelectorAll(".library-index .library-entry").length === ${TOTAL}`
      : `!!document.querySelector(".library-case h1")`);
    await sleep(700);  // Let the entrance animation and web fonts settle before measuring.
    const layout = await evaluate(`(() => {
      const wide = [...document.querySelectorAll("body *")].filter((e) => e.getBoundingClientRect().right > innerWidth + 1)
        .map((e) => e.tagName + "." + e.className).slice(0, 3);
      const sizes = [...document.querySelectorAll(".library-section-block p:not(.kicker), .library-points li, .library-entry-summary, .library-channel dd")]
        .map((e) => parseFloat(getComputedStyle(e).fontSize));
      const buttons = [...document.querySelectorAll(".library-category-button")].map((b) => b.getBoundingClientRect().height);
      const facts = document.querySelector(".library-facts tbody tr");
      return { scroll: document.documentElement.scrollWidth, width: innerWidth, wide, smallest: Math.min(...sizes),
               shortestButton: buttons.length ? Math.min(...buttons) : 44,
               stacked: facts ? getComputedStyle(facts).display === "block" : true };
    })()`);
    check(`narrow screen ${path}: no sideways scrolling, text at least 14px, 44px controls, facts stacked`,
      layout.scroll <= layout.width && layout.wide.length === 0 && layout.smallest >= 14 && layout.shortestButton >= 44 &&
      layout.stacked, JSON.stringify(layout));
  }

  const outside = requests.filter((url) => !url.startsWith(base) && !url.startsWith("data:") && url !== "about:blank");
  check("browsing the library requested nothing outside the local server", outside.length === 0, outside.join(", "));
  ws.close();
} catch (error) {
  check("the library browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(500);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
