// Browser check of the hand-run pilot drill (tests/pilot_drill.py; steps in docs/pilot/fomc-pilot-drill.he.md). It
// starts the drill as the owner would, in a new practice folder in the system's temporary folder, and walks one
// SYNTHETIC case through the pages at 1280 px: the readiness card, the manual form ("draft") with the kept baseline
// imported, the preview, one freeze as fomc-2026-12-09, the drill's journal (pending), the clock moved to Friday 3 p.m.
// New York (the target not yet posted), then to 4:35 p.m., one download from the in-process fake Board server, the
// outcome import, the assessment preview and one approval, and the journal again (assessed). Across the run: only local
// requests, no page error, no sideways scrolling at 375 px, the approved pilot settings unchanged and nothing written
// outside the practice folder's own files. SECOND_ORDER_DRILL_SCREENS=<folder> also saves each step at 1280 and 375 px.
//   cd frontend; npm run build; npm run test:browser:pilot-drill
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const python = process.env.SECOND_ORDER_PYTHON ?? "python";
const screens = process.env.SECOND_ORDER_DRILL_SCREENS ? resolve(process.env.SECOND_ORDER_DRILL_SCREENS) : undefined;
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
const parent = mkdtempSync(join(tmpdir(), "second-order-drill-check-"));
const practice = join(parent, "drill");
const profile = join(parent, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const digest = (path) => createHash("sha256").update(readFileSync(path)).digest("hex");
const approved = join(repo, "content/pilot/fomc-pilot.json");
const approvedBefore = digest(approved);
const drill = (...args) => spawnSync(python, [join(repo, "tests/pilot_drill.py"), ...args, "--root", practice],
  { cwd: repo, encoding: "utf-8" });
const PUBLISHED = "2026-12-09T14:00:00-05:00";

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
  check("the drill starts in a new practice folder with a byte copy of the approved settings and its label",
    digest(join(practice, "pilot/fomc-pilot.json")) === approvedBefore &&
    JSON.parse(readFileSync(join(practice, "drill.json"), "utf-8")).label.startsWith("SYNTHETIC pilot drill"));

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
  const failures = [];
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else if (message.method === "Network.requestWillBeSent") {
      requests.push({ method: message.params.request.method, url: message.params.request.url });
    } else if (message.method === "Network.responseReceived" && message.params.response.status >= 400) {
      failures.push(`${message.params.response.status} ${message.params.response.url}`);
    } else if (message.method === "Runtime.exceptionThrown") {
      errors.push(message.params.exceptionDetails.exception?.description ?? message.params.exceptionDetails.text);
    } else if (message.method === "Log.entryAdded" && message.params.entry.level === "error" &&
               !(message.params.entry.url ?? "").endsWith("/favicon.ico")) {
      errors.push(message.params.entry.text);
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
  const text = (selector) => evaluate(`document.querySelector(${q(selector)})?.textContent ?? ""`);
  const click = (selector) => evaluate(`document.querySelector(${q(selector)})?.click()`);
  const desktop = () => send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("Log.enable");
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
  const sideways = () => evaluate(`document.documentElement.scrollWidth - document.documentElement.clientWidth`);
  const wide = {};
  /** One step at 1280 px and at 375 px, scrolled to `selector`; also records the phone width's sideways scroll. */
  const shoot = async (name, selector) => {
    for (const [label, width, height, mobile] of [["1280", 1280, 900, false], ["375", 375, 812, true]]) {
      await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile });
      await sleep(250);
      await evaluate(`document.querySelector(${q(selector)})?.scrollIntoView({ block: "start" }); true`);
      await sleep(400);
      if (mobile) wide[name] = await sideways();
      if (!screens) continue;
      mkdirSync(screens, { recursive: true });
      const shot = await send("Page.captureScreenshot", { format: "png" });
      writeFileSync(join(screens, `drill-${name}-${label}.png`), Buffer.from(shot.data, "base64"));
    }
    await desktop();
  };
  const ledger = () => drill("ledger").stdout;

  // 1. The statement night, 4:35 p.m. New York: the readiness card asks for a baseline.
  await open("/hypotheses");
  check("the Hypotheses page loads with the freeze flow and the readiness card",
    await waitFor(`!!document.querySelector(".freeze-flow") && !!document.querySelector(".hypotheses-readiness .readiness-result")`));
  const readiness = await text(".hypotheses-readiness .readiness-result");
  check("the readiness card speaks for 9 Dec 2026, the simulated New York date",
    readiness.includes("2026-12-09"), readiness.slice(0, 300));
  await shoot("1-readiness", ".hypotheses-readiness");

  // 2. Draft: the manual form, typed in, and the kept SYNTHETIC baseline imported from 2025-01-02.
  await fill("headline", "SYNTHETIC drill: FOMC statement of 9 December 2026 (practice, not a real case)");
  await fill("source_url", "https://example.com/synthetic-fomc-statement");
  await fill("published_at", PUBLISHED);
  await fill("story_id", "fomc-2026-12-09");
  await fill("summary", "SYNTHETIC drill text: a statement read as lowering the expected policy path.");
  await fill("authoring", "SYNTHETIC drill: typed by the owner's practice, no AI assistance");
  await click('input[name="freeze-primary"][value="yield:ust2y_cmt_h15"]');
  for (const observable of ["yield:ust2y_cmt_h15", "yield:ust10y_cmt_h15"]) {
    await fill(`${observable}:expected`, "down");
    await fill(`${observable}:horizon`, "5");
    await fill(`${observable}:link`, observable.includes("2y") ? "direct" : "proxy");
    await fill(`${observable}:headline_reports_move`, "no");
    await fill(`${observable}:channel`, observable.includes("2y") ? "First order: expected policy path"
      : "First order: expected policy path and term premium");
    await fill(`${observable}:rationale`, "SYNTHETIC drill: the yield prices the expected policy path.");
    await fill(`${observable}:falsifier`, "SYNTHETIC drill: an unusually large rise over the scored window.");
  }
  check("the kept SYNTHETIC package is offered for an explicit import",
    await waitFor(`document.querySelectorAll(".freeze-package-list > li").length === 1`) &&
    (await text(".freeze-package-list")).includes("2026-12-08"), await text(".freeze-package-list"));
  await click(".freeze-package-list > li button");
  check("importing it selects its snapshot as the baseline",
    await waitFor(`[...document.querySelectorAll(".freeze-snapshot-list > li")].some((li) => li.querySelector("input")?.checked)`));
  await shoot("2-draft", ".freeze-flow");

  // 3. Preview: no blocker; required session 8 Dec, score anchor 10 Dec, target 17 Dec.
  await click(".freeze-preview-button");
  await waitFor(`!!document.querySelector(".freeze-preview[data-preview]")`);
  const preview = await text(".freeze-preview");
  check("the preview has no blocker and names the 8 Dec session, the 10 Dec score anchor and the 17 Dec target",
    !(await evaluate(`!!document.querySelector(".freeze-preview .freeze-blockers li")`)) &&
    preview.includes("2026-12-08") && preview.includes("2026-12-10") && preview.includes("2026-12-17"), preview.slice(0, 400));
  await shoot("3-preview", ".freeze-preview");

  // 4. Freeze, once.
  await click(".freeze-confirm input");
  await evaluate(`(() => { const button = document.querySelector(".button-freeze"); button.click(); button.click(); })()`);
  await waitFor(`!!document.querySelector(".freeze-outcome")`);
  const frozen = await text(".freeze-outcome");
  const freezes = requests.filter((row) => row.method === "POST" && row.url.endsWith("/api/lifecycle/freezes")).length;
  check("one approval freezes it once", freezes === 1 && /frozen/i.test(frozen), `${freezes} ${frozen.slice(0, 200)}`);
  await shoot("4-frozen", ".freeze-outcome");
  const night = ledger();
  check("the drill's journal shows 2026-12-09 pending, at the simulated time",
    /2026-12-09\s+pending/.test(night) && night.includes("SYNTHETIC pilot drill") && night.includes("New York"),
    night.slice(0, 600));

  // 5. Friday 3 p.m. New York: the target, the 17th, is not posted until 4:15 p.m.
  check("the clock moves to Friday 3 p.m. New York", drill("clock", "outcome-early").stdout.includes("15:00 New York"));
  await open("/hypotheses");
  await waitFor(`!!document.querySelector('input[name="retrieval-hypothesis"]')`);
  await click('input[name="retrieval-hypothesis"]');
  await click(".retrieval-preview-button");
  await waitFor(`!!document.querySelector(".retrieval-plan")`);
  const early = await text(".retrieval-plan");
  check("before the release the plan says the 17th is awaited until 2026-12-18 16:15 New York time",
    early.includes("2026-12-17") && early.includes("2026-12-18 16:15"), early.slice(0, 500));
  await shoot("5-outcome-early", ".retrieval-plan");

  // 6. 4:35 p.m.: one download from the fake Board server.
  check("the clock moves to Friday 4:35 p.m. New York", drill("clock", "outcome").stdout.includes("16:35 New York"));
  await open("/hypotheses");
  await waitFor(`!!document.querySelector('input[name="retrieval-hypothesis"]')`);
  await click('input[name="retrieval-hypothesis"]');
  await click(".retrieval-preview-button");
  await waitFor(`!!document.querySelector(".retrieval-plan")`);
  const plan = await text(".retrieval-plan");
  check("after the release the plan offers one full-release download, sent to the fake",
    plan.includes("One: the full release package") && !plan.includes("2026-12-18 16:15"), plan.slice(0, 500));
  await click('input[name="approve-retrieval"]');
  await click(".retrieval-send");
  check("the download is saved and accepted, and nothing is imported or assessed yet",
    await waitFor(`(document.querySelector(".retrieval-flow .freeze-outcome")?.dataset.outcome ?? "") === "saved"`) &&
    (await text(".retrieval-flow .freeze-outcome")).includes("nothing was imported or assessed"));
  await shoot("6-outcome-download", ".retrieval-flow .freeze-outcome");

  // 7. The case page: import the outcome, preview, approve once.
  const hypothesis = await evaluate(`document.querySelector('label[data-hypothesis]')?.dataset.hypothesis ?? ""`);
  await open(`/hypotheses/${hypothesis}`);
  await waitFor(`!!document.querySelector(".assess-flow .freeze-package-list")`);
  await evaluate(`[...document.querySelectorAll(".assess-flow .freeze-package-list > li button")].find((button) =>
    button.closest("li").textContent.includes("to 2026-12-17"))?.click()`);
  check("the downloaded package is imported as the outcome and selected",
    await waitFor(`[...document.querySelectorAll('input[name="outcome-snapshot"]')].some((input) => input.checked)`));
  await click(".assess-preview-button");
  await waitFor(`!!document.querySelector(".assess-flow .freeze-preview")`);
  const assessPreview = await text(".assess-flow .freeze-preview");
  check("the assessment preview binds the case and shows no result before the approval",
    assessPreview.includes(hypothesis) && !/\b(supported|contradicted)\b/.test(assessPreview), assessPreview.slice(0, 400));
  await shoot("7-assessment-preview", ".assess-flow .freeze-preview");
  await click('input[name="approve-assessment"]');
  await click(".assess-flow .button-freeze");
  await waitFor(`!!document.querySelector(".assess-flow .freeze-outcome")`);
  check("one approval records the assessment and prepares its Dossier",
    (await text(".assess-flow .freeze-outcome")).includes("Evaluation saved and Dossier prepared"));
  await shoot("8-assessed", ".assess-flow .freeze-outcome");
  const after = ledger();
  check("the drill's journal shows 2026-12-09 assessed, with a 2-year label",
    /2026-12-09\s+assessed\s+\S+\s+0\s+(supported|contradicted|inconclusive|unavailable)/.test(after), after.slice(0, 700));
  if (screens) writeFileSync(join(screens, "drill-ledger.txt"), `${night}\n----\n${after}`, "utf-8");

  check("no sideways scrolling at 375 px on any step", Object.values(wide).every((px) => px <= 0), JSON.stringify(wide));
  const outside = requests.filter((row) => !row.url.startsWith(base) && !row.url.startsWith("data:") && !row.url.startsWith("about:"));
  check("only requests to the drill's own server", outside.length === 0, outside.map((row) => row.url).join());
  check("no page errors and no reply of 400 or more", errors.length === 0 && failures.length === 0,
    [...errors, ...failures].join(" | "));
  check("the approved pilot settings are unchanged", digest(approved) === approvedBefore);
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
