// Browser check of the research views, against tests/review_browser_server.py serving a new, empty folder with
// --policy-research synthetic (SYNTHETIC retained sources and a SYNTHETIC research file; see
// tests/policy_research_fakes.py), or, as an explicit opt-in, SECOND_ORDER_POLICY_RESEARCH_SOURCES=<the retained
// data/sector-sources folder> (the committed views against the real retained sources, served read-only; a relative
// path is read from the repository, as the review server reads it, and a missing folder is refused). It checks:
// - discovery from the case library; the overview: research question, scope (a retrospective comparison of selected
//   retained publications), corpus limits, the labels' legend and the source check with its counts;
// - the chronology keeps listing times, release datelines and stated dates apart, each with its precision;
// - the matrix and the stage grid show one row per release, with publisher / curator / not-stated marks;
// - every comparison: the releases compared, the observation, expandable evidence with paragraph locators, why the
//   distinction helps (labelled interpretation) and what remains unknown;
// - each release's statements, silent dimensions without quotes, linked documents not retained, same-titled releases
//   kept apart (synthetic), and the records considered but not included;
// - (synthetic) a release written against another version needs revalidation, and missing sources make every
//   comparison unavailable, with observations withheld; restoring them restores the view;
// - a restart reads the same view; reads write nothing; nothing outside the local server is requested and nothing but
//   GET is sent; narrow screens; no page errors.
//
//   cd frontend; npm run build; npm run test:browser:policy-research
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync, rmSync, statSync, writeFileSync }
  from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const python = process.env.SECOND_ORDER_PYTHON ?? "python";
// The review server starts in the repository, so a relative opt-in path names the folder there; this script reads the
// same folder, never one relative to wherever npm was started (frontend/, where no such folder exists).
const realSources = process.env.SECOND_ORDER_POLICY_RESEARCH_SOURCES
  ? resolve(repo, process.env.SECOND_ORDER_POLICY_RESEARCH_SOURCES) : undefined;
const chromePath = [process.env.SECOND_ORDER_CHROME, "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
  "/usr/bin/chromium-browser"].find((path) => path && existsSync(path));
