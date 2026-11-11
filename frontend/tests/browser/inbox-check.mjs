// Browser acceptance check for the Event Inbox, in one headless Chrome against tests/review_browser_server.py with
// --simulated-feeds: SYNTHETIC feeds behind the five allowlisted URLs, served by an in-process fake installed at
// startup. The journey: an empty inbox -> Refresh events -> choose an entry -> check its metadata -> enter the
// published text and a verified time -> preview the exact request -> approve one local mock -> save a human review ->
// reload and find the saved result. Then a mock refusal, an entry with no feed timestamp, protection of unsaved edits
// and of a loaded preview, no switching while an action is in flight, a second refresh in which one source fails and
// one entry's title changes (saved captures unchanged), and a reload served from the local cache. No model, provider
// or real feed is contacted, and the page requests nothing outside the local server.
//
//   cd frontend; npm run build; npm run test:browser:inbox
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

const FEEDS = ["https://www.federalreserve.gov/feeds/press_monetary.xml", "https://www.bls.gov/feed/empsit.rss",
               "https://www.bls.gov/feed/cpi.rss", "https://www.eia.gov/rss/todayinenergy.xml",
               "https://www.wto.org/library/rss/latest_news_e.xml"];  // The energy and trade feeds list nothing here.
const STATEMENT = "Simulated: Federal Reserve issues FOMC statement";
const STATEMENT_LINK = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm";
const CPI = "Simulated: CPI rises 0.4 percent in August";
const PAYROLL = "Simulated: Payroll employment changes little in September";
const NO_TIME = "Simulated: Employment Situation entry without a timestamp";

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const until = async (condition, timeout = 10000) => {
  for (const start = Date.now(); Date.now() - start < timeout; await sleep(50)) if (condition()) return true;
  return false;
};
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const root = mkdtempSync(join(tmpdir(), "second-order-inbox-check-"));
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
const captureHashes = () => Object.fromEntries(folder("intake").flatMap((capture) => folder("intake", capture)
  .map((name) => [`${capture}/${name}`, createHash("sha256").update(readFileSync(join(served, "intake", capture, name))).digest("hex")])));

