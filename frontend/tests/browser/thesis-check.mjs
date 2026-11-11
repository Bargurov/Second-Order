// Browser check of the thesis page, against tests/review_browser_server.py serving a new, empty folder with
// --thesis synthetic (SYNTHETIC retained sources and a SYNTHETIC thesis, version 1 published and version 2 a draft;
// see tests/thesis_fakes.py), or, as an explicit opt-in, SECOND_ORDER_THESIS_SOURCES=<the retained
// data/sector-sources/copper folder> (the committed content/theses against the real retained sources, served
// read-only; the steps that remove a retained folder run only on the synthetic copy; a relative path is read from
// the repository, as the review server reads it, and a missing folder is refused). It checks:
// - discovery from the case library: the thesis is listed above the research views with its topic, version and state,
//   and the listing states the check at its scope (each source against its acquisition record; a figure transcribed
//   from a PDF bound by its SHA-256 only), never that every figure is checked;
// - each balance table's figure list says where each figure is cited, never that it was found;
// - each balance table's demand and supply rows named by the measure their figures state, never a fixed "Total
//   supply" (with the real sources: IEA base-case mine supply, and United States reported refined consumption and
//   refinery output), and no row name cut off on a 390 px wide screen;
// - all 12 sections in order, each section's plain note under its heading, and the Sources footer (state, edition,
//   terms, retrieval and, for a PDF, the pages transcribed);
// - the header (topic, opening date, last update, confidence, the line "A research view, not a recommendation to buy
//   or sell") and the draft banner;
// - every reason's and risk's status, change and what moved it last, and which comparison it makes: two years within
//   one edition (both figures from one source) or two editions (ruling R12), worded from the reply's own fields, and
//   the exact rule its status is read by, in the reply's own status words, with the change shown rounded and the status
//   read from the exact figures;
// - a computed gap with its sign and weeks of demand, and a table that does not compute one saying why;
// - the exposure computed row (cost per unit and share of the unit price);
// - the price record's rows ("Latest retained when the thesis opened", "Latest retained"), and every figure and passage
//   line naming its source by publisher and edition, with its title where two listed sources share both;
// - version 1 against version 2 through the versions switcher: the log is extended, never rewritten;
// - (synthetic) with the usgs-2025 folder removed: its reason is unavailable, shows its problems in place of its
//   status, and none of its numbers is on the page; restoring the folder restores the reason and its number;
// - a version that does not exist says so;
// - reads write nothing; only GET requests, to the local server only; no page errors (each attributed to its URL);
// - a 390 px wide screen without sideways scrolling;
// - page chrome free of affirmative recommendation and price-direction phrasings, compared case-insensitively (innerText
//   reflects CSS text-transform). The scan looks for the affirmative phrasings, not bare stems, because the header's
//   line names what it denies; text that is the served reply's own wording is set aside first (payload provenance).
//
//   cd frontend; npm run build; npm run test:browser:thesis
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync, rmSync, statSync, writeFileSync }
  from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const python = process.env.SECOND_ORDER_PYTHON ?? "python";
// The review server starts in the repository, so a relative opt-in path names the folder there (see
// policy-research-check.mjs); this script reads the same folder.
const realSources = process.env.SECOND_ORDER_THESIS_SOURCES
  ? resolve(repo, process.env.SECOND_ORDER_THESIS_SOURCES) : undefined;
const chromePath = [process.env.SECOND_ORDER_CHROME, "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
  "/usr/bin/chromium-browser"].find((path) => path && existsSync(path));
