// Browser acceptance check for the evidence-first research analysis, in one headless Chrome against
// tests/review_browser_server.py --simulated-provider: paid sending with a dummy key and an in-process fake of the
// Claude API that answers research requests with SYNTHETIC replies quoting the request's own captured text. No real
// provider, network or credential is used. Simulated replies verify the workflow, not the quality of an analysis.
//
// The journey: capture an event in the Tracker -> the preview offers an explicit analysis mode, the hypothesis draft
// by default -> choosing the research analysis hides the hypothesis approvals and links to the research page -> the
// page prepares nothing on load -> one explicit preparation writes a separate request (the capture's own request
// unchanged) -> reloading sends nothing -> one explicit paid approval sends those exact bytes once -> the source's
// quoted words, the interpretation and the unknowns appear as separate, differently styled sections, with the quoted
// passages marked in the captured text -> one review version saved and still there after a reload -> the event
// overview's history lists the prepared request, the result and the review, and the hypothesis attempt stays unused ->
// a reply whose quote is not in the source is refused as a whole -> a mock decline is labelled synthetic -> no second
// attempt is possible -> only explicit writes, nothing requested outside the local server, no key in any file.
//
//   cd frontend; npm run build; npm run test:browser:research-analysis
import { spawn } from "node:child_process";
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

const SOURCE = "September 16, 2026\n\nSimulated committee issues statement\n\nThe Committee decided to raise the " +
  "target range by 1/4 percentage point, in support of the Committee\u2019s goals.\n\nEconomic activity is expanding " +
  "at a solid pace. Inflation remains elevated.";
const QUOTED = ["The Committee decided to raise the target range by 1/4 percentage point, in support of the Committee\u2019s goals.",
  "Economic activity is expanding at a solid pace. Inflation remains elevated."];
