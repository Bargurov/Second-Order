// Browser check of the exposure map on the thesis page, against tests/review_browser_server.py serving a new, empty
// folder with --thesis synthetic (SYNTHETIC retained sources and thesis; see tests/thesis_fakes.py), or, as an explicit
// opt-in, SECOND_ORDER_THESIS_SOURCES=<the retained data/sector-sources/copper folder> (the committed content/theses
// against the real retained sources, served read-only; the steps that remove or change a retained file run only on the
// synthetic copy). It checks:
// - the map opens the "Who is exposed" section ahead of both exposure tables, leads with who is exposed and through
//   what mechanism, and is not a table (the two tables, and their rows, are unchanged);
// - the plain notes on incidence, pass-through and operating exposure, and a legend of the three kinds of line (stated,
//   conditional, not measured) that says lines carry no arrowheads; no arrow glyph anywhere in the map;
// - one lane per company the thesis moves, in served order, on its served side, with its side's stages from a change in
//   the copper price (producer: revenue, margin, operating cash flow; user: input cost, its own selling prices,
//   margin, operating cash flow), and no figure or number placed on any stage;
// - each available lane's statement with its served status, its stated figure's metric exactly as served, the cited
//   figures and passages to inspect, and a computed amount as served; nothing computed by the page;
// - one line per company that moves a reason, read from the reply alone: the reason's measure when its cited figures
//   include the reason's latest measured figure, related otherwise, withheld when either is not available;
// - every summary and link in the map is reachable by keyboard, and Enter opens what a lane rests on;
// - reads write nothing; (synthetic) with a source folder removed, and with a retained file changed, the parts that rest
//   on it are withheld on the map too, and none of their withheld facts is in the page's text, attributes or accessible
//   names; restoring the file restores them;
// - a 390 px wide screen without sideways scrolling, with each lane's stages stacked inside the screen;
// - page chrome free of affirmative recommendation and price-direction phrasings; only GETs to the local server; no
//   page errors.
//
//   cd frontend; npm run build; npm run test:browser:thesis-map
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
const root = mkdtempSync(join(tmpdir(), "second-order-thesis-map-check-"));
const served = join(root, "served");
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
/** {relative path: SHA-256} of every file below a folder. */
const hashes = (folder) => {
  const found = {};
  if (!existsSync(folder)) return found;
  const walk = (path) => {
    for (const name of readdirSync(path)) {
      const full = join(path, name);
      if (statSync(full).isDirectory()) walk(full);
      else found[relative(folder, full).replaceAll("\\", "/")] = createHash("sha256").update(readFileSync(full)).digest("hex");
    }
  };
  walk(folder);
  return found;
};
/** As hashes, with each file's modification time, so that a read that rewrote a file unchanged is seen too. */
const tree = (folder) => Object.fromEntries(Object.entries(hashes(folder)).map(([path, hash]) =>
  [path, `${hash}:${statSync(join(folder, path)).mtimeMs}`]));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const lower = (value) => value.toLowerCase().replace(/\s+/g, " ");
/** Every string the reply serves, wherever it sits. */
const strings = (value, out = []) => {
  if (typeof value === "string") out.push(value);
  else if (Array.isArray(value)) value.forEach((item) => strings(item, out));
  else if (value && typeof value === "object") Object.values(value).forEach((item) => strings(item, out));
  return out;
};

