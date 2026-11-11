// Browser check of Related Cases, against tests/review_browser_server.py serving a new, empty folder with
// --related-cases (the committed historical cases; SYNTHETIC Inbox entries and captures; no retained source copies).
// It checks:
// - the case library lists both historical cases apart from its release cases, with the coverage not built yet;
// - each case page: source facts with their quotes, dates kept apart (announcement, effective, unknown publication),
//   labelled interpretation, unknowns, review status, the historical note and the "copy not on this machine" state;
// - the event overview: nothing matched before one explicit action, sent once; a useful match explained (shared,
//   different, unknown, not compared); a topical overlap shown as not related; an unrelated event with no case;
//   recurring titles as separate events; a capture matched through its source address;
// - a repeat writes nothing, a restart reads the same, narrow screens, page errors and no request outside the server.
//
//   cd frontend; npm run build; npm run test:browser:related-cases
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const python = process.env.SECOND_ORDER_PYTHON ?? "python";
const chromePath = [process.env.SECOND_ORDER_CHROME, "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
  "/usr/bin/chromium-browser"].find((path) => path && existsSync(path));
if (!chromePath) throw new Error("Chrome was not found; set SECOND_ORDER_CHROME to its executable.");
if (!existsSync(join(repo, "frontend/dist/index.html"))) throw new Error("Build the client first: npm run build");

const TITLES = {
  controls: "Members discuss new export controls on advanced semiconductors",
  russia: "Sanctions on Russian crude oil exports shift trade flows",
  crude: "U.S. crude oil production reached a record in July",
  statement: "Federal Reserve issues FOMC statement",
  entity: "Commerce adds chipmakers in China to the Entity List",
};
const BIS = "bis-2022-10-07";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];  // As library.ts.
const day = (iso) => { const [y, m, d] = iso.split("-").map(Number); return `${d} ${MONTHS[m - 1]} ${y}`; };
const OFAC = "ofac-pdvsa-2019-01-28";
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => { const { port } = server.address(); server.close(() => done(port)); });
});
const root = mkdtempSync(join(tmpdir(), "second-order-related-check-"));
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
      else found[relative(folder, full)] = createHash("sha256").update(readFileSync(full)).digest("hex");
    }
  };
  walk(folder);
  return found;
};
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const contentBefore = tree(join(repo, "content", "related-cases"));

async function startServer(port, extra) {
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    ...extra], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  for (let i = 0; i < 300; i++) {
    try { if ((await fetch(`http://127.0.0.1:${port}/api/related-cases`)).ok) return server; } catch { /* starting */ }
    await sleep(200);
  }
  throw new Error("The review server did not start.");
}

