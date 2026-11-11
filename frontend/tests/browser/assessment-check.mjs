// Browser check of the A3 workflow (Hypotheses): outcome readiness, one approved outcome retrieval, explicit outcome
// import, a previewed assessment approved once as "Evaluate and prepare Dossier", the prepared Dossier, a reassessment,
// a lost reply, a failed preparation completed by an explicit Prepare Dossier, and the journal after reloads and a
// server restart. It runs against tests/review_browser_server.py serving a new, empty folder with --assessment
// (SYNTHETIC packages and three frozen hypotheses: two manual H.15 ones and a FRED-bound one stored before freshness
// policy B) and --simulated-market (an in-process fake of the Board's server whose first request gets an empty web
// page). The lifecycle clock starts at 14:00 UTC on 5 October 2026. It checks:
// - pages and reads write nothing; readiness states are kept apart; the FRED hypothesis is never planned or given H.15;
// - a retrieval preview names the selected hypotheses, missing past dates, reuse and the full-release download; a
//   failed attempt stays visible and is not retried; a second approval saves one package; a covered selection needs no
//   request;
// - an outcome is imported only by an explicit click; the preview shows the IDs, rules, cutoff, dates and what will be
//   created, and no result; a double click records one assessment, and its Dossier is prepared;
// - a reassessment needs its own confirmation; a lost reply is settled by reading, not by sending again; a failed
//   preparation keeps the evaluation and an explicit Prepare Dossier completes it without evaluating again;
// - reloads and a restart reopen the journal, assessment and Dossier unchanged; narrow screens; no outside request.
//
//   cd frontend; npm run build; npm run test:browser:assessment
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
const root = mkdtempSync(join(tmpdir(), "second-order-assessment-check-"));
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
const marketRequests = () => {
  const log = join(served, "simulated-market", "requests.jsonl");
  return existsSync(log) ? readFileSync(log, "utf8").split("\n").filter(Boolean).length : 0;
};

async function startServer(port, extra) {
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    ...extra], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  for (let i = 0; i < 300; i++) {
    try { if ((await fetch(`http://127.0.0.1:${port}/api/lifecycle`)).ok) return server; } catch { /* starting */ }
    await sleep(200);
  }
  throw new Error("The review server did not start.");
}

