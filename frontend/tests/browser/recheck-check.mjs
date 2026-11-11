// Browser acceptance check for honest send outcomes and the explicit local re-check, in one headless Chrome against
// tests/review_browser_server.py with --simulated-feeds triage, --simulated-triage and --long-summaries (a fake whose
// grounded summaries run past the 25-word target). The journey: a server still checking replies under
// triage-validation-1 (25 words as a hard limit) sends one simulated request, which is recorded as not accepted, and
// the banner says so -> the server restarts under the current policy -> Saved requests offers a local re-check, which
// accepts the saved response without sending anything and without touching its original records -> previewing the
// same entries reuses the result, labelled as accepted on a local re-check and not regenerated. Fake calls are counted
// from the fake's own records. Nothing outside the local server is requested.
//
//   cd frontend; npm run build; npm run test:browser:recheck
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

const JOBS = "Simulated: The Employment Situation — September 2026";
const CPI = "Simulated: Consumer Price Index — August 2026";

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const root = mkdtempSync(join(tmpdir(), "second-order-recheck-check-"));
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
const hashes = (...parts) => Object.fromEntries(folder(...parts).filter((name) => name.endsWith(".json")).map((name) =>
  [name, createHash("sha256").update(readFileSync(join(served, ...parts, name))).digest("hex")]));

async function startServer(extra) {
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    "--simulated-feeds", "triage", "--simulated-triage", "--long-summaries", ...extra],
    { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  for (let i = 0; i < 150; i++) {
    try { if ((await fetch(`${base}/api/drafts`)).ok) return { base, server }; } catch { await sleep(200); }
  }
  throw new Error("The review server did not start.");
}

