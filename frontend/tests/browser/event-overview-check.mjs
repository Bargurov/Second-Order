// Browser acceptance check for the private event overview, in one headless Chrome against tests/review_browser_server.py
// serving an empty temporary folder with SYNTHETIC feeds (--simulated-feeds context), a counting fake of the Board's
// server (--simulated-market, never asked here) and the committed bundle of real H.15 downloads, read in place.
//
// The journey: an Inbox entry's overview with empty sections -> Back to the Inbox -> Analyze this event fills the form ->
// capturing records the entry version as the capture's origin -> one local mock draft -> My analyses links to the
// capture's overview, which shows the origin, the draft, no review yet and real committed market values -> Open review
// -> one explicit review save -> the way back returns to the same overview, now showing the current review -> reload
// and Back -> the entry's overview lists the capture; an energy entry gets no yields -> only explicit writes, nothing
// requested outside the local server, no feed or Board request after the refresh, the committed bundle unchanged.
//
//   cd frontend; npm run build; npm run test:browser:overview
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
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

const JUNE = "Simulated: FOMC statement of 18 June 2025";
const SEPTEMBER = "Simulated: FOMC statement of 16 September 2026";
const ENERGY = "Simulated: Hydro-Québec electricity exports to New England fell";
const COMMITTED = join(repo, "content", "market-context");

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const root = mkdtempSync(join(tmpdir(), "second-order-overview-check-"));
const served = join(root, "served");
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const lines = (...parts) => (existsSync(join(served, ...parts)) ? readFileSync(join(served, ...parts), "utf8").trim()
  .split("\n").filter(Boolean) : []);
const folder = (...parts) => (existsSync(join(served, ...parts)) ? readdirSync(join(served, ...parts)).sort() : []);
const fingerprint = (path) => readdirSync(path, { recursive: true, withFileTypes: true }).filter((entry) => entry.isFile())
  .map((entry) => { const file = join(entry.parentPath ?? entry.path, entry.name);
    return `${file}:${createHash("sha256").update(readFileSync(file)).digest("hex")}`; }).sort().join("\n");
const committedValue = (date, column) => readFileSync(join(COMMITTED, "sources", "fomc-2025-06-18.csv"), "utf8")
  .split(/\r?\n/).find((line) => line.startsWith(`${date},`)).split(",")[column];

async function startServer() {
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    "--simulated-feeds", "context", "--simulated-market", "--market-context", "committed",
    "--market-clock", "2026-10-09T15:00:00+00:00"], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  for (let i = 0; i < 150; i++) {
    try { if ((await fetch(`${base}/api/drafts`)).ok) return base; } catch { await sleep(200); }
  }
  throw new Error("The review server did not start.");
}