const DUMMY_KEY = "sk-ant-dummy-simulated-key-not-real-00000000";
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done) => {
  const server = createServer().listen(0, "127.0.0.1", () => {
    const { port } = server.address();
    server.close(() => done(port));
  });
});
const root = mkdtempSync(join(tmpdir(), "second-order-research-analysis-check-"));
const served = join(root, "served");
const profile = join(root, "chrome");
const children = [];
const results = [];
const check = (name, ok, detail = "") => {
  results.push(ok);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail && !ok ? `  (${detail})` : ""}`);
};
const folder = (...parts) => (existsSync(join(served, ...parts)) ? readdirSync(join(served, ...parts)).sort() : []);
const sha = (path) => createHash("sha256").update(readFileSync(path)).digest("hex");
const everyFile = (path) => readdirSync(path, { withFileTypes: true }).flatMap((entry) =>
  entry.isDirectory() ? everyFile(join(path, entry.name)) : [join(path, entry.name)]);

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
  const exists = (selector) => evaluate(`!!document.querySelector(${JSON.stringify(selector)})`);
  const text = (selector) => evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent ?? ""`);
  const texts = (selector) => evaluate(`[...document.querySelectorAll(${JSON.stringify(selector)})]
    .map((element) => element.textContent)`);

  const requests = [];
  const errors = [];
  listeners.push((message) => {
    if (message.method === "Network.requestWillBeSent") {
      requests.push({ url: message.params.request.url, method: message.params.request.method });
    } else if (message.method === "Runtime.exceptionThrown") {
      errors.push(message.params.exceptionDetails.text);
    } else if (message.method === "Log.entryAdded" && message.params.entry.level === "error") {
      errors.push(`${message.params.entry.text} ${message.params.entry.url ?? ""}`);
    }
  });
  const posts = (part) => requests.filter((request) => request.method === "POST" && request.url.includes(part)).length;
  const calls = () => folder("simulated-provider").filter((name) => name.startsWith("request-")).length;

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Log.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const open = async (path) => {
    await send("Page.navigate", { url: base + path });
    await waitFor("document.readyState === 'complete'");
  };
  const captureEvent = async (headline, source = SOURCE) => {
    await open("/");
    await waitFor(`!!document.querySelector(".intake-form")`);
    await setValue('.intake-form input:not([type="url"]):not([type="date"]):not([type="time"])', headline);
    await setValue('.intake-form input[type="url"]', "https://example.test/policy-statement");
    await setValue('.intake-form input[type="date"]', "2026-09-16");
    await setValue('.intake-form input[type="time"]', "14:00");
    await setValue(".intake-time select", "-04:00");
    await setValue(".intake-form textarea", source);
    await click(".intake-form button[type=submit]");
    await waitFor(`!!document.querySelector(".intake-preview")`);
  };
  const openResearch = async () => {
    await click('.intake-mode-choice input[value="research"]');
    await waitFor(`!!document.querySelector(".intake-open-research")`);
    await click(".intake-open-research");
    await waitFor(`location.pathname.endsWith("/research") && !!document.querySelector("#research-prepare, #research-request")`);
    return evaluate("decodeURIComponent(location.pathname.split('/')[3])");
  };
  const prepare = async () => {
    await click(".research-prepare");
    return waitFor(`!!document.querySelector("#research-request")`);
  };

  // 1. The saved event offers an explicit analysis mode; the hypothesis draft stays the default and is unchanged.
  await captureEvent("Simulated research statement");
  check("the preview offers an explicit analysis mode with the hypothesis draft selected",
    await evaluate(`document.querySelector('.intake-mode-choice input[name="analysis-mode"]').checked`) &&
    await exists(".intake-source-choice") && !(await exists(".intake-mode-research")));
  await click('.intake-mode-choice input[value="research"]');
  check("choosing the research analysis hides the hypothesis approvals and only links to its own page",
    await waitFor(`!!document.querySelector(".intake-open-research")`) && !(await exists(".intake-source-choice")) &&
    !(await exists(".intake-confirm")) && posts("/api/research-analyses") === 0);
  const captureId = await openResearch();
  const captureRequest = join(served, "intake", captureId, "request.json");
  const captureHash = sha(captureRequest);
  check("the research page prepares nothing on load and says there is no analysis yet",
    (await text("#research-prepare")).includes("there is no analysis") && posts("/api/research-analyses") === 0 &&
    folder("research-analyses").length === 0);

  // 2. One explicit preparation writes a separate request; the capture's own request is untouched.
  check("one explicit preparation shows the prepared request", await prepare());
  const requestId = `${captureId}.research-prompt-2`;
  const savedRequest = join(served, "research-analyses", "requests", requestId, "request.json");
  check("the request is shown as prepared, not as an analysis",
    (await text(".research-status")).includes("Prepared · Nothing sent") &&
    (await text(".research-status")).includes("A prepared request is not an analysis") &&
    !(await exists("#research-result")) && !(await exists("#research-established")));
  check("the shown SHA-256 is the saved research request's, and the capture's own request is unchanged",
    (await text(".research-sha")) === sha(savedRequest) && sha(captureRequest) === captureHash &&
    sha(savedRequest) !== captureHash, await text(".research-sha"));
  check("the cost decision states its assumptions and the output limit for this mode",
    (await text("#research-request .intake-preview-head")).includes("16,000 tokens") &&
    await evaluate(`!document.querySelectorAll('input[name="research-source"]')[1].disabled`));
  await open(`/events/capture/${encodeURIComponent(captureId)}/research`);
  await waitFor(`!!document.querySelector("#research-request")`);
  check("reloading the page reads only: nothing prepared, sent or reserved again",
    posts("/api/research-analyses") === 1 && calls() === 0 && folder("research-analyses", "attempts").length === 0 &&
    await exists("#research-send"));

  // 3. One explicit paid approval sends the exact saved bytes once.
  await evaluate(`document.querySelectorAll('input[name="research-source"]')[1].click()`);
  await waitFor(`!!document.querySelector(".research-send-paid")`);
  const blocked = await evaluate(`document.querySelector(".research-send-paid").disabled`);
  check("the paid send names the estimate and is blocked until approved",
    blocked && (await text("#research-send .paid-decision")).includes("Output limit for this mode: 16,000 tokens"));
  await click(".paid-confirm input");
  await click(".research-send-paid");
  check("the recorded result appears", await waitFor(`!!document.querySelector("#research-result")`, 15000));
  const received = JSON.parse(readFileSync(join(served, "simulated-provider", "received-1.json"), "utf8"));
  check("exactly one call carried the saved research request's bytes, with the dummy key in its header",
    calls() === 1 && posts("/paid") === 1 &&
    readFileSync(join(served, "simulated-provider", "request-1.json")).equals(readFileSync(savedRequest)) &&
    received.x_api_key_is_the_dummy_key && received.url_is_messages_api);

  // 4. What the source establishes, the interpretation and the unknowns are separate, differently styled sections.
  check("the outcome is an analysis from a paid model response, not frozen or evaluated",
    (await text(".research-outcome")) === "Analysis recorded" &&
    (await text("#research-result")).includes("Model response · paid") &&
    (await text("#research-result")).includes("Not frozen · not evaluated"));
  check("the established section shows the source's own words, each with a locator",
    JSON.stringify(await texts("#research-established blockquote")) === JSON.stringify(QUOTED) &&
    (await texts("#research-established figcaption")).every((caption) => /^Paragraph \d+, characters \d+–\d+/.test(caption)),
    JSON.stringify(await texts("#research-established blockquote")));
  check("the interpretation is labelled as the model's reading and names the statements it relies on",
    (await text("#research-interpretation .overview-label")) === "The model's reading, not the publisher's words" &&
    (await text("#research-interpretation")).includes("Relies on established statement 1."));
  const styles = await evaluate(`(() => {
    const look = (selector) => { const style = getComputedStyle(document.querySelector(selector));
      return [style.backgroundColor, style.borderTopStyle, style.borderTopColor].join("|"); };
    return [look("#research-established"), look("#research-interpretation"), look("#research-unknowns")];
  })()`);
  check("the three sections look different from one another", new Set(styles).size === 3, styles.join(" / "));
  check("the unknowns name assumptions, competing explanations, missing information, tests and the absent baseline",
    JSON.stringify(await texts("#research-unknowns h3")) ===
      JSON.stringify(["Assumptions", "Competing explanations", "Missing information", "What would test it",
                      "Earlier baseline"]) &&
    (await text("#research-unknowns")).includes("No earlier baseline publication was supplied"));
  check("the captured text marks exactly the quoted passages",
    JSON.stringify(await evaluate(`[...document.querySelectorAll("#research-source mark")]
      .map((mark) => mark.firstChild.textContent)`)) === JSON.stringify(QUOTED));
  check("no send control remains once a response is recorded", !(await exists("#research-send")));

  // 5. One review version, saved explicitly, bound to the result shown, and still there after a reload.
  await evaluate(`document.querySelectorAll('input[name="research-review-status"]')[1].click()`);
  await setValue(".research-notes textarea", "Checked both quotes against the captured text; statement 2 is an assessment.");
  await click(".research-save-review");
  check("one explicit save records version 1",
    await waitFor(`document.querySelector(".research-versions li")?.textContent.includes("Version 1 · Needs revision")`) &&
    posts("/reviews") === 1 && folder("research-analyses", "reviews", requestId).join() === "000001.json");
  const record = JSON.parse(readFileSync(join(served, "research-analyses", "reviews", requestId, "000001.json"), "utf8"));
  await open(`/events/capture/${encodeURIComponent(captureId)}/research`);
  await waitFor(`!!document.querySelector(".research-versions li")`);
  check("after a reload the review is still there, bound to the result shown, and nothing was written on load",
    (await texts(".research-versions li")).length === 1 && posts("/reviews") === 1 &&
    record.binding.request_sha256 === sha(savedRequest) && record.record_version === "research-review-0.1");

  // 6. The event overview's history lists the research steps; the hypothesis request keeps its own unused attempt.
  await open(`/events/capture/${encodeURIComponent(captureId)}`);
  await waitFor(`!!document.querySelector("#overview-research-analysis") && !!document.querySelector(".overview-history-row")`);
  const history = await texts(".overview-history-row .overview-history-label");
  check("the overview links to the research analysis and shows its latest outcome",
    (await text("#overview-research-analysis")).includes("Paid research request: an analysis.") &&
    await exists("#overview-research-analysis .overview-open-research"));
  check("the processing history lists the prepared request, the result and the review",
    history.includes("Research analysis request prepared") && history.includes("Paid research request: an analysis") &&
    history.includes("Research review version 1: Needs revision"), history.join(" | "));
  const hypothesis = await (await fetch(`${base}/api/intake/${captureId}/attempt`)).json();
  check("the hypothesis request was never attempted", hypothesis.state === "none" && folder("tracker-attempts").length === 0);

  // 7. A reply whose quote is not in the captured text is refused as a whole.
  await captureEvent("Simulated research refused quote");
  await openResearch();
  await prepare();
  await evaluate(`document.querySelectorAll('input[name="research-source"]')[1].click()`);
  await click(".paid-confirm input");
  await click(".research-send-paid");
  await waitFor(`!!document.querySelector("#research-result")`, 15000);
  check("a reply quoting text the source does not contain is refused and none of it is shown as analysis",
    (await text(".research-outcome")) === "Refused: the response broke the research contract" &&
    (await text('[data-gap="problem"]')).includes("was not found in the captured text") &&
    !(await exists("#research-established")) && !(await exists("#research-interpretation")) && calls() === 2);

  // 8. A mock decline is labelled synthetic; no second attempt of the same request is possible.
  await captureEvent("Simulated research mock decline");
  const declinedId = `${await openResearch()}.research-prompt-2`;
  await prepare();
  await evaluate(`document.querySelectorAll('input[name="research-mock"]')[2].click()`);
  await click("#research-send .intake-confirm input");
  await click(".research-send-mock");
  await waitFor(`!!document.querySelector("#research-result")`, 15000);
  check("a mock decline is recorded as no analysis, labelled synthetic, with its own words shown apart",
    (await text(".research-outcome")) === "No analysis: declined" && await exists(".research-synthetic") &&
    (await text(".research-model-text")).includes("Mock refusal") && calls() === 2);
  const again = await evaluate(`fetch("/api/research-analyses/${declinedId}/mock", { method: "POST",
    headers: { "Content-Type": "application/json", "X-Second-Order-Research": "1" },
    body: JSON.stringify({ request_sha256: "${sha(join(served, "research-analyses", "requests", declinedId, "request.json"))}",
                           mock_outcome: "analysis" }) }).then((reply) => reply.status)`);
  check("a second attempt of the same request is refused by the server", again === 409 && calls() === 2);

  const carrying = everyFile(served).filter((path) => readFileSync(path).includes(DUMMY_KEY));
  check("no saved file anywhere contains the key", carrying.length === 0, carrying.join(", "));
  const outside = requests.filter((request) => !request.url.startsWith(base) && !request.url.startsWith("data:") &&
    request.url !== "about:blank");
  check("the page requested nothing outside the local server", outside.length === 0,
    outside.map((request) => request.url).join(", "));
  const real = errors.filter((entry) => !/favicon\.ico/.test(entry) && !/status of 409/.test(entry));
  check("no page error", real.length === 0, real.join(" | "));

  if (process.env.SECOND_ORDER_SCREENSHOTS) {  // Bounded per-section clips; never a whole tall page.
    const shoot = async (name, selector) => {
      await evaluate(`document.querySelector(${JSON.stringify(selector)})?.scrollIntoView({ block: "start" })`);
      await sleep(300);
      const box = await evaluate(`(() => { const r = document.querySelector(${JSON.stringify(selector)})
        ?.getBoundingClientRect(); return r && { x: r.left, y: r.top + scrollY, width: r.width,
        height: Math.min(r.height, 2400) }; })()`);
      if (!box) return;
      const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true,
        clip: { ...box, scale: 1 } });
      writeFileSync(join(process.env.SECOND_ORDER_SCREENSHOTS, `${name}.png`), Buffer.from(shot.data, "base64"));
    };
    await open(`/events/capture/${encodeURIComponent(captureId)}/research`);
    await waitFor(`!!document.querySelector("#research-review")`);
    for (const [name, selector] of [["research-request", "#research-request"], ["research-result", "#research-result"],
                                    ["research-established", "#research-established"],
                                    ["research-interpretation", "#research-interpretation"],
                                    ["research-unknowns", "#research-unknowns"], ["research-source", "#research-source"],
                                    ["research-review", "#research-review"]]) {
      await shoot(name, selector);
    }
    await captureEvent("Simulated research mode choice");
    await click('.intake-mode-choice input[value="research"]');
    await waitFor(`!!document.querySelector(".intake-open-research")`);
    await shoot("intake-mode-choice", ".intake-preview");
  }
  ws.close();
} catch (error) {
  check("the research-analysis browser check ran to completion", false, error.stack ?? String(error));
} finally {
  for (const child of children) child.kill();
  await sleep(500);
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}

const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);
