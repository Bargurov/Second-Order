// Browser acceptance check for the market-implied rate path, in one headless Chrome against
// tests/review_browser_server.py --rate-context synthetic: one SYNTHETIC workbook in the shape of the Atlanta Fed's MPT
// historical data, never a real estimate. No provider, network or credential is used; the research analysis is a $0
// local mock.
//
// The journey: capture an FOMC-shaped event -> both pages say no rate-path context is prepared, show the explicit
// command and keep meeting-specific pricing unavailable, and opening them writes nothing -> a research request, a mock
// analysis and a review are recorded by explicit clicks -> the explicit local commands retain the workbook and prepare
// the context, leaving every capture, request, attempt and review byte-identical -> the research page shows the first
// four windows (observation 15 Sep 2026, never the publication date), says the analysis did not carry this context and
// keeps its result and review unchanged -> the overview shows the same panel after Market context -> reloading writes
// nothing -> a non-Fed event gets no rate path -> phone width has no sideways scroll -> nothing outside the local
// server is requested.
//
//   cd frontend; npm run build; npm run test:browser:rate-path
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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

const FED_URL = "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm";
const SOURCE = "September 16, 2026\n\nSimulated committee issues statement\n\nThe Committee decided to raise the " +
  "target range by 1/4 percentage point, in support of the Committee\u2019s goals.\n\nEconomic activity is expanding " +
  "at a solid pace. Inflation remains elevated.";
const COMMAND = (id) => `python -m second_order rate-context prepare --capture ${id}`;
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const root = mkdtempSync(join(tmpdir(), "second-order-rate-path-check-"));
const served = join(root, "served");
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const sha = (path) => createHash("sha256").update(readFileSync(path)).digest("hex");
const everyFile = (path) => existsSync(path) ? readdirSync(path, { withFileTypes: true }).flatMap((entry) =>
  entry.isDirectory() ? everyFile(join(path, entry.name)) : [join(path, entry.name)]) : [];
const hashes = (...parts) => Object.fromEntries(everyFile(join(served, ...parts))
  .map((path) => [relative(served, path), sha(path)]));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const command = (...args) => {
  const run = spawnSync(python, ["-m", "second_order", "rate-context", ...args, "--data-dir", served],
                        { cwd: repo, encoding: "utf8" });
  return { code: run.status, body: run.status === 0 ? JSON.parse(run.stdout) : null, error: run.stderr };
};