if (!chromePath) throw new Error("Chrome was not found; set SECOND_ORDER_CHROME to its executable.");
if (!existsSync(join(repo, "frontend/dist/index.html"))) throw new Error("Build the client first: npm run build");
if (realSources && !existsSync(realSources)) throw new Error("SECOND_ORDER_THESIS_SOURCES names no folder.");

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => { const { port } = server.address(); server.close(() => done(port)); });
});
const root = mkdtempSync(join(tmpdir(), "second-order-thesis-check-"));
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
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];  // As format.ts.
const utcDay = (iso) => { const d = new Date(iso); return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`; };
const day = (value) => utcDay(`${value}T00:00:00Z`);
const lower = (value) => value.toLowerCase().replace(/\s+/g, " ");
/** Every string the reply serves, wherever it sits. */
const strings = (value, out = []) => {
  if (typeof value === "string") out.push(value);
  else if (Array.isArray(value)) value.forEach((item) => strings(item, out));
  else if (value && typeof value === "object") Object.values(value).forEach((item) => strings(item, out));
  return out;
};
/** Every figure the reply shows, wherever it sits. */
const figures = (value, out = []) => {
  if (Array.isArray(value)) value.forEach((item) => figures(item, out));
  else if (value && typeof value === "object") {
    if (typeof value.as_shown === "string" && typeof value.source === "string") out.push(value);
    Object.values(value).forEach((item) => figures(item, out));
  }
  return out;
};
/** Every passage the reply shows, wherever it sits. */
const passages = (value, out = []) => {
  if (Array.isArray(value)) value.forEach((item) => passages(item, out));
  else if (value && typeof value === "object") {
    if (typeof value.quote === "string" && typeof value.where === "string" && typeof value.source === "string" &&
      !("as_shown" in value)) out.push(value);
    Object.values(value).forEach((item) => passages(item, out));
  }
  return out;
};

// Affirmative recommendation and price-direction phrasings. Each is a phrasing that asserts, never a bare stem: the
// header's line "not a recommendation to buy or sell" names what it denies and must pass.
const AFFIRMATIVE = [
  /\b(?:we|i) (?:recommend|suggest|advise)\b/,
  /(?<!not a )\brecommendation to (?:buy|sell|hold)\b/,
  /\brecommends? (?:buying|selling|holding|a (?:buy|sell))\b/,
  /\b(?:should|must|time to|consider) (?:buy|sell)(?:ing)?\b/,
  /\b(?:buy|sell|hold) (?:signal|rating|now|call)\b/,
  /\bstrong (?:buy|sell)\b/,
  /\bgo (?:long|short)\b/,
  /\b(?:over|under)weight\b/,
  /\b(?:out|under)perform/,
  /\bprice target (?:of|is)\b/,
  /\btarget price\b/,
  /\bprices? (?:will|would|should|could|may|is likely to|are likely to|is set to|are set to|is expected to|are expected to) (?:rise|fall|climb|drop|increase|decrease|go up|go down|move up|move down)\b/,
  /\bprices? (?:rises?|rising|falls?|falling|climbs?|climbing|drops?|dropping|rall(?:y|ies)|surges?|slumps?|spikes?)\b/,
  /\b(?:higher|lower|rising|falling) (?:copper )?prices?\b/,
  /\b(?:upside|downside)\b/,
  /\b(?:bullish|bearish)\b/,
  /\b(?:upward|downward|price) pressure\b/,
  /\btighter than the price\b/,
];
const affirmative = (text) => AFFIRMATIVE.filter((pattern) => pattern.test(lower(text))).map(String);
/** The page's own words: its text with every multi-word string of the served replies set aside. */
const chromeOf = (pageText, ...replies) => {
  let rest = lower(pageText);
  const served = [...new Set(replies.flatMap((reply) => strings(reply)))].filter((value) => /\s/.test(value.trim()))
    .map(lower).sort((a, b) => b.length - a.length);
  for (const value of served) rest = rest.split(value).join(" ¦ ");
  return rest;
};

const LISTING_SCOPE = "Each source is checked against its acquisition record when the thesis is opened; figures " +
  "transcribed from a PDF are bound to it by its SHA-256 only.";
const SECTIONS = ["header", "view", "balance", "differs", "reasons", "risks", "conditions", "exposure", "log", "price",
  "plain", "not-claimed"];
const PLAIN = { view: "view", balance: "balance", differs: "differs", reasons: "reasons", risks: "risks",
  conditions: "conditions", exposure: "exposure", log: "log", price: "price" };  // Section -> its plain note's key.
const scenario = ["--thesis", realSources ?? "synthetic"];
const content = realSources ? join(repo, "content/theses") : join(served, "theses");
const sources = realSources ?? join(served, "thesis-sources");

async function startServer(port) {
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    ...scenario], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  for (let i = 0; i < 300; i++) {
    try { if ((await fetch(`http://127.0.0.1:${port}/api/theses`)).ok) return server; } catch { /* starting */ }
    await sleep(200);
  }
  throw new Error("The review server did not start.");
}