// Affirmative recommendation and price-direction phrasings, as thesis-check.mjs scans them.
const AFFIRMATIVE = [
  /\b(?:we|i) (?:recommend|suggest|advise)\b/,
  /(?<!not a )\brecommendation to (?:buy|sell|hold)\b/,
  /\brecommends? (?:buying|selling|holding|a (?:buy|sell))\b/,
  /\b(?:should|must|time to|consider) (?:buy|sell)(?:ing)?\b/,
  /\b(?:buy|sell|hold) (?:signal|rating|now|call)\b/,
  /\bstrong (?:buy|sell)\b/,
  /\bgo (?:long|short)\b/,
  /\b(?:over|under)weight\b/,
  /\b(?:out|under)perform/,
  /\bprice target (?:of|is)\b/,
  /\btarget price\b/,
  /\bprices? (?:will|would|should|could|may|is likely to|are likely to|is set to|are set to|is expected to|are expected to) (?:rise|fall|climb|drop|increase|decrease|go up|go down|move up|move down)\b/,
  /\bprices? (?:rises?|rising|falls?|falling|climbs?|climbing|drops?|dropping|rall(?:y|ies)|surges?|slumps?|spikes?)\b/,
  /\b(?:higher|lower|rising|falling) (?:copper )?prices?\b/,
  /\b(?:upside|downside)\b/,
  /\b(?:bullish|bearish)\b/,
  /\b(?:upward|downward|price) pressure\b/,
  /\btighter than the price\b/,
];
const affirmative = (text) => AFFIRMATIVE.filter((pattern) => pattern.test(lower(text))).map(String);
/** The page's own words: its text with every multi-word string of the served replies set aside. */
const chromeOf = (pageText, ...replies) => {
  let rest = lower(pageText);
  const shown = [...new Set(replies.flatMap((reply) => strings(reply)))].filter((value) => /\s/.test(value.trim()))
    .map(lower).sort((a, b) => b.length - a.length);
  for (const value of shown) rest = rest.split(value).join(" ¦ ");
  return rest;
};

// The map's contract, written out here rather than imported, so that this check states it on its own.
const STAGES = { producer: ["revenue", "margin", "cash_flow"], consumer: ["input_cost", "selling_price", "margin", "cash_flow"] };
const LINK_OF = { measure: "stated", related: "unmeasured", withheld: null };
const ARROWS = /[\u2190-\u21ff\u27f0-\u27ff\u2900-\u297f\u25b2-\u25c5\u2b00-\u2b2f]|->|=>/;
const kindOf = (reply, mover) => {
  const reason = reply.reasons.find((item) => item.id === mover.moves);
  if (mover.state !== "available" || !reason || reason.state !== "available") return "withheld";
  return reason.measure && mover.cites.includes(reason.measure.latest.id) ? "measure" : "related";
};
const scenario = ["--thesis", realSources ?? "synthetic"];
const content = realSources ? join(repo, "content/theses") : join(served, "theses");
const sources = realSources ?? join(served, "thesis-sources");

async function startServer(port) {
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    ...scenario], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  for (let i = 0; i < 300; i++) {
    try { if ((await fetch(`http://127.0.0.1:${port}/api/theses`)).ok) return server; } catch { /* starting */ }
    await sleep(200);
  }
  throw new Error("The review server did not start.");
}