try {
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    "--rate-context", "synthetic"], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
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
  const exists = (selector) => evaluate(`!!document.querySelector(${JSON.stringify(selector)})`);
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);
  const texts = (selector) => evaluate(`[...document.querySelectorAll(${JSON.stringify(selector)})]
    .map((element) => element.textContent)`);

  const requests = [];
  const errors = [];
  listeners.push((message) => {
    if (message.method === "Network.requestWillBeSent") {
      requests.push({ url: message.params.request.url, method: message.params.request.method });
    } else if (message.method === "Runtime.exceptionThrown") {
      errors.push(message.params.exceptionDetails.text);
    } else if (message.method === "Log.entryAdded" && message.params.entry.level === "error") {
      errors.push(`${message.params.entry.text} ${message.params.entry.url ?? ""}`);
    }
  });
  const posts = () => requests.filter((request) => request.method !== "GET").length;

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Log.enable");
  const desktop = () => send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1,
                                                                      mobile: false });
  await desktop();
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete'");
  };
  const captureEvent = async (headline, url) => {
    await open("/");
    await waitFor(`!!document.querySelector(".intake-form")`);
    await setValue('.intake-form input:not([type="url"]):not([type="date"]):not([type="time"])', headline);
    await setValue('.intake-form input[type="url"]', url);
    await setValue('.intake-form input[type="date"]', "2026-09-16");
    await setValue('.intake-form input[type="time"]', "14:00");
    await setValue(".intake-time select", "-04:00");
    await setValue(".intake-form textarea", SOURCE);
    await click(".intake-form button[type=submit]");
    await waitFor(`!!document.querySelector(".intake-preview")`);
  };
  const openResearch = async () => {
    await click('.intake-mode-choice input[value="research"]');
    await waitFor(`!!document.querySelector(".intake-open-research")`);
    await click(".intake-open-research");
    await waitFor(`location.pathname.endsWith("/research") && !!document.querySelector("#research-prepare, #research-request")`);
    return evaluate("decodeURIComponent(location.pathname.split('/')[3])");
  };
  const panelState = (id) => evaluate(`document.querySelector("#${id}")?.dataset.state ?? null`);
  const readPanel = (id) => waitFor(`!["loading", undefined].includes(document.querySelector("#${id}")?.dataset.state)`);

  // 1. Before any preparation both pages say so, show the explicit command and write nothing.
  await captureEvent("Federal Reserve issues FOMC statement", FED_URL);
  const captureId = await openResearch();
  const researchHref = `/events/capture/${encodeURIComponent(captureId)}/research`;
  const overviewHref = `/events/capture/${encodeURIComponent(captureId)}`;
  await readPanel("research-rate-path");
  check("the research page's panel says no rate-path context is prepared and shows the explicit local command",
    await panelState("research-rate-path") === "not_prepared" &&
    (await text("#research-rate-path .rate-path-command")) === COMMAND(captureId) &&
    (await text('#research-rate-path [data-gap="not_prepared"]')).includes("never by opening a page"));
  check("meeting-specific pricing is shown as unavailable even before preparation",
    (await text('#research-rate-path [data-meeting="unavailable"]')).includes("Meeting-specific pricing · Unavailable") &&
    (await text('#research-rate-path [data-meeting="unavailable"]')).includes("decision announced on 16 Sep 2026"));
  await open(overviewHref);
  await readPanel("overview-rate-path");
  check("the overview's panel says the same, and opening both pages created no rate-path records",
    await panelState("overview-rate-path") === "not_prepared" && !existsSync(join(served, "rate-context")) &&
    posts() === 1);

  // 2. A research request, a $0 mock analysis and a review, each by an explicit click.
  await open(researchHref);
  await waitFor(`!!document.querySelector(".research-prepare")`);
  await click(".research-prepare");
  await waitFor(`!!document.querySelector("#research-send")`);
  await evaluate(`document.querySelectorAll('input[name="research-mock"]')[0].click()`);
  await click("#research-send .intake-confirm input");
  await click(".research-send-mock");
  await waitFor(`!!document.querySelector("#research-result")`, 15000);
  await evaluate(`document.querySelectorAll('input[name="research-review-status"]')[1].click()`);
  await setValue(".research-notes textarea", "SYNTHETIC review saved before the rate path existed.");
  await click(".research-save-review");
  await waitFor(`document.querySelector(".research-versions li")?.textContent.includes("Version 1")`);
  const requestId = `${captureId}.research-prompt-2`;
  const shownBefore = await (await fetch(`${base}/api/research-analyses/${requestId}`)).json();
  check("the mock analysis and its review are recorded", shownBefore.result?.outcome === "analysis" &&
    shownBefore.reviews.records.length === 1);
  const protectedBefore = { ...hashes("intake"), ...hashes("research-analyses"), ...hashes("event-links") };

  // 3. The explicit local commands keep the workbook and prepare the context; nothing else changes.
  const digest = readFileSync(join(served, "rate-input", "sha256.txt"), "utf8").trim();
  const kept = command("retain", "--workbook", join(served, "rate-input", "synthetic-mpt.xlsx"), "--sha256", digest,
                       "--obtained-on", "2026-10-13", "--method", "SYNTHETIC: written by the browser check");
  check("the retain command keeps the workbook", kept.code === 0 && kept.body.retained_now === true, kept.error);
  const made = command("prepare", "--capture", captureId);
  check("the prepare command writes the context for the last observation before the publication date",
    made.code === 0 && made.body.saved_now === true && made.body.observation_date === "2026-09-15" &&
    same(made.body.windows, ["2026-12-16", "2027-03-17", "2027-06-16", "2027-09-15"]), made.error);
  const protectedAfter = { ...hashes("intake"), ...hashes("research-analyses"), ...hashes("event-links") };
  check("every capture, request, attempt, response and review file is byte-identical",
    same(protectedBefore, protectedAfter) && Object.keys(protectedBefore).length > 8);

  // 4. The research page: the first four windows, the separation from the analysis, the analysis unchanged.
  await open(researchHref);
  await readPanel("research-rate-path");
  const rows = await evaluate(`[...document.querySelectorAll("#research-rate-path .rate-path-table tbody tr")]
    .map((row) => [...row.querySelectorAll("th, td")].slice(0, 3).map((cell) => cell.textContent))`);
  check("the panel shows the first four windows with exact percents and their basis points",
    await panelState("research-rate-path") === "available" && rows.length === 4 &&
    same(rows[0], ["16 Dec 2026", "3.1550%315.50 bp", "2.9675%–3.3675%296.75–336.75 bp"]) &&
    same(rows.map((row) => row[0]), ["16 Dec 2026", "17 Mar 2027", "16 Jun 2027", "15 Sep 2027"]), JSON.stringify(rows));
  check("the observation is 15 Sep 2026; the same-day observation is named and not used",
    (await text("#research-rate-path [data-observation]")) === "15 Sep 2026" &&
    (await text("#research-rate-path .rate-path-note")).includes("observation dated 16 Sep 2026, the publication date"));
  const separate = await text("#research-rate-path .rate-path-separate");
  check("the panel says the analysis did not carry this context and was sent before it was prepared",
    separate.startsWith("Not part of this analysis.") && separate.includes("no model received it") &&
    separate.includes(", after it."), separate);
  const panelText = (await text("#research-rate-path")).toLowerCase();
  check("no probability, surprise or meeting-date reading appears in the windows",
    !(await text("#research-rate-path .rate-path-table")).toLowerCase().includes("prob") &&
    panelText.includes("it is not an fomc meeting date") && panelText.includes("no surprise measure"));
  const shownAfter = await (await fetch(`${base}/api/research-analyses/${requestId}`)).json();
  check("the research result and its review are unchanged: same view SHA-256, still one review",
    shownAfter.result_view_sha256 === shownBefore.result_view_sha256 && shownAfter.reviews.records.length === 1 &&
    (await texts(".research-versions li")).length === 1);

  // 5. The overview: the same panel, after Market context, with its own table of contents link.
  await open(overviewHref);
  await readPanel("overview-rate-path");
  check("the overview shows the panel after Market context, linked from its contents",
    await panelState("overview-rate-path") === "available" && await exists('.overview-toc a[href="#overview-rate-path"]') &&
    await evaluate(`!!(document.querySelector("#overview-market").compareDocumentPosition(
      document.querySelector("#overview-rate-path")) & Node.DOCUMENT_POSITION_FOLLOWING)`) &&
    (await texts("#overview-rate-path .rate-path-table tbody th")).length === 4);
  check("the yields' section carries no SOFR value and the panel carries no yield",
    !(await text("#overview-market")).includes("SOFR") && !(await text("#overview-rate-path")).includes("10-year"));
  check("the overview's panel does not speak for any analysis",
    !(await text("#overview-rate-path .rate-path-separate")).startsWith("Not part of this analysis."));

  // 6. Reading writes nothing.
  const everything = hashes();
  const before = posts();
  for (const path of [researchHref, overviewHref, researchHref]) {
    await open(path);
    await readPanel(path.endsWith("/research") ? "research-rate-path" : "overview-rate-path");
  }
  check("reloading both pages writes and sends nothing", same(hashes(), everything) && posts() === before);

  // 7. Another publisher's event gets no rate path.
  await captureEvent("Simulated agency release", "https://example.test/agency-release");
  const otherId = await openResearch();
  await open(`/events/capture/${encodeURIComponent(otherId)}`);
  await readPanel("overview-rate-path");
  check("an event that is not a Federal Reserve monetary-policy release gets no rate path",
    await panelState("overview-rate-path") === "unsupported" && !(await exists("#overview-rate-path table")) &&
    !(await exists('#overview-rate-path [data-meeting]')));

  // 8. Phone width: no sideways scroll; the decorative strip gives way to the numbers.
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  for (const [path, id] of [[overviewHref, "overview-rate-path"], [researchHref, "research-rate-path"]]) {
    await open(path);
    await readPanel(id);
    const layout = await evaluate(`({ scroll: document.documentElement.scrollWidth,
      width: document.documentElement.clientWidth,
      strip: getComputedStyle(document.querySelector("#${id} td.rate-path-strip-cell")).display })`);
    check(`at phone width ${path.endsWith("/research") ? "the research page" : "the overview"} has no sideways scroll`,
      layout.scroll <= layout.width && layout.strip === "none", JSON.stringify(layout));
  }
  await desktop();

  const outside = requests.filter((request) => !request.url.startsWith(base) && !request.url.startsWith("data:") &&
    request.url !== "about:blank");
  check("the pages requested nothing outside the local server", outside.length === 0,
    outside.map((request) => request.url).join(", "));
  const real = errors.filter((entry) => !/favicon\.ico/.test(entry));
  check("no page error", real.length === 0, real.join(" | "));

  if (process.env.SECOND_ORDER_SCREENSHOTS) {  // Bounded per-section clips; never a whole tall page.
    const shoot = async (name, selector) => {
      await evaluate(`document.querySelector(${JSON.stringify(selector)})?.scrollIntoView({ block: "start" })`);
      await sleep(300);
      const box = await evaluate(`(() => { const r = document.querySelector(${JSON.stringify(selector)})
        ?.getBoundingClientRect(); return r && { x: r.left, y: r.top + scrollY, width: r.width,
        height: Math.min(r.height, 2400) }; })()`);
      if (!box) return;
      const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true,
        clip: { ...box, scale: 1 } });
      writeFileSync(join(process.env.SECOND_ORDER_SCREENSHOTS, `${name}.png`), Buffer.from(shot.data, "base64"));
    };
    await open(researchHref);
    await readPanel("research-rate-path");
    await shoot("rate-path-research", "#research-rate-path");
    await evaluate(`document.querySelector("#research-rate-path .rate-path-provenance").open = true`);
    await shoot("rate-path-provenance", "#research-rate-path .rate-path-provenance");
    await open(overviewHref);
    await readPanel("overview-rate-path");
    await shoot("rate-path-overview", "#overview-rate-path");
    await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
    await open(overviewHref);
    await readPanel("overview-rate-path");
    await shoot("rate-path-phone", "#overview-rate-path");
  }
  ws.close();
} catch (error) {
  check("the rate-path browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(500);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