try {
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    "--simulated-feeds"], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
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
    const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
      : element instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value").set.call(element, ${JSON.stringify(value)});
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`);
  const click = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.click()`);
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);
  const value = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.value ?? null`);

  const requests = [];
  listeners.push((message) => {
    if (message.method === "Network.requestWillBeSent") {
      requests.push({ url: message.params.request.url, method: message.params.request.method });
    }
  });
  const held = [];
  listeners.push((message) => {
    if (message.method === "Fetch.requestPaused") held.push(message.params.requestId);
  });
  const posts = (part) => requests.filter((request) => request.method === "POST" && request.url.includes(part)).length;
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete'");
  };
  const entries = () => evaluate(`[...document.querySelectorAll(".inbox-item h3")].map((h) => h.textContent)`);
  const sourceStates = () => evaluate(`Object.fromEntries([...document.querySelectorAll(".inbox-source")]
    .map((li) => [li.dataset.source, li.dataset.state]))`);
  const choose = (title) => evaluate(`(() => { const li = [...document.querySelectorAll(".inbox-item")]
    .find((e) => e.querySelector("h3").textContent === ${JSON.stringify(title)});
    const button = li?.querySelector(".inbox-analyze"); if (!button || button.disabled) return false; button.click(); return true; })()`);
  const analyzeEnabled = () => evaluate(`[...document.querySelectorAll(".inbox-analyze")].some((b) => !b.disabled)`);
  const formValues = () => evaluate(`({
    headline: document.querySelector('.intake-form input:not([type="url"]):not([type="date"]):not([type="time"]):not([type="checkbox"])')?.value,
    url: document.querySelector('.intake-form input[type="url"]')?.value,
    date: document.querySelector('.intake-form input[type="date"]')?.value,
    time: document.querySelector('.intake-form input[type="time"]')?.value,
    offset: document.querySelector(".intake-time select")?.value,
    text: document.querySelector(".intake-form textarea")?.value })`);
  const approve = ".intake-preview .intake-actions .button:not(.button-quiet)";
  const notes = ".human-review .review-field textarea";
  const preview = async (submit = true) => {
    if (submit) await click(".intake-form button[type=submit]");
    return waitFor(`!!document.querySelector(".intake-preview")`);
  };

  // 1. A first visit: nothing cached, nothing requested, nothing written.
  await open("/");
  check("the Tracker shows the Event inbox, never refreshed, with nothing held",
    await waitFor(`!!document.querySelector(".event-inbox .inbox-sources")`) &&
    Object.values(await sourceStates()).every((state) => state === "never_refreshed") && (await entries()).length === 0 &&
    (await text(".event-inbox")).includes("never been refreshed"));
  await sleep(300);
  check("loading the page requested no feed and wrote no inbox record",
    feedRequests().length === 0 && !existsSync(join(served, "event-inbox")) && posts("/api/") === 0);

  // 2. Refresh events: the five listed feeds, once each, with the operator's contact; nothing else.
  await click(".inbox-refresh");
  check("Refresh events shows every entry the simulated feeds list",
    await waitFor(`document.querySelectorAll(".inbox-item").length === 5`, 15000));
  const firstRequests = feedRequests();
  check("the refresh requested exactly the five allowlisted feeds, once each, as an identified non-browser client",
    JSON.stringify(firstRequests.map((r) => r.url)) === JSON.stringify(FEEDS) &&
    firstRequests.every((r) => r.method === "GET" && r.user_agent.includes("contact: simulated-operator@example.invalid") &&
      !r.user_agent.includes("Mozilla")), JSON.stringify(firstRequests));
  check("each source reports its successful retrieval, never as live",
    Object.values(await sourceStates()).every((state) => state === "ok") &&
    (await text(".inbox-sources")).includes("as of that refresh, not live"));
  check("entries are ordered by their feed timestamps, the one without a timestamp last",
    JSON.stringify(await entries()) === JSON.stringify(["Simulated: Minutes of the Federal Open Market Committee",
      PAYROLL, STATEMENT, CPI, NO_TIME]), JSON.stringify(await entries()));
  const statement = await evaluate(`(() => { const li = [...document.querySelectorAll(".inbox-item")]
    .find((e) => e.querySelector("h3").textContent === ${JSON.stringify(STATEMENT)});
    const a = li.querySelector(".inbox-item-meta a");
    return { meta: li.querySelector(".inbox-item-meta").textContent, href: a.getAttribute("href"), target: a.target, rel: a.rel,
             time: li.querySelector(".inbox-item-time").textContent, fresh: li.querySelector(".inbox-item-fresh").textContent }; })()`);
  check("an entry shows its category, publisher, official link, raw feed timestamp and retrieval time",
    statement.meta.includes("Monetary policy") && statement.meta.includes("Board of Governors of the Federal Reserve System") &&
    statement.href === STATEMENT_LINK && statement.target === "_blank" && statement.rel === "noreferrer" &&
    statement.time.includes("Feed timestamp (RSS pubDate): Wed, 16 Sep 2026 18:00:00 GMT = 2026-09-16 18:00 UTC") &&
    statement.time.includes("Not a verified release time") && /^Retrieved \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC\. First retrieved \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC: when this inbox first saw it, not when it was published\.$/.test(statement.fresh),
    JSON.stringify(statement));
  const fedCard = await text('.inbox-source[data-source="fed-monetary"] .inbox-source-retrieval');
  check("each source states its recorded request: status, complete body, hash, kept copy, validators, parser, counts",
    /^Request 1, \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC: HTTP 200, body received complete, [\d,]+ bytes \(SHA-256 [0-9a-f]{12}…\), kept privately\. The response gave no cache validators\. Parsed by event-inbox-parser-0\.1\. Entries: 2 new, 0 unchanged, 0 changed\. 1 recorded request\.$/
      .test(fedCard), fedCard);
  const refreshed = await text(".inbox-message");
  check("the refresh says what each source added and that nothing was triaged or analyzed",
    refreshed.includes("Nothing was triaged or analyzed.") && refreshed.includes("Federal Reserve: monetary policy press releases: 2 new, 0 unchanged, 0 changed."),
    refreshed);
  check("every entry states its held text and, from local records, that it is not processed",
    await waitFor(`[...document.querySelectorAll(".inbox-item")].every((li) =>
      li.querySelector(".inbox-item-text")?.textContent.startsWith("Held text: the headline") &&
      li.querySelector(".inbox-item-processing")?.textContent === "Not processed")`));
  check("each requested source has one write-once retrieval record and its response kept beside the inbox",
    ["bls-cpi", "bls-empsit", "eia-todayinenergy", "fed-monetary", "wto-news"].every((key) =>
      JSON.stringify(folder("event-inbox", "acquisitions", key)) === JSON.stringify(["000001.json"]) &&
      folder("event-inbox", "raw", key).length === 1));
  check("an entry without a feed timestamp says so",
    (await evaluate(`[...document.querySelectorAll(".inbox-item")].find((e) => e.querySelector("h3").textContent ===
      ${JSON.stringify(NO_TIME)}).textContent`)).includes("The feed gives no timestamp for this entry."));

  // 3. Choosing an entry fills only the headline and official link; the form is complete only with the operator's work.
  await send("Emulation.setTimezoneOverride", { timezoneId: "Pacific/Pago_Pago" });
  check("Analyze this event fills the form's headline and official link, nothing else",
    await choose(STATEMENT) && await waitFor(`!!document.querySelector(".intake-origin")`) &&
    JSON.stringify(await formValues()) === JSON.stringify({ headline: STATEMENT, url: STATEMENT_LINK, date: "", time: "",
                                                             offset: "", text: "" }), JSON.stringify(await formValues()));
  const origin = await text(".intake-origin");
  check("the form shows the feed timestamp as a suggestion, apart from the published text",
    origin.includes("Feed timestamp (RSS pubDate)") && origin.includes("Wed, 16 Sep 2026 18:00:00 GMT") &&
    origin.includes("Suggestion: 2026-09-16 18:00:00 UTC+00:00") && origin.includes("not a verified release") &&
    origin.includes("Feed excerpt, not the published text") && origin.includes("only repeats the headline"), origin);
  await click(".intake-form button[type=submit]");
  await sleep(300);
  check("without a time and text nothing is captured", posts("/api/intake") === 0);
  await click(".intake-use-suggestion");
  const filled = await formValues();
  check("the suggestion fills exactly the feed's date, time and offset, even in another browser time zone",
    filled.date === "2026-09-16" && filled.time === "18:00:00" && filled.offset === "+00:00", JSON.stringify(filled));
  const pasted = "Simulated published text of the statement, pasted by the operator.\nSecond paragraph.";
  await setValue(".intake-form textarea", pasted);
  await click(".intake-form button[type=submit]");
  await sleep(300);
  check("a suggested time must be confirmed against the release before previewing",
    posts("/api/intake") === 0 && (await text(".intake-message")).includes("checked the date, time and offset"));
  await click(".intake-time-verified input");
  check("the exact request preview appears once the operator confirms the time", await preview());
  const times = { supplied: await text(".intake-time-supplied strong"), utc: await text(".intake-time-utc strong") };
  const requestText = await evaluate(`document.querySelector(".intake-request pre").textContent`);
  check("the preview holds the verified time and the operator's text, unshifted by the browser's zone",
    times.supplied === "2026-09-16T18:00:00+00:00" && times.utc === "2026-09-16T18:00:00Z" &&
    requestText.includes("Simulated published text of the statement") && requestText.includes(STATEMENT_LINK),
    JSON.stringify(times));
  await send("Emulation.setTimezoneOverride", { timezoneId: "" });

  // 4. One explicitly approved local mock, a saved human review, and a reload.
  check("approval stays explicit and the local mock is the default",
    await evaluate(`document.querySelector('.intake-source-choice input[value="mock"]').checked &&
      document.querySelector(${JSON.stringify(approve)}).disabled`));
  await click(".intake-confirm input");
  await click(approve);
  check("one mock draft opens in the review screen",
    await waitFor(`!!document.querySelector(".human-review") && location.search.startsWith("?draft=")`, 15000));
  const draft = (await evaluate("location.search")).slice(7);
  await evaluate(`[...document.querySelectorAll(".review-status input")][1].click()`);
  await setValue(notes, "Reviewed after choosing the event from the inbox.");
  await click(".review-save-bar button");
  check("the human review is saved", await waitFor(`document.querySelector(".review-message.is-saved")?.textContent.includes("Saved version 1")`));
  check("exactly one capture and one attempt, sent from the approved saved request",
    folder("intake").length === 1 && folder("tracker-attempts").length === 1 &&
    readFileSync(join(served, "intake", folder("intake")[0], "request.json"))
      .equals(readFileSync(join(served, "tracker-attempts", folder("tracker-attempts")[0], "request.json"))));

  // 5. Choosing another entry while a preview is loaded asks first; keeping changes nothing, replacing clears approvals.
  await choose(CPI);
  check("leaving a loaded preview needs confirmation",
    await waitFor(`!!document.querySelector(".intake-replace")`) && (await text(".intake-replace")).includes("A saved preview is open") &&
    await evaluate(`!!document.querySelector(".intake-preview")`));
  await click(".intake-replace-keep");
  check("keeping the current work leaves the preview as it was",
    await waitFor(`!document.querySelector(".intake-replace")`) && await evaluate(`!!document.querySelector(".intake-preview")`));
  await choose(CPI);
  await waitFor(`!!document.querySelector(".intake-replace")`);
  await click(".intake-replace-accept");
  check("replacing starts the form from the new entry and leaves the saved capture in Saved events",
    await waitFor(`!document.querySelector(".intake-preview") && !!document.querySelector(".intake-origin")`) &&
    (await formValues()).headline === CPI && folder("intake").length === 1 &&
    await waitFor(`document.querySelectorAll(".intake-saved-list li").length === 1`));

  // 6. A mock refusal from the CPI entry; the feed's excerpt never enters the request.
  await click(".intake-use-suggestion");
  await click(".intake-time-verified input");
  await setValue(".intake-form textarea", "Simulated CPI release text pasted by the operator.");
  await preview();
  check("the new preview starts with every approval cleared",
    !(await evaluate(`document.querySelector(".intake-confirm input").checked`)) &&
    await evaluate(`document.querySelector('.intake-source-choice input[value="mock"]').checked`));
  check("the feed excerpt is not the published text in the request",
    !(await evaluate(`document.querySelector(".intake-request pre").textContent`)).includes("the all items index rose"));
  await evaluate(`document.querySelectorAll(".intake-mock-choice input")[1].click()`);
  await click(".intake-confirm input");
  await click(approve);
  check("a mock refusal opens for review", await waitFor(`location.search !== "?draft=${draft}" &&
    document.querySelector(".draft-panel h3")?.textContent === ${JSON.stringify(CPI)}`, 15000) &&
    await waitFor(`document.querySelector(".draft-outcome .outcome-chip")?.textContent === "No draft"`));

  // 7. The saved review survives a reload, and the inbox is read again from its cache only.
  const requestsBefore = feedRequests().length;
  await open(`/?draft=${draft}`);
  check("after a reload the review is still saved",
    await waitFor(`document.querySelector(".review-dirty")?.textContent === "All changes saved · version 1"`) &&
    (await value(notes)) === "Reviewed after choosing the event from the inbox.");
  check("the reload shows the cached entries without requesting any feed",
    await waitFor(`document.querySelectorAll(".inbox-item").length === 5`) && feedRequests().length === requestsBefore);
  const chips = () => evaluate(`Object.fromEntries([...document.querySelectorAll(".inbox-item")].map((li) =>
    [li.querySelector("h3").textContent, li.querySelector(".inbox-item-processing")?.textContent]))`);
  check("each entry's processing is read from local records: captured entries name their saved events, the rest stay not processed",
    await waitFor(`!!document.querySelector(".inbox-item-processing")`) && (await chips())[STATEMENT] === "1 saved event" && (await chips())[CPI] === "1 saved event" &&
    (await chips())[PAYROLL] === "Not processed" && (await chips())[NO_TIME] === "Not processed", JSON.stringify(await chips()));

  // 8. An entry with no feed timestamp: no suggestion, and the operator's own time is used.
  await choose(NO_TIME);
  await waitFor(`!!document.querySelector(".intake-origin")`);
  check("an entry without a timestamp offers no suggestion and leaves the time empty",
    !(await evaluate(`!!document.querySelector(".intake-use-suggestion")`)) &&
    (await text(".intake-origin-suggestion")).includes("The feed gives no timestamp") &&
    (await formValues()).date === "" && (await formValues()).time === "");
  await setValue(".intake-form textarea", "Simulated employment text typed by the operator.");
  // 9. Unsaved edits are protected.
  await choose(PAYROLL);
  check("choosing another entry over unsaved edits asks first",
    await waitFor(`(document.querySelector(".intake-replace")?.textContent ?? "").includes("unsaved edits")`));
  await click(".intake-replace-keep");
  check("keeping the edits leaves them in place",
    (await formValues()).text === "Simulated employment text typed by the operator." && (await formValues()).headline === NO_TIME);
  await setValue('.intake-form input[type="date"]', "2026-09-04");
  await setValue('.intake-form input[type="time"]', "08:30");
  await setValue(".intake-time select", "-04:00");
  // 10. No switching while an action is in flight; the capture still completes.
  await send("Fetch.enable", { patterns: [{ urlPattern: "*/api/intake", requestStage: "Request" }] });
  await click(".intake-form button[type=submit]");
  const pausedCapture = await until(() => held.length > 0);
  check("while the capture is in flight, no entry can be chosen", pausedCapture &&
    await waitFor(`[...document.querySelectorAll(".inbox-analyze")].every((b) => b.disabled)`) &&
    await evaluate(`!document.querySelector(".intake-preview")`));
  for (const requestId of held.splice(0)) await send("Fetch.continueRequest", { requestId });
  await send("Fetch.disable");
  check("the operator's own time is previewed without a feed suggestion",
    await preview(false) && (await text(".intake-time-supplied strong")) === "2026-09-04T08:30:00-04:00" &&
    await analyzeEnabled());

  // 11. A second refresh: one source fails and keeps its earlier entry; a changed title never touches saved captures.
  const saved = captureHashes();
  await click(".inbox-refresh");
  check("a partly failed refresh says so", await waitFor(`(document.querySelector(".inbox-message")?.textContent ?? "").includes("did not refresh")`, 15000));
  const states = await sourceStates();
  const cpiCard = await text('.inbox-source[data-source="bls-cpi"]');
  check("the failed source keeps its last good entry, marked as from an earlier retrieval, with the error shown",
    states["bls-cpi"] === "failed" && states["fed-monetary"] === "ok" && cpiCard.includes("HTTP 503") &&
    (await entries()).includes(CPI) && (await evaluate(`[...document.querySelectorAll(".inbox-item")].find((e) =>
      e.querySelector("h3").textContent === ${JSON.stringify(CPI)}).textContent`)).includes("did not succeed"), cpiCard);
  check("the edited title appears in the inbox", (await entries()).includes(`${STATEMENT} (title edited in the feed)`));
  const second = await text(".inbox-message");
  check("the second refresh reports the changed entry, the reused ones and the failed source",
    second.includes("Federal Reserve: monetary policy press releases: 0 new, 1 unchanged, 1 changed.") &&
    second.includes("BLS: Consumer Price Index: did not refresh (HTTP 503); its earlier entries are kept."), second);
  const cpiRetrieval = await text('.inbox-source[data-source="bls-cpi"] .inbox-source-retrieval');
  check("the failed request is recorded as such, beside the earlier one",
    /^Request 2, .*: HTTP 503, not retrieved\. HTTP 503 from the publisher\..* 2 recorded requests\.$/.test(cpiRetrieval) &&
    JSON.stringify(folder("event-inbox", "acquisitions", "bls-cpi")) === JSON.stringify(["000001.json", "000002.json"]),
    cpiRetrieval);
  check("saved captures and their requests are byte-for-byte unchanged by the refresh",
    JSON.stringify(captureHashes()) === JSON.stringify(saved) && Object.keys(saved).length >= 9, Object.keys(saved).length);
  check("only the two refreshes reached the feeds: ten requests to the allowlisted URLs",
    feedRequests().length === 10 && feedRequests().every((r) => FEEDS.includes(r.url)));

  // 12. Reads only, and nothing outside the local server.
  const writes = requests.filter((r) => r.method !== "GET").map((r) => new URL(r.url).pathname.replace(/\/api\/intake\/[^/]+\//, "/api/intake/*/")
    .replace(/\/api\/drafts\/[^/]+\//, "/api/drafts/*/"));
  const allowed = new Set(["/api/inbox/refresh", "/api/intake", "/api/intake/*/mock-drafts", "/api/drafts/*/reviews"]);
  check("every write was an explicit action: two refreshes, three captures, two mocks, one review",
    writes.every((path) => allowed.has(path)) && posts("/api/inbox/refresh") === 2 && writes.filter((p) => p === "/api/intake").length === 3 &&
    writes.filter((p) => p.endsWith("mock-drafts")).length === 2 && writes.filter((p) => p.endsWith("reviews")).length === 1,
    JSON.stringify(writes));
  const outside = requests.filter(({ url }) => !url.startsWith(base) && !url.startsWith("data:") && url !== "about:blank");
  check("the page requested nothing outside the local server", outside.length === 0, outside.map((r) => r.url).join(", "));
  ws.close();
} catch (error) {
  check("the inbox browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(500);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
