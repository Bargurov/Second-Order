// Browser check of the industry findings from retained G.17 releases, against tests/review_browser_server.py serving
// a new, empty folder with --findings (three SYNTHETIC G.17 releases shaped like the Board's pages, with acquisition
// records; g17_fakes.SCENARIO). It checks:
// - the Treasury and G.17 findings are separate, labelled parts of the Findings page;
// - loading only reads; nothing is compared until the explicit check, and a double click sends one;
// - a divergence card shows both published rates with row path, NAICS code, column, release and Table 1 source, an
//   interpretation apart from the observations, and every estimate of that month;
// - a printed-zero parent gets no directional comparison; a revision card shows the month's estimates with markers and
//   the change in percentage points; printed-zero transitions are listed apart from reversals;
// - manufacturing breadth: the latest retained release's counts of the 19 NAICS subsectors with a legend and a counts
//   table, the universe and its exclusions, an aggregate-against-breadth card and a breadth revision card;
// - repeating the check writes nothing; the full tables load; a restart reads the same;
// - narrow screens, page errors, and no request outside the local server.
//
//   cd frontend; npm run build; npm run test:browser:findings-g17
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
const root = mkdtempSync(join(tmpdir(), "second-order-g17-check-"));
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
    try { if ((await fetch(`http://127.0.0.1:${port}/api/insights/g17`)).ok) return server; } catch { /* starting */ }
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
  const cardText = (part) => evaluate(`[...document.querySelectorAll(".g17-card")]
    .find((card) => card.dataset.card.includes(${JSON.stringify(part)}))?.textContent ?? ""`);
  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("Log.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete'");
  };
  const posts = () => requests.filter((row) => row.method === "POST" && row.url.endsWith("/api/insights/g17/checks"))
    .length;
  const records = join(served, "insights", "g17");

  // 1. Two separate evidence types; nothing compared before the explicit check.
  let before = tree(served);
  await open("/findings");
  await waitFor(`!!document.querySelector(".g17-check")`);
  const part = await text(".findings-g17 .findings-part-head");
  check("Treasury and G.17 findings are separate, labelled parts of the Findings page",
    (await text(".findings-treasury .findings-part-head")).includes("Treasury yields") &&
    part.includes("Evidence type 2") && part.includes("G.17") && part.includes("Separate from the Treasury findings"));
  check("before a check nothing is compared and loading wrote nothing",
    (await text(".g17-check")).includes("No G.17 check has been run yet. 3 retained releases are available") &&
    same(tree(served), before) && !existsSync(records));

  // 2. One explicit check, sent once for a double click.
  await evaluate(`(() => { const button = document.querySelector(".g17-run"); button.click(); button.click(); })()`);
  await waitFor(`(document.querySelector(".g17-outcome")?.textContent ?? "").includes("Checked")`);
  check("a double click sends one check, which reports what it created",
    posts() === 1 && (await text(".g17-outcome")).includes("3 new release results and 2 new revision comparisons"),
    `${posts()} ${await text(".g17-outcome")}`);
  await waitFor(`document.querySelectorAll(".g17-card").length > 0`);
  check("the releases list their dates as published, months and source hashes",
    (await evaluate(`document.querySelectorAll(".g17-releases tbody tr").length`)) === 3 &&
    (await text(".g17-releases")).includes("August 18, 2026") && (await text(".g17-releases")).includes("no time zone"));

  // 3. A divergence card, the printed-zero parent, a revision card and printed-zero transitions.
  const vehicles = await cardText("Motor vehicles and parts");
  check("a subsector against its parent shows both published rates with path, code, column, release and source",
    vehicles.includes("Motor vehicles and parts (NAICS 3361-3) fell while durable manufacturing rose") &&
    vehicles.includes("−0.8%") && vehicles.includes("+0.6%") && vehicles.includes("Monthly rate / 2026 / July[r]") &&
    vehicles.includes("INDUSTRY GROUP / Manufacturing / Manufacturing (NAICS) / Durable manufacturing") &&
    vehicles.includes("September 18, 2026 release") && vehicles.includes("Table 1") && vehicles.includes("−1.4 pp"),
    vehicles.slice(0, 300));
  check("the card keeps its interpretation apart and lists every estimate of the month",
    vehicles.includes("Interpretation (not observed)") && vehicles.includes("August 18, 2026 (preliminary): −2.1%") &&
    vehicles.includes("What this adds"));
  const totals = await text(".g17-divergence .g17-totals");
  check("the divergence cards state their totals and order", totals.startsWith("Showing") &&
    (await text(".g17-divergence")).includes("ordered by reference month"), totals);
  check("a printed-zero parent gets no directional comparison",
    (await text(".g17-quiet")).includes("Nondurable manufacturing printed 0.0% for August 2026"));
  const machinery = await cardText("Machinery");
  check("a revision card shows the month's estimates with markers and the change in percentage points",
    machinery.includes("Machinery (NAICS 333), June 2026: reported down, then up") && machinery.includes("−0.7%") &&
    machinery.includes("preliminary") && machinery.includes("+0.4%") && machinery.includes("+0.8 pp"),
    machinery.slice(0, 300));
  const zero = await text(".g17-zero");
  check("changes to or from a printed 0.0 are listed apart from reversals",
    zero.includes("Mining, May 2026") && zero.includes("To printed 0.0") && !(await cardText("Mining")));

  // 3b. Manufacturing breadth.
  const breadth = await text(".g17-breadth");
  check("the breadth summary names the latest retained release, the universe and what it excludes",
    breadth.includes("Manufacturing breadth: 19 NAICS subsectors") &&
    breadth.includes("As published in the September 18, 2026 release (the latest retained release)") &&
    breadth.includes("Mining, utilities and other (non-NAICS) manufacturing are outside this universe") &&
    breadth.includes("not shares of aggregate growth"), breadth.slice(0, 300));
  const april = await evaluate(`[...document.querySelector(".g17-breadth .g17-breadth-table").querySelectorAll("tbody tr")]
    .map((row) => [row.dataset.month, ...[...row.querySelectorAll("td")].map((cell) => cell.textContent)])`);
  const aprilRow = april.find((row) => row[0] === "2026-04") ?? [];
  check("the counts table has six months, a legend, and April's counts as published",
    april.length === 6 && (await evaluate(`document.querySelectorAll(".g17-breadth > .g17-legend li").length`)) === 4 &&
    aprilRow[2].startsWith("9") && aprilRow[3].startsWith("10") && aprilRow[4].startsWith("0") &&
    aprilRow[5] === "0" && aprilRow[7].includes("most subsectors down"), JSON.stringify(aprilRow));
  const against = await evaluate(`document.querySelector('.g17-breadth-card[data-type="aggregate_vs_breadth"]')?.textContent ?? ""`);
  check("an aggregate-against-breadth card states the rule's condition, its source and its interpretation apart",
    against.includes("April 2026: Manufacturing (NAICS) rose 0.3% while 10 of 19 subsectors were printed down") &&
    against.includes("Interpretation (not observed)") && against.includes("Table 1"), against.slice(0, 200));
  const revised = await evaluate(`document.querySelector('.g17-breadth-card[data-type="breadth_revision"]')?.textContent ?? ""`);
  check("a breadth revision card compares the same month across releases and names the subsectors that switched",
    revised.includes("April 2026 breadth revised: most subsectors up in the August 18, 2026 release, most subsectors down "
      + "in the September 18, 2026 release") && revised.includes("Switched direction") &&
    revised.includes("Machinery (333)"), revised.slice(0, 200));

  // 4. A repeat writes nothing; the full tables; a restart.
  before = tree(served);
  await click(".g17-run");
  await waitFor(`(document.querySelector(".g17-outcome")?.textContent ?? "").includes("Nothing changed")`);
  check("repeating an unchanged check writes nothing", same(tree(served), before));
  await click(".g17-all");
  await waitFor(`location.pathname === "/findings/g17" && !!document.querySelector(".g17-chains")`);
  const chain = await evaluate(`[...document.querySelectorAll(".g17-chains tbody tr")]
    .find((row) => row.dataset.path.endsWith("/ Machinery"))?.textContent ?? ""`);
  check("the full tables show breadth for each release and the revised breadth of the same month",
    (await evaluate(`document.querySelectorAll(".g17-breadth-full .g17-breadth-release").length`)) === 3 &&
    (await evaluate(`document.querySelectorAll(".g17-breadth-full .g17-breadth-revisions").length`)) === 2 &&
    (await text(".g17-breadth-full")).includes("picture changed"));
  check("the full tables show every release's comparisons and each row's estimates",
    (await evaluate(`document.querySelectorAll(".g17-release").length`)) === 3 &&
    chain.includes("−0.7% [p] → +0.1% → +0.4%") && chain.includes("reversed, then revised") &&
    (await text(".g17-provenance")).includes("g17-industry-tables-01"), chain.slice(0, 200));
  server.kill();
  await sleep(500);
  server = await startServer(port, ["--keep-records", "--findings"]);
  before = tree(served);
  await open("/findings");
  await waitFor(`document.querySelectorAll(".g17-card").length > 0`);
  check("after a restart the same findings are read and nothing is written",
    (await cardText("Motor vehicles and parts")).includes("−0.8%") && same(tree(served), before));

  // 5. Narrow screens.
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  for (const path of ["/findings", "/findings/g17"]) {
    await open(path);
    await waitFor(`!!document.querySelector(".findings")`);
    await sleep(600);
    const layout = await evaluate(`({ scroll: document.documentElement.scrollWidth, width: document.documentElement.clientWidth })`);
    check(`narrow screen ${path}: no sideways scrolling`, layout.scroll <= layout.width, JSON.stringify(layout));
  }

  const outside = requests.filter((row) => !row.url.startsWith(base) && !row.url.startsWith("data:") && row.url !== "about:blank");
  check("nothing outside the local server was requested", outside.length === 0, outside.map((row) => row.url).join(", "));
  const real = errors.filter((entry) => !/favicon\.ico/.test(entry));
  check("no page error", real.length === 0, real.join(" | "));
  ws.close();
} catch (error) {
  check("the G.17 findings browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(300);
  try { rmSync(root, { recursive: true, force: true }); } catch { /* Windows may hold a file briefly. */ }
}
console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
process.exit(results.every(Boolean) ? 0 : 1);
