// Browser check of the Hypotheses lifecycle views on a phone: no sideways scrolling of the page. It serves the hand-run
// pilot drill (tests/pilot_drill.py: a SYNTHETIC case in a new practice folder in the system's temporary folder, a
// simulated clock and a fake Board server; nothing outside that folder is read or written) and measures, at 375 and
// 390 px and at 1280 px: the freeze preview, the freeze confirmation, the frozen record, the outcome-data plan, the
// assessment preview, its confirmation and the recorded assessment. In each: the page is no wider than the screen;
// anything wider sits inside its own horizontal scroll area (a table), never clipped by an overflow-x: hidden page;
// every SHA-256 value is shown whole, selectable and inside the screen; text is no smaller than on the desktop; and
// every control of the view is within the screen and on top. On the desktop the tables need no scrolling.
// SECOND_ORDER_LIFECYCLE_SCREENS=<folder> also saves each view at each width.
//   cd frontend; npm run build; npm run test:browser:lifecycle-mobile
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const python = process.env.SECOND_ORDER_PYTHON ?? "python";
const screens = process.env.SECOND_ORDER_LIFECYCLE_SCREENS ? resolve(process.env.SECOND_ORDER_LIFECYCLE_SCREENS) : undefined;
const chromePath = [process.env.SECOND_ORDER_CHROME, "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium"]
  .find((path) => path && existsSync(path));