try {
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  let server = await startServer(port, ["--assessment", "--simulated-market"]);

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
  let dropReply = false;
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
    } else if (message.method === "Fetch.requestPaused") {
      const id = ++counter;  // The server has answered; with dropReply the page never receives it.
      ws.send(JSON.stringify({ id, method: dropReply ? "Fetch.failRequest" : "Fetch.continueRequest",
                               params: dropReply ? { requestId: message.params.requestId, errorReason: "ConnectionClosed" }
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
  const posts = (suffix) => requests.filter((row) => row.method === "POST" && row.url.endsWith(suffix)).length;
  const journalRow = (headline) => `[...document.querySelectorAll(".frozen-list > li")].find((li) =>
    li.querySelector(".frozen-headline")?.textContent.includes(${JSON.stringify(headline)}))`;
  const PAYROLLS = "Synthetic payrolls release (assessment check)";
  const RETAIL = "Synthetic retail sales release (retrieval check)";
  const FRED = "Synthetic Treasury announcement";

  // 1. The journal: one entry per frozen hypothesis, with its state, origin and provider. Reads write nothing.
  let before = tree(served);
  await open("/hypotheses");
  await waitFor(`document.querySelectorAll(".frozen-list > li").length === 3`);
  const row = (headline) => evaluate(`(${journalRow(headline)})?.textContent ?? ""`);
  const payrollsRow = await row(PAYROLLS);
  const retailRow = await row(RETAIL);
  const fredRow = await row(FRED);
  check("the journal lists each frozen hypothesis with its own lifecycle state, origin and provider",
    payrollsRow.includes("Outcome data held") && payrollsRow.includes("Manual hypothesis") &&
    payrollsRow.includes("Federal Reserve Board H.15") && retailRow.includes("Outcome data missing") &&
    retailRow.includes("expected target 2026-10-01") && fredRow.includes("Frozen outside this interface") &&
    fredRow.includes("FRED"), [payrollsRow, retailRow, fredRow].join(" | "));
  const payrollsId = await evaluate(`(${journalRow(PAYROLLS)}).dataset.hypothesis`);
  const retailId = await evaluate(`(${journalRow(RETAIL)}).dataset.hypothesis`);
  const fredId = await evaluate(`(${journalRow(FRED)}).dataset.hypothesis`);

  // 2. Outcome retrieval: nothing preselected; the FRED hypothesis is not offered.
  const offered = await evaluate(`[...document.querySelectorAll('input[name="retrieval-hypothesis"]')].map((input) =>
    ({ id: input.closest("label").dataset.hypothesis, checked: input.checked }))`);
  check("the outcome-data card offers only the H.15 hypotheses, with none preselected",
    offered.length === 2 && offered.every((item) => !item.checked) && !offered.some((item) => item.id === fredId) &&
    (await text(".hypotheses-outcome")).includes("FRED-bound hypotheses are not listed"), JSON.stringify(offered));
  check("loading the journal wrote nothing", same(tree(served), before));
  await click(`label[data-hypothesis="${retailId}"] input`);
  await click(".retrieval-preview-button");
  await waitFor(`!!document.querySelector(".retrieval-plan")`);
  const plan = await text(".retrieval-plan");
  check("the retrieval preview names the hypothesis, its missing past date, the reused package and one full-release "
    + "download", plan.includes(RETAIL) && plan.includes("2026-09-29 to 2026-10-01") && plan.includes("2026-10-01") &&
    plan.includes("Kept package") && plan.includes("One: the full release package") && plan.includes("needs no key"),
    plan);
  check("the preview wrote nothing and sent nothing", same(tree(served), before) && marketRequests() === 0);
  await click('input[name="approve-retrieval"]');
  await evaluate(`(() => { const button = document.querySelector(".retrieval-send"); button.click(); button.click(); })()`);
  await waitFor(`!!document.querySelector(".retrieval-flow .freeze-outcome")`);
  const failed = await text(".retrieval-flow .freeze-outcome");
  check("the first approved attempt is sent once, fails visibly (an empty web page) and is not retried",
    marketRequests() === 1 && posts("/api/lifecycle/retrievals") === 1 && failed.includes("refused reply") &&
    failed.includes("Nothing is retried"), `${marketRequests()} ${posts("/api/lifecycle/retrievals")} ${failed}`);
  await click(".retrieval-preview-button");
  await waitFor(`!!document.querySelector(".retrieval-plan")`);
  check("the next preview names the earlier attempt", (await text(".retrieval-plan")).includes("Attempt 1"));
  await click('input[name="approve-retrieval"]');
  await click(".retrieval-send");
  await waitFor(`(document.querySelector(".retrieval-flow .freeze-outcome")?.dataset.outcome ?? "") === "saved"`);
  check("a second, separately approved attempt keeps one package; nothing was imported or assessed",
    marketRequests() === 2 && (await text(".retrieval-flow .freeze-outcome")).includes("nothing was imported or assessed"));
  await click(".retrieval-preview-button");
  await waitFor(`!!document.querySelector(".retrieval-plan")`);
  check("the same selection is now covered and needs no request",
    (await evaluate(`document.querySelector('.retrieval-plan [data-requests]')?.dataset.requests`)) === "0" &&
    !(await evaluate(`!!document.querySelector(".retrieval-send")`)) && marketRequests() === 2);

  // 3. The payrolls hypothesis: readiness, an explicit outcome import, a preview, one approval.
  before = tree(served);
  await open(`/hypotheses/${payrollsId}`);
  await waitFor(`!!document.querySelector(".assess-flow")`);
  const readiness = await text(".assess-readiness");
  check("the hypothesis page shows its readiness and expected dates under the date convention",
    readiness.includes("Ready for an explicit assessment") && readiness.includes("latest expected target 2026-09-23") &&
    readiness.includes("2026-09-23T23:59:59-04:00") && readiness.includes("does not pin scoring rules"), readiness);
  check("opening the hypothesis page wrote nothing", same(tree(served), before));
  check("nothing is selected for the user; the choice is explicit",
    await evaluate(`[...document.querySelectorAll('input[name="outcome-snapshot"]')].every((input) => !input.checked)`) &&
    await evaluate(`document.querySelector(".assess-preview-button").disabled`));
  const importButton = `.freeze-package-list > li button`;
  check("kept packages that could serve are offered for an explicit import from the publication date",
    (await text(".assess-flow .freeze-package-list")).includes("Import as outcome from 2026-09-15"));
  await evaluate(`[...document.querySelectorAll(${JSON.stringify(importButton)})].find((button) =>
    button.closest("li").textContent.includes("to 2026-09-30")).click()`);
  check("importing selects the new outcome snapshot", await waitFor(`[...document.querySelectorAll('input[name="outcome-snapshot"]')]
    .some((input) => input.checked)`) && await waitFor(`(document.querySelector('.assess-flow [role="status"]')?.textContent ?? "")
    .includes("Imported as a new outcome snapshot")`));
  const chosenSnapshot = await evaluate(`document.querySelector('input[name="outcome-snapshot"]:checked').closest("li").dataset.snapshot`);
  before = tree(served);
  await click(".assess-preview-button");
  await waitFor(`!!document.querySelector(".assess-flow .freeze-preview")`);
  const previewText = await text(".assess-flow .freeze-preview");
  check("the preview binds the hypothesis, baseline, outcome, rules and cutoff, lists what it will create, and shows "
    + "no result", previewText.includes(payrollsId) && previewText.includes(chosenSnapshot) &&
    previewText.includes("0.5.0") && previewText.includes("Cutoff (server's)") && previewText.includes("2026-09-16") &&
    previewText.includes("2026-09-23") && previewText.includes("One prepared Dossier file") &&
    previewText.includes("not its result") && !/\b(supported|contradicted)\b/.test(previewText), previewText.slice(0, 500));
  check("the preview wrote nothing", same(tree(served), before));
  check("Evaluate and prepare Dossier is disabled until the approval is ticked",
    await evaluate(`document.querySelector(".assess-flow .button-freeze").disabled`) &&
    (await text(".assess-flow .button-freeze")) === "Evaluate and prepare Dossier");
  await click('input[name="approve-assessment"]');
  await evaluate(`(() => { const button = document.querySelector(".assess-flow .button-freeze"); button.click(); button.click(); })()`);
  await waitFor(`!!document.querySelector(".assess-flow .freeze-outcome")`);
  const recorded = await text(".assess-flow .freeze-outcome");
  check("a double click records one assessment and prepares its Dossier",
    posts("/api/lifecycle/assessments") === 1 && recorded.includes("Evaluation saved and Dossier prepared"), recorded);
  const dossierHref = await evaluate(`[...document.querySelectorAll(".assess-flow .freeze-outcome a")]
    .find((a) => a.textContent.includes("Dossier"))?.getAttribute("href") ?? ""`);
  const firstAssessmentHref = await evaluate(`[...document.querySelectorAll(".assess-flow .freeze-outcome a")]
    .find((a) => a.textContent.includes("recorded assessment"))?.getAttribute("href") ?? ""`);
  check("the assessment wrote only to the store and its one prepared Dossier",
    Object.keys(tree(served)).filter((path) => !(path in before) || tree(served)[path] !== before[path])
      .every((path) => path.startsWith(join("store", "research"))));

  // 4. The prepared Dossier and the recorded assessment, read-only.
  await open(dossierHref);
  await waitFor(`!!document.querySelector(".lifecycle-dossier-note") && !!document.querySelector(".dossier svg")`);
  const note = await text(".lifecycle-dossier-note");
  check("the Dossier shows its chart, reproducibility and the raw package held here",
    note.includes("reproducible") && note.includes("is held here and verifies") &&
    await evaluate(`document.querySelectorAll(".dossier svg").length >= 2`), note);
  before = tree(served);
  const dossierText = await text("main");
  await send("Page.reload", { ignoreCache: true });
  await waitFor(`!!document.querySelector(".dossier svg")`);
  check("a reload shows the same Dossier and writes nothing", (await text("main")) === dossierText && same(tree(served), before));
  await open(firstAssessmentHref);
  await waitFor(`!!document.querySelector(".assess-recorded-legs")`);
  check("the recorded assessment shows its legs, cutoff, rules and Dossier link",
    (await text(".assessment-record")).includes("Recorded by") && (await text(".assessment-record")).includes("interface approval") &&
    await evaluate(`document.querySelectorAll(".assess-recorded-legs tbody tr").length === 2`));
  const legDates = await evaluate(`[...document.querySelectorAll(".assess-recorded-legs tbody tr")].map((row) =>
    row.children[5].textContent)`);
  check("its legs show the New York dates measured: scoring anchor 16 September, target 23 September",
    legDates.every((cell) => cell === "2026-09-16 → 2026-09-23"), JSON.stringify(legDates));

  // 5. A reassessment on the other snapshot, with a lost reply settled by reading.
  await open(`/hypotheses/${payrollsId}`);
  await waitFor(`!!document.querySelector(".assess-flow")`);
  await evaluate(`[...document.querySelectorAll('input[name="outcome-snapshot"]')].find((input) =>
    !input.disabled && input.closest("li").dataset.snapshot !== ${JSON.stringify(chosenSnapshot)}).click()`);
  await click(".assess-preview-button");
  await waitFor(`!!document.querySelector(".assess-flow .freeze-preview")`);
  await click('input[name="approve-assessment"]');
  check("a reassessment needs its own confirmation before it can be approved",
    !!(await evaluate(`!!document.querySelector(".assess-reassess")`)) &&
    await evaluate(`document.querySelector(".assess-flow .button-freeze").disabled`));
  await click('input[name="reassessment"]');
  await send("Fetch.enable", { patterns: [{ urlPattern: "*/api/lifecycle/assessments", requestStage: "Response" }] });
  dropReply = true;
  before = posts("/api/lifecycle/assessments");
  await click(".assess-flow .button-freeze");
  const unconfirmed = await waitFor(`!!document.querySelector(".assess-flow .freeze-outcome.is-unconfirmed")`);
  dropReply = false;
  await send("Fetch.disable");
  check("a lost reply is shown as unconfirmed and the approval is not sent again",
    unconfirmed && posts("/api/lifecycle/assessments") - before === 1 &&
    (await text(".assess-flow .freeze-outcome")).includes("not sent again"));
  await click(".assess-flow .freeze-outcome button");
  check("checking reads that the approval recorded the reassessment",
    await waitFor(`(document.querySelector(".assess-flow .freeze-outcome")?.textContent ?? "").includes("This approval recorded")`) &&
    posts("/api/lifecycle/assessments") - before === 1);

  // 6. The retail hypothesis: import the downloaded package; preparation fails once, then is prepared explicitly.
  await open(`/hypotheses/${retailId}`);
  await waitFor(`!!document.querySelector(".assess-flow .freeze-package-list")`);
  await evaluate(`[...document.querySelectorAll(".assess-flow .freeze-package-list > li button")].find((button) =>
    button.textContent.includes("2026-09-29"))?.click()`);
  await waitFor(`[...document.querySelectorAll('input[name="outcome-snapshot"]')].some((input) => input.checked)`);
  await click(".assess-preview-button");
  await waitFor(`!!document.querySelector(".assess-flow .freeze-preview")`);
  const blocked = join(served, "store", "research-dossiers", retailId);
  mkdirSync(dirname(blocked), { recursive: true });
  writeFileSync(blocked, "A file where the Dossier folder would go: preparation cannot write.");
  await click('input[name="approve-assessment"]');
  await click(".assess-flow .button-freeze");
  await waitFor(`!!document.querySelector(".assess-flow .freeze-outcome")`);
  const saved = await text(".assess-flow .freeze-outcome");
  check("when preparation fails the page says Evaluation saved; Dossier not prepared",
    saved.includes("Evaluation saved; Dossier not prepared") && saved.includes("Prepare Dossier"), saved);
  rmSync(blocked);
  const evaluations = posts("/api/lifecycle/assessments");
  await click(".assess-flow .assess-prepare button");
  check("an explicit Prepare Dossier prepares it without evaluating again",
    await waitFor(`(document.querySelector(".assess-prepare")?.textContent ?? "").includes("Dossier prepared.")`) &&
    posts("/api/lifecycle/assessments") === evaluations && posts("/api/lifecycle/dossier-preparations") === 1);

  // 7. The FRED hypothesis: only local FRED snapshots; nothing is offered from H.15.
  await open(`/hypotheses/${fredId}`);
  await waitFor(`!!document.querySelector(".assess-flow")`);
  const fredFlow = await text(".assess-flow");
  check("the FRED-bound hypothesis says why no outcome is offered, with no H.15 package or retrieval",
    fredFlow.includes("never substituted") && fredFlow.includes("No other snapshot of this provider is stored") &&
    !(await evaluate(`!!document.querySelector(".assess-flow .freeze-package-list")`)), fredFlow.slice(0, 300));

  // 8. Reopen after a restart: the journal lists every assessment by record time, and reads write nothing.
  server.kill();
  await sleep(500);
  server = await startServer(port, ["--keep-records", "--assessment", "--simulated-market"]);
  before = tree(served);
  await open("/hypotheses");
  await waitFor(`document.querySelectorAll(".frozen-list > li").length === 3`);
  const reopened = await row(PAYROLLS);
  check("after a restart the journal lists both assessments of the payrolls hypothesis with their Dossiers",
    reopened.includes("Assessment recorded") && reopened.includes("Assessment 1") && reopened.includes("Assessment 2") &&
    await evaluate(`(${journalRow(PAYROLLS)}).querySelectorAll(".assess-list a[href*='/dossiers/']").length === 2`), reopened);
  check("the retail hypothesis's assessment and Dossier are listed", (await row(RETAIL)).includes("Assessment 1") &&
    await evaluate(`(${journalRow(RETAIL)}).querySelectorAll(".assess-list a[href*='/dossiers/']").length === 1`));
  await open(dossierHref);
  await waitFor(`!!document.querySelector(".dossier svg")`);
  check("the Dossier reopens unchanged after the restart", (await text("main")) === dossierText);
  check("reopening after the restart wrote nothing", same(tree(served), before));

  // 9. Narrow screens.
  await send("Emulation.setDeviceMetricsOverride", { width: 375, height: 812, deviceScaleFactor: 2, mobile: true });
  for (const path of ["/hypotheses", `/hypotheses/${payrollsId}`, firstAssessmentHref, dossierHref]) {
    await open(path);
    await waitFor(`!!document.querySelector(".hypotheses-header, .frozen-hypothesis, .dossier")`);
    await sleep(600);
    const layout = await evaluate(`({ scroll: document.documentElement.scrollWidth, width: document.documentElement.clientWidth,
      wide: [...document.querySelectorAll("body *")].filter((element) => element.getBoundingClientRect().right >
        document.documentElement.clientWidth + 1 && element.parentElement.getBoundingClientRect().right <=
        document.documentElement.clientWidth + 1).slice(0, 3).map((element) => element.tagName + "." +
        String(element.className).replace(/ /g, ".") + ":" + Math.round(element.getBoundingClientRect().right)) })`);
    check(`narrow screen ${path.replace(/[0-9a-f]{64}/g, ":id")}: no sideways scrolling`, layout.scroll <= layout.width,
      JSON.stringify(layout));
  }

  const outside = requests.filter((entry) => !entry.url.startsWith(base) && !entry.url.startsWith("data:") &&
    entry.url !== "about:blank");
  check("nothing outside the local server was requested", outside.length === 0, outside.map((entry) => entry.url).join(", "));
  const real = errors.filter((entry) => !/favicon\.ico/.test(entry) && !/net::ERR_CONNECTION_CLOSED|Failed to fetch/.test(entry));
  check("no page error other than the deliberately dropped reply", real.length === 0, real.join(" | "));
  if (process.env.SECOND_ORDER_SCREENSHOTS) {
    await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 1800, deviceScaleFactor: 1, mobile: false });
    for (const [name, path] of [["journal", "/hypotheses"], ["hypothesis", `/hypotheses/${payrollsId}`],
                                ["assessment", firstAssessmentHref], ["dossier", dossierHref]]) {
      await open(path);
      await sleep(900);
      const shot = await send("Page.captureScreenshot", { format: "png" });
      writeFileSync(join(process.env.SECOND_ORDER_SCREENSHOTS, `${name}.png`), Buffer.from(shot.data, "base64"));
    }
  }
  ws.close();
} catch (error) {
  check("the assessment browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(300);
  try { rmSync(root, { recursive: true, force: true }); } catch { /* Windows may hold a file briefly. */ }
}
console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
process.exit(results.every(Boolean) ? 0 : 1);
