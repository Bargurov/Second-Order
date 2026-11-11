// Browser check of the copper tools page (/theses/copper/tools), against tests/review_browser_server.py serving a new,
// empty folder with --copper-tools synthetic (SYNTHETIC retained sources and inputs catalogue; see tests/copper_fakes.py),
// or, as an explicit opt-in, SECOND_ORDER_THESIS_SOURCES=<the retained data/sector-sources/copper folder> (the committed
// catalogue against the real retained sources, served read-only; the step that removes a retained folder runs only on
// the synthetic copy; a relative path is read from the repository, and a missing folder is refused). It checks:
// - discovery: the copper thesis page and the case library link to the tools;
// - the header's read count, and every shown number marked as published, assumption, computed or missing;
// - the Part 0 box: eight links of the chain with statuses, linking only to the four existing pages, each of which opens;
// - the published baseline for Stated Policies 2035 (R 12,789 kt, 38.2%, its change 8,241), epsilon and delta, the mine
//   rows, and the IEA "Copper - Refining" series apart with its notes and its three unknowns;
// - no recycling control on the page, and a recycling field refused by the server;
// - the design's assumption set A computed (≈ 12,622.835 kt) with its three flags; computing writes nothing;
// - saving writes one record below the served root only, a repeat writes nothing, and the record is listed verified;
// - replies bound to their inputs, with requests held in Chrome (Fetch domain) while an input changes: a preview sent
//   for 2035 and released after 2040 is chosen is neither shown nor savable, computing again shows 2040's result, a save
//   held while the scenario changes is reported for the scenario it saved and its record is exactly that scenario, and
//   a capital-panel reply sent for 8% and released after 0 is typed is not shown;
// - the producer comparison (five rows, Southern Copper's margin not shown) and the capital panel with no defaults:
//   a zero rate uses 1/n (Tia Maria ≈ 0.341 $/lb over 20 years), and a negative rate or a fractional life is refused;
// - (synthetic) with one producer filing's folder removed, its figures are withheld and its reference magnitude too;
// - reads write nothing to the sources; only local requests; no page errors (each attributed to its URL); no sideways
//   scrolling at 375 px; page chrome free of affirmative recommendation and price-direction phrasings.
//
//   cd frontend; npm run build; npm run test:browser:copper-tools
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync, rmSync, statSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const python = process.env.SECOND_ORDER_PYTHON ?? "python";
const realSources = process.env.SECOND_ORDER_THESIS_SOURCES
  ? resolve(repo, process.env.SECOND_ORDER_THESIS_SOURCES) : undefined;
const chromePath = [process.env.SECOND_ORDER_CHROME, "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
  "/usr/bin/chromium-browser"].find((path) => path && existsSync(path));
