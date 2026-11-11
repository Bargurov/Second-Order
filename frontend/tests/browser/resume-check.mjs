// Browser acceptance check for resuming a saved event: capture it, reload the page and reopen the same capture
// from the saved-events list; refresh it after the server restarts with paid sending enabled; approve and send
// it once to a simulated provider and review the result. Then an attempted, an unreadable and an invalid capture,
// a failed refresh and an out-of-order reply. Opening and refreshing must be reads only, and an approval never
// survives either. The server is tests/review_browser_server.py over one temporary folder: first mock-only, then
// restarted with --simulated-provider --keep-records (a dummy key and an in-process fake; no network).
//
//   cd frontend; npm run build; npm run test:browser:resume
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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
const root = mkdtempSync(join(tmpdir(), "second-order-resume-check-"));
const served = join(root, "served");
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const folder = (...parts) => (existsSync(join(served, ...parts)) ? readdirSync(join(served, ...parts)).sort() : []);
const everyFile = (path) => readdirSync(path, { withFileTypes: true }).flatMap((entry) =>
  entry.isDirectory() ? everyFile(join(path, entry.name)) : [join(path, entry.name)]);
/** Every served file with its SHA-256: equal snapshots mean nothing was written, replaced or removed. */
const snapshot = () => JSON.stringify(everyFile(served).sort().map((path) =>
  [relative(served, path), createHash("sha256").update(readFileSync(path)).digest("hex")]));

