// Browser acceptance check for headline triage, in one headless Chrome against tests/review_browser_server.py with
// --simulated-feeds triage (SYNTHETIC feeds behind the five allowlisted URLs) and --simulated-triage (an in-process fake
// that answers triage requests by the supplied titles and records every request it receives). Model calls are counted
// from the fake's own records, not from the page. The journey:
// refresh -> select seven entries -> preview the planned request -> approve one simulated response -> add one entry: only
// it is triaged, with earlier entries as comparison context -> previewing again, reloading and restarting request
// nothing -> grouped and ungrouped views, sources and Analyze this event -> failure probes stay unresolved and are
// requested again only when ticked -> concurrent approvals send once -> a refresh drops one entry (retained history,
// result reused) and edits another (new version pending) -> a restart with paid triage enabled: simulated results never
// count as paid ones, and a paid request needs its own approval. Nothing outside the local server is requested.
//
//   cd frontend; npm run build; npm run test:browser:triage
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

const STATEMENT = "Simulated: Federal Reserve issues FOMC statement";
const NOTE = "Simulated: Implementation Note issued September 16, 2026";
const CORRECTION = "Simulated: Correction to the FOMC statement of September 16, 2026";
const GENERIC = "Simulated: Federal Reserve Board announcement";
const MINUTES = "Simulated: Minutes of the Federal Open Market Committee";
const JOBS = "Simulated: The Employment Situation — September 2026";
const AUGUST = "Simulated: The Employment Situation — August 2026";
const CPI = "Simulated: Consumer Price Index — August 2026";
const MALFORMED = "Simulated triage probe: malformed reply";
const MISSING = "Simulated triage probe: missing result";
const NO_REPLY = "Simulated triage probe: no reply";
const SEVEN = [[STATEMENT, "20260916a.htm"], [STATEMENT, "20260729a.htm"], [CORRECTION], [MINUTES], [JOBS], [AUGUST], [CPI]];

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const root = mkdtempSync(join(tmpdir(), "second-order-triage-check-"));
const served = join(root, "served");
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const folder = (...parts) => (existsSync(join(served, ...parts)) ? readdirSync(join(served, ...parts)).sort() : []);
const calls = () => folder("simulated-triage").filter((name) => name.startsWith("request-")).length;
const sent = (n) => JSON.parse(readFileSync(join(served, "simulated-triage", `request-${n}.json`), "utf8"));
const received = (n) => JSON.parse(readFileSync(join(served, "simulated-triage", `received-${n}.json`), "utf8"));
const payload = (request) => { const text = request.messages[0].content; return JSON.parse(text.slice(text.indexOf("\n\n{") + 2)); };
const savedRequests = () => folder("headline-triage", "requests");
const feedCalls = () => existsSync(join(served, "simulated-feeds", "requests.jsonl"))
  ? readFileSync(join(served, "simulated-feeds", "requests.jsonl"), "utf8").trim().split("\n").filter(Boolean).length : 0;

async function startServer(extra) {
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    "--simulated-feeds", "triage", ...extra], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  for (let i = 0; i < 150; i++) {
    try { if ((await fetch(`${base}/api/drafts`)).ok) return { base, server }; } catch { await sleep(200); }
  }
  throw new Error("The review server did not start.");
}