try {
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  let server = await startServer(port, ["--related-cases"]);
  const api = async (path) => (await fetch(base + path)).json();
  const inbox = await api("/api/inbox");
  const entries = [...inbox.items, ...inbox.retained];
  const entry = (title, index = 0) => entries.filter((item) => item.title === title)[index].id;
  const captures = (await api("/api/intake")).captures;
  const captureId = (headline) => captures.find((row) => row.headline === headline || row.event?.headline === headline)
    ?.capture_id;

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
      errors.push(message.params.exceptionDetails.text);
    } else if (message.method === "Log.entryAdded" && message.params.entry.level === "error") {
      errors.push(`${message.params.entry.text} ${message.params.entry.url ?? ""}`);
    }
  });
  const send = (method, params = {}) => new Promise((done, fail) => {
    const id = ++counter;
    pending.set(id, (message) => message.error ? fail(new Error(message.error.message)) : done(message.result));
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) =>
    (await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })).result.value;
  const waitFor = async (expression, timeout = 20000) => {
    for (const start = Date.now(); Date.now() - start < timeout; await sleep(80)) {
      if (await evaluate(expression)) return true;
    }
    return false;
  };
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);
  const count = (selector) => evaluate(`document.querySelectorAll(${JSON.stringify(selector)}).length`);
  const click = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.click()`);
  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("Log.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete'");
  };
  const posts = () => requests.filter((row) => row.method === "POST" && row.url.includes("/api/related-cases/")).length;
  const records = join(served, "related");
  const overview = (kind, id) => `/events/${kind}/${encodeURIComponent(id)}`;
  const settled = `["checked", "not_checked", "problem"].includes(document.querySelector("#overview-related")?.dataset.state)`;

  // 1. The case library lists both historical cases apart from its release cases.
  const library = await api("/api/case-library");
  await open("/library");
  await waitFor(`document.querySelectorAll(".historical-entry").length === 2`);
  const section = await text("#historical-cases");
  check("the case library lists the two historical cases in their own section",
    (await count(".historical-entry")) === 2 && section.includes("Announced 28 Jan 2019") &&
    section.includes("Announced 7 Oct 2022") && section.includes("Historical policy announcements"), section.slice(0, 200));
  // The release cases come from their own request; wait for that list to render, then compare the full count.
  await waitFor(`document.querySelectorAll(".library-index .library-entry").length >= ${library.cases.length}`);
  check("the release cases are unchanged beside them",
    (await count(".library-index .library-entry")) === library.cases.length, String(await count(".library-entry")));
  check("the coverage not built yet is listed as not covered, with what happened to each planned source",
    ["Tariffs and international trade", "Competition and regulatory policy", "Labor disruptions"]
      .every((topic) => section.includes(topic)) && section.includes("Not covered yet") && section.includes("HTTP 403"));

  // 2. Each case page, opened from the library.
  for (const id of [OFAC, BIS]) {
    const view = await api(`/api/related-cases/${id}`);
    await open("/library");
    await waitFor(`!!document.querySelector('[data-historical="${id}"] a')`);
    await click(`[data-historical="${id}"] a`);
    await waitFor(`document.querySelector(".historical-case")?.dataset.case === "${id}"`);
    const page = await text(".historical-case");
    check(`${id}: title, summary and labels, with the historical and review notes`,
      (await text("h1")) === view.case.title && page.includes("Not human-reviewed") &&
      page.includes("Not current law or policy") && page.includes("nothing here says what applies today"));
    check(`${id}: every source fact with its quotes`,
      (await count(".related-fact")) === view.case.facts.length &&
      (await count(".related-fact blockquote")) === view.case.facts.reduce((sum, fact) => sum + fact.quotes.length, 0));
    const dates = await evaluate(`[...document.querySelectorAll(".related-dates tbody tr")].map((row) => [row.dataset.kind,
      row.children[2].textContent])`);
    check(`${id}: dates kept apart, unknown dates unknown`,
      same(dates, view.case.dates.map((item) => [item.kind, item.date ? day(item.date) : "Unknown"])),
      JSON.stringify(dates));
    check(`${id}: interpretation is labelled and the copy is not on this machine`,
      page.includes("Curated interpretation, written with an AI assistant and not reviewed by a person") &&
      (await evaluate(`document.querySelector(".related-check")?.dataset.check`)) === "absent" &&
      page.includes("Retained copy not on this machine"));
  }
  check("the export-controls case states three effective dates apart from the announcement",
    (await evaluate(`[...document.querySelectorAll('.related-dates tr[data-kind="effective"]')].map((row) => row.children[2].textContent).join("|")`))
      === "7 Oct 2022|7 Oct 2022|12 Oct 2022|21 Oct 2022");

  // 3. A useful match, found by one explicit action.
  let before = tree(served);
  const controls = entry(TITLES.controls);
  await open(overview("inbox", controls));
  await waitFor(settled);
  check("before the action: not checked, nothing written, the Related cases link in the overview",
    (await evaluate(`document.querySelector("#overview-related").dataset.state`)) === "not_checked" &&
    same(tree(served), before) && (await text(".overview-toc")).includes("Related cases"));
  await click("#overview-related .related-action button");
  await waitFor(`document.querySelector("#overview-related")?.dataset.state === "checked"`);
  const match = await text("#overview-related");
  check("the action was sent once and stored once", posts() === 1 && Object.keys(tree(records)).length === 1);
  check("the match names the shared instrument and sector with where each was found",
    (await count('#overview-related [data-case="bis-2022-10-07"]')) === 1 &&
    match.includes("Policy instrument: Export controls (“export controls” in the entry's title)") &&
    match.includes("Semiconductors and advanced computing"), match.slice(0, 400));
  check("what differs and what is unknown come only from the event's text",
    match.includes("Nothing this event's text names differs from the case") &&
    match.includes("names no country or area; whether it concerns China (PRC), as the case does, is unknown") &&
    match.includes("The case was announced on October 7, 2022") && match.includes("Licensing policy"));
  await click('#overview-related [data-case="bis-2022-10-07"] .related-case-title');
  await waitFor(`document.querySelector(".historical-case")?.dataset.case === "${BIS}"`);
  check("the match links to the case page", (await text("h1")).startsWith("Commerce restricts"));

  // 4. A different country, a topical overlap, an unrelated event and recurring titles.
  const find = async (kind, id) => {
    await open(overview(kind, id));
    await waitFor(settled);
    if ((await evaluate(`document.querySelector("#overview-related").dataset.state`)) === "not_checked") {
      await click("#overview-related .related-action button");
      await waitFor(`document.querySelector("#overview-related")?.dataset.state === "checked"`);
    }
    return text("#overview-related");
  };
  const russia = await find("inbox", entry(TITLES.russia));
  check("a different country is stated as a difference",
    russia.includes("This event names Russia as its country or area; the case concerns Venezuela."));
  const crude = await find("inbox", entry(TITLES.crude));
  check("a shared topic alone is an overlap, not a related case",
    crude.includes("No related case.") && crude.includes("Checked, not related") &&
    crude.includes("names none of the case's policy instruments (Sanctions), so it is not presented as related"));
  const statements = [entry(TITLES.statement, 0), entry(TITLES.statement, 1)];
  const first = await find("inbox", statements[0]);
  await find("inbox", statements[1]);
  check("an unrelated event has no related case and no overlap",
    first.includes("No related case.") && !first.includes("Checked, not related"));
  const stored = Object.keys(tree(records)).length;
  check("recurring titles are separate events with separate stored checks", statements[0] !== statements[1] && stored === 5,
    String(stored));
  const entity = await find("capture", captureId(TITLES.entity));
  check("a capture is matched through its headline and source address",
    entity.includes("“www.bis.gov” in the capture's source address") && entity.includes("Entity List"));

  // 5. A repeat writes nothing; a restart reads the same.
  before = tree(served);
  const repeat = await evaluate(`fetch("/api/related-cases/events/inbox/${encodeURIComponent(controls)}/matches", {
    method: "POST", headers: { "Content-Type": "application/json", "X-Second-Order-Related": "1" },
    body: JSON.stringify({ find_related_cases: true }) }).then(async (r) => [r.status, (await r.json()).created])`);
  check("repeating the check reuses the stored result and writes nothing",
    same(repeat, [200, false]) && same(tree(served), before), JSON.stringify(repeat));
  await sleep(300);
  server.kill();
  await sleep(500);
  server = await startServer(port, ["--keep-records", "--related-cases"]);
  const postsBefore = posts();
  await open(overview("inbox", controls));
  await waitFor(settled);
  check("after a restart the stored match is read and nothing is written or sent",
    (await text("#overview-related")) === match && same(tree(served), before) && posts() === postsBefore);

  // 6. Narrow screens.
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  for (const path of [overview("inbox", controls), `/library/historical/${BIS}`, "/library"]) {
    await open(path);
    await waitFor(`!!document.querySelector("#overview-related, .historical-case, .historical-entry")`);
    await sleep(600);
    const layout = await evaluate(`({ scroll: document.documentElement.scrollWidth, width: document.documentElement.clientWidth })`);
    check(`narrow screen ${path}: no sideways scrolling`, layout.scroll <= layout.width, JSON.stringify(layout));
  }

  const outside = requests.filter((row) => !row.url.startsWith(base) && !row.url.startsWith("data:") && row.url !== "about:blank");
  check("nothing outside the local server was requested", outside.length === 0, outside.map((row) => row.url).join(", "));
  const real = errors.filter((item) => !/favicon\.ico/.test(item));
  check("no page error", real.length === 0, real.join(" | "));
  check("the committed historical cases are unchanged", same(tree(join(repo, "content", "related-cases")), contentBefore));
  ws.close();
} catch (error) {
  check("the related-cases browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(300);
  try { rmSync(root, { recursive: true, force: true }); } catch { /* Windows may hold a file briefly. */ }
}
console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
process.exit(results.every(Boolean) ? 0 : 1);
