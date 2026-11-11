// Browser check of the retained BIS snapshot workflow, against tests/review_browser_server.py serving a new, empty
// folder with --bis-snapshot synthetic (a SYNTHETIC snapshot; see tests/bis_snapshot_fakes.py), or, as an explicit
// opt-in, SECOND_ORDER_BIS_SNAPSHOT_SOURCES=<the retained BIS folder> (served read-only; the index and every import stay
// in the temporary folder). It checks, in the page:
// - discovery from the Event inbox; the snapshot's verified source (SHA-256 against its acquisition record), labelled a
//   retained snapshot, not a live feed, local and free; nothing parsed until the explicit open;
// - opening builds the index once; a reload and a server restart reuse it without rebuilding;
// - browsing: semiconductor records first, counts matching the server's, search and filters, inspection of a record
//   (address, listing timestamp apart from the release dateline and the CMS times, plain-text paragraphs, no markup);
// - selecting, previewing (new records) and importing them; previewing again shows them reused and offers nothing to
//   import; a direct repeat import writes nothing;
// - the imported records in the Event inbox, apart from the feeds and without triage, and their event overview;
// - only the explicit actions write, only below the temporary folder; nothing outside the local server is requested;
//   narrow screens; no page errors.
//
//   cd frontend; npm run build; npm run test:browser:snapshot
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const python = process.env.SECOND_ORDER_PYTHON ?? "python";
const realSources = process.env.SECOND_ORDER_BIS_SNAPSHOT_SOURCES;
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
const root = mkdtempSync(join(tmpdir(), "second-order-snapshot-check-"));
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
const scenario = realSources ? ["--bis-snapshot", realSources] : ["--bis-snapshot", "synthetic"];

async function startServer(port, extra = []) {
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    ...scenario, ...extra], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  for (let i = 0; i < 300; i++) {
    try { if ((await fetch(`http://127.0.0.1:${port}/api/inbox`)).ok) return server; } catch { /* starting */ }
    await sleep(200);
  }
  throw new Error("The review server did not start.");
}

