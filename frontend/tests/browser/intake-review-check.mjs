// Browser acceptance check for the operator path: event form -> exact request preview -> one local mock
// attempt -> existing human-review form -> saved review version. Then the failure paths: unsaved review edits
// while a new draft arrives (declined, delayed and failed list refreshes), a lost dispatch reply, a publication
// failure recovered from the saved records, an interrupted attempt, refusal persistence after refresh, and the
// documented prepare-drafts step leaving Tracker drafts reviewable. It uses an empty temporary folder, calls no
// model or provider, and checks that the page never requests anything outside the local server.
//
//   cd frontend; npm run build; npm run test:browser:intake
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync } from "node:fs";
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
const until = async (condition, timeout = 10000) => {
  for (const start = Date.now(); Date.now() - start < timeout; await sleep(50)) if (condition()) return true;
  return false;
};
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const root = mkdtempSync(join(tmpdir(), "second-order-intake-check-"));
const served = join(root, "served");
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const folder = (...parts) => (existsSync(join(served, ...parts)) ? readdirSync(join(served, ...parts)).sort() : []);
const fileHashes = (path) => Object.fromEntries(folder(path).map((name) =>
  [name, createHash("sha256").update(readFileSync(join(served, path, name))).digest("hex")]));

try {
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  const server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
    "--fault-probes"], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
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
  const bodyText = () => evaluate("document.body.innerText");
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);

  // Every request the page makes is recorded; confirm() answers come from `answer`; unloads are allowed.
  const requests = [];
  const dialogs = [];
  let answer = false;
  listeners.push((message) => {
    if (message.method === "Network.requestWillBeSent") {
      requests.push({ url: message.params.request.url, method: message.params.request.method });
    } else if (message.method === "Page.javascriptDialogOpening") {
      if (message.params.type !== "beforeunload") dialogs.push(message.params.message);
      send("Page.handleJavaScriptDialog", { accept: message.params.type === "beforeunload" || answer });
    }
  });
  // Paused requests are held, failed or passed according to `fetchMode`.
  const held = [];
  let fetchMode = "pass";
  listeners.push((message) => {
    if (message.method !== "Fetch.requestPaused") return;
    const { requestId } = message.params;
    if (fetchMode === "hold") held.push(requestId);
    else if (fetchMode === "fail") send("Fetch.failRequest", { requestId, errorReason: "ConnectionReset" });
    else send("Fetch.continueRequest", { requestId });
  });
  const intercept = (urlPattern, requestStage, mode) => {
    fetchMode = mode;
    return send("Fetch.enable", { patterns: [{ urlPattern, requestStage }] });
  };
  const posts = (part) => requests.filter((request) => request.method === "POST" && request.url.includes(part)).length;

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete'");
  };
  const notes = ".human-review .review-field textarea";
  const notesValue = () => evaluate(`document.querySelector(${JSON.stringify(notes)})?.value ?? null`);
  const reviewStatus = () => text(".review-dirty");
  const approve = ".intake-preview .intake-actions .button:not(.button-quiet)";
  const approveOffered = () => evaluate(`(() => { const b = document.querySelector(${JSON.stringify(approve)});
    return !!b && !b.disabled; })()`);
  const listedHeadlines = () =>
    evaluate(`[...document.querySelectorAll(".draft-choice-headline")].map((e) => e.textContent)`);
  const selectedHeadline = () => text(".draft-panel h3");
  const panelShows = (headline) => `document.querySelector(".draft-panel h3")?.textContent === ${JSON.stringify(headline)}`;
  const chooseDraft = (headline) => evaluate(`[...document.querySelectorAll(".draft-choice")]
    .find((b) => b.querySelector(".draft-choice-headline").textContent === ${JSON.stringify(headline)})?.click()`);
  const PILOT = "Synthetic committee signals a slower tightening pace";
  const fillForm = async (headline, source, { date = "2026-09-15", time = "14:00", offset = "-04:00" } = {}) => {
    if (await evaluate(`!!document.querySelector(".intake-preview")`)) await click(".intake-preview .button-quiet");
    await waitFor(`!!document.querySelector(".intake-form")`);
    await setValue('.intake-form input:not([type="url"]):not([type="date"]):not([type="time"])', headline);
    await setValue('.intake-form input[type="url"]', "https://example.test/policy-statement");
    await setValue('.intake-form input[type="date"]', date);
    await setValue('.intake-form input[type="time"]', time);
    await setValue(".intake-time select", offset);
    await setValue(".intake-form textarea", source);
    await click(".intake-form button[type=submit]");
  };
  const fillEvent = async (headline, source = `Synthetic published text for ${headline}.`, time = {}) => {
    await fillForm(headline, source, time);
    await waitFor(`!!document.querySelector(".intake-preview")`);
  };
  const shownTimes = async () => ({ supplied: await text(".intake-time-supplied strong"),
                                    utc: await text(".intake-time-utc strong") });
  const requestHash = () => evaluate(`[...document.querySelectorAll(".intake-facts code")][1]?.textContent ?? ""`);

  // 1. The complete zero-cost path.
  await open("/");
  check("the Tracker exposes Analyze an event", await waitFor(`!!document.querySelector(".event-intake .intake-form")`));
  const source = "The committee kept its policy rate unchanged.\nIt said future decisions remain data-dependent.";
  await fillEvent("Central bank keeps its policy rate unchanged", source);
  check("the exact saved request preview appears", await waitFor(`!!document.querySelector(".intake-preview")`));
  // textContent includes the exact request inside the intentionally closed <details>; innerText does not.
  const previewText = await evaluate(`document.querySelector(".intake-preview").textContent`);
  check("the preview names Sonnet and a zero-cost mock",
    previewText.includes("claude-sonnet-5-5") && previewText.includes("Mock cost") && previewText.includes("$0.00"));
  const requestText = await evaluate(`document.querySelector(".intake-request pre").textContent`);
  check("the preview includes the entered source text",
    requestText.includes("The committee kept its policy rate unchanged.") &&
    requestText.includes("It said future decisions remain data-dependent."));
  check("approval is explicit before the mock attempt", !(await approveOffered()));
  check("paid sending is off unless the server enables it, and the mock is the default",
    await evaluate(`document.querySelector('.intake-source-choice input[value="paid"]').disabled`) &&
    await evaluate(`document.querySelector('.intake-source-choice input[value="mock"]').checked`) &&
    (await text(".intake-source-note")).includes("not enabled"));

  await click(".intake-confirm input");
  await click(approve);
  check("one mock draft opens in the existing review screen",
    await waitFor(`!!document.querySelector(".human-review") && location.search.startsWith("?draft=")`, 15000));
  const firstDraft = (await evaluate("location.search")).slice(7);
  const reviewText = await bodyText();
  check("the review screen labels the response as local mock evidence",
    reviewText.includes("Generated by a local mock") && reviewText.includes("no provider was contacted"));
  check("the review screen retains the recorded event",
    reviewText.includes("Central bank keeps its policy rate unchanged") && reviewText.includes(source));

  await evaluate(`[...document.querySelectorAll(".review-status input")][1].click()`);
  await setValue(notes, "Reviewed through the Tracker interface.");
  check("the human review can be saved", await waitFor(`!document.querySelector(".review-save-bar button").disabled`));
  await click(".review-save-bar button");
  check("the interface confirms a saved review version",
    await waitFor(`document.querySelector(".review-message.is-saved")?.textContent.includes("Saved version 1")`));

  const captures = folder("intake");
  const attempts = folder("tracker-attempts");
  check("exactly one capture and one attempt were recorded", captures.length === 1 && attempts.length === 1);
  const capturedRequest = readFileSync(join(served, "intake", captures[0], "request.json"));
  const attemptedRequest = readFileSync(join(served, "tracker-attempts", attempts[0], "request.json"));
  check("the attempt used the approved saved request byte-for-byte", capturedRequest.equals(attemptedRequest));
  const reviewFolders = folder("reviews");
  check("the review was persisted without JSON or command-line interaction",
    reviewFolders.length === 1 && folder("reviews", reviewFolders[0]).length === 1);

  await open(`/?draft=${firstDraft}`);
  check("refresh: the mock draft is still reviewable with its saved version",
    await waitFor(`document.querySelector(".review-dirty")?.textContent === "All changes saved · version 1"`) &&
    (await notesValue()) === "Reviewed through the Tracker interface.");

  // 2. Unsaved review edits while a new draft arrives: leaving is asked; declining keeps the edits and lists it.
  await chooseDraft(PILOT);
  await waitFor(`${panelShows(PILOT)} && !!document.querySelector(${JSON.stringify(notes)})`);
  await setValue(notes, "Unsaved notes on the pilot draft.");
  check("edits: the pilot draft has unsaved review notes", (await reviewStatus()) === "Unsaved changes");
  answer = false;
  const dialogsBefore = dialogs.length;
  await fillEvent("Second event while a review is unsaved");
  await click(".intake-confirm input");
  await click(approve);
  check("edits: opening the new draft asks before discarding them",
    await until(() => dialogs.length === dialogsBefore + 1, 10000), `${dialogs.length - dialogsBefore} dialogs`);
  await sleep(300);
  check("edits: declining keeps the open draft and its unsaved notes",
    (await selectedHeadline()) === PILOT && (await notesValue()) === "Unsaved notes on the pilot draft." &&
    (await reviewStatus()) === "Unsaved changes");
  check("edits: the new draft stays listed and is announced for later",
    (await listedHeadlines()).includes("Second event while a review is unsaved") &&
    (await text(".drafts-notice")).includes("Second event while a review is unsaved"));
  answer = true;
  await chooseDraft("Second event while a review is unsaved");
  check("edits: selecting it later asks again, and accepting opens it",
    await waitFor(panelShows("Second event while a review is unsaved")) && dialogs.length === dialogsBefore + 2);

  // 3. Delayed and failed list refreshes while a review is unsaved.
  answer = false;
  await chooseDraft(PILOT);
  await waitFor(`${panelShows(PILOT)} && !!document.querySelector(${JSON.stringify(notes)})`);
  await setValue(notes, "Notes kept through a slow and failed refresh.");
  await fillEvent("Third event during a slow list refresh");
  await click(".intake-confirm input");
  await intercept("*/api/drafts", "Request", "hold");
  const heldBefore = held.length;
  await click(approve);
  check("refresh: the list refresh is held after the new draft is recorded",
    await until(() => held.length > heldBefore, 10000) && folder("tracker-attempts").length === 3);
  await sleep(300);
  check("refresh: while it is delayed the review stays open with its notes",
    (await notesValue()) === "Notes kept through a slow and failed refresh." &&
    (await reviewStatus()) === "Unsaved changes");
  while (held.length) await send("Fetch.failRequest", { requestId: held.shift(), errorReason: "ConnectionReset" });
  check("refresh: a failed refresh is reported without closing the review",
    await waitFor(`!!document.querySelector(".drafts-refresh-error")`) &&
    (await notesValue()) === "Notes kept through a slow and failed refresh.");
  await send("Fetch.disable");
  fetchMode = "pass";
  const dialogsBeforeRetry = dialogs.length;
  await click(".drafts-refresh-error button");
  check("refresh: retrying lists the new draft and asks before opening it",
    await waitFor(`[...document.querySelectorAll(".draft-choice-headline")]
      .some((e) => e.textContent === "Third event during a slow list refresh")`) &&
    await until(() => dialogs.length === dialogsBeforeRetry + 1));
  await sleep(300);
  check("refresh: declining keeps the notes after the refresh",
    (await notesValue()) === "Notes kept through a slow and failed refresh." &&
    (await reviewStatus()) === "Unsaved changes");
  await open("/");  // Leaves the scratch notes (the unload prompt is accepted) before the next scenarios.
  await waitFor(`!!document.querySelector(".event-intake .intake-form")`);

  // 4. A lost dispatch reply is settled by reading the recorded state, never by sending again.
  await fillEvent("Lost reply event");
  await click(".intake-confirm input");
  await intercept("*/mock-drafts", "Response", "fail");
  const dispatchesBefore = posts("/mock-drafts");
  await click(approve);
  check("lost reply: the page reads what was recorded and opens the draft",
    await waitFor(panelShows("Lost reply event"), 15000));
  await send("Fetch.disable");
  fetchMode = "pass";
  check("lost reply: the page says the reply was lost and the saved records show the draft",
    (await text(".intake-attempt")).includes("reply was lost") &&
    (await evaluate(`document.querySelector(".intake-attempt")?.dataset.state`)) === "ready");
  check("lost reply: one dispatch request and one attempt, no second attempt",
    posts("/mock-drafts") === dispatchesBefore + 1 && folder("tracker-attempts").length === 4 && !(await approveOffered()));

  // 5. A publication failure is recovered from the saved records by an explicit action.
  await fillEvent("Publication failure probe event");
  await click(".intake-confirm input");
  const failedBefore = posts("/mock-drafts");
  await click(approve);
  check("publication failure: the recorded response is reported as awaiting publication",
    await waitFor(`document.querySelector(".intake-attempt")?.dataset.state === "awaiting_publication"`));
  check("publication failure: approving again is not offered", !(await approveOffered()));
  const failedCapture = folder("intake").at(-1);
  const recorded = fileHashes(join("tracker-attempts", failedCapture));
  check("publication failure: the attempt is complete but not listed",
    "manifest.json" in recorded && "response.json" in recorded &&
    !(await listedHeadlines()).includes("Publication failure probe event"));
  await click(".intake-publish");
  check("publication failure: publishing the recorded response opens the draft",
    await waitFor(panelShows("Publication failure probe event"), 15000));
  check("publication failure: recovery used the saved files unchanged and made no second attempt",
    JSON.stringify(fileHashes(join("tracker-attempts", failedCapture))) === JSON.stringify(recorded) &&
    posts("/mock-drafts") === failedBefore + 1 && folder("tracker-attempts").length === 5 && posts("/publish") === 1);

  // 6. An interrupted attempt is reported as incomplete and blocks another attempt for that capture.
  await fillEvent("Interrupted attempt probe event");
  await click(".intake-confirm input");
  const interruptedBefore = posts("/mock-drafts");
  await click(approve);
  check("interrupted: the attempt is reported as incomplete",
    await waitFor(`document.querySelector(".intake-attempt")?.dataset.state === "incomplete"`));
  const interrupted = folder("tracker-attempts", folder("intake").at(-1));
  check("interrupted: what was written is kept, with no response or manifest",
    interrupted.includes("reservation.json") && !interrupted.includes("response.json") &&
    !interrupted.includes("manifest.json"));
  check("interrupted: approving again is not offered and nothing was sent again",
    !(await approveOffered()) && posts("/mock-drafts") === interruptedBefore + 1 &&
    !(await listedHeadlines()).includes("Interrupted attempt probe event"));

  // 7. A mock refusal is reviewable, and its saved review survives a refresh.
  await fillEvent("Refusal event");
  await evaluate(`document.querySelectorAll(".intake-mock-choice input")[1].click()`);
  await click(".intake-confirm input");
  await click(approve);
  check("refusal: the mock refusal opens in the review screen",
    await waitFor(`${panelShows("Refusal event")} && !!document.querySelector(${JSON.stringify(notes)})`, 15000));
  const refusalDraft = (await evaluate("location.search")).slice(7);
  await evaluate(`[...document.querySelectorAll(".review-status input")][1].click()`);
  await setValue(notes, "Refusal reviewed.");
  await click(".review-save-bar button");
  await waitFor(`!!document.querySelector(".review-message.is-saved")`);
  await open(`/?draft=${refusalDraft}`);
  check("refusal: after a refresh it is still reviewable with its saved version",
    await waitFor(`document.querySelector(".review-dirty")?.textContent === "All changes saved · version 1"`) &&
    (await notesValue()) === "Refusal reviewed." && (await text(".draft-outcome .outcome-chip")) === "No draft");

  // 8. The documented prepare-drafts step leaves every Tracker draft and its reviews reachable.
  const tracker = (await listedHeadlines()).filter((headline) => headline !== PILOT).sort();
  const prepared = spawnSync(python, ["-m", "second_order", "prepare-drafts", "--attempt", join(served, "pilot", "draft"),
    "--attempt", join(served, "pilot", "no-draft"), "--out", join(served, "prepared-drafts")],
  { cwd: repo, encoding: "utf-8" });
  check("prepare-drafts: the documented command succeeds", prepared.status === 0, prepared.stderr);
  await open(`/?draft=${firstDraft}`);
  await waitFor(`document.querySelectorAll(".draft-choice").length > 0`);
  const after = (await listedHeadlines()).filter((headline) => headline !== PILOT).sort();
  check("prepare-drafts: every Tracker draft is still listed",
    tracker.length === 6 && JSON.stringify(after) === JSON.stringify(tracker), JSON.stringify({ tracker, after }));
  check("prepare-drafts: the first draft still opens with its saved review",
    await waitFor(`document.querySelector(".review-dirty")?.textContent === "All changes saved · version 1"`) &&
    (await notesValue()) === "Reviewed through the Tracker interface.");

  // 9. The publication time is explicit: the browser's own time zone never changes the saved instant.
  const zoneRuns = [];
  for (const zone of ["America/Los_Angeles", "Asia/Tokyo"]) {
    await send("Emulation.setTimezoneOverride", { timezoneId: zone });
    await open("/");
    const active = await evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone");
    await fillEvent("Time zone check", "Synthetic text for the time zone check.",
                    { date: "2026-09-15", time: "14:00", offset: "-04:00" });
    const requestText = await evaluate(`document.querySelector(".intake-request pre").textContent`);
    zoneRuns.push({ zone, active, ...(await shownTimes()), hash: await requestHash(),
                    inRequest: requestText.includes("Published at (UTC): 2026-09-15T18:00:00Z") });
  }
  check("time zones: the overrides took effect in the browser",
    zoneRuns.every((run) => run.active === run.zone), JSON.stringify(zoneRuns));
  check("time zones: the preview shows the supplied time and its UTC instant in both browser zones",
    zoneRuns.every((run) => run.supplied === "2026-09-15T14:00:00-04:00" && run.utc === "2026-09-15T18:00:00Z" &&
      run.inRequest), JSON.stringify(zoneRuns));
  check("time zones: both browser zones saved the identical request",
    zoneRuns[0].hash.length === 64 && zoneRuns[0].hash === zoneRuns[1].hash, JSON.stringify(zoneRuns));

  await fillEvent("Late evening in New York", "Synthetic text published late in the evening.",
                  { date: "2026-09-15", time: "22:30", offset: "-04:00" });
  check("time zones: an evening time crosses midnight to the next UTC date",
    JSON.stringify(await shownTimes()) ===
      JSON.stringify({ supplied: "2026-09-15T22:30:00-04:00", utc: "2026-09-16T02:30:00Z" }));
  await click(".intake-confirm input");
  await click(approve);
  await waitFor(panelShows("Late evening in New York"), 15000);
  const lateCapture = folder("intake").at(-1);
  check("time zones: the attempt copied the saved request carrying that instant",
    readFileSync(join(served, "intake", lateCapture, "request.json"))
      .equals(readFileSync(join(served, "tracker-attempts", lateCapture, "request.json"))) &&
    readFileSync(join(served, "tracker-attempts", lateCapture, "request.json"), "utf8")
      .includes("Published at (UTC): 2026-09-16T02:30:00Z"));
  check("time zones: the review screen shows the same UTC publication time",
    (await bodyText()).includes("16 Sep 2026, 02:30 UTC"));

  const capturesBefore = folder("intake").length;
  await fillForm("No offset chosen", "Synthetic text without an offset.", { offset: "" });
  await sleep(300);
  check("time zones: without an explicit offset nothing is captured",
    await evaluate(`document.querySelector(".intake-time select").validity.valueMissing`) &&
    !(await evaluate(`!!document.querySelector(".intake-preview")`)) && folder("intake").length === capturesBefore);
  await send("Emulation.setTimezoneOverride", { timezoneId: "" });

  const outside = requests.filter((request) => !request.url.startsWith(base) && !request.url.startsWith("data:") &&
    request.url !== "about:blank");
  check("the page requested nothing outside the local server", outside.length === 0,
    outside.map((request) => request.url).join(", "));
  ws.close();
} catch (error) {
  check("the intake browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(500);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