try {
  mkdirSync(served);
  let { base, server } = await startServer(["--simulated-triage"]);
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
    await waitFor("document.readyState === 'complete' && !!document.querySelector('.triage-bar')");
  };
  const entryJs = (title, tail = "") => `[...document.querySelectorAll(".inbox-item")].find((li) =>
    li.querySelector("h3").textContent === ${JSON.stringify(title)} &&
    (li.querySelector(".inbox-item-meta a")?.getAttribute("href") ?? "").endsWith(${JSON.stringify(tail)}))`;
  const select = (title, tail = "") => evaluate(`(() => { const input = (${entryJs(title, tail)})
    ?.querySelector(".inbox-select input"); if (!input || input.disabled) return false; input.click(); return true; })()`);
  const selectAll = async (list) => { let ok = true; for (const [title, tail] of list) ok = (await select(title, tail)) && ok; return ok; };
  const rowJs = (title, tail = "") => `[...document.querySelectorAll(".triage-results .triage-row")].filter((li) =>
    li.querySelector(".triage-row-title").textContent === ${JSON.stringify(title)} &&
    (li.querySelector(".triage-row-meta a")?.getAttribute("href") ?? "").endsWith(${JSON.stringify(tail)}))`;
  const preview = async () => {
    const before = await evaluate(`document.querySelector(".triage-message")?.textContent ?? ""`);
    await click(".triage-preview");
    await waitFor(`!document.querySelector(".triage-preview").textContent.includes("Resolving")`);
    return waitFor(`!!document.querySelector(".triage-plan") && (document.querySelector(".triage-message")?.textContent ?? "") !== ${JSON.stringify(before)}`);
  };
  const approve = async () => {
    await click(".triage-confirm input");
    await click(".triage-approve");
    return waitFor(`(document.querySelector(".triage-message")?.textContent ?? "").includes("recorded")`, 15000);
  };
  const counts = () => evaluate(`Object.fromEntries([...document.querySelectorAll(".triage-plan-counts span")].map((s) =>
    [s.textContent.replace(/^\\d+\\s*/, ""), Number(s.querySelector("strong").textContent)]))`);
  const statuses = () => evaluate(`[...document.querySelectorAll(".triage-results .triage-row")].map((r) => r.dataset.status)`);

  // 1. A first visit: nothing selected, nothing planned, nothing requested.
  await open("/");
  check("the Event inbox shows headline triage with nothing selected and preview unavailable",
    (await text(".triage-count")) === "0 of 25 selected" && await evaluate(`document.querySelector(".triage-preview").disabled`) &&
    await evaluate(`document.querySelector('.triage-mode-choice input[value="paid"]').disabled`));
  await click(".inbox-refresh");
  check("Refresh events lists the twelve simulated entries and triages nothing",
    await waitFor(`document.querySelectorAll(".inbox-item").length === 12`, 15000) && calls() === 0 &&
    savedRequests().length === 0);

  // 2. Seven entries: everything is missing, so one request is planned and saved, and nothing is sent.
  check("seven entries can be selected, including both entries with the same title", await selectAll(SEVEN) &&
    (await text(".triage-count")) === "7 of 25 selected");
  check("Preview triage plans one request for the seven missing results", await preview() &&
    JSON.stringify(await counts()) === JSON.stringify({ "saved results reused": 0, "need a result": 7,
      "earlier entries as comparison context only": 0, "unresolved": 0, "from an earlier version": 0 }) &&
    (await text(".triage-plan-requests")).startsWith("Planned requests: 1, with 7 entries to triage"), JSON.stringify(await counts()));
  const request = JSON.parse(await text(".triage-request pre"));
  check("the preview shows Claude Haiku 5.5 at low effort, adaptive thinking and a bounded output",
    request.model === "claude-haiku-5-5" && request.output_config.effort === "low" && request.thinking.type === "adaptive" &&
    request.max_tokens === 4000 + 320 * 7 && !("temperature" in request) && !("tools" in request));
  check("the estimate explains its assumptions and is not a billing ceiling",
    (await text(".triage-estimate")).includes("not a guaranteed billing ceiling") &&
    await evaluate(`document.querySelectorAll(".triage-estimate li").length === 4`));
  check("previewing saved the exact request and sent nothing; every entry shows as pending",
    savedRequests().length === 1 && calls() === 0 && (await statuses()).every((status) => status === "process"));
  const firstId = await evaluate(`document.querySelector(".triage-panel").dataset.triage`);

  // 3. One approved simulated response, then the results are saved for reuse.
  check("approving the simulated response records it once", await approve() && calls() === 1 &&
    payload(sent(1)).entries.length === 7 && !received(1).has_key &&
    readFileSync(join(served, "simulated-triage", "request-1.json")).equals(
      readFileSync(join(served, "headline-triage", "requests", firstId, "request.json"))));
  check("afterwards all seven reuse their saved results and nothing more is planned",
    await waitFor(`[...document.querySelectorAll(".triage-results .triage-row")].every((r) => r.dataset.status === "reuse")`) &&
    (await text(".triage-plan-requests")).startsWith("Planned requests: none"));

  // 4. One added entry is triaged alone; earlier entries come along only as comparison context.
  await select(NOTE);
  await preview();
  check("adding one entry plans only that entry, with its comparison candidates as context",
    JSON.stringify(await counts()) === JSON.stringify({ "saved results reused": 7, "need a result": 1,
      "earlier entries as comparison context only": 2, "unresolved": 0, "from an earlier version": 0 }) &&
    (await text(".triage-plan-requests")).includes("of its input tokens are comparison context, billed like the rest"),
    JSON.stringify(await counts()));
  await approve();
  const added = payload(sent(2));
  check("the second request carries only the new entry in full, and two earlier titles as context",
    calls() === 2 && added.entries.length === 1 && added.entries[0].title === NOTE && added.comparison_context.length === 2 &&
    added.comparison_context.every((entry) => !("excerpt" in entry) && Object.keys(entry).length === 6) &&
    !JSON.stringify(sent(2).output_config.format.schema.properties.results.items.properties.id.enum).includes("0916a."),
    JSON.stringify(added.comparison_context.map((entry) => entry.title)));
  check("the earlier seven keep the results of the first request",
    await waitFor(`[...document.querySelectorAll(".triage-results .triage-row")].every((r) => r.dataset.status === "reuse")`) &&
    await evaluate(`[...document.querySelectorAll(".triage-results .triage-row")].filter((r) =>
      r.querySelector(".triage-row-provenance code")?.textContent === ${JSON.stringify(firstId)}).length === 7`));

  // 5. Previewing again, reloading and restarting the page request nothing.
  const recordsBefore = savedRequests().length;
  await preview();
  check("previewing the same entries again plans nothing and sends nothing",
    (await text(".triage-message")).includes("Nothing to request") && calls() === 2 && savedRequests().length === recordsBefore &&
    !(await evaluate(`!!document.querySelector(".triage-approve")`)));
  await open("/");
  await waitFor(`document.querySelectorAll(".inbox-item").length === 12`);
  await selectAll([...SEVEN, [NOTE]]);
  await preview();
  check("after a reload the same selection reuses every saved result with no request",
    (await text(".triage-message")).includes("Nothing to request") && calls() === 2 && feedCalls() === 5);

  // 6. The grouped and ungrouped views, original sources and Analyze this event.
  check("one collapsed 'Possibly the same event' group holds the statement and its implementation note",
    await evaluate(`document.querySelectorAll(".triage-group").length === 1 && !document.querySelector(".triage-group").open`) &&
    await evaluate(`(() => { const g = document.querySelector(".triage-group"); g.open = true;
      return [...g.querySelectorAll(".triage-row-title")].map((e) => e.textContent).sort().join("|"); })()`) ===
      [NOTE, STATEMENT].sort().join("|"));
  check("the same title on another meeting date stays a separate entry, never compared (49 days apart), so no note names it",
    await evaluate(`(() => { const rows = ${rowJs(STATEMENT, "20260729a.htm")};
      return rows.length === 1 && !rows[0].closest(".triage-group") && !rows[0].querySelector(".triage-note-row"); })()`));
  check("the correction stays its own entry with a note",
    await evaluate(`(() => { const rows = ${rowJs(CORRECTION)};
      return rows.length === 1 && !rows[0].closest(".triage-group") && rows[0].textContent.includes("Possible update or correction"); })()`));
  await evaluate(`[...document.querySelectorAll(".triage-layout input")][1].click()`);
  check("the ungrouped view lists all eight entries once, each with its official release and Analyze this event",
    await waitFor(`!document.querySelector(".triage-group") && document.querySelectorAll(".triage-results .triage-row").length === 8`) &&
    await evaluate(`[...document.querySelectorAll(".triage-results .triage-row")].every((row) => {
      const a = row.querySelector(".triage-row-meta a"); return a && a.target === "_blank" && !row.querySelector(".triage-analyze").disabled; })`));
  await evaluate(`(${rowJs(CPI)})[0].querySelector(".triage-analyze").click()`);
  check("Analyze this event from a triage row fills the Analyze an event form",
    await waitFor(`!!document.querySelector(".intake-origin")`) &&
    await evaluate(`document.querySelector('.intake-form input[type="url"]').value.endsWith("cpi_09112026.htm")`));

  // 7. Failure probes: recorded, never shown as triage, never re-queued on their own.
  for (const probe of [MALFORMED, MISSING, NO_REPLY]) {
    await click(".triage-clear");
    await select(probe);
    await preview();
    await click(".triage-confirm input");
    await click(".triage-approve");
    await waitFor(`(document.querySelector(".triage-message")?.textContent ?? "").includes("nothing from it is shown")`, 15000);
  }
  check("three failed responses were each requested once", calls() === 5);
  await click(".triage-clear");
  await select(MALFORMED);
  await preview();
  check("a failed entry stays visible as unresolved and is not planned again",
    JSON.stringify(await statuses()) === JSON.stringify(["unresolved"]) &&
    (await text(".triage-results .triage-claim")).includes("not valid JSON") &&
    (await text(".triage-plan-requests")).startsWith("Planned requests: none") && calls() === 5);
  await click(".triage-results .triage-reprocess input");
  check("ticking Request again asks for a new preview before anything can be approved",
    await waitFor(`!!document.querySelector(".triage-stale")`));
  await preview();
  check("the explicit re-request plans it again and is sent once more", (await counts())["need a result"] === 1 &&
    (await text(".triage-confirm")).includes("re-requests 1 entry") && await approve() && calls() === 6);

  // 8. Concurrent approvals of one planned request (repeated clicks, other tabs) send it once.
  await click(".triage-clear");
  await select(GENERIC);
  await preview();
  const concurrent = await evaluate(`(async () => {
    const id = document.querySelector(".triage-panel").dataset.triage;
    const sha = document.querySelector(".triage-request-hash code").textContent;
    const body = JSON.stringify({ request_sha256: sha, approve_simulated_response: true, reprocess_ids: [],
                                  comparison_pairs: [] });
    const post = () => fetch("/api/triage/" + id + "/simulated", { method: "POST", body,
      headers: { "Content-Type": "application/json", "X-Second-Order-Triage": "1" } }).then((r) => r.status);
    return (await Promise.all([post(), post(), post(), post()])).sort();
  })()`);
  check("four concurrent approvals of one request send it once", JSON.stringify(concurrent) === "[201,409,409,409]" &&
    calls() === 7, JSON.stringify(concurrent));

  // 9. A refresh drops one entry (retained history, result reused) and edits another (a new version, pending).
  await click(".inbox-refresh");
  await waitFor(`document.querySelectorAll(".inbox-items:not(.inbox-retained-items) > .inbox-item").length === 11`, 15000);
  check("the refresh made no model call", calls() === 7);
  check("the dropped entry is offered as retained history", (await text(".inbox-history-toggle")) === "Show retained headlines (1)");
  await click(".inbox-history-toggle");
  check("retained history shows when it was last seen in its feed",
    await waitFor(`!!document.querySelector(".inbox-retained-items .inbox-item.is-retained")`) &&
    (await text(".inbox-retained-items .inbox-item-fresh")).startsWith("Retained history: last seen in its feed"));
  await click(".triage-clear");
  await selectAll([[AUGUST], [JOBS], [NOTE + " (edited)"]]);
  await preview();
  const rows = await evaluate(`[...document.querySelectorAll(".triage-results .triage-row")].map((r) =>
    [r.querySelector(".triage-row-title").textContent, r.dataset.status, !!r.querySelector(".triage-location"),
     r.querySelector(".triage-versions")?.textContent ?? ""])`);
  const byTitle = Object.fromEntries(rows.map(([title, ...rest]) => [title, rest]));
  check("the retained entry reuses its saved result; the edited one is a new version pending approval",
    JSON.stringify(byTitle[AUGUST]?.slice(0, 2)) === JSON.stringify(["reuse", true]) && byTitle[JOBS]?.[0] === "reuse" &&
    byTitle[NOTE + " (edited)"]?.[0] === "process" && byTitle[NOTE + " (edited)"]?.[2].includes("1 earlier version") &&
    calls() === 7, JSON.stringify(rows));

  // 10. Narrow screens: no horizontal scrolling with the panel open.
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 1, mobile: true });
  await sleep(300);
  check("at phone width the triage panel causes no horizontal page scroll",
    await evaluate(`document.documentElement.scrollWidth <= window.innerWidth + 1`));
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  // 11. A restart with paid triage enabled: saved results survive; simulated ones never count as paid results.
  server.kill();
  await sleep(500);
  ({ base, server } = await startServer(["--keep-records", "--simulated-paid-triage"]));
  await open("/");
  await waitFor(`document.querySelectorAll(".inbox-items:not(.inbox-retained-items) > .inbox-item").length === 11`);
  await selectAll([[JOBS], [CPI]]);
  await preview();
  check("after a restart the saved simulated results are reused with no request",
    (await text(".triage-message")).includes("Nothing to request") && calls() === 7);
  await evaluate(`document.querySelector('.triage-mode-choice input[value="paid"]').click()`);
  await preview();
  check("in paid mode the same entries still need results: simulated results never count",
    (await counts())["need a result"] === 2 && await waitFor(`!!document.querySelector(".triage-confirm.is-paid")`) &&
    (await text(".triage-confirm")).includes("not a billing ceiling") && await evaluate(`document.querySelector(".triage-approve").disabled`));
  check("one approved paid request is sent, with the dummy key, and its results are labelled paid",
    await approve() && calls() === 8 && received(8).x_api_key_is_the_dummy_key &&
    (await text(".triage-provenance")).includes("Results from paid claude-haiku-5-5 responses"));
  check("no record holds the key", folder("headline-triage", "requests").every((id) =>
    ["paid", "simulated"].every((mode) => folder("headline-triage", "requests", id, mode).every((name) =>
      !readFileSync(join(served, "headline-triage", "requests", id, mode, name), "utf8").includes("sk-ant-dummy")))));

  // 12. Only explicit actions wrote, and nothing outside the local server was requested.
  const writes = requests.filter((r) => r.method !== "GET").map((r) => new URL(r.url).pathname
    .replace(/\/api\/triage\/triage-[0-9a-f]{24}\//, "/api/triage/*/"));
  const allowed = new Set(["/api/inbox/refresh", "/api/triage", "/api/triage/*/simulated", "/api/triage/*/paid"]);
  check("every write was an explicit action: refreshes, previews and approvals",
    writes.every((path) => allowed.has(path)) && writes.filter((p) => p === "/api/inbox/refresh").length === 2 &&
    writes.filter((p) => p.endsWith("/paid")).length === 1, JSON.stringify(writes));
  const outside = requests.filter(({ url }) => !url.startsWith("http://127.0.0.1:") && !url.startsWith("data:") && url !== "about:blank");
  check("the page requested nothing outside the local server", outside.length === 0, outside.map((r) => r.url).join(", "));
  const pageErrors = consoleErrors.filter((error) => !/\/favicon\.ico$/.test(error.url) && !/status of 409/.test(error.text));
  check("the page logged no errors (the favicon probe and the deliberate 409s aside)", pageErrors.length === 0,
    JSON.stringify(pageErrors));
  ws.close();
} catch (error) {
  check("the triage browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(500);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
