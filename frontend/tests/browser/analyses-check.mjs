// Browser acceptance check for My analyses: the Tracker's saved analyses and their human reviews, searchable and
// filterable, opened in the existing review screen, reviewed with an explicit save, and seen updated on return.
// The server is tests/review_browser_server.py --simulated-provider over a new temporary folder: mock attempts, and paid
// attempts against an in-process fake of the Claude API (no network, a dummy key). Records are made through the app's
// own routes from the page; nothing under data/ is read or written, and no real provider is used.
//
//   cd frontend; npm run build; npm run test:browser:analyses
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const root = mkdtempSync(join(tmpdir(), "second-order-analyses-check-"));
const served = join(root, "served");
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const everyFile = (folderPath) => existsSync(folderPath) ? readdirSync(folderPath, { withFileTypes: true }).flatMap((entry) =>
  entry.isDirectory() ? everyFile(join(folderPath, entry.name)) : [join(folderPath, entry.name)]) : [];
const fingerprint = () => Object.fromEntries(everyFile(served).filter((path) => !path.includes("chrome"))
  .map((path) => [path, createHash("sha256").update(readFileSync(path)).digest("hex")]));
const providerCalls = () => everyFile(join(served, "simulated-provider")).filter((path) => /request-\d+\.json$/.test(path)).length;

// A later review version saved against another view, written as a valid chain by the app's own review module. It
// stands in for a review of an earlier prepared view, which the Tracker's never-replaced views cannot produce.
const STALE = `
import json, sys
from pathlib import Path
from second_order import human_review
reviews, draft = Path(sys.argv[1]) / "reviews", sys.argv[2]
records = human_review.history(reviews, draft)
last = records[-1]
stale = {key: last[key] for key in ("record_version", "draft_id", "attributed_to", "corrections")}
stale.update(sequence=len(records) + 1, parent_review_id=last["review_id"], saved_at="2026-10-08T12:00:00+00:00",
             status="human_reviewed", notes="Saved against an earlier view.",
             binding={**last["binding"], "draft_view_sha256": "0" * 64})
stale["review_id"] = human_review.review_id(stale)
(reviews / draft / f"{len(records) + 1:06d}.json").write_text(json.dumps(stale), encoding="utf-8")
`;

