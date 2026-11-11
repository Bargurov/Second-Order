// Browser check of the interface freeze (Hypotheses): a manual H.15 hypothesis and a reviewed model draft are
// frozen through the page, each with one explicit approval, against tests/review_browser_server.py serving a new,
// empty folder (--lifecycle keeps two SYNTHETIC validated release packages; --simulated-provider answers the Tracker's
// paid route with a fake; the store is store/research.db inside the folder). It checks:
// - loading pages only reads (the folder is unchanged, no store is created until an explicit import);
// - freshness policy B: a stale baseline is refused, with the missing session named, and Freeze stays disabled;
// - editing after a preview voids it; a double click sends one approval; a lost reply is resolved by reading the
//   outcome, never by sending the approval again;
// - the reviewed H.15 model draft (and not the mock draft) can be frozen, and the review panel shows its H.15 IDs;
//   afterwards the draft's panel and My analyses show the freeze, read from its freeze record, while the draft's own
//   record is unchanged and a later review is named apart from the one used at freeze;
// - the frozen record reopens after a reload and after a server restart, as Frozen · Not evaluated with its baseline,
//   no vintage, freshness, scoring window and classification;
// - narrow screens, page errors, and no request outside the local server.
//
//   cd frontend; npm run build; npm run test:browser:freeze
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

const PUBLISHED = "2026-09-15T14:00:00-04:00";  // Tuesday; the last session before it is Monday, 14 September.
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => { const { port } = server.address(); server.close(() => done(port)); });
});
const root = mkdtempSync(join(tmpdir(), "second-order-freeze-check-"));
const served = join(root, "served");
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
/** Every file below the served folder with its hash, to show that reads write nothing. */
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
  for (let i = 0; i < 200; i++) {
    try { if ((await fetch(`http://127.0.0.1:${port}/api/lifecycle`)).ok) return server; } catch { /* starting */ }
    await sleep(200);
  }
  throw new Error("The review server did not start.");
}

