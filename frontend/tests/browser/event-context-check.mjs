// Browser acceptance check for private market context, in one headless Chrome against tests/review_browser_server.py
// serving an empty temporary folder with --simulated-feeds context, --simulated-market, --market-context committed and a
// fixed market clock (9 October 2026, 11:00 in New York). The Board's server is an in-process fake answering with
// SYNTHETIC release packages (invented values in the format of the Board's H.15 XML package, labelled so on every
// record and on the page); the committed bundle of real H.15 downloads is read in place. Fake requests and their
// headers are read from the fake's own log.
//
// The journey: the Event Inbox offers Market context on Federal Reserve and BLS entries and explains why energy and
// trade entries have none -> an entry from 18 June 2025 needs a confirmed date, then shows real committed values with
// no request -> a September 2026 entry plans exactly one request, disclosed as a download of the full release package;
// a double click sends it once, and its reply (an empty web page) is recorded as failed and not retried -> a second,
// explicitly approved attempt keeps and accepts the package -> a recent entry and a July entry are covered by that
// package with no request -> the list reopens everything; a server restart, reloads and display settings request
// nothing -> narrow screens, another time zone, and only explicit writes, all local.
//
//   cd frontend; npm run build; npm run test:browser:context-events
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

const TWO = "RIFLGFCY02_N.B";
const TEN = "RIFLGFCY10_N.B";
const JUNE = "Simulated: FOMC statement of 18 June 2025";
const SEPTEMBER = "Simulated: FOMC statement of 16 September 2026";
const JULY = "Simulated: FOMC statement of 29 July 2026";
const JOBS = "Simulated: The Employment Situation — September 2026";
const ENERGY = "Simulated: Hydro-Québec electricity exports to New England fell";
const TRADE = "Simulated: Trade forecast raised for 2026";
const COMMITTED = join(repo, "content", "market-context");

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const root = mkdtempSync(join(tmpdir(), "second-order-event-context-check-"));
const served = join(root, "served");
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const log = join(served, "simulated-market", "requests.jsonl");
const PACKAGE = "https://www.federalreserve.gov/releases/h15/data/FRB_h15_xml.zip";
const boardRequests = () => (existsSync(log) ? readFileSync(log, "utf8").trim().split("\n").filter(Boolean)
  .map((line) => JSON.parse(line)) : []);
const boardCalls = () => boardRequests().map((request) => request.url);
const fingerprint = (folder) => readdirSync(folder, { recursive: true, withFileTypes: true })
  .filter((entry) => entry.isFile())
  .map((entry) => { const path = join(entry.parentPath ?? entry.path, entry.name);
    return `${path}:${createHash("sha256").update(readFileSync(path)).digest("hex")}`; }).sort().join("\n");
/** Invented values, exactly as tests/market_fakes.py derives them from a date: not H.15 observations. */
const synthetic = (iso) => {
  const ordinal = Date.UTC(...iso.split("-").map((part, i) => Number(part) - (i === 1 ? 1 : 0))) / 86_400_000 + 719_163;
  return [(3 + (ordinal % 50) / 100).toFixed(2), (4 + (ordinal % 40) / 100).toFixed(2)];
};
/** A committed source's exact text for a date and series, read from its CSV. */
const committed = (file, date, column) => readFileSync(join(COMMITTED, "sources", file), "utf8").split(/\r?\n/)
  .find((line) => line.startsWith(`${date},`)).split(",")[column];
const bp = (from, to) => {
  const hundredths = (text) => Math.round(Number(text) * 100);
  const change = hundredths(to) - hundredths(from);
  return `${change > 0 ? "+" : change < 0 ? "\u2212" : ""}${Math.abs(change)} bp`;
};

async function startServer(extra = []) {
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    "--simulated-feeds", "context", "--simulated-market", "--market-context", "committed",
    "--market-clock", "2026-10-09T15:00:00+00:00", ...extra], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  for (let i = 0; i < 150; i++) {
    try { if ((await fetch(`${base}/api/drafts`)).ok) return { base, server }; } catch { await sleep(200); }
  }
  throw new Error("The review server did not start.");
}

