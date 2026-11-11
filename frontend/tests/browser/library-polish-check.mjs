// Browser check for browsing the case library on wide and narrow screens: browsing starts on the first screen with the
// collection's labels in view and its longer description behind a keyboard-operable disclosure; no sideways scrolling
// with long titles and wrapped filter labels; 44px controls and visible focus on a phone; one way back from an empty
// result plus one-click ways to widen it (replacing the address, as every filter control does); loading, read-error
// (with retry), empty and unknown-sector states; and no request other than local reads while doing any of this
// (opening the disclosure, filtering, resetting and retrying never prepare or send an analysis). The functional
// filter, count, order and address checks are library-check.mjs.
// The server is tests/review_browser_server.py over an empty temporary folder: no runtime records, keys or providers.
//
//   cd frontend; npm run build; node tests/browser/library-polish-check.mjs
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
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

const LABELS = ["Retrospective", "AI-assisted editorial illustration", "Not human-reviewed",
                "Never scored · not research evidence"];
const WIDTHS = [[1440, 900], [768, 1024], [390, 844]];
const PAGES = ["/library", "/library?category=industrial-production&sector=energy", "/library?q=unicorn&category=inflation",
               "/library?sector=astrology", "/library?category=export-controls&sector=banking-credit"];

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const root = mkdtempSync(join(tmpdir(), "second-order-library-polish-"));
const served = join(root, "served");
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};

