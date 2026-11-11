// Browser check of the Treasury findings pilot (Findings) against tests/review_browser_server.py serving a new, empty
// folder with --findings (a SYNTHETIC package of the pilot's seven series, two captures of one statement, and Inbox
// entries including an energy article and minutes whose timestamp contradicts its zone; no case library). It checks:
// - loading pages only reads; nothing is measured until the explicit check, and a double click sends one;
// - occasions are listed once per date; duplicate captures form one release; unsupported and undated entries are
//   listed with their reasons;
// - a finding shows its observations with series IDs, the comparison, what it adds, a labelled inference,
//   alternatives and strengthen/weaken items; an occasion where nothing met the rules says so and keeps its numbers;
// - repeating the check writes nothing; the event overview's band links to its occasion; a restart reads the same;
// - narrow screens, page errors, and no request outside the local server.
//
//   cd frontend; npm run build; npm run test:browser:findings
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
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
const root = mkdtempSync(join(tmpdir(), "second-order-findings-check-"));
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
    try { if ((await fetch(`http://127.0.0.1:${port}/api/insights`)).ok) return server; } catch { /* starting */ }
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
  const inflight = new Set();
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else if (message.method === "Network.requestWillBeSent") {
      requests.push({ method: message.params.request.method, url: message.params.request.url });
      inflight.add(message.params.requestId);
    } else if (message.method === "Network.loadingFinished" || message.method === "Network.loadingFailed") {
      inflight.delete(message.params.requestId);
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
  // Before a deliberate server stop: every request the page started has finished, and every font it needs is loaded,
  // so the stop interrupts nothing the page was still loading. A page that never settles fails this check.
  const settled = async () => {
    await evaluate("document.fonts.ready.then(() => true)");
    for (const start = Date.now(); inflight.size > 0 && Date.now() - start < 10000;) await sleep(50);
    await evaluate("document.fonts.ready.then(() => true)");
    return inflight.size === 0 && (await evaluate("document.fonts.status")) === "loaded";
  };
  const waitFor = async (expression, timeout = 20000) => {
    for (const start = Date.now(); Date.now() - start < timeout; await sleep(80)) {
      if (await evaluate(expression)) return true;
    }
    return false;
  };
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);
  const click = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.click()`);
  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("Log.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete'");
  };
  const posts = () => requests.filter((row) => row.method === "POST" && row.url.endsWith("/api/insights/checks")).length;

  // 1. Before any check: the page reads only and says nothing has been measured.
  let before = tree(served);
  await open("/findings");
  await waitFor(`!!document.querySelector(".findings-check")`);
  check("the Findings page loads from the top bar, labelled as a retrospective single-market pilot",
    (await text('.site-nav a[aria-current="page"]')) === "Findings" &&
    (await text(".findings-treasury .findings-part-head")).includes("retrospective single-market pilot") &&
    (await text(".findings-scope")).includes("not cross-sector discovery"));
  check("before a check nothing is measured and loading wrote nothing",
    (await text(".findings-check")).includes("No check has been run yet") && same(tree(served), before) &&
    !existsSync(join(served, "insights")));

  // 2. One explicit check, sent once for a double click.
  await evaluate(`(() => { const button = document.querySelector(".findings-run"); button.click(); button.click(); })()`);
  await waitFor(`(document.querySelector(".findings-outcome")?.textContent ?? "").includes("Checked")`);
  check("a double click sends one check, which reports what it did",
    posts() === 1 && (await text(".findings-outcome")).includes("Checked 3 occasions; 3 new results"),
    `${posts()} ${await text(".findings-outcome")}`);
  await waitFor(`document.querySelectorAll(".findings-list > li").length === 3`);
  const dates = await evaluate(`[...document.querySelectorAll(".findings-list > li")].map((li) => li.dataset.date)`);
  check("each dated occasion is listed once", same(dates, ["2026-06-17", "2026-07-29", "2026-09-16"]), JSON.stringify(dates));
  const september = await text('.findings-list > li[data-date="2026-09-16"]');
  check("the 16 September occasion reports its findings and one release from two captures",
    september.includes("3 findings") &&
    (await evaluate(`document.querySelectorAll('.findings-list > li[data-date="2026-09-16"] .findings-events > li').length`)) === 1,
    september);
  check("an occasion where nothing met the rules says so",
    (await text('.findings-list > li[data-date="2026-06-17"]')).includes("Checked · nothing met the rules"));
  const other = await text(".findings-other");
  check("entries outside the pilot and without a usable date are listed with their reasons",
    other.includes("Outside this pilot · 1") && other.includes("No usable date · 1"), other);
  check("the method section states the windows, ranks, rules and comparison sessions",
    (await text(".findings-method")).includes("ties count half") && (await text(".findings-method")).includes("R4") &&
    (await text(".findings-method")).includes("not a probability"));

  // 3. The finding's page.
  await open("/findings/2026-09-16");
  await waitFor(`!!document.querySelector(".finding-card")`);
  const card = await evaluate(`document.querySelector('.finding-card[data-check="R1:10:W1"]')?.textContent ?? ""`);
  check("the offsetting-components finding shows the numbers, series IDs, inference, alternatives and checks",
    card.includes("+30 bp") && card.includes("-30 bp") && card.includes("RIFLGFCY10_XII_N.B") &&
    card.includes("Inference (not observed)") && card.includes("Alternatives") && card.includes("Would weaken") &&
    card.includes("comparison sessions"), card.slice(0, 300));
  const releases = await text(".findings-occasion section");
  check("the release lists both captures with the basis of their date",
    (await evaluate(`document.querySelectorAll(".findings-releases > li > ul > li").length`)) === 2 &&
    releases.includes("supplied when the event was captured"), releases.slice(0, 300));
  // Nine measures over W1 and W5, plus the 2-year and 3-month yields over PRE: 20 rows, as served.
  const servedRows = async (day) => (await (await fetch(`${base}/api/insights/occasions/${day}`)).json()).result.measures.length;
  const rows = await evaluate(`document.querySelectorAll(".findings-measures tbody tr").length`);
  check("measured changes, policy context, provenance and limitations are shown once",
    rows === 20 && rows === await servedRows("2026-09-16") &&
    (await text(".findings-occasion")).includes("states no change in the discount") &&
    (await text(".findings-occasion")).includes("Result ID") &&
    (await evaluate(`document.querySelectorAll(".findings-limits-band li").length`)) === 5, `${rows} rows`);
  await open("/findings/2026-06-17");
  await waitFor(`!!document.querySelector(".findings-summary")`);
  check("the quiet occasion states that nothing met the rules and still shows its measured changes",
    (await text(".findings-summary")).startsWith("Checked: none of the 12") &&
    !(await evaluate(`!!document.querySelector(".finding-card")`)) &&
    (await evaluate(`document.querySelectorAll(".findings-measures tbody tr").length`)) === 20);

  // 4. A repeat writes nothing; the overview band; a restart.
  before = tree(served);
  await open("/findings");
  await waitFor(`!!document.querySelector(".findings-run")`);
  await click(".findings-run");
  await waitFor(`(document.querySelector(".findings-outcome")?.textContent ?? "").includes("Nothing changed")`);
  check("repeating an unchanged check writes nothing", same(tree(served), before));
  const captureId = readdirSync(join(served, "intake")).find((name) => !name.startsWith("."));
  await open(`/events/capture/${captureId}`);
  await waitFor(`(document.querySelector(".findings-band")?.textContent ?? "").includes("2026-09-16")`);
  check("the event overview's band links to its occasion",
    (await text(".findings-band")).includes("3 findings") &&
    (await evaluate(`document.querySelector(".findings-band a")?.getAttribute("href")`)) === "/findings/2026-09-16");
  check("the overview finished loading before the deliberate server stop", await settled());
  server.kill();
  await sleep(500);
  server = await startServer(port, ["--keep-records", "--findings"]);
  before = tree(served);
  await open("/findings");
  await waitFor(`document.querySelectorAll(".findings-list > li").length === 3`);
  check("after a restart the same occasions are read and nothing is written",
    (await text('.findings-list > li[data-date="2026-09-16"]')).includes("3 findings") && same(tree(served), before));

  // 5. Narrow screens.
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  for (const path of ["/findings", "/findings/2026-09-16", `/events/capture/${captureId}`]) {
    await open(path);
    await waitFor(`!!document.querySelector(".findings, .overview")`);
    await sleep(600);
    const layout = await evaluate(`({ scroll: document.documentElement.scrollWidth, width: document.documentElement.clientWidth })`);
    check(`narrow screen ${path.replace(captureId, ":id")}: no sideways scrolling`, layout.scroll <= layout.width,
      JSON.stringify(layout));
  }

  const outside = requests.filter((row) => !row.url.startsWith(base) && !row.url.startsWith("data:") && row.url !== "about:blank");
  check("nothing outside the local server was requested", outside.length === 0, outside.map((row) => row.url).join(", "));
  const real = errors.filter((entry) => !/favicon\.ico/.test(entry));
  check("no page error", real.length === 0, real.join(" | "));
  if (process.env.SECOND_ORDER_SCREENSHOTS) {
    await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 1800, deviceScaleFactor: 1, mobile: false });
    for (const [name, path] of [["findings", "/findings"], ["occasion", "/findings/2026-09-16"],
                                ["quiet", "/findings/2026-06-17"]]) {
      await open(path);
      await sleep(900);
      const shot = await send("Page.captureScreenshot", { format: "png" });
      writeFileSync(join(process.env.SECOND_ORDER_SCREENSHOTS, `${name}.png`), Buffer.from(shot.data, "base64"));
    }
  }
  ws.close();
} catch (error) {
  check("the findings browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(300);
  try { rmSync(root, { recursive: true, force: true }); } catch { /* Windows may hold a file briefly. */ }
}
console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
process.exit(results.every(Boolean) ? 0 : 1);