try {
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    "--simulated-provider"], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
  children.push(server);
  let started = false;
  for (let i = 0; i < 150 && !started; i++) {
    try { started = (await fetch(`${base}/api/drafts`)).ok; } catch { await sleep(200); }
  }
  if (!started) throw new Error("The review server did not start.");

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
  const listeners = [];
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    } else listeners.forEach((listener) => listener(message));
  });
  const send = (method, params = {}) => new Promise((done, fail) => {
    const id = ++counter;
    pending.set(id, (message) => message.error ? fail(new Error(message.error.message)) : done(message.result));
    ws.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) =>
    (await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })).result.value;
  const waitFor = async (expression, timeout = 10000) => {
    for (const start = Date.now(); Date.now() - start < timeout; await sleep(80)) {
      if (await evaluate(expression)) return true;
    }
    return false;
  };
  const setValue = (selector, value) => evaluate(`(() => {
    const element = document.querySelector(${JSON.stringify(selector)});
    if (!element) return false;
    const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
      : element instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value").set.call(element, ${JSON.stringify(value)});
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`);
  const click = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.click()`);
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);

  const requests = [];
  listeners.push((message) => {
    if (message.method === "Network.requestWillBeSent") {
      requests.push({ url: message.params.request.url, method: message.params.request.method });
    } else if (message.method === "Page.javascriptDialogOpening") {
      send("Page.handleJavaScriptDialog", { accept: true });
    }
  });
  const held = [];
  let fetchMode = "pass";
  listeners.push((message) => {
    if (message.method !== "Fetch.requestPaused") return;
    const { requestId } = message.params;
    if (fetchMode === "hold") held.push(requestId);
    else if (fetchMode === "fail") send("Fetch.failRequest", { requestId, errorReason: "ConnectionReset" });
    else send("Fetch.continueRequest", { requestId });
  });
  const posts = (part) => requests.filter((request) => request.method === "POST" && request.url.includes(part)).length;
  const libraryReads = () => requests.filter((request) => request.method === "GET" && request.url.endsWith("/api/analyses")).length;

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete'");
  };
  // Loaded: the list, the empty collection or a stated failure; never the loading message.
  const listedReady = "!!document.querySelector('.analysis-list, .analyses-empty, .analyses-state[role=alert]')";
  const cards = () => evaluate(`[...document.querySelectorAll(".analysis-card")].map((card) => ({
    draft: card.dataset.draft, headline: card.querySelector(".analysis-title").textContent,
    outcome: card.querySelector(".outcome-chip").textContent, mode: card.querySelector(".mode-mock, .mode-paid").textContent,
    review: card.querySelector(".analysis-review-chip").textContent, facts: card.querySelector(".analysis-facts").textContent,
    model: card.querySelector(".analysis-layer-model").textContent, mine: card.querySelector(".analysis-layer-review").textContent }))`);
  const card = async (headline) => (await cards()).find((row) => row.headline === headline);
  const post = (path, body, header) => evaluate(`fetch(${JSON.stringify(path)}, { method: "POST",
    headers: { "Content-Type": "application/json", ${JSON.stringify(header)}: "1" }, body: ${JSON.stringify(JSON.stringify(body))} })
    .then(async (response) => ({ status: response.status, body: await response.json() }))`);
  const made = {};
  const capture = async (headline) => {
    const saved = await post("/api/intake", { headline, source_url: "https://www.example.org/releases/statement",
      published_at: "2026-09-15T14:00:00-04:00", source_text: `Synthetic published text for ${headline}.` },
      "X-Second-Order-Intake");
    if (saved.status !== 201) throw new Error(`capture failed: ${JSON.stringify(saved)}`);
    return saved.body;
  };
  const mock = async (headline, outcome) => {
    const preview = await capture(headline);
    const sent = await post(`/api/intake/${preview.capture_id}/mock-drafts`,
      { request_sha256: preview.request_sha256, mock_outcome: outcome }, "X-Second-Order-Intake");
    made[headline] = { draft: sent.body.draft_id, capture: preview.capture_id };
  };
  const paid = async (headline) => {
    const preview = await capture(headline);
    const sent = await post(`/api/intake/${preview.capture_id}/paid-drafts`, { request_sha256: preview.request_sha256,
      approve_paid_request: true, estimated_max_usd: preview.cost_estimate.estimated_real_run_if_output_reaches_max_usd },
      "X-Second-Order-Intake");
    made[headline] = { draft: sent.body.draft_id, capture: preview.capture_id };
  };

  // 1. Before anything is analyzed: an honest empty library, reachable from the navigation.
  await open("/");
  check("navigation: My analyses is listed in the site navigation",
    await waitFor(`!!document.querySelector('.site-nav a[href="/analyses"]')`) &&
    (await text('.site-nav a[href="/analyses"]')) === "My analyses");
  await click('.site-nav a[href="/analyses"]');
  await waitFor(listedReady);
  check("empty: the address is /analyses and the page says no analyses exist yet",
    (await evaluate("location.pathname")) === "/analyses" &&
    (await text(".analyses-empty")).includes("No analyses yet") &&
    (await evaluate(`document.querySelector('.site-nav a[href="/analyses"]').getAttribute("aria-current")`)) === "page");
  check("empty: the two prepared pilot drafts are not listed, only counted as elsewhere",
    (await text(".analyses-not-listed")).includes("2 prepared pilot drafts are listed under Drafts for review") &&
    !(await evaluate("document.body.innerText")).includes("Synthetic committee signals a slower tightening pace"));

  // 2. Analyses of every outcome and both modes, made through the app's own routes, and one unsent capture.
  await mock("Mock draft analysis", "draft");
  await mock("Mock refusal analysis", "no_draft");
  await paid("Paid draft analysis");
  await paid("Simulated refusal analysis");
  await paid("Simulated invalid analysis");
  await paid("Simulated provider error analysis");
  await capture("Captured but never sent");
  const calls = providerCalls();
  check("setup: four paid requests reached the simulated provider, the two mocks none", calls === 4, String(calls));

  await open("/analyses");
  await waitFor("document.querySelectorAll('.analysis-card').length === 6");
  const listed = await cards();
  check("library: the six published analyses are listed, the unsent capture is not",
    listed.length === 6 && !listed.some((row) => row.headline === "Captured but never sent") &&
    (await text(".analyses-not-listed")).includes("1 saved event has no published review view yet (1 not sent)"));
  const by = Object.fromEntries(listed.map((row) => [row.headline, row]));
  check("library: each recorded outcome is labelled as the review screen labels it",
    by["Mock draft analysis"].outcome === "Draft" && by["Mock refusal analysis"].outcome === "No draft" &&
    by["Simulated refusal analysis"].outcome === "No draft" && by["Simulated invalid analysis"].outcome === "Invalid response" &&
    by["Simulated provider error analysis"].outcome === "Technical failure", JSON.stringify(listed.map((r) => r.outcome)));
  check("library: mock responses are labelled local and distinguished from paid provider responses",
    by["Mock draft analysis"].mode === "Local mock" && by["Mock draft analysis"].facts.includes("no provider was contacted") &&
    by["Paid draft analysis"].mode === "Paid provider response" && by["Paid draft analysis"].facts.includes("HTTP 200") &&
    by["Simulated provider error analysis"].facts.includes("HTTP 529"));
  check("library: the publication time keeps its recorded offset and shows the same instant in UTC",
    by["Paid draft analysis"].facts.includes("15 Sep 2026, 14:00 UTC−04:00") &&
    by["Paid draft analysis"].facts.includes("15 Sep 2026, 18:00 UTC"));
  check("library: the source is a link to the recorded address",
    await evaluate(`document.querySelector(".analysis-source")?.getAttribute("href") === "https://www.example.org/releases/statement"`));
  check("library: the model's words and the reviewer's layer are separate, and nothing is reviewed yet",
    by["Mock draft analysis"].model.includes("Mock workflow draft") && by["Mock draft analysis"].mine.includes("No review has been saved") &&
    listed.every((row) => row.review === "Not reviewed"));

  // 3. Search and filters live in the address and survive a reload and Back.
  await setValue("#analyses-search", "refusal");
  await waitFor("document.querySelectorAll('.analysis-card').length === 2");
  check("search: a query narrows the list and is written to the address",
    (await evaluate("location.search")) === "?q=refusal" &&
    (await cards()).map((row) => row.headline).sort().join("|") === "Mock refusal analysis|Simulated refusal analysis");
  await setValue('select[name="mode"]', "paid");
  await waitFor("document.querySelectorAll('.analysis-card').length === 1");
  check("filter: the response-mode filter combines with the search",
    (await evaluate("location.search")) === "?q=refusal&mode=paid" &&
    (await text(".analyses-result-count")).startsWith("Showing 1 of 6 analyses matching “refusal”"));
  await open("/analyses?q=refusal&mode=paid");
  await waitFor("document.querySelectorAll('.analysis-card').length === 1");
  check("reload: the search and filter come back from the address",
    (await evaluate(`document.querySelector("#analyses-search").value`)) === "refusal" &&
    (await evaluate(`document.querySelector('select[name="mode"]').value`)) === "paid");
  await click('.site-nav a[href="/library"]');
  await waitFor("location.pathname === '/library'");
  await evaluate("history.back()");
  check("back: returning from another page restores the filtered list",
    await waitFor("location.search === '?q=refusal&mode=paid' && document.querySelectorAll('.analysis-card').length === 1"));
  await click(".analyses-reset");
  await waitFor("document.querySelectorAll('.analysis-card').length === 6");
  await setValue('select[name="outcome"]', "technical_failure");
  check("filter: the outcome filter shows only technical failures",
    await waitFor("document.querySelectorAll('.analysis-card').length === 1") &&
    (await cards())[0].headline === "Simulated provider error analysis");
  await setValue('select[name="outcome"]', "");
  await setValue('select[name="review"]', "none");
  await waitFor("location.search === '?review=none'");

  // 4. Open the existing review screen, save explicitly, and come back to an updated library.
  const target = made["Paid draft analysis"].draft;
  const reviewPostsBefore = posts("/reviews");
  await click(`.analysis-card[data-draft="${target}"] .analysis-actions a`);
  check("open: the existing review screen opens this analysis by its deep link",
    await waitFor(`document.querySelector(".draft-panel h3")?.textContent === "Paid draft analysis" &&
      !!document.querySelector(".human-review .review-field textarea")`, 15000) &&
    (await evaluate("new URLSearchParams(location.search).get('draft')")) === target);
  check("open: the panel is brought to the top of the screen and focused, with a way back to this exact list",
    await waitFor(`document.activeElement?.id === "draft-review-panel" &&
      Math.abs(document.getElementById("draft-review-panel").getBoundingClientRect().top) < 2`) &&
    (await evaluate(`document.querySelector(".drafts-return a")?.getAttribute("href")`)) === "/analyses?review=none");
  check("open: the model's proposal and your review stay separate layers with their provenance",
    await evaluate(`!!document.querySelector(".draft-model") && !!document.querySelector(".human-review") &&
      document.querySelector(".draft-model").textContent.includes("Written by claude-sonnet-5-5") &&
      document.querySelector(".draft-provenance").textContent.includes("req_simulated0001")`));
  await evaluate(`[...document.querySelectorAll(".review-status input")][2].click()`);
  await setValue(".human-review .review-field textarea", "Reviewed from My analyses.");
  await sleep(300);
  check("save: nothing is saved before the explicit save", posts("/reviews") === reviewPostsBefore);
  await click(".review-save-bar button");
  check("save: the review version is saved by the explicit action, once",
    await waitFor(`!!document.querySelector(".review-message.is-saved")`) && posts("/reviews") === reviewPostsBefore + 1);
  await click(".drafts-return a");
  check("return: the way back restores the filtered list, which no longer holds the reviewed analysis",
    await waitFor(`location.pathname === "/analyses" && location.search === "?review=none" &&
      document.querySelectorAll(".analysis-card").length === 5`) &&
    !(await cards()).some((row) => row.draft === target));
  await setValue('select[name="review"]', "human_reviewed");
  await waitFor("document.querySelectorAll('.analysis-card').length === 1");
  const reviewed = (await cards())[0];
  check("return: the analysis now shows its human review, its note and its version",
    reviewed?.draft === target && reviewed.review === "Human-reviewed" && reviewed.mine.includes("Reviewed from My analyses.") &&
    reviewed.mine.includes("The latest of 1 saved version, marked reviewed by a person"), JSON.stringify(reviewed));
  await click(".analyses-reset");
  await waitFor("document.querySelectorAll('.analysis-card').length === 6");
  await click(`.analysis-card[data-draft="${made["Mock draft analysis"].draft}"] .analysis-title a`);
  await waitFor(`document.querySelector(".draft-panel h3")?.textContent === "Mock draft analysis"`, 15000);
  await evaluate("history.back()");
  check("back: the browser's Back from the review screen returns to the library",
    await waitFor(`location.pathname === "/analyses" && document.querySelectorAll(".analysis-card").length === 6`));

  // 5. Reads only: loading the library changes no record and contacts no provider.
  const before = fingerprint();
  const callsBefore = providerCalls();
  const readsBefore = libraryReads();
  for (let i = 0; i < 3; i++) {
    await open("/analyses?q=analysis&review=none");
    await waitFor("document.querySelectorAll('.analysis-card').length >= 1");
  }
  check("reads: three library loads read the library three times and changed nothing on disk",
    libraryReads() - readsBefore === 3 && JSON.stringify(fingerprint()) === JSON.stringify(before));
  check("reads: no provider was contacted by any library read", providerCalls() === callsBefore);

  // 6. Review bindings: a later version about another view, and a history that does not verify.
  const stale = spawnSync(python, ["-c", STALE, served, target], { cwd: repo, encoding: "utf8" });
  if (stale.status !== 0) throw new Error(stale.stderr);
  await open("/analyses");
  await waitFor("document.querySelectorAll('.analysis-card').length === 6");
  const staleCard = (await cards()).find((row) => row.draft === target);
  check("stale: a review saved against another view does not make this view reviewed",
    staleCard?.review === "Not reviewed for this view" && staleCard.mine.includes("saved against an earlier version") &&
    !staleCard.mine.includes("Reviewed from My analyses."), JSON.stringify(staleCard));
  const refusal = made["Simulated refusal analysis"].draft;
  mkdirSync(join(served, "reviews", refusal), { recursive: true });
  writeFileSync(join(served, "reviews", refusal, "000002.json"), "{}");
  await open("/analyses");
  await waitFor("document.querySelectorAll('.analysis-card').length === 6");
  check("invalid: a review history that does not verify is shown as unreadable, never as not reviewed",
    (await card("Simulated refusal analysis"))?.review === "Review history unreadable");

  // 7. One damaged record is reported; the rest of the collection stays usable.
  const broken = made["Mock refusal analysis"];
  writeFileSync(join(served, "tracker-drafts", `draft-${broken.draft}.json`), "{}");
  await open("/analyses");
  await waitFor("document.querySelectorAll('.analysis-card').length === 5");
  check("damaged: the damaged analysis is listed as unreadable with its capture, and five remain usable",
    (await text(".analyses-unreadable h2")) === "Records that could not be read (1)" &&
    (await text(".analyses-unreadable-note")).startsWith("1 record could not be read; it is listed after the analyses") &&
    (await text(".analyses-unreadable")).includes(`Capture ${broken.capture}`) &&
    !(await cards()).some((row) => row.headline === "Mock refusal analysis"));

  // 8. Loading and a failed load are stated, and trying again reads once more.
  await send("Fetch.enable", { patterns: [{ urlPattern: "*/api/analyses", requestStage: "Request" }] });
  fetchMode = "hold";
  await send("Page.navigate", { url: `${base}/analyses` });
  check("loading: the page says it is loading while the library is on its way",
    await waitFor(`document.querySelector(".analyses-state")?.textContent === "Loading your analyses…"`));
  for (const requestId of held.splice(0)) await send("Fetch.continueRequest", { requestId });
  fetchMode = "fail";
  await waitFor("document.querySelectorAll('.analysis-card').length === 5");
  await open("/analyses");
  check("error: a failed load says so and offers to try again",
    await waitFor(`(document.querySelector(".analyses-state")?.textContent ?? "").includes("could not be loaded")`));
  fetchMode = "pass";
  await click(".analyses-state button");
  check("error: trying again loads the library", await waitFor("document.querySelectorAll('.analysis-card').length === 5"));
  await send("Fetch.disable");

  // 9. A narrow screen keeps the page within its width.
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  await open("/analyses");
  await waitFor("document.querySelectorAll('.analysis-card').length === 5");
  check("narrow: no horizontal scrolling at 390 pixels",
    await evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"));

  const outside = requests.filter((request) => !request.url.startsWith(base) && !request.url.startsWith("data:") &&
    request.url !== "about:blank");
  check("the page requested nothing outside the local server", outside.length === 0,
    outside.map((request) => request.url).join(", "));
  ws.close();
} catch (error) {
  check("the analyses browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(500);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