try {
  mkdirSync(served);
  const before = fingerprint(COMMITTED);
  let { base, server } = await startServer();
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
  const go = async (path, ready) => {
    await send("Page.navigate", { url: base + path });
    return waitFor(`document.readyState === 'complete' && ${ready}`, 15000);
  };
  const entryJs = (title) => `[...document.querySelectorAll(".inbox-item")].find((li) =>
    li.querySelector("h3").textContent === ${JSON.stringify(title)})`;
  const loaded = `!!document.querySelector("#context-date-title") && !document.querySelector('.event-context-state[role="status"]')`;
  const confirm = async () => {
    await click('.event-context-form input[name="convention"]');
    await click(".event-context-form button");
    return waitFor(`!!document.querySelector(".event-context-plan") && !!document.querySelector(".event-context-view")`, 15000);
  };
  const cell = (date, series) => text(`#context-data tr[data-date="${date}"] td[data-series="${series}"]`);
  const change = (key) => text(`tr[data-change="${key}"] td:last-child`);

  // 1. Entry points: Market context on Federal Reserve and BLS entries; energy and trade entries say why not.
  await go("/", "!!document.querySelector('.inbox-refresh')");
  await click(".inbox-refresh");
  await waitFor(`document.querySelectorAll(".inbox-item").length === 6`, 15000);
  const links = await evaluate(`Object.fromEntries([...document.querySelectorAll(".inbox-item")].map((li) =>
    [li.querySelector("h3").textContent, li.querySelector("a.inbox-context")?.getAttribute("href") ?? null]))`);
  check("Federal Reserve and BLS entries offer Market context; energy and trade entries do not",
    [JUNE, SEPTEMBER, JULY, JOBS].every((title) => links[title]?.startsWith("/market-context/inbox/")) &&
    links[ENERGY] === null && links[TRADE] === null, JSON.stringify(links));
  check("energy and trade entries explain that they are outside this first slice",
    await evaluate(`[${JSON.stringify(ENERGY)}, ${JSON.stringify(TRADE)}].every((title) => (${entryJs("X").replace('"X"', "title")})
      ?.querySelector(".inbox-context-outside")?.textContent.includes("not offered for energy or trade entries in this first slice"))`));
  check("refreshing the inbox requested nothing from the Board", boardCalls().length === 0);

  // 2. An entry from 18 June 2025: a suggestion, no context until confirmed, then real committed values, no request.
  await click(`a.inbox-context[href="${links[JUNE]}"]`);
  await waitFor(loaded, 15000);
  check("the page suggests the New York date of the feed timestamp and calls the timestamp metadata",
    (await text(".event-context-suggestion")).includes("18 Jun 2025 (14:00 New York time, UTC-04:00)") &&
    (await text(".event-context-suggestion")).includes("metadata, not a verified publication instant") &&
    (await text(".event-context-time")).includes("Wed, 18 Jun 2025 18:00:00 GMT") &&
    (await evaluate(`document.querySelector('.event-context-form input[name="context-date"]').value`)) === "2025-06-18");
  check("nothing is shown or planned until the date and its convention are confirmed",
    !(await evaluate(`!!document.querySelector(".event-context-view") || !!document.querySelector(".event-context-plan")`)) &&
    await evaluate(`document.querySelector(".event-context-form button").disabled`));
  check("confirming shows the window with no request: the committed downloads cover it", await confirm() &&
    (await evaluate(`document.querySelector(".event-context-plan").dataset.requests`)) === "0" &&
    (await text(".event-context-approve button")) === "No request needed" &&
    await evaluate(`document.querySelector(".event-context-approve button").disabled`));
  const juneExpected = [[TWO, 1, "2025-06-17", "2025-06-20"], [TWO, 5, "2025-06-17", "2025-06-26"],
                        [TEN, 1, "2025-06-17", "2025-06-20"], [TEN, 5, "2025-06-17", "2025-06-26"]]
    .map(([series, horizon, from, to]) => {
      const column = series === TWO ? 1 : 2;
      return [`${series}-${horizon}`, bp(committed("fomc-2025-06-18.csv", from, column), committed("fomc-2025-06-18.csv", to, column))];
    });
  const juneShown = await Promise.all(juneExpected.map(([key]) => change(key)));
  check("the changes are the real committed values' differences in basis points, skipping the 19 June holiday",
    juneExpected.every(([, expected], i) => juneShown[i] === expected) &&
    (await cell("2025-06-19", TWO)) === "—" &&
    (await text('#context-data tr[data-date="2025-06-19"] .context-note')) === "No session: SIFMA holiday" &&
    (await cell("2025-06-17", TWO)) === `${committed("fomc-2025-06-18.csv", "2025-06-17", 1)}%`,
    JSON.stringify({ juneExpected, juneShown }));
  check("provenance names the committed downloads, read in place, and no fake-data notice is shown", await evaluate(`(() => {
    const items = [...document.querySelectorAll(".event-context-retrievals li")];
    return items.length > 0 && items.every((li) => li.dataset.origin === "bundle" && li.textContent.includes("read in place")) &&
      !document.querySelector(".event-context-simulated");
  })()`));
  const allRows = await evaluate(`document.querySelectorAll("#context-data tbody tr").length`);
  await click(".event-context-toggle input");
  const sessionRows = await evaluate(`document.querySelectorAll("#context-data tbody tr").length`);
  await click(".event-context-toggle input");
  check("a display setting filters the table locally and requests nothing",
    allRows === 29 && sessionRows === 20 && boardCalls().length === 0, `${allRows} ${sessionRows}`);

  // 3. 16 September 2026: exactly one planned request, for the full release package; a double click sends it once.
  await go(links[SEPTEMBER], loaded);
  await confirm();
  const plan = await text(".event-context-plan");
  check("the plan shows the source, both series, the package address and download, no key, no charge and the notice",
    (await evaluate(`document.querySelector(".event-context-plan").dataset.requests`)) === "1" &&
    plan.includes(PACKAGE) && plan.includes(TWO) && plan.includes(TEN) &&
    plan.includes("downloads the Board's complete H.15 release package") &&
    plan.includes("not a two-series or date-bounded download") &&
    plan.includes("every series of the release (daily, weekly, monthly and annual, current and discontinued)") &&
    plan.includes("4,285,147 bytes") && plan.includes("None: the Board's public website needs no key") &&
    plan.includes("None: the download is free") && plan.includes("Build Your Package") &&
    plan.includes("begin with a DOCTYPE declaration"), plan);
  check("the approval names the download, not a date range",
    (await text(".event-context-approve button")) === "Approve 1 download of the Board's H.15 release package (attempt 1)");
  const posts = () => requests.filter((r) => r.method === "POST" && r.url.endsWith("/api/market-context/retrievals")).length;
  const postsBefore = posts();
  await evaluate(`(() => { const button = document.querySelector(".event-context-approve button"); button.click(); button.click(); })()`);
  await waitFor(`!!document.querySelector(".event-context-result.is-error")`, 15000);
  const failure = await text(".event-context-result");
  check("a double click sends one approval; the fake receives one request, for the package only",
    posts() - postsBefore === 1 && boardCalls().length === 1 && boardCalls()[0] === PACKAGE, JSON.stringify(boardCalls()));
  const sent = boardRequests()[0]?.headers ?? {};
  check("the request carries the approved headers and no cookie",
    sent.accept === "*/*" && sent["accept-encoding"] === "identity" && sent["user-agent"]?.startsWith("SecondOrder/0.1") &&
    !("cookie" in sent), JSON.stringify(sent));
  check("an empty web page is recorded as a failed attempt, shown, and not retried",
    failure.includes("the reply was not kept") && failure.includes("web page") &&
    failure.includes("Nothing was retried automatically") && boardCalls().length === 1 &&
    await waitFor(`!!document.querySelector('.event-context-attempts li[data-outcome="refused_reply"]')`), failure);
  await go(links[SEPTEMBER], loaded);
  await sleep(500);
  check("reloading keeps the failed attempt visible, offers attempt 2 only as a new approval, and requests nothing",
    boardCalls().length === 1 && await evaluate(`!!document.querySelector('.event-context-attempts li[data-outcome="refused_reply"]')`) &&
    (await text(".event-context-approve button")).includes("attempt 2"));
  await click(".event-context-approve button");
  await waitFor(`!!document.querySelector(".event-context-result.is-done")`, 15000);
  await waitFor(`document.querySelector(".event-context-view")?.dataset.complete === "true"`);
  const [two15] = synthetic("2026-09-15");
  check("the second attempt kept and accepted the package; its values are shown, labelled as the synthetic fake's",
    boardCalls().length === 2 && (await cell("2026-09-15", TWO)) === `${two15}%` &&
    (await text(".event-context-simulated")).includes("not retrieved from the Board's server") &&
    (await text(".event-context-simulated")).includes("SYNTHETIC") &&
    (await text('.event-context-retrievals li[data-origin="package"]')).includes("full H.15 release package") &&
    (await text('.event-context-retrievals li[data-origin="package"]')).includes("SYNTHETIC") &&
    (await text('.event-context-attempts li[data-outcome="saved"]')).includes("the full H.15 release package"));

  // 4. The recent jobs report and a July statement: covered by the kept package, so nothing is requested.
  await go(links[JOBS], loaded);
  await confirm();
  check("a recent event is covered by the kept package; later sessions cannot be requested yet",
    (await evaluate(`document.querySelector(".event-context-plan").dataset.requests`)) === "0" &&
    (await text(".event-context-approve button")) === "No request needed" &&
    (await text(".event-context-plan")).includes("on or after today cannot be requested yet") && boardCalls().length === 2);
  await go(links[JULY], loaded);
  await confirm();
  check("a July statement is covered too: no request, a complete window",
    (await evaluate(`document.querySelector(".event-context-plan").dataset.requests`)) === "0" &&
    await waitFor(`document.querySelector(".event-context-view")?.dataset.complete === "true"`) && boardCalls().length === 2);

  // 5. The jobs report now: complete before today, future after it, and a holiday that is not a gap.
  await go(links[JOBS], loaded);
  check("a partial window distinguishes future sessions, holidays and weekends",
    (await text('#context-data tr[data-date="2026-10-09"] .context-note')) === "Not yet available: today or later" &&
    (await text('#context-data tr[data-date="2026-10-12"] .context-note')) === "No session: SIFMA holiday" &&
    (await text('#context-data tr[data-date="2026-10-10"] .context-note')) === "No session: weekend" &&
    (await cell("2026-10-08", TWO)) === `${synthetic("2026-10-08")[0]}%` &&
    (await change(`${TWO}-5`)).includes("today or later") && !(await change(`${TWO}-1`)).includes("Unavailable") &&
    (await evaluate(`document.querySelector(".event-context-plan").dataset.requests`)) === "0");

  // 6. The list reopens everything, without files or commands.
  await click('.site-nav a[href="/market-context"]');
  await waitFor(`document.querySelectorAll(".event-context-entry").length === 4`, 15000);
  const listed = await evaluate(`[...document.querySelectorAll(".event-context-entry")].map((li) => li.dataset.complete).sort().join()`);
  check("the list shows the four saved events, three complete and the recent one partial", listed === "false,true,true,true", listed);
  check("the list shows the reusable observations, the kept package and every attempt, failed included",
    (await evaluate(`document.querySelectorAll('.event-context-retrievals li[data-origin="bundle"]').length`)) === 12 &&
    (await evaluate(`document.querySelectorAll('.event-context-retrievals li[data-origin="package"]').length`)) === 1 &&
    (await evaluate(`[...document.querySelectorAll(".event-context-packages li")].map((li) => li.dataset.status).join()`)) ===
      "accepted" &&
    (await evaluate(`[...document.querySelectorAll(".event-context-attempts li")].map((li) => li.dataset.outcome).sort().join()`)) ===
      "refused_reply,saved");
  const reopened = (await evaluate(`[...document.querySelectorAll(".event-context-entry-title")].find((a) =>
    a.textContent === ${JSON.stringify(SEPTEMBER)})?.getAttribute("href")`));
  check("calls before the restart: two requests, both approved", boardCalls().length === 2);

  // 7. A server restart, reopening and reloading request nothing.
  server.kill();
  await sleep(600);
  ({ base, server } = await startServer(["--keep-records"]));
  await go(reopened, loaded);
  check("after a restart the saved event reopens with the same values and no request",
    (await cell("2026-09-15", TWO)) === `${two15}%` && boardCalls().length === 2 &&
    (await evaluate(`document.querySelector(".event-context-plan").dataset.requests`)) === "0");
  await go("/market-context", `document.querySelectorAll(".event-context-entry").length === 4`);
  check("the list after a restart requests nothing either", boardCalls().length === 2);

  // 8. Narrow screens and another time zone.
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  await go(reopened, loaded);
  await sleep(300);
  check("a phone-width page has no horizontal scroll and a narrow chart",
    await evaluate(`document.documentElement.scrollWidth <= window.innerWidth + 1`) &&
    (await evaluate(`document.querySelector(".context-chart svg").dataset.width`)) === "360");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Emulation.setTimezoneOverride", { timezoneId: "Asia/Tokyo" });
  await go(reopened, loaded);
  check("dates do not move with the browser's time zone",
    (await cell("2026-09-15", TWO)) === `${two15}%` &&
    (await evaluate(`document.querySelector("#context-data tbody tr").dataset.date`)) === "2026-09-02");
  await send("Emulation.setTimezoneOverride", { timezoneId: "" });

  // 9. Only explicit writes, nothing outside the local server, and the committed bundle unchanged.
  const writes = requests.filter((r) => r.method !== "GET").map((r) => new URL(r.url).pathname
    .replace(/\/api\/market-context\/inbox\/[^/]+\/confirm/, "/api/market-context/inbox/*/confirm"));
  const allowed = new Set(["/api/inbox/refresh", "/api/market-context/inbox/*/confirm", "/api/market-context/retrievals"]);
  check("every write was explicit: one refresh, four confirmations and two approvals",
    writes.every((path) => allowed.has(path)) && writes.filter((p) => p.endsWith("/confirm")).length === 4 &&
    writes.filter((p) => p.endsWith("/retrievals")).length === 2, JSON.stringify(writes));
  const outside = requests.filter(({ url }) => !url.startsWith("http://127.0.0.1:") && !url.startsWith("data:") && url !== "about:blank");
  check("the page requested nothing outside the local server", outside.length === 0, outside.map((r) => r.url).join(", "));
  check("the committed bundle is byte for byte unchanged", fingerprint(COMMITTED) === before);
  const pageErrors = consoleErrors.filter((error) => !/\/favicon\.ico$/.test(error.url));
  check("the page logged no errors (the favicon probe aside)", pageErrors.length === 0, JSON.stringify(pageErrors));
  ws.close();
} catch (error) {
  check("the event-context browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(500);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