try {
  check("the phrasing scan flags affirmative phrasings and passes the line that names what it denies",
    affirmative("A research view, not a recommendation to buy or sell").length === 0 &&
    affirmative("Not claimed: no price target, price forecast or trade.").length === 0 &&
    ["We recommend buying producers", "This is a recommendation to buy", "PRICES WILL RISE", "the upside case",
      "time to sell", "go long copper", "price pressure builds", "Strong buy"].every((phrase) => affirmative(phrase).length > 0));

  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const getJson = async (path) => (await fetch(`${base}${path}`)).json();
  await startServer(port);
  const contentBefore = tree(content);
  const sourcesBefore = tree(sources);

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
  const errors = [];  // { text, url }: every error attributed to its source before any is judged.
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
  const q = JSON.stringify;
  const text = (selector) => evaluate(`document.querySelector(${q(selector)})?.textContent ?? ""`);
  const inner = (selector) => evaluate(`document.querySelector(${q(selector)})?.innerText ?? ""`);
  const count = (selector) => evaluate(`document.querySelectorAll(${q(selector)}).length`);
  const navigate = (path) => send("Page.navigate", { url: `${base}${path}` });
  const loaded = (id, version) => `!!document.querySelector('article.thesis[data-thesis=${q(id)}][data-version="${version}"] h1')`;
  const chromeClean = async (name, ...replies) => {
    const found = affirmative(chromeOf(await inner("body"), ...replies));
    check(`${name}: the page's own words make no recommendation and state no price direction`, found.length === 0,
      found.join(", "));
  };
  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("Log.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  // 1. Discovery from the case library.
  const catalog = await getJson("/api/theses");
  const entry = catalog.theses?.[0];
  if (!entry) throw new Error("The server lists no thesis.");
  const id = entry.id;
  await navigate("/library");
  await waitFor(`!!document.querySelector("#theses a.library-entry-title")`);
  const listed = await evaluate(`(() => { const s = document.querySelector("#theses");
    const a = s.querySelector("a.library-entry-title"); const r = document.querySelector("#research-views");
    return { href: a.getAttribute("href"), title: a.textContent, text: s.innerText,
      above: !r || !!(s.compareDocumentPosition(r) & Node.DOCUMENT_POSITION_FOLLOWING) }; })()`);
  check("the case library lists the thesis above the research views, with its topic, version and state",
    listed.href === `/theses/${id}` && listed.title === entry.title && listed.text.includes(entry.topic) &&
    lower(listed.text).includes(`version ${entry.latest_version}`) && listed.above &&
    (entry.published_on === null ? lower(listed.text).includes("draft") : lower(listed.text).includes(lower(day(entry.published_on)))),
    JSON.stringify(listed));
  const listFound = affirmative(chromeOf(await inner("#theses"), catalog));
  check("the library listing makes no recommendation and states no price direction", listFound.length === 0,
    listFound.join(", "));
  // The check at its actual scope: each source against its acquisition record; a PDF figure is never read, only bound to
  // the PDF by its SHA-256. The listing must not say that every figure is checked against its source.
  check("the listing states the check at its scope: sources against their records, PDF figures bound by SHA-256 only",
    lower(listed.text).includes(lower(LISTING_SCOPE)) && !/each figure is checked|every figure is checked/.test(lower(listed.text)),
    listed.text);
  await evaluate(`document.querySelector("#theses a.library-entry-title").click()`);
  const latest = await getJson(`/api/theses/${id}`);
  check("opening it shows the thesis at its latest version",
    await waitFor(`location.pathname === ${q(`/theses/${id}`)} && ${loaded(id, latest.version)}`) &&
    (await text("article.thesis h1")) === latest.title);

  // 2. The 12 sections in order, their plain notes and the Sources footer.
  const sections = await evaluate(`[...document.querySelectorAll("[data-thesis-section]")].map((e) => e.dataset.thesisSection)`);
  check("the page shows the 12 sections in order", same(sections, SECTIONS), JSON.stringify(sections));
  const plain = await evaluate(`Object.fromEntries([...document.querySelectorAll("[data-thesis-section]")].map((e) =>
    [e.dataset.thesisSection, [...e.children].find((c) => c.matches(".thesis-plain"))?.querySelector(".thesis-plain-text")?.textContent ?? null]))`);
  check("each section's plain note is shown under its heading",
    Object.entries(PLAIN).every(([section, key]) => plain[section] === latest.plain[key]), JSON.stringify(plain));
  const gathered = await text("#plain");
  check("the plain-language notes gather every section's note and every reason's and risk's line",
    Object.values(latest.plain).every((note) => gathered.includes(note)) &&
    [...latest.reasons, ...latest.risks].every((item) => gathered.includes(item.plain)));
  const notClaimed = await evaluate(`[...document.querySelectorAll("#not-claimed li")].map((li) => li.textContent)`);
  check("the claims not made are listed", same(notClaimed, latest.not_claimed), JSON.stringify(notClaimed));
  const footer = await evaluate(`[...document.querySelectorAll("footer#sources [data-source]")].map((li) =>
    ({ id: li.dataset.source, state: li.dataset.state, text: li.innerText }))`);
  const transcribed = (source) => source.transcription
    ? `${source.transcription.method} (page${source.transcription.pages.length > 1 ? "s" : ""} ${source.transcription.pages.join(", ")} of the PDF)` : null;
  check("the Sources footer shows each source's state, edition, terms and retrieval, and a PDF's transcribed pages",
    footer.length === latest.sources.length && footer.every((row, index) => {
      const source = latest.sources[index];
      const transcription = transcribed(source);
      return row.id === source.id && row.state === source.state && row.text.includes(source.publisher) &&
        row.text.includes(source.edition) && row.text.includes(latest.labels.source_states[source.state]) &&
        row.text.includes(source.terms.licence) && row.text.includes(source.terms.note) &&
        !lower(row.text).includes("dated") && lower(row.text).includes("retrieved") && row.text.includes(utcDay(source.retrieved_at)) &&
        (transcription === null ? !lower(row.text).includes("transcribed from")
          : lower(row.text).includes(lower(transcription)));
    }) && latest.sources.some((source) => source.transcription !== null), JSON.stringify(footer.slice(0, 2)));

  // 3. The header and the draft banner.
  const header = await inner("[data-thesis-section=header]");
  check("the header shows the topic, opening date, last update and confidence, and the research-view line",
    header.includes(latest.topic) && header.includes(day(latest.opened_on)) &&
    (latest.published_on ? header.includes(day(latest.published_on)) : lower(header).includes("not published")) &&
    lower(header).includes(latest.confidence.level) && header.includes(latest.confidence.basis) &&
    lower(header).includes("a research view, not a recommendation to buy or sell"), header);
  const banner = lower(await inner(".thesis-draft"));
  check(latest.draft ? "a draft carries the banner \"Draft: not yet approved by the owner\"" : "a published version has no draft banner",
    latest.draft ? banner === "draft: not yet approved by the owner" : banner === "", banner);

  // 4. Reasons and risks: status, change and what moved it last.
  const claims = await evaluate(`[...document.querySelectorAll("[data-reason], [data-risk]")].map((card) =>
    ({ id: card.dataset.reason ?? card.dataset.risk, state: card.dataset.state,
      status: card.querySelector("[data-status-of]")?.dataset.statusOf ?? null,
      change: card.querySelector(".thesis-change")?.textContent ?? null, text: card.innerText }))`);
  const claimsOk = [...latest.reasons, ...latest.risks].every((item, index) => {
    const card = claims[index];
    if (!card || card.id !== item.id || card.state !== item.state) return false;
    if (item.state !== "available") return card.status === null && card.change === null;
    const moved = item.moved_by === null || (card.text.includes(`${item.moved_by.publisher} ${item.moved_by.edition}`) &&
      !lower(card.text).includes("the edition of") && !card.text.includes(day(item.moved_by.edition_date)));
    return card.status === item.status && moved &&
      (item.change_pct === null ? card.change === null : card.change.includes(`${item.change_pct.replace(/^(?!-)/, item.change_pct === "0.0" ? "" : "+")}%`));
  });
  check("every reason and risk shows its status, its change and what moved it last", claims.length ===
    latest.reasons.length + latest.risks.length && claimsOk, JSON.stringify(claims.map(({ text: _, ...rest }) => rest)));
  if (!realSources) {
    check("the synthetic statuses read strengthening, unchanged, weakening, strengthening; materialising, receding, " +
      "not tracked", same(claims.map((card) => card.status), ["strengthening", "unchanged", "weakening", "strengthening",
      "materialising", "receding", "not_tracked"]));
  }
  // Which comparison each measure makes (ruling R12), derived here from the reply independently of the page's code.
  const comparisons = await evaluate(`Object.fromEntries([...document.querySelectorAll("[data-reason], [data-risk]")]
    .map((card) => { const shown = card.querySelector("[data-comparison]");
      return [card.dataset.reason ?? card.dataset.risk, shown && { kind: shown.dataset.comparison, text: shown.textContent }]; }))`);
  const sourceNamed = (sourceId) => latest.sources.find((source) => source.id === sourceId);
  const comparisonOf = ({ latest: l, previous: p, compare }) => {
    const [newer, older] = [sourceNamed(l.source), sourceNamed(p.source)];
    if (l.source === p.source) {
      return { kind: "one-edition", text: `Compares ${l.year} with ${p.year} within the same edition (${newer.publisher}, ${newer.edition})` };
    }
    return { kind: "two-editions", text: compare === "revision"
      ? `Compares the ${newer.edition} edition with the ${older.edition} edition, both for ${l.year}`
      : `Compares ${l.year} in the ${newer.edition} edition with ${p.year} in the ${older.edition} edition` };
  };
  check("every measured reason and risk says whether it compares two years within one edition or two editions",
    [...latest.reasons, ...latest.risks].every((item) => (item.state === "available" && item.measure !== null
      ? same(comparisons[item.id], comparisonOf(item.measure)) : comparisons[item.id] === null)), JSON.stringify(comparisons));
  if (!realSources) {
    check("the synthetic same-edition reason reads \"Compares 2035 with 2030 within the same edition (Synthetic IEA, 2026)\"" +
      " and a two-edition reason \"Compares the 2026 edition with the 2025 edition, both for 2030\"",
      same(comparisons["total-demand-rising"],
        { kind: "one-edition", text: "Compares 2035 with 2030 within the same edition (Synthetic IEA, 2026)" }) &&
      same(comparisons["clean-tech-demand"],
        { kind: "two-editions", text: "Compares the 2026 edition with the 2025 edition, both for 2030" }),
      JSON.stringify([comparisons["total-demand-rising"], comparisons["clean-tech-demand"]]));
  }
  // The rule each status is read by, with its exact conditions (strictly less than the material change in either
  // direction is unchanged; at least it, one way or the other, is a change) and the reply's own status words, and that
  // the change shown is rounded while the status is read from the exact figures.
  const readAs = await evaluate(`Object.fromEntries([...document.querySelectorAll("[data-reason], [data-risk]")]
    .map((card) => [card.dataset.reason ?? card.dataset.risk, card.querySelector("[data-read-as]")?.textContent ?? null]))`);
  const ROUNDED = " The change is shown rounded to one decimal; the status is read from the exact figures.";
  const ruleOf = (measure, risk) => {
    const labels = risk ? latest.labels.risk_states : latest.labels.reason_states;
    const word = (key) => labels[key].split(":")[0];
    const [toward, away] = risk ? ["materialising", "receding"] : ["strengthening", "weakening"];
    const wanted = risk ? measure.grows_when : measure.supports_when;
    const x = `${measure.material_change_pct}%`;
    return `A change of less than ${x} in either direction reads as ${word("unchanged")}; ${word(toward)} when the ` +
      `latest figure is ${wanted} than the previous one by at least ${x}, ${word(away)} when it is ` +
      `${wanted === "higher" ? "lower" : "higher"} by at least ${x}.${ROUNDED}`;
  };
  check("every measured reason and risk states the rule its status is read by, exactly",
    [...latest.reasons.map((item) => [item, false]), ...latest.risks.map((item) => [item, true])].every(([item, risk]) =>
      (item.state === "available" && item.measure !== null ? readAs[item.id] === ruleOf(item.measure, risk)
        : readAs[item.id] === null)), JSON.stringify(readAs));
  if (!realSources) {
    check("the synthetic rules read exactly, for a reason that needs a higher figure, one that needs a lower one, and a risk",
      readAs["clean-tech-demand"] === "A change of less than 5% in either direction reads as Unchanged; Strengthening " +
        `when the latest figure is higher than the previous one by at least 5%, Weakening when it is lower by at least 5%.${ROUNDED}` &&
      readAs["mine-supply-slow"] === "A change of less than 2% in either direction reads as Unchanged; Strengthening " +
        `when the latest figure is lower than the previous one by at least 2%, Weakening when it is higher by at least 2%.${ROUNDED}` &&
      readAs["primary-supply-projections"] === "A change of less than 1% in either direction reads as Unchanged; " +
        "Materialising when the latest figure is higher than the previous one by at least 1%, Receding when it is lower " +
        `by at least 1%.${ROUNDED}`, JSON.stringify(readAs));
  }

  // 5. A computed gap and its weeks; a table that does not compute one says why.
  const tables = await evaluate(`[...document.querySelectorAll("[data-table]")].map((t) => ({ id: t.dataset.table,
    gaps: Object.fromEntries([...t.querySelectorAll("[data-gap-year]")].map((c) => [c.dataset.gapYear, c.textContent])),
    weeks: Object.fromEntries([...t.querySelectorAll("[data-weeks-year]")].map((c) => [c.dataset.weeksYear, c.textContent])),
    years: [...t.querySelectorAll("thead [data-year]")].map((c) => c.dataset.year), text: t.innerText }))`);
  const computed = latest.balance.tables.filter((table) => table.state === "available" && table.gap === "computed");
  // The synthetic thesis always computes a gap. Real content may have no table that can compute one (the sources give
  // no common basis); then the page must show no gap or weeks cell anywhere, which is checked instead.
  if (realSources && computed.length === 0) check("no table computes a gap, and the page shows no gap or weeks",
    tables.every((item) => Object.keys(item.gaps).length === 0 && Object.keys(item.weeks).length === 0),
    JSON.stringify(tables.map(({ text: _, ...rest }) => rest)));
  else check("a computed gap shows supply less demand with its sign, and its weeks of demand", computed.length > 0 &&
    computed.every((table) => {
      const shown = tables.find((item) => item.id === table.id);
      return shown && same(shown.years, table.rows.map((row) => row.year)) && table.rows.every((row) =>
        shown.gaps[row.year]?.includes(row.gap) && lower(shown.gaps[row.year]).includes(row.label) &&
        shown.weeks[row.year]?.includes(row.weeks));
    }), JSON.stringify(tables.map(({ text: _, ...rest }) => rest)));
  if (!realSources) {
    const steps = tables.find((item) => item.id === "balance-steps");
    check("the synthetic computed table shows a deficit of -500 kt in 2025, 1.0 weeks of demand",
      steps && steps.gaps["2025"].includes("-500") && lower(steps.gaps["2025"]).includes("deficit") &&
      steps.weeks["2025"].includes("1.0"));
  }
  const notComputed = latest.balance.tables.filter((table) => table.state === "available" && table.gap === "not_computed");
  check("a table that does not compute a gap shows none and says why", notComputed.every((table) => {
    const shown = tables.find((item) => item.id === table.id);
    return shown && Object.keys(shown.gaps).length === 0 && shown.text.includes(table.why_not);
  }));
  // A transcribed PDF figure is cited, never found: each table's figure list says where each figure is cited.
  const summaries = await evaluate(`Object.fromEntries([...document.querySelectorAll("[data-table]")].map((t) =>
    [t.dataset.table, t.querySelector(".thesis-where summary")?.textContent ?? null]))`);
  check("each table's figure list says where each figure is cited, not that it was found",
    latest.balance.tables.filter((table) => table.state === "available").every((table) => summaries[table.id] ===
      `Where each of the ${new Set(table.rows.flatMap((row) => [...row.lines.map((line) => line.figure.id),
        row.demand_total.id, row.supply_total.id])).size} figures is cited`) &&
    Object.values(summaries).every((summary) => summary === null || !/\bfound\b/i.test(summary)), JSON.stringify(summaries));
  // The demand and supply rows are named by the measure every figure of the row states (up to a qualifier some add
  // after a comma, such as ", estimated"), never by a fixed "Total supply": a table's sides are what its sources publish.
  const sharedMeasure = (measures) => {
    const parts = measures.map((measure) => measure.split(", "));
    const shared = [];
    for (const [index, part] of parts[0].entries()) {
      if (!parts.every((other) => other[index] === part)) break;
      shared.push(part);
    }
    return shared.length > 0 ? shared.join(", ") : null;
  };
  const totals = await evaluate(`Object.fromEntries([...document.querySelectorAll("[data-table]")].map((t) => [t.dataset.table,
    Object.fromEntries([...t.querySelectorAll("tr[data-total]")].map((row) =>
      [row.dataset.total, row.querySelector("th").firstChild?.textContent ?? ""]))]))`);
  check("each table's demand and supply rows are named by the measure their figures state",
    latest.balance.tables.filter((table) => table.state === "available").every((table) =>
      same(totals[table.id], { demand: sharedMeasure(table.rows.map((row) => row.demand_total.measure)) ?? "Demand",
        supply: sharedMeasure(table.rows.map((row) => row.supply_total.measure)) ?? "Supply" })) &&
    Object.values(totals).every((names) => Object.values(names).every((name) => !/^total (demand|supply)$/i.test(name))),
    JSON.stringify(totals));
  if (realSources) check("the real tables name IEA base-case mine supply, and US reported refined consumption and " +
    "refinery output", same(totals["balance-iea"], { demand: "IEA total copper demand",
    supply: "IEA base-case copper mine supply" }) && same(totals["us-refined-context"],
    { demand: "USGS US reported consumption of refined copper", supply: "USGS US refined copper production" }),
  JSON.stringify(totals));

  // 6. The exposure computed row.
  const computedMoved = latest.exposure.moved.filter((item) => item.state === "available" && item.amount.kind === "computed");
  const rows = await evaluate(`Object.fromEntries([...document.querySelectorAll("[data-moved]")].map((row) => [row.dataset.moved,
    { cost: row.querySelector("[data-computed=usd-per-unit]")?.textContent ?? null,
      share: row.querySelector("[data-computed=share]")?.textContent ?? null, text: row.innerText }]))`);
  // As for gaps: real content may have no computed exposure row (no retained source permits one); then none is shown.
  if (realSources && computedMoved.length === 0) check("no exposure row is computed, and the page shows no computed cost",
    (await count("[data-computed=usd-per-unit], [data-computed=share]")) === 0);
  else check("the exposure computed row shows the cost per unit and its share of the unit price", computedMoved.length > 0 &&
    computedMoved.every((item) => {
      const row = rows[item.id];
      return row && row.cost.includes(item.usd_per_unit) &&
        (item.share_pct === null ? row.share === null : row.share.includes(`${item.share_pct}%`)) &&
        row.text.includes(item.amount.per_unit.as_shown) && row.text.includes(item.amount.price.as_shown);
    }), JSON.stringify(rows[computedMoved[0]?.id] ?? null));
  check("the companies that move the thesis and the companies it moves are two tables",
    (await count("#exposure table")) === 2 && (await count("[data-mover]")) === latest.exposure.movers.length &&
    (await count("[data-moved]")) === latest.exposure.moved.length);
  check("the price is labelled a record, not evidence that the view is right",
    lower(await inner("#price")).includes("a record, not evidence that the view is right"));
  const priceRows = await evaluate(`[...document.querySelectorAll("[data-price] dt")].map((dt) => dt.textContent)`);
  check("the price record's rows read \"Latest retained when the thesis opened\" and \"Latest retained\"",
    latest.price_record.state === "available" ? same(priceRows, ["Latest retained when the thesis opened", "Latest retained"])
      : priceRows.length === 0, JSON.stringify(priceRows));
  // Each figure and passage line names its source by publisher and edition, and by title too where another listed
  // source has the same publisher and edition (copper v1: the MCS 2026 data release and its 2026 chapter).
  const nameOf = (source) => `${source.publisher} ${latest.sources.some((other) => other.id !== source.id &&
    other.publisher === source.publisher && other.edition === source.edition) ? `${source.edition} (${source.title})` : source.edition}`;
  const sourceOfItem = new Map([...figures(latest), ...passages(latest)].map((item) => [item.id, sourceNamed(item.source)]));
  const lines = await evaluate(`({ figures: [...document.querySelectorAll("[data-figure] .thesis-figure-value")]
      .map((e) => [e.closest("[data-figure]").dataset.figure, e.textContent]),
    passages: [...document.querySelectorAll("[data-passage] figcaption")]
      .map((e) => [e.closest("[data-passage]").dataset.passage, e.textContent]) })`);
  const twins = latest.sources.filter((source) => nameOf(source).endsWith(`(${source.title})`));
  check("every figure and passage line names its source by publisher and edition, and by title where two share them",
    lines.figures.length > 0 && lines.figures.every(([item, line]) => line.includes(` · ${nameOf(sourceOfItem.get(item))}`)) &&
    lines.passages.every(([item, line]) => line.startsWith(`${nameOf(sourceOfItem.get(item))} · `)) &&
    twins.every((source) => [...lines.figures, ...lines.passages].some(([item]) => sourceOfItem.get(item).id === source.id)),
    JSON.stringify({ twins: twins.map((source) => source.id), lines: [...lines.figures, ...lines.passages].slice(0, 4) }));
  await chromeClean(`version ${latest.version}`, latest);
  await evaluate(`(() => { const p = document.createElement("p"); p.id = "scan-probe"; p.style.textTransform = "uppercase";
    p.textContent = "copper prices will rise"; document.querySelector("[data-thesis-section=header]").append(p); })()`);
  const probe = affirmative(chromeOf(await inner("body"), latest));
  await evaluate(`document.querySelector("#scan-probe").remove()`);
  check("the page scan reads the rendered page and compares case-insensitively (a probe set in capitals is flagged)",
    probe.length > 0);

  // 7. Version 1 against version 2: the log is extended, never rewritten.
  const logOf = () => evaluate(`[...document.querySelectorAll("#log .thesis-log > li")].map((li) => li.innerText)`);
  if (latest.versions.length > 1) {
    const links = await evaluate(`[...document.querySelectorAll(".thesis-versions a")].map((a) =>
      [a.getAttribute("href"), a.getAttribute("aria-current")])`);
    check("the versions switcher links every version and marks the one shown",
      same(links.map(([href]) => href), latest.versions.map((item) => `/theses/${id}/versions/${item.version}`)) &&
      links.every(([, current], index) => (current === "page") === (index + 1 === latest.version)), JSON.stringify(links));
    const logLatest = await logOf();
    await evaluate(`document.querySelector('.thesis-versions a[href$="/versions/1"]').click()`);
    const first = await getJson(`/api/theses/${id}/versions/1`);
    check("the switcher opens version 1 at its own address",
      await waitFor(`location.pathname === ${q(`/theses/${id}/versions/1`)} && ${loaded(id, 1)}`));
    const logFirst = await logOf();
    const head = await inner("[data-thesis-section=header]");
    check("version 1 reads as published: its own date and confidence, no draft banner",
      !first.draft && (await count(".thesis-draft")) === 0 && head.includes(day(first.published_on)) &&
      lower(head).includes(first.confidence.level) && head.includes(first.confidence.basis));
    check("the later version's log extends version 1's log and rewrites none of its entries",
      logFirst.length === first.log.length && logLatest.length === latest.log.length &&
      logLatest.length > logFirst.length && logFirst.every((item, index) => item === logLatest[index]) &&
      first.log.every((item, index) => same(item, latest.log[index])), JSON.stringify([logFirst, logLatest]));
    await chromeClean("version 1", first);
    await evaluate(`document.querySelector('.thesis-versions a[href$="/versions/${latest.version}"]').click()`);
    check("the switcher returns to the latest version",
      await waitFor(`location.pathname === ${q(`/theses/${id}/versions/${latest.version}`)} && ${loaded(id, latest.version)}`) &&
      same(await logOf(), logLatest));
  }

  // 8. (synthetic) Without the usgs-2025 files: its reason is unavailable and none of its numbers is shown.
  if (!realSources) {
    const folder = join(sources, "usgs-2025");
    const others = new Set(figures(latest).filter((item) => item.source !== "usgs-2025").map((item) => item.as_shown));
    const numbers = [...new Set(figures(latest).filter((item) => item.source === "usgs-2025").map((item) => item.as_shown))]
      .filter((shown) => !others.has(shown));
    const reason = latest.reasons.find((item) => item.sources.includes("usgs-2025"));
    const hex = /[0-9a-f]{12,}/g;
    const onPage = (value) => evaluate(`document.body.outerHTML.replace(${hex}, "").includes(${q(value)})`);
    renameSync(folder, `${folder}-away`);
    try {
      await navigate(`/theses/${id}`);
      const away = await getJson(`/api/theses/${id}`);
      const after = away.reasons.find((item) => item.id === reason.id);
      await waitFor(`!!document.querySelector('[data-reason=${q(reason.id)}][data-state="unavailable"]')`);
      const card = await evaluate(`(() => { const c = document.querySelector('[data-reason=${q(reason.id)}]');
        return { status: !!c.querySelector("[data-status-of]"), change: !!c.querySelector(".thesis-change"),
          problems: [...c.querySelectorAll(".thesis-withheld li")].map((li) => li.textContent), text: c.innerText }; })()`);
      check("without the usgs-2025 files its reason is unavailable and shows its problems in place of its status",
        after.state === "unavailable" && !card.status && !card.change && card.problems.length === after.problems.length &&
        after.problems.every((line, index) => card.problems[index].endsWith(line.slice(line.indexOf(": ") + 2))) &&
        lower(card.text).includes("unavailable"), JSON.stringify(card));
      const missingNumbers = [];
      for (const value of numbers) if (await onPage(value)) missingNumbers.push(value);
      check("none of the usgs-2025 numbers is anywhere on the page", numbers.length > 0 && missingNumbers.length === 0,
        `${numbers.join(", ")} / shown: ${missingNumbers.join(", ")}`);
      check("the Sources footer marks usgs-2025 as not on this machine",
        (await evaluate(`document.querySelector('footer#sources [data-source="usgs-2025"]')?.dataset.state`)) === "missing");
      await chromeClean("with usgs-2025 removed", away);
    } finally {
      renameSync(`${folder}-away`, folder);
    }
    await navigate(`/theses/${id}`);
    await waitFor(`!!document.querySelector('[data-reason=${q(reason.id)}][data-state="available"]')`);
    const restored = await evaluate(`document.querySelector('[data-reason=${q(reason.id)}] [data-status-of]')?.dataset.statusOf ?? null`);
    let back = true;
    for (const value of numbers) back = back && await onPage(value);
    check("restoring the files restores the reason, its status and its numbers", restored === reason.status && back);
  }

  // 9. A version that does not exist says so.
  const absent = `/theses/${id}/versions/${latest.versions.length + 1}`;
  await navigate(absent);
  check("a version that does not exist says so", await waitFor(
    `(document.querySelector(".state-panel")?.textContent ?? "").includes("This thesis has no such version")`));

  // 10. Reading wrote nothing.
  check("reading wrote nothing to the thesis files", same(tree(content), contentBefore));
  check("reading wrote nothing to the retained sources",  // Two empty trees would compare equal; hashing nothing fails.
    Object.keys(sourcesBefore).length > 0 && same(tree(sources), sourcesBefore));

  // 11. A 390 px wide screen.
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  await navigate(`/theses/${id}`);
  await waitFor(loaded(id, latest.version));
  await evaluate(`document.querySelectorAll("details").forEach((d) => { d.open = true; })`);
  await sleep(700);
  const layout = await evaluate(`({ scroll: document.documentElement.scrollWidth, width: document.documentElement.clientWidth })`);
  check("a 390 px wide screen does not scroll sideways", layout.scroll <= layout.width, JSON.stringify(layout));
  const cut = await evaluate(`[...document.querySelectorAll(".thesis-balance tbody th")]
    .filter((th) => th.scrollWidth > th.clientWidth + 1).map((th) => th.textContent)`);
  check("on a 390 px wide screen no balance row name is cut off", cut.length === 0, JSON.stringify(cut));

  const outside = requests.filter((row) => !row.url.startsWith(base) && !row.url.startsWith("data:") && row.url !== "about:blank");
  check("nothing outside the local server was requested", outside.length === 0, outside.map((row) => row.url).join(", "));
  check("nothing but GET was sent", requests.every((row) => row.method === "GET"),
    requests.filter((row) => row.method !== "GET").map((row) => row.url).join(", "));
  // The browser's own favicon probe, and the 404 of the version asked for in step 9, are expected; each is attributed
  // by its URL, never by its text alone.
  const expected = new Set([`${base}/favicon.ico`, `${base}/api${absent}`]);
  const real = errors.filter((error) => !expected.has(error.url));
  check("no page error", real.length === 0, JSON.stringify(real));
  if (process.env.SECOND_ORDER_SCREENSHOTS) {  // One bounded clip per part of the page, for a visual review.
    const parts = [["header", "[data-thesis-section=header]"], ["view", "#view"], ["balance", "#balance"],
      ["reasons", "#reasons"], ["exposure", "#exposure"], ["log", "#log"], ["sources", "footer#sources"]];
    for (const [device, width, mobile] of [["desktop", 1280, false], ["phone", 390, true]]) {
      await send("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile });
      await navigate(`/theses/${id}`);
      await waitFor(loaded(id, latest.version));
      await sleep(900);
      for (const [name, selector] of parts) {
        const box = await evaluate(`(() => { const r = document.querySelector(${q(selector)}).getBoundingClientRect();
          return { x: 0, y: r.top + scrollY, width: ${width}, height: Math.min(Math.ceil(r.height), 2400) }; })()`);
        const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true,
          clip: { ...box, scale: 1 } });
        writeFileSync(join(process.env.SECOND_ORDER_SCREENSHOTS, `${device}-${name}.png`), Buffer.from(shot.data, "base64"));
      }
    }
  }
  ws.close();
} catch (error) {
  check("the thesis browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(300);
  try { rmSync(root, { recursive: true, force: true }); } catch { /* Windows may hold a file briefly. */ }
}
console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
process.exit(results.every(Boolean) ? 0 : 1);