if (!chromePath) throw new Error("Chrome was not found; set SECOND_ORDER_CHROME to its executable.");
if (!existsSync(join(repo, "frontend/dist/index.html"))) throw new Error("Build the client first: npm run build");
if (realSources && !existsSync(realSources)) throw new Error("SECOND_ORDER_THESIS_SOURCES names no folder.");

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => { const { port } = server.address(); server.close(() => done(port)); });
});
const root = mkdtempSync(join(tmpdir(), "second-order-copper-tools-check-"));
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
      else found[relative(folder, full).replaceAll("\\", "/")] =
        `${createHash("sha256").update(readFileSync(full)).digest("hex")}:${statSync(full).mtimeMs}`;
    }
  };
  walk(folder);
  return found;
};
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const lower = (value) => value.toLowerCase().replace(/\s+/g, " ");
const strings = (value, out = []) => {
  if (typeof value === "string") out.push(value);
  else if (Array.isArray(value)) value.forEach((item) => strings(item, out));
  else if (value && typeof value === "object") Object.values(value).forEach((item) => strings(item, out));
  return out;
};
// Affirmative recommendation and price-direction phrasings, never bare stems (thesis-check.mjs): the page's lines that
// name what they deny ("not a shortage", "no price view") must pass.
const AFFIRMATIVE = [
  /\b(?:we|i) (?:recommend|suggest|advise)\b/, /(?<!not a )\brecommendation to (?:buy|sell|hold)\b/,
  /\b(?:should|must|time to|consider) (?:buy|sell)(?:ing)?\b/, /\b(?:buy|sell|hold) (?:signal|rating|now|call)\b/,
  /\bstrong (?:buy|sell)\b/, /\bgo (?:long|short)\b/, /\b(?:over|under)weight\b/, /\b(?:out|under)perform/,
  /\bprice target (?:of|is)\b/, /\btarget price\b/,
  /\bprices? (?:will|would|should|could|may|is likely to|are likely to|is expected to|are expected to) (?:rise|fall|climb|drop|increase|decrease|go up|go down)\b/,
  /\bprices? (?:rises?|rising|falls?|falling|climbs?|climbing|drops?|dropping|rall(?:y|ies)|surges?|slumps?|spikes?)\b/,
  /\b(?:higher|lower|rising|falling) (?:copper )?prices?\b/, /\b(?:upside|downside)\b/, /\b(?:bullish|bearish)\b/,
  /\b(?:upward|downward|price) pressure\b/,
  /\b(?:there is|there will be|faces?|facing) a (?:copper )?(?:shortage|deficit)\b/, /\bshortage of \d/,
  /\bwill (?:close|be built)\b/, /\bnot at risk of clos/,
];
const affirmative = (text) => AFFIRMATIVE.filter((pattern) => pattern.test(lower(text))).map(String);
const chromeOf = (pageText, ...replies) => {
  let rest = lower(pageText);
  const all = [...new Set(replies.flatMap((reply) => strings(reply)))].filter((value) => /\s/.test(value.trim()))
    .map(lower).sort((a, b) => b.length - a.length);
  for (const value of all) rest = rest.split(value).join(" ¦ ");
  return rest;
};
const fcxMode = realSources && existsSync(join(repo, "data/company-sources/fcx")) ? "retained" : "synthetic";
const scenario = ["--copper-tools", realSources ?? "synthetic", "--company-fcx", fcxMode];
const sources = realSources ?? join(served, "copper-sources");
const records = join(served, "copper-scenarios");

async function startServer(port, args = scenario, folder = served) {
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", folder, "--port", String(port),
    ...args], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  for (let i = 0; i < 300; i++) {
    try { if ((await fetch(`http://127.0.0.1:${port}/api/tools/copper`)).ok) return server; } catch { /* starting */ }
    await sleep(200);
  }
  throw new Error("The review server did not start.");
}

