// Browser check of the cross-source comparisons, against tests/review_browser_server.py serving a new, empty folder with
// --findings (SYNTHETIC G.17 pages and SYNTHETIC EIA Table 7.6 files; the EIA file starts in January 2023, so Q4 2023
// against Q4 2022 is not covered). It checks:
// - a separate, labelled part after the G.17 and electricity parts; loading only reads; one explicit action, sent once;
// - coverage: the EIA file's range, retrieval and unassigned edition, the G.17 releases, and no month substituted;
// - not covered, no direction, same sign and opposite signs as sign-only descriptions; June from the July release,
//   marked preliminary; later G.17 periods without EIA data shown as not covered;
// - the measures, differences and labelled possibilities; the customer breakdown as EIA's own decomposition;
// - links to the existing parts, each value's source, the limits; repeat, restart, narrow screens, page errors and no
//   request outside the local server.
//
//   cd frontend; npm run build; npm run test:browser:findings-cross-source
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

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => { const { port } = server.address(); server.close(() => done(port)); });
});
const root = mkdtempSync(join(tmpdir(), "second-order-cross-source-check-"));
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

async function startServer(port, extra) {
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    ...extra], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  for (let i = 0; i < 300; i++) {
    try { if ((await fetch(`http://127.0.0.1:${port}/api/insights/cross-source`)).ok) return server; } catch { /* starting */ }
    await sleep(200);
  }
  throw new Error("The review server did not start.");
}