if (!chromePath) throw new Error("Chrome was not found; set SECOND_ORDER_CHROME to its executable.");
if (!existsSync(join(repo, "frontend/dist/index.html"))) throw new Error("Build the client first: npm run build");
if (realSources && !existsSync(realSources)) {
  throw new Error(`SECOND_ORDER_POLICY_RESEARCH_SOURCES names no folder: ${realSources}`);
}

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => { const { port } = server.address(); server.close(() => done(port)); });
});
const root = mkdtempSync(join(tmpdir(), "second-order-policy-research-check-"));
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
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];  // As format.ts.
const pad = (value) => String(value).padStart(2, "0");
const utc = (iso) => { const d = new Date(iso); return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}, ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`; };
const scenario = ["--policy-research", realSources ?? "synthetic"];
const content = realSources ? join(repo, "content/research") : join(served, "research");

async function startServer(port, extra = []) {
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    ...scenario, ...extra], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  for (let i = 0; i < 300; i++) {
    try { if ((await fetch(`http://127.0.0.1:${port}/api/research`)).ok) return server; } catch { /* starting */ }
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
  const contentBefore = tree(content);

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
  const waitFor = async (expression, timeout = 30000) => {
    for (const start = Date.now(); Date.now() - start < timeout; await sleep(80)) {
      if (await evaluate(expression)) return true;
    }
    return false;
  };
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);
  const count = (selector) => evaluate(`document.querySelectorAll(${JSON.stringify(selector)}).length`);
  const navigate = (path) => send("Page.navigate", { url: `${base}${path}` });
  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("Log.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  // 1. Discovery from the case library, and the overview.
  const catalog = await (await fetch(`${base}/api/research`)).json();
  const id = catalog.views[0].id;
  const page = `/library/research/${id}`;
  await navigate("/library");
  await waitFor(`!!document.querySelector("#research-views a.library-entry-title")`);
  check("the case library lists the research view, with its question and scope",
    (await evaluate(`document.querySelector("#research-views a.library-entry-title").getAttribute("href")`)) === page &&
    (await text("#research-views")).includes(catalog.views[0].question) &&
    (await text("#research-views")).includes(catalog.views[0].scope_note));
  await evaluate(`document.querySelector("#research-views a.library-entry-title").click()`);
  await waitFor(`location.pathname === ${JSON.stringify(page)} && !!document.querySelector(".policy-research h1")`);
  const view = await (await fetch(`${base}/api/research/${id}`)).json();
  const n = view.publications.length;
  const m = view.comparisons.length;
  const head = await text(".library-case-header");
  check("the overview states the question, the scope and the corpus limits",
    (await text(".policy-research h1")) === view.title && head.includes(view.question) &&
    (await text(".policy-scope")) === view.scope_note && (await count(".policy-corpus li")) === view.corpus_notes.length);
  if (realSources) {
    check("it is described as a retrospective comparison of selected retained publications, not a monitor",
      view.scope_note.includes("retrospective comparison") && view.scope_note.includes("not a complete or current"));
  }
  const legend = await text(".policy-legend");
  check("the legend explains publisher statement, curator interpretation, not stated, not retained and unknown",
    ["Publisher statement", "Curator interpretation", "Not stated in this source", "In a linked document not retained",
      "Unknown"].every((label) => legend.includes(label)));
  const status = await text(".policy-check");
  check("the source check states how many releases checked and comparisons are available",
    view.snapshot.state === "verified" && status.includes(`${n} of ${n} releases checked`) &&
    status.includes(`${m} of ${m} comparisons available`) &&
    status.includes(`${view.snapshot.filter_matches} records of the snapshot matched`), status);

  // 2. The chronology keeps its date fields apart.
  const moments = await evaluate(`[...document.querySelectorAll(".policy-moment")].map((li) => ({
    id: li.dataset.publication, rows: [...li.querySelectorAll(".policy-dates div")].map((div) =>
      [div.querySelector("dt").textContent, div.querySelector("dd").textContent]) }))`);
  const byId = new Map(view.publications.map((item) => [item.id, item]));
  const datesOk = moments.length === n && moments.every((moment, index) => {
    const item = byId.get(moment.id);
    const rows = Object.fromEntries(moment.rows.map(([label, value]) => [label, value]));
    const stated = item.dimensions.timing.statements.flatMap((statement) => statement.dates);
    return moment.id === view.publications[index].id && rows["BIS listing time"] === utc(item.listing.published) &&
      (item.dateline ? rows["Release dateline"] === item.dateline.value : !("Release dateline" in rows)) &&
      moment.rows.filter(([label]) => Object.values(view.labels.date_kinds).includes(label)).length === stated.length &&
      (stated.length > 0 || rows["Stated dates"] === "None stated in the text");
  });
  check("the chronology shows each listing time, a dateline only from a checked release page, and the stated dates",
    datesOk, JSON.stringify(moments.slice(0, 2)));
  const relative = view.publications.flatMap((item) => item.dimensions.timing.statements.flatMap((s) => s.dates))
    .find((date) => date.precision === "relative");
  const chronology = await text("#chronology");
  check("a relative date is quoted as stated and labelled with its precision",
    !relative || (chronology.includes(`“${relative.as_stated}”`) && chronology.includes("Relative to another date")));

  // 3. The matrix and the stage grid.
  const rows = await count(".policy-matrix tbody tr");
  const marks = await evaluate(`[...document.querySelectorAll(".policy-matrix tbody tr")].every((tr) =>
    tr.querySelectorAll("td").length === 4 && [...tr.querySelectorAll("td")].every((td) =>
      td.querySelector(".policy-mark")))`);
  check("the matrix has one row per release, every cell marked publisher, curator, not stated or not retained",
    rows === n && marks);
  const stages = view.publications.reduce((total, item) => total + item.stages.length, 0);
  check("the stage grid marks exactly the stages the releases name", (await count(".policy-stages .policy-named")) === stages &&
    (await count(".policy-stages tbody tr")) === n);

  // 4. Comparisons.
  check("every comparison is shown", (await count(".policy-comparison")) === m);
  let comparisonsOk = true;
  for (const comparison of view.comparisons) {
    const selector = `#cmp-${comparison.id}`;
    const shown = await evaluate(`(() => { const card = document.querySelector(${JSON.stringify(selector)});
      return { question: card.querySelector("h3").textContent, compared: card.querySelectorAll(".policy-compared a").length,
        observation: card.querySelector(".policy-observation")?.textContent ?? "", why: card.querySelector(".policy-why")?.textContent ?? "",
        unknown: card.querySelector(".policy-unknown")?.textContent ?? "", open: card.querySelector(".policy-evidence").open }; })()`);
    await evaluate(`document.querySelector(${JSON.stringify(`${selector} .policy-evidence summary`)}).click()`);
    await sleep(60);
    const quotes = await evaluate(`[...document.querySelectorAll(${JSON.stringify(`${selector} .policy-evidence .policy-quote`)})]
      .map((figure) => [figure.querySelector("blockquote").textContent, figure.querySelector("figcaption").textContent])`);
    const expected = comparison.evidence.filter((item) => item.kind === "quote");
    const located = quotes.length === expected.length && quotes.every(([quote, caption], index) =>
      quote === expected[index].quote &&
      caption.startsWith(`Paragraph ${expected[index].paragraph} of ${expected[index].paragraphs} · `));
    const ok = shown.question === comparison.question && shown.compared === comparison.publications.length &&
      shown.observation.includes(comparison.observation) && shown.why.includes(comparison.why) &&
      shown.why.includes("Curator interpretation") && shown.unknown.includes(comparison.unknown) &&
      shown.unknown.includes(comparison.would_establish) && shown.open === false && located;
    if (!ok) { comparisonsOk = false; console.log(`  ${comparison.id}: ${JSON.stringify(shown).slice(0, 300)}`); }
  }
  check("each comparison shows its releases, observation, evidence with paragraph locators, why and unknowns",
    comparisonsOk);
  const evidenceText = await text("#comparisons");
  check("listing metadata and checked absences are labelled as such",
    (!view.comparisons.some((c) => c.evidence.some((e) => e.kind === "field")) || evidenceText.includes("Listing metadata")) &&
    (!view.comparisons.some((c) => c.evidence.some((e) => e.kind === "absence")) ||
      evidenceText.includes("does not contain")));

  // 5. The releases.
  const first = view.publications[0];
  await evaluate(`document.querySelector("#pub-${first.id} summary").click()`);
  await sleep(100);
  const detail = await evaluate(`(() => { const d = document.querySelector("#pub-${first.id}");
    return { open: d.open, dimensions: d.querySelectorAll(".policy-dimensions > div").length,
      silentQuotes: [...d.querySelectorAll('.policy-statement[data-status="not_stated"]')].filter((li) =>
        li.querySelector(".policy-quote")).length,
      curator: [...d.querySelectorAll('.policy-statement[data-status="interpretation"] .policy-status')].every((tag) =>
        tag.textContent === "Curator interpretation"),
      references: d.querySelectorAll(".policy-references li").length }; })()`);
  check("a release opens to all seven dimensions, silent ones without quotes, interpretation labelled",
    detail.open && detail.dimensions === 7 && detail.silentQuotes === 0 && detail.curator &&
    detail.references === first.references.length, JSON.stringify(detail));
  const links = await evaluate(`[...document.querySelectorAll("a.library-external")].map((a) => [a.href, a.target, a.rel])`);
  check("outside links go only to bis.gov, in a new tab without a referrer",
    links.length > 0 && links.every(([href, target, rel]) => href.startsWith("https://www.bis.gov/") &&
      target === "_blank" && rel === "noreferrer"));
  if (!realSources) {
    const twins = await evaluate(`["synthetic-first", "synthetic-second"].map((id) => {
      const d = document.querySelector("#pub-" + id); d.open = true;
      const cells = [...d.querySelectorAll(".policy-ledger div")].map((div) => [div.querySelector("dt").textContent,
        div.querySelector("dd").textContent]);
      return Object.fromEntries(cells); })`);
    check("two releases with the same title stay two entries with their own addresses",
      twins[0]["Publisher's title"] === twins[1]["Publisher's title"] && twins[0].Address !== twins[1].Address);
  }
  check("the records considered but not included are listed with reasons",
    (await count(".policy-excluded li")) === view.not_included.length &&
    view.not_included.every((item) => evidenceText !== null) &&
    (await text("#not-included")).includes(view.not_included[0].reason));
  check("the claims not made are listed", (await count("#not-claimed li")) === view.not_claimed.length);

  // 6. (synthetic) A changed or missing source withholds what it supported, and restoring it restores the view.
  if (!realSources) {
    const file = join(content, id, "research.json");
    const original = readFileSync(file);
    const changed = JSON.parse(original.toString("utf8"));
    changed.publications[1].record.record_sha256 = "0".repeat(64);
    writeFileSync(file, JSON.stringify(changed, null, 2));
    await navigate(page);
    await waitFor(`!!document.querySelector('.policy-comparison[data-state="needs_revalidation"]')`);
    const card = await evaluate(`(() => { const c = document.querySelector('.policy-comparison[data-state="needs_revalidation"]');
      return { observation: !!c.querySelector(".policy-observation"), note: c.querySelector(".policy-withheld").textContent }; })()`);
    check("a release written against another version: its comparison needs revalidation and shows no observation",
      !card.observation && card.note.includes("Needs revalidation") && (await count(".policy-comparison .policy-observation")) === m - 1);
    writeFileSync(file, original);
    const bis = join(served, "policy-sources", "bis");
    renameSync(bis, `${bis}-away`);
    await navigate(page);
    await waitFor(`document.querySelectorAll('.policy-comparison[data-state="unavailable"]').length === ${m}`);
    check("without the retained snapshot every comparison is unavailable and nothing is shown as checked",
      (await count(".policy-comparison .policy-observation")) === 0 && (await count(".policy-stages .policy-named")) === 0 &&
      (await text(".policy-matrix tbody")).includes("Not checked here"));
    renameSync(`${bis}-away`, bis);
    await navigate(page);
    await waitFor(`document.querySelectorAll('.policy-comparison[data-state="available"]').length === ${m}`);
    check("restoring the sources restores every comparison", (await count(".policy-comparison .policy-observation")) === m);
  }

  // 7. A restart reads the same view; reading wrote nothing.
  const downFrom = errors.length;
  server.kill();
  await sleep(800);
  server = await startServer(port, ["--keep-records"]);
  const restartWindow = [downFrom, errors.length];
  const again = await (await fetch(`${base}/api/research/${id}`)).json();
  check("after a restart the view reads the same", JSON.stringify(again) === JSON.stringify(view));
  const contentAfter = tree(content);
  check("reading wrote nothing to the research files", realSources ? JSON.stringify(contentAfter) === JSON.stringify(contentBefore)
    : Object.keys(contentAfter).join() === Object.keys(contentBefore).join() &&
      Object.keys(contentAfter).every((key) => contentAfter[key].split(":")[0] === contentBefore[key].split(":")[0]));
  if (realSources) {  // Two empty trees would compare equal, so a check that hashed nothing fails.
    const hashed = Object.keys(sourcesBefore).length;
    check(`the retained folder was only read (${hashed} files hashed)`,
      hashed > 0 && JSON.stringify(tree(realSources)) === JSON.stringify(sourcesBefore));
  }

  // 8. Narrow screens.
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  await navigate(page);
  await waitFor(`!!document.querySelector(".policy-matrix")`);
  await evaluate(`document.querySelectorAll("details").forEach((d) => { d.open = true; })`);
  await sleep(600);
  const layout = await evaluate(`({ scroll: document.documentElement.scrollWidth, width: document.documentElement.clientWidth,
    stacked: getComputedStyle(document.querySelector(".policy-matrix thead")).position })`);
  check("narrow screen: no sideways scrolling, the matrix stacks by row", layout.scroll <= layout.width &&
    layout.stacked === "absolute", JSON.stringify(layout));

  const outside = requests.filter((row) => !row.url.startsWith(base) && !row.url.startsWith("data:") && row.url !== "about:blank");
  check("nothing outside the local server was requested", outside.length === 0, outside.map((row) => row.url).join(", "));
  check("nothing but GET was sent", requests.every((row) => row.method === "GET"),
    requests.filter((row) => row.method !== "GET").map((row) => row.url).join(", "));
  const real = errors.filter((item, index) => !/favicon\.ico/.test(item) && !(
    index >= restartWindow[0] && index < restartWindow[1] && item.includes("ERR_CONNECTION_REFUSED") && item.includes(base)));
  check("no page error", real.length === 0, real.join(" | "));
  if (process.env.SECOND_ORDER_SCREENSHOTS) {  // One bounded clip per part of the page, for a visual review.
    const parts = [["header", ".library-case-header"], ["chronology", "#chronology"], ["matrix", "#matrix"],
      ["stages", "#stages"], ["comparison", ".policy-comparison"], ["release", ".policy-publication"]];
    for (const [device, width, mobile] of [["desktop", 1280, false], ["phone", 375, true]]) {
      await send("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile });
      await navigate(page);
      await waitFor(`!!document.querySelector(".policy-matrix")`);
      await evaluate(`document.querySelector(".policy-evidence").open = true; document.querySelector(".policy-publication").open = true`);
      await sleep(900);
      for (const [name, selector] of parts) {
        const box = await evaluate(`(() => { const r = document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();
          return { x: 0, y: r.top + scrollY, width: ${width}, height: Math.min(Math.ceil(r.height), 2400) }; })()`);
        const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true,
          clip: { ...box, scale: 1 } });
        writeFileSync(join(process.env.SECOND_ORDER_SCREENSHOTS, `${device}-${name}.png`), Buffer.from(shot.data, "base64"));
      }
    }
  }
  ws.close();
} catch (error) {
  check("the research-view browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(300);
  try { rmSync(root, { recursive: true, force: true }); } catch { /* Windows may hold a file briefly. */ }
}
console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
process.exit(results.every(Boolean) ? 0 : 1);
