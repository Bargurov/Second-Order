// Browser check of the electricity findings (EIA Table 7.6), against tests/review_browser_server.py serving a new, empty
// folder with --findings (SYNTHETIC Table 7.6 files shaped like the retained ones, with acquisition records;
// electricity_fakes, whose months have known classes). It checks:
// - the electricity part is a separate, labelled evidence type beside the Treasury and G.17 parts;
// - loading only reads; nothing is computed until the explicit action, a double click sends one, and its reply says no
//   API call was made;
// - coverage is stated (months compared, the file's range, the last month not called current) and each source keeps
//   its own provenance, the CSV with no edition;
// - the monthly table shows each sector's change with its class, the inclusive bounds (exactly +1% and -1%) and the
//   band just inside them; context columns stay context;
// - one card per diverging month and one for January-June, each with observations, what it adds, an interpretation
//   apart, contributions with the rounding residual, and the six disclosures;
// - reconciliation is shown; repeating writes nothing; a restart reads the same;
// - narrow screens, page errors, and no request outside the local server.
//
//   cd frontend; npm run build; npm run test:browser:findings-electricity
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
const root = mkdtempSync(join(tmpdir(), "second-order-electricity-check-"));
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
    try { if ((await fetch(`http://127.0.0.1:${port}/api/insights/electricity`)).ok) return server; } catch { /* starting */ }
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
  const posts = () => requests.filter((row) => row.method === "POST" && row.url.endsWith("/api/insights/electricity/checks"))
    .length;
  const records = join(served, "insights", "electricity");

  // 1. A separate evidence type; nothing computed before the explicit action.
  let before = tree(served);
  await open("/findings");
  await waitFor(`!!document.querySelector(".electricity-check")`);
  const part = await text(".findings-electricity .findings-part-head");
  check("the electricity part is a separate, labelled evidence type beside Treasury and G.17",
    part.includes("Evidence type 3") && part.includes("Table 7.6") && part.includes("Separate from the Treasury and G.17") &&
    (await text(".findings-treasury .findings-part-head")).includes("Treasury yields") &&
    (await text(".findings-g17 .findings-part-head")).includes("G.17"), part.slice(0, 200));
  check("before the action nothing is computed and loading wrote nothing",
    (await text(".electricity-check")).includes("Nothing has been computed yet") && same(tree(served), before) &&
    !existsSync(records));

  // 2. One explicit action, sent once for a double click.
  await evaluate(`(() => { const button = document.querySelector(".electricity-run"); button.click(); button.click(); })()`);
  await waitFor(`(document.querySelector(".electricity-outcome")?.textContent ?? "").includes("Computed")`);
  const outcome = await text(".electricity-outcome");
  check("a double click sends one request, which reports a local computation with no API call",
    posts() === 1 && outcome.includes("Computed 12 months locally (no API call): 8 monthly findings and a January–June "
      + "finding"), `${posts()} ${outcome}`);
  await waitFor(`document.querySelectorAll(".electricity-card").length > 0`);

  // 3. Coverage and provenance.
  const coverage = await text(".electricity-coverage");
  check("coverage states the months compared, the file's range and that the last month is not called current",
    coverage.includes("July 2025 to June 2026") && coverage.includes("July 2024 to June 2025") &&
    coverage.includes("January–June 2026 against January–June 2025") && coverage.includes("2023-01 to 2026-06") &&
    coverage.includes("not described here as current") &&
    coverage.includes("Geography: The 50 states and the District of Columbia"), coverage);
  const csvRow = await text('.electricity-sources tr[data-kind="csv"]');
  const pdfRow = await text('.electricity-sources tr[data-kind="pdf"]');
  const pageRow = await text('.electricity-sources tr[data-kind="landing"]');
  check("each source keeps its own provenance; the CSV is given no edition",
    csvRow.includes("None stated") && csvRow.includes("none is assigned") && csvRow.includes("eia-mer-table76-01") &&
    pdfRow.includes("Monthly Energy Review September 2026") && pdfRow.includes("not the CSV") &&
    pageRow.includes("Release date September 29, 2026") && pageRow.includes("eia-mer-inspection-01"),
    `${csvRow} | ${pdfRow} | ${pageRow}`);

  // 4. The monthly table: classes, inclusive bounds, context.
  check("the table has twelve months, eight of them marked as diverging",
    (await evaluate(`document.querySelectorAll(".electricity-table tbody tr").length`)) === 12 &&
    (await evaluate(`document.querySelectorAll(".electricity-table tbody tr.is-finding").length`)) === 8);
  const up = await cell("2025-08", "ESRCPUS"), down = await cell("2025-08", "ESCCPUS");
  const inside = await cell("2025-09", "ESRCPUS");
  check("exactly +1% is up and exactly −1% is down; 0.999% is little changed",
    up.includes("+1.00%") && up.includes("Up (≥ +1%)") && down.includes("−1.00%") && down.includes("Down (≤ −1%)") &&
    inside.includes("+0.99%") && inside.includes("Little changed"), `${up} | ${down} | ${inside}`);
  const total = await cell("2025-08", "ESTCPUS");
  check("total retail sales are context, without a class", total.includes("%") && !total.includes("Up") &&
    !total.includes("Little changed") && (await text(".electricity-table thead")).includes("context"), total);

  // 5. Cards.
  const august = await cardText("month|2025-08");
  check("a monthly card states its observations, what it adds and an interpretation apart",
    august.includes("August 2025: residential sales up, commercial sales down from August 2024") &&
    august.includes("101,000.000") && august.includes("100,000.000") && august.includes("+1,000.000") &&
    august.includes("What this adds") && august.includes("Interpretation (not observed)") &&
    august.includes("Transportation (railways only)") && august.includes("context"), august.slice(0, 300));
  check("a card shows contributions with the rounding residual and every disclosure",
    august.includes("Contributions to the change in total retail sales") && august.includes("Rounding residual") &&
    august.includes("not total electricity consumption") && august.includes("Not weather-adjusted and not "
      + "calendar-adjusted") && august.includes("No price normalization") && august.includes("not marked") &&
    august.includes("not a revision history") && august.includes("No cause is established") &&
    august.includes("both have 31 days"), august.slice(0, 200));
  const cards = await evaluate(`[...document.querySelectorAll(".electricity-card")].map((card) => card.dataset.card)`);
  check("one card per diverging month, latest first, then January–June",
    cards.length === 9 && cards[0] === "month|2026-06" && cards[7] === "month|2025-07" &&
    cards[8] === "period|2026-01..2026-06", JSON.stringify(cards));
  const period = await cardText("period|2026-01..2026-06");
  check("the January–June card compares six-month sums",
    period.includes("January–June 2026: residential and commercial sales up, industrial sales down from January–June "
      + "2025") && (await text(".electricity-findings")).includes("summed before the change is computed"),
    period.slice(0, 200));
  check("reconciliation is shown with its tolerance",
    (await text(".electricity-reconciliation")).includes("24 of 24 months read reconcile within rounding") &&
    (await text(".electricity-reconciliation")).includes("0.0025"));
  check("the method keeps the 1% band a product filter and the footnotes as printed",
    (await text(".electricity-method")).includes("not statistical significance") &&
    (await evaluate(`document.querySelectorAll(".electricity-footnotes dt").length`)) === 10);

  // 6. A repeat writes nothing; a restart reads the same.
  before = tree(served);
  await click(".electricity-run");
  await waitFor(`(document.querySelector(".electricity-outcome")?.textContent ?? "").includes("reused")`);
  check("repeating the action writes nothing", same(tree(served), before) &&
    (await text(".electricity-outcome")).includes("nothing was written"));
  server.kill();
  await sleep(500);
  server = await startServer(port, ["--keep-records", "--findings"]);
  before = tree(served);
  await open("/findings");
  await waitFor(`document.querySelectorAll(".electricity-card").length > 0`);
  check("after a restart the same result is read and nothing is written",
    (await cardText("month|2025-08")).includes("+1,000.000") && same(tree(served), before));

  // 7. Narrow screens.
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  await open("/findings");
  await waitFor(`document.querySelectorAll(".electricity-card").length > 0`);
  await sleep(600);
  const layout = await evaluate(`({ scroll: document.documentElement.scrollWidth, width: document.documentElement.clientWidth })`);
  check("narrow screen /findings: no sideways scrolling", layout.scroll <= layout.width, JSON.stringify(layout));

  const outside = requests.filter((row) => !row.url.startsWith(base) && !row.url.startsWith("data:") && row.url !== "about:blank");
  check("nothing outside the local server was requested", outside.length === 0, outside.map((row) => row.url).join(", "));
  const real = errors.filter((entry) => !/favicon\.ico/.test(entry));
  check("no page error", real.length === 0, real.join(" | "));
  ws.close();
} catch (error) {
  check("the electricity findings browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(300);
  try { rmSync(root, { recursive: true, force: true }); } catch { /* Windows may hold a file briefly. */ }
}
console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
process.exit(results.every(Boolean) ? 0 : 1);