try {
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  children.push(spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    "--market-context", "committed"], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] }));
  let started = false;
  for (let i = 0; i < 150 && !started; i++) {
    try { started = (await fetch(`${base}/api/case-library`)).ok; } catch { await sleep(200); }
  }
  if (!started) throw new Error("The review server did not start.");
  const library = await (await fetch(`${base}/api/case-library`)).json();

  children.push(spawn(chromePath, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
    "--no-first-run", "--disable-gpu", "about:blank"], { stdio: "ignore" }));
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
  let libraryReply = "pass";  // How the next reads of /api/case-library are answered: "pass", "fail" or "hold".
  const held = [];
  const send = (method, params = {}) => new Promise((done, fail) => {
    const id = ++counter;
    pending.set(id, (message) => message.error ? fail(new Error(message.error.message)) : done(message.result));
    ws.send(JSON.stringify({ id, method, params }));
  });
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else if (message.method === "Network.requestWillBeSent") {
      requests.push({ method: message.params.request.method, url: message.params.request.url });
    } else if (message.method === "Fetch.requestPaused") {
      const { requestId } = message.params;
      if (libraryReply === "fail") {
        send("Fetch.fulfillRequest", { requestId, responseCode: 503,
          responseHeaders: [{ name: "content-type", value: "application/json" }],
          body: Buffer.from(JSON.stringify({ detail: "Temporarily unavailable" })).toString("base64") });
      } else if (libraryReply === "hold") {
        held.push(requestId);
      } else {
        send("Fetch.continueRequest", { requestId });
      }
    }
  });
  const evaluate = async (expression) =>
    (await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })).result.value;
  const waitFor = async (expression, timeout = 10000) => {
    for (const start = Date.now(); Date.now() - start < timeout; await sleep(80)) {
      if (await evaluate(expression)) return true;
    }
    return false;
  };
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Fetch.enable", { patterns: [{ urlPattern: `${base}/api/case-library` }] });
  const viewport = (width, height) =>
    send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 700 });
  const shown = `document.querySelectorAll(".library-index .library-entry").length > 0 || !!document.querySelector(".library-empty")`;
  const open = async (path, ready = shown) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete'");
    if (ready) await waitFor(ready);
    await evaluate("document.fonts.ready.then(() => true)");
    await sleep(700);  // Let the entrance animation settle before measuring.
  };
  const press = async (key, code, keyCode, typed, modifiers = 0) => {
    await send("Input.dispatchKeyEvent", { type: "keyDown", key, code, windowsVirtualKeyCode: keyCode, text: typed, modifiers });
    await send("Input.dispatchKeyEvent", { type: "keyUp", key, code, windowsVirtualKeyCode: keyCode, modifiers });
  };
  const tab = () => press("Tab", "Tab", 9);
  /** What has keyboard focus, and whether it draws a visible indicator (an outline or a ring). */
  const focus = () => evaluate(`(() => {
    const e = document.activeElement, s = getComputedStyle(e);
    const ring = (s.outlineStyle !== "none" && parseFloat(s.outlineWidth) >= 2) || (s.boxShadow && s.boxShadow !== "none");
    return { tag: e.tagName, text: (e.textContent || e.id || "").trim().replace(/\\s+/g, " ").slice(0, 60), id: e.id, ring,
             inLibrary: !!e.closest(".library") };
  })()`);
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

  // 1. On every width the collection's labels are in view and browsing starts on the first screen; the longer
  //    description and selection rules are on the page, behind a disclosure that starts closed.
  for (const [width, height] of WIDTHS) {
    await viewport(width, height);
    await open("/library");
    const layout = await evaluate(`(() => {
      const visible = (e) => !!e && e.getClientRects().length > 0 && !e.closest("details:not([open])");
      const labels = [...document.querySelectorAll(".library-header .library-labels li")].filter(visible).map((e) => e.textContent);
      const search = document.querySelector("#library-search").getBoundingClientRect();
      const about = [...document.querySelectorAll(".library-header details")];
      return { labels, searchBottom: search.bottom, inner: innerHeight, closed: about.length === 1 && !about[0].open,
               aboutText: about[0]?.textContent ?? "" };
    })()`);
    check(`${width}px: the retrospective, AI-assisted, not-human-reviewed and never-scored labels are in plain view`,
      LABELS.every((label) => layout.labels.includes(label)), JSON.stringify(layout.labels));
    check(`${width}px: the search field is on the first screen (${height}px tall), above the long description`,
      layout.searchBottom <= layout.inner, `${layout.searchBottom} > ${layout.inner}`);
    check(`${width}px: the full introduction and selection rules are on the page, in a disclosure that starts closed`,
      layout.closed && layout.aboutText.includes(library.introduction) && layout.aboutText.includes(library.selection));
    for (const path of PAGES) {
      if (path !== "/library") await open(path);
      const wide = await evaluate(`(() => ({ scroll: document.documentElement.scrollWidth, inner: innerWidth,
        wide: [...document.querySelectorAll("body *")].filter((e) => e.getBoundingClientRect().right > innerWidth + 1)
          .map((e) => e.tagName + "." + e.className).slice(0, 3) }))()`);
      check(`${width}px ${path}: no sideways scrolling`, wide.scroll <= wide.inner && wide.wide.length === 0, JSON.stringify(wide));
    }
  }

  // 2. A phone: every browsing control, sector link and the disclosure is at least 44px tall; case titles at least
  //    24px; text that wraps (long titles, filter labels) stays inside its control.
  await viewport(390, 844);
  for (const path of ["/library", "/library?category=industrial-production&sector=energy",
                      "/library?category=export-controls&sector=banking-credit"]) {
    await open(path);
    await evaluate(`document.querySelectorAll(".library details").forEach((d) => { d.open = true; })`);
    const targets = await evaluate(`(() => {
      const controls = [...document.querySelectorAll(".library-header summary, .library-index input, .library-index button, .library-index summary, .library-list .library-sector-chips a")]
        .filter((e) => e.getClientRects().length > 0);
      const short = controls.filter((e) => e.getBoundingClientRect().height < 44).map((e) => (e.textContent || e.id).trim().slice(0, 30) + ":" + Math.round(e.getBoundingClientRect().height));
      const titles = [...document.querySelectorAll(".library-list .library-entry-title")].map((e) => e.getBoundingClientRect().height);
      const spill = controls.filter((e) => e.scrollWidth > e.clientWidth + 1).map((e) => e.textContent.trim().slice(0, 30));
      return { count: controls.length, short, shortestTitle: titles.length ? Math.min(...titles) : 24, spill };
    })()`);
    check(`phone ${path}: ${targets.count} controls at least 44px tall, titles at least 24px, no label spilling out`,
      targets.count > 0 && targets.short.length === 0 && targets.shortestTitle >= 24 && targets.spill.length === 0,
      JSON.stringify(targets));
  }

  // 3. Keyboard only: the disclosure opens and closes with Enter and Space, shows focus, and changes nothing else;
  //    the next Tab goes to the search, then the topic controls, each with a visible focus indicator.
  await viewport(1440, 900);
  await open("/library");
  const before = requests.length;
  await evaluate(`document.querySelector(".library h1").setAttribute("tabindex", "-1"); document.querySelector(".library h1").focus()`);
  let summary = null;
  for (let i = 0; i < 12 && !summary; i++) {
    await tab();
    const now = await focus();
    if (now.tag === "SUMMARY" && now.inLibrary) summary = now;
  }
  check("the disclosure is reached with Tab after the heading and shows a visible focus indicator", !!summary?.ring,
    JSON.stringify(summary));
  await press("Enter", "Enter", 13, "\r");
  const opened = await waitFor(`document.querySelector(".library-header details")?.open === true`);
  const readable = await evaluate(`(() => { const p = [...document.querySelectorAll(".library-header details p")];
    return p.length > 0 && p.every((e) => e.getBoundingClientRect().height > 0); })()`);
  await press(" ", "Space", 32, " ");
  const closed = await waitFor(`document.querySelector(".library-header details")?.open === false`);
  check("Enter opens the description and Space closes it again", opened && readable && closed);
  check("opening and closing it leaves the address alone and makes no request",
    (await evaluate("location.pathname + location.search")) === "/library" && requests.length === before,
    JSON.stringify(requests.slice(before)));
  const path = [];
  for (let i = 0; i < 3; i++) {
    await tab();
    path.push(await focus());
  }
  check("Tab then reaches the search and the topic controls in order, each with a visible focus indicator",
    path[0].id === "library-search" && path[1].text.startsWith("All") && path[2].text.startsWith("Monetary policy") &&
    path.every((item) => item.ring), JSON.stringify(path));
  await press("Enter", "Enter", 13, "\r");
  await waitFor(`location.search === "?category=monetary-policy"`);
  for (let i = 0; i < 8; i++) await tab();
  const sector = await focus();
  check("the sector controls follow the topic controls, and focus stays visible on a pressed control",
    sector.text.startsWith("All sectors") && sector.ring, JSON.stringify(sector));

  // 4. An empty result: one way back to everything, and one click to widen it by dropping the topic or the sector.
  await open("/library?category=export-controls&sector=banking-credit");
  const empty = await evaluate(`(() => ({
    resets: [...document.querySelectorAll(".library-index .library-reset")].filter((e) => e.getClientRects().length > 0).map((e) => e.textContent),
    widen: [...document.querySelectorAll(".library-empty button:not(.library-reset)")].map((e) => e.textContent),
    text: document.querySelector(".library-empty")?.textContent ?? "" }))()`);
  check("an empty result offers one way back to every case, not two",
    same(empty.resets, ["Show all cases"]), JSON.stringify(empty.resets));
  check("it also offers to show the sector's cases in all topics and the topic's cases in all sectors",
    empty.widen.length === 2 && empty.text.includes("3 cases match under Banking & credit in all topics") &&
    empty.text.includes("3 cases match in Export controls across all sectors"), JSON.stringify(empty));
  await evaluate(`[...document.querySelectorAll(".library-empty button")].find((b) => /all topics/i.test(b.textContent))?.click()`);
  check("widening to all topics keeps the sector and shows its cases",
    await waitFor(`location.search === "?sector=banking-credit" && document.querySelectorAll(".library-index .library-entry").length === 3`));
  // Like every filter control, widening replaces the address rather than adding a history entry.
  await open("/library?category=export-controls&sector=banking-credit");
  await evaluate(`[...document.querySelectorAll(".library-empty button")].find((b) => /all sectors/i.test(b.textContent))?.click()`);
  check("widening to all sectors keeps the topic and shows its cases",
    await waitFor(`location.search === "?category=export-controls" && document.querySelectorAll(".library-index .library-entry").length === 3`));

  // 5. An unknown sector is stated as a note, and every case is shown.
  await open("/library?sector=astrology");
  const note = await evaluate(`(() => { const n = document.querySelector(".library-sector-note");
    return { text: n?.textContent ?? "", role: n?.getAttribute("role"), visible: !!n && n.getClientRects().length > 0,
             cases: document.querySelectorAll(".library-index .library-entry").length }; })()`);
  check("an unknown sector in the address is stated as a note, with every case shown",
    note.visible && note.role === "note" && note.text.includes("“astrology”") && note.cases === library.cases.length,
    JSON.stringify(note));

  // 6. Loading, a read failure and a retry; a filtered address survives all three.
  await viewport(390, 844);
  libraryReply = "hold";
  await open("/library?sector=energy", null);
  const loading = await waitFor(`document.querySelector(".library-index [role=status]")?.textContent.includes("Loading the case library")`);
  check("while the library is read, the page says so", loading);
  libraryReply = "fail";
  for (const requestId of held.splice(0)) await send("Fetch.failRequest", { requestId, errorReason: "Failed" });
  await open("/library?sector=energy", `!!document.querySelector(".library-index [role=alert]")`);
  const failed = await evaluate(`(() => { const a = document.querySelector(".library-index [role=alert]");
    const b = a?.querySelector("button"); return { text: a?.textContent ?? "", button: b?.textContent ?? "",
    tall: b ? b.getBoundingClientRect().height >= 44 : false, entries: document.querySelectorAll(".library-entry").length }; })()`);
  check("a read failure says so, shows no partial list and offers a 44px Try again",
    failed.text.includes("The case library could not be read") && failed.button === "Try again" && failed.tall &&
    failed.entries === 0, JSON.stringify(failed));
  libraryReply = "pass";
  const beforeRetry = requests.length;
  await evaluate(`document.querySelector(".library-index [role=alert] button").click()`);
  const retried = await waitFor(`document.querySelectorAll(".library-index .library-entry").length === 5 &&
    location.search === "?sector=energy"`);
  const retryRequests = requests.slice(beforeRetry);
  check("Try again reads the library once more, with a plain GET, and keeps the sector from the address",
    retried && retryRequests.length >= 1 && retryRequests.every((r) => r.method === "GET" && r.url === `${base}/api/case-library`),
    JSON.stringify(retryRequests));
  await send("Page.reload", { ignoreCache: true });
  check("a reload after the retry still shows the same sector",
    await waitFor(`document.querySelectorAll(".library-index .library-entry").length === 5 && location.search === "?sector=energy"`));

  // 7. Nothing here writes, prepares or sends anything, or reaches outside the local server.
  const writes = requests.filter((r) => r.method !== "GET");
  const outside = requests.filter((r) => !r.url.startsWith(base) && !r.url.startsWith("data:") && r.url !== "about:blank");
  const apis = [...new Set(requests.filter((r) => r.url.startsWith(`${base}/api/`)).map((r) => new URL(r.url).pathname))];
  check("browsing made only GET reads, none outside the local server and none of an analysis",
    writes.length === 0 && outside.length === 0 && apis.every((p) => !/analys|intake|attempt|paid|draft|freeze/.test(p)),
    JSON.stringify({ writes, outside, apis }));
  ws.close();
} catch (error) {
  check("the library polish check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(500);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