try {
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const getJson = async (path) => (await fetch(`${base}${path}`)).json();
  await startServer(port);
  const contentBefore = tree(content);
  const sourcesBefore = tree(sources);

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
  const count = (selector) => evaluate(`document.querySelectorAll(${q(selector)}).length`);
  const inner = (selector) => evaluate(`document.querySelector(${q(selector)})?.innerText ?? ""`);
  const navigate = (path) => send("Page.navigate", { url: `${base}${path}` });
  const openMap = async (id, version) => {
    await navigate(`/theses/${id}`);
    await waitFor(`!!document.querySelector('article.thesis[data-version="${version}"] [data-exposure-map]')`);
  };
  /** The page's text and every attribute value (accessible names, titles, data attributes), hashes set aside. */
  const pageWords = () => evaluate(`(document.body.innerText + " " + [...document.querySelectorAll("*")]
    .flatMap((e) => [...e.attributes].map((a) => a.value)).join(" ")).replace(/[0-9a-f]{10,}/g, "")`);
  const lanesOnPage = () => evaluate(`[...document.querySelectorAll("[data-exposure-map] [data-map-lane]")].map((lane) => ({
    id: lane.dataset.mapLane, side: lane.dataset.side, state: lane.dataset.state,
    stages: [...lane.querySelectorAll("[data-stage]")].map((node) => node.dataset.stage),
    stageText: [...lane.querySelectorAll("[data-stage]")].map((node) => node.innerText).join(" | "),
    stageFigures: lane.querySelectorAll("[data-stage] [data-figure], [data-stage] [data-passage]").length,
    status: lane.querySelector("[data-statement-status]")?.dataset.statementStatus ?? null,
    statusText: lane.querySelector("[data-statement-status]")?.textContent ?? null,
    metric: lane.querySelector("[data-map-metric]")?.textContent ?? null,
    figures: [...lane.querySelectorAll("[data-figure]")].map((node) => node.dataset.figure),
    passages: [...lane.querySelectorAll("[data-passage]")].map((node) => node.dataset.passage),
    computed: lane.querySelector("[data-map-computed]")?.innerText ?? null,
    withheld: !!lane.querySelector("[data-withheld]"), label: lane.getAttribute("aria-label"), text: lane.innerText }))`);
  const moversOnPage = () => evaluate(`[...document.querySelectorAll("[data-exposure-map] [data-map-mover]")].map((row) => ({
    id: row.dataset.mapMover, kind: row.dataset.kind, link: row.querySelector("[data-link]")?.dataset.link ?? null,
    href: row.querySelector("a[href^='#reason-']")?.getAttribute("href") ?? null,
    status: !!row.querySelector("[data-status-of]"), inspect: !!row.querySelector("details"),
    figures: [...row.querySelectorAll("[data-figure]")].map((node) => node.dataset.figure),
    passages: [...row.querySelectorAll("[data-passage]")].map((node) => node.dataset.passage),
    label: row.getAttribute("aria-label"), text: row.innerText }))`);
  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("Log.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  const catalog = await getJson("/api/theses");
  const id = catalog.theses?.[0]?.id;
  if (!id) throw new Error("The server lists no thesis.");
  const reply = await getJson(`/api/theses/${id}`);
  await openMap(id, reply.version);

  // 1. The map opens the section, ahead of both tables, and leads with who is exposed and through what.
  const order = await evaluate(`(() => { const s = document.querySelector("#exposure");
    const map = s.querySelector("[data-exposure-map]"); const tables = [...s.querySelectorAll("table")];
    return { tables: tables.length, ahead: tables.every((t) => !!(map.compareDocumentPosition(t) & Node.DOCUMENT_POSITION_FOLLOWING)),
      inMap: map.querySelectorAll("table").length, lead: map.querySelector("[data-map-lead]")?.innerText ?? "" }; })()`);
  check("the map opens the exposure section ahead of both tables, and is not itself a table",
    order.tables === 2 && order.ahead && order.inMap === 0, JSON.stringify(order));
  check("the map leads with who is exposed and through what mechanism",
    lower(order.lead).includes("who is exposed") && lower(order.lead).includes("mechanism"), order.lead);
  check("the exposure tables keep one row per company, as before",
    (await count("#exposure table [data-mover]")) === reply.exposure.movers.length &&
    (await count("#exposure table [data-moved]")) === reply.exposure.moved.length &&
    (await count("[data-mover]")) === reply.exposure.movers.length && (await count("[data-moved]")) === reply.exposure.moved.length);

  // 2. Plain notes and the legend.
  const notes = await evaluate(`[...document.querySelectorAll("[data-exposure-map] [data-concept]")]
    .map((node) => [node.dataset.concept, node.innerText])`);
  const noteOf = (name) => lower(notes.find(([key]) => key === name)?.[1] ?? "");
  check("the map explains incidence, pass-through and operating exposure in plain words",
    same(notes.map(([key]) => key), ["incidence", "pass-through", "operating-exposure"]) &&
    noteOf("incidence").includes("bears") && ["timing", "spread", "inventory"].every((word) => noteOf("pass-through").includes(word)) &&
    noteOf("operating-exposure").includes("share of sales") && noteOf("operating-exposure").includes("sensitivity"),
    JSON.stringify(notes));
  const legend = await evaluate(`(() => { const l = document.querySelector("[data-exposure-map] [data-map-legend]");
    return { kinds: [...l.querySelectorAll("[data-link]")].map((node) => node.dataset.link), text: l.innerText }; })()`);
  check("the legend tells the three kinds of line apart and says lines carry no arrowheads",
    same(legend.kinds, ["stated", "conditional", "unmeasured"]) && lower(legend.text).includes("no arrowheads"),
    JSON.stringify(legend));
  const mapText = await inner("[data-exposure-map]");
  check("no arrow glyph anywhere in the map", !ARROWS.test(mapText), mapText.match(ARROWS)?.[0]);

  // 3. One lane per company the thesis moves, on its side, with its side's stages.
  await evaluate(`document.querySelectorAll("[data-exposure-map] details").forEach((d) => { d.open = true; })`);
  const lanes = await lanesOnPage();
  check("one lane per company the thesis moves, in served order, on its served side",
    same(lanes.map((lane) => [lane.id, lane.side, lane.state]),
      reply.exposure.moved.map((moved) => [moved.id, moved.side, moved.state])), JSON.stringify(lanes.map((l) => l.id)));
  check("each lane runs from a change in the copper price through its side's stages, kept apart",
    lanes.every((lane) => same(lane.stages, ["price", ...STAGES[lane.side]])), JSON.stringify(lanes.map((l) => l.stages)));
  check("no figure, passage or number is placed on any stage",
    lanes.every((lane) => lane.stageFigures === 0 && !/\d/.test(lane.stageText)), lanes.map((l) => l.stageText).join(" || "));
  const shownLanes = lanes.filter((lane) => lane.state === "available");
  check("each available lane shows its statement with its served status, and its figure's metric exactly as served",
    shownLanes.length > 0 && shownLanes.every((lane) => {
      const moved = reply.exposure.moved.find((item) => item.id === lane.id);
      const stated = moved.amount.kind === "stated";
      return lane.text.includes(moved.how.text) && lane.status === moved.how.status &&
        lane.statusText === reply.labels.statuses[moved.how.status] &&
        (stated ? lane.metric === moved.amount.figure.measure && lane.figures.includes(moved.amount.figure.id)
          : lane.metric === null && lane.computed.includes(moved.usd_per_unit) &&
            (moved.share_pct === null || lane.computed.includes(`${moved.share_pct}%`)));
    }), JSON.stringify(shownLanes.map((l) => [l.id, l.status, l.metric])));
  check("each available lane lets the reader inspect every figure and passage its statement cites",
    shownLanes.every((lane) => {
      const moved = reply.exposure.moved.find((item) => item.id === lane.id);
      return moved.how.cites.every((cite) => lane.figures.includes(cite) || lane.passages.includes(cite));
    }));
  check("a lane's accessible name is its company and side only",
    lanes.every((lane) => {
      const moved = reply.exposure.moved.find((item) => item.id === lane.id);
      return lane.label === `${moved.company}, ${reply.labels.sides[moved.side].split(":")[0].toLowerCase()}`;
    }), JSON.stringify(lanes.map((l) => l.label)));
  // Every metric word the map shows is one the reply serves: a cash-flow sensitivity is not renamed EBITDA, nor a
  // share of sales a profit figure.
  const servedWords = strings(reply).join(" \n ").toLowerCase();
  const renamed = ["ebitda", "earnings", "profit sensitivity", "share price", "stock"].filter((word) =>
    lower(mapText).includes(word) && !servedWords.includes(word));
  check("the map names no financial measure the reply does not serve", renamed.length === 0, renamed.join(", "));

  // 4. The companies that move a reason, read from the reply alone.
  const movers = await moversOnPage();
  check("one line per company that moves a reason, its kind read from the ids it cites and the reason's measure",
    same(movers.map((row) => [row.id, row.kind, row.link]), reply.exposure.movers.map((mover) =>
      [mover.id, kindOf(reply, mover), LINK_OF[kindOf(reply, mover)]])), JSON.stringify(movers.map((r) => [r.id, r.kind, r.link])));
  check("each line links its reason, and shows the reason's status and what it cites only when both check",
    movers.every((row) => {
      const mover = reply.exposure.movers.find((item) => item.id === row.id);
      const read = row.kind !== "withheld";
      return row.href === `#reason-${mover.moves}` && row.status === read && row.inspect === read &&
        (!read || mover.cites.every((cite) => row.figures.includes(cite) || row.passages.includes(cite)));
    }), JSON.stringify(movers));

  // 5. Keyboard.
  const reach = await evaluate(`[...document.querySelectorAll("[data-exposure-map] summary, [data-exposure-map] a")]
    .map((node) => node.tabIndex)`);
  check("every summary and link in the map is reachable by keyboard", reach.length > 0 && reach.every((tab) => tab >= 0),
    JSON.stringify(reach));
  await openMap(id, reply.version);
  const summary = `document.querySelector("[data-exposure-map] [data-map-lane][data-state=available] .thesis-rests summary")`;
  await evaluate(`${summary}.focus()`);
  const key = { key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 };
  await send("Input.dispatchKeyEvent", { type: "keyDown", ...key, text: "\r" });
  await send("Input.dispatchKeyEvent", { type: "keyUp", ...key });
  check("Enter on a focused lane opens what its statement rests on",
    await waitFor(`document.activeElement === ${summary} && ${summary}.parentElement.open`, 3000));

  // 6. Reading wrote nothing.
  check("reading wrote nothing to the thesis files", same(tree(content), contentBefore));
  check("reading wrote nothing to the retained sources", Object.keys(sourcesBefore).length > 0 &&
    same(tree(sources), sourcesBefore));

  // 7. (synthetic) A source removed, then a retained file changed: what rests on it is withheld on the map too.
  if (!realSources) {
    const withheldOnMap = async (name, before, after) => {
      await evaluate(`document.querySelectorAll("[data-exposure-map] details").forEach((d) => { d.open = true; })`);
      const pageLanes = await lanesOnPage();
      const pageMovers = await moversOnPage();
      const hidden = after.exposure.moved.filter((moved) => moved.state !== "available");
      check(`${name}: the lanes that rest on it are withheld on the map, with no statement, figure or metric`,
        hidden.length > 0 && hidden.every((moved) => {
          const lane = pageLanes.find((item) => item.id === moved.id);
          return lane && lane.state === moved.state && lane.withheld && lane.status === null && lane.metric === null &&
            lane.figures.length === 0 && lane.passages.length === 0 && lane.computed === null;
        }), JSON.stringify(pageLanes.map((l) => [l.id, l.state, l.withheld])));
      check(`${name}: the companies whose link rests on it are withheld, with nothing to inspect`,
        pageMovers.every((row) => row.kind === kindOf(after, after.exposure.movers.find((item) => item.id === row.id))) &&
        pageMovers.filter((row) => row.kind === "withheld").every((row) => !row.inspect && !row.status &&
          row.figures.length === 0 && row.passages.length === 0) && pageMovers.some((row) => row.kind === "withheld"),
        JSON.stringify(pageMovers.map((r) => [r.id, r.kind])));
      // A withheld fact: a string served before that the reply no longer serves (numbers, texts, quotes, metrics).
      // A value that a string still served contains (a year inside a title) is not withheld by the change.
      const still = strings(after).join(" \n ");
      const gone = [...new Set(strings(before))].filter((value) => !still.includes(value) && (/\d/.test(value) || value.length > 3));
      const words = await pageWords();
      const leaked = gone.filter((value) => words.includes(value));
      check(`${name}: none of the withheld facts is in the page's text, attributes or accessible names`,
        gone.length > 0 && leaked.length === 0, leaked.slice(0, 5).join(" | "));
    };
    const folder = join(sources, "sec-producer-2025");
    renameSync(folder, `${folder}-away`);
    try {
      await openMap(id, reply.version);
      await withheldOnMap("without the sec-producer-2025 files", reply, await getJson(`/api/theses/${id}`));
    } finally {
      renameSync(`${folder}-away`, folder);
    }
    const file = join(sources, "sec-maker-2025", "10k.htm");
    const original = readFileSync(file);
    writeFileSync(file, Buffer.concat([original, Buffer.from("\n<!-- changed -->\n")]));
    try {
      await openMap(id, reply.version);
      const after = await getJson(`/api/theses/${id}`);
      check("the changed file reads as changed", after.sources.find((item) => item.id === "sec-maker-2025")?.state === "changed");
      await withheldOnMap("with the sec-maker-2025 file changed", reply, after);
    } finally {
      writeFileSync(file, original);
    }
    await openMap(id, reply.version);
    const restored = await lanesOnPage();
    check("restoring the files restores every lane and the retained bytes",
      same(restored.map((lane) => lane.state), reply.exposure.moved.map((moved) => moved.state)) &&
      same(hashes(sources), Object.fromEntries(Object.entries(sourcesBefore).map(([path, value]) => [path, value.split(":")[0]]))));
  }

  // 8. A 390 px wide screen.
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  await openMap(id, reply.version);
  await evaluate(`document.querySelectorAll("[data-exposure-map] details").forEach((d) => { d.open = true; })`);
  await sleep(500);
  const phone = await evaluate(`(() => { const width = document.documentElement.clientWidth;
    const lanes = [...document.querySelectorAll("[data-exposure-map] [data-map-lane]")].map((lane) =>
      [...lane.querySelectorAll("[data-stage]")].map((node) => { const r = node.getBoundingClientRect();
        return { left: r.left, right: r.right, top: r.top, bottom: r.bottom }; }));
    return { scroll: document.documentElement.scrollWidth, width, lanes }; })()`);
  check("a 390 px wide screen does not scroll sideways", phone.scroll <= phone.width, JSON.stringify([phone.scroll, phone.width]));
  check("on a 390 px wide screen each lane's stages are stacked inside the screen",
    phone.lanes.length > 0 && phone.lanes.every((nodes) => nodes.every((box, index) => box.left >= 0 &&
      box.right <= phone.width + 0.5 && (index === 0 || box.top >= nodes[index - 1].bottom - 0.5))),
    JSON.stringify(phone.lanes[0]));
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

  // 9. The page's own words, the requests and the errors.
  await openMap(id, reply.version);
  const found = affirmative(chromeOf(await inner("body"), reply));
  check("the page's own words make no recommendation and state no price direction", found.length === 0, found.join(", "));
  const outside = requests.filter((row) => !row.url.startsWith(base) && !row.url.startsWith("data:") && row.url !== "about:blank");
  check("nothing outside the local server was requested", outside.length === 0, outside.map((row) => row.url).join(", "));
  check("nothing but GET was sent", requests.every((row) => row.method === "GET"));
  const real = errors.filter((error) => error.url !== `${base}/favicon.ico`);
  check("no page error", real.length === 0, JSON.stringify(real));

  if (process.env.SECOND_ORDER_SCREENSHOTS) {  // Viewport-sized segments of the map (a tall single capture can hang).
    for (const [device, width, mobile] of [["desktop", 1280, false], ["phone", 390, true]]) {
      await send("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile });
      await openMap(id, reply.version);
      await sleep(700);
      const box = await evaluate(`(() => { const r = document.querySelector("[data-exposure-map]").getBoundingClientRect();
        return { top: r.top + scrollY, height: r.height }; })()`);
      for (let part = 0; part * 860 < box.height && part < 8; part++) {
        await evaluate(`scrollTo(0, ${Math.round(box.top + part * 860)})`);
        await sleep(250);
        const shot = await Promise.race([send("Page.captureScreenshot", { format: "png" }), sleep(15000).then(() => null)]);
        if (shot) writeFileSync(join(process.env.SECOND_ORDER_SCREENSHOTS, `${device}-map-${part + 1}.png`), Buffer.from(shot.data, "base64"));
      }
    }
  }
  ws.close();
} catch (error) {
  check("the exposure map browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(300);
  try { rmSync(root, { recursive: true, force: true }); } catch { /* Windows may hold a file briefly. */ }
}
console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
process.exit(results.every(Boolean) ? 0 : 1);