try {
  mkdirSync(served);
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;
  let server = null;
  const startServer = async (options) => {
    server = spawn(python, [join(repo, "tests/review_browser_server.py"), "--root", served, "--port", String(port),
      ...options], { cwd: repo, stdio: ["ignore", "inherit", "inherit"] });
    children.push(server);
    for (let i = 0; i < 150; i++) {
      try { if ((await fetch(`${base}/api/drafts`)).ok) return; } catch { /* starting */ }
      await sleep(200);
    }
    throw new Error("The review server did not start.");
  };
  const stopServer = async () => {
    const exited = new Promise((done) => server.once("exit", done));
    server.kill();
    await exited;
  };
  await startServer([]);  // Mock only, as `python -m second_order serve` runs by default.

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

  // Every request the page makes is recorded; confirm() answers are "no" and counted; unloads are allowed.
  const requests = [];
  const dialogs = [];
  listeners.push((message) => {
    if (message.method === "Network.requestWillBeSent") {
      requests.push({ url: message.params.request.url, method: message.params.request.method });
    } else if (message.method === "Page.javascriptDialogOpening") {
      if (message.params.type !== "beforeunload") dialogs.push(message.params.message);
      send("Page.handleJavaScriptDialog", { accept: message.params.type === "beforeunload" });
    }
  });
  // Paused requests are held or failed according to `fetchMode`.
  const held = [];
  let fetchMode = "fail";
  listeners.push((message) => {
    if (message.method !== "Fetch.requestPaused") return;
    const { requestId } = message.params;
    if (fetchMode === "hold") held.push(requestId);
    else send("Fetch.failRequest", { requestId, errorReason: "ConnectionReset" });
  });
  const intercept = (urlPattern, mode) => {
    fetchMode = mode;
    return send("Fetch.enable", { patterns: [{ urlPattern, requestStage: "Request" }] });
  };
  const posts = (part) => requests.filter((request) => request.method === "POST" && request.url.includes(part)).length;
  /** Requests made since `mark`, as "METHOD /path". */
  const since = (mark) => requests.slice(mark).map(({ method, url }) => `${method} ${url.slice(base.length)}`);
  const onlyReads = (mark) => since(mark).every((request) => request.startsWith("GET "));

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete'");
  };
  const fillEvent = async (headline) => {
    if (await evaluate(`!!document.querySelector(".intake-preview")`)) await click(".intake-preview .button-quiet");
    await waitFor(`!!document.querySelector(".intake-form")`);
    await setValue('.intake-form input:not([type="url"]):not([type="date"]):not([type="time"])', headline);
    await setValue('.intake-form input[type="url"]', "https://example.test/policy-statement");
    await setValue('.intake-form input[type="date"]', "2026-09-15");
    await setValue('.intake-form input[type="time"]', "14:00");
    await setValue(".intake-time select", "-04:00");
    await setValue(".intake-form textarea", `Synthetic published text for ${headline}.`);
    await click(".intake-form button[type=submit]");
    await waitFor(`!!document.querySelector(".intake-preview")`);
    return shownCapture();
  };
  const shownCapture = () => evaluate(`[...document.querySelectorAll(".intake-facts code")][0]?.textContent ?? ""`);
  const shownHash = () => evaluate(`[...document.querySelectorAll(".intake-facts code")][1]?.textContent ?? ""`);
  const savedRequest = (capture) => readFileSync(join(served, "intake", capture, "request.json"));
  const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
  const row = (capture) => `.intake-saved-list li[data-capture="${capture}"]`;
  const listed = (capture) => waitFor(`!!document.querySelector(${JSON.stringify(row(capture))})`);
  const settled = `!!document.querySelector(".intake-preview") &&
    document.querySelector(".intake-refresh-button")?.textContent === "Refresh saved preview"`;
  /** Reopen a capture from the saved-events list; resolves once its verified preview is shown. */
  const reopen = async (capture) => {
    await listed(capture);
    await click(`${row(capture)} .intake-reopen`);
    return waitFor(`${settled} && [...document.querySelectorAll(".intake-facts code")][0]?.textContent === ${JSON.stringify(capture)}`);
  };
  /** Refresh the preview shown; resolves once both reads were made and the page has settled. */
  const refresh = async (capture) => {
    const mark = requests.length;
    await click(".intake-refresh-button");
    await until(() => since(mark).includes(`GET /api/intake/${capture}/attempt`));
    return waitFor(settled);
  };
  const isChecked = (selector) => evaluate(`!!document.querySelector(${JSON.stringify(selector)})?.checked`);
  const isEnabled = (selector) => evaluate(`(() => { const e = document.querySelector(${JSON.stringify(selector)});
    return !!e && !e.disabled && !e.closest("fieldset:disabled"); })()`);
  const mockApprove = ".intake-preview .intake-actions .button:not(.button-quiet)";
  const sendPaid = ".intake-send-paid";
  const choosePaid = () => click('.intake-source-choice input[value="paid"]');
  const mockSelected = () => isChecked('.intake-source-choice input[value="mock"]');
  const attemptState = () => evaluate(`document.querySelector(".intake-attempt")?.dataset.state ?? null`);
  const calls = () => folder("simulated-provider").filter((name) => name.startsWith("request-")).length;
  const panelShows = (headline) => `document.querySelector(".draft-panel h3")?.textContent === ${JSON.stringify(headline)}`;
  const notes = ".human-review .review-field textarea";

  // 1. Capture an event, reload the page and reopen that same capture from the list, with reads only.
  await open("/");
  check("the saved-events list loads, empty, with the form",
    await waitFor(`document.querySelector(".intake-saved-state")?.textContent === "No saved events yet."`) &&
    await evaluate(`!!document.querySelector(".event-intake .intake-form")`));
  const first = await fillEvent("Resume probe event");
  const firstHash = await shownHash();
  const firstBytes = savedRequest(first);
  check("a capture shows its saved request hash", firstHash === sha256(firstBytes) && /^[a-f0-9]{64}$/.test(firstHash));
  await open("/");
  check("after a reload the capture is gone from view but listed under Saved events",
    !(await evaluate(`!!document.querySelector(".intake-preview")`)) && await listed(first) &&
    (await text(row(first))).includes("Resume probe event") && (await text(row(first))).includes(firstHash.slice(0, 12)));
  let before = snapshot();
  let mark = requests.length;
  check("the same capture reopens from the list", await reopen(first));
  check("reopened: the same capture ID, request hash and unchanged saved bytes",
    (await shownCapture()) === first && (await shownHash()) === firstHash && savedRequest(first).equals(firstBytes) &&
    (await text(".intake-time-supplied strong")) === "2026-09-15T14:00:00-04:00" &&
    (await text(".intake-time-utc strong")) === "2026-09-15T18:00:00Z");
  check("reopening reads only: the preview and the attempt state, no dispatch, reservation or file change",
    onlyReads(mark) && since(mark).includes(`GET /api/intake/${first}`) &&
    since(mark).includes(`GET /api/intake/${first}/attempt`) && snapshot() === before && folder("tracker-attempts").length === 0,
    since(mark).join(", "));
  check("on the mock-only server paid sending is unavailable and the local mock is selected",
    await mockSelected() && !(await isEnabled('.intake-source-choice input[value="paid"]')) &&
    !(await isChecked(".intake-confirm input")) && !(await isEnabled(mockApprove)));

  // 2. An approval does not survive a refresh, and a refresh is a read.
  await click(".intake-confirm input");
  check("a mock approval can be ticked on the reopened capture", await isEnabled(mockApprove));
  mark = requests.length;
  await refresh(first);
  check("a refresh clears the mock approval and keeps the local mock selected",
    !(await isChecked(".intake-confirm input")) && !(await isEnabled(mockApprove)) && await mockSelected());
  check("refreshing reads only and changes no file", onlyReads(mark) && snapshot() === before, since(mark).join(", "));

  // 3. The server restarts with paid sending enabled; refreshing the open preview shows it without recapturing.
  await stopServer();
  await startServer(["--simulated-provider", "--keep-records"]);
  check("before a refresh the page still shows the availability it last read",
    !(await isEnabled('.intake-source-choice input[value="paid"]')));
  before = snapshot();
  mark = requests.length;
  await refresh(first);
  check("after a refresh paid sending is available, yet the local mock stays selected and nothing is approved",
    await isEnabled('.intake-source-choice input[value="paid"]') && await mockSelected() &&
    !(await evaluate(`!!document.querySelector(".paid-confirm")`)));
  check("the refreshed preview is the same saved request; nothing was captured, sent or written",
    (await shownCapture()) === first && (await shownHash()) === firstHash && onlyReads(mark) && snapshot() === before &&
    folder("intake").length === 1 && calls() === 0, since(mark).join(", "));
  await choosePaid();
  await click(".paid-confirm input");
  check("a paid approval can be ticked once paid sending is offered", await isEnabled(sendPaid));
  await refresh(first);
  await choosePaid();
  check("a refresh clears the paid approval and returns to the local mock",
    !(await isChecked(".paid-confirm input")) && !(await isEnabled(sendPaid)));
  await click(".paid-confirm input");
  await open("/");
  await reopen(first);
  await choosePaid();
  check("reopening after a reload clears the paid approval too",
    !(await isChecked(".paid-confirm input")) && !(await isEnabled(sendPaid)) && calls() === 0);

  // 4. The reopened capture completes its flow: one approved paid send to the simulated provider, then a review.
  await click(".paid-confirm input");
  await click(sendPaid);
  check("the reopened capture's paid result opens for review",
    await waitFor(`${panelShows("Resume probe event")} && !!document.querySelector(${JSON.stringify(notes)})`, 15000));
  check("exactly one dispatch, carrying the saved request bytes unchanged",
    calls() === 1 && posts("/paid-drafts") === 1 && posts("/mock-drafts") === 0 &&
    readFileSync(join(served, "simulated-provider", "request-1.json")).equals(firstBytes));
  const draft = (await evaluate("location.search")).slice(7);
  await evaluate(`[...document.querySelectorAll(".review-status input")][1].click()`);
  await setValue(notes, "Reviewed the reopened capture's draft.");
  await click(".review-save-bar button");
  await waitFor(`!!document.querySelector(".review-message.is-saved")`);
  await open(`/?draft=${draft}`);
  check("the human review survives a refresh",
    await waitFor(`document.querySelector(".review-dirty")?.textContent === "All changes saved · version 1"`));

  // 5. Reopening an attempted capture never offers another dispatch, and never disturbs unsaved review edits.
  await setValue(notes, "Unsaved edit while reopening.");
  const dialogsBefore = dialogs.length;
  check("the attempted capture reopens showing its recorded result", await reopen(first) &&
    (await attemptState()) === "ready" && (await text(".intake-attempt")).includes("The model proposed a draft"));
  check("neither mode can dispatch it again, also after a refresh",
    !(await isEnabled(mockApprove)) && !(await isEnabled('.intake-source-choice input[value="paid"]')) &&
    await refresh(first) && (await attemptState()) === "ready" && !(await isEnabled(mockApprove)) &&
    calls() === 1 && posts("/paid-drafts") === 1);
  check("reopening left the open review and its unsaved edit alone, without a prompt",
    dialogs.length === dialogsBefore &&
    (await evaluate(`document.querySelector(${JSON.stringify(notes)})?.value`)) === "Unsaved edit while reopening.");
  await setValue(notes, "Reviewed the reopened capture's draft.");

  // 6. A failed refresh marks the preview stale and blocks approval until a refresh succeeds.
  const second = await fillEvent("Second resume event");
  await click(".intake-confirm input");
  await intercept(`*/api/intake/${second}`, "fail");
  await click(".intake-refresh-button");
  check("a failed refresh says the preview may be out of date and blocks approval",
    await waitFor(`!!document.querySelector(".intake-stale")`) &&
    (await text(".intake-stale")).includes("could not be refreshed") && !(await isEnabled(mockApprove)) &&
    !(await isEnabled(".intake-confirm input")) && !(await isChecked(".intake-confirm input")));
  await send("Fetch.disable");
  check("a later successful refresh clears the stale mark", await refresh(second) &&
    !(await evaluate(`!!document.querySelector(".intake-stale")`)) && await isEnabled(".intake-confirm input"));

  // 7. An attempt state that cannot be read is never taken as "no attempt".
  await open("/");
  await intercept(`*/api/intake/${second}/attempt`, "fail");
  await listed(second);
  await click(`${row(second)} .intake-reopen`);
  check("an unreadable attempt state is reported, and nothing can be approved",
    await waitFor(`document.querySelector(".intake-attempt")?.dataset.state === "unreadable"`) &&
    !(await isEnabled(".intake-confirm input")) && !(await isEnabled(mockApprove)) &&
    (await text(".intake-message")).includes("could not be read"));
  await send("Fetch.disable");

  // 8. An invalid capture or attempt cannot dispatch.
  const third = await fillEvent("Tampered resume event");
  const source = join(served, "intake", third, "source.txt");
  chmodSync(source, 0o666);
  writeFileSync(source, "Altered after capture.");
  await click(".intake-refresh-button");
  check("refreshing a capture whose saved files no longer verify marks it stale and blocks approval",
    await waitFor(`!!document.querySelector(".intake-stale")`) && !(await isEnabled(".intake-confirm input")));
  await open("/");
  check("a capture that does not verify is listed as such, without an Open action",
    await listed(third) && await evaluate(`document.querySelector(${JSON.stringify(row(third))}).classList.contains("is-refused")`) &&
    !(await evaluate(`!!document.querySelector(${JSON.stringify(`${row(third)} .intake-reopen`)})`)));
  const attemptRequest = join(served, "tracker-attempts", first, "request.json");
  writeFileSync(attemptRequest, Buffer.concat([readFileSync(attemptRequest), Buffer.from(" ")]));
  check("an attempt whose records no longer verify reopens as invalid, and nothing can be approved",
    await reopen(first) && (await attemptState()) === "invalid" && !(await isEnabled(mockApprove)) &&
    !(await isEnabled('.intake-source-choice input[value="paid"]')));

  // 9. An older reply never replaces a newer selection.
  const fourth = await fillEvent("Fourth resume event");
  await open("/");
  await listed(second);
  await intercept(`*/api/intake/${second}`, "hold");
  await click(`${row(second)} .intake-reopen`);
  await until(() => held.length === 1);
  check("the newer selection opens while the older reply is still held", held.length === 1 && await reopen(fourth));
  mark = requests.length;
  for (const requestId of held.splice(0)) await send("Fetch.continueRequest", { requestId });
  await until(() => since(mark).includes(`GET /api/intake/${second}/attempt`));
  await sleep(500);
  check("the older reply, once it arrives, does not replace the newer selection",
    (await shownCapture()) === fourth && (await text(".intake-facts")).includes(fourth) && await evaluate(settled) &&
    !(await evaluate(`!!document.querySelector(".intake-stale")`)) && !(await isChecked(".intake-confirm input")));
  await send("Fetch.disable");

  check("over the whole check: one dispatch, no mock dispatch, and no capture created by opening or refreshing",
    calls() === 1 && posts("/paid-drafts") === 1 && posts("/mock-drafts") === 0 && posts("/publish") === 0 &&
    posts("/api/intake") - posts("/api/intake/") === 4 && folder("intake").length === 4);
  const outside = requests.filter((request) => !request.url.startsWith(base) && !request.url.startsWith("data:") &&
    request.url !== "about:blank");
  check("the page requested nothing outside the local server", outside.length === 0,
    outside.map((request) => request.url).join(", "));
  ws.close();
} catch (error) {
  check("the resume browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(500);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
