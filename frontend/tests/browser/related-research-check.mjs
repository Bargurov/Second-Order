// Browser check of Related research, against tests/review_browser_server.py serving a new, empty folder with
// --related-research (the committed case library; SYNTHETIC Inbox entries and one capture). It checks:
// - a compact, labelled section on the event overview, below Related historical cases, linked from the overview's
//   table of contents;
// - coverage of this event (same address and date), a release family (FOMC minutes against a statement case, with the
//   document and date differences), a topic link, and no link for a shared publisher, a later case or a WTO item;
// - each link's content status and writing date; links open the existing library pages;
// - reads write nothing, narrow screens, page errors and no request outside the local server.
//
//   cd frontend; npm run build; npm run test:browser:related-research
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

const TITLES = {
  ev: "U.S. electricity use for electric vehicles increasing at a slower pace in 2026",
  minutes: "Minutes of the Federal Open Market Committee, September 15-16, 2026",
  discount: "Minutes of the Board's discount rate meetings on July 20 and July 29, 2026",
  winter: "Mixed outlook for energy expenditures this winter",
  newEngland: "New England natural gas prices have been trading near record discounts",
  trade: "Members discuss trade and climate measures",
  statement: "Federal Reserve issues FOMC statement",
};
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => { const { port } = server.address(); server.close(() => done(port)); });
});
const root = mkdtempSync(join(tmpdir(), "second-order-research-check-"));
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

try {
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    "--related-research"], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  for (let i = 0; i < 300; i++) {
    try { if ((await fetch(`${base}/api/inbox`)).ok) break; } catch { /* starting */ }
    await sleep(200);
  }
  const inbox = await (await fetch(`${base}/api/inbox`)).json();
  const entry = (title) => [...inbox.items, ...inbox.retained].find((item) => item.title === title).id;
  const capture = (await (await fetch(`${base}/api/intake`)).json()).captures.find((row) => row.headline === TITLES.statement)
    .capture_id;

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
  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("Log.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const open = async (kind, id) => {
    await send("Page.navigate", { url: `${base}/events/${kind}/${encodeURIComponent(id)}` });
    await waitFor(`document.querySelector("#overview-research")?.dataset.state === "ready"`);
    return text("#overview-research");
  };
  const relations = () => evaluate(`[...document.querySelectorAll("#overview-research .research-link")]
    .map((row) => [row.dataset.relation, row.dataset.target])`);
  const before = tree(served);

  // 1. Coverage of this event.
  const ev = await open("inbox", entry(TITLES.ev));
  const order = await evaluate(`[...document.querySelectorAll(".overview-section")].map((s) => s.id)`);
  check("the section sits below Related historical cases and the table of contents links to it",
    order.indexOf("overview-research") === order.indexOf("overview-related") + 1 &&
    (await text(".overview-toc")).includes("Related research"), JSON.stringify(order));
  check("the same address and date are labelled as coverage of this event, not corroboration",
    same(await relations(), [["same_event", "eia-tie-2026-09-30"]]) && ev.includes("Coverage of this event") &&
    ev.includes("not a separate source and not a corroboration"), ev.slice(0, 300));
  check("the link states its content status and that the case was written after the event",
    ev.includes("Editorial case · AI-assisted · Not human-reviewed · Not research evidence") &&
    ev.includes("after this event; it was not available when the event happened"));

  // 2. Same release family: minutes against a statement case.
  const minutes = await open("inbox", entry(TITLES.minutes));
  check("FOMC minutes link to the latest earlier statement case as the same family, with the differences",
    same(await relations(), [["release_family", "fomc-2025-06-18"]]) &&
    minutes.includes("Different documents: this event is FOMC meeting minutes, the case an FOMC statement.") &&
    minutes.includes("about 16 months earlier") && minutes.includes("carries only its title"));
  check("the other earlier cases of the family are one link away",
    (await evaluate(`[...document.querySelectorAll("#overview-research a")].some((a) =>
      a.getAttribute("href") === "/library?category=monetary-policy" && a.textContent.includes("3 more earlier"))`)));
  const statement = await open("capture", capture);
  check("a capture with the recurring statement title is a family link, never coverage of the event",
    same(await relations(), [["release_family", "fomc-2025-06-18"]]) && statement.includes("about 3 months earlier"));

  // 3. Topic, and no link where none is supported.
  const winter = await open("inbox", entry(TITLES.winter));
  check("a topic link names the terms found and says it is not the same mechanism",
    same(await relations(), [["topic", "eia-tie-2026-09-25"]]) &&
    winter.includes("“natural gas” and “prices” in the feed excerpt") && winter.includes("not the same mechanism"));
  for (const [name, title, note] of [["a shared publisher", TITLES.discount, null],
                                     ["a later case", TITLES.newEngland, "later case is not suggested"],
                                     ["an unrelated WTO item", TITLES.trade, null]]) {
    const body = await open("inbox", entry(title));
    check(`no link for ${name}`, (await relations()).length === 0 &&
      body.includes("No related research in the library for this event.") && (!note || body.includes(note)));
  }

  // 4. Links open the existing library pages; reads wrote nothing.
  await open("inbox", entry(TITLES.ev));
  await evaluate(`document.querySelector('#overview-research [data-target="eia-tie-2026-09-30"] .related-case-title').click()`);
  await waitFor(`location.pathname === "/library/eia-tie-2026-09-30" && !!document.querySelector("h1")`);
  check("a link opens the existing library case page", (await text("h1")).startsWith("EV electricity use grew 8%"));
  check("reading related research wrote nothing", same(tree(served), before));
  check("no write request was sent", requests.every((row) => row.method === "GET"));

  // 5. Narrow screens.
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  await open("inbox", entry(TITLES.minutes));
  await sleep(600);
  const layout = await evaluate(`({ scroll: document.documentElement.scrollWidth, width: document.documentElement.clientWidth })`);
  check("narrow screen: no sideways scrolling", layout.scroll <= layout.width, JSON.stringify(layout));

  const outside = requests.filter((row) => !row.url.startsWith(base) && !row.url.startsWith("data:") && row.url !== "about:blank");
  check("nothing outside the local server was requested", outside.length === 0, outside.map((row) => row.url).join(", "));
  const real = errors.filter((item) => !/favicon\.ico/.test(item));
  check("no page error", real.length === 0, real.join(" | "));
  ws.close();
} catch (error) {
  check("the related-research browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(300);
  try { rmSync(root, { recursive: true, force: true }); } catch { /* Windows may hold a file briefly. */ }
}
console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
process.exit(results.every(Boolean) ? 0 : 1);
