// Browser acceptance check for the simulated paid path: event form -> exact request preview -> cost decision ->
// explicit paid approval -> one call to a simulated provider -> the recorded draft, refusal or failure in the
// existing review screen -> a saved human review. Then a timeout, a lost reply, a credential echo and the mock
// staying the default. The server is tests/review_browser_server.py --simulated-provider: paid sending with a
// dummy key and an in-process fake of the Claude API (no network). No real provider or credential is used.
//
//   cd frontend; npm run build; npm run test:browser:paid
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
const root = mkdtempSync(join(tmpdir(), "second-order-paid-check-"));
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

  // Records of the simulated provider: what it received for each call, and how many calls there were.
  const calls = () => folder("simulated-provider").filter((name) => name.startsWith("request-")).length;
  const received = (number) => JSON.parse(readFileSync(join(served, "simulated-provider", `received-${number}.json`), "utf8"));
  const receivedBody = (number) => readFileSync(join(served, "simulated-provider", `request-${number}.json`));
  const savedRequest = () => readFileSync(join(served, "intake", folder("intake").at(-1), "request.json"));
  const manifestOf = () => JSON.parse(readFileSync(join(served, "tracker-attempts", folder("intake").at(-1),
                                                        "manifest.json"), "utf8"));
  const sendPaid = ".intake-send-paid";
  const paidOffered = () => evaluate(`(() => { const b = document.querySelector(${JSON.stringify(sendPaid)});
    return !!b && !b.disabled; })()`);
  const choosePaid = () => evaluate(`document.querySelector('.intake-source-choice input[value="paid"]').click()`);
  const DUMMY_KEY = "sk-ant-dummy-simulated-key-not-real-00000000";
  const everyFile = (folderPath) => readdirSync(folderPath, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? everyFile(join(folderPath, entry.name)) : [join(folderPath, entry.name)]);
  const paidEvent = async (headline) => {
    await fillEvent(headline);
    await choosePaid();
    await click(".paid-confirm input");
    await click(sendPaid);
  };

  // 1. The cost decision: the mock is the default; choosing the paid request shows the estimate and its basis.
  await open("/");
  check("paid: the Tracker exposes Analyze an event", await waitFor(`!!document.querySelector(".event-intake .intake-form")`));
  await fillEvent("Paid draft event");
  check("paid: the local mock is still the default response source",
    await evaluate(`document.querySelector('.intake-source-choice input[value="mock"]').checked`) &&
    await evaluate(`!document.querySelector('.intake-source-choice input[value="paid"]').disabled`) &&
    !(await evaluate(`!!document.querySelector(".paid-decision")`)));
  const estimate = await evaluate(`document.querySelector(".intake-estimate strong").textContent.trim()`);
  await choosePaid();
  const decision = await text(".paid-decision");
  check("paid: the cost decision shows the estimate, model, settings and pricing date",
    decision.includes(estimate) && /^\$0\.\d{4}$/.test(estimate) && decision.includes("claude-sonnet-5-5") &&
    decision.includes("medium effort") && decision.includes("16,000") && decision.includes("read on 2026-10-05"),
    decision);
  check("paid: it says the estimate is not a billing ceiling and states its assumptions",
    decision.includes("Not a guaranteed billing ceiling") && decision.includes("2 bytes per token") &&
    decision.includes("286 tool-use system tokens") && decision.includes("$2 per million input tokens") &&
    decision.includes("$10 per million output tokens"));
  check("paid: nothing can be sent before the separate paid approval",
    !(await paidOffered()) && calls() === 0 &&
    (await text(".paid-confirm")).includes(`estimated at up to ${estimate}`));
  await click(".paid-confirm input");
  check("paid: the clearly labelled paid action is offered after approval",
    await paidOffered() && (await text(sendPaid)) === "Send one paid request");
  await click(sendPaid);
  check("paid: the recorded draft opens in the existing review screen",
    await waitFor(`${panelShows("Paid draft event")} && !!document.querySelector(${JSON.stringify(notes)})`, 15000));
  const firstPaid = (await evaluate("location.search")).slice(7);
  const panel = await evaluate(`document.querySelector(".draft-panel").textContent`);
  check("paid: it is attributed to the model, not to the local mock",
    panel.includes("Written by claude-sonnet-5-5") && !panel.includes("Generated by a local mock"));
  check("paid: its provenance shows the provider's request ID and HTTP status",
    panel.includes("req_simulated0001") && panel.includes("200 · draft"));
  check("paid: one call to the simulated provider, carrying exactly the saved request bytes",
    calls() === 1 && receivedBody(1).equals(savedRequest()));
  const first = received(1);
  check("paid: the call went to the Messages API with the documented headers",
    first.url_is_messages_api && first.x_api_key_is_the_dummy_key && first.anthropic_version === "2023-06-01" &&
    first.content_type === "application/json", JSON.stringify(first));
  check("paid: the manifest records the request ID, status and usage-based cost, nothing invented",
    (() => { const m = manifestOf(); return m.request_id === "req_simulated0001" && m.http_status === 200 &&
      m.estimated_cost?.usd === 0.0084 && m.retries === 0 && m.attempts === 1; })());
  await evaluate(`[...document.querySelectorAll(".review-status input")][1].click()`);
  await setValue(notes, "Reviewed the paid draft.");
  await click(".review-save-bar button");
  check("paid: a human review is saved", await waitFor(`!!document.querySelector(".review-message.is-saved")`));
  await open(`/?draft=${firstPaid}`);
  check("paid: after a refresh the draft and its review remain",
    await waitFor(`document.querySelector(".review-dirty")?.textContent === "All changes saved · version 1"`) &&
    (await notesValue()) === "Reviewed the paid draft.");

  // 2. A refusal, an invalid response and a provider error each open for review; nothing is retried.
  await paidEvent("Simulated refusal event");
  check("paid refusal: the model's decline opens for review",
    await waitFor(`${panelShows("Simulated refusal event")} && document.querySelector(".draft-outcome .outcome-chip")?.textContent === "No draft"`, 15000));
  await evaluate(`[...document.querySelectorAll(".review-status input")][1].click()`);
  await setValue(notes, "Reviewed the refusal.");
  await click(".review-save-bar button");
  await waitFor(`!!document.querySelector(".review-message.is-saved")`);
  const refusal = (await evaluate("location.search")).slice(7);
  await open(`/?draft=${refusal}`);
  check("paid refusal: its review survives a refresh",
    await waitFor(`document.querySelector(".review-dirty")?.textContent === "All changes saved · version 1"`));
  await paidEvent("Simulated invalid response event");
  check("paid invalid: the contract failure opens for review without its content",
    await waitFor(`${panelShows("Simulated invalid response event")} && document.querySelector(".draft-outcome .outcome-chip")?.textContent === "Invalid response"`, 15000));
  await paidEvent("Simulated provider error event");
  check("paid provider error: the failure opens with the provider's status",
    await waitFor(panelShows("Simulated provider error event"), 15000) &&
    (await text(".draft-panel")).includes("HTTP 529 (overloaded_error)"));
  check("paid: one call per approved capture so far, never a retry", calls() === 4);

  // 3. A timeout after sending is an unknown outcome: reported as possibly billed, and never sent again.
  await paidEvent("Simulated timeout event");
  check("paid timeout: the failure opens and says the outcome is unknown and may be billed",
    await waitFor(panelShows("Simulated timeout event"), 15000) &&
    (await text(".draft-panel")).includes("outcome is unknown") &&
    (await text(".intake-message")).includes("may have received and billed"));
  check("paid timeout: approving again is not offered and the call was made once",
    !(await paidOffered()) && calls() === 5);

  // 4. A lost reply is settled by reading what was recorded; the paid request is not sent again.
  await fillEvent("Paid lost reply event");
  await choosePaid();
  await click(".paid-confirm input");
  await intercept("*/paid-drafts", "Response", "fail");
  await click(sendPaid);
  check("paid lost reply: the page reads the saved records and opens the result",
    await waitFor(panelShows("Paid lost reply event"), 15000) &&
    (await text(".intake-attempt")).includes("reply was lost"));
  await send("Fetch.disable");
  fetchMode = "pass";
  check("paid lost reply: one call to the provider and one POST, no second attempt",
    calls() === 6 && posts("/paid-drafts") === 6 && !(await paidOffered()));

  // 5. A reply that echoes the credential is not kept, and the dummy key appears in no saved file.
  await paidEvent("Simulated credential echo event");
  check("paid credential echo: the failure opens and nothing from the reply was kept",
    await waitFor(panelShows("Simulated credential echo event"), 15000) &&
    (await text(".draft-panel")).includes("contained the credential") &&
    !folder("tracker-attempts", folder("intake").at(-1)).includes("response.json"));
  const carrying = everyFile(served).filter((path) => readFileSync(path).includes(DUMMY_KEY));
  check("paid: no saved file anywhere contains the key", carrying.length === 0, carrying.join(", "));

  // 6. The mock remains the default and still works; one capture never gets a second attempt in either mode.
  await fillEvent("Mock after paid event");
  check("mock: a new capture starts with the local mock selected",
    await evaluate(`document.querySelector('.intake-source-choice input[value="mock"]').checked`));
  await click(".intake-confirm input");
  await click(approve);
  check("mock: the mock draft opens, labelled as a local mock",
    await waitFor(panelShows("Mock after paid event"), 15000) &&
    (await text(".draft-panel")).includes("Generated by a local mock"));
  check("mock: neither a paid request nor a second mock is offered for that capture",
    !(await approveOffered()) &&
    await evaluate(`document.querySelector('.intake-source-choice').disabled`) && calls() === 7);

  const outside = requests.filter((request) => !request.url.startsWith(base) && !request.url.startsWith("data:") &&
    request.url !== "about:blank");
  check("the page requested nothing outside the local server", outside.length === 0,
    outside.map((request) => request.url).join(", "));
  ws.close();
} catch (error) {
  check("the paid browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(500);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