try {
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  let server = await startServer(port);
  const sourcesBefore = realSources ? tree(realSources) : null;

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
  const navigate = (path) => send("Page.navigate", { url: `${base}${path}` });
  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("Log.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const posts = () => requests.filter((row) => row.method !== "GET").map((row) => new URL(row.url).pathname);

  // 1. Discovery, and the snapshot before it is opened.
  await navigate("/");
  await waitFor(`!!document.querySelector(".inbox-snapshot-link a")`);
  check("the Event inbox links to the retained snapshot and says it is not a live feed",
    (await text(".inbox-snapshot-link")).includes("not a live feed"));
  await click(".inbox-snapshot-link a");
  await waitFor(`location.pathname === "/inbox/bis-snapshot" && !!document.querySelector(".snapshot-head h1")`);
  const unopened = await (await fetch(`${base}/api/inbox/snapshots/bis`)).json();
  await waitFor(`!!document.querySelector(".snapshot-open button")`);
  const head = await text(".snapshot-page");
  check("before opening: the verified source is shown, labelled a retained snapshot, local and free",
    unopened.state === "not_opened" && head.includes(unopened.package.sha256) &&
    head.includes("verified against its acquisition record") && head.includes("Retained snapshot, not a live feed") &&
    head.includes("Local and free") && !(await evaluate(`!!document.querySelector(".snapshot-rows")`)),
    unopened.state);
  check("nothing was written by reading the page", !existsSync(join(served, "bis-index")));

  // 2. Opening builds the index once.
  await click(".snapshot-open button");
  await waitFor(`document.querySelectorAll(".snapshot-entry").length > 0`);
  const opened = await (await fetch(`${base}/api/inbox/snapshots/bis`)).json();
  const counts = opened.counts;
  check("opening verifies the page and builds its local index once",
    (await text(".inbox-message.is-done")).includes("index was built") &&
    readdirSync(join(served, "bis-index")).length === 1 && posts().filter((path) => path.endsWith("/open")).length === 1);
  const indexTree = tree(join(served, "bis-index"));

  // 3. Browsing: semiconductor records first, counts as the server states them.
  const shownCount = async () => Number((await text(".inbox-filter-count")).match(/^(\d+) of (\d+)/)?.[1]);
  check("the first view lists the semiconductor and advanced-computing records, counted as the server counts them",
    (await shownCount()) === counts.filters.semiconductors &&
    (await evaluate(`document.querySelector('select[name="snapshot-filter"]').value`)) === "semiconductors" &&
    (await text(".snapshot-summary")).includes(`${counts.listed} records in the listing data`));
  const setSelect = (name, value) => evaluate(`(() => { const s = document.querySelector('select[name="${name}"]');
    const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set; set.call(s, ${JSON.stringify(value)});
    s.dispatchEvent(new Event("change", { bubbles: true })); })()`);
  await setSelect("snapshot-filter", "all");
  await waitFor(`/^${counts.usable} of/.test(document.querySelector(".inbox-filter-count")?.textContent ?? "")`);
  check("all records can be browsed", (await shownCount()) === counts.usable);
  const semis = opened.rows.filter((row) => row.filters.semiconductors)
    .sort((a, b) => (b.date ?? "").localeCompare(a.date ?? "") || a.position - b.position);
  // The title word that the fewest records name: a search for it must narrow the list.
  const haystack = (row) => [row.title, row.opening, ...row.topics, row.external_host ?? ""].join(" ").toLowerCase();
  const word = semis[0].title.toLowerCase().split(/[^a-z0-9]+/).filter((part) => part.length > 4)
    .map((part) => [part, opened.rows.filter((row) => haystack(row).includes(part)).length])
    .sort((a, b) => a[1] - b[1])[0][0];
  await evaluate(`(() => { const input = document.querySelector('input[name="snapshot-query"]');
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set; set.call(input, ${JSON.stringify(word)});
    input.dispatchEvent(new Event("input", { bubbles: true })); })()`);
  await sleep(300);
  const searched = await evaluate(`[...document.querySelectorAll(".snapshot-entry h3")].map((h) => h.textContent)`);
  check("search narrows to records whose title or opening text names the word",
    searched.includes(semis[0].title) && searched.length < counts.usable, `${word}: ${searched.length}`);
  await evaluate(`(() => { const input = document.querySelector('input[name="snapshot-query"]');
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set; set.call(input, "");
    input.dispatchEvent(new Event("input", { bubbles: true })); })()`);
  await setSelect("snapshot-filter", "semiconductors");
  await sleep(300);

  // 4. Inspecting a record.
  const target = semis.find((row) => row.completeness === "checked") ?? semis[0];
  const detailApi = await (await fetch(`${base}/api/inbox/snapshots/bis/records/${target.key}`)).json();
  await click(`.snapshot-entry[data-key="${target.key}"] .snapshot-inspect`);
  await waitFor(`!!document.querySelector('[data-detail="${target.key}"] .snapshot-facts')`);
  const detail = await text(`[data-detail="${target.key}"]`);
  const paragraphs = await evaluate(`[...document.querySelectorAll('[data-detail="${target.key}"] .snapshot-paragraphs p')]
    .map((p) => p.textContent)`);
  check("a record shows its address, listing timestamp, release dateline apart, CMS times as not publication times",
    detail.includes(target.link) && detail.includes("Listing timestamp") && detail.includes("Release dateline") &&
    detail.includes("Not publication times") &&
    (target.completeness !== "checked" || detail.includes(detailApi.record.check.dateline)), detail.slice(0, 200));
  check("its text is the record's own paragraphs, as plain text",
    JSON.stringify(paragraphs) === JSON.stringify(detailApi.record.text.paragraphs) &&
    !(await evaluate(`/<script|<iframe|<b>/i.test(document.querySelector('[data-detail="${target.key}"] .snapshot-paragraphs')?.innerHTML ?? "")`)));
  if (!realSources) {
    const markup = opened.rows.find((row) => row.title === "Synthetic Markup Test");
    await setSelect("snapshot-filter", "all");
    await sleep(200);
    await click(`.snapshot-entry[data-key="${markup.key}"] .snapshot-inspect`);
    await waitFor(`!!document.querySelector('[data-detail="${markup.key}"] .snapshot-paragraphs')`);
    const shown = await evaluate(`(() => { const box = document.querySelector('[data-detail="${markup.key}"] .snapshot-paragraphs');
      return { text: box.textContent, elements: [...box.querySelectorAll("*")].map((e) => e.tagName) }; })()`);
    check("markup in the listing's text is shown as text: no element, script or link is created from it",
      shown.text.includes("Plain & safe <b> text") && shown.elements.every((tag) => tag === "P") &&
      !shown.text.includes("alert"), JSON.stringify(shown));
    await setSelect("snapshot-filter", "semiconductors");
    await sleep(200);
  }

  // 5. Select, preview, import.
  const chosen = semis.filter((row) => row.import.state === "new").slice(0, 2);
  for (const row of chosen) await click(`.snapshot-entry[data-key="${row.key}"] .inbox-select input`);
  await waitFor(`(document.querySelector(".snapshot-selection")?.textContent ?? "").startsWith("2 of at most 25 selected")`);
  check("two records are selected, within the limit of 25",
    (await text(".snapshot-selection")).startsWith("2 of at most 25 selected"));
  const beforePreview = tree(served);
  await click(".snapshot-preview");
  await waitFor(`!!document.querySelector('.snapshot-group[data-group="new"]')`);
  check("the preview lists both as new, says it is local and free, and wrote nothing",
    (await text('.snapshot-group[data-group="new"]')).includes("New: will be added (2)") &&
    (await text(".snapshot-preview-result")).includes("Local and free") &&
    (await text(".snapshot-run")).includes("Import 2 records into the Event Inbox (local, $0)") &&
    JSON.stringify(tree(served)) === JSON.stringify(beforePreview));
  await click(".snapshot-run");
  await waitFor(`!!document.querySelector(".snapshot-result")`);
  const resultText = await text(".snapshot-result");
  check("the import adds both and records the import", resultText.includes("2 added") && resultText.includes("Import 20"));
  await waitFor(`document.querySelectorAll('.snapshot-entry[data-import="imported"]').length >= 2`);
  check("the records now say they are in the Event Inbox",
    (await evaluate(`[...document.querySelectorAll('.snapshot-entry[data-import="imported"]')].map((e) => e.dataset.key)`))
      .filter((key) => chosen.some((row) => row.key === key)).length === 2);
  const afterImport = tree(served);
  const added = Object.keys(afterImport).filter((name) => !(name in beforePreview));
  check("the import wrote only its entries and its import record, below the temporary folder",
    added.length === 3 && added.every((name) => name.startsWith("event-inbox/imports/bis-snapshot/")), added.join(", "));

  // 6. Repeating: reused, nothing written.
  await click(".snapshot-preview");
  await waitFor(`!!document.querySelector('.snapshot-group[data-group="existing"]')`);
  check("previewing again shows both reused and offers nothing to import",
    (await text('.snapshot-group[data-group="existing"]')).includes("Already imported: reused, nothing written (2)") &&
    (await evaluate(`document.querySelector(".snapshot-run").disabled`)) &&
    (await text(".snapshot-run")).includes("Nothing new to import"));
  const repeat = await evaluate(`fetch("/api/inbox/snapshots/bis/import", { method: "POST", headers: {
    "Content-Type": "application/json", "X-Second-Order-Inbox": "1" },
    body: JSON.stringify({ keys: ${JSON.stringify(chosen.map((row) => row.key))}, decisions: {} }) })
    .then(async (r) => ({ status: r.status, body: await r.json() }))`);
  check("a repeated import is answered as reused and writes nothing",
    repeat.status === 200 && repeat.body.counts.reused === 2 && repeat.body.written === false &&
    JSON.stringify(tree(served)) === JSON.stringify(afterImport));

  // 7. The Event inbox and the event overview.
  await navigate("/");
  await waitFor(`document.querySelectorAll(".inbox-imported-items .inbox-item").length === 2`);
  const importedSection = await text(".inbox-imported");
  check("the Event inbox lists the imported records apart from the feeds, labelled, without triage",
    importedSection.includes("Imported from a retained snapshot (2)") &&
    importedSection.includes("Imported from a retained BIS snapshot, not a live feed") &&
    importedSection.includes("Not offered for headline triage") &&
    (await evaluate(`document.querySelectorAll(".inbox-imported-items .inbox-select").length`)) === 0 &&
    (await evaluate(`document.querySelectorAll(".inbox-items:not(.inbox-imported-items) .is-imported").length`)) === 0);
  check("an imported entry shows its listing timestamp as listing metadata",
    importedSection.includes("Listing timestamp") && importedSection.includes("not the release's dateline"));
  await click(".inbox-imported-items .inbox-overview");
  await waitFor(`location.pathname.startsWith("/events/inbox/bis-snapshot") && !!document.querySelector("#overview-source")`);
  await waitFor(`(document.querySelector("#overview-source")?.textContent ?? "").includes("Listing timestamp")`);
  const overview = await text("main");
  check("its event overview names the snapshot, keeps the dates apart and says triage is not offered",
    overview.includes("Imported from a retained BIS snapshot, not a live feed") && overview.includes("CMS times") &&
    overview.includes("not offered for records imported from a retained snapshot"), overview.slice(0, 200));

  // 8. A reload and a restart reuse the index and keep the imports.
  await navigate("/inbox/bis-snapshot");
  await waitFor(`document.querySelectorAll(".snapshot-entry").length > 0`);
  check("a reload opens straight from the reused index, with no rebuild",
    JSON.stringify(tree(join(served, "bis-index"))) === JSON.stringify(indexTree) &&
    posts().filter((path) => path.endsWith("/open")).length === 1);
  const downFrom = errors.length;  // While the server is deliberately down, the open page's requests are refused.
  server.kill();
  await sleep(800);
  server = await startServer(port, ["--keep-records"]);
  await sleep(300);
  const restartWindow = [downFrom, errors.length];
  await navigate("/inbox/bis-snapshot");
  await waitFor(`document.querySelectorAll('.snapshot-entry[data-import="imported"]').length >= 2`, 30000);
  check("after a server restart the index is reused and the imported records are still there",
    JSON.stringify(tree(join(served, "bis-index"))) === JSON.stringify(indexTree) &&
    (await evaluate(`document.querySelectorAll('.snapshot-entry[data-import="imported"]').length`)) >= 2);

  // 9. Narrow screens.
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  await navigate("/inbox/bis-snapshot");
  await waitFor(`document.querySelectorAll(".snapshot-entry").length > 0`);
  await sleep(600);
  const layout = await evaluate(`({ scroll: document.documentElement.scrollWidth, width: document.documentElement.clientWidth })`);
  check("narrow screen: no sideways scrolling", layout.scroll <= layout.width, JSON.stringify(layout));

  const outside = requests.filter((row) => !row.url.startsWith(base) && !row.url.startsWith("data:") && row.url !== "about:blank");
  check("nothing outside the local server was requested", outside.length === 0, outside.map((row) => row.url).join(", "));
  check("only the explicit open, previews and imports were sent as writes",
    posts().every((path) => /^\/api\/inbox\/snapshots\/bis\/(open|preview|import)$/.test(path)), posts().join(", "));
  if (realSources) check("the retained folder was only read", JSON.stringify(tree(realSources)) === JSON.stringify(sourcesBefore));
  // Attributed by source: the favicon probe, and refused local requests logged only inside the deliberate restart window.
  const real = errors.filter((item, index) => !/favicon\.ico/.test(item) && !(
    index >= restartWindow[0] && index < restartWindow[1] && item.includes("ERR_CONNECTION_REFUSED") &&
    item.includes(base)));
  check("no page error", real.length === 0, real.join(" | "));
  ws.close();
} catch (error) {
  check("the snapshot browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(300);
  try { rmSync(root, { recursive: true, force: true }); } catch { /* Windows may hold a file briefly. */ }
}
console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
process.exit(results.every(Boolean) ? 0 : 1);