if (!chromePath) throw new Error("Chrome was not found; set SECOND_ORDER_CHROME to its executable.");
if (!existsSync(join(repo, "frontend/dist/index.html"))) throw new Error("Build the client first: npm run build");

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => { const { port } = server.address(); server.close(() => done(port)); });
});
const parent = mkdtempSync(join(tmpdir(), "second-order-lifecycle-mobile-"));
const practice = join(parent, "drill");
const profile = join(parent, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const drill = (...args) => spawnSync(python, [join(repo, "tests/pilot_drill.py"), ...args, "--root", practice],
  { cwd: repo, encoding: "utf-8" });
const WIDTHS = [[375, 812, true], [390, 844, true], [1280, 900, false]];

/** What one view shows at width W: the page's overflow, what lies past the screen outside any scroll area, clipping
 * overflow on the page, the SHA-256 values and the controls. Measured with the page scrolled to x = 0. */
const MEASURE = (region, controls, width) => `(() => {
  const W = ${width};
  const area = document.querySelector(${JSON.stringify(region)});
  if (!area) return { missing: true };
  const name = (e) => (e.tagName + "." + [...e.classList].join(".")).slice(0, 60);
  const scroller = (e) => {
    for (let a = e.parentElement; a && a !== document.body; a = a.parentElement) {
      const style = getComputedStyle(a);
      if (/(auto|scroll)/.test(style.overflowX)) return a;
    }
    return null;
  };
  const inside = (r) => r.left >= -1 && r.right <= W + 1;
  const outside = [...document.querySelectorAll("body *")].filter((e) => {
    const r = e.getBoundingClientRect();
    if (r.width === 0 || r.right <= W + 1) return false;
    const s = scroller(e);
    return !s || !inside(s.getBoundingClientRect());
  }).map(name).slice(0, 6);
  const clipping = [document.documentElement, document.body, document.getElementById("root"), document.querySelector("main")]
    .filter(Boolean).filter((e) => /(hidden|clip)/.test(getComputedStyle(e).overflowX)).map(name);
  const scrollers = [...area.querySelectorAll("*")].filter((e) => /(auto|scroll)/.test(getComputedStyle(e).overflowX)
    && e.scrollWidth > e.clientWidth + 1).map((e) => ({ name: name(e), focusable: e.tabIndex >= 0,
      labelled: !!(e.getAttribute("aria-label") || e.getAttribute("aria-labelledby")), inside: inside(e.getBoundingClientRect()) }));
  const hashes = [];
  const walker = document.createTreeWalker(area, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    for (const found of node.textContent.matchAll(/[0-9a-f]{64}/g)) {
      const holder = node.parentElement;
      const range = document.createRange();
      range.setStart(node, found.index);
      range.setEnd(node, found.index + 64);
      const boxes = [...range.getClientRects()];
      hashes.push({ holder: name(holder), select: getComputedStyle(holder).userSelect !== "none",
        ellipsis: getComputedStyle(holder).textOverflow === "ellipsis",
        shown: boxes.length > 0 && boxes.every((r) => inside(r) || (scroller(holder) && inside(scroller(holder).getBoundingClientRect()))),
        font: parseFloat(getComputedStyle(holder).fontSize) });
    }
  }
  const sizes = {};
  for (const selector of [".ledger dd", ".freeze-legs td", ".freeze-legs th", ".freeze-origin code", ".freeze-note"]) {
    const e = area.querySelector(selector);
    if (e) sizes[selector] = parseFloat(getComputedStyle(e).fontSize);
  }
  const reach = [...document.querySelectorAll(${JSON.stringify(controls)})].filter((e) => e.getClientRects().length > 0)
    .map((e) => {
      const r = e.getBoundingClientRect();
      window.scrollTo(0, r.top + scrollY - innerHeight / 2);
      const now = e.getBoundingClientRect();
      const top = document.elementFromPoint(now.left + now.width / 2, now.top + now.height / 2);
      return { name: name(e), inside: inside(now), onTop: !!top && (top === e || e.contains(top) || top.contains(e)
        || (e.labels && [...e.labels].some((label) => label.contains(top)))) };
    });
  return { page: document.documentElement.scrollWidth - W, outside, clipping, scrollers, hashes, sizes, reach };
})()`;

try {
  const port = await freePort();
  let control = await freePort();
  while (control === port) control = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(python, [join(repo, "tests/pilot_drill.py"), "start", "--root", practice, "--port", String(port),
    "--control-port", String(control)], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  let up = false;
  for (let i = 0; i < 600 && !up; i++) {  // up to two minutes: a loaded machine starts it slowly
    try { up = (await fetch(`${base}/api/lifecycle/readiness`)).ok; } catch { /* starting */ }
    if (!up) await sleep(200);
  }
  if (!up) throw new Error("The drill's server did not start.");

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
  const errors = [];
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else if (message.method === "Runtime.exceptionThrown") {
      errors.push(message.params.exceptionDetails.exception?.description ?? message.params.exceptionDetails.text);
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
  const click = (selector) => evaluate(`document.querySelector(${q(selector)})?.click()`);
  const desktop = () => send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Page.enable"); await send("Runtime.enable");
  await desktop();
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete'");
  };
  const fill = (name, value) => evaluate(`(() => {
    const field = document.querySelector('[name="${name}"]');
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(field), "value").set;
    setter.call(field, ${q(value)});
    field.dispatchEvent(new Event(field.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
    return true;
  })()`);

  /** One view at each width: the measures above, checked; the desktop font sizes are the reference. */
  const views = [];
  const view = async (label, region, controls) => {
    const seen = {};
    for (const [width, height, mobile] of [...WIDTHS].reverse()) {
      await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile });
      await sleep(300);
      await evaluate(`(() => { const e = document.querySelector(${q(region)});
        if (e) window.scrollTo(0, e.getBoundingClientRect().top + scrollY - 12); return true; })()`);
      await sleep(900);  // let a resized page repaint before it is captured and measured
      const capture = async (suffix) => {
        if (!screens) return;
        mkdirSync(screens, { recursive: true });
        const shot = await send("Page.captureScreenshot", { format: "png" });
        writeFileSync(join(screens, `lifecycle-${label}${suffix}-${width}.png`), Buffer.from(shot.data, "base64"));
      };
      await capture("");
      if (await evaluate(`(() => { const t = document.querySelector(${q(region)})?.querySelector(".lifecycle-table-area");
        if (t) window.scrollTo(0, t.getBoundingClientRect().top + scrollY - 160); return !!t; })()`)) {
        await sleep(400);
        await capture("-table");
      }
      seen[width] = await evaluate(MEASURE(region, controls, width));  // last: it scrolls to each control
    }
    await desktop();
    views.push(label);
    for (const [width] of WIDTHS) {
      const m = seen[width];
      if (m.missing) { check(`${label} at ${width} px: the view is shown`, false, region); continue; }
      check(`${label} at ${width} px: the page is no wider than the screen, and nothing lies past it outside a scroll area`,
        m.page <= 0 && m.outside.length === 0, `${m.page} px; ${m.outside.join(" | ")}`);
      check(`${label} at ${width} px: no clipping overflow on the page, and each scroll area is in the screen, focusable `
        + "and named", m.clipping.length === 0 && m.scrollers.every((s) => s.inside && s.focusable && s.labelled)
        && (width > 720 ? m.scrollers.length === 0 : true), JSON.stringify({ clipping: m.clipping, scrollers: m.scrollers }));
      check(`${label} at ${width} px: every SHA-256 value is whole, selectable and on screen`,
        m.hashes.every((h) => h.shown && h.select && !h.ellipsis && h.font >= 11), JSON.stringify(m.hashes.filter((h) =>
          !h.shown || !h.select || h.ellipsis || h.font < 11)));
      const desk = seen[1280].sizes;
      check(`${label} at ${width} px: text is no smaller than on the desktop`,
        Object.entries(m.sizes).every(([selector, size]) => size >= (desk[selector] ?? 0)), JSON.stringify({ desk, now: m.sizes }));
      check(`${label} at ${width} px: every control is within the screen and on top`,
        m.reach.every((c) => c.inside && c.onTop), JSON.stringify(m.reach.filter((c) => !c.inside || !c.onTop)));
    }
  };

  // The night: the manual form, the kept SYNTHETIC baseline, the preview and one freeze.
  await open("/hypotheses");
  await waitFor(`!!document.querySelector(".freeze-flow")`);
  await fill("headline", "SYNTHETIC check: FOMC statement of 9 December 2026 (practice, not a real case)");
  await fill("source_url", "https://example.com/synthetic-fomc-statement");
  await fill("published_at", "2026-12-09T14:00:00-05:00");
  await fill("story_id", "fomc-2026-12-09");
  await fill("summary", "SYNTHETIC check text: a statement read as lowering the expected policy path.");
  await fill("authoring", "SYNTHETIC: typed by the lifecycle phone check, no AI assistance");
  await click('input[name="freeze-primary"][value="yield:ust2y_cmt_h15"]');
  for (const observable of ["yield:ust2y_cmt_h15", "yield:ust10y_cmt_h15"]) {
    await fill(`${observable}:expected`, "down");
    await fill(`${observable}:horizon`, "5");
    await fill(`${observable}:link`, observable.includes("2y") ? "direct" : "proxy");
    await fill(`${observable}:headline_reports_move`, "no");
    await fill(`${observable}:channel`, "First order: expected policy path");
    await fill(`${observable}:rationale`, "SYNTHETIC: the yield prices the expected policy path.");
    await fill(`${observable}:falsifier`, "SYNTHETIC: an unusually large rise over the scored window.");
  }
  await waitFor(`document.querySelectorAll(".freeze-package-list > li").length === 1`);
  await click(".freeze-package-list > li button");
  await waitFor(`[...document.querySelectorAll(".freeze-snapshot-list > li")].some((li) => li.querySelector("input")?.checked)`);
  await click(".freeze-preview-button");
  check("the freeze preview is shown", await waitFor(`!!document.querySelector(".freeze-preview[data-preview]")`));
  await view("freeze-preview", ".freeze-preview", ".freeze-preview-button, .freeze-confirm input, .button-freeze");
  await click(".freeze-confirm input");
  await click(".button-freeze");
  check("the freeze is confirmed", await waitFor(`!!document.querySelector(".freeze-outcome")`));
  await view("freeze-confirmed", ".freeze-flow", ".freeze-outcome a, .freeze-outcome button");
  const hypothesis = await evaluate(`[...document.querySelectorAll(".freeze-outcome a")].map((a) => a.getAttribute("href"))
    .find((href) => /^\\/hypotheses\\/[0-9a-f]{64}$/.test(href ?? ""))?.split("/").pop() ?? ""`);
  check("the confirmation links to the frozen record", /^[0-9a-f]{64}$/.test(hypothesis), hypothesis);
  await open(`/hypotheses/${hypothesis}`);
  await waitFor(`!!document.querySelector(".assess-flow")`);
  await view("frozen-record", "main", "main a, main button, main input");

  // The outcome day: the plan, one download from the fake, the import, the assessment preview and one approval.
  check("the drill's clock moves to Friday 4:35 p.m. New York", drill("clock", "outcome").stdout.includes("16:35 New York"));
  await open("/hypotheses");
  await waitFor(`!!document.querySelector('input[name="retrieval-hypothesis"]')`);
  await click('input[name="retrieval-hypothesis"]');
  await click(".retrieval-preview-button");
  await waitFor(`!!document.querySelector(".retrieval-plan")`);
  await view("outcome-plan", ".retrieval-flow", ".retrieval-flow input, .retrieval-flow button");
  await click('input[name="approve-retrieval"]');
  await click(".retrieval-send");
  check("the outcome package is saved",
    await waitFor(`(document.querySelector(".retrieval-flow .freeze-outcome")?.dataset.outcome ?? "") === "saved"`));
  await open(`/hypotheses/${hypothesis}`);
  await waitFor(`!!document.querySelector(".assess-flow .freeze-package-list")`);
  await evaluate(`[...document.querySelectorAll(".assess-flow .freeze-package-list > li button")].find((button) =>
    button.closest("li").textContent.includes("to 2026-12-17"))?.click()`);
  await waitFor(`[...document.querySelectorAll('input[name="outcome-snapshot"]')].some((input) => input.checked)`);
  await click(".assess-preview-button");
  check("the assessment preview is shown", await waitFor(`!!document.querySelector(".assess-flow .freeze-preview")`));
  await view("assessment-preview", ".assess-flow", ".assess-preview-button, input[name=\"approve-assessment\"], .assess-flow .button-freeze");
  await click('input[name="approve-assessment"]');
  await click(".assess-flow .button-freeze");
  check("the assessment is recorded", await waitFor(`!!document.querySelector(".assess-flow .freeze-outcome")`));
  await view("assessment-confirmed", ".assess-flow", ".assess-flow .freeze-outcome a");
  const recorded = await evaluate(`[...document.querySelectorAll(".assess-flow .freeze-outcome a")]
    .find((a) => a.textContent.includes("recorded assessment"))?.getAttribute("href") ?? ""`);
  await open(recorded);
  check("the recorded assessment opens", await waitFor(`!!document.querySelector(".assess-recorded-legs")`));
  await view("assessment-record", "main", "main a, main button");

  check("all seven views were measured", views.length === 7, views.join());
  check("no page errors", errors.length === 0, errors.join(" | "));
} catch (error) {
  check("the check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(500);
  const removed = drill("remove");
  if (removed.status !== 0) console.log(`NOTE  the practice folder was not removed: ${removed.stderr}`);
  try { rmSync(parent, { recursive: true, force: true }); } catch { /* Windows may hold a file briefly */ }
  const failed = results.filter((ok) => !ok).length;
  console.log(`\n${results.length - failed}/${results.length} checks passed`);
  process.exitCode = failed ? 1 : 0;
}