try {
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  let server = await startServer(port, ["--findings"]);

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
  const click = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.click()`);
  const cardText = (id) => evaluate(`document.querySelector('.electricity-card[data-card="${id}"]')?.textContent ?? ""`);
  const cell = (month, code) => text(`.electricity-table tr[data-month="${month}"] td[data-code="${code}"]`);
  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("Log.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete'");
  };
  const posts = () => requests.filter((row) => row.method === "POST" && row.url.endsWith("/api/insights/cross-source/checks"))
    .length;
  const records = join(served, "insights", "cross-source");
  const rowText = (comparison, period) => evaluate(`document.querySelector('[data-comparison="${comparison}"] tr[data-period="${period}"]')?.textContent ?? ""`);

  // 1. A separate part; nothing computed before the explicit action.
  let before = tree(served);
  await open("/findings");
  await waitFor(`!!document.querySelector(".cross-action")`);
  const part = await text(".findings-cross .findings-part-head");
  check("the comparisons are a separate, labelled part after the G.17 and electricity parts",
    part.includes("Cross-source comparisons") && part.includes("side by side") && part.includes("not transmission findings") &&
    (await evaluate(`[...document.querySelectorAll(".findings-part")].map((el) => el.className).join("|")`))
      .endsWith("findings-part findings-electricity|findings-part findings-cross"), part.slice(0, 200));
  check("before the action nothing is computed and loading wrote nothing",
    (await text(".cross-action")).includes("Nothing has been computed yet") && same(tree(served), before) &&
    !existsSync(records));

  // 2. One explicit action, sent once for a double click.
  await evaluate(`(() => { const button = document.querySelector(".cross-run"); button.click(); button.click(); })()`);
  await waitFor(`(document.querySelector(".cross-outcome")?.textContent ?? "").includes("Computed")`);
  check("a double click sends one request, which reports a local computation with no API call",
    posts() === 1 && (await text(".cross-outcome")).includes("Computed 6 periods locally (no API call)"),
    `${posts()} ${await text(".cross-outcome")}`);
  await waitFor(`document.querySelectorAll(".cross-card").length === 2`);

  // 3. Coverage and the industrial comparison.
  const coverage = await text(".cross-coverage");
  check("coverage names the EIA file's range, retrieval, unassigned edition and the G.17 releases",
    coverage.includes("2023-01 to 2026-06") && coverage.includes("none is assigned") &&
    coverage.includes("July 17, 2026, August 18, 2026, September 18, 2026") &&
    coverage.includes("no other month is used in its place"), coverage);
  const industrial = "industrial_vs_manufacturing";
  const q23 = await rowText(industrial, "2023-Q4"), q24 = await rowText(industrial, "2024-Q4");
  const q25 = await rowText(industrial, "2025-Q4"), june = await rowText(industrial, "2026-06");
  const july = await rowText(industrial, "2026-07");
  check("a fourth quarter the EIA file does not reach is not covered, never filled",
    q23.includes("Q4 2023 vs Q4 2022") && q23.includes("Not covered") && q23.includes("outside the retained file"), q23);
  check("an exact zero change has no direction; signs are sign-only with no threshold",
    q24.includes("No direction") && q24.includes("0.00%") && q25.includes("Same sign") && q25.includes("+0.03%") &&
    q25.includes("+1.0%"), `${q24} | ${q25}`);
  check("June compares June with June, from the release whose 12-month column is June, marked preliminary",
    june.includes("June 2026 vs June 2025") && june.includes("−1.00%") && june.includes("+1.0%") &&
    june.includes("July 17, 2026 release · preliminary") && june.includes("Opposite signs"), june);
  check("a later G.17 period without EIA data is shown as not covered", july.includes("Not covered") &&
    july.includes("August 18, 2026 release"), july);
  const card1 = await text(`[data-comparison="${industrial}"]`);
  check("the industrial card keeps its measures, differences and possibilities apart",
    card1.includes("Not the same measurement") && card1.includes("class of service, not NAICS manufacturing") &&
    card1.includes("cannot show industrial self-generation") &&
    card1.includes("Possibilities (not established by these observations)") &&
    card1.includes("not the ±1% categories of Electricity by sector"), card1.slice(0, 200));

  // 4. The utility comparison.
  const utilityRow = await rowText("utility_output_and_customers", "2025-Q4");
  check("the customer breakdown decomposes the EIA total, beside G.17 utility output",
    utilityRow.includes("+1.0%") && utilityRow.includes("+0.09%") && utilityRow.includes("+1,500.000") &&
    utilityRow.includes("−800.000") && utilityRow.includes("+80.000"), utilityRow);
  const card2 = await text(`[data-comparison="utility_output_and_customers"]`);
  check("the utility card says the breakdown is EIA's own and not a decomposition of G.17 output",
    card2.includes("decomposes EIA total retail sales only") && card2.includes("not decomposed by them") &&
    !card2.includes("Possibilities"), card2.slice(0, 200));
  check("links lead to the existing G.17 and electricity parts",
    (await evaluate(`[...document.querySelectorAll(".cross-card a[href^='#']")].map((a) => a.getAttribute("href"))
      .every((href) => !!document.querySelector(href))`)) &&
    (await evaluate(`document.querySelectorAll(".cross-card a[href='#electricity-title']").length`)) === 2);
  await evaluate(`document.querySelectorAll(".cross-provenance").forEach((d) => d.open = true)`);
  const sources = await text(".cross-provenance");
  check("each value's source is listed: row, column, release and hash, and the EIA months",
    sources.includes("INDUSTRY GROUP / Manufacturing / Manufacturing (NAICS) (31-33) · Fourth quarter to fourth quarter")
    && sources.includes("Table 1, September 18, 2026") && sources.includes("ESICPUS: 2025-10, 2025-11, 2025-12"),
    sources.slice(0, 300));
  check("the limits say agreement is not corroboration and no cause is established",
    (await text(".cross-limits")).includes("agreement between them is not corroboration") &&
    (await text(".cross-limits")).includes("no cause is established"));

  // 5. A repeat writes nothing; a restart reads the same.
  before = tree(served);
  const reads = () => requests.filter((row) => row.method === "GET" && row.url.endsWith("/api/insights/cross-source")).length;
  const readsBefore = reads();
  await click(".cross-run");
  await waitFor(`(document.querySelector(".cross-outcome")?.textContent ?? "").includes("reused")`);
  check("repeating the action writes nothing", same(tree(served), before));
  // The page reads the view again after the action; let that read finish before the server stops.
  for (let i = 0; i < 100 && reads() === readsBefore; i++) await sleep(50);
  await sleep(500);
  server.kill();
  await sleep(500);
  server = await startServer(port, ["--keep-records", "--findings"]);
  before = tree(served);
  await open("/findings");
  await waitFor(`document.querySelectorAll(".cross-card").length === 2`);
  check("after a restart the same result is read and nothing is written",
    (await rowText(industrial, "2026-06")).includes("Opposite signs") && same(tree(served), before));

  // 6. Narrow screens.
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  await open("/findings");
  await waitFor(`document.querySelectorAll(".cross-card").length === 2`);
  await sleep(600);
  const layout = await evaluate(`({ scroll: document.documentElement.scrollWidth, width: document.documentElement.clientWidth })`);
  check("narrow screen /findings: no sideways scrolling", layout.scroll <= layout.width, JSON.stringify(layout));

  const outside = requests.filter((row) => !row.url.startsWith(base) && !row.url.startsWith("data:") && row.url !== "about:blank");
  check("nothing outside the local server was requested", outside.length === 0, outside.map((row) => row.url).join(", "));
  const real = errors.filter((entry) => !/favicon\.ico/.test(entry));
  check("no page error", real.length === 0, real.join(" | "));
  ws.close();
} catch (error) {
  check("the cross-source browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(300);
  try { rmSync(root, { recursive: true, force: true }); } catch { /* Windows may hold a file briefly. */ }
}
console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
process.exit(results.every(Boolean) ? 0 : 1);