try {
  check("the phrasing scan flags affirmative phrasings and passes the lines that name what they deny",
    affirmative("R is what the counted pipeline leaves; it is not a shortage. No price view.").length === 0 &&
    ["PRICES WILL RISE", "there is a copper shortage", "the upside case", "time to sell", "this mine will close",
      "output is not at risk of closing"].every((phrase) => affirmative(phrase).length > 0));

  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const getJson = async (path) => (await fetch(`${base}${path}`)).json();
  await startServer(port);
  const sourcesBefore = tree(sources);
  const contentBefore = tree(join(repo, "content"));

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
  const paused = [];  // Fetch.requestPaused: requests held in Chrome.
  const responses = [];  // The URL of every response the page received.
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else if (message.method === "Network.requestWillBeSent") {
      requests.push({ method: message.params.request.method, url: message.params.request.url });
    } else if (message.method === "Fetch.requestPaused") {
      paused.push(message.params);
    } else if (message.method === "Network.responseReceived") {
      responses.push(message.params.response.url);
    } else if (message.method === "Runtime.exceptionThrown") {
      const details = message.params.exceptionDetails;
      errors.push({ text: details.exception?.description ?? details.text, url: details.url ?? "" });
    } else if (message.method === "Log.entryAdded" && message.params.entry.level === "error") {
      errors.push({ text: message.params.entry.text, url: message.params.entry.url ?? "" });
    }
  });
  const send = (method, params = {}) => new Promise((done, fail) => {
    const id = ++counter;
    pending.set(id, (message) => message.error ? fail(new Error(message.error.message)) : done(message.result));
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) =>
    (await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })).result.value;
  const waitFor = async (expression, timeout = 30000) => {
    for (const start = Date.now(); Date.now() - start < timeout; await sleep(80)) {
      if (await evaluate(expression)) return true;
    }
    return false;
  };
  const q = JSON.stringify;
  const inner = (selector) => evaluate(`document.querySelector(${q(selector)})?.innerText ?? ""`);
  const navigate = (path) => send("Page.navigate", { url: `${base}${path}` });
  const click = (selector) => evaluate(`(() => { const e = document.querySelector(${q(selector)}); if (!e) return false;
    e.click(); return true; })()`);
  const clickText = (scope, label) => evaluate(`(() => { const e = [...document.querySelectorAll(${q(scope)})]
    .find((x) => x.textContent.trim().startsWith(${q(label)})); if (!e) return false; e.click(); return true; })()`);
  const type = (selector, value) => evaluate(`(() => { const e = document.querySelector(${q(selector)}); if (!e) return false;
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set; set.call(e, ${q(value)});
    e.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
  const radio = (selector) => evaluate(`(() => { const e = document.querySelector(${q(selector)}); if (!e) return false;
    e.click(); return e.checked; })()`);
  const pageReady = `!!document.querySelector('article.ct-page h1')`;
  /** Hold the next request to `path` in Chrome, run `meanwhile` while it is held, then release it and wait until its
   * reply has reached the page: a delayed reply that arrives after an input changed. True when a request was held. */
  const holding = async (path, start, meanwhile) => {
    paused.length = 0;
    const arrived = () => responses.filter((url) => url.endsWith(path)).length;
    const before = arrived();
    await send("Fetch.enable", { patterns: [{ urlPattern: `*${path}`, requestStage: "Request" }] });
    await start();
    for (let i = 0; i < 300 && paused.length === 0; i++) await sleep(50);
    const held = paused.length === 1;
    await meanwhile();
    await sleep(200);
    if (held) await send("Fetch.continueRequest", { requestId: paused[0].requestId });
    await send("Fetch.disable");
    for (let i = 0; i < 300 && arrived() === before; i++) await sleep(50);
    await sleep(400);  // Let the page handle the reply it received.
    return held && arrived() > before;
  };
  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("Log.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  // 1. Discovery.
  await navigate("/theses/copper");
  await waitFor(`!!document.querySelector('a[href="/theses/copper/tools"]')`);
  check("the copper thesis page links to the tools",
    await evaluate(`!!document.querySelector('a[href="/theses/copper/tools"]')`));
  await navigate("/library");
  await waitFor(`!!document.querySelector('[data-tools="copper"] a[href="/theses/copper/tools"]')`);
  check("the case library lists the tools beside the copper thesis",
    await evaluate(`!!document.querySelector('[data-thesis="copper"] [data-tools="copper"] a[href="/theses/copper/tools"]')`));

  // 2. The page.
  const view = await getJson("/api/tools/copper");
  await navigate("/theses/copper/tools");
  check("the tools page loads", await waitFor(pageReady));
  const header = await inner(".ct-header");
  check("the header states what this read found",
    header.includes(`${view.catalog.verified} of ${view.catalog.items} figures and passages found where cited`) &&
    lower(header).includes("tools, not a view"));
  check("every shown number carries its kind", await evaluate(`[...document.querySelectorAll(".ct-value")]
    .every((e) => e.querySelector(".ct-kind"))`) && await evaluate(`document.querySelectorAll(".ct-value").length > 40`));

  // 3. Part 0.
  const chain = await evaluate(`[...document.querySelectorAll("[data-link]")].map((li) => ({ id: li.dataset.link,
    status: li.dataset.status, hrefs: [...li.querySelectorAll("a")].map((a) => a.getAttribute("href")) }))`);
  const hrefs = [...new Set(chain.flatMap((link) => link.hrefs))].sort();
  check("the Part 0 box lists eight links of the chain with statuses",
    chain.length === 8 && chain.every((link) => link.status) && chain.find((l) => l.id === "L2")?.status === "missing");
  check("the box links only to the four existing pages",
    same(hrefs, ["/findings", "/findings/g17", "/library/research/semiconductor-policy", "/theses/copper"]), hrefs.join());

  // 4. The published baseline: Stated Policies 2035.
  await radio(`input[name="ct-year"][value="2035"]`);
  await radio(`input[name="ct-scenario"][value="steps"]`);
  await waitFor(`document.querySelector('[data-row="residual"]')?.innerText.includes("12,789")`);
  const results = await inner(`[data-table="results"]`);
  check("R for Stated Policies 2035 is 12,789 kt, 38.2% of demand, up 8,241 since 2025",
    results.includes("12,789") && results.includes("38.2") && results.includes("+8,241"), results.slice(0, 300));
  const demand = await inner(`[data-table="demand"]`);
  check("the demand table shows the published rows, epsilon and delta",
    demand.includes("33,522") && demand.includes("-2.0132") && await evaluate(`document.querySelectorAll('[data-table="demand"] tbody tr').length === 12`));
  const refining = await inner(".ct-refining");
  check("the refining series is shown apart under its source name, with its notes and its three unknowns",
    refining.includes("Copper - Refining") && await evaluate(`document.querySelectorAll(".ct-refining [data-unknowns] li").length === 3`) &&
    await evaluate(`document.querySelectorAll(".ct-refining [data-passage] q").length === 2`));

  // 5. Recycling is not an input.
  const recycling = await evaluate(`[...document.querySelectorAll("#controls input, #controls label, #controls legend")]
    .some((e) => /recycl/i.test(e.textContent + (e.getAttribute("name") ?? "")))`);
  const refused = await evaluate(`fetch("/api/tools/copper/preview", { method: "POST", headers: { "Content-Type":
    "application/json", "X-Second-Order-Scenario": "1" }, body: JSON.stringify({ scenario: "steps", year: "2035",
    assumptions: { recycling: { kt: "160" } } }) }).then(async (r) => ({ status: r.status, body: await r.json() }))`);
  check("the page has no recycling control, and the server refuses a recycling field",
    !recycling && refused.status === 422 && /Recycling is not an input/.test(refused.body.detail ?? ""));

  // 6. Assumption set A.
  const beforePreview = tree(served);
  await clickText(`[data-control="ev"] label`, "Another published scenario");
  await evaluate(`(() => { const s = document.querySelector('[data-control="ev"] select'); s.value = "cps";
    s.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`);
  await clickText(`[data-control="networks"] label`, "The published");
  await evaluate(`(() => { const s = document.querySelector('[data-control="networks"] select'); s.value = "steps";
    s.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`);
  await clickText(`[data-control="mine"] label`, "A signed change");
  await waitFor(`!!document.querySelector(".ct-references button")`);
  await clickText(`.ct-references button`, "Enter as a reduction");
  await clickText(`#controls button`, "Compute with these inputs");
  await waitFor(`document.querySelector('[data-row="residual"]')?.innerText.includes("12,622.835")`);
  const assumed = await inner(`[data-table="results"]`);
  const flags = await evaluate(`[...document.querySelectorAll("[data-flag]")].map((e) => e.dataset.flag)`);
  check("assumption set A gives R' ≈ 12,622.835 kt, shown rounded with its exact value kept",
    assumed.includes("≈ 12,622.835"), assumed.slice(0, 400));
  check("its flags are hybrid, technology case and reference magnitude",
    same(flags, ["hybrid", "technology_case", "reference_magnitude"]), flags.join());
  check("computing wrote nothing", same(tree(served), beforePreview) && !existsSync(records));

  // 7. Save once.
  await type(`#save input[type="text"]`, "Set A in the browser check");
  await clickText(`#save button`, "Save this scenario");
  await waitFor(`!!document.querySelector('.ct-saved[data-status="created"]')`);
  const files = existsSync(records) ? readdirSync(records) : [];
  await waitFor(`document.querySelectorAll('[data-record][data-state="verified"]').length === 1`);
  check("saving writes one record below the served root, listed verified",
    files.length === 1 && /^[0-9a-f]{64}\.json$/.test(files[0]) &&
    await evaluate(`document.querySelectorAll('[data-record][data-state="verified"]').length === 1`));
  const written = tree(records);
  await clickText(`#save button`, "Save this scenario");
  await waitFor(`!!document.querySelector('.ct-saved[data-status="unchanged"]')`);
  check("saving it again writes nothing", same(tree(records), written));

  // 7b. Replies bound to the inputs they were sent for.
  const residualCell = `document.querySelector('[data-row="residual"] td:last-child')?.innerText ?? ""`;
  const saveDisabled = `document.querySelector('#save button')?.disabled === true`;
  const heldPreview = await holding("/api/tools/copper/preview",
    () => clickText(`#controls button`, "Compute with these inputs"),
    () => radio(`input[name="ct-year"][value="2040"]`));
  const afterStale = await evaluate(residualCell);
  check("a preview sent for 2035 and released after 2040 was chosen is not shown",
    heldPreview && afterStale.trim() === "\u2014" && !(await inner(`[data-table="results"]`)).includes("12,622.835"),
    afterStale);
  check("and nothing can be saved from it", await evaluate(saveDisabled));
  await clickText(`#controls button`, "Compute with these inputs");
  await waitFor(`(${residualCell}).includes("16,874.835")`);
  check("computing again for 2040 shows 2040's result, R' \u2248 16,874.835 kt",
    (await evaluate(residualCell)).includes("\u2248 16,874.835"));
  await type(`#save input[type="text"]`, "Set A for 2040");
  const before2040 = new Set(existsSync(records) ? readdirSync(records) : []);
  const heldSave = await holding("/api/tools/copper/scenarios",
    () => clickText(`#save button`, "Save this scenario"),
    () => radio(`input[name="ct-scenario"][value="hd"]`));
  await waitFor(`!!document.querySelector('.ct-saved[data-status="created"]')`);
  const report = await evaluate(`(() => { const e = document.querySelector(".ct-saved"); return e ? { scenario:
    e.dataset.savedScenario, year: e.dataset.savedYear, text: e.innerText } : null; })()`);
  const added = (existsSync(records) ? readdirSync(records) : []).filter((name) => !before2040.has(name));
  const record = added.length === 1 ? JSON.parse(readFileSync(join(records, added[0]), "utf8")).record : null;
  check("a save held while the scenario changed is reported for the scenario it saved, Stated Policies 2040",
    heldSave && report?.scenario === "steps" && report?.year === "2040" &&
    report.text.includes("Stated Policies scenario 2040"), JSON.stringify(report));
  check("and its record is exactly the scenario the preview showed",
    record?.baseline?.scenario === "steps" && record?.baseline?.year === "2040" &&
    record?.result?.residual?.value === "16874.8350405", JSON.stringify(record?.baseline));
  check("with the scenario changed, nothing can be saved until it is computed again",
    await evaluate(saveDisabled) && (await evaluate(residualCell)).trim() === "\u2014");

  // 8. Producers and the capital panel.
  const rows = await evaluate(`[...document.querySelectorAll('[data-table="costs"] [data-row]')].map((r) => r.dataset.state)`);
  check("the comparison shows its five rows", rows.length === 5 && rows.every((state) => state === "available"),
    rows.join());
  check("Southern Copper's margin is not shown",
    await evaluate(`document.querySelector('[data-margin="scco"]')?.dataset.state === "not_retained"`));
  check("the capital panel starts empty", await evaluate(`[...document.querySelectorAll('[data-panel="capital"] input')]
    .every((e) => e.value === "")`));
  await type(`[data-panel="capital"] input[inputmode="decimal"]`, "8");
  await type(`[data-panel="capital"] input[inputmode="numeric"]`, "20");
  const heldPanel = await holding("/api/tools/copper/capital-charge",
    () => clickText(`[data-panel="capital"] button`, "Compute the capital charge"),
    () => type(`[data-panel="capital"] input[inputmode="decimal"]`, "0"));
  check("a panel reply sent for 8% and released after 0 was typed is not shown",
    heldPanel && !(await evaluate(`!!document.querySelector('[data-panel-result]')`)) &&
    !(await inner(`[data-panel="capital"]`)).includes("0.101852"));
  await clickText(`[data-panel="capital"] button`, "Compute the capital charge");
  await waitFor(`!!document.querySelector('[data-panel-result="limit_at_zero_rate"]')`);
  const panel = await inner(`[data-panel="capital"]`);
  check("a zero rate recovers the capital evenly: CRF 0.050000, Tia Maria ≈ 0.341 $/lb",
    panel.includes("0.050000") && panel.includes("≈ 0.341"), panel.slice(0, 300));
  for (const [rate, years] of [["-1", "20"], ["8", "2.5"]]) {
    await type(`[data-panel="capital"] input[inputmode="decimal"]`, rate);
    await type(`[data-panel="capital"] input[inputmode="numeric"]`, years);
    await clickText(`[data-panel="capital"] button`, "Compute the capital charge");
    await waitFor(`!!document.querySelector('[data-panel="capital"] [role="alert"]')`);
    check(`the panel refuses rate ${rate}, life ${years}`,
      await evaluate(`!!document.querySelector('[data-panel="capital"] [role="alert"]')`));
  }

  // 8b. Bagdad's two company statements: the later one from the FCX records, the earlier 10-K one unchanged.
  {
    const tools = await getJson("/api/tools/copper");
    const linked = tools.linked.records;
    const earlier = tools.producers.projects.find((item) => item.id === "bagdad").statement;
    const order = await evaluate(`[...document.querySelectorAll('[data-table="projects"] tbody tr')].map((r) => r.dataset.project)`);
    check("the later Bagdad statement comes first and the earlier one second",
      same(order.slice(0, 2), ["bagdad-2026-11-04", "bagdad"]), order.join());
    const row = (id) => `[data-table="projects"] [data-project="${id}"]`;
    const stamp = await inner(`${row("bagdad-2026-11-04")} [data-statement]`);
    check("the later row's stamp names its kind, date and document",
      stamp === "Company estimates · stated 4 Nov 2026 · Freeport-McMoRan news release", stamp);
    const earlierStamp = await inner(`${row("bagdad")} [data-statement]`);
    check("the earlier row's stamp names the 10-K and when it was signed",
      earlierStamp.startsWith("Earlier statement · signed ") && earlierStamp.endsWith(earlier.document), earlierStamp);
    const nameCell = await inner(`${row("bagdad-2026-11-04")} th`);
    const earlierName = await inner(`${row("bagdad")} th`);
    const lines = (text) => text.split(/\r?\n/).map((line) => line.trim());
    check("each Bagdad stamp and the terms sit on their own lines under the project name",
      lines(nameCell).some((line) => line.startsWith("Company estimates · "))
        && lines(nameCell).some((line) => line.startsWith("Source terms: "))
        && lines(earlierName).some((line) => line.startsWith("Earlier statement · "))
        && !/\)(Company|Earlier)|release(Source)/.test(nameCell + earlierName), JSON.stringify([nameCell, earlierName]));
    check("the later row states the documents' terms",
      (await inner(`${row("bagdad-2026-11-04")} [data-terms]`)).includes("SEC EDGAR copy"));
    const current = await inner(row("bagdad-2026-11-04"));
    const cells = await evaluate(`[...document.querySelectorAll(${q(row("bagdad-2026-11-04") + " td")})].map((c) => c.innerText)`);
    check("its capacity is the incremental long-term annual rate",
      cells[1].includes("≈ 225") && cells[1].includes("million pounds per year")
        && cells[1].includes("incremental, long-term annual rate"), cells[1]);
    check("its capital is the company's estimate", cells[2].includes("≈ $4.5") && cells[2].includes("billion"), cells[2]);
    check("its capital per annual tonne is computed on its own figures", cells[3].includes("44,092"), cells[3]);
    check("its incentive price is not stated", cells[5].trim() === "Not stated", cells[5]);
    const breakEven = await inner(`${row("bagdad-2026-11-04")} [data-break-even]`);
    check("break-even economics sits in its own column, with its molybdenum condition",
      breakEven.includes("≈ $4.00") && breakEven.includes("$20") && breakEven.includes("molybdenum"), breakEven);
    const timing = cells[4];
    check("the timing cell holds the approval twice, the construction period and the start as words",
      timing.includes(linked["nr-p-board-approval"].quote) && timing.includes(linked["q3-p-bagdad-approval"].quote)
        && timing.includes("≈ 3.5") && timing.includes("years") && timing.includes("mid-2030"), timing.slice(0, 400));
    const caveats = await inner(`${row("bagdad-2026-11-04")} [data-caveats]`);
    check("the company's caveats sit under the later row's capital",
      caveats.toLowerCase().includes("company caveats") && caveats.includes(linked["nr-p-cost-risk"].quote)
        && caveats.includes(linked["nr-p-estimates-change"].quote), caveats.slice(0, 300));
    const badge = await evaluate(`(() => { const k = document.querySelector('[data-linked="nr-bagdad-capex-estimate"] .ct-kind');
      return k ? [k.title, k.getAttribute("aria-label")] : null; })()`);
    check("a later figure's badge names its document, date and page",
      same(badge, ["Company estimate · news release, 4 Nov 2026, p. 2", "Company estimate · news release, 4 Nov 2026, p. 2"]),
      JSON.stringify(badge));
    const earlierCells = await evaluate(`[...document.querySelectorAll(${q(row("bagdad") + " td")})].map((c) => c.innerText)`);
    check("the earlier row keeps its incentive prices and states no break-even",
      earlierCells[5].includes("$4.00") && earlierCells[5].includes("$3.50") && earlierCells[6].trim() === "Not stated",
      earlierCells.slice(5).join(" | "));
    check("the earlier row's capital per annual tonne is unchanged",
      earlierCells[3].includes("38,581") && earlierCells[3].includes("30,865"), earlierCells[3]);
    check("the two notes are shown under the table",
      (await inner(`[data-note="incentive_break_even"]`)) === tools.producers.notes.incentive_break_even
        && (await inner(`[data-note="no_path"]`)) === tools.producers.notes.no_path);
    check("the project table has no control of its own",
      await evaluate(`document.querySelectorAll('[data-table="projects"] button, [data-table="projects"] input, [data-table="projects"] [tabindex]').length === 0`));
    check("the later row shows no withheld value", !current.includes("Withheld"), current.slice(0, 200));
    await type(`[data-panel="capital"] input[inputmode="decimal"]`, "8");
    await type(`[data-panel="capital"] input[inputmode="numeric"]`, "20");
    await clickText(`[data-panel="capital"] button`, "Compute the capital charge");
    await waitFor(`!!document.querySelector('[data-panel-result="annuity"]')`);
    const later = await inner(`[data-charge-project="bagdad-2026-11-04"]`);
    const older = await inner(`[data-charge-project="bagdad"]`);
    check("the capital panel computes each Bagdad statement on its own figures",
      later.includes("2.037") && later.includes("Company estimates") && older.includes("1.782") && older.includes("1.426")
        && older.includes("Earlier statement"), `${later} | ${older}`);
  }

  // 9. A missing producer filing (synthetic only).
  if (!realSources) {
    const folder = join(sources, "fcx-synthetic-2024");
    const away = join(root, "fcx-synthetic-2024-away");
    renameSync(folder, away);
    await navigate("/theses/copper/tools");
    await waitFor(pageReady);
    const reference = await inner(`[data-table="perturbations"] tr[data-kind="reference_magnitude"]`);
    check("a missing filing withholds its figures and its reference magnitude",
      await evaluate(`!!document.querySelector('[data-project="bagdad"] .ct-withheld')`) &&
      reference.includes("Withheld"), reference);
    renameSync(away, folder);
    await navigate("/theses/copper/tools");
    await waitFor(pageReady);
    check("restoring it restores them", await evaluate(`!document.querySelector('[data-project="bagdad"] .ct-withheld')`));
  }

  // 10. Narrow screen, chrome wording, requests and errors.
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  await navigate("/theses/copper/tools");
  await waitFor(pageReady);
  await sleep(300);
  const overflow = await evaluate(`document.documentElement.scrollWidth - document.documentElement.clientWidth`);
  check("no sideways scrolling at 375 px", overflow <= 0, String(overflow));
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  await navigate("/theses/copper/tools");
  await waitFor(pageReady);
  await sleep(300);
  const phone = await evaluate(`(() => { const shown = (s) => { const e = document.querySelector(s); const r = e?.getBoundingClientRect();
    return !!r && r.width > 0 && r.height > 0; };
    return { overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      stamp: shown('[data-project="bagdad-2026-11-04"] [data-statement]'), notes: shown('[data-note="no_path"]'),
      inner: document.querySelector('[data-table="projects"]')?.parentElement?.scrollWidth >
        document.querySelector('[data-table="projects"]')?.parentElement?.clientWidth }; })()`);
  check("at 390 px the page does not scroll sideways; the stamps and notes are visible",
    phone.overflow <= 0 && phone.stamp && phone.notes, JSON.stringify(phone));
  const found = affirmative(chromeOf(await inner("body"), view));
  check("the page's own words make no recommendation and state no price direction", found.length === 0, found.join());
  const outside = requests.filter((r) => !r.url.startsWith(base) && !r.url.startsWith("data:") && !r.url.startsWith("about:"));
  check("only requests to the local server", outside.length === 0, outside.map((r) => r.url).join());
  const writes = requests.filter((r) => r.method !== "GET" && r.method !== "HEAD").map((r) => new URL(r.url).pathname);
  check("the only writes are the explicit POSTs",
    writes.every((path) => ["/api/tools/copper/preview", "/api/tools/copper/scenarios",
      "/api/tools/copper/capital-charge"].includes(path)), writes.join());
  // The browser logs the deliberate refusals above (a recycling field, a negative rate, a fractional life) as failed
  // loads of exactly those endpoints; each is attributed to its URL and set aside, as is the favicon probe.
  const deliberate = (e) => /status of 422/.test(e.text) &&
    /\/api\/tools\/copper\/(preview|capital-charge)$/.test(e.url);
  const real = errors.filter((e) => !e.url.endsWith("/favicon.ico") && !deliberate(e));
  check("no page errors", real.length === 0, real.map((e) => `${e.text} @ ${e.url}`).join(" | "));
  // 11. Without FCX documents: only the later Bagdad row is withheld, naming the release; the earlier row stands.
  {
    await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
    const bare = join(root, "served-no-fcx");
    mkdirSync(bare);
    const barePort = await freePort();
    await startServer(barePort, ["--copper-tools", realSources ?? "synthetic"], bare);
    await send("Page.navigate", { url: `http://127.0.0.1:${barePort}/theses/copper/tools` });
    await waitFor(pageReady);
    const current = await inner(`[data-table="projects"] [data-project="bagdad-2026-11-04"]`);
    const problem = await inner(`[data-table="projects"] [data-project="bagdad-2026-11-04"] [data-linked-problem]`);
    const earlier = await inner(`[data-table="projects"] [data-project="bagdad"]`);
    check("without FCX documents the later row is withheld, naming the release, with no number",
      current.includes("Withheld") && problem.includes("the Bagdad release of 4 November 2026")
        && !/\b225\b|\b4\.5\b|44,092/.test(current), `${problem} | ${current.slice(0, 200)}`);
    const bareName = await inner(`[data-table="projects"] [data-project="bagdad-2026-11-04"] th`);
    check("the withheld reason sits on its own line under the stamp",
      bareName.split(/\r?\n/).some((line) => line.trim().startsWith("Not shown: ")), JSON.stringify(bareName));
    check("without FCX documents the earlier row is unchanged",
      earlier.includes("38,581") && earlier.includes("30,865"), earlier.slice(0, 200));
  }
  check("the retained sources and committed content are unchanged by the run",
    same(tree(sources), sourcesBefore) && same(tree(join(repo, "content")), contentBefore));
} catch (error) {
  check("the check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(300);
  try { rmSync(root, { recursive: true, force: true }); } catch { /* Windows may hold a file briefly */ }
  const failed = results.filter((ok) => !ok).length;
  console.log(`\n${results.length - failed}/${results.length} checks passed`);
  process.exitCode = failed ? 1 : 0;
}