try {
  mkdirSync(served);
  let { base, server } = await startServer(["--validation-policy", "triage-validation-1"]);
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
  const open = async () => {
    await send("Page.navigate", { url: base + "/" });
    await waitFor("document.readyState === 'complete' && !!document.querySelector('.triage-bar')");
  };
  const select = (title) => evaluate(`(() => { const li = [...document.querySelectorAll(".inbox-item")].find((e) =>
    e.querySelector("h3").textContent === ${JSON.stringify(title)}); const input = li?.querySelector(".inbox-select input");
    if (!input || input.disabled || input.checked) return false; input.click(); return true; })()`);
  const preview = async () => {
    await click(".triage-preview");
    return waitFor(`!!document.querySelector(".triage-plan") && !document.querySelector(".triage-preview").textContent.includes("Resolving")`);
  };
  const message = () => text(".triage-message");
  const rowJs = (title) => `[...document.querySelectorAll(".triage-results .triage-row")].find((li) =>
    li.querySelector(".triage-row-title").textContent === ${JSON.stringify(title)})`;

  // 1. A server that still treats 25 words as a hard limit: the simulated reply is recorded as not accepted.
  await open();
  await click(".inbox-refresh");
  await waitFor(`document.querySelectorAll(".inbox-item").length === 12`, 15000);
  check("two entries are selected and previewed as one planned request",
    await select(JOBS) && await select(CPI) && await preview() &&
    (await text(".triage-plan-requests")).startsWith("Planned requests: 1, with 2 entries"));
  const triageId = await evaluate(`document.querySelector(".triage-panel").dataset.triage`);
  await click(".triage-confirm input");
  await click(".triage-approve");
  await waitFor(`(document.querySelector(".triage-message")?.textContent ?? "").includes("recorded")`, 15000);
  const banner = await message();
  check("the banner reports the recorded outcome: not accepted, with the reason, never as passing validation",
    banner.includes("recorded but not accepted") && banner.includes("longer than 25 words") &&
    !/passed validation|accepted under/.test(banner) &&
    await evaluate(`document.querySelector(".triage-message").classList.contains("is-error")`), banner);
  check("its entries stay unresolved and the fake received exactly one request",
    await waitFor(`[...document.querySelectorAll(".triage-results .triage-row")].every((r) => r.dataset.status === "unresolved")`) &&
    calls() === 1);
  const attempt = ["headline-triage", "requests", triageId, "simulated"];
  const original = hashes(...attempt);
  const manifest = JSON.parse(readFileSync(join(served, ...attempt, "manifest.json"), "utf8"));
  check("the attempt names the policy it was checked under",
    manifest.outcome === "not_accepted" && manifest.validation_policy === "triage-validation-1" &&
    Object.keys(original).sort().join() === "attempt.json,manifest.json,reservation.json,response.json");

  // 2. The server restarts under the current policy; Saved requests offers an explicit local re-check.
  server.kill();
  await sleep(500);
  ({ base, server } = await startServer(["--keep-records"]));
  await open();
  await evaluate(`document.querySelector(".triage-saved").open = true`);
  check("Saved requests offers a local re-check of the rejected simulated response",
    await waitFor(`!!document.querySelector('.triage-recheck[data-mode="simulated"]')`) &&
    (await text(".triage-recheck")).includes("Re-check the simulated response locally"));
  await click('.triage-recheck[data-mode="simulated"]');
  await waitFor(`(document.querySelector(".triage-message")?.textContent ?? "").includes("local re-check")`, 15000);
  const rechecked = await message();
  check("the re-check accepts it under triage-validation-3 and says nothing was sent or regenerated",
    rechecked.includes("Accepted on a local re-check under triage-validation-3") &&
    rechecked.includes("Nothing was sent or regenerated") && rechecked.includes("original record"), rechecked);
  check("the re-check sent nothing and left the original attempt records byte for byte as they were",
    calls() === 1 && JSON.stringify(hashes(...attempt)) === JSON.stringify(original) &&
    folder(...attempt, "revalidations").join() === "triage-validation-3.json");
  check("the saved request now shows the re-check beside the unchanged original outcome, and no second re-check",
    await waitFor(`(document.querySelector(".triage-saved-recheck")?.textContent ?? "").includes("accepted, with no request sent; the original record still says not accepted")`) &&
    !(await evaluate(`!!document.querySelector(".triage-recheck")`)));

  // 3. Previewing the same entries reuses the result, labelled as accepted on a local re-check.
  await select(JOBS);
  await select(CPI);
  await preview();
  check("nothing is requested: both entries reuse the re-checked result",
    (await message()).includes("Nothing to request") &&
    await evaluate(`[...document.querySelectorAll(".triage-results .triage-row")].every((r) => r.dataset.status === "reuse")`) &&
    calls() === 1);
  const row = await evaluate(`(() => { const li = ${rowJs(JOBS)}; return { summary: li.querySelector(".triage-summary").textContent,
    provenance: li.querySelector(".triage-row-provenance").textContent }; })()`);
  check("the result keeps its long, grounded summary and is labelled as re-checked, not regenerated",
    row.summary.split(/\s+/).length > 25 && row.provenance.includes("accepted on a local re-check under triage-validation-3") &&
    row.provenance.includes("not accepted on receipt under triage-validation-1") &&
    row.provenance.includes("not regenerated or re-sent"), JSON.stringify(row));

  // 4. Only explicit actions wrote, and nothing outside the local server was requested.
  const writes = requests.filter((r) => r.method !== "GET").map((r) => new URL(r.url).pathname
    .replace(/\/api\/triage\/triage-[0-9a-f]{24}\//, "/api/triage/*/"));
  const allowed = new Set(["/api/inbox/refresh", "/api/triage", "/api/triage/*/simulated", "/api/triage/*/simulated/revalidate"]);
  check("every write was an explicit action: one refresh, previews, one approval and one re-check",
    writes.every((path) => allowed.has(path)) && writes.filter((p) => p.endsWith("/simulated")).length === 1 &&
    writes.filter((p) => p.endsWith("/revalidate")).length === 1, JSON.stringify(writes));
  const outside = requests.filter(({ url }) => !url.startsWith("http://127.0.0.1:") && !url.startsWith("data:") && url !== "about:blank");
  check("the page requested nothing outside the local server", outside.length === 0, outside.map((r) => r.url).join(", "));
  const pageErrors = consoleErrors.filter((error) => !/\/favicon\.ico$/.test(error.url));
  check("the page logged no errors (the favicon probe aside)", pageErrors.length === 0, JSON.stringify(pageErrors));
  ws.close();
} catch (error) {
  check("the re-check browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(500);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