try {
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  let server = await startServer(port, ["--lifecycle", "--simulated-provider"]);

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
  let dropFreezeReply = false;
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
    } else if (message.method === "Fetch.requestPaused") {
      // The server has answered; the page never receives that answer: a lost reply.
      const id = ++counter;
      ws.send(JSON.stringify({ id, method: dropFreezeReply ? "Fetch.failRequest" : "Fetch.continueRequest",
                               params: dropFreezeReply ? { requestId: message.params.requestId, errorReason: "ConnectionClosed" }
                                                       : { requestId: message.params.requestId } }));
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
  const waitFor = async (expression, timeout = 15000) => {
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
  /** Set a field as typing would, so React sees the change. */
  const fill = (name, value) => evaluate(`(() => {
    const field = document.querySelector('[name="${name}"]');
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(field), "value").set;
    setter.call(field, ${JSON.stringify(value)});
    field.dispatchEvent(new Event(field.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
    return true;
  })()`);
  const fillManual = async (variant) => {
    await fill("headline", `Synthetic payrolls release (${variant})`);
    await fill("source_url", "https://example.com/release");
    await fill("published_at", PUBLISHED);
    await fill("story_id", `browser-${variant}`);
    await fill("summary", `A synthetic weaker payrolls print (${variant}) may lower Treasury yields.`);
    await fill("authoring", "Written by the browser check without AI assistance");
    await click('input[name="freeze-primary"][value="yield:ust2y_cmt_h15"]');
    for (const observable of ["yield:ust2y_cmt_h15", "yield:ust10y_cmt_h15"]) {
      await fill(`${observable}:expected`, "down");
      await fill(`${observable}:horizon`, "5");
      await fill(`${observable}:link`, observable.includes("2y") ? "direct" : "proxy");
      await fill(`${observable}:headline_reports_move`, "no");
      await fill(`${observable}:channel`, "Expected policy path");
      await fill(`${observable}:rationale`, "Tied to the expected policy path.");
      await fill(`${observable}:falsifier`, "An unusually large rise over the scored window.");
    }
  };
  const freezeRequests = () => requests.filter((row) => row.method === "POST" && row.url.endsWith("/api/lifecycle/freezes")).length;
  const previewShown = () => waitFor(`!!document.querySelector(".freeze-preview[data-preview]")`);
  const importPackage = async (through) => {
    const id = await evaluate(`[...document.querySelectorAll(".freeze-package-list > li")]
      .find((li) => li.textContent.includes("to ${through}"))?.dataset.package ?? ""`);
    await click(`.freeze-package-list > li[data-package="${id}"] button`);
    return waitFor(`[...document.querySelectorAll(".freeze-snapshot-list > li")].some((li) =>
      li.textContent.includes("${through}") && li.querySelector("input").checked)`);
  };

  // 1. Loading the page only reads: no store exists until an explicit import.
  let before = tree(served);
  await open("/hypotheses");
  check("the Hypotheses page loads from the top bar, with nothing frozen and no store yet",
    await waitFor(`!!document.querySelector(".freeze-flow")`) &&
    (await text('.site-nav a[aria-current="page"]')) === "Hypotheses" &&
    (await text(".hypotheses-list")).includes("No hypothesis is frozen") &&
    (await text(".freeze-step")).length > 0);
  check("loading the page and its reads wrote nothing and created no store", same(tree(served), before) &&
    !existsSync(join(served, "store", "research.db")));

  // 2. A manual hypothesis on a stale baseline: freshness policy B refuses it.
  await fillManual("first");
  check("both kept packages are listed for an explicit import",
    await waitFor(`document.querySelectorAll(".freeze-package-list > li").length === 2`));
  check("importing the stale package creates the store and selects its snapshot", await importPackage("2026-09-11") &&
    existsSync(join(served, "store", "research.db")));
  await click(".freeze-preview-button");
  check("the stale baseline's preview names the missing session and cannot be frozen", await previewShown() &&
    (await text(".freeze-blockers")).includes("the last expected session before the publication date 2026-09-15 is 2026-09-14") &&
    await evaluate(`document.querySelector(".button-freeze").disabled && document.querySelector(".freeze-confirm input").disabled`));

  // 3. The fresh package: preview, edit (which voids it), preview again, approve with a double click.
  check("importing the fresh package selects its snapshot", await importPackage("2026-09-14"));
  check("changing the baseline voided the earlier preview", !(await evaluate(`!!document.querySelector(".freeze-preview")`)));
  await click(".freeze-preview-button");
  await previewShown();
  const preview = await evaluate(`document.querySelector(".freeze-preview").textContent`);
  check("the preview shows the effective content, the Board as provider, no vintage, freshness B, the scoring window "
    + "and the showcase classification",
    preview.includes("Federal Reserve Board H.15 release package") && preview.includes("None: no historical vintage") &&
    preview.includes("2026-09-14") && preview.includes("freshness-b-1") && preview.includes("expected scoring anchor") &&
    preview.includes("excluded from research summaries and rates") && preview.includes("board-h15:RIFLGFCY02_N.B") &&
    preview.includes("2-year Treasury yield (Board H.15)"), preview.slice(0, 300));
  if (process.env.SECOND_ORDER_SCREENSHOTS) {
    await evaluate(`document.querySelector(".freeze-preview").scrollIntoView()`);
    await sleep(500);
    const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    writeFileSync(join(process.env.SECOND_ORDER_SCREENSHOTS, "preview.png"), Buffer.from(shot.data, "base64"));
  }
  await fill("summary", "An edited summary: the previewed content changed.");
  check("editing the hypothesis after the preview voids the preview and the approval",
    await waitFor(`!document.querySelector(".freeze-preview")`) &&
    await evaluate(`document.querySelector(".button-freeze").disabled`));
  await click(".freeze-preview-button");
  await previewShown();
  await click(".freeze-confirm input");
  before = freezeRequests();
  await evaluate(`(() => { const button = document.querySelector(".button-freeze"); button.click(); button.click(); })()`);
  check("a double click sends one approval and the page shows Frozen · Not evaluated",
    await waitFor(`!!document.querySelector(".freeze-outcome.is-frozen")`) && freezeRequests() - before === 1 &&
    (await text(".freeze-outcome.is-frozen")).includes("Frozen · Not evaluated") &&
    (await text(".freeze-outcome.is-frozen")).includes("Nothing was evaluated or prepared"));
  const firstHref = await evaluate(`document.querySelector(".freeze-outcome.is-frozen a").getAttribute("href")`);
  check("the frozen list shows the new hypothesis", await waitFor(`document.querySelectorAll(".frozen-list > li").length === 1`));

  // 4. A lost reply: the server freezes, the page never hears; it reads the outcome instead of sending again.
  await open("/hypotheses");
  await waitFor(`!!document.querySelector(".freeze-flow")`);
  await fillManual("second");
  await waitFor(`document.querySelectorAll(".freeze-snapshot-list > li").length === 2`);
  await evaluate(`[...document.querySelectorAll(".freeze-snapshot-list > li")].find((li) => li.textContent.includes("2026-09-14"))
    .querySelector("input").click()`);
  await click(".freeze-preview-button");
  await previewShown();
  await click(".freeze-confirm input");
  await send("Fetch.enable", { patterns: [{ urlPattern: "*/api/lifecycle/freezes", requestStage: "Response" }] });
  dropFreezeReply = true;
  before = freezeRequests();
  await click(".button-freeze");
  const unconfirmed = await waitFor(`!!document.querySelector(".freeze-outcome.is-unconfirmed")`);
  dropFreezeReply = false;
  await send("Fetch.disable");
  check("a lost reply is shown as unconfirmed, and the approval is not sent again",
    unconfirmed && (await text(".freeze-outcome.is-unconfirmed")).includes("not sent again") && freezeRequests() - before === 1);
  await click(".freeze-outcome.is-unconfirmed button");
  check("checking the outcome reads that this approval froze the hypothesis",
    await waitFor(`(document.querySelector(".freeze-outcome")?.textContent ?? "").includes("This approval froze the hypothesis")`) &&
    freezeRequests() - before === 1 && await waitFor(`document.querySelectorAll(".frozen-list > li").length === 2`));

  // 5. The model path: a paid H.15 draft reviewed as Human-reviewed is eligible; the mock draft is not.
  const post = (path, body, header) => evaluate(`fetch(${JSON.stringify(path)}, { method: "POST",
    headers: { "Content-Type": "application/json", "${header}": "1" }, body: ${JSON.stringify(JSON.stringify(body))} })
    .then(async (response) => ({ status: response.status, body: await response.json() }))`);
  const capture = async (headline) => (await post("/api/intake", { headline, source_url: "https://example.com/statement",
    published_at: PUBLISHED, source_text: `Synthetic statement for ${headline}.` }, "X-Second-Order-Intake")).body;
  const paidCapture = await capture("Browser check paid draft");
  const paid = await post(`/api/intake/${paidCapture.capture_id}/paid-drafts`, { request_sha256: paidCapture.request_sha256,
    approve_paid_request: true, estimated_max_usd: paidCapture.cost_estimate.estimated_real_run_if_output_reaches_max_usd },
    "X-Second-Order-Intake");
  const mockCapture = await capture("Browser check mock draft");
  const mock = await post(`/api/intake/${mockCapture.capture_id}/mock-drafts`, { request_sha256: mockCapture.request_sha256,
    mock_outcome: "draft" }, "X-Second-Order-Intake");
  const review = async (draftId) => {
    const loaded = await evaluate(`fetch("/api/drafts/${draftId}").then(async (r) => ({ hash: r.headers.get("x-draft-view-sha256"),
      body: await r.json() }))`);
    return post(`/api/drafts/${draftId}/reviews`, { parent_review_id: null, status: "human_reviewed",
      notes: "Checked in the browser check.", corrections: { summary: null, legs: {} },
      binding: { draft_view_sha256: loaded.hash, prompt_hash: loaded.body.provenance.prompt_hash,
                 response_sha256: loaded.body.provenance.response_sha256 } }, "X-Second-Order-Review");
  };
  const reviewed = [await review(paid.body.draft_id), await review(mock.body.draft_id)];
  check("a paid and a mock draft were made and reviewed through the app's own routes",
    paidCapture.prompt_version === "draft-prompt-6" && paid.status === 201 && mock.status === 201 &&
    reviewed.every((row) => row.status === 201), JSON.stringify([paid.status, mock.status, reviewed.map((r) => r.status)]));
  await open(`/?draft=${paid.body.draft_id}`);
  check("the review panel shows the new draft's H.15 observables",
    await waitFor(`[...document.querySelectorAll(".draft-leg-title code")].map((e) => e.textContent).join(" ").includes("yield:ust2y_cmt_h15")`));
  await open("/hypotheses");
  await waitFor(`!!document.querySelector(".freeze-flow")`);
  await click('input[name="freeze-origin"]:not(:checked)');
  check("the reviewed paid draft is eligible and the mock draft is not, with its reason",
    await waitFor(`!!document.querySelector('.freeze-draft-list li[data-draft="${paid.body.draft_id}"].is-eligible')`) &&
    (await text(`.freeze-draft-list li[data-draft="${mock.body.draft_id}"]`)).includes("local mock") &&
    await evaluate(`document.querySelector('.freeze-draft-list li[data-draft="${mock.body.draft_id}"] input').disabled`));
  await click(`.freeze-draft-list li[data-draft="${paid.body.draft_id}"] input`);
  await waitFor(`document.querySelectorAll(".freeze-snapshot-list > li").length === 2`);
  await evaluate(`[...document.querySelectorAll(".freeze-snapshot-list > li")].find((li) => li.textContent.includes("2026-09-14"))
    .querySelector("input").click()`);
  await click(".freeze-preview-button");
  await previewShown();
  check("the model draft's preview names its review and keeps the model's engine",
    (await text(".freeze-preview")).includes("Reviewed model draft") && (await text(".freeze-preview")).includes("anthropic"));
  await click(".freeze-confirm input");
  await click(".button-freeze");
  check("the reviewed model draft is frozen", await waitFor(`!!document.querySelector(".freeze-outcome.is-frozen")`) &&
    await waitFor(`document.querySelectorAll(".frozen-list > li").length === 3`));
  const modelHref = await evaluate(`document.querySelector(".freeze-outcome.is-frozen a").getAttribute("href")`);
  const draftBytes = await evaluate(`fetch("/api/drafts/${paid.body.draft_id}").then((r) => r.text())`);
  // A later review version, saved after the freeze.
  const later = await evaluate(`fetch("/api/drafts/${paid.body.draft_id}/reviews").then((r) => r.json())`);
  const current = await evaluate(`fetch("/api/drafts/${paid.body.draft_id}").then(async (r) => ({
    hash: r.headers.get("x-draft-view-sha256"), body: await r.json() }))`);
  const second = await post(`/api/drafts/${paid.body.draft_id}/reviews`, {
    parent_review_id: later.reviews.at(-1).review_id, status: "human_reviewed", notes: "Checked again after the freeze.",
    corrections: { summary: null, legs: {} }, binding: { draft_view_sha256: current.hash,
      prompt_hash: current.body.provenance.prompt_hash, response_sha256: current.body.provenance.response_sha256 } },
    "X-Second-Order-Review");
  check("a later review version is saved after the freeze", second.status === 201, JSON.stringify(second.body));
  await open(`/?draft=${paid.body.draft_id}`);
  await waitFor(`!!document.querySelector(".review-flag-frozen")`);
  const flag = await text(".review-flag-frozen");
  check("the draft's panel shows its freeze, derived from the freeze record, and names the later review apart",
    flag.includes("Frozen as hypothesis") && flag.includes("this draft's own record is unchanged") &&
    flag.includes("Frozen with review version 1") && flag.includes("The current review is version 2") &&
    (await evaluate(`document.querySelector(".review-flag-frozen a").getAttribute("href")`)) === modelHref, flag);
  check("the draft's own record still states the status it was prepared with",
    (await evaluate(`fetch("/api/drafts/${paid.body.draft_id}").then((r) => r.text())`)) === draftBytes &&
    JSON.parse(draftBytes).review_status === "Not frozen · Requires human review");
  await open("/analyses");
  check("My analyses links the frozen analysis to its hypothesis, and only that one",
    await waitFor(`!!document.querySelector('.analysis-card[data-draft="${paid.body.draft_id}"] .analysis-frozen')`) &&
    (await evaluate(`document.querySelectorAll(".analysis-frozen").length`)) === 1);

  // 6. Reopen: read-only, after a reload and after a server restart.
  before = tree(served);
  await open(firstHref);
  const record = () => evaluate(`document.querySelector(".frozen-hypothesis")?.textContent ?? ""`);
  await waitFor(`!!document.querySelector(".frozen-hypothesis .freeze-status") && !!document.querySelector(".assess-flow")`);
  const shown = await record();
  check("the frozen record reopens as Frozen · Not evaluated with its baseline, no vintage, freshness, scoring and "
    + "classification", shown.includes("Frozen · Not evaluated") && shown.includes("None: no historical vintage") &&
    shown.includes("freshness-b-1") && shown.includes("Scoring window") && shown.includes("excluded from research summaries") &&
    shown.includes("Written by the browser check without AI assistance"), shown.slice(0, 200));
  await send("Page.reload", { ignoreCache: true });
  await waitFor(`!!document.querySelector(".frozen-hypothesis .freeze-status") && !!document.querySelector(".assess-flow")`);
  check("a reload shows the same record", (await record()) === shown);
  check("the reloaded record finished loading before the deliberate server stop", await settled());
  server.kill();
  await sleep(500);
  server = await startServer(port, ["--keep-records"]);
  await open(firstHref);
  await waitFor(`!!document.querySelector(".frozen-hypothesis .freeze-status") && !!document.querySelector(".assess-flow")`);
  check("after a server restart the record is the same", (await record()) === shown);
  check("reopening and reloading wrote nothing", same(tree(served), before));

  // 7. Narrow screens.
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  for (const path of ["/hypotheses", firstHref]) {
    await open(path);
    await waitFor(`!!document.querySelector(".hypotheses-header, .frozen-hypothesis")`);
    await sleep(500);
    const layout = await evaluate(`({ scroll: document.documentElement.scrollWidth,
      width: document.documentElement.clientWidth })`);
    check(`narrow screen ${path.startsWith("/hypotheses/") ? "/hypotheses/:id" : path}: no sideways scrolling`,
      layout.scroll <= layout.width, JSON.stringify(layout));
  }

  const outside = requests.filter((row) => !row.url.startsWith(base) && !row.url.startsWith("data:") && row.url !== "about:blank");
  check("nothing outside the local server was requested", outside.length === 0, outside.map((row) => row.url).join(", "));
  const real = errors.filter((entry) => !/favicon\.ico/.test(entry) && !/net::ERR_CONNECTION_CLOSED|Failed to fetch/.test(entry));
  check("no page error other than the deliberately dropped reply", real.length === 0, real.join(" | "));
  if (process.env.SECOND_ORDER_SCREENSHOTS) {
    await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 1600, deviceScaleFactor: 1, mobile: false });
    await open(firstHref);
    await waitFor(`!!document.querySelector(".frozen-hypothesis .freeze-status")`);
    await sleep(600);
    const shot = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(process.env.SECOND_ORDER_SCREENSHOTS, "frozen-record.png"), Buffer.from(shot.data, "base64"));
  }
  ws.close();
} catch (error) {
  check("the freeze browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(300);
  try { rmSync(root, { recursive: true, force: true }); } catch { /* Windows may hold a file briefly. */ }
}
console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
process.exit(results.every(Boolean) ? 0 : 1);