try {
  mkdirSync(served);
  const before = fingerprint(COMMITTED);
  const base = await startServer();
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
  const click = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.click()`);
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);
  const setValue = (selector, value) => evaluate(`(() => {
    const element = document.querySelector(${JSON.stringify(selector)});
    if (!element) return false;
    const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
      : element instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value").set.call(element, ${JSON.stringify(value)});
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`);
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
    if (message.method === "Page.javascriptDialogOpening") send("Page.handleJavaScriptDialog", { accept: true });
  });
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Log.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const go = async (path, ready) => {
    await send("Page.navigate", { url: base + path });
    return waitFor(`document.readyState === 'complete' && ${ready}`, 15000);
  };
  const overviewReady = `!!document.querySelector("#overview-source") && !!document.querySelector("#overview-market")`;
  const entryJs = (title) => `[...document.querySelectorAll(".inbox-item")].find((li) =>
    li.querySelector("h3").textContent === ${JSON.stringify(title)})`;

  // 1. An Inbox entry's overview: feed metadata, and empty sections that say why.
  await go("/", "!!document.querySelector('.inbox-refresh')");
  await click(".inbox-refresh");
  await waitFor(`document.querySelectorAll(".inbox-item").length === 6`, 15000);
  const feedRequests = lines("simulated-feeds", "requests.jsonl").length;
  const juneOverview = await evaluate(`${entryJs(JUNE)}?.querySelector("a.inbox-overview")?.getAttribute("href")`);
  check("every Inbox entry links to its overview", (await evaluate(`[...document.querySelectorAll(".inbox-item")]
    .every((li) => li.querySelector("a.inbox-overview")?.getAttribute("href").startsWith("/events/inbox/"))`)) &&
    juneOverview?.startsWith("/events/inbox/fed-monetary%3A"));
  await click(`a.inbox-overview[href="${juneOverview}"]`);
  await waitFor(overviewReady, 15000);
  check("the entry's overview shows feed metadata as such, and is not a Dossier",
    (await text("#overview-source")).includes("Feed metadata") && (await text("#overview-source")).includes(JUNE) &&
    (await text("#overview-source")).includes("not a verified publication instant") &&
    (await text(".overview-not-dossier")).includes("not a research Dossier"));
  check("empty sections say why: no triage, no linked analysis, no confirmed context date",
    (await evaluate(`document.querySelector('#overview-triage [data-gap]')?.dataset.gap`)) === "none" &&
    (await evaluate(`document.querySelector('#overview-analysis [data-gap]')?.dataset.gap`)) === "none" &&
    (await evaluate(`document.querySelector("#overview-market").dataset.state`)) === "needs_date");
  const historyRows = (step) => evaluate(`[...document.querySelectorAll('#overview-history [data-step="${step}"] .overview-history-row')]
    .map((li) => li.dataset.state)`);
  check("the processing history says the entry is not processed, which is a valid state, and where it came from",
    (await evaluate(`document.querySelector("#overview-history [data-history]")?.dataset.history`)) === "not_processed" &&
    (await text("#overview-history .overview-history-state")).startsWith("Not processed: listed by 1 recorded retrieval;") &&
    JSON.stringify(await historyRows("source")) === '["retrieved"]' &&
    (await text('#overview-history [data-step="source"]')).includes("Feed timestamp") &&
    (await text('#overview-history [data-step="source"]')).includes("Listed by 1 recorded retrieval, 1 with the response kept privately") &&
    (await text('#overview-history [data-step="use"]')).includes("Research intake is closed"));
  check("the source says which texts it holds and that the first retrieval is not a publication time",
    (await text("#overview-source .overview-text-held")).startsWith("Held text: the headline as the feed supplies it") &&
    (await text("#overview-source")).includes("when this inbox first saw the entry, not when it was published"));
  await evaluate("history.back()");
  check("Back returns to the Inbox", await waitFor(`location.pathname === "/" && !!document.querySelector(".inbox-item")`));

  // 2. Analyze this event, capture with the origin recorded, one local mock draft.
  await evaluate(`${entryJs(JUNE)}.querySelector(".inbox-analyze").click()`);
  await waitFor(`document.querySelector('.intake-form input[type="url"]')?.value.includes("monetary20250618a")`);
  await setValue('.intake-form input[type="date"]', "2025-06-18");
  await setValue('.intake-form input[type="time"]', "14:00");
  await setValue(".intake-time select", "-04:00");
  await setValue(".intake-form textarea", "Simulated statement text supplied by the operator for this check.");
  await click(".intake-form button[type=submit]");
  await waitFor(`!!document.querySelector(".intake-preview")`, 15000);
  const captures = folder("intake");
  const links = folder("event-links");
  check("capturing recorded the Inbox entry version as the origin, beside the capture",
    captures.length === 1 && links.length === 1 && links[0] === `${captures[0]}.json` &&
    !folder("intake", captures[0]).includes("origin.json"));
  const link = JSON.parse(readFileSync(join(served, "event-links", links[0]), "utf8"));
  check("the origin names the entry, its version fingerprint, and that the form matched it",
    link.inbox.title === JUNE && /^[0-9a-f]{64}$/.test(link.inbox.content_sha256) && link.form.headline_matches &&
    link.form.source_url_matches);
  await click(".intake-confirm input");
  await click(".intake-preview .intake-actions .button:not(.button-quiet)");
  await waitFor(`!!document.querySelector(".human-review") && location.search.startsWith("?draft=")`, 15000);
  const draftId = (await evaluate("location.search")).slice(7);
  const servedView = async () => (await fetch(`${base}/api/drafts/${draftId}`)).headers.get("x-draft-view-sha256");
  const viewBefore = await servedView();

  // 3. My analyses links to the capture's overview: origin, draft, no review yet, real committed market values.
  await go("/analyses", "!!document.querySelector('.analysis-card')");
  await click(".analysis-card a.analysis-overview");
  await waitFor(overviewReady, 15000);
  const captureOverview = await evaluate("location.pathname");
  check("My analyses opens the capture's overview", captureOverview === `/events/capture/${captures[0]}`);
  check("the source shows the supplied time and the recorded origin",
    (await text("#overview-source")).includes("2025-06-18T14:00:00-04:00 as supplied") &&
    (await evaluate(`document.querySelector(".overview-origin").dataset.origin`)) === "verified" &&
    (await text(".overview-origin")).includes("Started from Inbox entry version 1 of 1"));
  check("the draft is shown apart from the review, which is not reviewed yet",
    (await text("#overview-analysis .analysis-layer-model h3")) === "The model's proposed summary" &&
    (await text("#overview-analysis .analysis-review-chip")) === "Not reviewed");
  const base2 = committedValue("2025-06-17", 1);
  const after1 = committedValue("2025-06-20", 1);
  const expected = `${Math.round((Number(after1) - Number(base2)) * 100) < 0 ? "\u2212" : "+"}${Math.abs(
    Math.round((Number(after1) - Number(base2)) * 100))} bp`;
  check("the market section shows the real committed values for 18 June 2025, with their changes",
    (await evaluate(`document.querySelector("#overview-market").dataset.state`)) === "complete" &&
    (await text('tr[data-change="RIFLGFCY02_N.B-1"] td:last-child')) === expected &&
    (await text('#context-data tr[data-date="2025-06-17"] td[data-series="RIFLGFCY02_N.B"]')) === `${base2}%`,
    expected);

  // 4. Open review from the overview, save once, and come back to the same overview.
  await click("#overview-analysis a.overview-open-review");
  await waitFor(`!!document.querySelector(".human-review") && location.search.includes("from=")`, 15000);
  check("the review editor offers the way back to the overview",
    (await text(".drafts-return a")) === "← Back to the event overview");
  await evaluate(`[...document.querySelectorAll(".review-status input")][2].click()`);  // Human-reviewed.
  await setValue(".human-review .review-field textarea", "Reviewed from the event overview.");
  await waitFor(`!document.querySelector(".review-save-bar button").disabled`);
  await click(".review-save-bar button");
  await waitFor(`document.querySelector(".review-message.is-saved")?.textContent.includes("Saved version 1")`);
  await click(".drafts-return a");
  await waitFor(`location.pathname === ${JSON.stringify(captureOverview)} && ${overviewReady}`, 15000);
  check("the overview now shows the current review, and the model's words are unchanged",
    (await text("#overview-analysis .analysis-review-chip")) === "Human-reviewed" &&
    (await text("#overview-analysis .analysis-note")).includes("Reviewed from the event overview.") &&
    (await text("#overview-analysis .analysis-layer-model h3")) === "The model's proposed summary");
  check("reading the overview left the draft view's fingerprint, and so its review binding, unchanged",
    (await servedView()) === viewBefore);
  await go(captureOverview, overviewReady);
  check("a direct reload shows the same event and review", (await text("h1")) === JUNE &&
    (await text("#overview-analysis .analysis-review-chip")) === "Human-reviewed");
  check("the capture's history shows its origin, the capture, the mock draft at $0 and the current review, linked",
    JSON.stringify(await historyRows("source")) === '["retrieved"]' &&
    JSON.stringify(await historyRows("analysis")) === '["captured","draft"]' &&
    JSON.stringify(await historyRows("review")) === '["human_reviewed"]' &&
    (await text('#overview-history [data-step="analysis"]')).includes("Local mock draft (no provider contacted): a draft") &&
    (await text('#overview-history [data-step="analysis"]')).includes("usage-derived $0") &&
    (await evaluate(`document.querySelector('#overview-history [data-step="analysis"] [data-state="draft"] a')?.getAttribute("href")`))
      ?.startsWith(`/?draft=${draftId}&from=`));
  await evaluate("history.back()");
  check("Back from the overview returns to the review editor it came from",
    await waitFor(`location.search.startsWith("?draft=") && !!document.querySelector(".human-review")`, 15000));

  // 5. The entry's overview lists the capture; another entry with no capture stays empty; energy gets no yields.
  await go(juneOverview, overviewReady);
  check("the entry's overview lists the capture that recorded it, with its review",
    (await evaluate(`[...document.querySelectorAll("#overview-analysis .overview-capture")].map((li) => li.dataset.capture).join()`))
      === captures[0] && (await text("#overview-analysis .overview-capture")).includes("Human-reviewed"));
  check("the entry's history is now processed: one saved event, one draft attempt, one review version",
    (await evaluate(`document.querySelector("#overview-history [data-history]")?.dataset.history`)) === "processed" &&
    (await text("#overview-history .overview-history-state")).includes("1 saved event, 1 recorded draft attempt, 1 review version"));
  await go("/", "document.querySelectorAll('.inbox-item').length === 6");
  const september = await evaluate(`${entryJs(SEPTEMBER)}.querySelector("a.inbox-overview").getAttribute("href")`);
  const energy = await evaluate(`${entryJs(ENERGY)}.querySelector("a.inbox-overview").getAttribute("href")`);
  await go(september, overviewReady);
  check("an entry with no recorded capture is not linked to one by its similar title",
    (await evaluate(`document.querySelector('#overview-analysis [data-gap]')?.dataset.gap`)) === "none" &&
    (await evaluate(`document.querySelector("#overview-history [data-history]")?.dataset.history`)) === "not_processed");
  await go(energy, overviewReady);
  check("an energy entry's market section says it is outside the slice and shows no yields",
    (await evaluate(`document.querySelector("#overview-market").dataset.state`)) === "unsupported" &&
    !(await evaluate(`!!document.querySelector("#overview-market .context-chart")`)));

  // 6. Only explicit writes; no feed or Board request after the refresh; nothing outside the local server.
  const writes = requests.filter((r) => r.method !== "GET").map((r) => new URL(r.url).pathname
    .replace(/\/api\/intake\/[^/]+\/mock-drafts/, "/api/intake/*/mock-drafts").replace(/\/api\/drafts\/[^/]+\/reviews/, "/api/drafts/*/reviews"));
  check("every write was explicit: one refresh, one capture, one mock draft, one review",
    JSON.stringify(writes.sort()) === JSON.stringify(["/api/drafts/*/reviews", "/api/inbox/refresh", "/api/intake",
                                                       "/api/intake/*/mock-drafts"]), JSON.stringify(writes));
  check("overview reads requested no feed and nothing from the Board",
    lines("simulated-feeds", "requests.jsonl").length === feedRequests && lines("simulated-market", "requests.jsonl").length === 0);
  const outside = requests.filter(({ url }) => !url.startsWith("http://127.0.0.1:") && !url.startsWith("data:") && url !== "about:blank");
  check("the page requested nothing outside the local server", outside.length === 0, outside.map((r) => r.url).join(", "));
  check("the committed bundle is byte for byte unchanged", fingerprint(COMMITTED) === before);
  const pageErrors = consoleErrors.filter((error) => !/\/favicon\.ico$/.test(error.url));
  check("the page logged no errors (the favicon probe aside)", pageErrors.length === 0, JSON.stringify(pageErrors));
  ws.close();
} catch (error) {
  check("the event-overview browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(500);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
